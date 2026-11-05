"""The GPU side of ``python -m wsbench.adapt introspection`` for the big MoE subjects that no single
GPU serves (``introspection.EXTERNAL``; plan 0067): ``introspection_ops.run_job`` (vectors, the
recorded plan of ``measure``, batched execution with the registered steer) on a multi-GPU stack,
sharded over containers; ``finish`` merges the shards and replays them into the ``.npz`` that
``stage=measure result=`` ingests.

Subjects (plan 0067 §3): ``glm-5.3`` (the vendored ``Glm53Text`` of global-workspace
``scripts/glm53_aff``, 78 blocks + head, H200:8), ``deepseek-v4-pro`` / ``muse-spark-open`` /
``kimi-k3`` (the xaff readers of global-workspace PR #723 at full depth, ``WSB_GW_XAFF``; H200:8,
H200:8, B300:8). The subject is fixed at import (Modal builds decorators then): pass
``--subject`` on the ``modal run`` line (or ``WSB_MP_SUBJECT``).

    export WSB_GW=/path/to/global-workspace     # a checkout with scripts/glm53_aff
    python -m wsbench.adapt introspection model=glm-5.3 stage=job
    modal run scripts/adapt_introspection_mp_modal.py::calib_main --subject glm-5.3 \\
        --job adapted/glm-5.3/introspection/job.json --out W/calib.pkl
    python scripts/adapt_introspection_mp_modal.py calib-report --job ... --calib W/calib.pkl
    modal run --detach scripts/adapt_introspection_mp_modal.py::run_main --subject glm-5.3 \\
        --job adapted/glm-5.3/introspection/job.json --out-dir W --calib-json W/calib.json \\
        --shards 2          # in tmux; parts also land on the wsb-introspection-mp volume
    python scripts/adapt_introspection_mp_modal.py finish --job ... --parts W --out W/result.npz
    python -m wsbench.adapt introspection model=glm-5.3 stage=measure result=W/result.npz
"""

import argparse
import hashlib
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import modal

WSB = Path(__file__).resolve().parents[1]
GW = Path(os.environ.get("WSB_GW", "/workspace/agam/global-workspace"))


def _subject_from_argv(argv: list[str]) -> str:
    for i, a in enumerate(argv):
        if a == "--subject" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--subject="):
            return a.split("=", 1)[1]
    return os.environ.get("WSB_MP_SUBJECT", "glm-5.3")


SUBJECT = _subject_from_argv(sys.argv) if modal.is_local() else os.environ["WSB_MP_SUBJECT"]
SUPPORTED = ("glm-5.3", "deepseek-v4-pro", "muse-spark-open", "kimi-k3")

# ------------------------------------------------------------------ Modal (per subject)

if SUBJECT not in SUPPORTED:
    raise SystemExit(f"{SUBJECT}: no multi-GPU stack yet (supported: {', '.join(SUPPORTED)})")

if modal.is_local() and str(WSB / "src") not in sys.path:
    sys.path.insert(0, str(WSB / "src"))
from wsbench.adapt.introspection_ops import (  # noqa: E402
    CALIB_PROMPT,
    CALIB_WORDS,
    HookStack,
    TorchStack,
    apply_steer,
    calib_report,
    check_generation_config,
    row_major_order,
    stop_ids_of,
)

PARTS = "/parts"  # every shard's result, written before it returns (a dropped client loses none)
parts_vol = modal.Volume.from_name("wsb-introspection-mp", create_if_missing=True, version=2)
DETERMINISTIC = "use_deterministic_algorithms(True, warn_only=True)"


def _git_commit(repo: Path, paths: list[str]) -> str:
    """``repo``'s HEAD, ``+dirty`` when ``paths`` (the stack's files) differ from it."""
    import subprocess

    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()  # fmt: skip
        dirty = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--", *paths],
                               capture_output=True, text=True).stdout.strip()  # fmt: skip
        return out + ("+dirty" if dirty else "")
    except Exception:  # a checkout without git: recorded as unknown
        return "unknown"


def _sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _deterministic() -> None:
    import torch

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True, warn_only=True)


def _generation(model_dir: str, extra_stops: list[int] | None) -> tuple[list[int], dict]:
    """Stop ids (generation config eos + the Subject's reply_end) and the greedy-processor check,
    read before any weight is loaded."""
    gen = json.loads((Path(model_dir) / "generation_config.json").read_text())
    stops = sorted(set(stop_ids_of(gen)) | {int(t) for t in extra_stops or []})
    return stops, check_generation_config(gen)


