"""Arabic / Greek / Hebrew naming phrases, no "(suomi)" label (Suomi is also Finland), and English
plurals of the multi-token families' content forms. Each case is a cited readout sample, pinned
with its too-lenient twin."""

import pytest

from wsbench import registry
from wsbench.banks import load_bank
from wsbench.multitoken import regex


def _units(family: str, item: str) -> dict[str, regex.ScoredUnit]:
    header, items = load_bank(registry.bank_path(family))
    it = next(i for i in items if i["id"] == item)
    contract = regex.contract_for(header, str(header.get("family", family)))
    return {u.role: u for u in regex.scored_units(it, contract)}


def _names(family: str, item: str, text: str) -> bool:
    return regex.language_leg([text], _units(family, item)["language"]).ok


@pytest.mark.parametrize(
    "family,item,text,ok",
    [
        # mlh-ar-aurora L60 p30: "في العربية" (in Arabic)
        (
            "multilingual_mt",
            "mlh-ar-aurora",
            'أحياناً "الشفق القطبي" أو "الأورورا" في العربية، وتُسمى في الإنكليزية Aurora Borealis',
            True,
        ),
        ("multilingual_mt", "mlh-ar-aurora", "وبالعربية تسمى الشفق القطبي", True),  # wa- proclitic
        ("multilingual_mt", "mlh-ar-aurora", "رحلة في العربية السعودية", False),  # Saudi Arabia
        # mlh-el-screwdriver L48 p20: "σε ελληνικά" (in Greek)
        ("multilingual_mt", "mlh-el-screwdriver", "(σε ελληνικά: κασσίρεια) The tool", True),
        ("multilingual_mt", "mlh-el-screwdriver", "σε ελληνικούς δρόμους", False),
        # mlh-he-toothbrush: "ובעברית" (and in Hebrew)
        ("multilingual_mt", "mlh-he-toothbrush", "ובעברית קוראים לזה מברשת שיניים", True),
        # mlmh-he-pacific-yew-taxol: "שמה העברי" (its Hebrew name)
        ("multilingual_multihop", "mlmh-he-pacific-yew-taxol", "שמה העברי נגזר מעץ", True),
        ("multilingual_multihop", "mlmh-he-pacific-yew-taxol", "עם עברי קדום", False),
        # mlt-fi-kansanedustaja: "(Suomi)" is the country; "(suomeksi)" names Finnish
        ("multilingual_typo", "mlt-fi-kansanedustaja", "Edustaja Sari Essayah (Suomi)", False),
        ("multilingual_typo", "mlt-fi-kansanedustaja", "anki (Suomi) a puolanki (Polska)", False),
        ("multilingual_typo", "mlt-fi-kansanedustaja", "kansanedustaja (suomeksi)", True),
    ],
)
def test_naming_phrases(family, item, text, ok):
    assert _names(family, item, text) is ok


def test_english_plural_of_a_content_form():
    # mlt-hu-cseppkobarlang: the digest's only native line
    units = _units("multilingual_typo", "mlt-hu-cseppkobarlang")
    line = "víz-barlangok** (*dripstone caves*)"
    assert regex.layer_unit_hits([line], list(units.values()))["correction_native"] == ["en"]
    assert regex.english_plurals("dripstone cave") == ["dripstone caves"]
    assert regex.english_plurals("brain waves") == []  # already a plural
    assert regex.english_plurals("butterfly") == ["butterflies"]


def test_no_plural_of_a_capitalised_form_and_is_becomes_es():
    """A form whose first letter is upper case is a name and takes no plural: matching is
    case-blind, so "Booth" -> "Booths" would credit "voting booths". "-is" -> "-es"."""
    assert regex.english_plurals("Turkmenistan") == []
    assert regex.english_plurals("Booth") == []
    assert regex.english_plurals("Republic of Turkmenistan") == []
    assert regex.english_plurals("COPD") == []
    assert regex.english_plurals("aurora borealis") == ["aurora boreales"]
    assert regex.english_plurals("analysis") == ["analyses"]
    assert regex.english_plurals("dialysis") == ["dialyses"]
    assert regex.english_plurals("cactus") == ["cactuses"]  # -us keeps +es
    booth = _units("multilingual_multihop", "mlmh-ko-vacuum-booth-gloucester")["bridge_native"]
    assert "Booths" not in booth.forms["en"]
    assert regex.layer_unit_hits(["Hubert Cecil Booth"], [booth])["bridge_native"] == ["en"]
    assert regex.layer_unit_hits(["rows of voting booths"], [booth])["bridge_native"] == []
    tm = _units("multilingual_multihop", "mlmh-ar-ashgabat-manat")["bridge_native"]
    assert not any(f.endswith("Turkmenistans") for f in tm.forms["en"])


def test_no_plural_for_multilingual_one_word_answers():
    # adjectives / numbers / months: "lows", "colds" would be other words
    assert "concept_native" not in regex.PLURAL_ROLES
    assert _units("multilingual", "b3-ml-es-month-april")["concept_native"].forms["en"] == ["May"]
    assert _units("multilingual", "de-half-six")["concept_native"].forms["en"] == ["three", "3"]


@pytest.mark.parametrize(
    "family", ["multilingual", "multilingual_mt", "multilingual_multihop", "multilingual_typo"]
)
def test_no_mc_distractor_hits_its_own_scored_unit(family):
    """The plural forms never make an item's own MC distractor credit its unit."""
    header, items = load_bank(registry.bank_path(family))
    contract = regex.contract_for(header, str(header.get("family", family)))
    for it in items:
        scored = {u.role: u for u in regex.scored_units(it, contract)}
        for role in it["mc_roles"]:
            block = (it.get("mc") or {}).get(role)
            if block and role in scored and role in regex.PLURAL_ROLES:
                for d in block["distractors"]:
                    assert not regex.hit_forms([d], scored[role].forms), (it["id"], d)
