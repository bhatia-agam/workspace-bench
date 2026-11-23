"""The lens bundle (`wsbench.produce.served.bundle`) and `wsbench bundle`: the LoRA merge, the
bundle built from a PEFT adapter, load errors, the command's keys, and what the judge path
imports (fakes, CPU, no network)."""

import json
import subprocess
import sys

import pytest
from served_fakes import DIM, EMBED, EOS, Q0, Q1, SLOT_ID, VOCAB, Tok, adapter, meta, snapshot

from wsbench import cli
from wsbench.produce.methods import OLens
from wsbench.produce.served import bundle

REV = "0123456789abcdef"


@pytest.fixture
def snap(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    return snapshot(tmp_path / "snap")


def tensors(folder):
    from safetensors.torch import load_file

    out = {}
    for shard in sorted(folder.glob("*.safetensors")):
        out.update(load_file(str(shard)))
    return out


def lora_of(folder):
    from safetensors.torch import load_file

    return load_file(str(folder / "adapter_model.safetensors"))


def test_merge_adds_the_delta_to_its_weight_and_leaves_the_rest(snap, tmp_path):
    import torch

    lora = lora_of(adapter(tmp_path / "ad"))
    out = tmp_path / "bundle"
    assert bundle.merge(snap, out, lora, 2.0, meta()) == {
        "status": "merged",
        "dir": str(out),
        "deltas": 1,
    }
    before, after = tensors(snap), tensors(out)
    a, b = (lora[k] for k in sorted(lora))
    want = (before[Q0].float() + 2.0 * (b @ a)).to(torch.bfloat16)
    assert torch.equal(after[Q0], want) and not torch.equal(after[Q0], before[Q0])
    assert after[Q0].dtype == torch.bfloat16
    assert set(after) == set(before)
    assert all(torch.equal(after[k], before[k]) for k in before if k != Q0)
    assert json.loads((out / bundle.META).read_text()) == meta()
    assert (out / bundle.DONE).exists() and (out / "tokenizer.json").exists()
    assert bundle.load(out).layers == [0, 1]
    assert bundle.merge(snap, out, lora, 2.0, meta())["status"] == "exists"


def test_merge_takes_ready_deltas_and_refuses_unmatched_or_ambiguous_ones(snap, tmp_path):
    import torch
    from safetensors.torch import load_file, save_file

    delta = torch.ones(DIM, DIM)
    out = tmp_path / "ready"
    bundle.merge(snap, out, {"layers.1.self_attn.q_proj.weight": delta}, 1.0, meta())
    assert torch.equal(tensors(out)[Q1], (tensors(snap)[Q1].float() + 1).to(torch.bfloat16))
    with pytest.raises(ValueError, match="matches no weight"):
        bundle.merge(snap, tmp_path / "x", {"layers.5.mlp.up.weight": delta}, 1.0, meta())
    with pytest.raises(ValueError, match="4, 4"):  # a delta of another shape
        bundle.merge(
            snap, tmp_path / "y", {"layers.0.self_attn.q_proj.weight": delta[:2]}, 1.0, meta()
        )
    assert not (tmp_path / "x").exists() and not (tmp_path / "y" / bundle.DONE).exists()
    # a second decoder with the same layer names: the language model's weight is the target
    shard = snap / "model-00002-of-00002.safetensors"
    more = load_file(str(shard)) | {"model.visual.layers.1.self_attn.q_proj.weight": delta.clone()}
    save_file(more, str(shard))
    (snap / bundle.INDEX).unlink()  # the weight map then comes from the files' headers
    assert bundle.merge(
        snap, tmp_path / "vl", {"layers.1.self_attn.q_proj.weight": delta}, 1, meta()
    )
    # two candidates and neither is the language model's: an error
    more["other.layers.1.self_attn.q_proj.weight"] = delta.clone()
    more["twin.layers.1.self_attn.q_proj.weight"] = delta.clone()
    del more[Q1]
    save_file(more, str(shard))
    with pytest.raises(ValueError, match="ambiguous"):
        bundle.merge(snap, tmp_path / "z", {"layers.1.self_attn.q_proj.weight": delta}, 1.0, meta())


def test_compute_deltas_pairs_a_and_b_by_decoder_layer():
    torch = pytest.importorskip("torch")
    a, b = torch.randn(2, 4), torch.randn(3, 2)
    deep = "base_model.model.model.layers.3.mlp.up_proj"
    deltas = bundle.compute_deltas(
        {f"{deep}.lora_A.weight": a, f"{deep}.lora_B.weight": b, "other.bias": a}, scaling=0.5
    )
    assert list(deltas) == ["layers.3.mlp.up_proj.weight"]
    assert torch.equal(deltas["layers.3.mlp.up_proj.weight"], 0.5 * (b @ a))
    assert bundle.weight_suffix("base_model.model.layers.3.mlp.up_proj") == next(iter(deltas))
    with pytest.raises(ValueError, match="differ"):
        bundle.compute_deltas({f"{deep}.lora_A.weight": a}, scaling=1.0)
    with pytest.raises(ValueError, match="decoder layer"):
        bundle.weight_suffix("base_model.model.lm_head")


def make(snap, tmp_path, adapter_dir=None):
    return bundle.from_adapter(
        snap,
        adapter_dir or adapter(tmp_path / "ad"),
        tmp_path / "b",
        name="toy",
        model="toy/model",
        model_revision=REV,
        prompt=OLens.prompt,
        alpha=16000.0,
        sampling=meta()["sampling"] | {"unused": 1},
        tokenizer=Tok(),
    )


def test_from_adapter_writes_one_prompt_per_layer_with_one_slot_and_norm_alpha(snap, tmp_path):
    made = make(snap, tmp_path)
    assert (made.name, made.k, made.model_revision, made.sampling_kind) == ("toy", 2, REV, "prose1")
    assert made.layers == [0, 1]
    m = made.meta
    for layer in (0, 1):
        p = m["prompts"][str(layer)]
        assert p["norm"] == 16000.0 and p["ids"].count(SLOT_ID) == 1
        assert p["ids"][p["slot"]] == SLOT_ID
        # the carrier prompt of the layer, with the first one-token ideograph in the slot
        want = Tok().apply_chat_template(
            [{"role": "user", "content": OLens.prompt.format(layer=layer, char=chr(0x3201))}],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        assert p["ids"] == want
    assert m["prompts"]["0"]["ids"] != m["prompts"]["1"]["ids"]
    assert (m["stop_ids"], m["base_vocab"], m["ban_ids"], m["prefix_ids"]) == (
        [EOS, 9],
        VOCAB,
        [],
        [],
    )
    assert m["sampling"] == meta()["sampling"]
    assert not tensors(made.path)[Q0].equal(tensors(snap)[Q0])  # the adapter is folded in
    assert tensors(made.path)[EMBED].equal(tensors(snap)[EMBED])
    with pytest.raises(bundle.BundleError, match="already holds a bundle"):
        make(snap, tmp_path, adapter_dir=tmp_path / "ad")


def test_from_adapter_uses_the_methods_own_carrier(snap):
    olens = OLens(lora="")
    olens._b = type("B", (), {"tokenizer": Tok()})()
    ids, slot = olens._carrier(1)
    assert ids[slot] == SLOT_ID and olens._carrier(1) is olens._slots[1]


def test_stop_ids_fall_back_to_the_tokenizer(snap):
    (snap / "generation_config.json").unlink()
    assert bundle.stop_ids(snap, Tok()) == [EOS]
    with pytest.raises(bundle.BundleError, match="eos_token_id"):
        bundle.stop_ids(snap, object())


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"use_dora": True}, "DoRA"),
        ({"use_rslora": True}, "rsLoRA"),
        ({"peft_type": "IA3"}, "not a LoRA"),
        ({"rank_pattern": {"q_proj": 4}}, "per-module"),
    ],
)
def test_other_adapter_kinds_are_refused(snap, tmp_path, config, message):
    with pytest.raises(bundle.BundleError, match=message):
        make(snap, tmp_path, adapter_dir=adapter(tmp_path / "bad", **config))
    assert not (tmp_path / "b").exists()


