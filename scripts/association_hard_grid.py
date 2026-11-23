"""association_hard, the option-grid pass (plan 0108 §2.3); its output `grid_v1.json` is
committed and is an input of `scripts/build_association_hard_bank.py`. It was run TWICE: the
first run (`grid_run1.json`, also committed and also read by the builder) refused five composed
cells because of its compose prompt; the second run, with the prompt below, is `grid_v1.json`.

    python scripts/association_hard_grid.py --src bank_final_B.json --work DIR --out grid_v1.json

For every complex item it parses the seven distractors into the grid's roles, has Opus 5.5
compose the one missing cell (replacing the off-grid option), screens the new list on the scene
(gold 5 of 5) and runs the options-only guessers in two replicate measurements (5 draws each of
the same prompt; the described guesser's examples come from the other items of the pass, so
its picks depend on which items are in it). Every model call is cached in `--work` by key and
prompt, so a re-run with the same prompts asks nothing twice. It reads the scene, the options
and the forms only.
"""

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from wsbench import llm, mc  # noqa: E402
from wsbench.baselines import lucky_guessing as lg  # noqa: E402
from wsbench.evals.association.association_hard import bank as bk  # noqa: E402
from wsbench.llm import schema_block  # noqa: E402

MODEL = "claude-opus-5-5"
BUILT = "2026-11-23"
SCREEN_DRAWS = 5
GUESS_DRAWS = 5
MEASUREMENTS = ("final", "confirm")
# the guessers' task line: the registered `association` description, the one both earlier
# measurements of the candidate lists used
GUESS_FAMILY = "association"

COMPOSE_SYSTEM = """You edit one multiple-choice option. Every option of the list joins two \
parts (a thing and its qualifier, its material, or the place it is in), all written to one pattern \
in one language. You get the worked options of the list, one of them to rewrite, and the part to \
exchange. Write that option with the one part exchanged and everything else kept: the same \
language, pattern, word order and other part, with the article and agreement corrected. Add \
nothing."""
COMPOSE_USER = """Language: {lang}
Worked options:
{worked}

Rewrite the option: {donor}
Exchange its part "{old}" for "{head}"."""
COMPOSE_SCHEMA = schema_block("grid_cell", {"option": {"type": "string"}}, ["option"])

SWAP_SYSTEM = """You write multiple-choice options for a benchmark. You get a correct concept, \
its category and the options already listed. Propose six further members of the same category, \
each as specific, as well known and written in the same language and form (article included) as \
the listed options, none of them the correct concept, a synonym of it, or already listed."""
SWAP_USER = "Correct concept: {gold}\nCategory: {category}\nAlready listed:\n{listing}"
SWAP_SCHEMA = schema_block(
    "swap", {"candidates": {"type": "array", "items": {"type": "string"}}}, ["candidates"]
)

# the scene screen of scripts/association_distractors.py, under this script's own constants
SCREEN_SYSTEM = """You read a short passage that evokes one concept without naming it. Pick the \
listed concept the passage evokes. Answer with the option number."""
SCREEN_USER = "PASSAGE:\n{scene}\n\nWhich concept does the passage evoke?\n{listing}"
SCREEN_SCHEMA = schema_block("scene_pick", {"choice": {"type": "integer"}}, ["choice"])


class Calls:
    """Model calls cached by key and prompt hash in ``<work>/calls.jsonl`` (append-only)."""

    def __init__(self, work: Path):
        self.path = work / "calls.jsonl"
        self.have: dict[str, Any] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.have[row["key"]] = row["result"]

    def run(
        self, reqs: list[tuple[str, str, str]], schema: dict[str, Any], effort: str | None = None
    ) -> dict[str, Any]:
        """``reqs`` = (key, system, user); returns key -> result (``None`` = failed call)."""
        reqs = [
            (f"{k}|{hashlib.sha256((s + u).encode()).hexdigest()[:12]}", s, u) for k, s, u in reqs
        ]
        todo = [r for r in reqs if self.have.get(r[0]) is None]
        got: dict[int, Any] = {}
        if todo:
            llm.stream_json(
                [(s, u) for _k, s, u in todo],
                schema=schema,
                model=MODEL,
                reasoning={"anthropic_effort": effort} if effort else None,
                on_result=got.__setitem__,
                concurrency=96,
                rpm=3000,
                timeout=600.0,
            )
            with self.path.open("a", encoding="utf-8") as f:
                for i, (k, _s, _u) in enumerate(todo):
                    if got.get(i) is not None:
                        self.have[k] = got[i]
                        f.write(json.dumps({"key": k, "result": got[i]}, ensure_ascii=False) + "\n")
        return {k.rsplit("|", 1)[0]: self.have.get(k) for k, _s, _u in reqs}


