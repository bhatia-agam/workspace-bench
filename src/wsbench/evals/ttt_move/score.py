"""ttt_move scoring: the seeded option order, one cell's verdict under the quote rule, the
gate-only ``ati_pass``, and the per-item best-of-layers row."""

import random
from collections.abc import Sequence
from typing import Any

from wsbench.family import tri_state

from .prompts import LETTERS, NONE
from .quote import check_quote, stated_moves


def empties(board: str) -> list[int]:
    """The empty squares of a board string (``X....X..O``: ``.`` = empty), in square order."""
    return [i for i, c in enumerate(board) if c == "."]


def shuffled_options(empty: Sequence[int], key: str) -> list[int]:
    """The item's options (empty squares) in the source's seeded order; ``key`` seeds it
    (source ``options.shuffled_options``, called with ``f"{id}|judge"``)."""
    order = list(empty)
    random.Random(key).shuffle(order)
    return order


def judge_options(item: dict[str, Any]) -> list[int]:
    return shuffled_options(empties(item["board"]), f"{item['id']}|judge")


def letter_to_square(letter: str | None, options: Sequence[int]) -> int | None:
    """Source ``options.letter_to_square``: a letter past the option list is no pick."""
    if not letter or letter not in LETTERS:
        return None
    k = LETTERS.index(letter)
    return options[k] if k < len(options) else None


def clean_quote(quote: str) -> str:
    """The source parser's quote cleanup: trim, drop backticks, drop one pair of matching
    surrounding quote marks."""
    q = quote.strip().strip("`").strip()
    if len(q) >= 2 and q[0] == q[-1] and q[0] in "\"'":
        q = q[1:-1]
    return q


def gold_stated(samples: Sequence[str], gold_name: str, names: Sequence[str]) -> bool:
    """Some sample states the gold as the move under the option-list-free rule."""
    return any(gold_name in stated_moves(s, names) for s in samples)


def cell_verdict(
    res: dict[str, Any] | None,
    *,
    samples: Sequence[str],
    options: Sequence[int],
    names: Sequence[str],
    gold: int,
) -> dict[str, Any]:
    """One judge answer. ``correct`` = a letter (not NONE) whose square is the gold AND whose
    quote passes ``check_quote`` against every board name with the options as the two-option
    guard. ``ati`` (gate only) = the letter is the gold ignoring the quote check, OR some sample
    states the gold under ``stated_moves`` (any sample, whatever the judge answered)."""
    ati_stated = gold_stated(samples, names[gold], names)
    if res is None:
        return _verdict(False, None, False, "unavailable", "", ati_stated)
    answer = res.get("answer")
    pick = None if answer == NONE else letter_to_square(answer, options)
    quote = clean_quote(str(res.get("quote") or ""))
    if pick is None:
        return _verdict(True, None, False, "none", quote, ati_stated)
    chk = check_quote(quote, samples, names[pick], names, [names[s] for s in options])
    return _verdict(
        True, pick, chk.ok and pick == gold, chk.reason, quote, pick == gold or ati_stated
    )


def _verdict(
    judged: bool, pick: int | None, correct: bool, why: str, quote: str, ati: bool
) -> dict[str, Any]:
    return {
        "judged": judged,
        "pick": pick,
        "correct": correct,
        "why": why,
        "quote": quote,
        "ati": ati,
    }


def item_row(
    item: dict[str, Any],
    options: list[int],
    verdicts: dict[int, dict[str, Any]],
    *,
    n_missing: int,
    empty_layers: list[int],
) -> dict[str, Any]:
    """``pass`` = the judge is right at some layer (tri-state: undecided when no layer hits and
    a cell is unjudged or missing; an empty cell is a judged negative). ``ati_pass`` = some cell's
    gate-only ``ati`` holds."""
    names = item["names_a"]
    hits = sorted(L for L, v in verdicts.items() if v["correct"])
    incomplete = n_missing > 0 or any(not v["judged"] for v in verdicts.values())
    return {
        "id": item["id"],
        "kind": item.get("kind"),
        "mover": item.get("mover"),
        "gold": item["label_name"],
        "options": [names[s] for s in options],
        "pass": tri_state(bool(hits), incomplete),
        "ati_pass": any(v["ati"] for v in verdicts.values()),
        "hit_layers": hits,
        "earliest_layer": hits[0] if hits else None,
        "empty_layers": sorted(empty_layers),
        "pick_by_layer": {
            str(L): None if v["pick"] is None else names[v["pick"]]
            for L, v in sorted(verdicts.items())
        },
        "quote_by_layer": {str(L): v["quote"] for L, v in sorted(verdicts.items())},
        "check_by_layer": {str(L): v["why"] for L, v in sorted(verdicts.items())},
    }
