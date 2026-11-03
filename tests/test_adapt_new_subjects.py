"""Plan 0060: the DeepSeek-V4-Pro, Kimi-K3 and Muse-Spark-Open subjects.

- Registry entries: pins, layer counts, no J-lens (``read_band=()``), the Modal app each deploys.
- DeepSeek-V4-Pro renders exactly as V4-Flash: its own ``encoding_dsv4.encode_messages(chat)``
  equals the pinned template (Pro's encoder differs from Flash's only in thinking mode).
- Kimi-K3: the per-subject thinking kwarg (``Subject.thinking_kwarg`` -> ``load_tokenizer``
  renames ``enable_thinking`` to ``thinking``), ``template.markers`` / ``check`` on its XTML
  render, carry's re-stamp, and ``RemoteRunner`` cutting replies at ``reply_end``.
- Muse-Spark-Open: the pinned no-think template (reasoning_effort low, pinned date, generation
  prompt ``<|start|>assistant to=user<|message|>``) and its markers / stops.

"real" tests read the pinned tokenizer files from the local HF cache (no weights, no network)
and skip when they are absent; the rest run on fakes."""

import importlib.util
import json
import sys
import types
from functools import cache
from pathlib import Path

import pytest
from test_adapt_v4 import SYNTHETIC, FakeTok, _jinja_render, _msgs, bank_renders, ref_encode

from wsbench.adapt import subjects, template
from wsbench.adapt.subjects import SUBJECTS, TEMPLATES, modal_spec, remap_layer

ROOT = Path(__file__).resolve().parents[1]
PRO, K3, MUSE = SUBJECTS["deepseek-v4-pro"], SUBJECTS["kimi-k3"], SUBJECTS["muse-spark-open"]
PRO_REV = "72e1d3230f6c080a530b0a1d46f8eb4602340597"
K3_REV = "f831ab66814297da540d832a5235f8e904f29d06"
MUSE_REV = "4239e4db19376904f2e82c167e78f70abb5455fe"


# ---------------------------------------------------------------- the registry


def test_registry_entries():
    assert (PRO.hf_id, PRO.revision, PRO.n_layers, PRO.tokenizer) == (
        "deepseek-ai/DeepSeek-V4-Pro-0813", PRO_REV, 61, "dsv4")  # fmt: skip
    assert (K3.hf_id, K3.revision, K3.n_layers, K3.tokenizer) == (
        "moonshotai/Kimi-K3", K3_REV, 93, "kimi3")  # fmt: skip
    assert (MUSE.hf_id, MUSE.revision, MUSE.n_layers, MUSE.tokenizer) == (
        "meta-models/Muse-Spark-Open-816B-A42B-NVFP4", MUSE_REV, 62, "muse")  # fmt: skip
    for s in (PRO, K3, MUSE):
        assert s.backend == "modal" and s.modal_built and s.tokenizer_dir is None
        assert s.read_band == ()  # no J-lens yet: depth remap, no band snap
        assert remap_layer(63, s.n_layers, s.read_band) == s.n_layers - 1
        assert subjects.subject_for(s.hf_id, s.revision) is s
        json.dumps(modal_spec(s))
    # thinking switch and reply end: only Kimi-K3 differs from the default
    assert K3.thinking_kwarg == "thinking" and K3.reply_end == "<|close|>"
    others = [s for k, s in SUBJECTS.items() if k != K3.key]
    assert all(s.thinking_kwarg == "enable_thinking" and s.reply_end is None for s in others)


