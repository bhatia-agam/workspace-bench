"""ttt_move: a blind MC judge over the board's empty squares with the verbatim move-quote rule,
one call per (item, layer) at the token before the move; an item passes when the judge is right
at any layer. Floors and the source record are in the family README."""

import json
from collections import Counter
from typing import Any

from wsbench.cache import Cache
from wsbench.family import fail, pass_rate_result, rate, require_cells
from wsbench.llm import Spend
from wsbench.mcjudge import Call, Preflighter, item_scope, run_calls, with_readout_count
from wsbench.readouts import Cell, load_readouts
from wsbench.registry import REPO_ROOT, JudgeArgs
from wsbench.results import FamilyResult

from .prompts import JLENS_TOP, PROMPT_VERSION, SCHEMA, SYSTEM, SYSTEM_JLENS, render_user
from .score import cell_verdict, item_row, judge_options

NAME = "ttt_move"
BANK = REPO_ROOT / "evals" / NAME / "items.json"
PRIMARY_LAYER = 52  # the source's pre-registered cell, reported for continuity
CHANCE_LABEL = (
    "per-cell uniform chance mean 1/K = 0.313; the any-of-11 analytic floor saturates (0.984) "
    "because the judge can answer NONE; the measured best-of-11 floors are the source's "
    "prompt-only Opus / Sonnet readers (0.000 / 0.007) and the position-mapped derangement "
    "null (0.380)"
)


def load_items() -> list[dict[str, Any]]:
    """The 150 scored bank items (``items``); ``set_c`` and ``r3_fewshot`` are never scored.
    The bank's ``options`` must equal the source's seeded order (asserted on load)."""
    items = json.loads(BANK.read_text(encoding="utf-8"))["items"]
    for it in items:
        if it["options"] != judge_options(it):
            raise ValueError(f"{NAME}: bank options of {it['id']} differ from the seeded order")
    return items


def samples_of(cell: Cell) -> tuple[list[str], str]:
    """``(samples, system)``: a prose cell is its samples as produced; a token cell is one
    sample of its first ten tokens, comma-joined (the source's J-lens rendering)."""
    if cell.tokens is not None:
        toks = [t.strip() for t in cell.tokens[:JLENS_TOP] if t.strip()]
        return ([", ".join(toks)] if toks else []), SYSTEM_JLENS
    return list(cell.samples or ()), SYSTEM


def run(args: JudgeArgs) -> FamilyResult:
    items = load_items()
    scope = item_scope(items, args)
    ids = [it["id"] for it in scope]
    by_id = {it["id"]: it for it in scope}
    # the read cell is the final token of the chat render (the bank's read_pos, or -1)
    positions = {it["id"]: {int(it["read_pos"]), -1} for it in scope}
    cells, rep = load_readouts(args.readouts, ids=ids, layers=args.layers, positions=positions)
    layers = args.layers if args.layers is not None else rep.layers
    if not layers and cells:
        fail(f"{NAME}: no layers in the readouts")
    chosen: dict[tuple[str, int], Cell] = {}
    n_extra = 0
    for c in cells:
        k = (c.id, c.layer)
        if k in chosen:
            n_extra += 1
            if c.pos >= 0:  # the explicit read_pos wins over a -1 duplicate
                chosen[k] = c
        else:
            chosen[k] = c
    missing = [(i, L) for i in ids for L in layers if (i, L) not in chosen]
    require_cells(NAME, missing, len(ids) * len(layers), args)

    options = {i: judge_options(by_id[i]) for i in ids}
    texts: dict[tuple[str, int], tuple[list[str], str]] = {}
    empty: set[tuple[str, int]] = set()
    for k, c in chosen.items():
        samples, system = samples_of(c)
        if c.empty or not samples:
            empty.add(k)
        else:
            texts[k] = (samples, system)

    spend = Spend()
    with Cache(args.out / "cells.jsonl") as cache:
        calls = [
            Call(
                key=f"{i}|L{L:03d}",
                system=system,
                user=render_user(samples, options[i], by_id[i]["names_a"]),
                meta={"item": i, "layer": L},
            )
            for (i, L), (samples, system) in sorted(texts.items())
        ]
        results = run_calls(
            calls,
            schema=SCHEMA,
            judge=args.judge,
            prompt_version=PROMPT_VERSION,
            cache=cache,
            spend=spend,
            concurrency=args.concurrency,
            rpm=args.rpm,
            dry_run=args.dry_run,
            preflight=Preflighter(args.dry_run).for_judge(args.judge),
        )

    per_item: dict[str, dict[int, dict[str, Any]]] = {i: {} for i in ids}
    for c in calls:
        i, layer = c.meta["item"], c.meta["layer"]
        it = by_id[i]
        per_item[i][layer] = cell_verdict(
            results.get(c.key),
            samples=texts[(i, layer)][0],
            options=options[i],
            names=it["names_a"],
            gold=int(it["label_square"]),
        )
    for i, layer in empty:
        per_item[i][layer] = {
            "judged": True,
            "pick": None,
            "correct": False,
            "why": "empty readout",
            "quote": "",
            "ati": False,
        }
    rows = [
        item_row(
            by_id[i],
            options[i],
            per_item[i],
            n_missing=sum(1 for k in missing if k[0] == i),
            empty_layers=[L for (j, L) in empty if j == i],
        )
        for i in ids
    ]
    verdicts = [(L, v) for i in ids for L, v in per_item[i].items()]
    judged = [(L, v) for L, v in verdicts if v["judged"]]
    decided = [r for r in rows if r["pass"] is not None]
    result = pass_rate_result(
        name=NAME,
        args=args,
        prompt_version=PROMPT_VERSION,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(ids) * len(layers),
        n_missing=len(missing),
        n_unjudged=sum(1 for _L, v in verdicts if not v["judged"]),
        n_empty=len(empty),
        spend=spend,
        chance_label=CHANCE_LABEL,
        skipped_extra=n_extra,
        config_extra={"layers_judged": layers, "options": "empty squares, source seeded order"},
        extras={
            "n_calls": len(calls),
            "per_layer_hit_rate": {
                str(L): rate(v["correct"] for La, v in judged if La == L) for L in layers
            },
            "primary_layer": PRIMARY_LAYER,
            "primary_layer_rate": rate(v["correct"] for L, v in judged if L == PRIMARY_LAYER),
            "earliest_layer": dict(Counter(str(r["earliest_layer"]) for r in decided if r["pass"])),
            "quote_checks": dict(Counter(v["why"] for _L, v in judged)),
            # gate-only (plan 0016): the letter is the gold ignoring the quote check, or a sample
            # states the gold under quote.stated_moves; never the family value
            "ati_pass_rate": rate(bool(r["ati_pass"]) for r in decided),
            "by_kind": {
                k: rate(bool(r["pass"]) for r in decided if str(r["kind"]) == k)
                for k in sorted({str(r["kind"]) for r in decided})
            },
            "by_mover": {
                m: rate(bool(r["pass"]) for r in decided if str(r["mover"]) == m)
                for m in sorted({str(r["mover"]) for r in decided})
            },
        },
    )
    return with_readout_count(result, scope, cells)
