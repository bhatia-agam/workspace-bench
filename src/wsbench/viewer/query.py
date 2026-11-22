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

from wsbench.viewer import gates, store

MACRO = "_macro"
BENCH_TITLES = {"wsb": "WorkspaceBench", "hb": "HallucinationBench"}
CORE = "core"  # the default tier: shown from the full run's rows, never stored
SUBSET_TITLES = {  # in the order the dropdown lists them
    CORE: "Core (the default tier)",
    "full": "Full bench",
    "fast": "Fast subset",
    "fast-safety": "Fast subset + safety",
    "ati": "Anti-text-inversion (ATI)",
}
WHOLE_BANK = ("full", CORE)  # subsets that keep every question of the evals they hold
METHOD_ORDER = {"olens": 0, "nla": 1, "jlens": 2, "logit_lens": 3, "other": 4}
METHOD_TITLES = {
    "olens": "O-lens", "nla": "NLA", "jlens": "J-lens", "logit_lens": "Logit lens",
    "other": "Other",
}  # fmt: skip
SNIPPET = 110


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

    def rq(self, rid: str, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        con = self.run_con(rid)
        if con is None:
            return []
        with self.lock:
            return con.execute(sql, args).fetchall()

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
        return self._named(dict(rows[0])) if rows else None

    def _named(self, run: dict) -> dict:
        """The run with its display name: the alias file's label, else the label given at
        ingest, else the lens id with the store's common prefixes removed."""
        alias = self._aliases().get(run["lens"]) or {}
        label = alias.get("label") or run["label"]
        return run | {
            "label": label,
            "description": alias.get("description") or "",
            "default": bool(alias.get("default")),  # shown when the page names no lenses
        }

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
        have = {r["subset"] for r in rows} | {"full"}
        if self._core(bench) and any(
            e in self._core(bench) for e in self._full_evals(bench, model)
        ):
            have.add(CORE)
        return [s for s in SUBSET_TITLES if s in have]

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
        return [dict(r) | {"gates": store.loads(r["gates"], [])} for r in rows]

    def eval(self, bench: str, model: str, name: str) -> dict | None:
        return next((e for e in self.evals(bench, model) if e["eval"] == name), None)

    def groups(self, bench: str, model: str) -> list[tuple[str, list[dict]]]:
        out: dict[str, list[dict]] = {}
        for e in self.evals(bench, model):
            out.setdefault(e["grp"] or "Other", []).append(e)
        return list(out.items())

    def scores(self, bench: str, model: str, subset: str) -> dict[str, dict[str, dict]]:
        """``{eval: {run_id | floor kind: score}}`` at the headline layer for one subset. Floors
        (prompt_only, lucky_guess, chance) are per eval, taken from any run that carries them."""
        rows = self.q(
            "SELECT s.* FROM score s JOIN run r USING (run_id) WHERE r.bench = ? AND r.model = ?"
            " AND s.subset = ? AND s.layer = -1",
            (bench, model, "full" if subset == CORE else subset),
        )
        out: dict[str, dict[str, dict]] = defaultdict(dict)
        for r in rows:
            key = r["run_id"] if r["kind"] == "lens" else r["kind"]
            if key not in out[r["eval"]] or r["kind"] == "lens":
                out[r["eval"]][key] = dict(r)
        return self._core_scores(out, self._core(bench)) if subset == CORE else out

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

    def subset_counts(self, bench: str, model: str, subset: str) -> dict[str, int]:
        if subset in WHOLE_BANK:
            return {}
        rows = self.q(
            "SELECT eval, count(*) n FROM subset_item WHERE bench = ? AND model = ? AND subset = ?"
            " GROUP BY eval",
            (bench, model, subset),
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
        if subset not in WHOLE_BANK:
            keep = {
                r["item"]
                for r in self.q(
                    "SELECT item FROM subset_item WHERE bench = ? AND model = ? AND subset = ?"
                    " AND eval = ?",
                    (bench, model, subset, name),
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
            for c in sorted(missing, key=lambda c: (c["src"], c["off"])):
                try:
                    with open(paths[c["src"]], "rb") as fh:
                        fh.seek(c["off"])
                        rec = json.loads(fh.read(c["len"]))
                    from wsbench.viewer.ingest.common import sample_texts

                    out[c["id"]] = sample_texts(rec)
                except (OSError, ValueError, KeyError):
                    out[c["id"]] = ["[readout source file is no longer available]"]
        return out

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
            "layers": sorted({c["layer"] for c in cells}),
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
        if subset not in WHOLE_BANK:
            keep = {
                (r["eval"], r["item"])
                for r in self.q(
                    "SELECT eval, item FROM subset_item WHERE bench = ? AND model = ? AND"
                    " subset = ?",
                    (bench, model, subset),
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
