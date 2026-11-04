# 0064: hinted_cutoff reads the prompt only

Issue #264. Follows plan 0063 (PR #261).

## Camila's ask (2026-11-04, verbatim)

> how does the floor beat the lens?? we shouldn't show it the reply, just the prompt. olens
> redouts should also only be ffrom the prompt

## Why

The merged family has two problems.

**It reads the reply.** It reads at Qwen's silent-reply positions and ships prompt + reply ids.

**Its floor sees the reply too.** The generic prompt-only floor reader (`po-opus-v1`) decodes the
render through the last read site, so Opus sees nearly the whole reply. Its floor is +0.63, higher
than the O-lens summary score of +0.355. That is not a prompt-only floor.

## Change

Every reader, lens and floor alike, sees **only the prompt**: Qwen's chat-templated user turn up
to and including the generation prompt. The read positions are the frozen gw **prompt span**.

### 1. Bank (`scripts/build_hinted_cutoff_bank.py` → `evals/hinted_cutoff/items.json`)

**`positions`** = `spans.prompt`, used verbatim. This is the gw read set the frozen prompt-span
O-lens numbers were measured on:
- the user-turn tokens, length-equalized within each pair (mean 46.5, range 38–58);
- 88 of 222 items have gaps, so `full_contiguous` stays `False`;
- hint tokens are never read positions:
  - in the 103 metadata pairs the span starts after `</question-metadata>`, so the hint is in context;
  - in the 8 authority/sycophancy pairs (16 items) the span ends at the answer-format line, before
    the hint sentence, so neither a lens nor the floor (which decodes only through the last read
    site) sees the hint there. This is the gw `prompt_set` rule, and the replay is unaffected.

**`input_ids`** = `input_ids[:n_prompt]`, the prompt only.

**Removed from the bank:**
- the `reply` text;
- `spans.reply`.

`spans` keeps `prompt` and `question`. Nothing a reader is given contains the reply.

**Builder asserts:**
- `max(positions) < n_prompt == len(input_ids)`;
- positions are sorted and unique;
- twins have equal counts (this already holds);
- no item has a `reply` key.

**Header changes:**
- `read_span: "prompt"`;
- the reference results the README quotes for this span: O-lens prompt-span hint_reliance, I 97 /
  N 87 / +10 (CI [0.009, 0.171]).

