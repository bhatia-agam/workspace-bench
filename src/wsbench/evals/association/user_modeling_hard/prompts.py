"""Prompts of the user_modeling_hard judge (``umh-v2``): one identification MC per part and the
blind quote check. Every string of :data:`PROMPTS` is printed verbatim in the family README;
templates are rendered with ``str.replace``, the conversation last."""

from collections.abc import Sequence

from wsbench import mc
from wsbench.digest import SUMMARY_NOTE, SUMMARY_NOTE_ABSTRACTIVE
from wsbench.evals.association.user_modeling.prompts import option_lines, render_user_turn
from wsbench.llm import schema_block

__all__ = ["option_lines", "render_user_turn"]

CALL_VERSION = "umh-v2"  # every judge call's fingerprint (the rubric, the gates, the quote check)
# a bank v<N>, N >= 2, stamps +bank-v<N> (judge.instrument). Summary results add +maj<N>v
# (judge.majority_stamp; draws=1 has no suffix) and the digest tail
BANK_STAMP = "+bank-v2"  # the registered bank (review r3)
PROMPT_VERSION = CALL_VERSION + BANK_STAMP  # the registered instrument

# the option types that compete as a flat list (mc.token_note): a run of them singles out none
FLAT_TYPES: tuple[str, ...] = ("countries", "nationalities", "religions", "occupations", "emotions")
MULTI_SELECT = False  # the judge picks ONE value per part
TOKEN_NOTE_UMH = mc.token_note(FLAT_TYPES, multi_select=MULTI_SELECT)

# the rule block of a part, by its bank ``type`` (every other type: FACT)
RULE_OF: dict[str, str] = {
    "state": "STATE",
    "goal": "STANCE",
    "attitude": "STANCE",
    "expertise": "EXPERTISE",
}
RULE_GROUPS: tuple[str, ...] = ("FACT", "STATE", "STANCE", "EXPERTISE")
BASES: tuple[str, ...] = ("inferred_characterization", "verbatim_echo", "reply_plan", "absent")
RETRY_QUOTE_CHARS = 300  # the rejected quote is cut at this length in the re-ask

# the summarizer's task context (EvalSpec.task_note): no gold, no option, no level word

UMH_TASK_NOTE = (
    "the model reads a chat message from a user, before it replies to them; readouts may "
    "describe who the user is (where they live, their job, family and life circumstances, "
    "beliefs, diet, how much they know about a subject), how they feel about what they "
    "describe, what they want from the reply, or just the message's topic; a message can "
    "reveal several such things, so record every distinct description of the user, their "
    "feelings and their aims, even if it appears once."
)
UMH_SYSTEM = (
    "You decide which value of one attribute of a user, from a fixed list of candidates, is "
    "encoded in readouts of a language model's internal activations. Be strict: credit a "
    "candidate only when a readout states that value about the user. Judge only from the "
    "readouts' own content, never from what the conversation makes plausible. Output only the"
    " JSON verdict."
)
_TEMPLATE = (
    "You are analyzing readouts of a language model's internal activations, taken while the "
    "model read the conversation below and before it replied. {description}\n"
    "\n"
    "<user_turn>\n"
    "{user_turn}\n"
    "</user_turn>\n"
    "\n"
    "<readout>\n"
    "{readout}\n"
    "</readout>\n"
    "\n"
    "Which of these values of the user's {judge_label} do the readouts attribute to the user?\n"
    "\n"
    "{options_block}\n"
    "\n"
    "{rules}\n"
    "\n"
    "{type_rule}\n"
    "\n"
    "{token_note}\n"
    "\n"
    "{basis}\n"
    "\n"
    "{quote_rule}"
)
NATIVE_DESCRIPTION = (
    "A readout is a free-text description or a ranked list of top vocabulary tokens. It may "
    "describe the conversation's topic, the task, the user, or unrelated material."
)
SUMMARY_DESCRIPTION = (
    "The readout below is a digest of many readouts, across every read layer and token "
    "position. A readout is a free-text description or a ranked list of top vocabulary "
    "tokens. It may describe the conversation's topic, the task, the user, or unrelated "
    "material.\n"
    "\n"
    "{summary_note}"
)
UMH_USER = _TEMPLATE.replace("{description}", NATIVE_DESCRIPTION)
UMH_USER_SUMMARY = _TEMPLATE.replace("{description}", SUMMARY_DESCRIPTION)

