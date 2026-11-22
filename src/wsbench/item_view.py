"""One bank item as a reader sees it: the text the model reads, what it should produce, and the
latent the eval looks for. Used by ``wsbench try`` and by the viewers; depends on nothing else."""

import json
from typing import Any

# What a reader needs first, in the order tried: the text the model sees, then what it should
# compute. Everything else stays in the item's raw fields.
STIMULUS_KEYS = ("prompt", "stimulus", "messages", "code", "text", "expr", "statement")
TARGET_KEYS = ("target", "target_alts", "answer", "gold", "gold_alt", "gold_label", "attr_label")
LATENT_KEYS = ("intermediates", "bridges", "hop1", "hop2", "concept", "concepts", "units")
ADAPT_KEY = "adapt"


def _is_turn(m: Any) -> bool:
    return isinstance(m, dict) and "role" in m


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(_is_turn(m) for m in value):
        return "\n\n".join(f"[{m['role']}]\n{m.get('content', '')}" for m in value)
    return json.dumps(value, ensure_ascii=False, indent=1)


def _flat(value: Any) -> list[str]:
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, list):
        return [s for v in value for s in _flat(v)]
    if isinstance(value, dict):
        q = value.get("answer") or value.get("target") or value.get("question")
        return [str(q)] if q else [json.dumps(value, ensure_ascii=False)]
    return [str(value)]


def item_id(item: dict, n: int) -> str:
    return str(item.get("id") or item.get("name") or n)


def _orig_rate(item: dict) -> float | None:
    for key in ("consistency_strict", "consistency"):
        value = item.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    gate = item.get("gate")
    if isinstance(gate, dict):
        block = gate.get("last") if isinstance(gate.get("last"), dict) else gate
        if isinstance(block.get("correct"), int) and block.get("n"):
            return block["correct"] / block["n"]
    return None


def _subfamily(item: dict) -> Any:
    """The item's subfamily label; an agentic_misalignment clean twin (``arm:
    "twin"``) is shown as its partner's category plus ``twin``, so it never reads as a misaligned
    scenario."""
    sub = item.get("subfamily") or item.get("variant") or item.get("category")
    return f"{sub} (twin)" if item.get("arm") == "twin" and sub else sub


def view_item(item: dict, n: int, gate: dict | None = None, selected: bool = True) -> dict:
    """One item as the viewer shows it: stimulus, target, latent, gate, and the raw fields."""
    stim_key = next((k for k in STIMULUS_KEYS if item.get(k)), None)
    adapt = item.get(ADAPT_KEY) or {}
    gate = gate or adapt.get("gate")
    if gate is None and (rate := _orig_rate(item)) is not None:
        gate = {"rate": rate, "pass": None}
    return {
        "id": item_id(item, n),
        "origin": adapt.get("origin", "original"),
        "selected": selected,
        "tier": adapt.get("tier"),
        "knobs": adapt.get("knobs") or {},
        "note": adapt.get("note"),
        "subfamily": _subfamily(item),
        "stimulus": _text(item[stim_key]) if stim_key else "",
        "target": [s for k in TARGET_KEYS for s in _flat(item.get(k))],
        "latent": [s for k in LATENT_KEYS for s in _flat(item.get(k))][:24],
        "gate": gate,
        "raw": {k: v for k, v in item.items() if k not in (stim_key, ADAPT_KEY)},
    }
