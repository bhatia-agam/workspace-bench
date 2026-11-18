"""Per-family judge configuration and the flag > env > family-pin override resolution."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from wsbench.llm import ANTHROPIC_REASONING_KEYS, OPENROUTER_MIN_REASONING, reasoning_for, route

DEFAULT_JUDGE = "claude-opus-5-5"  # plan 0023 (Camila 2026-10-29)
# OpenRouter judges with no reasoning of their own: one definition, in ``llm`` (plan 0096)
DEFAULT_REASONING = OPENROUTER_MIN_REASONING
__all__ = [
    "ANTHROPIC_REASONING_KEYS",
    "DEFAULT_JUDGE",
    "DEFAULT_REASONING",
    "ENV_OVERRIDE",
    "JUDGE_EFFORTS",
    "JudgeConfig",
    "ResolvedJudge",
    "resolve",
]
ENV_OVERRIDE = "WSBENCH_JUDGE_MODEL"
# ``judge_effort=`` (non-Claude judges only): replaces the reasoning resolve would give
JUDGE_EFFORTS = ("default", "minimal", "low", "medium", "high")


@dataclass(frozen=True)
class JudgeConfig:
    model: str = DEFAULT_JUDGE
    prompt_version: str = "v1"
    reasoning: dict | None = None  # route-keyed; see resolve()
    aux_models: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedJudge:
    model: str
    reasoning: dict | None
    pinned: bool  # True iff model == config.model (no override took effect)
    source: Literal["flag", "env", "family"]


def resolve(
    config: JudgeConfig,
    *,
    flag: str | None = None,
    env: Mapping[str, str] | None = None,
    effort: str | None = None,
) -> ResolvedJudge:
    """The judge of a family: model flag > env > family pin. ``effort`` (``judge_effort=``),
    when given, REPLACES the reasoning this would produce for a non-Claude judge (the family's
    keys and :data:`DEFAULT_REASONING` alike): ``default`` -> ``None``, else ``{"effort":
    effort}``, and the judge is no longer the pinned instrument. A ``claude-*`` judge with
    ``effort``, or an unknown level, exits 2. The ``openai`` route resolves like OpenRouter."""
    env = env or {}
    env_model = env.get(ENV_OVERRIDE, "")
    if flag:
        model, source = flag, "flag"
    elif env_model:
        model, source = env_model, "env"
    else:
        model, source = config.model, "family"
    # a family's reasoning keys are route-specific: `anthropic_effort` rides the Anthropic route,
    # every other key the OpenRouter one; keys for the other route are dropped, so an Opus judge
    # of a family with an OpenRouter-only setting resolves to None (plan 0023; the rule lives in
    # ``llm.reasoning_for``)
    route_ = route(model)
    reasoning = reasoning_for(route_, config.reasoning)
    pinned = model == config.model
    if effort is not None:
        from wsbench.family import fail  # wsbench.family imports this module

        if effort not in JUDGE_EFFORTS:
            fail(f"judge_effort={effort!r}: expected one of {', '.join(JUDGE_EFFORTS)}")
        if route_ == "anthropic":
            fail(f"judge_effort={effort!r} is for non-Claude judges; {model} is a claude-* judge")
        reasoning = None if effort == "default" else {"effort": effort}
        pinned = False
    return ResolvedJudge(model=model, reasoning=reasoning, pinned=pinned, source=source)
