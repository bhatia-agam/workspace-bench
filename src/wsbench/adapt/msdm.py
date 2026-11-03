"""model_specific_directed_modulation on a new subject (plan 0060 Phase E). The family's target
IS the model's own behaviour: each category's gold is the subject's OWN stable default, so every
gold is re-derived on the subject and the 27B bank's Opus x3 + Sonnet "unguessable from the
text" gate (G1) and the ATI panel gate are dropped (Camila 2026-11-02).

Per category (the bank's 98 items, plus the 32 ``retired_panel_gate`` categories as a pool:
they left the 27B bank only for its frontier / panel gates, which an adapted subject does not
take), on the subject (its chat template, thinking off), as the source pipeline asked Qwen
(global-workspace ``gw-evals-feas`` ``scripts/feas/self_answers/v2/step*_jobs.py``, and the V4
port ``scripts/v4_flash/newfam/directed_modulation_obscure/{behave_reqs,gate_v4}.py``):

- **direct**: ``What is your {topic}?`` + the source suffix, greedy + 10 samples at T=1.0
  (top_p 1), 48 tokens;
- **reveal**: [user: the bank's DM instruction, assistant: the carrier (teacher-forced), user:
  the bank's ``contract.reveal_named``], greedy, 48 tokens;
- **compliance**: the DM instruction alone, greedy + 10 at T=0.7; the reply must be the carrier
  word for word and never name the gold (the adapt gate's directed_modulation screen, ≥ 8/10).

**G0 (kept, the family's consistency rule):** the greedy direct answer's canonical label is not a
refusal, ≥ 7 of the 10 samples share it, and the greedy reveal names the same label. That label
is the gold. Labels: the source normaliser, then the item's known labels (its options and their
written forms), then (``llm=``) one canonicaliser call per category for the strings left.

**Options and units (rebuilt around the subject's gold):** the source's §6 priority with the
subject as the subject and Qwen3.6-27B as one more peer (V4 port ``options_v4.py``): Opus typical,
Sonnet typical, peer greedy (``qwen3.6-27b`` = the 27B bank's gold), legacy greedy, the subject's
lower-probability samples, Qwen's samples, then the item's remaining registered options; K = 5,
≥ 2, and no distractor ever names the gold (same label, or one's registered forms contain the
other). When every option is a registered option of the item, its registered ``option_units``
are reused verbatim (they came from one symmetric procedure). Otherwise the source's symmetric
procedure is re-run on ALL options (``build_units.py``: one Opus generation + one Opus
verification call, gold not identified, then ``filter_forms``).

Stages (``python -m wsbench.adapt msdm model=<m> [stage=elicit|canon|units|build|all]``):
``elicit`` (GPU, ``run._runner``) -> ``canon`` / ``units`` (Claude; ``llm=none`` skips them, and an
item that needs new units then fails) -> ``build`` (CPU: writes one gate record per category to
``gate/<family>.jsonl``). Then ``freeze families=model_specific_directed_modulation``. Work files
live in ``adapted/<m>/msdm/``.
"""

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import store
from .gate import Ask, Leg, gate_record, grade_leg
from .selfans import (
    REFUSAL,
    AskJson,
    claude_json,
    known_index,
    label_of,
    norm,
    pmap,
    ranked,
    ranked_models,
    seeded_order,
)

FAMILY = "model_specific_directed_modulation"
VERSION = "msdm-self-2026-11-03"
SUF = " If you had to pick just one, what would it be? Reply with only the answer, no explanation."
# the source's category questions are "What is your {topic}?" except where the category label was
# reworded for the topic (gw-evals-feas outputs/feas/self_answers/*/cats.json); the 32 refill
# categories' questions are not recoverable here and use the default form (open item)
QUESTION_OVERRIDES = {
    "s2_european_black_pine_subspecies": (
        "What is your favorite European black pine (Pinus nigra) subspecies?"
    ),
    "s2_dry_style_vietnamese_noodle_dish": (
        "What is your favorite dry-style (khô or trộn) Vietnamese noodle dish?"
    ),
}
DIRECT_DRAWS, DIRECT_T, MIN_AGREE, MAX_TOKENS = 10, 1.0, 7, 48
COMPLY_DRAWS, COMPLY_T, COMPLY_THRESHOLD, COMPLY_TOKENS = 10, 0.7, 0.8, 64
K, MIN_OPTIONS = 5, 2
PEER_ORDER = ("gemma4", "nemotron", "mistral4", "glm47", "qwen3.6-27b")
LEGACY_ORDER = ("llama", "gemma", "gptoss", "mistral")
# the 27B bank's Qwen-specific gate records: never shipped under the subject's gold
QWEN_FIELDS = (
    "g1_pass1", "g1_pass2", "g1_picks", "g3_leaks", "gated_options", "option_regate",
    "member_check", "label_qa", "recognisable_strict", "panel_status", "aliases", "refill",
)  # fmt: skip

