"""The token bank: the cells' slot vectors appended as extra vocabulary rows of a copy of the
bundle's model, so a request is plain token ids whose slot holds that cell's bank row id."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from wsbench.produce.served.bundle import DONE, INDEX, META, weight_map
from wsbench.produce.store import Cell


def slot_rows(meta: dict[str, Any], cells: list[Cell], device: str, chunk: int = 4096) -> Any:
    """[n, d] bf16 on the CPU: each cell's slot embedding ``norm_L * h / ||h||``, computed on
    ``device`` in float32. A CPU norm can differ from a GPU's in the last bit, so the device
    is the caller's explicit choice."""
    import torch

    norms = torch.tensor([meta["prompts"][str(c.layer)]["norm"] for c in cells])
    out = []
    for lo in range(0, len(cells), chunk):
        h = torch.stack([c.h for c in cells[lo : lo + chunk]]).float().to(device)
        n = norms[lo : lo + chunk].to(device)
        rows = n[:, None] * (h / h.norm(dim=-1, keepdim=True).clamp_min(1e-9))
        out.append(rows.to(torch.bfloat16).cpu())
    return torch.cat(out) if out else torch.zeros(0, 1, dtype=torch.bfloat16)


def head_row(head: Any, gamma: float = 4.0) -> Any:
    """The one output-embedding row every bank id shares: minus ``gamma`` x the mean row of
    the most frequent tokens (ids 256..4352, the earliest BPE merges), so a bank id's logit
    sits far below the top. That alone does not stop every bank id from being sampled, so the
    server also masks them (`processors.BankMask`) and the engine checks every output."""
    return (-gamma * head[256:4352].float().mean(0)).to(head.dtype)


def _bump_vocab(cfg: dict[str, Any], extra: int) -> None:
    for holder in (cfg, cfg.get("text_config")):
        if isinstance(holder, dict) and "vocab_size" in holder:
            holder["vocab_size"] = int(holder["vocab_size"]) + extra


def build_bank(merged: Path, out_dir: Path, vectors: Any) -> int:
    """``out_dir`` = the bundle's model with ``vectors`` [B, d] appended as vocabulary rows.
    Returns the base vocabulary size: bank row j is token id ``base + j``. Unchanged files are
    symlinks; only the files holding the input and output embeddings are rewritten."""
    import torch
    from safetensors.torch import load_file, save_file

    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    wmap = weight_map(merged)
    embed = [k for k in wmap if k.endswith("embed_tokens.weight")]
    head = [k for k in wmap if k.endswith("lm_head.weight")]
    if len(embed) != 1 or len(head) != 1:
        raise ValueError(f"need exactly one embedding and one head tensor, got {embed} / {head}")
    rewritten = {wmap[embed[0]], wmap[head[0]]}
    for f in merged.iterdir():
        if f.is_file() and f.name not in rewritten | {"config.json", INDEX, META, DONE}:
            os.symlink(f.resolve(), out_dir / f.name)
    base, added, n = 0, 0, vectors.shape[0]
    for name in sorted(rewritten):
        tensors = load_file(str(merged / name))
        if embed[0] in tensors:
            table = tensors[embed[0]]
            base = table.shape[0]
            rows = vectors.to(table.dtype)
            tensors[embed[0]] = torch.cat([table, rows])
            added += rows.numel() * rows.element_size()
        if head[0] in tensors:
            table = tensors[head[0]]
            pad = head_row(table).unsqueeze(0).expand(n, -1).contiguous()
            tensors[head[0]] = torch.cat([table, pad])
            added += pad.numel() * pad.element_size()
        save_file(tensors, str(out_dir / name), metadata={"format": "pt"})
        del tensors
    cfg = json.loads((merged / "config.json").read_text())
    _bump_vocab(cfg, n)
    (out_dir / "config.json").write_text(json.dumps(cfg, indent=1))
    if (merged / INDEX).exists():
        index = json.loads((merged / INDEX).read_text())
        if "total_size" in index.get("metadata", {}):
            index["metadata"]["total_size"] += added
        (out_dir / INDEX).write_text(json.dumps(index))
    return base
