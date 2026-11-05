"""wrong_intermediate (plan 0050): a blind 6-way MC judge over the model's wrong intermediate B'
(gold), the
true bridge B (contrast, scored as a fail and reported as ``true_bridge_rate``) and four
same-category distractors, plus "cannot tell" last. Options and name forms are frozen in bank v2
(``scripts/wrong_intermediate_mc_options.py``); nothing is built at judge time.

Summary mode (the default): every loaded cell of an item (every position x layer under
``reads=full``; the final token under ``reads=lite``) -> one digest -> ONE MC call. Native mode
(``opts=aggregate=native``, the ATI gate): one MC call per (item, layer) over that layer's
positions; an item passes if any layer is a credited gold pick.

A gold pick is credited only if its quote verifies against the readout (``digest.quote_ok``,
else near-verbatim), names the gold by a listed form (:func:`name_in`, every option matched the
same way) in the quote or, for a quote cut mid-name, where its line continues it
(:func:`form_via`), and is not an echo of the prompt. Nothing in code overrules the judge's pick;
the raw wrong-vs-true counts are reported beside the score, never scored."""

import functools
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher
from typing import Any

from wsbench import digest, mc, reads
from wsbench.banks import load_bank
from wsbench.cache import Cache
from wsbench.family import pass_rate_result, require_cells, tri_state
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
from wsbench.nearquote import close_lines, continued, sample_end_prefix
from wsbench.readouts import Cell
from wsbench.registry import JudgeArgs, bank_path
from wsbench.results import FamilyResult

from . import prompts as wp

NAME = "wrong_intermediate"
N_SHOWN = 7  # 6 candidates + cannot tell
CHANCE = 1 / 6
CHANCE_LABEL = (
    "MC, 6 candidates + cannot tell: uniform-guess floor 1/6; lucky-guessing floor in "
    "evals/baselines/lucky_guessing.json"
)
PICKS = (
    "gold",
    "contrast",
    "distractor",
    "cannot_tell",
    "invalid",
    "gold_uncredited",
)


# ------------------------------------------------------------------ the name matcher (round 4)
# Camila r2: the forms were too strict ("King Roger II", Russian "Назван в честь Карла Маркса").
# Bank v3 lists every option's Wikidata names in every language (symmetric over the options); the
# matcher, used for EVERY option and by every check below (the form gate, the raw counts), adds:
# inflection tolerance (each word of 4+ letters of a non-CJK form may run on into up to
# WORD_SUFFIX letters of its own script: "Карла Маркса" for "Карл Маркс", Croatian
# "Ivana Gundulića"), word boundaries counted against letters of the form's own scripts only (a
# Latin name glued to CJK text, "Blue Note以", is a whole word), and Hangul forms compared in NFC.
# wbforms-v2 (review of PR #208, round 4b): the inflection tolerance is for inflecting
# languages only (Camila asked for Russian / inflection tolerance, not English): it applies to a
# form spelled with a letter outside ASCII (Cyrillic, Greek, ..., or an accented Latin letter: a
# non-English spelling, Croatian "Ivan Gundulić"); a plain-ASCII form is English-spelled (or
# indistinguishable from it) and matches whole words only, since English does not inflect names:
# "random" is not Ayn Rand, "a wilder story" not Oscar Wilde, "Hannah Arendt" not William Hanna.
# wbforms-v3 (review of PR #208, round 4c nit): ``mc.fold`` strips accents, so an accent-only
# form ("Pärt", "Dalí": its only non-ASCII letters are Latin accents) folded to an English word
# ("part") or took the tail as a non-English spelling ("Dalit", "Dalian"). Such a form now takes
# the tail only when the text keeps its accents ("Dalís", "Ivana Gundulića"); spelled without
# them it matches as an English form, whole words only, and as one bare word only capitalized
# ("Beyonce", "Dali" still count; "part of the sonata" does not). The checks therefore read the
# text unfolded (:func:`norm`), never ``digest.fold_quote`` output.
FORMS_VERSION = wp.FORMS_VERSION  # wbforms-v4: ASCII twins of accent-only forms (_ascii_twins)
WORD_SUFFIX = 2
WORD_SUFFIX_MIN = 4
_SPACED = r"0-9a-z\u00c0-\u024f\u0370-\u03ff\u0400-\u052f\u0530-\u058f\u0590-\u05ff\u0600-\u06ff"
_BEFORE = rf"(?<![{_SPACED}])"
_AFTER = rf"(?![{_SPACED}])"
_TAIL = rf"[{_SPACED[3:]}]{{0,{WORD_SUFFIX}}}"
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")


