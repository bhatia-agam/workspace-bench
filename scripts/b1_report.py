"""Plan 0012 §1.4 readout: v1 vs v2 bank judge with the random null and near-miss foils, per
family, from two ``wsbench run`` output dirs; plus the flip lists the audit samples from.

A dev script, not part of the package.
"""

import argparse
import json
import random
from pathlib import Path
from typing import Any

from wsbench.results import read_results

BANK = ["association", "basic_readout", "multihop", "multilingual", "poetry", "typo"]
MT = [
    "basic_readout_mt",
    "multihop_mt",
    "multilingual_mt",
    "multilingual_multihop",
    "multilingual_typo",
    "typo_mt",
]


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}"


def ci(c: list[float] | None) -> str:
    return "" if not c else f" [{100 * c[0]:.0f}, {100 * c[1]:.0f}]"


def load(d: Path, fam: str) -> Any | None:
    p = d / fam
    return read_results(p) if (p / "results.json").exists() else None


def rows(r: Any) -> dict[str, bool | None]:
    return {row["id"]: row["pass"] for row in r.rows}


def table(v1: Path, v2: Path) -> list[str]:
    out = [
        "| family | judge | pass | random null | near-miss foil | lift (null) | lift (foil) "
        "| foil credits surface-free |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for fam in BANK:
        for tag, d in (("v1", v1), ("v2", v2)):
            r = load(d, fam)
            if r is None:
                out.append(f"| {fam} | {tag} | (not run) | | | | | |")
                continue
            n = r.extras.get("nulls", {})
            out.append(
                f"| {fam} | {tag} | {pct(r.value)}{ci(r.ci95)} | {pct(n.get('null_rate'))}"
                f"{ci(n.get('null_ci95'))} | {pct(n.get('foil_rate'))}{ci(n.get('foil_ci95'))} "
                f"| {pct(n.get('lift_null'))} | {pct(n.get('lift_foil'))} "
                f"| {pct(n.get('foil_surface_free_share'))} (n={n.get('foil_n_credits', 0)}) |"
            )
    return out


def mt_table(v1: Path) -> list[str]:
    out = ["| family | pass | random null | lift |", "|---|---|---|---|"]
    for fam in MT:
        r = load(v1, fam)
        if r is None:
            continue
        n = r.extras.get("nulls", {})
        out.append(
            f"| {fam} | {pct(r.value)} | {pct(n.get('null_rate'))}{ci(n.get('null_ci95'))} "
            f"| {pct(n.get('lift_null'))} |"
        )
    return out


def flips(v1: Path, v2: Path) -> dict[str, list[dict[str, Any]]]:
    """fail->pass and pass->fail items between the two instruments, with v2's quote."""
    up: list[dict[str, Any]] = []
    down: list[dict[str, Any]] = []
    for fam in BANK:
        a, b = load(v1, fam), load(v2, fam)
        if a is None or b is None:
            continue
        ra, rb = rows(a), rows(b)
        brow = {row["id"]: row for row in b.rows}
        arow = {row["id"]: row for row in a.rows}
        for i in ra:
            if ra[i] is False and rb.get(i) is True:
                q = [v for v in brow[i]["layers"].values() if v.get("expressed")]
                up.append({"family": fam, "id": i, "targets": brow[i]["targets"], "v2": q[:2]})
            elif ra[i] is True and rb.get(i) is False:
                q = [v for v in arow[i]["layers"].values() if v.get("expressed")]
                down.append({"family": fam, "id": i, "targets": arow[i]["targets"], "v1": q[:2]})
    return {"fail_to_pass": up, "pass_to_fail": down}


def foil_credits(d: Path, n: int, seed: int) -> list[dict[str, Any]]:
    """A stratified sample of foil credits (item, foil, layers) for the leniency audit."""
    out: list[dict[str, Any]] = []
    for fam in BANK:
        r = load(d, fam)
        if r is None:
            continue
        for i, tags in r.extras.get("nulls", {}).get("items", {}).items():
            for tag, v in tags.items():
                if tag.startswith("foil:") and v.get("pass"):
                    out.append(
                        {"family": fam, "id": i, "foil": v["targets"], "layers": v["layers"]}
                    )
    rng = random.Random(seed)
    rng.shuffle(out)
    by_fam: dict[str, list[dict[str, Any]]] = {}
    for c in out:
        by_fam.setdefault(c["family"], []).append(c)
    picked: list[dict[str, Any]] = []
    while len(picked) < n and any(by_fam.values()):
        for fam in list(by_fam):
            if by_fam[fam] and len(picked) < n:
                picked.append(by_fam[fam].pop())
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", type=Path, required=True)
    ap.add_argument("--v2", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    md = ["## Bank families", "", *table(a.v1, a.v2), "", "## Regex families (v1 run; $0)", ""]
    md += mt_table(a.v1)
    (a.out / "tables.md").write_text("\n".join(md) + "\n")
    f = flips(a.v1, a.v2)
    (a.out / "flips.json").write_text(json.dumps(f, ensure_ascii=False, indent=1))
    for tag, d in (("v1", a.v1), ("v2", a.v2)):
        fc = foil_credits(d, 60, seed=0)
        (a.out / f"foil_credits_{tag}.json").write_text(
            json.dumps(fc, ensure_ascii=False, indent=1)
        )
    print("\n".join(md))
    print(f"\nflips: {len(f['fail_to_pass'])} fail->pass, {len(f['pass_to_fail'])} pass->fail")


if __name__ == "__main__":
    main()
