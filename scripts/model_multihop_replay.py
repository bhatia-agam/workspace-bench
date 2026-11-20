"""Validation gate for model_multihop (plan 0076): convert gw's frozen readouts of all five readers
to the contract, check the native summarizer material is byte-equal to gw's (prose readers), and
replay gw's frozen summaries + judge answers through this family's verifier and scorer.

    python scripts/model_multihop_replay.py --gw <gw checkout> --mmh <gw mmh outputs dir> \
        --out /root/tmp/mmh-wsb-replay

Exits non-zero on any render or count difference."""

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from wsbench import reads
from wsbench.evals.model_specific.model_multihop import judge, prompts, score
from wsbench.judge_config import resolve
from wsbench.readouts import write_sidecar
from wsbench.readplan import GRID
from wsbench.registry import FAMILIES, JudgeArgs, load_all

NAME = "model_multihop"
FROZEN_REL = "evals/model_multihop/frozen_v2.json"
SJUDGE_REL = "scripts/feas/model_multihop/mmh_sjudge.py"
# reader -> (gw file suffix, layers, gw grid file, grid field, token reader?, headline unit)
READERS: dict[str, tuple[str, list[int], str, str, bool, str]] = {
    "s3d": ("", list(GRID), "", "", False, "all"),
    "mlnla": ("_mlnla", list(GRID), "grid_mlnla-rl600_v2.jsonl", "readouts", False, "all"),
    "jlens": ("_jlens", list(GRID), "grid_jlens_v2.jsonl", "jlens", True, "all"),
    "logit": ("_logit", [63], "grid_jlens_v2.jsonl", "logit", True, "63"),
    "nla": ("_nla", [42], "grid_nla-rl400_v2.jsonl", "readouts", False, "42"),
}
PROSE = ("s3d", "mlnla", "nla")
# plan rev G: exact integer counts, both categories with the item foils (gw's non-nb judge files,
# cjudge_v2{,_<reader>}.jsonl), the bank's options since bank v2
FROZEN_COUNTS = {
    "s3d": {"invented": (250, 255), "cutoff": (18, 28)},
    "mlnla": {"invented": (237, 255), "cutoff": (14, 28)},
    "jlens": {"invented": (245, 255), "cutoff": (4, 27)},
    "logit": {"invented": (235, 255), "cutoff": (10, 28)},
    "nla": {"invented": (221, 255), "cutoff": (12, 27)},
}
JUDGED = "cjudge_v2{suf}.jsonl"  # both categories (rev G: no _nb file)


def _jsonl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def gw_strings(gw: Path) -> dict[str, Any]:
    """gw ``mmh_sjudge``'s SUMMARIZER / CJUDGE / TASK, read from the source (no import)."""
    out = {}
    for n in ast.parse((gw / SJUDGE_REL).read_text()).body:
        t = n.targets[0] if isinstance(n, ast.Assign) else None
        if isinstance(t, ast.Name) and t.id in ("SUMMARIZER", "CJUDGE", "TASK"):
            out[t.id] = ast.literal_eval(n.value)
    return out


# ------------------------------------------------------------------ gw side, verbatim


def gw_cells(rd: dict[str, Any], region: str) -> dict[int, dict[int, str]]:
    """Verbatim gw ``mmh_sjudge._cells``."""
    meta = rd.get("pos_meta") or {}
    keep = {int(p) for p, m in meta.items() if region in (m.get("set") or [])}
    out: dict[int, dict[int, str]] = {}
    for layer, cells in rd["readouts"].items():
        out[int(layer)] = {
            int(c["pos"]): str(c["text"]).strip()
            for c in cells
            if (region in c["set"] if "set" in c else int(c["pos"]) in keep)
        }
    return out


def gw_units(rd: dict[str, Any], multi: bool) -> dict[str, tuple[str, str]]:
    """gw ``summarize``'s units: str(layer) or "all" -> (material, where)."""
    cells = gw_cells(rd, "post")
    units: dict[str, tuple[str, str]] = {}
    for layer, c in sorted(cells.items()):
        mat = "\n".join(f"[p{q}] {t}" for q, t in sorted(c.items()) if t)
        units[str(layer)] = (mat, "several token positions of one prompt, at one layer")
    if multi:
        mat = "\n".join(
            f"[L{layer} p{q}] {t}"
            for layer, c in sorted(cells.items())
            for q, t in sorted(c.items())
            if t
        )
        units["all"] = (mat, "several token positions of one prompt, at several layers")
    return units


# ------------------------------------------------------------------ conversion


