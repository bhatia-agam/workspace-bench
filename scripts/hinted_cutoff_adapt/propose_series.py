"""Plan 0084 top-ups: Opus-proposed NEW ccut series for a fade window (gw v2's densify precedent),
disjoint from the existing series files, for v2's ``bank_draft`` -> ``bank_verify`` -> ``bank``.

    python propose_series.py dir=<cwd>/evals/chint_cutoff lo=2025-05-01 hi=2026-01-31 \
        [per_call=30 rounds=3 out=series_v2_extra3.json force=1]
"""

import json
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

MODEL = "claude-opus-5-5"
SYSTEM = "You design quiz series for a factual-recall benchmark. Reply in the requested JSON."
EXISTING = ("series.json", "series_v2_extra.json", "series_v2_extra2.json")
SLICES = [
    ("sports", "football/soccer (club and international competitions, transfers, managers, "
     "awards)"),
    ("sports", "US and Canadian leagues (NFL, NBA, MLB, NHL, MLS, WNBA, college sports): games, "
     "trades, signings, drafts, awards"),
    ("sports", "individual sports: tennis, golf, athletics, cycling, combat sports, motorsport, "
     "winter sports, esports, chess"),
    ("sports", "other team sports and multi-sport events: cricket, rugby, basketball outside the "
     "US, handball, volleyball, hockey, world championships"),
    ("politics", "elections, referendums, leadership contests, government formations and "
     "appointments worldwide"),
    ("politics", "courts, legislation, diplomacy, sanctions, treaties, protests, arrests, "
     "resignations, military operations"),
    ("other", "business: acquisitions, IPOs, CEO changes, bankruptcies, fines, product launches, "
     "earnings milestones, strikes"),
    ("science", "technology, AI models, space missions, medicine and drug approvals, science "
     "prizes, discoveries"),
    ("arts", "film, TV, music and book awards and charts; festivals; box office; games; deaths of "
     "notable people"),
    ("other", "world news: disasters, records, city/country rankings, cultural events, words of "
     "the year, notable firsts"),
]  # fmt: skip

PROMPT = """You are extending a bank of factual-recall quiz SERIES. A series is a recurring or \
repeatable kind of dated event with a short, unambiguous, verifiable answer (a person, team or \
country, work title, or other short name), e.g. "winner of each Formula One Grand Prix", "which \
company agreed to acquire a named company (one question per deal)", "who was appointed head coach \
of a named club".

Propose {n} NEW series in this topic slice: {slice}.
They must have MANY occurrences between {lo} and {hi} that were widely and durably reported \
(broad, sustained news coverage), so that a careful writer can draft verified questions about \
them. \
Prefer series with several occurrences per month in that window.

They must be DISJOINT from every existing series below (no renamed duplicates, no narrower or \
wider versions of an existing series):
{existing}

Each series:
- id: short snake_case, unique, not in the existing ids;
- desc: one line saying exactly what is asked and how a question is phrased; for multi-event \
series \
say "one question per <event>";
- multi: true if one question per individual event (many per year), else false;
- family: reuse one of these families when it fits, else a new short snake_case family: {families};
- event_root: "per_item" when each question is its own event, else a short root naming the \
ceremony or tournament (one cluster per root and year)."""

_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "desc", "multi", "family", "event_root"],
    "properties": {
        "id": {"type": "string"},
        "desc": {"type": "string"},
        "multi": {"type": "boolean"},
        "family": {"type": "string"},
        "event_root": {"type": "string"},
    },
}
SCHEMA = {
    "name": "series",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["series"],
        "properties": {"series": {"type": "array", "items": _ITEM}},
    },
}

Ask = Callable[[list[tuple[str, str]]], list[dict | None]]


