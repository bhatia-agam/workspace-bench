"""A subject's native languages (plan 0060 A1.10): ``adapted/<model>/native_langs.json``.

``freeze`` writes ``contract.native_langs`` of the six families below from this file instead of
the registered header's Qwen value, and refuses those families until the file exists. File
format (one object)::

    {"model": "<key>", "native_langs": ["en", ...],   # ISO codes, English first
     "thinking": "on" | "off",                        # the mode the measurement ran in
     "method": "plan 0054 R6", "measured": "YYYY-MM-DD", "evidence": "<free text>"}

``measure`` runs plan 0054 R6 on the subject (a GPU job through the subject runner) and writes
the file; ``record`` writes a measurement made elsewhere, with its evidence. R6 (= plan 0032
§2.10) measures the reasoning TRACE, so ``measure`` defaults to thinking ON for a subject with a
thinking mode (``Subject.thinking_mode``) and falls back to the thinking-OFF response measure
(plan 0060 D7's variant) for one without; the record says which ran. The thinking-off variant
gave Qwen3.6-27B ['en'] (en .911, zh .037: it measures the ANSWER language), not R6's
['en', 'zh']. The second criterion (§2.10's "readouts", Camila 2026-11-03: the subject's
J-LENS, a token lens) is ``readout_criterion``: share of J-lens top-10 tokens per language at 10
read sites. native = English + both criteria (``combine``; ``native_by`` says which). On
Qwen3.6-27B: trace ['en'] (zh .0001), J-lens ['en', 'zh'] (zh .249) -> ['en', 'zh'].

Exception to copy-verbatim: when the subject's languages differ from the registered header's,
the ORIGINALS' native units are rebuilt per ``native_langs`` (plan 0054 §B) by the multilingual
upgraders (A2). Contract for an A2 multilingual upgrader, per original it rebuilds:

- set ``item[MARKER] = <the subject's native_langs>`` (``native_units_for``);
- rebuild EVERY unit (``units``: the native-role units AND the ``language`` unit, whose forms are
  keyed by native code) and ``probe_token_lens``;
- rebuild every native-dependent key the registered item has (``NATIVE_KEYS``: ``mc`` and
  ``mc_roles``, i.e. the native / language option blocks such as ``mc.correction_native``, and
  ``l2_equals_native`` / ``bridge_l2_creditable``);
- drop (never ship) an item whose L2 becomes native or stops being native, with that reason.

``freeze`` refuses a family whose passing originals are not marked for the subject's languages or
lack one of those keys (``unbuilt``), and otherwise takes them from the row (``overlay``)."""

import datetime as dt
import json
from typing import Any

from . import store

FILE = "native_langs.json"
MARKER = "native_units_for"  # item key: the native_langs its native units were rebuilt for
# the families whose header carries contract.native_langs (judges: banks.native_langs)
FAMILIES = (
    "multilingual",
    "multilingual_mt",
    "multilingual_typo",
    "multilingual_multihop",
    "basic_readout_mt",
    "typo_mt",
)
# per family, the unit roles holding forms in the native languages (documentation of what the
# rebuild touches; freeze takes EVERY unit from a rebuilt row, ``language`` included)
NATIVE_ROLES: dict[str, tuple[str, ...]] = {
    "multilingual": ("concept_native", "language"),
    "multilingual_mt": ("concept", "language"),
    "multilingual_typo": ("correction_native", "language"),
    "multilingual_multihop": ("bridge_native", "language"),
    "basic_readout_mt": ("readout", "language"),
    "typo_mt": ("correction",),
}
# item keys whose value depends on the native languages; with ``units`` and
# ``probe_token_lens``, a rebuilt original ships the row's value of every one the registered item
# has
NATIVE_KEYS = ("units", "probe_token_lens", "mc", "mc_roles", "l2_equals_native",
               "bridge_l2_creditable", "name_forms")  # fmt: skip
THINKING = ("off", "on")


def path(model: str):
    return store.model_dir(model) / FILE


def load(model: str) -> dict[str, Any] | None:
    """The validated record, or None when it was never measured."""
    p = path(model)
    if not p.exists():
        return None
    rec = json.loads(p.read_text(encoding="utf-8"))
    validate(rec)
    return rec


def validate(rec: dict[str, Any]) -> None:
    langs = rec.get("native_langs")
    if not isinstance(langs, list) or not langs or not all(isinstance(x, str) for x in langs):
        raise SystemExit(f"{FILE}: native_langs must be a non-empty list of ISO codes")
    if langs[0] != "en":
        raise SystemExit(f"{FILE}: native_langs must list English first, got {langs}")
    if len(set(langs)) != len(langs):
        raise SystemExit(f"{FILE}: duplicate codes in {langs}")
    if rec.get("method") == DECISION and "thinking" not in rec:
        return  # a decision record (Camila's Chinese-lab rule): nothing was sampled
    if rec.get("thinking") not in THINKING:
        raise SystemExit(f"{FILE}: thinking must be one of {THINKING} (plan 0060 D7)")


