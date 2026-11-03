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
from pathlib import Path

import modal

WSB = Path(__file__).resolve().parents[1]
app = modal.App("adapt-introspection")
hf = modal.Volume.from_name("adapt-hf-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.11.0",
        "transformers==5.17.0",
        "accelerate>=1.14",
        "safetensors",
        "huggingface_hub",
        "numpy",
    )
    .env({"HF_HOME": "/hf", "PYTHONPATH": "/root/wsb/src", "PYTHONUNBUFFERED": "1"})
    .add_local_dir(str(WSB / "src/wsbench"), "/root/wsb/src/wsbench", ignore=["**/__pycache__"])
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
