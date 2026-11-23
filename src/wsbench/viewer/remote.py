"""Run files that live on a volume (``modal://<volume>[@<environment>]/<path>``, or a directory
laid out like one, ``file://``): listing, fetching into the local cache (``$WSB_VIEWER_CACHE``)
and reading one question's readouts on demand. A file that cannot be had gives a marker."""

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CACHE_ENV = "WSB_VIEWER_CACHE"
DEFAULT_CACHE = "~/.cache/wsbench-viewer"
MODAL = "modal://"
FILE = "file://"
RETRY_SECONDS = 60  # a failed fetch is not tried again for this long
LIST_WORKERS = 8
GET_WORKERS = 8
GET_SECONDS = 1800
INDEX_SUFFIX = ".spans.json"

_failed: dict[str, tuple[float, str]] = {}
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


class UnavailableError(Exception):
    """The file is not on this machine and could not be fetched; the message says why."""


@dataclass(frozen=True)
class Entry:
    """One file of a volume listing; ``path`` is relative to the volume root."""

    path: str
    size: int
    mtime: int

    def sig(self) -> str:
        return f"{self.path}:{self.size}:{self.mtime}"


def cache_root(cache: str | os.PathLike | None = None) -> Path:
    return Path(cache or os.environ.get(CACHE_ENV) or DEFAULT_CACHE).expanduser()


def is_remote(path: str) -> bool:
    return path.startswith((MODAL, FILE))


def marker(where: str, why: str = "") -> str:
    """The text a page shows in place of readouts it cannot read."""
    return f"[readouts not available here: {where}" + (f" ({why})" if why else "") + "]"


def is_marker(text: str) -> bool:
    return text.startswith("[readouts not available here: ")


# ------------------------------------------------------------------ volumes


class Volume:
    """A place that holds run files; ``url(path)`` is what the store records."""

    def url(self, path: str) -> str:
        raise NotImplementedError

    def ls(self, path: str) -> list[Entry]:
        """Every file under ``path``, recursively; [] when there is none."""
        raise NotImplementedError

    def get(self, path: str, dest: Path) -> None:
        raise NotImplementedError


class LocalVolume(Volume):
    """A directory laid out like a volume."""

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root).expanduser().resolve()

    def url(self, path: str) -> str:
        return f"{FILE}{self.root}/{path.strip('/')}"

    def ls(self, path: str) -> list[Entry]:
        base = self.root / path.strip("/")
        if base.is_file():
            files = [base]
        else:
            files = sorted(p for p in base.rglob("*") if p.is_file()) if base.is_dir() else []
        out = []
        for p in files:
            st = p.stat()
            out.append(Entry(p.relative_to(self.root).as_posix(), st.st_size, int(st.st_mtime)))
        return out

    def get(self, path: str, dest: Path) -> None:
        src = self.root / path.strip("/")
        if not src.is_file():
            raise UnavailableError(f"{src} does not exist")
        shutil.copyfile(src, dest)