def test_load_says_what_is_wrong_with_a_folder(tmp_path):
    with pytest.raises(bundle.BundleError, match="not a finished lens bundle"):
        bundle.load(tmp_path)
    (tmp_path / bundle.META).write_text(json.dumps(meta()))
    with pytest.raises(bundle.BundleError, match="not a finished lens bundle"):
        bundle.load(tmp_path)  # lens.json without the marker: a merge that did not finish
    (tmp_path / bundle.DONE).write_text("ok\n")
    assert bundle.load(str(tmp_path)).name == "toy"
    cases = [
        (
            {k: v for k, v in meta().items() if k not in ("stop_ids", "base_vocab")},
            "stop_ids, base",
        ),
        (meta(sampling={"temperature": 1.0}), "sampling.top_p"),
        (meta(sampling_kind="tokens10"), "sampling_kind"),
        (meta(prompts={"3": {"ids": [1, 2], "slot": 2, "norm": 1.0}}), "layer 3"),
    ]
    for bad, message in cases:
        (tmp_path / bundle.META).write_text(json.dumps(bad))
        with pytest.raises(bundle.BundleError, match=message):
            bundle.load(tmp_path)


# ---------------------------------------------------------------- the command

KEYS = ["adapter", "model", "out", "name", "prompt", "alpha", "revision", "model_id"]
KEYS += ["temperature", "top_p", "top_k", "max_new_tokens", "samples", "bullet"]
PATHS = ["adapter=a", "model=m", "out=o"]


