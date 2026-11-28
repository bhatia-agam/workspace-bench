# Published residuals: the map

`map.json` describes the public dataset
[agu18dec/workspacebench_residuals](https://huggingface.co/datasets/agu18dec/workspacebench_residuals)
for the residual store (`src/wsbench/produce/dataset.py`). The dataset holds vectors, item ids,
layers and positions, and no prompt text, so the map records what the dataset cannot say about
itself: for each capture (today one, `fp32` under `float32-capture/`) and
each dataset folder, every item's store key at the benchmark commit the keys were built on.
The key is the sha256 of the item's exact token ids, read positions, layers and steering.

A read takes an item from the dataset only when the recorded key equals the key of today's
plan row. An item whose prompt, positions or layers changed since the capture is therefore not
found there and is captured with the model instead, until the eval is captured and uploaded
again and the map follows.

The dataset's `fast/` folders repeat the fast subset's questions. The map lists an item once,
under `full/`, where the lookup by id and key finds it, so it names no `fast/` folder. The
dataset no longer holds a 16-bit capture: `dtype=bf16` has nothing to pull and says so.

The file is written by `scripts/residuals_map.py` and is never edited by hand. When every
folder of the capture matches one benchmark commit's plan (the script prints `0 differ` for
each), key the whole capture at that commit and `merge` the part; that is how the current map
was written. When only some folders of the dataset change and the others no longer match the
current plan, key the changed folders alone at the commit they were captured on and `splice`
them in; each spliced folder then carries its own `bench_commit`. The script's docstring has
the commands.
`wsbench capture families=all check=True` then shows what the dataset holds of the current plan.
