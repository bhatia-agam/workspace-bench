"""HallucinationBench adapter: one lens's output directory (``<family>/<judge>/<arm>/
cells.jsonl`` + ``index/<judge>/index.json``) into the viewer store. HB is read as files; the
``hallucination_bench`` package is never imported."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from wsbench.viewer import gates, meta, store
from wsbench.viewer.ingest.common import CellWriter
from wsbench.viewer.ingest.wsb import guess_method

BENCH = "hb"
MODEL = "qwen3.6-27b"
JUDGE = "claude-opus-5-5"
# the claim-map families whose cells this adapter reads; the others are scored from index.json
CLAIM_EVALS = {"main": "wsbench_chat", "story": "story"}
BANKS = {"main": "data/wsbench_chat_x3/items.json", "story": "data/story/items.json"}
NOT_CLAIMS = frozenset({"junk", "non_claim", "off_topic", "failed"})
UNSETTLED = frozenset({"failed", "pending"})
# main: the layers every lens is judged at; its headline (and the paper plots) average these
HEADLINE_LAYERS = (20, 36, 44, 52, 60)
DEFAULT_WEIGHTS = {
    "false_claim": 1.0, "substitution_category": 0.5, "substitution_sibling": 0.5, "detail": 0.2,
}  # fmt: skip
TAG_KEYS = (
    "kind", "raw_leaf", "status", "source", "hedged", "prediction", "world", "world_false",
    "same_slot_alternative", "continuation_text", "contradicted_before_marker", "excuse_verdict",
    "reason", "prefix_clash",
)  # fmt: skip


def leaf_weights(index: dict[str, Any], family: str) -> dict[str, float]:
    w = (index.get("weights") or {}).get(f"{family}_leaf")
    return dict(w) if isinstance(w, dict) else dict(DEFAULT_WEIGHTS)


def arm_dir(lens_dir: Path, eval_dir: str, judge: str, lens: str) -> Path | None:
    base = lens_dir / eval_dir / judge
    if not base.is_dir():
        return None
    arms = [p for p in sorted(base.iterdir()) if (p / "cells.jsonl").exists()]
    return next((p for p in arms if p.name == lens), arms[0] if arms else None)


def load_index(lens_dir: Path, judge: str) -> dict[str, Any]:
    path = lens_dir / "index" / judge / "index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_bank(cat, hb_repo: Path | None, model: str, family: str) -> dict[str, dict]:
    """The family's items (prompt, response, read sites) into the catalog."""
    path = hb_repo / BANKS[family] if hb_repo and family in BANKS else None
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["items"] if isinstance(raw, dict) else raw
    out = {}
    for n, it in enumerate(items):
        m = {
            "response": it.get("response"), "sites": it.get("sites") or [],
            "source": it.get("source"), "subset": it.get("subset"),
        }  # fmt: skip
        cat.execute(
            "INSERT OR REPLACE INTO item VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (BENCH, model, family, it["id"], n, it.get("prompt") or "", "[]", "[]",
             it.get("source"), 0, store.dumps(m)),
        )  # fmt: skip
        out[it["id"]] = m
    return out


def write_eval(cat, model: str, name: str, m: meta.EvalMeta, n_items: int, pre_gate: bool) -> None:
    ids = [g for g in gates.HB_GATES if pre_gate or g != "hb_pregate"]
    cat.execute(
        "INSERT OR REPLACE INTO eval VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (BENCH, model, name, m.title, m.group, m.order, m.what, m.example, m.judged_by,
         m.prompt_template, store.dumps(ids if name in CLAIM_EVALS else []), n_items,
         "hallucination_rate", 0, ""),
    )  # fmt: skip


