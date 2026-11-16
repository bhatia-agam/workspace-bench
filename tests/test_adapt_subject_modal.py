"""Plan 0060 A3: per-subject Modal apps (Subject fields -> app spec), RemoteRunner sending token
ids (a render's BOS is never doubled), the glm-5.3 Subject and its pinned no-think template, and
kimi-k2 off Agam's box. No GPU, no Modal, no network (the template test skips without the
tokenizer)."""

import json
import os
import re
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

from wsbench.adapt import subjects
from wsbench.adapt.gate import Ask, RemoteRunner
from wsbench.adapt.subjects import DEFAULT_MODAL_APP, SUBJECTS, TEMPLATES, modal_spec

ROOT = Path(__file__).resolve().parents[1]
GLM53_REV = "e3b8f9f2fad29727dfa95e766c5cac18ea1414bf"
FLASH_REV = "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a"


# ---- Subject fields -> the deployed app ------------------------------------------------------


def test_default_subjects_keep_the_shared_app():
    """Every modal subject without its own fields deploys/uses today's shared H200 app."""
    shared = modal_spec(None)
    assert shared == {"app": DEFAULT_MODAL_APP, "gpu": ["H200"], "tp": 1, "replicas": 1,
                      "engines": 1, "image": "default", "volume": "adapt-hf-cache", "weights": None,
                      "engine": {}}  # fmt: skip
    for key in ("gemma-4-31b-it", "qwen3-8b", "olmo-3.1-32b", "qwen3.6-35b-a3b"):
        assert modal_spec(SUBJECTS[key]) == shared, key
    for s in SUBJECTS.values():
        json.dumps(modal_spec(s))  # baked into the image as JSON


def test_glm53_subject():
    s = SUBJECTS["glm-5.3"]
    assert (s.hf_id, s.revision, s.n_layers, s.tokenizer) == (
        "nvidia/GLM-5.3-NVFP4", GLM53_REV, 78, "glm5")  # fmt: skip
    assert s.backend == "modal" and s.tokenizer_dir is None and not s.trust_remote_code
    assert Path(s.chat_template) == TEMPLATES / "glm53_nvfp4_nothink.jinja"
    assert Path(s.chat_template).is_file()
    spec = modal_spec(s)
    assert spec["app"] == "adapt-glm-5.3"
    assert spec["gpu"] == ["B300:8", "B200:8", "H200:8"] and spec["tp"] == 8
    assert (spec["image"], spec["volume"], spec["weights"]) == (
        "glm53", "glm53-weights", "hf/nvidia__GLM-5.3-NVFP4")  # fmt: skip
    assert spec["engine"]["kernel_config"] == {"moe_backend": "marlin"}
    assert spec["engine"]["kv_cache_dtype"] == "fp8"


def test_kimi_needs_nothing_from_agams_box():
    s = SUBJECTS["kimi-k2"]
    assert s.tokenizer_dir is None and s.chat_template is None and s.trust_remote_code
    assert s.revision == "ac6c49f04883bd0a0598b790693a72061c676629"
    assert s.modal_app == "adapt-kimi-k2" and s.modal_gpu == ("B300:8",) and s.modal_tp == 8
    assert dict(s.modal_engine)["trust_remote_code"] is True
    # plan 0089: the pinned snapshot on its own volume, as kimi-k3 (no ~1 TB hub download)
    assert (s.modal_volume, s.modal_weights) == (
        "kimi-k2", "hf/hub/models--moonshotai--Kimi-K2-Instruct-0905/snapshots/"
        "ac6c49f04883bd0a0598b790693a72061c676629")  # fmt: skip
    for key in ("kimi-k2", "glm-5.3", "glm-5.3-flash"):
        assert "/workspace/agam" not in repr(SUBJECTS[key]), key


def test_glm53_flash_is_built_here():
    """plan 0089: GLM-5.3-Flash on its own adapt app (vLLM, TP4), tokenizer from the hub at the
    pinned revision, the pinned thinking-off template (the two edits of GLM-5.3's)."""
    s = SUBJECTS["glm-5.3-flash"]
    assert (s.hf_id, s.revision, s.n_layers, s.tokenizer) == (
        "zai-org/GLM-5.3-Flash", FLASH_REV, 45, "glm5")  # fmt: skip
    assert s.backend == "modal" and s.modal_built and s.tokenizer_dir is None
    assert Path(s.chat_template) == TEMPLATES / "glm53_flash_nothink.jinja"
    text = Path(s.chat_template).read_text()
    assert "<|assistant|>{{- '<think></think>' -}}" in text
    assert "in ['low', 'high'] else 'low' -%}" in text and "else 'max'" not in text
    spec = modal_spec(s)
    assert spec["app"] == "adapt-glm-5.3-flash"
    assert spec["gpu"] == ["B200:4", "H200:4"] and spec["tp"] == 4
    assert (spec["image"], spec["volume"]) == ("default", "glm53-flash")
    assert spec["weights"].endswith("/eb9eb208eb0d988989d07a6a12d0fdeb5f52574a")
    assert spec["engine"] == {"language_model_only": True}
    # plan 0089: the big subjects never scale past one container (a concurrent call queues)
    assert spec["max_containers"] == 1 and modal_spec(SUBJECTS["kimi-k2"])["max_containers"] == 1


