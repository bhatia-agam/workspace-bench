"""Inkling-2-Mini parity gate (the adapt Subject ``inkling-2-mini``): the released NVFP4 / MXFP8
checkpoint under stock transformers 5.24.0 vs the unrolled view (``wsbench.adapt.inkling_loop``),
and vLLM's Inkling image vs HF greedy. Writes one JSON report.

    modal run scripts/inkling_parity_modal.py --out outputs/inkling_parity.json [--gen 48]

Checks, on chat-rendered prompts (the subject's pinned no-think template):
1. capture vs plain: hooks on the 48 entries == the unrolled forward's hidden_states[L + 1];
2. unrolled vs stock: logits and all 49 hidden states equal the stock forward's;
3. greedy: stock generate == unrolled generate (KV cache on) == vLLM greedy (B200, and the
   serving GPU), token for token.
transformers' NVFP4 path needs Blackwell (sm100+), so the HF side runs on B200.
"""

import json
import os
import time
from pathlib import Path

import modal

WSB = Path(__file__).resolve().parents[1]
HF_ID = "thinkingmachines/Inkling-2-Mini"
REV = "b85c3cfa615fc413cc9af3379f491b963f3b586a"
SNAP = f"/vol/hf/hub/models--thinkingmachines--Inkling-2-Mini/snapshots/{REV}"
INKLING_IMAGE = (
    "vllm/vllm-openai@sha256:c2dc759f5984f69c1e2418c6af7c26eb756f5ed2a8934c768ae1253645d1449e"
)
app = modal.App("inkling-parity")
vol = modal.Volume.from_name("inkling-2-mini")
hf_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.11.0",
        "transformers==5.24.0",
        "kernels",
        "accelerate>=1.14",
        "safetensors",
        "huggingface_hub",
        "numpy",
    )
    .env({"HF_HOME": "/vol/hf", "HF_HUB_OFFLINE": "1", "PYTHONPATH": "/root/wsb/src"})
    .add_local_dir(str(WSB / "src/wsbench"), "/root/wsb/src/wsbench", ignore=["**/__pycache__"])
)
vllm_image = (
    modal.Image.from_registry(INKLING_IMAGE)
    .entrypoint([])
    .run_commands('command -v python || ln -s "$(command -v python3)" /usr/local/bin/python')
    .env({"HF_HOME": "/vol/hf", "HF_HUB_OFFLINE": "1"})
)


def _load():
    import torch
    from transformers import AutoConfig, Inkling2LoopForConditionalGeneration

    cfg = AutoConfig.from_pretrained(SNAP)
    m = Inkling2LoopForConditionalGeneration.from_pretrained(
        SNAP, config=cfg, dtype=torch.bfloat16, device_map="cuda"
    ).eval()
    return m


