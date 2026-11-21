"""Plan 0101 (2026-11-20): the multi-token families took the plain keys, the single-token ones
became ``<key>_st``, and every family directory moved under its category. No instrument moved
(T1); everything written before the rename reads as the family it was written for, or is
refused (T2-T14); the name-embedding sites keep their pre-rename inputs (T16); no walk over the
family trees is vacuous."""

import ast
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import write_jsonl, write_sidecar

from wsbench import fast, llm, readplan, reads, registry, runner, split, tiers
from wsbench.adapt import store
from wsbench.baselines import lucky_guessing as lg
from wsbench.baselines import text_inversion as ti
from wsbench.cli import _family, main
from wsbench.registry import RenamedKey
from wsbench.results import FamilyResult, macro, read_results, write_results

REPO = registry.REPO_ROOT
BARE = ("basic_readout", "multihop", "multilingual", "typo")
EIGHT = [*BARE, *(f"{b}_st" for b in BARE)]
HEADERS = {
    "basic_readout": "basic-readout-hard",
    "basic_readout_st": "basic-readout",
    "multihop": "multihop-hard",
    "multihop_st": "multihop",
    "multilingual": "multilingual-hard",
    "multilingual_st": "multilingual",
    "typo": "typo-hard",
    "typo_st": "typo",
}
# a bank path as a report stored it before the move (the flat layout: no such file today)
OLD_BANK = "evals/" + "multihop/items_v5.json"
pairs = pytest.mark.parametrize("bare", BARE)


@pytest.fixture(autouse=True)
def _real(real_families):
    registry._family_ids.cache_clear()
    yield
    registry._family_ids.cache_clear()


def _example(family: str) -> Path:
    return REPO / "examples/readouts" / f"{family}.jsonl"


def _ids(family: str, n: int = 2) -> list[str]:
    return sorted(registry.registered_ids(family))[:n]


def _rows(family: str) -> list[dict]:
    return [{"id": i, "layer": 20, "pos": 0, "token": "x", "samples": ["s"]} for i in _ids(family)]


# ---------------------------------------------------------------- T1: no silent instrument move


def _declare_mod():
    spec = importlib.util.spec_from_file_location(
        "manifest_0101_declare", REPO / "scripts/manifest_0101_declare.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MANIFEST_SCRIPT_SHA256_OF_THE_GOLDEN = (
    "7cac34f978b31913e006c831c70d03b4da1c0f95a90905c700fa0ff49adf178a"
)
MANIFEST_SCRIPT_SHA256_NOW = "b970df0814eb57d5bff12b9e0c617b6f437e0ca9615b4dcc800730999b85ee4a"
MANIFEST_GOLDEN_SHA256 = "30aedc244eefe776a989f5f4d58d6e4d5d3aa7e01abc0571598c4a7b5689eefb"


