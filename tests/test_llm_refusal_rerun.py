"""The client-side refusal re-run (``llm`` ``refusal_model=``, ``summ_fallback=none+<model>``) and
the per-model digest output cap (``digest.OUTPUT_CAPS``). The llm tests drive the real primitives
through a fake SDK client that answers by model; the digest tests check the settings and the
requests of both digest stages, layered stage 2 included."""

from types import SimpleNamespace
from typing import Any

import pytest
from conftest import write_jsonl
from summary_fakes import FakeLLM, summary_args
from test_jailbreak_recognition import _fixture_bank

from wsbench import digest, llm
from wsbench.evals.safety.jailbreak_recognition import judge as jb
from wsbench.evals.safety.jailbreak_recognition import prompts as jbp

SONNET, OPUS5 = "claude-sonnet-5", "claude-opus-5"


def _resp(text: str, stop: str = "end_turn", model: str = SONNET) -> Any:
    return SimpleNamespace(
        stop_reason=stop,
        model=model,
        content=[SimpleNamespace(type="text", text=text)] if text else [],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


class _Stream:
    def __init__(self, resp: Any):
        self.resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get_final_message(self) -> Any:
        return self.resp


class ModelAwareClient:
    """A fake ``AsyncAnthropic``: ``answer(model, kw) -> response`` for ``messages.create``
    (structured calls) and ``messages.stream`` (free text). ``calls`` records every request."""

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create, stream=self._stream)

    async def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        return self.answer(kw["model"], kw)

    def _stream(self, **kw: Any) -> _Stream:
        self.calls.append(kw)
        return _Stream(self.answer(kw["model"], kw))

    async def close(self) -> None:
        return None

    def models(self, kind: str) -> list[str]:
        """The model of every call of one kind: digest (stage 1 and stage 2) / judge (other
        structured calls) / text (free text)."""
        out = []
        for kw in self.calls:
            fmt = (kw.get("output_config") or {}).get("format")
            k = "text" if fmt is None else ("digest" if is_digest(kw) else "judge")
            if k == kind:
                out.append(kw["model"])
        return out


def is_digest(kw: dict) -> bool:
    """A digest request: a stage-1 bundle (``READOUTS:``) or a layered stage-2 call."""
    return kw["messages"][0]["content"].startswith(("READOUTS:", "LAYER DIGESTS:"))


def fake_client_installer(monkeypatch):
    """``install(answer) -> ModelAwareClient``: puts a fake client behind the real llm primitives
    (no network, no key, no pacing, no backoff)."""
    monkeypatch.setattr(llm, "api_key", lambda model: "sk-ant-test")
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: None)
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_pace", no_pace)

    def install(answer) -> ModelAwareClient:
        fake = ModelAwareClient(answer)
        monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
        return fake

    return install


@pytest.fixture
def client(monkeypatch):
    return fake_client_installer(monkeypatch)


SCHEMA = llm.schema_block("t", {"a": {"type": "integer"}}, ["a"])


# ---------------------------------------------------------------- llm primitives


def _json_once(client_answer, client, **kw):
    fake = client(client_answer)
    got: dict[int, Any] = {}
    spend = llm.stream_json(
        [("s", "u")], schema=SCHEMA, model=SONNET, on_result=got.__setitem__, **kw
    )
    return fake, got[0], spend


def test_refusal_model_reruns_a_declined_structured_call(client):
    def answer(model, kw):
        return _resp("", "refusal") if model == SONNET else _resp('{"a": 1}', model=OPUS5)

    fake, res, spend = _json_once(answer, client, refusal_model=OPUS5)
    assert res == {"a": 1, llm.SERVED_BY: OPUS5}
    assert [c["model"] for c in fake.calls] == [SONNET, OPUS5]
    # the same request (system, user, schema, cap) on the other model; no server-side fallbacks
    first, again = fake.calls
    assert {k: v for k, v in again.items() if k != "model"} == {
        k: v for k, v in first.items() if k != "model"
    }
    assert "fallbacks" not in again and "betas" not in again
    assert spend.refusals == 1


