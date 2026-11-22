"""Shortfalls and a mechanical audit of one model's adapted question set.

What it checks: that an adapted set is complete and clean before it ships.

    python scripts/adapt_set_audit.py deficits <model>   # per eval: chosen / target, new, short
    python scripts/adapt_set_audit.py audit <model>      # per frozen bank: lint, duplicates, gate

Inputs: the adapt store of ``<model>`` (``wsbench.adapt.store``: its gate records, pending
candidates and the frozen banks in ``adapted/<model>/``), and the model's tokenizer.

Outputs: ``deficits`` only prints. ``audit`` prints the table and writes it to
``adapted/<model>/SET_AUDIT.md``.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wsbench.adapt import families as fams
from wsbench.adapt import run, store
from wsbench.adapt.lint import lint


def deficits(model: str) -> dict:
    out = {}
    for f in fams.FAMILIES:
        rows = run.live_rows(model, f)
        _h, orig = store.original_bank(f)
        chosen = run.select(f, rows, len(orig), run.quotas(f, orig)) if rows else []
        orig_pass = sum(r["origin"] == "original" for r in chosen)
        new = len(chosen) - orig_pass
        pend = len(store.pending(model, f))
        out[f] = {"target": len(orig), "chosen": len(chosen), "orig_pass": orig_pass, "new": new,
                  "short": len(orig) - len(chosen), "pending": pend}  # fmt: skip
        print(f"{f:28s} {len(chosen):4d}/{len(orig):<4d} orig {orig_pass:4d} new {new:3d} "
              f"short {len(orig) - len(chosen):4d} pending {pend}")  # fmt: skip
    return out


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.casefold()).strip()


def audit(model: str) -> None:
    d = store.model_dir(model)
    report = []
    for p in sorted(d.glob("*.json")):
        if p.stem in ("report",) or p.stem.endswith("capture_rows"):
            continue
        raw = json.loads(p.read_text())
        items = raw["items"] if isinstance(raw, dict) else raw
        fam = p.stem
        gated = store.gated(model, fam) if fam in fams.FAMILIES else {}
        n_lint = n_gate_bad = 0
        probs = Counter()
        for it in items:
            if fam in fams.FAMILIES:
                ps = lint(fam, it)
                n_lint += bool(ps)
                probs.update(x.split(":")[0] for x in ps)
                rec = gated.get(str(it.get("id") or it.get("name")))
                n_gate_bad += not (rec and rec["gate"].get("pass"))
        stim = Counter(
            _norm(str(it.get("prompt") or it.get("stimulus") or it.get("statement") or ""))
            for it in items
        )
        dup_p = sum(c - 1 for s, c in stim.items() if s and c > 1)
        lat = Counter(_norm(str((it.get("intermediates") or [""])[0])) for it in items)
        dup_l = sum(c - 1 for s, c in lat.items() if s and c > 1) if fam in run.UNIQUE_LATENT else 0
        new = sum((it.get("adapt") or {}).get("origin", "original") != "original" for it in items)
        line = (f"| {fam} | {len(items)} | {new} | {n_lint} {dict(probs) or ''} | {dup_p} "
                f"| {dup_l} | {n_gate_bad} |")  # fmt: skip
        report.append(line)
        print(line)
    hdr = ["| family | items | new | lint fails | dup prompts | dup latents | not gate-passed |",
           "|---|---|---|---|---|---|---|"]  # fmt: skip
    (d / "SET_AUDIT.md").write_text(
        f"# Mechanical audit: adapted/{model}\n\nlint = wsbench.adapt.lint on the frozen item; "
        "dup latents only for unique-latent families; gate = last gate record passes.\n\n"
        + "\n".join(hdr + report) + "\n")  # fmt: skip


COMMANDS = {"deficits": deficits, "audit": audit}

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if {"-h", "--help"} & set(sys.argv[1:]) else 2)
    COMMANDS[sys.argv[1]](sys.argv[2])
