"""multihop bank v5 (2026-11-04): bank v4's 68 items byte-identical + 30 new two-hop items gated on
Qwen3.6-27B, with their own read plan (98 rows), MC options built blind to every readout, and the
side tables' new entries (derived forms mhforms-v2, first-hop cues). No API calls."""

import json
import re
import sys
from pathlib import Path

from wsbench import mc, readplan, reads, registry
from wsbench.banks import load_bank
from wsbench.basic import mcjudge_bank as mj
from wsbench.basic.prompts import prompt_version_of

REPO = Path(__file__).resolve().parents[1]
MH = REPO / "evals/multihop"
V4 = MH / "items_v4.json"
V5 = MH / "items_v5.json"
GOLDEN = REPO / "tests/golden/multihop_mc_options_v5.json"
# the plan the bank-v5 readouts were produced for (98 rows); v4 read v3's 100-row plan
PLAN_SHA_V5 = "3c9751600ae29bce9dd39e2bdb08763819c66659d3f1719cface71ef51fdcb2a"
PLAN_SHA_V3 = "487cd9960ae52f5f3a1bd500abf47ded27624193edfdcc90e1761e969c68d898"
sys.path.insert(0, str(REPO / "scripts"))


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _new() -> list[dict]:
    return _raw(V5)["items"][68:]


def test_v5_is_v4_plus_30_new_items():
    v4, v5 = _raw(V4), _raw(V5)
    assert v5["version"] == 5 and v5["supersedes"] == "items_v4.json"
    assert "read_plan_bank" not in v5  # its own plan
    assert v5["items"][:68] == v4["items"]  # every kept item byte-identical, same order
    assert v4["version"] == 4 and len(v4["items"]) == 68  # v4 stays frozen beside it
    new = [it["name"] for it in v5["items"][68:]]
    assert new == v5["v5"]["new"] and len(new) == 30 == v5["v5"]["n_new"]
    assert len(v5["items"]) == 98 == v5["v5"]["n_items"]
    names = [it["name"] for it in v5["items"]]
    assert len(set(names)) == len(names)
    assert not set(v5["v5"]["excluded"]) & set(names)  # the 3 hand-read shortcuts stay out


def test_new_items_rules():
    """No kind bank v4 dropped (language, capital, opposite, currency), no bridge of banks v1-v4
    reused, distinct answers, and every gate leg recorded and passing."""
    old_bridges: set[str] = set()
    for name in ("items.json", "items_v2.json", "items_v3.json", "items_v4.json"):
        _h, items = load_bank(MH / name)
        for it in items:
            old_bridges |= {str(b).casefold() for b in it.get("intermediates", [])}
            if it.get("mc"):
                old_bridges.add(it["mc"]["gold"].casefold())
    new = _new()
    assert len({it["target"].casefold() for it in new}) == 30
    for it in new:
        low = it["prompt"].lower()
        assert not any(w in low for w in ("language", "capital", "opposite", "currency")), it
        assert it["mc"]["gold"].casefold() not in old_bridges, it["name"]
        assert it["mc"]["gold"] in it["intermediates"]
        assert it["eval_render"] == "plain" and it["readout"]["offsets"] == [-1]
        assert min(it["consistency"], it["bridge_consistency"], it["hop_consistency"]) >= 0.8
        probes = it["shortcut_probes"]
        assert any(p["leg"] == "s1" and p["gates"] for p in probes)
        assert not [p["text"] for p in probes if p["gates"] and p["reaches"]], it["name"]


def test_v5_reads_its_own_plan(real_families, monkeypatch):
    assert registry.FAMILIES["multihop"].bank == Path("evals/multihop/items_v5.json")
    rows = readplan.plan("multihop")
    assert [s.id for s in rows] == [it["id"] for it in load_bank(V5)[1]]
    assert reads.plan_sha("multihop") == PLAN_SHA_V5
    # the 68 kept rows equal v3's rows (bank v4's plan) on every hashed field: their reads serve
    v5_rows = {s.id: s.row() for s in rows}
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(V4))
    assert reads.plan_sha("multihop") == PLAN_SHA_V3
    v3_rows = {s.id: s.row() for s in readplan.plan("multihop")}
    kept = [it["id"] for it in load_bank(V4)[1]]
    assert all(v5_rows[i] == v3_rows[i] for i in kept)


def test_options_v5_golden_and_clean():
    golden = _raw(GOLDEN)
    _h, items = load_bank(V5)
    assert sorted(golden) == sorted(it["id"] for it in items)
    for it in items:
        shown, gold_idx = mj.options_of("multihop", it)
        assert shown == golden[it["id"]], it["id"]
        assert len(shown) == 6 and shown[-1] == mc.CANNOT and shown[gold_idx] == it["mc"]["gold"]
    for it in _new():
        block = it["mc"]
        forms = {f.casefold() for f in [block["gold"], *block["aliases"]]}
        assert len(block["distractors"]) == 4 and block["topic_confusers"] >= 2
        for d in block["distractors"]:
            assert d.casefold() not in forms and d.casefold() != it["target"].casefold()
            assert not mc.form_in(it["prompt"], [d]), (it["name"], d)


def test_side_tables_cover_v5_and_leave_earlier_entries():
    import mc_leakage_r4 as r4

    table = _raw(MH / "derived_forms.json")
    assert table["version"] == "mhforms-v2"
    forms = table["forms"]
    earlier: set[str] = set()
    for name in ("items.json", "items_v2.json", "items_v3.json", "items_v4.json"):
        _h, items = load_bank(MH / name)
        earlier |= {
            o for it in items if it.get("mc") for o in [it["mc"]["gold"], *it["mc"]["distractors"]]
        }
    new_opts = {o for it in _new() for o in [it["mc"]["gold"], *it["mc"]["distractors"]]}
    assert new_opts <= set(forms)
    # every key added for bank v5 is an option of a new item only, so no bank v1-v4 verdict moves
    added = list(forms)[-105:]
    assert set(added) <= new_opts and not set(added) & earlier
    cues = _raw(MH / "split_subjects.json")
    assert cues["version"] == "split-subjects-r4"
    for it in _new():
        c = cues["subjects"][it["name"]]
        assert c and r4.split_subject({"id": it["name"]}) == c
        words = {
            w
            for o in [it["mc"]["gold"], *it["mc"]["distractors"]]
            for w in re.findall(r"[^\W\d_]+", mc.fold(o))
        }
        assert not {mc.fold(alt) for x in c for alt in x.split("|")} & words, it["name"]


def test_stamp_and_call_key():
    pv = prompt_version_of("multihop")
    assert pv == "bank-mc-2026-11-01-v3+bank-gate-r10+bank-v5"
    assert mj.GATE_VERSION == "bank-gate-r10"
    assert mj.call_pv("multihop", pv) == "bank-mc-2026-11-01-v3"  # cached calls stay valid


def test_leakage_floors_recorded():
    ml = _raw(V5)["mc_leakage_v5"]
    assert ml["chance"] == 0.2 and ml["bar"] == 0.25 and ml["n"]["items"] == 98
    for guesser in ("blind", "described", "topic"):
        f = ml["floors"][guesser]
        assert f["bank_98"] <= ml["bar"] and f["new_30"] <= ml["bar"], guesser