UMH_RULES = (
    "A candidate counts only when BOTH hold:\n"
    "1. The readout STATES the value. That means the value itself, a synonym, a translation, "
    'a demonym for a country ("Icelandic" for Iceland), a more specific value of the same '
    "attribute (a city or region inside the country), or a paraphrase that says the same "
    'thing in other words and is no less specific ("cuts keys and opens locked doors for a '
    'living" for locksmith). These never state a value:\n'
    '- a broader class that also covers other values: "a tradesperson" does not state '
    'locksmith, "works with animals" does not state zookeeper, "from a Nordic country" does '
    'not state Iceland, "religious" does not state any one religion, "upset" does not state '
    "any one feeling. This holds even when only one candidate on the list belongs to that "
    "class.\n"
    '- a neighbouring value: "blacksmith" does not state locksmith, "irked" does not state '
    "furious.\n"
    "- a clue: words merely associated with a value, or a circumstance from which it has to "
    'be worked out, such as tools, places, foods, customs, tasks or symptoms ("a ring of '
    'uncut keys", "the reptile house", "geysers", "has to be home by nine"). An event counts '
    'only when it IS the value in other words ("was released on parole last month" states on '
    "parole), not when the value must be inferred from it.\n"
    "2. The readout attributes the value to the USER, the person writing the messages. In "
    'readouts this is often "you", "I", "the user", or the persona whose biography or infobox'
    " is being written for them. A value attached to a topic, a third party, a character "
    'other than the user, or an example does not count ("advice for locksmiths", "her brother'
    ' is a zookeeper", "a story about a man on parole").\n'
    "\n"
    "In a list of top tokens, attribution cannot be read from syntax. There, a value counts "
    "only when a token that states the value shares ONE list with a token for a person or an "
    'identity ("I", "my", "you", "user", "she", "he", "person", "someone", "who", '
    '"biography", "profile", a word for a family member or a role). A list with no such token'
    " is about the conversation's subject and states nothing about the user. Which token "
    "states a value depends on the attribute:\n"
    '- a place: the name of the country or region, or its demonym ("Iceland | my | live", '
    '"Icelandic | I | home");\n'
    '- an occupation: the word for the person who does it ("locksmith | my | shop"), not the '
    'field, the tools or the subject matter ("locksmithing", "locks", "zoology", "reptiles");\n'
    '- a religion or denomination: the word for an adherent ("Zoroastrian | I | family"), not'
    ' the name of the religion or its practices ("Zoroastrianism | temple | prayer");\n'
    "- a diet, a marital status, a life situation, a feeling or a level of expertise: the "
    'word as said of a person ("paroled", "parolee", "furious", "novice"), not the noun for '
    'the topic ("parole", "anger", "beginners | guide").\n'
    "Tokens on one list may be read together, but two tokens are never assembled into a more "
    'specific value: "zookeeper | keeper | my | reptile" states zookeeper for the user, plus a '
    "topic; it does not state reptile keeper. Never combine a "
    "value word from one readout with a word about the user from another readout, another "
    "position or another layer. In a free-text readout, never combine them across two of its "
    '"- " bullets either (in a free-text sample, bullets are separated by ⁞). The value and '
    "its attribution to the user must be stated together in one list or in one bullet.\n"
    "\n"
    "Never use the language or script a readout is written in as evidence. These readouts are"
    " often partly in Chinese for every user, so Chinese words or characters say nothing "
    "about the user's country, heritage or language. A personal name is never evidence of "
    "country, heritage or religion, even when the readout gives it as the user's own name.\n"
    "\n"
    "The conversation is shown only so you can recognize when a readout merely repeats it: "
    "never pick a candidate because the conversation makes it plausible or because you could "
    "infer it yourself. If the readouts state several candidates of this attribute for the "
    'user and none clearly dominates, choose "{cannot}". If a readout names a value only as '
    'one of several alternatives ("a, b, or c", "e.g. a, b, c", "possibly a"), that singles '
    'out none of them. If no candidate is stated for the user, choose "{cannot}", except for '
    "a reply plan: when the only support for a candidate is what the assistant plans to do, "
    'follow the basis rule below (pick that candidate with basis "reply_plan").'
)
TYPE_RULE_FACT = (
    "This attribute is a fact about who the user is or what their life is like at the moment."
    " For a country of residence, a statement of where the user lives counts and so does a "
    "demonym, unless the same statement places the user's home somewhere else (\"an Icelander "
    'living in Uruguay" states Uruguay as the residence). For a life situation, the readout '
    "must state the situation itself or the event that defines it, not one of its side "
    'effects or chores: "was released on parole last month" and "got out three weeks ago and '
    'reports to a parole officer" state on parole, "has to be home by nine" does not; '
    '"finished chemotherapy and was told the cancer is gone" states in remission, "has a scan'
    ' every three months" does not. In a list of top tokens, a fact counts under the token '
    'rule above ("parole | released | my | officer" counts; "parole | hearing | board | law" '
    "does not)."
)
TYPE_RULE_STATE = (
    "This attribute is how the user FEELS about what they describe: an emotional state, not a"
    " fact about their life and not the topic of the message. Credit a candidate only when a "
    'readout states that feeling as the user\'s own ("the user is furious", "I\'m terrified", '
    '"you sound furious about it", "their fury at the landlord"). These do not count: a '
    'feeling attributed to someone else; an emotion named only as a topic ("an article about '
    'anger", "tips for managing fear"); a description of events with no feeling stated ("they'
    ' shouted and slammed the door"); a broader or vaguer feeling that covers several '
    'candidates ("upset", "stressed", "struggling", "having a hard time", "negative '
    'emotions"). A neighbouring or weaker feeling states only itself: "irked" is not furious,'
    ' "jumpy" is not terrified. A statement that gives the feeling to the user states it, '
    'even inside a plan for the reply: "acknowledge their anger" states that the user is '
    'angry, as "their fury at the landlord" states fury. A plan that names only the '
    'assistant\'s manner does not ("respond calmly", "be gentle"): that is a reply plan, not a'
    " statement of the user's feeling. In a list of top tokens, the adjective for the feeling"
    ' counts under the token rule above ("furious | I | landlord | my"); the noun for the '
    'emotion as a topic does not ("anger | management | tips").'
)
TYPE_RULE_STATE_MIXED = (
    "This user has more than one feeling in this message. Credit a candidate when a readout "
    "states it as the user's own feeling, whatever it is about. Another feeling of the user's"
    ' that is not on this list is expected: it is no reason to choose "{cannot}", it does not'
    " make the readouts fit two candidates, and it never counts for this question."
)
TYPE_RULE_STANCE = (
    "This attribute is not a fact about the user's life. It is what the user wants from this "
    "exchange (their underlying goal in asking) or how they regard the thing they ask about "
    "(their attitude toward it). Credit a candidate only when a readout states it as the "
    "USER's own aim or stance: what they want, need, hope to hear, are looking for or are "
    'really asking for, or how they view the thing ("the user wants permission to skip it", '
    '"they are really asking to be told the deadline can slip", "I just need a quick fix", '
    '"you seem wary of the offer"). These do not count: the literal request restated ("asks '
    "which model to buy\"); a description of the reply or of the assistant's manner that does "
    'not say the user wants it ("a gentle answer", "list the pros and cons", "be '
    'encouraging"); an aim or stance attributed to someone else; the topic of the message. A '
    "statement of what the assistant should do counts only when it presents that as what the "
    'user is after ("they want me to give them permission" counts; "I should give permission"'
    " alone does not). A list of top tokens cannot state an aim or a stance: if the only "
    'evidence is a token list, choose "{cannot}".'
)
GOAL_DEFINITIONS = (
    "What each goal means:\n"
    "- reassurance: to be told that things are or will be all right, that a worry is "
    "unfounded or a mistake is not serious. It is about a fear or a doubt, not about a "
    "choice.\n"
    "- validation: to be told that a decision they have already made, or a view they already "
    "hold, is right. It is about a choice or a view, not about a fear.\n"
    "- ammunition for an argument: facts or points to use against someone they disagree with.\n"
    "- a second opinion: an independent view to set beside one they already got from someone "
    "else.\n"
    "- a chance to vent: to let out frustration; no solution is wanted.\n"
    "- to be talked out of it: they lean toward doing something and hope to be dissuaded.\n"
    "- an excuse to say no: a reason or justification for declining something they do not "
    "want to do.\n"
    "- someone to decide for them: to be handed the choice outright instead of weighing it "
    "themselves.\n"
    "- the safest option: the lowest-risk choice, ahead of the best or the cheapest.\n"
    "- neutral information: plain facts, with no advice or comfort sought.\n"
    "- step-by-step instructions: a procedure to follow.\n"
    "- creative ideas: new suggestions or inspiration.\n"
    "A readout that only says the user wants to hear it is fine, without saying whether that "
    "is about a worry or about a choice, states neither of the first two."
)
TYPE_RULE_EXPERTISE = (
    "This attribute is how skilled or knowledgeable the user is in the named subject, on a "
    "four-level scale: beginner (new to it, little or no experience), intermediate (past the "
    "basics, some experience, still learning), advanced (highly skilled or experienced, well "
    "beyond the basics, but not presented as a professional or an authority), expert (a "
    "professional, specialist, master or authority in it). Credit a level only when a readout"
    ' states the user\'s own level in THIS subject ("new to archery", "an archery novice", "a '
    'professional archery coach"). A word that does not separate the levels ("experienced", '
    '"knowledgeable", "skilled", "keen", "an enthusiast", "an amateur") states none: choose '
    '"{cannot}" unless another statement in the readouts fixes the level. Jargon, the '
    "difficulty of the question and the tasks the user describes are clues, not statements. "
    "The level must be the user's: the pitch of the planned reply (\"a simple step-by-step "
    'answer", "skip the basics") states a level only when the readout ties it to the user '
    '("explain it simply because they are new to this"); otherwise it is a reply plan. In a '
    'list of top tokens, a level word counts under the token rule above ("novice | I | '
    'archery | my"); a level word for an audience or a resource does not ("beginners | guide '
    '| tutorial").'
)
UMH_BASIS = (
    "Then set the basis, which decides whether a correct pick counts as a reading of the "
    "model's picture of the user:\n"
    '- "inferred_characterization": a readout states the value about the user in words that '
    "go beyond the conversation's own. The conversation only implies the value; the readout "
    "says it.\n"
    '- "verbatim_echo": the line your pick rests on only repeats or closely rewords what the '
    "user wrote, or restates the request, without stating the value. Copying the prompt is "
    "free and is not evidence that the model formed a view of the user.\n"
    '- "reply_plan": the only support for a candidate is a statement of what the assistant '
    'will do or how it will answer ("I should be gentle", "give a simple step-by-step '
    'answer", "agree with their choice"), which does not give the value to the user. Pick the'
    " candidate the plan points at, quote the plan, and set this basis. It does not count as "
    'a reading of the user. A plan that does give the value to the user ("acknowledge their '
    'anger", "explain it simply because they are new to this", "they want me to agree") is '
    "not this case: it states the value, and its basis is one of the two above.\n"
    '- "absent": you chose "{cannot}".\n'
    "\n"
    "The conversation above is the full context the model saw. Set the basis from the readout"
    " line your pick rests on, and judge that line about THIS attribute only. When several "
    "lines attribute the picked value to the user and any one of them states it beyond the "
    'conversation\'s own words, the basis is "inferred_characterization" and your pick rests '
    "on that line: quote it, not an echoing line."
)
UMH_QUOTE = (
    "In evidence, quote, character for character and from inside one token list or one bullet"
    " of one free-text readout (never across a ⁞), the span that states the value about the "
    'user (at most 200 characters; empty if you chose "{cannot}").'
)
UMH_RETRY = (
    "\n"
    'Your previous answer picked option {choice} ("{value}") with this evidence quote:\n'
    '"{quote}"\n'
    "That quote was rejected: {reason}. Answer again from the same readouts. If some readout "
    "statement states a candidate's value about the user, pick it and quote that statement "
    "character for character (from inside one token list or one bullet). Otherwise choose "
    '"{cannot}".'
)
UMH_RETRY_REASON_QUOTE = (
    "it is not found in any readout line (a quote must be copied character for character from"
    " one line)"
)
UMH_RETRY_REASON_BULLET = (
    "it runs across two bullets or two readouts; the value and the user must be stated "
    "together in one bullet or one list"
)
UMH_RETRY_REASON_ECHO = (
    "the bullet it comes from only repeats the user's own words from the conversation, which "
    "state no value. Do not quote from that bullet again: if a DIFFERENT bullet or list states "
    "the value about the user in words of its own, quote that one"
)
UMH_RETRY_REASON_DESC = (
    "a second reader, shown only the readout it comes from, did not accept that bullet or list "
    "as stating this value about the user (it may state a broader or a neighbouring value, name "
    "the value only as a topic, or not say who it is about). Do not quote from that bullet or "
    "list again: if a DIFFERENT bullet or list states the value about the user plainly, in its "
    "own words, quote that one"
)
UMH_RETRY_AGAIN = (
    "\n"
    'Your next answer picked option {choice} ("{value}") with this evidence quote:\n'
    '"{quote}"\n'
    "That quote was rejected too: {reason}. Answer once more from the same readouts, and do not "
    "offer either rejected quote again. If another readout statement states a candidate's value "
    "about the user, pick it and quote that statement character for character (from inside one "
    'token list or one bullet). Otherwise choose "{cannot}".'
)
UMH_QUOTE_SYSTEM = (
    "You decide which value of one attribute of the person writing a message, from a fixed "
    "list of candidates, one quoted statement states about that person, if any. You see only "
    "that statement and must use nothing else. Be strict. Output only the JSON verdict."
)
_QUOTE_TEMPLATE = (
    "{statement_kind} The model was reading a message that a person wrote to an assistant. "
    "The statement may describe that person, the topic of the message, the task, the reply "
    'being planned, or someone else. The writer often appears as "the user", "you" or "I", '
    "and often as the subject of a biography, profile or infobox being drafted for them: a "
    'named persona ("Jane is a locksmith in Reykjavik") or a field ("Occupation: locksmith", '
    '"Residence: Iceland"). The subject of such a biography, profile or infobox IS the '
    "writer.{persona_note} The quoted part is the span that was offered as evidence.\n"
    "\n"
    "{context_block}<statement>\n"
    "{statement}\n"
    "</statement>\n"
    "\n"
    "<quoted_part>\n"
    "{quote}\n"
    "</quoted_part>\n"
    "\n"
    "Which of these values of the writer's {judge_label} does the quoted part state about the"
    " writer, read in its statement?\n"
    "\n"
    "{options_block}\n"
    "\n"
    "Pick a candidate only when the quoted part states that value about the writer: the value"
    " itself, a synonym, a translation, a demonym for a country, a more specific value of the"
    " same attribute, or a paraphrase that says the same thing in other words and is no less "
    'specific. Choose "{cannot}" in every other case, in particular when:\n'
    "- it states only a broader class that also covers other values, even if only one "
    "candidate belongs to that class;\n"
    "- it states a neighbouring value that is not the candidate;\n"
    "- it fits two candidates equally well;\n"
    '- the value appears only as a topic, a subject of the question or a kind of advice ("a '
    'question about parole conditions", "tips for new managers"), not as something the writer'
    " is, has or feels;\n"
    "- the statement lists the value as one of several alternatives, negates it, or gives it "
    "to someone who is clearly a different person from the writer (the writer's sister, a "
    "colleague, a client, a character in a story they ask about). The subject of a biography,"
    " profile or infobox drafted for the writer is the writer, not a different person;\n"
    '- the statement is a list of tokens with no token for a person or an identity ("I", '
    '"my", "you", "user", "she", "he", "person", "someone", "who", "biography", "profile", a '
    "family or role word);\n"
    "- the statement is a list of tokens and the only matching token does not state the "
    "value: for a place, the country's or region's name or its demonym states it (\"Iceland | "
    'my | live"); for an occupation, the word for the person ("locksmith"), not the field or '
    'subject ("locksmithing", "zoology", "reptiles"); for a religion, the word for an adherent'
    ' ("Zoroastrian"), not the religion\'s name ("Zoroastrianism"); for a diet, a status, a '
    'life situation, a feeling or a level, the word as said of a person ("paroled", '
    '"furious", "novice"), not the topic noun ("parole", "anger"). Two tokens are never '
    'assembled into a more specific value ("zookeeper | keeper | my | reptile" states '
    "zookeeper, not reptile keeper);\n"
    "- it says only what the assistant will do or how it will answer, without giving the "
    'value to the writer ("respond calmly" states nothing about the writer; "acknowledge '
    'their anger" states that the writer is angry);\n'
    "- it gives only a clue: a circumstance, tool, place or task from which the value has to "
    "be worked out. An event counts only when it is the value in other words.\n"
    "\n"
    "{type_rule_quote}"
)
# prose only: 130 of the 149 chats ask for "a hypothetical but realistic" biography of the writer,
# and the check read "as a fictional master saddler" as a role-play persona (review r2)
QUOTE_PERSONA = (
    ' That holds when the draft calls its subject hypothetical, fictional or imagined ("me, the '
    'hypothetical locksmith", "as a fictional locksmith named Jane"): the writer asked for it '
    "to be written about themselves, so what it says of its subject is said of the writer."
)
QUOTE_KIND_PROSE = (
    "The statement below is one bullet of one readout of a language model's internal activations."
)
# the prose check shows the statement inside its own readout line (never the conversation, the
# digest or another readout): enough to resolve a subject the bullet's cut-off start leaves out
QUOTE_CONTEXT = (
    "The statement is first shown inside the readout it was taken from. The bullets of a "
    "readout (separated by ⁞) come from one reading of the text; often they are separate "
    "attempts that all begin at the same point of the text the model was reading, so a bullet "
    "may begin or end in the middle of a sentence or a word, and the subject of its first words"
    " can be missing. Use the readout ONLY to work out who or what the statement is about: when"
    ' the other bullets open by naming the writer ("me, ...", "you, ...", "for my ...", "the '
    'user ..."), an opening such as ", the hypothetical locksmith, based on this life" or "/me '
    'as a locksmith" continues that same sentence and is about the writer. Readouts also mix '
    '"I", "you" and "the user" freely for the writer: a statement that says "you" and "I" is '
    "about one person unless it clearly speaks of two. The value itself must be stated in the "
    "statement: a value that only another bullet of the readout states does not count, and "
    "nothing outside the statement is evidence. A readout with no ⁞ is the statement alone.\n"
    "\n"
    "<readout>\n"
    "{context}\n"
    "</readout>\n"
    "\n"
)
QUOTE_KIND_TOKENS = (
    'The statement below is one ranked list of top vocabulary tokens (" | " separated) taken '
    "from readouts of a language model's internal activations; tokens of the list may be read"
    " together."
)
UMH_QUOTE_USER = (
    _QUOTE_TEMPLATE.replace("{statement_kind}", QUOTE_KIND_PROSE)
    .replace("{context_block}", QUOTE_CONTEXT)
    .replace("{persona_note}", QUOTE_PERSONA)
)
# a token list is its own readout and no draft: this check's text is as it was before review r2
UMH_QUOTE_USER_TOKENS = (
    _QUOTE_TEMPLATE.replace("{statement_kind}", QUOTE_KIND_TOKENS)
    .replace("{context_block}", "")
    .replace("{persona_note}", "")
)