def test_registry_modal_specs():
    assert modal_spec(PRO) == {
        "app": "adapt-v4-pro", "gpu": ["B300:8"], "tp": 8, "replicas": 1, "engines": 1,
        "image": "dsv4", "volume": "v4-pro",
        "weights": f"hf/hub/models--deepseek-ai--DeepSeek-V4-Pro-0813/snapshots/{PRO_REV}",
        "engine": {"moe_backend": "marlin", "generation_config": "vllm"},
    }  # fmt: skip
    assert modal_spec(K3) == {
        "app": "adapt-kimi-k3", "gpu": ["B300:8"], "tp": 8, "replicas": 1, "engines": 1,
        "image": "default", "volume": "kimi-k3",
        "weights": f"hf/hub/models--moonshotai--Kimi-K3/snapshots/{K3_REV}",
        "engine": {"trust_remote_code": True, "language_model_only": True,
                   "gpu_memory_utilization": 0.95},
    }  # fmt: skip
    assert K3.trust_remote_code and K3.chat_template is None  # the tokenizer's own XTML render
    assert modal_spec(MUSE) == {
        "app": "adapt-muse-spark-open", "gpu": ["B300:8", "B200:8"], "tp": 8, "replicas": 1,
        "engines": 1, "image": "muse", "volume": "muse-spark",
        "weights": "hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4", "engine": {},
    }  # fmt: skip
    assert Path(MUSE.chat_template) == TEMPLATES / "muse_spark_nothink.jinja"
    assert Path(MUSE.chat_template).is_file()


def test_new_subjects_are_external_for_introspection():
    from wsbench.adapt.introspection import EXTERNAL

    assert {PRO.key, K3.key, MUSE.key} <= set(EXTERNAL)


# ---------------------------------------------------------------- DeepSeek-V4-Pro


def test_v4_pro_uses_flash_render_and_d8():
    flash = SUBJECTS["deepseek-v4-flash"]
    assert PRO.chat_template == flash.chat_template
    assert PRO.arith_all_positions  # the render ends <|Assistant|></think>, as Flash's (D8)


@cache
def _pro_encoder():
    hub = pytest.importorskip("huggingface_hub")
    path = hub.try_to_load_from_cache(PRO.hf_id, "encoding/encoding_dsv4.py", revision=PRO_REV)
    if not isinstance(path, str):
        pytest.skip("V4-Pro encoding/encoding_dsv4.py of the pinned revision is not cached")
    spec = importlib.util.spec_from_file_location("_encoding_dsv4_pro", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_v4_pro_encoder_chat_mode_is_the_pinned_template():
    """Pro's own encoder (pinned revision, local cache) in chat mode = the vendored Flash
    reference = the pinned template, on every render test_adapt_v4 checks for Flash."""
    import copy

    mod = _pro_encoder()
    for msgs in SYNTHETIC + [_msgs(m) for _f, m in bank_renders()]:
        want = mod.encode_messages(copy.deepcopy(msgs), thinking_mode="chat")
        assert want == ref_encode(msgs) == _jinja_render(msgs, enable_thinking=False), msgs
    # the reasoning-effort prompts Pro added are thinking-mode only
    u = [{"role": "user", "content": "q"}]
    for effort in ("low", "high", "max", None):
        out = mod.encode_messages(copy.deepcopy(u), thinking_mode="chat", reasoning_effort=effort)
        assert out == ref_encode(u)


def test_real_v4_pro_tokenizer_token_for_token():
    transformers = pytest.importorskip("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained(PRO.hf_id, revision=PRO_REV,
                                                         local_files_only=True)  # fmt: skip
    except Exception as e:
        pytest.skip(f"V4-Pro tokenizer not cached ({type(e).__name__})")
    tok.chat_template = Path(PRO.chat_template).read_text(encoding="utf-8")
    for msgs in SYNTHETIC[:6]:
        got = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)  # fmt: skip
        got = list(got["input_ids"] if hasattr(got, "keys") else got)
        assert got == tok(ref_encode(msgs), add_special_tokens=False)["input_ids"]
    m = template.markers(tok)
    assert (m["header_len"], m["gen_tail"]) == (1, ["</think>"])
    assert template.check(tok) == [] and template.system_rule(tok) == "bare"


# ---------------------------------------------------------------- Kimi-K3: the thinking kwarg

XO, XC, XS, EOM = "<|open|>", "<|close|>", "<|sep|>", "<|end_of_msg|>"


