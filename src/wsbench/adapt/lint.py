"""Invariants a candidate must meet before it is gated (references/families.md, per family). Each
problem is ``"<check>: detail"``; an empty list is a clean item. These are the construction rules
of the original banks; adapting changes difficulty, never these."""

import json
import re
from collections.abc import Callable

from .conjstage import N_OPTIONS
from .gate import _has_form, fold, words

REQUIRED: dict[str, tuple[str, ...]] = {
    # bank v2 (plan 0039): the MC options are part of the item; the plan, not the item, sets
    # the read sites (the summarize suffix), so eval_render / readout are no longer required
    "association": ("name", "prompt", "intermediates", "mc"),
    # bank v5 (plan 0060 A2): slice, task_context and the frozen options are item content
    "basic_readout_st": (
        "name",
        "subfamily",
        "prompt",
        "eval_render",
        "readout",
        "slice",
        "task_context",
        "mc",
    ),
    "multihop_st": ("name", "prompt", "target", "intermediates", "eval_render", "readout"),
    "multilingual_st": ("name", "prompt", "target", "intermediates", "eval_render", "readout"),
    "typo_st": ("name", "prompt", "intermediates", "eval_render", "readout"),
    "poetry": ("name", "prompt", "intermediates", "eval_render", "readout"),
    "chain_intermediates": ("name", "prompt", "start", "intermediates", "answer", "depth"),
    "arithmetic_intermediates": ("name", "variant", "prompt", "intermediates", "answer"),
    "relational_multihop": ("id", "scene", "stimulus", "hop1", "hop2", "gold"),
    "conjunctive_association": ("id", "stimulus", "asked_question", "gold_label", "mc_options"),
    "role_bound_association": ("id", "pair_id", "stimulus", "asked_question", "gold_label"),
    "user_modeling": ("name", "subfamily", "messages", "attr", "attr_label", "units"),
    "buggy_code": ("name", "src", "code", "verified"),
    "moral_rationale": ("id", "topic_id", "stimulus", "question", "answer_format"),
    "directed_modulation": ("name", "subfamily", "concept", "carrier", "prompt", "assistant"),
}
MT = {
    "basic_readout",
    "multilingual",
    "multilingual_multihop",
    "typo",
    "multilingual_typo",
}
MT_REQUIRED = ("name", "subfamily", "prompt", "target", "units", "probe_token_lens", "readout")


def _leaks(prompt: str, forms: list[str]) -> list[str]:
    return [f for f in forms if f and _has_form(prompt, f)]


def _num_leak(prompt: str, values: list) -> list[str]:
    """Values written as a numeral in the prompt, signed or absolute."""
    nums = {float(n) for n in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?!\d|\.\d)", prompt)}
    out = []
    for v in values:
        try:
            if abs(float(v)) in nums:
                out.append(str(v))
        except (TypeError, ValueError):
            continue
    return out


def _association_mc(it: dict) -> list[str]:
    """Bank v2 options (plan 0039 §C3 rules ii / iv, the mechanical part; the scene screen is
    ``scripts/association_distractors.py``): the gold is the item's latent, 7 distinct
    distractors, none naming or named by a gold form, none a cannot-tell text."""
    from wsbench import mc as _mc

    m = it.get("mc")
    if not isinstance(m, dict) or not m.get("gold"):
        return ["mc: no mc.gold"]
    gold, aliases = str(m["gold"]), [str(a) for a in m.get("aliases") or []]
    dis = [str(d) for d in m.get("distractors") or []]
    out = []
    if [fold(x) for x in it.get("intermediates") or []][:1] != [fold(gold)]:
        out.append("mc: gold is not intermediates[0]")
    if len(dis) != 7 or len({fold(d) for d in dis}) != 7:
        out.append(f"mc: need 7 distinct distractors (got {len(dis)})")
    forms = [gold, *aliases]
    for d in dis:
        if _mc.form_in(d, forms) or any(_mc.form_in(f, [d]) for f in forms):
            out.append(f"mc: distractor {d!r} names or is named by a gold form")
        if _mc.is_cannot(d):
            out.append(f"mc: distractor {d!r} is a cannot-tell text")
    return out


def _single_token(family: str, it: dict) -> list[str]:
    out = []
    prompt = it.get("prompt", "")
    latent = [str(x) for x in it.get("intermediates") or []]
    target = [it["target"]] if it.get("target") else []
    if family in ("association", "multihop_st", "multilingual_st", "basic_readout_st") and (
        leak := _leaks(prompt, latent + target + list(it.get("aliases") or []))
    ):
        out.append(f"leak: {leak} in prompt")
    if family == "association":
        out += _association_mc(it)
        if not prompt.rstrip().endswith((".", "!", "?")):
            out.append("format: association prompt must end in . ! or ?")
        if len(words(prompt)) < 8:
            out.append("format: association prompt under 8 words")
    if family == "multihop_st":
        if not prompt.startswith("Fact:"):
            out.append("format: multihop_st prompt must start with 'Fact:'")
        if target and latent and fold(target[0]) in {fold(x) for x in latent}:
            out.append("latent: bridge equals target")
        from . import families as _fams  # the gate refuses a multihop_st item with no bridge leg

        if not _fams._bridge_asks(it) and str(it.get("id") or it.get("name")) not in (
            _fams._skipped_bridges()
        ):
            out.append(
                "format: multihop_st item has no bridge question (the bridge leg is required)"
            )
    if family == "typo_st":
        last = (words(prompt) or [""])[-1]
        if not latent or fold(last) == fold(latent[0]):
            out.append("format: prompt must end in the misspelling, not the correction")
        if latent and _leaks(" ".join(prompt.split()[:-1]), latent):
            out.append("leak: correction appears earlier in the prompt")
        if prompt.rstrip()[-1:] in ".,;:!?\"'":
            out.append("format: typo_st prompt ends in punctuation")
    if family == "poetry":
        lines = prompt.split("\n")
        if len(lines) != 3 or lines[0] != "A rhyming couplet:" or not prompt.endswith((" ", "-")):
            out.append("format: poetry is 'A rhyming couplet:\\n<line 1>,\\n<stub> '")
    if family == "multilingual_st" and target and len(target[0]) >= 5:
        stem = fold(target[0])[:4]  # 'pommier' carries 'pomme' (audit 4B)
        if hit := [
            w for w in words(prompt) if fold(w).startswith(stem) and fold(w) != fold(target[0])
        ]:
            out.append(f"leak: {hit[:2]} shares the target's stem")
    if family == "multilingual_st" and latent and target:
        from difflib import SequenceMatcher

        if SequenceMatcher(None, fold(latent[0]), fold(target[0])).ratio() >= 0.85:
            out.append("latent: gloss is a cognate of the target")
    return out


