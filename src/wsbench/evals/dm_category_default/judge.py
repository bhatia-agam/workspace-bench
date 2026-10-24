"""dm_category_default: regex any-target over the carrier grid, the gold and every distractor
option scored by one matcher (symmetric units); no LLM call. Rules in the family README."""

import dataclasses
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from wsbench.family import fail, mean, pass_rate_result, rate, require_cells, tri_state
from wsbench.judge_config import ResolvedJudge
from wsbench.llm import Spend
from wsbench.mcjudge import item_scope, with_readout_count
from wsbench.multitoken.regex import unicode_word_matcher
from wsbench.readouts import Cell, load_readouts
from wsbench.registry import REPO_ROOT, JudgeArgs
from wsbench.results import FamilyResult, bootstrap_ci

from .prompts import PROMPT_VERSION, render_user

NAME = "dm_category_default"
BANK = REPO_ROOT / "evals" / NAME / "items.json"
SCORER = "regex"
REGEX_JUDGE = ResolvedJudge(model=SCORER, reasoning=None, pinned=True, source="family")
CHANCE_LABEL = (
    "no analytic floor for an any-cell regex hit; the measured floor is the mean distractor "
    "option on the identical grid (extras.distractor_rate, source 0.289)"
)

# option -> layer -> one hit flag per read cell of that layer
OptionHits = Mapping[str, Mapping[int, Sequence[bool]]]


def load_items(path: Path = BANK) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(header, items)`` of the frozen bank (items carry their own ``id``)."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    items = d["items"]
    ids = [it["id"] for it in items]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path}: duplicate item ids")
    return {k: v for k, v in d.items() if k != "items"}, items


def option_forms(item: Mapping[str, Any]) -> dict[str, list[str]]:
    """Every option's regex forms, in option order (the gold's are its ``units[0].match``)."""
    return {o: list(item["option_units"].get(o) or []) for o in item["options"]}


def cell_samples(cell: Cell) -> list[str]:
    """The strings a cell is matched against, one at a time: prose samples, or each top-k token
    (``Ġ``/``▁`` read as the space they encode). Nothing is joined or stripped."""
    if cell.tokens is not None:
        return [t.replace("Ġ", " ").replace("▁", " ") for t in cell.tokens]
    return list(cell.samples or ())


def cell_hits(
    samples: Sequence[str], matchers: Mapping[str, Sequence[Callable[[str], bool]]]
) -> dict[str, bool]:
    """Per option: does any of its forms hit any SINGLE sample (an empty form list never hits)."""
    return {o: any(m(s) for s in samples for m in ms) for o, ms in matchers.items()}


def item_row(
    item: Mapping[str, Any], hits: OptionHits, missing_layers: Sequence[int]
) -> dict[str, Any]:
    """One item's verdict from its per-cell option hits. Pass = the gold hits ANY cell (any read
    position x any layer); no hit with a missing layer is undecided. Every non-gold option is
    scored by the same rule; ``distractor_rate`` is their mean any-hit."""
    gold = item["gold"]
    options = list(item["options"])
    any_hit = {o: any(any(v) for v in hits.get(o, {}).values()) for o in options}
    cells = sum(len(v) for v in hits.get(gold, {}).values())

    def cell_rate(o: str) -> float:
        flags = [b for v in hits.get(o, {}).values() for b in v]
        return sum(flags) / len(flags) if flags else 0.0

    distractors = [o for o in options if o != gold]
    return {
        "id": item["id"],
        "pass": tri_state(any_hit[gold], bool(missing_layers)),
        "gold": gold,
        "gold_hit_layers": sorted(L for L, v in hits.get(gold, {}).items() if any(v)),
        "option_any_hit": any_hit,
        "distractor_rate": (
            sum(any_hit[o] for o in distractors) / len(distractors) if distractors else 0.0
        ),
        "gold_cell_rate": cell_rate(gold),
        "distractor_cell_rate": (
            sum(cell_rate(o) for o in distractors) / len(distractors) if distractors else 0.0
        ),
        "layer_any_hit": {
            str(L): {o: any(hits.get(o, {}).get(L, ())) for o in options}
            for L in sorted({L for v in hits.values() for L in v})
        },
        "n_cells": cells,
        "missing_layers": list(missing_layers),
    }


