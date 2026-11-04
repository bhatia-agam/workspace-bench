"""multihop_mt_v2 bank v5 = bank v4 without Immanuel Kant among
mh2-kant-hume-edinburgh's bridge1 options (the prompt itself describes him). Every other byte is
v4's; the read plan is unchanged."""

import json
from pathlib import Path

from wsbench import reads, registry
from wsbench.evals.multihop_mt_v2 import prompts as mh2p
from wsbench.multitoken import family as fam
from wsbench.multitoken.options import option_sets

REPO = Path(__file__).resolve().parents[1]
V4 = REPO / "evals/multihop_mt_v2/items_v4.json"
V5 = REPO / "evals/multihop_mt_v2/items_v5.json"
KANT = "mh2-kant-hume-edinburgh"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_only_kant_leaves_kant_hume():
    v4 = {it["name"]: it for it in _raw(V4)["items"]}
    v5 = _raw(V5)
    assert v5["version"] == 5 and v5["supersedes"] == "items_v4.json"
    changed = [it["name"] for it in v5["items"] if it != v4[it["name"]]]
    assert changed == [KANT] and len(v5["items"]) == 70
    new = next(it for it in v5["items"] if it["name"] == KANT)["mc"]["bridge1"]
    old = v4[KANT]["mc"]["bridge1"]
    assert "Immanuel Kant" in old["distractors"] and "Immanuel Kant" not in new["distractors"]
    assert new["distractors"] == [d for d in old["distractors"] if d != "Immanuel Kant"]
    assert "Königsberg philosopher who wrote the Critique of Pure Reason" in v4[KANT]["prompt"]


def test_no_option_is_an_item_s_dropped_bridge():
    # the five three-hop -> two-hop relabels still describe the dropped bridge in their prompt
    for it in _raw(V5)["items"]:
        dropped = it.get("dropped_bridge")
        if dropped:
            for block in it["mc"].values():
                assert dropped not in block["distractors"], it["name"]


def test_kant_hume_shows_hume_and_three_others(real_families):
    from wsbench.banks import load_bank

    _h, items = load_bank(registry.bank_path("multihop_mt_v2"))
    opts, g = option_sets(items, cannot=mh2p.MH2_CANNOT)[KANT]["bridge1"]
    assert opts[g] == "David Hume" and "Immanuel Kant" not in opts and len(opts) == 5


def test_registered_stamp_call_key_and_plan(real_families):
    assert registry.bank_path("multihop_mt_v2") == V5
    assert mh2p.MH2_PROMPT_VERSION.endswith("+bank-v5")
    assert fam.call_pv("multihop_mt_v2", mh2p.MH2_PROMPT_VERSION).endswith("+bank-v4")
    assert reads.plan_sha("multihop_mt_v2").startswith("1d5f2e2fa84b")  # the readouts' plan
