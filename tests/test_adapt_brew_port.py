import json
from pathlib import Path

import pytest

from wsbench.adapt.brew_port import derive

BANK = Path(__file__).resolve().parents[1] / "evals" / "brew_intermediates" / "items.json"


def _qwen():
    transformers = pytest.importorskip("transformers")
    try:
        return transformers.AutoTokenizer.from_pretrained("Qwen/Qwen3.6-27B", local_files_only=True)
    except OSError:
        pytest.skip("Qwen3.6 tokenizer not cached")


def test_derive_reproduces_frozen_qwen_cells():
    tok = _qwen()
    for it in json.loads(BANK.read_text())["items"][:20]:
        regions, info = derive(tok, it["prompt"])
        assert {str(k): v for k, v in regions.items()} == it["regions"]
        assert info["has_think"]
