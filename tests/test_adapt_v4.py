"""Plan 0060 A3: DeepSeek-V4-Flash subject support for the adapt package.

- The pinned no-think template (``data/templates/deepseek_v4_chat.jinja``) reproduces
  ``encoding_dsv4.encode_messages(thinking_mode="chat")`` token for token.
- ``template.markers`` / ``check`` / ``bos_prefix`` / ``system_rule`` on V4's role-named
  ``<|User|>`` (fullwidth bars) render, with every other subject's marker results pinned unchanged.
- ``author.tokenizer`` applies a Subject's ``chat_template`` with no ``tokenizer_dir``.
- V4's end-relative anchors: carry's jailbreak re-stamp and MCDM by character span, 0 mismatches;
  arithmetic per D8 (no pre-registered cell: freeze, read plan and judge read every position).

Tests marked "real" use the pinned tokenizer files from the local HF cache (tokenizer files
only, no weights) and skip when transformers or the files are absent; the rest run on small
fake tokenizers that spell each subject's render shape."""

import copy
import importlib.util
import json
import sys
import types
from functools import cache, lru_cache
from pathlib import Path

import pytest

from wsbench.adapt import template
from wsbench.adapt.subjects import SUBJECTS, TEMPLATES, remap_layer
from wsbench.registry import frozen_bank_path

V4 = SUBJECTS["deepseek-v4-flash"]
BAR = "\uff5c"  # DeepSeek's special tokens use the fullwidth vertical line
BOS, EOS = f"<{BAR}begin\u2581of\u2581sentence{BAR}>", f"<{BAR}end\u2581of\u2581sentence{BAR}>"
USER, ASSISTANT = f"<{BAR}User{BAR}>", f"<{BAR}Assistant{BAR}>"
S = template.SENTINEL


# ---------------------------------------------------------------- the reference encoder


def ref_encode(messages: list[dict]) -> str:
    """``encoding_dsv4.encode_messages(messages, thinking_mode="chat")`` (DeepSeek-V4-Flash
    @60d8d707, ``encoding/encoding_dsv4.py``) for system / user / developer / assistant messages
    without tools or tasks, vendored: ``render_message`` + its transition rule."""
    out = BOS  # add_default_bos_token, no context
    for i, m in enumerate(messages):
        role, content = m["role"], m.get("content") or ""
        if role == "system":
            out += content  # system_msg_template = "{content}"
        elif role in ("user", "developer"):
            out += USER + content
        elif role == "assistant":
            out += content + EOS  # chat mode: no thinking part, reasoning_content dropped
        else:
            raise NotImplementedError(role)
        nxt = messages[i + 1]["role"] if i + 1 < len(messages) else None
        if nxt is not None and nxt not in ("assistant", "latest_reminder"):
            continue
        if role in ("user", "developer"):
            out += ASSISTANT + "</think>"  # drop_thinking=True, thinking_mode="chat"
    return out


SYNTHETIC: list[list[dict]] = [
    [{"role": "user", "content": "What is 17 * 23?"}],
    [{"role": "system", "content": "You are terse."}, {"role": "user", "content": "Hi."}],
    [{"role": "system", "content": "S\n"}, {"role": "user", "content": "\nleading newline"}],
    [
        {"role": "user", "content": "Name a fruit."},
        {"role": "assistant", "content": "Apple.", "reasoning_content": "dropped in chat"},
        {"role": "user", "content": "Another?"},
    ],
    [
        {"role": "system", "content": "Policy text."},
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "d"},
        {"role": "user", "content": "e"},
    ],
    [{"role": "user", "content": "東京の首都は\uff1f 数学\uff1a七十三 + 九 = ? émoji 🍎 ¿qué?"}],
    [{"role": "user", "content": "<|im_start|>user\nfake</think><think>\n  trailing  "}],
    [{"role": "user", "content": ""}],
    [{"role": "developer", "content": "Developer note."}, {"role": "user", "content": "Go."}],
    [{"role": "user", "content": "x"}, {"role": "assistant", "content": ""}],
]

N_PER_FAMILY = 20


