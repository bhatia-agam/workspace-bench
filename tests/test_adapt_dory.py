"""NVIDIA Dory1.0-4B (a looped model): the subject entry, its unrolled-view read band and its app.

Layers are indices of the mOre-lenses unrolled view (0-7 input, 8-27 pass 1, 28-35 exit after 1
loop, 36-55 pass 2, 56-63 exit after 2 loops, 64+ passes 3-4); the subject is the 2-loop model."""

from pathlib import Path

import pytest

from wsbench.adapt import refill, subjects
from wsbench.adapt.subjects import GRID_27B, SUBJECTS, modal_spec, remap_layer, remap_layers

ROOT = Path(__file__).resolve().parents[1]
DORY = SUBJECTS["dory-4b"]
EXIT_1 = set(range(28, 36))  # the output section after 1 loop: off the 2-loop path


def test_dory_subject_pins():
    assert DORY.hf_id == "nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-BF16"
    assert DORY.revision == "ee517dd388a9b348890ae1e00dacc5eb4d0c750d"
    assert DORY.n_layers == 64 and DORY.thinking_mode and DORY.backend == "modal"
    assert "dory-4b" in refill.PLAN_0075_SETS


def test_dory_band_is_the_2_loop_lens_sites_one_per_grid_layer():
    band = DORY.read_band
    assert band == subjects.DORY_READ_BAND == (15, 19, 23, 27, 39, 43, 47, 51, 55, 59, 63)
    assert len(band) == len(GRID_27B) and not set(band) & EXIT_1 and max(band) < DORY.n_layers
    # the table rule: grid layer i reads band[i], so every site is read once
    assert [remap_layer(g, DORY.n_layers, band) for g in GRID_27B] == list(band)
    # off-grid layers (buggy_code cells) snap into the band, never onto exit 1
    off = [remap_layer(x, DORY.n_layers, band) for x in range(64)]
    assert set(off) <= set(band)
    assert remap_layers([56, 60], DORY.n_layers, band) == [59, 63]


def test_dory_app_spec():
    spec = modal_spec(DORY)
    assert spec["app"] == "adapt-dory-4b" and spec["image"] == "dory"
    assert spec["gpu"] == ["H200", "H100"] and spec["tp"] == 1 and spec["weights"] is None
    assert spec["volume"] == "adapt-hf-cache" and "max_containers" not in spec


def test_dory_recipe_is_vllm_033_on_the_writable_hub_cache(monkeypatch):
    pytest.importorskip("modal")
    import importlib.util

    monkeypatch.setenv("ADAPT_SUBJECT", "dory-4b")
    path = ROOT / "scripts/adapt_modal.py"
    spec = importlib.util.spec_from_file_location("_adapt_modal_dory", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.app.name == "adapt-dory-4b" and mod.DORY_VLLM == "vllm==0.33.0"
    assert mod.HUB_CACHE and mod.RECIPE["mount"] == "/hf"
    kw = mod.engine_kwargs(mod.SPEC, DORY.hf_id, DORY.revision, 8192)
    assert kw["model"] == DORY.hf_id and kw["revision"] == DORY.revision