def ingest_cells(
    con, family: str, cells: Path, weights: dict[str, float], bank: dict[str, dict],
    only: set[str] | None,
) -> dict[str, Any]:  # fmt: skip
    """Stream one arm's cells.jsonl: readouts, segments, and the counts the index is made of."""
    writer = CellWriter(con)
    src = writer.source(cells)
    segs: list[tuple] = []
    per_layer: dict[int, list[float]] = defaultdict(lambda: [0.0, 0])  # weighted, claims
    per_item: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    n_cells = 0
    with open(cells, "rb") as fh:
        off = 0
        for raw in fh:
            length = len(raw)
            rec = json.loads(raw)
            iid, layer, pos = rec["id"], rec["layer"], rec["pos"]
            if not isinstance(layer, int) or (only is not None and iid not in only):
                off += length
                continue
            stages = rec.get("stages") or {}
            cmap = rec.get("map") or {}
            scored = stages.get("map") == "ok" and stages.get("cverify") not in UNSETTLED
            token = next(
                (s.get("token") for s in (bank.get(iid) or {}).get("sites", [])
                 if s.get("pos") == pos), None,
            )  # fmt: skip
            writer.add(family, iid, layer, pos, token, rec.get("samples") or [], 0, src, off,
                       length)  # fmt: skip
            con.execute(
                "INSERT INTO judgment VALUES (?,?,?,?,?,?,?,?)",
                (family, iid, layer, pos, "map", rec.get("key"),
                 store.pack({"rationale": cmap.get("rationale"), "scored": scored}),
                 store.dumps({"stages": stages, "site_kind": rec.get("site_kind"),
                              "n_units": len(cmap.get("units") or [])})),
            )  # fmt: skip
            for s in cmap.get("segments") or []:
                leaf = s.get("leaf") or "failed"
                claim = leaf not in NOT_CLAIMS
                w = weights.get(leaf, 0.0) if claim else None
                tags = {k: s[k] for k in TAG_KEYS if s.get(k) not in (None, False, "")}
                segs.append(
                    (family, iid, layer, pos, s.get("readout", 0), s.get("unit"), s.get("start"),
                     s.get("end"), leaf, w, s.get("why"), s.get("contradicted_by"),
                     s.get("supported_by"),
                     store.dumps(s["excuse_checks"]) if s.get("excuse_checks") else None,
                     store.dumps(tags))
                )  # fmt: skip
                if scored and claim:
                    for acc in (per_layer[layer], per_item[iid]):
                        acc[0] += w or 0.0
                        acc[1] += 1
            if len(segs) >= 20000:
                con.executemany(
                    "INSERT INTO hb_segment VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", segs
                )
                segs = []
            n_cells += 1
            off += length
    con.executemany("INSERT INTO hb_segment VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", segs)
    writer.flush()
    return {"per_layer": per_layer, "per_item": per_item, "n_cells": n_cells}


def write_index_scores(cat, rid: str, index: dict[str, Any], lens: str) -> dict[str, dict]:
    """index.json rows -> per-layer scores, plus the headline: the mean over layers of the
    per-layer value (and of the CI bounds), the number the HB plots report."""
    by_family: dict[str, dict[int, dict]] = defaultdict(dict)
    rows = index.get("rows") or []
    mine = [r for r in rows if r.get("method") == lens] or rows
    for r in mine:
        if not isinstance(r.get("layer"), int):
            continue
        for fam, v in (r.get("families") or {}).items():
            if isinstance(v, dict) and v.get("v") is not None:
                by_family[fam][r["layer"]] = v
    for fam, layers in by_family.items():
        for layer, v in layers.items():
            ci = v.get("ci") or [None, None]
            cat.execute(
                "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, fam, "full", layer, "lens", v["v"], ci[0], ci[1], v.get("n"), None),
            )
            cat.execute(
                "INSERT OR REPLACE INTO layer_stat VALUES (?,?,?,?,?,?)",
                (rid, fam, layer, "hb", v["v"] * (v.get("n") or 0), v.get("n") or 0),
            )
        # a lens judged at more layers still gets the headline over the common five
        used = {k: v for k, v in layers.items() if k in HEADLINE_LAYERS}
        used = used if fam == "main" and len(used) == len(HEADLINE_LAYERS) else layers
        vals = [v["v"] for v in used.values()]
        cis = [v["ci"] for v in used.values() if v.get("ci")]
        lo = sum(c[0] for c in cis) / len(cis) if len(cis) == len(vals) else None
        hi = sum(c[1] for c in cis) / len(cis) if len(cis) == len(vals) else None
        note = "mean over layers " + ", ".join(str(x) for x in sorted(used))
        n_items = max((v.get("n_items") or 0) for v in used.values())
        cat.execute(
            "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, fam, "full", -1, "lens", sum(vals) / len(vals), lo, hi, n_items, note),
        )
    return by_family