def convert(reader: str, mmh: Path, frozen: dict[str, dict], items: list[dict], out: Path) -> Path:
    _suf, layers, grid, field, is_tok, _head = READERS[reader]
    path = out / f"{reader}.jsonl"
    n = 0
    with path.open("w", encoding="utf-8") as fh:

        def put(iid: str, layer: int, pos: int, v: Any) -> None:
            nonlocal n
            row: dict[str, Any] = {"id": iid, "layer": layer, "pos": pos}
            row |= {"tokens": [str(t) for t in v]} if is_tok else {"samples": [str(v)]}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1

        if reader == "s3d":
            for it in items:
                rd = json.loads((mmh / "reads_v2" / f"mmh__{it['id']}__main.json").read_text())
                want = set(it["positions"])
                for layer in layers:
                    for c in rd["readouts"][str(layer)]:
                        if int(c["pos"]) in want:
                            put(it["id"], layer, int(c["pos"]), c["text"])
        else:
            rows = {r["key"]: r for r in _jsonl(mmh / grid)}
            for it in items:
                r = rows[f"mmh__{it['id']}__main"]
                allpos = [int(p) for p in frozen[it["id"]]["read"]["positions"]]
                want = set(it["positions"])
                for layer in layers:
                    vals = r[field][str(layer)]
                    if len(vals) != len(allpos):
                        raise SystemExit(f"{reader} {it['id']} L{layer}: misaligned grid row")
                    for p, v in zip(allpos, vals, strict=True):
                        if p in want:
                            put(it["id"], layer, p, v)
    write_sidecar(
        path,
        sampling="tokens10" if is_tok else "prose1",
        reader=f"gw-mmh-v2-{reader}",
        arm="frozen_v2",
        layers=layers,
        reads="full",
        plan_sha=reads.plan_sha(NAME),
    )
    print(f"[convert] {reader}: {n} rows -> {path}")
    return path


def bench_cells(path: Path, layers: list[int], out: Path) -> dict[str, list]:
    """The converted file through the bench loader (sidecar, plan_sha and span checks)."""
    load_all()
    spec = FAMILIES[NAME]
    args = JudgeArgs(
        readouts=path, out=out, judge=resolve(spec.judge),
        layers=layers if layers != GRID else None, items=None, limit=0, allow_missing=False,
        concurrency=1, rpm=1e9, dry_run=True, extra={"aggregate": "native"},
    )  # fmt: skip
    items = judge.load_items()
    cells, rep = reads.load(
        args,
        NAME,
        ids=[it["id"] for it in items],
        positions={it["id"]: it["positions"] for it in items},
    )
    if rep.reads_checked != "sidecar" or rep.partial_ids:
        raise SystemExit(f"{path}: reads {rep.reads_checked}, partial ids {rep.partial_ids}")
    by: dict[str, list] = defaultdict(list)
    for c in cells:
        by[c.id].append(c)
    return by


# ------------------------------------------------------------------ (2a) renders


def check_renders(reader: str, mmh: Path, by: dict[str, list], items: list[dict], gw: dict) -> int:
    _suf, layers, *_rest = READERS[reader]
    src = mmh / ("reads_v2" if reader == "s3d" else f"reads_v2_{reader}")
    n = bad = 0
    for it in items:
        rd = json.loads((src / f"mmh__{it['id']}__main.json").read_text())
        theirs = gw_units(rd, len(layers) > 1)
        mine = judge.native_units(by.get(it["id"], []), layers)
        if set(theirs) != {str(u) for u in mine}:
            bad += 1
            print(f"  UNITS DIFFER {reader} {it['id']}: {sorted(theirs)}")
            continue
        for u, mat in mine.items():
            tmat, where = theirs[str(u)]
            gw_prompt = prompts.port(gw["SUMMARIZER"]).replace("{where}", where)
            gw_prompt = gw_prompt.replace("{material}", tmat)
            n += 1
            if mat != tmat or judge.summarizer_user(mat, u) != gw_prompt:
                bad += 1
                if bad <= 3:
                    print(f"  DIFF {reader} {it['id']} {u}")
    print(f"[2a] {reader}: {n} units, {bad} differ from gw")
    return bad


# ------------------------------------------------------------------ (2b) frozen replay


