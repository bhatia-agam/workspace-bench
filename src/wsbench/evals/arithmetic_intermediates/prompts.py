"""Prompts of the arithmetic-intermediates free-recall judge: the chained-intermediates judge
(source repo ``judge_free_modal.py``) with its task sentence changed to a bare arithmetic
expression; printed verbatim in the family README."""

from wsbench import mc
from wsbench.digest import (
    SUMMARY_NOTE_ABSTRACTIVE_NO_RARE,
    SUMMARY_NOTE_NO_RARE,
)
from wsbench.llm import schema_block

# cells=frozen: one call per cell. 2026-10-30 (plan 0036): neutral readout wording
# (mc.READOUT_PHRASE), the shared token-list note rendered from the spec (flat type "numbers",
# decision Q4), and the "dominated by one value" rule without the "tight cluster" clause (Q4: a
# flat list of numbers singles out none of them).
CALL_VERSION = "arith-free-2026-10-30"  # keys every call (unchanged by final r1)
# final r1 (2026-10-31), the instrument stamp: integer golds match EXACTLY at any magnitude
# (rel5pct credited off-by-one / off-by-few / rounded numbers); the numbers digest keys are
# the union of the per-layer digests' keys (digest.NUMBERS_UNION_FAMILIES)
RULE_VERSION = "+exact-int+keys-union"
# summary mode (+generic-r7): ONE generic judge prompt that treats every lens alike
# (SYSTEM_SUMMARY below). It names every number the readout uses in a calculation, the numbers it
# operates on as well as the results ("87 + 83 = 170" for an intermediate 87); code only verifies
# the judge's values (written in the readouts, equal to a digest key). Summary calls are keyed
# CALL_VERSION_SUMMARY; native runs keep CALL_VERSION + RULE_VERSION (judge.NATIVE_PROMPT_VERSION).
# The earlier first-number consensus rule (+cons-r3 / +cons-r4) is retired: it could fire only on
# lenses with >= 3 samples per activation.
SUMMARY_RULE_VERSION = "+generic-r7"
CALL_VERSION_SUMMARY = CALL_VERSION + SUMMARY_RULE_VERSION
PROMPT_VERSION = CALL_VERSION + RULE_VERSION + SUMMARY_RULE_VERSION
# cells=all: one call per (item, layer) over every position of that layer (Camila, 2026-09-23 06:14:
# "for user modeling and arithmetic let's just batch it - feed it everything at once!"). Same
# instructions as PROMPT_VERSION, different packaging, so its own version tag. 2026-10-30: the
# entry headers no longer carry the read-site token (Camila: "Remove the token labels").
CALL_VERSION_BATCH = "arith-free-batched-2026-10-30"
PROMPT_VERSION_BATCH = CALL_VERSION_BATCH + RULE_VERSION
MAX_VALUES = 3  # the prompt caps the ranked list at three; the schema cannot (no maxItems)

# the registry reads these two (EvalSpec.flat_types / multi_select), so the token note the judge
# sees here and the one the digest note renders (digest.token_note_of) are the same text
FLAT_TYPES: tuple[str, ...] = ("numbers",)
MULTI_SELECT = False
TOKEN_NOTE = mc.token_note(FLAT_TYPES, multi_select=MULTI_SELECT)
# arithmetic's own condition on top of the shared note (plan 0032 §2.7.4 "add, never relax"):
# digits are not a split word, and assembling them would rebuild the prompt's operands
NO_ASSEMBLY = (
    "A number is never assembled from separate tokens: digits on one list or at adjacent "
    "positions (2, 7, 1) are not the number 271."
)

_INTRO = f"""You are reading {mc.READOUT_PHRASE}, written as text or as lists of tokens."""
_TASK = """The model is silently evaluating a short arithmetic expression: two or three operations
on given numbers, answered with no chain of thought. You do NOT get to see the expression — only
the readout{s}."""
_BAG = """- A bag of loose numerals with no arithmetic around them counts only when it is dominated
  by ONE value (several of its tokens write the same number, e.g. 九 | nine | 9): list that
  value. A bag or list of several different numbers singles out none of them, whatever their
  order or rank."""
_NOTE = f"""Token lists. {TOKEN_NOTE} {NO_ASSEMBLY}"""

