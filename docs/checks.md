# `wsbench check`: gates and sanity checks in one command

```bash
uv run wsbench check                 # list every check and what it guards
uv run wsbench check fast_subset     # run one: prints PASS or FAIL and one line of why
uv run wsbench check all             # run every check that needs no option; the others are listed as SKIP
```

Exit code: 0 = PASS, 1 = FAIL, 2 = usage error (unknown check, missing or unknown option).

| check | what it guards | options | needs |
|---|---|---|---|
| `fast_subset` | The registered banks are byte-identical to the ones the fast subset was frozen on (`fast.entry`). | | offline |
| `ati_subset` | Every anti-text-inversion entry still matches its family's judge instrument and bank (`text_inversion.subset_entry`). The one listed exception (chain_intermediates, `text_inversion.STALE_NO_ITEM_PENDING_AUDIT`: an entry of another bank with no id, read on the one bank recorded there) passes with a `NOTE` naming the family. | | offline |
| `frozen_pins` | The pinned tests of the fast subset, the ATI freeze and the bank versions pass. | | offline, `dev` extra |
| `readme_prompts` | Every judge prompt in the code is verbatim in its family README (`tests/test_prompts_in_readme.py`). | | offline, `dev` extra |
| `readouts_contract` | A readouts file parses under the contract: no malformed, duplicate or mixed-kind rows. | `readouts=FILE` `[family=F]` | offline |
| `judge_dry_run` | Each family builds its first judge prompt from `examples/readouts`, with no API call. | `[family=F]` | offline |
| `capable_gate` | A subject model answers the banks' own gate questions (`wsbench capable`). | `model=M` `[family=F]` `[limit=N]` `[dry_run=True]` | model and judge access unless `dry_run=True` |
| `adapt_gate` | An adapted set ships only items with a passing gate record. | `model=<folder under adapted/>` | offline |

## Adding a check

A check is a function that takes its options as keyword arguments (strings) and returns
`(ok, why)`: a bool and one line. Register it by dotted path, so nothing is imported until it runs.

In this repo, add the function to `src/wsbench/checks.py` and one `register(name, guards,
"wsbench.checks:<function>")` line at the bottom. A check whose assertions already live in a test
file is one line: `return pytest_outcome("tests/test_x.py")`.

From outside the repo (for example a reader's HF-vs-SGLang parity check), name it in the
environment; its one-line description is the function's docstring:

```bash
export WSB_CHECKS="reader_parity=reader.checks:parity"
uv run wsbench check reader_parity options=lens=my-lens,engine=sglang
```

`options=` passes any keyword the built-in keys (`family=`, `model=`, `readouts=`, `limit=`,
`dry_run=`) do not cover. Several plug-ins are a comma list: `WSB_CHECKS="a=pkg.mod:f,b=pkg.mod:g"`.
