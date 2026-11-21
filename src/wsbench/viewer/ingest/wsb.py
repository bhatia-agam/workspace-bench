"""WorkspaceBench adapter: a judged run directory (``<family>/results.json`` + ``cells.jsonl``)
and its readout files into the viewer store. Reads only; the sources are never modified."""

import copy
import json
import re
import zlib
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from wsbench import fast, nocot, registry
from wsbench import results as wsb_results
from wsbench.viewer import build as bank_view
from wsbench.viewer import gates, meta, store
from wsbench.viewer.ingest.common import CellWriter, fold, sample_texts, strings, term_pattern

BENCH = "wsb"
ORIGINAL = bank_view.ORIGINAL
MACRO = "_macro"
PRIVATE_NOTE = "[private item: its text is not shown unless the viewer runs with private=True]"
WHERE_RE = re.compile(r"\[L(-?\d+) pos (-?\d+)\]")
LAYER_RE = re.compile(r"(?:^|[|_:])L(-?\d+)")
POS_RE = re.compile(r"(?:^|[|_])p(-?\d+)")
MAX_STATEMENTS = 40
MIN_QUOTE = 8
GOLD_KEYS = (
    "gold", "bridge", "target", "targets", "intermediate", "intermediates", "concept", "concepts",
)  # fmt: skip
LAYER_VERDICT_KEYS = ("expressed", "pass", "correct", "hit")  # a native row's per-layer verdict
GOLD_INDEX_KEYS = ("gold_idx", "gold_position")
METHODS = ("olens", "nla", "jlens", "logit_lens", "other")


def guess_method(lens: str, reader: str | None = None, kind: str | None = None) -> str:
    """The method family of a lens from its names; pass ``method=`` to ingest to override."""
    text = f"{lens} {reader or ''}".lower()
    for needle, method in (("logit", "logit_lens"), ("jlens", "jlens"), ("j-lens", "jlens")):
        if needle in text:
            return method
    if re.search(r"(^|[^a-z])(ml)?nla([^a-z]|$)", text):
        return "nla"
    if kind == "tokens":
        return "jlens"
    return "olens"


def layout(path: Path) -> dict[str, Path | None]:
    """A lens directory as a full run lays it out (``judged/``, ``judged_ati/``,
    ``readouts/``), or a bare judged directory."""
    if (path / "judged").is_dir():
        ati = path / "judged_ati"
        ro = path / "readouts"
        return {
            "judged": path / "judged",
            "ati": ati if ati.is_dir() else None,
            "readouts": ro if ro.is_dir() else None,
        }
    return {"judged": path, "ati": None, "readouts": None}


def family_dirs(judged: Path) -> dict[str, Path]:
    """``{family: its results directory}`` under today's keys. A directory named by a key that
    plan 0101 reused (``multihop/`` written before the rename is the single-token family) is
    attributed by its content (``registry.dir_family``); one that cannot be is skipped."""
    out: dict[str, Path] = {}
    for p in sorted(judged.iterdir()):
        if not p.is_dir() or not (p / "results.json").exists():
            continue
        family = registry.dir_family(p)
        if family is None:
            print(f"  {p}: cannot tell which family wrote it (a reused key); skipped")
        elif family in out:
            print(f"  {p}: a second directory of {family} (also {out[family]}); skipped")
        else:
            out[family] = p
    return out


# ------------------------------------------------------------------ banks


def is_original(model: str) -> bool:
    """The original Qwen3.6-27B banks, or an older version of them (``qwen3.6-27b@<commit>``:
    runs judged on an earlier bench are kept apart from the current one)."""
    return model == ORIGINAL or model.startswith(ORIGINAL + "@")


def _bank_file(repo: Path, model: str, family: str) -> Path | None:
    if is_original(model):
        try:
            path = repo / bank_view._bank_rel(family)
        except (KeyError, SystemExit, ValueError):
            return None
    else:
        path = repo / "adapted" / model / f"{family}.json"
    if not path.is_file() and is_original(model):  # an older checkout: the unversioned bank
        path = repo / registry.family_rel(family) / "items.json"
    return path if path.is_file() else None


def _private_ids(repo: Path) -> set[str]:
    """knowledge_cutoff's nocot items: nocot-bench asks that they are not republished."""
    path = repo / nocot.OBSCURE.relative_to(registry.REPO_ROOT)
    if not path.exists():
        return set()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(i.get("id")) for i in raw.get("items", [])}


def _unique(values: Iterable[Any]) -> list[str]:
    """Order-preserving, case-insensitive de-duplication."""
    seen: dict[str, str] = {}
    for v in values:
        seen.setdefault(str(v).casefold(), str(v))
    return list(seen.values())