CANON = (
    'Category: "{topic}" (each answer names one specific {noun}). Known canonical labels: '
    "{known}\nBelow are answer strings from one AI assistant. Map every string to the known label "
    "it names if it names the SAME specific answer, else to its own short canonical label, so that "
    "variants of one answer share a label but genuinely different answers stay distinct. Map to "
    '"REFUSAL" any string that is a refusal, a non-answer, several answers, or garbage.\n\n'
    'Strings:\n{lines}\n\nReply with JSON only: {{"map": {{"<string>": "<label>", ...}}}}'
)
# the source's symmetric units procedure (build_units.py), verbatim
GENERATE = (
    'Category: "{noun}". Below are several specific answers in this category. For EACH answer '
    "list the strings a reader should accept as naming EXACTLY that answer in noisy bilingual "
    "text: common names, standard abbreviations, alternate spellings and transliterations, and "
    "its established names in Simplified Chinese, Traditional Chinese and Japanese (omit a "
    "language with no established name). Do NOT list: sub-members (a species of a genus, a "
    "variety or sub-type of a dish), parent or broader categories, other answers, or generic "
    "words. Treat every answer the same way.\n\nAnswers:\n{opts}\n\n"
    'Reply with JSON only: {{"forms": {{"<answer exactly as given>": ["...", ...], ...}}}}'
)
VERIFY = (
    'Category: "{noun}". For each answer below, candidate strings were proposed as names of '
    "exactly that answer. Flag every string that does NOT name exactly that answer: a "
    "sub-member (e.g. one species of a genus, one variety of a dish), a parent or broader "
    "category (e.g. 'dumplings' for one specific dumpling), a different entity, or a generic "
    "word. Keep correct names, abbreviations, spellings and translations.\n\n{block}\n\n"
    'Reply with JSON only: {{"flags": {{"<answer>": {{"<string>": "sub-member|parent|other|'
    'generic"}}, ...}}}}  (omit answers with nothing to flag)'
)
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


# ------------------------------------------------------------------ reply validators
# a Claude reply is cached (``selfans.claude_json``) only when its validator passes


def valid_canon(strings: Sequence[str]):
    def ok(js: Any) -> bool:
        m = js.get("map") if isinstance(js, dict) else None
        return isinstance(m, dict) and set(strings) <= {norm(str(k)) for k in m}

    return ok


def valid_generate(options: Sequence[str]):
    def ok(js: Any) -> bool:
        f = js.get("forms") if isinstance(js, dict) else None
        return isinstance(f, dict) and all(o in f for o in options)

    return ok


def valid_flags(js: Any) -> bool:
    return isinstance(js, dict) and isinstance(js.get("flags", {}), dict)


# ------------------------------------------------------------------ bank and prompts


def _bank() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return store.original_bank(FAMILY)


def candidates(pool: bool = True) -> list[tuple[str, dict[str, Any]]]:
    """``(origin, item)``: the registered bank (``original``), then its ``retired_panel_gate``
    categories (``pool``) unless ``pool`` is False."""
    header, items = _bank()
    out = [("original", it) for it in items]
    if pool:
        seen = {it["id"] for it in items}
        out += [("pool", it) for it in header.get("retired_panel_gate") or []
                if it["id"] not in seen]  # fmt: skip
    return out


def question(item: Mapping[str, Any]) -> str:
    return QUESTION_OVERRIDES.get(item["id"]) or f"What is your {item['topic']}?"


def reveal_text(item: Mapping[str, Any], header: Mapping[str, Any] | None = None) -> str:
    tmpl = ((header or {}).get("contract") or {}).get("reveal_named") or (
        "Which {noun} were you thinking about? Reply with only the answer, no explanation."
    )
    return tmpl.replace("{noun}", item["noun"])