def test_refusal_model_only_moves_refusals(client):
    # a max_tokens stop is the primary's outcome: no re-run
    fake, res, spend = _json_once(
        lambda m, kw: _resp('{"a":', "max_tokens"), client, refusal_model=OPUS5
    )
    assert res is None and [c["model"] for c in fake.calls] == [SONNET] and spend.errors == 1
    # both decline: None, or the refusal marker when the caller asks for markers
    fake, res, _ = _json_once(lambda m, kw: _resp("", "refusal"), client, refusal_model=OPUS5)
    assert res is None and [c["model"] for c in fake.calls] == [SONNET, OPUS5]
    _fake, res, _ = _json_once(
        lambda m, kw: _resp("", "refusal"), client, refusal_model=OPUS5, mark_refusals=True
    )
    assert res == llm.REFUSED_JSON
    # without refusal_model nothing changes: one call, a refusal is None
    fake, res, _ = _json_once(lambda m, kw: _resp("", "refusal"), client)
    assert res is None and len(fake.calls) == 1


def _cut_at(cap: int):
    """A model whose answer does not fit ``cap`` output tokens."""

    def answer(model, kw):
        if kw["max_tokens"] <= cap:
            return _resp('{"a":', "max_tokens")
        return _resp('{"a": 1}')

    return answer


def test_overflow_max_tokens_reasks_a_truncated_call_once_with_the_larger_cap(client):
    fake, res, spend = _json_once(
        _cut_at(100), client, max_tokens=100, overflow_max_tokens=200, timeout=50.0
    )
    assert res == {"a": 1} and spend.errors == 0 and spend.calls == 2
    first, again = fake.calls
    assert (first["max_tokens"], again["max_tokens"]) == (100, 200)
    assert (first["timeout"], again["timeout"]) == (50.0, 100.0)  # scaled with the cap
    same = lambda kw: {k: v for k, v in kw.items() if k not in ("max_tokens", "timeout")}  # noqa: E731
    assert same(first) == same(again)  # the same request otherwise
    # still truncated at the larger cap: the call's outcome, one counted error, no third try
    fake, res, spend = _json_once(_cut_at(200), client, max_tokens=100, overflow_max_tokens=200)
    assert res is None and [c["max_tokens"] for c in fake.calls] == [100, 200]
    assert spend.errors == 1
    # a call that fits is one unchanged request; a cap that is no larger asks nothing twice
    fake, res, _ = _json_once(_cut_at(50), client, max_tokens=100, overflow_max_tokens=200)
    assert res == {"a": 1} and [c["max_tokens"] for c in fake.calls] == [100]
    fake, res, spend = _json_once(_cut_at(100), client, max_tokens=100, overflow_max_tokens=100)
    assert res is None and len(fake.calls) == 1 and spend.errors == 1


def test_overflow_reask_keeps_the_refusal_rerun(client):
    """Truncated at the cap, then declined at the larger one: the refusal model serves it, at
    the larger cap."""

    def answer(model, kw):
        if model == OPUS5:
            return _resp('{"a": 2}', model=OPUS5)
        return _resp('{"a":', "max_tokens") if kw["max_tokens"] == 100 else _resp("", "refusal")

    fake, res, _ = _json_once(
        answer, client, max_tokens=100, overflow_max_tokens=200, refusal_model=OPUS5
    )
    assert res == {"a": 2, llm.SERVED_BY: OPUS5}
    assert [(c["model"], c["max_tokens"]) for c in fake.calls] == [
        (SONNET, 100), (SONNET, 200), (OPUS5, 200),
    ]  # fmt: skip


