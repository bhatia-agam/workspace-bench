"""The single-token basic families: the bank judge with the any-layer item rule."""

from collections import defaultdict
from pathlib import Path
from typing import Any

from wsbench.banks import exact_targets, item_targets, load_bank
from wsbench.basic.judge import CellKey, JudgeOutcome, NullOutcome, judge_cells, judge_null_cells
from wsbench.basic.prompts import PROMPT_VERSION, cell_samples
from wsbench.cache import Cache
from wsbench.family import pass_rate_result, require_cells, tri_state
from wsbench.judge_config import JudgeConfig
from wsbench.llm import Spend
from wsbench.mcjudge import Preflighter, item_scope, with_readout_count
from wsbench.nulls import K_FOIL, bank_partners, load_foils, null_summary, surface_free
from wsbench.readouts import Cell, load_readouts
from wsbench.registry import REPO_ROOT, EvalSpec, JudgeArgs
from wsbench.results import FamilyResult

GROUP = "basic"
CHANCE_LABEL = "no analytic floor (free text); the prompt-only baseline is the measured floor"


def bank_family(name: str, title: str, *, n_items: int = 100, n_layers: int = 11) -> EvalSpec:
    bank = Path("evals") / name / "items.json"
    return EvalSpec(
        name=name,
        title=title,
        group=GROUP,
        bank=bank,
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=lambda args: run_family(args, name=name, bank=REPO_ROOT / bank),
        calls_per_arm=f"≈ {n_items * n_layers / 1000:.1f}k",
        sources="",
    )


def targets_of(item: dict[str, Any]) -> list[str]:
    return exact_targets(item_targets(item))


def group_cells(cells: list[Cell]) -> dict[CellKey, list[Cell]]:
    groups: dict[CellKey, list[Cell]] = defaultdict(list)
    for c in cells:
        groups[(c.id, c.layer)].append(c)
    return dict(groups)


def run_family(args: JudgeArgs, *, name: str, bank: Path) -> FamilyResult:
    _header, items = load_bank(bank)
    scope = item_scope(items, args)
    ids = [it["id"] for it in scope]
    targets = {it["id"]: targets_of(it) for it in scope}
    cells, rep = load_readouts(args.readouts, ids=ids, layers=args.layers)
    layers = args.layers if args.layers is not None else rep.layers
    groups = group_cells(cells)
    expected = [(i, layer) for i in ids for layer in layers]
    missing = [k for k in expected if k not in groups]
    require_cells(name, missing, len(expected), args)

    nulls_on = args.extra.get("null") == "on"
    null_targets: dict[tuple[str, str], list[str]] = {}
    partners: dict[str, list[str]] = {}
    if nulls_on:
        # partners come from the FULL bank, so items= / limit= runs see the same ones
        partners = bank_partners(items, targets_of, family=name)
        by_id = {it["id"]: it for it in items}
        foils = load_foils(bank.parent / "null_foils.json")
        for i in ids:
            for j, p in enumerate(partners[i]):
                null_targets[(i, f"null:{j}")] = targets_of(by_id[p])
            for j, f in enumerate(foils.get(i, [])[:K_FOIL]):
                null_targets[(i, f"foil:{j}")] = [f]

    spend = Spend()
    null_outcome: NullOutcome | None = None
    with Cache(args.out / "cells.jsonl") as cache:
        outcome = judge_cells(
            groups,
            targets,
            kind=rep.kind or "prose",
            judge=args.judge,
            cache=cache,
            spend=spend,
            preflight=Preflighter(args.dry_run),
            concurrency=args.concurrency,
            rpm=args.rpm,
            dry_run=args.dry_run,
        )
        if nulls_on:
            null_outcome = judge_null_cells(
                groups,
                null_targets,
                kind=rep.kind or "prose",
                judge=args.judge,
                cache=cache,
                spend=spend,
                preflight=Preflighter(args.dry_run),
                concurrency=args.concurrency,
                rpm=args.rpm,
                dry_run=args.dry_run,
            )

    rows = [_item_row(i, layers, groups, targets[i], outcome) for i in ids]
    extras: dict[str, Any] = {"n_calls": outcome.n_calls}
    if null_outcome is not None:
        extras["nulls"] = null_extras(
            ids, layers, groups, rows, null_targets, partners, null_outcome
        )
    result = pass_rate_result(
        name=name,
        args=args,
        prompt_version=PROMPT_VERSION,
        rows=rows,
        cells=cells,
        rep=rep,
        # a cell is one (item, layer) judge call; empty = every sample at that layer is blank
        n_expected=len(expected),
        n_missing=len(missing),
        n_unjudged=outcome.n_unjudged,
        n_empty=outcome.n_empty,
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra={"layers_judged": layers},
        extras=extras,
    )
    return with_readout_count(result, scope, cells)


