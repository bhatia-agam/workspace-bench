"""Prompts of the nyt_connections judge (plan 0062); printed verbatim in the family README.

Plan 0099 (``nyt-mc-2026-11-20``): a candidate may be picked only when a readout line STATES its
connection (the candidate's wording or a clear paraphrase); a line that only lists words states
no connection, so the judge answers "cannot tell" instead of inferring one from member words.

Summary mode (the default): ``SYSTEM_MC`` / ``USER_MC`` per slot on the puzzle's digest (also the
partner null and the word-masked ablation). ``USER_CONT``: the continuation floor (the slot's four
member words as the only evidence). ``NATIVE_MC`` / ``USER_NATIVE``: the native diagnostic path
(``opts=aggregate=native``) on the puzzle's raw readout lines."""

from wsbench import mc
from wsbench.llm import schema_block

PROMPT_VERSION = "nyt-mc-2026-11-20"
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
is a connection that one group of the puzzle's words could share. Pick the ONE candidate whose
connection the readouts STATE: a readout line that names that connection itself, in the
candidate's words or a clear paraphrase of the same connection, and that expresses that
candidate more clearly than any other candidate on the list."""
_RULES = (
    """Rules:
- A candidate counts only when a readout line states its connection: the category, property,
  phrase or wordplay that links the words. The candidate's wording or a clear paraphrase of
  the same connection both count.
- A line that only lists words (puzzle words, members, examples or instances), with no
  connection named, states NO connection, however well those words would fit a candidate. Do
  not work out from listed words what they have in common: that is solving the puzzle. Such
  lines support no candidate.
- A line that names a connection and also lists words ("Types of cheese: brie, gouda, feta";
  "bass, sole, pike: all fish") states that connection, and supports the candidate with that
  connection, not a different candidate that the listed words happen to fit; quote the naming
  span, not the listed words.
- A definition or gloss of ONE word states that word's meaning, not the group's connection: it
  supports no candidate unless it also names the connection.
- In a ranked token line (items separated by " | "), a connection is stated only when tokens
  of that line spell the connection's own name or a paraphrase of it ("cheese";
  "mouse | actions"). Member or example tokens never state it, alone or jointly: the token
  rule below does not let members add up to a connection.
- """
    + TOKEN_NOTE
    + """
- If no candidate's connection is stated, or two or more candidates are about equally
  supported, pick the last option, "cannot tell from the readout". That is a normal answer.
- Never solve the puzzle yourself and never guess."""
)
QUOTE_DIGEST = """- Quote the shortest span, copied from inside ONE readout line, that states the
  connection of your pick."""
QUOTE_NATIVE = """- Quote the shortest span from the readouts, copied from inside ONE readout
  sample (one line under a [L<layer> pos <index>] header), that states the connection of your
  pick."""

SYSTEM_MC = f"{_INTRO}\n\n{_TASK}\n\n{_RULES}\n{QUOTE_DIGEST}"
NATIVE_MC = f"{_INTRO}\n\n{_TASK}\n\n{_RULES}\n{QUOTE_NATIVE}"
assert NATIVE_MC != SYSTEM_MC

QUESTION = "Which candidate's connection do the readouts state?"
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
            "description": (
                "shortest span, copied from inside one readout line, stating the pick's connection"
            ),
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