def bank_items(repo: Path, model: str, family: str) -> list[dict]:
    """The family's questions as catalog rows (prompt, expected, intermediates)."""
    path = _bank_file(repo, model, family)
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    private = _private_ids(repo) if family == "knowledge_cutoff" else set()
    out = []
    for n, item in enumerate(bank_view._items(raw)):
        if not isinstance(item, dict):
            continue
        v = bank_view.view_item(item, n)
        is_private = v["id"] in private or item.get("source") == "nocot"
        small = {k: x for k, x in v["raw"].items() if len(json.dumps(x, default=str)) < 1500}
        out.append(
            {
                "item": v["id"],
                "ord": n,
                "prompt": PRIVATE_NOTE if is_private else v["stimulus"],
                "expected": v["target"],
                "intermediates": _unique(
                    [x for x in v["latent"] if not x.startswith(("{", "["))]  # raw JSON units
                    + strings(item.get("units"))
                    + strings(item.get("mc"))
                ),
                "subfamily": v["subfamily"],
                "private": int(is_private),
                "meta": {} if is_private else small,
            }
        )
    seen = {r["item"] for r in out}
    for n, pid in enumerate(sorted(private - seen)):
        out.append(
            {
                "item": pid,
                "ord": len(out) + n,
                "prompt": PRIVATE_NOTE,
                "expected": [],
                "intermediates": [],
                "subfamily": "nocot",
                "private": 1,
                "meta": {},
            }
        )
    return out


def write_bank(cat, repo: Path, model: str, families: Iterable[str] | None = None) -> int:
    """Evals and items of one subject model's question set into the catalog."""
    metas = meta.load_wsb(repo)
    superseded = registry.superseded()
    names = list(families) if families is not None else list(metas)
    n = 0
    for order, fam in enumerate(names):
        items = bank_items(repo, model, fam)
        if not items and families is None:
            continue
        m = metas.get(fam) or meta.fallback(fam, order)
        base_gates = gates.for_wsb_eval(fam, m.judged_by, adapted=not is_original(model))
        cat.execute(
            "INSERT INTO eval (bench, model, eval, title, grp, ord, what, example, judged_by,"
            " prompt_template, gates, n_items, readme) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT (bench, model, eval) DO UPDATE SET title=excluded.title,"
            " readme=excluded.readme,"
            " grp=excluded.grp, ord=excluded.ord, what=excluded.what, example=excluded.example,"
            " judged_by=excluded.judged_by, prompt_template=excluded.prompt_template,"
            " n_items=CASE WHEN excluded.n_items > 0 THEN excluded.n_items ELSE eval.n_items END",
            (BENCH, model, fam, m.title, m.group, m.order, m.what, m.example, m.judged_by,
             m.prompt_template, store.dumps(base_gates), len(items),
             f"superseded by {superseded[fam]}: left out of default runs and of the macro"
             if fam in superseded else ""),
        )  # fmt: skip
        cat.executemany(
            "INSERT OR REPLACE INTO item VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (BENCH, model, fam, r["item"], r["ord"], r["prompt"], store.dumps(r["expected"]),
                 store.dumps(r["intermediates"]), r["subfamily"], r["private"],
                 store.dumps(r["meta"]))
                for r in items
            ],
        )  # fmt: skip
        n += len(items)
    cat.commit()
    return n


def ingest_banks(store_root: Path, repo: Path, models: Iterable[str] | None = None) -> dict:
    """Every subject model's question set (the original banks and ``adapted/<model>/``)."""
    cat = store.catalog(store_root)
    found = [ORIGINAL, *sorted(p.name for p in (repo / "adapted").glob("*") if p.is_dir())]
    out = {}
    for model in found if models is None else models:
        out[model] = write_bank(cat, repo, model)
    cat.close()
    return out


# ------------------------------------------------------------------ rows and judge calls


def tri(v: Any) -> int | None:
    return int(v) if isinstance(v, bool) else None


def row_pass(row: Mapping[str, Any]) -> int | None:
    for key in ("pass", "correct", "pair_hit"):
        if key in row and (t := tri(row[key])) is not None:
            return t
    return None


def row_score(row: Mapping[str, Any]) -> float | None:
    for key in ("score", "credit", "design_fidelity"):
        v = row.get(key)
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
    p = row_pass(row)
    return None if p is None else float(p)


def row_ids(row: Mapping[str, Any]) -> list[str]:
    """Every question id a results row is about (its own id, its item, a pair's two twins)."""
    out = []
    for key in ("id", "item", "readout_of", "I", "N"):
        v = row.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    return list(dict.fromkeys(out))


