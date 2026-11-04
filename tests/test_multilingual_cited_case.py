"""A case-sensitive answer form (May, March) also counts in lower case when the readout cites the
word with emphasis or quotes ("**may**"). The rule reads the marks, not the grammar, so an
emphasised or quoted verb hits too (accepted: the MC judge still has to pick the gold); an
unmarked lower-case verb never hits."""

import re

import pytest
from conftest import write_jsonl
from summary_fakes import FakeLLM, summary_args

from wsbench import registry
from wsbench.multitoken import regex
from wsbench.multitoken.prompts import CANNOT, ML_SYSTEM

APRIL = "b3-ml-es-month-april"  # "El mes después de abril es" -> mayo; May (case-sensitive)
#: the judge picked May on this verified quote; the case rule voided it
CITED = "En inglés el mes que sigue a abril es **may**."


@pytest.mark.parametrize(
    "text,hit",
    [
        ("es **may**.", True),
        ('"maio" = "may"', True),  # pt-month-after-apr
        ("*may*", True),
        ("«may»", True),
        ("May", True),
        ("you may go", False),
        ("**may be**", False),
        ("dismay", False),
        ("**mayo**", False),
        # the marks, not the grammar: an emphasised or quoted verb hits too (accepted)
        ("You **may** want to", True),
        ("it *may* rain", True),
        ("I think it 'may' work", True),
    ],
)
def test_cited_lower_case_hits_a_case_sensitive_form(text, hit):
    assert regex.hit_forms([text], {"en": ["May"]}, case_sensitive=("May",)) == (
        ["en"] if hit else []
    )
    # a form that is not case-sensitive is unchanged (any case hits)
    assert regex.hit_forms(["you may go"], {"en": ["May"]}) == ["en"]


def test_emphasised_march_verb_hits_unmarked_does_not():
    assert regex.hit_forms(["we **march** forward"], {"en": ["March"]}, case_sensitive=("March",))
    assert not regex.hit_forms(["we march forward"], {"en": ["March"]}, case_sensitive=("March",))


def _spec():
    import importlib

    spec = importlib.import_module("wsbench.evals.multilingual").SPEC
    registry.FAMILIES.setdefault(spec.name, spec)
    return spec


def _judge(quote):
    def judge(system, user, schema):
        assert system == ML_SYSTEM
        opts = {
            m.group(2).split(" / ")[0]: m.group(1)
            for m in re.finditer(r"^([A-F])\. (.*)$", user, re.M)
        }
        return {"choice": opts.get("May", opts[CANNOT]), "quote": quote}

    return judge


@pytest.mark.parametrize("line,want", [(CITED, True), ("Tal vez you may go en español.", False)])
def test_april_pick_on_a_cited_lower_case_may(tmp_path, monkeypatch, line, want):
    rows = [
        {"id": APRIL, "layer": 32, "pos": 0, "samples": [line]},
        {"id": APRIL, "layer": 32, "pos": 1, "samples": ["El mes después de abril, en español."]},
    ]
    path = write_jsonl(tmp_path / "r.jsonl", rows)
    quote = "es **may**" if want else "you may go"
    FakeLLM.install(monkeypatch, _judge(quote))
    spec = _spec()
    r = spec.run(summary_args(path, tmp_path / "o", spec.judge.prompt_version, items=[APRIL]))
    row = r.rows[0]
    v = row["mc"]["concept_native"]
    assert v["kind"] == "correct" and v["quote_ok"] and v["correct"] is want
    assert row["language_pass"] is True and row["pass"] is want