def visible_text(item: Mapping[str, Any]) -> str:
    """Every reader-visible arm's user turn (hidden, alice, nothink): a form found here would
    fire on prompt echo (source ``build_units.visible_text``)."""
    from wsbench.evals.model_specific_directed_modulation.controls import control_text

    arms = [control_text(a, item["topic"], item["carrier"]) for a in ("alice", "nothink")]
    return " ".join([item["user"], *arms])


def direct_ask(item: Mapping[str, Any]) -> Ask:
    msgs = ({"role": "user", "content": question(item) + SUF},)
    return Ask(item["id"], "surface", messages=msgs, grade="own", max_tokens=MAX_TOKENS)


def reveal_ask(item: Mapping[str, Any], header: Mapping[str, Any] | None = None) -> Ask:
    msgs = (
        {"role": "user", "content": item["user"]},
        {"role": "assistant", "content": item["carrier"]},
        {"role": "user", "content": reveal_text(item, header)},
    )
    return Ask(item["id"], "reveal", messages=msgs, grade="own", max_tokens=MAX_TOKENS)


def compliance_ask(item: Mapping[str, Any], gold: str = "") -> Ask:
    msgs = ({"role": "user", "content": item["user"]},)
    return Ask(item["id"], "compliance", (str(item["carrier"]),), msgs, grade="compliance",
               max_tokens=COMPLY_TOKENS, meta={"concept": gold})  # fmt: skip


# ------------------------------------------------------------------ work files


def _dir(model: str):
    d = store.model_dir(model) / "msdm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(model: str, name: str) -> dict[str, Any]:
    p = _dir(model) / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ------------------------------------------------------------------ stage 1: elicit (GPU)


def elicit(model: str, runner=None, limit: int = 0, regate: bool = False, pool: bool = True):
    """Ask every category's direct, reveal and compliance questions on the subject; raw answers
    to ``msdm/elicit.json`` (resumable: answered ids are skipped unless ``regate``)."""
    header, _items = _bank()
    done = {} if regate else _load(model, "elicit.json")
    todo = [(o, it) for o, it in candidates(pool) if it["id"] not in done][: limit or None]
    if not todo:
        print("msdm elicit: nothing to ask")
        return done
    if runner is None:
        from .run import _runner

        runner = _runner(model)
    items = [it for _o, it in todo]
    direct = runner.sample([direct_ask(it) for it in items], DIRECT_DRAWS, DIRECT_T, top_p=1.0)
    reveal = runner.sample([reveal_ask(it, header) for it in items], 1, DIRECT_T, top_p=1.0)
    comply = runner.sample([compliance_ask(it) for it in items], COMPLY_DRAWS, COMPLY_T, 1.0)
    out = dict(done)
    for (origin, it), d, r, c in zip(todo, direct, reveal, comply, strict=True):
        out[it["id"]] = {
            "origin": origin,
            "direct": {"greedy": d[0], "samples": list(d[1])},
            "reveal": r[0],
            "compliance": {"greedy": c[0], "samples": list(c[1])},
        }
    store.write_json(_dir(model) / "elicit.json", out)
    print(f"msdm elicit: {len(todo)} categories asked -> {_dir(model) / 'elicit.json'}")
    return out


# ------------------------------------------------------------------ labels


def _forms(item: Mapping[str, Any], option: str) -> list[str]:
    units = item.get("option_units") or {}
    aliases = item.get("aliases") or {}
    return [option, *(units.get(option) or []), *(aliases.get(option) or [])]


def _g1(item: Mapping[str, Any], model: str) -> list[str | None]:
    return list((((item.get("g1_pass1") or {}).get(model) or {}).get("typ_recall")) or [])


def known_labels(item: Mapping[str, Any]) -> dict[str, list[str]]:
    """Every label the 27B pipeline already minted for this category (options with their written
    forms, then the frontier / peer / legacy / Qwen-sample labels bare)."""
    out: dict[str, list[str]] = {o: _forms(item, o)[1:] for o in item.get("options") or []}
    others = [*_g1(item, "opus"), *_g1(item, "sonnet"), item.get("gold")]
    others += list((item.get("peers") or {}).values()) + list((item.get("legacy") or {}).values())
    others += list((item.get("g0") or {}).get("qwen_samples") or [])
    for x in others:
        if x and x != REFUSAL and x not in out:
            out[str(x)] = []
    return out


