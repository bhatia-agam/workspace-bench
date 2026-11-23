"""Read side of the store: every question the app asks, as plain dicts and lists. No HTML
here, and no writes except bookmarks (``user.db``)."""

import json
import re
import sqlite3
import threading
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any

from wsbench import registry
from wsbench.viewer import gates, meta, remote, store
from wsbench.viewer.ingest import common

MACRO = "_macro"
BENCH_TITLES = {"wsb": "WorkspaceBench", "hb": "HallucinationBench"}
CORE = "core"  # the default tier: shown from the full run's rows, never stored
FAST = "fast"  # the current fast subset (``wsbench.fast.DEFAULT``)
FAST_SAFETY = "fast-safety"  # the retired safety variant: shown where a store holds it
SUBSET_TITLES = {  # the sets, in the order the page lists them
    CORE: "Core",
    "full": "Full",
    FAST: "Fast",
    FAST_SAFETY: "Fast with safety (an earlier fast subset)",
    "ati": "Anti-text-inversion",
}
OLD_FAST = "fast-"  # a fast run of another version than the default is stored under its name
# the view of rows a store holds under ``fast`` that were scored on an earlier fast subset (the
# store was written while that subset was the default one); never a stored name
EARLIER_FAST = "fast-earlier"
SCORED_ON = re.compile(r"\bscored on (fast[\w.-]*)")  # what ingest notes on a fast set
FAST_STAMP = re.compile(r"\bfast(?:-safety)?-v\d+\b")  # a subset version named in a stored note


def is_earlier_fast(subset: str) -> bool:
    """A set scored on another selection of fast questions than the current fast subset."""
    return subset != FAST and (subset == FAST_SAFETY or subset.startswith(OLD_FAST))


def ordered(have: set[str] | dict[str, Any]) -> list[str]:
    """Sets in the order the pages list them: the titled ones in their order, with every set
    of an earlier fast subset (by name) right after the current fast subset."""
    other = sorted(set(have) - set(SUBSET_TITLES))
    out: list[str] = []
    for name in SUBSET_TITLES:
        out += [name] if name in have else []
        out += other if name == FAST else []
    return out


def subset_title(subset: str, n_evals: int | None = None) -> str:
    """The title of a set. The current fast subset is plain "Fast"; a set scored on an earlier
    fast subset says so, with its number of evals where the caller knows it: one stored under
    the version it was judged on is named by that version, the retired safety variant keeps
    its own title, and rows a store still holds under ``fast`` from an earlier subset are the
    "earlier fast subset"."""
    size = f"{n_evals} eval{'' if n_evals == 1 else 's'}" if n_evals else ""
    if subset == FAST_SAFETY:
        return SUBSET_TITLES[subset][:-1] + (f", {size})" if size else ")")
    if subset in SUBSET_TITLES:
        return SUBSET_TITLES[subset]
    if subset == EARLIER_FAST:
        return "Earlier fast subset" + (f" ({size})" if size else "")
    if subset.startswith(OLD_FAST):
        return f"Fast subset ({subset}, an earlier fast subset{' of ' + size if size else ''})"
    return f"Subset {subset}"


WHOLE_BANK = ("full", CORE)  # subsets that keep every question of the evals they hold
METHOD_ORDER = {m: n for n, m in enumerate(meta.METHODS)}
METHOD_TITLES = {m: v[0] for m, v in meta.METHODS.items()}
SNIPPET = 110
DERIVED = "derived from the full run"
# a run ingested before the store recorded its sets says it in the macro's note instead
DERIVED_NOTE = re.compile(r"\bderived\b|full-run verdicts", re.I)
OTHER_CATEGORY = "other"
OTHER_TITLE = "Other"
SCORED_BY_RULE = "rule (regex)"
SCORED_BY_JUDGE = "Claude judge"
SCORED_BY_PROBE = "Claude judge and a probe"
# HallucinationBench families whose label is settled by a probe on the activations after the
# judge (meta.HB_EVALS: "... then a commitment judge, then a distractor-rank probe")
HB_PROBE_FAMILIES = ("sibling",)


def category_title(key: str) -> str:
    """A category's short title, as the README's table of evals writes it: the registry's title
    without its parenthesis."""
    title = registry.CATEGORIES.get(key)
    return re.sub(r"\s*\(.*\)$", "", title) if title else OTHER_TITLE


def _spec(name: str) -> Any:
    registry.load_all()
    return registry.FAMILIES.get(registry.canonical(name))


def category_of(bench: str, name: str) -> str:
    """The registry category of a WorkspaceBench eval, read now rather than at ingest."""
    spec = _spec(name) if bench == "wsb" else None
    return spec.group if spec is not None and spec.group in registry.CATEGORIES else OTHER_CATEGORY


def scored_by(bench: str, name: str) -> str:
    """'rule (regex)' for an eval whose registry entry has a deterministic scorer of record,
    'Claude judge' for every other registered eval and for HallucinationBench (its sibling
    family: 'Claude judge and a probe'), '' when the registry does not know the eval."""
    if bench == "hb":
        return SCORED_BY_PROBE if name in HB_PROBE_FAMILIES else SCORED_BY_JUDGE
    spec = _spec(name) if bench == "wsb" else None
    if spec is None:
        return ""
    return SCORED_BY_RULE if spec.scorer else SCORED_BY_JUDGE


