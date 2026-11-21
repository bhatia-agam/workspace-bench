"""``wsbench try``: pick a few items of one family and show each question with its expected
answer. The command itself (``cli.Try``) then runs the ordinary plan, judge and report on them."""

import json
from pathlib import Path
from typing import Any

from wsbench import readplan, registry
from wsbench.item_view import item_id, view_item
from wsbench.readplan import ReadSpec

EXAMPLES = registry.REPO_ROOT / "examples" / "readouts"
QUESTION_CHARS = 400  # a question longer than this is cut in the middle when shown
LATENT_CHARS, LATENT_SHOWN = 60, 4  # the "looks for" line: at most 4 latents this short


def example_readouts(family: str) -> Path:
    """The toy readouts file shipped for ``family``."""
    return EXAMPLES / f"{family}.jsonl"


def readout_ids(path: Path) -> set[str]:
    """Item ids with at least one row in a readouts file (malformed lines are skipped)."""
    ids: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                ids.add(str(json.loads(line)["id"]))
            except (ValueError, KeyError, TypeError):
                continue
    return ids


def pick(family: str, readouts: Path, n: int) -> list[ReadSpec]:
    """The first ``n`` read-plan rows of ``family`` that have readouts in ``readouts`` (plan
    order; fewer when the file covers fewer items). None at all is a usage error."""
    have = readout_ids(readouts)
    rows = [s for s in readplan.plan(family) if s.id in have]
    if not rows:
        raise SystemExit(f"try: {readouts} has no readouts for any item of {family}")
    return rows[:n]


def _bank_items(family: str) -> dict[str, dict[str, Any]]:
    """The family's bank items by readout id; empty for a bank that is not a list of items."""
    try:
        _header, items = readplan.bank_file(registry.bank_path(family))
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return {}
    return {item_id(it, n): it for n, it in enumerate(items) if isinstance(it, dict)}


def _clip(text: str, limit: int = QUESTION_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half].rstrip()} [... {len(text) - 2 * half} chars ...] {text[-half:].lstrip()}"


def _short(values: list[str], limit: int = LATENT_SHOWN) -> list[str]:
    """The latents worth one line: names and numbers, not the bank's question texts or its
    JSON records (a multi-token bank keeps both beside the names)."""
    names = [v for v in dict.fromkeys(values) if len(v) <= LATENT_CHARS and v[:1] not in "{["]
    return names[:limit]


def question(spec: ReadSpec) -> str:
    """The text the subject model reads for this item, as the read plan renders it."""
    if spec.text:
        return spec.text
    if spec.messages:
        return "\n".join(f"[{m['role']}] {m.get('content', '')}" for m in spec.messages)
    return ""


def describe(family: str, specs: list[ReadSpec]) -> str:
    """One block per picked item: id, question, expected answer and the latent the eval looks
    for (the same fields the viewers show, ``item_view.view_item``)."""
    bank = _bank_items(family)
    lines: list[str] = []
    for k, spec in enumerate(specs, 1):
        view = view_item(bank[spec.id], k) if spec.id in bank else None
        asked = question(spec) or (view["stimulus"] if view else "")
        lines.append(f"[{k}] {spec.id}")
        lines.append(f"    question: {_clip(asked) or '(see the plan row)'}")
        target = list(dict.fromkeys(view["target"])) if view else []
        latent = _short(view["latent"]) if view else []
        if target or latent:
            lines.append(f"    expected: {' | '.join(target or latent)}")
        else:
            lines.append(f"    expected: see evals/{family}/README.md")
        if target and latent:
            lines.append(f"    looks for: {' | '.join(latent)}")
        layers = f"{spec.layers[0]}..{spec.layers[-1]}" if spec.layers else "-"
        lines.append(f"    read at: positions {spec.positions.get('kind')}, layers {layers}")
    return "\n".join(lines)


def viewer_commands(family: str, judged: Path, readouts: Path, out: Path) -> list[str]:
    """The two commands that show a judged try-out in the results viewer (its own small store
    under ``out``). The readouts are attached when the file has the name ingest looks for."""
    store = out / "viewer_store"
    named = readouts.name == f"{family}.jsonl"
    ingest = f"uv run wsbench viewer ingest {judged} adapter=wsb lens=try"
    ingest += (f" readouts={readouts.parent}" if named else "") + f" store={store}"
    return [ingest, f"uv run wsbench viewer serve store={store}"]
