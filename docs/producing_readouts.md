# Producing readouts

Judging is the contract; producing is optional. The item banks, the judges, the baselines and
the results contract are the benchmark; to score a lens you run it on the cells the plan names,
anywhere, and hand this repo one readouts file per family. `wsbench produce` (below) is a
bundled producer for anyone who would rather not write that plumbing. This page is the
interface between the two halves.

## 1. Get the read plan

```
uv run wsbench plan --full out=outputs/plan        # every family
uv run wsbench plan out=outputs/plan-core          # the core tier (the default; `--core`)
uv run wsbench plan families=poetry,buggy_code     # a subset
```

One JSONL per family, one row per bank item. A row says exactly what to feed the model, how to
render it, which token positions to read, and at which layers:

```json
{"family": "poetry", "id": "couplet-ahead-head", "render": "plain",
 "positions": {"kind": "line_one_tail"}, "layers": [20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60],
 "text": "A rhyming couplet:\nThe captain pointed at the route ahead,\nAnd told his crew to follow where he'd ",
 "note": "line one's last word through the newline that ends it (never the line-two stub); lite = that newline",
 "lite_positions": {"kind": "final_token"}}
```

| key | meaning |
|---|---|
| `render` | how to turn the row into a token sequence; the vocabulary is `wsbench.readplan.RENDERS` (`plain`, `chat`, `chat_context`, `chat_prefill`, `chat_dm`, `chat_summarize`, `bare`, `captured`) |
| `text` / `messages` / `system` / `prefill` / `suffix` / `assistant` | the pieces the render composes; `captured` rows ship `extra.input_ids` instead |
| `positions` | a rule over the rendered tokens (below); `wsbench.readplan.resolve(rule, tokens)` turns it into indices once you have tokenized the render |
| `lite_positions` / `lite_layers` | the `reads=lite` site: a rule over the row's FULL positions (`same`, `final_token`, `offset_from_end {k}`, `offsets_from_end {ks}`, `last_n {n}`, `positions {…}`, `every_nth_plus_tail {n, tail}`) and its layers (absent = the full layers). Lite is always a subset of full, so one full read serves both; `wsbench run reads=lite` re-judges the same file. A file produced `reads=lite` (sidecar `reads: "lite"`) already holds only the lite site and is judged as it is: the rule is never applied twice. When every row's rule is `same` at the full layers (association, conjunctive_association, the directed-modulation families, user_modeling, basic_readout_st, user_modeling_hard), a lite run gets the full read's completeness checks, and a declared-lite file with one position per cell exits 2 (it was produced under a superseded lite rule) |
| `layers` | the decoder layers to read (residual stream after that layer) |
| `note` | the family's read site in one line; the family README has the rest |

Positions rules, all handled by `resolve`:

