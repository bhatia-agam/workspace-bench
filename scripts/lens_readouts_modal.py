"""Readouts of the per-subject mOre-lenses O-lenses and neuronpedia J-lenses on an ADAPTED set
(plan 0079 §2-§5: the read spec, producer, incremental store and usage), on Modal, incremental
by plan row. Port of global-workspace scripts/ola/port/subject_wsbench_qwen_modal.py."""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

WSB = Path(__file__).resolve().parents[1]
if str(WSB / "src") not in sys.path:
    sys.path.insert(0, str(WSB / "src"))

MORE_REPO = "agu18dec/mOre-lenses"
MORE_REV = "441fd264200b68777f987a862f7a86176158d7ae"  # 2026-11-01, the README's checkpoints
JLENS_REPO = "neuronpedia/jacobian-lens"
JLENS_REV = "e166deb5ad540932100ef803c8c9bcc2a5453694"  # 2026-10-15

# O-lens arms: the README table's WSB tags -> run directory (olens.json inside). Every checkpoint
# with a WSB tag for the five subjects that have an adapted set.
OLENS: dict[str, dict[str, str]] = {
    "qwen3-8b": {
        "qwen3-8b.inv.s6795": "qwen3-8b/inverter/ao.qwen3-8b.wsd.s0",
        "qwen3-8b.sft": "qwen3-8b/distill/ao.qwen3-8b.wsd.distill.s0",
        "qwen3-8b.rl.i600": "qwen3-8b/rl/rl.qwen3-8b.ddp600.s0",
    },
    "qwen3.5-0.8b": {
        "qwen3.5-0.8b.inv.end": "qwen3.5-0.8b/inverter/ao.qwen3.5-0.8b.s0",
        "qwen3.5-0.8b.sft": "qwen3.5-0.8b/distill/ao.qwen3.5-0.8b.distill.s0",
        "qwen3.5-0.8b.rl.i600": "qwen3.5-0.8b/rl/rl.qwen3.5-0.8b.ddp600.s0",
    },
    "qwen3.5-2b": {
        "qwen3.5-2b.inv.end": "qwen3.5-2b/inverter/ao.qwen3.5-2b.s0",
        "qwen3.5-2b.sft": "qwen3.5-2b/distill/ao.qwen3.5-2b.distill.s0",
        "qwen3.5-2b.rl.i600": "qwen3.5-2b/rl/rl.qwen3.5-2b.ddp600.s0",
    },
    "qwen3.5-4b": {
        "qwen3.5-4b.inv.end": "qwen3.5-4b/inverter/ao.qwen3.5-4b.s0",
        "qwen3.5-4b.inv.L20.end": "qwen3.5-4b/inverter/ao.qwen3.5-4b.L20.s0",
        "qwen3.5-4b.sft": "qwen3.5-4b/distill/ao.qwen3.5-4b.distill.s0",
        "qwen3.5-4b.rl.i600": "qwen3.5-4b/rl/rl.qwen3.5-4b.ddp600.s0",
    },
    "qwen3.5-9b": {
        "qwen3.5-9b.inv.end": "qwen3.5-9b/inverter/ao.qwen3.5-9b.s0",
        "qwen3.5-9b.inv.L20.end": "qwen3.5-9b/inverter/ao.qwen3.5-9b.L20.s0",
        "qwen3.5-9b.sft": "qwen3.5-9b/distill/ao.qwen3.5-9b.distill.s0",
        "qwen3.5-9b.rl.i600": "qwen3.5-9b/rl/rl.qwen3.5-9b.ddp600.s0",
    },
}
# J-lens arms: neuronpedia's instruct lenses (4B: the n1000 file, as adapt_jlens.py uses). 9B has
# no instruct lens: Camila (2026-11-06) chose the BASE-model lens (fitted on Qwen3.5-9B-Base)
# applied to the chat subject, labelled as such everywhere. OLMo's lens is fitted on the base
# model allenai/Olmo-3-1025-7B, not the subject Olmo-3-7B-Instruct: not used. Never fitted here.
JLENS: dict[str, dict[str, str]] = {
    "qwen3-8b": {"jlens": "qwen3-8b/jlens/Salesforce-wikitext/Qwen3-8B_jacobian_lens.pt"},
    "qwen3.5-0.8b": {
        "jlens": "qwen3.5-0.8b/jlens/Salesforce-wikitext/Qwen3.5-0.8B_jacobian_lens.pt"
    },
    "qwen3.5-2b": {"jlens": "qwen3.5-2b/jlens/Salesforce-wikitext/Qwen3.5-2B_jacobian_lens.pt"},
    "qwen3.5-4b": {
        "jlens": "qwen3.5-4b/jlens/Salesforce-wikitext/Qwen3.5-4B_jacobian_lens_n1000.pt"
    },
    "qwen3.5-9b": {
        "jlens-base": "qwen3.5-9b-pt/jlens/Salesforce-wikitext/Qwen3.5-9B-Base_jacobian_lens.pt"
    },
}
ARM_LABEL = {"jlens-base": "jlens (base-model lens: fitted on Qwen3.5-9B-Base)"}
SAMPLING = {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "max_new_tokens": 256, "k": 1}
# plan rows whose read needs something this producer does not do
UNSUPPORTED = ("introspection", "jlens_concept_pr")
ROW_SHA_EXCLUDE = ("note",)
# plan 0079 §2: each subject's even lens band (the README's inverter bands, olens.json read.layers);
# a subject is read and judged at the plan's own layers inside it (a subset, never a snap)
BAND: dict[str, tuple[int, ...]] = {
    "qwen3-8b": tuple(range(12, 35, 2)),
    "qwen3.5-0.8b": tuple(range(8, 23, 2)),
    "qwen3.5-2b": tuple(range(8, 23, 2)),
    "qwen3.5-4b": tuple(range(10, 31, 2)),
    "qwen3.5-9b": tuple(range(10, 31, 2)),
}
BATCH = {"qwen3-8b": 512}  # decode batch; default 1024 (Qwen3.5 hybrids: small KV cache)


