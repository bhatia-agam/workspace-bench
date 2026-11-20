"""Plan 0096: the four fallback families under an OpenRouter judge (the refusal fallback follows
the judge, ``opts=fallback=none``, provenance, ``accept_served``), agentic's three native stages
on the OpenRouter route, and the shared helpers. The scenarios are the step-0 ones
(``test_pin_requests_0096``) with the judge moved off its pin."""

import dataclasses
import json
from typing import Any

import pytest
from conftest import tag_of, write_jsonl
from openrouter_fakes import OpenRouterClient, completion, install_routes, text_stream
from test_agentic_misalignment import (  # noqa: F401
    BENIGN_C,
    CTL,
    GOOD_C,
    RH,
    pre_twin_bank,
    stage_of,
)
from test_llm_refusal_rerun import ModelAwareClient
from test_pin_requests_0096 import MMH_IDS, SCENARIOS

from wsbench import family, llm, mcjudge, registry
from wsbench.cache import Cache, fingerprint
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.mcjudge import Call

LUNA = "openai/gpt-6-luna"
SONNET55, OPUS5 = "claude-sonnet-5-5", "claude-opus-5"
ALL = sorted(SCENARIOS)
# the three families whose fallback-served rows live under the judge's own cache key
SERVED_ROWS = [n for n in ALL if not n.startswith("hinted_cutoff")]
FALLBACK = {
    "agentic_misalignment": OPUS5,
    "jailbreak_recognition": OPUS5,
    "hinted_cutoff": SONNET55,
    "model_multihop": SONNET55,
}


class Run:
    """One scenario with the judge moved to ``judge_model``. The scripted answerer declines one
    call of the family's pin, so the judge is shown to it as the pin while ``declining``."""

    def __init__(self, name: str, tmp_path, monkeypatch, judge_model: str = LUNA):
        self.name, self.tmp_path, self.monkeypatch = name, tmp_path, monkeypatch
        self.family = name.split("/")[0]
        self.judge_model = judge_model
        self.declining = True
        self.ant: ModelAwareClient
        self.orc: OpenRouterClient

    def _as_seen(self, model: str) -> str:
        pin = registry.FAMILIES[self.family].judge.model
        return pin if model == self.judge_model and self.declining else model

    def __call__(self, out: str = "o", **extra: str):
        """Build the scenario afresh (a fresh "first call" counter), run it, return the result."""
        build, mode = SCENARIOS[self.name]
        judge, args, answer = build(self.tmp_path, self.monkeypatch, mode)
        spec = registry.FAMILIES[self.family]
        args = dataclasses.replace(
            args,
            judge=resolve(spec.judge, flag=self.judge_model, env={}),
            out=self.tmp_path / out,
            extra={**args.extra, **extra},
        )

        def on_openrouter(model: str, kw: dict[str, Any]) -> Any:
            # the scripted answerer reads an Anthropic-shaped request: translate both ways
            seen: dict[str, Any] = {"messages": [{"content": kw["messages"][-1]["content"]}]}
            if "response_format" in kw:
                schema = kw["response_format"]["json_schema"]["schema"]
                seen["output_config"] = {"format": {"schema": schema}}
            resp = answer(self._as_seen(model), seen)
            text = next((b.text for b in resp.content), "")
            if kw.get("stream"):
                declined = resp.stop_reason == "refusal"
                return text_stream(text, "content_filter" if declined else "stop")
            if resp.stop_reason == "refusal":
                return completion("", finish_reason="content_filter")
            return completion(text)

        self.ant = ModelAwareClient(lambda model, kw: answer(self._as_seen(model), kw))
        self.orc = OpenRouterClient(on_openrouter)
        install_routes(self.monkeypatch, anthropic=self.ant, openrouter=self.orc)
        return judge.run(args)

    def served_rows(self, res) -> list[dict]:
        """The rows a fallback model served a judge call of."""
        fb = FALLBACK[self.family]
        if self.family in ("agentic_misalignment", "jailbreak_recognition"):
            return [r for r in res.rows if fb in (r.get("judge_model") or "")]
        return [r for r in res.rows if r.get("fallback_served_by")]

    def fallback_requests(self) -> list[dict]:
        """The judge-call requests the fallback model got (digest calls are not the judge's)."""
        from test_llm_refusal_rerun import is_digest

        fb = FALLBACK[self.family]
        return [c for c in self.ant.calls if c["model"] == fb and not is_digest(c)]


