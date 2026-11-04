"""User modelling: does the lens, read at every token of the chat render (system turn, user turn,
template tail), encode the user attribute Qwen inferred — named for the USER, not as a topic?"""

from pathlib import Path

from wsbench.evals.user_modeling import prompts as _prompts
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, register

from . import judge
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="user_modeling",
        title="User modelling",
        group="association",
        # bank v3 = items.json's 47 selfdescribe items (the 53 synthsys items dropped) + 79 new
        # gated selfdescribe items (126), read with its own plan (the 47 kept rows equal
        # items.json's). items.json stays frozen and judgeable with WSB_BANK_FILE_USER_MODELING
        bank=Path("evals/user_modeling/items_v3.json"),
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        task_note=_prompts.UM_TASK_NOTE,
        # a reads=full file holds, per (item, layer), one contiguous run ending at the final
        # token of at least the bank's shortest render (37 tokens; plan positions = every token)
        min_full_positions=37,
        full_contiguous=True,
        flat_types=_prompts.FLAT_TYPES,
        multi_select=_prompts.MULTI_SELECT,
        calls_per_arm="≈ 93k x k native; 126 summary",
        sources="Choi et al. 2025",
    )
)
