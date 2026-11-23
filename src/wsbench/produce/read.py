"""Read evals with a served lens: plan rows -> cells from the residual store -> one engine
decode per pack of evals -> one readouts file per eval with its sidecar (`docs/fast_path.md`)."""

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wsbench import fast as fast_mod
from wsbench import reads as reads_mod
from wsbench.readouts import sidecar_path, write_sidecar
from wsbench.readplan import ReadSpec

from . import store as st


@dataclass(frozen=True)
class Job:
    """One eval to read: its plan rows and what its readouts file declares about them."""

    family: str
    specs: list[ReadSpec]
    plan_sha: str
    reads: str = "full"
    fast: bool = False  # the rows are the fast subset's plan


def job(family: str, specs: Sequence[ReadSpec], *, reads: str = "full", fast: bool = False) -> Job:
    """A registered eval's job, with the plan hash the judge compares against."""
    sha = reads_mod.fast_plan_sha(family) if fast else reads_mod.plan_sha(family)
    return Job(family, list(specs), sha, reads, fast)


def plan_file_jobs(path: Path) -> list[Job]:
    """Jobs for a plan file (any cell list in the plan's row format): the hash is the file's
    rows', so whoever wrote the plan can check the readouts against it."""
    return [
        Job(family, specs, reads_mod.plan_sha_rows(s.row() for s in specs))
        for family, specs in st.read_plan_file(path).items()
    ]


def open_engine(name: str, lens: Path, **options: Any) -> tuple[Any, Any]:
    """The lens bundle at ``lens`` and a loaded engine for it (``served.engine.load``)."""
    from .served import bundle as bundle_mod
    from .served import engine as engine_mod

    bundle = bundle_mod.load(lens)
    return bundle, engine_mod.load(name, bundle, **options)


def row(cell: st.Cell, samples: list[str]) -> str:
    """One readouts line in the benchmark's contract. U+2028 / U+2029 are escaped, because the
    loader splits lines at them."""
    obj = {"id": cell.id, "layer": cell.layer, "pos": cell.pos, "token": cell.token}
    text = json.dumps({**obj, "samples": samples}, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    os.replace(tmp, path)


def part_path(out: Path, family: str, shard: int, shards: int) -> Path:
    """Where one process writes an eval's rows: the readouts file itself, or with several
    processes (one per GPU) its own part under ``parts/``."""
    if shards == 1:
        return out / f"{family}.jsonl"
    return out / "parts" / f"{family}.{shard}of{shards}.jsonl"


def finish(out: Path, j: Job, shards: int, *, reader: str, sampling: str) -> bool:
    """Write the eval's sidecar once every part is there (joining the parts first when several
    processes read it). The sidecar is written last, so `wsbench run wait=` never judges a
    file that is still growing. Returns whether the eval is complete."""
    target = out / f"{j.family}.jsonl"
    if shards > 1:
        parts = [part_path(out, j.family, i, shards) for i in range(shards)]
        if not all(p.exists() for p in parts):
            return False
        lines = [x for p in parts for x in p.read_text(encoding="utf-8").splitlines() if x]
        _write(target, lines)
    write_sidecar(
        target,
        reads=j.reads,
        sampling=sampling,
        reader=reader,
        arm=reader,
        layers=sorted({int(x) for s in j.specs for x in s.layers}),
        plan_sha=j.plan_sha,
        **({"fast": fast_mod.VERSION} if j.fast else {}),
    )
    return True


def read_evals(
    jobs: Sequence[Job],
    engine: Any,
    store: st.Store,
    tokenizer: Any,
    out: Path,
    *,
    reader: str,
    sampling: str,
    pull: Any = None,
    subject: Any = None,
    pack_cells: int = 60_000,
    shard: int = 0,
    shards: int = 1,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Read every job that has no readouts yet and return one summary per eval. Cells come
    from the residual store (then ``pull``, then ``subject``); evals are decoded in packs of up
    to ``pack_cells`` cells, one ``engine.decode`` per pack, so small evals share a server
    start; each eval's file is written when its pack is decoded."""
    done: list[dict[str, Any]] = []
    todo: list[tuple[Job, Path]] = []
    for j in jobs:
        target = part_path(out, j.family, shard, shards)
        ready = target.exists() and (shards > 1 or sidecar_path(target).exists())
        if ready:
            finish(out, j, shards, reader=reader, sampling=sampling)
            done.append({"family": j.family, "status": "exists", "file": str(target)})
        else:
            todo.append((j, target))
    # every eval's cells first (the subject model, if it has to run, runs before the engine)
    loaded = []
    for j, target in todo:
        part = st.shard(j.specs, shard, shards)[: limit or None]
        cells, counts = st.cells_for(store, j.family, part, tokenizer, pull=pull, backend=subject)
        print(counts.line(j.family), flush=True)
        loaded.append((j, target, cells, counts))
    if subject is not None and hasattr(subject, "release"):
        subject.release()  # the engine needs the GPU the subject model was on
    pack: list[tuple[Job, Path, list[st.Cell], st.Counts]] = []

    def flush() -> None:
        cells = [c for _, _, part, _ in pack for c in part]
        texts = engine.decode(cells) if cells else []
        lo = 0
        for j, target, part, counts in pack:
            lines = [row(c, t) for c, t in zip(part, texts[lo : lo + len(part)], strict=True)]
            lo += len(part)
            _write(target, lines)
            complete = finish(out, j, shards, reader=reader, sampling=sampling)
            done.append(
                {
                    "family": j.family,
                    "status": "read",
                    "file": str(target),
                    "cells": len(part),
                    "from_store": counts.store,
                    "pulled": counts.pulled,
                    "captured": counts.captured,
                    "forward_passes": counts.forwards,
                    "complete": complete,
                }
            )
            print(f"{j.family}: {len(part)} cells read -> {target}", flush=True)
        pack.clear()

    for item in loaded:
        if pack and sum(len(p[2]) for p in pack) + len(item[2]) > pack_cells:
            flush()
        pack.append(item)
    if pack:
        flush()
    return done