# ---------------------------------------------------------------- the fallback follows the judge


@pytest.mark.parametrize("name", ALL)
def test_a_luna_judges_declined_call_reruns_on_the_family_fallback(
    name, tmp_path, monkeypatch, real_families
):
    run = Run(name, tmp_path, monkeypatch)
    res = run()
    fb = FALLBACK[run.family]
    assert res.config["judge_model"] == LUNA and run.orc.calls  # the judge is on OpenRouter
    assert len(run.fallback_requests()) == 1 and len(run.served_rows(res)) == 1
    assert not res.pinned_instrument and not res.complete  # a Luna row is never of record
    (again,) = run.fallback_requests()
    if run.family == "hinted_cutoff":
        row = run.served_rows(res)[0]
        assert row["fallback_served_by"] == [fb]
        assert res.config["fallback_model"] == fb and "judge_fallback" not in res.config
        assert res.extras["n_fallback_served_calls"] == res.extras["n_fallback_calls"] == 1
    else:
        assert res.config["judge_fallback"] == fb
    if run.family == "model_multihop":
        assert run.served_rows(res)[0]["id"] == MMH_IDS[0]
        assert run.served_rows(res)[0]["fallback_served_by"] == [fb]
        assert res.extras["n_fallback_served_calls"] == 1
    if run.family in ("hinted_cutoff", "model_multihop"):
        # the fallback runs at the family's own instrument (anthropic_effort: default = no
        # effort key), not at the low effort an always-thinking model gets with no setting
        assert llm.always_thinks(fb) and "effort" not in again["output_config"]
        assert "temperature" not in again
    if name == "model_multihop/summary":  # its temperature rides the OpenRouter judge call
        # (part 2: the digest follows the Luna judge, and a digest call sends no temperature)
        digests = [c for c in run.orc.calls if c["messages"][-1]["content"].startswith("READOUTS:")]
        judged = [c for c in run.orc.calls if c not in digests]
        assert digests and {c["model"] for c in digests} == {LUNA}
        assert all("temperature" not in c and "reasoning" not in c["extra_body"] for c in digests)
        assert judged and {c.get("temperature") for c in judged} == {0.0}
    if run.family == "agentic_misalignment":
        assert res.extras["judge_fallback_ids"] == [RH]
        assert again["thinking"] == {"type": "adaptive"}  # Stage C: free text, same settings
    if run.family == "jailbreak_recognition":
        assert res.extras["judge_served_by"][fb] == 1


@pytest.mark.parametrize("name", ALL)
def test_fallback_none_leaves_the_declined_call_lost(name, tmp_path, monkeypatch, real_families):
    run = Run(name, tmp_path, monkeypatch)
    res = run(fallback="none")
    assert run.fallback_requests() == [] and run.served_rows(res) == []
    assert "n_fallback_served_calls" not in res.extras
    assert all("fallback_served_by" not in r for r in res.rows)
    if run.family == "hinted_cutoff":
        assert res.config["fallback_model"] is None and "judge_fallback" not in res.config
        assert res.extras["n_fallback_calls"] == 0
    else:
        assert res.config["judge_fallback"] == "none"
    if run.family == "jailbreak_recognition":  # the declined draw is a failed draw of its item
        assert sum(r["judge_served_by"].count(None) for r in res.rows) == 1
    else:
        assert res.counts["n_unjudged_cells"] == 1


@pytest.mark.parametrize("name", ALL)
def test_a_judge_that_is_the_fallback_model_gets_no_fallback(
    name, tmp_path, monkeypatch, real_families
):
    fb = FALLBACK[name.split("/")[0]]
    run = Run(name, tmp_path, monkeypatch, judge_model=fb)
    res = run()
    assert res.config["judge_model"] == fb and run.orc.calls == []
    assert all("fallback_served_by" not in r for r in res.rows)
    assert "n_fallback_served_calls" not in res.extras
    # every judge call went out once: the declined one was not re-run on any model
    judge_calls = [json.dumps(c["messages"]) for c in run.fallback_requests()]
    n_draws = 3 if run.family == "jailbreak_recognition" else 1
    assert all(judge_calls.count(c) == n_draws for c in judge_calls)
    if run.family == "hinted_cutoff":
        assert res.config["fallback_model"] is None and res.extras["n_fallback_calls"] == 0
    else:
        assert res.config["judge_fallback"] == "same-as-judge"
    if run.family == "agentic_misalignment":
        assert res.extras["judge_fallback_ids"] == []


