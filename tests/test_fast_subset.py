"""Plans 0090 / 0094 / 0095: the frozen fast subsets (``fast-v1``, ``fast-v3`` = the default one,
``fast-safety-v2`` = ``--fast-safety``), the positions rules, loader, rescore and CLI."""

import dataclasses
import hashlib
import importlib.util
import json
import os
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import write_jsonl, write_sidecar

from wsbench import fast, llm, mcjudge, readplan, reads, registry, runner
from wsbench.baselines import text_inversion as ti
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.registry import EvalSpec, JudgeArgs
from wsbench.results import (
    MACRO_METRICS,
    FamilyResult,
    completeness,
    macro,
    read_results,
    write_results,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "golden" / "plan_sha_pre_0090.json"
WRITE_GOLDEN_ENV = "WSB_WRITE_GOLDEN_0090"  # set once, on the pre-0090 code, to create GOLDEN


@pytest.fixture(autouse=True)
def _registered_set(monkeypatch, real_families):
    """The registered Qwen3.6-27B banks (no adapted root, no bank pin), every family registered."""
    monkeypatch.delenv("WSB_BANK_ROOT", raising=False)
    monkeypatch.delenv(readplan.LAYERS_ENV, raising=False)
    for k in [k for k in os.environ if k.startswith("WSB_BANK_FILE_")]:
        monkeypatch.delenv(k)


def _rows_sha(specs) -> str:
    """sha256 of the plan rows exactly as ``wsbench plan`` writes them (every key). A row names
    its family by the CURRENT key, so the golden (recorded before plan 0101) is compared with
    that one field translated back (``registry.frozen_name``): nothing else in a row may move."""
    h = hashlib.sha256()
    for s in specs:
        row = s.row()
        row["family"] = registry.frozen_name(row["family"])
        h.update(json.dumps(row, ensure_ascii=False).encode() + b"\n")
    return h.hexdigest()


def _non_fast_shas() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {"plan_sha": {}, "rows": {}}
    for fam in readplan.families():
        out["plan_sha"][fam] = reads.plan_sha(fam)
        out["rows"][fam] = _rows_sha(readplan.plan(fam))
    return out


# ---------------------------------------------------------------- 4b. the non-fast plan


def test_non_fast_plan_is_byte_identical_to_pre_0090():
    """``plan_sha`` and the written plan rows of every family equal the values
    recorded on the code before plan 0090 (under pytest: the conftest stubs set nyt's and
    knowledge_cutoff's texts)."""
    got = _non_fast_shas()
    if os.environ.get(WRITE_GOLDEN_ENV):
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # the golden is keyed by the families' pre-0101 keys (plan 0101: translated, never rewritten)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    want = {kind: registry.rekey_pre_0101(by_family) for kind, by_family in golden.items()}
    # a family registered after plan 0090 has no pre-0090 record (plan 0106); every family of
    # the golden is still compared in full, and no other family may appear
    since = {"user_modeling_hard", "association_hard"}
    assert all(set(by_family) - set(want[kind]) == since for kind, by_family in got.items())
    got = {k: {f: v for f, v in by.items() if f not in since} for k, by in got.items()}
    assert got == want


# ---------------------------------------------------------------- helpers

V1, V2, VS1 = "fast-v1", "fast-v2", "fast-safety-v1"  # frozen predecessors
V3 = "fast-v3"  # the default from 2026-11-20 to plan 0104 (conjunctive_association on bank v6)
V4 = "fast-v4"  # plan 0104: a seeded random half of core, the default until plan 0110
V5 = "fast-v5"  # plan 0110: fast-v4 re-cut for chain_intermediates' bank v3
V6 = "fast-v6"  # plan 0114: the default, fast-v5 plus user_modeling_hard and association_hard
CORE_HALF = {V4, V5, V6}  # tests/test_fast_core_half.py
VS = "fast-safety-v2"  # plan 0095: `--fast-safety` (retired by plan 0104; the file stays)
OUTCOME_SELECTED = (V1, V2, VS1, V3, VS)  # the frozen predecessors this file is about
FAMILIES_V1 = sorted(fast.subset(V1))  # 24
FAMILIES_V3 = sorted(fast.subset(V3))  # 22: v1's without jailbreak_recognition and agentic
CONJ = "conjunctive_association"
DM = "directed_modulation"
# The families whose REGISTERED bank changed after a version was frozen, with those versions:
# their entry there is a record (``fast.entry`` fails closed, "bank changed ... re-freeze") and
# is entry-compatible with no later version. A re-freeze adds its family and versions here.
REFROZEN = {CONJ: (V1, V2, VS1)}  # 2026-11-20: bank v6 (comp-v6), cut as fast-v3 / fast-safety-v2
# Plan 0109: directed_modulation's registered bank is v2 (items_v2.json: the dont_think items
# removed, 37 think items added), so its entry in ALL FIVE outcome-selected files is a record of
# the 100-item items.json. No successor was cut: the item ids changed (the bank_sha-only script
# refuses), the selection of these files needs 23 arms' outcomes, which the new items do not
# have, and the family is in no selectable version (fast-v4 is a half of core; it is not core).
NOT_REFROZEN = {DM: OUTCOME_SELECTED}
SUPERSEDED = sorted(
    (v, f) for table in (REFROZEN, NOT_REFROZEN) for f, versions in table.items() for v in versions
)
# the families a version still serves on their registered bank
LIVE_V3 = [f for f in FAMILIES_V3 if (V3, f) not in SUPERSEDED]  # 21
LIVE_VS = [f for f in FAMILIES_V1 if (VS, f) not in SUPERSEDED]  # 23
DM_READ_ITEMS = 62  # its frozen entry in each of the five files
BY_VERSION = [
    (v, f)
    for v in (V1, V2, VS1, V3, VS)
    for f in sorted(fast.subset(v))
    if (v, f) not in SUPERSEDED
]
DROPPED = (
    "typo",
    "association",
    "multihop_st",
    "multilingual_st",
    "chain_intermediates",
    "multilingual",
)
STRICT_ATI_FAMILIES = (  # ati-subset-v2 (plan 0085, tests/test_ati_freeze.py)
    "introspection",
    "moral_rationale",
    "wrong_intermediate",
    "knowledge_cutoff",
    "conjunctive_association",
    "model_specific_directed_modulation",
    "model_multihop",
    "poetry",
)
JB, AM = "jailbreak_recognition", "agentic_misalignment"
DROPPED_V3 = (*DROPPED, JB, AM)  # plan 0094


def _now(names):
    """Family keys read off a frozen file (written in the pre-0101 keys, plan 0101) as the keys
    of today: what ``fast._file`` serves."""
    return [registry.PRE_0101_KEYS.get(f, f) for f in names]


REAL_RUN_CALLS = mcjudge.run_calls  # the `toy` fixture replaces it


@pytest.fixture(autouse=True)
def _the_frozen_predecessors(monkeypatch, _default_fast_subset):
    """Plan 0104: this file tests the machinery on the versions it was written for. The default
    is fast-v6 now (``tests/test_fast_core_half.py``); here every test starts on fast-v3, the
    last outcome-selected version, as it did while fast-v3 was the default, so the assertions
    below keep their values. ``--fast`` runs the active subset, whatever made it active.
    Returns the version that was active when the test's setup reached this fixture, after
    conftest's reset (``_default_fast_subset``, requested here so that it runs first)."""
    before = fast.VERSION
    monkeypatch.setattr(fast, "VERSION", V3)
    return before


@pytest.fixture
def fast_v1(monkeypatch):
    """The frozen ``fast-v1`` as the current subset (plan 0094): the two position-reduced
    families and their rules live only there."""
    monkeypatch.setattr(fast, "VERSION", V1)


def _units(family: str, group: str = "all") -> list[str]:
    return list(fast.subset()[family]["units"][group])


def _result(family: str, rows=(), value=None, *, extras=None, n_items=0, config=None, **kw):
    base = {
        "family": family,
        "metric": "pass_rate",
        "value": value,
        "ci95": None,
        "n_items": n_items,
        "higher_is_better": True,
        "chance": None,
        "chance_label": None,
        "complete": True,
        "pinned_instrument": True,
        "config": dict(config or {}),
        "counts": {},
        "extras": dict(extras or {}),
        "rows": [dict(r) for r in rows],
    }
    return FamilyResult(**{**base, **kw})


def _with_value(family: str, result: FamilyResult) -> FamilyResult:
    """``result`` with ``value`` = the family value its own rows give (so the guard holds)."""
    result.value = fast.value_of(*fast.units(family, result))
    return result


def _fast_row(family: str, **config) -> FamilyResult:
    cfg = {"scope": fast.SCOPE, "fast_subset": fast.VERSION, **config}
    return _result(family, value=0.5, n_items=30, config=cfg)


def _cell(iid: str, pos: int, token: str | None = "x", layer: int = 20) -> dict:
    row = {"id": iid, "layer": layer, "pos": pos, "samples": [f"s{pos}"]}
    return row if token is None else {**row, "token": token}


def _opts(**kw) -> SimpleNamespace:
    """The judge options ``runner`` reads (``cli.JudgeOptions`` after ``finalize``)."""
    base = {
        "judge_model": None,
        "layers": None,
        "items": None,
        "limit": 0,
        "allow_missing": False,
        "concurrency": 1,
        "rpm": 1e9,
        "dry_run": False,
        "anti_text_inversion": False,
        "opt": [],
        "family_workers": 1,
        "fast": True,
    }
    return SimpleNamespace(**{**base, **kw})


# ---------------------------------------------------------------- 1. the freeze


@pytest.mark.usefixtures("fast_v1")
def test_freeze_file_shape_and_counts():
    d = json.loads(fast.VERSIONS[fast.VERSION].read_text(encoding="utf-8"))
    assert d["version"] == fast.VERSION == "fast-v1" and d["subject"] == "Qwen3.6-27B"
    assert tuple(_now(d["dropped_families"])) == DROPPED
    assert len(d["families"]) == 24 and not set(DROPPED) & set(_now(d["families"]))
    assert "jlens_concept_pr" not in d["families"]
    assert fast.families() == FAMILIES_V1  # registry order
    n_units = sum(len(u) for e in d["families"].values() for u in e["units"].values())
    n_read = sum(len(e["read_ids"]) for e in d["families"].values())
    assert (n_units, n_read) == (1996, 2351)
    for fam, e in d["families"].items():
        groups = ["jailbreak", "control"] if fam == JB else ["all"]
        assert list(e["units"]) == groups, fam
        every = [u for g in groups for u in e["units"][g]]
        assert len(set(every)) == len(every), fam
        assert set(e) <= {"bank_sha", "units", "read_ids", "positions"}, fam
    assert d["families"][JB]["positions"] == {"kind": "punct_special"}
    assert d["families"][AM]["positions"] == {"kind": "last_n", "n": 60}
    assert [f for f, e in d["families"].items() if "positions" in e] == [AM, JB]


@pytest.mark.parametrize(("version", "fam"), BY_VERSION)
def test_freeze_family_is_registered_in_the_macro_and_on_its_bank(version, fam, monkeypatch):
    monkeypatch.setattr(fast, "VERSION", version)
    spec = registry.FAMILIES[fam]
    assert fam not in registry.not_in_macro() and fam not in registry.superseded()
    assert fam not in registry.RETIRED_FAMILIES and spec.metric in MACRO_METRICS
    e = fast.subset()[fam]
    # fails on a bank edit: the ids were chosen on these bytes (re-freeze, evals/fast/README.md)
    assert e["bank_sha"] == fast.bank_sha(fam)
    assert fast.entry(fam) is e
    plan_ids = [s.id for s in readplan.plan(fam)]
    assert len(set(e["read_ids"])) == len(e["read_ids"])
    assert set(e["read_ids"]) <= set(plan_ids)
    assert e["read_ids"] == [i for i in plan_ids if i in set(e["read_ids"])]  # plan order


@pytest.mark.parametrize("fam", STRICT_ATI_FAMILIES)
def test_freeze_contains_the_strict_ati_subset_whole(fam):
    ati = ti.subset_entry(fam, ti.FROZEN)["ids"]
    e = fast.subset()[fam]
    assert ati and set(ati) <= set(e["units"]["all"]) and set(ati) <= set(e["read_ids"])


@pytest.mark.parametrize(("version", "fam"), SUPERSEDED)
def test_a_version_frozen_before_a_bank_change_fails_closed_for_that_family(
    version, fam, monkeypatch
):
    """The frozen predecessor keeps its bytes and its old ``bank_sha``: under it the family is
    refused (never judged on the new bank as if nothing changed), and the versions that replaced
    it hold the same units and read ids on the registered bank."""
    old = fast.subset(version)[fam]
    assert old["bank_sha"] != fast.bank_sha(fam)
    for current in (V3, VS) if fam in REFROZEN else ():  # NOT_REFROZEN: no successor holds it
        new = fast.subset(current)[fam]
        assert new["bank_sha"] == fast.bank_sha(fam)
        assert {k: v for k, v in new.items() if k != "bank_sha"} == {
            k: v for k, v in old.items() if k != "bank_sha"
        }
        assert not fast.compatible(version, fam, against=current)
    monkeypatch.setattr(fast, "VERSION", version)
    with pytest.raises(SystemExit, match=f"{fam}: bank changed since {version} was frozen") as e:
        fast.entry(fam)
    assert not isinstance(e.value, fast.NotInFast)
    with pytest.raises(SystemExit, match="bank changed since"):
        readplan.plan(fam, fast=True)


def test_strict_ati_subset_is_350_ids():
    assert ti.SUBSET_VERSION == "ati-subset-v2"
    assert sum(len(ti.subset_entry(f, ti.FROZEN)["ids"]) for f in STRICT_ATI_FAMILIES) == 350


def test_entry_fails_closed(monkeypatch):
    with pytest.raises(fast.NotInFast) as e:
        fast.entry("typo")
    assert e.value.code == "typo: not in fast-v3"
    monkeypatch.setenv("WSB_BANK_ROOT", "adapted/glm-5.3")
    with pytest.raises(SystemExit) as e:
        fast.entry("poetry")
    assert not isinstance(e.value, fast.NotInFast)
    assert "registered Qwen3.6-27B banks only" in str(e.value.code)
    with pytest.raises(fast.NotInFast):  # a dropped family is skipped whatever the bank env
        fast.entry("association")
    monkeypatch.delenv("WSB_BANK_ROOT")
    monkeypatch.setenv("WSB_BANK_FILE_POETRY", "evals/basic/poetry/items.json")
    with pytest.raises(SystemExit, match="registered Qwen3\\.6-27B banks only"):
        fast.entry("poetry")
    assert fast.entry("basic_readout_st")  # another family's pin does not matter
    monkeypatch.delenv("WSB_BANK_FILE_POETRY")
    monkeypatch.setattr(fast, "bank_sha", lambda family: "0" * 64)
    with pytest.raises(SystemExit, match="bank changed since fast-v3 was frozen; re-freeze"):
        fast.entry("poetry")


def test_bank_sha_is_the_registered_file_hash():
    path = registry.frozen_bank_path("poetry")
    assert fast.bank_sha("poetry") == hashlib.sha256(path.read_bytes()).hexdigest()
    assert fast.bank_sha("wrong_bridge") == fast.bank_sha("wrong_intermediate")  # a former key


# ---------------------------------------------------------------- 2. is_fast_site

FW_COMMA, CJK_CLOSE, CURLY_CLOSE = "\uff0c", "\u300d", "\u201d"  # fullwidth comma, 」, ”
SITES = [".", " ,", '."', "\uff09\uff0c", "\n", " \n\n", "<|im_end|>", "<|im_start|>", "<think>"]
SITES += ["</think>", "<|endoftext|>", "<tool_call>", "<turn|>", "?!", " \u2026"]
SITES += [FW_COMMA, CJK_CLOSE, CURLY_CLOSE]
NOT_SITES = ["the", " 5", "$", "+", "<", "a<b>", "", " ", "<|", "<a b>", "x.", "Ċ", "Ġ,"]


@pytest.mark.parametrize("token", SITES)
def test_is_fast_site(token):
    assert readplan.is_fast_site(token)


@pytest.mark.parametrize("token", NOT_SITES)
def test_is_not_fast_site(token):
    assert not readplan.is_fast_site(token)


# ---------------------------------------------------------------- 3. resolve

TOKS = [
    "<|im_start|>",
    "user",
    "\n",
    "Tell",
    " me",
    ",",
    " now",
    FW_COMMA,
    " ok",
    "<|im_end|>",
    "\n",
]


def test_resolve_punct_special_and_its_fallback():
    assert readplan.resolve({"kind": "punct_special"}, TOKS) == [0, 2, 5, 7, 9, 10]
    assert readplan.resolve({"kind": "punct_special"}, ["a", "b", "c"]) == [2]
    assert readplan.resolve({"kind": "punct_special"}, []) == []


def test_resolve_fast_of_both_kinds():
    full_all = {"kind": "all"}
    r = {"kind": "fast_of", "full": full_all, "fast": {"kind": "last_n", "n": 3}}
    assert readplan.resolve(r, TOKS) == [8, 9, 10]
    r = {"kind": "fast_of", "full": full_all, "fast": {"kind": "last_n", "n": 60}}
    assert readplan.resolve(r, TOKS) == list(range(11))  # fewer than n: all of them
    r = {"kind": "fast_of", "full": full_all, "fast": {"kind": "punct_special"}}
    assert readplan.resolve(r, TOKS) == [0, 2, 5, 7, 9, 10]
    # a full rule that is not `all`: the fast rule applies WITHIN its positions, in its order
    span = {"kind": "positions", "positions": [3, 4, 5, 6, 7, 8]}
    r = {"kind": "fast_of", "full": span, "fast": {"kind": "punct_special"}}
    assert readplan.resolve(r, TOKS) == [5, 7]
    r = {"kind": "fast_of", "full": span, "fast": {"kind": "last_n", "n": 2}}
    assert readplan.resolve(r, TOKS) == [7, 8]
    # negative offsets (all_from_end) index the same tokens
    r = {"kind": "fast_of", "full": {"kind": "all_from_end"}, "fast": {"kind": "punct_special"}}
    assert readplan.resolve(r, TOKS) == [-11, -9, -6, -4, -2, -1]
    # fallback: no fast site inside the full positions -> the last full position
    words = {"kind": "positions", "positions": [3, 4]}
    r = {"kind": "fast_of", "full": words, "fast": {"kind": "punct_special"}}
    assert readplan.resolve(r, TOKS) == [4]
    with pytest.raises(ValueError, match="unknown fast rule"):
        readplan.resolve({"kind": "fast_of", "full": full_all, "fast": {"kind": "same"}}, TOKS)


@pytest.mark.usefixtures("fast_v1")
@pytest.mark.parametrize("token", [FW_COMMA, CJK_CLOSE, CURLY_CLOSE])
def test_non_ascii_punctuation_is_a_site_for_resolve_and_reads(token, tmp_path, mk_args):
    toks = ["日本", token, "語"]
    assert readplan.resolve({"kind": "punct_special"}, toks) == [1]
    iid = fast.subset()[JB]["read_ids"][0]
    path = write_jsonl(tmp_path / "jb.jsonl", [_cell(iid, p, t) for p, t in enumerate(toks)])
    cells, rep = reads.load(mk_args(path, scope=fast.SCOPE), JB)
    assert [(c.pos, c.token) for c in cells] == [(1, token)] and rep.fast_fallback_ids == []


# ---------------------------------------------------------------- 4. the fast plan


@pytest.mark.parametrize(("version", "fam"), BY_VERSION)
def test_fast_plan_rows(version, fam, monkeypatch):
    monkeypatch.setattr(fast, "VERSION", version)
    e = fast.subset()[fam]
    full = {s.id: s for s in readplan.plan(fam)}
    specs = readplan.plan(fam, fast=True)
    assert [s.id for s in specs] == e["read_ids"]
    for s in specs:
        if "positions" in e:
            want = {"kind": "fast_of", "full": full[s.id].positions, "fast": e["positions"]}
            assert s.positions == want and s.extra["fast"] == fast.VERSION
            assert dataclasses.replace(s, positions=full[s.id].positions, extra={}) == (
                dataclasses.replace(full[s.id], extra={})
            )
        else:
            assert s == full[s.id]  # the full plan's row, untouched
    if "positions" not in e:  # a FAST file's sha is its own: fewer rows than the full plan
        assert (reads.fast_plan_sha(fam) == reads.plan_sha(fam)) == (len(specs) == len(full))


def test_fast_plan_refusals():
    with pytest.raises(fast.NotInFast):
        readplan.plan("multihop_st", fast=True)
    assert fast.SCOPE not in json.dumps([s.row() for s in readplan.plan(AM)][:2])


# ---------------------------------------------------------------- 5. reads.load


def _jb_rows(tokens_by_item: dict[str, list[str | None]], layer: int = 20) -> list[dict]:
    return [
        _cell(iid, 100 + p, t, layer)
        for iid, toks in tokens_by_item.items()
        for p, t in enumerate(toks)
    ]


@pytest.mark.usefixtures("fast_v1")
def test_full_file_is_narrowed_punct_special(tmp_path, mk_args):
    a, b, c = fast.subset()[JB]["read_ids"][:3]
    other = next(s.id for s in readplan.plan(JB) if s.id not in set(fast.subset()[JB]["read_ids"]))
    rows = _jb_rows(
        {
            a: ["Do", " it", ".", "\n", "<|im_end|>"],
            b: ["all", " words", " here"],  # no fast site: the item's last position
            c: ["…", "x"],
            other: [".", "."],  # not a fast read id: never loaded
        }
    )
    path = write_jsonl(tmp_path / "jb.jsonl", rows)
    args = mk_args(path, scope=fast.SCOPE)
    cells, rep = reads.load(args, JB)
    assert {(x.id, x.pos) for x in cells} == {(a, 102), (a, 103), (a, 104), (b, 102), (c, 100)}
    assert rep.fast_fallback_ids == [b] and rep.n_cells_before_fast == 10
    assert json.loads(rep.fast_rule) == {"kind": "punct_special"}
    assert reads.config_stamps(args)["reads"] == "full"
    assert reads.config_stamps(args)["fast_rule"] == rep.fast_rule
    extras = reads.extras_of(args)
    assert extras["n_cells_before_fast"] == 10 and extras["fast_fallback_ids"] == [b]
    # site_tokens are collected before the narrowing (judges show context tokens)
    assert rep.site_tokens[a] == {100: "Do", 101: " it", 102: ".", 103: "\n", 104: "<|im_end|>"}
    assert other not in rep.site_tokens
    # the family's own ids= are intersected with the fast read ids
    cells, _ = reads.load(mk_args(path, scope=fast.SCOPE), JB, ids=[a, other])
    assert {x.id for x in cells} == {a}
    cells, _ = reads.load(mk_args(path, scope=fast.SCOPE), JB, positions={c: [100, 101]})
    assert {(x.id, x.pos) for x in cells} == {(c, 100)}


@pytest.mark.usefixtures("fast_v1")
def test_full_file_without_token_is_refused_under_punct_special(tmp_path, mk_args, capsys):
    a = fast.subset()[JB]["read_ids"][0]
    path = write_jsonl(tmp_path / "jb.jsonl", _jb_rows({a: [".", None]}))
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE), JB)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert a in err and "token" in err


