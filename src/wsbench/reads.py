"""The ONE loading entry point of every family (plan 0032 §2.0, §2.6): readouts + the producer's
sidecar, the declared sampling rule, the layer-presence check, the ``reads=lite`` selection and
the ``reads=full`` span check.

``reads.load(args, family)`` replaces every direct ``load_readouts`` call in a family judge. In
this order it: loads the file (``ids`` / ``layers`` / ``positions`` filters); reads the sidecar
``<file>.meta.json``; applies the declared sampling (``readouts.normalize``); checks that every
requested layer is present; applies the lite selection under ``reads=lite``; and under
``reads=full`` checks every (item, layer) holds the family's full span. With a sidecar the
checks enforce (exit 2, or ``partial`` items under ``allow_missing``); a sidecar-less file (test
fixtures, cached v1 readouts) gets the same checks in report-only mode
(``extras.partial_ids_unenforced``, ``config.reads_checked = "no_sidecar"``). A ``prompt_only:``
reader (one cell per item) waives the selection, the span check and the plan guards."""

import functools
import hashlib
import json
import os
import weakref
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from wsbench import fast, readplan, registry
from wsbench.nyt import NO_NYT_ENV
from wsbench.readouts import Cell, LoadReport, load_readouts, normalize, read_sidecar
from wsbench.readplan import FINAL, ReadSpec, lite_select
from wsbench.registry import (
    BANK_FILE_ENV_PREFIX,
    BANK_ROOT_ENV,
    JudgeArgs,
    canonical,
    hash_name,
)

READS = ("full", "lite")
LITE_STAMP = "+reads-lite"
PROMPT_ONLY_PREFIX = "prompt_only:"
# keys never hashed into plan_sha: the lite site, the reads flag, the note, and (critique fix,
# 2026-10-30) the layers, so a file read at more layers than the plan (layers=all) is judged —
# guard (ii) checks the plan's layers are present instead
PLAN_SHA_EXCLUDE = ("lite_positions", "lite_layers", "reads", "note", "layers")


def fail(msg: str) -> Any:
    import sys

    print(msg, file=sys.stderr)
    raise SystemExit(2)


def mode(args: JudgeArgs) -> str:
    """``reads=full|lite`` from ``args.extra["reads"]`` (default ``full``); a bad value exits 2."""
    m = args.extra.get("reads", "full")
    if m not in READS:
        fail(f"reads={m!r}: expected full or lite")
    return m


def stamp(pv: str, m: str) -> str:
    """``pv + "+reads-lite"`` for a lite run (once), ``pv`` unchanged for full."""
    if m == "lite" and not pv.endswith(LITE_STAMP):
        return pv + LITE_STAMP
    return pv


def strip_reads(pv: str) -> str:
    """``pv`` without a trailing ``+reads-lite`` (prompt-only floors serve full and lite rows)."""
    return pv[: -len(LITE_STAMP)] if pv.endswith(LITE_STAMP) else pv


def _env_key() -> tuple[tuple[str, str], ...]:
    keys = [BANK_ROOT_ENV, readplan.NO_NOCOT_ENV, NO_NYT_ENV]
    keys += [k for k in os.environ if k.startswith(BANK_FILE_ENV_PREFIX)]
    return tuple(sorted((k, os.environ.get(k, "")) for k in keys))


@functools.lru_cache(maxsize=64)
def _specs(family: str, _env: tuple[tuple[str, str], ...]) -> dict[str, ReadSpec]:
    return {s.id: s for s in readplan.plan(family, layers=None)}


def specs(family: str) -> dict[str, ReadSpec]:
    """``{item id: ReadSpec}`` of the family's plan of record (no tokenizer, no GPU; cached per
    bank environment). ``$WSB_LAYERS`` is ignored here: the judge's plan is the family's grid."""
    saved = os.environ.pop(readplan.LAYERS_ENV, None)
    try:
        return _specs(family, _env_key())
    finally:
        if saved is not None:
            os.environ[readplan.LAYERS_ENV] = saved