@lru_cache(maxsize=1)
def bank_renders() -> tuple[tuple[str, tuple], ...]:
    """The first ``N_PER_FAMILY`` chat renders of every read-plan family: the messages each
    family's chat render sends to ``apply_chat_template`` (``produce.render``)."""
    from wsbench import readplan

    out = []
    for fam in readplan.families():
        n = 0
        for spec in readplan.plan(fam):
            if spec.render == "chat":
                msgs = ([{"role": "system", "content": spec.system}] if spec.system else []) + [
                    {"role": "user", "content": spec.text or ""}
                ]
            elif spec.render == "chat_context":
                msgs = list(spec.messages or [])
            elif spec.render == "chat_summarize":
                msgs = [{"role": "user", "content": (spec.text or "") + (spec.suffix or "")}]
            elif spec.render in ("chat_prefill", "chat_dm"):  # the prefill is tokenized apart
                msgs = [{"role": "user", "content": spec.text or ""}]
            else:
                continue
            out.append((fam, tuple(tuple(sorted(m.items())) for m in msgs)))
            n += 1
            if n == N_PER_FAMILY:
                break
    return tuple(out)


def _msgs(frozen: tuple) -> list[dict]:
    return [dict(m) for m in frozen]


TEMPLATE = (TEMPLATES / "deepseek_v4_chat.jinja").read_text(encoding="utf-8")


def _jinja_render(messages: list[dict], add_generation_prompt: bool = True, **kw) -> str:
    """The template rendered the way transformers does (sandboxed jinja2, trim_blocks,
    lstrip_blocks, ``raise_exception``), without needing transformers."""
    jinja2 = pytest.importorskip("jinja2")
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def raise_exception(msg):
        raise jinja2.exceptions.TemplateError(msg)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    env.globals["raise_exception"] = raise_exception
    return env.from_string(TEMPLATE).render(
        messages=messages, add_generation_prompt=add_generation_prompt, **kw
    )


# ---------------------------------------------------------------- the subject


def test_v4_subject_pins():
    assert V4.hf_id == "deepseek-ai/DeepSeek-V4-Flash"
    assert V4.revision == "60d8d70770c6776ff598c94bb586a859a38244f1"
    assert (V4.n_layers, V4.tokenizer, V4.backend) == (43, "dsv4", "modal")
    assert V4.modal_app == "adapt-v4-flash" and V4.tokenizer_dir is None
    assert Path(V4.chat_template) == TEMPLATES / "deepseek_v4_chat.jinja"
    assert Path(V4.chat_template).is_file()
    # J-lens std-n1000 rows 0..40 = blocks 0..40; row 41 (identity anchor) and L42 never read
    assert V4.read_band == tuple(range(41))
    assert remap_layer(63, 43, V4.read_band) == 40 and remap_layer(60, 43, V4.read_band) == 40
    assert remap_layer(56, 43, V4.read_band) == 38 and remap_layer(0, 43, V4.read_band) == 0
    assert V4.arith_all_positions
    assert not any(s.arith_all_positions for k, s in SUBJECTS.items() if k != V4.key)


# ---------------------------------------------------------------- the template (string level)


