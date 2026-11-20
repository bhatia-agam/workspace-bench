"""plan 0070: the prompt-only control never reads a reply (``baselines.prompt_cut``)."""

import json
import sys
import types
from typing import ClassVar

import pytest

from wsbench.baselines import prompt_cut as pc
from wsbench.baselines import prompt_only_opus as po


class CharTok:
    """One token per character, special markers as single tokens; ``style`` picks the template:
    ``qwen`` (end marker, empty think block on the generation prompt), ``glm`` (no end marker,
    no think block) or ``gemma`` (a BOS before the first turn)."""

    SPECIALS: ClassVar[dict[str, list[str]]] = {
        "qwen": ["<|im_start|>", "<|im_end|>", "<think>", "</think>"],
        "glm": ["[gMASK]", "<|user|>", "<|assistant|>", "<|system|>"],
        "gemma": ["<bos>", "<start_of_turn>", "<end_of_turn>"],
    }

    def __init__(self, style: str = "qwen", template: bool = True):
        self.style = style
        self.chat_template = "x" if template else None
        self.specials = self.SPECIALS[style]
        self.vocab: dict[str, int] = {s: i for i, s in enumerate(self.specials)}

    def _id(self, piece: str) -> int:
        return self.vocab.setdefault(piece, len(self.vocab))

    def encode(self, text: str) -> list[int]:
        out, i = [], 0
        while i < len(text):
            for s in self.specials:
                if text.startswith(s, i):
                    out.append(self._id(s))
                    i += len(s)
                    break
            else:
                out.append(self._id(text[i]))
                i += 1
        return out

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": self.encode(text)}

    def decode(self, ids, **_):
        inv = {v: k for k, v in self.vocab.items()}
        return "".join(inv[i] for i in ids)

    def convert_ids_to_tokens(self, ids):
        inv = {v: k for k, v in self.vocab.items()}
        return [inv[i] for i in ids]

    def render(self, messages, add_generation_prompt):
        s = self.style
        if s == "qwen":
            text = ""
            last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
            for i, m in enumerate(messages):
                body = m["content"]
                if m["role"] == "assistant" and i > last_user:
                    body = "<think>\n\n</think>\n\n" + body
                text += f"<|im_start|>{m['role']}\n{body}<|im_end|>\n"
            if add_generation_prompt:
                text += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        elif s == "glm":
            text = "[gMASK]" + "".join(f"<|{m['role']}|>\n{m['content']}" for m in messages)
            if add_generation_prompt:
                text += "<|assistant|>\n"
        else:
            role = {"user": "user", "assistant": "model", "system": "user"}
            text = "<bos>" + "".join(
                f"<start_of_turn>{role[m['role']]}\n{m['content']}<end_of_turn>\n" for m in messages
            )
            if add_generation_prompt:
                text += "<start_of_turn>model\n"
        return text

    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=True, **_):
        text = self.render(messages, add_generation_prompt)
        return self.encode(text) if tokenize else text


def chat(tok, messages, gen=True, prefill=""):
    return tok.apply_chat_template(messages, add_generation_prompt=gen) + tok.encode(prefill)


U = [{"role": "user", "content": "What is the capital of France?"}]


@pytest.mark.parametrize("style", ["qwen", "glm", "gemma"])
def test_marks_and_final_turn_prefill_cut_at_generation_prompt(style):
    tok = CharTok(style)
    m = pc.turn_marks(tok)
    ids = chat(tok, U, prefill="My one-word answer is:")
    assert pc.reply_tokens(ids, m, tok) == len("My one-word answer is:")
    out = pc.prompt_only_ids(ids, len(ids) - 1, m, tok)
    assert out == chat(tok, U)  # the prompt through the generation prompt, nothing of the reply
    pc.assert_no_reply(out, m, tok)
    # a cut inside the reply ends at the same place
    assert pc.prompt_only_ids(ids, len(ids) - 5, m, tok) == chat(tok, U)


