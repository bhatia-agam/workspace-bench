"""The blind bank MC judge of the single-token basic families (plan 0048 C3; the design is
basic_readout.md C3): per-item options frozen in the bank, shuffled, ``cannot tell`` last; the
judge sees a TASK TYPE line, the readout and the options, never the item's prompt or answer.

A family opts in through ``basic.family.MC_BANK_FAMILIES`` and supplies, in its own
``wsbench.evals.<family>.prompts``, an ``MC`` :class:`MCStrings` (question, rules, cannot-tell
text). Its bank items carry ``mc = {bridge_type, gold, aliases, distractors}``.

Verdict: ``correct`` iff the letter is the gold option AND ``digest.quote_ok`` verifies the quote
against the readout lines (``col.evidence`` in summary mode, ``digest.native_lines`` natively)
AND ``mc.form_in`` finds the gold, a listed alias or a derived form of the frozen table (not part
of the final answer; :func:`gold_forms`) in the quote (a ``number`` bridge: its value is among
``numerals.numbers_in(quote)``), also in the quote's line context (a prose quote widened to word
boundaries; a CJK form followed by a demonym / language suffix never counts) AND the quote names
no other shown option (:func:`names_other`) AND, for a ``number`` bridge,
the quote is not supported only by number-flood lines (``digest.number_flood``, whole samples
only) AND not only by ranked token lists that also hold another shown option (the shared token
note, held in code for token lines by :func:`_holds_other`: a ``number`` bridge compares by
value, so ``eight`` / 八 is the shown option 8; other types match the option string and its
bank-listed ``distractor_aliases``, so 法国 is France). ``cannot_tell`` / ``distractor`` /
``invalid`` fail; a failed call is undecided.
Summary mode (default): one call per item on its digest. Native: one call per (item, layer),
any-layer pass, with ``mcjudge.layer_pick_columns`` beside the number."""

import importlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from wsbench import digest, mc, numerals, reads, registry
from wsbench.banks import load_bank
from wsbench.cache import Cache
from wsbench.family import fail, pass_rate_result, require_cells, tri_state
from wsbench.llm import JudgeConfigError, Spend, schema_block
from wsbench.mcjudge import (
    Call,
    Preflighter,
    item_scope,
    layer_pick_columns,
    run_calls,
    with_readout_count,
)
from wsbench.nearquote import close_lines, continued, cuts, sample_end_prefix
from wsbench.readouts import Cell
from wsbench.registry import JudgeArgs
from wsbench.results import FamilyResult
from wsbench.split import layer_protocols

LETTERS = "ABCDEFGH"
# the deterministic gate's own stamp (config.gate): a gate edit re-scores cached verdicts, so it
# leaves the prompt version (and every cached call) alone. r3: element-index + split rules;
# r4: the element-index test reads an ordinal naming ("8th") and the quote's clause in its
# support line ("...the 8th word ..., when located on the periodic table, is Oxygen");
# r5: those two r4 widenings apply to the nhop-*-element items only, and the line clause does not
# count when the quote is its counted half and the rest names the value again ("a cube has 6
# faces so the element with atomic number 6 is carbon");
# r6: the split rule's sentence break also falls after a bold / italic close that follows the
# sentence end ("...built the Great Wall.** The country that built the Great Pyramid of Giza is
# **the United States**" is two sentences; review 2 of PR #214)
# r7 (an unreleased draft): the split rule is removed; the quote's form check accepts the frozen
# table's derived forms (not part of the final answer) and fails a quote naming another shown
# option. Since r7 the gate version is part of the family's result stamp
# (basic.prompts.FAMILY_PROMPT_VERSIONS), while the MC calls keep CALL_VERSIONS as their key
# r8 (an unreleased draft): a near-verbatim quote (nearquote.close_lines) is read where it matched
# (near_block), and a quote that does not name the gold itself passed when its line named the gold
# and no other shown option
# r9: such a quote passes only when it was cut mid-name: its line continues it into the gold
# (continued_quote, nearquote.continued), the quote so run on naming the gold and no other shown
# option, or the quote ends its sample and its trailing words begin forms of the gold and of no
# other shown option (nearquote.sample_end_prefix)
# r10: the derived-forms table is mhforms-v2 (entries for the options of bank v5's 30 new items;
# every earlier entry unchanged, so no earlier bank's verdict moves). Gate code unchanged
GATE_VERSION = "bank-gate-r10"
# the MC calls' cache key per family: the judge's prompts are unchanged since this version, so a
# gate-only stamp change re-scores the cached answers instead of re-asking them
CALL_VERSIONS: dict[str, str] = {"multihop": "bank-mc-2026-11-01-v3"}
CHANCE_LABEL = (
    "1 in 5 options per judge call (cannot-tell excluded); the native any-layer rule's floor is "
    "higher (see extras layer_pick_columns)"
)


