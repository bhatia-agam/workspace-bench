"""model_multihop scoring: the gw concept judge's pick resolution and quote void (native), the
cluster bootstrap over the bridge, chance from the bank, and the per-category extras."""

import random
import re
from collections.abc import Sequence
from typing import Any

N_BOOT = 10_000
SEED = 20261106
ROLES = ("bridge", "decoy", "none")


def gw_squash(s: str) -> str:
    """gw ``mmh_score._squash``: whitespace runs to one space, stripped, lower case (the key a
    judge's pick is resolved to a candidate by)."""
    return re.sub(r"\s+", " ", s).strip().lower()


def gw_norm(s: str) -> str:
    """gw ``mmh_sjudge._norm``: the quote check's whitespace-squashed lower-case form."""
    return " ".join(s.lower().split())


def native_verdict(o: Any, order: Sequence[str], gold: str, summary: str) -> dict[str, Any] | None:
    """gw ``cjudge``'s per-call rule: the pick resolves to a candidate by :func:`gw_squash`
    (anything else, "none" included, is none); a candidate pick whose quote is empty or not a
    substring of the summary (:func:`gw_norm`) is voided to none. None = no usable answer
    (undecided)."""
    if not isinstance(o, dict) or not o:
        return None
    pick = str(o.get("pick") or "").strip()
    cand = {gw_squash(c): c for c in order}.get(gw_squash(pick))
    quote = str(o.get("quote") or "")
    voided = cand is not None and not (quote.strip() and gw_norm(quote) in gw_norm(summary))
    if voided:
        cand = None
    role = "none" if cand is None else ("bridge" if cand == gold else "decoy")
    return {"pick": cand or "none", "role": role, "quote": quote, "voided": voided}


def chance(items: Sequence[dict[str, Any]]) -> float | None:
    """Mean over items of 1 / (number of options), from the bank."""
    return sum(1 / len(it["mc"]["order"]) for it in items) / len(items) if items else None


def cluster_ci(
    vals: Sequence[float], clusters: Sequence[str], n_boot: int = N_BOOT, seed: int = SEED
) -> list[float] | None:
    """gw ``mmh_score._boot``'s 95% interval: clusters resampled with replacement, percentile
    indices ``int(0.025 n)`` and ``int(0.975 n) - 1`` (the seed is this family's)."""
    if not vals:
        return None
    by: dict[str, list[float]] = {}
    for v, c in zip(vals, clusters, strict=True):
        by.setdefault(c, []).append(v)
    keys = list(by)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        xs = [v for k in (rng.choice(keys) for _ in keys) for v in by[k]]
        stats.append(sum(xs) / len(xs))
    stats.sort()
    return [stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1]]


def category_stats(rows: Sequence[dict[str, Any]], n_boot: int = N_BOOT) -> dict[str, Any]:
    """Over decided rows (``role`` in bridge / decoy / none / unverified / cannot_tell): n,
    P(bridge) with its cluster CI, P(decoy), P(none or cannot tell), P(unverified), chance and
    Δ_foil = P(bridge) - P(decoy) / n_decoys (per row, then averaged)."""
    rows = [r for r in rows if r.get("pass") is not None]
    if not rows:
        return {"n": 0}
    n = len(rows)
    b = [float(r["role"] == "bridge") for r in rows]
    d = [float(r["role"] == "decoy") for r in rows]
    k = [max(1, int(r["n_options"]) - 1) for r in rows]
    cl = [str(r["bridge"]) for r in rows]
    dfoil = [bi - di / ki for bi, di, ki in zip(b, d, k, strict=True)]
    return {
        "n": n,
        "n_clusters": len(set(cl)),
        "n_bridge": int(sum(b)),
        "p_bridge": sum(b) / n,
        "p_bridge_ci95": cluster_ci(b, cl, n_boot),
        "p_decoy": sum(d) / n,
        "p_none": sum(r["role"] in ("none", "cannot_tell") for r in rows) / n,
        "p_unverified": sum(r["role"] == "unverified" for r in rows) / n,
        "chance": sum(1 / (ki + 1) for ki in k) / n,
        "d_foil": sum(dfoil) / n,
        "d_foil_ci95": cluster_ci(dfoil, cl, n_boot),
    }
