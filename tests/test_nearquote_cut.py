"""``nearquote.continued``: a line credits a quote only when the quote was cut mid-name and the
line continues it into a form of the answer. Generic cases, both directions; the family gates'
own cases are in their quote-line tests."""

from wsbench import digest, mc
from wsbench.digest import Line
from wsbench.nearquote import _folded, _plain, continued, cuts, sample_end_prefix

FORMS = ["Ludwig van Beethoven", "Beethoven", "贝多芬", "Angara River"]


def _run_on(quote: str, text: str, *, near: bool = False) -> list[str]:
    return continued(quote, Line(text), FORMS, lambda t, fs: mc.form_in(t, fs), near=near)


def test_a_name_that_continues_the_quote_is_found():
    assert _run_on("the composer was", "So the composer was **Beethoven**.") == [
        "the composer was Beethoven"
    ]
    assert _run_on("the composer was Ludwig", "the composer was Ludwig van Beethoven") == [
        "the composer was Ludwig van Beethoven"
    ]
    assert _run_on("I'd say Beeth", "I'd say Beethoven!") == ["I'd say Beethoven"]
    assert _run_on("the composer is", "the composer is: “Beethoven”") == [
        "the composer is: “Beethoven"
    ]
    assert _run_on("作曲家是贝多", "这首奏鸣曲的作曲家是贝多芬。") == ["作曲家是贝多芬"]


def test_one_article_may_stand_between_the_quote_and_the_name():
    assert _run_on("only outflow is", "Its only outflow is the **Angara River**.") == [
        "only outflow is the Angara River"
    ]
    assert _run_on("the composer was", "the composer was a Beethoven of his age") == [
        "the composer was a Beethoven"
    ]
    assert _run_on("only outflow is", "Its only outflow is the mighty Angara River.") == []
    assert _run_on("only outflow is", "Its only outflow is the. Angara River") == []


def test_a_name_elsewhere_in_the_line_is_not_a_continuation():
    assert _run_on("was born in 1770", "Ludwig van Beethoven was born in 1770.") == []
    assert _run_on("was born in 1770", "He was born in 1770. Beethoven wrote it.") == []
    assert _run_on("was born in 1770", "He was born in 1770 and Beethoven wrote it.") == []
    assert _run_on("was Ludwig van", "Beethoven. It was Ludwig van") == []  # ends its sample
    assert _run_on("was Ludwig van", "it was Ludwig van ⁞ Beethoven") == []  # next bullet
    assert _run_on("born in 1770.", "born in 1770. Beethoven") == []  # the quote ends a sentence


def test_every_place_the_quote_occurs_is_read():
    text = "the composer was Mozart; the composer was Beethoven"
    assert _run_on("the composer was", text) == ["the composer was Beethoven"]


def test_a_near_quote_is_cut_where_its_matched_block_ends():
    line = "In the end, the man who composed the Moonlight Sonata was a genius: Beethoven."
    quote = "So the man who composed the Moonlight Sonata was a genius"
    assert _run_on(quote, line, near=True) == [
        "the man who composed the Moonlight Sonata was a genius: Beethoven"
    ]


def test_token_lines_continue_nothing():
    ln = Line("Beeth | Beethoven", pieces=("Beeth", "Beethoven"))
    assert cuts("Beeth", ln) == []


def test_the_cut_is_read_in_fold_quote_positions():
    for text in ("Ünïcödé **ﬁne** straße ⁞ İstanbul\u00a0Æther", "a  _b_ `c`  ⁞  d"):
        assert _folded(_plain(text))[0] == digest.fold_quote(text)


OPTIONS = {
    "van Gogh": ["Vincent van Gogh", "Van Gogh"],
    "Vermeer": ["Johannes Vermeer", "Vermeer"],
    "salsa": ["salsa"],
    "swing": ["swing"],
}


def test_a_quote_cut_by_the_end_of_its_sample_names_the_one_option_it_begins():
    line = Line("is Vincent van Gogh. The artist who painted it is Vincent van")
    got = sample_end_prefix("The artist who painted it is Vincent van", line, OPTIONS)
    assert got == ("van Gogh", ["Vincent van Gogh"])
    line = Line("I'd say **sourd")  # mid-word, markdown at the end
    assert sample_end_prefix("I'd say **sourd", line, {"sourdough": ["sourdough"]})[0] == (
        "sourdough"
    )


def test_an_ambiguous_or_unended_sample_end_prefix_names_nothing():
    assert sample_end_prefix("I'd say **S", Line("Salsa. I'd say **S"), OPTIONS) is None
    line = Line("The artist who painted it is Vincent van, I think.")  # the sample goes on
    assert sample_end_prefix("The artist who painted it is Vincent van", line, OPTIONS) is None
    line = Line("The painter was born in 1853")  # a fact: no form starts that way
    assert sample_end_prefix("The painter was born in 1853", line, OPTIONS) is None
    ln = Line("Vincent | van", pieces=("Vincent", "van"))
    assert sample_end_prefix("van", ln, OPTIONS) is None  # a token list ends no sample
