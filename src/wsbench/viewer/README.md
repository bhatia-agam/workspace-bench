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

An eval's questions are the ones its bank file holds in the checkout that ingested last
(`repo=DIR`, else the checkout the command runs from): every ingest writes the bank of the
evals it stores. A question an earlier version of the bank held and the current one does
not leaves the eval's list; it keeps its text and its own page for the runs that were
judged on it, and such a run carries the mark `earlier questions` beside its score for
that eval: its score is on an earlier version of the questions.

`adapter=bank` on a workspace-bench checkout adds every subject model's question set
(`adapted/<model>/`), so the model dropdown lists them. Ingest is idempotent: an unchanged
source is skipped. `wsbench viewer --help` lists every key.

The prompt-only and lucky-guess floors of the registered banks (full and core sets) are
read from the checkout the viewer runs on (`evals/baselines/prompt_only_summary.json`,
`lucky_guessing.json`) when the viewer starts, not from a run's report: they are the
floors of the questions the checkout holds now. An eval whose frozen entry is stale by the
benchmark's own rule, or not measurable, shows none.

## Runs manifest

Runs that live on a volume are listed in a manifest and ingested with one command, one lens at
a time:

```bash
uv run wsbench viewer ingest runs.json adapter=manifest            # every finished run
uv run wsbench viewer ingest runs.json adapter=manifest run=<name> # one run (lens=, bench= narrow further)
uv run wsbench viewer check                                        # scores = the result files?
```

The manifest is a JSON list of runs, or an object with `runs` whose `volume`, `environment`
and `model` are defaults for every run. One run:

