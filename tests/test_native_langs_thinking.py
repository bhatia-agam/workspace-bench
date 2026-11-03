"""Plan 0054 R6 thinking-on native-language measure (plan 0060): trace delimiters read off the
template, trace extraction, per-run Han split, the subject flag and its default, the fallback to
thinking off, and the gate's template check unchanged. Offline: fake tokenizers and runners
(a real tokenizer only when it is already in the local HF cache)."""

import re
from types import SimpleNamespace
from typing import ClassVar

import pytest

from wsbench.adapt import native_langs as nl
from wsbench.adapt import store, subjects, template
from wsbench.adapt.gate import Ask, Runner

MODEL = "subj"


@pytest.fixture
def tmp_model(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    monkeypatch.setattr(store, "code_stamp", lambda: {})
    return tmp_path / MODEL


class FakeTok:
    """A ChatML tokenizer with a Qwen-style think block: ``mode`` = ``"prompt"`` (thinking on
    opens ``<think>`` in the generation prompt, Qwen3.5), ``"model"`` (the model writes it,
    Qwen3-8B), ``"always"`` (the prompt opens it whatever enable_thinking says, GLM's hub
    template) or ``"none"`` (no thinking mode, OLMo)."""

    SPECIAL = ("<|im_start|>", "<|im_end|>", "<think>", "</think>")
    PAT = re.compile(r"<\|im_start\|>|<\|im_end\|>|</?think>|\n|[^\s<]+|[ \t]+|<")

    def __init__(self, mode="prompt"):
        self.mode = mode
        self.vocab: dict[str, int] = {}
        self.added_tokens_decoder = {self._id(s): s for s in self.SPECIAL}
        self.all_special_ids = [self._id("<|im_end|>")]
        self.eos_token_id = self._id("<|im_end|>")

    def _id(self, piece):
        return self.vocab.setdefault(piece, len(self.vocab))

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [self._id(p) for p in self.PAT.findall(text)]}

    def decode(self, ids, skip_special_tokens=False):
        inv = {v: k for k, v in self.vocab.items()}
        skip = set(self.all_special_ids) if skip_special_tokens else set()
        return "".join(inv[i] for i in ids if i not in skip)

    def apply_chat_template(self, conv, tokenize=False, add_generation_prompt=False,
                            enable_thinking=False, **_):  # fmt: skip
        out = ""
        for m in conv:
            out += f"<|im_start|>{m['role']}\n"
            if m["role"] == "assistant" and "reasoning_content" in m and self.mode != "none":
                out += f"<think>\n{m['reasoning_content']}\n</think>\n\n"
            out += f"{m['content']}<|im_end|>\n"
        if add_generation_prompt:
            out += "<|im_start|>assistant\n"
            if self.mode == "always" or (self.mode == "prompt" and enable_thinking):
                out += "<think>\n"
            elif self.mode != "none" and not enable_thinking:
                out += "<think>\n\n</think>\n\n"
        return self(out)["input_ids"] if tokenize else out


# ------------------------------------------------------------------ delimiters off the template


def test_think_markers_read_off_the_render():
    tm = template.think_markers(FakeTok("prompt"))
    assert tm["open"] == "" and tm["close"] == "</think>" and tm["cut"] == "</think>"
    tok = FakeTok("model")
    tm = template.think_markers(tok)
    assert tm["open"] == "<think>\n" and tm["stop_id"] == tok.vocab["</think>"]
    assert template.think_markers(FakeTok("always"))["open"] == ""
    with pytest.raises(ValueError, match="no thinking mode"):
        template.think_markers(FakeTok("none"))


# ------------------------------------------------------------------ gate strictness unchanged


def test_gate_check_still_refuses_an_open_reasoning_block():
    assert template.check(FakeTok("prompt")) == []  # thinking-off render closes the block
    assert any("reasoning block open" in p for p in template.check(FakeTok("always")))
    # the measurement's own check accepts both; it never replaces check for a gate
    assert template.check_thinking(FakeTok("always")) == []
    assert template.check_thinking(FakeTok("prompt")) == []
    assert template.check_thinking(FakeTok("none"))  # no trace to delimit


def _fake_runner_cls(tok):
    class R:
        def __init__(self, *a, **kw):
            self.tok, self.kw = tok, kw

    return R


