"""Validation gate for hinted_cutoff (plan 0063): convert the source's frozen s3d readouts to the
contract, check the native render is byte-equal to the source's, and replay the source's frozen
judge answers through this family's verifier and scorer to the frozen numbers.

    python scripts/hinted_cutoff_replay.py --oracle <ccut>/oracle.json \
        --exist4 <ccut>/exist4.jsonl --out <dir>/hinted_cutoff.jsonl"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from wsbench import reads
from wsbench.banks import load_bank
from wsbench.evals.hinted_cutoff import judge, score
from wsbench.readouts import load_readouts, normalize, write_sidecar
from wsbench.readplan import GRID
from wsbench.registry import bank_path

FROZEN = {"I_flagged": 79, "N_flagged": 36, "count_metric": 43, "pairs_only_I": 46,
          "pairs_only_N": 3}  # fmt: skip
FROZEN_CI = (0.288, 0.486)


def gw_render(orc: dict, positions: list[int]) -> str:
    """Verbatim port of gw ``ccut_stages.render_chunk`` + ``_clip``."""

    def clip(s: str) -> str:
        s = " ".join(s.split())
        return s[:200] + "..." if len(s) > 200 else s

    lines = []
    for i, p in enumerate(positions):
        for layer in sorted(orc, key=int):
            bs = orc[layer][str(p)]
            lines.append(f"p{i} L{layer}: " + " | ".join(clip(b) for b in bs))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oracle", required=True)
    ap.add_argument("--exist4", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    _h, items = load_bank(bank_path("hinted_cutoff"))
    by_id = {it["id"]: it for it in items}
    oracle = json.loads(Path(a.oracle).read_text())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            orc = oracle[it["id"]]
            for layer in sorted(orc, key=int):
                for p in it["positions"]:
                    packed = "\n".join("- " + b for b in orc[layer][str(p)])
                    row = {"id": it["id"], "layer": int(layer), "pos": p, "samples": [packed]}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_sidecar(
        out,
        sampling="prose1",
        reader="olens-s3d-gw-ccut",
        arm="frozen_v1",
        layers=list(GRID),
        reads="full",
        plan_sha=reads.plan_sha("hinted_cutoff"),
    )
    print(f"wrote {out}")

    cells, _rep = load_readouts(out, ids=list(by_id))
    cells, diag = normalize(cells, "prose1")
    assert not any(diag.values()), diag
    per: dict[str, dict[int, dict[int, object]]] = defaultdict(lambda: defaultdict(dict))
    for c in cells:
        per[c.id][c.pos][c.layer] = c
    mats: dict[tuple[str, int], str] = {}
    n_bad = 0
    for it in items:
        for ci, ch in enumerate(judge.chunks(it["positions"])):
            mine = judge.render_chunk(per[it["id"]], ch)
            if mine != gw_render(oracle[it["id"]], ch):
                n_bad += 1
            mats[(it["id"], ci)] = mine
    print(f"render: {len(mats)} chunks, {n_bad} differ from the source")

    pair_role = {(it["pair_id"], it["role"]): it["id"] for it in items}
    flagged: dict[str, bool] = defaultdict(bool)
    seen: set[str] = set()
    for line in Path(a.exist4).read_text().splitlines():
        r = json.loads(line)
        k = r["key"].split("#")
        if k[0] != "reply" or r.get("status") != "ok":
            continue
        item_id = pair_role[(k[1], k[2])]
        f = score.flags_of(r["raw"], mats[(item_id, int(k[3][1:]))])
        assert f is not None, r["key"]
        seen.add(item_id)
        flagged[item_id] |= f["hint_reliance"]
    pairs = judge.pairs_of(items)
    rows = [(flagged[p["I"]["id"]], flagged[p["N"]["id"]]) for p in pairs]
    head = score.headline(rows, [p["cluster"] for p in pairs])
    print(json.dumps(head))
    ok = n_bad == 0 and len(seen) == len(items)
    ok &= all(head[k] == v for k, v in FROZEN.items())
    ok &= all(abs(x - y) < 1e-3 for x, y in zip(head["ci95"], FROZEN_CI, strict=True))
    print("GATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
