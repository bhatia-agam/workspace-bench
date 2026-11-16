"""Plan 0075's data-round rules (D1-D7) as one tool, ported from the run trees' scripts (plan 0091).

``python -m wsbench.adapt dataround model=<m> stage=leakers|screens|short`` (SKILL.md §Data round).
"""

import ast
import json
import math
import re
import shlex
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import refill as rf
from . import store

MARGIN = 0.05  # §0.1(a): the family bar is chance + 5 points on each guesser
BLIND_ONLY_BELOW = 4  # a family with fewer items is measured blind only (no described guesser)
MC_FAMILIES = (
    "association", "basic_readout", "basic_readout_mt", "multihop", "poetry",
    "role_bound_association", "multilingual", "multilingual_mt", "multilingual_typo",
    "multilingual_multihop",
)  # fmt: skip

R_LEAK = (
    "plan 0075 data round D1-D3 (strict, whole bank incl. originals): the list leaks in {run} AND "
    "in an earlier separate lucky-guessing run ({prior}) (blind+described 10/10, or a guesser over "
    "the chance+5 family bar >= 3/5 with blind+described >= 4/10; two-run rule of 2026-11-08); "
    "dropped and back-filled"
)
REASONS = {
    "d4": "plan 0075 data round D4: the answer is reachable without the bridge (a direct "
          "well-known pairing of the named thing with the answer); dropped and back-filled",
    "d5": "plan 0075 data round D5: a clue routes through, or the question asks, a capital; "
          "dropped and back-filled",
    "d6": "plan 0075 data round D6: the user turn names a city / town in the gold country "
          "(city -> country leak); dropped and back-filled with non-Country rows",
    "d6b": "plan 0075 data round D6 (ruling 2026-11-08): the user turn names a landmark / natural "
           "feature / region in the gold country, which points to it; dropped and back-filled "
           "with non-Country, non-Gender rows",
    "d7": "plan 0075 data round D7: user_modeling {cls} capped at 20% of the shipped family; the "
          "newest {cls} rows above the cap dropped ({before} -> {after}) and back-filled with "
          "Occupation / Religion rows",
}  # fmt: skip


# ---------------------------------------------------------------------------- the shipped bank
def shipped(model: str, family: str) -> list[dict]:
    """The set's frozen bank of ``family`` minus its audited drops (what ships), bank order."""
    path = store.bank_file(model, family)
    if not path.exists():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    items = doc["items"] if isinstance(doc, dict) else doc
    dropped = set(store.report_entry(store.read_report(model).get("drops"), family))
    return [it for it in items if store.item_id(it) not in dropped]


def twins(family: str, ids: set[str]) -> list[str]:
    """role_bound drops take both twins (``-ab`` / ``-ba``); every other family as given."""
    if family != "role_bound_association":
        return sorted(ids)
    out = set()
    for i in ids:
        stem = i[:-3] if i.endswith(("-ab", "-ba")) else i
        out |= {stem + "-ab", stem + "-ba"} if stem != i else {i}
    return sorted(out)


# ---------------------------------------------------------------------------- D1-D3: leakers
def _measures(fd: Path) -> dict[str, dict]:
    return {
        v: json.loads((fd / f"{v}.json").read_text(encoding="utf-8"))
        for v in ("blind", "described")
        if (fd / f"{v}.json").exists()
    }


def _hits(measures: dict[str, dict]) -> dict[str, dict[str, int]]:
    """``{per-item key: {guesser: correct draws of 5}}``."""
    out: dict[str, dict[str, int]] = {}
    for v, r in measures.items():
        for k, p in r["per_item"].items():
            out.setdefault(k, {})[v] = sum(1 for x in p.get("draws") or [] if x and x["correct"])
    return out


def _rates(hits: dict[str, dict[str, int]], keys: set[str], guessers) -> dict[str, float]:
    return {
        v: (sum(hits[k].get(v, 0) for k in keys) / (5 * len(keys)) if keys else 0.0)
        for v in guessers
    }