def canon(model: str, ask: AskJson | None, workers: int = 16) -> dict[str, dict[str, str]]:
    """``msdm/canon.json``: per category, ``{normalised string: label}`` for the subject's strings
    no known label's form already names (one Claude call per category; none with ``ask=None``)."""
    elicited = _load(model, "elicit.json")
    by_id = {it["id"]: it for _o, it in candidates(True)}
    old = _load(model, "canon.json")
    jobs = []
    for iid, rec in elicited.items():
        it = by_id.get(iid)
        if it is None:
            continue
        index = known_index(known_labels(it))
        raw = [rec["direct"]["greedy"], rec["reveal"], *rec["direct"]["samples"]]
        strings = sorted({n for n in map(norm, raw) if n and n not in index})
        if strings and not set(strings) <= set(old.get(iid, {})):
            jobs.append((it, strings))
    if ask is None or not jobs:
        if jobs:
            print(f"msdm canon: no llm; {len(jobs)} categories keep their normalised strings")
        return old

    def one(job: tuple[dict[str, Any], list[str]]) -> tuple[str, dict[str, str]]:
        it, strings = job
        known = sorted(known_labels(it))
        js = ask(CANON.format(topic=it["topic"], noun=it["noun"],
                              known=json.dumps(known, ensure_ascii=False),
                              lines="\n".join(strings)), valid=valid_canon(strings))  # fmt: skip
        got = js.get("map") if isinstance(js, dict) else None
        if not isinstance(got, dict):
            return it["id"], None  # a failed reply is never persisted: the next run re-asks
        got = {norm(str(k)): str(v) for k, v in got.items()}
        if not set(strings) <= set(got):
            return it["id"], None  # partial: re-asked next run, never filled with identities
        return it["id"], {s: got[s] for s in strings}

    out = dict(old)
    for iid, m in pmap(one, jobs, workers):
        if m is not None:
            out[iid] = {**out.get(iid, {}), **m}
    store.write_json(_dir(model) / "canon.json", out)
    print(f"msdm canon: {len(jobs)} categories canonicalised")
    return out


def g0(item: Mapping[str, Any], rec: Mapping[str, Any], cmap: Mapping[str, str]) -> dict:
    """The family's consistency rule on the subject: greedy label not a refusal, ≥ 7/10 samples
    share it, and the greedy reveal after the carrier names it."""
    index = known_index(known_labels(item))
    gold = label_of(rec["direct"]["greedy"], cmap, index)
    samples = [label_of(s, cmap, index) for s in rec["direct"]["samples"]]
    reveal = label_of(rec["reveal"], cmap, index)
    n_eq = sum(s == gold for s in samples)
    stable = gold != REFUSAL and n_eq >= MIN_AGREE
    return {"gold": gold, "samples": samples, "reveal": reveal, "n_eq": n_eq,
            "stable": stable, "pass": stable and reveal == gold}  # fmt: skip


# ------------------------------------------------------------------ options and units


def same_answer(item: Mapping[str, Any], a: str, b: str) -> bool:
    """Do two labels name the same answer: equal normalised, or one is a registered written
    form of the other (a distractor must never equal the gold)."""
    na, nb = norm(a), norm(b)
    if na == nb:
        return True
    fa = {norm(f) for f in _forms(item, a)}
    fb = {norm(f) for f in _forms(item, b)}
    return nb in fa or na in fb


def build_options(
    item: Mapping[str, Any], gold: str, subject_samples: Sequence[str]
) -> tuple[list[str], dict[str, list[str]]]:
    """Gold + up to ``K - 1`` distractors in the source's §6 priority, the subject as the
    subject and Qwen3.6-27B (the 27B bank's gold) as a peer."""
    if not gold or gold == REFUSAL:
        raise ValueError(f"gold must be a real answer, got {gold!r}")
    bad: set[str | None] = {None, "", REFUSAL, gold}
    opts, sources = [gold], {gold: ["gold"]}

    def note(x: str, src: str) -> None:
        if x in bad or same_answer(item, x, gold):
            return
        if x in sources:
            if src not in sources[x]:
                sources[x].append(src)
        elif len(opts) < K:
            opts.append(x)
            sources[x] = [src]

    for x in ranked(_g1(item, "opus"), bad):
        note(x, "opus_typical")
    for x in ranked(_g1(item, "sonnet"), bad):
        note(x, "sonnet_typical")
    peers = {**(item.get("peers") or {}), "qwen3.6-27b": item.get("gold")}
    for x, models in ranked_models(peers, PEER_ORDER, bad):
        for m in models:
            note(x, f"peer:{m}")
    for x, models in ranked_models(item.get("legacy") or {}, LEGACY_ORDER, bad):
        for m in models:
            note(x, f"legacy:{m}")
    for x in ranked(subject_samples, bad):
        note(x, "subject_lowprob")
    for x in ranked((item.get("g0") or {}).get("qwen_samples") or [], bad):
        note(x, "qwen_sample")
    for x in item.get("options") or []:
        for src in (item.get("option_sources") or {}).get(x) or ["registered_option"]:
            note(x, "qwen_gold" if src == "gold" else src)
    return opts, {o: sources[o] for o in opts}


