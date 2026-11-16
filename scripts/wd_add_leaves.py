"""Add classes the wrong_intermediate kind check expanded but the frozen class table lacks
(leaves past build_wd_tables.py's walk depth, plan 0089), each with its P279 parents; grow-only.

    python scripts/wd_add_leaves.py src/wsbench/adapt/data/wd_class_parents.json Q... Q...
"""

import importlib.util
import sys
from pathlib import Path

if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"):  # never treat a flag as the table path
    raise SystemExit(__doc__)
spec = importlib.util.spec_from_file_location(
    "bwt", Path(__file__).resolve().parent / "build_wd_tables.py"
)
bwt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bwt)
path, qids = Path(sys.argv[1]), sys.argv[2:]
meta, parents = bwt._existing(path, "parents")
todo = [q for q in qids if q not in parents]
got = bwt.Api(0.5).entities(todo)
fresh = {q: bwt.values(got.get(q) or {}, "P279") for q in todo}
merged = bwt.grow(parents, fresh)
meta = {
    **meta,
    "n_classes": len(merged),
    "added_leaves_plan_0089": sorted(set(meta.get("added_leaves_plan_0089", [])) | set(todo)),
}
bwt._write(path, meta, "parents", merged)
print("added", fresh)