@pytest.mark.parametrize("style", ["qwen", "glm", "gemma"])
def test_no_reply_is_byte_identical(style):
    tok = CharTok(style)
    m = pc.turn_marks(tok)
    ids = chat(tok, U)
    for last in (5, len(ids) - 3, len(ids) - 1):  # a site in the prompt or the generation prompt
        assert pc.prompt_only_ids(ids, last, m, tok) == ids[: last + 1]


@pytest.mark.parametrize("style", ["qwen", "glm", "gemma"])
def test_earlier_assistant_turn_is_dropped(style):
    tok = CharTok(style)
    m = pc.turn_marks(tok)
    msgs = [
        *U,
        {"role": "assistant", "content": "Paris, of course."},
        {"role": "user", "content": "And Spain?"},
    ]
    ids = chat(tok, msgs)
    last = len(ids) - len(m.gen) - 3  # inside the last user turn
    out = pc.prompt_only_ids(ids, last, m, tok)
    text = tok.decode(out)
    assert "Paris" not in text and "France" in text
    assert text.endswith(tok.decode(ids[last - 2 : last + 1]))
    assert pc.reply_tokens(out, m, tok) == 0
    with pytest.raises(AssertionError, match="reply tokens"):
        pc.assert_no_reply(ids[: last + 1], m, tok)


def test_no_template_fails_loudly():
    tok = CharTok("qwen", template=False)

    def raise_(*_a, **_k):
        raise ValueError(
            "Cannot use chat template functions because tokenizer.chat_template is not set"
        )

    tok.apply_chat_template = raise_
    with pytest.raises(SystemExit, match="apply_chat_template failed"):
        pc.turn_marks(tok)


def test_template_method_without_chat_template_attr_is_probed():
    """Kimi-K3's remote-code tokenizer has chat_template=None but overrides apply_chat_template."""
    tok = CharTok("qwen", template=False)
    m = pc.turn_marks(tok)
    ids = chat(tok, U, prefill="My one-word answer is:")
    assert pc.prompt_only_ids(ids, len(ids) - 1, m, tok) == chat(tok, U)


def test_control_token_inside_reply_fails_loudly():
    """A template with no end marker (GLM) puts a later system turn inside the assistant text."""
    tok = CharTok("glm")
    m = pc.turn_marks(tok)
    m = pc.TurnMarks(
        m.header, m.think, m.end, m.user, frozenset(tok.vocab[s] for s in tok.specials)
    )
    msgs = [*U, {"role": "assistant", "content": "Paris."}, {"role": "system", "content": "SYS"},
            {"role": "user", "content": "And Spain?"}]  # fmt: skip
    ids = chat(tok, msgs)
    with pytest.raises(SystemExit, match="ambiguous"):
        pc.prompt_only_ids(ids, len(ids) - 1, m, tok)


def test_orphan_end_marker_moves_out_of_the_user_header():
    """OLMo / Muse: a default system turn precedes the first user turn, so the naive common
    suffix put the previous turn's end marker into the user header and left it orphaned."""
    tok = CharTok("qwen")
    orig = tok.render
    tok.render = lambda msgs, gen: "<|im_start|>system\nSYS<|im_end|>\n" + orig(msgs, gen)
    m = pc.turn_marks(tok)
    assert tok.decode(m.user) == "<|im_start|>user\n" and tok.decode(m.end) == "<|im_end|>\n"
    msgs = [
        *U,
        {"role": "assistant", "content": "Paris."},
        {"role": "user", "content": "And Spain?"},
    ]
    ids = chat(tok, msgs)
    text = tok.decode(pc.prompt_only_ids(ids, len(ids) - 1, m, tok))
    assert "<|im_end|>\n<|im_end|>" not in text and "Paris" not in text


def test_template_that_rewrites_history_fails_loudly():
    tok = CharTok("qwen")
    orig = tok.render
    tok.render = lambda msgs, gen: ("SYS\n" if len(msgs) > 1 else "") + orig(msgs, gen)
    with pytest.raises(SystemExit, match="prefix"):
        pc.turn_marks(tok)


