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
    """The command line of each container: the caller's keys plus its shard."""
    return [[*argv, f"shard={i}", f"shards={gpus}", "launcher=local"] for i in range(gpus)]


def launch(
    argv: Sequence[str],
    *,
    gpus: int,
    gpu: str,
    volume: str,
    mount: str,
    secret: str,
    app_name: str,
    timeout: int,
    sglang: str,
) -> int:
    """Run `wsbench read <argv> shard=i shards=<gpus>` in ``gpus`` containers and return the
    worst exit code. ``volume`` is mounted at ``mount``: the store, the lens bundle and the
    readouts root in ``argv`` must be paths under it. ``secret``: a Modal secret that holds
    ``HF_TOKEN`` (only needed for a gated or private dataset), or empty."""
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
    secrets = [modal.Secret.from_name(secret)] if secret else []

    @app.function(
        image=image,
        gpu=gpu,
        volumes={mount: data},
        secrets=secrets,
        timeout=timeout,
        serialized=True,
    )
    def read_shard(args: list[str]) -> int:
        import subprocess
        import sys

        code = subprocess.run([sys.executable, "-m", "wsbench", "read", *args]).returncode
        data.commit()
        return code

    with app.run():
        codes = list(read_shard.map(shard_args(argv, gpus)))
    return max(codes, default=0)
