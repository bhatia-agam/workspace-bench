"""Stage the bank viewer: the original banks plus every adapted model under ``adapted/``, as
static JSON beside the site. Serve the output dir with ``python -m http.server``."""

import json
import shutil
from pathlib import Path
from typing import Any

from wsbench.adapt.subjects import SUBJECTS
from wsbench.item_view import view_item
from wsbench.registry import REPO_ROOT

SITE = Path(__file__).parent / "site"
ORIGINAL = "qwen3.6-27b"

# README §The evals, in its order.
GROUPS: list[tuple[str, list[str]]] = [
    (
        "Basic (adapted from the J-lens paper)",
        [
            "basic_readout_st",
            "multihop_st",
            "multilingual_st",
            "poetry",
            "typo_st",
            "directed_modulation",
            "multilingual",
            "typo",
            "basic_readout",
            "multilingual_multihop",
            "multilingual_typo",
            "multi_concept_directed_modulation",
        ],
    ),
    (
        "Computational",
        [
            "chain_intermediates",
            "buggy_code",
            "arithmetic_intermediates",
        ],
    ),
    ("Association", ["association", "user_modeling", "conjunctive_association"]),
    ("Safety", ["agentic_misalignment", "jailbreak_recognition"]),
    ("Anti-bag-of-features", ["relational_multihop", "role_bound_association"]),
    ("Logical processing", ["moral_rationale"]),
    (
        "Model-specific",
        [
            "introspection",
            "knowledge_cutoff",
            "hinted_cutoff",
            "model_multihop",
        ],
    ),
    ("J-lens comparison", ["jlens_concept_pr"]),
]


def _bank_rel(family: str) -> Path:
    """The family's registered bank path relative to a checkout root (plan 0032 §2.12)."""
    from wsbench.registry import REPO_ROOT, frozen_bank_path

    return frozen_bank_path(family).relative_to(REPO_ROOT)


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def _items(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return raw
    items = raw.get("items") if isinstance(raw, dict) else None
    return items if isinstance(items, list) else []


def _header(raw: Any) -> dict:
    return {k: v for k, v in raw.items() if k != "items"} if isinstance(raw, dict) else {}


def _summary(rows: list[dict], header: dict, report: dict | None) -> dict:
    sel = [r for r in rows if r["selected"]]
    rates = [r["gate"]["rate"] for r in sel if r["gate"] and r["gate"].get("rate") is not None]
    out = {
        "n_items": len(sel),
        "n_candidates": len(rows),
        "n_new": sum(r["origin"] != "original" for r in sel),
        "mean_rate": sum(rates) / len(rates) if rates else None,
        "gate_rule": header.get("gate") if isinstance(header.get("gate"), str) else None,
        "subfamilies": sorted({str(r["subfamily"]) for r in sel if r["subfamily"]})[:8],
    }
    return out | (report or {})


def _family_view(items: list[dict], header: dict, gates: dict | None) -> list[dict]:
    if gates is None:
        return [view_item(it, n) for n, it in enumerate(items)]
    # With a frozen bank, "in the bank" is its own id list; before freezing, the gate verdict.
    in_bank = {str(it.get("id") or it.get("name")) for it in items} if items else None
    rows = []
    for n, rec in enumerate(gates.values()):
        sel = rec["id"] in in_bank if in_bank is not None else bool(rec["gate"].get("pass"))
        rows.append(view_item(rec["item"], n, rec.get("gate"), sel))
    return rows


def _read_gates(path: Path) -> dict[str, dict] | None:
    if not path.exists():
        return None
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            rec = json.loads(line)
            out[str(rec["id"])] = rec  # last record per id wins (re-gates append)
    return out


def build(out: Path, root: Path = REPO_ROOT) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for asset in SITE.iterdir():
        shutil.copy(asset, out / asset.name)
    data = out / "data"
    if data.exists():
        shutil.rmtree(data)
    models: list[dict] = []

    orig = {"key": ORIGINAL, "label": "Qwen3.6-27B (original banks)", "families": {}}
    for _group, fams in GROUPS:
        for fam in fams:
            path = root / _bank_rel(fam)
            if not path.exists():
                continue
            raw = _load(path)
            rows = _family_view(_items(raw), _header(raw), None)
            _write(data / ORIGINAL / f"{fam}.json", {"family": fam, "items": rows})
            orig["families"][fam] = _summary(rows, _header(raw), {"status": "original"})
    models.append(orig)

    for mdir in sorted(p for p in (root / "adapted").glob("*") if p.is_dir()):
        report = _load(mdir / "report.json") if (mdir / "report.json").exists() else {}
        subject = SUBJECTS.get(mdir.name)
        label = report.get("label") or (subject.label if subject else mdir.name)
        model = {"key": mdir.name, "label": label, "families": {}}
        model["meta"] = {k: v for k, v in report.items() if k != "families"}
        for _group, fams in GROUPS:
            for fam in fams:
                bank, gates = mdir / f"{fam}.json", _read_gates(mdir / "gate" / f"{fam}.jsonl")
                if not bank.exists() and gates is None:
                    continue
                raw = _load(bank) if bank.exists() else {}
                rows = _family_view(_items(raw), _header(raw), gates)
                _write(data / mdir.name / f"{fam}.json", {"family": fam, "items": rows})
                fam_report = dict((report.get("families") or {}).get(fam) or {})
                n_orig = len(_items(_load(root / _bank_rel(fam))))
                orig_rows = [r for r in (gates or {}).values() if r.get("origin") == "original"]
                fam_report.setdefault("target", n_orig)
                fam_report.setdefault("n_original", n_orig)
                if orig_rows:
                    n_pass = sum(bool(r["gate"].get("pass")) for r in orig_rows)
                    fam_report.setdefault("n_original_pass", n_pass)
                fam_report.setdefault("status", "profiled" if not bank.exists() else "partial")
                model["families"][fam] = _summary(rows, _header(raw), fam_report)
        models.append(model)

    index = {"groups": [{"title": t, "families": f} for t, f in GROUPS], "models": models}
    _write(data / "index.json", index)
    return index


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False))


def main(out: str = "outputs/viewer") -> None:
    index = build(Path(out))
    n = sum(len(m["families"]) for m in index["models"])
    print(f"viewer: {len(index['models'])} models, {n} model-family views -> {out}")
    print(f"serve:  python -m http.server 8765 -d {out}")


if __name__ == "__main__":
    main()