QUOTE_RULE_FACT = (
    "A place the writer lives in or works in day to day (the country, or a city or region inside"
    " it), or a demonym, states a country of residence. A life "
    'situation must be stated itself or through the event that defines it ("got out three '
    'weeks ago and reports to a parole officer" states on parole), not through a side effect '
    'of it ("has to be home by nine").'
)
QUOTE_RULE_STATE = (
    'The value is a feeling of the writer\'s own. A vaguer feeling ("upset", "stressed", '
    '"struggling") or a weaker neighbouring one states none of the candidates. A description '
    "of events with no feeling stated is a clue."
)
QUOTE_RULE_STATE_MIXED = (
    "The writer may have more than one feeling. A feeling in the statement that is not on the"
    " list is expected: ignore it. It does not make the statement fit two candidates."
)
QUOTE_RULE_STANCE = (
    "The value is what the writer wants from the exchange, or how they regard the thing they "
    "ask about. The statement must say that the writer wants, needs, seeks or holds it; a "
    "description of a reply or of an assistant's manner states none. A list of tokens cannot "
    'state an aim or a stance: choose "{cannot}".'
)
QUOTE_RULE_EXPERTISE = (
    "The value is the person's level in the subject: beginner (new to it), intermediate (past"
    " the basics, still learning), advanced (highly skilled, not a professional or an "
    'authority), expert (a professional, specialist, master or authority). "Experienced", '
    '"knowledgeable", "skilled", "keen" or "an amateur" alone state none. The level must be '
    'the writer\'s: the pitch of a planned reply ("a simple step-by-step answer", "skip the '
    'basics") states a level only when the statement ties it to the writer ("explain it '
    'simply because they are new to this").'
)


