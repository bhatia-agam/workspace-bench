"""cutoff_confab: per cell, count the samples naming each option (exclusive longest match); an
item passes when gold strictly out-counts every other option at reply_start, at ONE layer chosen
bank-wide. No call; the rules and the source caveat are in the family README."""

import dataclasses
import json
from collections import defaultdict
from typing import Any

from wsbench.family import fail, pass_rate_result, rate, require_cells, tri_state
from wsbench.llm import Spend
from wsbench.mcjudge import item_scope, with_readout_count
from wsbench.multitoken.family import REGEX_JUDGE
from wsbench.readouts import Cell, load_readouts
from wsbench.registry import REPO_ROOT, JudgeArgs
from wsbench.results import FamilyResult

from .prompts import SCORER_VERSION
from .score import OptionForms, plurality, strict_win, token_bag_text
from .score import best_layer as pick_layer

NAME = "cutoff_confab"
BANK = REPO_ROOT / "evals" / NAME / "items.json"
# read sites as the plan reports them (offsets_from_end [10, 2, 1])
SITES = {-10: "user_end", -2: "think_close", -1: "reply_start"}
HEADLINE_SITE = "reply_start"
HEADLINE_POS = -1
CHANCE_LABEL = (
    "no analytic floor of record; source floors at the same one-layer selection: derangement "
    "0.034, distractor 0.095, G1-conditional line 0.258. Baseline C (stock Qwen, text only) "
    "ties the lens at 0.486 (README caveat)"
)


def load_items() -> list[dict[str, Any]]:
    """The 109 bank items (the separate ``g3_leak_items`` list is never scored)."""
    return json.loads(BANK.read_text(encoding="utf-8"))["items"]


def cell_samples(cell: Cell) -> list[str]:
    """A prose cell's samples, or a token cell's top-k as one bag sample (counts 0/1)."""
    if cell.tokens is not None:
        return [token_bag_text(cell.tokens)] if cell.tokens else []
    return list(cell.samples or ())


def run(args: JudgeArgs) -> FamilyResult:
    which = args.extra.get("judge", "regex")
    if which != "regex":
        fail(f"{NAME}: the regex scorer is the only instrument (opts=judge={which!r})")
    scope = item_scope(load_items(), args)
    ids = [it["id"] for it in scope]
    by_id = {it["id"]: it for it in scope}
    cells, rep = load_readouts(
        args.readouts, ids=ids, layers=args.layers, positions={i: set(SITES) for i in ids}
    )
    forms = {i: OptionForms.build(by_id[i]["option_units"]) for i in ids}
    counts: dict[tuple[str, int, int], dict[str, int]] = {}
    empty: set[tuple[str, int, int]] = set()
    for c in cells:
        samples = cell_samples(c)
        if not any(s.strip() for s in samples):
            empty.add((c.id, c.layer, c.pos))
        counts[(c.id, c.layer, c.pos)] = forms[c.id].counts(samples)

    # the bank layer: only layers with a reply_start readout are candidates
    head_layers = sorted({layer for (_i, layer, pos) in counts if pos == HEADLINE_POS})
    layers = args.layers if args.layers is not None else head_layers
    missing = [
        (i, layer) for i in ids for layer in layers if (i, layer, HEADLINE_POS) not in counts
    ]
    require_cells(NAME, missing, len(ids) * len(layers), args)
    gold = {i: str(by_id[i]["gold"]) for i in ids}

    def win(i: str, layer: int, pos: int = HEADLINE_POS) -> bool | None:
        k = (i, layer, pos)
        return strict_win(counts[k], gold[i]) if k in counts else None

    wins = {layer: sum(1 for i in ids if win(i, layer)) for layer in layers if layer in head_layers}
    chosen = pick_layer(wins)
    present = {c.id for c in cells}
    rows = []
    for i in ids:
        if i not in present:
            continue  # no readouts at all: no row (the ATI gate relies on this)
        k = (i, chosen, HEADLINE_POS) if chosen is not None else None
        c = counts.get(k) if k else None
        rows.append(
            {
                "id": i,
                "gold": gold[i],
                "layer": chosen,
                "pass": tri_state(c is not None and strict_win(c, gold[i]), c is None),
                # the ATI gate's looser rule: gold named by any sample at the chosen cell
                "ati_pass": None if c is None else c.get(gold[i], 0) > 0,
                "counts": c,
                "stratum": by_id[i].get("stratum"),
                "label_type": by_id[i].get("label_type"),
                "win_by_layer": {
                    str(L): win(i, L) for L in head_layers if (i, L, HEADLINE_POS) in counts
                },
            }
        )
    decided = [r for r in rows if r["pass"] is not None]
    per_site: dict[str, dict[str, float | None]] = {}
    site_layers = sorted({layer for (_i, layer, _p) in counts})
    for pos, site in SITES.items():
        per_site[site] = {
            str(L): rate(bool(win(i, L, pos)) for i in ids if (i, L, pos) in counts)
            for L in site_layers
            if any((i, L, pos) in counts for i in ids)
        }
    at = [counts[(i, chosen, HEADLINE_POS)] for i in ids if (i, chosen, HEADLINE_POS) in counts]
    at_gold = [gold[i] for i in ids if (i, chosen, HEADLINE_POS) in counts]
    by: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for r in decided:
        for key in ("stratum", "label_type"):
            by[key][str(r[key])].append(bool(r["pass"]))
    result = pass_rate_result(
        name=NAME,
        args=dataclasses.replace(args, judge=REGEX_JUDGE),
        prompt_version=SCORER_VERSION,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(ids) * len(layers),
        n_missing=len(missing),
        n_unjudged=0,
        n_empty=len({(i, L) for (i, L, p) in empty if p == HEADLINE_POS}),
        spend=Spend(),
        chance_label=CHANCE_LABEL,
        config_extra={
            "layers_judged": layers,
            "scorer": "regex",
            "scorer_version": SCORER_VERSION,
            "headline_site": HEADLINE_SITE,
        },
        extras={
            "n_calls": 0,
            "headline_layer": chosen,
            "candidate_layers": head_layers,
            "wins_by_layer": {str(L): n for L, n in wins.items()},
            "per_layer_strict": per_site,
            "tie_split_at_layer": (
                sum(plurality(c, g) for c, g in zip(at, at_gold, strict=True)) / len(at)
                if at
                else None
            ),
            "ati_pass_rate": rate(bool(r["ati_pass"]) for r in decided),
            "by_stratum": {k: rate(v) for k, v in sorted(by["stratum"].items())},
            "by_label_type": {k: rate(v) for k, v in sorted(by["label_type"].items())},
            "n_empty_cells_all_sites": len(empty),
            "caveat": "decoder prior: Baseline C (stock Qwen, prompt text only) ties the lens "
            "at 0.486, so this family cannot separate reading the activation from re-deriving "
            "Qwen's answer from the question",
        },
    )
    return with_readout_count(result, scope, cells)
