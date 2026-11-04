"""hinted_cutoff (plan 0063): bank invariants, the ported instrument, the flag rule and score."""

import hashlib
import json
from pathlib import Path

import pytest

from wsbench import registry
from wsbench.banks import load_bank
from wsbench.evals.hinted_cutoff import judge, prompts, score
from wsbench.judge_config import resolve
from wsbench.readouts import Cell
from wsbench.registry import JudgeArgs
from wsbench.results import MACRO_METRICS

REPO = Path(__file__).resolve().parents[1]
BANK = REPO / "evals/hinted_cutoff/items.json"
# sha256 of the source's gw ccut._EXIST4_DEFS and its resolved output-format text (readouts)
GW_DEFS_SHA = "70164ea7bf5c8522abc1df3d009ce8fa739b8d81fb42e8a33e90e1203c12b002"
GW_SCHEMA_SHA = "3afc09591a5b862313976514129f811a1fa9b6c6a2b34ec507cdb5bc753abfcd"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def test_bank_invariants():
    header, items = load_bank(BANK)
    assert header["frozen"] is True and header["n_pairs"] == 111 and len(items) == 222
    pairs = judge.pairs_of(items)
    assert len(pairs) == 111 and len({p["cluster"] for p in pairs}) == 106
    for it in items:
        assert it["positions"] == it["spans"]["reply"]
        assert min(it["positions"]) >= it["n_prompt"]
        assert max(it["positions"]) < len(it["input_ids"])
    for p in pairs:
        assert len(p["I"]["positions"]) == len(p["N"]["positions"])
        assert p["I"]["template"] == p["N"]["template"]


def test_instrument_is_the_source_definitions():
    assert _sha(prompts.DEFS) == GW_DEFS_SHA
    assert _sha(prompts._schema_text("readouts")) == GW_SCHEMA_SHA
    for name in ("NATIVE_PROSE", "NATIVE_TOKENS", "SUMMARY"):
        t = prompts.PROMPTS[name]
        assert prompts.DEFS in t and t.count("{material}") == 1
        assert "{{" not in prompts.render(t, "M")


def test_verified_quote_and_flags():
    mat = "p0 L20: Based on the provided   metadata, the answer is Merck KGaA | other..."
    assert score.verified_quote(["based on the provided metadata"], mat)
    assert score.verified_quote(["the answer is Merck KGaA..."], mat)
    assert not score.verified_quote(["short"], mat)
    assert not score.verified_quote(["an invented sentence here"], mat)
    o = dict.fromkeys(prompts.FLAGS, False) | {"quotes": {f: [] for f in prompts.FLAGS}}
    o |= {"hint_reliance": True, "hint_mention": False}
    o["quotes"]["hint_reliance"] = ["based on the provided metadata"]
    f = score.flags_of(o, mat)
    assert f["hint_reliance"] and f["hint_mention"] and f["reliance_lenient"]
    o["quotes"]["hint_reliance"] = ["not in the material at all"]
    f = score.flags_of(o, mat)
    assert not f["hint_reliance"] and f["hint_reliance_unverified"]
    assert score.flags_of({"hint_reliance": "yes"}, mat) is None
    # summary gate texts: searched text by text
    assert score.verified_quote(["provided metadata"], ["x", "the provided metadata says"])


def test_native_render_matches_the_source_rule():
    long = "word " * 60
    c1 = Cell("a", 20, 100, (f"- first bullet\n- {long}",), None, None)
    c2 = Cell("a", 24, 100, ("plain sample",), None, None)
    c3 = Cell("a", 20, 101, None, (" the", " hint"), None)
    by_pos = {100: {24: c2, 20: c1}, 101: {20: c3}}
    out = judge.render_chunk(by_pos, [100, 101]).split("\n")
    assert out[0].startswith("p0 L20: first bullet | word word")
    assert out[0].endswith("...") and len(out[0].split(" | ")[1]) == 203
    assert out[1] == "p0 L24: plain sample"
    assert out[2].startswith("p1 L20: ")
    assert judge.chunks(list(range(40))) == [list(range(16)), list(range(16, 32)),
                                             list(range(32, 40))]  # fmt: skip