def _flag(h: dict[str, int], failing: list[str], blind_only: bool) -> str | None:
    """The per-run test on one item (D1-D3), or None."""
    if blind_only:
        return "d12_blind_only" if h.get("blind", 0) >= 4 and "blind" in failing else None
    both = h.get("blind", 0) + h.get("described", 0)
    if both >= 10:
        return "d3_10of10"
    if both >= 4 and any(h.get(v, 0) >= 3 for v in failing):
        return "d12_failing_guesser"
    return None


def run_flags(fd: Path) -> set[str]:
    """Item keys one measurement flags, against that run's own failing guessers (all its items)."""
    m = _measures(fd)
    if "blind" not in m:
        return set()
    bar = float(m["blind"]["analytic_floor"]) + MARGIN
    hits = _hits(m)
    rates = _rates(hits, set(hits), m)
    failing = [v for v in rates if rates[v] > bar + 1e-9]
    blind_only = "described" not in m
    return {k for k, h in hits.items() if _flag(h, failing, blind_only)}


# the driver's measurement dirs (plan 0075: every earlier ``c*`` / ``final*`` run counts, the
# driver's report-only ``final_report_*`` measures included); a run under any other name (an ad
# hoc or debug measurement) never confirms a drop unless ``history=`` names it
HISTORY = ("c*", "final*")


def history(root: Path, family: str, exclude: Path,
            patterns: tuple[str, ...] = HISTORY) -> dict[str, list[str]]:  # fmt: skip
    """``{item key: [earlier run names that flag it]}`` over the other measurements of ``family``
    under ``root`` whose directory name matches ``patterns`` (each one run; a directory reached
    twice, e.g. through a symlink, counts once)."""
    seen: dict[str, list[str]] = {}
    done = {exclude.resolve()}
    dirs = sorted({d for pat in patterns for d in root.glob(pat) if d.is_dir()})
    for d in dirs:
        fd = d / family
        if d.resolve() in done or not (fd / "blind.json").exists():
            continue
        done.add(d.resolve())
        for k in run_flags(fd):
            seen.setdefault(k, []).append(d.name)
    return seen


def decide(model: str, family: str, fd: Path, root: Path,
           patterns: tuple[str, ...] = HISTORY) -> dict[str, Any]:  # fmt: skip
    """D1-D3 with the two-run rule on the SHIPPED items of ``family`` measured in ``fd``. A flag
    confirmed by an earlier run drops; the rates are recomputed and the pass repeats."""
    m = _measures(fd)
    bar = float(m["blind"]["analytic_floor"]) + MARGIN
    ship = {store.item_id(it) for it in shipped(model, family)}
    hits = {k: h for k, h in _hits(m).items() if k.split("#")[0] in ship}
    blind_only = "described" not in m
    hist = history(root, family, fd.parent, patterns)
    keep, drops, pending, rnd = set(hits), {}, {}, 0
    r0 = _rates(hits, keep, m)
    while True:
        rnd += 1
        r = _rates(hits, keep, m)
        failing = [v for v in r if r[v] > bar + 1e-9]
        new = {k: w for k in keep if (w := _flag(hits[k], failing, blind_only))}
        conf = {k: w for k, w in new.items() if hist.get(k)}
        for k, w in new.items():
            if k not in conf:
                pending[k] = {"rule": w, "hits": hits[k]}
        if not conf:
            break
        for k, w in conf.items():
            drops[k] = {"rule": w, "hits": hits[k], "round": rnd, "prior_runs": hist[k]}
        keep -= set(conf)
    rf_ = _rates(hits, keep, m)
    ids = twins(family, {k.split("#")[0] for k in drops})
    return {
        "n_shipped": len(ship),
        "n_measured": len({k.split("#")[0] for k in hits}),
        "unmeasured": sorted(ship - {k.split("#")[0] for k in hits}),
        "chance": round(bar - MARGIN, 4), "bar": round(bar, 4), "blind_only": blind_only,
        "rates_before": {k: round(v, 4) for k, v in r0.items()},
        "rates_after": {k: round(v, 4) for k, v in rf_.items()},
        "still_failing": [v for v in rf_ if rf_[v] > bar + 1e-9],
        "drops": drops, "drop_ids": ids,
        "pending": {k: v for k, v in pending.items() if k not in drops},
    }  # fmt: skip