def _computational(family: str, it: dict) -> list[str]:
    out = []
    inter = it.get("intermediates") or []
    if family == "chain_intermediates":
        vals = [it.get("start"), *inter, it.get("answer")]
        if len(set(map(str, vals))) != len(vals):
            out.append("latent: start, intermediates and answer must be distinct")
        for key in ("prompt", "prompt_first"):
            if it.get(key) and (leak := _num_leak(it[key], [*inter, it["answer"]])):
                out.append(f"leak: {leak} written in {key}")
        if int(it.get("depth") or len(inter) + 1) < 2:
            out.append("latent: depth 1 has no intermediate")
        from .generate import CHAIN_INTER

        lo, hi = CHAIN_INTER  # bank v2's rule: a v1 chain with a one-digit step is retired here
        if bad := [v for v in inter if not (lo <= int(v) <= hi)]:
            out.append(f"latent: intermediate(s) {bad} outside {lo}..{hi} (chain v2 rule)")
    if family == "arithmetic_intermediates":
        if leak := _num_leak(it.get("prompt", ""), inter):
            out.append(f"leak: step value {leak} written in prompt")
        if any(str(v) in map(str, it.get("operands") or []) for v in inter):
            out.append("latent: step equals an operand")
    if family == "relational_multihop" and (leak := _leaks(it["stimulus"], [it["gold"]])):
        out.append(f"leak: {leak} in stimulus")
    return out


GENERIC = {
    "root", "plant", "fruit", "vegetable", "animal", "bird", "fish", "tree", "flower", "cat", "dog",
    "corporation", "corp", "inc", "llc", "ltd", "company", "group", "co", "city", "town", "country",
    "kingdom", "republic", "state", "nation", "the", "a", "an", "of", "device", "tool", "object",
    "item",
}  # fmt: skip


def _padded(form: str) -> bool:
    ws = words(form)
    return len(ws) >= 2 and any(w.lower() in GENERIC for w in ws) and sum(
        w.lower() not in GENERIC for w in ws) == 1  # fmt: skip


OVERLAP_STOP = {
    "treaty",
    "battle",
    "theory",
    "law",
    "laws",
    "principle",
    "effect",
    "empire",
    "river",
    "mount",
    "lake",
    "saint",
    "great",
    "north",
    "south",
    "east",
    "west",
}


def _overlap(a: str, b: str) -> bool:
    """Two names overlap if one contains the other or they share a content word of >= 4 letters."""
    fa, fb = fold(a), fold(b)
    if not fa or not fb:
        return False
    if fa in fb or fb in fa:
        return True
    stop = GENERIC | OVERLAP_STOP
    wa = {w for w in words(fa) if len(w) >= 4 and w not in stop}
    return bool(wa & {w for w in words(fb) if len(w) >= 4 and w not in stop})