def inflecting(form: str) -> bool:
    """The form (as listed, before folding) is spelled with a letter outside ASCII: a
    non-English spelling, whose words may take an inflectional ending (see FORMS_VERSION)."""
    return any(ch.isalpha() and not ch.isascii() for ch in form)


def accent_only(form: str) -> bool:
    """The form's non-ASCII letters are all Latin accents: :func:`inflecting`, yet
    ``mc.fold`` makes it plain ASCII ("Pärt" -> "part"), so its folded spelling can be an
    English word (see FORMS_VERSION)."""
    return inflecting(form) and mc.fold(form).isascii()


_MD = re.compile(r"\*\*|__|[*_`]")


def norm(text: str) -> str:
    """``digest.fold_quote`` without the fold: NFC, markdown marks stripped, the bullet mark as
    a space, whitespace collapsed; accents and case kept for :func:`name_spans`."""
    t = _MD.sub("", unicodedata.normalize("NFC", text)).replace(digest.BULLET_MARK.strip(), " ")
    return " ".join(t.split())


def _views(text: str) -> tuple[str, str, str]:
    """(``mc.fold(text)``, the same with each letter's accents kept, the same with its case
    kept): equal lengths, so a span in one is the same span in the others."""
    t, k, c_ = [], [], []
    for c in unicodedata.normalize("NFC", text):
        f, a = mc.fold(c), c.casefold()
        t.append(f)
        k.append(a if len(a) == len(f) else f)
        c_.append(c if len(f) == 1 else f)
    return "".join(t), "".join(k), "".join(c_)


def _form_pattern(ff: str, inflect: bool = True) -> str:
    words = ff.split(" ")
    return " ".join(
        re.escape(w) + (_TAIL if inflect and len(w) >= WORD_SUFFIX_MIN and w[-1].isalpha() else "")
        for w in words
    )


_Rule = Callable[[str], bool]


def _plan(f: str, glued: bool) -> tuple[Any, ...] | None:
    """:func:`_compiled`, keyed by the module's current spelling rules (:func:`inflecting`,
    :func:`accent_only`), so a patched rule is a new key, never a stale pattern."""
    return _compiled(f, glued, inflecting, accent_only)


@functools.cache
def _compiled(f: str, glued: bool, infl_rule: _Rule, acc_rule: _Rule) -> tuple[Any, ...] | None:
    """One form's compiled matcher (cached: an option lists up to ~350 forms, which overflowed
    ``re``'s 512-entry cache, so every call recompiled every pattern, ~33 ms per ``name_in``)."""
    if _HANGUL.search(f):
        ff = unicodedata.normalize("NFC", f).casefold().strip()
        return ("hangul", ff) if ff else None
    ff = mc.fold(f).strip()
    if not ff:
        return None
    if mc.is_cjk(ff):
        return ("cjk", re.compile(re.escape(ff)))
    before, after = _BEFORE, _AFTER
    if not glued:
        before += r"(?<![^\W\d_][-\u2010\u2011])"
        after += r"(?![-\u2010\u2011][^\W\d_])"
    if acc_rule(f):
        fa = unicodedata.normalize("NFC", f).casefold().strip()
        return (
            "accent",
            re.compile(before + _form_pattern(fa, True) + after),
            re.compile(before + _form_pattern(ff, False) + after),  # unaccented: English form
            " " in ff,
        )
    return ("plain", re.compile(before + _form_pattern(ff, infl_rule(f)) + after))


@functools.lru_cache(maxsize=4096)
def _views_cached(text: str) -> tuple[str, str, str]:
    return _views(text)


