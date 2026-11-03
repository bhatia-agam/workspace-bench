"""Family registry: each ``wsbench.evals.<family>`` package registers one ``EvalSpec`` on import."""

import copy
import functools
import importlib
import json
import os
import pkgutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wsbench.judge_config import JudgeConfig, ResolvedJudge
from wsbench.results import FamilyResult

# src layout (uv-managed checkout); a wheel install would resolve to site-packages.
REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILIES: dict[str, "EvalSpec"] = {}  # filled by register(); EvalSpec is defined below
BANK_ROOT_ENV = "WSB_BANK_ROOT"  # a per-model bank directory, e.g. adapted/qwen3.5-4b
BANK_FILE_ENV_PREFIX = "WSB_BANK_FILE_"  # + FAMILY upper-cased: one family's bank file

# Former family keys -> current keys (pure renames; the instrument, bank and prompt_version did
# not change). Old names keep working on the command line, as readout file names, in stored
# results.json files and as keys of evals/baselines/anti_text_inversion.json.
LEGACY_FAMILY_NAMES: dict[str, str] = {
    "introspection_inject": "introspection",
    "cutoff_confab": "knowledge_cutoff",
    # canonical() is single-step, so both former keys point straight at the current one
    "dm_category_default": "model_specific_directed_modulation",
    "directed_modulation_obscure": "model_specific_directed_modulation",  # plan 0034 O1
}


# Families deleted from the bench -> why (never registered again; plan 0017). Old run dirs may
# still hold their results.json, so results.macro excludes them (reason "removed"); a removed
# family's former keys are listed too.
REMOVED_FAMILIES: dict[str, str] = {
    "ttt": "removed 2026-10-26 (#97): too close to next-token prediction",
    "ttt_move": "removed 2026-10-26 (#97): too close to next-token prediction",
    "brew_intermediates": "removed 2026-10-29 (plan 0029): the prompt alone solves it",
    "wrong_bridge_true": (
        "removed 2026-10-30 (Camila, plan 0050): not part of the benchmark; wrong_bridge "
        "reports the true-bridge pick as true_bridge_rate"
    ),
    "hallucination": "removed 2026-10-30 (plan 0040): replaced by HallucinationBench "
    "(github.com/camila-blank/hallucination-bench); its index is reported in WSB "
    "(README §HallucinationBench)",
    "multihop_mt": "removed 2026-10-30: superseded by multihop_mt_v2 (Camila)",
    "medical_diagnosis": "removed 2026-10-31 (Camila, plan 0058): taken out of the benchmark",
    "medical_diagnosis_alt": "removed 2026-10-31 (Camila, plan 0058): taken out of the "
    "benchmark with medical_diagnosis",
}

# Families retired from the bench FOR NOW -> why (plan 0058; reversible, unlike REMOVED_FAMILIES).
# The package, bank, tests and floors stay and the family is still registered and runnable by
# name (`families=<name>`), but it is left out of every `all` default (``drop_superseded``), the
# macro (reason "retired"), the README family list and the ATI file. Restoring one = deleting its
# entry here and re-adding its README entry, Judges row and ATI ``NOT_GATED`` line (plan 0058).
RETIRED_FAMILIES: dict[str, str] = {
    "unverbalized_hint": "retired (Camila 2026-10-31, for now)",
}


def canonical(name: str) -> str:
    """The current key of ``name``: a former key maps to its new one, any other name is kept."""
    return LEGACY_FAMILY_NAMES.get(name, name)


def legacy_names(name: str) -> list[str]:
    """The former keys of the current family ``name`` (empty for a family never renamed)."""
    return [old for old, new in LEGACY_FAMILY_NAMES.items() if new == name]


def bank_path(family: str) -> Path:
    """The bank a family judges (plan 0032 §2.12): ``$WSB_BANK_FILE_<FAMILY>`` (one family's
    whole bank file, read at call time) > ``$WSB_BANK_ROOT/<family>.json`` (an adapted bank; a
    family missing there is an error, never a silent fall-back to the frozen bank of another
    model) > ``REPO_ROOT / EvalSpec.bank`` (the registered file: ``items.json``, or a versioned
    ``items_v<N>.json`` once the family switches). There is no ``items.json`` literal fallback."""
    one = os.environ.get(BANK_FILE_ENV_PREFIX + family.upper())
    if one:  # one family's whole bank file (ATI refill candidates, pinned test fixtures)
        path = Path(one) if Path(one).is_absolute() else REPO_ROOT / one
        if not path.is_file():
            raise SystemExit(f"{BANK_FILE_ENV_PREFIX}{family.upper()}={one}: no such bank file")
        return path
    root = os.environ.get(BANK_ROOT_ENV)
    if root:
        base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
        path = base / f"{family}.json"
        if not path.exists():
            raise SystemExit(f"{BANK_ROOT_ENV}={root} has no bank for {family!r} ({path})")
        return path
    return REPO_ROOT / _spec_for_bank(family).bank


