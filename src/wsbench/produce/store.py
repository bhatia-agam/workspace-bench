"""The residual store: subject activations at a read plan's cells, captured once and read by
every readout method. Items are stored with a key (token ids, positions, layers, steering), so
a vector is only handed out for the prompt it was captured at (`docs/producing_readouts.md`)."""

import hashlib
import json
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wsbench.readplan import ReadSpec

DTYPES = ("fp32", "bf16")  # the subject's dtype during capture; vectors are stored as bf16
TORCH_DTYPE = {"fp32": "float32", "bf16": "bfloat16"}


class StoreError(RuntimeError):
    """The store cannot serve what was asked (a missing item with no way to get it, a pack
    written for another model or dtype, rows that are not the plan's)."""


class NoPromptError(StoreError):
    """A plan row that ships no prompt (a ``captured`` render without token ids): there is
    nothing to run the subject on, so the eval cannot be captured or read from a store."""


# ---------------------------------------------------------------- cells and items


@dataclass
class Cell:
    """One activation: the residual stream after decoder block ``layer`` at token ``pos`` of
    item ``id``. ``pos`` is the position as the read plan states it (negative = from the end);
    ``token`` is ``tokenizer.decode([id])`` of the token there; ``h`` is a ``[d]`` tensor."""

    id: str
    layer: int
    pos: int
    token: str
    h: Any


@dataclass
class Item:
    """One item's stored cells: ``rows`` are (layer, position, token) and ``acts`` is the
    ``[len(rows), d]`` tensor in the same order (layers outermost, positions in plan order)."""

    id: str
    key: str
    rows: list[tuple[int, int, str]]
    acts: Any

    def cells(self) -> list[Cell]:
        return [Cell(self.id, la, p, tok, self.acts[i]) for i, (la, p, tok) in enumerate(self.rows)]


@dataclass(frozen=True)
class Located:
    """An item rendered for the subject: the prompt's token ids, the plan's positions as the
    plan states them, and the same positions as indices into the prompt."""

    spec: ReadSpec
    ids: list[int]
    positions: list[int]
    indices: list[int]
    tokens: list[str]  # the decoded token at each position

    @property
    def key(self) -> str:
        """What the item's activations depend on, hashed: token ids, positions, layers, steer."""
        steer = (self.spec.extra or {}).get("steering") or None
        blob = json.dumps(
            {
                "ids": self.ids,
                "positions": self.positions,
                "layers": [int(x) for x in self.spec.layers],
                "steering": steer,
            },
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:24]

    @property
    def rows(self) -> list[tuple[int, int, str]]:
        return [
            (int(layer), p, tok)
            for layer in self.spec.layers
            for p, tok in zip(self.positions, self.tokens, strict=True)
        ]


def locate(spec: ReadSpec, tokenizer: Any) -> Located:
    """Render ``spec`` with the benchmark's own render and resolve its position rule (the same
    two calls the bundled producer makes). A position outside the prompt is an error."""
    from .producer import _positions
    from .render import render

    if spec.render == "captured" and "input_ids" not in (spec.extra or {}):
        raise NoPromptError(f"{spec.family}/{spec.id}: the plan ships this item without a prompt")
    rendered = render(spec, tokenizer)
    fast_of = spec.positions.get("kind") == "fast_of"  # tested on decoded tokens (plan 0090)
    pos = list(_positions(spec.positions, rendered.decoded if fast_of else rendered.tokens))
    n = len(rendered)
    bad = [q for q in pos if not -n <= q < n]
    if bad:
        raise ValueError(f"{spec.family}/{spec.id}: positions {bad} outside a {n}-token prompt")
    idx = [q % n for q in pos]
    return Located(spec, list(rendered.ids), pos, idx, [rendered.decoded[j] for j in idx])


# ---------------------------------------------------------------- plans


def read_plan_file(path: Path) -> dict[str, list[ReadSpec]]:
    """A plan file (one row per line, the format ``wsbench plan`` writes) as ``{family: rows}``.
    The rows need not come from this benchmark: any cell list in this format can be captured
    and read, e.g. ``{"family": "mine", "id": "a", "render": "captured", "positions": {"kind":
    "positions", "positions": [3, 7]}, "layers": [20, 44], "extra": {"input_ids": [...]}}``."""
    out: dict[str, list[ReadSpec]] = {}
    names = set(ReadSpec.__dataclass_fields__)
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        unknown = sorted(set(row) - names)
        missing = sorted({"family", "id", "render", "positions", "layers"} - set(row))
        if unknown or missing:
            raise ValueError(f"{path}:{n}: not a plan row (unknown {unknown}, missing {missing})")
        out.setdefault(row["family"], []).append(ReadSpec(**row))
    for family, specs in out.items():
        ids = [s.id for s in specs]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{path}: {family} lists an item id twice")
    return out


