"""multihop bank v4 = bank v3 without the 31 language / capital / opposite items and
b3-mh-fuji-currency. The list is derived mechanically from the v3 prompts, the kept items are
byte-identical, and v3's read plan (and every v3 readout file) serves v4."""

import json
from pathlib import Path

from wsbench import readplan, reads, registry
from wsbench.basic import mcjudge_bank as mj
from wsbench.basic.prompts import prompt_version_of

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "evals/multihop/items_v3.json"
V4 = REPO / "evals/multihop/items_v4.json"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _derive(items: list[dict]) -> dict[str, list[str]]:
    def by(word: str) -> list[str]:
        return [it["name"] for it in items if word in it["prompt"].lower()]

    return {"language": by("language"), "capital": by("capital"), "opposite": by("opposite")}


def test_removed_items_are_the_derived_categories():
    v3 = _raw(V3)
    cats = _derive(v3["items"])
    assert [len(cats[k]) for k in ("language", "capital", "opposite")] == [9, 20, 5]
    overlap = set(cats["language"]) & set(cats["capital"])
    assert len(overlap) == 3  # the "whose capital is X" language items
    union = set(cats["language"]) | set(cats["capital"]) | set(cats["opposite"])
    assert len(union) == 31
    removed = _raw(V4)["v4"]["removed"]
    assert {k: sorted(v) for k, v in removed.items() if k != "other"} == {
        k: sorted(v) for k, v in cats.items()
    }
    assert removed["other"] == ["b3-mh-fuji-currency"]
    kept = {it["name"] for it in _raw(V4)["items"]}
    assert kept == {it["name"] for it in v3["items"]} - union - {"b3-mh-fuji-currency"}
    assert len(kept) == 68 == _raw(V4)["v4"]["n_items"]
    # the antonym items are not "opposite" items and stay
    assert {"dbl-altitude-antonym", "dbl-armistice-antonym"} <= kept


def test_kept_items_are_byte_identical_and_v3_is_frozen():
    v3 = {it["name"]: it for it in _raw(V3)["items"]}
    v4 = _raw(V4)
    assert all(it == v3[it["name"]] for it in v4["items"])
    assert len(v3) == 100 and v4["version"] == 4 and v4["supersedes"] == "items_v3.json"


def test_v3_read_plan_serves_v4(real_families):
    assert _raw(V4)["read_plan_bank"] == "items_v3.json"
    spec = registry.FAMILIES["multihop"]
    assert spec.bank == Path("evals/multihop/items_v4.json")
    plan_ids = {s.id for s in readplan.plan("multihop")}
    assert len(plan_ids) == 100  # v3's rows: the frozen readouts' plan_sha still matches
    assert reads.plan_sha("multihop")


def test_stamp_and_call_key():
    pv = prompt_version_of("multihop")
    assert pv.endswith("+bank-v4") and "+" + mj.GATE_VERSION + "+" in pv
    assert mj.call_pv("multihop", pv) == "bank-mc-2026-11-01-v3"