# the gate conditions that earn a re-ask, each with its reason
UMH_RETRY_REASONS: dict[str, str] = {
    "quote": UMH_RETRY_REASON_QUOTE,
    "bullet": UMH_RETRY_REASON_BULLET,
    "echo": UMH_RETRY_REASON_ECHO,
    "desc_rejected": UMH_RETRY_REASON_DESC,
}
TYPE_RULES: dict[str, str] = {
    "FACT": TYPE_RULE_FACT,
    "STATE": TYPE_RULE_STATE,
    "STANCE": TYPE_RULE_STANCE,
    "EXPERTISE": TYPE_RULE_EXPERTISE,
}
QUOTE_RULES: dict[str, str] = {
    "FACT": QUOTE_RULE_FACT,
    "STATE": QUOTE_RULE_STATE,
    "STANCE": QUOTE_RULE_STANCE,
    "EXPERTISE": QUOTE_RULE_EXPERTISE,
}

UMH_ATTRIBUTE_SCHEMA: dict = schema_block(
    "umh_attribute",
    {
        "choice": {"type": "integer"},
        "basis": {"type": "string", "enum": list(BASES)},
        "evidence": {"type": "string"},
        "rationale": {"type": "string"},
    },
    ["choice", "basis", "evidence", "rationale"],
)
UMH_QUOTE_SCHEMA: dict = schema_block(
    "umh_quote",
    {"choice": {"type": "integer"}, "rationale": {"type": "string"}},
    ["choice", "rationale"],
)