@dataclass(frozen=True)
class MCStrings:
    """A family's own strings for this judge (its ``prompts.MC``)."""

    question: str
    rules: str  # extra "- " rule lines, added to the shared rules
    cannot: str = mc.CANNOT


SYSTEM_MC = """You are judging readouts of a language model's internal activations for an
interpretability benchmark. You get one eval item: a TASK TYPE line (the kind of task the model
was doing while the readouts were taken, never the item itself), the readout, one question and
lettered options. You are not told the item's text or its answer.

Pick the ONE option the readout names, by these rules:
- Judge only what is written in the readout. Do not use your own knowledge of the task to work
  out which option is right.
{rules}
- The last option is the cannot-tell option: choose it whenever the rules single out no option.
- Every other pick must include a VERBATIM quote copied exactly from ONE readout sample (from a
  ranked token list: one token, or several tokens of that same line joined by " | "): the
  shortest span that names the option. No quote, no pick.
Return JSON: {"choice": "<letter>", "quote": "<verbatim span, empty for cannot tell>"}."""

NATIVE_NOTE = (
    "The readout below holds the samples read at one layer: one block per token position, one "
    "sample per line."
)
USER_MC = (
    "TASK TYPE: {task_type}\n{kind_note}\n\nREADOUT:\n{readout}\n\nQUESTION: {question}\n{options}"
)
BLOCK_MC = "[position {pos}]\n{lines}"

SCHEMA = schema_block(
    "basic_mc_verdict",
    {"choice": {"type": "string"}, "quote": {"type": "string"}},
    ["choice", "quote"],
)

PROMPTS: dict[str, str] = {
    "SYSTEM_MC": SYSTEM_MC,
    "NATIVE_NOTE": NATIVE_NOTE,
    "USER_MC": USER_MC,
    "BLOCK_MC": BLOCK_MC,
}


def strings_of(family: str) -> MCStrings:
    s = importlib.import_module(f"wsbench.evals.{family}.prompts").MC
    if not isinstance(s, MCStrings):
        raise TypeError(f"{family}: prompts.MC must be an MCStrings")
    return s


def system_of(family: str) -> str:
    return SYSTEM_MC.replace("{rules}", strings_of(family).rules.rstrip("\n"))


def options_of(family: str, item: dict[str, Any]) -> tuple[list[str], int]:
    """(shown options incl. the cannot-tell line LAST, 0-based gold index). Gold + distractors
    are shuffled with ``mc.seeded_shuffle(f"{family}|{id}")`` first; the escape is never
    shuffled in (``mc.options_with_cannot``)."""
    block = item.get("mc")
    if not isinstance(block, dict) or not block.get("gold") or not block.get("distractors"):
        fail(
            f"{family}/{item.get('id')}: bank item has no `mc` block (gold + distractors); "
            "this judge needs the frozen options (scripts/build_multihop_mc.py for multihop)"
        )
    content = [block["gold"], *block["distractors"]]
    shown = mc.options_with_cannot(
        mc.seeded_shuffle(content, f"{family}|{item['id']}"), cannot=strings_of(family).cannot
    )
    return shown, shown.index(block["gold"])


def render_options(shown: list[str]) -> str:
    return "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(shown))


def render_native(lines: list[digest.Line]) -> str:
    by_pos: dict[int, list[str]] = defaultdict(list)
    for ln in lines:
        by_pos[int(ln.pos or 0)].append(ln.text)
    return "\n\n".join(
        BLOCK_MC.replace("{pos}", str(p)).replace("{lines}", "\n".join(f"  {t}" for t in ts))
        for p, ts in sorted(by_pos.items())
    )


def render_user(
    task_type: str, kind_note: str, readout: str, question: str, shown: list[str]
) -> str:
    return (
        USER_MC.replace("{task_type}", task_type)
        .replace("{kind_note}", kind_note)
        .replace("{question}", question)
        .replace("{options}", render_options(shown))
        .replace("{readout}", readout)
    )


# a CJK country / place form followed by one of these is a demonym or a language name
# (日本人, 意大利语, 西班牙文, 广东话), not the place itself
_CJK_SUFFIX = frozenset("人语語话話文")


def _form_bounded(text: str, forms: list[str]) -> bool:
    """``mc.form_in`` with the CJK demonym / language guard: a CJK form counts only at an
    occurrence not followed by a :data:`_CJK_SUFFIX` character."""
    t = mc.fold(text)
    for f in forms:
        ff = mc.fold(f).strip()
        if not ff:
            continue
        if mc._CJK.search(ff):
            if any(
                t[m.end() : m.end() + 1] not in _CJK_SUFFIX for m in re.finditer(re.escape(ff), t)
            ):
                return True
        elif mc.form_in(text, [f]):
            return True
    return False


