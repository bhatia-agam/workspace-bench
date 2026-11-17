"""One structured-JSON judge client with two routes.

* ``claude-*`` model ids go to the Anthropic SDK (structured outputs via ``output_config``);
  everything else goes to OpenRouter through the OpenAI SDK (``response_format`` json_schema).
* Requests are paced under a process-wide requests-per-minute cap shared by every event loop
  and thread (``_PACER``), so several families judged concurrently share one budget; an optional
  input-token budget (``set_itpm``, ``_TOKEN_PACER``) paces each call's estimated size as well.
* Transient failures (408/409/429/5xx, timeouts, connection errors, garbled bodies) are
  retried with jittered backoff; any other per-call failure yields ``None`` (an unjudged cell,
  never a clean one). Problems that would fail every call raise :class:`JudgeConfigError`.
* ``on_result(i, result)`` fires as each call lands so callers can cache as they go.
"""

import asyncio
import contextlib
import contextvars
import json
import math
import os
import random
import struct
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

OPENROUTER = "https://openrouter.ai/api/v1"
# 520: Cloudflare's "web server is returning an unknown error", seen on long digest and judge
# calls; retried like the other 5xx instead of failing the cell
_TRANSIENT = (408, 409, 429, 500, 502, 503, 504, 520, 529)
_FATAL = ("AuthenticationError", "PermissionDeniedError", "NotFoundError")
_ATTEMPTS = 12
_DEFAULT_MAX_TOKENS = {"openrouter": 8000, "anthropic": 16000}

Route = Literal["anthropic", "openrouter"]


class JudgeConfigError(RuntimeError):
    """A configuration problem that would fail every judge call (raised, never degraded)."""


LEDGER_ENV = "WSB_TOKEN_LEDGER"  # plan 0075 §4: one JSONL row per Anthropic call (spend cap)
_LEDGER_LOCK = threading.Lock()


def ledger(model: str, usage: Any) -> None:
    """Append ``{model, in, out}`` to ``$WSB_TOKEN_LEDGER`` when set (subprocesses inherit it), so
    a run's API spend is measured from tokens even where OAuth logs ``spend=$0.00``."""
    path = os.environ.get(LEDGER_ENV)
    if not path or usage is None:
        return
    if not os.path.isabs(path):  # subprocesses run elsewhere: one ledger, one absolute path
        path = os.environ[LEDGER_ENV] = os.path.abspath(path)
    row = {
        "model": model,
        "in": int(getattr(usage, "input_tokens", 0) or 0),
        "out": int(getattr(usage, "output_tokens", 0) or 0),
        # prompt caching (the system prompt carries cache_control): billed apart from `in`
        "cache_write": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "cache_read": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    }
    with _LEDGER_LOCK, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


@dataclass
class Spend:
    """Per-run tally. ``calls`` counts HTTP 200 responses (including garbled bodies that were
    then retried); ``errors``/``refusals`` count cells left unjudged."""

    usd: float = 0.0
    calls: int = 0
    retries: int = 0
    errors: int = 0
    refusals: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def report(self) -> str:
        s = (
            f"calls={self.calls} retries={self.retries} errors={self.errors} "
            f"refusals={self.refusals} spend=${self.usd:.2f}"
        )
        if self.input_tokens or self.output_tokens:
            s += f" in_tok={self.input_tokens} out_tok={self.output_tokens}"
        return s


def route(model: str) -> Route:
    return "anthropic" if model.startswith("claude-") else "openrouter"


def api_key(model: str) -> str:
    if route(model) == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
        if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return OAUTH_PREFIX + os.environ["ANTHROPIC_AUTH_TOKEN"]  # keyless OAuth bearer token
        if os.environ.get("ANTHROPIC_PROFILE"):
            return ""  # "" = let the SDK resolve the named `ant auth login` profile
        raise JudgeConfigError(
            f"ANTHROPIC_API_KEY is missing (needed for {model}); or set ANTHROPIC_AUTH_TOKEN, or "
            "ANTHROPIC_PROFILE to use an `ant auth login` profile"
        )
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key.startswith("sk-or-"):
        raise JudgeConfigError("OPENROUTER_API_KEY is missing or not an OpenRouter key (sk-or-…)")
    return key


def schema_block(name: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": list(required),
            "properties": properties,
        },
    }


# ---------------------------------------------------------------- pacing / backoff seams


def _now() -> float:
    return time.monotonic()


PACER_ENV = "WSB_PACER"  # a directory: the pacers of every process using it share one budget


