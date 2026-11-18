"""OpenRouter-shaped fake SDK clients for the plan-0096 tests: completions that can carry
``finish_reason`` / ``message.refusal``, a streaming variant, and a per-route client installer."""

from types import SimpleNamespace
from typing import Any

from wsbench import llm


class APIError(Exception):
    """SDK-shaped: what the OpenAI SDK raises from a stream iterator for SSE data with an
    ``error`` key (no ``status_code``)."""


class ModerationError(Exception):
    """OpenRouter's moderation 403: the body names the flagged input."""

    status_code = 403

    def __init__(self, message: str = "flagged"):
        super().__init__(message)
        self.body = {"code": 403, "metadata": {"flagged_input": "the prompt", "reasons": ["x"]}}


def usage(cost: float = 0.001, in_tok: int = 7, out_tok: int = 3) -> Any:
    return SimpleNamespace(cost=cost, prompt_tokens=in_tok, completion_tokens=out_tok)


def completion(
    content: str | None, *, finish_reason: str = "stop", refusal: str | None = None
) -> Any:
    """One non-streamed chat completion."""
    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=message)], usage=usage()
    )


def chunk(
    content: str | None = None, *, finish_reason: str | None = None, refusal: str | None = None
) -> Any:
    delta = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)], usage=None
    )


def text_stream(text: str, finish_reason: str = "stop", **kw: Any) -> list[Any]:
    """The chunks of one streamed answer: the text in two deltas, the finish chunk, then the
    usage chunk (no choices), as OpenRouter ends every stream."""
    half = len(text) // 2
    parts = [chunk(text[:half]), chunk(text[half:])] if text else [chunk("")]
    return [
        *parts,
        chunk(finish_reason=finish_reason, **kw),
        SimpleNamespace(choices=[], usage=usage()),
    ]


class FakeStream:
    """An async iterator over scripted chunks; an exception among them is raised in place."""

    def __init__(self, events: list[Any]):
        self.events = list(events)
        self.closed = False

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> Any:
        if not self.events:
            raise StopAsyncIteration
        ev = self.events.pop(0)
        if isinstance(ev, BaseException):
            raise ev
        return ev

    async def close(self) -> None:
        self.closed = True


class OpenRouterClient:
    """A fake ``AsyncOpenAI``: ``answer(model, kw)`` returns a :func:`completion` (or, for a
    ``stream=True`` request, a list of chunks) or raises. ``calls`` records every request,
    ``streams`` every stream handed out, ``closed`` whether the client was closed."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict[str, Any]] = []
        self.streams: list[FakeStream] = []
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        out = self.answer(kw["model"], kw)
        if isinstance(out, BaseException):
            raise out
        if kw.get("stream"):
            self.streams.append(FakeStream(out))
            return self.streams[-1]
        return out

    async def close(self) -> None:
        self.closed = True


def quiet(monkeypatch) -> None:
    """No pacing, no backoff sleep, both keys present."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: None)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_pace", no_pace)


def install_routes(monkeypatch, **clients: Any) -> list[str]:
    """Put one fake client per route behind ``llm._make_client`` (``anthropic=``,
    ``openrouter=``); returns the list every built route is appended to. A route without a
    client fails the test when it is built."""
    quiet(monkeypatch)
    built: list[str] = []

    def make(route: str, key: str) -> Any:
        built.append(route)
        assert route in clients, f"no client expected on the {route} route"
        return clients[route]

    monkeypatch.setattr(llm, "_make_client", make)
    return built
