"""Message Batches transport for Anthropic judge calls (opt-in; ``llm`` is the only caller).

The Message Batches API runs ordinary Messages requests asynchronously at half the token price,
outside the account's live rate limits. This module only moves requests: the caller builds each
request's ``params`` exactly as its live call would (minus ``timeout``; a batch request cannot
set ``stream`` or ``fallbacks``), and gets every request's outcome back through ``on_entry``.

* :func:`request_id` names a request by a hash of its ``params``, so the same judge call has the
  same id in every run.
* :func:`run` re-attaches to batches an interrupted run left behind (the :class:`Journal`),
  submits the rest in chunks, polls, and hands each result to ``on_entry(custom_id, result)``:
  ``result`` is the API's result object (``.type`` is ``succeeded`` / ``errored`` / ``canceled``
  / ``expired``; a succeeded one carries ``.message``) or ``None`` when its batch returned
  nothing for it. Whatever is not a clean success is the caller's to re-run live.
* Transient API errors are retried; anything else (a revoked token, no access) is raised.

Nothing here knows about prompts, schemas or caches, so the caller's cache keys and resume
logic are the same under either backend.
"""

import asyncio
import hashlib
import inspect
import json
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_MAX_REQUESTS = 100_000  # per batch (the API's limit)
API_MAX_BYTES = 256_000_000
_TRANSIENT = (408, 409, 429, 500, 502, 503, 504, 520, 529)
_ATTEMPTS = 12
JOURNAL_FILE = "batches.jsonl"


@dataclass(frozen=True)
class Settings:
    """How requests are grouped and watched. ``min_requests``: fewer pending requests than this
    are not worth a batch round trip and stay live (the caller applies it)."""

    max_requests: int = 5_000
    max_bytes: int = 64_000_000
    min_requests: int = 20
    poll_seconds: float = 20.0
    linger_seconds: float = 2.0  # a caller queueing single calls sends them after this much quiet
    journal_dir: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_requests <= API_MAX_REQUESTS:
            raise ValueError(f"batch max_requests must be 1..{API_MAX_REQUESTS}")
        if not 1 <= self.max_bytes <= API_MAX_BYTES:
            raise ValueError(f"batch max_bytes must be 1..{API_MAX_BYTES}")
        if self.poll_seconds <= 0 or self.linger_seconds < 0:
            raise ValueError("batch poll_seconds must be > 0 and linger_seconds >= 0")

    @classmethod
    def from_env(cls, prefix: str) -> "Settings":
        """``<prefix>_MAX_REQUESTS``, ``_MAX_BYTES``, ``_MIN_REQUESTS``, ``_POLL_SECONDS``,
        ``_LINGER_SECONDS`` and ``_DIR`` (the journal directory); each unset variable keeps its
        default."""
        env = os.environ

        def num(name: str, default: float) -> float:
            raw = env.get(f"{prefix}_{name}", "")
            return float(raw) if raw else default

        return cls(
            max_requests=int(num("MAX_REQUESTS", cls.max_requests)),
            max_bytes=int(num("MAX_BYTES", cls.max_bytes)),
            min_requests=int(num("MIN_REQUESTS", cls.min_requests)),
            poll_seconds=num("POLL_SECONDS", cls.poll_seconds),
            linger_seconds=num("LINGER_SECONDS", cls.linger_seconds),
            journal_dir=env.get(f"{prefix}_DIR") or None,
        )


def request_id(params: dict[str, Any]) -> str:
    """A stable 40-hex name for one request: the hash of its ``params``."""
    blob = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()[:40]


def unique_ids(params: list[dict[str, Any]]) -> list[str]:
    """One ``custom_id`` per request, ``<request_id>-<k>``: ``k`` counts earlier identical
    requests of the list (a batch rejects a repeated ``custom_id``)."""
    seen: dict[str, int] = {}
    out = []
    for p in params:
        rid = request_id(p)
        k = seen.get(rid, 0)
        seen[rid] = k + 1
        out.append(f"{rid}-{k}")
    return out


class Journal:
    """Append-only record of submitted batches, so a re-run collects a batch that is still
    running or finished unread instead of paying for it again. Rows: ``{batch, ids, ts}`` when a
    batch is created, ``{batch, delivered: true}`` once every result of it was handed over (a
    delivered batch is never re-read: a request asked again gets a new answer, as live)."""

    def __init__(self, directory: str | os.PathLike[str]):
        self.path = Path(directory) / JOURNAL_FILE

    def _append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def created(self, batch_id: str, ids: list[str]) -> None:
        self._append({"batch": batch_id, "ids": ids, "ts": time.time()})

    def delivered(self, batch_id: str) -> None:
        self._append({"batch": batch_id, "delivered": True, "ts": time.time()})

    def undelivered(self) -> dict[str, list[str]]:
        """``{batch id: custom ids}`` of the batches created and not yet delivered."""
        out: dict[str, list[str]] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line
            if not isinstance(row, dict) or not isinstance(row.get("batch"), str):
                continue
            if row.get("delivered"):
                out.pop(row["batch"], None)
            elif isinstance(row.get("ids"), list):
                out[row["batch"]] = [str(i) for i in row["ids"]]
        return out


