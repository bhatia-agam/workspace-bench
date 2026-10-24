"""brew read cells in any subject's coordinates: regions from the subject's own chat_prefill render
(line spans; emission cells by template role), cross-checked against the Qwen cells char-mapped."""

from typing import Any

from wsbench.produce.render import _chat

PREFILL = "Answer:"
LINES = {"stir": "You stir", "start": "The potion starts out", "question": "What colour"}
ROLES = ("assistant", "model")


def char_spans(tok: Any, ids: list[int]) -> tuple[str, list[tuple[int, int]]]:
    """The decoded render and each token's char span (prefix decodes must nest)."""
    text, spans = "", []
    for k in range(len(ids)):
        nxt = tok.decode(ids[: k + 1], clean_up_tokenization_spaces=False)
        if not nxt.startswith(text):
            raise ValueError(f"decode of ids[:{k + 1}] does not extend ids[:{k}]")
        spans.append((len(text), len(nxt)))
        text = nxt
    return text, spans


def derive(tok: Any, prompt: str) -> tuple[dict[int, str], dict[str, Any]]:
    """{token index: region} in the subject's chat_prefill render, plus what each cell decodes to.
    Raises ValueError when a region can't be located exactly (never guesses)."""
    msgs = [{"role": "user", "content": prompt}]
    gen, ids = _chat(tok, msgs), _chat(tok, msgs, PREFILL)
    if ids[: len(gen)] != gen:
        raise ValueError("prefill render does not extend the chat render")
    text, sp = char_spans(tok, ids)
    pc = text.rfind(prompt)
    if pc < 0 or not text.endswith(PREFILL):
        raise ValueError("prompt / prefill not found in the render")
    regions: dict[int, str] = {}
    for region, head in LINES.items():
        line = next(ln for ln in prompt.splitlines() if ln.startswith(head))
        c0 = text.rfind(line, pc)
        for i, (s, e) in enumerate(sp):
            if e > c0 and s < c0 + len(line) and e > s:
                regions[i] = region
    tok_text = [text[s:e] for s, e in sp]
    if tok_text[-1] != ":":
        raise ValueError(f"last token is {tok_text[-1]!r}, not the prefill colon")
    pe = pc + len(prompt)
    tail = [k for k in range(len(gen)) if sp[k][0] >= pe]
    roles = [k for k in tail if tok_text[k].strip() in ROLES]
    if not roles:
        raise ValueError("no assistant role token in the template tail")
    think, role = len(gen) - 1, roles[-1]
    # Qwen: 'assistant' '\n' <think> .. '</think>' '\n\n' -> emit_asst = the '\n' after the role.
    # No reasoning block (ChatML OLMo, Gemma): the header's newline IS the last template token,
    # so emit_think keeps it and emit_asst takes the role token (wsbench_mp's rule).
    asst = role + 1 if role + 1 < think and not tok_text[role + 1].strip() else role
    if not asst < think:
        raise ValueError(f"emit_asst ({asst}) and emit_think ({think}) collide")
    for k, r in ((asst, "emit_asst"), (think, "emit_think"), (len(ids) - 1, "emit_colon")):
        if k in regions:
            raise ValueError(f"{r} lands on a prompt-line token")
        regions[k] = r
    info = {"n_tokens": len(ids), "tokens": {str(k): tok_text[k] for k in sorted(regions)},
            "has_think": "</think>" in "".join(tok_text[k] for k in tail)}  # fmt: skip
    return dict(sorted(regions.items())), info


def qwen_crosscheck(tok: Any, qtok: Any, prompt: str, q_regions: dict[str, str],
                    regions: dict[int, str]) -> list[str]:  # fmt: skip
    """Map every Qwen prompt/prefill cell to the subject token holding its last char; each must
    land on a subject cell of the same region. Returns the disagreements (empty = consistent)."""
    msgs = [{"role": "user", "content": prompt}]
    q_text, q_sp = char_spans(qtok, _chat(qtok, msgs, PREFILL))
    s_text, s_sp = char_spans(tok, _chat(tok, msgs, PREFILL))
    qc, sc = q_text.rfind(prompt), s_text.rfind(prompt)
    bad = []
    for p, region in ((int(k), v) for k, v in q_regions.items()):
        if region.startswith("emit_") and region != "emit_colon":
            continue  # template cells: by role, checked in derive
        a, b = q_sp[p]
        tail = len(s_text) - (len(q_text) - b)
        target = tail if region == "emit_colon" else sc + (b - qc)
        s = next(i for i, (x, y) in enumerate(s_sp) if x < target <= y)
        if regions.get(s) != region:
            bad.append(f"qwen {p} {region} {q_text[a:b]!r} -> subject {s} {regions.get(s)}")
    return bad


def port_items(tok: Any, items: list[dict], qtok: Any | None = None) -> tuple[list[dict], dict]:
    """Re-stamp ``eval_positions`` / ``regions`` in the subject's coordinates (Qwen's kept under
    ``qwen``). Items whose cells can't be derived exactly are dropped and counted."""
    out, dropped, mismatches, n_cells = [], [], [], 0
    for it in items:
        try:
            regions, info = derive(tok, it["prompt"])
        except ValueError as e:
            dropped.append(f"{it.get('name') or it.get('id')}: {e}")
            continue
        if qtok is not None and it.get("regions"):
            bad = qwen_crosscheck(tok, qtok, it["prompt"], it["regions"], regions)
            mismatches += [f"{it.get('name')}: {b}" for b in bad]
        n_cells += len(regions)
        qwen = {k: it[k] for k in ("eval_positions", "regions") if k in it}
        cells = {str(k): v for k, v in regions.items()}
        out.append(
            {**it, "eval_positions": sorted(regions), "regions": cells, "qwen": qwen, "port": info}
        )
    return out, {"dropped": dropped, "qwen_mismatches": mismatches, "n_cells": n_cells}
