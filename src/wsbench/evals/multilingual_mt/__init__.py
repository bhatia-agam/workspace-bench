"""Multilingual (multi-token): the concept in English or the model's native language AND the
language's name (the raw-sample language leg), regex contract on the v2 bank."""

from pathlib import Path

from wsbench.multitoken.family import mt_family
from wsbench.multitoken.prompts import DIGEST_TASK_NOTES, V2_MT_TAG
from wsbench.registry import register

SPEC = register(
    mt_family(
        "multilingual_mt",
        "Multilingual (multi-token)",
        calls_per_arm="≈ 2.2k",
        scorer="regex",
        bank=Path("evals/multilingual_mt/items_v4.json"),
        # "v2+ln-…+langleg-v1+bank-v4": the naming forms, the language leg, bank v4
        instrument_tag=V2_MT_TAG,
        min_full_positions=16,
        full_contiguous=True,
        task_note=DIGEST_TASK_NOTES["multilingual_mt"],
        flat_types=(),
    )
)