def test_subject_for_finds_the_registered_subject():
    assert subjects.subject_for("nvidia/GLM-5.3-NVFP4").key == "glm-5.3"
    assert subjects.subject_for("nvidia/GLM-5.3-NVFP4", "deadbeef") is None
    assert subjects.subject_for("no/such-model") is None


def test_tokenizer_applies_the_chat_template_without_a_tokenizer_dir(monkeypatch):
    """author.tokenizer: GLM-5.3 loads from the hub at its revision and still gets its template;
    Kimi's remote-code tokenizer is trusted."""
    calls = []

    class _Auto:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append((name, kw))
            return types.SimpleNamespace(chat_template="UPSTREAM")

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoTokenizer=_Auto))
    from wsbench.adapt.author import tokenizer

    tok = tokenizer("glm-5.3")
    assert calls[-1] == ("nvidia/GLM-5.3-NVFP4",
                         {"revision": GLM53_REV, "trust_remote_code": False})  # fmt: skip
    assert tok.chat_template == (TEMPLATES / "glm53_nvfp4_nothink.jinja").read_text()
    tokenizer("kimi-k2")
    assert calls[-1][1]["trust_remote_code"] is True
    assert tokenizer("qwen3-8b").chat_template == "UPSTREAM"  # no template: the tokenizer's own


# ---- RemoteRunner: token ids, the subject's app, fan-out -------------------------------------


class _Tok:
    """Specials ``<bos>`` ``<u>`` ``<a>`` plus one id per other character; ``auto_bos`` = the
    tokenizer prepends <bos> itself when asked to add specials (Llama-style)."""

    SPECIAL: ClassVar[dict[str, int]] = {"<bos>": 0, "<u>": 1, "<a>": 2}

    def __init__(self, auto_bos=False):
        self.auto_bos = auto_bos

    def __call__(self, text, add_special_tokens=True):
        ids = [self.SPECIAL.get(t, 100 + ord(t[0])) for t in re.findall(r"<bos>|<u>|<a>|.", text)]
        return {"input_ids": ([0] if add_special_tokens and self.auto_bos else []) + ids}

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True, **_):
        return "<bos>" + "".join(f"<u>{m['content']}" for m in msgs) + "<a>"


class _Method:
    def __init__(self, log, name):
        self.log, self.name = log, name

    def remote(self, *args):
        self.log.append((self.name, "remote", args))
        return self._answer(args)

    def starmap(self, arglists):
        arglists = list(arglists)
        self.log.append((self.name, "starmap", arglists))
        return [self._answer(a) for a in arglists]

    def _answer(self, args):
        if self.name == "sample":
            return [(f"g{len(p)}", ["s"] * args[2]) for p in args[0]]
        return [{"text": "t", "ids": list(p)} for p in args[0]]


def _fake_modal(monkeypatch, log):
    class _Cls:
        @staticmethod
        def from_name(app, name):
            log.append(("from_name", app, name))

            def bind(**params):
                log.append(("params", params))
                return types.SimpleNamespace(sample=_Method(log, "sample"),
                                             generate=_Method(log, "generate"))  # fmt: skip

            return bind

    monkeypatch.setitem(sys.modules, "modal", types.SimpleNamespace(Cls=_Cls))


def _runner(monkeypatch, tok, hf_id="nvidia/GLM-5.3-NVFP4", **kw):
    log, loads = [], []
    _fake_modal(monkeypatch, log)

    def load(*a):
        loads.append(a)
        return tok

    monkeypatch.setattr(subjects, "load_tokenizer", load)
    r = RemoteRunner(hf_id, revision=kw.pop("revision", GLM53_REV), **kw)
    return r, log, loads


