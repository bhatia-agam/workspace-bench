"""Plan 0083: drop arithmetic's ``frac`` variant from the registered bank (v1 -> v2), the ATI file,
the floors and every adapted set, offline (``uv run python scripts/drop_frac_0083.py``; re-runnable:
each part runs only while its input still has the variant)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from wsbench import reads
from wsbench.results import bootstrap_ci

REPO = Path(__file__).resolve().parents[1]
FAM = "arithmetic_intermediates"
VARIANT = "frac"
V1 = REPO / "evals" / FAM / "items.json"
V2 = REPO / "evals" / FAM / "items_v2.json"
OLD_PLAN_SHA = "ad92c18203e8c526ef3a4e02d80fc0a17063ee1d1a5cd3584d6992b198b8e715"
AT = "2026-11-08"
NOTE = (
    "removed 2026-11-08 (Camila, plan 0083): (p / q) * (p*q*k) scores the decimal p/q, but q "
    "cancels, so every model computes p*q*k / q first and no reader ever names p/q; the bank "
    "gated on the final answer only"
)
FLOOR_FILES = ("floors/floors.json", "floors/prompt_only_summary.json")


def dump(path: Path, obj: Any, indent: int | None) -> None:
    text = json.dumps(obj, indent=indent, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def indent_of(path: Path) -> int | None:
    """The file's own JSON indent (None = one line), so a rewrite keeps its layout."""
    raw = path.read_text(encoding="utf-8")
    if "\n" not in raw.strip():
        return None
    line = raw.split("\n", 2)[1]
    return len(line) - len(line.lstrip(" ")) or 1