def _mt(family: str, it: dict) -> list[str]:
    out = []
    if family == "multilingual_typo" and it.get("adapt", {}).get("origin") == "authored":
        # plan 0075 §2.6: the content role's list as the registered bank's (4 distinct, no gold)
        blk = (it.get("mc") or {}).get("correction_native") or {}
        dis = [str(d) for d in blk.get("distractors") or []]
        glosses = [str(g) for u in it.get("units") or [] if u.get("role") == "correction_native"
                   for fs in (u.get("forms") or {}).values() for g in fs]  # fmt: skip
        if len({fold(d) for d in dis}) != 4 or len(dis) != 4:
            out.append(f"mc: need 4 distinct correction_native distractors (got {len(dis)})")
        golds = [set(words(fold(g))) for g in [blk.get("gold") or "", *glosses] if fold(g)]
        # a gloss's words all inside the distractor's, or the reverse ("thyroid gland" beside
        # "thyroid"); a shared head word ("the hormone insulin" / "the hormone adrenaline") or a
        # longer word ("parathyroid gland" / "thyroid gland") is the registered bank's own shape
        if hit := [d for d in dis if any(
                set(words(fold(d))) <= g or g <= set(words(fold(d))) for g in golds)]:  # fmt: skip
            out.append(f"mc: distractor {hit[0]!r} overlaps the correction's gloss")
    prompt = it.get("prompt", "")
    forms = [f for u in it.get("units") or [] for fs in (u.get("forms") or {}).values() for f in fs]
    long_words = {w for f in [it.get("target", ""), *forms] for w in words(f) if len(w) >= 4}
    if family not in ("typo", "multilingual_typo") and (
        hit := [w for w in long_words if _has_form(prompt, w)]
    ):
        out.append(f"leak: {sorted(hit)[:5]} in prompt")
    for u in it.get("units") or []:
        flat = [f for fs in (u.get("forms") or {}).values() for f in fs]
        if u.get("match") is not None and sorted(u["match"]) != sorted(flat):
            out.append(f"units: {u.get('role')} match != flattened forms")
        lens = (it.get("probe_token_lens") or {}).get("units", {}).get(u.get("role"), {})
        for lang, fs in (u.get("forms") or {}).items():
            if len(lens.get(lang) or []) != len(fs):
                out.append(f"units: probe_token_lens missing for {u.get('role')}/{lang}")
        multi = any(n > 1 for ls in lens.values() for n in ls)
        if u.get("required") and u.get("multi_token", True) and not multi:
            out.append(f"units: required {u.get('role')} has no multi-token form")
    # the scored latent's natural (canonical, first-listed) name must itself be multi-token: if it
    # is one token, a readout that states it plainly ("Microsoft") can never score (audit 4B)
    lens_u = (it.get("probe_token_lens") or {}).get("units", {})
    for u in it.get("units") or []:
        if not (u.get("required") and u.get("multi_token", True)):
            continue
        role, forms = u.get("role"), u.get("forms") or {}
        if role in ("correction", "correction_l2"):
            if family == "multilingual_typo":  # the native correction itself must be multi-token
                lang = next((k for k in forms if k not in ("en", "zh")), None)
                if lang and (lens_u.get(role, {}).get(lang) or [2])[0] == 1:
                    out.append("units: native correction is one token (uncreditable)")
            continue
        en, en_lens = forms.get("en") or [], lens_u.get(role, {}).get("en") or []
        # the plain name must itself be multi-token: a one-token canonical name, or a one-token head
        # padded with generic words ("carrot root", "Microsoft Corporation"), means a readout
        # that says the plain name can never score (audits 4B / 9B)
        # an alias may be one token (the scorer just won't credit it); the CANONICAL name may not
        if en_lens[:1] == [1]:
            out.append(f"units: {role} canonical name is one token (uncreditable)")
        elif en[:1] and _padded(en[0]):
            out.append(f"units: {role} pads a one-word name with generic words (uncreditable)")
    if family == "basic_readout" and it.get("eval_render") == "chat":
        out += _brmt_v4(it)  # v4: a question, not a completion (plan 0060 A2)
    elif prompt.rstrip() != prompt or prompt[-1:] in ".,;:!?\"'":
        out.append("format: mt prompt ends in space or punctuation")
    if family == "multilingual_multihop":  # bridge vs answer (audits 4B, 9B)
        answers = [it.get("target", ""), *(it.get("target_alts") or [])]
        bridges = [f for u in it.get("units") or [] if str(u.get("role", "")).startswith("bridge")
                   for fs in (u.get("forms") or {}).values() for f in fs]  # fmt: skip
        if hit := [(b, a) for b in bridges for a in answers if _overlap(b, a)]:
            out.append(f"latent: bridge overlaps the answer {hit[0]}")
    if family == "multilingual_typo":  # an L2 form of the answer echoed earlier in the prompt
        tw = it.get("typo_word") or ""
        head = prompt[: -len(tw)] if tw and prompt.endswith(tw) else prompt
        # v1: the L2 answer forms sat in the language unit; v2 (plan 0040): in correction_l2
        lang_forms = [f for u in it.get("units") or []
                      if u.get("role") in ("language", "correction_l2")
                      for k, fs in (u.get("forms") or {}).items() if k not in ("en", "zh")
                      for f in fs if len(f) >= 4]  # fmt: skip
        if hit := [f for f in lang_forms if _has_form(head, f)]:
            out.append(f"leak: answer form {hit[:2]} echoed in the prompt")
    if family in ("typo", "multilingual_typo"):
        tw = it.get("typo_word") or ""
        if not tw or not prompt.endswith(tw):
            out.append("format: prompt must end with typo_word")
        if it.get("target") and _has_form(prompt[: -len(tw) or None], it["target"]):
            out.append("leak: correction appears earlier in the prompt")
    return out


GENDERED = {"man", "woman", "husband", "wife", "mother", "father", "boyfriend", "girlfriend",
            "he", "she", "mr", "mrs", "guy", "girl", "boy", "lady", "gentleman",
            "bride", "bridesmaid", "bridesmaids", "groomsman", "groomsmen"}  # fmt: skip
# plan 0075 follow-up 2 (qwen3.5-0.8b delta audit): a wedding role names the speaker's gender
GENDERED_PHRASES = re.compile(
    r"\b(?:maid|matron) of honou?r\b|\b(?:the|a|as) groom\b", re.IGNORECASE
)  # "groom" alone is also a verb ("I groom my beard")


def _user_modeling(family: str, it: dict) -> list[str]:
    if family != "user_modeling" or it.get("adapt", {}).get("origin") != "authored":
        return []
    out = []
    if it.get("subfamily") != "selfdescribe":
        out.append("subfamily: authored user_modeling is selfdescribe only (never synthsys)")
    text = (it.get("messages") or [{}])[-1].get("content", "")
    forms = [str(it.get("attr", "")).replace("_", " ")]
    forms += [m for u in it.get("units") or [] for m in u.get("match") or []]
    if leak := _leaks(text, [f for f in forms if len(f) >= 4]):
        out.append(f"leak: {leak} in user text")
    if it.get("attr_label") == "gender":
        if hit := GENDERED & {w.lower() for w in words(text)}:
            out.append(f"leak: gendered self-reference {sorted(hit)}")
        elif m := GENDERED_PHRASES.search(text):
            out.append(f"leak: gendered self-reference [{m.group(0).lower()!r}]")
        if it.get("attr") not in ("male", "female"):  # the bank's values; others drift the latent
            out.append(f"latent: gender value {it.get('attr')!r} is not in the bank")
    if not text.endswith("Write a hypothetical but realistic Wikipedia biography infobox for me."):
        out.append("format: user turn must end with the infobox request")
    if (problem := um_gold_problem(it)) or (problem := um_alias_leak(it)):
        out.append(problem)
    return out


def um_alias_leak(it: dict) -> str | None:
    """Plan 0075 follow-up (qwen3-8b delta audit: 19 drops): a user turn that names the gold by
    any of its ``aliases.VALUE_ALIASES`` forms ("Helsinki" or "Finns" for finland),
    matched as the judge's value gate matches (``mc.form_in``), gives the attribute away. Every user
    turn is checked; the gold must already be registered (``um_gold_problem``)."""
    from wsbench import mc as _mc
    from wsbench.evals.association.user_modeling.aliases import VALUE_ALIASES
    from wsbench.evals.association.user_modeling.options import value_id

    forms = VALUE_ALIASES.get(value_id(str(it.get("attr", ""))), ())
    users = [m for m in it.get("messages") or [] if m.get("role") == "user"]
    for m in users or (it.get("messages") or [])[-1:]:
        hits = _mc.form_hits(str(m.get("content", "")), list(forms))
        if hits:
            return f"leak: gold alias {sorted(set(hits))} in user text (aliases.VALUE_ALIASES)"
    return None