@pytest.mark.parametrize("backend", ["box", "modal"])
def test_runner_gating_path_keeps_check(monkeypatch, backend):
    from wsbench.adapt import gate, run

    s = SimpleNamespace(hf_id="x/y", revision=None, max_model_len=4096, modal_app="a",
                        tokenizer_dir=None, chat_template=None, thinking_template=None,
                        gpu_memory_utilization=0.8, enforce_eager=False, backend=backend,
                        thinking_mode=True)  # fmt: skip
    monkeypatch.setattr(run, "get_subject", lambda m: s)
    monkeypatch.setenv("ADAPT_BACKEND", backend)
    monkeypatch.setattr(gate, "Runner", _fake_runner_cls(FakeTok("always")))
    monkeypatch.setattr(gate, "RemoteRunner", _fake_runner_cls(FakeTok("always")))
    with pytest.raises(SystemExit, match="template check failed"):
        run._runner("m")  # a template that thinks never gates
    r = run._runner("m", measure_thinking=True, max_model_len=12288)  # the one exemption
    assert r.thinking is True and r.kw["max_model_len"] == 12288
    monkeypatch.setattr(gate, "Runner", _fake_runner_cls(FakeTok("prompt")))
    monkeypatch.setattr(gate, "RemoteRunner", _fake_runner_cls(FakeTok("prompt")))
    assert not getattr(run._runner("m"), "thinking", False)
    s.thinking_mode = False
    with pytest.raises(SystemExit, match="no thinking mode"):
        run._runner("m", measure_thinking=True)


def test_runner_render_thinks_only_when_set():
    r = Runner.__new__(Runner)
    r.tok = FakeTok("prompt")
    ask = Ask("i", "l", messages=({"role": "user", "content": "hi"},))
    assert r.render(ask).endswith("<think>\n\n</think>\n\n")  # default: thinking off
    r.thinking = True
    assert r.render(ask).endswith("assistant\n<think>\n")


# ------------------------------------------------------------------ trace extraction + letters


def test_trace_of_prompt_opened_model_opened_and_missing():
    tm = template.think_markers(FakeTok("prompt"))
    assert nl.trace_of("用户问的是 colour.\n</think>\n\nred", tm) == "用户问的是 colour.\n"
    cut = "still thinking, cut at max_tokens"
    assert nl.trace_of(cut, tm) == cut
    tm = template.think_markers(FakeTok("model"))
    assert nl.trace_of("<think>\n嗯\uff0c好的</think>\n\nOK", tm).strip() == "嗯\uff0c好的"
    assert nl.trace_of("<think>\nstopped on the closing token", tm).strip() == (
        "stopped on the closing token"
    )
    assert nl.trace_of("Just an answer.", tm) is None  # no trace opened
    # special tokens dropped by decoding (Gemma-4): the visible rest of the opener parses
    gem = {"open": "<|channel>thought\n", "open_visible": "thought\n", "close": "<channel|>",
           "cut": "<channel|>", "stop_id": 101}  # fmt: skip
    assert nl.trace_of("thought\nLet me think.", gem) == "Let me think."
    kimi = {"open": "", "close": "<|close|>think<|sep|><|open|>response<|sep|>",
            "cut": "<|close|>", "stop_id": 1}  # fmt: skip
    assert nl.trace_of("思考 here<|close|>think<|sep|>", kimi) == "思考 here"


def test_letter_codes_han_split_per_run():
    trace = "好的\uff0c用户问 colour。\nこれはテスト 日本語\n我们来想一想"
    by_run = nl.letter_codes(trace, han="run")
    # runs: 好的用户问 (zh 5) | colour (en 6) | これはテスト日本語 (ja: kana beside Han)
    # | 我们来想一想 (zh 6)
    assert by_run == {"zh": 11, "en": 6, "ja": 9}
    assert nl.letter_codes(trace) == {"ja": 20, "en": 6}  # whole-text rule: one kana flips all
    assert nl.letter_codes("ラーメン", han="run") == {"ja": 4}  # ー is a kana letter
    with pytest.raises(ValueError):
        nl.letter_codes("x", han="word")


# ------------------------------------------------------------------ flag defaults


