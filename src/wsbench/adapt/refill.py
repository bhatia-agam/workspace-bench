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
MH2 = "multihop"

# the adapt module that owns each family's stages and optional hooks (row_passes, select_refill,
# refill_wave, prior_tally, build_pool); buggy_code goes through run.fill
FAMILY_MODULES = {MSDM: "msdm", KCUTOFF: "kcutoff", WI: "wrong_intermediate", MH2: "mhmt2"}
MH2_ROUTE = f"{FAMILY_MODULES[MH2]}.refill_wave"


def _registered_size(family: str) -> int:
    return len(store.original_bank(family)[1])


# Plan 0075 §0 (2026-11-06): adapted targets above the registered size. The target is
# max(registered, this), so no target is ever lowered; buggy_code keeps plan 0072 D1's target
# bank (24 pairs) and is never read from here.
ADAPTED_TARGETS: dict[str, int] = {
    "association": 100,
    "basic_readout": 120,
    "typo": 100,
    "multihop_st": 100,
    "poetry": 100,
    "multilingual": 100,
    "multilingual_typo": 100,
    "multilingual_multihop": 100,
    "relational_multihop": 100,
    "role_bound_association": 100,
}


# the sets plan 0075 retargets; every other set keeps its registered-size target. Plan 0089
# rebuilds Agam's five sets to the same standard, so they take the same targets and guards; a set
# built fresh after 0075 is built to its rules from the start (deepseek-v4-flash, 2026-11-15)
PLAN_0075_SETS = frozenset({
    "glm-5.3", "deepseek-v4-pro", "muse-spark-open", "kimi-k3", "qwen3-8b", "qwen3.5-9b",
    "qwen3.5-4b", "qwen3.5-2b", "qwen3.5-0.8b", "olmo-3-7b",
    "gemma-4-31b-it", "glm-5.3-flash", "kimi-k2", "olmo-3.1-32b", "qwen3.6-35b-a3b",
    "deepseek-v4-flash", "dory-4b",
})  # fmt: skip


# plan 0078: a model-specific family whose adapted target is set below its registered size
# (model_multihop: 100 per set, the caller's brief; freeze still ships every passing item up to
# ``SHIP_CAP``); every other family keeps the "never lowered" rule above
TARGET_OVERRIDE: dict[str, int] = {"model_multihop": 100}
SHIP_CAP: dict[str, int] = {"model_multihop": 283}  # the registered bank's size


def adapted_target(
    family: str, originals: list[dict] | None = None, model: str | None = None
) -> int:
    """The adapted item target of ``family``: ``max(len(originals), ADAPTED_TARGETS[family])``
    on a plan-0075 set (``PLAN_0075_SETS``); the registered bank's size elsewhere;
    ``TARGET_OVERRIDE`` first (plan 0078)."""
    if family in TARGET_OVERRIDE:
        return TARGET_OVERRIDE[family]
    n = len(originals) if originals is not None else _registered_size(family)
    if model is not None and model not in PLAN_0075_SETS:
        return n
    return max(n, ADAPTED_TARGETS.get(family, 0))


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
    """The registered twin-pair count (64 at bank v2; 24 on items.json): the pool the originals
    come from, NOT the adapted target (``target_bank``)."""
    return pair_count(store.original_bank(BUGGY)[1])


# Plan 0072 §0 D1 (Camila 2026-11-04, reaffirmed 2026-11-05): an adapted set's buggy_code target
# stays bank v1's (items.json, frozen: 24 pairs, 63 items, its `src` quota). #325's bank v2 (64
# pairs) is a larger pool of originals, not a new target; the originals are still the registered
# bank's items (``store.original_bank``), selected originals first up to this cap.
BUGGY_TARGET_FILE = "items.json"  # of the registered buggy_code directory


def target_bank() -> list[dict]:
    """The items of buggy_code's target bank (``BUGGY_TARGET_FILE``): the pair target, the item
    cap and the ``src`` quota of every adapted freeze / refill are read off it."""
    from wsbench.registry import resource_path

    raw = json.loads(resource_path(BUGGY, BUGGY_TARGET_FILE).read_text(encoding="utf-8"))
    return list(raw["items"] if isinstance(raw, dict) else raw)


