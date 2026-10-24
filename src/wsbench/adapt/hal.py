"""hallucination on a new subject: the bank IS the subject's own responses (references/porting.md).
The pinned 149 prompts, chat render with thinking off, T=1.0 / top-p 1 / no top-k, 512 new tokens,
seed 7, cut at the first stop id; read sites by ``hallucination_bench.response_sites`` thinned to 8;
items with no site re-sampled with seed+k (k <= 4). Port of global-workspace bdff9b03
``wsbench_gemma.build_hal_onpolicy``; generation runs on vLLM here instead of HF ``generate``
(recorded in the meta). Writes ``hallucination.json`` + ``hallucination.capture_rows.json``."""

import json
import time
import unicodedata
from pathlib import Path
from typing import Any

from . import store

GEN = {"temperature": 1.0, "top_p": 1.0, "top_k": 0, "max_new_tokens": 512, "seed": 7}
MAX_SITES = 8
RESAMPLE = 4
_SENTENCE = set(".!?…")
_CLAUSE = set(",;:—–-")  # noqa: RUF001 — typographic dashes are exactly what is detected
_QUOTE = set("\"'“”‘’«»")  # noqa: RUF001 — ditto for curly quotes


def is_summary_token(text: str) -> bool:
    """Copied from global-workspace ``hallucination_bench``: non-empty after stripping spaces and
    made only of Unicode punctuation (``P*``) and/or whitespace."""
    s = text.strip(" ")
    return bool(s) and all(unicodedata.category(c).startswith("P") or c.isspace() for c in s)


def site_kind(text: str) -> str | None:
    """Copied from global-workspace ``hallucination_bench``: sentence > clause > quote >
    whitespace-only (newline) > markup; ``None`` for a non-site."""
    if not is_summary_token(text):
        return None
    s = text.strip(" ")
    chars = set(s)
    if chars & _SENTENCE:
        return "sentence"
    if chars & _CLAUSE:
        return "clause"
    if chars & _QUOTE:
        return "quote"
    if s.isspace():
        return "newline"
    return "markup"


def response_sites(tokens: list[str], start: int) -> list[dict[str, Any]]:
    out, char = [], 0
    for pos in range(start, len(tokens)):
        char += len(tokens[pos])
        kind = site_kind(tokens[pos])
        if kind is not None:
            out.append({"pos": pos, "token": tokens[pos], "kind": kind, "char": char})
    return out


def thin(sites: list[dict[str, Any]], k: int = MAX_SITES) -> list[dict[str, Any]]:
    if k and len(sites) > k:
        step = len(sites) / k
        return [sites[int(i * step)] for i in range(k)]
    return sites


def hal_item(tok: Any, item: dict, prompt_ids: list[int], out_ids: list[int]) -> dict[str, Any]:
    ids, pl = [*prompt_ids, *out_ids], len(prompt_ids)
    tokens = [tok.decode([t], skip_special_tokens=False) for t in ids]
    response = tok.decode(out_ids, skip_special_tokens=False)
    sites, bad = [], 0
    for st in thin(response_sites(tokens, pl)):
        prefix = tok.decode(ids[pl : int(st["pos"]) + 1], skip_special_tokens=False)
        if not response.startswith(prefix):
            bad += 1
            continue
        sites.append({**st, "char": len(prefix)})
    return {"id": item["id"], "stratum": item.get("stratum", "chat"), "source": item.get("source"),
            "source_id": item.get("source_id"), "prompt": item["prompt"], "response": response,
            "response_start": pl, "sites": sites, "input_ids": ids,
            "n_site_prefix_mismatch": bad}  # fmt: skip


