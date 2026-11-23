"""Generate one tier C batch of new invented entities for the model_multihop adapted sets (plan 0078
R51-R52): gw's sibling-country route (Opus 5.5 writes, Sonnet 5.5 screens), deduplicated against
the pool and earlier batches, written to ``$WSB_POOL_DIR/mmh_tierc_b<k>.json``; pin the printed
sha256 in ``wsbench.adapt.mmh_tierc.TIERC_SHA256[k]``.

    WSB_ANTHROPIC_AUTH=sdk ANTHROPIC_PROFILE=default \\
        python scripts/archive/build_mmh_tierc.py --batch 1
"""

import argparse
import hashlib
import json
from collections import Counter

from wsbench.adapt import mmh_tierc as t
from wsbench.adapt.refill import load_pool, pool_dir
from wsbench.adapt.selfans import claude_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--n", type=int, default=t.BATCH_N)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()
    d = pool_dir()
    out = t.batch_path(d, a.batch)
    if out.exists():
        raise SystemExit(f"{out} exists: a batch is generated once")
    earlier = {k: v for k, v in t.TIERC_SHA256.items() if k < a.batch}
    if sorted(earlier) != list(range(1, a.batch)):
        raise SystemExit(f"batch {a.batch}: batches 1..{a.batch - 1} must be pinned first")
    pool = load_pool("mmh")
    heads = t.batch_headers(d, earlier)
    pool_names = [r["entity_name"] for r in pool["invented"]]
    known = pool_names + [r["entity_name"] for r in t.load_batches(d, earlier)]
    known += [x for h in heads for x in h["names_past_cut"]]
    avoid_tail = pool_names + [x for h in heads for x in h["raw_names"]]
    cache = d / f"mmh_tierc_b{a.batch}.claude"
    gen = claude_json(t.OPUS, cache.with_suffix(".opus.jsonl"), max_tokens=12000)
    scr = claude_json(t.SONNET, cache.with_suffix(".sonnet.jsonl"), max_tokens=12000)
    res = t.build_batch(a.batch, gen, scr, known, avoid_tail, n=a.n, workers=a.workers)
    rows = res["rows"]
    header = {
        "plan": "0078 R51-R52 (tier C)",
        "batch": a.batch,
        "gw_commit": t.GW_COMMIT,
        "ported_sha256": t.ported_hashes(),
        "models": {"generate": t.OPUS, "screen": t.SONNET},
        "rule": "sibling route; drop real / marker / top-1 p >= 0.7 / dup (whole-word "
        "containment against the pool and earlier batches); first "
        f"{a.n} kept rows in (pass, cluster, reply) order",
        "pool_sha256": hashlib.sha256((d / "mmh_pool.json").read_bytes()).hexdigest(),
        "n_rows": len(rows),
        "short": res["short"],
        "n_pass": res["n_pass"],
        "retired_clusters": res["retired"],
        "pass_cap_hit": res.get("pass_cap_hit", False),
        "n_raw": res["n_raw"],
        "raw_names": res["raw_names"],
        "names_past_cut": res["names_past_cut"],
        "drops": res["drops"],
        "counts": {
            "cluster": dict(Counter(r["cluster"] for r in rows)),
            "type": dict(Counter(r["type"] for r in rows)),
        },
    }
    out.write_text(json.dumps({"header": header, "invented": rows}, ensure_ascii=False, indent=1))
    print(f"{out}: {len(rows)} rows; sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}")
    print(json.dumps(header, indent=1))


if __name__ == "__main__":
    main()