def ingest(
    lens_dir: Path,
    store_root: Path,
    *,
    lens: str | None = None,
    model: str = MODEL,
    method: str | None = None,
    label: str | None = None,
    hb_repo: Path | None = None,
    items: list[str] | None = None,
    families: list[str] | None = None,
    build_dir: Path | None = None,
    force: bool = False,
    judge: str | None = None,
    safety_dir: Path | None = None,
    readouts: Path | None = None,
) -> dict[str, Any]:
    """Ingest one lens's HallucinationBench output. Idempotent like the WSB adapter.
    ``safety_dir`` is a second directory to search for the non-claim families (overrefusal,
    benign_roleplay); ``readouts`` holds their readout files (``hb_overrefusal.jsonl`` ...)."""
    lens = lens or lens_dir.name
    judge = judge or JUDGE
    index = load_index(lens_dir, judge)
    arms = {
        fam: d for fam, edir in CLAIM_EVALS.items()
        if (not families or fam in families) and (d := arm_dir(lens_dir, edir, judge, lens))
    }  # fmt: skip
    dirs = [d for d in (lens_dir, safety_dir) if d is not None]
    patterns = (
        "or/overrefusal/*/offtopic_index/index_counts.jsonl",
        "br_index_root/index_counts.jsonl",
    )
    safety_files = [f for pat in patterns if (f := _find(dirs, pat))]
    if not arms and not index and not safety_files:
        raise SystemExit(f"{lens_dir}: no <family>/{judge}/<arm>/cells.jsonl and no index.json")
    rid = store.run_id(BENCH, model, lens)
    files = [d / "cells.jsonl" for d in arms.values()]
    files.append(lens_dir / "index" / judge / "index.json")
    files += safety_files
    sig = store.signature(files) + f"|items={','.join(items or [])}|schema={store.SCHEMA}"
    cat = store.catalog(store_root)
    old = cat.execute("SELECT source_sig FROM run WHERE run_id = ?", (rid,)).fetchone()
    db_path = store.run_db_path(store_root, rid)
    if old and old["source_sig"] == sig and not force and db_path.exists():
        cat.close()
        return {"run_id": rid, "skipped": True}
    for table in ("score", "verdict", "layer_stat"):
        cat.execute(f"DELETE FROM {table} WHERE run_id = ?", (rid,))
    metas = meta.load_hb(hb_repo)
    only = set(items) if items else None
    by_family = write_index_scores(cat, rid, index, lens) if only is None else {}
    summary: dict[str, Any] = {"run_id": rid, "skipped": False, "families": {}, "check": {}}
    with store.building(db_path, build_dir) as tmp:
        con = store.connect(tmp, store.RUN_DDL)
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        for fam, adir in arms.items():
            bank = write_bank(cat, hb_repo, model, fam)
            sv = adir / "summary_v2.json"
            cfg = (
                json.loads(sv.read_text(encoding="utf-8")).get("config", {}) if sv.exists() else {}
            )
            got = ingest_cells(con, fam, adir / "cells.jsonl", leaf_weights(index, fam), bank, only)
            write_eval(cat, model, fam, metas[fam], len(got["per_item"]) or len(bank),
                       bool(cfg.get("pre_gate")))  # fmt: skip
            for iid in got["per_item"]:
                cat.execute(
                    "INSERT OR IGNORE INTO item (bench, model, eval, item, ord, prompt, expected,"
                    " intermediates, private, meta) VALUES (?,?,?,?,?,'','[]','[]',0,'{}')",
                    (BENCH, model, fam, iid, 100000),
                )
            cat.executemany(
                "INSERT OR REPLACE INTO verdict VALUES (?,?,?,?,?)",
                [
                    (rid, fam, i, None, w / n if n else None)
                    for i, (w, n) in got["per_item"].items()
                ],
            )
            # the store's own recount of the index, so a drift from index.json is visible
            check = {}
            for layer, (w, n) in sorted(got["per_layer"].items()):
                ref = (by_family.get(fam) or {}).get(layer)
                if ref and n:
                    check[layer] = round(w / n - ref["v"], 6)
            value = None
            if only is not None:
                tot = [sum(x[0] for x in got["per_layer"].values()),
                       sum(x[1] for x in got["per_layer"].values())]  # fmt: skip
                value = tot[0] / tot[1] if tot[1] else None
                if value is not None:
                    cat.execute(
                        "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            rid,
                            fam,
                            "full",
                            -1,
                            "lens",
                            value,
                            None,
                            None,
                            len(got["per_item"]),
                            "pooled over the ingested items only",
                        ),
                    )
            else:
                row = cat.execute(
                    "SELECT value FROM score WHERE run_id = ? AND eval = ? AND layer = -1",
                    (rid, fam),
                ).fetchone()
                value = row["value"] if row else None
            summary["families"][fam] = {
                "value": value, "n": len(got["per_item"]), "cells": got["n_cells"],
            }  # fmt: skip
            summary["check"][fam] = check
            cat.commit()  # keep the catalog's write lock short: a running viewer reads it
        for fam, fn in (
            ("overrefusal", ingest_overrefusal),
            ("benign_roleplay", ingest_benign_roleplay),
        ):
            if families and fam not in families:
                continue
            got = fn(con, cat, rid, model, lens, dirs, metas, readouts, only)
            if got:
                _safety_bank(cat, hb_repo, model, fam)
                summary["families"][fam] = got
                cat.commit()
        con.commit()
        con.execute("INSERT INTO readout (readout) VALUES ('optimize')")
        con.commit()
        con.close()
    for fam in by_family:  # index families without cells here: scores only
        if fam not in arms and fam in metas and fam not in summary["families"]:
            write_eval(cat, model, fam, metas[fam], 0, False)
    run_meta = {"index_version": index.get("version"), "check": summary["check"], "items": items}
    cat.execute(
        "INSERT OR REPLACE INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, BENCH, lens, label or lens, method or guess_method(lens), model, judge, "claim map",
         str(lens_dir), sig, f"runs/{rid}.db", store.now(), store.dumps(run_meta)),
    )  # fmt: skip
    cat.commit()
    cat.close()
    return summary


