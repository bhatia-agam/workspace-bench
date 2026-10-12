"""Gate a candidate bank on an open-weights subject model (HF transformers): greedy + K samples
with thinking off, deterministic sign-aware grading (optional LLM grader for the misses),
model-specific golds, tokenizer re-stamping, and the out-of-capability verdict.

    uv run --extra gpu python .claude/skills/wsb-new-questions/scripts/gate_hf.py \\
        --family multihop --bank cand/multihop.json --model Qwen/Qwen3.5-0.8B \\
        --out gated/multihop

Writes <out>/gate.json (every question, answer and verdict), <out>/items.json (the passers,
stamped for this subject) and <out>/summary.json (rates, OOC verdict). Needs a GPU for anything
bigger than ~2B parameters (--device cpu works for tiny models, slowly).
"""

import argparse
import json
import math
import random
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_bank import LIST_BANKS, MT_FAMILIES, load_any, make_shadow

ANSWER_STEM = "My one-word answer is:"  # basic_readout implicit items (the plan's prefill)
FINAL_ANSWER = {"arithmetic_intermediates", "chain_intermediates", "brew_intermediates"}
STRICT = {"chain_intermediates", "brew_intermediates"}  # 10/10 at T=0.8, top_p=0.95
MC = {"conjunctive_association", "role_bound_association"}
GREEDY_ONLY = {"relational_multihop"}  # greedy-correct, both items of a scene
UNSUPPORTED = {
    "moral_rationale": "its golds are elicited from the subject (SKILL.md, moral_rationale)",
    "multi_concept_directed_modulation": "no capability gate: the sentence is prefilled",
    "user_modeling": "kept as-is in the reference recipe; use `wsbench capable` to check",
}
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w])")


# ------------------------------------------------------------------ grading


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", t).strip()


def string_match(answer: str, golds: list[str]) -> bool:
    """Word-aligned containment after folding (drops punctuation AND the minus sign)."""
    a = f" {norm(answer)} "
    return any(g and f" {norm(g)} " in a for g in map(str, golds))


def as_num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def quick_match(answer: str, golds: list[str], final: bool) -> bool:
    """``final`` families: a numeric gold must be the answer's LAST number, sign included
    (plain string_match would accept 1386 for -1386); a colour gold is a whole-word match."""
    if not final:
        return string_match(answer, golds)
    nums = NUM.findall(answer.replace(",", ""))
    for g in map(str, golds):
        gv = as_num(g)
        if gv is None:
            if string_match(answer, [g]):
                return True
        elif nums and as_num(nums[-1]) == gv:
            return True
    return False


def first_word(text: str) -> str:
    m = re.search(r"[^\W\d_][\w'-]*|\d+", text)
    return m.group(0).casefold().strip("'-") if m else ""


def mc_letter(text: str) -> str:
    m = re.match(r"\s*\(?([A-P])\)?(?![a-z])", text)
    return m.group(1) if m else ""


def rhymes(a: str, b: str) -> bool:
    """CMU rhyming part shared (any pronunciation), else the same final two letters."""
    if a == b:
        return True
    try:
        import pronouncing  # type: ignore[import-not-found]
    except ImportError:
        return a[-2:] == b[-2:]
    pa, pb = pronouncing.phones_for_word(a), pronouncing.phones_for_word(b)
    if pa and pb:
        return bool(
            {pronouncing.rhyming_part(p) for p in pa} & {pronouncing.rhyming_part(p) for p in pb}
        )
    return a[-2:] == b[-2:]


def line_one_end(prompt: str) -> str:
    lines = [ln for ln in prompt.split("\n") if ln.strip()]
    words = re.findall(r"[A-Za-z']+", lines[-2] if len(lines) >= 2 else lines[0])
    return words[-1].casefold() if words else ""


# ------------------------------------------------------------------ questions


def key_of(family: str, it: dict[str, Any]) -> str:
    return (
        str(it["id"]) if family in LIST_BANKS else re.sub(r"[^A-Za-z0-9._-]", "_", str(it["name"]))
    )