@pytest.mark.parametrize("name", ALL)
def test_pinned_judge_with_fallback_none_is_not_the_instrument(
    name, tmp_path, monkeypatch, real_families
):
    pin = registry.FAMILIES[name.split("/")[0]].judge.model
    run = Run(name, tmp_path, monkeypatch, judge_model=pin)
    res = run(fallback="none")
    assert run.fallback_requests() == [] and run.served_rows(res) == []
    if run.family == "hinted_cutoff":  # its existing fallback=none behaviour is left as it is
        assert res.config["fallback_model"] is None and "judge_fallback" not in res.config
        assert res.pinned_instrument
    else:
        assert res.config["judge_fallback"] == "none" and not res.pinned_instrument


@pytest.mark.parametrize(
    "name", [*ALL, "agentic_misalignment/native", "jailbreak_recognition/native"]
)
def test_a_bad_fallback_value_exits_2(name, tmp_path, monkeypatch, real_families):
    fam, mode = name.split("/")
    build = next(b for n, (b, _m) in SCENARIOS.items() if n.startswith(fam))
    judge, args, _answer = build(tmp_path, monkeypatch, mode)
    args = dataclasses.replace(args, extra={**args.extra, "fallback": "maybe"})
    install_routes(monkeypatch)  # no client may be built
    with pytest.raises(SystemExit) as e:
        judge.run(args)
    assert e.value.code == 2


def test_fallback_on_message_is_hinted_cutoffs(mk_args, tmp_path, capsys):
    args = mk_args(tmp_path / "r.jsonl", extra={"fallback": "maybe"})
    with pytest.raises(SystemExit):
        family.fallback_on(args, "hinted_cutoff")
    assert capsys.readouterr().err == (
        "hinted_cutoff: opts=fallback must be on or none, not 'maybe'\n"
    )
    assert family.fallback_on(mk_args(tmp_path / "r.jsonl"), "x") is True
    assert (
        family.fallback_on(mk_args(tmp_path / "r.jsonl", extra={"fallback": "none"}), "x") is False
    )


# ---------------------------------------------------------------- fallback=none and the cache


@pytest.mark.parametrize("name", SERVED_ROWS)
def test_on_none_on_when_the_judge_declines_again(name, tmp_path, monkeypatch, real_families):
    """``fallback=none`` never reuses a fallback-served cache row: the key is re-asked on the
    judge. Declined again, nothing is cached for it, and a later fallback-on run hits the served
    row again without a call."""
    run = Run(name, tmp_path, monkeypatch)
    assert len(run.served_rows(run())) == 1
    res = run(fallback="none")
    assert run.served_rows(res) == [] and run.fallback_requests() == []
    assert len(run.orc.calls) == 1  # the one key the fallback had served, re-asked on the judge
    res = run()
    assert len(run.served_rows(res)) == 1
    assert run.orc.calls == [] and run.fallback_requests() == []  # the served row: a hit again
    res = run(fallback="none")  # and it is re-asked on every fallback=none resume
    assert len(run.orc.calls) == 1 and run.served_rows(res) == []


@pytest.mark.parametrize("name", SERVED_ROWS)
def test_on_none_on_when_the_judge_answers_the_reask(name, tmp_path, monkeypatch, real_families):
    """If the judge itself answers the re-ask, its newer row supersedes the served one for
    every later run, fallback on or not."""
    run = Run(name, tmp_path, monkeypatch)
    assert len(run.served_rows(run())) == 1
    run.declining = False
    res = run(fallback="none")
    assert len(run.orc.calls) == 1 and run.served_rows(res) == []
    run.declining = True
    for extra in ({}, {"fallback": "none"}):
        res = run(**extra)
        assert run.orc.calls == [] and run.fallback_requests() == []
        assert run.served_rows(res) == []


@pytest.mark.parametrize("name", ["hinted_cutoff/native", "hinted_cutoff/summary"])
def test_hinted_cutoff_on_none_on(name, tmp_path, monkeypatch, real_families):
    """hinted_cutoff needs no switch: its ``|fb`` rows are read only when the fallback is on."""
    run = Run(name, tmp_path, monkeypatch)
    assert len(run.served_rows(run())) == 1
    res = run(fallback="none")
    assert run.served_rows(res) == [] and run.fallback_requests() == []
    res = run()
    assert len(run.served_rows(res)) == 1 and run.fallback_requests() == []  # the |fb row: a hit
    assert res.extras["n_fallback_served_calls"] == 1  # cache hits included