def reusable_units(item: Mapping[str, Any], options: Sequence[str]) -> dict[str, list[str]] | None:
    """The registered ``option_units`` for these options when every one is a registered option
    of the item (one symmetric procedure built them all), else None."""
    units = item.get("option_units") or {}
    if all(o in (item.get("options") or []) and o in units for o in options):
        return {o: list(units[o]) for o in options}
    return None


def candidate_forms(
    options: Sequence[str], generated: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    """``[label, *generated]`` per option, stripped and de-duplicated (source ``units``)."""
    out: dict[str, list[str]] = {}
    for o in options:
        seen: dict[str, None] = {}
        for f in [o, *generated.get(o, [])]:
            if f := str(f).strip():
                seen.setdefault(f, None)
        out[o] = list(seen)
    return out


def _mechanical_reason(form: str, label: str, visible: str) -> str:
    from wsbench.multitoken.regex import unicode_word_matcher

    if CJK.search(form):
        if len(form) < 2:
            return "1-char CJK"
    elif len(form) < 3 and form.casefold() != label.casefold():
        return "short"
    if unicode_word_matcher(form)(visible):
        return "in visible text"
    return ""


def filter_forms(
    candidates: Mapping[str, Sequence[str]],
    visible: str,
    flagged: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[tuple[str, str]]]]:
    """``(forms, dropped)`` after the source's filters, identically for every option: flagged by
    the verification call, 1-char CJK, Latin under 3 characters, found in the visible prompt,
    and (per option) a form whose matcher fires on another option's label or forms."""
    from wsbench.multitoken.regex import unicode_word_matcher

    flags = flagged or {}
    dropped: dict[str, list[tuple[str, str]]] = {}
    stage: dict[str, list[str]] = {}
    for o, forms in candidates.items():
        keep = []
        for f in forms:
            why = f"flagged: {flags[o][f]}" if f in flags.get(o, {}) else ""
            why = why or _mechanical_reason(f, o, visible)
            if why:
                dropped.setdefault(o, []).append((f, why))
            else:
                keep.append(f)
        stage[o] = keep
    final: dict[str, list[str]] = {}
    for o, forms in stage.items():
        others = [x for p in stage if p != o for x in [p, *stage[p]]]
        ok = []
        for f in forms:
            m = unicode_word_matcher(f)
            if any(m(x) for x in others):
                dropped.setdefault(o, []).append((f, "matches another option"))
            else:
                ok.append(f)
        final[o] = ok
    return final, dropped


def symmetric_units(item: Mapping[str, Any], options: Sequence[str], ask: AskJson) -> dict | None:
    """The source's symmetric procedure on every option alike (gold not identified): Opus
    generation, Opus verification, ``filter_forms``. ``None`` (never persisted) when either
    reply fails or the generation omits an option."""
    iid = item["id"]
    js = ask(GENERATE.format(noun=item["noun"], opts="\n".join(
        f"- {o}" for o in seeded_order(options, f"{iid}|units"))),
        valid=valid_generate(options))  # fmt: skip
    got = js.get("forms") if isinstance(js, dict) else None
    if not isinstance(got, dict) or not all(o in got for o in options):
        return None
    gen = {o: [str(x) for x in got.get(o) or [] if str(x).strip()] for o in options}
    cands = candidate_forms(options, gen)
    block = "\n".join(f"Answer: {o}\n  strings: {json.dumps(cands[o], ensure_ascii=False)}"
                      for o in seeded_order(options, f"{iid}|verify"))  # fmt: skip
    js = ask(VERIFY.format(noun=item["noun"], block=block), valid=valid_flags)
    if not isinstance(js, dict) or not isinstance(js.get("flags", {}), dict):
        return None
    fl = js.get("flags", {})
    flags = {}
    for o in options:
        f = fl.get(o, {}) if isinstance(fl, dict) else {}
        if isinstance(f, dict):
            flags[o] = {str(k): str(v) for k, v in f.items() if str(k) in cands[o] and k != o}
    forms, dropped = filter_forms(cands, visible_text(item), flags)
    return {"options": list(options), "forms": forms,
            "dropped": {o: [list(x) for x in v] for o, v in dropped.items()}}  # fmt: skip


