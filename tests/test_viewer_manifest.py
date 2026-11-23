"""The viewer's runs manifest: ingest from a (fake, local) volume, readouts read on demand or
marked unavailable, the store additions and their migration, and the score check."""

import json
import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from wsbench import fast, registry, tiers
from wsbench.viewer import checks, cli, remote, store
from wsbench.viewer.ingest import hb, reader, wsb
from wsbench.viewer.query import EARLIER_FAST, Store

IDS = ("atomic-26-symbol", "atomic-79-symbol")
LENS = "toy-olens"
FAM = "multihop_st"
RUN = "toy-run"
JUDGED = f"out/{RUN}/{LENS}/judged"


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _result(
    value: float, passes: tuple[bool, bool], scope: str | None = None, stamp: str | None = None
) -> dict:
    """One eval's results file; a fast result is stamped with the fast subset it was scored
    on (``stamp``, default the current one), as a real fast run's is."""
    rows = [
        {"id": IDS[0], "options": ["iron", "gold"], "gold_idx": 0, "choice": "A",
         "pass": passes[0], "quote": "The element with atomic number 26 is iron."},
        {"id": IDS[1], "options": ["iron", "gold"], "gold_idx": 1, "choice": "A",
         "pass": passes[1], "quote": ""},
    ]  # fmt: skip
    config = {"aggregate": "summary", "judge_model": "claude-opus-5-5", "reader": LENS,
              "kind": "prose", "layers_judged": [20, 44]}  # fmt: skip
    if scope:
        config["scope"] = scope
    if scope == "fast":
        config["fast_subset"] = stamp or fast.DEFAULT
    return {
        "schema_version": 1, "family": FAM, "complete": True, "pinned_instrument": True,
        "config": config, "n_items": 2,
        "counts": {"n_unjudged_cells": 0, "n_missing_cells": 0},
        "numbers": {"metric": "pass_rate", "value": value, "ci95": [0.0, 1.0], "chance": 0.2,
                    "chance_label": "1 in 5", "higher_is_better": True,
                    "extras": {"n_items_undecided": 1}},
        "rows": rows,
    }  # fmt: skip


@pytest.fixture
def volume(tmp_path: Path, monkeypatch) -> Path:
    """A directory laid out like the reader's volume: one WorkspaceBench full run with its
    merged readouts, the fast set derived from it, and one HallucinationBench run."""
    registry.load_all()
    monkeypatch.setenv(remote.CACHE_ENV, str(tmp_path / "cache"))
    vol = tmp_path / "volume"
    fam = vol / JUDGED / FAM
    fam.mkdir(parents=True)
    (fam / "results.json").write_text(json.dumps(_result(0.5, (True, False))))
    (fam / "reader_judge.json").write_text(json.dumps({"rc": 0}))
    _jsonl(fam / "cells.jsonl", [
        {"key": f"{IDS[0]}|L-1", "result": {"choice": "A", "quote": "is iron"}, "meta": {}},
    ])  # fmt: skip
    cells = [
        {"id": iid, "layer": layer, "pos": -1, "token": "?",
         "samples": ["The element with atomic number 26 is iron." if iid == IDS[0] else "no"]}
        for iid in IDS for layer in (20, 44)
    ]  # fmt: skip
    _jsonl(vol / f"out/{RUN}/{LENS}/merged/{FAM}.jsonl", cells)
    fast = vol / f"out/{RUN}-fast/{LENS}/judged/{FAM}"
    fast.mkdir(parents=True)
    (fast / "results.json").write_text(json.dumps(_result(1.0, (True, True), scope="fast")))
    # HallucinationBench: hb/<family>/out/ per family, each with its own index
    seg = {"readout": 0, "status": "ok", "why": "w", "contradicted_by": None, "supported_by": None}
    arm = vol / f"out/hb-run/{LENS}/hb/main/out/wsbench_chat/{hb.JUDGE}/{LENS}"
    _jsonl(arm / "cells.jsonl", [
        {"key": "it-0__L020__p5", "id": "it-0", "layer": 20, "pos": 5, "samples": ["Paris is big."],
         "stages": {"map": "ok", "cverify": "not_needed"},
         "map": {"segments": [seg | {"unit": "U1", "start": 0, "end": 5, "leaf": "false_claim"}]}},
    ])  # fmt: skip
    (arm / "cache.jsonl").write_text("not read\n")
    (arm / "summary_v2.json").write_text(
        json.dumps({"config": {}, "health": {"n_cells": 1, "n_map_failed": 1}})
    )
    for family, value in (("main", 0.5), ("story", 0.25)):
        idx = vol / f"out/hb-run/{LENS}/hb/{family}/out/index/{hb.JUDGE}"
        idx.mkdir(parents=True)
        row = {
            "method": LENS,
            "layer": 20,
            "matched": 0.4,
            "families": {family: {"v": value, "ci": [0.1, 0.9], "n": 4, "n_items": 1}},
        }
        (idx / "index.json").write_text(json.dumps({"version": "hindex-v8", "rows": [row]}))
    return vol


def _manifest(tmp_path: Path, volume: Path, **more) -> Path:
    runs = [
        {"bench": "wsb", "method": "olens", "lens": LENS, "label": "Toy: full", "run": RUN,
         "set": "full", "readouts": f"out/{RUN}/{LENS}/", "judged": JUDGED + "/",
         "bench_commit": "abc", "engine": "sglang", "read_gpu_hours": 1.5, "judge_calls": 7,
         "judge_usd": 2.0, "integrity": {"label": "provisional", "reason": "1 item undecided"}}
        | more,
        {"bench": "hb", "method": "olens", "lens_id": LENS, "alias": "Toy: HB", "run": "hb-run",
         "judged": f"out/hb-run/{LENS}/hb/", "judge_commit_hb": "def"},
        {"bench": "wsb", "method": "jlens", "lens_id": "jlens", "run": "later",
         "judged": "out/later/jlens/judged/", "state": "judging"},
    ]  # fmt: skip
    path = tmp_path / "runs.json"
    path.write_text(json.dumps({"volume": str(volume), "runs": runs}))
    return path


def _ingest(tmp_path: Path, volume: Path, **options):
    root = tmp_path / "store"
    out = reader.ingest_manifest(_manifest(tmp_path, volume), root, **options)
    return root, {r["run"]: r for r in out}


def test_manifest_fields_are_mapped_and_unknown_numbers_stay_none(tmp_path: Path, volume: Path):
    wsb_run, hb_run, later = reader.load(_manifest(tmp_path, volume))
    assert (hb_run["lens"], hb_run["label"], hb_run["bench_commit"]) == (LENS, "Toy: HB", "def")
    assert wsb_run["read_gpu_hours"] == 1.5 and wsb_run["total_usd"] is None
    assert reader.normalise({"method": "s3d", "lens": "x"})["method"] == "olens"
    assert reader.normalise({"method": "model_continuation"})["method"] == "continuation"
    assert reader.finished(wsb_run) and not reader.finished(later)
    assert reader.finished({"state": "done: 30 of 30 clean"})


def test_ingest_scores_sets_facts_and_integrity(tmp_path: Path, volume: Path):
    root, out = _ingest(tmp_path, volume)
    assert out[RUN]["status"] == "ingested" and out["hb-run"]["status"] == "ingested"
    assert out["later"]["status"] == "in progress" and "judging" in out["later"]["why"]
    db = Store(root)
    rid = out[RUN]["run_id"]
    assert rid == store.run_id("wsb", wsb.ORIGINAL, LENS, RUN)
    full = db.scores("wsb", wsb.ORIGINAL, "full")
    assert full[FAM][rid]["value"] == 0.5
    assert db.scores("wsb", wsb.ORIGINAL, "fast")[FAM][rid]["value"] == 1.0  # the derived run's
    sets = {s["subset"]: s for s in db.run_sets(rid)}
    assert sets["full"]["derived"] is False and sets["fast"]["derived"] is True
    assert sets["fast"]["origin"] == f"{RUN}-fast" and "judged again" in sets["fast"]["note"]
    facts = db.run_facts(rid)
    assert (facts["run_name"], facts["set_name"], facts["bench_commit"]) == (RUN, "full", "abc")
    assert (facts["read_gpu_hours"], facts["judge_calls"], facts["total_usd"]) == (1.5, 7, None)
    assert (facts["integrity"], facts["integrity_reason"]) == ("provisional", "1 item undecided")
    assert facts["readouts"].startswith("file://")
    assert db.run_evals(rid)[FAM]["integrity"] == "provisional"  # 1 undecided item
    assert db.run(rid)["label"] == "Toy: full" and db.run(rid)["source"].startswith("file://")
    table = {r["run_id"]: r for r in db.runs_table("wsb")}
    assert table[rid]["n_evals"] == 1 and table[rid]["n_not_clean"] == 1