@pytest.mark.usefixtures("fast_v1")
def test_full_file_is_narrowed_last_n(tmp_path, mk_args):
    a, b = fast.subset()[AM]["read_ids"][:2]
    rows = [_cell(a, p, None) for p in range(100)] + [_cell(b, p, None) for p in range(40)]
    rows += [_cell(a, p, None, layer=24) for p in range(10, 75)]
    path = write_jsonl(tmp_path / "am.jsonl", rows)
    args = mk_args(path, scope=fast.SCOPE)
    cells, rep = reads.load(args, AM)
    got = {(i, L): sorted(x.pos for x in cells if (x.id, x.layer) == (i, L)) for i, L in
           [(a, 20), (b, 20), (a, 24)]}  # fmt: skip
    assert got[(a, 20)] == list(range(40, 100)) and got[(a, 24)] == list(range(15, 75))
    assert got[(b, 20)] == list(range(40))  # fewer than 60 present: all of them
    assert rep.n_cells_before_fast == 205 and len(cells) == 160 and rep.fast_fallback_ids == []
    assert json.loads(reads.config_stamps(args)["fast_rule"]) == {"kind": "last_n", "n": 60}


def test_a_family_without_fast_positions_is_only_restricted(tmp_path, mk_args):
    keep = fast.subset()["poetry"]["read_ids"][0]
    drop = next(s.id for s in readplan.plan("poetry") if s.id not in set(_units("poetry")))
    rows = [_cell(keep, 7, "a"), _cell(keep, 8, "b"), _cell(drop, 7, "a")]
    path = write_jsonl(tmp_path / "poetry.jsonl", rows)
    args = mk_args(path, scope=fast.SCOPE)
    cells, rep = reads.load(args, "poetry")
    assert [(x.id, x.pos) for x in cells] == [(keep, 7), (keep, 8)]
    assert rep.fast_rule == "" and "fast_rule" not in reads.config_stamps(args)
    assert "n_cells_before_fast" not in reads.extras_of(args)
    # no flag: every row, as before plan 0090; `opts=fast=1` is not the flag
    for extra in ({}, {"fast": "1"}, {"fast": "True"}):
        plain = mk_args(path, extra=extra)
        cells, rep = reads.load(plain, "poetry")
        assert len(cells) == 3 and "fast_rule" not in reads.config_stamps(plain)
        assert not mcjudge.is_subset(plain) and plain.scope == ""


def test_fast_load_refuses_a_dropped_family(tmp_path, mk_args):
    path = write_jsonl(tmp_path / "x.jsonl", [_cell("a", 1)])
    with pytest.raises(fast.NotInFast):
        reads.load(mk_args(path, scope=fast.SCOPE), "multihop_st")


@pytest.mark.usefixtures("fast_v1")
def test_prompt_only_reader_is_restricted_and_nothing_else(tmp_path, mk_args):
    a = fast.subset()[JB]["read_ids"][0]
    other = next(s.id for s in readplan.plan(JB) if s.id not in set(fast.subset()[JB]["read_ids"]))
    path = write_jsonl(tmp_path / "jb.jsonl", [_cell(a, 0, None), _cell(other, 0, None)])
    write_sidecar(path, reader="prompt_only:opus")
    args = mk_args(path, scope=fast.SCOPE)
    cells, rep = reads.load(args, JB)
    assert [x.id for x in cells] == [a] and rep.reads_checked == "prompt_only"
    assert rep.fast_rule == "" and rep.n_cells_before_fast == 0


def _fast_am_file(tmp_path, *, short: str | None = None, absent: str | None = None, **meta):
    """A FAST agentic file at layer 20: the last 60 positions of every fast read item."""
    ids = fast.subset()[AM]["read_ids"]
    rows = []
    for iid in ids:
        if iid == absent:
            continue
        n = 59 if iid == short else 60
        rows += [_cell(iid, 500 + p, None) for p in range(n)]
    path = write_jsonl(tmp_path / "am.jsonl", rows)
    meta = {"fast": fast.VERSION, "plan_sha": reads.fast_plan_sha(AM), "layers": [20], **meta}
    write_sidecar(path, **{k: v for k, v in meta.items() if v is not None})
    return path, ids


@pytest.mark.usefixtures("fast_v1")
def test_fast_declared_file_is_accepted_with_the_fast_plan_sha(tmp_path, mk_args):
    path, ids = _fast_am_file(tmp_path)
    assert reads.fast_plan_sha(AM) != reads.plan_sha(AM)
    args = mk_args(path, scope=fast.SCOPE, layers=[20])
    cells, rep = reads.load(args, AM)
    assert len(cells) == 60 * len(ids) == rep.n_cells_before_fast  # the narrowing is idempotent
    assert rep.partial_ids == [] and rep.reads_checked == "sidecar"
    assert not reads.incomplete(args) and not mcjudge.is_subset(args)


@pytest.mark.usefixtures("fast_v1")
def test_fast_declared_file_is_refused_without_the_flag(tmp_path, mk_args, capsys):
    path, _ = _fast_am_file(tmp_path)
    for extra in ({}, {"fast": "1"}):
        with pytest.raises(SystemExit) as e:
            reads.load(mk_args(path, layers=[20], extra=extra), AM)
        assert e.value.code == 2
        assert "file was produced --fast; judge it with --fast" in capsys.readouterr().err


@pytest.mark.usefixtures("fast_v1")
def test_fast_declared_file_wrong_version_or_plan_is_refused(tmp_path, mk_args, capsys):
    path, _ = _fast_am_file(tmp_path, fast="fast-v0")
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), AM)
    assert e.value.code == 2 and "another fast subset" in capsys.readouterr().err
    # the full plan's sha is not a FAST file's sha
    path, _ = _fast_am_file(tmp_path, plan_sha=reads.plan_sha(AM))
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), AM)
    assert e.value.code == 2 and "different fast plan" in capsys.readouterr().err


@pytest.mark.usefixtures("fast_v1")
def test_truncated_fast_agentic_file_is_partial(tmp_path, mk_args, capsys):
    ids = fast.subset()[AM]["read_ids"]
    path, _ = _fast_am_file(tmp_path, short=ids[3])
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), AM)
    assert e.value.code == 2 and ids[3] in capsys.readouterr().err
    args = mk_args(path, scope=fast.SCOPE, layers=[20], allow_missing=True)
    _cells, rep = reads.load(args, AM)
    assert rep.partial_ids == [ids[3]] and reads.incomplete(args) and mcjudge.is_subset(args)
    # an item of the fast read ids absent from the file is partial too
    path, _ = _fast_am_file(tmp_path, absent=ids[5])
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), AM)
    assert e.value.code == 2 and ids[5] in capsys.readouterr().err
    args = mk_args(path, scope=fast.SCOPE, layers=[20], allow_missing=True)
    _cells, rep = reads.load(args, AM)
    assert rep.partial_ids == [ids[5]] and reads.incomplete(args)


def test_full_file_with_a_sidecar_keeps_the_full_plan_guard(tmp_path, mk_args, capsys):
    """A FULL file under --fast: today's checks first (plan_sha against the FULL plan)."""
    a = fast.subset()["poetry"]["read_ids"][0]
    path = write_jsonl(tmp_path / "poetry.jsonl", [_cell(a, 7), _cell(a, 8)])
    write_sidecar(path, plan_sha=reads.fast_plan_sha("poetry"))  # not the full plan's sha
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    assert e.value.code == 2 and "different plan" in capsys.readouterr().err
    write_sidecar(path, plan_sha=reads.plan_sha("poetry"))
    cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    assert len(cells) == 2 and rep.reads_checked == "sidecar" and rep.partial_ids == []


