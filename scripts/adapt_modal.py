"""The subject on Modal, for subjects too big for the 24 GB box (SKILL.md runbook step 0).

A deployed vLLM class the local pipeline calls through ``wsbench.adapt.gate.RemoteRunner``: the
box renders every prompt with the subject's own template (so the gate, read plan and lint are the
same code for every subject), tokenizes it, and Modal only generates from the TOKEN IDS (a BOS the
render carries is never doubled). Text-only (image/video limits 0).

One app per subject. ``ADAPT_SUBJECT=<key>`` at deploy time picks the Subject
(``wsbench/adapt/subjects.py``) whose fields set the app: ``modal_app`` (its name), ``modal_gpu``
(GPU spec, fallbacks in order), ``modal_tp`` (tensor parallel), ``modal_engines`` (vLLM engines
per container, one per GPU: each call's prompts are split across them), ``modal_replicas``
(containers ``RemoteRunner`` fans chunks over), ``modal_image`` (a recipe below), ``modal_volume`` +
``modal_weights`` (a checkpoint dir on the volume, else the hub id cached on the volume) and
``modal_engine`` (extra ``vllm.LLM`` kwargs: ``tokenizer_mode``, ``quantization``, ``moe_backend``
/ ``kernel_config``, ...). Without ``ADAPT_SUBJECT`` it deploys today's shared app
``adapt-subject-llm`` (H200, stock vLLM, ``adapt-hf-cache``), which every subject with the default
modal fields uses (Gemma-4-31B, Qwen3-8B, OLMo-3.1-32B, Qwen3.6-35B-A3B).

Image recipes (``Subject.modal_image``):

- ``default``: CUDA 13 devel + vLLM 0.31.0 + transformers 5.17.0; weights from the hub cache.
- ``glm53``: the glm53 drivers' ``VLLM_GLM_IMAGE`` (global-workspace
  ``scripts/glm53_aff/common.py``): vLLM 0.31.0 + the vllm-metamodels ``glm53`` fork tarball
  (``ceselder/glm-5.3-olens-lens`` @689c5dba), CUDA graphs on. At load the checkpoint is copied
  from the volume to node NVMe and its routed NVFP4 experts are marked W4A16 (Marlin), as
  ``glm53_aff/vllm_gen.VllmGlm`` does; the volume itself is never written.
- ``dsv4``: ``gw-v4-flash-ar/scripts/v4_flash/gen_vllm_modal.py``'s image (CUDA 13 devel +
  vLLM 0.31.0, ``CUDA_HOME`` for DeepGEMM's JIT, ``MAX_JOBS=4``); weights from the ``v4-flash``
  volume (``modal_weights`` = the snapshot dir under ``hf/hub``), the MoE backend override
  (``("moe_backend", "marlin")``) in the Subject's engine kwargs. Layout per Camila's rule
  "always 8xB300": ``modal_gpu=("B300:8",)``, ``modal_tp=1``, ``modal_engines=8`` = one container
  running 8 TP=1 engines (the first warms the JIT caches, then the other 7 start), as
  ``gen_vllm_modal.py`` does.

Prerequisites: the subject's weights volume exists in the env (``glm53-weights`` with
``hf/nvidia__GLM-5.3-NVFP4``; ``v4-flash``); the glm53 fork tarball comes from a public HF repo
(no secret). kimi-k2 has no weights volume: its first load downloads ~1 TB into
``adapt-hf-cache``. A Subject with ``modal_built=False`` (glm-5.3-flash: Agam's text-only app)
is refused here and by RemoteRunner.

Deploy (Camila's env; ``MODAL=/root/.cache/cfinf-modal-venv/bin/modal``, from the repo root)::

    export MODAL_PROFILE=safety-sahan-2 MODAL_ENVIRONMENT=camila-blank
    $MODAL deploy scripts/adapt_modal.py                            # adapt-subject-llm (shared)
    ADAPT_SUBJECT=glm-5.3 $MODAL deploy scripts/adapt_modal.py      # adapt-glm-5.3 (B300:8 TP8)
    ADAPT_SUBJECT=kimi-k2 $MODAL deploy scripts/adapt_modal.py      # adapt-kimi-k2 (B300:8 TP8)
    # then every adapt command for that subject (backend="modal") uses its app transparently;
    # ADAPT_BACKEND=modal sends a box-sized subject to the shared app instead of the 4090

The client side needs MODAL_ENVIRONMENT set to the env the app was deployed in. Redeploy an app
deployed before plan 0060 A3: its methods took text, RemoteRunner now sends token ids.
"""