@functools.cache
def _ascii_twins(forms: tuple[str, ...], acc_rule: _Rule) -> frozenset[str]:
    """wbforms-v4 (review of PR #208, round 4d nit): the bank also lists an accent-only name's
    plain-ASCII spelling as a form of its own ("Dali" beside "Dalí", "Cezanne", "Melies"), which
    matched case-insensitively ("by dali", "a dali-like scene"). Such a one-word twin of an
    accent-only label word follows the accent-only rule: as one bare word it counts only
    capitalized."""
    # the accented words of the option's own label (forms[0], the bank's order): "Dalí" of
    # "Salvador Dalí"; an accent in some other language's form ("Lénine") makes no twin, so
    # lowercase token-list "lenin" / "chopin" still count
    label = forms[0] if forms else ""
    acc = (
        {mc.fold(w).strip(".,") for w in label.split() if not w.isascii()}
        if acc_rule(label)
        else set()
    )
    return frozenset(
        f
        for f in forms
        if f.isascii() and " " not in f.strip() and not acc_rule(f) and mc.fold(f).strip() in acc
    )


def name_spans(text: str, forms: Sequence[str], *, glued: bool = True) -> list[tuple[int, int]]:
    """Where the forms occur in ``mc.fold(text)`` (see FORMS_VERSION); ``glued=False``: a Latin
    form glued by a hyphen into a longer name ("Wong Fei-Hung") does not count."""
    t, t_acc, t_case = _views_cached(text)
    twins = _ascii_twins(tuple(forms), accent_only)
    out: list[tuple[int, int]] = []
    for f in forms:
        plan = _plan(f, glued)
        if plan is None:
            continue
        kind = plan[0]
        if f in twins and kind == "plain":
            out += [
                (m.start(), m.end()) for m in plan[1].finditer(t) if t_case[m.start()].isupper()
            ]
            continue
        if kind == "hangul":
            if plan[1] in unicodedata.normalize("NFC", text).casefold():
                out.append((0, 0))  # Hangul: presence only (NFC offsets differ from fold's)
        elif kind == "cjk":
            out += [(m.start(), m.end()) for m in plan[1].finditer(t)]
        elif kind == "accent":
            out += [(m.start(), m.end()) for m in plan[1].finditer(t_acc)]
            out += [
                (m.start(), m.end())
                for m in plan[2].finditer(t)
                if plan[3] or t_case[m.start()].isupper()
            ]
        else:
            out += [(m.start(), m.end()) for m in plan[1].finditer(t)]
    return out


def _any_plan(forms: Sequence[str]) -> tuple[re.Pattern[str] | None, tuple[str, ...]]:
    return _any_compiled(tuple(forms), inflecting, accent_only)


def _twin(f: str, forms: tuple[str, ...], acc_rule: _Rule) -> bool:
    return f in _ascii_twins(forms, acc_rule)


@functools.cache
def _any_compiled(
    forms: tuple[str, ...], infl_rule: _Rule, acc_rule: _Rule
) -> tuple[re.Pattern[str] | None, tuple[str, ...]]:
    """(one alternation of every plain form's pattern, the other forms): :func:`name_in` asks
    only whether some form occurs, so the plain forms are searched in one pass."""
    plain, rest = [], []
    for f in forms:
        plan = _compiled(f, True, infl_rule, acc_rule)
        if plan is None:
            continue
        if plan[0] == "plain" and not _twin(f, forms, acc_rule):
            plain.append(f"(?:{plan[1].pattern})")
        else:
            rest.append(f)
    return (re.compile("|".join(plain)) if plain else None), tuple(rest)


def name_in(text: str, forms: Sequence[str]) -> bool:
    """A listed form of an option occurs in ``text`` (see FORMS_VERSION)."""
    alt, rest = _any_plan(forms)
    if alt is not None and alt.search(_views_cached(text)[0]):
        return True
    return bool(rest) and bool(name_spans(text, rest))


def load_items() -> list[dict[str, Any]]:
    _header, items = load_bank(bank_path(NAME))
    return items


def shown_options(it: dict[str, Any]) -> list[str]:
    """The item's numbered list as the judge sees it: the frozen order, CANNOT last."""
    return wp.render_options(list(it["mc"]["order"]))[0]


def positions(it: dict[str, Any]) -> tuple[int, int]:
    """(gold, contrast) 1-based positions in the shown list."""
    order = list(it["mc"]["order"])
    return order.index(it["mc"]["gold"]) + 1, order.index(it["mc"]["contrast"]) + 1


