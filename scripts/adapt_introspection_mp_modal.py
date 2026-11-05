"""The GPU side of ``python -m wsbench.adapt introspection`` for the big MoE subjects that no single
GPU serves (``introspection.EXTERNAL``; plan 0067): ``introspection_ops.run_job`` (vectors, the
recorded plan of ``measure``, batched execution with the registered steer) on a multi-GPU stack,
sharded over containers; ``finish`` merges the shards and replays them into the ``.npz`` that
``stage=measure result=`` ingests.

Subjects: ``glm-5.3`` (the vendored ``Glm53Text`` of global-workspace ``scripts/glm53_aff``, all
78 blocks + head, H200:8). The subject is fixed at import (Modal builds decorators then): pass
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
SUPPORTED = ("glm-5.3",)
MAX_SEQ = 2048  # GLM: the DSA indexer bypass is exact only for S <= index_topk (2048)
WSB_SRC = "/root/wsb/src"

# ------------------------------------------------------------------ Modal (per subject)

if SUBJECT not in SUPPORTED:
    raise SystemExit(f"{SUBJECT}: no multi-GPU stack yet (supported: {', '.join(SUPPORTED)})")

if modal.is_local():
    for p in (GW / "scripts/glm53_aff", WSB / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
from common import EPHEMERAL_DISK_MB, HF_GLM_IMAGE, MODEL_DIR, WEIGHTS, weights_vol  # noqa: E402

from wsbench.adapt.introspection_ops import (  # noqa: E402
    CALIB_PROMPT,
    CALIB_WORDS,
    calib_report,
    check_generation_config,
    row_major_order,
    stop_ids_of,
)


def _gw_commit() -> str:
    import subprocess

    try:
        out = subprocess.run(["git", "-C", str(GW), "rev-parse", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()  # fmt: skip
        dirty = subprocess.run(["git", "-C", str(GW), "status", "--porcelain", "--",
                                "src/global_workspace/glm53_aff", "scripts/glm53_aff"],
                               capture_output=True, text=True).stdout.strip()  # fmt: skip
        return out + ("+dirty" if dirty else "")
    except Exception:  # a checkout without git: recorded as unknown
        return "unknown"


app = modal.App(f"adapt-introspection-mp-{SUBJECT}")
image = (
    # no build step may follow the base image's add_local_* layers: wsbench lands in /root (on
    # sys.path) as a local python source, the subject / commit go in through the function env
    HF_GLM_IMAGE.add_local_python_source("wsbench", ignore=["**/__pycache__"])
)
FN_ENV = {"WSB_MP_SUBJECT": SUBJECT, "WSB_GW_COMMIT": _gw_commit() if modal.is_local() else ""}
GPU = ["H200:8"]  # one GPU type per run (no fallback list): shards stay comparable
PARTS = "/parts"  # every shard's result, written before it returns (a dropped client loses none)
parts_vol = modal.Volume.from_name("wsb-introspection-mp", create_if_missing=True, version=2)


def _gw_record() -> dict[str, Any]:
    """The global-workspace stack this run used: the vendored forward's sha256, the checkout's
    commit (passed in from the client), and the weights' download record."""
    p = Path("/root/app/src/global_workspace/glm53_aff/vendor/glm53_hf.py")
    done = Path(MODEL_DIR) / "DOWNLOAD.DONE.json"
    dl = json.loads(done.read_text()) if done.exists() else None
    return {"vendored_glm53_hf_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "gw_commit": os.environ.get("WSB_GW_COMMIT", ""), "weights_download": dl}  # fmt: skip


def _load_glm() -> Any:
    """``adapt_jlens_glm53_modal._load``: all 78 blocks + head, grouped experts, deterministic
    algorithms, the DSA indexer bypass (exact for S <= 2048)."""
    import torch

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True, warn_only=True)
    from global_workspace.glm53_aff import runtime

    gen = json.loads((Path(MODEL_DIR) / "generation_config.json").read_text())
    stops, gen_check = stop_ids_of(gen), check_generation_config(gen)  # before the long load
    hf = runtime._import_vendor()
    local = runtime.local_model_dir(MODEL_DIR, n_layers=None)
    gm = hf.Glm53Text(local, "nvfp4", n_layers=None)
    gm.load()
    hf.set_experts_impl("grouped", model=gm)
    hf.set_indexer_bypass(gm, True)
    gm.model.eval()
    for p in gm.parameters():
        p.requires_grad_(False)
    return gm, stops, gen_check


