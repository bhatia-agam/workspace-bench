"""The engine interface and the SGLang engine: per batch of cells, build the token bank, start
a stock SGLang server on it, send one plain `input_ids` request row per readout, stop the
server. One bank per server lifetime, so no cache can serve another cell's activation."""

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from wsbench.produce.served.bank import build_bank, slot_rows
from wsbench.produce.served.bundle import Bundle
from wsbench.produce.served.sampling import SamplingPlan
from wsbench.produce.served.server import start_server, stop_server
from wsbench.produce.store import Cell

# `sglang.launch_server` flags the engine adds by default. They are scheduler settings, found
# by measuring one GPU type (a B200) with Qwen3.6-27B; they do not change what is sampled.
# Pass `server_args=[...]` to replace them all (a smaller GPU needs fewer running requests).
DEFAULT_SERVER_ARGS = (
    "--disable-radix-cache",  # no prefix cache: it limited how many requests ran at once
    "--mamba-ssm-dtype",  # a hybrid model's recurrent state is kept in bf16
    "bfloat16",
    "--disable-prefill-cuda-graph",  # a shorter server start
    "--max-running-requests",  # rows decoded together; bounded by GPU memory
    "768",
    "--prefill-decode-interval",  # waiting rows are admitted every 8 decode steps
    "8",
)
SAMPLERS = ("hf", "native")
LEAK_TRIES = 4  # times a row is asked again after it sampled a bank id


@dataclass
class Stats:
    """What the decodes of an engine cost so far."""

    rows: int = 0  # readouts returned
    tokens: int = 0  # tokens generated in them
    seconds: float = 0.0  # bank + server start + requests
    extra: dict[str, float] = field(default_factory=dict)  # the three parts, and re-asked rows

    def as_dict(self) -> dict[str, float]:
        return {
            "rows": self.rows,
            "tokens": self.tokens,
            "seconds": round(self.seconds, 2),
            **self.extra,
        }


class Engine(Protocol):
    """What a caller may use of an engine. Another serving stack is another class with these
    members; one that accepts prompt embeddings needs no token bank."""

    name: str
    sampler: str  # the filter order: "hf" (top-k, renormalise, top-p) or "native" (the server's)
    stats: Stats
    tokens: list[list[int]]  # the last decode's token ids, one list per readout row

    def decode(self, cells: list[Cell]) -> list[list[str]]:
        """``bundle.k`` readout strings per cell, in cell order."""

    def close(self) -> None: ...


def token_checks(rows: list[list[int]], meta: dict[str, Any]) -> dict[str, Any]:
    """Checks on a decode's token rows: the length spread and, for a bundle with a ban, the
    rows that contain a banned id or stopped before ``ban_min_new`` tokens (both must be 0)."""
    if not rows:
        return {}
    stop = set(meta["stop_ids"])
    lengths = sorted(len(r) - (1 if r and r[-1] in stop else 0) for r in rows)
    out: dict[str, Any] = {
        "length_mean": round(sum(lengths) / len(lengths), 2),
        "length_p50": lengths[len(lengths) // 2],
        "length_p90": lengths[int(0.9 * len(lengths))],
        "length_max": lengths[-1],
    }
    if meta["ban_ids"]:
        banned = set(meta["ban_ids"])
        hold = min(int(meta["ban_min_new"]), int(meta["sampling"]["max_new_tokens"]))
        out["rows_with_banned_token"] = sum(1 for r in rows if banned & set(r))
        out["rows_stopped_before_hold"] = sum(
            1 for r in rows if r and r[-1] in stop and len(r) - 1 < hold
        )
    return out


def enforce_ban(checks: dict[str, Any]) -> None:
    """A read with a ban must have no banned token and no early stop."""
    bad = {k: checks.get(k) for k in ("rows_with_banned_token", "rows_stopped_before_hold")}
    if any(bad.values()):
        raise RuntimeError(f"the token ban was violated: {bad}; no readout is returned")


def load_tokenizer(path: Path) -> Any:
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(path))