def _fake_transformers(monkeypatch, tok):
    mod = types.ModuleType("transformers")
    mod.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda *_a, **_k: tok)
    monkeypatch.setitem(sys.modules, "transformers", mod)


def test_build_regression_reply_free(tmp_path, monkeypatch):
    """The families whose last read site lies inside a prefilled / dictated reply
    (basic_readout_st's
    implicit items, directed_modulation, multi-concept DM) build reply-free prefixes; a family read
    in the prompt only (association) is byte-identical to the old cut."""
    tok = CharTok("qwen")
    _fake_transformers(monkeypatch, tok)
    from wsbench import readplan
    from wsbench.produce.producer import _positions
    from wsbench.produce.render import render

    fams = [
        "basic_readout_st",
        "directed_modulation",
        "multi_concept_directed_modulation",
        "association",
    ]
    po.build(tmp_path, fams, limit=4)
    rows = [json.loads(x) for x in (tmp_path / "prompts.jsonl").read_text().splitlines()]
    assert {r["prompt_cut"] for r in rows} == {po.PROMPT_CUT}
    m = pc.turn_marks(tok)
    n_cut = 0
    for r in rows:
        ids = tok.encode(r["prefix"])
        assert pc.reply_tokens(ids, m, tok) == 0, r["id"]
        spec = next(s for s in readplan.plan(r["family"]) if s.id == r["id"])
        rr = render(spec, tok)
        last = po.last_site(_positions(spec.positions, rr.tokens), len(rr)) % len(rr)
        old = tok.decode(rr.ids[: last + 1])
        if r["family"] == "association":
            assert r["prefix"] == old
        elif r["prefix"] != old:
            n_cut += 1
            assert r["prefix"].endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert n_cut >= 8  # every DM / MCDM row and the implicit basic_readout_st rows in scope
    # the reader's question holds no reply text, its quoted token included (review of #350: v1
    # quoted the read-site token, e.g. the prefilled stem's ':')
    for r in rows:
        spec = next(s for s in readplan.plan(r["family"]) if s.id == r["id"])
        q = po.reader_prompt(r)
        assert r["token"] == tok.decode(tok.encode(r["prefix"])[-1:])
        assert f"{r['token']!r}" in q
        shown = q.split("<prompt>\n")[1].split("\n</prompt>")[0]
        assert shown == r["prefix"]
        assert pc.reply_tokens(tok.encode(shown), m, tok) == 0, r["id"]
        if r["family"] != "association":
            assert r["token"] == "\n\n" or r["prefix"].endswith(r["token"])
            assert r["site_token"] != r["token"]  # the cell is still placed at the read site


def test_stale_prompts_are_refused(tmp_path):
    (tmp_path / "prompts.jsonl").write_text(
        json.dumps({"family": "f", "id": "a", "prefix": "x"}) + "\n"
    )
    with pytest.raises(SystemExit, match="rebuild"):
        po.write_readouts(tmp_path)


def test_answers_to_an_older_prompt_are_never_served(tmp_path, monkeypatch):
    """Review of #350: answers are keyed by prompt_sha, so a rebuilt prompts.jsonl (e.g. the old
    reply-holding cut) never reuses, skips or freezes an answer to the older question."""
    import asyncio
    from types import SimpleNamespace

    row = {"family": "moral_rationale", "id": "a", "prefix": "NEW", "token": "W", "pos": 1,
           "n_tokens": 2, "prompt_cut": po.PROMPT_CUT}  # fmt: skip
    old = {**row, "prefix": "OLD with reply", "token": ":"}
    (tmp_path / "prompts.jsonl").write_text(json.dumps(row) + "\n")
    (tmp_path / "answers").mkdir()
    stale = {"family": "moral_rationale", "id": "a", "answer": "stale", "error": "",
             "prompt_sha": po.prompt_shas([old])[("moral_rationale", "a")]}  # fmt: skip
    (tmp_path / "answers" / "draw0.jsonl").write_text(json.dumps(stale) + "\n")
    st = po.write_readouts(tmp_path)
    assert st["moral_rationale"]["failed"] == ["a"]  # the stale answer is not served
    asked: list[str] = []

    class Msgs:
        async def create(self, **kw):
            asked.append(kw["messages"][0]["content"])
            usage = SimpleNamespace(output_tokens=1, input_tokens=1)
            text = [SimpleNamespace(type="text", text="fresh")]
            return SimpleNamespace(content=text, stop_reason="end_turn", usage=usage)

    monkeypatch.setattr(po, "client", lambda: SimpleNamespace(messages=Msgs()))
    asyncio.run(po._ask(tmp_path, 2, None))
    assert asked == [po.reader_prompt(row)]  # re-asked on the current question
    po.write_readouts(tmp_path)
    cell = json.loads((tmp_path / "readouts/moral_rationale.jsonl").read_text())
    assert cell["samples"] == ["fresh"]


