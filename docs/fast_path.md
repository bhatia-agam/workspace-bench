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

## Run it on your own GPU

```bash
uv sync --extra dev --extra gpu
uv pip install "sglang[all]" httpx          # the serving stack (not installed by an extra)

# once per lens: fold the adapter into a servable copy of the model
uv run wsbench bundle adapter=<adapter folder> model=<model snapshot folder> out=bundles/my-lens

# where are the cells? (downloads nothing, loads nothing)
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
| `lens` | required | the lens bundle folder |
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

The volume is mounted at `modal_mount` (default `/data`), so `lens=`, `store=` and `out=` are
paths under it, and the bundle has to be on the volume first (`modal volume put`). Settings,
all keys of the command: `gpus`, `modal_gpu` (default `B200`), `modal_volume`, `modal_mount`,
`modal_secret` (a secret holding `HF_TOKEN`, only if your dataset needs one), `modal_app`,
`modal_timeout`, `modal_sglang` (the pip requirement of the server). The image is a starting
point: a serving stack moves fast, so pin `modal_sglang` to the version you tested.

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
