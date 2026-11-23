"""association_hard (plan 0108): one 8-way MC (+ cannot tell) per item over a digest of every
read cell, asked in three independent draws whose pass / fail verdicts are put to a majority
(summary mode, the default), or one MC per (item, layer) (native); ``gate.py`` verifies a gold
pick. Options are frozen in the bank and shown in bank order."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from wsbench import digest, mc, reads, registry
from wsbench.banks import load_bank
from wsbench.cache import Cache
from wsbench.evals.association.conjunctive_association.judge import draw_key, majority, n_draws
from wsbench.family import fail, pass_rate_result, rate, require_cells, tri_state
from wsbench.llm import Spend
from wsbench.mcjudge import (
    Call,
    Preflighter,
    choice_of,
    item_scope,
    layer_pick_columns,
    quote_of,
    run_calls,
    with_readout_count,
)
from wsbench.multitoken.family import merge_forms
from wsbench.readouts import Cell
from wsbench.registry import JudgeArgs
from wsbench.results import FamilyResult

from . import bank as bk
from . import gate, prompts
from .prompts import CALL_VERSION, CHANCE

FAMILY = "association_hard"
CHANCE_LABEL = (
    "1/8: a forced guess among the 8 substantive options (cannot tell excluded); 1/6 on the "
    "complex kinds for a reader who never picks a bare head"
)
PIN_PER_OPTION = 2  # raw samples pinned per option that no digest line names
PIN_SUFFIX = 2  # the pin predicate tolerates this many trailing word letters (a plural)


def load_items() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(header, items)`` of the registered bank (``registry.bank_path``); fails closed when
    the bank does not pass its own checks."""
    header, items = load_bank(registry.bank_path(FAMILY))
    findings = bk.validate(header, items)
    if findings:
        shown = "\n  ".join(findings[:10])
        more = f"\n  ... and {len(findings) - 10} more" if len(findings) > 10 else ""
        fail(f"{FAMILY}: the bank fails its own checks ({len(findings)}):\n  {shown}{more}")
    return header, items


def instrument(header: Mapping[str, Any]) -> str:
    """The result stamp of a bank: the call version, the gate version and ``+bank-v<N>`` for
    bank v<N> >= 2 (``PROMPT_VERSION`` for the registered bank)."""
    version = int(header.get("version", 1))
    stamp = f"{CALL_VERSION}+{gate.GATE_VERSION}"
    return stamp + (f"+bank-v{version}" if version >= 2 else "")


def majority_stamp(n: int) -> str:
    """``+maj<N>v`` for the majority of ``N`` draws' pass / fail verdicts; one draw is the
    single-call instrument (no suffix)."""
    return f"+maj{n}v" if n > 1 else ""


def shown_options(it: Mapping[str, Any]) -> tuple[list[str], int]:
    """(the options as shown: bank order, cannot tell LAST; the gold's 1-based position)."""
    return mc.options_with_cannot(it["mc"]["options"]), int(it["mc"]["gold_position"])


