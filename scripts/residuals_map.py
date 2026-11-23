"""Build one capture's part of `evals/residuals/map.json`: for every item of the published
residuals, the residual store's item key at the benchmark commit the capture was made on.

Run it with that commit's source on the path, so the keys are those of the prompts that were
captured (the dataset holds vectors, item ids, layers and positions, never text):

    PYTHONPATH=<checkout of the capture's bench commit>/src python scripts/residuals_map.py \\
        <dataset dir holding manifest.json and <variant>/<eval>/index.json> <out.json>

It only uses that checkout's `readplan`, `registry` and `produce.render`, and needs the subject's
tokenizer (no model, no GPU). The map is then written by

    python scripts/residuals_map.py merge <part.json>... <map.json> <dataset repo> <revision>
"""

import hashlib
import json
import sys
from pathlib import Path


def item_key(ids: list[int], positions: list[int], layers: list[int], steering: object) -> str:
    """The same bytes as `wsbench.produce.store.Located.key` (a test holds the two equal)."""
    blob = json.dumps(
        {"ids": ids, "positions": positions, "layers": layers, "steering": steering},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def folder_items(index: dict) -> dict[str, list[tuple[int, int]]]:
    """item id -> its (layer, position) rows, in the dataset's row order."""
    out: dict[str, list[tuple[int, int]]] = {}
    cells = index["cells"]
    for i, layer, pos in zip(cells["id"], cells["layer"], cells["pos"], strict=True):
        out.setdefault(index["items"][i], []).append((int(layer), int(pos)))
    return out


def build(dataset: Path, out: Path) -> None:
    from transformers import AutoTokenizer

    from wsbench import readplan, registry
    from wsbench.produce.producer import _positions
    from wsbench.produce.render import render

    registry.load_all()
    manifest = json.loads((dataset / "manifest.json").read_text())
    tok = AutoTokenizer.from_pretrained(manifest["model"], revision=manifest["revision"])
    evals: dict[str, dict] = {}
    for index_path in sorted(dataset.glob("*/*/index.json")):
        variant, name = index_path.parts[-3], index_path.parts[-2]
        have = folder_items(json.loads(index_path.read_text()))
        specs = readplan.plan(name, fast=True) if variant == "fast" else readplan.plan(name)
        keys, differ = {}, 0
        for s in specs:
            if s.id not in have or (s.render == "captured" and "input_ids" not in s.extra):
                continue
            r = render(s, tok)
            fast_of = s.positions.get("kind") == "fast_of"
            pos = [int(p) for p in _positions(s.positions, r.decoded if fast_of else r.tokens)]
            layers = [int(x) for x in s.layers]
            if have[s.id] != [(la, p) for la in layers for p in pos]:
                differ += 1  # the dataset's rows are not this plan's rows: not usable
                continue
            steering = (s.extra or {}).get("steering") or None
            keys[s.id] = item_key([int(x) for x in r.ids], pos, layers, steering)
        evals[f"{variant}/{name}"] = {"items": keys, "not_the_plans_rows": differ}
        print(f"{variant}/{name}: {len(keys)} of {len(have)} items keyed, {differ} differ")
    capture = manifest.get("capture_dtype", "bf16")
    part = {
        "capture": capture,
        "model": manifest["model"],
        "model_revision": manifest["revision"],
        "bench_commit": manifest["bench_commit"],
        "folders": evals,
    }
    out.write_text(json.dumps(part))


SUBDIR = {"fp32": "float32-capture", "bf16": ""}  # where each capture lives in the dataset


def merge(parts: list[Path], out: Path, repo: str, revision: str) -> None:
    """The map: one entry per capture. An item of a `fast/` folder that a `full/` folder holds
    under the same key is left out (one place per item is enough)."""
    captures = {}
    for p in parts:
        part = json.loads(p.read_text())
        full = {
            (name, key)
            for folder, info in part["folders"].items()
            if folder.startswith("full/")
            for name, key in info["items"].items()
        }
        folders = {}
        for folder, info in sorted(part["folders"].items()):
            items = {
                name: key
                for name, key in sorted(info["items"].items())
                if folder.startswith("full/") or (name, key) not in full
            }
            if items:
                folders[folder] = {"items": items}
        captures[part["capture"]] = {
            "subdir": SUBDIR[part["capture"]],
            "model": part["model"],
            "model_revision": part["model_revision"],
            "bench_commit": part["bench_commit"],
            "folders": folders,
        }
    text = json.dumps({"repo": repo, "revision": revision, "captures": captures}, sort_keys=True)
    out.write_text(text + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "merge":
        *part_files, target, dataset_repo, dataset_revision = sys.argv[2:]
        merge([Path(p) for p in part_files], Path(target), dataset_repo, dataset_revision)
    else:
        build(Path(sys.argv[1]), Path(sys.argv[2]))
