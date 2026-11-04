"""Prompts of the introspection blind forced-choice judge (plan 0045; descended from the source
repo's ``olens_suite/introspection_inject/judge.py`` ``LENS_SYSTEM``); printed verbatim in the
family README. The options are the item's five cluster concepts, "no injected concept" and, last,
"cannot tell from the readout"; every option is rendered with its listed "also" words and the
cluster-mates it is "same as" (decision Q12), so the gold is never singled out."""

from collections.abc import Mapping, Sequence

from wsbench import digest, mc
from wsbench.llm import schema_block

# plan 0045: folds plan 0032's "+cannot-2026-10-30"; v2 = the Q12 equivalents / "also" menu, the
# leniency rubric, the restated tie rule, the spec-rendered token note and the "same as" line
# clause; v3 was round 3's "presented as the thought" tightening (reverted in round 4); v4: ONE
# naming criterion, "names the concept or a close equivalent, in any way" (the name / code /
# related-word / buried-word exclusions and the unscored anomaly fields are gone)
CALL_VERSION = "ii-grid-2026-11-v4"  # every judge call's fingerprint
# the regex matcher's name rule (judge.names_form). Deterministic, so in the result stamp only;
# no call is re-asked
# v3 (fresh-eye review of #194): Title-Case headings and list labels are no names
# v4 (round 4): the regex matches regular inflections of every single-word form ("dreaming",
# "glued", "parades" -> judge.inflected); it feeds the regex diagnostic only
REGEX_LEG_VERSION = "twinrx-v4"
# the HEADLINE is the paired LLM judge; the round-4 regex headline (rxhead-v1) is the rx_* /
# regex_* diagnostic column. v2: the gaussian twin voids a hit only by its own judge verdict
# (same judge, rubric and read window as the hit). Scoring only: no call is re-asked
HEADLINE_VERSION = "jhead-v2"
PROMPT_VERSION = f"{CALL_VERSION}+{REGEX_LEG_VERSION}+{HEADLINE_VERSION}"

SYSTEM = f"""You are judging {mc.READOUT_PHRASE} in an interpretability benchmark. One internal
activation was turned into text. You get the readout samples for that activation and a numbered
list of OPTIONS: five concept words, the option "no injected concept" and, last, the option
"cannot tell from the readout". A concept option may list "also" words (other words that name
it) and the options it is "same as" (options that count as the same concept).

Decide which ONE concept option the readout names.
- An option is named if a sample names that concept or a close equivalent, in any way.
- Options marked "same as" one another count as ONE concept: answer with any one of them.
- If different samples name different options, choose the one named most often / most
  prominently. In a token list, an option counts only where the token-line rule in the user
  turn singles it out.
- Choose "no injected concept" when no sample names a concept option.
- Choose "cannot tell from the readout" when the samples neither name a concept option nor
  clearly report that no concept was injected.
- For a concept choice, "quote" must be the shortest span copied VERBATIM from one sample that
  names it; for a token line whose options are all "same as" one another, quote the whole line
  (its tokens joined by " | "). Otherwise "quote" is "".
Judge only what is written. Return JSON {{"choice": <option number>, "quote": "..."}}."""

# the family's one addition to the shared token-list rule (plan 0045 §2.2, decision Q12): it
# follows the rendered ``mc.token_note`` wherever that note is shown; the scorer narrows it
# mechanically (``judge.quote_options`` must lie inside the item's accept set)
SAME_AS_LINE = (
    'Options marked "same as" one another count as ONE option for the line rule above: a line '
    'whose options are all "same as" one another singles them out together; answer with any one '
    "of them."
)

USER = "OPTIONS:\n{options}\n\n{note}\n\n{samples}"
NOTE_TEXT = "The samples below are independent free-text readouts of the same activation."
NOTE_TOKEN_LIST = (
    "The sample below is ONE ranked list of the top vocabulary tokens read from this activation."
)
SAMPLE = "[sample {n}]\n{sample}"

# summary mode (plan 0020): one digest of every read layer and position replaces the per-cell
# samples; the judge rules are unchanged
SUMMARY_INPUT_OLD = (
    "One internal\nactivation was turned into text. You get the readout samples for that "
    "activation and a numbered\nlist of OPTIONS"
)
assert SUMMARY_INPUT_OLD in SYSTEM
SUMMARY_INPUT = """\
A language model's internal activations, at every read layer and token position, were turned
into text. You get a digest of the readouts (described in the note in the user turn) and a
numbered list of OPTIONS"""
SYSTEM_SUMMARY = SYSTEM.replace(SUMMARY_INPUT_OLD, SUMMARY_INPUT)
assert SYSTEM_SUMMARY != SYSTEM
USER_SUMMARY = "OPTIONS:\n{options}\n\n{note}\n\n{summary}"