def test_t1_no_instrument_moves_without_a_declared_stamp_or_bank_change(tmp_path):
    """``scripts/manifest_0101.py`` (its own process: it patches the LLM layer) rebuilds every
    hash, seed, option order, prompt sha, call key and fingerprint of every family, with family
    keys read through ``frozen_name``. The result is compared with the manifest made on main
    before the rename and with the ledger of declared changes
    (``tests/golden/manifest_0101_declared.json``) under ``manifest_0101_declare.verdict``.
    Neither the script nor the golden is ever regenerated (the golden embeds the script's sha)."""
    dec = _declare_mod()
    script, golden = REPO / "scripts/manifest_0101.py", REPO / "tests/golden/manifest_0101_pre.json"
    env = {"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path), "PYTHONPATH": str(REPO / "src")}
    now = tmp_path / "manifest_now.json"
    r = subprocess.run(
        [sys.executable, str(script), "--out", str(now), "--any-tree"],
        capture_output=True, text=True, env=env, cwd=REPO,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-4000:]
    doc = json.loads(golden.read_text(encoding="utf-8"))
    # Two pins. The golden names the script that MADE it; the script as it is now is that file
    # plus one `try` in `plan_entry` (2026-11-20: a family whose bank changed after an older
    # fast version was frozen made `fast.entry` exit the whole manifest; the row now reads
    # "unavailable", a constant, so no error wording is hashed). Any further edit of the script
    # moves the second pin on purpose.
    assert doc["script_sha256"] == MANIFEST_SCRIPT_SHA256_OF_THE_GOLDEN
    assert hashlib.sha256(script.read_bytes()).hexdigest() == MANIFEST_SCRIPT_SHA256_NOW
    assert hashlib.sha256(golden.read_bytes()).hexdigest() == MANIFEST_GOLDEN_SHA256
    current, ledger = json.loads(now.read_text(encoding="utf-8")), dec.load_ledger()
    declared, failures = dec.verdict(
        doc,
        current,
        ledger,
        script_sha256=MANIFEST_SCRIPT_SHA256_NOW,
        fast_as=dec.fast_equivalents(doc, current),
    )
    print(f"T1: {len(declared)} family(ies) declared an instrument change since plan 0101:")
    for fam, why in declared.items():
        print(f"  {fam}: {why}")
    assert not failures, "\n".join(failures)
    # the ledger holds nothing but live declarations: every entry is a family of this tree
    assert set(ledger) <= set(current["families"])


def _mini_manifest() -> dict:
    def fam(stamp: str, sha: str) -> dict:
        return {
            "files": {"bank_file": "items.json", "bank_sha256": sha},
            "plan": {"plan_sha": "plan-" + sha},
            "stamps": {"prompt_version": stamp, "prompts_sha256": "p-" + stamp},
            "run": {"native": {"judge_calls": ["a", "b"]}},
        }

    return {
        "script_sha256": "s",
        "shared": {"digest_prompt_version": "digest-v5", "n_families": 2},
        "families": {"fam_a": fam("a-v1", "sha-a"), "fam_b": fam("b-v1", "sha-b")},
    }


def _restamped() -> dict:
    """fam_a under a new stamp: its stamps and run rows moved, nothing else."""
    cur = _mini_manifest()
    cur["families"]["fam_a"]["stamps"] = {"prompt_version": "a-v2", "prompts_sha256": "p-a-v2"}
    cur["families"]["fam_a"]["run"]["native"]["judge_calls"] = ["x", "y", "z"]
    return cur


def test_t1_category_move_waives_one_row_of_one_family(monkeypatch):
    """Plan 0107: ONE family changing category (``CATEGORY_MOVES``: ``association``, ``basic``
    -> ``association``) moves one row, ``list.category``, and is declared under the golden's own
    stamp and bank. The waiver is that family's, that row's and that (old, new) pair's only."""
    from wsbench import registry

    dec = _declare_mod()
    assert dec.CATEGORY_MOVES == {"association": ("basic", "association")}
    assert {f: was for f, (was, _) in dec.CATEGORY_MOVES.items()} == (
        registry.LEGACY_FAMILY_CATEGORIES
    )
    for fam, (was, now) in dec.CATEGORY_MOVES.items():
        assert was != now and {was, now} <= set(registry.CATEGORIES)
        assert registry.category_of(fam) == now  # the manifest keys this family by its own key
        assert registry.frozen_name(fam) == fam
    # the real golden and ledger: the entry declares exactly that row
    golden = json.loads((REPO / "tests/golden/manifest_0101_pre.json").read_text("utf-8"))
    g = golden["families"]["association"]
    assert g["list"]["category"] == "basic"
    entry = dec.load_ledger()["association"]
    moved_rows = {**g, "list": {**g["list"], "category": "association"}}
    assert {k: entry[k] for k in dec.triple(g)} == dec.triple(g)  # no stamp or bank bump
    assert entry["rows_sha256"] == dec.rows_sha256(moved_rows) and entry["plan"] == "0107"
    assert dec.category_renamed(g, moved_rows, "association") == moved_rows
    assert dec.category_renamed(g, moved_rows, "poetry") is g
    assert dec.category_renamed(g, moved_rows) is g

    # synthetic manifests: fam_a is the listed family, fam_b another family of the same category
    monkeypatch.setattr(dec, "CATEGORY_MOVES", {"fam_a": ("basic", "association")})
    gold = _mini_manifest()
    for fam in gold["families"].values():
        fam["list"] = {"category": "basic", "metric": "pass_rate", "tier": "full"}

    def tree(family: str = "fam_a", category: str = "association") -> dict:
        cur = json.loads(json.dumps(gold))
        cur["families"][family]["list"]["category"] = category
        return cur

    cur = tree()
    declared, failures = dec.verdict(gold, cur, {})
    assert not declared and len(failures) == 1 and "no ledger entry" in failures[0]
    led = {"fam_a": dec.declare(gold, cur, {}, "fam_a", "0107", "test")}
    assert {k: led["fam_a"][k] for k in dec.triple(gold["families"]["fam_a"])} == dec.triple(
        gold["families"]["fam_a"]
    )
    declared, failures = dec.verdict(gold, cur, led)
    assert not failures and declared == {
        "fam_a": "category 'basic' -> 'association' (plan 0107: test)"
    }
    # another family making the same move, the listed family moving elsewhere or back to front,
    # and both families moving: refused, with or without a (forged) ledger entry
    both = tree()
    both["families"]["fam_b"]["list"]["category"] = "association"
    cases = [
        ("fam_b", tree("fam_b")),
        ("fam_a", tree("fam_a", "safety")),
        ("fam_b", both),
    ]
    back = json.loads(json.dumps(gold))
    back["families"]["fam_a"]["list"]["category"] = "association"
    cases.append(("fam_a", {**tree("fam_a", "basic"), "_gold": back}))  # association -> basic
    for fam, other in cases:
        base = other.pop("_gold", gold)
        rows = other["families"][fam]
        forged = {fam: {**dec.triple(rows), "rows_sha256": dec.rows_sha256(rows)}}
        for ledger in ({}, led, {**led, **forged}):
            declared, failures = dec.verdict(base, other, ledger)
            assert fam not in declared, (fam, ledger)
            assert any(
                f.startswith(f"{fam}: instrument moved without a stamp or bank change")
                for f in failures
            ), (fam, failures)
        with pytest.raises(dec.Refused, match="its stamp and bank are the golden's"):
            dec.declare(base, other, {}, fam, "0107", "test")
    # the move covers its one row: any other row moving with it fails, entry or not
    for sec, key in (
        ("plan", "plan_sha"),
        ("stamps", "prompts_sha256"),
        ("files", "bank_sha256x"),
        ("list", "metric"),
        ("list", "tier"),
        ("run", "native"),
    ):
        moved = tree()
        moved["families"]["fam_a"][sec][key] = "moved"
        rows = moved["families"]["fam_a"]
        forged = {"fam_a": {**dec.triple(rows), "rows_sha256": dec.rows_sha256(rows)}}
        for ledger in ({}, led, forged):
            declared, failures = dec.verdict(gold, moved, ledger)
            assert not declared and len(failures) == 1, (sec, key, ledger)
            assert "instrument moved without a stamp or bank change" in failures[0]
        with pytest.raises(dec.Refused, match="its stamp and bank are the golden's"):
            dec.declare(gold, moved, {}, "fam_a", "0107", "test")
    # a later stamp change of the moved family: the category row is set aside, no other is
    bumped = tree()
    bumped["families"]["fam_a"]["stamps"] = {"prompt_version": "a-v2", "prompts_sha256": "p2"}
    led2 = {"fam_a": dec.declare(gold, bumped, led, "fam_a", "9999", "test")}
    declared, failures = dec.verdict(gold, bumped, led2)
    assert not failures and "'a-v1' -> 'a-v2'; category 'basic'" in declared["fam_a"]
    bumped["families"]["fam_a"]["list"]["tier"] = "core"
    led3 = {"fam_a": dec.declare(gold, bumped, led, "fam_a", "9999", "test")}
    assert "declared by a stamp change only" in dec.verdict(gold, bumped, led3)[1][0]


def test_t1_category_rename_is_the_only_bumpless_declaration():
    """Plan 0105: a category rename listed in ``CATEGORY_RENAMES`` moves one row,
    ``list.category``, and is declared under the golden's own stamp and bank; every other row
    must still equal the golden's, and the rename must be the listed one."""
    from wsbench import registry

    dec = _declare_mod()
    assert dec.CATEGORY_RENAMES == registry.LEGACY_CATEGORIES == {"precision": "jlens_comparison"}
    assert set(dec.CATEGORY_RENAMES.values()) <= set(registry.CATEGORIES)
    assert not set(dec.CATEGORY_RENAMES) & set(registry.CATEGORIES)
    gold = _mini_manifest()
    for fam in gold["families"].values():
        fam["list"] = {"category": "precision", "metric": "precision"}

    def tree(category: str = "jlens_comparison") -> dict:
        cur = json.loads(json.dumps(gold))
        cur["families"]["fam_a"]["list"]["category"] = category
        return cur

    def entry(cur: dict) -> dict:
        return {"fam_a": dec.declare(gold, cur, {}, "fam_a", "0105", "test")}

    # the listed rename: fails without an entry, passes with one, and is named in T1's output
    cur = tree()
    declared, failures = dec.verdict(gold, cur, {})
    assert not declared and len(failures) == 1 and "no ledger entry" in failures[0]
    led = entry(cur)
    same = dec.triple(gold["families"]["fam_a"])  # the entry carries the golden's own triple
    assert {k: led["fam_a"][k] for k in same} == same
    declared, failures = dec.verdict(gold, cur, led)
    assert not failures and declared == {
        "fam_a": "category 'precision' -> 'jlens_comparison' (plan 0105: test)"
    }
    with pytest.raises(dec.Refused, match="already declared"):
        dec.declare(gold, cur, led, "fam_a", "0105", "test")
    # a rename that is not listed, or the metric row of the same spelling, is still refused
    for other in (tree("something_else"), tree("precision")):
        if other == gold:
            other["families"]["fam_a"]["list"]["metric"] = "jlens_comparison"
        declared, failures = dec.verdict(gold, other, led)
        assert not declared and len(failures) == 1
        assert failures[0].startswith("fam_a: instrument moved without a stamp or bank change")
        with pytest.raises(dec.Refused, match="its stamp and bank are the golden's"):
            dec.declare(gold, other, {}, "fam_a", "0105", "test")
    # the rename covers its one row: any other row moving with it fails, entry or not
    for sec, key in (("plan", "plan_sha"), ("stamps", "prompts_sha256"), ("list", "metric")):
        moved = tree()
        moved["families"]["fam_a"][sec][key] = "moved"
        rows = moved["families"]["fam_a"]
        forged = {"fam_a": {**dec.triple(rows), "rows_sha256": dec.rows_sha256(rows)}}
        for ledger in ({}, led, forged):
            declared, failures = dec.verdict(gold, moved, ledger)
            assert not declared and len(failures) == 1, (sec, ledger)
            assert "instrument moved without a stamp or bank change" in failures[0]
        with pytest.raises(dec.Refused, match="its stamp and bank are the golden's"):
            dec.declare(gold, moved, {}, "fam_a", "0105", "test")
    # a later stamp change of the renamed family: the category row is set aside, no other is
    bumped = tree()
    bumped["families"]["fam_a"]["stamps"] = {"prompt_version": "a-v2", "prompts_sha256": "p2"}
    led2 = {"fam_a": dec.declare(gold, bumped, led, "fam_a", "9999", "test")}
    declared, failures = dec.verdict(gold, bumped, led2)
    assert not failures and "'a-v1' -> 'a-v2'; category 'precision'" in declared["fam_a"]
    bumped["families"]["fam_a"]["plan"]["plan_sha"] = "other"
    led3 = {"fam_a": dec.declare(gold, bumped, led, "fam_a", "9999", "test")}
    assert "declared by a stamp change only" in dec.verdict(gold, bumped, led3)[1][0]


def test_t1_rule_on_synthetic_manifests():
    dec = _declare_mod()
    gold = _mini_manifest()
    assert dec.verdict(gold, _mini_manifest(), {}) == ({}, [])

    def entry(cur: dict, fam: str, ledger: dict | None = None) -> dict:
        return {fam: dec.declare(gold, cur, ledger or {}, fam, "9999", "test")}

    # a stamp change with a matching ledger entry passes; without one it fails and says what to do
    cur = _restamped()
    declared, failures = dec.verdict(gold, cur, {})
    assert not declared and len(failures) == 1
    assert "differs from the migration golden and from its declared state" in failures[0]
    assert "scripts/manifest_0101_declare.py fam_a" in failures[0]
    led = entry(cur, "fam_a")
    keys = {"prompt_version", "bank_file", "bank_sha256", "rows_sha256", "plan", "note"}
    assert set(led["fam_a"]) == keys
    declared, failures = dec.verdict(gold, cur, led)
    assert list(declared) == ["fam_a"] and "'a-v1' -> 'a-v2'" in declared["fam_a"] and not failures
    # (a) a stamp change with no other differing row is fine too (once declared)
    only = _mini_manifest()
    only["families"]["fam_a"]["stamps"]["prompt_version"] = "a-v2"
    assert dec.verdict(gold, only, entry(only, "fam_a"))[1] == []
    # a declared family whose rows change AGAIN with no further bump fails (the ledger hash)
    again = _restamped()
    again["families"]["fam_a"]["stamps"]["prompts_sha256"] = "edited-later"
    declared, failures = dec.verdict(gold, again, led)
    assert (
        not declared and len(failures) == 1 and "changed again after it was declared" in failures[0]
    )
    # ... and the tool refuses to re-declare it without a bump
    with pytest.raises(dec.Refused, match="bump the stamp or the bank version first"):
        dec.declare(gold, again, led, "fam_a", "9999", "test")
    with pytest.raises(dec.Refused, match="already declared"):
        dec.declare(gold, cur, led, "fam_a", "9999", "test")
    # a ledger entry for another stamp does not cover the tree's
    bumped = _restamped()
    bumped["families"]["fam_a"]["stamps"]["prompt_version"] = "a-v3"
    assert "ledger entry is for" in dec.verdict(gold, bumped, led)[1][0]
    assert dec.verdict(gold, bumped, entry(bumped, "fam_a", led))[1] == []
    # a stamp-only declaration waives `stamps` and `run`, nothing else: a moved plan_sha fails
    moved = _restamped()
    moved["families"]["fam_a"]["plan"]["plan_sha"] = "other"
    declared, failures = dec.verdict(gold, moved, entry(moved, "fam_a"))
    assert not declared and len(failures) == 1
    assert "declared by a stamp change only" in failures[0] and "/plan/plan_sha" in failures[0]
    # a declared bank change (new file or new sha) compares nothing against the golden
    for key, value in (("bank_file", "items_v2.json"), ("bank_sha256", "sha-b2")):
        cur = _mini_manifest()
        cur["families"]["fam_b"]["files"][key] = value
        cur["families"]["fam_b"]["plan"]["plan_sha"] = "new-plan"
        cur["families"]["fam_b"]["run"]["native"]["judge_calls"] = ["x"]
        declared, failures = dec.verdict(gold, cur, entry(cur, "fam_b"))
        assert list(declared) == ["fam_b"] and not failures
        was = entry(cur, "fam_b")
        cur["families"]["fam_b"]["plan"]["plan_sha"] = "moved-after"  # ... but the hash holds it
        assert "changed again" in dec.verdict(gold, cur, was)[1][0]
    # (b) rows differ while stamp and bank are unchanged: fails and says why, ledger or not,
    # and the tool refuses to declare it
    cur = _mini_manifest()
    cur["families"]["fam_b"]["stamps"]["prompts_sha256"] = "moved"
    rows_b = cur["families"]["fam_b"]
    forged = {"fam_b": {**dec.triple(rows_b), "rows_sha256": dec.rows_sha256(rows_b)}}
    for ledger in ({}, forged):
        declared, failures = dec.verdict(gold, cur, ledger)
        assert not declared and len(failures) == 1
        assert failures[0].startswith("fam_b: instrument moved without a stamp or bank change")
    with pytest.raises(dec.Refused, match="its stamp and bank are the golden's"):
        dec.declare(gold, cur, {}, "fam_b", "9999", "test")
    with pytest.raises(dec.Refused, match="nothing to declare"):
        dec.declare(gold, _mini_manifest(), {}, "fam_b", "9999", "test")
    # ... also beside another family's declared change
    both = _restamped()
    both["families"]["fam_b"]["stamps"]["prompts_sha256"] = "moved"
    declared, failures = dec.verdict(gold, both, entry(both, "fam_a"))
    assert list(declared) == ["fam_a"] and len(failures) == 1 and "fam_b" in failures[0]
    # a global section never moves, declared family or not
    cur = _restamped()
    cur["shared"]["digest_prompt_version"] = "digest-v6"
    assert dec.verdict(gold, cur, entry(cur, "fam_a"))[1] == [
        "global section moved: /shared/digest_prompt_version: 'digest-v5' != 'digest-v6'"
    ]
    cur = _mini_manifest()
    cur["script_sha256"] = "other"
    assert dec.verdict(gold, cur, {})[1] == ["global section moved: /script_sha256: 's' != 'other'"]
    # a family gone from the tree fails; a new one needs a ledger entry and counts in n_families
    cur = _mini_manifest()
    del cur["families"]["fam_b"]
    assert any("/families/fam_b" in f for f in dec.verdict(gold, cur, {})[1])
    cur = _mini_manifest()
    cur["families"]["fam_c"] = json.loads(json.dumps(cur["families"]["fam_a"]))
    cur["shared"]["n_families"] = 3
    declared, failures = dec.verdict(gold, cur, {})
    assert not declared and len(failures) == 1 and "a new family needs one too" in failures[0]
    led_c = entry(cur, "fam_c")
    declared, failures = dec.verdict(gold, cur, led_c)
    assert (
        list(declared) == ["fam_c"] and declared["fam_c"].startswith("new family") and not failures
    )
    cur["shared"]["n_families"] = 2
    assert dec.verdict(gold, cur, led_c)[1] == [
        "/shared/n_families: not the golden's count plus the new families"
    ]
    cur["shared"]["n_families"] = 3
    cur["families"]["fam_c"]["stamps"]["prompts_sha256"] = "edited"  # a new family is guarded too
    assert "changed again" in dec.verdict(gold, cur, led_c)[1][0]
    with pytest.raises(dec.Refused, match="bump"):
        dec.declare(gold, cur, led_c, "fam_c", "9999", "test")


def _with_fast(doc: dict, rows: dict[str, dict[str, str]]) -> dict:
    out = json.loads(json.dumps(doc))
    for fam, by_version in rows.items():
        out["families"][fam]["plan"]["fast_plan_sha"] = dict(by_version)
    return out


def test_t1_rule_for_fast_versions_cut_after_the_golden():
    """A new fast version's row for a family must be the family's row under a golden version
    (directly, or as recomputed under that version's name for a family whose rows hash the
    version); then it needs no declaration and stales none. Anything else fails, except for a
    family declared with a new bank."""
    dec = _declare_mod()
    gold = _with_fast(_mini_manifest(), {"fam_a": {"fast-v2": "A"}, "fam_b": {"fast-v2": "B"}})
    same = {"fam_a": {"fast-v2": "A", "fast-v3": "A"}, "fam_b": {"fast-v2": "B", "fast-v3": "B"}}
    assert dec.verdict(gold, _with_fast(_mini_manifest(), same), {}) == ({}, [])
    # a new version's row that is not the predecessor's: the fast plan moved
    moved = _with_fast(_mini_manifest(), {**same, "fam_b": {"fast-v2": "B", "fast-v3": "X"}})
    declared, failures = dec.verdict(gold, moved, {})
    assert not declared and len(failures) == 1
    assert "/families/fam_b/plan/fast_plan_sha/fast-v3" in failures[0]
    assert "its fast plan moved" in failures[0]
    # ... unless it is that row as the golden version would have declared it (rows that hash
    # the version string); the equivalence must give the GOLDEN row, not any value
    as_old = {"fam_b": {"fast-v3": {"row": "X", "as": {"fast-v2": "B"}}}}
    assert dec.verdict(gold, moved, {}, fast_as=as_old) == ({}, [])
    wrong = {"fam_b": {"fast-v3": {"row": "X", "as": {"fast-v2": "X"}}}}
    assert len(dec.verdict(gold, moved, {}, fast_as=wrong)[1]) == 1
    # ... and only for the very row it was computed for (a stale equivalence covers nothing)
    stale = {"fam_b": {"fast-v3": {"row": "another row", "as": {"fast-v2": "B"}}}}
    assert len(dec.verdict(gold, moved, {}, fast_as=stale)[1]) == 1
    # a GOLDEN version's row never moves that way, and a golden version may not vanish
    old_moved = _with_fast(_mini_manifest(), {**same, "fam_b": {"fast-v2": "X", "fast-v3": "X"}})
    assert dec.verdict(gold, old_moved, {})[1][0].startswith("/families/fam_b/plan/fast_plan_sha")
    gone = _with_fast(_mini_manifest(), {**same, "fam_b": {"fast-v3": "B"}})
    assert "moved without a stamp or bank change" in dec.verdict(gold, gone, {})[1][0]
    # a version the golden has for another family is not "new" for this one
    gold2 = _with_fast(_mini_manifest(), {"fam_a": {"fast-v2": "A", "fast-s1": "A"}, "fam_b": {}})
    joined = _with_fast(_mini_manifest(), {"fam_a": {"fast-v2": "A", "fast-s1": "A"},
                                            "fam_b": {"fast-s1": "B"}})  # fmt: skip
    assert "moved without a stamp or bank change" in dec.verdict(gold2, joined, {})[1][0]
    # a stamp-only declaration: its hash ignores acceptable new rows, so a later fast cut does
    # not stale it, and a moved new row still fails
    cur = _with_fast(_restamped(), {"fam_a": {"fast-v2": "A"}, "fam_b": {"fast-v2": "B"}})
    led = {"fam_a": dec.declare(gold, cur, {}, "fam_a", "9999", "test")}
    later = _with_fast(_restamped(), same)
    assert (
        list(dec.verdict(gold, later, led)[0]) == ["fam_a"] and not dec.verdict(gold, later, led)[1]
    )
    assert dec.declare(gold, later, {}, "fam_a", "9999", "test") == led["fam_a"]
    bad = _with_fast(_restamped(), {**same, "fam_a": {"fast-v2": "A", "fast-v3": "X"}})
    assert "its fast plan moved" in dec.verdict(gold, bad, led)[1][0]

    # a family declared with a NEW BANK: an old version's row may read "unavailable", a new
    # row equal to its golden row is set aside (a later cut stales nothing), and a new row that
    # is not its golden row is part of what the ledger hash holds
    def rebanked(rows: dict[str, str]) -> dict:
        cur = _with_fast(_mini_manifest(), {"fam_a": {"fast-v2": "A"}, "fam_b": rows})
        cur["families"]["fam_b"]["files"]["bank_file"] = "items_v2.json"
        return cur

    cur = rebanked({"fast-v2": "unavailable: bank changed", "fast-v3": "B"})
    led = {"fam_b": dec.declare(gold, cur, {}, "fam_b", "9999", "test")}
    assert list(dec.verdict(gold, cur, led)[0]) == ["fam_b"] and not dec.verdict(gold, cur, led)[1]
    later = rebanked({"fast-v2": "unavailable: bank changed", "fast-v3": "B", "fast-v4": "B"})
    assert not dec.verdict(gold, later, led)[1]
    other = rebanked({"fast-v2": "unavailable: bank changed", "fast-v3": "N"})
    assert "changed again" in dec.verdict(gold, other, led)[1][0]
    led_n = {"fam_b": dec.declare(gold, other, {}, "fam_b", "9999", "test")}
    assert not dec.verdict(gold, other, led_n)[1]
    # the script pin: with it, the manifest's own sha must be the pinned one
    cur = _mini_manifest()
    cur["script_sha256"] = "edited"
    plain = _mini_manifest()
    assert dec.verdict(plain, cur, {}, script_sha256="edited", fast_as={})[1] == []
    assert dec.verdict(plain, cur, {}, script_sha256="other")[1] == [
        "/script_sha256: 'edited' is not the pinned script's 'other'"
    ]


def test_t1_declare_command_refuses_without_a_bump(tmp_path, monkeypatch, capsys):
    """The CLI on a synthetic tree: writes an entry after a bump, exit 2 without one."""
    dec = _declare_mod()
    gold, cur = _mini_manifest(), _restamped()
    (tmp_path / "golden.json").write_text(json.dumps(gold), encoding="utf-8")
    monkeypatch.setattr(dec, "GOLDEN", tmp_path / "golden.json")
    monkeypatch.setattr(dec, "LEDGER", tmp_path / "declared.json")
    monkeypatch.setattr(dec, "REPO", tmp_path)
    monkeypatch.setattr(dec, "build_current", lambda: cur)
    args = ["fam_a", "--plan", "9999", "--note", "a new judge rule", "--write"]
    assert dec.main(args) == 0
    led = json.loads((tmp_path / "declared.json").read_text(encoding="utf-8"))
    assert led["fam_a"]["prompt_version"] == "a-v2" and led["fam_a"]["plan"] == "9999"
    assert dec.verdict(gold, cur, led)[1] == []
    cur["families"]["fam_a"]["stamps"]["prompts_sha256"] = "edited-later"
    assert (
        dec.main(args) == 2
        and "bump the stamp or the bank version first" in capsys.readouterr().err
    )
    assert json.loads((tmp_path / "declared.json").read_text(encoding="utf-8")) == led
    assert dec.main(["fam_b", "--plan", "9999", "--note", "x"]) == 2
    assert "nothing to declare" in capsys.readouterr().err


# ---------------------------------------------------------------- T2: stored results


def _stored(tmp_path: Path, key: str, pv: str) -> FamilyResult:
    d = tmp_path / key / hashlib.sha256(pv.encode()).hexdigest()[:8]
    r = FamilyResult(
        family=key, metric="pass_rate", value=0.5, ci95=None, n_items=2, higher_is_better=True,
        chance=None, chance_label=None, complete=True, pinned_instrument=True,
        config={"prompt_version": pv}, counts={},
    )  # fmt: skip
    write_results(d, r)
    return read_results(d)


@pairs
def test_t2_a_pre_0101_results_tree_reads_as_the_families_it_was_written_for(bare, tmp_path):
    st, mt = registry.FAMILIES[f"{bare}_st"], registry.FAMILIES[bare]
    # before 2026-11-20: `<bare>/` was the single-token family, `<bare>_mt/` the multi-token one
    old_st = _stored(tmp_path, bare, st.judge.prompt_version + "+digest-v5-task-extractive+sj-v10")
    old_mt = _stored(tmp_path, f"{bare}_mt", mt.judge.prompt_version)
    new_mt = _stored(tmp_path, bare, mt.judge.prompt_version + "+reads-lite")
    assert (old_st.family, old_mt.family, new_mt.family) == (st.name, bare, bare)
    with pytest.raises(RenamedKey):
        _stored(tmp_path, bare, "a-stamp-neither-family-wrote")


def test_t2_the_old_typo_row_is_superseded_and_the_old_typo_mt_row_is_in_the_macro(tmp_path):
    old_typo = _stored(tmp_path, "typo", registry.FAMILIES["typo_st"].judge.prompt_version)
    old_typo_mt = _stored(tmp_path, "typo_mt", registry.FAMILIES["typo"].judge.prompt_version)
    assert (old_typo.family, old_typo_mt.family) == ("typo_st", "typo")
    m = macro([old_typo, old_typo_mt])
    assert {"family": "typo_st", "reason": "superseded", "by": "typo"} in m["excluded"]
    assert [f["family"] if isinstance(f, dict) else f for f in m["families"]] == ["typo"]


def test_t2_an_ambiguous_stamp_is_settled_by_the_result_rows(tmp_path):
    # the multilingual pair's unpinned opts=judge=mc diagnostic: either member can stamp it
    for family in ("multilingual", "multilingual_st"):
        d = tmp_path / family
        rows = [{"id": i, "pass": True} for i in _ids(family)]
        r = FamilyResult(
            family="multilingual", metric="pass_rate", value=1.0, ci95=None, n_items=2,
            higher_is_better=True, chance=None, chance_label=None, complete=True,
            pinned_instrument=False, config={"prompt_version": "mc-2026-10-30"}, counts={},
            rows=rows,
        )  # fmt: skip
        write_results(d, r)
        assert read_results(d).family == family
        assert registry.dir_owner(d, "multilingual") == family


@pairs
def test_t2_an_empty_stamp_is_settled_by_the_result_rows(bare, tmp_path):
    """Review c5: a result under a bare key with no stamp is its rows' family (a copied old
    single-token result with the stamp blanked), and the live family only without rows."""
    st = f"{bare}_st"
    assert registry.stored_family(bare, "") == bare and registry.stored_family(bare, None) == bare
    assert registry.stored_family(bare, "", _ids(st)) == st
    assert registry.stored_family(bare, "", _ids(bare)) == bare
    assert registry.stored_family(bare, "", ["an-id-in-no-bank"]) == bare
    with pytest.raises(RenamedKey):
        registry.stored_family(bare, "", [*_ids(st), *_ids(bare)])
    for family in (st, bare):
        d = tmp_path / family
        r = FamilyResult(
            family=bare, metric="pass_rate", value=1.0, ci95=None, n_items=2,
            higher_is_better=True, chance=None, chance_label=None, complete=True,
            pinned_instrument=True, config={}, counts={},
            rows=[{"id": i, "pass": True} for i in _ids(family)],
        )  # fmt: skip
        write_results(d, r)
        assert read_results(d).family == family and registry.dir_owner(d, bare) == family


# ---------------------------------------------------------------- T3: readouts


@pairs
def test_t3_a_root_written_before_or_after_the_rename_serves_both_families(bare, tmp_path):
    st = f"{bare}_st"
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    write_jsonl(old / f"{bare}.jsonl", _rows(st))  # single-token under the bare key
    write_jsonl(old / f"{bare}_mt.jsonl", _rows(bare))
    assert runner.readouts_path(old, st) == old / f"{bare}.jsonl"
    assert runner.readouts_path(old, bare) == old / f"{bare}_mt.jsonl"
    write_jsonl(new / f"{bare}.jsonl", _rows(bare))
    write_jsonl(new / f"{st}.jsonl", _rows(st))
    assert runner.readouts_path(new, bare) == new / f"{bare}.jsonl"
    assert runner.readouts_path(new, st) == new / f"{st}.jsonl"
    # only the single-token family's pre-0101 file: the multi-token family has no readouts
    lone = tmp_path / "lone"
    lone.mkdir()
    write_jsonl(lone / f"{bare}.jsonl", _rows(st))
    assert runner.readouts_choice(lone, bare) == (None, lone / f"{bare}.jsonl")
    assert runner.readouts_path(lone, st) == lone / f"{bare}.jsonl"


@pairs
def test_t3_the_partners_file_is_refused_whatever_it_is_called(bare, tmp_path, mk_args, capsys):
    st = f"{bare}_st"

    def refused(path, family, **kw) -> str:
        with pytest.raises(SystemExit) as e:
            reads.load(mk_args(path, **kw), family)
        assert e.value.code == 2
        return capsys.readouterr().err

    by_ids = write_jsonl(tmp_path / "anything.jsonl", _rows(st))
    assert reads.owner_of(by_ids, bare) == st
    for allow in (False, True):
        err = refused(by_ids, bare, allow_missing=allow)
        assert f"holds {st} readouts" in err and f"family={st}" in err
    by_sha = write_jsonl(tmp_path / "sidecar.jsonl", _rows(st))
    write_sidecar(by_sha, plan_sha=reads.plan_sha(st), layers=[20])
    assert reads.owner_of(by_sha, bare) == st and reads.owner_of(by_sha, st) == st
    assert f"holds {st} readouts" in refused(by_sha, bare)
    mt = write_jsonl(tmp_path / "mt.jsonl", _rows(bare))
    assert f"holds {bare} readouts" in refused(mt, st)
    mixed = write_jsonl(tmp_path / "mixed.jsonl", [*_rows(st), *_rows(bare)])
    for family in (bare, st):
        assert "holds readouts of both" in refused(mixed, family)


@pairs
def test_t3_judge_refuses_the_partners_file_without_a_call(bare, tmp_path, monkeypatch, capsys):
    def no_call(*a, **k):
        raise AssertionError("a refused file must never reach a model")

    monkeypatch.setattr(llm, "stream_json", no_call)
    monkeypatch.setattr(llm, "preflight", lambda *a, **k: None)
    old = tmp_path / f"{bare}.jsonl"  # the single-token family's file under its pre-0101 name
    old.write_bytes(_example(f"{bare}_st").read_bytes())
    argv = ["judge", f"family={bare}", f"readouts={old}", f"out={tmp_path / 'o'}"]
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2
    assert f"holds {bare}_st readouts" in capsys.readouterr().err
    assert not (tmp_path / "o" / "cells.jsonl").exists()


# ---------------------------------------------------------------- T4 / T5: banks


def test_t4_a_pre_0101_set_resolves_both_members_by_header(monkeypatch):
    root = REPO / "tests/fixtures/adapted_v1"  # written before the rename, never migrated
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(root))
    assert registry.bank_path("multilingual") == root / "multilingual_mt.json"
    assert registry.bank_path("multilingual_st") == root / "multilingual.json"


