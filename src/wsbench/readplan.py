"""The read plan: for every item of every family, what to feed the model, how to render it,
which token positions to read, and at which layers. `wsbench plan` writes it as JSONL; `resolve`
turns a positions rule into token indices once a producer has tokenized the render."""

import json
import os
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from wsbench.banks import load_bank as load_bank_file
from wsbench.registry import BANK_ROOT_ENV, REPO_ROOT, bank_path

GRID = list(range(20, 61, 4))  # the benchmark's layer grid for Qwen3.6-27B (64 layers)
SIX = [20, 28, 36, 44, 52, 60]  # the association families' coarser grid
FIVE = [20, 36, 44, 52, 60]  # the in-house layers of the hallucination and jailbreak arms
ANSWER_STEM = "My one-word answer is:"  # basic_readout implicit items: prefilled assistant turn
SUMMARIZE_SUFFIX = "\n\nSummarize the preceding story in one sentence."

RENDERS: dict[str, str] = {
    "plain": "the text verbatim, no chat template, no special tokens",
    "chat": "Qwen chat template, enable_thinking=False (empty <think> block); the text is the "
    "user turn, `system` the system turn when the item carries one; read positions index the "
    "full render",
    "chat_context": "Qwen chat template over the item's `messages` (system + user), "
    "enable_thinking=False; read positions index the full render",
    "chat_prefill": "Qwen chat template, enable_thinking=False; the text is the user turn and "
    "`prefill` is appended verbatim as the start of the assistant turn",
    "chat_dm": "Qwen chat template; the prompt is the user turn and `assistant` is the "
    "teacher-forced assistant turn (the carrier sentence the model copies)",
    "chat_summarize": "Qwen chat template, enable_thinking=False, no system prompt; the user turn "
    "is the stimulus followed by `suffix`",
    "bare": "the text verbatim with nothing asked (a program, a scene), no chat template",
    "captured": "the exact captured token ids (`input_ids`) shipped with the bank; positions "
    "index them directly",
}


@dataclass(frozen=True)
class ReadSpec:
    """One item's read plan. ``positions`` is a rule (see ``resolve``); ``layers`` the layers to
    read; ``text`` / ``messages`` / ``prefill`` / ``suffix`` what to render under ``render``."""

    family: str
    id: str
    render: str
    positions: dict[str, Any]
    layers: list[int]
    text: str | None = None
    messages: list[dict[str, str]] | None = None
    system: str | None = None
    prefill: str | None = None
    suffix: str | None = None
    assistant: str | None = None
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def row(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, "", {}, [])}


# ---------------------------------------------------------------- positions rules
#
# kinds:
#   final_token                 the last token of the render
#   offset_from_end {k}         the token k from the end (k=1 is the last), reported as the
#                               negative index -k, the convention of the banks that use it
#   last_n {n}                  the last n tokens
#   all                         every token
#   all_from_end                every token, reported as negative offsets -n..-1 (the
#                               convention of the banks that count from the end)
#   positions {list}            explicit indices into the render
#   line_one_newline            the newline token that ends line one (the last newline)
#   last_newline                the last newline token anywhere (chat_prefill: inside the prefill)
#   from_token {token}          from the first token whose text is `token` through the end
#   from_last_sentence_start    from the first token of the final sentence of the last user
#                               turn through the end of the render
#   suffix_text {text}          the tokens whose joined text is `text` at the end of the render
#   suffix_text_then_tail       `suffix_text` plus every token after it (the chat tail)


def _hal_capture_rows() -> Path:
    """``$WSB_BANK_ROOT/hallucination.capture_rows.json`` for an adapted bank (an error if it is
    missing), else the frozen ``evals/hallucination/capture_rows.json``."""
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return REPO_ROOT / "evals/hallucination/capture_rows.json"
    base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
    path = base / "hallucination.capture_rows.json"
    if not path.exists():
        raise SystemExit(f"{BANK_ROOT_ENV}={root} has no hallucination capture rows ({path})")
    return path