def test_remote_runner_calls_the_subjects_app_with_token_ids(monkeypatch):
    s = SUBJECTS["glm-5.3"]
    r, log, loads = _runner(monkeypatch, _Tok(), modal_app=s.modal_app,
                            chat_template=s.chat_template)  # fmt: skip
    assert log[:2] == [("from_name", "adapt-glm-5.3", "SubjectLLM"),
                       ("params", {"model_id": s.hf_id, "revision": GLM53_REV,
                                   "max_model_len": 4096})]  # fmt: skip
    assert loads == [(s.hf_id, GLM53_REV, None, s.chat_template, False)]
    asks = [Ask("i", "surface", ("x",), messages=({"role": "user", "content": "hi"},),
                prefill="A", max_tokens=5)]  # fmt: skip
    out = r.sample(asks, draws=3, temperature=0.7, top_p=0.95)
    name, how, args = log[-1]
    assert (name, how) == ("sample", "remote")
    ids = args[0][0]
    assert ids == [0, 1, 100 + ord("h"), 100 + ord("i"), 2, 100 + ord("A")]  # one <bos>
    assert args[1:] == ([5], 3, 0.7, 0.95, 0)
    assert out == [("g6", ["s"] * 3)]


def test_remote_runner_never_doubles_an_auto_bos(monkeypatch):
    """A tokenizer that prepends <bos> itself: added once to a raw prompt that lacks it (as the
    engine's own text tokenization did), never to a render that already starts with it."""
    r, log, _ = _runner(monkeypatch, _Tok(auto_bos=True))
    r._bos = ""  # bos_prefix() is [] for such a tokenizer
    raw = Ask("i", "surface:plain", ("x",), prompt="ab", max_tokens=4)
    chat = Ask("j", "surface", ("x",), messages=({"role": "user", "content": "ab"},), max_tokens=4)
    r.sample([raw, chat], draws=1, temperature=0.7)
    sent = log[-1][2][0]
    assert sent[0] == [0, 100 + ord("a"), 100 + ord("b")]
    assert sent[1][:2] == [0, 1] and sent[1].count(0) == 1
    # generate: text prompts are encoded the same way; token-id prompts pass through untouched
    out = r.generate(["<bos>ab", [7, 8]], temperature=0.0, max_tokens=3, seed=5)
    assert log[-1][2][0] == [[0, 100 + ord("a"), 100 + ord("b")], [7, 8]]
    assert out[1]["ids"] == [7, 8]


def test_remote_runner_chunks_and_fans_out(monkeypatch):
    """512-prompt chunks with seed + chunk start, in order; a subject with replicas > 1 maps the
    chunks over its containers (same arguments, same order)."""
    asks = [Ask(f"i{k}", "surface", ("x",), prompt="p", max_tokens=2) for k in range(1100)]
    r, log, _ = _runner(monkeypatch, _Tok(), seed=10)
    r._bos = ""
    out = r.sample(asks, draws=2, temperature=0.7)
    calls = [c for c in log if c[0] == "sample"]
    assert [c[1] for c in calls] == ["remote"] * 3
    assert [len(c[2][0]) for c in calls] == [512, 512, 76]
    assert [c[2][5] for c in calls] == [10, 522, 1034]
    assert len(out) == 1100
    serial = [c[2] for c in calls]

    r2, log2, _ = _runner(monkeypatch, _Tok(), seed=10, replicas=8)
    r2._bos = ""
    assert r2.sample(asks, draws=2, temperature=0.7) == out
    fan = [c for c in log2 if c[0] == "sample"]
    assert len(fan) == 1 and fan[0][1] == "starmap" and fan[0][2] == serial


def test_remote_runner_takes_registered_settings(monkeypatch):
    """Callers (run._runner) pass only the old kwargs; trust_remote_code and replicas come from
    the registered Subject."""
    monkeypatch.setitem(SUBJECTS, "fake-dp", subjects.Subject(
        "fake-dp", "org/fake", "Fake", 4, "x", "r1", backend="modal", modal_replicas=8,
        trust_remote_code=True))  # fmt: skip
    r, _, loads = _runner(monkeypatch, _Tok(), hf_id="org/fake", revision="r1")
    assert r.replicas == 8 and loads[0][-1] is True
    monkeypatch.setitem(SUBJECTS, "fake-plain", subjects.Subject(
        "fake-plain", "org/plain", "Plain", 4, "x", "r2", backend="modal"))  # fmt: skip
    r, _, loads = _runner(monkeypatch, _Tok(), hf_id="org/plain", revision="r2")
    assert r.replicas == 1 and loads[0][-1] is False
    assert r.CHUNK == 512  # RemoteRunner.CHUNK unless the Subject sets modal_chunk


def test_remote_runner_takes_the_subjects_chunk_and_keeps_each_prompts_seed(monkeypatch):
    """A padded subject's bigger chunk (V4-Flash: 9,600) makes fewer, larger calls; every
    prompt keeps the seed it gets with 512-prompt chunks (seed + its global index)."""
    assert SUBJECTS["deepseek-v4-flash"].modal_chunk == 9600
    monkeypatch.setitem(SUBJECTS, "fake-big", subjects.Subject(
        "fake-big", "org/big", "Big", 4, "x", "r3", backend="modal", modal_chunk=1000))  # fmt: skip
    asks = [Ask(f"i{k}", "surface", ("x",), prompt="p", max_tokens=2) for k in range(1100)]
    r, log, _ = _runner(monkeypatch, _Tok(), hf_id="org/big", revision="r3", seed=10)
    r._bos = ""
    assert r.CHUNK == 1000
    r.sample(asks, draws=2, temperature=0.7)
    calls = [c for c in log if c[0] == "sample"]
    assert [len(c[2][0]) for c in calls] == [1000, 100]
    assert [c[2][5] for c in calls] == [10, 1010]