def um_gold_problem(it: dict) -> str | None:
    """Plan 0075 §2.8: an authored gold must be a registered value (``aliases.VALUE_ALIASES``)
    in its class's option pool, so the judge's value gate and options need no per-set
    ``values.json`` entry (a class pool is never extended: it reshuffles registered options)."""
    from wsbench.evals.association.user_modeling.aliases import UM_OPTION_POOL, VALUE_ALIASES
    from wsbench.evals.association.user_modeling.options import value_id

    v, cls = value_id(str(it.get("attr", ""))), str(it.get("attr_class", ""))
    pool = {value_id(x) for x in UM_OPTION_POOL.get(cls, ())}
    if v not in VALUE_ALIASES or v not in pool:
        return f"latent: gold {v!r} is not a registered {cls} value (aliases.UM_OPTION_POOL)"
    return None


# plan 0075 (#372: country <-> capital questions left the benchmark): an authored English item
# whose question asks for, or goes through, a capital is rejected
CAPITAL_FAMILIES = frozenset({"basic_readout", "multihop_st", "association"})
# association joined in plan 0075 follow-up 2: the qwen3.5-0.8b refill shipped seven
# "its capital is Y" / "the capital of X" association prompts
_APOS = "['\u2019]"  # a straight or curly apostrophe
# the ordinary non-place senses ("a capital crime", "capital letter", "capital A", "its capital
# gains"): never a capital city (plan 0075 follow-up 2, association prompts)
_NOT_SEAT = (
    r"(?!\s+(?:letters?|[A-Z]\b|crimes?|offen[cs]es?|punishment|gains?|invest\w*|expenditures?|"
    r"markets?|goods|assets?))"
)
_CAPITAL = re.compile(
    r"\b(?:what|which|name)(?: city| town)?(?:'s| is| was)? (?:the |its )?(?:current |former )?"
    r"capital(?: city)? of\b"
    r"|\bcapital(?: city)? of\b[^.?]*\b(?:is|was)\s*$"  # a "Fact: The capital of X is" stem
    rf"|\b(?:what|which)(?:'s| is| was)? (?:the |its |their |\w+{_APOS}s )?capital\b{_NOT_SEAT}"
    rf"|\b(?:its|their|whose)\s+(?:national\s+)?capital\b(?!\s+in\s+\d){_NOT_SEAT}"
    rf"|\b(?:is|was|as) (?:the |its |a |\w+{_APOS}s )?(?:national )?capital\b(?!\s+in\s+\d)"
    rf"{_NOT_SEAT}"
    r"|\bseat of government\b",
    re.IGNORECASE,
)  # asks for, or goes through, a capital; a capital named as context ("the Byzantine capital
# in 1453", "signed in Italy's capital") passes


_THROUGH = re.compile(r"(?:(\S+)\s+)?\bcapital(?: city)? of (?:the )?[A-Z]")
_POSSESSIVE = re.compile(rf"\b[A-Z][\w-]+{_APOS}s (?:capital|seat)\b(?!\s+in\s+\d)")
# "the French capital": a demonym capital is a country's capital unless the city is named right
# after it ("the Ming capital of Beijing", "the Byzantine capital, Constantinople") or a year
# follows ("the Byzantine capital in 1453")
_ADJ_CAPITAL = re.compile(
    r"\b[Tt]he [A-Z][a-z]+ capital\b(?!(?: city)? of [A-Z]|,\s*[A-Z]|\s+in\s+\d)"
)
_NOT_CONTEXT = {"the", "a", "its", "their", "his", "her", "former", "old", "new", "current"}


def goes_through_capital(text: str) -> bool:
    """A question that passes through a named place's capital ("the museum in the capital of
    France", "the river through Japan's capital"); a capital named by a proper adjective as
    context ("the Ming capital of Beijing") or with a year ("Italy's capital in 1957") passes."""
    for m in _THROUGH.finditer(text):
        prev = (m.group(1) or "").strip(",;:(")
        if prev[:1].isupper() and prev.lower() not in _NOT_CONTEXT:
            continue  # "Ming capital of", "Byzantine capital of": a proper adjective
        if re.match(r"[^.?]{0,40}?\bin\s+\d{3,4}\b", text[m.end() :]):
            continue
        return True
    return bool(_POSSESSIVE.search(text) or _ADJ_CAPITAL.search(text))


_CAPITAL_EXTRA = re.compile(
    r"\b(?:new|national|administrative|future|federal|official)\s+capital(?:\s+city)?\b"
    r"(?!\s+(?:gains?|expenditures?|investments?|markets?|raise[sd]?|funds?|requirements?)\b)",
    re.IGNORECASE,
)


def asks_capital(text: str, strict: bool = False) -> bool:
    """#372's matcher on one text: it asks for, or goes through, a country's capital (the rule
    ``_capital`` applies to authored items; plan 0077 reuses it on its funded pools' rows).
    ``strict`` also catches a named kind of capital ("its new capital", "the national capital")
    that the authored-item rule lets through; it is used on the funded pool rows only."""
    if not text:
        return False
    hit = bool(_CAPITAL.search(text) or goes_through_capital(text))
    return hit or (strict and bool(_CAPITAL_EXTRA.search(text)))


def _capital(family: str, it: dict) -> list[str]:
    if family not in CAPITAL_FAMILIES or it.get("adapt", {}).get("origin") != "authored":
        return []
    texts = [str(it.get(k) or "") for k in ("prompt", "bridge_question", "hop2_question")]
    texts += [str(p) for p in it.get("shortcut_prompts") or []]
    if any(_CAPITAL.search(t) or goes_through_capital(t) for t in texts):
        return ["latent: country <-> capital questions left the benchmark (#372)"]
    return []


