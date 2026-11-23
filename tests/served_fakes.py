"""A tiny fake model snapshot, LoRA adapter and tokenizer for the served-engine tests."""

import json
from pathlib import Path

VOCAB, DIM, EOS = 300, 4, 7
Q0 = "model.language_model.layers.0.self_attn.q_proj.weight"
Q1 = "model.language_model.layers.1.self_attn.q_proj.weight"
EMBED = "model.language_model.embed_tokens.weight"
SLOT_ID = 299


class Tok:
    """Characters are tokens; the first enclosed ideograph splits in two, the others are one."""

    eos_token_id = EOS

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [i for ch in text for i in self.ids(ch)]}

    def ids(self, ch):
        if ord(ch) == 0x3200:
            return [SLOT_ID - 2, SLOT_ID - 1]
        return [SLOT_ID] if ord(ch) > 0x3200 else [ord(ch) % 200]

    def apply_chat_template(self, messages, **kw):
        assert kw == {"tokenize": True, "add_generation_prompt": True, "enable_thinking": False}
        return [250, *self(messages[0]["content"])["input_ids"], 251]

    def batch_decode(self, rows, skip_special_tokens=True):
        return [" " + " ".join(str(t) for t in row) + " " for row in rows]


def snapshot(root: Path) -> Path:
    """Two weight files with an index, a config with a text part, eos ids, one other file."""
    import torch
    from safetensors.torch import save_file

    torch.manual_seed(0)
    root.mkdir()
    shards = {
        "model-00001-of-00002.safetensors": {
            EMBED: torch.randn(VOCAB, DIM).to(torch.bfloat16),
            Q0: torch.randn(DIM, DIM).to(torch.bfloat16),
            "model.visual.blocks.0.attn.weight": torch.randn(DIM, DIM),
        },
        "model-00002-of-00002.safetensors": {
            Q1: torch.randn(DIM, DIM).to(torch.bfloat16),
            "lm_head.weight": torch.randn(VOCAB, DIM).to(torch.bfloat16),
        },
    }
    for name, tensors in shards.items():
        save_file(tensors, str(root / name))
    wmap = {k: name for name, tensors in shards.items() for k in tensors}
    index = {"metadata": {"total_size": 100}, "weight_map": wmap}
    (root / "model.safetensors.index.json").write_text(json.dumps(index))
    text = {"vocab_size": VOCAB, "num_hidden_layers": 2}
    (root / "config.json").write_text(json.dumps({"text_config": text}))
    (root / "generation_config.json").write_text(json.dumps({"eos_token_id": [EOS, 9]}))
    (root / "tokenizer.json").write_text("{}")
    return root


def adapter(root: Path, **config) -> Path:
    """A rank-2 PEFT LoRA on layer 0's q_proj (lora_alpha 4, so scaling 2)."""
    import torch
    from safetensors.torch import save_file

    torch.manual_seed(1)
    root.mkdir()
    module = "base_model.model.model.layers.0.self_attn.q_proj"
    lora = {
        f"{module}.lora_A.weight": torch.randn(2, DIM),
        f"{module}.lora_B.weight": torch.randn(DIM, 2),
    }
    save_file(lora, str(root / "adapter_model.safetensors"))
    cfg = {"peft_type": "LORA", "r": 2, "lora_alpha": 4, **config}
    (root / "adapter_config.json").write_text(json.dumps(cfg))
    return root


def meta(**changes) -> dict:
    """A complete `lens.json` for the fake snapshot: layers 0 and 1, slot at index 2."""
    out = {
        "name": "toy",
        "model": "toy/model",
        "model_revision": "r" * 40,
        "prompts": {
            "0": {"ids": [250, 10, SLOT_ID, 251], "slot": 2, "norm": 2.0},
            "1": {"ids": [250, 11, SLOT_ID, 12, 251], "slot": 2, "norm": 10.0},
        },
        "stop_ids": [EOS, 9],
        "ban_ids": [],
        "ban_min_new": 0,
        "base_vocab": VOCAB,
        "prefix_ids": [],
        "sampling": {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "max_new_tokens": 8, "k": 2},
        "sampling_kind": "prose1",
    }
    return {**out, **changes}
