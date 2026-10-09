"""Mismatched-target nulls (plan 0012 §1): seeded bank-level derangements and near-miss foils,
graded on an item's own cells so a pass rate can be read beside what a wrong target scores."""

import json
import random
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from wsbench.mc import fold, seed_int
from wsbench.results import bootstrap_ci

K_NULL = 3  # random partners per item
K_FOIL = 3  # near-miss foils per item


def word_in(needle: str, text: str) -> bool:
    """Whole-word containment after ``mc.fold``: ``7`` is not in ``17``, ``art`` not in
    ``start``. A needle with no word characters, or with CJK, is a plain substring."""
    n, t = fold(needle).strip(), fold(text)
    if not n:
        return False
    if not re.search(r"\w", n) or re.search(r"[぀-ヿ㐀-鿿가-힯]", n):
        return n in t
    return re.search(rf"(?<!\w){re.escape(n)}(?!\w)", t) is not None


def _matching(
    ids: Sequence[str], allowed: Mapping[str, set[str]], rng: random.Random
) -> dict[str, str] | None:
    """A perfect matching item -> partner inside ``allowed`` (Kuhn's augmenting paths over a
    seeded shuffle of the adjacency), or None when none exists."""
    adj = {i: rng.sample(sorted(allowed[i]), len(allowed[i])) for i in ids}
    order = rng.sample(list(ids), len(ids))
    owner: dict[str, str] = {}  # partner -> item

    def augment(i: str, seen: set[str]) -> bool:
        for p in adj[i]:
            if p in seen:
                continue
            seen.add(p)
            if p not in owner or augment(owner[p], seen):
                owner[p] = i
                return True
        return False

    for i in order:
        if not augment(i, set()):
            return None
    return {i: p for p, i in owner.items()}


def derangements(
    ids: Sequence[str], allowed: Mapping[str, set[str]], *, k: int, seed: str
) -> list[dict[str, str]]:
    """``k`` edge-disjoint derangements of ``ids`` restricted to ``allowed`` (an item is never
    allowed to itself). Raises ``ValueError`` when the constraints leave no perfect matching."""
    rng = random.Random(seed_int(seed))
    left = {i: set(allowed[i]) - {i} for i in ids}
    out: list[dict[str, str]] = []
    for j in range(k):
        m = _matching(ids, left, rng)
        if m is None:
            raise ValueError(f"{seed}: no derangement {j} satisfies the null constraints")
        out.append(m)
        for i, p in m.items():
            left[i].discard(p)
    return out


def bank_partners(
    items: Sequence[dict[str, Any]],
    targets_of: Callable[[dict[str, Any]], list[str]],
    *,
    family: str,
    k: int = K_NULL,
) -> dict[str, list[str]]:
    """item id -> its ``k`` random-null partners over the FULL bank (plan 0012 §1.1):
    no partner target equals one of the item's targets (folded), sits as a word in the item's
    prompt (or a multilingual item's ``reference_concepts``), or equals its surface ``target``."""
    by_id = {it["id"]: it for it in items}
    tgts = {i: targets_of(it) for i, it in by_id.items()}
    ctx = {
        i: " \n ".join([str(it.get("prompt", "")), *map(str, it.get("reference_concepts") or [])])
        for i, it in by_id.items()
    }
    surface = {i: fold(str(it.get("target") or "")).strip() for i, it in by_id.items()}
    own = {i: {fold(t).strip() for t in ts} for i, ts in tgts.items()}

    def ok(i: str, p: str) -> bool:
        for t in tgts[p]:
            ft = fold(t).strip()
            if ft in own[i] or (surface[i] and ft == surface[i]) or word_in(t, ctx[i]):
                return False
        return True

    ids = list(by_id)
    allowed = {i: {p for p in ids if p != i and ok(i, p)} for i in ids}
    ms = derangements(ids, allowed, k=k, seed=f"{family}:null")
    return {i: [m[i] for m in ms] for i in ids}


def load_foils(path: Path) -> dict[str, list[str]]:
    """``null_foils.json`` sidecar: ``{"items": {id: [foil, ...]}}``; {} when absent."""
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): [str(x) for x in v] for k, v in (d.get("items") or {}).items()}


def surface_free(credited: Iterable[str], quote: str) -> bool:
    """A credit is surface-free when none of the credited strings is a word of the quote."""
    return not any(word_in(c, quote) for c in credited)


def null_summary(per_item: Mapping[str, list[bool | None]]) -> dict[str, Any]:
    """Rate over items of the mean decided null pass (each item's draws averaged first), with a
    bootstrap CI over items; items with no decided draw leave the denominator."""
    vals = []
    for draws in per_item.values():
        dec = [1.0 if d else 0.0 for d in draws if d is not None]
        if dec:
            vals.append(sum(dec) / len(dec))
    return {
        "rate": sum(vals) / len(vals) if vals else None,
        "ci95": list(bootstrap_ci(vals)) if vals else None,
        "n": len(vals),
    }