def test_freeze_refuses_a_run_without_the_current_cut(tmp_path):
    from wsbench.baselines import prompt_only as pof

    run = tmp_path / "run" / "association"
    run.mkdir(parents=True)
    (run / "results.json").write_text("{}")
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"protocol": pof.PO_OPUS, "families": {}}))
    with pytest.raises(ValueError, match="prompt_cut"):
        pof.freeze(tmp_path / "run", tmp_path / "dst.json", source=cfg)


@pytest.mark.parametrize("stamp", [None, po.PROMPT_CUT])
def test_freeze_refuses_the_legacy_sonnet5_fallback_run(tmp_path, stamp):
    """Re-review of #350: re-freezing the 2026-10-31 Sonnet 5 fallback run would restore the
    reply-holding jailbreak / introspection floors; it is refused stamped or not."""
    from wsbench.baselines import prompt_only as pof

    (tmp_path / "run" / "association").mkdir(parents=True)
    (tmp_path / "run" / "association" / "results.json").write_text("{}")
    cfg = {"protocol": pof.PO_FALLBACK_SONNET5, "families": {}}
    if stamp:
        cfg["prompt_cut"] = stamp
    (tmp_path / "cfg.json").write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="frozen history"):
        pof.freeze(tmp_path / "run", tmp_path / "dst.json", source=tmp_path / "cfg.json")


def test_freeze_requires_the_cut_on_any_po_opus_protocol(tmp_path):
    from wsbench.baselines import prompt_only as pof

    (tmp_path / "run" / "association").mkdir(parents=True)
    (tmp_path / "run" / "association" / "results.json").write_text("{}")
    (tmp_path / "cfg.json").write_text(json.dumps({"protocol": "po-opus-v1+other", "families": {}}))
    with pytest.raises(ValueError, match="prompt_cut"):
        pof.freeze(tmp_path / "run", tmp_path / "dst.json", source=tmp_path / "cfg.json")


# ------------------------------------------------- review of the port (2026-11-17)


class MergeTok(CharTok):
    """A BPE-like ChatML tokenizer: two newlines in a row are ONE token (as under OLMo-3 and
    Qwen3-8B), and the template neither strips content nor adds a think block. A reply that
    starts with a newline therefore merges with the header's newline, so the full header
    ``<|im_start|>assistant\\n`` is not in the turn's ids. CharTok cannot show this."""

    def __init__(self):
        super().__init__("qwen")

    def encode(self, text: str) -> list[int]:
        out, i = [], 0
        while i < len(text):
            piece = next((s for s in [*self.specials, "\n\n"] if text.startswith(s, i)), text[i])
            out.append(self._id(piece))
            i += len(piece)
        return out

    def render(self, messages, add_generation_prompt):
        text = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
        return text + ("<|im_start|>assistant\n" if add_generation_prompt else "")


def _merge_marks(tok):
    m = pc.turn_marks(tok)
    return pc.TurnMarks(
        m.header,
        m.think,
        m.end,
        m.user,
        frozenset(tok.vocab[s] for s in tok.specials),
        m.header_core,
        m.user_core,
    )


