"""The viewer's entry for ``wsbench check``, registered through its plug-in variable:

export WSB_CHECKS="viewer_store=wsbench.viewer.checks:viewer_store"
wsbench check viewer_store
"""

import json
import tempfile
from pathlib import Path

from wsbench import registry
from wsbench.viewer import store
from wsbench.viewer.ingest import wsb

TOY = registry.REPO_ROOT / "examples" / "viewer_toy"


def viewer_store(**options: str) -> tuple[bool, str]:
    """Store ingest round trip: the toy run's scores and verdicts in a fresh store equal its
    results.json."""
    run = Path(options.get("run") or TOY)
    if not (run / "judged").is_dir():
        return False, f"{run}: no judged/ directory (pass options=run=<lens dir>)"
    registry.load_all()
    with tempfile.TemporaryDirectory() as tmp:
        out = wsb.ingest(run, Path(tmp), lens="check")
        cat = store.catalog(Path(tmp), readonly=True)
        bad = []
        for fam, fdir in wsb.family_dirs(run / "judged").items():
            want = json.loads((fdir / "results.json").read_text(encoding="utf-8"))
            got = cat.execute(
                "SELECT value, n FROM score WHERE run_id = ? AND eval = ? AND subset = 'full'"
                " AND layer = -1 AND kind = 'lens'",
                (out["run_id"], fam),
            ).fetchone()
            value = want["numbers"]["value"]
            if value is None:
                continue
            if got is None or abs(got["value"] - value) > 1e-12 or got["n"] != want["n_items"]:
                bad.append(f"{fam}: store {tuple(got) if got else None} != results {value}")
            passed = {
                r["item"]: r["pass"]
                for r in cat.execute(
                    "SELECT item, pass FROM verdict WHERE run_id = ? AND eval = ?",
                    (out["run_id"], fam),
                )
            }
            for row in want["rows"]:
                if "pass" in row and passed.get(row["id"]) != int(bool(row["pass"])):
                    bad.append(f"{fam}/{row['id']}: verdict differs")
        cat.close()
        n_cells = sum(f["cells"] for f in out["families"].values())
    if bad:
        return False, "; ".join(bad[:3])
    return True, f"{len(out['families'])} evals, {n_cells} cells: scores and verdicts round-trip"


TOLERANCE = 1e-12


def store_scores(
    root: Path, runs: list[str] | None = None, cache: Path | None = None
) -> dict[str, dict]:
    """Every manifest-ingested run's headline scores against the run's own result files:
    WorkspaceBench ``results.json`` ``numbers.value`` per eval and set (and the report's
    macro), HallucinationBench the index value per family and layer. The result files are
    re-read from the ingest cache when it still holds them, else the values recorded from
    them at ingest are used. ``{run_id: {checked, mismatches, against}}``."""
    from wsbench.viewer import remote
    from wsbench.viewer.ingest import hb, reader

    cache = remote.cache_root(cache)
    cat = store.catalog(root, readonly=True)
    out: dict[str, dict] = {}
    if not store.has_table(cat, "run_facts"):
        cat.close()
        return out
    rows = cat.execute(
        "SELECT f.run_id, f.headline, r.bench, r.lens, r.judge FROM run_facts f JOIN run r"
        " USING (run_id) ORDER BY f.run_id"
    ).fetchall()
    for r in rows:
        rid = r["run_id"]
        if runs and rid not in runs:
            continue
        want = store.loads(r["headline"], {})
        against = "the values recorded from the result files at ingest"
        work = reader.work_dir(cache, rid)
        if r["bench"] == "hb":
            index = work / "lens" / "index" / (r["judge"] or hb.JUDGE) / "index.json"
            if index.is_file():
                fresh = json.loads(index.read_text(encoding="utf-8"))
                want = {"index": reader.hb_headline(fresh, r["lens"])}
                against = f"the index files in {work}"
        else:
            index = work / "derived" / reader.SET_INDEX  # set -> folder, written at ingest
            folder = json.loads(index.read_text(encoding="utf-8")) if index.is_file() else {}
            dirs = {"ati": work / "judged_ati"} | {
                s: work / "derived" / folder.get(s, s)
                for s in want
                if (work / "derived" / folder.get(s, s)).is_dir()
            }
            main = next((s for s in want if s not in dirs), None)
            if main and (work / "judged").is_dir():
                dirs[main] = work / "judged"
            if all(d.is_dir() for s, d in dirs.items() if s in want) and main in dirs:
                registry.load_all()
                want = {s: reader.wsb_headline(dirs[s])["values"] for s in want}
                against = f"the result files in {work}"
        bad, n = [], 0
        for subset, values in want.items():
            for name, value in values.items():
                layers = value if isinstance(value, dict) else {"-1": value}
                for layer, v in layers.items():
                    if v is None:
                        continue
                    n += 1
                    got = cat.execute(
                        "SELECT value FROM score WHERE run_id = ? AND eval = ? AND subset = ?"
                        " AND layer = ? AND kind = 'lens'",
                        (rid, name, "full" if subset == "index" else subset, int(layer)),
                    ).fetchone()
                    if got is None or abs(got["value"] - v) > TOLERANCE:
                        where = f"{subset}/{name}" + ("" if layer == "-1" else f"/L{layer}")
                        bad.append(
                            f"{where}: store {got['value'] if got else None} != result file {v}"
                        )
        out[rid] = {"checked": n, "mismatches": bad, "against": against}
    cat.close()
    return out


def missing_sources(root: Path) -> list[dict]:
    """Runs whose readout source files no longer exist on this machine."""
    from wsbench.viewer.query import Store

    return Store(root).missing_sources()
