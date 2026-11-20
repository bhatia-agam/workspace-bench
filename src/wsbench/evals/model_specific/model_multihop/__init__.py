"""Model-specific multihop (plan 0076): one question whose hidden bridge only Qwen3.6-27B believes
(an invented entity's country, or a stale "current" holder); does a lens name Qwen's bridge?"""

from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, family_rel, register

from . import judge
from .prompts import PROMPT_VERSION, TASK_NOTE

SPEC = register(
    EvalSpec(
        name="model_multihop",
        title="Model-specific multihop",
        group="model_specific",
        bank=family_rel("model_multihop") / "items.json",
        # gw ran Opus 5.5 at its default effort (both stages); a refused call retries on Sonnet
        judge=JudgeConfig(
            prompt_version=PROMPT_VERSION,
            reasoning={"anthropic_effort": "default"},
            aux_models={judge.FALLBACK_ROLE: "claude-sonnet-5-5"},
        ),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        calls_per_arm=(
            "summary: 283 items x read layers per-layer digests + 283 MC calls; native: "
            "283 x (layers + 1) summarizer + concept-judge call pairs"
        ),
        sources="",
        # the post-entity span: 27-37 contiguous prompt tokens, the shortest 27
        min_full_positions=16,
        full_contiguous=True,
        task_note=TASK_NOTE,
        item_task_notes=judge.item_task_notes,
    )
)