def _last_ok(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        if r.get("ok"):
            out[(r["id"], str(r["layer"]))] = r
    return out


def replay(reader: str, mmh: Path, items: list[dict]) -> tuple[dict[str, tuple[int, int]], int]:
    """(2b) on the rows: the counts, and the number of problems (a flipped pick, a candidate
    set that is not the item's options, an unresolvable answer)."""
    suf, _layers, _g, _f, _tok, head = READERS[reader]
    summ = _last_ok(_jsonl(mmh / f"summ_v2{suf}.jsonl"))
    rows_all = _last_ok(_jsonl(mmh / JUDGED.format(suf=suf)))
    judged = {"invented": rows_all, "cutoff": rows_all}
    rows = []
    n_reverified = n_flipped = n_bad = 0
    for it in items:
        r = judged[it["cat"]].get((it["id"], head))
        row = {"id": it["id"], "cat": it["cat"], "bridge": it["bridge"]}
        row["n_options"] = len(it["mc"]["order"])
        if r is None:
            rows.append({**row, "pass": None, "role": None})
            continue
        if set(r["cands"]) != set(it["mc"]["order"]) or r["cands"][0] != it["mc"]["gold"]:
            n_bad += 1
            print(f"  CANDIDATES DIFFER {reader} {it['id']}")
            continue
        if r["pick"] == "none":  # gw's none, or a gw void (the pick is gone): judged none
            role = "none"
        else:  # re-verify the quote and resolve the pick with this family's code
            s = summ[(it["id"], head)]["summary"]
            v = score.native_verdict(r, it["mc"]["order"], it["mc"]["gold"], s)
            if v is None:
                n_bad += 1
                continue
            role = v["role"]
            n_reverified += 1
            n_flipped += role != r["role"].replace("foil", "decoy")
        rows.append({**row, "pass": role == "bridge", "role": role})
    out = {}
    for cat in ("invented", "cutoff"):
        st = score.category_stats([r for r in rows if r["cat"] == cat], n_boot=1000)
        out[cat] = (st.get("n_bridge", 0), st["n"])
    print(f"[2b] {reader} [{head}]: {n_reverified} picks re-verified, {n_flipped} changed; "
          f"invented {out['invented'][0]}/{out['invented'][1]}, "
          f"cutoff {out['cutoff'][0]}/{out['cutoff'][1]}")  # fmt: skip
    return out, n_flipped + n_bad


def replay_run(reader: str, mmh: Path, path: Path, out: Path) -> dict[str, tuple[int, int]]:
    """(2b), end to end: ``judge.run`` (native) on the converted file with every call answered
    from gw's frozen rows (a summarizer call by its summary, a judge call by gw's pick and
    quote; gw's none after a void stays none), scored by this family's run."""
    suf, layers, _g, _f, _tok, _head = READERS[reader]
    summ = _last_ok(_jsonl(mmh / f"summ_v2{suf}.jsonl"))
    cat = {it["id"]: it["cat"] for it in judge.load_items()}
    rows_all = _last_ok(_jsonl(mmh / JUDGED.format(suf=suf)))
    judged = {"invented": rows_all, "cutoff": rows_all}

    def fake_run_calls(calls, **_kw):
        res: dict[str, dict | None] = {}
        for c in calls:
            iid, unit, stage = c.key.split("|")
            u = unit if unit == "all" else str(int(unit[1:]))
            if stage == "summ":
                r = summ.get((iid, u))
                res[c.key] = {"summary": r["summary"], "concepts": r["concepts"]} if r else None
            else:
                r = judged[cat[iid]].get((iid, u))
                res[c.key] = {"pick": r["pick"], "quote": r.get("quote", "")} if r else None
        return res

    load_all()
    spec = FAMILIES[NAME]
    orig = judge.run_calls
    judge.run_calls = fake_run_calls
    try:
        res = judge.run(
            JudgeArgs(
                readouts=path,
                out=out,
                judge=resolve(spec.judge),
                layers=None if layers == GRID else layers,
                items=None,
                limit=0,
                allow_missing=False,
                concurrency=1,
                rpm=1e9,
                dry_run=False,
                extra={"aggregate": "native"},
            )
        )
    finally:
        judge.run_calls = orig
    got = {}
    for c in ("invented", "cutoff"):
        dec = [r for r in res.rows if r["cat"] == c and r["pass"] is not None]
        got[c] = (sum(bool(r["pass"]) for r in dec), len(dec))
    print(f"[2b run] {reader}: invented {got['invented'][0]}/{got['invented'][1]}, "
          f"cutoff {got['cutoff'][0]}/{got['cutoff'][1]}; value {res.value:.4f}")  # fmt: skip
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gw", required=True, help="the global-workspace checkout")
    ap.add_argument(
        "--mmh", required=True, help="gw's mmh output dir (reads_v2, grid, summ, cjudge)"
    )
    ap.add_argument("--out", default="/root/tmp/mmh-wsb-replay")
    a = ap.parse_args()
    gw, mmh, out = Path(a.gw), Path(a.mmh), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    frozen = {it["id"]: it for it in json.loads((gw / FROZEN_REL).read_text())["items"]}
    items = judge.load_items()
    strings = gw_strings(gw)
    ok = True
    for reader in READERS:
        path = convert(reader, mmh, frozen, items, out)
        layers = READERS[reader][1]
        by = bench_cells(path, layers, out / f"{reader}_judge")
        if reader in PROSE:
            ok &= check_renders(reader, mmh, by, items, strings) == 0
        rows_got, problems = replay(reader, mmh, items)
        if problems:  # fail closed: a flipped or unresolvable pick is a mismatch
            ok = False
            print(f"  {problems} PICKS FLIPPED OR UNRESOLVED {reader}")
        for got in (rows_got, replay_run(reader, mmh, path, out / reader)):
            for cat, want in FROZEN_COUNTS[reader].items():
                if got[cat] != want:
                    ok = False
                    print(f"  COUNT MISMATCH {reader} {cat}: {got[cat]} != {want}")
    print("GATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
