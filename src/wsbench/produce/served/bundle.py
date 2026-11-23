"""The lens bundle: the one folder a served engine needs (the merged model files, `lens.json`
and a `MERGE_DONE` marker). `from_adapter` builds it for WorkspaceBench's own LoRA slot lens; a
lens trained elsewhere with its own model code plugs in by writing the same folder."""

import json
import re
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

META = "lens.json"
DONE = "MERGE_DONE"
INDEX = "model.safetensors.index.json"
KEYS = (
    "name",  # the lens's name (free text; names the readouts)
    "model",  # the subject model's id
    "model_revision",  # the subject revision the lens reads (the residual store's key)
    "prompts",  # {"<layer>": {"ids": [...], "slot": int, "norm": float}}
    "stop_ids",  # token ids that end a readout
    "ban_ids",  # token ids never sampled; [] = no ban
    "ban_min_new",  # new tokens before a stop token may end a readout (with a ban)
    "base_vocab",  # rows of the model's embedding table: bank row j is token id base_vocab + j
    "prefix_ids",  # token ids put in front of every readout before decoding; usually []
    "sampling",  # {temperature, top_p, top_k, max_new_tokens, k}
    "sampling_kind",  # what the readouts sidecar declares: prose1 | bullet4
)
SAMPLING_KEYS = ("temperature", "top_p", "top_k", "max_new_tokens", "k")
SAMPLING_KINDS = ("prose1", "bullet4")


class BundleError(RuntimeError):
    """The folder is not a finished bundle, or its `lens.json` lacks something."""


def check(meta: Mapping[str, Any], where: Path) -> None:
    """Raise unless ``meta`` has every key a served engine reads."""
    missing = [k for k in KEYS if k not in meta]
    missing += [f"sampling.{k}" for k in SAMPLING_KEYS if k not in meta.get("sampling", {})]
    if missing:
        raise BundleError(f"{where / META}: missing {', '.join(missing)}")
    if meta["sampling_kind"] not in SAMPLING_KINDS:
        raise BundleError(f"{where / META}: sampling_kind is one of {SAMPLING_KINDS}")
    for layer, p in meta["prompts"].items():
        if not 0 <= int(p["slot"]) < len(p["ids"]) or float(p["norm"]) <= 0:
            raise BundleError(f"{where / META}: layer {layer} needs a slot inside ids and a norm")


@dataclass(frozen=True)
class Bundle:
    """A finished bundle folder and its `lens.json`."""

    path: Path
    meta: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.meta["name"])

    @property
    def k(self) -> int:
        """Readouts sampled per cell."""
        return int(self.meta["sampling"]["k"])

    @property
    def model_revision(self) -> str:
        return str(self.meta["model_revision"])

    @property
    def layers(self) -> list[int]:
        """The layers the lens has a prompt for."""
        return sorted(int(layer) for layer in self.meta["prompts"])

    @property
    def sampling_kind(self) -> str:
        return str(self.meta["sampling_kind"])


def load(path: str | Path) -> Bundle:
    """The bundle at ``path``; a `BundleError` when the folder is not a finished one."""
    path = Path(path)
    if not (path / DONE).exists() or not (path / META).exists():
        raise BundleError(
            f"{path} is not a finished lens bundle (it needs {META} and {DONE}): build one "
            "with `wsbench bundle`, or write the folder as docs/producing_readouts.md says"
        )
    meta = json.loads((path / META).read_text(encoding="utf-8"))
    check(meta, path)
    return Bundle(path, meta)


# ---------------------------------------------------------------- LoRA -> weight deltas

# a PEFT LoRA tensor: <module path>.lora_A.weight ([r, in]) or .lora_B.weight ([out, r])
_LORA_KEY = re.compile(r"^(?P<module>.+)\.lora_(?P<ab>[AB])\.weight$")


def weight_suffix(module: str) -> str:
    """`base_model.model.model.layers.3.mlp.up_proj` -> `layers.3.mlp.up_proj.weight`: the
    part of a LoRA module path that also ends the weight's name in the model files, however
    deep either one nests the decoder."""
    m = re.search(r"(?:^|\.)(layers\.\d+\..+)$", module)
    if m is None:
        raise ValueError(f"LoRA module {module!r} is not inside a decoder layer (…layers.<i>.…)")
    return f"{m[1]}.weight"