def test_subject_thinking_flags():
    assert subjects.Subject("k", "h", "l", 1, "t").thinking_mode is False
    on = {k for k, s in subjects.SUBJECTS.items() if s.thinking_mode}
    off = set(subjects.SUBJECTS) - on
    assert {"qwen3.5-0.8b", "qwen3.5-2b", "qwen3.5-4b", "qwen3.5-9b", "qwen3-8b",
            "qwen3.6-35b-a3b", "glm-5.3", "glm-5.3-flash", "deepseek-v4-flash",
            "deepseek-v4-pro", "kimi-k3", "muse-spark-open", "gemma-4-31b-it"} == on  # fmt: skip
    assert {"olmo-3-7b", "olmo-3.1-32b", "kimi-k2"} == off
    assert nl.default_thinking("qwen3.5-0.8b") == "on"
    assert nl.default_thinking("olmo-3-7b") == "off"
    assert nl.default_thinking("no-such-subject") == "off"


def _cached_tokenizer(s):
    import os

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        return subjects.load_tokenizer(s.hf_id, s.revision, s.tokenizer_dir, s.thinking_template,
                                       s.trust_remote_code, s.thinking_kwarg)  # fmt: skip
    except Exception as e:  # not in the local cache (CI): nothing to verify here
        pytest.skip(f"{s.key}: tokenizer not cached ({type(e).__name__})")


# DeepSeek-V4: thinking mode in encoding_dsv4 but no Jinja template renders it (no hub template)
NO_THINKING_RENDER = {"deepseek-v4-flash", "deepseek-v4-pro"}


@pytest.mark.parametrize("key", sorted(subjects.SUBJECTS))
def test_flag_matches_the_template(key):
    """``thinking_mode`` is True exactly when the subject's thinking render delimits a trace."""
    s = subjects.SUBJECTS[key]
    if key in NO_THINKING_RENDER:
        pytest.skip("no thinking render pinned")
    tok = _cached_tokenizer(s)
    assert (template.check_thinking(tok) == []) is s.thinking_mode


# ------------------------------------------------------------------ measure: on, fallback


class TraceRunner:
    """Fake thinking runner: family traces think in Chinese, neutral ones in English."""

    thinking = True

    def __init__(self, fam_trace="嗯\uff0c用户问的是这个词的意思。我想一下。", tok=None):
        self.fam_trace, self.tok, self.calls = fam_trace, tok, []

    def sample(self, asks, draws, temperature, top_p=1.0, stop_token_ids=None):
        self.calls.append((asks, stop_token_ids))
        assert (draws, temperature) == (nl.K, nl.TEMPERATURE)
        out = []
        for a in asks:
            assert a.prefill == "" and a.messages and a.max_tokens == nl.THINK_MAX_TOKENS
            trace = (self.fam_trace if a.item_id.startswith("family:") else
                     "Okay, the user wants a short answer about this everyday topic.")  # fmt: skip
            out.append(("greedy", [trace + "</think>\n\nanswer"] * draws))
        return out


def test_measure_thinking_on_counts_trace_letters(tmp_model, monkeypatch):
    tm = template.think_markers(FakeTok("prompt"))
    ref = SimpleNamespace(hf_id=nl.CALIBRATION_REFERENCE[0], thinking_mode=True)
    monkeypatch.setattr(subjects, "get", lambda key: ref)
    runner = TraceRunner()
    rec = nl.measure(MODEL, runner=runner, markers=tm)  # default: on (a thinking subject)
    assert rec["thinking"] == "on" and "thinking ON" in rec["evidence"]
    assert rec["native_langs"] == ["en", "zh"]
    assert rec["calibration"]["status"] == "pass"
    # no tok on the fake runner: draws stop at the trace's closing token
    assert runner.calls[0][1] == [tm["stop_id"]]
    # a close that survives decoding is cut from the text instead (older deployed apps)
    tok = FakeTok("prompt")
    assert nl._trace_stop(template.think_markers(tok), tok) is None
    tok.all_special_ids.append(tok.vocab["</think>"])  # decoding now drops it: stop on it
    assert nl._trace_stop(template.think_markers(tok), tok) == [tok.vocab["</think>"]]
    assert rec["protocol"]["n_family"] == 30 and rec["protocol"]["n_neutral"] == 20
    assert rec["traces"]["n"] == 50 * nl.K and rec["traces"]["missing"] == 0
    # the decision is over ALL traces (R6): family + neutral letters
    assert "zh" not in rec["shares_neutral"]
    assert rec["shares_all"]["zh"] < rec["shares_family"]["zh"]
    assert nl.load(MODEL)["thinking"] == "on"
    # English-only traces: the reference fails calibration
    rec = nl.measure(MODEL, runner=TraceRunner("Let me think about the word."), markers=tm)
    assert rec["native_langs"] == ["en"] and rec["calibration"]["status"] == "FAIL"