def test_remote_runner_refuses_apps_adapt_modal_does_not_build(monkeypatch):
    """Token ids only reach apps built by scripts/adapt_modal.py: an unregistered model, or a
    subject on an external text-only app (``modal_built=False``; glm-5.3-flash was one until
    plan 0089), is refused before any call."""
    with pytest.raises(SystemExit, match="not a registered Subject"):
        _runner(monkeypatch, _Tok(), hf_id="org/unregistered", revision=None)
    ext = subjects.Subject("fake-ext", "org/ext", "Ext", 4, "x", "r9", backend="modal",
                           modal_app="adapt-mp-external", modal_built=False)  # fmt: skip
    monkeypatch.setitem(SUBJECTS, ext.key, ext)
    with pytest.raises(SystemExit, match=re.escape("adapt-mp-external")):
        _runner(monkeypatch, _Tok(), hf_id=ext.hf_id, revision=ext.revision,
                modal_app=ext.modal_app)  # fmt: skip
    # plan 0089: every registered subject is now served by an app adapt_modal.py builds
    assert all(s.modal_built for k, s in SUBJECTS.items() if k != ext.key)


# ---- scripts/adapt_modal.py builds the subject's app (needs the modal package) ---------------


def _load_script(monkeypatch, key):
    pytest.importorskip("modal")
    import importlib.util

    if key:
        monkeypatch.setenv("ADAPT_SUBJECT", key)
    else:
        monkeypatch.delenv("ADAPT_SUBJECT", raising=False)
    path = ROOT / "scripts/adapt_modal.py"
    spec = importlib.util.spec_from_file_location(f"_adapt_modal_{key}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_adapt_modal_script_per_subject(monkeypatch):
    m = _load_script(monkeypatch, "")
    assert modal_spec(None) == m.SPEC and m.app.name == DEFAULT_MODAL_APP
    kw = m.engine_kwargs(m.SPEC, "Qwen/Qwen3-8B", "abc", 4096)
    assert kw == {"model": "Qwen/Qwen3-8B", "revision": "abc", "max_model_len": 4096,
                  "gpu_memory_utilization": 0.90, "seed": 0,
                  "limit_mm_per_prompt": {"image": 0, "video": 0},
                  "tensor_parallel_size": 1}  # fmt: skip
    g = _load_script(monkeypatch, "glm-5.3")
    assert g.app.name == "adapt-glm-5.3" and modal_spec(SUBJECTS["glm-5.3"]) == g.SPEC
    monkeypatch.setattr(g, "localize", lambda p: "/local/" + os.path.basename(p))
    monkeypatch.setattr(g, "quant_override_w4a16", lambda p: 1)
    kw = g.engine_kwargs(g.SPEC, "nvidia/GLM-5.3-NVFP4", GLM53_REV, 4096)
    assert kw["model"] == "/local/nvidia__GLM-5.3-NVFP4" and kw["revision"] is None
    assert kw["tensor_parallel_size"] == 8 and kw["kernel_config"] == {"moe_backend": "marlin"}


def test_deploy_builds_glm53_flash(monkeypatch):
    """plan 0089: glm-5.3-flash deploys (it was refused as Agam's external app before); the
    refusal path is unreachable for registered subjects now (all modal_built)."""
    f = _load_script(monkeypatch, "glm-5.3-flash")
    assert f.app.name == "adapt-glm-5.3-flash" and modal_spec(SUBJECTS["glm-5.3-flash"]) == f.SPEC
    kw = f.engine_kwargs(f.SPEC, "zai-org/GLM-5.3-Flash", "eb9eb208", 8192)
    assert kw["model"] == "/hf/" + f.SPEC["weights"] and kw["revision"] is None
    assert kw["tensor_parallel_size"] == 4 and kw["language_model_only"] is True
    k = _load_script(monkeypatch, "kimi-k2")
    kw = k.engine_kwargs(k.SPEC, "moonshotai/Kimi-K2-Instruct-0905", "ac6c49f0", 8192)
    assert kw["model"] == "/hf/" + k.SPEC["weights"] and kw["tensor_parallel_size"] == 8


def test_deploy_refuses_an_external_app(monkeypatch, tmp_path):
    """The deploy script's ``modal_built=False`` refusal, kept covered after plan 0089 left no
    registered external subject: the script reads subjects.py by path, so it runs from a temp
    tree whose subjects.py registers one unbuilt subject."""
    pytest.importorskip("modal")
    import importlib.util
    import shutil

    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/adapt_modal.py", tmp_path / "scripts/adapt_modal.py")
    adapt = tmp_path / "src/wsbench/adapt"
    adapt.mkdir(parents=True)
    src = (ROOT / "src/wsbench/adapt/subjects.py").read_text()
    (adapt / "subjects.py").write_text(src + (
        "\nSUBJECTS['fake-ext'] = Subject('fake-ext', 'org/ext', 'Ext', 4, 'x', 'r9', "
        "backend='modal', modal_app='adapt-mp-external', modal_built=False)\n"))  # fmt: skip
    monkeypatch.setenv("ADAPT_SUBJECT", "fake-ext")
    spec = importlib.util.spec_from_file_location(
        "_adapt_modal_ext", tmp_path / "scripts/adapt_modal.py"
    )
    mod = importlib.util.module_from_spec(spec)
    with pytest.raises(SystemExit, match="modal_built=False"):
        spec.loader.exec_module(mod)


class _FakeEngine:
    """An engine process stand-in: records its slice, answers through RUN-like logic."""

    def __init__(self, log, k):
        self.log, self.k = log, k

    def __call__(self, name, args):
        self.log.append((self.k, name, args))
        if name == "sample":
            out = [(f"p{p}@{args[5] + i}", []) for i, p in enumerate(args[0])]
        else:
            out = [{"text": f"p{p}@{args[3]}", "ids": []} for p in args[0]]
        return types.SimpleNamespace(result=lambda: out)


def test_engines_split_a_call_and_keep_each_prompts_seed(monkeypatch):
    """dsv4 layout: one container, 8 TP=1 engines. A call is split into contiguous slices; each
    prompt gets the seed it would get on one engine; results come back in prompt order."""
    m = _load_script(monkeypatch, "")
    assert m.split(10, 8) == [(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)]
    assert m.split(16, 8)[-1] == (14, 16) and m.split(0, 8) == [] and m.split(3, 1) == [(0, 3)]
    log = []
    engines = [_FakeEngine(log, k) for k in range(8)]
    prompts = list(range(19))
    out = m.fan_out(engines, "sample", (prompts, [5] * 19, 2, 0.7, 0.95, 100))
    assert [o[0] for o in out] == [f"p{p}@{100 + p}" for p in prompts]
    assert [len(a[2][0]) for a in log] == [3, 3, 3, 3, 3, 3, 1]  # ceil(19/8) per engine
    assert all(a[2][1] == [5] * len(a[2][0]) and a[2][2:5] == (2, 0.7, 0.95) for a in log)
    log.clear()
    out = m.fan_out(engines, "generate", (prompts, 0.0, 7, 42, 1.0, [1]))
    assert [o["text"] for o in out] == [f"p{p}@42" for p in prompts]
    assert all(a[2][1:] == (0.0, 7, 42, 1.0, [1]) for a in log)


def _fake_make(kwargs):
    """A CPU stand-in for vllm.LLM in a real spawned engine process (module level: pickled);
    ``fail_gpu`` = the engine on that GPU fails to start."""
    if os.environ["CUDA_VISIBLE_DEVICES"] == str(kwargs.get("fail_gpu")):
        raise RuntimeError("engine load failed")
    return {"pid": os.getpid(), **kwargs}


def _fake_run(llm, name, args):
    if "boom" in args[0]:
        raise ValueError("bad request")
    if "die" in args[0]:
        os._exit(3)
    return [f"{name}:{p}" for p in args[0]]


def test_real_engine_processes_drain_errors_and_never_hang(monkeypatch):
    """The real _Engine / _engine_worker (spawned, non-daemonic) with a fake LLM: a normal call;
    an engine raising -> the call fails after every reply is drained, and the next call gets its
    own answers (no stale replies); a dead engine raises instead of hanging."""
    pytest.importorskip("modal")
    monkeypatch.delenv("ADAPT_SUBJECT", raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))  # importable by name in the children
    import adapt_modal as m

    engines = [m._Engine(k, {"k": k}, _fake_make, _fake_run) for k in range(3)]
    try:
        for e in engines:
            e.wait_ready()
            assert not e.proc.daemon  # vLLM's EngineCore is a child of the worker
        gen = ("generate", 0.0, 4, 1, 1.0, None)

        def call(prompts):
            return m.fan_out(engines, gen[0], (prompts, *gen[1:]))

        p6 = ["a", "b", "c", "d", "e", "f"]
        assert call(p6) == [f"generate:{p}" for p in p6]
        # a per-request error goes to the caller, not EngineDiedError (the container serves on)
        with pytest.raises(RuntimeError, match="engine 2: engine error: ValueError") as err:
            call(["a", "b", "c", "d", "boom", "f"])
        assert not isinstance(err.value, m.EngineDiedError)
        assert all(e.proc.is_alive() for e in engines)
        p6b = ["u", "v", "w", "x", "y", "z"]
        assert call(p6b) == [f"generate:{p}" for p in p6b]  # nothing stale left in the pipes
        with pytest.raises(m.EngineDiedError, match="engine 1: engine process died"):
            call(["a", "b", "die", "d", "e", "f"])
        assert all(e.proc.is_alive() for k, e in enumerate(engines) if k != 1)
        engines[0].proc.kill()
        engines[0].proc.join(30)
        with pytest.raises(m.EngineDiedError, match="engine 0: engine process"):
            call(p6)
    finally:
        for e in engines:
            e.close(timeout=30)
    assert not any(e.proc.is_alive() for e in engines)