def langs_for_freeze(model: str) -> list[str]:
    """What freeze writes into ``contract.native_langs``; refuses when unmeasured."""
    rec = load(model)
    if rec is None:
        raise SystemExit(
            f"{model}: no {path(model)}; measure the subject's native languages first "
            f"(plan 0060 A1.10) before freezing {', '.join(FAMILIES)}"
        )
    return list(rec["native_langs"])


DECISION = "decision"  # a record set by decision, not measured (no thinking mode applies)


def record(model: str, langs: list[str], evidence: str, thinking: str | None = None,
           method: str | None = None) -> dict[str, Any]:  # fmt: skip
    """Write native languages set elsewhere (never a guess: ``evidence`` is required).

    Without ``thinking`` it is a DECISION record (``method: "decision"``, no ``thinking``
    field): Camila's 2026-11-03 rule that a Chinese-lab model is ``["en", "zh"]`` unmeasured.
    With ``thinking`` it is a measurement made elsewhere (``method`` default plan 0054 R6)."""
    if not evidence.strip():
        raise SystemExit("native_langs: evidence= is required (what was measured or decided)")
    rec: dict[str, Any] = {"model": model, "native_langs": list(langs)}
    if thinking is None:
        rec["method"] = method or DECISION
    else:
        rec.update(thinking=thinking, method=method or "plan 0054 R6")
    rec.update(measured=str(dt.date.today()), evidence=evidence)
    validate(rec)
    store.write_json(path(model), rec)
    return rec


# --- the measurement (plan 0054 R6 = plan 0032 §2.10) -------------------------------------------
# thinking ON (R6 as written; ``_measure_trace``): below. thinking OFF (plan 0060 D7's variant,
# the fallback for a subject without a thinking mode):
# 30 prompts of the multilingual families (5 per family, in each family's own gate render) plus 20
# neutral English prompts, K=4 draws at T=1.0 through the subject runner (its own template,
# thinking off); a non-English language is native when it holds >= 10% of the response letters of
# the FAMILY prompts (``measure``). Letters are
# classified by Unicode script (``unicodedata`` name); Han letters count as ``ja`` in a response
# that also writes kana, else ``zh`` (the procedure's langid split, without the dependency).
# Thinking off has no trace, so the RESPONSE letters are measured; a family prompt's own scripts
# (the passage's L2: a continuation in that language is not evidence of a native language) are
# left out of its tally, except Latin, which is English's and always counts.
N_PER_FAMILY, K, TEMPERATURE, MAX_TOKENS, SHARE = 5, 4, 1.0, 256, 0.10
NEUTRAL_PROMPTS = (
    "What is a good way to start learning to play the guitar?",
    "Explain why the sky is blue in two or three sentences.",
    "Write a short poem about a quiet morning.",
    "Give me three tips for staying focused while studying.",
    "How does a refrigerator keep food cold?",
    "Describe your ideal weekend.",
    "What should I consider when adopting a dog?",
    "Summarize the plot of a story about a lost key, in a few sentences.",
    "Why do leaves change colour in autumn?",
    "Suggest a simple recipe for dinner tonight.",
    "What is the difference between weather and climate?",
    "Tell me a fun fact about octopuses.",
    "How can I make my mornings less rushed?",
    "Explain what a prime number is to a ten-year-old.",
    "What are some good habits for writing clean code?",
    "Plan a one-day trip to a city by the sea.",
    "Why is sleep important for memory?",
    "Write two sentences describing a busy market.",
    "How do bees make honey?",
    "What makes a good friend?",
)
SCRIPT_CODES = {
    "LATIN": "en", "CYRILLIC": "ru", "ARABIC": "ar", "HEBREW": "he", "GREEK": "el",
    "DEVANAGARI": "hi", "THAI": "th", "HANGUL": "ko", "HIRAGANA": "ja", "KATAKANA": "ja",
    "BENGALI": "bn", "TAMIL": "ta", "GEORGIAN": "ka", "ARMENIAN": "hy", "ETHIOPIC": "am",
    "KATAKANA-HIRAGANA": "ja",  # the prolonged sound mark (ー), a kana letter
}  # fmt: skip


def _script(ch: str) -> str:
    import unicodedata

    head = unicodedata.name(ch, "UNKNOWN").split(" ")[0]
    return "cjk" if head == "CJK" else SCRIPT_CODES.get(head, f"script:{head.lower()}")


