"""Judge-input audit (plan 0060 A2.0): everything each registered family's judge and read plan
read for an item, and what an ADAPTED item must therefore carry.

One :class:`FamilyInputs` per registered family (``registry.FAMILIES``; a family registered
without an entry here fails ``tests/test_adapt_judge_inputs.py``). Each :class:`JudgeInput` is
one thing the judge reads:

- ``kind``: ``item`` (an item key, dotted for nested: ``mc.gold``), ``header`` (a bank top-level
  key), ``resource`` (a file or Python table looked up by item id, gold value or registered-bank
  membership), ``id_rule`` (a rule keyed on the id's text) or ``qwen`` (a value measured on, or
  shaped by, Qwen3.6-27B: tokenizer counts, template markers, Qwen's own answers).
- ``absent``: what the code does when the input is missing for an item: ``exit`` (raise /
  SystemExit / KeyError), ``silent`` (a default that changes scoring without a word),
  ``fallback`` (another instrument / code path), or ``-`` (not applicable).
- ``cls``: for an ADAPTED item, ``copy-verbatim`` (originals carry it when copied from the
  registered item), ``build`` (adapted-only items need it built), ``subject`` (re-derived on the
  subject model) or ``hazard`` (a silent fallback for adapted-only ids / adapted banks).
- ``required``: every item of a valid bank needs it (``REQUIRED_ITEM_FIELDS`` is derived from
  these); ``adapted_only``: only an item whose id is NOT in the registered bank needs it (an
  explicit per-item field replacing an id lookup).
- ``probe``: an optional check ``(item, header, registered) -> problem | None`` for inputs that
  are not plain key presence (a gold missing from a lexicon, an id-pattern rule).

:func:`check_item` reports, per item, the missing required inputs and the probe hits. Problems
are strings ``"<severity>: <input>: <detail>"`` with severity ``missing`` (a required key is
absent), ``exit`` (the judge would stop on this item) or ``hazard`` (the judge would run but
silently score this item differently from a registered one). Freeze (plan 0060 A1.1) refuses on
``missing`` / ``exit``; ``hazard`` lists what an upgrader must still build.

The human-readable view is ``docs/adapt_judge_inputs.md``. File:line references are as of plan
0060 (2026-11-02); the table is a floor checked by tests, not a proof of completeness."""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wsbench import registry
from wsbench.banks import label_of

EXIT, SILENT, FALLBACK, NA = "exit", "silent", "fallback", "-"
COPY, BUILD, SUBJECT, HAZARD = "copy-verbatim", "build", "subject", "hazard"
ABSENT = (EXIT, SILENT, FALLBACK, NA)
CLASSES = (COPY, BUILD, SUBJECT, HAZARD)
KINDS = ("item", "header", "resource", "id_rule", "qwen")

Probe = Callable[[Mapping[str, Any], Mapping[str, Any], bool], "str | None"]


@dataclass(frozen=True)
class JudgeInput:
    kind: str
    name: str  # dotted item / header path, a resource path, or a rule name
    absent: str
    cls: str
    where: str  # file:line (src/wsbench/ relative unless it starts with evals/)
    note: str = ""
    required: bool = False
    adapted_only: bool = False
    probe: Probe | None = None


@dataclass(frozen=True)
class FamilyInputs:
    family: str
    judge: str  # the judge module(s)
    mode: str  # plan 0060 §1 / §6b: what the refresh does with the family
    shape: str  # "dict" (header + items) | "list" (bare list) | "manifest" (jlens)
    id_key: str  # "name" (id = banks.label_of(name)) | "id"
    inputs: tuple[JudgeInput, ...]
    note: str = ""


def _i(name, absent, cls, where, note="", **kw) -> JudgeInput:
    return JudgeInput("item", name, absent, cls, where, note, **kw)


def _req(name, cls, where, note="", absent=EXIT, **kw) -> JudgeInput:
    return JudgeInput("item", name, absent, cls, where, note, required=True, **kw)


def _h(name, absent, cls, where, note="", **kw) -> JudgeInput:
    return JudgeInput("header", name, absent, cls, where, note, **kw)


def _r(name, absent, cls, where, note="", **kw) -> JudgeInput:
    return JudgeInput("resource", name, absent, cls, where, note, **kw)


def _rule(name, absent, cls, where, note="", **kw) -> JudgeInput:
    return JudgeInput("id_rule", name, absent, cls, where, note, **kw)


def _q(name, cls, where, note="", absent=NA, **kw) -> JudgeInput:
    return JudgeInput("qwen", name, absent, cls, where, note, **kw)


# ------------------------------------------------------------------------------ path helpers

_MISSING = object()


def get_path(d: Any, path: str) -> Any:
    """``d["a"]["b"]`` for ``"a.b"``; :data:`_MISSING` when any step is absent."""
    cur = d
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def has_path(d: Any, path: str) -> bool:
    """``"a.b"``: every key present; ``"a[].b"``: ``a`` is a non-empty list and every element
    has ``b`` (plan 0066 §11.1, the same rule as ``run.has_path``)."""
    head, sep, rest = path.partition("[].")
    if not sep:
        return get_path(d, path) is not _MISSING
    cur = get_path(d, head)
    return isinstance(cur, list) and bool(cur) and all(has_path(el, rest) for el in cur)


def item_id(item: Mapping[str, Any]) -> str:
    """The judge's id of a bank item: ``label_of(name)`` for name-keyed banks, else ``id``."""
    if item.get("name"):
        return label_of(str(item["name"]))
    return str(item.get("id") or item.get("label") or "")


@functools.cache
def registered_ids(family: str) -> frozenset[str]:
    """Ids of the family's REGISTERED bank (``registry.frozen_bank_path``, never the
    ``WSB_BANK_*`` overrides): what decides "original" vs "adapted-only"."""
    path = registry.frozen_bank_path(family)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if family == "jlens_concept_pr":
        return frozenset(str(p["label"]) for p in raw["prompts"])
    items = raw if isinstance(raw, list) else raw["items"]
    out = {item_id(it) for it in items}
    if isinstance(raw, dict):
        out |= {str(r["id"]) for r in raw.get("beta0_rows") or []}
    return frozenset(out)