# ------------------------------------------------------------------ safety families
# overrefusal and benign_roleplay are not claim maps: each (item, layer) has one judge verdict
# on a digest of that layer's readouts. Their numbers come from the families' own count files.

N_BOOT = 1000
SAFETY_READOUTS = {
    "overrefusal": ("hb_overrefusal.jsonl",),
    "benign_roleplay": ("hb_br_hb_only.jsonl", "hb_br_shared.jsonl"),
}
SAFETY_BANKS = {
    "overrefusal": "data/overrefusal/items.json",
    "benign_roleplay": "data/benign_roleplay/items_v1.json",
}


def _find(dirs: list[Path], pattern: str) -> Path | None:
    for d in dirs:
        hit = sorted(d.glob(pattern))
        if hit:
            return hit[0]
    return None


def _counts(path: Path, lens: str) -> dict[int, dict[str, tuple[int, int]]]:
    """``{layer: {item: (numerator, denominator)}}`` of a family's ``index_counts.jsonl``: the
    index share is n_contradicted / n_claims, pooled over items."""
    out: dict[int, dict[str, tuple[int, int]]] = defaultdict(dict)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r.get("arm") == lens and isinstance(r.get("layer"), int):
                out[r["layer"]][r["item"]] = (r["n_contradicted"], r["n_claims"])
    return out


def _share(items: dict[str, tuple[int, int]]) -> tuple[float, float, float, int] | None:
    """Pooled share with an item-bootstrap 95% CI: ``(value, lo, hi, denominator)``."""
    import random

    vals = list(items.values())
    den = sum(d for _n, d in vals)
    if not den:
        return None
    rng = random.Random(0)
    stats = []
    for _ in range(N_BOOT):
        draw = rng.choices(vals, k=len(vals))
        d = sum(x[1] for x in draw)
        if d:
            stats.append(sum(x[0] for x in draw) / d)
    stats.sort()
    lo, hi = stats[round(0.025 * (len(stats) - 1))], stats[round(0.975 * (len(stats) - 1))]
    return sum(n for n, _d in vals) / den, lo, hi, den


def _write_safety_scores(cat, rid: str, fam: str, counts: dict, note: str) -> float | None:
    per_layer = {}
    for layer, items in sorted(counts.items()):
        s = _share(items)
        if s is None:
            continue
        per_layer[layer] = s
        cat.execute(
            "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, fam, "full", layer, "lens", s[0], s[1], s[2], s[3], note),
        )
        cat.execute(
            "INSERT OR REPLACE INTO layer_stat VALUES (?,?,?,?,?,?)",
            (rid, fam, layer, "hb", s[0] * s[3], s[3]),
        )
    if not per_layer:
        return None
    n = len(per_layer)
    value = sum(s[0] for s in per_layer.values()) / n
    cat.execute(
        "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
        (rid, fam, "full", -1, "lens", value, sum(s[1] for s in per_layer.values()) / n,
         sum(s[2] for s in per_layer.values()) / n,
         max(len(i) for i in counts.values()),
         note + "; mean over layers " + ", ".join(map(str, sorted(per_layer)))),
    )  # fmt: skip
    return value


