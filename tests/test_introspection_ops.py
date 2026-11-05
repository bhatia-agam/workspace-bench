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
