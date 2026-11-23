"""Association (hard): a scene implies an uncommon thing, or an ordinary thing in an unusual
state, material or place, without naming it; does the lens state the WHOLE concept at the
summarize-request positions? One 8-way MC + cannot tell in three draws, majority."""

from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, family_rel, register

from . import judge, prompts
from .prompts import PROMPT_VERSION

SPEC = register(
    EvalSpec(
        name="association_hard",
        title="Association (hard)",
        group="association",
        bank=family_rel("association_hard") / "items.json",
        judge=JudgeConfig(prompt_version=PROMPT_VERSION),
        metric="pass_rate",
        higher_is_better=True,
        run=judge.run,
        task_note=prompts.DIGEST_TASK_NOTE,
        # the 19 suffix + chat-tail positions, one contiguous run ending at the final token
        min_full_positions=19,
        full_contiguous=True,
        calls_per_arm="≈ 0.2k MC (3 draws) + up to 0.2k quote re-judges summary; native ≈ 0.8k x k",
    )
)
