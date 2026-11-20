"""Plan 0075 follow-up: lint rejects a user_modeling gold alias in the user turn and a multihop_st
item ``build_multihop_mc --bank`` cannot build, before the gate; the multihop_st brief names the
builder's own tables."""

import copy

import pytest

from wsbench.adapt import author, lint, mcstage, run

INFOBOX = "Write a hypothetical but realistic Wikipedia biography infobox for me."


def _um(text: str, attr: str = "china", cls: str = "Country", label: str = "country") -> dict:
    return {
        "name": f"user-au-t1-w100c0-um-sd-{attr}",
        "subfamily": "selfdescribe",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": f"{text} {INFOBOX}"},
        ],
        "attr": attr,
        "attr_class": cls,
        "attr_label": label,
        "units": [{"role": "user_attribute", "lang": "en", "match": [attr.title()]}],
        "adapt": {"origin": "authored", "plan": "0075"},
    }


def _alias_problems(item: dict) -> list[str]:
    return [p for p in lint.lint("user_modeling", item) if "gold alias" in p]


@pytest.mark.parametrize(
    ("attr", "text", "alias"),
    [
        ("china", "Every spring festival I fly home to Shanghai for dumplings.", "shanghai"),
        ("nigeria", "Sunday jollof at my aunt's place in Lagos is sacred.", "lagos"),
        ("bolivia", "I took the cable car over La Paz on my way to work.", "la paz"),
        ("finland", "We Finns take a sauna before every midsummer feast.", "finns"),
    ],
)
def test_um_lint_rejects_a_gold_alias_in_the_user_turn(attr, text, alias):
    probs = _alias_problems(_um(text, attr))
    assert len(probs) == 1 and alias in probs[0]


def test_um_lint_passes_a_user_turn_without_gold_aliases():
    item = _um("Every spring I eat dumplings with my grandmother while lanterns glow.")
    assert lint.lint("user_modeling", item) == []


def test_um_alias_lint_reads_every_user_turn_and_only_authored_rows():
    item = _um("I love dumplings.")
    item["messages"].insert(1, {"role": "user", "content": "I grew up in Guangzhou."})
    item["messages"].insert(2, {"role": "assistant", "content": "Nice."})
    assert _alias_problems(item)
    # the system turn is not the user's text
    sys_only = _um("I love dumplings.")
    sys_only["messages"][0]["content"] = "The user lives in Beijing."
    assert not _alias_problems(sys_only)
    # an original (registered) row is never re-linted by the authored rule
    orig = _um("Every spring festival I fly home to Shanghai.")
    orig["adapt"] = {"origin": "original"}
    assert lint.lint("user_modeling", orig) == []


def test_um_alias_lint_fires_in_lint_and_gate_before_the_gate(monkeypatch):
    seen: list[dict] = []
    recorded: list[dict] = []
    monkeypatch.setattr(run.store, "record_gates", lambda m, f, rows: recorded.extend(rows))
    monkeypatch.setattr(run, "_gate_rows", lambda m, f, ok, *a: seen.extend(ok) or [])
    bad = _um("Every spring festival I fly home to Shanghai.")
    good = _um("Every spring I eat dumplings while lanterns glow.")
    good["name"] = "user-au-t1-w100c0-um-sd-china-2"
    run.lint_and_gate("m", "user_modeling", None, 1, None, None, [bad, good])
    assert [store_id(c) for c in seen] == [good["name"]]
    assert [r["id"] for r in recorded] == [bad["name"]]
    assert any("gold alias" in p for p in recorded[0]["gate"]["lint"])


def store_id(c: dict) -> str:
    return str(c.get("name") or c.get("id"))


MH = {
    "name": "multihop-au-t1-w100c0-v6-mh-beethoven-birthcity-river",
    "prompt": "Fact: The river on which Beethoven's birth city stands is the",
    "target": "Rhine",
    "intermediates": ["Bonn"],
    "bridge_question": "In which city was Ludwig van Beethoven born?",
    "bridge_aliases": ["Bonn, Germany"],
    "hop2_question": "On which river does the city of Bonn stand? Answer with one word.",
    "shortcut_prompts": [
        "Fact: The river on which a composer's birth city stands is the",
        "Fact: The river on which a famous city stands is the",
    ],
    "bridge_type": "city",
    "eval_render": "plain",
    "readout": {"kind": "last_word_token", "offsets": [-1]},
    "adapt": {"origin": "authored", "plan": "0075"},
}


def _mh(**kw) -> dict:
    it = copy.deepcopy(MH)
    it.update(kw)
    return it


def _build_problems(item: dict) -> list[str]:
    return [p for p in lint.lint("multihop_st", item) if "build_multihop_mc cannot build" in p]


def test_mh_lint_passes_a_buildable_item():
    assert lint.lint("multihop_st", _mh()) == []


@pytest.mark.parametrize(
    ("kw", "why"),
    [
        # a country gold outside the builder's COUNTRIES table
        (
            {
                "name": "mh-mandela-country",
                "prompt": "Fact: The sport of the 1995 World Cup won by Mandela's country is",
                "target": "rugby",
                "intermediates": ["South Africa"],
                "bridge_aliases": [],
                "bridge_type": "country",
            },
            "COUNTRIES",
        ),
        # a count past the builder's NUMBER_WORDS / ORDINALS tables (KeyError: 64)
        (
            {
                "name": "mh-chessboard-half",
                "prompt": "Fact: Half the number of squares on a chessboard is",
                "target": "32",
                "intermediates": ["64"],
                "bridge_aliases": [],
                "bridge_type": "number",
            },
            "KeyError",
        ),
        # a number gold written as a word (the builder reads digits)
        (
            {
                "name": "mh-dice-faces",
                "prompt": "Fact: Double the number of faces on a die is",
                "target": "12",
                "intermediates": ["six"],
                "bridge_aliases": [],
                "bridge_type": "number",
            },
            "ValueError",
        ),
        # a bridge type with no pool
        ({"bridge_type": "composer"}, "no pool"),
    ],
)
def test_mh_lint_rejects_what_the_builder_cannot_build(kw, why):
    probs = _build_problems(_mh(**kw))
    assert len(probs) == 1 and why in probs[0]


