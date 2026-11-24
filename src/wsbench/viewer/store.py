"""The results store the viewer reads: ``catalog.db`` (runs, evals, scores, items), one
``runs/<run>.db`` per ingested lens (cells, readouts, judgments) and ``user.db`` (bookmarks).
Ingest writes it, the app only reads it; ``manifest.json`` documents every table."""

import json
import os
import re
import sqlite3
import time
import zlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

STORE_ENV = "WSB_VIEWER_STORE"
DEFAULT_STORE = "outputs/viewer_store"
SCHEMA = 1
BUSY_SECONDS = 30  # a page waits this long for an ingest that is committing
SAMPLE_SEP = "\x1e"  # joins the samples of one cell inside the full-text table

# cell.flags bits
HAS_EXPECTED = 1  # a sample contains an expected answer (string match, not a judge verdict)
HAS_QUOTE = 2  # a sample contains the quote the judge gave as evidence
CITED = 4  # the digest the judge read cites this cell

CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY, bench TEXT, lens TEXT, label TEXT, method TEXT, model TEXT,
  judge TEXT, mode TEXT, source TEXT, source_sig TEXT, db TEXT, ingested_at REAL, meta TEXT);
CREATE TABLE IF NOT EXISTS eval (
  bench TEXT, model TEXT, eval TEXT, title TEXT, grp TEXT, ord INTEGER, what TEXT,
  example TEXT, judged_by TEXT, prompt_template TEXT, gates TEXT, n_items INTEGER,
  metric TEXT, higher_is_better INTEGER, readme TEXT,
  PRIMARY KEY (bench, model, eval));
CREATE TABLE IF NOT EXISTS item (
  bench TEXT, model TEXT, eval TEXT, item TEXT, ord INTEGER, prompt TEXT, expected TEXT,
  intermediates TEXT, subfamily TEXT, private INTEGER DEFAULT 0, meta TEXT,
  PRIMARY KEY (bench, model, eval, item));
CREATE TABLE IF NOT EXISTS subset_item (
  bench TEXT, model TEXT, subset TEXT, eval TEXT, item TEXT,
  PRIMARY KEY (bench, model, subset, eval, item));
CREATE TABLE IF NOT EXISTS score (
  run_id TEXT, eval TEXT, subset TEXT, layer INTEGER, kind TEXT, value REAL, ci_lo REAL,
  ci_hi REAL, n INTEGER, note TEXT,
  PRIMARY KEY (run_id, eval, subset, layer, kind));
CREATE TABLE IF NOT EXISTS verdict (
  run_id TEXT, eval TEXT, item TEXT, pass INTEGER, score REAL,
  PRIMARY KEY (run_id, eval, item));
CREATE TABLE IF NOT EXISTS layer_stat (
  run_id TEXT, eval TEXT, layer INTEGER, kind TEXT, hits REAL, n INTEGER,
  PRIMARY KEY (run_id, eval, layer, kind));
CREATE INDEX IF NOT EXISTS verdict_item ON verdict (eval, item);
CREATE TABLE IF NOT EXISTS item_tokens (
  bench TEXT, model TEXT, eval TEXT, item TEXT, tokens BLOB,
  PRIMARY KEY (bench, model, eval, item));
CREATE TABLE IF NOT EXISTS run_facts (
  run_id TEXT PRIMARY KEY, run_name TEXT, set_name TEXT, bench_commit TEXT, engine TEXT,
  cells INTEGER, read_gpu_hours REAL, read_wall_seconds REAL, judge_wall_seconds REAL,
  judge_calls INTEGER, judge_usd REAL, total_usd REAL, total_wall_seconds REAL,
  integrity TEXT, integrity_reason TEXT, readouts TEXT, headline TEXT, entry TEXT);
CREATE TABLE IF NOT EXISTS run_set (
  run_id TEXT, subset TEXT, derived INTEGER DEFAULT 0, origin TEXT, note TEXT,
  PRIMARY KEY (run_id, subset));
CREATE TABLE IF NOT EXISTS run_eval (
  run_id TEXT, eval TEXT, integrity TEXT, reason TEXT, facts TEXT,
  PRIMARY KEY (run_id, eval));
CREATE TABLE IF NOT EXISTS hb_index (
  run_id TEXT, layer INTEGER, key TEXT, kind TEXT, value REAL, ci_lo REAL, ci_hi REAL,
  n INTEGER, n_items INTEGER,
  PRIMARY KEY (run_id, layer, key));
