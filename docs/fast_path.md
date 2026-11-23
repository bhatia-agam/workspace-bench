# The fast path: reading a lens over the benchmark

`wsbench read` is reference code for producing a lens's readouts quickly. It is meant to be run
as it is on your own GPUs or on Modal, and to be read and adapted: every part is a small module
under `src/wsbench/produce/`. Judging is unchanged; this page is only about producing the
readouts files that `wsbench run` judges.

## The design in four parts

1. **Stored activations.** The subject model's activations do not depend on the lens, so they
   are captured once and kept in a residual store. For the reference model the store is the
   public dataset
   [agu18dec/workspacebench_residuals](https://huggingface.co/datasets/agu18dec/workspacebench_residuals):
   a read first looks on disk, then pulls from the dataset, and runs the 27B model only for
   cells that are in neither. Every stored item carries a key (its exact token ids, read
   positions, layers and steering), so a vector is only used for the prompt it was captured
   at. `src/wsbench/produce/store.py`, `dataset.py`; README "Stored activations" lists what
   the dataset holds.
2. **A lens bundle.** A lens that reads an activation by putting it in one slot of a prompt
   needs, at read time, only a servable copy of its weights and a small JSON: the prompt's
   token ids per layer, the slot's index and norm, the stop tokens and the sampling settings.
   That folder is the bundle (`src/wsbench/produce/served/bundle.py`; `wsbench bundle` makes
   one from a LoRA adapter). A lens trained with other model code plugs in by writing the same
   folder; nothing else in the path knows how the lens was trained.
3. **A served engine.** Instead of calling `generate` cell by cell, the cells' slot vectors
   are appended to a copy of the bundle's embedding table as extra vocabulary rows, and each
   cell becomes an ordinary request of token ids whose slot holds its row. A stock SGLang
   server then decodes them with continuous batching: a request leaves the batch the moment
   its readout ends and the next one takes its place. `src/wsbench/produce/served/`.
4. **One command.** `wsbench read` goes plan -> cells -> decode -> one readouts file per eval
   with its sidecar, packs small evals into one server start, resumes where it stopped, and
   with `judge=True` hands the files to `wsbench run`. `src/wsbench/produce/read.py`.

## What is stored

The 32-bit capture of the reference model, which is what `dtype=fp32` (the default) reads:

| set | evals | cells in the plan | cells stored | not stored |
|---|---|---|---|---|
| Every eval | 32 | 3,407,387 | 3,239,252 | 168,135 |
| The core evals | 18 | 2,906,722 | 2,884,128 | 22,594 |
| The fast subset | 16 | 438,790 | 425,513 | 13,277 |

Not stored: `user_modeling_hard` (142,252 cells), not captured and uploaded yet; 39
`knowledge_cutoff` questions (22,594 cells, 13,277 of them in the fast subset), left out on
purpose; `jlens_concept_pr` (3,289 cells), which ships no prompts. `wsbench read` runs the
model for the first two and cannot read the third. The capture is 39.7 GB in
`float32-capture/`; the repository root holds an older, partial 16-bit capture (28 evals,
1,371,161 cells, 20.6 GB, neither safety eval), read with `dtype=bf16`. An eval's files are
downloaded when it is first read. `wsbench capture families=all check=True` prints the current
state per eval.

## Hardware and time

Built for one GPU that holds the model per serving process: for the reference model an NVIDIA
B200 (183 GiB), where the served reader used 174 GiB at the default 768 running requests. A
smaller GPU needs fewer running requests (`server_args="... --max-running-requests <n>"`);
that was not measured. Host memory holds the cells of the evals being read (5,120 values of
two bytes per cell: about 0.6 GB per 60,000 cells).

Measured with the in-house reader this code was written from, on B200 GPUs, one trained slot
lens at 11 layers, one sample per cell; carried over, not measured again with `wsbench read`:

| what was read | cells | GPU-hours to read | wall-clock to read | start to score |
|---|---|---|---|---|
| Two questions, not judged | 803 | 0.04 | 4.5 min on 1 GPU | 4.5 min |
| The fast subset as it was selected then (22 evals) | 657,690 | 2.03 | 12 to 16 min on 12 GPUs | 52 min |
| Every eval at the time (30 evals) | 3,261,846 | 9.26 | 48 min on up to 32 GPUs | 2 h 29 min |

With fewer GPUs the GPU-hours stay and the wall-clock grows in proportion. Folding an adapter
into a servable copy of the model took about two minutes on one GPU in that tool; `wsbench
bundle` does it on the CPU and was not timed. Nothing in this table has been reproduced with
the code on this page.

What has been run with the code on this page, on one B200 with a real SGLang server:

| check | result |
|---|---|
| `wsbench capture` for 8 questions of `typo` and `poetry` | 187 cells pulled from the dataset, 0 forward passes |
| The served engine on those 187 cells, greedy | 145 s: 8 s to build the token bank, 111 s server start, 26 s of requests; 8,455 tokens; no banned token, no bank id sampled |
| The same cells and merged weights through the in-house reader, greedy | token ids identical on 187 of 187 rows |
| `wsbench read families=typo limit=2`, then `wsbench try dry_run=True` and `wsbench judge dry_run=True` on its file | ran end to end; the file was accepted |

The whole check took 5.9 GPU-minutes. It covers greedy decoding on a bundle that linked the
in-house reader's merged weights. Not covered by a GPU run yet: `wsbench bundle` on a real
adapter, sampled (non-greedy) agreement, `launcher=modal`, and `method=model_continuation`.

## Run it on your own GPU

```bash
uv sync --extra dev --extra gpu
uv pip install "sglang[all]" httpx          # the serving stack (not installed by an extra)

# once per lens: fold the adapter into a servable copy of the model
uv run wsbench bundle adapter=<adapter folder> model=<model snapshot folder> out=bundles/my-lens

# where are the cells? (no vectors downloaded, no model loaded)
uv run wsbench read --fast lens=bundles/my-lens out=outputs/readouts/my-lens check=True

# read the fast subset, then judge and report
uv run wsbench read --fast lens=bundles/my-lens out=outputs/readouts/my-lens judge=True
```

Each eval prints where its cells came from, for example `poetry: 1650 cells = 0 from the store
+ 1650 pulled from the dataset + 0 captured (0 forward passes)`, and then
`poetry: 1650 cells read -> outputs/readouts/my-lens/poetry.jsonl`. The model is loaded only if
some cells are in neither the store nor the dataset; it is released before the server starts.

| key | default | meaning |
|---|---|---|
| `method` | `lens` | `lens`: a served lens over stored activations; `model_continuation`: the baseline below |
| `lens` | required for `method=lens` | the lens bundle folder |
| `out` | required | the readouts root: `<out>/<eval>.jsonl` with its sidecar |
| `families`, `--fast`, `plan` | | which evals: a comma list or `all`, the fast subset, or a plan file (below) |
| `store`, `dataset`, `dataset_revision`, `revision`, `dtype`, `model`, `device` | as on `capture` | where the activations come from |
| `check` | `False` | only say where each eval's cells are |
| `engine` | `sglang` | the serving engine |
| `pack_cells` | `60000` | cells decoded per server start; evals are packed up to this many |
| `sampler` | `hf` | `hf`: top-k, renormalise, then top-p, the order of `generate`; `native`: the server's own joint filter |
| `greedy` | `False` | greedy decoding, for parity checks |
| `server_args` | the engine's | the server's flags, as one quoted string |
| `in_flight` | `4096` | request rows the client keeps in flight |
| `work` | a temporary folder | scratch space for the copy of the embedding table |
| `limit` | `0` | the first N questions of each eval |
| `shard`, `shards` | `0`, `1` | one process per GPU: each reads every `shards`-th question from `shard` and writes a part under `<out>/parts/`; whichever process finishes an eval last joins the parts and writes the sidecar |
| `judge`, `judged` | `False`, `<out>_judged` | then run `wsbench run readouts_root=<out> out=<judged>` on these evals |
| `launcher`, `gpus`, `modal_*` | `local` | the Modal launcher (below) |

Several GPUs on one machine are several processes:

```bash
for i in 0 1 2 3; do
  CUDA_VISIBLE_DEVICES=$i uv run wsbench read --fast lens=bundles/my-lens \
      out=outputs/readouts/my-lens shard=$i shards=4 &
done; wait
uv run wsbench run --fast readouts_root=outputs/readouts/my-lens out=outputs/judged/my-lens
```

`wsbench run wait=<seconds>` can be started before the read: it judges each eval when its
sidecar appears, so judging overlaps reading.

## Run it on Modal

The launcher is optional and thin (`src/wsbench/produce/modal_launch.py`, about 80 lines): it
builds an image with SGLang and this checkout, and runs the same command in `gpus` containers,
each on its own shard, against one volume. It needs `pip install modal` and a Modal account;
nothing else in the repository imports Modal.

```bash
uv run wsbench read --fast launcher=modal gpus=12 modal_volume=<your volume> \
    lens=/data/bundles/my-lens store=/data/store out=/data/readouts/my-lens
modal volume get <your volume> readouts/my-lens outputs/readouts/my-lens
uv run wsbench run --fast readouts_root=outputs/readouts/my-lens out=outputs/judged/my-lens
```

An image for this path needs, beside SGLang and `httpx`, the packages `wsbench` itself imports
(`pydra-config` and `pronouncing` are the two a serving image does not already have; the
launcher's `PACKAGES` lists them), and network access to the Hugging Face hub for the dataset
pull; an anonymous pull works, no token is needed for the public dataset.

The volume is mounted at `modal_mount` (default `/data`), so `lens=`, `store=` and `out=` are
paths under it, and the bundle has to be on the volume first (`modal volume put`). Settings,
all keys of the command: `gpus`, `modal_gpu` (default `B200`), `modal_volume`, `modal_mount`,
`modal_secret` (a secret holding `HF_TOKEN`, only if your dataset needs one), `modal_app`,
`modal_timeout`, `modal_sglang` (the pip requirement of the server). The image is a starting
point: a serving stack moves fast, so pin `modal_sglang` to the version you tested.

## The model-continuation baseline

How much of a lens's score could be had without reading any activation? `method=
model_continuation` gives the unmodified subject model each question's prompt, exactly as the
benchmark renders it, cut after a read position's token, and takes what the model says next as
that position's readout. It is served the same way (plain generation from token ids, no token
bank, no store), with the lenses' sampling: temperature 1.0, top-k 64 then top-p 0.95 in the
order of `generate`, at most 256 new tokens, one sample.

```bash
uv run wsbench read --fast method=model_continuation model_dir=<model snapshot folder> \
    out=outputs/readouts/model_continuation judge=True
```

Choices that keep the comparison with a lens fair: a row ends at the end-of-text token, not at
the end of a chat turn, so when the cut is the last token of the user's turn the readout is
the turn boundary followed by the model's reply; a question that is read under steering is
continued unsteered; no lens prompt is involved, so nothing of a lens's template can leak.
The baseline has no layer axis: there is one row per (question, position), written at one
layer number (`layer=`, default 44), and `judge=True` judges that layer alone
(`wsbench run ... layers=44`). `model_dir=` is a local folder with the model's files;
`pack_cells=`, `server_args=`, `in_flight=`, `work=`, `limit=`, `shard=` / `shards=` and the
Modal keys mean what they mean for a lens. `src/wsbench/produce/served/continuation.py`.

## Your own cell list

`plan=<file>` reads any cell list in the row format `wsbench plan` writes, so the same engine
serves prompts outside this benchmark (`docs/producing_readouts.md`, "The residual store", has
the row format). The readouts file is the benchmark's contract, and its sidecar's `plan_sha` is
the hash of the plan file's rows. `judge=True` is refused for a plan file: its judge is yours.

## Adapting it

- **Another serving stack.** An engine is one class with `decode(cells) -> list[list[str]]`
  (`served/engine.py`). A server that accepts prompt embeddings needs no token bank: build the
  embeddings from the bundle's prompt ids and the slot rows (`served/bank.py`, `slot_rows`).
- **Another lens.** Write a bundle folder. A lens that changes more than one input embedding
  (for example one that adds a learned map at every block) cannot be served this way.
- **Another subject model.** `wsbench capture model=<id> revision=<sha>` fills a store for it;
  the public dataset is for the reference model only (`dataset=none`).
- **Another scheduler.** `launcher=` is a dozen lines in `cli.Read.execute`; the unit of work
  is `wsbench read ... shard=i shards=n`, which any job system can run.

## What is not here

A served path for the NLA baseline (it adds the activation inside the model, not at an input
embedding, and needs a server plugin) is not part of this reference code; `wsbench produce
method=nla` reads the same stored activations through transformers.