def letter_codes(text: str, han: str = "text") -> dict[str, int]:
    """Letters per language code by Unicode script (a script with no code is
    ``script:<name>``). Han letters are ``ja`` beside kana, else ``zh``: ``han="text"`` decides
    once for the whole text (a short reply); ``han="run"`` per run, i.e. per stretch of text
    between Latin letters and line breaks (a long reasoning trace, where one Japanese word
    must not turn a whole Chinese trace into ``ja``: R6's "CJK split zh / ja on the run")."""
    from collections import Counter

    out: Counter[str] = Counter()
    if han == "text":
        for ch in text:
            if ch.isalpha():
                out[_script(ch)] += 1
        if n := out.pop("cjk", 0):
            out["ja" if out.get("ja") else "zh"] += n
        return dict(out)
    if han != "run":
        raise ValueError(f"han must be 'text' or 'run', got {han!r}")
    run: Counter[str] = Counter()

    def flush() -> None:
        if n := run.pop("cjk", 0):
            out["ja" if run.get("ja") else "zh"] += n
        out.update(run)
        run.clear()

    for ch in text:
        if ch == "\n":
            flush()
        elif ch.isalpha():
            code = _script(ch)
            if code == "en":  # a Latin letter ends the CJK run
                flush()
                out["en"] += 1
            else:
                run[code] += 1
    flush()
    return dict(out)


def family_prompts(n_per_family: int = N_PER_FAMILY) -> list[tuple[str, Any]]:
    """``[(family, Ask)]``: the first ``n_per_family`` items (by id) of each family's registered
    bank, asked in the family's own gate render (``families.FAMILIES[f].asks``, first leg)."""
    from . import families as fams

    out = []
    for fam in FAMILIES:
        _h, items = store.original_bank(fam)
        for it in sorted(items, key=store.item_id)[:n_per_family]:
            asks = fams.get(fam).asks(it)
            if asks:
                out.append((fam, asks[0]))
    return out


CALIBRATION_REFERENCE = ("Qwen/Qwen3.6-27B", ["en", "zh"])  # plan 0032 §2.10's measured result
# thinking ON (R6 as written): the K draws stop at the trace's closing token, so a sample is the
# trace; the budget covers a long trace (one cut at THINK_MAX_TOKENS still counts its letters)
THINK_MAX_TOKENS, THINK_MAX_MODEL_LEN = 8192, 12288


def _shares(tally: Any) -> dict[str, float]:
    total = sum(tally.values()) or 1
    return {c: round(n / total, 4) for c, n in tally.most_common()}


def _subject(model: str) -> Any:
    try:
        from .subjects import get as get_subject

        return get_subject(model)
    except (SystemExit, KeyError):
        return None


def _calibration(model: str, native: list[str]) -> dict[str, Any]:
    """``pass`` / ``FAIL`` on the reference subject (Qwen3.6-27B must give ['en', 'zh']), else
    ``unverified`` with what to check."""
    s = _subject(model)
    ref_id, ref_langs = CALIBRATION_REFERENCE
    if getattr(s, "hf_id", None) == ref_id:
        return {"status": "pass" if native == ref_langs else "FAIL", "expected": ref_langs}
    check = ("the first GPU run measures the reference with this procedure; trust this "
             "subject's result only once that gives the expected list")  # fmt: skip
    return {"status": "unverified", "reference": ref_id, "expected": ref_langs, "check": check}


def default_thinking(model: str) -> str:
    """``on`` for a subject with a thinking mode (``Subject.thinking_mode``), else ``off``."""
    return "on" if getattr(_subject(model), "thinking_mode", False) else "off"


def trace_of(text: str, tm: dict[str, Any]) -> str | None:
    """The reasoning trace in one sampled continuation (``tm`` = ``template.think_markers``), or
    None when the model wrote none. The trace starts at the continuation (the generation prompt
    opened it) or after the opener the model writes itself (``tm["open"]``, or what decoding
    without special tokens leaves of it, ``tm["open_visible"]``), and ends at the first
    ``tm["cut"]`` (or ``tm["close"]``); a sample stopped on the closing token, or cut at
    ``max_tokens``, has none and runs to its end."""
    t = text
    if tm["open"].strip():
        body = t.lstrip()
        for o in (tm["open"], tm.get("open_visible") or ""):
            if o.strip() and body.startswith(o.strip()):
                t = body[len(o.strip()) :].lstrip()
                break
        else:
            return None  # the model answered without opening a trace
    for c in (tm["cut"], tm["close"]):
        if c and (k := t.find(c)) >= 0:
            t = t[:k]
    return t