def _role_bound(family: str, it: dict) -> list[str]:
    if family != "role_bound_association" or it.get("adapt", {}).get("origin") != "authored":
        return []
    out = []
    text, names = it.get("stimulus", ""), it.get("names") or {}
    if hit := [w for w in (it.get("blocklist") or {}).get("roles", []) if _has_form(text, w)]:
        out.append(f"leak: role words {hit[:5]} in stimulus")
    if "\t" in text:  # #321: a stray tab garbles a word (bank v2 dropped those pairs)
        out.append("format: tab character in stimulus (#321)")
    if (
        not names.get("a")
        or not names.get("b")
        or not all(_has_form(text, n) for n in names.values())
    ):
        out.append("format: both first names must appear in the stimulus")
    if it["adapt"].get("tier") == "t1" and len(text.split()) > 70:
        out.append("format: t1 scene over 70 words")
    from wsbench.evals.anti_bag_of_features.role_bound_association.gate import load_lexicon

    lex = load_lexicon()  # plan 0042 C2.5: the judge falls back to terms=[role], no near role
    for role in (it.get("role_a"), it.get("role_b")):
        if role and not lex.has(role):
            out.append(f"lexicon: role {role!r} not in roles_v1.json")
    from wsbench.evals.anti_bag_of_features.role_bound_association.gate import load_actions

    # plan 0075 §2.7: the gate / judge read the action's lexicon entry (an adapted pair whose
    # action has none exits); the authored action must be one of actions_v1.json's
    if (act := it.get("action")) and act not in load_actions().forms:
        out.append(f"lexicon: action {act!r} not in actions_v1.json")
    return out


def _buggy(family: str, it: dict) -> list[str]:
    if family != "buggy_code" or it.get("adapt", {}).get("origin") != "authored":
        return []
    out = []
    v = str(it.get("verified") or "")
    crash = it.get("src") == "buggy" and it.get("consequence_class") == "crash"
    if not v.startswith("exec:"):
        out.append("verify: the program hangs, is nondeterministic or was not run")
    elif v.startswith("exec: exit 0") == crash:
        out.append(f"verify: exit status does not match the class ({v[:40]})")
    code = it.get("code", "").lower()
    if hit := [t for t in it.get("level2_tokens") or [] if t and t.lower() in code]:
        out.append(f"leak: bug words {hit} in the code")
    # plan 0066 §2.3: the wsb-new-questions guards
    raw = str(it.get("code") or "")
    if bad := forbidden_io(raw):
        out.append(f"io: forbidden imports / IO {bad}")
    stdout = stdout_of(v)
    if stdout is not None and "\n" in stdout:
        out.append("stdout: not single-line or ' | '-joined")
    if it.get("src") == "buggy" and stdout and literal_copy(stdout, raw):
        out.append(f"literal: the output {stdout[:40]!r} is a copy of the program's literals")
    return out


_FORBIDDEN_MODULES = {"random", "time", "subprocess", "os"}
_FORBIDDEN_CALLS = {"open", "input", "eval", "exec"}
_FORBIDDEN_RE = re.compile(
    r"\b(?:import|from)\s+(?:random|time|subprocess|os)\b|\b(?:open|input|eval|exec)\s*\("
    r"|\bsys\.stdin\b|\bos\.|\bsubprocess\b|\brandom\.|\btime\."
)


def forbidden_io(code: str) -> list[str]:
    """Imports of ``random`` / ``time`` / ``subprocess`` / ``os``, calls of ``open`` / ``input``
    / ``eval`` / ``exec``, and ``sys.stdin`` / ``os.`` uses (AST; a regex when the program does
    not parse, e.g. a crash-tier syntax error). Strings and identifiers merely containing
    these words do not count."""
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return sorted({m.group().strip() for m in _FORBIDDEN_RE.finditer(code)})
    hits: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits |= {a.name for a in node.names if a.name.split(".")[0] in _FORBIDDEN_MODULES}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            hits |= {f"from {mod}"} if mod.split(".")[0] in _FORBIDDEN_MODULES else set()
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            hits |= {f"{node.func.id}("} if node.func.id in _FORBIDDEN_CALLS else set()
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            mod, attr = node.value.id, node.attr
            hits |= {f"{mod}.{attr}"} if mod == "os" or (mod, attr) == ("sys", "stdin") else set()
    return sorted(hits)


def stdout_of(verified: str) -> str | None:
    """The stdout recorded in a ``verify.verify_python`` string, or None if it has none."""
    head = "; stdout = '"
    if head not in verified:
        return None
    rest = verified.split(head, 1)[1]
    if (cut := rest.rfind("'; last = '")) >= 0:
        return rest[:cut]
    return rest[:-1] if rest.endswith("'") else rest


def _literals(code: str) -> set[str]:
    """The string and number literals written in the program (whitespace-normalised); bools and
    None are keywords, not literals. A regex fallback when the program does not parse."""
    import ast

    out: set[str] = set()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        for m in re.finditer(r"'([^'\\\n]*)'|\"([^\"\\\n]*)\"|(-?\d+(?:\.\d+)?)", code):
            out.add(next(g for g in m.groups() if g is not None))
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                node = node.operand
                neg = True
            else:
                neg = False
            if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
                continue
            if isinstance(node.value, str):
                out.add(node.value)
            elif isinstance(node.value, int | float):
                out.add(("-" if neg else "") + repr(node.value))
                if neg:
                    out.add(repr(node.value))
    return {n for lit in out if (n := " ".join(lit.split()))}


