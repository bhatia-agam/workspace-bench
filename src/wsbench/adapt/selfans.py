"""Shared helpers for the self-answer families re-derived on the subject (plan 0060 Phase E:
``msdm.py`` and ``kcutoff.py``). Their gold is the subject's OWN stable answer, so the gate is
the family's own consistency rule re-run on the subject, never a carried-over Qwen label.

- ``norm``: the source pipelines' answer normaliser (global-workspace
  ``olens_suite/knowledge_cutoff/labels.py`` = ``scripts/feas/self_answers/common.py``), the first
  step before any canonicaliser.
- ``claude_json``: a JSON-replying Claude call through ``auth.Session`` (the adapt grader's
  credentials; ``WSB_ANTHROPIC_AUTH=sdk`` off Agam's box), cached on disk per (model, prompt) so a
  re-run re-asks nothing that was answered.
- ``label_of``: one string -> its canonical label for an item (a canonicaliser map, then the
  item's known labels, else the normalised string itself).

No module here builds a vLLM engine: generation goes through ``run._runner(model)``.
"""

import hashlib
import json
import re
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REFUSAL = "REFUSAL"
ATTEMPTS = 4

_PREAMBLE = re.compile(
    r"^(my favorite [a-z ]+ (is|would be)|i would name it|i'd name it|i would pick|i'd pick|"
    r"i'd choose|i would choose)\s*:?\s*"
)

# ``ask(prompt, valid=None)`` -> parsed JSON reply (None when unparsable or never valid)
AskJson = Callable[..., Any]
Valid = Callable[[Any], bool]


def norm(s: str) -> str:
    """Normalised answer string ("" for an empty answer): NFKC, first line only, lower-case,
    quotes / markdown stripped, a few answer preambles, a leading article, trailing punctuation
    and a trailing parenthetical removed. Verbatim from the source pipelines."""
    s = unicodedata.normalize("NFKC", s).replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s.strip().split("\n")[0]).lower() if s.strip() else ""
    s = re.sub("[*_\"'\u201c\u201d\u2018\u2019`]", "", s)
    s = _PREAMBLE.sub("", s)
    s = re.sub(r"^(the|a|an)\s+", "", s)
    s = re.sub(r"[.!,;:]+$", "", s).strip()
    return re.sub(r"\s*\(.*\)$", "", s).strip()


# a deterministic floor under the canonicaliser (which the source relied on alone): answers that
# commit to nothing are refusals even when no Claude call is made (``llm=none``)
_REFUSAL_RX = re.compile(  # on norm()'s output: apostrophes are already stripped
    r"^(i (do not|dont|cannot|cant|am not able to|have no)|im not (sure|able)|not sure|unknown$|"
    r"no (information|data|answer)|sorry|unable to|as of my|my (knowledge|training))"
)


def looks_refusal(n: str) -> bool:
    """A normalised answer that commits to no specific answer ("i dont know", "not sure")."""
    return bool(_REFUSAL_RX.match(n))