| kind | selects |
|---|---|
| `final_token` | the last token of the render |
| `offset_from_end {k}` | the token `k` from the end (`k=1` is the last) |
| `last_n {n}` | the last `n` tokens |
| `all` | every token |
| `all_from_end` | every token, reported as negative offsets `-n..-1` (arithmetic intermediates: the bank and judge count from the end) |
| `positions {positions}` | explicit indices (jailbreak, J-lens precision) |
| `line_one_newline` | the newline token that ends line one (poetry's lite site) |
| `line_one_tail {anchor?}` | line one's last word through the newline that ends it: the word's tokens, any punctuation after it, and that newline (poetry's full read; `couplet-ahead-head` → `" ahead"`, `","`, `"\n"` = positions 14-16). `anchor: "last_newline"` ends it at the last newline anywhere (adapted `chat_prefill` items) |
| `from_token {token}` | from the first token with that text through the end (chain's question span) |
| `from_text_last_token {text}` | from the LAST token of the (last) occurrence of `text` through the end (chain: "The starting number is 23" reads from the "3") |
| `from_last_sentence_start` | from the first token of the last user turn's final sentence through the end (user modelling) |
| `suffix_text {text}` | the tokens spelling `text` at the end of the render (directed modulation's carrier) |
| `suffix_text_then_tail {text}` | those plus every token after them (the association families' summarize suffix and chat tail) |

Renders are described for Qwen3.6-27B's chat template; another model's template changes every
position index, which is why the rules are given as rules and not as numbers wherever the bank
allows it. `resolve` works on the token strings of any tokenizer.

## 2. Read the lens

For every row, every position the rule selects and every layer: run your lens on the residual
activation there and keep what it produces. A prose lens gives one or more text samples; a token
lens gives a ranked token list with scores.

## 3. Write the readouts file

One JSONL per family, one row per (item, layer, position), in the contract of the top-level
README:

```json
{"id": "couplet-ahead-head", "layer": 36, "pos": 16, "token": "\n", "samples": ["led the way"]}
{"id": "couplet-ahead-head", "layer": 36, "pos": 16, "token": "\n", "tokens": [" led", " said"], "scores": [9.1, 7.7]}
```

`id` is the row's `id` from the plan, `pos` the index into your render, `token` that position's
token string (optional, checked where a family knows it). A file is all-prose or all-tokens.
Missing cells are fatal by default: every (item, layer) the plan asks for must have a row, or the
run must be told `allow_missing=True` and the result is marked incomplete.

`wsbench convert-gen-dir` and `wsbench convert-read-json` produce this shape from the two
in-house producer layouts; anything else needs a few lines of your own.

**Layers.** Every family's plan reads the 11-layer grid (`GRID`, agentic `GRID + [63]`).
`wsbench plan layers=all` (or `WSB_LAYERS=all` in a producer's environment) plans every model
layer; `layers=20,44` any combination. A file may hold more layers than the plan: every present
layer is judged. `wsbench run layers=44` judges one layer (a complete, defined variant);
`layers=each` runs the all-layer config plus one sub-run per layer in the file.

**The sidecar.** A producer declares how it sampled, beside the file:
`<family>.jsonl.meta.json` = `{"reads": "full|lite", "sampling": "bullet4|prose1|tokens10",
"reader": "<method>", "arm": "<arm>", "layers": [...], "plan_sha": "<reads.plan_sha(family)>"}`.
The rule: a SINGLE-bullet oracle lens (the `*-x4` arms) gets 4 separate
samples per activation (`bullet4`); every other prose method, the multi-bullet s3d O-lens and NLA
included, ONE sample per activation (`prose1`); a token lens its top 10 (`tokens10`). The
sampling is declared, never inferred from bullet shape; `sampling=` on the CLI overrides it.
`wsbench produce` and the converters (`sampling= arm= plan_sha=`) write the sidecar. With a
sidecar, `reads.load` enforces the full span (a lite file under `reads=full`, a missing plan
layer or a different `plan_sha` exits 2); a sidecar-less file is judged as it is, with the
same checks reported only (`config.reads_checked = "no_sidecar"`, never a campaign result).

## 4. Judge

```
uv run wsbench judge family=poetry readouts=outputs/readouts/mylens/poetry.jsonl out=outputs/judged/mylens/poetry dry_run=True
uv run wsbench run all=True readouts_root=outputs/readouts/mylens out=outputs/judged/mylens
uv run wsbench report dir=outputs/judged/mylens
```

Every run is in summary mode by default (each item's readouts go to one passive digest,
judged once; `docs/summarizer.md` § Item digest). Add `opts=aggregate=native` for the per-cell
rules, into a separate `out=` dir.

**Throughput.** `judge` and `run` default to `concurrency=256` (calls in flight per
family), `rpm=30000` (requests a minute) and `itpm=60000000` (estimated input tokens a minute,
a call counted as its prompt's characters / 3; `itpm=0` = off); `rpm` and `itpm` are budgets of
the whole run. `run` judges eight families at a time (`family_workers=8`; `family_workers=0` = all at once, `N` caps it). Several `wsbench judge` processes started by hand on one account share its limits: set `WSB_SLOTS=<dir>:<n>` in each to cap the API calls in flight across all of them (unset = off for `judge`; 29 families at 256 each exceed a 15M output-tokens-a-minute limit without it). On a rate-limited key lower `rpm=`, then `itpm=`, then `concurrency=`. None of these
changes a cache key or a score. A family whose calls failed after their retries prints
`<family>: N judge call(s) failed after retries; ...` on stderr; rerun into the same `out=` to
ask only those again.

**Judging through Message Batches.** `judge_backend=batches` sends the Claude calls through
Message Batches instead of live requests: same requests, same caches, outside the live rate
limits (`docs/judge_backends.md`).

**One process per family (`run procs=True`, the default).** `run` starts one `wsbench judge`
process per family, `family_workers` at a time: one Python process is one CPU core, and eight
families at `concurrency=256` inside one process drop connections, while a process per family
at the same settings drops none.

- The run itself does the up-front work, in this order: the `--fast` membership check, the
  readouts check (and the waiting of `wait=`), the ATI scope check and one preflight per judge and
  digest model; a failure there exits before any process starts. Each judge process then
  preflights its own models again (one or two tiny calls per family). Results, messages, per-family
  outcomes, `summary.md`, `run.json` and the exit code are those of the one-process run (plus two failure messages of its own, `judge process exited N` and `killed by signal N`, and an unexpected error in one family stops the others at once); only the
  order in which the families' lines reach the terminal differs.
- `rpm=` and `itpm=` stay budgets of the whole run, and at most 1,500 API calls are in flight
  across the processes (about what a 15M output-tokens-a-minute limit carries). The run makes a
  private directory under the system temporary directory (`wsb-run-*`, never under `out=`) for the
  lock files and removes it at the end; that directory must support `flock`, or the run exits 3
  before starting anything (set `TMPDIR` to a local disk). A `WSB_SLOTS=<dir>:<n>` already in the
  environment is used instead of the 1,500 cap.
- A family whose process exits 2 or 3, or is killed by a signal (for example out of memory), is
  that family's failure only; any other exit stops the run. Ctrl-C starts no new family, lets the
  running ones finish and exits 130; a second Ctrl-C terminates them. SIGTERM and SIGHUP terminate
  them at once.
- `procs=False`, or `WSB_RUN_PROCS=0` in the environment (the key wins), judges the families in
  threads of one process; `dry_run=True` and `layers=each` always do.
- `judge outcome=PATH` is how a judge process reports back to its `run` (a small JSON file with
  the family's status and exit code); it is not meant for other callers.

**Judging while the read is running (`run wait=SECONDS`).** With `wait=` greater than 0, a family
whose readouts are not ready is pending instead of skipped. `run` submits the ready families at
once, looks at the pending ones every 2 s and submits each as it becomes ready. It stops waiting
when nothing is pending, when `SECONDS` have passed since the start, or when the file
`<readouts_root>/_READS_DONE` exists; it then finishes the families in flight and reports the
ones still pending as skipped (exit code 0, as for any skipped family).

- **Ready** = `<family>.jsonl` exists AND its sidecar `<family>.jsonl.meta.json` exists, parses
  as a JSON object and has a modification time not older than the file's. A file under a former
  family key counts, as without `wait=`.
- **What a producer does:** write the JSONL (ideally under a temporary name, then rename it),
  then the sidecar, last. When copying files in from elsewhere, copy the sidecar last: a copy
  tool that does not preserve modification times can otherwise leave the sidecar older than the
  file, which is not ready. `wsbench produce` follows this: it deletes an existing sidecar before
  it appends to a readouts file and writes it again at the end, atomically, so a resumed file is
  not ready while it grows (after a crash the file has no sidecar until the next resume finishes).
- **`_READS_DONE`**: create `<readouts_root>/_READS_DONE` when no more files are coming. Files
  that landed together with it are still judged. Nothing in this repo writes or removes it, so
  delete a stale one before a new read starts; one that is already there ends the wait at once.
- **`settle=SECONDS`** (default 0 = a sidecar is required): a file with no sidecar whose
  modification time is at least that old is also ready. Opt-in, for producers that write no
  sidecar; a slow writer looks settled, and a sidecar-less file is judged with the read checks
  report-only (`config.reads_checked = "no_sidecar"`).
- A pending family is skipped with `no readouts at <path> after waiting <wait>s` when its file
  never appeared, `readouts at <path> not ready after <wait>s (no current sidecar)` when the file
  is there without a current sidecar, and plain `no readouts at <path>` when `_READS_DONE` ended
  the wait. A family judged late prints `<family>: readouts landed after <t>s`, and `run.json`
  records the top-level `wait` and that family's `waited_s`.
- Every judge and digest model of the pending families is preflighted before the first call,
  with the ready ones. A family outside the `--fast` subset is skipped at once, never waited
  for. `wait=` works with `--fast`, `anti_text_inversion=True`, `layers=<list>` and `reads=lite`;
  it is refused with `dry_run=True` and with `layers=each`.

One command for a read in progress (the reader writes each family's sidecar last and
`_READS_DONE` at the end):

```
rm -f outputs/readouts/mylens-fast/_READS_DONE   # then start the read into that directory
uv run wsbench run --fast all=True readouts_root=outputs/readouts/mylens-fast out=outputs/judged/mylens-fast wait=3600
```

## Fast subset (`--fast`)

`--fast` judges the frozen subset `fast-v5` (`evals/fast/README.md`): 16 families
(the core tier without `jailbreak_recognition` and `agentic_misalignment`), a seeded random
half of each family's units plus the whole strict ATI subset, 1,441 read items. **A full
readouts file is always judgeable with `--fast`**: the judge keeps the fast items itself, so
existing full readouts need no re-read. To read only what the fast subset needs:

```
uv run wsbench plan --fast out=outputs/plan-fast          # the 16 fast families
uv run wsbench run --fast all=True readouts_root=outputs/readouts/mylens-fast out=outputs/judged/mylens-fast
```

- The fast plan is the full plan's rows of the fast read items: same render, layers and
  positions rule for every family (no `fast-v5` row carries a reduced-position rule), so a
  producer of the full plan needs nothing new. A pair, a headline unit or a slot is read with
  every row it needs (both members of a pair, the rows an introspection item's twins read, a
  slot's puzzle), which is why a family's read items can outnumber its units.
- Declare the file in its sidecar: `"fast": "fast-v5"` and `"plan_sha"` = the FAST plan's sha
  (`wsbench.reads.fast_plan_sha(family)`, i.e. `plan_sha_rows` over the rows
  `wsbench plan --fast` wrote), with `"reads": "full"`. A file that declares `fast` is judged only with
  `--fast`. `wsbench produce family=F --fast` does all of this.
- A FAST file declaring another version is judged only when that version reads the family's
  same items at the same positions (`fast.same_reads`; with a `plan_sha`, or the same bank).
  `fast-v4` does for every family but `chain_intermediates` (`fast-v5` is `fast-v4` re-cut for
  that family's bank `items_v3.json`), so a `fast-v4` FAST file of another family is judged as it is.
  The older versions (`fast-v1` .. `fast-v3`, `fast-safety-v1` / `-v2`) read other items than
  `fast-v5`, so their FAST files are refused under `--fast`: judge from a full file, or produce
  the `fast-v5` plan. (Their reduced-position rows, `fast_of` with `last_n` / `punct_special`,
  exist only in those frozen files: `wsbench.readplan.resolve(rule, tokens)` still resolves
  them, on DECODED token strings.) `--fast-safety` is retired.
- `--fast` takes full reads only (no `reads=lite`), on the registered
  Qwen3.6-27B banks only.

## Or let the repo produce them

`wsbench.produce` is a small producer over Hugging Face transformers, for anyone who has a GPU
and wants readouts without writing the plumbing. Install the `gpu` extra (`uv sync --extra gpu`)
and:

```python
from wsbench.produce import Producer

# methods: logit_lens | jlens | rlens | olens | nla
p = Producer.load("Qwen/Qwen3.6-27B", "jlens")
p.read("The athlete Muhammad Ali plays the sport of", pos=-1, layer=36).readout.tokens
p.read_prompt("Sechs geteilt durch zwei ist", positions="all", layers=[20, 36, 60])
# a whole eval set, resumable; the plan picks the cells
p.run_family("poetry", "outputs/readouts/mine/poetry.jsonl", limit=10)
# swap method, keep the loaded model
p.use("olens")
```

The same from the shell:

```
wsbench produce family=poetry method=logit_lens out=outputs/readouts/mine/poetry.jsonl
wsbench produce text="The athlete Muhammad Ali plays the sport of" method=jlens positions=-1 layers=20,36,60
```

**Where the activations come from.** `wsbench produce family=<eval>` (and `Producer.load(...,
store=..., pull=...)` in Python) reads the eval's activations from [the residual
store](#the-residual-store): what is on disk, then the published residuals, and a forward pass
only for the cells that are in neither, which are then written to the store. It prints the
same line as `wsbench capture`, for example `poetry: 3322 cells = 0 from the store + 3322
pulled from the dataset + 0 captured (0 forward passes)`. Its keys for this are `store=`
(default `outputs/store`), `dataset=`, `dataset_revision=`, `revision=` and `dtype=`, with the
meanings they have on `capture`; with a store the model is loaded in the capture's dtype
(`dtype=fp32` loads it in 32-bit floats, `dtype=bf16` as shipped). The model is still loaded,
since every bundled method needs its weights to read a vector; the forward passes over the
prompts are what is skipped. `store=none`, the `text=` form and a `Producer` built without a
store run one forward pass per prompt and keep nothing.

What it does: renders the prompt the way the plan says (its chat template, thinking off),
takes the residual stream after each requested decoder block (from the store, or in one forward
pass), and hands each (layer, position) vector to the method. The vector lenses (`logit_lens`, `jlens`, `rlens`)
return the top-10 tokens with scores; `olens` verbalizes through its LoRA with the vector placed
in the carrier prompt's `<activation>` slot as `alpha · unit(h)`, the adapter off while capturing
and on while generating; `nla` runs Karvonen's reader with the vector added norm-matched at its
marker token. Methods are plain classes behind one `read(h, layer)` protocol, so a new lens is a
few lines. Sampling for the verbalizers is `Sampling(temperature=1.0, top_p=0.95, top_k=64,
max_new_tokens=256, k=1)`, the settings of the in-house arms.

Two spellings, on purpose: the read-site `token` is `tokenizer.decode([id])`, exactly what the
banks store (`"\n"`, `" öffnen"`, `"<|im_end|>"`); the ranked `tokens` of a token lens are the
byte-level BPE strings with `Ġ`/`▁` shown as a space (`" led"`, and `"çļĦç»ĵæŀľ"` for 的结果).
`wsbench.readouts.load_readouts` decodes each of those to text once, on load
(`wsbench.bpe.decode_token`: `"çļĦç»ĵæŀľ"` -> `"的结果"`, `"Ċ"` -> `"\n"`), so every summarizer,
judge and regex sees text. Write the vocabulary strings. A string that does not decode cleanly is kept as written: a token holding
part of a character stays in its byte-level spelling, and most already-decoded text survives
(`"café"`, `"się"`), but decoded text that happens to spell valid UTF-8 in the byte table
(`"Ã©"`) is decoded again.
`pos` is the index the plan resolves: absolute, except the two rules that count from the end
because their banks and judges do — `offset_from_end` (some multihop items) and `all_from_end`
(arithmetic intermediates) — whose rows carry the negative offset (`-8`). A single-layer lens reads at its trained layer whatever the
plan lists: `nla` is layer 42 (not on the benchmark grid; in-house NLA numbers read at L44
are off-layer and superseded). `nla` also loads its own copy of the reader (a second 27B on the
same device), so it wants an H200; the other methods fit one H100.

What it is not: fast. It reads one prompt at a time on one GPU, which is right for a token
position, a question or a family, and wrong for the whole benchmark at every token; the in-house
runs fan that out over Modal.

## The residual store

The subject model's activations do not depend on the readout method, so they are captured once
and kept: `wsbench capture` runs the model over a read plan and writes the residual stream at
every planned cell to a store on disk, and every method can then read the same vectors without
running the model again.

```
uv run wsbench capture families=poetry,multihop store=outputs/store   # needs --extra gpu
uv run wsbench capture --fast store=outputs/store                     # the fast subset's plan
uv run wsbench capture plan=my_cells.jsonl store=outputs/store        # any cell list
```

Each eval prints where its cells came from, for example
`poetry: 3322 cells = 3322 from the store + 0 pulled from the dataset + 0 captured (0 forward
passes)`. A second run of the same command makes no forward pass and does not load the model.

| key | default | meaning |
|---|---|---|
| `families` | | a comma list, or `all`; with `--fast`, the fast subset's evals |
| `plan` | | a plan file instead of `families=`: rows in the format `wsbench plan` writes |
| `store` | `outputs/store` | the store's root folder |
| `model`, `revision` | Qwen/Qwen3.6-27B at the revision the banks were built on | the subject; `revision=<sha>` is required for another model |
| `dtype` | `fp32` | the subject's dtype during capture: `fp32` (the forward runs in float32) or `bf16` (the model as shipped); vectors are stored as bf16 either way |
| `reads` | `full` | `lite` captures the lite sites only |
| `limit` | `0` | the first N items of each eval |
| `shard`, `shards` | `0`, `1` | this process captures every `shards`-th item from `shard` (items sorted by id): one process per GPU |
| `device` | `cuda` | |
| `dataset` | `agu18dec/workspacebench_residuals` | the published residuals, asked before the model runs: a Hugging Face dataset id, a local folder that holds a copy of it, or `none` |
| `dataset_revision` | the revision the map was built on | another revision of that dataset |
| `check` | `False` | `True`: one line per eval saying how many cells are in the store, in the dataset and in neither; downloads no vectors and loads no model (it renders the plan, so it needs the tokenizer, which is fetched once if it is not cached) |

**What is stored.** One folder per model revision, capture dtype and eval:
`<store>/<revision>/<dtype>/<eval>/<pack>.safetensors` (`acts`, one row per cell) with a
`<pack>.json` beside it that lists the pack's items and, per item, its cells as
`[layer, position, token]`. Every stored item carries a key: the sha256 of its exact token ids,
its read positions, its layers and its steering. A read asks for items by id and key, so a
vector is only handed out for the prompt, positions and layers it was captured at. An item
stored under another key (the bank or the plan changed since) is refused, counted in the
printed line, and captured again; a pack found under another revision or dtype than its folder
is an error.

**A plan file from somewhere else.** `plan=` takes any cell list in the plan's row format, so
activations for prompts outside this benchmark are captured and read the same way. The minimal
row gives the exact token ids, the positions and the layers:

```json
{"family": "my_eval", "id": "item-1", "render": "captured",
 "positions": {"kind": "positions", "positions": [3, 7]}, "layers": [20, 44],
 "extra": {"input_ids": [151644, 872, 198]}, "lite_positions": {"kind": "same"}}
```

A row may also give text to render (`"render": "chat"` with `"text"`, see the table in §1) and
any positions rule. `family` is a free name here; it only names the store folder.

**The published residuals.** The store fills itself from the public dataset
[agu18dec/workspacebench_residuals](https://huggingface.co/datasets/agu18dec/workspacebench_residuals)
before it runs the model (`wsbench.produce.dataset.Residuals`). The dataset holds vectors, item
ids, layers and positions, and no text, so `evals/residuals/map.json` records, for every stored
item, the key it had at the benchmark commit the capture was made on. An item is pulled only
when that key equals the plan's key today; index files are read first and only the part files
that hold wanted rows are downloaded. The map is built by `scripts/residuals_map.py`, run with
the capture's own benchmark commit on the path; a new capture or a re-upload means running it
again. The README's "Stored activations" section has the table of what is stored.

In Python, `wsbench.produce.store.cells_for(store, eval, plan_rows, tokenizer, backend=...)` is
the one call that returns cells: from the store, else from a `pull` function, else from a
forward pass, which it writes back to the store.

## A served engine (reference code)

The producer above reads one activation at a time. `wsbench.produce.served` is reference code
for the fast way to read a slot lens: a lens that replaces ONE prompt token's input embedding
with the activation, scaled as `norm_L * h / ||h||`. Instead of sending embeddings to a
server, the cells' slot vectors are appended as extra vocabulary rows of a copy of the lens
model (the "token bank"), and each request is plain token ids whose slot position holds that
cell's bank row id. A stock SGLang server with continuous batching then decodes all rows
together, and a row leaves the batch the moment it ends.

Two details keep the readouts equal in kind to the producer's. A logit processor inside the
server masks the bank ids, and the engine asks again for any row that still sampled one (a
bank id is never kept). A second, optional processor applies top-k and then top-p in the
order Hugging Face `generate` does; the server's own sampler applies both to the full
distribution, which keeps a larger nucleus.

It is small on purpose (`src/wsbench/produce/served/`, one job per module), to be run as it is
or adapted:

| module | what it holds |
|---|---|
| `bundle.py` | the lens bundle: `load`, `merge` (a LoRA folded into a copy of the model, file by file, on the CPU), `from_adapter` |
| `bank.py` | `slot_rows` (the slot vectors), `build_bank` (the model copy with the bank rows) |
| `sampling.py` | `SamplingPlan` (a bundle's sampling as server parameters), `hf_top_k_top_p` |
| `processors.py` | the two logit processors (the only module that imports `sglang`) |
| `server.py` | start and stop a local SGLang server process |
| `engine.py` | the `Engine` protocol, `SGLangEngine`, `load` |

**The lens bundle.** The engine needs one folder and nothing else: the model files with the
lens's adapter folded in (what a server can load), a `lens.json`, and a marker
file `MERGE_DONE` that says the folder is complete. `lens.json` holds:

| key | meaning |
|---|---|
| `name` | the lens's name |
| `model`, `model_revision` | the subject model's id and the revision the lens reads (the residual store's key) |
| `prompts` | per layer, `{"<layer>": {"ids": [...], "slot": int, "norm": float}}`: the readout prompt's token ids, the index of the slot token in them, and the norm the activation is scaled to |
| `stop_ids` | token ids that end a readout |
| `ban_ids`, `ban_min_new` | token ids that are never sampled, and how many new tokens come before a stop token may end the readout; `[]` and `0` for no ban |
| `base_vocab` | rows of the model's embedding table; bank row `j` is token id `base_vocab + j` |
| `prefix_ids` | token ids put in front of every readout before it is decoded to text; usually `[]` |
| `sampling` | `{temperature, top_p, top_k, max_new_tokens, k}`; `k` readouts are sampled per cell |
| `sampling_kind` | what the readouts sidecar declares: `prose1` or `bullet4` |

**Making one.** For the bundled O-lens (`method=olens`: a PEFT LoRA on the subject and the
carrier prompt with one activation slot), `wsbench bundle` builds the folder from two local
folders, on the CPU and without loading the model:

```
uv run wsbench bundle adapter=<PEFT adapter folder> model=<subject snapshot folder> out=bundles/my-lens
```

| key | default | meaning |
|---|---|---|
| `adapter` | | a local PEFT adapter folder (`adapter_config.json`, `adapter_model.safetensors`); plain LoRA only, DoRA and rsLoRA are refused |
| `model` | | a local folder with the subject's files (config, tokenizer, weights) |
| `out` | | the bundle folder to write; it needs about the model's size on disk |
| `name` | the `out` folder's name | |
| `prompt`, `alpha` | the O-lens's | the carrier prompt (with `{layer}` and `{char}`) and the slot norm: the slot vector is `alpha * unit(h)` at every layer |
| `model_id`, `revision` | Qwen/Qwen3.6-27B at the revision the banks were built on | recorded as `model` and `model_revision`; `revision=<sha>` is required for another model |
| `temperature`, `top_p`, `top_k`, `max_new_tokens`, `samples` | `1.0`, `0.95`, `64`, `256`, `1` | the bundle's `sampling` |
| `bullet` | `False` | a single-bullet lens: 4 readouts per cell and `sampling_kind` `bullet4` |

**A lens with its own model code** (trained elsewhere, not a PEFT adapter on the subject)
plugs in by writing the same folder: save a copy of the lens model that a server can load,
write `lens.json` with the keys above, then the `MERGE_DONE` file. If the lens is a LoRA,
`bundle.merge(snapshot, out_dir, lora_state, scaling, meta)` does all three. The engine only
needs the lens to be a slot lens: the activation enters at one token position, with a norm
that depends on the layer alone.

**Reading cells.** Cells come from the residual store; the engine returns `k` strings per
cell, in cell order:

```python
from wsbench.produce.served import bundle, engine

lens = bundle.load("bundles/my-lens")
eng = engine.load("sglang", lens)  # options: work=, max_bank=, server_args=, sampler=, greedy=, ...
texts = eng.decode(cells)  # cells: list[wsbench.produce.store.Cell] -> list[list[str]]
eng.stats.as_dict(), eng.checks  # seconds per stage, token-length and ban checks
eng.close()
```

`decode` builds the bank for the cells, starts the server on it, sends the requests, and stops
the server; more than `max_bank` cells are read as several banks. The server samples, so
readouts are not seeded. `sampler="hf"` (the default) uses the Hugging Face filter order and
needs temperature 1.0; `sampler="native"` leaves top-k and top-p to the server. Writing the
texts in the readouts contract (§3) is the caller's job.

**What it needs.** `sglang` and `httpx` beside the `gpu` extra (`uv pip install sglang
httpx`; they are not in the lock file), and one GPU that holds the model. An image built from
a serving stack alone also needs `accelerate`, which the `gpu` extra has: loading the subject
model for a capture uses it. The default server
flags (`engine.DEFAULT_SERVER_ARGS`) are scheduler settings chosen on one GPU type: a B200
with 183 GiB, for Qwen3.6-27B at 768 running requests. A smaller GPU needs fewer running
requests: pass your own flags with `server_args=[...]`. Other GPUs and other models were not
measured. The scratch folder (`work=`, a temporary folder by default) holds the bank: two
rewritten weight files and symlinks to the rest.

**Another serving stack.** Write a class with the members of `engine.Engine` (`name`,
`sampler`, `stats`, `tokens`, `decode(cells)`, `close()`) and return it from `engine.load`.
An engine whose server accepts prompt embeddings needs no bank: it embeds `prompts[layer].ids`,
replaces the row at `slot` with `bank.slot_rows(...)`, and sends that.

## What the plan does not carry

- **Model-dependence.** The banks were gated on Qwen3.6-27B; `wsbench capable` re-runs that gate on
  another model, and `AGENTS.md` says which families port, which need re-gating and which need
  re-generating.
- **Sampling.** The in-house arms use k=1, temperature 1.0, top-p 0.95, top-k 64, max 256 new
  tokens for prose lenses and top-10 for token lenses; the judges accept any k.
- **Steering.** `introspection` rows carry `extra.steering` (a concept or gaussian vector
  added at layer 12 over a token span, `h <- h + beta * ||h|| * v / ||v||`); the producer must
  apply it in the forward that is read. The vectors ship with the bank
  (`evals/model_specific/introspection/vectors/*.npy`; each row names `vector_file` / `vector_row`), and
  `wsbench produce` applies the steer itself (a forward hook on the inject layer's output over
  the span; `type: none` rows are a plain forward). Any other steering type is refused.
- **A family without text.** `jlens_concept_pr` ships captured token ids and positions, not
  prompts: its items are the model's own activations, read by re-feeding those ids.
