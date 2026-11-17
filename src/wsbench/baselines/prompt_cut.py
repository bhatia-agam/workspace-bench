"""The prompt/reply boundary of a rendered read: a prompt-only reader never sees a reply
(plan 0070). Assistant turns are found in token ids, from markers probed off the subject's
own chat template."""

from dataclasses import dataclass
from typing import Any

_PROBE_USER, _PROBE_REPLY, _PROBE_NEXT = "Probe question one", "Probe reply text", "Probe two"


@dataclass(frozen=True)
class TurnMarks:
    """Token markers of a chat template: ``header`` opens an assistant turn, ``think`` is the
    fixed rest of the generation prompt (Qwen: the empty think block; may be empty), ``end``
    closes an assistant turn's content (may be empty) and ``user`` opens a user turn.

    ``header_core`` / ``user_core`` are the headers without their trailing whitespace tokens
    (Qwen: ``<|im_start|>assistant`` of ``<|im_start|>assistant\n``). Turns are FOUND by the
    core: a BPE tokenizer merges the header's newline with a reply (or user text) that starts
    with one (``\n`` + ``\n`` -> one ``\n\n`` token under OLMo-3 / Qwen3-8B, whose templates do
    not strip content), so the full header is not in the ids of such a turn. Empty = the header
    itself (no trailing whitespace token)."""

    header: tuple[int, ...]
    think: tuple[int, ...]
    end: tuple[int, ...]
    user: tuple[int, ...]
    specials: frozenset[int] = frozenset()  # control / added token ids of the tokenizer
    header_core: tuple[int, ...] = ()
    user_core: tuple[int, ...] = ()

    @property
    def gen(self) -> tuple[int, ...]:
        return self.header + self.think

    @property
    def hcore(self) -> tuple[int, ...]:
        return self.header_core or self.header

    @property
    def ucore(self) -> tuple[int, ...]:
        return self.user_core or self.user


def _ids(tok: Any, messages: list[dict[str, str]], gen: bool) -> list[int]:
    out = tok.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=gen, enable_thinking=False
    )
    return [int(i) for i in (out["input_ids"] if hasattr(out, "keys") else out)]


def _find(
    seq: list[int] | tuple[int, ...], sub: tuple[int, ...] | list[int], start: int = 0
) -> int:
    sub = list(sub)
    n = len(sub)
    for i in range(start, len(seq) - n + 1):
        if list(seq[i : i + n]) == sub:
            return i
    return -1


def _fail(why: str) -> SystemExit:
    return SystemExit(
        f"prompt_cut: cannot find the assistant turn markers of this chat template ({why})"
    )


def turn_marks(tok: Any) -> TurnMarks:
    """Probe ``tok``'s chat template (thinking off, as every chat render is built) for its turn
    markers; a template whose renders are not prefixes of each other exits loudly."""
    u = [{"role": "user", "content": _PROBE_USER}]
    ua = [*u, {"role": "assistant", "content": _PROBE_REPLY}]
    try:  # no `chat_template` check: a remote-code tokenizer (Kimi-K3) overrides the method
        p0, pg = _ids(tok, u, False), _ids(tok, u, True)
        three = _ids(tok, [*ua, {"role": "user", "content": _PROBE_NEXT}], True)
    except Exception as exc:
        raise _fail(f"apply_chat_template failed: {type(exc).__name__}: {exc}"[:300]) from exc
    if pg[: len(p0)] != p0 or three[: len(p0)] != p0:
        raise _fail("the one-turn render is not a prefix of the longer renders")
    gen = pg[len(p0) :]
    reply = tok(_PROBE_REPLY, add_special_tokens=False)["input_ids"]
    at = _find(three, reply, len(p0))
    if at < 0:
        raise _fail("the probe reply is not tokenized on its own inside the template")
    header = three[len(p0) : at]
    if not header or gen[: len(header)] != header:
        raise _fail("the earlier assistant turn's header is not the generation prompt's start")
    think = gen[len(header) :]
    nxt = tok(_PROBE_NEXT, add_special_tokens=False)["input_ids"]
    at2 = _find(three, nxt, at + len(reply))
    if at2 < 0 or three[len(three) - len(gen) :] != gen:
        raise _fail("the second user turn or the closing generation prompt is not found")
    between = three[at + len(reply) : at2]  # the assistant turn's end + the next user header
    q = tok(_PROBE_USER, add_special_tokens=False)["input_ids"]
    aq = _find(p0, q)
    if aq < 0:
        raise _fail("the probe question is not tokenized on its own inside the template")
    # the user header: the longest common suffix of what precedes each user turn's text
    pre, k = p0[:aq], 0
    while (
        k < min(len(pre), len(between)) and pre[len(pre) - 1 - k] == between[len(between) - 1 - k]
    ):
        k += 1
    if not k:
        raise _fail("the two user turns share no opening tokens")
    user, end = between[len(between) - k :], between[: len(between) - k]
    # the common suffix can reach into the previous turn's closing tokens when the probe's user
    # turn follows a default system turn (OLMo, Muse): those belong to `end`, not the header
    close = p0[aq + len(q) :]
    if close and user[: len(close)] == close and len(user) > len(close):
        user, end = user[len(close) :], end + close
    return TurnMarks(
        tuple(header),
        tuple(think),
        tuple(end),
        tuple(user),
        _specials(tok),
        _core(header, tok),
        _core(user, tok),
    )