class Deltas(Mapping[str, Any]):
    """Weight-name suffix -> ``scaling * (B @ A)`` ([out, in], fp32), computed when asked, so
    the deltas of a large adapter are never all in memory."""

    def __init__(self, pairs: dict[str, tuple[Any, Any]], scaling: float) -> None:
        self.pairs, self.scaling = pairs, scaling

    def __getitem__(self, suffix: str) -> Any:
        a, b = self.pairs[suffix]
        return self.scaling * (b.float() @ a.float())

    def __iter__(self) -> Iterator[str]:
        return iter(self.pairs)

    def __len__(self) -> int:
        return len(self.pairs)


def compute_deltas(lora: Mapping[str, Any], *, scaling: float) -> Deltas:
    """Pair each module's `lora_A` / `lora_B` of a PEFT state dict (other keys are ignored)."""
    a: dict[str, Any] = {}
    b: dict[str, Any] = {}
    for key, tensor in lora.items():
        m = _LORA_KEY.match(key)
        if m is not None:
            (a if m["ab"] == "A" else b)[weight_suffix(m["module"])] = tensor
    if set(a) != set(b):
        raise ValueError(f"lora_A / lora_B modules differ: {sorted(set(a) ^ set(b))[:3]}")
    return Deltas({suffix: (a[suffix], b[suffix]) for suffix in a}, scaling)


# ---------------------------------------------------------------- merge (once per lens)


def weight_map(folder: Path) -> dict[str, str]:
    """Tensor name -> the safetensors file of ``folder`` that holds it (the weights index
    when there is one, else the files' headers)."""
    if (folder / INDEX).exists():
        return dict(json.loads((folder / INDEX).read_text())["weight_map"])
    from safetensors import safe_open

    out: dict[str, str] = {}
    for shard in sorted(folder.glob("*.safetensors")):
        with safe_open(str(shard), framework="pt") as f:
            out.update(dict.fromkeys(f.keys(), shard.name))
    return out


def _targets(names: Mapping[str, str], deltas: Mapping[str, Any]) -> dict[str, str]:
    """Weight name -> the delta suffix added to it; every delta must match exactly one weight
    (in a model with a vision tower, the language model's)."""
    out: dict[str, str] = {}
    for suffix in deltas:
        hits = [n for n in names if n == suffix or n.endswith(f".{suffix}")]
        if len(hits) > 1:
            hits = [n for n in hits if "language_model." in n] or hits
        if len(hits) != 1:
            what = "matches no weight" if not hits else f"is ambiguous: it matches {hits[:3]}"
            raise ValueError(f"LoRA delta {suffix} {what}")
        out[hits[0]] = suffix
    return out