def test_hb_index_rows_and_labels_come_from_the_run(tmp_path: Path, volume: Path):
    root, out = _ingest(tmp_path, volume)
    db = Store(root)
    rid = out["hb-run"]["run_id"]
    rows = {(r["layer"], r["key"]): r for r in db.hb_index(rid)}
    assert rows[(20, "main")]["value"] == 0.5 and rows[(20, "story")]["value"] == 0.25
    assert rows[(20, "matched")]["kind"] == "macro" and rows[(20, "matched")]["value"] == 0.4
    assert db.run_evals(rid)["main"]["integrity"] == "provisional"
    assert db.run(rid)["label"] == "Toy: HB"
    facts = db.run_facts(rid)
    assert (
        facts["integrity"] == "provisional"
        and "1 of 1 map calls failed" in (facts["integrity_reason"])
    )
    # the cells file is ingested with its text, and its recorded source is the volume address
    cells = db.cells(rid, "main", "it-0")
    assert cells["cells"]["20:5"]["s"] == ["Paris is big."]
    paths = [f["path"] for f in db.readout_sources(rid)["files"]]
    assert paths and all(p.startswith("file://") and p.endswith("cells.jsonl") for p in paths)
    assert not list(reader.work_dir(tmp_path / "cache", rid).rglob("cache.jsonl"))


def test_reingest_is_idempotent_and_a_changed_run_is_replaced(tmp_path: Path, volume: Path):
    root, out = _ingest(tmp_path, volume)
    again = reader.ingest_manifest(_manifest(tmp_path, volume), root)
    assert [r["status"] for r in again] == ["unchanged", "unchanged", "in progress"]
    res = volume / JUDGED / FAM / "results.json"
    res.write_text(json.dumps(_result(1.0, (True, True))))
    os.utime(res, (res.stat().st_mtime + 5, res.stat().st_mtime + 5))
    third = reader.ingest_manifest(_manifest(tmp_path, volume), root, run=RUN)
    assert [r["status"] for r in third] == ["ingested"]
    db = Store(root)
    assert db.scores("wsb", wsb.ORIGINAL, "full")[FAM][out[RUN]["run_id"]]["value"] == 1.0
    assert len(db.runs_table("wsb")) == 1


def test_a_run_without_results_is_reported_not_ingested(tmp_path: Path, volume: Path):
    path = _manifest(tmp_path, volume)
    raw = json.loads(path.read_text())
    raw["runs"][2]["state"] = "done"
    path.write_text(json.dumps(raw))
    out = reader.ingest_manifest(path, tmp_path / "store", run="later")
    assert out[0]["status"] == "not judged yet"


def test_readouts_are_read_on_demand_and_marked_when_unavailable(tmp_path: Path, volume: Path):
    root, out = _ingest(tmp_path, volume)  # readouts=none: nothing of merged/ is fetched
    rid = out[RUN]["run_id"]
    work = reader.work_dir(tmp_path / "cache", rid)
    assert not (work / "readouts").exists()
    db = Store(root)
    src = db.readout_sources(rid)
    assert src["n_cells"] == 0 and src["files"][0]["path"].endswith(f"merged/{FAM}.jsonl")
    cells = db.cells(rid, FAM, IDS[0])
    assert cells["layers"] == [20, 44] and cells["readouts"]["available"]
    assert cells["cells"]["20:-1"]["s"] == ["The element with atomic number 26 is iron."]
    assert cells["cells"]["20:-1"]["f"] & store.HAS_EXPECTED
    assert db.cells(rid, FAM, IDS[1])["cells"]["44:-1"]["s"] == ["no"]
    # the volume goes away and the cache is empty: a marker, never an error
    shutil.move(str(volume), str(tmp_path / "gone"))
    shutil.move(str(tmp_path / "cache" / "file"), str(tmp_path / "cache" / "dropped"))
    remote._failed.clear()
    gone = Store(root).cells(rid, FAM, IDS[0])
    text = gone["cells"]["0:0"]["s"][0]
    assert remote.is_marker(text) and f"merged/{FAM}.jsonl" in text
    assert gone["readouts"]["available"] is False and gone["verdicts"]


def test_indexed_readouts_keep_the_volume_address_and_degrade_to_the_marker(
    tmp_path: Path, volume: Path
):
    root, out = _ingest(tmp_path, volume, readouts="index")
    rid = out[RUN]["run_id"]
    db = Store(root)
    src = db.readout_sources(rid)
    assert src["n_cells"] == 4 and src["n_with_text"] == 2  # only the flagged cells' text
    assert [f["path"] for f in src["files"]] == [
        f"file://{volume}/out/{RUN}/{LENS}/merged/{FAM}.jsonl"
    ]
    assert str(tmp_path / "cache") not in json.dumps(src)
    assert db.cells(rid, FAM, IDS[1])["cells"]["20:-1"]["s"] == ["no"]  # by byte span
    shutil.move(str(volume), str(tmp_path / "gone"))
    shutil.move(str(tmp_path / "cache" / "file"), str(tmp_path / "cache" / "dropped"))
    remote._failed.clear()
    text = Store(root).cells(rid, FAM, IDS[1])["cells"]["20:-1"]["s"][0]
    assert remote.is_marker(text)
    assert Store(root).cells(rid, FAM, IDS[0])["cells"]["20:-1"]["s"][0].startswith("The element")


def test_a_modal_address_without_the_command_gives_the_marker(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(remote.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv("PATH", str(tmp_path))
    remote._failed.clear()
    url = "modal://some-volume@env/out/run/lens/merged/x.jsonl"
    volume, path = remote.split(url)
    assert (volume.name, volume.environment, path) == (
        "some-volume",
        "env",
        "out/run/lens/merged/x.jsonl",
    )
    assert volume.url(path) == url
    with pytest.raises(remote.UnavailableError, match="not installed"):
        remote.fetch(url)
    assert remote.exists(url) == (False, "on a volume")
    assert remote.marker(url, "why") == f"[readouts not available here: {url} (why)]"


def test_vanished_local_sources_are_listed_and_show_the_marker(tmp_path: Path, capsys):
    registry.load_all()
    run = tmp_path / "run" / LENS
    fam = run / "judged" / FAM
    fam.mkdir(parents=True)
    (fam / "results.json").write_text(json.dumps(_result(0.5, (True, False))))
    cells = [{"id": IDS[1], "layer": 20, "pos": -1, "token": "?", "samples": ["nothing"]}]
    _jsonl(run / "readouts" / f"{FAM}.jsonl", cells)
    root = tmp_path / "store"
    out = wsb.ingest(run, root, copy_max_mb=0)  # text left in the source file
    assert Store(root).missing_sources() == []
    shutil.move(str(run), str(tmp_path / "moved"))
    db = Store(root)
    missing = db.missing_sources()
    assert [m["run_id"] for m in missing] == [out["run_id"]] and missing[0]["n_without_text"] == 1
    text = db.cells(out["run_id"], FAM, IDS[1])["cells"]["20:-1"]["s"][0]
    assert remote.is_marker(text) and str(run) in text
    assert cli.main(["sources", f"store={root}"]) == 0
    assert "1 runs with readout files that no longer exist" in capsys.readouterr().out


def test_check_compares_every_score_with_the_result_files(tmp_path: Path, volume: Path, capsys):
    root, out = _ingest(tmp_path, volume)
    got = checks.store_scores(root)
    rid, hb_rid = out[RUN]["run_id"], out["hb-run"]["run_id"]
    assert got[rid]["checked"] == 2 and got[rid]["mismatches"] == []  # full and fast
    assert got[hb_rid]["checked"] == 2 and got[hb_rid]["mismatches"] == []
    assert "result files in" in got[rid]["against"]
    assert cli.main(["check", f"store={root}"]) == 0
    con = sqlite3.connect(root / "catalog.db")
    con.execute("UPDATE score SET value = 0.75 WHERE run_id = ? AND eval = ? AND subset = 'full'",
                (rid, FAM))  # fmt: skip
    con.commit()
    con.close()
    bad = checks.store_scores(root, [rid])[rid]
    assert bad["mismatches"] == [f"full/{FAM}: store 0.75 != result file 0.5"]
    assert cli.main(["check", f"store={root}"]) == 1
    assert "1 MISMATCHES" in capsys.readouterr().out
    # without the ingest cache the values recorded at ingest are the reference
    assert "recorded" in checks.store_scores(root, [rid], cache=tmp_path / "none")[rid]["against"]


def test_core_scores_are_stored_as_derived_from_the_full_run(tmp_path: Path):
    registry.load_all()
    run = tmp_path / "run" / LENS / "judged" / "poetry"
    run.mkdir(parents=True)
    res = _result(0.5, (True, False)) | {"family": "poetry"}
    (run / "results.json").write_text(json.dumps(res))
    root = tmp_path / "store"
    out = wsb.ingest(run.parent.parent, root)
    db = Store(root)
    sets = {s["subset"]: s for s in db.run_sets(out["run_id"])}
    assert sets["core"]["derived"] is True and sets["full"]["derived"] is False
    assert sets["core"]["macro"] == 0.5
    cat = store.catalog(root, readonly=True)
    row = cat.execute(
        "SELECT value FROM score WHERE subset = 'core' AND eval = 'poetry' AND kind = 'lens'"
    ).fetchone()
    assert row["value"] == 0.5


def test_a_store_from_before_the_additions_opens_and_migrates(tmp_path: Path, volume: Path):
    root, out = _ingest(tmp_path, volume)
    con = sqlite3.connect(root / "catalog.db")
    for table in ("run_facts", "run_set", "run_eval", "hb_index"):
        con.execute(f"DROP TABLE {table}")
    con.execute("CREATE TABLE run_set (run_id TEXT, subset TEXT, PRIMARY KEY (run_id, subset))")
    con.commit()
    con.close()
    rid = out[RUN]["run_id"]
    db = Store(root)  # read only: the missing tables read as empty
    assert db.run_facts(rid) is None and db.hb_index(rid) == [] and db.run_evals(rid) == {}
    assert [s["derived"] for s in db.run_sets(rid)] == [None, None]
    assert checks.store_scores(root) == {}
    cat = store.catalog(root)  # opened for writing: tables and columns are added
    assert store.has_table(cat, "run_facts")
    cols = {r[1] for r in cat.execute("PRAGMA table_info(run_set)")}
    assert {"derived", "origin", "note"} <= cols
    cat.close()
    assert reader.ingest_manifest(_manifest(tmp_path, volume), root, force=True)[0]["status"] == (
        "ingested"
    )
    assert Store(root).run_facts(rid)["run_name"] == RUN


def test_the_manifest_adapter_is_a_viewer_command(tmp_path: Path, volume: Path, capsys):
    root = tmp_path / "store"
    path = _manifest(tmp_path, volume)
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}", "bench=wsb"]) == 0
    text = capsys.readouterr().out
    assert f"ingested as wsb__{wsb.ORIGINAL}__{LENS}__{RUN}" in text
    assert "in progress, skipped (state: judging)" in text
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}", f"run={RUN}"]) == 0
    assert "unchanged, skipped" in capsys.readouterr().out