def mc_ask(it: dict[str, Any]) -> tuple[str, str]:
    opts = list(it.get("mc_options") or [it["gold_label"], it["contrast_label"]])
    if it["gold_label"] not in opts:
        opts = [it["gold_label"], *opts]
    random.Random(f"pm-mc|{it['id']}").shuffle(opts)
    letters = "ABCDEFGHIJKLMNOP"
    listing = "\n".join(f"({letters[i]}) {o}" for i, o in enumerate(opts))
    ask = (
        f"{it['stimulus']}\n\nWhich option best describes what the text implies?\n{listing}"
        "\n\nReply with the letter only."
    )
    return ask, letters[opts.index(it["gold_label"])]


def build_questions(family: str, items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    from wsbench.capable.questions import build

    out: list[dict[str, Any]] = []

    def q(
        qid: str, ask: str, golds: list[str], mode: str, prefill: str = "", max_new: int = 64
    ) -> None:
        out.append(
            {
                "qid": qid,
                "item": qid.split(":bridge")[0],
                "ask": ask,
                "golds": golds,
                "mode": mode,
                "prefill": prefill,
                "max_new": max_new,
            }
        )

    if family in MC:
        for k, it in items.items():
            ask, gold = mc_ask(it)
            q(k, ask, [gold], "mc", max_new=8)
    elif family == "poetry":
        for c in build(family):
            q(c.id, c.ask, [], "own_poetry", max_new=16)
    elif family == "directed_modulation":
        for k, it in items.items():
            q(k, it["prompt"], [it["carrier"]], "dm", max_new=64)
    else:
        for c in build(family):
            golds = list(c.golds)
            if family in FINAL_ANSWER:  # capable's golds are the intermediates for these
                golds = [str(items[c.id.split(":bridge")[0]]["answer"])]
            q(c.id, c.ask, golds, "greedy" if family in GREEDY_ONLY else "standard")
        if family == "basic_readout":
            for k, it in items.items():
                if it.get("subfamily") == "implicit":
                    q(k, it["prompt"], [], "own_implicit", prefill=ANSWER_STEM, max_new=16)
    return out


# ------------------------------------------------------------------ generation


class Subject:
    def __init__(self, model_id: str, device: str, dtype: str) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.tok.padding_side = "left"
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, dtype=getattr(torch, dtype), device_map=device
        )
        self.model.eval()
        self.device = device
        stops = {self.tok.eos_token_id}
        for t in ("<|im_end|>", "<|endoftext|>", "<end_of_turn>", "<turn|>"):
            i = self.tok.convert_tokens_to_ids(t)
            if isinstance(i, int) and i >= 0 and i != self.tok.unk_token_id:
                stops.add(i)
        self.stops = sorted(s for s in stops if s is not None)

    def render(self, ask: str, prefill: str) -> list[int]:
        """The benchmark's chat render: user turn only, thinking OFF, optional prefill."""
        out = self.tok.apply_chat_template(
            [{"role": "user", "content": ask}],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        ids = list(out["input_ids"] if hasattr(out, "keys") else out)
        if prefill:
            ids += self.tok(prefill, add_special_tokens=False)["input_ids"]
        return ids

    def generate(
        self,
        prompts: list[list[int]],
        *,
        n: int,
        temperature: float,
        top_p: float,
        max_new: int,
        batch: int,
        seed: int,
    ) -> list[list[str]]:
        torch = self.torch
        torch.manual_seed(seed)
        order = sorted(range(len(prompts)), key=lambda i: len(prompts[i]))
        res: list[list[str]] = [[] for _ in prompts]
        bs = max(1, batch // max(1, n))
        for s in range(0, len(order), bs):
            idx = order[s : s + bs]
            enc = self.tok.pad({"input_ids": [prompts[i] for i in idx]}, return_tensors="pt")
            enc = {k: v.to(self.model.device) for k, v in enc.items()}
            kw: dict[str, Any] = {
                "max_new_tokens": max_new,
                "eos_token_id": self.stops,
                "pad_token_id": self.tok.pad_token_id,
            }
            if temperature > 0:
                kw |= {
                    "do_sample": True,
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": 0,
                    "num_return_sequences": n,
                }
            else:
                kw |= {"do_sample": False}
            with torch.no_grad():
                gen = self.model.generate(**enc, **kw)
            width = enc["input_ids"].shape[1]
            for j, row in enumerate(gen[:, width:].tolist()):
                cut = next((p for p, t in enumerate(row) if t in self.stops), len(row))
                text = self.tok.decode(row[:cut], skip_special_tokens=True).strip()
                res[idx[j // (n if temperature > 0 else 1)]].append(text)
        return res


# ------------------------------------------------------------------ per-subject stamping


def ntok(tok: Any, s: str) -> int:
    """Strict token count: min over {s, lower, title} x {bare, leading space}."""
    return min(
        len(tok(v, add_special_tokens=False)["input_ids"])
        for c in {s, s.lower(), s.title()}
        for v in (c, " " + c)
    )


def stamp_mt(it: dict[str, Any], tok: Any, family: str) -> bool:
    """Re-stamp probe_token_lens with the subject tokenizer; False when a required multi-token
    unit keeps no multi-token form in some non-zh language (the item is then ineligible)."""
    units: dict[str, dict[str, list[int]]] = {}
    ok = True
    for u in it.get("units", []):
        forms = u.get("forms") or {}
        units[u["role"]] = {lang: [ntok(tok, f) for f in fs] for lang, fs in forms.items()}
        if u.get("required", True) and u.get("multi_token", True):
            for lang, counts in units[u["role"]].items():
                if lang != "zh" and not any(c > 1 for c in counts):
                    ok = False
    ptl: dict[str, Any] = {"units": units, "target": ntok(tok, str(it.get("target", "")))}
    if family == "multihop_mt":
        ptl["target_alts"] = [ntok(tok, str(a)) for a in it.get("target_alts", [])]
    it["probe_token_lens"] = ptl
    return ok


def multihop_offsets(it: dict[str, Any], tok: Any) -> None:
    ids = tok(it["prompt"], add_special_tokens=False)["input_ids"]
    last = tok.decode(ids[-1:])
    it["readout"] = {"kind": "last_word_token", "offsets": [-2 if not last.strip() else -1]}


def brew_cells(it: dict[str, Any], tok: Any) -> None:
    """eval_positions + regions in the subject's chat_prefill 'Answer:' render: the stir /
    start / question lines plus the emission cells n-7, n-3, n-1 (Qwen-style chat tail; check
    the tail tokens by eye for another template family)."""
    out = tok.apply_chat_template(
        [{"role": "user", "content": it["prompt"]}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    ids = list(out["input_ids"] if hasattr(out, "keys") else out)
    ids += tok("Answer:", add_special_tokens=False)["input_ids"]
    text = tok.decode(ids)
    enc = tok(text, add_special_tokens=False, return_offsets_mapping=True)
    if enc["input_ids"] != ids:
        raise RuntimeError(f"{it['name']}: the decoded render does not re-tokenize identically")
    lines = it["prompt"].split("\n")
    base = text.index(it["prompt"])
    regions: dict[str, str] = {}
    for reg, line in (("stir", lines[-3]), ("start", lines[-2]), ("question", lines[-1])):
        a = base + it["prompt"].rindex(line)
        b = a + len(line)
        for k, (s, e) in enumerate(enc["offset_mapping"]):
            if s >= a and e <= b and e > s:
                regions[str(k)] = reg
    n = len(ids)
    for reg, k in (("emit_asst", n - 7), ("emit_think", n - 3), ("emit_colon", n - 1)):
        regions[str(k)] = reg
    pos = sorted(int(k) for k in regions)
    it["eval_positions"] = pos
    it["regions"] = {str(p): regions[str(p)] for p in pos}


# ------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--family", required=True)
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--model", required=True, help="HF id of the subject model")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--k", type=int, default=10, help="sampled draws per question")
    ap.add_argument("--min-pass", type=int, default=8, help="of K (STRICT families: K)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--batch", type=int, default=256, help="sequences per generate call")
    ap.add_argument(
        "--grader",
        default="",
        help="optional LLM grader for answers the string match rejects, e.g. "
        "google/gemini-3.8-flash (OPENROUTER_API_KEY) or a claude-* id "
        "(ANTHROPIC_API_KEY); empty = deterministic grading only",
    )
    ap.add_argument(
        "--capacity",
        type=int,
        default=0,
        help="how many candidates this family could ever supply (for the OOC rule)",
    )
    a = ap.parse_args()
    fam = a.family
    if fam in UNSUPPORTED:
        print(f"{fam}: not gated by this script: {UNSUPPORTED[fam]}", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    header, raw_items, is_list = load_any(a.bank)
    shadow = make_shadow(a.repo.resolve(), fam, a.bank.resolve(), a.out.resolve() / "work")
    sys.path.insert(0, str(shadow / "src"))
    from wsbench.banks import load_bank

    items_l = raw_items if is_list else load_bank(shadow / "evals" / fam / "items.json")[1]
    items = {key_of(fam, it): it for it in items_l}
    qs = build_questions(fam, items)
    print(f"{fam}: {len(items)} items, {len(qs)} questions; loading {a.model}")
    subj = Subject(a.model, a.device, a.dtype)
    final = fam in FINAL_ANSWER

    # 1. greedy
    for mx in sorted({q["max_new"] for q in qs}):
        group = [q for q in qs if q["max_new"] == mx]
        outs = subj.generate(
            [subj.render(q["ask"], q["prefill"]) for q in group],
            n=1,
            temperature=0.0,
            top_p=1.0,
            max_new=mx,
            batch=a.batch,
            seed=0,
        )
        for q, o in zip(group, outs, strict=True):
            q["greedy"] = o[0]

    def hit(q: dict[str, Any], ans: str) -> bool | None:
        m = q["mode"]
        if m == "mc":
            return mc_letter(ans) == q["golds"][0]
        if m == "dm":
            it = items[q["item"]]
            return norm(ans) == norm(it["carrier"]) and not string_match(ans, [it["concept"]])
        if m in ("own_poetry", "own_implicit"):
            return None  # decided after sampling, against the greedy word
        if quick_match(ans, q["golds"], final):
            return True
        return None if a.grader and not final else False

    for q in qs:
        q["greedy_ok"] = hit(q, q["greedy"])
    # 2. samples (only where greedy can still pass)
    strict = fam in STRICT
    temp, top_p = (0.8, 0.95) if strict else (0.7, 1.0)
    need = a.k if strict else a.min_pass
    todo = [q for q in qs if q["mode"] != "greedy" and q["greedy_ok"] is not False]
    for mx in sorted({q["max_new"] for q in todo}):
        group = [q for q in todo if q["max_new"] == mx]
        outs = subj.generate(
            [subj.render(q["ask"], q["prefill"]) for q in group],
            n=a.k,
            temperature=temp,
            top_p=top_p,
            max_new=mx,
            batch=a.batch,
            seed=7,
        )
        for q, o in zip(group, outs, strict=True):
            q["samples"] = o
    # 3. optional LLM grading of undecided answers
    if a.grader:
        from wsbench.capable.questions import Question
        from wsbench.capable.run import GRADE_SCHEMA, GRADE_SYSTEM, render_grade
        from wsbench.llm import stream_json

        pend: list[tuple[dict[str, Any], int, str]] = []
        for q in qs:
            if q["mode"] not in ("standard", "greedy"):
                continue
            for i, ans in enumerate([q["greedy"], *q.get("samples", [])]):
                if ans and not quick_match(ans, q["golds"], final):
                    pend.append((q, i, ans))
        verdicts: dict[tuple[str, int], bool] = {}
        prompts = [
            (GRADE_SYSTEM, render_grade(Question(q["qid"], q["ask"], q["golds"]), ans))
            for q, _i, ans in pend
        ]

        def on(i: int, r: dict[str, Any] | None) -> None:
            verdicts[(pend[i][0]["qid"], pend[i][1])] = bool(r and r.get("correct"))

        if prompts:
            stream_json(prompts, schema=GRADE_SCHEMA, model=a.grader, on_result=on, temperature=0.0)
        for q in qs:
            if q["mode"] in ("standard", "greedy"):
                q["llm"] = {str(i): v for (qid, i), v in verdicts.items() if qid == q["qid"]}
    # 4. verdicts
    for q in qs:
        m, answers = q["mode"], [q["greedy"], *q.get("samples", [])]
        if m in ("own_poetry", "own_implicit"):
            w = first_word(q["greedy"])
            hits = sum(first_word(s) == w for s in q.get("samples", []))
            q["word"] = w
            ok_w = bool(w)
            if m == "own_poetry":
                q["line_one_end"] = line_one_end(q["ask"])
                q["rhymes"] = ok_w and rhymes(w, q["line_one_end"])
                ok_w = q["rhymes"]
            q["hits"], q["pass"] = hits, ok_w and hits >= need
            continue

        def ok(i: int, ans: str, q: dict[str, Any] = q) -> bool:
            v = hit(q, ans)
            return bool(v) if v is not None else bool(q.get("llm", {}).get(str(i)))

        q["greedy_ok"] = ok(0, answers[0])
        if m == "greedy":
            q["hits"], q["pass"] = None, q["greedy_ok"]
            continue
        hits = sum(ok(i + 1, s) for i, s in enumerate(q.get("samples", [])))
        q["hits"], q["pass"] = hits, q["greedy_ok"] and hits >= need
    # 5. item verdicts (every leg must pass; relational: both items of a scene)
    by_item: dict[str, list[dict[str, Any]]] = {}
    for q in qs:
        by_item.setdefault(q["item"], []).append(q)
    passed = {k: all(q["pass"] for q in v) for k, v in by_item.items()}
    if fam in GREEDY_ONLY:
        scenes: dict[str, list[str]] = {}
        for k, it in items.items():
            scenes.setdefault(str(it.get("scene")), []).append(k)
        for ks in scenes.values():
            both = all(passed.get(k) for k in ks)
            for k in ks:
                passed[k] = both
    if fam == "arithmetic_intermediates":  # twins survive together
        for k, it in items.items():
            tw = re.sub(r"[^A-Za-z0-9._-]", "_", str(it.get("pair") or ""))
            if tw in items and not passed.get(tw):
                passed[k] = False
    # 6. stamp passers for this subject
    tok = subj.tok
    kept, dropped = [], {}
    for k, it in items.items():
        if not passed.get(k):
            continue
        it = dict(it)
        if not is_list:
            it.pop("id", None)
        legs = by_item.get(k, [])
        main = next((q for q in legs if q["qid"] == k), legs[0] if legs else None)
        if main and main.get("hits") is not None:
            it["consistency"] = main["hits"] / a.k
        if main:
            it["consistency_greedy"] = int(bool(main["greedy_ok"]))
        if fam in ("multihop_mt", "multilingual_multihop"):
            it["bridge_consistency"] = {
                q["qid"].split(":")[1]: q["hits"] / a.k for q in legs if ":bridge" in q["qid"]
            }
        if fam == "poetry":
            it["intermediates"] = [main["word"]]
        if fam == "basic_readout" and it.get("subfamily") == "implicit":
            w = next(q["word"] for q in legs if q["mode"] == "own_implicit")
            it["target"], it["intermediates"] = w, [w]
            it["units"] = [{"role": "readout", "lang": "en", "headline": True, "match": [w]}]
        if fam in MT_FAMILIES and not stamp_mt(it, tok, fam):
            dropped[k] = "a required unit has no multi-token form under this tokenizer"
            continue
        if fam == "multihop":
            multihop_offsets(it, tok)
        if fam == "brew_intermediates":
            brew_cells(it, tok)
        kept.append(it)
    if fam == "arithmetic_intermediates":  # null sets may only point at surviving items
        names = {re.sub(r"[^A-Za-z0-9._-]", "_", it["name"]) for it in kept}
        for it in kept:
            it["null_set"] = [n for n in it.get("null_set", []) if n in names]
            it["pair_survived"] = it.get("pair") in names
    rate = sum(passed.values()) / max(1, len(passed))
    n_eval = len(passed)
    floor = min(200, a.capacity) if a.capacity else 200
    status = (
        "ooc"
        if n_eval >= floor and rate < 0.03
        else "undetermined (gate >= min(200, capacity) candidates before calling OOC)"
        if rate < 0.03
        else "in-capability"
    )
    gate_note = (
        f"{a.model} behavioral, chat template (enable_thinking=False): greedy-correct "
        f"AND >= {need}/{a.k} @ T={temp} top_p={top_p}; gate_hf.py"
    )
    out_bank: Any = kept if is_list else {**header, "gate": gate_note, "items": kept}
    (a.out / "items.json").write_text(
        json.dumps(out_bank, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (a.out / "gate.json").write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {
        "family": fam,
        "model": a.model,
        "n_items": n_eval,
        "n_pass": sum(passed.values()),
        "pass_rate": round(rate, 4),
        "n_kept": len(kept),
        "dropped_after_gate": dropped,
        "status": status,
        "want_more_candidates_for_100": math.ceil(max(0, 100 - len(kept)) / max(rate, 0.03) * 1.3),
        "rule": gate_note,
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