def test_engine_startup_failure_stops_every_started_engine(monkeypatch):
    """Engine 1 of 3 fails to load: start_engines raises (no hang), every started engine is in
    the list and has exited, so nothing blocks multiprocessing's exit join."""
    pytest.importorskip("modal")
    monkeypatch.delenv("ADAPT_SUBJECT", raising=False)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import adapt_modal as m

    engines: list = []
    with pytest.raises(m.EngineDiedError):
        m.start_engines(3, {"fail_gpu": 1}, engines, _fake_make, _fake_run)
    assert len(engines) == 3
    assert not any(e.proc.is_alive() for e in engines)
    assert all(e in m._STARTED for e in engines)  # the atexit backstop knows them


def test_quant_override_marks_nvfp4_layers_w4a16(monkeypatch, tmp_path):
    m = _load_script(monkeypatch, "")
    q = {"quantization": {"quantized_layers": {"a": {"quant_algo": "NVFP4"},
                                               "b": {"quant_algo": "FP8"}}}}  # fmt: skip
    (tmp_path / "hf_quant_config.json").write_text(json.dumps(q))
    assert m.quant_override_w4a16(str(tmp_path)) == 1
    got = json.loads((tmp_path / "hf_quant_config.json").read_text())
    assert got["quantization"]["quantized_layers"] == {"a": {"quant_algo": "W4A16_NVFP4"},
                                                       "b": {"quant_algo": "FP8"}}  # fmt: skip
    assert m.quant_override_w4a16(str(tmp_path)) == 0