def _word_span(t: str, s: int, e: int) -> tuple[int, int]:
    """``[s, e)`` widened over adjacent word characters that are not CJK (CJK has no word
    breaks; its suffix guard is :func:`_form_bounded`)."""

    def wordy(c: str) -> bool:
        return (c.isalnum() or c == "_") and not mc._CJK.match(c)

    while s > 0 and wordy(t[s - 1]):
        s -= 1
    while e < len(t) and wordy(t[e]):
        e += 1
    return s, e


def _in_context(quote: str, ln: digest.Line, forms: list[str], value: int | None) -> bool:
    """The gold is named by ``quote`` where it occurs in ``ln``. Token lines hold whole tokens,
    so the quote is its own context there. In a prose line some occurrence of the quote,
    widened to word boundaries (plus one following character for the CJK guard), names the
    gold: a listed form (``value is None``) or a numeral overlapping the quote whose value is
    ``value`` (a CJK numeral run counts whole: 六 of 十六 is 16)."""
    if ln.pieces is not None:
        return True
    fq, t = digest.fold_quote(quote), digest.fold_quote(ln.text)
    if not fq:
        return False
    start = t.find(fq)
    while start >= 0:
        s, e = _word_span(t, start, start + len(fq))
        if value is not None:
            if any(ts < e and te > s and v == value for ts, te, v, _k in numerals.tokens(t)):
                return True
        elif _form_bounded(t[s : e + 1] if mc._CJK.match(t[e - 1 : e] or " ") else t[s:e], forms):
            return True
        start = t.find(fq, start + 1)
    return False


def _holds_other(pieces: Sequence[str], others: list[str], block: dict[str, Any]) -> bool:
    """A token list holds another shown option. A ``number`` bridge compares by value, in any
    script (``eight`` and 八 are the shown option 8). Other types match each option's string
    and its listed ``distractor_aliases`` (法国 is France), per token with the CJK suffix guard;
    a one-character CJK form only as the whole token (马 is horse, 马来西亚 is not); a
    multi-word form also over the list joined ("North | America")."""
    if block.get("bridge_type") == "number":
        values = {v for o in others if (v := numerals.word_value(o)) is not None}
        return any(numerals.numbers_in(t) & values for t in pieces)
    listed = block.get("distractor_aliases", {})
    return pieces_hold(pieces, [f for o in others for f in (o, *listed.get(o, ()))])


def pieces_hold(pieces: Sequence[str], forms: Sequence[str]) -> bool:
    """One token list names one of ``forms``: per token with the CJK suffix guard; a
    one-character CJK form only as the whole token (马 is horse, 马来西亚 is not); a multi-word
    form also over the list joined ("North | America")."""
    toks = [mc.fold(t).strip() for t in pieces]
    for f in forms:
        ff = mc.fold(f).strip()
        if not ff:
            continue
        if len(ff) == 1 and mc._CJK.match(ff):
            hit = ff in toks
        else:
            hit = any(_form_bounded(t, [f]) for t in pieces)
            hit = hit or (" " in ff and _form_bounded(" ".join(pieces), [f]))
        if hit:
            return True
    return False


# content-word stop list of the round-3 rules below
_STOP_WORDS = (
    "the and for are was its not but has had you his her one how why who can may now our out "
    "any all yes let get got via per say see that this with from have there which what when "
    "where these those also into than then they them their about would could should because "
    "while been being were will your only each such more most other some very just like does "
    "here same both after before over under first last number month year called known "
    "traditional official"
)
_STOP = frozenset(_STOP_WORDS.split())


# round 3 (assoc_multihop): an "element index" clause. In the nhop-*-element items the bridge
# number IS the answer element's atomic number, so a numeral read as an atomic number / periodic
# position ("Sodium's atomic number is 11", "element number 6", "the seventh element") reads the
# answer back; it never names the counted bridge ("11 players on a soccer team")
_ELEMENT_TEXT = (
    "atomic element elements periodic proton protons electron electrons isotope isotopes "
    "period periods group groups row rows position positions transition lanthanide actinide "
    "halogen noble metal metals"
)
ELEMENT_WORDS = frozenset(_ELEMENT_TEXT.split())
_CLAUSE = re.compile(r"[.;:!?\n\u205e,()\[\]\u2014\u2013|]+|\s-\s|\band\b|\bbut\b")
_MARKDOWN = re.compile(r"[*_#`>]+")
_WORDS = re.compile(r"[^\W\d_]+")


def clauses(text: str) -> list[str]:
    """``text`` folded, markdown dropped, cut into clauses (at punctuation, dashes, "and",
    "but")."""
    plain = _MARKDOWN.sub(" ", numerals.fold(text))
    return [c.strip() for c in _CLAUSE.split(plain) if c.strip()]


_ORDINAL_END = re.compile(r"(?:st|nd|rd|th)$")


