"""The mismatched-target nulls of plan 0012 §1: derangements, the separate null batch, extras."""

from pathlib import Path

import pytest

from wsbench.banks import load_bank
from wsbench.basic import family as bfam
from wsbench.basic import judge as bjudge
from wsbench.basic.family import targets_of
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.multitoken import regex
from wsbench.multitoken.family import _mt_null_units
from wsbench.nulls import bank_partners, derangements, null_summary, surface_free, word_in
from wsbench.registry import JudgeArgs

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples/readouts/association.jsonl"
BANKS = ["association", "basic_readout", "multihop", "multilingual", "poetry", "typo"]


def test_word_in_is_whole_word_after_fold():
    assert word_in("7", "the answer is 7.") and not word_in("7", "it was 17")
    assert not word_in("art", "a fresh start") and word_in("Art", "modern art")
    assert word_in("café", "the CAFE downtown") and word_in("巴黎", "巴黎的春天")
    assert not word_in("", "anything")
    assert surface_free(["tennis"], "a racket sport at Wimbledon")
    assert not surface_free(["tennis", "Tennis"], "tennis balls")


def test_derangements_are_disjoint_constrained_and_deterministic():
    ids = [f"i{n}" for n in range(12)]
    allowed = {i: {p for p in ids if p != i and not (i == "i0" and p == "i1")} for i in ids}
    a = derangements(ids, allowed, k=3, seed="t")
    assert a == derangements(ids, allowed, k=3, seed="t")
    for m in a:
        assert sorted(m) == sorted(ids) == sorted(m.values())  # a permutation
        assert all(m[i] != i for i in ids) and m["i0"] != "i1"
    for i in ids:
        assert len({m[i] for m in a}) == 3  # edge-disjoint
    with pytest.raises(ValueError, match="no derangement"):
        derangements(["a", "b", "c"], {"a": {"b"}, "b": {"a"}, "c": {"a"}}, k=1, seed="x")


@pytest.mark.parametrize("name", BANKS)
def test_bank_partners_respect_the_constraints(name):
    _h, items = load_bank(REPO / "evals" / name / "items.json")
    by_id = {it["id"]: it for it in items}
    p = bank_partners(items, targets_of, family=name)
    assert p == bank_partners(items, targets_of, family=name)
    for i, ps in p.items():
        assert len(ps) == 3 and len(set(ps)) == 3 and i not in ps
        own = {t.casefold() for t in targets_of(by_id[i])}
        surface = str(by_id[i].get("target") or "").casefold()
        for q in ps:
            for t in targets_of(by_id[q]):
                assert t.casefold() not in own and t.casefold() != surface
                assert not word_in(t, by_id[i]["prompt"])


def test_null_summary_averages_draws_then_items():
    sm = null_summary({"a": [True, False, None], "b": [False, False, False], "c": [None]})
    assert sm["rate"] == pytest.approx(0.25) and sm["n"] == 2


def _args(tmp_path: Path, extra: dict[str, str]) -> JudgeArgs:
    return JudgeArgs(
        readouts=EXAMPLE,
        out=tmp_path / "out",
        judge=resolve(JudgeConfig(prompt_version=bfam.PROMPT_VERSION)),
        layers=[20, 36],
        items=["pt-carnaval", "chess", "bf-paris", "nasa"],
        limit=0,
        allow_missing=False,
        concurrency=1,
        rpm=1.0,
        dry_run=False,
        extra=extra,
    )


def test_null_batch_is_separate_and_never_moves_value(tmp_path, monkeypatch):
    seen: list[list[str]] = []

    def fake_run_calls(calls, **kw):
        seen.append([c.key for c in calls])
        out = {}
        for c in calls:
            if c.key.endswith("|null:0"):
                out[c.key] = {"expressed": True, "target": "x", "quote": "the clock ticking"}
            elif "|foil:" in c.key:
                out[c.key] = None  # every foil call fails: counted, never raised
            elif c.key == "chess|L20":
                out[c.key] = {"expressed": True, "target": "chess", "quote": "chess"}
            else:
                out[c.key] = {"expressed": False, "target": "", "quote": ""}
        return out

    monkeypatch.setattr(bjudge, "run_calls", fake_run_calls)
    monkeypatch.setattr(bfam, "load_foils", lambda path: {"chess": ["checkers"]})
    plain = bfam.run_family(
        _args(tmp_path, {}),
        name="association",
        bank=bfam.REPO_ROOT / "evals/association/items.json",
    )
    with_nulls = bfam.run_family(
        _args(tmp_path, {"null": "on"}),
        name="association",
        bank=bfam.REPO_ROOT / "evals/association/items.json",
    )
    assert plain.value == with_nulls.value == pytest.approx(0.25)
    assert plain.counts.keys() == with_nulls.counts.keys()
    assert with_nulls.counts["n_unjudged_cells"] == plain.counts["n_unjudged_cells"]
    assert "nulls" not in plain.extras
    assert len(seen) == 3 and not any("|null" in k or "|foil" in k for k in seen[1])
    n = with_nulls.extras["nulls"]
    # null:0 verifies only on chess (1 of its 3 draws); the 4 items are all decided
    assert n["null_rate"] == pytest.approx((1 / 3) / 4)
    assert n["foil_rate"] is None and n["null_failed"] == 2  # chess's 2 non-empty layers
    assert n["items"]["chess"]["foil:0"]["pass"] is None
    assert n["lift_null"] == pytest.approx(0.25 - (1 / 3) / 4)
    assert n["null_surface_free_share"] == 1.0
    assert set(n["null_partners"]) == {"pt-carnaval", "chess", "bf-paris", "nasa"}


def test_mt_null_never_gates_on_an_optional_language_unit():
    name = "multilingual_multihop"
    h, items = load_bank(REPO / "evals" / name / "items.json")
    c = regex.contract_for(h, str(h.get("family", name)))
    units_of = {it["id"]: regex.scored_units(it, c) for it in items}
    assert any(u.role == "language" and not u.required for u in units_of[items[0]["id"]])
    nu, partners = _mt_null_units(items, c, name, units_of)
    for i, lists in nu.items():
        assert len(lists) == 3 and len(partners[i]) == 3
        for units in lists:
            assert units and all(u.required for u in units)
            assert all(u.role != "language" for u in units)


def test_mt_null_keeps_the_items_own_required_language():
    name = "multilingual_mt"
    h, items = load_bank(REPO / "evals" / name / "items.json")
    c = regex.contract_for(h, str(h.get("family", name)))
    units_of = {it["id"]: regex.scored_units(it, c) for it in items}
    nu, _ = _mt_null_units(items, c, name, units_of)
    i = items[0]["id"]
    own_lang = [u for u in units_of[i] if u.role == "language"]
    for units in nu[i]:
        assert [u for u in units if u.role == "language"] == own_lang