import atexit
import json
import multiprocessing.util  # noqa: F401  (registers its exit join before our backstop)
import os

import modal

SPEC_ENV = "ADAPT_MODAL_SPEC"  # the deployed spec, baked into the image for the container


def _spec() -> dict:
    """Locally: the spec of ``$ADAPT_SUBJECT`` (or the shared app's), from subjects.py loaded by
    path (the Modal client venv has no wsbench). In the container: the one baked into the image."""
    if not modal.is_local():
        return json.loads(os.environ[SPEC_ENV])
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "src/wsbench/adapt/subjects.py"
    loader = importlib.util.spec_from_file_location("_adapt_subjects", path)
    subjects = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(subjects)
    key = os.environ.get("ADAPT_SUBJECT", "")
    if key and key not in subjects.SUBJECTS:
        raise SystemExit(f"ADAPT_SUBJECT={key!r} is not in wsbench/adapt/subjects.py")
    if key and not subjects.SUBJECTS[key].modal_built:
        raise SystemExit(f"{key}: its modal_app is not built by this script (modal_built=False)")
    return subjects.modal_spec(subjects.SUBJECTS[key] if key else None)


SPEC = _spec()

GLM_LENS_REPO = "ceselder/glm-5.3-olens-lens"  # hosts the vllm-metamodels glm53 fork tarball
GLM_LENS_SHA = "689c5dbae3d2f83dbf969e234a023958f1612185"
GLM_FORK = "vllm_metamodels_glm53_b26f02d.tar.gz"
RECIPES: dict[str, dict] = {
    "default": {"mount": "/hf", "env": {"HF_HOME": "/hf"}, "resources": {}},
    "glm53": {
        "mount": "/vol",
        # VLLM_LENS_CUDA_GRAPHS: the metamodels plugin forces enforce_eager without it
        "env": {"VLLM_LENS_CUDA_GRAPHS": "1",
                "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"},
        # node NVMe for the localized checkpoint (~440 GB of shards), as glm53-rollouts' S1
        "resources": {"ephemeral_disk": 1_000_000, "memory": 512 * 1024, "cpu": 32},
    },
    "dsv4": {
        "mount": "/vol",
        "env": {"HF_HOME": "/vol/hf", "CUDA_HOME": "/usr/local/cuda", "MAX_JOBS": "4"},
        "resources": {"memory": 256 * 1024, "cpu": 16},
    },
}  # fmt: skip
RECIPE = RECIPES[SPEC["image"]]


def _image(recipe: str) -> modal.Image:
    env = {
        **RECIPES[recipe]["env"],
        "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        "TOKENIZERS_PARALLELISM": "false",
        SPEC_ENV: json.dumps(SPEC, sort_keys=True),
    }
    if recipe == "glm53":
        # a CUDA devel base: flashinfer JIT-compiles its sampler with nvcc at engine warm-up
        return (
            modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu24.04", add_python="3.12")
            .entrypoint([])
            .pip_install(
                "vllm==0.31.0",
                "huggingface_hub[hf_transfer]>=0.35",
                # the fork is installed --no-deps (keeps vllm pinned); its runtime deps:
                "zstandard>=0.23.0",
                "datasets>=4.0.0",
                "pydantic>=2.0",
            )
            .run_commands(
                'python -c "from huggingface_hub import hf_hub_download as d; '
                f"print(d('{GLM_LENS_REPO}', '{GLM_FORK}', revision='{GLM_LENS_SHA}', "
                "local_dir='/opt'))\"",
                f"pip install --no-deps /opt/{GLM_FORK}",  # a public repo: no HF secret
            )
            .env(env)
        )
    if recipe == "dsv4":  # DeepGEMM JIT-compiles at runtime and asserts a CUDA home (nvcc)
        return (
            modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu24.04", add_python="3.12")
            .uv_pip_install("vllm==0.31.0")
            .env(env)
        )
    # a CUDA *devel* base: vLLM's flashinfer kernels JIT-compile with nvcc (Gemma-4 failed on
    # debian_slim: "Could not find nvcc"); 13.0 matches vllm 0.31's torch (cu130)
    return (
        modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu22.04", add_python="3.12")
        # tiktoken: Kimi-K2's remote-code tokenizer (vLLM loads it with trust_remote_code)
        .pip_install("vllm==0.31.0", "transformers==5.17.0", "huggingface_hub", "tiktoken")
        .env(env)
    )