@pytest.mark.parametrize("reply", ["\nParis SECRET.", "\n\nParis SECRET.", "\n\n\nParis SECRET."])
def test_reply_starting_with_a_newline_is_cut_when_it_merges_with_the_header(reply):
    tok = MergeTok()
    m = _merge_marks(tok)
    assert tok.decode(m.header) == "<|im_start|>assistant\n"
    assert tok.decode(m.hcore) == "<|im_start|>assistant"
    msgs = [*U, {"role": "assistant", "content": reply}, {"role": "user", "content": "And Spain?"}]
    ids = chat(tok, msgs)
    # the premise: the turn's full header is not in the ids (only the generation prompt's is)
    assert pc._find(ids, m.header) == len(ids) - len(m.header)
    out = pc.prompt_only_ids(ids, len(ids) - 1, m, tok)
    text = tok.decode(out)
    assert "SECRET" not in text and "Paris" not in text
    assert "France" in text and text.endswith("And Spain?<|im_end|>\n<|im_start|>assistant\n")
    pc.assert_no_reply(out, m, tok)
    with pytest.raises(AssertionError, match="reply tokens"):
        pc.assert_no_reply(ids, m, tok)
    # a site inside that reply ends at the generation prompt
    turn = pc.assistant_turns(ids, m)[0]
    assert pc.prompt_only_ids(ids, turn.content + 2, m, tok) == chat(tok, U)


def test_final_turn_prefill_starting_with_a_newline_is_cut():
    tok = MergeTok()
    m = _merge_marks(tok)
    ids = tok.encode(tok.render(U, True) + "\nMy one-word answer is:")
    assert pc._find(ids, m.header) < 0
    assert pc.prompt_only_ids(ids, len(ids) - 1, m, tok) == chat(tok, U)


def test_assert_no_reply_does_not_share_the_token_detector_blind_spot():
    """Marks without the header core search the FULL header, as the first version did: the
    token-level detector misses the merged turn, the decoded-text check still raises."""
    tok = MergeTok()
    m = _merge_marks(tok)
    blind = pc.TurnMarks(m.header, m.think, m.end, m.user, m.specials)
    msgs = [
        *U,
        {"role": "assistant", "content": "\nParis SECRET."},
        {"role": "user", "content": "And Spain?"},
    ]
    ids = chat(tok, msgs)
    assert pc.reply_tokens(ids, blind, tok) == 0  # the blind spot
    assert pc.reply_text(ids, blind, tok) == "Paris SECRET."
    with pytest.raises(AssertionError, match="decoded-text check"):
        pc.assert_no_reply(ids, blind, tok)
    assert pc.reply_text(chat(tok, U), blind, tok) == ""


@pytest.mark.parametrize("make", [lambda: CharTok("qwen"), MergeTok])
def test_site_on_the_first_end_marker_token_cuts_back_to_the_generation_prompt(make):
    """The end marker is two tokens (``<|im_end|>`` + newline); a read site on the first one is
    the end of that reply, not an ambiguous turn boundary."""
    tok = make()
    m = _merge_marks(tok)  # the marks with the fake tokenizer's control tokens as specials
    assert len(m.end) == 2
    msgs = [*U, {"role": "assistant", "content": "Paris."}, {"role": "user", "content": "And?"}]
    ids = chat(tok, msgs)
    turn = pc.assistant_turns(ids, m)[0]
    site = turn.stop  # the <|im_end|> token that closes the reply
    assert tok.decode(ids[site : site + 1]) == "<|im_end|>"
    out = pc.prompt_only_ids(ids, site, m, tok)
    assert out == chat(tok, U)
    pc.assert_no_reply(out, m, tok)
    # an empty assistant turn closed there holds no reply: unchanged
    empty = chat(tok, [*U, {"role": "assistant", "content": ""}, {"role": "user", "content": "x"}])
    t0 = pc.assistant_turns(empty, m)[0]
    assert t0.stop == t0.content
    assert pc.prompt_only_ids(empty, t0.stop, m, tok) == empty[: t0.stop + 1]


