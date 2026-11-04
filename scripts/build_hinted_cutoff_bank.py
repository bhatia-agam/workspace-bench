"""Build evals/hinted_cutoff/items.json from global-workspace's frozen_v1.json (plan 0063).

    python scripts/build_hinted_cutoff_bank.py --frozen <gw>/evals/chint_cutoff/frozen_v1.json \
        [--gw-commit <sha>]

A pure transform (no tokenizer, no GPU). Plan 0064: every reader sees the PROMPT only, so items
ship the prompt ids (``input_ids[:n_prompt]``), no reply text and no reply span; the read
positions are the frozen gw prompt span (the user-turn tokens, length-equalized within each
pair)."""

import argparse
import hashlib
import json
from pathlib import Path

OUT = Path("evals/hinted_cutoff/items.json")
KEEP = (
    "qid",
    "template",
    "event_date",
    "question",
    "hint_answer",
    "n_prompt",
    "question_token_coverage",
)


def build(frozen: dict, sha: str, gw_commit: str) -> dict:
    items = []
    cluster = {p["I"]: p["cluster"] for p in frozen["pairs"]}
    cluster |= {p["N"]: p["cluster"] for p in frozen["pairs"]}
    pair_of = {p["I"]: p["pair_id"] for p in frozen["pairs"]}
    pair_of |= {p["N"]: p["pair_id"] for p in frozen["pairs"]}
    for key in sorted(frozen["items"]):
        it = frozen["items"][key]
        n = it["n_prompt"]
        pos = [int(x) for x in it["spans"]["prompt"]]
        assert pos and max(pos) < n <= len(it["input_ids"]), key  # prompt positions only
        assert pos == sorted(set(pos)), key
        row = {
            "name": it["read_label"],
            "item_key": key,
            "pair_id": pair_of[key],
            "role": it["role"],
            "cluster": cluster[key],
            "text": it["user_prompt"],
            **{k: it[k] for k in KEEP},
            "input_ids": it["input_ids"][:n],
            "spans": {s: it["spans"][s] for s in ("prompt", "question")},
            "positions": pos,
        }
        items.append(row)
    ids = [r["name"] for r in items]
    assert len(ids) == len(set(ids)) == 2 * len(frozen["pairs"])
    for p in frozen["pairs"]:
        a = next(r for r in items if r["item_key"] == p["I"])
        b = next(r for r in items if r["item_key"] == p["N"])
        assert (a["role"], b["role"]) == ("I", "N") and len(a["positions"]) == len(b["positions"])
    for r in items:
        assert "reply" not in r and "reply" not in r["spans"], r["name"]
        assert len(r["input_ids"]) == r["n_prompt"] and max(r["positions"]) < r["n_prompt"]
    m = frozen["metric"]
    return {
        **{
            "family": "hinted_cutoff",
            "frozen": True,
            "source": "global-workspace ccut series (#719-#727), evals/chint_cutoff/frozen_v1.json",
            "source_sha256": sha,
            "source_commit": gw_commit,
            "subject": "Qwen/Qwen3.6-27B",
            "n_pairs": len(frozen["pairs"]),
            "n_items": len(items),
            "metric": m["definition"],
            "flag": m["flag"],
            "read_span": "prompt",
            "reference_result_prompt_span": frozen["reference_results"]["olens"][
                "prompt|hint_reliance"
            ],
            "gw_judge_prompts_sha256": m["judge_prompts_sha256"],
            "reference_results": frozen["reference_results"],
            "prompt_only_baseline": frozen["prompt_only_baseline"],
        },
        "items": items,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frozen", required=True)
    ap.add_argument("--gw-commit", default="")
    a = ap.parse_args()
    raw = Path(a.frozen).read_bytes()
    out = build(json.loads(raw), hashlib.sha256(raw).hexdigest(), a.gw_commit)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT}: {out['n_items']} items, {out['n_pairs']} pairs")


if __name__ == "__main__":
    main()