def frozen_bank_path(family: str) -> Path:
    """The family's registered bank of record (``REPO_ROOT / EvalSpec.bank``), ignoring the
    ``WSB_BANK_*`` overrides: what the adapt / viewer / lucky-guessing tools treat as the frozen
    27B bank (a versioned ``items_v<N>.json`` once the family switches, plan 0032 §2.12)."""
    return REPO_ROOT / _spec_for_bank(family).bank


def bank_root() -> Path | None:
    """``$WSB_BANK_ROOT`` as a path (relative = under REPO_ROOT), or None for the registered
    bank."""
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return None
    return Path(root) if Path(root).is_absolute() else REPO_ROOT / root


def resource_path(family: str, name: str) -> Path:
    """A judge resource of the REGISTERED instrument: ``REPO_ROOT/evals/<family>/<name>``."""
    return REPO_ROOT / "evals" / family / name


def overlay_path(family: str, name: str) -> Path | None:
    """The per-set overlay of a judge resource (plan 0060 A2): ``$WSB_BANK_ROOT/<family>/<name>``
    when ``WSB_BANK_ROOT`` is set and that file exists, else None (never under the registered
    bank)."""
    root = bank_root()
    return None if root is None else _overlay_at(str(root), family, name)


@functools.cache
def _overlay_at(root: str, family: str, name: str) -> Path | None:
    """One existence check per (set dir, family, file): judges look resources up per item, and
    a set dir is written before it is judged."""
    path = Path(root) / family / name
    return path if path.is_file() else None


def merge_overlay(
    base: Any, over: Any, keys: Iterable[str], *, where: str = "overlay"
) -> tuple[Any, frozenset[str]]:
    """``(merged, added)``: ``base`` (never mutated) with the overlay's entries ADDED under each
    dotted path of ``keys`` (``"subjects"``, ``"groups.pair"``): a key absent from the
    registered map is added; a key the registered map has must carry the identical value, else
    SystemExit (an overlay never shadows a registered entry). A list at a path (``passive``)
    merges as a set of members. ``added`` = every added entry as ``"<path>/<key>"``. Every other
    overlay field (``version``, ``note``) is ignored."""
    out = copy.deepcopy(base)
    added: set[str] = set()
    for path in keys:
        parts = path.split(".")
        src: Any = over
        for p in parts:
            src = src.get(p) if isinstance(src, Mapping) else None
        if src is None:
            continue
        dst = out
        for p in parts[:-1]:
            dst = dst.setdefault(p, {})
            if not isinstance(dst, dict):
                raise SystemExit(f"{where}: {path} shape differs from the registered file")
        reg = dst.get(parts[-1])
        if not isinstance(src, (list, Mapping)):
            raise SystemExit(f"{where}: {path!r} must be a map or a list")
        if reg is not None and isinstance(reg, list) != isinstance(src, list):
            raise SystemExit(f"{where}: {path} shape differs from the registered file")
        if reg is not None and not isinstance(reg, (list, Mapping)):
            raise SystemExit(f"{where}: {path} shape differs from the registered file")
        if isinstance(src, list):
            have_l = list(dst.get(parts[-1]) or [])
            new = [x for x in src if x not in have_l]
            dst[parts[-1]] = have_l + new
            added |= {f"{path}/{x}" for x in new}
            continue
        have = dst.setdefault(parts[-1], {})
        for k, v in src.items():
            if k in have:
                if have[k] != v:
                    raise SystemExit(
                        f"{where}: {path}/{k} differs from the registered entry (an overlay "
                        "only adds entries; registered keys resolve to registered entries)"
                    )
                continue
            have[k] = v
            added.add(f"{path}/{k}")
    return out, frozenset(added)


_RESOURCE_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[Any, frozenset[str]]] = {}