class _Pacer:
    """Process-wide next-slot time behind a lock: shared by every loop, thread and Spend. With
    ``$WSB_PACER`` set (``wsbench run`` sets it for its judge processes, plan 0092 §5) the
    next-slot time lives in one small file of that directory instead, read and advanced under an
    exclusive ``flock``, so ``rpm=`` stays the budget of the whole run."""

    _FILE = "rpm"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 0.0
        self._shared: tuple[str, int] | None = None  # (directory, descriptor) of the shared file

    def reset(self) -> None:
        with self._lock:
            self._next = 0.0
            d = os.environ.get(PACER_ENV, "")
            if d:
                os.ftruncate(self._fd(d), 0)
            elif self._shared is not None:
                os.close(self._shared[1])
                self._shared = None

    def _fd(self, d: str) -> int:
        """The descriptor of this pacer's file in ``d``, opened once and kept."""
        if self._shared is not None and self._shared[0] == d:
            return self._shared[1]
        if self._shared is not None:
            os.close(self._shared[1])
            self._shared = None
        os.makedirs(d, exist_ok=True)
        fd = os.open(os.path.join(d, self._FILE), os.O_CREAT | os.O_RDWR, 0o644)
        self._shared = (d, fd)
        return fd

    def _advance(self, step: float) -> float:
        """Take the next slot and move it ``step`` seconds on; return the wait for it. Called
        with ``self._lock`` held."""
        d = os.environ.get(PACER_ENV, "")
        if not d:
            now = _now()
            slot = max(now, self._next)
            self._next = slot + step
            return slot - now
        import fcntl

        fd = self._fd(d)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            now = _now()
            slot = max(now, _stored_next(os.pread(fd, 8, 0)))
            os.pwrite(fd, struct.pack("<d", slot + step), 0)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
        return slot - now

    def reserve(self, rpm: float) -> float:
        """Reserve the next slot; return how long the caller must wait for it (seconds)."""
        with self._lock:
            return self._advance(60.0 / rpm)


def _stored_next(raw: bytes) -> float:
    """The next-slot time a shared pacer file holds; an empty or torn file reads as 0."""
    if len(raw) != 8:
        return 0.0
    (v,) = struct.unpack("<d", raw)
    return v if math.isfinite(v) and v > 0 else 0.0


_PACER = _Pacer()


class _TokenPacer(_Pacer):
    """Process-wide input-token budget (plan 0092): a call's start slot is ``max(now, next)`` and
    ``next`` advances by the time its estimated tokens take at ``itpm`` tokens a minute. One
    budget for every model, FIFO; a call larger than a whole minute's budget still runs. Shared
    across processes under ``$WSB_PACER`` like ``_Pacer``."""

    _FILE = "itpm"

    def reserve(self, tokens: int, itpm: float) -> float:  # type: ignore[override]
        """Reserve ``tokens``; return how long the caller must wait for its slot (seconds)."""
        with self._lock:
            return self._advance(max(0, tokens) * 60.0 / itpm)


_TOKEN_PACER = _TokenPacer()
_ITPM = 0.0  # input tokens per minute; 0 = off (the library default)


def set_itpm(tokens_per_minute: float) -> None:
    """Set the process-wide input-token budget ``_pace_tokens`` paces under; 0 turns it off."""
    global _ITPM
    _ITPM = max(0.0, float(tokens_per_minute or 0))


_sleep = asyncio.sleep  # seam: tests patch this instead of the global asyncio.sleep


async def _pace(rpm: float) -> None:
    delay = _PACER.reserve(rpm)
    if delay > 0:
        await _sleep(delay)


async def _pace_tokens(est: int) -> None:
    """Wait for ``est`` input tokens' slot under ``set_itpm``; returns at once when it is off."""
    itpm = _ITPM
    if itpm <= 0:
        return
    delay = _TOKEN_PACER.reserve(est, itpm)
    if delay > 0:
        await _sleep(delay)


# ---------------------------------------------------------------- cross-process slots

SLOTS_ENV = "WSB_SLOTS"  # "<dir>:<n>": at most n API calls in flight across every process using it


def _slots_config() -> tuple[str, int] | None:
    raw = os.environ.get(SLOTS_ENV, "")
    if not raw:
        return None
    d, _, n = raw.rpartition(":")
    try:
        count = int(n)
    except ValueError:
        count = 0
    if not d or count < 1:
        raise JudgeConfigError(f"{SLOTS_ENV}={raw!r}: expected <dir>:<n> with n >= 1")
    return d, count