def glm_stack(extra_stops: list[int] | None = None) -> Any:
    from global_workspace.glm53_aff.template import EOS_ID

    from wsbench.adapt.introspection_ops import TorchStack, apply_steer

    gm, stops, gen_check = _load_glm()
    stops = sorted(set(stops) | {int(t) for t in extra_stops or []})

    class GlmStack(TorchStack):
        """``Glm53Text.forward``: ``inject`` on block L's output; ``logit_mask`` limits the head
        to the selected positions."""

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

    stack = GlmStack(stops, EOS_ID)
    stack.record = {"stop_ids": stops, "generation_config_check": gen_check}
    return stack, gm


def _engine(n_shards: int, stack: Any, budget: int) -> dict[str, Any]:
    import torch

    return {"stack": "glm53_aff vendored Glm53Text (78 blocks + head), inject on block output",
            "subject_revision": "nvidia/GLM-5.3-NVFP4@e3b8f9f2fad29727dfa95e766c5cac18ea1414bf",
            "residual": "plain_6144", "gpu": torch.cuda.get_device_name(0),
            "n_gpus": torch.cuda.device_count(),
            "deterministic": "use_deterministic_algorithms(True, warn_only=True)",
            "token_budget": budget,
            "indexer_bypass": True, "n_shards": n_shards, **stack.record,
            **_gw_record()}  # fmt: skip


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
    """CPU-only: the image builds, wsbench and the vendored stack import, the snapshot's
    generation config passes (seconds, before any 30-minute GPU load)."""
    from global_workspace.glm53_aff import runtime

    import wsbench.adapt.introspection  # noqa: F401

    runtime._import_vendor()
    gen = json.loads((Path(MODEL_DIR) / "generation_config.json").read_text())
    return {"stop_ids": stop_ids_of(gen), "generation_config_check": check_generation_config(gen),
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
    stack, _ = glm_stack(extra_stops)
    print(f"[mp] loaded in {time.time() - t0:.0f}s; shard {shard}/{n_shards}", flush=True)
    part = ops.run_job(stack, job, shard, n_shards, log=lambda s: print(s, flush=True))
    part["engine"] = _engine(n_shards, stack, ops.TOKEN_BUDGET)
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

    stack, _ = glm_stack(extra_stops)
    layer = int(job["inject_layer"])
    hid = ops.compute_hidden(stack, ops.vector_requests(job), layer, budget=1)  # as run_job
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
        return ops.run_greedy(stack, [op], vecs, log=lambda _s: None)[0]

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
    outs = ops.run_greedy(stack, g_ops, vecs, log=lambda s: print(s, flush=True))
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
    prod = ops.execute(stack, mixed, vecs, log=lambda s: print(s, flush=True))
    alone = ops.execute(stack, c_ops, vecs, budget=1, log=lambda s: print(s, flush=True))
    batch = {"ops": [{"single": alone[ops.op_key(op)], "packed": prod[ops.op_key(op)],
                      "target": i} for i, op in enumerate(c_ops)]}  # fmt: skip
    # (d) block-L state with / without a steer at beta 4
    ids = stack._pad([pr["ids"]])
    span = list(pr["inject"])
    pre = list(range(max(0, span[0] - 8), span[0]))
    sel = [(0, p) for p in pre + span]
    s = stack._steer([pr["ids"]], [st(raw[w0], 4.0, span)])
    h0 = stack._forward(ids, None, layer, sel).float().cpu()
    h1 = stack._forward(ids, s, layer, sel).float().cpu()
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
                         "engine": _engine(0, stack, ops.TOKEN_BUDGET)})  # fmt: skip
    out = Path(PARTS) / str(job["job_sha"]) / "calib.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    parts_vol.commit()
    return blob


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