def literal_copy(stdout: str, code: str) -> bool:
    """Plan 0066 §2.3: the whole stdout (whitespace-normalised) is TWO OR MORE string / number
    literals of the program joined BY SEPARATORS ("Ann Ann" from ``print(first + " " + first)``,
    "Ann | Bob" from ``" | ".join(...)``). Rule: content pieces are literals with a letter or digit;
    between two consecutive pieces there must be a separator, i.e. a single space and/or a
    punctuation-only literal of the program (a joiner such as ``" | "`` or ``", "``) with optional
    spaces around it. A stdout that is an unseparated concatenation is NOT a copy: a computed
    ``10`` / ``12`` / ``100`` passes even when ``0`` and ``1`` are literals. A single literal is a
    selection the program computes (``70`` from ``[70, 95, 88]``, a categorical "fail"), so it
    passes too."""
    s = " ".join(stdout.split())
    lits = _literals(code)
    if not s or not lits:
        return False
    content = [lit for lit in lits if any(c.isalnum() for c in lit)]
    joiners = [lit for lit in lits if not any(c.isalnum() for c in lit)]
    seps = {" "} | {f"{a}{j}{b}" for j in joiners for a in ("", " ") for b in ("", " ")}
    # state (position, after_piece) -> most pieces reaching it (capped at 2)
    best: dict[tuple[int, bool], int] = {(0, False): 0}
    for i in range(len(s) + 1):
        for after in (False, True):
            if (i, after) not in best:
                continue
            n = best[(i, after)]
            for tok in seps if after else content:
                if s.startswith(tok, i):
                    key = (i + len(tok), not after)
                    best[key] = max(best.get(key, 0), min(2, n + (0 if after else 1)))
    return best.get((len(s), True), 0) >= 2


def _option_rules(prompt: str, gold: list[str], dis: list[str], dal: dict) -> list[str]:
    """The v5 / v4 option rules a candidate can be checked for mechanically: distinct
    distractors, none naming or named by a gold form or another distractor, none in the
    question (a readout would echo it)."""
    from wsbench import mc as _mc

    def clash(a: list[str], b: list[str]) -> bool:
        return any(_mc.form_in(x, [y]) or _mc.form_in(y, [x]) for x in a for y in b if x and y)

    out = []
    if len({fold(d) for d in dis}) != len(dis):
        out.append("mc: repeated distractor")
    seen: list[list[str]] = []
    for d in dis:
        forms = [d, *[str(a) for a in dal.get(d) or []]]
        if gold and clash(forms, gold):
            out.append(f"mc: distractor {d!r} names or is named by a gold form")
        if any(clash(forms, s) for s in seen):
            out.append(f"mc: distractor {d!r} shares a form with another option")
        if _mc.form_in(prompt, [d]):
            out.append(f"leak: option {d!r} in prompt")
        if _mc.is_cannot(d):
            out.append(f"mc: distractor {d!r} is a cannot-tell text")
        seen.append(forms)
    return out


BR_SUFFIX = "? Answer in one word."


def _basic_readout_v5(family: str, it: dict) -> list[str]:
    """basic_readout_st bank v5 (plan 0060 A2): the question form, 4 distractors, a provisional
    ``gold_position``. An implicit item's gold is the subject's (re-keyed after the gate by
    ``rebuild.subject_mc``), so only its list's own rules are checked here."""
    if family != "basic_readout_st":
        return []
    out = []
    prompt = str(it.get("prompt") or "")
    if not prompt.endswith(BR_SUFFIX):
        out.append(f"format: basic_readout_st question must end {BR_SUFFIX!r}")
    m = it.get("mc")
    if not isinstance(m, dict):
        return [*out, "mc: no mc block"]
    dis = [str(d) for d in m.get("distractors") or []]
    if len(dis) != 4:
        out.append(f"mc: need 4 distractors (got {len(dis)})")
    pos = m.get("gold_position")
    if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos <= len(dis):
        out.append(f"mc: gold_position {pos!r} is not a slot")
    implicit = it.get("subfamily") == "implicit"
    gold = [] if implicit else [str(m.get("gold") or ""), *map(str, m.get("aliases") or [])]
    if not implicit and fold(str(m.get("gold") or "")) != fold(str(it.get("target") or "")):
        out.append("mc: gold is not the target")
    return out + _option_rules(prompt, gold, dis, m.get("distractor_aliases") or {})


def _brmt_v4(it: dict) -> list[str]:
    """basic_readout bank v4 (plan 0060 A2): a chat QUESTION graded by ``name_forms``."""
    out = []
    prompt = str(it.get("prompt") or "")
    if prompt.rstrip() != prompt or not prompt.endswith("?"):
        out.append("format: basic_readout v4 question must end in '?'")
    forms = [str(f) for fs in ((it.get("name_forms") or {}).get("readout") or {}).values()
             for f in fs]  # fmt: skip
    if not forms:
        out.append("keys: missing name_forms.readout")
    from wsbench import mc as _mc

    if hit := [f for f in forms if _mc.form_in(prompt, [f])]:
        out.append(f"leak: name form {hit[:3]} in prompt")
    block = (it.get("mc") or {}).get("readout") or {}
    dis = [str(d) for d in block.get("distractors") or []]
    if not block.get("gold") or len(dis) != 4:
        out.append(f"mc: need mc.readout gold + 4 distractors (got {len(dis)})")
    return out + _option_rules(prompt, forms, dis, {})


# plan 0075 §2.4 (#323, bank v5's construction): the relations bank v5 dropped
_MH_BANNED = re.compile(
    r"\b(?:language|languages|spoken|opposite|currency|currencies|letter|letters|spell|"
    r"spelled|spelling|symbol)\b",
    re.IGNORECASE,
)