if SUBJECT == "glm-5.3":
    if modal.is_local() and str(GW / "scripts/glm53_aff") not in sys.path:
        sys.path.insert(0, str(GW / "scripts/glm53_aff"))
    from common import (
        EPHEMERAL_DISK_MB,
        HF_GLM_IMAGE,
        MODEL_DIR,
        WEIGHTS,
        weights_vol,
    )

    # no build step may follow the base image's add_local_* layers: wsbench lands in /root (on
    # sys.path) as a local python source, the subject / commit go in through the function env
    image = HF_GLM_IMAGE.add_local_python_source("wsbench", ignore=["**/__pycache__"])
    GPU = ["H200:8"]  # one GPU type per run (no fallback list): shards stay comparable
    GW_COMMIT = (_git_commit(GW, ["src/global_workspace/glm53_aff", "scripts/glm53_aff"])
                 if modal.is_local() else "")  # fmt: skip
    MAX_SEQ = 2048  # the DSA indexer bypass is exact only for S <= index_topk (2048)
    BUDGET, HIDDEN_BUDGET = 16384, 1  # tokens per micro-batch; vectors one row per forward

    def make_stack(extra_stops: list[int] | None = None) -> Any:
        """The vendored ``Glm53Text`` (``adapt_jlens_glm53_modal._load``): all 78 blocks + head,
        grouped experts, deterministic algorithms, the DSA indexer bypass."""
        from global_workspace.glm53_aff import runtime
        from global_workspace.glm53_aff.template import EOS_ID

        _deterministic()
        stops, gen_check = _generation(MODEL_DIR, extra_stops)
        hf = runtime._import_vendor()
        local = runtime.local_model_dir(MODEL_DIR, n_layers=None)
        gm = hf.Glm53Text(local, "nvfp4", n_layers=None)
        gm.load()
        hf.set_experts_impl("grouped", model=gm)
        hf.set_indexer_bypass(gm, True)
        gm.model.eval()
        for p in gm.parameters():
            p.requires_grad_(False)

        class GlmStack(TorchStack):
            """``Glm53Text.forward``: ``inject`` on block L's output; ``logit_mask`` limits the
            head to the selected positions."""

            def _forward(self, ids, steer, layer_out, select):
                import torch

                if ids.shape[1] > MAX_SEQ:
                    raise ValueError(f"row of {ids.shape[1]} tokens > {MAX_SEQ} (indexer bypass)")
                kw: dict[str, Any] = {}
                if steer is not None:
                    kw = {"inject": lambda h: apply_steer(h, steer["mask"], steer["unit"],
                                                          steer["beta"]),
                          "inject_layer": int(steer["layer"])}  # fmt: skip
                with torch.inference_mode():
                    if layer_out is not None:
                        out = gm(ids, capture_layers=[int(layer_out)], return_logits=False, **kw)
                        h = out["h_cap"][int(layer_out)]
                        return h[[b for b, _ in select], [p for _, p in select]]
                    mask = torch.zeros(ids.shape, dtype=torch.bool)
                    for b, p in select:
                        mask[b, p] = True
                    lg = gm(ids, logit_mask=mask, **kw)["logits"]
                    return lg[row_major_order(list(select))]

        vend = "/root/app/src/global_workspace/glm53_aff/vendor/glm53_hf.py"
        done = Path(MODEL_DIR) / "DOWNLOAD.DONE.json"
        stack = GlmStack(stops, EOS_ID)
        stack.gm = gm
        stack.record = {
            "stack": "glm53_aff vendored Glm53Text (78 blocks + head), inject on block output",
            "subject_revision": "nvidia/GLM-5.3-NVFP4@e3b8f9f2fad29727dfa95e766c5cac18ea1414bf",
            "residual": "plain_6144", "indexer_bypass": True, "stop_ids": stops,
            "generation_config_check": gen_check, "loader_sha256": {vend: _sha256(vend)},
            "gw_commit": os.environ.get("WSB_GW_COMMIT", ""),
            "weights_download": json.loads(done.read_text()) if done.exists() else None,
        }  # fmt: skip
        return stack

    def preflight_check() -> dict:
        from global_workspace.glm53_aff import runtime

        runtime._import_vendor()
        return {}

elif SUBJECT == "deepseek-v4-pro":
    # the xaff V4-Pro reader (global-workspace PR #723, xaff.backends.v4pro): native FP8/FP4
    # checkpoint, transformers 5.11.0, every quantized GEMM as bf16 on its dequantized weight
    XAFF = Path(os.environ.get("WSB_GW_XAFF", str(GW)))
    WEIGHTS = "/vol"
    weights_vol = modal.Volume.from_name("v4-pro")
    REVISION = "72e1d3230f6c080a530b0a1d46f8eb4602340597"
    MODEL_DIR = f"{WEIGHTS}/hf/hub/models--deepseek-ai--DeepSeek-V4-Pro-0813/snapshots/{REVISION}"
    EPHEMERAL_DISK_MB = 524_288  # Modal minimum; weights are read in place from the volume
    GPU = ["H200:8"]  # 832 GiB of weights at ~114 GiB/GPU; one type per run
    # every expert is dequantized per call: a forward has a large fixed cost, so big micro-batches
    # (65536 left GPU 0 without room for a micro-batch, calib 2026-11-04)
    BUDGET = HIDDEN_BUDGET = 32768
    GW_COMMIT = (_git_commit(XAFF, ["src/global_workspace/xaff/backends"])
                 if modal.is_local() else "")  # fmt: skip
    _GWS = XAFF / "src/global_workspace"
    _APP = "/root/app/src/global_workspace"
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .uv_pip_install(
            "torch==2.11.0",
            "transformers==5.11.0",
            "kernels>=0.13,<0.14",
            "accelerate>=1.0",
            "safetensors>=0.8.0",
            "huggingface_hub>=0.35",
            "numpy>=2.3",
            "einops>=0.8",
        )
        .env(
            {
                "PYTHONPATH": "/root/app/src",
                "PYTHONUNBUFFERED": "1",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                "TOKENIZERS_PARALLELISM": "false",
                "TRANSFORMERS_DISABLE_DEEPGEMM_LINEAR": "1",
            }
        )
        .add_local_file(_GWS / "__init__.py", f"{_APP}/__init__.py")
        .add_local_file(_GWS / "xaff/__init__.py", f"{_APP}/xaff/__init__.py")
        .add_local_file(_GWS / "xaff/backends/__init__.py", f"{_APP}/xaff/backends/__init__.py")
        .add_local_file(_GWS / "xaff/backends/v4flash.py", f"{_APP}/xaff/backends/v4flash.py")
        .add_local_file(_GWS / "xaff/backends/v4pro.py", f"{_APP}/xaff/backends/v4pro.py")
        .add_local_python_source("wsbench", ignore=["**/__pycache__"])
    )

    def make_stack(extra_stops: list[int] | None = None) -> Any:
        """``load_native`` at full depth (61 blocks + hc_head + norm + lm_head, the MTP layer never
        built) then ``patch_reader(native_linear=False)`` (``HfV4Pro``'s reader forward); the steer
        and the read are hooks on the decoder block's raw mHC output ``[B, S, 4, 7168]``, whose
        flat 28,672-d view is the vector space (``mhc_raw_flat_28672``)."""
        from global_workspace.xaff.backends.v4pro import load_native, patch_reader

        _deterministic()
        stops, gen_check = _generation(MODEL_DIR, extra_stops)
        model = load_native(MODEL_DIR, n_layers=None)
        counts = patch_reader(model, native_linear=False)
        cfg = json.loads((Path(MODEL_DIR) / "config.json").read_text())
        pad = cfg.get("pad_token_id") or cfg.get("eos_token_id")
        pad = int(pad[0] if isinstance(pad, list) else pad)
        stack = HookStack(model, model.model.layers, stops, pad)
        f = f"{_APP}/xaff/backends/v4pro.py"
        stack.record = {
            "stack": "xaff V4-Pro native reader (load_native + patch_reader(native_linear=False))"
            ", full depth, forward hooks on the decoder block output",
            "subject_revision": f"deepseek-ai/DeepSeek-V4-Pro-0813@{REVISION}",
            "residual": "mhc_raw_flat_28672", "patch_reader": counts, "stop_ids": stops,
            "generation_config_check": gen_check, "pad_id": pad,
            "loader_sha256": {f: _sha256(f), f.replace("v4pro", "v4flash"):
                              _sha256(f.replace("v4pro", "v4flash"))},
            "gw_commit": os.environ.get("WSB_GW_COMMIT", ""),
            "n_blocks": len(model.model.layers),
        }  # fmt: skip
        return stack

    def preflight_check() -> dict:
        from global_workspace.xaff.backends import v4pro  # noqa: F401

        cfg = json.loads((Path(MODEL_DIR) / "config.json").read_text())
        return {"num_hidden_layers": cfg.get("num_hidden_layers"),
                "hc_mult": cfg.get("hc_mult"), "hidden_size": cfg.get("hidden_size")}  # fmt: skip