def load_resource(
    family: str, name: str, keys: Iterable[str], *, registered: Path | None = None
) -> tuple[Any, frozenset[str]]:
    """``(data, added)``: the registered resource (``registered``, default
    :func:`resource_path`; a missing file reads as ``{}``) with the per-set overlay
    (:func:`overlay_path`) merged on it by :func:`merge_overlay`. With no ``WSB_BANK_ROOT`` or no
    overlay file: exactly the registered file, ``added`` empty. Cached per (registered file,
    overlay file); the caller must not mutate the result."""
    reg = registered if registered is not None else resource_path(family, name)
    over = overlay_path(family, name)
    ks = tuple(keys)
    key = (str(reg), str(over or ""), ks)
    if key not in _RESOURCE_CACHE:
        base = json.loads(reg.read_text(encoding="utf-8")) if reg.is_file() else {}
        if over is None:
            _RESOURCE_CACHE[key] = (base, frozenset())
        else:
            data = json.loads(over.read_text(encoding="utf-8"))
            _RESOURCE_CACHE[key] = merge_overlay(base, data, ks, where=str(over))
    return _RESOURCE_CACHE[key]


def registered_ids(family: str) -> frozenset[str]:
    """Ids of the family's REGISTERED bank (:func:`frozen_bank_path`, never the ``WSB_BANK_*``
    overrides): ``label_of(name)`` for name-keyed items, else ``id``. What decides "registered"
    vs "adapted-only" for every per-set overlay lookup."""
    return _registered_ids(_frozen_bank_str(family))


@functools.cache
def _frozen_bank_str(family: str) -> str:
    """:func:`frozen_bank_path` once per family (it may list the evals package on each call when
    the registry was emptied, and the per-item overlay checks call it per item)."""
    return str(frozen_bank_path(family))


@functools.cache
def _registered_ids(path: str) -> frozenset[str]:
    from wsbench.banks import label_of

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("items", [])
    out = set()
    for it in items:
        if it.get("name"):
            out.add(label_of(str(it["name"])))
        elif it.get("id"):
            out.add(str(it["id"]))
    return frozenset(out)


def registered_values(family: str, field_name: str) -> frozenset[str]:
    """Every value of item field ``field_name`` in the family's REGISTERED bank (e.g.
    role_bound's ``pair_id``)."""
    return _registered_values(_frozen_bank_str(family), field_name)