@app.function(image=hf_image, gpu="B200", volumes={"/vol": vol}, timeout=3 * 3600, memory=131072)
def hf_parity(prompts: list[list[int]], gen: int) -> dict:
    import torch

    from wsbench.adapt import inkling_loop

    t0 = time.time()
    m = _load()
    out: dict = {"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__}
    import transformers

    out["transformers"] = transformers.__version__
    out["load_seconds"] = time.time() - t0
    tm = inkling_loop.text_model(m)
    stock: list[dict] = []
    with torch.no_grad():
        for ids in prompts:
            x = torch.tensor([ids], device="cuda")
            o = m(input_ids=x, use_cache=False, output_hidden_states=True)
            g = m.generate(x, attention_mask=torch.ones_like(x), max_new_tokens=gen,
                           do_sample=False)  # fmt: skip
            stock.append({"logits": o.logits.float().cpu(),
                          "hs": [h.float().cpu() for h in o.hidden_states],
                          "gen": g[0, len(ids):].tolist()})  # fmt: skip
    out["stock_n_hidden_states"] = len(stock[0]["hs"])
    inkling_loop.unroll(m)
    out["n_entries"] = len(tm.layers)
    rows = []
    with torch.no_grad():
        for ids, st in zip(prompts, stock, strict=True):
            x = torch.tensor([ids], device="cuda")
            o = m(input_ids=x, use_cache=False, output_hidden_states=True)
            hs = [h.float().cpu() for h in o.hidden_states]
            plain: dict[int, torch.Tensor] = {}
            calls: list[int] = []

            def mk(i, calls=calls, plain=plain):
                def hook(_m, _a, y):
                    calls.append(i)
                    plain[i] = (y if torch.is_tensor(y) else y[0]).float().cpu()

                return hook

            hs_handles = [e.register_forward_hook(mk(i)) for i, e in enumerate(tm.layers)]
            o2 = m(input_ids=x, use_cache=False)
            for h in hs_handles:
                h.remove()
            g = m.generate(x, attention_mask=torch.ones_like(x), max_new_tokens=gen,
                           do_sample=False)  # fmt: skip
            n = min(len(hs), len(st["hs"]))
            rows.append({
                "n_tokens": len(ids),
                "hooks_fire_once_in_order": calls == list(range(len(tm.layers))),
                "capture_vs_plain_max_abs": max((plain[i] - hs[i + 1]).abs().max().item()
                                                for i in plain),
                "capture_vs_plain_bitwise": all(torch.equal(plain[i], hs[i + 1]) for i in plain),
                "plain_vs_capture_logits_bitwise": torch.equal(o2.logits.float().cpu(),
                                                               o.logits.float().cpu()),
                "unrolled_n_hidden_states": len(hs),
                "unrolled_vs_stock_logits_max_abs": (o.logits.float().cpu()
                                                     - st["logits"]).abs().max().item(),
                "unrolled_vs_stock_logits_bitwise": torch.equal(o.logits.float().cpu(),
                                                                st["logits"]),
                "unrolled_vs_stock_hs_bitwise": [torch.equal(hs[i], st["hs"][i])
                                                 for i in range(n)],
                "unrolled_vs_stock_hs_max_abs": [(hs[i] - st["hs"][i]).abs().max().item()
                                                 for i in range(n)],
                "greedy_stock": st["gen"],
                "greedy_unrolled": g[0, len(ids):].tolist(),
            })  # fmt: skip
    out["rows"] = rows
    out["seconds"] = time.time() - t0
    return out


def _vllm(prompts: list[list[int]], gen: int, stop: list[int]) -> dict:
    import torch
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt

    t0 = time.time()
    llm = LLM(model=SNAP, max_model_len=8192, gpu_memory_utilization=0.9, seed=0,
              limit_mm_per_prompt={"image": 0, "video": 0})  # fmt: skip
    sp = SamplingParams(temperature=0.0, max_tokens=gen, stop_token_ids=stop or None)
    outs = llm.generate([TokensPrompt(prompt_token_ids=p) for p in prompts], sp, use_tqdm=False)
    import vllm

    return {"gpu": torch.cuda.get_device_name(0), "vllm": vllm.__version__,
            "greedy": [list(o.outputs[0].token_ids) for o in outs],
            "text": [o.outputs[0].text for o in outs], "seconds": time.time() - t0}  # fmt: skip


@app.function(image=vllm_image, gpu="B200", volumes={"/vol": vol}, timeout=3600)
def vllm_b200(prompts: list[list[int]], gen: int, stop: list[int]) -> dict:
    return _vllm(prompts, gen, stop)


@app.function(image=vllm_image, gpu="H200", volumes={"/vol": vol}, timeout=3600)
def vllm_h200(prompts: list[list[int]], gen: int, stop: list[int]) -> dict:
    return _vllm(prompts, gen, stop)


@app.function(image=hf_image, gpu="B200", volumes={"/vol": vol}, timeout=3600, memory=131072)
def tf_hf(seqs: list[list[int]], starts: list[int]) -> list[dict]:
    """Teacher-forced on HF: per continuation position, the argmax and the log-prob of the
    token actually there (``seqs[i][starts[i]:]``)."""
    import torch

    m = _load()
    out = []
    with torch.no_grad():
        for ids, k in zip(seqs, starts, strict=True):
            lp = torch.log_softmax(m(input_ids=torch.tensor([ids], device="cuda"),
                                     use_cache=False).logits[0].float(), -1)  # fmt: skip
            out.append({"argmax": lp[k - 1 : len(ids) - 1].argmax(-1).tolist(),
                        "lp": [lp[j - 1, ids[j]].item() for j in range(k, len(ids))]})  # fmt: skip
    return out


def _tf_vllm(seqs: list[list[int]], starts: list[int]) -> list[dict]:
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt

    llm = LLM(model=SNAP, max_model_len=8192, gpu_memory_utilization=0.9, seed=0,
              limit_mm_per_prompt={"image": 0, "video": 0})  # fmt: skip
    sp = SamplingParams(temperature=0.0, max_tokens=1, prompt_logprobs=1)
    outs = llm.generate([TokensPrompt(prompt_token_ids=s) for s in seqs], sp, use_tqdm=False)
    res = []
    for o, ids, k in zip(outs, seqs, starts, strict=True):
        pl = o.prompt_logprobs
        top = [max(pl[j].items(), key=lambda kv: kv[1].logprob)[0] for j in range(k, len(ids))]
        res.append({"argmax": top, "lp": [pl[j][ids[j]].logprob for j in range(k, len(ids))]})
    return res


@app.function(image=vllm_image, gpu="B200", volumes={"/vol": vol}, timeout=3600)
def tf_vllm(seqs: list[list[int]], starts: list[int]) -> list[dict]:
    return _tf_vllm(seqs, starts)


@app.local_entrypoint()
def crossed(prompts: str, first: str, out: str) -> None:
    """Each engine teacher-forced on the OTHER's greedy continuations (from ``first``)."""
    ps = json.loads(Path(prompts).read_text())
    r = json.loads(Path(first).read_text())
    hf_seqs = [p + row["greedy_stock"] for p, row in zip(ps, r["hf"]["rows"], strict=True)]
    vl_seqs = [p + g for p, g in zip(ps, r["vllm_b200"]["greedy"], strict=True)]
    starts = [len(p) for p in ps]
    a, b = tf_vllm.spawn(hf_seqs, starts), tf_hf.spawn(vl_seqs, starts)
    res = {"vllm_on_hf_greedy": a.get(), "hf_on_vllm_greedy": b.get(),
           "hf_seqs": hf_seqs, "vllm_seqs": vl_seqs, "starts": starts}  # fmt: skip
    Path(out).write_text(json.dumps(res))
    print(f"wrote {out}")


@app.local_entrypoint()
def main(prompts: str, out: str, gen: int = 48) -> None:
    ps = json.loads(Path(prompts).read_text())
    calls = {"hf": hf_parity.spawn(ps, gen), "vllm_b200": vllm_b200.spawn(ps, gen, []),
             "vllm_h200": vllm_h200.spawn(ps, gen, [])}  # fmt: skip
    res = {}
    for k, c in calls.items():
        try:
            res[k] = c.get()
        except Exception as e:  # reported, never fatal for the other legs
            res[k] = {"error": repr(e)}
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(f"wrote {out}")
