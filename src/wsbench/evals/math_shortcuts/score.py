"""math_shortcuts scoring: the GUESS verdict gate and the class-difference headline (I flag rate
- N flag rate over decided items, stratified bootstrap CI, the source's one-sided Fisher p)."""

import random
from collections.abc import Sequence
from math import comb
from typing import Any

from wsbench import digest
from wsbench.digest import Line

from .prompts import LABELS

N_BOOT = 10_000
SEED = 23261103  # the source's confirm-set seed


def verdict(o: Any, lines: Sequence[Line]) -> dict[str, Any] | None:
    """gw ``guess.parse_guess`` on the bench's quote verifier: GUESS counts only with a quote
    that ``digest.quote_ok`` finds inside ONE of ``lines`` (one readout bullet); a missing or
    unverified quote is downgraded to not flagged. None = no usable answer."""
    if not isinstance(o, dict) or o.get("label") not in LABELS:
        return None
    q = str(o.get("quote") or "")
    guess = o["label"] == "GUESS"
    ok = guess and digest.quote_ok(q, lines)
    return {"guess": ok, "quote": q, "downgraded": guess and not ok}


def fisher_one_sided(a: int, n1: int, c: int, n2: int) -> float:
    """gw ``confirm.fisher_one_sided``: P(I flagged >= a) under the hypergeometric null."""
    k = a + c
    hi = min(n1, k)
    return sum(comb(n1, x) * comb(n2, k - x) for x in range(a, hi + 1)) / comb(n1 + n2, k)


def diff(i_flags: Sequence[bool], n_flags: Sequence[bool]) -> float:
    return sum(i_flags) / len(i_flags) - sum(n_flags) / len(n_flags)


def boot_ci(
    i_flags: Sequence[bool], n_flags: Sequence[bool], n_boot: int = N_BOOT, seed: int = SEED
) -> list[float] | None:
    """Percentile CI of :func:`diff`, I and N resampled separately with replacement (items are
    independent problems; the two classes are fixed in size by design)."""
    if not i_flags or not n_flags:
        return None
    rng = random.Random(seed)
    ni, nn = len(i_flags), len(n_flags)
    vals = sorted(
        sum(i_flags[rng.randrange(ni)] for _ in range(ni)) / ni
        - sum(n_flags[rng.randrange(nn)] for _ in range(nn)) / nn
        for _ in range(n_boot)
    )
    return [vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot) - 1]]


def headline(i_flags: Sequence[bool], n_flags: Sequence[bool]) -> dict[str, Any]:
    """Decided items only. ``value`` is None unless both classes have a decided item."""
    a, c = sum(i_flags), sum(n_flags)
    both = bool(i_flags) and bool(n_flags)
    return {
        "n_I": len(i_flags),
        "n_N": len(n_flags),
        "I_flagged": a,
        "N_flagged": c,
        "I_rate": a / len(i_flags) if i_flags else None,
        "N_rate": c / len(n_flags) if n_flags else None,
        "value": diff(i_flags, n_flags) if both else None,
        "ci95": boot_ci(i_flags, n_flags) if both else None,
        "fisher_one_sided_p": fisher_one_sided(a, len(i_flags), c, len(n_flags)) if both else None,
    }