| key | meaning |
|---|---|
| `bench` | `wsb` or `hb` |
| `method` | `olens`, `nla`, `jlens`, `jpp_lens`, `rlens`, `logit_lens`, `continuation` or `other` |
| `lens` (or `lens_id`) | the lens id; with `run` it names the store run `<bench>__<model>__<lens>__<run>` |
| `label` (or `alias`) | the short name the pages show for this run |
| `run` | the run's name |
| `set` | `full`, `core`, `fast` or `anti-text-inversion` (`ati`); any other text is a description of a run that stands alone |
| `families_file` | on a `core` entry: a file listing the core evals, one per line (default: the benchmark's core tier) |
| `volume`, `environment` | a Modal volume and its environment, or a directory laid out like the volume |
| `judged` | WorkspaceBench: the directory of `<eval>/results.json` + `cells.jsonl`. HallucinationBench: the directory of `<family>/out/` trees (`<eval>/<judge>/<arm>/cells.jsonl`, `index/<judge>/index.json`) |
| `readouts` | the directory of the readout files (`merged/<eval>.jsonl`, else the read's shards) |
| `judged_ati` | the anti-text-inversion results (default: `judged_ati/` beside `judged`) |
| `derived` | sets derived from this full run: `[{"set": "fast", "run": ..., "judged": ...}]`, one per judged folder (default: run `<run>-fast` when it exists) |
| `report` | the run's `report.json`: its macro and floors. The stored macro is the report's when one is given |
| `results_file` | the run's own per-eval results (`{eval: {"value": ...}}`); ingest says where the judged folder differs from it |
| `timing_note` | the run's own words on its timings and costs; the runs page shows them on hover over the numbers |
| `bench_commit`, `engine` | text |
| `cells`, `read_gpu_hours`, `read_wall_seconds`, `judge_wall_seconds`, `judge_calls`, `judge_usd`, `total_usd`, `total_wall_seconds` | numbers from the run's result files; `null` when no file holds one |
| `integrity` | `{"label": "" / "partial" / "provisional" / "incomplete", "reason": "..."}` as the run's result files say; left out, it is read per eval from the results themselves |
| `state` | left out = finished. A run whose state does not start with done / finished / complete / judged is skipped with a line saying so; the same command picks it up later |
| `updates` | the name of the full run (same lens) whose evals this entry's `judged` folder replaces or adds to: evals judged again after the benchmark changed their questions, or new evals, in a run folder of their own |
| `sources`, `note` | where the numbers came from; free text |

A runs file that names its fields `lens_id`, `alias`, `judge_seconds`, `judge_usd_list`,
`bench_commit_wsb` / `judge_commit_hb` is read as it is.

A runs file may list one entry per set of a run. The entries of one lens and run name are
one store run, ingested together:

- `full`: the run itself, from its `judged` folder.
- `core`: the core tier of that same folder; the entry's `judged` is not read.
- `anti-text-inversion`: the results in its `judged` folder (`judged_ati/`), stored as the
  run's anti-text-inversion set.
- `fast`: the run named `<run>-fast` or `<run>-fast-<more>` (or an entry with the full run's
  name), stored as a fast set of the run, marked derived. A fast run with no full entry is a
  run of its own. Which fast set it is comes from the results themselves, not from the entry:
  results stamped with the current fast subset are the run's **Fast** set, results stamped
  with an earlier subset are stored under that subset's name and shown as an earlier fast
  subset. One run can therefore carry both, from two `fast` entries with different `judged`
  folders; two folders scored on the same subset are refused.

An entry with `updates` is no run of its own either. Its evals join the run it names (its
`full` entry, or the one entry of a run that stands alone, such as a fast run),
eval by eval: result files, judge calls and readouts of such an eval are read from the
entry's `judged` and `readouts` folders in place of the run's own (a later entry wins over
an earlier one), every other eval stays as the run has it. The run then has one row per
eval whatever folder it was judged in; each updated eval records the entry's run name and
`bench_commit` (the runs page shows them on the bench commit). The run's `report` was made
before the update: its floors for the updated evals are dropped and the stored macro is the
benchmark's own rule over the evals as they are now. An update entry whose folder holds no
result yet, or whose `state` is not finished, is skipped and picked up by a later ingest.

A runs file may also record such a run as one entry of its own (its own `judged`, if it
repeats the base run's, is not read):
`base` (`{"run": <the full run>}`) and `parts`, one per run folder, each with `run`,
`judged`, `readouts`, `bench_commit`, `results_file` and `state` (the entry's `state` when a
part has none). Every part is read as an `updates` entry of the base run. Where no entry
of its own lists the base run, the record is that entry (its `run`, `judged` and `readouts`
name the base run's folders); the record's own numbers are not stored. A second record over the
same parts (the core view of the same run) adds nothing.

Only the `full` entry writes the run row, its source, judge and full scores. An entry that
cannot be placed (a `core` entry without its full run, a second entry for the same run with
another set, a second `fast` entry for the same judged folder, a `judged` value that is not a
path) and a folder whose results are stamped with
another set than the entry names are reported as `FAILED`; the store keeps what it had, the
other runs are still ingested, and the command exits 1.

`report`, `results_file` and `families_file` are looked up as local files first (an absolute
path, else beside the manifest), then as paths on the run's volume; a file in neither place
fails the run and its sets, naming both places.

What ingest does with a run:

- It lists the run's files on the volume and compares them (size and time) with the last
  ingest: an unchanged run is skipped without a download, a changed one is replaced.
  When the files are unchanged and the entry still names the same folders, a change of its
  facts alone (timings, cost, notes, label, the report or families file) is written in place:
  nothing is downloaded and the run database is not rebuilt. The report's floors are stored
  at a full ingest only (`force=True`).
- Results, judge caches, indexes and run summaries are downloaded into the cache
  (`cache=DIR`, else `$WSB_VIEWER_CACHE`, else `~/.cache/wsbench-viewer`) and ingested by the
  WorkspaceBench and HallucinationBench adapters. Only files an adapter reads are fetched:
  HallucinationBench's raw call cache and joint cells are not, nor are the judge-call caches
  of a run's derived sets.
- The cache cleans up after itself. A WorkspaceBench run's judge-call cache and readout file
  are fetched eval by eval and removed as soon as the eval is in the run database; once a run
  is stored, every remaining cell or readout file (`*.jsonl`) is removed from its cache
  folder (for HallucinationBench also the per-layer result files of benign role-play), and the command prints one line per run with the count and size. The result files,
  reports, indexes and summaries stay: they are what `viewer check` and a facts update read
  again. A removed file is fetched again only by a forced or changed ingest; an unchanged run
  is recognised from the volume's listing alone. `keep_downloads=True` keeps everything.
- Readout files are not downloaded (`readouts=none`, the default). The run database records
  where each eval's files are (`modal://<volume>@<environment>/<path>`), and a question page
  fetches the eval's file into the cache the first time it is opened, then reads it locally.
  Such a run has scores, verdicts, judge calls and digests, the expected-answer and quote
  highlights computed when a question is opened, but no per-layer proxy charts and no readout
  search. A viewer that has the volume mounted as a directory (a hosted one) reads it there:
  `WSB_VIEWER_VOLUME_MOUNTS=<volume>=<directory>[,<volume>=<directory>]`, no `modal` command
  and no credentials needed. Where the volume cannot be reached (no `modal` command, no credentials, no network)
  the page shows `[readouts not available here: <address> (<why>)]` in place of the readouts.
  `readouts=index` fetches each eval's readout file once at ingest for the cell index, the
  flags and the proxy charts (text of flagged cells only); `readouts=copy` keeps all text, so
  search works. HallucinationBench samples are in the judge's own cells file and are always
  stored.
- HallucinationBench families of a manifest run. The run folder holds one folder per family
  (`<family>/out/...`, `<family>/readouts/...`) and, when the run has one, its own index over
  all families (`index/<judge>/index.json`), which is then the index (else the per-family
  index files are merged). Every family gets items, with the prompt from the benchmark
  checkout (`hb_repo=DIR`):
  - main, story: the claim map of each read cell (`<eval>/<judge>/<arm>/cells.jsonl`).
  - agentic misalignment, claims: the same claim map from
    `agentic_misalignment/<judge>/<arm>/cells.jsonl`, for the cells that have one (cells with
    a detected mention); a claim counts only where its segment overlaps a mention, and the
    page lists the cell's mentions.
  - agentic misalignment, situation: `agentic_misalignment/<judge>/<arm>/situation.jsonl`,
    one judge call per read cell. An item shows, per layer, the cells judged, the cells whose
    readouts misrepresent the scenario and the judge's reason for each; every cell's own call
    is listed with the cell.
    As in the benchmark, a flagged cell counts only with a quote located in its readout
    (the row's `counted`): one without is listed as flagged without a located quote and
    is not in the rate.
  - over-refusal: `overrefusal/<judge>/offtopic_index/index_counts.jsonl` (decline lines
    and off-topic decline lines per prompt and layer), `sj_records_full.jsonl` (the digest
    lines the strict judge read, its verdict and reason) and `offtopic/<arm>.jsonl` (the
    off-topic judge's reason).
  - benign role-play: `index_root/index_counts.jsonl` and the per-layer results of the
    jailbreak-recognition judge, for the prompts only this benchmark has
    (`benign_roleplay/<judge>/<arm>/<set>/jailbreak_recognition/L<n>/`) and for the ones it
    shares with WorkspaceBench (`campaign_raw/<arm>/jailbreak_recognition/L<n>/`): flagged
    or not, the judge's rationale and quotes, and the digest it read.
  The readouts of the last three stay on the volume (`<family>/readouts/`) and are read when
  a question is opened. A local output directory (`adapter=hb`, with `or/` and
  `br_index_root/`) is read as before.
- The store never records a cache path as a readout source. `wsbench viewer sources` lists the
  runs of a store whose readout files no longer exist on this machine; their cells without
  stored text show the same marker.

`wsbench viewer check` compares every stored headline score of the manifest runs with the
run's own result files (WorkspaceBench: `numbers.value` of each `results.json` per set and the
report's macro; HallucinationBench: the index value per family and layer) and prints each
mismatch; it exits 1 when there is one.

Per run the catalog keeps the manifest's facts (`run_facts`), which score sets the run has and
whether a set was judged as such or derived from the full run (`run_set`: the core rows and
the fast questions of a full run are derived; a separately read fast run is not), each eval's
integrity (`run_eval`) and HallucinationBench's index rows per layer (`hb_index`).
`manifest.json` in the store documents every table.

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
- Categories: the registry's eval categories (`registry.CATEGORIES`, what `group=` selects),
  read from the registry when a page is built, so a store ingested earlier follows them too.
  An eval is listed under its own category, and also under a second one where the benchmark's
  `groups.ALSO_IN` lists it there ("also listed under …"); without that table, once.
- Sets: **Core**, **Full**, **Fast** and **Anti-text-inversion**, each offered only where the
  store has scores for it. Core is the benchmark's core tier (`wsbench.tiers.CORE`, read when
  the page is built): the core evals' rows of the full run with the core macro (as stored at
  ingest; computed by the page for a run stored without them, or stored under an earlier core
  list), so it is labelled "derived from the full run"; any other set carries the same words
  when the store records it as derived from the full run rather than judged as that set.
- Fast sets: **Fast** is the current fast subset (`wsbench.fast.DEFAULT`) and nothing else.
  A run scored on an earlier fast subset is never shown as Fast: it is a set of its own,
  titled as an earlier fast subset with its number of evals, and its page says that it is not
  comparable with Fast. This holds for a run ingested now (its set is stored under the
  subset its results are stamped with) and for a store written while an earlier subset was
  the current one: its rows stay under `fast` and the page tells them apart when it is built,
  by the subset named in the set's stored note and, where there is none, by the
  evals and question list the rows cover. The store is not rewritten. The fast variant with
  the two safety evals is no longer derived from a full run; a store that holds it shows it
  as **Fast with safety (an earlier fast subset)**.
- Family keys: a run tree written under an earlier name of an eval is read as the family that
  wrote it, by its content (`registry.dir_family`), and stored under the current key.

## The pages

- **Scores** (the first page): one row per eval, by category, with the category links above
  the table. Columns: who scores the eval ("rule (regex)" where the registry names a
  deterministic scorer, else "Claude judge"), the number of questions, one column per chosen
  run with its 95% CI, and the floors. In summary mode the readouts of every eval, the
  rule-scored ones included, first pass through the Claude summarizer. For HallucinationBench
  the page also holds the table of index families (weight in the index, what each tests,
  prompts, who scores it), the claim-map taxonomy (every leaf under its verdict, with its
  weight) and each run's index rows as its index file has them: one row per layer and the
  joint row, one column per family and per macro.
- **One eval**: what it tests, an example, how it is judged and by whom, its gates, the scores
  of the chosen runs, a per-layer chart, the stored score rows per layer (HallucinationBench:
  the index row of each layer, and the joint row) and the question list with every run's
  verdict. An eval a run's results mark as incomplete or provisional carries that tag beside
  its score, with the reason on hover.
- **One question**: the prompt, the layers x positions map of each open run, and one pane per
  run with the readouts of the current cell next to the judge's decision. HallucinationBench
  readouts are coloured by claim-map leaf, with a legend that groups the leaves under their
  verdicts (hallucination, probe candidate, thinky, correct, unresolved, junk); a segment shows
  the judge's reason and quotes, and the span classifier's axes when the store has them.
  Readouts kept on a volume are read when the question is opened; where they cannot be had,
  the pane says "Readouts not available here" with their address, and still shows the verdict
  and the judge calls.
- **Runs**: one row per run with what its result files gave ingest: method, run name, sets
  (a derived one says so), cells, GPU-hours to read, read and judge wall-clock, judge calls,
  judge and total cost, engine, bench commit, integrity label with its reason, and where the
  readouts are (in the store, local, cached, on a volume, missing). A fact the files do not
  hold is a dash. A click on a heading sorts.
- **Layers**, **Filter** (compare two runs: questions one gets right and the other wrong, or
  ranked by the difference of their rates), **Search** (readout full text) and **Bookmarks**.
- Methods: O-lens, NLA, J-lens, logit lens and model continuation each have one colour, used
  for that method in every chart, chip and legend (`meta.METHODS`); runs of the same method
  differ by shade and line style. A run the store marks (partial, provisional, incomplete)
  shows that label with its reason beside its name.
- Runs shown before any is chosen: the lenses the alias file marks `default`, one run per
  lens. When a lens has several runs, the one with scores in the set on screen is taken, then
  the one that has a full set, then the one with the most evals in that set, then the newest;
  the others are in the run chooser.

## What the page can and cannot say per layer

In summary mode the judge gives one verdict per question, not per layer. Per-layer charts are
then labelled **proxy** (the expected answer appears in the readout; the judge's quote sits at
this layer). Where a run has real per-layer verdicts (native and regex evals, HallucinationBench)
they are labelled **exact**.

## Layout

`store.py` schema · `ingest/{wsb,hb}.py` adapters · `ingest/reader.py` the runs manifest ·
`remote.py` volumes, the download cache and on-demand readouts · `meta.py` README parsing ·
`gates.py` the gate explanations · `tokens.py` · `checks.py` · `query.py` reads · `app/` pages ·
`static/` CSS and JS.
