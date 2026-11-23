"""The model-continuation baseline: what the unmodified subject model says next when its prompt
is cut after a read position. No activation is read; the served model generates plain text."""

import asyncio
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wsbench.produce import store as st
from wsbench.readplan import ReadSpec

from . import engine as engine_mod
from .server import start_server, stop_server

NAME = "model_continuation"
# The baseline has no layer axis: its rows carry one layer number, and the judge is told to
# judge that layer alone (`layers=44`), as the benchmark's other layer-free rows do.
LAYER = 44
END_OF_TEXT = "<|endoftext|>"


@dataclass(frozen=True)
class Prompt:
    """One (item, read position): the rendered prompt up to and including that token."""

    id: str
    pos: int
    token: str
    ids: list[int]


def prompts_of(specs: Sequence[ReadSpec], tokenizer: Any) -> list[Prompt]:
    """The prompts of plan rows: the benchmark's own render (the token ids the activations
    were captured on), cut after each read position's token. A row that is read under
    steering is continued unsteered: the baseline is the unmodified model."""
    out = []
    for s in specs:
        at = st.locate(s, tokenizer)
        for q, j, tok in zip(at.positions, at.indices, at.tokens, strict=True):
            out.append(Prompt(s.id, q, tok, at.ids[: j + 1]))
    return out


def cut(ids: list[int], stop_ids: Sequence[int]) -> list[int]:
    """A row up to, not including, its first end-of-text token."""
    for i, t in enumerate(ids):
        if t in stop_ids:
            return ids[:i]
    return ids


class ContinuationEngine:
    """The subject model served by SGLang as plain generation from token ids. Sampling is the
    lenses' (temperature 1.0, top-k then top-p in HF's order, a length cap); a row ends at the
    end-of-text token, not at the end of a chat turn, so when the cut is the last token of the
    user's turn the readout is the turn boundary and then the model's reply."""

    name = "sglang"
    sampler = "hf"

    def __init__(
        self,
        model: Path,  # a local snapshot folder of the subject model
        *,
        work: Path | None = None,  # scratch folder for the server log
        in_flight: int = 4096,
        post_rows: int = 32,
        mem_fraction: float = 0.85,
        server_args: list[str] | None = None,  # replaces the engine's DEFAULT_SERVER_ARGS
        temperature: float = 1.0,
        top_p: float = 0.95,
        top_k: int = 64,
        max_new_tokens: int = 256,
        end_of_text: str = END_OF_TEXT,
    ) -> None:
        if temperature != 1.0:
            raise ValueError("the HF-order sampler needs temperature 1.0")
        self.model = Path(model)
        self.work = Path(work) if work is not None else Path(tempfile.mkdtemp(prefix="wsb-cont-"))
        self.in_flight, self.post_rows, self.mem_fraction = in_flight, post_rows, mem_fraction
        defaults = engine_mod.DEFAULT_SERVER_ARGS
        self.server_args = list(defaults if server_args is None else server_args)
        self.top_p, self.top_k, self.max_new_tokens = top_p, top_k, max_new_tokens
        self.tok = engine_mod.load_tokenizer(self.model)
        self.stop_ids = [int(self.tok.convert_tokens_to_ids(end_of_text))]
        self.tokens: list[list[int]] = []  # the last decode's token ids, one list per prompt

    def params(self) -> dict[str, Any]:
        """SGLang sampling parameters: the filter is applied by the logit processor, the
        server's own top-k / top-p are switched off, and the server's stop at the end of a
        chat turn is ignored (rows are cut at end-of-text here)."""
        return {
            "temperature": 1.0,
            "top_k": 1 << 30,
            "top_p": 1.0,
            "max_new_tokens": self.max_new_tokens,
            "ignore_eos": True,
            "skip_special_tokens": True,
            "custom_params": {"hf_top_k": self.top_k, "hf_top_p": self.top_p},
        }

    def decode(self, prompts: Sequence[Sequence[int]]) -> list[str]:
        """One continuation per prompt (token ids), in order: one server start per call."""
        if not prompts:
            return []
        self.work.mkdir(parents=True, exist_ok=True)
        proc, url = start_server(
            self.model,
            self.work / "server.log",
            mem_fraction=self.mem_fraction,
            extra=["--enable-custom-logit-processor", *self.server_args],
        )
        try:
            rows = asyncio.run(self._requests(url, [list(p) for p in prompts]))
        finally:
            stop_server(proc)
        self.tokens = [cut(ids, self.stop_ids) for ids in rows]
        return [self.tok.decode(ids, skip_special_tokens=True) for ids in self.tokens]

    async def _requests(self, url: str, prompts: list[list[int]]) -> list[list[int]]:
        out: list[list[int]] = [[] for _ in prompts]
        sem = asyncio.Semaphore(max(1, self.in_flight // self.post_rows))
        body = {
            "sampling_params": self.params(),
            "custom_logit_processor": engine_mod.processor(True),
        }

        async def post(client: Any, lo: int) -> None:
            chunk = prompts[lo : lo + self.post_rows]
            async with sem:
                r = await client.post(f"{url}/generate", json={**body, "input_ids": chunk})
            r.raise_for_status()
            res = r.json()
            for i, one in enumerate(res if isinstance(res, list) else [res]):
                out[lo + i] = [int(t) for t in one["output_ids"]]

        async with engine_mod.http_client() as client:
            starts = range(0, len(prompts), self.post_rows)
            await asyncio.gather(*(post(client, lo) for lo in starts))
        return out

    def close(self) -> None:
        pass