def concepts(items: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """The concepts of ``items``, one entry (its forms) each: every item's gold with its
    accepted forms and every distractor with its own; entries that share a form are one
    concept. The builder freezes this list into the header (``concepts``), and that frozen pool
    is what :func:`run` judges with, so a successor bank that only drops items and carries the
    list keeps every kept item's calls."""
    raw: list[list[str]] = []
    for it in items:
        raw.append(bk.gold_forms(it))
        raw += [bk.distractor_forms(it, d) for d in it["mc"]["distractors"]]
    return merge_forms(raw)


def option_forms(option: str, pool: Sequence[Sequence[str]]) -> list[str]:
    """An option's forms: the bank concept entry that holds it, plus the option as shown."""
    key = mc.fold(option).strip()
    entry = next((list(e) for e in pool if key in {mc.fold(f).strip() for f in e}), [])
    return list(dict.fromkeys([option, *entry]))


def other_forms(
    others: Sequence[str], gold: Sequence[str], pool: Sequence[Sequence[str]]
) -> list[str]:
    """Every form of every other shown option, minus any that folds equal to a gold form."""
    g = {mc.fold(f).strip() for f in gold}
    out = [f for o in others for f in option_forms(o, pool) if mc.fold(f).strip() not in g]
    return list(dict.fromkeys(out))


def names(text: str, forms: Sequence[str]) -> bool:
    """The pin predicate: a listed form occurs in ``text``, plural-tolerant."""
    return bool(mc.form_hits(text, forms, suffix=PIN_SUFFIX))


def pin_options(
    col: digest.Collapse,
    present: Mapping[str, list[Cell]],
    item_of: Mapping[str, Mapping[str, Any]],
    pool: Sequence[Sequence[str]],
    s: digest.Settings,
) -> int:
    """For every shown option (gold and distractors alike, never told which is gold) that NO
    line of the item's digest names, pin up to :data:`PIN_PER_OPTION` raw prose samples that
    name it; an option the digest already names gets no pin."""
    n = 0
    for i, cells in present.items():
        if i not in col.cells or i in col.unsummarized:
            continue
        have = [ln.text for ln in col.evidence.get(i, ())]
        preds = []
        for o in item_of[i]["mc"]["options"]:
            forms = option_forms(o, pool)
            if any(names(t, forms) for t in have):
                continue

            def pred(ln: digest.Line, forms: list[str] = forms) -> bool:
                return ln.pieces is None and names(ln.text, forms)

            preds.append(pred)
        if preds:
            n += digest.pin_lines(col, i, cells, preds, s, PIN_PER_OPTION)
    return n


# ---------------------------------------------------------------- calls


def _render_blocks(lines: Sequence[digest.Line]) -> str:
    by: dict[str, list[str]] = defaultdict(list)
    for ln in lines:
        by[ln.where].append(ln.text)
    return "\n\n".join(w + "\n" + "\n".join(f"- {t}" for t in ts) for w, ts in by.items())


class Unit:
    """One MC question: an item's digest in one draw (summary), or one (item, layer) (native)."""

    def __init__(
        self, key: str, it: Mapping[str, Any], system: str, user: str, lines: Sequence[digest.Line]
    ):
        self.key = key
        self.it = it
        self.system = system
        self.user = user
        self.lines = list(lines)
        self.shown, self.gold_pos = shown_options(it)

    def call(self, key: str | None = None, user: str | None = None) -> Call:
        return Call(
            key or self.key,
            self.system,
            user or self.user,
            {"id": self.it["id"], "gold_pos": self.gold_pos, "n_shown": len(self.shown)},
        )


def _run(
    calls: list[Call], *, schema: dict, args: JudgeArgs, pv: str, cache: Cache, spend: Spend,
    pre: Preflighter,
) -> dict[str, dict | None]:  # fmt: skip
    if not calls:
        return {}
    return run_calls(
        calls,
        schema=schema,
        judge=args.judge,
        prompt_version=pv,
        cache=cache,
        spend=spend,
        concurrency=args.concurrency,
        rpm=args.rpm,
        dry_run=args.dry_run,
        preflight=pre.for_judge(args.judge),
    )


def role_of(it: Mapping[str, Any], option: str | None) -> str:
    """What a picked option is for its item: ``gold`` | ``bare_head`` | ``sibling`` (another
    cell of the gold's grid) | ``other`` (any other distractor) | ``none`` (no option picked)."""
    m = it["mc"]
    if option is None:
        return "none"
    if option == m["gold"]:
        return "gold"
    grid = m.get("grid")
    if grid and option in grid["heads"]:
        return "bare_head"
    return "sibling" if grid and option in grid["cells"] else "other"


def judge_units(
    units: list[Unit],
    *,
    args: JudgeArgs,
    pv: str,
    sampling: str,
    pool: Sequence[Sequence[str]],
    cache: Cache,
    spend: Spend,
    pre: Preflighter,
) -> dict[str, dict[str, Any]]:
    """key -> the unit's verdict (``pick``, ``picked``, ``outcome``, ``credit``, tri-state
    ``pass``, quote fields). Three batches: the MC calls, the ONE re-ask of each quote miss
    (``<key>|retry1``), the quote-only re-judges (``<key>|quote``)."""
    first = _run(
        [u.call() for u in units], schema=prompts.SCHEMA, args=args, pv=pv, cache=cache,
        spend=spend, pre=pre,
    )  # fmt: skip
    if args.dry_run:
        return {}

    def picked(u: Unit, r: dict | None) -> str:
        return mc.classify(choice_of(r), u.gold_pos, len(u.shown)) if r is not None else "api_fail"

    retry = [
        u
        for u in units
        if picked(u, first.get(u.key)) in ("gold", "distractor")
        and not digest.quote_ok(quote_of(first.get(u.key)), u.lines)
    ]
    retried = _run(
        [u.call(f"{u.key}|retry1", prompts.render_retry(u.user)) for u in retry],
        schema=prompts.SCHEMA, args=args, pv=pv, cache=cache, spend=spend, pre=pre,
    )  # fmt: skip
    again = {u.key for u in retry}
    out: dict[str, dict[str, Any]] = {}
    rejudge: list[Unit] = []
    for u in units:
        was_retried = u.key in again
        r = retried.get(f"{u.key}|retry1") if was_retried else first.get(u.key)
        pick = picked(u, r)
        quote = quote_of(r)
        choice = choice_of(r)
        option = u.shown[choice - 1] if pick in ("gold", "distractor") else None
        v: dict[str, Any] = {
            "choice": choice,
            "pick": pick,
            "picked": option,
            "role": role_of(u.it, option),
            "quote": quote,
            "quote_ok": bool(quote) and digest.quote_ok(quote, u.lines),
            "retried": was_retried,
            "failed_stage": "retry" if (r is None and was_retried) else ("mc" if r is None else ""),
        }
        if pick != "gold":
            v["outcome"] = pick
        else:
            others = [o for i, o in enumerate(u.shown[:-1], start=1) if i != u.gold_pos]
            forms = bk.gold_forms(u.it)
            grid = u.it["mc"].get("grid")
            v["outcome"] = gate.gate_gold(
                quote,
                u.lines,
                forms=forms,
                shown_others=others,
                other_forms=other_forms(others, forms, pool),
                sampling=sampling,
                rivals=pool,
                own_head=option_forms(grid["heads"][0], pool) if grid else (),
            )
            if v["outcome"] == "needs_rejudge":
                rejudge.append(u)
        out[u.key] = v
    tokens = sampling == "tokens10"
    rj = _run(
        [
            u.call(
                f"{u.key}|quote", prompts.render_quote(out[u.key]["quote"], u.shown, tokens=tokens)
            )
            for u in rejudge
        ],
        schema=prompts.QUOTE_SCHEMA, args=args, pv=pv, cache=cache, spend=spend, pre=pre,
    )  # fmt: skip
    for u in rejudge:
        v = out[u.key]
        r = rj.get(f"{u.key}|quote")
        if r is None:
            v.update(outcome="api_fail", pick="api_fail", failed_stage="quote_check")
            continue
        v["rejudge_pick"] = mc.classify(choice_of(r), u.gold_pos, len(u.shown))
        v["outcome"] = "gold_description" if v["rejudge_pick"] == "gold" else "gold_desc_rejected"
    for v in out.values():
        v["credit"] = gate.CREDIT.get(v["outcome"], "none")
        v["pass"] = None if v["outcome"] == "api_fail" else v["outcome"] in gate.PASSING
    return out


def draw_verdict(v: Mapping[str, Any] | None) -> str:
    """``pass`` | ``fail`` | ``api_fail`` of one draw."""
    if v is None or v["pass"] is None:
        return "api_fail"
    return "pass" if v["pass"] else "fail"


def gate_extras(verdicts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    outcomes = [v["outcome"] for v in verdicts]
    return {
        "n_gold_raw": sum(1 for v in verdicts if v.get("role") == "gold"),
        "n_listed_form": outcomes.count("gold_listed_form"),
        "n_listed_line": outcomes.count("gold_listed_line"),
        "n_listed_evidence": outcomes.count("gold_listed_evidence"),
        "n_description_credit": outcomes.count("gold_description"),
        "description_credit_quotes": [
            v["quote"] for v in verdicts if v["outcome"] == "gold_description"
        ],
        "n_gold_unverified": outcomes.count("gold_unverified"),
        "n_gold_desc_rejected": outcomes.count("gold_desc_rejected"),
        "n_flat_list_voided": outcomes.count("gold_flat_list"),
        "n_retried": sum(1 for v in verdicts if v.get("retried")),
        "n_distractor": outcomes.count("distractor"),
        "n_cannot_tell": outcomes.count("cannot_tell"),
    }


def _split(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for value in sorted({r[key] for r in rows}):
        decided = [r for r in rows if r[key] == value and r["pass"] is not None]
        out[value] = {
            "n": len(decided),
            "passed": sum(1 for r in decided if r["pass"]),
            "rate": rate(r["pass"] for r in decided),
        }
    return out


def score_extras(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The family's breakdowns over the item rows (summary mode)."""
    decided = [r for r in rows if r["pass"] is not None]
    first = rate(bool(r.get("pass_first_ask")) for r in decided)
    by_kind = _split(rows, "kind")
    cx = [r for r in decided if r["kind"] != "obscure"]
    head = [r["id"] for r in cx if r.get("pick_role") == "bare_head"]
    sib = [r["id"] for r in cx if r.get("pick_role") == "sibling"]
    value = rate(r["pass"] for r in decided)

    def f(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    lines = [
        "| association_hard | n | passed | rate |",
        "|---|---|---|---|",
        *[f"| {k} | {d['n']} | {d['passed']} | {f(d['rate'])} |" for k, d in by_kind.items()],
        "",
        f"pass rate {f(value)}; counting a pass obtained after the quote re-ask as a fail "
        f"(first ask): {f(first)}",
        f"complex items whose majority pick is the bare head: {len(head)} of {len(cx)}; "
        f"another cell of the grid: {len(sib)} of {len(cx)}",
    ]
    return {
        "by_kind": by_kind,
        "by_lang": _split(rows, "lang"),
        "unanimous_items": sum(1 for r in rows if r.get("unanimous")),
        "picked_bare_head": head,
        "picked_sibling": sib,
        "pass_rate_first_ask": first,
        "breakdown_md": "\n".join(lines),
    }


# ---------------------------------------------------------------- run


def run(args: JudgeArgs) -> FamilyResult:
    header, items = load_items()
    scope = item_scope(items, args)
    ids = [it["id"] for it in scope]
    cells, rep = reads.load(args, FAMILY, ids=ids)
    sampling = rep.sampling or ("tokens10" if rep.kind == "tokens" else "prose1")
    layers = args.layers if args.layers is not None else rep.layers
    groups: dict[tuple[str, int], list[Cell]] = defaultdict(list)
    for c in cells:
        groups[(c.id, c.layer)].append(c)
    prompt_only = reads.is_prompt_only(rep.reader)
    expected = [(i, layer) for i in ids for layer in layers]
    missing = [] if prompt_only else [k for k in expected if k not in groups]
    require_cells(FAMILY, missing, len(expected), args)
    pool = header["concepts"]  # frozen in the bank (V13), never the judged subset
    stamp = instrument(header)
    if digest.summary_mode(args):
        return _run_summary(
            args, scope, ids, cells, rep, sampling, len(expected), missing, pool, stamp
        )
    return _run_native(args, scope, ids, cells, rep, sampling, layers, groups, missing, pool, stamp)


def _base_row(it: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": it["id"],
        "gold": it["mc"]["gold"],
        "gold_pos": int(it["mc"]["gold_position"]),
        "kind": it["kind"],
        "lang": it["lang"],
    }


def _run_summary(
    args: JudgeArgs,
    scope: list[dict[str, Any]],
    ids: list[str],
    cells: list[Cell],
    rep: Any,
    sampling: str,
    n_expected: int,
    missing: list[tuple[str, int]],
    pool: Sequence[Sequence[str]],
    stamp: str,
) -> FamilyResult:
    """Every loaded cell of an item -> one digest -> the MC in ``n`` draws -> the gate per draw
    -> the majority of the draws' pass / fail verdicts."""
    spec = registry.FAMILIES.get(FAMILY)
    task_note = spec.task_note if spec is not None else prompts.DIGEST_TASK_NOTE
    n = n_draws(args)
    by_item: dict[str, list[Cell]] = defaultdict(list)
    for c in cells:
        by_item[c.id].append(c)
    partial = {i for i, _layer in missing}
    pv = digest.prompt_version(CALL_VERSION, args, FAMILY)  # the calls; the stamp adds the gate
    spend = Spend()
    pre = Preflighter(args.dry_run)
    item_of = {it["id"]: it for it in scope}
    with Cache(args.out / "cells.jsonl") as cache:
        present = {i: by_item[i] for i in ids if by_item.get(i)}
        col = digest.collapse(
            FAMILY,
            present,
            args=args,
            cache=cache,
            spend=spend,
            preflight=pre.for_judge(digest.summarizer_judge(args, FAMILY)),
            task_note=task_note,
            expect_all=[c for c in cells if c.id in present],
        )
        if not args.dry_run:
            pin_options(col, present, item_of, pool, digest.settings(args, FAMILY))
        source_kind = digest.as_prose(rep)
        note = digest.summary_note(args, source_kind, FAMILY)
        judged = [i for i in present if i not in col.unsummarized and i not in col.empty]
        units = []
        for i in judged:
            shown, _g = shown_options(item_of[i])
            text = (col.cells[i].samples or ("",))[0]
            user = prompts.render_summary(note, text, shown)
            base = f"{i}|L{digest.SUMMARY_LAYER}"
            lines = col.evidence.get(i, ())
            units += [
                Unit(draw_key(base, k), item_of[i], prompts.SYSTEM_SUMMARY, user, lines)
                for k in range(n)
            ]
        verdicts = judge_units(
            units, args=args, pv=pv, sampling=sampling, pool=pool, cache=cache, spend=spend, pre=pre
        )
    rows: list[dict[str, Any]] = []
    for i in ids:
        row = _base_row(item_of[i])
        if i not in present:
            row.update(outcome="missing", credit="none", **{"pass": None})
        elif i in col.empty:
            row.update(outcome="empty", credit="none", **{"pass": False})
        elif i in col.unsummarized:
            row.update(outcome="unsummarized", credit="none", **{"pass": None})
        elif not verdicts:  # dry run
            row.update(outcome="unjudged", credit="none", **{"pass": None})
        else:
            base = f"{i}|L{digest.SUMMARY_LAYER}"
            vs = [verdicts[draw_key(base, k)] for k in range(n)]
            row.update(item_verdict(vs))
            if i in partial and row["pass"] is False:
                row["pass"] = None  # a missing layer leaves a non-pass undecided
        row.setdefault("pass_first_ask", False)
        if i in col.cells:
            row.update(col.row(i))
        rows.append(row)
    all_draws = list(verdicts.values())
    n_api = sum(1 for r in rows if r.get("verdict") == "api_fail")
    extras = {
        **gate_extras(all_draws),
        **score_extras(rows),
        "n_draws": n,
        "n_calls": len(units),
        "summary": col.extras(),
        "n_readouts_in": col.diag.get("n_readouts_in", 0),
        "n_readouts_bundled": col.diag.get("n_readouts_bundled", 0),
    }
    result = pass_rate_result(
        name=FAMILY,
        args=args,
        prompt_version=digest.prompt_version(stamp + majority_stamp(n), args, FAMILY),
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=n_expected,
        n_missing=len(missing),
        n_unjudged=len(col.unsummarized) + n_api,
        n_empty=len(col.empty),
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra={
            **digest.config(args, source_kind, FAMILY),
            "layers_judged": args.layers,
            "draws": n,
        },
        extras=extras,
        n_items=len(ids),
        pinned=digest.pinned(args, FAMILY),
    )
    result.chance = CHANCE
    return with_readout_count(result, scope, cells)


def item_verdict(vs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """An item's row fields from its draws: the majority of the draws' pass / fail verdicts (a
    failed draw never votes but counts in the half), ``outcome`` / ``credit`` of the first
    passing draw (else of draw 0), and the first-ask verdict (a draw that passed only after the
    quote re-ask counts as a fail)."""
    labels = [draw_verdict(v) for v in vs]
    verdict = majority(labels)
    lead = next((v for v in vs if v["pass"]), vs[0])
    asked_once = [
        "fail" if (v["pass"] and v["retried"]) else x for v, x in zip(vs, labels, strict=True)
    ]
    first = majority(asked_once)
    return {
        "pass": None if verdict == "api_fail" else verdict == "pass",
        "verdict": verdict,
        "outcome": lead["outcome"],
        "credit": lead["credit"],
        "quote": lead["quote"],
        "pick_role": Counter(v["role"] for v in vs).most_common(1)[0][0],
        "unanimous": len(set(labels)) == 1,
        "pass_first_ask": first == "pass",
        "draw_verdicts": labels,
        "draws": [
            {
                k: v.get(k)
                for k in (
                    "choice",
                    "pick",
                    "picked",
                    "role",
                    "quote",
                    "quote_ok",
                    "retried",
                    "outcome",
                    "credit",
                    "rejudge_pick",
                    "failed_stage",
                )
            }
            for v in vs
        ],
    }


def _run_native(
    args: JudgeArgs,
    scope: list[dict[str, Any]],
    ids: list[str],
    cells: list[Cell],
    rep: Any,
    sampling: str,
    layers: list[int],
    groups: dict[tuple[str, int], list[Cell]],
    missing: list[tuple[str, int]],
    pool: Sequence[Sequence[str]],
    stamp: str,
) -> FamilyResult:
    """One MC call per (item, layer) over every position at that layer, one draw; the item
    passes if any layer passes the gate."""
    note = digest.token_note_of(FAMILY) if rep.kind == "tokens" else prompts.NATIVE_NOTE_PROSE
    item_of = {it["id"]: it for it in scope}
    spend = Spend()
    pre = Preflighter(args.dry_run)
    units: list[Unit] = []
    n_empty = 0
    for i in ids:
        for layer in layers:
            cs = groups.get((i, layer))
            if not cs:
                continue
            lines = digest.native_lines(cs)
            if not lines:
                n_empty += 1
                continue
            shown, _g = shown_options(item_of[i])
            user = prompts.render_native(note, _render_blocks(lines), shown)
            units.append(Unit(f"{i}|L{layer}", item_of[i], prompts.SYSTEM_NATIVE, user, lines))
    with Cache(args.out / "cells.jsonl") as cache:
        verdicts = judge_units(
            units,
            args=args,
            pv=CALL_VERSION,
            sampling=sampling,
            pool=pool,
            cache=cache,
            spend=spend,
            pre=pre,
        )
    rows: list[dict[str, Any]] = []
    for i in ids:
        per: dict[str, dict[str, Any]] = {}
        passed = undecided = False
        n_missing = 0
        for layer in layers:
            v = verdicts.get(f"{i}|L{layer}")
            if (i, layer) not in groups:
                n_missing += 1
                continue
            if v is None:  # an all-blank cell (counted in n_empty) or a dry run
                undecided = undecided or args.dry_run
                continue
            per[str(layer)] = v
            passed = passed or v["pass"] is True
            undecided = undecided or v["pass"] is None
        passing = [int(L) for L, v in per.items() if v["pass"]]
        rows.append(
            {
                **_base_row(item_of[i]),
                "pass": tri_state(passed, undecided or n_missing > 0 or not per),
                "earliest_layer": min(passing) if passing else None,
                "n_missing": n_missing,
                "credit": next((per[str(L)]["credit"] for L in sorted(passing)), "none"),
                "layers": per,
            }
        )
    judged = list(verdicts.values())
    n_api = sum(1 for v in judged if v["outcome"] == "api_fail")
    extras = {
        **gate_extras(judged),
        **layer_pick_columns(rows),
        "by_kind": _split(rows, "kind"),
        "by_lang": _split(rows, "lang"),
        "n_calls": len(units),
    }
    result = pass_rate_result(
        name=FAMILY,
        args=args,
        prompt_version=stamp,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(ids) * len(layers),
        n_missing=len(missing),
        n_unjudged=n_api,
        n_empty=n_empty,
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra={"layers_judged": layers},
        extras=extras,
    )
    result.chance = CHANCE
    return with_readout_count(result, scope, cells)