def _safety_bank(cat, hb_repo: Path | None, model: str, fam: str) -> None:
    path = hb_repo / SAFETY_BANKS[fam] if hb_repo else None
    if path is None or not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    for n, it in enumerate(raw["items"] if isinstance(raw, dict) else raw):
        prompt = it.get("prompt") or "\n\n".join(
            f"[{m.get('role')}]\n{m.get('content', '')}" for m in it.get("messages") or []
        )
        sub = it.get("population") or it.get("control_type") or it.get("kind")
        cat.execute(
            "INSERT OR REPLACE INTO item VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (BENCH, model, fam, it["id"], n, prompt, "[]", "[]", sub, 0, "{}"),
        )


def _safety_cells(con, fam: str, readouts: Path | None, keep: set[str]) -> int:
    n = 0
    if readouts is None:
        return n
    writer = CellWriter(con)
    for name in SAFETY_READOUTS[fam]:
        path = readouts / name
        if not path.exists():
            continue
        src = writer.source(path)
        with open(path, "rb") as fh:
            off = 0
            for raw in fh:
                rec = json.loads(raw)
                if rec["id"] in keep:
                    writer.add(fam, rec["id"], rec["layer"], rec["pos"], rec.get("token"),
                               rec.get("samples") or [], 0, src, off, len(raw))  # fmt: skip
                    n += 1
                off += len(raw)
    writer.flush()
    return n


def _finish_safety(con, cat, rid, model, fam, metas, counts, detail, note, only) -> dict:
    """Shared tail of a safety family: verdict rows (one per item, a block per layer), the
    catalog's per-item rate and the scores."""
    items = {i for layer in counts.values() for i in layer} | set(detail)
    if only is not None:
        items &= only
    for iid in items:
        layers = detail.get(iid, {})
        num = sum(counts[k].get(iid, (0, 0))[0] for k in counts)
        den = sum(counts[k].get(iid, (0, 0))[1] for k in counts)
        row = {"id": iid, "layers": {str(k): v for k, v in sorted(layers.items())}}
        con.execute(
            "INSERT OR REPLACE INTO verdict VALUES (?,?,?,?,?,?)",
            (fam, iid, 0, None, num / den if den else None, store.pack(row)),
        )
        cat.execute(
            "INSERT OR REPLACE INTO verdict VALUES (?,?,?,?,?)",
            (rid, fam, iid, None, num / den if den else None),
        )
        cat.execute(
            "INSERT OR IGNORE INTO item (bench, model, eval, item, ord, prompt, expected,"
            " intermediates, private, meta) VALUES (?,?,?,?,?,'','[]','[]',0,'{}')",
            (BENCH, model, fam, iid, 100000),
        )
    value = _write_safety_scores(cat, rid, fam, counts, note) if only is None else None
    write_eval(cat, model, fam, metas[fam], len(items), False)
    return {"value": value, "n": len(items)}


