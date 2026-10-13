# Porting workspace-bench to a new subject model

The banks were built and gated on **Qwen3.6-27B**. Every item asks "does the lens surface what *this
model* computes but never writes?" — so an item is only meaningful on a new model if that model
actually computes the scored latent. Porting is therefore not "run the readouts on the new model";
it is: **re-gate every item on the new model, rewrite what fails, and re-target the families whose
gold IS the model's own choice.** This guide is the procedure, in order. The worked example
throughout is DeepSeek-V4-Flash (2026-10-13; full write-up in the source repo,
`docs/project/experiments/v4_flash_ar/wsbench_v4_suitability.md`).

The short version:

1. Render and capture correctly for the new model (§1).
2. Run the new model on **every existing question** with `wsbench capable` (§2).
3. Per family, keep the items that pass the gate; **rewrite the failing items until they pass, or
   drop them**; a family whose items cannot be made to pass does not port (§3).
4. **Always** rewrite poetry and moral_rationale for the new model — their gold is the model's own
   rhyme / side / reasons (§4).
5. Regenerate the families whose bank is the model's own output (§5).
6. Judge with one pinned instrument, report gated and all-items numbers side by side (§6–§7).

---

## 1. Render, tokenize, capture — what is model-specific regardless of the gate

- **Chat template, thinking off.** Every bench render is a non-thinking chat turn (or plain text with
  BOS). Build prompts with the new model's *own* encoder and check the tail token by token; for
  V4 that is `encode_messages(..., thinking_mode="chat")`, ending `<｜Assistant｜></think>`. Never
  trust a server's default template for scoring.
- **Tail-relative position rules change meaning.** Qwen's assistant tail is 9 tokens, V4's is 2.
  Any `last_n` rule reads different things: moral_rationale's `last_n 5` is all template on Qwen
  but 3 stimulus tokens + 2 template tokens on V4. Decide per family whether that is acceptable.
- **Token positions are tokenizer-specific.** Families that pin token indices
  (jailbreak_recognition, brew emission cells, arithmetic frozen cells) need re-resolving on the new
  tokenizer (by text/char offset, never by index).
- **Depth map.** Map the bench's layers to the new model by depth fraction and record the map;
  per-layer curves are not comparable layer-for-layer across models. A lens fitted to a target
  layer cannot read past it (V4's J-lens reads its L42 cells at L41).
- **Banks already remapped to the new model's numbering** (e.g. buggy_code's read layer) must not be
  mapped again by the producer.