def test_bundle_keys_exist_and_an_unknown_key_is_refused(capsys):
    assert cli.COMMANDS["bundle"] is cli.Bundle
    command = cli.Bundle()
    assert sorted(command.to_dict()) == sorted(KEYS)
    assert (command.prompt, command.alpha) == (OLens.prompt, OLens.alpha)
    assert cli.main(["bundle", "no_such=1"]) == cli.EXIT_USAGE
    assert cli.main(["bundle", *PATHS, "no_such=1"]) == cli.EXIT_USAGE
    capsys.readouterr()


def test_bundle_defaults_resolve(capsys):
    from wsbench.produce.backend import DEFAULT_REVISION

    assert cli.main(["bundle", *PATHS, "--show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["name"], shown["revision"], shown["samples"]) == ("o", DEFAULT_REVISION, 1)
    assert cli.main(["bundle", *PATHS, "bullet=True", "samples=2", "--show"]) == 0
    assert json.loads(capsys.readouterr().out)["samples"] == 4


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["model=m", "out=o"], "give adapter="),
        (["adapter=a", "out=o"], "give model="),
        (["adapter=a", "model=m"], "give out="),
        ([*PATHS, "model_id=other/model"], "revision=<sha> is required"),
        ([*PATHS, "prompt=no-slot"], "{char}"),
        ([*PATHS, "alpha=0"], "alpha must be positive"),
        ([*PATHS, "samples=0"], "at least 1"),
        (PATHS, "adapter=a is not a folder"),
    ],
)
def test_bundle_usage_errors(argv, message, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["bundle", *argv]) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err


def test_bundle_command_writes_a_bundle(snap, tmp_path, monkeypatch, capsys):
    transformers = pytest.importorskip("transformers")
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda *a, **kw: Tok())
    out = tmp_path / "lens-a"
    argv = [f"adapter={adapter(tmp_path / 'ad')}", f"model={snap}", f"out={out}"]
    assert cli.main(["bundle", *argv, "bullet=True", "alpha=5", f"revision={REV}"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"lens bundle -> {out}" and len(lines) == 3
    assert "2 layers (0..1), 4 readout(s) per cell (bullet4)" in lines[2]
    made = bundle.load(out)
    assert (made.name, made.k, made.sampling_kind) == ("lens-a", 4, "bullet4")
    assert made.meta["model"] == "Qwen/Qwen3.6-27B" and made.meta["prompts"]["1"]["norm"] == 5.0
    assert cli.main(["bundle", *argv]) == cli.EXIT_USAGE  # the folder is taken
    assert "already holds a bundle" in capsys.readouterr().err
    (tmp_path / "ad" / "adapter_config.json").write_text(json.dumps({"r": 2, "use_dora": True}))
    assert cli.main(["bundle", *argv[:2], f"out={tmp_path / 'other'}"]) == cli.EXIT_USAGE
    assert "DoRA" in capsys.readouterr().err


def test_the_judge_path_imports_no_serving_code():
    code = (
        "import sys, wsbench.cli, wsbench.runner, wsbench.reads\n"
        "bad = sorted(m for m in ('torch', 'sglang', 'modal', 'httpx',"
        " 'wsbench.produce.served') if m in sys.modules)\n"
        "print(bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_importing_the_engine_needs_no_sglang_or_torch():
    code = (
        "import sys\n"
        "from wsbench.produce.served import bundle, bank, sampling, server, engine\n"
        "print(sorted(m for m in ('torch', 'sglang', 'httpx', 'transformers') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