def target_pairs() -> int:
    """buggy_code's adapted target in pairs (24)."""
    return pair_count(target_bank())


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
    BUGGY: Policy("pairs", target_pairs, 60, 0.03, ("author: brief tiers t1, t2",), "t2"),
    MSDM: Policy("categories", lambda: _registered_size(MSDM), 200, 0.03,
                 ("bank", "retired_panel_gate", "pool: msdm_pool.jsonl"), "ext pool"),
    KCUTOFF: Policy("items", lambda: _registered_size(KCUTOFF), 1000, 0.01,
                    ("bank", "retired_panel_gate", "pool: kcutoff_pool.jsonl"), "ext pool"),
    WI: Policy("items", lambda: _registered_size(WI), 200_000, 5e-5,
               ("source 0: unmapped templates", "re-scrape"), "expanded scrape"),
    MH2: Policy("items", lambda: _registered_size(MH2), 300, 0.03,
                ("bank", "pool: mh2_pool.json"), "2-hop pool"),
}  # fmt: skip

# Plan 0075 §2.2: the authored (``run.fill``) and generated (``run.auto``) families `adapt refill`
# drives, with run.fill / run.auto's own stop thresholds (OOC_MIN 60 candidates, OOC_YIELD 3%
# at the easiest tier); their target is ``adapted_target``.
FILL_POLICY: dict[str, str] = {
    "association": "run.fill",
    "basic_readout": "run.fill",
    "typo": "run.fill",
    "multihop_st": "run.fill",
    "poetry": "run.fill",
    "role_bound_association": "run.fill",
    "user_modeling": "run.fill",
    "multilingual": "run.fill",
    "multilingual_typo": "run.fill",
    "multilingual_multihop": "run.fill",
    "relational_multihop": "run.auto",
    "conjunctive_association": "run.fill",  # plan 0077 §6 (plan 0075 §2.9's Phase B)
}

FILL_ROUTES = frozenset(FILL_POLICY.values())
# run.NOTE_REFILL_FAMILIES (plan 0072 D6): their hand `note refill=` blocks keep counting
HAND_REFILL_FAMILIES = frozenset({"user_modeling", "multihop_st"})

