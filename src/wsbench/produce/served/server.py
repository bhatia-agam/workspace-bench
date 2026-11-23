"""Start and stop a local SGLang server process."""

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(
    model: Path,
    log_path: Path,
    *,
    mem_fraction: float = 0.85,
    extra: list[str] | None = None,
    timeout: float = 1800.0,
) -> tuple[Any, str]:
    """Start `sglang.launch_server` on ``model`` at a free local port, its output appended to
    ``log_path``; return (process, base url) once the server answers. ``extra``: more
    launch_server flags."""
    import httpx

    port = _free_port()
    cmd = [sys.executable, "-m", "sglang.launch_server", "--model-path", str(model)]
    cmd += ["--mem-fraction-static", str(mem_fraction), *(extra or [])]
    cmd += ["--host", "127.0.0.1", "--port", str(port)]
    log = open(log_path, "a")  # noqa: SIM115  (the server's stdout: must outlive this call)
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + timeout
    with httpx.Client() as client:
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-40:])
                raise RuntimeError(f"the model server died during startup:\n{tail}")
            with contextlib.suppress(httpx.HTTPError):
                if client.get(f"{url}/get_model_info", timeout=5).status_code == 200:
                    return proc, url
            time.sleep(3)
    stop_server(proc)
    raise RuntimeError(f"the model server did not start within {timeout:.0f}s (see {log_path})")


def stop_server(proc: Any) -> None:
    """Stop the server's whole process group and wait until it is gone."""
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        return
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(pgid, signal.SIGKILL)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except OSError:
            break
        time.sleep(0.5)
    time.sleep(2)  # GPU teardown before a successor server takes the device
