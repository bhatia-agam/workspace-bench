"""The unrolled view of Inkling-2-Mini (transformers ``inkling2_loop``): one entry per block call,
in execution order, so "layer L" is the output of entry L and a hook on entry L fires once."""

import sys
import types
from dataclasses import dataclass
from typing import Any

# the released config's loop_config {core_start 6, core_end 18, num_passes 3} over 24 blocks
N_BLOCKS, CORE_START, CORE_END, N_PASSES = 24, 6, 18, 3
N_CORE = CORE_END - CORE_START
N_ENTRIES = N_BLOCKS + (N_PASSES - 1) * N_CORE  # 48 = the stock total_num_hidden_layers


@dataclass(frozen=True)
class Site:
    """Entry ``index`` of the unrolled view: physical ``block``, its ``section`` (pre / loop /
    post) and ``loop_pass`` (1..N_PASSES inside the loop, 0 outside)."""

    index: int
    block: int
    section: str
    loop_pass: int

    def label(self) -> str:
        if self.section == "loop":
            return f"{self.block - CORE_START + 1}/{N_CORE} of loop pass {self.loop_pass}"
        if self.section == "pre":
            return f"{self.block + 1}/{CORE_START} of the input section"
        return f"{self.block - CORE_END + 1}/{N_BLOCKS - CORE_END} of the output section"


def layout(
    n_blocks: int = N_BLOCKS, start: int = CORE_START, end: int = CORE_END, passes: int = N_PASSES
) -> list[Site]:
    """The unrolled index -> :class:`Site` table, in the order the stock forward calls blocks."""
    sites = [Site(i, i, "pre", 0) for i in range(start)]
    for p in range(1, passes + 1):
        sites += [Site(len(sites) + j, start + j, "loop", p) for j in range(end - start)]
    sites += [Site(len(sites) + j, end + j, "post", 0) for j in range(n_blocks - end)]
    return sites


def _nn() -> Any:
    from torch import nn

    return nn


def _block_pass_cls() -> Any:
    nn = _nn()

    class BlockPass(nn.Module):
        """One call of a physical block; holds the block by reference (not a submodule), so
        weights are registered once (``text_model.blocks``) and a hook here fires per call."""

        def __init__(self, block: Any, site: Site) -> None:
            super().__init__()
            object.__setattr__(self, "_block", block)
            self.site = site

        @property
        def block(self) -> Any:
            return self._block

        @property
        def is_block_boundary(self) -> bool:
            return bool(self._block.is_block_boundary)

        @property
        def attention_type(self) -> str:
            return str(self._block.attention_type)

        def forward(self, *args: Any, **kwargs: Any) -> Any:
            return self._block(*args, **kwargs)

    return BlockPass


def text_model(model: Any) -> Any:
    """The ``Inkling2LoopTextModel`` inside a ForConditionalGeneration, ForCausalLM or bare."""
    for path in ("model.language_model", "language_model", "model"):
        obj = model
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
        except AttributeError:
            continue
        if type(obj).__name__ == "Inkling2LoopTextModel":
            return obj
    if type(model).__name__ == "Inkling2LoopTextModel":
        return model
    raise ValueError(f"no Inkling2LoopTextModel inside {type(model).__name__}")


def unroll(model: Any) -> Any:
    """Rewrite a loaded Inkling-2 loop model IN PLACE into the unrolled view: ``layers`` becomes
    N_ENTRIES thin entries (execution order), the physical blocks move to ``blocks``, and the
    text model's forward walks the entries with the stock forward's arithmetic (same ops, same
    order; ``hidden_states`` = embeddings + every entry's output, the last being entry 47's raw
    output, not the stock's normed final mix). Idempotent. Returns the model. Not supported after
    unrolling: ``output_attentions`` / ``output_router_logits`` (dropped, None), and anything that
    relies on state-dict keys (``save_pretrained``, a PEFT attach): blocks move to ``blocks``."""
    tm = text_model(model)
    if getattr(tm, "_unrolled", False):
        return model
    cfg = tm.config
    shape = (cfg.num_hidden_layers, cfg.loop_layer_index_start, cfg.loop_layer_index_end,
             cfg.loop_num_passes)  # fmt: skip
    if shape != (N_BLOCKS, CORE_START, CORE_END, N_PASSES):
        raise ValueError(f"inkling_loop: unexpected loop shape {shape}")
    nn = _nn()
    block_pass = _block_pass_cls()
    blocks = tm.layers
    entries = nn.ModuleList([block_pass(blocks[s.block], s) for s in layout()])
    del tm.layers
    tm.blocks = blocks
    tm.layers = entries
    tm._unrolled = True
    tm.forward = types.MethodType(_forward, tm)
    return model


