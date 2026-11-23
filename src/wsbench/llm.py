"""One structured-JSON judge client with three routes.

* ``claude-*`` model ids go to the Anthropic SDK (structured outputs via ``output_config``);
  everything else goes to OpenRouter through the OpenAI SDK (``response_format`` json_schema).
* With ``WSBENCH_OPENAI_ROUTE=wif`` an ``openai/*`` id (not ``openai/gpt-oss*``) goes to OpenAI
  directly (route ``openai``, workload identity federation through ``baselines.ati_remote``;
  plan 0096 part 2). ``WSBENCH_OPENROUTER_MAX_OUT`` caps the output of both chat routes.
* Requests are paced under a process-wide requests-per-minute cap shared by every event loop
  and thread (``_PACER``), so several families judged concurrently share one budget; an optional
  input-token budget (``set_itpm``, ``_TOKEN_PACER``) paces each call's estimated size as well.
* Transient failures (408/409/429/5xx, timeouts, connection errors, garbled bodies) are
  retried with jittered backoff; any other per-call failure yields ``None`` (an unjudged cell,
  never a clean one). Problems that would fail every call raise :class:`JudgeConfigError`.
* ``on_result(i, result)`` fires as each call lands so callers can cache as they go.
* Opt-in: with ``$WSB_JUDGE_BACKEND=batches`` (``judge_backend=batches`` on ``judge`` / ``run``)
  the structured Anthropic calls of :func:`stream_json_async` go through the Message Batches API
  (:mod:`wsbench.judge_batches`): the same requests, outside the live rate limits. Whatever a
  batch does not answer cleanly is re-run live, so results, cache keys and resume are those of
  the live backend.
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
_DEFAULT_MAX_TOKENS = {"openrouter": 8000, "anthropic": 16000, "openai": 8000}

Route = Literal["anthropic", "openrouter", "openai"]
# the two chat-completions routes: they share the response rules, the output cap and `_too_long`
_CHAT_ROUTES = ("openrouter", "openai")
# "wif" sends openai/* ids (not gpt-oss) to OpenAI directly (route openai; plan 0096 part 2)
OPENAI_ROUTE_ENV = "WSBENCH_OPENAI_ROUTE"
_OPEN_WEIGHTS = "openai/gpt-oss"  # served by other providers, never by OpenAI: stays on OpenRouter
# the output budget of the chat routes: every call's cap, raised or lowered to it (outside every
# fingerprint); the starting budget of a free-text call. Never read on the Anthropic route
MAX_OUT_ENV = "WSBENCH_OPENROUTER_MAX_OUT"
# a chat-route 400 whose message names the context length is a too-long input, only while
# MAX_OUT_ENV is set (`_too_long`; "too many tokens" is deliberately absent: it also names an
# output request over the cap)
OPENROUTER_TOO_LONG = (
    "maximum context length",
    "context length",
    "context window",
    "prompt is too long",
)

# A family's reasoning dict is route-keyed: these keys ride the Anthropic route, every other key
# the OpenRouter one (plan 0023); `reasoning_for` is the one rule
ANTHROPIC_REASONING_KEYS = frozenset({"anthropic_effort"})
# OpenRouter calls with no reasoning setting of their own: Gemini cannot turn reasoning off
OPENROUTER_MIN_REASONING = {"effort": "minimal"}


class JudgeConfigError(RuntimeError):
    """A configuration problem that would fail every judge call (raised, never degraded)."""


LEDGER_ENV = "WSB_TOKEN_LEDGER"  # plan 0075 §4: one JSONL row per Anthropic call (spend cap)
_LEDGER_LOCK = threading.Lock()


def ledger(model: str, usage: Any, *, batch: bool = False) -> None:
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
    if batch:  # a Message Batches call: tallied at the batch rate
        row["batch"] = True
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
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("openai/") and not model.startswith(_OPEN_WEIGHTS) and _openai_wif():
        return "openai"
    return "openrouter"


def _openai_wif() -> bool:
    """``WSBENCH_OPENAI_ROUTE`` is ``wif`` (unset / empty: ``False``; anything else is a
    :class:`JudgeConfigError`)."""
    raw = os.environ.get(OPENAI_ROUTE_ENV, "").strip()
    if raw and raw != "wif":
        raise JudgeConfigError(f"{OPENAI_ROUTE_ENV}={raw!r}: expected 'wif' or unset")
    return raw == "wif"


def openrouter_max_out() -> int | None:
    """``WSBENCH_OPENROUTER_MAX_OUT`` as a positive int (``None`` when unset); a bad value is a
    :class:`JudgeConfigError`."""
    raw = os.environ.get(MAX_OUT_ENV, "").strip()
    if not raw:
        return None
    try:
        cap = int(raw)
    except ValueError:
        cap = 0
    if cap <= 0:
        raise JudgeConfigError(f"{MAX_OUT_ENV}={raw!r}: expected a positive integer")
    return cap


def _capped(route_: Route, max_tokens: int) -> int:
    """The output cap a call on ``route_`` runs at: :func:`openrouter_max_out` on the two chat
    routes when it is set, else ``max_tokens`` (always, on the Anthropic route)."""
    if route_ in _CHAT_ROUTES and (cap := openrouter_max_out()) is not None:
        return cap
    return max_tokens


def reasoning_for(route_: Route, reasoning: dict[str, Any] | None) -> dict[str, Any] | None:
    """``reasoning`` as a call on ``route_`` sends it: the Anthropic route keeps only
    :data:`ANTHROPIC_REASONING_KEYS` (``None`` when none is left), the OpenRouter route (and the
    ``openai`` route, treated alike) every other key, or a copy of
    :data:`OPENROUTER_MIN_REASONING` when none is left. Used by ``judge_config.resolve`` and for
    a refusal re-run on another route (plan 0096)."""
    is_anthropic = route_ == "anthropic"
    kept = {
        k: v
        for k, v in (reasoning or {}).items()
        if (k in ANTHROPIC_REASONING_KEYS) == is_anthropic
    }
    return kept or (None if is_anthropic else dict(OPENROUTER_MIN_REASONING))


def api_key(model: str) -> str:
    route_ = route(model)
    if route_ == "openai":
        return ""  # workload identity federation: the client exchanges a token
    if route_ == "anthropic":
        if _ANTHROPIC_CLIENT is not None:
            return ""  # the injected client carries its own credentials
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


def require_credentials(model: str) -> None:
    """Raise :class:`JudgeConfigError` now when ``model``'s route has no credentials: its key
    (:func:`api_key`), or on the ``openai`` route, where there is no key, the WIF token source
    (the ``openai-wif`` secret and the Modal identity). No network call."""
    if route(model) != "openai":
        api_key(model)
        return
    from wsbench.baselines import ati_remote

    try:
        ati_remote.WifToken()
    except ati_remote.AbortError as e:
        raise JudgeConfigError(str(e)) from e


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

_ANTHROPIC_CLIENT: Callable[[], Any] | None = None


def use_anthropic_client(factory: Callable[[], Any] | None) -> None:
    """Build every Anthropic client with ``factory()`` (an ``AsyncAnthropic``; ``None`` restores
    the default). For credentials the environment cannot carry, e.g. workload identity
    federation with a token provider. Each batch of calls closes the client it was given."""
    global _ANTHROPIC_CLIENT
    _ANTHROPIC_CLIENT = factory


BACKEND_ENV = "WSB_JUDGE_BACKEND"  # live (default) | batches; subprocesses inherit it
BATCH_ENV_PREFIX = "WSB_JUDGE_BATCH"  # _DIR, _MAX_REQUESTS, ...: judge_batches.Settings.from_env


def set_backend(name: str) -> None:
    """Choose how structured Anthropic calls travel, for this process and its children."""
    os.environ[BACKEND_ENV] = judge_backend(name)


def judge_backend(name: str | None = None) -> str:
    """``name`` (default: ``$WSB_JUDGE_BACKEND``, else ``live``), checked."""
    name = name or os.environ.get(BACKEND_ENV, "") or "live"
    if name not in ("live", "batches"):
        raise JudgeConfigError(f"judge backend must be live or batches, got {name!r}")
    return name


def _make_client(route: str, key: str) -> Any:
    """The ONLY place SDK clients are built (tests monkeypatch this to inject fakes)."""
    if route == "anthropic":
        if _ANTHROPIC_CLIENT is not None:
            return _ANTHROPIC_CLIENT()
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
    if route == "openai":
        from wsbench.baselines import ati_remote  # lazily: the route is opt-in

        try:
            return _WifClient(ati_remote.Clients("openai-wif"))
        except ati_remote.AbortError as e:  # the openai-wif secret / Modal identity is missing
            raise JudgeConfigError(str(e)) from e
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
    mark_refusals: bool = False,
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
    return _chat_result(
        resp, model=model, max_tokens=max_tokens, spend=spend, mark_refusals=mark_refusals
    )


def _chat_result(
    resp: Any, *, model: str, max_tokens: int, spend: Spend, mark_refusals: bool = False
) -> dict[str, Any] | None:
    """A chat-completions response (OpenRouter or OpenAI) -> the parsed object, a refusal or
    ``None``; tallies cost (0 where the route reports none) and tokens. A refusal is
    ``finish_reason`` content_filter or a ``message.refusal`` with no content. An unparsable
    body cut at the output cap (``finish_reason`` length) is one failed call, never retried (a
    retry would be cut off, and paid, again); any other unparsable body raises (retried)."""
    spend.calls += 1
    if not getattr(resp, "choices", None):  # an error delivered in a 200 body
        raise ValueError("response has no choices")
    usage = getattr(resp, "usage", None)
    spend.usd += _openrouter_cost(usage)
    if usage is not None:  # getattr defaults: the test fakes carry only ``cost``
        spend.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        spend.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
    choice = resp.choices[0]
    finish = getattr(choice, "finish_reason", None)
    content = choice.message.content or ""
    refusal = getattr(choice.message, "refusal", None)
    if finish == "content_filter" or (
        refusal and not content.strip()
    ):  # a declined call (plan 0096): one refusal, never 12 retries of an unparsable body
        spend.refusals += 1
        print(f"  llm refusal: {model}")
        return REFUSED_JSON if mark_refusals else None
    try:
        return _parse_object(content)
    except (ValueError, json.JSONDecodeError):
        if finish != "length":
            raise  # a garbled body: retried
        _note_error(spend)
        print(f"  llm error: {model} finish_reason=length (max_tokens={max_tokens})")
        return None


def _openai_effort(effort: Any) -> str:
    """The ``reasoning_effort`` the ``openai`` route sends for a reasoning ``effort``. OpenAI's
    current reasoning models reject ``minimal`` (400: supported are none / low / medium / high /
    xhigh; seen live on gpt-6-luna, 2026-11-18), so the repo's non-Anthropic default
    ``{"effort": "minimal"}`` is sent as ``low``, the nearest level and the one plan 0059
    validated. The judge fingerprint keeps the reasoning as resolved."""
    return "low" if str(effort) == "minimal" else str(effort)


class _WifClient:
    """The ``openai`` route's client: ``ati_remote.Clients("openai-wif")`` (one ``AsyncOpenAI``
    per access token) behind the ``close()`` the batch calls at the end."""

    def __init__(self, clients: Any) -> None:
        self.clients = clients
        self._built: list[Any] = []

    async def get(self) -> Any:
        c = await self.clients.get()
        if not any(c is b for b in self._built):
            self._built.append(c)
        return c

    def auth_failed(self, client: Any) -> None:
        self.clients.auth_failed(client)

    async def close(self) -> None:
        for c in self._built:
            close = getattr(c, "close", None)
            if close is not None:
                await close()


async def _wif_create(wif: Any, kwargs: dict[str, Any]) -> Any:
    """``chat.completions.create`` on the ``openai`` route. A 401 drops the access token and
    re-exchanges, up to ``ati_remote.AUTH_REFRESHES`` times; the last 401 propagates (fatal in
    :func:`_one` / :func:`_one_text`). A failed token exchange is a :class:`JudgeConfigError`
    (key / identity problem) or, on a 429 / 5xx from the token endpoint, a retried
    ``TransientExchangeError``."""
    from wsbench.baselines import ati_remote

    for auth in range(ati_remote.AUTH_REFRESHES + 1):
        try:
            client = await wif.get()
        except ati_remote.AbortError as e:
            raise JudgeConfigError(str(e)) from e
        try:
            return await client.chat.completions.create(**kwargs)
        except Exception as e:
            if getattr(e, "status_code", None) == 401 and auth < ati_remote.AUTH_REFRESHES:
                wif.auth_failed(client)  # the short-lived token may have expired mid-run
                continue
            raise
    raise AssertionError("unreachable: the last 401 propagates")


async def _openai_once(
    wif: Any,
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    model: str,
    reasoning: dict[str, Any] | None,
    max_tokens: int,
    timeout: float,
    spend: Spend,
    mark_refusals: bool = False,
) -> dict[str, Any] | None:
    """One structured OpenAI chat completion through WIF: ``max_completion_tokens``,
    ``reasoning_effort`` from the reasoning's ``effort``, no ``temperature``, no OpenRouter
    ``extra_body``; the response is read by :func:`_chat_result` (cost 0 on this route)."""
    from wsbench.baselines import ati_remote

    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "model": ati_remote.route_model(model, "openai-wif"),
        "max_completion_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    effort = (reasoning or {}).get("effort")
    if effort:
        kwargs["reasoning_effort"] = _openai_effort(effort)
    resp = await _wif_create(wif, kwargs)
    return _chat_result(
        resp, model=model, max_tokens=max_tokens, spend=spend, mark_refusals=mark_refusals
    )


def _openrouter_cost(usage: Any) -> float:
    """The USD cost OpenRouter reports in ``usage`` (``usage: {include: true}``), else 0."""
    cost = getattr(usage, "cost", None) if usage is not None else None
    if cost is None and usage is not None:
        cost = (getattr(usage, "model_extra", None) or {}).get("cost")
    return float(cost or 0.0)


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


def anthropic_params(
    system: str,
    user: str,
    *,
    schema: dict[str, Any],
    model: str,
    max_tokens: int,
    reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The Messages request of one structured call: what the live call sends (plus its
    ``timeout``) and, unchanged, the ``params`` of the same call in a batch."""
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "format": {"type": "json_schema", "schema": anthropic_schema(schema["schema"])},
            **anthropic_effort(model, reasoning),
        },
    }


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
        **anthropic_params(
            system, user, schema=schema, model=model, max_tokens=max_tokens, reasoning=reasoning
        ),
    }
    if fallbacks is None:
        resp = await client.messages.create(**kwargs)
    else:  # server-side refusal fallback: a declined request re-runs on a fallback model
        betas = [FALLBACK_BETA]
        if getattr(client, "auth_token", None):  # betas= replaces the client's default header
            betas.append("oauth-2025-04-20")
        resp = await client.beta.messages.create(**kwargs, betas=betas, fallbacks=fallbacks)
    return _anthropic_result(
        resp,
        model=model,
        spend=spend,
        mark_refusals=mark_refusals,
        fallbacks=fallbacks,
        mark_truncated=mark_truncated,
        max_tokens=max_tokens,
    )


