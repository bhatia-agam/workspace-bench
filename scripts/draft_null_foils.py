"""Draft the near-miss foil sidecars ``evals/<family>/null_foils.json`` (plan 0012 §1.1).

A dev script, not part of the package. An LLM proposes 3 same-type near-miss targets per bank
item; each proposal is then checked mechanically (not an item target, not the surface answer,
not a word of the prompt or the item's reference concepts) and items with fewer than 3 clean
foils are re-asked. The prompt also forbids foils stated in the prompt in another language or
word form, which the mechanical check cannot see; Fable spot-checks that by hand.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import anthropic

from wsbench.banks import load_bank
from wsbench.basic.family import targets_of
from wsbench.mc import fold
from wsbench.nulls import K_FOIL, word_in

REPO = Path(__file__).resolve().parents[1]
FAMILIES = ["association", "basic_readout", "multihop", "multilingual", "poetry", "typo"]
MODEL = "claude-opus-5-5"
CHUNK = 20

FAMILY_NOTES = {
    "association": "The target is a concept the prompt evokes but never names.",
    "basic_readout": "The target is the obvious next concept or answer for the prompt.",
    "multihop": "The target is the unstated BRIDGE entity of a two-hop fact (not the answer).",
    "multilingual": "The prompt is non-English; the target is the English concept it computes.",
    "poetry": "The target is the rhyme WORD the model will write to end the couplet's line 2.",
    "typo": "The target is the correctly spelled word that the prompt misspells.",
}

INSTRUCTIONS = """You are building a control condition for an interpretability benchmark.
For each item below you get the prompt a language model read and the TARGET concept(s) a lens
should find in the model's activations. Write exactly 3 NEAR-MISS FOILS per item: plausible
wrong answers of the SAME TYPE as the target that a sloppy reader might confuse with it.
Examples of the type match: another sport for a sport, the adjacent month or number for a
month or number, a neighbouring colour for a colour, another word that rhymes with the line for
a rhyme word, another city in the same country for a city, a similar common word for a word.

Hard rules for every foil:
- It is NOT one of the item's targets, an alias, a synonym, a translation, or a spelling
  variant of one, and NOT the item's surface answer.
- It is NOT stated in the prompt in ANY language or word form: if the prompt says "zwei", do
  not use "two"; if it says "a dozen", do not use "12" or "twelve"; if it names Paris, do not
  use Paris. Also avoid the listed reference concepts.
- One or two words, the form a reader would write; no explanations.
{family_note}

Return JSON {"items": [{"id": "...", "foils": ["...", "...", "..."]}, ...]} covering every id."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "foils": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "foils"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def clean(item: dict[str, Any], foils: list[str]) -> list[str]:
    """Drop foils the mechanical checks catch; keep the first K_FOIL distinct survivors."""
    own = {fold(t).strip() for t in targets_of(item)}
    surface = fold(str(item.get("target") or "")).strip()
    ctx = " \n ".join(
        [str(item.get("prompt", "")), *map(str, item.get("reference_concepts") or [])]
    )
    out: list[str] = []
    for f in foils:
        ff = fold(f).strip()
        if not ff or ff in own or ff == surface or word_in(f, ctx):
            continue
        if any(ff in o or o in ff for o in own if len(o) > 3):  # "Football" vs "football club"
            continue
        if ff not in {fold(x).strip() for x in out}:
            out.append(f.strip())
    return out[:K_FOIL]


def ask(
    client: anthropic.Anthropic, family: str, chunk: list[dict[str, Any]]
) -> dict[str, list[str]]:
    payload = [
        {
            "id": it["id"],
            "prompt": it.get("prompt", ""),
            "targets": targets_of(it),
            **({"surface_answer": it["target"]} if it.get("target") else {}),
            **(
                {"reference_concepts": it["reference_concepts"]}
                if it.get("reference_concepts")
                else {}
            ),
        }
        for it in chunk
    ]
    msg = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=INSTRUCTIONS.replace("{family_note}", FAMILY_NOTES[family]),
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
    )
    if msg.stop_reason == "refusal":
        print(f"[{family}] refusal on a chunk of {len(chunk)}", file=sys.stderr)
        return {}
    text = next((b.text for b in msg.content if b.type == "text"), "")
    return {r["id"]: r["foils"] for r in json.loads(text)["items"]}