def leakers(model: str, run: Path, root: Path | None = None, apply: bool = False,
            patterns: tuple[str, ...] = HISTORY) -> dict:  # fmt: skip
    """Every family measured in ``run`` (``<family>/blind.json``): :func:`decide` against the
    earlier runs under ``root`` (default: ``run``'s parent), written to ``<run>/leakers.json``;
    ``apply`` drops the confirmed ids through ``run.drop``. Only ``run``'s flags can drop: an item
    an earlier run flagged that ``run`` does not is kept."""
    from . import run as adapt_run

    root = root or run.parent
    out: dict[str, Any] = {}
    cmds = []
    for fd in sorted(p for p in run.iterdir() if (p / "blind.json").exists()):
        fam = fd.name
        d = out[fam] = decide(model, fam, fd, root, patterns)
        prior = sorted({r for x in d["drops"].values() for r in x["prior_runs"]})
        print(f"{fam:24s} shipped={d['n_shipped']} bar={d['bar']:.3f} before={d['rates_before']}"
              f" after={d['rates_after']} drops={len(d['drop_ids'])}"
              f" pending={len(d['pending'])} still_failing={d['still_failing']}")  # fmt: skip
        if d["drop_ids"]:
            reason = R_LEAK.format(run=run.name, prior=", ".join(prior))
            cmds.append((fam, d["drop_ids"], reason))
    store.write_json(run / "leakers.json", out)
    _act(model, cmds, apply, adapt_run.drop)
    return out


def _act(model: str, cmds: list[tuple[str, list[str], str]], apply: bool, drop: Callable) -> None:
    for fam, ids, reason in cmds:
        if apply:
            drop(model, fam, ids, reason)
            print(f"dropped {fam}: {len(ids)}")
        else:
            q_ids, q_why = shlex.quote("ids=" + ",".join(ids)), shlex.quote("reason=" + reason)
            print(f"python -m wsbench.adapt drop model={model} family={fam} {q_ids} {q_why}")
    if not apply and cmds:
        print("(not applied: pass apply=true)")


# ---------------------------------------------------------------------------- D4-D7: screens
CAPITAL_FAMILIES = (
    "association", "basic_readout", "basic_readout_mt", "typo_mt", "multihop",
    "role_bound_association", "poetry", "user_modeling", "multilingual", "multilingual_mt",
    "multilingual_typo", "multilingual_multihop", "relational_multihop",
    "conjunctive_association", "chain_intermediates",
)  # fmt: skip
# D5 keeps the two figurative typo_mt rows (plan 0075 "Data round rules")
CAPITAL_KEEP = frozenset({"tyh-real-gastronomy", "typo-au-t1-w100c0-tyh-novel-decentralization"})
CAPITAL = re.compile(
    r"\bcapital\b(?!\s+(?:letters?|[A-Z]\b|crimes?|offen[cs]es?|punishment|gains?|invest\w*|"
    r"expenditures?|markets?|goods|assets?|ships?|T\b))|imperial (?:city|seat|residence)|"
    r"seat of (?:government|power|the (?:emperor|court))|首都|столиц|capitale|hauptstadt|"
    r"thủ đô|عاصم|ibu ?kota|수도|राजधानी|başkent|پایتخت|stolic|mji mkuu|เมืองหลวง|"
    r"πρωτεύουσα|בירת|huvudstad|hoofdstad|capitais",
    re.I,
)
TEXT_KEYS = ("prompt", "stimulus", "bridge_question", "hop2_question", "text", "question",
             "scene", "user")  # fmt: skip


