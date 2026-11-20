"""Build a hinted_cutoff bank from a global-workspace frozen ccut set (plans 0063, 0074).

    python scripts/build_hinted_cutoff_bank.py --frozen <gw>/evals/chint_cutoff/frozen_v2.json \
        --scores <gw>/evals/chint_cutoff/frozen_v2_scores.json [--gw-commit <sha>] \
        --out evals/model_specific/hinted_cutoff/items_v2.json

(v1: ``--frozen <gw>/evals/chint_cutoff/frozen_v1.json --out
evals/model_specific/hinted_cutoff/items.json``.)

A pure transform (no tokenizer, no GPU). Plan 0064: every reader sees the PROMPT only, so items
ship the prompt ids (``input_ids[:n_prompt]``), no reply text and no reply span; the read
positions are the frozen gw prompt span (the user-turn tokens, length-equalized within each
pair)."""

import argparse
import hashlib
import json
from pathlib import Path

OUT = Path("evals/model_specific/hinted_cutoff/items_v2.json")
# plan 0074: the gw reader results a v2 header carries (frozen_v2_scores.json keys)
READER_KEYS = (
    "prompttext", "predict_single", "predict_normal", "logit", "olens_v2", "mlnla", "jlens",
    "yesno_logit", "yesno_olens", "yesno_mlnla", "yesno_jlens",
    "olens_v2@rand1", "mlnla@rand1", "jlens@rand1",
    "yesno_olens@rand1", "yesno_mlnla@rand1", "yesno_jlens@rand1",
)  # fmt: skip
ADAPTED_DATE_TOL = 0.10  # gw ccut.V2_GATE_TOL
GATE_KEYS = ("n_pairs", "day_auroc", "obscurity_auroc", "expected_auroc", "prior_fame_auroc",
             "share_I_later", "cell_excess", "pass")  # fmt: skip
KEEP = (
    "qid",
    "template",
    "event_date",
    "question",
    "hint_answer",
    "n_prompt",
    "question_token_coverage",
)


def _adapted_header(frozen: dict, items: list, sha: str, gw_commit: str, adapt: dict) -> dict:
    """Plan 0084: an adapted set's header. The subject's own gate and prompt-only results; none of
    Qwen's reader results (the registered bank's ``reference_results_readers``) are carried."""
    assert {it["template"] for it in items} == {"metadata"}, "adapted bank: metadata pairs only"
    assert frozen.get("subject") == adapt["hf_id"], (frozen.get("subject"), adapt["hf_id"])
    assert gw_commit, "an adapted bank records the gw commit its pipeline ran at"
    m, leak = frozen["metric"], frozen["date_leak"]
    return {
        "family": "hinted_cutoff",
        "version": 2,
        "frozen": True,
        "source": "global-workspace ccut v2 pipeline (PRs #747, #751, #753) re-run on the "
        "subject (plan 0084); gw-format frozen file",
        "source_sha256": sha,
        "source_commit": gw_commit,
        "subject": adapt["hf_id"],
        "n_pairs": len(frozen["pairs"]),
        "n_items": len(items),
        "metric": m["definition"],
        "flag": m["flag"],
        "read_span": "prompt",
        # plan 0084 R19: date-matched = the date checks (day AUROC, cell excess within the gw v2
        # tolerance); the gate's rating AUROCs stay in ``date_leak`` as measurements
        "date_matched": bool(
            abs(leak["final"]["day_auroc"] - 0.5) <= ADAPTED_DATE_TOL
            and leak["final"]["cell_excess"] <= ADAPTED_DATE_TOL
        ),
        # every gate rating's AUROC (plan 0084 R18 adds the guessability caliper's)
        "date_leak": {
            **{k: leak["final"][k] for k in GATE_KEYS},
            **{k: v for k, v in leak["final"].items() if k.endswith("_auroc")},
        },
        "gw_judge_prompts_sha256": m["judge_prompts_sha256"],
        "reference_results": frozen["reference_results"],
        "prompt_only_baseline": frozen["prompt_only_baseline"],
        "funnel": frozen.get("funnel"),
        "adapt": adapt,
    }


def build(
    frozen: dict,
    sha: str,
    gw_commit: str,
    scores: dict | None = None,
    scores_sha: str = "",
    adapt: dict | None = None,
) -> dict:
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
    if adapt is not None:  # plan 0084: the gw ccut v2 pipeline re-run on an adapt subject
        return {
            **_adapted_header(frozen, items, sha, gw_commit, adapt),
            "items": items,
        }
    if frozen.get("version") != "v2":  # v1: the original header, byte for byte
        return {
            **{
                "family": "hinted_cutoff",
                "frozen": True,
                "source": "global-workspace ccut series (#719-#727), "
                "evals/chint_cutoff/frozen_v1.json",
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
    # plan 0074: v2 = the date-matched set, metadata pairs only; the strict O-lens reference and
    # every reader's prompt-span result come from the gw scores file
    assert scores is not None, "a v2 frozen set needs --scores (frozen_v2_scores.json)"
    assert {it["template"] for it in items} == {"metadata"}, "v2 bank: metadata pairs only"
    readers = {k: scores[k]["prompt|hint_reliance"] for k in READER_KEYS}
    assert all(r["n_pairs"] <= len(frozen["pairs"]) for r in readers.values())
    leak = frozen["date_leak"]
    return {
        **{
            "family": "hinted_cutoff",
            "version": 2,
            "frozen": True,
            "source": "global-workspace ccut v2 (PRs #747, #751, #753), "
            "evals/chint_cutoff/frozen_v2.json",
            "source_sha256": sha,
            "source_commit": gw_commit,
            "source_scores": "evals/chint_cutoff/frozen_v2_scores.json",
            "source_scores_sha256": scores_sha,
            "subject": "Qwen/Qwen3.6-27B",
            "n_pairs": len(frozen["pairs"]),
            "n_items": len(items),
            "metric": m["definition"],
            "flag": m["flag"],
            "read_span": "prompt",
            "reference_result_prompt_span": readers["olens_v2"],
            "reference_results_readers": readers,
            "date_matched": frozen["date_matched"],
            "date_leak": {k: leak["final"][k] for k in GATE_KEYS},
            "subset_of": frozen["subset_of"],
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
    ap.add_argument("--scores", default="", help="gw frozen_v2_scores.json (v2 only)")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    raw = Path(a.frozen).read_bytes()
    sraw = Path(a.scores).read_bytes() if a.scores else b""
    out = build(
        json.loads(raw),
        hashlib.sha256(raw).hexdigest(),
        a.gw_commit,
        json.loads(sraw) if sraw else None,
        hashlib.sha256(sraw).hexdigest() if sraw else "",
    )
    dest = Path(a.out)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{dest}: {out['n_items']} items, {out['n_pairs']} pairs")


if __name__ == "__main__":
    main()
