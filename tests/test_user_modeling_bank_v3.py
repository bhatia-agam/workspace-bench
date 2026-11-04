"""user_modeling bank v3 (2026-11-04): items.json's 47 selfdescribe items byte-identical + 79 new
selfdescribe items gated on Qwen3.6-27B, with their own read plan (126 rows), the um-v3.5 option
lists (NEIGHBOURS for the new golds) and the +bank-v3 stamp. No API calls."""

import hashlib
import json
from pathlib import Path

import pytest

from wsbench import mc, readplan, reads, registry
from wsbench.evals.user_modeling import aliases, judge, options, prompts
from wsbench.evals.user_modeling.judge import build_options
from wsbench.mcjudge import load_bank

ROOT = Path(__file__).resolve().parents[1]
UM = ROOT / "evals/user_modeling"
V3 = UM / "items_v3.json"
# the plan the bank-v3 readouts were produced for (126 rows); v1 / v2 read items.json's 100 rows
PLAN_SHA_V3 = "9cc43bf742edf7eb5b29f84ad815d79fc61d9769d9690ceafcf8f76e427aa709"
GOLDEN_V4 = json.loads((ROOT / "tests/golden/user_modeling_options_v4.json").read_text())
GOLDEN_V5 = json.loads((ROOT / "tests/golden/user_modeling_options_v5.json").read_text())


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _registered(monkeypatch, real_families):
    monkeypatch.delenv("WSB_BANK_FILE_USER_MODELING", raising=False)


def test_v3_is_v1s_selfdescribe_items_plus_79_new_items():
    v1, v3 = _raw(UM / "items.json"), _raw(V3)
    assert v3["version"] == 3 and v3["supersedes"] == "items.json"
    assert "read_plan_bank" not in v3  # its own plan
    kept = [it for it in v1["items"] if it["subfamily"] == "selfdescribe"]
    assert v3["items"][:47] == kept  # every kept item byte-identical, same order
    sha = hashlib.sha256((UM / "items.json").read_bytes()).hexdigest()
    assert v3["source_sha256"] == {"items.json": sha}
    assert len(v1["items"]) == 100 and len(kept) == 47
    assert not (UM / "items_v2.json").exists()
    new = v3["items"][47:]
    assert len(new) == 79 and len(v3["items"]) == 126
    names = [it["name"] for it in v3["items"]]
    assert len(set(names)) == 126 and all(n.startswith("um-sd2-") for n in names[47:])


def test_new_items_are_implied_selfdescribe_items():
    for it in _raw(V3)["items"][47:]:
        assert it["subfamily"] == "selfdescribe" and it["eval_render"] == "chat_context"
        assert it["readout"] == {"kind": "task_sentence_through_prompt_end"}
        assert it["messages"][0] == {"role": "system", "content": "You are a helpful assistant."}
        user = it["messages"][-1]["content"]
        assert user.endswith(
            "Write a hypothetical but realistic Wikipedia biography infobox for me."
        )
        # implied only: no listed form of any value of the class appears in the message
        for v in aliases.UM_OPTION_POOL[it["attr_class"]]:
            assert not mc.form_in(user, aliases.VALUE_ALIASES[v]), (it["name"], v)
        assert len(it["authoring"]["cues"]) >= 2 and it["consistency"] >= 0.8


def test_registered_bank_stamp_and_instrument():
    spec = registry.FAMILIES["user_modeling"]
    assert spec.bank == Path("evals/user_modeling/items_v3.json")
    assert spec.judge.prompt_version == prompts.PROMPT_VERSION == "um-v3.5+bank-v3"
    assert judge.instrument(load_bank("user_modeling")) == "um-v3.5+bank-v3"
    assert judge.instrument({"version": 2}) == "um-v3.5+bank-v2"
    assert judge.instrument({}) == prompts.CALL_VERSION == "um-v3.5"


def test_v3_reads_its_own_plan(monkeypatch):
    rows = readplan.plan("user_modeling")
    assert [s.id for s in rows] == [it["name"] for it in _raw(V3)["items"]]
    assert reads.plan_sha("user_modeling") == PLAN_SHA_V3
    # the 47 kept rows equal items.json's rows on every hashed field: their reads serve bank v3
    v3_rows = {s.id: s.row() for s in rows}
    monkeypatch.setenv("WSB_BANK_FILE_USER_MODELING", "evals/user_modeling/items.json")
    v1_rows = {s.id: s.row() for s in readplan.plan("user_modeling")}
    kept = [it["name"] for it in _raw(V3)["items"][:47]]
    assert all(v3_rows[i] == v1_rows[i] for i in kept)


def test_options_kept_unchanged_and_new_lists_pinned():
    items = _raw(V3)["items"]
    opts = build_options(items)
    assert set(GOLDEN_V5) == set(opts)
    for it in items:
        shown, gold_position = opts[it["name"]]
        assert {"options": shown, "gold_position": gold_position} == GOLDEN_V5[it["name"]]
        if it["name"] in GOLDEN_V4:  # the 47 kept items: their um-v3.4 lists, byte for byte
            assert GOLDEN_V5[it["name"]] == GOLDEN_V4[it["name"]]
        value = options.value_id(it["attr"])
        assert shown[gold_position - 1] == options.display_value(it["attr"])
        assert len(set(shown)) == len(shown)
        for d in shown:
            assert options.value_of(d) in aliases.UM_OPTION_POOL[it["attr_class"]]
        if it["attr_class"] in ("Country", "Occupation"):
            assert set(aliases.NEIGHBOURS[value]) <= {options.value_of(o) for o in shown}


def test_new_neighbours_touch_no_earlier_gold():
    """um-v3.5 adds NEIGHBOURS for the Country / Occupation golds of the new candidates (the 9
    golds of the 79 kept items among them), none a bank v1 / v2 gold, so no earlier list moves."""
    v1 = _raw(UM / "items.json")["items"]
    new = _raw(V3)["items"][47:]
    added = {
        "japan", "brazil", "finland", "poland", "mexico", "australia",
        "nurse", "electrician", "librarian", "chef", "farmer", "accountant",
    }  # fmt: skip
    assert added <= set(aliases.NEIGHBOURS)
    assert not added & {options.value_id(it["attr"]) for it in v1}
    golds = {
        options.value_id(it["attr"]) for it in new if it["attr_class"] in ("Country", "Occupation")
    }
    assert len(golds) == 9 and golds <= added