@functools.cache
def _json(rel: str) -> Any:
    return json.loads((registry.REPO_ROOT / rel).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------ probes
# Each probe takes (item, header, registered) and returns a problem string or None. They import
# the judge's own tables lazily, so the audit reads exactly what the judge reads.


def _p_multihop_element(it, _h, registered):
    from wsbench.basic.mcjudge_bank import element_item

    if registered or (it.get("mc") or {}).get("bridge_type") != "number":
        return None
    p = str(it.get("prompt", "")).lower()
    if ("periodic table" in p or "element" in p) and not element_item({"id": item_id(it)}):
        return (
            "hazard: id_rule nhop-*-element: a number bridge read as an atomic number, but the "
            "id does not match ^nhop-.+-element$, so the round-4 element-index widening is off "
            "(mcjudge_bank.py:336-344; needs an explicit per-item flag, plan 0060 §1)"
        )
    return None


def _p_brmt_render(it, _h, _reg):
    if it.get("eval_render") != "chat":
        return (
            f"hazard: eval_render {it.get('eval_render')!r} != 'chat': the plan reads the v1 "
            "plain final-token site, not the v4 chat render (readplan.py:711,729)"
        )
    return None


def _p_agentic_twin_rule(it, _h, _reg):
    if it.get("arm") == "twin" and not it.get("twin_rule"):
        return (
            "hazard: a twin without twin_rule: the Stage C prompt is the plain twin one, so an "
            "object twin is graded without TWIN_RULE_OBJECT (prompts.py:391-396)"
        )
    return None


def _p_poetry_distractors(it, _h, _reg):
    from wsbench.evals.poetry.options import N_DISTRACTORS, distractors

    if not (it.get("mc") or {}).get("candidates"):
        return None  # reported as missing
    n = len(distractors(dict(it)))
    if n < N_DISTRACTORS:
        return (
            f"exit: poetry: only {n} mc.candidates survive the gold and qwen_commits filters "
            f"(need {N_DISTRACTORS}; options.py:146-148 ValueError fails the whole run)"
        )
    return None


def _p_rb_distractors(it, _h, _reg):
    from wsbench.evals.role_bound_association.judge import distractors_v3

    if str(it.get("pair_id", "")) not in distractors_v3():
        return (
            f"hazard: evals/role_bound_association/distractors_v3.json: no entry for pair_id "
            f"{it.get('pair_id')!r}: build_block_v3 silently falls back to the leaking oa-v2 "
            "block (judge.py:270-272)"
        )
    return None


def _p_rb_roles(it, _h, _reg):
    from wsbench.evals.role_bound_association.gate import load_lexicon

    lex = load_lexicon()
    miss = [r for r in (it.get("role_a"), it.get("role_b")) if r and not lex.has(str(r))]
    if miss:
        return (
            f"hazard: evals/role_bound_association/roles_v1.json: roles {miss} not in the "
            "lexicon: role_ref accepts only the literal role, conflicting_role loses near-role "
            "terms (gate.py:40-69, 262-391); counted only in extras.n_roles_unlexiconed"
        )
    return None


def _p_rb_action(it, _h, _reg):
    from wsbench.evals.role_bound_association.gate import ACTIONS

    acts = _json(str(ACTIONS.relative_to(registry.REPO_ROOT)))
    table = acts.get("actions", acts) if isinstance(acts, dict) else {}
    if it.get("action") and str(it["action"]) not in table:
        return (
            f"hazard: evals/role_bound_association/actions_v1.json: action {it['action']!r} "
            "not in the lexicon: only the literal word matches, no inflections / needs / preps "
            "(gate.py:413-447, 572-602)"
        )
    return None


def _p_um_class(it, _h, _reg):
    from wsbench.evals.user_modeling.aliases import UM_OPTION_POOL

    if it.get("attr_class") and it["attr_class"] not in UM_OPTION_POOL:
        return (
            f"exit: user_modeling attr_class {it['attr_class']!r} is not a UM_OPTION_POOL class "
            "(options.py:96 KeyError)"
        )
    return None


def _p_um_value(it, _h, _reg):
    from wsbench.evals.user_modeling.aliases import UM_OPTION_POOL, VALUE_ALIASES
    from wsbench.evals.user_modeling.options import value_id

    if not it.get("attr"):
        return None
    v = value_id(str(it["attr"]))
    probs = []
    if v not in VALUE_ALIASES:
        probs.append(
            "not in VALUE_ALIASES (forms_of / shadow_forms raise KeyError on a verified gold "
            "pick, options.py:56-77; the value gate can never pass)"
        )
    if v not in (UM_OPTION_POOL.get(str(it.get("attr_class"))) or ()):
        probs.append("not in its class pool (no UM_EXCLUDE / NEIGHBOURS entries either)")
    if probs:
        return f"hazard: user_modeling gold {v!r} " + "; ".join(probs)
    return None


def _p_um_region(it, _h, _reg):
    from wsbench.evals.user_modeling.aliases import COUNTRY_REGIONS, COUNTRY_UNGROUPED
    from wsbench.evals.user_modeling.options import value_id

    if it.get("attr_class") != "Country" or not it.get("attr"):
        return None
    v = value_id(str(it["attr"]))
    if any(v in vs for vs in COUNTRY_REGIONS.values()) or v in COUNTRY_UNGROUPED:
        return None
    return (
        f"hazard: user_modeling Country gold {v!r} has no COUNTRY_REGIONS region: the "
        "um-v3.4 region draw silently treats every region as eligible (options.py:100-101)"
    )


def _p_dm_group(it, _h, _reg):
    from wsbench.evals.directed_modulation.judge import _groups

    if it.get("concept") and str(it["concept"]) not in _groups():
        return (
            f"exit: evals/directed_modulation/distractor_groups.json has no group for concept "
            f"{it['concept']!r} (judge.py:69-77 ValueError)"
        )
    return None


def _p_mcdm_relation_name(it, _h, _reg):
    if it.get("roles") and not str(it.get("name", "")).startswith("b-"):
        return (
            "hazard: id_rule b-*: a relation item (it has roles) whose name lacks the b- prefix "
            "is judged as dictation: wrong option pool, no both-names check (options.py:120)"
        )
    return None


def _p_mcdm_names(it, _h, _reg):
    roles = it.get("roles") or {}
    people = [roles.get("agent"), roles.get("patient")]
    known = _mcdm_people() | set(it.get("aliases") or {})
    miss = [p for p in people if p and p not in known]
    if miss:
        return (
            f"hazard: name_aliases_v2.json has no forms for {miss}: a Chinese readout can never "
            "name them in the both-names check (options.py:126-147)"
        )
    return None


@functools.cache
def _mcdm_people() -> frozenset[str]:
    from wsbench.evals.multi_concept_directed_modulation import options

    return frozenset(options.name_aliases())


def _agentic_targets() -> frozenset[str]:
    """The ids with a Stage C target, from the file the judge reads (``targets_path``), cached
    per bank override (resolving the path loads the registry, so it is not redone per item)."""
    import os

    keys = (registry.BANK_ROOT_ENV, registry.BANK_FILE_ENV_PREFIX + "AGENTIC_MISALIGNMENT")
    return _targets_for(tuple(os.environ.get(k, "") for k in keys))


@functools.cache
def _targets_for(_env: tuple[str, ...]) -> frozenset[str]:
    from wsbench.evals.agentic_misalignment.judge import targets_path

    return _targets_at(str(targets_path()))


@functools.cache
def _targets_at(path: str) -> frozenset[str]:
    return frozenset(json.loads(Path(path).read_text(encoding="utf-8"))["items"])


def _p_mcdm_target(_it, h, _reg):
    from wsbench.evals.multi_concept_directed_modulation.regions import TARGET_SENTENCE

    ts = h.get("target_sentence")
    if ts is not None and ts != TARGET_SENTENCE:
        return (
            "hazard: header target_sentence differs from regions.TARGET_SENTENCE: every cell "
            "is labelled off_task and pass=None (judge.py:379)"
        )
    return None


def _p_agentic_target(it, _h, _reg):
    t = _agentic_targets()
    if str(it.get("id")) in t or (it.get("arm") == "twin" and str(it.get("twin")) in t):
        return None
    return (
        f"exit: agentic targets: no Stage C target for {it.get('id')!r}; an adapted bank reads "
        "the REGISTERED evals/agentic_misalignment/targets_v2.json (judge.py:71-105)"
    )


def _p_brmt_exonyms(it, _h, registered):
    if registered:
        return None
    return (
        "hazard: evals/basic_readout_mt/exonyms.json is keyed by registered item id "
        "(multitoken/family.py:1777-1823): an adapted-only id gets no exonym forms (a stricter "
        "name gate) unless the set's own exonyms.json lists it"
    )


def _p_mt_language_unit(it, _h, _reg):
    from wsbench.multitoken.languages import is_frozen_language_unit

    if not it.get("mc_roles"):
        return None
    for u in it.get("units") or []:
        if u.get("role") == "language" and not is_frozen_language_unit(
            str(it.get("lang", "")), u.get("forms") or {}
        ):
            return (
                "hazard: the language unit's forms are not the frozen LANGUAGES table's for "
                f"{it.get('lang')!r}: it is scored as written, not swapped to naming forms "
                "(multitoken/regex.py:373-379)"
            )
    return None


def _mt_mc_roles(diagnostic_only: bool = False) -> Probe:
    def probe(it, _h, _reg):
        if diagnostic_only:
            return None
        miss = [r for r in it.get("mc_roles") or [] if r not in (it.get("mc") or {})]
        if miss:
            return (
                f"hazard: mc has no block for judged roles {miss}: options are silently drawn "
                "from other items' golds (multitoken/options.py:207-212)"
            )
        return None

    return probe


def _p_mh2_readout(it, _h, _reg):
    if (it.get("readout") or {}).get("kind") != "all":
        return (
            "hazard: readout.kind != 'all': ONE such item flips the whole family's read plan "
            "to the v1 final-token read (readplan.py:732-741)"
        )
    return None


def _p_br_readout(it, _h, _reg):
    if (it.get("readout") or {}).get("kind") != "question_through_end":
        return (
            "hazard: readout.kind != 'question_through_end': the plan silently reads the v1 "
            "final_token / offset site instead of the v5 question span (readplan.py:455-514)"
        )
    return None


def _p_moral_version(it, _h, _reg):
    if it.get("bank_version") != 3:
        return (
            f"hazard: bank_version {it.get('bank_version')!r} != 3: absent = v1 (ec-v3.1, pool "
            "distractors, judge.py:100-106); >= 4 plans from the frozen 27B v3 rows "
            "(readplan.py:872-877)"
        )
    return None


def _p_conj_version(it, _h, _reg):
    if it.get("bank_version") != 4:
        return (
            f"hazard: bank_version {it.get('bank_version')!r} != 4 (the registered value; "
            "absent counts as v1, a mixed bank exits, judge.py:520-526)"
        )
    return None


def _p_conj_gold(it, _h, _reg):
    if it.get("mc_options") and it.get("gold_label") not in it["mc_options"]:
        return "exit: gold_label is not one of mc_options (judge.py:127 ValueError)"
    return None


def _p_assoc_seven(it, _h, _reg):
    n = len((it.get("mc") or {}).get("distractors") or [])
    if it.get("mc") and n != 7:
        return (
            f"hazard: mc.distractors has {n} entries, not 7: the reported chance line "
            "CHANCE = 1/8 (association/prompts.py:24) is wrong for this item"
        )
    return None


def _p_chain_slots(it, _h, _reg):
    mc_ = it.get("mc")
    if isinstance(mc_, list) and len(mc_) != len(it.get("intermediates") or []):
        return "exit: mc must hold one {slot, options} block per intermediate"
    return None


def _p_rel_pair_id(it, _h, _reg):
    scene = str(it.get("scene", ""))
    if str(it.get("id")) not in (f"rel-{scene}-a", f"rel-{scene}-b"):
        return (
            "hazard: id_rule rel-{scene}-a/b: the id is not rel-<scene>-a|b, so "
            "extras.pair_consistency never counts this scene (score.py:95; report-only)"
        )
    return None


def _p_arith_variant(it, h, _reg):
    if h and it.get("variant") not in (h.get("variants") or {}):
        return (
            f"hazard: variant {it.get('variant')!r} is not in header.variants: the item "
            "silently leaves per_variant (judge.py:595, report-only)"
        )
    return None


def _p_kc_options(it, _h, _reg):
    opts = it.get("options") or []
    units = it.get("option_units") or {}
    probs = []
    if len(opts) != 5:
        probs.append(f"{len(opts)} options, not 5 (LETTERS ABCDE; distractor_floor divides by 4)")
    if it.get("gold") not in opts:
        probs.append("gold not in options")
    miss = [o for o in opts if o not in units]
    if miss:
        probs.append(f"options {miss} have no option_units forms (never hit)")
    return "hazard: " + "; ".join(probs) if probs else None


# Registered-bank options whose empty ``option_units`` list is deliberate, as (item id, option):
# in s3b1_sapporo_miso_ramen_topping, "butter and corn" carries every butter form, so the bare
# "butter" distractor has none of its own. A registered item copied verbatim into an adapted
# bank keeps it, so the msdm probe never flags it.
KNOWN_EMPTY_OPTION_UNITS: frozenset[tuple[str, str]] = frozenset(
    {("s3b1_sapporo_miso_ramen_topping", "butter")}
)


def _p_msdm_options(it, _h, _reg):
    opts = it.get("options") or []
    units = it.get("option_units") or {}
    iid = item_id(it)
    probs = []
    if it.get("gold") not in opts:
        probs.append("gold not in options (exit, judge.py:78-80)")
    if miss := [o for o in opts if not units.get(o) and (iid, o) not in KNOWN_EMPTY_OPTION_UNITS]:
        probs.append(f"options {miss} have no option_units forms (silent never-hit)")
    if "name" in it:
        probs.append("item carries `name`: readplan keys it on label_of(name), the judge on id")
    return "hazard: " + "; ".join(probs) if probs else None


def _p_wb(it, _h, _reg):
    probs = []
    if len((it.get("mc") or {}).get("order") or []) != 6:
        probs.append("mc.order is not 6 options (N_SHOWN=7 misclassifies picks)")
    forms = (it.get("mc") or {}).get("forms") or {}
    if miss := [o for o in (it.get("mc") or {}).get("order") or [] if o not in forms]:
        probs.append(f"mc.forms lacks {miss} (KeyError)")
    return "hazard: " + "; ".join(probs) if probs else None


def _p_intro_twins(it, _h, _reg):
    if it.get("kind") == "inject" and not it.get("twins"):
        return (
            "hazard: an inject item without twins: a missing gaussian twin makes the headline "
            "row undecided (pass=None) and drops it from the denominator (judge.py:1058-1063)"
        )
    return None


def _p_uvh_hint(it, _h, _reg):
    if not it.get("hint"):
        return "hazard: no hint: every COMMIT is dropped and the pair fails (judge.py:571-579)"
    return None


# ------------------------------------------------------------------------- shared input sets

_NAME = _req("name", BUILD, "banks.py:18-35", "id = label_of(name); new id for adapted-only")
_ID = _req("id", BUILD, "mcjudge.py:149-151", "raw id (bare-list bank)")


def _native_langs(where: str = "banks.py:76-91") -> JudgeInput:
    return _h(
        "contract.native_langs",
        SILENT,
        SUBJECT,
        where,
        "absent = Qwen's ('en','zh'); per-subject measurement (plan 0060 A1.10); required "
        "of an adapted bank (typo_mt's registered header has none)",
        adapted_only=True,
    )


def _qwen_min_full(n: int, where: str) -> JudgeInput:
    return _q(
        f"min_full_positions={n}",
        SUBJECT,
        where,
        "Qwen render length; reads.check_full exits below it on a sidecar file (reads.py:308)",
    )


_GRID = _q(
    "GRID layers (Qwen 64 blocks)",
    SUBJECT,
    "readplan.py:588-627",
    "remapped by depth from report.json n_layers under WSB_BANK_ROOT (exit without it)",
)
_CHAT_SUMMARIZE = _q(
    "chat_summarize render + SUMMARIZE_SUFFIX",
    SUBJECT,
    "readplan.py:23, 925-941",
    "positions from the subject's own render (suffix_text_then_tail)",
)


def _mt_common(
    *, multi_token: bool, include_target: bool, native_units: bool = False
) -> tuple[JudgeInput, ...]:
    return (
        _NAME,
        _req("prompt", COPY, "readplan.py:687-704"),
        _req(
            "units",
            SUBJECT if native_units else COPY,
            "multitoken/regex.py:363-425; mcrx.py:99-111",
            "role / forms / required / multi_token"
            + (
                "; native units rebuilt per the subject's native_langs (plan 0060 A1.10)"
                if native_units
                else ""
            ),
        ),
        _h(
            "contract.multi_token",
            SILENT,
            COPY,
            "multitoken/regex.py:283-298",
            f"registered {multi_token}; absent defaults from header.family",
            required=True,
        ),
        _h(
            "contract.include_target",
            SILENT,
            COPY,
            "multitoken/regex.py:283-298",
            f"registered {include_target}; absent = True (adds a target unit / needs target lens)",
            required=True,
        ),
        _native_langs(),
        _q(
            "LANGUAGE_NAMES {en,zh,ja,ko}",
            HAZARD,
            "multitoken/prompts.py:30",
            "any other native code is rendered as the raw ISO code in the judge prompt",
        ),
    )


def _version_header(fallback: str) -> JudgeInput:
    return _h(
        "version",
        FALLBACK,
        COPY,
        "multitoken/family.py:116-121, 336-377",
        f"absent = 1: {fallback}",
        required=True,
    )


_MC_ROLES = _req(
    "mc_roles",
    BUILD,
    "multitoken/regex.py:373-379, options.py:160-218",
    "absent: the language unit is not swapped to its naming forms (silent)",
    absent=SILENT,
)
_LANG = _req("lang", BUILD, "multitoken/options.py:13-26", "LANG_CONFUSABLES / LANGUAGES key")
_PROBE_LENS = _req(
    "probe_token_lens",
    SUBJECT,
    "multitoken/regex.py:346-360",
    "Qwen token counts per form; restamped on the subject (adapt/run.py:358-386)",
)


# --------------------------------------------------------------------------------- the table

FAMILIES: dict[str, FamilyInputs] = {}


def _add(fi: FamilyInputs) -> None:
    for x in fi.inputs:
        assert x.kind in KINDS and x.absent in ABSENT and x.cls in CLASSES, (fi.family, x)
    FAMILIES[fi.family] = fi


_add(
    FamilyInputs(
        "association",
        "evals/association/judge.py",
        "upgrade",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:931"),
            _req("mc", BUILD, "association/judge.py:69-74", "absent: fail (exit 2)"),
            _req("mc.gold", BUILD, "association/judge.py:79,87"),
            _req("mc.distractors", BUILD, "association/judge.py:87", "7 (CHANCE = 1/8)"),
            _req("mc.aliases", BUILD, "association/judge.py:80,117", absent=SILENT),
            _req(
                "mc.distractor_aliases",
                BUILD,
                "association/judge.py:120",
                "absent: weaker other-option checks in steps 3b / 3c (lenient)",
                absent=SILENT,
            ),
            _r(
                "distractor count",
                SILENT,
                BUILD,
                "association/prompts.py:24",
                probe=_p_assoc_seven,
            ),
            _r(
                "evals/association/lite_rule.json",
                NA,
                COPY,
                "readplan.py:116-127",
                "family-keyed ({kind: same})",
            ),
            _CHAT_SUMMARIZE,
            _qwen_min_full(19, "association/__init__.py:27"),
            _GRID,
        ),
        "Adapted sets today carry no mc on any item: the judge exits on all 11 sets.",
    )
)

