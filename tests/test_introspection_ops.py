"""Offline tests for ``wsbench.adapt.introspection_ops`` (plan 0067): record / replay equals a
direct engine, the executor's batching and greedy rules, shards, and the torch steer."""

from contextlib import contextmanager

import numpy as np
import pytest
from test_adapt_introspection import FakeEngine, FakeTok, _randn

from wsbench.adapt import introspection as ii
from wsbench.adapt import introspection_ops as ops
from wsbench.adapt import subjects
from wsbench.adapt.subjects import Subject

D = 24


@pytest.fixture(scope="module")
def bank():
    return ii.registered_bank()


@pytest.fixture(scope="module")
def job(bank):
    s = Subject("fake-32l", "org/Fake-32L", "Fake-32L", 32, "fake", "abc123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(subjects.SUBJECTS, s.key, s)
        yield ii.build_job(s.key, FakeTok(), bank)


class FakeStack:
    """A :class:`ops.Stack` computing exactly :class:`FakeEngine`'s function from padded-free
    rows: the steer reaches it as data, the readouts are recovered from the row's ids."""

    def __init__(self, job, stop_ids=(), d=D):
        self.eng = FakeEngine(job, d=d)
        self.job = job
        self.stop_ids = list(stop_ids)
        self.batches: list[tuple[str, int, int]] = []  # (kind, n_rows, max_len)
        self.word_of_cont = {tuple(c): w for w, c in job["protocol"]["cont_ids"].items()}

    @contextmanager
    def _with(self, steer):
        if steer is None:
            yield
        else:
            with self.eng.steer(steer["layer"], steer["positions"], steer["vector"],
                                steer["beta"]):  # fmt: skip
                yield

    def hidden(self, rows, layer):
        self.batches.append(("hidden", len(rows), max(map(len, rows))))
        return np.stack([self.eng.last_hidden(r, layer) for r in rows]).astype(np.float32)

    def token_logprobs(self, rows, steers, queries):
        self.batches.append(("lp", len(rows), max(map(len, rows))))
        out = []
        pr = self.job["protocol"]["ids"]
        for r, s, qs in zip(rows, steers, queries, strict=True):
            with self._with(s):
                if r[: len(pr)] == pr and len(qs) and qs[0][0] == len(pr) - 1 and len(r) > len(pr):
                    c = r[len(pr) :]
                    tot = self.eng.cont_logprobs(pr, [c])[0]
                    # spread the summed score over the continuation's tokens (sums back exactly
                    # in binary for halves)
                    out.append([[tot] if j == 0 else [0.0] for j in range(len(qs))])
                else:
                    ((_, toks),) = qs
                    out.append([self.eng.next_logprobs(r, toks)])
        return out

    def argmax(self, rows, steers):
        self.batches.append(("argmax", len(rows), max(map(len, rows))))
        out = []
        for _r, s in zip(rows, steers, strict=True):
            with self._with(s):
                bad = self.eng.cur is not None and self.eng.cur[1] >= 6
            out.append(7 if bad else 5)
        return out


def _decode(ids):
    if all(t == 7 for t in ids):
        return "zzz zzz zzz"
    return "A fine reply."


class GreedyAwareEngine(FakeEngine):
    """FakeEngine whose greedy reply is the decode of :class:`FakeStack`'s generated ids, so the
    direct and the replayed path see the same function."""

    def greedy(self, ids, n):
        bad = self.cur is not None and self.cur[1] >= 6
        return _decode([7 if bad else 5] * n)


def test_record_replay_equals_a_direct_engine(job):
    direct = ii.measure(GreedyAwareEngine(job, d=D), job, randn=_randn, log=lambda s: None)
    stack = FakeStack(job)
    part = ops.run_job(stack, job, randn=_randn, log=lambda s: None)
    merged = ops.merge([part])
    res = ops.finish(job, merged, _decode, {"stack": "fake"}, randn=_randn)
    np.testing.assert_array_equal(res["concept"], direct["concept"])
    np.testing.assert_array_equal(res["gaussian"], direct["gaussian"])
    eng = res["sweep"].pop("engine")
    assert eng["stack"] == "fake" and eng["plan_sha"] == part["plan_sha"]
    assert res["sweep"] == direct["sweep"]


def test_duplicate_ops_execute_once_and_cross_reuses_inject(job):
    hid = ops.compute_hidden(FakeStack(job), ops.vector_requests(job), job["inject_layer"])
    plan, vectors, _ = ops.plan(job, hid, _randn)
    n_paper = len(job["protocol"]["paper_words"])
    in_paper = sum(job["cross_partner"][w] in job["protocol"]["paper_words"]
                   for w in job["protocol"]["paper_words"])  # fmt: skip
    n_cont = sum(op["kind"] == "cont" for op in plan)
    assert n_cont == 1 + len(job["betas"]) * (2 * n_paper + n_paper - in_paper)
    keys = [ops.op_key(op) for op in plan]
    assert len(keys) == len(set(keys))
    assert all(op["steer"] is None or op["steer"]["vec"] in vectors for op in plan)


def test_replay_refuses_a_missing_answer_and_extra_answers(job):
    stack = FakeStack(job)
    part = ops.run_job(stack, job, randn=_randn, log=lambda s: None)
    ans = dict(part["answers"])
    ans.pop(next(iter(ans)))
    with pytest.raises(KeyError, match="never planned"):
        ops.replay(job, part["hidden"], ans, _decode, _randn)
    extra = {**part["answers"], "deadbeef": [0.0]}
    with pytest.raises(RuntimeError, match="never asked"):
        ops.replay(job, part["hidden"], extra, _decode, _randn)
    with pytest.raises(RuntimeError, match="call sequence"):
        ops.replay(job, part["hidden"], part["answers"], _decode, _randn, plan_sha="x")
    moved = {k: v * 1.01 for k, v in part["vectors"].items()}
    with pytest.raises(RuntimeError, match="not the one the plan"):
        ops.replay(job, part["hidden"], part["answers"], _decode, _randn, vectors=moved)
    # another machine's last-bit noise in the vectors keeps every op key (ids by call order)
    noisy = part["hidden"] * np.float32(1 + 1e-7)
    ops.replay(job, noisy, part["answers"], _decode, _randn, vectors=part["vectors"])


def test_recorder_refuses_a_zero_vector_and_nesting():
    rec = ops.Recorder({}, 3)
    with pytest.raises(ValueError, match="zero norm"), rec.steer(3, [1], np.zeros(4), 2.0):
        pass
    with rec.steer(3, [1], np.ones(4), 2.0), pytest.raises(RuntimeError, match="nested"):  # noqa: SIM117
        with rec.steer(3, [1], np.ones(4), 2.0):
            pass
    with pytest.raises(ValueError, match="block 4"):
        rec.last_hidden([1], 4)


def test_pack_respects_the_budget():
    assert ops.pack([10, 10, 10, 30], 30) == [[0, 1, 2], [3]]
    assert ops.pack([50, 5], 30) == [[0], [1]]
    for mb in ops.pack([7, 3, 9, 9, 2, 11, 4], 20):
        lens = [[7, 3, 9, 9, 2, 11, 4][i] for i in mb]
        assert len(mb) == 1 or len(lens) * max(lens) <= 20


def test_execute_batches_mixed_steers_and_keeps_answers_per_op(job):
    stack = FakeStack(job)
    hid = ops.compute_hidden(stack, ops.vector_requests(job), job["inject_layer"])
    plan, vectors, _ = ops.plan(job, hid, _randn)
    sub = [op for op in plan if op["kind"] != "greedy"][:30]
    ans = ops.execute(stack, sub, vectors, budget=4000, log=lambda s: None)
    one = {}
    for op in sub:
        one.update(ops.execute(FakeStack(job), [op], vectors, log=lambda s: None))
    assert ans == one
    lp = [b for b in stack.batches if b[0] == "lp"]
    assert len(lp) > 1 and all(n * m <= 4000 for _, n, m in lp)


def test_greedy_stops_at_the_first_stop_id_and_runs_n_steps():
    class S:
        stop_ids = (9,)

        def argmax(self, rows, steers):
            return [9 if r[0] == 1 and len(r) >= 4 else len(r) for r in rows]

    out = ops.run_greedy(S(), [{"ids": [1, 0], "n": 10, "steer": None},
                               {"ids": [2], "n": 3, "steer": None}], {})  # fmt: skip
    assert out == [[2, 3], [1, 2, 3]]


def test_shards_partition_and_merge_checks(job):
    parts = [ops.run_job(FakeStack(job), job, i, 3, randn=_randn, log=lambda s: None)
             for i in range(3)]  # fmt: skip
    whole = ops.run_job(FakeStack(job), job, randn=_randn, log=lambda s: None)
    merged = ops.merge(parts)
    assert merged["answers"] == whole["answers"]
    assert merged["n_shards"] == 3 and merged["vectors_sha"] == whole["vectors_sha"]
    kinds = [sum(1 for k in p["answers"]) for p in parts]
    assert max(kinds) - min(kinds) <= 3
    with pytest.raises(ValueError, match=r"not 0\.\.2"):
        ops.merge(parts[:2])

    def scaled(p, f):
        return dict(p, vectors={k: v * f for k, v in p["vectors"].items()})

    near = [parts[0], scaled(parts[1], 1 + 1e-5), parts[2]]
    assert 0 < ops.merge(near)["vector_max_rel_diff_across_shards"] < ops.VECTOR_TOL
    far = [parts[0], scaled(parts[1], 1.01), parts[2]]
    with pytest.raises(ValueError, match="vectors differ"):
        ops.merge(far)
    with pytest.raises(ValueError, match="plan_sha"):
        ops.merge([parts[0], dict(parts[1], plan_sha="x"), parts[2]])
    with pytest.raises(ValueError, match="answered by two"):
        ops.merge([dict(parts[0], shard=[0, 2]), dict(parts[0], shard=[1, 2])])


def test_finish_refuses_another_job(job):
    part = ops.run_job(FakeStack(job), job, randn=_randn, log=lambda s: None)
    with pytest.raises(ValueError, match="answers are for job"):
        ops.finish(dict(job, job_sha="other"), ops.merge([part]), _decode, {})


def test_helpers():
    assert ops.stop_ids_of({"eos_token_id": 5}) == [5]
    assert ops.stop_ids_of({"eos_token_id": [5, 6]}) == [5, 6]
    with pytest.raises(ValueError):
        ops.stop_ids_of({})
    assert ops.row_major_order([(1, 2), (0, 5), (1, 0)]) == [2, 0, 1]
    with pytest.raises(ValueError):
        ops.row_major_order([(0, 1), (0, 1)])
    assert ops.mentions("I keep thinking of Trumpets.", "trumpets")
    assert ops.mentions("the ocean's roar", "ocean")
    assert not ops.mentions("a cartoon", "car")
    assert ops.mentions("## The Sound of the Trumpet", "trumpets")
    assert ops.mentions("one more berry", "berries") and ops.mentions("a treasure", "treasures")
    assert ops.mentions("two branch lines", "branches")
    assert ops.mentions("a xylophone", "xylophones")
    assert ops.mentions("her purse", "purses") and ops.mentions("an avalanche", "avalanches")
    assert ops.mentions("the suitcase", "suitcases") and ops.mentions("a database", "databases")
    assert not ops.mentions("a camping kit", "kites") and not ops.mentions("lie down", "lies")
    assert not ops.mentions("bon voyage", "bones")


def test_calib_report_verdicts():
    raw = {
        "noop": {
            "base_lp": [[-1.0, -2.0]],
            "beta0_lp": [[-1.0, -2.0]],
            "zero_lp": [[-1.0, -2.5]],
            "base_greedy": [1, 2],
            "beta0_greedy": [1, 2],
            "zero_greedy": [1, 2],
        },
        "mention": {"words": ["ocean"], "base": [0], "steered": {"4": {"ocean": [1]}}},
        "batch": {"ops": [{"single": [-1.0, -2.0], "packed": [-1.0, -2.0], "target": 0}]},
        "local": {"pre_span_max_abs_diff": 0.0, "in_span_max_rel_err": 0.001},
    }
    rep = ops.calib_report(raw, lambda ids: "the ocean" if ids == [1] else "hello")
    assert rep["a_noop"]["beta0_logprobs_equal"] and not rep["a_noop"]["zero_vec_logprobs_equal"]
    assert rep["a_noop"]["max_abs_logprob_diff"] == 0.5
    assert rep["b_mention"]["per_beta"]["4"]["mention_rate"] == 1.0
    assert rep["c_batched_vs_single"]["bit_equal"] and rep["c_batched_vs_single"]["pass"]
    assert rep["a_noop"]["pass"] is False and rep["g0_pass"] is False
    raw["noop"]["zero_lp"] = [[-1.0, -2.0]]
    assert ops.calib_report(raw, lambda ids: "the ocean" if ids == [1] else "hi")["g0_pass"]
    raw["batch"]["ops"][0]["packed"] = [-2.5, -2.0]  # the target's rank flips
    rep2 = ops.calib_report(raw, lambda ids: "x")  # and no reply mentions the concept
    assert not rep2["c_batched_vs_single"]["pass"] and not rep2["b_mention"]["pass"]
    assert rep2["g0_pass"]  # (b) and (c) are recorded, not gated: g0 = engine checks (a), (d)
    raw["local"]["pre_span_max_abs_diff"] = 1e-3
    assert not ops.calib_report(raw, lambda ids: "x")["g0_pass"]
    raw["local"]["pre_span_max_abs_diff"] = 0.0
    raw["local"]["pre_span_logits_max_abs_diff"] = 1.8  # MoE re-routing noise: recorded only
    assert ops.calib_report(raw, lambda ids: "x")["g0_pass"]


# ---------------------------------------------------------------- torch


def test_apply_steer_matches_backend_steered():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM

    from wsbench.produce.backend import Backend

    torch.manual_seed(0)
    cfg = LlamaConfig(vocab_size=50, hidden_size=32, intermediate_size=64, num_hidden_layers=3,
                      num_attention_heads=4, num_key_value_heads=4,
                      max_position_embeddings=64)  # fmt: skip
    model = LlamaForCausalLM(cfg).to(torch.bfloat16).eval()
    be = Backend(model=model, tokenizer=None, device="cpu", model_id="tiny")
    stack = ops.HookStack(model, model.model.layers, stop_ids=[0], pad_id=0)
    ids = [3, 7, 9, 11, 4, 5, 6, 8]
    vec = np.random.default_rng(1).standard_normal(32).astype(np.float32)
    pos = [2, 3, 4]
    qs = [[(5, [1, 2, 3]), (7, [4])]]
    with be.steered(1, pos, vec, 4.0), torch.no_grad():
        ref = torch.log_softmax(model(torch.tensor([ids]), use_cache=False).logits.float(), -1)[0]
    st = {"layer": 1, "positions": pos, "beta": 4.0, "vector": vec}
    got = stack.token_logprobs([ids], [st], qs)[0]
    assert got[0] == [float(ref[5, t]) for t in (1, 2, 3)] and got[1] == [float(ref[7, 4])]
    # batched with an unsteered, longer row: the steered row is unchanged
    got2 = stack.token_logprobs([ids, [*ids, 9, 9]], [st, None], [*qs, qs[0]])
    assert got2[0] == got
    with torch.no_grad():
        plain = torch.log_softmax(model(torch.tensor([ids]), use_cache=False).logits.float(), -1)
    base = stack.token_logprobs([ids], [None], qs)[0]
    assert base[1] == [float(plain[0, 7, 4])]
    assert stack.token_logprobs([ids], [dict(st, beta=0.0)], qs)[0] == base
    assert stack.token_logprobs([ids], [dict(st, vector=np.zeros(32, np.float32))], qs)[0] == base
    h = stack.hidden([ids, ids[:5]], 1)
    cap = be.capture(ids, [1], [7])[1][0].numpy()
    np.testing.assert_array_equal(h[0], cap)


def test_apply_steer_touches_only_masked_positions_and_flattens_streams():
    torch = pytest.importorskip("torch")
    h = torch.randn(2, 5, 4, 3, dtype=torch.bfloat16)  # an mHC-like [B, S, streams, d]
    mask = torch.zeros(2, 5, dtype=torch.bool)
    mask[0, 1] = mask[1, 3] = True
    unit = torch.nn.functional.normalize(torch.randn(2, 12), dim=-1)
    beta = torch.tensor([2.0, 3.0])
    out = ops.apply_steer(h, mask, unit, beta)
    assert torch.equal(out[~mask], h[~mask])
    x = h[0, 1].reshape(-1).float()
    want = (x + 2.0 * x.norm() * unit[0]).to(torch.bfloat16).reshape(4, 3)
    assert torch.equal(out[0, 1], want)


def test_torch_stack_pipeline_equals_hfengine_on_a_tiny_model(bank):
    """The whole path (vectors, plan, HookStack execution with right padding and mixed-steer
    micro-batches, lock-step greedy with a stop id, replay) against ``measure(HFEngine)`` on the
    same tiny fp32 model. Skipped in CI (no torch); run it before any GPU spend."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM

    from wsbench.produce.backend import Backend

    s = Subject("tiny-4l", "org/Tiny-4L", "Tiny-4L", 4, "fake", "abc123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(subjects.SUBJECTS, s.key, s)
        job = ii.build_job(s.key, FakeTok(), bank, betas=(4.0,))
    torch.manual_seed(0)
    cfg = LlamaConfig(vocab_size=4096, hidden_size=32, intermediate_size=64, num_hidden_layers=4,
                      num_attention_heads=4, num_key_value_heads=4, max_position_embeddings=512,
                      eos_token_id=2, bos_token_id=1)  # fmt: skip
    model = LlamaForCausalLM(cfg).float().eval()
    model.generation_config.pad_token_id = 2

    def decode(ids):
        return " ".join(str(int(i)) for i in ids if int(i) != 2)

    class Dec:
        def decode(self, ids, skip_special_tokens=True):
            return decode(list(ids))

    eng = ii.HFEngine(Backend(model=model, tokenizer=None, device="cpu", model_id="tiny"))
    eng._tok = Dec()
    randn = ii.gaussian_rows
    direct = ii.measure(eng, job, randn=randn, log=lambda s: None)
    stack = ops.HookStack(model, model.model.layers, stop_ids=[2], pad_id=0)
    part = ops.run_job(stack, job, budget=3000, randn=randn, log=lambda s: None)
    res = ops.finish(job, ops.merge([part]), decode, {"stack": "tiny"}, randn=randn)
    np.testing.assert_allclose(res["concept"], direct["concept"], rtol=1e-5, atol=1e-6)
    a, b = res["sweep"], direct["sweep"]
    assert a["beta0"]["top5"] == b["beta0"]["top5"]
    for cell in ("inject", "gaussian", "cross"):
        same = [a["betas"]["4"][cell][w] == b["betas"]["4"][cell][w] for w in a["beta0"]["rr"]]
        assert sum(same) >= 0.96 * len(same), cell
    for k in ("p_yes_inject", "p_yes_gaussian"):
        for w, p in a["betas"]["4"][k].items():
            assert p == pytest.approx(b["betas"]["4"][k][w], abs=1e-4)
    replies = [(x["reply"], y["reply"]) for x, y in zip(a["neutral"], b["neutral"], strict=True)]
    assert all(x == y for x, y in replies)


def test_apply_steer_norm_src_is_the_kimi_full_sum_recipe():
    torch = pytest.importorskip("torch")
    prefix = torch.randn(1, 4, 6, dtype=torch.bfloat16)
    br = torch.randn(4, 2, 6, dtype=torch.bfloat16)  # [b*s, n_blocks, d]
    full = prefix.float() + br.float().sum(1).view(1, 4, 6)
    mask = torch.tensor([[False, True, True, False]])
    unit = torch.nn.functional.normalize(torch.randn(1, 6), dim=-1)
    out = ops.apply_steer(prefix, mask, unit, torch.tensor([3.0]), norm_src=full)
    assert torch.equal(out[~mask], prefix[~mask])
    want = (prefix[0, 1].float() + 3.0 * full[0, 1].norm() * unit[0]).to(torch.bfloat16)
    assert torch.equal(out[0, 1], want)
    new_full = out.float() + br.float().sum(1).view(1, 4, 6)
    delta = 3.0 * full[0, 2].norm() * unit[0]
    assert torch.allclose(new_full[0, 2] - full[0, 2], delta, rtol=2e-2, atol=2e-2)


def test_hookstack_forward_kwargs_are_fresh_per_forward():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM

    cfg = LlamaConfig(vocab_size=50, hidden_size=16, intermediate_size=32, num_hidden_layers=2,
                      num_attention_heads=2, num_key_value_heads=2,
                      max_position_embeddings=64)  # fmt: skip
    model = LlamaForCausalLM(cfg).eval()
    made = []

    def kwargs():
        made.append(object())
        return {"use_cache": False}

    stack = ops.HookStack(model, model.model.layers, [0], 0, forward_kwargs=kwargs)
    stack.token_logprobs([[1, 2, 3]], [None], [[(2, [4])]])
    stack.hidden([[1, 2, 3]], 1)
    assert len(made) == 2 and made[0] is not made[1]
    del torch


def test_set_kda_mode_switches_every_kimi_delta_attention():
    class KimiDeltaAttention:
        def __init__(self):
            self.mode = "chunk"

    class Other:
        mode = "chunk"

    class Model:
        def __init__(self):
            self.kda = [KimiDeltaAttention(), KimiDeltaAttention()]
            self.other = Other()

        def modules(self):
            return [*self.kda, self.other]

    m = Model()
    assert ops.set_kda_mode(m, "fused_recurrent") == 2
    assert all(k.mode == "fused_recurrent" for k in m.kda) and m.other.mode == "chunk"
    with pytest.raises(ValueError):
        ops.set_kda_mode(m, "parallel")


def test_full_depth_causality_gate_for_batch_invariant_stacks():
    raw = {
        "noop": {"base_lp": [[-1.0]], "beta0_lp": [[-1.0]], "zero_lp": [[-1.0]],
                 "base_greedy": [1], "beta0_greedy": [1], "zero_greedy": [1]},
        "mention": {"words": ["ocean"], "base": [0], "steered": {"4": {"ocean": [1]}}},
        "batch": {"ops": [{"single": [-1.0, -2.0], "packed": [-1.0, -2.0], "target": 0}]},
        "local": {"pre_span_max_abs_diff": 0.0, "in_span_max_rel_err": 0.001,
                  "pre_span_logits_max_abs_diff": 5.6},  # Kimi chunk-mode KDA
    }  # fmt: skip
    dec = lambda ids: "x"  # noqa: E731
    assert ops.calib_report(raw, dec)["g0_pass"]  # recorded only by default (MoE shape noise)
    assert not ops.calib_report(raw, dec, gate_full_depth=True)["g0_pass"]
    raw["local"]["pre_span_logits_max_abs_diff"] = 0.0  # fused_recurrent: exactly causal
    assert ops.calib_report(raw, dec, gate_full_depth=True)["g0_pass"]


def test_hookstack_steer_never_moves_earlier_logits():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from transformers import LlamaConfig, LlamaForCausalLM

    torch.manual_seed(0)
    cfg = LlamaConfig(vocab_size=60, hidden_size=32, intermediate_size=64, num_hidden_layers=3,
                      num_attention_heads=4, num_key_value_heads=4,
                      max_position_embeddings=64)  # fmt: skip
    model = LlamaForCausalLM(cfg).eval()
    stack = ops.HookStack(model, model.model.layers, [0], 0)
    row = [3, 9, 4, 7, 11, 5, 8, 2, 6, 10]
    vec = np.random.default_rng(0).standard_normal(32).astype(np.float32)
    st = stack._steer([row], [{"layer": 1, "positions": [6, 7, 8], "beta": 4.0, "vector": vec}])
    sel = [(0, p) for p in range(6)]
    a = stack._forward(stack._pad([row]), None, None, sel)
    b = stack._forward(stack._pad([row]), st, None, sel)
    assert torch.equal(a, b)  # the calib (d) full-depth check: exactly 0 on a causal stack
    later = [(0, 9)]
    assert not torch.equal(stack._forward(stack._pad([row]), None, None, later),
                           stack._forward(stack._pad([row]), st, None, later))  # fmt: skip


def _tiny_glm5_next():
    """A random fp32 GLM-5.3-Flash-shaped text model: three KDA blocks, one DSA block, mHC x4."""
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers.models.glm5_next")
    from transformers.models.glm5_next.configuration_glm5_next import Glm5NextTextConfig
    from transformers.models.glm5_next.modeling_glm5_next import Glm5NextTextModel

    torch.manual_seed(0)
    lt = ["linear_attention"] * 3 + ["deepseek_sparse_attention"]
    cfg = Glm5NextTextConfig(
        vocab_size=97, hidden_size=64, intermediate_size=96, moe_intermediate_size=32,
        num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=4, n_routed_experts=8,
        num_experts_per_tok=2, n_shared_experts=1, first_k_dense_replace=1, q_lora_rank=32,
        kv_lora_rank=16, qk_nope_head_dim=16, qk_rope_head_dim=0, qk_head_dim=16, v_head_dim=16,
        index_n_heads=2, index_head_dim=16, index_topk=64, index_kpool=4, hc_mult=4,
        layer_types=lt, mlp_layer_types=["dense"] + ["sparse"] * 3, indexer_types=["full"] * 4,
        linear_attn_config={"num_heads": 2, "head_dim": 16, "short_conv_kernel_size": 4,
                            "gate_lower_bound": -5.0, "kda_layers": [0, 1, 2],
                            "full_attn_layers": [3]},
        pad_token_id=0, num_nextn_predict_layers=0,
    )  # fmt: skip
    return torch, Glm5NextTextModel(cfg).eval()


def test_set_kda_mode_switches_glm5_next_to_the_recurrent_step():
    torch, m = _tiny_glm5_next()
    import transformers.models.glm5_next.modeling_glm5_next as mg

    ids = torch.randint(1, 97, (1, 70))  # > one 64-token chunk
    with torch.inference_mode():
        chunk = m(input_ids=ids, use_cache=False).last_hidden_state
        try:
            assert ops.set_kda_mode(m, "fused_recurrent") == 3
            assert mg.chunk_kimi_delta_attention.__name__ == "recurrent_as_chunk"
            rec = m(input_ids=ids, use_cache=False).last_hidden_state
            # token-sequential: a prefix's states do not depend on later tokens (to fp32 rounding:
            # the MoE blocks' per-expert token grouping changes with later tokens, ~1e-8 on CPU;
            # the GPU calibration records the full-depth pre-span diff, 0.0 on the subject). The
            # stock torch chunk path is itself causal (the #363 leak is fla's Triton kernel), so
            # this loop does not by itself show the swap: the leaky-chunk test below does.
            for p in (5, 63, 64):
                other = ids.clone()
                other[0, p + 1 :] = (ids[0, p + 1 :] % 96) + 1
                moved = m(input_ids=other, use_cache=False).last_hidden_state
                assert torch.allclose(moved[0, : p + 1], rec[0, : p + 1], atol=1e-6, rtol=0)
                assert not torch.equal(moved[0, p + 1 :], rec[0, p + 1 :])
                cut = m(input_ids=ids[:, : p + 1], use_cache=False).last_hidden_state
                assert torch.allclose(cut[0, -1], rec[0, p], atol=1e-5)
        finally:
            assert ops.set_kda_mode(m, "chunk") == 3
        assert mg.chunk_kimi_delta_attention is mg._wsb_chunk_kda
        again = m(input_ids=ids, use_cache=False).last_hidden_state
    assert torch.equal(again, chunk)  # chunk restored
    assert torch.allclose(rec, chunk, atol=1e-4)  # the same function, another schedule


def test_set_kda_mode_removes_a_leaky_chunk_kernel(monkeypatch):
    """The swap is what makes the GLM-5.3-Flash stack causal when the chunk kernel is not (fla's
    Triton chunk kernel, #363): a chunk stand-in that leaks the sequence mean into every position
    moves a prefix; after ``fused_recurrent`` the prefix no longer moves; ``chunk`` brings the
    leaky kernel back (it restores whatever the module's chunk function was)."""
    torch, m = _tiny_glm5_next()
    import transformers.models.glm5_next.modeling_glm5_next as mg

    real = mg.__dict__.get("_wsb_chunk_kda", mg.chunk_kimi_delta_attention)

    def leaky(query, key, value, g, beta, **kw):
        out, state = real(query, key, value, g, beta, **kw)
        return out + 0.5 * value.mean(dim=1, keepdim=True).to(out.dtype), state

    monkeypatch.setitem(mg.__dict__, "_wsb_chunk_kda", leaky)
    monkeypatch.setattr(mg, "chunk_kimi_delta_attention", leaky)
    ids = torch.randint(1, 97, (1, 40))
    other = ids.clone()
    other[0, 20:] = (ids[0, 20:] % 96) + 1

    def prefix_moves() -> bool:
        a = m(input_ids=ids, use_cache=False).last_hidden_state[0, :20]
        b = m(input_ids=other, use_cache=False).last_hidden_state[0, :20]
        return not torch.allclose(a, b, atol=1e-6, rtol=0)

    with torch.inference_mode():
        assert prefix_moves()  # the stand-in leaks
        try:
            ops.set_kda_mode(m, "fused_recurrent")
            assert not prefix_moves()  # the swap removes it
        finally:
            ops.set_kda_mode(m, "chunk")
        assert mg.chunk_kimi_delta_attention is leaky and prefix_moves()


def test_hookstack_reads_glm5_next_streams_flat():
    torch, m = _tiny_glm5_next()

    class Wrap(torch.nn.Module):  # HookStack's shape: .model (the text model), output embedding
        def __init__(self, text):
            super().__init__()
            self.model, self.head = text, torch.nn.Linear(64, 97, bias=False)

        def get_output_embeddings(self):
            return self.head

    w = Wrap(m).eval()
    stack = ops.HookStack(w, m.layers, [0], 0)
    rows = [[5, 6, 7, 8, 9], [10, 11, 12]]
    h = stack.hidden(rows, 1)
    assert h.shape == (2, 4 * 64)  # [B, S, 4, 64] read flat, stream-major
    with torch.inference_mode():
        raw = []
        hd = m.layers[1].register_forward_hook(lambda _m, _i, o: raw.append(o[0]))
        m(input_ids=torch.tensor([rows[0]]), use_cache=False)
        hd.remove()
    assert np.allclose(h[0], raw[0][0, -1].reshape(-1).numpy(), atol=1e-6)


def test_stock_hf_subjects_are_supported_by_the_mp_script():
    import ast
    from pathlib import Path

    src = (Path(__file__).parents[1] / "scripts/adapt_introspection_mp_modal.py").read_text()
    tree = ast.parse(src)
    consts: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == "SUPPORTED":
                consts["SUPPORTED"] = ast.literal_eval(node.value)
            if isinstance(t, ast.Name) and t.id == "RESIDUAL":
                consts.setdefault("RESIDUAL", []).append(ast.literal_eval(node.value))
    assert {"kimi-k2", "glm-5.3-flash"} <= set(consts["SUPPORTED"])
    for key in ("kimi-k2", "glm-5.3-flash"):
        assert key in subjects.SUBJECTS and "adapt_introspection_mp_modal.py" in ii.EXTERNAL[key]
    # a non-plain residual must be one build_bank can describe (plan 0067 §2)
    assert set(consts["RESIDUAL"]) == {"plain_7168", "mhc_raw_flat_16384"}
    assert "mhc_raw_flat_16384" in ii.RESIDUALS
    assert subjects.get("glm-5.3-flash").n_layers == 45 and subjects.get("kimi-k2").n_layers == 61
