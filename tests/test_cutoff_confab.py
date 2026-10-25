"""cutoff_confab: the ported exclusive longest-match matcher, the strict cell rule, the bank-wide
layer choice among layers with reply_start readouts, rows (id / pass / ati_pass), the read plan."""

import json
from pathlib import Path

import pytest

from wsbench import readplan
from wsbench.evals import cutoff_confab
from wsbench.evals.cutoff_confab import judge
from wsbench.evals.cutoff_confab.prompts import PROMPT_VERSION, SUBJECT_USER
from wsbench.evals.cutoff_confab.score import (
    OptionForms,
    best_layer,
    compile_form,
    plurality,
    strict_win,
    token_bag_text,
)
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.registry import JudgeArgs

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "readouts" / "cutoff_confab.jsonl"
BANK = json.loads((REPO / "evals" / "cutoff_confab" / "items.json").read_text(encoding="utf-8"))
ITEMS = BANK["items"]
A, B = ITEMS[0], ITEMS[1]  # cs00013 (gold "kirin 9100"), cs00017 (gold "64")


def _args(readouts: Path, tmp_path: Path, **kw) -> JudgeArgs:
    base = {
        "readouts": readouts,
        "out": tmp_path / "out",
        "judge": resolve(JudgeConfig(prompt_version=PROMPT_VERSION)),
        "layers": None,
        "items": [A["id"], B["id"]],
        "limit": 0,
        "allow_missing": False,
        "concurrency": 1,
        "rpm": 1.0,
        "dry_run": False,
    }
    base.update(kw)
    return JudgeArgs(**base)


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "r.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return p


def _cell(item: dict, layer: int, pos: int, samples: list[str]) -> dict:
    return {"id": item["id"], "layer": layer, "pos": pos, "samples": samples}


def test_bank_is_the_frozen_109_and_leaks_are_separate():
    assert len(ITEMS) == 109 and len({it["id"] for it in ITEMS}) == 109
    assert len(BANK["g3_leak_items"]) == 6
    assert not {it["id"] for it in ITEMS} & {it["id"] for it in BANK["g3_leak_items"]}
    for it in ITEMS:
        assert it["gold"] in it["options"] and set(it["option_units"]) == set(it["options"])
        want = SUBJECT_USER.replace("{question}", it["question"].strip())
        assert it["user"] == want.replace("{answer_type}", it["answer_type"].strip())


def test_number_forms_are_standalone():
    p = compile_form("1199")
    assert p.search("costs 1,199 dollars") and p.search("$1199") and p.search("1199元")
    assert not p.search("11990") and not p.search("1199.5") and not p.search("x1199")
    assert compile_form("131072").search("131 072 tokens")
    d = compile_form("6.23")
    assert d.search("version 6.23") and not d.search("16.23") and not d.search("6.234")
    assert compile_form("十八") is None and compile_form("  ") is None
    g = compile_form("9000s")
    assert g.search("the 9000s") and not g.search("19000s") and not g.search("6.9000s")


def test_exclusive_longest_match_and_contested_spans():
    f = OptionForms.build({"nintendo switch": [], "nintendo switch 2": ["Switch 2"]})
    assert f.named("It is the Nintendo Switch 2.") == {"nintendo switch 2"}
    assert f.named("the Nintendo Switch, not the Switch 2") == {
        "nintendo switch",
        "nintendo switch 2",
    }
    clash = OptionForms.build({"x": ["Aruba"], "y": ["aruba"]})
    assert clash.named("Aruba") == set()  # the identical span credits neither
    assert f.counts(["Nintendo Switch 2", "Switch 2 again", "nothing"]) == {
        "nintendo switch": 0,
        "nintendo switch 2": 2,
    }
    assert token_bag_text(["ĠKirin", " 9100 ", "▁x"]) == "Kirin 9100 x"


def test_strict_win_ties_lose_and_layer_ties_go_early():
    assert strict_win({"g": 2, "o": 1}, "g") and not strict_win({"g": 2, "o": 2}, "g")
    assert not strict_win({"g": 0, "o": 0}, "g")
    assert plurality({"g": 2, "o": 2, "p": 0}, "g") == 0.5
    assert best_layer({60: 3, 44: 3, 52: 1}) == 44 and best_layer({}) is None


