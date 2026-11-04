"""jlens_concept_pr on GLM-5.3 (nvidia/GLM-5.3-NVFP4, 78 blocks): ``adapt_jlens.py``'s recipe read
through GLM's own fitted J-lens (global-workspace ``scripts/glm53_aff/jlens_fit_modal.py``: Modal
volume ``glm53-jlens``, ``glm-5.3-nvfp4/lens.pt``, sources 0..76, target block 77).

GLM does not fit ``adapt_jlens_modal.py``'s single-H200 HF ``generate`` path (754B NVFP4 MoE), so:

* ``rollout`` (local; generation on the subject's own adapt app, ``RemoteRunner``): the frozen
  bank's 299 seeds re-rendered for GLM by ``adapt_jlens.seed_ids`` (chat: GLM's pinned thinking-off
  template; pt: ``[gMASK]<sop>`` + 128 of its own tokens), sampled T=1.0 / top-p 1 / top-k off /
  512 new tokens, seed 7, on vLLM (the HF stack has no KV cache; vLLM only writes the TEXT, never
  a residual). One read position per rollout by ``pick_read_position`` (same rng as the source).
* ``read`` (Modal, one 8-GPU node, H200 first: batch-invariant): the vendored HF stack
  (``Glm53Text``, the fit's own loader), one rollout per forward truncated at its read position,
  block outputs at the read layers; the cosine readout of ``jlens_eval.py``
  (``(W_U J h) / ||J^T W_U[t]||``, W_U = ``lm_head``, untied), top-10 display tokens. Also a
  sanity rate per layer (current / next token in the top-10) and the residuals (volume).
* ``assemble`` (local): ``manifest.json`` + ``items.json`` + ``gen-jlens-pr-jlens/`` for the
  shipped layers (``--ship``), as ``adapt_jlens.py`` assembles.

    export WSB_GW=/path/to/global-workspace   # a checkout with scripts/glm53_aff + src/jlens
    python scripts/adapt_jlens_glm53_modal.py rollout --work W
    modal run scripts/adapt_jlens_glm53_modal.py::read_main --work W
    python scripts/adapt_jlens_glm53_modal.py assemble --work W --dst adapted/glm-5.3 \\
        --ship 34,39,44,49,54,58,63,68,73
"""

import argparse
import json
import os
import random
import shutil
import sys
from pathlib import Path
from typing import Any

import modal