def prompt_texts(it: dict) -> list[str]:
    """The prompt-side strings of an item (never golds, options or forms)."""
    out = [it[k] for k in TEXT_KEYS if isinstance(it.get(k), str)]
    out += [str(x) for x in it.get("shortcut_prompts") or []]
    out += [m["content"] for m in _seq(it.get("messages"))
            if isinstance(m, dict) and isinstance(m.get("content"), str)]  # fmt: skip
    if isinstance(it.get("prompts"), dict):
        out += [str(v) for v in it["prompts"].values()]
    return out


def _seq(v: Any) -> list:
    """A list field some banks store as its Python repr."""
    if isinstance(v, str) and v.startswith("["):
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return []
    return v if isinstance(v, list) else []


def capital_hits(model: str) -> dict[str, list[tuple[str, str]]]:
    """D5: ``{family: [(id, context)]}`` for every shipped item whose prompt text routes through
    a capital (any origin, any language)."""
    out: dict[str, list[tuple[str, str]]] = {}
    for fam in CAPITAL_FAMILIES:
        for it in shipped(model, fam):
            iid = store.item_id(it)
            if iid in CAPITAL_KEEP:
                continue
            for t in prompt_texts(it):
                if mm := CAPITAL.search(t):
                    ctx = t[max(0, mm.start() - 90) : mm.end() + 50].replace("\n", " ")
                    out.setdefault(fam, []).append((iid, ctx))
                    break
    return out


def _age(pos_item: tuple[int, dict]) -> tuple:
    i, it = pos_item
    a = it.get("adapt") or {}
    return (a.get("origin", "original") != "original", a.get("wave") or 0, i)


def class_caps(model: str, cap: float = 0.20) -> dict[str, dict]:
    """D7: user_modeling Country and Gender at most ``cap`` of the shipped family each; the
    newest rows above a cap drop (authored by wave, then bank order; originals last). One cap's
    drops shrink the family and can push the other class over, so it repeats until stable."""
    items = list(enumerate(shipped(model, "user_modeling")))
    n0 = len(items)
    before = {
        c: sum(1 for _, it in items if it.get("attr_class") == c) for c in ("Country", "Gender")
    }
    gone: dict[str, set[str]] = {"Country": set(), "Gender": set()}
    changed = True
    while changed:
        changed = False
        for cls in ("Country", "Gender"):
            n = len(items)
            rows = [x for x in items if x[1].get("attr_class") == cls]
            # k rows leave: (g - k) / (n - k) <= cap
            k = max(0, math.ceil((len(rows) - cap * n) / (1 - cap) - 1e-9))
            if k:
                ids = {store.item_id(it) for _, it in sorted(rows, key=_age, reverse=True)[:k]}
                gone[cls] |= ids
                items = [x for x in items if store.item_id(x[1]) not in ids]
                changed = True
    n = len(items)
    return {
        c: {
            "ids": sorted(ids),
            "before": f"{before[c]}/{n0}",
            "after": f"{before[c] - len(ids)}/{n}",
        }
        for c, ids in gone.items()
        if ids
    }