def _xtml(msgs, gen, thinking=True):
    """Kimi-K3's encoding_k3.build_chat_segments as tokens (users / system / plain assistant).
    ``thinking`` (default True, as upstream) prepends the thinking-effort system message and
    opens the think channel in the generation prompt."""
    toks = []
    if thinking:
        toks += [XO, "message", " role", '="', "system", '"', " type", '="', "thinking-effort",
                 '"', XS, "effort=max", XC, "message", XS, EOM]  # fmt: skip
    for m in msgs:
        toks += [XO, "message", " role", '="', m["role"], '"', XS]
        if m["role"] == "assistant":
            toks += [XO, "think", XS, XC, "think", XS] if thinking else []
            toks += [XO, "response", XS, m["content"], XC, "response", XS]
        else:
            toks += [m["content"]]
        toks += [XC, "message", XS, EOM]
    if gen:
        toks += [XO, "message", " role", '="', "assistant", '"', XS]
        toks += [XO, "think" if thinking else "response", XS]
    return toks


class XtmlTok(FakeTok):
    """The K3 tokenizer's interface: ``thinking`` is the switch; anything else (enable_thinking)
    falls into **kwargs and is ignored, exactly as the remote code does."""

    def __init__(self):
        super().__init__(_xtml, [XO, XC, XS, EOM, "[BOS]"], eos="[EOS]")
        self.calls = []

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=True,
                            thinking=True, **kw):  # fmt: skip
        self.calls.append({"thinking": thinking, **kw})
        toks = _xtml(msgs, add_generation_prompt, thinking)
        return [self._id(t) for t in toks] if tokenize else "".join(toks)

    def encode(self, text, allow_special_tokens=True):
        return self(text, add_special_tokens=False)["input_ids"]


def test_rename_thinking():
    raw = XtmlTok()
    assert subjects.rename_thinking(raw, "enable_thinking") is raw  # no wrapper by default
    tok = subjects.rename_thinking(XtmlTok(), "thinking")
    msgs = [{"role": "user", "content": "q"}]
    tok.apply_chat_template(msgs, tokenize=False, enable_thinking=False)
    tok.apply_chat_template(msgs, tokenize=False, enable_thinking=True)
    tok.apply_chat_template(msgs, tokenize=False)  # no switch: the template's own default
    assert tok.calls == [{"thinking": False}, {"thinking": True}, {"thinking": True}]


def _fake_transformers(monkeypatch, make):
    calls = []

    class _Auto:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append((name, kw))
            return make()

    monkeypatch.setitem(sys.modules, "transformers", types.SimpleNamespace(AutoTokenizer=_Auto))
    return calls


def test_load_tokenizer_takes_the_subjects_thinking_kwarg(monkeypatch):
    """author.tokenizer / RemoteRunner (load_tokenizer without the kwarg): Kimi-K3's renders
    reach its tokenizer as thinking=False; every other subject's still say enable_thinking."""
    from wsbench.adapt.author import tokenizer

    calls = _fake_transformers(monkeypatch, XtmlTok)
    msgs = [{"role": "user", "content": "q"}]
    tok = tokenizer(K3.key)
    assert calls[-1] == (K3.hf_id, {"revision": K3_REV, "trust_remote_code": True})
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False)  # fmt: skip
    assert tok.calls[-1] == {"thinking": False}
    assert text.endswith(f'{XO}message role="assistant"{XS}{XO}response{XS}')
    assert "thinking-effort" not in text
    # kimi-k2 (and every other subject): enable_thinking goes through unchanged
    k2 = tokenizer("kimi-k2")
    k2.apply_chat_template(msgs, tokenize=False, enable_thinking=False)
    assert k2.calls[-1] == {"thinking": True, "enable_thinking": False}
    # RemoteRunner's call (5 positional args, no kwarg): the registered Subject decides
    tok = subjects.load_tokenizer(K3.hf_id, K3_REV, None, None, True)
    tok.apply_chat_template(msgs, enable_thinking=False)
    assert tok.calls[-1] == {"thinking": False}
    # an explicit kwarg wins; an unregistered model keeps enable_thinking
    tok = subjects.load_tokenizer("org/unknown", None, thinking_kwarg="thinking")
    tok.apply_chat_template(msgs, enable_thinking=False)
    assert tok.calls[-1] == {"thinking": False}
    tok = subjects.load_tokenizer("org/unknown", None)
    tok.apply_chat_template(msgs, enable_thinking=False)
    assert tok.calls[-1] == {"thinking": True, "enable_thinking": False}