def summary_extras(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Gold vs distractor on the complete items (no missing layer): the mean distractor rate,
    the paired gold-minus-distractor gap with a bootstrap CI, cell rates and per-layer rates."""
    full = [r for r in rows if not r["missing_layers"]]
    gaps = [float(r["option_any_hit"][r["gold"]]) - r["distractor_rate"] for r in full]
    layers = sorted({L for r in full for L in r["layer_any_hit"]}, key=int)

    def layer_dis(r: Mapping[str, Any], layer: str) -> float:
        d = [h for o, h in r["layer_any_hit"].get(layer, {}).items() if o != r["gold"]]
        return sum(d) / len(d) if d else 0.0

    return {
        "n_items_complete": len(full),
        "gold_rate_complete": rate(bool(r["pass"]) for r in full),
        "distractor_rate": mean(r["distractor_rate"] for r in full),
        "gold_minus_distractor": mean(gaps),
        "gold_minus_distractor_ci95": bootstrap_ci(gaps) if gaps else None,
        "gold_cell_rate": mean(r["gold_cell_rate"] for r in full),
        "distractor_cell_rate": mean(r["distractor_cell_rate"] for r in full),
        "per_layer": {
            L: {
                "gold": rate(bool(r["layer_any_hit"].get(L, {}).get(r["gold"])) for r in full),
                "distractor": mean(layer_dis(r, L) for r in full),
            }
            for L in layers
        },
    }


def run(args: JudgeArgs) -> FamilyResult:
    _header, items = load_items()
    bad = [it["id"] for it in items if it["user"] != render_user(it["topic"], it["carrier"])]
    if bad:
        fail(f"{NAME}: {len(bad)} bank items whose user turn is not the template (first {bad[0]})")
    scope = item_scope(items, args)
    ids = [it["id"] for it in scope]
    cells, rep = load_readouts(args.readouts, ids=ids, layers=args.layers)
    layers = args.layers if args.layers is not None else rep.layers
    present = {(c.id, c.layer) for c in cells}
    missing = [(i, L) for i in ids for L in layers if (i, L) not in present]
    require_cells(NAME, missing, len(ids) * len(layers), args)

    by_item: dict[str, list[Cell]] = defaultdict(list)
    for c in cells:
        by_item[c.id].append(c)
    rows = []
    for it in scope:
        if not by_item.get(it["id"]):
            continue  # no readouts at all: no row (never a silent fail, never a decided item)
        matchers = {o: [unicode_word_matcher(f) for f in fs] for o, fs in option_forms(it).items()}
        hits: dict[str, dict[int, list[bool]]] = {o: defaultdict(list) for o in matchers}
        for c in sorted(by_item[it["id"]], key=lambda c: (c.layer, c.pos)):
            for o, h in cell_hits(cell_samples(c), matchers).items():
                hits[o][c.layer].append(h)
        miss = [L for L in layers if (it["id"], L) not in present]
        rows.append(item_row(it, hits, miss))
    result = pass_rate_result(
        name=NAME,
        args=dataclasses.replace(args, judge=REGEX_JUDGE),
        prompt_version=PROMPT_VERSION,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(ids) * len(layers),
        n_missing=len(missing),
        n_unjudged=0,
        n_empty=sum(1 for c in cells if c.empty),
        spend=Spend(),
        chance_label=CHANCE_LABEL,
        config_extra={"layers_judged": layers, "scorer": SCORER, "scorer_version": PROMPT_VERSION},
        extras=summary_extras(rows),
    )
    return with_readout_count(result, scope, cells)