@functools.cache
def _registered_values(path: str, field_name: str) -> frozenset[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("items", [])
    return frozenset(str(it[field_name]) for it in items if it.get(field_name) is not None)


def adapted_only(family: str, item_id: str) -> bool:
    """An adapted bank is in use (``WSB_BANK_ROOT``) AND ``item_id`` is not in the family's
    registered bank: the case where a per-set entry is required and a missing one is a loud
    error. Always False for the registered bank."""
    return bank_root() is not None and str(item_id) not in registered_ids(family)


def _spec_for_bank(family: str) -> "EvalSpec":
    """The family's EvalSpec, also when the registry was emptied after import (the family
    package's ``SPEC``); an unknown family exits 2."""
    if family not in FAMILIES:
        load_all()
    if family in FAMILIES:
        return FAMILIES[family]
    try:
        spec = importlib.import_module(f"wsbench.evals.{family}").SPEC
    except (ImportError, AttributeError):
        raise SystemExit(f"no registered bank for family {family!r}") from None
    return spec  # type: ignore[no-any-return]


@dataclass
class JudgeArgs:
    """What ``cli.judge`` passes to every family. ``limit == 0`` means no limit."""

    readouts: Path
    out: Path
    judge: ResolvedJudge
    layers: list[int] | None
    items: list[str] | None
    limit: int
    allow_missing: bool
    concurrency: int
    rpm: float
    dry_run: bool
    aux_models: Mapping[str, str] = field(default_factory=dict)  # e.g. {"summarizer": model}
    extra: dict[str, str] = field(default_factory=dict)  # family options from opts=key=value
    scope: str = ""  # "anti_text_inversion": `items` is that frozen subset, not a partial run


@dataclass(frozen=True)
class EvalSpec:
    name: str  # family key, e.g. "moral_rationale"
    title: str  # README name, e.g. "Moral rationale"
    group: str  # "basic" | "basic_mt" | "safety" | "association" | "bag_of_words" | "precision"
    #            | "model_specific" | "computational"
    bank: Path  # the bank file, relative to REPO_ROOT (items.json; jlens_concept_pr: manifest.json)
    judge: JudgeConfig
    metric: str
    higher_is_better: bool
    run: Callable[[JudgeArgs], FamilyResult]  # returns a FamilyResult; writes nothing
    calls_per_arm: str = ""  # human string for `wsbench list`, e.g. "≈ 7k" (judge calls per arm)
    sources: str = ""  # credit substring that appears verbatim in README §Credits and NOTICE.md
    # a deterministic scorer of record ("regex"): `wsbench list` shows it as the judge and `run`
    # skips its preflight unless opts=judge=mc asks for the family's optional LLM judge
    scorer: str = ""
    # the family that replaces this one. A superseded family stays registered, frozen and
    # runnable by explicit name, but every "all" default skips it and the macro excludes it
    # (reason "superseded") — so its numbers never double-count beside its successor's.
    superseded_by: str = ""
    # why this family is kept out of the macro (e.g. "hillclimbing: not yet reviewed"); empty =
    # in the macro. It stays in `all` runs and reports, only the macro row skips it.
    not_in_macro: str = ""
    # a ``not_in_macro`` reason computed when the macro is assembled, not at import (it may read
    # the bank ``bank_path`` resolves under the live ``WSB_BANK_*`` overrides); "" = in the
    # macro. A non-empty static ``not_in_macro`` wins. See :func:`macro_reason`.
    macro_gate: Callable[[], str] | None = None
    # the family's item ids when they are not just its read plan's (knowledge_cutoff: the frozen
    # bank + the ids-only nocot items, whose plan rows need a network fetch). Feeds the ATI
    # construction entry and `wsbench list`; None = the readplan ids / the bank file's length.
    item_ids: Callable[[], list[str]] | None = None
    # plan 0032 §2.6.5: the reads=full span check (reads.check_full). A full read is ONE
    # contiguous run of >= min_full_positions positions ending at the item's max position per
    # (item, layer); full_contiguous=False (explicit-position rules) needs only the count.
    min_full_positions: int = 2
    full_contiguous: bool = True
    # plan 0032 §2.8.3: the summarizer's task context (no gold, no tool name); per-item notes
    # (a Mapping covering every item) when the family has several prompt kinds
    task_note: str = ""
    item_task_notes: Callable[[], Mapping[str, str]] | None = None
    # plan 0032 §2.7.2: option types that compete as a flat list (e.g. "numbers"); a run of them
    # singles out none (mc.token_note). multi_select: the judge may pick several options.
    flat_types: tuple[str, ...] = ()
    multi_select: bool = False
    # the judge holds TARGETS, not options (the basic bank families): mc.token_note(targets=True)
    # drops the lone-option clause (review of PR #140)
    targets_judge: bool = False


def register(spec: EvalSpec) -> EvalSpec:
    if spec.name in FAMILIES:
        raise ValueError(f"family {spec.name!r} is already registered")
    FAMILIES[spec.name] = spec
    return spec


def get(name: str) -> EvalSpec:
    try:
        return FAMILIES[name]
    except KeyError:
        known = ", ".join(sorted(FAMILIES)) or "(none)"
        raise KeyError(f"unknown family {name!r}; known families: {known}") from None


def load_all() -> None:
    """Import every ``wsbench.evals.<pkg>`` so FAMILIES is populated. Idempotent."""
    import wsbench.evals as evals_pkg

    for mod in pkgutil.iter_modules(evals_pkg.__path__):
        importlib.import_module(f"wsbench.evals.{mod.name}")


def superseded() -> dict[str, str]:
    """``{family: successor}`` for every superseded family (loads the registry)."""
    load_all()
    return {s.name: s.superseded_by for s in FAMILIES.values() if s.superseded_by}


def macro_reason(spec: EvalSpec) -> str:
    """Why ``spec`` is kept out of the macro now ("" = in it): its static ``not_in_macro``, else
    its ``macro_gate`` evaluated at call time."""
    if spec.not_in_macro or spec.macro_gate is None:
        return spec.not_in_macro
    return spec.macro_gate()


def not_in_macro() -> dict[str, str]:
    """``{family: reason}`` for every family kept out of the macro (loads the registry)."""
    load_all()
    reasons = {s.name: macro_reason(s) for s in FAMILIES.values()}
    return {name: why for name, why in reasons.items() if why}


def drop_superseded(names: Iterable[str]) -> list[str]:
    """``names`` minus the superseded and the retired (``RETIRED_FAMILIES``) families, order
    kept: what ``all`` means everywhere."""
    sup = superseded()
    return [n for n in names if n not in sup and n not in RETIRED_FAMILIES]
