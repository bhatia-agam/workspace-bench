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
    # prompt + reply budget of the subject's vLLM engine. Every bank's longest prompt plus its
    # max_tokens must fit: carry's jailbreak_recognition v2 re-screen sends a 4,261-token prompt
    # (Qwen render, ``read.n_tokens`` of rp-wildchat-fe022288) + 512 tokens, over the old 4096
    # (tests/test_adapt_phase2_fixes.py holds the margin for every subject). 8192 keeps the KV
    # reservation small for the 24 GB box subjects (qwen3.5-9b at 0.93 + eager)
    max_model_len: int = 8192
    backend: str = "box"  # "box" = the RunPod 4090; "modal" = too big for 24 GB
    gpu_memory_utilization: float = 0.85  # vLLM share of the 24 GB card
    enforce_eager: bool = False  # no torch.compile / CUDA graphs (saves memory on a tight fit)
    read_band: tuple[int, ...] = ()  # the subject's lens layers, if it reads only some (snap there)
    modal_app: str = DEFAULT_MODAL_APP  # backend="modal": the deployed app generating for it
    tokenizer_dir: str | None = None  # local tokenizer files when the hub id needs remote code
    chat_template: str | None = None  # a template file replacing the tokenizer's own
    trust_remote_code: bool = False  # the hub tokenizer is remote code (Kimi's tiktoken)
    # the chat-template kwarg that turns thinking on/off. Every adapt render passes
    # ``enable_thinking``; ``load_tokenizer`` renames it to this for a template that spells it
    # differently (Kimi-K3's remote-code apply_chat_template takes ``thinking`` and silently
    # ignores enable_thinking, so the render would open a think block at thinking_effort=max)
    thinking_kwarg: str = "enable_thinking"
    # the one-token marker that ends a reply when the engine does not stop on it by itself:
    # RemoteRunner makes the engine stop on that TOKEN id (a reply that writes the same string as
    # BPE text is untouched). Kimi-K3: "<|close|>" (163588) closes the response channel; vLLM
    # stops only at <|end_of_msg|>, after "<|close|>response<|sep|><|close|>message<|sep|>"
    reply_end: str | None = None
    # RemoteRunner takes prompt ids from apply_chat_template(tokenize=True) instead of
    # re-encoding the rendered text (``gate.RemoteRunner.prompt_ids``). Kimi-K3: its template
    # encodes message content with specials disallowed, so re-encoding the text would turn a
    # literal "<|close|>" in a message into a control token
    template_ids: bool = False
    # backend="modal": how scripts/adapt_modal.py builds the subject's app (``modal_spec``). The
    # defaults are the shared app's: one H200, the hub cache volume, the stock vLLM image.
    modal_gpu: tuple[str, ...] = ("H200",)  # Modal GPU spec(s); more than one = fallback order
    modal_tp: int = 1  # vLLM tensor_parallel_size (= the GPUs per container)
    modal_replicas: int = 1  # containers RemoteRunner fans its chunks over (data parallel)
    # vLLM engines per container, one per GPU at TP=modal_tp: DeepSeek-V4-Flash is one B300:8
    # running 8 TP=1 engines (gen_vllm_modal.py; Camila's rule "always 8xB300"), not 8 containers
    modal_engines: int = 1
    modal_image: str = "default"  # recipe in scripts/adapt_modal.py: default|glm53|dsv4|muse
    modal_volume: str = "adapt-hf-cache"  # mounted at the recipe's mount point
    modal_weights: str | None = None  # a checkpoint dir inside the volume; None = the hub id
    # False = its modal_app is not built by scripts/adapt_modal.py (an Agam-only text app that
    # predates token-id prompts): RemoteRunner refuses it instead of failing inside vLLM
    modal_built: bool = True
    modal_engine: tuple[tuple[str, Any], ...] = ()  # extra kwargs for the vLLM engine (overrides)
    # plan 0060 D8: arithmetic has no pre-registered cell on this subject (its render has no
    # counterpart of the Qwen cell's token); freeze drops cell.pos and the judge reads every cell
    arith_all_positions: bool = False
    # the subject has a native thinking mode (a reasoning trace before the answer), verified on
    # its own template (``template.think_markers`` delimits a trace; tests/
    # test_native_langs_thinking.py). Only ``native_langs.measure`` ever renders it (plan 0054 R6
    # measures the TRACE; its default is thinking on for such a subject). Every gating render
    # stays thinking off (``template.check``).
    thinking_mode: bool = False
    # the chat template file for that thinking-on measurement render; None = the tokenizer's own
    # (hub) template, NOT ``chat_template`` (a pinned thinking-OFF render: GLM-5.3, Muse)
    thinking_template: str | None = None


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
            thinking_mode=True,  # hub template: enable_thinking opens <think>
        ),
        Subject(
            "qwen3.5-2b",
            "Qwen/Qwen3.5-2B",
            "Qwen3.5-2B",
            24,
            "qwen3.6",
            "15852e8c16360a2fea060d615a32b45270f8a8fc",
            thinking_mode=True,  # hub template: enable_thinking opens <think>
        ),
        Subject(
            "qwen3.5-4b",
            "Qwen/Qwen3.5-4B",
            "Qwen3.5-4B",
            32,
            "qwen3.6",
            "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
            thinking_mode=True,  # hub template: enable_thinking opens <think>
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
            thinking_mode=True,  # hub template: enable_thinking opens <think>
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
            thinking_mode=True,  # enable_thinking: the model opens <|channel>thought
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
            thinking_mode=True,  # enable_thinking: the model opens <think> itself
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
            thinking_mode=True,  # hub template: enable_thinking opens <think>
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
            thinking_mode=True,  # the upstream template always opens <think> (see above)
        ),
        # GLM-5.3 non-Flash (plan 0060 D1): the glm53 lens work's checkpoint, 754B MoE, d 6144.
        # Thinking off = its template at reasoning_effort=low with the <think></think> closed
        # (data/templates/glm53_nvfp4_nothink.jinja); raw prompts open with [gMASK]<sop>
        # (``template.bos_prefix``). Served like the glm53 drivers' S1 engine: vLLM 0.31.0 + the
        # metamodels glm53 fork, TP8 on B300:8 (B200:8, then H200:8 fallback: every NVFP4 layer
        # is served W4A16 Marlin, which runs on Hopper; glm53_aff ran vLLM TP8 on H200).
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
            # J-lens glm53-jlens:glm-5.3-nvfp4/lens.pt (global-workspace glm53_aff
            # jlens_fit_modal.py, 1950 prompts): rows = blocks 0..76 (sources), target block 77
            # has no row, so the band is every lens row (as V4-Flash's). Split-half <= 0.2 only
            # from L31 up: jlens_concept_pr ships its references at grid layers >= 34
            read_band=tuple(range(77)),
            modal_gpu=("B300:8", "B200:8", "H200:8"),
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
            thinking_mode=True,  # the hub template always opens <think> (effort Max)
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
            # encoding_dsv4 thinking_mode="thinking"; no Jinja template renders it yet, so
            # native_langs thinking=on refuses until a thinking_template is pinned
            thinking_mode=True,
        ),
        # plan 0060 new subjects (2026-11-03; every pin = hub main that day). No J-lens for any
        # of the three yet: read_band=() (depth remap, no snap) until one is fitted.
        # DeepSeek-V4-Pro-0813: Flash's tokenizer files byte for byte; its encoding_dsv4.py
        # differs from Flash's only in thinking-mode reasoning-effort prompts, so the chat-mode
        # render (Flash's pinned template) is identical (tests/test_adapt_new_subjects.py).
        # arithmetic per D8, as Flash: the render ends <|Assistant|></think>. Served as ONE
        # TP8 engine on B300:8 (not Flash's 8 TP=1 engines), the dsv4 image, volume v4-pro.
        Subject(
            "deepseek-v4-pro",
            "deepseek-ai/DeepSeek-V4-Pro-0813",
            "DeepSeek-V4-Pro-0813",
            61,
            "dsv4",
            "72e1d3230f6c080a530b0a1d46f8eb4602340597",
            backend="modal",
            modal_app="adapt-v4-pro",
            chat_template=str(TEMPLATES / "deepseek_v4_chat.jinja"),
            arith_all_positions=True,
            modal_gpu=("B300:8",),
            modal_tp=8,
            modal_image="dsv4",
            modal_volume="v4-pro",
            modal_weights="hf/hub/models--deepseek-ai--DeepSeek-V4-Pro-0813/snapshots/"
            "72e1d3230f6c080a530b0a1d46f8eb4602340597",
            modal_engine=(("moe_backend", "marlin"), ("generation_config", "vllm")),
            thinking_mode=True,  # as Flash: no thinking render pinned yet
        ),
        # Kimi-K3: the remote-code tokenizer overrides apply_chat_template with an XTML render
        # (encoding_k3.py), switched by ``thinking`` (enable_thinking is ignored). thinking=False
        # drops the think channel: the generation prompt opens the response channel directly,
        # <|open|>message role="assistant"<|sep|><|open|>response<|sep|> (no think block to
        # close, no thinking-effort system message). Replies end "<|close|>response<|sep|>
        # <|close|>message<|sep|><|end_of_msg|>"; the XTML markers are not special tokens, so
        # reply_end stops the engine on the <|close|> token; template_ids keeps literal markers
        # in content plain text. Default image (vLLM 0.31.0, tiktoken), TP8 on
        # B300:8; weights on volume kimi-k3 (mounted at /hf: the snapshot is /hf/hf/hub/...).
        Subject(
            "kimi-k3",
            "moonshotai/Kimi-K3",
            "Kimi-K3",
            93,
            "kimi3",
            "f831ab66814297da540d832a5235f8e904f29d06",
            backend="modal",
            modal_app="adapt-kimi-k3",
            trust_remote_code=True,
            thinking_kwarg="thinking",
            reply_end="<|close|>",
            template_ids=True,
            modal_gpu=("B300:8",),
            modal_tp=8,
            modal_volume="kimi-k3",
            modal_weights="hf/hub/models--moonshotai--Kimi-K3/snapshots/"
            "f831ab66814297da540d832a5235f8e904f29d06",
            modal_engine=(
                ("trust_remote_code", True),
                ("language_model_only", True),
                ("gpu_memory_utilization", 0.95),
            ),
            thinking_mode=True,  # thinking=True opens <|open|>think<|sep|>
        ),
        # Muse-Spark-Open (816B-A42B, NVFP4; gated, the local HF token has access). No native
        # thinking-off mode: the pinned data/templates/muse_spark_nothink.jinja is the upstream
        # template at reasoning_effort=low, current_date 2026-11-03 (deterministic) and the
        # generation prompt <|start|>assistant to=user<|message|> (the answer channel, not
        # to=self reasoning). Stops: generation_config.json eos [200001, 200008] (<|eot|>).
        # The "muse" image (vLLM 0.33.0); weights on volume muse-spark as a plain snapshot dir.
        Subject(
            "muse-spark-open",
            "meta-models/Muse-Spark-Open-816B-A42B-NVFP4",
            "Muse-Spark-Open-816B-A42B (NVFP4)",
            62,
            "muse",
            "4239e4db19376904f2e82c167e78f70abb5455fe",
            backend="modal",
            modal_app="adapt-muse-spark-open",
            chat_template=str(TEMPLATES / "muse_spark_nothink.jinja"),
            modal_gpu=("B300:8", "B200:8"),
            modal_tp=8,
            modal_image="muse",
            modal_volume="muse-spark",
            modal_weights="hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4",
            # no thinking-off mode at all (the pinned template forces the answer channel): its
            # hub template reasons in the to=self channel, which think_markers delimits
            thinking_mode=True,
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
    thinking_kwarg: str | None = None,
) -> Any:
    """The subject's tokenizer: local ``tokenizer_dir`` files, else the hub id at ``revision``;
    ``chat_template`` (a file) replaces the tokenizer's own template either way.
    ``thinking_kwarg`` (None = the registered Subject's, else ``enable_thinking``): the kwarg
    ``apply_chat_template`` receives in place of ``enable_thinking`` (``rename_thinking``)."""
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
    if thinking_kwarg is None:
        s = subject_for(hf_id, revision)
        thinking_kwarg = s.thinking_kwarg if s else "enable_thinking"
    return rename_thinking(tok, thinking_kwarg)


def rename_thinking(tok: Any, kwarg: str) -> Any:
    """``tok`` whose ``apply_chat_template`` passes ``enable_thinking`` on as ``kwarg``: every
    adapt render (gate, template checks, read plan, carry, introspection) keeps saying
    ``enable_thinking=False`` and reaches a template that spells the switch differently.
    Unchanged (the same object, unwrapped) for ``enable_thinking``."""
    if kwarg == "enable_thinking":
        return tok
    apply = tok.apply_chat_template

    def apply_chat_template(conversation: Any, *args: Any, **kw: Any) -> Any:
        if "enable_thinking" in kw:
            kw[kwarg] = kw.pop("enable_thinking")
        return apply(conversation, *args, **kw)

    tok.apply_chat_template = apply_chat_template
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
