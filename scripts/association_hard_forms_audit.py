"""association_hard, the scene-aware audit of the accepted forms of NEW golds (plan 0116 §2.4);
its output `v3/forms_audit_v3.json` is committed. It is a list of candidates for the builder's
`FORM_DROPS_V3` table, read by hand: nothing is dropped by this file alone.

    python scripts/association_hard_forms_audit.py --bank BANK --waves b4,b5 --work DIR --out FILE

The forms pass never sees a scene, so in bank v2 it named some golds in another sense of the word
(`un banco` as a bench) and listed forms that also fit a distractor (`Italian bagpipe` beside
`una piva`). Here Opus 5.5 reads each new item's scene, gold and OTHER options and marks every
accepted form that does not name the gold as the scene means it, or that could equally name
another option of the list.
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

SYSTEM = """You audit the accepted names of a benchmark answer. You get a short scene that \
implies one thing without naming it, the thing (the gold answer, in the scene's language), and \
a numbered list of names under which a reader's answer would be accepted. Mark a name WRONG \
when, read on its own, it would also be said of something that is NOT the gold as this scene \
means it: another sense of an ambiguous word (a bank that is a bench, a chimney that is a \
fireplace, "offbeat" meaning eccentric instead of out of time), an ordinary word or phrase for a \
different thing or activity, a broader or narrower thing, or a name that leaves out or changes a \
part of a compound gold (its qualifier, material or place), or a name that would equally be \
said of one of the OTHER OPTIONS listed with it (a generic name that covers the gold and a \
sibling, or the usual translation of another option). A faithful translation, synonym, \
spelling variant or rewording of the WHOLE gold in the scene's sense is RIGHT. Answer with one \
verdict per name, in order, and a few words of reason for each WRONG."""
USER = (
    "SCENE:\n{scene}\n\nGOLD: {gold}\n\nOTHER OPTIONS (wrong answers of this item):\n{others}"
    "\n\nACCEPTED NAMES:\n{listing}"
)
SCHEMA = schema_block(
    "forms_audit",
    {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"wrong": {"type": "boolean"}, "why": {"type": "string"}},
                "required": ["wrong", "why"],
                "additionalProperties": False,
            },
        }
    },
    ["verdicts"],
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", type=Path, required=True, help="a bank built WITHOUT this audit")
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--waves", required=True, help="audit only the items of these waves")
    a = ap.parse_args(argv)
    if a.out.exists():
        raise SystemExit(f"{a.out} exists; write to a fresh path")
    a.work.mkdir(parents=True, exist_ok=True)
    calls = Calls(a.work)
    waves = set(a.waves.split(","))
    bank = [
        it
        for it in json.loads(a.bank.read_text(encoding="utf-8"))["items"]
        if it["authoring"]["wave"] in waves
    ]
    reqs = []
    for it in bank:
        user = (
            USER.replace("{scene}", it["prompt"])
            .replace("{gold}", it["mc"]["gold"])
            .replace("{others}", "\n".join(f"- {d}" for d in it["mc"]["distractors"]))
            .replace("{listing}", mc.listing(it["mc"]["aliases"]))
        )
        reqs.append((f"audit|{it['name']}", SYSTEM, user))
    got = calls.run(reqs, SCHEMA, effort="default")
    out: dict[str, dict[str, str]] = {}
    for it in bank:
        forms = it["mc"]["aliases"]
        vs = list((got[f"audit|{it['name']}"] or {}).get("verdicts") or [])
        if len(vs) != len(forms):
            raise SystemExit(f"audit call failed or is malformed for {it['name']}; re-run")
        wrong = {f: str(v["why"]) for f, v in zip(forms, vs, strict=True) if v["wrong"]}
        if wrong:
            out[it["name"]] = wrong
    doc = {
        "version": 1,
        "built": BUILT,
        "model": MODEL,
        "what": "per new item, the accepted forms of the gold that a scene-aware audit marks as "
        "not naming the gold in the scene's sense or as fitting another option of its list, "
        "each with the reason: candidates for the builder's FORM_DROPS_V3, read by hand",
        "prompts": {"SYSTEM": SYSTEM, "USER": USER},
        "audited_items": [it["name"] for it in bank],
        "wrong": out,
    }
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(bank)} items audited, {sum(map(len, out.values()))} forms marked in {len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