def arms_of(subject: str) -> dict[str, dict[str, str]]:
    """{arm: {"kind": olens|jlens, "path": ...}} for a subject."""
    out = {a: {"kind": "olens", "path": p} for a, p in OLENS.get(subject, {}).items()}
    out |= {a: {"kind": "jlens", "path": p} for a, p in JLENS.get(subject, {}).items()}
    return out


def in_band(row: dict[str, Any], subject: str) -> dict[str, Any]:
    """The plan row with its layers cut to the subject's lens band (plan 0079 §2)."""
    band = set(BAND[subject])
    return {**row, "layers": [x for x in row["layers"] if x in band]}


def row_sha(row: dict[str, Any]) -> str:
    """sha256 of one plan row as ``wsbench plan`` writes it, minus the note (layers
    kept: a changed layer list is a changed read). The row's ``family`` is hashed as its
    pre-0101 key (``registry.frozen_name``, plan 0101 F14): a renamed family's stored cells
    keep their ``row_sha``."""
    from wsbench.registry import frozen_name

    clean = {k: v for k, v in row.items() if k not in ROW_SHA_EXCLUDE}
    if isinstance(clean.get("family"), str):
        clean["family"] = frozen_name(clean["family"])
    if isinstance(clean.get("extra"), dict):
        clean["extra"] = {k: v for k, v in clean["extra"].items() if k != "reads"}
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()


# ------------------------------------------------------------------------------ Modal side

try:
    import modal
except ImportError:  # assemble / tests run without modal
    modal = None  # type: ignore[assignment]

if modal is not None:
    CAUSAL_CONV1D_WHL = (
        "https://github.com/Dao-AILab/causal-conv1d/releases/download/v1.6.2.post1/"
        "causal_conv1d-1.6.2.post1%2Bcu12torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"
    )
    app = modal.App("wsb-0079-lens-readouts")
    hf_vol = modal.Volume.from_name("wsb-0079-hf", create_if_missing=True)
    image = (  # Agam's producer image (subject_wsbench_qwen_modal.py), the validated pins
        modal.Image.from_registry("nvidia/cuda:12.8.1-devel-ubuntu24.04", add_python="3.12")
        .apt_install("git")
        .pip_install("torch==2.9.1", index_url="https://download.pytorch.org/whl/cu128")
        .pip_install(
            "transformers==5.11.0",
            "peft==0.19.1",
            "accelerate>=1.0",
            "safetensors>=0.8.0",
            "huggingface_hub>=0.35",
            "numpy>=2.3",
            "einops>=0.8",
            "jinja2",
            "nvidia-cuda-nvcc-cu12==12.9.86",
            "flash-linear-attention==0.5.1",
        )
        .run_commands(f"pip install --no-deps '{CAUSAL_CONV1D_WHL}'")
        .env(
            {
                "HF_HOME": "/hf",
                "PYTHONUNBUFFERED": "1",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                "TRITON_CACHE_DIR": "/tmp/triton",
                "FLA_TILELANG": "0",
                "PYTHONPATH": "/root/wsb/src",
            }
        )
        .add_local_dir(WSB / "src", "/root/wsb/src", ignore=["**/__pycache__"])
    )
    MAX_CONTAINERS = int(os.environ.get("WSB_0079_MAX_CONTAINERS", "4"))  # plan 0079: <= 4

    @app.function(
        image=image,
        # WSB_0079_GPU="H100:2": one PEFT backend per GPU of a container, cells split across them
        gpu=os.environ.get("WSB_0079_GPU", "H100,H200,B200").split(","),
        timeout=6 * 3600,
        memory=65_536,
        cpu=8.0,
        volumes={"/hf": hf_vol},
        max_containers=MAX_CONTAINERS,
        retries=1,
    )
    def read_job(job: dict[str, Any]) -> dict[str, Any]:
        import traceback

        try:
            return {"k": job["k"], **_read_job(job)}
        except Exception:  # the driver reports it with its job; the rows stay pending
            return {"k": job["k"], "error": traceback.format_exc()[-3000:]}


