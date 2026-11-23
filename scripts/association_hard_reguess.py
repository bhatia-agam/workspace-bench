"""association_hard, the one-off options-only re-measurement in the bank's frozen option order
(plan 0108, validation); its output `reguess_v1.json` is committed and is an input of
`scripts/build_association_hard_bank.py`.

    python scripts/association_hard_reguess.py --bank items.json --work DIR --out reguess_v1.json

The candidate lists of the `obscure` items were selected on another option order (the
`association` seed), where a blind guesser picked their golds 0.01 of the time; in the bank's
own order it picks them 0.21 of the time. This pass runs the family's blind and described
guessers (`wsbench.baselines.lucky_guessing`) in two replicate measurements (5 draws each of
the same prompt) on every obscure item as the bank shows it; the builder drops an item
guessable in both.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from association_hard_grid import BUILT, GUESS_DRAWS, MEASUREMENTS, MODEL, Calls  # noqa: E402

from wsbench.baselines import lucky_guessing as lg  # noqa: E402

FAMILY = "association_hard"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=Path, required=True, help="the bank built WITHOUT this pass")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; write to a fresh path")
    a.work.mkdir(parents=True, exist_ok=True)
    calls = Calls(a.work)
    bank = json.loads(a.bank.read_text(encoding="utf-8"))["items"]
    items = [
        lg.Item(
            it["name"],
            [list(it["mc"]["options"])],
            [int(it["mc"]["gold_position"])],
            meta={"topic": lg.fine_topic(it["mc"]), "kind": it["kind"]},
        )
        for it in bank
    ]
    kind = {it["name"]: it["kind"] for it in bank}
    reqs = []
    for i, item in enumerate(items):
        if kind[item.id] != "obscure":
            continue
        for v in ("blind", "described"):
            ex = lg.pick_examples(items, i, FAMILY, lg.DEFAULT_SEED) if v == "described" else None
            user = lg.user_message(item, v, FAMILY, ex)
            reqs += [
                (f"guess|{meas}|{item.id}|{v}|{d}", lg.SYSTEM, user)
                for meas in MEASUREMENTS
                for d in range(GUESS_DRAWS)
            ]
    got = calls.run(reqs, lg.schema(1))
    if any(v is None for v in got.values()):
        raise SystemExit("calls failed; re-run")
    out: dict[str, dict[str, dict[str, int]]] = {}
    for item in items:
        if kind[item.id] != "obscure":
            continue
        out[item.id] = {
            meas: {
                v: sum(
                    bool(s := lg.score_draw(got[f"guess|{meas}|{item.id}|{v}|{d}"], item))
                    and s["correct"]
                    for d in range(GUESS_DRAWS)
                )
                for v in ("blind", "described")
            }
            for meas in MEASUREMENTS
        }
    doc = {
        "version": 1,
        "built": BUILT,
        "model": MODEL,
        "what": "per obscure item, hits of 5 of the family's blind and described options-only "
        "guessers on the list in the bank's frozen option order, in two measurements; the "
        "examples of the described guesser are drawn from the bank this pass was given",
        "bank_items": [it["name"] for it in bank],
        "items": out,
    }
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    leak = [n for n, g in out.items() if all(max(g[m].values()) >= 3 for m in MEASUREMENTS)]
    print(f"{len(out)} obscure items measured, {len(leak)} guessable in both measurements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
