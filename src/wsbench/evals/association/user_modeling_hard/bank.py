"""The user_modeling_hard bank's own checks (V1-V14) and counts: the builder script, the judge's
loader (fail closed) and the bank tests run this one ``validate``."""

import difflib
import hashlib
import math
import re
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wsbench import mc
from wsbench.banks import label_of

# the option-seed prefix: a bank property that never moves with the judge stamp (umh-v3 today), so
# that an unchanged part keeps its option order across bank versions
STAMP = "umh-v1"
# (the kind `life` was removed in bank v2, review r3: an item of it fails V1)
KINDS: tuple[str, ...] = ("two", "three", "state", "expertise", "stance", "fine")
PARTS_OF: dict[str, tuple[int, ...]] = {"two": (2,), "three": (3,), "state": (1, 2)}
N_OPTIONS: dict[str, int] = {"expertise": 4, "marital": 6}  # every other type: 7
DEFAULT_N_OPTIONS = 7
PAIR = ("validation", "reassurance")  # V11: never both in one goal list
EXPERTISE_MAX_SHARE = 0.4  # V12
MODAL_MIN_PARTS = 5  # a constant guesser knows a type's modal gold only from this many parts
MIXED_LABEL = "emotional state"  # V13: the label both judge prompts show for a mixed part
# V13: a label that needs the chat to be understood (an ordinal, or "the ... situation they
# describe"); the plain label "current life situation" is not one
CHAT_BOUND = re.compile(r"\b(?:first|second)\b|\bsituations?\s+(?:they|the user)\b")
MIN_GATE_CORRECT = 8  # V9
MIN_OPEN_STATED = 3  # V9
NEAR_RATIO = 0.85  # V5
_STOP = frozenset({"a", "an", "the", "to", "of"})
_SUFFIXES = ("ing", "es", "ed", "s")


def n_options(part_type: str) -> int:
    return N_OPTIONS.get(part_type, DEFAULT_N_OPTIONS)


def option_seed(name: str, k: int) -> str:
    return f"{STAMP}|{name}|p{k}"


def option_order(options: Sequence[str], seed: str) -> list[str]:
    """The frozen option order of a part: the seeded shuffle of the fold-sorted list."""
    return mc.seeded_shuffle(sorted(options, key=lambda x: (mc.fold(x), x)), seed)


def words(text: str) -> frozenset[str]:
    """The folded alphanumeric words of ``text`` minus a / an / the / to / of, each stripped of a
    final ing / es / ed / s when at least three letters remain (V5-V7)."""
    out = set()
    for w in re.findall(r"[^\W_]+", mc.fold(text)):
        if w in _STOP:
            continue
        for suf in _SUFFIXES:
            if w.endswith(suf) and len(w) - len(suf) >= 3:
                w = w[: -len(suf)]
                break
        out.add(w)
    return frozenset(out)


def subset_pair(a: str, b: str) -> bool:
    """One text's words are a subset of the other's."""
    wa, wb = words(a), words(b)
    return wa <= wb or wb <= wa


def near_duplicate(a: str, b: str) -> bool:
    """V5: the word-subset test, or a character ratio of at least :data:`NEAR_RATIO`."""
    ratio = difflib.SequenceMatcher(None, mc.fold(a), mc.fold(b)).ratio()
    return subset_pair(a, b) or ratio >= NEAR_RATIO


def user_text(item: Mapping[str, Any]) -> str:
    """The item's user turn (V8 reads it; ``messages`` = system turn + user turn)."""
    return str(item["messages"][-1]["content"])


def item_chance(item: Mapping[str, Any]) -> float:
    """The uniform single-draw chance of the all-parts rule: the product of 1 / options."""
    return math.prod(1 / len(p["options"]) for p in item["parts"])


def uniform_chance(items: Sequence[Mapping[str, Any]]) -> float | None:
    return statistics.fmean(item_chance(i) for i in items) if items else None


def constant_chance(items: Sequence[Mapping[str, Any]]) -> float | None:
    """The expected share of ``items`` (one kind) a constant guesser gets with every part right:
    for a part type with at least :data:`MODAL_MIN_PARTS` parts among them it answers that type's
    most common gold; for a smaller type it guesses uniformly."""
    if not items:
        return None
    golds: dict[str, Counter[str]] = {}
    for it in items:
        for p in it["parts"]:
            golds.setdefault(p["type"], Counter())[p["gold"]] += 1
    top = {
        t: c.most_common(1)[0][0] for t, c in golds.items() if sum(c.values()) >= MODAL_MIN_PARTS
    }

    def one(p: Mapping[str, Any]) -> float:
        if p["type"] in top:
            return 1.0 if p["gold"] == top[p["type"]] else 0.0
        return 1 / len(p["options"])

    return statistics.fmean(math.prod(one(p) for p in it["parts"]) for it in items)