def _anthropic_result(
    resp: Any,
    *,
    model: str,
    spend: Spend,
    mark_refusals: bool = False,
    fallbacks: str | None = None,
    batch: bool = False,
    mark_truncated: bool = False,
    max_tokens: int = 0,
) -> dict[str, Any] | None:
    """Tally one Messages response (live or from a batch) and parse its JSON object. With
    ``mark_truncated`` a ``max_tokens`` stop comes back as :data:`TRUNCATED_JSON` (the caller
    re-asks with a larger cap; ``max_tokens`` is the cap that was hit, for the log line)."""
    spend.calls += 1
    usage = getattr(resp, "usage", None)
    ledger(model, usage, batch=batch)
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


# OpenAI error types / codes that mean the account or project is out of quota (delivered as a
# 429, or as a status-less error event inside a stream): fatal for the run, not a rate limit
_QUOTA_CODES = frozenset(
    {"insufficient_quota", "project_spend_limit_exceeded", "billing_hard_limit_reached"}
)


def _out_of_quota(e: Exception) -> bool:
    """An error whose body names an exhausted quota or spend limit (``_QUOTA_CODES``)."""
    body = getattr(e, "body", None)
    if not isinstance(body, dict):
        return False
    return body.get("type") in _QUOTA_CODES or body.get("code") in _QUOTA_CODES


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
                if route_ == "openai":
                    return await _openai_once(
                        client,
                        system,
                        user,
                        schema=schema,
                        model=model,
                        reasoning=reasoning,
                        max_tokens=max_tokens,
                        timeout=timeout,
                        spend=spend,
                        mark_refusals=mark_refusals,
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
                    # only when asked: fakes of this function need not know the keyword
                    **({"mark_refusals": True} if mark_refusals else {}),
                )
        except Exception as e:
            if isinstance(e, JudgeConfigError):  # e.g. the openai route's failed token exchange
                raise
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if _out_of_quota(e):  # a spend limit fails every call: never 12 backoffs each
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
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
                or name == "TransientExchangeError"  # openai route: token endpoint 429 / 5xx
            )
            if transient and attempt < n_attempts - 1:
                spend.retries += 1
                await _sleep(_backoff(attempt, status))
                continue
            too_long = mark_refusals and status == 400 and _too_long(route_, str(e))
            if too_long:
                spend.errors += 1  # re-asked in halves by the digest: not a lost call
            else:
                _note_error(spend)
            print(f"  llm error: {name}: {str(e)[:200]}{_cause(e)}")
            if too_long:
                return TOO_LONG_JSON
            return None
    return None