def _forward(
    self: Any,
    input_ids: Any = None,
    attention_mask: Any = None,
    position_ids: Any = None,
    cache: Any = None,
    inputs_embeds: Any = None,
    use_cache: bool | None = None,
    output_hidden_states: bool | None = None,
    past_key_values: Any = None,
    **kwargs: Any,
) -> Any:
    """``Inkling2LoopTextModel.forward`` (transformers 5.24.0) over the unrolled entries."""
    import copy

    import torch

    mod = sys.modules[type(self).__module__]
    for k in ("return_dict", "output_attentions", "output_router_logits"):
        kwargs.pop(k, None)
    if cache is None:
        cache = past_key_values
    if output_hidden_states is None:
        output_hidden_states = bool(getattr(self.config, "output_hidden_states", False))
    output_hidden_states = output_hidden_states is not False  # a selection list keeps them all
    if use_cache is None:
        use_cache = bool(getattr(self.config, "use_cache", False))
    if (input_ids is None) ^ (inputs_embeds is not None):
        raise ValueError("You must specify exactly one of input_ids or inputs_embeds")
    if inputs_embeds is None:
        inputs_embeds = self.embed_tokens(input_ids)
    if use_cache and cache is None:
        cache = mod.DynamicCache(config=self.config)
    if position_ids is None:
        past = cache.get_seq_length() if cache is not None else 0
        position_ids = (torch.arange(inputs_embeds.shape[1], device=inputs_embeds.device)
                        + past).unsqueeze(0)  # fmt: skip

    mask = attention_mask
    if not isinstance(mask, dict):
        mk = {"config": self.config, "inputs_embeds": inputs_embeds,
              "attention_mask": attention_mask, "cache": cache,
              "position_ids": position_ids}  # fmt: skip
        mask = {
            "full_attention": mod.create_causal_mask(**mk),
            "sliding_attention": mod.create_sliding_window_causal_mask(**mk),
            "linear_attention": mod.create_recurrent_attention_mask(**mk),
        }
    rel = {
        "full_attention": mod.get_relative_distance(inputs_embeds, cache, is_sliding=False),
        "sliding_attention": mod.get_relative_distance(inputs_embeds, cache, is_sliding=True),
    }
    start, end = self.config.loop_layer_index_start, self.config.loop_layer_index_end
    n_loop = end - start
    if cache is not None and len(cache.layers) == self.config.num_hidden_layers:
        loop_layers = cache.layers[start:end]
        cache.layers += [copy.deepcopy(x) for x in loop_layers * (self.config.loop_num_passes - 1)]

    hidden = inputs_embeds
    block_states = inputs_embeds.new_zeros(*inputs_embeds.shape[:-1], 0, inputs_embeds.shape[-1])
    states = [hidden] if output_hidden_states else None
    pre_hidden = pre_blocks = prev_blocks = prev_hidden = None
    n_pre_blocks = 0
    for entry in self.layers:
        s = entry.site
        common = {
            "attention_mask": mask[entry.attention_type],
            "relative_distance": rel[entry.attention_type],
            "conv_mask": mask["linear_attention"],
            "cache": cache,
            "position_ids": position_ids,
            **kwargs,
        }
        if s.section == "loop" and s.block == start:  # a pass begins
            if s.loop_pass == 1:
                pre_hidden, pre_blocks = hidden, block_states
                n_pre_blocks = pre_blocks.shape[-2]
            else:  # restart from the pre-loop states; messages from the previous pass
                prev_blocks = block_states[..., n_pre_blocks + 1 :, :]
                prev_hidden = hidden
                hidden, block_states = pre_hidden, pre_blocks
        if s.section == "loop" and s.loop_pass > 1:
            j = s.block - start
            messages = self.message_input(prev_blocks, prev_hidden, j)
            offset = self.config.num_hidden_layers + (s.loop_pass - 2) * n_loop - start
            new = entry(hidden, block_states, messages, cache_offset=offset, **common)
        else:
            new = entry(hidden, block_states, **common)
        if entry.is_block_boundary:
            prev = block_states.to(hidden.device)
            block_states = torch.cat([prev, hidden.unsqueeze(-2)], dim=-2)
        hidden = new
        if states is not None:
            states.append(hidden)

    hidden = self.final_input(block_states, hidden)[0]
    hidden = self.norm(hidden).to(inputs_embeds.dtype)
    return mod.MoeModelOutputWithPast(
        last_hidden_state=hidden,
        cache=cache,
        hidden_states=tuple(states) if states is not None else None,
    )