def _text(tok: Any, ids: Any) -> str:
    return str(tok.decode(list(ids), skip_special_tokens=False, clean_up_tokenization_spaces=False))


def _core(header: list[int], tok: Any) -> tuple[int, ...]:
    """``header`` without its trailing whitespace-only tokens (never emptied)."""
    n = len(header)
    while n > 1 and not _text(tok, header[n - 1 : n]).strip():
        n -= 1
    return tuple(header[:n])


def _specials(tok: Any) -> frozenset[int]:
    ids = set(getattr(tok, "all_special_ids", None) or [])
    ids |= {int(i) for i in (getattr(tok, "added_tokens_decoder", None) or {})}
    return frozenset(ids)


@dataclass(frozen=True)
class Turn:
    """One assistant turn in a render: ``start`` = its header, ``content`` = the first token after
    the header (and after the fixed think block when it follows), ``stop`` = one past its last
    content token, ``close`` = one past its end marker (the next turn's start, or the render
    end)."""

    start: int
    content: int
    stop: int
    close: int


def _tail_prefix(ids: list[int], lo: int, hi: int, marker: tuple[int, ...]) -> int:
    """The length of the longest PROPER prefix of ``marker`` that ``ids[lo:hi]`` ends with."""
    for k in range(min(len(marker) - 1, hi - lo), 0, -1):
        if list(ids[hi - k : hi]) == list(marker[:k]):
            return k
    return 0


def assistant_turns(ids: list[int], m: TurnMarks) -> list[Turn]:
    """Every assistant turn of ``ids`` (a full render or a cut prefix of one). A turn starts at
    the header's core (:class:`TurnMarks`); when the header's trailing whitespace token does not
    follow it (merged with reply text that starts with whitespace), the content starts right
    after the core, so the merged token is reply content."""
    out = []
    core, ucore = m.hcore, m.ucore
    rest = m.header[len(core) :]
    i = _find(ids, core)
    while i >= 0:
        c = i + len(core)
        if list(ids[c : c + len(rest)]) == list(rest):
            c += len(rest)
            if m.think and list(ids[c : c + len(m.think)]) == list(m.think):
                c += len(m.think)
            elif m.think and list(m.think[: len(ids) - c]) == list(ids[c:]):
                c = len(ids)  # cut inside the fixed think block
        elif list(rest[: len(ids) - c]) == list(ids[c:]):
            c = len(ids)  # cut inside the header
        nexts = [j for j in (_find(ids, core, c), _find(ids, ucore, c)) if j >= 0]
        nxt = min(nexts) if nexts else len(ids)
        e = _find(ids[:nxt], m.end, c) if m.end else -1
        stop = e if e >= 0 else nxt
        close = (e + len(m.end)) if e >= 0 else nxt
        if e < 0 and m.end and nxt == len(ids):
            # the cut ends on the first token(s) of a multi-token end marker (a read site on
            # ``<|im_end|>`` of ``<|im_end|>\n``): the reply ends there, the turn is not closed
            stop -= _tail_prefix(ids, c, nxt, m.end)
        if any(t in m.specials for t in ids[c:stop]):
            # a control token inside reply text means another turn (a system / tool turn under
            # a template with no end marker) sits there: refuse rather than over- or under-cut
            raise SystemExit(
                "prompt_cut: an assistant turn's text holds a control token "
                f"({ids[c:stop][:12]}...): the turn boundary is ambiguous under this template"
            )
        out.append(Turn(i, c, stop, max(close, stop)))
        i = _find(ids, core, max(c, close))
    return out