WSB = Path(__file__).resolve().parents[1]
GW = Path(os.environ.get("WSB_GW", "/workspace/agam/global-workspace"))
if modal.is_local():
    for p in (GW / "scripts/glm53_aff", WSB / "src", WSB / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
from common import EPHEMERAL_DISK_MB, HF_GLM_IMAGE, MODEL_DIR, WEIGHTS, weights_vol  # noqa: E402

MODEL = "glm-5.3"  # wsbench.adapt Subject key
HF_ID, REVISION = "nvidia/GLM-5.3-NVFP4", "e3b8f9f2fad29727dfa95e766c5cac18ea1414bf"
TAG = "glm-5.3-nvfp4"  # the fit's tag on the lens volume
JL = "/jl"
LENS = f"{JL}/{TAG}/lens.pt"
N_LAYERS, D_MODEL, N_SOURCES = 78, 6144, 77  # lens rows 0..76; block 77 is the target
MAX_SEQ = 2048  # the DSA indexer bypass is exact only for S <= index_topk (2048)
K = 10
jl_vol = modal.Volume.from_name("glm53-jlens", version=2)
app = modal.App("adapt-jlens-glm53")
# GLM's reply-ending tokens (generation_config eos ids); a sampled reply is cut at the first one
STOP_TOKENS = ("<|endoftext|>", "<|user|>", "<|observation|>")


# ------------------------------------------------------------------ pure helpers (tested)


def cut_at_stop(ids: list[int], stop: set[int]) -> list[int]:
    """A sampled reply up to (excluding) its first stop token."""
    out = []
    for t in ids:
        if int(t) in stop:
            break
        out.append(int(t))
    return out


def display(token: str | None) -> str:
    """``jlens_eval.py``'s display form: byte-level BPE with ``Ġ`` / ``▁`` as a space."""
    return token.replace("Ġ", " ").replace("▁", " ") if isinstance(token, str) else ""


def manifest_entry(row: dict) -> dict:
    """``capture_acts.py``'s manifest entry for one rollout (the frozen bank's schema;
    ``n_pos`` = the rollout's length, the acts file itself is not shipped)."""
    return {
        "label": row["label"],
        "family": row["family"],
        "file": f"{row['label']}.safetensors",
        "n_pos": len(row["input_ids"]),
        "targets": [],
        "look_for": "",
        "eval_positions": list(row["eval_positions"]),
        "units": None,
        "contract": None,
    }


def read_layers() -> list[int]:
    """The family's grid of record (``readplan.GRID``) at GLM's depth, snapped to its band."""
    from wsbench.adapt import subjects
    from wsbench.readplan import GRID

    s = subjects.SUBJECTS[MODEL]
    return subjects.remap_layers(GRID, s.n_layers, s.read_band)


# ------------------------------------------------------------------ rollout (local + adapt app)


def rollout(work: Path, max_new: int = 512, seed: int = 7) -> dict:
    import adapt_jlens

    sys.path.insert(0, str(GW / "scripts/oracle_lens_evals"))
    from jlens_pr.items import pick_read_position

    from wsbench.adapt.run import _runner

    os.environ.setdefault("ADAPT_BACKEND", "modal")
    src = json.loads(adapt_jlens.SRC_ITEMS.read_text())
    runner = _runner(MODEL)
    tok = runner.tok
    stop = {int(tok.eos_token_id)} | {int(tok.convert_tokens_to_ids(t)) for t in STOP_TOKENS}
    pids = [adapt_jlens.seed_ids(r, tok) for r in src]
    outs = runner.generate(pids, 1.0, max_new, seed=seed, top_p=1.0)
    rng = random.Random(seed)
    rows, n_empty, n_trunc, per_source = [], 0, 0, {}
    for r, p, o in zip(src, pids, outs, strict=True):
        oids = cut_at_stop(list(o.get("ids") or []), stop)
        if not oids:
            n_empty += 1
            continue
        n_trunc += len(oids) >= max_new
        per_source[r["source"]] = per_source.get(r["source"], 0) + 1
        pos = pick_read_position(len(p), len(oids), rng)
        rows.append({
            **{k: r[k] for k in ("label", "family", "source", "source_id", "seed_key")},
            "input_ids": [*p, *oids], "prompt_len": len(p), "eval_positions": [pos],
            "targets": [], "look_for": "", "render": "plain",
        })  # fmt: skip
    work.mkdir(parents=True, exist_ok=True)
    (work / "items.json").write_text(json.dumps(rows))
    meta = {
        "n_items": len(rows), "n_empty_rollouts": n_empty, "n_hit_max_new": n_trunc,
        "per_source": per_source, "read_region": "generated_only",
        "rollout_sampling": {"temperature": 1.0, "top_p": 1.0, "top_k": 0, "max_new": max_new,
                             "seed": seed, "engine": f"vllm ({runner.__class__.__name__}, "
                             f"Modal app of Subject {MODEL!r})"},
        "render": "chat: GLM-5.3 pinned thinking-off template; pt: [gMASK]<sop> + 128 tokens",
    }  # fmt: skip
    (work / "items_manifest.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))
    return meta


# ------------------------------------------------------------------ read (Modal, HF stack)


def _load() -> tuple[Any, Any]:
    """The fit's loader (jlens_fit_modal._load): all 78 blocks, grouped experts, indexer bypass."""
    import torch
    from transformers import AutoTokenizer

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True, warn_only=True)
    from global_workspace.glm53_aff import runtime

    hf = runtime._import_vendor()
    local = runtime.local_model_dir(MODEL_DIR, n_layers=None)
    gm = hf.Glm53Text(local, "nvfp4", n_layers=None)
    gm.load()
    hf.set_experts_impl("grouped", model=gm)
    hf.set_indexer_bypass(gm, True)
    gm.model.eval()
    for p in gm.parameters():
        p.requires_grad_(False)
    return gm, AutoTokenizer.from_pretrained(local)


@app.function(
    image=HF_GLM_IMAGE,
    gpu=["H200:8", "B300:8"],
    volumes={WEIGHTS: weights_vol, JL: jl_vol},
    timeout=6 * 3600,
    memory=1_048_576,
    cpu=64,
    ephemeral_disk=EPHEMERAL_DISK_MB,
)
def read(items: list[dict], layers: list[int], k: int = K) -> dict:
    import time

    import jlens
    import torch

    assert all(0 <= ly < N_SOURCES for ly in layers), f"lens rows are 0..{N_SOURCES - 1}: {layers}"
    t0 = time.time()
    gm, tok = _load()
    print(f"[read] loaded in {round(time.time() - t0)} s on {torch.cuda.get_device_name(0)}",
          flush=True)  # fmt: skip
    dev = gm.devN
    lens = jlens.JacobianLens.load(LENS)
    assert lens.d_model == D_MODEL, lens.d_model
    jac = {ly: lens.jacobians[ly].to(dev, torch.float32) for ly in layers}
    n_prompts = int(lens.n_prompts)
    del lens
    w_u = gm.lm_head.weight.detach().to(dev, torch.float32)  # [vocab, d]
    denom = {ly: (w_u @ jac[ly]).norm(dim=1).clamp_min(1e-9) for ly in layers}  # ||J^T W_U[t]||
    disp = [display(t) for t in tok.convert_ids_to_tokens(list(range(int(w_u.shape[0]))))]
    rows, resid, hits = [], {}, {ly: {"cur": 0, "next": 0, "n": 0} for ly in layers}
    for n, it in enumerate(items):
        pos = int(it["eval_positions"][0])
        ids = it["input_ids"][: pos + 1]  # causal: nothing after the read position matters
        assert len(ids) <= MAX_SEQ, (it["label"], len(ids))
        out = gm(torch.tensor([ids]), capture_layers=list(layers), capture_positions=[pos],
                 return_logits=False)["h_cap"]  # fmt: skip
        hs = torch.stack([out[ly][0, 0] for ly in layers])  # [layers, d] fp32
        resid[it["label"]] = hs.to(torch.bfloat16)
        h = hs.to(dev)
        for li, ly in enumerate(layers):
            scores = (w_u @ (jac[ly] @ h[li])) / denom[ly]
            vals, top = torch.topk(scores, k)
            top_ids, top_vals = top.tolist(), vals.tolist()
            cur = int(it["input_ids"][pos])
            nxt = int(it["input_ids"][pos + 1]) if pos + 1 < len(it["input_ids"]) else None
            hits[ly]["n"] += 1
            hits[ly]["cur"] += cur in top_ids
            hits[ly]["next"] += nxt is not None and nxt in top_ids
            rows.append({
                "label": it["label"], "family": it["family"], "layer": ly, "pos": pos,
                "token": disp[cur], "samples": [disp[i] for i in top_ids],
                "scores": [round(v, 4) for v in top_vals],
            })  # fmt: skip
        if n % 25 == 0:
            print(f"[read] {n + 1}/{len(items)} ({round(time.time() - t0)} s)", flush=True)
    sanity = {ly: {"current_in_top10": round(c["cur"] / c["n"], 4),
                   "next_in_top10": round(c["next"] / c["n"], 4)}
              for ly, c in hits.items()}  # fmt: skip
    out_dir = Path(f"{JL}/{TAG}/bank_reads")
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"layers": layers, "resid": resid}, out_dir / "resid.pt")
    (out_dir / "sanity.json").write_text(json.dumps(sanity, indent=1))
    jl_vol.commit()
    print(json.dumps(sanity, indent=1), flush=True)
    return {"rows": rows, "sanity": sanity, "lens_n_prompts": n_prompts,
            "gpu": torch.cuda.get_device_name(0)}  # fmt: skip