def _clean(tok: str) -> str:
    return tok.replace("Ġ", " ").replace("▁", " ").replace("Ċ", "\n")


# Poetry renders for subjects that commit to a rhyme only with a format scaffold (adapt gate legs
# surface:fewshot / surface:prefill; gate_variant plain_fewshot / chat_prefill, porting.md).
POETRY_FEWSHOT = (
    "A rhyming couplet:\nThe cat lay sleeping on the mat,\nAnd dreamed it chased a little rat.\n\n"
    "A rhyming couplet:\nThe sun went down behind the hill,\n"
    "The evening air was calm and still.\n\n"
)
POETRY_PREFILL_USER = "Write a rhyming couplet."


def poetry_prefill(prompt: str) -> str:
    """Line one + the line-two stem (the couplet without its header), trailing space dropped."""
    return "\n".join(prompt.split("\n")[1:]).rstrip()


def resolve(rule: dict[str, Any], tokens: list[str]) -> list[int]:
    """Token indices a rule selects over ``tokens`` (the render's token strings, byte-level BPE
    display or plain). Every kind above is handled; unknown kinds raise."""
    n = len(tokens)
    kind = rule["kind"]
    if kind == "final_token":
        return [n - 1] if n else []
    if kind == "offset_from_end":
        k = int(rule["k"])
        return [-k] if 0 < k <= n else []
    if kind == "last_n":
        return list(range(max(0, n - int(rule["n"])), n))
    if kind == "all":
        return list(range(n))
    if kind == "all_from_end":
        return list(range(-n, 0))
    if kind == "positions":
        return [int(p) for p in rule["positions"] if 0 <= int(p) < n]
    if kind == "line_one_newline":
        # the last newline of the user content: in a chat render, before the closing turn marker
        ends = [i for i, t in enumerate(tokens) if t in TURN_END]
        stop = ends[-1] if ends else n
        nls = [i for i, t in enumerate(tokens[:stop]) if "\n" in _clean(t)]
        return [nls[-1]] if nls else []
    if kind == "last_newline":
        nls = [i for i, t in enumerate(tokens) if "\n" in _clean(t)]
        return [nls[-1]] if nls else []
    if kind == "from_token":
        want = rule["token"]
        hits = [i for i, t in enumerate(tokens) if _clean(t) == want or t == want]
        return list(range(hits[0], n)) if hits else []
    if kind == "from_last_sentence_start":
        return _from_last_sentence_start(tokens)
    if kind in ("suffix_text", "suffix_text_then_tail"):
        start = _suffix_start(tokens, rule["text"])
        if start is None:
            return []
        if kind == "suffix_text_then_tail":
            return list(range(start, n))
        end = _text_end(tokens, start, rule["text"])
        return list(range(start, end))
    raise ValueError(f"unknown positions rule {kind!r}")


# turn markers of the chat templates the banks are adapted to (ChatML / Qwen, Gemma-4, Gemma-2/3,
# Llama-3); the rules below find the user turn by these, never by one template's literals
TURN_START = {"<|im_start|>", "<|turn>", "<start_of_turn>", "<|start_header_id|>"}
TURN_END = {"<|im_end|>", "<turn|>", "<end_of_turn>", "<|eot_id|>", "<|end|>"}


def _user_turn(tokens: list[str]) -> tuple[int, int] | None:
    """(first content token, closing turn marker) of the LAST user turn, or None."""
    n = len(tokens)
    starts = [
        i
        for i, t in enumerate(tokens)
        if t in TURN_START and i + 1 < n and _clean(tokens[i + 1]).strip() == "user"
    ]
    if not starts:
        return None
    u0 = starts[-1] + 2  # past the marker and the role name
    while u0 < n and not _clean(tokens[u0]).strip():  # and the header's newline(s)
        u0 += 1
    u1 = next((i for i in range(u0, n) if tokens[i] in TURN_END), None)
    return None if u1 is None else (u0, u1)


