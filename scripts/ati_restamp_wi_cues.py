"""Restamp wrong_intermediate's frozen ATI entry to the ``+wbcues-v2`` instrument (plan 0066 §5.4).

    uv run --no-sync python scripts/ati_restamp_wi_cues.py [--check]

``CUES_VERSION`` adds role cues for templates the registered bank does not use, and every
registered template's cues are byte-identical (``tests/test_refill_wi_cues.py``), so no
registered verdict can change and the 100-item subset stands. The script, offline and
deterministic,

1. recomputes ``ti.bank_fingerprint("wrong_intermediate")`` and refuses unless it equals the
   stored ``bank_sha`` (the bank and the read plan are unchanged);
2. refuses unless the stored instrument is the pre-bump one, i.e. the current instrument with
   ``+<CUES_VERSION>`` removed (only the cues stamp moved);
3. writes the entry with the new instrument, recording the old one under ``restamped_from`` and
   a ``restamp_note`` (the moral_rationale precedent); ids, status, gate and passes are copied
   as is.

Re-running it on an already restamped entry is a no-op. ``--check`` writes nothing and exits 1
when a restamp is still due. No model call, no network."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from wsbench import registry
from wsbench.baselines import text_inversion as ti
from wsbench.evals.wrong_intermediate import prompts as wp

FAMILY = "wrong_intermediate"
NOTE = (
    "plan 0066 §5.4: " + wp.CUES_VERSION + " adds role cues only for templates outside the "
    "registered bank (every registered template's cues byte-identical, "
    "tests/test_refill_wi_cues.py), and no MC or audit call keys on it, so no registered verdict "
    "changes and the subset stands; restamped by scripts/ati_restamp_wi_cues.py, not re-gated"
)


def restamp(
    frozen: dict[str, Any], *, current: str | None = None, bank_sha: str | None = None
) -> dict[str, Any]:
    """``frozen`` with the family's entry restamped to ``current`` (default: the family's gate
    instrument); ``bank_sha`` defaults to the live fingerprint. Raises ``SystemExit`` on a bank
    change or on any instrument move other than the cues stamp."""
    current = current if current is not None else ti.gate_instrument(FAMILY)
    tag = "+" + wp.CUES_VERSION
    if tag not in current:
        raise SystemExit(f"{FAMILY}: the instrument {current!r} has no {tag}; nothing to restamp")
    pre = current.replace(tag, "", 1)
    if FAMILY not in frozen:
        raise SystemExit(f"{FAMILY}: no ATI entry; run the gate first")
    entry = dict(frozen[FAMILY])
    sha = bank_sha if bank_sha is not None else ti.bank_fingerprint(FAMILY)
    if entry.get("bank_sha") != sha:
        raise SystemExit(
            f"{FAMILY}: bank_sha {sha[:12]} != stored {str(entry.get('bank_sha'))[:12]}: the bank "
            "or plan changed; re-gate instead of restamping"
        )
    if entry.get("instrument") == current:
        return frozen  # already restamped
    if entry.get("instrument") != pre:
        raise SystemExit(
            f"{FAMILY}: stored instrument {entry.get('instrument')!r} is not the pre-cues "
            f"{pre!r}: more than the cues stamp moved; re-gate instead of restamping"
        )
    entry["instrument"] = current
    entry["restamped_from"] = pre
    entry["restamp_note"] = NOTE
    return {k: (entry if k == FAMILY else v) for k, v in frozen.items()}


def main(argv: list[str] | None = None, dst: Path = ti.FROZEN) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check", action="store_true", help="write nothing; exit 1 if a restamp is due"
    )
    a = ap.parse_args(argv)
    registry.load_all()
    frozen = json.loads(dst.read_text(encoding="utf-8"))
    out = restamp(frozen, current=ti.gate_instrument(FAMILY))
    if out is frozen:
        print(f"{FAMILY}: already on {frozen[FAMILY]['instrument']}")
        return 0
    if a.check:
        e = out[FAMILY]
        print(f"{FAMILY}: restamp due ({e['restamped_from']} -> {e['instrument']})")
        return 1
    dst.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    e = out[FAMILY]
    print(f"restamped {FAMILY}: {len(e['ids'])} ids, {e['restamped_from']} -> {e['instrument']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