# ---------------------------------------------------------------- 6. units / rescore


def test_units_default_family_and_rescore():
    us = _units("poetry")
    rows = [{"id": u, "pass": k % 2 == 0} for k, u in enumerate(us)]
    rows += [{"id": f"not-fast-{k}", "pass": True} for k in range(20)]  # a full-bench result
    r = _with_value("poetry", _result("poetry", rows, n_items=100, chance=0.2))
    assert r.value == pytest.approx(60 / 100)
    groups, sign = fast.units("poetry", r)
    assert sign == {"all": 1.0} and len(groups["all"]) == 100
    fast.rescore("poetry", r)
    assert r.value == pytest.approx(0.5) and r.n_items == 80 and r.complete is True
    lo, hi = r.ci95
    assert 0.3 < lo < 0.5 < hi < 0.7
    assert r.extras["fast_family_value"] == pytest.approx(0.6)
    assert r.extras["fast_n_units"] == r.extras["fast_n_scored"] == 80
    assert r.extras["fast_units_missing"] == [] and r.extras["fast_ci"] == "unit-bootstrap"
    assert "fast_rescore_mismatch" not in r.extras
    assert r.metric == "pass_rate" and r.chance == 0.2  # every other field is the family's
    again = _with_value("poetry", _result("poetry", rows))
    fast.rescore("poetry", again)
    assert again.ci95 == r.ci95  # random.Random(0): deterministic


def test_units_normalise_string_values_and_correct_rows():
    us = _units("conjunctive_association")[:4]
    rows = [
        {"id": us[0], "pass": "True"},
        {"id": us[1], "pass": "False"},
        {"id": us[2], "pass": "None"},  # undecided: no outcome
        {"id": us[3], "pass": None},
    ]
    groups, _ = fast.units("conjunctive_association", _result("conjunctive_association", rows))
    assert groups == {"all": {us[0]: 1.0, us[1]: 0.0}}
    rows = [
        {"id": us[0], "correct": True, "pick": "gold"},
        {"id": us[1], "correct": False, "pick": "cannot_tell"},
        {"id": us[2], "correct": False, "pick": "unsummarized"},  # unserved: no outcome
        {"id": us[3], "correct": "False", "pick": "api_fail"},
    ]
    groups, _ = fast.units("conjunctive_association", _result("conjunctive_association", rows))
    assert groups == {"all": {us[0]: 1.0, us[1]: 0.0}}


def test_missing_units_and_the_ten_percent_rule():
    us = _units("poetry")  # 80 units: 8 missing is exactly 10%
    for n_missing, complete in ((8, True), (9, False)):
        rows = [{"id": u, "pass": True} for u in us[n_missing:]]
        rows += [{"id": u, "pass": None} for u in us[: n_missing - 1]]  # undecided, and one rowless
        r = _with_value("poetry", _result("poetry", rows))
        fast.rescore("poetry", r)
        assert r.complete is complete and r.value == 1.0 and r.n_items == 80 - n_missing
        assert r.extras["fast_n_scored"] == 80 - n_missing and r.extras["fast_n_units"] == 80
        assert r.extras["fast_units_missing"] == sorted(us[:n_missing])
    # complete is left as the family set it
    r = _with_value("poetry", _result("poetry", [{"id": u, "pass": True} for u in us]))
    r.complete = False
    fast.rescore("poetry", r)
    assert r.complete is False and "fast_rescore_mismatch" not in r.extras
    # nothing scored (a dry run): no value, no CI, incomplete
    r = _result("poetry")
    fast.rescore("poetry", r)
    assert (r.value, r.ci95, r.n_items, r.complete) == (None, None, 0, False)


@pytest.mark.usefixtures("fast_v1")  # agentic is in fast-v1 only; buggy_code's entry is the same
@pytest.mark.parametrize(
    ("fam", "arm_key", "arm"), [(AM, "arm", "misaligned"), ("buggy_code", "src", "buggy")]
)
def test_units_pair_families(fam, arm_key, arm):
    us = _units(fam)
    other = "twin" if fam == AM else "clean"
    rows = []
    for k, u in enumerate(us):
        rows.append({"id": f"m{k}", arm_key: arm, "pair": u, "pair_hit": k < 6})
        rows.append({"id": u, arm_key: other, "pair": u, "pair_hit": k < 6})
    rows.append({"id": "orphan", arm_key: arm, "pair": None, "pair_hit": None})
    rows.append({"id": "undecided", arm_key: arm, "pair": "p-und", "pair_hit": None})
    rows.append({"id": "not-fast", arm_key: arm, "pair": "p-full", "pair_hit": True})
    r = _with_value(fam, _result(fam, rows))
    groups, _ = fast.units(fam, r)
    assert set(groups["all"]) == {*us, "p-full"} and r.value == pytest.approx(7 / (len(us) + 1))
    fast.rescore(fam, r)
    assert r.value == pytest.approx(6 / len(us)) and r.n_items == len(us)


def test_units_hinted_cutoff_is_the_class_difference():
    us = _units("hinted_cutoff")
    rows = [{"id": u, "I_flagged": k < 30, "N_flagged": 10 <= k < 15} for k, u in enumerate(us)]
    rows.append({"id": "undecided", "I_flagged": True, "N_flagged": None})
    r = _with_value("hinted_cutoff", _result("hinted_cutoff", rows))
    groups, _ = fast.units("hinted_cutoff", r)
    assert set(groups["all"].values()) == {1.0, 0.0} and "undecided" not in groups["all"]
    assert groups["all"][us[12]] == 0.0 and groups["all"][us[0]] == 1.0
    fast.rescore("hinted_cutoff", r)
    assert r.value == pytest.approx(30 / 105 - 5 / 105) and r.n_items == 105


def test_units_introspection_reads_headline_rows_only():
    us = _units("introspection")
    rows = [{"id": u, "role": "headline", "pass": k < 50} for k, u in enumerate(us)]
    rows += [{"id": f"gaussian|{k}", "role": "twin", "pass": True} for k in range(40)]
    rows[3]["pass"] = None
    r = _with_value("introspection", _result("introspection", rows))
    fast.rescore("introspection", r)
    assert r.value == pytest.approx(49 / 124) and r.n_items == 124
    assert r.extras["fast_units_missing"] == [us[3]] and r.complete is True


@pytest.mark.parametrize("fam", ["moral_rationale", "user_modeling"])
def test_units_majority_families(fam):
    us = _units(fam)
    rows = [{"id": u, "majority": "pass" if k < 10 else "fail"} for k, u in enumerate(us[2:])]
    r = _result(fam, rows, extras={"undecided_ids": [us[0]]})
    groups, _ = fast.units(fam, r)
    # an undecided id has no outcome; every other entry id scores, a rowless one 0.0
    assert us[0] not in groups["all"] and groups["all"][us[1]] == 0.0
    assert sum(groups["all"].values()) == 10 and len(groups["all"]) == len(us) - 1
    fast.rescore(fam, _with_value(fam, r))
    assert r.value == pytest.approx(10 / (len(us) - 1)) and r.extras["fast_units_missing"] == [
        us[0]
    ]


# ---------------------------------------------------------------- 10. failure states


@pytest.mark.usefixtures("fast_v1")
def test_jailbreak_unserved_control_and_undecided_item():
    jb, ctl = _units(JB, "jailbreak"), _units(JB, "control")
    item_rows = [{"id": u, "kind": "jailbreak", "state": "judged", "flagged": k < 35}
                 for k, u in enumerate(jb)]  # fmt: skip
    item_rows += [{"id": u, "kind": "control", "state": "judged", "flagged": False} for u in ctl]
    item_rows[1] |= {"state": "undecided", "flagged": False}  # digest declined: no outcome
    item_rows[2] |= {"state": "refused", "flagged": False}  # reader declined: no outcome
    item_rows[40] |= {"state": "unjudged", "flagged": False}  # an unjudged positive is a miss
    item_rows[len(jb)] |= {"state": "no_readouts", "flagged": True}  # an unserved control: flagged
    item_rows[len(jb) + 1] |= {"state": "unjudged", "flagged": True}
    r = _result(JB, rows=[{"id": "a-cell-row"}], extras={"item_rows": item_rows})
    groups, sign = fast.units(JB, r)
    assert sign == {"jailbreak": 1.0, "control": -1.0}
    assert len(groups["jailbreak"]) == 68 and len(groups["control"]) == 85
    assert groups["control"][ctl[0]] == 1.0 and groups["jailbreak"][jb[40]] == 0.0
    fast.rescore(JB, _with_value(JB, r))
    assert r.value == pytest.approx(33 / 68 - 2 / 85) and r.n_items == 153
    assert r.extras["fast_units_missing"] == sorted(jb[1:3]) and r.complete is True
    lo, hi = r.ci95
    assert lo < r.value < hi
    # one kind only (a controls-only file): no value
    only = _result(JB, extras={"item_rows": [x for x in item_rows if x["kind"] == "control"]})
    fast.rescore(JB, only)
    assert only.value is None and only.ci95 is None and only.complete is False


def test_directed_modulation_unjudged_row_has_no_outcome():
    us = _units("directed_modulation")
    rows = [{"item": u, "judged": True, "pick": "gold", "voided": False} for u in us[:20]]
    rows += [{"item": u, "judged": True, "pick": "cannot_tell", "voided": False} for u in us[20:]]
    rows[21] = {"item": us[21], "judged": False}  # unjudged, no gold pick: undecided, never 0.0
    rows[22] = {"item": us[22], "judged": True, "pick": "gold", "voided": True}  # no pick
    rows.append({"item": us[0], "judged": False})  # unjudged beside a gold pick: still a pass
    del rows[23]  # an entry item with no row (every cell blank): a fail, as in the family
    r = _result("directed_modulation", rows)
    groups, _ = fast.units("directed_modulation", r)
    assert us[21] not in groups["all"] and groups["all"][us[0]] == 1.0
    assert groups["all"][us[22]] == 0.0 and groups["all"][us[23]] == 0.0
    fast.rescore("directed_modulation", _with_value("directed_modulation", r))
    assert r.value == pytest.approx(20 / 61) and r.extras["fast_units_missing"] == [us[21]]


def test_moral_one_side_missing_scores_zero():
    us = _units("moral_rationale")
    d = {"reason_class": "deliberative", "majority": "pass"}
    c = {"reason_class": "committed", "side": "committed"}
    rows = [
        {"id": us[0], **d, "side": "yes"},
        {"id": us[0], **d, "side": "no"},  # both sides pass
        {"id": us[1], **d, "side": "yes"},  # the no side's row is missing: 0.0
        {"id": us[2], **d, "side": "yes"},
        {"id": us[2], **d, "side": "no", "majority": "fail"},
        {"id": us[3], **c, "majority": "pass"},
        {"id": us[4], **c, "majority": "fail"},
    ]  # us[5] has no row at all: 0.0; us[6] is undecided
    r = _result("moral_rationale", rows, extras={"undecided_ids": [us[6]]})
    got = fast.units("moral_rationale", r)[0]["all"]
    assert [got[u] for u in us[:6]] == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0] and us[6] not in got
    assert len(got) == len(us) - 1


def test_default_family_rowless_item_is_missing_not_a_fail():
    us = _units("wrong_intermediate")
    rows = [{"id": u, "pass": True} for u in us[1:]]
    r = _with_value("wrong_intermediate", _result("wrong_intermediate", rows))
    fast.rescore("wrong_intermediate", r)
    assert r.value == 1.0 and r.n_items == len(us) - 1 and r.complete is True
    assert r.extras["fast_units_missing"] == [us[0]]


def test_role_bound_pairs_fold_both_directions():
    us = _units("role_bound_association")
    rows = [{"id": f"{u}-{d}", "pass": True} for u in us for d in ("ab", "ba")]
    rows[0]["pass"] = False  # one direction fails: the pair fails
    del rows[3]  # one direction absent: the pair is undecided
    r = _with_value("role_bound_association", _result("role_bound_association", rows))
    fast.rescore("role_bound_association", r)
    assert r.value == pytest.approx(43 / 44) and r.extras["fast_units_missing"] == [us[1]]


def test_rescore_guard_fires_on_a_doctored_value():
    us = _units("poetry")
    rows = [{"id": u, "pass": k < 20} for k, u in enumerate(us)]
    r = _result("poetry", rows, value=0.9)  # the family's own value does not match its rows
    fast.rescore("poetry", r)
    assert r.complete is False
    assert r.extras["fast_rescore_mismatch"] == {"family_value": 0.9, "units_value": 0.25}
    assert r.value == 0.25 and r.extras["fast_family_value"] == 0.9  # the rescore still proceeds
    # nyt_connections: the family value covers more units than the entry; computed before the
    # filtering, the guard still holds
    us = _units("nyt_connections")
    rows = [{"id": u, "pass": False} for u in us] + [
        {"id": f"x|s{k}", "pass": True} for k in range(22)
    ]
    r = _with_value("nyt_connections", _result("nyt_connections", rows))
    fast.rescore("nyt_connections", r)
    assert (r.value, r.extras["fast_family_value"], r.complete) == (0.0, 0.5, True)


# ---------------------------------------------------------------- 8. macro


def test_macro_refuses_mixed_rows_and_names_the_subset():
    rows = [_fast_row("poetry"), _fast_row("basic_readout_st")]
    m = macro(rows)
    assert m["families"] == ["poetry", "basic_readout_st"] and m["fast_subset"] == "fast-v3"
    assert m["value"] == 0.5 and m["excluded"] == []
    with pytest.raises(SystemExit, match="macro: results mix fast and non-fast rows"):
        macro([*rows, _result("user_modeling", value=0.5, n_items=30)])
    with pytest.raises(SystemExit, match="mix fast and non-fast"):  # introspection's own scope
        macro([*rows, _result("introspection", value=0.5, n_items=30, config={"scope": "all"})])
    assert "fast_subset" not in macro([_result("poetry", value=0.5, n_items=30)])


def test_macro_excludes_a_stale_subset_and_keeps_every_other_rule():
    stale = _fast_row("basic_readout_st", fast_subset="fast-v0")
    small = _result("user_modeling", value=1.0, n_items=3, config=_fast_row("poetry").config)
    incomplete = _fast_row("moral_rationale")
    incomplete.complete = False
    other_metric = _fast_row("wrong_intermediate")
    other_metric.metric = "precision"
    m = macro([_fast_row("poetry"), stale, small, incomplete, other_metric])
    assert m["families"] == ["poetry", "user_modeling"]  # no n<20 rule for fast rows
    assert m["excluded"] == [
        {"family": "basic_readout_st", "reason": "stale fast subset (fast-v0)"},
        {"family": "moral_rationale", "reason": "incomplete"},
        {"family": "wrong_intermediate", "reason": "metric"},
    ]


# ---------------------------------------------------------------- 9. completeness, end to end

TOY = "fast_toy"
TOY_IDS = ["t1", "t2", "t3", "t4", "not-fast"]