def _trace_stop(markers: dict[str, Any], tok: Any) -> list[int] | None:
    """The engine stop id for the trace's closing token, sent only when a decoded sample would
    lose it (a special token that ``skip_special_tokens`` drops: Gemma-4 ``<channel|>``, Muse
    ``<|eom|>``). When the close survives decoding (Qwen / GLM ``</think>``) the text is cut at
    it instead (``trace_of``), so apps deployed before ``stop_token_ids`` existed still serve
    those subjects."""
    sid = markers.get("stop_id")
    if sid is None:
        return None
    if tok is not None and tok.decode([sid], skip_special_tokens=True).strip():
        return None
    return [sid]


def trace_end(text: str, tm: dict[str, Any], stop: list[int] | None, tok: Any) -> str:
    """How a sampled trace ended: ``closed`` (its closing marker is in the text, or the engine
    stopped on the closing token, ``stop``), ``cut`` (no closing marker and the sample used the
    whole ``THINK_MAX_TOKENS`` budget) or ``eos`` (no closing marker, budget not used: the model
    ended its turn inside the trace). Without a tokenizer the budget is unknown: ``eos`` unless
    closed."""
    if any(c and c in text for c in (tm.get("cut"), tm.get("close"))):
        return "closed"
    hit = tok is not None and len(tok(text, add_special_tokens=False)["input_ids"]) >= (
        THINK_MAX_TOKENS - 1
    )
    if hit:
        return "cut"
    return "closed" if stop else "eos"


def measure(model: str, thinking: str | None = None, runner: Any = None,
            card_langs: list[str] | None = None, markers: dict[str, Any] | None = None,
            readouts: str | None = None, tok: Any = None) -> dict[str, Any]:  # fmt: skip
    """Plan 0054 R6 on the subject through the subject runner; writes and returns the
    ``native_langs.json`` record (``thinking`` says which mode ran, and the evidence says why).

    ``thinking``: None = ``default_thinking`` (on for a subject with a thinking mode, the R6
    trace measure ``_measure_trace``; off otherwise, the response measure ``_measure_off``).
    ``on`` for a subject without a thinking mode is refused. ``markers`` (tests): the trace
    delimiters, else ``template.think_markers(runner.tok)``.

    ``readouts``: the subject's J-lens (token lens) readouts dir, for the second criterion
    (``readout_criterion``, Camila 2026-11-03); None = the subject has none, recorded as such.
    ``tok`` decodes its tokens (default: the runner's, else the subject's tokenizer).
    native = English + trace(or response)-native + readout-native (``combine``)."""
    if thinking is None:
        thinking = default_thinking(model)
        why = ("default: the subject has a thinking mode" if thinking == "on" else
               "default: the subject has no thinking mode")  # fmt: skip
    else:
        why = f"thinking={thinking} requested"
    if thinking not in THINKING:
        raise SystemExit(f"native_langs: thinking must be one of {THINKING}, got {thinking!r}")
    if readouts:  # a bad readouts dir fails here, before any sampling
        site_rows(readouts)
    if thinking == "on":
        if default_thinking(model) != "on":
            raise SystemExit(f"native_langs: {model} has no thinking mode (Subject."
                             "thinking_mode=False); measure it with thinking=off")  # fmt: skip
        rec = _measure_trace(model, why, runner, card_langs, markers)
    else:
        rec = _measure_off(model, why, runner, card_langs)
    ro = None
    if readouts:
        ro = readout_criterion(readouts, tok or getattr(runner, "tok", None) or _tokenizer(model))
    return finalize(model, rec, ro)


# --- the readout criterion (plan 0032 §2.10, reader = the subject's J-lens; Camila 2026-11-03) --
# §2.10: "if a prose reader exists, take 10 read sites of its readouts ... a language is native
# if ... at least 10% of readout samples are in it". Camila's decision of 2026-11-03: the reader is
# the subject's J-LENS (a token lens, ``tokens10``: its top-10 tokens per cell are the samples),
# not an O-lens / NLA prose reader (the 27B's O-lens rl-onchat-x4 readouts hold ~0 Chinese; its
# J-lens top-10 hold 11-36% Chinese per family, the observation behind "qwen thinks in chinese").
READ_SITES = 10
TOKEN_SAMPLING = "tokens10"


def read_sites(n: int = READ_SITES) -> list[tuple[str, Any]]:
    """The ``n`` read sites: the trace's family prompts (``family_prompts``) taken round-robin
    over ``FAMILIES`` (each family's first item, then each one's second, ...), so the sites span
    the families. A site is that item's read position(s) at every layer its readouts hold."""
    by: dict[str, list[Any]] = {}
    for fam, ask in family_prompts():
        by.setdefault(fam, []).append(ask)
    out: list[tuple[str, Any]] = []
    for i in range(max((len(v) for v in by.values()), default=0)):
        out += [(f, by[f][i]) for f in FAMILIES if i < len(by.get(f, []))]
    return out[:n]


