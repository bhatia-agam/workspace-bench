"""Build the frozen Wikidata tables of the wrong_intermediate entity check (plan 0066 §5.3, §11.2):
``wd_class_parents.json`` (class -> P279 superclasses), ``wd_registered_bprime.json`` and (plan 0077
§3b) ``wd_registered_options.json`` (P31 / P106 / P17 / P495 of every registered option).

Reads the scrape's entity stores (streamed; the round-1 ``entities.json`` is ~295 MB) and fetches
what they lack from the Wikidata API (``wbgetentities``, rate limited). CC0 Wikidata facts only.

    python scripts/build_wd_tables.py [--entities F ...] [--no-auto-extra] [--out-dir D]

Sources: the round-1 pool ``entities.json`` (``--entities``, default the scrape's), plus (unless
``--no-auto-extra``) every per-set work-dir store that exists at its exact path,
``adapted/<m>/gate/{wrong_bridge,wrong_intermediate}.work/entities_extra.json``, and the round-2
pools' ``wrong_bridge_{r2a,r2b,r3,r4}/entities.json`` (a missing one is skipped with a note).

Every class the walk visits is a key of ``parents``, a parentless one with ``[]``: a class ABSENT
from the table was never seen, and the gate-time kind check stops on it (rebuild the tables).
Plan 0077 §3b: the tables only GROW: the walk runs from an empty table (a new class's ancestors
are walked in full), then the fresh tables are merged under the committed ones (existing keys and
values win) and the result is asserted a superset.
"""

import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wsbench.adapt import wrong_intermediate as wb  # noqa: E402

DEFAULT_ENTITIES = "/workspace/gw-wrong-bridge/outputs/wrong_bridge/entities.json"
# the later rounds' pool stores (plan 0066 §5 r2 as built: r2a / r2b; plan 0077 §3: r3, §3b: r4)
LATER_ROUNDS = tuple(
    Path(f"/workspace/gw-wrong-bridge/outputs/wrong_bridge_{r}/entities.json")
    for r in ("r2a", "r2b", "r3", "r4")
)
ADAPTED = Path("/workspace/wsb-runs/adapted")
WORK_DIRS = ("wrong_bridge.work", "wrong_intermediate.work")
ITEMS = REPO / "evals" / "model_specific" / "wrong_intermediate" / "items_v4.json"
R4 = REPO / "evals" / "model_specific" / "wrong_intermediate" / "r4_distractors.json"
WD = REPO / "evals" / "model_specific" / "wrong_intermediate" / "wikidata_v3.json"
OPTION_PROPS = ("P31", "P106", "P17", "P495")
OUT = REPO / "src" / "wsbench" / "adapt" / "data"
API = "https://www.wikidata.org/w/api.php"
UA = "workspace-bench-adapt/0.1 (interpretability research; build_wd_tables; camilab@anthropic.com)"


def extra_sources(
    adapted: Path = ADAPTED, rounds: Path | tuple[Path, ...] = LATER_ROUNDS
) -> list[str]:
    """The per-set work-dir ``entities_extra.json`` stores and the later rounds' pool stores
    that exist (exact paths, one ``adapted/<m>`` level listed; never a recursive search)."""
    out = []
    if adapted.is_dir():
        for m in sorted(p.name for p in adapted.iterdir() if p.is_dir()):
            for w in WORK_DIRS:
                f = adapted / m / "gate" / w / "entities_extra.json"
                if f.is_file():
                    out.append(str(f))
    print(f"per-set entities_extra.json stores found: {len(out)}", flush=True)
    for store in (rounds,) if isinstance(rounds, Path) else rounds:
        if store.is_file():
            out.append(str(store))
        else:
            print(f"note: pool store {store} does not exist yet; skipped", flush=True)
    return out


def stream_object(path: Path, chunk: int = 1 << 20) -> Iterator[tuple[str, dict]]:
    """(key, value) of a top-level JSON object, one at a time (never the whole file in memory)."""
    dec = json.JSONDecoder()
    with path.open(encoding="utf-8") as f:
        buf, i, eof = f.read(chunk), 0, False

        def more() -> bool:
            nonlocal buf, i, eof
            if eof:
                return False
            got = f.read(chunk)
            if not got:
                eof = True
                return False
            buf, i = buf[i:] + got, 0
            return True

        def skip(chars: str) -> None:
            nonlocal i
            while True:
                while i < len(buf) and buf[i] in chars:
                    i += 1
                if i < len(buf) or not more():
                    return

        skip(" \t\r\n")
        if buf[i] != "{":
            raise SystemExit(f"{path}: not a JSON object")
        i += 1
        while True:
            skip(" \t\r\n,")
            if i >= len(buf) or buf[i] == "}":
                return
            while True:
                try:
                    key, j = dec.raw_decode(buf, i)
                    k = j
                    while True:
                        while k < len(buf) and buf[k] in " \t\r\n:":
                            k += 1
                        if k < len(buf):
                            break
                        raise ValueError("need more")
                    val, j = dec.raw_decode(buf, k)
                    if j >= len(buf) and not eof:
                        raise ValueError("value may be cut")
                    break
                except ValueError:
                    if not more():
                        raise
            i = j
            yield key, val


