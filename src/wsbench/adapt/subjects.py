"""Subject models the banks can be adapted to. ``tokenizer`` names the family whose token indices
carry over unchanged (``qwen3.6`` = the banks' own tokenizer and chat template)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEMPLATES = Path(__file__).parent / "data" / "templates"  # pinned chat templates (A3, plan 0060)
DEFAULT_MODAL_APP = "adapt-subject-llm"  # the shared H200 app any hub-cached subject can use


@dataclass(frozen=True)
class Subject:
    key: str
    hf_id: str
    label: str
    n_layers: int  # 0 = read num_hidden_layers from the HF config at run time
    tokenizer: str
    revision: str | None = None
    max_model_len: int = 4096
    backend: str = "box"  # "box" = the RunPod 4090; "modal" = too big for 24 GB
    gpu_memory_utilization: float = 0.85  # vLLM share of the 24 GB card
    enforce_eager: bool = False  # no torch.compile / CUDA graphs (saves memory on a tight fit)
    read_band: tuple[int, ...] = ()  # the subject's lens layers, if it reads only some (snap there)
    modal_app: str = DEFAULT_MODAL_APP  # backend="modal": the deployed app generating for it
    tokenizer_dir: str | None = None  # local tokenizer files when the hub id needs remote code
    chat_template: str | None = None  # a template file replacing the tokenizer's own
    trust_remote_code: bool = False  # the hub tokenizer is remote code (Kimi's tiktoken)
    # backend="modal": how scripts/adapt_modal.py builds the subject's app (``modal_spec``). The
    # defaults are the shared app's: one H200, the hub cache volume, the stock vLLM image.
    modal_gpu: tuple[str, ...] = ("H200",)  # Modal GPU spec(s); more than one = fallback order
    modal_tp: int = 1  # vLLM tensor_parallel_size (= the GPUs per container)
    modal_replicas: int = 1  # containers RemoteRunner fans its chunks over (data parallel)
    # vLLM engines per container, one per GPU at TP=modal_tp: DeepSeek-V4-Flash is one B300:8
    # running 8 TP=1 engines (gen_vllm_modal.py; Camila's rule "always 8xB300"), not 8 containers
    modal_engines: int = 1
    modal_image: str = "default"  # the image recipe in scripts/adapt_modal.py: default|glm53|dsv4
    modal_volume: str = "adapt-hf-cache"  # mounted at the recipe's mount point
    modal_weights: str | None = None  # a checkpoint dir inside the volume; None = the hub id
    # False = its modal_app is not built by scripts/adapt_modal.py (an Agam-only text app that
    # predates token-id prompts): RemoteRunner refuses it instead of failing inside vLLM
    modal_built: bool = True
    modal_engine: tuple[tuple[str, Any], ...] = ()  # extra kwargs for the vLLM engine (overrides)
    # plan 0060 D8: arithmetic has no pre-registered cell on this subject (its render has no
    # counterpart of the Qwen cell's token); freeze drops cell.pos and the judge reads every cell
    arith_all_positions: bool = False


SUBJECTS: dict[str, Subject] = {
    s.key: s
    for s in [
        Subject(
            "qwen3.5-0.8b",
            "Qwen/Qwen3.5-0.8B",
            "Qwen3.5-0.8B",
            24,
            "qwen3.6",
            "2fc06364715b967f1860aea9cf38778875588b17",
        ),
        Subject(
            "qwen3.5-2b",
            "Qwen/Qwen3.5-2B",
            "Qwen3.5-2B",
            24,
            "qwen3.6",
            "15852e8c16360a2fea060d615a32b45270f8a8fc",
        ),
        Subject(
            "qwen3.5-4b",
            "Qwen/Qwen3.5-4B",
            "Qwen3.5-4B",
            32,
            "qwen3.6",
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
        ),
        Subject(
            "qwen3.5-9b",
            "Qwen/Qwen3.5-9B",
            "Qwen3.5-9B",
            32,
            "qwen3.6",
            "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
            gpu_memory_utilization=0.93,
            enforce_eager=True,
        ),
        Subject(
            "olmo-3-7b",
            "allenai/Olmo-3-7B-Instruct",
            "OLMo-3-7B-Instruct",
            32,
            "dolma2",
            "6e5971d9eba42665f5bd5a0fcf047f299ce1dccc",
        ),
        Subject(
            "gemma-4-31b-it",
            "google/gemma-4-31b-it",
            "Gemma-4-31B-it",
            60,
            "gemma4",
            "842da3794eaa0b77d5f08bae87a17459d91ff475",
            backend="modal",
        ),
        # OLens subjects added 2026-10-18 (hub main that day); Modal so sets build in parallel
        # with the box queue. Tokenizer keys: "qwen3" = Qwen3's 151k vocab (not the 3.6 one).
        Subject(
            "qwen3-8b",
            "Qwen/Qwen3-8B",
            "Qwen3-8B",
            36,
            "qwen3",
            "b968826d9c46dd6066d109eabc6255188de91218",
            backend="modal",
            read_band=tuple(range(12, 35, 2)),
        ),  # its OLens reads even layers 12..34
        Subject(
            "olmo-3.1-32b",
            "allenai/Olmo-3.1-32B-Instruct",
            "OLMo-3.1-32B-Instruct",
            64,
            "dolma2",
            "ac0587e4a7744a551c059d8cd17ba220bc940dae",
            backend="modal",
        ),
        Subject(
            "qwen3.6-35b-a3b",
            "Qwen/Qwen3.6-35B-A3B",
            "Qwen3.6-35B-A3B",
            40,
            "qwen3.6",
            "995ad96eacd98c81ed38be0c5b274b04031597b0",
            backend="modal",
        ),
        # normal-bank OLens subjects (>= 32B, 2026-10-23): gated + re-golded on the 27B bank only.
        # model-parallel HF generation on Modal: gw-olens scripts/ola/port/adapt_mp_subject_modal.py
        # kimi-k2: the hub tokenizer at the pinned revision (tiktoken remote code; needs the
        # ``tiktoken`` package, in the gpu extra), no longer Agam's converted
        # /workspace/agam/hf_tok/kimi-k2. Its official hub template is used as-is (no thinking),
        # so EVERY Kimi render opens with the template's default system turn ("You are Kimi, an
        # AI assistant created by Moonshot AI.") unless the ask brings its own system message;
        # sets are built fresh, so this need not match Agam's earlier gate renders. Generation:
        # our B300:8 at TP8 (plan 0060 D2); the first load writes ~1 TB into adapt-hf-cache.
        Subject(
            "kimi-k2",
            "moonshotai/Kimi-K2-Instruct-0905",
            "Kimi-K2-Instruct-0905",
            61,
            "kimi",
            "ac6c49f04883bd0a0598b790693a72061c676629",
            backend="modal",
            modal_app="adapt-kimi-k2",
            trust_remote_code=True,
            modal_gpu=("B300:8",),
            modal_tp=8,
            modal_engine=(("trust_remote_code", True),),
        ),
        Subject(
            "glm-5.3-flash",
            "zai-org/GLM-5.3-Flash",
            "GLM-5.3-Flash",
            45,
            "glm5",
            "eb9eb208eb0d988989d07a6a12d0fdeb5f52574a",
            backend="modal",
            modal_app="adapt-mp-glm-5.3-flash",
            modal_built=False,  # Agam's text-only app; not rebuilt (plan 0060 D1: GLM-5.3 instead)
            tokenizer_dir="/workspace/agam/hf_tok/glm-5.3-flash",
            # gw-olens' template: the upstream one always opens <think>
            chat_template="/workspace/agam/hf_tok/glm-5.3-flash/glm5_chat_nothink.jinja",
        ),
        # GLM-5.3 non-Flash (plan 0060 D1): the glm53 lens work's checkpoint, 754B MoE, d 6144.
        # Thinking off = its template at reasoning_effort=low with the <think></think> closed
        # (data/templates/glm53_nvfp4_nothink.jinja); raw prompts open with [gMASK]<sop>
        # (``template.bos_prefix``). Served like the glm53 drivers' S1 engine: vLLM 0.31.0 + the
        # metamodels glm53 fork, TP8 on B300:8 (B200:8 fallback), routed experts as W4A16 Marlin.
        Subject(
            "glm-5.3",
            "nvidia/GLM-5.3-NVFP4",
            "GLM-5.3 (NVFP4)",
            78,
            "glm5",
            "e3b8f9f2fad29727dfa95e766c5cac18ea1414bf",
            backend="modal",
            modal_app="adapt-glm-5.3",
            chat_template=str(TEMPLATES / "glm53_nvfp4_nothink.jinja"),
            modal_gpu=("B300:8", "B200:8"),
            modal_tp=8,
            modal_image="glm53",
            modal_volume="glm53-weights",
            modal_weights="hf/nvidia__GLM-5.3-NVFP4",
            modal_engine=(
                ("enable_expert_parallel", False),
                ("kv_cache_dtype", "fp8"),
                ("max_num_seqs", 512),
                ("max_num_batched_tokens", 32768),
                ("enable_prefix_caching", False),
                ("model_loader_extra_config", {"enable_multithread_load": True, "num_threads": 64}),
                ("kernel_config", {"moe_backend": "marlin"}),
            ),
        ),
        # plan 0060 A3 (2026-11-03). No Jinja template ships: the pinned one reproduces
        # encode_messages(thinking_mode="chat") = <bos><|User|>...<|Assistant|></think> (fullwidth
        # bars) token for token (tests/test_adapt_v4.py). J-lens v4-flash:/runs/jlens/std-n1000:
        # row r = block r for r in 0..40 (sources 0..40, target block 41); row 41 is the identity
        # anchor and there is no L42 row, so the band is rows <= 40.
        Subject(
            "deepseek-v4-flash",
            "deepseek-ai/DeepSeek-V4-Flash",
            "DeepSeek-V4-Flash",
            43,
            "dsv4",
            "60d8d70770c6776ff598c94bb586a859a38244f1",
            backend="modal",
            read_band=tuple(range(41)),
            modal_app="adapt-v4-flash",
            chat_template=str(TEMPLATES / "deepseek_v4_chat.jinja"),
            arith_all_positions=True,
            # Camila's rule: always 8xB300 = one container, 8 TP=1 engines (gen_vllm_modal.py)
            modal_gpu=("B300:8",),
            modal_tp=1,
            modal_engines=8,
            modal_image="dsv4",
            modal_volume="v4-flash",
            modal_weights="hf/hub/models--deepseek-ai--DeepSeek-V4-Flash/snapshots/"
            "60d8d70770c6776ff598c94bb586a859a38244f1",
            modal_engine=(("moe_backend", "marlin"), ("generation_config", "vllm")),
        ),
    ]
}

ORIGINAL_LAYERS = 64  # Qwen3.6-27B, the model every bank and read grid was built on


def get(key: str) -> Subject:
    try:
        return SUBJECTS[key]
    except KeyError:
        raise SystemExit(f"unknown subject {key!r}; add it to wsbench/adapt/subjects.py") from None


def modal_spec(s: Subject | None = None) -> dict[str, Any]:
    """What scripts/adapt_modal.py deploys for ``s`` (None = the shared default app): plain JSON,
    baked into the image so the container builds the same app it was deployed as."""
    s = s or Subject("", "", "", 0, "")
    return {
        "app": s.modal_app,
        "gpu": list(s.modal_gpu),
        "tp": s.modal_tp,
        "replicas": s.modal_replicas,
        "engines": s.modal_engines,
        "image": s.modal_image,
        "volume": s.modal_volume,
        "weights": s.modal_weights,
        "engine": dict(s.modal_engine),
    }


def subject_for(hf_id: str, revision: str | None = None) -> Subject | None:
    """The registered subject serving ``hf_id`` (at ``revision`` when given), if any."""
    return next((s for s in SUBJECTS.values() if s.hf_id == hf_id
                 and (revision is None or s.revision == revision)), None)  # fmt: skip


def load_tokenizer(
    hf_id: str,
    revision: str | None = None,
    tokenizer_dir: str | None = None,
    chat_template: str | None = None,
    trust_remote_code: bool = False,
) -> Any:
    """The subject's tokenizer: local ``tokenizer_dir`` files, else the hub id at ``revision``;
    ``chat_template`` (a file) replaces the tokenizer's own template either way."""
    from transformers import AutoTokenizer

    if tokenizer_dir:
        try:
            tok = AutoTokenizer.from_pretrained(tokenizer_dir)
        except ValueError:  # Kimi: a converted tokenizer.json beside a remote-code config
            from transformers import PreTrainedTokenizerFast

            tok = PreTrainedTokenizerFast.from_pretrained(tokenizer_dir)
    else:
        tok = AutoTokenizer.from_pretrained(
            hf_id, revision=revision, trust_remote_code=trust_remote_code
        )
    if chat_template:
        tok.chat_template = Path(chat_template).read_text()
    return tok


def remap_layer(layer: int, n_layers: int, band: tuple[int, ...] | list[int] = ()) -> int:
    """A 27B read layer at the same depth fraction of the subject, snapped to the nearest layer of
    ``band`` (the subject's lens layers; ties go deeper) when the subject has one."""
    x = min(n_layers - 1, round(layer * n_layers / ORIGINAL_LAYERS))
    return min(band, key=lambda b: (abs(b - x), -b)) if band else x


def remap_layers(
    layers: list[int], n_layers: int, band: tuple[int, ...] | list[int] = ()
) -> list[int]:
    return sorted({remap_layer(layer, n_layers, band) for layer in layers})
