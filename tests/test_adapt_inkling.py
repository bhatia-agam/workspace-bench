"""Inkling-2-Mini (a looped MoE): the subject entry, its unrolled view (adapt/inkling_loop.py), its
every-other-entry read band, its pinned no-think template and its app."""

import importlib.util
from pathlib import Path

import pytest

from wsbench.adapt import inkling_loop, refill, subjects, template
from wsbench.adapt.subjects import GRID_27B, SUBJECTS, modal_spec, remap_layer

ROOT = Path(__file__).resolve().parents[1]
INK = SUBJECTS["inkling-2-mini"]


def test_inkling_subject_pins():
    assert INK.hf_id == "thinkingmachines/Inkling-2-Mini"
    assert INK.revision == "b85c3cfa615fc413cc9af3379f491b963f3b586a"
    assert INK.n_layers == inkling_loop.N_ENTRIES == 48
    assert INK.backend == "modal" and INK.thinking_mode and INK.reply_end == "<|end_message|>"
    assert INK.thinking_kwarg == "enable_thinking"  # the pinned template ignores the switch
    assert Path(INK.chat_template).name == "inkling2_mini_nothink.jinja"
    assert "inkling-2-mini" in refill.PLAN_0075_SETS


def test_unrolled_layout_is_the_stock_execution_order():
    sites = inkling_loop.layout()
    assert [s.index for s in sites] == list(range(48))
    assert [s.block for s in sites] == [*range(6), *range(6, 18), *range(6, 18), *range(6, 18),
                                        *range(18, 24)]  # fmt: skip
    assert [s.loop_pass for s in sites[6:42]] == [1] * 12 + [2] * 12 + [3] * 12
    assert {s.section for s in sites[:6]} == {"pre"} and {s.section for s in sites[42:]} == {"post"}
    assert sites[6].label() == "1/12 of loop pass 1" and sites[41].label() == "12/12 of loop pass 3"
    assert sites[0].label() == "1/6 of the input section"
    assert sites[47].label() == "6/6 of the output section"


def test_band_is_every_other_unrolled_entry_passes_included():
    band = INK.read_band
    assert band == subjects.INKLING_READ_BAND == tuple(range(1, 48, 2)) and len(band) == 24
    passes = {inkling_loop.layout()[i].loop_pass for i in band}
    assert passes == {0, 1, 2, 3}  # passes 1 and 2 are read too (Camila 2026-11-23)
    # 24 sites is not the 11-site table rule: grid layers snap by depth, one site each
    got = [remap_layer(g, INK.n_layers, band) for g in GRID_27B]
    assert got == [15, 19, 21, 25, 27, 31, 33, 37, 39, 43, 45]
    assert len(set(got)) == len(GRID_27B)
    assert {remap_layer(x, INK.n_layers, band) for x in range(64)} <= set(band)


def test_role_marker_reads_inkling_turns():
    assert "<|message_user|>" in template.ROLE_MARKERS


def test_inkling_app_spec():
    spec = modal_spec(INK)
    assert spec["app"] == "adapt-inkling-2-mini" and spec["image"] == "inkling"
    assert spec["gpu"] == ["B200"] and spec["tp"] == 1 and spec["replicas"] == 16
    assert "max_containers" not in spec and spec["volume"] == "inkling-2-mini"
    assert spec["weights"].endswith("/snapshots/b85c3cfa615fc413cc9af3379f491b963f3b586a")