def _from_last_sentence_start(tokens: list[str]) -> list[int]:
    n = len(tokens)
    turn = _user_turn(tokens)
    if turn is None:  # a chat render without recognisable turn markers: fail, never read it all
        raise ValueError("from_last_sentence_start: no user turn markers in the render")
    u0, u1 = turn
    body = list(range(u0, u1))
    if not body:
        return list(range(u1, n))
    i = body[-1] - 1
    while i > body[0]:
        if re.search(r"[.!?]\s*$", _clean(tokens[i])):
            break
        i -= 1
    start = i + 1 if i > body[0] else body[0]
    return list(range(start, n))


def _suffix_start(tokens: list[str], text: str) -> int | None:
    """Index where the joined token text last begins ``text`` (leading whitespace ignored)."""
    target = text.strip()
    for start in range(len(tokens) - 1, -1, -1):
        joined = "".join(_clean(t) for t in tokens[start:]).lstrip()
        if joined.startswith(target):
            return start
    return None


def _text_end(tokens: list[str], start: int, text: str) -> int:
    target = text.strip()
    acc = ""
    for i in range(start, len(tokens)):
        acc = (acc + _clean(tokens[i])).lstrip() if not acc else acc + _clean(tokens[i])
        if len(acc) >= len(target):
            return i + 1
    return len(tokens)


# ---------------------------------------------------------------- per-family plans


def _bank(family: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = bank_path(family)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):  # the plain-list banks already carry ids
        return {}, raw
    if raw["items"] and "name" not in raw["items"][0]:  # wrapped banks keyed on id
        return {k: v for k, v in raw.items() if k != "items"}, raw["items"]
    header, items = load_bank_file(path)
    return header, items


def _final_token_families(family: str, render: str) -> list[ReadSpec]:
    _h, items = _bank(family)
    out = []
    for it in items:
        rule = {"kind": "final_token"}
        spec = it.get("readout") or {}
        if spec.get("kind") in ("final_prompt_token", "last_word_token") and spec.get("offsets"):
            k = -int(spec["offsets"][0])
            rule = {"kind": "final_token"} if k == 1 else {"kind": "offset_from_end", "k": k}
        r = it.get("eval_render") or render
        if r == "chat":  # basic_readout's implicit items: the model's own favourite after the stem
            out.append(
                ReadSpec(
                    family,
                    it["id"],
                    "chat_prefill",
                    rule,
                    GRID,
                    text=it["prompt"],
                    prefill=ANSWER_STEM,
                )
            )
        else:
            out.append(ReadSpec(family, it["id"], r, rule, GRID, text=it["prompt"]))
    return out


BANK_LAYERS = {"buggy_code", "multi_concept_directed_modulation"}  # layers stored in the bank


def _subject_layers() -> int | None:
    """The adapted subject's block count (``$WSB_BANK_ROOT/report.json`` ``n_layers``), or None
    for the frozen banks (whose grids are Qwen3.6-27B layers out of 64)."""
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return None
    base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
    n = json.loads((base / "report.json").read_text()).get("n_layers")
    if not n:
        raise SystemExit(f"{base / 'report.json'} has no n_layers; re-run adapt freeze")
    return int(n)


def _subject_band() -> list[int]:
    """The subject's lens layers (``report.json`` ``read_band``), empty if it reads every layer."""
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return []
    base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
    return list(json.loads((base / "report.json").read_text()).get("read_band") or [])


def plan(family: str) -> list[ReadSpec]:
    """``_plan`` in the subject's own layers: under ``$WSB_BANK_ROOT`` every grid taken from the
    27B constants is remapped by depth (``round(L * n / 64)``, then snapped to ``read_band`` if the
    subject has one; duplicates dropped); layers an
    adapted bank stores itself (``BANK_LAYERS``) are already the subject's."""
    from dataclasses import replace

    specs = _plan(family)
    n = _subject_layers()
    if n is None or family in BANK_LAYERS:
        return specs
    from wsbench.adapt.subjects import remap_layers

    band = _subject_band()
    return [replace(s, layers=remap_layers([int(x) for x in s.layers], n, band)) for s in specs]