def _toy_run(args: JudgeArgs) -> FamilyResult:
    """A toy family: one judge call per in-scope item (``run_calls``), pass-rate over them."""
    scope = mcjudge.item_scope([{"id": i} for i in TOY_IDS], args)
    cells, _rep = reads.load(args, TOY, ids=[it["id"] for it in scope])
    calls = [mcjudge.Call(c.key, "system", c.samples[0]) for c in cells]
    from wsbench.cache import Cache
    from wsbench.llm import Spend

    with Cache(args.out / "cells.jsonl") as cache:
        res = mcjudge.run_calls(
            calls,
            schema={"name": "toy"},
            judge=args.judge,
            prompt_version="toy-v1",
            cache=cache,
            spend=Spend(),
            concurrency=1,
            rpm=1e9,
            dry_run=args.dry_run,
        )
    rows = [{"id": c.id, "pass": (res.get(c.key) or {}).get("ok")} for c in cells]
    decided = [r["pass"] for r in rows if r["pass"] is not None]
    return FamilyResult(
        family=TOY,
        metric="pass_rate",
        value=sum(decided) / len(decided) if decided else None,
        ci95=None,
        n_items=len(scope),
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=completeness(
            pinned=args.judge.pinned,
            subset=mcjudge.is_subset(args),
            n_expected=len(scope),
            n_missing=len(scope) - len(cells),
            n_unjudged=len(rows) - len(decided),
            n_empty=0,
        ),
        pinned_instrument=args.judge.pinned,
        config=mcjudge.base_config(args, "toy-v1", aggregate=args.extra.get("aggregate")),
        counts={},
        rows=rows,
    )


@pytest.fixture
def toy(monkeypatch, tmp_path):
    """The toy family registered and frozen into a synthetic fast file: read items t1..t4, of
    which t1..t3 are the scored units (as nyt_connections reads more than it scores)."""
    bank = Path("evals/basic/poetry/items_v5.json")  # never read: the toy's bank_sha is patched
    spec = EvalSpec(TOY, "Toy", "basic", bank, JudgeConfig(), "pass_rate", True, _toy_run)
    registry.FAMILIES[TOY] = spec
    entry = {"bank_sha": "0" * 64, "units": {"all": TOY_IDS[:3]}, "read_ids": TOY_IDS[:4]}
    real_file, files = fast._file, {}

    def file_(version):  # the loader's signature (plan 0094): one file per version, the toy in each
        if version not in files:
            fams = {**real_file(version)["families"], TOY: entry}
            files[version] = {"version": version, "families": fams}
        return files[version]

    monkeypatch.setattr(fast, "_file", file_)
    real_sha = fast.bank_sha
    monkeypatch.setattr(fast, "bank_sha", lambda f: "0" * 64 if f == TOY else real_sha(f))
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: None)  # `run` preflights

    def fake_run_calls(calls, **kw):
        return {c.key: {"ok": c.user == "yes"} for c in calls}

    monkeypatch.setattr(mcjudge, "run_calls", fake_run_calls)
    answers = {"t1": "yes", "t2": "no", "t3": "no", "t4": "yes", "not-fast": "yes"}
    rows = [{"id": i, "layer": 20, "pos": 5, "samples": [a]} for i, a in answers.items()]
    return spec, write_jsonl(tmp_path / f"{TOY}.jsonl", rows)


def test_is_subset_is_false_under_the_fast_scope(mk_args, tmp_path):
    path = write_jsonl(tmp_path / "x.jsonl", [_cell("a", 1)])
    assert not mcjudge.is_subset(mk_args(path, items=["a"], scope=fast.SCOPE))
    assert not mcjudge.is_subset(mk_args(path, items=["a"], scope=ti.SCOPE))
    assert mcjudge.is_subset(mk_args(path, items=["a"]))  # a plain items= run is a subset
    assert mcjudge.is_subset(mk_args(path, items=["a"], scope=fast.SCOPE, limit=1))


def test_fast_judge_end_to_end(toy, tmp_path):
    spec, path = toy
    judge = resolve(spec.judge, flag=None, env={})
    opts = runner.parse_opts([])
    shared = dict(opts)
    r = runner.judge_family(spec, _opts(), path, tmp_path / "fast", judge=judge, opts=opts)
    assert opts == shared  # the shared opts are never mutated
    # the family judged the four read items (1/2) and was rescored on its three units (1/3)
    assert r.extras["fast_family_value"] == 0.5 and r.value == pytest.approx(1 / 3)
    assert r.n_items == 3 and r.extras["fast_n_units"] == 3 and r.extras["fast_units_missing"] == []
    assert r.complete is True and r.pinned_instrument is True
    assert r.config["scope"] == "fast" and r.config["fast_subset"] == "fast-v3"
    assert r.config["items"] == TOY_IDS[:4] and r.config["reads"] == "full"
    assert r.config["prompt_version"] == "toy-v1" and "fast_rule" not in r.config
    assert [row["id"] for row in r.rows] == TOY_IDS[:4]
    stored = read_results(tmp_path / "fast")
    assert stored.value == r.value and stored.config["scope"] == "fast"
    assert macro([stored])["fast_subset"] == "fast-v3" and macro([stored])["families"] == [TOY]
    # without the flag: the whole file, no rescore, no stamp (and items= alone is a subset run)
    full = runner.judge_family(
        spec, _opts(fast=False), path, tmp_path / "full", judge=judge, opts=opts
    )
    assert full.value == pytest.approx(3 / 5) and full.n_items == 5 and full.complete is True
    assert "scope" not in full.config and not any(k.startswith("fast") for k in full.extras)
    sub = _opts(fast=False, items=TOY_IDS[:4])
    part = runner.judge_family(spec, sub, path, tmp_path / "items", judge=judge, opts=opts)
    assert part.value == 0.5 and part.complete is False
    # `opts=fast=1` is not the flag
    typed = runner.parse_opts(["fast=1"])
    same = runner.judge_family(
        spec, _opts(fast=False), path, tmp_path / "opt", judge=judge, opts=typed
    )
    assert (same.value, same.n_items, same.complete) == (full.value, 5, True)
    assert "scope" not in same.config and "fast_subset" not in same.config


def test_fast_stamp_suffix_is_appended_once(toy, tmp_path, monkeypatch):
    spec, path = toy
    cases = [
        ({"kind": "last_n", "n": 60}, "+fast-last_n60"),
        ({"kind": "punct_special"}, "+fast-punct_special"),
    ]
    for rule, tag in cases:
        stamps = {"prompt_version": "pv", "instrument_of_record": "ior"}
        r = _result(TOY, [{"id": "t1", "pass": True}], value=1.0, config=stamps)
        entry = {**fast.subset()[TOY], "positions": rule}
        runner.stamp_fast(TOY, r, entry)
        runner.stamp_fast(TOY, r, entry)
        assert r.config["prompt_version"] == "pv" + tag
        assert r.config["instrument_of_record"] == "ior" + tag
    # end to end: a reduced family's rows carry the rule and the suffix
    fams = fast.subset()
    fams[TOY]["positions"] = {"kind": "last_n", "n": 1}
    judge = resolve(spec.judge, flag=None, env={})
    r = runner.judge_family(
        spec, _opts(), path, tmp_path / "o", judge=judge, opts=runner.parse_opts([])
    )
    assert r.config["prompt_version"] == "toy-v1+fast-last_n1"
    assert json.loads(r.config["fast_rule"]) == {"kind": "last_n", "n": 1}


def test_run_families_skips_what_is_not_in_the_subset(toy, tmp_path, capsys):
    spec, path = toy
    specs = [spec, registry.FAMILIES["typo"], registry.FAMILIES["poetry"]]
    outcomes, code = runner.run_families(
        specs, _opts(dry_run=True), readouts_root=path.parent, out=tmp_path / "out"
    )
    by = {o.family: o for o in outcomes}
    assert code == 0 and by[TOY].status == "ok"
    assert (by["typo"].status, by["typo"].error) == ("skipped", "not in fast-v3")
    assert by["poetry"].status == "skipped" and by["poetry"].error.startswith("no readouts")
    assert "typo: skipped (not in fast-v3)" in capsys.readouterr().out
    # a bank that changed since the freeze fails (exit 2) before any preflight
    fast.subset()[TOY]["bank_sha"] = "1" * 64
    outcomes, code = runner.run_families(
        [spec], _opts(dry_run=True), readouts_root=path.parent, out=tmp_path / "out2"
    )
    assert code == 2 and outcomes[0].status == "failed" and "re-freeze" in outcomes[0].error


# ---------------------------------------------------------------- 7 / 11. CLI


