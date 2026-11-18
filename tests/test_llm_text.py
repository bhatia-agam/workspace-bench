"""Offline tests for the free-text streaming primitive (``stream_text`` / ``stream_text_async``):
a fake ``messages.stream`` context manager is injected via ``_make_client``."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from openrouter_fakes import APIError, ModerationError, OpenRouterClient, chunk, text_stream

from wsbench import llm
from wsbench.llm import JudgeConfigError, Spend, stream_text, stream_text_async

CLAUDE = "claude-sonnet-5"
GEMINI = "google/gemini-3.8-flash"


class RateLimitError(Exception):
    status_code = 429


class AuthenticationError(Exception):
    status_code = 401


class BadRequestError(Exception):
    status_code = 400


def text_response(text: str, stop_reason: str = "end_turn", in_tok: int = 7, out_tok: int = 3):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking="hmm"),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


class FakeStream:
    def __init__(self, resp: Any):
        self.resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get_final_message(self) -> Any:
        if isinstance(self.resp, BaseException):
            raise self.resp
        return self.resp


class FakeAnthropicStream:
    """``outcomes`` is a shared queue: a response object, a str (-> end_turn response) or an
    exception (raised from ``get_final_message``)."""

    def __init__(self, outcomes: list[Any]):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw: Any) -> FakeStream:
        self.calls.append(kw)
        out = self.outcomes.pop(0)
        if isinstance(out, str):
            out = text_response(out)
        return FakeStream(out)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_pace", no_pace)


def _collect(prompts, fake, monkeypatch, *, model=CLAUDE, thinking=False, max_tokens=400, **kw):
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    got: dict[int, str | None] = {}
    spend = stream_text(
        prompts,
        model=model,
        on_result=lambda i, r: got.__setitem__(i, r),
        thinking=thinking,
        max_tokens=max_tokens,
        **kw,
    )
    return got, spend


def test_success_shape_thinking_off(keys, fast, monkeypatch):
    fake = FakeAnthropicStream(["  a note  "])
    got, spend = _collect(["usr"], fake, monkeypatch, thinking=False, max_tokens=400)
    assert got == {0: "a note"}  # stripped, thinking block ignored
    assert spend.calls == 1 and spend.input_tokens == 7 and spend.output_tokens == 3
    assert spend.errors == 0 and spend.refusals == 0 and spend.usd == 0.0
    kw = fake.calls[0]
    assert kw["model"] == CLAUDE and kw["max_tokens"] == 400
    assert kw["thinking"] == {"type": "disabled"}
    assert kw["messages"] == [{"role": "user", "content": "usr"}]
    assert "system" not in kw and "output_config" not in kw
    assert kw["timeout"] == 600.0
    assert fake.closed


def test_thinking_on(keys, fast, monkeypatch):
    fake = FakeAnthropicStream(["x"])
    _collect(["u"], fake, monkeypatch, thinking=True, max_tokens=16000)
    assert fake.calls[0]["thinking"] == {"type": "adaptive"}
    assert fake.calls[0]["max_tokens"] == 16000


def test_budget_doubling_on_empty_max_tokens(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([text_response("", "max_tokens"), "done"])
    got, spend = _collect(["u"], fake, monkeypatch, thinking=True, max_tokens=3000)
    assert got == {0: "done"}
    assert [c["max_tokens"] for c in fake.calls] == [3000, 6000]
    assert spend.calls == 2 and spend.retries == 0 and spend.errors == 0


def test_budget_ceiling_returns_empty_string(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([text_response("", "max_tokens")] * 3)
    got, spend = _collect(["u"], fake, monkeypatch, thinking=True, max_tokens=32000)
    assert got == {0: ""}  # a valid (cacheable) result, as the source returns it
    assert [c["max_tokens"] for c in fake.calls] == [32000, 64000]
    assert spend.calls == 2 and spend.errors == 0


def test_nonempty_text_with_max_tokens_is_returned(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([text_response("partial", "max_tokens")])
    got, _ = _collect(["u"], fake, monkeypatch)
    assert got == {0: "partial"} and len(fake.calls) == 1


def test_refusal_is_none_not_cached(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([text_response("", "refusal")])
    got, spend = _collect(["u"], fake, monkeypatch)
    assert got == {0: None}
    assert spend.refusals == 1 and spend.errors == 0 and len(fake.calls) == 1


def test_transient_then_success(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([RateLimitError("slow"), "ok"])
    got, spend = _collect(["u"], fake, monkeypatch)
    assert got == {0: "ok"} and spend.retries == 1 and spend.errors == 0 and spend.calls == 1


def test_non_transient_error_is_none(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([BadRequestError("bad")])
    got, spend = _collect(["u"], fake, monkeypatch)
    assert got == {0: None} and spend.errors == 1 and spend.retries == 0


def test_exhausted_retries_is_none(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([RateLimitError("slow")] * 12)
    got, spend = _collect(["u"], fake, monkeypatch)
    assert got == {0: None} and spend.retries == 11 and spend.errors == 1
    assert fake.outcomes == []


def test_fatal_raises_and_closes(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([AuthenticationError("bad key")])
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    with pytest.raises(JudgeConfigError):
        stream_text(["u"], model=CLAUDE, on_result=lambda i, r: None, thinking=False, max_tokens=1)
    assert fake.closed


def test_openrouter_model_raises(keys, fast, monkeypatch):
    """Plan 0096: an OpenRouter model is no longer refused (the free-text stage runs on both
    routes); what still raises before any client is built is a missing OpenRouter key."""
    fake = OpenRouterClient(lambda model, kw: text_stream("ok"))
    got, _spend = _collect(["u"], fake, monkeypatch, model=GEMINI, max_tokens=1)
    assert got == {0: "ok"} and fake.closed

    def boom(route, key):
        raise AssertionError("client must not be built")

    monkeypatch.setattr(llm, "_make_client", boom)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(JudgeConfigError, match="OPENROUTER_API_KEY"):
        stream_text(["u"], model=GEMINI, on_result=lambda i, r: None, thinking=False, max_tokens=1)


def test_empty_prompts_build_no_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def boom(route, key):
        raise AssertionError("client must not be built")

    monkeypatch.setattr(llm, "_make_client", boom)
    spend = stream_text([], model=CLAUDE, on_result=lambda i, r: None, thinking=False, max_tokens=1)
    assert spend.calls == 0


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(JudgeConfigError):
        stream_text(["u"], model=CLAUDE, on_result=lambda i, r: None, thinking=False, max_tokens=1)


def test_bad_concurrency_and_rpm(keys, monkeypatch):
    monkeypatch.setattr(llm, "_make_client", lambda route, key: FakeAnthropicStream([]))
    for kw in ({"concurrency": 0}, {"rpm": 0}):
        with pytest.raises(JudgeConfigError):
            stream_text(
                ["u"], model=CLAUDE, on_result=lambda i, r: None, thinking=False, max_tokens=1, **kw
            )


def test_lone_surrogate_sanitised(keys, fast, monkeypatch):
    fake = FakeAnthropicStream(["ok"])
    _collect(["u\udfff x"], fake, monkeypatch)
    content = fake.calls[0]["messages"][0]["content"]
    content.encode("utf-8")  # must not raise
    assert content == "u? x"


def test_results_land_in_completion_order_and_spend_is_shared(keys, fast, monkeypatch):
    order: list[int] = []

    class Slow(FakeAnthropicStream):
        def _stream(self, **kw: Any) -> FakeStream:
            self.calls.append(kw)
            n = len(self.calls)

            class S(FakeStream):
                async def get_final_message(self) -> Any:
                    await asyncio.sleep(0.02 if n == 1 else 0.0)
                    return text_response(f"r{n}")

            return S(None)

    fake = Slow([])
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    spend = Spend()
    got: dict[int, str | None] = {}

    def on_result(i: int, r: str | None) -> None:
        order.append(i)
        got[i] = r

    stream_text(
        ["a", "b"], model=CLAUDE, on_result=on_result, thinking=False, max_tokens=1, spend=spend
    )
    assert order == [1, 0] and set(got.values()) == {"r1", "r2"}
    assert spend.calls == 2


def test_stream_text_inside_loop_raises_but_async_works(keys, fast, monkeypatch):
    fake = FakeAnthropicStream(["ok"])
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)

    async def inner():
        with pytest.raises(JudgeConfigError):
            stream_text(
                ["u"], model=CLAUDE, on_result=lambda i, r: None, thinking=False, max_tokens=1
            )
        got: dict[int, Any] = {}
        await stream_text_async(
            ["u"],
            model=CLAUDE,
            on_result=lambda i, r: got.__setitem__(i, r),
            thinking=False,
            max_tokens=1,
        )
        return got

    assert asyncio.run(inner()) == {0: "ok"}


def test_existing_json_primitive_untouched():
    """The concurrent-PR guard: the structured primitive keeps its signature."""
    import inspect

    p = inspect.signature(llm.stream_json_async).parameters
    assert {"prompts", "schema", "model", "on_result", "reasoning", "max_tokens"} <= set(p)
    t = inspect.signature(stream_text_async).parameters
    assert {"prompts", "model", "on_result", "thinking", "max_tokens", "concurrency", "rpm"} <= set(
        t
    )
    assert "schema" not in t and "reasoning" not in t


def test_real_stream_signature():
    """Guards the SDK call shape without any network."""
    import inspect

    from anthropic.resources.messages import AsyncMessages

    a = inspect.signature(AsyncMessages.stream).parameters
    assert {"thinking", "messages", "max_tokens", "model", "timeout"} <= set(a)


def test_refusal_can_be_marked(keys, fast, monkeypatch):
    fake = FakeAnthropicStream([text_response("", "refusal")])
    got: dict = {}
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    llm.stream_text(
        ["u"],
        model=CLAUDE,
        on_result=lambda i, t: got.__setitem__(i, t),
        thinking=False,
        max_tokens=10,
        mark_refusals=True,
    )
    assert got == {0: llm.REFUSED}


# ---------------------------------------------------------------- OpenRouter route (plan 0096)

LUNA = "openai/gpt-6-luna"


def _scripted(outcomes: list[Any]) -> OpenRouterClient:
    """An OpenRouter fake that hands out ``outcomes`` in order (chunk lists or exceptions)."""
    left = list(outcomes)
    return OpenRouterClient(lambda model, kw: left.pop(0))


@pytest.mark.parametrize(
    ("thinking", "reasoning"), [(True, {"enabled": True}), (False, {"effort": "minimal"})]
)
def test_openrouter_text_request_and_spend(keys, fast, monkeypatch, thinking, reasoning):
    fake = _scripted([text_stream("  a note  ")])
    got, spend = _collect(["usr"], fake, monkeypatch, model=LUNA, thinking=thinking)
    assert got == {0: "a note"}  # the deltas joined and stripped
    assert (spend.calls, spend.input_tokens, spend.output_tokens) == (1, 7, 3)
    assert spend.usd == pytest.approx(0.001) and spend.errors == 0 and spend.refusals == 0
    assert fake.calls == [
        {
            "stream": True,
            "stream_options": {"include_usage": True},
            "timeout": 600.0,
            "model": LUNA,
            "max_tokens": 400,
            "messages": [{"role": "user", "content": "usr"}],  # user only: no system block
            "extra_body": {
                "usage": {"include": True},
                "provider": {"require_parameters": True},
                "reasoning": reasoning,
            },
        }
    ]
    assert fake.streams[0].closed and fake.closed
    assert llm.OPENROUTER_MIN_REASONING == {"effort": "minimal"}  # the constant is not mutated


def test_openrouter_empty_at_the_cap_doubles_to_the_ceiling_then_returns_empty(
    keys, fast, monkeypatch
):
    fake = OpenRouterClient(lambda model, kw: text_stream("", "length"))
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA, max_tokens=16_000)
    assert got == {0: ""}  # valid, as on the Anthropic route
    assert [c["max_tokens"] for c in fake.calls] == [16_000, 32_000, 64_000]
    assert llm._TEXT_BUDGET_CEILING == 64_000 and spend.calls == 3 and spend.errors == 0
    # text at the cap is an answer: no doubling
    fake = _scripted([text_stream("cut off", "length")])
    got, _ = _collect(["u"], fake, monkeypatch, model=LUNA, max_tokens=16)
    assert got == {0: "cut off"} and len(fake.calls) == 1


@pytest.mark.parametrize("mark", [True, False])
def test_openrouter_text_refusals(keys, fast, monkeypatch, mark):
    want = {0: llm.REFUSED if mark else None}
    for outcome in (
        text_stream("partial", "content_filter"),  # filtered: a refusal even with text
        [chunk(refusal="I can't help with that"), chunk(finish_reason="stop")],
        ModerationError("flagged"),  # the moderation 403: one refusal, never a config error
    ):
        fake = _scripted([outcome])
        got, spend = _collect(["u"], fake, monkeypatch, model=LUNA, mark_refusals=mark)
        assert got == want and spend.refusals == 1 and spend.errors == 0 and len(fake.calls) == 1
    # with no schema, a refusal written as ordinary content is an answer
    fake = _scripted([text_stream("I can't help with that")])
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA, mark_refusals=mark)
    assert got == {0: "I can't help with that"} and spend.refusals == 0


def test_openrouter_stream_errors_are_retried(keys, fast, monkeypatch):
    broken = [
        [chunk("par"), APIError("Provider disconnected")],  # the SDK raises from the iterator
        [chunk("par"), chunk(finish_reason="error")],
        [SimpleNamespace(choices=[], usage=None)],  # ends with no chunk that has choices
    ]
    fake = _scripted([*broken, text_stream("whole")])
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA)
    assert got == {0: "whole"} and spend.retries == 3 and spend.errors == 0
    assert len(fake.streams) == 4 and all(s.closed for s in fake.streams)
    # an APIError WITH a non-transient status is still one failed call, not a retry
    fake = _scripted([BadRequestError("bad")])
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA)
    assert got == {0: None} and spend.retries == 0 and spend.errors == 1
    # on the Anthropic route a status-less APIError keeps its old classification (not transient)
    ant = FakeAnthropicStream([APIError("x")])
    got, spend = _collect(["u"], ant, monkeypatch)
    assert got == {0: None} and spend.retries == 0 and spend.errors == 1


def test_openrouter_fatal_still_raises(keys, fast, monkeypatch):
    fake = _scripted([AuthenticationError("bad key")])
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    with pytest.raises(JudgeConfigError):
        stream_text(["u"], model=LUNA, on_result=lambda i, r: None, thinking=False, max_tokens=1)
    assert fake.closed


def _stream_error(code):
    e = APIError("Provider returned error")
    e.body = {"code": code, "message": "x"}
    return e


def test_openrouter_stream_error_is_classified_by_its_code(keys, fast, monkeypatch):
    """An error event inside the stream has no HTTP status; its body's code decides (review of
    #505): a transient code is retried, a credits / auth code is fatal, any other is one error."""
    fake = _scripted([[chunk("par"), _stream_error(502)], text_stream("whole")])
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA)
    assert got == {0: "whole"} and spend.retries == 1 and spend.errors == 0
    fake = _scripted([[chunk("par"), _stream_error(400)], text_stream("never")])
    got, spend = _collect(["u"], fake, monkeypatch, model=LUNA)
    assert got == {0: None} and spend.retries == 0 and spend.errors == 1
    fake = _scripted([[chunk("par"), _stream_error(402)], text_stream("never")])
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    with pytest.raises(JudgeConfigError):
        llm.stream_text(
            ["u"], model=LUNA, on_result=lambda i, r: None, thinking=False, max_tokens=100
        )
