# 0069: drop the math_shortcuts family

Issue #347. Decision: Camila, 2026-11-05: "we are officially dropping the math-shortcuts eval,
remove it from the repo".

## What changes

`math_shortcuts` (plan 0065, PR #271, merge 689e8d79) leaves the bench. The registered family set
goes back to the pre-#271 set: the 27 core families + `nyt_connections` + `hinted_cutoff` (the
macro family count drops by one; `readplan.families()` 33 → 32).

Implemented as a revert of #271's code, data, tests and docs, merged onto current main:

- source: `src/wsbench/evals/math_shortcuts/` (judge, prompts, score, registration), the
  `readplan.py` branch, `results.NO_SHARED_BRACKET` (back to `{"hinted_cutoff"}`), the viewer
  group, the `digest.py` summary overrides, `capable/questions.py` NOT_GATED reason,
  `baselines/text_inversion.py` not-gated reason, `adapt/judge_inputs.py` entry,
  `scripts/summary_mode_compare.py` special-case;
- data: `evals/math_shortcuts/` (bank + README), `examples/readouts/math_shortcuts.jsonl`;
- scripts: `scripts/build_math_shortcuts_bank.py`, `scripts/math_shortcuts_replay.py`;
- baselines: the `math_shortcuts` entry of `evals/baselines/prompt_only_summary.json` and of
  `anti_text_inversion.json`'s not-gated map (every other floor byte-identical; the file is
  re-dumped with its own `indent=1` format);
- docs: README (model-specific family list: seven → six), CLAUDE.md (own-judge count thirteen →
  twelve, the math_shortcuts bullet), AGENTS.md (re-gate table row and list), NOTICE.md (Omni-MATH attribution: no Omni-MATH text remains),
  `docs/adapt_judge_inputs.md`;
- tests: `tests/test_math_shortcuts.py` removed; `tests/test_readplan.py` family count 33 → 32
  with the history comment extended (`+ math_shortcuts (0065), - math_shortcuts (dropped
  2026-11-05)`). That test change is sanctioned here: it follows directly from removing one
  registered family, and no other test assertion changes.
- adapted sets: no set has a math_shortcuts bank or result; the nine `report.json` files that
  carry the auto-written `"absent"` row for it lose that row (no other byte changes).

## Kept

- `plans/0065-math-shortcuts.md` stays as history with a "dropped" note at its top; its row in
  `plans/README.md` is marked dropped. `plans/0066` keeps its historical mention.
- Off-repo outputs (box-local lens runs and the fair-rating study) are untouched.

## Checks

`ruff check`, `ruff format --check`, `pytest -q`; `git grep -i math_shortcuts` finds only the plan
history (0065, 0066, plans/README, this plan) and the test-history comment.
