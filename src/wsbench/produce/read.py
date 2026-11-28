"""Read evals with a served lens: plan rows -> cells from the residual store -> one engine
decode per pack of evals -> one readouts file per eval with its sidecar (`docs/fast_path.md`)."""

import json
import os
import time
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
    fast: bool = False  # the rows are the fast subset's plan


def job(family: str, specs: Sequence[ReadSpec], *, fast: bool = False) -> Job:
    """A registered eval's job, with the plan hash the judge compares against."""
    sha = reads_mod.fast_plan_sha(family) if fast else reads_mod.plan_sha(family)
    return Job(family, list(specs), sha, fast)


def plan_file_jobs(path: Path) -> list[Job]:
    """Jobs for a plan file (any cell list in the plan's row format): the hash is the file's
    rows', so whoever wrote the plan can check the readouts against it."""
    return [
        Job(family, specs, reads_mod.plan_sha_rows(s.row() for s in specs))
        for family, specs in st.read_plan_file(path).items()
    ]


def load_bundle(lens: Path) -> Any:
    """The lens bundle at ``lens`` (``served.bundle.load``): its name, sampling, prompts."""
    from .served import bundle as bundle_mod

    return bundle_mod.load(lens)


def open_engine(name: str, lens: Path, **options: Any) -> tuple[Any, Any]:
    """The lens bundle at ``lens`` and a loaded engine for it (``served.engine.load``)."""
    from .served import engine as engine_mod

    bundle = load_bundle(lens)
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
        reads=reads_mod.READS,
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
        t0 = time.time()
        texts = engine.decode(cells) if cells else []
        seconds = time.time() - t0
        # the engine keeps the token ids of its last decode, one list per readout row
        rows = getattr(engine, "tokens", None) or []
        per_cell = len(rows) // len(cells) if cells and len(rows) % len(cells) == 0 else 0
        lo = 0
        for j, target, part, counts in pack:
            lines = [row(c, t) for c, t in zip(part, texts[lo : lo + len(part)], strict=True)]
            mine = rows[lo * per_cell : (lo + len(part)) * per_cell] if per_cell else []
            lo += len(part)
            _write(target, lines)
            complete = finish(out, j, shards, reader=reader, sampling=sampling)
            share = seconds * len(part) / len(cells) if cells else 0.0
            done.append(
                {
                    "family": j.family,
                    "status": "read",
                    "file": str(target),
                    "cells": len(part),
                    "tokens": sum(len(r) for r in mine),
                    # this eval's share, by cells, of its pack's decode time (server start,
                    # token bank and requests); evals of one pack are decoded together
                    "seconds": round(share, 1),
                    "pack_cells": len(cells),
                    "pack_seconds": round(seconds, 1),
                    "from_store": counts.store,
                    "pulled": counts.pulled,
                    "captured": counts.captured,
                    "forward_passes": counts.forwards,
                    "complete": complete,
                }
            )
            print(
                f"{j.family}: {len(part)} cells read, {done[-1]['tokens']} tokens, "
                f"{share:.0f} s of a {seconds:.0f} s pack -> {target}",
                flush=True,
            )
        pack.clear()

    for item in loaded:
        if pack and sum(len(p[2]) for p in pack) + len(item[2]) > pack_cells:
            flush()
        pack.append(item)
    if pack:
        flush()
    return done


