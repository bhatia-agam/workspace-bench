"""Plan 0079's readout store (``scripts/lens_readouts_modal.py``), offline: ``row_sha`` and the
read-set cut, and ``assemble`` writing only the current plan's rows with today's ``plan_sha``."""

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

from wsbench import reads

PATH = Path(__file__).resolve().parents[1] / "scripts" / "lens_readouts_modal.py"
_spec = importlib.util.spec_from_file_location("_test_lens_readouts_modal", PATH)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


def _row(i: str, text: str = "x", layers=(8, 10)) -> dict:
    return {"family": "fam", "id": i, "render": "plain", "positions": {"kind": "final_token"},
            "layers": list(layers), "text": text, "note": "n"}  # fmt: skip


def test_row_sha_ignores_the_note_but_tracks_the_read():
    base = lr.row_sha(_row("a"))
    assert lr.row_sha({**_row("a"), "note": "other"}) == base
    assert lr.row_sha(_row("a", text="y")) != base
    assert lr.row_sha(_row("a", layers=(8,))) != base


def test_in_band_keeps_only_the_subjects_even_band():
    r = lr.in_band(_row("a", layers=(8, 9, 10, 15, 21, 22, 23)), "qwen3.5-0.8b")
    assert r["layers"] == [8, 10, 22]
    assert lr.in_band(_row("a", layers=(10, 30, 31)), "qwen3.5-9b")["layers"] == [10, 30]
    assert lr.BAND["qwen3-8b"] == tuple(range(12, 35, 2))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    rows = {"fam": [_row("a"), _row("b")]}
    monkeypatch.setattr(lr, "_subject", lambda s: None)
    monkeypatch.setattr(lr, "_families", lambda arg: ["fam"])
    monkeypatch.setattr(lr, "_plan_rows", lambda fam, subject: rows[fam])
    monkeypatch.setattr(reads, "plan_sha", lambda fam: "sha-today")
    store = tmp_path / "store"
    args = Namespace(subject="qwen3.5-0.8b", arm="jlens", store=str(store), families=None,
                     out=str(tmp_path / "out"), partial=False)  # fmt: skip
    return rows, store, args


def _put(store: Path, row: dict, cells: list[dict] | None) -> None:
    p = lr.store_path(store, "qwen3.5-0.8b", "jlens", "fam")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        if cells is None:
            fh.write(json.dumps({"row_sha": lr.row_sha(row), "row": None}) + "\n")
        for c in cells or []:
            fh.write(json.dumps({"row_sha": lr.row_sha(row), "row": c}, ensure_ascii=False) + "\n")


def _cells(i: str, tag: str = "t") -> list[dict]:
    return [{"id": i, "layer": L, "pos": 3, "token": "x", "tokens": [tag], "scores": [1.0]}
            for L in (8, 10)]  # fmt: skip


def test_assemble_writes_the_current_plan_with_todays_plan_sha(setup):
    rows, store, args = setup
    _put(store, rows["fam"][0], _cells("a"))
    _put(store, rows["fam"][1], _cells("b"))
    _put(store, _row("gone"), _cells("gone"))  # a dropped id stays in the store only
    lr.assemble(args)
    out = Path(args.out) / "fam.jsonl"
    ids = [json.loads(line)["id"] for line in out.read_text().splitlines()]
    assert ids == ["a", "a", "b", "b"]
    meta = json.loads((Path(args.out) / "fam.jsonl.meta.json").read_text())
    assert meta["plan_sha"] == "sha-today" and meta["sampling"] == "tokens10"
    assert meta["layers"] == [8, 10] and meta["reads"] == "full"


