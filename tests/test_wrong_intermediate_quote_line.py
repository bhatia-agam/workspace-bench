"""wrong_intermediate's quote rule (``qline-v1``): the quote is verified by ``digest.quote_ok``
(markdown-insensitive), else near-verbatim (``nearquote.close_lines``), and it names the gold
reasonably and unambiguously, read in the line it came from. Both directions, on cached digest
lines whose quotes were cut at a sample boundary ("Vincent van", "Ludwig van")."""

from wsbench import digest
from wsbench.evals.wrong_intermediate import judge as wb
from wsbench.evals.wrong_intermediate import prompts as wp

VAN_GOGH = "painting_creator-Q586035-birth_year"  # gold Vincent van Gogh
BEETHOVEN = "composition_composer-Q1977772-birth_city"  # gold Beethoven, contrast Mozart


def _item(iid: str) -> dict:
    return next(it for it in wb.load_items() if it["id"] == iid)


def _decide(iid: str, quote: str, texts: list[str]) -> dict:
    it = _item(iid)
    res = {"choice": wb.positions(it)[0], "quote": quote, "rival_quote": ""}
    return wb.decide(res, it, [digest.Line(t) for t in texts])


# two lenses' cached sample lines (the quote is the sample's cut-off end)
VAN_LINE = (
    "is Vincent van Gogh. The painting is called The Narrow Street. Van Gogh painted The Narrow "
    "Street in 1885. The artist who painted The Narrow Street is Vincent van"
)
LUDWIG_LINE = (
    "Ludwig van Beethoven. The genre of the musical composition Sonata No. 14 is a piano sonata. "
    "The person who wrote Sonata No. 14 was Ludwig van"
)


def test_cut_quotes_pass_through_their_line():
    v = _decide(VAN_GOGH, "The artist who painted The Narrow Street is Vincent van", [VAN_LINE])
    assert v["credited"] and v["form_via"] == "line" and v["quote_verified"]
    v = _decide(BEETHOVEN, "The person who wrote Sonata No. 14 was Ludwig van", [LUDWIG_LINE])
    assert v["credited"] and v["form_via"] == "line"


def test_a_line_that_also_names_another_candidate_does_not_rescue():
    line = LUDWIG_LINE + ". Or was it Wolfgang Amadeus Mozart?"
    v = _decide(BEETHOVEN, "The person who wrote Sonata No. 14 was Ludwig van", [line])
    assert not v["credited"] and v["pick"] == "gold_uncredited" and v["form_ok"] is False


def test_a_line_naming_nobody_does_not_rescue():
    v = _decide(BEETHOVEN, "was born in Bonn", ["The composer was born in Bonn in 1770."])
    assert not v["credited"] and v["form_via"] is None


def test_the_quote_line_must_hold_the_quote():
    # another line naming the gold is no rescue: only the line the quote came from counts
    texts = ["The composer was born in Bonn in 1770.", "Ludwig van Beethoven wrote it."]
    v = _decide(BEETHOVEN, "was born in Bonn", texts)
    assert not v["credited"]


def test_a_quote_naming_another_candidate_never_passes():
    line = "Ludwig van Beethoven or Wolfgang Amadeus Mozart wrote it."
    v = _decide(BEETHOVEN, "Beethoven or Wolfgang Amadeus Mozart", [line])
    assert not v["credited"]


def test_markdown_dropped_from_the_quote_still_verifies():
    v = _decide(BEETHOVEN, "the sonata is by Beethoven", ["The sonata is by **Beethoven**."])
    assert v["credited"] and v["quote_verified"] and v["form_via"] == "quote"


def test_near_verbatim_quote_is_read_in_its_located_line():
    # one word off at an edge: the located line names the gold, the quote's own words do not count
    line = "In the end, the man who composed the Moonlight Sonata was Ludwig van Beethoven."
    v = _decide(BEETHOVEN, "the man who composed the Moonlight Sonata was Ludwig van", [line])
    assert v["quote_verified"] and v["credited"]  # verified exactly (a substring)
    quote = "So the man who composed the Moonlight Sonata was Ludwig van Beethoven."
    v = _decide(BEETHOVEN, quote, [line])
    assert (
        not v["quote_verified"] and v["quote_near"] and v["credited"] and v["form_via"] == "block"
    )
    # a near quote whose matched block stops before the name falls back to its line
    line = (
        "In the end, the man who composed the Moonlight Sonata was a genius: Ludwig van Beethoven."
    )
    quote = "So the man who composed the Moonlight Sonata was a genius"
    v = _decide(BEETHOVEN, quote, [line])
    assert v["quote_near"] and v["credited"] and v["form_via"] == "line"


def test_near_quote_whose_line_names_nobody_fails():
    line = "In the end, the man who composed the Moonlight Sonata was a great genius of music."
    quote = "So the man who composed the Moonlight Sonata was a great genius of music"
    v = _decide(BEETHOVEN, quote, [line])
    assert v["quote_near"] and not v["credited"]


def test_short_near_quotes_must_verify_exactly():
    v = _decide(BEETHOVEN, "Beethovn", ["by Beethoven"])
    assert not v["quote_verified"] and not v["quote_near"] and not v["credited"]


def test_stamp_carries_the_quote_rule_and_the_call_key_does_not():
    assert "+qline-v1+" in wp.PROMPT_VERSION and wp.QUOTE_RULE_VERSION == "qline-v1"
    assert wb._mc_version(wp.PROMPT_VERSION) == "wb-mc-2026-10-31r+rv-2026-10-31e"