elif SUBJECT == "muse-spark-open":
    # the xaff MUS reader (global-workspace PR #723, xaff.backends.muse): the J-lens Muse text
    # stack on transformers 5.22.1 (muse_spark), fused NVFP4 expert dequant, at full depth + head
    XAFF = Path(os.environ.get("WSB_GW_XAFF", str(GW)))
    WEIGHTS = "/vol"
    weights_vol = modal.Volume.from_name("muse-spark")
    REVISION = "4239e4db19376904f2e82c167e78f70abb5455fe"
    MODEL_DIR = f"{WEIGHTS}/hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4"
    EPHEMERAL_DISK_MB = 1_000_000  # the 533 GB checkpoint is copied to node NVMe
    GPU = ["H200:8"]
    # experts are re-dequantized per micro-batch per layer (~1 s/layer): the xaff reader's size
    BUDGET = HIDDEN_BUDGET = 131072
    GW_COMMIT = (_git_commit(XAFF, ["src/global_workspace/xaff/backends",
                                    "src/global_workspace/native_quant_jlens"])
                 if modal.is_local() else "")  # fmt: skip
    _APP = "/root/app/src/global_workspace"
    image = (
        modal.Image.debian_slim(python_version="3.12")
        .pip_install("torch==2.13.0", index_url="https://download.pytorch.org/whl/cu130")
        .pip_install(
            "transformers==5.22.1",
            "accelerate>=1.0",
            "safetensors>=0.8.0",
            "huggingface_hub>=0.35",
            "numpy>=2.3",
            "einops",
        )
        .env(
            {
                "PYTHONPATH": "/root/app/src",
                "PYTHONUNBUFFERED": "1",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                "TOKENIZERS_PARALLELISM": "false",
                "XAFF_LOCAL_ROOT": "/local",
            }
        )
        .add_local_dir(
            XAFF / "src/global_workspace", _APP, ignore=["**/__pycache__", "**/*.safetensors"]
        )
        .add_local_python_source("wsbench", ignore=["**/__pycache__"])
    )

    def make_stack(extra_stops: list[int] | None = None) -> Any:
        """``xaff.backends.muse.load_truncated`` at all 62 blocks (+ the final norm), the head
        loaded from the checkpoint; ``MuseReader``'s own layer step (masks, NoPE layers), the
        steer applied to the decoder-layer output after block L, then the stock
        ``ForConditionalGeneration`` logits: ``T * tanh(lm_head(norm(h)) * mult / T)``."""
        import torch
        from global_workspace.xaff.backends import muse as mx
        from safetensors import safe_open

        _deterministic()
        stops, gen_check = _generation(MODEL_DIR, extra_stops)
        local = mx.local_model_dir(MODEL_DIR)
        text, tcfg, _tok, dmap = mx.load_truncated(local, mx.N_LAYERS, fast_experts=True)
        reader = mx.MuseReader.__new__(mx.MuseReader)  # the validated layer step, no reload
        reader.text, reader.cfg, reader.dmap = text, tcfg, dmap
        reader.devs = [next(layer.parameters()).device for layer in text.layers]
        reader.dev0, reader.n_layers = reader.devs[0], mx.N_LAYERS
        idx = json.loads((Path(local) / "model.safetensors.index.json").read_text())
        last = torch.device("cuda", torch.cuda.device_count() - 1)
        with safe_open(str(Path(local) / idx["weight_map"]["lm_head.weight"]), "pt") as f:
            w_head = f.get_tensor("lm_head.weight").to(last, torch.bfloat16)
        full = json.loads((Path(local) / "config.json").read_text())
        tc = full.get("text_config", full)
        mult, cap = float(tc["output_multiplier"]), float(tc["final_logit_softcapping"])
        norm_dev = next(text.norm.parameters()).device

        class MuseStack(TorchStack):
            def _forward(self, ids, steer, layer_out, select):
                with torch.inference_mode():
                    st = reader._embed(ids, reader.dev0)
                    cur = reader.dev0
                    stop = mx.N_LAYERS - 1 if layer_out is None else int(layer_out)
                    for i in range(stop + 1):
                        if reader.devs[i] != cur:
                            cur = reader.devs[i]
                            st = {k: (v.to(cur) if isinstance(v, torch.Tensor) else v)
                                  for k, v in st.items()}  # fmt: skip
                        reader._layer(i, st)
                        if steer is not None and i == int(steer["layer"]):
                            st["h"] = apply_steer(st["h"], steer["mask"], steer["unit"],
                                                  steer["beta"])  # fmt: skip
                    h = st["h"]
                    bi = torch.tensor([b for b, _ in select], device=h.device)
                    pi = torch.tensor([p for _, p in select], device=h.device)
                    if layer_out is not None:
                        return h[bi, pi]
                    x = text.norm(h[bi, pi].to(norm_dev)).to(last)
                    lg = torch.nn.functional.linear(x, w_head).float()
                    return torch.tanh(lg * mult / cap) * cap

        stack = MuseStack(stops, mx.PAD_ID)
        f = f"{_APP}/xaff/backends/muse.py"
        g = f"{_APP}/native_quant_jlens/backends.py"
        stack.record = {
            "stack": "xaff MUS reader (load_truncated at 62 blocks, fused NVFP4 experts) + the "
            "checkpoint's lm_head with the stock softcap; steer on the decoder-layer output",
            "subject_revision": f"meta-models/Muse-Spark-Open-816B-A42B-NVFP4@{REVISION}",
            "residual": "plain_8192", "stop_ids": stops, "generation_config_check": gen_check,
            "logits": f"{cap:g} * tanh(lm_head(norm(h)) * {mult:g} / {cap:g})",
            "loader_sha256": {f: _sha256(f), g: _sha256(g)},
            "gw_commit": os.environ.get("WSB_GW_COMMIT", ""), "device_map": list(dmap),
        }  # fmt: skip
        return stack

    def preflight_check() -> dict:
        from global_workspace.xaff.backends import muse  # noqa: F401

        full = json.loads((Path(MODEL_DIR) / "config.json").read_text())
        tc = full.get("text_config", full)
        idx = json.loads((Path(MODEL_DIR) / "model.safetensors.index.json").read_text())
        return {k: tc.get(k) for k in ("num_hidden_layers", "hidden_size", "output_multiplier",
                                       "final_logit_softcapping", "tie_word_embeddings")} | {
            "lm_head_in_checkpoint": "lm_head.weight" in idx["weight_map"]}  # fmt: skip