def _download(repo: str, rev: str, pattern: str) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(repo, revision=rev, allow_patterns=[pattern], cache_dir="/hf/hub")


def _load_backend(hf_id: str, rev: str, device: str = "cuda:0") -> Any:
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from wsbench.produce.backend import Backend

    local = snapshot_download(hf_id, revision=rev, cache_dir="/hf/hub")
    tok = AutoTokenizer.from_pretrained(local)
    model = AutoModelForCausalLM.from_pretrained(local, dtype=torch.bfloat16, device_map=device)
    model.eval()
    return Backend(model=model, tokenizer=tok, device=device, model_id=hf_id)


def _olens_card(path: str) -> tuple[dict[str, Any], str]:
    d = _download(MORE_REPO, MORE_REV, f"{path}/*")
    card = json.loads(Path(d, path, "olens.json").read_text())
    adir = str(Path(d, card["adapter_subfolder"]))
    if not Path(adir, "adapter_model.safetensors").exists():
        d = _download(MORE_REPO, MORE_REV, f"{card['adapter_subfolder']}/*")
        adir = str(Path(d, card["adapter_subfolder"]))
    return card, adir


def _attach_lora(backend: Any, adir: str) -> None:
    """PEFT only WARNS on unmatched keys and lora_B starts at zero: refuse a silent no-op
    (Agam's ``_assert_adapter_loaded``) and any adapter key PEFT did not load."""
    from peft import PeftModel
    from safetensors import safe_open

    blocks = backend.blocks
    backend.model = PeftModel.from_pretrained(backend.model, adir)
    backend.model.eval()
    # this instance only (Modal reuses warm containers: never patch the shared Backend class)
    patched = {"blocks": property(lambda _s: blocks)}
    backend.__class__ = type("PeftBackend", (type(backend),), patched)
    b = [p for n, p in backend.model.named_parameters() if "lora_B" in n]
    if not b or all(float(p.detach().abs().max()) == 0.0 for p in b):
        raise RuntimeError(f"{adir}: LoRA did not load (no nonzero lora_B)")
    with safe_open(str(Path(adir, "adapter_model.safetensors")), "pt") as f:
        n_file = len([k for k in f.keys() if "lora_" in k])  # noqa: SIM118
    n_model = len([n for n, _ in backend.model.named_parameters() if "lora_" in n])
    if n_model != n_file:
        raise RuntimeError(f"{adir}: {n_file} LoRA tensors in the file, {n_model} on the model")