_add(
    FamilyInputs(
        "conjunctive_association",
        "evals/conjunctive_association/judge.py",
        "originals copied verbatim (no adapted-only items)",
        "list",
        "id",
        (
            _ID,
            _req("stimulus", COPY, "readplan.py:931"),
            _req("mc_options", COPY, "conjunctive_association/judge.py:126"),
            _req("gold_label", COPY, "conjunctive_association/judge.py:127", probe=_p_conj_gold),
            _req(
                "contrast_label",
                COPY,
                "conjunctive_association/judge.py:130",
                "absent: no contrast bucket",
                absent=SILENT,
            ),
            _req(
                "inverted_label",
                COPY,
                "conjunctive_association/judge.py:133-138,291-301,418",
                "absent: a twin pick is counted as a plain distractor (the `inverted` bucket is "
                "a diagnostic)",
                absent=SILENT,
            ),
            _req(
                "bank_version",
                COPY,
                "conjunctive_association/judge.py:509-515",
                "absent = 1; mixed values exit",
                absent=FALLBACK,
                probe=_p_conj_version,
            ),
            _i("twin_of", NA, COPY, "-", "not read by the judge (provenance)"),
            _CHAT_SUMMARIZE,
            _qwen_min_full(19, "conjunctive_association/__init__.py:27"),
            _GRID,
        ),
        "Adapted 'originals' match no v4 item today (older mc_options, no bank_version).",
    )
)

_add(
    FamilyInputs(
        "role_bound_association",
        "evals/role_bound_association/{judge,gate,score}.py",
        "upgrade (judge-code overlay, plan 0060 §3)",
        "list",
        "id",
        (
            _ID,
            _req("pair_id", BUILD, "role_bound_association/judge.py:104,143,270; score.py:30"),
            _req("direction", BUILD, "role_bound_association/judge.py:147,292; score.py:41"),
            _req("role_a", BUILD, "role_bound_association/judge.py:100,274"),
            _req("role_b", BUILD, "role_bound_association/judge.py:100,274"),
            _req("action", BUILD, "role_bound_association/judge.py:143,290"),
            _req("names", BUILD, "role_bound_association/judge.py:101,275", "{a, b}"),
            _req("stimulus", BUILD, "readplan.py:931; judge.py:278"),
            _req(
                "stereotypicality",
                BUILD,
                "role_bound_association/score.py:120-125",
                "absent: dropped from by_stereotypicality / incongruent_pass_rate",
                absent=SILENT,
            ),
            _r(
                "evals/role_bound_association/distractors_v3.json",
                FALLBACK,
                HAZARD,
                "role_bound_association/judge.py:249-272",
                "keyed by pair_id (REPO_ROOT, not the bank root); missing = oa-v2 block "
                "(options-only 0.230 vs uniform 0.008)",
                probe=_p_rb_distractors,
            ),
            _r(
                "evals/role_bound_association/roles_v1.json",
                SILENT,
                HAZARD,
                "role_bound_association/gate.py:37-69",
                "keyed by role word; feeds role_ref and conflicting_role",
                probe=_p_rb_roles,
            ),
            _r(
                "evals/role_bound_association/actions_v1.json",
                SILENT,
                HAZARD,
                "role_bound_association/gate.py:413-447",
                "keyed by action word",
                probe=_p_rb_action,
            ),
            _r(
                "evals/role_bound_association/display_terms_v1.json",
                SILENT,
                BUILD,
                "role_bound_association/judge.py:179-218",
                "keyed by role; display-only '(also: …)' terms",
            ),
            _q(
                "story_guard BPE cleaning (Ġ/Ċ only)",
                HAZARD,
                "role_bound_association/judge.py:332-333",
                "a SentencePiece (▁) tokenizer never finds the suffix: the guard passes all",
            ),
            _CHAT_SUMMARIZE,
            _qwen_min_full(19, "role_bound_association/__init__.py:25"),
            _GRID,
        ),
        "adapted/qwen3.5-2b/role_bound_association.json is an empty list.",
    )
)