def row_gold(row: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for key in GOLD_KEYS:
        out += strings(row.get(key))
    opts = row.get("options")
    for key in GOLD_INDEX_KEYS:
        i = row.get(key)
        if isinstance(opts, list) and isinstance(i, int) and 0 <= i < len(opts):
            out += strings(opts[i])
    return list(dict.fromkeys(out))


def row_quotes(row: Any, depth: int = 0) -> list[str]:
    """Every quote the judge gave as evidence, wherever the family's row keeps it."""
    out: list[str] = []
    if depth > 4:
        return out
    if isinstance(row, Mapping):
        for k, v in row.items():
            if str(k).startswith("summary"):
                continue
            named = "quote" in str(k) or k == "evidence"
            if named and isinstance(v, str):
                out.append(v)
            elif named and isinstance(v, list):
                out += [s for s in v if isinstance(s, str)]
            elif isinstance(v, Mapping | list):
                out += row_quotes(v, depth + 1)
    elif isinstance(row, list):
        for v in row[:200]:
            out += row_quotes(v, depth + 1)
    return [q for q in dict.fromkeys(out) if len(q) >= MIN_QUOTE and not q.startswith("[redacted")]


def exact_layers(row: Mapping[str, Any], judged_layers: Iterable[int]) -> dict[int, bool]:
    """Per-layer verdicts a row really contains (regex and native families); ``{}`` for a
    summary-mode judge row, which has one verdict for all layers together."""
    layers = row.get("layers")
    if isinstance(row.get("passing_layers"), list) and isinstance(layers, Mapping):
        passing = {int(x) for x in row["passing_layers"]}
        return {int(k): int(k) in passing for k in layers if int(k) >= 0}
    if isinstance(row.get("regex_layers_passing"), list):
        passing = {int(x) for x in row["regex_layers_passing"]}
        return {int(k): int(k) in passing for k in judged_layers if int(k) >= 0}
    if isinstance(layers, Mapping) and layers:
        out = {}
        roles = row.get("roles") if isinstance(row.get("roles"), list) else None
        for k, v in layers.items():
            if not str(k).lstrip("-").isdigit() or int(k) < 0:
                continue
            if isinstance(v, Mapping) and isinstance(v.get("hits"), Mapping):
                hits = v["hits"]
                out[int(k)] = all(bool(hits.get(r)) for r in (roles or list(hits)))
                continue
            flag = next(
                (
                    v[f]
                    for f in LAYER_VERDICT_KEYS
                    if isinstance(v, Mapping) and tri(v.get(f)) is not None
                ),
                v if isinstance(v, bool) else None,
            )
            if flag is None:
                return {}
            out[int(k)] = bool(flag)
        return out
    return {}


def slim_row(row: Mapping[str, Any]) -> dict:
    """A results row without the digest text (kept apart) and with its top statements."""
    out = {k: v for k, v in row.items() if not str(k).startswith("summary")}
    stm = row.get("summary_statements")
    if isinstance(stm, list) and stm:
        top = sorted(stm, key=lambda s: -(s.get("count") or 0) if isinstance(s, dict) else 0)
        out["_statements"] = top[:MAX_STATEMENTS]
        out["_n_statements"] = len(stm)
    return out


def parse_key(key: str, ids: set[str]) -> tuple[str | None, str, int | None, int | None]:
    """``(item, stage, layer, pos)`` of a cells.jsonl key. Keys differ per family
    (``digest:<id>|<layer>``, ``layered:<id>|all|d1``, ``<id>|L-1``,
    ``<id>__L044__p69|infer|v2``): the item is the
    longest known id the key starts with, the rest names the stage."""
    prefix = re.match(r"(digest|layered):", key)  # both are digest calls, never the judge
    digest = prefix is not None
    body = key[prefix.end() :] if prefix else key
    item = None
    for sep in ("|", "__L", ":"):
        head = body.split(sep, 1)[0]
        if head in ids:
            item = head
            break
    if item is None:
        for cand in sorted((i for i in ids if body.startswith(i)), key=len, reverse=True):
            item = cand
            break
    rest = body[len(item) :] if item else body
    layer = pos = None
    if digest:
        m = re.match(r"\|(-?\d+)(\||$)", rest)
        layer = int(m.group(1)) if m else None
        stage = "digest" if layer is not None else "digest_all"
    else:
        if m := LAYER_RE.search(rest):
            layer = int(m.group(1))
        if m := POS_RE.search(rest):
            pos = int(m.group(1))
        tags = [t for t in re.split(r"[|:]", rest) if t and not re.fullmatch(r"(__)?L-?\d+.*", t)]
        stage = "/".join(tags) if tags else "judge"
        if tags and tags[0] == "all":
            stage = "digest_all"
    return item, stage, layer, pos


def read_judgments(path: Path, ids: set[str]) -> tuple[list[tuple], dict[str, set]]:
    """cells.jsonl -> judgment rows, plus per item the cells its digest cites."""
    rows: list[tuple] = []
    cited: dict[str, set] = defaultdict(set)
    if not path.exists():
        return rows, cited
    last: dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            key = rec.get("key")
            if not isinstance(key, str):
                continue
            item, stage, layer, pos = parse_key(key, ids)
            result, m = rec.get("result"), rec.get("meta") or {}
            if isinstance(m.get("layer"), int) and layer is None:
                layer = m["layer"]
            if isinstance(m.get("pos"), int) and pos is None:
                pos = m["pos"]
            if stage.startswith("digest") and isinstance(result, Mapping) and item:
                for part in ("items", "rare"):
                    for st in result.get(part) or []:
                        for lm in WHERE_RE.finditer(str(st.get("where") or "")):
                            cited[item].add((int(lm.group(1)), int(lm.group(2))))
            row = (item, layer, pos, stage, key, store.pack(result), store.dumps(m))
            if key in last:  # a re-asked call: the last record is the one the run used
                rows[last[key]] = row
            else:
                last[key] = len(rows)
                rows.append(row)
    return rows, cited


# ------------------------------------------------------------------ one family


def _readout_file(readouts: Path | None, family: str) -> Path | None:
    if readouts is None:
        return None
    for name in registry.lookup_names(family):
        p = readouts / f"{name}.jsonl"
        # a file under a key plan 0101 reused belongs to the family its item ids say
        if p.is_file() and registry.file_family(p) == family:
            return p
    return None


def _unit_outcomes(family: str, result: wsb_results.FamilyResult) -> dict[str, float]:
    """Per scored unit, the outcome the family's headline averages (``fast.units``); empty
    when the family's rows do not reproduce its headline that way."""
    try:
        groups, sign = fast.units(family, result)
    except (KeyError, TypeError, ValueError, SystemExit, AttributeError):
        return {}
    value = fast.value_of(groups, sign)
    if result.value is None or value is None or abs(value - result.value) > 1e-6:
        return {}
    out: dict[str, float] = {}
    for g, units in groups.items():
        for u, v in units.items():
            out[u] = v if sign[g] > 0 else 1.0 - v
    return out


def ingest_family(
    con, cat, rid: str, model: str, family: str, fdir: Path, readout_file: Path | None,
    known: dict[str, dict], copy_text: bool, only: set[str] | None,
) -> dict[str, Any]:  # fmt: skip
    """One family of one run: verdict rows, judge calls, cells; returns its catalog facts."""
    result = wsb_results.read_results(fdir)
    rows = [r for r in result.rows if isinstance(r, dict)]
    if only is not None:
        rows = [r for r in rows if set(row_ids(r)) & only]
    by_item: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for n, row in enumerate(rows):
        for iid in row_ids(row):
            by_item[iid].append((n, row))
    judged_layers = [x for x in result.config.get("layers_judged") or [] if isinstance(x, int)]

    # what the string checks look for, per question
    terms: dict[str, list[str]] = {}
    quotes: dict[str, list[str]] = {}
    for iid, pairs in by_item.items():
        gold = [g for _n, r in pairs for g in row_gold(r)]
        bank = known.get(iid) or {}
        latent = bank.get("intermediates") or []
        terms[iid] = list(dict.fromkeys(gold + (latent or bank.get("expected") or [])))
        quotes[iid] = list(dict.fromkeys(q for _n, r in pairs for q in row_quotes(r)))
    for iid, bank in known.items():
        if iid not in terms:
            terms[iid] = list(bank.get("intermediates") or bank.get("expected") or [])

    ids = set(by_item) | set(known)
    judgments, cited = read_judgments(fdir / "cells.jsonl", ids)
    if only is not None:
        judgments = [j for j in judgments if j[0] in only]
    con.executemany(
        "INSERT INTO judgment VALUES (?,?,?,?,?,?,?,?)", [(family, *j) for j in judgments]
    )
    for iid, pairs in by_item.items():
        for k, (_n, row) in enumerate(pairs):
            con.execute(
                "INSERT OR REPLACE INTO verdict VALUES (?,?,?,?,?,?)",
                (family, iid, k, row_pass(row), row_score(row), store.pack(slim_row(row))),
            )
        text = next((r.get("summary") for _n, r in pairs if isinstance(r.get("summary"), str)), "")
        if text:
            con.execute(
                "INSERT OR REPLACE INTO digest VALUES (?,?,?)",
                (family, iid, zlib.compress(text.encode("utf-8"), 6)),
            )

    # cells
    seen_layers: dict[str, dict[int, int]] = defaultdict(dict)  # item -> layer -> flags OR
    n_cells = 0
    if readout_file is not None:
        writer = CellWriter(con)
        src = writer.source(readout_file)
        pats: dict[str, Any] = {}
        qfold = {i: [fold(q) for q in qs] for i, qs in quotes.items()}
        with open(readout_file, "rb") as fh:
            off = 0
            for raw in fh:
                length = len(raw)
                try:
                    rec = json.loads(raw)
                    iid, layer, pos = str(rec["id"]), int(rec["layer"]), int(rec["pos"])
                except (ValueError, KeyError, TypeError):
                    off += length
                    continue
                if only is not None and iid not in only:
                    off += length
                    continue
                samples = sample_texts(rec)
                if iid not in pats:
                    pats[iid] = term_pattern(terms.get(iid, []))
                flags = 0
                folded = [fold(s) for s in samples]
                if pats[iid] is not None and any(pats[iid].search(s) for s in folded):
                    flags |= store.HAS_EXPECTED
                if any(q in s for q in qfold.get(iid, ()) for s in folded):
                    flags |= store.HAS_QUOTE
                if (layer, pos) in cited.get(iid, ()):
                    flags |= store.CITED
                keep = copy_text or flags
                writer.add(family, iid, layer, pos, rec.get("token"), samples if keep else None,
                           flags, src, off, length, n_samples=len(samples))  # fmt: skip
                seen_layers[iid][layer] = seen_layers[iid].get(layer, 0) | flags
                n_cells += 1
                off += length
        writer.flush()
    con.executemany(
        "INSERT OR REPLACE INTO target VALUES (?,?,?,?)",
        [(family, i, store.dumps(terms.get(i, [])), store.dumps(quotes.get(i, []))) for i in ids],
    )

    # catalog: item verdicts, layer stats, gates
    units = _unit_outcomes(family, result)
    verdicts: dict[str, tuple[int | None, float | None]] = {}
    for iid, pairs in by_item.items():
        own = [r for _n, r in pairs if r.get("role") in (None, "headline")] or [r for _, r in pairs]
        ps = [p for r in own if (p := row_pass(r)) is not None]
        sc = [s for r in own if (s := row_score(r)) is not None]
        p = None if not ps else (1 if all(ps) else 0 if not any(ps) else None)
        verdicts[iid] = (p, sum(sc) / len(sc) if sc else None)
    for u, v in units.items():
        verdicts[u] = (int(v > 0.5), float(v))
    cat.executemany(
        "INSERT OR REPLACE INTO verdict VALUES (?,?,?,?,?)",
        [(rid, family, i, p, s) for i, (p, s) in verdicts.items()],
    )
    stats: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0.0, 0])
    for iid, layers in seen_layers.items():
        has_quote = bool(quotes.get(iid))
        for layer, fl in layers.items():
            st = stats[(layer, "expected")]
            st[0] += bool(fl & store.HAS_EXPECTED)
            st[1] += 1
            if has_quote:
                st = stats[(layer, "cited")]
                st[0] += bool(fl & store.HAS_QUOTE)
                st[1] += 1
    for row in rows:
        for layer, ok in exact_layers(row, judged_layers).items():
            st = stats[(layer, "judge")]
            st[0] += bool(ok)
            st[1] += 1
    cat.executemany(
        "INSERT OR REPLACE INTO layer_stat VALUES (?,?,?,?,?,?)",
        [(rid, family, layer, kind, h, n) for (layer, kind), (h, n) in stats.items()],
    )
    row_keys = {k for r in rows[:50] for k in r}
    return {
        "result": result,
        "row_keys": row_keys,
        "n_cells": n_cells,
        "n_rows": len(rows),
        "items": sorted(set(by_item) | set(seen_layers)),
        "private": {
            i for i, ps in by_item.items() if any(r.get("source") == "nocot" for _, r in ps)
        },
    }  # fmt: skip