def counted_clause(clause: str, value: int) -> bool:
    """``clause`` names ``value`` as a count, not as an element index: it names the value as a
    cardinal (not an ordinal: "the seventh color" is a position, "7th" too; not glued to a word
    by a hyphen: "carbon-6") and names no other numeral, has no element-index word
    (:data:`ELEMENT_WORDS`), and has at least one content word of >= 3 letters besides number
    words ("### 11" or "why is the 7" name nothing)."""
    toks = numerals.tokens(clause)
    t = numerals.fold(clause)
    if not toks or any(v != value for _s, _e, v, _k in toks):
        return False
    for s, e, _v, _k in toks:
        if _ORDINAL_END.search(t[s:e]) or re.match(r"(?:st|nd|rd|th)\b", t[e:]):
            return False
        if re.search(r"[^\W\d_]-$", t[:s]):
            return False
    words = [w for w in _WORDS.findall(t) if numerals.word_value(w) is None]
    if ELEMENT_WORDS & set(words):
        return False
    return any(len(w) >= 3 and w not in _STOP for w in words)


def _elem_words(clause: str) -> bool:
    return bool(
        ELEMENT_WORDS & {w for w in _WORDS.findall(clause) if numerals.word_value(w) is None}
    )


def _ordinal_only(clause: str, value: int) -> bool:
    """Every naming of ``value`` in ``clause`` is an ordinal ("8th", "the seventh"): a position,
    never the count the bridge is (every number bridge of the bank is a count)."""
    t = numerals.fold(clause)
    named = [(s, e) for s, e, v, _k in numerals.tokens(clause) if v == value]
    return bool(named) and all(
        bool(_ORDINAL_END.search(t[s:e]) or re.match(r"(?:st|nd|rd|th)\b", t[e:])) for s, e in named
    )


ELEMENT_ITEM = re.compile(r"^nhop-.+-element$")


ELEMENT_FLAG = "element_bridge"  # plan 0060 A2: the explicit flag of an adapted-only item


def element_item(item: Mapping[str, Any], family: str = "multihop") -> bool:
    """The item's number bridge IS its answer element's atomic number (``nhop-*-element``): the
    only items where the round-4 widenings (an ordinal-only naming, the quote's line clause) can
    read the answer back. Elsewhere "period", "rows", "group", "positions" name the counted thing
    ("12 hours in each period", "5 rings in two rows"; gate bank-gate-r5).

    A registered id keeps the id rule. Any other id takes its explicit ``element_bridge`` flag
    when the row carries one (plan 0060 A2); under ``WSB_BANK_ROOT`` an adapted-only
    number-bridge item without the flag is an error, never a silent id-rule miss."""
    iid = str(item.get("id", ""))
    if ELEMENT_FLAG in item and iid not in registry.registered_ids(family):
        return bool(item[ELEMENT_FLAG])
    if (item.get("mc") or {}).get("bridge_type") == "number" and registry.adapted_only(family, iid):
        raise SystemExit(
            f"{family}/{iid}: an adapted-only number-bridge item needs an explicit "
            f"{ELEMENT_FLAG!r} flag (true/false); the nhop-*-element id rule is for registered ids"
        )
    return bool(ELEMENT_ITEM.match(iid))


def _counted_half(line_clause: str, clause: str, value: int) -> bool:
    """``clause`` is a :func:`counted_clause` and the part of ``line_clause`` outside it names
    ``value`` again: the element word belongs to that other naming, and the quote is the counted
    half of a count-to-element chain ("a cube has 6 faces so the element with atomic number 6 is
    carbon" with the quote "a cube has 6 faces"). A bare "7" (no content word) never."""
    if not counted_clause(clause, value):
        return False
    k = line_clause.find(clause)
    rest = f"{line_clause[:k]} {line_clause[k + len(clause) :]}"
    return value in numerals.numbers_in(rest)


def element_index_quote(
    quote: str, support: Sequence[digest.Line], value: int, *, widen: bool = False
) -> bool:
    """Every clause of the quote that names ``value`` reads it as an element index: the clause
    has an element-index word ("Sodium's atomic number is 11", "element number 6"), or, with
    ``widen`` (the element items only, :func:`element_item`; round 4), names the value only as
    an ordinal ("8th") or sits in a support-line clause that has one (a short quote "Sodium is
    11" cut from "Sodium is 11 on the periodic table"), unless it is the counted half of that
    line clause (:func:`_counted_half`). A token quote never (token lists have no clauses), and
    a quote whose naming clause is a cardinal with no such word in its line ("That's seven.")
    never."""
    if any(ln.pieces is not None for ln in support):
        return False
    naming = [c for c in clauses(quote) if value in numerals.numbers_in(c)]
    line_clauses = [lc for ln in support for lc in clauses(ln.text)] if widen else []

    def index(c: str) -> bool:
        if _elem_words(c) or (widen and _ordinal_only(c, value)):
            return True
        return any(
            c in lc and _elem_words(lc) and not _counted_half(lc, c, value) for lc in line_clauses
        )

    return bool(naming) and all(index(c) for c in naming)


