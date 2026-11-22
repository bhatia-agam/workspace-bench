"""Helpers both adapters share: text matching for the 'expected answer' flags and the cell
writer that fills a run database."""

import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from wsbench.viewer import store

MIN_TERM = 2  # a one-character expected answer matches too much to flag cells with


def fold(text: str) -> str:
    """Case and accent folding, for the string checks only (never a judge verdict)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def term_pattern(terms: Iterable[str]) -> re.Pattern[str] | None:
    """One regex matching any term as a whole word (word boundaries only where the term starts
    or ends with a word character, so CJK and symbol answers still match)."""
    parts = []
    for t in dict.fromkeys(fold(str(t)).strip() for t in terms if t is not None):
        if len(t) < MIN_TERM and not t.isdigit():
            continue
        left = r"(?<![\w])" if t[0].isalnum() else ""
        right = r"(?![\w])" if t[-1].isalnum() else ""
        parts.append(left + re.escape(t) + right)
    return re.compile("|".join(parts)) if parts else None


def strings(value: Any, limit: int = 24) -> list[str]:
    """Every short string inside a bank field (a string, a list, or a dict of forms)."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if len(out) >= limit or v is None or isinstance(v, bool):
            return
        if isinstance(v, int | float):
            out.append(str(v))
        elif isinstance(v, str):
            if v.strip() and len(v) <= 160:
                out.append(v.strip())
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for k in ("answer", "target", "gold", "canonical", "name", "text", "forms", "aliases",
                      "match"):  # fmt: skip
                if k in v:
                    walk(v[k])

    walk(value)
    return list(dict.fromkeys(out))


class CellWriter:
    """Buffers cell rows (and their text) into a run database."""

    def __init__(self, con: sqlite3.Connection, name: Callable[[Path], str] | None = None) -> None:
        """``name`` gives the address recorded for a readout file (default: its path); an
        ingest from a download cache records where the file lives, not the cache copy."""
        self.con = con
        self.name = name
        self.next_id = (con.execute("SELECT max(id) FROM cell").fetchone()[0] or 0) + 1
        self.cells: list[tuple] = []
        self.texts: list[tuple] = []
        self.sources: dict[str, int] = {}

    def source(self, path: Path) -> int:
        key = self.name(path) if self.name else str(path)
        if key not in self.sources:
            cur = self.con.execute(
                "INSERT OR IGNORE INTO source (path, size) VALUES (?, ?)",
                (key, path.stat().st_size),
            )
            row = self.con.execute("SELECT src FROM source WHERE path = ?", (key,)).fetchone()
            self.sources[key] = row[0] if row else cur.lastrowid
        return self.sources[key]

    def add(
        self,
        eval_name: str,
        item: str,
        layer: int,
        pos: int,
        token: str | None,
        samples: list[str] | None,
        flags: int,
        src: int | None = None,
        off: int | None = None,
        length: int | None = None,
        n_samples: int | None = None,
    ) -> None:
        n = n_samples if n_samples is not None else len(samples or [])
        self.cells.append(
            (self.next_id, eval_name, item, layer, pos, token, n, flags, src, off, length)
        )
        if samples is not None:
            self.texts.append((self.next_id, store.SAMPLE_SEP.join(samples)))
        self.next_id += 1
        if len(self.cells) >= 20000:
            self.flush()

    def flush(self) -> None:
        self.con.executemany(
            "INSERT OR IGNORE INTO cell VALUES (?,?,?,?,?,?,?,?,?,?,?)", self.cells
        )
        self.con.executemany("INSERT INTO readout (rowid, text) VALUES (?, ?)", self.texts)
        self.cells, self.texts = [], []


def sample_texts(row: dict) -> list[str]:
    """The samples of one readout row as strings: prose samples as they are, a top-k token
    list (J-lens, logit lens) as one line of tokens."""
    samples = row.get("samples")
    if isinstance(samples, list) and samples:
        return [s if isinstance(s, str) else json.dumps(s, ensure_ascii=False) for s in samples]
    tokens = row.get("tokens")
    if isinstance(tokens, list) and tokens:
        parts = [t[0] if isinstance(t, list | tuple) and t else t for t in tokens]
        return [" · ".join(str(p).strip() or repr(p) for p in parts)]
    return []


def remote_source(con: sqlite3.Connection, eval_name: str, address: str, size: int) -> None:
    """Record a readout file that was not read at ingest: the page reads a question's cells
    from it on demand (``readout_file``)."""
    con.execute("INSERT OR IGNORE INTO source (path, size) VALUES (?, ?)", (address, size))
    src = con.execute("SELECT src FROM source WHERE path = ?", (address,)).fetchone()[0]
    con.execute("INSERT OR IGNORE INTO readout_file VALUES (?, ?)", (eval_name, src))


def text_flags(samples: list[str], pattern: re.Pattern[str] | None, quotes: list[str]) -> int:
    """The string flags of one cell: an expected answer, or a judge quote, in a sample."""
    folded = [fold(s) for s in samples]
    flags = 0
    if pattern is not None and any(pattern.search(s) for s in folded):
        flags |= store.HAS_EXPECTED
    if any(fold(q) in s for q in quotes for s in folded):
        flags |= store.HAS_QUOTE
    return flags
