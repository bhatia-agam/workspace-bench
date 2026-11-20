"""Plan 0101 (2026-11-20): the multi-token families took the plain keys, the single-token ones
became ``<key>_st``, and every family directory moved under its category. No instrument moved
(T1); everything written before the rename reads as the family it was written for, or is
refused (T2-T14); the name-embedding sites keep their pre-rename inputs (T16); no walk over the
family trees is vacuous."""

import ast
import hashlib
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


# ---------------------------------------------------------------- T1: no instrument moved


def test_t1_the_manifest_is_byte_identical_under_the_key_translation(tmp_path):
    """``scripts/manifest_0101.py --check`` (its own process: it patches the LLM layer): every
    hash, seed, option order, prompt sha, call key and fingerprint of all 32 families equals the
    manifest made on main before the rename, with family keys read through ``frozen_name``."""
    script, golden = REPO / "scripts/manifest_0101.py", REPO / "tests/golden/manifest_0101_pre.json"
    env = {"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path), "PYTHONPATH": str(REPO / "src")}
    r = subprocess.run(
        [sys.executable, str(script), "--check", str(golden)],
        capture_output=True, text=True, env=env, cwd=REPO,
    )  # fmt: skip
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-4000:]
    assert "identical (32 families" in r.stdout
    doc = json.loads(golden.read_text(encoding="utf-8"))
    assert doc["script_sha256"] == hashlib.sha256(script.read_bytes()).hexdigest()


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
        assert set(got) == {registry.PRE_0101_KEYS.get(f, f) for f in raw["families"]}
        assert {"basic_readout", "basic_readout_st", "multihop"} <= set(got)
        assert not {"basic_readout_mt", "multihop_mt"} & set(got)
        for old, entry in raw["families"].items():
            new = registry.PRE_0101_KEYS.get(old, old)
            assert got[new] == entry and entry["bank_sha"] == fast.bank_sha(new), (version, old)


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