def counted_anywhere(lines: Sequence[digest.Line], value: int) -> bool:
    """Some prose evidence line has a :func:`counted_clause` for ``value`` (the rescue: the
    judge quoted the atomic number, but the readout also names the count)."""
    return any(
        ln.pieces is None and any(counted_clause(c, value) for c in clauses(ln.text))
        for ln in lines
    )


# The quote's form check: a gold pick's quote names the gold by its name, a listed alias, or a
# derived form (demonym / adjective / plural) from the family's frozen reviewed table
# (evals/<family>/derived_forms.json), except a derived form that is part of the item's final
# answer ("Spanish" for Spain when the answer is Spanish: the answer read back, not the bridge). A
# quote that also names another shown option (its name, aliases or derived forms) names none of
# them. Descriptions never count.
DERIVED_FORMS = "derived_forms.json"


def derived_forms(family: str = "multihop") -> dict[str, list[str]]:
    """``evals/<family>/derived_forms.json``: option -> its reviewed derived forms (missing file:
    none). Under ``WSB_BANK_ROOT`` a set's own ``<root>/<family>/derived_forms.json`` adds forms
    for options the registered table lacks (``registry.load_resource``; a registered option always
    keeps its registered forms); an option in neither has no derived forms."""
    data, _added = registry.load_resource(family, DERIVED_FORMS, ("forms",))
    return {str(k): [str(f) for f in v] for k, v in (data.get("forms") or {}).items()}


def answer_part(item: Mapping[str, Any], form: str) -> bool:
    """``form`` occurs (word-bounded, folded) in the item's final answer (``target``)."""
    return mc.form_in(str(item.get("target") or ""), [form])


def gold_forms(item: Mapping[str, Any], family: str = "multihop") -> list[str]:
    """The forms a quote may name the gold by: the gold, its listed aliases, and its derived
    forms that are not part of the item's final answer."""
    block = item["mc"]
    derived = [f for f in derived_forms(family).get(block["gold"], []) if not answer_part(item, f)]
    return [block["gold"], *block.get("aliases", []), *derived]


def option_forms(item: Mapping[str, Any], option: str, family: str = "multihop") -> list[str]:
    """Another shown option's forms: the option, its ``distractor_aliases`` and derived forms."""
    listed = item["mc"].get("distractor_aliases", {})
    return [option, *listed.get(option, ()), *derived_forms(family).get(option, [])]


def names_other(
    text: str, item: Mapping[str, Any], others: Sequence[str], family: str = "multihop"
) -> bool:
    """``text`` names another shown option: a ``number`` bridge by value (any script), any
    other type by :func:`option_forms` (with the CJK suffix guard)."""
    if item["mc"].get("bridge_type") == "number":
        values = {v for o in others if (v := numerals.word_value(o)) is not None}
        return bool(numerals.numbers_in(text) & values)
    return any(_form_bounded(text, option_forms(item, o, family)) for o in others)


def near_block(quote: str, text: str) -> str:
    """The longest block a near-verbatim quote shares with a line (``digest.fold_quote`` forms):
    the readout's own words at the quote's place, never the judge's."""
    fq, fl = digest.fold_quote(quote), digest.fold_quote(text)
    m = SequenceMatcher(None, fq, fl, autojunk=False).find_longest_match(0, len(fq), 0, len(fl))
    return fl[m.b : m.b + m.size]


def continued_quote(
    quote: str, ln: digest.Line, item: Mapping[str, Any], forms: Sequence[str], near: bool
) -> list[str]:
    """The quote run on, on prose line ``ln``, through the gold where the line continues it (the
    quote was cut mid-name; ``nearquote.continued`` over ``forms``); a ``number`` bridge: through
    the gold's value written from a word of the quote or the first word after it and read whole
    ("twenty" of "twenty-one" is 21). ``[]``: the line does not continue the quote into the gold
    (a token line never does)."""
    block = item["mc"]
    if block.get("bridge_type") != "number":
        return continued(quote, ln, forms, _form_bounded, near=near)
    gold = int(block["gold"])
    out: list[str] = []
    for c in cuts(quote, ln, near=near, max_words=4):
        # the first numeral from the window's first word on: the whole window, and the gold
        first = numerals.tokens(digest.fold_quote(c.window + c.after))[:1]
        if first and first[0][:3] == (0, len(digest.fold_quote(c.window)), gold):
            out.append(c.extended)
    return list(dict.fromkeys(out))


