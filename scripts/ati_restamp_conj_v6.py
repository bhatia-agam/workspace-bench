"""Restamp conjunctive_association's frozen ATI entry for comp-v6 / bank v6, keeping its ids.

    uv run python scripts/ati_restamp_conj_v6.py [--check] [--frozen PATH]

The strict ATI subset is frozen (``ati-subset-v2``, plan 0085; Camila: do not change it), so the
entry keeps its 26 ids, its panel statuses and its draw record exactly as gated under comp-v5 on
bank v4. Only the two stale fields move: ``instrument`` (comp-v5 -> the live gate instrument) and
``bank_sha`` (bank v4's fingerprint -> bank v6's: the items gained options, nothing the panel
read changed). The script

1. recomputes bank v4's fingerprint (``WSB_BANK_FILE_CONJUNCTIVE_ASSOCIATION`` = items_v4.json)
   and asserts it equals the stored ``bank_sha``: the entry was gated on that bank, unedited;
2. asserts bank v6 keeps every v4 id with the same stimulus, question and gold (the panel's
   input and the target are unchanged), and that the ids are the 26 of record (``IDS_SHA256``);
3. writes ``instrument`` / ``bank_sha`` and records the old values under ``restamped_from``
   together with ``EVIDENCE`` (evals/association/conjunctive_association/ati_restamp_v6.json):
   the re-judge of a stored panel under the new instrument, i.e. what a full re-gate would have
   changed.

No model call. ``--check`` exits 1 unless the frozen entry is exactly this restamp of the
comp-v5 entry (and ``scripts/ati_rederive.py --check`` still holds: the statuses are untouched).
A full re-gate (``wsbench text-inversion stage=gate``) is the supported path that MOVES the ids;
this script is the path that keeps them, and it says so in the entry.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from wsbench import reads, registry
from wsbench.baselines import text_inversion as ti

FAMILY = "conjunctive_association"
ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "evals/association/conjunctive_association/items_v4.json"
EVIDENCE = ROOT / "evals/association/conjunctive_association/ati_restamp_v6.json"
BANK_ENV = "WSB_BANK_FILE_CONJUNCTIVE_ASSOCIATION"
OLD_INSTRUMENT = "comp-v5"
NEW_INSTRUMENT = "comp-v6"
N_IDS = 26
IDS_SHA256 = "2c301902b8878e3c828c38866c618d91a9f4aeec8ceadb1d151d07773c541a26"
KEEP = ("id", "stimulus", "asked_question", "gold_label", "read_position")


def ids_sha(ids: list[str]) -> str:
    return hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest()


def fingerprint_of(bank: Path | None) -> str:
    """``ti.bank_fingerprint`` with the family pointed at ``bank`` (None: the registered bank)."""
    old = os.environ.pop(BANK_ENV, None)
    try:
        if bank is not None:
            os.environ[BANK_ENV] = str(bank)
        reads._specs.cache_clear()  # the plan is cached per bank environment
        return ti.bank_fingerprint(FAMILY)
    finally:
        os.environ.pop(BANK_ENV, None)
        if old is not None:
            os.environ[BANK_ENV] = old
        reads._specs.cache_clear()


def same_inputs() -> None:
    v4 = {it["id"]: it for it in json.loads(V4.read_text(encoding="utf-8"))}
    cur = json.loads(registry.bank_path(FAMILY).read_text(encoding="utf-8"))
    if [it["id"] for it in cur] != list(v4):
        raise SystemExit(f"{FAMILY}: the registered bank's ids are not bank v4's; re-gate")
    for it in cur:
        if any(it.get(k) != v4[it["id"]].get(k) for k in KEEP):
            raise SystemExit(f"{FAMILY}: {it['id']} differs from bank v4 on a panel input; re-gate")


def restamp(entry: dict[str, Any]) -> dict[str, Any]:
    """The comp-v6 / bank v6 entry of a comp-v5 / bank v4 ``entry`` (ids and statuses kept)."""
    if entry.get("instrument") != OLD_INSTRUMENT or "restamped_from" in entry:
        raise SystemExit(f"{FAMILY}: the entry is not the {OLD_INSTRUMENT} entry of record")
    if ti.gate_instrument(FAMILY) != NEW_INSTRUMENT:
        raise SystemExit(f"{FAMILY}: the live instrument is not {NEW_INSTRUMENT}; re-gate")
    if fingerprint_of(V4) != entry.get("bank_sha"):
        raise SystemExit(f"{FAMILY}: the stored bank_sha is not bank v4's fingerprint; re-gate")
    if len(entry["ids"]) != N_IDS or ids_sha(entry["ids"]) != IDS_SHA256:
        raise SystemExit(f"{FAMILY}: the ids are not the {N_IDS} of record")
    same_inputs()
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    out = dict(entry)
    out["instrument"] = NEW_INSTRUMENT
    out["bank_sha"] = fingerprint_of(None)
    out["restamped_from"] = {
        "instrument": entry["instrument"],
        "bank_sha": entry["bank_sha"],
        "why": "comp-v6 on bank v6 (2026-11-20): every part of an option required, shared-axis "
        "distractors added; the strict ATI subset is frozen (ati-subset-v2), so the ids, "
        "statuses and draw record are the comp-v5 gate's, NOT re-derived under comp-v6",
        "evidence": evidence["summary"],
        "evidence_file": str(EVIDENCE.relative_to(ROOT)),
    }
    return out


def check(entry: dict[str, Any]) -> list[str]:
    """Why ``entry`` is not this script's restamp (empty = it is)."""
    rf = entry.get("restamped_from")
    if not isinstance(rf, dict):
        return ["no restamped_from record"]
    before = {k: v for k, v in entry.items() if k != "restamped_from"}
    before.update(instrument=rf.get("instrument"), bank_sha=rf.get("bank_sha"))
    try:
        again = restamp(before)
    except SystemExit as e:
        return [str(e)]
    return [] if again == entry else ["the entry differs from a fresh restamp"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--frozen", type=Path, default=None)
    a = ap.parse_args()
    registry.load_all()
    path = a.frozen or ti.FROZEN
    frozen = json.loads(path.read_text(encoding="utf-8"))
    if a.check:
        why = check(frozen[FAMILY])
        print(f"{FAMILY}: restamp " + ("ok" if not why else "STALE: " + "; ".join(why)))
        return 1 if why else 0
    frozen[FAMILY] = restamp(frozen[FAMILY])
    path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    e = frozen[FAMILY]
    print(
        f"restamped {FAMILY}: {len(e['ids'])} ids kept, instrument {e['instrument']}, "
        f"bank_sha {e['restamped_from']['bank_sha'][:12]} -> {e['bank_sha'][:12]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