def merge(
    snapshot: Path,
    out_dir: Path,
    deltas: Mapping[str, Any],
    scaling: float,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Write the bundle ``out_dir``: the model snapshot with the deltas added to its weights
    (fp32 add, cast back), every other file copied, plus `lens.json` (``meta``) and the
    marker. ``deltas``: a PEFT LoRA state dict (folded with ``scaling`` = lora_alpha / r), or
    a ready mapping weight-name suffix -> delta. Streams shard by shard on the CPU."""
    from safetensors.torch import load_file, save_file

    snapshot, out_dir = Path(snapshot), Path(out_dir)
    if (out_dir / DONE).exists():
        return {"status": "exists", "dir": str(out_dir)}
    check(meta, out_dir)
    if any(_LORA_KEY.match(key) for key in deltas):
        deltas = compute_deltas(deltas, scaling=scaling)
    targets = _targets(weight_map(snapshot), deltas)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in snapshot.iterdir():
        if f.is_file() and f.suffix != ".safetensors":
            shutil.copy2(f, out_dir / f.name)
    for shard in sorted(snapshot.glob("*.safetensors")):
        tensors = load_file(str(shard))
        for name in tensors.keys() & targets.keys():
            tensor, delta = tensors[name], deltas[targets[name]]
            if tuple(tensor.shape) != tuple(delta.shape):
                raise ValueError(f"{name}: {tuple(tensor.shape)} vs delta {tuple(delta.shape)}")
            tensors[name] = (tensor.float() + delta).to(tensor.dtype)
        tmp = out_dir / f"{shard.name}.tmp"
        save_file(tensors, str(tmp), metadata={"format": "pt"})
        tmp.replace(out_dir / shard.name)
        del tensors
    (out_dir / META).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (out_dir / DONE).write_text("ok\n")
    return {"status": "merged", "dir": str(out_dir), "deltas": len(targets)}


# ---------------------------------------------------------------- WorkspaceBench's own lens


def _config(snapshot: Path, key: str) -> Any:
    """A model config value, from the top level or the text model's part."""
    cfg = json.loads((snapshot / "config.json").read_text())
    for holder in (cfg, cfg.get("text_config") or {}):
        if key in holder:
            return holder[key]
    raise BundleError(f"{snapshot / 'config.json'} has no {key}")


def base_vocab(snapshot: Path) -> int:
    """Rows of the input embedding table, read from the weight file's header."""
    from safetensors import safe_open

    names = weight_map(snapshot)
    embed = [n for n in names if n.endswith("embed_tokens.weight")]
    if len(embed) != 1:
        raise BundleError(f"{snapshot}: need exactly one embed_tokens.weight, got {embed}")
    with safe_open(str(snapshot / names[embed[0]]), framework="pt") as f:
        return int(f.get_slice(embed[0]).get_shape()[0])


def stop_ids(snapshot: Path, tokenizer: Any) -> list[int]:
    """Where generation stops: `generation_config.json`'s eos ids, else the tokenizer's."""
    path = snapshot / "generation_config.json"
    eos = json.loads(path.read_text()).get("eos_token_id") if path.exists() else None
    if eos is None:
        eos = getattr(tokenizer, "eos_token_id", None)
    if eos is None:
        raise BundleError(f"{snapshot}: no eos_token_id in generation_config.json or tokenizer")
    return sorted({int(x) for x in ([eos] if isinstance(eos, int) else eos)})


def lora_scaling(adapter: Path) -> float:
    """lora_alpha / r of a plain PEFT LoRA; other adapter kinds are refused."""
    cfg = json.loads((adapter / "adapter_config.json").read_text())
    if str(cfg.get("peft_type", "LORA")).upper() != "LORA":
        raise BundleError(f"{adapter}: a {cfg['peft_type']} adapter, not a LoRA")
    for flag, what in (("use_dora", "DoRA"), ("use_rslora", "rsLoRA")):
        if cfg.get(flag):
            raise BundleError(f"{adapter}: {what} adapters are not merged here (plain LoRA only)")
    if cfg.get("rank_pattern") or cfg.get("alpha_pattern"):
        raise BundleError(f"{adapter}: per-module ranks / alphas are not merged here")
    return float(cfg["lora_alpha"]) / float(cfg["r"])


def from_adapter(
    snapshot: str | Path,
    adapter: str | Path,
    out_dir: str | Path,
    *,
    name: str,
    model: str,
    model_revision: str,
    prompt: str,
    alpha: float,
    sampling: Mapping[str, Any],
    sampling_kind: str = "prose1",
    tokenizer: Any = None,
) -> Bundle:
    """Build the bundle of a WorkspaceBench LoRA slot lens (`produce.methods.OLens`) on the
    CPU, without loading the model: ``snapshot`` is a local folder of the subject's files,
    ``adapter`` a local PEFT folder. The slot vector is ``alpha * unit(h)``, so every layer's
    norm is ``alpha``. ``tokenizer``: the subject's, when already loaded."""
    from safetensors.torch import load_file

    from wsbench.produce.methods import carrier_prompt

    snapshot, adapter, out_dir = Path(snapshot), Path(adapter), Path(out_dir)
    if (out_dir / DONE).exists():
        raise BundleError(f"{out_dir} already holds a bundle: delete it or pick another folder")
    scaling = lora_scaling(adapter)
    if tokenizer is None:
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(snapshot))
    prompts = {}
    for layer in range(int(_config(snapshot, "num_hidden_layers"))):
        ids, slot = carrier_prompt(tokenizer, prompt, layer)
        prompts[str(layer)] = {"ids": ids, "slot": slot, "norm": float(alpha)}
    meta = {
        "name": name,
        "model": model,
        "model_revision": model_revision,
        "prompts": prompts,
        "stop_ids": stop_ids(snapshot, tokenizer),
        "ban_ids": [],
        "ban_min_new": 0,
        "base_vocab": base_vocab(snapshot),
        "prefix_ids": [],
        "sampling": {k: sampling[k] for k in SAMPLING_KEYS},
        "sampling_kind": sampling_kind,
    }
    merge(snapshot, out_dir, load_file(str(adapter / "adapter_model.safetensors")), scaling, meta)
    return load(out_dir)