def read_continuations(
    jobs: Sequence[Job],
    engine: Any,
    out: Path,
    *,
    reader: str,
    layer: int,
    pack_prompts: int = 60_000,
    shard: int = 0,
    shards: int = 1,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """The model-continuation baseline over jobs: one readout per (item, read position), written
    at the single layer number ``layer`` (the baseline has no layer axis). No activation and no
    store is involved; ``engine`` is a ``served.continuation.ContinuationEngine``. Files, parts
    and sidecars are as ``read_evals`` writes them, with ``layers`` = ``[layer]``."""
    from .served import continuation

    done: list[dict[str, Any]] = []
    pack: list[tuple[Job, Path, list[Any]]] = []

    def flush() -> None:
        texts = engine.decode([p.ids for _, _, part in pack for p in part])
        lo = 0
        for j, target, part in pack:
            cells = [st.Cell(p.id, layer, p.pos, p.token, None) for p in part]
            lines = [row(c, [t]) for c, t in zip(cells, texts[lo : lo + len(part)], strict=True)]
            lo += len(part)
            _write(target, lines)
            finish(out, one_layer(j, layer), shards, reader=reader, sampling="prose1")
            done.append(
                {"family": j.family, "status": "read", "file": str(target), "cells": len(part)}
            )
            print(f"{j.family}: {len(part)} continuations read -> {target}", flush=True)
        pack.clear()

    for j in jobs:
        target = part_path(out, j.family, shard, shards)
        if target.exists() and (shards > 1 or sidecar_path(target).exists()):
            done.append({"family": j.family, "status": "exists", "file": str(target)})
            continue
        specs = st.shard(j.specs, shard, shards)[: limit or None]
        part = continuation.prompts_of(specs, engine.tok)
        if pack and sum(len(p[2]) for p in pack) + len(part) > pack_prompts:
            flush()
        pack.append((j, target, part))
    if pack:
        flush()
    return done


def _at_layer(spec: ReadSpec, layer: int) -> ReadSpec:
    import dataclasses

    return dataclasses.replace(spec, layers=[layer])


def missing(
    jobs: Sequence[Job],
    store: st.Store,
    tokenizer: Any,
    pull: Any = None,
    *,
    shard: int = 0,
    shards: int = 1,
    limit: int = 0,
) -> dict[str, int]:
    """Per eval, how many items are neither in the store nor in the dataset: the ones only a
    forward pass of the subject model can supply. Reads indexes only."""
    out: dict[str, int] = {}
    for j in jobs:
        located = [
            st.locate(s, tokenizer) for s in st.shard(j.specs, shard, shards)[: limit or None]
        ]
        stored = store.has(j.family, {at.spec.id: at.key for at in located})
        rest = [at for at in located if at.spec.id not in stored]
        n = sum(1 for at in rest if pull is None or pull.folder_of(at) is None)
        if n:
            out[j.family] = n
    return out


def join(
    jobs: Sequence[Job], out: Path, shards: int, *, reader: str, sampling: str
) -> list[dict[str, Any]]:
    """Write every eval's readouts file and sidecar from the parts under ``<out>/parts``: the
    step after ``shards`` processes that could not see each other's files (one container per
    GPU). An eval whose parts are not all there is reported, and nothing is written for it."""
    done = []
    for j in jobs:
        parts = [part_path(out, j.family, i, shards) for i in range(shards)]
        lacking = [p.name for p in parts if not p.exists()]
        if lacking:
            done.append({"family": j.family, "status": "incomplete", "missing_parts": lacking})
            continue
        finish(out, j, shards, reader=reader, sampling=sampling)
        rows = sum(1 for _ in (out / f"{j.family}.jsonl").open(encoding="utf-8"))
        done.append({"family": j.family, "status": "joined", "rows": rows})
    return done


def totals(done: Sequence[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    """One summary of a call's reads: cells, readout tokens, decode seconds and the rates."""
    read_rows = [d for d in done if d.get("status") == "read"]
    packs = {(d["pack_cells"], d["pack_seconds"]) for d in read_rows}
    cells = sum(d["cells"] for d in read_rows)
    tokens = sum(d["tokens"] for d in read_rows)
    decode = sum(seconds for _, seconds in packs)
    return {
        "evals_read": len(read_rows),
        "cells": cells,
        "tokens": tokens,
        "packs": len(packs),
        "decode_seconds": round(decode, 1),
        "wall_seconds": round(wall_seconds, 1),
        "cells_per_second": round(cells / decode, 1) if decode else 0.0,
        "tokens_per_second": round(tokens / decode, 1) if decode else 0.0,
        "forward_passes": sum(d["forward_passes"] for d in read_rows),
    }


def stats_path(out: Path, shard: int, shards: int) -> Path:
    """Where a read saves its timing: `<out>/read_stats.json`, or one file per process."""
    if shards == 1:
        return out / "read_stats.json"
    return out / "parts" / f"read_stats.{shard}of{shards}.json"


ENGINE_SECONDS = ("bank_seconds", "server_start_seconds", "request_seconds")


def sum_stats(parts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The saved timing of several processes (one per shard) as one: the totals summed, the
    per-eval rows summed by eval, and each shard's own line. ``gpu_seconds`` is the sum of
    the processes' wall-clock (a process holds its GPU from start to end); ``wall_seconds``
    is the longest of them, since they ran side by side."""
    shards = [p["total"] for p in parts]
    keys = ("evals_read", "cells", "tokens", "packs", "decode_seconds", "forward_passes")
    total: dict[str, Any] = {k: round(sum(t.get(k, 0) for t in shards), 1) for k in keys}
    total["evals_read"] = len(
        {d["family"] for p in parts for d in p["evals"] if d["status"] == "read"}
    )
    total["shards"] = len(parts)
    total["gpu_seconds"] = round(sum(t.get("wall_seconds", 0.0) for t in shards), 1)
    total["wall_seconds"] = round(max((t.get("wall_seconds", 0.0) for t in shards), default=0.0), 1)
    for key in ENGINE_SECONDS:
        if any(key in (t.get("engine") or {}) for t in shards):
            total[key] = round(sum((t.get("engine") or {}).get(key, 0.0) for t in shards), 1)
    decode = total["decode_seconds"]
    total["cells_per_second"] = round(total["cells"] / decode, 1) if decode else 0.0
    total["tokens_per_second"] = round(total["tokens"] / decode, 1) if decode else 0.0
    evals: dict[str, dict[str, Any]] = {}
    for p in parts:
        for d in p["evals"]:
            if d["status"] != "read":
                continue
            e = evals.setdefault(d["family"], {"family": d["family"], "status": "read"})
            for k in (
                "cells",
                "tokens",
                "seconds",
                "from_store",
                "pulled",
                "captured",
                "forward_passes",
            ):
                e[k] = round(e.get(k, 0) + d.get(k, 0), 1)
    return {"total": total, "shards": shards, "evals": list(evals.values())}


def one_layer(j: Job, layer: int) -> Job:
    """The job as a layer-free method writes it: every row at the one layer number."""
    return Job(j.family, [_at_layer(s, layer) for s in j.specs], j.plan_sha, j.fast)
