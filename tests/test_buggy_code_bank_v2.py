"""buggy_code bank v2 (2026-11-04): items.json's 63 items byte-identical + 40 new buggy/clean pairs
gated on Qwen3.6-27B as pairs, read with the bank's own plan (143 rows), stamped +bank-v2. No API
calls."""

import json
from pathlib import Path

import pytest

from wsbench import readplan, reads, registry
from wsbench.banks import load_bank
from wsbench.evals.buggy_code import judge
from wsbench.evals.buggy_code import prompts as bp

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "evals/buggy_code/items.json"
V2 = REPO / "evals/buggy_code/items_v2.json"
# the plan the bank-v2 readouts were produced for (143 rows)
PLAN_SHA_V2 = "4f3419aa2798700524635d3546c9f47f447d2b70747659537457b90ab034a126"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _registered(monkeypatch, real_families):
    monkeypatch.delenv("WSB_BANK_FILE_BUGGY_CODE", raising=False)


def test_v2_is_items_json_plus_40_pairs():
    v1, v2 = _raw(V1), _raw(V2)
    assert v2["version"] == 2 and v2["supersedes"] == "items.json"
    assert v2["items"][:63] == v1["items"]  # every kept item byte-identical, same order
    assert v2["read_cells"] == v1["read_cells"] and len(v1["items"]) == 63
    new = v2["items"][63:]
    assert len(new) == 80 == v2["v2"]["n_new"] and len(v2["items"]) == 143
    names = [it["name"] for it in v2["items"]]
    assert len(set(names)) == 143
    _h, items = load_bank(V2)
    assert len(judge.pairs_of(items)) == 64 == v2["v2"]["n_pairs"]  # 24 + 40


def test_new_pairs_are_adjacent_verified_silent_twins():
    new = _raw(V2)["items"][63:]
    buggy = [it for it in new if it["src"] == "buggy"]
    assert [it["name"] for it in buggy] == _raw(V2)["v2"]["new_pairs"] and len(buggy) == 40
    for b, c in zip(new[::2], new[1::2], strict=True):
        assert b["src"] == "buggy" and c["src"] == "clean", b["name"]
        assert b["twin"] == c["name"] == b["name"] + "-clean" and c["twin"] == b["name"]
        assert b["language"] == c["language"] and b["lang_group"] == c["lang_group"]
        assert (b["language"] == "python") == (b["lang_group"] == "python")
        for it in (b, c):
            assert it["verified"].startswith("exec: exit 0; stdout = ") and it["verified_by"]
        assert b["verified"] != c["verified"]  # the bug changes the output
        assert b["failure_mode"] == "silent" and not b["raises"]
        assert b["consequence_class"] in ("value", "categorical") and b["cause"]
        assert b["gate_tier"] in ("strict", "tolerant") and c["gate"] and "why_correct" in c


def test_v2_reads_its_own_plan(monkeypatch):
    assert registry.FAMILIES["buggy_code"].bank == Path("evals/buggy_code/items_v2.json")
    rows = readplan.plan("buggy_code")
    assert [s.id for s in rows] == [it["id"] for it in load_bank(V2)[1]]
    assert reads.plan_sha("buggy_code") == PLAN_SHA_V2
    for s in rows:  # the EOF cell at every GRID layer; lite = the bank layer
        assert s.render == "bare" and s.positions == {"kind": "final_token"}
        assert s.lite_layers in ([56], [60]) and s.layers == readplan.GRID
    # the 63 kept rows equal items.json's: their reads serve bank v2
    v2_rows = {s.id: s.row() for s in rows}
    monkeypatch.setenv("WSB_BANK_FILE_BUGGY_CODE", str(V1))
    v1_rows = {s.id: s.row() for s in readplan.plan("buggy_code")}
    assert len(v1_rows) == 63 and all(v2_rows[i] == r for i, r in v1_rows.items())


def test_stamp_by_bank_version():
    assert registry.FAMILIES["buggy_code"].judge.prompt_version == bp.PROMPT_VERSION
    assert bp.PROMPT_VERSION == bp.INSTRUMENT_V1 + "+bank-v2"
    assert judge.instrument(_raw(V2)) == bp.PROMPT_VERSION
    assert judge.instrument(_raw(V1)) == bp.INSTRUMENT_V1  # items.json / adapted banks: no suffix
    # the judge calls keep their key, so the kept items' cached calls serve bank v2
    assert bp.JUDGE_PROMPT_VERSION == "buggy-pairs-2026-10-29+infer-r1-2026-10-31"
