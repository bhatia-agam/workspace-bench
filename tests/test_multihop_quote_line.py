"""multihop's quote rule (``bank-gate-r8``): the quote is verified by ``digest.quote_ok``
(markdown-insensitive), else near-verbatim (``nearquote.close_lines``), and names the gold
reasonably and unambiguously, read in the line it came from. Both directions."""

from wsbench import digest
from wsbench.banks import load_bank
from wsbench.basic import mcjudge_bank as mj
from wsbench.readouts import Cell
from wsbench.registry import REPO_ROOT


def _item(iid: str) -> dict:
    _h, items = load_bank(REPO_ROOT / "evals/multihop/items_v3.json")  # the cases' bank
    return next(it for it in items if it["id"] == iid)


def _v(iid: str, quote: str, *texts: str) -> dict:
    it = _item(iid)
    shown, g = mj.options_of("multihop", it)
    cells = [Cell(iid, 44, -1 - k, (t,), None, None) for k, t in enumerate(texts)]
    lines = digest.native_lines(cells)
    return mj.verdict({"choice": mj.LETTERS[g], "quote": quote}, shown, g, lines, it)


KATHMANDU = "bf-kathmandu-mountain"  # gold Nepal


def test_markdown_dropped_from_the_quote_still_verifies():
    v = _v(KATHMANDU, "Kathmandu is the capital of Nepal", "Kathmandu is the capital of **Nepal**.")
    assert v["quote_ok"] and v["correct"] and v["form_via"] == "quote"


def test_quote_cut_before_the_name_passes_through_its_line():
    line = "The country whose capital is Kathmandu is Nepal, home to the highest peak."
    v = _v(KATHMANDU, "The country whose capital is Kathmandu is", line)
    assert v["quote_ok"] and v["correct"] and v["form_via"] == "line"


def test_line_naming_another_option_does_not_rescue():
    it = _item(KATHMANDU)
    other = it["mc"]["distractors"][0]
    line = f"The country whose capital is Kathmandu is Nepal, not {other}."
    v = _v(KATHMANDU, "The country whose capital is Kathmandu is", line)
    assert not v["correct"] and v["form_via"] is None


def test_only_the_quotes_own_line_counts():
    v = _v(KATHMANDU, "capital is Kathmandu", "The capital is Kathmandu.", "Nepal is a country.")
    assert not v["correct"]


def test_near_verbatim_quote_is_read_in_its_line():
    line = "In fact, the country whose capital is Kathmandu is Nepal, in the Himalayas."
    quote = "So the country whose capital is Kathmandu is Nepal, in the Himalayas!"
    v = _v(KATHMANDU, quote, line)
    assert not v["quote_ok"] and v["quote_near"] and v["correct"] and v["form_via"] == "block"
    line2 = "In fact, the country whose capital is Kathmandu is in the Himalayas mountains."
    quote2 = "So the country whose capital is Kathmandu is in the Himalayas mountains"
    v = _v(KATHMANDU, quote2, line2)
    assert v["quote_near"] and not v["correct"]  # its line names no option


def test_unlocatable_quote_still_fails():
    v = _v(KATHMANDU, "Nepal is lovely", "Kathmandu is the capital.")
    assert not v["quote_ok"] and not v["quote_near"] and not v["correct"]


def test_number_line_rescue_reads_values():
    # nhop-spider-element: gold 8
    it = _item("nhop-spider-element")
    other = next(o for o in it["mc"]["distractors"] if o.isdigit())
    v = _v("nhop-spider-element", "A spider has", "A spider has 8 legs.")
    assert v["correct"] and v["form_via"] == "line"
    v = _v("nhop-spider-element", "A spider has", f"A spider has 8 legs, or {other}.")
    assert not v["correct"]


def test_gate_version_and_stamp():
    from wsbench.basic.prompts import prompt_version_of

    assert mj.GATE_VERSION == "bank-gate-r9"  # r9 (bank v5): the forms table's new entries
    assert prompt_version_of("multihop").startswith("bank-mc-2026-11-01-v3+bank-gate-r9")
    assert mj.call_pv("multihop", prompt_version_of("multihop")) == "bank-mc-2026-11-01-v3"
