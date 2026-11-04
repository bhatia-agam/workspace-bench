"""Refill the five small families until target or out of capacity (plan 0066 §1): the policy
table, ``stop_status``, the sha-pinned box pools, buggy_code's pair selection and the driver."""

import hashlib
import importlib
import json
import os
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import store

BUGGY = "buggy_code"
MSDM = "model_specific_directed_modulation"
KCUTOFF = "knowledge_cutoff"
WI = "wrong_intermediate"
MH2 = "multihop_mt_v2"

# the adapt module that owns each family's stages and optional hooks (row_passes, select_refill,
# refill_wave, prior_tally, build_pool); buggy_code goes through run.fill
FAMILY_MODULES = {MSDM: "msdm", KCUTOFF: "kcutoff", WI: "wrong_intermediate", MH2: "mhmt2"}


def _registered_size(family: str) -> int:
    return len(store.original_bank(family)[1])


def pair_count(items: list[dict]) -> int:
    """Groups of 2 whose members are each other's ``twin`` (registered field, or derived from the
    authored ``-au-`` / ``-au-clean-`` ids)."""
    from .run import buggy_twin

    by_id = {store.item_id(it): it for it in items}
    n = 0
    for iid, it in by_id.items():
        tw = buggy_twin(it)
        if tw and tw in by_id and buggy_twin(by_id[tw]) == iid:
            n += 1
    return n // 2


def registered_pairs() -> int:
    """buggy_code's target: the registered twin-pair count (24)."""
    return pair_count(store.original_bank(BUGGY)[1])


@dataclass(frozen=True)
class Policy:
    unit: str
    target_fn: Callable[[], int]
    n_min: int
    y_min: float
    sources: tuple[str, ...]
    easiest: str

    @property
    def target(self) -> int:
        return self.target_fn()


POLICY: dict[str, Policy] = {
    BUGGY: Policy("pairs", registered_pairs, 60, 0.03, ("author: brief tiers t1, t2",), "t2"),
    MSDM: Policy("categories", lambda: _registered_size(MSDM), 200, 0.03,
                 ("bank", "retired_panel_gate", "pool: msdm_pool.jsonl"), "ext pool"),
    KCUTOFF: Policy("items", lambda: _registered_size(KCUTOFF), 1000, 0.01,
                    ("bank", "retired_panel_gate", "pool: kcutoff_pool.jsonl"), "ext pool"),
    WI: Policy("items", lambda: _registered_size(WI), 200_000, 5e-5,
               ("source 0: unmapped templates", "re-scrape"), "expanded scrape"),
    MH2: Policy("items", lambda: _registered_size(MH2), 300, 0.03,
                ("bank", "pool: mh2_pool.json"), "2-hop pool"),
}  # fmt: skip

# the fill / auto families the strict freeze guard covers by their `untried` status (§1.3)
UNTRIED_GUARDED = frozenset({
    "typo_mt", "association", "basic_readout", "basic_readout_mt",
    "arithmetic_intermediates", "relational_multihop", "chain_intermediates",
})  # fmt: skip


def stop_status(
    have: int,
    target: int,
    tried: int,
    landed: int,
    n_min: int,
    y_min: float,
    exhausted: bool,
    budget_hit: bool | str,
    cap_binding: bool = False,
    hold: str | None = None,
) -> tuple[str | None, str]:
    """Plan 0066 §1.2, conditions 1-6 in order; ``(None, "")`` = keep refilling. ``hold`` (the
    family's ``refill_hold``) turns an ``ooc`` into ``partial`` (§11.6). ``budget_hit`` may name
    the budget spent."""
    if have >= target:
        return "full", f"{have} >= target {target}"
    low = tried >= n_min and tried > 0 and landed / tried < y_min
    rule = f"yield {landed}/{tried} < {y_min:g} on >= {n_min} candidates at the easiest level"
    if low and have < target / 2:
        if hold:
            return "partial", f"ooc held (refill_hold: {hold}); {rule}"
        return "ooc", f"{rule}, {have} < {target}/2"
    if exhausted:
        return "partial", "pool exhausted"
    if budget_hit:
        which = budget_hit if isinstance(budget_hit, str) else "budget"
        return "partial", f"budget spent ({which})"
    if cap_binding:
        return "partial", "crash cap binding"
    if low:
        return "partial", f"low yield above half: {rule}, {have} >= {target}/2"
    return None, ""