def decode_token(tok: Any, t: str) -> str:
    """A readout token as text: the files spell byte-level BPE tokens as the tokenizer's token
    strings (``Ġ`` / ``▁`` shown as a space, ``produce.render.display_tokens``; cached files may
    keep raw byte strings such as ``åķ¥``), so the token id is recovered and decoded; a string
    that is no token is taken as it is."""
    for cand in (t, t.replace(" ", "Ġ"), t.replace(" ", "▁")):
        try:
            i = tok.convert_tokens_to_ids(cand)
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(i, int) and i >= 0 and i != getattr(tok, "unk_token_id", None):
            return tok.decode([i])
    return t


def token_lang(text: str) -> str | None:
    """The language of one token: the code holding most of its letters (``letter_codes``); None
    for a token without letters (digits, punctuation, whitespace), left out of the shares."""
    codes = letter_codes(text, han="run")
    return max(codes, key=lambda c: (codes[c], c)) if codes else None


def site_rows(readouts: str, sites: list[tuple[str, Any]] | None = None,
              sampling: str = TOKEN_SAMPLING) -> dict[str, list[dict]]:  # fmt: skip
    """``{"<family>/<id>": rows}``: each read site's cells in ``<readouts>/<family>.jsonl`` at ONE
    position, the item's last position in the file (a final-token file holds one per item; a
    full-position file then counts the final token, not every position), every layer there.
    Refuses (SystemExit) a non-token-lens sampling, a sidecar declaring one, or any site with no
    rows; ``measure`` calls it BEFORE sampling, so a bad dir never costs a GPU run."""
    from pathlib import Path

    if sampling != TOKEN_SAMPLING:
        raise SystemExit(f"native_langs: the readout criterion reads a token lens "
                         f"({TOKEN_SAMPLING}), not {sampling!r}")  # fmt: skip
    root = Path(readouts)
    sites = read_sites() if sites is None else sites
    out: dict[str, list[dict]] = {}
    missing = []
    for fam, ask in sites:
        f = root / f"{fam}.jsonl"
        meta = root / f"{fam}.jsonl.meta.json"
        if meta.exists():
            declared = json.loads(meta.read_text()).get("sampling")
            if declared and declared != TOKEN_SAMPLING:
                raise SystemExit(f"native_langs: {meta} declares sampling={declared!r}, not a "
                                 f"token lens ({TOKEN_SAMPLING})")  # fmt: skip
        rows = []
        if f.exists():
            with f.open(encoding="utf-8") as fh:
                rows = [r for r in map(json.loads, fh) if r.get("id") == ask.item_id]
        if not rows:
            missing.append(f"{fam}/{ask.item_id}")
            continue
        pos = max(int(r.get("pos", 0)) for r in rows)
        out[f"{fam}/{ask.item_id}"] = [r for r in rows if int(r.get("pos", 0)) == pos]
    if missing:
        raise SystemExit(f"native_langs: no readouts in {root} for read sites {missing}")
    return out


def readout_criterion(readouts: str, tok: Any, sites: list[tuple[str, Any]] | None = None,
                      sampling: str = TOKEN_SAMPLING) -> dict[str, Any]:  # fmt: skip
    """Shares of the J-lens's top-10 tokens per language at the read sites (``read_sites``):
    each site's cells at one position (``site_rows``), every layer, tokens decoded with the
    subject's tokenizer (``decode_token``) and assigned by script (``token_lang``). A token in
    the item's OWN non-Latin script(s) (its passage's L2, read off the question) is left out: it
    echoes the passage, not a language the model thinks in (the 27B's shares barely move: zh
    .245 -> .249). Native at >= ``SHARE`` of the letter-bearing tokens; ``shares_incl_own`` is
    recorded beside. Only a token lens (``tokens10``) is accepted."""
    from collections import Counter

    sites = read_sites() if sites is None else sites
    by_site = site_rows(readouts, sites, sampling)
    tally: Counter[str] = Counter()
    incl: Counter[str] = Counter()
    n_cells = n_noletter = 0
    positions = {}
    for fam, ask in sites:
        rows = by_site[f"{fam}/{ask.item_id}"]
        positions[f"{fam}/{ask.item_id}"] = rows[0].get("pos")
        own = set(letter_codes(ask.question())) - {"en"}
        for r in rows:
            n_cells += 1
            for t in (r.get("tokens") or [])[:10]:
                lang = token_lang(decode_token(tok, t))
                if lang is None:
                    n_noletter += 1
                    continue
                incl[lang] += 1
                if lang not in own:
                    tally[lang] += 1
    shares = _shares(tally)
    native = ["en"] + [c for c, sh in shares.items()
                       if c != "en" and sh >= SHARE and not c.startswith("script:")]  # fmt: skip
    return {"status": "measured", "reader": "J-lens (token lens)", "readouts": str(readouts),
            "sampling": TOKEN_SAMPLING, "native": native, "shares": shares,
            "shares_incl_own": _shares(incl),
            "sites": [f"{fam}/{a.item_id}" for fam, a in sites], "positions": positions,
            "n_cells": n_cells, "n_tokens": sum(tally.values()),
            "n_tokens_without_letters": n_noletter,
            "unit": "J-lens top-10 tokens with letters at the read sites (one position each, "
                    "every layer), the item's own non-Latin L2 script left out"}  # fmt: skip


