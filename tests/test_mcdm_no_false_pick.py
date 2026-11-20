"""Plan 0100: in summary mode a multi_concept_directed_modulation item passes only when every
dictated concept is credited AND the judge made no false pick; native's verdict is unchanged."""

import re
from pathlib import Path

import pytest
from conftest import native_args, write_jsonl
from summary_fakes import FakeLLM, digest_lines, summary_args

from wsbench.banks import load_bank
from wsbench.cache import fingerprint
from wsbench.evals import multi_concept_directed_modulation as pkg
from wsbench.evals.multi_concept_directed_modulation import judge, options, prompts
from wsbench.evals.multi_concept_directed_modulation.options import option_sets
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.registry import bank_path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/readouts/multi_concept_directed_modulation.jsonl"
CB = "content_bound"
OPTIONS = ["violin", "jar of honey", "origami", "tightrope", "walrus", "zeppelin"]
GOLD = [0, 1]
READOUT = "a violin beside a jar of honey, an origami crane on a tightrope"
ITEM = {"id": "d-x", "name": "d-x", "concepts": ["violin", "jar of honey"], "stratum": "pair"}
REGIONS = {-1: judge.Region.IN_SENTENCE}


@pytest.fixture(autouse=True)
def _registered(real_families):
    return real_families


def _pick(letter: str, quote: str, basis: str = CB) -> dict:
    return {"choice": letter, "quote": quote, "basis": basis}


GOLD_PICKS = [_pick("A", "a violin"), _pick("B", "a jar of honey")]


def _cell(picks: list[dict] | None, pos: int = -1) -> dict:
    res = None if picks is None else {"picks": picks}
    return {"item": "d-x", "layer": -1, "pos": pos, **judge.verdict(res, OPTIONS, GOLD, READOUT)}


def _row(cells: list[dict], *, summary: bool, item: dict = ITEM, regions=REGIONS, **kw) -> dict:
    opts = kw.pop("opts", (OPTIONS, GOLD))
    partner = kw.pop("partner", set())
    extra = {"no_false_pick": True} if summary else {}
    return judge._item_row(item, opts, partner, regions, None, cells, [], set(), set(), [44],
                           **extra)  # fmt: skip


def test_summary_item_with_a_verified_false_pick_fails():
    clean = _row([_cell(GOLD_PICKS)], summary=True)
    assert clean["pass"] is True and clean["false_pick_fail"] is False
    assert clean["pass_no_false_pick"] is True and clean["false_picks"] == []
    stray = _row([_cell([*GOLD_PICKS, _pick("D", "on a tightrope")])], summary=True)
    assert stray["pass"] is False and stray["reason"] is None
    assert stray["false_pick_fail"] is True and stray["false_picks"] == ["tightrope"]
    assert stray["concepts_surfaced"] == ["jar of honey", "violin"]  # the credit is unchanged
    assert stray["pass_no_false_pick"] is False


def test_false_pick_counts_whatever_its_basis():
    """Rulings: any verified pick of a non-dictated candidate, an invalid basis included."""
    for basis in ("incidental", "instruction_narration", "no-such-basis", None):
        row = _row([_cell([*GOLD_PICKS, _pick("C", "an origami crane", basis)])], summary=True)
        assert row["pass"] is False and row["false_pick_fail"] is True, basis


def test_unverified_wrong_pick_does_not_fail_the_item():
    """A wrong pick whose quote is in no readout is dropped before the rule and never counts."""
    v = _cell([*GOLD_PICKS, _pick("E", "a walrus on the ice")])
    assert v["false"] == [] and v["n_unverified"] == 1
    row = _row([v], summary=True)
    assert row["pass"] is True and row["false_pick_fail"] is False and row["false_picks"] == []


def test_false_pick_is_a_decided_fail():
    """Like the partner veto: no unjudged cell can rescue an item with a false pick."""
    regions = {-2: judge.Region.IN_SENTENCE, -1: judge.Region.IN_SENTENCE}
    cells = [_cell([_pick("A", "a violin"), _pick("D", "on a tightrope")], -2), _cell(None, -1)]
    assert _row(cells, summary=True, regions=regions)["pass"] is False
    native = _row(cells, summary=False, regions=regions)
    assert native["pass"] is None and native["reason"] == "unjudged"
    assert native["pass_no_false_pick"] is False  # the extras channel is decided in both modes
    # one concept missing and a cell unjudged, no false pick: undecided in both channels
    cells = [_cell([_pick("A", "a violin")], -2), _cell(None, -1)]
    row = _row(cells, summary=True, regions=regions)
    assert row["pass"] is None and row["pass_no_false_pick"] is None