class ModalVolume(Volume):
    """A Modal volume, through the ``modal`` command (read only: ``ls`` and ``get``)."""

    def __init__(self, name: str, environment: str | None = None) -> None:
        self.name = name
        self.environment = environment or None

    def url(self, path: str) -> str:
        env = f"@{self.environment}" if self.environment else ""
        return f"{MODAL}{self.name}{env}/{path.strip('/')}"

    def _run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess:
        exe = shutil.which("modal")
        if exe is None:
            raise UnavailableError("the modal command is not installed")
        env = dict(os.environ)
        if self.environment:
            env["MODAL_ENVIRONMENT"] = self.environment
        try:
            return subprocess.run(
                [exe, *args], capture_output=True, text=True, timeout=timeout, env=env, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise UnavailableError(f"modal {args[1]} failed: {type(e).__name__}") from e

    def _ls_dir(self, path: str) -> list[dict[str, Any]]:
        r = self._run(["volume", "ls", "--json", self.name, path.strip("/") or "/"], 300)
        if r.returncode != 0:
            err = _last_line(r.stderr)
            if any(x in err.lower() for x in ("not found", "no such", "does not exist")):
                return []
            raise UnavailableError(f"cannot list volume {self.name}: {err}")
        try:
            return json.loads(r.stdout) if r.stdout.strip() else []
        except ValueError as e:
            raise UnavailableError(f"cannot list volume {self.name}: unreadable listing") from e

    def ls(self, path: str) -> list[Entry]:
        out: list[Entry] = []
        todo = [path.strip("/")]
        with ThreadPoolExecutor(LIST_WORKERS) as pool:
            while todo:
                found = list(pool.map(self._ls_dir, todo))
                todo = []
                for rows in found:
                    for e in rows:
                        if e.get("type") == "dir":
                            todo.append(e["filename"])
                        else:
                            out.append(Entry(e["filename"], int(e.get("size") or 0), _stamp(e)))
        return sorted(out, key=lambda e: e.path)

    def get(self, path: str, dest: Path) -> None:
        r = self._run(["volume", "get", "--force", self.name, path.strip("/"), str(dest)],
                      GET_SECONDS)  # fmt: skip
        if r.returncode != 0 or not dest.is_file():
            raise UnavailableError(f"cannot fetch from volume {self.name}: {_last_line(r.stderr)}")


def _last_line(text: str) -> str:
    lines = [x.strip(" │╭╰─╮╯") for x in (text or "").splitlines()]
    lines = [x for x in lines if x]
    return (lines[-1] if lines else "no error text")[:200]


def _stamp(entry: dict[str, Any]) -> int:
    try:
        return int(datetime.fromisoformat(str(entry.get("created_modified"))).timestamp())
    except ValueError:
        return 0


def open_volume(spec: str, environment: str | None = None) -> Volume:
    """A volume from a manifest's ``volume`` value: an existing directory (or ``file://<dir>``)
    is a local copy, anything else the name of a Modal volume."""
    if spec.startswith(FILE):
        return LocalVolume(spec[len(FILE) :])
    if spec.startswith(MODAL):
        spec = spec[len(MODAL) :].strip("/")
        if "@" in spec:
            spec, environment = spec.split("@", 1)
    if "/" in spec or Path(spec).expanduser().is_dir():
        return LocalVolume(spec)
    return ModalVolume(spec, environment)


def split(url: str) -> tuple[Volume, str]:
    """``(volume, path inside it)`` of an address; a ``file://`` address is its own file."""
    if url.startswith(MODAL):
        head, _, path = url[len(MODAL) :].partition("/")
        name, _, env = head.partition("@")
        return ModalVolume(name, env or None), path
    if url.startswith(FILE):
        p = Path(url[len(FILE) :])
        return LocalVolume(p.parent), p.name
    raise ValueError(f"not a volume address: {url}")


# ------------------------------------------------------------------ the cache


def cache_path(url: str, cache: str | os.PathLike | None = None) -> Path:
    scheme, rest = url.split("://", 1)
    return cache_root(cache) / scheme / re.sub(r"[^A-Za-z0-9._/@-]+", "_", rest.lstrip("/"))


def _lock(key: str) -> threading.Lock:
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def fetch_to(volume: Volume, entry: Entry, dest: Path) -> bool:
    """Download one listed file to ``dest`` unless the copy there has its size and time.
    Returns True when it was downloaded."""
    if dest.is_file():
        st = dest.stat()
        if st.st_size == entry.size and int(st.st_mtime) == entry.mtime:
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    volume.get(entry.path, tmp)
    os.utime(tmp, (entry.mtime, entry.mtime))
    tmp.replace(dest)
    return True


def fetch_all(volume: Volume, pairs: Iterable[tuple[Entry, Path]]) -> tuple[int, int]:
    """Download every ``(entry, destination)``; ``(files downloaded, bytes downloaded)``."""
    pairs = list(pairs)
    with ThreadPoolExecutor(GET_WORKERS) as pool:
        done = list(pool.map(lambda p: fetch_to(volume, p[0], p[1]), pairs))
    return sum(done), sum(e.size for (e, _d), got in zip(pairs, done, strict=True) if got)


def fetch(url: str, cache: str | os.PathLike | None = None) -> Path:
    """The local copy of a file at an address, downloading it once. ``UnavailableError`` when it
    cannot be had; a failure is remembered for a minute so a page of cells asks once."""
    dest = cache_path(url, cache)
    if dest.is_file():
        return dest
    with _lock(str(dest)):
        if dest.is_file():
            return dest
        failed = _failed.get(url)
        if failed and time.time() - failed[0] < RETRY_SECONDS:
            raise UnavailableError(failed[1])
        volume, path = split(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            volume.get(path, tmp)
        except UnavailableError as e:
            _failed[url] = (time.time(), str(e))
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(dest)
        return dest


def local_file(path: str, cache: str | os.PathLike | None = None) -> Path:
    """A readable local file for a ``source.path`` of a run database: the path itself, or the
    cached copy of an address. ``UnavailableError`` when neither can be had."""
    if is_remote(path):
        return fetch(path, cache)
    p = Path(path)
    if not p.is_file():
        raise UnavailableError("the file is gone from this machine")
    return p


def exists(path: str, cache: str | os.PathLike | None = None) -> tuple[bool, str]:
    """Whether a ``source.path`` can be read without a download: ``(yes, how)`` with ``how``
    one of local, cached, on a volume (not checked), missing."""
    if not is_remote(path):
        return (True, "local") if Path(path).is_file() else (False, "missing")
    if cache_path(path, cache).is_file():
        return True, "cached"
    if path.startswith(FILE):
        return (True, "local") if Path(path[len(FILE) :]).is_file() else (False, "missing")
    return False, "on a volume"


# ------------------------------------------------------------------ one question's readouts


def item_index(path: Path) -> dict[str, list[list[int]]]:
    """``{item id: [[offset, length], ...]}`` of a readouts file, built once and kept beside
    the cached file (the next question of the same eval is then one seek per cell)."""
    side = path.with_name(path.name + INDEX_SUFFIX)
    st = path.stat()
    stamp = [st.st_size, int(st.st_mtime)]
    if side.is_file():
        try:
            saved = json.loads(side.read_text(encoding="utf-8"))
            if saved.get("file") == stamp:
                return saved["items"]
        except (ValueError, OSError, KeyError):
            pass
    items: dict[str, list[list[int]]] = {}
    id_re = re.compile(rb'"id":\s*"((?:[^"\\]|\\.)*)"')
    with open(path, "rb") as fh:
        off = 0
        for raw in fh:
            m = id_re.search(raw)
            if m:
                try:
                    iid = json.loads(b'"' + m.group(1) + b'"')
                except ValueError:
                    iid = None
                if iid is not None:
                    items.setdefault(iid, []).append([off, len(raw)])
            off += len(raw)
    try:
        tmp = side.with_name(side.name + ".part")
        tmp.write_text(json.dumps({"file": stamp, "items": items}), encoding="utf-8")
        tmp.replace(side)
    except OSError:
        pass  # a read-only cache: the index is rebuilt next time
    return items


def item_rows(paths: Iterable[str], item: str, cache: str | os.PathLike | None = None) -> list:
    """The readout rows of one question from the files at ``paths`` (local paths or
    addresses). ``UnavailableError`` when a file cannot be had."""
    out = []
    for p in paths:
        local = local_file(p, cache)
        spans = item_index(local).get(item) or []
        with open(local, "rb") as fh:
            for off, length in spans:
                fh.seek(off)
                try:
                    rec = json.loads(fh.read(length))
                except ValueError:
                    continue
                if str(rec.get("id")) == item:
                    out.append(rec)
    return out
