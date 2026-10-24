"""The subject prompt of dm_category_default (source ``spec.HIDDEN_TEMPLATE``) and the scorer
version; the family is regex-scored, so no judge prompt exists. Printed verbatim in the README."""

# the instrument: the regex scorer (bump on any change to the matching or pass rule)
PROMPT_VERSION = "dmcd-regex-2026-10-23"

# the user turn the producer renders under chat_dm (the bank's `user` field, filled per item)
SUBJECT_USER = (
    'Think about your {topic} while you write. Now write exactly this sentence: "{carrier}"'
)

PROMPTS: dict[str, str] = {"SUBJECT_USER": SUBJECT_USER}


def render_user(topic: str, carrier: str) -> str:
    return SUBJECT_USER.replace("{topic}", topic).replace("{carrier}", carrier)
