"""Download one pinned HF snapshot into a Modal volume, on CPU, before an adapt subject's
first deploy (plan 0091; the adapt-bank skill §0). A GPU container never downloads weights.

    WSB_DL_VOLUME=kimi-k2 modal run --detach scripts/download_weights_modal.py \\
        --repo moonshotai/Kimi-K2-Instruct-0905 --revision <40-char sha>

The volume is fixed at import (Modal builds the decorators then), so it comes from the environment
and is baked into the image's env for the container. Layout: the hub cache under ``hf/hub`` (a
subject's own volume, mounted at the default recipe's ``/hf``; ``modal_weights`` = the snapshot dir)
or under ``hub`` for the shared ``adapt-hf-cache`` (``HF_HOME=/hf``). Gated repos read the Modal
secret ``WSB_DL_SECRET`` (default ``hf-camila``). The recipe of the plan-0089 downloads.
"""

import os

import modal

SHARED_VOLUME = "adapt-hf-cache"


def cache_subdir(volume: str) -> str:
    """Where the hub cache lives inside the volume (what the adapt apps' mounts expect)."""
    return "hub" if volume == SHARED_VOLUME else "hf/hub"


def check_revision(revision: str) -> str:
    """A pinned revision is a full commit sha, never a branch or a short sha."""
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise SystemExit(f"--revision {revision!r}: pin the full 40-character commit sha")
    return revision


VOLUME = os.environ.get("WSB_DL_VOLUME", "") if modal.is_local() else os.environ["WSB_DL_VOLUME"]
SECRET = os.environ.get("WSB_DL_SECRET", "hf-camila")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("huggingface_hub[hf_transfer]>=0.35,<1")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1", "WSB_DL_VOLUME": VOLUME})
)
app = modal.App("adapt-weights-download")
vol = (
    modal.Volume.from_name(VOLUME, create_if_missing=VOLUME != SHARED_VOLUME, version=2)
    if VOLUME
    else None
)


@app.function(image=image, volumes={"/vol": vol} if vol else {},
              secrets=[modal.Secret.from_name(SECRET)], timeout=24 * 3600, cpu=16,
              memory=65536)  # fmt: skip
def download(repo: str, revision: str) -> str:
    from huggingface_hub import snapshot_download

    path = snapshot_download(repo, revision=revision, max_workers=32,
                             cache_dir=f"/vol/{cache_subdir(VOLUME)}")  # fmt: skip
    vol.commit()
    n = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)
    return f"{repo}@{revision[:10]} -> {VOLUME}:{path.removeprefix('/vol/')} ({n / 1e9:.0f} GB)"


@app.local_entrypoint()
def main(repo: str, revision: str) -> None:
    if not VOLUME:
        raise SystemExit("set WSB_DL_VOLUME=<volume> (the Subject's modal_volume)")
    print(download.remote(repo, check_revision(revision)), flush=True)
