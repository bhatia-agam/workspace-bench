"""The on-subject gate: ask each question of the subject itself (its own chat template, thinking
off), one greedy answer plus ``draws`` samples, graded per answer; an item passes when every leg
passes. The rule is the banks' own: greedy right AND sampled rate >= threshold."""

import math
import os
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

DEFAULT_DRAWS = 10
DEFAULT_TEMPERATURE = 0.7
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class Ask:
    """One question for the subject. ``messages`` is a chat (rendered with the subject's template,
    thinking off, then ``prefill`` appended as the start of the assistant turn); ``prompt`` is a
    raw continuation. ``grade`` names a grader in ``GRADERS``.

    ``followup`` (plan 0060 D10): turns asked AFTER the subject's own reply to ``messages``. The
    reply is the subject's greedy answer to the ``messages`` render (``run_gate`` generates it, up
    to ``meta["reply_tokens"]``), and the render is that exact ``messages`` render, the reply,
    then the template's own text for closing the reply and asking ``followup``
    (``template.followup_tail``), so the first render is a token prefix of the follow-up
    (``with_replies`` checks it on token ids)."""

    item_id: str
    leg: str
    golds: tuple[str, ...] = ()
    messages: tuple[dict, ...] | None = None
    prompt: str | None = None
    prefill: str = ""
    grade: str = "contains"
    max_tokens: int = 24
    meta: dict = field(default_factory=dict)
    followup: tuple[dict, ...] = ()
    reply: str | None = None

    def question(self) -> str:
        if self.messages:
            body = "\n\n".join(f"[{m['role']}] {m['content']}" for m in self.messages)
            body += f"\n\n[assistant] {self.prefill}" if self.prefill else ""
            if self.followup:
                body += ("" if self.prefill else "\n\n[assistant] ") + (self.reply or "")
                body += "".join(f"\n\n[{m['role']}] {m['content']}" for m in self.followup)
            return body
        return self.prompt or ""

    def first_turn(self) -> "Ask":
        """The ask without its follow-up: the render the reply answers."""
        return replace(self, followup=(), reply=None)


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("\u2019", "'"))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold().strip()


_WORD = re.compile(r"[^\W_]+(?:['\-][^\W_]+)*", re.UNICODE)


def first_line(text: str) -> str:
    # split on "\n" only: str.splitlines also breaks on U+2028, which OLMo emits inside answers
    return next((ln.strip() for ln in text.strip().split("\n") if ln.strip()), "")


def exact_words(text: str) -> list[str]:
    """Words with diacritics kept (NFC, casefolded): the strict-form deterministic match."""
    return _WORD.findall(unicodedata.normalize("NFC", text.replace("\u2019", "'")).casefold())


def exact_hit(text: str, golds: Iterable[str]) -> bool:
    ws = exact_words(text)
    for g in golds:
        gw = exact_words(g)
        if gw and any(ws[i : i + len(gw)] == gw for i in range(len(ws) - len(gw) + 1)):
            return True
    return False


def words(text: str) -> list[str]:
    return _WORD.findall(fold(text))


def _has_form(answer: str, form: str) -> bool:
    a, f = fold(answer), fold(form)
    if not f:
        return False
    if re.search(r"[^\w\s'\-]", f) or not f.isascii():
        return f in a
    return re.search(rf"(?<![\w]){re.escape(f).replace(r'\ ', r'[\s\-]+')}(?![\w])", a) is not None


def _num(text: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", text.replace("\u2212", "-"))
    return float(m.group().replace(",", "")) if m else None


NUMBER_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]  # fmt: skip


def _with_number_words(golds: tuple[str, ...]) -> list[str]:
    """``"5"`` also accepts ``"five"`` and the reverse (0-20): the same value, spelled."""
    out = list(golds)
    for g in golds:
        f = fold(g)
        if f.isdigit() and int(f) < len(NUMBER_WORDS):
            out.append(NUMBER_WORDS[int(f)])
        elif f in NUMBER_WORDS:
            out.append(str(NUMBER_WORDS.index(f)))
    return out