@pairs
def test_t4_a_root_with_only_the_single_token_bank_has_no_multi_token_family(
    bare, tmp_path, monkeypatch
):
    st = f"{bare}_st"
    (tmp_path / f"{bare}.json").write_text(json.dumps({"family": HEADERS[st], "items": []}))
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert registry.bank_path(st) == tmp_path / f"{bare}.json"
    with pytest.raises(SystemExit, match=f"has no bank for '{bare}'.*is the bank of '{st}'"):
        registry.bank_path(bare)
    assert st in readplan.families() and bare not in readplan.families()
    # the partner's ids are still known under a root that lacks its bank (never an exit)
    assert registry.family_ids(bare) == registry._family_ids(bare, "")


def _sets() -> list[Path]:
    return sorted(p.parent for p in (REPO / "adapted").glob("*/report.json"))


def test_t4_t5_every_in_repo_set_is_migrated_and_its_pairs_share_no_id(monkeypatch):
    sets = _sets()
    assert len(sets) >= 17  # every set, the ones built after the rename included
    ids: dict[str, set[str]] = {f: set(registry._family_ids(f, "")) for f in EIGHT}
    for d in sets:
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        assert report["family_keys"] == "0101", d.name
        assert store.pre_0101_evidence(d.name, report) == ""
        assert (
            not [p.name for p in d.glob("*_mt.json")] and not (d / "multihop_mt_v2.json").exists()
        )
        monkeypatch.setenv(registry.BANK_ROOT_ENV, str(d))
        for family in EIGHT:
            bank = d / f"{family}.json"
            if not bank.exists():
                continue
            assert registry.bank_path(family) == bank, (d.name, family)
            doc = json.loads(bank.read_text(encoding="utf-8"))
            assert doc["family"] == HEADERS[family], (d.name, family)  # header vocabulary (F9)
            ids[family] |= registry._bank_file_ids(bank)
            entry = report["families"].get(family)
            assert entry is None or store.report_key(report["families"], family) == family
    for bare in BARE:  # T5: item ids identify the family of a file
        assert ids[bare] and ids[f"{bare}_st"] and not ids[bare] & ids[f"{bare}_st"], bare


