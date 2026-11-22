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
