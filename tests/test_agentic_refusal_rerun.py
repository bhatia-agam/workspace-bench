"""agentic_misalignment on its Sonnet pins: the digest and Stage C run on claude-sonnet-5, a call
Sonnet declines re-runs once on claude-opus-5 (client-side), the rows record the serving models,
and the run stays the instrument of record. Driven through the real ``llm`` primitives with a
fake SDK client that answers by model (``test_llm_refusal_rerun``)."""

import json

import pytest
from conftest import write_jsonl
from summary_fakes import first_lines_digest, layered_digest
from test_llm_refusal_rerun import OPUS5, SONNET, _resp, fake_client_installer, is_digest
from test_summary_mode_agentic import BENIGN, GOOD, RH, _rows

from wsbench import digest
from wsbench.evals.agentic_misalignment import SPEC as AM_SPEC
from wsbench.evals.agentic_misalignment import judge as am_judge
from wsbench.evals.agentic_misalignment import prompts as am_prompts
from wsbench.judge_config import resolve


@pytest.fixture
def client(monkeypatch):
    return fake_client_installer(monkeypatch)


def _am_args(mk_args, path, out, **extra):
    return mk_args(
        path,
        out=out,
        judge=resolve(AM_SPEC.judge, env={}),
        aux_models=AM_SPEC.judge.aux_models,
        extra={"aggregate": "summary", **extra},
        items=[RH],
    )


def test_sonnet_digest_settings(tmp_path, mk_args):
    s = digest.settings(_am_args(mk_args, tmp_path / "r.jsonl", tmp_path), "agentic_misalignment")
    assert (s.model, s.fallback, s.server_fallback, s.refusal_model) == (
        SONNET, f"none+{OPUS5}", None, OPUS5,
    )  # fmt: skip
    assert s.max_tokens == 64_000


def _answer(declined_layer: str):
    """Sonnet declines RH's digest at ``declined_layer`` and RH's Stage C call; Opus 5 serves."""

    def answer(model, kw):
        user = kw["messages"][0]["content"]
        if user.startswith("LAYER DIGESTS:"):
            return _resp(json.dumps(layered_digest(user)), model=model)
        if is_digest(kw):
            if model == SONNET and f"R:{RH}:{declined_layer}" in user:
                return _resp("", "refusal")
            return _resp(json.dumps(first_lines_digest(user)), model=model)
        if model == SONNET and f"R:{RH}:" in user and "~twin" not in user:
            return _resp("", "refusal")
        return _resp(GOOD if "~twin" not in user else BENIGN, model=model)

    return answer


def test_declined_calls_rerun_on_opus5_and_rows_record_it(tmp_path, client, mk_args):
    """RH's layer-36 digest and RH's Stage C call are declined by Sonnet: both re-run on Opus 5
    with the same request (the digest at the 64k cap), the rows name Opus 5, the run stays the
    pinned instrument, and a rerun from the cache keeps the provenance with no call at all."""
    path = write_jsonl(tmp_path / "r.jsonl", _rows([RH, f"{RH}~twin"], positions=(0, 1)))
    fake = client(_answer("L36"))
    r = am_judge.run(_am_args(mk_args, path, tmp_path / "o"))
    digests = fake.models("digest")
    assert digests.count(OPUS5) == 1 and digests.count(SONNET) == 4  # 2 items x 2 layers
    assert sorted(fake.models("text")) == [OPUS5, SONNET, SONNET]
    assert {c["max_tokens"] for c in fake.calls if is_digest(c)} == {64_000}
    assert all("fallbacks" not in c for c in fake.calls)
    rows = {x["id"]: x for x in r.rows}
    assert rows[RH]["digest_model"] == OPUS5 and rows[RH]["judge_model"] == OPUS5
    assert rows[f"{RH}~twin"]["digest_model"] == SONNET
    assert rows[f"{RH}~twin"]["judge_model"] == SONNET
    assert rows[RH]["design_fidelity"] == 3  # judged, not undecided
    assert r.extras["judge_served_by"] == {SONNET: 1, OPUS5: 1}
    assert r.extras["judge_fallback_ids"] == [RH]
    assert r.extras["summary"]["digest_served_by"] == {OPUS5: 1, SONNET: 1}
    assert r.pinned_instrument and r.extras["n_items_digest_refused"] == 0
    # resumed run: every call is a cache hit and the served-by survives
    again = client(lambda m, kw: pytest.fail(f"unexpected call to {m}"))
    r2 = am_judge.run(_am_args(mk_args, path, tmp_path / "o"))
    assert again.calls == []
    rows2 = {x["id"]: x for x in r2.rows}
    assert (rows2[RH]["digest_model"], rows2[RH]["judge_model"]) == (OPUS5, OPUS5)
    assert r2.pinned_instrument
    # summ_fallback=none switches the re-run off and the run is no longer the instrument
    client(_answer("L36"))
    off = am_judge.run(_am_args(mk_args, path, tmp_path / "o3", summ_fallback="none"))
    assert not off.pinned_instrument


def test_layered_stage_two_runs_on_the_sonnet_pin(tmp_path, client, mk_args):
    """Under the layered digest (the CLI default for a multi-layer run) stage 2 runs on the same
    Sonnet pin, cap and client-side re-run; the stamp carries the layered tag and the run is the
    instrument of record."""
    path = write_jsonl(tmp_path / "r.jsonl", _rows([RH, f"{RH}~twin"], positions=(0, 1)))
    fake = client(_answer("L36"))
    r = am_judge.run(_am_args(mk_args, path, tmp_path / "o", summ_layers="layered"))
    stage2 = [c for c in fake.calls if c["messages"][0]["content"].startswith("LAYER DIGESTS:")]
    assert {c["model"] for c in stage2} == {SONNET} and len(stage2) == 2
    assert {c["max_tokens"] for c in stage2} == {64_000}
    assert all("fallbacks" not in c for c in fake.calls)
    assert r.config["summarizer"]["layer_mode"] == "layered"
    assert "-layered-v1x4+" in r.config["prompt_version"]
    assert r.config["prompt_version"].startswith(am_prompts.SUMMARY_STAMP_VERSION)
    rows = {x["id"]: x for x in r.rows}
    assert rows[RH]["digest_model"] == OPUS5 and rows[RH]["judge_model"] == OPUS5
    assert r.pinned_instrument