def test_load_tokenizer_honours_a_monkeypatched_subject(monkeypatch):
    """Subjects added at test time (monkeypatch.setitem(SUBJECTS, ...), PR #244) are looked up
    live, so their thinking_kwarg applies too."""
    _fake_transformers(monkeypatch, XtmlTok)
    monkeypatch.setitem(SUBJECTS, "fake-xtml", subjects.Subject(
        "fake-xtml", "org/fake-xtml", "Fake", 4, "x", "r1", thinking_kwarg="thinking"))  # fmt: skip
    tok = subjects.load_tokenizer("org/fake-xtml", "r1")
    tok.apply_chat_template([{"role": "user", "content": "q"}], enable_thinking=False)
    assert tok.calls[-1] == {"thinking": False}


# ---------------------------------------------------------------- Kimi-K3: markers on XTML

K3_TAIL = ["message", XS, EOM, XO, "message", " role", '="', "assistant", '"', XS, XO,
           "response", XS]  # fmt: skip


def test_xtml_markers_check_bos_stop():
    tok = subjects.rename_thinking(XtmlTok(), "thinking")
    m = template.markers(tok)
    assert (m["turn_start"], m["turn_end"], m["header_len"], m["gen_tail"]) == (
        XO, XC, 7, K3_TAIL)  # fmt: skip
    assert template.check(tok) == []
    assert template.system_rule(tok) == "marker"
    assert template.bos_prefix(tok) == []
    assert m["turn_end_id"] in template.stop_ids(tok) and tok.eos_token_id in template.stop_ids(tok)


def test_xtml_check_flags_enable_thinking_reaching_k3_unrenamed():
    """Without the rename the K3 tokenizer ignores enable_thinking=False: the render opens the
    think channel (and the effort=max system message), and the step-0 check refuses it."""
    tok = XtmlTok()
    m = template.markers(tok)  # the user turn is still found past the effort message
    assert (m["turn_start"], m["turn_end"], m["header_len"]) == (XO, XC, 7)
    problems = template.check(tok)
    assert len(problems) == 1 and "reasoning block open" in problems[0]


def test_xtml_carry_restamp_reads_the_last_user_turn():
    from wsbench.adapt.carry import restamp_read

    tok = subjects.rename_thinking(XtmlTok(), "thinking")
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "LAST"},
    ]
    r = restamp_read(tok, msgs)
    ids = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                  enable_thinking=False)  # fmt: skip
    a, b = r["span"]
    assert tok.decode(ids[a:b]) == "LAST" and tok.decode([ids[b]]) == XC
    assert r["turn_end"] == b == len(ids) - len(K3_TAIL) - 1
    assert r["tokens"] == {str(a): "LAST", str(b): XC}


def test_real_k3_tokenizer_render():
    """The pinned remote-code tokenizer (local cache): what thinking=False renders, the text
    re-encoding to the template's own ids (RemoteRunner.encode), and the step-0 checks."""
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("tiktoken")
    try:
        raw = transformers.AutoTokenizer.from_pretrained(
            K3.hf_id, revision=K3_REV, trust_remote_code=True, local_files_only=True
        )
    except Exception as e:
        pytest.skip(f"Kimi-K3 tokenizer not cached ({type(e).__name__})")
    assert template.check(raw)  # enable_thinking alone leaves the think channel open
    tok = subjects.rename_thinking(raw, K3.thinking_kwarg)
    msg = [{"role": "user", "content": "hi"}]
    text = tok.apply_chat_template(msg, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False)  # fmt: skip
    assert text == (f'{XO}message role="user"{XS}hi{XC}message{XS}{EOM}'
                    f'{XO}message role="assistant"{XS}{XO}response{XS}')  # fmt: skip
    for u in ["hi", "What is 17 + 25?\nAnswer with the number only.", " leading", "東京?"]:
        m1 = [{"role": "user", "content": u}]
        ids = tok.apply_chat_template(m1, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)  # fmt: skip
        ids = list(ids["input_ids"] if hasattr(ids, "keys") else ids)
        t = tok.apply_chat_template(m1, tokenize=False, add_generation_prompt=True,
                                    enable_thinking=False)  # fmt: skip
        assert list(tok(t, add_special_tokens=False)["input_ids"]) == ids, u
    m = template.markers(tok)
    assert (m["turn_start"], m["turn_end"], m["header_len"], m["gen_tail"]) == (
        XO, XC, 7, K3_TAIL)  # fmt: skip
    assert template.check(tok) == [] and template.system_rule(tok) == "marker"
    assert template.bos_prefix(tok) == []
    # generation_config.json eos = <|end_of_msg|>; the turn-closing <|close|> ends the reply
    assert template.stop_ids(tok, gen_eos=163586) == [163585, 163586, 163588]


