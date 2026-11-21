"""Optional full-prompt tokenization: with ``transformers`` and the subject's tokenizer in the
local Hugging Face cache, render every question the way the read plan does and keep its tokens,
so the token strip shows the whole prompt with the read positions marked. Without them nothing
is stored and the strip shows the read positions only."""

import os
from pathlib import Path
from typing import Any

from wsbench import readplan
from wsbench.viewer import store

HF_IDS = {"qwen3.6-27b": "Qwen/Qwen3.6-27B"}
# knowledge_cutoff's plan downloads the nocot questions; the viewer never stores those
SKIP = frozenset({"knowledge_cutoff"})
MAX_TOKENS = 6000  # longer prompts keep the read-positions strip


def load_tokenizer(model: str) -> tuple[Any | None, str]:
    """``(tokenizer, why not)``: offline only, never a download."""
    hf_id = HF_IDS.get(model)
    if hf_id is None:
        return None, f"no tokenizer id known for {model!r}"
    try:
        from transformers import AutoTokenizer
    except ImportError:
        return None, "transformers is not installed (uv sync --extra gpu, or pip install it)"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        return AutoTokenizer.from_pretrained(hf_id, local_files_only=True), ""
    except (OSError, ValueError) as e:
        return None, f"{hf_id} is not in the local Hugging Face cache ({type(e).__name__})"


def family_tokens(family: str, tokenizer: Any) -> dict[str, list[str]]:
    """``{item id: decoded tokens of its rendered prompt}``; ``{}`` when the family's plan
    cannot be built offline."""
    from wsbench.produce.render import render

    if family in SKIP:
        return {}
    try:
        specs = readplan.plan(family)
    except (SystemExit, Exception):  # a plan that needs data or a download that is not here
        return {}
    out = {}
    for spec in specs:
        try:
            toks = render(spec, tokenizer).decoded
        except (KeyError, ValueError, TypeError):
            continue
        if len(toks) <= MAX_TOKENS:
            out[spec.id] = toks
    return out


def ingest(store_root: Path, model: str, families: list[str] | None = None) -> dict[str, Any]:
    """Tokenize the prompts of every eval of ``model`` in the catalog."""
    tokenizer, why = load_tokenizer(model)
    if tokenizer is None:
        return {"mode": "read positions only", "why": why, "families": {}}
    cat = store.catalog(store_root)
    names = [
        r["eval"]
        for r in cat.execute("SELECT eval FROM eval WHERE bench = 'wsb' AND model = ?", (model,))
    ]
    private = {
        (r["eval"], r["item"])
        for r in cat.execute(
            "SELECT eval, item FROM item WHERE bench = 'wsb' AND model = ? AND private = 1",
            (model,),
        )
    }
    done = {}
    for fam in names:
        if families and fam not in families:
            continue
        toks = family_tokens(fam, tokenizer)
        rows = [
            ("wsb", model, fam, item, store.pack(t))
            for item, t in toks.items()
            if (fam, item) not in private
        ]
        cat.executemany("INSERT OR REPLACE INTO item_tokens VALUES (?,?,?,?,?)", rows)
        cat.commit()
        done[fam] = len(rows)
    cat.close()
    return {"mode": "full prompt", "why": "", "families": done}