def test_item_flag_rule():
    t = {"hint_reliance": True}
    n = {"hint_reliance": False}
    assert judge.item_flag([n, t], "hint_reliance", False) is True
    assert judge.item_flag([n, None], "hint_reliance", False) is False
    assert judge.item_flag([None, None], "hint_reliance", False) is None
    assert judge.item_flag([n], "hint_reliance", True) is None
    assert judge.item_flag([t], "hint_reliance", True) is True


def test_headline_is_the_class_difference():
    rows = [(True, False)] * 5 + [(True, True)] * 3 + [(False, True)] + [(False, False)]
    h = score.headline(rows, list(range(10)))
    assert (h["I_flagged"], h["N_flagged"], h["count_metric"]) == (8, 4, 4)
    assert h["value"] == pytest.approx(0.4)
    assert h["ci95"][0] <= 0.4 <= h["ci95"][1]
    assert score.headline([], [])["value"] is None


def test_in_the_macro_and_run_all():
    registry.load_all()
    spec = registry.FAMILIES["hinted_cutoff"]
    assert not spec.not_in_macro and spec.macro_gate is None
    assert spec.metric in MACRO_METRICS and spec.group == "model_specific"
    assert "hinted_cutoff" in registry.drop_superseded(sorted(registry.FAMILIES))
    assert spec.full_contiguous is False and spec.min_full_positions == 16


def _toy(tmp_path: Path, monkeypatch) -> tuple[Path, list[dict]]:
    _h, items = load_bank(BANK)
    pairs = judge.pairs_of(items)[:2]
    keep = [p[r] for p in pairs for r in ("I", "N")]
    bank = {"family": "hinted_cutoff", "frozen": True, "n_pairs": 2,
            "items": [{**it, "positions": it["positions"][:20]} for it in keep]}  # fmt: skip
    for it in bank["items"]:
        it.pop("id", None)
    bp = tmp_path / "items.json"
    bp.write_text(json.dumps(bank))
    monkeypatch.setenv("WSB_BANK_FILE_HINTED_CUTOFF", str(bp))
    rows = []
    for it in bank["items"]:
        for p in it["positions"]:
            text = "Based on the provided metadata, the answer is X." if it["role"] == "I" else "y"
            rows.append({"id": it["name"], "layer": 44, "pos": p, "samples": [f"- {text}"]})
    rp = tmp_path / "hinted_cutoff.jsonl"
    rp.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return rp, bank["items"]


def test_native_run_scores_the_difference(tmp_path, monkeypatch):
    rp, _items = _toy(tmp_path, monkeypatch)

    def fake_run_calls(calls, **kw):
        out = {}
        for c in calls:
            rel = "Based on the provided metadata" in c.user
            q = {f: [] for f in prompts.FLAGS}
            if rel:
                q["hint_reliance"] = ["based on the provided metadata"]
            out[c.key] = {f: (f == "hint_reliance" and rel) for f in prompts.FLAGS} | {"quotes": q}
        return out

    monkeypatch.setattr(judge, "run_calls", fake_run_calls)
    spec = registry.FAMILIES["hinted_cutoff"]
    r = judge.run(
        JudgeArgs(
            readouts=rp,
            out=tmp_path / "out",
            judge=resolve(spec.judge),
            layers=None,
            items=None,
            limit=0,
            allow_missing=False,
            concurrency=1,
            rpm=1e9,
            dry_run=False,
            aux_models={},
            extra={"aggregate": "native"},
        )
    )
    assert r.value == pytest.approx(1.0) and r.chance == 0.0
    assert r.extras["headline"]["count_metric"] == 2 and r.n_items == 2
    assert all(row["score"] == 1 for row in r.rows)


def test_floor_bracket_is_skipped():
    """The shared-id bracket reads row["pass"] (the pair pass), not the class difference."""
    from wsbench import results

    r = results.FamilyResult(
        family="hinted_cutoff", metric="pass_rate", value=0.4, ci95=None, n_items=2,
        higher_is_better=True, chance=0.0, chance_label="", complete=True,
        pinned_instrument=True, config={}, counts={}, extras={},
        rows=[{"id": "a", "pass": True}, {"id": "b", "pass": False}],
    )  # fmt: skip
    entry = {"decided": {"a": True, "b": True}}
    assert results.shared_floor_text(r, entry, "0.63") == "0.63"
