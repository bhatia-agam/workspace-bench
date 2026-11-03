"""The subject's chat-template markers, read off its own render (no template's literals in code):
a one-turn conversation with a sentinel user message, rendered with the generation prompt, gives
the token that opens a user turn, the one that closes it, and the generation-prompt tail."""

from typing import Any

SENTINEL = "ZQXSENTINELXQZ"
SYS_SENTINEL = "ZQXSYSTEMXQZ"
REPLY_SENTINEL = "ZQXREPLYXQZ"
# turn openers that name the role themselves (no separate role token): GLM's <|user|>,
# DeepSeek-V4's <|User|> spelled with fullwidth bars (U+FF5C). ChatML / Gemma / Kimi spell the
# role as its own token after the opener ("<|im_start|>", "user").
ROLE_MARKERS = ("<|user|>", "<\uff5cUser\uff5c>")


def markers(tok: Any) -> dict[str, Any]:
    out = tok.apply_chat_template([{"role": "user", "content": SENTINEL}], tokenize=True,
                                  add_generation_prompt=True, enable_thinking=False)  # fmt: skip
    ids = list(out["input_ids"] if hasattr(out, "keys") else out)
    toks = [tok.decode([i], skip_special_tokens=False) for i in ids]
    text, acc, s0, s1 = "".join(toks), 0, None, None
    at = text.index(SENTINEL)
    for i, t in enumerate(toks):  # token span of the sentinel
        if s0 is None and acc + len(t) > at:
            s0 = i
        acc += len(t)
        if s0 is not None and acc >= at + len(SENTINEL):
            s1 = i
            break
    if s0 is None or s1 is None:
        raise ValueError("template: sentinel not found in the render")
    role = next(i for i in range(s0 - 1, -1, -1) if toks[i].strip() in ("user", *ROLE_MARKERS))
    start = role if toks[role].strip() in ROLE_MARKERS else role - 1  # GLM / V4: role-named
    return {
        "turn_start_id": ids[start], "turn_start": toks[start],
        "turn_end_id": ids[s1 + 1], "turn_end": toks[s1 + 1],
        "header_len": s0 - start,  # marker + role + newline(s) before the content
        "gen_tail": toks[s1 + 2 :],  # what follows the closing marker (generation prompt)
    }  # fmt: skip


def bos_prefix(tok: Any) -> list[int]:
    """Token ids a raw (non-chat) render must start with: the special tokens the subject's own
    chat render opens with before its first role marker, when the tokenizer does not add them by
    itself. Gemma-4: [<bos>] (without it the model loops: "26 is 26 is"; Gemma audit, 0/698 plain
    legs passed); GLM-5.3: [[gMASK], <sop>]. Qwen, OLMo, Kimi (the render opens with a role
    marker): [] — their renders are unchanged."""
    out = tok.apply_chat_template([{"role": "user", "content": SENTINEL}], tokenize=True,
                                  add_generation_prompt=True, enable_thinking=False)  # fmt: skip
    ids = list(out["input_ids"] if hasattr(out, "keys") else out)
    special = set(getattr(tok, "all_special_ids", []) or [])
    special |= {int(i) for i in getattr(tok, "added_tokens_decoder", {}) or {}}
    start = markers(tok)["turn_start_id"]
    lead: list[int] = []
    for i in ids:
        text = tok.decode([i], skip_special_tokens=False)
        if i == start or i not in special or "system" in text or "user" in text:
            break
        lead.append(i)
    plain = tok("x", add_special_tokens=True)["input_ids"]
    return [] if not lead or plain[: len(lead)] == lead else lead


def stop_ids(tok: Any, gen_eos: Any = None) -> list[int]:
    """Every id that ends a reply: the tokenizer's eos, the generation config's eos list, and the
    template's own turn-closing marker."""
    ids = {tok.eos_token_id, markers(tok)["turn_end_id"]}
    for e in gen_eos if isinstance(gen_eos, list) else [gen_eos]:
        ids.add(e)
    return sorted(i for i in ids if i is not None)


OPEN_THINK = ("<think>", "<|channel>thought", "<|think|>")  # an unclosed reasoning block


def check(tok: Any) -> list[str]:
    """Step-0 render check (SKILL.md): with ``enable_thinking=False`` the generation prompt must not
    leave a reasoning block open, the markers must be derivable, and a system turn must render.
    Returns the problems (empty = the template is safe to gate with)."""
    problems = []
    try:
        m = markers(tok)
    except (ValueError, StopIteration, IndexError) as e:
        return [f"turn markers not derivable from the render: {e!r}"]
    tail = "".join(m["gen_tail"])
    for o in OPEN_THINK:
        if o in tail and tail.rfind(o) > max(tail.rfind("</think>"), tail.rfind("<channel|>")):
            problems.append(f"generation prompt leaves a reasoning block open: {tail!r}")
    try:
        sys_user = [{"role": "system", "content": SYS_SENTINEL}, {"role": "user", "content": "U"}]
        text = tok.apply_chat_template(sys_user, tokenize=False, add_generation_prompt=True,
                                       enable_thinking=False)  # fmt: skip
    except Exception as e:
        problems.append(f"template rejects a system turn ({type(e).__name__}); moral/agentic "
                        "asks with a system prompt need it folded into the user turn")  # fmt: skip
    else:
        if isinstance(text, str) and SYS_SENTINEL not in text:
            problems.append("template drops the system turn's content")
    return problems


def system_rule(tok: Any) -> str:
    """How the subject renders a system turn ahead of the first user turn: ``"marker"`` = inside
    its own role-marked turn (ChatML ``<|im_start|>system``, Gemma, GLM, Kimi); ``"bare"`` = the
    content alone between the BOS and the first user marker, no role marker and no closing token
    (DeepSeek-V4: ``encode_messages`` renders system as ``"{content}"``). Under ``"bare"`` no
    token separates the system text from the user turn, so a read anchored on a system-turn
    marker has none to anchor on; user-turn anchors (``markers``) are unaffected."""
    text = tok.apply_chat_template([{"role": "system", "content": SYS_SENTINEL}, {"role": "user",
                                   "content": SENTINEL}], tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)  # fmt: skip
    at = text.index(SYS_SENTINEL) + len(SYS_SENTINEL)
    bare = text.startswith(markers(tok)["turn_start"].strip(), at) and "system" not in text[:at]
    return "bare" if bare else "marker"


def followup_tail(tok: Any, messages: Any, followup: Any) -> str:
    """The template's own text after an assistant reply to ``messages``, through the follow-up
    turns and the generation prompt (plan 0060 D10): what closes the reply turn (Qwen
    ``<|im_end|>\n``, Gemma ``<end_of_turn>\n``) and opens the next user turn, rendered from the
    full conversation with a sentinel in place of the reply. Appended to the first turn's own
    render plus the reply, it keeps that render a token-exact prefix: a template that re-renders a
    past assistant turn differently (Qwen drops the empty think block of a past turn) cannot
    change the tokens the lens reads."""
    conv = [*messages, {"role": "assistant", "content": REPLY_SENTINEL}, *followup]
    text = tok.apply_chat_template(conv, tokenize=False, add_generation_prompt=True,
                                   enable_thinking=False)  # fmt: skip
    if REPLY_SENTINEL not in text:
        raise ValueError("template: the assistant reply is not rendered in a follow-up")
    return text[text.index(REPLY_SENTINEL) + len(REPLY_SENTINEL) :]