def test_a_changed_row_is_unread_and_its_old_file_is_removed(setup):
    rows, store, args = setup
    _put(store, rows["fam"][0], _cells("a"))
    _put(store, rows["fam"][1], _cells("b"))
    lr.assemble(args)
    rows["fam"][1] = _row("b", text="edited")  # same id, new render: must be re-read
    lr.assemble(args)
    assert not (Path(args.out) / "fam.jsonl").exists()
    report = json.loads((Path(args.out) / "assemble_report.json").read_text())
    assert report["fam"]["missing"] == 1
    assert lr.stored_shas(lr.store_path(store, "qwen3.5-0.8b", "jlens", "fam")) == {
        lr.row_sha(_row("a")),
        lr.row_sha(_row("b")),
    }
    _put(store, rows["fam"][1], _cells("b", tag="new"))
    lr.assemble(args)
    out = [json.loads(line) for line in (Path(args.out) / "fam.jsonl").read_text().splitlines()]
    assert [c["tokens"] for c in out if c["id"] == "b"] == [["new"], ["new"]]


def test_a_no_position_row_is_reported_not_reread(setup):
    rows, store, args = setup
    _put(store, rows["fam"][0], _cells("a"))
    _put(store, rows["fam"][1], None)
    lr.assemble(args)
    report = json.loads((Path(args.out) / "assemble_report.json").read_text())
    assert report["fam"] == {"items": 2, "missing": 0, "no_position": ["b"]}


def test_produce_routes_a_mixed_family_job_to_each_familys_store(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    a, b = _row("a"), {**_row("b"), "family": "fam2"}
    job = {"subject": "qwen3.5-0.8b", "arm": "jlens", "family": "fam+fam2", "k": 0,
           "specs": [{"row_sha": lr.row_sha(a), "row": a, "family": "fam"},
                     {"row_sha": lr.row_sha(b), "row": b, "family": "fam2"}]}  # fmt: skip
    failed = {**job, "k": 1, "specs": job["specs"][:1]}
    res = {"k": 0, "rows": [{"row_sha": lr.row_sha(a), "row": _cells("a")[0]}],
           "empty_ids": [lr.row_sha(b)],
           "meta": {"n_cells": 1, "total_s": 1, "n_empty_samples": 0, "gpu": "x"}}  # fmt: skip
    monkeypatch.setattr(lr, "jobs_for", lambda args: [job, failed])
    # without the modal package (CI) the module defines no app / read_job: create them
    monkeypatch.setattr(lr, "app", SimpleNamespace(run=nullcontext), raising=False)
    monkeypatch.setattr(
        lr,
        "read_job",
        SimpleNamespace(map=lambda jobs, **kw: [{"k": 1, "error": "boom"}, res]),
        raising=False,
    )
    args = Namespace(subject="qwen3.5-0.8b", arm="jlens", store=str(tmp_path), dry_run=False,
                     verbose=False)  # fmt: skip
    lr.produce(args)
    assert lr.stored_shas(lr.store_path(tmp_path, "qwen3.5-0.8b", "jlens", "fam")) == {
        lr.row_sha(a)
    }
    f2 = lr.store_path(tmp_path, "qwen3.5-0.8b", "jlens", "fam2").read_text().splitlines()
    assert [json.loads(x) for x in f2] == [{"row_sha": lr.row_sha(b), "row": None}]


def test_same_topk_tolerates_only_near_ties():
    t, s = ["a", "b", "c"], [3.0, 2.0, 1.0]
    assert lr.same_topk(t, s, t, s)
    assert lr.same_topk(["a", "b", "c"], [3.0, 2.0, 2.0], ["a", "c", "b"], [3.0, 2.0, 2.0])
    assert lr.same_topk(t, s, ["a", "b", "d"], [3.0, 2.0, 1.0])  # k-th boundary swap
    assert not lr.same_topk(t, s, ["b", "a", "c"], [3.0, 2.0, 1.0])  # a real reorder
    assert not lr.same_topk(t, s, t, [3.0, 2.5, 1.0])  # scores differ


def test_store_lines_with_u2028_survive(setup):
    rows, store, args = setup
    cells = _cells("a")
    cells[0]["tokens"] = ["line\u2028separator"]  # JSON keeps U+2028 raw; splitlines() splits it
    _put(store, rows["fam"][0], cells)
    _put(store, rows["fam"][1], _cells("b"))
    lr.assemble(args)
    out = (Path(args.out) / "fam.jsonl").read_text(encoding="utf-8").split("\n")
    got = [json.loads(x) for x in out if x]
    assert len(got) == 4 and got[0]["tokens"] == ["line\u2028separator"]
