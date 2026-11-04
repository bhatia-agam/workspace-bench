"""basic_readout_mt bank v5 = bank v4 without the sarin item (the
bank's only weapon-related item, whose digest was refused on most layers). The kept items are
byte-identical and v4's read plan (and every v4 readout file) serves v5."""

import json
from pathlib import Path

from wsbench import readplan, reads, registry
from wsbench.multitoken import family as fam
from wsbench.multitoken import prompts as mp

REPO = Path(__file__).resolve().parents[1]
V4 = REPO / "evals/basic_readout_mt/items_v4.json"
V5 = REPO / "evals/basic_readout_mt/items_v5.json"
SARIN = "brh-ent-chem-sarin-systematic"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_v5_is_v4_without_the_sarin_item():
    v4 = {it["name"]: it for it in _raw(V4)["items"]}
    v5 = _raw(V5)
    assert v5["version"] == 5 and v5["supersedes"] == "items_v4.json"
    assert v5["v5"]["removed"] == [SARIN] and SARIN in v4
    assert [it["name"] for it in v5["items"]] == [n for n in v4 if n != SARIN]
    assert all(it == v4[it["name"]] for it in v5["items"])


def test_v4_read_plan_serves_v5(real_families):
    assert _raw(V5)["read_plan_bank"] == "items_v4.json"
    assert registry.bank_path("basic_readout_mt") == V5
    assert len({s.id for s in readplan.plan("basic_readout_mt")}) == 99  # v4's rows
    assert reads.plan_sha("basic_readout_mt").startswith("4c8f2cc057e6")  # the readouts' plan


def test_stamp_and_call_key():
    assert mp.BRMT_PROMPT_VERSION.endswith("+bank-v5")
    assert fam.call_pv("basic_readout_mt", mp.BRMT_PROMPT_VERSION).endswith("+bank-v4")