def grade_contains(ask: Ask, text: str) -> bool | None:
    """The answer's first line contains one of the golds as a whole word or phrase."""
    line = first_line(text)
    if not line:
        return False
    return any(_has_form(line, g) for g in _with_number_words(ask.golds))


def grade_first_word(ask: Ask, text: str) -> bool | None:
    """The first word (or first len(gold) words) of the answer is a gold."""
    ws = words(first_line(text))
    if not ws:
        return False
    for g in ask.golds:
        gw = words(g)
        if gw and ws[: len(gw)] == gw:
            return True
    return False


def grade_number(ask: Ask, text: str) -> bool | None:
    """The first number in the answer equals a gold number."""
    got = _num(first_line(text))
    if got is None:
        return False
    return any((g := _num(str(gold))) is not None and math.isclose(got, g) for gold in ask.golds)


def grade_exact_text(ask: Ask, text: str) -> bool | None:
    """The answer, with quotes and outer punctuation stripped, is word-for-word a gold."""
    got = words(text.strip().strip("\"'“”"))
    return any(got == words(g) for g in ask.golds)


def grade_compliance(ask: Ask, text: str) -> bool | None:
    """directed_modulation: the reply is the carrier word for word and never names the concept."""
    concept = ask.meta.get("concept", "")
    return bool(grade_exact_text(ask, text)) and not (concept and _has_form(text, concept))


def grade_name_forms(ask: Ask, text: str) -> bool | None:
    """basic_readout_mt v4 (plan 0060 A2): the whole answer names the gold by one of its
    ``name_forms`` (any language, ``mc.form_in``), the bank's own gate grader
    (``scripts/build_brmt_v2.py`` ``stage_grade``)."""
    from wsbench import mc

    return mc.form_in(text, list(ask.golds))


def grade_llm(ask: Ask, text: str) -> bool | None:
    """Prose golds (conjunctive, role-bound, buggy_code): undecided until a model grades it."""
    return None


_INT = re.compile(r"(?<![\d.])-?\d+(?!\d|\.\d)")  # "is 16." still counts


def writes_forbidden(text: str, forbid: list[str]) -> bool:
    """The rollout wrote an intermediate on the page (a number standalone, a word as a word), so
    the latent was not computed silently."""
    nums = set(_INT.findall(text.replace("\u2212", "-")))
    return any(f in nums if _INT.fullmatch(f) else _has_form(text, f) for f in forbid)


GRADERS: dict[str, Callable[[Ask, str], bool | None]] = {
    "contains": grade_contains,
    "first_word": grade_first_word,
    "number": grade_number,
    "exact_text": grade_exact_text,
    "compliance": grade_compliance,
    "name_forms": grade_name_forms,
    "llm": grade_llm,
    # "own": no gold; the answer IS the gold (poetry rhyme, implicit favourite). Graded in
    # ``own_word`` after sampling, because the gold is the greedy answer.
}


# Graders whose verdict is exact by construction: a model grader would only loosen them.
NO_FALLBACK = {"number", "exact_text", "compliance", "first_word", "name_forms"}


@dataclass
class Leg:
    greedy: dict
    samples: list[dict]
    rate: float | None
    decided: int
    passed: bool
    question: str
    own: str | None = None
    reply: str | None = None  # a follow-up leg's conditioning reply (Ask.reply), kept for regrade
    # a follow-up leg's checks (``with_replies``): ``prefix`` exact / stripped / broken, and
    # ``reply_states_gold`` (the summary already wrote a gold form, so a pass may be a copy)
    followup: dict | None = None


NO_ANSWER = {"none", "no", "nothing", "n", "a", "i", "as", "sorry", "unknown", "neutral"}


def own_word(text: str, stub: str = "") -> str:
    """First word of the answer's first line; with a poetry ``stub`` (line 2 so far), an echoed
    tail of the stub is skipped first ("clear as a bell" after "...as clear as a" -> "bell")."""
    ws = words(first_line(text))
    if stub and ws:
        sw = [fold(w) for w in words(stub)]
        fw = [fold(w) for w in ws]
        for k in range(min(len(sw), len(fw) - 1), 0, -1):
            if fw[:k] == sw[-k:]:
                return ws[k]
    return ws[0] if ws else ""


