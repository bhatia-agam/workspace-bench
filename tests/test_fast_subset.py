"""Plan 0090: the frozen fast subset (``fast-v1``), its positions rules, loader, rescore and CLI."""

import dataclasses
import hashlib
import json
import os
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
    """sha256 of the plan rows exactly as ``wsbench plan`` writes them (every key)."""
    h = hashlib.sha256()
    for s in specs:
        h.update(json.dumps(s.row(), ensure_ascii=False).encode() + b"\n")
    return h.hexdigest()


def _non_fast_shas() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {"plan_sha": {}, "rows_full": {}, "rows_lite": {}}
    for fam in readplan.families():
        out["plan_sha"][fam] = reads.plan_sha(fam)
        out["rows_full"][fam] = _rows_sha(readplan.plan(fam))
        out["rows_lite"][fam] = _rows_sha(readplan.plan(fam, reads="lite"))
    return out


# ---------------------------------------------------------------- 4b. the non-fast plan


def test_non_fast_plan_is_byte_identical_to_pre_0090():
    """``plan_sha`` and the written plan rows (full and lite) of every family equal the values
    recorded on the code before plan 0090 (under pytest: the conftest stubs set nyt's and
    knowledge_cutoff's texts)."""
    got = _non_fast_shas()
    if os.environ.get(WRITE_GOLDEN_ENV):
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert got == want


# ---------------------------------------------------------------- helpers

FAMILIES_24 = sorted(fast.subset())
DROPPED = (
    "typo_mt",
    "association",
    "multihop",
    "multilingual",
    "chain_intermediates",
    "multilingual_mt",
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


def test_freeze_file_shape_and_counts():
    d = json.loads(fast.PATH.read_text(encoding="utf-8"))
    assert d["version"] == fast.VERSION == "fast-v1" and d["subject"] == "Qwen3.6-27B"
    assert tuple(d["dropped_families"]) == DROPPED
    assert len(d["families"]) == 24 and not set(DROPPED) & set(d["families"])
    assert "jlens_concept_pr" not in d["families"]
    assert fast.families() == FAMILIES_24  # registry order
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


@pytest.mark.parametrize("fam", FAMILIES_24)
def test_freeze_family_is_registered_in_the_macro_and_on_its_bank(fam):
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


def test_strict_ati_subset_is_350_ids():
    assert ti.SUBSET_VERSION == "ati-subset-v2"
    assert sum(len(ti.subset_entry(f, ti.FROZEN)["ids"]) for f in STRICT_ATI_FAMILIES) == 350


def test_entry_fails_closed(monkeypatch):
    with pytest.raises(fast.NotInFast) as e:
        fast.entry("typo_mt")
    assert e.value.code == "typo_mt: not in fast-v1"
    monkeypatch.setenv("WSB_BANK_ROOT", "adapted/glm-5.3")
    with pytest.raises(SystemExit) as e:
        fast.entry("poetry")
    assert not isinstance(e.value, fast.NotInFast)
    assert "registered Qwen3.6-27B banks only" in str(e.value.code)
    with pytest.raises(fast.NotInFast):  # a dropped family is skipped whatever the bank env
        fast.entry("association")
    monkeypatch.delenv("WSB_BANK_ROOT")
    monkeypatch.setenv("WSB_BANK_FILE_POETRY", "evals/poetry/items.json")
    with pytest.raises(SystemExit, match="registered Qwen3\\.6-27B banks only"):
        fast.entry("poetry")
    assert fast.entry("basic_readout")  # another family's pin does not matter
    monkeypatch.delenv("WSB_BANK_FILE_POETRY")
    monkeypatch.setattr(fast, "bank_sha", lambda family: "0" * 64)
    with pytest.raises(SystemExit, match="bank changed since fast-v1 was frozen; re-freeze"):
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


@pytest.mark.parametrize("token", [FW_COMMA, CJK_CLOSE, CURLY_CLOSE])
def test_non_ascii_punctuation_is_a_site_for_resolve_and_reads(token, tmp_path, mk_args):
    toks = ["日本", token, "語"]
    assert readplan.resolve({"kind": "punct_special"}, toks) == [1]
    iid = fast.subset()[JB]["read_ids"][0]
    path = write_jsonl(tmp_path / "jb.jsonl", [_cell(iid, p, t) for p, t in enumerate(toks)])
    cells, rep = reads.load(mk_args(path, scope=fast.SCOPE), JB)
    assert [(c.pos, c.token) for c in cells] == [(1, token)] and rep.fast_fallback_ids == []


# ---------------------------------------------------------------- 4. the fast plan


@pytest.mark.parametrize("fam", FAMILIES_24)
def test_fast_plan_rows(fam):
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
        readplan.plan("multihop", fast=True)
    with pytest.raises(SystemExit, match="drop reads=lite"):
        readplan.plan("poetry", fast=True, reads="lite")
    assert fast.SCOPE not in json.dumps([s.row() for s in readplan.plan(AM)][:2])


# ---------------------------------------------------------------- 5. reads.load


def _jb_rows(tokens_by_item: dict[str, list[str | None]], layer: int = 20) -> list[dict]:
    return [
        _cell(iid, 100 + p, t, layer)
        for iid, toks in tokens_by_item.items()
        for p, t in enumerate(toks)
    ]


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
    assert rep.reads == "full" and reads.config_stamps(args)["reads"] == "full"
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


def test_full_file_without_token_is_refused_under_punct_special(tmp_path, mk_args, capsys):
    a = fast.subset()[JB]["read_ids"][0]
    path = write_jsonl(tmp_path / "jb.jsonl", _jb_rows({a: [".", None]}))
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE), JB)
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert a in err and "token" in err


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