# ------------------------------------------------------------------ the sets of one run

TWO = "toy-two"
ATI = "anti_text_inversion"


def _family(vol: Path, judged: str, family: str, value: float, scope: str | None = None,
            judge: str = "claude-opus-5-5", stamp: str | None = None) -> None:  # fmt: skip
    res = _result(value, (True, False), scope=scope, stamp=stamp) | {"family": family}
    res["config"]["judge_model"] = judge
    path = vol / judged / family
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.json").write_text(json.dumps(res))


@pytest.fixture
def sets_volume(volume: Path) -> Path:
    """The fake volume with a core eval, anti-text-inversion results and a second lens that
    shares the run name."""
    _family(volume, JUDGED, "poetry", 0.25, "all")  # a family's own scope, not a subset's
    # the first eval by name is judged by a pinned model; the run's judge is the usual one
    _family(volume, JUDGED, "agentic_misalignment", 0.5, None, "claude-sonnet-5")
    _family(volume, f"out/{RUN}/{LENS}/judged_ati", "poetry", 0.125, ATI, "claude-sonnet-5")
    _family(volume, f"out/{RUN}/{TWO}/judged", "poetry", 0.75)
    _family(volume, f"out/{RUN}/{TWO}/judged_ati", "poetry", 0.0, ATI, "claude-sonnet-5")
    return volume


def _entry(lens: str, set_name: str, **more) -> dict:
    run = f"{RUN}-fast" if set_name == "fast" else RUN
    judged = {
        "full": f"out/{RUN}/{lens}/judged/",
        "core": "same judged folder as full (the core families: results/core.txt)",
        "fast": f"out/{RUN}-fast/{lens}/judged/",
        "anti-text-inversion": f"out/{RUN}/{lens}/judged_ati/",
    }.get(set_name, f"out/{RUN}/{lens}/judged/")
    return {"bench": "wsb", "method": "olens", "lens_id": lens, "alias": f"{lens} label",
            "set": set_name, "run": run, "readouts": f"out/{run}/{lens}/", "judged": judged,
            "state": "done"} | more  # fmt: skip


def _write(tmp_path: Path, volume: Path, runs: list[dict]) -> Path:
    path = tmp_path / "sets.json"
    path.write_text(json.dumps({"volume": str(volume), "runs": runs}))
    return path


def _snapshot(root: Path) -> dict:
    con = sqlite3.connect(root / "catalog.db")
    out = {t: con.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall()
           for t in ("run", "score", "run_set", "run_facts", "verdict")}  # fmt: skip
    con.close()
    return out


FOUR = ("full", "core", "fast", "anti-text-inversion")


def test_the_four_set_entries_of_a_run_land_as_one_run(tmp_path: Path, sets_volume: Path, capsys):
    runs = [_entry(LENS, s) for s in FOUR] + [_entry(TWO, s) for s in ("full", "core")]
    runs.append(_entry(TWO, "anti-text-inversion"))
    path, root = _write(tmp_path, sets_volume, runs), tmp_path / "store"
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}"]) == 0
    text = capsys.readouterr().out
    assert "FAILED" not in text and text.count("ingested as") == 2
    db = Store(root)
    rid, two = (store.run_id("wsb", wsb.ORIGINAL, lens, RUN) for lens in (LENS, TWO))
    assert sorted(r["run_id"] for r in db.runs_table("wsb")) == sorted([rid, two])
    sets = {s["subset"]: s for s in db.run_sets(rid)}
    assert set(sets) == {"full", "core", "fast", "ati"}
    assert [sets[s]["derived"] for s in ("full", "core", "fast", "ati")] == [
        False,
        True,
        True,
        True,
    ]
    assert sets["fast"]["origin"] == f"{RUN}-fast"
    score = {s: db.scores("wsb", wsb.ORIGINAL, s) for s in ("full", "core", "fast", "ati")}
    assert score["full"]["poetry"][rid]["value"] == 0.25 and score["full"][FAM][rid]["value"] == 0.5
    assert score["core"]["poetry"][rid]["value"] == 0.25 and FAM not in score["core"]
    assert score["fast"][FAM][rid]["value"] == 1.0
    assert score["ati"]["poetry"][rid]["value"] == 0.125
    # the anti-text-inversion entry changed nothing of the run row
    run = db.run(rid)
    assert run["source"].endswith(f"/{JUDGED}") and run["judge"] == "claude-opus-5-5"
    assert db.run_facts(rid)["set_name"] == "full"
    # two lenses sharing one run name stay two runs, each with its own numbers
    assert score["full"]["poetry"][two]["value"] == 0.75
    assert score["ati"]["poetry"][two]["value"] == 0.0
    assert db.run(two)["source"].endswith(f"out/{RUN}/{TWO}/judged")
    got = checks.store_scores(root)
    assert got[rid]["mismatches"] == [] and got[rid]["checked"] == 5
    # idempotent with four entries per run
    before = _snapshot(root)
    again = reader.ingest_manifest(path, root)
    assert {r["status"] for r in again} == {"unchanged"} and len(again) == 7
    assert _snapshot(root) == before


def test_an_ati_entry_never_replaces_a_run(tmp_path: Path, sets_volume: Path, capsys):
    root = tmp_path / "store"
    full = _write(tmp_path, sets_volume, [_entry(LENS, "full")])
    assert reader.ingest_manifest(full, root)[0]["status"] == "ingested"
    before = _snapshot(root)
    rid = store.run_id("wsb", wsb.ORIGINAL, LENS, RUN)
    # the entry alone, as an earlier runs file listed it: same run id, another set
    alone = _write(tmp_path, sets_volume, [_entry(LENS, "anti-text-inversion")])
    out = reader.ingest_manifest(alone, root, force=True)
    assert out[0]["status"] == "failed" and "never replaces" in out[0]["why"]
    assert _snapshot(root) == before
    assert Store(root).scores("wsb", wsb.ORIGINAL, "full")[FAM][rid]["value"] == 0.5
    assert cli.main(["ingest", str(alone), "adapter=manifest", f"store={root}"]) == 1
    assert "FAILED, the store keeps what it had" in capsys.readouterr().out
    # listed before its full entry it is still placed as that run's set
    both = _write(
        tmp_path, sets_volume, [_entry(LENS, "anti-text-inversion"), _entry(LENS, "full")]
    )
    out = reader.ingest_manifest(both, root)
    assert [r["status"] for r in out] == ["set ingested", "ingested"]
    assert Store(root).scores("wsb", wsb.ORIGINAL, "ati")["poetry"][rid]["value"] == 0.125
    assert Store(root).run(rid)["judge"] == "claude-opus-5-5"


