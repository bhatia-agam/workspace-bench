"""Plan 0092: the process-wide input-token pacer (``llm.set_itpm``, ``llm._TOKEN_PACER``) and the
per-family failed-call tally (``llm.error_tally``). Offline: fakes via ``_make_client``."""

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from wsbench import llm
from wsbench.llm import schema_block, stream_json, stream_text

SCHEMA = schema_block("t", {"a": {"type": "integer"}}, ["a"])
GEMINI = "google/gemini-3.8-flash"
CLAUDE = "claude-sonnet-5"
PROMPT = ("s" * 10, "u" * 20)  # (10 + 20) // 3 = an estimated 10 tokens


class RateLimitError(Exception):
    status_code = 429


class BadRequestError(Exception):
    status_code = 400


def _ok() -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"a": 1}'))],
        usage=SimpleNamespace(cost=0.0),
    )


class FakeOpenRouter:
    def __init__(self, outcomes: list[Any]):
        self.outcomes = list(outcomes)
        self.n = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kw: Any) -> Any:
        self.n += 1
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    async def close(self) -> None:
        return None


class FakeStream:
    def __init__(self, resp: Any):
        self.resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get_final_message(self) -> Any:
        return self.resp


class FakeAnthropicStream:
    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw: Any) -> FakeStream:
        return FakeStream(
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=self.texts.pop(0))],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def clock(monkeypatch):
    """A frozen clock, a recording ``_sleep``, no request pacing, no backoff, both API keys."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_sleep", fake_sleep)
    monkeypatch.setattr(llm, "_pace", no_pace)
    return slept


@pytest.fixture
def reserved(monkeypatch):
    """Every ``(tokens, itpm)`` the token pacer was asked to reserve."""
    seen: list[tuple[int, float]] = []
    orig = llm._TOKEN_PACER.reserve

    def reserve(tokens: int, itpm: float) -> float:
        seen.append((tokens, itpm))
        return orig(tokens, itpm)

    monkeypatch.setattr(llm._TOKEN_PACER, "reserve", reserve)
    return seen


def _json(monkeypatch, fake, prompts, **kw) -> tuple[dict, llm.Spend]:
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    got: dict[int, dict | None] = {}
    spend = stream_json(
        prompts,
        schema=SCHEMA,
        model=GEMINI,
        on_result=lambda i, r: got.__setitem__(i, r),
        concurrency=1,
        **kw,
    )
    return got, spend


def test_off_by_default_no_delay_and_no_reservation(clock, reserved, monkeypatch):
    assert llm._ITPM == 0
    got, _ = _json(monkeypatch, FakeOpenRouter([_ok(), _ok()]), [PROMPT, PROMPT])
    assert got == {0: {"a": 1}, 1: {"a": 1}}
    assert clock == [] and reserved == []
    asyncio.run(llm._pace_tokens(10**12))  # returns at once whatever the size
    assert clock == [] and reserved == []


def test_three_calls_of_ten_tokens_are_one_second_apart(clock, reserved, monkeypatch):
    llm.set_itpm(600)  # 10 tokens a second
    got, _ = _json(monkeypatch, FakeOpenRouter([_ok()] * 3), [PROMPT] * 3)
    assert len(got) == 3
    assert reserved == [(10, 600.0)] * 3
    assert clock == [pytest.approx(1.0), pytest.approx(2.0)]  # the first call starts at once


def test_reserve_slots_and_reset(monkeypatch):
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    p = llm._TokenPacer()
    assert p.reserve(10, 600.0) == 0.0
    assert p.reserve(30, 600.0) == pytest.approx(1.0)
    assert p.reserve(10, 600.0) == pytest.approx(4.0)  # the 30-token call took three seconds
    monkeypatch.setattr(llm, "_now", lambda: 200.0)
    assert p.reserve(10, 600.0) == 0.0  # an idle budget does not accumulate a debt
    p.reset()
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    assert p.reserve(10, 600.0) == 0.0


def test_reserve_is_thread_safe(monkeypatch):
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    p = llm._TokenPacer()
    delays: list[float] = []
    lock = threading.Lock()

    def work() -> None:
        for _ in range(200):
            d = p.reserve(10, 600.0)
            with lock:
                delays.append(d)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 1,600 reservations of one second each: every slot handed out exactly once
    assert sorted(delays) == pytest.approx([float(k) for k in range(1600)])


def test_one_reservation_per_call_across_retries(clock, reserved, monkeypatch):
    llm.set_itpm(600)
    fake = FakeOpenRouter([RateLimitError("slow"), RateLimitError("slow"), _ok()])
    got, spend = _json(monkeypatch, fake, [PROMPT])
    assert got == {0: {"a": 1}} and spend.retries == 2 and fake.n == 3
    assert reserved == [(10, 600.0)]


def test_a_call_above_the_whole_budget_still_runs(clock, reserved, monkeypatch):
    llm.set_itpm(600)
    big = ("s" * 3000, "u" * 3000)  # 2,000 tokens against 600 a minute
    fake = FakeOpenRouter([_ok(), _ok()])
    got, _ = _json(monkeypatch, fake, [big, PROMPT])
    assert got == {0: {"a": 1}, 1: {"a": 1}} and fake.n == 2
    assert reserved == [(2000, 600.0), (10, 600.0)]
    assert clock == [pytest.approx(200.0)]  # the big call starts at once; the next one queues


def test_set_itpm_zero_turns_it_off_again(clock, reserved, monkeypatch):
    llm.set_itpm(600)
    assert llm._ITPM == 600.0
    llm.set_itpm(0)
    assert llm._ITPM == 0
    _json(monkeypatch, FakeOpenRouter([_ok()] * 2), [PROMPT] * 2)
    assert clock == [] and reserved == []


def test_fixture_leaves_the_budget_off():
    """``conftest._reset_pacer`` resets what an earlier test (or ``main([...])``) set."""
    assert llm._ITPM == 0 and llm._TOKEN_PACER._next == 0.0


def test_text_call_reserves_its_user_prompt(clock, reserved, monkeypatch):
    llm.set_itpm(600)
    monkeypatch.setattr(llm, "_make_client", lambda route, key: FakeAnthropicStream(["a", "b"]))
    got: dict[int, str | None] = {}
    stream_text(
        ["u" * 30, "u" * 30],
        model=CLAUDE,
        on_result=lambda i, r: got.__setitem__(i, r),
        thinking=False,
        max_tokens=100,
        concurrency=1,
    )
    assert got == {0: "a", 1: "b"}
    assert reserved == [(10, 600.0)] * 2 and clock == [pytest.approx(1.0)]


# ---------------------------------------------------------------- the failed-call tally (2b)


def test_error_tally_counts_failed_calls_in_its_context_only(clock, monkeypatch):
    fake = FakeOpenRouter([BadRequestError("bad"), _ok(), BadRequestError("bad")])
    with llm.error_tally() as tally:
        got, spend = _json(monkeypatch, fake, [PROMPT, PROMPT])
    assert got == {0: None, 1: {"a": 1}} and spend.errors == 1 and tally.n == 1
    got, spend = _json(monkeypatch, fake, [PROMPT])  # outside any tally: Spend only
    assert got == {0: None} and spend.errors == 1 and tally.n == 1


def test_error_tally_counts_exhausted_retries_once(clock, monkeypatch):
    fake = FakeOpenRouter([RateLimitError("slow")] * llm._ATTEMPTS)
    with llm.error_tally() as tally:
        got, spend = _json(monkeypatch, fake, [PROMPT])
    assert got == {0: None} and fake.n == llm._ATTEMPTS
    assert spend.errors == 1 and spend.retries == llm._ATTEMPTS - 1 and tally.n == 1


def test_error_tally_skips_a_too_long_bundle(clock, monkeypatch):
    """A "prompt is too long" 400 under ``mark_refusals`` is re-asked in halves by the digest: it
    is counted in ``Spend.errors`` but is not a lost call, so the 2b line stays quiet."""
    fake = FakeOpenRouter([BadRequestError("Prompt is too long: 250000 tokens")])
    with llm.error_tally() as tally:
        got, spend = _json(monkeypatch, fake, [PROMPT], mark_refusals=True)
    assert got == {0: llm.TOO_LONG_JSON} and spend.errors == 1 and tally.n == 0
    fake = FakeOpenRouter([BadRequestError("Prompt is too long: 250000 tokens")])
    with llm.error_tally() as tally:  # without mark_refusals it IS a lost call
        got, spend = _json(monkeypatch, fake, [PROMPT])
    assert got == {0: None} and spend.errors == 1 and tally.n == 1


# ---------------------------------------------------------------- cross-process slots


def test_slots_off_without_the_variable(clock, monkeypatch):
    monkeypatch.delenv(llm.SLOTS_ENV, raising=False)
    got, _ = _json(monkeypatch, FakeOpenRouter([_ok()]), [PROMPT])
    assert got == {0: {"a": 1}} and clock == []


def test_slots_bound_calls_in_flight_and_are_released(tmp_path, monkeypatch):
    d = tmp_path / "slots"
    monkeypatch.setenv(llm.SLOTS_ENV, f"{d}:2")
    a, b = llm._try_slot(str(d), 2, tries=64), llm._try_slot(str(d), 2, tries=64)
    assert a is not None and b is not None
    assert llm._try_slot(str(d), 2, tries=64) is None  # both taken (flock is per open file)
    import os

    os.close(a)
    c = llm._try_slot(str(d), 2, tries=64)
    assert c is not None
    os.close(b), os.close(c)


def test_a_call_waits_for_a_slot_then_runs(clock, tmp_path, monkeypatch):
    d = tmp_path / "slots"
    monkeypatch.setenv(llm.SLOTS_ENV, f"{d}:1")
    held = llm._try_slot(str(d), 1)
    import os

    async def sleep_then_free(delay):
        clock.append(delay)
        if held in fds:
            os.close(fds.pop())

    fds = [held]
    monkeypatch.setattr(llm, "_sleep", sleep_then_free)
    got, _ = _json(monkeypatch, FakeOpenRouter([_ok()]), [PROMPT])
    assert got == {0: {"a": 1}} and len(clock) == 1 and fds == []
    assert llm._try_slot(str(d), 1) is not None  # the call released its slot


def test_bad_slots_value_is_a_config_error(monkeypatch):
    monkeypatch.setenv(llm.SLOTS_ENV, "nodir")
    with pytest.raises(llm.JudgeConfigError):
        llm._slots_config()
