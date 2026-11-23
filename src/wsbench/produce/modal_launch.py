"""An optional Modal launcher for `wsbench read`: one container per GPU, each running the same
command on its own shard against a shared volume. Imported only for `launcher=modal`; needs the
`modal` package and a Modal account. Reference code: adapt the image to your serving stack."""

from collections.abc import Sequence
from typing import Any

from wsbench.registry import REPO_ROOT

# SGLang's kernels need the CUDA 12.9 compiler; the package's own dependencies follow
BASE_IMAGE = "nvidia/cuda:12.9.1-devel-ubuntu24.04"
PACKAGES = (
    "httpx",
    "safetensors",
    "accelerate",  # a capture loads the subject model with `device_map=`
    "transformers>=5",
    "numpy>=1.26",
    "pydra-config>=0.0.17",
    "openai>=1.40",
    "anthropic>=1.0",
    "pronouncing>=0.2",
)
REMOTE = "/opt/wsbench"  # where the checkout sits in the container
IGNORE = [".git", ".venv", "adapted", "outputs", "**/__pycache__", "tests"]


def shard_args(argv: Sequence[str], gpus: int) -> list[list[str]]:
    """The command line of each read container: the caller's keys plus its shard. The
    capture step ran before, so a cell that is still missing is an error there."""
    extra = ["launcher=local", "capture=False"]
    return [[*argv, f"shard={i}", f"shards={gpus}", *extra] for i in range(gpus)]


def launch(
    argv: Sequence[str],
    *,
    capture_argv: Sequence[str] | None,
    gpus: int,
    gpu: str,
    volume: str,
    mount: str,
    secret: str,
    app_name: str,
    timeout: int,
    sglang: str,
    model_volume: str = "",
    model_mount: str = "/model",
    lens_volume: str = "",
    lens_mount: str = "/lens",
) -> int:
    """Three steps, each `wsbench` in a container, and the worst exit code:

    1. one GPU container runs `wsbench capture <capture_argv>`: it fills the store on the
       volume from the dataset and runs the subject model for the cells the dataset lacks, so
       the model is loaded at most once (skipped when ``capture_argv`` is None);
    2. ``gpus`` GPU containers run `wsbench read <argv> shard=i shards=<gpus>`, each writing
       its parts;
    3. one CPU container runs `wsbench read <argv> shards=<gpus> join=True`, which writes
       every eval's readouts file and sidecar from the parts.

    ``volume`` is mounted at ``mount`` and holds the store and the readouts root. The subject
    model's files and the lens bundle may live on volumes of their own, mounted read-only at
    ``model_mount`` / ``lens_mount`` (`model=` and `lens=` in ``argv`` are then paths under
    those). ``secret``: a Modal secret that holds ``HF_TOKEN``, or empty."""
    import modal

    image: Any = (
        modal.Image.from_registry(BASE_IMAGE, add_python="3.12")
        .apt_install("git", "curl", "libnuma1")
        .pip_install(sglang, *PACKAGES)
        .env({"PYTHONPATH": f"{REMOTE}/src", "PYTHONUNBUFFERED": "1"})
        .add_local_dir(str(REPO_ROOT), REMOTE, ignore=IGNORE)
    )
    app = modal.App(app_name)
    data = modal.Volume.from_name(volume, create_if_missing=True)
    volumes: dict[str, Any] = {mount: data}
    for name, where in ((model_volume, model_mount), (lens_volume, lens_mount)):
        if name:
            volumes[where] = modal.Volume.from_name(name).read_only()
    secrets = [modal.Secret.from_name(secret)] if secret else []
    shared: dict[str, Any] = {
        "image": image,
        "volumes": volumes,
        "secrets": secrets,
        "timeout": timeout,
        "serialized": True,
    }

    def wsbench(args: list[str]) -> int:
        import subprocess
        import sys

        data.reload()  # what the earlier steps committed
        code = subprocess.run([sys.executable, "-m", "wsbench", *args]).returncode
        data.commit()
        return code

    # one body, registered twice under its own name: with a GPU and without
    on_gpu = app.function(name="wsbench_gpu", gpu=gpu, **shared)(wsbench)
    on_cpu = app.function(name="wsbench_cpu", **shared)(wsbench)
    # enable_output: the containers' lines are printed here as they run, not only in Modal's logs
    with modal.enable_output(), app.run():
        if capture_argv is not None:
            code = on_gpu.remote(["capture", *capture_argv])
            if code:
                return int(code)
        codes = list(on_gpu.map([["read", *a] for a in shard_args(argv, gpus)]))
        if max(codes, default=0):
            return int(max(codes))
        join = ["read", *argv, f"shards={gpus}", "join=True", "launcher=local"]
        return int(on_cpu.remote(join))