# ------------------------------------------------------------------ scores


def _score(cat, rid, ev, subset, layer, kind, value, ci, n, note=None) -> None:
    if value is None:
        return
    lo, hi = (ci[0], ci[1]) if ci else (None, None)
    cat.execute(
        "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
        (rid, ev, subset, layer, kind, float(value), lo, hi, n, note),
    )


def write_scores(cat, rid: str, judged: Path, results: Mapping[str, Any], subset: str) -> None:
    """Headline, chance and floor scores of one judged directory under ``subset``."""
    report = {}
    if (judged / "report.json").exists():
        report = json.loads((judged / "report.json").read_text(encoding="utf-8"))
    floors = report.get("floors") or {}
    for fam, r in results.items():
        _score(cat, rid, fam, subset, -1, "lens", r.value, r.ci95, r.n_items)
        _score(cat, rid, fam, subset, -1, "chance", r.chance, None, None, r.chance_label)
        lucky = (floors.get("lucky_guessing") or {}).get(fam) or {}
        best = max(
            ((v["mean"], k) for k, v in lucky.items()
             if isinstance(v, dict) and isinstance(v.get("mean"), int | float) and k != "uniform"),
            default=None,
        )  # fmt: skip
        if best and subset == "full":
            note = f"best options-only guesser ({best[1]}); the judge never sees a readout"
            _score(cat, rid, fam, subset, -1, "lucky_guess", best[0], None,
                   lucky[best[1]].get("n_items"), note)  # fmt: skip
        po = (floors.get("prompt_only_summary") or {}).get(fam)
        if isinstance(po, dict) and subset == "full" and po.get("rate") is not None:
            try:
                same = wsb_results.summary_floor_applies(r, po)
            except (KeyError, TypeError, ValueError, AttributeError, SystemExit):
                same = False
            note = "a frontier model reads only the prompt text, judged the same way"
            if not same:
                note += "; measured with a different judge prompt version than this run"
            _score(cat, rid, fam, subset, -1, "prompt_only", po["rate"], po.get("ci95"),
                   po.get("n_items"), note)  # fmt: skip
    macro = (report.get("macro") or {}).get("value")
    note = "the run's own macro (report.json)"
    n_macro = len((report.get("macro") or {}).get("families") or [])
    if macro is None:  # no report beside the run: the plain mean of the comparable evals
        vals = [
            r.value for r in results.values()
            if r.value is not None and r.higher_is_better and 0.0 <= r.value <= 1.0
        ]  # fmt: skip
        macro, n_macro = (sum(vals) / len(vals) if vals else None), len(vals)
        note = "mean over the evals with a 0-1, higher-is-better score (the run has no report.json)"
    _score(cat, rid, MACRO, subset, -1, "lens", macro, None, n_macro, note)