elif SUBJECT == "kimi-k3":
    # the xaff KK3 reader (global-workspace PR #723, xaff.backends.kimik3): remote-code
    # KimiLinearForCausalLM, MXFP4 experts, block Attention Residuals, at full depth + head
    XAFF = Path(os.environ.get("WSB_GW_XAFF", str(GW)))
    WEIGHTS = "/vol"
    weights_vol = modal.Volume.from_name("kimi-k3")
    REVISION = "f831ab66814297da540d832a5235f8e904f29d06"
    MODEL_DIR = f"{WEIGHTS}/hf/hub/models--moonshotai--Kimi-K3/snapshots/{REVISION}"
    EPHEMERAL_DISK_MB = 524_288  # 1.56 TB: read in place from the volume
    GPU = ["B300:8"]  # the only type that holds it
    BUDGET = HIDDEN_BUDGET = 65536  # experts dequantized per call: big micro-batches
    GW_COMMIT = (_git_commit(XAFF, ["src/global_workspace/xaff/backends",
                                    "src/global_workspace/native_quant_jlens"])
                 if modal.is_local() else "")  # fmt: skip
    _APP = "/root/app/src/global_workspace"
    image = (
        modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu24.04", add_python="3.12")
        .entrypoint([])
        .pip_install("torch==2.11.0", index_url="https://download.pytorch.org/whl/cu130")
        .pip_install(
            "transformers==4.56.2",
            "flash-linear-attention==0.5.2",
            "tiktoken",
            "blobfile",
            "accelerate>=1.0",
            "safetensors>=0.8.0",
            "numpy>=2.3",
            "einops>=0.8",
            "huggingface_hub>=0.35",
        )
        .env(
            {
                "PYTHONPATH": "/root/app/src",
                "PYTHONUNBUFFERED": "1",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
                "TOKENIZERS_PARALLELISM": "false",
                "HF_HOME": "/root/.cache/huggingface",
                "TRITON_PTXAS_PATH": "/usr/local/cuda/bin/ptxas",
            }
        )
        .add_local_dir(
            XAFF / "src/global_workspace", _APP, ignore=["**/__pycache__", "**/*.safetensors"]
        )
        .add_local_python_source("wsbench", ignore=["**/__pycache__"])
    )

    def make_stack(extra_stops: list[int] | None = None) -> Any:
        """``xaff.backends.kimik3.load_text_model`` at all 93 blocks (+ output_attn_res, norm,
        lm_head); ``KimiK3Reader``'s own step over ``(prefix_sum, block_residual)``. The vector
        space is full_sum = prefix_sum + sum(block_residual) (Camila 2026-11-04, xaff); the steer
        adds ``beta * ||full_sum|| * v_hat`` to prefix_sum after block L (``attnres_full_sum``);
        logits = ``lm_head(norm(output AttnRes mix))``, the remote code's own head."""
        import torch
        from global_workspace.xaff.backends import kimik3 as kx

        _deterministic()
        stops, gen_check = _generation(MODEL_DIR, extra_stops)
        model, _tok, devs = kx.load_text_model(MODEL_DIR, kx.N_BLOCKS)
        reader = kx.KimiK3Reader.__new__(kx.KimiK3Reader)  # the validated step, no reload
        reader.model, reader.text, reader.devs = model, model.model, devs
        reader.read_mode, reader.n_layers, reader.d = "full_sum", kx.N_BLOCKS, kx.D_MODEL
        text = model.model
        last = devs[-1]
        head_dev = model.lm_head.weight.device

        class KimiStack(TorchStack):
            def _forward(self, ids, steer, layer_out, select):
                with torch.inference_mode():
                    st = reader._init(ids, devs[0])
                    stop = kx.N_BLOCKS - 1 if layer_out is None else int(layer_out)
                    for li in range(stop + 1):
                        st = {k: v.to(devs[li]) for k, v in st.items()}
                        st = reader._step(li, st)
                        if steer is not None and li == int(steer["layer"]):
                            full = kx.read_vector(text, li, st["h"], st["br"], "full_sum")
                            st["h"] = apply_steer(st["h"], steer["mask"], steer["unit"],
                                                  steer["beta"], norm_src=full)  # fmt: skip
                    bi = torch.tensor([b for b, _ in select])
                    pi = torch.tensor([p for _, p in select])
                    if layer_out is not None:
                        full = kx.read_vector(text, stop, st["h"], st["br"], "full_sum")
                        return full[bi.to(full.device), pi.to(full.device)]
                    h, br = st["h"].to(last), st["br"].to(last)
                    mixed = text._apply_output_attn_res(h, br)
                    x = text.norm(mixed[bi.to(last), pi.to(last)])
                    return model.lm_head(x.to(head_dev))

        stack = KimiStack(stops, kx.PAD_ID)
        f = f"{_APP}/xaff/backends/kimik3.py"
        g = f"{_APP}/native_quant_jlens/backends.py"
        stack.record = {
            "stack": "xaff KK3 reader (load_text_model at 93 blocks, MXFP4 experts) + the remote "
            "code's output AttnRes / norm / lm_head; steer into prefix_sum at full_sum's norm",
            "subject_revision": f"moonshotai/Kimi-K3@{REVISION}",
            "residual": "attnres_full_sum", "stop_ids": stops,
            "generation_config_check": gen_check,
            "loader_sha256": {f: _sha256(f), g: _sha256(g)},
            "gw_commit": os.environ.get("WSB_GW_COMMIT", ""),
        }  # fmt: skip
        return stack

    def preflight_check() -> dict:
        from global_workspace.xaff.backends import kimik3  # noqa: F401

        cfg = json.loads((Path(MODEL_DIR) / "config.json").read_text())
        tc = cfg.get("text_config", cfg)
        idx = json.loads((Path(MODEL_DIR) / "model.safetensors.index.json").read_text())
        head = "language_model.lm_head.weight" in idx["weight_map"]
        if not head or tc.get("tie_word_embeddings"):
            raise SystemExit("kimi-k3: no untied language_model.lm_head.weight in the checkpoint")
        return {k: tc.get(k) for k in ("num_hidden_layers", "hidden_size", "tie_word_embeddings",
                                       "use_attn_residuals", "attn_res_block_size")} | {
            "lm_head_in_checkpoint": head}  # fmt: skip