# ---------------------------------------------------------------- Kimi-K3: reply_end


class _Remote:
    """A fake Modal app recording each call's args; ``answers`` = what sample / generate return."""

    def __init__(self, log, sample_out, gen_out):
        self.log, self.sample_out, self.gen_out = log, sample_out, gen_out

    def bind(self, app, name):
        log, so, go = self.log, self.sample_out, self.gen_out

        class _M:
            def __init__(self, n):
                self.n = n

            def remote(self, *args):
                log.append((self.n, args))
                return [so if self.n == "sample" else go for _ in args[0]]

        return lambda **kw: types.SimpleNamespace(sample=_M("sample"), generate=_M("generate"))


def _k3_runner(monkeypatch, tok, sample_out=("a", ["b"]), gen_out=None):
    from wsbench.adapt.gate import RemoteRunner

    log: list = []
    rem = _Remote(log, sample_out, gen_out or {"text": "t", "ids": []})
    fake = types.SimpleNamespace(Cls=types.SimpleNamespace(from_name=rem.bind))
    monkeypatch.setitem(sys.modules, "modal", fake)
    monkeypatch.setattr(subjects, "load_tokenizer", lambda *a: tok)
    return RemoteRunner(K3.hf_id, revision=K3_REV, modal_app=K3.modal_app), log


def test_remote_runner_stops_k3_replies_on_the_close_token(monkeypatch):
    """reply_end is a TOKEN stop: the engine is asked to stop on <|close|>'s id (sample: after
    top_k; generate: with the caller's stops), the reply text is never split on the string (a
    reply quoting "<|close|>" as text stays whole), and generate's ids end before the stop id."""
    from wsbench.adapt.gate import Ask

    tok = subjects.rename_thinking(XtmlTok(), "thinking")
    close = tok(XC, add_special_tokens=False)["input_ids"][0]
    quoted = f"the marker is {XC} here"
    r, log = _k3_runner(monkeypatch, tok, sample_out=(quoted, [quoted]),
                        gen_out={"text": "x", "ids": [5, close, 6, 7]})  # fmt: skip
    assert r.reply_stop == [close]
    ask = Ask("i", "surface", ("4",), messages=({"role": "user", "content": "2+2"},),
              max_tokens=8)  # fmt: skip
    assert r.sample([ask], draws=1, temperature=1.0) == [(quoted, [quoted])]
    assert log[-1][0] == "sample" and log[-1][1][6:] == (-1, [close])
    out = r.generate([[1, 2]], 0.0, 8, 0, stop_token_ids=[99])
    assert log[-1][0] == "generate" and log[-1][1][5] == sorted({99, close})
    assert out[0]["ids"] == [5] and out[0]["text"] == tok.decode([5], skip_special_tokens=True)


def _real_k3():
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("tiktoken")
    try:
        raw = transformers.AutoTokenizer.from_pretrained(
            K3.hf_id, revision=K3_REV, trust_remote_code=True, local_files_only=True
        )
    except Exception as e:
        pytest.skip(f"Kimi-K3 tokenizer not cached ({type(e).__name__})")
    return subjects.rename_thinking(raw, K3.thinking_kwarg)