"""
# tables that hold one run's rows and are cleared when the run is ingested again
PER_RUN_TABLES = ("score", "verdict", "layer_stat", "run_set", "run_eval", "hb_index")
# item.ord of a question an earlier version of its eval's bank held and the current one does
# not: kept with its text for the runs judged on it, never listed among the eval's questions
EARLIER_BANK = 200000
JOINT_LAYER = -2  # hb_index.layer of the index's joint row (layer "all")
ALIASES = "lens_aliases.json"

RUN_DDL = """
CREATE TABLE IF NOT EXISTS source (src INTEGER PRIMARY KEY, path TEXT UNIQUE, size INTEGER);
CREATE TABLE IF NOT EXISTS cell (
  id INTEGER PRIMARY KEY, eval TEXT, item TEXT, layer INTEGER, pos INTEGER, token TEXT,
  n_samples INTEGER, flags INTEGER DEFAULT 0, src INTEGER, off INTEGER, len INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS cell_key ON cell (eval, item, layer, pos);
CREATE VIRTUAL TABLE IF NOT EXISTS readout USING fts5 (text, detail = none, columnsize = 0);
CREATE TABLE IF NOT EXISTS judgment (
  eval TEXT, item TEXT, layer INTEGER, pos INTEGER, stage TEXT, key TEXT, result BLOB,
  meta TEXT);
CREATE INDEX IF NOT EXISTS judgment_item ON judgment (eval, item);
CREATE TABLE IF NOT EXISTS verdict (
  eval TEXT, item TEXT, row INTEGER, pass INTEGER, score REAL, detail BLOB,
  PRIMARY KEY (eval, item, row));
CREATE TABLE IF NOT EXISTS hb_segment (
  eval TEXT, item TEXT, layer INTEGER, pos INTEGER, sample INTEGER, unit TEXT, start INTEGER,
  end INTEGER, leaf TEXT, weight REAL, why TEXT, contradicted_by TEXT, supported_by TEXT,
  checks TEXT, tags TEXT);
CREATE INDEX IF NOT EXISTS hb_segment_item ON hb_segment (eval, item);
CREATE TABLE IF NOT EXISTS digest (eval TEXT, item TEXT, text BLOB, PRIMARY KEY (eval, item));
CREATE TABLE IF NOT EXISTS target (
  eval TEXT, item TEXT, terms TEXT, quotes TEXT, PRIMARY KEY (eval, item));
CREATE TABLE IF NOT EXISTS readout_file (eval TEXT, src INTEGER, PRIMARY KEY (eval, src));
"""

USER_DDL = """
CREATE TABLE IF NOT EXISTS bookmark (
  id INTEGER PRIMARY KEY, bench TEXT, model TEXT, eval TEXT, item TEXT, run_id TEXT,
  layer INTEGER, pos INTEGER, note TEXT, created REAL);
"""

MANIFEST: dict[str, Any] = {
    "schema": SCHEMA,
    "layout": {
        "catalog.db": "what exists: runs, evals, scores, items; small, read on every page",
        "runs/<run_id>.db": "one ingested lens: cells, readout text, judge calls, verdicts",
        "user.db": "bookmarks and notes; never touched by ingest",
        "lens_aliases.json": "lens id -> {label, description, default}: the short names the "
        "pages show, and which lenses a page shows before any are chosen. "
        "Edit it by hand; ingest only creates it when missing",
    },
    "catalog.db": {
        "run": "one ingested lens on one bench and subject model (one per named run when the "
        "ingest gives a run name); `method` is olens | nla | jlens | logit_lens | "
        "continuation | other, `source` the judged directory or its volume address, "
        "`source_sig` its size+mtime signature (ingest skips a run whose signature is "
        "unchanged)",
        "run_facts": "what the runs manifest says about a run, one row per run ingested from a "
        "manifest: run name, set (full | fast | ...), bench commit, engine, cells read, "
        "read GPU-hours and wall-clock, judge wall-clock, calls and cost (US dollars, list "
        "prices), total cost and wall-clock (NULL = not in the run's result files), "
        "`integrity` ('' = clean, partial, provisional) with its reason, `readouts` (where "
        "the readout files are), `headline` (JSON: the scores read straight from the run's "
        "result files at ingest, what `viewer check` compares the store with) and `entry` "
        "(the manifest entry, JSON)",
        "run_set": "which score sets a run has (full | core | fast | ati; `fast` is the "
        "current fast subset, a set scored on an earlier fast subset is named after that "
        "subset, `fast-safety` is the retired variant with the two safety evals) and "
        "whether a set was judged as such (`derived` = 0) or derived from the full run "
        "(`derived` = 1), with `origin` (the derived run or rule) and a note (for a fast set: "
        "the subset its results are stamped with)",
        "run_eval": "per run and eval, the integrity of the score: '' = clean, incomplete, "
        "provisional, partial, with the reason and the counters it was read from (JSON)",
        "hb_index": "HallucinationBench index rows as the run's index.json has them: one row "
        "per layer (-2 = the joint row over all layers) and key, `kind` = family (an index "
        "family's value) or macro (a macro column of the index row)",
        "eval": "one eval per (bench, model): title, group, what it tests, one example, how it "
        "is judged, the judge prompt template, gate ids (JSON list), n_items, metric; "
        "`readme` holds a short note for evals a default run leaves out (superseded)",
        "item": "one question: prompt, expected answers (JSON list), intermediates (JSON "
        "list), `private` = 1 for items that must not be published",
        "item_tokens": "optional: the full rendered prompt's tokens per question (zlib JSON "
        "list), written by `ingest adapter=tokens` when the subject tokenizer is available",
        "subset_item": "membership of an item in a named subset (fast, fast-<version>, ati)",
        "score": "one number: run x eval x subset x layer (-1 = the eval's headline) x kind "
        "(lens | prompt_only | lucky_guess | chance), with its 95% CI and n; eval "
        "`_macro` is the mean over evals",
        "verdict": "per run and item: pass (1 / 0 / NULL = undecided) and a numeric score; "
        "a compact copy of the run db's verdicts for cross-run filters",
        "layer_stat": "per run, eval and layer: hits / n for one `kind`: `judge` (an exact "
        "per-layer verdict), `expected` (share of items whose readouts at the layer "
        "contain the expected answer; a proxy), `cited` (share of items whose "
        "judge quote sits at the layer; a proxy), `hb` (HallucinationBench rate)",
    },
    "runs/<run_id>.db": {
        "source": "the readout files the cells came from: a local path, or an address on a "
        "volume (modal://<volume>[@<environment>]/<path>) that is fetched into the local "
        "cache when a page first needs it",
        "readout_file": "per eval, the `source` rows that hold its readouts when the cells "
        "were not indexed at ingest: the page reads a question's cells from those files on "
        "demand",
        "cell": "one read cell (eval, item, layer, pos): the token read, sample count, flags "
        "(1 = a sample contains an expected answer, 2 = contains the judge's quote, "
        "4 = cited by the digest) and the byte span of its line in `source`",
        "readout": "FTS5 table, rowid = cell.id: the cell's samples joined by U+001E. Cells "
        "without a row here are read from `source` by byte span on demand",
        "judgment": "one cached judge or digest call from cells.jsonl: `stage` (digest | judge "
        "| the family's own tag), the raw key, `result` (the model's JSON output, zlib JSON) and "
        "`meta` (what the judge code stored beside it: options, gold position, ...)",
        "verdict": "the rows of results.json, one per row (`row` = its index for the item): "
        "pass, score and the full row minus the digest text in `detail` (zlib JSON)",
        "digest": "summary mode: the digest text the judge read for the question (zlib)",
        "target": "per question, what the string flags looked for: expected-answer terms and "
        "the judge's quotes (JSON lists)",
        "hb_segment": "HallucinationBench claim-map segments: character span in one sample, "
        "leaf, index weight, the judge's why, its supporting / contradicting quote "
        "and the cverify checks",
    },
    "user.db": {"bookmark": "a bookmarked question, optionally a cell (run, layer, pos), + note"},
}


def root(store: str | os.PathLike | None = None) -> Path:
    """The store directory: the argument, else ``$WSB_VIEWER_STORE``, else the default."""
    return Path(store or os.environ.get(STORE_ENV) or DEFAULT_STORE)


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")


def run_id(bench: str, model: str, lens: str, run: str | None = None) -> str:
    """One store run per lens, or per named run of a lens when ``run`` is given."""
    rid = f"{slug(bench)}__{slug(model)}__{slug(lens)}"
    return f"{rid}__{slug(run)}" if run else rid


def connect(path: Path, ddl: str | None = None, readonly: bool = False) -> sqlite3.Connection:
    """A connection with dict-like rows; ``ddl`` creates missing tables."""
    if readonly:
        con = sqlite3.connect(
            f"file:{path}?mode=ro", uri=True, check_same_thread=False, timeout=BUSY_SECONDS
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, check_same_thread=False, timeout=BUSY_SECONDS)
    con.row_factory = sqlite3.Row
    if ddl:
        con.executescript(ddl)
    return con


def catalog(store: Path, readonly: bool = False) -> sqlite3.Connection:
    """The catalog. Opened for writing, a store written by an earlier version is brought up
    to date first (missing tables and columns are added; nothing is dropped)."""
    if not readonly:
        write_manifest(store)
        if not (store / ALIASES).exists():
            (store / ALIASES).write_text("{}\n", encoding="utf-8")  # filled in by hand
    con = connect(store / "catalog.db", None if readonly else CATALOG_DDL, readonly)
    if not readonly:
        migrate(con, CATALOG_DDL)
    return con


def migrate(con: sqlite3.Connection, ddl: str) -> list[str]:
    """Add the columns ``ddl`` declares that an existing table lacks (``CREATE TABLE IF NOT
    EXISTS`` already added the missing tables). Returns ``table.column`` for each one added."""
    added = []
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", ddl, re.S):
        have = {r[1] for r in con.execute(f"PRAGMA table_info({name})")}
        for part in re.split(r",(?![^()]*\))", body):
            words = part.split()
            if not words or words[0] in ("PRIMARY", "UNIQUE", "FOREIGN", "CHECK"):
                continue
            if words[0] not in have:
                con.execute(f"ALTER TABLE {name} ADD COLUMN {' '.join(words)}")
                added.append(f"{name}.{words[0]}")
    if added:
        con.commit()
    return added


def has_table(con: sqlite3.Connection, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
    )


def aliases(store: Path) -> dict[str, dict[str, str]]:
    """``{lens id: {label, description}}`` from the store's alias file ({} when unreadable)."""
    try:
        raw = json.loads((store / ALIASES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("label")}


def run_db_path(store: Path, rid: str) -> Path:
    return store / "runs" / f"{rid}.db"


def user(store: Path) -> sqlite3.Connection:
    return connect(store / "user.db", USER_DDL)


def write_manifest(store: Path) -> Path:
    store.mkdir(parents=True, exist_ok=True)
    path = store / "manifest.json"
    text = json.dumps(MANIFEST, indent=1)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
    return path


@contextmanager
def building(final: Path, build_dir: Path | None) -> Iterator[Path]:
    """Build a database file away from ``final`` (a local disk is much faster than a network
    volume), then move it into place; an exception leaves ``final`` untouched."""
    tmp_root = build_dir or final.parent
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp = tmp_root / f"{final.name}.building"
    tmp.unlink(missing_ok=True)
    yield tmp
    final.parent.mkdir(parents=True, exist_ok=True)
    if tmp.parent == final.parent:
        tmp.replace(final)
    else:
        import shutil

        shutil.copyfile(tmp, final.with_suffix(".copying"))
        final.with_suffix(".copying").replace(final)
        tmp.unlink()


def signature(paths: Iterable[Path]) -> str:
    """Size and mtime of every file, as one string: the 'unchanged source' check."""
    parts = []
    for p in sorted(paths):
        if p.is_file():
            s = p.stat()
            parts.append(f"{p.name}:{s.st_size}:{int(s.st_mtime)}")
    return "|".join(parts)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text: str | None, default: Any = None) -> Any:
    return default if text is None or text == "" else json.loads(text)


def pack(obj: Any) -> bytes:
    """JSON, zlib-compressed: the large judge payloads (digests, result rows)."""
    return zlib.compress(dumps(obj).encode("utf-8"), 6)


def unpack(blob: bytes | str | None, default: Any = None) -> Any:
    if blob is None:
        return default
    if isinstance(blob, str):
        return loads(blob, default)
    return json.loads(zlib.decompress(blob).decode("utf-8"))


def now() -> float:
    return time.time()