def http_client() -> Any:
    import httpx

    return httpx.AsyncClient(timeout=httpx.Timeout(3600.0))


def processor(hf_order: bool) -> str:
    """The serialised logit processor a request carries (imports sglang)."""
    from wsbench.produce.served import processors

    return (processors.HFOrderSampler() if hf_order else processors.BankMask()).to_str()


class SGLangEngine:
    """Reads cells through a local SGLang server with continuous batching. Not seeded: the
    server samples, so two decodes of the same cells differ."""

    name = "sglang"

    def __init__(
        self,
        bundle: Bundle,
        *,
        work: Path | None = None,  # scratch folder for the bank and the server log
        max_bank: int = 65536,  # cells per bank (= per server start)
        in_flight: int = 4096,  # rows the client keeps in flight: well above the server's
        post_rows: int = 32,  # rows per HTTP request
        mem_fraction: float = 0.85,  # the server's `--mem-fraction-static`
        server_args: list[str] | None = None,  # replaces DEFAULT_SERVER_ARGS
        greedy: bool = False,  # argmax instead of sampling
        sampler: str = "hf",  # "hf": HF generate's filter order; "native": the server's own
        device: str = "cuda",  # where the slot vectors are computed before the server starts
    ) -> None:
        if sampler not in SAMPLERS:
            raise ValueError(f"sampler is one of {SAMPLERS}, not {sampler!r}")
        self.bundle, self.sampler, self.greedy, self.device = bundle, sampler, greedy, device
        self.work = Path(work) if work is not None else Path(tempfile.mkdtemp(prefix="wsb-served-"))
        self.max_bank, self.in_flight, self.post_rows = max_bank, in_flight, post_rows
        self.mem_fraction = mem_fraction
        self.server_args = list(DEFAULT_SERVER_ARGS if server_args is None else server_args)
        self.tok = load_tokenizer(bundle.path)
        self.stats = Stats()
        self.tokens: list[list[int]] = []
        self.checks: dict[str, Any] = {}  # token_checks of the last decode
        self.leaks = 0  # rows asked again because they sampled a bank id
        self.version = ""  # the server's version, once a decode ran

    def __enter__(self) -> "SGLangEngine":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.work / "bank", ignore_errors=True)

    def decode(self, cells: list[Cell]) -> list[list[str]]:
        unknown = sorted({c.layer for c in cells} - set(self.bundle.layers))
        if unknown:
            raise ValueError(f"lens {self.bundle.name} has no prompt for layers {unknown}")
        texts: list[list[str]] = []
        self.tokens = []
        for lo in range(0, len(cells), self.max_bank):
            texts += self._decode_bank(cells[lo : lo + self.max_bank])
        self.checks = token_checks(self.tokens, self.bundle.meta)
        enforce_ban(self.checks)
        return texts

    def _decode_bank(self, cells: list[Cell]) -> list[list[str]]:
        meta = self.bundle.meta
        t0 = time.time()
        self.work.mkdir(parents=True, exist_ok=True)
        bank = self.work / "bank"
        base = build_bank(self.bundle.path, bank, slot_rows(meta, cells, self.device))
        if base != meta["base_vocab"]:
            raise RuntimeError(f"bank base {base} != the bundle's base_vocab {meta['base_vocab']}")
        t1 = time.time()
        proc, url = start_server(
            bank,
            self.work / "server.log",
            mem_fraction=self.mem_fraction,
            extra=["--enable-custom-logit-processor", *self.server_args],
        )
        t2 = time.time()
        try:
            out = asyncio.run(self._requests(url, cells, base))
        finally:
            stop_server(proc)
        t3 = time.time()
        x = self.stats.extra
        for key, seconds in (
            ("bank_seconds", t1 - t0),
            ("server_start_seconds", t2 - t1),
            ("request_seconds", t3 - t2),
        ):
            x[key] = round(x.get(key, 0.0) + seconds, 1)
        x["bank_leaks_resampled"] = self.leaks
        self.stats.seconds += t3 - t0
        return out

    def _params(self, base: int) -> tuple[dict[str, Any], str]:
        """The request's ``sampling_params`` and its logit processor."""
        params = SamplingPlan.of(self.bundle, greedy=self.greedy).sglang()
        params["custom_params"] = {"base_vocab": base}
        hf_order = self.sampler == "hf" and not self.greedy
        if hf_order:
            # the processor applies top-k then top-p; the server's own (joint) filter is off
            if float(params["temperature"]) != 1.0:
                raise NotImplementedError("sampler='hf' needs temperature 1.0; use 'native'")
            params["custom_params"].update(hf_top_k=params["top_k"], hf_top_p=params["top_p"])
            params.update(top_k=1 << 30, top_p=1.0)
        return params, processor(hf_order)

    async def _requests(self, url: str, cells: list[Cell], base: int) -> list[list[str]]:
        meta, k = self.bundle.meta, self.bundle.k
        params, mask = self._params(base)
        # one row per (cell, sample), ordered by layer so neighbours share a prompt
        rows = sorted(
            ((ci, j) for ci in range(len(cells)) for j in range(k)),
            key=lambda r: (cells[r[0]].layer, r[0]),
        )
        tokens: dict[tuple[int, int], list[int]] = {}
        sem = asyncio.Semaphore(max(1, self.in_flight // self.post_rows))

        def ids_for(ci: int) -> list[int]:
            p = meta["prompts"][str(cells[ci].layer)]
            ids = list(p["ids"])
            ids[p["slot"]] = base + ci  # the cell's bank row stands where the slot token was
            return ids

        async def post(client: Any, todo: list[tuple[int, int]]) -> None:
            for _attempt in range(LEAK_TRIES):
                body = {
                    "input_ids": [ids_for(ci) for ci, _ in todo],
                    "sampling_params": params,
                    "custom_logit_processor": mask,
                }
                async with sem:
                    r = await client.post(f"{url}/generate", json=body)
                r.raise_for_status()
                res = r.json()
                again = []
                for key, one in zip(todo, res if isinstance(res, list) else [res], strict=True):
                    ids = one.get("output_ids")
                    if ids is None:
                        raise RuntimeError("this SGLang build returns no output_ids")
                    if any(t >= base for t in ids):  # a bank id was sampled: never keep it
                        self.leaks += 1
                        again.append(key)
                    else:
                        tokens[key] = [int(t) for t in ids]
                todo = again
                if not todo:
                    return
            raise RuntimeError(f"{len(todo)} rows sampled a bank id {LEAK_TRIES} times in a row")

        async with http_client() as client:
            info = (await client.get(f"{url}/get_server_info")).json()
            self.version = str(info.get("version", ""))
            chunks = [rows[i : i + self.post_rows] for i in range(0, len(rows), self.post_rows)]
            await asyncio.gather(*[post(client, c) for c in chunks])
        ordered = [tokens[(ci, j)] for ci in range(len(cells)) for j in range(k)]
        self.tokens += ordered
        prefix = list(meta["prefix_ids"])
        dec = self.tok.batch_decode([prefix + row for row in ordered], skip_special_tokens=True)
        self.stats.rows += len(ordered)
        self.stats.tokens += sum(len(row) for row in ordered)
        return [[dec[ci * k + j].strip() for j in range(k)] for ci in range(len(cells))]


def load(name: str, bundle: Bundle, **options: Any) -> Engine:
    """A loaded engine for the bundle, by name. Only "sglang" exists here."""
    if name == "sglang":
        return SGLangEngine(bundle, **options)
    raise ValueError(
        f"unknown engine {name!r} (known: sglang). To add one, write a class with the members "
        "of `Engine` (its `decode` turns cells into readout strings) and return it here."
    )