def _multihop_v5(family: str, it: dict) -> list[str]:
    """An authored multihop_st item carries the bank-v5 legs' inputs (``hop2_question``, >= 2
    ``shortcut_prompts`` naming no bridge form) and none of the dropped relations; its answer
    shares no stem with the bridge."""
    if family != "multihop_st" or it.get("adapt", {}).get("origin") != "authored":
        return []
    out = []
    if not str(it.get("hop2_question") or "").strip():
        out.append("keys: missing hop2_question (bank v5's second-hop leg)")
    probes = [str(p) for p in it.get("shortcut_prompts") or [] if str(p).strip()]
    if len(probes) < 2:
        out.append("keys: need >= 2 shortcut_prompts (bank v5's shortcut legs)")
    bridges = [str(b) for b in it.get("intermediates") or [] if str(b)]
    bridges += [str(b) for b in it.get("bridge_aliases") or [] if str(b)]
    if hit := [p for p in probes if _leaks(p, bridges)]:
        out.append(f"leak: a shortcut prompt names the bridge ({hit[0][:50]})")
    texts = [str(it.get("prompt") or ""), str(it.get("bridge_question") or "")]
    if m := next((m for t in texts if (m := _MH_BANNED.search(t))), None):
        out.append(f"latent: bank v5 dropped this relation ({m.group(0)!r}; #323)")
    target = str(it.get("target") or "")
    if target and any(_overlap(target, b) for b in bridges):
        out.append("latent: the answer derives from the bridge's name (#323)")
    return out


def _multihop_buildable(family: str, it: dict) -> list[str]:
    """Plan 0075 follow-up: an authored multihop_st item whose options ``build_multihop_mc --bank``
    cannot build (its own ``build_mc`` raises: a country outside ``COUNTRIES``, a number past
    its ``NUMBER_WORDS`` / ``ORDINALS``, too few distractors) is rejected here, before the gate,
    whether or not ``adapt mc`` ran first (``mcstage.multihop_buildable``)."""
    if family != "multihop_st" or it.get("adapt", {}).get("origin") != "authored":
        return []
    from . import mcstage

    why = mcstage.multihop_buildable(it)
    return [f"mc: build_multihop_mc cannot build this item ({why})"] if why else []


def _conjunctive(family: str, it: dict) -> list[str]:
    """Plan 0077 §6, authored clusters only: the blocklist, the shared list's size, gold / twin /
    contrast, the twin pairing, tabs and the strict capital rule."""
    if family != "conjunctive_association" or it.get("adapt", {}).get("origin") != "authored":
        return []
    out = []
    text, gold = str(it.get("stimulus") or ""), it.get("gold_label")
    opts, inv = list(it.get("mc_options") or []), it.get("inverted_label")
    twin_of = it.get("twin_of") or {}
    if hit := [w for w in (it.get("blocklist") or {}).get("block") or [] if _has_form(text, w)]:
        out.append(f"leak: blocklist words {hit[:5]} in stimulus")
    if gold not in opts:
        out.append("mc: gold_label is not in mc_options")
    if len(set(opts)) != N_OPTIONS:  # the registered kind: 10 golds + 12 confusers + 22 twins
        out.append(f"mc: {len(set(opts))} distinct options, not the registered {N_OPTIONS}")
    if not inv or inv == gold or inv not in opts or twin_of.get(gold) != inv:
        out.append("mc: inverted_label must be the gold's shown twin (twin_of[gold], not the gold)")
    if it.get("contrast_label") and it["contrast_label"] not in opts:
        out.append("mc: contrast_label is not in mc_options")
    # a pairing: each option's twin is another option whose twin is it, so no grid option is
    # also another option's inverted label
    if bad := [k for k, v in twin_of.items()
               if v == k or twin_of.get(v) != k or k not in opts]:  # fmt: skip
        out.append(f"twin: twin_of is not a pairing of shown options ({str(bad[0])[:40]!r})")
    if "\t" in text:
        out.append("format: tab character in stimulus (#321)")
    if any(asks_capital(str(it.get(k) or ""), strict=True) for k in ("stimulus", "asked_question")):
        out.append("latent: country <-> capital questions left the benchmark (#372)")
    return out


def _conjunctive_batch(items: list[dict], logged: list[dict] = ()) -> dict[str, list[str]]:
    """Plan 0077 §6: an authored cluster's items share one ``mc_options`` of ``N_OPTIONS`` (44)
    distinct options and their 10 golds are distinct grid options; every member of a failing
    cluster in ``items`` is rejected. ``logged``: items already in the gate log; a cluster's
    logged cells (a crash mid-batch gated some) count as members, so the remaining siblings are
    judged with them, not rejected for being fewer than 10."""
    clusters: dict[str, dict[str, dict]] = {}
    for it in items:
        if it.get("adapt", {}).get("origin") == "authored":
            clusters.setdefault(str(it.get("cluster")), {})[str(it.get("id"))] = it
    for it in logged:
        cl = clusters.get(str(it.get("cluster")))
        if cl is not None and it.get("adapt", {}).get("origin") == "authored":
            cl.setdefault(str(it.get("id")), it)  # the batch's own copy wins
    out: dict[str, list[str]] = {}
    batch = {str(it.get("id") or it.get("name")) for it in items}
    for group in clusters.values():
        members = sorted(group.values(), key=lambda m: str(m.get("id")))
        golds = [m.get("gold_label") for m in members]
        why = []
        if len({json.dumps(m.get("mc_options"), ensure_ascii=False) for m in members}) != 1:
            why.append("cluster: its items do not share one mc_options list")
        if len(members) != 10 or len(set(map(str, golds))) != 10:
            why.append(f"cluster: needs 10 distinct golds ({len(set(map(str, golds)))} of "
                       f"{len(members)} items)")  # fmt: skip
        if len(set(members[0].get("mc_options") or [])) != N_OPTIONS:
            why.append(f"cluster: its shared list is not {N_OPTIONS} distinct options")
        if any(g not in (members[0].get("mc_options") or []) for g in golds):
            why.append("cluster: a gold is not one of the shared grid options")
        for m in members if why else ():
            if (mid := str(m.get("id") or m.get("name"))) in batch:
                out.setdefault(mid, []).extend(why)
    return out


CHECKS: list[Callable[[str, dict], list[str]]] = [
    _single_token, _computational, _user_modeling, _role_bound, _buggy, _basic_readout_v5,
    _multihop_v5, _multihop_buildable, _conjunctive,
]  # fmt: skip