def _states_role(text: str, role: str) -> bool:
    """The role's head noun (its last word, singular or plural) is written in the answer."""
    head = (words(role) or [role])[-1]
    return any(_has_form(text, f) for f in (head, head + "s", head + "es"))


def _names_to_roles(text: str, name_roles: dict[str, str]) -> str:
    for name, role in name_roles.items():
        text = re.sub(rf"\b{re.escape(name)}\b(?:'s)?", role, text)
    return text


def grade_leg(
    ask: Ask,
    greedy: str,
    samples: list[str],
    threshold: float,
    llm: Callable[[Ask, list[str]], list[bool | None]] | None = None,
) -> Leg:
    if ask.grade == "free_line":  # poetry v5's free line-two leg (``poetry.free_leg``)
        from .poetry import free_leg

        return free_leg(ask, greedy, samples)
    texts = [greedy, *samples]
    broken = (ask.meta.get("followup") or {}).get("prefix") == "broken"
    if name_roles := ask.meta.get("name_roles"):  # role_bound: names -> "the <role> (<name>)"
        texts = [_names_to_roles(t, name_roles) for t in texts]
    if ask.grade == "own":
        stub = ask.meta.get("stub", "") if ask.meta.get("rhymes_with") else ""
        gold = own_word(greedy, stub)
        verdicts: list[bool | None] = [bool(gold) and own_word(t, stub) == gold for t in texts]
        if ask.meta.get("no_refusal") and gold.lower() in NO_ANSWER:  # "None" is no favourite
            verdicts[0] = False
        if ask.meta.get("rhymes_with") and gold:
            from .rhyme import known, rhymes

            # the committed word must be a real English word that rhymes (not "1ight", not 墙)
            if not (gold.isascii() and known(gold) and rhymes(gold, ask.meta["rhymes_with"])):
                verdicts[0] = False
            # a rhyme already written in line 2's stub is not a latent (audit 4B: hug/rug -> bug)
            if fold(gold) in {fold(w) for w in words(ask.meta.get("stub", ""))}:
                verdicts[0] = False
    else:
        verdicts = [GRADERS[ask.grade](ask, t) for t in texts]
        if ask.meta.get("strict_form"):  # fold() drops accents: "frio" must not pass for "frío"
            verdicts = [None if v is True and not exact_hit(t, ask.golds) else v
                        for t, v in zip(texts, verdicts, strict=True)]  # fmt: skip
        if llm is not None and ask.grade not in NO_FALLBACK:
            # The undecided, and the misses (an alias or a translation the forms lack), go to
            # the model grader; a deterministic pass is never second-guessed.
            todo = [i for i, v in enumerate(verdicts) if v is not True and texts[i].strip()]
            if todo:
                for i, v in zip(todo, llm(ask, [texts[i] for i in todo]), strict=True):
                    if v is not None:
                        verdicts[i] = v
    if roles := ask.meta.get("require_roles"):  # role_bound strict: the roles must be stated
        verdicts = [v if v is not True or all(_states_role(t, r) for r in roles) else False
                    for t, v in zip(texts, verdicts, strict=True)]  # fmt: skip
    if forbid := ask.meta.get("forbid"):
        verdicts = [
            False if writes_forbidden(t, forbid) else v
            for t, v in zip(texts, verdicts, strict=True)
        ]
    if broken:  # the read render is not a token prefix of the follow-up: nothing is decided
        verdicts = [None] * len(texts)
    # a source gate's own bar for this leg (role-bound asked-open: greedy only; buggy: 4/6)
    threshold = float(ask.meta.get("threshold", threshold))
    if ask.meta.get("leak"):
        # a leak screen: the grader answers "does this text state the gold?"; the leg passes when
        # the greedy text does not and at most ``max_rate`` of the samples do. Shown as ✓ = clean.
        verdicts = [None if v is None else not v for v in verdicts]
        threshold = 1.0 - float(ask.meta.get("max_rate", 0.0))
    g_ok, s_ok = verdicts[0], verdicts[1:]
    decided = [v for v in s_ok if v is not None]
    rate = sum(decided) / len(decided) if decided else None
    floor = max(1, math.ceil(threshold * len(samples)) if threshold > 0 else 1)
    passed = bool(g_ok) and rate is not None and len(decided) >= floor and rate >= threshold
    greedy_d: dict[str, Any] = {"text": greedy, "ok": g_ok}
    sample_ds: list[dict[str, Any]] = [
        {"text": t, "ok": v} for t, v in zip(samples, s_ok, strict=True)
    ]
    if ask.grade == "own" and ask.meta.get("rhymes_with"):
        # poetry: each draw's committed word, so the subject's commitments (``qwen_commits``)
        # can be counted from the record alone (plan 0060 A2)
        stub = ask.meta.get("stub", "")
        for d in (greedy_d, *sample_ds):
            d["word"] = own_word(d["text"], stub)
    return Leg(
        greedy=greedy_d,
        samples=sample_ds,
        rate=rate,
        decided=len(decided),
        passed=passed,
        question=ask.question(),
        own=own_word(greedy, ask.meta.get("stub", "") if ask.meta.get("rhymes_with") else "")
        if ask.grade == "own"
        else None,
        reply=ask.reply if ask.followup else None,
        followup=ask.meta.get("followup") if ask.followup else None,
    )