FAST_SUBSETS = {"": "fast", "safety": "fast-safety"}  # fast variant -> the store's subset


def fast_subset_of(results: Mapping[str, Any]) -> str:
    """The store subset of a ``--fast`` / ``--fast-safety`` run, from the subset version its
    results are stamped with (any version of the safety variant, ``fast-safety-v<N>``)."""
    safety = fast.VARIANTS["safety"].rsplit("-v", 1)[0]  # "fast-safety"
    stamped = {str(r.config.get("fast_subset") or "") for r in results.values()}
    return FAST_SUBSETS["safety" if any(v.startswith(safety) for v in stamped) else ""]


def write_fast_scores(cat, rid: str, model: str, results: Mapping[str, Any]) -> None:
    """Fast scores of a full run: its verdicts restricted to the frozen fast questions, once per
    fast variant (``fast``: the default fast subset; ``fast-safety``: the same plus
    jailbreak_recognition and agentic_misalignment, written only when the run has one of them)."""
    if model != ORIGINAL:
        return
    active = fast.VERSION
    try:
        for variant, subset in FAST_SUBSETS.items():
            version = fast.select(variant)
            try:
                fams, sub = fast.families(), fast.subset()
            except (SystemExit, OSError, KeyError, ValueError):
                continue
            if variant and not any(f in results for f in set(fams) - set(_fast_families(""))):
                continue  # nothing the plain fast subset does not already show
            _write_fast(cat, rid, model, results, fams, sub, subset, version)
    finally:
        fast.VERSION = active


