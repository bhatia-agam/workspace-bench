"""Stock floors: readout lines with U+2028 in a sample, and an empty family readout file."""

import json
import types

from wsbench.adapt import floors


def _row(iid, text):
    return {"id": iid, "layer": 7, "pos": 0, "samples": [text]}


def test_stored_keeps_a_row_whose_sample_holds_a_line_separator(tmp_path):
    rd = tmp_path / "readouts"
    rd.mkdir()
    rows = [_row("a", "one\u2028two\u0085three"), _row("b", "plain")]
    # ensure_ascii=False, as generate() writes: U+2028 / U+0085 stay raw inside the JSON string
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    assert "\u2028" in text
    (rd / "basic_readout_st.jsonl").write_text(text, encoding="utf-8")
    assert floors._stored(rd, "basic_readout_st") == rows


def test_judge_records_an_empty_family_file_and_judges_the_rest(tmp_path, monkeypatch):
    fdir = tmp_path / "floors"
    rd = fdir / "readouts"
    rd.mkdir(parents=True)
    (rd / "poetry.jsonl").write_text("", encoding="utf-8")  # no planned items
    (rd / "typo.jsonl").write_text(json.dumps(_row("t1", "x")) + "\n", encoding="utf-8")
    monkeypatch.setattr(floors, "_dir", lambda m: fdir)
    monkeypatch.setattr(floors.store, "model_dir", lambda m: tmp_path)
    monkeypatch.setattr(floors, "judge_opts", lambda m, f: "opts=aggregate=native")
    monkeypatch.setenv("WSB_ANTHROPIC_AUTH", "sdk")
    monkeypatch.delenv("ADAPT_FLOORS_FAMILIES", raising=False)
    judged: list[str] = []

    def fake_run(cmd, env, check, capture_output, text):
        fam = next(a.split("=", 1)[1] for a in cmd if a.startswith("family="))
        judged.append(fam)
        res = fdir / "results" / fam
        res.mkdir(parents=True, exist_ok=True)
        (res / "results.json").write_text(json.dumps(
            {"numbers": {"value": 0.25, "metric": "pass_rate"}, "n_items": 1,
             "config": {"prompt_version": "pv"}}))  # fmt: skip
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(floors.subprocess, "run", fake_run)
    written: dict = {}
    monkeypatch.setattr(floors, "merge_record", lambda d, rec: written.update(rec))
    rec = floors.judge("m")
    assert judged == ["typo"]
    assert rec["families"]["typo"]["rate"] == 0.25
    assert rec["families"]["poetry"]["n_items"] == 0
    assert rec["families"]["poetry"]["rate"] is None
    assert written["families"] == rec["families"]