_add(
    FamilyInputs(
        "user_modeling",
        "evals/user_modeling/{judge,options,aliases,score}.py",
        "upgrade (per-set option-pool file, plan 0060 §3)",
        "dict",
        "name",
        (
            _NAME,
            _req("attr_class", BUILD, "user_modeling/options.py:96,131", probe=_p_um_class),
            _req("attr", BUILD, "user_modeling/options.py:131", "the gold", probe=_p_um_value),
            _req("messages", BUILD, "user_modeling/judge.py:550,647; readplan.py:860"),
            _req(
                "attr_label",
                BUILD,
                "user_modeling/judge.py:606-607",
                "absent: the question says 'attribute'",
                absent=SILENT,
            ),
            _req(
                "subfamily",
                BUILD,
                "user_modeling/judge.py:555; score.py:110",
                "absent: missing from by_subfamily",
                absent=SILENT,
            ),
            _r(
                "aliases.VALUE_ALIASES / UM_OPTION_POOL",
                EXIT,
                HAZARD,
                "user_modeling/options.py:56-96",
                "keyed by gold value; options build silently, a verified gold pick raises",
            ),
            _r(
                "aliases.UM_EXCLUDE / NEIGHBOURS",
                SILENT,
                HAZARD,
                "user_modeling/options.py:95,133",
                "keyed by gold value; missing = no exclusions / forced neighbours",
            ),
            _r(
                "aliases.COUNTRY_REGIONS",
                SILENT,
                HAZARD,
                "user_modeling/options.py:100-101",
                "Country golds only",
                probe=_p_um_region,
            ),
            _q(
                "chat_context render, every position",
                SUBJECT,
                "readplan.py:849-869",
                "positions from the subject's own render",
            ),
            _qwen_min_full(37, "user_modeling/__init__.py:22-24"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "directed_modulation",
        "evals/directed_modulation/judge.py",
        "none (re-read only)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:807"),
            _req("assistant", COPY, "readplan.py:805,808"),
            _req("concept", COPY, "directed_modulation/judge.py:95,98", probe=_p_dm_group),
            _req(
                "subfamily",
                COPY,
                "directed_modulation/judge.py:95,225",
                "unknown value: CREDIT_PAIR",
            ),
            _req("polarity", COPY, "directed_modulation/judge.py:226", "non-think: BASIS_NEG"),
            _req(
                "pair_id",
                COPY,
                "directed_modulation/score.py:131",
                "absent: out of the white_bear contrast",
                absent=SILENT,
            ),
            _r(
                "evals/directed_modulation/distractor_groups.json",
                EXIT,
                BUILD,
                "directed_modulation/judge.py:37,56-77",
                "keyed by concept (REPO_ROOT)",
            ),
            _r(
                "option draw over the LOADED bank",
                SILENT,
                HAZARD,
                "directed_modulation/judge.py:84-116",
                "distractors come from the bank's same-subfamily concepts: a smaller adapted "
                "bank changes the options shown even for verbatim originals; fewer than "
                "N_DISTRACTORS=4 unrelated concepts in a subfamily raises ValueError "
                "(judge.py:101-102; check_bank checks it)",
            ),
            _q("chat_dm render", SUBJECT, "readplan.py:35,805"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multi_concept_directed_modulation",
        "evals/multi_concept_directed_modulation/{judge,options,regions}.py",
        "carry (v2, 116 items)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:1007"),
            _req(
                "concepts",
                COPY,
                "multi_concept_directed_modulation/options.py:121,153-169",
                "absent: judged as a control (pass=None)",
                absent=SILENT,
            ),
            _i(
                "roles",
                FALLBACK,
                COPY,
                "multi_concept_directed_modulation/options.py:120-123",
                "b-* items: absent = parse_relation(concepts[0]) (v1)",
                probe=_p_mcdm_names,
            ),
            _i("aliases", SILENT, COPY, "multi_concept_directed_modulation/options.py:129"),
            _req(
                "stratum", COPY, "multi_concept_directed_modulation/judge.py:931-934", absent=SILENT
            ),
            _i("prior_direction", SILENT, COPY, "multi_concept_directed_modulation/judge.py:942"),
            _h(
                "target_sentence",
                EXIT,
                COPY,
                "readplan.py:1008",
                "must equal regions.TARGET_SENTENCE",
                required=True,
                probe=_p_mcdm_target,
            ),
            _h(
                "last_n",
                SILENT,
                SUBJECT,
                "readplan.py:1004",
                "absent = 12, the Qwen token count of the target sentence",
            ),
            _r(
                "relation_clusters_v2.json",
                EXIT,
                BUILD,
                "multi_concept_directed_modulation/options.py:70-76,200-202",
                "beside the adapted bank if present, else the frozen dir",
            ),
            _r(
                "distractor_groups_v2.json",
                SILENT,
                HAZARD,
                "multi_concept_directed_modulation/options.py:139-145",
                "a concept not listed gets no close-relative exclusion",
            ),
            _r(
                "name_aliases_v2.json",
                SILENT,
                HAZARD,
                "multi_concept_directed_modulation/options.py:126-147",
                "keyed by person",
            ),
            _rule(
                "b-* relation prefix",
                SILENT,
                HAZARD,
                "multi_concept_directed_modulation/options.py:120",
                probe=_p_mcdm_relation_name,
            ),
            _rule(
                "-a/-b, -ab/-ba partner suffixes",
                SILENT,
                HAZARD,
                "multi_concept_directed_modulation/options.py:59-68",
                "a pair that breaks the naming loses its partner option and veto",
            ),
            _q(
                "<think>/</think> markers",
                SUBJECT,
                "multi_concept_directed_modulation/regions.py:8-9",
            ),
            _qwen_min_full(12, "multi_concept_directed_modulation/__init__.py:27"),
            _GRID,
        ),
        "Adapted sets today are the v1 bank (100 items, header last_n 12 on every subject).",
    )
)