def _tpl_ids(tok, msgs):
    out = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                  enable_thinking=False)  # fmt: skip
    return list(out["input_ids"] if hasattr(out, "keys") else out)


def test_real_k3_prompt_ids_keep_literal_markers_plain(monkeypatch):
    """A user message quoting XTML markers (what floors do with the subject's own render): the
    ids sent are the template's own, not the rendered text re-encoded (the quoted markers
    turned into live control tokens). Prefill, follow-up and raw prompts likewise."""
    from wsbench.adapt.gate import Ask, prompt_of

    tok = _real_k3()
    r, log = _k3_runner(monkeypatch, tok)
    msgs = ({"role": "user", "content": "<|close|>message<|sep|>"},)
    want = _tpl_ids(tok, list(msgs))
    text = r.render(Ask("i", "floor", messages=msgs))
    # the bug: re-encoding the text makes the quoted <|close|> / <|sep|> live (32 ids -> 24)
    bad = r.encode(text)
    assert len(bad) < len(want) and bad.count(163588) == 2 and want.count(163588) == 1
    ask = Ask("i", "floor", messages=msgs, max_tokens=4)
    assert r.prompt_ids(ask) == prompt_of(r, ask) == want
    r.sample([ask], draws=1, temperature=1.0)
    assert log[-1][1][0] == [want]
    # a prefill is plain text after the template's ids
    pre = r.prompt_ids(Ask("i", "floor", messages=msgs, prefill=f"A{XC}"))
    assert pre == want + list(tok.encode(f"A{XC}", allow_special_tokens=False))
    assert 163588 not in pre[len(want) :]
    # a follow-up = the full conversation's template ids (K3 encodes each segment on its own)
    fu = Ask("i", "knowledge", messages=msgs, followup=({"role": "user", "content": "Sure?"},),
             reply=f"yes {XS}")  # fmt: skip
    conv = [*msgs, {"role": "assistant", "content": f"yes {XS}"},
            {"role": "user", "content": "Sure?"}]  # fmt: skip
    assert r.prompt_ids(fu) == _tpl_ids(tok, conv)
    assert r.token_prefix(r.prompt(fu.first_turn()), r.prompt(fu))
    # a raw prompt: the text plain (K3's bos_prefix is [])
    assert r.prompt_ids(Ask("i", "raw", prompt=f"x{XO}")) == list(
        tok.encode(f"x{XO}", allow_special_tokens=False))  # fmt: skip


def test_real_k3_cont_jobs_encode_plain(monkeypatch):
    from wsbench.adapt.gate import cont_jobs

    tok = _real_k3()
    r, _ = _k3_runner(monkeypatch, tok)
    ((ids, k),) = cont_jobs(tok, [f"say {XC}"], [" ok"], r.plain)
    assert ids == list(tok.encode(f"say {XC} ok", allow_special_tokens=False))
    assert 163588 not in ids and k > 0


# ---------------------------------------------------------------- Muse-Spark-Open

MUSE_SYSTEM = (
    "<|begin_of_text|><|start|>system<|message|>You are a helpful AI assistant.\n\n"
    "Knowledge cutoff: 2026-01-04.\n\nCurrent date: 2026-11-03.\n\n{extra}"
    "Reasoning strength: 8.\n\nUse the appropriate recipient for each message:\n\n"
    '- "self": private reasoning and tool planning.\n'
    '- "commentary": user-visible intermediate updates while the assistant will continue '
    "working, including messages sent to the user before or between tool calls.\n"
    '- "user": messages that end the assistant turn, such as a completed response or '
    "clarification question that waits for the user's reply; do not use for pre-tool updates "
    'or partial responses.\n\n# Valid recipients: "self", "commentary", "user".<|eot|>'
)
MUSE_GEN = "<|start|>assistant to=user<|message|>"
MUSE_TPL = (TEMPLATES / "muse_spark_nothink.jinja").read_text(encoding="utf-8")