def localize(src: str, dst_root: str = "/local", threads: int = 64, chunk: int = 64 << 20) -> str:
    """Copy a checkpoint dir from the (FUSE) volume to node disk with many parallel large reads
    (single-stream volume reads are ~0.3 GB/s): glm53_common.localize, every shard."""
    import shutil
    from concurrent.futures import ThreadPoolExecutor

    dst = os.path.join(dst_root, os.path.basename(src.rstrip("/")))
    os.makedirs(dst, exist_ok=True)
    jobs = []
    for f in sorted(os.listdir(src)):
        s, d = os.path.join(src, f), os.path.join(dst, f)
        if not os.path.isfile(s):
            continue
        if not f.endswith(".safetensors"):
            shutil.copy2(s, d)
            continue
        size = os.path.getsize(s)
        if os.path.exists(d) and os.path.getsize(d) == size:
            continue
        with open(d, "wb") as fh:
            fh.truncate(size)
        jobs += [(s, d, o, min(chunk, size - o)) for o in range(0, size, chunk)]

    def copy(job: tuple) -> None:
        s, d, off, n = job
        fi, fo = os.open(s, os.O_RDONLY), os.open(d, os.O_WRONLY)
        try:
            os.pwrite(fo, os.pread(fi, n, off), off)
        finally:
            os.close(fi)
            os.close(fo)

    with ThreadPoolExecutor(threads) as pool:
        list(pool.map(copy, jobs))
    return dst


def quant_override_w4a16(model_dir: str) -> int:
    """Mark every NVFP4 layer of a LOCAL checkpoint copy W4A16_NVFP4 (W4A4 clips the sink tokens;
    glm53_aff/vllm_gen.quant_override_w4a16). Idempotent."""
    path = os.path.join(model_dir, "hf_quant_config.json")
    with open(path) as fh:
        q = json.load(fh)
    n = 0
    for info in q["quantization"]["quantized_layers"].values():
        if str(info.get("quant_algo", "")).upper() == "NVFP4":
            info["quant_algo"], n = "W4A16_NVFP4", n + 1
    with open(path + ".tmp", "w") as fh:
        json.dump(q, fh, indent=1)
    os.replace(path + ".tmp", path)
    return n


def model_path(spec: dict, model_id: str) -> str:
    """What vLLM loads: the hub id (cached on the volume), or the checkpoint dir on the volume,
    localized and quant-overridden first for the glm53 recipe."""
    if not spec["weights"]:
        return model_id
    path = os.path.join(RECIPES[spec["image"]]["mount"], spec["weights"])
    if spec["image"] == "glm53":
        path = localize(path)
        quant_override_w4a16(path)
    return path


def engine_kwargs(spec: dict, model_id: str, revision: str, max_model_len: int) -> dict:
    """``vllm.LLM`` kwargs: the shared app's settings, the subject's TP, then its overrides."""
    model = model_path(spec, model_id)
    return {
        "model": model,
        "revision": (revision or None) if model == model_id else None,
        "max_model_len": max_model_len,
        "gpu_memory_utilization": 0.90,
        "seed": 0,
        "limit_mm_per_prompt": {"image": 0, "video": 0},
        "tensor_parallel_size": spec["tp"],
        **spec["engine"],
    }


