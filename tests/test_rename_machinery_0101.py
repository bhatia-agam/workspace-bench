"""Plan 0101: the registry's pair machinery on the four renamed pairs (``<bare>`` = the
multi-token family since 2026-11-20, ``<bare>_st`` = the single-token one that held the key
before): names, stamps, evidence, bank lookup under a root, pins, out dirs, resumed files."""

import importlib.util
import json

import pytest

from wsbench import registry, split
from wsbench.readouts import refuse_partner_file
from wsbench.registry import RenamedKey

BARE = ("basic_readout", "multihop", "multilingual", "typo")
# bare key -> (an item id of the multi-token family, one of the single-token family)
IDS = {
    "basic_readout": ("brh-ent-aghlabid-dynasty", "br-ent-ath-ali"),
    "multihop": ("mh2-henry-james-pragmatism", "atomic-26-symbol"),
    "multilingual": ("mlh-ar-hourglass", "de-half-six"),
    "typo": ("tyh-novel-interpretability-hand", "typo-February"),
}
# bare key -> (a registered stamp of the multi-token family, one of the single-token family)
STAMPS = {
    "basic_readout": ("mc-brmt-2026-10-31r+norival-v1+qline-v2+bank-v7", "br-mc-2026-11-01-v5b"),
    "multihop": ("mh2-mc-2026-11-01+norival-v1+qline-v2+bank-v6", "bank-mc-2026-11-01-v3"),
    "multilingual": ("mt-regex-2026-10-30+v2+ln-2026-11-03a", "mcrx-2026-11-03e+mc-ml-2026-11-01b"),
    "typo": ("mt-regex-2026-10-30+typo-v2", "bank-2026-10-30b"),
}
HEADERS = {
    "basic_readout": ("basic-readout-hard", "basic-readout"),
    "multihop": ("multihop-hard", "multihop"),
    "multilingual": ("multilingual-hard", "multilingual"),
    "typo": ("typo-hard", "typo"),
}
pairs = pytest.mark.parametrize("bare", BARE)


@pytest.fixture(autouse=True)
def _real(real_families):
    registry._family_ids.cache_clear()
    yield
    registry._family_ids.cache_clear()


def test_the_probe_ids_are_real_and_the_pairs_share_none(real_families):
    for bare in BARE:
        live, other = registry.family_ids(bare), registry.family_ids(f"{bare}_st")
        assert IDS[bare][0] in live and IDS[bare][1] in other and not live & other, bare


def test_tables():
    assert registry.PRE_0101_KEYS == {
        "basic_readout": "basic_readout_st",
        "basic_readout_mt": "basic_readout",
        "multihop": "multihop_st",
        "multihop_mt": "multihop",
        "multihop_mt_v2": "multihop",
        "multilingual": "multilingual_st",
        "multilingual_mt": "multilingual",
        "typo": "typo_st",
        "typo_mt": "typo",
    }
    assert set(registry.REUSED_FAMILY_KEYS) == {"multihop_mt", *BARE}
    for bare in BARE:
        r = registry.REUSED_FAMILY_KEYS[bare]
        assert (r.live, r.other) == (bare, f"{bare}_st")
        assert (r.live_header, r.other_header) == HEADERS[bare]
        assert registry.frozen_name(bare) == f"{bare}_mt"
        assert registry.frozen_name(f"{bare}_st") == registry.hash_name(f"{bare}_st") == bare
    # hash_name and frozen_name differ for ONE family (plan 0101 §2.1)
    differ = [
        f for f in registry.FROZEN_KEY_NAMES if registry.frozen_name(f) != registry.hash_name(f)
    ]
    assert differ == ["multihop"]
    assert (registry.hash_name("multihop"), registry.frozen_name("multihop")) == (
        "multihop_mt_v2",
        "multihop_mt",
    )
    assert registry.frozen_name("poetry") == registry.hash_name("poetry") == "poetry"
    # a hash name is applied once, to a CURRENT key: it is not idempotent across a pair
    assert registry.hash_name(registry.hash_name("multihop_st")) == "multihop_mt_v2"


