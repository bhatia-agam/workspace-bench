"""Mechanical audit of a judged run (gpu.md G9).

    python scripts/audit_run.py --judged <run dir> [--json]

Per ``<run dir>/<family>/results.json`` it checks, and prints a table:
- ``config.aggregate == "summary"`` (``jlens_concept_pr``: native);
- ``config.sampling_source == "declared"`` and ``config.reads_checked`` is ``sidecar`` (or
  ``prompt_only`` for the floor run); a ``-dmo-*`` dir is a diagnostic control arm, exempt;
- ``prompt_version`` equals ``digest.prompt_version(<registry PV>, …)`` (a superseded
  instrument never reaches the site);
- ``n_readouts_in == n_readouts_bundled`` and ``n_truncated_items == 0`` (no readout dropped);
- ``complete`` for a ``layers=<L>`` run.
It prints ``extras.digest_served_by``, ``n_unverified_bullet`` and ``n_bare_mention_pass``, and
(round 3; plan 0046 moral) the two instrument matches, reported, never failed (a PV change after
gpu R6 / R8 means "no floor" / "re-gate", not a broken run): ``floor`` = whether the frozen
summary prompt-only floor's ``instrument`` equals ``prompt_version``
(``prompt_only.summary_floor_applies``), ``ati`` = whether a native row's ``prompt_version``
equals the frozen ATI entry's ``instrument``.
Exit 1 when any check fails."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NATIVE = {"jlens_concept_pr"}


def _probe(cfg: dict[str, Any]) -> Any:
    from wsbench import digest

    keys = ("variant", "render", "max_items", "max_rare", "numbers", "overflow", "lang")
    summ = cfg.get("summarizer") or {}
    extra = {"aggregate": "summary"}
    names = {
        "variant": "summ_variant",
        "render": "summ_render",
        "max_items": "summ_max",
        "max_rare": "summ_rare",
        "numbers": "summ_numbers",
        "overflow": "summ_overflow",
    }
    for k in keys:
        if k in names and k in summ and summ[k] not in (None, ""):
            extra[names[k]] = str(summ[k])
    # an old run's summ_lang=1 is not replayed: the option was removed on 2026-11-01
    return digest._probe(extra)


def audit_family(fam_dir: Path) -> dict[str, Any]:
    from wsbench import digest, registry

    res = json.loads((fam_dir / "results.json").read_text(encoding="utf-8"))
    cfg = res.get("config", {})
    family = registry.stored_family(res["family"], cfg.get("prompt_version"))
    extras = (res.get("numbers") or {}).get("extras", {}) or {}
    summ = extras.get("summary") if isinstance(extras.get("summary"), dict) else extras
    diag = "-dmo-" in str(fam_dir)
    problems: list[str] = []
    try:
        spec = registry._spec_for_bank(family)  # also with an emptied registry
    except SystemExit:
        spec = None
    if family not in NATIVE and cfg.get("aggregate") != "summary":
        problems.append(f"aggregate={cfg.get('aggregate')!r}")
    if not diag:
        if cfg.get("reads_checked") not in ("sidecar", "prompt_only"):
            problems.append(f"reads_checked={cfg.get('reads_checked')!r}")
        if cfg.get("sampling_source") != "declared" and cfg.get("reads_checked") != "prompt_only":
            problems.append(f"sampling_source={cfg.get('sampling_source')!r}")
    if spec is not None and cfg.get("aggregate") == "summary":
        want = digest.prompt_version(spec.judge.prompt_version, _probe(cfg))
        # an adapted set's re-stamped row (plan 0072 0.2): audit its registered stamp
        got_pv = cfg.get("registered_prompt_version") or cfg.get("prompt_version", "")
        if not str(got_pv).startswith(spec.judge.prompt_version):
            problems.append(f"prompt_version {cfg.get('prompt_version')!r} != registry")
        elif got_pv != want:
            problems.append(f"prompt_version {cfg.get('prompt_version')!r} != {want!r}")
    if isinstance(summ, dict) and "n_readouts_in" in summ:
        if summ["n_readouts_in"] != summ.get("n_readouts_bundled"):
            problems.append("readouts dropped from the digest")
        if summ.get("n_truncated_items"):
            problems.append(f"n_truncated_items={summ['n_truncated_items']}")
    if cfg.get("layers") and not res.get("complete"):
        problems.append("a layers= run is incomplete")
    floor, ati = _instrument_matches(family, cfg)
    return {
        "family": family,
        "dir": str(fam_dir),
        "diagnostic": diag,
        "ok": not problems,
        "problems": problems,
        "digest_served_by": (summ or {}).get("digest_served_by")
        if isinstance(summ, dict)
        else None,
        "n_unverified_bullet": extras.get("n_unverified_bullet"),
        "n_bare_mention_pass": extras.get("n_bare_mention_pass"),
        "floor": floor,
        "ati": ati,
    }


def _instrument_matches(family: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """(floor, ati) status strings: ``applies`` / ``no floor (<instrument>)`` / ``none`` for a
    summary row; ``ok`` / ``re-gate (<instrument>)`` / ``none`` for a native row's ATI entry."""
    from wsbench.baselines import prompt_only, text_inversion

    pv = str(cfg.get("prompt_version") or "")
    floor = ati = "n/a"
    if cfg.get("aggregate") == "summary":
        e = prompt_only.summary_floors().get(family)
        if e is None:
            floor = "none"
        elif prompt_only.summary_floor_applies(e, cfg):
            floor = "applies"
        else:
            floor = f"no floor ({e.get('instrument')} != {pv})"
    else:
        frozen = json.loads(text_inversion.FROZEN.read_text(encoding="utf-8"))
        e = frozen.get(family) if isinstance(frozen.get(family), dict) else None
        if e is None:
            ati = "none"
        else:
            ok = e.get("instrument") in (pv, cfg.get("registered_prompt_version"))  # plan 0072 0.2
            ati = "ok" if ok else f"re-gate ({e.get('instrument')} != {pv})"
    return floor, ati


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--judged", required=True, nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rows = [
        audit_family(p.parent) for d in a.judged for p in sorted(Path(d).glob("**/results.json"))
    ]
    if a.json:
        print(json.dumps(rows, indent=1))
    else:
        for r in rows:
            mark = "ok  " if r["ok"] else "FAIL"
            tag = " (diagnostic control arm)" if r["diagnostic"] else ""
            print(f"{mark} {r['family']}{tag}: {'; '.join(r['problems']) or '—'}")
            print(f"     floor: {r['floor']}; ati: {r['ati']}; "
                  f"n_unverified_bullet: {r['n_unverified_bullet']}")  # fmt: skip
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