# ---------------------------------------------------------------- T6: adapted sets


def test_t6_a_pre_0101_report_is_read_entry_by_entry():
    report = {  # the shape of a set before the migration (glm-5.3)
        "families": {
            "multihop": {"n_items": 80, "bank": OLD_BANK},
            "multihop_mt_v2": {"n_items": 41},
            "typo_mt": {"n_items": 85},
        },
        "drops": {
            "multihop": {_ids("multihop_st")[0]: "why"},
            "multihop_mt": {"mh2-alfred-athelstan-brunanburh-r3": "leaker"},
            "multihop_mt_regex": {"multihop-au-t1-w0c0-x": "removed family"},
        },
    }
    fams, drops = report["families"], report["drops"]
    assert store.report_key(fams, "multihop_st") == "multihop"
    assert store.report_key(fams, "multihop") == "multihop_mt_v2"
    assert store.report_key(fams, "typo") == "typo_mt"
    assert store.report_entry(fams, "typo_st") == {}
    assert store.report_key(drops, "multihop_st") == "multihop"
    assert store.report_key(drops, "multihop") == "multihop_mt"
    assert "multihop-au-t1-w0c0-x" not in store.report_entry(drops, "multihop")


@pairs
def test_t6_each_pair_is_found_in_a_report_of_either_vintage(bare):
    st, mt = f"{bare}_st", f"{bare}_mt"
    old = {bare: {_ids(st)[0]: "a drop"}, mt: {_ids(bare)[0]: "a drop"}}  # before the rename
    assert store.report_key(old, st) == bare and store.report_key(old, bare) == mt
    assert _ids(st)[0] in store.report_entry(old, st)
    assert _ids(bare)[0] in store.report_entry(old, bare)
    new = {bare: {_ids(bare)[0]: "a drop"}, st: {_ids(st)[0]: "a drop"}}  # migrated
    assert store.report_key(new, bare) == bare and store.report_key(new, st) == st
    lone = {bare: {_ids(st)[0]: "a drop"}}  # only the single-token family, pre-0101
    assert store.report_key(lone, st) == bare and store.report_entry(lone, bare) == {}