def test_measure_refuses_a_non_thinking_runner(tmp_model, monkeypatch):
    monkeypatch.setattr(subjects, "get", lambda key: SimpleNamespace(hf_id="h", thinking_mode=True))
    r = TraceRunner()
    r.thinking = False
    with pytest.raises(SystemExit, match="thinking runner"):
        nl.measure(MODEL, runner=r, markers=template.think_markers(FakeTok("prompt")))


def test_measure_falls_back_to_off_without_a_thinking_mode(tmp_model, monkeypatch):
    plain = SimpleNamespace(hf_id="allenai/x", thinking_mode=False)
    monkeypatch.setattr(subjects, "get", lambda key: plain)

    class OffRunner:
        def sample(self, asks, draws, temperature, top_p=1.0):
            assert all(a.max_tokens == nl.MAX_TOKENS for a in asks)
            return [("g", ["A plain English answer."] * draws) for _a in asks]

    rec = nl.measure(MODEL, runner=OffRunner())
    assert rec["thinking"] == "off" and rec["native_langs"] == ["en"]
    assert "no thinking mode" in rec["evidence"]
    with pytest.raises(SystemExit, match="no thinking mode"):
        nl.measure(MODEL, thinking="on", runner=TraceRunner())
    rec = nl.measure(MODEL, thinking="off", runner=OffRunner())  # explicit off is honoured
    assert "thinking=off requested" in rec["evidence"]


# ------------------------------------------------------------------ readout criterion (J-lens)


class ByteTok:
    """Token strings -> ids for decode_token: two byte-level tokens (raw spelling) and plain
    pieces; ``decode`` returns their text."""

    unk_token_id = None
    TOKENS: ClassVar[dict[str, str]] = {"åķ¥": "啥", "Ġred": " red", "Ġ42": " 42",
                                        "ĠاØŃ": " اح"}  # fmt: skip

    def __init__(self):
        self.ids = {t: i for i, t in enumerate(self.TOKENS)}

    def convert_tokens_to_ids(self, t):
        return self.ids.get(t)

    def decode(self, ids):
        inv = {i: t for t, i in self.ids.items()}
        return self.TOKENS[inv[ids[0]]]


def test_decode_token_and_token_lang():
    tok = ByteTok()
    assert nl.decode_token(tok, "åķ¥") == "啥"  # a raw byte-level spelling
    assert nl.decode_token(tok, " red") == " red"  # display spelling (Ġ shown as a space)
    assert nl.decode_token(tok, "unknown") == "unknown"
    assert nl.token_lang("啥") == "zh" and nl.token_lang(" red") == "en"
    assert nl.token_lang(" 42") is None  # no letters: out of the shares


def _write_readouts(root, sites, tokens_for):
    import json as _json

    root.mkdir(parents=True, exist_ok=True)
    rows: dict[str, list] = {}
    for fam, ask in sites:
        for layer in (20, 40):
            rows.setdefault(fam, []).append(
                {
                    "id": ask.item_id,
                    "layer": layer,
                    "pos": 3,
                    "tokens": tokens_for(fam, ask),
                    "scores": [0] * 10,
                }
            )
    for fam, rs in rows.items():
        (root / f"{fam}.jsonl").write_text("\n".join(_json.dumps(r) for r in rs))


def test_read_sites_round_robin_over_families():
    sites = nl.read_sites()
    assert len(sites) == nl.READ_SITES
    assert [f for f, _a in sites[: len(nl.FAMILIES)]] == list(nl.FAMILIES)


