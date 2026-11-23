"""``wsbench check``: the registry of gates and sanity checks, and its plug-in point."""

import json

import pytest

from wsbench import checks, cli, fast, registry


def passing(colour: str = "green"):
    """A plug-in check that always passes."""
    return True, f"all {colour}"


def failing(needed: str):
    """A plug-in check that always fails."""
    return False, f"saw {needed}"


def exiting():
    raise SystemExit("bank changed since the freeze")


@pytest.fixture(autouse=True)
def _restore_registry():
    saved = dict(checks.REGISTRY)
    yield
    checks.REGISTRY.clear()
    checks.REGISTRY.update(saved)


def test_every_builtin_check_resolves_and_has_a_description():
    for check in checks.REGISTRY.values():
        assert callable(check.function()), check.name
        assert check.guards.endswith("."), check.name
    assert {"fast_subset", "ati_subset", "readme_prompts", "readouts_contract"} <= set(
        checks.REGISTRY
    )
    assert "readouts_contract" not in checks.offline()  # it needs readouts=
    assert "fast_subset" in checks.offline()


def test_list_prints_every_check_with_its_options(capsys):
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    for check in checks.REGISTRY.values():
        assert check.name in out and check.guards in out
    assert "readouts_contract readouts= [family=]" in out


def test_fast_subset_passes_and_fails_closed_on_a_changed_bank(monkeypatch, capsys, real_families):
    assert cli.main(["check", "fast_subset"]) == 0
    assert capsys.readouterr().out.startswith("PASS  fast_subset: 16 bank files match")
    monkeypatch.setattr("wsbench.fast.bank_sha", lambda family: "0" * 64)
    assert cli.main(["check", "fast_subset"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("FAIL  fast_subset:") and f"bank changed since {fast.DEFAULT}" in out


def test_ati_subset_passes(capsys, real_families):
    assert cli.main(["check", "name=ati_subset"]) == 0
    assert "entries match their judge instrument and bank" in capsys.readouterr().out


def test_readouts_contract(tmp_path, capsys, real_families):
    good = registry.REPO_ROOT / "examples" / "readouts" / "multihop.jsonl"
    assert cli.main(["check", "readouts_contract", f"readouts={good}", "family=multihop"]) == 0
    assert "4 cells of 2 items" in capsys.readouterr().out
    bad = tmp_path / "bad.jsonl"
    row = {"id": "atomic-26-symbol", "layer": 20, "pos": 1, "samples": ["x"]}
    bad.write_text(json.dumps(row) + "\nnot json\n")
    assert cli.main(["check", "readouts_contract", f"readouts={bad}"]) == 1
    assert '"malformed": 1' in capsys.readouterr().out
    stranger = tmp_path / "stranger.jsonl"
    stranger.write_text(json.dumps({**row, "id": "not-an-item"}) + "\n")
    assert cli.main(["check", "readouts_contract", f"readouts={stranger}", "family=multihop"]) == 1
    assert "not in the multihop read plan" in capsys.readouterr().out
    assert cli.main(["check", "readouts_contract", f"readouts={tmp_path / 'none'}"]) == 1


def test_judge_dry_run_on_one_family(capsys, real_families):
    assert cli.main(["check", "judge_dry_run", "family=poetry"]) == 0
    assert "1 families build their first judge prompt" in capsys.readouterr().out


def test_adapt_gate_reads_a_set(tmp_path, monkeypatch, capsys):
    root = tmp_path / "adapted" / "toy"
    root.mkdir(parents=True)
    monkeypatch.setattr(registry, "REPO_ROOT", tmp_path)
    assert cli.main(["check", "adapt_gate", "model=toy"]) == 1  # no report.json
    (root / "report.json").write_text(json.dumps({"families": {"multihop": {}}}))
    items = [{"id": "a", "adapt": {"gate": {"pass": True}}}, {"id": "b"}]
    (root / "multihop.json").write_text(json.dumps({"items": items}))
    capsys.readouterr()
    assert cli.main(["check", "adapt_gate", "model=toy"]) == 0
    assert "1 of 2 shipped items carry a passing gate record, 1 carry no" in capsys.readouterr().out
    items[1]["adapt"] = {"gate": {"pass": False}}
    (root / "multihop.json").write_text(json.dumps({"items": items}))
    assert cli.main(["check", "adapt_gate", "model=toy"]) == 1
    assert "item b ships a failed gate" in capsys.readouterr().out


def test_capable_gate_dry_run(capsys, real_families):
    argv = ["check", "capable_gate", "model=some-model", "family=multihop", "limit=2"]
    assert cli.main([*argv, "dry_run=True"]) == 0
    assert "nothing sent" in capsys.readouterr().out


def test_pytest_outcome_reports_the_last_line():
    ok, why = checks.pytest_outcome("tests/test_prompts_in_readme.py::test_fence_parser")
    assert ok and "1 passed" in why
    ok, why = checks.pytest_outcome("tests/no_such_test_file.py")
    assert not ok


def test_usage_errors(capsys):
    assert cli.main(["check", "no_such_check"]) == cli.EXIT_USAGE
    assert "unknown check" in capsys.readouterr().err
    assert cli.main(["check", "readouts_contract"]) == cli.EXIT_USAGE
    assert "needs readouts=" in capsys.readouterr().err
    assert cli.main(["check", "fast_subset", "model=x"]) == cli.EXIT_USAGE
    assert "does not take ['model']" in capsys.readouterr().err
    assert cli.main(["check", "fast_subset", "options=novalue"]) == cli.EXIT_USAGE


def test_plugin_checks_by_dotted_path(monkeypatch, capsys):
    here = "test_check_command"
    monkeypatch.setenv(
        checks.PLUGIN_ENV, f"ok={here}:passing, bad={here}:failing,boom={here}:exiting"
    )
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "ok [colour=]\n    A plug-in check that always passes." in out
    assert "bad needed=" in out
    assert cli.main(["check", "ok", "options=colour=blue"]) == 0
    assert capsys.readouterr().out == "PASS  ok: all blue\n"
    assert cli.main(["check", "bad", "options=needed=red"]) == 1
    assert capsys.readouterr().out == "FAIL  bad: saw red\n"
    assert cli.main(["check", "boom"]) == 1  # a guard that fails closed with SystemExit
    assert capsys.readouterr().out == "FAIL  boom: bank changed since the freeze\n"
    monkeypatch.setenv(checks.PLUGIN_ENV, "nodots")
    assert cli.main(["check"]) == cli.EXIT_USAGE


def test_check_all_runs_only_optionless_checks(monkeypatch, capsys):
    checks.REGISTRY.clear()
    here = "test_check_command"
    checks.register("ok", "Always passes.", f"{here}:passing")
    checks.register("bad", "Always fails.", f"{here}:failing")
    assert cli.main(["check", "all"]) == 0
    assert capsys.readouterr().out == (
        "PASS  ok: all green\n"
        "SKIP  bad: skipped (needs needed=...); run: wsbench check bad needed=...\n"
    )
    with pytest.raises(ValueError, match="module:function"):
        checks.register("x", "y", "no_colon")


def test_check_all_names_what_it_skips(monkeypatch, capsys):
    monkeypatch.setattr(checks, "offline", lambda: [])  # run nothing: only the skipped lines
    assert cli.main(["check", "all"]) == 0
    out = capsys.readouterr().out
    assert "SKIP  readouts_contract: skipped (needs readouts=...)" in out
    assert "SKIP  capable_gate: skipped (needs model=...)" in out and "fast_subset" not in out


def test_the_offline_checks_name_things_by_role(capsys):
    """A PASS line says what was checked, without the version id of a subset."""
    import re

    for name in ("fast_subset", "ati_subset"):
        assert cli.main(["check", name]) == 0
        line = capsys.readouterr().out
        assert line.startswith(f"PASS  {name}:") and not re.search(r"\bv\d|-v\d", line), line
