"""Multilingual multihop: the bridge in the prompt's language AND in English or the model's native
language AND the language's name; MC with distractors, then regex (plan 0054, scorer mc+regex)."""

from pathlib import Path

from wsbench.multitoken.family import mt_family
from wsbench.multitoken.prompts import (
    DIGEST_TASK_NOTES,
    MCRX_VERSION,
    ML_BANK_TAGS,
    ML_MC_PROMPT_VERSION,
)
from wsbench.registry import register

SPEC = register(
    mt_family(
        "multilingual_multihop",
        "Multilingual multihop",
        calls_per_arm="≈ 0.4k",
        scorer="mc+regex",
        # bank v5 = v4 with the leaking bridge lists rebuilt and 9 items dropped (its header's
        # read_plan_bank keeps v4's read plan, so v4 readouts serve it)
        bank=Path("evals/multilingual_multihop/items_v5.json"),
        prompt_version=MCRX_VERSION,
        instrument_tag=f"{ML_MC_PROMPT_VERSION}+{ML_BANK_TAGS['multilingual_multihop']}",
        min_full_positions=12,
        full_contiguous=True,
        task_note=DIGEST_TASK_NOTES["multilingual_multihop"],
        flat_types=(),
        v1_scorer="regex",  # a v1-shaped (adapted) bank: the regex contract, as before v2
    )
)
