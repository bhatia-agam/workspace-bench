# ruff: noqa: RUF001
"""The multilingual language leg has ONE scorer, the raw samples of the read window: credited
when at least one sample names the language in a naming context (``languages.naming_forms``),
whatever the digest kept and however many samples a producer writes per cell; the per-item count
is reported. Fixtures follow the motivating cases."""

import re

import pytest
from conftest import write_jsonl
from summary_fakes import FakeLLM, summary_args

from wsbench import registry
from wsbench.banks import load_bank
from wsbench.multitoken import regex
from wsbench.multitoken.prompts import CANNOT, ML_SYSTEM, QUESTION_LANGUAGE_V2

AUSTRIA = "b3-ml-de-capital-austria"  # "Die Hauptstadt von Österreich ist" -> Wien; Vienna
# the capital items left the registered bank in v5 (2026-11-05); the leg's rule is the same on
# every bank, so the motivating Austria cases read the frozen bank v4 that holds them
V4 = "evals/multilingual/items_v4.json"
PASLANMAZ = "mlmh-tr-paslanmaz-sheffield"
# L32 p4: the only kind of German naming one lens wrote (5 of 220 naming samples); its 128-line
# digest dropped it, so the MC language role said cannot tell, while another lens, whose digest
# kept the same phrase, passed
AUF_DEUTSCH = "Wien (oder auf Deutsch: Die Hauptstadt von Österreich ist Wien)"
# L60 p22: the one raw sample the MC language judge credited "Turkish" from
STEELIN = (
    "kimyasal adı ve kullanım alanı nedir?\nA) 304 paslanmaz çeliğinin işaretidir.\n"
    "B) Stainless steelin Türkçe"
)


def _spec(name: str):
    import importlib

    spec = importlib.import_module(f"wsbench.evals.{name}").SPEC
    registry.FAMILIES.setdefault(spec.name, spec)
    return spec


@pytest.fixture(autouse=True)
def _austria_bank(monkeypatch):
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "MULTILINGUAL", V4)


def _unit(family: str, item: str) -> regex.ScoredUnit:
    header, items = load_bank(registry.bank_path(family))
    it = next(i for i in items if i["id"] == item)
    unit = regex.language_unit(regex.scored_units(it, regex.contract_for(header, family)))
    assert unit is not None
    return unit


def _content_judge(gold: str, quote: str):
    """Picks ``gold`` with ``quote`` on the content question; fails on any language question."""

    def judge(system, user, schema):
        assert system == ML_SYSTEM and QUESTION_LANGUAGE_V2 not in user
        opts = {
            m.group(2).split(" / ")[0]: m.group(1)
            for m in re.finditer(r"^([A-F])\. (.*)$", user, re.M)
        }
        return {"choice": opts.get(gold, opts[CANNOT]), "quote": quote}

    return judge


def _digest_without(word: str):
    """A digest that keeps every bundle sample except those holding ``word``."""

    def digest_fn(user):
        lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
        keep = [ln for ln in lines if word not in ln]
        return {"items": [{"statement": "s", "where": "", "evidence": ln} for ln in keep]}

    return digest_fn


def _rows(samples_per_cell: list[list[str]], layer: int = 32) -> list[dict]:
    return [
        {"id": AUSTRIA, "layer": layer, "pos": p, "samples": s}
        for p, s in enumerate(samples_per_cell)
    ]


def _austria(tmp_path, monkeypatch, rows):
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    fake = FakeLLM.install(
        monkeypatch, _content_judge("Vienna", "ist **Wien** (Vienna)"), _digest_without("Deutsch")
    )
    spec = _spec("multilingual")
    r = spec.run(summary_args(path, tmp_path / "o", spec.judge.prompt_version, items=[AUSTRIA]))
    return r.rows[0], fake


X4 = [
    ["Die Hauptstadt Österreichs ist Wien.", "ist **Wien** (Vienna). Die Hauptstadt ist Wien."],
    ["Wien ist eine der bedeutendsten Städte in Europa.", AUF_DEUTSCH],
]


def test_a_dropped_one_sample_naming_still_credits_the_leg(tmp_path, monkeypatch):
    row, fake = _austria(tmp_path, monkeypatch, _rows(X4))
    assert all("Deutsch" not in u for n, _s, u in fake.calls if n == "pick")  # not in the digest
    assert row["language_pass"] is True and row["language_naming_samples"] == 1
    assert row["unit_correct"] == {"concept_native": True} and row["pass"] is True


def test_no_naming_sample_fails_the_leg(tmp_path, monkeypatch):
    rows = _rows([X4[0], ["Wien ist eine der bedeutendsten Städte in Europa.", "Wien."]])
    row, _fake = _austria(tmp_path, monkeypatch, rows)
    assert row["language_pass"] is False and row["language_naming_samples"] == 0
    assert row["unit_hit"]["language"] is False
    assert row["mc_pass"] and row["regex_pass"] and row["pass"] is False