def test_overflow_reask_has_a_bounded_retry_budget(client):
    """A re-ask that keeps timing out is tried ``OVERFLOW_ATTEMPTS`` times, not the full 12 (at
    a doubled timeout that held a slot for hours); the first call's budget is unchanged."""

    class APITimeoutError(Exception):
        pass

    def reask_times_out(model, kw):
        if kw["max_tokens"] == 100:
            return _resp('{"a":', "max_tokens")
        raise APITimeoutError("timed out")

    fake, res, spend = _json_once(reask_times_out, client, max_tokens=100, overflow_max_tokens=200)
    caps = [c["max_tokens"] for c in fake.calls]
    assert res is None and caps == [100] + [200] * llm.OVERFLOW_ATTEMPTS == [100, 200, 200, 200]
    assert spend.errors == 1 and spend.retries == llm.OVERFLOW_ATTEMPTS - 1
    # a caller's lower budget still wins on the re-ask
    fake, _res, _ = _json_once(
        reask_times_out, client, max_tokens=100, overflow_max_tokens=200, attempts=2
    )
    assert [c["max_tokens"] for c in fake.calls] == [100, 200, 200]
    # the first call keeps the full budget: 11 timeouts, then the answer, with no re-ask
    left = [11]

    def first_times_out(model, kw):
        if left[0]:
            left[0] -= 1
            raise APITimeoutError("timed out")
        return _resp('{"a": 3}')

    fake, res, spend = _json_once(first_times_out, client, max_tokens=100, overflow_max_tokens=200)
    assert res == {"a": 3} and len(fake.calls) == 12 and spend.retries == 11
    assert {c["max_tokens"] for c in fake.calls} == {100}


def test_overflow_reask_too_long_is_the_too_long_marker_under_mark_refusals(client):
    """A re-ask that stops with ``model_context_window_exceeded`` is a context overflow like
    any other: ``TOO_LONG_JSON`` for a caller asking for markers (the digest halves the bundle;
    before the re-ask existed the item stayed unsummarized), ``None`` otherwise."""

    def answer(model, kw):
        stop = "max_tokens" if kw["max_tokens"] == 100 else "model_context_window_exceeded"
        return _resp('{"a":', stop)

    kw = {"max_tokens": 100, "overflow_max_tokens": 200}
    fake, res, spend = _json_once(answer, client, mark_refusals=True, **kw)
    assert res == llm.TOO_LONG_JSON and len(fake.calls) == 2 and spend.errors == 1
    _fake, res, _ = _json_once(answer, client, **kw)
    assert res is None


def test_refusal_model_must_differ(client):
    client(lambda m, kw: _resp('{"a": 1}'))
    with pytest.raises(llm.JudgeConfigError):
        llm.stream_json(
            [("s", "u")], schema=SCHEMA, model=SONNET, on_result=lambda i, r: None,
            refusal_model=SONNET,
        )  # fmt: skip


def test_refusal_model_reruns_a_declined_text_call(client):
    def answer(model, kw):
        return _resp("", "refusal") if model == SONNET else _resp("graded", model=OPUS5)

    fake = client(answer)
    events: list[tuple] = []
    llm.stream_text(
        ["u0"],
        model=SONNET,
        thinking=True,
        max_tokens=100,
        on_result=lambda i, t: events.append(("result", i, t)),
        refusal_model=OPUS5,
        on_served=lambda i, m: events.append(("served", i, m)),
    )
    assert events == [("served", 0, OPUS5), ("result", 0, "graded")]
    assert [c["model"] for c in fake.calls] == [SONNET, OPUS5]
    assert fake.calls[1]["thinking"] == {"type": "adaptive"}  # same thinking setting


def test_cloudflare_520_is_retried(client):
    class InternalServerError(Exception):
        status_code = 520

    outcomes = [InternalServerError("Error 520"), _resp('{"a": 2}')]

    def answer(model, kw):
        out = outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out

    _fake, res, spend = _json_once(answer, client)
    assert res == {"a": 2} and spend.retries == 1 and spend.errors == 0


# ---------------------------------------------------------------- digest settings

CLIENT_ONLY = {"summ_model": SONNET, "summ_fallback": f"none+{OPUS5}"}