@pytest.mark.parametrize("style", ["qwen", "glm", "gemma"])
def test_whitespace_only_assistant_turn_is_a_reply(style):
    """Decision (review of #350): an assistant turn that holds only whitespace is still a reply
    and is dropped like any other; an EMPTY turn (no content token) is not."""
    tok = CharTok(style)
    m = pc.turn_marks(tok)
    msgs = [*U, {"role": "assistant", "content": " \n"}, {"role": "user", "content": "And Spain?"}]
    ids = chat(tok, msgs)
    assert pc.reply_tokens(ids, m, tok) == 2
    last = len(ids) - len(m.gen) - 3  # inside the last user turn
    text = tok.decode(pc.prompt_only_ids(ids, last, m, tok))
    assert tok.decode(m.hcore) not in text and "France" in text and "And Sp" in text
    assert pc.reply_tokens(chat(tok, U), m, tok) == 0  # the generation prompt alone: no reply


def test_fallback_stale_prompts_name_the_dir_they_came_from(tmp_path):
    """Several ``src=`` dirs: the refusal names the prompts file that holds the stale rows (the
    last dir with that family), not simply the last dir."""
    row = {"id": "a", "prefix": "P", "token": "?", "pos": 0, "n_tokens": 1}
    old, new = tmp_path / "old", tmp_path / "new"
    for d, fam, stamp in ((old, "moral_rationale", None), (new, "association", po.PROMPT_CUT)):
        d.mkdir()
        r = {**row, "family": fam, **({"prompt_cut": stamp} if stamp else {})}
        (d / "prompts.jsonl").write_text(json.dumps(r) + "\n")
    with pytest.raises(SystemExit) as exc:
        po.write_fallback_readouts(tmp_path / "fb", [old, new])
    msg = str(exc.value)
    assert str(old / "prompts.jsonl") in msg and "moral_rationale" in msg
    assert str(new / "prompts.jsonl") not in msg and "rebuild" in msg
    # a later dir that re-builds the family on the current cut replaces the stale rows
    r = {**row, "family": "moral_rationale", "prompt_cut": po.PROMPT_CUT}
    (new / "prompts.jsonl").write_text(json.dumps(r) + "\n")
    po.write_fallback_readouts(tmp_path / "fb", [old, new])


def test_adapted_poetry_chat_prefill_prefix_stops_at_the_generation_prompt():
    """Pins ``adapt.poetry.read_prefix`` (plan 0070 3b): a ``chat_prefill`` item's prompt-only
    input is the chat prompt through the generation prompt and holds nothing of line one, so it
    is the SAME for every chat_prefill item (the Opus text-leak gate cannot tell them apart; an
    open decision recorded in the plan). ``plain`` / ``plain_fewshot`` items still show line one."""
    from wsbench.adapt import poetry
    from wsbench.readplan import POETRY_PREFILL_USER

    tok = CharTok("qwen")
    m = pc.turn_marks(tok)
    a = {"prompt": "A rhyming couplet:\nHe saw a carrot and had to grab it,\n"}
    b = {"prompt": "A rhyming couplet:\nThe silver moon rose over the hill,\n"}
    gen = tok.render([{"role": "user", "content": POETRY_PREFILL_USER}], True)
    for it in (a, b):
        prefix, token = poetry.read_prefix({**it, "gate_variant": "chat_prefill"}, tok)
        assert prefix == gen and prefix.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
        assert "carrot" not in prefix and "silver moon" not in prefix
        assert token == "\n"  # the prefix's own last token (CharTok: one newline)
        assert pc.reply_tokens(tok.encode(prefix), m, tok) == 0
        pc.assert_no_reply(tok.encode(prefix), m, tok)
    plain, _ = poetry.read_prefix({**a, "gate_variant": "plain"}, tok)
    fewshot, _ = poetry.read_prefix({**a, "gate_variant": "plain_fewshot"}, tok)
    assert "carrot" in plain and "carrot" in fewshot
    with pytest.raises(SystemExit, match="tokenizer"):
        poetry.read_prefix({**a, "gate_variant": "chat_prefill"})