PROMPTS: dict[str, str] = {
    "UMH_SYSTEM": UMH_SYSTEM,
    "UMH_USER": UMH_USER,
    "UMH_USER_SUMMARY": UMH_USER_SUMMARY,
    "NATIVE_DESCRIPTION": NATIVE_DESCRIPTION,
    "SUMMARY_DESCRIPTION": SUMMARY_DESCRIPTION,
    "UMH_RULES": UMH_RULES,
    "TYPE_RULE_FACT": TYPE_RULE_FACT,
    "TYPE_RULE_STATE": TYPE_RULE_STATE,
    "TYPE_RULE_STATE_MIXED": TYPE_RULE_STATE_MIXED,
    "TYPE_RULE_STANCE": TYPE_RULE_STANCE,
    "GOAL_DEFINITIONS": GOAL_DEFINITIONS,
    "TYPE_RULE_EXPERTISE": TYPE_RULE_EXPERTISE,
    "UMH_BASIS": UMH_BASIS,
    "UMH_QUOTE": UMH_QUOTE,
    "TOKEN_NOTE_UMH": TOKEN_NOTE_UMH,
    "UMH_RETRY": UMH_RETRY,
    "UMH_RETRY_REASON_QUOTE": UMH_RETRY_REASON_QUOTE,
    "UMH_RETRY_REASON_BULLET": UMH_RETRY_REASON_BULLET,
    "UMH_RETRY_REASON_ECHO": UMH_RETRY_REASON_ECHO,
    "UMH_RETRY_REASON_DESC": UMH_RETRY_REASON_DESC,
    "UMH_RETRY_AGAIN": UMH_RETRY_AGAIN,
    "UMH_QUOTE_SYSTEM": UMH_QUOTE_SYSTEM,
    "UMH_QUOTE_USER": UMH_QUOTE_USER,
    "UMH_QUOTE_USER_TOKENS": UMH_QUOTE_USER_TOKENS,
    "QUOTE_KIND_PROSE": QUOTE_KIND_PROSE,
    "QUOTE_KIND_TOKENS": QUOTE_KIND_TOKENS,
    "QUOTE_CONTEXT": QUOTE_CONTEXT,
    "QUOTE_PERSONA": QUOTE_PERSONA,
    "QUOTE_RULE_FACT": QUOTE_RULE_FACT,
    "QUOTE_RULE_STATE": QUOTE_RULE_STATE,
    "QUOTE_RULE_STATE_MIXED": QUOTE_RULE_STATE_MIXED,
    "QUOTE_RULE_STANCE": QUOTE_RULE_STANCE,
    "QUOTE_RULE_EXPERTISE": QUOTE_RULE_EXPERTISE,
    "SUMMARY_NOTE": SUMMARY_NOTE,
    "SUMMARY_NOTE_ABSTRACTIVE": SUMMARY_NOTE_ABSTRACTIVE,
    "UMH_TASK_NOTE": UMH_TASK_NOTE,
    "CANNOT": mc.CANNOT,
}