# ---- the pinned GLM-5.3 template against the glm53 lens work's render ------------------------


def _glm53_tokenizer():
    """The hub tokenizer at the pinned revision (tokenizer files only; ``WSB_GLM53_TOKENIZER``
    = a local dir with them); skip without transformers or the files."""
    transformers = pytest.importorskip("transformers")
    src = os.environ.get("WSB_GLM53_TOKENIZER")
    try:
        if src:
            return transformers.AutoTokenizer.from_pretrained(src)
        return transformers.AutoTokenizer.from_pretrained(
            "nvidia/GLM-5.3-NVFP4", revision=GLM53_REV
        )
    except Exception as e:  # offline / no hub access
        pytest.skip(f"GLM-5.3 tokenizer unavailable: {e!r}")


def _reference_prompt_ids(tok, user: str) -> list[int]:
    """global-workspace src/global_workspace/glm53_aff/template.py, verbatim logic:
    render_user_turn (upstream template, reasoning_effort="low", + "</think>") -> prompt_ids."""
    s = tok.apply_chat_template([{"role": "user", "content": user}], tokenize=False,
                                add_generation_prompt=True, reasoning_effort="low")  # fmt: skip
    assert s.endswith("<think>"), s[-40:]
    ids = tok.encode(s + "</think>", add_special_tokens=False)
    assert tuple(ids[:2]) == (154822, 154824), ids[:4]  # [gMASK]<sop>
    return ids


USERS = [
    "hi",
    "What is 17 + 25?\nAnswer with the number only.",
    " leading space",
    "Was ist die Hauptstadt von Frankreich?",
    "\u65e5\u672c\u306e\u9996\u90fd\u306f\uff1f",  # Japanese, full-width question mark
    "<think>not a tag</think>",
]


