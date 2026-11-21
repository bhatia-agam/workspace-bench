"""External locations come from the environment (``wsbench.paths``); the defaults are the dev
box paths the pools were built on, and no other absolute box path is hardcoded in ``src``."""

import ast
import importlib
import os
from pathlib import Path

import pytest

from wsbench import paths

SRC = Path(paths.__file__).resolve().parent
# (module, attribute, its own variable or None, the default before paths.py existed)
LOCATIONS = [
    (
        "wsbench.adapt.kcutoff",
        "SOURCE_ROOT",
        "WSB_KCUTOFF_SOURCE",
        "/workspace/gw-evals-feas/outputs/feas/cutoff_confab/scale",
    ),
    (
        "wsbench.adapt.msdm",
        "GW_ROOT",
        "WSB_MSDM_SOURCE",
        "/workspace/gw-evals-feas/outputs/feas/self_answers",
    ),
    ("wsbench.adapt.mhmt2", "GW_DIR", None, "/workspace/gw-mh-v2/outputs/multihop_v2"),
    ("wsbench.adapt.refill", "DEFAULT_POOL_DIR", None, "/workspace/wsb-runs/pools"),
]
WI_POOLS = tuple(
    f"/workspace/gw-wrong-bridge/outputs/wrong_bridge{suffix}"
    for suffix in ("", "_r2a", "_r2b", "_r3", "_r4")
)
VARIABLES = (paths.DATA_ROOT_ENV, "WSB_KCUTOFF_SOURCE", "WSB_MSDM_SOURCE", "WSB_WI_POOL_ROOT")


def test_defaults_are_the_former_literals():
    if any(os.environ.get(v) for v in VARIABLES):
        pytest.skip("a location variable is set in this environment")
    for name, attr, _var, old in LOCATIONS:
        assert str(getattr(importlib.import_module(name), attr)) == old, (name, attr)
    assert importlib.import_module("wsbench.adapt.wrong_intermediate").DEFAULT_POOLS == WI_POOLS


def test_data_root_moves_a_default(monkeypatch, tmp_path):
    monkeypatch.delenv("WSB_KCUTOFF_SOURCE", raising=False)
    monkeypatch.delenv(paths.DATA_ROOT_ENV, raising=False)
    assert paths.devbox("wsb-runs/pools") == Path("/workspace/wsb-runs/pools")
    assert paths.external("WSB_KCUTOFF_SOURCE", "a/b") == Path("/workspace/a/b")
    monkeypatch.setenv(paths.DATA_ROOT_ENV, str(tmp_path))
    assert paths.devbox("wsb-runs/pools") == tmp_path / "wsb-runs/pools"
    assert paths.external("WSB_KCUTOFF_SOURCE", "a/b") == tmp_path / "a/b"


def test_a_location_variable_wins_over_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.DATA_ROOT_ENV, "/somewhere/else")
    monkeypatch.setenv("WSB_KCUTOFF_SOURCE", str(tmp_path / "scale"))
    assert paths.external("WSB_KCUTOFF_SOURCE", "a/b") == tmp_path / "scale"
    monkeypatch.setenv("WSB_KCUTOFF_SOURCE", "")  # empty counts as unset
    assert paths.external("WSB_KCUTOFF_SOURCE", "a/b") == Path("/somewhere/else/a/b")


def test_the_location_variables_are_the_documented_ones():
    from wsbench.adapt import kcutoff, mhmt2, msdm, wrong_intermediate

    assert kcutoff.SOURCE_ENV == "WSB_KCUTOFF_SOURCE" and msdm.GW_ROOT_ENV == "WSB_MSDM_SOURCE"
    assert wrong_intermediate.POOL_ROOT_ENV == "WSB_WI_POOL_ROOT"
    assert mhmt2.GW_DIR_ENV == "WSB_GW_MH2_DIR"  # read at call time, as before


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def test_no_box_path_literal_in_src():
    """Every string literal in ``src`` (docstrings aside) is free of absolute dev-box paths;
    the one default root lives in ``paths.py``."""
    found = []
    for file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in skip or file.name == "paths.py":
                continue
            if "/workspace/" in node.value or node.value.startswith(("/workspace", "/root/")):
                found.append(f"{file.relative_to(SRC)}:{node.lineno}: {node.value[:60]!r}")
    assert not found, found