@pytest.mark.usefixtures("fast_v1")
def test_cli_plan_fast(tmp_path, capsys):
    assert main(["plan", "--fast", "families=poetry,agentic_misalignment", f"out={tmp_path}"]) == 0
    rows = [json.loads(x) for x in (tmp_path / "poetry.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == fast.subset()["poetry"]["read_ids"]
    rows = [json.loads(x) for x in (tmp_path / f"{AM}.jsonl").read_text().splitlines()]
    assert len(rows) == 36 and all(r["extra"]["fast"] == "fast-v1" for r in rows)
    assert rows[0]["positions"] == {
        "kind": "fast_of",
        "full": {"kind": "all"},
        "fast": {"kind": "last_n", "n": 60},
    }
    assert reads.plan_sha_rows(rows) == reads.fast_plan_sha(AM)
    capsys.readouterr()
    # a dropped family: exit 2, nothing written
    assert main(["plan", "--fast", "families=poetry,multihop_st", f"out={tmp_path / 'x'}"]) == 2
    assert "multihop_st: not in fast-v1" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
    # fast=False is the plan of record
    assert main(["plan", "fast=False", "families=poetry", f"out={tmp_path / 'z'}"]) == 0
    assert len((tmp_path / "z/poetry.jsonl").read_text().splitlines()) == len(
        readplan.plan("poetry")
    )


def test_cli_plan_fast_all_is_the_22_families(tmp_path, capsys):
    # plan 0109: under fast-v3 the all-families plan fails closed on directed_modulation (its
    # registered bank is no longer the one fast-v3 froze, NOT_REFROZEN); the other 21 plan
    assert main(["plan", "--fast", f"out={tmp_path / 'all'}"]) == 2
    assert f"{DM}: bank changed since fast-v3 was frozen; re-freeze" in capsys.readouterr().err
    assert len(FAMILIES_V3) == 22 and [f for f in FAMILIES_V3 if f != DM] == LIVE_V3
    assert main(["plan", "--fast", f"families={','.join(LIVE_V3)}", f"out={tmp_path}"]) == 0
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == LIVE_V3
    n = sum(len(p.read_text().splitlines()) for p in tmp_path.glob("*.jsonl"))
    assert n == 2160 - DM_READ_ITEMS


def test_cli_judge_fast(toy, tmp_path, capsys):
    _spec, path = toy
    out = tmp_path / "o"
    assert main(["judge", f"family={TOY}", f"readouts={path}", f"out={out}", "--fast"]) == 0
    r = read_results(out)
    assert r.config["scope"] == "fast" and r.value == pytest.approx(1 / 3) and r.complete
    capsys.readouterr()
    assert main(["judge", "family=typo", f"readouts={path}", f"out={out}", "--fast"]) == 2
    assert capsys.readouterr().err.strip() == "typo: not in fast-v3"


@pytest.mark.parametrize(
    "extra",
    [
        ["anti_text_inversion=True"],
        ["layers=each"],
        ["opts=aggregate=native"],
        ["opts=judge=mc"],
        ["opts=judge=regex"],
    ],
)
def test_cli_fast_refused_combinations(toy, tmp_path, capsys, extra):
    _spec, path = toy
    base = [f"family={TOY}", f"readouts={path}", f"out={tmp_path / 'o'}"]
    assert main(["judge", *base, "--fast", *extra]) == 2
    assert "--fast" in capsys.readouterr().err and not (tmp_path / "o").exists()
    run = ["run", f"families={TOY}", f"readouts_root={path.parent}", f"out={tmp_path / 'r'}"]
    assert main([*run, "fast=True", *extra]) == 2
    assert not (tmp_path / "r").exists()


def test_cli_fast_is_an_unknown_key_elsewhere(capsys):
    assert main(["list", "--fast"]) == 2
    assert main(["freeze", "--fast"]) == 2
    capsys.readouterr()
    assert main(["judge", "family=poetry", "readouts=x.jsonl", "--fast", "--show"]) == 0
    assert json.loads(capsys.readouterr().out)["fast"] is True
    assert main(["judge", "family=poetry", "readouts=x.jsonl", "--show"]) == 0
    assert json.loads(capsys.readouterr().out)["fast"] is False


def test_cli_run_fast_all_skips_the_eight_dropped_families(tmp_path, capsys):
    root, out = tmp_path / "readouts", tmp_path / "out"
    root.mkdir()
    argv = ["run", "--fast", "all=True", f"readouts_root={root}", f"out={out}", "dry_run=True"]
    # plan 0109: exit 2, since directed_modulation fails closed under fast-v3 (NOT_REFROZEN)
    assert main(argv) == 2
    text = capsys.readouterr().out
    statuses = json.loads((out / "run.json").read_text())["families"]
    not_fast = {f for f, s in statuses.items() if s.get("error") == "not in fast-v3"}
    assert set(DROPPED_V3) <= not_fast and not not_fast & set(FAMILIES_V3)
    for fam in DROPPED_V3:
        assert f"{fam}: skipped (not in fast-v3)" in text
    # the 22 families are the ones the run goes on to (here: no readouts file for any), except
    # the one whose bank changed since the freeze
    assert {f for f, s in statuses.items() if s["error"].startswith("no readouts")} == set(LIVE_V3)
    assert statuses[DM]["status"] == "failed"
    assert statuses[DM]["error"] == f"{DM}: bank changed since fast-v3 was frozen; re-freeze"


def test_cli_run_fast_judges_and_reports(toy, tmp_path, capsys):
    _spec, path = toy
    out = tmp_path / "out"
    argv = [
        "run",
        "--fast",
        f"families={TOY},typo",
        f"readouts_root={path.parent}",
        f"out={out}",
    ]
    assert main(argv) == 0
    capsys.readouterr()
    assert main(["report", f"dir={out}", "--fast"]) == 0
    text = capsys.readouterr().out
    head = "scope: fast subset fast-v3 (23 families; not comparable with full-bench numbers)"
    assert text.startswith(head) and (out / "summary.md").read_text().startswith(head)
    assert f"| {TOY} † | pass_rate | 0.333 |" in text and "lucky guess" not in text
    assert main(["report", f"dir={out}"]) == 0  # unset, one kind present: the fast table
    assert capsys.readouterr().out.startswith(head)
    assert main(["report", f"dir={out}", "fast=False"]) == 0  # no non-fast row: an empty table
    assert TOY not in capsys.readouterr().out.replace(str(out), "")
    payload_rc = main(["report", f"dir={out}", "--fast", "json=True"])
    payload = json.loads(capsys.readouterr().out)
    assert payload_rc == 0 and payload["macro"]["fast_subset"] == "fast-v3"


def test_cli_report_refuses_a_mix_unless_told(tmp_path, capsys):
    write_results(tmp_path / "poetry", _fast_row("poetry", judge_model="m"))
    write_results(
        tmp_path / "basic_readout_st", _result("basic_readout_st", value=0.25, n_items=30)
    )
    assert main(["report", f"dir={tmp_path}"]) == 2
    err = capsys.readouterr().err
    assert "report: results mix fast and non-fast rows; pass --fast or fast=False" in err
    assert main(["report", f"dir={tmp_path}", "--fast", "floors=False"]) == 0
    text = capsys.readouterr().out
    assert (
        "| poetry |" in text
        and "| basic_readout_st |" not in text
        and "fast subset fast-v3 (22" in text
    )
    assert main(["report", f"dir={tmp_path}", "fast=False", "floors=False"]) == 0
    text = capsys.readouterr().out
    assert "| basic_readout_st |" in text and "| poetry |" not in text and "fast subset" not in text


def test_fast_judge_of_a_real_family_end_to_end(tmp_path, monkeypatch):
    """relational_multihop under --fast, its judge scripted (as the family's own tests do): the
    run is complete, stamped, and carries the rescored value."""
    from summary_fakes import FakeLLM

    from wsbench.evals.anti_bag_of_features.relational_multihop import SPEC, prompts

    golden = json.loads((GOLDEN.parent / "relational_multihop_options_v3.json").read_text())
    ids = fast.subset()["relational_multihop"]["read_ids"]
    won = "rel-s00-a"
    gold_s = "Riley is Avery's landlord's sibling."
    rows = [
        {"id": i, "layer": 36, "pos": 20, "token": "'s", "samples": [gold_s if i == won else "hm"]}
        for i in ids
    ]
    path = write_jsonl(tmp_path / "relational_multihop.jsonl", rows)

    def judge_(system, user, schema):
        assert system == prompts.JUDGE_SYSTEM
        if gold_s in user:
            return {"choice": golden[won]["gold_pos"], "quote": "landlord's sibling"}
        return {"choice": len(golden[won]["shown"]), "quote": ""}

    def dig(user):
        text = gold_s if gold_s in user else "hm"
        key = "landlord's sibling" if gold_s in user else ""
        return {"items": [{"statement": "s", "key": key, "where": "", "evidence": text}]}

    fake = FakeLLM.install(monkeypatch, judge_, digest=dig)
    judge = resolve(SPEC.judge, flag=None, env={})
    opts = runner.parse_opts([])
    r = runner.judge_family(SPEC, _opts(), path, tmp_path / "out", judge=judge, opts=opts)
    assert fake.n("digest") == 100 and r.config["aggregate"] == "summary"
    assert r.complete is True and r.pinned_instrument is True
    assert r.config["scope"] == "fast" and r.config["fast_subset"] == "fast-v3"
    assert r.value == pytest.approx(1 / 100) and r.n_items == 100
    assert r.extras["fast_family_value"] == pytest.approx(1 / 100)
    assert r.extras["fast_n_scored"] == 100 and "fast_rescore_mismatch" not in r.extras
    assert "+fast-" not in r.config["prompt_version"]  # no reduced positions in this family
    assert macro([r])["families"] == ["relational_multihop"]


def test_rescore_keeps_no_value_when_the_family_has_none():
    """Review of PR #476: a family result without a value (a dry run) is never given one."""
    from wsbench import fast
    from wsbench.results import FamilyResult

    e = fast.subset()["relational_multihop"]
    rows = [{"id": u, "pass": True} for u in e["units"]["all"][:5]]
    r = FamilyResult(
        family="relational_multihop",
        complete=False,
        pinned_instrument=True,
        config={},
        n_items=0,
        counts={},
        metric="pass_rate",
        value=None,
        ci95=None,
        chance=None,
        chance_label="",
        higher_is_better=True,
        extras={"n_items_undecided": 100},
        rows=rows,
    )
    fast.rescore("relational_multihop", r)
    assert r.value is None and r.ci95 is None
    assert r.extras["n_items_undecided"] == r.extras["fast_n_units"] - 5
    assert r.extras["fast_family_n_items_undecided"] == 100


def test_cli_fast_items_is_a_partial_run(toy, tmp_path, capsys):
    """Plan 0092 §2c: items= under --fast judges a part of the fast items (a cache warm-up);
    the result is never complete, and an id outside the subset is a usage error."""
    _spec, path = toy
    ids = fast.subset()[TOY]["read_ids"]
    out = tmp_path / "part"
    args = ["judge", f"family={TOY}", f"readouts={path}", f"out={out}", "--fast"]
    assert main([*args, f"items={ids[0]}"]) == 0
    r = read_results(out)
    assert r.config["scope"] == "fast" and not r.complete
    assert r.extras["fast_items_subset"] == 1
    capsys.readouterr()
    assert main([*args, "items=not-a-fast-item"]) == 2
    assert "items= not in fast-v3" in capsys.readouterr().err


# ---------------------------------------------------------------- plan 0094: fast-v3

V1_SHA256 = "8ff8316a39e6fc6181147bbab3af884d2e364df1a887a4a5482c88cc84146a39"
# the fast plan shas of the two families only fast-v1 holds (their `fast_of` rows): nothing else
# catches drift in the retained position-reduction machinery
V1_FAST_PLAN_SHA = {
    JB: "3930f94db18c92d08e7188eb98988ac900a44f24cef19d31a832db815eb54913",
    AM: "8082f236c5340b20dccc2e880ec9da1a9528c620758b1e16a96b25c42f417c61",
}


def test_v2_is_v1_without_the_two_safety_families():
    raw = fast.VERSIONS[V1].read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V1_SHA256  # fast_v1.json is frozen
    v1, v2 = json.loads(raw), json.loads(fast.VERSIONS[V2].read_text(encoding="utf-8"))
    assert list(v2) == list(v1) and (v1["version"], v2["version"]) == (V1, V2)
    assert v2["dropped_families"] == [*v1["dropped_families"], JB, AM]
    assert _now(v2["dropped_families"]) == list(DROPPED_V3)
    assert {
        k: v for k, v in v2.items() if k not in ("version", "dropped_families", "families")
    } == {k: v for k, v in v1.items() if k not in ("version", "dropped_families", "families")}
    want = [f for f in v1["families"] if f not in (JB, AM)]
    assert list(v2["families"]) == want and len(want) == 22  # the same order
    for fam in want:  # entry for entry, key order included
        assert json.dumps(v2["families"][fam]) == json.dumps(v1["families"][fam]), fam
    n_units = sum(len(u) for e in v2["families"].values() for u in e["units"].values())
    n_read = sum(len(e["read_ids"]) for e in v2["families"].values())
    assert (n_units, n_read) == (1823, 2160)
    assert not [f for f, e in v2["families"].items() if "positions" in e]
    # the file's own formatting is v1's
    assert fast.VERSIONS[V2].read_text(encoding="utf-8") == json.dumps(v2, indent=1) + "\n"
    assert raw.decode() == json.dumps(v1, indent=1) + "\n"


def test_subset_versions(monkeypatch):
    assert fast.VERSION == V3 and set(fast.VERSIONS) == {V1, V2, VS1, V3, VS, V4, V5, V6}
    assert not hasattr(fast, "COMPATIBLE")  # per family since 2026-11-20: fast.compatible
    assert fast.KEY_ERA == {
        **{V1: "pre-0101", V2: "pre-0101", VS1: "pre-0101", V3: "0101", VS: "0101"},
        V4: "0101",
        V5: "0101",
        V6: "0101",
    }
    assert not hasattr(fast, "PATH")
    assert fast.subset() is fast.subset(V3) and fast.families() == FAMILIES_V3
    assert sorted(fast.subset(V1)) == FAMILIES_V1 and len(FAMILIES_V1) == 24
    assert set(FAMILIES_V1) - set(FAMILIES_V3) == {JB, AM}
    with pytest.raises(SystemExit, match="unknown fast subset 'fast-v9'"):
        fast.subset("fast-v9")
    monkeypatch.setattr(fast, "VERSION", V1)  # read at call time; the cache is per version
    assert fast.subset() is fast.subset(V1) and fast.families() == FAMILIES_V1
    assert fast.entry(JB)["positions"] == {"kind": "punct_special"}
    monkeypatch.setattr(fast, "VERSION", "fast-v9")
    with pytest.raises(SystemExit, match="unknown fast subset"):
        fast.subset()
    monkeypatch.setattr(fast, "VERSION", V3)
    assert JB not in fast.subset() and AM not in fast.subset()


@pytest.mark.parametrize("fam", STRICT_ATI_FAMILIES)
@pytest.mark.parametrize("version", [V1, V3, VS])
def test_every_version_contains_the_strict_ati_subset_whole(version, fam):
    ati = ti.subset_entry(fam, ti.FROZEN)["ids"]
    e = fast.subset(version)[fam]
    assert ati and set(ati) <= set(e["units"]["all"]) and set(ati) <= set(e["read_ids"])


@pytest.mark.usefixtures("fast_v1")
def test_v1_position_rules_are_still_planned():
    specs = readplan.plan(JB, fast=True)
    assert [s.id for s in specs] == fast.subset(V1)[JB]["read_ids"]
    assert all(s.extra["fast"] == "fast-v1" for s in specs)
    assert {s.positions["kind"] for s in specs} == {"fast_of"}
    assert specs[0].positions["fast"] == {"kind": "punct_special"}
    assert {f: reads.fast_plan_sha(f) for f in (JB, AM)} == V1_FAST_PLAN_SHA


def test_fast_plan_sha_is_the_same_under_both_versions(monkeypatch):
    """A fast-v1 file of a family still in the subset declares the plan_sha fast-v3 wants (a
    family re-frozen since fast-v1 has no fast-v1 plan any more: ``REFROZEN``)."""
    same = [f for f in FAMILIES_V3 if (V1, f) not in SUPERSEDED]
    assert len(same) == len(FAMILIES_V3) - 2  # conjunctive_association, directed_modulation
    v3 = {f: reads.fast_plan_sha(f) for f in same}
    monkeypatch.setattr(fast, "VERSION", V1)
    assert {f: reads.fast_plan_sha(f) for f in same} == v3


@pytest.mark.parametrize("fam", [JB, AM])
def test_the_two_safety_families_are_not_in_fast_v3(fam, tmp_path, capsys, mk_args):
    with pytest.raises(fast.NotInFast) as e:
        fast.entry(fam)
    assert e.value.code == f"{fam}: not in fast-v3"
    with pytest.raises(fast.NotInFast):
        readplan.plan(fam, fast=True)
    root, out = tmp_path / "readouts", tmp_path / "out"
    root.mkdir()
    path = write_jsonl(root / f"{fam}.jsonl", [_cell("a", 1)])
    # a fast-v1 file of theirs never reaches the sidecar's version check
    write_sidecar(path, fast=V1, plan_sha=V1_FAST_PLAN_SHA[fam])
    with pytest.raises(fast.NotInFast):
        reads.load(mk_args(path, scope=fast.SCOPE), fam)
    argv = ["run", "--fast", f"families={fam}", f"readouts_root={root}", f"out={out}"]
    assert main([*argv, "dry_run=True"]) == 0
    assert f"{fam}: skipped (not in fast-v3)" in capsys.readouterr().out
    status = json.loads((out / "run.json").read_text())["families"][fam]
    assert (status["status"], status["error"]) == ("skipped", "not in fast-v3")
    judge = ["judge", f"family={fam}", f"readouts={path}", f"out={tmp_path / 'j'}", "--fast"]
    assert main(judge) == 2
    assert capsys.readouterr().err.strip() == f"{fam}: not in fast-v3"
    assert not (tmp_path / "j").exists()
    assert main(["plan", "--fast", f"families={fam}", f"out={tmp_path / 'p'}"]) == 2
    assert f"{fam}: not in fast-v3" in capsys.readouterr().err


def _fast_poetry_file(tmp_path, declared: str):
    """A FAST poetry file at layer 20 (every fast read item, two positions) declaring a subset."""
    ids = fast.subset()["poetry"]["read_ids"]
    rows = [_cell(i, p) for i in ids for p in (7, 8)]
    path = write_jsonl(tmp_path / "poetry.jsonl", rows)
    write_sidecar(path, fast=declared, plan_sha=reads.fast_plan_sha("poetry"), layers=[20])
    return path, ids


def test_a_fast_v1_sidecar_is_accepted_under_fast_v3(tmp_path, mk_args, capsys):
    for declared in (V1, V3):
        path, ids = _fast_poetry_file(tmp_path, declared)
        args = mk_args(path, scope=fast.SCOPE, layers=[20])
        cells, rep = reads.load(args, "poetry")
        assert len(cells) == 2 * len(ids) and rep.reads_checked == "sidecar"
        assert rep.partial_ids == [] and not reads.incomplete(args)
    path, _ = _fast_poetry_file(tmp_path, "fast-v0")  # any other version: refused, as before
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    err = capsys.readouterr().err
    assert e.value.code == 2 and "another fast subset ('fast-v0', not 'fast-v3')" in err
    # the plan_sha guard is unchanged for a compatible file
    path, _ = _fast_poetry_file(tmp_path, V1)
    write_sidecar(path, fast=V1, plan_sha="0" * 64, layers=[20])
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    assert e.value.code == 2 and "different fast plan" in capsys.readouterr().err
    # and so is the refusal without the flag
    with pytest.raises(SystemExit):
        reads.load(mk_args(path, layers=[20]), "poetry")
    assert "file was produced --fast; judge it with --fast" in capsys.readouterr().err


def test_a_fast_v1_file_is_judged_under_fast_v3(toy, tmp_path, capsys, monkeypatch):
    spec, path = toy
    spec = dataclasses.replace(spec, min_full_positions=1)  # the toy file reads one position
    monkeypatch.setitem(registry.FAMILIES, TOY, spec)
    judge = resolve(spec.judge, flag=None, env={})

    def run(out):
        return runner.judge_family(
            spec, _opts(), path, tmp_path / out, judge=judge, opts=runner.parse_opts([])
        )

    plain = run("plain")
    write_sidecar(path, fast=V1)
    r = run("declared-v1")
    assert r.value == plain.value == pytest.approx(1 / 3) and r.complete is True
    assert r.config["fast_subset"] == "fast-v3" and r.config["reads_checked"] == "sidecar"
    assert r.rows == plain.rows
    write_sidecar(path, fast="fast-v0")
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        run("declared-v0")
    assert e.value.code == 2 and "another fast subset" in capsys.readouterr().err


def test_a_produced_fast_file_declares_fast_v3(tmp_path):
    from wsbench.produce.methods import Readout
    from wsbench.produce.producer import Producer, Row
    from wsbench.readouts import read_sidecar

    class Fake(Producer):
        def read_spec(self, spec, *, layers=None):
            return [Row(spec.id, 36, 0, "t", Readout(samples=["x"]))]

    out = tmp_path / "poetry.jsonl"
    p = Fake(backend=None, method=SimpleNamespace(name="fake", layers=None))  # type: ignore[arg-type]
    p.run_family("poetry", out, fast=True)
    meta = read_sidecar(out)
    assert meta["fast"] == "fast-v3" and meta["plan_sha"] == reads.fast_plan_sha("poetry")
    ids = [json.loads(x)["id"] for x in out.read_text().splitlines()]
    assert ids == fast.subset()["poetry"]["read_ids"]


def test_macro_keeps_compatible_rows_of_in_subset_families():
    """Plan 0094: a fast-v1 results directory reports a fast-v3 macro over its 22 families."""
    old = [_fast_row(f, fast_subset=V1) for f in ("poetry", "basic_readout_st")]
    old_jb, old_am = _fast_row(JB, fast_subset=V1), _fast_row(AM, fast_subset=V1)
    m = macro([*old, old_jb, old_am])
    assert m["families"] == ["poetry", "basic_readout_st"] and m["fast_subset"] == "fast-v3"
    assert m["value"] == 0.5 and m["excluded"] == [
        {"family": JB, "reason": "stale fast subset (fast-v1)"},
        {"family": AM, "reason": "stale fast subset (fast-v1)"},
    ]
    # beside current rows; any other version is excluded as before, whatever the family
    m = macro([*old, _fast_row("user_modeling"), _fast_row("hinted_cutoff", fast_subset="fast-v0")])
    assert m["families"] == ["poetry", "basic_readout_st", "user_modeling"]
    assert m["excluded"] == [{"family": "hinted_cutoff", "reason": "stale fast subset (fast-v0)"}]
    unstamped = _result("poetry", value=0.5, n_items=30, config={"scope": fast.SCOPE})
    assert macro([unstamped])["excluded"] == [
        {"family": "poetry", "reason": "stale fast subset (None)"}
    ]
    # the other rules still apply to a compatible row; fast and non-fast rows never mix
    incomplete = _fast_row("moral_rationale", fast_subset=V1)
    incomplete.complete = False
    assert macro([*old, incomplete])["excluded"] == [
        {"family": "moral_rationale", "reason": "incomplete"}
    ]
    with pytest.raises(SystemExit, match="macro: results mix fast and non-fast rows"):
        macro([*old, _result("user_modeling", value=0.5, n_items=30)])


def test_cli_report_of_a_fast_v1_directory(tmp_path, capsys):
    for fam in ("poetry", "basic_readout_st", JB):
        write_results(tmp_path / fam, _fast_row(fam, fast_subset=V1))
    assert main(["report", f"dir={tmp_path}", "--fast", "json=True"]) == 0
    m = json.loads(capsys.readouterr().out)["macro"]
    assert m["fast_subset"] == "fast-v3" and sorted(m["families"]) == ["basic_readout_st", "poetry"]
    assert m["excluded"] == [{"family": JB, "reason": "stale fast subset (fast-v1)"}]
    assert main(["report", f"dir={tmp_path}", "--fast"]) == 0
    text = capsys.readouterr().out
    assert text.startswith(
        "scope: fast subset fast-v3 (22 families; not comparable with full-bench numbers); "
        "rows of other subsets are excluded\n"
    )
    assert "stale fast subset (fast-v1)" in text


def test_a_fast_v1_cache_replays_under_fast_v3(toy, tmp_path, monkeypatch):
    """The same calls under both versions: a cache written with ``fast.VERSION`` = fast-v1
    answers a fast-v3 run with no new call, and the value is the same."""
    spec, path = toy
    asked: list[tuple[str, str]] = []

    def stream_json(prompts, *, on_result, **_kw):
        for i, (system, user) in enumerate(prompts):
            asked.append((system, user))
            on_result(i, {"ok": user == "yes"})
        return llm.Spend()

    monkeypatch.setattr(mcjudge, "run_calls", REAL_RUN_CALLS)  # the real cache path
    monkeypatch.setattr(llm, "stream_json", stream_json)
    judge = resolve(spec.judge, flag=None, env={})
    out = tmp_path / "out"
    monkeypatch.setattr(fast, "VERSION", V1)
    old = runner.judge_family(spec, _opts(), path, out, judge=judge, opts=runner.parse_opts([]))
    assert len(asked) == 4 and old.config["fast_subset"] == "fast-v1"
    monkeypatch.setattr(fast, "VERSION", V3)
    new = runner.judge_family(spec, _opts(), path, out, judge=judge, opts=runner.parse_opts([]))
    assert len(asked) == 4  # 0 new calls
    assert new.config["fast_subset"] == "fast-v3" and new.value == old.value == pytest.approx(1 / 3)
    assert new.rows == old.rows and new.config["prompt_version"] == old.config["prompt_version"]
    differ = {k for k in {*old.config, *new.config} if old.config.get(k) != new.config.get(k)}
    assert differ == {"fast_subset"}


# ---------------------------------------------------------------- plan 0095: fast-safety-v2

V2_SHA256 = "f82e48933602a9618e6826a315469b9edb421d88d5d37d3d26867c4ef725abe8"
VS1_SHA256 = "894a26ca6655e5b355241a62f0e82c578c7eedef0d82d10bbe7e3ec653ac257b"
# the two position-reduced families' own fast-safety-v2 plan shas (their rows say
# `extra.fast = "fast-safety-v2"`, so they differ from V1_FAST_PLAN_SHA and from the shas the
# same rows had as fast-safety-v1's plan, which a fast-safety-v1 sidecar still declares)
VS_FAST_PLAN_SHA = {
    JB: "4579d4bfbd312d9f7fbae415156840de09e3dda39334724fceab81aa10250ff3",
    AM: "eb0c3ba96b0ba09cc6c0dcd938a65dbff09a13715c1ba82d0765217e5966a938",
}
VS1_FAST_PLAN_SHA = {
    JB: "77dcf110e63d44cdb3ebeffaa02b4efa36b80faec7bb72285d574d9f4798640e",
    AM: "7068e8862a5e10b847c1d130d94dd224655f97c326aa2143dfc8af7192bfb6ea",
}


@pytest.fixture
def fast_safety():
    """``fast-safety-v2`` as the active subset (``conftest`` restores the default)."""
    assert fast.use(VS) == VS


class FakeText:
    """``llm.stream_text`` stand-in for agentic's Stage C: every call answers ``nothing``."""

    def __init__(self):
        self.n = 0

    def __call__(self, prompts_, *, on_result, **_kw):
        for i, _user in enumerate(prompts_):
            self.n += 1
            on_result(i, "nothing")
        return llm.Spend()


def _safety_fakes(monkeypatch):
    """Offline judges for the two safety families: a passive digest, jailbreak's item question
    answered ``no``, agentic's Stage C text."""
    from summary_fakes import FakeLLM

    monkeypatch.setattr(llm, "count_tokens", lambda model, ps, concurrency=8: [10] * len(ps))
    answer = {"answer": "no", "quotes": [], "rationale": ""}
    fake = FakeLLM.install(monkeypatch, lambda s, u, sc: dict(answer))
    text = FakeText()
    monkeypatch.setattr(llm, "stream_text", text)
    return fake, text


def _am_readouts(path: Path) -> Path:
    """A sidecar-less agentic file at layer 20: 60 positions of every fast read item."""
    ids = fast.subset(VS)[AM]["read_ids"]
    return write_jsonl(path, [_cell(i, 500 + p, None) for i in ids for p in range(60)])


def _jb_readouts(path: Path) -> Path:
    """A sidecar-less jailbreak file at layer 20: every bank position of every fast read item,
    with the bank's own tokens (the family checks them)."""
    bank = json.loads(registry.frozen_bank_path(JB).read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in bank["items"]}
    rows = [
        _cell(i, int(p), t)
        for i in fast.subset(VS)[JB]["read_ids"]
        for p, t in by_id[i]["read"]["tokens"].items()
    ]
    return write_jsonl(path, rows)


def _fast_jb_file(tmp_path, **meta):
    """A FAST jailbreak file at layer 20 (two positions of every fast read item) and a sidecar."""
    ids = fast.subset(VS)[JB]["read_ids"]
    path = write_jsonl(tmp_path / "jb.jsonl", _jb_rows({i: [".", "x"] for i in ids}))
    write_sidecar(path, layers=[20], **meta)
    return path, ids


def test_safety_file_is_v1_under_its_own_name():
    raw = {v: fast.VERSIONS[v].read_bytes() for v in (V1, V2, VS1)}
    shas = {v: hashlib.sha256(b).hexdigest() for v, b in raw.items()}
    assert shas == {V1: V1_SHA256, V2: V2_SHA256, VS1: VS1_SHA256}  # all three frozen
    v1, v2, vs = (json.loads(raw[v]) for v in (V1, V2, VS1))
    # the file differs from fast_v1.json in the version value only (same serialization)
    assert vs["version"] == VS1 and raw[VS1] == raw[V1].replace(b'"fast-v1"', b'"fast-safety-v1"')
    assert raw[V1].count(b'"fast-v1"') == 1
    assert list(vs) == list(v1) and {**vs, "version": V1} == v1
    assert _now(vs["dropped_families"]) == list(DROPPED)
    assert list(vs["families"]) == list(v1["families"])
    # fast-v2's 22 entries plus fast-v1's two, entry for entry, key order included
    assert set(vs["families"]) == {*v2["families"], JB, AM} and len(vs["families"]) == 24
    for fam, e in vs["families"].items():
        src = v1 if fam in (JB, AM) else v2
        assert json.dumps(e) == json.dumps(src["families"][fam]), fam
    n_units = sum(len(u) for e in vs["families"].values() for u in e["units"].values())
    n_read = sum(len(e["read_ids"]) for e in vs["families"].values())
    assert (n_units, n_read) == (1996, 2351)
    assert {f: e["positions"] for f, e in vs["families"].items() if "positions" in e} == {
        JB: {"kind": "punct_special"},
        AM: {"kind": "last_n", "n": 60},
    }
    assert len(vs["families"][JB]["read_ids"]) == 155 and len(vs["families"][AM]["read_ids"]) == 36


# sha256 of the two files cut on 2026-11-20 (`scripts/fast_refreeze_bank.py`): frozen like the rest
V3_SHA256 = "4a58b249a68b8aefb3a58162704063182607827cdebf454be19be18a0eae063a"
VS_SHA256 = "19cde720531d6ae6a68ecd6be099249aad73bd230b3a0b421661f9c0fc06aadc"


@pytest.mark.parametrize(("old", "new", "new_sha"), [(V2, V3, V3_SHA256), (VS1, VS, VS_SHA256)])
def test_a_refrozen_version_is_its_predecessor_with_only_the_refrozen_bank_sha(
    old, new, new_sha, monkeypatch
):
    """fast-v3 / fast-safety-v2 = fast-v2 / fast-safety-v1 in today's family keys, with ONLY
    conjunctive_association's ``bank_sha`` moved (bank v6): units, read ids, the family order and
    every other entry are the predecessor's bytes."""
    raw = fast.VERSIONS[new].read_bytes()
    assert hashlib.sha256(raw).hexdigest() == new_sha
    a = json.loads(fast.VERSIONS[old].read_text(encoding="utf-8"))
    b = json.loads(raw)
    assert raw.decode() == json.dumps(b, indent=1) + "\n"
    assert list(b) == list(a) and b["version"] == new and b["subject"] == a["subject"]
    assert b["dropped_families"] == _now(a["dropped_families"])  # written in today's keys
    assert list(b["families"]) == _now(a["families"])  # the same order
    changed = []
    for was, now in zip(a["families"], b["families"], strict=True):
        if json.dumps(a["families"][was]) != json.dumps(b["families"][now]):
            changed.append(now)
    assert changed == [CONJ] == [f for f, versions in REFROZEN.items() if old in versions]
    e_old, e_new = a["families"][CONJ], b["families"][CONJ]
    assert list(e_new) == list(e_old) and {**e_new, "bank_sha": e_old["bank_sha"]} == e_old
    assert e_new["bank_sha"] == fast.bank_sha(CONJ) and len(e_new["read_ids"]) == 98
    # the script that cut the file reproduces it, with every family on the bank it had at the
    # cut: directed_modulation was on items.json then (plan 0109 registered items_v2.json later,
    # NOT_REFROZEN; the script refuses a cut that leaves a changed bank unnamed)
    then = registry.family_rel(DM) / "items.json"
    monkeypatch.setitem(
        registry.FAMILIES, DM, dataclasses.replace(registry.FAMILIES[DM], bank=then)
    )
    assert fast.bank_sha(DM) == a["families"][DM]["bank_sha"] == b["families"][DM]["bank_sha"]
    spec = importlib.util.spec_from_file_location(
        "fast_refreeze_bank", ROOT / "scripts/fast_refreeze_bank.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.build(old, new, [CONJ]) == raw.decode()
    # the family's plan rows of its read ids are the same on the bank the old version froze
    # (found by its sha: items_v4.json) and on the registered one; an unknown old bank refuses
    before, after = mod.plan_shas(old, CONJ)
    assert before == after and len(after) == 64
    assert mod.old_bank(old, CONJ).name == "items_v4.json"
    # a bank change that moves the plan rows of the read ids is refused unless allowed
    real = mod.plan_shas
    mod.plan_shas = lambda *a: ("a" * 64, "b" * 64)
    try:
        with pytest.raises(SystemExit, match="read differently on the new bank"):
            mod.build(old, new, [CONJ])
        assert mod.build(old, new, [CONJ], allow_plan_change=True) == raw.decode()
    finally:
        mod.plan_shas = real
    with pytest.raises(SystemExit, match="no file with the sha256"):
        mod.old_bank(old, CONJ, given=ROOT / "evals/fast/README.md")
    with pytest.raises(SystemExit, match="exists: a frozen file is never edited"):
        mod.main([old, new, CONJ])
    with pytest.raises(SystemExit, match="poetry: its registered bank is the one"):
        mod.build(old, "fast-v9", [CONJ, "poetry"])
    with pytest.raises(SystemExit, match=f"{CONJ}: its registered bank changed since"):
        mod.build(old, "fast-v9", [])


def test_versions_are_entry_compatible_per_family():
    """Plans 0094 / 0095, per family since 2026-11-20: two versions are compatible for a family
    iff both hold it with the identical entry. Every family is compatible across all five files
    except the ones a re-freeze moved (``REFROZEN``), which split at that re-freeze."""
    files = {v: fast.subset(v) for v in OUTCOME_SELECTED}  # fast-v4 / -v5: test_fast_core_half.py
    assert set(files) == {V1, V2, VS1, V3, VS} == set(fast.VERSIONS) - CORE_HALF
    for a in files:
        for b in files:
            for fam in set(files[a]) | set(files[b]):
                both = fam in files[a] and fam in files[b]
                same = both and json.dumps(files[a][fam]) == json.dumps(files[b][fam])
                assert fast.compatible(a, fam, against=b) == same, (a, b, fam)
                old = REFROZEN.get(fam, ())
                assert same == (both and (a in old) == (b in old)), (a, b, fam)
    assert not fast.compatible("fast-v0", "poetry") and not fast.compatible(None, "poetry")
    assert not fast.compatible(V1, "poetry", against="fast-v0")
    assert fast.compatible(V1, "poetry") and fast.compatible(VS1, "poetry", against=VS)
    assert not fast.compatible(V2, JB, against=VS) and fast.compatible(V1, JB, against=VS)
    assert set(fast.subset(VS)) >= set(fast.subset(V3))
    assert set(fast.VARIANTS.values()) <= set(fast.VERSIONS)
    # the last outcome-selected versions and the selectable one hold every family on its
    # registered bank
    # registered bank, except a family whose bank changed with no re-freeze (NOT_REFROZEN)
    for v in (V3, VS, *fast.VARIANTS.values()):
        stale = [f for f, e in fast.subset(v).items() if e["bank_sha"] != fast.bank_sha(f)]
        assert stale == [f for f, versions in NOT_REFROZEN.items() if v in versions], v
    assert all(DM not in fast.subset(v) for v in fast.VARIANTS.values())


def test_a_refrozen_family_is_stale_under_the_old_stamp_and_the_others_are_not(
    tmp_path, mk_args, capsys
):
    """2026-11-20: what the re-freeze means for existing fast results and readouts files. A
    conjunctive_association RESULT row of fast-v1 / fast-v2 / fast-safety-v1 is stale under
    fast-v3 / fast-safety-v2 (its instrument changed: re-judge); its FAST readouts files are
    still judged (same reads); every other family's old rows and files are accepted as before."""
    from wsbench.results import _stale_fast_subset

    def row(fam: str, v: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(family=fam, config={"fast_subset": v})

    for active in (V3, VS):
        now = fast.use(active)
        for old in (V1, V2, VS1):
            assert _stale_fast_subset(row(CONJ, old))
            assert not _stale_fast_subset(row("poetry", old))
            assert not _stale_fast_subset(row("user_modeling", old))
        assert not _stale_fast_subset(row(CONJ, V3 if now == VS else VS))  # the other new one
        assert not _stale_fast_subset(row(CONJ, now))
    fast.use(V3)
    m = macro([_fast_row("poetry", fast_subset=V2), _fast_row(CONJ, fast_subset=V2)])
    assert m["families"] == ["poetry"] and m["fast_subset"] == V3
    assert m["excluded"] == [{"family": CONJ, "reason": "stale fast subset (fast-v2)"}]
    # a FAST readouts file of the family declaring an older version IS judged: the readouts are
    # what the active plan asks for (same read ids, same positions, the same fast plan sha under
    # every version); only its result rows are another instrument's (above)
    ids = fast.subset()[CONJ]["read_ids"]
    sha = reads.fast_plan_sha(CONJ)
    path = write_jsonl(tmp_path / "conj.jsonl", [_cell(i, p) for i in ids for p in range(19)])
    for declared in (V1, V2, VS1, V3, VS):
        assert fast.same_reads(declared, CONJ) and reads.fast_plan_sha(CONJ, declared) == sha
        write_sidecar(path, fast=declared, plan_sha=sha, layers=[20])
        cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), CONJ)
        assert len(cells) == 19 * len(ids) and rep.reads_checked == "sidecar"
        # without a plan_sha nothing ties the file to the active plan: accepted only when the
        # declared version froze the same bank (fast-v3 / fast-safety-v2), refused across the
        # bank change (`same_reads` compares frozen entries, not plans)
        write_sidecar(path, fast=declared, layers=[20])
        if declared in (V3, VS):
            cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), CONJ)
            assert len(cells) == 19 * len(ids)
        else:
            with pytest.raises(SystemExit) as e:
                reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), CONJ)
            err = capsys.readouterr().err
            assert e.value.code == 2 and "without a plan_sha" in err
            assert f"{CONJ}'s bank changed since that version" in err
        write_sidecar(path, fast=declared, plan_sha="0" * 64, layers=[20])  # the sha guard holds
        with pytest.raises(SystemExit):
            reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), CONJ)
        assert "different fast plan" in capsys.readouterr().err
    # a safety family's fast-safety-v1 file, with the sha it was produced under, is still good
    fast.use(VS)
    jb, jb_ids = _fast_jb_file(tmp_path, fast=VS1, plan_sha=VS1_FAST_PLAN_SHA[JB])
    cells, rep = reads.load(mk_args(jb, scope=fast.SCOPE, layers=[20]), JB)
    assert len(cells) == len(jb_ids) and rep.reads_checked == "sidecar"
    assert reads.fast_plan_sha(JB, declared=VS1) == VS1_FAST_PLAN_SHA[JB]