def test_readout_criterion_shares_and_own_script(tmp_path):
    sites = nl.read_sites()
    # 6 English + 3 Chinese + 1 digit token per cell; Arabic items add their own script
    toks = [" red"] * 6 + ["åķ¥"] * 3 + [" 42"]
    _write_readouts(tmp_path / "jl", sites, lambda f, a: toks)
    ro = nl.readout_criterion(str(tmp_path / "jl"), ByteTok())
    assert ro["native"] == ["en", "zh"] and ro["shares"] == {"en": 0.6667, "zh": 0.3333}
    assert ro["n_cells"] == 2 * nl.READ_SITES and ro["n_tokens_without_letters"] == 20

    # a token in the item's own L2 script is left out (recorded in shares_incl_own)
    def arabic_echo(f, a):  # the Arabic items' readouts echo their passage's script
        return [" red"] * 5 + (["ĠاØŃ"] * 5 if "ar" in nl.letter_codes(a.question()) else [])

    _write_readouts(tmp_path / "ar", sites, arabic_echo)
    ro = nl.readout_criterion(str(tmp_path / "ar"), ByteTok())
    assert ro["shares_incl_own"]["ar"] >= nl.SHARE and ro["native"] == ["en"]
    with pytest.raises(SystemExit, match="token lens"):
        nl.readout_criterion(str(tmp_path / "jl"), ByteTok(), sampling="bullet4")
    with pytest.raises(SystemExit, match="no readouts"):
        nl.readout_criterion(str(tmp_path / "empty"), ByteTok())


def test_readout_sidecar_must_declare_a_token_lens(tmp_path):
    import json as _json

    sites = nl.read_sites()
    _write_readouts(tmp_path, sites, lambda f, a: [" red"] * 10)
    (tmp_path / f"{sites[0][0]}.jsonl.meta.json").write_text(_json.dumps({"sampling": "bullet4"}))
    with pytest.raises(SystemExit, match="declares sampling"):
        nl.readout_criterion(str(tmp_path), ByteTok())


def test_combine_records_which_criterion():
    native, by = nl.combine({"trace": ["en", "ja"], "readout": ["en", "zh", "ja"]})
    assert native == ["en", "ja", "zh"]
    assert by == {"en": ["always"], "ja": ["trace", "readout"], "zh": ["readout"]}
    assert nl.combine({"trace": ["en"], "readout": None}) == (["en"], {"en": ["always"]})


def test_measure_trace_plus_readouts(tmp_model, tmp_path, monkeypatch):
    """The 27B shape: English traces, Chinese in the J-lens -> ['en', 'zh'] by the readout."""
    tm = template.think_markers(FakeTok("prompt"))
    ref = SimpleNamespace(hf_id=nl.CALIBRATION_REFERENCE[0], thinking_mode=True)
    monkeypatch.setattr(subjects, "get", lambda key: ref)
    _write_readouts(tmp_path / "jl", nl.read_sites(), lambda f, a: [" red"] * 7 + ["åķ¥"] * 3)
    english = TraceRunner("Let me think about the word.")
    rec = nl.measure(MODEL, runner=english, markers=tm, readouts=str(tmp_path / "jl"),
                     tok=ByteTok())  # fmt: skip
    assert rec["native_langs"] == ["en", "zh"] and rec["native_by"]["zh"] == ["readout"]
    assert rec["criteria"]["trace"]["native"] == ["en"]
    assert rec["criteria"]["readout"]["status"] == "measured"
    assert rec["calibration"]["status"] == "pass"
    assert "READOUT criterion" in rec["evidence"] and "calibration pass" in rec["evidence"]
    # no readouts: the trace alone decides, and the record says so
    rec = nl.measure(MODEL, runner=english, markers=tm)
    assert rec["native_langs"] == ["en"] and rec["criteria"]["readout"]["status"] == "none"
    assert rec["calibration"]["status"] == "FAIL"
    # added later to the measured record
    rec = nl.add_readouts(MODEL, str(tmp_path / "jl"), tok=ByteTok())
    assert rec["native_langs"] == ["en", "zh"] and rec["evidence"].count("calibration") == 1


