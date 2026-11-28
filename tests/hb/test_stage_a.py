"""Plan 0120 stage A: the hand edits made when HallucinationBench moved into this repository."""

import hashlib
import json
from pathlib import Path

import pytest

from wsbench import registry
from wsbench.hb import DATA, REPO_ROOT, final, paths
from wsbench.hb.cli import build_parser
from wsbench.hb.evals.benign_roleplay import wsb

BANKS = (
    "wsbench_chat",
    "wsbench_chat_x3",
    "story",
    "agentic_misalignment",
    "sibling_probe",
    "overrefusal",
    "benign_roleplay",
    "calibration",
)


def test_prog_is_wsbench_hb() -> None:  # H1
    assert build_parser().prog == "wsbench hb"


def test_data_is_the_bank_directory_of_this_repository() -> None:  # M3
    assert REPO_ROOT == registry.REPO_ROOT
    assert DATA == REPO_ROOT / "evals" / "hallucinationbench"
    for name in BANKS:
        assert (DATA / name).is_dir(), name
    assert (DATA / "index" / "v8_manifest.json").is_file()


def _list(p: Path) -> dict[str, str]:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": final.PERSISTENT_VERSION, "cells": []}))
    return {"path": "data/index/list.json", "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def test_load_persistent_prefers_base_then_falls_back_to_data(tmp_path, monkeypatch) -> None:  # H2
    base, data = tmp_path / "base", tmp_path / "bank"
    ref = _list(data / "index" / "list.json")
    monkeypatch.setattr(final, "DATA", data)
    m = {"entries": [], "persistent_failures": ref}
    assert final.load_persistent(m, base) == {}  # no <base>/data/...: the file under DATA
    # a file at <base>/<path> wins, exactly as before the move (here: one with another sha256)
    (base / "data" / "index").mkdir(parents=True)
    (base / "data" / "index" / "list.json").write_text("{}")
    with pytest.raises(final.ManifestError, match="sha256 mismatch"):
        final.load_persistent(m, base)
    # only a leading `data/` is mapped
    with pytest.raises(final.ManifestError, match="missing file"):
        final.load_persistent(
            {"entries": [], "persistent_failures": {**ref, "path": "x.json"}}, base
        )


def test_the_frozen_manifest_finds_its_persistent_failures(tmp_path) -> None:  # H2
    m = final.load_manifest(DATA / "index" / "v8_manifest.json")
    assert m["persistent_failures"]["path"] == "data/index/v8_persistent_failures.json"
    assert final.load_persistent(m, tmp_path)


def test_pinned_env(monkeypatch) -> None:  # H4
    for k in ("PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "WSB_BANK_ROOT", "WSBENCH_OPENAI_ROUTE"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv(wsb.BANK_ENV, "/elsewhere.json")
    monkeypatch.setenv("HBENCH_WSBENCH_PUB", "/somewhere")
    monkeypatch.setenv("ANTHROPIC_PROFILE", "p")
    env = wsb.pinned_env()
    assert not [k for k in env if k.startswith(("WSB_", "WSBENCH_"))]
    assert "PYTHONPATH" not in env and "UV_PROJECT_ENVIRONMENT" not in env
    assert env["HBENCH_WSBENCH_PUB"] == "/somewhere" and env["ANTHROPIC_PROFILE"] == "p"
    assert env["PATH"]


def test_run_calls_sets_the_hb_only_bank_after_the_strip(monkeypatch) -> None:  # H4
    seen: list[dict[str, str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(wsb, "check_pin", lambda root, sha=wsb.WSB_SHA: None)
    monkeypatch.setattr(wsb.subprocess, "run", lambda argv, **kw: seen.append(kw["env"]) or Done())
    monkeypatch.setenv("PYTHONPATH", "/this/checkout/src")
    monkeypatch.setenv(wsb.BANK_ENV, "/elsewhere.json")
    wsb.run_calls(Path("."), [wsb.Call(["wsbench"]), wsb.Call(["wsbench"], {wsb.BANK_ENV: "hb"})])
    assert wsb.BANK_ENV not in seen[0] and "PYTHONPATH" not in seen[0]
    assert seen[1][wsb.BANK_ENV] == "hb" and "PYTHONPATH" not in seen[1]


def test_overrefusal_default_readouts_root(monkeypatch) -> None:  # H3
    import argparse

    from wsbench.hb.evals.overrefusal import cli

    assert "OR_READOUTS_V2_DEFAULT" in paths.__all__
    monkeypatch.delenv("HBENCH_OR_READOUTS", raising=False)
    none = argparse.Namespace(readouts_root=None)
    assert cli._readouts_root(none) == Path(paths.OR_READOUTS_V2_DEFAULT)
    monkeypatch.setenv("HBENCH_OR_READOUTS", "/env")
    assert cli._readouts_root(none) == Path("/env")
    assert cli._readouts_root(argparse.Namespace(readouts_root="/flag")) == Path("/flag")


def test_hb_dispatch_registers_nothing(monkeypatch, capsys) -> None:  # I1, I4
    from wsbench import cli, tiers

    def refuse() -> None:
        raise AssertionError("`wsbench hb` must not load the family registry")

    monkeypatch.setattr(registry, "load_all", refuse)
    before = (set(registry.FAMILIES), tuple(tiers.CORE), set(cli.COMMANDS))
    with pytest.raises(SystemExit) as e:
        cli.main(["hb", "--help"])
    assert e.value.code == 0 and "usage: wsbench hb" in capsys.readouterr().out
    assert (set(registry.FAMILIES), tuple(tiers.CORE), set(cli.COMMANDS)) == before
    assert "hb" not in cli.COMMANDS and "hallucination" in registry.REMOVED_FAMILIES
    assert not {n for n in registry._layout() if "hallucination" in n or n == "hb"}


def test_wsbench_cli_does_not_import_hb() -> None:
    import subprocess
    import sys

    code = (
        "import sys, wsbench.cli; "
        "hb = [m for m in sys.modules if m.split('.')[:2] == ['wsbench', 'hb']]; "
        "bad = hb or 'matplotlib' in sys.modules; "
        "sys.exit(1 if bad else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_imported_tree_is_pinned() -> None:
    """The imported code and banks equal the recorded import (no HallucinationBench checkout
    needed): a deliberate change to one of them updates `import_pin_0120.json` in the same PR."""
    repo = Path(__file__).resolve().parents[2]
    pin = json.loads((Path(__file__).parent / "import_pin_0120.json").read_text())
    here = {}
    for root, pattern in (("src/wsbench/hb", "*.py"), ("evals/hallucinationbench", "*")):
        for f in sorted((repo / root).rglob(pattern)):
            rel = f.relative_to(repo).as_posix()
            if f.is_file() and "__pycache__" not in rel and rel not in pin["not_pinned"]:
                here[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    assert here == pin["sha256"]
