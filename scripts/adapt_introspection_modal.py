"""The GPU side of ``python -m wsbench.adapt introspection`` for a subject that one HF load on one
GPU serves (the Qwen3.5 sizes, Qwen3-8B, OLMo-3 7B / 32B, Gemma-4-31B, Qwen3.6-35B-A3B):
``wsbench.adapt.introspection.measure`` on ``HFEngine`` (the subject's pinned HF revision,
bf16, adapter-free). The job (every render and token id, written by ``stage=job`` on the box) goes
in; one ``.npz`` (the subject's concept vectors, the gaussian rows at its width, the RR / detection
sweep and the neutral replies) comes back, and ``stage=measure`` writes it under
``adapted/<m>/introspection/``. Weights cache on the ``adapt-hf-cache`` volume.

    MODAL_ENVIRONMENT=<env> modal deploy scripts/adapt_introspection_modal.py
    python -m wsbench.adapt introspection model=<m> stage=measure   # Subject.backend == "modal"

or, without a deploy (writes the ``.npz`` locally; then ``stage=measure result=<out>``):

    modal run scripts/adapt_introspection_modal.py \\
        --job adapted/<m>/introspection/job.json --out /tmp/<m>_introspection.npz

The big MoE subjects (``introspection.EXTERNAL``) do not run here: their own loaders implement
``introspection.Engine`` and hand back the same ``.npz`` (``save_result``).
"""

import json
import os
from pathlib import Path

import modal

WSB = Path(__file__).resolve().parents[1]
# ADAPT_INTROSPECTION=dory-4b deploys the Dory variant (its own app, introspection.APP_OF):
# transformers from PR 50099 at a pinned commit (Dory is in no release) plus the mOre-lenses
# unrolled view (looped.py / loop_layout.py at a pinned sha, sha256-checked), which HFEngine.load
# applies so block L is unrolled entry L (the Subject's layer convention)
VARIANT = os.environ.get("ADAPT_INTROSPECTION", "")
DORY_TRANSFORMERS = (
    "git+https://github.com/shan18/transformers@fcc6924dfbac964f00787859b568c867ef5ad4cb"
)
MORE_REPO, MORE_SHA = "agu18dec/mOre-lenses", "65c77744b1144b89560ff69c799f1d64ef9f4d8a"
LOOPED_SHA256 = {
    "looped.py": "41efcd5ddbe1e09bb6d227da582d187e3e74cb88281e90b6f0a3b7baca767282",
    "loop_layout.py": "35d743f3987ebe1118f4d2913263bee3f6d4ae0a275216d9cfb44a0b9db2b200",
}
if VARIANT not in ("", "dory-4b"):
    raise SystemExit(f"ADAPT_INTROSPECTION={VARIANT!r}: expected unset or dory-4b")
app = modal.App("adapt-introspection" + (f"-{VARIANT}" if VARIANT else ""))
hf = modal.Volume.from_name("adapt-hf-cache", create_if_missing=True)
image = modal.Image.debian_slim(python_version="3.12")
if VARIANT == "dory-4b":
    image = image.apt_install("git").pip_install(
        "torch==2.11.0",
        DORY_TRANSFORMERS,
        "accelerate>=1.14",
        "safetensors",
        "huggingface_hub",
        "numpy",
    )
    fetch = (
        "import hashlib, shutil; from huggingface_hub import hf_hub_download as d; "
        + "; ".join(
            f"p = d('{MORE_REPO}', 'dory-4b/code/{f}', revision='{MORE_SHA}'); "
            f"assert hashlib.sha256(open(p, 'rb').read()).hexdigest() == '{h}', '{f}'; "
            f"shutil.copy(p, '/root/looped/{f}')"
            for f, h in LOOPED_SHA256.items()
        )
    )
    image = image.run_commands("mkdir -p /root/looped", f'python -c "{fetch}"')
    path = "/root/wsb/src:/root/looped"
else:
    image = image.pip_install(
        "torch==2.11.0",
        "transformers==5.17.0",
        "accelerate>=1.14",
        "safetensors",
        "huggingface_hub",
        "numpy",
    )
    path = "/root/wsb/src"
image = image.env({"HF_HOME": "/hf", "PYTHONPATH": path, "PYTHONUNBUFFERED": "1"}).add_local_dir(
    str(WSB / "src/wsbench"), "/root/wsb/src/wsbench", ignore=["**/__pycache__"]
)


@app.function(image=image, gpu="H200", volumes={"/hf": hf}, timeout=8 * 3600, memory=131072)
def measure(job: dict) -> bytes:
    from wsbench.adapt import introspection as ii

    engine = ii.HFEngine.load(job["hf_id"], job.get("revision"))
    hf.commit()
    return ii.save_result(ii.measure(engine, job))


@app.local_entrypoint()
def main(job: str, out: str) -> None:
    blob = measure.remote(json.loads(Path(job).read_text(encoding="utf-8")))
    Path(out).write_bytes(blob)
    print(f"wrote {out} ({len(blob)} B); next: stage=measure result={out}")