def _leg_dict(leg: Leg) -> dict[str, Any]:
    d = asdict(leg)
    for k in ("reply", "followup"):  # only follow-up legs carry them; other records keep shape
        if d[k] is None:
            del d[k]
    return d


# A leg named ``note:<what>`` is an annotation: sampled, graded and kept in ``legs``, but never
# part of the pass rule or the rate (plan 0060 A2 chain: v2 kept items that failed `first`).
ANNOTATION = "note"


def gate_record(legs: dict[str, Leg]) -> dict[str, Any]:
    """One item's gate. Legs are grouped by the name before ``:``: renders of the same question
    (``surface`` = chat, ``surface:plain`` = raw continuation) are alternatives, so one passing is
    enough; separate questions (``surface``, ``bridge1``) must each pass. The shown answers are
    the best-scoring render of the surface group. ``note:*`` legs (:data:`ANNOTATION`) are
    recorded only."""
    groups: dict[str, list[tuple[str, Leg]]] = {}
    for name, leg in legs.items():
        if name.split(":")[0] == ANNOTATION:  # recorded, never gating (chain v2's `first`)
            continue
        groups.setdefault(name.split(":")[0], []).append((name, leg))
    best = {g: max(ls, key=lambda x: (x[1].passed, x[1].rate or 0.0)) for g, ls in groups.items()}
    head_name, head = best.get("surface") or next(iter(best.values()))
    rates = [leg.rate for _n, leg in best.values()]
    # plan 0060 D10: the knowledge leg's follow-up checks, at the top for analysis (a pass whose
    # conditioning summary already named the gold may be a copy)
    extra = {"followup": head.followup} if head.followup is not None else {}
    return {
        **extra,
        "greedy": head.greedy,
        "samples": head.samples,
        "question": head.question,
        "render": head_name,
        "rate": None if None in rates else min(rates),
        "pass": all(leg.passed for _n, leg in best.values()),
        "legs": {k: _leg_dict(v) for k, v in legs.items()},
    }


