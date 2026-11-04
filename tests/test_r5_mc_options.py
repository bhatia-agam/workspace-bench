"""The r5-rebuilt MC option banks (scripts/mc_options_r5.py): each new bank is its predecessor with
the leaking content distractor lists rebuilt (``r5_mc.changed``) and the items that still leaked
dropped (``r5_mc.dropped``); registered and stamped, and the read plan of record is unchanged."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from wsbench import mc, reads, registry
from wsbench.banks import label_of, load_bank

REPO = Path(__file__).resolve().parents[1]
# family -> (the bank it supersedes, the new bank, its version)
BANKS = {
    "basic_readout_mt": ("items_v4.json", "items_v6.json", 6),
    "multihop_mt_v2": ("items_v4.json", "items_v6.json", 6),
    "multilingual": ("items_v3.json", "items_v4.json", 4),
    "multilingual_mt": ("items_v4.json", "items_v5.json", 5),
    "multilingual_multihop": ("items_v4.json", "items_v5.json", 5),
    "multilingual_typo": ("items_v3.json", "items_v4.json", 4),
}
# the plan_sha of each family's read plan before the rebuild: options are never rendered, and a
# dropped item's plan row stays (``read_plan_bank``), so every earlier readout file serves
PLAN_SHA = {
    "basic_readout_mt": "4c8f2cc057e6",
    "multihop_mt_v2": "1d5f2e2fa84b",
    "multilingual": "e9a67ff80bee",
    "multilingual_mt": "2510a7af7c96",
    "multilingual_multihop": "f57d844abf4e",
    "multilingual_typo": "e5abae63b4ab",
}


# the rebuild started from a small edit of the bank it supersedes that the series folded into the
# new bank instead of keeping a file of its own: the header key of the new bank recording the edit
# (scripts/mc_options_r5.py's ``start_bank`` re-applies it the same way)
FOLDED = {"basic_readout_mt": "v5", "multihop_mt_v2": "v5"}


def _raw(family: str, name: str) -> dict:
    return json.loads((REPO / "evals" / family / name).read_text(encoding="utf-8"))


def _driver():
    spec = importlib.util.spec_from_file_location(
        "mc_options_r5", REPO / "scripts/mc_options_r5.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_families(real_families):
    """Each family the driver rebuilds: its starting bank exists, the bank it freezes is the next
    version beside it, and once frozen that bank is the registered one."""
    r5 = _driver()
    assert sorted(r5.CFGS) == [
        "basic_readout_mt",
        "multihop_mt_v2",
        "multilingual",
        "multilingual_mt",
        "multilingual_multihop",
        "multilingual_typo",
    ]
    for name, cfg in r5.CFGS.items():
        start, new = REPO / cfg.bank, REPO / cfg.new
        assert cfg.name == name and name in real_families and start.is_file(), name
        assert new == start.with_name(f"items_v{cfg.version}.json"), name
        if new.is_file():
            assert real_families[name].bank == Path(cfg.new), name
            assert json.loads(new.read_text(encoding="utf-8"))["supersedes"] == start.name
    assert {n for n, c in r5.CFGS.items() if (REPO / c.new).is_file()} == set(BANKS)


def _start(family: str) -> dict:
    """The bank the rebuild started from: the superseded bank, with a folded edit re-applied
    (``removed`` items, ``removed_options`` of a role) and recorded in its header."""
    src, dst, _v = BANKS[family]
    old = _raw(family, src)
    key = FOLDED.get(family)
    if not key:
        return old
    rec = _raw(family, dst)[key]
    gone = set(rec.get("removed") or [])
    cut = rec.get("removed_options") or {}
    items = []
    for it in old["items"]:
        if it["name"] in gone:
            continue
        for role, opts in cut.get(it["name"], {}).items():
            blk = it["mc"][role]
            blk["distractors"] = [d for d in blk["distractors"] if d not in opts]
        items.append(it)
    head = {k: v for k, v in old.items() if k != "items"}
    if gone:
        head["read_plan_bank"] = head.get("read_plan_bank") or src
    return {**head, key: rec, "items": items}


@pytest.mark.parametrize("family", sorted(BANKS))
def test_only_the_recorded_lists_change(family):
    src, dst, version = BANKS[family]
    old, new = _start(family), _raw(family, dst)
    r5 = new["r5_mc"]
    assert new["version"] == version and new["supersedes"] == src
    assert r5["procedure"] == "mcleak-r5-2026-11-04"
    changed, dropped = r5["changed"], set(r5["dropped"])
    by = {label_of(it["name"]): it for it in old["items"]}
    assert dropped <= set(by) and not dropped & set(changed)
    assert [label_of(it["name"]) for it in new["items"]] == [k for k in by if k not in dropped]
    if dropped:
        assert new["read_plan_bank"] == old.get("read_plan_bank", src)
    n = 0
    for it in new["items"]:
        iid = label_of(it["name"])
        o = by[iid]
        assert {k: v for k, v in it.items() if k != "mc"} == {
            k: v for k, v in o.items() if k != "mc"
        }
        assert set(it["mc"]) == set(o["mc"])
        for role, blk in it["mc"].items():
            ob = o["mc"][role]
            if role in changed.get(iid, {}):
                rec = changed[iid][role]
                assert rec["from"] == ob["distractors"] and rec["to"] == blk["distractors"]
                assert blk["distractors"] != ob["distractors"] and blk["gold"] == ob["gold"]
                assert {k for k in blk if k != "pool"} == {k for k in ob if k != "pool"}
                n += 1
            else:
                assert blk == ob, (iid, role)
    assert n == sum(len(v) for v in changed.values()) > 0


@pytest.mark.parametrize("family", sorted(BANKS))
def test_rebuilt_lists_are_well_formed(family):
    """Four distinct distractors; never a form of the gold or of another unit of the item, the
    answer or a prompt word."""
    _src, dst, _v = BANKS[family]
    raw = _raw(family, dst)
    _h, items = load_bank(REPO / "evals" / family / dst)
    for it in items:
        for role in raw["r5_mc"]["changed"].get(it["id"], {}):
            blk = it["mc"][role]
            ds = [str(d) for d in blk["distractors"]]
            assert len(ds) == 4 and len({mc.fold(d) for d in ds}) == 4, (it["id"], role)
            names = [str(blk["gold"]), str(it.get("target") or "")]
            for u in it["units"]:
                if u["role"] != "language":
                    names += [str(f) for fs in (u.get("forms") or {}).values() for f in fs]
            for fs in ((it.get("name_forms") or {}).get(role) or {}).values():
                names += [str(f) for f in fs]
            for d in ds:
                assert not any(mc.fold(d).strip() == mc.fold(x).strip() for x in names), (
                    it["id"],
                    d,
                )
                pat = r"(?<!\w)" + re.escape(mc.fold(d)) + r"(?!\w)"
                assert not re.search(pat, mc.fold(str(it["prompt"]))), (it["id"], d)


@pytest.mark.parametrize("family", sorted(BANKS))
def test_registered_and_read_plan_unchanged(family, real_families):
    _src, dst, version = BANKS[family]
    assert real_families[family].bank == Path("evals") / family / dst
    assert registry.frozen_bank_path(family) == REPO / "evals" / family / dst
    assert f"+bank-v{version}" in real_families[family].judge.prompt_version
    assert reads.plan_sha(family).startswith(PLAN_SHA[family])


# the rebuild's own record (the header's r5_mc.floors, every measurement up to the freeze):
# multilingual_multihop's topic guesser stayed above the standard on the kept items whatever was
# dropped; multihop_mt_v2 met it on the kept items' repair-round draws, but its topic guesser
# fails it on fresh draws over the frozen bank (evals/baselines/README.md, "Option rebuild r5")
NOT_MET = {"multilingual_multihop"}


@pytest.mark.parametrize("family", sorted(BANKS))
def test_recorded_floors_and_standard(family):
    """The bank's own record of its last measurement (the frozen floors are measured on fresh
    draws in evals/baselines/lucky_guessing.json): fresh draws over the bank where measured, else
    the kept items' rates in the last round's draws; every guesser <= chance + 5 points. The
    header's standard_met is that verdict unless the frozen floors fail."""
    r5 = _raw(family, BANKS[family][1])["r5_mc"]
    fl = r5["floors"]
    base = fl.get("kept_estimate") or fl[max(k for k in fl if k.startswith("round"))]
    last = {v: (fl.get("fresh") or {}).get(v, base[v]) for v in ("blind", "described", "topic")}
    met = all(x <= base.get("chance", fl["chance"]) + 0.05 + 1e-9 for x in last.values())
    assert met is (family not in NOT_MET), (family, last)
    # the header's verdict also follows the frozen floors (fresh draws over the whole bank): a bank
    # its own record passes but those floors fail says standard_met false, with a note
    assert r5["standard_met"] is (met and not FROZEN_FAILS[family]), family
    assert ("standard_met_note" in r5) is (met and bool(FROZEN_FAILS[family])), family