def rule_group(part_type: str) -> str:
    """FACT / STATE / STANCE / EXPERTISE for a part's bank ``type``."""
    return RULE_OF.get(part_type, "FACT")


def type_rule(part_type: str, *, mixed: bool = False) -> str:
    """The main prompt's block for a part: its rule group's text, then the mixed-state block
    (a part of a ``mixed_state`` item) or the goal definitions (a ``goal`` part)."""
    group = rule_group(part_type)
    text = TYPE_RULES[group]
    if group == "STATE" and mixed:
        text += "\n\n" + TYPE_RULE_STATE_MIXED
    if part_type == "goal":
        text += "\n\n" + GOAL_DEFINITIONS
    return text


def quote_type_rule(part_type: str, *, mixed: bool = False) -> str:
    """The quote check's block for a part (as :func:`type_rule`)."""
    group = rule_group(part_type)
    text = QUOTE_RULES[group]
    if group == "STATE" and mixed:
        text += "\n\n" + QUOTE_RULE_STATE_MIXED
    if part_type == "goal":
        text += "\n\n" + GOAL_DEFINITIONS
    return text


def _render(
    template: str,
    user_turn: str,
    readout: str,
    options: Sequence[str],
    judge_label: str,
    part_type: str,
    mixed: bool,
    token_note: str,
    summary_note: str = "",
) -> str:
    return (
        template.replace("{summary_note}", summary_note)
        .replace("{rules}", UMH_RULES)
        .replace("{type_rule}", type_rule(part_type, mixed=mixed))
        .replace("{token_note}", token_note)
        .replace("{basis}", UMH_BASIS)
        .replace("{quote_rule}", UMH_QUOTE)
        .replace("{options_block}", option_lines(options))
        .replace("{cannot}", mc.CANNOT)
        .replace("{judge_label}", judge_label)
        .replace("{readout}", readout)
        .replace("{user_turn}", user_turn)
    )