def values(ent: dict, prop: str) -> list[str]:
    """Every non-deprecated item value of ``prop`` (the check reads all of B''s classes)."""
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        if c.get("rank") == "deprecated":
            continue
        dv = (c.get("mainsnak") or {}).get("datavalue") or {}
        if dv.get("type") == "wikibase-entityid":
            out.append(dv["value"]["id"])
    return sorted(set(out))


class Api:
    def __init__(self, pause: float):
        self.pause, self.calls, self.failed = pause, 0, 0

    def get(self, ids: list[str]) -> dict:
        params = {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
                  "format": "json", "maxlag": "5"}  # fmt: skip
        url = API + "?" + urllib.parse.urlencode(params)
        for k in range(8):
            time.sleep(self.pause)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=90) as r:
                    self.calls += 1
                    d = json.loads(r.read())
                if "error" in d:  # maxlag: back off
                    time.sleep(5 * (k + 1))
                    continue
                return d.get("entities") or {}
            except OSError:
                time.sleep(5 * (k + 1))
        self.failed += 1
        raise SystemExit(f"wbgetentities failed 8 times for {ids[:3]}...")

    def entities(self, ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for n in range(0, len(ids), 50):
            out.update(self.get(ids[n : n + 50]))
            if n and n % 2500 == 0:
                print(f"  fetched {n}/{len(ids)}", flush=True)
        return out


def walk(p31: set[str], p106: set[str], api: "Api") -> dict[str, list[str]]:
    """The class walk from an EMPTY table: ``P31_STEPS`` steps up from the P31 classes (and the
    category roots), ``OCC_STEPS`` from the occupations (and the occupation roots). Every fetched
    class is a key, a parentless one with ``[]``."""
    parents: dict[str, list[str]] = {}

    def fetch(qs: set[str]) -> set[str]:
        todo = sorted(q for q in qs if q not in parents)
        got = api.entities(todo)
        new: set[str] = set()
        for q in todo:
            parents[q] = values(got.get(q) or {}, "P279")
            new.update(parents[q])
        return new

    roots = {q for s in wb.CATEGORY_P31.values() for q in s}
    occ_roots = {q for s in wb.OCCUPATION_ROOTS.values() for q in s}
    frontier = set(p31) | roots
    for _ in range(wb.P31_STEPS):
        frontier = fetch(frontier)
    frontier = set(p106) | occ_roots
    for _ in range(wb.OCC_STEPS):
        frontier = fetch(frontier)
    return dict(sorted(parents.items()))


def grow(existing: dict, fresh: dict) -> dict:
    """``fresh`` merged UNDER ``existing`` (existing keys and values win, new keys added), sorted;
    asserts the result is a superset of both key sets and keeps every existing value."""
    merged = {**fresh, **existing}
    assert set(merged) >= set(existing) | set(fresh)
    assert all(merged[k] == v for k, v in existing.items())
    return dict(sorted(merged.items()))


def _existing(path: Path, key: str) -> tuple[dict, dict]:
    """(``_meta``, ``key`` table) of a committed table; empty when the file does not exist."""
    if not path.exists():
        return {}, {}
    d = json.loads(path.read_text("utf-8"))
    return d.get("_meta") or {}, d.get(key) or {}


def option_qids(items: list[dict]) -> list[str]:
    """Every registered option QID, resolved as ``option_pool`` resolves it."""
    r4 = json.loads(R4.read_text("utf-8"))["items"]
    wd = json.loads(WD.read_text("utf-8"))
    return sorted(wb.registered_option_qids(items, r4, wd))


def option_facts(qids: list[str], api: "Api") -> dict[str, dict[str, list[str]]]:
    """``{qid: {P31, P106, P17, P495}}`` fetched from Wikidata (every non-deprecated value)."""
    got = api.entities(qids)
    return {q: {p: values(got.get(q) or {}, p) for p in OPTION_PROPS} for q in qids}


def _write(path: Path, meta: dict, key: str, table: dict) -> None:
    path.write_text(
        json.dumps({"_meta": meta, key: table}, separators=(",", ":"), sort_keys=True) + "\n",
        "utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--entities",
        nargs="+",
        default=[DEFAULT_ENTITIES],
        help="claim-bearing entity stores (pool entities.json, entities_extra.json)",
    )
    ap.add_argument(
        "--no-auto-extra",
        action="store_true",
        help="do not add the per-set entities_extra.json stores and the later rounds' pool stores",
    )
    ap.add_argument("--items", default=str(ITEMS))
    ap.add_argument("--out-dir", default=str(OUT))
    ap.add_argument("--min-sitelinks", type=int, default=5, help="pick_bridge's floor for a B'")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between API requests")
    args = ap.parse_args()  # fmt: skip

    sources = list(dict.fromkeys(args.entities + ([] if args.no_auto_extra else extra_sources())))
    print("entity sources:\n  " + "\n  ".join(sources), flush=True)
    items = json.loads(Path(args.items).read_text("utf-8"))["items"]
    reg_q = sorted({str(it["wikidata"]["B_prime"]) for it in items})
    p31: set[str] = set()
    p106: set[str] = set()
    registered: dict[str, dict] = {}
    n_ent = 0
    t0 = time.time()
    for f in sources:
        for q, e in stream_object(Path(f)):
            if not q.startswith("Q"):
                continue
            if q in reg_q and q not in registered and (e.get("claims") or {}):
                registered[q] = {p: values(e, p) for p in ("P31", "P106", "P39")}
            if e.get("sitelinks_n", len(e.get("sitelinks") or {})) < args.min_sitelinks:
                continue
            n_ent += 1
            p31.update(values(e, "P31"))
            p106.update(values(e, "P106"))
        print(f"{f}: {n_ent} entities >= {args.min_sitelinks} sitelinks so far, "
              f"{time.time() - t0:.0f}s", flush=True)  # fmt: skip
    api = Api(args.pause)
    missing = [q for q in reg_q if q not in registered]
    for q, e in api.entities(missing).items():
        registered[q] = {p: values(e, p) for p in ("P31", "P106", "P39")}
    if bad := [q for q in reg_q if not registered.get(q, {}).get("P31")]:
        raise SystemExit(f"registered B' with no P31 after the fetch: {bad}")
    for r in registered.values():
        p31.update(r["P31"])
        p106.update(r["P106"])
    # plan 0077 §3b: the registered options' facts, their classes joining the walk's frontier
    opt_q = option_qids(items)
    options = option_facts(opt_q, api)
    if bad := [q for q in opt_q if not options[q]["P31"]]:
        print(f"note: registered options with no P31: {bad}", flush=True)
    for r in options.values():
        p31.update(r["P31"])
        p106.update(r["P106"])
    print(f"classes: {len(p31)} P31, {len(p106)} P106; fetching superclasses", flush=True)
    fresh = walk(p31, p106, api)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = dt.date.today().isoformat()
    old_meta, old_parents = _existing(out / "wd_class_parents.json", "parents")
    table = grow(old_parents, fresh)
    files = list(dict.fromkeys([*(old_meta.get("entity_files") or []), *sources]))
    meta = {"source": "Wikidata (CC0): pool entity stores + wbgetentities", "fetched": date,
            "script": "scripts/build_wd_tables.py", "p31_steps": wb.P31_STEPS,
            "occ_steps": wb.OCC_STEPS, "n_classes": len(table), "entity_files": files,
            "merge": "plan 0077 §3b: walked from empty, merged under the committed table "
                     "(existing entries kept verbatim; superset asserted)"}  # fmt: skip
    _write(out / "wd_class_parents.json", meta, "parents", table)
    _old_reg_meta, old_reg = _existing(out / "wd_registered_bprime.json", "bprime")
    reg_table = grow(old_reg, {q: registered[q] for q in reg_q})
    reg_meta = {**meta, "n_classes": None, "items": "evals/wrong_intermediate/items_v4.json",
                "n_bprime": len(reg_table), "fetched_from_api": len(missing)}  # fmt: skip
    if reg_table != old_reg:  # unchanged: the committed file stays byte-identical
        _write(out / "wd_registered_bprime.json", reg_meta, "bprime", reg_table)
    _old_opt_meta, old_opt = _existing(out / "wd_registered_options.json", "options")
    opt_table = grow(old_opt, options)
    base = {k: v for k, v in meta.items() if k != "entity_files"}  # options: API facts only
    opt_meta = {**base, "n_classes": None, "items": "evals/wrong_intermediate/items_v4.json",
                "resolved": "gold -> wikidata.B_prime, contrast -> B, distractors via "
                            "r4_distractors.json enwiki titles -> wikidata_v3.json enwiki",
                "props": list(OPTION_PROPS), "n_options": len(opt_table),
                "source": "Wikidata (CC0): wbgetentities"}  # fmt: skip
    _write(out / "wd_registered_options.json", opt_meta, "options", opt_table)
    print(f"wrote {len(table)} classes ({len(table) - len(old_parents)} new), {len(reg_table)} "
          f"registered B' ({len(missing)} from the API), {len(opt_table)} registered options; "
          f"{api.calls} API calls, {time.time() - t0:.0f}s")  # fmt: skip


if __name__ == "__main__":
    main()
