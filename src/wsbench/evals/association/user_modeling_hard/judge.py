"""user_modeling_hard (umh-v2): one blind identification MC per PART of an item (1-3 implied
traits of the user), read at every token of the chat render; a gold pick counts only with a
verified quote that a blind second reading of its statement also assigns to the gold."""

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from wsbench import digest, mc, reads, registry
from wsbench.cache import Cache
from wsbench.evals.association.conjunctive_association.judge import draw_key, majority, n_draws
from wsbench.evals.association.user_modeling.judge import decode_choice
from wsbench.family import fail, render_bag
from wsbench.llm import Spend
from wsbench.mcjudge import Call, Preflighter, load_bank, run_calls, with_readout_count
from wsbench.readouts import Cell, LoadReport
from wsbench.registry import JudgeArgs
from wsbench.results import FamilyResult

from . import bank as bk
from . import gate, prompts, score
from .prompts import (
    CALL_VERSION,
    UMH_ATTRIBUTE_SCHEMA,
    UMH_QUOTE_SCHEMA,
    UMH_QUOTE_SYSTEM,
    UMH_SYSTEM,
)

FAMILY = "user_modeling_hard"
POOLS_FILE = "option_pools.json"
INFERRED = "inferred_characterization"
REPLY_PLAN = "reply_plan"
ECHO_BASIS = "verbatim_echo"
__all__ = ["draw_label", "draw_verdict", "instrument", "judge_units", "load", "run"]


def _spec() -> registry.EvalSpec:
    """The family's spec as registered (a test may patch it), else the package's own."""
    import importlib

    return registry.FAMILIES.get(FAMILY) or importlib.import_module(__package__).SPEC


def _token_note() -> str:
    """THE token-list rule rendered from the family's spec (``mc.token_note``)."""
    spec = _spec()
    return mc.token_note(spec.flat_types, multi_select=spec.multi_select)


