# Documentation

Start with the [README](../README.md): what the benchmark is, install, the two-question try-out
and a full run. The pages here go deeper. The docs say "eval" for what the code calls a family.

## Use the benchmark

| page | read it when you want to |
|---|---|
| [quickstart_fast.md](quickstart_fast.md) | Take one lens through the fast subset, from install to the report. |
| [evals.md](evals.md) | See every eval with one example and its judging rule. |
| [producing_readouts.md](producing_readouts.md) | Know what to read (the read plan, positions, layers) and how to write a readouts file, or produce one with a bundled lens. |
| [running.md](running.md) | Look up every option of `judge` and `run`, throughput settings, and how to judge while a producer is still writing. |
| [tiers.md](tiers.md) | Choose between the core, full and fast sets and understand their macros. |
| [fast_subset.md](fast_subset.md) | Know how the fast subset is drawn and how its scores relate to core scores. |
| [fast_path.md](fast_path.md) | Read a lens quickly with stored activations and a served engine, on your GPUs or on Modal. |
| [judge_backends.md](judge_backends.md) | Choose live calls or Message Batches and size concurrency. |
| [results_contract.md](results_contract.md) | Read `results.json` and the macro row field by field. |
| [checks.md](checks.md) | Run the built-in checks, or add one. |

## Understand a score

| page | read it when you want to |
|---|---|
| [judges.md](judges.md) | Know which model judges each eval, with which prompt, and why. |
| [summarizer.md](summarizer.md) | Know how an item's readouts are turned into the notes the judge reads (the item digest), with its prompts. |
| [baselines.md](baselines.md) | Understand the floors beside each score and the anti-text-inversion subset. |
| [read_sites.md](read_sites.md) | See exactly which tokens are read for the association evals, relational_multihop and moral_rationale. |
| [hallucinationbench.md](hallucinationbench.md) | Understand the HallucinationBench index that `report` shows beside the macro. |
| Each eval's page | `evals/<category>/<family>/README.md`, linked from the table in the [README](../README.md#the-evals): questions, read sites, prompts, pass rule, history. |

## Run it on another model

| page | read it when you want to |
|---|---|
| [porting.md](porting.md) | Re-run each bank's own gate on another model. |
| [../AGENTS.md](../AGENTS.md) | Know what the banks assume about the model and which checks to run before trusting a number. |
| [../adapted/README.md](../adapted/README.md) | Use or build a per-model question set. |
| [adapt_judge_inputs.md](adapt_judge_inputs.md) | Look up, per eval, every bank field its judge and read plan read (generated from the code). |

## Contribute

| page | read it when you want to |
|---|---|
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Change or add an eval, and open a pull request. |
| [adding_an_eval.md](adding_an_eval.md) | See every file and shared table a new eval touches, and the tests that say what is missing. |
| [adding_a_readout_method.md](adding_a_readout_method.md) | Add a readout method of your own to `wsbench produce`. |
| [repository_layout.md](repository_layout.md) | Find what lives where. |
| [eval_readme_template.md](eval_readme_template.md) | Write or revise an eval's page. |
| [../CLAUDE.md](../CLAUDE.md) | Follow the code conventions; also the per-eval change log, for contributors and coding agents. |
| [../tests/golden/README.md](../tests/golden/README.md) | Know what each pinned golden file guards. |

## Records

Kept for the record; they describe the benchmark as it was when they were written.

| page | what it records |
|---|---|
| [summary_mode_validation.md](summary_mode_validation.md), [summary_mode_audits/](summary_mode_audits/) | The validation of summary mode before it became the default, and its audits. |
| [archive/](archive/README.md) | Results write-ups of finished plans. |
| [open_work.md](open_work.md) | Open work. |
| `../plans/` | Numbered design notes. |