def _clean_row(row: Mapping[str, Any]) -> dict[str, Any]:
    d = {k: v for k, v in row.items() if k not in PLAN_SHA_EXCLUDE}
    if isinstance(d.get("family"), str):  # v1.2.0: a renamed family hashes as its former key
        d["family"] = hash_name(d["family"])
    if isinstance(d.get("extra"), dict):
        d["extra"] = {k: v for k, v in d["extra"].items() if k != "reads"}
        if not d["extra"]:
            d.pop("extra")
    return d


def plan_sha_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    """sha256 over plan rows as ``wsbench plan`` writes them (each row's keys sorted; the
    ``PLAN_SHA_EXCLUDE`` keys dropped). The producer's plan-file mode hashes its input with it."""
    h = hashlib.sha256()
    for row in rows:
        h.update(json.dumps(_clean_row(row), sort_keys=True, ensure_ascii=False).encode())
        h.update(b"\n")
    return h.hexdigest()


def plan_sha(family: str) -> str:
    """``plan_sha_rows`` of ``readplan.plan(family)``'s rows (the producer imports this, so the
    producer's and the judge's hashes agree by construction). Layers are not hashed."""
    return plan_sha_rows(s.row() for s in readplan.plan(family, layers=None))


def fast_plan_sha(family: str, declared: str | None = None) -> str:
    """``plan_sha_rows`` of the family's FAST plan rows (``readplan.plan(family, fast=True)``):
    the ``plan_sha`` a file produced ``--fast`` declares beside ``"fast": fast.VERSION``. With
    ``declared`` (plan 0095), the sha the plan of that mutually compatible version had: each
    row's ``extra["fast"]``, where present, reads ``declared``."""
    rows = [s.row() for s in readplan.plan(family, layers=None, fast=True)]
    if declared is None:
        return plan_sha_rows(rows)
    fam = canonical(family)
    ok = declared in {fast.VERSION, *fast.COMPATIBLE}
    if not ok or fam not in fast.subset(declared):
        raise SystemExit(f"{fam}: not in fast subset {declared}")
    for row in rows:
        if "fast" in (row.get("extra") or {}):
            row["extra"] = {**row["extra"], "fast": declared}
    return plan_sha_rows(rows)


# ---------------------------------------------------------------- plan lineage (plan 0072 0.3)
# A re-freeze of an adapted set that only DROPS items (or edits judge-side fields that are not in
# the plan, e.g. ``mc``) leaves every kept item's plan row as it was, but moves ``plan_sha``.
# ``adapt freeze`` then records the step in ``report.json`` ``families.<f>.plan_lineage`` and
# guard (iii) accepts a readout of an older plan only through a chain of such records, with the
# dropped items' cells removed. Anything else (no record, a changed or added row, no
# ``WSB_BANK_ROOT``) refuses as before: fail-closed.
LINEAGE_KEY = "plan_lineage"
LINEAGE_MAX_STEPS = 64