def _fast_families(variant: str) -> list[str]:
    try:
        return list(fast.subset(fast.VARIANTS[variant]))
    except (SystemExit, OSError, KeyError, ValueError):
        return []


def _write_fast(cat, rid, model, results, fams, sub, subset: str, version: str) -> None:
    vals = []
    note = f"full-run verdicts on the {version} questions (not a separate fast run)"
    for fam in fams:
        r = results.get(fam)
        if r is None or r.value is None or r.config.get("aggregate") != "summary":
            continue
        r2 = copy.deepcopy(r)
        try:
            fast.rescore(fam, r2)
        except (KeyError, TypeError, ValueError, SystemExit, ZeroDivisionError):
            continue
        if r2.value is None or "fast_rescore_mismatch" in r2.extras:
            continue
        _score(cat, rid, fam, subset, -1, "lens", r2.value, r2.ci95, r2.n_items, note)
        vals.append(r2.value)
        members = {u for us in sub[fam]["units"].values() for u in us}
        members |= set(sub[fam].get("read_ids") or [])
        cat.executemany(
            "INSERT OR IGNORE INTO subset_item VALUES (?,?,?,?,?)",
            [(BENCH, model, subset, fam, u) for u in members],
        )
    if vals:
        _score(cat, rid, MACRO, subset, -1, "lens", sum(vals) / len(vals), None, len(vals), note)