D4_FAMILIES = ("multihop", "multilingual_multihop")
D4_KEEP = ("firstname",)  # every 0075 / 0089 run tree kept the *firstname* items D4 flagged
D4_SYSTEM = (
    "You audit two-hop benchmark questions. Each question is meant to require an intermediate "
    "entity (the bridge): the reader first recalls the bridge, then the answer from it. Flag the "
    "item (shortcut=true) ONLY when the thing named in the question is, in common knowledge, "
    "directly and routinely paired with the answer itself, so a reader states the answer without "
    "ever recalling the bridge. Flag these patterns: an author named from a famous place, "
    "character trait or detail of the work (Hogwarts -> Rowling, Neverland -> Barrie, Lilliput "
    "-> Swift, servant Friday -> Defoe, Hundred Acre Wood -> Milne, the vampire count from "
    "Transylvania -> Stoker); a landmark or nickname whose own location IS the answer while the "
    "bridge is a smaller place inside it (Griffith Observatory -> California via Los Angeles, Sin "
    "City -> Nevada via Las Vegas, 221B Baker Street -> London via Sherlock Holmes); a fact "
    "stated with the named thing itself (Christmas -> winter, a stop sign -> 8 sides, the Odyssey "
    "-> the Iliad, the fruit in the gravity story -> apple); a question whose wording answers "
    "itself (the border between the US and ___). Do NOT flag a chain where the answer is a "
    "property of a country, city, person or object the reader must first identify, even if a "
    "well-read person could also link the start to the answer: the continent / ocean / river / "
    "currency / language / capital-free property of the country of a landmark (Eiffel Tower -> "
    "Europe, Taj Mahal -> Asia, Giza -> Africa, Great Sphinx -> Nile, Mount Fuji -> Pacific: all "
    "keep), the chemical symbol of the element with atomic number N (keep), the birthplace / "
    "nationality of the person who did X (keep), a number derived from a recalled name (keep). "
    "When in doubt, do not flag."
)
D6_SYSTEM = (
    "You check a benchmark item. The user's text is meant to imply their home country without "
    "naming it. List every named city, town, suburb, neighbourhood or district in the text (not "
    "regions, provinces, states, landmarks, festivals, dishes or brands), each with the country it "
    "is in. Then say whether any listed place is in the given country."
)
D6B_SYSTEM = (
    "You check a benchmark item. The user's text is meant to imply their home country without "
    "naming it, through customs, festivals, foods, language or habits. List every NAMED PLACE in "
    "the text: cities, towns, suburbs, districts, regions, provinces, states, islands, mountains, "
    "rivers, lakes, coasts, parks, trails, roads, squares, transit lines, buildings, monuments and "
    "other landmarks (not festivals, dishes, drinks, brands, sports teams, languages or people), "
    "each with the country it is in. Then say whether any listed place is in the given country."
)


def _d4_text(it: dict) -> str:
    bridges = it.get("intermediates")
    bridges = _seq(bridges) if isinstance(bridges, str) else bridges
    bq = " / ".join(b.get("question", "") for b in _seq(it.get("bridges")) if isinstance(b, dict))
    return (f"Question: {it.get('prompt', '')}\nBridge: {bridges}\nBridge question(s): {bq}\n"
            f"Answer: {it.get('target')}")  # fmt: skip


def _user_text(it: dict) -> str:
    return " ".join(m["content"] for m in _seq(it.get("messages")) if m.get("role") == "user")


def _ask(asks: list[tuple[str, str]], schema: dict, cache_path: Path, llm_model: str,
         stream: Callable | None) -> dict[str, dict]:  # fmt: skip
    """Cached structured calls keyed by the user text; only new texts are asked."""
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [(s, u) for s, u in dict.fromkeys(asks) if u not in cache]
    if todo:
        if stream is None:
            from wsbench import llm

            stream = llm.stream_json
        got: dict[int, dict] = {}
        stream(todo, schema=schema, model=llm_model,
               on_result=lambda i, r: got.__setitem__(i, r), concurrency=16)  # fmt: skip
        for i, (_s, u) in enumerate(todo):
            if got.get(i) is not None:
                cache[u] = got[i]
        store.write_json(cache_path, cache)
    return cache


def _schema(name: str, props: dict, req: list[str]) -> dict:
    from wsbench import llm

    return llm.schema_block(name, props, req)


