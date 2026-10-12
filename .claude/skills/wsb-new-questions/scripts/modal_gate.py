"""OPTIONAL: run gate_hf.py on a rented GPU with Modal (https://modal.com) instead of a local
GPU. Generic: your own Modal account, no secrets needed for deterministic grading.

    modal run .claude/skills/wsb-new-questions/scripts/modal_gate.py \\
        --family multihop --bank cand/multihop.json --model Qwen/Qwen3.5-0.8B --out gated/multihop

Extra flags for gate_hf.py go in --extra (a quoted string). An LLM grader needs its key as a
Modal secret (e.g. `modal secret create openrouter OPENROUTER_API_KEY=...`, then --secret
openrouter); never bake keys into the image.
"""

import json
import os
from pathlib import Path

import modal

_HERE = Path(__file__).resolve()
# .claude/skills/<skill>/scripts/ -> repo root (only meaningful on the client side)
REPO = _HERE.parents[4] if len(_HERE.parents) > 4 else Path("/repo")
# a small subject fits any GPU; set WSB_GATE_GPU=H100 (etc.) for >= 9B models
GPU = os.environ.get("WSB_GATE_GPU", "L40S")  # "none" = CPU only (pass --extra "--device cpu")
GPU_ARG = None if GPU.lower() == "none" else GPU

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.9.1",
        "transformers>=5",
        "accelerate",
        "jinja2",
        "pronouncing",
        "openai>=1.40",
        "anthropic>=1.0",
        "numpy>=1.26",
        "pydra-config>=0.0.17",
    )
    .add_local_dir(REPO / "src", "/repo/src", ignore=["**/__pycache__"])
    .add_local_dir(REPO / "evals", "/repo/evals", ignore=["jlens_concept_pr/gen-*"])
    .add_local_dir(
        REPO / ".claude" / "skills" / "wsb-new-questions" / "scripts",
        "/repo/.claude/skills/wsb-new-questions/scripts",
        ignore=["**/__pycache__"],
    )
)
app = modal.App("wsb-gate-hf", image=image)
hf_cache = modal.Volume.from_name("wsb-gate-hf-cache", create_if_missing=True)


def _run(argv: list[str]) -> dict[str, str]:
    import subprocess

    os.environ["PYTHONPATH"] = "/repo/src"
    os.environ["HF_HOME"] = "/cache"
    p = subprocess.run(
        [
            "python",
            "/repo/.claude/skills/wsb-new-questions/scripts/gate_hf.py",
            *argv,
            "--repo",
            "/repo",
            "--out",
            "/tmp/out",
        ],
        cwd="/repo",
    )
    hf_cache.commit()
    if p.returncode != 0:
        raise RuntimeError(f"gate_hf.py exited {p.returncode}")
    return {f: Path("/tmp/out", f).read_text() for f in ("items.json", "gate.json", "summary.json")}


@app.function(gpu=GPU_ARG, cpu=8.0, memory=32768, timeout=4 * 3600, volumes={"/cache": hf_cache})
def gate(argv: list[str], bank_text: str) -> dict[str, str]:
    Path("/tmp/bank.json").write_text(bank_text)
    return _run([*argv, "--bank", "/tmp/bank.json"])


@app.local_entrypoint()
def main(family: str, bank: str, model: str, out: str, extra: str = "") -> None:
    argv = ["--family", family, "--model", model, *extra.split()]
    res = gate.remote(argv, Path(bank).read_text(encoding="utf-8"))
    dst = Path(out)
    dst.mkdir(parents=True, exist_ok=True)
    for name, text in res.items():
        (dst / name).write_text(text, encoding="utf-8")
    print(json.dumps(json.loads(res["summary.json"]), indent=1))