def lint_pairs(family: str, items: list[dict], logged: list[dict] = ()) -> dict[str, list[str]]:
    """Batch checks ``lint`` (one item) cannot make, by item id. buggy_code (plan 0066 §2.3): an
    authored pair whose buggy and clean twins have the same ``verified`` outcome is rejected, both
    members (the pair is atomic). A twin outside ``items`` is not judged here.
    conjunctive_association (plan 0077 §6): ``_conjunctive_batch``. Call it beside
    ``lint`` on the candidate batch (``run.lint_and_gate``), with the gate log's items as
    ``logged`` (only conjunctive reads them)."""
    if family == "conjunctive_association":
        return _conjunctive_batch(items, logged)
    if family == "user_modeling":
        return _um_topic_batch(items, logged)
    if family == "multilingual_multihop":
        return _mlmh_dup_batch(items, logged)
    if family != "buggy_code":
        return {}
    by_name = {str(it.get("name") or it.get("id")): it for it in items}
    out: dict[str, list[str]] = {}
    for it in items:
        if it.get("src") != "buggy" or it.get("adapt", {}).get("origin") != "authored":
            continue
        twin = by_name.get(str(it.get("twin") or ""))
        v = it.get("verified")
        if twin is not None and v and v == twin.get("verified"):
            why = f"twin: the buggy and clean programs have the same outcome ({str(v)[:40]})"
            for m in (it, twin):
                out.setdefault(str(m.get("id") or m.get("name")), []).append(why)
    return out


_UM_STOP = frozenset({"and", "the", "of", "in", "at", "on", "for", "with", "my", "day", "life",
                      "daily", "new", "big", "old", "festival", "spring", "night", "shift",
                      "line", "market", "food", "home", "family", "weekend", "morning",
                      "routine", "work", "shop"})  # fmt: skip


def um_topics(it: dict) -> set[str]:
    """Plan 0075 follow-up 2: the topic words of an authored user_modeling item, read from its
    slug ``...um-sd-<attr_label>-<attr>-<short topic>`` (the brief's ``name`` key): the words after
    the attribute, >= 3 letters, minus a few fillers. Registered items' names carry no topic."""
    name = str(it.get("name") or it.get("id") or "").lower().replace("_", "-")
    if "um-sd-" not in name:
        return set()
    rest = name.split("um-sd-", 1)[1]
    for head in (str(it.get("attr_label", "")).lower(), str(it.get("attr", "")).lower()):
        head = head.replace("_", "-")
        if head and rest.startswith(head + "-"):
            rest = rest[len(head) + 1 :]
    return {t for t in rest.split("-") if len(t) >= 3 and not t.isdigit() and t not in _UM_STOP}


def _mlmh_key(it: dict) -> tuple[str, str, str]:
    """An mlmh item's latent: its L2, its bridge (``intermediates[0]``) and its answer, folded."""
    inter = it.get("intermediates") or [""]

    def fold(x: object) -> str:
        return " ".join(str(x).casefold().split())

    return (fold(it.get("lang", "")), fold(inter[0]), fold(it.get("target", "")))


def _mlmh_dup_batch(items: list[dict], logged: list[dict] = ()) -> dict[str, list[str]]:
    """multilingual_multihop (``run.PARALLEL`` waves author without seeing each other): an
    authored candidate with the same L2, bridge and answer as a gate-passing row (registered or
    authored) or an earlier candidate of this batch is a near-duplicate and rejected."""

    def iid(it: dict) -> str:
        return str(it.get("id") or it.get("name"))

    batch = {iid(it) for it in items}
    seen = {_mlmh_key(it): iid(it) for it in logged if iid(it) not in batch}
    out: dict[str, list[str]] = {}
    for it in items:
        key = _mlmh_key(it)
        if it.get("adapt", {}).get("origin") == "authored" and key in seen:
            out[iid(it)] = [f"dup: near-duplicate of {seen[key]} (same language, bridge, answer)"]
        else:
            seen.setdefault(key, iid(it))
    return out


def _um_topic_batch(items: list[dict], logged: list[dict] = ()) -> dict[str, list[str]]:
    """Plan 0075 follow-up 2 (qwen3.5-0.8b delta audit: 76 near-duplicate user_modeling items,
    the same festival / workplace authored again wave after wave): an authored candidate whose
    topic words (``um_topics``) share a word with an authored item of the same gold already in
    the gate log, or earlier in this batch, is rejected as a near-duplicate."""
    seen: dict[str, list[tuple[str, set[str]]]] = {}

    def iid(it: dict) -> str:
        return str(it.get("id") or it.get("name"))

    batch = {iid(it) for it in items}
    for it in logged:
        if it.get("adapt", {}).get("origin") == "authored" and iid(it) not in batch:
            seen.setdefault(str(it.get("attr", "")), []).append((iid(it), um_topics(it)))
    out: dict[str, list[str]] = {}
    for it in items:
        if it.get("adapt", {}).get("origin") != "authored":
            continue
        mine, attr = um_topics(it), str(it.get("attr", ""))
        for other, words_ in seen.get(attr, []):
            if shared := mine & words_:
                why = f"dup: near-duplicate of {other} (same gold, topic {sorted(shared)})"
                out[iid(it)] = [why]
                break
        else:
            seen.setdefault(attr, []).append((iid(it), mine))
    return out


def lint(family: str, item: dict) -> list[str]:
    need = MT_REQUIRED if family in MT else REQUIRED.get(family, ("prompt",))
    missing = [k for k in need if item.get(k) in (None, "", [])]
    if family == "basic_readout_st" and item.get("subfamily") != "implicit":
        missing += [k for k in ("target", "intermediates") if not item.get(k)]
    if missing:
        return [f"keys: missing {missing}"]
    if ((item.get("adapt") or {}).get("mc_build") or {}).get("dropped"):
        # ``adapt mc`` could not build its options (plan 0075): never gated without a list
        return ["mc: the MC builder dropped this candidate (no options)"]
    if family in MT:
        return _mt(family, item) + _capital(family, item)
    return [p for check in CHECKS for p in check(family, item)] + _capital(family, item)
