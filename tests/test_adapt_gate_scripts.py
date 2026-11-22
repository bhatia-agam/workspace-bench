"""The gating and audit scripts beside the adapt tooling start without their external inputs:
``--help`` prints what each gates, its inputs, outputs and commands, and no box path is hardcoded
in them (external locations come from ``wsbench.paths``)."""

import os
import subprocess
import sys

import pytest

from wsbench import registry

SCRIPTS = registry.REPO_ROOT / "scripts"
PYTHON = ["adapt_gate_on_reference_bank.py", "adapt_gated_rescore.py", "adapt_set_audit.py"]
SHELL = ["adapt_rejudge_own_answers.sh"]


def _run(name: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = (
        [sys.executable, str(SCRIPTS / name)] if name.endswith(".py") else ["bash", SCRIPTS / name]
    )
    return subprocess.run(
        [*cmd, *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


@pytest.mark.parametrize("name", PYTHON + SHELL)
def test_help_runs_and_says_what_the_script_needs(name):
    done = _run(name, "--help")
    assert done.returncode == 0, done.stderr
    for word in ("Inputs", "Outputs", name):
        assert word in done.stdout, (name, word)


@pytest.mark.parametrize("name", PYTHON + SHELL)
def test_no_arguments_is_a_usage_error_not_a_traceback(name):
    done = _run(name)
    assert done.returncode != 0
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize("name", PYTHON + SHELL)
def test_no_box_path_is_hardcoded(name):
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "/workspace/agam" not in text and "/dev/shm" not in text


def test_external_locations_follow_the_environment(tmp_path):
    script = str(SCRIPTS / "adapt_gated_rescore.py")
    code = (
        f"import runpy; ns = runpy.run_path({script!r}, run_name='probe');"
        "print(ns['CKPTS']); print(ns['SPEC_DIR']); print(ns['OUT'])"
    )
    names = {"WSB_OLENS_CKPTS": "ckpts", "WSB_OLENS_SPEC_DIR": "spec", "WSB_GATED_OUT": "out"}
    env = {var: str(tmp_path / name) for var, name in names.items()}
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == [str(tmp_path / name) for name in names.values()]