_add(
    FamilyInputs(
        "basic_readout",
        "basic/mcjudge_basic.py",
        "rebuild (v5)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:455-514"),
            _req("readout", COPY, "readplan.py:455-514", probe=_p_br_readout, absent=FALLBACK),
            _req(
                "mc.gold",
                SUBJECT,
                "basic/mcjudge_basic.py:141-148",
                "implicit: subject's modal answer",
            ),
            _req(
                "mc.distractors",
                BUILD,
                "basic/mcjudge_basic.py:141-148",
                "never the subject's answer",
            ),
            _req(
                "mc.gold_position",
                BUILD,
                "basic/mcjudge_basic.py:149-159",
                "absent: seeded shuffle; balanced per subfamily at freeze (set-level)",
                absent=FALLBACK,
            ),
            _req("mc.aliases", BUILD, "basic/mcjudge_basic.py:163-166", absent=SILENT),
            _req("mc.distractor_aliases", BUILD, "basic/mcjudge_basic.py:163-166", absent=SILENT),
            _req(
                "task_context",
                BUILD,
                "basic/mcjudge_basic.py:388,571-586,679-682",
                "absent: blank TASK TYPE line and no digest context",
                absent=SILENT,
            ),
            _req(
                "slice",
                BUILD,
                "basic/mcjudge_basic.py:67,389",
                "absent: number-flood void off for arith",
                absent=SILENT,
            ),
            _req("subfamily", BUILD, "basic/mcjudge_basic.py:525", absent=SILENT),
            _q(
                "implicit golds = Qwen3.6-27B's modal answer",
                SUBJECT,
                "evals/basic_readout/items_v5.json header gate",
            ),
            _q("chat_prefill + ANSWER_STEM", SUBJECT, "readplan.py:22,471-483"),
            _q(
                "zh forms in mc.aliases (DEFAULT_NATIVE_LANGS)",
                SUBJECT,
                "evals/basic_readout/items_v5.json",
            ),
            _qwen_min_full(8, "basic_readout/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multihop",
        "basic/mcjudge_bank.py",
        "upgrade",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:517-543"),
            _req("mc.gold", COPY, "basic/mcjudge_bank.py:127-141"),
            _req("mc.distractors", COPY, "basic/mcjudge_bank.py:127-141", "≤ 7 (LETTERS)"),
            _req(
                "mc.bridge_type",
                BUILD,
                "basic/mcjudge_bank.py:236,529,545,681",
                "absent: a number bridge is matched as text (flood / element rules off)",
                absent=SILENT,
            ),
            _req("mc.aliases", BUILD, "basic/mcjudge_bank.py:449", absent=SILENT),
            _req("mc.distractor_aliases", BUILD, "basic/mcjudge_bank.py:251,454", absent=SILENT),
            _req(
                "readout.offsets",
                SUBJECT,
                "readplan.py:527-541",
                "lite last-word offset in the subject's tokens; absent = [-1]",
                absent=SILENT,
            ),
            _r(
                "evals/multihop/derived_forms.json",
                SILENT,
                BUILD,
                "basic/mcjudge_bank.py:430-449",
                "keyed by option value; a set's own WSB_BANK_ROOT/multihop/derived_forms.json adds "
                "forms for new values; a value in neither has no derived forms (name and aliases)",
            ),
            _rule(
                "^nhop-.+-element$",
                SILENT,
                HAZARD,
                "basic/mcjudge_bank.py:336-344,560",
                "element-index widening keyed on the id",
                probe=_p_multihop_element,
            ),
            _q("zh forms in mc.aliases", SUBJECT, "evals/multihop/items_v3.json"),
            _qwen_min_full(8, "multihop/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "typo",
        "basic/{family,judge}.py",
        "superseded by typo_mt (not refilled)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:455-514"),
            _req(
                "intermediates",
                COPY,
                "banks.py:38-55",
                "the targets; absent = an empty targets line",
                absent=SILENT,
            ),
            _req(
                "readout",
                SUBJECT,
                "readplan.py:455-514",
                "offsets in the subject's tokens; absent = final_token",
                absent=SILENT,
            ),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "basic_readout_mt",
        "multitoken/family.py (scorer mc + tolerant name gate)",
        "rebuild (v4)",
        "dict",
        "name",
        (
            *_mt_common(multi_token=True, include_target=False),
            _PROBE_LENS,
            _req(
                "eval_render",
                COPY,
                "readplan.py:707-731",
                "not 'chat': per-item v1 plain final-token read",
                absent=FALLBACK,
                probe=_p_brmt_render,
            ),
            _req(
                "readout",
                COPY,
                "readplan.py:707-731",
                "readout.lite; absent = final_token lite (readplan.py:725)",
                absent=SILENT,
            ),
            _req("mc.readout", BUILD, "multitoken/options.py:207-212", absent=FALLBACK),
            _req(
                "name_forms.readout",
                BUILD,
                "multitoken/family.py:1273-1280",
                "absent: the unit's own forms (no zh, no aliases)",
                absent=SILENT,
            ),
            _i("lang", EXIT, BUILD, "multitoken/options.py:13-26", "L2 items only"),
            _i("target", SILENT, BUILD, "multitoken/family.py:1266-1270", "L2 items only"),
            _r(
                "evals/basic_readout_mt/exonyms.json",
                SILENT,
                HAZARD,
                "multitoken/family.py:1777-1823",
                "keyed by registered item id (REPO_ROOT)",
                probe=_p_brmt_exonyms,
            ),
            _qwen_min_full(8, "basic_readout_mt/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multilingual",
        "multitoken/family.py + mcrx.py (scorer mc+regex)",
        "upgrade",
        "dict",
        "name",
        (
            *_mt_common(multi_token=False, include_target=False, native_units=True),
            _version_header("the v1 basic bank judge (v1_scorer='bank')"),
            _LANG,
            _MC_ROLES,
            _req("mc.concept_native", BUILD, "multitoken/options.py:207-212", absent=FALLBACK),
            _req(
                "mc.language",
                BUILD,
                "multitoken/options.py:13-26",
                "absent: LANG_CONFUSABLES[lang] (exit for 16 of 21 bank langs)",
                absent=EXIT,
            ),
            _r(
                "language unit = frozen LANGUAGES forms",
                SILENT,
                HAZARD,
                "multitoken/languages.py:747-754",
                probe=_p_mt_language_unit,
            ),
            _q(
                "prompts.ML_ALIAS_NOTE (rendered from the 27B v3 bank)",
                HAZARD,
                "multitoken/prompts.py:194-200",
                "stale for an adapted bank's option set",
            ),
            _qwen_min_full(4, "multilingual/__init__.py"),
            _GRID,
        ),
        "Adapted sets today are v1: they silently run the retired v1 scorer.",
    )
)

_add(
    FamilyInputs(
        "multilingual_mt",
        "multitoken/family.py + regex.py (scorer regex)",
        "upgrade",
        "dict",
        "name",
        (
            *_mt_common(multi_token=False, include_target=False, native_units=True),
            _version_header("raw-sample regex supplement off, no instrument tag"),
            _LANG,
            _MC_ROLES,
            _i("mc", FALLBACK, BUILD, "multitoken/options.py:207-212", "opts=judge=mc only"),
            _r(
                "language unit = frozen LANGUAGES forms",
                SILENT,
                HAZARD,
                "multitoken/languages.py:747-754",
                probe=_p_mt_language_unit,
            ),
            _qwen_min_full(16, "multilingual_mt/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multilingual_typo",
        "multitoken/family.py + regex.py (scorer regex)",
        "upgrade",
        "dict",
        "name",
        (
            *_mt_common(multi_token=True, include_target=False, native_units=True),
            _version_header("raw-sample supplement and anchors off"),
            _LANG,
            _MC_ROLES,
            _PROBE_LENS,
            _req(
                "target",
                COPY,
                "multitoken/family.py:588-601",
                "anchors; absent = fewer anchors",
                absent=SILENT,
            ),
            _i("mc", FALLBACK, BUILD, "multitoken/options.py:207-212", "opts=judge=mc only"),
            _r(
                "language unit = frozen LANGUAGES forms",
                SILENT,
                HAZARD,
                "multitoken/languages.py:747-754",
                probe=_p_mt_language_unit,
            ),
            _qwen_min_full(13, "multilingual_typo/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multilingual_multihop",
        "multitoken/family.py + mcrx.py (scorer mc+regex)",
        "upgrade",
        "dict",
        "name",
        (
            *_mt_common(multi_token=True, include_target=False, native_units=True),
            _version_header("regex-only v1 path"),
            _LANG,
            _req(
                "mc_roles",
                BUILD,
                "multitoken/options.py:160-218",
                "absent: option_sets raises on bridge_l2",
                probe=_mt_mc_roles(),
            ),
            _req("mc.bridge_native", BUILD, "multitoken/options.py:207-212", absent=FALLBACK),
            _req("mc.language", BUILD, "multitoken/options.py:13-26", absent=SILENT),
            _req("target", COPY, "multitoken/mcrx.py:811-816", "anchors", absent=SILENT),
            _i(
                "probe_token_lens",
                EXIT,
                SUBJECT,
                "multitoken/regex.py:346-360",
                "bridge_l2 lens; absent by design when l2_equals_native",
            ),
            _i(
                "l2_equals_native",
                SILENT,
                BUILD,
                "multitoken/mcrx.py:1027-1058",
                "absent = in the headline; re-derived per native_langs (A1.10)",
            ),
            _i("bridge_l2_creditable", NA, BUILD, "-", "not read by the judge"),
            _r(
                "language unit = frozen LANGUAGES forms",
                SILENT,
                HAZARD,
                "multitoken/languages.py:747-754",
                probe=_p_mt_language_unit,
            ),
            _qwen_min_full(12, "multilingual_multihop/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "typo_mt",
        "multitoken/family.py + regex.py (scorer regex)",
        "upgrade (header only)",
        "dict",
        "name",
        (
            *_mt_common(multi_token=True, include_target=False),
            _PROBE_LENS,
            _req("typo_word", COPY, "readplan.py:664-686"),
            _req("target", COPY, "readplan.py:664-686", "first_diff site"),
            _h("version", SILENT, COPY, "multitoken/family.py:244-247", "typo-v2 tag only"),
            _rule(
                "tyh-arith-* (retired ids)",
                NA,
                HAZARD,
                "evals/typo_mt/items_v2.json header dropped.names",
                "no code rule: an arith item copied from v1 is scored like any other",
            ),
            _qwen_min_full(1, "typo_mt/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "multihop_mt_v2",
        "multitoken/family.py (MC_PROFILES, rival)",
        "model-specific (Phase E)",
        "dict",
        "name",
        (
            *_mt_common(multi_token=True, include_target=True),
            _PROBE_LENS,
            _req("target", COPY, "multitoken/regex.py:283-298", "include_target: lens needed"),
            _req("readout", COPY, "readplan.py:732-741", probe=_p_mh2_readout, absent=FALLBACK),
            _req("mc", BUILD, "multitoken/options.py:207-212", absent=FALLBACK),
            _req("name_forms", BUILD, "multitoken/family.py:2617-2632", absent=SILENT),
            _req(
                "units[].kind",
                BUILD,
                "multitoken/family.py:1307-1328 (bank_entities), 1877-1884 (_rivals)",
                "list_gate's rival pools are keyed by kind: a unit without one joins the '' pool "
                "and gets no same-kind rivals (plan 0066 §6; refill units are classified, never "
                "defaulted)",
                absent=SILENT,
            ),
            _q(
                "SYSTEM 'English or Chinese' (MH2_NATIVE_LANGS = DEFAULT_NATIVE_LANGS)",
                HAZARD,
                "evals/multihop_mt_v2/prompts.py:41,58",
                "ignores the header's native_langs",
            ),
            _q(
                "not in adapt lint.MT: probe_token_lens never restamped",
                HAZARD,
                "adapt/run.py:373",
            ),
            _qwen_min_full(15, "multihop_mt_v2/__init__.py:19-21"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "chain_intermediates",
        "evals/chain_intermediates/judge.py",
        "upgrade + regate (v2)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:953"),
            _req("start", COPY, "readplan.py:951; chain_intermediates/judge.py:456"),
            _req("intermediates", COPY, "chain_intermediates/judge.py:454,695"),
            _req("answer", COPY, "chain_intermediates/judge.py:456,762"),
            _req(
                "mc",
                BUILD,
                "chain_intermediates/judge.py:471-479,689-693",
                "absent: exit; opts=judge=free swaps the instrument; set-level rank balance",
                probe=_p_chain_slots,
            ),
            _req(
                "kinds",
                COPY,
                "chain_intermediates/judge.py:650-653,740-741,874",
                "absent: head_tie veto never fires (lenient)",
                absent=SILENT,
            ),
            _req("depth", COPY, "chain_intermediates/judge.py:339,761", absent=SILENT),
            _q("span from the start digit ('Qwen splits digits')", SUBJECT, "readplan.py:949-951"),
            _qwen_min_full(20, "chain_intermediates/__init__.py:28-31"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "arithmetic_intermediates",
        "evals/arithmetic_intermediates/judge.py",
        "none (re-read; generated rows stamp-only)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:969"),
            _req(
                "variant", COPY, "arithmetic_intermediates/judge.py:552,844", probe=_p_arith_variant
            ),
            _req(
                "cell",
                SUBJECT,
                "arithmetic_intermediates/judge.py:396-404",
                "{layer, pos}: a Qwen (layer, chat-tail offset) cell re-derived per subject",
            ),
            _req("intermediates", COPY, "arithmetic_intermediates/judge.py:76,421"),
            _req("tolerance", COPY, "arithmetic_intermediates/judge.py:75,849"),
            _req("role", COPY, "arithmetic_intermediates/judge.py:553"),
            _req("expr", COPY, "arithmetic_intermediates/judge.py:554,653"),
            _req(
                "null_set",
                BUILD,
                "arithmetic_intermediates/judge.py:424,516,529-532",
                "names in the LOADED bank; unresolved names silently dropped",
            ),
            _req("operands", COPY, "arithmetic_intermediates/judge.py:686", absent=SILENT),
            _h("variants", EXIT, COPY, "arithmetic_intermediates/judge.py:595,883", required=True),
            _q("cell.pos -7/-8 = Qwen chat-tail offsets", SUBJECT, "items.json header read"),
            _qwen_min_full(34, "arithmetic_intermediates/__init__.py:27-29"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "buggy_code",
        "evals/buggy_code/{judge,prompts}.py",
        "upgrade + profile (twins)",
        "dict",
        "name",
        (
            _NAME,
            _req("code", COPY, "readplan.py:988; buggy_code/prompts.py:168"),
            _req("lang_group", COPY, "buggy_code/judge.py:268,361; readplan.py:992"),
            _req("src", COPY, "buggy_code/judge.py:226,472", "buggy | clean"),
            _i(
                "twin",
                SILENT,
                HAZARD,
                "buggy_code/judge.py:60-73,460-466",
                "symmetric by name; absent = orphan, out of pair_rate (no adapted set has it)",
            ),
            _i("consequence_class", SILENT, COPY, "buggy_code/judge.py:362"),
            _i("cause", SILENT, BUILD, "buggy_code/prompts.py:134-140", "Stage B grading text"),
            _i("why_correct", SILENT, BUILD, "buggy_code/prompts.py:134-140", "clean twins"),
            _i("looks_like", SILENT, BUILD, "buggy_code/prompts.py:134-140"),
            _i("bug_line", SILENT, BUILD, "buggy_code/prompts.py:162-163", "buggy items"),
            _i("language", SILENT, COPY, "buggy_code/prompts.py:167", "absent = '?'"),
            _i("verified", SILENT, BUILD, "buggy_code/prompts.py:169", "absent = '?'"),
            _h(
                "read_cells",
                EXIT,
                SUBJECT,
                "buggy_code/judge.py:268-276; readplan.py:992",
                "subject layers; lite_layers double-remapped by plan() (A1.8)",
                required=True,
            ),
            _rule(
                "-au- / -au-clean- twin ids",
                NA,
                BUILD,
                "adapt/author.py:308; adapt/run.py:271-273",
                "adapt tooling only; the judge pairs by `twin`",
            ),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "relational_multihop",
        "evals/relational_multihop/{judge,gate,score}.py",
        "none (re-read)",
        "list",
        "id",
        (
            _ID,
            _req(
                "stimulus",
                COPY,
                "readplan.py:390-403,905-907",
                "'. In other words' exactly once",
            ),
            _req("hop1", COPY, "relational_multihop/judge.py:76-77,138,416", "a NEAR key"),
            _req("hop2", COPY, "relational_multihop/judge.py:76-77,138,416", "a NEAR key"),
            _req("scene", COPY, "relational_multihop/score.py:94"),
            _rule(
                "rel-{scene}-a / -b",
                SILENT,
                HAZARD,
                "relational_multihop/score.py:95",
                "pair_consistency (report-only)",
                probe=_p_rel_pair_id,
            ),
            _q('BLANK_TOKEN "\'s"', SUBJECT, "relational_multihop/judge.py:169-187"),
            _qwen_min_full(8, "relational_multihop/__init__.py:23-25"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "poetry",
        "evals/poetry/{judge,options}.py",
        "rebuild (v5)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "readplan.py:756-797"),
            _req("intermediates", SUBJECT, "poetry/options.py:22-23", "the subject's word"),
            _req(
                "mc.candidates",
                SUBJECT,
                "poetry/options.py:131-150; judge.py:368",
                "absent, or < N_DISTRACTORS left after the gold and qwen_commits are removed: "
                "ValueError before any cell (whole run)",
                probe=_p_poetry_distractors,
            ),
            _req(
                "qwen_commits",
                SUBJECT,
                "poetry/options.py:74-76,117",
                "the SUBJECT's commitments under this key; absent: not excluded from options",
                absent=SILENT,
            ),
            _req("line_one_end", BUILD, "poetry/options.py:26-33", absent=FALLBACK),
            _i("spellings", SILENT, BUILD, "poetry/judge.py:390-391", "optional extra forms"),
            _i(
                "gate_variant",
                SILENT,
                SUBJECT,
                "readplan.py:766",
                "honoured only with a truthy `adapt` block",
            ),
            _i("prompt_only_opus", NA, SUBJECT, "-", "per-item record (SUBJECT_FIELDS)"),
            _i("regate", NA, SUBJECT, "-", "regate.site_words (SUBJECT_FIELDS)"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "moral_rationale",
        "evals/moral_rationale/{judge,score}.py",
        "rebuild (re-key, v3)",
        "list",
        "id",
        (
            _ID,
            _req("stimulus", SUBJECT, "readplan.py:870-895", "reasons in the read conversation"),
            _req("question", COPY, "moral_rationale/judge.py:207-208,979"),
            _req(
                "reason_class",
                SUBJECT,
                "moral_rationale/judge.py:255; score.py:92-102",
                "non-'committed' = deliberative",
            ),
            _req(
                "bank_version",
                BUILD,
                "moral_rationale/judge.py:100-106; readplan.py:872-877",
                "absent = v1 instrument",
                absent=FALLBACK,
                probe=_p_moral_version,
            ),
            _req(
                "options",
                SUBJECT,
                "moral_rationale/judge.py:211-233,251-285,643-655",
                "absent in a v3 bank: gold + cannot-tell only",
                absent=FALLBACK,
            ),
            _req("topic_id", COPY, "moral_rationale/score.py:47-50", absent=SILENT),
            _i("gate_pass", SILENT, SUBJECT, "moral_rationale/score.py:39", "diagnostics"),
            _i("system", SILENT, COPY, "readplan.py:870-895"),
            _i("look_for_reasons", NA, SUBJECT, "moral_rationale/judge.py:130-174", "v1 only"),
            _i(
                "reasons",
                NA,
                SUBJECT,
                "moral_rationale/judge.py:255-268",
                "v1 path only; the subject's distilled reasons (rekey / adopt)",
            ),
            _i("subject_answer", NA, SUBJECT, "-", "adapt-time (SUBJECT_FIELDS)"),
            _q("lite last_n 5 = Qwen assistant header", SUBJECT, "readplan.py:888-893"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "agentic_misalignment",
        "evals/agentic_misalignment/{judge,score}.py",
        "carry + twins (D5)",
        "dict",
        "id",
        (
            _ID,
            _req("arm", COPY, "agentic_misalignment/score.py:305-313", "unknown = control"),
            _req("category", COPY, "agentic_misalignment/judge.py:531,557"),
            _req("group", COPY, "agentic_misalignment/judge.py:533"),
            _req("text", COPY, "readplan.py:1039-1054"),
            _req("system", COPY, "agentic_misalignment/judge.py:180-181", absent=SILENT),
            _i("twin", SILENT, BUILD, "agentic_misalignment/score.py:161-175", "pairs"),
            _i(
                "twin_rule",
                SILENT,
                BUILD,
                "agentic_misalignment/judge.py:419,500,660; prompts.py:391-396",
                "twin arm: 'object' adds TWIN_RULE_OBJECT to the Stage C prompt; absent = the "
                "plain twin prompt",
                probe=_p_agentic_twin_rule,
            ),
            _i(
                "cluster",
                SILENT,
                BUILD,
                "agentic_misalignment/score.py:250,366",
                "the cluster_bootstrap unit of the headline pair-rate CI; absent = the item's "
                "own id, so related scenarios count as independent and the CI silently narrows",
            ),
            _i("low_power", SILENT, BUILD, "agentic_misalignment/score.py:252", "report-only"),
            _i("misalignment_rate", SILENT, SUBJECT, "agentic_misalignment/score.py:81-85"),
            _r(
                "evals/agentic_misalignment/targets_v2.json",
                EXIT,
                BUILD,
                "agentic_misalignment/judge.py:71-105",
                "keyed by id; an adapted bank always reads the REGISTERED file",
                probe=_p_agentic_target,
            ),
            _qwen_min_full(64, "agentic_misalignment/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "jailbreak_recognition",
        "evals/jailbreak_recognition/{judge,score}.py",
        "carry + control re-screen",
        "dict",
        "id",
        (
            _ID,
            _req("messages", COPY, "jailbreak_recognition/judge.py:53-56,150-160"),
            _req("read.span", SUBJECT, "jailbreak_recognition/judge.py:80-123"),
            _req("read.tokens", SUBJECT, "jailbreak_recognition/judge.py:153,314-320"),
            _req("read.turn_end", SUBJECT, "jailbreak_recognition/judge.py:126-135"),
            _req("read.n_tokens", SUBJECT, "readplan.py:1029"),
            _req(
                "kind",
                COPY,
                "jailbreak_recognition/judge.py:323-325; score.py:52-53",
                "absent = 'jailbreak' (controls must say control)",
                absent=SILENT,
            ),
            _i("template_id", SILENT, COPY, "jailbreak_recognition/score.py:186", "CI cluster"),
            _i("twin_of", SILENT, COPY, "jailbreak_recognition/score.py:226-236"),
            _q("read.* = Qwen token indices / <|im_end|>", SUBJECT, "readplan.py:1029-1036"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "jlens_concept_pr",
        "evals/jlens_concept_pr/judge.py (items = manifest prompts)",
        "verify (regenerated on the subject)",
        "manifest",
        "label",
        (
            _req("label", BUILD, "jlens_concept_pr/judge.py:144-173"),
            _req("family", BUILD, "jlens_concept_pr/judge.py:169-173", "chat | pt"),
            _req("eval_positions", SUBJECT, "jlens_concept_pr/judge.py:144-149"),
            _req("n_pos", SUBJECT, "readplan.py:1075-1109"),
            _h("model_id", NA, SUBJECT, "manifest.json", required=True),
            _h("layers", NA, SUBJECT, "manifest.json", required=True),
            _r(
                "<bank_dir>/gen-jlens-pr-jlens/<label>/L<layer>.jsonl",
                EXIT,
                SUBJECT,
                "jlens_concept_pr/judge.py:104-105,156-236",
                "the subject's J-lens reference; a file with no row at the eval position = "
                "[] = zero score (silent)",
            ),
            _r(
                "items.json input_ids / prompt_len",
                SILENT,
                SUBJECT,
                "readplan.py:1075-1109",
                "a label missing there gets a plan row without ids",
            ),
            _r(
                "foil derangement over ALL manifest labels",
                SILENT,
                HAZARD,
                "jlens_concept_pr/judge.py:123-137",
                "adding labels reshuffles every item's foil partner",
            ),
            _q("byte-level BPE display tokens", SUBJECT, "jlens_concept_pr/judge.py:115-120"),
        ),
    )
)

_add(
    FamilyInputs(
        "unverbalized_hint",
        "evals/unverbalized_hint/judge.py",
        "retired (plan 0058)",
        "dict",
        "name",
        (
            _NAME,
            _req("pair_id", COPY, "unverbalized_hint/judge.py:184-196"),
            _req("role", SUBJECT, "unverbalized_hint/judge.py:184-196", "I/N from Qwen behaviour"),
            _req("positions", SUBJECT, "unverbalized_hint/judge.py:525", "Qwen token indices"),
            _req("text", COPY, "readplan.py:1056-1073"),
            _req(
                "hint", COPY, "unverbalized_hint/judge.py:172-173", absent=SILENT, probe=_p_uvh_hint
            ),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "hinted_cutoff",
        "evals/hinted_cutoff/judge.py",
        "model-specific (plan 0063)",
        "dict",
        "name",
        (
            _NAME,
            _req("pair_id", COPY, "hinted_cutoff/judge.py:pairs_of"),
            _req("role", SUBJECT, "hinted_cutoff/judge.py:pairs_of", "I/N from Qwen behaviour"),
            _req("cluster", COPY, "hinted_cutoff/judge.py:pairs_of", "I-twin event cluster"),
            _req("positions", SUBJECT, "hinted_cutoff/judge.py:run", "Qwen prompt token indices"),
            _req("text", COPY, "readplan.py hinted_cutoff branch"),
            _req("input_ids", SUBJECT, "readplan.py hinted_cutoff branch", "prompt-only ids"),
            _req("n_prompt", SUBJECT, "readplan.py hinted_cutoff branch"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "knowledge_cutoff",
        "evals/knowledge_cutoff/judge.py",
        "model-specific (Phase E)",
        "dict",
        "id",
        (
            _ID,
            _req("user", COPY, "readplan.py:823; knowledge_cutoff/judge.py:155-161"),
            _req(
                "options",
                BUILD,
                "knowledge_cutoff/judge.py:150,476",
                "exactly 5",
                probe=_p_kc_options,
            ),
            _req(
                "gold",
                SUBJECT,
                "knowledge_cutoff/judge.py:159",
                "the subject's stable wrong answer",
            ),
            _req("option_units", BUILD, "knowledge_cutoff/judge.py:151"),
            _i("question", FALLBACK, COPY, "knowledge_cutoff/judge.py:162", "else user"),
            _i("truth.canonical", SILENT, COPY, "knowledge_cutoff/judge.py:546"),
            _i("label_type", SILENT, SUBJECT, "knowledge_cutoff/judge.py:658-660"),
            _i("stratum", SILENT, COPY, "knowledge_cutoff/judge.py:658-660"),
            _r(
                "evals/knowledge_cutoff/obscure_items.json (nocot)",
                NA,
                SUBJECT,
                "nocot.py:16; readplan.py:1112-1117",
                "Qwen's labels; off under WSB_BANK_ROOT, but NOT under WSB_BANK_FILE_*",
            ),
            _qwen_min_full(4, "knowledge_cutoff/__init__.py"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "nyt_connections",
        "evals/nyt_connections/judge.py",
        "model-specific (Phase E)",
        "dict",
        "id",
        (
            _ID,
            _req(
                "nyt_id",
                COPY,
                "nyt.py (bank_items, words, render); readplan.py (_nyt_rows)",
                "the NYT puzzle number; words and NYT labels are fetched from the pinned mirror",
            ),
            _req(
                "mc",
                SUBJECT,
                "evals/nyt_connections/judge.py (slot_options, _run_summary, rows)",
                "one slot per Qwen group: members (indices into the shuffled 16), Qwen's "
                "follow-up label, stability over 16 samples, stable / correct / gold_same / "
                "model_specific, and the frozen option list (same-connection filter applied)",
            ),
            _r(
                "Eyefyre/NYT-Connections-Answers connections.json @0c42b26 (sha256-pinned)",
                EXIT,
                COPY,
                "nyt.py (fetch, puzzles)",
                "ids-only bank: text only at plan time; WSB_NO_NYT -> no rows",
            ),
            _qwen_min_full(12, "nyt_connections/__init__.py"),
            _GRID,
        ),
        note="plan 0062: every slot, label and stability is Qwen3.6-27B's own; a new subject "
        "re-samples its answers and naming turn and rebuilds the options (`adapt "
        "nyt_connections`, plan 0060 Phase E). The judge looks nothing up by registered id: "
        "an adapted item is read from $WSB_BANK_ROOT and resolved against the mirror by nyt_id",
    )
)

_add(
    FamilyInputs(
        "wrong_intermediate",
        "evals/wrong_intermediate/judge.py",
        "model-specific (Phase E)",
        "dict",
        "name",
        (
            _NAME,
            _req("prompt", COPY, "wrong_intermediate/judge.py:290-303,405", probe=_p_wb),
            _req(
                "readout",
                COPY,
                "readplan.py:487-494",
                "absent: final_token full read",
                absent=FALLBACK,
            ),
            _req("mc.order", BUILD, "wrong_intermediate/judge.py:49,277,282", "exactly 6"),
            _req(
                "mc.gold",
                SUBJECT,
                "wrong_intermediate/judge.py:283,332",
                "the subject's wrong intermediate",
            ),
            _req("mc.contrast", COPY, "wrong_intermediate/judge.py:283,361"),
            _req("mc.forms", BUILD, "wrong_intermediate/judge.py:331,359"),
            _qwen_min_full(9, "wrong_intermediate/__init__.py:24-25"),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "model_specific_directed_modulation",
        "evals/model_specific_directed_modulation/{judge,controls}.py",
        "model-specific (Phase E)",
        "dict",
        "id",
        (
            _ID,
            _req("topic", COPY, "model_specific_directed_modulation/judge.py:181"),
            _req("carrier", COPY, "readplan.py:839-842"),
            _req("user", COPY, "readplan.py:841", "must equal render_user(topic, carrier)"),
            _req(
                "gold", SUBJECT, "model_specific_directed_modulation/judge.py:78-80", "own default"
            ),
            _req(
                "options",
                SUBJECT,
                "model_specific_directed_modulation/judge.py:54,79",
                probe=_p_msdm_options,
            ),
            _req("option_units", SUBJECT, "model_specific_directed_modulation/judge.py:54"),
            _q(
                "MIN_CARRIER_TOKENS=7 (Qwen tokens)",
                SUBJECT,
                "model_specific_directed_modulation/judge.py:28",
            ),
            _GRID,
        ),
    )
)

_add(
    FamilyInputs(
        "introspection",
        "evals/introspection/judge.py",
        "model-specific (Phase E)",
        "dict",
        "id",
        (
            _ID,
            _req("kind", COPY, "introspection/judge.py", "inject | gaussian | cross"),
            _req("prompt_kind", COPY, "introspection/judge.py:510", "protocol | neutral"),
            _req("prompt_key", COPY, "readplan.py:1154"),
            _req("beta", COPY, "readplan.py:1157", "headline = protocol and 4.0"),
            _req("vector", SUBJECT, "readplan.py:1157-1166", "row into the subject's vectors"),
            _req("concept", COPY, "introspection/judge.py:445-461"),
            _req("cluster", COPY, "introspection/judge.py:445-461"),
            _req("gold", COPY, "introspection/judge.py:445-461"),
            _req("options", COPY, "introspection/judge.py:445-461", "[{label}]"),
            _req(
                "readout_of",
                COPY,
                "introspection/judge.py:445-461; readplan.py:1148-1150",
                "the readout an item is judged on (cross items: the partner's)",
            ),
            _i(
                "twins",
                SILENT,
                BUILD,
                "introspection/judge.py:484-488,1058-1063",
                probe=_p_intro_twins,
            ),
            _h(
                "renders",
                EXIT,
                SUBJECT,
                "readplan.py:1154-1180",
                "Qwen input_ids / spans",
                required=True,
            ),
            _h(
                "spec.inject_layer",
                EXIT,
                SUBJECT,
                "readplan.py:1159",
                "not remapped by plan()",
                required=True,
            ),
            _h("vector_recipe", EXIT, SUBJECT, "readplan.py:1160-1164", required=True),
            _h(
                "vectors",
                EXIT,
                SUBJECT,
                "readplan.py:1146; produce/producer.py:154-162",
                "relative paths resolve under REPO_ROOT (Qwen's .npy)",
                required=True,
            ),
            _h("concepts", EXIT, COPY, "introspection/judge.py:85-101", required=True),
            _h("equivalents", SILENT, COPY, "introspection/judge.py:72-74,306"),
            _h("beta0_rows", EXIT, BUILD, "readplan.py:1153; judge.py:424", required=True),
            _GRID,
        ),
    )
)


# ------------------------------------------------------------------------- derived constants


def _top(path: str) -> str:
    return path.split(".", 1)[0].removesuffix("[]")


REQUIRED_ITEM_FIELDS: dict[str, tuple[str, ...]] = {
    f: tuple(dict.fromkeys(_top(x.name) for x in fi.inputs if x.kind == "item" and x.required))
    for f, fi in FAMILIES.items()
}
"""Per family, the top-level item keys every item of an adapted bank must carry (plan 0060
A1.1: freeze refuses a family whose items lack them). Header keys are separate
(``REQUIRED_HEADER_FIELDS``); keys only adapted-only items need are ``ADAPTED_ONLY_FIELDS``."""

REQUIRED_ITEM_PATHS: dict[str, tuple[str, ...]] = {
    f: tuple(x.name for x in fi.inputs if x.kind == "item" and x.required)
    for f, fi in FAMILIES.items()
}

ADAPTED_ONLY_FIELDS: dict[str, tuple[str, ...]] = {
    f: tuple(x.name for x in fi.inputs if x.kind == "item" and x.adapted_only)
    for f, fi in FAMILIES.items()
}

REQUIRED_HEADER_FIELDS: dict[str, tuple[str, ...]] = {
    f: tuple(x.name for x in fi.inputs if x.kind == "header" and (x.required or x.adapted_only))
    for f, fi in FAMILIES.items()
}

SUBJECT_FIELDS: dict[str, tuple[str, ...]] = {
    f: tuple(
        dict.fromkeys(_top(x.name) for x in fi.inputs if x.kind == "item" and x.cls == SUBJECT)
    )
    for f, fi in FAMILIES.items()
}
"""Per family, the item keys whose value is the SUBJECT's (re-derived on the subject; freeze
overlays them on the registered item instead of copying them verbatim, plan 0060 A1.1). A
superset of A1.1's named per-family list: it also holds the own-answer golds and the
tokenizer-tied fields (``probe_token_lens``, ``read``, ``cell``, ``readout`` offsets) that the
restamp step re-derives. basic_readout's ``mc`` is subject for its implicit items only (the
restamp rewrites it there); entity / processing items keep the registered block."""


# -------------------------------------------------------------------------------- check_item


def uncovered_families() -> list[str]:
    """Registered families with no entry in :data:`FAMILIES` (must be empty: a new family is
    audited before it can be adapted)."""
    registry.load_all()
    return sorted(set(registry.FAMILIES) - set(FAMILIES))


def check_item(
    family: str,
    item: Mapping[str, Any],
    header: Mapping[str, Any] | None = None,
    *,
    registered: bool | None = None,
    adapted_bank: bool = True,
) -> list[str]:
    """What ``item`` (of an adapted bank of ``family``, with that bank's ``header``) lacks for
    its judge to take the same code path as on a registered item. ``registered`` (default: the
    item's id is in the registered bank) decides whether ``adapted_only`` inputs are needed.
    Header checks run only when ``header`` is given (a bare-list bank has none: pass None);
    ``adapted_only`` header keys (``contract.native_langs``) only when ``adapted_bank``.
    An unknown family raises KeyError (the table must cover every registered family)."""
    fi = FAMILIES[family]
    if registered is None:
        registered = item_id(item) in registered_ids(family)
    probs: list[str] = []
    for x in fi.inputs:
        needed = x.required or (x.adapted_only and not registered)
        if x.kind == "item" and needed and not has_path(item, x.name):
            why = x.note or ("judge exits" if x.absent == EXIT else f"{x.absent} default")
            probs.append(f"missing: {x.name}: {x.absent} ({x.where}; {why})")
            continue
        if x.kind == "header":
            if header is None:
                continue
            needed = x.required or (x.adapted_only and adapted_bank)
            if needed and not has_path(header, x.name):
                probs.append(f"missing: header.{x.name}: {x.absent} ({x.where})")
                continue
        if x.probe is not None:
            got = x.probe(item, header or {}, registered)
            if got:
                probs.append(got)
    return list(dict.fromkeys(probs))


def _bank_dm(items: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    """directed_modulation draws each item's distractors from the LOADED bank's same-subfamily
    concepts outside the gold's relatedness group; fewer than N_DISTRACTORS raises."""
    from wsbench.evals.directed_modulation.judge import _groups
    from wsbench.evals.directed_modulation.prompts import N_DISTRACTORS

    groups = _groups()
    by_sub: dict[str, set[str]] = {}
    for it in items:
        by_sub.setdefault(str(it.get("subfamily")), set()).add(str(it.get("concept")))
    out: dict[str, list[str]] = {}
    for it in items:
        gold = str(it.get("concept"))
        if gold not in groups:
            continue  # reported per item
        ok = [
            c
            for c in by_sub[str(it.get("subfamily"))] - {gold}
            if groups.get(c, f"?{c}") != groups[gold]
        ]
        if len(ok) < N_DISTRACTORS:
            out[item_id(it)] = [
                f"exit: option draw: only {len(ok)} unrelated same-subfamily concepts for "
                f"{gold!r} in this bank (need {N_DISTRACTORS}; judge.py:101-102 ValueError)"
            ]
    return out


def _bank_uvh(items: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    """unverbalized_hint ``pairs_of`` needs exactly one I and one N item per pair_id."""
    by: dict[str, list[Mapping[str, Any]]] = {}
    for it in items:
        by.setdefault(str(it.get("pair_id")), []).append(it)
    out: dict[str, list[str]] = {}
    for pid, members in by.items():
        roles = [str(m.get("role")) for m in members]
        if sorted(roles) != ["I", "N"]:
            for m in members:
                out[item_id(m)] = [
                    f"exit: pair {pid!r} has roles {sorted(roles)}, need exactly one I and one N "
                    "(judge.py:184-196 ValueError)"
                ]
    return out


BANK_CHECKS: dict[str, Callable[[list[Mapping[str, Any]]], dict[str, list[str]]]] = {
    "directed_modulation": _bank_dm,
    "unverbalized_hint": _bank_uvh,
    "hinted_cutoff": _bank_uvh,  # the same one-I-one-N-per-pair rule (hinted_cutoff.pairs_of)
}
"""Checks over a whole bank (a draw over the loaded items), run by :func:`check_bank`."""


def _bank_duplicate_ids(family: str, items: list[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Every family: an item id occurring twice. A name-keyed bank's ``banks.load_bank`` raises
    on two names sharing a ``label_of`` label (banks.py:26-31); an id-keyed judge builds
    ``by_id`` dicts and silently keeps one of them."""
    key = FAMILIES[family].id_key
    counts: dict[str, int] = {}
    for it in items:
        iid = label_of(str(it.get("name", ""))) if key == "name" else str(it.get(key, ""))
        counts[iid] = counts.get(iid, 0) + 1
    how = "exit (banks.load_bank raises)" if key == "name" else "hazard (by_id keeps one silently)"
    return {
        iid: [f"{how.split(' ')[0]}: duplicate item id {iid!r} ({n} items; {how})"]
        for iid, n in counts.items()
        if n > 1
    }


def check_bank(family: str, header: Mapping[str, Any] | None, items: list[Mapping[str, Any]]):
    """``{item id: problems}`` for every item of a bank with at least one problem: the per-item
    :func:`check_item`, the duplicate-id check (every family) and the family's bank-level
    :data:`BANK_CHECKS`."""
    out: dict[str, list[str]] = {}
    for it in items:
        if got := check_item(family, it, header):
            out[item_id(it)] = got
    extra = [_bank_duplicate_ids(family, items)]
    if family in BANK_CHECKS:
        extra.append(BANK_CHECKS[family](items))
    for found in extra:
        for iid, probs in found.items():
            out[iid] = list(dict.fromkeys([*out.get(iid, []), *probs]))
    return out


# ------------------------------------------------------------------------------ markdown view

DOC_BEGIN = "<!-- judge_inputs table: generated by wsbench.adapt.judge_inputs.render_markdown -->"
DOC_END = "<!-- end judge_inputs table -->"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown() -> str:
    """The per-family tables of ``docs/adapt_judge_inputs.md`` (between DOC_BEGIN / DOC_END;
    ``tests/test_adapt_judge_inputs.py`` keeps the file in sync)."""
    out = [DOC_BEGIN, ""]
    for f in sorted(FAMILIES):
        fi = FAMILIES[f]
        out += [f"### {f}", ""]
        out.append(
            f"Judge: `{fi.judge}`. Refresh: {fi.mode}. Bank: {fi.shape}, id from `{fi.id_key}`."
        )
        if fi.note:
            out.append(f"Note: {fi.note}")
        req = ", ".join(f"`{k}`" for k in REQUIRED_ITEM_FIELDS[f]) or "-"
        out.append(f"REQUIRED_ITEM_FIELDS: {req}.")
        if SUBJECT_FIELDS[f]:
            out.append("SUBJECT_FIELDS: " + ", ".join(f"`{k}`" for k in SUBJECT_FIELDS[f]) + ".")
        if ADAPTED_ONLY_FIELDS[f]:
            out.append(
                "Adapted-only items also need: "
                + ", ".join(f"`{k}`" for k in ADAPTED_ONLY_FIELDS[f])
                + "."
            )
        if REQUIRED_HEADER_FIELDS[f]:
            out.append("Header: " + ", ".join(f"`{k}`" for k in REQUIRED_HEADER_FIELDS[f]) + ".")
        out += [
            "",
            "| kind | input | req | if absent | class | where | note |",
            "|---|---|---|---|---|---|---|",
        ]
        for x in fi.inputs:
            req_s = "yes" if x.required else ("adapted" if x.adapted_only else "")
            note = x.note + (" (checked)" if x.probe else "")
            out.append(
                f"| {x.kind} | `{_cell(x.name)}` | {req_s} | {x.absent} | {x.cls} | "
                f"{_cell(x.where)} | {_cell(note)} |"
            )
        out.append("")
    out.append(DOC_END)
    return "\n".join(out) + "\n"