@pairs
def test_t6_nothing_writes_into_a_set_that_was_never_migrated(bare, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda m, root=None: tmp_path / m)
    st = f"{bare}_st"
    for name, write in (
        ("old-report", lambda d: (d / "report.json").write_text(
            json.dumps({"families": {bare: {}, f"{bare}_mt": {}}}))),
        ("old-file", lambda d: (d / f"{bare}_mt.json").write_text("{}")),
        ("old-header", lambda d: (d / f"{bare}.json").write_text(
            json.dumps({"family": HEADERS[st], "items": []}))),
    ):  # fmt: skip
        d = tmp_path / name
        d.mkdir()
        write(d)
        before = sorted((p.name, p.read_bytes()) for p in d.glob("*.json"))
        assert store.pre_0101_evidence(name)
        with pytest.raises(SystemExit, match=r"written before plan 0101.*migrate_0101\.py set"):
            store.update_report(name, lambda r: r.update(x=1))
        assert sorted((p.name, p.read_bytes()) for p in d.glob("*.json")) == before


@pairs
def test_t6_a_set_created_after_the_rename_is_marked(bare, tmp_path, monkeypatch):
    """Review c5 S1: ``update_report`` stamps the marker on a set with no pre-rename key, so
    ``migrate_0101.py set`` can never take its bare keys for the single-token families'."""
    monkeypatch.setattr(store, "model_dir", lambda m, root=None: tmp_path / m)
    d = tmp_path / "new"
    d.mkdir()
    (d / f"{bare}.json").write_text(json.dumps({"family": HEADERS[bare], "items": []}))
    report = store.update_report("new", lambda r: r.setdefault("families", {}).update({bare: {}}))
    assert (
        report["family_keys"]
        == "0101"
        == json.loads((d / "report.json").read_text())["family_keys"]
    )
    assert store.pre_0101_evidence("new") == ""
    assert store.update_report("new", lambda r: r.update(x=1))["x"] == 1  # and stays writable
    # a marked set is never read as pre-0101, whatever is put beside it later
    (d / f"{bare}_mt.json").write_text("{}")
    assert store.pre_0101_evidence("new") == ""