def _too_long(route_: Route, message: str) -> bool:
    """A 400 that is a too-long input: "prompt is too long"; on the two chat routes with
    ``WSBENCH_OPENROUTER_MAX_OUT`` set, any :data:`OPENROUTER_TOO_LONG` phrase (sound only under
    that output cap: without it a "maximum context length" 400 can be the output request)."""
    msg = message.lower()
    if route_ == "anthropic" or openrouter_max_out() is None:  # the broad list needs the cap
        return "prompt is too long" in msg
    return any(p in msg for p in OPENROUTER_TOO_LONG)


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
    backend: str | None = None,
    overflow_max_tokens: int | None = None,
    refusal_reasoning: dict[str, Any] | None = None,
) -> Spend:
    """Run ``(system, user)`` prompt pairs concurrently, handing each parsed result (or
    ``None``) to ``on_result(index, result)`` as it lands. Raises :class:`JudgeConfigError` on
    a config problem. Builds no client when there is nothing to call. ``temperature`` is sent on
    the OpenRouter route only: newer Claude models reject the field (400), so the Anthropic route
    drops it with one printed warning per batch, and so does the ``openai`` route (OpenAI
    reasoning models reject it too). ``WSBENCH_OPENROUTER_MAX_OUT`` replaces the output cap of
    every call made on a chat route (``openrouter``, ``openai``), by the route of the model
    actually called: the primary and its refusal re-run each by their own.

    ``refusal_model`` (client-side): a call ``model`` declines (Anthropic ``stop_reason``
    refusal; OpenRouter ``finish_reason`` content_filter, a ``message.refusal`` with no content,
    or the moderation 403) is re-run ONCE, same request, on that model; a served result carries
    it as :data:`SERVED_BY`. Only refusals move: a ``max_tokens`` stop, an error or an
    unparsable body stays the primary's outcome. For models without server-side ``fallbacks``
    (claude-sonnet-5 rejects the parameter with a 400). It must be another model and may be on
    any route (plan 0096). On the same route the re-run shares the client and sends
    ``reasoning`` unchanged. On the other route its key is resolved before any call (a missing
    one raises :class:`JudgeConfigError`), a second client is built, and the request is
    re-shaped for that route: ``reasoning`` through :func:`reasoning_for`, a ``max_tokens`` left
    ``None`` as that route's default, ``temperature`` sent to an OpenRouter model (the caller's
    value) and to no other route's, the plain cap and timeout (the ``overflow_max_tokens``
    state carries over only between Anthropic calls). ``refusal_reasoning`` (a dict) is the
    re-run's reasoning as given, instead of that rule.

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
    bounded budget once the primary needed them, and is itself never re-asked.

    ``backend`` (default ``$WSB_JUDGE_BACKEND``, else ``live``): ``batches`` sends the Anthropic
    requests through Message Batches first (see :class:`_BatchRound`); ``concurrency``, ``rpm``
    and ``timeout`` then bound only the calls that still run live (a batch answer that stopped
    at ``max_tokens`` is one of those, so the ``overflow_max_tokens`` re-ask applies to it)."""
    spend = spend or Spend()
    if not prompts:
        return spend
    if concurrency < 1 or rpm <= 0:
        raise JudgeConfigError(f"concurrency must be >= 1 and rpm > 0 (got {concurrency}, {rpm})")
    route_ = route(model)
    key = api_key(model)
    if refusal_model is not None and refusal_model == model:
        raise JudgeConfigError(f"refusal_model={refusal_model!r} must be another model")
    # a refusal model on the other route: its key before any call, its own client and knobs
    fb_route = route_ if refusal_model is None else route(refusal_model)
    cross = fb_route != route_
    fb_key = api_key(refusal_model) if cross and refusal_model is not None else key
    fb_kw: dict[str, Any] = {}
    if cross:
        fb_kw = {
            "reasoning": reasoning_for(fb_route, reasoning),
            "temperature": temperature if fb_route == "openrouter" else None,
            "max_tokens": _capped(
                fb_route, _DEFAULT_MAX_TOKENS[fb_route] if max_tokens is None else max_tokens
            ),
            "timeout": timeout,
            "attempts": attempts,
        }
    if refusal_reasoning is not None:
        fb_kw["reasoning"] = refusal_reasoning
    if temperature is not None and route_ == "anthropic":
        print(f"  llm: dropping temperature={temperature} for {model} (Anthropic route rejects it)")
        temperature = None
    if temperature is not None and route_ == "openai":
        print(f"  llm: dropping temperature={temperature} for {model} (OpenAI reasoning models)")
        temperature = None
    if max_tokens is None:
        max_tokens = _DEFAULT_MAX_TOKENS[route_]
    # the chat routes' output budget, up AND down (a same-route re-run shares it)
    max_tokens = _capped(route_, max_tokens)
    client = _make_client(route_, key)
    try:
        fb_client = _make_client(fb_route, fb_key) if cross else client
    except BaseException:
        await client.close()
        raise
    sem = asyncio.Semaphore(concurrency)
    grow = (
        route_ == "anthropic"
        and overflow_max_tokens is not None
        and overflow_max_tokens > max_tokens
    )
    batch: _BatchRound | None = None
    if route_ == "anthropic" and judge_backend(backend) == "batches":
        from wsbench import judge_batches

        settings = judge_batches.Settings.from_env(BATCH_ENV_PREFIX)
        if len(prompts) >= settings.min_requests:
            batch = _BatchRound(
                client,
                prompts,
                settings,
                schema=schema,
                model=model,
                max_tokens=max_tokens,
                reasoning=reasoning,
                spend=spend,
                mark_refusals=mark_refusals or refusal_model is not None,
                fallbacks=fallbacks,
                mark_truncated=grow,
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
        res: Any = _RUN_LIVE if batch is None else await batch.answers[i]
        async with sem:
            if res is _RUN_LIVE:
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
                    fb_route,
                    fb_client,
                    system,
                    user,
                    model=refusal_model,
                    mark_refusals=True,
                    **(kw | fb_kw),
                )
                if isinstance(again, dict) and again not in (REFUSED_JSON, TOO_LONG_JSON):
                    again = {**again, SERVED_BY: refusal_model}
                res = again
        if not mark_refusals and res in (REFUSED_JSON, TOO_LONG_JSON):
            res = None  # the caller did not ask for markers
        return i, res

    tasks = [asyncio.ensure_future(one(i, s, u)) for i, (s, u) in enumerate(prompts)]
    if batch is not None:
        tasks.append(asyncio.ensure_future(batch.run()))
    try:
        for fut in asyncio.as_completed(tasks):
            landed = await fut
            if landed is not None:  # None: the batch round itself finished
                on_result(*landed)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await client.close()
        finally:
            if fb_client is not client:
                await fb_client.close()
    return spend