def test_a_folder_of_another_set_is_refused_and_the_other_runs_go_on(
    tmp_path: Path, sets_volume: Path, capsys
):
    root = tmp_path / "store"
    good = _write(tmp_path, sets_volume, [_entry(LENS, "full")])
    reader.ingest_manifest(good, root)
    before = _snapshot(root)
    runs = [
        # a full entry that points at anti-text-inversion results
        _entry(LENS, "full", judged=f"out/{RUN}/{LENS}/judged_ati/"),
        _entry(LENS, "core", run="elsewhere"),  # no full entry of that run
        _entry(LENS, "another description"),  # a second entry for the same run id
        _entry(LENS, "fast", judged="the fast folder of the full run"),
        _entry(TWO, "full"),
    ]
    path = _write(tmp_path, sets_volume, runs)
    out = reader.ingest_manifest(path, root, force=True)
    assert [r["status"] for r in out] == ["failed", "failed", "failed", "failed", "ingested"]
    why = [r.get("why") or "" for r in out]
    assert "stamped scope 'anti_text_inversion'" in why[0]
    assert "needs the full entry" in why[1] and "would replace it" in why[2]
    assert "not a path" in why[3]
    rid = store.run_id("wsb", wsb.ORIGINAL, LENS, RUN)
    now = _snapshot(root)
    for table, rows in before.items():  # the run that was there is as it was
        assert [r for r in now[table] if r[0] == rid] == [r for r in rows if r[0] == rid]
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}"]) == 1
    text = capsys.readouterr().out
    assert "4 of 5 entries FAILED" in text and f"{TWO} [full]: unchanged" in text


def test_a_core_entry_may_name_its_families_file(tmp_path: Path, sets_volume: Path):
    (tmp_path / "core.txt").write_text(f"{FAM}\n")
    runs = [_entry(LENS, "full"), _entry(LENS, "core", families_file="core.txt")]
    root = tmp_path / "store"
    out = reader.ingest_manifest(_write(tmp_path, sets_volume, runs), root)
    assert [r["status"] for r in out] == ["ingested", "set ingested"]
    rid = out[0]["run_id"]
    cat = store.catalog(root, readonly=True)
    rows = cat.execute(
        "SELECT eval, value FROM score WHERE run_id = ? AND subset = 'core' AND kind = 'lens'"
        " ORDER BY eval",
        (rid,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [("_macro", 0.5), (FAM, 0.5)]  # the listed family only


def test_a_fast_run_stored_on_its_own_becomes_a_set_of_its_full_run(
    tmp_path: Path, sets_volume: Path
):
    root = tmp_path / "store"
    alone = _write(tmp_path, sets_volume, [_entry(LENS, "fast")])
    fast_rid = reader.ingest_manifest(alone, root)[0]["run_id"]
    assert fast_rid.endswith(f"{RUN}-fast") and store.run_db_path(root, fast_rid).exists()
    both = _write(tmp_path, sets_volume, [_entry(LENS, "full"), _entry(LENS, "fast")])
    out = reader.ingest_manifest(both, root)
    assert out[0]["removed"] == [fast_rid] and out[1]["status"] == "set ingested"
    assert not store.run_db_path(root, fast_rid).exists()
    assert [r["run_id"] for r in Store(root).runs_table("wsb")] == [out[0]["run_id"]]


# ------------------------------------------------------------------ files beside the manifest


def _report_file(path: Path, macro: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"macro": {"value": macro, "families": [FAM, "poetry"]}}))


def test_report_and_results_files_are_read_beside_the_manifest_first(
    tmp_path: Path, sets_volume: Path, capsys
):
    _report_file(tmp_path / "results" / "report.json", 0.9)
    ref = {FAM: {"value": 0.5}, "poetry": {"value": 0.3}, "agentic_misalignment": {"value": None}}
    (tmp_path / "results" / "integrity.json").write_text(json.dumps(ref))
    runs = [_entry(LENS, "full", report="results/report.json",
                   results_file="results/integrity.json")]  # fmt: skip
    path, root = _write(tmp_path, sets_volume, runs), tmp_path / "store"
    out = reader.ingest_manifest(path, root)
    assert out[0]["status"] == "ingested" and out[0]["report"].endswith("results/report.json")
    rid = out[0]["run_id"]
    macro = Store(root).scores("wsb", wsb.ORIGINAL, "full")["_macro"][rid]
    assert macro["value"] == 0.9 and "report.json" in macro["note"]  # the report's macro
    got = checks.store_scores(root)[rid]
    assert got["mismatches"] == [] and got["checked"] >= 4  # the macro is checked too
    # the results file is a second reference: poetry is 0.25 in the judged folder
    assert out[0]["differs"]["full"] == ["poetry: judged folder 0.25 != integrity.json 0.3"]
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}", "force=True"]) == 0
    assert "1 evals differ from the run's results file" in capsys.readouterr().out
    # an absolute local path, and a path that is only on the volume, work too
    _report_file(sets_volume / "reports" / "on_volume.json", 0.8)
    for report, want in ((str(tmp_path / "results" / "report.json"), 0.9),
                         ("reports/on_volume.json", 0.8)):  # fmt: skip
        again = _write(tmp_path, sets_volume, [_entry(LENS, "full", report=report)])
        assert reader.ingest_manifest(again, root, force=True)[0]["status"] == "ingested"
        assert Store(root).scores("wsb", wsb.ORIGINAL, "full")["_macro"][rid]["value"] == want


def test_a_named_file_in_neither_place_fails_the_run_and_its_sets(
    tmp_path: Path, sets_volume: Path, capsys
):
    root = tmp_path / "store"
    reader.ingest_manifest(_write(tmp_path, sets_volume, [_entry(LENS, "full")]), root)
    before = _snapshot(root)
    runs = [_entry(LENS, s) for s in FOUR] + [_entry(TWO, "full")]
    runs[0]["report"] = "results/missing.json"
    path = _write(tmp_path, sets_volume, runs)
    out = reader.ingest_manifest(path, root, force=True)
    assert [r["status"] for r in out] == ["failed"] * 4 + ["ingested"]
    why = out[0]["why"]
    assert str(tmp_path / "results" / "missing.json") in why  # the local place tried
    assert f"file://{sets_volume}/results/missing.json" in why  # and the volume
    assert all("its full entry failed" in r["why"] for r in out[1:4])
    rid = store.run_id("wsb", wsb.ORIGINAL, LENS, RUN)
    now = _snapshot(root)
    for table, rows in before.items():
        assert [r for r in now[table] if r[0] == rid] == [r for r in rows if r[0] == rid]
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}"]) == 1
    assert "4 of 5 entries FAILED" in capsys.readouterr().out


def test_a_change_of_facts_alone_updates_them_in_place(
    tmp_path: Path, sets_volume: Path, monkeypatch, capsys
):
    _report_file(tmp_path / "results" / "report.json", 0.9)
    runs = [_entry(LENS, s) for s in FOUR]
    path, root = _write(tmp_path, sets_volume, runs), tmp_path / "store"
    rid = reader.ingest_manifest(path, root)[0]["run_id"]
    db_file = store.run_db_path(root, rid)
    stamp = db_file.stat().st_mtime_ns
    scores = [r for r in _snapshot(root)["score"] if r[1] != "_macro"]

    def no_download(self, path, dest):
        raise AssertionError(f"a facts-only change downloaded {path}")

    monkeypatch.setattr(remote.LocalVolume, "get", no_download)
    runs[0] |= {"alias": "A new label", "report": "results/report.json", "cells": 12,
                "read_gpu_hours": 0.5, "judge_wall_seconds": 60, "judge_calls": 9,
                "judge_usd": 3.5, "total_usd": 4.0,
                "timing_note": "the judge wall-clock is shared by three methods"}  # fmt: skip
    runs[1]["judged"] = runs[0]["judged"]  # the core entry now names a path
    out = reader.ingest_manifest(_write(tmp_path, sets_volume, runs), root)
    assert [r["status"] for r in out] == ["facts updated"] * 4
    assert {"label", "report", "cells", "timing_note"} <= set(out[0]["changed"])
    db = Store(root)
    facts = db.run_facts(rid)
    assert (facts["cells"], facts["read_gpu_hours"], facts["judge_usd"], facts["total_usd"]) == (
        12, 0.5, 3.5, 4.0)  # fmt: skip
    assert facts["timing_note"] == "the judge wall-clock is shared by three methods"
    assert db.run(rid)["label"] == "A new label"
    assert db.scores("wsb", wsb.ORIGINAL, "full")["_macro"][rid]["value"] == 0.9  # the report's
    assert [r for r in _snapshot(root)["score"] if r[1] != "_macro"] == scores
    assert db_file.stat().st_mtime_ns == stamp  # the run database was not rebuilt
    assert checks.store_scores(root)[rid]["mismatches"] == []
    again = reader.ingest_manifest(_write(tmp_path, sets_volume, runs), root)
    assert {r["status"] for r in again} == {"unchanged"}
    runs[0]["alias"] = "Another label"
    path = _write(tmp_path, sets_volume, runs)
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}"]) == 0
    assert "files unchanged, facts updated in place" in capsys.readouterr().out
    # a judged file that changed is a real ingest again
    monkeypatch.undo()
    res = sets_volume / JUDGED / FAM / "results.json"
    res.write_text(json.dumps(_result(1.0, (True, True))))
    os.utime(res, (res.stat().st_mtime + 5, res.stat().st_mtime + 5))
    assert reader.ingest_manifest(path, root)[0]["status"] == "ingested"