def _squash(s: str) -> str:
    return "".join(ch for ch in digest.fold_quote(s) if ch.isalnum())


def echo_of_prompt(quote: str, prompt: str) -> bool:
    """The quote (folded, whitespace and punctuation removed) is part of the prompt (folded the
    same way): a name the readout copied from the input is not evidence of the bridge
    (``album_label-Q21480481-founded_year``: "Bluenote" from "Bluenote Café")."""
    q = _squash(quote)
    return bool(q) and q in _squash(prompt)


# ------------------------------------------------------------------ the quote and its line
# The quote is verified by ``digest.quote_ok`` (markdown-insensitive), else near-verbatim
# (``nearquote.close_lines``), and must name the gold reasonably and unambiguously, read in the
# line it came from: the verified quote itself names the gold, or a near quote's matched block (the
# readout's own words) does, or the quote was cut mid-name: its line continues it into a listed
# form of the gold ("...the composer was Ludwig van" + " Beethoven"; ``nearquote.continued``), the
# quote so run on naming the gold and no other candidate, or the quote ends its sample and its
# trailing words begin forms of the gold and of no other candidate ("...is Vincent van";
# ``nearquote.sample_end_prefix``). A line naming the gold anywhere else (a fact-only quote) gives
# nothing. The quote names no other candidate.


def quote_lines(quote: str, lines: Sequence[digest.Line]) -> tuple[bool, list[digest.Line]]:
    """(verified, the lines the quote came from): ``digest.quote_ok`` and the lines holding it
    (``digest.line_holds``, or a word split across positions), else the near-verbatim lines
    (``nearquote.close_lines``; prose only) with ``verified`` False. No line: unverified."""
    if digest.quote_ok(quote, lines):
        held = [ln for ln in lines if digest.line_holds(quote, ln)]
        return True, held or list(digest.split_word(quote, lines) or [])
    return False, close_lines(quote, list(lines))


def near_block(quote: str, text: str) -> str:
    """The longest block a near-verbatim quote shares with a line (``digest.fold_quote`` forms):
    the readout's own words at the quote's place, never the judge's."""
    fq, fl = digest.fold_quote(quote), digest.fold_quote(text)
    m = SequenceMatcher(None, fq, fl, autojunk=False).find_longest_match(0, len(fq), 0, len(fl))
    return fl[m.b : m.b + m.size]


def form_via(
    it: dict[str, Any], quote: str, verified: bool, located: Sequence[digest.Line]
) -> str | None:
    """How the quote names the gold: ``quote`` (a verified quote holds a listed form of the
    gold), ``block`` (a near quote's matched readout text names the gold and no other candidate),
    ``line`` (the quote was cut mid-name: a located line continues it into a listed form of the
    gold, :func:`~wsbench.nearquote.continued`, and the quote so run on names the gold and no
    other candidate; or the quote ends its sample and its trailing words begin forms of the gold
    and of no other candidate, :func:`~wsbench.nearquote.sample_end_prefix`), else None. A quote
    naming another candidate never names the gold."""
    forms = it["mc"]["forms"]
    gold = it["mc"]["gold"]
    others = [o for o in it["mc"]["order"] if o != gold]

    def single(text: str) -> bool:
        return name_in(text, forms[gold]) and not any(name_in(text, forms[o]) for o in others)

    q = norm(quote)
    if any(name_in(q, forms[o]) for o in others):
        return None
    if verified and name_in(q, forms[gold]):
        return "quote"
    if not verified and any(single(near_block(quote, ln.text)) for ln in located):
        return "block"
    by_option = {o: forms[o] for o in it["mc"]["order"]}
    for ln in located:
        for run_on in continued(quote, ln, forms[gold], _names_window, near=not verified):
            if single(norm(run_on)):
                return "line"
        cut = sample_end_prefix(quote, ln, by_option, near=not verified)
        if cut is not None and cut[0] == gold:
            return "line"
    return None


def _names_window(text: str, forms: list[str]) -> bool:
    return name_in(norm(text), forms)