# the fill / auto families the strict freeze guard covers by their `untried` status (§1.3)
UNTRIED_GUARDED = frozenset({
    "typo", "association", "basic_readout_st", "basic_readout",
    "arithmetic_intermediates", "relational_multihop", "chain_intermediates",
})  # fmt: skip
# plan 0075: the families it gave a refill route, guarded on its ten sets only
UNTRIED_GUARDED_0075 = frozenset({
    "multihop_st", "poetry", "role_bound_association", "user_modeling",
    "multilingual", "multilingual_typo", "multilingual_multihop",
    "conjunctive_association",  # plan 0077 §6
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
    "kcutoffv2": "kcutoff_pool.v2.jsonl",  # plan 0077 §2: v1 + the b3..b5 batches
    "mh2v3": "mh2_pool.v3.json",  # plan 0077 §4: v2 + the v3 generator runs
    "mmh": "mmh_pool.json",  # plan 0078: gw mmh v2 candidates (scripts/build_mmh_pool.py)
}
# pinned once built on the box by scripts/build_adapt_pools.py (plan 0066 §8 step 1, 2026-11-04;
# the builds are deterministic, two builds gave the same bytes); None = not built yet
POOL_SHA256: dict[str, str | None] = {
    "msdm": "b1936e2efc4ac61230f69ab4d70da622ba1da83e7348ed25d24c795e6af3b073",
    "kcutoff": "0597d19caace1866a860dffb697a024e4ee12ab5245090591f54c6ba9ff3e614",
    "mh2": "553df6a6de636ddad043b63bcb21b7e38cc35cb2a89a13f7749e6910d2b29926",
    # decision 7 (built 2026-11-04 for GLM-5.3: + the GW adversary over the S1-only candidates)
    "mh2v2": "7e3e4d16da32ddef44a9d452474a4ddb12cf1be104ec6c8161bfebc9bf394629",
    # plan 0077 (funded pools), pinned once built on the box
    "kcutoffv2": "6b0dd01656637a4e3664d42f13c1c1fc66d8837576f9691fb444e0a2fd478e93",
    "mh2v3": "dfd973d3bfd57b07d19f00228bb1f397c59f3d836f02fb76f14b78cea4c2a3d6",
    # plan 0078 (built 2026-11-06 from gw frozen_v2 2027ef208 + /root/tmp/mmh-out cands files)
    "mmh": "2adc5f0c724c51add14a4a7cc8a8c8cd30ada4a19ec027b8b040d103571443f8",
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


def newest_pool(names: tuple[str, ...], base: str) -> str:
    """The newest of ``names`` (newest first) that is pinned AND whose file is in the pool dir;
    ``base`` otherwise (its own loader still refuses a missing / mismatched file). A pinned newer
    generation whose file is absent is skipped with a printed note (plan 0077: a funded pool is
    used once it is on the box)."""
    for name in names:
        if name == base:
            break
        if name in POOL_FILES and POOL_SHA256.get(name):
            path = pool_dir() / POOL_FILES[name]
            if path.is_file():
                return name
            if str(path) not in _ABSENT_NOTED:  # once per path, not per call
                _ABSENT_NOTED.add(str(path))
                print(f"refill: pool {name!r} is pinned but {path} is absent; reading {base!r}")
    return base


_ABSENT_NOTED: set[str] = set()


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


# plan 0075: fill families whose module adds a ``row_passes`` hook (a new row is complete only
# once its post-gate stage built the judge-side fields)
ROW_HOOK_MODULES = {
    "poetry": "poetry", "role_bound_association": "rbstage", "multihop_st": "mhstage",
}  # fmt: skip


def _module(family: str):
    name = FAMILY_MODULES.get(family) or ROW_HOOK_MODULES.get(family)
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
    if hook is None:
        return True
    if family in ROW_HOOK_MODULES and not is_0075(row):
        return True  # rows authored before plan 0075 (other sets' frozen banks) keep shipping
    return bool(hook(row))


def is_0075(row: dict) -> bool:
    """A row authored under plan 0075's refill rules (``adapt.plan``, stamped by
    ``author._finish``); only these get the new families' ``row_passes`` hooks."""
    return ((row.get("item") or {}).get("adapt") or {}).get("plan") == "0075"


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


def freeze_rows(family: str, rows: list[dict], model: str | None = None) -> list[dict]:
    """What freeze and the refill select from: ``row_passes`` applied, then the select hook.
    With ``model`` (freeze, ``fill``, ``have_of``), plan 0075 / #372: a capital-family authored row
    the set does not already ship that fails the capital rule is out, BEFORE selection, so the
    refill's count and freeze's agree and a passing row backfills it."""
    rows = _with_passes(family, rows)
    if model is not None and model in PLAN_0075_SETS:  # other sets re-freeze as before
        from .lint import CAPITAL_FAMILIES, _capital

        if family in CAPITAL_FAMILIES:
            from .run import shipped_ids

            before = shipped_ids(model, family)
            rows = [
                {**r, "gate": {**r["gate"], "pass": False}, "selected": False}
                if r["origin"] != "original" and r["id"] not in before and r["gate"].get("pass")
                and _capital(family, {**r["item"], "adapt": {"origin": "authored"}})
                else r
                for r in rows
            ]  # fmt: skip
    return apply_select_hook(family, rows)


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
    rows: list[dict], originals_target: int, quota: dict[str, int] | None = None
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
    head = f"refill via {block.get('route', '?')}"
    if block.get("have") is not None or block.get("target") is not None:
        head += f": {block.get('have')}/{block.get('target')} {block.get('unit', 'items')}"
    parts = [head]
    if block.get("tried") is not None:
        y = block.get("yield")
        ys = f", yield {y:.2%}" if isinstance(y, int | float) else ""
        # T1 (#289): multihop tallies its easiest level only (2-hop, §1.2) while 3-hop items
        # ship too, so `landed` is below the shipped count by design; the line says so
        lvl = " at the easiest level only" if block.get("route") == MH2_ROUTE else ""
        parts.append(f"{block.get('landed')} landed of {block['tried']} tried{lvl}{ys}")
    if block.get("pool_size") is not None:
        parts.append(f"pool {block.get('pool_used')}/{block['pool_size']} used")
    parts.append(f"stop: {block.get('stop')}")
    return "; ".join(parts)


NOTE_MARK = "refill_note_sha"  # the hand note as it stood before the last refill that gated any
# note segments (" | "-joined) code writes: kcutoff's shipped mix and mhmt2's mc tally (rewritten
# inside their waves) and freeze's allow_untried stamp. They are never the "hand note".
ROUTE_NOTE_PREFIXES = ("refill mix:", "mc over gate:", "freeze guard overridden")


def hand_note(entry: dict) -> str:
    """The family's ``note`` without the segments code writes (``ROUTE_NOTE_PREFIXES``)."""
    segs = (s for s in str(entry.get("note") or "").split(" | ") if s.strip())
    return " | ".join(s for s in segs if not s.startswith(ROUTE_NOTE_PREFIXES))


def note_sha(entry: dict) -> str:
    return hashlib.sha256(hand_note(entry).encode()).hexdigest()[:16]


def stale_note(entry: dict) -> bool:
    """True when the family's hand note (``hand_note``) is byte-identical to the one that stood
    BEFORE its last refill that gated candidates (``write_block(note_before=)``): the refill is
    newer than the note, which may describe the pre-refill family (R1, #289). Never flagged: an
    entry without the mark (older blocks), a note only the refill route wrote, a note rewritten
    since (a later no-op resume does not move the mark)."""
    mark = entry.get(NOTE_MARK)
    return bool(mark and entry.get("refill") and hand_note(entry) and mark == note_sha(entry))


def write_block(
    model: str, family: str, block: dict, status: str, note_before: str | None = None
) -> None:
    """Write the family's refill block and status. ``note_before``: ``note_sha`` of the entry as
    it stood before this call's waves, given ONLY when the call gated candidates; it becomes
    the entry's ``NOTE_MARK``. A call that gated none leaves the mark as it is."""

    def _set(report: dict) -> None:
        entry = store.report_slot(report, "families", family)
        entry["refill"] = block
        entry["status"] = status
        if note_before is not None:
            entry[NOTE_MARK] = note_before

    store.update_report(model, _set)


# ---------------------------------------------------------------------------- driver
def have_of(model: str, family: str) -> int:
    """``have`` in the family's unit, through the same selection freeze uses."""
    from . import run

    _h, originals = store.original_bank(family)
    rows = freeze_rows(family, run._bank_rows(model, family, originals), model)
    quota = run.quotas(family, originals)
    if family == BUGGY:  # plan 0072 §0 D1: the target bank's cap and quota, as freeze
        tb = target_bank()
        return selected_pairs(buggy_selection(rows, len(tb), run.quotas(family, tb)))
    return len(run.select(family, rows, adapted_target(family, originals, model), quota))


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


def _pool_state(family: str, model: str) -> tuple[int, str] | None:
    """``(size, identity)`` of the pool the family's waves read now (the module's optional
    ``pool_state(model)`` hook: size as its waves report ``pool_size``, identity = the pool's
    name and pinned sha), or None (no hook, or no readable pool)."""
    hook = _hook(family, "pool_state")
    if hook is None:
        return None
    try:
        size, ident = hook(model)
    except SystemExit:  # unpinned / missing pool file: its loader refuses
        return None
    return int(size), str(ident)


def _refill_family(
    model: str, family: str, waves: int, claude_budget: int | None, gpu_minutes: float | None,
    pilot: bool, llm: str, runner: Any,
) -> str:  # fmt: skip
    pol = POLICY[family]
    entry = store.report_entry(store.read_report(model).get("families"), family)
    hold = entry.get("refill_hold")
    note0 = note_sha(entry)  # before any wave: kcutoff / mhmt2 waves rewrite their note segment
    prev = refill_block(entry) or {}
    target = pol.target
    tried, landed = prior_tally(model, family)
    tally0 = {"tried": tried, "landed": landed}
    wave_fn = _wave_fn(family)
    # budget: the Claude calls a wave reports (`claude_calls`, when the module counts them) and
    # gpu_minutes as a wall-clock cap on this family's waves; no global call counter is cheap
    start, calls, done = time.monotonic(), 0, 0
    exhausted, pool_size, pool_used = False, prev.get("pool_size"), prev.get("pool_used")
    # S1 (#289): the previous block's pool state, used ONLY to label a stop this call makes
    # before its first wave (a resume would else relabel a "pool exhausted" stop "low yield above
    # half"); it never stops a call that would have run a wave. Trusted only for the SAME pool:
    # the module's `pool_state` must report the size and identity the previous block recorded
    # (a swapped or extended pool, a block without `pool_id`, or a family with no such hook
    # keeps the label this call computes itself).
    pool_now = _pool_state(family, model)
    prev_exhausted = (
        pool_now is not None
        and isinstance(pool_size, int) and isinstance(pool_used, int)
        and (pool_size, prev.get("pool_id")) == pool_now
        and pool_used >= pool_size
    )  # fmt: skip
    status, why = None, ""
    levels_hook = _hook(family, "untried_levels")
    gen_hook = _hook(family, "pool_generation")
    gen: dict | None = None
    gen_rules = False
    untried: list[str] = []
    while True:
        have = have_of(model, family)
        # a harder level of the family's construction with candidates never gated: no ooc yet
        # (GLM-5.3 multihop, 2026-11-04: the 2-hop pilot failed on shortcuts, i.e. the
        # subject was too capable for the easiest level, and the 3-hop pool was never tried)
        untried = list(levels_hook(model)) if levels_hook is not None else []
        n_min = float("inf") if untried else pol.n_min
        budget: bool | str = False
        if claude_budget is not None and calls >= claude_budget:
            budget = f"claude_budget {claude_budget}"
        elif gpu_minutes is not None and (time.monotonic() - start) / 60 >= gpu_minutes:
            budget = f"gpu_minutes {gpu_minutes:g} (wall clock)"
        # plan 0077 §1: while the newest funded pool generation has unseen candidates, the stop
        # rule reads that generation's own tally (never the older generations' stops)
        gen = gen_hook(model) if gen_hook is not None else None
        gen_rules = gen is not None and (gen["unseen"] > 0 or gen["tried"] >= pol.n_min)
        if gen_rules:
            # unseen candidates left, or measured on >= n_min of its own: the generation's yield
            # decides, with the wave's pool `exhausted` flag (a wave that cannot reach the
            # remaining unseen candidates still stops, never after empty waves to the wave cap)
            s_tried, s_landed, s_exhausted = gen["tried"], gen["landed"], exhausted
        else:  # no generation, or one smaller than n_min and exhausted: the combined tally
            s_tried, s_landed, s_exhausted = tried, landed, exhausted
        status, why = stop_status(have, target, s_tried, s_landed, n_min, pol.y_min,
                                  s_exhausted, budget, hold=hold)  # fmt: skip
        if (status == "partial" and done == 0 and prev_exhausted
                and not (gen is not None and gen["unseen"] > 0)):  # fmt: skip
            # same arguments with the pool known exhausted: full / ooc / held-ooc precede that
            # condition in stop_status, so only a partial's reason can change
            status, why = stop_status(have, target, s_tried, s_landed, n_min, pol.y_min,
                                      True, budget, hold=hold)  # fmt: skip
        if status in ("ooc", "partial") and gen_rules and ("yield" in why or "exhausted" in why):
            why = f"{why} (pool generation {gen['name']})"  # only when its tally stopped it
        if status is not None:
            break
        if pilot and (s_tried if gen_rules else tried) >= pol.n_min:
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
        "tally": {pol.easiest: {"tried": tried, "landed": landed, "prior": tally0},
                  **({gen["name"]: {k: gen[k] for k in ("tried", "landed", "size", "unseen")}}
                     if gen is not None else {})},
        "pool_size": pool_size, "pool_used": pool_used, "stop": why,
        "budget": {"claude_budget": claude_budget, "gpu_minutes": gpu_minutes,
                   "claude_calls": calls},
        "pilot": pilot,
        "untried_levels": untried,
    }  # fmt: skip
    # the pool that `pool_size` / `pool_used` describe, when the module can name it: this call's
    # waves read the pool as it is now; a call that ran none carries the previous block's
    # numbers, so it keeps that block's identity only while the pool is still that one
    now = _pool_state(family, model)
    if now is not None and now[0] == pool_size and (done or now[1] == prev.get("pool_id")):
        block["pool_id"] = now[1]
    # the mark moves only when this call gated candidates (a resume whose wave finds the pool
    # used up tried nothing, so a note written since the real refill is not flagged)
    ran = tried > tally0["tried"]
    write_block(model, family, block, status, note_before=note0 if ran else None)
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

    known = set(POLICY) | set(FILL_POLICY)
    if bad := [f for f in families if f not in known]:
        raise SystemExit(f"refill: no refill route for {bad}; known: {sorted(known)}")
    out = {}
    for family in families:
        if family in FILL_POLICY:  # plan 0075 §2.2
            if pilot or claude_budget is not None or gpu_minutes is not None:
                raise SystemExit(
                    f"refill: pilot / claude_budget / gpu_minutes are for the POLICY families, "
                    f"not {family} (plan 0075 §3: one family per call, the ledger is the cap)"
                )
            if FILL_POLICY[family] == "run.auto":
                from .generate import GENERATORS

                # run.auto's max_waves is per tier: `waves` bounds the whole ladder (the budget)
                per_tier = max(1, -(-waves // len(GENERATORS[family].tiers)))
                out[family] = run.auto(model, family, runner=runner, max_waves=per_tier)
            else:
                out[family] = run.fill(model, family, llm, waves, runner=runner)
        elif family == BUGGY:
            budget_s = None if gpu_minutes is None else gpu_minutes * 60
            out[family] = run.fill(model, family, llm, waves, runner=runner, pilot=pilot,
                                   budget_s=budget_s, claude_budget=claude_budget)  # fmt: skip
        else:
            out[family] = _refill_family(model, family, waves, claude_budget, gpu_minutes, pilot,
                                         llm, runner)  # fmt: skip
        print(family, out[family])
    return out


def guard_problem(
    family: str, entry: dict, n: int, target: int, model: str | None = None
) -> str | None:
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
    # plan 0075's rules apply to its ten sets (a set elsewhere re-freezes exactly as before)
    plan_0075 = model is None or model in PLAN_0075_SETS
    guarded = UNTRIED_GUARDED | (UNTRIED_GUARDED_0075 if plan_0075 else frozenset())
    if family in guarded and entry.get("status") == "untried":
        return f"{n}/{target} items and untried (no refill attempted)"
    if plan_0075 and family in FILL_POLICY and entry.get("status") not in ("ooc", "blocked"):
        # plan 0075 §2.1: a family short of its (raised) adapted target ships only after a
        # refill measured AT that target; authored rows from an earlier, lower target make it
        # `partial`, not `untried`, so the untried rule alone would let it through
        block = refill_block(entry) or {}
        route = block.get("route")
        if family in HAND_REFILL_FAMILIES and route and route not in FILL_ROUTES:
            return None  # plan 0072 D6 retained: a `note refill=` block (no driver then) counts
        if block.get("target") != target:
            return (
                f"{n}/{target} items and no refill at the current target {target} "
                f"(last refill target: {block.get('target')})"
            )
        if route in FILL_ROUTES and not block.get("tried_total", block.get("tried")):
            return f"{n}/{target} items and the last refill gated no candidate (tried 0)"
    return None
