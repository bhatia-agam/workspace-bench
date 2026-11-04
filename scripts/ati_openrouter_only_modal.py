"""ATI panel answers from the hosted readers (astra, argon) over OpenRouter only, from Modal.

The request and retry rules of ``scripts/ati_openrouter_modal.py`` (``ati_remote.answer_one``,
route ``openrouter``), binding only the ``openrouter`` secret, with a cap on HTTP attempts.
Usage: evals/baselines/README.md ("Running the panel with only an OpenRouter secret").
"""

import json
import time
from pathlib import Path

import modal

app = modal.App("wsb-ati-openrouter-only")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("openai>=1.60", "httpx")
    .add_local_python_source("wsbench")
)
CONCURRENCY = 16  # per container, as ati_openrouter_modal.py


@app.function(image=image, secrets=[modal.Secret.from_name("openrouter")], timeout=3 * 3600)
def answer_shard(model: str, reqs: list[dict], cap: int) -> dict:
    """Answer ``reqs`` with at most ``cap`` HTTP attempts (retries and 429 waits included): at
    the cap the shard stops (``AbortError``) and returns what it has."""
    import asyncio

    from wsbench.baselines import ati_remote as ar

    n_http = 0
    real_create = ar._create

    async def counted_create(client, route, kwargs):
        nonlocal n_http
        if n_http >= cap:
            raise ar.AbortError(f"call cap {cap} reached in this shard")
        n_http += 1
        return await real_create(client, route, kwargs)

    ar._create = counted_create

    async def run() -> tuple[list[dict], str]:
        clients = ar.Clients("openrouter")
        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [asyncio.create_task(ar.answer_one(clients, sem, model, r)) for r in reqs]
        rows, why = [], ""
        try:
            for fut in asyncio.as_completed(tasks):
                rows.append(await fut)
        except ar.AbortError as exc:
            why = str(exc)[:300]
        finally:
            for t in tasks:
                t.cancel()
        return rows, why

    rows, why = asyncio.run(run())
    return {"rows": rows, "n_http": n_http, "abort": why}


@app.local_entrypoint()
def main(
    answerer: str,
    out: str,
    families: str = "",
    draws: int = 3,
    shards: int = 4,
    cap: int = 2000,
) -> None:
    """``cap`` = HTTP attempts over all shards (each shard gets ``cap // shards``)."""
    from wsbench.baselines import text_inversion as ti

    if answerer not in ti.OPENROUTER_ANSWERERS:
        raise SystemExit(f"answerer must be one of {sorted(ti.OPENROUTER_ANSWERERS)}")
    model = ti.PANEL[answerer]
    out_p = Path(out)
    fams = {f for f in families.split(",") if f} or None
    reqs = ti.pending_requests(out_p, answerer, draws, fams)
    print(f"{answerer} ({model}, openrouter): {len(reqs)} requests pending", flush=True)
    if not reqs:
        return
    k = max(1, min(shards, len(reqs)))
    parts = [reqs[i::k] for i in range(k)]
    t0 = time.time()
    results = list(answer_shard.starmap([(model, p, cap // k) for p in parts]))
    rows = [r for res in results for r in res["rows"]]
    print(ti.append_answers(out_p, answerer, rows), flush=True)
    meta = {
        "answerer": answerer,
        "model": model,
        "route": "openrouter",
        "requests": len(reqs),
        "rows": len(rows),
        "n_http": sum(res["n_http"] for res in results),
        "aborts": [res["abort"] for res in results if res["abort"]],
        "n_error_rows": sum(1 for r in rows if r.get("error") and not r.get("refused")),
        "n_refused": sum(1 for r in rows if r.get("refused")),
        "wall_s": round(time.time() - t0, 1),
    }
    with (out_p / "or_runs.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta) + "\n")
    print(json.dumps(meta), flush=True)
