"""The published residuals as a source for the residual store: `Residuals` is the `pull` of
`store.cells_for`. An item is taken only when the key recorded for it in `evals/residuals/map.json`
equals the plan's key today, so a prompt that changed since the capture is never read from it."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wsbench.registry import REPO_ROOT

from .store import Item, Located

REPO = "agu18dec/workspacebench_residuals"
MAP = REPO_ROOT / "evals/residuals/map.json"

# a file of the dataset, by its path inside the repository -> a local path
Fetch = Callable[[str], Path]


def load_map(path: Path = MAP) -> dict[str, Any]:
    """The map of the published residuals: per capture dtype, the dataset folders and, per
    item, the store key it had at the benchmark commit the capture was made on."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hub_fetch(repo: str, revision: str, cache_dir: Path | None = None) -> Fetch:
    """Download files of a Hugging Face dataset at a pinned revision (cached by the hub)."""

    def fetch(path: str) -> Path:
        from huggingface_hub import hf_hub_download

        return Path(
            hf_hub_download(repo, path, repo_type="dataset", revision=revision, cache_dir=cache_dir)
        )

    return fetch


def local_fetch(root: Path) -> Fetch:
    """Read a copy of the dataset that is already on disk (a snapshot folder, a mirror)."""
    return lambda path: Path(root) / path


@dataclass
class Residuals:
    """The dataset for one capture dtype and model revision. ``residuals(family, missing)``
    returns the stored items among ``missing`` whose recorded key equals the plan's."""

    dtype: str
    model_revision: str
    fetch: Fetch
    map: dict[str, Any] = field(default_factory=load_map, repr=False)
    downloaded: list[str] = field(default_factory=list)  # every file fetched, in order
    _where: dict[str, list[tuple[str, str]]] | None = field(default=None, repr=False)
    _index: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    @property
    def capture(self) -> dict[str, Any] | None:
        """This dtype's entry of the map, or None when the dataset has no capture of this
        dtype for this model revision (nothing can be pulled then)."""
        entry = self.map.get("captures", {}).get(self.dtype)
        if entry is None or entry["model_revision"] != self.model_revision:
            return None
        return entry

    def where(self, item: str) -> list[tuple[str, str]]:
        """The (folder, key) pairs under which the dataset holds an item id."""
        if self._where is None:
            self._where = {}
            for folder, info in (self.capture or {"folders": {}})["folders"].items():
                for name, key in info["items"].items():
                    self._where.setdefault(name, []).append((folder, key))
        return self._where.get(item, [])

    def folder_of(self, at: Located) -> str | None:
        """The dataset folder that holds this item under the plan's own key, if any."""
        return next((folder for folder, key in self.where(at.spec.id) if key == at.key), None)

    def _get(self, path: str) -> Path:
        capture = self.capture
        assert capture is not None
        full = f"{capture['subdir']}/{path}" if capture["subdir"] else path
        self.downloaded.append(full)
        return self.fetch(full)

    def _rows(self, folder: str) -> dict[str, Any]:
        """A folder's index: per item its row numbers, and the parts' row offsets."""
        if folder not in self._index:
            meta = json.loads(self._get(f"{folder}/index.json").read_text(encoding="utf-8"))
            cells, rows = meta["cells"], {}
            for n, i in enumerate(cells["id"]):
                rows.setdefault(meta["items"][i], []).append(n)
            starts = [0]
            for part in meta["parts"]:
                starts.append(starts[-1] + int(part["rows"]))
            self._index[folder] = {"meta": meta, "rows": rows, "starts": starts}
        return self._index[folder]

    def __call__(self, family: str, missing: Sequence[Located]) -> list[Item]:
        import torch
        from safetensors.torch import load_file

        by_folder: dict[str, list[Located]] = {}
        for at in missing:
            folder = self.folder_of(at)
            if folder is not None:
                by_folder.setdefault(folder, []).append(at)
        items = []
        for folder, wanted in by_folder.items():
            index = self._rows(folder)
            cells, starts, parts = index["meta"]["cells"], index["starts"], index["meta"]["parts"]
            want = {}
            for at in wanted:
                rows = index["rows"].get(at.spec.id, [])
                have = [(int(cells["layer"][n]), int(cells["pos"][n])) for n in rows]
                if have == [(la, p) for la, p, _ in at.rows]:  # else the map is not this folder's
                    want[at.spec.id] = (at, rows)
            acts: dict[str, list[Any]] = {name: [] for name in want}
            for k, part in enumerate(parts):  # one part file in memory at a time
                lo, hi = starts[k], starts[k + 1]
                take = {
                    name: [n - lo for n in rows if lo <= n < hi] for name, (_, rows) in want.items()
                }
                if not any(take.values()):
                    continue
                table = load_file(str(self._get(f"{folder}/{part['file']}")))["acts"]
                for name, local in take.items():
                    if local:
                        acts[name].append(table[torch.tensor(local)])
            for name, (at, _) in want.items():
                if at.rows:
                    items.append(Item(name, at.key, at.rows, torch.cat(acts[name])))
        return items


def source(dataset: str, revision: str, dtype: str, model_revision: str) -> Residuals | None:
    """The pull for a `dataset=` key: a Hugging Face dataset id (at `revision`, default the
    map's pinned one), a local folder holding a copy, or `none` for no dataset."""
    if dataset in ("", "none"):
        return None
    mapping = load_map()
    if Path(dataset).is_dir():
        fetch = local_fetch(Path(dataset))
    else:
        fetch = hub_fetch(dataset, revision or mapping["revision"])
    return Residuals(dtype, model_revision, fetch, mapping)


def write_folder(folder: Path, items: Sequence[Item], part_rows: int = 120_000) -> dict[str, Any]:
    """Write items as one dataset folder (`part-NNN.safetensors` + `index.json`): the published
    layout, which holds vectors, item ids, layers and positions only (no text, no tokens)."""
    import torch
    from safetensors.torch import save_file

    folder.mkdir(parents=True, exist_ok=True)
    names = [i.id for i in items]
    cells: dict[str, list[int]] = {"id": [], "layer": [], "pos": []}
    for n, item in enumerate(items):
        for layer, pos, _ in item.rows:
            cells["id"].append(n)
            cells["layer"].append(layer)
            cells["pos"].append(pos)
    acts = torch.cat([i.acts.to(torch.bfloat16) for i in items if i.rows])
    parts = []
    for lo in range(0, acts.shape[0], part_rows):
        name = f"part-{len(parts):03d}.safetensors"
        chunk = acts[lo : lo + part_rows].contiguous()
        save_file({"acts": chunk}, str(folder / name))
        parts.append({"file": name, "rows": int(chunk.shape[0])})
    meta = {"parts": parts, "items": names, "cells": cells}
    (folder / "index.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta
