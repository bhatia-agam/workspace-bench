"""Record / replay of ``introspection.measure`` on a multi-GPU subject (plan 0067): batched ops, a
stack-agnostic executor, sharding, and the shared torch steer (``Backend.steered``'s recipe)."""

import hashlib
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol

import numpy as np

KINDS = ("cont", "next", "greedy")
TOKEN_BUDGET = 16384


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:20]


def vec_key(v: Any) -> str:
    """A steering vector's identity: its float32 bytes (and length)."""
    a = np.ascontiguousarray(np.asarray(v, np.float32).ravel())
    return f"{a.size}:{hashlib.sha256(a.tobytes()).hexdigest()[:24]}"


def op_key(op: dict[str, Any]) -> str:
    return _sha(op)


def array_sha(a: Any) -> str:
    a = np.ascontiguousarray(np.asarray(a, np.float32))
    return hashlib.sha256(repr(a.shape).encode() + a.tobytes()).hexdigest()[:24]


# ---------------------------------------------------------------- record / replay


def vector_requests(job: dict[str, Any]) -> list[list[int]]:
    """Every ``last_hidden`` render ``measure`` asks for, in order (baselines, then concepts)."""
    return [list(i) for i in job["baseline_ids"]] + [
        list(job["concept_ids"][w]) for w in job["words"]
    ]


def hidden_map(job: dict[str, Any], hidden: Any) -> dict[tuple[int, ...], Any]:
    """``(tuple(ids)) -> row`` for :func:`vector_requests` and its ``[n, d]`` result."""
    reqs = vector_requests(job)
    h = np.asarray(hidden, np.float32)
    if h.shape[0] != len(reqs):
        raise ValueError(f"{h.shape[0]} hidden rows for {len(reqs)} requests")
    return {tuple(r): h[i] for i, r in enumerate(reqs)}


class Recorder:
    """:class:`introspection.Engine` that records the op list ``measure`` asks for (``answers``
    None: placeholder values) or replays it from answers keyed by :func:`op_key` (a call that is
    not answered raises). ``last_hidden`` is served from ``hidden``; greedy answers that are
    token ids are decoded with ``decode``."""

    def __init__(
        self,
        hidden: dict[tuple[int, ...], Any],
        layer: int,
        answers: dict[str, Any] | None = None,
        decode: Callable[[list[int]], str] | None = None,
    ) -> None:
        self.hidden, self.layer, self.answers, self.decode = hidden, int(layer), answers, decode
        self.ops: dict[str, dict[str, Any]] = {}
        self.vectors: dict[str, Any] = {}  # "v<k>" -> vector, k = first-appearance order
        self._ids: dict[str, str] = {}  # vec_key (bytes, this process) -> "v<k>"
        self.calls: list[str] = []
        self._steer: dict[str, Any] | None = None

    def last_hidden(self, ids: list[int], layer: int) -> Any:
        if int(layer) != self.layer:
            raise ValueError(f"last_hidden at block {layer}, the job injects at {self.layer}")
        return np.array(self.hidden[tuple(int(i) for i in ids)], np.float32)

    @contextmanager
    def steer(
        self, layer: int, positions: Sequence[int], vector: Any, beta: float
    ) -> Iterator[None]:
        v = np.asarray(vector, np.float32).ravel()
        if not float(np.linalg.norm(v.astype(np.float64))) > 0:
            raise ValueError("steering vector has zero norm")  # Backend.steered's refusal
        if self._steer is not None:
            raise RuntimeError("nested steer")
        # ids by first appearance, never by content: a replay on another machine (another CPU's
        # float32 mean, another torch's randn) gets the same ids for the same call sequence
        b = vec_key(v)
        if b not in self._ids:
            self._ids[b] = f"v{len(self._ids)}"
            self.vectors[self._ids[b]] = v.copy()
        k = self._ids[b]
        self._steer = {"layer": int(layer), "positions": [int(p) for p in positions],
                       "vec": k, "beta": float(beta)}  # fmt: skip
        try:
            yield
        finally:
            self._steer = None

    def _call(self, kind: str, body: dict[str, Any], dummy: Any) -> Any:
        op = {"kind": kind, **body, "steer": self._steer}
        key = op_key(op)
        self.calls.append(key)
        self.ops.setdefault(key, op)
        if self.answers is None:
            return dummy
        if key not in self.answers:
            raise KeyError(f"replay: op {key} ({kind}) was never planned / executed")
        ans = self.answers[key]
        if kind == "greedy" and not isinstance(ans, str):
            if self.decode is None:
                raise ValueError("greedy answers are token ids: pass decode=")
            return self.decode([int(t) for t in ans])
        return list(ans) if kind != "greedy" else ans

    def cont_logprobs(self, prefix: list[int], conts: list[list[int]]) -> list[float]:
        body = {"ids": [int(i) for i in prefix], "conts": [[int(t) for t in c] for c in conts]}
        return self._call("cont", body, [0.0] * len(conts))

    def next_logprobs(self, ids: list[int], token_ids: list[int]) -> list[float]:
        body = {"ids": [int(i) for i in ids], "tokens": [int(t) for t in token_ids]}
        return self._call("next", body, [0.0] * len(token_ids))

    def greedy(self, ids: list[int], n: int) -> str:
        return self._call("greedy", {"ids": [int(i) for i in ids], "n": int(n)}, "")


def _measure() -> Callable[..., dict[str, Any]]:
    from .introspection import measure

    return measure


def plan(
    job: dict[str, Any], hidden: Any, randn: Callable[..., Any] | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    """``measure`` on a recording engine: the unique ops in first-call order, the vector table, and
    the plan's identity (the sha of the full call sequence, duplicates included)."""
    rec = Recorder(hidden_map(job, hidden), job["inject_layer"])
    kw = {"randn": randn} if randn is not None else {}
    _measure()(rec, job, log=lambda _s: None, **kw)
    return list(rec.ops.values()), rec.vectors, _sha(rec.calls)


def replay(
    job: dict[str, Any],
    hidden: Any,
    answers: dict[str, Any],
    decode: Callable[[list[int]], str] | None = None,
    randn: Callable[..., Any] | None = None,
    plan_sha: str | None = None,
    vectors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``measure`` answered from ``answers`` (what a direct engine on the same stack returns, up
    to the stack's batch-composition noise). Refuses a call sequence other than the plan's
    (``plan_sha``), a vector table other than ``vectors`` (rel L2 1e-4), and unused answers."""
    rec = Recorder(hidden_map(job, hidden), job["inject_layer"], answers, decode)
    kw = {"randn": randn} if randn is not None else {}
    res = _measure()(rec, job, log=lambda _s: None, **kw)
    if plan_sha is not None and _sha(rec.calls) != plan_sha:
        raise RuntimeError("replay: the call sequence differs from the executed plan")
    if vectors is not None:
        if sorted(vectors) != sorted(rec.vectors):
            raise RuntimeError("replay: the vector table differs from the executed plan's")
        for k, v in rec.vectors.items():
            w = np.asarray(vectors[k], np.float64)
            if np.linalg.norm(np.asarray(v, np.float64) - w) > 1e-4 * np.linalg.norm(w):
                raise RuntimeError(f"replay: vector {k} is not the one the plan steered with")
    if unused := set(answers) - set(rec.ops):
        raise RuntimeError(f"replay: {len(unused)} answered ops were never asked for")
    return res


# ---------------------------------------------------------------- the executor (no torch)


class Stack(Protocol):
    """What :func:`execute` needs from a loaded subject. ``rows`` are unpadded id lists; a steer is
    ``{"layer", "positions", "beta", "vector"}`` (float32 vector) or None."""

    stop_ids: Sequence[int]

    def hidden(self, rows: list[list[int]], layer: int) -> Any:
        """Block ``layer``'s output at each row's LAST token, unsteered: float32 ``[B, d]``."""
        ...

    def token_logprobs(
        self,
        rows: list[list[int]],
        steers: list[dict[str, Any] | None],
        queries: list[list[tuple[int, list[int]]]],
    ) -> list[list[list[float]]]:
        """Per row, per ``(pos, token_ids)`` query: log-softmax at ``pos`` of those tokens."""
        ...

    def argmax(self, rows: list[list[int]], steers: list[dict[str, Any] | None]) -> list[int]:
        """The argmax next token after each row's last position."""
        ...


def pack(lengths: Sequence[int], budget: int) -> list[list[int]]:
    """Consecutive micro-batches with ``n_rows * max_len <= budget`` (a longer row goes alone)."""
    out: list[list[int]] = []
    cur: list[int] = []
    mx = 0
    for i, n in enumerate(lengths):
        new = max(mx, n)
        if cur and (len(cur) + 1) * new > budget:
            out.append(cur)
            cur, new = [], n
        cur.append(i)
        mx = new
    if cur:
        out.append(cur)
    return out


def compute_hidden(
    stack: Stack, rows: list[list[int]], layer: int, budget: int = TOKEN_BUDGET
) -> Any:
    out: list[Any] = [None] * len(rows)
    order = sorted(range(len(rows)), key=lambda i: (len(rows[i]), i))
    for mb in pack([len(rows[i]) for i in order], budget):
        idx = [order[j] for j in mb]
        h = np.asarray(stack.hidden([rows[i] for i in idx], layer), np.float32)
        for k, i in enumerate(idx):
            out[i] = h[k]
    return np.stack(out).astype(np.float32)


def _steer_of(op: dict[str, Any], vectors: dict[str, Any]) -> dict[str, Any] | None:
    s = op.get("steer")
    if s is None:
        return None
    return {"layer": s["layer"], "positions": list(s["positions"]), "beta": float(s["beta"]),
            "vector": np.asarray(vectors[s["vec"]], np.float32)}  # fmt: skip


def execute(
    stack: Stack,
    ops: Sequence[dict[str, Any]],
    vectors: dict[str, Any],
    budget: int = TOKEN_BUDGET,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Every op, batched across ops (rows of one micro-batch may carry different steers). Returns
    ``{op_key: answer}``: cont = summed log-probs per continuation, next = the token log-probs,
    greedy = generated ids (cut before the first stop id)."""
    answers: dict[str, Any] = {}
    # teacher-forced rows: (op index, row index, ids, queries)
    rows: list[tuple[int, int, list[int], list[tuple[int, list[int]]]]] = []
    greedy: list[int] = []
    for oi, op in enumerate(ops):
        if op["kind"] == "cont":
            p = list(op["ids"])
            for ri, c in enumerate(op["conts"]):
                qs = [(len(p) - 1 + j, [int(t)]) for j, t in enumerate(c)]
                rows.append((oi, ri, p + list(c), qs))
        elif op["kind"] == "next":
            rows.append((oi, 0, list(op["ids"]), [(len(op["ids"]) - 1, list(op["tokens"]))]))
        elif op["kind"] == "greedy":
            greedy.append(oi)
        else:
            raise ValueError(f"unknown op kind {op['kind']!r}")
    got: dict[tuple[int, int], list[list[float]]] = {}
    mbs = pack([len(r[2]) for r in rows], budget)
    for n, mb in enumerate(mbs):
        sel = [rows[i] for i in mb]
        lp = stack.token_logprobs(
            [r[2] for r in sel], [_steer_of(ops[r[0]], vectors) for r in sel], [r[3] for r in sel]
        )
        for r, v in zip(sel, lp, strict=True):
            got[(r[0], r[1])] = v
        if n % 50 == 0:
            log(f"[ops] teacher-forced micro-batch {n + 1}/{len(mbs)}")
    for oi, op in enumerate(ops):
        if op["kind"] == "cont":
            answers[op_key(op)] = [float(sum(x[0] for x in got[(oi, ri)]))
                                   for ri in range(len(op["conts"]))]  # fmt: skip
        elif op["kind"] == "next":
            answers[op_key(op)] = [float(x) for x in got[(oi, 0)][0]]
    if greedy:
        for oi, ids in zip(greedy, run_greedy(stack, [ops[i] for i in greedy], vectors, budget,
                                              log), strict=True):  # fmt: skip
            answers[op_key(ops[oi])] = ids
    return answers


def run_greedy(
    stack: Stack,
    ops: Sequence[dict[str, Any]],
    vectors: dict[str, Any],
    budget: int = TOKEN_BUDGET,
    log: Callable[[str], None] = print,
) -> list[list[int]]:
    """Lock-step greedy decoding of every op (no KV cache: each step re-runs every live row, so a
    steered prompt position is steered on every step and a generated position never is)."""
    stop = {int(t) for t in stack.stop_ids}
    seqs = [list(op["ids"]) for op in ops]
    gen: list[list[int]] = [[] for _ in ops]
    live = [True] * len(ops)
    steers = [_steer_of(op, vectors) for op in ops]
    step = 0
    while True:
        act = [i for i, op in enumerate(ops) if live[i] and len(gen[i]) < int(op["n"])]
        if not act:
            break
        act.sort(key=lambda i: (len(seqs[i]), i))
        for mb in pack([len(seqs[i]) for i in act], budget):
            idx = [act[j] for j in mb]
            nxt = stack.argmax([seqs[i] for i in idx], [steers[i] for i in idx])
            for i, t in zip(idx, nxt, strict=True):
                t = int(t)
                if t in stop:
                    live[i] = False
                else:
                    gen[i].append(t)
                    seqs[i].append(t)
        step += 1
        if step % 16 == 0:
            log(f"[ops] greedy step {step}: {len(act)} live rows")
    return gen


# ---------------------------------------------------------------- one job on one stack, shards


def shard(ops: Sequence[dict[str, Any]], i: int, k: int) -> list[dict[str, Any]]:
    """Ops ``j ≡ i (mod k)`` within each kind (so greedy work is dealt evenly)."""
    if not 0 <= i < k:
        raise ValueError(f"shard {i} of {k}")
    out = []
    for kind in KINDS:
        of = [op for op in ops if op["kind"] == kind]
        out += of[i::k]
    return out


VECTOR_TOL = 1e-3  # max relative L2 between two shards' steering vectors (else refused)


def run_job(
    stack: Stack,
    job: dict[str, Any],
    shard_index: int = 0,
    n_shards: int = 1,
    randn: Callable[..., Any] | None = None,
    budget: int = TOKEN_BUDGET,
    log: Callable[[str], None] = print,
    hidden_budget: int = 1,
) -> dict[str, Any]:
    """The GPU side for one shard: vectors (packed by length under ``hidden_budget``, one row per
    forward by default, so their batch composition never depends on the sharding; a stack with a
    large per-forward cost packs them), the plan, this shard's ops. Every shard plans by itself;
    ops are keyed by the call sequence, so :func:`merge` needs equal plans, and steering vectors
    equal within :data:`VECTOR_TOL` (the stack's cross-container noise, recorded)."""
    layer = int(job["inject_layer"])
    hidden = compute_hidden(stack, vector_requests(job), layer, budget=hidden_budget)
    log(f"[ops] vectors {hidden.shape} at block {layer}")
    ops, vectors, psha = plan(job, hidden, randn)
    mine = shard(ops, shard_index, n_shards)
    counts = {k: sum(op["kind"] == k for op in ops) for k in KINDS}
    log(f"[ops] plan {psha}: {counts} unique ops; shard {shard_index}/{n_shards}: {len(mine)}")
    answers = execute(stack, mine, vectors, budget, log)
    vsha = _sha({k: array_sha(v) for k, v in vectors.items()})
    return {"job_sha": job.get("job_sha"), "hidden": hidden, "hidden_sha": array_sha(hidden),
            "vectors": vectors, "vectors_sha": vsha, "plan_sha": psha, "op_counts": counts,
            "shard": [shard_index, n_shards], "budget": budget, "hidden_budget": hidden_budget,
            "answers": answers}  # fmt: skip


def merge(parts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One answer table from every shard (shard 0's vectors are the result's). Refuses a missing /
    duplicate shard, shards of another job or plan, or steering vectors (same ids: the plans are
    equal) further apart than :data:`VECTOR_TOL`."""
    if not parts:
        raise ValueError("no shards")
    parts = sorted(parts, key=lambda p: int(p["shard"][0]))
    k = int(parts[0]["shard"][1])
    if [int(p["shard"][0]) for p in parts] != list(range(k)) or any(
        int(p["shard"][1]) != k for p in parts
    ):
        raise ValueError(f"shards {[p['shard'] for p in parts]} are not 0..{k - 1} of {k}")
    for key in ("job_sha", "plan_sha"):
        if len({p[key] for p in parts}) != 1:
            raise ValueError(f"shards disagree on {key}: {sorted({p[key] for p in parts})}")
    v0 = parts[0]["vectors"]
    worst = 0.0
    for p in parts[1:]:
        if sorted(p["vectors"]) != sorted(v0):
            raise ValueError("shards disagree on the vector table's ids")
        for vid, v in p["vectors"].items():
            a, b = np.asarray(v, np.float64), np.asarray(v0[vid], np.float64)
            if a.shape != b.shape:
                raise ValueError(f"shards disagree on vector {vid}'s shape")
            worst = max(worst, float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-12)))
    if worst > VECTOR_TOL:
        raise ValueError(f"shards' steering vectors differ by rel {worst:.2e} > {VECTOR_TOL}")
    answers: dict[str, Any] = {}
    for p in parts:
        for kk, v in p["answers"].items():
            if kk in answers:
                raise ValueError(f"op {kk} answered by two shards")
            answers[kk] = v
    keep = ("job_sha", "hidden", "hidden_sha", "vectors", "vectors_sha", "plan_sha", "op_counts")
    return {**{k2: parts[0][k2] for k2 in keep}, "answers": answers,
            "vector_max_rel_diff_across_shards": worst,
            "budget": parts[0].get("budget"), "n_shards": k}  # fmt: skip


def finish(
    job: dict[str, Any],
    merged: dict[str, Any],
    decode: Callable[[list[int]], str],
    engine: dict[str, Any],
    randn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Replay the merged answers into ``measure``'s result and stamp ``sweep.engine``."""
    if merged["job_sha"] != job.get("job_sha"):
        raise ValueError(f"answers are for job {merged['job_sha']}, not {job.get('job_sha')}")
    res = replay(
        job,
        merged["hidden"],
        merged["answers"],
        decode,
        randn,
        merged["plan_sha"],
        merged.get("vectors"),
    )
    res["sweep"]["engine"] = {**engine, **{k: merged.get(k) for k in (
        "plan_sha", "hidden_sha", "vectors_sha", "op_counts", "vector_max_rel_diff_across_shards",
        "budget",
        "n_shards")}}  # fmt: skip
    return res


# ---------------------------------------------------------------- torch side (GPU stacks)


def apply_steer(h: Any, mask: Any, unit: Any, beta: Any, norm_src: Any = None) -> Any:
    """``h <- h + beta * ||h|| * u`` at the masked positions of ``h [B, S, ...]`` (trailing dims
    flattened: the norm and ``u`` live in that flat space), computed in fp32 and written back in
    ``h``'s dtype; every other position is returned bit-unchanged (``Backend.steered``). With
    ``norm_src`` (same shape) the norm is ``||norm_src||`` instead: Kimi-K3 adds to prefix_sum
    the dose of full_sum (plan 0067 §2, ``attnres_full_sum``)."""
    import torch

    shp = h.shape
    flat = h.reshape(shp[0], shp[1], -1)
    x = flat.float()
    ref = x if norm_src is None else norm_src.reshape(shp[0], shp[1], -1).float().to(x.device)
    b = beta.to(x.device, torch.float32).view(-1, 1, 1)
    y = x + b * ref.norm(dim=-1, keepdim=True) * unit.to(x.device, torch.float32)[:, None, :]
    out = torch.where(mask.to(x.device)[..., None], y.to(h.dtype), flat)
    return out.reshape(shp)


class TorchStack:
    """:class:`Stack` over one abstract ``_forward``. A subclass implements
    ``_forward(ids [B,S] long CPU, steer, layer_out, select) -> device tensor``: block
    ``layer_out``'s output at ``select`` ``[(b, pos)]`` as ``[N, ...]`` when ``layer_out`` is set,
    else the logits at ``select`` ``[N, V]``; ``steer`` (or None) is
    ``{"layer", "mask" [B,S] bool, "unit" [B,d] fp32, "beta" [B] fp32}`` for :func:`apply_steer`."""

    def __init__(self, stop_ids: Sequence[int], pad_id: int) -> None:
        self.stop_ids, self.pad_id = [int(t) for t in stop_ids], int(pad_id)

    def _forward(self, ids: Any, steer: Any, layer_out: int | None, select: list[Any]) -> Any:
        raise NotImplementedError

    def _pad(self, rows: list[list[int]]) -> Any:
        import torch

        n = max(len(r) for r in rows)
        return torch.tensor([list(r) + [self.pad_id] * (n - len(r)) for r in rows])

    def _steer(self, rows: list[list[int]], steers: list[dict[str, Any] | None]) -> Any:
        import torch

        live = [s for s in steers if s is not None]
        if not live:
            return None
        layers = {int(s["layer"]) for s in live}
        if len(layers) != 1:
            raise ValueError(f"one micro-batch, several inject layers {sorted(layers)}")
        d = int(np.asarray(live[0]["vector"]).size)
        n = max(len(r) for r in rows)
        mask = torch.zeros(len(rows), n, dtype=torch.bool)
        unit = torch.zeros(len(rows), d, dtype=torch.float32)
        beta = torch.zeros(len(rows), dtype=torch.float32)
        for b, s in enumerate(steers):
            if s is None:
                continue
            ps = [int(p) for p in s["positions"]]
            if ps and max(ps) >= len(rows[b]):
                raise ValueError(f"steer position {max(ps)} beyond row length {len(rows[b])}")
            v = torch.as_tensor(np.asarray(s["vector"], np.float32)).flatten()
            nv = float(v.norm())
            unit[b] = v / nv if nv > 0 else v  # a zero vector steers nothing (calibration (a))
            beta[b] = float(s["beta"])
            mask[b, ps] = True
        return {"layer": layers.pop(), "mask": mask, "unit": unit, "beta": beta}

    def hidden(self, rows: list[list[int]], layer: int) -> Any:
        sel = [(b, len(r) - 1) for b, r in enumerate(rows)]
        h = self._forward(self._pad(rows), None, int(layer), sel)
        return h.reshape(len(rows), -1).float().cpu().numpy()

    def token_logprobs(self, rows, steers, queries):
        import torch

        sel = sorted({(b, int(p)) for b, qs in enumerate(queries) for p, _ in qs})
        where = {s: i for i, s in enumerate(sel)}
        logits = self._forward(self._pad(rows), self._steer(rows, steers), None, sel)
        lp = torch.log_softmax(logits.float(), dim=-1)
        out = []
        for b, qs in enumerate(queries):
            out.append([[float(lp[where[(b, int(p))], int(t)]) for t in toks] for p, toks in qs])
        return out

    def argmax(self, rows, steers):
        sel = [(b, len(r) - 1) for b, r in enumerate(rows)]
        logits = self._forward(self._pad(rows), self._steer(rows, steers), None, sel)
        return [int(t) for t in logits.float().argmax(dim=-1).cpu().tolist()]


class _ReadDone(Exception):  # noqa: N818 (a control-flow signal, not an error)
    """Raised by :class:`HookStack`'s read hook to stop the forward after the read block."""


class HookStack(TorchStack):
    """:class:`TorchStack` over an HF causal LM: the steer is a forward hook on decoder block
    ``layer`` (the block's output tensor, or element 0 of its output tuple), the read a hook on
    ``layer_out``; logits = the output embedding on ``model.model``'s last hidden state at the
    selected positions only."""

    def __init__(self, model: Any, blocks: Any, stop_ids: Sequence[int], pad_id: int) -> None:
        super().__init__(stop_ids, pad_id)
        self.model, self.blocks = model, blocks

    @staticmethod
    def logits(x: Any) -> Any:
        """Post-head logit transform (none here; a subject with a softcap overrides it)."""
        return x

    @staticmethod
    def _h(out: Any) -> Any:
        return out[0] if isinstance(out, tuple) else out

    def _forward(self, ids, steer, layer_out, select):
        import torch

        handles, store = [], {}
        if steer is not None:

            def steer_hook(_m: Any, _i: Any, out: Any) -> Any:
                h = self._h(out)
                new = apply_steer(h, steer["mask"], steer["unit"], steer["beta"])
                return (new, *out[1:]) if isinstance(out, tuple) else new

            handles.append(self.blocks[steer["layer"]].register_forward_hook(steer_hook))
        if layer_out is not None:
            bi = torch.tensor([b for b, _ in select])
            pi = torch.tensor([p for _, p in select])

            def read_hook(_m: Any, _i: Any, out: Any) -> None:
                h = self._h(out)
                # flat per position ([N, 4, 7168] -> [N, 28672] on V4: the steer's space)
                store["h"] = h[bi.to(h.device), pi.to(h.device)].float().reshape(len(select), -1)
                raise _ReadDone  # nothing past block layer_out is needed

            handles.append(self.blocks[layer_out].register_forward_hook(read_hook))
        try:
            with torch.inference_mode():
                dev = next(self.model.parameters()).device
                x = ids.to(dev)
                # the decoder stack, then the head on the selected positions only (a full
                # [B, S, V] logits tensor does not fit a production micro-batch)
                try:
                    h = self.model.model(input_ids=x, use_cache=False).last_hidden_state
                except _ReadDone:
                    return store["h"]
                bi = torch.tensor([b for b, _ in select], device=h.device)
                pi = torch.tensor([p for _, p in select], device=h.device)
                head = self.model.get_output_embeddings()
                sel = h[bi, pi].to(head.weight.device)
                return self.logits(head(sel))
        finally:
            for hd in handles:
                hd.remove()


# ---------------------------------------------------------------- stack + calibration helpers

CALIB_WORDS = 10
CALIB_PROMPT = "on_your_mind"


def stop_ids_of(generation_config: dict[str, Any]) -> list[int]:
    """``generate``'s stop ids: ``generation_config.json``'s ``eos_token_id`` (an int or a list)."""
    e = generation_config.get("eos_token_id")
    ids = [e] if isinstance(e, int) else list(e or [])
    if not ids:
        raise ValueError("generation_config has no eos_token_id")
    return [int(i) for i in ids]


def row_major_order(select: list[tuple[int, int]]) -> list[int]:
    """For a ``logit_mask`` forward (rows come back in row-major (b, pos) order): the index into
    that output of each ``select`` entry, in ``select``'s order. Entries must be distinct."""
    if len(set(select)) != len(select):
        raise ValueError("duplicate (row, pos) in select")
    order = sorted(range(len(select)), key=lambda i: select[i])
    where = [0] * len(select)
    for rank, i in enumerate(order):
        where[i] = rank
    return where


def mentions(reply: str, word: str) -> bool:
    """The concept word, its singular stem (``trumpets`` -> ``trumpet``, ``treasures`` ->
    ``treasure``, ``berries`` -> ``berry``) or a simple inflection of either, as a whole word,
    case-folded."""
    import re

    w = word.lower()
    forms = {w}
    if w.endswith("ies") and len(w) >= 6:
        forms.add(w[:-3] + "y")
    elif w.endswith(("ses", "xes", "zes", "ches", "shes")) and len(w) >= 6:
        forms |= {w[:-2], w[:-1]}  # branches -> branch, purses -> purse, avalanches -> avalanche
    elif w.endswith("s") and not w.endswith("ss") and len(w) >= 5:
        forms.add(w[:-1])  # stems of 4+ letters only (no "kit", "lie", "bon")
    r = reply.lower()
    return any(re.search(rf"\b{re.escape(f)}(s|es|ed|ing|'s)?\b", r) for f in forms)


CALIB_MENTION = 0.5  # (b): some beta of the grid surfaces the concept in >= half the replies
CALIB_RANK_AGREE = 0.95  # (c): the injected word's rank unchanged, single vs production packing
CALIB_SPAN_REL = 1e-2  # (d): the steered state is h + beta*||h||*u up to the bf16 write-back


def _rank(scores: Sequence[float], i: int) -> int:
    return 1 + sum(1 for j, x in enumerate(scores) if x > scores[i] or (x == scores[i] and j < i))


def calib_report(raw: dict[str, Any], decode: Callable[[list[int]], str]) -> dict[str, Any]:
    """Verdicts of plan 0067 §5 from the stack's raw calibration outputs (pure), each with a
    ``pass``. ``g0_pass`` (the run refuses to launch without it) = the ENGINE checks (a) no-op and
    (d) local steer; (b) concept mention and (c) batched vs single are recorded measurements of
    the subject (Camila / coordinator 2026-11-04: GO / NO-GO is the registered median-RR rule in
    ``calibrate``, and batch-composition noise is a stack property, characterised, not gated)."""
    a = raw["noop"]
    base_lp = [x for r in a["base_lp"] for x in r]
    other = [x for k in ("beta0_lp", "zero_lp") for r in a[k] for x in r]
    rep: dict[str, Any] = {"gpu": raw.get("gpu")}
    ra = {
        "beta0_logprobs_equal": a["beta0_lp"] == a["base_lp"],
        "zero_vec_logprobs_equal": a["zero_lp"] == a["base_lp"],
        "beta0_greedy_equal": a["beta0_greedy"] == a["base_greedy"],
        "zero_vec_greedy_equal": a["zero_greedy"] == a["base_greedy"],
        "max_abs_logprob_diff": max(abs(x - y) for x, y in zip(other, base_lp * 2, strict=True)),
    }
    ra["pass"] = all(v for k, v in ra.items() if k.endswith("_equal"))
    rep["a_noop"] = ra
    m = raw["mention"]
    base = decode(m["base"])
    per_beta: dict[str, Any] = {}
    for b, rows in m["steered"].items():
        replies = {w: decode(ids) for w, ids in rows.items()}
        hits = [w for w, r in replies.items() if mentions(r, w)]
        per_beta[b] = {"mention_rate": len(hits) / len(replies), "hits": hits,
                       "replies": replies}  # fmt: skip
    best = max((v["mention_rate"] for v in per_beta.values()), default=0.0)
    rep["b_mention"] = {"prompt": CALIB_PROMPT, "unsteered_reply": base,
                        "unsteered_mentions": [w for w in m["words"] if mentions(base, w)],
                        "per_beta": per_beta, "best_rate": best,
                        "pass": best >= CALIB_MENTION}  # fmt: skip
    c = raw["batch"]
    agree, diffs = [], []
    for row in c["ops"]:
        single, packed, i = row["single"], row["packed"], int(row["target"])
        agree.append(_rank(single, i) == _rank(packed, i))
        diffs += [abs(x - y) for x, y in zip(single, packed, strict=True)]
    rate = sum(agree) / len(agree)
    rep["c_batched_vs_single"] = {"rank_agreement": rate, "n_ops": len(agree),
                                  "max_abs_diff": max(diffs), "bit_equal": max(diffs) == 0.0,
                                  "pass": rate >= CALIB_RANK_AGREE}  # fmt: skip
    d = dict(raw["local"])
    d["pass"] = d["pre_span_max_abs_diff"] == 0.0 and d["in_span_max_rel_err"] <= CALIB_SPAN_REL
    rep["d_steer_is_local"] = d
    rep["g0_pass"] = rep["a_noop"]["pass"] and rep["d_steer_is_local"]["pass"]
    rep["recorded_not_gated"] = ["b_mention", "c_batched_vs_single"]
    return rep


# what ``generate`` would apply at do_sample=False besides the argmax (plan 0067 §3): the stack
# must refuse a snapshot that sets one, since lock-step greedy is a plain argmax
GREEDY_PROCESSORS = {"repetition_penalty": (None, 1.0), "no_repeat_ngram_size": (None, 0),
                     "encoder_no_repeat_ngram_size": (None, 0), "suppress_tokens": (None, []),
                     "begin_suppress_tokens": (None, []), "bad_words_ids": (None, []),
                     "min_new_tokens": (None, 0), "min_length": (None, 0),
                     "forced_bos_token_id": (None,), "forced_eos_token_id": (None,),
                     "sequence_bias": (None, {}), "num_beams": (None, 1),
                     "num_beam_groups": (None, 1), "diversity_penalty": (None, 0.0),
                     "exponential_decay_length_penalty": (None,),
                     "encoder_repetition_penalty": (None, 1.0)}  # fmt: skip


def check_generation_config(generation_config: dict[str, Any]) -> dict[str, Any]:
    """Refuse a generation config whose greedy decoding is not a plain argmax; returns the record
    (``engine.generation_config_check``)."""
    bad = {k: generation_config[k] for k, ok in GREEDY_PROCESSORS.items()
           if k in generation_config and generation_config[k] not in ok}  # fmt: skip
    if bad:
        raise ValueError(f"generation_config sets greedy-time processors {bad}: HF generate "
                         "would apply them, a plain argmax would not")  # fmt: skip
    return {"checked": sorted(GREEDY_PROCESSORS), "non_default": {}}