def test_the_leg_does_not_depend_on_samples_per_cell(tmp_path, monkeypatch):
    # the same eight samples as an s3d-shaped file (one per cell) and an x4-shaped one (four per
    # cell): the one naming sample credits the leg in both, with the same count
    flat = [s for cell in X4 + X4 for s in cell if AUF_DEUTSCH not in s] + [AUF_DEUTSCH]
    one = _rows([[s] for s in flat])
    four = _rows([flat[i : i + 4] for i in range(0, len(flat), 4)])
    got = []
    for name, rows in (("s3d", one), ("x4", four)):
        sub = tmp_path / name
        sub.mkdir()
        row, _fake = _austria(sub, monkeypatch, rows)
        got.append((row["language_pass"], row["language_naming_samples"], row["pass"]))
    assert got == [(True, 1, True), (True, 1, True)]


def test_one_scorer_for_the_language():
    # mlmh-tr-paslanmaz-sheffield: the MC judge credited "Turkish" from this one sample
    # while the regex leg (two samples per layer) rejected it; now the raw naming forms alone
    # decide, and they credit it
    unit = _unit("multilingual_multihop", PASLANMAZ)
    leg = regex.language_leg([STEELIN, "Paslanmaz çelik Sheffield'da icat edildi."], unit)
    assert leg.ok and leg.n_samples == 1 and leg.langs == ("tr",)
    # an adjective of a topic names no language, whatever any judge would say
    assert not regex.language_leg(["Türkçe futbol ligi", "Sheffield çeliği"], unit).ok


def test_item_result_takes_the_language_out_of_the_layer_conjunction():
    unit = _unit("multilingual", AUSTRIA)
    content = regex.ScoredUnit("concept_native", True, {"en": ["Vienna"]})
    units = [content, unit]
    by_layer = {20: {"concept_native": ["en"], "language": []}, 24: {"language": ["de"]}}
    assert not regex.item_result(by_layer, units)["pass"]  # the old same-layer conjunction
    ok = regex.item_result(by_layer, units, regex.LanguageLeg(1, ("de",)))
    assert ok["pass"] and ok["passing_layers"] == [20] and ok["unit_langs"]["language"] == ["de"]
    no = regex.item_result(by_layer, units, regex.LanguageLeg(0, ()))
    assert not no["pass"] and no["passing_layers"] == [] and not no["unit_hit"]["language"]


ANTICYCLONE = "mlt-ru-anticyclone"
# L24 p6: a lens's only naming of the language, dropped by the digest (another lens passed on an
# equivalent one-sample naming its digest kept)
NA_RUSSKOM = "Вот несколько вариантов описания ясного неба безоблаков на русском языке:"


def _no_judge(system, user, schema):
    raise AssertionError(f"unexpected judge call ({schema.get('name')})")


def test_typo_leg_reads_the_naming_the_digest_dropped(tmp_path, monkeypatch):
    # bank v4 dropped the anticyclone item: the rule is run on bank v3
    v3 = registry.bank_path("multilingual_typo").with_name("items_v3.json")
    monkeypatch.setenv("WSB_BANK_FILE_MULTILINGUAL_TYPO", str(v3))
    spec = _spec("multilingual_typo")
    correction = "мощный антициклон (anticyclone) принёс ясное небо"
    for with_naming in (True, False):
        sub = tmp_path / str(with_naming)
        sub.mkdir()
        samples = [correction, correction, *([NA_RUSSKOM] if with_naming else ["Ясное небо."])]
        rows = [
            {"id": ANTICYCLONE, "layer": 24, "pos": p, "samples": [s]}
            for p, s in enumerate(samples)
        ]
        path = write_jsonl(sub / "r.jsonl", rows)
        FakeLLM.install(monkeypatch, _no_judge, _digest_without("русском"))
        r = spec.run(summary_args(path, sub / "o", spec.judge.prompt_version, items=[ANTICYCLONE]))
        row = r.rows[0]
        assert row["language_naming_samples"] == int(with_naming)
        assert row["pass"] is with_naming and row["unit_hit"]["correction_native"] is True


# ------------------------------------------------------------------ the prompt-language bridge


def test_bridge_l2_is_optional_in_multihop_only():
    # writing the bridge in the prompt's language is not required (a scored diagnostic)
    for family, item, optional in (
        ("multilingual_multihop", PASLANMAZ, {"bridge_l2"}),
        ("multilingual_typo", ANTICYCLONE, set()),  # its L2 correction stays required
    ):
        path = registry.bank_path(family)
        if family == "multilingual_typo":  # bank v4 dropped the anticyclone item
            path = path.with_name("items_v3.json")
        header, items = load_bank(path)
        it = next(i for i in items if i["id"] == item)
        units = regex.scored_units(it, regex.contract_for(header, family))
        assert {u.role for u in units if not u.required} == optional, family
    # a v1-shaped item (no mc_roles) keeps the bank's own flag
    header, items = load_bank(registry.bank_path("multilingual_multihop"))
    v1 = {**next(i for i in items if i["id"] == PASLANMAZ), "mc_roles": None}
    contract = regex.contract_for(header, "multilingual_multihop")
    assert all(u.required for u in regex.scored_units(v1, contract))
