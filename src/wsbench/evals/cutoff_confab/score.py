"""cutoff_confab's regex scorer: an port of the source's per-option span matcher with
exclusive longest match (``olens_suite/cutoff_confab/matching.py``) and its cell rules
(``scoring.py``). The rules are stated in ``evals/cutoff_confab/README.md``."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from wsbench.multitoken.regex import fold  # identical to the source's bank.matching.fold

_CJK_NUMERAL = re.compile(r"^[零〇一二两兩三四五六七八九十百千万亿点]+$")
_CJK_HANGUL = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_WORDY = re.compile(r"[^\W_]+(?:[\s\-'][^\W_]+)*")
_STRIP = re.compile(r"US\$|[$,%\s]")
_DIGIT_GUARD = r"(?<!\d)(?<!\d[.,])"  # a form starting with a digit never starts mid-number
# a word character that is NOT CJK/Hangul: numbers may touch CJK text (12个, 约16, 2026年, 1199元)
_NW = r"[^\W぀-ヿ㐀-鿿가-힯]"
_NUM_PRE = r"(?<!\d[.,])(?<!-)(?<!" + _NW + r")"  # a fullwidth comma folds to ","
_NUM_POST = r"(?![.,]?\d)(?!" + _NW + r")"


def _int_body(digits: str) -> str:
    """Digits with an optional thousands separator (comma or space) at thousands positions."""
    head = len(digits) % 3 or 3
    groups = [digits[:head]] + [digits[i : i + 3] for i in range(head, len(digits), 3)]
    return "[ ,]?".join(re.escape(g) for g in groups)


def compile_form(form: str) -> re.Pattern[str] | None:
    """The span pattern for one alias form over folded text; ``None`` if the form is dropped."""
    f = form.strip()
    if not f:
        return None
    num = _STRIP.sub("", f)
    if re.fullmatch(r"\d+", num):
        return re.compile(_NUM_PRE + _int_body(num) + _NUM_POST)
    if re.fullmatch(r"\d+\.\d+", num):
        whole, frac = num.split(".")
        return re.compile(_NUM_PRE + _int_body(whole) + r"\." + re.escape(frac) + _NUM_POST)
    if _CJK_NUMERAL.fullmatch(f):
        return None
    ff = fold(f)
    guard = _DIGIT_GUARD if ff[:1].isdigit() else ""
    if _CJK_HANGUL.search(f) or not _WORDY.fullmatch(ff):
        return re.compile(guard + re.escape(ff))
    parts = [re.escape(w) for w in re.split(r"[\s\-]+", ff) if w]
    return re.compile(guard + r"(?<![^\W_])" + r"[\s\-]+".join(parts) + r"(?![^\W_])")


@dataclass(frozen=True)
class OptionForms:
    """All options' compiled forms for one item; scoring is exclusive longest match."""

    forms: tuple[tuple[str, re.Pattern[str]], ...]
    options: tuple[str, ...]

    @classmethod
    def build(cls, aliases: Mapping[str, Sequence[str]]) -> "OptionForms":
        """``aliases``: option -> forms (the option label itself is always added)."""
        forms: list[tuple[str, re.Pattern[str]]] = []
        for opt, fs in aliases.items():
            for f in sorted({opt, *fs}):
                pat = compile_form(f)
                if pat is not None:
                    forms.append((opt, pat))
        return cls(tuple(forms), tuple(aliases))

    def named(self, text: str) -> set[str]:
        """Options named in ``text``: all matches of all forms, longest first (then leftmost),
        a match kept only if it overlaps no kept span; the identical span claimed by two options
        credits neither."""
        t = fold(text)
        spans = [
            (m.start(), m.end(), opt)
            for opt, pat in self.forms
            for m in pat.finditer(t)
            if m.end() > m.start()
        ]
        spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
        kept: list[tuple[int, int, str]] = []
        contested: set[tuple[int, int]] = set()
        for a, b, opt in spans:
            clash = [(ka, kb, ko) for ka, kb, ko in kept if a < kb and ka < b]
            if clash:
                if any((ka, kb) == (a, b) and ko != opt for ka, kb, ko in clash):
                    contested.add((a, b))
                continue
            kept.append((a, b, opt))
        return {o for a, b, o in kept if (a, b) not in contested}

    def counts(self, samples: Iterable[str]) -> dict[str, int]:
        """``option -> number of samples naming it`` (exclusive per sample)."""
        c = dict.fromkeys(self.options, 0)
        for s in samples:
            for o in self.named(s):
                c[o] += 1
        return c


def token_bag_text(tokens: Sequence[str]) -> str:
    """A token lens's top-k list as ONE sample: tokens stripped and space-joined (byte-level
    display markers rendered first). Qwen splits digits, so multi-digit numbers never hit."""
    return " ".join(t.replace("Ġ", " ").replace("▁", " ").strip() for t in tokens)


def strict_win(counts: Mapping[str, int], gold: str) -> bool:
    """Gold named by strictly more samples than every other option (and by at least one)."""
    g = counts.get(gold, 0)
    return g > 0 and all(v < g for o, v in counts.items() if o != gold)


def plurality(counts: Mapping[str, int], gold: str) -> float:
    """Tie-split view: 1 if gold is the unique most-named option, 1/n if tied at the top."""
    top = max(counts.values(), default=0)
    if top == 0 or counts.get(gold, 0) != top:
        return 0.0
    return 1.0 / sum(1 for v in counts.values() if v == top)


def best_layer(wins_by_layer: Mapping[int, int]) -> int | None:
    """The bank layer: most strict wins at reply_start, ties to the earliest layer."""
    if not wins_by_layer:
        return None
    return max(sorted(wins_by_layer), key=lambda k: wins_by_layer[k])
