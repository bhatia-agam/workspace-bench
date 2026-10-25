"""Multihop (multi-token): a multi-token basic family on the forced-choice judge."""

from wsbench.multitoken.family import mt_family
from wsbench.registry import register

# superseded by the shortcut-gated multihop_mt_v2 (plans 0013, 0015): frozen, runnable by name,
# out of every "all" default and of the macro
SPEC = register(
    mt_family(
        "multihop_mt",
        "Multihop (multi-token)",
        calls_per_arm="≈ 1.5k",
        superseded_by="multihop_mt_v2",
    )
)