_RUN_LIVE: Any = object()  # a batch round's answer for "ask this one through the live path"


class _BatchRound:
    """One prompt list's trip through Message Batches. Each request is the live call's request
    (:func:`anthropic_params`), minus ``fallbacks`` (a batch request cannot set it).
    ``answers[i]`` resolves to prompt ``i``'s parsed result, or to ``_RUN_LIVE`` for whatever
    the batch did not settle: an errored / expired / canceled / missing entry, an unparsable
    body, and a refusal when ``fallbacks`` is set (the live call re-runs it on the fallback)."""

    def __init__(
        self,
        client: Any,
        prompts: list[tuple[str, str]],
        settings: Any,
        *,
        schema: dict[str, Any],
        model: str,
        max_tokens: int,
        reasoning: dict[str, Any] | None,
        spend: Spend,
        mark_refusals: bool,
        fallbacks: str | None,
        mark_truncated: bool = False,
    ) -> None:
        from wsbench import judge_batches

        self.client = client
        self.settings = settings
        self.model = model
        self.spend = spend
        self.mark_refusals = mark_refusals
        self.fallbacks = fallbacks
        self.mark_truncated = mark_truncated  # overflow_max_tokens: the live path re-asks
        self.max_tokens = max_tokens
        params = [
            anthropic_params(
                # the live path's surrogate repair (see _one)
                system.encode("utf-8", "replace").decode("utf-8"),
                user.encode("utf-8", "replace").decode("utf-8"),
                schema=schema,
                model=model,
                max_tokens=max_tokens,
                reasoning=reasoning,
            )
            for system, user in prompts
        ]
        ids = judge_batches.unique_ids(params)
        self.requests = list(zip(ids, params, strict=True))
        self.index = {cid: i for i, cid in enumerate(ids)}
        loop = asyncio.get_running_loop()
        self.answers: list[asyncio.Future[Any]] = [loop.create_future() for _ in prompts]

    def _entry(self, custom_id: str, result: Any) -> None:
        fut = self.answers[self.index[custom_id]]
        if fut.done():
            return
        if getattr(result, "type", None) != "succeeded":
            fut.set_result(_RUN_LIVE)
            return
        msg = result.message
        if self.fallbacks is not None and getattr(msg, "stop_reason", None) == "refusal":
            ledger(self.model, getattr(msg, "usage", None), batch=True)
            fut.set_result(_RUN_LIVE)
            return
        try:
            fut.set_result(
                _anthropic_result(
                    msg,
                    model=self.model,
                    spend=self.spend,
                    mark_refusals=self.mark_refusals,
                    batch=True,
                    mark_truncated=self.mark_truncated,
                    max_tokens=self.max_tokens,
                )
            )
        except ValueError:  # an unparsable body (JSONDecodeError included): live retries it
            fut.set_result(_RUN_LIVE)

    async def run(self) -> None:
        from wsbench import judge_batches

        print(f"  batches: {len(self.requests)} request(s) for {self.model}")
        try:
            await judge_batches.run(
                self.client, self.requests, self._entry, settings=self.settings, sleep=_sleep
            )
        except Exception as e:
            name = type(e).__name__
            if name in _FATAL or getattr(e, "status_code", None) in (401, 402, 403):
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
            # the Batches API itself is failing: nothing is lost, the live path takes over
            print(f"  batches: {name}: {str(e)[:200]}; unanswered requests run live")
        for fut in self.answers:
            if not fut.done():
                fut.set_result(_RUN_LIVE)


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
    backend: str | None = None,
    overflow_max_tokens: int | None = None,
    refusal_reasoning: dict[str, Any] | None = None,
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
            backend=backend,
            overflow_max_tokens=overflow_max_tokens,
            refusal_reasoning=refusal_reasoning,
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
        backend="live",  # a preflight is one call, answered now
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
# Used by agentic_misalignment (three free-text stages, no schema). Every route (plan 0096):
# streaming (the Anthropic SDK refuses non-streaming requests whose max_tokens implies a >10 min
# operation), per-call thinking on/off, and a budget-doubling retry when the text is empty and
# the stop is the output cap (thinking ate the budget), up to _TEXT_BUDGET_CEILING.

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