def split(n: int, k: int) -> list[tuple[int, int]]:
    """``n`` prompts as at most ``k`` contiguous non-empty slices, in order."""
    step = -(-n // max(1, k)) if n else 1
    return [(lo, min(n, lo + step)) for lo in range(0, n, step)]


def run_sample(llm, prompts, max_tokens, draws, temperature, top_p, seed) -> list:
    """Greedy + ``draws`` samples per prompt (token ids, or text); prompt i samples with seed+i."""
    from vllm import SamplingParams

    ins = _inputs(prompts)
    g = llm.generate(
        ins, [SamplingParams(temperature=0.0, max_tokens=m) for m in max_tokens], use_tqdm=False
    )
    s = llm.generate(
        ins,
        [
            SamplingParams(
                n=draws, temperature=temperature, top_p=top_p, max_tokens=m, seed=seed + i
            )
            for i, m in enumerate(max_tokens)
        ],
        use_tqdm=False,
    )
    return [(gi.outputs[0].text, [o.text for o in si.outputs]) for gi, si in zip(g, s, strict=True)]


def run_generate(llm, prompts, temperature, max_tokens, seed, top_p, stop_token_ids) -> list:
    """One completion per prompt (token ids, or text): text + generated token ids."""
    from vllm import SamplingParams

    sp = SamplingParams(
        temperature=temperature,
        top_p=top_p,
        top_k=0,
        max_tokens=max_tokens,
        seed=seed,
        stop_token_ids=stop_token_ids or None,
    )
    outs = llm.generate(_inputs(prompts), sp, use_tqdm=False)
    return [{"text": o.outputs[0].text, "ids": list(o.outputs[0].token_ids)} for o in outs]


def _inputs(prompts: list) -> list:
    from vllm.inputs import TokensPrompt

    return [TokensPrompt(prompt_token_ids=p) if isinstance(p, list) else p for p in prompts]


# ---- plan 0060 Phase E (wrong_bridge logP legs) ----
def run_cont_logprobs(llm, ids: list, starts: list) -> list:
    """Per token-id sequence: the sum of its teacher-forced log-probs from ``max(k, 1)`` on
    (vLLM ``prompt_logprobs``; ``gate.sum_cont_logprob`` is the same sum on the local Runner)."""
    from vllm import SamplingParams

    sp = SamplingParams(temperature=0.0, max_tokens=1, prompt_logprobs=0)
    outs = llm.generate(_inputs(ids), sp, use_tqdm=False)
    return [
        float(sum(o.prompt_logprobs[i][x[i]].logprob for i in range(max(k, 1), len(x))))
        for o, x, k in zip(outs, ids, starts, strict=True)
    ]


# ---- end plan 0060 Phase E ----

RUN = {"sample": run_sample, "generate": run_generate, "cont_logprobs": run_cont_logprobs}


def fan_out(engines: list, name: str, args: tuple) -> list:
    """Run one call over the container's engines: contiguous prompt slices (per-prompt fields
    sliced too), sample's seed shifted to the slice start so every prompt keeps the seed it has
    on one engine; results in prompt order. ``engines`` are ``(name, args) -> future`` callables
    whose futures have ``.result()``. EVERY engine's reply is collected before an error is
    raised, so no reply is left in a pipe to be read as the next call's answer."""
    prompts = args[0]
    calls = []
    for eng, (lo, hi) in zip(engines, split(len(prompts), len(engines)), strict=False):
        if name == "sample":  # (prompts, max_tokens, draws, temperature, top_p, seed)
            a = (prompts[lo:hi], args[1][lo:hi], *args[2:5], args[5] + lo)
        elif name == "cont_logprobs":  # (ids, starts): both per prompt (plan 0060 Phase E)
            a = (prompts[lo:hi], args[1][lo:hi])
        else:  # generate: one seed for every prompt, as on one engine
            a = (prompts[lo:hi], *args[1:])
        calls.append(eng(name, a))
    out, errors, died = [], [], False
    for k, c in enumerate(calls):
        try:
            out += c.result()
        except Exception as e:
            errors.append(f"engine {k}: {e}")
            died |= isinstance(e, EngineDiedError)
    if errors:  # a per-request error leaves the drained workers healthy; a death does not
        raise (EngineDiedError if died else RuntimeError)("; ".join(errors))
    return out


def _vllm_engine(kwargs: dict):
    from vllm import LLM

    return LLM(**kwargs)


def _vllm_run(llm, name: str, args: tuple) -> list:
    return RUN[name](llm, *args)


def _engine_worker(gpu: int, kwargs: dict, conn, make=_vllm_engine, run=_vllm_run) -> None:
    """One TP=1 engine pinned to one GPU (gen_vllm_modal.py's data-parallel layout). ``make`` /
    ``run`` are module-level callables (tests pass CPU fakes; spawn pickles them by name)."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    llm = make(kwargs)
    conn.send("ready")
    while (msg := conn.recv()) is not None:
        name, args = msg
        try:
            conn.send(("ok", run(llm, name, args)))
        except Exception as e:  # reported; the container treats it as fatal (SubjectLLM._run)
            conn.send(("err", repr(e)))


class EngineDiedError(RuntimeError):
    """An engine process is dead or unreachable: fatal for the container."""


class _Engine:
    """A spawned engine process; calling it sends a request, ``.result()`` waits for the reply
    (or raises once the process is dead: never hangs on a dead engine). Not daemonic: vLLM's V1
    EngineCore spawns a child, which a daemonic process may not have."""

    POLL_S = 2.0

    def __init__(self, gpu: int, kwargs: dict, make=_vllm_engine, run=_vllm_run) -> None:
        import multiprocessing as mp

        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_engine_worker, args=(gpu, kwargs, child, make, run))
        self.proc.start()
        child.close()  # only the worker holds its end: a dead worker reads as EOF here
        self.error: str | None = None

    def _recv(self):
        while not self.conn.poll(self.POLL_S):
            if not self.proc.is_alive():
                break
        try:
            return self.conn.recv()
        except (EOFError, OSError):
            raise EngineDiedError(f"engine process died (exit code {self.proc.exitcode})") from None

    def wait_ready(self) -> None:
        if self._recv() != "ready":
            raise EngineDiedError("engine failed to start")

    def __call__(self, name: str, args: tuple) -> "_Engine":
        try:
            self.conn.send((name, args))
            self.error = None
        except OSError as e:  # a dead engine: reported by result(), after the others drained
            self.error = f"engine process unreachable: {e!r}"
        return self

    def result(self) -> list:
        if self.error:
            raise EngineDiedError(self.error)
        status, out = self._recv()
        if status != "ok":
            raise RuntimeError(f"engine error: {out}")
        return out

    def close(self, timeout: float = 60.0) -> None:
        """Ask the worker to exit (vLLM shuts its EngineCore down), then terminate a straggler."""
        import contextlib

        with contextlib.suppress(OSError):  # already dead
            self.conn.send(None)
        self.proc.join(timeout)
        if self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(10)
        self.conn.close()


_STARTED: list = []  # every engine process this process started (the atexit backstop)


def stop_engines(engines: list, timeout: float = 60.0) -> None:
    for e in engines:
        e.close(timeout)


@atexit.register  # registered after multiprocessing's own exit hook, so it runs first (LIFO)
def _close_started() -> None:
    stop_engines([e for e in _STARTED if e.proc.is_alive()], timeout=10.0)


def start_engines(n: int, kwargs: dict, into: list, make=_vllm_engine, run=_vllm_run) -> None:
    """``n`` engines, one per GPU, appended to ``into`` as each starts. The first warms the JIT
    caches, then the rest start together. If any fails to come up, every started engine is
    terminated and joined before the error propagates (a non-daemonic straggler would block
    multiprocessing's exit join and hang the container)."""
    try:
        for gpu in range(n):
            e = _Engine(gpu, kwargs, make, run)
            into.append(e)
            _STARTED.append(e)
            if gpu == 0:
                e.wait_ready()  # its JIT kernels are built: the siblings reuse the cache
        for e in into[1:]:
            e.wait_ready()
    except BaseException:
        stop_engines(into, timeout=5.0)
        raise


app = modal.App(SPEC["app"])
volume = modal.Volume.from_name(SPEC["volume"], create_if_missing=SPEC["image"] == "default")
_cls_options = dict(RECIPE["resources"])
if SPEC["replicas"] > 1:  # the containers RemoteRunner fans out over
    _cls_options["max_containers"] = SPEC["replicas"]


@app.cls(
    image=_image(SPEC["image"]),
    gpu=SPEC["gpu"][0] if len(SPEC["gpu"]) == 1 else SPEC["gpu"],
    # the weights volumes (glm53-weights, v4-flash) are read-only here; the hub cache is written
    volumes={RECIPE["mount"]: volume if SPEC["image"] == "default" else volume.read_only()},
    timeout=6 * 3600,
    scaledown_window=600,
    **_cls_options,
)
class SubjectLLM:
    model_id: str = modal.parameter()
    revision: str = modal.parameter(default="")
    max_model_len: int = modal.parameter(default=4096)

    @modal.enter()
    def load(self) -> None:
        kwargs = engine_kwargs(SPEC, self.model_id, self.revision, self.max_model_len)
        if SPEC["engines"] > 1:  # one TP=1 engine per GPU of the container, data parallel
            self.engines: list = []
            start_engines(SPEC["engines"], kwargs, self.engines)
        else:
            from vllm import LLM

            self.llm = LLM(**kwargs)
        if not SPEC["weights"]:  # a first load cached the hub weights on the volume
            volume.commit()

    @modal.exit()
    def stop(self) -> None:
        stop_engines(getattr(self, "engines", []))

    def _run(self, name: str, args: tuple) -> list:
        if SPEC["engines"] == 1:
            return RUN[name](self.llm, *args)
        # a dead engine is fatal for the container: a partial engine set must not keep serving
        # (Modal replaces the container; the client sees this call fail). A per-request error
        # (e.g. a prompt over max_model_len) is raised to the caller: fan_out drained every
        # reply, so the workers stay healthy and in sync.
        dead = [k for k, e in enumerate(self.engines) if not e.proc.is_alive()]
        try:
            if dead:
                raise EngineDiedError(f"engine(s) {dead} died")
            return fan_out(self.engines, name, args)
        except EngineDiedError as e:
            print(f"FATAL: {e}; stopping the container", flush=True)
            for eng in self.engines:
                if eng.proc.is_alive():
                    eng.proc.terminate()
            os._exit(1)

    @modal.method()
    def sample(
        self,
        prompts: list,
        max_tokens: list[int],
        draws: int,
        temperature: float,
        top_p: float,
        seed: int,
    ) -> list[tuple[str, list[str]]]:
        """Greedy + ``draws`` samples per prompt (token ids, or text): Runner.sample's contract."""
        return self._run("sample", (prompts, max_tokens, draws, temperature, top_p, seed))

    @modal.method()
    def generate(
        self,
        prompts: list,
        temperature: float,
        max_tokens: int,
        seed: int,
        top_p: float = 1.0,
        stop_token_ids: list[int] | None = None,
    ) -> list[dict]:
        """One completion per prompt (token ids, or text): text + generated token ids."""
        return self._run(
            "generate", (prompts, temperature, max_tokens, seed, top_p, stop_token_ids)
        )

    # ---- plan 0060 Phase E (wrong_bridge logP legs): RemoteRunner.cont_logprobs ----
    @modal.method()
    def cont_logprobs(self, ids: list[list[int]], starts: list[int]) -> list[float]:
        """Teacher-forced sum of log P over ``ids[i][max(k, 1):]`` per sequence (token ids and
        start positions built locally by ``gate.cont_jobs``), in input order."""
        return self._run("cont_logprobs", (ids, starts))

    # ---- end plan 0060 Phase E ----