def opus_ask(prompts: list[tuple[str, str]]) -> list[dict | None]:
    """Structured calls through ``wsbench.llm``: streamed, and Opus 5.5 (always thinking) runs at
    low effort, so the reply budget goes to the list (an unstructured call at the model's default
    effort spent all 16k output tokens thinking, 2026-11-16)."""
    from wsbench import llm

    out: list[dict | None] = [None] * len(prompts)

    def on_result(i: int, r: dict | None) -> None:
        out[i] = r

    if prompts:
        llm.stream_json(prompts, schema=SCHEMA, model=MODEL, on_result=on_result,
                        concurrency=len(prompts), max_tokens=16000,
                        timeout=600.0)  # fmt: skip
    return out


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def accept(
    raw: dict | None, group: str, ids: set[str], descs: set[str], drops: Counter
) -> list[dict]:
    """The usable, new series of one reply in the series.json schema (``group`` from the slice);
    ``ids`` / ``descs`` (normalised) are the ones already taken and grow with each kept series."""
    kept = []
    if raw is None:  # a failed or refused call
        drops["failed_call"] += 1
        return kept
    for s in raw.get("series") or []:
        fields = ("id", "desc", "family", "event_root")
        if not isinstance(s, dict) or not all(isinstance(s.get(k), str) and s[k] for k in fields):
            drops["bad"] += 1
            continue
        if not re.fullmatch(r"[a-z0-9_]+", s["id"]):
            drops["bad"] += 1
            continue
        if s["id"] in ids:
            drops["dup_id"] += 1
            continue
        if norm(s["desc"]) in descs:
            drops["dup_desc"] += 1
            continue
        ids.add(s["id"])
        descs.add(norm(s["desc"]))
        kept.append({"id": s["id"], "group": group, "desc": s["desc"],
                     "multi": bool(s.get("multi")), "family": s["family"],
                     "event_root": s["event_root"]})  # fmt: skip
    return kept


def propose(
    existing: list[dict], lo: str, hi: str, per_call: int = 30, rounds: int = 3,
    ask: Ask = opus_ask,
) -> tuple[list[dict], Counter]:  # fmt: skip
    """``rounds`` sequential rounds, one call per slice each (slices in parallel); a round's
    prompt lists the existing series plus everything its slice proposed so far."""
    fams = ", ".join(sorted({s["family"] for s in existing}))
    ids = {s["id"] for s in existing}
    descs = {norm(s["desc"]) for s in existing}
    base = "\n".join(f"- {s['id']}: {s['desc'][:140]}" for s in existing)
    mine: list[list[dict]] = [[] for _ in SLICES]
    drops: Counter = Counter()
    for _ in range(rounds):
        prompts = []
        for (_group, desc), got in zip(SLICES, mine, strict=True):
            listed = "\n".join([base, *(f"- {s['id']}: {s['desc'][:140]}" for s in got)])
            user = PROMPT.format(n=per_call, slice=desc, lo=lo, hi=hi, existing=listed,
                                 families=fams)  # fmt: skip
            prompts.append((SYSTEM, user))
        for k, raw in enumerate(ask(prompts)):
            mine[k] += accept(raw, SLICES[k][0], ids, descs, drops)
    return [s for got in mine for s in got], drops


def main() -> None:
    a = dict(x.split("=", 1) for x in sys.argv[1:])
    d = Path(a["dir"])
    out = d / a.get("out", "series_v2_extra3.json")
    if out.exists() and a.get("force") != "1":
        raise SystemExit(f"{out} exists: pass force=1 to overwrite it")
    existing = [s for f in EXISTING for s in json.loads((d / f).read_text())["series"]]
    new, drops = propose(existing, a["lo"], a["hi"], int(a.get("per_call", 30)),
                         int(a.get("rounds", 3)))  # fmt: skip
    obj = {
        "_doc": f"plan 0084 top-up densify series for {a['lo']}..{a['hi']} (Opus 5.5, gw v2 "
        "densify precedent), disjoint from " + ", ".join(EXISTING) + ". Same schema.",
        "series": new,
    }
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    print(f"[propose] {len(new)} new series -> {out}; drops {dict(drops)}")


if __name__ == "__main__":
    main()