app = modal.App(f"adapt-introspection-mp-{SUBJECT}")
FN_ENV = {"WSB_MP_SUBJECT": SUBJECT, "WSB_GW_COMMIT": GW_COMMIT}


def _engine(n_shards: int, stack: Any, budget: int) -> dict[str, Any]:
    import torch

    return {**stack.record, "gpu": torch.cuda.get_device_name(0),
            "n_gpus": torch.cuda.device_count(), "deterministic": DETERMINISTIC,
            "token_budget": budget, "hidden_budget": HIDDEN_BUDGET,
            "n_shards": n_shards}  # fmt: skip


FN: dict[str, Any] = {
    "image": image,
    "gpu": GPU,
    "volumes": {WEIGHTS: weights_vol, PARTS: parts_vol},
    "timeout": 12 * 3600,
    "memory": 1_048_576,
    "cpu": 64,
    "ephemeral_disk": EPHEMERAL_DISK_MB,
    "max_containers": 4,
    "env": FN_ENV,
}


@app.function(image=image, volumes={WEIGHTS: weights_vol}, env=FN_ENV, timeout=900)
def preflight() -> dict:
    """CPU-only: the image builds, wsbench and the subject's stack import, the snapshot's
    generation config passes (seconds, before any 30-minute GPU load)."""
    import wsbench.adapt.introspection  # noqa: F401

    stops, gen_check = _generation(MODEL_DIR, None)
    return {"stop_ids": stops, "generation_config_check": gen_check, **preflight_check(),
            "env": {k: os.environ.get(k) for k in FN_ENV}}  # fmt: skip


@app.local_entrypoint()
def preflight_main(subject: str = SUBJECT) -> None:
    assert subject == SUBJECT
    print(json.dumps(preflight.remote(), indent=1))


@app.function(**FN)
def run_shard(job: dict, shard: int, n_shards: int, extra_stops: list[int]) -> bytes:
    import wsbench.adapt.introspection  # noqa: F401  (fail before the load, not after)
    from wsbench.adapt import introspection_ops as ops

    t0 = time.time()
    stack = make_stack(extra_stops)
    print(f"[mp] loaded in {time.time() - t0:.0f}s; shard {shard}/{n_shards}", flush=True)
    part = ops.run_job(stack, job, shard, n_shards, budget=BUDGET, hidden_budget=HIDDEN_BUDGET,
                       log=lambda s: print(s, flush=True))  # fmt: skip
    part["engine"] = _engine(n_shards, stack, BUDGET)
    part["seconds"] = round(time.time() - t0)
    blob = pickle.dumps(part)
    out = Path(PARTS) / str(job["job_sha"]) / f"part_{shard}_of_{n_shards}.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    parts_vol.commit()
    print(f"[mp] shard {shard} -> wsb-introspection-mp:{out.relative_to(PARTS)}", flush=True)
    return blob