# ---------------------------------------------------------------------------- pools (decision 3)
POOL_FILES = {
    "msdm": "msdm_pool.jsonl",
    "kcutoff": "kcutoff_pool.jsonl",
    "mh2": "mh2_pool.json",
    "mh2v2": "mh2_pool.v2.json",  # decision 7: + the adversary over the S1-only candidates
}
# pinned once built on the box by scripts/build_adapt_pools.py (plan 0066 §8 step 1, 2026-11-04;
# the builds are deterministic, two builds gave the same bytes); None = not built yet
POOL_SHA256: dict[str, str | None] = {
    "msdm": "b1936e2efc4ac61230f69ab4d70da622ba1da83e7348ed25d24c795e6af3b073",
    "kcutoff": "0597d19caace1866a860dffb697a024e4ee12ab5245090591f54c6ba9ff3e614",
    "mh2": "553df6a6de636ddad043b63bcb21b7e38cc35cb2a89a13f7749e6910d2b29926",
    # decision 7 (built 2026-11-04 for GLM-5.3: + the GW adversary over the S1-only candidates)
    "mh2v2": "7e3e4d16da32ddef44a9d452474a4ddb12cf1be104ec6c8161bfebc9bf394629",
}
DEFAULT_POOL_DIR = "/workspace/wsb-runs/pools"


def pool_dir() -> Path:
    return Path(os.environ.get("WSB_POOL_DIR") or DEFAULT_POOL_DIR)


def _verified_bytes(name: str) -> tuple[Path, bytes]:
    if name not in POOL_FILES:
        raise SystemExit(f"refill: unknown pool {name!r}; known: {sorted(POOL_FILES)}")
    path = pool_dir() / POOL_FILES[name]
    pin = POOL_SHA256.get(name)
    if pin is None:
        raise SystemExit(
            f"refill: pool {name!r} is not pinned (refill.POOL_SHA256[{name!r}] is None); build it "
            f"with scripts/build_adapt_pools.py {name} and pin its sha256 (plan 0066 §8)"
        )
    if not path.is_file():
        raise SystemExit(f"refill: pool file {path} is missing (set WSB_POOL_DIR; pinned {pin})")
    data = path.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != pin:
        raise SystemExit(f"refill: pool {path} sha256 mismatch: pinned {pin}, file {got}")
    return path, data


def pool_path(name: str) -> Path:
    """The verified pool file (refuses when unpinned, missing or not the pinned bytes)."""
    return _verified_bytes(name)[0]