def test_frozen_name_is_what_the_raw_key_sites_embed():
    # the dev split of the families is the one their pre-0101 keys gave
    from wsbench.mc import seed_int

    for family, old in registry.FROZEN_KEY_NAMES.items():
        for i in range(50):
            want = seed_int(f"{old}:{i}") % 1000 < split.DEV_SHARE * 1000
            assert split.is_dev(family, str(i)) == want, family


def test_rekey_pre_0101():
    got = registry.rekey_pre_0101({"multihop": 1, "multihop_mt": 2, "poetry": 3})
    assert got == {"multihop_st": 1, "multihop": 2, "poetry": 3}
    assert list(registry.rekey_pre_0101({"poetry": 0, "typo_mt": 2})) == ["poetry", "typo"]
    assert registry.from_pre_0101("typo") == "typo_st"
    assert registry.from_pre_0101("wrong_bridge") == "wrong_intermediate"
    with pytest.raises(ValueError, match="two keys"):
        registry.rekey_pre_0101({"multihop_mt": 1, "multihop_mt_v2": 2})


@pairs
def test_pair_names(bare):
    st = f"{bare}_st"
    assert registry.partner(bare) == st and registry.partner(st) == bare
    assert registry.shared_key(bare) == registry.shared_key(st) == bare
    assert registry.lookup_names(st) == [st, bare]
    assert registry.lookup_names(bare)[0] == bare and f"{bare}_mt" in registry.lookup_names(bare)
    assert registry.bank_pins(st) == [
        f"WSB_BANK_FILE_{st.upper()}",
        f"WSB_BANK_FILE_{bare.upper()}",
    ]
    assert registry.partner("poetry") is None and registry.shared_key("multihop_mt") is None


@pairs
def test_stored_family_by_stamp(bare):
    live, other = STAMPS[bare]
    st = f"{bare}_st"
    for suffix in ("", "+digest-v5-task-extractive+sj-v10", "+reads-lite", "+fast-last_n"):
        assert registry.stored_family(bare, live + suffix) == bare
        assert registry.stored_family(bare, other + suffix) == st
    assert registry.stored_family(bare, "") == bare and registry.stored_family(bare, None) == bare
    with pytest.raises(RenamedKey):
        registry.stored_family(bare, "unknown-stamp")
    assert registry.stored_family(f"{bare}_mt", live) == bare  # the old `_mt` key: one family
    assert registry.stored_family(st, other) == st
    # each registered holder's current stamp classifies as itself
    for family in (bare, st):
        pv = registry.FAMILIES[family].judge.prompt_version
        assert registry.stored_family(bare, pv) == family


def test_ambiguous_and_retained_stamps():
    # the multilingual pair: both members can write the unpinned opts=judge=mc diagnostic
    for stamp in ("mc-ml-2026-11-01b", "mc-2026-10-30"):
        with pytest.raises(RenamedKey):
            registry.stored_family("multilingual", stamp)
    # the single-token multilingual family's regex diagnostic beats the shorter live prefix
    assert registry.stored_family("multilingual", "mt-regex-2026-10-30+leg-regex") == (
        "multilingual_st"
    )
    # the 2026-11-04 key keeps its rule: every non-live stamp, empty included, is the removed one
    assert registry.stored_family("multihop_mt", "mh2-mc-2026-11-01") == "multihop"
    assert registry.stored_family("multihop_mt", "") == "multihop_mt_regex"
    assert registry.stored_family("multihop_mt", "mc-2026-09-16") == "multihop_mt_regex"
    assert registry.stored_family("multihop_mt_v2", "mc-2026-09-16") == "multihop"
    assert registry.stored_family("wrong_bridge", "x") == "wrong_intermediate"