def plan_rows(env: dict[str, str]) -> list[dict]:
    """The family's ``wsbench plan`` rows in a fresh process (no plan cache crosses files)."""
    code = (
        "import json; from wsbench import readplan; "
        f"print(json.dumps([s.row() for s in readplan.plan({FAM!r}, layers=None)]))"
    )
    base = {k: v for k, v in os.environ.items() if not k.startswith("WSB_")}
    out = subprocess.run(
        [sys.executable, "-c", code], env={**base, **env}, cwd=REPO, check=True,
        capture_output=True, text=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def split(items: list[dict]) -> tuple[list[dict], set[str]]:
    """(kept items, dropped ids); every kept item's null_set / pair must name a kept item."""
    gone = {it["name"] for it in items if it["variant"] == VARIANT}
    kept = [it for it in items if it["variant"] != VARIANT]
    for it in kept:
        refs = set(it.get("null_set") or []) | ({it["pair"]} if it.get("pair") else set())
        if refs & gone:
            raise SystemExit(f"{it['name']} references dropped items {sorted(refs & gone)}")
    return kept, gone


def drop_header(header: dict) -> None:
    header["variants"].pop(VARIANT, None)
    header["removed_variants"] = sorted({*header.get("removed_variants", []), VARIANT})
    header.setdefault("removed_variant_notes", {})[VARIANT] = NOTE


# ---------------------------------------------------------------- registered bank


def registered() -> dict[str, Any]:
    if not V1.exists():
        raise SystemExit(f"{V1.relative_to(REPO)} is gone: plan 0083 already applied")
    raw = json.loads(V1.read_text(encoding="utf-8"))
    old_rows = plan_rows({f"WSB_BANK_FILE_{FAM.upper()}": str(V1)})
    if reads.plan_sha_rows(old_rows) != OLD_PLAN_SHA:
        raise SystemExit("the 596-item plan_sha moved; re-check before dropping")
    kept, gone = split(raw["items"])
    new = {k: v for k, v in raw.items() if k != "items"}
    drop_header(new)
    new["source"] = f"{new['source']}; 13 since plan 0083 removed frac (2026-11-08)"
    new["bank_version"] = 2
    new["items"] = kept
    dump(V2, new, indent_of(V1))
    new_rows = plan_rows({})  # the registered spec now points at items_v2.json
    step = reads.lineage_step(old_rows, new_rows)
    if step is None or sorted(step["dropped"]) != sorted(gone):
        raise SystemExit(f"registered lineage step not drop-only: {step}")
    step["at"] = AT
    new = {k: v for k, v in new.items() if k != "items"}
    new["plan_lineage"] = [step]
    new["items"] = kept
    dump(V2, new, indent_of(V1))
    V1.unlink()
    print(f"registered: {len(raw['items'])} -> {len(kept)} ({len(gone)} frac)", step["to"])
    return {"n_before": len(raw["items"]), "n_after": len(kept), "gone": gone}


# ---------------------------------------------------------------- ATI file


def ati(gone: set[str]) -> None:
    sys.path.insert(0, str(REPO / "scripts"))
    from ati_rederive import rederive

    from wsbench.baselines import text_inversion as ti

    path = REPO / "evals" / "baselines" / "anti_text_inversion.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    before = json.loads(json.dumps(data))
    e = data[FAM]
    all_ids = list(e["status"])
    p3 = {a: round(sum(e["status"][i][k] == "solved" for i in all_ids) / len(all_ids), 4)
          for k, a in enumerate(e["pass_at_3"])}  # fmt: skip
    p1 = {a: ti._pass_at_1(dp, all_ids, ti.DRAWS) for a, dp in e["draw_pass"].items()}
    if p3 != e["pass_at_3"] or p1 != e["pass_at_1"]:  # the recompute reproduces the entry first
        raise SystemExit(f"ATI pass@k do not reproduce: {p1} {p3}")
    status = {i: s for i, s in e["status"].items() if i not in gone}
    ids = list(status)
    e["status"] = status
    e["draw_pass"] = {
        a: {i: v for i, v in dp.items() if i not in gone} for a, dp in e["draw_pass"].items()
    }
    e["n_bank"] = len(ids)
    e["pass_at_1"] = {a: ti._pass_at_1(dp, ids, ti.DRAWS) for a, dp in e["draw_pass"].items()}
    e["pass_at_3"] = {  # its keys are the panel in status order
        a: round(sum(status[i][k] == "solved" for i in ids) / max(1, len(ids)), 4)
        for k, a in enumerate(e["pass_at_3"])
    }
    if isinstance(e.get("reader_routes"), dict):
        for a, r in e["reader_routes"].items():
            if isinstance(r, dict) and set(r) & gone:
                e["reader_routes"][a] = {i: v for i, v in r.items() if i not in gone}
    e["bank_sha"] = ti.bank_fingerprint(FAM)
    e["rederived_from"] = (
        f"{e.get('rederived_from')} -> panel-v2 over the 596-item bank -> plan 0083: the 116 "
        "frac items dropped (kept items' verdicts unchanged)"
    )
    out = rederive(data)
    for k, v in out.items():
        if k != FAM and v != before.get(k):
            raise SystemExit(f"ATI rederive moved another entry: {k}")
    dump(path, out, indent_of(path))
    a = out[FAM]
    print(f"ATI: n_bank {a['n_bank']} n_ati {a['n_ati']} n_inv {a['n_invertible']}")


# ---------------------------------------------------------------- floors


def recompute(e: dict, gone: set[str]) -> int:
    """A floor entry with a per-item ``decided`` map, the frac ids dropped. Returns k dropped."""
    dec = e["decided"]
    k_dec = sum(1 for i in dec if i in gone)
    unserved = [i for i in e.get("digest_unserved") or [] if i not in gone]
    k_uns = len(e.get("digest_unserved") or []) - len(unserved)
    k = len(gone)  # every frac id of the set was in scope (n_items == the bank)
    if e.get("n_refused_ask"):
        raise SystemExit("an entry with ask refusals has no per-id record; cannot recompute")
    kept = {i: v for i, v in dec.items() if i not in gone}
    vals = [1.0 if v else 0.0 for v in kept.values()]
    e["decided"] = kept
    e["n_items"] = e["n_items"] - k
    e["n_items_decided"] = len(kept)
    e["rate"] = sum(vals) / len(vals)
    e["ci95"] = list(bootstrap_ci(vals))
    c = e.get("counts") or {}
    if "n_expected_cells" in c:
        c["n_expected_cells"] -= k
    if "n_unjudged_cells" in c:
        c["n_unjudged_cells"] = e["n_items"] - len(kept)
    if "digest_unserved" in e:
        e["digest_unserved"] = unserved
    if "value" in e:  # the po-opus-v1 fields (prompt_only._po_opus_entries)
        n_ref = len(unserved)
        share = n_ref / e["n_items"] if e["n_items"] else 0.0
        e.update(
            value=e["rate"], n=len(kept), ci=e["ci95"], n_refused=n_ref, n_refused_digest=n_ref,
            refusal_share=share, label=f"Opus 5.5 ({n_ref} refused)", not_measurable=share > 0.2,
        )  # fmt: skip
    e["plan_0083"] = {
        "dropped_frac": k,
        "dropped_decided": k_dec,
        "dropped_unserved": k_uns,
        "recomputed_from": "decided",
        "note": "counts.n_empty_cells is not split per item and is kept as measured",
    }
    return k


def floors(path: Path, gone: set[str], k_set: int) -> list[str]:
    """Every arithmetic floor entry in ``path``: recomputed when it has ``decided``, else marked."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    done: list[str] = []

    def walk(x: Any, where: str) -> None:
        if not isinstance(x, dict):
            return
        for key, v in x.items():
            if key == FAM and isinstance(v, dict) and ("rate" in v or "value" in v):
                if "decided" in v:
                    recompute(v, gone)
                    done.append(f"{where}: recomputed")
                else:
                    v["plan_0083"] = {
                        "stale": f"measured on the pre-0083 bank including {k_set} frac items; "
                        "no per-item record, not recomputed"
                    }
                    done.append(f"{where}: marked stale")
            else:
                walk(v, f"{where}/{key}")

    walk(data, path.name)
    dump(path, data, indent_of(path))
    return done


# ---------------------------------------------------------------- adapted sets


def adapted(model_dir: Path, k_reg: int) -> dict[str, Any] | None:
    from wsbench.adapt.gen_arith import null_sets
    from wsbench.adapt.run import plan_rows_under

    bank = model_dir / f"{FAM}.json"
    raw = json.loads(bank.read_text(encoding="utf-8"))
    kept, gone = split(raw["items"])
    if VARIANT not in raw.get("variants", {}):
        return None  # done already (the script is re-runnable over the sets)
    if not gone:  # the variant is in the header but no item shipped: header only, plan unchanged
        drop_header(raw)
        dump(bank, raw, indent_of(bank))
        rep_path = model_dir / "report.json"
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        n = len(raw["items"])
        e = rep["families"][FAM]
        before = {k: e.get(k) for k in ("target", "n_original", "n_original_gated")}
        e["target"] = k_reg
        for key in ("n_original", "n_original_gated"):
            if isinstance(e.get(key), int):
                e[key] = k_reg
        for key, val in (("bank", f"evals/{FAM}/items_v2.json"), ("bank_version", 2)):
            if key in e:
                before[key] = e[key]
                e[key] = val
        e["plan_0083"] = {"dropped_frac": 0, "before": n, "after": n, "fields_before": before}
        dump(rep_path, rep, indent_of(rep_path))
        return {"before": n, "after": n, "frac": 0, "floors": [], "header_only": True}
    old_rows = plan_rows_under(model_dir, FAM)
    if old_rows is None:
        raise SystemExit(f"{model_dir.name}: no plan rows")
    pools = null_sets([json.loads(json.dumps(it)) for it in kept])  # on copies: the bank
    small = [n for n, s in pools.items() if s < 8]
    if small:
        raise SystemExit(f"{model_dir.name}: kept items with a null pool under 8: {small[:5]}")
    new = {k: v for k, v in raw.items() if k != "items"}
    drop_header(new)
    new["items"] = kept
    dump(bank, new, indent_of(bank))
    new_rows = plan_rows_under(model_dir, FAM)
    step = reads.lineage_step(old_rows, new_rows or [])
    if step is None or sorted(step["dropped"]) != sorted(gone):
        raise SystemExit(f"{model_dir.name}: lineage step not drop-only: {step}")
    step["at"] = AT
    rep_path = model_dir / "report.json"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    e = rep["families"][FAM]
    e[reads.LINEAGE_KEY] = [*(e.get(reads.LINEAGE_KEY) or []), step]
    n_gen = sum(
        1 for it in raw["items"]
        if it["name"] in gone and (it.get("adapt") or {}).get("origin") == "generated"
    )  # fmt: skip
    before = {k: e.get(k) for k in ("n_items", "target", "n_new", "n_original",
                                    "n_original_gated", "n_original_pass")}  # fmt: skip
    e["n_items"] = len(kept)
    e["target"] = k_reg
    if isinstance(e.get("n_new"), int):
        e["n_new"] -= n_gen
    for key in ("n_original", "n_original_gated"):  # every registered original was gated
        if isinstance(e.get(key), int):
            e[key] = k_reg
    if isinstance(e.get("n_original_pass"), int):  # every shipped original passed its gate
        e["n_original_pass"] = min(e["n_original_pass"] - (len(gone) - n_gen), k_reg)
    if "bank" in e:
        e["bank"] = f"evals/{FAM}/items_v2.json"
    if "bank_version" in e:
        e["bank_version"] = 2
    e["plan_0083"] = {
        "dropped_frac": len(gone),
        "dropped_generated": n_gen,
        "dropped_original": len(gone) - n_gen,
        "before": len(raw["items"]),
        "after": len(kept),
        "fields_before": before,
        "n_original_pass": "minus the frac originals this set shipped (every shipped original "
        "passed), capped at n_original: an upper bound, since frac originals that passed but did "
        "not ship are not known here (box-local gate logs)",
    }
    dump(rep_path, rep, indent_of(rep_path))
    fl = []
    for rel in FLOOR_FILES:
        fl += floors(model_dir / rel, gone, len(gone))
    return {"before": len(raw["items"]), "after": len(kept), "frac": len(gone), "floors": fl,
            "status": e.get("status"), "plan_sha": step["to"]}  # fmt: skip


OLD_PV = "arith-free-2026-10-30+exact-int+keys-union+generic-r7"


def restamp(path: Path) -> None:
    """The recomputed stock summary floor carries the bank-v2 result stamp (``PROMPT_VERSION``
    gained ``+bank-v2``), so it is drawn beside bank-v2 rows only."""
    from wsbench.evals.computational.arithmetic_intermediates.prompts import PROMPT_VERSION

    if not PROMPT_VERSION.startswith(OLD_PV + "+bank-v2"):
        raise SystemExit(f"unexpected PROMPT_VERSION {PROMPT_VERSION!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    e = data[FAM]
    if not str(e.get("instrument", "")).startswith(OLD_PV + "+digest"):
        raise SystemExit(f"unexpected floor instrument {e.get('instrument')!r}")
    e["instrument"] = PROMPT_VERSION + e["instrument"][len(OLD_PV) :]
    dump(path, data, indent_of(path))
    print("  stock floor restamped", e["instrument"])


def main() -> None:
    if V1.exists():
        reg = registered()
        ati(reg["gone"])
        base = REPO / "evals" / "baselines"
        for name in ("prompt_only_summary.json", "prompt_only.json"):
            for line in floors(base / name, reg["gone"], len(reg["gone"])):
                print("  stock floor", line)
        restamp(base / "prompt_only_summary.json")
    else:  # registered part applied: only sets still carrying the variant are processed
        reg = {"n_after": len(json.loads(V2.read_text(encoding="utf-8"))["items"])}
    summary = {}
    for d in sorted((REPO / "adapted").iterdir()):
        if (d / f"{FAM}.json").exists():
            r = adapted(d, reg["n_after"])
            if r is not None:
                summary[d.name] = r
                print(d.name, r)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