def _inside(head: str, option: str) -> bool:
    h = mc.fold(bk.bare(head) or head).strip()
    o = mc.fold(bk.bare(option) or option)
    return option != head and re.search(rf"(?<!\w){re.escape(h)}(?!\w)", o) is not None


def remainder(option: str, head: str) -> str:
    """The option without its article and its head: the qualifier, material or place as written."""
    h = mc.fold(bk.bare(head) or head).strip()
    o = mc.fold(bk.bare(option) or option)
    return re.sub(r"\s+", " ", re.sub(rf"(?<!\w){re.escape(h)}(?!\w)", " ", o, count=1)).strip()


def _close(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def parse(item: dict[str, Any]) -> dict[str, Any] | str:
    """The candidate list by role, or the reason it does not have the shape: the gold A+B, A+B',
    A'+B, A'+B', the bare heads B and B', one off-grid option, and ONE compound of a third
    qualifier C (``C_have``, on the head ``C_on``); the cell C on the other head (``C_to``) is
    the one the list lacks."""
    gold, ds = item["mc"]["gold"], list(item["mc"]["distractors"])
    opts = [gold, *ds]
    heads = [o for o in opts if sum(_inside(o, x) for x in opts) >= 2]
    b = [h for h in heads if _inside(h, gold)]
    if len(heads) != 2 or len(b) != 1:
        return f"{len(heads)} bare heads, {len(b)} inside the gold"
    hb = b[0]
    hb2 = next(h for h in heads if h != hb)
    rest = [o for o in ds if o not in heads]
    on_b = [o for o in rest if _inside(hb, o)]
    on_b2 = [o for o in rest if _inside(hb2, o)]
    orphan = [o for o in rest if o not in on_b and o not in on_b2]
    shape = (len(on_b), len(on_b2), len(orphan))
    if shape not in ((1, 3, 1), (2, 2, 1)):
        return f"{shape[0]} / {shape[1]} / {shape[2]} compounds on B / on B' / off the grid"
    a = remainder(gold, hb)
    left2 = list(on_b2)
    ab2 = max(left2, key=lambda o: _close(remainder(o, hb2), a))
    left2.remove(ab2)
    if shape == (1, 3, 1):
        a2b = on_b[0]
        a2b2 = max(left2, key=lambda o: _close(remainder(o, hb2), remainder(a2b, hb)))
        left2.remove(a2b2)
        c_have, c_on, c_to = left2[0], hb2, hb
    else:
        a2b2 = left2[0]
        a2b = max(on_b, key=lambda o: _close(remainder(o, hb), remainder(a2b2, hb2)))
        c_have, c_on, c_to = next(o for o in on_b if o != a2b), hb, hb2
    if (
        _close(remainder(ab2, hb2), a) < 0.6
        or _close(remainder(a2b2, hb2), remainder(a2b, hb)) < 0.6
    ):
        return "the B' compounds do not repeat the qualifiers of the B compounds"
    return {
        "B": hb, "B2": hb2, "AB": gold, "A2B": a2b, "AB2": ab2, "A2B2": a2b2,
        "C_have": c_have, "C_on": c_on, "C_to": c_to, "off_grid": orphan[0],
    }  # fmt: skip


def check_cell(new: str, r: dict[str, Any]) -> str:
    """Why the composed cell is not the missing one ("" = it is)."""
    if not _inside(r["C_to"], new) or _inside(r["C_on"], new):
        return "it does not hold the wanted head alone"
    listed = [r[k] for k in ("B", "B2", "AB", "A2B", "AB2", "A2B2", "C_have", "off_grid")]
    if mc.fold(new).strip() in {mc.fold(o).strip() for o in listed}:
        return "it repeats a listed option"
    c = remainder(r["C_have"], r["C_on"])
    if _close(remainder(new, r["C_to"]), c) < 0.6:
        return f"its qualifier {remainder(new, r['C_to'])!r} is not {c!r}"
    if bool(bk.bare(new)) != bool(bk.bare(r["AB"])):
        return "its article differs from the gold's"
    return ""


def grid_of(new: str, r: dict[str, Any]) -> dict[str, Any]:
    """The 3 x 2 grid: qualifiers named as written on the gold's head B."""
    cb, cb2 = (new, r["C_have"]) if r["C_to"] == r["B"] else (r["C_have"], new)
    qa, qa2, qc = (remainder(x, r["B"]) for x in (r["AB"], r["A2B"], cb))
    return {
        "heads": [r["B"], r["B2"]],
        "qualifiers": [qa, qa2, qc],
        "cells": {
            r["AB"]: [qa, r["B"]], r["A2B"]: [qa2, r["B"]], cb: [qc, r["B"]],
            r["AB2"]: [qa, r["B2"]], r["A2B2"]: [qa2, r["B2"]], cb2: [qc, r["B2"]],
        },
    }  # fmt: skip


def lg_items(lists: dict[str, tuple[list[str], str]]) -> list[lg.Item]:
    return [
        lg.Item(n, [list(opts)], [opts.index(gold) + 1], meta={})
        for n, (opts, gold) in lists.items()
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; write to a fresh path")
    a.work.mkdir(parents=True, exist_ok=True)
    from build_association_hard_bank import DROP, SCENE_NAMED  # the tables of record

    calls = Calls(a.work)
    src = [
        it
        for it in json.loads(a.src.read_text(encoding="utf-8"))["items"]
        if it["name"] not in DROP
    ]
    by = {it["name"]: it for it in src}
    out_items: dict[str, Any] = {}
    dropped: dict[str, str] = {}
    unparsed: dict[str, str] = {}

    # 1. roles, 2. the missing cell
    roles: dict[str, dict[str, Any]] = {}
    for it in src:
        if it["kind"] == "obscure":
            continue
        r = parse(it)
        if isinstance(r, str):
            unparsed[it["name"]] = r
        else:
            roles[it["name"]] = r
    if unparsed:
        raise SystemExit(
            f"items that do not fit the grid (add them to DROP with the reason): {unparsed}"
        )
    reqs = []
    for n, r in roles.items():
        worked = "\n".join(f"- {r[k]}" for k in ("AB", "AB2", "A2B", "A2B2", "C_have"))
        user = (
            COMPOSE_USER.replace("{lang}", by[n]["lang"])
            .replace("{worked}", worked)
            .replace("{head}", r["C_to"])
            .replace("{old}", r["C_on"])
            .replace("{donor}", r["C_have"])
        )
        reqs.append((f"compose|{n}", COMPOSE_SYSTEM, user))
    composed = calls.run(reqs, COMPOSE_SCHEMA)
    new_lists: dict[str, tuple[list[str], str]] = {}
    for n, r in roles.items():
        res = composed[f"compose|{n}"]
        new = str((res or {}).get("option", "")).strip()
        why = "the compose call failed" if not new else check_cell(new, r)
        if why:
            dropped[n] = f"grid pass: the composed cell {new!r} is refused ({why})"
            continue
        opts = [o for o in [r["AB"], *by[n]["mc"]["distractors"]] if o != r["off_grid"]] + [new]
        out_items[n] = {"replaced": r["off_grid"], "new": new, "grid": grid_of(new, r)}
        new_lists[n] = (bk.option_order(opts, n), r["AB"])

    # 3. a distractor the scene names (SCENE_NAMED): one replacement from the gold and category
    swaps: dict[str, Any] = {}
    for n, old in SCENE_NAMED.items():
        it = by[n]
        m = it["mc"]
        listed = [m["gold"], *m["distractors"]]
        user = (
            SWAP_USER.replace("{gold}", m["gold"])
            .replace("{category}", m["category"])
            .replace("{listing}", "\n".join(f"- {o}" for o in listed))
        )
        res = calls.run([(f"swap|{n}", SWAP_SYSTEM, user)], SWAP_SCHEMA)[f"swap|{n}"] or {}
        cands = [str(c).strip() for c in res.get("candidates", [])]
        ok = [
            c
            for c in cands
            if c
            and mc.fold(c) not in {mc.fold(o) for o in listed}
            and not mc.form_in(it["prompt"], bk.widen([c]))
        ]
        if not ok:
            dropped[n] = f"grid pass: no replacement for {old!r} that the scene does not name"
            continue
        opts = [o for o in listed if o != old] + [ok[0]]
        swaps[n] = {"replaced": old, "new": ok[0], "proposed": cands}
        new_lists[n] = (bk.option_order(opts, n), m["gold"])

    # 4. the scene screen on every changed list
    reqs = []
    for n, (opts, _gold) in new_lists.items():
        user = SCREEN_USER.replace("{scene}", by[n]["prompt"]).replace(
            "{listing}", mc.listing(opts)
        )
        reqs += [(f"screen|{n}|{d}", SCREEN_SYSTEM, user) for d in range(SCREEN_DRAWS)]
    screened = calls.run(reqs, SCREEN_SCHEMA, effort="default")
    for n, (opts, gold) in list(new_lists.items()):
        picks = [(screened[f"screen|{n}|{d}"] or {}).get("choice") for d in range(SCREEN_DRAWS)]
        rec = out_items.get(n) or swaps[n]
        rec["screen"] = [
            opts[p - 1] if isinstance(p, int) and 1 <= p <= len(opts) else None for p in picks
        ]
        if rec["screen"] != [gold] * SCREEN_DRAWS:
            hits = rec["screen"].count(gold)
            dropped[n] = f"grid pass: the scene screen picks the gold {hits} of 5 on the new list"
            del new_lists[n]

    # 5. the options-only guessers, twice, on every changed list (examples from the whole bank)
    lists = {
        it["name"]: new_lists.get(
            it["name"],
            (
                bk.option_order([it["mc"]["gold"], *it["mc"]["distractors"]], it["name"]),
                it["mc"]["gold"],
            ),
        )
        for it in src
        if it["name"] not in dropped
    }
    items = lg_items(lists)
    reqs = []
    for i, item in enumerate(items):
        if item.id not in new_lists:
            continue
        for v in ("blind", "described"):
            ex = (
                lg.pick_examples(items, i, GUESS_FAMILY, lg.DEFAULT_SEED)
                if v == "described"
                else None
            )
            user = lg.user_message(item, v, GUESS_FAMILY, ex)
            reqs += [
                (f"guess|{meas}|{item.id}|{v}|{d}", lg.SYSTEM, user)
                for meas in MEASUREMENTS
                for d in range(GUESS_DRAWS)
            ]
    guessed = calls.run(reqs, lg.schema(1))
    item_of = {x.id: x for x in items}
    for n in list(new_lists):
        rec = out_items.get(n) or swaps[n]
        rec["guess"] = {}
        for meas in MEASUREMENTS:
            rec["guess"][meas] = {}
            for v in ("blind", "described"):
                hits = 0
                for d in range(GUESS_DRAWS):
                    s = lg.score_draw(guessed[f"guess|{meas}|{n}|{v}|{d}"], item_of[n])
                    hits += bool(s and s["correct"])
                rec["guess"][meas][v] = hits
        if all(max(rec["guess"][m].values()) >= bk.GUESS_LEAK for m in MEASUREMENTS):
            dropped[n] = (
                f"grid pass: guessable from the new list in both measurements ({rec['guess']})"
            )
    for n, rec in [*out_items.items(), *swaps.items()]:
        rec["kept"] = n not in dropped
    failed = [k for k, v in calls.have.items() if v is None]
    if failed:
        raise SystemExit(f"{len(failed)} calls failed; re-run")
    doc = {
        "version": 1,
        "built": BUILT,
        "model": MODEL,
        "what": "per complex item the composed cell C+B that replaces the off-grid option, its "
        "grid, the 5-draw scene screen and two options-only guesser measurements (blind / "
        "described, hits of 5; replicate draws of one prompt) on the new list; `swaps` = the "
        "same evidence for a replaced distractor the scene names; `kept` = whether this run "
        "keeps the item; `dropped` = items this run removes, with the reason",
        "prompts": {
            "COMPOSE_SYSTEM": COMPOSE_SYSTEM,
            "COMPOSE_USER": COMPOSE_USER,
            "SWAP_SYSTEM": SWAP_SYSTEM,
            "SWAP_USER": SWAP_USER,
            "SCREEN_SYSTEM": SCREEN_SYSTEM,
            "SCREEN_USER": SCREEN_USER,
            "guessers": "wsbench.baselines.lucky_guessing blind / described, family line "
            + repr(GUESS_FAMILY),
        },
        "items": out_items,
        "swaps": swaps,
        "dropped": dropped,
    }
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"composed {len(out_items)}, swaps {len(swaps)}, dropped {len(dropped)}: {dropped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