def test_fast_load_refuses_lite_and_a_dropped_family(tmp_path, mk_args, capsys):
    path = write_jsonl(tmp_path / "x.jsonl", [_cell("a", 1)])
    with pytest.raises(SystemExit) as e:
        reads.load(mk_args(path, scope=fast.SCOPE, extra={"reads": "lite"}), "poetry")
    assert e.value.code == 2 and "drop reads=lite" in capsys.readouterr().err
    with pytest.raises(fast.NotInFast):
        reads.load(mk_args(path, scope=fast.SCOPE), "multihop")


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


def test_fast_declared_file_is_accepted_with_the_fast_plan_sha(tmp_path, mk_args):
    path, ids = _fast_am_file(tmp_path)
    assert reads.fast_plan_sha(AM) != reads.plan_sha(AM)
    args = mk_args(path, scope=fast.SCOPE, layers=[20])
    cells, rep = reads.load(args, AM)
    assert len(cells) == 60 * len(ids) == rep.n_cells_before_fast  # the narrowing is idempotent
    assert rep.partial_ids == [] and rep.reads_checked == "sidecar"
    assert not reads.incomplete(args) and not mcjudge.is_subset(args)


def test_fast_declared_file_is_refused_without_the_flag(tmp_path, mk_args, capsys):
    path, _ = _fast_am_file(tmp_path)
    for extra in ({}, {"fast": "1"}):
        with pytest.raises(SystemExit) as e:
            reads.load(mk_args(path, layers=[20], extra=extra), AM)
        assert e.value.code == 2
        assert "file was produced --fast; judge it with --fast" in capsys.readouterr().err


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
    rows = [_fast_row("poetry"), _fast_row("basic_readout")]
    m = macro(rows)
    assert m["families"] == ["poetry", "basic_readout"] and m["fast_subset"] == "fast-v1"
    assert m["value"] == 0.5 and m["excluded"] == []
    with pytest.raises(SystemExit, match="macro: results mix fast and non-fast rows"):
        macro([*rows, _result("user_modeling", value=0.5, n_items=30)])
    with pytest.raises(SystemExit, match="mix fast and non-fast"):  # introspection's own scope
        macro([*rows, _result("introspection", value=0.5, n_items=30, config={"scope": "all"})])
    assert "fast_subset" not in macro([_result("poetry", value=0.5, n_items=30)])