def clean_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The rows ``plan_sha_rows`` hashes, cleaned the same way (``_clean_row``)."""
    return [_clean_row(r) for r in rows]


def lineage_step(old: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]) -> dict | None:
    """The lineage record of a re-freeze from plan rows ``old`` to ``new`` (``wsbench plan``'s
    rows), or None. A record is written ONLY when the shas differ, no id repeats in either plan,
    every new id is an old id and every new cleaned row equals the old cleaned row of its id:
    ``{"from": <old sha>, "to": <new sha>, "dropped": [ids]}``."""
    o, n = clean_rows(old), clean_rows(new)
    sha_o, sha_n = plan_sha_rows(old), plan_sha_rows(new)
    if sha_o == sha_n:
        return None
    o_ids = [str(r.get("id")) for r in o]
    n_ids = [str(r.get("id")) for r in n]
    if len(set(o_ids)) != len(o_ids) or len(set(n_ids)) != len(n_ids):
        return None
    by_id = dict(zip(o_ids, o, strict=True))
    for iid, row in zip(n_ids, n, strict=True):
        if by_id.get(iid) != row:
            return None
    return {"from": sha_o, "to": sha_n, "dropped": sorted(set(o_ids) - set(n_ids))}


def _root_report() -> dict[str, Any] | None:
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return None
    base = Path(root) if Path(root).is_absolute() else readplan.REPO_ROOT / root
    try:
        return json.loads((base / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _registered_header(family: str) -> dict[str, Any]:
    """The registered bank's header (a wrapped bank's non-``items`` keys), else {}."""
    from wsbench.registry import bank_path

    try:
        raw = json.loads(bank_path(family).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, SystemExit):
        return {}
    return raw if isinstance(raw, dict) else {}


def owner_of(path: Path, family: str, meta: Mapping[str, Any] | None = None) -> str | None:
    """Which member of ``family``'s renamed pair (plan 0101) a readouts file belongs to: by its
    sidecar's ``plan_sha`` (the family's or the partner's own plan, fast plans included), else
    by its item ids (``registry.owner``; ``RenamedKey`` when it holds both members' ids). None
    for a family outside a pair and for a file that says neither."""
    family = canonical(family)
    other, key = registry.partner(family), registry.shared_key(family)
    if other is None or key is None:
        return None
    meta = read_sidecar(Path(path)) if meta is None else meta
    sha = str((meta or {}).get("plan_sha") or "")
    if sha:
        declared = (meta or {}).get("fast")
        for member in (family, other):
            try:
                if declared:
                    mine = fast_plan_sha(member, declared=str(declared))
                else:
                    mine = plan_sha(member)
            except (SystemExit, KeyError):  # not in that fast subset, no plan under this root
                continue
            if sha == mine:
                return member
        return None  # another plan: guard (iii) decides (lineage, or "a different plan")
    from wsbench.readouts import ids_in

    return registry.owner(key, ids=ids_in(Path(path)))


def lineage_drops(family: str, have: str, want: str) -> list[str] | None:
    """The ids dropped on a chain of ``plan_lineage`` records from plan ``have`` to plan ``want``
    (a breadth-first search over ``from -> to`` links, at most ``LINEAGE_MAX_STEPS`` deep): the
    adapted set's ``report.json`` records under ``$WSB_BANK_ROOT``, else (no root, plan 0083) the
    registered bank header's ``plan_lineage``. None when no chain exists, a root has no report,
    or a ``WSB_BANK_FILE_<FAMILY>`` pin overrides the bank (fail-closed)."""
    from wsbench.registry import bank_pin, canonical, lookup_names

    fam = canonical(family)
    if bank_pin(fam) is not None:
        return None
    if os.environ.get(BANK_ROOT_ENV):
        report = _root_report()
        if report is None:
            return None
        fams = report.get("families") or {}
        entry = next((fams[k] for k in lookup_names(fam) if k in fams), {})
    else:
        entry = _registered_header(fam)
    steps = [s for s in entry.get(LINEAGE_KEY) or [] if isinstance(s, dict)]
    frontier: dict[str, set[str]] = {have: set()}
    seen = {have}
    for _ in range(LINEAGE_MAX_STEPS):
        nxt: dict[str, set[str]] = {}
        for sha, dropped in frontier.items():
            for s in steps:
                if s.get("from") != sha or not s.get("to"):
                    continue
                acc = dropped | {str(i) for i in s.get("dropped") or []}
                if s["to"] == want:
                    return sorted(acc)
                if s["to"] not in seen:
                    seen.add(s["to"])
                    nxt[s["to"]] = acc
        if not nxt:
            return None
        frontier = nxt
    return None


# ---------------------------------------------------------------- selection and span check


def _by_item_layer(cells: Iterable[Cell]) -> dict[tuple[str, int], list[Cell]]:
    out: dict[tuple[str, int], list[Cell]] = defaultdict(list)
    for c in cells:
        out[(c.id, c.layer)].append(c)
    return out


def is_prompt_only(reader: str) -> bool:
    return reader.startswith(PROMPT_ONLY_PREFIX)


def select(
    cells: Sequence[Cell],
    specs: Mapping[str, ReadSpec],
    mode: str,
    *,
    reader: str = "",
    declared: str | None = None,
) -> list[Cell]:
    """The cells a ``reads`` mode judges: identity under ``full`` (and for a ``prompt_only:``
    reader); under ``lite`` each item's ``lite_positions`` rule over its positions at each layer,
    at its ``lite_layers`` (an item without a plan row: ``final_token``). Identity, too, for a
    file whose sidecar declares ``reads=lite`` (``declared``): the producer already applied the
    rule, and the rule is not idempotent (``offset_from_end`` over its own single output keeps
    nothing), so it is never applied twice (review of PR #140)."""
    if mode == "full" or is_prompt_only(reader) or declared == "lite":
        return list(cells)
    keep: set[tuple[str, int, int]] = set()
    for (iid, layer), cs in _by_item_layer(cells).items():
        sp = specs.get(iid)
        rule = sp.lite_positions if sp is not None else FINAL
        if sp is not None and sp.lite_layers is not None and layer not in sp.lite_layers:
            continue
        for p in lite_select([c.pos for c in cs], rule):
            keep.add((iid, layer, p))
    return [c for c in cells if (c.id, c.layer, c.pos) in keep]


def _span_ok(positions: Sequence[int], min_positions: int, contiguous: bool) -> bool:
    ps = sorted(set(positions))
    if len(ps) < min_positions:
        return False
    return not contiguous or ps[-1] - ps[0] + 1 == len(ps)


def check_full(
    cells: Sequence[Cell],
    specs: Mapping[str, ReadSpec],
    *,
    min_positions: int,
    contiguous: bool,
    allow_missing: bool,
    reader: str = "",
) -> set[str]:
    """The partial item ids of a ``reads=full`` run. Per (item, layer) the positions must be ONE
    contiguous run (ending at the item's max position) of length >= ``min_positions``
    (``contiguous=False``: just the count). A file whose every (item, layer) holds exactly one
    position, for a family that needs more, exits 2 (it looks like a lite file). Any other
    violation exits 2 naming the first offender unless ``allow_missing`` (then those items are
    returned as partial). A ``prompt_only:`` reader is waived (empty set)."""
    if is_prompt_only(reader) or not cells:
        return set()
    groups = _by_item_layer(cells)
    if min_positions > 1 and all(len({c.pos for c in cs}) == 1 for cs in groups.values()):
        fail(
            "reads=full but the file has 1 position per cell; this looks like a lite file — "
            "use reads=lite"
        )
    bad: set[str] = set()
    first: tuple[str, int] | None = None
    for (iid, layer), cs in sorted(groups.items()):
        if not _span_ok([c.pos for c in cs], min_positions, contiguous):
            bad.add(iid)
            first = first or (iid, layer)
    if bad and not allow_missing:
        assert first is not None
        need = f"one contiguous run of >= {min_positions}" if contiguous else f">= {min_positions}"
        fail(
            f"reads=full: item {first[0]} at L{first[1]} does not hold its full span ({need} "
            f"positions); {len(bad)} item(s) partial (allow_missing=True judges them as partial)"
        )
    return bad


def lite_rule_of(specs: Mapping[str, ReadSpec], ids: Collection[str] | None = None) -> str:
    """The lite rule(s) of the plan rows (of ``ids``), as one canonical JSON string: what a
    ``reads=lite`` result stamps as ``config.lite_rule`` (late fix 2026-10-30: the frozen lite
    rule is part of the lite instrument, and ``scripts/audit_run.py`` checks it)."""
    rules = {
        json.dumps({"positions": sp.lite_positions, "layers": sp.lite_layers}, sort_keys=True)
        for iid, sp in specs.items()
        if ids is None or iid in ids
    }
    return json.dumps([json.loads(r) for r in sorted(rules)], sort_keys=True)


def lite_is_full(specs: Mapping[str, ReadSpec], ids: Collection[str]) -> bool:
    """Every item of ``ids`` has a plan row whose lite rule is ``same`` at the full layers
    (``lite_layers is None``): ``reads=lite`` then judges exactly the ``reads=full`` cells
    (association, conjunctive_association, plan 0061's families), so it gets full's completeness
    checks. An item without a plan row is lite-read at ``final_token`` (``select``), never full."""
    return bool(ids) and all(
        iid in specs
        and specs[iid].lite_positions.get("kind") == "same"
        and specs[iid].lite_layers is None
        for iid in ids
    )


def plan_layers_missing(
    cells: Sequence[Cell], specs: Mapping[str, ReadSpec], mode: str
) -> dict[str, list[int]]:
    """Guard (ii): per item, the plan layers (``lite_layers`` under lite) absent from the file.
    Layers beyond the plan are fine (every present layer is judged)."""
    have: dict[str, set[int]] = defaultdict(set)
    for c in cells:
        have[c.id].add(c.layer)
    out: dict[str, list[int]] = {}
    for iid, got in have.items():
        sp = specs.get(iid)
        if sp is None:
            continue
        want = sp.lite_layers if mode == "lite" and sp.lite_layers is not None else sp.layers
        miss = sorted(set(want) - got)
        if miss:
            out[iid] = miss
    return out


# ---------------------------------------------------------------- load


def min_full_positions(family: str, default: int) -> int:
    """The family's ``reads=full`` minimum span, lowered (never raised) by an ADAPTED bank's
    ``adapt.min_grid_positions`` (a bare-list bank: the set's ``report.json`` entry, under
    ``$WSB_BANK_ROOT`` only): a subject whose template gives a render fewer read positions
    than the 27B's (introspection's neutral grid, ``wsbench.adapt.introspection``). Consulted
    only under a bank override (``$WSB_BANK_FILE_<FAMILY>`` or ``$WSB_BANK_ROOT``, resolved by
    ``registry.bank_path`` with its precedence); the registered banks are never read here."""
    from wsbench import registry

    if not (os.environ.get(BANK_FILE_ENV_PREFIX + family.upper()) or os.environ.get(BANK_ROOT_ENV)):
        return default
    try:
        raw = json.loads(registry.bank_path(family).read_text(encoding="utf-8"))
    except (SystemExit, OSError, ValueError):
        return default
    adapt = raw.get("adapt") if isinstance(raw, dict) else None
    n = adapt.get("min_grid_positions") if isinstance(adapt, dict) else None
    if n is None and not os.environ.get(BANK_FILE_ENV_PREFIX + family.upper()):
        n = _root_min_grid(family)  # a bare-list bank (conjunctive, role_bound) has no header
    return min(default, int(n)) if isinstance(n, int) and n >= 1 else default


def _root_min_grid(family: str) -> int | None:
    """``report.json`` ``families.<family>.min_grid_positions`` of the ``$WSB_BANK_ROOT`` set:
    where a set records the span of a bank that is a bare list (no ``adapt`` header to hold it)."""
    from wsbench import registry

    root = registry.bank_root()
    if root is None:
        return None
    try:
        rep = json.loads((root / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fams = rep.get("families") if isinstance(rep, dict) else None
    entry = fams.get(family) if isinstance(fams, dict) else None
    n = entry.get("min_grid_positions") if isinstance(entry, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) else None


def _spec_of(family: str) -> Any:
    from wsbench import registry

    try:
        return registry._spec_for_bank(family)  # also when the registry was emptied
    except SystemExit:
        return None


def load(
    args: JudgeArgs,
    family: str,
    path: Path | None = None,
    *,
    ids: Collection[str] | None = None,
    positions: Mapping[str, Collection[int]] | None = None,
) -> tuple[list[Cell], LoadReport]:
    """Every family's loader (module docstring). The report is also remembered beside ``args``
    (``report_of(args)``) so ``mcjudge.base_config`` and the runner stamp ``config.reads``,
    ``sampling``, ``sampling_source``, ``reader``, ``reads_checked`` and ``layers_judged``."""
    path = Path(path or args.readouts)
    m = mode(args)
    # plan 0090: the fast flag is JudgeArgs.scope (set by the runner), never an opts= key
    fast_entry = fast.entry(family) if args.scope == fast.SCOPE else None
    fast_ids: set[str] = set()
    if fast_entry is not None:
        if m == "lite":
            fail(f"{path}: --fast judges the fast subset's full reads; drop reads=lite")
        fast_ids = set(fast_entry["read_ids"])
        if ids is not None:
            fast_ids &= set(ids)
        elif positions is not None:
            fast_ids &= set(positions)
        ids = fast_ids
    cells, rep = load_readouts(path, ids=ids, layers=args.layers, positions=positions)
    meta = read_sidecar(path)
    other = registry.partner(canonical(family))
    if other is not None:  # the last guard of a renamed pair, whatever the file is called
        try:
            who = owner_of(path, family, meta)
        except registry.RenamedKey:
            fail(
                f"{path} holds readouts of both {canonical(family)} and {other} (the two "
                "families of a renamed pair, plan 0101): split it by family"
            )
        if who == other:
            fail(
                f"{path} holds {other} readouts (before 2026-11-20 "
                f"{registry.shared_key(other)!r} named the single-token family, plan 0101): "
                f"judge it with family={other}"
            )
    rep.meta = meta
    rep.reads = m
    rep.layers_requested = None if args.layers is None else sorted(set(args.layers))
    reader = str((meta or {}).get("reader") or "")
    rep.reader = reader
    # sampling: override > declared > default (never inferred from bullet shape)
    over = args.extra.get("sampling")
    if over:
        sampling, source = over, "override"
    elif meta is not None and meta.get("sampling"):
        sampling, source = str(meta["sampling"]), "declared"
    else:
        sampling = "tokens10" if rep.kind == "tokens" else "prose1"
        source = "default"
    normed, diag = normalize(cells, sampling)
    if source != "default":
        cells = normed
    # a sidecar-less file without sampling= is judged as it is (report-only, like the span
    # check): the counts say what the declared rule would trim; campaign files always declare
    rep.sampling, rep.sampling_source = sampling, source
    rep.n_samples_trimmed = diag["n_samples_trimmed"]
    rep.n_packed_ambiguous = diag["n_packed_ambiguous"]
    rep.n_cells_short = diag["n_cells_short"]
    prompt_only = is_prompt_only(reader)
    # guard (i): a declared lite file under a full run
    if meta is not None and meta.get("reads") == "lite" and m == "full":
        fail(f"{path}: file was produced reads=lite; judge it with reads=lite")
    # plan 0090: a file produced from the fast plan holds only the fast reads
    declared_fast = meta.get("fast") if meta is not None else None
    if declared_fast is not None and fast_entry is None:
        fail(f"{path}: file was produced --fast; judge it with --fast")
    # explicit layers=: every requested layer must be present (§2.1.7)
    if args.layers is not None and not prompt_only:
        got = {c.layer for c in cells}
        miss = sorted(set(args.layers) - got)
        if miss:
            if not args.allow_missing:
                fail(f"layers= asks for L{miss[0]}, file has {sorted(got)} ({path})")
            rep.layers_missing = miss
    spec = _spec_of(family)
    min_pos = int(getattr(spec, "min_full_positions", 2)) if spec is not None else 2
    min_pos = min_full_positions(family, min_pos)
    contiguous = bool(getattr(spec, "full_contiguous", True)) if spec is not None else True
    if prompt_only:
        rep.reads_checked = "prompt_only"
        _attach(args, rep)
        return cells, rep
    fast_file = fast_entry is not None and declared_fast is not None
    # plans 0094 / 0095: a compatible version's file is judged as it is (identical entries for
    # every family in both subsets; its plan_sha is checked as that version's, below)
    if fast_file and declared_fast not in {fast.VERSION, *fast.COMPATIBLE}:
        fail(
            f"{path}: readouts were produced for another fast subset ({declared_fast!r}, not "
            f"{fast.VERSION!r})"
        )
    # plan 0095: the declared version's own file must hold the family (with or without plan_sha)
    if fast_file and canonical(family) not in fast.subset(declared_fast):
        fail(f"{path}: {canonical(family)}: not in fast subset {declared_fast}")
    fast_rule = dict(fast_entry.get("positions") or {}) if fast_entry is not None else {}
    if fast_rule and fast_rule.get("kind") not in readplan.FAST_KINDS:
        fail(f"{family}: unknown fast positions rule {fast_rule!r}")
    if fast_file:
        # a FAST file carries the fast plan's own sha (no lineage); its span is the fast rule's
        if meta is not None and meta.get("plan_sha"):
            # the sha the declared (compatible) version's own plan had; the guard is retained
            want, have = fast_plan_sha(family, declared=declared_fast), str(meta["plan_sha"])
            if have != want:
                fail(
                    f"{path}: readouts were produced for a different fast plan (plan_sha "
                    f"{have[:12]} != {want[:12]})"
                )
        if fast_rule.get("kind") == "last_n":
            min_pos, contiguous = int(fast_rule["n"]), True
        elif fast_rule:  # punct_special: at least one position per (item, layer)
            min_pos, contiguous = 1, False
    # guard (iii): plan drift (never waived by allow_missing); an adapted set's drop-only
    # re-freeze is accepted only through its recorded lineage (plan 0072 0.3), dropped ids removed
    elif meta is not None and meta.get("plan_sha"):
        want = plan_sha(family)
        have = str(meta["plan_sha"])
        if have != want:
            dropped = lineage_drops(family, have, want)
            if dropped is None:
                fail(
                    f"{path}: readouts were produced for a different plan (plan_sha "
                    f"{have[:12]} != {want[:12]})"
                )
            gone = set(dropped)
            n_before = len(cells)
            cells = [c for c in cells if c.id not in gone]
            rep.plan_lineage = {
                "from": have,
                "to": want,
                "n_dropped_items": len(gone),
                "n_dropped_cells": n_before - len(cells),
            }
    try:
        sp = specs(family)
    except (SystemExit, KeyError, OSError, ValueError):
        sp = {}
    enforce = meta is not None
    if m == "lite":
        rep.lite_rule = lite_rule_of(sp, {c.id for c in cells})
    declared = str(meta.get("reads") or "") if meta is not None else None
    for c in cells:  # before the selection: lite keeps every position's token for context
        if c.token is not None:
            rep.site_tokens.setdefault(c.id, {}).setdefault(c.pos, c.token)
    lite_full = m == "lite" and lite_is_full(sp, {c.id for c in cells})
    if (
        lite_full
        and meta is not None
        and min_pos > 1
        and cells
        and all(len({c.pos for c in cs}) == 1 for cs in _by_item_layer(cells).values())
    ):
        # plan 0061: a file produced under a superseded single-site lite rule (final token,
        # MCDM's ' to') would otherwise be judged as the `same` instrument (any sidecar file:
        # check_full's own 1-position message would say "use reads=lite" to a lite run)
        fail(
            f"{path}: reads=lite with 1 position per cell, but this family's lite rule is `same` "
            "(lite = the full positions); a lite-site file (a superseded lite rule) or a "
            "truncated read — re-produce it, or judge the full file with reads=lite"
        )
    before = cells
    cells = select(cells, sp, m, reader=reader, declared=declared)
    if m == "lite" and before and not cells:
        # the rule kept nothing: a file that holds only the lite site, undeclared (a sidecar-less
        # toy file), would otherwise judge zero cells and report n items as plain negatives
        fail(
            f"{path}: reads=lite kept no readout (lite rule {rep.lite_rule!r} over the file's "
            "positions); a file produced at the lite site must declare reads=lite in its sidecar"
        )
    partial: set[str] = set()
    if m == "full" or lite_full:
        partial |= (
            check_full(
                cells,
                sp,
                min_positions=min_pos,
                contiguous=contiguous,
                allow_missing=args.allow_missing or not enforce,
            )
            if enforce
            else _report_only(cells, sp, min_pos, contiguous)
        )
    if args.layers is None:
        gaps = plan_layers_missing(cells, sp, m)
        if gaps and enforce and not args.allow_missing:
            iid = sorted(gaps)[0]
            fail(
                f"{path}: item {iid} lacks plan layer(s) {gaps[iid]} (layers=None judges the "
                "plan's layers; pass layers= to judge fewer)"
            )
        partial |= set(gaps)
    if fast_file:  # an item of the fast read ids absent from a FAST file is partial
        absent = sorted(fast_ids - {c.id for c in cells})
        if absent and enforce and not args.allow_missing:
            fail(
                f"{path}: fast read item {absent[0]} has no readout; {len(absent)} item(s) "
                "absent (allow_missing=True judges them as partial)"
            )
        partial |= set(absent)
    if fast_rule:  # after every check: narrow to the fast positions (idempotent on a FAST file)
        rep.fast_rule = json.dumps(fast_rule, sort_keys=True)
        rep.n_cells_before_fast = len(cells)
        cells, rep.fast_fallback_ids = fast_narrow(cells, fast_rule, path)
    if enforce:
        rep.partial_ids = sorted(partial)
        rep.reads_checked = "sidecar"
    else:
        rep.partial_ids_unenforced = sorted(partial)
        rep.reads_checked = "no_sidecar"
    _attach(args, rep)
    return cells, rep


def fast_narrow(
    cells: Sequence[Cell], rule: Mapping[str, Any], path: Path | str = ""
) -> tuple[list[Cell], list[str]]:
    """Plan 0090: ``(cells, fallback ids)`` narrowed per (item, layer) to a fast positions rule.
    ``last_n``: the last n positions present. ``punct_special``: the positions whose ``token``
    is a fast site (``readplan.is_fast_site``, the producer's own predicate), else the item's
    last position there (its id is returned); a row without ``token`` exits 2."""
    keep: set[tuple[str, int, int]] = set()
    fallback: set[str] = set()
    for (iid, layer), cs in _by_item_layer(cells).items():
        ps = sorted({c.pos for c in cs})
        if rule["kind"] == "last_n":
            chosen = ps[-int(rule["n"]) :]
        else:
            if any(c.token is None for c in cs):
                fail(
                    f"{path}: item {iid} at L{layer} has rows without `token`; the fast "
                    "punct_special rule needs each row's read-site token"
                )
            chosen = sorted({c.pos for c in cs if readplan.is_fast_site(str(c.token))})
            if not chosen:
                chosen = ps[-1:]
                fallback.add(iid)
        keep.update((iid, layer, p) for p in chosen)
    return [c for c in cells if (c.id, c.layer, c.pos) in keep], sorted(fallback)


def _report_only(
    cells: Sequence[Cell], specs: Mapping[str, ReadSpec], min_pos: int, contiguous: bool
) -> set[str]:
    return {
        iid
        for (iid, _layer), cs in _by_item_layer(cells).items()
        if not _span_ok([c.pos for c in cs], min_pos, contiguous)
    }


_REPORTS: list[tuple[weakref.ref, LoadReport]] = []  # (args, the last load's report), weakly held


def _attach(args: JudgeArgs, rep: LoadReport) -> None:
    """Remember this run's load report beside ``args`` (not a JudgeArgs field, so
    ``JudgeArgs(**vars(args))`` keeps working). ``dataclasses.replace(args, judge=…)`` copies
    share ``args.extra`` and ``readouts``, so :func:`report_of` finds the report through them."""
    _REPORTS[:] = [(r, x) for r, x in _REPORTS if r() is not None and r() is not args]
    _REPORTS.append((weakref.ref(args), rep))


def report_of(args: JudgeArgs) -> LoadReport | None:
    """The report of the last ``reads.load`` on ``args`` (or on the args it was copied from)."""
    for r, rep in reversed(_REPORTS):
        a = r()
        if a is args:
            return rep
    for r, rep in reversed(_REPORTS):
        a = r()
        if a is not None and a.extra is args.extra and a.readouts == args.readouts:
            return rep
    return None


def config_stamps(args: JudgeArgs) -> dict[str, Any]:
    """The ``config`` keys a result carries from its load (``mcjudge.base_config`` and the
    runner call this)."""
    rep = report_of(args)
    m = mode(args)
    if rep is None:
        return {"reads": m, "layers_judged": args.layers}
    return {
        "reads": m,
        "sampling": rep.sampling,
        "sampling_source": rep.sampling_source,
        "reader": rep.reader,
        "reads_checked": rep.reads_checked,
        "layers_judged": rep.layers_requested if rep.layers_requested is not None else rep.layers,
        **({"lite_rule": rep.lite_rule} if m == "lite" else {}),
        **({"fast_rule": rep.fast_rule} if rep.fast_rule else {}),
        **({"plan_lineage": rep.plan_lineage} if rep.plan_lineage else {}),
    }


def extras_of(args: JudgeArgs) -> dict[str, Any]:
    rep = report_of(args)
    if rep is None:
        return {}
    return {
        "partial_ids": rep.partial_ids,
        "partial_ids_unenforced": rep.partial_ids_unenforced,
        "layers_missing": rep.layers_missing,
        "n_samples_trimmed": rep.n_samples_trimmed,
        "n_packed_ambiguous": rep.n_packed_ambiguous,
        "n_cells_short": rep.n_cells_short,
        **(
            {
                "n_cells_before_fast": rep.n_cells_before_fast,
                "fast_fallback_ids": rep.fast_fallback_ids,
            }
            if rep.fast_rule
            else {}
        ),
    }


def incomplete(args: JudgeArgs) -> bool:
    """The load left items partial or requested layers missing (sidecar-enforced only)."""
    rep = report_of(args)
    return rep is not None and bool(rep.partial_ids or rep.layers_missing)
