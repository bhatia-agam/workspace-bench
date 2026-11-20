"""ADAPT_FLOORS_MISSING_ONLY: stock floor readouts are generated for missing ids only."""

import importlib
import json
import types

import pytest

from wsbench.adapt import floors


def _spec(iid):
    return types.SimpleNamespace(id=iid, positions="p", layers=[7], extra={})


def _row(iid, text="old"):
    return {"id": iid, "layer": 7, "pos": 0, "samples": [text]}


def test_merge_rows_keeps_planned_prunes_the_rest_and_refuses_a_clash():
    old = [_row("a"), _row("b"), _row("gone")]
    rows, kept, pruned = floors.merge_rows(old, {"a", "b", "new"}, [_row("new", "fresh")])
    assert [r["id"] for r in rows] == ["a", "b", "new"] and (kept, pruned) == (2, 1)
    assert rows[0] == old[0]  # byte-for-byte the stored row: the judge cache serves it
    with pytest.raises(SystemExit, match="already stored"):
        floors.merge_rows(old, {"a"}, [_row("a", "fresh")])


@pytest.mark.parametrize("missing_only", [True, False])
def test_generate_asks_only_the_missing_ids(tmp_path, monkeypatch, missing_only):
    rd = tmp_path / "floors" / "readouts"
    rd.mkdir(parents=True)
    stored = [_row("kept"), _row("dropped")]
    (rd / "basic_readout_st.jsonl").write_text("".join(json.dumps(r) + "\n" for r in stored))
    monkeypatch.setattr(floors, "_dir", lambda m: tmp_path / "floors")
    monkeypatch.setattr(floors.store, "model_dir", lambda m: tmp_path)
    monkeypatch.setattr(floors, "families", lambda m: ["basic_readout_st"])
    monkeypatch.setenv("WSB_BANK_ROOT", str(tmp_path))  # generate() sets it: restored after
    if missing_only:
        monkeypatch.setenv("ADAPT_FLOORS_MISSING_ONLY", "1")
    else:
        monkeypatch.delenv("ADAPT_FLOORS_MISSING_ONLY", raising=False)
    from wsbench import readplan
    from wsbench.adapt import gate, run

    render_mod = importlib.import_module("wsbench.produce.render")

    monkeypatch.setattr(readplan, "plan", lambda fam: [_spec("kept"), _spec("new")])
    monkeypatch.setattr(readplan, "resolve", lambda positions, tokens: [0])
    monkeypatch.setattr(render_mod, "render", lambda spec, tok: types.SimpleNamespace(
        tokens=["t"], ids=[1], decoded=["t"]))  # fmt: skip
    monkeypatch.setattr(gate, "prompt_of", lambda runner, ask: ask.item_id)
    asked: list[list[str]] = []

    class Runner:
        tok = types.SimpleNamespace(decode=lambda ids, skip_special_tokens=False: "t")

        def generate(self, prompts, temperature, max_new, seed=None):
            asked.append(list(prompts))
            return [{"text": f"gen-{p}"} for p in prompts]

    monkeypatch.setattr(run, "_runner", lambda m: Runner())
    floors.generate("m")
    rows = [json.loads(ln) for ln in (rd / "basic_readout_st.jsonl").read_text().splitlines()]
    if missing_only:
        assert asked == [["new"]]
        assert rows == [stored[0], _row("new", "gen-new")]
    else:  # the default is unchanged: the whole family is regenerated, the file rewritten
        assert asked == [["kept", "new"]]
        assert [r["samples"] for r in rows] == [["gen-kept"], ["gen-new"]]


def test_generate_missing_only_with_nothing_missing_asks_no_generation(tmp_path, monkeypatch):
    rd = _setup(tmp_path, monkeypatch, [_row("kept")])
    from wsbench import readplan
    from wsbench.adapt import run

    monkeypatch.setattr(readplan, "plan", lambda fam: [_spec("kept")])

    class Runner:
        tok = types.SimpleNamespace(decode=lambda ids, skip_special_tokens=False: "t")

        def generate(self, *a, **k):
            raise AssertionError("no prompt to generate")

    monkeypatch.setattr(run, "_runner", lambda m: Runner())
    floors.generate("m")
    assert (rd / "basic_readout_st.jsonl").read_text() == json.dumps(_row("kept")) + "\n"


def _setup(
    tmp_path, monkeypatch, stored_rows, fname="basic_readout_st.jsonl", fam="basic_readout_st"
):
    rd = tmp_path / "floors" / "readouts"
    rd.mkdir(parents=True)
    (rd / fname).write_text("".join(json.dumps(r) + "\n" for r in stored_rows))
    monkeypatch.setattr(floors, "_dir", lambda m: tmp_path / "floors")
    monkeypatch.setattr(floors.store, "model_dir", lambda m: tmp_path)
    monkeypatch.setattr(floors, "families", lambda m: [fam])
    monkeypatch.setenv("ADAPT_FLOORS_MISSING_ONLY", "1")
    monkeypatch.setenv("WSB_BANK_ROOT", str(tmp_path))  # generate() sets it: restored after
    from wsbench import readplan
    from wsbench.adapt import gate, run

    render_mod = importlib.import_module("wsbench.produce.render")
    monkeypatch.setattr(readplan, "plan", lambda f: [_spec("kept"), _spec("new")])
    monkeypatch.setattr(readplan, "resolve", lambda positions, tokens: [0])
    monkeypatch.setattr(render_mod, "render", lambda spec, tok: types.SimpleNamespace(
        tokens=["t"], ids=[1], decoded=["t"]))  # fmt: skip
    monkeypatch.setattr(gate, "prompt_of", lambda runner, ask: ask.item_id)

    class Runner:
        tok = types.SimpleNamespace(decode=lambda ids, skip_special_tokens=False: "t")

        def generate(self, prompts, temperature, max_new, seed=None):
            return [{"text": f"gen-{p}"} for p in prompts]

    monkeypatch.setattr(run, "_runner", lambda m: Runner())
    return rd


def test_generate_missing_only_refuses_a_kept_id_whose_cells_moved(tmp_path, monkeypatch):
    moved = {**_row("kept"), "pos": 3}  # today's plan reads position 0
    rd = _setup(tmp_path, monkeypatch, [moved])
    with pytest.raises(SystemExit, match="do not match its plan"):
        floors.generate("m")
    assert json.loads((rd / "basic_readout_st.jsonl").read_text()) == moved  # nothing written


def test_generate_missing_only_rewrites_a_former_key_file_in_place(tmp_path, monkeypatch):
    rd = _setup(tmp_path, monkeypatch, [_row("kept")], "multihop_mt_v2.jsonl", "multihop")
    floors.generate("m")
    assert sorted(p.name for p in rd.glob("*.jsonl")) == ["multihop_mt_v2.jsonl"]
    rows = [json.loads(ln) for ln in (rd / "multihop_mt_v2.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["kept", "new"] and rows[0] == _row("kept")


def test_generate_missing_only_with_no_stored_file_generates_everything(tmp_path, monkeypatch):
    rd = _setup(tmp_path, monkeypatch, [])
    (rd / "basic_readout_st.jsonl").unlink()
    floors.generate("m")
    rows = [json.loads(ln) for ln in (rd / "basic_readout_st.jsonl").read_text().splitlines()]
    assert [r["samples"] for r in rows] == [["gen-kept"], ["gen-new"]]