def test_inkling_recipe_is_the_pinned_vllm_image(monkeypatch):
    pytest.importorskip("modal")
    monkeypatch.setenv("ADAPT_SUBJECT", "inkling-2-mini")
    path = ROOT / "scripts/adapt_modal.py"
    spec = importlib.util.spec_from_file_location("_adapt_modal_inkling", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.app.name == "adapt-inkling-2-mini" and mod.RECIPE["mount"] == "/hf"
    assert mod.INKLING_IMAGE.startswith("vllm/vllm-openai@sha256:") and not mod.HUB_CACHE
    kw = mod.engine_kwargs(mod.SPEC, INK.hf_id, INK.revision, 8192)
    assert kw["model"] == "/hf/" + INK.modal_weights and kw["revision"] is None


def test_pinned_template_is_the_hub_template_plus_two_edits():
    text = Path(INK.chat_template).read_text()
    assert '{%- set eff = "none" -%}' in text
    assert text.rstrip().endswith('{{- "<|message_model|><|content_text|>" -}}\n{%- endif -%}')
    assert "reasoning_effort is defined" not in text


def _tiny_model():
    """A random 24-block Inkling-2 loop model (the released loop shape, tiny widths), CPU fp32."""
    torch = pytest.importorskip("torch")
    tf = pytest.importorskip("transformers")
    if not hasattr(tf, "Inkling2LoopForConditionalGeneration"):
        pytest.skip("transformers without inkling2_loop (needs >= 5.24)")
    from transformers import Inkling2LoopConfig, Inkling2LoopForConditionalGeneration

    text = {
        "hidden_size": 64, "num_hidden_layers": 24, "vocab_size": 320,
        "unpadded_vocab_size": 320, "num_attention_heads": 4, "num_key_value_heads": 2,
        "head_dim": 16, "swa_head_dim": 16, "swa_num_attention_heads": 4,
        "swa_num_key_value_heads": 2, "sliding_window_size": 8, "n_routed_experts": 8,
        "num_experts_per_tok": 2, "intermediate_size": 32, "moe_intermediate_size": 32,
        "d_rel": 4, "rel_extent": 16, "loop_gate_rank": 8,
        "loop_config": {"core_start": 6, "core_end": 18, "num_passes": 3, "gate_rank": 8},
    }  # fmt: skip
    vision = {"hidden_size": 32, "num_hidden_layers": 1, "num_attention_heads": 2,
              "text_hidden_size": 64, "projection_hidden_dim": 32}  # fmt: skip
    cfg = Inkling2LoopConfig(text_config=text, vision_config=vision)
    torch.manual_seed(0)
    m = Inkling2LoopForConditionalGeneration(cfg).eval()
    with torch.no_grad():  # zero-init queries make every residual mix uniform: randomize them
        for name, p in m.named_parameters():
            if "query" in name:
                p.normal_(0, 0.5)
    return torch, m


def test_unroll_equals_the_stock_forward_and_hooks_fire_once():
    torch, m = _tiny_model()
    x = torch.randint(0, 300, (1, 12))
    with torch.no_grad():
        ref = m(input_ids=x, use_cache=False, output_hidden_states=True)
        g_ref = m.generate(x, attention_mask=torch.ones_like(x), max_new_tokens=6, do_sample=False)
    inkling_loop.unroll(m)
    inkling_loop.unroll(m)  # idempotent
    tm = inkling_loop.text_model(m)
    assert len(tm.layers) == 48 and len(tm.blocks) == 24
    calls, got = [], {}

    def mk(i):
        def hook(_m, _a, y):
            calls.append(i)
            got[i] = y.clone()

        return hook

    hs = [e.register_forward_hook(mk(i)) for i, e in enumerate(tm.layers)]
    with torch.no_grad():
        out = m(input_ids=x, use_cache=False, output_hidden_states=True)
    for h in hs:
        h.remove()
    assert calls == list(range(48))
    assert torch.equal(out.logits, ref.logits)
    assert len(out.hidden_states) == 49
    for i in range(48):
        assert torch.equal(got[i], out.hidden_states[i + 1]), i
    # stock hidden_states[0..47] are the embeddings and entries 0..46; its LAST element is the
    # final-mixed, normed state (``final_input`` + ``norm``), ours is entry 47's own output
    for i in range(48):
        assert torch.equal(out.hidden_states[i], ref.hidden_states[i]), i
    with torch.no_grad():
        g = m.generate(x, attention_mask=torch.ones_like(x), max_new_tokens=6, do_sample=False)
    assert torch.equal(g, g_ref)
