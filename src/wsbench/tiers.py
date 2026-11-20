"""The three run tiers (plan 0098): ``fast`` (the frozen fast subset), ``core`` (the default,
``CORE``) and ``full`` (every family ``all`` runs)."""

from wsbench import fast, registry

TIERS = ("fast", "core", "full")
DEFAULT = "core"
CORE: tuple[str, ...] = (
    "agentic_misalignment",
    "jailbreak_recognition",
    "arithmetic_intermediates",
    "buggy_code",
    "nyt_connections",
    "moral_rationale",
    "poetry",
    "introspection",
    "multi_concept_directed_modulation",
    "wrong_intermediate",
    "relational_multihop",
    "role_bound_association",
    "knowledge_cutoff",
    "model_specific_directed_modulation",
    "model_multihop",
    "chain_intermediates",
    "hinted_cutoff",
)


def core() -> list[str]:
    """The registered ``CORE`` families, sorted by name (the order of ``all``)."""
    registry.load_all()
    return sorted(f for f in CORE if f in registry.FAMILIES)


def full() -> list[str]:
    """Every family ``all=True`` runs: the registry minus the superseded and retired ones."""
    registry.load_all()
    return registry.drop_superseded(sorted(registry.FAMILIES))


def families(tier: str) -> list[str]:
    if tier == "fast":
        return fast.families()
    if tier == "core":
        return core()
    if tier == "full":
        return full()
    raise ValueError(f"unknown tier {tier!r} (known: {', '.join(TIERS)})")


def tier_of(family: str) -> str:
    """``core`` for a core family that ``full`` runs, ``full`` for every other member of
    ``full()``, else ``""`` (superseded, retired, unknown)."""
    if family not in full():
        return ""
    return "core" if family in CORE else "full"


def check(*, static_only: bool = False) -> None:
    """The tier invariant: every ``CORE`` family is registered, not superseded, not retired, in
    ``full()``, and in the macro (``static_only``: its static ``not_in_macro`` alone, without the
    bank-reading ``macro_gate`` and the live registry)."""
    if len(set(CORE)) != len(CORE):
        raise ValueError("tiers.CORE repeats a family")
    for name in CORE:
        spec = registry._spec_for_bank(name)
        if spec.superseded_by:
            raise ValueError(f"core family {name!r} is superseded by {spec.superseded_by!r}")
        if spec.not_in_macro:
            raise ValueError(f"core family {name!r} is not in the macro: {spec.not_in_macro}")
    if static_only:
        return
    run, held_out = set(full()), registry.not_in_macro()
    for name in CORE:
        if name not in registry.FAMILIES or name in registry.RETIRED_FAMILIES or name not in run:
            raise ValueError(f"core family {name!r} is not a family `full` runs")
        if name in held_out:
            raise ValueError(f"core family {name!r} is not in the macro: {held_out[name]}")


check(static_only=True)
