"""plan 0060 Phase E on main's per-subject Modal design: the wrong_bridge logP legs as token ids
(``gate.cont_jobs``), ``RemoteRunner.cont_logprobs`` in chunks over the subject's app, and the
app's ``cont_logprobs`` on one engine or fanned out over several (order kept). No GPU, no Modal
calls, no network."""

import sys
import types
from pathlib import Path

import pytest

from wsbench.adapt import gate, template

ROOT = Path(__file__).resolve().parents[1]


class _Tok:
    """a=1 b=2 c=3 d=4 x=5, "bc" merges into one token (23); ``bos`` = the specials it adds."""

    def __init__(self, bos=()):
        self.bos = list(bos)

    def __call__(self, text, add_special_tokens=False):
        ids, i = [], 0
        while i < len(text):
            if text[i : i + 2] == "bc":
                ids.append(23)
                i += 2
            else:
                ids.append(" abcdx".index(text[i]))
                i += 1
        return {"input_ids": (self.bos if add_special_tokens else []) + ids}


def test_cont_jobs_lead_is_the_render_bos_else_the_tokenizers_own(monkeypatch):
    monkeypatch.setattr(template, "bos_prefix", lambda tok: [9])  # Gemma / GLM: the render's
    assert gate.cont_jobs(_Tok(bos=[7]), ["ab"], ["c"]) == [([9, 1, 23], 2)]
    monkeypatch.setattr(template, "bos_prefix", lambda tok: [])
    # a Llama-style tokenizer that prepends its BOS itself (as RemoteRunner.encode adds it)
    assert gate.cont_jobs(_Tok(bos=[7]), ["ab"], ["c"]) == [([7, 1, 23], 2)]
    assert gate.cont_jobs(_Tok(), ["ab", "ab"], ["c", "d"]) == [([1, 23], 1), ([1, 2, 4], 2)]


class _Method:
    def __init__(self, log):
        self.log = log

    def remote(self, ids, starts):
        self.log.append(("remote", ids, starts))
        return [float(k) - 100 * len(x) for x, k in zip(ids, starts, strict=True)]

    def starmap(self, arglists):
        arglists = list(arglists)
        self.log.append(("starmap", arglists))
        return [self.remote(*a) for a in arglists]


def _remote(monkeypatch, replicas=1):
    monkeypatch.setattr(template, "bos_prefix", lambda tok: [9])
    r = object.__new__(gate.RemoteRunner)  # the app lookup is tested in test_adapt_subject_modal
    log = []
    r.tok, r.replicas = _Tok(), replicas
    r.remote = types.SimpleNamespace(cont_logprobs=_Method(log))
    return r, log


def test_remote_runner_cont_logprobs_sends_token_ids_in_chunks(monkeypatch):
    r, log = _remote(monkeypatch)
    prompts, conts = ["ab"] * 1100, ["c", "d"] * 550
    out = r.cont_logprobs(prompts, conts)
    calls = [c for c in log if c[0] == "remote"]
    assert [len(c[1]) for c in calls] == [512, 512, 76]
    assert calls[0][1][:2] == [[9, 1, 23], [9, 1, 2, 4]] and calls[0][2][:2] == [2, 3]
    assert out == [2.0 - 300, 3.0 - 400] * 550  # in input order
    r8, log8 = _remote(monkeypatch, replicas=8)
    assert r8.cont_logprobs(prompts, conts) == out
    assert log8[0][0] == "starmap" and len(log8[0][1]) == 3


# ---- scripts/adapt_modal.py (needs the modal package) -----------------------------------------


def _load_script(monkeypatch):
    pytest.importorskip("modal")
    import importlib.util

    monkeypatch.delenv("ADAPT_SUBJECT", raising=False)
    spec = importlib.util.spec_from_file_location(
        "_adapt_modal_phase_e", ROOT / "scripts/adapt_modal.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _LP:
    def __init__(self, v):
        self.logprob = v


def _fake_vllm(monkeypatch):
    vllm = types.ModuleType("vllm")
    vllm.SamplingParams = lambda **kw: kw
    inputs = types.ModuleType("vllm.inputs")
    inputs.TokensPrompt = lambda prompt_token_ids: prompt_token_ids
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.inputs", inputs)


class _LLM:
    """prompt_logprobs with log P(token t) = -t / 10."""

    def generate(self, prompts, sp, use_tqdm=False):
        assert sp == {"temperature": 0.0, "max_tokens": 1, "prompt_logprobs": 0}
        return [
            types.SimpleNamespace(prompt_logprobs=[None] + [{t: _LP(-t / 10)} for t in p[1:]])
            for p in prompts
        ]


def test_app_cont_logprobs_on_one_engine(monkeypatch):
    m = _load_script(monkeypatch)
    _fake_vllm(monkeypatch)
    assert m.RUN["cont_logprobs"] is m.run_cont_logprobs
    out = m.run_cont_logprobs(_LLM(), [[9, 1, 23], [9, 1, 2, 4]], [2, 3])
    assert out == pytest.approx([-2.3, -0.4])  # only ids[k:] (k >= 1) is summed


class _Engine:
    def __init__(self, log, k, die=False):
        self.log, self.k, self.die = log, k, die

    def __call__(self, name, args):
        self.log.append((self.k, name, args))
        if self.die:
            raise_ = self.k

            def result():
                raise _ERR(f"engine {raise_} died")

            return types.SimpleNamespace(result=result)
        out = [float(k * 1000 + len(x)) for x, k in zip(args[0], args[1], strict=True)]
        return types.SimpleNamespace(result=lambda: out)


_ERR = RuntimeError


def test_app_cont_logprobs_fans_out_in_order_and_dies_like_the_others(monkeypatch):
    global _ERR
    m = _load_script(monkeypatch)
    log = []
    ids = [[0] * (n + 1) for n in range(19)]
    starts = list(range(19))
    out = m.fan_out([_Engine(log, k) for k in range(8)], "cont_logprobs", (ids, starts))
    assert out == [float(k * 1000 + k + 1) for k in range(19)]  # prompt order, starts aligned
    assert [len(a[2][0]) for a in log] == [3, 3, 3, 3, 3, 3, 1]
    assert all(len(a[2]) == 2 and a[2][1] == starts[3 * a[0] : 3 * a[0] + len(a[2][0])]
               for a in log)  # fmt: skip
    _ERR = m.EngineDiedError
    engines = [_Engine(log, 0), _Engine(log, 1, die=True)]
    with pytest.raises(m.EngineDiedError):
        m.fan_out(engines, "cont_logprobs", (ids[:4], starts[:4]))