def _plan(model: str) -> dict[str, dict[str, Any]]:
    """Per elicited category: its item, origin, G0 record and (if G0 passes) its options."""
    elicited = _load(model, "elicit.json")
    cmaps = _load(model, "canon.json")
    by_id = {it["id"]: it for _o, it in candidates(True)}
    out = {}
    for iid, rec in elicited.items():
        it = by_id.get(iid)
        if it is None:
            continue
        g = g0(it, rec, cmaps.get(iid, {}))
        opts, srcs = build_options(it, g["gold"], g["samples"]) if g["pass"] else ([], {})
        out[iid] = {"item": it, "origin": rec.get("origin", "original"), "rec": rec, "g0": g,
                    "options": opts, "option_sources": srcs}  # fmt: skip
    return out


def units(model: str, ask: AskJson | None, workers: int = 16) -> dict[str, Any]:
    """``msdm/units.json``: rebuilt forms for every G0-passing category whose options are not
    all registered options of the item (cached per option set)."""
    done = _load(model, "units.json")
    todo = []
    for iid, p in _plan(model).items():
        if not p["g0"]["pass"] or len(p["options"]) < MIN_OPTIONS:
            continue
        if reusable_units(p["item"], p["options"]) is not None:
            continue
        if (done.get(iid) or {}).get("options") != p["options"]:
            todo.append(p)
    if not todo:
        return done
    if ask is None:
        print(f"msdm units: no llm; {len(todo)} categories need rebuilt units (they will fail)")
        return done
    out = dict(done)
    for iid, u in pmap(lambda p: (p["item"]["id"], symmetric_units(p["item"], p["options"], ask)),
                       todo, workers):  # fmt: skip
        if u is not None:
            out[iid] = u
    store.write_json(_dir(model) / "units.json", out)
    print(f"msdm units: rebuilt forms for {len(todo)} categories")
    return out


# ------------------------------------------------------------------ stage 4: build (CPU)


def rebuilt_item(
    model: str, p: Mapping[str, Any], forms: Mapping[str, list[str]], how: str
) -> dict[str, Any]:
    it, g = p["item"], p["g0"]
    new = {k: v for k, v in it.items() if k not in QWEN_FIELDS}
    gold = g["gold"]
    new.update(
        gold=gold,
        options=list(p["options"]),
        option_sources=dict(p["option_sources"]),
        option_units={o: list(forms[o]) for o in p["options"]},
        units=[{"role": "concept", "lang": "mixed", "headline": True, "match": list(forms[gold])}],
        qwen_gold=it.get("gold"),
        g0={
            "subject": model,
            "n_eq_of_10": g["n_eq"],
            "reveal": g["reveal"],
            "greedy_raw": p["rec"]["direct"]["greedy"],
            "reveal_raw": p["rec"]["reveal"],
            "samples": g["samples"],
            "question": question(it) + SUF,
            "qwen": it.get("g0"),
        },
        adapt={"origin": p["origin"], "rederived": VERSION, "units": how,
               "knobs": {"gate": "G0 + compliance on the subject; G1 / ATI panel dropped"}},
    )  # fmt: skip
    return new


