"""Precision tiers ``tier=lite|standard|max`` (plan 0014): which judge and which read regime a
run pays for. The table and the ranking evidence are in README §Judges."""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, get_args

from wsbench.judge_config import DEFAULT_JUDGE, JudgeConfig

Tier = Literal["lite", "standard", "max"]
TIERS: tuple[str, ...] = get_args(Tier)
DEFAULT_TIER: Tier = "standard"
MAX_JUDGE = "claude-opus-5-5"
S_LITE = 8  # agentic Stage A stride under lite (plan 0014 §6; may change after validation)
_PINS = frozenset({"jailbreak_recognition", "agentic_misalignment"})


@dataclass(frozen=True)
class TierSpec:
    default_model: str
    keep_pins: frozenset[str]  # families whose JudgeConfig.model survives the tier
    family_opts: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


TABLE: dict[str, TierSpec] = {
    "lite": TierSpec(
        DEFAULT_JUDGE,
        _PINS,
        {
            "jailbreak_recognition": {"read": "lite"},
            "agentic_misalignment": {"stride": str(S_LITE)},
        },
    ),
    "standard": TierSpec(DEFAULT_JUDGE, _PINS),
    # Opus 5.5 refuses agentic Stage B (Camila 2026-10-21), so agentic keeps Sonnet 5
    "max": TierSpec(MAX_JUDGE, frozenset({"agentic_misalignment"})),
}


def check(tier: str) -> str:
    """``tier`` if it is a known tier, else ValueError (a usage error at the CLI)."""
    if tier not in TABLE:
        raise ValueError(f"tier must be one of {', '.join(TIERS)}, got {tier!r}")
    return tier


def tier_config(config: JudgeConfig, family: str, tier: str) -> JudgeConfig:
    """The family's instrument under ``tier``. Identity for lite and standard (the registry's
    configs and pins are those tiers' instruments, so any pin survives); under max, ``model``
    and every non-empty ``aux_models`` value move to Opus 5.5 unless the family keeps its pin.
    ``reasoning`` is left as the family set it."""
    t = TABLE[check(tier)]
    if t.default_model == DEFAULT_JUDGE or family in t.keep_pins:
        return config
    aux = {k: t.default_model if v else v for k, v in config.aux_models.items()}
    return dataclasses.replace(config, model=t.default_model, aux_models=aux)


def family_opts(family: str, tier: str) -> dict[str, str]:
    """The tier's ``opts=`` defaults for ``family`` (the user's ``opts=`` wins over these)."""
    return dict(TABLE[check(tier)].family_opts.get(family, {}))


def tier_read(tier: str) -> str:
    """jailbreak_recognition's read regime of record under ``tier``."""
    return family_opts("jailbreak_recognition", tier).get("read", "span")


def tier_stride(tier: str) -> int:
    """agentic_misalignment's Stage A stride of record under ``tier``."""
    return int(family_opts("agentic_misalignment", tier).get("stride", "1"))
