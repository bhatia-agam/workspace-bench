# Results viewer

A local web page for reading WorkspaceBench and HallucinationBench results: scores per eval with
error bars and floors, how each eval is judged and gated, and every question with each method's
readouts side by side, across layers and positions, next to what the judge saw and decided.

The page reads only a **store** (SQLite files). `ingest` fills the store from run outputs; the
sources are never modified.

## Install

```bash
uv sync --extra dev --extra viewer   # a bare `--extra viewer` would remove the dev tools
```

## Try it on two questions

```bash
uv run wsbench viewer ingest examples/viewer_toy adapter=wsb lens=toy-olens store=/tmp/viewer_try
uv run wsbench viewer serve store=/tmp/viewer_try        # http://127.0.0.1:8600
```

`examples/viewer_toy` is the judged result of `wsbench try family=multihop_st` on the shipped example readouts (two questions). A live `wsbench try`
ends with the same two commands for its own output, so a try-out opens in the viewer directly.
On any real run, add `families=multihop_st items=<id1>,<id2>` to ingest just two questions.

## The three commands

```bash
# 1. add a lens. <dir> is a judged run (<family>/results.json + cells.jsonl), or a lens
#    directory holding judged/, judged_ati/ and readouts/
uv run wsbench viewer ingest <dir> adapter=wsb readouts=<readouts dir> method=olens

# 2. the same for HallucinationBench: <dir> = <out>/<lens>
uv run wsbench viewer ingest <dir> adapter=hb hb_repo=<hallucination-bench checkout>

# 3. open it (127.0.0.1 only; private=True also shows items marked private)
uv run wsbench viewer serve
```

`adapter=bank` on a workspace-bench checkout adds every subject model's question set
(`adapted/<model>/`), so the model dropdown lists them. Ingest is idempotent: an unchanged
source is skipped. `wsbench viewer --help` lists every key; `wsbench viewer bank` still builds
the static bank browser.

## Where things go

- Store: `store=DIR`, else `$WSB_VIEWER_STORE`, else `outputs/viewer_store`. It holds
  `catalog.db`, `runs/<run>.db` (one per lens), `user.db` (bookmarks) and `manifest.json`, which
  documents every table. `build_dir=DIR` builds a database on a fast local disk first.
- Keys on a question page: `←` `→` positions, `↑` `↓` layers, `j` `k` questions, `h` next
  highlighted cell, `/` search, `b` bookmark, `?` help.

- Short lens names: `lens_aliases.json` in the store root, created empty:
  `{"<lens id>": {"label": "...", "description": "...", "default": true}}`. `default` marks the
  lenses a page shows before any are chosen. Edit it and reload; the full id stays on hover.
- Whole-prompt token strip: `wsbench viewer ingest . adapter=tokens` tokenizes every prompt with
  the subject tokenizer when `transformers` and the tokenizer are in the local HF cache
  (offline). Without them the strip shows the read positions only, and says so.
- Sanity check: `WSB_CHECKS="viewer_store=wsbench.viewer.checks:viewer_store" wsbench check
  viewer_store` ingests the toy run and compares scores and verdicts with its results.json.
- Groups: the headings of the README's 'The evals' section, which are the registry's eval
  categories (`registry.CATEGORIES`, what `group=` selects).
- Subsets: the dropdown offers **Core** (the default tier, where a core eval has a full-run
  score: the core evals' rows of the full run and the core macro), **Full bench**, **Fast
  subset**, **Fast subset + safety** and **ATI**, each only where the store has data for it.
- Family keys: eight keys changed on 2026-11-20 (plan 0101: `multihop_mt` became `multihop`,
  `multihop` became `multihop_st`, and the same for `basic_readout`, `multilingual`, `typo`).
  Ingest reads a run tree written before that as the family that wrote it, by its content
  (`registry.dir_family`), and stores it under today's key.

## What the page can and cannot say per layer

In summary mode the judge gives one verdict per question, not per layer. Per-layer charts are
then labelled **proxy** (the expected answer appears in the readout; the judge's quote sits at
this layer). Where a run has real per-layer verdicts (native and regex evals, HallucinationBench)
they are labelled **exact**.

## Layout

`store.py` schema · `ingest/{wsb,hb}.py` adapters · `meta.py` README parsing ·
`gates.py` the gate explanations · `tokens.py` · `checks.py` · `query.py` reads · `app/` pages ·
`static/` CSS and JS.