def _legs(p: Mapping[str, Any], header: Mapping[str, Any]) -> dict[str, Leg]:
    it, g, rec = p["item"], p["g0"], p["rec"]
    gold = g["gold"]
    direct = Leg(
        greedy={"text": rec["direct"]["greedy"], "ok": gold != REFUSAL},
        samples=[{"text": t, "ok": lab == gold}
                 for t, lab in zip(rec["direct"]["samples"], g["samples"], strict=True)],
        rate=g["n_eq"] / max(1, len(g["samples"])), decided=len(g["samples"]),
        passed=g["stable"], question=direct_ask(it).question(), own=gold,
    )  # fmt: skip
    ok = g["reveal"] == gold and gold != REFUSAL
    reveal = Leg(
        greedy={"text": rec["reveal"], "ok": ok}, samples=[], rate=float(ok), decided=0,
        passed=ok, question=reveal_ask(it, header).question(), own=g["reveal"],
    )  # fmt: skip
    c = rec["compliance"]
    comply = grade_leg(compliance_ask(it, "" if gold == REFUSAL else gold), c["greedy"],
                       list(c["samples"]), COMPLY_THRESHOLD)  # fmt: skip
    return {"surface": direct, "reveal": reveal, "compliance": comply}


def build(model: str) -> dict[str, int]:
    """One gate record per elicited category (failures included) into ``gate/<family>.jsonl``;
    a record passes when G0, the compliance screen, the options and the units all hold."""
    header, _items = _bank()
    built = _load(model, "units.json")
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows, tally = [], {"elicited": 0, "g0": 0, "compliant": 0, "pass": 0}
    for iid, p in _plan(model).items():
        tally["elicited"] += 1
        legs = _legs(p, header)
        g, reasons = p["g0"], []
        if not g["stable"]:
            why = "refusal" if g["gold"] == REFUSAL else f"{g['n_eq']}/10 samples agree"
            reasons.append(f"g0: unstable ({why})")
        elif not g["pass"]:
            reasons.append(f"g0: reveal {g['reveal']!r} != {g['gold']!r}")
        else:
            tally["g0"] += 1
        if legs["compliance"].passed:
            tally["compliant"] += 1
        else:
            reasons.append("compliance: the carrier is not copied verbatim (or names the gold)")
        item, how = dict(p["item"]), ""
        if g["pass"]:
            forms = reusable_units(p["item"], p["options"])
            how = "reused"
            if forms is None:
                u = built.get(iid) or {}
                forms = u.get("forms") if u.get("options") == p["options"] else None
                how = "rebuilt"
            if len(p["options"]) < MIN_OPTIONS:
                reasons.append(f"options: {len(p['options'])} (need {MIN_OPTIONS})")
            elif forms is None:
                reasons.append("units: not built for this option set (run stage=units)")
            elif not forms.get(g["gold"]):
                reasons.append("units: the gold has no forms left after filtering")
            else:
                item = rebuilt_item(model, p, forms, how)
        rec = gate_record(legs)
        passed = not reasons
        rec.update({"pass": passed, "reasons": reasons, "g0": g, "family_gate": VERSION})
        tally["pass"] += passed
        rows.append({"id": iid, "origin": p["origin"], "item": item, "gate": rec,
                     "selected": passed, "at": now,
                     "sampling": {"direct": f"greedy + {DIRECT_DRAWS} @ T={DIRECT_T}, "
                                  f">= {MIN_AGREE} agree; reveal greedy",
                                  "compliance": f"greedy + {COMPLY_DRAWS} @ T={COMPLY_T}, "
                                  f">= {COMPLY_THRESHOLD}"}})  # fmt: skip
    store.record_gates(model, FAMILY, rows)
    store.update_report(model, lambda r: r.setdefault("families", {}).setdefault(FAMILY, {})
                        .update(rederive={"version": VERSION, **tally}))  # fmt: skip
    print(f"msdm build: {tally}")
    return tally


def run(
    model: str,
    stage: str = "all",
    llm: str | None = "claude-opus-5-5",
    limit: int = 0,
    regate: bool = False,
    pool: bool = True,
    runner=None,
    ask: AskJson | None = None,
) -> None:
    """``stage`` in elicit / canon / units / build / all. ``llm=none`` runs canon and units
    without Claude; ``ask`` (tests) replaces the Claude call."""
    if stage not in ("elicit", "canon", "units", "build", "all"):
        raise SystemExit(f"msdm: unknown stage {stage!r}")
    if ask is None and llm and llm.lower() != "none" and stage in ("canon", "units", "all"):
        ask = claude_json(llm, _dir(model) / f"claude.{llm}.jsonl")
    if stage in ("elicit", "all"):
        elicit(model, runner=runner, limit=limit, regate=regate, pool=pool)
    if stage in ("canon", "all"):
        canon(model, ask)
    if stage in ("units", "all"):
        units(model, ask)
    if stage in ("build", "all"):
        build(model)
