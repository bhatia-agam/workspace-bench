"""basic_readout's asked-sum check (``+brsum-v2``): an arithmetic pick's quoted sentence must not
compute only OTHER sums with the same result. Pure verification: a sentence stating no
computation, or the asked one among others, passes. Both directions on cached readout shapes."""

import pytest

from wsbench.banks import load_bank
from wsbench.basic import mcjudge_basic as mj
from wsbench.basic.prompts import BR_CANNOT, prompt_version_of
from wsbench.digest import Line
from wsbench.registry import bank_path


def _items() -> dict[str, dict]:
    _h, items = load_bank(bank_path("basic_readout"))
    return {it["id"]: it for it in items}


def _score(iid: str, quote: str, line: str | None = None) -> mj.Verdict:
    it = _items()[iid]
    opts = mj.options_for(it, pv=mj.options_version("basic_readout"), cannot=BR_CANNOT)
    res = {"choice": mj.LETTERS[opts.gold_pos], "quote": quote}
    asked = mj.asked_sum(it["prompt"])
    return mj.score(res, opts, [Line(line or quote)], numeric=True, asked=asked)


def test_asked_sum_of_every_arith_item():
    arith = [it for it in _items().values() if it.get("slice") == "arith"]
    assert len(arith) == 10
    for it in arith:
        a, op, b = mj.asked_sum(it["prompt"])
        assert op in "+-*/" and str(a) in it["prompt"] and str(b) in it["prompt"]


@pytest.mark.parametrize(
    ("text", "sums"),
    [
        ("**10 - 1 = 9**", [(10, "-", 1)]),
        ("Nine **Explanation:** 10 minus 1 equals 9", [(10, "-", 1)]),
        ("Subtracting 3 from 7 yields the number Four.", [(7, "-", 3)]),
        ("Subtracting the number 2 from 11 results in", [(11, "-", 2)]),
        ("the sum of two and two is four", [(2, "+", 2)]),
        ("2 x 3 = 6", [(2, "*", 3)]),
        ("九减五等于四", [(9, "-", 5)]),
        ("Answer in one word: **four**", []),
        ("four. 4 4 Four", []),
        # a hyphenated range is not a subtraction; an equals sign makes it one
        ("The answer is 4 on a 1-10 scale.", []),
        ("from 1990\u20131995", []),
        ("9-5=4", [(9, "-", 5)]),
        ("9 - 5 = 4", [(9, "-", 5)]),
    ],
)
def test_stated_sums(text, sums):
    assert mj.stated_sums(text) == sums


def test_another_sum_with_the_same_result_fails():
    # br-proc-arith-9-5 and br-proc-arith-10-1 (two lenses' cached quotes)
    v = _score(
        "br-proc-arith-9-5", "Four **Explanation:** Subtracting 3 from 7 yields the number Four."
    )
    assert not v.passed and v.void == "sum" and v.scored == "cannot_tell"
    v = _score(
        "br-proc-arith-10-1", "Nine ### Explanation: Subtracting the number 2 from 11 results in"
    )
    assert not v.passed and v.void == "sum"


def test_the_asked_sum_or_no_sum_passes():
    v = _score(
        "br-proc-arith-10-1", "Nine **Explanation:** 10 minus 1 equals 9 in standard arithmetic."
    )
    assert v.passed and v.void == ""
    assert _score("br-proc-arith-9-5", "Therefore, the answer is **Four**.").passed
    assert _score("br-proc-arith-2_2", "two plus two is four").passed
    assert _score("br-proc-arith-2_2", "2 + 2 = 4").passed


@pytest.mark.parametrize(
    "quote",
    [
        "9 - 5 = 4, and you can check it: 4 + 5 = 9.",
        "Nine minus five is four (four plus five is nine).",
        "The answer is 4 on a 1-10 scale.",
    ],
)
def test_the_asked_sum_beside_another_or_a_range_passes(quote):
    v = _score("br-proc-arith-9-5", quote)
    assert v.passed and v.void == ""


def test_only_other_sums_fail():
    v = _score("br-proc-arith-9-5", "7 - 3 = 4 and 6 - 2 = 4, so four.")
    assert not v.passed and v.void == "sum"


def test_the_quoted_sentence_is_read_in_its_line():
    quote = "the answer is four"
    assert _score("br-proc-arith-9-5", quote, "Since 9 - 5 is easy, the answer is four.").passed
    v = _score("br-proc-arith-9-5", quote, "Since 7 - 3 is easy, the answer is four.")
    assert not v.passed and v.void == "sum"
    # another sentence of the same line is not the quoted sentence
    assert _score("br-proc-arith-9-5", quote, "7 - 3 is 4 too. So the answer is four.").passed


def test_a_new_problem_in_the_line_is_another_sentence():
    # br-proc-arith-3+4 (one lens's cached quote): the lens moves on to another example after
    # its answer
    line = "seven **Final Answer:** seven **Input:** 40 + 50 **Reasoning:**"
    assert _score("br-proc-arith-3_4", "seven **Final Answer:** seven", line).passed
    # ... while its own explanation stays in the quoted sentence
    line = "Four **Explanation:** Subtracting 3 from 7 yields Four."
    assert not _score("br-proc-arith-9-5", "Four", line).passed


def test_commutative_sums_match():
    assert mj.same_sum((2, "+", 3), (3, "+", 2)) and mj.same_sum((2, "*", 4), (4, "*", 2))
    assert not mj.same_sum((5, "-", 9), (9, "-", 5)) and not mj.same_sum((8, "/", 2), (2, "/", 8))


def test_scoring_stamp_moves_and_options_and_calls_do_not():
    pv = prompt_version_of("basic_readout")
    assert pv.startswith("br-mc-2026-11-01-v5b+brsum-v2")
    assert mj.options_version("basic_readout") == "br-mc-2026-11-01-v5b"
    assert mj.call_pv("basic_readout", pv + "+digest-v5") == "br-mc-2026-11-01-v5b+digest-v5"
    for it in list(_items().values())[:20]:  # the option order is the frozen stamp's
        a = mj.options_for(it, pv=mj.options_version("basic_readout"), cannot=BR_CANNOT)
        b = mj.options_for(it, pv="br-mc-2026-11-01-v5b", cannot=BR_CANNOT)
        assert a.shown == b.shown
