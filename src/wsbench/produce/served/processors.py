"""Logit processors for the SGLang server (started with `--enable-custom-logit-processor`):
`BankMask` sets the bank ids' logits to -inf; `HFOrderSampler` also applies HF's top-k, then
top-p order. Imports sglang, so only the engine imports this module, when it sends requests."""

from typing import Any

from sglang.srt.sampling.custom_logit_processor import CustomLogitProcessor

from wsbench.produce.served.sampling import hf_top_k_top_p


class BankMask(CustomLogitProcessor):
    """Bank rows are extra vocabulary ids and the model has output logits for them too; with
    this mask a readout can never contain one."""

    def __call__(self, logits: Any, custom_param_list: list[dict[str, Any]] | None = None) -> Any:
        base = int((custom_param_list or [{}])[0].get("base_vocab", logits.shape[-1]))
        logits[..., base:] = float("-inf")
        return logits


class HFOrderSampler(CustomLogitProcessor):
    """The bank mask plus HF `generate`'s filter: keep the top-k logits, renormalise, then
    apply top-p inside that set. SGLang's own sampler applies both cut-offs to the full
    distribution, which keeps a larger nucleus; the request then asks the server for no
    further top-k / top-p. Temperature must be 1.0 (the server applies it after this)."""

    def __call__(self, logits: Any, custom_param_list: list[dict[str, Any]] | None = None) -> Any:
        p = (custom_param_list or [{}])[0]
        base = int(p.get("base_vocab", logits.shape[-1]))
        logits[..., base:] = float("-inf")
        if p.get("hf_top_k"):
            hf_top_k_top_p(logits, int(p["hf_top_k"]), float(p.get("hf_top_p", 1.0)))
        return logits
