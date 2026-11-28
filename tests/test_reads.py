"""reads.load: the ONE loading entry point (plan 0032 §2.0, §2.6): sidecar, sampling, the
full-span check and the full-read guards."""

import ast
from pathlib import Path

import pytest
from conftest import native_args, write_jsonl, write_sidecar

from wsbench import digest, readplan, reads, registry
from wsbench.cache import Cache
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.llm import Spend
from wsbench.readouts import Cell
from wsbench.results import FamilyResult, write_results

SRC = Path(__file__).resolve().parents[1] / "src" / "wsbench"
MORAL = "moral_rationale"  # full = all positions, min_full_positions 6, contiguous (plan 0046)


def _args(path: Path, tmp_path: Path, **kw) -> object:
    extra = kw.pop("extra", {})
    return native_args(
        readouts=path,
        out=tmp_path / "o",
        judge=resolve(JudgeConfig()),
        layers=kw.pop("layers", None),
        items=None,
        limit=0,
        allow_missing=kw.pop("allow_missing", False),
        concurrency=1,
        rpm=1.0,
        dry_run=True,
        extra=extra,
    )


def _rows(iid: str, layers, positions, text="x"):
    return [
        {"id": iid, "layer": L, "pos": p, "samples": [f"{text} L{L} p{p}"]}
        for L in layers
        for p in positions
    ]


def _moral_ids(n=2) -> list[str]:
    return [s.id for s in readplan.plan(MORAL)[:n]]


# ---------------------------------------------------------------- structure


def test_no_family_calls_load_readouts_directly():
    roots = [SRC / "evals", SRC / "basic", SRC / "multitoken"]
    bad = []
    for root in roots:
        for f in root.rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and any(
                    a.name == "load_readouts" for a in node.names
                ):
                    bad.append(str(f.relative_to(SRC)))
                if isinstance(node, ast.Attribute) and node.attr == "load_readouts":
                    bad.append(str(f.relative_to(SRC)))
    assert bad == []


def _families() -> list[str]:
    registry.load_all()
    return sorted(readplan.families())


def test_min_full_positions_per_family(real_families):
    single = {"final_token", "offset_from_end", "line_one_newline", "last_newline"}
    for name, spec in real_families.items():
        kinds = {s.positions["kind"] for s in readplan.plan(name)[:20]}
        if kinds <= single:
            assert spec.min_full_positions == 1, name
        assert spec.min_full_positions >= 1, name
    for name in ("introspection", "jlens_concept_pr"):  # unverbalized_hint removed (plan 0081)
        assert real_families[name].full_contiguous is False, name
    assert real_families["jailbreak_recognition"].full_contiguous is True


# ---------------------------------------------------------------- full-read guards


def test_single_site_file_exits_2(tmp_path):
    a, b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, [20], [9]) + _rows(b, [20], [9]))
    write_sidecar(path, reader="t", arm="t")
    with pytest.raises(SystemExit):
        reads.load(_args(path, tmp_path, layers=[20]), MORAL)


def test_noncontiguous_full_is_partial_under_allow_missing(tmp_path):
    a, b = _moral_ids()
    rows = _rows(a, [20], [1, 2, 4, 5]) + _rows(b, [20], [5, 6, 7, 8, 9, 10])
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    write_sidecar(path, reader="t", arm="t")
    with pytest.raises(SystemExit):
        reads.load(_args(path, tmp_path, layers=[20]), MORAL)
    args = _args(path, tmp_path, layers=[20], allow_missing=True)
    _cells, rep = reads.load(args, MORAL)
    assert rep.partial_ids == [a] and rep.reads_checked == "sidecar"
    assert reads.incomplete(args)


def test_prompt_only_reader_waives_check_full(tmp_path):
    a, b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, [44], [9]) + _rows(b, [44], [7]))
    write_sidecar(path, reader="prompt_only:claude-opus-5-5", layers=[44], protocol="po-opus-v1")
    cells, rep = reads.load(_args(path, tmp_path), MORAL)
    assert len(cells) == 2 and rep.reads_checked == "prompt_only" and not rep.partial_ids


def test_full_is_the_only_reads_mode(tmp_path, capsys):
    """``reads=`` takes ``full`` alone: another value exits 2 with one message, from the loader
    (``opts=reads=``), from the CLI key, and for a file whose sidecar declares it."""
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, readplan.GRID, [5, 6, 7, 8, 9]))
    msg = "reads='lite': full is the only reads mode"
    with pytest.raises(SystemExit) as e:
        reads.load(_args(path, tmp_path, extra={"reads": "lite"}), MORAL)
    assert e.value.code == 2 and msg in capsys.readouterr().err
    for argv in (["plan", "reads=lite"], ["report", f"dir={tmp_path}", "reads=lite"]):
        assert main(argv) == 2
        assert msg in capsys.readouterr().err
    write_sidecar(path, reads="lite", reader="t")
    with pytest.raises(SystemExit, match="full is the only reads mode"):
        reads.load(_args(path, tmp_path), MORAL)


