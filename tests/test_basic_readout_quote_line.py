# ruff: noqa: RUF001
"""basic_readout's quote rule (``+qline-v2``): the quote verifies by ``digest.quote_ok``
(markdown-insensitive), else near-verbatim (``nearquote.close_lines``), and names the pick read in
the line it came from: through the line only when the quote was cut mid-name, where the line
continues it into the pick or the sample ends inside a name only the pick's forms start with.
Both directions on cached quote voids (bread, ghibli, type of dance)."""

from wsbench.banks import load_bank
from wsbench.basic import mcjudge_basic as mj
from wsbench.basic.prompts import BR_CANNOT
from wsbench.digest import Line
from wsbench.registry import bank_path


def _score(iid: str, pick: str, quote: str, *lines: str) -> mj.Verdict:
    _h, items = load_bank(bank_path("basic_readout"))
    it = next(i for i in items if i["id"] == iid)
    o = mj.options_for(it, pv=mj.options_version("basic_readout"), cannot=BR_CANNOT)
    res = {"choice": mj.LETTERS[o.shown.index(pick)], "quote": quote}
    return mj.score(res, o, [Line(t) for t in lines or (quote,)], numeric=False)


def test_markdown_inside_the_quote_names_the_option():
    q = "My favorite Studio Ghibli film is **_Spirited Away_**"
    v = _score("br-imp-ghibli", "Spirited Away", q, q + ", without question.")
    assert v.passed and v.form_via == "quote"


def test_quote_cut_mid_name_passes_through_its_line():
    line = "I'd say **sourdough**, with its tangy crust."
    v = _score("br-imp-bread", "sourdough", "I'd say **sourd", line)
    assert v.passed and v.form_via == "line"
    v = _score("br-imp-typeofdance", "salsa", "I’d say **S", "I’d say **Salsa**, for its energy.")
    assert v.passed and v.form_via == "line"


def test_a_continuation_into_another_option_does_not_rescue():
    line = "I'd say a **baguette**, though sourdough is lovely too."
    v = _score("br-imp-bread", "sourdough", "I'd say a **b", line)
    assert not v.passed and v.void == "quote"
    # the quote run on to the end of the pick's name is read like a verified quote: an option
    # named later in the line does not void it
    line = "I'd say **sourdough**, or maybe a **baguette**."
    assert _score("br-imp-bread", "sourdough", "I'd say **sourd", line).passed


def test_a_quote_cut_by_the_end_of_its_sample():
    # the cached digest lines: each sample stops inside the name. "sourd" begins only sourdough's
    # forms (credited); "S" begins salsa and swing (ambiguous: no credit)
    line = "Sourdough As an AI, I don't have personal preferences, but I can share that sourd"
    v = _score("br-imp-bread", "sourdough", "I can share that sourd", line)
    assert v.passed and v.form_via == "line"
    line = "As an AI, I don't eat bread, but if I had to choose, I’d say **sourd"
    assert _score("br-imp-bread", "sourdough", "I’d say **sourd", line).passed
    # the pick must be the option the trailing words begin
    assert not _score("br-imp-bread", "challah", "I’d say **sourd", line).passed
    line = (
        "Salsa As an AI, I don’t have personal preferences, but I find all dance styles "
        "fascinating. If I had to choose one that best reflects my nature, I’d say **S"
    )
    v = _score("br-imp-typeofdance", "salsa", "I’d say **S", line)
    assert not v.passed and v.void == "quote"


def test_one_article_between_the_quote_and_the_name():
    line = "My favourite bread is a **sourdough** with a tangy crust."
    v = _score("br-imp-bread", "sourdough", "My favourite bread is", line)
    assert v.passed and v.form_via == "line"


def test_a_fact_only_quote_is_not_rescued():
    line = "Sourdough is my favourite: a tangy crust and an open crumb."
    v = _score("br-imp-bread", "sourdough", "a tangy crust and an open crumb", line)
    assert not v.passed and v.void == "quote"


def test_one_line_continuing_the_quote_is_enough():
    quote = "My favourite bread is"
    lines = [f"My favourite bread is **baguette** ({k})." for k in range(3)]
    v = _score("br-imp-bread", "sourdough", quote, *lines, "My favourite bread is **sourdough**.")
    assert v.passed and v.form_via == "line"
    assert not _score("br-imp-bread", "sourdough", quote, *lines).passed


def test_another_line_naming_the_option_does_not_rescue():
    v = _score(
        "br-imp-bread", "sourdough", "I'd say **sourd", "I'd say **sourd, I think", "sourdough!"
    )
    assert not v.passed and v.void == "quote"


def test_near_quote_is_read_in_its_line():
    line = "Honestly, my favourite bread of all is a fresh sourdough loaf from the bakery."
    quote = "So my favourite bread of all is a fresh sourdough loaf from the bakery!"
    v = _score("br-imp-bread", "sourdough", quote, line)
    assert v.passed and v.quote_near and v.form_via == "block"
    # a near quote whose matched block stops before the name falls back to its line
    line2 = "Honestly, my favourite bread of all is a fresh loaf from the bakery: sourdough."
    quote2 = "So my favourite bread of all is a fresh loaf from the bakery!"
    v = _score("br-imp-bread", "sourdough", quote2, line2)
    assert v.passed and v.quote_near and v.form_via == "line"


def test_stamp_carries_the_rule_and_options_and_calls_do_not_move():
    from wsbench.basic.prompts import prompt_version_of

    pv = prompt_version_of("basic_readout")
    assert "+qline-v2" in pv and mj.options_version("basic_readout") == "br-mc-2026-11-01-v5b"
    assert mj.call_pv("basic_readout", pv) == "br-mc-2026-11-01-v5b"