def test_none_plus_model_is_a_client_side_rerun_only(tmp_path, mk_args):
    s = digest.settings(mk_args(tmp_path / "r.jsonl", extra=dict(CLIENT_ONLY)), "poetry")
    assert (s.model, s.fallback, s.server_fallback, s.refusal_model) == (
        SONNET, f"none+{OPUS5}", None, OPUS5,
    )  # fmt: skip
    for bad in ("none+", "server+claude-opus-5"):
        with pytest.raises(SystemExit):
            digest.settings(mk_args(tmp_path / "r.jsonl", extra={"summ_fallback": bad}), "poetry")


def test_output_cap_is_per_digest_model_and_the_single_call_budget_does_not_move(tmp_path, mk_args):
    s = digest.settings(mk_args(tmp_path / "r.jsonl", extra=dict(CLIENT_ONLY)), "poetry")
    assert s.max_tokens == digest.OUTPUT_CAPS[SONNET] == 64_000
    assert digest.MAX_TOKENS == 32_000
    # budget0 = min(cap, window - MAX_TOKENS - margin) is keyed on MAX_TOKENS, not the cap
    assert min(s.token_cap, digest.CONTEXT_WINDOW - digest.MAX_TOKENS - digest.CONTEXT_MARGIN) == (
        904_000
    )
    other = digest.settings(mk_args(tmp_path / "r.jsonl", extra={}), "poetry")
    assert other.model == digest.DEFAULT_MODEL and other.max_tokens == digest.MAX_TOKENS


# ---------------------------------------------------------------- both digest stages

LAYERS = (20, 24, 28)


def _quiet(system, user, schema):
    return {"verdicts": [], "rationale": ""}


def test_both_stages_use_the_cap_and_rerun_refusals_client_side(tmp_path, monkeypatch):
    """Stage 1 (per layer) and layered stage 2 send the digest model's output cap and no
    server-side fallbacks under ``none+<model>``; a declined stage-2 call re-runs on the refusal
    model and the item is summarized from its answer."""
    items = _fixture_bank(tmp_path, monkeypatch, 1, 1)
    rows = [
        {
            "id": it["id"],
            "layer": ly,
            "pos": it["read"]["turn_end"],
            "samples": [f"L{ly} {it['id']} sea story", f"shared boat line {it['id']}"],
        }
        for it in items
        for ly in LAYERS
    ]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    real = FakeLLM.install(monkeypatch, _quiet)
    orig = real.stream_json
    seen: list[tuple[str, str, int, Any]] = []

    def stream(prompts, *, schema, on_result, **kw):
        if schema.get("name") == "digest" and prompts:
            stage = "layered" if prompts[0][1].startswith("LAYER DIGESTS:") else "layer"
            seen.append((stage, kw["model"], kw["max_tokens"], kw.get("fallbacks")))
            if stage == "layered" and kw["model"] == SONNET:
                for i in range(len(prompts)):
                    on_result(i, llm.REFUSED_JSON)
                return llm.Spend()
        return orig(prompts, schema=schema, on_result=on_result, **kw)

    monkeypatch.setattr(llm, "stream_json", stream)
    extra = {**CLIENT_ONLY, "summ_layers": "layered"}
    res = jb.run(summary_args(path, tmp_path / "o", jbp.PROMPT_VERSION, extra=extra))
    assert {(st, m, cap, fb) for st, m, cap, fb in seen if st == "layer"} == {
        ("layer", SONNET, 64_000, None)
    }
    assert [(m, cap, fb) for st, m, cap, fb in seen if st == "layered"] == [
        (SONNET, 64_000, None),
        (OPUS5, 64_000, None),
    ]
    assert res.extras["summary"]["n_layered_items"] == len(items)
    assert all(OPUS5 in (r["summary_served_by"] or "") for r in res.rows)


