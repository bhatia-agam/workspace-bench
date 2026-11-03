"""A subject's native languages (plan 0060 A1.10): ``adapted/<model>/native_langs.json``.

``freeze`` writes ``contract.native_langs`` of the six families below from this file instead of
the registered header's Qwen value, and refuses those families until the file exists. File
format (one object)::

    {"model": "<key>", "native_langs": ["en", ...],   # ISO codes, English first
     "thinking": "off",                               # D7 (decided: off, the skill's rule)
     "method": "plan 0054 R6", "measured": "YYYY-MM-DD", "evidence": "<free text>"}

The measurement itself (plan 0054 R6 on the subject, a GPU job) is not implemented yet:
``measure`` raises. ``record`` writes a measurement made elsewhere, with its evidence.

Exception to copy-verbatim: when the subject's languages differ from the registered header's,
the ORIGINALS' native units are rebuilt per ``native_langs`` (plan 0054 §B) by the multilingual
upgraders (A2). Contract for an A2 multilingual upgrader, per original it rebuilds:

- set ``item[MARKER] = <the subject's native_langs>`` (``native_units_for``);
- rebuild EVERY unit (``units``: the native-role units AND the ``language`` unit, whose forms are
  keyed by native code) and ``probe_token_lens``;
- rebuild every native-dependent key the registered item has (``NATIVE_KEYS``: ``mc`` and
  ``mc_roles``, i.e. the native / language option blocks such as ``mc.correction_native``, and
  ``l2_equals_native`` / ``bridge_l2_creditable``);
- drop (never ship) an item whose L2 becomes native or stops being native, with that reason.

``freeze`` refuses a family whose passing originals are not marked for the subject's languages or
lack one of those keys (``unbuilt``), and otherwise takes them from the row (``overlay``)."""

import datetime as dt
import json
from typing import Any

from . import store

FILE = "native_langs.json"
MARKER = "native_units_for"  # item key: the native_langs its native units were rebuilt for
# the families whose header carries contract.native_langs (judges: banks.native_langs)
FAMILIES = (
    "multilingual",
    "multilingual_mt",
    "multilingual_typo",
    "multilingual_multihop",
    "basic_readout_mt",
    "typo_mt",
)
# per family, the unit roles holding forms in the native languages (documentation of what the
# rebuild touches; freeze takes EVERY unit from a rebuilt row, ``language`` included)
NATIVE_ROLES: dict[str, tuple[str, ...]] = {
    "multilingual": ("concept_native", "language"),
    "multilingual_mt": ("concept", "language"),
    "multilingual_typo": ("correction_native", "language"),
    "multilingual_multihop": ("bridge_native", "language"),
    "basic_readout_mt": ("readout", "language"),
    "typo_mt": ("correction",),
}
# item keys whose value depends on the native languages; with ``units`` and
# ``probe_token_lens``, a rebuilt original ships the row's value of every one the registered item
# has
NATIVE_KEYS = ("units", "probe_token_lens", "mc", "mc_roles", "l2_equals_native",
               "bridge_l2_creditable")  # fmt: skip
THINKING = ("off", "on")


def path(model: str):
    return store.model_dir(model) / FILE


def load(model: str) -> dict[str, Any] | None:
    """The validated record, or None when it was never measured."""
    p = path(model)
    if not p.exists():
        return None
    rec = json.loads(p.read_text(encoding="utf-8"))
    validate(rec)
    return rec


def validate(rec: dict[str, Any]) -> None:
    langs = rec.get("native_langs")
    if not isinstance(langs, list) or not langs or not all(isinstance(x, str) for x in langs):
        raise SystemExit(f"{FILE}: native_langs must be a non-empty list of ISO codes")
    if langs[0] != "en":
        raise SystemExit(f"{FILE}: native_langs must list English first, got {langs}")
    if len(set(langs)) != len(langs):
        raise SystemExit(f"{FILE}: duplicate codes in {langs}")
    if rec.get("thinking") not in THINKING:
        raise SystemExit(f"{FILE}: thinking must be one of {THINKING} (plan 0060 D7)")


def langs_for_freeze(model: str) -> list[str]:
    """What freeze writes into ``contract.native_langs``; refuses when unmeasured."""
    rec = load(model)
    if rec is None:
        raise SystemExit(
            f"{model}: no {path(model)}; measure the subject's native languages first "
            f"(plan 0060 A1.10) before freezing {', '.join(FAMILIES)}"
        )
    return list(rec["native_langs"])


def record(model: str, langs: list[str], evidence: str, thinking: str = "off",
           method: str = "plan 0054 R6") -> dict[str, Any]:  # fmt: skip
    """Write a measurement made elsewhere (never a guess: ``evidence`` is required)."""
    if not evidence.strip():
        raise SystemExit("native_langs: evidence= is required (what was measured, where)")
    rec = {"model": model, "native_langs": list(langs), "thinking": thinking, "method": method,
           "measured": str(dt.date.today()), "evidence": evidence}  # fmt: skip
    validate(rec)
    store.write_json(path(model), rec)
    return rec


def measure(model: str, thinking: str = "off") -> dict[str, Any]:
    """Plan 0054 R6 on the subject (GPU). Not implemented: plan 0060 Phase B measures it."""
    raise NotImplementedError(
        f"native_langs measurement for {model} (plan 0054 R6, thinking={thinking}) is not "
        "implemented yet; measure it on the subject and write the result with "
        "`python -m wsbench.adapt native_langs model=<m> langs=en,... evidence=...`"
    )


def unbuilt(family: str, row_item: dict, reg_item: dict, langs: list[str]) -> bool:
    """True when ``row_item`` is not a rebuild of ``reg_item`` for ``langs``: unmarked, marked
    for other languages, or missing a native-dependent key the registered item has."""
    if row_item.get(MARKER) != list(langs):
        return True
    return any(k in reg_item and k not in row_item for k in NATIVE_KEYS)


def overlay_native_units(family: str, item: dict, row_item: dict) -> dict:
    """``item`` (a copy of the registered original) with every native-dependent key
    (``NATIVE_KEYS``: all units, the language unit included, the token counts, the option blocks,
    the L2-is-native flags) taken from the rebuilt row (freeze re-counts tokens on a non-Qwen
    tokenizer)."""
    import copy

    for k in NATIVE_KEYS:
        if k in item and k in row_item:
            item[k] = copy.deepcopy(row_item[k])
    return item