def verdict(
    result: dict[str, Any] | None,
    shown: list[str],
    gold_idx: int,
    lines: list[digest.Line] | tuple[digest.Line, ...],
    item: dict[str, Any],
    family: str = "multihop",
) -> dict[str, Any]:
    """The scored verdict of one call (``None`` result = undecided); ``family`` picks the derived
    forms table (:func:`derived_forms`)."""
    if result is None:
        return {"choice_kind": None, "correct": None}
    choice = result.get("choice")
    quote = str(result.get("quote") or "").strip()
    idx = mc.letter_index(choice, shown, LETTERS[: len(shown)])
    kind = mc.classify(None if idx is None else idx + 1, gold_idx + 1, len(shown))
    out: dict[str, Any] = {"choice": choice, "choice_kind": kind, "quote": quote}
    if kind != "gold":
        out["correct"] = False
        return out
    block = item["mc"]
    # the name, aliases and the table's derived forms not part of the final answer
    forms = gold_forms(item, family)
    q_ok = digest.quote_ok(quote, lines)
    # same-list tokens are quoted joined by " | ": "New | Zealand" names "New Zealand"
    flat = " ".join(quote.replace("|", " ").split())
    number = block.get("bridge_type") == "number"
    # a number: the VALUE, in any script: digits, words, ordinals, CJK (十六 is 16, never 6);
    # listed CJK forms match as substrings, so they are not used for numbers
    f_ok = int(block["gold"]) in numerals.numbers_in(flat) if number else _form_bounded(flat, forms)
    support: list[digest.Line] = []
    if q_ok:
        support = [ln for ln in lines if digest.quote_ok(quote, [ln])]
        support = support or (digest.split_word(quote, lines) or [])
    else:
        # a near-verbatim quote (nearquote.close_lines) is located in its prose line; its own
        # words then count for nothing, only that line's text does
        support = close_lines(quote, list(lines))
    near = not q_ok and bool(support)
    # the quote is read in its line's context (add, never relax): a prose quote cut out of a
    # longer word ("6" of "16", "six" of "sixteen", "Japan" of a "Japanese" the table does not
    # accept for this item) or a CJK form followed by a demonym / language suffix (日本人, 意大利语)
    # does not name the gold
    if f_ok and support:
        f_ok = q_ok and any(
            _in_context(quote, ln, forms, int(block["gold"]) if number else None) for ln in support
        )
    others = [o for k, o in enumerate(shown[:-1]) if k != gold_idx]
    # a quote that also names another shown option names none of them
    other = names_other(flat, item, others, family)
    # a near quote is read where it matched (its block of the readout's own words names the gold
    # and no other shown option); a quote that still does not name the gold passes only when it was
    # cut mid-name: its line continues it into the gold, and the quote so run on names the gold and
    # no other shown option, or the quote ends its sample inside a name only the gold's forms start
    # with (a line naming the gold anywhere else gives nothing)
    via = "quote" if f_ok else None
    if not f_ok and near and not other:
        for b in (near_block(quote, ln.text) for ln in support):
            named = (
                int(block["gold"]) in numerals.numbers_in(b) if number else _form_bounded(b, forms)
            )
            if named and not names_other(b, item, others, family):
                f_ok, via = True, "block"
                break
    if not f_ok and not other:
        for run_on in (t for ln in support for t in continued_quote(quote, ln, item, forms, near)):
            named = (
                int(block["gold"]) in numerals.numbers_in(run_on)
                if number
                else _form_bounded(run_on, forms)
            )
            if named and not names_other(run_on, item, others, family):
                f_ok, via = True, "line"
                break
    if not f_ok and not other:
        # the sample ends inside the gold's name: the quote's trailing words begin forms of the
        # gold and of no other shown option
        options = {block["gold"]: forms, **{o: option_forms(item, o, family) for o in others}}
        for ln in support:
            cut = sample_end_prefix(quote, ln, options, near=near)
            if cut is not None and cut[0] == block["gold"]:
                f_ok, via = True, "line"
                break
    flood = (
        block.get("bridge_type") == "number"
        and bool(support)
        and all(digest.number_flood(ln) for ln in support)
    )
    # the shared token note, held in code for token lines (add, never relax): a ranked list that
    # also holds another shown option singles out none of them
    multi = bool(support) and all(
        ln.pieces is not None and _holds_other(ln.pieces, others, block) for ln in support
    )
    # round 3: a number bridge quoted only as an atomic number / periodic position, with no
    # counted mention anywhere in the evidence, reads the answer element back (nhop-* lite)
    elem = (
        number
        and bool(support)
        and element_index_quote(quote, support, int(block["gold"]), widen=element_item(item))
        and not counted_anywhere(lines, int(block["gold"]))
    )
    out.update(
        {
            "quote_ok": q_ok,
            "quote_near": near,
            "form_ok": f_ok,
            "form_via": via,
            "names_other": other,
            "number_flood": flood,
            "multi_option": multi,
            "element_index": elem,
        }
    )
    out["correct"] = (q_ok or near) and f_ok and not other and not flood and not multi and not elem
    return out


def _validate(call: Call, r: dict) -> bool:
    shown = call.meta["options"]
    return mc.letter_index(r.get("choice"), shown, LETTERS[: len(shown)]) is not None