def shortcut_flags(model: str, out: Path, llm_model: str, stream: Callable | None = None):
    """D4 (Opus): ``{family: [(id, why)]}``; unanswered items are reported, never dropped."""
    rows = [(f, it) for f in D4_FAMILIES for it in shipped(model, f)]
    schema = _schema("mh", {"shortcut": {"type": "boolean"}, "why": {"type": "string"}},
                     ["shortcut", "why"])  # fmt: skip
    cache = _ask([(D4_SYSTEM, _d4_text(it)) for _f, it in rows], schema,
                 out / "d4_cache.json", llm_model, stream)  # fmt: skip
    flags: dict[str, list] = {}
    unchecked = []
    for f, it in rows:
        iid, r = store.item_id(it), cache.get(_d4_text(it))
        if r is None:
            unchecked.append(iid)
        elif r.get("shortcut") and not any(s in iid for s in D4_KEEP):
            flags.setdefault(f, []).append((iid, str(r.get("why", ""))[:200]))
    return flags, unchecked


def place_flags(model: str, out: Path, llm_model: str, stream: Callable | None = None):
    """D6 / D6b (Opus) on user_modeling Country rows: ``({"d6": [..], "d6b": [..]}, unchecked)``."""
    rows = [it for it in shipped(model, "user_modeling") if it.get("attr_class") == "Country"]
    place = {"type": "object", "properties": {"place": {"type": "string"},
             "country": {"type": "string"}}, "required": ["place", "country"],
             "additionalProperties": False}  # fmt: skip
    schema = _schema("cities", {"places": {"type": "array", "items": place},
                                "in_gold_country": {"type": "boolean"}},
                     ["places", "in_gold_country"])  # fmt: skip

    def text(it: dict) -> str:
        return f"Country: {str(it.get('attr', '')).replace('_', ' ')}\nText: {_user_text(it)}"

    res: dict[str, list] = {"d6": [], "d6b": []}
    unchecked = []
    city = _ask([(D6_SYSTEM, text(it)) for it in rows], schema, out / "d6_cache.json",
                llm_model, stream)  # fmt: skip
    hit = set()
    for it in rows:
        r = city.get(text(it))
        if r is None:
            unchecked.append(store.item_id(it))
        elif r.get("in_gold_country"):
            hit.add(store.item_id(it))
            res["d6"].append((store.item_id(it), [p.get("place") for p in r.get("places", [])]))
    rest = [it for it in rows if store.item_id(it) not in hit]
    other = _ask([(D6B_SYSTEM, text(it)) for it in rest], schema, out / "d6b_cache.json",
                 llm_model, stream)  # fmt: skip
    for it in rest:
        r = other.get(text(it))
        if r is None:
            unchecked.append(store.item_id(it))
        elif r.get("in_gold_country"):
            res["d6b"].append((store.item_id(it), [p.get("place") for p in r.get("places", [])]))
    return res, sorted(set(unchecked))


SCREENS = ("d4", "d5", "d6", "d7")


