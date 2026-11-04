"""The near-verbatim quote fallback of the name / form gates (audit fix F4, 2026-10-31).

``digest.quote_ok`` stays THE quote verifier; this module never replaces it. A gate that would
otherwise mark a gold pick ``unverified`` because the judge's quote is off by a word ("the
only one natural outflow river: the **Angara River**" for the line "Baikal has only one
natural outflow river: the **Angara River**.") may instead locate the prose line the quote
came from: :func:`close_lines`. The quote's own words then count for nothing — a gate that
accepts a near quote must find the answer's name in the located LINE (the readout's text),
never in the judge's paraphrase of it, so an invented or swapped name can never be credited.

A gate that reads a quote "in the line it came from" credits it through that line only when the
quote was cut mid-name: :func:`continued` (see "A quote cut mid-name" below).
"""

import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from wsbench import digest, mc

CLOSE_RATIO = 0.9  # the longest common block covers at least this share of the folded quote
CLOSE_MIN_CHARS = 12  # shorter quotes must verify exactly (a name alone is no near quote)


def close_lines(quote: str, lines: Sequence[digest.Line]) -> list[digest.Line]:
    """The PROSE lines of ``lines`` a near-verbatim ``quote`` came from: on
    ``digest.fold_quote`` forms, the quote is at least :data:`CLOSE_MIN_CHARS` characters and
    its longest common block with the line is at least ``ceil(CLOSE_RATIO * len(quote))``
    characters (one added, dropped or changed word at an edge, not a rewritten sentence). Token
    lines never match (a token quote verifies exactly or not at all)."""
    fq = digest.fold_quote(quote)
    if len(fq) < CLOSE_MIN_CHARS:
        return []
    need = math.ceil(CLOSE_RATIO * len(fq))
    out: list[digest.Line] = []
    for ln in lines:
        if ln.pieces is not None:
            continue
        fl = digest.fold_quote(ln.text)
        if len(fl) < need:
            continue
        m = SequenceMatcher(None, fq, fl, autojunk=False).find_longest_match(0, len(fq), 0, len(fl))
        if m.size >= need:
            out.append(ln)
    return out


# ---------------------------------------------------------------- a quote cut mid-name
# A gold pick whose quote does not name the answer earns credit through the line the quote came
# from only when the quote was cut mid-name, read in that line:
# - the line continues the quote into a form of the answer (:func:`continued`): the form starts
#   inside the quote and runs on past its end ("...is Vincent van" + " Gogh", "I'd say **sourd" +
#   "ough**"), or starts right after it, with only spaces, markdown emphasis, punctuation other
#   than a sentence end and at most one article ("the", "a", "an") in between ("the composer
#   was" + " **Beethoven**", "the outflow is" + " the Angara River");
# - or the sample ends inside the name (:func:`sample_end_prefix`): the quote is the sample's last
#   words, and its trailing words begin a listed form of exactly ONE option, the answer ("...is
#   Vincent van" with only van Gogh's forms starting "Vincent van"); a start several options
#   share ("**S" for salsa and swing) credits none.
# A line that names the answer anywhere else gives the quote nothing: a fact-only quote ("was born
# in 1770") is not credited however its line goes on. One line that credits the quote is enough:
# the other lines holding the same words are not weighed (the judge's pick stands; code only
# verifies).

# a word: a run of letters / digits, or ONE CJK, kana or Hangul character (scripts without spaces
# between words); names and lines are counted in the same words
_NOSPACE = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff"
_WORD = re.compile(rf"[{_NOSPACE}]|[^\W_{_NOSPACE}]+")
_NOSPACE_CHAR = re.compile(rf"[{_NOSPACE}]")
_MD = re.compile(r"[*_`]")  # the markdown marks digest.fold_quote drops
_MARK = digest.BULLET_MARK.strip()
# a sentence end between the quote and the next word, or inside a continuation, ends the name
# ("." too at the cut itself: a quote that ends a sentence is not cut mid-name)
_SENTENCE_END = frozenset("!?\u3002\uff01\uff1f" + _MARK)
_CUT_END = _SENTENCE_END | {"."}
MAX_WORDS = 12  # the longest continuation tried (a form of more words is never read across a cut)
ARTICLES = frozenset({"the", "a", "an"})  # one may stand between the quote and the name it cut


def words(text: str) -> list[tuple[int, int]]:
    """The word spans of ``text`` (:data:`_WORD`)."""
    return [m.span() for m in _WORD.finditer(text)]


def _plain(text: str) -> str:
    """``text`` as a cut is read in: NFC, the markdown marks ``digest.fold_quote`` drops dropped,
    whitespace collapsed; case, accents and the bullet mark kept."""
    return " ".join(_MD.sub("", unicodedata.normalize("NFC", text)).split())


def _folded(plain: str) -> tuple[str, list[int]]:
    """``digest.fold_quote(plain)`` built one character at a time, with each folded character's
    index in ``plain``."""
    chars: list[tuple[str, int]] = []
    for i, c in enumerate(plain):
        for ch in " " if c == _MARK else mc.fold(c):
            if ch.isspace():
                if chars and chars[-1][0] != " ":
                    chars.append((" ", i))
            else:
                chars.append((ch, i))
    if chars and chars[-1][0] == " ":
        chars.pop()
    return "".join(ch for ch, _i in chars), [i for _ch, i in chars]