VERIFY = """You audit control foils for an interpretability benchmark. For each item you get a
prompt, its TARGET concept(s), and candidate FOILS that must be plausible wrong answers of the
same type. Flag a foil as BAD if ANY of these hold:
- it is stated in the prompt in any language or word form (prompt "zwei" -> foil "two" is BAD;
  "a dozen" -> "12" is BAD; a name in the prompt is BAD), or it is a listed reference concept;
- it means the same as a target or is a near-synonym, alias, translation, abbreviation or
  spelling variant of one ("little" or "tiny" for target "small", "final" for "last", "close"
  for "near", "football" for "soccer" are BAD);
- it is a broader category of a target or contains a target.
Foils that are merely related, opposite, or same-type alternatives are fine.
Return JSON {"items": [{"id": "...", "bad": ["<foil copied exactly>", ...]}, ...]} for every id
(an empty "bad" list when all foils are fine)."""

VSCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "bad": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "bad"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def verify(
    client: anthropic.Anthropic, chunk: list[dict[str, Any]], foils: dict[str, list[str]]
) -> dict[str, set[str]]:
    payload = [
        {
            "id": it["id"],
            "prompt": it.get("prompt", ""),
            "targets": targets_of(it),
            **(
                {"reference_concepts": it["reference_concepts"]}
                if it.get("reference_concepts")
                else {}
            ),
            "foils": foils.get(it["id"], []),
        }
        for it in chunk
    ]
    msg = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": VSCHEMA}},
        system=VERIFY,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)}],
    )
    if msg.stop_reason == "refusal":
        return {}
    text = next((b.text for b in msg.content if b.type == "text"), "")
    return {r["id"]: {fold(b).strip() for b in r["bad"]} for r in json.loads(text)["items"]}


def draft(client: anthropic.Anthropic, family: str, rounds: int = 4) -> dict[str, list[str]]:
    _h, items = load_bank(REPO / "evals" / family / "items.json")
    by_id = {it["id"]: it for it in items}
    out = REPO / "evals" / family / "null_foils.json"
    done: dict[str, list[str]] = {}
    if out.exists():  # resume: keep what an earlier run drafted, re-verify it below
        done = {k: list(v) for k, v in json.loads(out.read_text())["items"].items()}
    rejected: dict[str, set[str]] = {i: set() for i in by_id}
    todo = [i for i in by_id if len(done.get(i, [])) < K_FOIL]
    for _ in range(rounds):
        chunks = [[by_id[i] for i in todo[k : k + CHUNK]] for k in range(0, len(todo), CHUNK)]
        with ThreadPoolExecutor(8) as ex:
            for got in ex.map(lambda c: ask(client, family, c), chunks):
                for i, fs in got.items():
                    if i in by_id:
                        fs2 = [f for f in fs if fold(f).strip() not in rejected[i]]
                        done[i] = clean(by_id[i], [*done.get(i, []), *fs2])
        # verify every item that changed (all of them on the first round)
        ids = list(by_id) if _ == 0 else todo
        vchunks = [[by_id[i] for i in ids[k : k + CHUNK]] for k in range(0, len(ids), CHUNK)]
        with ThreadPoolExecutor(8) as ex:
            for bad in ex.map(lambda c: verify(client, c, done), vchunks):
                for i, b in bad.items():
                    if i in by_id and b:
                        rejected[i] |= b
                        done[i] = [f for f in done[i] if fold(f).strip() not in b]
        todo = [i for i in by_id if len(done.get(i, [])) < K_FOIL]
        print(
            f"[{family}] round {_}: {sum(len(r) for r in rejected.values())} rejected, "
            f"{len(todo)} short",
            file=sys.stderr,
        )
        if not todo:
            break
    if todo:
        print(
            f"[{family}] {len(todo)} items still short of {K_FOIL} foils: {todo[:5]}",
            file=sys.stderr,
        )
    return {i: done.get(i, []) for i in by_id}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--families", default=",".join(FAMILIES))
    a = ap.parse_args()
    client = anthropic.Anthropic()
    for fam in a.families.split(","):
        foils = draft(client, fam)
        out = REPO / "evals" / fam / "null_foils.json"
        doc = {
            "family": fam,
            "about": "Near-miss foils for the plan-0012 null (wsbench.nulls); LLM-drafted by "
            f"scripts/draft_null_foils.py ({MODEL}), mechanically filtered, hand spot-checked.",
            "items": foils,
        }
        out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        n_full = sum(len(v) == K_FOIL for v in foils.values())
        print(f"[{fam}] wrote {out} ({n_full}/{len(foils)} full)")


if __name__ == "__main__":
    main()