# ------------------------------------------------------------------ role cues (data only)
# The role cues of each template (folded; a Latin cue is a word start, so "direct" also matches
# "directed" / "director"; a CJK cue is a substring). The judge's verified pick stands
# (judge-only-v1), so no verdict reads them; the adapt refill admits only a template listed here
# (adapt.wrong_intermediate.category_of, adapt.judge_inputs), and CUES_VERSION stamps the table.
_PERFORMER = "releas record perform sing sang sung rapper band artist 演唱 歌手 乐队 樂隊 樂團"
_CUES = {
    "film_director": "direct helm filmmaker regia regist 导演 導演 执导 執導",
    "painting_creator": "paint artist 画 畫",
    "novel_author": "author wrot writ novelist poet 作者 作家 著 写 寫",
    "composition_composer": "compos wrot writ 作曲",
    "album_performer": _PERFORMER + " album 专辑 專輯",
    "song_performer": _PERFORMER + " song single",
    "album_label": "label releas record sign issu 唱片",
    "doctoral_advisor": "advis supervis mentor doctoral phd 导师 導師",
    "person_father": "father son daughter child sire 父",
    "person_mother": "mother son daughter child 母",
    "org_founder": "found establish creat 创 創",
    "game_developer": "develop studio creat made produc 开发 開發",
    "product_manufacturer": "manufactur built build made produc maker shipyard shipbuild 制造 製造",
    "namesake": "name honor honour 命名",
    "song_lyricist": "lyric wrot writ 作词 作詞",
    "character_creator": "creat invent wrot writ 创 創",
    "tv_network": "network air broadcast channel 电视 電視",
    # plan 0066 §5.4 (CUES_VERSION wbcues-v2): templates the adapted refill admits; no entry
    # above changes, so no registered verdict moves
    "film_screenwriter": "screenplay screenwrit writ wrot script 编剧 編劇",
    "song_composer": "compos wrot writ 作曲",
    "tv_creator": "creat develop showrunner 创 創",
    "novel_publisher": "publish publication imprint 出版",
    "film_producer": "produc 制片 製片",
    "opera_librettist": "librett libretto wrot writ 作词 作詞 剧本 劇本",
    "album_producer": "produc 制作 製作",
    "aircraft_manufacturer": "manufactur built build produc maker 制造 製造",
}
ROLE_CUES: dict[str, tuple[str, ...]] = {k: tuple(v.split()) for k, v in _CUES.items()}


# ------------------------------------------------------------------ raw counts (report only)
# How often the raw samples name the wrong bridge B' and the true bridge B. Reported only
# (``raw_wrong`` / ``raw_true`` / ``raw_majority``); the judge's verified pick decides.


def raw_counts(it: dict[str, Any], cells: Sequence[Cell]) -> tuple[int, int]:
    """(wrong, true): how many raw readout samples of the item's loaded cells (one prose sample,
    or one cell's token list; ``digest.native_lines``) name the gold B' and the contrast B
    through their listed forms (:func:`name_in`)."""
    forms = it["mc"]["forms"]
    texts = [norm(ln.text) for ln in digest.native_lines(list(cells))]
    gold, contrast = forms[it["mc"]["gold"]], forms[it["mc"]["contrast"]]
    return sum(name_in(t, gold) for t in texts), sum(name_in(t, contrast) for t in texts)


def raw_majority(wrong: int, true: int) -> str:
    """Which bridge the raw samples name more often: ``wrong`` (B'), ``true`` (B), ``tie`` or
    ``none`` (neither named)."""
    if wrong == true:
        return "none" if wrong == 0 else "tie"
    return "wrong" if wrong > true else "true"


def raw_fields(raw: tuple[int, int] | None) -> dict[str, Any]:
    """The row's raw wrong-vs-true report (both modes; never scored natively)."""
    if raw is None:
        return {}
    return {"raw_wrong": raw[0], "raw_true": raw[1], "raw_majority": raw_majority(*raw)}