def load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(header, items)`` of the bank the family judges, validated (fail closed, exit 2): the
    shape checks of ``bank.validate``, with the pool checks when the bank is the registered
    one (the pools file sits beside it)."""
    import json

    raw = load_bank(FAMILY)
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        fail(f"{FAMILY}: the bank must be an object with an `items` list")
    header = {k: v for k, v in raw.items() if k != "items"}
    items = raw["items"]
    pools_path = registry.resource_path(FAMILY, POOLS_FILE)
    registered = registry.bank_path(FAMILY).parent == pools_path.parent
    pools = None
    if registered and pools_path.is_file():
        pools = json.loads(pools_path.read_text(encoding="utf-8"))
    findings = bk.validate(
        header, items, pools=pools, sources={POOLS_FILE: pools_path} if pools is not None else None
    )
    if findings:
        shown = "\n  ".join(findings[:10])
        more = f"\n  ... and {len(findings) - 10} more" if len(findings) > 10 else ""
        fail(f"{FAMILY}: the bank fails its own checks ({len(findings)}):\n  {shown}{more}")
    return header, items


def instrument(raw: Mapping[str, Any]) -> str:
    """The result stamp of a bank: ``CALL_VERSION`` plus ``+bank-v<N>`` for bank v<N> >= 2."""
    version = int(raw.get("version", 1))
    return CALL_VERSION + (f"+bank-v{version}" if version >= 2 else "")


def majority_stamp(n: int) -> str:
    """``+maj<N>v`` for the majority of ``N`` draws' pass / fail verdicts per part; one draw is
    the single-call instrument (no suffix)."""
    return f"+maj{n}v" if n > 1 else ""


def item_scope(items: list[dict], args: JudgeArgs) -> list[dict]:
    """bank ∩ ``items=`` (bank order) on the bank key ``name``, then ``limit=``."""
    if args.items is not None:
        want = set(args.items)
        items = [it for it in items if it["name"] in want]
    if args.limit > 0:
        items = items[: args.limit]
    return items


def _str(r: Mapping[str, Any], key: str) -> str:
    v = r.get(key)
    return v if isinstance(v, str) else ""


@dataclasses.dataclass
class Unit:
    """One MC question: a part of an item against one readout text (the item's digest, draw
    ``d``; or natively one sample / token list)."""

    key: str
    item: dict
    k: int  # the part's index
    user: str  # the rendered prompt
    lines: list[digest.Line]
    cells: Sequence[Cell]
    meta: dict


def _answer(r: Mapping[str, Any], u: Unit, chat: str) -> dict[str, Any]:
    """One MC answer, decoded and taken through steps 1-3 of the verification. The echo step is
    given the picked value (for the gold also the bank's accepted wordings): a quote that says
    it in a word the chat does not have is not the user's own words."""
    part = u.item["parts"][u.k]
    choice = r.get("choice")
    pick, value, invalid = decode_choice(choice, part["options"], part["gold_position"])
    evidence = _str(r, "evidence")
    content = pick in ("gold", "distractor")
    forms = [value, *(map(str, part.get("forms") or ()) if pick == "gold" else ())]
    loc = gate.locate(evidence, u.lines, u.cells, chat, forms) if content else gate.Located("")
    return {
        "choice": choice,
        "pick": "unverified" if loc.gate else pick,
        "pick_raw": pick,
        "pick_value": value,
        "choice_invalid": invalid,
        "basis": r.get("basis") if isinstance(r.get("basis"), str) else None,
        "evidence": evidence,
        "statement": loc.statement,
        "near_quote": loc.near,
        "token_statement": loc.tokens,
        "shown_quote": loc.shown,
        "readings": [
            {
                "statement": x.statement,
                "shown": x.shown,
                "near": x.near,
                "tokens": x.tokens,
                "context": x.context,
            }
            for x in loc.readings()
        ],
        "gate": loc.gate,
        # gate `echo`: the copied statements that could not state the GOLD either (mostly chat
        # under the gold's forms too); the draw never reads them again
        "echoed": [
            s
            for s in loc.echoed
            if gate.mostly_chat(s, chat, [str(part["gold"]), *map(str, part.get("forms") or ())])
        ],
        "credit": "",
        "quote_check_choice": None,
        "quote_check_pick": None,
        "quote_check_choices": [],
        "broader_suspect": False,
        "formless": False,
        "rationale": _str(r, "rationale"),
    }


def quote_key(key: str, j: int) -> str:
    """The call key of the quote check on the ``j``-th holding statement of an answer (``key`` =
    the answer's own call key: the draw's, or ``<draw key>|retry<n>``): ``<key>|quote`` for the
    first (the single-statement key), ``<key>|quote<j+1>`` after it."""
    return f"{key}|quote" if j == 0 else f"{key}|quote{j + 1}"


def ask_key(key: str, n: int) -> str:
    """The call key of a draw's ``n``-th ask: the draw's own key, then ``<key>|retry<n>``."""
    return key if n == 0 else f"{key}|retry{n}"


def needs_quote_check(row: Mapping[str, Any]) -> bool:
    """Only a GOLD pick that stands after steps 1-3 with an inferred basis is read a second
    time: every other draw already fails, so nothing about the call tells which is which."""
    return row["pick"] == "gold" and not row["gate"] and row["basis"] == INFERRED


def draw_verdict(row: Mapping[str, Any] | None) -> str:
    """One draw's vote: ``pass`` iff the pick is the gold, no gate fired, the basis is inferred
    and the blind quote check returned the gold too; ``api_fail`` for a draw whose MC call or
    quote check did not land; else ``fail``."""
    if row is None:
        return "api_fail"
    ok = row["pick"] == "gold" and not row["gate"] and row["basis"] == INFERRED
    return "pass" if ok and row["credit"] == "description" else "fail"


def first_ask_verdict(row: Mapping[str, Any] | None) -> str:
    """:func:`draw_verdict` with every re-asked draw counted as its FIRST answer, which a gate
    rejected: a pass obtained after a re-ask is a ``fail`` here (review r3, S2)."""
    v = draw_verdict(row)
    return "fail" if v == "pass" and row and row.get("reasks") else v


def draw_label(row: Mapping[str, Any] | None, part: Mapping[str, Any]) -> str:
    """One draw's full answer (a diagnostic): ``gold:description`` (the pass), ``gold:echo_basis``,
    ``gold:reply_plan``, ``gold:no_basis`` (a gold pick with basis ``absent`` or none),
    ``unverified:<gate>``, ``distractor``, ``distractor:neighbour``, ``cannot_tell``, ``invalid``,
    ``api_fail``."""
    if row is None:
        return "api_fail"
    if row["gate"]:
        return f"unverified:{row['gate']}"
    if row["pick"] == "gold":
        if row["credit"] == "description":
            return "gold:description"
        by_basis = {ECHO_BASIS: "gold:echo_basis", REPLY_PLAN: "gold:reply_plan"}
        return by_basis.get(row["basis"], "gold:no_basis")
    if row["pick"] == "distractor":
        near = row["pick_value"] in (part.get("near_neighbours") or ())
        return "distractor:neighbour" if near else "distractor"
    return "invalid" if row["choice_invalid"] else "cannot_tell"


def judge_units(
    args: JudgeArgs,
    units: list[Unit],
    *,
    cache: Cache,
    spend: Spend,
    pre: Preflighter,
    prompt_version: str,
    broader: Mapping[str, Any],
) -> tuple[dict[str, dict | None], dict[str, int]]:
    """Every unit's final answer (``None`` = the MC call or a quote check did not land), the
    same in both modes. A draw is a chain of at most ``1 + gate.MAX_REASKS`` asks of the main
    judge (keys ``<key>``, ``<key>|retry1``, ``<key>|retry2``), at most
    ``gate.MAX_REASKS_DESC`` of the re-asks following a quote-check refusal
    (``gate.reask_allowed``). Each answer is verified (``gate.locate``), and a standing gold
    pick with an inferred basis is then read by the blind quote check, one call per distinct
    statement that holds the quote (``gate.MAX_STATEMENTS``
    at most; keys ``<ask key>|quote``, ``|quote2`` ...): the pick stands when ANY of them
    returns the gold, is undecided when none does and one did not land or gave no valid choice,
    and is ``desc_rejected`` when every one is a valid other answer. An answer whose quote was
    not accepted (gate ``quote`` / ``bullet`` / ``echo`` / ``desc_rejected``) is re-asked while
    the draw has a re-ask left: every rejected answer and its reason are appended to the draw's
    own user turn, the new answer replaces the old one and is verified from the start. A failed
    re-ask leaves the gated answer before it (a fail). A statement the quote check has refused
    is never read again in that draw (a later answer that rests only on refused statements is
    ``desc_rejected`` with no call), and neither is a statement the echo gate found to be the
    user's own words (``row["echoed"]``), so a re-ask can only pass on a different statement
    (statements are compared on ``digest.fold_quote`` forms). No
    path passes without a quote check that returned the gold. Also the call tally."""

    def ask(calls: list[Call], schema: dict) -> dict[str, dict | None]:
        if not calls:
            return {}
        return run_calls(
            calls,
            schema=schema,
            judge=args.judge,
            prompt_version=prompt_version,
            cache=cache,
            spend=spend,
            concurrency=args.concurrency,
            rpm=args.rpm,
            dry_run=args.dry_run,
            preflight=pre.for_judge(args.judge),
        )

    chats = {u.key: prompts.render_user_turn(u.item["messages"]) for u in units}
    rows: dict[str, dict | None] = {}
    rejected: dict[str, list[dict]] = {u.key: [] for u in units}  # the answers re-asked, in order
    refused: dict[str, set[str]] = {u.key: set() for u in units}  # statements the check refused
    tally = {"n_mc_calls": len(units), "n_retried": 0, "n_quote_checks": 0, "n_reasks_desc": 0}
    pending = list(units)
    for n in range(gate.MAX_REASKS + 1):
        calls = []
        for u in pending:
            blocks = "".join(
                prompts.retry_text(
                    x["choice"], x["pick_value"], x["evidence"], x["gate"], again=j > 0
                )
                for j, x in enumerate(rejected[u.key])
            )
            calls.append(Call(ask_key(u.key, n), UMH_SYSTEM, u.user + blocks, u.meta))
        if n:
            tally["n_retried"] += len(calls)
        answers = ask(calls, UMH_ATTRIBUTE_SCHEMA)
        checks: list[Call] = []
        asked: list[tuple[Unit, list[str], list[dict]]] = []
        landed: list[Unit] = []
        for u in pending:
            r = answers.get(ask_key(u.key, n))
            if r is None:  # the first ask did not land: undecided; a failed re-ask changes nothing
                if n == 0:
                    rows[u.key] = None
                continue
            row = _answer(r, u, chats[u.key])
            if n:
                was = [
                    {k: x[k] for k in ("pick_raw", "gate", "evidence", "choice")}
                    for x in rejected[u.key]
                ]
                row = {**row, "retry_of": was[0], "reasks": was}
            rows[u.key] = row
            landed.append(u)
            if not needs_quote_check(row):
                continue
            part = u.item["parts"][u.k]
            fresh = [
                x
                for x in row["readings"]
                if digest.fold_quote(x["statement"]) not in refused[u.key]
            ]
            if not fresh:  # it rests only on statements already refused in this draw
                row["gate"], row["pick"] = "desc_rejected", "unverified"
                continue
            keys = []
            for j, reading in enumerate(fresh):
                user = prompts.render_quote_check(
                    reading["statement"],
                    reading["shown"],
                    part["options"],
                    part["judge_label"],
                    part["type"],
                    mixed=bool(u.item.get("mixed_state")),
                    tokens=reading["tokens"],
                    context=reading["context"],
                )
                keys.append(quote_key(ask_key(u.key, n), j))
                checks.append(Call(keys[-1], UMH_QUOTE_SYSTEM, user, u.meta))
            asked.append((u, keys, fresh))
        tally["n_quote_checks"] += len(checks)
        checked = ask(checks, UMH_QUOTE_SCHEMA)
        for u, keys, fresh in asked:
            row = rows[u.key]
            assert row is not None
            part = u.item["parts"][u.k]
            picks: list[str] = []  # per reading: gold / distractor / cannot_tell / undecided
            for key in keys:
                r = checked.get(key)
                choice = r.get("choice") if r is not None else None
                pick, _value, invalid = decode_choice(
                    choice, part["options"], part["gold_position"]
                )
                # a second reading that did not land or gave no valid choice decides nothing
                picks.append("undecided" if r is None or invalid else pick)
                row["quote_check_choices"].append(choice)
            at = picks.index("gold") if "gold" in picks else 0
            reading = fresh[at]
            row["statement"], row["shown_quote"] = reading["statement"], reading["shown"]
            row["near_quote"], row["token_statement"] = reading["near"], reading["tokens"]
            row["quote_check_choice"], row["quote_check_pick"] = (
                row["quote_check_choices"][at],
                picks[at],
            )
            if "gold" in picks:
                row["credit"] = "description"
                row["broader_suspect"] = gate.broader_suspect(row["statement"], part, broader)
                row["formless"] = gate.formless(row["statement"], part)
            elif "undecided" in picks:  # the draw is undecided, never a pass and never a fail
                rows[u.key] = None
            else:
                row["gate"], row["pick"] = "desc_rejected", "unverified"
                refused[u.key].update(
                    digest.fold_quote(x["statement"])
                    for x, p in zip(fresh, picks, strict=True)
                    if p != "undecided"
                )
        pending = []
        for u in landed:
            row = rows[u.key]
            if row is None:
                continue
            if row["gate"] == "echo":
                refused[u.key].update(digest.fold_quote(s) for s in row["echoed"])
            if gate.reask_allowed(row["gate"], [x["gate"] for x in rejected[u.key]]):
                rejected[u.key].append(row)
                tally["n_reasks_desc"] += row["gate"] == "desc_rejected"
                pending.append(u)
    return rows, tally


PART_SHOWN = (
    "choice",
    "pick",
    "pick_raw",
    "pick_value",
    "basis",
    "evidence",
    "statement",
    "near_quote",
    "gate",
    "credit",
    "quote_check_choice",
    "quote_check_choices",
    "rationale",
    "retry_of",
    "reasks",
    "broader_suspect",
    "formless",
)


def _part_head(k: int, part: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "part": k,
        "type": part["type"],
        "rule": prompts.rule_group(part["type"]),
        "attr_label": part["attr_label"],
        "options": list(part["options"]),
        "gold_position": part["gold_position"],
    }


def _shown(row: Mapping[str, Any] | None) -> dict[str, Any]:
    return {f: (row or {}).get(f) for f in PART_SHOWN}


def unjudged_part(k: int, part: Mapping[str, Any], passed: bool | None) -> dict[str, Any]:
    """A part of an item that made no call (no readouts, an empty or unserved digest)."""
    return {
        **_part_head(k, part),
        "pass": passed,
        "pass_first_ask": passed,
        "draw_verdicts": [],
        "draw_labels": [],
    }


def summary_part(k: int, part: Mapping[str, Any], draws: list[dict | None]) -> dict[str, Any]:
    """A part's verdict in summary mode: the majority of its draws' pass / fail verdicts (more
    than half of ALL draws; a failed draw never votes but counts in the half), ``None`` =
    undecided. The shown draw is one on the winning side with the most common label."""
    verdicts = [draw_verdict(r) for r in draws]
    labels = [draw_label(r, part) for r in draws]
    top = majority(verdicts)
    first = majority([first_ask_verdict(r) for r in draws])
    shown = None
    if top in ("pass", "fail"):
        side = [d for d, v in enumerate(verdicts) if v == top]
        common = Counter(labels[d] for d in side).most_common(1)[0][0]
        shown = draws[next(d for d in side if labels[d] == common)]
    return {
        **_part_head(k, part),
        "pass": {"pass": True, "fail": False}.get(top),
        "pass_first_ask": {"pass": True, "fail": False}.get(first),
        "majority": top,
        "draw_verdicts": verdicts,
        "draw_labels": labels,
        "label_split": len(set(labels)) == len(labels) > 1,
        **_shown(shown),
    }


def native_part(
    k: int, part: Mapping[str, Any], units: list[tuple[Unit, dict | None]]
) -> dict[str, Any]:
    """A part's verdict natively: it passes when ANY of its units passes, fails when every unit
    is decided and none passes, and is undecided otherwise. The shown unit is the first passing
    one, else the first with the most common label."""
    verdicts = [draw_verdict(r) for _u, r in units]
    labels = [draw_label(r, part) for _u, r in units]
    passed: bool | None = (
        True if "pass" in verdicts else (None if "api_fail" in verdicts else False)
    )
    firsts = [first_ask_verdict(r) for _u, r in units]
    first: bool | None = True if "pass" in firsts else (None if "api_fail" in firsts else False)
    at = None
    if "pass" in verdicts:
        at = verdicts.index("pass")
    elif any(v != "api_fail" for v in verdicts):
        landed = [d for d, v in enumerate(verdicts) if v != "api_fail"]
        common = Counter(labels[d] for d in landed).most_common(1)[0][0]
        at = next(d for d in landed if labels[d] == common)
    where = units[at][0].meta if at is not None else {}
    return {
        **_part_head(k, part),
        "pass": passed if units else False,
        "pass_first_ask": first if units else False,
        "n_units": len(units),
        "n_units_passed": verdicts.count("pass"),
        "draw_verdicts": verdicts,
        "draw_labels": labels,
        "layer": where.get("layer"),
        "pos": where.get("pos"),
        "sample_idx": where.get("sample_idx"),
        **_shown(units[at][1] if at is not None else None),
    }


def item_row(it: Mapping[str, Any], key: str, state: str, parts: list[dict]) -> dict[str, Any]:
    """The item's row: ``pass`` is False if any part failed (an undecided sibling cannot rescue
    it), True if every part passed, else None (no part failed, at least one undecided)."""
    verdicts = [p["pass"] for p in parts]
    passed: bool | None = False if False in verdicts else (None if None in verdicts else True)
    firsts = [p["pass_first_ask"] for p in parts]
    first: bool | None = False if False in firsts else (None if None in firsts else True)
    return {
        "id": it["name"],
        "key": key,
        "kind": it["kind"],
        "request_variant": it.get("request_variant"),
        "mixed_state": bool(it.get("mixed_state")),
        "state": state,
        "pass": passed,
        "pass_first_ask": first,  # the same rule with no pass that needed a re-ask (review r3)
        "n_parts": len(parts),
        "n_parts_passed": verdicts.count(True),
        "n_parts_undecided": verdicts.count(None),
        "parts": parts,
    }


def _parts_all(it: Mapping[str, Any], passed: bool | None) -> list[dict]:
    return [unjudged_part(k, p, passed) for k, p in enumerate(it["parts"])]


def digest_loss(
    scope: list[dict], by_item: Mapping[str, list[Cell]], col: digest.Collapse
) -> dict[str, Any]:
    """Mechanical, never gating (plan 0106 §3.7): the parts whose gold or a form occurs in a raw
    prose sample or token list of the item (``mc.form_in``) but in none of the digest's evidence
    lines. The bank's forms are loose, so this is an upper bound on what the digest dropped."""
    lost: list[str] = []
    n_in_raw = n_parts = 0
    for it in scope:
        i = it["name"]
        cells = by_item.get(i) or []
        if not cells:
            continue
        raw = "\n".join(
            " | ".join(c.tokens) if c.tokens is not None else "\n".join(c.samples or ())
            for c in cells
        )
        kept = "\n".join(ln.text for ln in col.evidence.get(i, ()))
        for k, p in enumerate(it["parts"]):
            n_parts += 1
            forms = [str(p["gold"]), *map(str, p.get("forms") or ())]
            if not mc.form_in(raw, forms):
                continue
            n_in_raw += 1
            if not mc.form_in(kept, forms):
                lost.append(f"{i}|p{k}")
    return {
        "n_parts": n_parts,
        "n_parts_in_raw": n_in_raw,
        "n_parts_lost": len(lost),
        "share_of_parts": len(lost) / n_parts if n_parts else None,
        "parts": lost,
    }


def run(args: JudgeArgs) -> FamilyResult:
    header, items = load()
    stamp = instrument(header)
    scope = item_scope(items, args)
    by_id = {it["name"]: it for it in scope}
    cells, rep = reads.load(args, FAMILY, ids=list(by_id))
    if digest.summary_mode(args):
        return _run_summary(args, header, scope, by_id, cells, rep, stamp)
    return _run_native(args, header, scope, by_id, cells, rep, stamp)


def _meta(c: Cell, i: str, k: int, part: Mapping[str, Any], sample_idx: int = 0) -> dict:
    return {
        "cell": c.key,
        "id": i,
        "part": k,
        "layer": c.layer,
        "pos": c.pos,
        "sample_idx": sample_idx,
        "gold_position": part["gold_position"],
        "n_options": len(part["options"]),
    }


def _run_native(
    args: JudgeArgs,
    header: Mapping[str, Any],
    scope: list[dict],
    by_id: dict[str, dict],
    cells: list[Cell],
    rep: LoadReport,
    stamp: str,
) -> FamilyResult:
    """Native mode: one MC call per (part, cell, sample) for prose, per (part, cell) for a token
    list (``family.render_bag``: the raw ranked tokens), no draws, the same verification. The
    instrument of the ATI panel (one cell per item) and of the toy examples."""
    nonempty = [c for c in cells if not c.empty]
    spend = Spend()
    pre = Preflighter(args.dry_run)
    note = _token_note()
    shown: list[tuple[Cell, int, str]] = []  # (the cell cut to the one sample shown, idx, text)
    if rep.kind == "tokens":
        for c in nonempty:
            bag = render_bag(c.tokens or (), c.scores)
            if bag is not None:
                shown.append((c, 0, bag))
    else:
        for c in nonempty:
            shown.extend(
                (dataclasses.replace(c, samples=(s,)), j, digest.sample_text(s))
                for j, s in enumerate(c.samples or ())
                if s.strip()
            )
    units: list[Unit] = []
    for c, j, text in shown:
        it = by_id[c.id]
        chat = prompts.render_user_turn(it["messages"])
        lines = digest.native_lines([c])
        for k, part in enumerate(it["parts"]):
            user = prompts.render_user(
                chat,
                text,
                part["options"],
                part["judge_label"],
                part["type"],
                mixed=bool(it.get("mixed_state")),
                token_note=note,
            )
            units.append(
                Unit(f"{c.key}:s{j}|p{k}", it, k, user, lines, [c], _meta(c, c.id, k, part, j))
            )
    with Cache(args.out / "cells.jsonl") as cache:
        rows, tally = judge_units(
            args,
            units,
            cache=cache,
            spend=spend,
            pre=pre,
            prompt_version=CALL_VERSION,
            broader=header.get("broader_by_type") or {},
        )
    per_part: dict[tuple[str, int], list[tuple[Unit, dict | None]]] = defaultdict(list)
    judged_cells: set[str] = set()
    for u in units:
        per_part[(u.item["name"], u.k)].append((u, rows[u.key]))
        if rows[u.key] is not None:
            judged_cells.add(u.meta["cell"])
    have = {c.id for c in cells}
    item_rows = []
    for it in scope:
        i = it["name"]
        if i not in have:
            item_rows.append(item_row(it, i, "no_readouts", _parts_all(it, False)))
            continue
        if not any(per_part.get((i, k)) for k in range(len(it["parts"]))):
            item_rows.append(item_row(it, i, "empty_readouts", _parts_all(it, False)))
            continue
        parts = [native_part(k, p, per_part.get((i, k), [])) for k, p in enumerate(it["parts"])]
        item_rows.append(item_row(it, i, "judged", parts))
    # as summary mode counts them: an item a failed call left undecided is unjudged, even in a
    # cell whose other units landed (plus the cells of decided items where no unit landed)
    undecided = {r["id"] for r in item_rows if r["state"] == "judged" and r["pass"] is None}
    return with_readout_count(
        score.score(
            args,
            scope,
            item_rows,
            draws=[(u.item, u.k, rows[u.key]) for u in units],
            cells=cells,
            rep=rep,
            spend=spend,
            prompt_version=stamp,
            n_unjudged=len(undecided)
            + sum(1 for c in nonempty if c.key not in judged_cells and c.id not in undecided),
            n_empty=len(cells) - len(nonempty),
            tally=tally,
            config_extra={"aggregate": "native", "options": "bank order"},
        ),
        scope,
        cells,
    )


def _run_summary(
    args: JudgeArgs,
    header: Mapping[str, Any],
    scope: list[dict],
    by_id: dict[str, dict],
    cells: list[Cell],
    rep: LoadReport,
    stamp: str,
) -> FamilyResult:
    """Summary mode (the instrument of record): every read cell of an item -> one digest -> per
    part ``n_draws`` MC calls on it (draw 0 keeps the single-call key ``<cell key>|p<k>``). An
    item with no cells and an empty digest are fails (the whole-scope denominator); an
    unsummarized item (a refused or collapsed digest) is undecided, never a fail."""
    by_item: dict[str, list[Cell]] = defaultdict(list)
    for c in cells:
        by_item[c.id].append(c)
    spend = Spend()
    pre = Preflighter(args.dry_run)
    pv = digest.prompt_version(CALL_VERSION, args, FAMILY)
    n = n_draws(args)
    passed = {i: by_item[i] for i in by_id if by_item.get(i)}
    with Cache(args.out / "cells.jsonl") as cache:
        col = digest.collapse(
            FAMILY,
            passed,
            args=args,
            cache=cache,
            spend=spend,
            preflight=pre.for_judge(digest.summarizer_judge(args)),
            task_note=_spec().task_note,
            expect_all=[c for v in passed.values() for c in v],
        )
        source_kind = digest.as_prose(rep)
        # the template always carries the spec's token rule; the digest note is asked without it
        note = digest.summary_note(args, None, family=FAMILY)
        token_note = _token_note()
        units: list[Unit] = []
        for i, c in col.cells.items():
            if i in col.unsummarized or i in col.empty:
                continue
            it = by_id[i]
            chat = prompts.render_user_turn(it["messages"])
            lines = list(col.evidence.get(i, ()))
            for k, part in enumerate(it["parts"]):
                user = prompts.render_user_summary(
                    chat,
                    note,
                    col.summaries[i],
                    part["options"],
                    part["judge_label"],
                    part["type"],
                    mixed=bool(it.get("mixed_state")),
                    token_note=token_note,
                )
                base = f"{c.key}|p{k}"
                units += [
                    Unit(draw_key(base, d), it, k, user, lines, by_item[i], _meta(c, i, k, part))
                    for d in range(n)
                ]
        rows, tally = judge_units(
            args,
            units,
            cache=cache,
            spend=spend,
            pre=pre,
            prompt_version=pv,
            broader=header.get("broader_by_type") or {},
        )
    per_part: dict[tuple[str, int], list[dict | None]] = defaultdict(list)
    for u in units:
        per_part[(u.item["name"], u.k)].append(rows[u.key])
    item_rows = []
    n_call_undecided = 0
    for it in scope:
        i = it["name"]
        if i not in col.cells:
            item_rows.append(item_row(it, i, "no_readouts", _parts_all(it, False)))
            continue
        key = col.cells[i].key
        if i in col.unsummarized:
            row = item_row(it, key, "unsummarized", _parts_all(it, None))
        elif i in col.empty:
            row = item_row(it, key, "empty_digest", _parts_all(it, False))
        else:
            parts = [summary_part(k, p, per_part[(i, k)]) for k, p in enumerate(it["parts"])]
            row = item_row(it, key, "judged", parts)
            n_call_undecided += row["pass"] is None
        item_rows.append({**row, **col.row(i)})
    return with_readout_count(
        score.score(
            args,
            scope,
            item_rows,
            draws=[(u.item, u.k, rows[u.key]) for u in units],
            cells=cells,
            rep=rep,
            spend=spend,
            prompt_version=digest.prompt_version(stamp + majority_stamp(n), args, FAMILY),
            n_unjudged=len(col.unsummarized) + n_call_undecided,
            n_empty=len(col.empty),
            tally=tally,
            config_extra={
                "draws": n,
                "options": "bank order",
                **digest.config(args, source_kind, FAMILY),
            },
            summary=col.extras(),
            digest_loss=digest_loss(scope, by_item, col),
            n_items_scope=len(scope),
            pinned=digest.pinned(args, FAMILY),
        ),
        scope,
        cells,
    )