def combine(criteria: dict[str, list[str] | None]) -> tuple[list[str], dict[str, list[str]]]:
    """native = English (always) + every language some criterion makes native, in criterion
    order; ``by[lang]`` = the criteria that made it native (``always`` for English)."""
    native, by = ["en"], {"en": ["always"]}
    for name, langs in criteria.items():
        for c in langs or []:
            if c == "en":
                continue
            if c not in by:
                native.append(c)
                by[c] = []
            by[c].append(name)
    return native, by


def finalize(model: str, rec: dict[str, Any], readout: dict[str, Any] | None) -> dict[str, Any]:
    """Combine the first criterion (``trace`` with thinking on, ``response`` with it off) with
    the readout criterion, set ``native_langs`` / ``native_by`` / ``criteria`` / calibration,
    then validate and write the record."""
    if rec.get("method") == DECISION:  # set by decision (record()): no shares to carry
        first, key = DECISION, None
    else:
        first = "trace" if rec.get("thinking") == "on" else "response"
        key = "shares_all" if first == "trace" else "shares_family"
    first_native = rec.get("criteria", {}).get(first, {}).get("native", rec["native_langs"])
    if readout is None:
        readout = {"status": "none", "reason": "no J-lens readouts for this subject: the "
                   f"{first} criterion alone decides"}  # fmt: skip
    native, by = combine({first: first_native, "readout": readout.get("native")})
    # a record() written elsewhere carries no shares: None, never a KeyError
    shares = rec.get(key) if key else None
    rec["criteria"] = {first: {"native": first_native, "shares": shares}, "readout": readout}
    rec["native_langs"], rec["native_by"] = native, by
    rec["calibration"] = _calibration(model, native)
    rec["evidence"] = rec["evidence"].split("; READOUT criterion")[0].split("; calibration ")[0]
    ro = (
        f"; READOUT criterion (J-lens top-10 at {len(readout['sites'])} read sites, "
        f"{readout['readouts']}): shares {readout['shares']} -> {readout['native']}"
        if readout.get("status") == "measured"
        else f"; READOUT criterion: {readout['reason']}"
    )
    rec["evidence"] += f"{ro}; native {native} by {by}; calibration {rec['calibration']['status']}"
    validate(rec)
    store.write_json(path(model), rec)
    return rec


def add_readouts(model: str, readouts: str, tok: Any = None) -> dict[str, Any]:
    """The readout criterion added to an already measured record (``measure`` ran without
    readouts, e.g. before the subject's J-lens readouts existed)."""
    rec = load(model)
    if rec is None:
        raise SystemExit(f"{model}: not measured ({path(model)}); run stage=measure first")
    return finalize(model, rec, readout_criterion(readouts, tok or _tokenizer(model)))


def _tokenizer(model: str) -> Any:
    from .subjects import get as get_subject
    from .subjects import load_tokenizer

    s = get_subject(model)
    return load_tokenizer(s.hf_id, s.revision, s.tokenizer_dir, s.chat_template,
                          s.trust_remote_code)  # fmt: skip