def _try_slot(d: str, n: int, tries: int = 8) -> int | None:
    """Lock one free slot file of ``d`` (``flock``, released by the kernel if the process dies)
    and return its descriptor, or None when the ``tries`` random probes were all taken."""
    import fcntl

    os.makedirs(d, exist_ok=True)
    for _ in range(tries):
        fd = os.open(os.path.join(d, f"{random.randrange(n)}.slot"), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            os.close(fd)
    return None


@contextlib.asynccontextmanager
async def _slot() -> Any:
    """Hold one of the ``WSB_SLOTS`` slots for one API attempt (plan 0092: the account's output
    tokens per minute bound how many calls may generate at once, across the per-family judge
    processes); a no-op without the variable. A waiting call polls with jittered sleeps."""
    cfg = _slots_config()
    if cfg is None:
        yield
        return
    fd = _try_slot(*cfg)
    while fd is None:
        await _sleep(0.05 + 0.2 * random.random())
        fd = _try_slot(*cfg)
    try:
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


class ErrorTally:
    """Calls that ended in an error (retries exhausted, a non-transient error, a ``max_tokens``
    stop) while the tally was active; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.n = 0

    def add(self) -> None:
        with self._lock:
            self.n += 1


_ERRORS: contextvars.ContextVar[ErrorTally | None] = contextvars.ContextVar(
    "wsbench_llm_errors", default=None
)


@contextlib.contextmanager
def error_tally() -> Iterator[ErrorTally]:
    """Count the failed calls made in this context (``asyncio.run`` and its tasks inherit it), so
    ``runner`` can report them per family without a ``Spend`` crossing the family boundary."""
    tally = ErrorTally()
    token = _ERRORS.set(tally)
    try:
        yield tally
    finally:
        _ERRORS.reset(token)


def _note_error(spend: Spend) -> None:
    spend.errors += 1
    if (tally := _ERRORS.get()) is not None:
        tally.add()


def _cause(e: BaseException) -> str:
    """The transport error under an SDK connection error (" [ConnectError: ...]"), else ""."""
    c = e.__cause__
    return f" [{type(c).__name__}: {str(c)[:120]}]" if c is not None else ""


def _backoff(attempt: int, status: int | None) -> float:
    cap = 90.0 if status == 429 else 30.0
    return min(cap, 2.0 * 2**attempt) * (0.5 + random.random())


OAUTH_PREFIX = "oauth:"  # api_key() marks an OAuth bearer token (ANTHROPIC_AUTH_TOKEN) with this


def _make_client(route: str, key: str) -> Any:
    """The ONLY place SDK clients are built (tests monkeypatch this to inject fakes)."""
    if route == "anthropic":
        from anthropic import AsyncAnthropic

        if key.startswith(OAUTH_PREFIX):  # keyless judges: bearer auth + the OAuth beta flag
            return AsyncAnthropic(
                auth_token=key[len(OAUTH_PREFIX) :],
                api_key=None,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
                max_retries=0,
            )
        if not key:  # an `ant` profile (ANTHROPIC_PROFILE): the SDK reads its OAuth credentials
            return AsyncAnthropic(max_retries=0)
        return AsyncAnthropic(api_key=key, max_retries=0)
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=key, base_url=OPENROUTER, max_retries=0)


# ---------------------------------------------------------------- one call


def _parse_object(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    data = json.loads(content)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not a JSON object", content, 0)
    return data


async def _openrouter_once(
    client: Any,
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    model: str,
    reasoning: dict[str, Any] | None,
    temperature: float | None,
    max_tokens: int,
    timeout: float,
    spend: Spend,
) -> dict[str, Any] | None:
    extra_body: dict[str, Any] = {
        "usage": {"include": True},
        "provider": {"require_parameters": True},
    }
    if reasoning is not None:
        extra_body["reasoning"] = reasoning
    kwargs: dict[str, Any] = {}
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = await client.chat.completions.create(
        timeout=timeout,
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": schema},
        extra_body=extra_body,
        **kwargs,
    )
    spend.calls += 1
    if not getattr(resp, "choices", None):  # an error delivered in a 200 body
        raise ValueError("response has no choices")
    usage = getattr(resp, "usage", None)
    cost = getattr(usage, "cost", None) if usage is not None else None
    if cost is None and usage is not None:
        cost = (getattr(usage, "model_extra", None) or {}).get("cost")
    spend.usd += float(cost or 0.0)
    return _parse_object(resp.choices[0].message.content or "")


# What a free-text call returns for a model refusal when the caller passes mark_refusals=True
# (agentic Stage A treats a refused position as uninformative; plan 0012, Camila 2026-10-11).
REFUSED = "\x00refused\x00"
# What a structured-output call returns for a model refusal when the caller passes
# mark_refusals=True (the summary-mode digest tells a refusal from a failure; plan 0021)
REFUSED_JSON: dict[str, Any] = {"\x00refused": True}
# ... and for a context overflow (stop_reason model_context_window_exceeded, or a 400 "prompt is too
# long"), also only under mark_refusals=True
TOO_LONG_JSON: dict[str, Any] = {"\x00too_long": True}
# internal to stream_json_async(overflow_max_tokens=): a max_tokens stop it re-asks with a larger
# cap; never handed to a caller
TRUNCATED_JSON: dict[str, Any] = {"\x00truncated": True}
OVERFLOW_ATTEMPTS = 3  # attempts of that re-ask (first call: the caller's `attempts`)
# key a structured result carries when a server-side refusal fallback served it (the model id)
SERVED_BY = "\x00served_by"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Models that reject thinking={"type": "disabled"} (thinking is always on): a no-thinking call
# omits the parameter and asks for low effort instead, so the reply budget goes to the answer.
_ALWAYS_THINK = ("claude-opus-5-5", "claude-fable-", "claude-mythos-", "claude-sonnet-5-5")


def always_thinks(model: str) -> bool:
    return model.startswith(_ALWAYS_THINK)


def anthropic_effort(model: str, reasoning: dict[str, Any] | None) -> dict[str, str]:
    """The ``output_config`` effort of a structured Anthropic call. No family setting: low effort
    on always-thinking models (the repo default). A family's
    ``reasoning={"anthropic_effort": "default"}`` omits it (the model's own default, as the source
    instrument of introspection ran); any other value is passed through. The
    OpenRouter-style ``effort`` key stays ignored on this route."""
    effort = (reasoning or {}).get("anthropic_effort")
    if effort == "default":
        return {}
    if effort:
        return {"effort": str(effort)}
    return {"effort": "low"} if always_thinks(model) else {}


# JSON-schema keywords Anthropic structured outputs reject (OpenRouter accepted them): numeric
# bounds. The prompts state every range in words, so dropping them from the schema is safe.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
)


def anthropic_schema(schema: Any) -> Any:
    """A copy of ``schema`` without the keywords the Anthropic route rejects."""
    if isinstance(schema, dict):
        return {
            k: anthropic_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(schema, list):
        return [anthropic_schema(v) for v in schema]
    return schema


async def _anthropic_once(
    client: Any,
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    model: str,
    max_tokens: int,
    timeout: float,
    spend: Spend,
    reasoning: dict[str, Any] | None = None,
    mark_refusals: bool = False,
    fallbacks: str | None = None,
    mark_truncated: bool = False,
) -> dict[str, Any] | None:
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "format": {"type": "json_schema", "schema": anthropic_schema(schema["schema"])},
            **anthropic_effort(model, reasoning),
        },
    }
    if fallbacks is None:
        resp = await client.messages.create(**kwargs)
    else:  # server-side refusal fallback: a declined request re-runs on a fallback model
        betas = [FALLBACK_BETA]
        if getattr(client, "auth_token", None):  # betas= replaces the client's default header
            betas.append("oauth-2025-04-20")
        resp = await client.beta.messages.create(**kwargs, betas=betas, fallbacks=fallbacks)
    spend.calls += 1
    usage = getattr(resp, "usage", None)
    ledger(model, usage)
    if usage is not None:
        spend.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        spend.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
    stop = getattr(resp, "stop_reason", None)
    if stop == "refusal":
        spend.refusals += 1
        print(f"  llm refusal: {model}")
        return REFUSED_JSON if mark_refusals else None
    if stop == "max_tokens" and mark_truncated:
        # the caller re-asks once with a larger output cap: not a lost call yet
        print(f"  llm: {model} stop_reason=max_tokens at {max_tokens}; re-asking with a larger cap")
        return TRUNCATED_JSON
    if stop in ("max_tokens", "model_context_window_exceeded"):
        if mark_refusals and stop == "model_context_window_exceeded":
            spend.errors += 1  # a too-long bundle is re-asked in halves: not a lost call
        else:
            _note_error(spend)
        print(f"  llm error: {model} stop_reason={stop}")
        if mark_refusals and stop == "model_context_window_exceeded":
            return TOO_LONG_JSON
        return None
    blocks = list(resp.content)
    seams = [j for j, b in enumerate(blocks) if getattr(b, "type", None) == "fallback"]
    if fallbacks is not None and seams:
        # a mid-output refusal: the declining model's partial text, a fallback seam, then the
        # serving model's output (which may continue the partial as a prefill)
        texts = [getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text"]
        after = "".join(
            getattr(b, "text", "")
            for b in blocks[seams[-1] + 1 :]
            if getattr(b, "type", None) == "text"
        )
        try:
            out = _parse_object("".join(texts))
        except (ValueError, json.JSONDecodeError):
            out = _parse_object(after)
        if isinstance(out, dict):
            out[SERVED_BY] = str(getattr(resp, "model", "") or "fallback")
        return out
    text = next((b.text for b in blocks if getattr(b, "type", None) == "text"), None)
    if text is None:
        raise ValueError("response has no text block")
    return _parse_object(text)


def _moderation_flagged(e: Exception) -> bool:
    """OpenRouter's moderation 403 names the flagged input in ``error.metadata.flagged_input``."""
    body = getattr(e, "body", None)
    meta = body.get("metadata") if isinstance(body, dict) else None
    return isinstance(meta, dict) and "flagged_input" in meta


async def _one(
    route_: Route,
    client: Any,
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    model: str,
    reasoning: dict[str, Any] | None,
    temperature: float | None,
    max_tokens: int,
    timeout: float,
    rpm: float,
    spend: Spend,
    mark_refusals: bool = False,
    attempts: int | None = None,
    fallbacks: str | None = None,
    mark_truncated: bool = False,
) -> dict[str, Any] | None:
    # detokenised lens readouts can contain lone surrogates, which both APIs reject every time
    system = system.encode("utf-8", "replace").decode("utf-8")
    user = user.encode("utf-8", "replace").decode("utf-8")
    n_attempts = _ATTEMPTS if attempts is None else max(1, min(attempts, _ATTEMPTS))
    await _pace_tokens((len(system) + len(user)) // 3)  # once per call, not per retry
    for attempt in range(n_attempts):
        await _pace(rpm)
        try:
            async with _slot():
                if route_ == "anthropic":
                    return await _anthropic_once(
                        client,
                        system,
                        user,
                        schema=schema,
                        model=model,
                        max_tokens=max_tokens,
                        timeout=timeout,
                        spend=spend,
                        reasoning=reasoning,
                        mark_refusals=mark_refusals,
                        fallbacks=fallbacks,
                        # only when asked: fakes of this function need not know the keyword
                        **({"mark_truncated": True} if mark_truncated else {}),
                    )
                return await _openrouter_once(
                    client,
                    system,
                    user,
                    schema=schema,
                    model=model,
                    reasoning=reasoning,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    spend=spend,
                )
        except Exception as e:
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if route_ == "openrouter" and status == 403 and _moderation_flagged(e):
                spend.refusals += 1  # one prompt flagged by moderation, not a config error
                print(f"  llm refusal (moderation): {model}")
                return REFUSED_JSON if mark_refusals else None
            if name in _FATAL or status in (401, 402, 403):  # bad key, no credits, no access
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
            transient = (
                status in _TRANSIENT
                or "Timeout" in name
                or "Connection" in name
                or "Deadline" in name
                or isinstance(e, json.JSONDecodeError | ValueError)
            )
            if transient and attempt < n_attempts - 1:
                spend.retries += 1
                await _sleep(_backoff(attempt, status))
                continue
            too_long = mark_refusals and status == 400 and "prompt is too long" in str(e).lower()
            if too_long:
                spend.errors += 1  # re-asked in halves by the digest: not a lost call
            else:
                _note_error(spend)
            print(f"  llm error: {name}: {str(e)[:200]}{_cause(e)}")
            if too_long:
                return TOO_LONG_JSON
            return None
    return None


# ---------------------------------------------------------------- the primitive


async def stream_json_async(
    prompts: list[tuple[str, str]],
    *,
    schema: dict[str, Any],
    model: str,
    on_result: Callable[[int, dict[str, Any] | None], None],
    reasoning: dict[str, Any] | None = None,
    temperature: float | None = None,
    concurrency: int = 64,
    rpm: float = 240.0,
    max_tokens: int | None = None,
    timeout: float = 180.0,
    spend: Spend | None = None,
    mark_refusals: bool = False,
    attempts: int | None = None,
    fallbacks: str | None = None,
    refusal_model: str | None = None,
    overflow_max_tokens: int | None = None,
) -> Spend:
    """Run ``(system, user)`` prompt pairs concurrently, handing each parsed result (or
    ``None``) to ``on_result(index, result)`` as it lands. Raises :class:`JudgeConfigError` on
    a config problem. Builds no client when there is nothing to call. ``temperature`` is sent on
    the OpenRouter route only: newer Claude models reject the field (400), so the Anthropic route
    drops it with one printed warning per batch.

    ``refusal_model`` (client-side): a call ``model`` declines (``stop_reason``
    refusal) is re-run ONCE, same request, on that model (same route); a served result carries
    it as :data:`SERVED_BY`. Only refusals move: a ``max_tokens`` stop, an error or an
    unparsable body stays the primary's outcome. For models without server-side ``fallbacks``
    (claude-sonnet-5 rejects the parameter with a 400).

    ``overflow_max_tokens`` (Anthropic route): a call of ``model`` that stops at ``max_tokens``
    is re-asked ONCE, same request, with this larger output cap (and the timeout scaled by the
    same factor); a second ``max_tokens`` stop is the call's outcome (``None``, one counted
    error). Ignored unless it is above ``max_tokens``. The re-ask's retry budget is at most
    :data:`OVERFLOW_ATTEMPTS` attempts (3; fewer when ``attempts`` is lower), so a re-ask that
    times out holds its slot for at most 3 scaled timeouts; the first call keeps ``attempts``.
    Every other outcome of the re-ask is handled as the first call's would be: under
    ``mark_refusals`` a ``model_context_window_exceeded`` stop comes back as
    :data:`TOO_LONG_JSON` (the digest then halves the bundle), a refusal as
    :data:`REFUSED_JSON`. The refusal model's re-run keeps the larger cap, scaled timeout and
    bounded budget once the primary needed them, and is itself never re-asked."""
    spend = spend or Spend()
    if not prompts:
        return spend
    if concurrency < 1 or rpm <= 0:
        raise JudgeConfigError(f"concurrency must be >= 1 and rpm > 0 (got {concurrency}, {rpm})")
    route_ = route(model)
    key = api_key(model)
    if refusal_model is not None and (refusal_model == model or route(refusal_model) != route_):
        raise JudgeConfigError(f"refusal_model={refusal_model!r} must be another {route_} model")
    if temperature is not None and route_ == "anthropic":
        print(f"  llm: dropping temperature={temperature} for {model} (Anthropic route rejects it)")
        temperature = None
    if max_tokens is None:
        max_tokens = _DEFAULT_MAX_TOKENS[route_]
    client = _make_client(route_, key)
    sem = asyncio.Semaphore(concurrency)
    grow = (
        route_ == "anthropic"
        and overflow_max_tokens is not None
        and overflow_max_tokens > max_tokens
    )

    async def one(i: int, system: str, user: str) -> tuple[int, dict[str, Any] | None]:
        kw: dict[str, Any] = {
            "schema": schema,
            "reasoning": reasoning,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "rpm": rpm,
            "spend": spend,
            "attempts": attempts,
        }
        async with sem:
            res = await _one(
                route_,
                client,
                system,
                user,
                model=model,
                mark_refusals=mark_refusals or refusal_model is not None,
                fallbacks=fallbacks,
                **({"mark_truncated": True} if grow else {}),
                **kw,
            )
            if grow and res == TRUNCATED_JSON:
                kw["timeout"] = timeout * overflow_max_tokens / max_tokens
                kw["max_tokens"] = overflow_max_tokens
                # a long call at a doubled timeout must not also keep the full retry budget
                kw["attempts"] = min(attempts or _ATTEMPTS, OVERFLOW_ATTEMPTS)
                res = await _one(
                    route_,
                    client,
                    system,
                    user,
                    model=model,
                    mark_refusals=mark_refusals or refusal_model is not None,
                    fallbacks=fallbacks,
                    **kw,
                )
            if refusal_model is not None and res == REFUSED_JSON:
                again = await _one(
                    route_, client, system, user, model=refusal_model, mark_refusals=True, **kw
                )
                if isinstance(again, dict) and again not in (REFUSED_JSON, TOO_LONG_JSON):
                    again = {**again, SERVED_BY: refusal_model}
                res = again
        if not mark_refusals and res in (REFUSED_JSON, TOO_LONG_JSON):
            res = None  # the caller did not ask for markers
        return i, res

    tasks = [asyncio.ensure_future(one(i, s, u)) for i, (s, u) in enumerate(prompts)]
    try:
        for fut in asyncio.as_completed(tasks):
            i, res = await fut
            on_result(i, res)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
    return spend


def _in_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def stream_json(
    prompts: list[tuple[str, str]],
    *,
    schema: dict[str, Any],
    model: str,
    on_result: Callable[[int, dict[str, Any] | None], None],
    reasoning: dict[str, Any] | None = None,
    temperature: float | None = None,
    concurrency: int = 64,
    rpm: float = 240.0,
    max_tokens: int | None = None,
    timeout: float = 180.0,
    spend: Spend | None = None,
    mark_refusals: bool = False,
    attempts: int | None = None,
    fallbacks: str | None = None,
    refusal_model: str | None = None,
    overflow_max_tokens: int | None = None,
) -> Spend:
    """Synchronous wrapper around :func:`stream_json_async` for the CLI and tests."""
    if _in_running_loop():
        raise JudgeConfigError(
            "stream_json called inside a running event loop; await stream_json_async"
        )
    return asyncio.run(
        stream_json_async(
            prompts,
            schema=schema,
            model=model,
            on_result=on_result,
            reasoning=reasoning,
            temperature=temperature,
            concurrency=concurrency,
            rpm=rpm,
            max_tokens=max_tokens,
            timeout=timeout,
            spend=spend,
            mark_refusals=mark_refusals,
            attempts=attempts,
            fallbacks=fallbacks,
            refusal_model=refusal_model,
            overflow_max_tokens=overflow_max_tokens,
        )
    )


def count_tokens(
    model: str, prompts: list[tuple[str, str]], concurrency: int = 8
) -> list[int | None]:
    """Real input-token counts of ``(system, user)`` pairs (``messages.count_tokens``, Anthropic
    route only; ``None`` where a count failed). Used by the summary-mode digest to decide whether a
    bundle fits the context window (plan 0021)."""
    if route(model) != "anthropic":
        raise JudgeConfigError(f"count_tokens needs an Anthropic model, got {model}")
    if not prompts:
        return []
    client = _make_client("anthropic", api_key(model))
    sem = asyncio.Semaphore(concurrency)

    async def one(system: str, user: str) -> int | None:
        system = system.encode("utf-8", "replace").decode("utf-8")
        user = user.encode("utf-8", "replace").decode("utf-8")
        async with sem:
            for attempt in range(_ATTEMPTS):
                try:
                    r = await client.messages.count_tokens(
                        model=model, system=system, messages=[{"role": "user", "content": user}]
                    )
                    return int(r.input_tokens)
                except Exception as e:
                    status = getattr(e, "status_code", None)
                    if status in _TRANSIENT and attempt < _ATTEMPTS - 1:
                        await _sleep(_backoff(attempt, status))
                        continue
                    print(f"  count_tokens error: {type(e).__name__}: {str(e)[:200]}")
                    return None
        return None

    async def run() -> list[int | None]:
        try:
            return list(await asyncio.gather(*(one(s, u) for s, u in prompts)))
        finally:
            await client.close()

    if _in_running_loop():
        raise JudgeConfigError("count_tokens called inside a running event loop")
    return asyncio.run(run())


async def preflight_async(model: str, reasoning: dict[str, Any] | None) -> None:
    """One tiny structured call, so a bad key/model/route fails before a long run starts."""
    out: list[dict[str, Any] | None] = []
    schema = schema_block("t", {"a": {"type": "integer"}}, ["a"])
    await stream_json_async(
        [("Reply JSON.", 'Return {"a":1}')],
        schema=schema,
        model=model,
        reasoning=reasoning,
        concurrency=1,
        on_result=lambda _i, r: out.append(r),
    )
    if out != [{"a": 1}]:
        raise JudgeConfigError(f"preflight failed for {model}: {out}")


def preflight(model: str, reasoning: dict[str, Any] | None) -> None:
    if _in_running_loop():
        raise JudgeConfigError(
            "preflight called inside a running event loop; await preflight_async"
        )
    asyncio.run(preflight_async(model, reasoning))


# ---------------------------------------------------------------- free-text primitive
# Used by agentic_misalignment (three free-text stages, no schema). Anthropic route only:
# streaming (the SDK refuses non-streaming requests whose max_tokens implies a >10 min
# operation), per-call thinking on/off, and a budget-doubling retry when the text is empty and
# stop_reason == "max_tokens" (thinking ate the budget), up to _TEXT_BUDGET_CEILING.

_TEXT_BUDGET_CEILING = 64_000


async def _anthropic_text_once(
    client: Any,
    user: str,
    *,
    model: str,
    thinking: bool,
    max_tokens: int,
    timeout: float,
    spend: Spend,
    mark_refusals: bool = False,
) -> str | None:
    budget = max_tokens
    while True:
        if always_thinks(model):  # cannot disable: adaptive, low effort for "no thinking" stages
            think: dict[str, Any] = {"thinking": {"type": "adaptive"}}
            if not thinking:
                think["output_config"] = {"effort": "low"}
        else:
            think = {"thinking": {"type": "adaptive" if thinking else "disabled"}}
        async with client.messages.stream(
            timeout=timeout,
            model=model,
            max_tokens=budget,
            messages=[{"role": "user", "content": user}],
            **think,
        ) as stream:
            resp = await stream.get_final_message()
        spend.calls += 1
        usage = getattr(resp, "usage", None)
        ledger(model, usage)
        if usage is not None:
            spend.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            spend.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        stop = getattr(resp, "stop_reason", None)
        if stop == "refusal":
            spend.refusals += 1
            print(f"  llm refusal: {model}")
            return REFUSED if mark_refusals else None
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if not txt and stop == "max_tokens" and budget < _TEXT_BUDGET_CEILING:
            budget *= 2
            continue
        return txt


async def _one_text(
    client: Any,
    user: str,
    *,
    model: str,
    thinking: bool,
    max_tokens: int,
    timeout: float,
    rpm: float,
    spend: Spend,
    mark_refusals: bool = False,
) -> str | None:
    """Same backoff / fatal classification as :func:`_one`, for one free-text call."""
    user = user.encode("utf-8", "replace").decode("utf-8")
    await _pace_tokens(len(user) // 3)  # once per call, not per retry
    for attempt in range(_ATTEMPTS):
        await _pace(rpm)
        try:
            async with _slot():
                return await _anthropic_text_once(
                    client,
                    user,
                    model=model,
                    thinking=thinking,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    spend=spend,
                    mark_refusals=mark_refusals,
                )
        except Exception as e:
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if name in _FATAL or status in (401, 402, 403):
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
            transient = (
                status in _TRANSIENT
                or "Timeout" in name
                or "Connection" in name
                or "Deadline" in name
                or isinstance(e, json.JSONDecodeError | ValueError)
            )
            if transient and attempt < _ATTEMPTS - 1:
                spend.retries += 1
                await _sleep(_backoff(attempt, status))
                continue
            _note_error(spend)
            print(f"  llm error: {name}: {str(e)[:200]}{_cause(e)}")
            return None
    return None


async def stream_text_async(
    prompts: list[str],
    *,
    model: str,
    on_result: Callable[[int, str | None], None],
    thinking: bool,
    max_tokens: int,
    concurrency: int = 64,
    rpm: float = 240.0,
    timeout: float = 600.0,
    spend: Spend | None = None,
    mark_refusals: bool = False,
    refusal_model: str | None = None,
    on_served: Callable[[int, str], None] | None = None,
) -> Spend:
    """Run user-only free-text prompts concurrently on the Anthropic route (no system block,
    no schema), handing each stripped text (or ``None`` = exhausted retries / non-transient
    error / refusal; with ``mark_refusals`` a refusal is :data:`REFUSED` instead) to
    ``on_result(index, text)`` as it lands. ``""`` is a valid result (the
    source returns it after the 64k budget ceiling). Any non-``claude-*`` model raises
    :class:`JudgeConfigError`. Builds no client when there is nothing to call.

    ``refusal_model`` (client-side): a prompt ``model`` declines is re-run ONCE on
    that model with the same settings; when it serves, ``on_served(index, refusal_model)`` fires
    just before ``on_result`` (the text itself carries no provenance)."""
    spend = spend or Spend()
    if not prompts:
        return spend
    if concurrency < 1 or rpm <= 0:
        raise JudgeConfigError(f"concurrency must be >= 1 and rpm > 0 (got {concurrency}, {rpm})")
    if route(model) != "anthropic":
        raise JudgeConfigError(f"free-text stage requires a claude-* model (got {model})")
    if refusal_model is not None and (
        refusal_model == model or route(refusal_model) != "anthropic"
    ):
        raise JudgeConfigError(f"refusal_model={refusal_model!r} must be another claude-* model")
    client = _make_client("anthropic", api_key(model))
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, user: str) -> tuple[int, str | None, str | None]:
        kw: dict[str, Any] = {
            "thinking": thinking,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "rpm": rpm,
            "spend": spend,
        }
        served: str | None = None
        async with sem:
            res = await _one_text(
                client, user, model=model, mark_refusals=mark_refusals or bool(refusal_model), **kw
            )
            if refusal_model is not None and res == REFUSED:
                res = await _one_text(client, user, model=refusal_model, mark_refusals=True, **kw)
                if res is not None and res != REFUSED:
                    served = refusal_model
        if res == REFUSED and not mark_refusals:
            res = None  # the caller did not ask for the marker
        return i, res, served

    tasks = [asyncio.ensure_future(one(i, u)) for i, u in enumerate(prompts)]
    try:
        for fut in asyncio.as_completed(tasks):
            i, res, served = await fut
            if served is not None and on_served is not None:
                on_served(i, served)
            on_result(i, res)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.close()
    return spend


def stream_text(
    prompts: list[str],
    *,
    model: str,
    on_result: Callable[[int, str | None], None],
    thinking: bool,
    max_tokens: int,
    concurrency: int = 64,
    rpm: float = 240.0,
    timeout: float = 600.0,
    spend: Spend | None = None,
    mark_refusals: bool = False,
    refusal_model: str | None = None,
    on_served: Callable[[int, str], None] | None = None,
) -> Spend:
    """Synchronous wrapper around :func:`stream_text_async` for the CLI and tests."""
    if _in_running_loop():
        raise JudgeConfigError(
            "stream_text called inside a running event loop; await stream_text_async"
        )
    return asyncio.run(
        stream_text_async(
            prompts,
            model=model,
            on_result=on_result,
            thinking=thinking,
            max_tokens=max_tokens,
            concurrency=concurrency,
            rpm=rpm,
            timeout=timeout,
            spend=spend,
            mark_refusals=mark_refusals,
            refusal_model=refusal_model,
            on_served=on_served,
        )
    )
