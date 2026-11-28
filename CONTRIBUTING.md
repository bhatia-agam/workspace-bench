# Contributing

This page is for changing the benchmark: fixing an eval, adding one, or touching shared code. To
*use* the benchmark, start at the [README](README.md). Where things live:
[docs/repository_layout.md](docs/repository_layout.md).

## Set up

```bash
git clone https://github.com/camilablank/workspace-bench && cd workspace-bench
uv sync --extra dev
uv run wsbench check all      # offline, no key
```

CI runs three commands on every push and pull request; run them before you push:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The tests are offline: every judge call is faked and the two fetched data sources are stubbed.
A test that needs a key or the network does not belong in the suite.

## The parts of an eval

The code calls an eval a *family*. One eval is:

| part | where | what it is |
|---|---|---|
| Question bank | `evals/<category>/<family>/items*.json` | The questions. A bank is frozen: a change is a new file (`items_v<N>.json`), registered in the family's `EvalSpec`. |
| Page | `evals/<category>/<family>/README.md` | What the eval measures, where it is read, every judge prompt verbatim, the pass rule. |
| Code | `src/wsbench/evals/<category>/<family>/` | `__init__.py` registers the `EvalSpec`; `prompts.py` holds the prompts and `PROMPT_VERSION`; `judge.py` scores. |
| Read plan | `src/wsbench/readplan.py` | Which positions and layers are read for each question. |
| Example readouts | `examples/readouts/<family>.jsonl` | A few rows, enough for a dry run and the try-out. |
| Tests | `tests/test_<family>.py` | Offline tests of the judge, the bank and the pins. |
| Floors | `evals/baselines/` | What a guesser and a prompt-only reader score on this eval. |

## Changing an eval

Work through the parts the change touches, in this order.

1. **Bank.** Never edit a registered bank in place. Write the new version beside it, register it
   in the family's `__init__.py`, and say in the page what changed and why. A bank change moves
   the read plan, so readouts produced for the old bank no longer apply to changed questions.
2. **Prompts.** Edit the prompt in `prompts.py` and the same text in the page's fenced block;
   `tests/test_prompts_in_readme.py` fails if they differ. Any edit to a prompt, to the options
   a judge is shown or to the pass rule changes what a score means, so bump the stamp.
3. **Stamp.** `PROMPT_VERSION` in `prompts.py` is the eval's stamp. Results carry it, cached
   judge calls are keyed by it, and floors apply only to results with the same stamp. Bump it
   whenever the instrument changes; never reuse an old value.
4. **Floors.** A new stamp or bank leaves the eval without floors until they are measured again
   (`wsbench baseline`, then `wsbench freeze`). Until then `report` shows the row without a
   floor, which is correct. Say in the pull request whether floors were re-measured.
   [docs/baselines.md](docs/baselines.md).
5. **Checks and gates.** If the change adds or removes a gate (a rule that decides which
   questions are in the bank) or a scoring-time check (a rule the code applies to the judge's
   answer), update the "Checks and gates" table of the page.
6. **Tests.** Update `tests/test_<family>.py`. If a pinned hash or golden file moves, the change
   to it must be deliberate and named in the pull request; `tests/golden/README.md` says what
   each golden pins. The rename guard (`tests/test_rename_0101.py`) fails when an eval's
   instrument moves without a new stamp or bank; `scripts/manifest_0101_declare.py` records a
   declared change.
7. **Try it.** `uv run wsbench try family=<family> dry_run=True`, then a live run on a few
   questions (`limit=3`) before any full run.

## Adding an eval

Everything above, plus: the package under `src/wsbench/evals/<category>/<family>/` with an
`EvalSpec` (`group=<category>`), a page written from
[docs/eval_readme_template.md](docs/eval_readme_template.md), example readouts, the entry in
[docs/evals.md](docs/evals.md) and the row in [docs/judges.md](docs/judges.md), and a credit in
the README and `NOTICE.md` if the questions come from an external source. A new eval implements
summary mode (the default) or is listed in `digest.NATIVE_ONLY` with the reason.
[CLAUDE.md](CLAUDE.md) has the code conventions.

## Pull request checklist

- [ ] One purpose per pull request; the description says what changed and why, motivation first.
- [ ] `ruff check`, `ruff format --check` and `pytest` pass.
- [ ] A changed instrument has a new stamp; a changed bank is a new file.
- [ ] Prompts in the page match the code; the page's "Checks and gates" table is current.
- [ ] Floors: re-measured, or the description says they are pending.
- [ ] Any golden or pinned hash that moved is named, with the reason.
- [ ] No keys, no absolute paths of your machine, no results of unfinished runs in docs.
