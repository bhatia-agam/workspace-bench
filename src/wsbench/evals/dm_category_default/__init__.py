"""Category default: the model is told to think about its favourite member of a category while
copying an unrelated sentence; does the lens name the model's own answer at the writing
positions."""

from pathlib import Path

from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, register

from . import judge
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="dm_category_default",
        title="Category default",
        group="association",
        bank=Path("evals/dm_category_default/items.json"),
        # the instrument is the regex scorer; no judge model is ever called
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        calls_per_arm="0 (regex)",
        sources="",
        scorer=judge.SCORER,
        not_in_macro="hillclimbing: not yet reviewed",
    )
)