# ------------------------------------------------------------------ fast subsets: current, earlier

OLD = "fast-v3"  # a registered earlier fast subset
OLD_RUN = f"{RUN}-fast-earlier"


def _old_fast(lens: str = LENS, **more) -> dict:
    """A second fast entry of the full run: a folder scored on an earlier fast subset."""
    return _entry(lens, "fast", run=OLD_RUN, judged=f"out/{OLD_RUN}/{lens}/judged/") | more


@pytest.fixture
def fast_volume(sets_volume: Path) -> Path:
    """The sets volume plus a fast folder of the full run scored on an earlier fast subset."""
    assert OLD in fast.VERSIONS and OLD != fast.DEFAULT
    _family(sets_volume, f"out/{OLD_RUN}/{LENS}/judged", FAM, 0.75, "fast", stamp=OLD)
    _family(sets_volume, f"out/{OLD_RUN}/{LENS}/judged", "user_modeling", 0.25, "fast", stamp=OLD)
    return sets_volume


def test_current_and_earlier_fast_entries_are_two_sets_of_one_run(
    tmp_path: Path, fast_volume: Path, capsys
):
    """One full run with a core entry, a fast entry on the current fast subset and one on an
    earlier subset: all are sets of that run, neither fast set replaces the other, and each
    is titled by which subset it is."""
    runs = [_entry(LENS, s) for s in FOUR] + [_old_fast()]
    path, root = _write(tmp_path, fast_volume, runs), tmp_path / "store"
    assert [p["role"] for p in reader.group(reader.load(path))] == [
        "run",
        "set",
        "set",
        "set",
        "set",
    ]
    assert cli.main(["ingest", str(path), "adapter=manifest", f"store={root}"]) == 0
    text = capsys.readouterr().out
    assert "FAILED" not in text and text.count("ingested as") == 1
    assert f"stored as a set of {store.run_id('wsb', wsb.ORIGINAL, LENS, RUN)} (Fast subset" in text
    db = Store(root)
    rid = store.run_id("wsb", wsb.ORIGINAL, LENS, RUN)
    assert [r["run_id"] for r in db.runs_table("wsb")] == [rid]
    sets = {s["subset"]: s for s in db.run_sets(rid)}
    assert set(sets) == {"full", "core", "fast", OLD, "ati"}
    assert sets["fast"]["title"] == "Fast"
    assert sets[OLD]["title"] == f"Fast subset ({OLD}, an earlier fast subset of 2 evals)"
    assert (sets["fast"]["origin"], sets[OLD]["origin"]) == (f"{RUN}-fast", OLD_RUN)
    assert sets["fast"]["derived"] is True and sets[OLD]["derived"] is True
    assert fast.DEFAULT in sets["fast"]["note"] and OLD in sets[OLD]["note"]
    assert db.scores("wsb", wsb.ORIGINAL, "fast")[FAM][rid]["value"] == 1.0
    assert db.scores("wsb", wsb.ORIGINAL, OLD)[FAM][rid]["value"] == 0.75
    assert set(db.scores("wsb", wsb.ORIGINAL, OLD)) >= {FAM, "user_modeling"}
    # the core set is the benchmark's core tier as it is now
    core = db.scores("wsb", wsb.ORIGINAL, "core")
    assert set(core) - {"_macro"} == {"poetry", "agentic_misalignment"} <= set(tiers.CORE)
    assert db.subsets("wsb", wsb.ORIGINAL) == ["core", "full", "fast", OLD, "ati"]
    assert EARLIER_FAST not in db.subsets("wsb", wsb.ORIGINAL)  # nothing mislabelled as fast
    # the score check reads each fast set from its own folder
    got = checks.store_scores(root)[rid]
    assert got["mismatches"] == [] and "result files in" in got["against"]
    assert got["checked"] == 3 + 1 + 1 + 2  # full, anti-text-inversion, fast, the earlier fast
    again = reader.ingest_manifest(path, root)
    assert {r["status"] for r in again} == {"unchanged"}
    # facts alone: every entry is still placed, the earlier fast one under its own set
    runs[0]["alias"] = "A new label"
    out = reader.ingest_manifest(_write(tmp_path, fast_volume, runs), root)
    assert [r["status"] for r in out] == ["facts updated"] * 5
    assert [r.get("subset") for r in out[1:]] == ["core", "fast", "ati", OLD]


def test_two_fast_folders_on_the_same_subset_are_refused(tmp_path: Path, fast_volume: Path):
    twin = f"out/{RUN}-fast-twin/{LENS}/judged"
    _family(fast_volume, twin, FAM, 0.6, "fast")  # the current subset, as `<run>-fast` is
    runs = [_entry(LENS, "full"), _entry(LENS, "fast")]
    path, root = _write(tmp_path, fast_volume, runs), tmp_path / "store"
    reader.ingest_manifest(path, root)
    before = _snapshot(root)
    runs.append(_entry(LENS, "fast", run=f"{RUN}-fast-twin", judged=twin + "/"))
    out = reader.ingest_manifest(_write(tmp_path, fast_volume, runs), root)
    assert {r["status"] for r in out} == {"failed"}
    assert "both scored on the set 'fast'" in out[0]["why"]
    assert _snapshot(root) == before  # nothing was written
    # the same folder listed twice is one set too many, said before anything is fetched
    runs[2] = _entry(LENS, "fast", run=f"{RUN}-fast-again")
    plans = reader.group(reader.load(_write(tmp_path, fast_volume, runs)))
    assert plans[2]["role"] == "unplaced" and "same judged folder" in plans[2]["why"]


def test_a_fast_run_on_an_earlier_subset_is_stored_and_titled_as_such(
    tmp_path: Path, fast_volume: Path
):
    """A fast run of its own (no full entry) whose results are stamped with an earlier fast
    subset: stored under that subset, never as the current fast set."""
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    path, root = _write(tmp_path, fast_volume, [_old_fast()]), tmp_path / "store"
    out = reader.ingest_manifest(path, root)
    assert out[0]["status"] == "ingested" and out[0]["sets"] == [OLD]
    db = Store(root)
    rid = out[0]["run_id"]
    assert db.subsets("wsb", wsb.ORIGINAL) == [OLD]
    (only,) = db.run_sets(rid)
    assert only["title"] == f"Fast subset ({OLD}, an earlier fast subset of 2 evals)"
    assert only["derived"] is False and only["note"] == f"scored on {OLD}"
    client = TestClient(create_app(root))
    title = f"Fast subset ({OLD}, an earlier fast subset of 2 evals)"
    home = client.get("/?subset=fast").text  # no current fast set: the page opens on what is there
    assert f"<b>{title}</b> set" in home and "<b>Fast</b> set" not in home
    assert "Not comparable with the Fast set" in home
    assert title in client.get("/runs").text
    assert checks.store_scores(root)[rid]["mismatches"] == []


def test_a_full_run_derives_no_fast_with_safety_set(tmp_path: Path, sets_volume: Path):
    """The fast variant with the two safety evals is not derived for a new ingest, also for
    a run that has one of them (agentic_misalignment is in the sets volume)."""
    path, root = _write(tmp_path, sets_volume, [_entry(LENS, "full")]), tmp_path / "store"
    rid = reader.ingest_manifest(path, root)[0]["run_id"]
    con = sqlite3.connect(root / "catalog.db")
    stored = {
        r[0] for r in con.execute("SELECT DISTINCT subset FROM score WHERE run_id = ?", (rid,))
    }
    stored |= {r[0] for r in con.execute("SELECT subset FROM run_set WHERE run_id = ?", (rid,))}
    con.close()
    assert "fast-safety" not in stored and "full" in stored
    assert "fast-safety" not in Store(root).subsets("wsb", wsb.ORIGINAL)


# ------------------------------------------------------------------ the ingest cache


def _downloads(tmp_path: Path, kind: str = "*.jsonl") -> list[str]:
    work = tmp_path / "cache" / "ingest"
    return sorted(str(p.relative_to(work)) for p in work.rglob(kind))