def build(model: str, limit: int = 0) -> dict[str, Any]:
    from wsbench.produce.render import _chat

    from .run import _runner
    from .subjects import get

    s = get(model)
    src = json.loads((store.REPO_ROOT / "evals/hallucination/items.json").read_text())
    rows = {r["id"]: r for r in json.loads(
        (store.REPO_ROOT / "evals/hallucination/capture_rows.json").read_text())}  # fmt: skip
    items = src["items"][: limit or None]
    runner = _runner(model)  # local vLLM, or Modal for subjects too big for the box
    tok = runner.tok
    from .template import stop_ids

    stop = stop_ids(tok, runner.gen_eos())  # eos + config/generation eos + the turn-closing marker
    prompts = [_chat(tok, [{"role": "user", "content": it["prompt"]}]) for it in items]

    def gen(idx: list[int], seed: int) -> list[list[int]]:
        outs = runner.generate([prompts[i] for i in idx], GEN["temperature"],
                               GEN["max_new_tokens"], seed, top_p=GEN["top_p"],
                               stop_token_ids=stop)  # fmt: skip
        return [[t for t in o["ids"] if t not in stop] for o in outs]

    t0 = time.time()
    built = [hal_item(tok, it, p, o)
             for it, p, o in zip(items, prompts, gen(list(range(len(items))), GEN["seed"]),
                                 strict=True)]  # fmt: skip
    attempts = [1] * len(built)
    for k in range(1, RESAMPLE + 1):
        redo = [i for i, it in enumerate(built) if not it["sites"]]
        if not redo:
            break
        for i, o in zip(redo, gen(redo, GEN["seed"] + k), strict=True):
            built[i], attempts[i] = hal_item(tok, items[i], prompts[i], o), k + 1
    lens = sorted(len(it["input_ids"]) - it["response_start"] for it in built)
    meta = {
        "family": "hallucination_chat_onpolicy", "model": s.hf_id, "revision": s.revision,
        "source_bank": {k: src["meta"].get(k) for k in ("model", "n_items", "n_sites")},
        "prompts": "the pinned bank's items (same ids, order, prompt text)",
        "rollouts": f"{s.hf_id} on-policy, vLLM (declared deviation from HF generate), "
        f"T={GEN['temperature']}, top-p {GEN['top_p']}, no top-k, max {GEN['max_new_tokens']} "
        f"new tokens, seed {GEN['seed']}; chat template enable_thinking=False; cut at the first "
        "stop id (not kept)",
        "stop_ids": stop, "read_sites": f"response_sites over per-token decodes, thinned to "
        f"{MAX_SITES}; char offsets from whole-span decodes",
        "resample": f"items with no site re-sampled with seed+k, k<={RESAMPLE}",
        "n_items": len(built), "n_sites": sum(len(it["sites"]) for it in built),
        "n_items_no_sites": sum(not it["sites"] for it in built),
        "n_resampled": sum(a > 1 for a in attempts),
        "n_truncated_at_max": sum(n >= GEN["max_new_tokens"] for n in lens),
        "n_site_prefix_mismatch": sum(it["n_site_prefix_mismatch"] for it in built),
        "response_tokens_median": lens[len(lens) // 2], "gen_seconds": round(time.time() - t0),
    }  # fmt: skip
    capture = [{"id": it["id"], "source": it["source"], "source_id": rows.get(it["id"], {}).get(
                "source_id", it.get("source_id")), "prompt_len": it["response_start"],
                "input_ids": it["input_ids"], "read_positions": [st["pos"] for st in it["sites"]]}
               for it in built]  # fmt: skip
    for it, a in zip(built, attempts, strict=True):
        it["attempts"] = a
        del it["input_ids"]
    out = store.model_dir(model)
    tag = f".smoke{limit}" if limit else ""
    store.write_json(Path(out / f"hallucination{tag}.json"), {"meta": meta, "items": built})
    store.write_json(Path(out / f"hallucination{tag}.capture_rows.json"), capture)
    if not limit:  # every step writes its own report.json entry (skill audit)
        store.update_report(model, lambda r: r.setdefault("families", {}).setdefault(
            "hallucination", {}).update(
            status="full", n_items=meta["n_items"], target=src["meta"].get("n_items"),
            change=f"rebuilt on the subject's own responses ({meta['n_sites']} sites, "
            f"{meta['n_truncated_at_max']} at the {GEN['max_new_tokens']}-token cap)"))  # fmt: skip
    print(json.dumps(meta, indent=1))
    return meta