def run(args: JudgeArgs, *, name: str, bank: Path) -> FamilyResult:
    _header, items = load_bank(bank)
    scope = item_scope(items, args)
    for it in scope:  # plan 0060 A2: a missing per-set entry fails here, before any call
        element_item(it, name)
    ids = [it["id"] for it in scope]
    by_id = {it["id"]: it for it in scope}
    options = {i: options_of(name, by_id[i]) for i in ids}
    cells, rep = reads.load(args, name, ids=ids)
    layers = args.layers if args.layers is not None else rep.layers
    groups: dict[tuple[str, int], list[Cell]] = defaultdict(list)
    for c in cells:
        groups[(c.id, c.layer)].append(c)
    expected = [(i, layer) for i in ids for layer in layers]
    missing = [k for k in expected if k not in groups]
    require_cells(name, missing, len(expected), args)
    spec = registry._spec_for_bank(name)  # also when the registry was emptied after import
    ctx = _Ctx(args, name, spec.task_note, by_id, options, digest.token_note_of(name))
    if digest.summary_mode(args):
        return _summary(ctx, scope, ids, cells, rep, groups, len(expected), missing)
    return _native(ctx, scope, ids, cells, rep, groups, layers, len(expected), missing)


@dataclass
class _Ctx:
    args: JudgeArgs
    name: str
    task_type: str
    items: dict[str, dict[str, Any]]
    options: dict[str, tuple[list[str], int]]
    token_note: str


def _pv(name: str) -> str:
    from wsbench.basic.prompts import prompt_version_of

    return prompt_version_of(name)


def call_pv(name: str, pv: str) -> str:
    """The MC calls' fingerprint version: ``pv`` (the result stamp, maybe with the digest and
    reads suffixes) with the family's stamp replaced by its :data:`CALL_VERSIONS` entry."""
    stamp = _pv(name)
    return pv.replace(stamp, CALL_VERSIONS.get(name, stamp), 1)


def _calls_run(ctx: _Ctx, calls: list[Call], pv: str, cache: Cache, spend: Spend, pre: Preflighter):
    results = run_calls(
        calls,
        schema=SCHEMA,
        judge=ctx.args.judge,
        prompt_version=pv,
        cache=cache,
        spend=spend,
        concurrency=ctx.args.concurrency,
        rpm=ctx.args.rpm,
        dry_run=ctx.args.dry_run,
        preflight=pre.for_judge(ctx.args.judge),
        validate=_validate,
        temperature=0.0,
    )
    if calls and not ctx.args.dry_run and all(results.get(c.key) is None for c in calls):
        raise JudgeConfigError(f"all {len(calls)} judge calls failed; nothing was scored")
    return results