def test_missing_plan_layer_under_layers_none_exits_2(tmp_path):
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, [56, 60], [5, 6, 7, 8, 9]))
    write_sidecar(path, reader="t")
    with pytest.raises(SystemExit):
        reads.load(_args(path, tmp_path), MORAL)
    _c, rep = reads.load(_args(path, tmp_path, allow_missing=True), MORAL)
    assert rep.partial_ids == [a]


def test_extra_layers_beyond_plan_are_judged(tmp_path):
    a, _b = _moral_ids()
    layers = [*readplan.GRID, 61, 62, 63]
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, layers, [4, 5, 6, 7, 8, 9]))
    write_sidecar(path, reader="t", layers=layers)
    _cells, rep = reads.load(_args(path, tmp_path), MORAL)
    assert rep.layers == layers and not rep.partial_ids
    assert reads.config_stamps(_args(path, tmp_path))["reads"] == "full"


def test_all_layer_producer_file_is_judged(tmp_path):
    """Late critique fix (2026-10-30): plan_sha does not hash layers, so a file the producer read
    at all 64 layers (``plan(layers="all")``) carries the plan_sha the judge recomputes, and is
    judged at every layer (guard ii checks the plan's own layers are present)."""
    every = readplan.plan(MORAL, layers="all")
    assert every[0].layers == list(range(64))
    assert reads.plan_sha_rows(s.row() for s in every) == reads.plan_sha(MORAL)
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, range(64), [4, 5, 6, 7, 8, 9]))
    write_sidecar(path, reader="t", layers=list(range(64)), plan_sha=reads.plan_sha(MORAL))
    cells, rep = reads.load(_args(path, tmp_path), MORAL)
    assert rep.layers == list(range(64)) and not rep.partial_ids
    assert len(cells) == 64 * 6


def test_plan_sha_drift_exits_2(tmp_path):
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, readplan.GRID, [5, 6, 7, 8, 9]))
    write_sidecar(path, reader="t", plan_sha="0" * 64)
    with pytest.raises(SystemExit):
        reads.load(_args(path, tmp_path, allow_missing=True), MORAL)  # never waived


def test_plan_sha_excludes_note_and_layers():
    rows = [s.row() for s in readplan.plan(MORAL)]
    base = reads.plan_sha_rows(rows)
    moved = [{**r, "note": "another note", "layers": [1]} for r in rows]
    assert reads.plan_sha_rows(moved) == base
    other = [{**r, "positions": {"kind": "last_n", "n": 3}} for r in rows]
    assert reads.plan_sha_rows(other) != base


def test_sidecarless_file_is_report_only(tmp_path):
    a, b = _moral_ids()
    rows = _rows(a, [20], [1, 2, 4, 5]) + _rows(b, [20], [5, 6, 7, 8, 9, 10])
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    args = _args(path, tmp_path, layers=[20])
    _cells, rep = reads.load(args, MORAL)  # no exit
    assert rep.reads_checked == "no_sidecar" and rep.partial_ids_unenforced == [a]
    assert rep.partial_ids == [] and not reads.incomplete(args)


def test_missing_requested_layer_exits_2(tmp_path):
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, [20], [5, 6]))
    with pytest.raises(SystemExit):
        reads.load(_args(path, tmp_path, layers=[20, 44]), MORAL)


def test_missing_requested_layer_allow_missing_is_incomplete(tmp_path):
    a, _b = _moral_ids()
    path = write_jsonl(tmp_path / "r.jsonl", _rows(a, [20], [5, 6]))
    args = _args(path, tmp_path, layers=[20, 44], allow_missing=True)
    _c, rep = reads.load(args, MORAL)
    assert rep.layers_missing == [44] and reads.incomplete(args)


# ---------------------------------------------------------------- stamps


def test_report_refuses_results_of_another_reads_mode(tmp_path, capsys):
    def res(family, m):
        return FamilyResult(
            family=family, metric="pass_rate", value=0.5, ci95=None, n_items=1,
            higher_is_better=True, chance=None, chance_label=None, complete=True,
            pinned_instrument=True, config={"reads": m}, counts={},
        )  # fmt: skip

    write_results(tmp_path / "a", res("association", "full"))
    write_results(tmp_path / "b", res("poetry", "lite"))
    assert main(["report", f"dir={tmp_path}", "floors=False"]) == 2
    assert "only full reads are reported" in capsys.readouterr().err


def test_collapse_rejects_dropped_cells(tmp_path):
    cells = [Cell("a", 20, p, (f"s{p}",), None, None) for p in range(3)]
    with Cache(tmp_path / "c.jsonl") as cache, pytest.raises(ValueError):
        digest.collapse(
            "fam",
            {"a": cells[:2]},
            args=native_args(
                readouts=tmp_path,
                out=tmp_path,
                judge=resolve(JudgeConfig()),
                layers=None,
                items=None,
                limit=0,
                allow_missing=False,
                concurrency=1,
                rpm=1.0,
                dry_run=True,
                extra={"aggregate": "summary"},
            ),
            cache=cache,
            spend=Spend(),
            preflight=None,
            task_note="",
            expect_all=cells,
        )