async def _chat_text(
    create: Callable[[int], Any],
    *,
    model: str,
    max_tokens: int,
    spend: Spend,
    mark_refusals: bool,
) -> str | None:
    """The streamed free-text loop of the two chat routes: ``create(budget)`` opens one stream.
    Returns the stripped text (``""`` valid), or ``None`` / :data:`REFUSED` for a refusal
    (``finish_reason`` content_filter, or a refusal with no text); an empty answer cut at the
    output cap doubles the budget up to ``_TEXT_BUDGET_CEILING``. A stream that ends in
    ``finish_reason`` error or without any choice raises ``ValueError`` (retried by
    :func:`_one_text`); the stream is closed on every exit path."""
    budget = max_tokens
    while True:
        stream = await create(budget)
        parts: list[str] = []
        refusal: list[str] = []
        finish: str | None = None
        usage: Any = None
        seen = False  # a chunk with choices arrived
        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage  # the final chunk's
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                seen = True
                delta = getattr(choices[0], "delta", None)
                if getattr(delta, "content", None):
                    parts.append(delta.content)
                if getattr(delta, "refusal", None):
                    refusal.append(delta.refusal)
                if getattr(choices[0], "finish_reason", None) is not None:
                    finish = choices[0].finish_reason
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                await close()
        spend.calls += 1
        spend.usd += _openrouter_cost(usage)
        if usage is not None:
            spend.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            spend.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        if finish == "error":  # a provider error delivered inside the stream
            raise ValueError("stream ended with finish_reason=error")
        if not seen:
            raise ValueError("stream has no choices")
        txt = "".join(parts).strip()
        if finish == "content_filter" or ("".join(refusal).strip() and not txt):
            spend.refusals += 1
            print(f"  llm refusal: {model}")
            return REFUSED if mark_refusals else None
        if not txt and finish == "length" and budget < _TEXT_BUDGET_CEILING:
            budget = min(budget * 2, _TEXT_BUDGET_CEILING)  # providers 400 above their cap
            continue
        return txt