def test_t6_a_set_under_the_2026_11_04_former_key_is_written_but_not_marked(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda m, root=None: tmp_path / m)
    for name, by_file in (("v2-file", True), ("v2-report", False)):
        d = tmp_path / name
        d.mkdir()
        if by_file:
            (d / "multihop_mt_v2.json").write_text(
                json.dumps({"family": "multihop-hard", "items": []})
            )
        else:
            (d / "report.json").write_text(json.dumps({"drops": {"multihop_mt_v2": {}}}))
        report = store.update_report(name, lambda r: r.update(x=1))
        assert report["x"] == 1 and "family_keys" not in report


def test_t6_an_adapted_bank_keeps_the_registered_header_value():
    for family in EIGHT:  # the header is the source repo's vocabulary, never the key
        assert store.original_bank(family)[0]["family"] == HEADERS[family]


# ---------------------------------------------------------------- T8: the command line


def test_t8_former_keys_resolve_with_a_note(monkeypatch, capsys):
    monkeypatch.delenv(registry.NO_NOTICE_ENV)
    former = {k: v for k, v in registry.PRE_0101_KEYS.items() if k not in BARE}
    assert len(former) == 5
    for old, new in former.items():
        assert _family(old) == new
        assert capsys.readouterr().err.strip() == f"note: family {old!r} was renamed to {new!r}"


@pairs
def test_t8_a_bare_key_is_announced_once(bare, monkeypatch, capsys):
    monkeypatch.delenv(registry.NO_NOTICE_ENV)
    monkeypatch.setattr(registry, "_NOTICED", set())
    assert _family(bare) == bare
    assert capsys.readouterr().err.strip() == (
        f"note: '{bare}' is the multi-token family since 2026-11-20 (was {bare}_mt); the "
        f"single-token family is '{bare}_st'"
    )
    assert _family(bare) == bare and capsys.readouterr().err == ""  # once per key and process
    assert _family(f"{bare}_st") == f"{bare}_st" and capsys.readouterr().err == ""
    monkeypatch.setattr(registry, "_NOTICED", set())
    assert _family(bare, notice=False) == bare and capsys.readouterr().err == ""
    monkeypatch.setenv(registry.NO_NOTICE_ENV, "1")
    assert _family(bare) == bare and capsys.readouterr().err == ""