def test_digest_calls_carry_the_overflow_cap_and_cached_digests_stay_valid(tmp_path, monkeypatch):
    """#289: every digest call (stage 1 and layered stage 2) of a model on the 32k cap asks for
    one re-ask at 64k after a ``max_tokens`` stop; a model already at the ceiling asks for none.
    The cap is in no fingerprint: a run with the re-ask switched off reuses every cached row."""
    s = digest.settings(summary_args(tmp_path / "r.jsonl", tmp_path, "pv"), "poetry")
    assert (s.model, s.max_tokens, s.overflow_max_tokens) == (digest.DEFAULT_MODEL, 32_000, 64_000)
    at_cap = digest.settings(
        summary_args(tmp_path / "r.jsonl", tmp_path, "pv", extra=dict(CLIENT_ONLY)), "poetry"
    )
    assert (at_cap.max_tokens, at_cap.overflow_max_tokens, at_cap.overflow_kw) == (64_000, None, {})

    items = _fixture_bank(tmp_path, monkeypatch, 1, 1)
    rows = [
        {
            "id": it["id"],
            "layer": ly,
            "pos": it["read"]["turn_end"],
            "samples": [f"L{ly} {it['id']} sea story", f"shared boat line {it['id']}"],
        }
        for it in items
        for ly in LAYERS
    ]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    real = FakeLLM.install(monkeypatch, _quiet)
    orig = real.stream_json
    seen: list[tuple[str, int, Any]] = []

    def stream(prompts, *, schema, on_result, **kw):
        if schema.get("name") == "digest" and prompts:
            stage = "layered" if prompts[0][1].startswith("LAYER DIGESTS:") else "layer"
            seen.append((stage, kw["max_tokens"], kw.get("overflow_max_tokens")))
        return orig(prompts, schema=schema, on_result=on_result, **kw)

    monkeypatch.setattr(llm, "stream_json", stream)
    extra = {"summ_model": digest.DEFAULT_MODEL, "summ_layers": "layered"}
    args = lambda: summary_args(path, tmp_path / "o", jbp.PROMPT_VERSION, extra=dict(extra))  # noqa: E731
    first = jb.run(args())
    assert {st for st, _c, _o in seen} == {"layer", "layered"}
    assert {(c, o) for _st, c, o in seen} == {(32_000, 64_000)}
    n = len(seen)
    monkeypatch.setattr(digest, "OVERFLOW_CEILING", digest.MAX_TOKENS)  # the re-ask off
    again = jb.run(args())
    assert len(seen) == n  # every digest row is a cache hit: the cap keys nothing
    assert [r["summary"] for r in again.rows] == [r["summary"] for r in first.rows]


# ---------------------------------------------------------------- cross-route re-run (plan 0096)

LUNA = "openai/gpt-6-luna"


class _Closing(ModelAwareClient):
    """A ``ModelAwareClient`` that records its ``close()``."""

    closed = False

    async def close(self) -> None:
        self.closed = True


def _declines(text: str = '{"a": 1}'):
    """An Anthropic answerer: Sonnet declines, any other Claude model answers ``text``."""
    return lambda model, kw: _resp("", "refusal") if model == SONNET else _resp(text, model=model)


def test_none_plus_any_model_is_a_client_side_refusal_model(tmp_path, mk_args):
    """Plan 0096: ``summ_fallback`` takes any model id after ``none+`` / ``default+``."""
    for v, want in ((f"none+{LUNA}", (None, LUNA)), ("default+gpt-6", ("default", "gpt-6"))):
        s = digest.settings(mk_args(tmp_path / "r.jsonl", extra={"summ_fallback": v}), "poetry")
        assert (s.server_fallback, s.refusal_model) == want