def test_vendored_encoder_matches_upstream_when_cached():
    """The vendored ``ref_encode`` agrees with DeepSeek's own ``encoding_dsv4.py`` (pinned
    revision, from the local HF cache) on every render this file checks."""
    hub = pytest.importorskip("huggingface_hub")
    path = hub.try_to_load_from_cache(V4.hf_id, "encoding/encoding_dsv4.py", revision=V4.revision)
    if not isinstance(path, str):
        pytest.skip("encoding/encoding_dsv4.py of the pinned revision is not cached")
    spec = importlib.util.spec_from_file_location("_encoding_dsv4_ref", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cases = SYNTHETIC + [_msgs(m) for _f, m in bank_renders()]
    for msgs in cases:
        assert mod.encode_messages(copy.deepcopy(msgs), thinking_mode="chat") == ref_encode(msgs)


def test_template_reproduces_encode_messages_as_text():
    cases = SYNTHETIC + [_msgs(m) for _f, m in bank_renders()]
    fams = {f for f, _m in bank_renders()}
    assert len(fams) >= 15  # every chat-rendered family (16 today) contributes up to 20 renders
    for msgs in cases:
        assert _jinja_render(msgs, enable_thinking=False) == ref_encode(msgs), msgs
        # thinking stays off whatever enable_thinking says
        assert _jinja_render(msgs, enable_thinking=True) == ref_encode(msgs)


def test_template_generation_prompt_and_unsupported_inputs():
    jinja2 = pytest.importorskip("jinja2")
    u = [{"role": "user", "content": "q"}]
    assert _jinja_render(u) == f"{BOS}{USER}q{ASSISTANT}</think>"
    assert _jinja_render(u, add_generation_prompt=False) == f"{BOS}{USER}q"
    for bad in (
        [{"role": "tool", "content": "r"}],
        [{"role": "user", "content": "q", "tools": [{"type": "function"}]}],
        [{"role": "assistant", "content": "", "tool_calls": [{"function": {}}]}],
    ):
        with pytest.raises(jinja2.exceptions.TemplateError):
            _jinja_render(bad)


# ---------------------------------------------------------------- fake tokenizers


class FakeTok:
    """A token-list tokenizer: ``render(messages, gen)`` spells the subject's chat render as a
    list of token strings; ``specials`` are its special tokens; ``add_bos`` = what a plain
    ``tok(text, add_special_tokens=True)`` prepends."""

    def __init__(self, render, specials, add_bos=(), eos="</s>"):
        self.render, self.vocab = render, []
        self.specials = set(specials) | {eos}
        self.add_bos = list(add_bos)
        self.eos_token_id = self._id(eos)
        self.bos_token = add_bos[0] if add_bos else None

    def _id(self, t: str) -> int:
        if t not in self.vocab:
            self.vocab.append(t)
        return self.vocab.index(t)

    @property
    def all_special_ids(self) -> list[int]:
        return [self._id(t) for t in sorted(self.specials)]

    def apply_chat_template(self, msgs, tokenize=True, add_generation_prompt=True, **_):
        toks = self.render(msgs, add_generation_prompt)
        return [self._id(t) for t in toks] if tokenize else "".join(toks)

    def decode(self, ids, skip_special_tokens=False):
        return "".join(self.vocab[i] for i in ids)

    def __call__(self, text, add_special_tokens=True):
        ids = [self._id(t) for t in text.split(" ")] if text else []
        return {
            "input_ids": ([self._id(t) for t in self.add_bos] if add_special_tokens else []) + ids
        }


def _chatml(think_tail: bool, default_system: str | None = None):
    def render(msgs, gen):
        toks = []
        if default_system and not any(m["role"] == "system" for m in msgs):
            toks += ["<|im_start|>", "system", "\n", default_system, "<|im_end|>", "\n"]
        for m in msgs:
            toks += ["<|im_start|>", m["role"], "\n", m["content"], "<|im_end|>", "\n"]
        if gen:
            toks += ["<|im_start|>", "assistant", "\n"]
            toks += ["<think>", "\n\n", "</think>", "\n\n"] if think_tail else []
        return toks

    return render


def _gemma(msgs, gen):
    toks = ["<bos>"]
    for m in msgs:
        role = "model" if m["role"] == "assistant" else m["role"]
        toks += ["<|turn>", role, "\n", m["content"], "<turn|>", "\n"]
    return toks + (["<|turn>", "model", "\n"] if gen else [])


def _glm(msgs, gen):
    toks = ["[gMASK]", "<sop>"]
    for m in msgs:
        toks += [f"<|{m['role']}|>", "\n", m["content"]]
    return toks + (["<|assistant|>", "</think>"] if gen else [])


def _kimi(msgs, gen):
    toks = []
    if not any(m["role"] == "system" for m in msgs):
        toks += ["<|im_system|>", "system", "<|im_middle|>", "You are Kimi.", "<|im_end|>"]
    for m in msgs:
        toks += [f"<|im_{m['role']}|>", m["role"], "<|im_middle|>", m["content"], "<|im_end|>"]
    return toks + (["<|im_assistant|>", "assistant", "<|im_middle|>"] if gen else [])


def _v4(msgs, gen):
    """The V4 render as tokens (the pinned template's shape)."""
    toks = [BOS]
    for i, m in enumerate(msgs):
        if m["role"] == "system":
            toks += [m["content"]]
        elif m["role"] == "user":
            toks += [USER, m["content"]]
            last = i + 1 == len(msgs)
            if (last and gen) or (not last and msgs[i + 1]["role"] == "assistant"):
                toks += [ASSISTANT, "</think>"]
        else:
            toks += [m["content"], EOS]
    return toks


CHATML_SP = ["<|im_start|>", "<|im_end|>", "<think>", "</think>"]
FAKES = {
    "qwen": lambda: FakeTok(_chatml(True), CHATML_SP, eos="<|im_end|>"),
    "olmo": lambda: FakeTok(_chatml(False, "You are OLMo."), CHATML_SP, eos="<|endoftext|>"),
    "gemma": lambda: FakeTok(_gemma, ["<bos>", "<|turn>", "<turn|>"], eos="<eos>"),
    "glm": lambda: FakeTok(
        _glm,
        ["[gMASK]", "<sop>", "<|user|>", "<|assistant|>", "<|system|>", "</think>"],
        eos="<|endoftext|>",
    ),
    "kimi": lambda: FakeTok(
        _kimi,
        ["<|im_system|>", "<|im_user|>", "<|im_assistant|>", "<|im_middle|>", "<|im_end|>"],
        eos="[EOS]",
    ),
    "v4": lambda: FakeTok(_v4, [BOS, USER, ASSISTANT, "</think>"], eos=EOS),
}

# pinned: the existing subjects' results are what template.py gave before plan 0060 A3 (checked
# against the pre-A3 module, git show ef1497c0:src/wsbench/adapt/template.py)
EXPECTED = {
    "qwen": ("<|im_start|>", "<|im_end|>", 3,
             ["\n", "<|im_start|>", "assistant", "\n", "<think>", "\n\n", "</think>", "\n\n"], [],
             "marker"),
    "olmo": ("<|im_start|>", "<|im_end|>", 3, ["\n", "<|im_start|>", "assistant", "\n"], [],
             "marker"),
    "gemma": ("<|turn>", "<turn|>", 3, ["\n", "<|turn>", "model", "\n"], ["<bos>"], "marker"),
    "glm": ("<|user|>", "<|assistant|>", 2, ["</think>"], ["[gMASK]", "<sop>"], "marker"),
    "kimi": ("<|im_user|>", "<|im_end|>", 3, ["<|im_assistant|>", "assistant", "<|im_middle|>"],
             [], "marker"),
    "v4": (USER, ASSISTANT, 1, ["</think>"], [BOS], "bare"),
}  # fmt: skip


def _summary(tok, mod=template) -> tuple:
    m = mod.markers(tok)
    bos = [tok.decode([i]) for i in mod.bos_prefix(tok)]
    return (m["turn_start"], m["turn_end"], m["header_len"], m["gen_tail"], bos)


@pytest.mark.parametrize("name", sorted(FAKES))
def test_marker_results_per_render_shape(name):
    tok = FAKES[name]()
    *want, rule = EXPECTED[name]
    assert _summary(tok) == tuple(want)
    assert template.check(tok) == []
    assert template.system_rule(tok) == rule
    m = template.markers(tok)
    assert tok.eos_token_id in template.stop_ids(tok) and m["turn_end_id"] in template.stop_ids(tok)


def _pre_a3_template():
    """template.py as it was before plan 0060 A3 (git object of the base commit), or None."""
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    try:
        src = subprocess.run(
            ["git", "-C", str(repo), "show", "ef1497c0:src/wsbench/adapt/template.py"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    mod = types.ModuleType("_template_pre_a3")
    exec(compile(src, "template_pre_a3.py", "exec"), mod.__dict__)
    return mod


def test_existing_shapes_unchanged_from_pre_a3_module():
    old = _pre_a3_template()
    if old is None:
        pytest.skip("base commit not available")
    for name in ("qwen", "olmo", "gemma", "glm", "kimi"):
        assert _summary(FAKES[name]()) == _summary(FAKES[name](), old), name
        assert template.stop_ids(FAKES[name]()) == old.stop_ids(FAKES[name]())
    with pytest.raises(StopIteration):  # the pre-A3 role detection could not see V4's USER
        old.markers(FAKES["v4"]())


def test_check_flags_a_dropped_system_turn():
    def drops_system(msgs, gen):
        return _chatml(True)([m for m in msgs if m["role"] != "system"], gen)

    tok = FakeTok(drops_system, CHATML_SP, eos="<|im_end|>")
    assert template.check(tok) == ["template drops the system turn's content"]


# ---------------------------------------------------------------- real tokenizers (local cache)


@cache
def _real(key: str):
    transformers = pytest.importorskip("transformers")
    s = SUBJECTS[key]
    try:
        tok = transformers.AutoTokenizer.from_pretrained(
            s.hf_id, revision=s.revision, local_files_only=True
        )
    except Exception as e:  # not cached / remote code (Kimi) / no local files
        pytest.skip(f"{key}: tokenizer not loadable offline ({type(e).__name__})")
    if s.chat_template:
        tok.chat_template = Path(s.chat_template).read_text(encoding="utf-8")
    return tok


def _ids(out) -> list[int]:
    return list(out["input_ids"] if hasattr(out, "keys") else out)


def test_real_v4_template_token_for_token():
    """The pinned template through ``apply_chat_template`` gives the same ids as tokenizing
    ``encode_messages`` (``add_special_tokens=False``, as vLLM gets them) on every render."""
    tok = _real(V4.key)
    cases = SYNTHETIC + [_msgs(m) for _f, m in bank_renders()]
    bad = []
    for msgs in cases:
        got = _ids(tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                           enable_thinking=False))  # fmt: skip
        want = tok(ref_encode(msgs), add_special_tokens=False)["input_ids"]
        if got != want:
            bad.append(msgs)
    assert not bad, f"{len(bad)}/{len(cases)} renders differ, e.g. {bad[0]}"


def test_real_v4_markers_check_bos_stop():
    tok = _real(V4.key)
    m = template.markers(tok)
    assert (m["turn_start"], m["turn_end"], m["header_len"], m["gen_tail"]) == (
        USER, ASSISTANT, 1, ["</think>"]
    )  # fmt: skip
    assert template.check(tok) == []
    assert template.system_rule(tok) == "bare"
    assert [tok.decode([i]) for i in template.bos_prefix(tok)] == [BOS]
    assert tok("x", add_special_tokens=True)["input_ids"][:1] != template.bos_prefix(tok)
    stops = template.stop_ids(tok, gen_eos=1)  # generation_config.json eos_token_id = 1
    assert tok.eos_token_id == 1 and stops == sorted({1, m["turn_end_id"]})


QWEN_TAIL = ["\n", "<|im_start|>", "assistant", "\n", "<think>", "\n\n", "</think>", "\n\n"]
CHATML = ("<|im_start|>", "<|im_end|>", 3)
# pinned: (turn_start, turn_end, header_len, gen_tail, bos_prefix decoded, stop_ids) as the
# pre-A3 template.py gave them on each subject's own tokenizer (local HF cache, 2026-11-03);
# check() == [] and system_rule == "marker" on all of them. kimi-k2 / glm-5.3-flash have no
# local tokenizer here (Agam-only tokenizer_dir): their shapes are pinned by the fakes above.
REAL_EXPECTED = {
    **{k: (*CHATML, QWEN_TAIL, [], [248046])
       for k in ("qwen3.5-0.8b", "qwen3.5-2b", "qwen3.5-4b", "qwen3.5-9b", "qwen3.6-35b-a3b")},
    "qwen3-8b": (*CHATML, QWEN_TAIL, [], [151645]),
    **{k: (*CHATML, ["\n", "<|im_start|>", "assistant", "\n"], [], [100257, 100265])
       for k in ("olmo-3-7b", "olmo-3.1-32b")},
    "gemma-4-31b-it": ("<|turn>", "<turn|>", 3,
                       ["\n", "<|turn>", "model", "\n", "<|channel>", "thought", "\n",
                        "<channel|>"], ["<bos>"], [1, 106]),
}  # fmt: skip


@pytest.mark.parametrize("key", sorted(REAL_EXPECTED))
def test_real_existing_subjects_marker_results_unchanged(key):
    tok = _real(key)
    assert (*_summary(tok), template.stop_ids(tok)) == REAL_EXPECTED[key]
    assert template.check(tok) == [] and template.system_rule(tok) == "marker"


def test_real_v4_jailbreak_restamp_by_character_span():
    """Every jailbreak item re-stamped on V4's render: the span is exactly the last user turn's
    content (character span, decoded), turn_end is ``<|Assistant|>``, the read tokens are the
    render's own tokens. 0 mismatches over the whole bank."""
    from wsbench.adapt.carry import restamp_read
    from wsbench.evals.jailbreak_recognition.judge import prefix_to_last_user

    tok = _real(V4.key)
    bank = json.loads(frozen_bank_path("jailbreak_recognition").read_text(encoding="utf-8"))
    bad = []
    for it in bank["items"]:
        msgs = prefix_to_last_user(it["messages"])
        ids = _ids(tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True,
                                           enable_thinking=False))  # fmt: skip
        r = restamp_read(tok, it["messages"])
        a, b = r["span"]
        content = msgs[-1]["content"]
        head = max(i for i in range(a) if tok.decode([ids[i]]) == USER)
        ok = (
            tok.decode(ids[r["turn_end"]]) == ASSISTANT
            # the rule skips leading whitespace-only tokens (two items open with "\n")
            and not tok.decode(ids[head + 1 : a]).strip()
            and tok.decode(ids[a:b]) == content.lstrip()
            and tok.decode(ids) == ref_encode(msgs)
            and r["turn_end"] == len(ids) - 2
            and all(tok.decode([ids[int(p)]]) == t for p, t in r["tokens"].items())
            and max(r["positions"]) == r["turn_end"]
        )
        if not ok:
            bad.append(it["id"])
    assert not bad, f"{len(bad)} jailbreak items mismatch: {bad[:5]}"


def test_real_v4_mcdm_prefill_by_character_span():
    from wsbench.produce.render import _chat

    tok = _real(V4.key)
    fam = "multi_concept_directed_modulation"
    bank = json.loads(frozen_bank_path(fam).read_text(encoding="utf-8"))
    sent = bank["target_sentence"]
    n = len(tok(sent, add_special_tokens=False)["input_ids"])
    bad = []
    for it in bank["items"]:
        msgs = [{"role": "user", "content": it["prompt"]}]
        ids = _chat(tok, msgs, prefill=sent)
        text = ref_encode(msgs) + sent
        if (
            tok.decode(ids[-n:]) != sent
            or tok.decode(ids[-n - 1]) != "</think>"
            or tok.decode(ids, skip_special_tokens=False) != text
        ):
            bad.append(it["name"])
    assert not bad, f"{len(bad)} mcdm items mismatch: {bad[:5]}"


# ---------------------------------------------------------------- arithmetic (D8)


def _arith_items(k: int = 6) -> tuple[dict, list[dict]]:
    raw = json.loads(frozen_bank_path("arithmetic_intermediates").read_text(encoding="utf-8"))
    items = copy.deepcopy(raw["items"][:k])
    assert {it["cell"]["pos"] for it in raw["items"]} == {-7, -8}
    return raw, items


def test_arith_cells_have_no_v4_counterpart_and_d8_reads_all_positions():
    """Qwen's -7 (two tokens past <|im_end|>) lands past the end of V4's render, which ends
    ``<|Assistant|></think>``: the re-anchor exits there. Under D8 the cell keeps its (depth-
    remapped) layer, loses its position, and records Qwen's."""
    from wsbench.adapt.run import _restamp_arith_cells

    _raw, items = _arith_items(40)
    tok = FAKES["v4"]()
    if any(it["cell"]["pos"] == -7 for it in items):
        with pytest.raises(SystemExit, match="outside the render"):
            _restamp_arith_cells(tok, copy.deepcopy(items))
    out, notes = _restamp_arith_cells(tok, copy.deepcopy(items), all_positions=True)
    assert all(it["cell"]["pos"] is None for it in out)
    assert [it["cell"]["pos_qwen"] for it in out] == [it["cell"]["pos"] for it in items]
    assert [it["cell"]["layer"] for it in out] == [it["cell"]["layer"] for it in items]
    assert "D8" in notes[0]
    # the other subjects' re-anchor is untouched (ChatML with Qwen's think tail: positions kept)
    same, _ = _restamp_arith_cells(FAKES["qwen"](), copy.deepcopy(items))
    assert [it["cell"]["pos"] for it in same] == [it["cell"]["pos"] for it in items]


def test_v4_freeze_path_keeps_arithmetic(monkeypatch):
    """``restamp_tokens`` (what freeze calls for a non-Qwen tokenizer) takes D8 from the Subject,
    so V4 arithmetic freezes instead of being reported blocked; ``_post_freeze`` snaps the cell
    layers into the lens band (rows <= 40)."""
    from wsbench.adapt import author, run

    monkeypatch.setattr(author, "tokenizer", lambda model: FAKES["v4"]())
    raw, items = _arith_items()
    out, _notes = run.restamp_tokens(V4.key, "arithmetic_intermediates", copy.deepcopy(items))
    assert len(out) == len(items) and all(it["cell"]["pos"] is None for it in out)
    header = {k: v for k, v in raw.items() if k != "items"}
    run._post_freeze("arithmetic_intermediates", copy.deepcopy(header), out, V4.n_layers,
                     V4.read_band)  # fmt: skip
    assert all(0 <= it["cell"]["layer"] <= 40 for it in out)


def test_v4_arith_bank_plans_and_judges_every_position(tmp_path, monkeypatch):
    """A bank with ``cell.pos`` None plans (every position, frozen_cell passed through) and the
    judge reads it under ``cells=all``; the frozen-cell judge refuses it with a pointer."""
    from conftest import native_args

    from wsbench import readplan
    from wsbench.evals.arithmetic_intermediates import judge
    from wsbench.evals.arithmetic_intermediates.prompts import PROMPT_VERSION
    from wsbench.judge_config import JudgeConfig, resolve

    raw = json.loads(frozen_bank_path("arithmetic_intermediates").read_text(encoding="utf-8"))
    for it in raw["items"]:
        it["cell"] = {**it["cell"], "pos": None, "pos_qwen": it["cell"]["pos"]}
    bank = tmp_path / "arith.json"
    bank.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("WSB_BANK_FILE_ARITHMETIC_INTERMEDIATES", str(bank))

    specs = readplan.plan("arithmetic_intermediates")
    assert len(specs) == len(raw["items"])
    assert all(s.positions == {"kind": "all_from_end"} for s in specs)
    assert all(s.extra["frozen_cell"]["pos"] is None for s in specs)

    from wsbench.banks import load_bank

    it = load_bank(bank)[1][0]
    rows = [{"id": it["id"], "layer": L, "pos": p, "samples": ["x"]}
            for L in (20, 40) for p in (-1, -2)]  # fmt: skip
    path = tmp_path / "r.jsonl"
    path.write_text("".join(json.dumps(x) + "\n" for x in rows))
    monkeypatch.setattr(judge, "run_calls", lambda calls, **kw: {})
    base = {
        "readouts": path,
        "out": tmp_path / "out",
        "judge": resolve(JudgeConfig(prompt_version=PROMPT_VERSION)),
        "layers": None,
        "items": [it["id"]],
        "limit": 0,
        "allow_missing": True,
        "concurrency": 1,
        "rpm": 1.0,
        "dry_run": False,
    }
    with pytest.raises(SystemExit):
        judge.run(native_args(**base))  # cells=frozen (the native default): no cell to read
    r = judge.run(native_args(**base, extra={"cells": "all"}))
    assert r.extras["n_rows_off_cell"] == 0 and r.counts["n_missing_cells"] == 0


# ---------------------------------------------------------------- author.tokenizer


def test_author_tokenizer_applies_chat_template_without_tokenizer_dir(monkeypatch):
    from wsbench.adapt import author

    calls = []

    class _Auto:
        @staticmethod
        def from_pretrained(name, **kw):
            calls.append((name, kw))
            return types.SimpleNamespace(chat_template="upstream")

    fake = types.ModuleType("transformers")
    fake.AutoTokenizer = _Auto
    monkeypatch.setitem(sys.modules, "transformers", fake)
    tok = author.tokenizer(V4.key)
    assert calls == [(V4.hf_id, {"revision": V4.revision, "trust_remote_code": False})]
    assert tok.chat_template == TEMPLATE
    calls.clear()
    assert author.tokenizer("qwen3.5-4b").chat_template == "upstream"  # no pinned template
