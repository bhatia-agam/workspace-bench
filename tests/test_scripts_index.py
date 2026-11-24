"""`scripts/README.md` has one row for every file under `scripts/` (the archive has its own page),
and names no file that is not there."""

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
KINDS = {".py", ".sh", ".json", ".txt"}


def on_disk() -> set[str]:
    files = (p for p in SCRIPTS.rglob("*") if p.is_file() and p.suffix in KINDS)
    rel = {p.relative_to(SCRIPTS).as_posix() for p in files}
    return {r for r in rel if not r.startswith("archive/") and "__pycache__" not in r}


def rows() -> list[str]:
    """The first cell of every table row: the file name in code formatting."""
    text = (SCRIPTS / "README.md").read_text(encoding="utf-8")
    return re.findall(r"^\| `([^`|]+)` \|", text, flags=re.M)


def test_every_script_has_a_row():
    assert sorted(on_disk() - set(rows())) == []


def test_every_row_names_a_file_that_exists_and_only_once():
    listed = rows()
    assert sorted(set(listed) - on_disk()) == []
    assert sorted(r for r in set(listed) if listed.count(r) > 1) == []