def has_content(ids: list[int], t: Turn, tok: Any = None) -> bool:
    """True when the turn holds reply text: ANY content token, whitespace included (decision at
    the 2026-11-17 review of #350: a whitespace-only assistant turn is still a reply the subject
    was shown, and a whitespace token after the header can be the merged start of one; no row of
    the registered banks has such a turn). ``tok`` is unused, kept for callers."""
    return t.stop > t.content


def reply_tokens(ids: list[int], m: TurnMarks, tok: Any) -> int:
    """How many reply-content tokens ``ids`` holds (0 = prompt only)."""
    return sum(t.stop - t.content for t in assistant_turns(ids, m) if has_content(ids, t, tok))


def prompt_only_ids(ids: list[int], last: int, m: TurnMarks, tok: Any) -> list[int]:
    """``ids`` through ``last`` with no reply in it. Unchanged when no assistant turn before the cut
    holds text; else every such turn is dropped whole and, when ``last`` lies inside one, the
    prefix ends at the generation prompt (assistant header + fixed think block) that opens it."""
    cut = list(ids[: last + 1])
    turns = [t for t in assistant_turns(cut, m) if has_content(cut, t, tok)]
    if not turns:
        return cut
    out: list[int] = []
    pos = 0
    for t in turns:
        out += cut[pos : t.start]
        if t.close >= len(cut):  # the cut ends inside this turn (or at its very end)
            out += list(m.gen)
            pos = len(cut)
            break
        pos = t.close
    out += cut[pos:]
    assert reply_tokens(out, m, tok) == 0, "prompt_only_ids left reply text"
    return out


def reply_text(ids: list[int], m: TurnMarks, tok: Any) -> str:
    """The first assistant-reply text in ``ids``, found in the DECODED text (``""`` = none): what
    follows each assistant header string (the header core's text, e.g. ``<|im_start|>assistant``)
    up to the end marker, the next user or assistant header or the end, minus the fixed think
    block. Independent of :func:`assistant_turns` on purpose: a tokenization that hides a turn
    from the token-level search (a merged header token) cannot hide it here."""
    text = _text(tok, ids)
    head = _text(tok, m.hcore).strip()
    if not head:
        return ""
    stops = [x for x in (_text(tok, m.end).strip(), _text(tok, m.ucore).strip(), head) if x]
    think = _text(tok, m.think).strip()
    at = text.find(head)
    while at >= 0:
        a = at + len(head)
        found = [j for j in (text.find(x, a) for x in stops) if j >= 0]
        b = min(found) if found else len(text)
        seg = text[a:b].strip()
        if think and seg.startswith(think):
            seg = seg[len(think) :].strip()
        elif think and think.startswith(seg):
            seg = ""  # the cut ends inside the fixed think block
        if seg:
            return seg
        at = text.find(head, b)
    return ""


def assert_no_reply(ids: list[int], m: TurnMarks, tok: Any, where: str = "") -> None:
    """Raise when ``ids`` hold any reply text (Camila 2026-11-04: the control NEVER reads a
    reply). Two detectors that share no code path: the token-level turns the cut itself uses
    (:func:`reply_tokens`) and the decoded text (:func:`reply_text`)."""
    n = reply_tokens(ids, m, tok)
    if n:
        raise AssertionError(f"prompt-only input holds {n} reply tokens {where}".rstrip())
    seg = reply_text(ids, m, tok)
    if seg:
        raise AssertionError(
            f"prompt-only input holds reply text {seg[:60]!r} after an assistant header "
            f"(decoded-text check) {where}".rstrip()
        )