def decide(
    result: dict | None,
    it: dict[str, Any],
    lines: list[digest.Line],
) -> dict[str, Any]:
    """One MC answer as a verdict: ``pick`` (one of :data:`PICKS`, or None = unjudged) and the
    gate fields. Only a gold pick whose quote passes every gate is ``credited``. ``rival_quote`` is
    kept on the verdict as the judge returned it; it is never scored."""
    if result is None:
        return {"pick": None, "credited": False}
    gold_pos, contrast_pos = positions(it)
    kind = mc.classify(choice_of(result), gold_pos, N_SHOWN, contrast_pos=contrast_pos)
    quote = quote_of(result)
    out: dict[str, Any] = {
        "choice": choice_of(result),
        "quote": quote,
        "credited": False,
        "rival_quote": str(result.get("rival_quote", "") or ""),
    }
    if kind != "gold":
        out["pick"] = kind
        return out
    verified, located = quote_lines(quote, lines)
    near = not verified and bool(located)
    via = form_via(it, quote, verified, located)
    echo = echo_of_prompt(quote, it["prompt"])
    credited = (verified or near) and via is not None and not echo
    out.update(
        pick="gold" if credited else "gold_uncredited",
        credited=credited,
        quote_verified=verified,
        quote_near=near,
        form_ok=via is not None,
        form_via=via,
        echo_of_prompt=echo,
    )
    return out


def _mc_version(pv: str) -> str:
    """The MC call's fingerprint version: ``pv`` with the family's result stamp replaced by the
    frozen :data:`~wsbench.evals.wrong_intermediate.prompts.MC_CALL_VERSION` (the MC prompt has not
    changed since round 3, so cached MC answers are re-scored, never re-asked)."""
    return pv.replace(wp.PROMPT_VERSION, wp.MC_CALL_VERSION, 1)


def _valid(_call: Call, r: dict) -> bool:
    return mc.classify(choice_of(r), 1, N_SHOWN) != "invalid"


def _kind_note(kind: str | None) -> str:
    return digest.token_note_of(NAME) if kind == "tokens" else wp.KIND_NOTE_PROSE


def native_user(it: dict[str, Any], cells: list[Cell], kind: str | None) -> str:
    """The native user message for one (item, layer): every position's samples, rendered by
    ``digest.native_lines`` (a multi-bullet sample shows as ``- a ⁞ b ⁞ c``)."""
    by_pos: dict[int, list[Cell]] = defaultdict(list)
    for c in cells:
        by_pos[c.pos].append(c)
    blocks = []
    for pos in sorted(by_pos):
        lines = digest.native_lines(by_pos[pos])
        if lines:
            blocks.append(wp.render_block(pos, "\n".join(f"- {ln.text}" for ln in lines)))
    _shown, listing = wp.render_options(list(it["mc"]["order"]))
    return wp.render_user(listing, _kind_note(kind), "\n\n".join(blocks))


def summary_user(it: dict[str, Any], summary: str, note: str) -> str:
    _shown, listing = wp.render_options(list(it["mc"]["order"]))
    return wp.render_user_summary(listing, note, summary)


def _counts(verdicts: list[dict[str, Any]]) -> dict[str, int]:
    out = dict.fromkeys(PICKS, 0)
    for v in verdicts:
        if v.get("pick") in out:
            out[v["pick"]] += 1
    return out


def run(args: JudgeArgs) -> FamilyResult:
    items = load_items()
    scope = item_scope(items, args)
    ids = [it["id"] for it in scope]
    cells, rep = reads.load(args, NAME, ids=ids)
    layers = args.layers if args.layers is not None else rep.layers
    groups: dict[tuple[str, int], list[Cell]] = defaultdict(list)
    for c in cells:
        groups[(c.id, c.layer)].append(c)
    expected = [(i, layer) for i in ids for layer in layers]
    missing = [k for k in expected if k not in groups]
    require_cells(NAME, missing, len(expected), args)
    if digest.summary_mode(args):
        return _run_summary(args, scope, cells, rep, groups, expected, missing)
    return _run_native(args, scope, cells, rep, layers, groups, expected, missing)