def _muse_render(messages, add_generation_prompt=True, chat_template=MUSE_TPL, **kw) -> str:
    """The template rendered as transformers does (its own jinja env, {% generation %} tag)."""
    ctu = pytest.importorskip("transformers.utils.chat_template_utils")
    out, _ = ctu.render_jinja_template(
        conversations=[messages], chat_template=chat_template,
        add_generation_prompt=add_generation_prompt, bos_token="<|begin_of_text|>", **kw,
    )  # fmt: skip
    return out[0]


def test_muse_template_renders_thinking_off():
    u = [{"role": "user", "content": "What is 17 * 23?"}]
    want = MUSE_SYSTEM.format(extra="") + "<|start|>user<|message|>What is 17 * 23?<|eot|>"
    assert _muse_render(u) == want + MUSE_GEN
    assert _muse_render(u, add_generation_prompt=False) == want
    # pinned: the caller cannot raise the effort or move the date; enable_thinking is ignored
    for kw in ({"reasoning_effort": "xhigh"}, {"current_date": "1999-01-01"},
               {"enable_thinking": True}):  # fmt: skip
        assert _muse_render(u, **kw) == want + MUSE_GEN, kw
    # a system message joins the system turn; an earlier assistant turn speaks to=user
    msgs = [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello."},
        {"role": "user", "content": "again"},
    ]
    assert _muse_render(msgs) == (
        MUSE_SYSTEM.format(extra="Be terse.\n\n") + "<|start|>user<|message|>hi<|eot|>"
        + MUSE_GEN + "Hello.<|eot|><|start|>user<|message|>again<|eot|>" + MUSE_GEN
    )  # fmt: skip


def test_muse_template_is_upstream_with_three_edits():
    """Against the pinned upstream chat_template.jinja (local cache): the same render at
    reasoning_effort=low and the pinned date, the generation prompt naming to=user."""
    hub = pytest.importorskip("huggingface_hub")
    path = hub.try_to_load_from_cache(MUSE.hf_id, "chat_template.jinja", revision=MUSE_REV)
    if not isinstance(path, str):
        pytest.skip("Muse chat_template.jinja of the pinned revision is not cached")
    up = Path(path).read_text(encoding="utf-8")
    kw = {"reasoning_effort": "low", "current_date": "2026-11-03"}
    cases = [
        [{"role": "user", "content": "hi"}],
        [{"role": "user", "content": "<|eot|> escaped <image>"}],
        [{"role": "system", "content": "Policy."}, {"role": "user", "content": "q"}],
        [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ],
    ]
    for msgs in cases:
        base = _muse_render(msgs, add_generation_prompt=False, chat_template=up, **kw)
        assert _muse_render(msgs, add_generation_prompt=False) == base
        gen = _muse_render(msgs, chat_template=up, **kw)
        assert gen.endswith("<|start|>assistant")
        assert _muse_render(msgs) == gen + " to=user<|message|>"


def test_real_muse_tokenizer_markers_and_stops():
    transformers = pytest.importorskip("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained(MUSE.hf_id, revision=MUSE_REV,
                                                         local_files_only=True)  # fmt: skip
    except Exception as e:  # gated: needs the token's access once to cache the files
        pytest.skip(f"Muse tokenizer not cached ({type(e).__name__})")
    tok.chat_template = MUSE_TPL
    m = template.markers(tok)
    assert (m["turn_start"], m["turn_end"], m["header_len"]) == ("<|start|>", "<|eot|>", 3)
    assert m["gen_tail"] == ["<|start|>", "assistant", " to", "=user", "<|message|>"]
    assert template.check(tok) == [] and template.system_rule(tok) == "marker"
    assert template.bos_prefix(tok) == [200000]  # the tokenizer does not add <|begin_of_text|>
    # generation_config.json eos_token_id [200001, 200008]: <|end_of_text|>, <|eot|>
    assert template.stop_ids(tok, gen_eos=[200001, 200008]) == [200001, 200008]
    assert m["turn_end_id"] == 200008
    for u in ["hi", "What is 17 + 25?\nAnswer with the number only.", " leading", "東京?"]:
        msgs = [{"role": "user", "content": u}]
        ids = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                      enable_thinking=False)  # fmt: skip
        ids = list(ids["input_ids"] if hasattr(ids, "keys") else ids)
        text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)  # fmt: skip
        assert list(tok(text, add_special_tokens=False)["input_ids"]) == ids, u
        assert ids[0] == 200000 and ids.count(200000) == 1


