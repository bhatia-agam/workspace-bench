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
from wsbench.evals.jailbreak_recognition import judge as jb
from wsbench.evals.jailbreak_recognition import prompts as jbp

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
    for bad in ("none+", "none+gpt-6", "server+claude-opus-5"):
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
