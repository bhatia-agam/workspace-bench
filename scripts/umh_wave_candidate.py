"""The harder wave's candidate file (``wave5_candidate.json``, the builder's ``--wave``) from the
wave's authoring run directory (plan 0112):

    python scripts/umh_wave_candidate.py --harder <run dir> [--redraw-table redraw_table.json] \
        --out wave5_candidate.json [--table-out original_rule_table.json]

Deterministic, no model call: it reads the run's recorded samples and grade memos only.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wsbench import mc, registry  # noqa: E402
from wsbench.evals.association.user_modeling_hard import bank as bk  # noqa: E402

FAMILY = "user_modeling_hard"
BATCHES = ("b1", "b2", "b3", "b4")
WAVE = 5
N_SAMPLES = 10
GATE_NOTE = (
    "label-gate evidence per the ORIGINAL rule, ONE draw per part (the wave's own): the stem leg "
    "`My answer is:` with an empty sample counted as not gold; the no-stem leg only on an empty "
    "stem greedy. `second_draw` beside a record is a diagnostic re-draw of a failing stem leg "
    "(2026-11-23): never the gate record, and the builder admits no item by it"
)

Verdict = Callable[[str, int, str], str | None]


def clean(text: str) -> str:
    """An answer as the authoring run graded it: its first paragraph, at most 300 characters."""
    return re.split(r"\n\s*\n", text.strip())[0].strip()[:300]


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_samples(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def leg(rec: Mapping[str, Any] | None, name: str, part: int, verdict: Verdict) -> dict | None:
    """One leg of the label gate (the authoring run's ``fgrade.leg``): the greedy answer's
    verdict and the count of samples graded ``gold``; an EMPTY answer is ``other``, never
    re-drawn. None when the leg has no greedy answer on record."""
    if rec is None or rec["greedy"] is None:
        return None
    gv = verdict(name, part, rec["greedy"]) if rec["greedy"] else "other"
    sv = [verdict(name, part, a) if a else "other" for a in rec["samples"]]
    n_gold = sum(v == "gold" for v in sv)
    return {
        "greedy": rec["greedy"],
        "greedy_verdict": gv,
        "n_correct": n_gold,
        "n_samples": len(sv),
        "empty_samples": sum(not a for a in rec["samples"]),
        "ungraded": sum(v is None for v in [gv, *sv]),
        "pass": gv == "gold" and len(sv) == N_SAMPLES and n_gold >= bk.MIN_GATE_CORRECT,
    }


def gate_record(
    stem: Mapping[str, Any],
    bare: Mapping[str, Any] | None,
    wave_leg: str,
    redraw: Mapping[str, Any] | None = None,
) -> dict:
    """A part's gate record under the original rule on the wave's own draw. The no-stem leg
    (``bare``) decides only when the stem's GREEDY answer is empty (``stem_dropped``). A re-draw
    of the stem leg (``redraw``, a row of ``redraw_table.json``) is attached as the diagnostic
    ``second_draw`` and changes nothing else: one draw per part gates."""
    dropped = not stem["greedy"] and bare is not None
    use = bare if dropped else stem
    if use["ungraded"]:
        raise SystemExit("a gate answer has no grade on record")
    out = {
        "greedy": use["greedy"],
        "greedy_verdict": use["greedy_verdict"],
        "n_correct": use["n_correct"],
        "n_samples": use["n_samples"],
        "stem_dropped": bool(dropped),
        "stem_empty_samples": stem["empty_samples"],
        "pass_original_rule": bool(use["pass"]),
        "no_stem_leg": None
        if bare is None
        else {k: bare[k] for k in ("greedy", "n_correct", "n_samples")}
        | {"pass": bool(bare["pass"])},
        "wave_gate_leg": wave_leg,
        "draw": 1,
    }
    if redraw is not None:
        if use["pass"] or dropped:
            raise SystemExit("a re-draw is on record for a part that needed none")
        if (redraw["greedy"], redraw["greedy_verdict"]) != (use["greedy"], use["greedy_verdict"]):
            raise SystemExit("the re-draw's greedy answer differs from the wave's")
        fresh = redraw["fresh_original_rule"]
        out["second_draw"] = {
            "n_correct": fresh["n_correct"],
            "n_samples": N_SAMPLES,
            "empty_samples": fresh["empty"],
            "pass": bool(fresh["pass"]),
            "note": "diagnostic only: not the gate record",
        }
    return out


def clean_forms(item: Mapping[str, Any], j: int, broader: Mapping[str, Sequence[str]]) -> list[str]:
    """The part's accepted forms minus one that collides with an option of the item or is a
    broader term of its type (the wave's ``mkbank.clean_forms``)."""
    p = item["parts"][j]
    others = [x for x in p["options"] if x != p["gold"]]
    others += [x for k, q in enumerate(item["parts"]) if k != j for x in q["options"]]
    terms = {mc.fold(b) for b in broader.get(p["type"], [])}
    return [
        f
        for f in p["accepted"]
        if not (any(bk.subset_pair(f, x) for x in others) or mc.fold(f) in terms)
    ]


def build(
    harder: Path, pools: Mapping[str, Any], redraw_rows: Sequence[Mapping[str, Any]]
) -> tuple:
    """``(candidate document, per-part table)`` for the wave's admitted items."""
    broader = pools["broader_classes_never_accepted_as_forms"]
    items: dict[str, dict] = {}
    guess: dict[str, Any] = {}
    opn: dict[str, Any] = {}
    memo: dict[str, Any] = {}
    wgate: dict[str, Any] = {}
    legs: dict[tuple[str, int, str], dict] = defaultdict(lambda: {"greedy": None, "samples": []})
    for b in BATCHES:
        items.update({it["name"]: it for it in load(harder / "cand" / f"{b}.json")["items"]})
        g = load(harder / "out" / f"{b}_guess.json")
        guess.update(g["blind"])
        for n, v in g["prompt_only"].items():
            items[n]["prompt_only"] = v
        opn.update(load(harder / "open" / f"{b}_open.json"))
        memo.update(load(harder / "gate" / f"{b}_grades.json"))
        wgate.update(load(harder / "gate" / f"{b}_gate.json"))
        for r in read_samples(harder / "gate" / f"{b}s1.samples.jsonl"):
            k = r["key"].split("|")
            if k[1] == "reply":
                continue
            e = legs[(k[0], int(k[2][1:]), k[1])]
            if r["greedy"]:
                e["greedy"] = clean(r["text"])
            else:
                e["samples"].append(clean(r["text"]))

    def verdict(n: str, j: int, a: str) -> str | None:
        return (memo.get(f"{n}|{j}|{a}") or {}).get("verdict")

    redraw = {(r["item"], r["part"]): r for r in redraw_rows}
    out, table = [], []
    for n in load(harder / "out" / "admitted.json"):
        it = items[n]
        parts = []
        for j, p in enumerate(it["parts"]):
            stem = leg(legs.get((n, j, "gate")), n, j, verdict)
            bare = leg(legs.get((n, j, "bare")), n, j, verdict)
            if stem is None:
                raise SystemExit(f"{n} p{j}: no stem leg on record")
            wave = wgate[n]["parts"][j]
            try:
                g = gate_record(stem, bare, wave["gate_leg"], redraw.get((n, j)))
            except SystemExit as e:
                raise SystemExit(f"{n} p{j}: {e}") from None
            if g["pass_original_rule"] != bool(wave["pass_strict"]):
                raise SystemExit(f"{n} p{j}: the wave's own strict verdict differs")
            d = (guess[f"{n}|{j}"]["draws"] or [{}])[-1]
            c = opn[n]["conds"]["second|q1"]["parts"][j]
            table.append({"item": n, "part": j, "type": p["type"], "gold": p["gold"], **g})
            parts.append(
                {
                    "attr_label": p["attr_label"],
                    "type": p["type"],
                    "gold": p["gold"],
                    "forms": clean_forms(it, j, broader),
                    "options": p["options"],
                    "near_neighbours": [x for x in p["near_neighbours"] if x in p["options"]],
                    "cues": p["cues"],
                    "gate": g,
                    "open_probe": {
                        "second|q1": {"n_stated": c["n_stated"], "n_samples": c["n_samples"]}
                    },
                    "blind_guess": {"hits": d.get("hits"), "n": d.get("n")},
                    "prompt_only_ok": next(
                        (x["po_ok"] for x in it.get("prompt_only", []) if x["part"] == j), None
                    ),
                }
            )
        out.append(
            {
                "name": n,
                "kind": it["kind"],
                "request_variant": it["request_variant"],
                **({"mixed_state": True} if it.get("mixed") else {}),
                **({"third": it["third"]} if "third" in it else {}),
                "messages": it["messages"],
                "consistency": min(x["gate"]["n_correct"] / x["gate"]["n_samples"] for x in parts),
                "source": it["source"],
                "gate_variant": "chat_revealed_belief",
                "eval_render": "chat_context",
                "authoring": {
                    "model": "claude-opus-5-5",
                    "wave": WAVE,
                    "cues": it["authoring"]["cues"],
                    "tempting_wrong": it["authoring"]["tempting_wrong"],
                },
                "parts": parts,
            }
        )
    doc = {
        "family": FAMILY,
        "status": "candidate (the harder wave of 2026-11-22/23: the 86 items its loosened gate "
        "admitted)",
        "built": "2026-11-23",
        "subject": "Qwen/Qwen3.6-27B",
        "gate_note": GATE_NOTE,
        "items": out,
    }
    return doc, table


def dumps(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--harder", type=Path, required=True, help="the wave's authoring run dir")
    ap.add_argument("--pools", type=Path, default=None, help="default: the family's pools")
    ap.add_argument(
        "--redraw-table",
        type=Path,
        default=None,
        help="redraw_table.json of the diagnostic second draw (recorded, never gating)",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--table-out", type=Path, default=None)
    args = ap.parse_args(argv)
    for path in (args.out, args.table_out):
        if path is not None and path.exists():
            raise SystemExit(f"{path} exists; pass a fresh path")
    pools = load(args.pools or registry.family_root(FAMILY) / "option_pools.json")
    rows = load(args.redraw_table) if args.redraw_table else []
    doc, table = build(args.harder, pools, rows)
    args.out.write_text(dumps(doc), encoding="utf-8")
    if args.table_out is not None:
        args.table_out.write_text(dumps(table), encoding="utf-8")
    ok = [i for i in doc["items"] if all(p["gate"]["pass_original_rule"] for p in i["parts"])]
    print(f"{len(doc['items'])} items; {len(ok)} pass the original rule on every part")
    return 0


if __name__ == "__main__":
    sys.exit(main())