def _quote_spans(quote: str, plain: str, near: bool) -> list[tuple[int, int]]:
    """Where ``quote`` sits in ``plain`` (start, end): every place a verified quote occurs
    (``digest.fold_quote`` forms, as ``digest.line_holds`` reads it), or a near quote's longest
    common block (the readout's own words at the quote's place, :func:`close_lines`)."""
    fl, src = _folded(plain)
    fq = digest.fold_quote(quote)
    if not fq or not fl or fl != digest.fold_quote(plain):
        return []
    spans: list[tuple[int, int]] = []
    if near:
        m = SequenceMatcher(None, fq, fl, autojunk=False).find_longest_match(0, len(fq), 0, len(fl))
        if m.size:
            spans.append((m.b, m.b + m.size))
    else:
        k = fl.find(fq)
        while k >= 0:
            spans.append((k, k + len(fq)))
            k = fl.find(fq, k + 1)
    return [(src[s], src[e - 1] + 1) for s, e in spans]


@dataclass(frozen=True)
class Cut:
    """One way a line may continue a quote: ``window`` = ``n_words`` consecutive words of the line
    that run from a word of the quote across the quote's end, or start with the first word after
    it; ``extended`` = the quote as the line has it, run on to the window's end (plus one
    following CJK character, for the gates' CJK suffix guards); ``after`` = the line's text after
    the window."""

    window: str
    n_words: int
    extended: str
    after: str


def cuts(
    quote: str, ln: digest.Line, *, near: bool = False, max_words: int = MAX_WORDS
) -> list[Cut]:
    """Every window of up to ``max_words`` words in which prose line ``ln`` may continue
    ``quote`` (``near``: a near-verbatim quote, located by its matched block): from a word of the
    quote across its end, or from the first word after it (the word after an article, when that
    first word is one). A token line holds whole tokens and continues nothing; a quote at a
    sentence end, or at the end of the line, has no continuation."""
    if ln.pieces is not None:
        return []
    plain = _plain(ln.text)
    ws = words(plain)
    out: list[Cut] = []
    for qs, qe in _quote_spans(quote, plain, near):
        inside = [k for k, (s, e) in enumerate(ws) if s < qe and e > qs]
        if not inside:
            continue
        last = inside[-1]
        if ws[last][1] > qe:  # the quote ends inside a word: that word runs on past it
            cross = last
        else:
            cross = last + 1
            if cross >= len(ws) or _CUT_END & set(plain[ws[last][1] : ws[cross][0]]):
                continue
        # (first word, the word every window from it must reach)
        spans = [(i, cross) for i in range(max(inside[0], cross - max_words + 1), cross + 1)]
        nxt = cross + 1
        if (
            cross == last + 1
            and nxt < len(ws)
            and plain[slice(*ws[cross])].casefold() in ARTICLES
            and not _CUT_END & set(plain[ws[cross][1] : ws[nxt][0]])
        ):
            spans.append((nxt, nxt))  # "...is" + " the Angara River"
        for i, reach in spans:
            for j in range(reach, min(i + max_words, len(ws))):
                if j > i and _SENTENCE_END & set(plain[ws[j - 1][1] : ws[j][0]]):
                    break
                end = ws[j][1]
                tail = plain[end : end + 1]
                out.append(
                    Cut(
                        window=plain[ws[i][0] : end],
                        n_words=j - i + 1,
                        extended=plain[min(qs, ws[i][0]) : end].lstrip()
                        + (tail if _NOSPACE_CHAR.match(tail) else ""),
                        after=plain[end:],
                    )
                )
    return out


def continued(
    quote: str,
    ln: digest.Line,
    forms: Sequence[str],
    names: Callable[[str, list[str]], bool],
    *,
    near: bool = False,
) -> list[str]:
    """The quote run on, on line ``ln``, through a form of ``forms`` that continues it (see "A
    quote cut mid-name"): a window of n words (:func:`cuts`) is a continuation when the family's
    own matcher ``names(window, forms of n words)`` accepts it, so the form fills the window from
    its first word. ``[]``: the line does not continue the quote into a form. The caller reads each
    returned text as it reads a verified quote (names the gold, names no other option)."""
    by_n: dict[int, list[str]] = defaultdict(list)
    for f in forms:
        n = len(words(_plain(f)))
        if n:
            by_n[n].append(f)
    if not by_n:
        return []
    found = [
        c.extended
        for c in cuts(quote, ln, near=near, max_words=min(max(by_n), MAX_WORDS))
        if c.n_words in by_n and names(c.window, by_n[c.n_words])
    ]
    return list(dict.fromkeys(found))


def sample_end_prefix(
    quote: str,
    ln: digest.Line,
    options: Mapping[str, Sequence[str]],
    *,
    near: bool = False,
) -> tuple[str, list[str]] | None:
    """A quote cut by the end of its sample (see "A quote cut mid-name"): when the quote is the
    last words of prose line ``ln`` (nothing but whitespace or markdown follows), its trailing
    words (the longest run of its last words, the last one maybe cut mid-word, that begins a
    listed form; folded as ``mc.form_in`` compares) begin forms of exactly one option of
    ``options`` (option -> its listed forms): that option and the forms it begins. ``None`` when
    the quote does not end its sample, no form starts that way, or several options' forms do."""
    if ln.pieces is not None:
        return None
    plain = _plain(ln.text)
    ws = words(plain)

    def key(text: str) -> str:
        return " ".join(mc.fold(text).split())

    folded = {o: [(f, key(f)) for f in fs if key(f)] for o, fs in options.items()}
    for qs, qe in _quote_spans(quote, plain, near):
        if plain[qe:].strip():
            continue  # the sample goes on: read by :func:`continued`
        for s, _e in ws:
            if not qs <= s < qe:
                continue
            t = key(plain[s:qe])
            hits = {
                o: [f for f, k in fs if len(k) > len(t) and k.startswith(t)]
                for o, fs in folded.items()
            }
            hits = {o: fs for o, fs in hits.items() if fs}
            if hits:
                return next(iter(hits.items())) if len(hits) == 1 else None
    return None