def test_json_rerun_anthropic_to_openrouter(monkeypatch):
    from openrouter_fakes import OpenRouterClient, completion, install_routes

    ant = _Closing(_declines())
    orc = OpenRouterClient(lambda model, kw: completion('{"a": 2}'))
    built = install_routes(monkeypatch, anthropic=ant, openrouter=orc)
    got: dict[int, Any] = {}
    kw = {"schema": SCHEMA, "model": SONNET, "on_result": got.__setitem__, "refusal_model": LUNA}
    llm.stream_json([("s", "u")], temperature=0.0, overflow_max_tokens=64_000, **kw)
    assert got == {0: {"a": 2, llm.SERVED_BY: LUNA}}
    assert built == ["anthropic", "openrouter"] and ant.closed and orc.closed
    (first,), (again,) = ant.calls, orc.calls
    assert "temperature" not in first and first["max_tokens"] == 16_000  # the Anthropic default
    # re-shaped for its route: OpenRouter's default cap, the caller's ORIGINAL temperature (the
    # Anthropic primary dropped it), the minimal reasoning, no fallbacks
    assert again["model"] == LUNA and again["max_tokens"] == 8000
    assert again["temperature"] == 0.0 and "fallbacks" not in again
    assert again["extra_body"]["reasoning"] == {"effort": "minimal"}
    assert [m["content"] for m in again["messages"]] == ["s", "u"]  # the same request
    # an explicit cap is kept; a family's Anthropic-only reasoning never reaches OpenRouter, and
    # refusal_reasoning= is what the re-run sends, as given
    orc.calls.clear()
    llm.stream_json(
        [("s", "u")],
        reasoning={"anthropic_effort": "default"},
        max_tokens=400,
        refusal_reasoning={"effort": "low"},
        **kw,
    )
    assert orc.calls[0]["max_tokens"] == 400 and "temperature" not in orc.calls[0]
    assert orc.calls[0]["extra_body"]["reasoning"] == {"effort": "low"}


def test_json_rerun_openrouter_to_anthropic(monkeypatch):
    from openrouter_fakes import OpenRouterClient, completion, install_routes

    refusals = [
        completion("", finish_reason="content_filter"),
        completion(None, refusal="I can't help with that"),
    ]
    orc = OpenRouterClient(lambda model, kw: refusals.pop(0))
    ant = _Closing(lambda model, kw: _resp('{"a": 3}', model=model))
    built = install_routes(monkeypatch, anthropic=ant, openrouter=orc)
    got: dict[int, Any] = {}
    kw = {"schema": SCHEMA, "model": LUNA, "on_result": got.__setitem__}
    spend = llm.stream_json(
        [("s", "u")], temperature=0.0, reasoning={"effort": "low"}, refusal_model=OPUS5, **kw
    )
    assert got == {0: {"a": 3, llm.SERVED_BY: OPUS5}} and spend.refusals == 1
    assert built == ["openrouter", "anthropic"] and ant.closed and orc.closed
    assert orc.calls[0]["temperature"] == 0.0 and orc.calls[0]["max_tokens"] == 8000
    again = ant.calls[0]
    # the Anthropic default cap, no temperature, and the OpenRouter-only reasoning key dropped
    # (claude-opus-5 does not always think: no effort at all)
    assert again["model"] == OPUS5 and again["max_tokens"] == 16_000
    assert "temperature" not in again and "effort" not in again["output_config"]
    # refusal_reasoning: the family's own Anthropic instrument on an always-thinking fallback
    ant.calls.clear()
    llm.stream_json([("s", "u")], refusal_model="claude-sonnet-5-5", **kw)
    assert ant.calls[0]["output_config"]["effort"] == "low"  # the repo default for the model
    ant.calls.clear()
    refusals.append(completion("", finish_reason="content_filter"))
    llm.stream_json(
        [("s", "u")],
        refusal_model="claude-sonnet-5-5",
        refusal_reasoning={"anthropic_effort": "default"},
        **kw,
    )
    assert "effort" not in ant.calls[0]["output_config"]


def test_structured_openrouter_refusal_is_one_refusal_not_twelve_retries(monkeypatch):
    from openrouter_fakes import ModerationError, OpenRouterClient, completion, install_routes

    for outcome in (
        completion("", finish_reason="content_filter"),
        completion(None, refusal="no"),
        ModerationError("flagged"),
    ):
        for mark, want in ((True, llm.REFUSED_JSON), (False, None)):
            orc = OpenRouterClient(lambda model, kw, o=outcome: o)
            install_routes(monkeypatch, openrouter=orc)
            got: dict[int, Any] = {}
            spend = llm.stream_json(
                [("s", "u")],
                schema=SCHEMA,
                model=LUNA,
                on_result=got.__setitem__,
                mark_refusals=mark,
            )
            assert got == {0: want} and len(orc.calls) == 1
            assert (spend.refusals, spend.retries, spend.errors) == (1, 0, 0)
    # a refusal field beside real content is an answer
    orc = OpenRouterClient(lambda model, kw: completion('{"a": 5}', refusal="x"))
    install_routes(monkeypatch, openrouter=orc)
    got = {}
    llm.stream_json([("s", "u")], schema=SCHEMA, model=LUNA, on_result=got.__setitem__)
    assert got == {0: {"a": 5}}


