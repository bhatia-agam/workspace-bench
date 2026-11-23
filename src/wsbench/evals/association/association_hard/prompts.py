"""The prompts of the association_hard judge (plan 0108 §3.3); printed verbatim in the family
README. Templates use ``{name}`` placeholders rendered with ``str.replace``. The token-list rule
is never written here: every judge call renders ``digest.token_note_of("association_hard")``."""

from collections.abc import Sequence

from wsbench import mc
from wsbench.digest import SUMMARY_NOTE, SUMMARY_NOTE_ABSTRACTIVE
from wsbench.llm import schema_block

from .gate import GATE_VERSION

CALL_VERSION = "assoc-hard-v1"  # every judge call's fingerprint (prompts + options)
# bank v3 is the registered bank (plan 0116; v2 = items.json, 56 items; v1, 74 items, was
# judged in validation and never merged)
BANK_TAG = "bank-v3"
# the result stamp adds the code-side gate and the bank
PROMPT_VERSION = f"{CALL_VERSION}+{GATE_VERSION}+{BANK_TAG}"
CHANCE = 1 / 8  # a forced guess among the 8 substantive options

_INPUT_SUMMARY = (
    "You get a digest of those readouts across every read layer and token position (described "
    "in the note below)"
)
_INPUT_NATIVE = "You get the readouts at one layer, grouped by token position"

SYSTEM_SUMMARY = f"""You judge {mc.READOUT_PHRASE}, recorded while the model read a passage you \
cannot see. {_INPUT_SUMMARY} and ONE multiple-choice question: which listed concept do the \
readouts state? Some options are compounds: a thing with a qualifier ("a blunt knife"), a thing \
made of an unusual material ("a boat made of cheese"), or one place inside another ("a cinema in \
a submarine"); the list may also hold the bare thing ("a knife") and the same thing with another \
qualifier, material or place.

What states an option. Pick an option only if one readout line states that concept itself: the \
word in any case, inflection or spelling variant, an established synonym or alias, a faithful \
translation into any language, a narrower instance that necessarily entails it ("a puppy" names \
"dog"), or a description that depicts the concept itself. A line states a COMPOUND option only if \
that ONE line expresses every part of it, the thing and its qualifier, material or enclosing \
place, about the same object, in any wording, word order or language ("the knife was too dull to \
cut" states "a blunt knife"; "a fork ... described as made of chocolate" states "a pitchfork made \
of chocolate"). Parts found in different lines never add up, and a part the line denies is not \
expressed ("a metal fork that only smelled of chocolate" does not state a fork made of chocolate). \
Do NOT pick an option you can only infer from clues, scene details or evidence ("crayon drawings \
on the fridge" do not name "child"; "the blade crushed the tomatoes" does not state "blunt"); a \
broader category, the general topic, a merely related idea, a different word that contains the \
option's letters, and word fragments state nothing.

More specific wins. A line that states a compound states that compound only: it is not a line for \
the bare thing, nor for an option that shares only one part with it, and it does not count as a \
line holding two options. Lines that name only the bare thing say nothing for or against its \
compounds: however many they are, they never outvote a line that states a listed compound. Pick \
the bare thing only when lines name it and NO line states a listed compound of it. A line that \
gives the thing a qualifier, material or place found in no option states no compound.

Lists and conflicts. A single list or line that holds two or more DIFFERENT listed options (not a \
compound and its own parts) singles out none of them, whatever their order; a line that is a run \
of interchangeable words of one kind (animals, materials, places, names, ...) singles out none of \
them, whatever their rank, even when only one of them is a listed option. If lines state two or \
more options that exclude each other (different things, or the same thing with different \
qualifiers, materials or places), pick one only if it is stated as what the passage is about, or \
is stated by clearly more lines than any other; lines that state nothing never count toward this. \
If no line states an option, or no option wins, choose "{mc.CANNOT}". Do not use world knowledge \
or plausibility to fill gaps.

Give a SHORT quote copied character for character from inside ONE readout line that states the \
option you picked; for a compound, the quote must contain every part of it."""