def kind_chance(items: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """``{uniform, constant, chance}`` of one kind's items; ``chance`` = the larger of the two."""
    uni, const = uniform_chance(items), constant_chance(items)
    both = [x for x in (uni, const) if x is not None]
    return {"uniform": uni, "constant": const, "chance": max(both) if both else None}


def counts(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The header keys that are computed from the items (V10 compares them)."""
    kinds = Counter(i["kind"] for i in items)
    requests = Counter(str(i["request_variant"]) for i in items if i.get("request_variant"))
    parts: Counter[str] = Counter()
    types: Counter[str] = Counter()
    expertise: Counter[str] = Counter()
    for i in items:
        parts[i["kind"]] += len(i["parts"])
        for p in i["parts"]:
            types[p["type"]] += 1
            if p["type"] == "expertise":
                expertise[p["gold"]] += 1
    chance = {}
    for kind in KINDS:
        c = kind_chance([i for i in items if i["kind"] == kind])
        if c["chance"] is not None:
            chance[kind] = {
                "uniform": round(c["uniform"] or 0.0, 4),
                "modal_gold_share": round(c["constant"] or 0.0, 4),
                "chance": round(c["chance"], 4),
            }
    uni = uniform_chance(items)
    return {
        "n_items": len(items),
        "n_parts": sum(parts.values()),
        "kinds": {k: kinds[k] for k in KINDS if kinds[k]},
        "parts_per_kind": {k: parts[k] for k in KINDS if parts[k]},
        "types": dict(sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))),
        "expertise_golds": dict(sorted(expertise.items(), key=lambda kv: (-kv[1], kv[0]))),
        "uniform_chance": round(uni, 4) if uni is not None else None,
        "chance_by_kind": chance,
        # A = the chat ends with the fixed biography request (`request_variants`), B = with an
        # authored natural request: the count the READMEs and prompts.QUOTE_PERSONA's note cite
        "request_variant_counts": dict(sorted(requests.items())),
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pool_values(pools: Mapping[str, Any], part_type: str) -> list[str]:
    pool = pools.get("pools", {}).get(part_type) or {}
    return [v for cluster in pool.get("clusters", []) for v in cluster]


def _part_findings(
    name: str,
    k: int,
    p: Mapping[str, Any],
    mixed: bool,
    chat: str,
    broader: Mapping[str, Sequence[str]],
    pools: Mapping[str, Any] | None,
) -> list[str]:
    at = f"{name} p{k}"
    out: list[str] = []
    opts = list(p["options"])
    gold, forms, ptype = str(p["gold"]), list(p.get("forms") or []), str(p["type"])
    folded = [mc.fold(x) for x in opts]
    n = n_options(ptype)
    # V3
    if len(opts) != n:
        out.append(f"V3 {at}: {len(opts)} options, a {ptype} part has {n}")
    if len(set(folded)) != len(folded):
        out.append(f"V3 {at}: options repeat after folding")
    if folded.count(mc.fold(gold)) != 1:
        out.append(f"V3 {at}: the gold {gold!r} is not in the options exactly once")
    pos = p.get("gold_position")
    if not isinstance(pos, int) or not 1 <= pos <= len(opts) or opts[pos - 1] != gold:
        out.append(f"V3 {at}: gold_position {pos!r} does not point at the gold")
    if any(mc.is_cannot(str(x)) for x in opts):
        out.append(f"V3 {at}: an option is a cannot-tell text")
    seed = p.get("option_seed")
    if seed != option_seed(name, k):
        out.append(f"V3 {at}: option_seed {seed!r} is not {option_seed(name, k)!r}")
    elif opts != option_order(opts, seed):
        out.append(f"V3 {at}: the option order is not the seeded shuffle of option_seed")
    # V4
    near = set(p.get("near_neighbours") or [])
    if not near <= set(opts) - {gold}:
        out.append(f"V4 {at}: near_neighbours are not distractor options")
    if pools is not None:
        values = pool_values(pools, ptype)
        closed = bool((pools.get("pools", {}).get(ptype) or {}).get("closed"))
        if not values:
            out.append(f"V4 {at}: no option pool for type {ptype!r}")
        elif closed and set(opts) != set(values):
            out.append(f"V4 {at}: a closed type must hold the pool's whole scale")
        elif not closed and not set(opts) <= set(values):
            odd = sorted(set(opts) - set(values))
            out.append(f"V4 {at}: options outside the {ptype} pool: {odd}")
    # V5
    for a in range(len(opts)):
        for b in range(a + 1, len(opts)):
            if near_duplicate(opts[a], opts[b]):
                out.append(f"V5 {at}: near-duplicate options {opts[a]!r} / {opts[b]!r}")
    # V6
    terms = {mc.fold(t) for t in broader.get(ptype, ())}
    for f in forms:
        for x in opts:
            if x != gold and subset_pair(f, x):
                out.append(f"V6 {at}: form {f!r} collides with the option {x!r}")
        if mc.fold(f).strip() in terms:
            out.append(f"V6 {at}: form {f!r} is a broader term of type {ptype!r}")
    # V8
    for f in (gold, *forms):
        if mc.form_in(chat, [f]):
            out.append(f"V8 {at}: {f!r} occurs in the user turn (stated, not implied)")
    # V9
    gate, probe = p.get("gate") or {}, p.get("open_probe") or {}
    if not (
        int(gate.get("n_correct", 0)) >= MIN_GATE_CORRECT
        and int(probe.get("n_stated", 0)) >= MIN_OPEN_STATED
    ):
        out.append(f"V9 {at}: gate evidence below the bar ({gate!r}, {probe!r})")
    # V11
    if ptype == "goal" and all(x in opts for x in PAIR):
        out.append(f"V11 {at}: a goal list holds both {PAIR[0]} and {PAIR[1]}")
    # V13
    label, gated = str(p.get("judge_label") or ""), str(p.get("attr_label") or "")
    if mixed and label != MIXED_LABEL:
        out.append(f"V13 {at}: a mixed-state part's judge_label must be {MIXED_LABEL!r}")
    if not mixed and label != gated:
        out.append(f"V13 {at}: judge_label {label!r} differs from attr_label {gated!r}")
    if not label or CHAT_BOUND.search(label.lower()):
        out.append(f"V13 {at}: judge_label {label!r} needs the chat to be understood")
    return out


def validate(
    header: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    *,
    pools: Mapping[str, Any] | None = None,
    sources: Mapping[str, Path] | None = None,
    require_tokens: bool = True,
) -> list[str]:
    """Every finding of V1-V14 (``[]`` = the bank is valid). ``pools`` (``option_pools.json``)
    turns on the pool-membership half of V4; ``sources`` (file name -> path) the input half of
    V10; ``require_tokens=False`` lets the builder validate before the tokenizer step (V14)."""
    out: list[str] = []
    broader = header.get("broader_by_type") or {}
    seen: set[str] = set()
    for it in items:
        name = str(it.get("name"))
        # V1
        if name in seen:
            out.append(f"V1 {name}: the name repeats")
        seen.add(name)
        if label_of(name) != name:
            out.append(f"V1 {name}: the name is not label-safe")
        kind, parts = it.get("kind"), list(it.get("parts") or [])
        mixed = bool(it.get("mixed_state"))
        if kind not in KINDS:
            out.append(f"V1 {name}: unknown kind {kind!r}")
            continue
        if len(parts) not in PARTS_OF.get(str(kind), (1,)):
            out.append(f"V1 {name}: a {kind} item cannot have {len(parts)} part(s)")
        if mixed != (kind == "state" and len(parts) == 2):
            out.append(f"V1 {name}: mixed_state must be set exactly on a two-part state item")
        # V2
        msgs = it.get("messages") or []
        roles = [m.get("role") for m in msgs]
        if roles != ["system", "user"] or not all(
            str(m.get("content") or "").strip() for m in msgs
        ):
            out.append(f"V2 {name}: messages must be one system turn and one user turn, non-empty")
            continue
        chat = user_text(it)
        for k, p in enumerate(parts):
            out += _part_findings(name, k, p, mixed, chat, broader, pools)
        # V7
        golds = [mc.fold(str(p["gold"])) for p in parts]
        if len(set(golds)) != len(golds):
            out.append(f"V7 {name}: two parts share a gold")
        for k, p in enumerate(parts):
            for k2, p2 in enumerate(parts):
                if k2 == k:
                    continue
                for f in (p["gold"], *(p.get("forms") or [])):
                    for x in p2["options"]:
                        if subset_pair(f, x):
                            out.append(
                                f"V7 {name} p{k}: {f!r} collides with the option {x!r} of part {k2}"
                            )
    # V10
    for key, want in counts(items).items():
        if header.get(key) != want:
            out.append(f"V10 header {key}: {header.get(key)!r} != the items' {want!r}")
    for fname, path in (sources or {}).items():
        have = (header.get("source_sha256") or {}).get(fname)
        if have != sha256_file(path):
            out.append(f"V10 source_sha256[{fname}] does not equal {path}")
    # V12
    levels = Counter(p["gold"] for i in items for p in i["parts"] if p["type"] == "expertise")
    total = sum(levels.values())
    for level, n in sorted(levels.items()):
        # (with fewer than three expertise parts no split of a four-level scale can meet the bar)
        if total >= 3 and n > EXPERTISE_MAX_SHARE * total:
            out.append(
                f"V12 expertise level {level!r} is the gold of {n} of {total} expertise parts "
                f"(over {EXPERTISE_MAX_SHARE:.0%})"
            )
    # V14
    tokens = header.get("min_render_tokens")
    if require_tokens and (isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1):
        out.append(
            "V14 header min_render_tokens is missing: build the bank with the subject's tokenizer "
            "(scripts/build_user_modeling_hard_bank.py)"
        )
    return out
