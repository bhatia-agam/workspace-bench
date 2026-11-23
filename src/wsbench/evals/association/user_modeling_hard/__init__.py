"""User modelling (hard): a chat implies one to three things about its user (who they are, how
they feel, what they know or want) without stating any; does the lens state EACH of them about
the user, at any token of the chat render? One identification MC per trait; all must pass."""

from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, family_rel, register

from . import judge, prompts
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="user_modeling_hard",
        title="User modelling (hard)",
        group="association",
        bank=family_rel("user_modeling_hard") / "items.json",
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        task_note=prompts.UMH_TASK_NOTE,
        # a reads=full file holds, per (item, layer), one contiguous run ending at the final
        # token of at least the bank's shortest render (the header's `min_render_tokens`; plan
        # positions = every token)
        min_full_positions=85,
        full_contiguous=True,
        flat_types=prompts.FLAT_TYPES,
        multi_select=prompts.MULTI_SELECT,
        calls_per_arm="≈ 0.5k MC + up to 0.6k quote checks and re-asks summary; native ≈ 0.2M x k",
        sources="Choi et al. 2025",
    )
)
