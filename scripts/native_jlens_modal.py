"""J-lens readouts at the native-language read sites (plan 0054 R6's readout criterion, Camila
2026-11-03: the subject's J-lens), on one Modal H200, for a subject whose J-lens is a neuronpedia
artifact. ``native_langs.read_sites()`` = 10 family items; each is read with ``wsbench produce``'s
own producer and ``JLens`` (cosine readout) at the FINAL token of its read-plan render and at
the 27B's 11 read layers remapped to the subject (``subjects.remap_layers``, snapped to
``read_band``). The 27B's cached J-lens readouts hold the final token for 9 of the 10 sites;
brh-ar-ain-jalut is pos 24 there (a token inside the question of its 37-token chat render), so
this script's 27B re-read differs from the cache at that one site. Writes
``<out>/<family>.jsonl`` + a ``tokens10`` sidecar, the input of ``native_langs stage=readouts
readouts=<out>``.

    source /workspace/wsb-runs/run_env.sh   # Modal profile / environment
    PYTHONPATH=src modal run scripts/native_jlens_modal.py --model qwen3.5-4b \\
        --lens qwen3.5-4b/jlens/Salesforce-wikitext/Qwen3.5-4B_jacobian_lens_n1000.pt --out DIR
"""

import json
from pathlib import Path

import modal

WSB = Path(__file__).resolve().parents[1]
app = modal.App("native-jlens")
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
LAYERS_27B = [20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60]  # the cached 27B J-lens grid


@app.function(image=image, gpu="H200", volumes={"/hf": hf}, timeout=3600, memory=65536)
def read(model: str, revision: str, lens_repo: str, lens: str, sites: list[dict]) -> list[dict]:
    """``sites``: ``{family, id, ids, layers}`` (ids rendered locally) -> readout rows."""
    from huggingface_hub import snapshot_download

    from wsbench.produce import Producer
    from wsbench.produce.render import Rendered

    path = snapshot_download(model, revision=revision)
    hf.commit()
    p = Producer.load(path, "jlens", repo=lens_repo, filename=lens)
    tok = p.backend.tokenizer
    out = []
    for s in sites:
        ids = s["ids"]
        r = Rendered(ids=ids, tokens=tok.convert_ids_to_tokens(ids),
                     decoded=[tok.decode([i]) for i in ids], render="native-site")  # fmt: skip
        for row in p._read_rendered(s["id"], r, {"kind": "final_token"}, s["layers"]):
            out.append({"family": s["family"], **row.contract()})
    return out


@app.local_entrypoint()
def main(model: str, lens: str, out: str, lens_repo: str = "neuronpedia/jacobian-lens"):
    from wsbench import readplan
    from wsbench.adapt import native_langs as nl
    from wsbench.adapt import subjects
    from wsbench.produce.render import render

    s = subjects.get(model)
    tok = subjects.load_tokenizer(s.hf_id, s.revision, s.tokenizer_dir, s.chat_template,
                                  s.trust_remote_code)  # fmt: skip
    layers = subjects.remap_layers(LAYERS_27B, s.n_layers, s.read_band)
    sites = []
    for fam, ask in nl.read_sites():
        spec = next(x for x in readplan.plan(fam) if x.id == ask.item_id)
        sites.append({"family": fam, "id": ask.item_id, "ids": render(spec, tok).ids,
                      "layers": layers})  # fmt: skip
    rows = read.remote(s.hf_id, s.revision or "main", lens_repo, lens, sites)
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r.pop("family"), []).append(r)
    for fam, rs in by.items():
        (root / f"{fam}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                                   for r in rs))  # fmt: skip
        meta = {"reads": "lite", "sampling": "tokens10", "reader": f"jlens:{lens_repo}/{lens}",
                "model": f"{s.hf_id}@{s.revision}", "layers": layers,
                "sites": "native_langs.read_sites() at final_token"}  # fmt: skip
        (root / f"{fam}.jsonl.meta.json").write_text(json.dumps(meta, indent=1))
    print(f"wrote {len(rows)} rows for {len(sites)} sites to {root}")