def load_pool(name: str) -> Any:
    """The verified pool, parsed from the very bytes that were hashed: a ``.jsonl`` pool is a list
    of rows (a header row, if any, is the first), a ``.json`` pool its object."""
    path, data = _verified_bytes(name)
    text = data.decode("utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.split("\n") if line.strip()]
    return json.loads(text)


# ---------------------------------------------------------------------------- per-row hooks
BUGCLAIM_REQUIRED = True
BUGCLAIM = "bugclaim"


def _module(family: str):
    name = FAMILY_MODULES.get(family)
    return importlib.import_module(f"wsbench.adapt.{name}") if name else None


def _hook(family: str, attr: str):
    mod = _module(family)
    return getattr(mod, attr, None) if mod is not None else None


def has_bugclaim(row: dict) -> bool:
    legs = (row.get("gate") or {}).get("legs") or {}
    return any(k == BUGCLAIM or str(k).startswith(BUGCLAIM) for k in legs)


def row_passes(family: str, row: dict) -> bool:
    """Gate pass AND the family's newer legs (§11.6): a buggy_code clean row needs its
    ``bugclaim`` leg; the other families defer to their module's optional ``row_passes(row)``."""
    if not row["gate"].get("pass"):
        return False
    if family == BUGGY:
        # every clean row, originals included: plan 0066 §2.2 regates all 38 clean originals
        # (`refill families=buggy_code` re-asks every passing clean row lacking the leg,
        # authored ones too), and no pre-0066 test freezes buggy_code
        if BUGCLAIM_REQUIRED and row["item"].get("src") == "clean":
            return has_bugclaim(row)
        return True
    hook = _hook(family, "row_passes")
    return bool(hook(row)) if hook is not None else True


def bugclaim_missing(rows: list[dict]) -> list[str]:
    """The ids of buggy_code clean rows whose gate passes but which have no ``bugclaim`` leg
    (gated before plan 0066): ``row_passes`` fails them, so freeze would ship none of them."""
    return [
        r["id"]
        for r in rows
        if r["gate"].get("pass") and r["item"].get("src") == "clean" and not has_bugclaim(r)
    ]


def bugclaim_warning(n: int) -> str:
    """The freeze message for ``n`` clean rows lacking the ``bugclaim`` leg."""
    return (
        f"{BUGGY}: {n} clean rows have no {BUGCLAIM} leg (gated before plan 0066) and fail "
        f"row_passes; before freezing run `refill families={BUGGY}` (re-asks the missing leg "
        f"on every passing clean row, originals and authored) or `gate families={BUGGY} "
        f"regate=true` (re-gates every passing authored row; `profile families={BUGGY} "
        f"regate=true` re-gates the originals only)"
    )


def _with_passes(family: str, rows: list[dict]) -> list[dict]:
    """Rows whose gate passes but which fail ``row_passes`` become non-passing copies."""
    out = []
    for r in rows:
        if r["gate"].get("pass") and not row_passes(family, r):
            r = {**r, "gate": {**r["gate"], "pass": False}, "selected": False}
        out.append(r)
    return out


def apply_select_hook(family: str, rows: list[dict]) -> list[dict]:
    """The family's ``select_refill(rows) -> rows`` over its NON-original rows (originals kept as
    they are, first, in order); a module without one changes nothing."""
    hook = _hook(family, "select_refill")
    if hook is None:
        return rows
    orig = [r for r in rows if r["origin"] == "original"]
    return orig + list(hook([r for r in rows if r["origin"] != "original"]))


def freeze_rows(family: str, rows: list[dict]) -> list[dict]:
    """What freeze and the refill select from: ``row_passes`` applied, then the select hook."""
    return apply_select_hook(family, _with_passes(family, rows))


# ---------------------------------------------------------------------------- buggy_code pairs
def _is_crash(group: list[dict]) -> bool:
    return any(
        r["item"].get("src") == "buggy" and r["item"].get("consequence_class") == "crash"
        for r in group
    )


def _buggy_groups(rows: list[dict]) -> list[list[dict]]:
    from .run import buggy_twin

    groups: dict[Any, list[dict]] = defaultdict(list)
    for r in rows:
        tw = buggy_twin(r["item"])
        groups[frozenset((r["id"], str(tw))) if tw else r["id"]].append(r)
    return list(groups.values())


def _authored_pair(group: list[dict]) -> bool:
    return len(group) == 2 and all(r["origin"] != "original" for r in group)


def buggy_classes(rows: list[dict]) -> tuple[int, int]:
    """(authored non-crash, authored crash) pairs whose two twins both pass (``row_passes``)."""
    rows = _with_passes(BUGGY, rows)
    ok = [g for g in _buggy_groups(rows) if _authored_pair(g) and all(r["gate"]["pass"] for r in g)]
    crash = sum(_is_crash(g) for g in ok)
    return len(ok) - crash, crash


def buggy_selection(
    rows: list[dict], originals_target: int = 63, quota: dict[str, int] | None = None
) -> list[dict]:
    """Plan 0066 §2.4: both-pass groups (pairs atomic) ordered originals first, then authored
    non-crash pairs in gate order, then authored crash pairs (at most ``floor(n_nc / 4)``); then
    the existing ``select`` with the item cap and ``src`` quota. Authored singletons are dropped."""
    from .run import select

    rows = _with_passes(BUGGY, rows)
    order = {id(r): i for i, r in enumerate(rows)}
    passing = [g for g in _buggy_groups(rows) if all(r["gate"]["pass"] for r in g)]
    passing.sort(key=lambda g: min(order[id(r)] for r in g))
    orig = [g for g in passing if all(r["origin"] == "original" for r in g)]
    authored = [g for g in passing if _authored_pair(g)]
    nc = [g for g in authored if not _is_crash(g)]
    crash = [g for g in authored if _is_crash(g)][: len(nc) // 4]
    ordered = [r for g in orig + nc + crash for r in sorted(g, key=lambda r: order[id(r)])]
    return select(BUGGY, ordered, originals_target, quota)


def selected_pairs(rows: list[dict]) -> int:
    """The pair count of selected rows (mutual twins)."""
    return pair_count([r["item"] for r in rows])


def crash_cap_binds(rows: list[dict]) -> bool:
    nc, crash = buggy_classes(rows)
    return crash > nc // 4


# ---------------------------------------------------------------------------- report block
def refill_block(entry: dict | None) -> dict | None:
    """A family entry's ``refill``, an old string value read as ``{stop: <string>}``."""
    val = (entry or {}).get("refill")
    if val is None:
        return None
    return {"stop": val} if isinstance(val, str) else dict(val)


def change_text(block: dict, measured: str = "") -> str:
    """The family's ``change`` line from its refill block (§1.3); an old string block (only
    ``stop``) keeps the ``measured`` line (``generate.describe``) and appends its stop."""
    if set(block) == {"stop"}:
        return f"{measured}; refill: {block['stop']}" if measured else f"refill: {block['stop']}"
    parts = [f"refill via {block.get('route', '?')}: {block.get('have')}/{block.get('target')} "
             f"{block.get('unit', 'items')}"]  # fmt: skip
    if block.get("tried") is not None:
        y = block.get("yield")
        ys = f", yield {y:.2%}" if isinstance(y, int | float) else ""
        parts.append(f"{block.get('landed')} landed of {block['tried']} tried{ys}")
    if block.get("pool_size") is not None:
        parts.append(f"pool {block.get('pool_used')}/{block['pool_size']} used")
    parts.append(f"stop: {block.get('stop')}")
    return "; ".join(parts)


def write_block(model: str, family: str, block: dict, status: str) -> None:
    def _set(report: dict) -> None:
        entry = report.setdefault("families", {}).setdefault(family, {})
        entry["refill"] = block
        entry["status"] = status

    store.update_report(model, _set)


# ---------------------------------------------------------------------------- driver
def have_of(model: str, family: str) -> int:
    """``have`` in the family's unit, through the same selection freeze uses."""
    from . import run

    _h, originals = store.original_bank(family)
    rows = freeze_rows(family, run._bank_rows(model, family, originals))
    quota = run.quotas(family, originals)
    if family == BUGGY:
        return selected_pairs(buggy_selection(rows, len(originals), quota))
    return len(run.select(family, rows, len(originals), quota))


def prior_tally(model: str, family: str) -> tuple[int, int]:
    """Candidates already gated with the same construction (§1.2 "What counts"): the module's
    ``prior_tally(model) -> (tried, landed)`` if it has one (wrong_intermediate's screened
    candidates are not in the gate log), else the gate log (``row_passes`` for landed)."""
    hook = _hook(family, "prior_tally")
    if hook is not None:
        tried, landed = hook(model)
        return int(tried), int(landed)
    rows = [r for r in store.gated(model, family).values() if not r["gate"].get("lint")]
    return len(rows), sum(row_passes(family, r) for r in rows)


def _wave_fn(family: str) -> Callable[..., dict]:
    fn = _hook(family, "refill_wave")
    if fn is None:
        raise SystemExit(f"refill: {FAMILY_MODULES[family]}.refill_wave is not implemented yet")
    return fn


def _refill_family(
    model: str, family: str, waves: int, claude_budget: int | None, gpu_minutes: float | None,
    pilot: bool, llm: str, runner: Any,
) -> str:  # fmt: skip
    pol = POLICY[family]
    entry = (store.read_report(model).get("families") or {}).get(family, {})
    hold = entry.get("refill_hold")
    prev = refill_block(entry) or {}
    target = pol.target
    tried, landed = prior_tally(model, family)
    tally0 = {"tried": tried, "landed": landed}
    wave_fn = _wave_fn(family)
    # budget: the Claude calls a wave reports (`claude_calls`, when the module counts them) and
    # gpu_minutes as a wall-clock cap on this family's waves; no global call counter is cheap
    start, calls, done = time.monotonic(), 0, 0
    exhausted, pool_size, pool_used = False, prev.get("pool_size"), prev.get("pool_used")
    status, why = None, ""
    levels_hook = _hook(family, "untried_levels")
    untried: list[str] = []
    while True:
        have = have_of(model, family)
        # a harder level of the family's construction with candidates never gated: no ooc yet
        # (GLM-5.3 multihop_mt_v2, 2026-11-04: the 2-hop pilot failed on shortcuts, i.e. the
        # subject was too capable for the easiest level, and the 3-hop pool was never tried)
        untried = list(levels_hook(model)) if levels_hook is not None else []
        n_min = float("inf") if untried else pol.n_min
        budget: bool | str = False
        if claude_budget is not None and calls >= claude_budget:
            budget = f"claude_budget {claude_budget}"
        elif gpu_minutes is not None and (time.monotonic() - start) / 60 >= gpu_minutes:
            budget = f"gpu_minutes {gpu_minutes:g} (wall clock)"
        status, why = stop_status(have, target, tried, landed, n_min, pol.y_min, exhausted,
                                  budget, hold=hold)  # fmt: skip
        if status is not None:
            break
        if pilot and tried >= pol.n_min:
            status, why = "partial", "pilot: not ooc (run the full refill)"
            break
        if done >= waves:
            status, why = "partial", f"max waves ({waves})"
            break
        res = wave_fn(model, wave=int(prev.get("waves") or 0) + done, runner=runner, llm=llm)
        done += 1
        tried += int(res.get("tried", 0))
        landed += int(res.get("landed", 0))
        calls += int(res.get("claude_calls", 0))
        exhausted = bool(res.get("exhausted"))
        pool_size = res.get("pool_size", pool_size)
        pool_used = res.get("pool_used", pool_used)
        print(f"  refill {family} wave {done}: tried {tried} landed {landed} have {have}")
    block = {
        "route": f"{FAMILY_MODULES[family]}.refill_wave", "unit": pol.unit, "target": target,
        "have": have, "tried": tried, "landed": landed,
        "yield": landed / tried if tried else None, "waves": int(prev.get("waves") or 0) + done,
        "n_min": pol.n_min, "y_min": pol.y_min,
        "tally": {pol.easiest: {"tried": tried, "landed": landed, "prior": tally0}},
        "pool_size": pool_size, "pool_used": pool_used, "stop": why,
        "budget": {"claude_budget": claude_budget, "gpu_minutes": gpu_minutes,
                   "claude_calls": calls},
        "pilot": pilot,
        "untried_levels": untried,
    }  # fmt: skip
    write_block(model, family, block, status)
    return status


def refill(
    model: str,
    families: list[str],
    waves: int = 8,
    claude_budget: int | None = None,
    gpu_minutes: float | None = None,
    pilot: bool = False,
    llm: str = "claude-opus-5-5",
    runner: Any = None,
) -> dict[str, str]:
    """``adapt refill``: each family through its route until ``stop_status`` stops it; writes
    ``report.json`` ``families.<f>.refill`` and ``status``. Returns {family: status}.
    ``claude_budget`` counts every Claude ask a wave reports (``claude_calls``), cache hits
    included, so on a resumed run it overstates spend and stops early: deliberately conservative
    (Camila 2026-11-04). buggy_code (``run.fill``) gets both budgets: ``claude_budget`` against
    its authoring + grading calls, ``gpu_minutes`` as its wall clock."""
    from . import run

    if bad := [f for f in families if f not in POLICY]:
        raise SystemExit(f"refill: no refill route for {bad}; known: {sorted(POLICY)}")
    out = {}
    for family in families:
        if family == BUGGY:
            budget_s = None if gpu_minutes is None else gpu_minutes * 60
            out[family] = run.fill(model, family, llm, waves, runner=runner, pilot=pilot,
                                   budget_s=budget_s, claude_budget=claude_budget)  # fmt: skip
        else:
            out[family] = _refill_family(model, family, waves, claude_budget, gpu_minutes, pilot,
                                         llm, runner)  # fmt: skip
        print(family, out[family])
    return out


def guard_problem(family: str, entry: dict, n: int, target: int) -> str | None:
    """The strict freeze guard (§1.3 + §11.6): a POLICY family short of target with no refill block
    (or only a pilot that did not stop it as ooc); a fill / auto family left ``untried``."""
    if n >= target:
        return None
    if family in POLICY:
        block = refill_block(entry)
        if block is None:
            return f"{n}/{target} {POLICY[family].unit} and never refilled (no refill block)"
        if block.get("pilot") and entry.get("status") != "ooc":
            return f"{n}/{target} {POLICY[family].unit}; only a pilot ran and it was not ooc"
        return None
    if family in UNTRIED_GUARDED and entry.get("status") == "untried":
        return f"{n}/{target} items and untried (no refill attempted)"
    return None