def test_glm53_template_matches_the_reference_render_token_for_token():
    from wsbench.adapt.template import bos_prefix, check, markers

    ref = _glm53_tokenizer()
    upstream = ref.chat_template
    tok = _glm53_tokenizer()
    tok.chat_template = (TEMPLATES / "glm53_nvfp4_nothink.jinja").read_text()
    for u in USERS:
        ref.chat_template = upstream
        want = _reference_prompt_ids(ref, u)
        msg = [{"role": "user", "content": u}]
        got = tok.apply_chat_template(msg, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)  # fmt: skip
        got = list(got["input_ids"] if hasattr(got, "keys") else got)
        assert got == want, u
        text = tok.apply_chat_template(msg, tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)  # fmt: skip
        assert tok(text, add_special_tokens=False)["input_ids"] == want  # RemoteRunner.encode
    # the system line: the same as the upstream template at reasoning_effort=low (+ </think>)
    msgs = [{"role": "system", "content": "Be terse."}, {"role": "user", "content": "hi"}]
    up = ref.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                 reasoning_effort="low")  # fmt: skip
    assert tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False) == up + "</think>"  # fmt: skip
    # the adapt pipeline's step-0 checks pass and find GLM's markers and [gMASK]<sop>
    assert check(tok) == []
    m = markers(tok)
    assert (m["turn_start"], m["turn_end"]) == ("<|user|>", "<|assistant|>")
    assert "".join(m["gen_tail"]) == "<think></think>"
    assert bos_prefix(tok) in ([], [154822, 154824])  # [] only if the tokenizer adds them itself


# ---- kimi-k2 from the hub (tiktoken remote code at the pinned revision) ----------------------


def test_kimi_hub_tokenizer_round_trips_a_render():
    """The pinned hub tokenizer (no /workspace/agam dir): the render's text re-encodes to the
    template's own ids (what RemoteRunner sends), the step-0 checks pass, and the official
    template's default system turn opens every render."""
    pytest.importorskip("transformers")
    pytest.importorskip("tiktoken")
    from wsbench.adapt.author import tokenizer
    from wsbench.adapt.template import bos_prefix, check, markers

    try:
        tok = tokenizer("kimi-k2")
    except Exception as e:  # offline / no hub access
        pytest.skip(f"Kimi-K2 tokenizer unavailable: {e!r}")
    for u in USERS:
        msg = [{"role": "user", "content": u}]
        ids = tok.apply_chat_template(msg, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)  # fmt: skip
        ids = list(ids["input_ids"] if hasattr(ids, "keys") else ids)
        text = tok.apply_chat_template(msg, tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)  # fmt: skip
        assert list(tok(text, add_special_tokens=False)["input_ids"]) == ids, u
        assert tok.decode(ids, skip_special_tokens=False) == text
        assert text.startswith("<|im_system|>system<|im_middle|>You are Kimi")
    assert check(tok) == []
    m = markers(tok)
    assert (m["turn_start"], m["turn_end"]) == ("<|im_user|>", "<|im_end|>")
    assert bos_prefix(tok) == []


# ---- glm-5.3-flash from the hub (plan 0089) ----------------------------------------------------


def test_glm53_flash_template_is_upstream_at_low_effort_with_think_closed():
    """The pinned Flash template renders exactly the upstream one at reasoning_effort="low" plus
    "</think>" (token for token, with and without a system turn), and the step-0 checks pass."""
    transformers = pytest.importorskip("transformers")
    from wsbench.adapt.template import bos_prefix, check, markers

    try:
        load = transformers.AutoTokenizer.from_pretrained
        ref = load("zai-org/GLM-5.3-Flash", revision=FLASH_REV)
        tok = load("zai-org/GLM-5.3-Flash", revision=FLASH_REV)
    except Exception as e:  # offline / no hub access
        pytest.skip(f"GLM-5.3-Flash tokenizer unavailable: {e!r}")
    tok.chat_template = (TEMPLATES / "glm53_flash_nothink.jinja").read_text()
    for u in USERS:
        for msgs in (
            [{"role": "user", "content": u}],
            [{"role": "system", "content": "Be terse."}, {"role": "user", "content": u}],
        ):
            up = ref.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                         reasoning_effort="low")  # fmt: skip
            assert up.endswith("<think>"), up[-40:]
            got = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                          enable_thinking=False)  # fmt: skip
            assert got == up + "</think>", u
            ids = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                          enable_thinking=False)  # fmt: skip
            ids = list(ids["input_ids"] if hasattr(ids, "keys") else ids)
            assert tok(got, add_special_tokens=False)["input_ids"] == ids  # RemoteRunner.encode
    assert check(tok) == []
    m = markers(tok)
    assert (m["turn_start"], m["turn_end"]) == ("<|user|>", "<|assistant|>")
    assert "".join(m["gen_tail"]) == "<think></think>"
    assert bos_prefix(tok) in ([], [154822, 154824])


def _fake_vllm(monkeypatch):
    """Minimal ``vllm`` stand-ins: SamplingParams / TokensPrompt as plain records."""

    class SamplingParams(types.SimpleNamespace):
        def __init__(self, **kw):
            kw.setdefault("max_tokens", 16)
            super().__init__(**kw)

    vllm = types.ModuleType("vllm")
    vllm.SamplingParams = SamplingParams
    inputs = types.ModuleType("vllm.inputs")
    inputs.TokensPrompt = lambda prompt_token_ids: {"ids": prompt_token_ids}
    vllm.inputs = inputs
    monkeypatch.setitem(sys.modules, "vllm", vllm)
    monkeypatch.setitem(sys.modules, "vllm.inputs", inputs)


