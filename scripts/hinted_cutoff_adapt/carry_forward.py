"""Plan 0084 top-ups: no twin of a pair an earlier audit dropped re-enters a re-paired set; emits
``{pair_id: reason}`` for every current pair holding such a twin (applied with ``drop_pairs.py``).

    python carry_forward.py <prior audit_drops.json> [<more prior drops> ...] <build out_dir> <out>
"""

import json
import sys
from pathlib import Path


def flagged(prior: dict[str, str]) -> dict[str, str]:
    """Item key -> reason, for BOTH twins of every dropped pair. Conservative on purpose: audit
    reasons are compound ("N answer ...; I twin also ...", "I hint answer WRONG", "I kept reply
    hedges", "I event repeats ..."), so blaming one twin from the wording misroutes (PR #483)."""
    out: dict[str, str] = {}
    for pid, reason in prior.items():
        for key in pid.split("~"):
            why = f"carry-forward: twin of earlier-dropped pair {pid}: {reason.split(': ', 1)[-1]}"
            out.setdefault(key, why)
    return out


def drops(prior: dict[str, str], pairs: list[dict]) -> dict[str, str]:
    """The current pairs that hold a flagged twin, with the earlier audit's reason."""
    bad = flagged(prior)
    out = {}
    for p in pairs:
        for k in (p["I"], p["N"]):
            if k in bad and p["pair_id"] not in out:
                out[p["pair_id"]] = bad[k]
    return out


def main() -> None:
    *priors, build, dest = sys.argv[1:]
    if not priors:
        raise SystemExit(__doc__)
    prior: dict[str, str] = {}
    for p in priors:
        prior.update(json.loads(Path(p).read_text()))
    pairs = json.loads((Path(build) / "pairs.json").read_text())
    out = drops(prior, pairs)
    Path(dest).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"[carry_forward] {len(flagged(prior))} flagged items; {len(out)} of {len(pairs)} hit")


if __name__ == "__main__":
    main()
