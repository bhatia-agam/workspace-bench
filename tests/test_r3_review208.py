# ruff: noqa: RUF001
"""Review of PR #208 (round 3 bridge_ml), blocking findings, each pinned in BOTH
directions (the too-lenient shape still fails AND the too-strict shape now passes):

1. multilingual / multilingual_multihop topic veto (``mcrx._rescue_topic``): word-bounded stems,
   an official / national stem only beside a language noun, and only near the naming;
2. multilingual_mt anchoring (``family.anchored``): "<Lang> word / phrase / text" names any word,
   so only a passage noun with no gloss after it anchors (``languages.input_passage_naming``).
(Finding 3, the rival check ``rival.contest``, went with the rule.)"""

from test_r3_mcrx_language import CANNOT, _cells, _ctx

from wsbench import digest
from wsbench.banks import load_bank
from wsbench.digest import Line
from wsbench.multitoken import family as fam
from wsbench.multitoken import mcrx, regex
from wsbench.multitoken.options import LANGUAGE_ROLE
from wsbench.readouts import Cell

# ------------------------------------------------------------------ 1. the topic veto

PASLANMAZ = "mlmh-tr-paslanmaz-sheffield"
# the L60 sample the single-layer judge credited (cached final-olens readout)
PASLANMAZ_L60 = (
    "Official adı (Распознаваемый названия) ne olduğu soruluyor. Bu alaşımınOfficial adı "
    "**Stainless Steel** yani Türkçe çeviriyle **Paslanmaz Çelik'tir**. Ancak spesifik olarak bu "
    "hastanelerde kimya derslerinde sorulan"
)
BAYEUX_L36 = (
    "ilytetään ensin Britannian kansallismuseossa (The National Museum in London). Tämä "
    "käsikirjoitusta säilytetään erityisessä ilmastoidussa arkistokaapissa. Suomeksi tätä "
    "säilytettyä esinettä kutsutaan nimellä **Sandstonen rukouskirja"
)


def _forms(option: str) -> dict[str, list[str]]:
    return mcrx._option_naming_forms(option, ("en", "zh"))


def test_ordinary_words_no_longer_veto_a_naming():
    # the reviewer's reproductions: exam in 'example', 'of course', Finnish 'ensin' (= first),
    # 'the official name', plus the two real readouts
    tr, fi = _forms("Turkish"), _forms("Finnish")
    for text, forms in [
        ("For example, in Turkish it is called paslanmaz çelik", tr),
        ("Of course, suomeksi sitä kutsutaan nimellä ruostumaton teräs", fi),
        ("Ensin: suomeksi tätä esinettä kutsutaan nimellä ruostumaton teräs", fi),
        ("The official name of this alloy in Turkish is paslanmaz çelik", tr),
        ("While shopping: suomeksi tätä kutsutaan nimellä teräs", fi),
        (PASLANMAZ_L60, tr),
        (BAYEUX_L36, fi),
    ]:
        assert regex.hit_forms([text], forms), text  # it IS a naming of the option
        assert not mcrx._rescue_topic(text, forms), text


def test_topic_mentions_still_veto():
    tr, ar = _forms("Turkish"), _forms("Arabic")
    for text, forms in [
        ("Turkish is the official language of Turkey; in Turkish it is called çelik", tr),
        ("Turkish is the national language here. In Turkish it is called çelik", tr),
        ("In Turkish lessons, the word for steel is çelik", tr),
        ("Turkish exams: in Turkish it is called çelik", tr),
        ("A Turkish language course: in Turkish it is called çelik", tr),
        ("Learning Turkish: in Turkish it is called çelik", tr),
        (
            "عشق آباد (Ashgabat) هو العربية (Arabic)، وهي اللغة الرسمية الوحيدة المعتمدة في "
            "الدولة، واسمها بالعربية عشق آباد",
            ar,
        ),
    ]:
        assert mcrx._rescue_topic(text, forms), text


def test_topic_word_vetoes_only_near_the_naming():
    tr = _forms("Turkish")
    filler = " ".join(["kelime"] * 20)
    far = f"The school was founded in 1900. {filler}. In Turkish it is called çelik."
    near = "The school teaches it. In Turkish it is called çelik."
    assert not mcrx._rescue_topic(far, tr)
    assert mcrx._rescue_topic(near, tr)


