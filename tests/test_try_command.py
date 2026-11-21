"""``wsbench try``: the two-question try-out over the bundled example readouts."""

import json

import pytest

from wsbench import cli, readplan, tryout

EXAMPLE_FAMILIES = sorted(
    p.stem for p in tryout.EXAMPLES.glob("*.jsonl") if p.stem in readplan.families()
)


def test_pick_keeps_plan_order_and_needs_readouts(tmp_path, real_families):
    specs = tryout.pick("multihop", tryout.example_readouts("multihop"), 2)
    plan_ids = [s.id for s in readplan.plan("multihop")]
    assert [s.id for s in specs] == [i for i in plan_ids if i in {s.id for s in specs}]
    assert len(specs) == 2
    empty = tmp_path / "none.jsonl"
    empty.write_text('{"id": "not-an-item", "layer": 20, "pos": 0, "samples": ["x"]}\nnot json\n')
    with pytest.raises(SystemExit, match="no readouts for any item"):
        tryout.pick("multihop", empty, 2)


def test_describe_shows_question_and_expected_answer(real_families):
    specs = tryout.pick("multihop_st", tryout.example_readouts("multihop_st"), 2)
    text = tryout.describe("multihop_st", specs)
    assert "[1] atomic-26-symbol" in text
    assert "question: Fact: The chemical symbol for the element with atomic number 26 is" in text
    assert "expected: Fe" in text


def test_describe_keeps_the_latent_line_short(real_families):
    # the multi-token bank stores question texts and JSON records beside the bridge names
    specs = tryout.pick("multihop", tryout.example_readouts("multihop"), 1)
    looks = next(x for x in tryout.describe("multihop", specs).splitlines() if "looks for:" in x)
    assert looks.strip() == "looks for: Richard I of England | John of England"


def test_try_dry_run_writes_every_output(tmp_path, capsys, real_families):
    out = tmp_path / "try"
    assert cli.main(["try", "family=multihop_st", "dry_run=True", f"out={out}"]) == 0
    shown = capsys.readouterr().out
    assert "== wsbench try: multihop_st, 2 item(s)" in shown
    assert "expected: Fe" in shown and "expected: Au" in shown
    assert "== report" in shown and "== outputs" in shown
    plan = out / "plan" / "multihop_st.jsonl"
    plan_rows = [json.loads(x) for x in plan.read_text().splitlines()]
    assert [r["id"] for r in plan_rows] == ["atomic-26-symbol", "atomic-79-symbol"]
    results = json.loads((out / "judged" / "multihop_st" / "results.json").read_text())
    assert results["n_items"] == 2  # items= scoped the ordinary judge to the picked two
    assert (out / "judged" / "summary.md").is_file()
    for path in ("plan/multihop_st.jsonl", "judged/multihop_st/results.json", "judged/summary.md"):
        assert str(out / path) in shown


def test_try_takes_fewer_items_when_the_file_has_fewer(tmp_path, capsys, real_families):
    assert cli.main(["try", "family=multihop", "n=5", "dry_run=True", f"out={tmp_path}"]) == 0
    assert "readouts for 2 item(s) only, asked for 5" in capsys.readouterr().out


def test_try_usage_errors(tmp_path, capsys, real_families):
    assert cli.main(["try", "family=no_such_family"]) == cli.EXIT_USAGE
    missing = tmp_path / "missing.jsonl"
    assert cli.main(["try", "family=multihop", f"readouts={missing}"]) == cli.EXIT_USAGE
    assert "no readouts file" in capsys.readouterr().err
    assert cli.main(["try", "family=multihop", "n=0"]) == cli.EXIT_USAGE


@pytest.mark.parametrize("family", EXAMPLE_FAMILIES)
def test_try_runs_on_every_bundled_example(family, tmp_path, capsys, real_families):
    assert cli.main(["try", f"family={family}", "dry_run=True", f"out={tmp_path}"]) == 0
    assert "expected:" in capsys.readouterr().out