def _plan(family: str) -> list[ReadSpec]:
    """The read plan for one family, one ReadSpec per bank item."""
    if family in (
        "association",
        "basic_readout",
        "multihop",
        "multilingual",
        "typo",
        "basic_readout_mt",
        "multihop_mt",
        "multilingual_mt",
        "multilingual_multihop",
        "multilingual_typo",
        "typo_mt",
    ):
        return _final_token_families(family, "plain")
    if family == "poetry":
        from wsbench.capable.questions import CONTINUE

        _h, items = _bank(family)
        # an adapted item whose rhyme was committed in the chat render is read in that render
        # (the gate's own question); the frozen bank and plain commitments read the raw couplet
        out = []
        for it in items:
            # only an ADAPTED item's gate_variant picks its read render; a frozen item's
            # gate_variant records the 27B's gate and never the eval read (bank header)
            gv = it.get("gate_variant") if it.get("adapt") else None
            if gv == "chat_prefill":  # the couplet is the assistant's own (prefilled) text
                spec = ReadSpec(
                    family,
                    it["id"],
                    "chat_prefill",
                    {"kind": "last_newline"},
                    GRID,
                    text=POETRY_PREFILL_USER,
                    prefill=poetry_prefill(it["prompt"]),
                    note="the newline that ends line one, inside the prefill",
                )
            else:
                texts = {
                    "chat": f"{CONTINUE}\n\n{it['prompt']}",
                    "plain_fewshot": POETRY_FEWSHOT + it["prompt"],
                }
                spec = ReadSpec(
                    family,
                    it["id"],
                    "chat" if gv == "chat" else "plain",
                    {"kind": "line_one_newline"},
                    GRID,
                    text=texts.get(gv, it["prompt"]),
                    note="the newline that ends line one of the couplet",
                )
            out.append(spec)
        return out
    if family == "directed_modulation":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_dm",
                {"kind": "suffix_text", "text": it["assistant"]},
                GRID,
                text=it["prompt"],
                assistant=it["assistant"],
                note="every token of the teacher-forced carrier sentence",
            )
            for it in items
        ]
    if family == "user_modeling":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_context",
                {"kind": "from_last_sentence_start"},
                GRID,
                messages=it["messages"],
                note="the request sentence through the end of the render, template tokens included",
            )
            for it in items
        ]
    if family == "moral_rationale":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat",
                {"kind": "last_n", "n": 5},
                GRID,
                text=it["stimulus"],
                system=it.get("system"),  # the subject's one-word system turn (moral.variant)
                note="the last five positions of the render",
            )
            for it in items
        ]
    if family == "relational_multihop":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "bare",
                {"kind": "final_token"},
                GRID,
                text=it["stimulus"],
                note="the possessive blank that ends the cloze",
            )
            for it in items
        ]
    if family in ("conjunctive_association", "role_bound_association"):
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_summarize",
                {"kind": "suffix_text_then_tail", "text": SUMMARIZE_SUFFIX.strip()},
                SIX,
                text=it["stimulus"],
                suffix=SUMMARIZE_SUFFIX,
                note="the 19 suffix and chat-tail tokens; story positions are never "
                "read (docs/read_sites.md)",
            )
            for it in items
        ]
    if family == "brew_intermediates":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_prefill",
                {"kind": "positions", "positions": it["eval_positions"]},
                GRID,
                text=it["prompt"],
                prefill="Answer:",
                extra={"regions": it["regions"]},
                note="24 pinned cells: the three emission cells (the headline) plus the stir, "
                "start and question regions",
            )
            for it in items
        ]
    if family == "chain_intermediates":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat",
                {"kind": "from_token", "token": " What"},
                GRID,
                text=it["prompt"],
                note="the question span through the end of the render (opts=cells=all); the "
                "default judge reads only the render's final token, the assistant onset",
            )
            for it in items
        ]
    if family == "arithmetic_intermediates":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat",
                {"kind": "all_from_end"},
                [56, 60],
                text=it["prompt"],
                extra={"variant": it["variant"], "frozen_cell": it["cell"]},
                note="every position at layers 56 and 60 (opts=cells=all, the regime of record); "
                "frozen_cell is the pre-registered (layer, negative offset) the default judge "
                "reads",
            )
            for it in items
        ]
    if family == "buggy_code":
        header, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "bare",
                {"kind": "final_token"},
                [int(header["read_cells"][it["lang_group"]]["layer"])],
                text=it["code"],
                note="the end of the file; layer 60 for python, 56 otherwise",
            )
            for it in items
        ]
    if family == "multi_concept_directed_modulation":
        header, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_prefill",
                {"kind": "last_n", "n": int(header.get("last_n", 12))},  # the sentence's own count
                [int(x) for x in header["layers"]],
                text=it["prompt"],
                prefill=header["target_sentence"],
                note="every token of the prefilled target sentence",
            )
            for it in items
        ]
    if family == "hallucination":
        # an adapted bank's rows are the subject's own ids (off-policy ids must never be read)
        rows = json.loads(_hal_capture_rows().read_text())
        return [
            ReadSpec(
                family,
                r["id"],
                "captured",
                {"kind": "positions", "positions": r["read_positions"]},
                FIVE,
                extra={"input_ids": r["input_ids"], "prompt_len": r["prompt_len"]},
                note="punctuation and newline sites inside the model's own response, at the "
                "five in-house layers",
            )
            for r in rows
        ]
    if family == "jailbreak_recognition":
        from wsbench.evals.jailbreak_recognition.judge import grid_positions, prefix_to_last_user

        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat_context",
                {"kind": "positions", "positions": grid_positions(it["read"])},
                FIVE,
                messages=prefix_to_last_user(it["messages"]),
                extra={"n_tokens": it["read"]["n_tokens"]},
                note="every token of the last user turn, first content token through its "
                "<|im_end|> (read.span); the bank's n_tokens also closes an empty assistant "
                "turn, two tokens past the generation prompt and past every read position",
            )
            for it in items
        ]
    if family == "agentic_misalignment":
        _h, items = _bank(family)
        return [
            ReadSpec(
                family,
                it["id"],
                "chat",
                {"kind": "all"},
                [*GRID, 63],
                text=it["text"],
                system=it.get("system"),
                note="every prompt position of the chat render (system + user); the pinned "
                "rollout is not read",
            )
            for it in items
        ]
    if family == "jlens_concept_pr":
        from wsbench.evals.jlens_concept_pr.judge import bank_dir

        d = bank_dir()  # the adapted bank's own manifest under WSB_BANK_ROOT, never the 27B's
        m = json.loads((d / "manifest.json").read_text())
        rows = {}
        if (d / "items.json").exists():  # an adapted bank ships the subject's exact rollout ids
            rows = {r["label"]: r for r in json.loads((d / "items.json").read_text())}
        return [
            ReadSpec(
                family,
                p["label"],
                "captured",
                {"kind": "positions", "positions": p["eval_positions"]},
                GRID,
                extra={"n_pos": p["n_pos"], "source_family": p["family"]}
                | (
                    {
                        "input_ids": rows[p["label"]]["input_ids"],
                        "prompt_len": rows[p["label"]]["prompt_len"],
                    }
                    if p["label"] in rows
                    else {}
                ),
                note="the subject's own rollout ids (items.json)"
                if rows
                else "the text is not shipped; recapture from the source repo's items",
            )
            for p in m["prompts"]
        ]
    raise KeyError(f"no read plan for {family!r}")


def families() -> list[str]:
    """Every family with a bank; under ``$WSB_BANK_ROOT`` only those the adapted root actually
    has (an ooc family with no bank is skipped, not an error, when planning everything)."""
    names = sorted(
        p.name
        for p in (REPO_ROOT / "evals").iterdir()
        if (p / "items.json").exists() or (p / "manifest.json").exists()
    )
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return names
    base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
    return [
        f for f in names if (base / f"{f}.json").exists() or (base / f / "manifest.json").exists()
    ]


def write(specs: Iterable[ReadSpec], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for s in specs:
            fh.write(json.dumps(s.row(), ensure_ascii=False) + "\n")
            n += 1
    return n
