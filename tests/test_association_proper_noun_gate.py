"""association gate steps 3 and 4b: for a gold whose name is also a common word its scene invites
(``HOMOGRAPH_GOLDS``: pentagon), a form counts only with its capital and never hyphen-glued, and a
quote holding it only as the common word fails without a re-judge; every other gold is named in
any case, hyphen-glued forms included."""

import pytest

from wsbench import digest
from wsbench.evals.association import judge as aj
from wsbench.evals.association.judge import gate_gold, quote_names_gold

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


def test_only_listed_homograph_golds_take_the_rule():
    assert set(aj.HOMOGRAPH_GOLDS) == {"pentagon"}
    assert aj.homograph_gold({"id": "pentagon"})
    assert not aj.homograph_gold({"id": "bf-paris"})
    assert not aj.homograph_gold({})


def _line(text: str) -> digest.Line:
    return digest.Line(text=text, where="[L36 pos 49]", layer=36)


def test_lowercase_homograph_quote_fails_without_rejudge():
    q = "failed to find a key for the pentagon"
    line = _line(q + " ⁞ the pentagon-shaped building had five doors")
    kw = {"forms": PENTAGON, "others": ["White House", "Kremlin"], "sampling": "bullet4"}
    assert gate_gold(q, [line], homograph=True, **kw) == "gold_common_word"
    hy = "a pentagon-shaped building"
    assert gate_gold(hy, [_line(hy)], homograph=True, **kw) == "gold_common_word"
    ok = "they met at the Pentagon"
    assert gate_gold(ok, [_line(ok)], homograph=True, **kw) == "gold_listed_form"
    # without the flag the same quote is named case-blind, as for every other gold
    assert gate_gold(q, [line], **kw) == "gold_listed_form"


@pytest.mark.parametrize(
    ("iid", "quote"),
    [
        ("b3-as-barbecue", "grilling ribs at a bbq"),  # the alias "BBQ", lowercased
        ("bf-christmas", "gifts under the tree on christmas morning"),
        ("bf-paris", "a Paris-based fashion house"),  # hyphen-glued
    ],
)
def test_other_capitalised_golds_are_named_in_any_case(iid, quote):
    """A gold (or alias) with a capital but no common-word homograph is named case-blind and
    hyphen-glued, as before the rule: these quotes pass at step 3, never ``gold_common_word``."""
    it = next(i for i in aj.load_items() if i["id"] == iid)
    assert not aj.homograph_gold(it)
    shown, gp = aj.build_options(it)
    others = [o for k, o in enumerate(shown[:-1], start=1) if k != gp]
    out = gate_gold(
        quote,
        [_line(quote)],
        forms=aj.gold_forms(it),
        others=others,
        sampling="bullet4",
        rivals=aj.bank_concepts(aj.load_items()),
        homograph=aj.homograph_gold(it),
    )
    assert out == "gold_listed_form"
