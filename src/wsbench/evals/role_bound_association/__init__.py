"""Role-bound association: does the lens bind the direction of a scene's relation."""

from pathlib import Path

from wsbench.evals.role_bound_association import prompts as _prompts
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, register

from . import judge
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="role_bound_association",
        title="Role-bound association",
        group="association",
        # bank v2 = items.json without the 4 pairs whose stories carry a stray tab (92 items);
        # its header's read_plan_bank keeps items.json's read plan, so those readouts serve it
        bank=Path("evals/role_bound_association/items_v2.json"),
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        task_note=_prompts.DIGEST_TASK_NOTE,
        # the 19 suffix + chat-tail positions: one contiguous run ending at the final token
        min_full_positions=19,
        full_contiguous=True,
        flat_types=_prompts.FLAT_TYPES,
        multi_select=_prompts.MULTI_SELECT,
        not_in_macro="",
        calls_per_arm="≈ 370 (summary: 92 digests + 3 draws x 92 judge calls); ≈ 19.2k native",
        sources="",
    )
)