@pairs
def test_owner_by_each_kind_of_evidence(bare):
    st = f"{bare}_st"
    live_id, other_id = IDS[bare]
    assert registry.owner(bare) is None and registry.owner("poetry", ids=["x"]) is None
    assert registry.owner(bare, ids=[live_id]) == bare
    assert registry.owner(bare, ids=[other_id]) == st
    assert registry.owner(bare, ids=["in-neither-bank"]) is None
    assert registry.owner(bare, header=HEADERS[bare][1]) == st
    assert registry.owner(bare, header=HEADERS[bare][0]) == bare
    assert registry.owner(bare, stamp=STAMPS[bare][1]) == st
    assert registry.owner(bare, plan_sha=("b", "a", "b")) == st
    assert registry.owner(bare, plan_sha=("c", "a", "b")) is None
    with pytest.raises(RenamedKey):
        registry.owner(bare, ids=[live_id, other_id])
    with pytest.raises(RenamedKey):
        registry.owner(bare, ids=[live_id], header=HEADERS[bare][1])
    with pytest.raises(RenamedKey):
        registry.owner(bare, stamp="unknown-stamp")


def test_attribute_rows():
    rows = [
        {"family": "multihop", "id": IDS["multihop"][1]},  # a pre-0101 row of the single-token one
        {"family": "multihop", "id": IDS["multihop"][0]},
        {"family": "multihop_mt", "id": "x"},
        {"family": "wrong_bridge", "id": "x"},
    ]
    assert [r["family"] for r in registry.attribute_rows(rows)] == [
        "multihop_st",
        "multihop",
        "multihop",
        "wrong_intermediate",
    ]
    kept = registry.attribute_rows(
        [{"family": "wrong_bridge", "id": "x"}, {"family": "typo_mt", "id": "x"}],
        canonicalize=False,
    )
    assert [r["family"] for r in kept] == ["wrong_bridge", "typo"]
    with pytest.raises(RenamedKey):
        registry.attribute_rows([{"family": "typo", "id": "in-neither-bank"}])


def _bank(path, header):
    path.write_text(json.dumps({"family": header, "items": []}), encoding="utf-8")
    return path


@pairs
def test_root_bank_and_bank_path_by_header(bare, tmp_path, monkeypatch):
    st = f"{bare}_st"
    live_header, other_header = HEADERS[bare]
    old = _bank(tmp_path / f"{bare}.json", other_header)  # a pre-0101 set: the bare key
    assert registry.root_bank(tmp_path, st) == old
    assert registry.root_bank(tmp_path, bare) is None
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert registry.bank_path(st) == old
    with pytest.raises(SystemExit, match=rf"has no bank for '{bare}'.*is the bank of '{st}'"):
        registry.bank_path(bare)
    mt = _bank(tmp_path / f"{bare}_mt.json", live_header)  # ... with its multi-token bank
    assert registry.bank_path(bare) == mt
    # a migrated set
    new = _bank(tmp_path / f"{st}.json", other_header)
    _bank(old, live_header)
    assert registry.root_bank(tmp_path, st) == new and registry.root_bank(tmp_path, bare) == old


