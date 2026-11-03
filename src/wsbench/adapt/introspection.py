"""introspection on a new subject (plan 0060 §6b Phase E): everything the 27B bank took from
Qwen3.6-27B is re-derived on the subject; nothing is carried over.

- **Vectors**: the bank's ``vector_recipe`` on the subject's own model: the output residual of
  decoder block ``L`` at the LAST token of the subject's chat render of ``Tell me about {word}``
  (thinking off) minus the mean over the bank's 100 baseline entries. ``L`` = the 27B's
  ``spec.inject_layer`` (12 of 64) remapped by depth (``subjects.remap_layer``, no lens-band snap:
  it is an injection site, not a read). The gaussian controls are the bank's seeds drawn at the
  subject's ``d_model``.
- **Renders**: the 12 prompts re-rendered with the subject's tokenizer + template; inject span,
  grid, null, echo and lite are re-located by character offsets with the source's rules
  (global-workspace ``olens_suite/introspection/prompts.py``). Under the Qwen3.6 tokenizer they
  must reproduce the registered renders exactly (checked).
- **Scale**: Agam's Phase-1 reproduction on the subject (the 27B bank's ``agam_reproduction``):
  the subject's own report at the open quote of the protocol, the 50 paper concepts ranked by
  summed continuation log-prob, RR of the injected word, over a beta grid, with the norm-matched
  gaussian and the cross-partner controls; greedy neutral replies rated for coherence. Rule (the
  pre-registered rule of the DeepSeek-V4 port, global-workspace
  ``scripts/v4_flash/newfam/introspection/gate.py``): headline beta = the smallest beta with
  median RR >= 0.60 and >= 80% of injected neutral replies coherent (>= 6/10); secondary = the
  smallest with median RR >= 0.35 (half the headline if that is the headline itself).
- **Detection baseline**: the subject's own unsteered (beta 0) report: median RR of the paper
  words, its top-5 reported words, and P(Yes) on the un-prefilled protocol turn (false alarms,
  Trial 1..8), plus P(Yes) under each dose. The family's gate is measured against it: at the
  headline beta, median RR - beta0 >= 0.30, - gaussian >= 0.30, and cross <= beta0 + 0.10.
  No Opus / Sonnet unguessability gate (Camila, Phase E).

The item ``beta`` stays the dose TIER the judge keys on (4 = headline, 2 = secondary; ids and
twins are unchanged); each item's ``dose`` is the subject's calibrated beta, which the read plan
injects (``readplan._introspection``: ``dose`` if present, else ``beta``).

    python -m wsbench.adapt introspection model=<m> stage=job|measure|coherence|calibrate|build|all
        [result=<npz from an external runner>] [coherence=off] [llm=<claude id>]

``job`` (CPU, the subject's tokenizer) writes every render and token id the GPU side needs;
``measure`` runs :func:`measure` on the subject's HF model (Modal ``adapt-introspection``, or
the box GPU for a box subject) or ingests ``result=`` from an external runner (the big MoE
subjects, :data:`EXTERNAL`); ``coherence`` rates the neutral replies (Claude); ``calibrate``
applies the rule; ``build`` writes ``adapted/<m>/introspection.json`` and the report entry."""

import copy
import datetime as dt
import hashlib
import io
import json
import os
import statistics
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from wsbench.registry import REPO_ROOT, frozen_bank_path

from . import store
from .subjects import SUBJECTS, remap_layer
from .subjects import get as get_subject

FAMILY = "introspection"
APP = "adapt-introspection"  # scripts/adapt_introspection_modal.py
BETA_GRID = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0)
HEAD_TIER, SEC_TIER = 4.0, 2.0  # the registered bank's dose tiers (judge.HEADLINE)
HEAD_RR, SEC_RR = 0.60, 0.35
COHERENT_SCORE, COHERENT_SHARE = 6.0, 0.80
MARGIN, CROSS_SLACK = 0.30, 0.10
N_NULL = 2
N_COHERENCE = 10  # concepts per neutral prompt in the coherence check (the V4 port's COH_N)
REPLY_NEW = 64
CHUNK = 16  # continuations per batched forward
MIN_FULL_POSITIONS = 9  # EvalSpec.min_full_positions of the registered family

# Subjects whose weights no single-GPU HF load serves. ``measure`` refuses them and says what
# their runner must do: implement :class:`Engine` on their own loader, call ``measure(engine,
# job)``, ``save_result(...)`` the result, then ``stage=measure result=<that file>``.
EXTERNAL: dict[str, str] = {
    "glm-5.3": "nvidia/GLM-5.3-NVFP4 @e3b8f9f2 (754B MoE, 78 blocks, d 6144): ceselder's HF "
    "stack vendored in global-workspace scripts/glm53_aff (HF_GLM_IMAGE, weights volume "
    "glm53-weights); no-think render = the reasoning_effort=low system line + <think></think> "
    "(global-workspace src/global_workspace/glm53_aff/template.py), which the Subject's "
    "chat_template must reproduce before `job`",
    "glm-5.3-flash": "zai-org/GLM-5.3-Flash (320B MoE, 45 blocks): Agam's model-parallel app "
    "(gw-olens adapt_mp_subject_modal.py); not refreshed (plan 0060 D1)",
    "deepseek-v4-flash": "deepseek-ai/DeepSeek-V4-Flash (284B MoE, 43 blocks, 4 mHC residual "
    "streams): global-workspace scripts/v4_flash/common.py load_model; the render is "
    "encode_messages(thinking_mode='chat'), not an HF chat template; the engine must choose "
    "the stream mode (raw 16,384-d flat vs stream sum) and record it. The earlier port under "
    "this rule was NO-GO at blocks 6/8/10 (global-workspace docs/project/experiments/"
    "v4_flash_ar/newfam/introspection.md)",
    "kimi-k2": "moonshotai/Kimi-K2-Instruct-0905 (1T MoE, 61 blocks): the B300:8 model-parallel "
    "app (gw-olens adapt_mp_subject_modal.py, Subject.modal_app); tokenizer_dir is Agam-only",
}

COHERENCE_PROMPT = (  # the V4 port's rater prompt, verbatim
    "Rate the COHERENCE of this assistant reply to the user's request on a 0-10 scale. "
    "10 = fluent, "
    "on-topic, well-formed (it may be cut off mid-sentence at a token limit -- do not penalise "
    "truncation itself). 6 = understandable and mostly on-task, some oddity. 3 = derailed, "
    "repetitive, or fixated on an unrelated topic. 0 = gibberish / degenerate repetition.\n\n"
    'User request: "{prompt}"\n\nReply: "{reply}"\n\nAnswer with JSON only: {{"score": <0-10>}}'
)


# ---------------------------------------------------------------- paths


def work_dir(model: str) -> Path:
    return store.model_dir(model) / FAMILY


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return str(p)


def vector_paths(model: str, layer: int) -> dict[str, Path]:
    d = work_dir(model) / "vectors"
    return {
        "concept": d / f"concept_vectors_L{layer}.npy",
        "gaussian": d / f"gaussian_vectors_L{layer}.npy",
    }


def registered_bank() -> dict[str, Any]:
    return json.loads(frozen_bank_path(FAMILY).read_text(encoding="utf-8"))


def _read(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"{FAMILY}: {path} missing; run the earlier stage first")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- renders (CPU, the tokenizer)


def _ids(out: Any) -> list[int]:
    return [int(i) for i in (out["input_ids"] if hasattr(out, "keys") else out)]


def encode(tok: Any, text: str) -> tuple[list[int], list[tuple[int, int]]]:
    """Ids and character offsets of an already-templated string (no special tokens added: the
    template wrote them, the source's convention)."""
    enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
    return _ids(enc), [(int(a), int(b)) for a, b in enc["offset_mapping"]]


def span_tokens(offsets: Sequence[tuple[int, int]], start: int, end: int) -> list[int]:
    """Token indices whose character span overlaps ``[start, end)`` (the source's helper)."""
    return [i for i, (a, b) in enumerate(offsets) if b > a and a < end and b > start]


def _template(tok: Any, messages: list[dict[str, str]]) -> str:
    return str(
        tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
    )


def protocol_messages(prompts: dict[str, Any], trial: int) -> list[dict[str, str]]:
    p = prompts["protocol"]
    return [
        {"role": "user", "content": p["system_turn"]},
        {"role": "assistant", "content": p["ack_turn"]},
        {"role": "user", "content": p["trial_turn"].format(trial=trial)},
    ]


def _sites(tok: Any, rendered: str, inject_chars: tuple[int, int], echo_char: int | None):
    ids, offsets = encode(tok, rendered)
    inject = span_tokens(offsets, *inject_chars)
    if not inject or inject != list(range(inject[0], inject[-1] + 1)):
        raise ValueError("the steered span must be a non-empty contiguous run of positions")
    echo = inject[-1] if echo_char is None else span_tokens(offsets, echo_char, echo_char + 1)[0]
    if inject[0] < N_NULL:
        raise ValueError("not enough positions before the steered span for the null check")
    grid = list(range(inject[-1] + 1, len(ids)))
    if not grid:
        raise ValueError("no unsteered position after the steered span")
    return ids, inject, grid, list(range(inject[0] - N_NULL, inject[0])), [echo]


def protocol_render(tok: Any, prompts: dict[str, Any], trial: int, prefill: bool = True):
    """The protocol prompt (prefilled through the open quote unless ``prefill=False``, the
    detection probe): inject = the trial turn, echo = the comma after "If so", lite = the last
    token."""
    p = prompts["protocol"]
    text = p["trial_turn"].format(trial=trial)
    rendered = _template(tok, protocol_messages(prompts, trial)) + (p["prefill"] if prefill else "")
    t0 = rendered.rindex(text)
    comma = t0 + text.index("If so,") + len("If so,") - 1
    ids, inject, grid, null, echo = _sites(tok, rendered, (t0, t0 + len(text)), comma)
    return _render(tok, rendered, ids, inject, grid, null, echo, [grid[-1]])


def neutral_render(tok: Any, prompt: str):
    """A neutral prompt: inject = the user content, echo = its last token, lite = ``grid[1]``
    (the registered rule; ``grid[0]`` when the grid has one position)."""
    rendered = _template(tok, [{"role": "user", "content": prompt}])
    u0 = rendered.index(prompt)
    ids, inject, grid, null, echo = _sites(tok, rendered, (u0, u0 + len(prompt)), None)
    return _render(tok, rendered, ids, inject, grid, null, echo, [grid[min(1, len(grid) - 1)]])


def _render(tok, rendered, ids, inject, grid, null, echo, lite) -> dict[str, Any]:
    return {
        "input_ids": ids,
        "n_tokens": len(ids),
        "inject_span": inject,
        "grid": grid,
        "null": null,
        "echo": echo,
        "tokens": [tok.decode([i], skip_special_tokens=False) for i in ids],
        "lite": lite,
        "_text": rendered,
    }