def _run_native(
    args: JudgeArgs,
    scope: list[dict[str, Any]],
    cells: list[Cell],
    rep: Any,
    layers: list[int],
    groups: dict[tuple[str, int], list[Cell]],
    expected: list[tuple[str, int]],
    missing: list[tuple[str, int]],
) -> FamilyResult:
    calls: list[Call] = []
    lines_of: dict[str, list[digest.Line]] = {}
    empty: set[tuple[str, int]] = set()
    for it in scope:
        for layer in layers:
            cs = groups.get((it["id"], layer))
            if cs is None:
                continue
            lines = digest.native_lines(cs)
            if not lines:
                empty.add((it["id"], layer))
                continue
            key = f"{it['id']}|L{layer:03d}"
            lines_of[key] = lines
            calls.append(
                Call(
                    key=key,
                    system=wp.SYSTEM,
                    user=native_user(it, cs, rep.kind),
                    meta={"item": it["id"], "layer": layer},
                )
            )
    spend = Spend()
    with Cache(args.out / "cells.jsonl") as cache:
        results = run_calls(
            calls,
            schema=wp.SCHEMA,
            judge=args.judge,
            prompt_version=_mc_version(wp.PROMPT_VERSION),
            cache=cache,
            spend=spend,
            concurrency=args.concurrency,
            rpm=args.rpm,
            dry_run=args.dry_run,
            preflight=Preflighter(args.dry_run).for_judge(args.judge),
            validate=_valid,
            temperature=0.0,
        )
    rows: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    n_unjudged = 0
    for it in scope:
        per: dict[str, dict[str, Any]] = {}
        n_miss = n_unj = 0
        for layer in layers:
            k = (it["id"], layer)
            if k not in groups:
                n_miss += 1
                continue
            if k in empty:
                per[str(layer)] = {"pick": "empty", "credited": False}
                continue
            key = f"{it['id']}|L{layer:03d}"
            v = decide(results.get(key), it, lines_of[key])
            if v["pick"] is None:
                n_unj += 1
            else:
                verdicts.append(v)
            per[str(layer)] = v
        n_unjudged += n_unj
        credited = [int(L) for L, v in per.items() if v.get("credited")]
        contrast = any(v.get("pick") == "contrast" for v in per.values())
        undecided = n_miss > 0 or n_unj > 0 or not per
        passed = tri_state(bool(credited), undecided)
        gold_pos, contrast_pos = positions(it)
        item_cells = [c for layer in layers for c in groups.get((it["id"], layer), ())]
        rows.append(
            {
                "id": it["id"],
                "pass": passed,
                "picked_true_bridge": bool(contrast and not credited)
                if passed is not None
                else None,
                "earliest_layer": min(credited) if credited else None,
                "options": shown_options(it),
                "gold_position": gold_pos,
                "contrast_position": contrast_pos,
                "n_missing": n_miss,
                "n_unjudged": n_unj,
                "layers": {L: v.get("pick") for L, v in per.items()},
                "verdicts": per,
                # reported only: the native path (the ATI gate) has no true-bridge check
                **raw_fields(raw_counts(it, item_cells) if item_cells else None),
            }
        )
    extras = _extras(rows, verdicts, len(calls))
    extras.update(layer_pick_columns(rows))
    result = pass_rate_result(
        name=NAME,
        args=args,
        prompt_version=wp.PROMPT_VERSION,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(expected),
        n_missing=len(missing),
        n_unjudged=n_unjudged,
        n_empty=len(empty),
        spend=spend,
        chance_label=CHANCE_LABEL,
        extras=extras,
    )
    result.chance = CHANCE
    return with_readout_count(result, scope, cells)


def _extras(
    rows: list[dict[str, Any]], verdicts: list[dict[str, Any]], n_calls: int
) -> dict[str, Any]:
    decided = [r for r in rows if r["pass"] is not None]
    n_tb = sum(1 for r in decided if r.get("picked_true_bridge"))
    majority = dict.fromkeys(("wrong", "true", "tie", "none"), 0)
    for r in rows:
        if r.get("raw_majority") in majority:
            majority[r["raw_majority"]] += 1
    n_raw = sum(majority.values())
    return {
        "n_calls": n_calls,
        "pick_counts": _counts(verdicts),
        "n_items_picked_true_bridge": n_tb,
        "true_bridge_rate": n_tb / len(decided) if decided else None,
        # the raw wrong-vs-true majority beside the judged score (items with readouts)
        "raw_majority": majority,
        "raw_wrong_majority_rate": majority["wrong"] / n_raw if n_raw else None,
    }


