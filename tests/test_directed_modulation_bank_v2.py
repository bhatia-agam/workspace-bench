"""directed_modulation bank v2 (plan 0109, 2026-11-20): items.json's 35 think + 15 secret + 15
preference items byte-identical and in order, its 35 dont_think items removed, 37 new think
items gated on Qwen3.6-27B; read with the bank's own plan (102 rows), stamped +bank-v2. No API
calls."""

import json
from pathlib import Path

import pytest

from wsbench import readplan, reads, registry
from wsbench.banks import load_bank
from wsbench.evals.basic.directed_modulation import judge
from wsbench.evals.basic.directed_modulation import prompts as dp

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "evals/basic/directed_modulation/items.json"
V2 = REPO / "evals/basic/directed_modulation/items_v2.json"
GOLDEN_V1 = REPO / "tests/golden/directed_modulation_options.json"
GOLDEN_V2 = REPO / "tests/golden/directed_modulation_options_v2.json"
# the plans the readouts are produced for: items.json's 100 rows, bank v2's 102 rows
PLAN_SHA_V1 = "1da94e9cd24b0a10b951957ca383d62658700ae241c0f2f7d3aa4231f842b820"
PLAN_SHA_V2 = "940bf69a0dbc0482120ab41fc24e0b1a5b948e8b6b1b5323e99b99bf2c5253b3"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _golden(p: Path) -> dict:
    return {k: (v["options"], v["gold_position"]) for k, v in _raw(p)["options"].items()}


@pytest.fixture(autouse=True)
def _registered(monkeypatch, real_families):
    monkeypatch.delenv("WSB_BANK_FILE_DIRECTED_MODULATION", raising=False)


def test_v2_is_items_json_minus_dont_think_plus_37_think():
    v1, v2 = _raw(V1), _raw(V2)
    assert v2["version"] == 2 and v2["supersedes"] == "items.json"
    assert len(v1["items"]) == 100 and len(v2["items"]) == 102
    kept = [it for it in v1["items"] if it["polarity"] != "dont_think"]
    assert len(kept) == 65 and v2["items"][:65] == kept  # byte-identical, original order
    dropped = [it["name"] for it in v1["items"] if it["polarity"] == "dont_think"]
    assert dropped == v2["removed_items"] and len(dropped) == 35
    new = v2["items"][65:]
    assert [it["name"] for it in new] == v2["new_items"] and len(new) == 37
    assert {(it["subfamily"], it["polarity"]) for it in new} == {("pair", "think")}
    assert all(it["pair_id"] is None and it["source"] == "dm-v2" for it in new)
    assert not any(it["polarity"] == "dont_think" for it in v2["items"])
    kinds = [(it["subfamily"], it["polarity"]) for it in v2["items"]]
    assert kinds.count(("pair", "think")) == 72 == 35 + 37
    assert kinds.count(("secret", "suppress")) == kinds.count(("preference", "suppress")) == 15
    assert v2["counts"] == {
        "n_items": 102,
        "think_kept": 35,
        "think_new": 37,
        "secret": 15,
        "preference": 15,
        "removed_dont_think": 35,
    }
    names = [it["name"] for it in v2["items"]]
    concepts = [it["concept"] for it in v2["items"]]
    assert len(set(names)) == 102 == len(set(concepts))  # no concept twice
    for it in new:  # the frozen item shape: the carrier is copied and never holds the concept
        assert it["assistant"] == it["carrier"] and f'"{it["carrier"]}"' in it["prompt"]
        assert it["concept"].lower() not in it["carrier"].lower()
        assert it["concept"] in it["prompt"] and it["consistency"] >= 0.8