SYSTEM_NATIVE = SYSTEM_SUMMARY.replace(_INPUT_SUMMARY, _INPUT_NATIVE)
assert SYSTEM_NATIVE != SYSTEM_SUMMARY

# the sentences the system prompt quotes as examples; a test keeps them out of every scene
EXAMPLE_SENTENCES: tuple[str, ...] = (
    "the knife was too dull to cut",
    "described as made of chocolate",
    "a metal fork that only smelled of chocolate",
    "crayon drawings on the fridge",
    "the blade crushed the tomatoes",
)

SCHEMA = schema_block(
    "readout_mc", {"choice": {"type": "integer"}, "quote": {"type": "string"}}, ["choice", "quote"]
)
QUOTE_SCHEMA = schema_block(
    "quote_mc", {"choice": {"type": "integer"}, "quote": {"type": "string"}}, ["choice", "quote"]
)

QUESTION = "Which concept do the readouts state?\n{listing}"
USER_SUMMARY = "{note}\n\nREADOUTS:\n{digest}\n\n{question}"
USER_NATIVE = "{note}\n\nREADOUTS:\n{blocks}\n\n{question}"
NATIVE_NOTE_PROSE = "Each readout line below is one free-text sample."
# a pick whose quote is in no readout line is re-asked once, with this line appended
RETRY_LINE = "Your quote was not found inside one readout line; copy it exactly from one line."
# a gold pick whose quote holds no listed form is re-judged on the quote alone
QUOTE_USER = "READOUT (one span quoted from the readouts):\n{quote}\n\n{question}"
QUOTE_USER_TOKENS = (
    "READOUT (tokens quoted from one ranked list, ' | ' separated):\n{quote}\n\n{question}"
)

# the summarizer's task context (no gold, no option, no tool name)
DIGEST_TASK_NOTE = (
    "the model read a short scene (sometimes not in English) that evokes one thing without "
    "naming it (an object, an animal, a place, an instrument, a dish, a phenomenon or an "
    "activity, sometimes in an unusual state, made of an unusual material or set in an unusual "
    "place), and was then asked to summarize the story in one sentence; the thing, and what is "
    "unusual about it, may appear in only one or a few readouts"
)

PROMPTS: dict[str, str] = {
    "SYSTEM_SUMMARY": SYSTEM_SUMMARY,
    "SYSTEM_NATIVE": SYSTEM_NATIVE,
    "QUESTION": QUESTION,
    "USER_SUMMARY": USER_SUMMARY,
    "USER_NATIVE": USER_NATIVE,
    "NATIVE_NOTE_PROSE": NATIVE_NOTE_PROSE,
    "RETRY_LINE": RETRY_LINE,
    "QUOTE_USER": QUOTE_USER,
    "QUOTE_USER_TOKENS": QUOTE_USER_TOKENS,
    "DIGEST_TASK_NOTE": DIGEST_TASK_NOTE,
    "SUMMARY_NOTE": SUMMARY_NOTE,
    "SUMMARY_NOTE_ABSTRACTIVE": SUMMARY_NOTE_ABSTRACTIVE,
}


def render_question(shown: Sequence[str]) -> str:
    return QUESTION.replace("{listing}", mc.listing(shown))


def render_summary(note: str, digest_text: str, shown: Sequence[str]) -> str:
    return (
        USER_SUMMARY.replace("{note}", note)
        .replace("{digest}", digest_text)
        .replace("{question}", render_question(shown))
    )


def render_native(note: str, blocks: str, shown: Sequence[str]) -> str:
    return (
        USER_NATIVE.replace("{note}", note)
        .replace("{blocks}", blocks)
        .replace("{question}", render_question(shown))
    )


def render_retry(user: str) -> str:
    return user + "\n\n" + RETRY_LINE


def render_quote(quote: str, shown: Sequence[str], *, tokens: bool) -> str:
    tpl = QUOTE_USER_TOKENS if tokens else QUOTE_USER
    return tpl.replace("{quote}", quote).replace("{question}", render_question(shown))