class Runner:
    """vLLM over the subject's HF weights. Thinking is always off: the banks' latents are the ones
    computed without a written chain of thought."""

    def __init__(
        self,
        hf_id: str,
        revision: str | None = None,
        max_model_len: int = 4096,
        gpu_memory_utilization: float = 0.85,
        seed: int = 0,
        enforce_eager: bool = False,
        **engine: Any,
    ):
        from vllm import LLM

        self.hf_id, self.revision, self.seed = hf_id, revision, seed
        self.llm = LLM(
            model=hf_id,
            revision=revision,
            max_model_len=max_model_len,
            gpu_memory_utilization=gpu_memory_utilization,
            seed=seed,
            # text only: no image/video inputs, so vLLM skips the vision encoder's memory
            # profiling (a 9B does not fit on 24 GB otherwise)
            limit_mm_per_prompt={"image": 0, "video": 0},
            enforce_eager=enforce_eager,
            **engine,
        )
        self.tok = self.llm.get_tokenizer()

    def render(self, ask: Ask) -> str:
        if ask.followup:  # plan 0060 D10: the first render, the subject's reply, the follow-up
            if ask.reply is None:
                raise ValueError(f"{ask.item_id}/{ask.leg}: a follow-up ask needs its reply")
            from .template import followup_tail

            tail = followup_tail(self.tok, ask.messages or (), ask.followup)
            return self.render(ask.first_turn()) + ask.reply + tail
        # NB: the box Runner hands vLLM this TEXT (vLLM tokenizes it, adding the tokenizer's own
        # specials), while RemoteRunner sends token ids (``RemoteRunner.encode``: no added
        # specials, an auto-BOS only when the render lacks it). For a tokenizer that auto-adds a
        # BOS the chat render already carries, the two backends can diverge by that one token.
        if ask.messages:
            text = self.tok.apply_chat_template(
                list(ask.messages),
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return text + ask.prefill
        from .template import bos_prefix

        if not hasattr(self, "_bos"):  # a raw continuation starts with the subject's BOS (Gemma)
            self._bos = self.tok.decode(bos_prefix(self.tok), skip_special_tokens=False)
        return self._bos + (ask.prompt or "")

    def token_prefix(self, head: str, full: str) -> bool:
        """``full``'s token ids start with ``head``'s (both tokenized as ``RemoteRunner.encode``
        does, without added specials): BPE can merge across the join (Qwen: the generation
        prompt's ``\n\n`` and a reply's leading ``\n``)."""
        a = list(self.tok(head, add_special_tokens=False)["input_ids"])
        b = list(self.tok(full, add_special_tokens=False)["input_ids"])
        return b[: len(a)] == a

    def sample(
        self, asks: list[Ask], draws: int, temperature: float, top_p: float = 1.0, top_k: int = -1
    ) -> list[tuple[str, list[str]]]:
        """``top_k`` -1 = off (vLLM's default); a bank whose gate fixed one (basic_readout_mt v4:
        20) passes it."""
        from vllm import SamplingParams

        prompts = [self.render(a) for a in asks]
        greedy_p = [SamplingParams(temperature=0.0, max_tokens=a.max_tokens) for a in asks]
        sample_p = [
            SamplingParams(
                n=draws,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                max_tokens=a.max_tokens,
                seed=self.seed + i,
            )
            for i, a in enumerate(asks)
        ]
        g = self.llm.generate(prompts, greedy_p, use_tqdm=False)
        s = self.llm.generate(prompts, sample_p, use_tqdm=False)
        return [
            (gi.outputs[0].text, [o.text for o in si.outputs]) for gi, si in zip(g, s, strict=True)
        ]

    def generate(
        self,
        prompts: list,
        temperature: float,
        max_tokens: int,
        seed: int,
        top_p: float = 1.0,
        stop_token_ids: list[int] | None = None,
    ) -> list[dict]:
        """One completion per prompt (text, or token ids): ``{"text", "ids"}``. The same contract
        as ``RemoteRunner.generate``, so floors run on either backend."""
        from vllm import SamplingParams
        from vllm.inputs import TokensPrompt

        sp = SamplingParams(temperature=temperature, top_p=top_p, top_k=0, max_tokens=max_tokens,
                            seed=seed, stop_token_ids=stop_token_ids or None)  # fmt: skip
        ins = [TokensPrompt(prompt_token_ids=p) if isinstance(p, list) else p for p in prompts]
        outs = self.llm.generate(ins, sp, use_tqdm=False)
        return [{"text": o.outputs[0].text, "ids": list(o.outputs[0].token_ids)} for o in outs]

    # ---- plan 0060 Phase E (wrong_intermediate logP legs): teacher-forced continuation scores ----
    def cont_logprobs(self, prompts: list[str], conts: list[str]) -> list[float]:
        """log P(cont | prompt) per pair, raw render (the subject's BOS + text, no template), as
        global-workspace ``wrong_bridge/qwen_modal.py`` scores it: ``prompt + cont`` teacher-
        forced, summed from the first token where it diverges from the prompt's own ids."""
        from vllm import SamplingParams
        from vllm.inputs import TokensPrompt

        jobs = cont_jobs(self.tok, prompts, conts)
        sp = SamplingParams(temperature=0.0, max_tokens=1, prompt_logprobs=0)
        outs = self.llm.generate([TokensPrompt(prompt_token_ids=ids) for ids, _k in jobs], sp,
                                 use_tqdm=False)  # fmt: skip
        return [
            sum_cont_logprob(o.prompt_logprobs, ids, k)
            for (ids, k), o in zip(jobs, outs, strict=True)
        ]

    # ---- end plan 0060 Phase E ----

    def gen_eos(self) -> list[int]:
        """The model config's and the generation config's eos ids (Qwen3.5's generation config
        adds <|im_end|>; Gemma's adds <turn|>)."""
        from transformers import AutoConfig, GenerationConfig

        ids: list[int] = []
        for load in (AutoConfig.from_pretrained, GenerationConfig.from_pretrained):
            try:
                cfg = load(self.hf_id, revision=self.revision)
            except (OSError, ValueError):
                continue
            for c in (cfg, getattr(cfg, "text_config", None)):
                e = getattr(c, "eos_token_id", None) if c is not None else None
                ids += e if isinstance(e, list) else [e] if e is not None else []
        return sorted(set(ids))


class RemoteRunner(Runner):
    """``Runner`` with generation on Modal (scripts/adapt_modal.py: the subject's own app,
    ``Subject.modal_app``) for subjects too big for the box: the template, rendering and grading
    stay local and identical. Prompts go to Modal as TOKEN IDS (the local render, tokenized
    without adding specials), so a BOS the render already carries (Gemma's ``<bos>``, GLM's
    ``[gMASK]<sop>``) is never doubled by the engine's own tokenization."""

    CHUNK = 512  # prompts per remote call (bounded payloads; the seed offset is the chunk start)

    def __init__(
        self,
        hf_id: str,
        revision: str | None = None,
        max_model_len: int = 4096,
        seed: int = 0,
        modal_app: str = "adapt-subject-llm",
        tokenizer_dir: str | None = None,
        chat_template: str | None = None,
        trust_remote_code: bool | None = None,
        replicas: int | None = None,
        **_: Any,
    ) -> None:
        import modal

        from . import subjects

        s = subjects.subject_for(hf_id, revision)  # its registered modal settings
        if s is None or not s.modal_built:
            why = ("is not a registered Subject" if s is None else
                   f"({s.key}) uses {s.modal_app!r}, an app scripts/adapt_modal.py does not build "
                   "(modal_built=False)")  # fmt: skip
            raise SystemExit(
                f"RemoteRunner: {hf_id}@{revision} {why}. RemoteRunner sends token ids, which only "
                "the apps built by scripts/adapt_modal.py accept: register the subject in "
                "subjects.py and deploy its app (ADAPT_SUBJECT=<key> modal deploy "
                "scripts/adapt_modal.py)."
            )
        if trust_remote_code is None:
            trust_remote_code = s.trust_remote_code
        self.replicas = replicas or s.modal_replicas
        self.hf_id, self.revision, self.seed = hf_id, revision, seed
        self.tok = subjects.load_tokenizer(hf_id, revision, tokenizer_dir, chat_template,
                                           trust_remote_code)  # fmt: skip
        cls = modal.Cls.from_name(modal_app, "SubjectLLM")
        self.remote = cls(model_id=hf_id, revision=revision or "", max_model_len=max_model_len)

    def encode(self, prompt: str | list[int]) -> list[int]:
        """A rendered prompt's token ids, as ``apply_chat_template(tokenize=True)`` gives them;
        the specials the tokenizer itself prepends (a Llama-style BOS) are added only when the
        render does not already start with them."""
        if isinstance(prompt, list):
            return prompt
        ids = list(self.tok(prompt, add_special_tokens=False)["input_ids"])
        if not hasattr(self, "_lead"):
            on = list(self.tok("x", add_special_tokens=True)["input_ids"])
            off = list(self.tok("x", add_special_tokens=False)["input_ids"])
            at = next((i for i in range(len(on) - len(off) + 1) if on[i : i + len(off)] == off), 0)
            self._lead = on[:at]
        lead = self._lead
        return ids if not lead or ids[: len(lead)] == lead else lead + ids

    def _calls(self, method: Any, args: list[tuple]) -> list:
        """One remote call per chunk: in order, or fanned over the subject's replicas."""
        if self.replicas > 1 and len(args) > 1:
            return list(method.starmap(args))
        return [method.remote(*a) for a in args]

    def sample(
        self, asks: list[Ask], draws: int, temperature: float, top_p: float = 1.0, top_k: int = -1
    ) -> list[tuple[str, list[str]]]:
        prompts = [self.encode(self.render(a)) for a in asks]
        n = self.CHUNK
        # top_k travels only when set, so an app deployed before it existed still serves the rest
        extra = (top_k,) if top_k != -1 else ()
        args = [(prompts[i : i + n], [a.max_tokens for a in asks[i : i + n]], draws, temperature,
                 top_p, self.seed + i, *extra) for i in range(0, len(prompts), n)]  # fmt: skip
        return [r for part in self._calls(self.remote.sample, args) for r in part]

    def generate(
        self,
        prompts: list,
        temperature: float,
        max_tokens: int,
        seed: int,
        top_p: float = 1.0,
        stop_token_ids: list[int] | None = None,
    ) -> list[dict]:
        ids = [self.encode(p) for p in prompts]
        n = self.CHUNK
        args = [(ids[i : i + n], temperature, max_tokens, seed + i, top_p, stop_token_ids)
                for i in range(0, len(ids), n)]  # fmt: skip
        return [r for part in self._calls(self.remote.generate, args) for r in part]

    # ---- plan 0060 Phase E (wrong_intermediate logP legs): scored on Modal from local token ids --
    def cont_logprobs(self, prompts: list[str], conts: list[str]) -> list[float]:
        jobs = cont_jobs(self.tok, prompts, conts)  # token ids, like sample / generate
        n = self.CHUNK
        args = [([j[0] for j in jobs[i : i + n]], [j[1] for j in jobs[i : i + n]])
                for i in range(0, len(jobs), n)]  # fmt: skip
        return [r for part in self._calls(self.remote.cont_logprobs, args) for r in part]

    # ---- end plan 0060 Phase E ----


# ---- plan 0060 Phase E: helpers for Runner.cont_logprobs (shared with scripts/adapt_modal.py) ----
def cont_jobs(tok: Any, prompts: list[str], conts: list[str]) -> list[tuple[list[int], int]]:
    """``(ids of BOS + prompt + cont, k)``: ``k`` = the first index where those ids diverge from
    the prompt's own ids (tokenization may merge at the seam), i.e. where scoring starts. The
    lead is the raw render's (``bos_prefix``: Gemma ``<bos>``, GLM ``[gMASK]<sop>``) or else the
    specials the tokenizer itself prepends (a Llama-style BOS, as ``RemoteRunner.encode`` adds):
    the ids go to the engine as-is, which adds nothing."""
    from .template import bos_prefix

    bos = list(bos_prefix(tok))
    if not bos:
        on = list(tok("x", add_special_tokens=True)["input_ids"])
        off = list(tok("x", add_special_tokens=False)["input_ids"])
        at = next((i for i in range(len(on) - len(off) + 1) if on[i : i + len(off)] == off), 0)
        bos = on[:at]
    out = []
    for p, c in zip(prompts, conts, strict=True):
        p_ids = bos + tok(p, add_special_tokens=False)["input_ids"]
        full = bos + tok(p + c, add_special_tokens=False)["input_ids"]
        k = 0
        while k < len(p_ids) and k < len(full) and full[k] == p_ids[k]:
            k += 1
        out.append((full, k))
    return out


def sum_cont_logprob(prompt_logprobs: list, ids: list[int], k: int) -> float:
    """Sum of the teacher-forced log-probs of ``ids[max(k, 1):]`` (vLLM ``prompt_logprobs``: one
    ``{token_id: Logprob}`` per position, None at 0)."""
    return float(sum(prompt_logprobs[i][ids[i]].logprob for i in range(max(k, 1), len(ids))))


# ---- end plan 0060 Phase E ----


GRADE_WORKERS = int(os.environ.get("ADAPT_CLAUDE_WORKERS", "16"))  # org OTPM is shared


def run_gate(
    runner: "Runner",
    asks: Iterable[Ask],
    draws: int = DEFAULT_DRAWS,
    temperature: float = DEFAULT_TEMPERATURE,
    threshold: float = DEFAULT_THRESHOLD,
    llm: Callable[[Ask, list[str]], list[bool | None]] | None = None,
    top_p: float = 1.0,
    top_k: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Gate every ask; returns ``{item_id: gate_record}``. ``top_k`` is passed to the runner only
    when a family's gate fixes one."""
    from concurrent.futures import ThreadPoolExecutor

    asks = list(asks)
    kw = {} if top_k is None else {"top_k": top_k}  # only when a family's gate fixes one
    # plan 0060 D10: a follow-up ask needs its reply first; one whose read render is not a token
    # prefix is not sampled (its leg is undecided)
    later = iter(with_replies(runner, [a for a in asks if a.followup]))
    asks = [next(later) if a.followup else a for a in asks]
    live = [a for a in asks if not _broken(a)]
    got = iter(runner.sample(live, draws, temperature, top_p, **kw) if live else [])
    outs = [("", [""] * draws) if _broken(a) else next(got) for a in asks]

    def grade(pair: tuple) -> Leg:
        ask, (greedy, samples) = pair
        return grade_leg(ask, greedy, samples, threshold, llm)

    # model grading is network-bound: one call at a time took ~3 h for 170 items
    with ThreadPoolExecutor(GRADE_WORKERS if llm is not None else 1) as pool:
        graded = list(pool.map(grade, zip(asks, outs, strict=True)))
    legs: dict[str, dict[str, Leg]] = {}
    for ask, leg in zip(asks, graded, strict=True):
        legs.setdefault(ask.item_id, {})[ask.leg] = leg
    return {iid: gate_record(lg) for iid, lg in legs.items()}


def _broken(ask: Ask) -> bool:
    return (ask.meta.get("followup") or {}).get("prefix") == "broken"


def with_replies(runner: "Runner", asks: list[Ask]) -> list[Ask]:
    """Fill each follow-up ask's ``reply`` with the subject's greedy answer to its first turn, and
    check the token prefix: the read render's ids must start the follow-up's. When they do not,
    the reply's leading whitespace is stripped (Qwen merges a reply's leading ``\n`` into the
    generation prompt's ``\n\n``) and the check repeated; still not a prefix = ``broken`` (the
    leg is left undecided). ``meta["followup"]`` records the outcome and whether the reply
    already states a gold form (deterministic, any line)."""
    replies: dict[int, str] = {}
    todo: dict[int, list[int]] = {}  # max_tokens -> indices
    for i, a in enumerate(asks):
        todo.setdefault(int(a.meta.get("reply_tokens", 128)), []).append(i)
    for max_tokens, idx in todo.items():
        prompts = [runner.render(asks[i].first_turn()) for i in idx]
        got = runner.generate(prompts, temperature=0.0, max_tokens=max_tokens,
                              seed=getattr(runner, "seed", 0))  # fmt: skip
        replies.update({i: g["text"] for i, g in zip(idx, got, strict=True)})
    out = []
    for i, a in enumerate(asks):
        head, reply = runner.render(a.first_turn()), replies[i]
        check: dict[str, Any] = {"prefix": "exact"}
        if not runner.token_prefix(head, runner.render(replace(a, reply=reply))):
            check = {"prefix": "stripped", "reply_raw": reply}
            reply = reply.lstrip()
            if not runner.token_prefix(head, runner.render(replace(a, reply=reply))):
                check["prefix"] = "broken"
        check["reply_states_gold"] = any(_has_form(reply, g) for g in a.golds)
        out.append(replace(a, reply=reply, meta={**a.meta, "followup": check}))
    return out


def answer_histogram(record: dict[str, Any], top: int = 5) -> list[tuple[str, int]]:
    return Counter(fold(s["text"]).strip() for s in record["samples"]).most_common(top)
