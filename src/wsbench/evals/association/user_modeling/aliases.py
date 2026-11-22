"""The user_modeling value lexicon and option pools (um-v3.2; data only, frozen). The values
live in ``aliases.json`` beside this file; this module loads them into the same names and types.

Provenance: proposed offline by Claude Opus 5.5 on 2026-10-30
(``/workspace/root/wsb-bp/um_build/propose_aliases.py``: every pool value's naming forms —
the value, inflections, synonyms, demonyms, a more specific value, CJK translations; for each
continent every country in it, en + demonym + zh), then hand-reviewed
(``build_aliases.py``: dropped "english" for united kingdom, "cook" for chef, bare decade words
for age bands, two mis-segmented CJK forms; added "9-to-5" and other employment synonyms,
continent sub-regions such as "scandinavia" / "east asia"; for a continent, the full lexicon of
every pool country inside it). Checked against the replay of every gold pick of the cached
um-v2 summary run (``tests/fixtures/user_modeling_gate_cases.json``). The lexicon is part of
the instrument: an edit bumps ``prompts.CALL_VERSION``. um-v3.3 (2026-10-31, final r1): added
dude / bro (male), angler (fisherman), locksmithing, stay-at-home spouse (homemaker) and surviving
spouse (widowed); dropped "fisher" / "fishers" (a surname: "Captain Fisher"); round 3: hunk /
fella (male), keysmith (locksmith), "loss of a spouse" (widowed), plural homemakers, and for each
age band "age N" / "aged N" for every N inside it and every narrower "x-y" range inside it
("age 60", "58-62" for 56-65). um-v3.4 (2026-11-01, round 4, MC leakage standard): no form
changed; option-list data only (``SHOWN_POOL``: Gender shows male / female / nonbinary;
``COUNTRY_REGIONS``; a second Occupation neighbour). um-v3.5 (2026-11-04): no form changed;
``NEIGHBOURS`` for the 6 Country and 6 Occupation golds of the new selfdescribe candidates (9 of
them are golds of bank v3's 79 new items; none is a gold of bank v1 / v2, so their option lists
are unchanged).

``VALUE_ALIASES[value]`` lists the forms that NAME a value (``mc.form_in``: Latin forms
word-bounded, CJK forms as substrings; a quote without Latin letters passes only on a listed form
in its script). No CJK form is a single character (um-v3.2: a CJK form matches as a substring,
so 他 would hit 其他 "other", 女 女演员 "actress", 猫 熊猫 "panda", 狗 热狗 "hot dog"), and a CJK
form inside a longer form of another value of its class (道教 in 神道教) is masked by the gate
(``options.shadow_forms``). Gender forms are person-reference words only, never gendered role
nouns (actress, actor). Words merely associated with a value (foods, customs, practices,
objects, landscapes) are never listed.
"""

import json
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).with_name("aliases.json")
_DATA: dict[str, Any] = json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _tuples(table: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    return {key: tuple(values) for key, values in table.items()}


# every value that can be shown, per attr_class (mutually exclusive within a class)
UM_OPTION_POOL: dict[str, tuple[str, ...]] = _tuples(_DATA["UM_OPTION_POOL"])
UM_OPTION_POOL["ReligiousAffiliation"] = UM_OPTION_POOL["Religion"]

# values that are not mutually exclusive with the gold, or are near aliases of it: never a
# distractor for that gold (a distractor must never also be true of the user). married /
# separated: a separated person is still married; agnostic / atheist: "agnostic atheist" is a
# common self-description
UM_EXCLUDE: dict[str, frozenset[str]] = {
    key: frozenset(values) for key, values in _DATA["UM_EXCLUDE"].items()
}

# hard neighbours (2 per Country gold; 2 per Occupation gold since um-v3.4, 1 before): always
# among the distractors, so a readout naming only the region ("Central America", "Korean or
# Japanese") or the domain singles out none, and every list holds >= 2 same-topic confusers
# (Camila r2, 2026-11-01).
# um-v3.5 (2026-11-04), the entries from "japan" on: the golds of the new selfdescribe
# candidates (bank v3), each inside its existing COUNTRY_REGIONS region / the existing
# Occupation pool, so no existing gold's draw changes
# (tests/golden/user_modeling_options_v4.json regenerates byte-identical)
NEIGHBOURS: dict[str, tuple[str, ...]] = _tuples(_DATA["NEIGHBOURS"])

# um-v3.4 (MC leakage standard, Camila r2): the Country pool by region. A Country list is the
# gold's region triple (gold + its two NEIGHBOURS) plus three-country triples of two OTHER
# regions plus one country of no region, so every list holds three regional clusters and the
# gold's is not the only one ("the gold always sits in the visible cluster of 3", ANSWERS_R2 Q13)
COUNTRY_REGIONS: dict[str, tuple[str, ...]] = _tuples(_DATA["COUNTRY_REGIONS"])
COUNTRY_UNGROUPED: tuple[str, ...] = tuple(_DATA["COUNTRY_UNGROUPED"])

# um-v3.4 (MC leakage standard): the values SHOWN for a class where the pool holds values no bank
# gold can plausibly be. Gender golds are male / female only (12 / 4): the five-way list
# (genderfluid / agender) lowered chance to 1/5 under a guesser that splits male / female and
# failed the floors; a binary list left ONE same-topic confuser, below the standard's >= 2
# (review r3 of #213). Male / female / nonbinary holds two and passes (blind 0.200, described
# 0.184 vs chance 0.155)
SHOWN_POOL: dict[str, tuple[str, ...]] = _tuples(_DATA["SHOWN_POOL"])

# option text where the bare value is ambiguous
DISPLAY: dict[str, str] = dict(_DATA["DISPLAY"])

VALUE_ALIASES: dict[str, tuple[str, ...]] = _tuples(_DATA["VALUE_ALIASES"])
