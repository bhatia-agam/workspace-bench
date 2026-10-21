"""Precision tiers (plan 0014): tier_config, precedence, the lite read, completeness, report."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import write_jsonl
from test_agentic_misalignment import BENIGN_C, FakeText, stage_of

from wsbench import llm, registry, tiers
from wsbench.cli import floor_columns, main
from wsbench.evals.jailbreak_recognition import judge as jb
from wsbench.evals.jailbreak_recognition.judge import (
    grid_positions,
    lite_positions,
    punct_positions,
)
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.llm import schema_block, stream_json
from wsbench.mcjudge import load_bank
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult, write_results
from wsbench.tiers import MAX_JUDGE, S_LITE, tier_config, tier_read, tier_stride

GEMINI = "google/gemini-3.8-flash"
SONNET = "claude-sonnet-5"
JB, AM = "jailbreak_recognition", "agentic_misalignment"
REGIMES = {"span": grid_positions, "lite": lite_positions, "punct": punct_positions}
registry.load_all()  # at import, before conftest snapshots the registry for each test


@pytest.fixture
def families():
    return registry.FAMILIES


def _jb_items() -> list[dict]:
    return load_bank(JB)["items"]


# ---- 1. tier_config


@pytest.mark.parametrize("tier", tiers.TIERS)
def test_tier_config_per_family(families, tier):
    for name, standard_model in [
        ("basic_readout", GEMINI),  # a Gemini family
        ("hallucination", GEMINI),  # explicit Gemini reasoning
        ("basic_readout_mt", GEMINI),  # a multitoken (regex-scored) family
        (JB, SONNET),
        (AM, SONNET),
    ]:
        spec = families[name]
        cfg = tier_config(spec.judge, name, tier)
        assert spec.judge.model == standard_model
        moves = tier == "max" and name != AM
        assert cfg.model == (MAX_JUDGE if moves else standard_model), (tier, name)
        assert cfg.reasoning == spec.judge.reasoning  # left as the family set it
        assert cfg.prompt_version == spec.judge.prompt_version
        assert dict(cfg.aux_models) == dict(spec.judge.aux_models)  # no family sets any today
        if tier != "max":
            assert cfg is spec.judge  # the identity


def test_tier_config_aux_models_and_unknown_pins():
    cfg = JudgeConfig(model="claude-haiku-9", aux_models={"summarizer": GEMINI, "unused": ""})
    for tier in ("lite", "standard"):
        assert tier_config(cfg, "stub", tier) is cfg  # a pin in no keep_pins survives
    hi = tier_config(cfg, "stub", "max")
    assert hi.model == MAX_JUDGE and dict(hi.aux_models) == {"summarizer": MAX_JUDGE, "unused": ""}
    assert tier_config(cfg, AM, "max") is cfg  # max keeps agentic's pin
    with pytest.raises(ValueError, match="tier must be one of"):
        tier_config(cfg, "stub", "ultra")


def test_tier_table_shape():
    assert tiers.DEFAULT_TIER == "standard" and tiers.TIERS == ("lite", "standard", "max")
    assert tiers.family_opts(JB, "lite") == {"read": "lite"}
    assert tiers.family_opts(AM, "lite") == {"stride": str(S_LITE)}
    for tier in ("standard", "max"):
        assert tiers.family_opts(JB, tier) == {} and tiers.family_opts(AM, tier) == {}
    assert [tier_read(t) for t in tiers.TIERS] == ["lite", "span", "span"]
    assert [tier_stride(t) for t in tiers.TIERS] == [S_LITE, 1, 1]


# ---- 2. precedence


def test_precedence_flag_env_tier_and_pinned(families):
    hal = tier_config(families["hallucination"].judge, "hallucination", "max")
    r = resolve(hal, env={})
    assert (r.model, r.source, r.pinned) == (MAX_JUDGE, "family", True)
    r = resolve(hal, env={"WSBENCH_JUDGE_MODEL": GEMINI})
    assert (r.model, r.source, r.pinned) == (GEMINI, "env", False)
    r = resolve(hal, flag=SONNET, env={"WSBENCH_JUDGE_MODEL": GEMINI})
    assert (r.model, r.source, r.pinned) == (SONNET, "flag", False)
    r = resolve(hal, flag=MAX_JUDGE, env={})  # an override equal to the tier instrument
    assert r.source == "flag" and r.pinned is True
    std = tier_config(families["hallucination"].judge, "hallucination", "standard")
    assert resolve(std, flag=GEMINI, env={}).pinned is True
    assert resolve(std, flag=MAX_JUDGE, env={}).pinned is False


# ---- 3. the lite read


def test_lite_positions_over_the_bank():
    total = 0
    n_equal = 0
    for it in _jb_items():
        rd = it["read"]
        lite, grid = lite_positions(rd), grid_positions(rd)
        assert set(lite) <= set(grid) and lite == sorted(set(lite)), it["id"]
        assert rd["turn_end"] in lite and set(punct_positions(rd)) <= set(lite)
        a, b = rd["span"]
        assert set(range(max(a, b - 16), b + 1)) <= set(lite)
        total += len(lite)
        n_equal += lite == grid
    assert total == 1859 and n_equal == 11


# ---- 4. completeness matrix


def _recognize(calls, **kw):
    return {c.key: {"verdicts": [{"index": 1, "label": "echo", "quote": ""}], "rationale": ""}
            for c in calls}  # fmt: skip


def _jb_readouts(tmp_path: Path, regime: str) -> Path:
    rows = [
        {"id": it["id"], "layer": 20, "pos": p, "samples": ["a persona"]}
        for it in _jb_items()
        for p in REGIMES[regime](it["read"])
    ]
    return write_jsonl(tmp_path / f"jb_{regime}.jsonl", rows)


def _args(readouts: Path, out: Path, judge, tier: str, extra: dict) -> JudgeArgs:
    return JudgeArgs(
        readouts=readouts,
        out=out,
        judge=judge,
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        concurrency=4,
        rpm=1e9,
        dry_run=False,
        extra=extra,
        tier=tier,
    )


def test_jailbreak_completeness_matrix(tmp_path, monkeypatch, families):
    monkeypatch.setattr(jb, "run_calls", _recognize)
    spec = families[JB]
    for regime in REGIMES:
        readouts = _jb_readouts(tmp_path, regime)
        for tier in tiers.TIERS:
            judge = resolve(tier_config(spec.judge, JB, tier), env={})
            out = tmp_path / f"o_{regime}_{tier}"
            res = jb.run(_args(readouts, out, judge, tier, {"read": regime}))
            assert res.counts["n_missing_cells"] == 0 and res.pinned_instrument
            assert res.config["tier"] == tier and res.config["read"] == regime
            want = regime == {"lite": "lite"}.get(tier, "span")  # punct: never
            assert res.complete is want, (regime, tier)


def test_agentic_completeness_matrix(tmp_path, monkeypatch, families):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_pace", no_pace)

    def responder(user, kw):
        stage = stage_of(user)
        return "note" if stage == "A" else "ACCOUNT" if stage == "B" else BENIGN_C

    fake = FakeText(responder)
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    from wsbench.evals.agentic_misalignment import judge as am

    spec = families[AM]
    bank = load_bank(AM)["items"]
    rows = [{"id": it["id"], "layer": 20, "pos": 0, "samples": ["R"]} for it in bank]
    readouts = write_jsonl(tmp_path / "am.jsonl", rows)
    for tier in tiers.TIERS:
        judge = resolve(tier_config(spec.judge, AM, tier), env={})
        assert judge.model == SONNET and judge.pinned
        for stride in (1, S_LITE):
            out = tmp_path / f"o_{tier}_{stride}"
            res = am.run(_args(readouts, out, judge, tier, {"stride": str(stride)}))
            assert res.config["tier"] == tier and res.config["stride"] == stride
            assert res.complete is (stride == tier_stride(tier)), (tier, stride)


# ---- 5 / 5b. standard unchanged; the lite tier end to end through the CLI


def test_standard_is_the_registry_instrument(families):
    for name, spec in families.items():
        assert tier_config(spec.judge, name, "standard") is spec.judge
        assert tier_config(spec.judge, name, "lite") is spec.judge
        assert tiers.family_opts(name, "standard") == {}
    fields = JudgeArgs.__dataclass_fields__
    assert fields["tier"].default == "standard"


def _offline(monkeypatch):
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    seen: list[str] = []
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: seen.append(model))
    return seen


def test_cli_run_lite_end_to_end(tmp_path, monkeypatch):
    seen = _offline(monkeypatch)
    calls: list[int] = []

    def fake_calls(cs, **kw):
        calls.append(len(cs))
        return _recognize(cs)

    monkeypatch.setattr(jb, "run_calls", fake_calls)
    root, out = tmp_path / "r", tmp_path / "o"
    root.mkdir()
    _jb_readouts(tmp_path, "lite").rename(root / f"{JB}.jsonl")
    argv = ["run", f"families={JB}", f"readouts_root={root}", f"out={out}", "tier=lite"]
    assert main(argv) == 0
    res = json.loads((out / JB / "results.json").read_text())
    assert res["config"]["tier"] == "lite" and res["config"]["read"] == "lite"
    assert res["complete"] is True and res["pinned_instrument"] is True
    assert calls == [1859] and seen == [SONNET]
    run = json.loads((out / "run.json").read_text())
    assert run["tier"] == "lite" and run["families"][JB]["complete"] is True
    assert (out / "summary.md").read_text().startswith("tier: lite\n\n|")

    # the user's opts= wins over the tier's: the run is then off-tier (incomplete)
    out2 = tmp_path / "o2"
    argv = ["run", f"families={JB}", f"readouts_root={root}", f"out={out2}", "tier=lite"]
    assert main([*argv, "opts=read=punct"]) == 0
    res = json.loads((out2 / JB / "results.json").read_text())
    assert res["config"]["read"] == "punct" and res["complete"] is False

    # standard on the same file: the span grid is missing -> the family fails, exit 2
    assert main(["run", f"families={JB}", f"readouts_root={root}", f"out={tmp_path / 's'}"]) == 2
    assert json.loads((tmp_path / "s" / "run.json").read_text())["tier"] == "standard"


def test_cli_judge_max_and_bad_tier(tmp_path, monkeypatch, capsys):
    _offline(monkeypatch)
    seen: list[tuple[str, dict, str]] = []

    def run(args):
        seen.append((args.judge.model, dict(args.extra), args.tier))
        return _result("stub", args.tier, pinned=args.judge.pinned)

    register(
        EvalSpec(
            name="stub",
            title="Stub",
            group="logic",
            bank=Path("evals/stub/items.json"),
            judge=JudgeConfig(),
            metric="pass_rate",
            higher_is_better=True,
            run=run,
        )
    )
    r = write_jsonl(tmp_path / "r.jsonl", [{"id": "a", "layer": 1, "pos": 1, "samples": ["x"]}])
    assert main(["judge", "family=stub", f"readouts={r}", f"out={tmp_path / 'o'}", "tier=max"]) == 0
    assert seen == [(MAX_JUDGE, {}, "max")]
    for cmd in (
        ["judge", "family=stub", f"readouts={r}", "tier=ultra"],
        ["run", "all=True", f"readouts_root={tmp_path}", f"out={tmp_path}", "tier=ultra"],
        ["report", f"dir={tmp_path}", "tier=ultra"],
        ["list", "tier=ultra"],
    ):
        assert main(cmd) == 2, cmd
        assert "tier must be one of" in capsys.readouterr().err


def test_list_judge_column_follows_tier(capsys):
    assert main(["list", "tier=max"]) == 0
    rows = {ln.split()[0]: ln for ln in capsys.readouterr().out.splitlines()[1:]}
    assert MAX_JUDGE in rows["basic_readout"] and SONNET in rows[AM]
    assert MAX_JUDGE in rows[JB] and "regex" in rows["basic_readout_mt"]
    assert "lite ≈ 9.3k" in rows[JB]
    assert main(["list"]) == 0
    rows = {ln.split()[0]: ln for ln in capsys.readouterr().out.splitlines()[1:]}
    assert GEMINI in rows["basic_readout"] and SONNET in rows[JB]


# ---- 6. report over tiers; floors follow the tier


def _result(family: str, tier: str | None, value: float = 0.5, pinned: bool = True):
    config = {"judge_model": GEMINI, "prompt_version": "v1"}
    if tier is not None:
        config["tier"] = tier
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=value,
        ci95=(0.4, 0.6),
        n_items=10,
        higher_is_better=True,
        chance=0.1,
        chance_label="1/10",
        complete=pinned,
        pinned_instrument=pinned,
        config=config,
        counts={
            "n_expected_cells": 10,
            "n_missing_cells": 0,
            "n_unjudged_cells": 0,
            "n_empty_cells": 0,
            "skipped_rows": 0,
            "spend_usd": 0.0,
        },
    )


def test_report_mixed_tiers_detect_and_filter(tmp_path, capsys):
    write_results(tmp_path / "a", _result("a", "lite", 0.25))
    write_results(tmp_path / "b", _result("b", None, 0.75))  # an old file reads as standard
    assert main(["report", f"dir={tmp_path}", "floors=False"]) == 2
    assert "lite, standard" in capsys.readouterr().err
    assert not (tmp_path / "summary.md").exists()

    assert main(["report", f"dir={tmp_path}", "tier=lite", "json=True", "floors=False"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert [f["family"] for f in d["families"]] == ["a"] and d["macro"]["value"] == 0.25
    text = (tmp_path / "summary_lite.md").read_text()
    assert text.startswith("tier: lite\n\n") and "| a |" in text and "| b |" not in text
    assert main(["report", f"dir={tmp_path}", "tier=standard", "floors=False"]) == 0
    assert "| b |" in (tmp_path / "summary_standard.md").read_text()
    assert not (tmp_path / "summary.md").exists()

    lite = tmp_path / "lite"
    write_results(lite / "a", _result("a", "lite"))
    assert main(["report", f"dir={lite}", "floors=False"]) == 0
    assert (lite / "summary.md").read_text().startswith("tier: lite\n\n")
    old = tmp_path / "old"
    write_results(old / "b", _result("b", None))
    assert main(["report", f"dir={old}", "floors=False"]) == 0
    assert (old / "summary.md").read_text().startswith("tier: standard\n\n")


def test_floors_follow_the_tier(tmp_path, monkeypatch, capsys, families):
    from wsbench.baselines import lucky_guessing as lg
    from wsbench.baselines import prompt_only as po

    uniform = {"mean": 0.1, "model": "seeded-uniform"}
    monkeypatch.setattr(
        lg,
        "floors",
        lambda: {
            "typo": {
                "blind": {"mean": 0.5, "model": GEMINI},
                "described": {"mean": 0.6, "model": GEMINI},
                "uniform": uniform,
            },
            "poetry": {"blind": {"mean": 0.3}},  # no model stamp: every tier
        },
    )
    monkeypatch.setattr(
        po,
        "floors",
        lambda: {
            "typo_mt": {"rate": 0.25, "judge_model": "regex"},
            "typo": {"rate": 1.0, "judge_model": GEMINI},
            JB: {"rate": 0.1, "judge_model": SONNET},
            AM: {"rate": 0.2, "judge_model": SONNET},
        },
    )
    lucky, prompt = "lucky guess (blind / described)", "prompt-only"
    std = floor_columns()
    assert std == floor_columns("standard") == floor_columns("lite")
    assert std[lucky] == {"typo": "0.500 / 0.600", "poetry": "0.300 / —"}
    assert set(std[prompt]) == {"typo_mt", "typo", JB, AM}
    hi = floor_columns("max")
    assert hi[lucky] == {"poetry": "0.300 / —"}  # typo drops out, not "— / —"
    assert set(hi[prompt]) == {"typo_mt", AM}  # regex everywhere; agentic keeps Sonnet

    write_results(tmp_path / "a", _result("a", "max"))
    assert main(["report", f"dir={tmp_path}", "json=True"]) == 0
    floors = json.loads(capsys.readouterr().out)["floors"]
    assert floors["lucky_guessing"] == {
        "typo": {"uniform": uniform},
        "poetry": {"blind": {"mean": 0.3}},
    }
    assert set(floors["prompt_only"]) == {"typo_mt", AM}
    assert (tmp_path / "summary.md").read_text().startswith("tier: max\n\n")


def test_freeze_prompt_only_refuses_off_standard(tmp_path, families):
    from wsbench.baselines import prompt_only as po

    def write(family: str, **config):
        r = _result(family, None)
        r.config.update(prompt_version=families[family].judge.prompt_version, **config)
        write_results(tmp_path / "run" / family, r)

    write("typo", tier="lite")
    with pytest.raises(ValueError, match="tier=lite"):
        po.freeze(tmp_path / "run", tmp_path / "po.json")
    assert main(["freeze", "kind=prompt_only", f"src={tmp_path / 'run'}", "dst=x.json"]) == 2
    write("typo", tier="standard")
    write(JB, tier="standard", read="lite")
    with pytest.raises(ValueError, match="read=lite"):
        po.freeze(tmp_path / "run", tmp_path / "po.json")
    write(JB, tier="standard", read="span")
    frozen = po.freeze(tmp_path / "run", tmp_path / "po.json")
    assert frozen["typo"]["tier"] == "standard" and frozen[JB]["tier"] == "standard"


# ---- 7. tier never enters a fingerprint


def test_lite_reuses_the_standard_cache(tmp_path, fake_llm, monkeypatch, families):
    it = _jb_items()[0]
    lite = lite_positions(it["read"])
    rows = [{"id": it["id"], "layer": 20, "pos": p, "samples": ["persona"]} for p in lite]
    readouts = write_jsonl(tmp_path / "r.jsonl", rows)
    spec = families[JB]
    judge = resolve(spec.judge, env={})
    seen: list[str] = []

    def responder(system, user):
        if user.startswith("Return"):
            return {"a": 1}
        seen.append(user)
        return {"verdicts": [{"index": 1, "label": "echo", "quote": ""}], "rationale": ""}

    fake_llm(responder)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm, "_make_client", lambda route, key: _AnthropicJSON(responder))
    out = tmp_path / "out"

    def args(tier, read):
        a = _args(readouts, out, judge, tier, {"read": read})
        a.allow_missing = True
        return a

    jb.run(args("standard", "span"))
    assert len(seen) == len(lite)
    fps = {json.loads(ln)["key"]: json.loads(ln)["fp"] for ln in (out / "cells.jsonl").open()}
    seen.clear()
    res = jb.run(args("lite", "lite"))
    assert seen == [] and res.config["tier"] == "lite"
    again = {json.loads(ln)["key"]: json.loads(ln)["fp"] for ln in (out / "cells.jsonl").open()}
    assert again == fps


class _AnthropicJSON:
    """An Anthropic-shaped fake for structured JSON calls (``responder(system, user)``)."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        r = self.responder(kw["system"][0]["text"], kw["messages"][0]["content"])
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(r))],
            usage=SimpleNamespace(input_tokens=7, output_tokens=3),
        )

    async def close(self):
        return None


# ---- 8. max on Opus 5.5 takes the always_thinks path


def test_max_judge_on_opus_asks_low_effort(monkeypatch, families):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(llm, "_backoff", lambda attempt, status: 0.0)

    async def no_pace(rpm: float) -> None:
        return None

    monkeypatch.setattr(llm, "_pace", no_pace)
    fake = _AnthropicJSON(lambda s, u: {"a": 1})
    monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
    judge = resolve(tier_config(families["hallucination"].judge, "hallucination", "max"), env={})
    assert judge.model == MAX_JUDGE and judge.reasoning == {"effort": "minimal"}  # inert here
    got: dict[int, dict | None] = {}
    stream_json(
        [("sys", "usr")],
        schema=schema_block("t", {"a": {"type": "integer"}}, ["a"]),
        model=judge.model,
        reasoning=judge.reasoning,
        on_result=got.__setitem__,
    )
    assert got == {0: {"a": 1}}
    kw = fake.calls[0]
    assert kw["model"] == MAX_JUDGE and kw["output_config"]["effort"] == "low"
    assert "thinking" not in kw and "reasoning" not in kw and "extra_body" not in kw