def _measure_trace(model: str, why: str, runner: Any, card_langs: list[str] | None,
                   markers: dict[str, Any] | None) -> dict[str, Any]:  # fmt: skip
    """R6 as written (plan 0032 §2.10, gating.md §0): the 30 family + 20 neutral prompts, thinking
    ON, K draws at T, and a language is native at >= ``SHARE`` of the THOUGHT letters of all
    ``(30 + 20) * K`` traces (``shares_all``; English always counts). Letters by Unicode script,
    Han split zh / ja per run (``letter_codes(han="run")``). A family trace's letters in its
    prompt's OWN non-Latin script (the passage's L2, which the trace quotes) are left out of the
    decision, as in the readout criterion and the thinking-off variant (R6's text does not say;
    Qwen3.5-0.8B's traces hold 7.5% Arabic, all of it the Arabic passages quoted);
    ``shares_all_incl_own_scripts`` records the count without that rule. Family prompts go as
    their gate render's messages without the answer prefill (a stem there would sit inside the
    trace); a raw family prompt becomes the user turn. Recorded beside the decision: the
    family / neutral split, the family share with each prompt's own L2 scripts left out,
    traces missing and cut at ``THINK_MAX_TOKENS``."""
    from collections import Counter

    from .gate import Ask

    fam_asks = family_prompts()
    asks = [Ask(f"family:{a.item_id}", "native", a.golds,
                tuple(a.messages) if a.messages else ({"role": "user", "content": a.prompt or ""},),
                max_tokens=THINK_MAX_TOKENS) for _f, a in fam_asks]  # fmt: skip
    asks += [Ask(f"neutral:{k}", "native", messages=({"role": "user", "content": p},),
                 max_tokens=THINK_MAX_TOKENS) for k, p in enumerate(NEUTRAL_PROMPTS)]  # fmt: skip
    if runner is None:
        from .run import _runner

        runner = _runner(model, measure_thinking=True, max_model_len=THINK_MAX_MODEL_LEN)
    if hasattr(runner, "thinking") and not runner.thinking:
        raise SystemExit("native_langs: thinking=on needs a thinking runner "
                         "(run._runner(measure_thinking=True))")  # fmt: skip
    if markers is None:
        from .template import think_markers

        markers = think_markers(runner.tok)
    stop = _trace_stop(markers, getattr(runner, "tok", None))
    outs = runner.sample(asks, K, TEMPERATURE, stop_token_ids=stop)
    tally: dict[str, Counter[str]] = {
        k: Counter() for k in ("all", "incl_own", "family", "neutral", "own")
    }
    n_missing = n_cut = n_eos = 0
    tok = getattr(runner, "tok", None)
    for ask, (_greedy, samples) in zip(asks, outs, strict=True):
        is_fam = ask.item_id.startswith("family:")
        own = set(letter_codes(ask.question())) - {"en"} if is_fam else set()
        for text in samples:  # the K draws (the greedy reply is not part of the procedure)
            trace = trace_of(text, markers)
            if trace is None:
                n_missing += 1
                continue
            end = trace_end(text, markers, stop, tok)
            n_cut += end == "cut"
            n_eos += end == "eos"
            codes = letter_codes(trace, han="run")
            kept = {c: n for c, n in codes.items() if c not in own}
            tally["all"].update(kept)  # the decision: a family prompt's own L2 script left out
            tally["incl_own"].update(codes)
            tally["family" if is_fam else "neutral"].update(codes)
            if is_fam:
                tally["own"].update(kept)
    shares = _shares(tally["all"])
    native = ["en"] + [c for c, sh in shares.items()
                       if c != "en" and sh >= SHARE and not c.startswith("script:")]  # fmt: skip
    unmapped = {c: sh for c, sh in shares.items() if c.startswith("script:") and sh >= SHARE}
    n = len(asks) * K
    evidence = (
        f"plan 0054 R6 with thinking ON ({why}): {len(fam_asks)} family + "
        f"{len(NEUTRAL_PROMPTS)} neutral prompts x K={K} at T={TEMPERATURE}, <= "
        f"{THINK_MAX_TOKENS} trace tokens, through the subject runner; thought-letter shares of "
        f"all traces (own L2 script left out) {shares}; native >= {SHARE:.0%}; traces missing "
        f"{n_missing}/{n}, cut at "
        f"max_tokens {n_cut}/{n}, ended without a closing marker {n_eos}/{n}; model card: "
        f"{card_langs or 'not recorded'}"
        + (f"; UNMAPPED scripts >= {SHARE:.0%}: {unmapped}" if unmapped else "")
    )
    rec = {"model": model, "native_langs": native, "thinking": "on", "method": "plan 0054 R6",
           "measured": str(dt.date.today()), "evidence": evidence, "shares_all": shares,
           "shares_all_incl_own_scripts": _shares(tally["incl_own"]),
           "shares_family": _shares(tally["family"]), "shares_neutral": _shares(tally["neutral"]),
           "shares_family_excl_own_scripts": _shares(tally["own"]),
           "model_card_langs": list(card_langs) if card_langs else None,
           "traces": {"n": n, "missing": n_missing, "cut_at_max_tokens": n_cut,
                      "ended_without_close": n_eos,
                      "markers": {k: markers.get(k) for k in ("open", "close", "stop_id")}},
           "protocol": {"n_family": len(fam_asks), "n_neutral": len(NEUTRAL_PROMPTS), "k": K,
                        "temperature": TEMPERATURE, "max_tokens": THINK_MAX_TOKENS,
                        "share": SHARE, "unit": "thought letters of all traces (family + "
                        "neutral), a family prompt's own non-Latin L2 script left out, Han split "
                        "zh/ja per run"}}  # fmt: skip
    return rec