def shard(specs: Sequence[ReadSpec], index: int = 0, n: int = 1) -> list[ReadSpec]:
    """Every ``n``-th item from ``index`` of the plan sorted by id: how a plan is split over
    several GPUs. ``shard(specs)`` is the whole plan in that order."""
    if not 0 <= index < n:
        raise ValueError(f"shard {index} of {n}")
    return sorted(specs, key=lambda s: s.id)[index::n]


# ---------------------------------------------------------------- the store on disk


@dataclass(frozen=True)
class Store:
    """A residual store for one subject model revision and one capture dtype."""

    root: Path
    revision: str
    dtype: str = "fp32"

    def __post_init__(self) -> None:
        if self.dtype not in DTYPES:
            raise ValueError(f"dtype is one of {DTYPES}, not {self.dtype!r}")
        if len(self.revision) < 12:
            raise ValueError(
                f"the store is keyed by the subject model's revision sha, got {self.revision!r}"
            )

    def folder(self, family: str) -> Path:
        return Path(self.root) / self.revision[:12] / self.dtype / family

    def write(self, family: str, items: Sequence[Item], info: dict[str, Any] | None = None) -> Path:
        """One pack holding ``items``: the vectors, then the index (written last and atomically,
        so an index on disk always has its vectors)."""
        import torch
        from safetensors.torch import save_file

        folder = self.folder(family)
        folder.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256("".join(f"{i.id}:{i.key};" for i in items).encode()).hexdigest()[:16]
        stem = folder / name
        acts = torch.cat([i.acts.to(torch.bfloat16) for i in items])
        tmp = stem.with_name(f"{name}.{os.getpid()}.tmp")
        save_file({"acts": acts.contiguous()}, str(tmp))
        os.replace(tmp, stem.with_suffix(".safetensors"))
        start, index = 0, []
        for i in items:
            index.append({"id": i.id, "key": i.key, "start": start, "rows": i.rows})
            start += len(i.rows)
        meta = {
            "revision": self.revision,
            "dtype": self.dtype,
            "family": family,
            "info": info or {},
            "items": index,
        }
        tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, stem.with_suffix(".json"))
        return stem

    def has(self, family: str, want: dict[str, str]) -> set[str]:
        """The ids among ``want`` (item id -> key) that are stored under that key (reads the
        indexes only, no vectors)."""
        out: set[str] = set()
        for path in sorted(self.folder(family).glob("*.json")):
            for e in json.loads(path.read_text(encoding="utf-8"))["items"]:
                if want.get(e["id"]) == e["key"]:
                    out.add(e["id"])
        return out

    def find(self, family: str, want: dict[str, str]) -> tuple[dict[str, Item], list[str]]:
        """The stored items among ``want`` (item id -> key), and the ids that are stored under
        another key only (refused: their vectors belong to another prompt, plan or layer set).
        A pack written for another revision or dtype than its folder says is an error."""
        from safetensors import safe_open

        found: dict[str, Item] = {}
        other: set[str] = set()
        for path in sorted(self.folder(family).glob("*.json")):
            meta = json.loads(path.read_text(encoding="utf-8"))
            if (meta.get("revision"), meta.get("dtype")) != (self.revision, self.dtype):
                raise StoreError(
                    f"{path}: written for revision {meta.get('revision')!r}, capture dtype "
                    f"{meta.get('dtype')!r}; this store is {self.revision!r}, {self.dtype!r}"
                )
            hits = [e for e in meta["items"] if e["id"] in want and e["id"] not in found]
            other |= {e["id"] for e in hits if e["key"] != want[e["id"]]}
            hits = [e for e in hits if e["key"] == want[e["id"]]]
            if not hits:
                continue
            # only the wanted items' rows are read from the file, not the whole pack
            with safe_open(str(path.with_suffix(".safetensors")), framework="pt") as fh:
                acts = fh.get_slice("acts")
                for e in hits:
                    rows = [(int(la), int(p), str(tok)) for la, p, tok in e["rows"]]
                    part = acts[e["start"] : e["start"] + len(rows)] if rows else None
                    found[e["id"]] = Item(e["id"], e["key"], rows, part)
        return found, sorted(other - set(found))


# ---------------------------------------------------------------- capture