def known_index(known: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """``{norm(form): label}`` over every known label and its written forms; a normalised form
    claimed by two labels is ambiguous and maps to neither."""
    seen: dict[str, set[str]] = {}
    for label, forms in known.items():
        for f in [label, *forms]:
            n = norm(str(f))
            if n:
                seen.setdefault(n, set()).add(label)
    return {n: next(iter(ls)) for n, ls in seen.items() if len(ls) == 1}


def label_of(s: str | None, cmap: Mapping[str, str], index: Mapping[str, str]) -> str:
    """The canonical label of one raw answer: ``REFUSAL`` for an empty answer or a refusal; the
    canonicaliser's label (``cmap``, keyed by the normalised string) when it has one; else the
    known label whose written form it is (``index``); else the normalised string itself. A label
    that is itself a known form resolves to that known label, so a canonicaliser's spelling of a
    registered option lands on the option's exact string."""
    n = norm(s or "")
    if not n:
        return REFUSAL
    if n not in cmap and n not in index and looks_refusal(n):
        return REFUSAL
    v = cmap.get(n, n)
    if str(v).strip().upper() == REFUSAL:
        return REFUSAL
    v = norm(str(v)) or REFUSAL
    if v == REFUSAL:
        return REFUSAL
    return index.get(v, v)


def ranked(values: Iterable[str | None], bad: set[str | None]) -> list[str]:
    """Distinct usable values by frequency, ties by first appearance (source
    ``options._ranked``)."""
    seq = [v for v in values if v is not None and v not in bad]
    cnt = Counter(seq)
    first = {v: seq.index(v) for v in cnt}
    return sorted(cnt, key=lambda v: (-cnt[v], first[v]))


def ranked_models(
    answers: Mapping[str, str | None], order: Sequence[str], bad: set[str | None]
) -> list[tuple[str, list[str]]]:
    """(answer, [models giving it]) by frequency, ties by the earliest model in ``order``; models
    outside ``order`` rank after it, alphabetically (source ``options._ranked_models``)."""
    by: dict[str, list[str]] = {}
    extra = sorted(m for m in answers if m not in order)
    for m in [*order, *extra]:
        v = answers.get(m)
        if v is None or v in bad:
            continue
        by.setdefault(v, []).append(m)
    rank = {m: i for i, m in enumerate([*order, *extra])}
    return sorted(by.items(), key=lambda kv: (-len(kv[1]), min(rank[m] for m in kv[1])))


def seeded_order(options: Sequence[str], key: str) -> list[str]:
    """Options in a per-item seeded shuffle (SHA-256 of ``key``; source
    ``options.seeded_order``)."""
    import random

    seed = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    out = list(options)
    random.Random(seed).shuffle(out)
    return out


def first_json(text: str) -> Any:
    """The first decodable JSON object in a reply (fences and prose around it are ignored)."""
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


class JsonCache:
    """Append-only jsonl ``{k, v}`` cache: a crash loses only the calls in flight."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.d: dict[str, Any] = {}
        self._lock = threading.Lock()
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if text and not text.endswith("\n"):  # a run killed mid-append: close the torn line
                with path.open("a", encoding="utf-8") as fh:  # so the next put starts clean
                    fh.write("\n")
            for line in text.split("\n"):
                if not line.strip():
                    continue
                try:  # a run killed mid-append leaves a partial line: skip it (re-asked later)
                    rec = json.loads(line)
                    self.d[rec["k"]] = rec["v"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

    def put(self, k: str, v: Any) -> None:
        with self._lock:
            self.d[k] = v
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")


def claude_json(model: str, cache_path: Path | None = None, max_tokens: int = 4000) -> AskJson:
    """``prompt -> parsed JSON`` on ``model`` (a Claude id) via ``auth.Session``; transient errors
    and unparsable replies are retried, then ``None``. A 401 on the newest token stops the run.
    Replies are cached per (model, prompt) in ``cache_path`` only when ``valid(reply)`` holds (the
    caller's completeness check): an invalid reply is retried like an unparsable one, never cached,
    and a cached reply that fails ``valid`` is ignored and re-asked. ``None`` is never cached."""
    import anthropic

    from .auth import PUSH, Session, TokenExpired

    session = Session()
    cache = JsonCache(cache_path) if cache_path else None

    def ask(prompt: str, valid: Valid | None = None) -> Any:
        ok = valid or (lambda _js: True)
        key = hashlib.sha256(json.dumps([model, prompt]).encode()).hexdigest()
        if cache is not None and key in cache.d and ok(cache.d[key]):
            return cache.d[key]
        attempt = 0
        while attempt < ATTEMPTS:
            seen = session.pushed
            try:
                msg = session.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(b.text for b in msg.content if b.type == "text")
                if (js := first_json(text)) is not None and ok(js):
                    if cache is not None:
                        cache.put(key, js)
                    return js
                attempt += 1
            except anthropic.AuthenticationError as e:
                if not session.refresh(seen):
                    raise TokenExpired(PUSH) from e
            except anthropic.APIError:
                time.sleep(2**attempt)
                attempt += 1
        return None

    return ask


def pmap(fn: Callable[[Any], Any], jobs: Sequence[Any], workers: int = 16) -> list[Any]:
    """``[fn(j) for j in jobs]`` on a thread pool (Claude calls are network-bound)."""
    from concurrent.futures import ThreadPoolExecutor

    if workers <= 1 or len(jobs) <= 1:
        return [fn(j) for j in jobs]
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(fn, jobs))