def screens(model: str, out: Path, apply: bool = False, llm_model: str = "claude-opus-5-5",
            only: tuple[str, ...] = SCREENS, stream: Callable | None = None) -> dict:  # fmt: skip
    """D4-D7 on the shipped bank, in that order of application: D5 / D4 / D6 drops first, then
    the D7 caps over what is left. Writes ``<out>/screens.json``."""
    from . import run as adapt_run

    if bad := [s for s in only if s not in SCREENS]:
        raise SystemExit(f"dataround screens: unknown only= {bad} (known: {', '.join(SCREENS)})")
    out.mkdir(parents=True, exist_ok=True)
    rep: dict[str, Any] = {}
    cmds: list[tuple[str, list[str], str]] = []
    if "d5" in only:
        rep["d5"] = capital_hits(model)
        cmds += [(f, twins(f, {i for i, _ in xs}), REASONS["d5"]) for f, xs in rep["d5"].items()]
    if "d4" in only:
        flags, unchecked = shortcut_flags(model, out, llm_model, stream)
        rep["d4"], rep["d4_unchecked"] = flags, unchecked
        cmds += [(f, sorted({i for i, _ in xs}), REASONS["d4"]) for f, xs in flags.items()]
    if "d6" in only:
        flags, unchecked = place_flags(model, out, llm_model, stream)
        rep["d6"], rep["d6_unchecked"] = flags, unchecked
        cmds += [("user_modeling", sorted({i for i, _ in xs}), REASONS[k])
                 for k, xs in flags.items() if xs]  # fmt: skip
    _act(model, cmds, apply, adapt_run.drop)
    if "d7" in only:  # after the other drops: the caps are shares of what then ships
        if not apply and cmds:
            print("d7: computed on the bank BEFORE the drops above (apply=true for the real caps)")
        rep["d7"] = class_caps(model)
        cmds7 = [("user_modeling", v["ids"], REASONS["d7"].format(cls=c, before=v["before"],
                  after=v["after"])) for c, v in rep["d7"].items()]  # fmt: skip
        _act(model, cmds7, apply, adapt_run.drop)
    um = shipped(model, "user_modeling")
    if um:
        cls = Counter(it.get("attr_class") for it in um)
        rep["user_modeling_shares"] = {k: f"{v}/{len(um)}" for k, v in cls.most_common()}
    for k in SCREENS:
        if k in rep:
            n = sum(len(v["ids"]) if isinstance(v, dict) else len(v) for v in rep[k].values())
            print(f"{k}: {n}")
    store.write_json(out / "screens.json", rep)
    return rep


# ---------------------------------------------------------------------------- short families
OBJECTIVE_STOPS = ("pool exhausted", "yield", "crash cap", "ladder exhausted")
REFILL_ROUTES = frozenset(rf.POLICY) | frozenset(rf.FILL_POLICY) | {"basic_readout"}


def short(model: str) -> dict[str, list[str]]:
    """Families below target in ``report.json``: ``refill`` = short with a refill route and no
    objective stop yet (back-fill them); ``max_waves`` = those whose last refill ran out of waves
    (re-run with more); ``final`` = short on an objective stop (ooc / blocked / pool exhausted /
    yield / crash cap: report, never re-wave)."""
    fams = store.read_report(model).get("families") or {}
    out: dict[str, list[str]] = {"refill": [], "max_waves": [], "final": []}
    for f, e in sorted(fams.items()):
        if f == "buggy_code":
            have, target = e.get("n_pairs") or 0, e.get("target_pairs") or 0
        else:
            have, target = e.get("n_items") or 0, e.get("target") or 0
        if f not in REFILL_ROUTES or have >= target:
            continue
        stop = str((rf.refill_block(e) or {}).get("stop") or "")
        if e.get("status") in ("ooc", "blocked") or any(s in stop for s in OBJECTIVE_STOPS):
            out["final"].append(f)
            continue
        out["refill"].append(f)
        if stop.startswith("max waves"):
            out["max_waves"].append(f)
    return out


def counts(model: str) -> dict[str, Any]:
    """Shipped units per family (pairs for buggy_code) and the audited drops so far: the driver's
    convergence check (a cycle dropped nothing, a back-fill landed nothing) compares two."""
    rep = store.read_report(model)
    fams = rep.get("families") or {}
    return {
        "families": {f: int((e.get("n_pairs") if f == "buggy_code" else e.get("n_items")) or 0)
                     for f, e in sorted(fams.items())},
        "drops": sum(len(v) for v in (rep.get("drops") or {}).values()),
    }  # fmt: skip


def lucky_families(model: str) -> dict[str, list[str]]:
    """The MC families the set ships, split by how lucky guessing measures them: ``both`` (blind +
    described) and ``blind_only`` (under ``BLIND_ONLY_BELOW`` items: no described guesser)."""
    out: dict[str, list[str]] = {"both": [], "blind_only": []}
    for f in MC_FAMILIES:
        n = len(shipped(model, f))
        if n:
            out["both" if n >= BLIND_ONLY_BELOW else "blind_only"].append(f)
    return out
