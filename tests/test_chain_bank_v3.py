"""chain_intermediates bank v3 (plan 0110, 2026-11-23): bank v2's 54 items the vetting kept, byte
identical and in order, its 66 flawed items removed, 66 new gated chains built under the
construction rules of ``scripts/build_chain_v3.py``; its own 120-row read plan, stamped
``+bank-v3``. No API calls."""

import hashlib
import importlib.util
import itertools
import json
from collections import Counter
from pathlib import Path

import pytest

from wsbench import readplan, reads, registry
from wsbench.banks import load_bank
from wsbench.evals.computational.chain_intermediates import judge
from wsbench.evals.computational.chain_intermediates import options as mcopt
from wsbench.evals.computational.chain_intermediates import prompts as cp

REPO = Path(__file__).resolve().parents[1]
FAMILY = "chain_intermediates"
DIR = REPO / "evals/computational/chain_intermediates"
V1, V2, V3 = DIR / "items.json", DIR / "items_v2.json", DIR / "items_v3.json"
SHA = {  # the three files are frozen
    V1: "79c9ce395061e1214c2734237defcf86db2407b8245098d894fa9351c88c3f6f",
    V2: "ce39296efbf25c3b86663b3adc8609d85911e8d08642123226dd762e282666ed",
    V3: "3ae1c3f216198dbf5e314f494217ce2f3d07951243379a937d6774cecb55fa21",
}
# the plans the readouts are produced for
PLAN_SHA_V2 = "bf888e2f745fca37b04a879666cbf0559383849bedfd89a68f3d6668489f5c05"
PLAN_SHA_V3 = "5966480f7fbd5200b57369b1e1d922e6d444a17a28aaee0c98eec76701a5d426"
PIN = "WSB_BANK_FILE_CHAIN_INTERMEDIATES"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location(
        "build_chain_v3", REPO / "scripts/build_chain_v3.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _registered(monkeypatch, real_families):
    monkeypatch.delenv(PIN, raising=False)


def test_the_three_bank_files_are_frozen_and_v3_is_registered():
    for path, sha in SHA.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, path.name
    assert registry.FAMILIES[FAMILY].bank == Path(
        "evals/computational/chain_intermediates/items_v3.json"
    )
    assert registry.bank_path(FAMILY).name == "items_v3.json"


def test_v3_is_v2_minus_the_66_plus_66_new(build):
    v2, v3 = _raw(V2), _raw(V3)
    assert v3["version"] == 3 and v3["supersedes"] == "items_v2.json" and v3["n"] == 120
    dropped = v3["selection"]["dropped_v2"]
    assert dropped == build.DROPPED and len(dropped) == 66
    assert Counter(dropped.values()) == {"not_required": 41, "chance_prone": 23, "duplicate": 2}
    kept = [it for it in v2["items"] if it["name"] not in dropped]
    assert len(v2["items"]) == 120 and len(kept) == 54
    assert v3["items"][:54] == kept  # equal and in v2's order (byte identity: build.check)
    new = v3["items"][54:]
    assert len(new) == 66 and all(it["name"].startswith("chain-v3-") for it in new)
    names = [it["name"] for it in v3["items"]]
    earlier = {it["name"] for b in (V1, V2) for it in _raw(b)["items"]}
    assert len(set(names)) == 120 and not {it["name"] for it in new} & earlier
    assert len({it["prompt"] for it in v3["items"]}) == 120
    # composition: the depth-3 share falls (few depth-3 candidates pass the gate and its probes)
    depth = lambda items: dict(sorted(Counter(it["depth"] for it in items).items()))  # noqa: E731
    assert depth(v2["items"]) == {2: 84, 3: 36}
    assert depth([it for it in v2["items"] if it["name"] in dropped]) == {2: 35, 3: 31}
    assert depth(kept) == {2: 49, 3: 5} and depth(new) == {2: 64, 3: 2}
    assert depth(v3["items"]) == {2: 113, 3: 7}
    assert dict(sorted(Counter(build.shape(it) for it in new).items())) == {
        "AH": 20, "AM": 20, "HA": 11, "MA": 13, "MAH": 1, "MAM": 1,
    }  # fmt: skip
    assert sum(len(it["mc"]) for it in v3["items"]) == 127


def test_no_item_of_v3_has_a_vetting_flaw_and_every_new_item_passes_the_rules(build):
    """The filter, re-run on the frozen bank: no scored intermediate between two add / subtract
    steps and no chance-prone gold anywhere; the new items also satisfy C1-C6 and carry their
    strict gate record. Bank v2 fails the same filter on 64 items (the other 2 of the 66 are
    duplicates), so the filter is not vacuous."""
    assert build.check() == ""
    v3 = _raw(V3)["items"]
    assert not [it["name"] for it in v3 if build.flaws(it)]
    for it in v3:  # stated here independently of the builder's helpers
        additive = [k in ("add", "sub") for k in it["kinds"]]
        assert not any(a and b for a, b in itertools.pairwise(additive)), it["name"]
        assert not {10, 12, 15, 25} & set(it["intermediates"]), it["name"]
    flawed_v2 = {it["name"] for it in _raw(V2)["items"] if build.flaws(it)}
    assert len(flawed_v2) == 64 and flawed_v2 <= set(build.DROPPED)
    new = v3[54:]
    assert not [it["name"] for it in new if build.violations(it)]
    for it in new:
        assert all(11 <= g <= 99 and g % 10 for g in it["intermediates"])
        assert 6 <= it["start"] <= 60 and it["gate"]["last"]["correct"] == 10
        assert it["gate"]["last"]["ok"] and it["gate"]["last"]["greedy_ok"]
    # C6: a new item shares its first computation with no item of the bank
    first = Counter((it["start"], it["intermediates"][0]) for it in v3)
    assert all(first[(it["start"], it["intermediates"][0])] == 1 for it in new)
    # the rules reject what they name
    bad = {**new[0], "kinds": ["add", "sub"], "steps": ["Add 5.", "Subtract 3."]}
    assert "C1:add-add" in build.violations(bad) and build.flaws(bad) == ["not_required"]
    assert build.flaws({**new[0], "intermediates": [25]}) == ["chance_prone"]


def test_mc_blocks(build):
    v2 = {it["name"]: it for it in _raw(V2)["items"]}
    v3 = _raw(V3)["items"]
    counts = [0] * mcopt.N_OPTIONS
    for it in v3:
        assert len(it["mc"]) == len(it["intermediates"])
        for s in it["mc"]:
            assert not mcopt.check_slot(it, s), it["name"]
            counts[mcopt.sorted_rank(s)] += 1
        if it["name"] in v2:  # a kept item's lists are bank v2's: its cached judge calls replay
            assert it["mc"] == v2[it["name"]]["mc"]
    assert sorted(counts) == [15, 16, 16, 16, 16, 16, 16, 16]  # the gold's sorted rank
    assert max(counts) <= mcopt.MAX_RANK_SHARE * sum(counts)


def test_v3_reads_its_own_plan(monkeypatch):
    rows = readplan.plan(FAMILY)
    assert [s.id for s in rows] == [it["id"] for it in load_bank(V3)[1]]
    assert reads.plan_sha(FAMILY) == PLAN_SHA_V3
    assert "plan_lineage" not in _raw(V3)  # drop + add is no drop-only step
    v3_rows = [s.row() for s in rows]
    monkeypatch.setenv(PIN, str(V2))
    assert reads.plan_sha(FAMILY) == PLAN_SHA_V2
    v2_rows = [s.row() for s in readplan.plan(FAMILY)]
    assert reads.lineage_step(v2_rows, v3_rows) is None
    old, new = {r["id"]: r for r in v2_rows}, {r["id"]: r for r in v3_rows}
    kept = [i for i in old if i in new]
    # the 54 kept rows equal bank v2's: their reads serve bank v3
    assert len(kept) == 54 and all(old[i] == new[i] for i in kept)
    assert len(new) - len(kept) == 66


def test_stamp_by_bank_version(monkeypatch):
    assert registry.FAMILIES[FAMILY].judge.prompt_version == cp.PROMPT_VERSION
    assert cp.PROMPT_VERSION == cp.INSTRUMENT_V2 + "+bank-v3"
    assert cp.INSTRUMENT_V2 == "chain-mc-2026-10-30+heads-v5+start-op+key-ex2"
    assert (
        judge.instrument(_raw(V3)) == cp.PROMPT_VERSION and judge.bank_tag(_raw(V3)) == "+bank-v3"
    )
    # bank v2, items.json and the adapted banks (header version <= 2): the stamp they always had
    for header in (_raw(V2), _raw(V1), {}, _raw(REPO / "adapted/glm-5.3/chain_intermediates.json")):
        assert judge.instrument(header) == cp.INSTRUMENT_V2 and judge.bank_tag(header) == ""
    assert judge.instrument() == cp.PROMPT_VERSION  # no header: the bank judged now
    monkeypatch.setenv(PIN, str(V2))
    assert judge.instrument() == cp.INSTRUMENT_V2
    # no call key and no ATI gate instrument moved
    assert cp.MC_CALL_VERSION == "chain-mc-2026-10-30"
    assert cp.NATIVE_PROMPT_VERSION == "chain-free-2026-10-30"


def test_a_judged_row_carries_the_tag_of_the_bank_it_judged(monkeypatch):
    """The live single-layer summary stamp (a call-free dry run), on the registered bank and on
    bank v2 through the pin: only the bank tag differs."""
    from wsbench.baselines import logit_lens

    v3 = logit_lens.live_config(FAMILY)["prompt_version"]
    assert v3.startswith(cp.PROMPT_VERSION + "+digest-") and "+bank-v3+digest-" in v3
    monkeypatch.setenv(PIN, str(V2))
    v2 = logit_lens.live_config(FAMILY)["prompt_version"]
    assert v2 == v3.replace("+bank-v3", "") and v2.startswith(cp.INSTRUMENT_V2 + "+digest-")


def test_prompt_only_freeze_accepts_the_judged_banks_stamp(monkeypatch):
    from wsbench.baselines import prompt_only as po

    assert po.summary_bases(FAMILY, cp.PROMPT_VERSION) == (cp.PROMPT_VERSION,)
    monkeypatch.setenv(PIN, str(V2))
    assert po.judged_bank_stamp(FAMILY) == cp.INSTRUMENT_V2
    assert po.summary_bases(FAMILY, cp.PROMPT_VERSION) == (cp.PROMPT_VERSION, cp.INSTRUMENT_V2)


def test_toy_file_reads_the_registered_bank():
    ids = {it["id"] for it in load_bank(V3)[1]}
    toy = REPO / "examples/readouts/chain_intermediates.jsonl"
    rows = [json.loads(x) for x in toy.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert {r["id"] for r in rows} <= ids and len({r["id"] for r in rows}) >= 2