def test_same_reads_is_read_ids_and_positions_never_bank_or_units(monkeypatch):
    """``fast.same_reads`` (readouts files) against ``fast.compatible`` (result rows), on a
    synthetic version: another ``bank_sha`` or other units keep the reads, other read ids or
    another positions rule do not; ``compatible`` is false for all four."""
    real = fast._file
    base = real(VS)["families"]

    def variant(fam: str, **change) -> None:
        fams = {**base, fam: {**base[fam], **change}}
        monkeypatch.setitem(fast.VERSIONS, "fast-vx", fast.VERSIONS[VS])
        monkeypatch.setattr(
            fast, "_file", lambda v: {"families": fams} if v == "fast-vx" else real(v)
        )

    fast.use(VS)
    for fam in ("poetry", JB, AM):
        e = base[fam]
        variant(fam, bank_sha="0" * 64)
        assert fast.same_reads("fast-vx", fam) and not fast.compatible("fast-vx", fam)
        variant(fam, units={g: u[:-1] for g, u in e["units"].items()})
        assert fast.same_reads("fast-vx", fam) and not fast.compatible("fast-vx", fam)
        variant(fam, read_ids=e["read_ids"][:-1])
        assert not fast.same_reads("fast-vx", fam) and not fast.compatible("fast-vx", fam)
        with pytest.raises(SystemExit, match="reads other items or positions"):
            reads.fast_plan_sha(fam, declared="fast-vx")
        variant(fam, positions={"kind": "last_n", "n": 7})
        assert not fast.same_reads("fast-vx", fam)
    assert not fast.same_reads("fast-v0", "poetry") and not fast.same_reads(V3, JB)
    assert not fast.same_reads(VS, "typo")  # in neither file


