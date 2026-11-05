"""The model grader for answers a deterministic match cannot decide (aliases, translations, prose
golds). Same rubric as ``capable`` (``GRADE_SYSTEM``); it reads only the subject's answer."""

import hashlib
import json
import time
from collections.abc import Callable

from wsbench.capable.run import GRADE_SYSTEM

from . import store
from .gate import Ask

ATTEMPTS = 4
# families whose latent IS the form (an L2 word, a correct spelling): the shared rubric's
# "a faithful translation is correct" would pass an English answer to an L2 prompt
STRICT_FORM = (
    " EXCEPTION for this question: the expected answer's language, script and spelling are what "
    "is being tested. An answer in a different language (a translation), a transliteration, or a "
    "misspelling of the expected word is NOT correct, even if it means the same thing. Missing "
    "diacritics count as a misspelling. When the expected answer has several words, an answer "
    "giving only some of them (e.g. 'gigi' for 'dokter gigi') is NOT correct."
)

# Per-Ask rubrics (``Ask.meta["rubric"]``, plan 0066 §2.2): ``id -> (prompt, JSON key)``. The
# prompt is filled by ``str.replace`` of ``{cont}`` with the answer and sent as the only user
# turn, no system prompt, as its source script sends it. The verdict is the key's boolean; for a
# rubric in ``gate.NEGATIVE_RUBRICS`` the leg passes on False.
B_PROMPT = (
    # scripts/buggy_twin_gate_grade.py B_PROMPT verbatim, its ``.format`` brace escapes un-doubled
    "Here is a continuation a model wrote after reading a short program:\n\n{cont}\n\nDoes the "
    "continuation claim that the program has a bug, an error, a crash or a wrong result? Neutral "
    "commentary, explanations of what it does, or test code that agrees with it are NOT a bug "
    'claim. Reply with JSON only: {"bug_claim": true} or {"bug_claim": false}.'
)
RUBRICS: dict[str, tuple[str, str]] = {"buggy_bug_claim": (B_PROMPT, "bug_claim")}
# plan 0066 delta audit B1: Opus refuses to grade some bare programs (stop_reason "refusal", no
# text; 20 of 147 GLM-5.3 bugclaim grades). For these rubrics a refused grade is re-asked ONCE
# on this model (the jailbreak precedent, digest.REFUSAL_MODEL); the serving model is recorded
# beside the persisted verdict and counted in ``grade.served_by``
REFUSAL_FALLBACK = "claude-sonnet-5-5"
FALLBACK_RUBRICS = frozenset({"buggy_bug_claim"})


def rubric_of(ask: Ask) -> str | None:
    """The Ask's rubric id, or None for the default "does the answer state the gold" rubric."""
    rid = ask.meta.get("rubric")
    if rid is not None and rid not in RUBRICS:
        raise ValueError(f"{ask.item_id}/{ask.leg}: unknown grading rubric {rid!r}")
    return rid


def cache_key(ask: Ask, answer: str) -> str:
    """The grade-cache key. The rubric is part of it (a lenient verdict is not reused for a strict
    question, nor a "correct" verdict for a bug-claim one); with no per-Ask rubric it is the key
    this cache has always used."""
    strict = bool(ask.meta.get("strict_form"))
    parts = [ask.question(), list(ask.golds), answer.strip()] + (["strict2"] if strict else [])
    if (rid := rubric_of(ask)) is not None:
        parts.append(f"rubric:{rid}")
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def request(ask: Ask, answer: str) -> tuple[str | None, str, str]:
    """``(system, user, JSON key)`` of the grading call for one answer."""
    if (rid := rubric_of(ask)) is not None:
        prompt, key = RUBRICS[rid]
        return None, prompt.replace("{cont}", answer), key
    expected = "\n".join(f"- {g}" for g in ask.golds)
    user = (
        f"QUESTION:\n{ask.question()}\n\nEXPECTED (any one of):\n{expected}\n\n"
        f'ANSWER:\n{answer}\n\nReply with JSON only: {{"correct": true|false, "why": "..."}}'
    )
    return GRADE_SYSTEM + (STRICT_FORM if ask.meta.get("strict_form") else ""), user, "correct"


def grader(model: str) -> Callable[[Ask, list[str]], list[bool | None]]:
    """``model`` is a Claude id; the client is ``auth.client()`` (the judges' keyless OAuth token).
    A refused or unparsable grade is ``None``: undecided, never a pass; a 401 stops the run.
    Grades are cached per (question, golds, answer), so repeated samples cost one call."""
    import threading

    import anthropic

    from .auth import PUSH, Session, TokenExpired

    session = Session()
    cache: dict[str, bool | None] = {}
    served_by: dict[str, int] = {}  # serving model -> grades it decided (a fallback is visible)
    lock = threading.Lock()
    # persisted across runs (a 401 or a crash no longer redoes every grade): decided verdicts
    # only, so an undecided one is asked again next time
    path = store.REPO_ROOT / "adapted" / ".grade_cache" / f"{model}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                rec = json.loads(line)
                cache[rec["k"]] = rec["v"]

    def one(ask: Ask, answer: str) -> bool | None:
        key = cache_key(ask, answer)  # the rubric is part of the key
        with lock:
            if key in cache:
                return cache[key]
        verdict, by = _call(ask, answer)
        with lock:
            cache[key] = verdict
            if verdict is not None:
                served_by[by] = served_by.get(by, 0) + 1
                rec = (
                    {"k": key, "v": verdict} if by == model else {"k": key, "v": verdict, "by": by}
                )
                try:  # the cache is an optimisation: a network-volume I/O error must not kill a run
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec) + "\n")
                except OSError as e:
                    print(f"[grade-cache] write failed ({e}); continuing uncached")
        return verdict

    def _call(ask: Ask, answer: str) -> tuple[bool | None, str]:
        system, user, field = request(ask, answer)
        kw = {} if system is None else {"system": system}
        use = model
        fallback = REFUSAL_FALLBACK if rubric_of(ask) in FALLBACK_RUBRICS else None
        # a transient error or an unparsable reply is retried: an undecided grade fails a strict
        # leak screen (max_rate 0 needs every sample decided), so None must mean "really unsure"
        attempt = 0
        while attempt < ATTEMPTS:
            seen = session.pushed
            try:
                msg = session.create(
                    model=use,
                    max_tokens=200,
                    **kw,
                    messages=[{"role": "user", "content": user}],
                )
                refused = getattr(msg, "stop_reason", None) == "refusal"
                if refused and fallback is not None and use != fallback:
                    use, attempt = fallback, 0  # re-ask on the fallback model (B1)
                    continue
                text = "".join(b.text for b in msg.content if b.type == "text").strip()
                return bool(json.loads(text[text.index("{") : text.rindex("}") + 1])[field]), use
            except anthropic.AuthenticationError as e:
                if not session.refresh(seen):  # no newer token in the Dict
                    raise TokenExpired(PUSH) from e
            except (anthropic.APIError, ValueError, KeyError):
                time.sleep(2**attempt)
                attempt += 1
        return None, use

    def grade(ask: Ask, answers: list[str]) -> list[bool | None]:
        return [one(ask, a) for a in answers]

    grade.cache = cache  # type: ignore[attr-defined]
    grade.served_by = served_by  # type: ignore[attr-defined]
    return grade