def _transient(e: BaseException) -> bool:
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    return status in _TRANSIENT or any(s in name for s in ("Timeout", "Connection", "Deadline"))


async def _retrying(
    call: Callable[[], Awaitable[Any]], sleep: Callable[[float], Awaitable[Any]]
) -> Any:
    """``await call()``, retrying transient API errors with jittered backoff."""
    for attempt in range(_ATTEMPTS):
        try:
            return await call()
        except Exception as e:
            if not _transient(e) or attempt == _ATTEMPTS - 1:
                raise
            await sleep(min(60.0, 2.0 * 2**attempt) * (0.5 + random.random()))
    raise AssertionError("unreachable")


def chunks(
    requests: list[tuple[str, dict[str, Any]]], settings: Settings
) -> list[list[tuple[str, dict[str, Any]]]]:
    """Split ``(custom_id, params)`` pairs into batches under the request and byte caps (a
    single request larger than ``max_bytes`` still gets a batch of its own)."""
    out: list[list[tuple[str, dict[str, Any]]]] = []
    cur: list[tuple[str, dict[str, Any]]] = []
    size = 0
    for cid, params in requests:
        n = len(json.dumps(params, ensure_ascii=False, default=str).encode("utf-8", "replace"))
        if cur and (len(cur) >= settings.max_requests or size + n > settings.max_bytes):
            out.append(cur)
            cur, size = [], 0
        cur.append((cid, params))
        size += n
    if cur:
        out.append(cur)
    return out


async def run(
    client: Any,
    requests: list[tuple[str, dict[str, Any]]],
    on_entry: Callable[[str, Any], None],
    *,
    settings: Settings,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    log: Callable[[str], None] = print,
) -> None:
    """Get every ``(custom_id, params)`` request answered through Message Batches and hand each
    outcome to ``on_entry`` exactly once (see the module docstring). ``client`` is an
    ``AsyncAnthropic``-shaped client. Raises on a non-transient API error; requests of batches
    already submitted stay collectable by a later run through the journal."""
    if not requests:
        return
    journal = Journal(settings.journal_dir) if settings.journal_dir else None
    wanted = {cid for cid, _p in requests}
    if len(wanted) != len(requests):
        raise ValueError("batch requests need unique custom ids")
    jobs: list[tuple[str, set[str]]] = []  # (batch id, the custom ids to take from it)
    attached: set[str] = set()
    if journal is not None:
        for batch_id, ids in journal.undelivered().items():
            mine = (wanted - attached) & set(ids)
            if not mine:
                continue
            try:
                await _retrying(lambda b=batch_id: client.messages.batches.retrieve(b), sleep)
            except Exception as e:
                if getattr(e, "status_code", None) != 404:
                    raise
                journal.delivered(batch_id)  # gone (older than the 29-day retention)
                continue
            log(f"  batches: re-attached to {batch_id} for {len(mine)} request(s)")
            jobs.append((batch_id, mine))
            attached |= mine
    for chunk in chunks([r for r in requests if r[0] not in attached], settings):
        body = [{"custom_id": cid, "params": params} for cid, params in chunk]
        batch = await _retrying(lambda b=body: client.messages.batches.create(requests=b), sleep)
        ids = [cid for cid, _p in chunk]
        if journal is not None:
            journal.created(batch.id, ids)
        log(f"  batches: submitted {batch.id} ({len(ids)} request(s))")
        jobs.append((batch.id, set(ids)))
    await asyncio.gather(
        *(_collect(client, b, ids, on_entry, settings, journal, sleep, log) for b, ids in jobs)
    )


async def _collect(
    client: Any,
    batch_id: str,
    ids: set[str],
    on_entry: Callable[[str, Any], None],
    settings: Settings,
    journal: Journal | None,
    sleep: Callable[[float], Awaitable[Any]],
    log: Callable[[str], None],
) -> None:
    """Wait for one batch to end, then deliver its results for ``ids`` (``None`` for an id it
    has no result for)."""
    delay = min(5.0, settings.poll_seconds)
    while True:
        batch = await _retrying(lambda: client.messages.batches.retrieve(batch_id), sleep)
        if getattr(batch, "processing_status", None) == "ended":
            break
        await sleep(delay)
        delay = min(settings.poll_seconds, delay * 1.5)
    left = set(ids)

    async def read() -> None:
        stream = client.messages.batches.results(batch_id)
        if inspect.isawaitable(stream):
            stream = await stream
        async for entry in stream:
            cid = getattr(entry, "custom_id", None)
            if cid in left:
                left.discard(cid)
                on_entry(cid, entry.result)

    try:
        await _retrying(read, sleep)  # a broken download resumes: delivered ids are skipped
    except Exception as e:
        if not _transient(e):
            raise
        log(f"  batches: results of {batch_id} unreadable ({type(e).__name__})")
    if left:
        log(f"  batches: {batch_id} returned no result for {len(left)} request(s)")
    for cid in sorted(left):
        on_entry(cid, None)
    if journal is not None:
        journal.delivered(batch_id)