def test_text_rerun_crosses_routes_both_ways(monkeypatch):
    from openrouter_fakes import OpenRouterClient, install_routes, text_stream

    def run(model, refusal_model):
        events: list[tuple] = []
        llm.stream_text(
            ["u0"],
            model=model,
            thinking=True,
            max_tokens=100,
            on_result=lambda i, t: events.append(("result", i, t)),
            refusal_model=refusal_model,
            on_served=lambda i, m: events.append(("served", i, m)),
        )
        return events

    ant = _Closing(_declines("graded"))
    orc = OpenRouterClient(lambda model, kw: text_stream("from luna"))
    built = install_routes(monkeypatch, anthropic=ant, openrouter=orc)
    assert run(SONNET, LUNA) == [("served", 0, LUNA), ("result", 0, "from luna")]
    assert built == ["anthropic", "openrouter"] and ant.closed and orc.closed
    assert orc.calls[0]["max_tokens"] == 100  # the same settings
    assert orc.calls[0]["extra_body"]["reasoning"] == {"enabled": True}

    ant = _Closing(_declines("graded"))
    orc = OpenRouterClient(lambda model, kw: text_stream("", "content_filter"))
    built = install_routes(monkeypatch, anthropic=ant, openrouter=orc)
    assert run(LUNA, OPUS5) == [("served", 0, OPUS5), ("result", 0, "graded")]
    assert built == ["openrouter", "anthropic"] and ant.closed and orc.closed
    assert ant.calls[0]["thinking"] == {"type": "adaptive"} and ant.calls[0]["max_tokens"] == 100


def test_missing_fallback_key_raises_before_the_first_call(monkeypatch):
    """A cross-route refusal model whose key is missing is a config error up front (this test
    patches ``llm.api_key`` itself: no fake-client installer)."""

    def api_key(model: str) -> str:
        if llm.route(model) == "openrouter":
            raise llm.JudgeConfigError("OPENROUTER_API_KEY is missing")
        return "sk-ant-test"

    def boom(route, key):
        raise AssertionError("no client may be built")

    monkeypatch.setattr(llm, "api_key", api_key)
    monkeypatch.setattr(llm, "_make_client", boom)
    with pytest.raises(llm.JudgeConfigError, match="OPENROUTER_API_KEY"):
        llm.stream_json(
            [("s", "u")], schema=SCHEMA, model=SONNET, on_result=lambda i, r: None,
            refusal_model=LUNA,
        )  # fmt: skip
    with pytest.raises(llm.JudgeConfigError, match="OPENROUTER_API_KEY"):
        llm.stream_text(
            ["u"], model=SONNET, on_result=lambda i, r: None, thinking=True, max_tokens=1,
            refusal_model=LUNA,
        )  # fmt: skip


def test_same_route_rerun_builds_one_client_and_text_refusal_model_must_differ(monkeypatch):
    built: list[str] = []
    fake = fake_client_installer(monkeypatch)(_declines())
    monkeypatch.setattr(llm, "_make_client", lambda route, key: built.append(route) or fake)
    got: dict[int, Any] = {}
    llm.stream_json(
        [("s", "u")], schema=SCHEMA, model=SONNET, on_result=got.__setitem__, refusal_model=OPUS5
    )
    assert built == ["anthropic"] and got == {0: {"a": 1, llm.SERVED_BY: OPUS5}}
    for model in (SONNET, LUNA):
        with pytest.raises(llm.JudgeConfigError, match="must be another model"):
            llm.stream_text(
                ["u"], model=model, on_result=lambda i, r: None, thinking=True, max_tokens=1,
                refusal_model=model,
            )  # fmt: skip