class _PadLLM:
    """Records each generate call; answers request i with text ``t<i>`` (or ``garbage``)."""

    def __init__(self, garbage=False):
        self.calls, self.garbage = [], garbage

    def generate(self, ins, sps, use_tqdm=False):
        sps = sps if isinstance(sps, list) else [sps] * len(ins)
        self.calls.append((list(ins), sps))
        out = []
        for i, (p, sp) in enumerate(zip(ins, sps, strict=True)):
            if self.garbage:
                text = "- 1. 2. 3."
            elif p["ids"][-1] == 128822:
                text = " Steven Spielberg"
            elif p["ids"][-1] == 344:
                text = " Paris."
            else:
                text = f"t{p['ids'][0]}"
            n = getattr(sp, "n", 1) or 1
            out.append(types.SimpleNamespace(
                outputs=[types.SimpleNamespace(text=text, token_ids=[i])] * n))  # fmt: skip
        return out


def test_v4_flash_pads_every_engine_call_and_checks_its_canary(monkeypatch):
    """DeepSeek-V4-Flash's TP=1 engines: every generate() is wrapped in 300 throwaway requests at
    the head and the tail (greedy, to the call's longest max_tokens, EOS ignored), only the real
    outputs come back in order; the canary refuses a broken engine. V4-Pro's spec has no pad."""
    assert "pad" not in modal_spec(SUBJECTS["deepseek-v4-pro"])
    assert modal_spec(SUBJECTS["deepseek-v4-flash"])["pad"] == 300
    assert modal_spec(SUBJECTS["deepseek-v4-flash"])["max_containers"] == 4
    # plan 0089 caps kimi-k2 / glm-5.3-flash at 1 (tested in test_glm53_flash_is_built_here)
    capped = {"deepseek-v4-flash", "kimi-k2", "glm-5.3-flash"}
    assert all("max_containers" not in modal_spec(s) for k, s in SUBJECTS.items()
               if k not in capped)  # fmt: skip
    _fake_vllm(monkeypatch)
    m = _load_script(monkeypatch, "deepseek-v4-flash")
    assert m.PAD == 300 and m.SPEC["engines"] == 8
    assert m._cls_options["max_containers"] == 4
    llm = _PadLLM()
    prompts = [[7], [8], [9]]
    out = m.run_sample(llm, prompts, [5, 9, 3], 2, 0.7, 0.95, 100)
    assert [g for g, _ in out] == ["t7", "t8", "t9"] and [len(s) for _, s in out] == [2, 2, 2]
    assert len(llm.calls) == 2
    for ins, sps in llm.calls:
        assert len(ins) == 603 and [p["ids"] for p in ins[300:303]] == prompts
        pads = sps[:300] + sps[303:]
        assert all(sp.max_tokens == 9 and sp.min_tokens == 9 and sp.ignore_eos for sp in pads)
        assert all(sp.temperature == 0.0 for sp in pads)
    assert [sp.seed for sp in llm.calls[1][1][300:303]] == [100, 101, 102]
    gen = m.run_generate(_PadLLM(), [[4]], 0.0, 7, 1, 1.0, None)
    assert [g["text"] for g in gen] == ["t4"]
    assert m.canary(_PadLLM()) == [" Steven Spielberg", " Paris."]
    with pytest.raises(RuntimeError, match="canary failed"):
        m.canary(_PadLLM(garbage=True))
    plain = _load_script(monkeypatch, "deepseek-v4-pro")
    llm = _PadLLM()
    assert plain.PAD == 0 and [
        g for g, _ in plain.run_sample(llm, prompts, [5] * 3, 1, 0.7, 0.95, 0)
    ] == ["t7", "t8", "t9"]
    assert all(len(ins) == 3 for ins, _ in llm.calls)


def test_spawned_engine_worker_reads_the_baked_spec(monkeypatch):
    """An engine worker spawned in the container re-imports the script where modal.is_local()
    is True and the repo is absent: the image's ADAPT_MODAL_SPEC must win over the local path
    (the V4-Flash 8-engine container crash-looped on /src/wsbench/adapt/subjects.py otherwise)."""
    baked = modal_spec(SUBJECTS["deepseek-v4-flash"])
    monkeypatch.setenv("ADAPT_MODAL_SPEC", json.dumps(baked, sort_keys=True))
    m = _load_script(
        monkeypatch, ""
    )  # ADAPT_SUBJECT unset: the local path would give the shared app
    assert baked == m.SPEC and m.PAD == 300 and m.app.name == "adapt-v4-flash"