def test_t8_list_shows_the_new_keys_titles_categories_and_tiers(capsys):
    assert main(["list"]) == 0
    rows = {ln.split()[0]: ln for ln in capsys.readouterr().out.splitlines() if ln.strip()}
    assert set(rows) >= set(registry.FAMILIES) and len(registry.FAMILIES) == 32
    assert not {"basic_readout_mt", "multihop_mt", "multilingual_mt", "typo_mt"} & set(rows)
    for family in EIGHT:
        assert registry.FAMILIES[family].group == "basic" and " basic " in rows[family]
    assert "basic (superseded by typo)" in rows["typo_st"] and tiers.tier_of("typo_st") == ""
    assert tiers.tier_of("typo") == "full"
    titles = {f: registry.FAMILIES[f].title for f in EIGHT}
    assert titles == {
        "basic_readout": "Basic readout",
        "multihop": "Multihop",
        "multilingual": "Multilingual",
        "typo": "Typo",
        "basic_readout_st": "Basic readout (single-token)",
        "multihop_st": "Multihop (single-token)",
        "multilingual_st": "Multilingual (single-token)",
        "typo_st": "Typo (single-token)",
    }


# ---------------------------------------------------------------- T9: hash names stay opaque


def test_t9_the_frozen_tables_are_used_in_the_registry_only():
    for path in sorted((REPO / "src/wsbench").rglob("*.py")):
        if path.name == "registry.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "HASH_FAMILY_NAMES" not in text and "FROZEN_KEY_NAMES" not in text, path