The source sha and commit move to the gw re-freeze that marks the prompt as the headline span
(gw #727, 9a3da920a, sha `bf794d44…`); the items are unchanged.

### 2. `readplan.py` hinted_cutoff branch

- `assistant=None`: no reply.
- `extra.input_ids` is the prompt ids.
- `prompt_len` = `n_prompt`.
- The note is rewritten to describe the prompt-span positions.
- Lite stays `last_n 32`, which is 32 ≤ 38 = the minimum span.

### 3. Family code

- **`__init__.py`:**
  - the comment says the positions are the length-equalized prompt span;
  - `calls_per_arm` gets the native chunk count recomputed for the prompt span (`sum` of
    `ceil(len/16)`, written in literally);
  - `min_full_positions=16` and `full_contiguous=False` are retained.
- **`judge.py`:**
  - the module docstring says "prompt-position readouts";
  - `CHANCE_LABEL` "flags every reply" becomes "flags every twin".
- **`prompts.py`:** `DIGEST_TASK_NOTE` (a bench addition, not gw-pinned) said "a step-by-step
  answer…". That is false for prompt reads and primes the summarizer toward reliance. It becomes
  "the model was reading a dated factual question whose prompt supplies a candidate answer", and
  `PROMPT_VERSION` is bumped to `hc-2026-11-04b`. The README, the §Judges row and the floor
  instrument string follow.
- **Unchanged:** the judge prompts and their gw sha256-pinned definitions.

### 4. `adapt/judge_inputs.py`

The hinted_cutoff entry:
- drops the `reply` requirement;
- `positions` is described as "Qwen prompt token indices (gw prompt span)".

`docs/adapt_judge_inputs.md` is regenerated.

### 5. Replay gate (`scripts/hinted_cutoff_replay.py`)

- The key filter `reply` becomes `prompt`.
- `FROZEN` = {I 97, N 87, count +10, only-I 16, only-N 6}.
- `FROZEN_CI` = (0.00926, 0.17073), from gw `frozen_v1.json reference_results.olens["prompt|hint_reliance"]`.
- The render byte-equality check over all prompt chunks is retained.

### 6. Re-measure and re-freeze (local runs; only the frozen floor JSON is committed)

1. **Replay gate:** must PASS.
2. **Live run on the converted prompt-span s3d readouts:**
   - `wsbench run all=True` (summary, the macro row);
   - `wsbench judge … opts=aggregate=native`.
3. **Generic floor:**
   - `wsbench baseline kind=prompt_only_opus` ask → readouts → run → `freeze` into
     `evals/baselines/prompt_only_summary.json`, replacing the hinted_cutoff entry only;
   - check in `prompts.jsonl` that the floor reader's material has no reply text.

### 7. Docs

- **`evals/hinted_cutoff/README.md`:** the bank, readouts and floors are rewritten. The floor table
  gives:
  - the gw prompt-only predictors (YES/NO +54, normal +43, and the new one-guess predictor when
    gw #727 lands it);
  - the O-lens prompt span (+10, frozen);
  - the new bench floor;
  - the new measured summary and native numbers.

  The reply-position O-lens (+43) stays as a historical reference row, labelled "reply positions
  (not used by the family since plan 0064)".
- **`CLAUDE.md`** bullet: "reads the silent REPLY" becomes "reads the PROMPT span only (plan 0064);
  the bank ships prompt ids only".
- **`README.md`:** the §Porting sentence ("its read positions are this model's own reply tokens")
  becomes "prompt tokens".
- **`AGENTS.md`:** line 66, the Porting sentence, becomes "prompt render".
- **`capable/questions.py`:** the hinted_cutoff NO_QUESTION reason now reads "prompt render", not
  "reply".
- **`CLAUDE.md`:** the replay numbers become 97 / 87 over 712 chunks.
- **The family README:** the deviation bullet becomes "712 chunks".

### 8. Tests (`tests/test_hinted_cutoff.py`)

- `test_bank_invariants`:
  - `positions == spans["prompt"]`;
  - `max(positions) < n_prompt == len(input_ids)`;
  - `"reply" not in it` and `"reply" not in it["spans"]`;
  - equal twin counts and the same template are retained.
- A new readplan test: every hinted_cutoff ReadSpec has `assistant is None`,
  `len(extra["input_ids"]) == prompt_len`, and every position `< prompt_len`.
- The other tests are unchanged, and the examples file is regenerated if its positions are
  validated against the bank.

## Invariants retained

- Pair scoring, the class-difference headline (chance 0, in the macro unrescaled).
- The event-cluster CI (seed 20261103).
- NOT_GATED, NO_QUESTION, `summ_rare=25`.
- Model-blind judge prompts.
- The source judge definitions, byte-pinned.


## Addendum: the floor's framing (Camila, 2026-11-04)

> oh well we should not specify an open weights model

> actually try it for every family and only specify if it gets refusals, but for now just hinted
> cutoff

- **New note.** `text_inversion.NEUTRAL_NOTE` keeps the benchmark sentence and makes no claim
  about the model: no "open-weights" and no "not a Claude model".
- **hinted_cutoff only.** `prompt_only_opus.FAMILY_FRAMING = {"hinted_cutoff": "neutral"}`.
  Every other family keeps `open_model` until it is tried.
- **Rule for the rest of the bench, not applied yet:** a family moves to `neutral` unless that
  framing gets refusals.
- **Bookkeeping:**
  - `run_config.json` records `family_framing`, and the frozen floor entry carries `framing` /
    `template_sha`;
  - an answer asked under another framing is not a cache hit.
- **The floor is re-asked and re-frozen under the neutral note.** The refusal count is reported in
  the entry (`n_refused`).
