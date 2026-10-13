"""Steer the next wave: diversity of a bank (`mix`) and why a gated wave failed (`fails`).

    # template / relation mix, repeated latents and shared entities of a (gated) bank
    uv run python .claude/skills/wsb-new-questions/scripts/wave_report.py mix \\
        --family multihop --bank gated/multihop/items.json [--cap 0.2]
    # failure pattern per item of a gate_hf.py wave (reads <dir>/gate.json)
    uv run python .claude/skills/wsb-new-questions/scripts/wave_report.py fails \\
        --family multihop --gated gated/multihop

`mix` exits 1 when one template, relation or latent exceeds --cap of the bank (default 20%):
small banks gated on weak models collapse to a few easy templates, and a lens score over
"capital -> language" x 40 is not a multihop score. `fails` prints a count per pattern and the
item ids, to be read against the decision table in references/weak-model.md.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_bank import fold, item_key, load_any, prompt_text

# item fields that already name a template / stratum in some families
TYPE_FIELDS = (
    "relation",
    "subfamily",
    "variant",
    "stratum",
    "tier",
    "domain",
    "kind",
    "category",
    "failure_mode",
)
# the scored latent per family where it is not intermediates/bridge/target; "" = no latent cap
# (moral repeats each topic in two formats by design; buggy's latent is per-program)
LATENT_FIELD = {"role_bound_association": "action", "moral_rationale": "", "buggy_code": ""}
ENTITY = re.compile(r"(?<![.!?:]\s)(?<!^)\b[A-Z][\w'-]+(?:\s+(?:of|the|de|von|[A-Z][\w'-]+))*")
SKELETON_WORDS = 8


def skeleton(text: str) -> str:
    """Template key: the first words of the prompt with names and numbers masked."""
    t = ENTITY.sub(" NAME ", re.sub(r"\d[\d,.]*", " NUM ", text))
    words = [w if w in ("NAME", "NUM") else w.lower() for w in re.findall(r"[A-Za-z']+", t)]
    return " ".join(words[:SKELETON_WORDS])


def latent(family: str, it: dict[str, Any]) -> str:
    if family in LATENT_FIELD:
        f = LATENT_FIELD[family]
        return fold(str(it.get(f, ""))) if f else ""
    for k in ("intermediates", "bridge"):
        v = it.get(k)
        if isinstance(v, list) and v:
            return fold(str(v[0]))
        if isinstance(v, str) and v:
            return fold(v)
    return fold(str(it.get("target") or it.get("gold_label") or it.get("key") or ""))


def cmd_mix(family: str, bank: Path, cap: float) -> int:
    _h, items, _l = load_any(bank)
    n = len(items)
    if not n:
        print("empty bank")
        return 1
    bad = False

    def show(title: str, c: Counter, limit: int = 8, check: bool = True) -> None:
        nonlocal bad
        top = c.most_common(limit)
        share = top[0][1] / n if top else 0.0
        flag = check and share > cap and n >= 5
        bad |= flag
        over = " OVER CAP" if flag else ""
        print(f"{title}: {len(c)} distinct over {n} items; largest {share:.0%}{over}")
        for k, v in top:
            print(f"   {v:3d}  {k}")

    for f in TYPE_FIELDS:  # informational: a 2-valued field can never be under a 20% cap
        vals = [str(it[f]) for it in items if f in it]
        if len(vals) == n:
            show(f"field {f!r} (not capped)", Counter(vals), check=False)
    texts = [prompt_text(family, it) for it in items]
    show("prompt template (first words, names/numbers masked)", Counter(map(skeleton, texts)))
    lat = Counter(latent(family, it) for it in items)
    if any(lat):
        show("scored latent", lat, check=True)
    ents: dict[str, set[str]] = defaultdict(set)
    for it, t in zip(items, texts, strict=True):
        for m in ENTITY.findall(t):
            ents[m].add(item_key(it))
    shared = sorted(((len(v), k) for k, v in ents.items() if len(v) > 1), reverse=True)
    print(f"entities named in >1 prompt: {len(shared)}")
    for c, k in shared[:8]:
        print(f"   {c:3d}  {k}")
    print("MIX " + ("FAIL (diversify the next wave; see weak-model.md)" if bad else "OK"))
    return 1 if bad else 0


def pattern(fam: str, legs: list[dict[str, Any]]) -> str:
    """One failure pattern per item (first that applies)."""
    main = next((q for q in legs if ":bridge" not in q["qid"]), legs[0])
    bridges = [q for q in legs if ":bridge" in q["qid"]]
    if all(q.get("pass") for q in legs):
        return "pass"
    if any(q.get("leaks") for q in legs):
        return "cot_leak (wrote the intermediate)"
    if main.get("truncated_greedy"):
        return "truncated (no stop token within max_new)"
    if main["mode"] == "own_poetry":
        if not main.get("word"):
            return "poetry: no first word"
        if not main.get("rhymes"):
            return "poetry: greedy word does not rhyme"
        return "poetry: rhymes but unstable (< need samples agree)"
    if main["mode"] == "mc":
        from gate_hf import mc_letter

        if not mc_letter(main.get("greedy", "")):
            return "mc: no parsable letter"
        return "mc: wrong or unstable letter"
    if bridges and all(q.get("pass") for q in bridges) and not main.get("pass"):
        return "bridges known, composition fails"
    if bridges and main.get("pass"):
        return "surface right, a bridge leg fails"
    if not main.get("greedy_ok"):
        return "greedy wrong"
    return "greedy right, samples inconsistent"


def cmd_fails(fam: str, gated: Path) -> int:
    qs = json.loads((gated / "gate.json").read_text(encoding="utf-8"))
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in qs:
        by_item[q["item"]].append(q)
    pats: dict[str, list[str]] = defaultdict(list)
    for k, legs in by_item.items():
        pats[pattern(fam, legs)].append(k)
    n = len(by_item)
    for p, ks in sorted(pats.items(), key=lambda kv: -len(kv[1])):
        more = " ..." if len(ks) > 4 else ""
        print(f"{len(ks):4d} ({len(ks) / n:5.1%})  {p}: {', '.join(ks[:4])}{more}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mix")
    m.add_argument("--family", required=True)
    m.add_argument("--bank", required=True, type=Path)
    m.add_argument("--cap", type=float, default=0.2)
    f = sub.add_parser("fails")
    f.add_argument("--family", required=True)
    f.add_argument("--gated", required=True, type=Path)
    a = ap.parse_args()
    if a.cmd == "mix":
        return cmd_mix(a.family, a.bank, a.cap)
    return cmd_fails(a.family, a.gated)


if __name__ == "__main__":
    sys.exit(main())