def capture(located: Sequence[Located], backend: Any) -> list[Item]:
    """One forward pass of the subject model per item (``backend``: a ``produce.Backend``),
    under the item's steering when the plan row carries one."""
    import torch

    from .producer import Producer

    steer = Producer(backend=backend, method=None)  # type: ignore[arg-type]  # .steering only
    items = []
    for at in located:
        if not at.positions:
            items.append(Item(at.spec.id, at.key, [], torch.zeros(0, 1)))
            continue
        layers = [int(x) for x in at.spec.layers]
        with steer.steering(at.spec):
            acts = backend.capture(at.ids, layers, at.indices)
        items.append(Item(at.spec.id, at.key, at.rows, torch.cat([acts[la] for la in layers])))
    return items


@dataclass
class Subject:
    """The subject model for ``cells_for``, loaded on the first forward pass it is asked for:
    a run whose cells are all stored loads the tokenizer only. ``loads`` counts model loads."""

    model: str
    revision: str
    dtype: str = "fp32"
    device: str = "cuda"
    loads: int = 0
    _tokenizer: Any = field(default=None, repr=False)
    _backend: Any = field(default=None, repr=False)

    @property
    def tokenizer(self) -> Any:
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model, revision=self.revision)
        return self._tokenizer

    @property
    def backend(self) -> Any:
        if self._backend is None:
            from .backend import Backend

            self._backend = Backend.load(
                self.model,
                device=self.device,
                dtype=TORCH_DTYPE[self.dtype],
                revision=self.revision,
            )
            self.loads += 1
        return self._backend

    def capture(self, ids: list[int], layers: list[int], positions: list[int]) -> dict[int, Any]:
        return self.backend.capture(ids, layers, positions)

    def steered(self, *args: Any, **kwargs: Any) -> Any:
        return self.backend.steered(*args, **kwargs)


# ---------------------------------------------------------------- the one way to get cells

Pull = Callable[[str, Sequence[Located]], list[Item]]


@dataclass
class Counts:
    """Where an eval's cells came from, and what was refused."""

    store: int = 0  # cells read from the local store
    pulled: int = 0  # cells fetched from the published dataset (and written to the store)
    captured: int = 0  # cells from a fresh forward pass of the subject (written to the store)
    refused: int = 0  # items the store holds under another key; fetched again, never read
    forwards: int = 0  # subject forward passes this call made
    notes: list[str] = field(default_factory=list)

    def line(self, family: str) -> str:
        total = self.store + self.pulled + self.captured
        text = (
            f"{family}: {total} cells = {self.store} from the store + {self.pulled} pulled "
            f"from the dataset + {self.captured} captured ({self.forwards} forward passes)"
        )
        if self.refused:
            text += f"; {self.refused} stored item(s) refused (stored for another plan)"
        return text


def cells_for(
    store: Store,
    family: str,
    specs: Iterable[ReadSpec],
    tokenizer: Any,
    *,
    pull: Pull | None = None,
    backend: Any = None,
) -> tuple[list[Cell], Counts]:
    """The cells of ``specs`` in plan order (items as given; within an item layers outermost),
    from the store, else from ``pull``, else from a forward pass with ``backend``. Without a
    backend a cell that is in neither place is an error that names the items."""
    located = [locate(s, tokenizer) for s in specs]
    want = {at.spec.id: at.key for at in located}
    if len(want) != len(located):
        raise ValueError(f"{family}: an item id appears twice in the plan")
    have, refused = store.find(family, want)
    counts = Counts(store=sum(len(i.rows) for i in have.values()), refused=len(refused))
    if refused:
        counts.notes.append(f"refused (stored under another key): {', '.join(refused[:5])}")
    missing = [at for at in located if at.spec.id not in have]
    if missing and pull is not None:
        pulled = [i for i in pull(family, missing) if want.get(i.id) == i.key]
        if pulled:
            store.write(family, pulled, {"source": "pulled from the published dataset"})
            have.update({i.id: i for i in pulled})
            counts.pulled = sum(len(i.rows) for i in pulled)
        missing = [at for at in missing if at.spec.id not in have]
    if missing:
        if backend is None:
            names = ", ".join(at.spec.id for at in missing[:5])
            raise StoreError(
                f"{family}: {len(missing)} item(s) are not in the residual store "
                f"({store.folder(family)}) nor in the dataset, and no subject model is loaded "
                f"to capture them: {names}{' ...' if len(missing) > 5 else ''}. "
                f"Run `wsbench capture` for this eval first."
            )
        fresh = capture(missing, backend)
        store.write(family, fresh, {"source": "captured"})
        have.update({i.id: i for i in fresh})
        counts.captured = sum(len(i.rows) for i in fresh)
        counts.forwards = sum(1 for at in missing if at.positions)
    cells: list[Cell] = []
    for at in located:
        item = have[at.spec.id]
        if item.rows != at.rows:  # the key matched, so this is a damaged pack
            raise StoreError(f"{family}/{item.id}: the stored rows are not the plan's rows")
        cells += item.cells()
    return cells, counts