def test_run_calls_accept_served_and_refusal_reasoning(tmp_path, monkeypatch):
    schema = llm.schema_block("t", {"a": {"type": "integer"}}, ["a"])
    judge = resolve(JudgeConfig(), flag=LUNA, env={})
    calls = [Call("k1", "s", "u1"), Call("k2", "s", "u2")]
    seen: list[dict] = []
    answers: dict[str, Any] = {}

    def stream_json(prompts, *, on_result, **kw):
        seen.append({"users": [u for _s, u in prompts], **kw})
        for i, (_s, u) in enumerate(prompts):
            on_result(i, answers[u])
        return llm.Spend()

    monkeypatch.setattr(llm, "stream_json", stream_json)

    def run(**kw):
        with Cache(tmp_path / "cells.jsonl") as cache:
            return mcjudge.run_calls(
                calls, schema=schema, judge=judge, prompt_version="pv", cache=cache,
                spend=llm.Spend(), concurrency=1, rpm=1e9, dry_run=False, **kw,
            )  # fmt: skip

    answers.update(u1={"a": 1, llm.SERVED_BY: SONNET55}, u2={"a": 2})
    out = run(refusal_model=SONNET55, refusal_reasoning={"anthropic_effort": "default"})
    assert seen[-1]["refusal_reasoning"] == {"anthropic_effort": "default"}
    assert "accept_served" not in seen[-1]  # consumed by run_calls, never forwarded
    assert out["k1"][llm.SERVED_BY] == SONNET55
    n = len(seen)
    assert run() == out and len(seen) == n  # default: the served row is a hit (today's lookup)
    answers["u1"] = None
    assert run(accept_served=False) == {"k1": None, "k2": {"a": 2}}
    assert seen[-1]["users"] == ["u1"]  # only the served row is re-asked
    assert "refusal_reasoning" not in seen[-1] and "refusal_model" not in seen[-1]
    assert run() == out and len(seen) == n + 1  # declined again: the served row hits again
    answers["u1"] = {"a": 7}
    assert run(accept_served=False)["k1"] == {"a": 7}
    assert run()["k1"] == {"a": 7} and len(seen) == n + 2  # the judge's newer row wins
    fp = fingerprint("pv", LUNA, judge.reasoning, None, "s", "u1")
    with Cache(tmp_path / "cells.jsonl") as cache:  # append-only: the served row is still there
        assert [r["result"] for r in cache._rows["k1"] if r["fp"] == fp] == [
            {"a": 1, llm.SERVED_BY: SONNET55}, None, {"a": 7},
        ]  # fmt: skip


# ---------------------------------------------------------------- credentials up front


@pytest.mark.parametrize("name", ALL)
def test_missing_fallback_key_exits_before_the_first_call(
    name, tmp_path, monkeypatch, real_families
):
    """A Luna judge with only the OpenRouter key: the family's Anthropic fallback has no key, a
    ``JudgeConfigError`` (exit 3) that names ``opts=fallback=none``, before any call. The digest
    is given an OpenRouter model too, so nothing else of the run needs the Anthropic key."""
    run = Run(name, tmp_path, monkeypatch)
    real_key = llm.api_key

    def api_key(model: str) -> str:
        if llm.route(model) == "anthropic":
            raise llm.JudgeConfigError("ANTHROPIC_API_KEY is missing")
        return real_key(model)

    def go(**extra):
        monkeypatch.setattr(llm, "api_key", real_key)
        build, mode = SCENARIOS[name]
        judge, args, _answer = build(tmp_path, monkeypatch, mode)
        args = dataclasses.replace(
            args,
            judge=resolve(registry.FAMILIES[run.family].judge, flag=LUNA, env={}),
            extra={**args.extra, "summ_model": LUNA, "summ_fallback": "none", **extra},
        )
        orc = OpenRouterClient(lambda model, kw: completion("", finish_reason="content_filter"))
        install_routes(monkeypatch, openrouter=orc)
        monkeypatch.setattr(llm, "count_tokens", lambda model, ps, concurrency=8: [10] * len(ps))
        monkeypatch.setattr(llm, "api_key", api_key)
        return judge, args, orc

    judge, args, orc = go()
    with pytest.raises(llm.JudgeConfigError, match="opts=fallback=none"):
        judge.run(args)
    assert orc.calls == []
    judge, args, orc = go()
    judge.run(dataclasses.replace(args, dry_run=True))  # never on a dry run
    judge, args, orc = go(fallback="none")  # the single-key way out: the run goes through
    judge.run(args)
    assert orc.calls


# ---------------------------------------------------------------- agentic native on OpenRouter


def test_agentic_native_stages_run_on_an_openrouter_judge(
    tmp_path,
    monkeypatch,
    mk_args,
    pre_twin_bank,  # noqa: F811
):
    """Stages A, B and C are free text: on a Luna judge they run on the OpenRouter route end to
    end (before plan 0096: ``JudgeConfigError``, exit 3)."""
    from wsbench.evals.safety.agentic_misalignment import SPEC
    from wsbench.evals.safety.agentic_misalignment import judge as am

    rows = [
        {"id": iid, "layer": layer, "pos": pos, "samples": [f"R:{iid}:L{layer}:p{pos}"]}
        for iid in (RH, CTL)
        for pos in (0, 1)
        for layer in (20, 36)
    ]
    path = write_jsonl(tmp_path / "r.jsonl", rows)

    def answer(model, kw):
        assert model == LUNA and kw["stream"] is True and "response_format" not in kw
        user = kw["messages"][0]["content"]
        stage = stage_of(user)
        reasoning = kw["extra_body"]["reasoning"]
        if stage == "A":  # no thinking: the minimal effort (a model may not turn reasoning off)
            assert reasoning == {"effort": "minimal"} and kw["max_tokens"] == 400
            return text_stream(f"note {tag_of(user)} voice: own intention")
        assert reasoning == {"enabled": True}
        if stage == "B":
            return text_stream(f"ACCOUNT {RH if RH in user else CTL}")
        return text_stream(GOOD_C if RH in user else BENIGN_C)

    orc = OpenRouterClient(answer)
    install_routes(monkeypatch, openrouter=orc)
    args = mk_args(path, items=[RH, CTL], judge=resolve(SPEC.judge, flag=LUNA, env={}))
    res = am.run(args)
    stages = [stage_of(c["messages"][0]["content"]) for c in orc.calls]
    assert (stages.count("A"), stages.count("B"), stages.count("C")) == (4, 2, 2)
    by = {r["id"]: r for r in res.rows}
    assert by[RH]["design_fidelity"] == 3 and by[RH]["account"] == f"ACCOUNT {RH}"
    assert by[CTL]["design_fidelity"] == 0
    assert res.config["judge_model"] == LUNA and not res.pinned_instrument
    assert "judge_fallback" not in res.config  # native: no judge fallback, no key
    assert res.counts["n_unjudged_cells"] == 0 and res.counts["spend_usd"] > 0
    # a filtered Stage A position is read as uninformative, as an Anthropic refusal is
    declining = OpenRouterClient(
        lambda model, kw: (
            text_stream("", "content_filter")
            if stage_of(kw["messages"][0]["content"]) == "A"
            else answer(model, kw)
        )
    )
    install_routes(monkeypatch, openrouter=declining)
    res = am.run(dataclasses.replace(args, out=tmp_path / "o2"))
    assert res.extras["n_refused_positions"] == 4 and res.counts["n_unjudged_cells"] == 0


def test_stamp_and_effective_fallback_helpers(mk_args, tmp_path):
    pinned = mk_args(tmp_path / "r.jsonl")
    luna = mk_args(tmp_path / "r.jsonl", judge=resolve(JudgeConfig(), flag=LUNA, env={}))
    assert family.judge_fallback_stamp(pinned, True, SONNET55) == {}  # the pin: config unchanged
    assert family.judge_fallback_stamp(pinned, False, SONNET55) == {"judge_fallback": "none"}
    assert family.judge_fallback_stamp(luna, True, SONNET55) == {"judge_fallback": SONNET55}
    assert family.judge_fallback_stamp(luna, True, LUNA) == {"judge_fallback": "same-as-judge"}
    assert family.judge_fallback_stamp(luna, True, "") == {"judge_fallback": "none"}
    assert family.effective_fallback(luna, True, SONNET55) == SONNET55
    assert family.effective_fallback(luna, False, SONNET55) is None
    assert family.effective_fallback(luna, True, LUNA) is None
    assert (
        json.dumps(family.judge_fallback_stamp(luna, False, None)) == '{"judge_fallback": "none"}'
    )