# the task TYPE the digest's `task` variant is told (never the options or the concept): the
# family-level note, and one note per prompt kind (plan 0045 C5; controls and twins get their
# prompt kind's note, so floors and pairs stay matched)
DIGEST_TASK_NOTE = (
    "the model reads a short request, and its activations may or may not have been steered "
    "toward a concept, which may appear in only one or a few readouts"
)
TASK_NOTES = {
    "protocol": "the model was asked whether it detects an injected thought and what it is "
    "about; a concept may appear in only one or a few readouts",
    "neutral": "the model was given an ordinary short request; its activations may have been "
    "steered toward a concept, which may appear in only one or a few readouts",
}

PROMPTS: dict[str, str] = {
    "SYSTEM": SYSTEM,
    "SAME_AS_LINE": SAME_AS_LINE,
    "USER": USER,
    "NOTE_TEXT": NOTE_TEXT,
    "NOTE_TOKEN_LIST": NOTE_TOKEN_LIST,
    "SAMPLE": SAMPLE,
    "SUMMARY_INPUT": SUMMARY_INPUT,
    "USER_SUMMARY": USER_SUMMARY,
    "DIGEST_TASK_NOTE": DIGEST_TASK_NOTE,
    "TASK_NOTE_PROTOCOL": TASK_NOTES["protocol"],
    "TASK_NOTE_NEUTRAL": TASK_NOTES["neutral"],
    "SUMMARY_NOTE": digest.SUMMARY_NOTE,
    "SUMMARY_NOTE_ABSTRACTIVE": digest.SUMMARY_NOTE_ABSTRACTIVE,
    "SUMMARY_NOTE_TOKENS": digest.SUMMARY_NOTE_TOKENS,
}

SCHEMA = schema_block(
    "introspection_verdict",
    {"choice": {"type": "integer"}, "quote": {"type": "string"}},
    ["choice", "quote"],
)

Menu = Mapping[str, tuple[Sequence[str], Sequence[str]]]  # label -> (also words, same-as options)


def option_text(label: str, menu: Menu | None = None) -> str:
    """``gadgets (also: devices; same as: contraptions, machines)``: the label plus its listed
    "also" words and the shown options it is "same as"; a bare label when it has neither."""
    also, same = (menu or {}).get(label, ((), ()))
    parts = []
    if also:
        parts.append("also: " + ", ".join(also))
    if same:
        parts.append("same as: " + ", ".join(same))
    return f"{label} ({'; '.join(parts)})" if parts else label


def format_options(labels: Sequence[str], menu: Menu | None = None) -> str:
    """Numbered option lines (1-based), in the item's order, every option rendered alike."""
    return "\n".join(f"{i + 1}. {option_text(lab, menu)}" for i, lab in enumerate(labels))


def token_note(note: str) -> str:
    """The token-list rule the judge receives (``mc.token_note`` of the registered spec, via
    ``digest.token_note_of``) followed by the family's "same as" line clause."""
    return f"{note}\n{SAME_AS_LINE}"


def render_user(
    samples: Sequence[str],
    labels: Sequence[str],
    kind: str,
    menu: Menu | None = None,
    *,
    rule: str | None = None,
) -> str:
    """The judge's user turn for one cell; ``kind`` is ``"text"`` (prose samples) or
    ``"tokens"`` (one sample: a token readout's top-k as ONE ``" | "``-joined ranked list,
    followed by ``rule``, the spec-rendered token note, and the "same as" clause)."""
    body = "\n".join(
        SAMPLE.replace("{n}", str(i + 1)).replace("{sample}", s) for i, s in enumerate(samples)
    )
    if kind == "tokens":
        note = NOTE_TOKEN_LIST + "\n" + token_note(rule if rule is not None else mc.TOKEN_NOTE)
    else:
        note = NOTE_TEXT
    return (
        USER.replace("{options}", format_options(labels, menu))
        .replace("{note}", note)
        .replace("{samples}", body)
    )


def render_user_summary(
    summary: str, labels: Sequence[str], note: str, menu: Menu | None = None
) -> str:
    """Summary mode: the options, the digest note (with the token rule and the "same as"
    clause on a token source), then the unit's readout digest."""
    return (
        USER_SUMMARY.replace("{options}", format_options(labels, menu))
        .replace("{note}", note)
        .replace("{summary}", summary)
    )