def ingest_overrefusal(con, cat, rid, model, lens, dirs, metas, readouts, only) -> dict | None:
    """Over-refusal: per (item, layer) the digest lines, the strict judge's refusal verdict and
    the off-topic judge's call on each decline line."""
    root = _find(dirs, "or/overrefusal/*/offtopic_index/index_counts.jsonl")
    if root is None:
        return None
    base = root.parent.parent
    counts = _counts(root, lens)
    off: dict[tuple[str, int], dict] = {}
    off_file = base / "offtopic" / f"{lens}.jsonl"
    if off_file.exists():
        with open(off_file, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                _tag, _lens, item, layer = r["key"].rsplit(":", 3)
                off[(item, int(layer[1:]))] = r.get("result") or {}
    detail: dict[str, dict[int, dict]] = defaultdict(dict)
    records = base / "sj_records_full.jsonl"
    if records.exists():
        with open(records, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                iid, layer = r["item"], r["layer"]
                if r.get("reader") != lens or (only is not None and iid not in only):
                    continue
                lines = (r.get("digest") or {}).get("lines") or []
                o = off.get((iid, layer), {})
                num, den = counts.get(layer, {}).get(iid, (0, 0))
                detail[iid][layer] = {
                    "flagged": num > 0, "refusal_verdict": r.get("verdict"),
                    "decline_lines": den, "off_topic_decline_lines": num,
                    "judge_reason": r.get("sj_reason"), "off_topic_reason": o.get("reason"),
                    "population": r.get("population"),
                }  # fmt: skip
                con.execute(
                    "INSERT INTO judgment VALUES (?,?,?,?,?,?,?,?)",
                    ("overrefusal", iid, layer, None, "strict judge", f"sj:{iid}:L{layer}",
                     store.pack({"verdict": r.get("verdict"), "reason": r.get("sj_reason"),
                                 "decline_lines": [lines[i] for i in r.get("decline_lines") or []
                                                   if isinstance(i, int) and i < len(lines)]}),
                     store.dumps({"digest_lines_the_judge_read": lines})),
                )  # fmt: skip
                if o:
                    con.execute(
                        "INSERT INTO judgment VALUES (?,?,?,?,?,?,?,?)",
                        ("overrefusal", iid, layer, None, "off-topic judge", f"off:{iid}:L{layer}",
                         store.pack(o), "{}"),
                    )  # fmt: skip
    n_cells = _safety_cells(
        con, "overrefusal", readouts, set(detail) | set().union(*counts.values())
    )
    note = ("off-topic decline lines / decline lines, computed by the viewer from "
            "offtopic_index/index_counts.jsonl; CI = item bootstrap")  # fmt: skip
    out = _finish_safety(con, cat, rid, model, "overrefusal", metas, counts, detail, note, only)
    return out | {"cells": n_cells}


def ingest_benign_roleplay(con, cat, rid, model, lens, dirs, metas, readouts, only) -> dict | None:
    """Benign role-play: per (item, layer) WorkspaceBench's jailbreak-recognition judge on that
    layer's digest; flagged = the readouts show a jailbreak recognition."""
    counts_file = _find(dirs, "br_index_root/index_counts.jsonl")
    if counts_file is None:
        return None
    counts = _counts(counts_file, lens)
    detail: dict[str, dict[int, dict]] = defaultdict(dict)
    for d in dirs:
        for res in sorted(
            d.glob(f"benign_roleplay/*/{lens}/*/jailbreak_recognition/L*/results.json")
        ):
            layer = int(res.parent.name[1:])
            r = json.loads(res.read_text(encoding="utf-8"))
            states = {x["id"]: x for x in (r["numbers"].get("extras") or {}).get("item_rows") or []}
            for row in r.get("rows") or []:
                iid = row.get("id")
                if not isinstance(iid, str) or (only is not None and iid not in only):
                    continue
                st = states.get(iid, {})
                quotes, kinds = row.get("quotes") or [], row.get("recognition_kinds") or []
                detail[iid][layer] = {
                    "flagged": bool(st.get("flagged")), "state": st.get("state"),
                    "any_recognition": row.get("any_recognition"),
                    "n_recognition": row.get("n_recognition"), "rationale": row.get("rationale"),
                    "recognition_quotes": [q for q, k in zip(quotes, kinds, strict=False) if k][:6],
                }  # fmt: skip
            cells = res.parent / "cells.jsonl"
            if cells.exists():
                with open(cells, encoding="utf-8") as fh:
                    for line in fh:
                        c = json.loads(line)
                        key = c.get("key") or ""
                        if not key.startswith("digest:"):
                            continue
                        iid = key[7:].split("|", 1)[0]
                        if only is not None and iid not in only:
                            continue
                        con.execute(
                            "INSERT INTO judgment VALUES (?,?,?,?,?,?,?,?)",
                            (
                                "benign_roleplay",
                                iid,
                                layer,
                                None,
                                "digest",
                                key,
                                store.pack(c.get("result")),
                                "{}",
                            ),
                        )
    keep = set(detail) | set().union(*counts.values())
    n_cells = _safety_cells(con, "benign_roleplay", readouts, keep)
    note = ("flagged prompts / judged prompts, computed by the viewer from "
            "br_index_root/index_counts.jsonl; CI = item bootstrap")  # fmt: skip
    out = _finish_safety(con, cat, rid, model, "benign_roleplay", metas, counts, detail, note, only)
    return out | {"cells": n_cells}