def _carrier(tok: Any, template: str, layer: int, slot_char: str, slot_id: int) -> tuple:
    out = tok.apply_chat_template(
        [{"role": "user", "content": template.format(layer=layer, char=slot_char)}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    ids = list(out["input_ids"] if hasattr(out, "keys") else out)
    slots = [i for i, t in enumerate(ids) if t == slot_id]
    if len(slots) != 1:
        raise RuntimeError(f"L{layer}: slot id {slot_id} occurs {len(slots)}x in the carrier")
    return ids, slots[0]


def _check_carrier(backend: Any, rd: dict[str, Any], layer: int, carrier: tuple) -> bool:
    """olens.json's slot char must encode to exactly ``[slot_id]`` (the training contract, plan
    0079 §2); returns whether the bench's own search (``OLens._carrier``) agrees. Diagnostic only:
    on Qwen3-8B that search picks U+320E while the checkpoint was trained on U+321C."""
    from wsbench.produce.methods import OLens

    tok = backend.tokenizer
    if tok(rd["slot_char"], add_special_tokens=False)["input_ids"] != [rd["slot_id"]]:
        raise RuntimeError(f"slot char {rd['slot_char']!r} does not encode to [{rd['slot_id']}]")
    ref = OLens(lora="", prompt=rd["prompt_template"])
    ref._b = backend
    return ref._carrier(layer) == (list(carrier[0]), carrier[1])


def _cells(backend: Any, specs: list[dict[str, Any]]) -> tuple[list[tuple], list[str]]:
    """(row_sha, id, layer, pos, token, h) per plan cell; ids with no position are reported."""
    from wsbench.produce.producer import _positions
    from wsbench.produce.render import render
    from wsbench.readplan import ReadSpec

    cells, empty = [], []
    for d in specs:
        s = ReadSpec(**d["row"])
        r = render(s, backend.tokenizer)
        pos = _positions(s.positions, r.tokens)
        if not pos:
            empty.append(d["row_sha"])
            continue
        idx = [q % len(r) for q in pos]
        acts = backend.capture(r.ids, list(s.layers), idx)
        for layer in s.layers:
            for i, (q, j) in enumerate(zip(pos, idx, strict=True)):
                cells.append((d["row_sha"], s.id, layer, q, r.decoded[j], acts[layer][i]))
    return cells, empty


def _stop_ids(backend: Any) -> list[int]:
    tok = backend.tokenizer
    ids = {tok.eos_token_id, tok.convert_tokens_to_ids("<|im_end|>")}
    gen = backend.model.generation_config.eos_token_id
    ids |= set(gen if isinstance(gen, list) else [gen] if gen is not None else [])
    return sorted(i for i in ids if isinstance(i, int) and i >= 0)


def _olens_read(backend: Any, card: dict[str, Any], cells: list[tuple], batch: int) -> tuple:
    import torch

    rd = card["read"]
    tok = backend.tokenizer
    embed = backend.model.get_input_embeddings()
    stop = _stop_ids(backend)
    pad = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id
    texts: list[str] = [""] * len(cells)
    norms: dict[int, dict[str, float]] = {}
    bench_agrees: dict[int, bool] = {}
    by_layer: dict[int, list[int]] = {}
    for ci, c in enumerate(cells):
        by_layer.setdefault(c[2], []).append(ci)
    for layer, cis in sorted(by_layer.items()):
        ids, slot = _carrier(tok, rd["prompt_template"], layer, rd["slot_char"], rd["slot_id"])
        bench_agrees[layer] = _check_carrier(backend, rd, layer, (ids, slot))
        with torch.no_grad():
            base = embed(torch.tensor([ids], device=backend.device))[0]
        hn, inn = [], []
        for lo in range(0, len(cis), batch):
            chunk = cis[lo : lo + batch]
            h = torch.stack([cells[ci][5] for ci in chunk]).to(backend.device).float()
            if rd["transform"] == "scaled":
                v = float(rd["global_scale"]) * h
            elif rd["transform"] == "unit":
                v = float(rd["alpha"]) * h / h.norm(dim=-1, keepdim=True).clamp_min(1e-9)
            else:
                raise ValueError(f"unknown transform {rd['transform']!r}")
            hn.append(h.norm(dim=-1).cpu())
            inn.append(v.norm(dim=-1).cpu())
            e = base.unsqueeze(0).repeat(len(chunk), 1, 1).clone()
            e[:, slot, :] = v.to(e.dtype)
            with torch.no_grad():
                out = backend.model.generate(
                    inputs_embeds=e,
                    attention_mask=torch.ones(len(chunk), len(ids), device=backend.device).long(),
                    do_sample=True,
                    temperature=SAMPLING["temperature"],
                    top_p=SAMPLING["top_p"],
                    top_k=SAMPLING["top_k"],
                    max_new_tokens=SAMPLING["max_new_tokens"],
                    eos_token_id=stop,
                    pad_token_id=pad,
                )
            for ci, t in zip(chunk, tok.batch_decode(out, skip_special_tokens=True), strict=True):
                texts[ci] = t.strip()
        norms[layer] = {
            "median_h": round(float(torch.cat(hn).median()), 2),
            "median_injected": round(float(torch.cat(inn).median()), 1),
        }
    info = {"norms": norms, "stop_ids": stop, "carrier_matches_bench": bench_agrees}
    return [{"samples": [t]} for t in texts], info


def _jlens_read(backend: Any, filename: str, cells: list[tuple], batch: int) -> tuple:
    """wsbench JLens's cosine readout ``(W_U J h) / ||J^T W_U[t]||``, batched per layer; a few
    cells are re-read through ``JLens.read`` itself and must agree (the batching is exact)."""
    import torch
    from huggingface_hub import hf_hub_download

    from wsbench.produce.methods import TOP_K, JLens
    from wsbench.produce.render import display_tokens

    path = hf_hub_download(JLENS_REPO, filename, revision=JLENS_REV, cache_dir="/hf/hub")
    jac = _load_jacobians_local(path, backend.device)
    w_u = backend.unembed.float()
    out: list[dict[str, Any]] = [{}] * len(cells)
    by_layer: dict[int, list[int]] = {}
    for ci, c in enumerate(cells):
        by_layer.setdefault(c[2], []).append(ci)
    for layer, cis in sorted(by_layer.items()):
        if layer >= jac.shape[0]:
            raise ValueError(f"layer {layer} beyond the lens's {jac.shape[0]} source layers")
        denom = (w_u @ jac[layer]).norm(dim=1).clamp_min(1e-9)
        for lo in range(0, len(cis), batch):
            chunk = cis[lo : lo + batch]
            h = torch.stack([cells[ci][5] for ci in chunk]).to(backend.device).float()
            scores = ((h @ jac[layer].T) @ w_u.T) / denom
            vals, ids = torch.topk(scores, TOP_K, dim=-1)
            for k, ci in enumerate(chunk):
                out[ci] = {
                    "tokens": display_tokens(backend.tokenizer, ids[k].tolist()),
                    "scores": [round(v, 4) for v in vals[k].tolist()],
                }
    # exactness check against the bench's own per-vector method on up to 8 cells
    ref = JLens(repo=JLENS_REPO, filename=filename)
    ref._b, ref._jac, ref._w_u = backend, jac, w_u
    for ci in range(0, len(cells), max(1, len(cells) // 8))[:8]:
        r = ref.read(cells[ci][5], cells[ci][2])
        if not same_topk(r.tokens, r.scores, out[ci]["tokens"], out[ci]["scores"]):
            raise RuntimeError(
                f"batched J-lens != JLens.read at cell {ci}: {r.tokens} {r.scores} vs "
                f"{out[ci]['tokens']} {out[ci]['scores']}"
            )
    return out, {"lens_layers": int(jac.shape[0])}


def same_topk(t1: list, s1: list, t2: list, s2: list, tol: float = 1e-3) -> bool:
    """Two top-k readouts of the same vector agree: scores equal within ``tol`` (relative, floor
    1) rank by rank, and the token lists differ only where scores tie within ``tol`` (a batched
    and a per-vector matmul may order near-equal scores differently, or swap the k-th token)."""
    close = lambda a, b: abs(a - b) <= tol * max(1.0, abs(a))  # noqa: E731
    if len({len(t1), len(t2), len(s1), len(s2)}) > 1:
        return False
    if not all(close(a, b) for a, b in zip(s1, s2, strict=True)):
        return False
    for i, (a, b) in enumerate(zip(t1, t2, strict=True)):
        if a != b:
            tied = [j for j in range(len(s1)) if close(s1[j], s1[i])]
            k_edge = close(s1[i], s1[-1])  # a token swapped in at the k-th boundary
            if b not in [t1[j] for j in tied] and not k_edge:
                return False
    return True


def _load_jacobians_local(path: str, device: str) -> Any:
    import torch

    obj = torch.load(path, map_location="cpu", weights_only=False)
    jac = obj["J"] if "J" in obj else obj["jacobians"]
    if isinstance(jac, dict):
        layers = sorted(int(k) for k in jac)
        stacked = torch.stack([jac[L] if L in jac else jac[str(L)] for L in layers]).float()
    else:
        stacked, layers = jac.float(), list(range(jac.shape[0]))
    if layers != list(range(len(layers))):
        raise ValueError(f"{path}: source layers not contiguous from 0: {layers}")
    return stacked.to(device)


def _olens_multi(job, backend, card, adir, cells, batch) -> tuple:
    """``_olens_read`` over every GPU of the container: device 0 in this process, each other
    device in a subprocess pinned to it (``CUDA_VISIBLE_DEVICES``; threads race in Triton's
    autotuner), the cells cut into contiguous chunks (order kept)."""
    import shutil
    import subprocess
    import sys
    import tempfile

    import torch

    n = torch.cuda.device_count()
    if n < 2 or len(cells) < 2 * batch:
        return _olens_read(backend, card, cells, batch)
    k = -(-len(cells) // n)
    chunks = [cells[i * k : (i + 1) * k] for i in range(n)]
    tmp = Path(tempfile.mkdtemp(prefix="olens_"))
    procs = []
    for i in range(1, n):
        src = tmp / f"in{i}.pt"
        torch.save({"job": {k2: v for k2, v in job.items() if k2 != "specs"}, "card": card,
                    "adir": adir, "batch": batch, "seed": int(job["seed"]) + i,
                    "cells": [c[:5] for c in chunks[i]],
                    "h": torch.stack([c[5] for c in chunks[i]])}, src)  # fmt: skip
        code = (
            f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); "
            f"import {Path(__file__).stem} as m; m._worker({str(src)!r})"
        )
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(i)}
        procs.append(subprocess.Popen([sys.executable, "-c", code], env=env))
    try:
        reads0, info0 = _olens_read(backend, card, chunks[0], batch)
        parts = [(reads0, info0)]
        for i, pr in enumerate(procs, start=1):
            if pr.wait() != 0:
                raise RuntimeError(f"GPU worker {i} exited {pr.returncode}")
            res = json.loads((tmp / f"in{i}.pt.out.json").read_text())
            parts.append((res["reads"], res["info"]))
    finally:  # a failed job leaves no live worker and no stacked activations on disk
        for pr in procs:
            if pr.poll() is None:
                pr.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    reads = [r for part, _ in parts for r in part]
    if len(reads) != len(cells):
        raise RuntimeError(f"multi-GPU decode returned {len(reads)} of {len(cells)} cells")
    return reads, {**info0, "gpus": n, "norms_by_gpu": [p[1]["norms"] for p in parts]}


def _worker(src: str) -> None:
    """One extra GPU of ``_olens_multi`` (its only visible device is cuda:0)."""
    import torch

    d = torch.load(src, weights_only=False)
    backend = _load_backend(d["job"]["hf_id"], d["job"]["revision"])
    _attach_lora(backend, d["adir"])
    torch.manual_seed(d["seed"])
    cells = [(*c, h) for c, h in zip(d["cells"], d["h"], strict=True)]
    reads, info = _olens_read(backend, d["card"], cells, d["batch"])
    info = json.loads(json.dumps(info, default=str))
    Path(src + ".out.json").write_text(json.dumps({"reads": reads, "info": info}))


def _read_job(job: dict[str, Any]) -> dict[str, Any]:
    import torch

    t0 = time.time()
    backend = _load_backend(job["hf_id"], job["revision"])
    meta: dict[str, Any] = {}
    if job["kind"] == "olens":
        card, adir = _olens_card(job["path"])
        if card["base_model"] != job["hf_id"]:
            raise RuntimeError(f"{job['path']}: base model {card['base_model']} != {job['hf_id']}")
        if card["read"].get("sampling_of_record") != SAMPLING:
            raise RuntimeError(f"{job['path']}: sampling of record != {SAMPLING}")
        _attach_lora(backend, adir)
        meta["read"] = card["read"]
    hf_vol.commit()  # the downloaded weights / adapters / lenses persist for the next container
    cells, empty = _cells(backend, job["specs"])
    t_cap = time.time() - t0
    torch.manual_seed(int(job["seed"]))
    if job["kind"] == "olens":
        reads, info = _olens_multi(job, backend, card, adir, cells, int(job.get("batch", 256)))
    else:
        reads, info = _jlens_read(backend, job["path"], cells, int(job.get("batch", 512)))
    rows = []
    for c, r in zip(cells, reads, strict=True):
        rows.append({"row_sha": c[0], "row": {"id": c[1], "layer": c[2], "pos": c[3],
                                              "token": c[4], **r}})  # fmt: skip
    n_empty = sum(1 for r in reads if r.get("samples") == [""])
    n_cells = len(cells)
    del backend, cells  # free the GPU before a warm container's next job
    torch.cuda.empty_cache()
    return {
        "rows": rows,
        "empty_ids": empty,
        "meta": {
            **meta,
            **info,
            "n_cells": n_cells,
            "n_empty_samples": n_empty,
            "capture_s": round(t_cap),
            "total_s": round(time.time() - t0),
            "gpu": torch.cuda.get_device_name(0),
        },
    }


# ------------------------------------------------------------------------------ local side


def _subject(subject: str) -> Any:
    from wsbench.adapt.subjects import SUBJECTS

    s = SUBJECTS[subject]
    root = os.environ.get("WSB_BANK_ROOT", "")
    if Path(root).name != subject:
        raise SystemExit(f"WSB_BANK_ROOT={root!r} is not adapted/{subject}")
    return s


def _families(arg: str | None) -> list[str]:
    from wsbench import readplan

    fams = arg.split(",") if arg else readplan.families()
    return [f for f in fams if f not in UNSUPPORTED]


def _plan_rows(family: str, subject: str) -> list[dict[str, Any]]:
    """The family's plan rows (today's adapted plan) cut to the subject's read set."""
    from wsbench import readplan

    rows = [in_band(s.row(), subject) for s in readplan.plan(family, layers=None)]
    return [r for r in rows if r["layers"]]


def store_path(store: Path, subject: str, arm: str, family: str) -> Path:
    """Where a family's NEW cells are written: always ``<current key>.jsonl``."""
    return store / subject / arm / f"{family}.jsonl"


def _store_ids(path: Path) -> set[str]:
    """The item ids of a store file's rows (``{"row_sha", "row": {"id", ...}}``)."""
    out = set()
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            try:
                row = json.loads(line).get("row")
            except (json.JSONDecodeError, AttributeError):
                continue
            if isinstance(row, dict) and row.get("id") is not None:
                out.add(str(row["id"]))
    return out


def _store_owner(path: Path, family: str) -> str | None:
    """Which family of ``family``'s renamed pair the store file's ids belong to (plan 0101
    §5.9); None for an empty file. Ids of both, or of neither, are a ``RenamedKey``."""
    from wsbench import registry

    ids = _store_ids(path)
    if not ids:
        return None
    who = registry.owner(str(registry.shared_key(family)), ids=ids)
    if who is None:
        raise registry.RenamedKey(f"{path}: its rows are in neither family of the renamed pair")
    return who


def store_files(store: Path, subject: str, arm: str, family: str) -> list[Path]:
    """The store files a family's cells are READ from: ``<key>.jsonl`` for every key the family
    has held (``registry.lookup_names``); a file under the bare key of a renamed pair only when
    its ids are this family's."""
    from wsbench import registry

    bare = registry.shared_key(family)
    out = []
    for key in registry.lookup_names(family):
        path = store / subject / arm / f"{key}.jsonl"
        if not path.exists():
            continue
        if key == bare and _store_owner(path, family) not in (family, None):
            continue
        out.append(path)
    return out


def check_store_writable(path: Path, family: str) -> None:
    """Before a run's first append to ``store_path``: it must be absent, empty, or this
    family's. The partner's file (written before the rename) is never appended to."""
    from wsbench import registry

    if registry.shared_key(family) is None or not path.exists():
        return
    who = _store_owner(path, family)
    if who not in (family, None):
        raise SystemExit(
            f"{path} is the store of {who!r}, written before the plan-0101 rename; run "
            f"`scripts/migrate_0101.py set {path.parent.parent}` or move it to {who}.jsonl"
        )


def stored_shas(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    # split on "\n" only, never splitlines(): a sample may hold a raw U+2028 (valid inside JSON)
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            try:
                out.add(json.loads(line)["row_sha"])
            except json.JSONDecodeError:  # a line cut by a killed driver: that row is re-read
                continue
    return out


def _est_cells(row: dict[str, Any], tok: Any) -> int:
    from wsbench.produce.producer import _positions
    from wsbench.produce.render import render
    from wsbench.readplan import ReadSpec

    try:
        r = render(ReadSpec(**row), tok)
        return max(1, len(_positions(row["positions"], r.tokens))) * len(row["layers"])
    except Exception:  # an estimate only; the remote render is authoritative
        return 50 * len(row["layers"])


def jobs_for(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Pending rows (no stored cells for their row_sha), packed into jobs of ~``--job-cells``."""
    from transformers import AutoTokenizer

    subj = _subject(args.subject)
    tok = AutoTokenizer.from_pretrained(subj.hf_id, revision=subj.revision)
    jobs = []
    for arm in args.arm.split(","):
        spec = arms_of(args.subject)[arm]
        # one arm's pending rows of EVERY family packed together (a refresh adds a few rows to
        # many families: per-family jobs would each pay a container's model load)
        pend: list[dict[str, Any]] = []
        for fam in _families(args.families):
            rows = _plan_rows(fam, args.subject)
            if args.limit:
                rows = rows[: args.limit]
            have: set[str] = set()
            for path in store_files(Path(args.store), args.subject, arm, fam):
                have |= stored_shas(path)
            new = [{"row_sha": row_sha(r), "row": r, "family": fam} for r in rows
                   if row_sha(r) not in have]  # fmt: skip
            if new:  # refused before any job is launched: nothing is appended
                check_store_writable(store_path(Path(args.store), args.subject, arm, fam), fam)
            pend += new
        pack: list[dict[str, Any]] = []
        n = 0
        for p in pend:
            pack.append(p)
            n += _est_cells(p["row"], tok)
            if n >= args.job_cells:
                jobs.append(_job(args, subj, arm, spec, pack, len(jobs)))
                pack, n = [], 0
        if pack:
            jobs.append(_job(args, subj, arm, spec, pack, len(jobs)))
    return jobs


def _job(args, subj, arm, spec, pack, k) -> dict[str, Any]:
    from wsbench.registry import frozen_name

    fam = pack[0]["family"]
    key = f"{arm}|{frozen_name(fam)}|{pack[0]['row_sha']}"  # plan 0101 F14: the pre-rename key
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    fams = sorted({p["family"] for p in pack})
    label = fams[0] + (f"+{len(fams) - 1}" if len(fams) > 1 else "")
    return {"subject": args.subject, "hf_id": subj.hf_id, "revision": subj.revision, "arm": arm,
            "kind": spec["kind"], "path": spec["path"], "family": label, "specs": pack,
            "seed": seed, "batch": args.batch or BATCH.get(args.subject, 1024), "k": k}  # fmt: skip


def produce(args: argparse.Namespace) -> None:
    jobs = jobs_for(args)
    store = Path(args.store)
    log = store / args.subject / "produce_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(jobs)} jobs, {sum(len(j['specs']) for j in jobs)} rows pending", flush=True)
    if not jobs or args.dry_run:
        return
    with modal.enable_output() if args.verbose else _Null(), app.run():
        by_k = {j["k"]: j for j in jobs}
        for res in read_job.map(jobs, order_outputs=False, return_exceptions=True):
            job = by_k.get(res.get("k")) if isinstance(res, dict) else None
            if job is None:  # an exception carries no job: report, the rows stay pending
                print(f"FAILED job: {res!r}"[:2000], flush=True)
                _append(log, {"error": repr(res)[:2000], "ts": time.time()})
                continue
            tag = f"{job['arm']}/{job['family']} ({len(job['specs'])} rows)"
            if "error" in res:
                print(f"FAILED {tag}: {res['error'][-600:]}", flush=True)
                _append(log, {"job": tag, "error": res["error"], "ts": time.time()})
                continue
            fam_of = {d["row_sha"]: d["family"] for d in job["specs"]}  # a job spans families
            out: dict[str, list[str]] = {}
            for r in res["rows"]:
                out.setdefault(fam_of[r["row_sha"]], []).append(json.dumps(r, ensure_ascii=False))
            for d in job["specs"]:  # a row with no position: a marker so it is not re-read
                if d["row_sha"] in res["empty_ids"]:
                    out.setdefault(d["family"], []).append(
                        json.dumps({"row_sha": d["row_sha"], "row": None})
                    )
            for fam, lines in out.items():
                dst = store_path(store, job["subject"], job["arm"], fam)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open("a", encoding="utf-8") as fh:
                    fh.write("".join(line + "\n" for line in lines))
            _append(log, {"job": tag, **res["meta"], "ts": time.time()})
            print(
                f"done {tag}: {res['meta']['n_cells']} cells, {res['meta']['total_s']}s, "
                f"empty {res['meta']['n_empty_samples']}, {res['meta']['gpu']}",
                flush=True,
            )


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _append(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def assemble(args: argparse.Namespace) -> None:
    """The CURRENT plan's cells from the store -> ``<out>/<family>.jsonl`` + sidecar. A row with
    no stored cells is reported (and the family left out unless ``--partial``)."""
    from wsbench import reads as reads_mod
    from wsbench.readouts import refuse_partner_file, write_sidecar

    _subject(args.subject)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    spec = arms_of(args.subject)[args.arm]
    report = {}
    for fam in _families(args.families):
        rows = _plan_rows(fam, args.subject)
        if not rows:  # no in-band row (or an empty bank): no file
            continue
        cells: dict[str, list[dict[str, Any]]] = {}
        for src in store_files(Path(args.store), args.subject, args.arm, fam):
            for line in src.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:  # a line cut by a killed driver
                        continue
                    cells.setdefault(d["row_sha"], [])
                    if d["row"] is not None:
                        cells[d["row_sha"]].append(d["row"])
        missing = [r["id"] for r in rows if row_sha(r) not in cells]
        no_pos = [r["id"] for r in rows if row_sha(r) in cells and not cells[row_sha(r)]]
        report[fam] = {"items": len(rows), "missing": len(missing), "no_position": no_pos}
        refuse_partner_file(out / f"{fam}.jsonl", fam)  # before it is unlinked or overwritten
        if missing and not args.partial:
            stale = out / f"{fam}.jsonl"
            for f in (stale, stale.with_name(stale.name + ".meta.json")):
                f.unlink(missing_ok=True)  # an older file of this family would judge a stale set
            print(f"{fam}: {len(missing)}/{len(rows)} rows not read yet; skipped", flush=True)
            continue
        dst = out / f"{fam}.jsonl"
        seen = set()
        with dst.open("w", encoding="utf-8") as fh:
            for r in rows:
                for c in cells.get(row_sha(r), []):
                    k = (c["id"], c["layer"], c["pos"])
                    if k not in seen:  # a re-read row keeps its first cells (load keeps first)
                        seen.add(k)
                        fh.write(json.dumps(c, ensure_ascii=False) + "\n")
        write_sidecar(
            dst,
            reads="full",
            sampling="prose1" if spec["kind"] == "olens" else "tokens10",
            reader=ARM_LABEL.get(args.arm, args.arm),
            arm=args.arm,
            layers=sorted({x for r in rows for x in r["layers"]}),
            plan_sha=reads_mod.plan_sha(fam),
            source={
                "repo": MORE_REPO if spec["kind"] == "olens" else JLENS_REPO,
                "revision": MORE_REV if spec["kind"] == "olens" else JLENS_REV,
                "path": spec["path"],
            },
        )
        print(f"{fam}: {len(rows)} rows -> {dst}", flush=True)
    (out / "assemble_report.json").write_text(json.dumps(report, indent=1) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("produce", "assemble", "jobs"):
        p = sub.add_parser(name)
        p.add_argument("--subject", required=True)
        p.add_argument("--arm", required=True, help="comma-separated arms (produce/jobs)")
        p.add_argument("--store", required=True)
        p.add_argument("--families", default=None)
        p.add_argument("--limit", type=int, default=0, help="rows per family (smoke)")
        if name == "assemble":
            p.add_argument("--out", required=True)
            p.add_argument("--partial", action="store_true")
        else:
            p.add_argument("--job-cells", type=int, default=40_000)
            p.add_argument("--batch", type=int, default=0, help="0 = the subject's BATCH")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "assemble":
        assemble(args)
    elif args.cmd == "jobs":
        args.dry_run = True
        produce(args)
    else:
        produce(args)


if __name__ == "__main__":
    main()