def _pick_extras(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    picks: dict[str, int] = defaultdict(int)
    for v in verdicts:
        picks[str(v.get("choice_kind"))] += 1
    gold = [v for v in verdicts if v.get("choice_kind") == "gold"]
    return {
        "picks": dict(sorted(picks.items())),
        "n_gold_pick_quote_unverified": sum(1 for v in gold if not v.get("quote_ok")),
        "n_gold_pick_form_missing": sum(
            1 for v in gold if v.get("quote_ok") and not v.get("form_ok")
        ),
        "n_gold_pick_number_flood": sum(1 for v in gold if v.get("number_flood")),
        "n_gold_pick_multi_option_list": sum(1 for v in gold if v.get("multi_option")),
        "n_gold_pick_element_index": sum(1 for v in gold if v.get("element_index")),
        "n_gold_pick_names_other": sum(1 for v in gold if v.get("names_other")),
    }


def _item_meta(ctx: _Ctx, i: str) -> dict[str, Any]:
    shown, gold_idx = ctx.options[i]
    return {
        "id": i,
        "options": shown,
        "gold_idx": gold_idx,
        "bridge_type": ctx.items[i]["mc"].get("bridge_type", ""),
    }


def _summary(ctx, scope, ids, cells, rep, groups, n_expected, missing) -> FamilyResult:
    args, name = ctx.args, ctx.name
    by_item: dict[str, list[Cell]] = defaultdict(list)
    for (i, _layer), cs in groups.items():
        by_item[i].extend(cs)
    partial = {i for i, _layer in missing}
    pv = digest.prompt_version(_pv(name), args, name)
    spend = Spend()
    pre = Preflighter(args.dry_run)
    system = system_of(name)
    question = strings_of(name).question
    with Cache(args.out / "cells.jsonl") as cache:
        col = digest.collapse(
            name,
            {i: by_item[i] for i in ids if by_item.get(i)},
            args=args,
            cache=cache,
            spend=spend,
            preflight=pre.for_judge(digest.summarizer_judge(args, name)),
            task_note=ctx.task_type,
        )
        source_kind = digest.as_prose(rep)
        note = digest.summary_note(args, None, name) + "\n" + ctx.token_note
        calls = []
        for i in ids:
            if i not in col.cells or i in col.unsummarized or i in col.empty:
                continue
            shown, gold_idx = ctx.options[i]
            text = (col.cells[i].samples or ("",))[0]
            user = render_user(ctx.task_type, note, text, question, shown)
            calls.append(Call(f"{i}|L{digest.SUMMARY_LAYER}", system, user, {"options": shown}))
        results = _calls_run(ctx, calls, call_pv(name, pv), cache, spend, pre)
    rows, verdicts = [], []
    n_unjudged = len(col.unsummarized)
    for i in ids:
        row = _item_meta(ctx, i)
        row["n_missing"] = sum(1 for k in missing if k[0] == i)
        shown, gold_idx = ctx.options[i]
        if i not in col.cells:
            row.update({"pass": None, "choice_kind": None})
        elif i in col.unsummarized:
            row.update({"pass": None, "choice_kind": None, "n_unjudged": 1})
        elif i in col.empty:
            row.update({"pass": False, "choice_kind": "empty"})
        else:
            key = f"{i}|L{digest.SUMMARY_LAYER}"
            r = results.get(key)
            v = verdict(r, shown, gold_idx, col.evidence.get(i, ()), ctx.items[i], name)
            if r is None:
                n_unjudged += 1
                row["n_unjudged"] = 1
            else:
                verdicts.append(v)
            row.update(v)
            passed = v.get("correct")
            row["pass"] = tri_state(bool(passed), passed is None or i in partial)
        if i in col.cells:
            row.update(col.row(i))
        rows.append(row)
    extras = {"n_calls": len(calls), "summary": col.extras(), **_pick_extras(verdicts)}
    result = pass_rate_result(
        name=name,
        args=args,
        prompt_version=pv,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=n_expected,
        n_missing=len(missing),
        n_unjudged=n_unjudged,
        n_empty=len(col.empty),
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra={**digest.config(args, source_kind, name), "gate": GATE_VERSION},
        extras=extras,
        n_items=len(ids),
        pinned=digest.pinned(args, name),
    )
    return with_readout_count(result, scope, cells)


def _native(ctx, scope, ids, cells, rep, groups, layers, n_expected, missing) -> FamilyResult:
    args, name = ctx.args, ctx.name
    pv = _pv(name)
    spend = Spend()
    pre = Preflighter(args.dry_run)
    system = system_of(name)
    question = strings_of(name).question
    note = NATIVE_NOTE + "\n" + ctx.token_note
    lines_of: dict[str, list[digest.Line]] = {}
    n_empty = 0
    calls = []
    for (i, layer), cs in sorted(groups.items()):
        if i not in ctx.options:
            continue
        lines = digest.native_lines(cs)
        key = f"{i}|L{layer}"
        if not lines:
            n_empty += 1
            lines_of[key] = []
            continue
        lines_of[key] = lines
        shown, _g = ctx.options[i]
        user = render_user(ctx.task_type, note, render_native(lines), question, shown)
        calls.append(Call(key, system, user, {"options": shown}))
    with Cache(args.out / "cells.jsonl") as cache:
        results = _calls_run(ctx, calls, call_pv(name, pv), cache, spend, pre)
    rows, verdicts = [], []
    n_unjudged = 0
    for i in ids:
        row = _item_meta(ctx, i)
        shown, gold_idx = ctx.options[i]
        per_layer: dict[str, dict[str, Any]] = {}
        hits: list[int] = []
        n_miss = n_unj = 0
        for layer in layers:
            key = f"{i}|L{layer}"
            if (i, layer) not in groups:
                n_miss += 1
                continue
            if not lines_of.get(key):
                per_layer[str(layer)] = {"pick": "empty", "choice_kind": "empty", "correct": False}
                continue
            r = results.get(key)
            v = verdict(r, shown, gold_idx, lines_of[key], ctx.items[i], name)
            if r is None:
                n_unj += 1
            else:
                verdicts.append(v)
            v["pick"] = v.get("choice_kind")
            per_layer[str(layer)] = v
            if v.get("correct"):
                hits.append(layer)
        n_unjudged += n_unj
        row.update(
            {
                "pass": tri_state(bool(hits), n_unj > 0 or n_miss > 0 or not per_layer),
                "earliest_layer": min(hits) if hits else None,
                "n_unjudged": n_unj,
                "n_missing": n_miss,
                "layers": per_layer,
            }
        )
        rows.append(row)
    extras: dict[str, Any] = {"n_calls": len(calls), **_pick_extras(verdicts)}
    extras.update(layer_pick_columns(rows))
    if not args.dry_run:
        extras["layer_protocols"] = layer_protocols(
            {
                r["id"]: {
                    int(L): bool(v.get("correct"))
                    for L, v in r["layers"].items()
                    if v.get("correct") is not None
                }
                for r in rows
            },
            family=name,
            layers=layers,
        )
    result = pass_rate_result(
        name=name,
        args=args,
        prompt_version=pv,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=n_expected,
        n_missing=len(missing),
        n_unjudged=n_unjudged,
        n_empty=n_empty,
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra={"gate": GATE_VERSION},
        extras=extras,
    )
    return with_readout_count(result, scope, cells)