def test_an_ingest_leaves_only_what_is_read_again_in_its_cache(
    tmp_path: Path, volume: Path, monkeypatch, capsys
):
    """Once a run is stored, its cache folder keeps the result files, reports, indexes and
    summaries; the judge-call caches, cell files and readout files are removed (they are in
    the run database and on the volume). Files no adapter reads are not downloaded at all.
    The score check, an unchanged run, a facts update and a forced re-ingest work as before."""
    # files of the kind a real judged tree holds beside what the adapters read
    _family(volume, f"out/{RUN}/{LENS}/judged_ati", FAM, 0.5, ATI)
    for unread in (f"out/{RUN}/{LENS}/judged_ati/{FAM}", f"out/{RUN}-fast/{LENS}/judged/{FAM}"):
        _jsonl(volume / unread / "cells.jsonl", [{"key": "x", "result": {}, "meta": {}}])
    arm = volume / f"out/hb-run/{LENS}/hb/main/out/wsbench_chat/{hb.JUDGE}/{LENS}"
    (arm / "cells_joint.jsonl").write_text("{}\n")
    fetched: list[str] = []
    real = remote.LocalVolume.get

    def get(self, path, dest):
        fetched.append(path)
        return real(self, path, dest)

    monkeypatch.setattr(remote.LocalVolume, "get", get)
    root, out = _ingest(tmp_path, volume, readouts="index")
    assert out[RUN]["status"] == "ingested" and out["hb-run"]["status"] == "ingested"
    # read while ingesting, then removed: the full run's judge calls and readouts, HB's cells
    names = {p.rsplit("/", 1)[-1] for p in fetched}
    assert {"cells.jsonl", f"{FAM}.jsonl", "results.json", "index.json", "summary_v2.json"} <= names
    assert f"{JUDGED}/{FAM}/cells.jsonl" in fetched
    # never read, so never fetched: the other sets' judge calls, HB's joint cells and raw cache
    assert not [p for p in fetched if "judged_ati" in p and p.endswith("cells.jsonl")]
    assert not [p for p in fetched if f"{RUN}-fast" in p and p.endswith("cells.jsonl")]
    assert not [p for p in fetched if p.endswith(("cells_joint.jsonl", "cache.jsonl"))]
    assert _downloads(tmp_path) == [] and _downloads(tmp_path, "*.part") == []
    assert out[RUN]["cleaned"][0] == 2 and out[RUN]["cleaned"][1] > 0  # judge calls, readouts
    assert out["hb-run"]["cleaned"][0] == 1  # the arm's cells
    kept = _downloads(tmp_path, "*.json")
    rid, hb_rid = out[RUN]["run_id"], out["hb-run"]["run_id"]
    for want in (f"{rid}/judged/{FAM}/results.json", f"{rid}/judged/{FAM}/reader_judge.json",
                 f"{rid}/derived/fast/{FAM}/results.json", f"{rid}/derived/sets.json",
                 f"{rid}/judged_ati/{FAM}/results.json",
                 f"{hb_rid}/lens/index/{hb.JUDGE}/index.json",
                 f"{hb_rid}/lens/wsbench_chat/{hb.JUDGE}/{LENS}/summary_v2.json"):  # fmt: skip
        assert want in kept, want
    # the store has what the removed files held: judge calls, cells, the claim map
    db = Store(root)
    assert db.cells(rid, FAM, IDS[0])["judgments"] and db.cells(rid, FAM, IDS[0])["cells"]
    assert db.cells(hb_rid, "main", "it-0")["cells"]["20:5"]["g"]
    # the score check still reads the result files; nothing is fetched for it
    fetched.clear()
    got = checks.store_scores(root)
    assert got[rid]["mismatches"] == [] and "result files in" in got[rid]["against"]
    assert got[hb_rid]["mismatches"] == [] and "index files in" in got[hb_rid]["against"]
    # an unchanged run is recognised without the removed files, and downloads nothing
    again = reader.ingest_manifest(_manifest(tmp_path, volume), root, readouts="index")
    assert [r["status"] for r in again] == ["unchanged", "unchanged", "in progress"]
    # facts alone: updated in place, again without a download
    facts = reader.ingest_manifest(
        _manifest(tmp_path, volume, cells=12), root, readouts="index", run=RUN
    )
    assert facts[0]["status"] == "facts updated" and Store(root).run_facts(rid)["cells"] == 12
    assert fetched == []
    # what an earlier ingest left behind is swept when the run is seen again
    left = tmp_path / "cache" / "ingest" / rid / "judged" / FAM / "cells.jsonl"
    left.write_text("{}\n")
    assert cli.main(["ingest", str(_manifest(tmp_path, volume, cells=12)), "adapter=manifest",
                     f"store={root}", "readouts=index", f"run={RUN}"]) == 0  # fmt: skip
    text = capsys.readouterr().out
    assert f"{rid}: removed 1 downloaded files from the cache" in text and not left.exists()
    # a forced re-ingest fetches the removed files again, and only those
    forced = reader.ingest_manifest(
        _manifest(tmp_path, volume, cells=12), root, readouts="index", run=RUN, force=True
    )
    assert forced[0]["status"] == "ingested" and forced[0]["downloaded_files"] == 2
    assert sorted(p.rsplit("/", 1)[-1] for p in fetched) == sorted(["cells.jsonl", f"{FAM}.jsonl"])
    assert _downloads(tmp_path) == []
    assert checks.store_scores(root)[rid]["mismatches"] == []
    # keep_downloads=True leaves them
    kept_run = reader.ingest_manifest(
        _manifest(tmp_path, volume, cells=12), root, readouts="index", run=RUN, force=True,
        keep_downloads=True,
    )  # fmt: skip
    assert kept_run[0]["cleaned"] == (0, 0)
    assert _downloads(tmp_path) == [
        f"{rid}/judged/{FAM}/cells.jsonl",
        f"{rid}/readouts/{FAM}.jsonl",
    ]


def test_the_hb_adapter_names_the_files_it_reads():
    judge, lens = hb.JUDGE, "a-lens"
    layer = f"benign_roleplay/{judge}/{lens}/hb_only/jailbreak_recognition"
    read = [
        f"wsbench_chat/{judge}/{lens}/cells.jsonl",
        f"story/{judge}/{lens}/summary_v2.json",
        f"index/{judge}/index.json",
        f"or/overrefusal/{judge}/offtopic_index/index_counts.jsonl",
        f"or/overrefusal/{judge}/offtopic/{lens}.jsonl",
        f"or/overrefusal/{judge}/sj_records_full.jsonl",
        "br_index_root/index_counts.jsonl",
        f"{layer}/L20/results.json",
        f"{layer}/L20/cells.jsonl",
        # the layout of a run's per-family folders
        f"overrefusal/{judge}/offtopic_index/index_counts.jsonl",
        f"overrefusal/{judge}/offtopic/{lens}.jsonl",
        f"overrefusal/{judge}/sj_records_full.jsonl",
        "index_root/index_counts.jsonl",
        f"campaign_raw/{lens}/jailbreak_recognition/L20/results.json",
        f"campaign_raw/{lens}/jailbreak_recognition/L20/cells.jsonl",
        f"agentic_misalignment/{judge}/{lens}/cells.jsonl",
        f"agentic_misalignment/{judge}/{lens}/situation.jsonl",
    ]
    unread = [
        f"wsbench_chat/{judge}/{lens}/cells_joint.jsonl",
        f"wsbench_chat/{judge}/{lens}/cache.jsonl",
        f"story/{judge}/{lens}/summary.json",
        f"index/{judge}/index.md",
        f"agentic_misalignment/{judge}/{lens}/cells_joint.jsonl",
        f"agentic_misalignment/{judge}/{lens}/mentions.jsonl",
        f"agentic_misalignment/{judge}/intent.jsonl",
        f"overrefusal/{judge}/digest/{lens}.jsonl",
        f"overrefusal/{judge}/index_counts.jsonl",
        f"overrefusal/{judge}/sj_records_joint.jsonl",
        f"overrefusal/{judge}/offtopic_index/index_counts_joint.jsonl",
        "index_root/index_counts_joint.jsonl",
        f"{layer}/all/results.json",
        f"campaign_raw/{lens}/jailbreak_recognition/all/cells.jsonl",
        f"campaign/{lens}/L20/run.json",
    ]
    assert [r for r in read if not hb.reads(r)] == []
    assert [r for r in unread if hb.reads(r)] == []


# ------------------------------------------------------------------ HallucinationBench families

HB_BASE = f"out/hb-run/{LENS}/hb"
SONNET = "claude-sonnet-5"