SYSTEM = f"""{_INTRO} {_TASK.format(s="")}

The readout may be free text, bullet points, or a bag of loose tokens, possibly in several
languages (Chinese numerals like 十四 mean fourteen). It is often vague, generic, or about
something else entirely, and it frequently contains numbers that are not results of anything.

Your job: name the number(s) that this readout presents as a COMPUTED VALUE — a result, an
intermediate, a total, a "the answer is X". Rank them, most clearly a computed result first,
at most three. Decimals and negative numbers are values too; report them exactly as written.

Rules:
- Do NOT list numbers that appear as operands, quantities, labels, list indices, years, counts
  of items, or parts of unrelated prose. Only numbers the readout presents as something that was
  worked out.
- If the readout states arithmetic with both operands and a result ("16 - 2 = 14"), list the
  RESULT (14), not the operands.
{_BAG}
- If the readout presents no number as a computed value, set states_value false and return an
  empty list. That is a normal and common answer — do not invent one.
- Never do any arithmetic of your own. You do not know the task, so you cannot know what the
  right answer is; only report what the text itself puts forward.

{_NOTE}"""

# summary mode, numbers digest (plan 0022 Part B): the digest's number keys bound what can pass;
# the judge sees whole evidence samples and may name up to ten values, kept only when a key
# writes them. A plain, generic ask: no consensus rule, no operand/result rule (a restated
# operand takes a digest key only when no other number is left, digest.collapse ``operands=``),
# no bag rule (the flat-list void is code's, digest.number_flood) and no list of numbers to leave
# out beyond one generic "label, count or date" line.
MAX_VALUES_SUMMARY = 10  # the judge cannot see the keys; the digest's number keys bound it
SYSTEM_SUMMARY = f"""{_INTRO} {_TASK.format(s="")}

The readout may be free text, bullet points, or lists of tokens, possibly in several languages
(Chinese numerals like 十四 mean fourteen). It is often vague or about something else, and it may
contain numbers that are not results of anything.

Your job: name every number this readout uses in a calculation: the numbers it operates on
as well as the results it gets (a result, an intermediate, a total, an answer). Rank them, most
prominent first, at most ten. Report each number exactly as written; decimals and negative
numbers are values too.

- Leave out numbers that only label, count or date things, or that belong to unrelated prose.
- If no number takes part in a calculation, set states_value false and return an empty list.
- Never do arithmetic of your own: you do not know the expression, so report only what the text
  itself puts forward.

{_NOTE}"""


def system_summary(n_keys: int) -> str:
    """final r1: a multi-layer digest holds up to five number keys PER LAYER, so the judge may
    name as many values as there are keys (never fewer than ten): a gold key is never cut by the
    cap. ``n_keys <= MAX_VALUES_SUMMARY`` is :data:`SYSTEM_SUMMARY` unchanged."""
    if n_keys <= MAX_VALUES_SUMMARY:
        return SYSTEM_SUMMARY
    return SYSTEM_SUMMARY.replace("at most ten.", f"at most {n_keys}.")


USER = (
    "Readout:\n<<<\n{readout}\n>>>\n\n"
    "Which number(s) does this readout present as a computed value?"
)

SYSTEM_BATCH = f"""{_INTRO} {_TASK.format(s="s")}

You are given several readouts at once, one per position of the prompt that was read, as
numbered entries "[k] pos=<offset from the end of the prompt>:" followed by that entry's readout
(a bag of loose tokens is written as "tokens: ..."). Judge every entry on its own; the entries do
not explain each other, and an entry's header is not part of its readout. The one exception is
the token-list note below: tokens of adjacent entries may be joined only to spell one word split
across them, never to assemble a number.

A readout may be free text, bullet points, or a bag of loose tokens, possibly in several
languages (Chinese numerals like 十四 mean fourteen). It is often vague, generic, or about
something else entirely, and it frequently contains numbers that are not results of anything.

Your job, for EACH entry: name the number(s) that its readout presents as a COMPUTED VALUE — a
result, an intermediate, a total, a "the answer is X". Rank them, most clearly a computed result
first, at most three. Decimals and negative numbers are values too; report them exactly as written.

Rules, applied to every entry on its own:
- Do NOT list numbers that appear as operands, quantities, labels, list indices, years, counts
  of items, or parts of unrelated prose. Only numbers the readout presents as something that was
  worked out.
- If the readout states arithmetic with both operands and a result ("16 - 2 = 14"), list the
  RESULT (14), not the operands.
{_BAG}
- If a readout presents no number as a computed value, return an empty list for that entry. That
  is a normal and common answer — do not invent one.
- Never do any arithmetic of your own. You do not know the task, so you cannot know what the
  right answer is; only report what each text itself puts forward.
- Answer with exactly one result per entry, carrying the entry's k, in the order given; the
  quote is the shortest verbatim span of THAT entry supporting its top value (empty if none).

{_NOTE}"""

