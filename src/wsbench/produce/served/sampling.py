"""Sampling: one plan per bundle, rendered for the server, and HF's top-k / top-p filter as a
function."""

from dataclasses import dataclass
from typing import Any, Self

from wsbench.produce.served.bundle import Bundle


@dataclass(frozen=True)
class SamplingPlan:
    """What a lens samples with. The ban (token ids never sampled, and no stop before ``hold``
    new tokens) is on when the bundle lists ``ban_ids``."""

    temperature: float
    top_p: float
    top_k: int
    max_new: int
    stop_ids: tuple[int, ...]
    ban_ids: tuple[int, ...] = ()
    hold: int = 0  # new tokens before a stop token may end the row
    greedy: bool = False

    @classmethod
    def of(cls, bundle: Bundle, *, greedy: bool = False) -> Self:
        meta, s = bundle.meta, bundle.meta["sampling"]
        ban = tuple(int(i) for i in meta["ban_ids"])
        return cls(
            temperature=float(s["temperature"]),
            top_p=float(s["top_p"]),
            top_k=int(s["top_k"]),
            max_new=int(s["max_new_tokens"]),
            stop_ids=tuple(int(i) for i in meta["stop_ids"]),
            ban_ids=ban,
            hold=min(int(meta["ban_min_new"]), int(s["max_new_tokens"])) if ban else 0,
            greedy=greedy,
        )

    def sglang(self) -> dict[str, Any]:
        """SGLang ``sampling_params`` (the ban: ``logit_bias`` + ``min_new_tokens``)."""
        out: dict[str, Any] = {
            "temperature": 0.0 if self.greedy else self.temperature,
            "top_p": 1.0 if self.greedy else self.top_p,
            "top_k": 1 if self.greedy else self.top_k,
            "max_new_tokens": self.max_new,
            "stop_token_ids": list(self.stop_ids),
            "skip_special_tokens": True,
        }
        if self.ban_ids:
            out["logit_bias"] = {str(i): -1e9 for i in self.ban_ids}
            out["min_new_tokens"] = self.hold
        return out


def hf_top_k_top_p(logits: Any, top_k: int, top_p: float) -> Any:
    """HF's TopKLogitsWarper then TopPLogitsWarper, in place, for [batch, vocab] logits: keep
    the ``top_k`` largest, softmax over them, drop the tail whose cumulative mass (counted from
    the smallest) is at most ``1 - top_p``; the largest token always stays."""
    import torch

    k = min(int(top_k), logits.shape[-1])
    vals, idx = torch.topk(logits, k, dim=-1)  # sorted, largest first
    probs = torch.softmax(vals.float(), dim=-1)
    tail = torch.flip(torch.cumsum(torch.flip(probs, dims=[-1]), dim=-1), dims=[-1])
    drop = tail <= (1.0 - float(top_p))
    drop[..., 0] = False
    kept = vals.masked_fill(drop, float("-inf"))
    logits.fill_(float("-inf"))
    logits.scatter_(-1, idx, kept.to(logits.dtype))
    return logits
