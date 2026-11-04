"""The rival sentence of the forced-choice judges' prompts (round 3, 2026-10-31): the judge also
returns ``rival_quote``, the readout line with the most samples that gives a competing answer.
Nothing weighs it against the gold any more (the support-count contest, its margins and the
rival / option audit calls were removed on 2026-11-04): code verifies a judge pick, it never
overrules one. The sentence stays in the prompts unchanged, so cached answers stay valid;
``rival_quote`` is reported per row and never scored."""

# the judge calls' key of the round-3 rival sentence (wrong_intermediate's MC_CALL_VERSION and the
# multi-token families' frozen call versions are built on it)
RIVAL_CALL_VERSION = "rv-2026-10-31e"

RIVAL_FIELD = {"rival_quote": {"type": "string"}}

RIVAL_RULE = (
    'Also give "rival_quote": when you pick an option, a SHORT quote copied exactly from the '
    "readout line with the MOST samples that gives a competing answer to the SAME hidden "
    "question: {competing} A line about another work, thing or relation, a line that names "
    "nobody in that role, and a line that also names your pick are NOT rivals. Leave it empty "
    "when there is no such line, and when you choose cannot tell."
)


def rival_rule(competing: str) -> str:
    """The rival sentence of one family's SYSTEM prompt; ``competing`` says what a competing
    answer is for that family (who or what, in which role, for what)."""
    return RIVAL_RULE.replace("{competing}", competing.strip())