def test_example_readouts_pass_at_the_bank_layer(tmp_path):
    r = judge.run(_args(EXAMPLE, tmp_path))
    rows = {row["id"]: row for row in r.rows}
    assert r.extras["headline_layer"] == 60 and r.value == 0.5
    assert rows[A["id"]]["pass"] is True and rows[A["id"]]["ati_pass"] is True
    assert rows[B["id"]]["pass"] is False and rows[B["id"]]["layer"] == 60
    assert r.counts["spend_usd"] == 0 and r.config["judge_model"] == "regex"


def test_one_layer_bank_wide_not_per_item(tmp_path):
    gold_a, gold_b = A["option_units"][A["gold"]][0], B["gold"]
    rows = [
        # A wins at 44 only, B wins at 60 only: a per-item rule would pass both
        _cell(A, 44, -1, [gold_a]),
        _cell(A, 60, -1, ["nothing named"]),
        _cell(B, 44, -1, ["nothing named"]),
        _cell(B, 60, -1, [f"answer {gold_b}"]),
        # user_end never feeds the pass, and a layer with no reply_start cell is no candidate
        _cell(A, 60, -10, [gold_a, gold_a]),
        _cell(A, 52, -10, [gold_a]),
        _cell(B, 52, -10, [f"answer {gold_b}"]),
    ]
    r = judge.run(_args(_write(tmp_path, rows), tmp_path))
    by = {row["id"]: row for row in r.rows}
    assert r.extras["headline_layer"] == 44  # 1-1 tie, earliest layer
    assert r.extras["candidate_layers"] == [44, 60]
    assert by[A["id"]]["pass"] is True and by[B["id"]]["pass"] is False and r.value == 0.5
    assert r.extras["per_layer_strict"]["user_end"]["52"] == 1.0


def test_tie_loses_and_ati_pass_is_any_mention(tmp_path):
    gold_a = A["option_units"][A["gold"]][0]
    other = next(o for o in A["options"] if o != A["gold"])
    rows = [_cell(A, 60, -1, [gold_a, other, "Kirin"]), _cell(B, 60, -1, ["no number"])]
    r = judge.run(_args(_write(tmp_path, rows), tmp_path))
    by = {row["id"]: row for row in r.rows}
    assert by[A["id"]]["pass"] is False and by[A["id"]]["ati_pass"] is True
    assert by[B["id"]]["ati_pass"] is False


def test_partial_layer_run_uses_its_own_layer(tmp_path):
    r = judge.run(_args(EXAMPLE, tmp_path, layers=[44]))
    assert r.extras["headline_layer"] == 44 and r.config["layers_judged"] == [44]
    by = {row["id"]: row for row in r.rows}
    assert by[A["id"]]["pass"] is False  # Kirin 9020 and 9100 tie at L44
    assert by[A["id"]]["ati_pass"] is True


def test_missing_cells_exit_and_rowless_items(tmp_path):
    rows = [_cell(A, 60, -1, ["Kirin 9100"]), _cell(A, 44, -1, ["x"]), _cell(B, 44, -1, ["x"])]
    with pytest.raises(SystemExit) as e:
        judge.run(_args(_write(tmp_path, rows), tmp_path))
    assert e.value.code == 2
    r = judge.run(_args(_write(tmp_path, rows), tmp_path, allow_missing=True))
    by = {row["id"]: row for row in r.rows}
    assert r.extras["headline_layer"] == 60
    assert by[A["id"]]["pass"] is True and by[B["id"]]["pass"] is None
    # an item with no readouts at all gets no row
    r2 = judge.run(_args(_write(tmp_path, rows[:1]), tmp_path, allow_missing=True))
    assert [row["id"] for row in r2.rows] == [A["id"]]
    assert r2.extras["n_items_without_readouts"] == 1


def test_off_site_positions_are_ignored(tmp_path):
    rows = [_cell(A, 60, 40, ["Kirin 9100"]), _cell(A, 60, -1, ["no"]), _cell(B, 60, -1, ["no"])]
    r = judge.run(_args(_write(tmp_path, rows), tmp_path))
    assert r.value == 0.0 and r.counts["skipped_rows"] == 1


def test_spec_and_plan():
    spec = cutoff_confab.SPEC
    assert spec.scorer == "regex" and spec.group == "precision"
    assert spec.not_in_macro == ""  # in the macro (Camila, 2026-10-25)
    plan = readplan.plan("cutoff_confab")
    assert [s.id for s in plan] == [it["id"] for it in ITEMS]
    s = plan[0]
    assert s.render == "chat" and s.text == A["user"] and s.layers == readplan.GRID
    assert s.positions == {"kind": "offsets_from_end", "ks": [10, 2, 1]}
    assert readplan.resolve(s.positions, ["t"] * 30) == [-10, -2, -1]