@app.function(**FN)
def calib(job: dict, extra_stops: list[int]) -> bytes:
    """Plan 0067 §5 raw outputs: (a) beta 0 / zero vector no-op, (b) concept mention at the
    neutral prompt over the beta grid, (c) batched == single, (d) the steer is local."""
    import numpy as np
    import torch

    from wsbench.adapt import introspection_ops as ops
    from wsbench.adapt.introspection import gaussian_rows

    stack = make_stack(extra_stops)
    layer = int(job["inject_layer"])
    hid = ops.compute_hidden(stack, ops.vector_requests(job), layer, budget=HIDDEN_BUDGET)
    hmap = ops.hidden_map(job, hid)
    base = np.mean([hmap[tuple(i)] for i in job["baseline_ids"]], axis=0)
    raw = {w: hmap[tuple(job["concept_ids"][w])] - base for w in job["words"]}
    pr = job["protocol"]
    rows = [pr["ids"] + pr["cont_ids"][w] for w in pr["paper_words"]]
    qs = [[(len(pr["ids"]) - 1 + j, [t]) for j, t in enumerate(pr["cont_ids"][w])]
          for w in pr["paper_words"]]  # fmt: skip
    w0 = pr["paper_words"][0]

    def st(vec: Any, beta: float, inject: list[int]) -> dict[str, Any]:
        return {"layer": layer, "positions": inject, "beta": beta, "vector": vec}

    def flat(lp: Any) -> list[list[float]]:
        return [[x[0] for x in r] for r in lp]

    zero = np.zeros_like(raw[w0])
    n = job["neutral"][CALIB_PROMPT]
    g_op = {"kind": "greedy", "ids": n["ids"], "n": 64}

    def greedy(steer: dict[str, Any] | None) -> list[int]:
        vecs = {"v": steer["vector"]} if steer else {}
        op = {**g_op, "steer": None if steer is None else
              {k: steer[k] for k in ("layer", "positions", "beta")} | {"vec": "v"}}  # fmt: skip
        return ops.run_greedy(stack, [op], vecs, BUDGET, log=lambda _s: None)[0]

    noop = {
        "base_lp": flat(stack.token_logprobs(rows, [None] * len(rows), qs)),
        "beta0_lp": flat(stack.token_logprobs(rows, [st(raw[w0], 0.0, pr["inject"])] * len(rows),
                                              qs)),
        "zero_lp": flat(stack.token_logprobs(rows, [st(zero, 4.0, pr["inject"])] * len(rows), qs)),
        "base_greedy": greedy(None),
        "beta0_greedy": greedy(st(raw[w0], 0.0, n["inject"])),
        "zero_greedy": greedy(st(zero, 4.0, n["inject"])),
    }  # fmt: skip
    words = list(job["coherence_words"])[:CALIB_WORDS]
    g_ops, vecs = [], {}
    for b in job["betas"]:
        for w in words:
            vecs[w] = raw[w]
            g_ops.append({**g_op, "steer": {"layer": layer, "positions": n["inject"],
                                            "beta": float(b), "vec": w}})  # fmt: skip
    outs = ops.run_greedy(stack, g_ops, vecs, BUDGET, log=lambda s: print(s, flush=True))
    steered: dict[str, dict[str, list[int]]] = {}
    for op, ids in zip(g_ops, outs, strict=True):
        steered.setdefault(f"{op['steer']['beta']:g}", {})[op["steer"]["vec"]] = ids
    mention = {"words": words, "base": noop["base_greedy"], "steered": steered}
    # (c) twenty inject ops at beta 4: every row alone vs production packing mixed with their
    # gaussian twins (execute at TOKEN_BUDGET); the injected word's rank is compared
    gauss = gaussian_rows(job["gaussian_seeds"], int(raw[w0].size))
    vecs = {}
    c_ops, g_ops2 = [], []
    for i, w in enumerate(pr["paper_words"][:20]):
        g = np.asarray(gauss[int(job["gaussian_row"][w])], np.float32)
        vecs[f"c{i}"], vecs[f"g{i}"] = raw[w], g
        base_op = {"kind": "cont", "ids": pr["ids"],
                   "conts": [pr["cont_ids"][x] for x in pr["paper_words"]]}  # fmt: skip
        c_ops.append({**base_op, "steer": {"layer": layer, "positions": pr["inject"],
                                           "beta": 4.0, "vec": f"c{i}"}})  # fmt: skip
        g_ops2.append({**base_op, "steer": {"layer": layer, "positions": pr["inject"],
                                            "beta": 4.0, "vec": f"g{i}"}})  # fmt: skip
    mixed = [op for pair in zip(c_ops, g_ops2, strict=True) for op in pair]
    prod = ops.execute(stack, mixed, vecs, budget=BUDGET, log=lambda s: print(s, flush=True))
    # alone: every row in its own forward where a forward is cheap (GLM), else each op alone
    if HIDDEN_BUDGET == 1:
        alone = ops.execute(stack, c_ops, vecs, budget=1, log=lambda s: print(s, flush=True))
    else:
        alone = {}
        for op in c_ops:
            alone.update(ops.execute(stack, [op], vecs, budget=10**9, log=lambda s: None))
    batch = {"ops": [{"single": alone[ops.op_key(op)], "packed": prod[ops.op_key(op)],
                      "target": i} for i, op in enumerate(c_ops)]}  # fmt: skip
    # (d) block-L state with / without a steer at beta 4
    ids = stack._pad([pr["ids"]])
    span = list(pr["inject"])
    pre = list(range(max(0, span[0] - 8), span[0]))
    sel = [(0, p) for p in pre + span]
    s = stack._steer([pr["ids"]], [st(raw[w0], 4.0, span)])
    h0 = stack._forward(ids, None, layer, sel).float().cpu().reshape(len(sel), -1)
    h1 = stack._forward(ids, s, layer, sel).float().cpu().reshape(len(sel), -1)
    u = torch.as_tensor(raw[w0] / np.linalg.norm(raw[w0]), dtype=torch.float32)
    k = len(pre)
    want = h0[k:] + 4.0 * h0[k:].norm(dim=-1, keepdim=True) * u
    pre_l1 = stack._forward(ids, s, None, [(0, pre[-1])]).float()
    pre_l0 = stack._forward(ids, None, None, [(0, pre[-1])]).float()
    pre_logit_diff = float((pre_l1 - pre_l0).abs().max())
    local = {
        "pre_span_max_abs_diff": float((h1[:k] - h0[:k]).abs().max()),
        "in_span_max_rel_err": float(((h1[k:] - want).norm(dim=-1) / want.norm(dim=-1)).max()),
        # the capture returns at block L, so the line above is exact by construction; the full
        # depth check (informational): next-token log-probs at the last pre-span position
        "pre_span_logits_max_abs_diff": pre_logit_diff,
    }
    blob = pickle.dumps({"noop": noop, "mention": mention, "batch": batch, "local": local,
                         "gpu": torch.cuda.get_device_name(0), "job_sha": job.get("job_sha"),
                         "engine": _engine(0, stack, BUDGET)})  # fmt: skip
    out = Path(PARTS) / str(job["job_sha"]) / "calib.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    parts_vol.commit()
    return blob


