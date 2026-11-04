"""association gate steps 3 and 4b: a proper-noun gold form counts only with its capital and never
hyphen-glued; a quote holding it only as a common word fails without a re-judge."""

from wsbench.evals.association.judge import quote_names_gold

PENTAGON = ["Pentagon", "Pentagon building", "The Pentagon", "五角大楼"]


def test_proper_noun_needs_its_capital():
    assert quote_names_gold("they met at the Pentagon on Monday", PENTAGON)
    assert not quote_names_gold("failed to find a key for the pentagon", PENTAGON)
    assert not quote_names_gold("PENTAGON", PENTAGON)


def test_hyphen_glued_form_is_a_modifier():
    assert not quote_names_gold("a pentagon-shaped building", PENTAGON)
    assert not quote_names_gold("the Pentagon-shaped facility", PENTAGON)
    assert not quote_names_gold("a pentagonal building", PENTAGON)


def test_lowercase_gold_still_case_blind_and_cjk_substring():
    assert quote_names_gold("The Carnaval parade", ["carnaval"])
    assert quote_names_gold("他们去了五角大楼开会", PENTAGON)


def test_lowercase_proper_noun_quote_fails_without_rejudge():
    from wsbench import digest
    from wsbench.evals.association.judge import gate_gold

    q = "failed to find a key for the pentagon"
    line = digest.Line(
        text=q + " ⁞ the pentagon-shaped building had five doors", where="[L36 pos 49]", layer=36
    )
    out = gate_gold(
        q, [line], forms=PENTAGON, others=["White House", "Kremlin"], sampling="bullet4"
    )
    assert out == "gold_common_word"
    ok = gate_gold(
        "they met at the Pentagon",
        [digest.Line(text="they met at the Pentagon", layer=36)],
        forms=PENTAGON,
        others=["White House"],
        sampling="bullet4",
    )
    assert ok == "gold_listed_form"
