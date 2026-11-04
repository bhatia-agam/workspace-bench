"""Review of PR #208 (round 4d): wrong_intermediate ``name_in`` precompiles its patterns (was
~33 ms per call) and its ASCII-twin forms (wbforms-v4). The round's split-line and option-audit
fixes went with the rules they fixed."""

import time

import pytest

from wsbench import digest
from wsbench.evals.wrong_intermediate import judge as wb
from wsbench.evals.wrong_intermediate import prompts as wp


def _g(text: str, count: int) -> digest.Grounded:
    ln = digest.Line(text)
    return digest.Grounded("", digest.support_text(count), text, ln, text, "items", "", count)


# ------------------------------------------------------------------ name_in speed
def test_name_in_is_precompiled():
    it = max(wb.load_items(), key=lambda i: max(len(v) for v in i["mc"]["forms"].values()))
    forms = [it["mc"]["forms"][o] for o in it["mc"]["order"]]
    text = "The composer of the song was Paul McCartney, while John Lennon wrote others."
    for f in forms:
        wb.name_in(text, f)  # warm the caches
    t = time.perf_counter()
    for _ in range(100):
        for f in forms:
            wb.name_in(text, f)
    per_call = (time.perf_counter() - t) / (100 * len(forms))
    assert per_call < 0.005  # was ~0.033-0.05 s with the re cache overflowing


# ------------------------------------------------------------------ ASCII twins (wbforms-v4)
DALI_ITEM = "painting_creator-Q2272625-death_year"


@pytest.fixture(scope="module")
def dali_forms():
    it = next(i for i in wb.load_items() if i["id"] == DALI_ITEM)
    return it["mc"]["forms"]["Salvador Dalí"]


def test_lowercase_ascii_twin_no_longer_names_dali(dali_forms):
    assert "Dali" in dali_forms  # the bank's own plain-ASCII twin of the label's "Dalí"
    for text in ("by dali", "a dali-like scene", "the dali painting"):
        assert not wb.name_in(text, dali_forms), text
        assert not wb.name_spans(text, dali_forms), text


def test_capitalized_twin_and_full_names_still_name_dali(dali_forms):
    for text in ("by Dali", "a Dali-like scene", "Salvador Dali", "salvador dali", "Dalí"):
        assert wb.name_in(text, dali_forms), text


def test_twins_come_only_from_the_label():
    twins = {
        (o, t)
        for it in wb.load_items()
        for o, fs in it["mc"]["forms"].items()
        for t in wb._ascii_twins(tuple(fs), wb.accent_only)
    }
    assert ("Paul Cézanne", "Cezanne") in twins and ("Georges Méliès", "Melies") in twins
    assert not any(o in ("Vladimir Lenin", "Frédéric Chopin", "Nintendo") for o, _t in twins)
    assert wp.FORMS_VERSION == "wbforms-v4"