def test_native_verdict_is_unchanged_and_records_the_stricter_rule():
    cells = [_cell([*GOLD_PICKS, _pick("D", "on a tightrope")])]
    native = _row(cells, summary=False)
    assert native["pass"] is True and native["false_picks"] == ["tightrope"]
    assert native["pass_no_false_pick"] is False and native["false_pick_fail"] is True
    # the keyword is the only mode signal: the same cells, the summary rule
    assert _row(cells, summary=True)["pass"] is False
    # a non-pass for another reason is not a false-pick fail
    short = _row([_cell([_pick("A", "a violin"), _pick("D", "on a tightrope")])], summary=True)
    assert short["pass"] is False and short["false_pick_fail"] is False


def test_controls_keep_pass_none():
    control = {"id": "d-none", "name": "d-none", "concepts": [], "stratum": "control"}
    res = {"picks": [_pick("D", "on a tightrope")]}
    v = {"item": "d-none", "layer": -1, "pos": -1, **judge.verdict(res, OPTIONS, [], READOUT)}
    row = _row([v], summary=True, item=control, opts=(OPTIONS, []))
    assert row["pass"] is None and row["reason"] == "control"
    assert row["pass_no_false_pick"] is None and row["false_pick_fail"] is False


REL = ["Adam being angry at Betty", "Betty being angry at Adam", "x", "y", "z", "w"]
REL_ITEM = {"id": "b-x", "name": "b-x-ab", "concepts": [REL[0]], "stratum": "names"}


def _rel_cell(picks: list[dict], readout: str) -> dict:
    return {"item": "b-x", "layer": -1, "pos": -1,
            **judge.verdict({"picks": picks}, REL, [0], readout, partner=[1])}  # fmt: skip


def test_relation_item_partner_veto_is_as_before():
    """The partner veto is retained (and now implied): a credited relation alone passes (its
    people are no candidates, so a component is never a false pick); the partner direction named
    too fails in both modes with ``partner_as_content`` reported as before."""
    readout = "Adam is angry at Betty. Betty is angry at Adam."
    own = _pick("A", "Adam is angry at Betty")
    alone = _rel_cell([own], readout)
    for summary in (True, False):
        row = _row([alone], summary=summary, item=REL_ITEM, opts=(REL, [0]), partner={REL[1]})
        assert row["pass"] is True and row["false_pick_fail"] is False
        assert row["partner_as_content"] == [] and row["partner_picked"] is False
    both = _rel_cell([own, _pick("B", "Betty is angry at Adam")], readout)
    assert both["kind"] == "direction_conflict"
    for summary in (True, False):
        row = _row([both], summary=summary, item=REL_ITEM, opts=(REL, [0]), partner={REL[1]})
        assert row["pass"] is False and row["partner_as_content"] == [REL[1]]
        assert row["partner_picked"] is True and row["false_pick_fail"] is False


# ---------------------------------------------------------------- end to end

_LETTER_LINE = re.compile(r"^([A-F])\. (.*)$", re.M)


def _summary_judge(extra_pick: bool):
    _h, items = load_bank(bank_path(pkg.SPEC.name))
    opts = option_sets(items)

    def answer(system: str, user: str, schema: dict) -> dict:
        shown = [o for _l, o in _LETTER_LINE.findall(user)]
        item = next(i for i, (o, _g) in opts.items() if o == shown)
        quote = re.sub(r"^\[[^\]]*\] ", "", digest_lines(user)[0])[:12]
        _o, gold = opts[item]
        picks = [_pick("ABCDEF"[g], quote) for g in gold]
        if extra_pick and gold:
            wrong = next(i for i in range(len(shown)) if i not in gold)
            picks.append(_pick("ABCDEF"[wrong], quote, "incidental"))
        return {"picks": picks}

    return answer


