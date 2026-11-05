"""Build the frozen Wikidata tables of the wrong_intermediate entity check (plan 0066 §5.3, §11.2):
``wd_class_parents.json`` (class -> P279 superclasses) and ``wd_registered_bprime.json``.

Reads the scrape's entity stores (streamed; the round-1 ``entities.json`` is ~295 MB) and fetches
what they lack from the Wikidata API (``wbgetentities``, rate limited). CC0 Wikidata facts only.

    python scripts/build_wd_tables.py [--entities F ...] [--no-auto-extra] [--out-dir D]

Sources: the round-1 pool ``entities.json`` (``--entities``, default the scrape's), plus (unless
``--no-auto-extra``) every per-set work-dir store that exists at its exact path,
``adapted/<m>/gate/{wrong_bridge,wrong_intermediate}.work/entities_extra.json``, and the round-2
pool ``wrong_bridge_r2/entities.json`` (a missing one is skipped with a printed note).

Every class the walk visits is a key of ``parents``, a parentless one with ``[]``: a class ABSENT
from the table was never seen, and the gate-time kind check stops on it (rebuild the tables).
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
ROUND2_ENTITIES = Path("/workspace/gw-wrong-bridge/outputs/wrong_bridge_r2/entities.json")
ADAPTED = Path("/workspace/wsb-runs/adapted")
WORK_DIRS = ("wrong_bridge.work", "wrong_intermediate.work")
ITEMS = REPO / "evals" / "wrong_intermediate" / "items_v4.json"
OUT = REPO / "src" / "wsbench" / "adapt" / "data"
API = "https://www.wikidata.org/w/api.php"
UA = "workspace-bench-adapt/0.1 (interpretability research; build_wd_tables; camilab@anthropic.com)"


def extra_sources(adapted: Path = ADAPTED, round2: Path = ROUND2_ENTITIES) -> list[str]:
    """The per-set work-dir ``entities_extra.json`` stores and the round-2 pool store that exist
    (exact paths, one ``adapted/<m>`` level listed; never a recursive search)."""
    out = []
    if adapted.is_dir():
        for m in sorted(p.name for p in adapted.iterdir() if p.is_dir()):
            for w in WORK_DIRS:
                f = adapted / m / "gate" / w / "entities_extra.json"
                if f.is_file():
                    out.append(str(f))
    print(f"per-set entities_extra.json stores found: {len(out)}", flush=True)
    if round2.is_file():
        out.append(str(round2))
    else:
        print(f"note: round-2 pool store {round2} does not exist yet; skipped", flush=True)
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
        help="do not add the per-set entities_extra.json stores and the round-2 pool store",
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
    roots = {q for s in wb.CATEGORY_P31.values() for q in s}
    occ_roots = {q for s in wb.OCCUPATION_ROOTS.values() for q in s}
    print(f"classes: {len(p31)} P31, {len(p106)} P106; fetching superclasses", flush=True)

    parents: dict[str, list[str]] = {}

    def fetch(qs: set[str]) -> set[str]:
        todo = sorted(q for q in qs if q not in parents)
        got = api.entities(todo)
        new: set[str] = set()
        for q in todo:
            parents[q] = values(got.get(q) or {}, "P279")
            new.update(parents[q])
        return new

    # P31: the check walks P31_STEPS steps; P106: OCC_STEPS steps (the closure of §5.3)
    frontier = set(p31) | roots
    for _ in range(wb.P31_STEPS):
        frontier = fetch(frontier)
    frontier = set(p106) | occ_roots
    for _ in range(wb.OCC_STEPS):
        frontier = fetch(frontier)
    # every visited class stays, a parentless one with []: "absent" means "never seen"
    table = dict(sorted(parents.items()))
    date = dt.date.today().isoformat()
    meta = {"source": "Wikidata (CC0): pool entity stores + wbgetentities", "fetched": date,
            "script": "scripts/build_wd_tables.py", "p31_steps": wb.P31_STEPS,
            "occ_steps": wb.OCC_STEPS, "n_classes": len(table),
            "entity_files": sources}  # fmt: skip
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "wd_class_parents.json").write_text(
        json.dumps({"_meta": meta, "parents": table}, separators=(",", ":"), sort_keys=True) + "\n",
        "utf-8",
    )
    reg_meta = {**meta, "n_classes": None, "items": "evals/wrong_intermediate/items_v4.json",
                "n_bprime": len(reg_q), "fetched_from_api": len(missing)}  # fmt: skip
    (out / "wd_registered_bprime.json").write_text(
        json.dumps({"_meta": reg_meta, "bprime": {q: registered[q] for q in reg_q}},
                   separators=(",", ":"), sort_keys=True) + "\n",
        "utf-8",
    )  # fmt: skip
    print(f"wrote {len(table)} classes, {len(reg_q)} registered B' ({len(missing)} from the API); "
          f"{api.calls} API calls, {time.time() - t0:.0f}s")  # fmt: skip


if __name__ == "__main__":
    main()
