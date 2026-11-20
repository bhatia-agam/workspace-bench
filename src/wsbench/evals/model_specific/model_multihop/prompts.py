"""model_multihop prompts: the global-workspace mmh v2 summarizer and concept judge (ported, the
tool name reworded) and the summary-mode MC judge; rendered by :func:`render`, not ``.format``."""

import re

from wsbench import mc
from wsbench.llm import schema_block

CALL_VERSION = "mmh-2026-11-06"  # every judge call's fingerprint version
# the name matcher + the bank's frozen forms (judge.option_spans); v2: quotes read in their line,
# overlap blocking, case-checked forms by capitals, review fixes to the forms and blockers
# v3: a quote cut at its sample's end is read in its line (no longer name it may be the tail of)
# and blockers join the prefix check; blockers hide only the options that list them
FORMS_VERSION = "mmh-forms-v3"
# the bank's options (plan 0076 rev G): bank v2 = invented decoys are the item's own gw foils
BANK_TAG = "bank-v2"
PROMPT_VERSION = f"{CALL_VERSION}+{FORMS_VERSION}+{BANK_TAG}"  # the result stamp

# gw sent no system prompt; the bench's Anthropic route needs a non-empty one (hinted_cutoff)
SYSTEM = "Reply with JSON only."

# gw mmh_sjudge.TASK, verbatim: the one-line task per category (never the entity or question)
TASK_INVENTED = "answering a question about which country something or someone is from."
TASK_CUTOFF = "answering a question about a current product, officeholder, title holder or similar."
TASKS = {"invented": TASK_INVENTED, "cutoff": TASK_CUTOFF}

# the digest's task notes (digest.DIGEST_TASK_LINE: "while these readouts were taken, <note>.")
TASK_NOTE = "the model was answering a short factual question"
ITEM_TASK_NOTES = {cat: "the model was " + t.rstrip(".") for cat, t in TASKS.items()}

# Native mode: gw mmh_sjudge.SUMMARIZER and CJUDGE verbatim except the REWORDS below and the
# ``.format`` braces ({{ }} -> { }); tests/test_model_multihop.py pins both.
WHERE_LAYER = "several token positions of one prompt, at one layer"
WHERE_ALL = "several token positions of one prompt, at several layers"

SUMMARIZER = f"""You will see {mc.READOUT_PHRASE}. Each readout is either a short text \
description or a list of top vocabulary tokens (word fragments, other scripts and noise are \
normal). They come from {{where}}.

Summarize what the model appears to be thinking about. Name the specific concepts (people, \
products, models/versions, places, countries, organisations, values) the readouts point to, \
most prominent first. Weigh a concept by how consistently it recurs across the readouts: one \
that dominates many readouts matters more than one mentioned once, e.g. in a list of \
alternatives. Ground every claim in the readouts; add no knowledge of your own and do not guess \
what the model was asked.

Readouts:
{{material}}

Return JSON only: {{"summary": "<3-6 sentences>", "concepts": ["<most prominent>", ...]}}"""

CJUDGE = """A language model was working on a task. Task: {task}

The model's internal activations were read while it worked. Summary of the readouts:
<<<{summary}>>>
Concepts the summary lists, most prominent first: {concepts}

Which ONE of these candidates is the model thinking about? Candidates: {cands}

- Count a candidate only if the summary names it (obvious aliases, abbreviations and \
spellings are fine; a near-miss version or a different country is a different candidate).
- If the summary names several candidates, choose the one it presents as most prominent.
- If it names none of them, answer "none".

Return JSON only: {"pick": "<one candidate copied exactly, or none>", "quote": "<verbatim \
words from the summary that name it, or empty>"}"""

# the only wording changes from gw (plan rev 9): the tool name, which the bench bans in prompts
REWORDS = (
    (
        "readouts from an interpretability tool that reads a language model's internal activations",
        mc.READOUT_PHRASE,
    ),
    (
        "An interpretability tool read the model's internal activations while it worked. "
        "Summary of what the tool read:",
        "The model's internal activations were read while it worked. Summary of the readouts:",
    ),
)

# Summary mode (the default): one blind MC call per item over the digest, cannot tell LAST.
CANNOT = "cannot tell: the readout does not single out one of these candidates"

SYSTEM_SUMMARY = f"""You judge {mc.READOUT_PHRASE}, taken while the model worked on a task. \
You get a one-line description of the task, a numbered list of candidates and the readout.

Choose the ONE candidate the readout shows the model thinking about, or the "cannot tell" line.
- Count a candidate only if the readout names it (obvious aliases, abbreviations and spellings \
are fine; a near-miss version or a different country is a different candidate).
- If the readout names several candidates, choose the one it presents as most prominent.
- If it names none of them, choose "cannot tell".
- Give a SHORT quote copied character for character from ONE line of the readout that names \
your pick and no other candidate; leave it empty when you choose "cannot tell".
Return JSON: {{"choice": <the number of your line>, "quote": "<verbatim>"}}."""

USER_SUMMARY = """TASK: the model was {task}

CANDIDATES:
{options}

{summary_note}

READOUT:
{summary}"""

PROMPTS: dict[str, str] = {
    "SYSTEM": SYSTEM,
    "SUMMARIZER": SUMMARIZER,
    "WHERE_LAYER": WHERE_LAYER,
    "WHERE_ALL": WHERE_ALL,
    "CJUDGE": CJUDGE,
    "TASK_INVENTED": TASK_INVENTED,
    "TASK_CUTOFF": TASK_CUTOFF,
    "SYSTEM_SUMMARY": SYSTEM_SUMMARY,
    "USER_SUMMARY": USER_SUMMARY,
    "CANNOT": CANNOT,
    "TASK_NOTE": TASK_NOTE,
    "TASK_NOTE_INVENTED": ITEM_TASK_NOTES["invented"],
    "TASK_NOTE_CUTOFF": ITEM_TASK_NOTES["cutoff"],
}

_STR = {"type": "string"}
SUMMARY_SCHEMA = schema_block(
    "mmh_summary",
    {"summary": _STR, "concepts": {"type": "array", "items": _STR}},
    ["summary", "concepts"],
)
CJUDGE_SCHEMA = schema_block("mmh_concept", {"pick": _STR, "quote": _STR}, ["pick", "quote"])
MC_SCHEMA = schema_block(
    "mmh_pick", {"choice": {"type": "integer"}, "quote": _STR}, ["choice", "quote"]
)

_SLOT = re.compile(r"\{(where|material|task|summary|concepts|cands|options|summary_note)\}")


def render(template: str, **values: str) -> str:
    """One pass over the template's ``{name}`` slots (a value is never re-scanned, so readout
    text holding ``{summary}`` stays as it is); unknown names stay literal."""
    return _SLOT.sub(lambda m: values[m.group(1)] if m.group(1) in values else m.group(0), template)


def port(gw: str) -> str:
    """A gw ``.format`` template as this module holds it: REWORDS applied, ``{{ }}`` -> ``{ }``."""
    for old, new in REWORDS:
        gw = gw.replace(old, new)
    return gw.replace("{{", "{").replace("}}", "}")
