"""basic_readout_mt drops the sarin item (the bank's only weapon-related item, whose digest was
refused on most layers). Bank v6 starts from bank v4 without it (its header keeps the record,
``v5``; that 98-item step shipped first as a bank of its own, which bank v6 replaces), and v4's
read plan (and every v4 readout file) serves v6."""

import json
from pathlib import Path

from wsbench import readplan, reads, registry
from wsbench.banks import label_of
from wsbench.multitoken import family as fam
from wsbench.multitoken import prompts as mp

REPO = Path(__file__).resolve().parents[1]
V4 = REPO / "evals/basic_readout_mt/items_v4.json"
V6 = REPO / "evals/basic_readout_mt/items_v6.json"
SARIN = "brh-ent-chem-sarin-systematic"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_v6_starts_from_v4_without_the_sarin_item():
    v4 = {it["name"]: it for it in _raw(V4)["items"]}
    v6 = _raw(V6)
    assert v6["supersedes"] == "items_v4.json" and v6["v5"]["removed"] == [SARIN] and SARIN in v4
    dropped = set(v6["r5_mc"]["dropped"])  # the option rebuild's own drops
    assert [it["name"] for it in v6["items"]] == [
        n for n in v4 if n != SARIN and label_of(n) not in dropped
    ]
    assert not (REPO / "evals/basic_readout_mt/items_v5.json").exists()


def test_v4_read_plan_serves_v6(real_families, monkeypatch):
    assert _raw(V6)["read_plan_bank"] == "items_v4.json"
    # bank v7 (2026-11-05, the capital item replaced) reads with its own plan; pin v6 here
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "BASIC_READOUT_MT", str(V6))
    assert registry.bank_path("basic_readout_mt") == V6
    assert len({s.id for s in readplan.plan("basic_readout_mt")}) == 99  # v4's rows
    assert reads.plan_sha("basic_readout_mt").startswith("4c8f2cc057e6")  # the readouts' plan


def test_stamp_and_call_key():
    assert mp.BRMT_PROMPT_VERSION.endswith("+bank-v7")  # bank v7 after v6
    assert fam.call_pv("basic_readout_mt", mp.BRMT_PROMPT_VERSION).endswith("+bank-v4")