def test_a_bare_key_pin_needs_a_positive_header(tmp_path, monkeypatch):
    theirs = _bank(tmp_path / "theirs.json", "multihop")
    mine = _bank(tmp_path / "mine.json", "multihop-hard")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(theirs))
    with pytest.raises(RenamedKey):
        registry.bank_path("multihop")
    with pytest.raises(RenamedKey, match="WSB_BANK_FILE_MULTIHOP_ST"):
        registry.bank_path("multihop_st")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(mine))
    assert registry.bank_path("multihop") == mine
    (tmp_path / "list.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(tmp_path / "list.json"))
    for family in ("multihop", "multihop_st"):  # a header-less file under a bare variable
        with pytest.raises(RenamedKey):
            registry.bank_path(family)
    monkeypatch.delenv("WSB_BANK_FILE_MULTIHOP")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP_ST", str(mine))  # unambiguous name, partner's file
    with pytest.raises(RenamedKey):
        registry.bank_path("multihop_st")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP_ST", str(theirs))
    assert registry.bank_path("multihop_st") == theirs
    monkeypatch.delenv("WSB_BANK_FILE_MULTIHOP_ST")
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP_MT", str(mine))  # a former key of the live family
    assert registry.bank_path("multihop") == mine


def _results(d, family, stamp):
    d.mkdir(parents=True)
    doc = {"family": family, "config": {"prompt_version": stamp}}
    (d / "results.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


@pairs
def test_family_dir_is_content_checked_under_the_bare_key(bare, tmp_path):
    st = f"{bare}_st"
    live, other = STAMPS[bare]
    # a pre-0101 out root: `<bare>/` single-token, `<bare>_mt/` multi-token
    old = _results(tmp_path / "a" / bare, bare, other)
    old_mt = _results(tmp_path / "a" / f"{bare}_mt", f"{bare}_mt", live)
    assert registry.dir_owner(old) == st
    assert registry.family_dir(tmp_path / "a", st) == old
    assert registry.family_dir(tmp_path / "a", bare) == old_mt
    # the partner's directory under the family's own key, and no other candidate
    lone = _results(tmp_path / "e" / bare, bare, other)
    with pytest.raises(RenamedKey, match=f"holds results of '{st}'"):
        registry.family_dir(tmp_path / "e", bare)
    assert registry.family_dir(tmp_path / "e", st) == lone
    mine = _results(tmp_path / "b" / bare, bare, live)
    assert registry.family_dir(tmp_path / "b", bare) == mine
    assert registry.family_dir(tmp_path / "b", st) == tmp_path / "b" / st
    cells = tmp_path / "c" / bare  # no results.json: by the cache rows' item ids
    cells.mkdir(parents=True)
    oid = IDS[bare][1]
    rows = [{"key": f"digest:{oid}|20", "fp": "x"}, {"key": f"{oid}|L20", "fp": "y"}]
    (cells / "cells.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    assert registry.dir_owner(cells) == st and registry.family_dir(tmp_path / "c", st) == cells
    store = tmp_path / "s" / bare  # a digest store directory: L*.jsonl
    store.mkdir(parents=True)
    (store / "L20.jsonl").write_text(json.dumps(rows[0]) + "\n", "utf-8")
    assert registry.family_dir(tmp_path / "s", st) == store
    with pytest.raises(RenamedKey):
        registry.family_dir(tmp_path / "s", bare)
    empty = tmp_path / "d" / bare
    empty.mkdir(parents=True)
    assert registry.family_dir(tmp_path / "d", bare) == empty  # unidentified, under its own key


@pairs
def test_a_partner_readouts_file_is_never_resumed(bare, tmp_path):
    st = f"{bare}_st"
    path = tmp_path / f"{bare}.jsonl"
    path.write_text(json.dumps({"id": IDS[bare][1], "layer": 1, "pos": 0}) + "\n", encoding="utf-8")
    with pytest.raises(RenamedKey, match=f"holds '{st}' readouts"):
        refuse_partner_file(path, bare)
    refuse_partner_file(path, st)
    refuse_partner_file(tmp_path / "absent.jsonl", bare)
    refuse_partner_file(path, "moral_rationale")  # a family outside any pair: no check


# ---------------------------------------------------------------- plan 0106: the ledger rule


def _declare_mod():
    spec = importlib.util.spec_from_file_location(
        "manifest_0101_declare", registry.REPO_ROOT / "scripts/manifest_0101_declare.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest(families: dict[str, dict[str, str]]) -> dict:
    """A synthetic manifest: family -> its ``plan.fast_plan_sha`` rows."""

    def fam(name: str, fast: dict[str, str]) -> dict:
        return {
            "files": {"bank_file": "items.json", "bank_sha256": f"sha-{name}"},
            "plan": {"plan_sha": f"plan-{name}", "fast_plan_sha": dict(fast)},
            "stamps": {"prompt_version": f"{name}-v1", "prompts_sha256": f"p-{name}"},
            "run": {"native": {"judge_calls": ["a", "b"]}},
        }

    return {
        "script_sha256": "s",
        "shared": {"digest_prompt_version": "digest-v5", "n_families": len(families)},
        "families": {name: fam(name, fast) for name, fast in families.items()},
    }


def test_a_later_fast_cut_does_not_stale_a_new_familys_ledger_entry():
    """Plan 0106 §7.4: a family the golden does not have keeps its ``plan.fast_plan_sha`` rows
    outside its ledger entry (``without_fast``), so a fast version cut after its declaration
    neither fails T1 nor can be re-declared; a golden family still follows ``new_fast_rows``."""
    dec = _declare_mod()
    old = {"fam_a": {"fast-v4": "A"}, "fam_b": {"fast-v4": "B"}}
    gold = _manifest(old)
    cur = _manifest({**old, "fam_c": {"fast-v5": "C5"}})
    assert "a new family needs one too" in dec.verdict(gold, cur, {})[1][0]
    led = {"fam_c": dec.declare(gold, cur, {}, "fam_c", "0106", "new family")}
    declared, failures = dec.verdict(gold, cur, led)
    assert list(declared) == ["fam_c"] and declared["fam_c"].startswith("new family")
    assert not failures
    # the entry hashes the family's rows without its fast rows, and nothing else is left out
    bare = json.loads(json.dumps(cur["families"]["fam_c"]))
    del bare["plan"]["fast_plan_sha"]
    assert led["fam_c"]["rows_sha256"] == dec.rows_sha256(bare)
    assert dec.without_fast(cur["families"]["fam_c"])["plan"] == {"plan_sha": "plan-fam_c"}
    assert dec.without_fast({"stamps": {}}) == {"stamps": {}}
    # a later fast version (and a moved row of an older one) for the NEW family: still passing,
    # and `declare` has nothing new to hash
    later = _manifest({**old, "fam_c": {"fast-v5": "C5", "fast-v6": "C6"}})
    assert dec.verdict(gold, later, led) == (declared, [])
    with pytest.raises(dec.Refused, match="already declared in this state"):
        dec.declare(gold, later, led, "fam_c", "0106", "again")
    # every other row of the new family is still guarded (its full plan among them)
    moved = json.loads(json.dumps(later))
    moved["families"]["fam_c"]["plan"]["plan_sha"] = "plan-moved"
    assert "changed again" in dec.verdict(gold, moved, led)[1][0]
    # the same added row on a GOLDEN family follows `new_fast_rows`: it fails unless it equals
    # the family's row under a golden version
    bad = _manifest({"fam_a": {"fast-v4": "A", "fast-v6": "X"}, "fam_b": old["fam_b"]})
    assert "its fast plan moved" in dec.verdict(gold, bad, {})[1][0]
    same = _manifest({"fam_a": {"fast-v4": "A", "fast-v6": "A"}, "fam_b": old["fam_b"]})
    assert dec.verdict(gold, same, {}) == ({}, [])


def test_the_ledger_rule_for_new_families_moves_no_existing_entry():
    """``without_fast`` is applied for ``g is None`` only: a declared GOLDEN family's entry is
    hashed exactly as before (its rows with the acceptable new fast rows set aside)."""
    dec = _declare_mod()
    gold = _manifest({"fam_a": {"fast-v4": "A"}, "fam_b": {"fast-v4": "B"}})
    cur = _manifest({"fam_a": {"fast-v4": "A", "fast-v5": "A"}, "fam_b": {"fast-v4": "B"}})
    cur["families"]["fam_a"]["stamps"] = {"prompt_version": "fam_a-v2", "prompts_sha256": "p2"}
    entry = dec.declare(gold, cur, {}, "fam_a", "9999", "test")
    kept = json.loads(json.dumps(cur["families"]["fam_a"]))
    del kept["plan"]["fast_plan_sha"]["fast-v5"]  # the acceptable new row, set aside as before
    assert entry["rows_sha256"] == dec.rows_sha256(kept)
    assert kept["plan"]["fast_plan_sha"] == {"fast-v4": "A"}  # the golden rows stay hashed
    assert dec.verdict(gold, cur, {"fam_a": entry})[1] == []
