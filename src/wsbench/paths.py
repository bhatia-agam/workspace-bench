"""Locations outside the repo (source pools the adapt tools read). Each has its own environment
variable; unset, it sits under ``$WSB_DATA_ROOT`` (default: the dev box's ``/workspace``)."""

import os
from pathlib import Path

DATA_ROOT_ENV = "WSB_DATA_ROOT"
DEFAULT_DATA_ROOT = "/workspace"


def devbox(rel: str) -> Path:
    """``$WSB_DATA_ROOT/<rel>`` (the root defaults to ``/workspace``)."""
    return Path(os.environ.get(DATA_ROOT_ENV) or DEFAULT_DATA_ROOT) / rel


def external(var: str, rel: str) -> Path:
    """``$<var>`` when set, else :func:`devbox` of ``rel``."""
    return Path(os.environ[var]) if os.environ.get(var) else devbox(rel)
