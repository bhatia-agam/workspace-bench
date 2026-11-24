# Quick start: one lens on the fast subset

The shortest path from a clone to a table for one lens on the fast subset, a frozen part of the
core evals ([fast_subset.md](fast_subset.md)). Fast values are not comparable with core values.

## 1. Install

```bash
uv sync --extra dev
uv run wsbench check judge_dry_run     # offline, no credential: every eval builds a judge prompt
```
Judging needs an Anthropic credential in the environment (README, "Requirements").

## 2. Get readouts

A readouts folder holds one `<eval>.jsonl` per eval. Pick the route that fits your lens.

**Your own reader.** Write the plan, then run your lens at every row's positions and layers:

```bash
uv run wsbench plan fast=True out=outputs/plan-fast
```

Each row of `outputs/plan-fast/<eval>.jsonl` is one question: how to render it, which positions,
which layers. Write `outputs/readouts/my-lens/<eval>.jsonl` with one row per cell, in the format
of [producing_readouts.md](producing_readouts.md) (sections 1 to 3, and the sidecar a fast file
declares under "Fast subset"). A file that holds every question of an eval works too: the judge
keeps the fast questions. `uv run wsbench check readouts_contract readouts=<file> family=<eval>`
checks one file without a judge call.

You do not need to run the model for its activations. They are stored in a public dataset, and
`capture` copies the fast subset's part to a local store, from which
`wsbench.produce.store.cells_for` returns the vectors of an eval's plan rows
([producing_readouts.md](producing_readouts.md#the-residual-store)):

```bash
uv sync --extra dev --extra gpu
uv run wsbench capture fast=True check=True          # where the cells are; fetches no vectors
uv run wsbench capture fast=True store=outputs/store
```

**A bundled method** (`logit_lens`, `jlens`, `rlens`, `olens`, `nla`). One command per eval; each
loads the model and reads the stored activations:

```bash
uv run wsbench produce family=poetry method=jlens fast=True out=outputs/readouts/jlens/poetry.jsonl
```

In Python, `Producer.run_family(name, out, fast=True)` over `fast.families()` reads every fast
eval with one load of the model ([producing_readouts.md](producing_readouts.md#or-let-the-repo-produce-them)).

**A trained slot lens, served.** `wsbench read` is the reference inference code: it takes the
stored activations, decodes them with a served engine and writes every file
([fast_path.md](fast_path.md)). With `judge=True` it also does steps 3 and 4:

```bash
uv sync --extra dev --extra gpu && uv pip install "sglang[all]" httpx
uv run wsbench bundle adapter=<adapter folder> model=<model snapshot folder> out=bundles/my-lens
uv run wsbench read fast=True lens=bundles/my-lens out=outputs/readouts/my-lens judge=True
```

## 3. Judge

```bash
uv run wsbench run fast=True readouts_root=outputs/readouts/my-lens out=outputs/judged/my-lens-fast dry_run=True
uv run wsbench run fast=True readouts_root=outputs/readouts/my-lens out=outputs/judged/my-lens-fast
```

The first line makes no API call. `fast=True` alone selects every eval of the fast subset. Other
pages write this step as `--fast` or as `fast=True all=True`; the code accepts all three and
resolves them to the same settings (add `--show` to see them). An eval with no file is skipped
and listed. Add `wait=3600` to judge while a producer is still writing.

## 4. Report

```bash
uv run wsbench report dir=outputs/judged/my-lens-fast fast=True
```

It prints one row per eval and the fast macro ([results_contract.md](results_contract.md)).
