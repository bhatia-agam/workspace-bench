"""Prompts of the ttt_move blind MC judge (source repo ``scripts/oracle_lens_evals/ttt_move/
judge.py``, ``INTRO`` + ``CONSTRAINED``); only the answer-format tail moves to the JSON schema.
Printed verbatim in the family README."""

from wsbench.llm import schema_block

PROMPT_VERSION = "ttt-move-2026-10-24"
LETTERS = "ABCDEFGHI"
NONE = "NONE"
JLENS_TOP = 10  # the J-lens sample is the cell's first ten tokens, as the source rendered it

# the source prompt's first paragraph (``INTRO``), sent as the system turn
SYSTEM = (
    "A language model (Qwen3.6-27B) was given a tic-tac-toe prompt in which every square has a "
    "name (a common noun), and asked to reply with the name of the square it plays. Just before "
    "it replied, its internal activations were decoded into text by an 'activation verbalizer': "
    "each sample below is one noisy natural-language description of what the model represents "
    "at that moment. The readouts may restate the board; that is NOT evidence of the move."
)
# the J-lens variant (source ``JLENS_INTRO``): only the description of a "sample" changes
SYSTEM_JLENS = SYSTEM.replace(
    "its internal activations were decoded into text by an 'activation verbalizer': "
    "each sample below is one noisy natural-language description of what the model represents "
    "at that moment.",
    "its internal activation was read with a Jacobian lens: the sample below lists the 10 "
    "vocabulary tokens most aligned with the activation at that moment, most aligned first.",
)
# the source ``CONSTRAINED`` body after ``INTRO``, verbatim up to "Think briefly"; the source's
# closing `ANSWER:` / `QUOTE:` lines become the schema's `answer` / `quote` fields
USER = (
    "=== ACTIVATION READOUTS ===\n{reads}\n\n=== OPTIONS (the empty squares) ===\n{menu}\n\n"
    "Decide which option the model is about to play. Your answer must be supported by a VERBATIM "
    "quote copied exactly from one sample that either STATES the move (e.g. 'play walrus', 'take "
    "walrus', 'the best move is walrus') or is a bare square name that is that sample's leading "
    "square mention (not part of a restated board). If no sample states a move for any option, "
    "answer NONE. Think briefly, then give three fields:\n`reasoning`: <your brief thinking>\n"
    "`answer`: <letter or NONE>\n`quote`: <verbatim span from one sample, or empty>"
)

PROMPTS: dict[str, str] = {"SYSTEM": SYSTEM, "SYSTEM_JLENS": SYSTEM_JLENS, "USER": USER}

SCHEMA = schema_block(
    "ttt_move",
    {
        "reasoning": {"type": "string", "description": "brief"},
        "answer": {"type": "string", "enum": [*LETTERS, NONE]},
        "quote": {"type": "string", "description": "verbatim span from one sample, or empty"},
    },
    ["reasoning", "answer", "quote"],
)


def fmt(samples: list[str]) -> str:
    """The source's sample block: ``[sample j] <text>`` separated by blank lines."""
    return "\n\n".join(f"[sample {j + 1}] {t.strip()}" for j, t in enumerate(samples))


def menu(options: list[int], names: list[str]) -> str:
    """``A. walrus`` lines for an option list (source ``options.menu``)."""
    return "\n".join(f"{LETTERS[k]}. {names[sq]}" for k, sq in enumerate(options))


def render_user(samples: list[str], options: list[int], names: list[str]) -> str:
    # the menu first: a readout sample may contain the literal text "{menu}"
    return USER.replace("{menu}", menu(options, names)).replace("{reads}", fmt(samples))