def ingest_subset(cat, rid: str, model: str, judged: Path, subset: str) -> int:
    """A judged directory that scores a subset of the run's questions (ATI): scores and
    membership only; the cells and judge calls are the full run's."""
    results = {}
    for fam, fdir in family_dirs(judged).items():
        r = wsb_results.read_results(fdir)
        results[fam] = r
        ids = {i for row in r.rows if isinstance(row, dict) for i in row_ids(row)}
        cat.executemany(
            "INSERT OR IGNORE INTO subset_item VALUES (?,?,?,?,?)",
            [(BENCH, model, subset, fam, i) for i in ids],
        )
    write_scores(cat, rid, judged, results, subset)
    return len(results)


# ------------------------------------------------------------------ entry point


def ingest(
    path: Path,
    store_root: Path,
    *,
    lens: str | None = None,
    model: str = ORIGINAL,
    method: str | None = None,
    label: str | None = None,
    readouts: Path | None = None,
    repo: Path = registry.REPO_ROOT,
    items: list[str] | None = None,
    families: list[str] | None = None,
    build_dir: Path | None = None,
    force: bool = False,
    copy_max_mb: int = 4096,
) -> dict[str, Any]:
    """Ingest one lens. ``path`` is a judged directory or a lens directory holding ``judged/``
    (+ ``judged_ati/``, ``readouts/``). Idempotent: an unchanged source is skipped unless
    ``force``. ``items`` keeps only those question ids (the two-question try-out)."""
    lay = layout(path)
    judged = lay["judged"]
    readouts = readouts or lay["readouts"]
    lens = lens or path.name
    fdirs = family_dirs(judged)
    if families:
        fdirs = {f: d for f, d in fdirs.items() if f in families}
    if not fdirs:
        raise SystemExit(f"{judged}: no <family>/results.json found")
    rid = store.run_id(BENCH, model, lens)
    files = [d / n for d in fdirs.values() for n in ("results.json", "cells.jsonl")]
    files += [p for f in fdirs if (p := _readout_file(readouts, f))]
    if lay["ati"]:
        files += [d / "results.json" for d in family_dirs(lay["ati"]).values()]
    sig = store.signature(files) + f"|items={','.join(items or [])}|schema={store.SCHEMA}"
    cat = store.catalog(store_root)
    old = cat.execute("SELECT source_sig FROM run WHERE run_id = ?", (rid,)).fetchone()
    if (
        old
        and old["source_sig"] == sig
        and not force
        and store.run_db_path(store_root, rid).exists()
    ):
        cat.close()
        return {"run_id": rid, "skipped": True}

    for table in ("score", "verdict", "layer_stat"):
        cat.execute(f"DELETE FROM {table} WHERE run_id = ?", (rid,))
    write_bank(cat, repo, model, families=list(fdirs))
    only = set(items) if items else None
    summary: dict[str, Any] = {"run_id": rid, "skipped": False, "families": {}}
    results: dict[str, Any] = {}
    reader = kind = judge = None
    with store.building(store.run_db_path(store_root, rid), build_dir) as tmp:
        con = store.connect(tmp, store.RUN_DDL)
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        for fam, fdir in fdirs.items():
            known = {
                r["item"]: {"expected": store.loads(r["expected"], []),
                            "intermediates": store.loads(r["intermediates"], [])}
                for r in cat.execute(
                    "SELECT item, expected, intermediates FROM item"
                    " WHERE bench = ? AND model = ? AND eval = ?", (BENCH, model, fam))
            }  # fmt: skip
            rfile = _readout_file(readouts, fam)
            big = rfile is not None and rfile.stat().st_size > copy_max_mb * 2**20
            info = ingest_family(con, cat, rid, model, fam, fdir, rfile, known, not big, only)
            r = info["result"]
            results[fam] = r
            reader = reader or r.config.get("reader")
            kind = kind or r.config.get("kind")
            judge = judge or r.config.get("judge_model")
            m_judged = cat.execute(
                "SELECT judged_by FROM eval WHERE bench = ? AND model = ? AND eval = ?",
                (BENCH, model, fam),
            ).fetchone()
            in_ati = bool(lay["ati"] and (lay["ati"] / fam / "results.json").exists())
            gate_ids = gates.for_wsb_eval(
                fam, m_judged["judged_by"] if m_judged else "", info["row_keys"], r.config,
                adapted=not is_original(model), ati=in_ati,
            )  # fmt: skip
            cat.execute(
                "UPDATE eval SET gates = ?, metric = ?, higher_is_better = ?,"
                " n_items = CASE WHEN n_items > 0 THEN n_items ELSE ? END"
                " WHERE bench = ? AND model = ? AND eval = ?",
                (store.dumps(gate_ids), r.metric, int(r.higher_is_better), r.n_items, BENCH,
                 model, fam),
            )  # fmt: skip
            have = set(known)
            extra = [i for i in info["items"] if i not in have]
            cat.executemany(
                "INSERT OR IGNORE INTO item (bench, model, eval, item, ord, prompt, expected,"
                " intermediates, private, meta) VALUES (?,?,?,?,?,?,'[]','[]',?,'{}')",
                [(BENCH, model, fam, i, 100000 + n, "", int(i in info["private"]))
                 for n, i in enumerate(extra)],
            )  # fmt: skip
            cat.executemany(
                "UPDATE item SET private = 1, prompt = ? WHERE bench = ? AND model = ? AND"
                " eval = ? AND item = ?",
                [(PRIVATE_NOTE, BENCH, model, fam, i) for i in info["private"]],
            )
            cat.commit()  # keep the catalog's write lock short: a running viewer reads it
            summary["families"][fam] = {
                "value": r.value, "n": r.n_items, "cells": info["n_cells"], "rows": info["n_rows"],
            }  # fmt: skip
        con.commit()
        con.execute("INSERT INTO readout (readout) VALUES ('optimize')")
        con.commit()
        con.close()
    ati_run = all(r.config.get("scope") == "anti_text_inversion" for r in results.values())
    if only is None and ati_run:
        # a lens judged on the ATI subset only: its scores are ATI scores, never full or fast
        ingest_subset(cat, rid, model, judged, "ati")
    elif only is None and all(r.config.get("scope") == fast.SCOPE for r in results.values()):
        # a --fast / --fast-safety run: its results.json values are that subset's scores
        # (never full-bench ones)
        fast_name = fast_subset_of(results)
        write_scores(cat, rid, judged, results, fast_name)
        try:
            safety = fast_name == FAST_SUBSETS["safety"]
            sub = fast.subset(fast.VARIANTS["safety" if safety else ""])
        except (SystemExit, OSError, KeyError, ValueError):
            sub = {}
        for fam in results:
            e = sub.get(fam) or {}
            members = {u for us in (e.get("units") or {}).values() for u in us}
            members |= set(e.get("read_ids") or [])
            cat.executemany(
                "INSERT OR IGNORE INTO subset_item VALUES (?,?,?,?,?)",
                [(BENCH, model, fast_name, fam, u) for u in members],
            )
        if lay["ati"]:
            ingest_subset(cat, rid, model, lay["ati"], "ati")
    elif only is None:
        write_scores(cat, rid, judged, results, "full")
        write_fast_scores(cat, rid, model, results)
        if lay["ati"]:
            ingest_subset(cat, rid, model, lay["ati"], "ati")
    else:  # a partial ingest has no meaningful headline: score what was ingested
        for fam in results:
            rows = cat.execute(
                "SELECT pass FROM verdict WHERE run_id = ? AND eval = ? AND pass IS NOT NULL",
                (rid, fam),
            ).fetchall()
            if rows:
                val = sum(x["pass"] for x in rows) / len(rows)
                _score(cat, rid, fam, "full", -1, "lens", val, None, len(rows),
                       "pass rate over the ingested questions only")  # fmt: skip
    run_meta = {"reader": reader, "kind": kind, "items": items, "readouts": str(readouts or "")}
    cat.execute(
        "INSERT OR REPLACE INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, BENCH, lens, label or lens, method or guess_method(lens, reader, kind), model,
         judge, next(iter(results.values())).config.get("aggregate") or "native", str(path), sig,
         f"runs/{rid}.db", store.now(), store.dumps(run_meta)),
    )  # fmt: skip
    cat.commit()
    cat.close()
    return summary