async def _openrouter_text_once(
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
    """The OpenRouter twin of :func:`_anthropic_text_once`, same contract (:func:`_chat_text`).
    With no schema, a refusal written as ordinary content is an answer. ``thinking`` asks for
    OpenRouter's default (medium) reasoning; a no-thinking stage runs at
    :data:`OPENROUTER_MIN_REASONING`, since some models cannot turn reasoning off."""

    async def create(budget: int) -> Any:
        return await client.chat.completions.create(
            stream=True,
            stream_options={"include_usage": True},
            timeout=timeout,
            model=model,
            max_tokens=budget,
            messages=[{"role": "user", "content": user}],
            extra_body={
                "usage": {"include": True},
                "provider": {"require_parameters": True},
                "reasoning": {"enabled": True} if thinking else dict(OPENROUTER_MIN_REASONING),
            },
        )

    return await _chat_text(
        create, model=model, max_tokens=max_tokens, spend=spend, mark_refusals=mark_refusals
    )


async def _openai_text_once(
    wif: Any,
    user: str,
    *,
    model: str,
    thinking: bool,
    max_tokens: int,
    timeout: float,
    spend: Spend,
    mark_refusals: bool = False,
) -> str | None:
    """The ``openai``-route twin, same contract (:func:`_chat_text`): ``max_completion_tokens``,
    no ``extra_body``; ``thinking`` sends no ``reasoning_effort`` (the model's default), a
    no-thinking stage the lowest effort the route takes (:func:`_openai_effort`). A 401
    re-exchanges the token (:func:`_wif_create`)."""
    from wsbench.baselines import ati_remote

    async def create(budget: int) -> Any:
        kwargs: dict[str, Any] = {
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": timeout,
            "model": ati_remote.route_model(model, "openai-wif"),
            "max_completion_tokens": budget,
            "messages": [{"role": "user", "content": user}],
        }
        if not thinking:
            kwargs["reasoning_effort"] = _openai_effort(OPENROUTER_MIN_REASONING["effort"])
        return await _wif_create(wif, kwargs)

    return await _chat_text(
        create, model=model, max_tokens=max_tokens, spend=spend, mark_refusals=mark_refusals
    )


async def _one_text(
    route_: Route,
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
    """Same backoff / fatal classification as :func:`_one`, for one free-text call, with its
    OpenRouter moderation rule (a 403 naming the flagged input is one refusal; OpenRouter only:
    on the ``openai`` route every 403 is fatal). On the two chat routes an SDK ``APIError``
    without a status is an error event inside the stream: it is classified by its body's
    ``code`` like an HTTP status (fatal, moderation, transient), and is transient when it
    carries none."""
    user = user.encode("utf-8", "replace").decode("utf-8")
    once = {
        "anthropic": _anthropic_text_once,
        "openrouter": _openrouter_text_once,
        "openai": _openai_text_once,
    }[route_]
    await _pace_tokens(len(user) // 3)  # once per call, not per retry
    for attempt in range(_ATTEMPTS):
        await _pace(rpm)
        try:
            async with _slot():
                return await once(
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
            if isinstance(e, JudgeConfigError):  # e.g. the openai route's failed token exchange
                raise
            name = type(e).__name__
            status = getattr(e, "status_code", None)
            if _out_of_quota(e):  # a spend limit fails every call: never 12 backoffs each
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
            if route_ in _CHAT_ROUTES and name == "APIError" and status is None:
                # an error event inside the stream has no HTTP status: classify it by its code
                body = getattr(e, "body", None)
                code = body.get("code") if isinstance(body, dict) else None
                status = code if isinstance(code, int) else None
                stream_error = True
            else:
                stream_error = False
            if route_ == "openrouter" and status == 403 and _moderation_flagged(e):
                spend.refusals += 1  # one prompt flagged by moderation, not a config error
                print(f"  llm refusal (moderation): {model}")
                return REFUSED if mark_refusals else None
            if (name in _FATAL and not stream_error) or status in (401, 402, 403):
                raise JudgeConfigError(f"{name}: {str(e)[:300]}") from e
            transient = (
                status in _TRANSIENT
                or "Timeout" in name
                or "Connection" in name
                or "Deadline" in name
                or isinstance(e, json.JSONDecodeError | ValueError)
                or name == "TransientExchangeError"  # openai route: token endpoint 429 / 5xx
                or (stream_error and status is None)  # no code: a dropped / garbled stream
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
    """Run user-only free-text prompts concurrently on the model's route (every route since
    plan 0096; no system block, no schema), handing each stripped text (or ``None`` = exhausted
    retries / non-transient error / refusal; with ``mark_refusals`` a refusal is :data:`REFUSED`
    instead) to ``on_result(index, text)`` as it lands. ``""`` is a valid result (the
    source returns it after the 64k budget ceiling). Builds no client when there is nothing to
    call.

    ``refusal_model`` (client-side): a prompt ``model`` declines is re-run ONCE on
    that model with the same settings; when it serves, ``on_served(index, refusal_model)`` fires
    just before ``on_result`` (the text itself carries no provenance). It must be another model
    and may be on any route: on another route its key is resolved before any call and a
    second client is built (:func:`stream_json_async`). On a chat route (``openrouter``,
    ``openai``) ``WSBENCH_OPENROUTER_MAX_OUT`` is the STARTING budget of each call, by the route
    of the model called; the doubling still runs to ``_TEXT_BUDGET_CEILING``."""
    spend = spend or Spend()
    if not prompts:
        return spend
    if concurrency < 1 or rpm <= 0:
        raise JudgeConfigError(f"concurrency must be >= 1 and rpm > 0 (got {concurrency}, {rpm})")
    route_ = route(model)
    key = api_key(model)
    if refusal_model is not None and refusal_model == model:
        raise JudgeConfigError(f"refusal_model={refusal_model!r} must be another model")
    fb_route = route_ if refusal_model is None else route(refusal_model)
    cross = fb_route != route_
    fb_key = api_key(refusal_model) if cross and refusal_model is not None else key
    budget, fb_budget = _capped(route_, max_tokens), _capped(fb_route, max_tokens)
    client = _make_client(route_, key)
    try:
        fb_client = _make_client(fb_route, fb_key) if cross else client
    except BaseException:
        await client.close()
        raise
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, user: str) -> tuple[int, str | None, str | None]:
        kw: dict[str, Any] = {
            "thinking": thinking,
            "timeout": timeout,
            "rpm": rpm,
            "spend": spend,
        }
        served: str | None = None
        async with sem:
            res = await _one_text(
                route_,
                client,
                user,
                model=model,
                max_tokens=budget,
                mark_refusals=mark_refusals or bool(refusal_model),
                **kw,
            )
            if refusal_model is not None and res == REFUSED:
                res = await _one_text(
                    fb_route,
                    fb_client,
                    user,
                    model=refusal_model,
                    max_tokens=fb_budget,
                    mark_refusals=True,
                    **kw,
                )
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
        try:
            await client.close()
        finally:
            if fb_client is not client:
                await fb_client.close()
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