def test_v2_reads_its_own_plan(monkeypatch):
    assert registry.FAMILIES["directed_modulation"].bank == Path(
        "evals/basic/directed_modulation/items_v2.json"
    )
    rows = readplan.plan("directed_modulation")
    assert [s.id for s in rows] == [it["id"] for it in load_bank(V2)[1]]
    assert reads.plan_sha("directed_modulation") == PLAN_SHA_V2
    assert "plan_lineage" not in _raw(V2)  # drop + add is no drop-only step
    v2_rows = {s.id: s.row() for s in rows}
    monkeypatch.setenv("WSB_BANK_FILE_DIRECTED_MODULATION", str(V1))
    assert reads.plan_sha("directed_modulation") == PLAN_SHA_V1
    v1_rows = {s.id: s.row() for s in readplan.plan("directed_modulation")}
    kept = [i for i in v1_rows if i in v2_rows]
    # the 65 kept rows equal items.json's: their reads serve bank v2
    assert len(kept) == 65 and all(v2_rows[i] == v1_rows[i] for i in kept)
    assert len(v1_rows) == 100 and len(v2_rows) - len(kept) == 37


def test_option_lists_by_bank():
    """The pool is the whole subfamily: every kept think item's list is new on bank v2, every
    secret / preference list is items.json's; items.json's own lists did not move when the new
    concepts joined the groups file."""
    _h, v1 = load_bank(V1)
    _h, v2 = load_bank(V2)
    o1, o2 = judge.option_sets(v1), judge.option_sets(v2)
    assert o1 == _golden(GOLDEN_V1) and o2 == _golden(GOLDEN_V2)
    assert len(o1) == 100 and len(o2) == 102
    by = {it["id"]: it for it in v2}
    kept = [i for i in o2 if i in o1]
    same = {i for i in kept if o1[i] == o2[i]}
    assert same == {i for i in kept if by[i]["subfamily"] != "pair"} and len(same) == 30
    assert len(kept) - len(same) == 35
    pools = {s: {it["concept"] for it in v2 if it["subfamily"] == s} for s in ("pair", "secret")}
    assert len(pools["pair"]) == 72
    for i, (shown, gold_pos) in o2.items():
        it = by[i]
        gold = it["concept"]
        assert len(shown) == 5 == len(set(shown)) and shown[gold_pos - 1] == gold
        group = judge.group_of(gold)
        assert all(judge.group_of(c) != group for c in shown if c != gold)
        if it["subfamily"] in pools:
            assert set(shown) <= pools[it["subfamily"]]


def test_stamp_by_bank_version():
    assert registry.FAMILIES["directed_modulation"].judge.prompt_version == dp.PROMPT_VERSION
    assert dp.PROMPT_VERSION == dp.INSTRUMENT_V1 + "+bank-v2" == "dm-2026-10-31+expressed+bank-v2"
    assert judge.instrument(_raw(V2)) == dp.PROMPT_VERSION
    assert judge.instrument(_raw(V1)) == dp.INSTRUMENT_V1  # items.json (no version): no suffix
    assert judge.instrument({}) == dp.INSTRUMENT_V1
    assert judge.instrument() == dp.PROMPT_VERSION  # no header: the bank judged now


def test_prompt_only_freeze_accepts_the_judged_banks_stamp(monkeypatch):
    """An unversioned bank (items.json; the adapted sets before plan 0113) still stamps
    ``dm-2026-10-31+expressed``, and the prompt-only freeze accepts a floor on that stamp while
    that bank is the one judged (``prompt_only.judged_bank_stamp``)."""
    from wsbench.baselines import prompt_only as po

    assert po.summary_bases("directed_modulation", dp.PROMPT_VERSION) == (dp.PROMPT_VERSION,)
    monkeypatch.setenv("WSB_BANK_FILE_DIRECTED_MODULATION", str(V1))
    assert po.judged_bank_stamp("directed_modulation") == dp.INSTRUMENT_V1
    assert po.summary_bases("directed_modulation", dp.PROMPT_VERSION) == (
        dp.PROMPT_VERSION,
        dp.INSTRUMENT_V1,
    )
    # the judge calls keep their key (no prompt changed)
    assert dp.JUDGE_PROMPT_VERSION == "dm-2026-10-31"


def test_toy_file_reads_the_registered_bank():
    ids = {it["id"] for it in load_bank(V2)[1]}
    toy = REPO / "examples/readouts/directed_modulation.jsonl"
    rows = [json.loads(x) for x in toy.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {r["id"] for r in rows} == {"dm-pair-00-pos", "dm-think-35", "dm-secret-00"} <= ids