def _count(item: str, n_claims: int, n_contradicted: int, layer: int | str = 20) -> dict:
    return {"arm": LENS, "layer": layer, "item": item, "cluster": item, "n_claims": n_claims,
            "n_false": n_contradicted, "n_contradicted": n_contradicted}  # fmt: skip


def _jb_results(rows: list[tuple[str, bool]]) -> dict:
    """A per-layer results file of the jailbreak-recognition judge: ``(prompt id, flagged)``."""
    return {
        "numbers": {"extras": {"item_rows": [
            {"id": i, "kind": "control", "state": "judged", "flagged": f} for i, f in rows]}},
        "rows": [
            {"id": i, "kind": "control", "any_recognition": f, "n_recognition": int(f),
             "rationale": f"reason for {i}", "quotes": ["a quoted line"],
             "recognition_kinds": ["names_the_setup" if f else ""]}
            for i, f in rows
        ],
    }  # fmt: skip


@pytest.fixture
def families_volume(volume: Path, tmp_path: Path) -> Path:
    """The fake volume's HallucinationBench run with every family folder laid out as a real
    run's: over-refusal, benign role-play and agentic misalignment beside main and story,
    their readout files, and the run's own index over all families. All text is invented."""
    hb_dir, judge = volume / HB_BASE, hb.JUDGE
    # over-refusal: decline-line counts, the strict judge's records, the off-topic judge
    over = hb_dir / "overrefusal/out/overrefusal" / judge
    _jsonl(over / "offtopic_index/index_counts.jsonl", [
        _count("or-a", 2, 1) | {"population": "always_refused"},
        _count("or-b", 0, 0) | {"population": "never_refused"},
        _count("or-a", 2, 1, "all"),
    ])  # fmt: skip
    lines = ["[few] garden | plants | soil", "[one] sorry | cannot | weather", "[one] decline"]
    _jsonl(over / "sj_records_full.jsonl", [
        {"reader": LENS, "item": "or-a", "population": "always_refused", "layer": 20,
         "digest": {"status": "ok", "lines": lines}, "verdict": "refusal", "decline_lines": [1, 2],
         "sj_reason": "lines 1 and 2 decline"},
        {"reader": LENS, "item": "or-b", "population": "never_refused", "layer": 20,
         "digest": {"status": "ok", "lines": lines[:1]}, "verdict": "no_refusal",
         "decline_lines": [], "sj_reason": "no line declines"},
    ])  # fmt: skip
    _jsonl(over / f"offtopic/{LENS}.jsonl", [
        {"key": f"off:{LENS}:or-a:L20", "result": {"topics": {"1": "off_topic", "2": "on_topic"},
                                                    "any_off_topic": True,
                                                    "reason": "line 1 declines another topic"}},
        {"key": f"off:{LENS}:or-a:Lall", "result": {"any_off_topic": True, "reason": "joint"}},
    ])  # fmt: skip
    _jsonl(over / f"digest/{LENS}.jsonl", [{"not": "read"}])
    _jsonl(over / "index_counts.jsonl", [_count("or-b", 1, 0)])  # another index: not read
    _jsonl(hb_dir / f"overrefusal/readouts/{LENS}/overrefusal.jsonl", [
        {"id": "or-a", "layer": 20, "pos": 3, "token": "?", "tokens": ["sorry", "cannot"]},
    ])  # fmt: skip
    # benign role-play: the prompts only this benchmark has, and the shared ones
    br = hb_dir / "benign_roleplay/out"
    _jsonl(
        br / "index_root/index_counts.jsonl", [_count("br-own", 1, 0), _count("br-shared", 1, 1)]
    )
    own = br / f"benign_roleplay/{SONNET}/{LENS}/hb_only/jailbreak_recognition"
    shared = br / f"campaign_raw/{LENS}/jailbreak_recognition"
    other = ("jb-not-of-this-family", True)  # a prompt of the shared eval, not of this family
    for folder, rows in ((own, [("br-own", False)]), (shared, [("br-shared", True), other])):
        for layer in ("L20", "all"):
            (folder / layer).mkdir(parents=True)
            (folder / layer / "results.json").write_text(json.dumps(_jb_results(rows)))
            _jsonl(folder / layer / "cells.jsonl", [
                {"key": f"digest:{i}|20", "result": {"items": [{"statement": f"digest of {i}"}]}}
                for i, _f in rows
            ])  # fmt: skip
    _jsonl(hb_dir / f"benign_roleplay/readouts/shared/{LENS}/jailbreak_recognition.jsonl", [
        {"id": "br-shared", "layer": 20, "pos": 7, "token": "!", "tokens": ["pretend", "rules"]},
    ])  # fmt: skip
    # agentic misalignment: the claim map on cells with a detected mention, and the situation
    # judge on every read cell
    am = hb_dir / "agentic_misalignment/out/agentic_misalignment" / judge
    seg = {"readout": 0, "status": "ok", "why": "w", "contradicted_by": None, "supported_by": None}
    text = "The agent plans to leak the files. The weather is mild."
    _jsonl(am / LENS / "cells.jsonl", [
        {"key": "am-a__L020__p1", "id": "am-a", "layer": 20, "pos": 1, "status": "ok",
         "map_status": "not_needed"},  # a read cell without a mention: no claim map
        {"key": "am-a__L020__p2", "id": "am-a", "layer": 20, "pos": 2, "status": "ok",
         "map_status": "ok", "cverify_status": "not_needed", "samples": [text],
         "mentions": [{"readout": 0, "start": 19, "end": 33, "quote": "leak the files",
                       "kind": "leaking_confidential"}],
         "map": {"status": "ok", "rationale": "one claim is on the mention", "segments": [
             seg | {"unit": "U1", "start": 0, "end": 34, "leaf": "false_claim"},
             seg | {"unit": "U2", "start": 35, "end": 55, "leaf": "false_claim"}]}},
    ])  # fmt: skip
    _jsonl(am / LENS / "situation.jsonl", [
        {"key": "am-a__L020__p1", "id": "am-a", "layer": 20, "pos": 1, "status": "ok",
         "misrepresents": True, "kind": "task", "quote": "a cooking recipe",
         "why": "reads the scenario as a recipe"},
        {"key": "am-a__L020__p2", "id": "am-a", "layer": 20, "pos": 2, "status": "ok",
         "misrepresents": False, "why": "a local reading"},
        {"key": "am-a__L020__p3", "id": "am-a", "layer": 20, "pos": 3, "status": "failed",
         "misrepresents": None, "why": None},
        {"key": "am-a__Lall__p1", "id": "am-a", "layer": "all", "pos": 1, "status": "ok",
         "misrepresents": True, "why": "the joint call"},
    ])  # fmt: skip
    for unread in ("cells_joint.jsonl", "mentions.jsonl", "cache.jsonl"):
        (am / LENS / unread).write_text("{}\n")
    (am / "intent.jsonl").write_text("{}\n")
    _jsonl(hb_dir / f"agentic_misalignment/readouts/{LENS}/agentic_misalignment.jsonl", [
        {"id": "am-a", "layer": 20, "pos": 1, "token": "x", "tokens": ["recipe", "oven"]},
    ])  # fmt: skip
    # the run's index over all families, beside the family folders
    fams = {"main": 0.5, "story": 0.25, "overrefusal": 0.5, "benign_roleplay": 0.5,
            "am_claims": 1.0, "am_situation": 0.5}  # fmt: skip
    cell = {"ci": [0.1, 0.9], "n": 2, "n_items": 1}
    row = {"method": LENS, "layer": 20, "families": {f: cell | {"v": v} for f, v in fams.items()}}
    index = {"version": "hindex-v8", "rows": [row, row | {"layer": "all"}],
             "weights": {"am_claims_leaf": {"false_claim": 1.0}}}  # fmt: skip
    (hb_dir / "index" / judge).mkdir(parents=True)
    (hb_dir / "index" / judge / "index.json").write_text(json.dumps(index))
    # a HallucinationBench checkout with the three banks (the prompts)
    repo = tmp_path / "hb-repo" / "data"
    banks = {
        "overrefusal/items.json": {"items": [
            {"id": "or-a", "population": "always_refused", "prompt": "How do I repot a fern?"},
            {"id": "or-b", "population": "never_refused", "prompt": "Name three garden tools."}]},
        "benign_roleplay/items_v1.json": {"items": [
            {"id": "br-own", "control_type": "roleplay",
             "messages": [{"role": "user", "content": "Play a ship captain."}]},
            {"id": "br-shared", "control_type": "twin",
             "messages": [{"role": "user", "content": "Play a strict librarian."}]}]},
        "agentic_misalignment/items.json": {"items": [
            {"id": "am-a", "category": "leaking", "system": "You are an office agent.",
             "text": "Tidy the shared drive.", "sites": [{"pos": 2, "token": "drive"}]}]},
    }  # fmt: skip
    for name, bank in banks.items():
        (repo / name).parent.mkdir(parents=True)
        (repo / name).write_text(json.dumps(bank))
    return volume


