# Published residuals: the map

`map.json` describes the public dataset
[agu18dec/workspacebench_residuals](https://huggingface.co/datasets/agu18dec/workspacebench_residuals)
for the residual store (`src/wsbench/produce/dataset.py`). The dataset holds vectors, item ids,
layers and positions, and no prompt text, so the map records what the dataset cannot say about
itself: for each capture (`fp32` under `float32-capture/`, `bf16` in the repository root) and
each dataset folder, every item's store key at the benchmark commit the capture was made on.
The key is the sha256 of the item's exact token ids, read positions, layers and steering.

A read takes an item from the dataset only when the recorded key equals the key of today's
plan row. An item whose prompt, positions or layers changed since the capture is therefore not
found there and is captured with the model instead.

A folder that was captured at a later benchmark commit than the rest of its capture carries its
own `bench_commit` in the map (`full/directed_modulation` and `full/user_modeling_hard` of the
32-bit capture). The dataset's `fast/` folders hold an earlier selection of the fast subset;
the lookup is by id and key across all folders, so today's fast questions are found in `full/`.

The file is written by `scripts/residuals_map.py` and is never edited by hand. When only some
folders of the dataset change, key those folders alone at the commit they were captured on and
`splice` them in (the script's docstring); a full rebuild at a later commit would drop the
folders that no longer match that commit's plan. To rebuild it
after a new capture is uploaded, run the script once per capture with that capture's benchmark
commit checked out, then merge the parts (the script's docstring has the two commands).
`wsbench capture families=all check=True` then shows what the dataset holds of the current plan.