@app.function(**FN)
def diag(job: dict, extra_stops: list[int], layers: list[int], betas: list[float]) -> bytes:
    """Diagnostics after a failed calibration (plan 0067 §5): vector statistics (norms, top-dim
    share), the norm of h at the inject span vs the vector's, single vs packed log-probs at beta 0
    / 1 / 4 (numerics vs the steered regime), and concept mention on the neutral prompt over
    ``betas`` at the registered layer and at ``layers`` (same recipe, other blocks)."""
    import numpy as np
    import torch

    from wsbench.adapt import introspection_ops as ops

    stack = make_stack(extra_stops)
    reg = int(job["inject_layer"])
    n = job["neutral"][CALIB_PROMPT]
    words = list(job["coherence_words"])[:CALIB_WORDS]
    out: dict[str, Any] = {"layers": {}, "registered_layer": reg}
    for layer in [reg, *[x for x in layers if x != reg]]:
        hid = ops.compute_hidden(stack, ops.vector_requests(job), layer, budget=HIDDEN_BUDGET)
        hmap = ops.hidden_map(job, hid)
        base = np.mean([hmap[tuple(i)] for i in job["baseline_ids"]], axis=0)
        raw = {w: hmap[tuple(job["concept_ids"][w])] - base for w in job["words"]}
        v = np.stack([raw[w] for w in words])
        absv = np.abs(v)
        top = np.sort(absv, axis=1)[:, ::-1]
        h_last = np.stack([hmap[tuple(job["concept_ids"][w])] for w in words])
        span = stack._forward(stack._pad([n["ids"]]), None, layer,
                              [(0, p) for p in n["inject"]]).float().cpu()  # fmt: skip
        span = span.reshape(len(n["inject"]), -1)
        rec: dict[str, Any] = {
            "vec_norm_median": float(np.median(np.linalg.norm(v, axis=1))),
            "h_last_norm_median": float(np.median(np.linalg.norm(h_last, axis=1))),
            "span_h_norm": [round(float(x), 2) for x in span.norm(dim=-1)],
            "top1_dim_share": float(np.median(top[:, 0] ** 2 / (top**2).sum(1))),
            "top10_dim_share": float(np.median((top[:, :10] ** 2).sum(1) / (top**2).sum(1))),
            "top_dims": [int(i) for i in np.argsort(-absv.mean(0))[:5]],
            "baseline_mean_norm": float(np.linalg.norm(base)),
        }
        g_ops, vecs = [], {}
        for b in betas:
            for w in words:
                vecs[w] = raw[w]
                g_ops.append({"kind": "greedy", "ids": n["ids"], "n": 48, "steer":
                              {"layer": layer, "positions": n["inject"], "beta": float(b),
                               "vec": w}})  # fmt: skip
        ids = ops.run_greedy(stack, g_ops, vecs, BUDGET, log=lambda s: None)
        rec["hidden"] = hid.astype(np.float32)  # every vector request, for purity etc. locally
        rec["greedy"] = [[op["steer"]["beta"], op["steer"]["vec"], x]
                         for op, x in zip(g_ops, ids, strict=True)]  # fmt: skip
        out["layers"][str(layer)] = rec
        show = {k: rec[k] for k in rec if k not in ("greedy", "hidden")}
        print(f"[diag] layer {layer}: {json.dumps(show)}",
              flush=True)  # fmt: skip
    # single vs packed at beta 0 / 1 / 4 on the registered layer's vectors
    hid = ops.compute_hidden(stack, ops.vector_requests(job), reg, budget=HIDDEN_BUDGET)
    hmap = ops.hidden_map(job, hid)
    base = np.mean([hmap[tuple(i)] for i in job["baseline_ids"]], axis=0)
    pr = job["protocol"]
    cmp: dict[str, Any] = {}
    for beta in (0.0, 1.0, 4.0):
        vecs, c_ops = {}, []
        for i, w in enumerate(pr["paper_words"][:8]):
            vecs[f"c{i}"] = hmap[tuple(job["concept_ids"][w])] - base
            c_ops.append({"kind": "cont", "ids": pr["ids"],
                          "conts": [pr["cont_ids"][x] for x in pr["paper_words"]],
                          "steer": {"layer": reg, "positions": pr["inject"], "beta": beta,
                                    "vec": f"c{i}"}})  # fmt: skip
        packed = ops.execute(stack, c_ops, vecs, budget=BUDGET, log=lambda s: None)
        if HIDDEN_BUDGET == 1:
            alone = ops.execute(stack, c_ops, vecs, budget=1, log=lambda s: None)
        else:  # a stack with a large per-forward cost: each op alone, as calib (c)
            alone = {}
            for op in c_ops:
                alone.update(ops.execute(stack, [op], vecs, budget=10**9, log=lambda s: None))
        d = []
        for op in c_ops:
            k = ops.op_key(op)
            d += [abs(x - y) for x, y in zip(packed[k], alone[k], strict=True)]
        cmp[f"{beta:g}"] = {"max_abs_diff": max(d), "median_abs_diff": float(np.median(d))}
        print(f"[diag] single vs packed beta {beta:g}: {cmp[f'{beta:g}']}", flush=True)
    out["single_vs_packed"] = cmp
    out["gpu"] = torch.cuda.get_device_name(0)
    blob = pickle.dumps(out)
    p = Path(PARTS) / str(job["job_sha"]) / "diag.pkl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)
    parts_vol.commit()
    return blob


@app.local_entrypoint()
def diag_main(job: str, out: str, layers: str = "", betas: str = "0.5,1,1.5,2,3,4",
              subject: str = SUBJECT) -> None:  # fmt: skip
    assert subject == SUBJECT
    j = json.loads(Path(job).read_text(encoding="utf-8"))
    lay = [int(x) for x in layers.split(",") if x]
    bs = [float(x) for x in betas.split(",") if x]
    blob = diag.remote(j, reply_end_ids(j["model"]), lay, bs)
    Path(out).write_bytes(blob)
    print(f"wrote {out}")


@app.function(**FN)
def numerics(job: dict, extra_stops: list[int]) -> bytes:
    """GLM only. Batch-composition isolation (plan 0067 §5(c) failed at beta 0): the same 10
    protocol continuations scored (1) alone twice, (2) as 8 identical unpadded copies, (3) alone
    with 5 pad tokens appended, (4) inside a production-size packed micro-batch of other ops'
    rows; under the grouped experts with the indexer bypass (the run's stack), then without the
    bypass, then with the loop experts."""
    import numpy as np
    import torch

    if SUBJECT != "glm-5.3":
        raise SystemExit("numerics is the GLM isolation (it toggles Glm53Text options)")
    stack = make_stack(extra_stops)
    gm = stack.gm
    from global_workspace.glm53_aff import runtime

    hf = runtime._import_vendor()
    pr = job["protocol"]
    words = pr["paper_words"][:10]
    rows = [pr["ids"] + pr["cont_ids"][w] for w in words]
    qs = [[(len(pr["ids"]) - 1 + j, [t]) for j, t in enumerate(pr["cont_ids"][w])] for w in words]
    others = [pr["ids"] + pr["cont_ids"][w] for w in pr["paper_words"]] * 2  # ~100 rows

    def lp(rs, q):
        return [sum(x[0] for x in r) for r in stack.token_logprobs(rs, [None] * len(rs), q)]

    def suite() -> dict[str, Any]:
        a1 = [lp([r], [q])[0] for r, q in zip(rows, qs, strict=True)]
        a2 = [lp([r], [q])[0] for r, q in zip(rows, qs, strict=True)]
        copies = [lp([r] * 8, [q] * 8) for r, q in zip(rows, qs, strict=True)]
        pad = [lp([r + [stack.pad_id] * 5], [q])[0] for r, q in zip(rows, qs, strict=True)]
        oq = [[(len(pr["ids"]) - 1, [o[len(pr["ids"])]])] for o in others]
        packed = lp(rows + others, qs + oq)[: len(rows)]
        f = np.array
        return {
            "rerun_max": float(np.abs(f(a1) - f(a2)).max()),
            "copies_max": float(
                max(np.abs(f(c) - x).max() for c, x in zip(copies, a1, strict=True))
            ),
            "copies_spread": float(max(np.ptp(c) for c in copies)),
            "pad_max": float(np.abs(f(pad) - f(a1)).max()),
            "packed_max": float(np.abs(f(packed) - f(a1)).max()),
            "alone": a1,
        }

    out = {"grouped+bypass": suite()}
    print(f"[num] grouped+bypass {out['grouped+bypass']}", flush=True)
    hf.set_indexer_bypass(gm, False)
    out["grouped+indexer"] = suite()
    print(f"[num] grouped+indexer {out['grouped+indexer']}", flush=True)
    hf.set_experts_impl("loop", model=gm)
    out["loop+indexer"] = suite()
    print(f"[num] loop+indexer {out['loop+indexer']}", flush=True)
    out["gpu"] = torch.cuda.get_device_name(0)
    return pickle.dumps(out)


