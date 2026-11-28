# Repository layout

What lives where. The package is used from a checkout: the question banks in `evals/` sit beside
the code in `src/`, and the code finds them through the registry (`wsbench.registry`), never by
building paths.

## Top level

| path | what it holds |
|---|---|
| `README.md` | What the bench is, install, the try-out, a full run, where outputs go, the evals table. |
| `CONTRIBUTING.md` | How to set up, change an eval and open a pull request. |
| `docs/` | Guides and reference pages; [docs/README.md](README.md) is the index. |
| `evals/` | The data of every eval: question banks, each eval's page, frozen floors and subsets. |
| `src/wsbench/` | The `wsbench` package: the CLI, the loader, the judges, the baselines, the viewer. |
| `adapted/` | Per-model question sets for subjects other than the reference model, one folder per model. |
| `examples/` | A few readout rows per eval for dry runs and the try-out, and a toy judged run for the viewer. |
| `tests/` | The offline test suite; no test calls an API. |
| `scripts/` | Bank builders, one-off replays and Modal launchers. Not part of the package. |
| `plans/` | Numbered design notes, kept as the record of why things are the way they are. |
| `AGENTS.md` | Running the bench on another model: what the banks assume and the checks to run first. |
| `CLAUDE.md` | Code conventions and the per-eval change log, written for contributors and coding agents. |
| `NOTICE.md`, `LICENSE`, `CITATION.cff` | Credits for external sources, the license, how to cite. |
| `pyproject.toml`, `uv.lock` | Package metadata and pinned dependencies (`uv sync --extra dev`). |
| `.github/workflows/ci.yml` | CI: `ruff check`, `ruff format --check`, `pytest`. |

## `evals/`: the data

Evals are grouped by category. The code calls an eval a *family*.

| path | what it holds |
|---|---|
| `evals/<category>/<family>/README.md` | The eval's page: what it measures, read sites, every judge prompt verbatim, the pass rule, its history. |
| `evals/<category>/<family>/items*.json` | The question bank. The registered version is named in the family's `EvalSpec`; earlier versions stay as frozen records. |
| `evals/<category>/<family>/` other files | Build records of the bank (distractor pools, gate reports, option tables). |
| `evals/baselines/` | The frozen floors (lucky guessing, prompt only, logit lens) and the anti-text-inversion subset. |
| `evals/fast/` | The frozen fast subsets, one file per version. |
| `evals/residuals/` | The map of the stored-activations dataset. |
| `evals/hallucinationbench/` | The vendored HallucinationBench index that `report` shows beside the macro. |

Categories: `basic`, `computational`, `association`, `safety`, `anti_bag_of_features`,
`logical_processing`, `model_specific`, `jlens_comparison`.

## `src/wsbench/`: the code

| path | what it holds |
|---|---|
| `cli.py` | Every `wsbench` command and its keys. |
| `registry.py` | The list of evals (`EvalSpec`), their categories, banks and paths. |
| `evals/<category>/<family>/` | One package per eval: `__init__.py` registers it, `prompts.py` holds its judge prompts, `judge.py` scores it. |
| `basic/`, `multitoken/` | Judges shared by several evals of the basic category. |
| `readplan.py` | The read plan: what to feed the model and which positions and layers to read, per question. |
| `readouts.py`, `reads.py` | The readouts file contract and the one loader every eval uses. |
| `digest.py` | The summarizer that turns an item's readouts into the notes the judge reads. |
| `mcjudge.py`, `mc.py`, `llm.py`, `judge_config.py`, `judge_batches.py`, `cache.py` | The judge layer: calls, caching, models, the Batches backend. |
| `results.py`, `runner.py`, `tiers.py`, `fast.py` | Results, the macro, the run driver, the core / full / fast sets. |
| `baselines/` | The floors and the anti-text-inversion gate. |
| `produce/` | Optional: capturing activations and producing readouts with a bundled lens (`gpu` extra). |
| `adapt/`, `capable/` | Building and checking a per-model set. |
| `viewer/` | The local results viewer (`viewer` extra). |
| `checks.py`, `tryout.py` | `wsbench check` and `wsbench try`. |

## `tests/`

| path | what it holds |
|---|---|
| `tests/test_<family>.py` | Each eval's offline tests (the judge's calls are faked). |
| `tests/golden/` | Pinned prompts, option lists and hashes; `tests/golden/README.md` says what each file pins. |
| `tests/fixtures/` | Small inputs for tests. |
| `tests/conftest.py` | Shared fixtures; stubs the two fetched data sources so tests stay offline. |

## What a run writes

Nothing is written into the checkout except under `outputs/` (ignored by git) or the `out=` you
pass. See "Where outputs go" in the [README](../README.md).