def null_extras(
    ids: list[str],
    layers: list[int],
    groups: dict[CellKey, list[Cell]],
    rows: list[dict[str, Any]],
    null_targets: dict[tuple[str, str], list[str]],
    partners: dict[str, list[str]],
    outcome: NullOutcome,
) -> dict[str, Any]:
    """Fold the null verdicts with the real item rule (any layer; a layer with no text is a
    negative; a failed call with no pass is undecided) into rates, lifts and surface-free
    shares. ``value`` is never touched; this lives in ``extras["nulls"]``."""
    per: dict[str, dict[str, list[bool | None]]] = {"null": {}, "foil": {}}
    credits: dict[str, list[bool]] = {"null": [], "foil": []}
    detail: dict[str, dict[str, Any]] = {}
    for (item_id, tag), tgts in sorted(null_targets.items()):
        kind = tag.split(":")[0]
        hit_layers: list[int] = []
        undecided = False
        for layer in layers:
            cells = groups.get((item_id, layer))
            if cells is None:
                undecided = True
                continue
            if not any(s.strip() for c in cells for s in cell_samples(c)):
                continue
            v = outcome.verdicts.get((item_id, layer, tag))
            if v is None:
                undecided = True
            elif v.expressed:
                hit_layers.append(layer)
                credits[kind].append(surface_free(tgts, v.quote))
        passed = True if hit_layers else (None if undecided else False)
        per[kind].setdefault(item_id, []).append(passed)
        detail.setdefault(item_id, {})[tag] = {
            "targets": tgts,
            "pass": passed,
            "layers": hit_layers,
        }
    decided = [r for r in rows if r["pass"] is not None]
    value = sum(1.0 for r in decided if r["pass"]) / len(decided) if decided else None
    out: dict[str, Any] = {"value": value}
    for kind in ("null", "foil"):
        sm = null_summary(per[kind])
        out[f"{kind}_rate"] = sm["rate"]
        out[f"{kind}_ci95"] = sm["ci95"]
        out[f"{kind}_n_items"] = sm["n"]
        out[f"lift_{kind}"] = (
            value - sm["rate"] if value is not None and sm["rate"] is not None else None
        )
        cs = credits[kind]
        out[f"{kind}_n_credits"] = len(cs)
        out[f"{kind}_surface_free_share"] = sum(cs) / len(cs) if cs else None
    out["n_null_calls"] = outcome.n_calls
    out["null_failed"] = outcome.n_failed
    out["null_partners"] = {i: partners.get(i, []) for i in ids}
    out["items"] = detail
    return out


def _item_row(
    item_id: str,
    layers: list[int],
    groups: dict[CellKey, list[Cell]],
    targets: list[str],
    outcome: JudgeOutcome,
) -> dict[str, Any]:
    """``pass`` is True on any expressed layer, False when every expected layer was judged
    negative, and None (undecided) when nothing is expressed and a layer is missing or
    unjudged."""
    per_layer: dict[str, dict[str, Any]] = {}
    expressed_layers: list[int] = []
    n_unjudged = n_missing = 0
    for layer in layers:
        cells = groups.get((item_id, layer))
        if cells is None:
            n_missing += 1
            continue
        verdict = outcome.verdicts.get((item_id, layer))
        if verdict is None:
            n_unjudged += 1
        elif verdict.expressed:
            expressed_layers.append(layer)
        per_layer[str(layer)] = verdict.to_json() if verdict is not None else {"expressed": None}
    undecided = n_unjudged > 0 or n_missing > 0 or not per_layer
    return {
        "id": item_id,
        "targets": targets,
        "pass": tri_state(bool(expressed_layers), undecided),
        "earliest_layer": min(expressed_layers) if expressed_layers else None,
        "n_unjudged": n_unjudged,
        "n_missing": n_missing,
        "layers": per_layer,
    }