def test_a_refused_fast_file_reads_other_items(tmp_path, mk_args, capsys, monkeypatch):
    real = fast._file
    fams = dict(real(V3)["families"])
    fams["poetry"] = {**fams["poetry"], "read_ids": fams["poetry"]["read_ids"][:-1]}
    monkeypatch.setitem(fast.VERSIONS, "fast-vx", fast.VERSIONS[V3])
    monkeypatch.setattr(fast, "_file", lambda v: {"families": fams} if v == "fast-vx" else real(v))
    path, _ = _fast_poetry_file(tmp_path, "fast-vx")
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    err = capsys.readouterr().err
    assert e.value.code == 2 and "poetry reads other items or positions there" in err


def test_files_of_the_frozen_predecessors_load_under_the_new_defaults(tmp_path, mk_args):
    """An unchanged family's FAST file declaring fast-v2 under ``--fast``, and an agentic FAST
    file declaring fast-safety-v1 (with the sha that version's plan had) under
    ``--fast-safety``: judged as they are."""
    assert fast.VERSION == V3
    for declared in (V2, V1, VS1):
        path, ids = _fast_poetry_file(tmp_path, declared)
        cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
        assert len(cells) == 2 * len(ids) and rep.reads_checked == "sidecar"
        assert reads.fast_plan_sha("poetry", declared=declared) == reads.fast_plan_sha("poetry")
    fast.use(VS)
    for declared, shas in ((VS1, VS1_FAST_PLAN_SHA), (V1, V1_FAST_PLAN_SHA)):
        path, ids = _fast_am_file(tmp_path, fast=declared, plan_sha=shas[AM])
        cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), AM)
        assert len(cells) == 60 * len(ids) and rep.reads_checked == "sidecar"
        assert json.loads(rep.fast_rule) == {"kind": "last_n", "n": 60}


def test_select_and_use():
    """Plan 0104 (fast-v6 since plan 0114): the default is the only selectable subset;
    ``--fast-safety`` (``select("safety")``) is retired with a message; ``use`` activates any
    registered version (``report fast_version=``), which is how the frozen predecessors are
    still read."""
    assert fast.DEFAULT == V6 and fast.VARIANTS == {"": V6}
    with pytest.raises(ValueError, match=r"--fast-safety is retired \(plan 0104\)"):
        fast.select("safety")
    assert fast.VERSION == V3  # this file's fixture; a refused select changes nothing
    assert fast.use(VS) == VS == fast.VERSION
    assert fast.subset() is fast.subset(VS) and fast.families() == FAMILIES_V1
    assert fast.entry(JB)["positions"] == {"kind": "punct_special"}
    assert fast.select("") == V6 == fast.VERSION and fast.select() == V6
    with pytest.raises(ValueError, match=r"unknown fast variant 'v1' \(known: ''\)"):
        fast.select("v1")  # fast-v1 is not selectable
    with pytest.raises(ValueError, match="unknown fast subset 'fast-v9'"):
        fast.use("fast-v9")
    assert fast.VERSION == V6
    fast.use(VS)  # left active: the next test starts on its own subset all the same


def test_every_test_starts_on_the_default_subset(_the_frozen_predecessors):
    """The conftest reset: the test before this one leaves ``fast-safety-v2`` active
    (``test_select_and_use``), and this one's setup still found the default. Only then does
    this file's fixture make fast-v3 active."""
    assert _the_frozen_predecessors == fast.DEFAULT == V6 and fast.VERSION == V3


def test_cli_plan_fast_safety(tmp_path, capsys):
    fast.use(VS)  # plan 0104: the retired --fast-safety, made active directly
    # plan 0109: the all-families plan fails closed on directed_modulation (NOT_REFROZEN)
    assert main(["plan", "--fast", f"out={tmp_path / 'all'}"]) == 2
    assert f"{DM}: bank changed since {VS} was frozen; re-freeze" in capsys.readouterr().err
    fast.use(VS)
    assert main(["plan", "--fast", f"families={','.join(LIVE_VS)}", f"out={tmp_path}"]) == 0
    assert fast.VERSION == VS
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == LIVE_VS
    assert len(FAMILIES_V1) == 24 and [f for f in FAMILIES_V1 if f != DM] == LIVE_VS
    n_rows = sum(len(p.read_text().splitlines()) for p in tmp_path.glob("*.jsonl"))
    assert n_rows == 2351 - DM_READ_ITEMS
    for fam, rule in ((JB, {"kind": "punct_special"}), (AM, {"kind": "last_n", "n": 60})):
        rows = [json.loads(x) for x in (tmp_path / f"{fam}.jsonl").read_text().splitlines()]
        assert [r["id"] for r in rows] == fast.subset(VS)[fam]["read_ids"]
        assert all(r["extra"]["fast"] == VS for r in rows)
        assert all(r["positions"]["kind"] == "fast_of" for r in rows)
        assert rows[0]["positions"]["fast"] == rule
        # its own sha, and the sha the same rows had as fast-v1's plan
        assert reads.plan_sha_rows(rows) == reads.fast_plan_sha(fam) == VS_FAST_PLAN_SHA[fam]
        assert reads.fast_plan_sha(fam, declared=VS) == VS_FAST_PLAN_SHA[fam]
        as_v1 = [{**r, "extra": {**r["extra"], "fast": V1}} for r in rows]
        assert reads.plan_sha_rows(as_v1) == V1_FAST_PLAN_SHA[fam]
        assert reads.fast_plan_sha(fam, declared=V1) == V1_FAST_PLAN_SHA[fam]
        assert VS_FAST_PLAN_SHA[fam] != V1_FAST_PLAN_SHA[fam]
    # a family without a positions rule: one sha whatever the declared version
    assert len({reads.fast_plan_sha("poetry", declared=v) for v in (None, V1, V3, VS)}) == 1
    for declared in (V3, "fast-v0"):  # not that version's family / not a compatible version
        with pytest.raises(SystemExit) as e:
            reads.fast_plan_sha(JB, declared=declared)
        assert e.value.code == f"{JB}: not in fast subset {declared}"
    capsys.readouterr()
    fast.use(VS)  # plan 0104: the retired --fast-safety, made active directly
    assert main(["plan", "--fast", "families=multihop_st", f"out={tmp_path / 'x'}"]) == 2
    assert "multihop_st: not in fast-safety-v2" in capsys.readouterr().err


def test_fast_plan_sha_declared_under_fast_v1(fast_v1):
    """The mirror: under fast-v1 the safety version's sha is the declared one."""
    for fam in (JB, AM):
        assert reads.fast_plan_sha(fam) == V1_FAST_PLAN_SHA[fam]
        assert reads.fast_plan_sha(fam, declared=VS) == VS_FAST_PLAN_SHA[fam]


@pytest.mark.parametrize(
    ("fam", "suffix", "n_items"),
    [(JB, "+fast-punct_special", 155), (AM, "+fast-last_n60", 18)],
)
def test_cli_judge_fast_safety_of_the_two_safety_families(
    fam, suffix, n_items, tmp_path, capsys, monkeypatch
):
    fake, text = _safety_fakes(monkeypatch)
    make = _jb_readouts if fam == JB else _am_readouts
    path = make(tmp_path / f"{fam}.jsonl")
    out = tmp_path / "o"
    fast.use(VS)  # plan 0104: the retired --fast-safety, made active directly
    assert main(["judge", f"family={fam}", f"readouts={path}", f"out={out}", "--fast"]) == 0
    r = read_results(out)
    assert r.config["scope"] == "fast" and r.config["fast_subset"] == VS
    assert r.config["prompt_version"].endswith(suffix) and r.config["aggregate"] == "summary"
    assert json.loads(r.config["fast_rule"]) == fast.subset(VS)[fam]["positions"]
    assert r.complete is True and r.value == 0.0 and r.n_items == n_items
    assert r.config["items"] == fast.subset(VS)[fam]["read_ids"]
    assert fake.n("digest") > 0 and (text.n == 36 if fam == AM else fake.n("item_recognition") > 0)
    assert macro([r])["families"] == [fam] and macro([r])["fast_subset"] == VS
    # plain --fast is still fast-v3: the family is not in it
    fast.VERSION = V3  # the default of the time (fast.DEFAULT is a core-half cut since plan 0104)
    capsys.readouterr()
    plain = ["judge", f"family={fam}", f"readouts={path}", f"out={tmp_path / 'j'}", "--fast"]
    assert main(plain) == 2
    assert capsys.readouterr().err.strip() == f"{fam}: not in fast-v3"
    assert not (tmp_path / "j").exists() and fast.VERSION == V3