def render_user(
    user_turn: str,
    readout: str,
    options: Sequence[str],
    judge_label: str,
    part_type: str,
    *,
    mixed: bool = False,
    token_note: str = TOKEN_NOTE_UMH,
) -> str:
    """Native mode: one readout (one sample, or one rendered token list), one part."""
    return _render(UMH_USER, user_turn, readout, options, judge_label, part_type, mixed, token_note)


def render_user_summary(
    user_turn: str,
    note: str,
    summary: str,
    options: Sequence[str],
    judge_label: str,
    part_type: str,
    *,
    mixed: bool = False,
    token_note: str = TOKEN_NOTE_UMH,
) -> str:
    """Summary mode: the item's digest, one part; ``note`` = the digest note without the token
    rule (the template always carries it)."""
    return _render(
        UMH_USER_SUMMARY,
        user_turn,
        summary,
        options,
        judge_label,
        part_type,
        mixed,
        token_note,
        note,
    )


def render_quote_check(
    statement: str,
    quote: str,
    options: Sequence[str],
    judge_label: str,
    part_type: str,
    *,
    mixed: bool = False,
    tokens: bool = False,
    context: str = "",
) -> str:
    """The blind quote check: ONE statement and the quoted part, the part's label and its options
    in the same order; never the conversation, the digest or the pick. A prose statement is
    shown inside ``context``, the readout line it is one bullet of (the statement itself when
    none is given); a token list is its own readout and is shown alone."""
    template = UMH_QUOTE_USER_TOKENS if tokens else UMH_QUOTE_USER
    return (
        template.replace("{type_rule_quote}", quote_type_rule(part_type, mixed=mixed))
        .replace("{options_block}", option_lines(options))
        .replace("{cannot}", mc.CANNOT)
        .replace("{judge_label}", judge_label)
        .replace("{quote}", quote)
        .replace("{statement}", statement)
        .replace("{context}", context or statement)
    )


def retry_text(choice: object, value: str, quote: str, gate: str, *, again: bool = False) -> str:
    """One re-ask block, appended to the draw's own user turn after the blocks of its earlier
    re-asks (``again`` = it is not the first). The same text whatever the pick was."""
    return (
        (UMH_RETRY_AGAIN if again else UMH_RETRY)
        .replace("{reason}", UMH_RETRY_REASONS[gate])
        .replace("{choice}", str(choice))
        .replace("{value}", value)
        .replace("{cannot}", mc.CANNOT)
        .replace("{quote}", quote[:RETRY_QUOTE_CHARS])
    )
