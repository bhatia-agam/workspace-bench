"""Offline evidence for plan 0045 (introspection), no model and no API call.

``paired`` (default): the source repo's committed per-cell verdicts (s3d.rl600 O-lens and J-lens,
every unit, all 11 layers x the full grid; ``grid_verdicts.json``) run through THIS repo's v2
scoring code: ``judge.units`` on bank v2, ``judge._row`` (accept sets A(c)), ``judge.pair`` (the
gaussian twin's judge verdict) and ``judge.summarize``. The source verdicts have no
quotes, so the "same as" group check (``quote_options`` inside A(c)) cannot be applied
offline (every quote is taken as naming only the pick); the v2 menu ("also" / "same as") and
rubric only act in the LLM phase. ``--v1`` scores with A(c) = {c} (today's rule).

    uv run --no-sync python scripts/introspection_offline_evidence.py [--out evidence.json]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wsbench.evals.model_specific.introspection import judge  # noqa: E402

SRC = Path("/workspace/gw-introspection-inject")
VERDICTS = (
    SRC / "evals/workspace-bench/hillclimbing_evals/multi_token/introspection_inject/readouts"
    "/grid_verdicts.json"
)


# ---------------------------------------------------------------- paired (source verdicts)


def _bank(v1: bool) -> dict[str, Any]:
    bank = judge.load()
    if v1:
        bank = {**bank, "equivalents": {}}
        bank["concepts"] = [
            {**c, "surface_forms": [c["word"]], "extra_forms": []} for c in bank["concepts"]
        ]
    return bank


def paired(reader: str, *, v1: bool = False, beta: float = 4.0, kind: str = "protocol") -> dict:
    bank = _bank(v1)
    entries = json.loads(VERDICTS.read_text(encoding="utf-8"))["entries"]
    verdicts = {e["item"]: e for e in entries if e["reader"] == reader}
    pool = [
        it
        for it in bank["items"]
        if it["kind"] == "inject" and it["prompt_kind"] == kind and float(it["beta"]) == beta
    ]
    scope = pool + judge._twin_items(bank, pool)
    us = judge.units(bank, scope)
    for u in us:  # the headline flag of this sub-headline (so summarize reports it)
        u["headline"] = u["kind"] == "inject"
    rows = []
    for u in us:
        e = verdicts.get(u["id"])
        if e is None:
            continue
        g = e["regions"]["grid"]
        cells: dict[tuple[int, int], tuple[str, str] | None] = {}
        for pi, pos in enumerate(g["positions"]):
            for li, layer in enumerate(g["layers"]):
                v = g["picks"][pi][li]
                cells[(layer, pos)] = None if v < 0 else (e["options"][v], "")
        rows.append(judge._row(u, cells))
    judge.pair(rows)
    s = judge.summarize(rows, list(range(20, 61, 4)))
    key = f"{kind}|b{beta:g}"
    sub = s["subheadlines"][key]
    inj = [r for r in rows if r["kind"] == "inject"]
    return {
        "reader": reader,
        "rule": "v1 (A(c) = {c})" if v1 else "v2 (A(c), Q12)",
        "subheadline": key,
        "n": len(inj),
        "unpaired": sub["unpaired"],
        "paired": sub["rate"],
        "paired_all_twins": sub["paired_all_twins"],
        "beta0_prior_rate": sub["beta0_prior_rate"],
        "n_twin_missing": sub["n_twin_missing"],
        "floors": {k: s["floors"][key][k] for k in ("beta0", "cross", "gaussian")},
        "unpaired_pass": sorted(r["concept"] for r in inj if r["pass_unpaired"]),
        "voided": [
            {
                "id": r["id"],
                "gaussian_judge": r["twin_hits"]["gaussian"]["judge"],
            }
            for r in inj
            if r["pass_unpaired"] and r["pass"] is False
        ],
    }


def cmd_paired(a: argparse.Namespace) -> dict:
    out: dict[str, Any] = {"source_verdicts": str(VERDICTS), "tables": []}
    for reader in ("olens", "jlens"):
        for v1 in (True, False):
            out["tables"].append(paired(reader, v1=v1))
    for t in out["tables"]:
        print(
            f"{t['reader']:6s} {t['rule']:16s} n={t['n']} unpaired={t['unpaired']:.3f} "
            f"PAIRED={t['paired']:.3f} all-twins={t['paired_all_twins']:.3f} "
            f"beta0-prior={t['beta0_prior_rate']:.3f} floors={t['floors']} "
            f"voided={len(t['voided'])}"
        )
    v1o, v2o = out["tables"][0], out["tables"][1]
    v1j, v2j = out["tables"][2], out["tables"][3]
    out["near_duplicate_new_passes"] = {
        "olens": sorted(set(v2o["unpaired_pass"]) - set(v1o["unpaired_pass"])),
        "jlens": sorted(set(v2j["unpaired_pass"]) - set(v1j["unpaired_pass"])),
    }
    print("new unpaired passes from A(c):", out["near_duplicate_new_passes"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    out = cmd_paired(a)
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
