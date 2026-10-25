"""Post-cutoff confabulation: Qwen gives a stable, specific, wrong answer to a question about an
event after its knowledge cutoff; does the lens name that answer at the token before the reply?"""

from pathlib import Path

from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, register

from . import judge
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="cutoff_confab",
        title="Post-cutoff confabulation",
        group="precision",
        bank=Path("evals/cutoff_confab/items.json"),
        # the instrument is the regex scorer; the JudgeConfig only carries its version
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        calls_per_arm="0 (regex)",
        sources="",
        scorer="regex",
    )
)