@app.local_entrypoint()
def numerics_main(job: str, out: str, subject: str = SUBJECT) -> None:
    assert subject == SUBJECT
    j = json.loads(Path(job).read_text(encoding="utf-8"))
    Path(out).write_bytes(numerics.remote(j, reply_end_ids(j["model"])))
    print(f"wrote {out}")


@app.local_entrypoint()
def calib_main(job: str, out: str, subject: str = SUBJECT) -> None:
    assert subject == SUBJECT
    j = json.loads(Path(job).read_text(encoding="utf-8"))
    blob = _fetch_part(j["job_sha"], "calib.pkl")  # a finished calib survives a dropped client
    if blob is None:
        blob = calib.remote(j, reply_end_ids(j["model"]))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(blob)
    print(f"wrote {out}; next: python {Path(__file__).name} calib-report --job {job} --calib {out}")


def _fetch_part(job_sha: str, name: str) -> bytes | None:
    try:
        return b"".join(parts_vol.read_file(f"{job_sha}/{name}"))
    except (FileNotFoundError, modal.exception.NotFoundError):  # not written (yet)
        return None


@app.local_entrypoint()
def run_main(job: str, out_dir: str, calib_json: str, shards: int = 2,
             subject: str = SUBJECT) -> None:  # fmt: skip
    """Launch (``modal run --detach`` in tmux) the shards still missing; every shard writes its
    part to the ``wsb-introspection-mp`` volume before returning, so a dropped client or a failed
    sibling loses nothing; parts already there (or in ``out_dir``) are not re-run. Refuses
    without a passing calibration report (plan 0067 §5)."""
    assert subject == SUBJECT
    j = json.loads(Path(job).read_text(encoding="utf-8"))
    rep = json.loads(Path(calib_json).read_text(encoding="utf-8"))
    if not rep.get("g0_pass") or rep.get("job_sha") != j.get("job_sha"):
        raise SystemExit(f"{calib_json}: no passing calibration for job {j.get('job_sha')}")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    todo = []
    for i in range(shards):
        name = f"part_{i}_of_{shards}.pkl"
        if not (d / name).exists() and (blob := _fetch_part(j["job_sha"], name)) is not None:
            (d / name).write_bytes(blob)
        if not (d / name).exists():
            todo.append(i)
    print(f"[mp] {SUBJECT}: shards {todo} of {shards} (job {j.get('job_sha')})", flush=True)
    stops = reply_end_ids(j["model"])
    calls = {i: run_shard.spawn(j, i, shards, stops) for i in todo}
    failed = []
    for i, c in calls.items():
        try:
            (d / f"part_{i}_of_{shards}.pkl").write_bytes(c.get())
            print(f"[mp] shard {i} done -> {d / f'part_{i}_of_{shards}.pkl'}", flush=True)
        except Exception as e:  # keep collecting the others; re-run only what failed
            failed.append(i)
            print(f"[mp] shard {i} FAILED: {e!r}", flush=True)
    if failed:
        raise SystemExit(f"[mp] shards {failed} failed; re-run run_main to retry only those")


# ------------------------------------------------------------------ local (no Modal call)


def reply_end_ids(model: str) -> list[int]:
    """The Subject's ``reply_end`` marker as stop ids (none for GLM; Kimi's ``<|close|>``)."""
    from wsbench.adapt.subjects import get

    end = get(model).reply_end
    if not end:
        return []
    from wsbench.adapt.author import tokenizer

    ids = tokenizer(model)(end, add_special_tokens=False)["input_ids"]
    if len(ids) != 1:
        raise SystemExit(f"{model}: reply_end {end!r} is {len(ids)} tokens, not one stop id")
    return [int(ids[0])]


def _decoder(model: str) -> Any:
    from wsbench.adapt.author import tokenizer

    tok = tokenizer(model)
    return lambda ids: str(tok.decode(ids, skip_special_tokens=True))


def finish(job_path: Path, parts_dir: Path, out: Path) -> None:
    from wsbench.adapt import introspection as ii
    from wsbench.adapt import introspection_ops as ops

    job = json.loads(job_path.read_text(encoding="utf-8"))
    parts = [pickle.loads(p.read_bytes()) for p in sorted(parts_dir.glob("part_*_of_*.pkl"))]
    merged = ops.merge(parts)
    engines = {json.dumps({k: v for k, v in p["engine"].items() if k != "gpu"}, sort_keys=True)
               for p in parts}  # fmt: skip
    if len(engines) != 1:
        raise SystemExit(f"shards ran on different stacks: {engines}")
    engine = {**parts[0]["engine"], "gpus": sorted({p["engine"]["gpu"] for p in parts}),
              "shard_seconds": [p.get("seconds") for p in parts]}  # fmt: skip
    res = ops.finish(job, merged, _decoder(job["model"]), engine)
    out.write_bytes(ii.save_result(res))
    print(f"wrote {out}; next: python -m wsbench.adapt introspection model={job['model']} "
          f"stage=measure result={out}")  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["finish", "calib-report"])
    ap.add_argument("--job", required=True)
    ap.add_argument("--parts", default="")
    ap.add_argument("--calib", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--subject", default=SUBJECT)
    a = ap.parse_args()
    if a.cmd == "finish":
        finish(Path(a.job), Path(a.parts), Path(a.out))
    else:
        job = json.loads(Path(a.job).read_text(encoding="utf-8"))
        raw = pickle.loads(Path(a.calib).read_bytes())
        if raw.get("job_sha") != job.get("job_sha"):
            raise SystemExit(f"{a.calib} was measured on job {raw.get('job_sha')}, not "
                             f"{job.get('job_sha')}")  # fmt: skip
        rep = calib_report(raw, _decoder(job["model"]))
        rep["job_sha"], rep["engine"] = raw["job_sha"], raw.get("engine")
        text = json.dumps(rep, indent=1, ensure_ascii=False)
        (Path(a.out) if a.out else Path(a.calib).with_suffix(".json")).write_text(text)
        print(text)


if __name__ == "__main__":
    main()
