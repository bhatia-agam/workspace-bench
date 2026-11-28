# HallucinationBench

HallucinationBench (HB) measures hallucination in activation-reading lenses: the claims a lens
makes that the model's own computation contradicts. WorkspaceBench has no hallucination family
of its own. HB's code, banks and tests live in this repository, moved here unchanged from
[its own repository](https://github.com/camila-blank/hallucination-bench):

| what | where |
|---|---|
| the package (its own command, `wsbench hb`) | [`src/wsbench/hb/`](../src/wsbench/hb/CLAUDE.md) |
| the banks, the manifest of the frozen index and the method table | [`evals/hallucinationbench/`](../evals/hallucinationbench/README.md) |
| tests | `tests/hb/` |
| scripts (bank builders, Modal jobs, audits) | `scripts/hb/` |
| HB's README (kept as written in its own repository: where it says `hbench` and `data/`, read `wsbench hb` and `evals/hallucinationbench/`), results and design history | [`docs/hb/`](hb/README.md), `plans/hb/` |

## The index

The index is the weighted share of a lens's claims that are hallucinated (lower is better;
index version `hindex-v8`, family weights main 9 / am_claims 3 / am_situation 3 / sibling 1 /
story 1 / overrefusal 1 / benign_roleplay 2). There is one number per (method, layer): `full`
where the method has every family, else `matched (no sibling)` (J-lens).

**The index is a separate number. It never enters the WorkspaceBench macro, a tier or the fast
subset**, and `wsbench hb` registers no WorkspaceBench family: an HB family is not one pass rate
over items (its units are claims, situation cells, refusal lines and prompts, each method has
per-layer rows and a joint row, and the index is a weighted macro with its own bootstraps).

**The index of record is the vendored file** `evals/hallucinationbench/index.json`, frozen at
one HB commit and written only by `scripts/vendor_hb_index.py`. A method is shown for an arm
only when the arm's checkpoint is verified to be that method's (`evals/hallucinationbench/methods.json`),
never by alias. `wsbench report dir=D [hb_method=<name>]` appends the index after the macro
table, per judged layer plus the layer mean for a multi-layer run.

## Running it

`wsbench hb <command> [options]` is HB's own command line (argparse options, not `key=value`);
`wsbench hb --help` lists the commands. Install the tokenizer its sibling eval needs with
`uv sync --extra dev --extra hb`.

```bash
uv run wsbench hb run --eval story --readouts-root <dir> --arms <a,b> --out <dir>   # judge
uv run wsbench hb run --eval story --rebuild --readouts-root <dir> --arms <a,b> --out <dir>
                                              # no API call: cells and summaries from the cache
uv run wsbench hb report --out <dir>
uv run wsbench hb final --manifest evals/hallucinationbench/index/v8_manifest.json \
    --methods evals/hallucinationbench/index/methods.json --out <dir> --plots <dir>
```

`final` checks every file the manifest names (sha256, cell and failure counts), rebuilds the
index from exactly those files and draws the plots. Run from the repository root with the judged
outputs at the manifest's paths (`outputs/...`), it reproduces the vendored numbers. An index
built here records this repository's commit, so `scripts/vendor_hb_index.py`, which accepts
only the HB commit it is pinned to, does not vendor it.

Judging uses the same credentials as the rest of the bench. One family, `benign_roleplay`, is
judged by a separate pinned WorkspaceBench checkout (`$HBENCH_WSBENCH_PUB`), never by this
checkout's `jailbreak_recognition`; the runbook
[`src/wsbench/hb/CLAUDE.md`](../src/wsbench/hb/CLAUDE.md) says why and holds every other
operating note (external inputs are `HBENCH_*` environment variables, `src/wsbench/hb/paths.py`).

Tests: `uv run pytest tests/hb -q` (offline). A change to any HB prompt, bank, scoring rule or
weight is a new index version.