def _run_summary(
    args: JudgeArgs,
    scope: list[dict[str, Any]],
    cells: list[Cell],
    rep: Any,
    groups: dict[tuple[str, int], list[Cell]],
    expected: list[tuple[str, int]],
    missing: list[tuple[str, int]],
) -> FamilyResult:
    by_item: dict[str, list[Cell]] = defaultdict(list)
    for (i, _layer), cs in groups.items():
        by_item[i].extend(cs)
    partial = {i for i, _layer in missing}
    by_id = {it["id"]: it for it in scope}
    spend = Spend()
    pre = Preflighter(args.dry_run)
    pv = digest.prompt_version(wp.PROMPT_VERSION, args, NAME)
    with Cache(args.out / "cells.jsonl") as cache:
        col = digest.collapse(
            NAME,
            {i: by_item[i] for i in by_id if by_item.get(i)},
            args=args,
            cache=cache,
            spend=spend,
            preflight=pre.for_judge(digest.summarizer_judge(args, NAME)),
            task_note=wp.TASK_NOTE,
            expect_all=cells,
        )
        source_kind = digest.as_prose(rep)
        note = digest.summary_note(args, source_kind, NAME)
        calls = [
            Call(
                key=f"{i}|summary",
                system=wp.SYSTEM,
                user=summary_user(by_id[i], (c.samples or ("",))[0], note),
                meta={"item": i},
            )
            for i, c in col.cells.items()
            if i not in col.unsummarized and i not in col.empty
        ]
        results = run_calls(
            calls,
            schema=wp.SCHEMA,
            judge=args.judge,
            prompt_version=_mc_version(pv),
            cache=cache,
            spend=spend,
            concurrency=args.concurrency,
            rpm=args.rpm,
            dry_run=args.dry_run,
            preflight=pre.for_judge(args.judge),
            validate=_valid,
            temperature=0.0,
        )
    # the raw wrong-vs-true counts over every loaded cell of the item (not the digest)
    raw = {i: raw_counts(by_id[i], by_item[i]) for i in by_id if by_item.get(i)}
    rows: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    n_unjudged = len(col.unsummarized)
    for it in scope:
        i = it["id"]
        gold_pos, contrast_pos = positions(it)
        row: dict[str, Any] = {
            "id": i,
            "options": shown_options(it),
            "gold_position": gold_pos,
            "contrast_position": contrast_pos,
            "n_missing": sum(1 for k in missing if k[0] == i),
        }
        if i not in col.cells:  # no cells at all: the native missing path (undecided)
            row.update({"pass": None, "pick": None})
        elif i in col.unsummarized:
            row.update({"pass": None, "pick": None, "n_unjudged": 1})
        elif i in col.empty:
            row.update({"pass": False, "pick": "empty"})
        else:
            v = decide(results.get(f"{i}|summary"), it, list(col.evidence.get(i, ())))
            if v["pick"] is None:
                n_unjudged += 1
                row["n_unjudged"] = 1
            else:
                verdicts.append(v)
            passed = tri_state(bool(v.get("credited")), v["pick"] is None)
            if i in partial and passed is False:
                passed = None  # a missing layer leaves a non-pass undecided, as natively
            row.update({"pass": passed, **v})
        row["picked_true_bridge"] = (
            row.get("pick") == "contrast" if row["pass"] is not None else None
        )
        if i in col.cells:
            row.update(col.row(i))
        row.update(raw_fields(raw.get(i)))
        rows.append(row)
    extras = _extras(rows, verdicts, len(calls))
    extras["summary"] = col.extras()
    result = pass_rate_result(
        name=NAME,
        args=args,
        prompt_version=pv,
        rows=rows,
        cells=cells,
        rep=rep,
        n_expected=len(expected),
        n_missing=len(missing),
        n_unjudged=n_unjudged,
        n_empty=len(col.empty),
        spend=spend,
        chance_label=CHANCE_LABEL,
        config_extra=digest.config(args, source_kind, NAME),
        extras=extras,
        n_items=len(scope),
        pinned=digest.pinned(args, NAME),
    )
    result.chance = CHANCE
    return with_readout_count(result, scope, cells)