USER_BATCH = (
    "Readouts, one per read position:\n\n{entries}\n\n"
    "For each entry, which number(s) does its readout present as a computed value?"
)

# summary mode (plan 0020): the per-cell SYSTEM judges one digest per item; the USER's
# "Readout:" header becomes the digest note (digest.summary_note)
USER_SUMMARY = (
    "{summary_note}\n\nReadout:\n<<<\n{readout}\n>>>\n\n"
    "Which numbers does this readout use in a calculation, as inputs or as results?"
)
# the task TYPE the digest's `task` variant is told (EvalSpec.task_note; never the expression,
# its values or its answer: no numeral and no number word, test_arith_task_note_has_no_numerals)
TASK_NOTE = (
    "the model was silently evaluating a short arithmetic expression (a few operations on given "
    "numbers) and answering with only the final number, with no written working"
)

PROMPTS: dict[str, str] = {
    "SYSTEM": SYSTEM,
    "SYSTEM_SUMMARY": SYSTEM_SUMMARY,
    "USER": USER,
    "SYSTEM_BATCH": SYSTEM_BATCH,
    "USER_BATCH": USER_BATCH,
    "USER_SUMMARY": USER_SUMMARY,
    # the numbers digest runs summ_rare=0, so the note without the rare clause (plan 0022)
    "SUMMARY_NOTE_NO_RARE": SUMMARY_NOTE_NO_RARE,
    "SUMMARY_NOTE_ABSTRACTIVE_NO_RARE": SUMMARY_NOTE_ABSTRACTIVE_NO_RARE,
    # the token note every arithmetic prompt shows (and digest.summary_note appends for tokens)
    "TOKEN_NOTE": TOKEN_NOTE,
    "TASK_NOTE": TASK_NOTE,
}

SCHEMA = schema_block(
    "arith_free",
    {
        "states_value": {"type": "boolean"},
        "values": {
            "type": "array",
            "items": {"type": "number"},
            "description": "ranked, most clearly a computed result first, at most three",
        },
        "basis": {"type": "string", "enum": ["arithmetic", "stated_result", "numeral_bag", "none"]},
        "quote": {
            "type": "string",
            "description": "shortest verbatim span supporting the top value",
        },
    },
    ["states_value", "values", "basis", "quote"],
)
SCHEMA_SUMMARY = schema_block(
    "arith_free",
    {
        **SCHEMA["schema"]["properties"],
        "values": {
            "type": "array",
            "items": {"type": "number"},
            "description": "ranked, most clearly presented first, at most ten",
        },
    },
    ["states_value", "values", "basis", "quote"],
)


_VALUES = {
    "type": "array",
    "items": {"type": "number"},
    "description": "ranked, most clearly a computed result first, at most three",
}
_BASIS = {"type": "string", "enum": ["arithmetic", "stated_result", "numeral_bag", "none"]}

# one object per entry: the per-cell answer minus states_value (an empty list says it), plus k
SCHEMA_BATCH = schema_block(
    "arith_free_batch",
    {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["k", "values", "basis", "quote"],
                "properties": {
                    "k": {"type": "integer", "description": "the entry number [k]"},
                    "values": _VALUES,
                    "basis": _BASIS,
                    "quote": {
                        "type": "string",
                        "description": (
                            "shortest verbatim span of the entry supporting its top value"
                        ),
                    },
                },
            },
        }
    },
    ["entries"],
)


def render_user(readout: str) -> str:
    return USER.replace("{readout}", readout.strip())


def render_user_summary(note: str, summary: str) -> str:
    """Summary mode: the digest note, then the item's digest as the lens output."""
    return USER_SUMMARY.replace("{summary_note}", note).replace("{readout}", summary.strip())


def render_entry(k: int, pos: int, text: str, *, bag: bool) -> str:
    """``[k] pos=<offset>: <readout>``; a token lens's bag is prefixed ``tokens:``. No read-site
    token text: the headers would spell out the expression the judge must not see (Camila:
    "Remove the token labels")."""
    head = f"[{k}] pos={pos}:"
    body = text.strip()
    return f"{head} tokens: {body}" if bag else f"{head} {body}"


def render_batch_user(entries: list[tuple[int, int, str]], *, bag: bool) -> str:
    """The cells=all user message: every non-empty position of one (item, layer), in position
    order, as numbered entries ``(k, pos, text)`` separated by blank lines."""
    block = "\n\n".join(render_entry(k, pos, text, bag=bag) for k, pos, text in entries)
    return USER_BATCH.replace("{entries}", block)
