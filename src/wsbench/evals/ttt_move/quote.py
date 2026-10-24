"""The ttt_move verbatim move-quote rule, ported verbatim from the source repo's
``global_workspace.olens_suite.ttt_move.quote`` (the rule is stated in the family README)."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_VERBS = (
    r"play|plays|playing|played|take|takes|taking|took|choose|chooses|choosing|chose|chosen|"
    r"pick|picks|picking|picked|select|selects|selecting|selected|place|places|placing|placed|"
    r"put|puts|putting|mark|marks|marking|marked|claim|claims|claiming|claimed|occupy|occupies|"
    r"occupying|go with|goes with|going with|go for|goes for|going for|opt for|opting for|"
    r"move to|moves to|moving to|move is|move:|answer is|answer:|reply is|reply:|respond with|"
    r"responds with|responding with|reply with|replies with|replying with|my move|next move|"
    r"the move|i'll take|i will take|output|outputs|outputting|answer|answering|respond|"
    r"responds|responding|move"
)
_NOUNS = r"move|play|choice|answer|pick|option|square to (?:play|take)|reply|response"
_NEGATION = re.compile(
    r"\b(?:not|never|avoid|avoids|avoiding|instead of|rather than)\b|n't\b", re.I
)
_SEG_SPLIT = re.compile(r"\n+|(?<=[.!?;])\s+")
_MARKUP = re.compile(r"[\s*_`'\"\u201c\u201d\u2018\u2019.,:;!?()\[\]<>#-]+")


def _negated(prefix: str) -> bool:
    """A negation in the same clause as what follows ``prefix`` (clause = text after the last
    ``.;!?,`` or newline)."""
    clause = re.split(r"[.;!?,\n]", prefix)[-1]
    return bool(_NEGATION.search(clause))


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _word(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", re.IGNORECASE)


def states_move(text: str, name: str) -> bool:
    """A non-negated move statement naming ``name`` inside ``text``. Three forms:
    a move verb before the name ("play walrus", "answer: walrus"); the name followed by a move
    predicate ("walrus is the best move", "walrus is the winning square"); a move noun followed
    by the name ("the move that completes the row is walrus")."""
    nm = rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])"
    pats = (
        rf"\b(?:{_VERBS})(?![A-Za-z])[^.!?\n]{{0,40}}?{nm}",
        rf"{nm}[^.!?\n]{{0,60}}?\b(?:is|would be|seems|looks like|as)\b[^.!?\n]{{0,40}}?"
        rf"\b(?:{_NOUNS}|win|winning|best|correct|optimal|right)\b",
        rf"\b(?:{_NOUNS})\b[^.!?\n]{{0,40}}?(?:\bis\b|:|=)[^.!?\n]{{0,15}}?{nm}",
    )
    for pat in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            if not _negated(text[max(0, m.start() - 30) : m.start()] + m.group(0)):
                return True
    return False


def is_restatement(segment: str, names: Iterable[str]) -> bool:
    if re.search(r"\((?:X|O)\)|---", segment) or segment.count("|") >= 2:
        return True
    return sum(bool(_word(n).search(segment)) for n in set(names)) >= 3


def square_mentions(sample: str, names: Sequence[str]) -> list[str]:
    """Square names mentioned in ``sample`` outside board restatements, in order of first
    appearance (each name once)."""
    out: list[str] = []
    for seg in _SEG_SPLIT.split(sample):
        if not seg.strip() or is_restatement(seg, names):
            continue
        hits = sorted((m.start(), n) for n in names for m in _word(n).finditer(seg))
        for _, n in hits:
            if n not in out:
                out.append(n)
    return out


def is_bare_name(quote: str, name: str) -> bool:
    return _MARKUP.sub("", quote).lower() == re.sub(r"\s+", "", name).lower()


_LEAD_MARKUP = r"[\s*_`'\"\u201c\u201d\u2018\u2019#>•.,:;!-]*"
_TRAILER = re.compile(
    rf"^{_LEAD_MARKUP}(?:\([^()]*(?:\)|$){_LEAD_MARKUP})?(?:(?:#|//|\||\s-\s|\s—\s).*)?$",
    re.DOTALL,
)


def leads_with_name(quote: str, name: str) -> bool:
    """The quote OPENS with the bare name and the rest is only markup, one parenthetical (closed,
    or cut off at the end of the quote) and/or a comment introduced by ``#``, ``//``, ``|`` or a
    spaced dash (``"walrus** (the corner)"``, ``"walrus  # blocks the row"``,
    ``"walrus | Reason: …"``), none of it negated. Free text continuing the sentence after the
    name (``"walrus (top-left) to create a line"``) does not qualify."""
    body = re.sub(r"^[\s*_`'\"\u201c\u201d\u2018\u2019#>•-]+", "", quote)
    m = re.match(rf"{re.escape(name)}(?![A-Za-z])", body, re.IGNORECASE)
    if m is None:
        return False
    rest = body[m.end() :]
    return _TRAILER.match(rest) is not None and not _NEGATION.search(rest)


@dataclass(frozen=True)
class QuoteCheck:
    ok: bool
    reason: str  # "move" | "bare_leading" | "bare_only" | failure reason


def check_quote(
    quote: str,
    samples: Sequence[str],
    name: str,
    square_names: Sequence[str],
    option_names: Sequence[str] | None = None,
) -> QuoteCheck:
    """Validate a judge's (option name, quote) against the readout samples. ``square_names``
    are every square name on the board (plus any extra scored names, e.g. §5's C);
    ``option_names`` (default: ``square_names``) are the MC options — a move quote naming two or
    more of them does not single out one move and is rejected."""
    q = norm_ws(quote)
    if not q:
        return QuoteCheck(False, "empty quote")
    holders = [s for s in samples if q in norm_ws(s)]
    if not holders:
        return QuoteCheck(False, "quote not verbatim in any sample")
    if not _word(name).search(q):
        return QuoteCheck(False, "quote does not contain the option name")
    opts = square_names if option_names is None else option_names
    if states_move(q, name):
        if sum(bool(_word(o).search(q)) for o in set(opts)) >= 2:
            return QuoteCheck(False, "move quote names two or more options")
        # the quote must not sit inside a negation ("don't <quote>") in any sample holding it
        for s in holders:
            ns = norm_ws(s)
            i = ns.index(q)
            if not _negated(ns[max(0, i - 30) : i]):
                return QuoteCheck(True, "move")
        return QuoteCheck(False, "move statement is negated in context")
    if is_bare_name(q, name) or leads_with_name(q, name):
        for s in holders:
            ments = square_mentions(s, square_names)
            if ments and ments[0] == name:
                return QuoteCheck(True, "bare_leading" if len(ments) > 1 else "bare_only")
        return QuoteCheck(False, "bare name is not the leading square mention")
    return QuoteCheck(False, "quote neither states the move nor is a bare leading name")


def stated_moves(sample: str, names: Sequence[str]) -> set[str]:
    """Option-list-free application of the rule to ONE sample: every name the sample states as
    the move (move statement outside restatements), plus its leading square mention when that
    mention is a bare name (the sample opens with it, markup aside)."""
    out: set[str] = set()
    for seg in _SEG_SPLIT.split(sample):
        if not seg.strip() or is_restatement(seg, names):
            continue
        for n in names:
            if states_move(seg, n):
                out.add(n)
    ments = square_mentions(sample, names)
    if ments:
        body = re.sub(r"^[\s\-*•#>]+", "", sample)
        head = re.split(r"[\n.!?;:,(—]| - | # ", body, maxsplit=1)[0]
        if is_bare_name(head, ments[0]):
            out.add(ments[0])
    return out


def stated_rate(samples: Sequence[str], name: str, names: Sequence[str]) -> float:
    """Fraction of samples that state ``name`` as the move (``name`` must be in ``names``)."""
    if not samples:
        return 0.0
    return sum(name in stated_moves(s, names) for s in samples) / len(samples)
