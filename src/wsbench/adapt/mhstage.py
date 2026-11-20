"""multihop_st refill (plan 0075 §2.4): a new row ships only with bank v5's legs (#323), the second
hop asked with the bridge named and the shortcut probes, both measured by the gate."""


def row_passes(row: dict) -> bool:
    """An original keeps its registered legs; a new row needs a ``hop2`` leg and >= 2
    ``shortcut*`` legs in its gate record (rows authored before plan 0075 carry neither)."""
    if row["origin"] == "original":
        return True
    legs = (row["gate"] or {}).get("legs") or {}
    return "hop2" in legs and sum(str(k).startswith("shortcut") for k in legs) >= 2