class Store:
    """One opened store. Connections are shared across request threads behind a lock."""

    def __init__(self, root: Path, private: bool = False) -> None:
        self.root = root
        self.private = private
        self.lock = threading.RLock()
        self.cat = store.catalog(root, readonly=True)
        self.user = store.user(root)
        self._runs: dict[str, sqlite3.Connection] = {}
        self._alias_cache: dict[str, dict[str, str]] = {}
        self._alias_stamp = 0.0
        self._counts: dict[str, tuple[float, tuple[int, int]]] = {}

    # ------------------------------------------------------------ plumbing

    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.cat.execute(sql, args).fetchall()

    def run_con(self, rid: str) -> sqlite3.Connection | None:
        with self.lock:
            if rid not in self._runs:
                path = store.run_db_path(self.root, rid)
                if not path.exists():
                    return None
                self._runs[rid] = store.connect(path, readonly=True)
            return self._runs[rid]

    def _core(self, bench: str) -> set[str]:
        """The core tier's evals; empty for a bench that has no tiers."""
        if bench != "wsb":
            return set()
        from wsbench import tiers

        return set(tiers.CORE)

    # ------------------------------------------------------------ which fast subset
    # The store names a set by the fast subset it was scored on: `fast` is the current one,
    # an earlier one has its own name. A store written while an earlier subset was the
    # current one still holds that subset's rows under `fast`; they are told apart here, at
    # read time, and shown as the set `EARLIER_FAST`. Nothing is rewritten.

    @staticmethod
    def _stored(subset: str) -> str:
        """The stored name of the rows a set is shown from."""
        return "full" if subset == CORE else FAST if subset == EARLIER_FAST else subset

    def _in_set(self, bench: str, model: str, subset: str):
        """Whether a run's rows under ``_stored(subset)`` belong to the set ``subset``."""
        if subset not in (FAST, EARLIER_FAST):
            return lambda rid: True
        earlier = self._earlier_fast(bench, model)
        return (
            (lambda rid: rid in earlier)
            if subset == EARLIER_FAST
            else (lambda rid: rid not in earlier)
        )

    def _fast_runs(self, bench: str, model: str) -> set[str]:
        rows = self.q(
            "SELECT DISTINCT s.run_id FROM score s JOIN run r USING (run_id) WHERE r.bench = ?"
            " AND r.model = ? AND s.subset = ?",
            (bench, model, FAST),
        )
        return {r["run_id"] for r in rows}

    @staticmethod
    def _current_fast() -> dict[str, int] | None:
        """``{eval: questions}`` of the current fast subset, read from ``wsbench.fast`` now;
        None when its frozen file cannot be read."""
        from wsbench import fast

        try:
            sub = fast.subset(fast.DEFAULT)
        except (SystemExit, OSError, KeyError, ValueError):
            return None
        return {
            fam: len(
                {u for us in (e.get("units") or {}).values() for u in us}
                | set(e.get("read_ids") or [])
            )
            for fam, e in sub.items()
        }

    @staticmethod
    def _is_current_stamp(stamp: str, evals: set[str]) -> bool:
        """Is a row set stamped with fast subset ``stamp`` the current subset's: the current
        version itself, or one that holds the identical entry for every eval of the set."""
        from wsbench import fast

        if stamp == fast.DEFAULT:
            return True
        try:
            return bool(evals) and all(
                fast.compatible(stamp, ev, against=fast.DEFAULT) for ev in evals
            )
        except (SystemExit, OSError, KeyError, ValueError):
            return False

    def _fast_membership(self, bench: str, model: str) -> dict[str, int]:
        rows = self.q(
            "SELECT eval, count(*) n FROM subset_item WHERE bench = ? AND model = ? AND subset = ?"
            " GROUP BY eval",
            (bench, model, FAST),
        )
        return {r["eval"]: r["n"] for r in rows}

    def _membership_is_current(self, bench: str, model: str) -> bool:
        """Is the question list the store keeps under ``fast`` the current fast subset's."""
        current = self._current_fast()
        return current is not None and self._fast_membership(bench, model) == current

    def _earlier_fast(self, bench: str, model: str) -> set[str]:
        """The runs whose rows under ``fast`` were scored on an EARLIER fast subset. A run's
        stamp decides where the store has one (the subset version named in its set's note or
        in its macro's note); without a stamp, the run is on an earlier subset
        when it scores an eval the current subset does not hold, or when the store's question
        list of one of its evals is not the current subset's."""
        if bench != "wsb":
            return set()
        evals: dict[str, set[str]] = defaultdict(set)
        notes: dict[str, list[str]] = defaultdict(list)  # the macro's note
        said: dict[str, list[str]] = defaultdict(list)  # the set's note
        for r in self.q(
            "SELECT s.run_id, s.eval, s.note FROM score s JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND s.subset = ? AND s.kind = 'lens'"
            " AND s.layer = -1",
            (bench, model, FAST),
        ):
            if r["eval"] == MACRO:
                notes[r["run_id"]].append(r["note"] or "")
            else:
                evals[r["run_id"]].add(r["eval"])
        for r in self._opt(
            "SELECT t.run_id, t.origin, t.note FROM run_set t JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND t.subset = ?",
            (bench, model, FAST),
        ):
            said[r["run_id"]].append(r["note"] or "")
        current = self._current_fast()
        stored = self._fast_membership(bench, model) if current is not None else {}
        out = set()
        for rid in set(evals) | set(notes) | set(said):
            # ingest's own words first ("scored on <subset>"), then any subset a note names
            stamps = [m.group(1) for text in said[rid] if (m := SCORED_ON.search(text))]
            stamps += [
                m.group(0) for text in notes[rid] + said[rid] if (m := FAST_STAMP.search(text))
            ]
            if stamps:
                if not self._is_current_stamp(stamps[0], evals[rid]):
                    out.add(rid)
            elif current is not None and any(
                ev not in current or stored.get(ev, current[ev]) != current[ev] for ev in evals[rid]
            ):
                out.add(rid)
        return out

    def set_sizes(self, bench: str, model: str) -> dict[str, int]:
        """``{set: evals with a headline score in it}`` over the runs of a model, by the set
        names ``subsets`` lists (core: as stored)."""
        earlier = self._earlier_fast(bench, model)
        evals: dict[str, set[str]] = defaultdict(set)
        for r in self.q(
            "SELECT s.run_id, s.subset, s.eval FROM score s JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND s.kind = 'lens' AND s.layer = -1"
            " AND s.eval != ?",
            (bench, model, MACRO),
        ):
            name = EARLIER_FAST if r["subset"] == FAST and r["run_id"] in earlier else r["subset"]
            evals[name].add(r["eval"])
        return {k: len(v) for k, v in evals.items()}

    def title(self, bench: str, model: str, subset: str) -> str:
        """A set's title on a page: ``subset_title`` with the evals an earlier fast subset
        has scores for in this store."""
        n = self.set_sizes(bench, model).get(subset) if is_earlier_fast(subset) else None
        return subset_title(subset, n)

    def rq(self, rid: str, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        con = self.run_con(rid)
        if con is None:
            return []
        with self.lock:
            return con.execute(sql, args).fetchall()

    def _opt(self, sql: str, args: tuple = (), rid: str | None = None) -> list[sqlite3.Row]:
        """A query on a table that a store written by an earlier version lacks: [] then."""
        try:
            return self.rq(rid, sql, args) if rid else self.q(sql, args)
        except sqlite3.OperationalError:
            return []

    # ------------------------------------------------------------ catalog

    def benches(self) -> list[str]:
        have = {r["bench"] for r in self.q("SELECT DISTINCT bench FROM eval")}
        return [b for b in BENCH_TITLES if b in have] + sorted(have - set(BENCH_TITLES))

    def models(self, bench: str) -> list[dict]:
        """Subject models with a question set, those with ingested runs first."""
        runs = {
            r["model"]: r["n"]
            for r in self.q(
                "SELECT model, count(*) n FROM run WHERE bench = ? GROUP BY 1", (bench,)
            )
        }
        rows = self.q(
            "SELECT model, count(*) n_evals, sum(n_items) n_items FROM eval WHERE bench = ?"
            " GROUP BY model",
            (bench,),
        )
        out = [dict(r) | {"n_runs": runs.get(r["model"], 0)} for r in rows]
        return sorted(out, key=lambda m: (-m["n_runs"], m["model"]))

    def runs(self, bench: str, model: str) -> list[dict]:
        rows = self.q("SELECT * FROM run WHERE bench = ? AND model = ?", (bench, model))
        out = [self._named(dict(r) | {"meta": store.loads(r["meta"], {})}) for r in rows]
        rank = {lens: n for n, lens in enumerate(self._aliases())}  # the alias file's order
        return sorted(
            out,
            key=lambda r: (
                METHOD_ORDER.get(r["method"], 9),
                rank.get(r["lens"], 10**6),
                r["label"],
            ),
        )

    def run(self, rid: str) -> dict | None:
        rows = self.q("SELECT * FROM run WHERE run_id = ?", (rid,))
        if not rows:
            return None
        return self._named(dict(rows[0]) | {"meta": store.loads(rows[0]["meta"], {})})

    def _named(self, run: dict) -> dict:
        """The run with its display name: the alias file's label, else the label given at
        ingest, else the lens id with the store's common prefixes removed."""
        alias = self._aliases().get(run["lens"]) or {}
        label = alias.get("label") or run["label"]
        marks = self._integrity()
        if run["run_id"] in marks:
            label = run["label"]  # one of several runs of a lens: the manifest's own label
        mark, reason = marks.get(run["run_id"], ("", ""))
        return run | {
            "integrity": mark,  # '' = clean, or not a manifest run
            "integrity_reason": reason,
            "manifest": run["run_id"] in marks,
            "label": label,
            "description": alias.get("description") or "",
            "default": bool(alias.get("default")),  # shown when the page names no lenses
        }

    def _integrity(self) -> dict[str, tuple[str, str]]:
        """``{run_id: (integrity label, reason)}`` of the runs the manifest lists."""
        return {
            r["run_id"]: (r["integrity"] or "", r["integrity_reason"] or "")
            for r in self._opt("SELECT run_id, integrity, integrity_reason FROM run_facts")
        }

    def _manifest_runs(self) -> set[str]:
        return set(self._integrity())

    # ------------------------------------------------------------ runs: facts, sets, integrity

    def run_facts(self, rid: str) -> dict | None:
        """What the runs manifest says about one run (``run_facts``): run name, set, bench
        commit, engine, cells, timings and costs (None = not in the run's result files),
        ``integrity`` ('' = clean) with ``integrity_reason``, ``readouts`` (where the readout
        files are), ``headline`` (the result files' own scores) and ``entry`` (the manifest
        entry). None for a run that was not ingested from a manifest."""
        rows = self._opt("SELECT * FROM run_facts WHERE run_id = ?", (rid,))
        if not rows:
            return None
        out = dict(rows[0])
        out["headline"] = store.loads(out["headline"], {})
        out["entry"] = store.loads(out["entry"], {})
        out["timing_note"] = out["entry"].get("timing_note") or ""
        return out

    def run_sets(self, rid: str) -> list[dict]:
        """The score sets a run has, in the dropdown's order: ``subset`` (the name the pages
        use: rows stored under ``fast`` from an earlier fast subset are ``EARLIER_FAST``),
        ``title``, ``derived`` (True = derived from the full run, not judged as that set),
        ``origin``, ``note``, and the set's macro (``macro``, ``n_evals``) where it has one. A
        run from before the table existed lists the sets its scores have, with ``derived``
        None."""
        known = {r["subset"]: dict(r) for r in self._opt(
            "SELECT * FROM run_set WHERE run_id = ?", (rid,))}  # fmt: skip
        macros = {
            r["subset"]: r
            for r in self.q(
                "SELECT subset, value, n FROM score WHERE run_id = ? AND eval = ? AND layer = -1"
                " AND kind = 'lens'",
                (rid, MACRO),
            )
        }
        have = {
            r["subset"]: r["n"]
            for r in self.q(
                "SELECT subset, count(DISTINCT CASE WHEN eval != ? THEN eval END) n FROM score"
                " WHERE run_id = ? AND kind = 'lens' GROUP BY 1",
                (MACRO, rid),
            )
        }
        run = self.q("SELECT bench, model FROM run WHERE run_id = ?", (rid,))
        old = bool(run) and FAST in have and rid in self._earlier_fast(*run[0])
        out = []
        for subset in ordered(have):
            k = known.get(subset) or {}
            m = macros.get(subset)
            # the name the pages know the set by: rows under `fast` from an earlier subset
            shown = EARLIER_FAST if old and subset == FAST else subset
            out.append({
                "subset": shown,
                "title": subset_title(shown, have[subset] if is_earlier_fast(shown) else None),
                "derived": bool(k["derived"]) if k else None, "origin": k.get("origin"),
                "note": k.get("note") or "", "macro": m["value"] if m else None,
                "n_evals": m["n"] if m else None,
            })  # fmt: skip
        return out

    def run_evals(self, rid: str) -> dict[str, dict]:
        """``{eval: {integrity, reason, facts}}`` per eval of a run: '' = clean, else
        incomplete / provisional / partial with the reason and the counters behind it."""
        return {
            r["eval"]: {"integrity": r["integrity"], "reason": r["reason"],
                        "facts": store.loads(r["facts"], {})}
            for r in self._opt("SELECT * FROM run_eval WHERE run_id = ?", (rid,))
        }  # fmt: skip

    def runs_table(self, bench: str | None = None, model: str | None = None) -> list[dict]:
        """Every run with what a runs page shows: the run row (label, method, lens, judge,
        ingested_at), ``facts`` (``run_facts`` or None), ``sets`` (``run_sets``), the count of
        evals with a headline score and of evals that are not clean, and ``readouts`` (where
        the readouts are and whether they can be read here)."""
        sql, args = "SELECT * FROM run", []
        where = [(k, v) for k, v in (("bench", bench), ("model", model)) if v]
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k, _v in where)
            args = [v for _k, v in where]
        out = []
        for r in self.q(sql, tuple(args)):
            run = self._named(dict(r) | {"meta": store.loads(r["meta"], {})})
            rid = run["run_id"]
            evals = self.run_evals(rid)
            n = self.q(
                "SELECT count(DISTINCT eval) n FROM score WHERE run_id = ? AND layer = -1 AND"
                " kind = 'lens' AND eval != ?",
                (rid, MACRO),
            )[0]["n"]
            out.append(run | {
                "facts": self.run_facts(rid), "sets": self.run_sets(rid), "n_evals": n,
                "n_not_clean": sum(1 for e in evals.values() if e["integrity"]),
                "readouts": self.readout_sources(rid),
            })  # fmt: skip
        return sorted(
            out,
            key=lambda r: (r["bench"], r["model"], METHOD_ORDER.get(r["method"], 9), r["label"]),
        )

    def hb_index(self, rid: str) -> list[dict]:
        """The run's HallucinationBench index rows as its index.json has them: ``layer``
        (``store.JOINT_LAYER`` = the joint row over all layers), ``key`` (a family or a macro
        column), ``kind`` (family | macro), ``value``, ``ci_lo``, ``ci_hi``, ``n``,
        ``n_items``."""
        return [dict(r) for r in self._opt(
            "SELECT layer, key, kind, value, ci_lo, ci_hi, n, n_items FROM hb_index"
            " WHERE run_id = ? ORDER BY layer, kind, key", (rid,))]  # fmt: skip

    def readout_sources(self, rid: str) -> dict[str, Any]:
        """Where a run's readout text is: ``files`` (each ``path``, ``size``, ``state`` =
        local | cached | on a volume | missing), ``n_cells``, ``n_with_text`` (cells whose text
        is in the store itself) and ``missing`` (files that are gone from this machine and are
        on no volume: their cells show the 'not available' marker)."""
        files = []
        for s in self._opt("SELECT path, size FROM source ORDER BY src", rid=rid):
            ok, how = remote.exists(s["path"])
            files.append({"path": s["path"], "size": s["size"], "state": how, "readable": ok})
        n_cells, n_text = self._text_counts(rid)
        return {
            "files": files,
            "n_cells": n_cells,
            "n_with_text": n_text,
            "missing": [f["path"] for f in files if f["state"] == "missing"],
        }

    def _text_counts(self, rid: str) -> tuple[int, int]:
        """``(cells, cells whose text is in the store)`` of a run. Counting the text table of a
        large run takes a tenth of a second, so the pair is kept until the run's database
        file changes."""
        path = store.run_db_path(self.root, rid)
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return 0, 0
        hit = self._counts.get(rid)
        if hit is None or hit[0] != stamp:
            rows = self._opt(
                "SELECT count(*) n, (SELECT count(*) FROM readout) t FROM cell", rid=rid
            )
            hit = (stamp, (rows[0]["n"], rows[0]["t"]) if rows else (0, 0))
            self._counts[rid] = hit
        return hit[1]

    def missing_sources(self) -> list[dict]:
        """Runs whose readout files are gone (a local path that no longer exists): ``run_id``,
        ``label``, ``missing`` (paths), ``n_cells`` and ``n_without_text`` (cells that now show
        the 'not available' marker)."""
        out = []
        for r in self.q("SELECT run_id, label FROM run ORDER BY run_id"):
            src = self.readout_sources(r["run_id"])
            if src["missing"]:
                out.append({
                    "run_id": r["run_id"], "label": r["label"], "missing": src["missing"],
                    "n_cells": src["n_cells"],
                    "n_without_text": src["n_cells"] - src["n_with_text"],
                })  # fmt: skip
        return out

    def _aliases(self) -> dict[str, dict[str, str]]:
        path = self.root / store.ALIASES
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return {}
        if stamp != self._alias_stamp:
            self._alias_cache, self._alias_stamp = store.aliases(self.root), stamp
        return self._alias_cache

    def subsets(self, bench: str, model: str) -> list[str]:
        rows = self.q(
            "SELECT DISTINCT subset FROM score s JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ?",
            (bench, model),
        )
        have = {r["subset"] for r in rows}
        if self._core(bench) and any(
            e in self._core(bench) for e in self._full_evals(bench, model)
        ):
            have.add(CORE)
        if FAST in have:  # rows stored under `fast`: the current subset's, an earlier one's
            earlier = self._earlier_fast(bench, model)
            if earlier:
                have.add(EARLIER_FAST)
            if not self._fast_runs(bench, model) - earlier:
                have.discard(FAST)
        # a model with no scores at all still lists its question set, under the full set
        return ordered(have) or ["full"]

    def run_subsets(self, bench: str, model: str) -> dict[str, dict[str, int]]:
        """``{run_id: {set: evals with a headline score}}`` (the sets by the names ``subsets``
        lists; core as stored)."""
        earlier = self._earlier_fast(bench, model)
        out: dict[str, dict[str, int]] = defaultdict(dict)
        for r in self.q(
            "SELECT s.run_id, s.subset, count(*) n FROM score s JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND s.kind = 'lens' AND s.layer = -1"
            " AND s.eval != ? GROUP BY 1, 2",
            (bench, model, MACRO),
        ):
            old = r["subset"] == FAST and r["run_id"] in earlier
            out[r["run_id"]][EARLIER_FAST if old else r["subset"]] = r["n"]
        return dict(out)

    def derived_runs(self, bench: str, model: str, subset: str) -> dict[str, str]:
        """``{run_id: note}`` for the runs whose scores in this set were derived from their
        full run rather than judged as that set. The store's ``run_set`` rows decide (the note
        is theirs); a run without one is derived when the page computes its core rows from the
        full rows, or when its stored macro note says so."""
        out: dict[str, str] = {}
        known: set[str] = set()
        mine = self._in_set(bench, model, subset)
        for r in self._opt(
            "SELECT t.run_id, t.derived, t.origin, t.note FROM run_set t JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND t.subset = ?",
            (bench, model, FAST if subset == EARLIER_FAST else subset),
        ):
            if not mine(r["run_id"]):
                continue
            known.add(r["run_id"])
            if r["derived"]:
                out[r["run_id"]] = r["note"] or (f"from {r['origin']}" if r["origin"] else "")
        for r in self.q(
            "SELECT s.run_id, s.note FROM score s JOIN run r USING (run_id) WHERE r.bench = ?"
            " AND r.model = ? AND s.subset = ? AND s.kind = 'lens' AND s.layer = -1"
            " AND s.eval = ?",
            (bench, model, self._stored(subset), MACRO),
        ):
            if r["run_id"] in known or not mine(r["run_id"]):
                continue
            if subset == CORE:
                out[r["run_id"]] = "the core evals' rows of the full run"
            elif DERIVED_NOTE.search(r["note"] or ""):
                out[r["run_id"]] = r["note"]
        if subset == CORE:  # full runs without a macro row
            stored = set(self._stored_core(bench, model))
            for rid, sets in self.run_subsets(bench, model).items():
                if "full" in sets and rid not in known and rid not in stored:
                    out.setdefault(rid, "the core evals' rows of the full run")
        return out

    def eval_marks(self, bench: str, model: str) -> dict[str, dict[str, tuple[str, str]]]:
        """``{run_id: {eval: (integrity label, reason)}}`` for the evals a run's results mark
        as not clean (incomplete, provisional, partial)."""
        out: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        for r in self._opt(
            "SELECT e.run_id, e.eval, e.integrity, e.reason FROM run_eval e JOIN run r"
            " USING (run_id) WHERE r.bench = ? AND r.model = ? AND e.integrity != ''",
            (bench, model),
        ):
            out[r["run_id"]][r["eval"]] = (r["integrity"], r["reason"] or "")
        return dict(out)

    def _stored_core(self, bench: str, model: str) -> dict[str, list[sqlite3.Row]]:
        """The core rows ingest stored, per run (a run ingested earlier has none)."""
        out: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in self.q(
            "SELECT s.* FROM score s JOIN run r USING (run_id) WHERE r.bench = ? AND r.model = ?"
            " AND s.subset = ? AND s.layer = -1 AND s.kind = 'lens'",
            (bench, model, CORE),
        ):
            out[r["run_id"]].append(r)
        return dict(out)

    def _own_core(self, bench: str, model: str) -> set[str]:
        """The runs that name their own core list (a families file in their manifest entry)."""
        rows = self._opt(
            "SELECT f.run_id, f.entry FROM run_facts f JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ?",
            (bench, model),
        )
        return {r["run_id"] for r in rows if store.loads(r["entry"], {}).get("families_file")}

    def _full_evals(self, bench: str, model: str) -> set[str]:
        rows = self.q(
            "SELECT DISTINCT s.eval FROM score s JOIN run r USING (run_id)"
            " WHERE r.bench = ? AND r.model = ? AND s.subset = 'full' AND s.kind = 'lens'",
            (bench, model),
        )
        return {r["eval"] for r in rows}

    def evals(self, bench: str, model: str) -> list[dict]:
        rows = self.q(
            "SELECT * FROM eval WHERE bench = ? AND model = ? ORDER BY ord", (bench, model)
        )
        out = []
        for r in rows:
            cat = category_of(bench, r["eval"])
            out.append(
                dict(r)
                | {
                    "gates": store.loads(r["gates"], []),
                    "category": cat,
                    # WorkspaceBench: the registry's category now; any other bench: as stored
                    "grp": category_title(cat) if bench == "wsb" else r["grp"],
                    "scored_by": scored_by(bench, r["eval"]),
                }
            )
        return out

    def eval(self, bench: str, model: str, name: str) -> dict | None:
        return next((e for e in self.evals(bench, model) if e["eval"] == name), None)

    def groups(self, bench: str, model: str) -> list[dict]:
        """The evals by category: ``[{key, title, evals}]``. WorkspaceBench follows the
        registry's categories in their order, each eval once, under its own category; another
        bench keeps the groups it was stored with."""
        evs = self.evals(bench, model)
        out: dict[str, dict] = {}
        if bench != "wsb":
            for e in evs:
                title = e["grp"] or OTHER_TITLE
                out.setdefault(title, {"key": title, "title": title, "evals": []})
                out[title]["evals"].append(e)
            return list(out.values())
        for key in (*registry.CATEGORIES, OTHER_CATEGORY):
            members = [e for e in evs if e["category"] == key]
            if members:
                out[key] = {"key": key, "title": category_title(key), "evals": members}
        return list(out.values())

    def scores(self, bench: str, model: str, subset: str) -> dict[str, dict[str, dict]]:
        """``{eval: {run_id | floor kind: score}}`` at the headline layer for one subset. Floors
        (prompt_only, lucky_guess, chance) are per eval, taken from any run that carries them.
        The core set (``wsbench.tiers.CORE``, read now): a run's stored core rows and core macro
        where ingest stored them for today's core list (or for the list the run named itself),
        else the core evals' rows of its full run with their mean as the macro."""
        rows = self.q(
            "SELECT s.* FROM score s JOIN run r USING (run_id) WHERE r.bench = ? AND r.model = ?"
            " AND s.subset = ? AND s.layer = -1",
            (bench, model, self._stored(subset)),
        )
        mine = self._in_set(bench, model, subset)
        out: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            if not mine(r["run_id"]):
                continue
            key = r["run_id"] if r["kind"] == "lens" else r["kind"]
            if key not in out[r["eval"]] or r["kind"] == "lens":
                out[r["eval"]][key] = dict(r)
        if subset != CORE:
            return out
        names = self._core(bench)
        core = self._core_scores(out, names)
        own = self._own_core(bench, model)
        for rid, rows_ in self._stored_core(bench, model).items():
            today = {ev for ev in names if rid in out.get(ev, {})}
            if rid not in own and {r["eval"] for r in rows_} - {MACRO} != today:
                continue  # stored under an earlier core list: today's list, from the full rows
            for by_key in core.values():
                by_key.pop(rid, None)  # the stored set wins over the page's own derivation
            for r in rows_:
                core[r["eval"]][rid] = dict(r)
        return core

    @staticmethod
    def _core_scores(full: dict[str, dict[str, dict]], core: set[str]) -> dict:
        """The core tier of a full run: the core evals' rows as they are (a core eval is judged
        exactly as in a full run), and the core macro, the mean over the core rows a run has."""
        out: dict[str, dict[str, dict]] = defaultdict(dict)
        per_run: dict[str, list[float]] = defaultdict(list)
        for ev, by_key in full.items():
            if ev not in core:
                continue
            out[ev] = by_key
            for key, sc in by_key.items():
                if sc["kind"] == "lens" and sc["value"] is not None:
                    per_run[key].append(sc["value"])
        for rid, vals in per_run.items():
            out[MACRO][rid] = {
                "run_id": rid, "eval": MACRO, "subset": CORE, "layer": -1, "kind": "lens",
                "value": sum(vals) / len(vals), "ci_lo": None, "ci_hi": None, "n": len(vals),
                "note": f"core macro: the mean over {len(vals)} of {len(core)} core evals",
            }  # fmt: skip
        return out

    def layer_scores(self, bench: str, model: str, name: str, subset: str = "full") -> dict:
        """``{layer: {run_id: score}}`` for one eval: the stored per-layer score rows (the
        HallucinationBench index rows), without the headline."""
        rows = self.q(
            "SELECT s.* FROM score s JOIN run r USING (run_id) WHERE r.bench = ? AND r.model = ?"
            " AND s.eval = ? AND s.subset = ? AND s.kind = 'lens' AND s.layer >= 0"
            " ORDER BY s.layer",
            (bench, model, name, self._stored(subset)),
        )
        mine = self._in_set(bench, model, subset)
        out: dict[int, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            if mine(r["run_id"]):
                out[r["layer"]][r["run_id"]] = dict(r)
        return dict(out)

    def hb_leaves(self, rids: list[str] | None = None) -> set[str]:
        """The claim-map leaves the store's run databases hold (all runs, or ``rids``)."""
        ids = rids or [r["run_id"] for r in self.q("SELECT run_id FROM run")]
        out: set[str] = set()
        for rid in ids:
            try:
                out |= {r["leaf"] for r in self.rq(rid, "SELECT DISTINCT leaf FROM hb_segment")}
            except sqlite3.OperationalError:  # a run database without the table
                continue
        return out

    def _listed(self, bench: str, model: str, subset: str) -> bool:
        """Does the store hold the question list of this set. A whole-bank set has none; the
        list under ``fast`` is one subset's, so the other fast view (the earlier subset once
        the list was rewritten for the current one, or the reverse) has none either and
        shows every question of its evals."""
        if subset in WHOLE_BANK:
            return False
        if subset in (FAST, EARLIER_FAST) and bench == "wsb" and self._current_fast() is not None:
            return self._membership_is_current(bench, model) == (subset == FAST)
        return True

    def subset_counts(self, bench: str, model: str, subset: str) -> dict[str, int]:
        if not self._listed(bench, model, subset):
            return {}
        rows = self.q(
            "SELECT eval, count(*) n FROM subset_item WHERE bench = ? AND model = ? AND subset = ?"
            " GROUP BY eval",
            (bench, model, self._stored(subset)),
        )
        return {r["eval"]: r["n"] for r in rows}

    def layer_stats(self, bench: str, model: str, name: str | None = None) -> dict:
        """``{eval: {kind: {run_id: [(layer, rate, n)]}}}``."""
        sql = (
            "SELECT l.* FROM layer_stat l JOIN run r USING (run_id) WHERE r.bench = ? AND"
            " r.model = ? AND l.layer >= 0"
        )
        args: tuple = (bench, model)
        if name:
            sql, args = sql + " AND l.eval = ?", (*args, name)
        out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        for r in self.q(sql + " ORDER BY l.layer", args):
            if r["n"]:
                out[r["eval"]][r["kind"]][r["run_id"]].append(
                    (r["layer"], r["hits"] / r["n"], r["n"])
                )
        return out

    # ------------------------------------------------------------ items

    def visible(self, row: sqlite3.Row | dict) -> bool:
        return self.private or not row["private"]

    def items(self, bench: str, model: str, name: str, subset: str = "full") -> list[dict]:
        """The eval's questions in bank order with every run's verdict: ``pass`` per run id."""
        rows = self.q(
            "SELECT item, expected, intermediates, subfamily, private FROM item WHERE bench = ?"
            " AND model = ? AND eval = ? ORDER BY ord, item",
            (bench, model, name),
        )
        if self._listed(bench, model, subset):
            keep = {
                r["item"]
                for r in self.q(
                    "SELECT item FROM subset_item WHERE bench = ? AND model = ? AND subset = ?"
                    " AND eval = ?",
                    (bench, model, self._stored(subset), name),
                )
            }
            rows = [r for r in rows if r["item"] in keep]
        verdicts: dict[str, dict[str, dict]] = defaultdict(dict)
        for v in self.q(
            "SELECT v.* FROM verdict v JOIN run r USING (run_id) WHERE r.bench = ? AND r.model = ?"
            " AND v.eval = ?",
            (bench, model, name),
        ):
            verdicts[v["item"]][v["run_id"]] = {"pass": v["pass"], "score": v["score"]}
        out = []
        for r in rows:
            shown = self.visible(r)
            exp = list(
                dict.fromkeys(
                    str(x)
                    for x in store.loads(r["expected"], []) + store.loads(r["intermediates"], [])
                )
            )
            out.append(
                {
                    "item": r["item"],
                    "expected": exp[:3] if shown else [],
                    "subfamily": r["subfamily"],
                    "private": bool(r["private"]),
                    "runs": verdicts.get(r["item"], {}),
                }
            )
        return out

    def item(self, bench: str, model: str, name: str, item: str) -> dict | None:
        rows = self.q(
            "SELECT * FROM item WHERE bench = ? AND model = ? AND eval = ? AND item = ?",
            (bench, model, name, item),
        )
        if not rows:
            return None
        r = dict(rows[0])
        if not self.visible(r):
            return {"item": item, "private": True, "hidden": True}
        r["expected"] = store.loads(r["expected"], [])
        r["intermediates"] = store.loads(r["intermediates"], [])
        r["meta"] = store.loads(r["meta"], {})
        r["private"] = bool(r["private"])
        try:
            toks = self.q(
                "SELECT tokens FROM item_tokens WHERE bench = ? AND model = ? AND eval = ?"
                " AND item = ?",
                (bench, model, name, item),
            )
        except sqlite3.OperationalError:  # a store written before the table existed
            toks = []
        r["tokens"] = store.unpack(toks[0]["tokens"]) if toks else None
        return r

    def is_hidden(self, bench: str, model: str, name: str, item: str) -> bool:
        rows = self.q(
            "SELECT private FROM item WHERE bench = ? AND model = ? AND eval = ? AND item = ?",
            (bench, model, name, item),
        )
        return bool(rows and rows[0]["private"] and not self.private)

    # ------------------------------------------------------------ one question, one run

    def _texts(self, rid: str, cells: list[sqlite3.Row]) -> dict[int, list[str]]:
        ids = [c["id"] for c in cells]
        out: dict[int, list[str]] = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            marks = ",".join("?" * len(chunk))
            for r in self.rq(
                rid, f"SELECT rowid, text FROM readout WHERE rowid IN ({marks})", tuple(chunk)
            ):
                out[r["rowid"]] = r["text"].split(store.SAMPLE_SEP) if r["text"] else []
        missing = [c for c in cells if c["id"] not in out and c["src"] is not None]
        if missing:  # not copied at ingest: read the line from the source file
            paths = {r["src"]: r["path"] for r in self.rq(rid, "SELECT src, path FROM source")}
            local: dict[int, Path | str] = {}  # src -> the readable file, or why there is none
            for c in sorted(missing, key=lambda c: (c["src"], c["off"])):
                where = paths.get(c["src"], "an unrecorded file")
                if c["src"] not in local:
                    try:
                        local[c["src"]] = remote.local_file(where)
                    except remote.UnavailableError as e:
                        local[c["src"]] = str(e)
                if isinstance(local[c["src"]], str):
                    out[c["id"]] = [remote.marker(where, local[c["src"]])]
                    continue
                try:
                    with open(local[c["src"]], "rb") as fh:
                        fh.seek(c["off"])
                        rec = json.loads(fh.read(c["len"]))
                    out[c["id"]] = common.sample_texts(rec)
                except (OSError, ValueError, KeyError):
                    out[c["id"]] = [remote.marker(where, "the file changed since it was ingested")]
        return out

    def _remote_cells(self, rid: str, name: str, item: str) -> tuple[dict, dict, dict | None]:
        """The cells of a question whose readouts were not indexed at ingest, read now from the
        eval's readout files: ``(cells, tokens, readouts note)``. When the files cannot be had,
        one placeholder cell carries the 'not available' marker."""
        files = self._opt(
            "SELECT s.path FROM readout_file f JOIN source s USING (src) WHERE f.eval = ?"
            " ORDER BY s.src",
            (name,), rid,
        )  # fmt: skip
        if not files:
            return {}, {}, None
        paths = [f["path"] for f in files]
        where = paths[0] if len(paths) == 1 else f"{paths[0]} and {len(paths) - 1} more"
        try:
            rows = remote.item_rows(paths, item)
        except remote.UnavailableError as e:
            note = {"available": False, "where": where, "why": str(e),
                    "marker": remote.marker(where, str(e))}  # fmt: skip
            return {"0:0": {"s": [note["marker"]], "f": 0}}, {0: None}, note
        target = self.rq(
            rid, "SELECT terms, quotes FROM target WHERE eval = ? AND item = ?", (name, item)
        )
        pattern = common.term_pattern(store.loads(target[0]["terms"], [])) if target else None
        quotes = store.loads(target[0]["quotes"], []) if target else []
        cells: dict[str, dict] = {}
        tokens: dict[int, str | None] = {}
        for rec in rows:
            try:
                layer, pos = int(rec["layer"]), int(rec["pos"])
            except (KeyError, TypeError, ValueError):
                continue
            samples = common.sample_texts(rec)
            cells.setdefault(
                f"{layer}:{pos}", {"s": samples, "f": common.text_flags(samples, pattern, quotes)}
            )
            tokens.setdefault(pos, rec.get("token"))
        return cells, tokens, {"available": True, "where": where, "read": "on demand"}

    def cells(self, rid: str, name: str, item: str) -> dict[str, Any]:
        """Everything one run has on one question: all layers x positions with their samples,
        the judge calls, the verdict rows and (HB) the claim-map segments."""
        run = self.run(rid)
        if run is None:
            return {"error": "unknown run"}
        if self.is_hidden(run["bench"], run["model"], name, item):
            return {"run": rid, "private": True}
        cells = self.rq(
            rid,
            "SELECT * FROM cell WHERE eval = ? AND item = ? ORDER BY layer, pos",
            (name, item),
        )
        texts = self._texts(rid, cells)
        out_cells: dict[str, dict] = {}
        tokens: dict[int, str | None] = {}
        for c in cells:
            out_cells[f"{c['layer']}:{c['pos']}"] = {"s": texts.get(c["id"], []), "f": c["flags"]}
            tokens.setdefault(c["pos"], c["token"])
        readouts = None
        if not cells:  # not indexed at ingest: read from the eval's readout files now
            out_cells, tokens, readouts = self._remote_cells(rid, name, item)
        for s in self.rq(
            rid,
            "SELECT * FROM hb_segment WHERE eval = ? AND item = ?"
            " ORDER BY layer, pos, sample, start",
            (name, item),
        ):
            cell = out_cells.get(f"{s['layer']}:{s['pos']}")
            if cell is not None:
                cell.setdefault("g", []).append(
                    {
                        "i": s["sample"], "a": s["start"], "b": s["end"], "leaf": s["leaf"],
                        "w": s["weight"], "why": s["why"], "con": s["contradicted_by"],
                        "sup": s["supported_by"], "chk": store.loads(s["checks"]),
                        "tags": store.loads(s["tags"], {}), "unit": s["unit"],
                    }
                )  # fmt: skip
        judgments = []
        for j in self.rq(
            rid,
            "SELECT layer, pos, stage, key, result, meta FROM judgment WHERE eval = ? AND item = ?",
            (name, item),
        ):
            rec = {
                "layer": j["layer"], "pos": j["pos"], "stage": j["stage"], "key": j["key"],
                "result": store.unpack(j["result"]), "meta": store.loads(j["meta"], {}),
            }  # fmt: skip
            cell = out_cells.get(f"{j['layer']}:{j['pos']}") if j["stage"] == "map" else None
            if cell is not None:
                cell["j"] = {"r": rec["result"], "m": rec["meta"]}
            else:
                judgments.append(rec)
        verdicts = [
            {"pass": v["pass"], "score": v["score"], "detail": store.unpack(v["detail"], {})}
            for v in self.rq(
                rid,
                "SELECT pass, score, detail FROM verdict WHERE eval = ? AND item = ? ORDER BY row",
                (name, item),
            )
        ]
        target = self.rq(
            rid, "SELECT terms, quotes FROM target WHERE eval = ? AND item = ?", (name, item)
        )
        overall = self.q(
            "SELECT pass, score FROM verdict WHERE run_id = ? AND eval = ? AND item = ?",
            (rid, name, item),
        )
        has_digest = bool(
            self.rq(rid, "SELECT 1 FROM digest WHERE eval = ? AND item = ?", (name, item))
        )
        return {
            "run": rid,
            "label": run["label"],
            "method": run["method"],
            "mode": run["mode"],
            "judge": run["judge"],
            "layers": sorted({int(k.split(":")[0]) for k in out_cells}),
            "readouts": readouts,
            "positions": [{"p": p, "t": tokens[p]} for p in sorted(tokens)],
            "cells": out_cells,
            "judgments": judgments,
            "verdicts": verdicts,
            "pass": overall[0]["pass"] if overall else None,
            "score": overall[0]["score"] if overall else None,
            "terms": store.loads(target[0]["terms"], []) if target else [],
            "quotes": store.loads(target[0]["quotes"], []) if target else [],
            "has_digest": has_digest,
        }

    def digest(self, rid: str, name: str, item: str) -> str:
        run = self.run(rid)
        if run is None or self.is_hidden(run["bench"], run["model"], name, item):
            return ""
        rows = self.rq(rid, "SELECT text FROM digest WHERE eval = ? AND item = ?", (name, item))
        return zlib.decompress(rows[0]["text"]).decode("utf-8") if rows else ""

    # ------------------------------------------------------------ cross-run questions

    def filter(
        self, bench: str, model: str, preds: list[tuple[str, str]], name: str | None = None,
        subset: str = "full",
    ) -> list[dict]:  # fmt: skip
        """Questions matching every ``(run_id, want)`` predicate, ``want`` one of ``right``,
        ``wrong``, ``undecided``. Only item-level judge verdicts are used."""
        if not preds:
            return []
        want = {"right": "= 1", "wrong": "= 0"}
        sql, args, where = "SELECT v0.eval, v0.item FROM verdict v0", [], []
        for n in range(1, len(preds)):
            sql += (
                f" JOIN verdict v{n} ON v{n}.eval = v0.eval AND v{n}.item = v0.item"
                f" AND v{n}.run_id = ?"
            )
            args.append(preds[n][0])
        sql += " WHERE v0.run_id = ?"
        args.append(preds[0][0])
        for n, (_rid, w) in enumerate(preds):
            where.append(f"v{n}.pass {want[w]}" if w in want else f"v{n}.pass IS NULL")
        sql += " AND " + " AND ".join(where)
        if name:
            sql += " AND v0.eval = ?"
            args.append(name)
        rows = self.q(sql + " ORDER BY v0.eval, v0.item", tuple(args))
        info = {
            (r["eval"], r["item"]): r
            for r in self.q(
                "SELECT eval, item, expected, intermediates, private FROM item WHERE bench = ?"
                " AND model = ?",
                (bench, model),
            )
        }
        keep = None
        core = self._core(bench) if subset == CORE else None
        if self._listed(bench, model, subset):
            keep = {
                (r["eval"], r["item"])
                for r in self.q(
                    "SELECT eval, item FROM subset_item WHERE bench = ? AND model = ? AND"
                    " subset = ?",
                    (bench, model, self._stored(subset)),
                )
            }
        out = []
        for r in rows:
            key = (r["eval"], r["item"])
            it = info.get(key)
            if it is None or (keep is not None and key not in keep):
                continue
            if core is not None and r["eval"] not in core:
                continue
            shown = self.visible(it)
            both = store.loads(it["expected"], []) + store.loads(it["intermediates"], [])
            exp = list(dict.fromkeys(str(x) for x in both))
            out.append({"eval": r["eval"], "item": r["item"], "expected": exp[:2] if shown else [],
                        "private": bool(it["private"])})  # fmt: skip
        return out

    def score_diff(self, a: str, b: str, name: str | None = None, limit: int = 200) -> list[dict]:
        """Questions ranked by score(a) - score(b): for benches with a per-question rate rather
        than a right / wrong verdict (HallucinationBench)."""
        sql = (
            "SELECT x.eval, x.item, x.score a, y.score b FROM verdict x JOIN verdict y ON"
            " x.eval = y.eval AND x.item = y.item WHERE x.run_id = ? AND y.run_id = ? AND"
            " x.score IS NOT NULL AND y.score IS NOT NULL"
        )
        args: tuple = (a, b)
        if name:
            sql, args = sql + " AND x.eval = ?", (*args, name)
        rows = self.q(sql + " ORDER BY x.score - y.score DESC LIMIT ?", (*args, limit))
        return [dict(r) for r in rows]

    def search(
        self, text: str, bench: str, model: str, rids: list[str] | None = None,
        name: str | None = None, limit: int = 60,
    ) -> list[dict]:  # fmt: skip
        """Readout full-text search. The index finds cells holding every word; the phrase is
        then checked on the text itself. Private questions are skipped unless allowed."""
        words = re.findall(r"\w+", text)
        if not words:
            return []
        match = " AND ".join(f'"{w}"' for w in words)
        needle = text.casefold().strip()
        hidden = set()
        if not self.private:
            hidden = {
                (r["eval"], r["item"])
                for r in self.q(
                    "SELECT eval, item FROM item WHERE bench = ? AND model = ? AND private = 1",
                    (bench, model),
                )
            }
        out: list[dict] = []
        for run in self.runs(bench, model):
            if rids and run["run_id"] not in rids:
                continue
            sql = (
                "SELECT c.eval, c.item, c.layer, c.pos, c.token, r.text FROM readout r"
                " JOIN cell c ON c.id = r.rowid WHERE readout MATCH ?"
            )
            args: tuple = (match,)
            if name:
                sql, args = sql + " AND c.eval = ?", (*args, name)
            per_run = 0
            for r in self.rq(run["run_id"], sql + " LIMIT 4000", args):
                low = r["text"].casefold()
                at = low.find(needle)
                if at < 0 or (r["eval"], r["item"]) in hidden:
                    continue
                a, b = max(0, at - SNIPPET), min(len(low), at + len(needle) + SNIPPET)
                out.append(
                    {
                        "run_id": run["run_id"], "label": run["label"], "method": run["method"],
                        "eval": r["eval"], "item": r["item"], "layer": r["layer"], "pos": r["pos"],
                        "token": r["token"],
                        "pre": r["text"][a:at].replace(store.SAMPLE_SEP, " ⏎ "),
                        "hit": r["text"][at : at + len(needle)],
                        "post": r["text"][at + len(needle) : b].replace(store.SAMPLE_SEP, " ⏎ "),
                    }
                )  # fmt: skip
                per_run += 1
                if per_run >= limit:
                    break
        return out

    # ------------------------------------------------------------ bookmarks

    def bookmarks(self, **where: Any) -> list[dict]:
        sql, args = "SELECT * FROM bookmark", []
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
            args = list(where.values())
        with self.lock:
            return [dict(r) for r in self.user.execute(sql + " ORDER BY created DESC", args)]

    def add_bookmark(self, rec: dict[str, Any]) -> int:
        with self.lock:
            cur = self.user.execute(
                "INSERT INTO bookmark (bench, model, eval, item, run_id, layer, pos, note, created)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (rec.get("bench"), rec.get("model"), rec.get("eval"), rec.get("item"),
                 rec.get("run_id"), rec.get("layer"), rec.get("pos"), rec.get("note") or "",
                 store.now()),
            )  # fmt: skip
            self.user.commit()
            return int(cur.lastrowid or 0)

    def delete_bookmark(self, bid: int) -> None:
        with self.lock:
            self.user.execute("DELETE FROM bookmark WHERE id = ?", (bid,))
            self.user.commit()


def gate_cards(ids: list[str]) -> list[dict[str, str]]:
    return gates.describe(ids)