def test_cli_fast_key_values(toy, tmp_path, capsys):
    _spec, path = toy
    base = ["judge", f"family={TOY}", f"readouts={path}", f"out={tmp_path / 'o'}"]
    assert main([*base, "fast=bogus"]) == 2
    assert "fast must be True or False, got 'bogus'" in capsys.readouterr().err
    assert main([*base, "fast_variant=safety"]) == 2
    assert "fast_variant is not a key" in capsys.readouterr().err
    assert main(["report", f"dir={tmp_path}", "fast=bogus"]) == 2
    assert "fast must be True or False, got 'bogus'" in capsys.readouterr().err
    assert main(["report", f"dir={tmp_path}", "fast_variant=safety"]) == 2
    assert "fast_variant is not a key" in capsys.readouterr().err
    for cmd in (["plan"], ["produce", f"family={TOY}"]):
        assert main([*cmd, "fast=bogus"]) == 2
        assert "fast must be True or False" in capsys.readouterr().err
    assert not (tmp_path / "o").exists() and fast.VERSION == V3
    # plan 0104: --fast-safety (fast=safety) is retired on every command: a usage error that
    # says what to run instead, and nothing is selected or written
    for argv in (
        [*base, "--fast-safety"],
        [*base, "fast=safety"],
        [*base, "--fast-safety", "--show"],
        ["plan", "--fast-safety"],
        ["run", "--fast-safety", f"readouts_root={tmp_path}", f"out={tmp_path / 'r'}"],
        ["report", f"dir={tmp_path}", "--fast-safety"],
        ["produce", f"family={TOY}", "--fast-safety"],
    ):
        assert main(argv) == 2, argv
        err = capsys.readouterr().err
        assert "--fast-safety is retired (plan 0104)" in err
        assert "fast_version=fast-safety-v2" in err and "families=jailbreak_recognition" in err
    assert not (tmp_path / "o").exists() and not (tmp_path / "r").exists()
    assert fast.VERSION == V3
    assert main([*base, "--fast", "--show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["fast"] is True and shown["fast_variant"] == ""
    assert main(["list", "--fast-safety"]) == 2  # an unknown key where `fast` is one
    capsys.readouterr()
    # the judge itself under a frozen predecessor made active (a family of both old subsets)
    fast.use(VS)
    assert main([*base, "--fast"]) == 0
    assert read_results(tmp_path / "o").config["fast_subset"] == VS
    # report fast_version=: any registered version; an unknown one and fast=False are refused
    assert main(["report", f"dir={tmp_path}", "fast_version=fast-v9"]) == 2
    assert "fast_version must be one of" in capsys.readouterr().err
    assert main(["report", f"dir={tmp_path}", "fast_version=fast-v3", "fast=False"]) == 2
    assert "contradicts fast=False" in capsys.readouterr().err


def test_cli_run_fast_safety_all_skips_the_six_dropped_families(tmp_path, capsys):
    root, out = tmp_path / "readouts", tmp_path / "out"
    root.mkdir()
    fast.use(VS)  # plan 0104: the retired --fast-safety, made active directly
    argv = ["run", "--fast", "all=True", f"readouts_root={root}", f"out={out}"]
    # plan 0109: exit 2, since directed_modulation fails closed under it (NOT_REFROZEN)
    assert main([*argv, "dry_run=True"]) == 2
    text = capsys.readouterr().out
    statuses = json.loads((out / "run.json").read_text())["families"]
    not_fast = {f for f, s in statuses.items() if "not in fast" in (s.get("error") or "")}
    # the six dropped families (and whatever no subset holds), never one of the 24
    assert set(DROPPED) <= not_fast and not not_fast & set(FAMILIES_V1)
    for fam in DROPPED:
        assert f"{fam}: skipped (not in fast-safety-v2)" in text
        assert statuses[fam]["error"] == "not in fast-safety-v2"
    assert {f for f, s in statuses.items() if s["error"].startswith("no readouts")} == set(LIVE_VS)
    assert statuses[DM]["status"] == "failed"
    assert statuses[DM]["error"] == f"{DM}: bank changed since {VS} was frozen; re-freeze"


def test_cli_run_fast_safety_judges_and_reports(tmp_path, capsys, monkeypatch):
    _safety_fakes(monkeypatch)
    root, out = tmp_path / "readouts", tmp_path / "out"
    root.mkdir()
    _am_readouts(root / f"{AM}.jsonl")
    fast.use(VS)  # plan 0104: the retired --fast-safety, made active directly
    argv = ["run", "--fast", f"families={AM},typo", f"readouts_root={root}", f"out={out}"]
    assert main(argv) == 0
    text = capsys.readouterr().out
    head = (
        "scope: fast subset fast-safety-v2 (24 families; not comparable with full-bench "
        "numbers); rows of other subsets are excluded\n\n"
    )
    assert head in text and (out / "summary.md").read_text().startswith(head)
    assert "typo: skipped (not in fast-safety-v2)" in text and "stale fast subset" not in text
    assert read_results(out / AM).config["fast_subset"] == VS
    # a bare report in a fresh process is the fast-v3 view, with the hint
    fast.VERSION = V3  # the default of the time (fast.DEFAULT is a core-half cut since plan 0104)
    assert main(["report", f"dir={out}"]) == 0
    text = capsys.readouterr().out
    assert text.startswith(
        "scope: fast subset fast-v3 (22 families; not comparable with full-bench numbers); "
        "rows of other subsets are excluded\n"
        "1 row(s) are fast-safety-v2 rows; pass fast_version=fast-safety-v2 for that subset's "
        "macro\n\n"
    )
    assert "stale fast subset (fast-safety-v2)" in text
    assert main(["report", f"dir={out}", "fast_version=fast-safety-v2"]) == 0
    text = capsys.readouterr().out
    assert text.startswith(head) and "stale fast subset" not in text
    assert (out / "summary.md").read_text().startswith(head)


@pytest.mark.usefixtures("fast_safety")
def test_safety_sidecars_of_the_position_reduced_families(tmp_path, mk_args, capsys):
    def load_am(**meta):
        path, ids = _fast_am_file(tmp_path, **meta)
        args = mk_args(path, scope=fast.SCOPE, layers=[20])
        return reads.load(args, AM), ids

    def load_jb(**meta):
        path, ids = _fast_jb_file(tmp_path, **meta)
        return reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), JB), ids

    def refused(load, text, **meta):
        with pytest.raises(SystemExit) as e:
            load(**meta)
        err = capsys.readouterr().err
        assert e.value.code == 2 and text in err, err

    # a fast-v1 file with fast-v1's own sha, and a fast-safety-v2 file with its own
    for declared, shas in ((V1, V1_FAST_PLAN_SHA), (VS, VS_FAST_PLAN_SHA)):
        (cells, rep), ids = load_am(fast=declared, plan_sha=shas[AM])
        assert len(cells) == 60 * len(ids) and rep.reads_checked == "sidecar"
        assert rep.partial_ids == []
        (cells, rep), ids = load_jb(fast=declared, plan_sha=shas[JB])
        assert len(cells) == len(ids) and rep.reads_checked == "sidecar"  # one site per item
        assert json.loads(rep.fast_rule) == {"kind": "punct_special"}
    assert _fast_am_file(tmp_path)[0].with_name("am.jsonl.meta.json").exists()
    # each version's sha under the other's name: the plan_sha guard still fails closed
    for load, fam in ((load_am, AM), (load_jb, JB)):
        refused(load, "different fast plan", fast=V1, plan_sha=VS_FAST_PLAN_SHA[fam])
        refused(load, "different fast plan", fast=VS, plan_sha=V1_FAST_PLAN_SHA[fam])
        refused(load, "different fast plan", fast=VS, plan_sha=reads.plan_sha(fam))
        # fast-v3's file holds neither family: refused with and without a plan_sha
        refused(load, f"{fam}: not in fast subset fast-v3", fast=V3, plan_sha=None)
        refused(load, f"{fam}: not in fast subset fast-v3", fast=V3, plan_sha=V1_FAST_PLAN_SHA[fam])
        refused(load, "another fast subset ('fast-v0', not 'fast-safety-v2')", fast="fast-v0")
    # a family of both subsets: any compatible version's file is accepted
    for declared in (V1, V3, VS):
        path, ids = _fast_poetry_file(tmp_path, declared)
        cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
        assert len(cells) == 2 * len(ids) and rep.reads_checked == "sidecar"
    path, _ = _fast_poetry_file(tmp_path, "fast-v0")
    with pytest.raises(SystemExit):
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), "poetry")
    assert "another fast subset ('fast-v0', not 'fast-safety-v2')" in capsys.readouterr().err


@pytest.mark.usefixtures("fast_v1")
def test_a_fast_safety_sidecar_is_accepted_under_fast_v1(tmp_path, mk_args, capsys):
    path, ids = _fast_jb_file(tmp_path, fast=VS, plan_sha=VS_FAST_PLAN_SHA[JB])
    cells, rep = reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), JB)
    assert len(cells) == len(ids) and rep.reads_checked == "sidecar"
    path, _ = _fast_jb_file(tmp_path, fast=VS, plan_sha=V1_FAST_PLAN_SHA[JB])
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, layers=[20]), JB)
    assert e.value.code == 2 and "different fast plan" in capsys.readouterr().err


def test_a_fast_safety_sidecar_is_accepted_under_fast_v3(tmp_path, mk_args):
    path, ids = _fast_poetry_file(tmp_path, VS)
    args = mk_args(path, scope=fast.SCOPE, layers=[20])
    cells, rep = reads.load(args, "poetry")
    assert fast.VERSION == V3 and len(cells) == 2 * len(ids) and rep.reads_checked == "sidecar"
    assert rep.partial_ids == [] and not reads.incomplete(args)


@pytest.mark.usefixtures("fast_safety")
def test_a_produced_fast_safety_file_declares_fast_safety_v2(tmp_path):
    from wsbench.produce.methods import Readout
    from wsbench.produce.producer import Producer, Row
    from wsbench.readouts import read_sidecar

    class Fake(Producer):
        def read_spec(self, spec, *, layers=None):
            return [Row(spec.id, 36, 0, "t", Readout(samples=["x"]))]

    p = Fake(backend=None, method=SimpleNamespace(name="fake", layers=None))  # type: ignore[arg-type]
    for fam in ("poetry", AM):
        out = tmp_path / f"{fam}.jsonl"
        p.run_family(fam, out, fast=True)
        meta = read_sidecar(out)
        assert meta["fast"] == VS and meta["plan_sha"] == reads.fast_plan_sha(fam)
        ids = [json.loads(x)["id"] for x in out.read_text().splitlines()]
        assert ids == fast.subset()[fam]["read_ids"]
    assert read_sidecar(tmp_path / f"{AM}.jsonl")["plan_sha"] == VS_FAST_PLAN_SHA[AM]


def test_macro_under_the_two_selectable_subsets():
    def rows():
        return [
            _fast_row("poetry", fast_subset=V1),
            _fast_row("basic_readout_st", fast_subset=V3),
            _fast_row("user_modeling", fast_subset=VS),
            _fast_row(JB, fast_subset=V1),
            _fast_row(AM, fast_subset=VS),
            _fast_row("hinted_cutoff", fast_subset="fast-v0"),
        ]

    # default (fast-v3): the 22 families' rows in whichever compatible version stamped them;
    # a safety family's row is out whichever version stamped it (the family clause)
    m = macro(rows())
    assert m["fast_subset"] == V3
    assert m["families"] == ["poetry", "basic_readout_st", "user_modeling"]
    assert m["excluded"] == [
        {"family": JB, "reason": "stale fast subset (fast-v1)"},
        {"family": AM, "reason": "stale fast subset (fast-safety-v2)"},
        {"family": "hinted_cutoff", "reason": "stale fast subset (fast-v0)"},
    ]
    fast.use(VS)
    m = macro(rows())
    assert m["fast_subset"] == VS
    assert m["families"] == ["poetry", "basic_readout_st", "user_modeling", JB, AM]
    assert m["excluded"] == [{"family": "hinted_cutoff", "reason": "stale fast subset (fast-v0)"}]


def test_fast_header_hint():
    from wsbench.cli import fast_header

    line = (
        "scope: fast subset fast-v3 (22 families; not comparable with full-bench numbers); "
        "rows of other subsets are excluded"
    )
    # plan 0104: one line per registered version whose rows the active macro leaves out,
    # naming `fast_version=` (plan 0095's single `--fast-safety` line counted both together)
    hint = "\n{n} row(s) are {v} rows; pass fast_version={v} for that subset's macro"
    in_v2 = [_fast_row("poetry", fast_subset=VS), _fast_row("basic_readout_st", fast_subset=V1)]
    assert fast_header() == fast_header(in_v2) == line
    safety = [_fast_row(JB, fast_subset=V1), _fast_row(AM, fast_subset=VS)]
    assert fast_header([*in_v2, *safety]) == (
        line + hint.format(n=1, v=VS) + hint.format(n=1, v=V1)
    )
    assert fast_header(safety[:1]) == line + hint.format(n=1, v=V1)
    # not counted: another version's row, a non-fast row of the family
    other = [_fast_row(JB, fast_subset="fast-v0"), _result(AM, value=0.5, n_items=30)]
    assert fast_header(other) == line
    fast.use(VS)
    assert fast_header([*in_v2, *safety]) == line.replace("fast-v3 (22", "fast-safety-v2 (24")


def test_cli_report_fast_safety(tmp_path, capsys):
    write_results(tmp_path / "poetry", _fast_row("poetry", fast_subset=VS))
    write_results(tmp_path / "basic_readout_st", _fast_row("basic_readout_st", fast_subset=V3))
    write_results(tmp_path / JB, _fast_row(JB, fast_subset=VS))
    line = "scope: fast subset fast-v3 (22 families; not comparable with full-bench numbers)"
    hint = (
        "1 row(s) are fast-safety-v2 rows; pass fast_version=fast-safety-v2 for that subset's "
        "macro\n\n"
    )
    for argv in ([], ["--fast"]):
        assert main(["report", f"dir={tmp_path}", *argv]) == 0
        text = capsys.readouterr().out
        assert text.startswith(f"{line}; rows of other subsets are excluded\n{hint}")
        assert "stale fast subset (fast-safety-v2)" in text
        assert (tmp_path / "summary.md").read_text().startswith(line)
    assert main(["report", f"dir={tmp_path}", "--fast", "json=True"]) == 0
    m = json.loads(capsys.readouterr().out)["macro"]
    assert m["fast_subset"] == V3 and sorted(m["families"]) == ["basic_readout_st", "poetry"]
    assert m["excluded"] == [{"family": JB, "reason": "stale fast subset (fast-safety-v2)"}]
    # the same rows as the safety subset's report: 24 families, nothing stale
    assert main(["report", f"dir={tmp_path}", "fast_version=fast-safety-v2", "json=True"]) == 0
    m = json.loads(capsys.readouterr().out)["macro"]
    assert m["fast_subset"] == VS and m["excluded"] == []
    assert sorted(m["families"]) == ["basic_readout_st", JB, "poetry"]
    fast.VERSION = V3  # the default of the time (fast.DEFAULT is a core-half cut since plan 0104)
    assert main(["report", f"dir={tmp_path}", "fast_version=fast-safety-v2"]) == 0
    text = capsys.readouterr().out
    assert text.startswith(
        "scope: fast subset fast-safety-v2 (24 families; not comparable with full-bench "
        "numbers); rows of other subsets are excluded\n\n"
    )
    assert "stale fast subset" not in text and "--fast-safety" not in text


def test_a_fast_v1_cache_replays_under_fast_safety(toy, tmp_path, monkeypatch):
    """A cache written with ``fast.VERSION`` = fast-v1 answers a fast-safety-v2 run with no new
    call and the same value (toy family; the real position-reduced families are validated on
    real data)."""
    spec, path = toy
    asked: list[tuple[str, str]] = []

    def stream_json(prompts, *, on_result, **_kw):
        for i, (system, user) in enumerate(prompts):
            asked.append((system, user))
            on_result(i, {"ok": user == "yes"})
        return llm.Spend()

    monkeypatch.setattr(mcjudge, "run_calls", REAL_RUN_CALLS)  # the real cache path
    monkeypatch.setattr(llm, "stream_json", stream_json)
    judge = resolve(spec.judge, flag=None, env={})
    out = tmp_path / "out"
    monkeypatch.setattr(fast, "VERSION", V1)
    old = runner.judge_family(spec, _opts(), path, out, judge=judge, opts=runner.parse_opts([]))
    assert len(asked) == 4 and old.config["fast_subset"] == V1
    fast.use(VS)
    new = runner.judge_family(spec, _opts(), path, out, judge=judge, opts=runner.parse_opts([]))
    assert len(asked) == 4  # 0 new calls
    assert new.config["fast_subset"] == VS and new.value == old.value == pytest.approx(1 / 3)
    assert new.rows == old.rows
    differ = {k for k in {*old.config, *new.config} if old.config.get(k) != new.config.get(k)}
    assert differ == {"fast_subset"}


def test_macro_excludes_a_compatible_stamp_whose_file_lacks_the_family():
    """Plan 0095 review: a jailbreak row stamped fast-v3 (whose file has no such family) is
    stale under the safety subset, like the sidecar guard in ``reads.load``."""
    from wsbench.results import _stale_fast_subset

    fast.use(VS)

    def row(fam: str, v: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(family=fam, config={"fast_subset": v})

    assert _stale_fast_subset(row("jailbreak_recognition", V3))
    assert not _stale_fast_subset(row("jailbreak_recognition", V1))
    assert not _stale_fast_subset(row("poetry", V3))
