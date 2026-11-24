# Adding an eval

The code calls an eval a family. An eval is a folder of code, a folder of data, a read plan and
entries in shared tables. Registering the package is not enough: `wsbench list` and
`wsbench check judge_dry_run` work at once, but `wsbench plan` and `wsbench try` stop with
`no read plan for '<eval>'` until the read plan exists, and about thirty tests fail until the
tables below are filled. Writing the questions is the `wsb-new-questions` skill
(`.claude/skills/wsb-new-questions/`).

## The eval's own files

| file | what it holds |
|---|---|
| `src/wsbench/evals/<category>/<eval>/__init__.py` | `register(EvalSpec(...))`: name, title, `group=<category>` (it must equal the folder), the bank path, the judge, the metric, `run`, `calls_per_arm`, `sources`. |
| `.../prompts.py` | `PROMPTS` (every judge prompt) and `PROMPT_VERSION`. |
| `.../judge.py` | `run(args) -> FamilyResult`; it writes nothing. It scores in summary mode, the default (`digest.collapse`, then a judge over the summary), or the eval is listed in `digest.NATIVE_ONLY` with its reason. |
| `evals/<category>/<eval>/items.json` | The bank. Once merged it is frozen: a change is a new file beside it. |
| `evals/<category>/<eval>/README.md` | The eval's page: bank, read sites, scoring, and every prompt of `PROMPTS` verbatim in a fenced block, with `PROMPT_VERSION`. |
| `examples/readouts/<eval>.jsonl` | A few rows of toy readouts, for `try` and the dry run. |
| `tests/test_<eval>.py` | Offline tests; replace the module's `run_calls` so no call is made. |

## Entries every eval needs

The command or test in the last column fails until the entry is there.

| where | entry | what tells you |
|---|---|---|
| `src/wsbench/readplan.py`, `_plan` | A branch that returns the eval's `ReadSpec` rows: render, positions rule, layers. | `wsbench plan families=<eval>`; `tests/test_readplan.py` |
| `src/wsbench/capable/questions.py` | A builder in `BUILDERS` (the question that gates an item on another model), or a reason in `NO_QUESTION`. | `tests/test_capable.py` |
| `src/wsbench/baselines/text_inversion.py` | A reason in `NOT_GATED`, or an entry in the frozen anti-text-inversion file made by running the panel gate. | `wsbench check ati_subset`; `tests/test_check_command.py`, `tests/test_ati_freeze.py`, `tests/test_glm_ati.py` |
| `evals/baselines/prompt_only_summary.json` | The eval's frozen prompt-only floor ([baselines.md](baselines.md)), or, for an eval outside the core set, a reason in `PENDING_FLOOR` in the test. | `tests/test_po_floors_r3.py` |
| `src/wsbench/adapt/families.py` | A reason in `NOT_ADAPTED`. Or, for an eval that per-model sets build, a `Family` in `FAMILIES` and an entry in `FAMILIES` of `src/wsbench/adapt/judge_inputs.py`. | `tests/test_adapt_judge_inputs.py`, `tests/test_adapt_skill_docs.py` |
| `.claude/skills/adapt-bank/references/families.md` | A row in the table of banks: the eval and its bank path. | `tests/test_adapt_skill_docs.py` |
| `tests/golden/manifest_0101_declared.json` | The ledger entry of the eval's judge instrument, written by `python scripts/manifest_0101_declare.py <eval> --plan <plan number> --note "<one line>" --write`. | `tests/test_rename_0101.py` |
| `scripts/readme_evals_table.py`, `WHAT` | One sentence on what the eval tests; then `python scripts/readme_evals_table.py --write` rewrites the README table. | `tests/test_readme.py` |
| `docs/evals.md` | Under the category: the title line with the link to the eval's page, then exactly three lines, `- *What it is:*`, `- *Example:*`, `- *Judged by:*`. | `tests/test_readme.py` |
| `docs/judges.md` | A row with the eval's name and its prompt version. | `tests/test_readme.py` |

## Entries only some evals need

| where | when |
|---|---|
| README "Credits" and `NOTICE.md` | The items come from an outside source: the `sources` text of the spec, verbatim (`tests/test_readme.py`). An in-house eval is not named there. |
| `src/wsbench/baselines/lucky_guessing.py` (`BUILDERS`, `DESCRIPTIONS`) | The eval is multiple choice and gets a guessing floor from `wsbench baseline`. |
| `scripts/summary_mode_compare.py` | The eval's item rule is not the default one of that script (`tests/test_summary_mode_compare.py`). |
| `src/wsbench/tiers.py`, `CORE` | The eval joins the core set. That is the maintainer's decision and it comes with a new cut of the fast subset (`scripts/fast_cut_core_half.py`). A new eval is in the full set with no entry. |
| `docs/read_sites.md`, `docs/tiers.md`, `evals/baselines/README.md` | The eval has read sites, a tier or floors to state there. |

## Tests that pin the list of evals

These hold a count or a table of every eval. Each fails on a new one and names what it expected.

| test | what it pins |
|---|---|
| `tests/test_tiers.py`, `tests/test_family_paths.py` | the category of every eval |
| `tests/test_groups.py` | the evals of each category |
| `tests/test_readplan.py`, `tests/test_rename_0101.py`, `tests/test_no_token_interpreter.py` | the number of evals; the listing `wsbench list` prints |
| `tests/test_fast_subset.py`, `tests/test_migrate_0101.py` | the evals added since a frozen snapshot of the plan (a `since` set) |
| `tests/test_adapt_skill_docs.py`, `tests/test_user_modeling_hard.py` | how many evals the per-model driver builds; which evals are in `NOT_ADAPTED` |
| `tests/test_check_command.py` | the counts in the messages of `wsbench check` |
| `tests/test_token_note_prompts.py`, `tests/test_mc_cannot_tell.py` | multiple-choice evals: the token note and the "cannot tell" option |

## Check it

```bash
uv run wsbench list
uv run wsbench check judge_dry_run family=<eval>
uv run wsbench plan families=<eval> out=outputs/plan-new
uv run wsbench try family=<eval> dry_run=True
uv run wsbench check all
uv run pytest -q
```

Then judge three questions for real before any full run:
`uv run wsbench judge family=<eval> readouts=<file> out=outputs/judged/new limit=3`.