def test_trace_leaves_out_the_prompts_own_script(tmp_model, monkeypatch):
    """A family trace quoting its Arabic passage does not make Arabic native."""
    tm = template.think_markers(FakeTok("prompt"))
    monkeypatch.setattr(subjects, "get", lambda key: SimpleNamespace(hf_id="h", thinking_mode=True))

    class Quoting(TraceRunner):
        def sample(self, asks, draws, temperature, top_p=1.0, stop_token_ids=None):
            out = []
            for a in asks:
                q = "الدم لونه أحمر اللون " * 3 if "ar" in nl.letter_codes(a.question()) else ""
                out.append(("g", [f"The user writes {q} and wants a word.</think>x"] * draws))
            return out

    rec = nl.measure(MODEL, runner=Quoting(), markers=tm)
    assert rec["shares_all_incl_own_scripts"]["ar"] >= nl.SHARE
    assert "ar" not in rec["shares_all"] and rec["native_langs"] == ["en"]


# ------------------------------------------------------------------ review fixes (#256)


def test_bad_readouts_dir_fails_before_sampling(tmp_model, tmp_path, monkeypatch):
    monkeypatch.setattr(subjects, "get", lambda key: SimpleNamespace(hf_id="h", thinking_mode=True))

    class NeverSample(TraceRunner):
        def sample(self, *a, **kw):
            raise AssertionError("sampled before the readouts dir was checked")

    with pytest.raises(SystemExit, match="no readouts"):
        nl.measure(MODEL, runner=NeverSample(), readouts=str(tmp_path / "empty"),
                   markers=template.think_markers(FakeTok("prompt")))  # fmt: skip


def test_record_is_a_decision_and_takes_readouts(tmp_model, tmp_path):
    rec = nl.record(MODEL, ["en", "zh"], "Chinese-lab model: en+zh assumed")
    assert rec["method"] == "decision" and "thinking" not in rec
    assert nl.load(MODEL)["native_langs"] == ["en", "zh"]
    _write_readouts(tmp_path / "jl", nl.read_sites(), lambda f, a: [" red"] * 10)
    rec = nl.add_readouts(MODEL, str(tmp_path / "jl"), tok=ByteTok())  # no KeyError
    assert rec["native_langs"] == ["en", "zh"] and rec["native_by"]["zh"] == ["decision"]
    assert rec["criteria"]["decision"]["shares"] is None
    # a measurement made elsewhere keeps its mode and method
    rec = nl.record(MODEL, ["en"], "measured on the box", thinking="on")
    assert (rec["thinking"], rec["method"]) == ("on", "plan 0054 R6")
    assert nl.add_readouts(MODEL, str(tmp_path / "jl"), tok=ByteTok())["native_langs"] == ["en"]


def test_trace_end_counts_on_the_trace():
    tok = FakeTok("prompt")
    tm = template.think_markers(tok)
    assert nl.trace_end("thinking</think>\n\nanswer", tm, None, tok) == "closed"
    assert nl.trace_end("thinking, then the turn ended", tm, None, tok) == "eos"
    assert nl.trace_end("stopped on the close token", tm, [1], tok) == "closed"
    long = "word " * nl.THINK_MAX_TOKENS
    assert nl.trace_end(long, tm, None, tok) == "cut"
    assert nl.trace_end(long, tm, [1], tok) == "cut"  # budget hit even with a stop id
    # a long ANSWER after a closed trace is not a cut trace
    assert nl.trace_end("t</think>" + long, tm, None, tok) == "closed"


def test_read_site_is_one_position(tmp_path):
    import json as _json

    sites = nl.read_sites()
    root = tmp_path / "full"
    root.mkdir()
    rows: dict[str, list] = {}
    for fam, ask in sites:
        for pos, toks in ((3, ["åķ¥"] * 10), (7, [" red"] * 10)):  # a full-position file
            for layer in (20, 40):
                rows.setdefault(fam, []).append({"id": ask.item_id, "layer": layer, "pos": pos,
                                                 "tokens": toks})  # fmt: skip
    for fam, rs in rows.items():
        (root / f"{fam}.jsonl").write_text("\n".join(_json.dumps(r) for r in rs))
    ro = nl.readout_criterion(str(root), ByteTok())
    assert ro["n_cells"] == 2 * nl.READ_SITES  # one position x 2 layers per site
    assert set(ro["positions"].values()) == {7} and ro["native"] == ["en"]