def test_paslanmaz_l60_naming_is_rescued_and_a_topic_twin_is_not():
    # the decisive L60 line reaches the rescue (it names the bridge in both languages); the same
    # naming inside an official-language sentence is still a topic
    cells = _cells(PASLANMAZ, [PASLANMAZ_L60, "Paslanmaz çelik Sheffield'da icat edildi."])
    ctx = _ctx(PASLANMAZ, cells)
    v = mcrx.language_rescue(ctx, PASLANMAZ, dict(CANNOT), [Line(PASLANMAZ_L60)], cells)
    assert v["kind"] == "correct" and v["form_via"] == "rescue"
    topic = (
        "Türkçe resmi dil olarak kullanılır; Türkçe çeviriyle **Paslanmaz Çelik** "
        "(Stainless Steel) denir."
    )
    cells = _cells(PASLANMAZ, [topic, "Paslanmaz çelik Sheffield'da icat edildi."])
    ctx = _ctx(PASLANMAZ, cells)
    v = mcrx.language_rescue(ctx, PASLANMAZ, dict(CANNOT), [Line(topic)], cells)
    assert v["kind"] == "cannot"


def _pinned(iid: str, samples: list[str]) -> list[str]:
    cells = _cells(iid, samples)
    ctx = _ctx(iid, cells)
    col = digest.Collapse()
    col.cells[iid] = cells[0]
    col.grounded[iid] = []
    out: list[str] = []

    def fake_pin(col, item_id, cs, preds, s, per):
        # the LANGUAGE option predicates only (``lang=True`` default): a content option's head
        # word ("stainless steel") pins a line by itself
        lang = [p for p in preds if p.__defaults__ and p.__defaults__[1]]
        out.extend(ln.text for ln in digest.native_lines(cs) if any(p(ln) for p in lang))
        return 0

    orig, settings = mcrx.digest.pin_lines, mcrx.digest.settings
    mcrx.digest.pin_lines, mcrx.digest.settings = fake_pin, lambda *a, **k: None
    try:
        mcrx._pin_options(ctx, col)
    finally:
        mcrx.digest.pin_lines, mcrx.digest.settings = orig, settings
    return out


def test_paslanmaz_l60_line_is_pinned_and_a_topic_line_is_not():
    topic = "Türkçe, Türkiye'nin resmi dilidir; Türkçe çeviriyle çelik denir."
    pinned = _pinned(PASLANMAZ, [PASLANMAZ_L60, topic])
    assert PASLANMAZ_L60 in pinned and topic not in pinned


# ------------------------------------------------------------------ 2. multilingual_mt anchoring

MT_BANK = "evals/multilingual_mt/items_v2.json"


def _mt(iid: str):
    header, items = load_bank(MT_BANK)
    contract = regex.contract_for(header, str(header["family"]))
    it = next(i for i in items if i["id"] == iid)
    units = regex.scored_units(it, contract)
    lang = next(u for u in units if u.role == LANGUAGE_ROLE)
    return it, units, contract, fam.anchor_forms(it), lang


def test_naming_of_another_word_does_not_anchor():
    # the reviewer's cells, all namings of OTHER objects (cached readout quotes)
    for iid, text in [
        ("mlh-pl-kasztanowiec", "The Polish word for city is miasto."),
        ("mlh-fi-toothbrush", 'Kylmäinen is a Finnish word that translates to "refrigerator"'),
        ("mlh-fi-tortoise", 'a beautiful Finnish phrase meaning "hopefully well"'),
        ("mlh-tr-dis-macunu", "the Turkish text of the famous Azerbaijani folk song"),
        ("mlh-ar-hourglass", "Arabic Word Generator"),
        ("mlh-sw-mwarobaini", "Swahili word that translates to Tree"),
        ("mlh-sw-mwarobaini", "This Swahili phrase means good morning."),
        ("mlh-pl-kasztanowiec", "a Polish riddle meaning city"),
    ]:
        _it, _u, _c, anchors, lang = _mt(iid)
        assert not fam.anchored(text, lang, anchors), (iid, text)


def test_passage_naming_still_anchors():
    _it, _u, _c, anchors, lang = _mt("mlh-pl-kasztanowiec")
    for text in [
        "This is a Polish riddle about a tree.",
        "This is a Polish riddle: what tree has conkers?",
        "a simple Polish arithmetic question",
        "The prompt is a Polish fill-in prompt.",
        "This passage is written in Polish.",
    ]:
        assert fam.anchored(text, lang, anchors), text


def test_toothbrush_layer_fails_on_another_words_naming_and_passes_on_the_passage():
    it, units, contract, anchors, _lang = _mt("mlh-fi-toothbrush")
    concept = next(u for u in units if u.role != LANGUAGE_ROLE).all_forms()[0]
    other = 'Kylmäinen is a Finnish word that translates to "refrigerator".'
    rest = [f"It is a {concept}.", f"A {concept} again."]

    def passes(samples: list[str]) -> bool:
        cells = [Cell(it["id"], 28, -1 - k, (s,), None, None) for k, s in enumerate(samples)]
        hits = fam.raw_layer_hits(cells, units, contract, anchors)
        return any(regex.layer_passes(h, units) for h in hits.values())

    assert not passes([other, *rest])
    assert passes(["This is a Finnish riddle about a household object.", *rest])
