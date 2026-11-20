"""Prompts of the nyt_connections judge (plan 0062); printed verbatim in the family README.

Summary mode (the default): ``SYSTEM_MC`` / ``USER_MC`` per slot on the puzzle's digest (also the
partner null and the word-masked ablation). ``USER_CONT``: the continuation floor (the slot's four
member words as the only evidence). ``NATIVE_MC`` / ``USER_NATIVE``: the native diagnostic path
(``opts=aggregate=native``) on the puzzle's raw readout lines."""

from wsbench import mc
from wsbench.llm import schema_block

PROMPT_VERSION = "nyt-mc-2026-11-02"
FLAT_TYPES: tuple[str, ...] = ()
MULTI_SELECT = False
TOKEN_NOTE = mc.token_note(FLAT_TYPES, multi_select=MULTI_SELECT)

_INTRO = (
    "You are reading "
    + mc.READOUT_PHRASE
    + """, recorded while the model read a word-grouping
puzzle: 16 words to be sorted into 4 groups of 4 words that share a connection (a category, a
phrase the words complete, wordplay, hidden words, and so on). The model had not answered yet. You
do NOT see the puzzle, its words or the answer."""
)
_TASK = """You are given the readouts and a numbered list of candidate connections. Each candidate
is a connection that one group of the puzzle's words could share. Pick the ONE candidate that the
readouts point to: a connection, category or grouping the readouts state that expresses that
candidate more clearly than any other candidate on the list."""
_RULES = (
    """Rules:
- A candidate is pointed to by readouts that name its connection or a close paraphrase of it, or
  that group words under it.
- """
    + TOKEN_NOTE
    + """
- If no candidate is pointed to, or two or more candidates are about equally supported, pick the
  last option, "cannot tell from the readout". That is a normal answer.
- Never solve the puzzle yourself and never guess."""
)
QUOTE_DIGEST = """- Quote the shortest span, copied from inside ONE readout line, that shows your
  pick."""
QUOTE_NATIVE = """- Quote the shortest span from the readouts, copied from inside ONE readout
  sample (one line under a [L<layer> pos <index>] header), that shows your pick."""

SYSTEM_MC = f"{_INTRO}\n\n{_TASK}\n\n{_RULES}\n{QUOTE_DIGEST}"
NATIVE_MC = f"{_INTRO}\n\n{_TASK}\n\n{_RULES}\n{QUOTE_NATIVE}"
assert NATIVE_MC != SYSTEM_MC

QUESTION = "Which candidate connection do the readouts point to?"
USER_MC = (
    "{summary_note}\n\nReadouts:\n<<<\n{readout}\n>>>\n\nCandidate connections:\n{listing}\n\n"
    + QUESTION
)
# the native diagnostic: every read cell's raw samples under its [L<layer> pos <i>] header
USER_NATIVE = (
    "Readouts (grouped by layer and token position):\n<<<\n{readout}\n>>>\n\n"
    "Candidate connections:\n{listing}\n\n" + QUESTION
)
# the continuation floor: the slot's four member words are the only evidence (no quote gate)
USER_CONT = "Readouts:\n<<<\n{readout}\n>>>\n\nCandidate connections:\n{listing}\n\n" + QUESTION

# the task TYPE the digest's `task` variant is told (no gold, no words, no tool name)
DIGEST_TASK_NOTE = (
    "the model was reading a 16-word grouping puzzle (sort the words into 4 groups of 4 that share "
    "a connection) and had not answered yet; note the groupings and connections the readouts "
    "state"
)

PROMPTS: dict[str, str] = {
    "SYSTEM_MC": SYSTEM_MC,
    "NATIVE_MC": NATIVE_MC,
    "USER_MC": USER_MC,
    "USER_NATIVE": USER_NATIVE,
    "USER_CONT": USER_CONT,
    "TOKEN_NOTE": TOKEN_NOTE,
    "DIGEST_TASK_NOTE": DIGEST_TASK_NOTE,
}

SCHEMA_MC = schema_block(
    "nyt_mc",
    {
        "choice": {"type": "integer", "description": "the number of the candidate line"},
        "quote": {
            "type": "string",
            "description": "shortest span, copied from inside one readout line, showing the pick",
        },
    },
    ["choice", "quote"],
)


def render_user_mc(note: str, readout: str, listing: str) -> str:
    return (
        USER_MC.replace("{summary_note}", note)
        .replace("{listing}", listing)
        .replace("{readout}", readout.strip())
    )


def render_user_native(readout: str, listing: str) -> str:
    return USER_NATIVE.replace("{listing}", listing).replace("{readout}", readout.strip())


def render_user_cont(words: str, listing: str) -> str:
    return USER_CONT.replace("{listing}", listing).replace("{readout}", words.strip())