def test_summary_run_fails_the_item_and_reports_the_extras(tmp_path, monkeypatch):
    pv = prompts.PROMPT_VERSION
    FakeLLM.install(monkeypatch, _summary_judge(extra_pick=False))
    r = pkg.SPEC.run(summary_args(EXAMPLE, tmp_path / "a", pv, items=["d-plumber", "d-none"]))
    row = {x["id"]: x for x in r.rows}["d-plumber"]
    assert row["pass"] is True and row["false_pick_fail"] is False
    assert r.value == 1.0 and r.extras["no_false_pick_rate"] == 1.0
    assert r.extras["n_false_pick_fails"] == 0
    assert r.config["prompt_version"].startswith(pv) and "+nofalse-a2" in pv
    FakeLLM.install(monkeypatch, _summary_judge(extra_pick=True))
    r = pkg.SPEC.run(summary_args(EXAMPLE, tmp_path / "b", pv, items=["d-plumber", "d-none"]))
    rows = {x["id"]: x for x in r.rows}
    row = rows["d-plumber"]
    assert row["pass"] is False and row["false_pick_fail"] is True and len(row["false_picks"]) == 1
    assert len(row["concepts_surfaced"]) == 3 and row["concept_recall"] == 1.0
    assert rows["d-none"]["pass"] is None and rows["d-none"]["reason"] == "control"
    assert r.value == 0.0 and r.extras["no_false_pick_rate"] == 0.0
    assert r.extras["n_false_pick_fails"] == 1


def test_native_run_keeps_its_pass_and_reports_the_stricter_rate(tmp_path, monkeypatch):
    bank = load_bank(bank_path(pkg.SPEC.name))[1]
    s = options.build(bank)["d-lion"]
    golds = [s.options[g] for g in s.gold]
    wrong = next(o for o in s.options if o not in golds)
    # the 12 prefilled sentence tokens (the write-compliance gate), pos -12 .. -1
    sent = ["The", " committee", " will", " meet", " on", " Thursday", " to", " review", " the",
            " annual", " budget", "."]  # fmt: skip
    rows = [
        {"id": "d-lion", "layer": 44, "pos": i - 12, "token": tok,
         "tokens": [*golds, wrong] if i == 11 else []}
        for i, tok in enumerate(sent)
    ]  # fmt: skip
    path = write_jsonl(tmp_path / "r.jsonl", rows)

    def fake_run_calls(calls, **kw):
        picks = [_pick(prompts.LETTERS[s.options.index(o)], o) for o in [*golds, wrong]]
        return {c.key: {"picks": picks} for c in calls}

    monkeypatch.setattr(judge, "run_calls", fake_run_calls)
    args = native_args(readouts=path, out=tmp_path / "o",
                       judge=resolve(JudgeConfig(prompt_version=prompts.PROMPT_VERSION)),
                       layers=None, items=["d-lion"], limit=0, allow_missing=True, concurrency=1,
                       rpm=1.0, dry_run=False)  # fmt: skip
    r = judge.run(args)
    row = r.rows[0]
    assert row["pass"] is True and r.value == 1.0  # native: today's rule exactly
    assert row["false_picks"] == [wrong] and row["false_pick_fail"] is True
    assert r.extras["no_false_pick_rate"] == 0.0 and r.extras["n_false_pick_fails"] == 1


# ---------------------------------------------------------------- the cache key does not move


def test_judge_call_fingerprint_is_unchanged_by_plan_0100():
    """No prompt text and no call key changed: a fixed call hashes exactly as before the plan
    (the literal was computed on the commit before it), so every cached judge call replays."""
    assert prompts.JUDGE_PROMPT_VERSION == "mcdm-2026-11-01e"
    assert "nofalse" not in prompts.JUDGE_PROMPT_VERSION
    user = prompts.render_user(
        "- a plumber fixing a violin", ["violin", "plumber", "x", "y", "z", "w"], summary_note=None
    )
    j = resolve(JudgeConfig(prompt_version=prompts.PROMPT_VERSION))
    fp = fingerprint(prompts.JUDGE_PROMPT_VERSION, j.model, j.reasoning, 0.0, prompts.SYSTEM, user)
    assert fp == "fcaeace91f5bb230"


def test_summary_calls_are_keyed_by_the_judge_prompt_version(tmp_path, monkeypatch):
    seen: dict[str, str] = {}
    real = judge.run_calls

    def spy(calls, **kw):
        seen["pv"] = kw["prompt_version"]
        return real(calls, **kw)

    monkeypatch.setattr(judge, "run_calls", spy)
    FakeLLM.install(monkeypatch, _summary_judge(extra_pick=False))
    args = summary_args(EXAMPLE, tmp_path / "k", prompts.PROMPT_VERSION, items=["d-plumber"])
    pkg.SPEC.run(args)
    assert seen["pv"].startswith(prompts.JUDGE_PROMPT_VERSION + "+digest-")
    assert "nofalse" not in seen["pv"] and "nocap" not in seen["pv"]