def _measure_off(model: str, why: str, runner: Any,
                 card_langs: list[str] | None) -> dict[str, Any]:  # fmt: skip
    """Plan 0060 D7's thinking-OFF variant (the fallback for a subject without a thinking mode).

    A non-English language is native at >= ``SHARE`` of the response letters of the FAMILY
    prompts (``shares_family``; the neutral English pool is left out of that denominator, where it
    would only dilute it: an English prompt answered in English says nothing about a second
    language). ``shares_neutral`` / ``shares_all`` are recorded beside it, and so are the model
    card's stated languages (``card_langs``; the measurement decides). ``calibration``: on
    Qwen3.6-27B this variant gave ['en'] (en .911, zh .037), not R6's ['en', 'zh']: it measures
    the answer language, so a subject that thinks in a second language but answers in English
    reads as English-only."""
    from collections import Counter

    from .gate import Ask

    fam_asks = family_prompts()
    asks = [Ask(f"family:{a.item_id}", "native", a.golds, a.messages, a.prompt, a.prefill,
                max_tokens=MAX_TOKENS) for _f, a in fam_asks]  # fmt: skip
    asks += [Ask(f"neutral:{k}", "native", messages=({"role": "user", "content": p},),
                 max_tokens=MAX_TOKENS) for k, p in enumerate(NEUTRAL_PROMPTS)]  # fmt: skip
    if runner is None:
        from .run import _runner

        runner = _runner(model)
    outs = runner.sample(asks, K, TEMPERATURE)
    fam_tally: Counter[str] = Counter()
    neu_tally: Counter[str] = Counter()
    for ask, (_greedy, samples) in zip(asks, outs, strict=True):
        is_fam = ask.item_id.startswith("family:")
        # a family prompt's own scripts (its L2), Latin apart
        own = set(letter_codes(ask.question())) - {"en"} if is_fam else set()
        tally = fam_tally if is_fam else neu_tally
        for text in samples:  # the K draws (the greedy reply is not part of the procedure)
            for code, n in letter_codes(text).items():
                if code not in own:
                    tally[code] += n
    shares = _shares(fam_tally)
    native = ["en"] + [c for c, sh in shares.items()
                       if c != "en" and sh >= SHARE and not c.startswith("script:")]  # fmt: skip
    unmapped = {c: sh for c, sh in shares.items() if c.startswith("script:") and sh >= SHARE}
    evidence = (
        f"plan 0054 R6 with thinking OFF ({why}; plan 0060 D7's variant): {len(fam_asks)} family + "
        f"{len(NEUTRAL_PROMPTS)} neutral prompts x K={K} at T={TEMPERATURE}, {MAX_TOKENS} tokens, "
        f"through the subject runner; family-prompt response-letter shares {shares}; native >= "
        f"{SHARE:.0%}; model card: {card_langs or 'not recorded'}"
        + (f"; UNMAPPED scripts >= {SHARE:.0%}: {unmapped}" if unmapped else "")
    )
    rec = {"model": model, "native_langs": native, "thinking": "off", "method": "plan 0054 R6",
           "measured": str(dt.date.today()), "evidence": evidence, "shares_family": shares,
           "shares_neutral": _shares(neu_tally), "shares_all": _shares(fam_tally + neu_tally),
           "model_card_langs": list(card_langs) if card_langs else None,
           "protocol": {"n_family": len(fam_asks), "n_neutral": len(NEUTRAL_PROMPTS), "k": K,
                        "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS, "share": SHARE,
                        "unit": "response letters of the family prompts (no trace with thinking "
                        "off)"}}  # fmt: skip
    return rec


def unbuilt(family: str, row_item: dict, reg_item: dict, langs: list[str]) -> bool:
    """True when ``row_item`` is not a rebuild of ``reg_item`` for ``langs``: unmarked, marked
    for other languages, or missing a native-dependent key the registered item has."""
    if row_item.get(MARKER) != list(langs):
        return True
    return any(k in reg_item and k not in row_item for k in NATIVE_KEYS)


def overlay_native_units(family: str, item: dict, row_item: dict) -> dict:
    """``item`` (a copy of the registered original) with every native-dependent key
    (``NATIVE_KEYS``: all units, the language unit included, the token counts, the option blocks,
    the L2-is-native flags) taken from the rebuilt row (freeze re-counts tokens on a non-Qwen
    tokenizer)."""
    import copy

    for k in NATIVE_KEYS:
        if k in item and k in row_item:
            item[k] = copy.deepcopy(row_item[k])
    return item