def test_real_muse_carry_restamp_skips_the_whole_header():
    """carry's jailbreak re-stamp on Muse's render: the span starts at the content, past the
    whole <|start|>user<|message|> header (header_len 3), never on <|message|>."""
    import json as _json

    from wsbench.adapt.carry import restamp_read
    from wsbench.evals.jailbreak_recognition.judge import prefix_to_last_user
    from wsbench.registry import frozen_bank_path

    transformers = pytest.importorskip("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained(MUSE.hf_id, revision=MUSE_REV,
                                                         local_files_only=True)  # fmt: skip
    except Exception as e:
        pytest.skip(f"Muse tokenizer not cached ({type(e).__name__})")
    tok.chat_template = MUSE_TPL
    bank = _json.loads(frozen_bank_path("jailbreak_recognition").read_text(encoding="utf-8"))
    bad = []
    for it in bank["items"]:
        r = restamp_read(tok, it["messages"])
        a, b = r["span"]
        content = prefix_to_last_user(it["messages"])[-1]["content"]
        ids = tok.apply_chat_template(prefix_to_last_user(it["messages"]), tokenize=True,
                                      add_generation_prompt=True)  # fmt: skip
        ids = list(ids["input_ids"] if hasattr(ids, "keys") else ids)
        if (
            r["tokens"][str(a)] == "<|message|>"
            or tok.decode([ids[b]]) != "<|eot|>"
            or not content.lstrip().startswith(tok.decode(ids[a : a + 3]).strip()[:1])
        ):
            bad.append(it["id"])
    assert not bad, f"{len(bad)} items: {bad[:5]}"


# ---------------------------------------------------------------- scripts/adapt_modal.py


def _load_script(monkeypatch, key):
    pytest.importorskip("modal")
    monkeypatch.setenv("ADAPT_SUBJECT", key)
    spec = importlib.util.spec_from_file_location(f"_adapt_modal_{key}",
                                                  ROOT / "scripts/adapt_modal.py")  # fmt: skip
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_adapt_modal_builds_the_new_apps(monkeypatch):
    pro = _load_script(monkeypatch, PRO.key)
    assert pro.app.name == "adapt-v4-pro" and modal_spec(PRO) == pro.SPEC
    kw = pro.engine_kwargs(pro.SPEC, PRO.hf_id, PRO_REV, 4096)
    assert kw["model"] == "/vol/" + modal_spec(PRO)["weights"]
    assert kw["model"].endswith(f"/snapshots/{PRO_REV}")
    assert kw["revision"] is None and kw["tensor_parallel_size"] == 8
    assert kw["moe_backend"] == "marlin" and pro.SPEC["engines"] == 1

    k3 = _load_script(monkeypatch, K3.key)
    assert k3.app.name == "adapt-kimi-k3" and k3.RECIPE["mount"] == "/hf"
    kw = k3.engine_kwargs(k3.SPEC, K3.hf_id, K3_REV, 4096)
    assert kw["model"] == f"/hf/hf/hub/models--moonshotai--Kimi-K3/snapshots/{K3_REV}"
    assert kw["gpu_memory_utilization"] == 0.95 and kw["language_model_only"] is True
    assert kw["trust_remote_code"] is True and kw["tensor_parallel_size"] == 8

    muse = _load_script(monkeypatch, MUSE.key)
    assert muse.app.name == "adapt-muse-spark-open" and muse.MUSE_VLLM == "vllm==0.33.0"
    assert muse.RECIPE["mount"] == "/vol"
    kw = muse.engine_kwargs(muse.SPEC, MUSE.hf_id, MUSE_REV, 4096)
    assert kw["model"] == "/vol/hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4"
    assert kw["revision"] is None and kw["tensor_parallel_size"] == 8
    assert kw["gpu_memory_utilization"] == 0.90
