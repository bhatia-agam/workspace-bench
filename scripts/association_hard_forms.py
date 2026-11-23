"""association_hard, the one-off forms pass (plan 0108 §2.4); its output `forms_v1.json` is
committed and is an input of `scripts/build_association_hard_bank.py`.

    python scripts/association_hard_forms.py --src bank_final_B.json --grid grid_v1.json \\
        --work DIR --out forms_v1.json

For EVERY option of every kept item, gold and distractor alike and without saying which is
which, Opus 5.5 lists the standard English and Chinese names of the concept; a second call
audits each name as "the same concept". It never sees a scene or a readout.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from association_hard_grid import BUILT, MODEL, Calls  # noqa: E402

from wsbench import mc  # noqa: E402
from wsbench.llm import schema_block  # noqa: E402

MAX_PER_LANGUAGE = 3

NAMES_SYSTEM = """You get a noun phrase in some language. It names one thing, sometimes with a \
qualifier, a material it is made of, or a place it is in. List the standard names of exactly \
that concept in English and in Chinese: the ordinary names a fluent writer would use for it, \
the whole concept with every part, at most three per language. No descriptions or definitions, \
no broader or narrower terms, no related things. Give noun phrases without a leading article."""
NAMES_USER = "Phrase: {option}"
NAMES_SCHEMA = schema_block(
    "names",
    {
        "english": {"type": "array", "items": {"type": "string"}},
        "chinese": {"type": "array", "items": {"type": "string"}},
    },
    ["english", "chinese"],
)
AUDIT_SYSTEM = """You check names. You get a noun phrase and a numbered list of candidate names \
in English or Chinese. For each candidate say whether it names the SAME concept as the phrase: \
the same thing with every qualifier, material or place the phrase gives, no broader, narrower or \
merely related concept, and not a word whose ordinary meaning is something else. Answer with \
one boolean per candidate, in order."""
AUDIT_USER = "Phrase: {option}\nCandidates:\n{listing}"
AUDIT_SCHEMA = schema_block(
    "audit", {"same": {"type": "array", "items": {"type": "boolean"}}}, ["same"]
)


def kept_options(src: Path, grid_p: Path) -> list[str]:
    """Every option of every kept item, each once, in bank order."""
    from build_association_hard_bank import DROP

    grid = json.loads(grid_p.read_text(encoding="utf-8"))
    drop = {**DROP, **grid["dropped"]}
    out: list[str] = []
    for it in json.loads(src.read_text(encoding="utf-8"))["items"]:
        if it["name"] in drop:
            continue
        ds = list(it["mc"]["distractors"])
        ch = grid["items"].get(it["name"]) or grid["swaps"].get(it["name"])
        if ch:
            ds = [d for d in ds if d != ch["replaced"]] + [ch["new"]]
        out += [it["mc"]["gold"], *ds]
    return list(dict.fromkeys(out))


def usable(name: str) -> bool:
    """A single CJK character is never listed: CJK forms match as substrings, so it would be
    found inside other words (刀 in 剪刀)."""
    n = name.strip()
    return bool(n) and not (mc.is_cjk(n) and len(n) < 2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--grid", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; write to a fresh path")
    a.work.mkdir(parents=True, exist_ok=True)
    calls = Calls(a.work)
    options = kept_options(a.src, a.grid)
    named = calls.run(
        [(f"names|{o}", NAMES_SYSTEM, NAMES_USER.replace("{option}", o)) for o in options],
        NAMES_SCHEMA,
    )
    proposed: dict[str, list[str]] = {}
    for o in options:
        r = named[f"names|{o}"]
        if r is None:
            raise SystemExit(f"names call failed for {o!r}; re-run")
        cands = [
            str(x).strip()
            for lang in ("english", "chinese")
            for x in list(r.get(lang) or [])[:MAX_PER_LANGUAGE]
        ]
        proposed[o] = list(dict.fromkeys(c for c in cands if usable(c)))
    reqs = [
        (
            f"audit|{o}",
            AUDIT_SYSTEM,
            AUDIT_USER.replace("{option}", o).replace("{listing}", mc.listing(proposed[o])),
        )
        for o in options
        if proposed[o]
    ]
    audited = calls.run(reqs, AUDIT_SCHEMA)
    out: dict[str, dict[str, list[str]]] = {}
    for o in options:
        same = list((audited.get(f"audit|{o}") or {}).get("same") or [])
        if proposed[o] and len(same) != len(proposed[o]):
            raise SystemExit(f"audit call failed or is malformed for {o!r}; re-run")
        out[o] = {
            "names": [c for c, ok in zip(proposed[o], same, strict=True) if ok],
            "rejected": [c for c, ok in zip(proposed[o], same, strict=True) if not ok],
        }
    doc = {
        "version": 1,
        "built": BUILT,
        "model": MODEL,
        "what": "per option of the bank (gold and distractors alike, the proposer never told "
        "which is which and never shown a scene or a readout): the standard English and Chinese "
        "names that a second call audited as the same concept (`names`), and the proposed names "
        "the audit refused (`rejected`); a single CJK character is never proposed",
        "prompts": {
            "NAMES_SYSTEM": NAMES_SYSTEM,
            "NAMES_USER": NAMES_USER,
            "AUDIT_SYSTEM": AUDIT_SYSTEM,
            "AUDIT_USER": AUDIT_USER,
        },
        "options": out,
    }
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(v["names"]) for v in out.values())
    refused = sum(len(v["rejected"]) for v in out.values())
    print(f"{len(out)} options, {n} names kept, {refused} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