- **Readout spelling.** Token lenses spell tokens byte-level (`display_tokens`). For a CJK-heavy
  model (33 % of V4's J-lens tokens are non-ASCII) check the judge reads them: under Opus 5.5 the
  decoded and byte-level readouts score the same (association 0.546 vs 0.540); a weaker judge may not.

## 2. Run the new model on every existing question

```
wsbench capable model=<new-model> judge_model=<grader> families=all draws=10
```

`capable` asks each bank's own question, takes one greedy and 10 sampled answers (T 0.7), grades
them, and marks an item as passing when the greedy answer is right AND ≥ 8/10 samples are (10/10 for
chain and brew). `bank` in its output is Qwen's rate on the same items.

Practicalities learned on V4:

- **Self-hosted model:** `WSBENCH_OPENAI_BASE_URL` / `WSBENCH_OPENAI_API_KEY` point the answer route
  at an OpenAI-compatible server (vLLM); `WSBENCH_CHAT_TEMPLATE_KWARGS` passes e.g. a thinking
  switch. Without a server, generate the answers in a batch job and seed them into `capable`'s
  cache under its own fingerprints (`(prompt_version, model, reasoning, temperature, system,
  user)`), so `capable` only grades — exact and resumable.
- **Always pass `judge_model=`** — otherwise the default Gemini grader goes to the override URL.
- **Run `capable` on the banks as shipped, before re-targeting anything** — after re-targeting it
  would grade the model against its own answers.
- `capable` adds a system prompt and asks for a JSON answer; it is a capability *proxy* for the
  banks' raw-continuation gates, not the identical gate. Read association and conjunctive loosely
  (the grader can be strict on synonyms, and conjunctive is graded against a prose label).

## 3. Rewrite until the items pass the gate (or drop them)

For every family with a `capable` question:

| outcome | action |
|---|---|
| item passes | keep as is |
| item fails because the model answers *differently but correctly* (synonym, alias) | widen the gold (`target_alts`), re-grade |
| item fails because the model cannot do it | rewrite the item (simpler / clearer, same latent) with the family's generator, re-gate; else drop |
| most of the family fails | the family does not port at this difficulty: re-author at a level the model passes (the state-tracking generators already freeze at "the hardest ladder level the model passes") — or report it as not portable |

Record `gate_pass_<model>` and the rate on every item, keep failing items in the bank with their
flags (the scorers ignore gate fields), and score the gated subset with `wsbench judge … items=<ids>`.

**Check the no-chain-of-thought families by hand.** chain, brew and arithmetic assume the model
computes the intermediate silently and then answers. A model that stops early answers *the
intermediate itself*: V4 answers brew's first-step colour on 95/100 items (gate 0.05 vs Qwen 1.00),
so the "silent intermediate" is V4's output and the family measures output reading. That family
does not port by rewriting — a one-step item has no intermediate left to read.

## 4. Always rewrite: poetry and moral_rationale

These two families' gold is not a fact about the world, it is **the model's own choice**. Re-target
them for every new model, even if `capable` looks fine (it only checks agreement with Qwen).

### Poetry — the rhyme the model plans at the read site

The read site is the newline after line one; the latent is the rhyme the model has already planned
there. Probe it directly:

1. Feed `BOS + "A rhyming couplet:\n" + line1 + "\n"` (the prompt cut at the read site — assert it is
   a token prefix of the full prompt) and let the model write line two: greedy + 10 samples at
   T 0.7, stop at the newline.
2. The planned rhyme = the last word of each complete line (case/plural-folded). A cut-off or empty
   line is a miss.
3. Gate: greedy rhyme == majority rhyme AND majority ≥ 8/10. Target = that word.
4. If too few items pass, **re-author the bank**: generate candidate first lines, probe them, keep the
   couplets where the model commits, and build each item's prompt from the model's *own* greedy line
   two minus its last word (so the forced reading agrees), with no leak (the target never appears in
   the prompt) and one item per target word.

Do not re-target by completing the shipped line-two prefix: that prefix was written for the old
model and nearly dictates the word (V4 matched Qwen's rhyme 97/100 that way, yet committed to a
plan on only 10/100 shipped couplets). Strip the prompt's trailing space before any forced reading
— a trailing `' '` token produced `"ight"` targets.

### Moral rationale — the model's own side and reasons

Reasons are sampled from the subject, never authored. Re-run the bank's Phase 1 with the new model
as the subject (source scripts `ec_elicit_gpu.py` → `ec_finalize.py` → `ec_gate_gpu.py` /
`ec_gate_finalize.py`):

1. **Elicit:** one row per dilemma (`question` + "First answer yes or no. Then, in one short
   sentence, state the single most important consideration…"), chat thinking-off, 1 greedy + 8
   samples at T 0.8 / top-p 0.95, max 96 tokens.
2. **Finalize:** a strong judge distils the samples into canonical reasons (text, `supports`,
   `terms`, `frequency`) and classifies committed vs deliberative (`ec_finalize.py`'s prompt +
   schema). Fail hard on a judge error — never keep the old model's reasons under the new label.
3. **Targets:** committed → the top reason **supporting the model's committed side** (the original
   finalize took `reasons[0]` whatever its side); deliberative → the top yes-reason and the top
   no-reason. Every `look_for_reasons` entry must be a verbatim `reasons[].text` (the judge matches
   them by exact text; a mismatch silently makes the item unpassable).
4. **Gate:** greedy one-word answer on each item's own stimulus: a clean decision token, exactly one
   word, aligned with the elicited side (any clean decision for deliberative items).
5. Every item's distractors are rebuilt from the new bank, so the whole family is re-judged.

V4: 38/200 items flip side vs Qwen, 38 change class, 24 deliberative (Qwen 34), 188/200 pass.

## 5. Regenerate: families whose bank is the model's own output

| family | what to regenerate |
|---|---|
| hallucination | the model's own responses to the 149 prompts + their read sites |
| basic_readout (32 implicit items) | the model's own favourites (`"what is your favourite …"`) |
| agentic_misalignment | re-run the scenarios — a model that does not misbehave has nothing to read |
| directed_modulation | re-run the compliance screen |
| jailbreak_recognition | re-capture read positions with the new tokenizer |
| jlens_concept_pr | re-capture; its reference J-lens must be the new model's |

## 6. Judge and floors

- **One pinned judge per pass**; numbers are comparable only within a pass. If you change the
  judge (V4 used Opus 5.5 after the Gemini key ran out), say so on every figure.
- **Refusals:** a more safety-tuned judge can make a family unscorable — Opus 5.5 refused 7.8 % of
  agentic stage-A calls and the bench skips any item with a refusal. Fall back to the family's
  pinned judge (Sonnet 5) for that family and label it.
- **Floors** (`evals/baselines/`) were measured with Qwen + Gemini; re-measure them for a new model
  or judge before drawing them.

## 7. Report

Per family: `capable` gate on the new model beside Qwen's `bank`; the lens score on **all items**
and on **gated items** (`items=`, cached, no new calls for unchanged banks); for poetry / moral the
re-targeted score, labelled with its target definition. Flag families that do not port (brew on
V4) instead of averaging them in.

## Checklist

- [ ] encoder render checked token by token (thinking off); positions re-resolved on the new tokenizer
- [ ] depth map recorded; banks already in the new numbering not re-mapped
- [ ] `capable` run on the **shipped** banks, all families, pinned grader
- [ ] failing items rewritten/re-gated or dropped; gate fields + rates on every item
- [ ] poetry: planned rhyme probed at the read site; bank re-authored where the model does not commit
- [ ] moral: Phase 1 re-run with the new subject; side-supporting targets; verbatim look_for
- [ ] model-output families regenerated (§5)
- [ ] one judge per pass; refusal rates checked; floors re-measured or omitted
- [ ] report gated + all-items, and list the families that do not port
