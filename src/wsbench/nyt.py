"""nyt_connections' puzzle text (plan 0062): the pinned Eyefyre mirror of the NYT Connections
answers, fetched at plan / judge time (sha256-checked, cached as that one file); the committed
bank is ids-only and never holds NYT text."""

import hashlib
import http.client
import json
import os
import random
import re
import urllib.error
import urllib.request
from functools import cache
from pathlib import Path
from typing import Any

from wsbench import mc
from wsbench.registry import bank_path

NAME = "nyt_connections"
REPO = "Eyefyre/NYT-Connections-Answers"
COMMIT = "0c42b26054d4d9e2b1d8fc7b1599925a97fb1ec7"
FILE = "connections.json"
SHA256 = "1bd17c9161c665dbdf2ea8011123a574b7e831cc6442fc7a73fd144d0371f534"
URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{FILE}"
NO_NYT_ENV = "WSB_NO_NYT"  # offline consumers (atlas): the family's plan has no rows

# the pilot's members-only user turn (global-workspace scripts/feas/connections/conn_common.py),
# verbatim; ``{words}`` is filled by str.replace, byte-identical to the pilot's ``.format``
PROMPT_MEMBERS = (
    "Solve this NYT Connections puzzle. Sort the 16 words below into 4 groups of 4 words that "
    "share a connection. Every word belongs to exactly one group. A connection can be anything: a "
    "category, a phrase the words complete, wordplay, hidden words, and so on.\n\n"
    "Words: {words}\n\n"
    "Answer with exactly 4 lines, one per group, each listing the group's 4 words in the format\n"
    "WORD, WORD, WORD, WORD\n"
    "Do not name or explain the connections. Write nothing else."
)


def cache_dir() -> Path:
    root = os.environ.get("WSB_CACHE")
    return (Path(root) if root else Path.home() / ".cache" / "wsbench") / "nyt"


def cache_path() -> Path:
    return cache_dir() / f"{SHA256}.json"


def fetch() -> bytes:
    """The pinned ``connections.json``, from the cache or GitHub; a fetch failure or a sha256
    mismatch raises (SystemExit) naming the URL and both hashes."""
    path = cache_path()
    if path.exists():
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() == SHA256:
            return blob
        path.unlink(missing_ok=True)  # a corrupt / partial cache file: drop it and re-fetch once
    try:
        with urllib.request.urlopen(URL, timeout=120) as r:  # a pinned https URL
            blob = bytes(r.read())
    except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
        raise SystemExit(
            f"{NAME}: cannot fetch {URL} ({e}); pinned sha256 {SHA256}, got none"
        ) from None
    got = hashlib.sha256(blob).hexdigest()
    if got != SHA256:
        raise SystemExit(f"{NAME}: {URL} sha256 {got} != pinned {SHA256}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_bytes(blob)
    os.replace(tmp, path)  # atomic: concurrent processes never read a partial file
    return blob


def parse(blob: bytes) -> dict[int, dict[str, Any]]:
    """``nyt_id -> {"id", "date", "groups": [{"name", "members", "level"}]}`` in the file's
    group order (members stripped, names as published)."""
    out: dict[int, dict[str, Any]] = {}
    for p in json.loads(blob.decode("utf-8")):
        out[int(p["id"])] = {
            "id": int(p["id"]),
            "date": str(p["date"]),
            "groups": [
                {
                    "name": str(g["group"]),
                    "members": [str(m).strip() for m in g["members"]],
                    "level": g.get("level"),
                }
                for g in p["answers"]
            ],
        }
    return out


@cache
def puzzles() -> dict[int, dict[str, Any]]:
    """Every puzzle of the pinned mirror (one fetch per process). Tests replace this function
    (tests/conftest.py ``_offline_nyt``), so nothing fetches offline; every other function here
    reads it through the module attribute."""
    return parse(fetch())


def puzzle(nyt_id: int) -> dict[str, Any]:
    p = puzzles().get(int(nyt_id))
    if p is None:
        raise SystemExit(f"{NAME}: NYT puzzle {nyt_id} is not in the pinned mirror ({URL})")
    return p


def words(nyt_id: int) -> list[str]:
    """The 16 words in the order Qwen saw them: NYT order shuffled by ``conn-<id>`` (the pilot's
    ``make_puzzles.py``)."""
    order = [w for g in puzzle(nyt_id)["groups"] for w in g["members"]]
    random.Random(f"conn-{int(nyt_id)}").shuffle(order)
    return order


def render(nyt_id: int) -> str:
    """The user turn Qwen read (chat template, thinking off, no system prompt)."""
    return PROMPT_MEMBERS.replace("{words}", ", ".join(words(nyt_id)))


def group_name(nyt_id: int, group: int) -> str:
    return str(puzzle(nyt_id)["groups"][int(group)]["name"])


def members(nyt_id: int, idx: list[int]) -> list[str]:
    """A slot's member words from its committed indices into :func:`words`."""
    ws = words(nyt_id)
    return [ws[int(i)] for i in idx]


_QUOTES = re.compile("[\"'`\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u00b4\u2032\u2033]")


def fold_label(s: str) -> str:
    """A connection label's comparison form: ``mc.fold``, every quote mark dropped, whitespace
    collapsed."""
    return " ".join(_QUOTES.sub("", mc.fold(s)).split())


def option_label(opt: dict[str, Any], nyt_id: int) -> str:
    """One committed option's text: its own ``label``, or the NYT group it references
    (``nyt_id`` omitted = the slot's own puzzle)."""
    if "label" in opt:
        return str(opt["label"])
    return group_name(int(opt.get("nyt_id", nyt_id)), int(opt["nyt_group"]))


def bank_items() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(header, items)`` of the registered bank (``registry.bank_path``); reads no NYT text."""
    raw = json.loads(bank_path(NAME).read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if k != "items"}, list(raw["items"])


def referenced_ids(items: list[dict[str, Any]]) -> set[int]:
    """Every NYT puzzle the bank needs: its items and every cross-puzzle option reference."""
    out = {int(it["nyt_id"]) for it in items}
    for it in items:
        for s in it["mc"]:
            out |= {int(o["nyt_id"]) for o in s["options"] if "nyt_id" in o}
    return out