def test_t17_no_code_derives_anything_from_a_family_keys_spelling():
    """Plan 0101 §2.3: a prefix / suffix / split / regex test on a family key outside the
    reviewed sites would have been mis-renamed, and would be again."""
    keys = {*registry.FAMILIES, *registry.PRE_0101_KEYS, "multihop_mt_regex"} - {"poetry"}
    spelling = {"startswith", "endswith", "removeprefix", "removesuffix"}
    allowed = {("src/wsbench/adapt/onecue.py", "multilingual")}
    found = set()
    for path in sorted((REPO / "src/wsbench").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr in spelling:
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value in keys:
                        found.add((str(path.relative_to(REPO)), arg.value))
    assert found == allowed
    from wsbench.adapt import onecue

    item = {"target": "TARGET-FORM", "units": []}
    for family in ("multilingual", "multilingual_typo", "multilingual_multihop"):
        assert "TARGET-FORM" in onecue._gold_forms(family, item, "concept", {"gold": "g"})


# ---------------------------------------------------------------- T10 / T11: frozen files


def test_t10_the_fast_files_are_read_in_todays_keys():
    for version in sorted(fast.VERSIONS):
        raw = json.loads(fast.VERSIONS[version].read_text(encoding="utf-8"))
        got = fast.subset(version)
        pre = fast.KEY_ERA[version] == "pre-0101"  # a file cut after the rename is in today's keys

        def today(key: str, pre: bool = pre) -> str:
            return registry.PRE_0101_KEYS.get(key, key) if pre else key

        assert set(got) == {today(f) for f in raw["families"]}
        assert {"basic_readout", "basic_readout_st", "multihop"} <= set(got)
        assert not {"basic_readout_mt", "multihop_mt"} & set(got)
        for old, entry in raw["families"].items():
            new = today(old)
            assert got[new] == entry, (version, old)
            # a version frozen before a family's bank changed keeps its old sha (a record): by
            # rule, the entries that are not the selectable versions' (tests/test_fast_subset.py
            # pins which families those are, `REFROZEN`)
            live = [v for v in fast.VARIANTS.values() if new in fast.subset(v)]
            refrozen = any(not fast.compatible(version, new, against=v) for v in live)
            assert (entry["bank_sha"] == fast.bank_sha(new)) != refrozen, (version, old)


def test_t11_every_frozen_entry_under_a_renamed_key_carries_that_familys_stamp():
    files = [
        *sorted((REPO / "evals/baselines").glob("*.json")),
        *(REPO / "adapted").glob("*/floors/*.json"),
    ]
    files += sorted((REPO / "adapted").glob("*/anti_text_inversion*.json"))
    n = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = dict(doc) if "protocols" not in doc else {}
        for proto in (doc.get("protocols") or {}).values():
            for family, pv in (proto.get("prompt_version") or {}).items():
                entries.setdefault(family, {"instrument": pv})
        for family in EIGHT:
            e = entries.get(family)
            stamp = e.get("instrument") if isinstance(e, dict) else None
            if not isinstance(stamp, str) or not stamp:
                continue
            assert registry.stored_family(registry.shared_key(family), stamp) == family, (
                path,
                family,
            )
            assert not registry.stale_floor_key(family, stamp)
            n += 1
    assert n > 100
    scores = sorted((REPO / "adapted").glob("*/lenses/scores.json"))
    for path in scores:
        for row in json.loads(path.read_text(encoding="utf-8")):
            if row.get("family") in EIGHT:  # the macro rows carry no family
                key = registry.shared_key(row["family"])
                assert registry.stored_family(key, row["instrument"]) == row["family"], path


@pairs
def test_t11_a_floors_file_written_before_the_rename_is_refused(bare, tmp_path):
    from wsbench.baselines import prompt_only as po

    st_stamp = registry.FAMILIES[f"{bare}_st"].judge.prompt_version
    stale = {bare: {"instrument": st_stamp, "rate": 0.5}}  # the single-token family's, pre-0101
    path = tmp_path / "prompt_only_summary.json"
    path.write_text(json.dumps(stale))
    with pytest.raises(RenamedKey, match="written before plan 0101"):
        po.summary_floors(path)
    assert registry.stale_floor_key(bare, st_stamp)
    assert ti._by_family(stale, bare) is None  # never served to the multi-token family


# ---------------------------------------------------------------- T12: ATI work directories


@pairs
def test_t12_a_pre_0101_work_dir_keeps_each_row_with_its_own_family(bare, tmp_path):
    st, mt = f"{bare}_st", f"{bare}_mt"
    st_id, mt_id = _ids(st)[0], _ids(bare)[0]
    prompts = [
        {"family": bare, "id": st_id, "prefix": "p", "token": "t"},
        {"family": mt, "id": mt_id, "prefix": "p", "token": "t"},
    ]
    got = registry.attribute_rows([dict(r) for r in prompts])
    assert [(r["family"], r["id"]) for r in got] == [(st, st_id), (bare, mt_id)]
    path = tmp_path / "draw0.jsonl"
    write_jsonl(path, [{**r, "error": "", "answer": "a"} for r in prompts])
    assert set(ti.latest_answers(path)) == {(st, st_id), (bare, mt_id)}
    # a judged directory of the partner under the bare key
    d = tmp_path / "judged" / bare
    d.mkdir(parents=True)
    doc = {"family": bare, "rows": [{"id": st_id, "pass": True}],
           "config": {"prompt_version": registry.FAMILIES[st].judge.prompt_version},
           "numbers": {"metric": "pass_rate", "value": 1.0}}  # fmt: skip
    (d / "results.json").write_text(json.dumps(doc))
    # (the verdict field is each family's own row shape: only the attribution is under test)
    assert set(ti.draw_verdicts(d / "results.json", expect=st)) == {st_id}
    with pytest.raises(RenamedKey, match=f"holds results of '{st}'"):
        ti.draw_verdicts(d / "results.json", expect=bare)


# ---------------------------------------------------------------- T13: viewers


@pairs
def test_t13_a_run_tree_directory_is_shown_as_the_family_that_wrote_it(bare, tmp_path):
    st, mt = registry.FAMILIES[f"{bare}_st"], registry.FAMILIES[bare]
    tree = tmp_path / "judged_opus"
    for name, pv in ((bare, st.judge.prompt_version), (f"{bare}_mt_opus", mt.judge.prompt_version)):
        (tree / name).mkdir(parents=True)
        doc = {"family": name.removesuffix("_opus"), "config": {"prompt_version": pv}}
        (tree / name / "results.json").write_text(json.dumps(doc))
    assert registry.dir_family(tree / bare) == st.name
    assert registry.dir_family(tree / f"{bare}_mt_opus", f"{bare}_mt") == bare
    (tmp_path / "empty" / bare).mkdir(parents=True)
    assert registry.dir_family(tmp_path / "empty" / bare) is None  # unattributable: skipped
    assert registry.dir_family(tree / "poetry") == "poetry"
    ro = write_jsonl(tmp_path / f"s.{bare}.jsonl", _rows(st.name))
    assert registry.file_family(ro, bare) == st.name


def test_t13_both_viewers_attribute_through_the_helper():
    for viewer in ("atlas/build.py", "viewer_app/index.py"):
        text = (REPO / viewer).read_text(encoding="utf-8")
        assert "dir_family(jd, name)" in text and "fam = jd.name" not in text, viewer


# ---------------------------------------------------------------- T14: floors readouts


@pairs
def test_t14_a_pre_0101_floors_readouts_dir_holds_both_members(bare, tmp_path):
    st = f"{bare}_st"
    rd = tmp_path / "readouts"
    rd.mkdir()
    write_jsonl(rd / f"{bare}.jsonl", _rows(st))
    write_jsonl(rd / f"{bare}_mt.jsonl", _rows(bare))
    stems = {registry.file_family(p) or registry.canonical(p.stem) for p in rd.glob("*.jsonl")}
    assert stems == {bare, st}
    assert runner.readouts_path(rd, st) == rd / f"{bare}.jsonl"
    assert runner.readouts_path(rd, bare) == rd / f"{bare}_mt.jsonl"


# ---------------------------------------------------------------- T16: the name-embedding sites


def _pre(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


def test_t16_language_distractors_seed_with_the_pre_0101_key():
    from wsbench.multitoken import options

    assert set(options.R4_LANG_POOLS) == {
        "multilingual_st", "multilingual", "multilingual_multihop", "multilingual_typo",
    }  # fmt: skip
    for family, old in (("multilingual_st", "multilingual"), ("multilingual", "multilingual_mt")):
        for gold in sorted(options.R4_LANG_POOLS[family])[:4]:
            pool = [p for p in options.R4_LANG_POOLS[family] if p != gold]
            random.Random(_pre(f"{options.R4_LANG_SEED}|{old}|{gold}")).shuffle(pool)
            pool.sort(key=lambda p: -options.r4_lang_score(gold, p))
            want = pool[: options.N_DISTRACTORS]
            assert options.r4_language_distractors(family, gold) == want, (family, gold)


def test_t16_dev_split_and_option_order_seed_with_the_pre_0101_key():
    from wsbench import mc
    from wsbench.banks import load_bank
    from wsbench.basic import mcjudge_bank

    for family in EIGHT:
        old = registry.frozen_name(family)
        for iid in sorted(registry.registered_ids(family))[:20]:
            want = mc.seed_int(f"{old}:{iid}") % 1000 < split.DEV_SHARE * 1000
            assert split.is_dev(family, iid) == want
    _h, items = load_bank(registry.frozen_bank_path("multihop_st"))
    for it in items[:5]:
        content = [it["mc"]["gold"], *it["mc"]["distractors"]]
        want = mc.seeded_shuffle(content, f"multihop|{it['id']}")  # the single-token key then
        shown, gold = mcjudge_bank.options_of("multihop_st", it)
        assert shown[:-1] == want and shown[gold] == it["mc"]["gold"]


def test_t16_the_shared_key_helpers_keep_the_stored_keys():
    """The three key helpers behind sites the pre/post manifest cannot observe on its own (it
    builds those keys itself): each writes the key the family's stored rows already carry."""
    import importlib.util

    def script(name):
        spec = importlib.util.spec_from_file_location(f"_t16_{name}", REPO / f"scripts/{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        return mod

    # lucky-guessing call keys: the HASH name (v1.2.0 site)
    want = {
        "basic_readout": "basic_readout_mt", "multihop": "multihop_mt_v2",
        "multilingual": "multilingual_mt", "typo": "typo_mt", "basic_readout_st": "basic_readout",
        "multihop_st": "multihop", "multilingual_st": "multilingual", "typo_st": "typo",
        "wrong_intermediate": "wrong_bridge", "poetry": "poetry",
    }  # fmt: skip
    for family, key in want.items():
        assert lg.call_key(family, "blind", "an-id", 2) == f"{key}|blind|an-id|d2"
    # builder keys: the key of just before plan 0101 (multihop: multihop_mt, not multihop_mt_v2)
    refine, confusers = script("r4b_mc_refine"), script("common_confusers_r5")
    frozen = {**want, "multihop": "multihop_mt", "wrong_intermediate": "wrong_intermediate"}
    for family, key in frozen.items():
        assert refine.draw_key(family, ("an-id", "role")) == f"{key}|('an-id', 'role')"
        assert confusers.gate_key(family, "an-id") == f"{key}|an-id"
    assert set(confusers.BANKS) == {"basic_readout_st", "association"}
    assert set(refine.FAMILIES) == {
        "basic_readout", "multihop", "multilingual_multihop", "multilingual", "multilingual_typo",
    }  # fmt: skip


# ---------------------------------------------------------------- no vacuous walk


_WALK = re.compile(r"""\.(?:glob|rglob)\(\s*f?["']([^"']+)["']""")


def test_every_walk_over_the_family_trees_matches_something():
    """A ``glob`` written for the flat layout (``evals/*/README.md``, ``adapted/*/typo_mt.json``)
    matches nothing after the move, and a guard built on it passes vacuously: every literal
    glob over the repository's ``evals/``, ``adapted/`` or ``examples/`` trees in the tests, the
    package, ``scripts/``, ``atlas/``, ``viewer_app/`` and the skills' scripts must match at
    least one path today. Two spellings are recognised, ``(X / "evals").glob("...")`` and
    ``REPO.glob("evals/...")``; a pattern with a placeholder is skipped, and so is a walk over
    a run tree outside the repository (most of the viewers' and scripts' walks: there is no
    such tree to match against here)."""
    absent_on_purpose = {
        "*/multihop_mt_v2.json", "*/multihop_mt.json", "*_mt.json",  # retired by plan 0101
        "*/hallucination*.json",  # the pre-rename key of a family renamed in v1.2.0
    }  # fmt: skip
    trees = ("evals", "adapted", "examples")
    empty, seen = [], 0
    files = [*(REPO / "tests").glob("*.py"), *(REPO / "src/wsbench").rglob("*.py")]
    for top in ("scripts", "atlas", "viewer_app", ".claude"):
        files += (REPO / top).rglob("*.py")
    for path in sorted(files):
        for line in path.read_text(encoding="utf-8").split("\n"):
            m = _WALK.search(line)
            if not m or "{" in m.group(1) or "..." in m.group(1):
                continue  # a placeholder (or this docstring's own examples)
            if m.group(1) in absent_on_purpose:
                continue
            pattern, bases = m.group(1), []
            if pattern.split("/")[0] in trees and re.search(r"\b(?:REPO|ROOT)\.r?glob\(", line):
                bases.append(REPO)
            for base in trees:
                if re.search(rf'"{base}"\)?\s*\)?\.(?:glob|rglob)\(', line):
                    bases.append(REPO / base)
            for base in bases:
                seen += 1
                if not list(base.glob(pattern)):
                    where = base.relative_to(REPO).as_posix()
                    empty.append(f"{path.relative_to(REPO)}: ({where}).glob({pattern!r})")
    assert seen >= 10  # the scan itself is not vacuous
    assert not empty, empty
    # the two guards the move would have emptied: they cover the family directories again
    assert len([registry.family_root(f) / "README.md" for f in registry._layout()]) == 32
    assert sorted(readplan.families()) == sorted(registry.FAMILIES)