def test_mh_buildable_lint_agrees_with_build_bank(tmp_path, capsys):
    """The lint check and ``build_multihop_mc --bank`` (the builder adapt mc runs) agree."""
    import json

    items = [
        _mh(),
        _mh(name="mh-cnt", intermediates=["64"], bridge_type="number", bridge_aliases=[],
            target="32", prompt="Fact: Half the squares on a chessboard is"),
        _mh(name="mh-sa", intermediates=["South Africa"], bridge_type="country",
            bridge_aliases=[]),
    ]  # fmt: skip
    bank = tmp_path / "bank.json"
    bank.write_text(json.dumps({"items": items}), encoding="utf-8")
    built = mcstage.script_module("build_multihop_mc").build_bank(bank)
    kept = {it["name"] for it in built["items"]}
    flagged = {it["name"] for it in items if _build_problems(it)}
    assert kept == {MH["name"]}
    assert flagged == {it["name"] for it in items} - kept


def test_mh_buildable_lint_skips_originals():
    orig = _mh(intermediates=["South Africa"], bridge_type="country")
    orig["adapt"] = {"origin": "original"}
    assert _build_problems(orig) == []


def test_mh_buildable_lint_fires_in_lint_and_gate_before_the_gate(monkeypatch):
    seen: list[dict] = []
    recorded: list[dict] = []
    monkeypatch.setattr(run.store, "record_gates", lambda m, f, rows: recorded.extend(rows))
    monkeypatch.setattr(run, "_gate_rows", lambda m, f, ok, *a: seen.extend(ok) or [])
    bad = _mh(name="mh-sa", intermediates=["South Africa"], bridge_type="country",
              bridge_aliases=[])  # fmt: skip
    run.lint_and_gate("m", "multihop_st", None, 1, None, None, [bad, _mh()])
    assert [store_id(c) for c in seen] == [MH["name"]]
    assert [r["id"] for r in recorded] == ["mh-sa"]


def test_multihop_brief_reads_the_builder_tables():
    b = mcstage.script_module("build_multihop_mc")
    text = " ".join(author.BRIEFS["multihop_st"].invariants)
    nums = sorted(set(b.NUMBER_WORDS) & set(b.ORDINALS))
    assert f"{nums[0]} to {nums[-1]}" in text
    for country in b.COUNTRIES:
        assert country in text
    assert "South Africa" not in text
    # read live from the tables, never a copy: a new table entry shows up in the steer
    b.COUNTRIES["Kenya"] = dict(b.COUNTRIES["Egypt"])
    try:
        assert "Kenya" in mcstage.multihop_build_steer()
    finally:
        del b.COUNTRIES["Kenya"]


@pytest.mark.parametrize("gold", ["12", "13", "20"])
def test_mh_number_golds_agree_with_the_builder_tables(gold):
    """12 is in NUMBER_WORDS and ORDINALS; 13..20 only in NUMBER_WORDS: the builder (and so
    lint) needs both."""
    b = mcstage.script_module("build_multihop_mc")
    ok = int(gold) in b.NUMBER_WORDS and int(gold) in b.ORDINALS
    item = _mh(name=f"mh-n{gold}", intermediates=[gold], bridge_type="number", bridge_aliases=[],
               target="x", prompt="Fact: A count of things is")  # fmt: skip
    assert (not _build_problems(item)) is ok


def test_mh_buildable_lint_reads_an_item_adapt_mc_already_built():
    item = _mh()
    item["mc"] = mcstage.script_module("build_multihop_mc").build_mc(copy.deepcopy(item))
    assert lint.lint("multihop_st", item) == []
    bad = _mh(intermediates=["South Africa"], bridge_type="country", bridge_aliases=[])
    bad["mc"] = {"bridge_type": "country", "gold": "South Africa", "aliases": []}
    assert _build_problems(bad)


def test_mh_buildable_lint_fails_safe_and_keeps_sys_path():
    import sys

    before = list(sys.path)
    for _ in range(3):
        assert not _build_problems(_mh(intermediates=["7"], bridge_type="number",
                                       bridge_aliases=[], target="x",
                                       prompt="Fact: A count of things is"))  # fmt: skip
    assert sys.path == before
    # a malformed authored field is rejected, never a crash of the whole lint batch
    assert _build_problems(_mh(mc_exclude=5))


def test_mc_build_drop_reject_still_comes_first():
    item = _mh(intermediates=["South Africa"], bridge_type="country", bridge_aliases=[])
    item["adapt"]["mc_build"] = {"dropped": True}
    assert lint.lint("multihop_st", item) == [
        "mc: the MC builder dropped this candidate (no options)"
    ]


def test_multihop_brief_names_only_buildable_bridge_kinds():
    b = mcstage.script_module("build_multihop_mc")
    br = author.BRIEFS["multihop_st"]
    assert all(t in br.invariants[-1] for t in b.POOLS)
    for tier in br.tiers.values():
        assert "moon" not in tier.lower() and "company" not in tier.lower()