def subject_renders(tok: Any, bank: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every render key of the registered bank, rebuilt with the subject's tokenizer."""
    out = {}
    for key in bank["renders"]:
        kind, name = key.split(":", 1)
        if kind == "protocol":
            out[key] = protocol_render(tok, bank["prompts"], int(name.removeprefix("trial")))
        else:
            out[key] = neutral_render(tok, bank["prompts"]["neutral"][name])
    return out


SITE_KEYS = ("input_ids", "n_tokens", "inject_span", "grid", "null", "echo", "lite")


def check_against_registered(renders: dict[str, Any], bank: dict[str, Any]) -> list[str]:
    """Under the banks' own tokenizer the rebuilt renders must BE the registered ones (the port of
    the site rules is verified, not assumed). Returns the mismatches."""
    bad = []
    for key, r in bank["renders"].items():
        for k in SITE_KEYS:
            if r.get(k) != renders[key].get(k):
                bad.append(f"{key}.{k}")
    return bad


def cont_ids(tok: Any, rendered: str, words: Sequence[str]) -> tuple[dict[str, list[int]], int]:
    """Each word's continuation ids after ``rendered``, in context (the source's ``_cont_ids``).
    A word that re-tokenizes the prefix is scored on its bare ids appended to the forced prefix;
    returns the count of those."""
    pre = encode(tok, rendered)[0]
    out, loose = {}, 0
    for w in words:
        full = encode(tok, rendered + w)[0]
        if full[: len(pre)] == pre and len(full) > len(pre):
            out[w] = full[len(pre) :]
        else:
            out[w], loose = _ids(tok(w, add_special_tokens=False)), loose + 1
    return out, loose


def job_sha(job: dict[str, Any]) -> str:
    """The job's identity (everything but the stamp itself): every downstream file carries it."""
    body = {k: v for k, v in job.items() if k != "job_sha"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def paper_words(bank: dict[str, Any]) -> list[str]:
    return [c["word"] for c in bank["concepts"] if c.get("source") == "paper"]


def build_job(
    model: str, tok: Any, bank: dict[str, Any] | None = None, betas: Sequence[float] = BETA_GRID
) -> dict[str, Any]:
    """Every token id the GPU side needs (it never sees a tokenizer)."""
    bank = bank or registered_bank()
    if model in EXTERNAL and model not in SUBJECTS:
        raise SystemExit(
            f"{FAMILY}: {model} is not in wsbench/adapt/subjects.py yet; add the Subject (its "
            f"pinned revision, n_layers, chat_template) first. Its runner: {EXTERNAL[model]}"
        )
    s = get_subject(model)
    if not s.n_layers:
        raise SystemExit(f"{model}: Subject.n_layers is 0; set the block count first")
    layer = remap_layer(int(bank["spec"]["inject_layer"]), s.n_layers)
    renders = subject_renders(tok, bank)
    # the exact-match check is gated on the 27B's TEMPLATE, not the tokenizer key (Qwen3.5
    # shares the key; its template may differ): a subject whose render of the protocol is the
    # bank's token for token must reproduce every registered site, else the port is wrong
    p1 = bank["renders"]["protocol:trial1"]
    if renders["protocol:trial1"]["input_ids"] == p1["input_ids"] and (
        bad := check_against_registered(renders, bank)
    ):
        raise SystemExit(f"{model}: the 27B's template, but sites differ from the bank: {bad[:6]}")
    rec = bank["vector_recipe"]
    words = [c["word"] for c in bank["concepts"]]

    def vec_ids(word: str) -> list[int]:
        msg = [{"role": "user", "content": rec["user_turn"].format(word=word.lower())}]
        return encode(tok, _template(tok, msg))[0]

    trial = int(bank["prompts"]["protocol"].get("trial_scored", 1))
    proto = renders[f"protocol:trial{trial}"]
    paper = paper_words(bank)
    conts, loose = cont_ids(tok, proto["_text"], paper)
    detect = {}
    for n in range(1, 9):
        d = protocol_render(tok, bank["prompts"], n, prefill=False)
        detect[str(n)] = {"ids": d["input_ids"], "inject": d["inject_span"]}
    d1 = protocol_render(tok, bank["prompts"], 1, prefill=False)["_text"]
    yes_no = cont_ids(tok, d1, ["Yes", "No"])[0]
    gauss = [it for it in bank["items"] if it["kind"] == "gaussian"]
    g_row = {
        it["concept"]: it["vector"]["row"]
        for it in gauss
        if it["prompt_key"] == f"trial{trial}" and float(it["beta"]) == HEAD_TIER
    }
    partner = {c["word"]: c["cross_partner"] for c in bank["concepts"]}
    job = {
        "model": model,
        "hf_id": s.hf_id,
        "revision": s.revision,
        "n_layers": s.n_layers,
        "registered_template": not check_against_registered(renders, bank),
        "inject_layer": layer,
        "betas": [float(b) for b in betas],
        "words": words,
        "concept_ids": {w: vec_ids(w) for w in words},
        "baseline_ids": [vec_ids(w) for w in rec["baseline_words"]],  # duplicate kept
        "gaussian_seeds": [int(it["vector"]["seed"]) for it in gauss],  # bank (= row) order
        "protocol": {
            "ids": proto["input_ids"],
            "inject": proto["inject_span"],
            "paper_words": paper,
            "cont_ids": conts,
            "n_loose": loose,
        },
        "detect": {"trials": detect, "yes": yes_no["Yes"][0], "no": yes_no["No"][0]},
        "neutral": {
            k.split(":", 1)[1]: {
                "ids": r["input_ids"],
                "inject": r["inject_span"],
                "prompt": bank["prompts"]["neutral"][k.split(":", 1)[1]],
            }
            for k, r in renders.items()
            if k.startswith("neutral:")
        },
        "coherence_words": paper[:: max(1, len(paper) // N_COHERENCE)][:N_COHERENCE],
        "gaussian_row": g_row,
        "cross_partner": partner,
        "renders": {k: {kk: v for kk, v in r.items() if kk != "_text"} for k, r in renders.items()},
    }
    job["job_sha"] = job_sha(job)
    return job


# ---------------------------------------------------------------- the GPU side


class Engine(Protocol):
    """What :func:`measure` needs from a loaded subject. :class:`HFEngine` is the HF one; a big
    MoE runner implements the same five methods on its own loader (:data:`EXTERNAL`)."""

    def last_hidden(self, ids: list[int], layer: int) -> Any:
        """The output residual of decoder block ``layer`` at the last position, float32 [d]."""
        ...

    def steer(
        self, layer: int, positions: Sequence[int], vector: Any, beta: float
    ) -> AbstractContextManager[None]:
        """``h <- h + beta * ||h|| * v / ||v||`` on block ``layer``'s output at ``positions``
        for every forward inside (prefill only: a cached decode step is never steered)."""
        ...

    def cont_logprobs(self, prefix: list[int], conts: list[list[int]]) -> list[float]:
        """Summed log-prob of each continuation after ``prefix``."""
        ...

    def next_logprobs(self, ids: list[int], token_ids: list[int]) -> list[float]:
        """Log-probs of ``token_ids`` as the next token after ``ids``."""
        ...

    def greedy(self, ids: list[int], n: int) -> str:
        """``n`` greedy tokens after ``ids``, decoded."""
        ...


def gaussian_rows(seeds: Sequence[int], d_model: int) -> Any:
    """The bank's gaussian recipe at the subject's width: ``torch.Generator().manual_seed(seed);
    torch.randn(d_model, generator=g)`` on CPU, float32."""
    import numpy as np
    import torch

    rows = []
    for s in seeds:
        g = torch.Generator().manual_seed(int(s))
        rows.append(torch.randn(d_model, generator=g, dtype=torch.float32).numpy())
    return np.stack(rows).astype(np.float32)


def _ranks(scores: Sequence[float]) -> list[float]:
    """Reciprocal rank of each entry under descending score (rank 1 = the max)."""
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    rr = [0.0] * len(scores)
    for r, i in enumerate(order):
        rr[i] = 1.0 / (r + 1)
    return rr


def _p_yes(lp: Sequence[float]) -> float:
    import math

    a, b = math.exp(lp[0]), math.exp(lp[1])
    return a / (a + b) if a + b > 0 else 0.5


def measure(
    engine: Engine,
    job: dict[str, Any],
    randn: Callable[[Sequence[int], int], Any] = gaussian_rows,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Vectors, the RR sweep, the detection probe and the neutral replies, for one subject.
    Returns ``{"concept": [125, d], "gaussian": [500, d], "sweep": {...}}``."""
    import numpy as np

    layer, words = int(job["inject_layer"]), list(job["words"])
    base = np.mean(
        [np.asarray(engine.last_hidden(i, layer), np.float32) for i in job["baseline_ids"]], axis=0
    )
    raw = {
        w: np.asarray(engine.last_hidden(job["concept_ids"][w], layer), np.float32) - base
        for w in words
    }
    concept = np.stack([raw[w] for w in words]).astype(np.float32)
    gauss = np.asarray(randn(job["gaussian_seeds"], concept.shape[1]), np.float32)
    log(f"[introspection] vectors {concept.shape}, gaussians {gauss.shape}")

    pr = job["protocol"]
    paper, prefix, inject = pr["paper_words"], pr["ids"], pr["inject"]
    conts = [pr["cont_ids"][w] for w in paper]
    det, yn = job["detect"], [int(job["detect"]["yes"]), int(job["detect"]["no"])]
    d1 = det["trials"]["1"]

    def rr_of(i: int, vec: Any, beta: float) -> float:
        with engine.steer(layer, inject, vec, beta):
            return _ranks(engine.cont_logprobs(prefix, conts))[i]

    def p_yes(vec: Any, beta: float) -> float:
        with engine.steer(layer, d1["inject"], vec, beta):
            return _p_yes(engine.next_logprobs(d1["ids"], yn))

    base_sc = engine.cont_logprobs(prefix, conts)
    b0rr = _ranks(base_sc)
    top = sorted(range(len(paper)), key=lambda i: -base_sc[i])[:5]
    sweep: dict[str, Any] = {
        "beta0": {
            "rr": dict(zip(paper, b0rr, strict=True)),
            "top5": [paper[i] for i in top],
            "p_yes": {
                n: _p_yes(engine.next_logprobs(t["ids"], yn)) for n, t in det["trials"].items()
            },
        },
        "betas": {},
        "neutral": [],
    }
    for beta in job["betas"]:
        cell: dict[str, dict[str, float]] = {
            k: {} for k in ("inject", "gaussian", "cross", "p_yes_inject", "p_yes_gaussian")
        }
        for i, w in enumerate(paper):
            g = gauss[int(job["gaussian_row"][w])]
            cell["inject"][w] = rr_of(i, raw[w], beta)
            cell["gaussian"][w] = rr_of(i, g, beta)
            cell["cross"][w] = rr_of(i, raw[job["cross_partner"][w]], beta)
            cell["p_yes_inject"][w] = p_yes(raw[w], beta)
            cell["p_yes_gaussian"][w] = p_yes(g, beta)
        sweep["betas"][f"{beta:g}"] = cell
        log(
            f"[introspection] beta {beta:g}: median RR "
            f"{statistics.median(cell['inject'].values()):.3f}"
        )
    for key, n in job["neutral"].items():
        sweep["neutral"].append(
            {
                "beta": 0.0,
                "kind": "beta0",
                "concept": "",
                "prompt": key,
                "reply": engine.greedy(n["ids"], REPLY_NEW),
            }
        )
        for beta in job["betas"]:
            for w in job["coherence_words"]:
                g = gauss[int(job["gaussian_row"][w])]
                for kind, vec in (("inject", raw[w]), ("gaussian", g)):
                    with engine.steer(layer, n["inject"], vec, beta):
                        reply = engine.greedy(n["ids"], REPLY_NEW)
                    sweep["neutral"].append(
                        {
                            "beta": float(beta),
                            "kind": kind,
                            "concept": w,
                            "prompt": key,
                            "reply": reply,
                        }
                    )
    sweep["job_sha"] = job.get("job_sha")  # an external runner's result carries it back too
    return {"concept": concept, "gaussian": gauss, "sweep": sweep}


def save_result(result: dict[str, Any]) -> bytes:
    """One ``.npz`` (concept, gaussian, the sweep as UTF-8 JSON bytes): what an external runner
    hands to ``stage=measure result=``."""
    import numpy as np

    buf = io.BytesIO()
    sweep = np.frombuffer(json.dumps(result["sweep"], ensure_ascii=False).encode(), np.uint8)
    np.savez(buf, concept=result["concept"], gaussian=result["gaussian"], sweep=sweep)
    return buf.getvalue()


def load_result(blob: bytes) -> dict[str, Any]:
    import numpy as np

    z = np.load(io.BytesIO(blob), allow_pickle=False)
    return {
        "concept": z["concept"].astype(np.float32),
        "gaussian": z["gaussian"].astype(np.float32),
        "sweep": json.loads(bytes(z["sweep"]).decode()),
    }


class HFEngine:
    """:class:`Engine` over a transformers causal LM (small / medium subjects), built on
    ``wsbench.produce.backend.Backend`` (its block lookup, capture and steer hook)."""

    def __init__(self, backend: Any, revision: str | None = None) -> None:
        self.b, self.revision, self._tok = backend, revision, None

    @classmethod
    def load(cls, hf_id: str, revision: str | None = None) -> "HFEngine":
        import torch
        from transformers import AutoModelForCausalLM

        from wsbench.produce.backend import Backend

        model = AutoModelForCausalLM.from_pretrained(
            hf_id, revision=revision, dtype=torch.bfloat16, device_map="auto"
        )
        model.eval()
        dev = str(next(model.parameters()).device)
        return cls(Backend(model=model, tokenizer=None, device=dev, model_id=hf_id), revision)

    def last_hidden(self, ids: list[int], layer: int) -> Any:
        return self.b.capture(ids, [layer], [len(ids) - 1])[layer][0].numpy()

    def steer(self, layer, positions, vector, beta):
        return self.b.steered(layer, positions, vector, beta)

    def _logits(self, batch: list[list[int]], keep: int) -> Any:
        import torch

        x = torch.tensor(batch, device=self.b.device)
        with torch.no_grad():
            try:
                out = self.b.model(x, use_cache=False, logits_to_keep=keep)
            except TypeError:
                out = self.b.model(x, use_cache=False)
        return torch.log_softmax(out.logits[:, -keep:].float(), dim=-1)

    def cont_logprobs(self, prefix: list[int], conts: list[list[int]]) -> list[float]:
        width, out = max(len(c) for c in conts), []
        for s in range(0, len(conts), CHUNK):
            ch = conts[s : s + CHUNK]
            lp = self._logits([prefix + c + [0] * (width - len(c)) for c in ch], width + 1)
            for r, c in enumerate(ch):  # lp[:, j] predicts the token at len(prefix) + j
                out.append(float(sum(lp[r, j, t].item() for j, t in enumerate(c))))
        return out

    def next_logprobs(self, ids: list[int], token_ids: list[int]) -> list[float]:
        lp = self._logits([ids], 1)
        return [float(lp[0, -1, t].item()) for t in token_ids]

    def greedy(self, ids: list[int], n: int) -> str:
        import torch
        from transformers import AutoTokenizer

        if self._tok is None:  # decode only (the job's ids were rendered on the box)
            self._tok = AutoTokenizer.from_pretrained(self.b.model_id, revision=self.revision)
        x = torch.tensor([ids], device=self.b.device)
        with torch.no_grad():
            g = self.b.model.generate(
                x, attention_mask=torch.ones_like(x), max_new_tokens=n, do_sample=False
            )
        return str(self._tok.decode(g[0, len(ids) :], skip_special_tokens=True))


# ---------------------------------------------------------------- calibration (CPU)


def _med(xs: Sequence[float]) -> float | None:
    return float(statistics.median(xs)) if xs else None


def coherence_key(n: dict[str, Any]) -> str:
    """One rating per (dose, kind, concept, prompt, REPLY): a re-measured reply is re-rated."""
    h = hashlib.sha256(str(n["reply"]).encode()).hexdigest()[:16]
    return f"{float(n['beta']):g}|{n['kind']}|{n['concept']}|{n['prompt']}|{h}"


def calibrate(sweep: dict[str, Any], coherence: dict[str, float] | None) -> dict[str, Any]:
    """The rule (module docstring) over a sweep; ``coherence`` = None drops the coherence clause
    (recorded as a deviation). Pure."""
    b0 = sweep["beta0"]
    b0_med = _med(list(b0["rr"].values()))
    table: dict[str, dict[str, Any]] = {}
    for b, cell in sweep["betas"].items():

        def ok_share(kind: str, b: str = b) -> float | None:
            if coherence is None:
                return None
            sc = [
                coherence[k]
                for n in sweep["neutral"]
                if n["kind"] == kind
                and f"{float(n['beta']):g}" == b
                and (k := coherence_key(n)) in coherence
            ]
            return sum(s >= COHERENT_SCORE for s in sc) / len(sc) if sc else None

        table[b] = {
            "rr_inject": _med(list(cell["inject"].values())),
            "rr_inject_mean": statistics.mean(cell["inject"].values()),
            "rr_gauss": _med(list(cell["gaussian"].values())),
            "rr_cross": _med(list(cell["cross"].values())),
            "detect_inject": statistics.mean(p > 0.5 for p in cell["p_yes_inject"].values()),
            "detect_gauss": statistics.mean(p > 0.5 for p in cell["p_yes_gaussian"].values()),
            "coherent_inject": ok_share("inject"),
            "coherent_gauss": ok_share("gaussian"),
        }
    betas = sorted(table, key=float)

    def coherent(b: str) -> bool:
        c = table[b]["coherent_inject"]
        return coherence is None or (c is not None and c >= COHERENT_SHARE)

    head = next((b for b in betas if table[b]["rr_inject"] >= HEAD_RR and coherent(b)), None)
    sec = next((b for b in betas if table[b]["rr_inject"] >= SEC_RR), None)
    notes = [] if coherence is not None else ["coherence clause dropped (coherence=off)"]
    go, why = (
        False,
        (
            f"no beta reaches median RR >= {HEAD_RR}"
            + (
                ""
                if coherence is None
                else f" with >= {COHERENT_SHARE:.0%} coherent neutral replies"
            )
        ),
    )
    if head is not None:
        if sec is None or float(sec) >= float(head):
            notes.append("secondary = headline / 2 (no smaller beta reached median RR >= 0.35)")
            sec = f"{float(head) / 2:g}"
        h = table[head]
        c1 = h["rr_inject"] - b0_med >= MARGIN
        c2 = h["rr_inject"] - h["rr_gauss"] >= MARGIN
        c3 = h["rr_cross"] <= b0_med + CROSS_SLACK
        go = c1 and c2 and c3
        why = f"vs beta0 {c1}, vs gaussian {c2}, cross at chance {c3}"
    p0 = list(b0["p_yes"].values())
    return {
        "rule": f"headline = smallest beta with median RR >= {HEAD_RR} and >= "
        f"{COHERENT_SHARE:.0%} injected neutral replies rated >= {COHERENT_SCORE:g}; secondary = "
        f"smallest with median RR >= {SEC_RR}; GO iff at the headline RR - beta0 >= {MARGIN}, "
        f"RR - gaussian >= {MARGIN}, cross <= beta0 + {CROSS_SLACK}",
        "detection_baseline": {
            "beta0_median_rr": b0_med,
            "beta0_top5": b0["top5"],
            "p_yes_beta0": b0["p_yes"],
            "false_alarm_rate": statistics.mean(p > 0.5 for p in p0) if p0 else None,
        },
        "table": table,
        "headline_beta": None if head is None else float(head),
        "secondary_beta": None if head is None else float(sec),  # type: ignore[arg-type]
        "GO": go,
        "why": why,
        "notes": notes,
    }


# ---------------------------------------------------------------- the adapted bank (CPU)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fingerprint(row: Any) -> str:
    """The bank's ``vector_fingerprint`` recipe."""
    blob = json.dumps([round(x, 3) for x in row.astype("float32").tolist()])
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def vector_space(concept: Any, bank: dict[str, Any]) -> tuple[dict[str, Any], list[float]]:
    """The bank's ``vector_space_check`` on the subject's vectors: per concept the share of its 4
    nearest neighbours (cosine) in its own cluster, and the mean cosine within / across."""
    import numpy as np

    cl = [c["cluster"] for c in bank["concepts"]]
    u = concept / np.linalg.norm(concept, axis=1, keepdims=True)
    cos = u @ u.T
    n, k = len(cl), 4
    pur, within, across = [], [], []
    for i in range(n):
        nb = [j for j in np.argsort(-cos[i]) if j != i][:k]
        pur.append(sum(cl[j] == cl[i] for j in nb) / k)
        for j in range(n):
            if j != i:
                (within if cl[j] == cl[i] else across).append(float(cos[i, j]))
    return {
        "mean_neighbour_purity": round(float(np.mean(pur)), 4),
        "uniform_expectation": round(k / (n - 1), 4),
        "mean_cos_within_cluster": round(float(np.mean(within)), 4),
        "mean_cos_across_clusters": round(float(np.mean(across)), 4),
    }, pur


def build_bank(
    model: str,
    bank: dict[str, Any],
    job: dict[str, Any],
    cal: dict[str, Any],
    concept: Any,
    paths: dict[str, Path],
    gaussian_shape: Sequence[int],
) -> dict[str, Any]:
    """The adapted bank: the registered v2 bank with every subject-dependent field replaced."""
    s = get_subject(model)
    layer, d = int(job["inject_layer"]), int(concept.shape[1])
    dose = {HEAD_TIER: float(cal["headline_beta"]), SEC_TIER: float(cal["secondary_beta"])}
    out = copy.deepcopy(bank)
    out["model"] = s.hf_id
    out["reference_27b"] = {
        k: out.pop(k) for k in ("agam_reproduction", "vector_space_check") if k in out
    }
    out["renders"] = copy.deepcopy(job["renders"])
    spec = out["spec"]
    spec["inject_layer"] = layer
    spec["betas"] = {
        "headline": dose[HEAD_TIER],
        "secondary": dose[SEC_TIER],
        "tiers": "items[].beta is the registered dose TIER (4 = headline, 2 = secondary) the "
        "judge and ids key on; items[].dose is the subject's calibrated beta, which is injected",
    }
    spec["vector_recipe"] = (
        f"the bank's recipe on {s.hf_id}: residual at the LAST token of the subject's chat render "
        f"of 'Tell me about {{word}}' (thinking off) minus the mean over the 100 baseline "
        f"entries, block {layer} (the 27B's L12 remapped by depth), raw then unit-normalized"
    )
    # the 27B's pre-grid read keys (layers of 64) are provenance, not this subject's spec
    if "legacy_v1" in spec:
        out["reference_27b"]["spec_legacy_v1"] = spec.pop("legacy_v1")
    spec["controls"] = (
        "gaussian (a random direction from the bank's seed at the subject's width, same dose), "
        "cross (another cluster's subject vector, same dose; readout reused from that concept's "
        "inject row since the visible text is identical), beta0 (protocol Trial 1..8 + 4 "
        "neutral prompts, judged against every cluster, bootstrap unit = activation)"
    )
    spec["subject_note"] = (
        f"adapted to {s.hf_id}: every activation-, token- and dose-dependent field is the "
        "subject's (renders, inject_layer, betas/dose, vectors, calibration); options, "
        "clusters, seeds and visible text are the registered bank's (subject-independent)"
    )
    spec["inject"] = (
        f"h <- h + dose*||h||*v_hat at block {layer} across the protocol trial turn / the neutral "
        "prompt's user content (the subject's own render); adapter disabled"
    )
    vs, pur = vector_space(concept, bank)
    out["vector_space_check"] = vs
    for c, row, p in zip(out["concepts"], concept, pur, strict=True):
        for k in ("vector_norm_L12", "vector_fingerprint", "neighbour_purity"):
            c.pop(k, None)
        c.update(
            vector_norm=round(float((row**2).sum() ** 0.5), 3),
            vector_fingerprint=fingerprint(row),
            neighbour_purity=p,
        )
    read36 = remap_layer(36, s.n_layers, s.read_band)
    for it in out["items"]:
        it["inject_layer"] = layer
        if "read_layer" in it:
            it["read_layer"] = read36
        it["dose"] = dose[float(it["beta"])]
    for r in out["beta0_rows"]:
        if "read_layer" in r:
            r["read_layer"] = read36
    note = (
        f"RAW block-{layer} vectors of {s.hf_id} (un-normalised); the injection unit-normalises "
        "them: h <- h + dose * ||h|| * v / ||v||"
    )
    out["vectors"] = {
        "concept": {
            "path": _rel(paths["concept"]),
            "sha256": _sha(paths["concept"]),
            "dtype": "float32",
            "shape": [len(out["concepts"]), d],
            "order": "concepts",
            "normalised": False,
        },
        "gaussian": {
            "path": _rel(paths["gaussian"]),
            "sha256": _sha(paths["gaussian"]),
            "dtype": "float32",
            "shape": list(gaussian_shape),
            "order": "gaussian items in bank order",
            "normalised": False,
        },
        "note": note,
    }
    vr = out["vector_recipe"]
    vr.update(
        layer=layer,
        render=f"{s.hf_id}'s chat template over one user turn, add_generation_prompt=True, "
        "enable_thinking=False; read the LAST token of the generation prompt",
        vector=f"output residual of decoder block {layer} for the concept minus the mean over "
        "the 100 baseline entries (duplicate included); unit-normalized before injection",
        inject=f"h <- h + dose * ||h|| * v_hat at the output of decoder block {layer}, every "
        "position of the render's inject_span, adapter disabled",
        gaussian=f"torch.Generator().manual_seed(seed); g = torch.randn(d_model={d}, "
        "generator=gen) on CPU in float32; v_hat = g / ||g||; injected exactly like a concept",
        fingerprints="concepts[].vector_fingerprint / vector_norm (the subject's vectors)",
    )
    out["calibration"] = cal
    short = min(len(r["grid"]) for r in out["renders"].values())
    out["adapt"] = {
        "model": model,
        "hf_id": s.hf_id,
        "revision": s.revision,
        "frozen": str(dt.date.today()),
        "inject_layer": layer,
        "dose": {"4": dose[HEAD_TIER], "2": dose[SEC_TIER]},
        "renders": "re-rendered with the subject's tokenizer + chat template; sites by character "
        "offsets (global-workspace olens_suite/introspection/prompts.py rules)",
        "n_loose_continuations": job["protocol"].get("n_loose", 0),
        "min_grid_positions": short,
        "gate": "the subject's own detection baseline (calibration.detection_baseline) and the "
        "GO margins; no Opus / Sonnet unguessability gate (plan 0060 Phase E)",
    }
    return out


# ---------------------------------------------------------------- stages


def stage_job(model: str, tok: Any = None) -> dict[str, Any]:
    if tok is None:
        from .author import tokenizer

        tok = tokenizer(model)
    job = build_job(model, tok)
    old = work_dir(model) / "job.json"
    if (
        old.exists()
        and json.loads(old.read_text(encoding="utf-8")).get("job_sha") != job["job_sha"]
    ):
        w = work_dir(model)
        stale = [w / "sweep.json", w / "calibration.json", _bank_path(model)]
        stale += sorted((w / "vectors").glob("*.npy"))
        _unlink(stale, "the job changed")
    store.write_json(old, job)
    print(
        f"{FAMILY} job: inject block {job['inject_layer']} of {job['n_layers']}, "
        f"{len(job['renders'])} renders, {job['protocol']['n_loose']} loose continuations"
    )
    return job


def _bank_path(model: str) -> Path:
    return store.model_dir(model) / f"{FAMILY}.json"


def _unlink(paths: Sequence[Path], why: str) -> None:
    for p in paths:
        if p.exists():
            p.unlink()
            print(f"{FAMILY}: removed {_rel(p)} ({why})")


def _write_result(model: str, job: dict[str, Any], res: dict[str, Any]) -> None:
    import numpy as np

    if res["sweep"].get("job_sha") != job.get("job_sha"):
        raise SystemExit(
            f"{FAMILY}: the result was measured on job {res['sweep'].get('job_sha')}, not on "
            f"the current job.json ({job.get('job_sha')}); re-run measure on this job"
        )

    if res["concept"].shape[0] != len(job["words"]):
        raise SystemExit(f"{FAMILY}: result has {res['concept'].shape[0]} concept rows")
    if res["gaussian"].shape != (len(job["gaussian_seeds"]), res["concept"].shape[1]):
        raise SystemExit(f"{FAMILY}: gaussian rows {res['gaussian'].shape} do not match the job")
    sw = res["sweep"]
    if sorted(sw.get("betas", {}), key=float) != [f"{float(b):g}" for b in sorted(job["betas"])]:
        raise SystemExit(f"{FAMILY}: result betas {sorted(sw.get('betas', {}))} != the job's")
    if list(sw.get("beta0", {}).get("rr", {})) != list(job["protocol"]["paper_words"]):
        raise SystemExit(f"{FAMILY}: result words do not match the job's paper words")
    concept = np.asarray(res["concept"], np.float64)
    norms = np.linalg.norm(concept, axis=1) if np.isfinite(concept).all() else None
    if norms is None or not (norms > 0).all():
        raise SystemExit(f"{FAMILY}: the result has a non-finite or zero-norm concept vector")
    # the gaussian controls are the bank's recipe, not the runner's: an external runner may draw
    # them another way (another RNG, fp64, a unit vector), so they are re-drawn here and compared
    want = gaussian_rows(job["gaussian_seeds"], int(concept.shape[1]))
    if not np.allclose(np.asarray(res["gaussian"], np.float32), want, rtol=0, atol=1e-6):
        raise SystemExit(
            f"{FAMILY}: the result's gaussian rows are not the recipe's (torch.Generator()"
            ".manual_seed(seed); torch.randn(d_model) on CPU, float32)"
        )
    # new vectors void everything built from the old ones (the bank records their sha256)
    _unlink([work_dir(model) / "calibration.json", _bank_path(model)], "new vectors")
    paths = vector_paths(model, int(job["inject_layer"]))
    paths["concept"].parent.mkdir(parents=True, exist_ok=True)
    np.save(paths["concept"], res["concept"].astype(np.float32))
    np.save(paths["gaussian"], res["gaussian"].astype(np.float32))
    store.write_json(work_dir(model) / "sweep.json", res["sweep"])


def stage_measure(model: str, result: str | None = None, engine: Engine | None = None) -> None:
    job = _read(work_dir(model) / "job.json")
    if result:
        res = load_result(Path(result).read_bytes())
    elif engine is not None:
        res = measure(engine, job)
    elif model in EXTERNAL:
        raise SystemExit(
            f"{FAMILY}: {model} needs its own loader: {EXTERNAL[model]}. Implement "
            "wsbench.adapt.introspection.Engine on it, run measure(engine, job) on "
            f"{_rel(work_dir(model) / 'job.json')}, write save_result(...) to a file, then "
            f"`python -m wsbench.adapt introspection model={model} stage=measure result=<file>`"
        )
    elif os.environ.get("ADAPT_BACKEND", get_subject(model).backend) == "modal":
        import modal

        fn = modal.Function.from_name(APP, "measure")
        res = load_result(fn.remote(job))
    else:
        res = measure(HFEngine.load(job["hf_id"], job.get("revision")), job)
    _write_result(model, job, res)
    print(
        f"{FAMILY} measure: vectors {res['concept'].shape} written under "
        f"{_rel(work_dir(model) / 'vectors')}"
    )


def _coherence_cache(model: str) -> dict[str, float]:
    path = work_dir(model) / "coherence.jsonl"
    return {r["key"]: float(r["score"]) for r in store._read_jsonl(path)}


def _claude_rater(llm: str) -> Callable[[str, str], float | None]:
    from .auth import Session

    session = Session()

    def rate(prompt: str, reply: str) -> float | None:
        for _ in range(4):
            try:
                m = session.create(
                    model=llm,
                    max_tokens=2000,
                    messages=[
                        {
                            "role": "user",
                            "content": COHERENCE_PROMPT.format(prompt=prompt, reply=reply),
                        }
                    ],
                )
                t = "".join(getattr(b, "text", "") for b in m.content)
                return float(json.loads(t[t.index("{") : t.rindex("}") + 1])["score"])
            except Exception:  # a failed rating is undecided, never a score
                continue
        return None

    return rate


def stage_coherence(
    model: str,
    llm: str = "claude-opus-5-5",
    rate: Callable[[str, str], float | None] | None = None,
    workers: int = 32,
) -> int:
    """Rate every neutral reply once (resume-safe cache ``coherence.jsonl``)."""
    from concurrent.futures import ThreadPoolExecutor

    job, sweep = _read(work_dir(model) / "job.json"), _read(work_dir(model) / "sweep.json")
    cache = _coherence_cache(model)
    todo = [n for n in sweep["neutral"] if coherence_key(n) not in cache]
    rate = rate or _claude_rater(llm)
    prompt_of = {k: v["prompt"] for k, v in job["neutral"].items()}
    with ThreadPoolExecutor(workers) as ex:
        scores = list(ex.map(lambda n: rate(prompt_of[n["prompt"]], n["reply"]), todo))
    rows = [
        {"key": coherence_key(n), "score": s, "llm": llm}
        for n, s in zip(todo, scores, strict=True)
        if s is not None
    ]
    store._append_jsonl(work_dir(model) / "coherence.jsonl", rows)
    print(f"{FAMILY} coherence: {len(rows)} rated, {len(todo) - len(rows)} undecided")
    return len(rows)


def stage_calibrate(model: str, use_coherence: bool = True) -> dict[str, Any]:
    sweep = _read(work_dir(model) / "sweep.json")
    coh = _coherence_cache(model) if use_coherence else None
    n_total = len(sweep["neutral"])
    if coh is not None:
        n_rated = sum(coherence_key(n) in coh for n in sweep["neutral"])
        if n_rated < n_total:  # every reply rated, or the coherent share is over a subset
            raise SystemExit(
                f"{FAMILY}: {n_rated}/{n_total} neutral replies rated; re-run stage=coherence "
                "(undecided ratings are retried) or coherence=off"
            )
    _unlink([_bank_path(model)], "a new calibration voids its dose")
    cal = calibrate(sweep, coh)
    cal["job_sha"] = sweep.get("job_sha")
    cal["coherence_coverage"] = None if coh is None else {"rated": n_total, "total": n_total}
    store.write_json(work_dir(model) / "calibration.json", cal)
    print(
        f"{FAMILY} calibrate: GO={cal['GO']} headline={cal['headline_beta']} "
        f"secondary={cal['secondary_beta']} ({cal['why']})"
    )
    return cal


def stage_build(model: str) -> dict[str, Any] | None:
    import numpy as np

    bank = registered_bank()
    job, cal = _read(work_dir(model) / "job.json"), _read(work_dir(model) / "calibration.json")
    target = len(bank["items"])
    if cal.get("job_sha") != job.get("job_sha"):
        raise SystemExit(
            f"{FAMILY}: calibration.json is for job {cal.get('job_sha')}, job.json is "
            f"{job.get('job_sha')}; re-run measure and calibrate"
        )
    if not cal["GO"]:
        _unlink([_bank_path(model)], "NO-GO")
        _report(
            model,
            status="blocked",
            n_items=0,
            target=target,
            note=f"calibration NO-GO: {cal['why']} (adapted/{model}/introspection/"
            "calibration.json); no bank written",
        )
        print(f"{FAMILY} build: blocked ({cal['why']})")
        return None
    paths = vector_paths(model, int(job["inject_layer"]))
    concept = np.load(paths["concept"])
    gshape = np.load(paths["gaussian"], mmap_mode="r").shape
    out = build_bank(model, bank, job, cal, concept, paths, gshape)
    store.write_json(store.model_dir(model) / f"{FAMILY}.json", out)
    notes = list(cal.get("notes") or [])
    if out["adapt"]["min_grid_positions"] < MIN_FULL_POSITIONS:
        notes.append(
            f"a render's grid has {out['adapt']['min_grid_positions']} positions < the family's "
            f"min_full_positions {MIN_FULL_POSITIONS}: under WSB_BANK_ROOT the reads=full span "
            "check uses the bank's adapt.min_grid_positions instead (reads.min_full_positions)"
        )
    _report(
        model,
        status="full",
        n_items=len(out["items"]),
        target=target,
        change=f"subject vectors at block {job['inject_layer']}; dose headline "
        f"{cal['headline_beta']:g} / secondary {cal['secondary_beta']:g} (registered 4 / 2); "
        f"renders re-stamped; detection baseline beta0 median RR "
        f"{cal['detection_baseline']['beta0_median_rr']:.3f}",
        **({"freeze_notes": notes} if notes else {}),
    )
    print(f"{FAMILY} build: {len(out['items'])} items -> adapted/{model}/{FAMILY}.json")
    return out


def _report(model: str, **entry: Any) -> None:
    store.update_report(
        model, lambda r: r.setdefault("families", {}).setdefault(FAMILY, {}).update(entry)
    )


STAGES = ("job", "measure", "coherence", "calibrate", "build")


def run(
    model: str,
    stage: str = "all",
    result: str | None = None,
    coherence: str = "on",
    llm: str = "claude-opus-5-5",
) -> None:
    use_coh = coherence.lower() not in ("off", "0", "false", "no")
    stages = STAGES if stage == "all" else (stage,)
    for st in stages:
        if st == "job":
            stage_job(model)
        elif st == "measure":
            stage_measure(model, result)
        elif st == "coherence":
            if use_coh:
                stage_coherence(model, llm)
        elif st == "calibrate":
            stage_calibrate(model, use_coh)
        elif st == "build":
            stage_build(model)
        else:
            raise SystemExit(f"{FAMILY}: unknown stage {st!r}; one of {', '.join(STAGES)}, all")