def test_macro_excludes_a_stale_subset_and_keeps_every_other_rule():
    stale = _fast_row("basic_readout", fast_subset="fast-v0")
    small = _result("user_modeling", value=1.0, n_items=3, config=_fast_row("poetry").config)
    incomplete = _fast_row("moral_rationale")
    incomplete.complete = False
    other_metric = _fast_row("wrong_intermediate")
    other_metric.metric = "precision"
    m = macro([_fast_row("poetry"), stale, small, incomplete, other_metric])
    assert m["families"] == ["poetry", "user_modeling"]  # no n<20 rule for fast rows
    assert m["excluded"] == [
        {"family": "basic_readout", "reason": "stale fast subset (fast-v0)"},
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
    bank = Path("evals/poetry/items_v5.json")  # never read: the toy's bank_sha is patched
    spec = EvalSpec(TOY, "Toy", "basic", bank, JudgeConfig(), "pass_rate", True, _toy_run)
    registry.FAMILIES[TOY] = spec
    entry = {"bank_sha": "0" * 64, "units": {"all": TOY_IDS[:3]}, "read_ids": TOY_IDS[:4]}
    fams = {**fast.subset(), TOY: entry}
    monkeypatch.setattr(fast, "_file", lambda: {"version": fast.VERSION, "families": fams})
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
    assert r.config["scope"] == "fast" and r.config["fast_subset"] == "fast-v1"
    assert r.config["items"] == TOY_IDS[:4] and r.config["reads"] == "full"
    assert r.config["prompt_version"] == "toy-v1" and "fast_rule" not in r.config
    assert [row["id"] for row in r.rows] == TOY_IDS[:4]
    stored = read_results(tmp_path / "fast")
    assert stored.value == r.value and stored.config["scope"] == "fast"
    assert macro([stored])["fast_subset"] == "fast-v1" and macro([stored])["families"] == [TOY]
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
    specs = [spec, registry.FAMILIES["typo_mt"], registry.FAMILIES["poetry"]]
    outcomes, code = runner.run_families(
        specs, _opts(dry_run=True), readouts_root=path.parent, out=tmp_path / "out"
    )
    by = {o.family: o for o in outcomes}
    assert code == 0 and by[TOY].status == "ok"
    assert (by["typo_mt"].status, by["typo_mt"].error) == ("skipped", "not in fast-v1")
    assert by["poetry"].status == "skipped" and by["poetry"].error.startswith("no readouts")
    assert "typo_mt: skipped (not in fast-v1)" in capsys.readouterr().out
    # a bank that changed since the freeze fails (exit 2) before any preflight
    fast.subset()[TOY]["bank_sha"] = "1" * 64
    outcomes, code = runner.run_families(
        [spec], _opts(dry_run=True), readouts_root=path.parent, out=tmp_path / "out2"
    )
    assert code == 2 and outcomes[0].status == "failed" and "re-freeze" in outcomes[0].error


# ---------------------------------------------------------------- 7 / 11. CLI


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
    assert main(["plan", "--fast", "families=poetry,multihop", f"out={tmp_path / 'x'}"]) == 2
    assert "multihop: not in fast-v1" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
    assert main(["plan", "--fast", "reads=lite", f"out={tmp_path / 'y'}"]) == 2
    # fast=False is the plan of record
    assert main(["plan", "fast=False", "families=poetry", f"out={tmp_path / 'z'}"]) == 0
    assert len((tmp_path / "z/poetry.jsonl").read_text().splitlines()) == len(
        readplan.plan("poetry")
    )


def test_cli_plan_fast_all_is_the_24_families(tmp_path):
    assert main(["plan", "--fast", f"out={tmp_path}"]) == 0
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == FAMILIES_24
    n = sum(len(p.read_text().splitlines()) for p in tmp_path.glob("*.jsonl"))
    assert n == 2351


def test_cli_judge_fast(toy, tmp_path, capsys):
    _spec, path = toy
    out = tmp_path / "o"
    assert main(["judge", f"family={TOY}", f"readouts={path}", f"out={out}", "--fast"]) == 0
    r = read_results(out)
    assert r.config["scope"] == "fast" and r.value == pytest.approx(1 / 3) and r.complete
    capsys.readouterr()
    assert main(["judge", "family=typo_mt", f"readouts={path}", f"out={out}", "--fast"]) == 2
    assert capsys.readouterr().err.strip() == "typo_mt: not in fast-v1"


@pytest.mark.parametrize(
    "extra",
    [
        ["items=t1"],
        ["anti_text_inversion=True"],
        ["reads=lite"],
        ["opts=reads=lite"],
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


def test_cli_run_fast_all_skips_the_six_dropped_families(tmp_path, capsys):
    root, out = tmp_path / "readouts", tmp_path / "out"
    root.mkdir()
    argv = ["run", "--fast", "all=True", f"readouts_root={root}", f"out={out}", "dry_run=True"]
    assert main(argv) == 0
    text = capsys.readouterr().out
    statuses = json.loads((out / "run.json").read_text())["families"]
    not_fast = {f for f, s in statuses.items() if s.get("error") == "not in fast-v1"}
    assert set(DROPPED) <= not_fast and not not_fast & set(FAMILIES_24)
    for fam in DROPPED:
        assert f"{fam}: skipped (not in fast-v1)" in text
    # the 24 families are the ones the run goes on to (here: no readouts file for any)
    assert {f for f, s in statuses.items() if s["error"].startswith("no readouts")} == set(
        FAMILIES_24
    )


def test_cli_run_fast_judges_and_reports(toy, tmp_path, capsys):
    _spec, path = toy
    out = tmp_path / "out"
    argv = [
        "run",
        "--fast",
        f"families={TOY},typo_mt",
        f"readouts_root={path.parent}",
        f"out={out}",
    ]
    assert main(argv) == 0
    capsys.readouterr()
    assert main(["report", f"dir={out}", "--fast"]) == 0
    text = capsys.readouterr().out
    head = "scope: fast subset fast-v1 (25 families; not comparable with full-bench numbers)"
    assert text.startswith(head) and (out / "summary.md").read_text().startswith(head)
    assert f"| {TOY} † | pass_rate | 0.333 |" in text and "lucky guess" not in text
    assert main(["report", f"dir={out}"]) == 0  # unset, one kind present: the fast table
    assert capsys.readouterr().out.startswith(head)
    assert main(["report", f"dir={out}", "fast=False"]) == 0  # no non-fast row: an empty table
    assert TOY not in capsys.readouterr().out.replace(str(out), "")
    payload_rc = main(["report", f"dir={out}", "--fast", "json=True"])
    payload = json.loads(capsys.readouterr().out)
    assert payload_rc == 0 and payload["macro"]["fast_subset"] == "fast-v1"


def test_cli_report_refuses_a_mix_unless_told(tmp_path, capsys):
    write_results(tmp_path / "poetry", _fast_row("poetry", judge_model="m"))
    write_results(tmp_path / "basic_readout", _result("basic_readout", value=0.25, n_items=30))
    assert main(["report", f"dir={tmp_path}"]) == 2
    err = capsys.readouterr().err
    assert "report: results mix fast and non-fast rows; pass --fast or fast=False" in err
    assert main(["report", f"dir={tmp_path}", "--fast", "floors=False"]) == 0
    text = capsys.readouterr().out
    assert (
        "| poetry |" in text
        and "| basic_readout |" not in text
        and "fast subset fast-v1 (24" in text
    )
    assert main(["report", f"dir={tmp_path}", "fast=False", "floors=False"]) == 0
    text = capsys.readouterr().out
    assert "| basic_readout |" in text and "| poetry |" not in text and "fast subset" not in text


def test_fast_judge_of_a_real_family_end_to_end(tmp_path, monkeypatch):
    """relational_multihop under --fast, its judge scripted (as the family's own tests do): the
    run is complete, stamped, and carries the rescored value."""
    from summary_fakes import FakeLLM

    from wsbench.evals.relational_multihop import SPEC, prompts

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
    assert r.config["scope"] == "fast" and r.config["fast_subset"] == "fast-v1"
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