@app.local_entrypoint()
def read_main(work: str, layers: str = "") -> None:
    w = Path(work)
    items = json.loads((w / "items.json").read_text())
    lay = [int(x) for x in layers.split(",")] if layers else read_layers()
    print(f"[read] {len(items)} items at layers {lay}", flush=True)
    res = read.remote(items, lay)
    gen = w / "gen"
    by: dict[tuple[str, int], list[dict]] = {}
    for r in res["rows"]:
        by.setdefault((r["label"], r["layer"]), []).append(r)
    for (label, layer), rs in by.items():
        f = gen / label / f"L{layer:03d}.jsonl"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(json.dumps(r) + "\n" for r in rs))
    meta = {"layers": lay, "lens": f"glm53-jlens:{TAG}/lens.pt", "lens_n_prompts":
            res["lens_n_prompts"], "readout": "cosine", "gpu": res["gpu"],
            "sanity": res["sanity"]}  # fmt: skip
    (w / "read_meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


# ------------------------------------------------------------------ assemble (local)


def assemble(work: Path, dst_root: Path, ship: list[int]) -> Path:
    items = json.loads((work / "items.json").read_text())
    rmeta = json.loads((work / "read_meta.json").read_text())
    missing = [ly for ly in ship if ly not in rmeta["layers"]]
    if missing:
        raise SystemExit(f"--ship layers {missing} were not read ({rmeta['layers']})")
    dst = dst_root / "jlens_concept_pr"
    man = {
        "model_id": f"{HF_ID}@{REVISION}",
        "layers": sorted(ship),
        "prompts": [manifest_entry(r) for r in items],
        "adapt": {
            "model": f"{HF_ID}@{REVISION}",
            "lens": rmeta["lens"],
            "lens_n_prompts": rmeta["lens_n_prompts"],
            "readout": rmeta["readout"],
            "layers_read": rmeta["layers"],
            "layers_shipped": sorted(ship),
            "sanity": rmeta["sanity"],
            "items_manifest": json.loads((work / "items_manifest.json").read_text()),
            "script": "scripts/adapt_jlens_glm53_modal.py",
        },
    }
    if (dst / "gen-jlens-pr-jlens").exists():
        shutil.rmtree(dst / "gen-jlens-pr-jlens")
    for r in items:
        for ly in ship:
            src = work / "gen" / r["label"] / f"L{ly:03d}.jsonl"
            out = dst / "gen-jlens-pr-jlens" / r["label"] / src.name
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, out)
    (dst / "manifest.json").write_text(json.dumps(man, indent=1))
    shutil.copy(work / "items.json", dst / "items.json")
    print(f"[assemble] {len(items)} items x layers {sorted(ship)} -> {dst}")
    return dst


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["rollout", "assemble"])
    ap.add_argument("--work", required=True)
    ap.add_argument("--dst", default=str(WSB / "adapted" / MODEL))
    ap.add_argument("--ship", default="", help="layers to ship (default: every layer read)")
    ap.add_argument("--max-new", type=int, default=512)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    work = Path(a.work)
    if a.stage == "rollout":
        rollout(work, a.max_new, a.seed)
    else:
        layers = json.loads((work / "read_meta.json").read_text())["layers"]
        ship = [int(x) for x in a.ship.split(",")] if a.ship else layers
        assemble(work, Path(a.dst), ship)


if __name__ == "__main__":
    main()