# the frozen floors (evals/baselines/lucky_guessing.json), every guesser measured on the new bank:
# the standard verdicts on record
FROZEN_FAILS: dict[str, set[str]] = {
    "basic_readout_mt": set(),
    "multihop_mt_v2": {"topic"},
    "multilingual": set(),
    "multilingual_mt": set(),
    "multilingual_multihop": {"described", "topic"},
    "multilingual_typo": set(),
}


@pytest.mark.parametrize("family", sorted(BANKS))
def test_frozen_floors_are_on_the_new_bank(family, real_families):
    from wsbench.baselines import lucky_guessing as lg

    entry = json.loads((REPO / "evals/baselines/lucky_guessing.json").read_text("utf-8"))[family]
    n = len(load_bank(REPO / "evals" / family / BANKS[family][1])[1])
    current = lg.instrument_versions()[family]
    for v in ("blind", "described", "topic", "uniform"):
        assert entry[v]["instrument"] == current and entry[v]["n_items"] == n, (family, v)
    chance = entry["uniform"]["analytic_floor"]
    assert set(lg.leakage_failures(entry, chance, family)) == FROZEN_FAILS[family]


def test_call_keys_survive_the_bank_stamps(real_families):
    """A bank stamp moves the result stamp only: the MC calls stay keyed as before (the options
    are in the fingerprinted prompt, so a rebuilt list is re-asked and every other one is not)."""
    from wsbench.evals.multihop_mt_v2.prompts import MH2_CALL_VERSION, MH2_PROMPT_VERSION
    from wsbench.multitoken import mcrx
    from wsbench.multitoken.family import call_pv
    from wsbench.multitoken.prompts import BRMT_CALL_VERSION, BRMT_PROMPT_VERSION

    assert call_pv("basic_readout_mt", BRMT_PROMPT_VERSION) == BRMT_CALL_VERSION
    assert call_pv("multihop_mt_v2", MH2_PROMPT_VERSION) == MH2_CALL_VERSION
    for family in ("multilingual", "multilingual_multihop"):
        pv = real_families[family].judge.prompt_version
        assert "+bank-v" in pv and "+bank-v" not in mcrx.call_version(pv)
        assert mcrx.call_version(pv) == mcrx.call_version(pv.split("+bank-v")[0])


def test_multilingual_alias_note_is_the_new_bank_table():
    from wsbench.multitoken.options import alias_note, option_aliases
    from wsbench.multitoken.prompts import ML_ALIAS_NOTE

    _h, items = load_bank(REPO / "evals/multilingual/items_v4.json")
    assert alias_note(option_aliases(items)) == ML_ALIAS_NOTE