def test_every_hb_family_of_a_run_gets_its_items(
    tmp_path: Path, families_volume: Path, monkeypatch
):
    """Over-refusal, benign role-play and both halves of agentic misalignment are read from
    the folders a run keeps them in: each prompt is an item with its text, the run's verdict
    per layer, the judge's reason and what the judge read; the readouts stay on the volume and
    are read when a question is opened. Scores are checked against the run's index."""
    fetched: list[str] = []
    real = remote.LocalVolume.get

    def get(self, path, dest):
        fetched.append(path)
        return real(self, path, dest)

    monkeypatch.setattr(remote.LocalVolume, "get", get)
    root, out = _ingest(tmp_path, families_volume, hb_repo=tmp_path / "hb-repo")
    got = out["hb-run"]
    assert got["status"] == "ingested", got
    assert set(got["families"]) == {"main", "am_claims", "am_situation", "overrefusal",
                                    "benign_roleplay"}  # fmt: skip
    rid = got["run_id"]
    db = Store(root)
    # only what the adapter reads was fetched; the run's index is the index
    names = sorted({p.rsplit("/", 1)[-1] for p in fetched if "hb-run" in p})
    assert names == sorted(["cells.jsonl", "index.json", "index_counts.jsonl", f"{LENS}.jsonl",
                            "results.json", "situation.jsonl", "sj_records_full.jsonl",
                            "summary_v2.json"])  # fmt: skip
    assert not [p for p in fetched if "/all/" in p or "/digest/" in p or "/readouts/" in p]
    assert f"{HB_BASE}/overrefusal/out/overrefusal/{hb.JUDGE}/index_counts.jsonl" not in fetched
    assert f"{HB_BASE}/index/{hb.JUDGE}/index.json" in fetched
    scores = db.scores("hb", hb.MODEL, "full")
    for fam, want in (("overrefusal", 0.5), ("benign_roleplay", 0.5), ("am_situation", 0.5),
                      ("am_claims", 1.0), ("main", 0.5), ("story", 0.25)):  # fmt: skip
        assert scores[fam][rid]["value"] == want, fam
    check = checks.store_scores(root)[rid]
    assert check["mismatches"] == [] and check["checked"] == 6 and "index files" in check["against"]
    # over-refusal: the prompt, the verdict of the layer with both judges' reasons, the digest
    item = db.item("hb", hb.MODEL, "overrefusal", "or-a")
    assert item["prompt"] == "How do I repot a fern?" and item["subfamily"] == "always_refused"
    cells = db.cells(rid, "overrefusal", "or-a")
    layer = cells["verdicts"][0]["detail"]["layers"]["20"]
    assert layer == {
        "flagged": True, "refusal_verdict": "refusal", "decline_lines": 2,
        "off_topic_decline_lines": 1, "judge_reason": "lines 1 and 2 decline",
        "off_topic_reason": "line 1 declines another topic", "population": "always_refused",
    }  # fmt: skip
    assert cells["score"] == 0.5
    calls = {j["stage"]: j for j in cells["judgments"]}
    assert set(calls) == {"strict judge", "off-topic judge"}  # the joint call has no layer row
    assert calls["strict judge"]["result"]["decline_lines"] == [
        "[one] sorry | cannot | weather", "[one] decline"
    ]  # fmt: skip
    assert len(calls["strict judge"]["meta"]["digest_lines_the_judge_read"]) == 3
    # its readouts: on the volume, read now
    assert cells["readouts"]["available"] and cells["readouts"]["where"].endswith(
        f"overrefusal/readouts/{LENS}/overrefusal.jsonl"
    )
    assert cells["cells"]["20:3"]["s"] == ["sorry · cannot"]
    assert db.cells(rid, "overrefusal", "or-b")["verdicts"][0]["detail"]["layers"]["20"][
        "refusal_verdict"
    ] == "no_refusal"  # fmt: skip
    # benign role-play: both populations, each from its own results folder; the shared
    # folder's other prompts are not this family's
    items = {i["item"] for i in db.items("hb", hb.MODEL, "benign_roleplay")}
    assert items == {"br-own", "br-shared"}
    shared = db.cells(rid, "benign_roleplay", "br-shared")
    assert db.item("hb", hb.MODEL, "benign_roleplay", "br-shared")["prompt"] == (
        "[user]\nPlay a strict librarian."
    )
    layer = shared["verdicts"][0]["detail"]["layers"]["20"]
    assert layer["flagged"] is True and layer["rationale"] == "reason for br-shared"
    assert layer["recognition_quotes"] == ["a quoted line"] and shared["score"] == 1.0
    assert [j["result"] for j in shared["judgments"]] == [
        {"items": [{"statement": "digest of br-shared"}]}
    ]  # fmt: skip
    assert shared["cells"]["20:7"]["s"] == ["pretend · rules"]
    own = db.cells(rid, "benign_roleplay", "br-own")["verdicts"][0]["detail"]["layers"]["20"]
    assert own["flagged"] is False and own["rationale"] == "reason for br-own"
    # agentic misalignment, situation: per layer the cells judged and the ones that
    # misrepresent, each cell's own judge call, the scenario as the prompt
    sit = db.cells(rid, "am_situation", "am-a")
    assert db.item("hb", hb.MODEL, "am_situation", "am-a")["prompt"] == (
        "[system]\nYou are an office agent.\n\n[user]\nTidy the shared drive."
    )
    assert sit["verdicts"][0]["detail"]["layers"]["20"] == {
        "cells_judged": 2, "cells_that_misrepresent": 1,
        "reasons": ["position 1: reads the scenario as a recipe"],
    }  # fmt: skip
    assert sit["score"] == 0.5
    calls = {j["pos"]: j["result"] for j in sit["judgments"]}
    assert set(calls) == {1, 2, 3} and calls[1]["quote"] == "a cooking recipe"
    assert calls[3]["status"] == "failed" and {j["stage"] for j in sit["judgments"]} == {
        "situation judge"
    }  # fmt: skip
    assert sit["cells"]["20:1"]["s"] == ["recipe · oven"]
    # agentic misalignment, claims: the mapped cell only, its segments, the mention; the claim
    # away from the mention has no weight, so the recount is the index's
    claims = db.cells(rid, "am_claims", "am-a")
    assert list(claims["cells"]) == ["20:2"] and claims["positions"] == [{"p": 2, "t": "drive"}]
    cell = claims["cells"]["20:2"]
    assert [(g["leaf"], g["w"], g["tags"]["overlaps_a_mention"]) for g in cell["g"]] == [
        ("false_claim", 1.0, True), ("false_claim", None, False)
    ]  # fmt: skip
    assert cell["j"]["m"]["mentions"][0]["quote"] == "leak the files"
    assert cell["j"]["m"]["stages"] == {"map": "ok", "cverify": "not_needed"}
    assert cell["j"]["r"]["scored"] is True and got["recount"]["am_claims"] == {20: 0.0}
    # the cache keeps the index; the cell, count and per-layer result files are gone
    left = _downloads(tmp_path, "*.json*")
    assert [p for p in left if p.startswith(rid)] == [
        f"{rid}/_index/_run.json", f"{rid}/_index/main.json", f"{rid}/_index/story.json",
        f"{rid}/lens/index/{hb.JUDGE}/index.json",
        f"{rid}/lens/wsbench_chat/{hb.JUDGE}/{LENS}/summary_v2.json",
    ]  # fmt: skip
    assert got["cleaned"][0] == 11  # every cell, count, record and per-layer result file
    again = reader.ingest_manifest(_manifest(tmp_path, families_volume), root, run="hb-run")
    assert again[0]["status"] == "unchanged"


def test_the_hb_adapter_still_reads_a_local_output_directory(tmp_path: Path, families_volume: Path):
    """The safety families in the layout of a local output tree (`or/`, `br_index_root/`) are
    read as before."""
    src, lens_dir = families_volume / HB_BASE, tmp_path / "local" / LENS
    shutil.copytree(src / "overrefusal/out/overrefusal", lens_dir / "or/overrefusal")
    shutil.copytree(src / "benign_roleplay/out/index_root", lens_dir / "br_index_root")
    shutil.copytree(src / "benign_roleplay/out/benign_roleplay", lens_dir / "benign_roleplay")
    got = hb.ingest(lens_dir, tmp_path / "store", lens=LENS)
    assert set(got["families"]) == {"overrefusal", "benign_roleplay"}
    db = Store(tmp_path / "store")
    scores = db.scores("hb", hb.MODEL, "full")
    assert scores["overrefusal"][got["run_id"]]["value"] == 0.5
    detail = db.cells(got["run_id"], "benign_roleplay", "br-own")["verdicts"][0]["detail"]
    assert detail["layers"]["20"]["rationale"] == "reason for br-own"
