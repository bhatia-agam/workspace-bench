---
name: adapt-bank
description: Adapt WorkspaceBench to a new subject model so every question is one that model actually computes, and say what an existing adapted set can and cannot be judged on after the bench changed (refresh is blocked until plan 0060). Gate the registered banks on the subject, rebuild what is model-specific, refill each family with new items of the same kind at a difficulty the subject passes, and freeze a per-model bank under adapted/<model>/. Use when someone wants WorkspaceBench for a model other than Qwen3.6-27B (from Qwen3.5-0.8B up to 1T MoE subjects like Kimi-K2: Qwen3.5, Qwen3, OLMo, Gemma, GLM, DeepSeek, any HF chat model), asks for "adaptive", "per-model", "re-gated", "ported" or "updated/refreshed" per-model banks, asks why an adapted set fails to judge, or asks why a lens scores low on a small model.
---

# Adapt WorkspaceBench to a subject model

Every bank was gated on Qwen3.6-27B. A lens that says nothing about an intermediate the model never
computed is not wrong, so on any other model the banks have to be re-gated, and items the subject
fails replaced with items it passes. **The goal is a bank where every item is (a) the same kind of
latent the family tests, (b) something this subject computes (greedy right, ≥8/10 sampled), and (c)
still valid for the family's judge, read site and null.** Easier is fine; a different kind of latent
is not.

What earlier attempts got wrong (the `.pm` / `.pmeq` banks in global-workspace `1f36ca88`): they
drew new candidates at the 27B's difficulty and filtered them, so yields on Qwen3.5-4B were 0–4% on
multihop_mt (since removed), multilingual_mt, chain and brew (since retired). **Change the
difficulty of what is asked, never the construction rules, the gate, or the scorer.**

## State of the adapted sets (2026-11-02): every set predates the bank v2+ round

All 11 `adapted/<m>/` sets were frozen 2026-10-18..24 (touch-ups through 10-30: MCDM re-carry,
typo_mt arithmetic drop, multihop_mt / hallucination / brew removal) from the **v1** banks. Since
then most families moved to new registered banks (`EvalSpec.bank`: `items_v2`..`items_v5`) with
blind-MC judges, new gate legs and every-position reads (plans 0023-0058). What happens today if you
judge an adapted set as it is (verified on qwen3.5-9b, gemma-4-31b-it, kimi-k2, glm-5.3-flash):

| effect on an adapted v1 bank | families |
|---|---|
| **judge exits** (no `mc` / `mc.candidates`: exit 2; poetry: uncaught ValueError) | association, basic_readout, multihop, chain_intermediates (default `judge=mc`), poetry |
| runs, on a **retired instrument** or without the v2+ fields | moral_rationale (ec-v3.1, no option lists), multilingual (`v1_scorer="bank"`), multilingual_multihop (v1 regex), conjunctive_association (no `twin_of` / `inverted_label`: no inverted-twin diagnostic) |
| runs, **headline None** (no twins / controls, so out of the macro) | buggy_code (no `twin`), agentic_misalignment (no clean twins), jailbreak_recognition (no v2 controls); a set rebuilt with plan 0060 A2 has all three |
| runs, but on the old questions | basic_readout_mt (v4 shares 0/99 prompts with v1), multilingual_mt, multilingual_typo, typo_mt, multi_concept_directed_modulation (glm / kimi: still the 27-item set) |
| bank unchanged; re-judge / re-read only (relgate-v4 and role_bound's action gate are JUDGE-side quote gates, not subject gate legs: no regate) | relational_multihop, role_bound_association, user_modeling, arithmetic_intermediates, directed_modulation |
| absent from every set | wrong_intermediate, multihop_mt_v2, knowledge_cutoff, model_specific_directed_modulation, nyt_connections, introspection (§Families the adapt machinery does not cover) |

Also stale on every set: `report.json` `code.adapt_sha256` (`5c9d…` / `ebba…` / `0ffc…`) no longer
matches the adapt package, and `floors/floors.json` predates summary mode, the Opus prompt-only
protocol and every judge change since 10-21. Readouts produced against the pre-plan-0032 read plans
do not match today's plans. **A correct refresh needs plan 0060 Phase A first: §Refresh lists why, and the target procedure.**
The per-family detail behind this table is in `references/families.md` (the "Bank now" line of
each entry).

## Layout (everything this skill writes)

```
adapted/<model>/report.json            per-family: target, n_original, n_original_pass, n_items,
                                       n_new, status, change (what the difficulty knobs did), note
adapted/<model>/<family>.json          frozen adapted bank: the header + item shape of the
                                       REGISTERED bank (`registry.frozen_bank_path`, e.g.
                                       evals/association/items_v3.json, not items.json); each
                                       item carries `adapt` {origin, tier, knobs, gate, parent?, note?}
adapted/<model>/gate/<family>.jsonl    every gated candidate, failures included (append-only;
                                       last record per id wins): {id, origin, item, gate, selected}
adapted/<model>/cand/<family>.jsonl    candidates not yet gated (generator or author output)
```

Frozen originals under `evals/` are never edited. Adapted banks are separate files. Judge them
with `WSB_BANK_ROOT=adapted/<model>` (see `references/porting.md` §Judging an adapted bank).
**A header and items from different bank versions break the judges** (multitoken families route
on the header's version; conjunctive and moral check `bank_version` PER ITEM and refuse a mix, and
moral v3 and conjunctive v4 are bare lists with no header): never hand-copy a new header over old items or the
reverse, and every kept item, new dilemmas included, carries the registered `bank_version`.

`gate/`, `cand/`, `floors/{readouts,results}/` and the grade cache are git-ignored. For the 11
existing sets they live only on Agam's RunPod box (`/workspace/agam/workspace-bench/adapted/`,
~27 GB); once plan 0060 lands, a refresh on any other box starts by reseeding from the frozen set
(§Refresh, target step 0).

## What can be built correctly today (until plan 0060 lands)

**New subjects only** (no `adapted/<m>/gate/` yet). On an existing set, `profile` skips ids already
in its gate log and `freeze` puts the registered header over the stored v1 payloads: that is
§Refresh, which is blocked.

Every runbook step below is limited by this table. "originals only" = profile the registered bank
and freeze its passing items, with NO refill (new items would lack judge-side options or pools
keyed to the registered items, or the family has no Brief / generator). Freeze marks a short family
with no refill attempt `untried` (`run.py`; it resets `partial`), so record the reason with `note`
AFTER every freeze, re-freezes included.

| status today | families | how |
|---|---|---|
| full build | typo_mt, association (Brief writes `mc`, but the options are NOT leakage-screened and new items lack v3's `mc.distractor_aliases` / `topic`: say so in the note) | profile + `fill` |
| full build (plan 0060 A2 rebuilds) | basic_readout v5 (Brief tiers `t1` implicit / `entity` / `processing`; profile → `fill` → `$A mc $M families=basic_readout` (entity / processing candidates: `mc_leakage_r4.py --bank`) → gate → `$A mc $M families=basic_readout stage=subject` after EVERY gate (implicit golds = the subject's answer, a distractor never names it; marks `subject_fields_for`) → freeze (balances `mc.gold_position` per subfamily over the shipped set)), basic_readout_mt v4 (gate = the v4 question in chat, no system turn / stem, graded by `name_forms`, T 0.7 / top_p 0.8 / top_k 20 (a Modal subject needs its app redeployed for `top_k`); Brief `t1` / `t2`; `$A mc $M families=basic_readout_mt` before gate (r4 → r4b → `build_r4b_mc_banks.py --bank`); freeze writes the set's `basic_readout_mt/{exonyms,hidden_rivals}.json` overlays, which need the judge overlays of PR #243) | as described |
| full build (generated) | relational_multihop, arithmetic_intermediates | profile + `auto` |
| originals only | directed_modulation (profile is its compliance gate; no Brief), multihop, chain_intermediates (gate = v2's rule: strict 10/10 + greedy + no leak on the seed-last render; `first` is a `note:first` annotation leg; new generated items get per-slot `mc` from `options.build_mc` over the shipped set at freeze; originals keep the registered options), conjunctive_association, role_bound_association (oa-v3 `distractors_v3.json` is keyed by registered pair ids), user_modeling (option pools), buggy_code (plan 0060 A2: `select` keeps each buggy / clean pair `{id, twin}` atomic, registered `twin` or the authored `-au-` / `-au-clean-` ids; a failed clean twin drops its buggy partner; authored pairs get `twin` at authoring and at freeze), multilingual / multilingual_mt / multilingual_typo / multilingual_multihop **only for a subject whose native languages are exactly `en` and `zh`**: freeze copies Qwen's `contract.native_langs` | profile + freeze |
| carry | jailbreak_recognition (`carry` re-screens every v2 control on the subject with the bank's J5 grader, `scripts/build_jailbreak_v2.py` `grade_gate`: 20 no-think draws + greedy, since the subject never thinks; a failing control is dropped with its pairing in `adapt.dropped_controls` and the report; `screen=false` skips it, and then the net headline is not valid), multi_concept_directed_modulation | `carry families=jailbreak_recognition,multi_concept_directed_modulation` (never another family: carry treats any non-jailbreak name as MCDM) |
| regenerated | agentic_misalignment (plan 0060 D5: every clean twin is rolled out with the same protocol and kept only if the subject never misbehaves on it, beside its kept partner; pairs are atomic; at >= `MACRO_MIN_PAIRS` pairs the macro exclusion is lifted; `twins=false` gives plan 0031's twin-less scope), jlens_concept_pr (needs the subject's J-lens) | `$A agentic`; `scripts/adapt_jlens*.py` |
| do not build (`note status=blocked`, reason "plan 0060") | poetry (v5 free leg missing; profile would put the subject's gold over Qwen's `mc.candidates`), moral_rationale (`$A moral` / `profile` keep Qwen's `options`; rekey is Qwen-only), the multilingual families for any subject whose native languages are not exactly `en` and `zh` | — |
| not in the adapt machinery | §Families the adapt machinery does not cover | — |

## Runbook (one subject, in order)

Every step is resumable; run each in its own tmux session with a log under `logs/` (on Agam's box:
`/workspace/agam/logs/<step>-<m>.log`). `A=scripts/adapt_box.sh` on Agam's box, else
`A="python -m wsbench.adapt"` with the environment of §On another box; `M=model=<key>` (the key
from `subjects.py`).

| step | command | notes |
|---|---|---|
| 0 set up | add a `Subject` (pinned revision, `n_layers`, tokenizer family, `chat_template`, `gpu_memory_utilization` / `enforce_eager` for a tight fit), download weights, `$A profile $M families=typo_mt limit=5 llm=claude-opus-5-5` (step 1 skips these rows, so grade them the same way) | 9B on the 4090: 0.93 + eager (vision profiling is skipped: text only) |
| 1 profile | `$A profile $M llm=claude-opus-5-5 families=<the full-build, generated and originals-only families of §What can be built>` | gates every item of the REGISTERED bank; parallel Opus grading |
| 2 generated | `$A auto $M family=arithmetic_intermediates`, then `family=relational_multihop`, then `family=chain_intermediates` (tiers keep every intermediate in 10..99) | deterministic ladders |
| 3 authored | `$A fill $M families=typo_mt,association` (only these two: other families with a Brief would build items missing their judge-side keyed fields; `fill` raises KeyError on a family with no Brief) | waves sized by yield, auto-steered by the last wave's misses, tier step-down, ooc stop |
| 4 model-specific | `$A agentic $M` · `$A carry $M families=jailbreak_recognition,multi_concept_directed_modulation` · jlens: `scripts/adapt_jlens.py` / `adapt_jlens_modal.py` (the subject's neuronpedia J-lens, or one fitted with `scripts/fit_jlens_modal.py`; else `note status=blocked`). NOT `$A moral` until plan 0060 | directed_modulation is compliance-gated by step 1 |
| 5 freeze | `$A freeze $M families=<the families built>`, then `note` per family (after EVERY freeze) | writes `n_layers` into report.json: `wsbench plan` then emits subject layers. wrong_intermediate, multihop_mt_v2 and nyt_connections (plan 0060 Phase E: `$A wrong_intermediate`, `$A multihop_mt_v2`, `$A nyt_connections`) are not in the default family list: they ship ONLY when named, `families=wrong_intermediate,multihop_mt_v2,nyt_connections` |
| 6 verify | `WSB_BANK_ROOT=adapted/<m> wsbench plan out=…` and each family's judge with `dry_run=True` | any non-zero exit (exit 2, or a traceback) means a required field was not built |
| 7 floors | §4 Floors | both protocols, stamped |
| 8 audit | an INDEPENDENT agent writes `adapted/<m>/AUDIT.md` (correctness, leakage, difficulty, judge agreement); apply its drops, re-freeze | never self-certify |
| 9 publish | update `adapted/README.md` (path, status, audit, bank versions) and tell olens-train | consumers read via `WSB_BANK_ROOT=adapted/<m> wsbench plan` |

`python -m wsbench.adapt` subcommands (`src/wsbench/adapt/__main__.py`; unknown keys are errors):
`profile` (families limit regate llm draws temperature), `generate` (family tier n seed), `author`
(family tier n steer wave), `gate` (families llm draws temperature regate), `regrade` (families llm
workers), `auto` (family), `fill` (families llm waves), `freeze` (families), `note` (family status
text exclude_from_macro), `drop` (family ids reason), `patch` (family id set note), `status`, `native_langs` (stage langs evidence thinking: write or
show `adapted/<m>/native_langs.json`, which `freeze` needs for the six multilingual / mt families;
`stage=measure` is not implemented yet, plan 0060 A1.10),
`moral` (stage step out limit), `agentic` (stage), `carry` (families), `floors` (stage judge).
There is no `hal` subcommand: the hallucination family was removed (plan 0040; HallucinationBench
is reported as an index, `evals/hallucinationbench/`).

## Procedure

Keep a ◼/◻ todo tree in replies, one line per family. Do one subject at a time and finish it before
starting the next.

### 0. Set up the subject
- Add it to `src/wsbench/adapt/subjects.py`: HF id, pinned revision, layer count, and the tokenizer
  family. Qwen3.5 shares the Qwen3.6 tokenizer and template, so token indices carry over; Gemma's
  don't. A subject whose upstream template always opens a reasoning block (GLM-5.3-Flash) or ships
  no Jinja at all (DeepSeek-V4: only `encoding_dsv4.py`) needs a pinned no-think `chat_template`
  file checked against the vendor's own encoder on a few renders.
- Run the gate where the weights fit. Up to ~9B: the RunPod 4090 with vLLM.
  `scripts/adapt_box.sh <cmd> …` wraps `python -m wsbench.adapt` with:
  - the venv `$ADAPT_ENV` (default `/workspace/agam/envs/adapt`; vLLM needs its `ninja` on PATH);
  - the persistent HF cache (`HF_HOME`, default `/workspace/.persist/huggingface`);
  - offline weights (`HF_HUB_OFFLINE`, default 1).

  The first vLLM start compiles, which takes minutes; later starts reuse the cache. Larger subjects
  run on Modal: deploy `scripts/adapt_modal.py` once (app `adapt-subject-llm`, vLLM, CUDA devel
  image) and set `backend="modal"` on the Subject (or `ADAPT_BACKEND=modal`); every step (gate,
  moral, agentic, floors) then generates there through `RemoteRunner` while rendering and grading
  stay local. The GPU is the decorator's `gpu="H200"` (`adapt_modal.py:24`): edit it to change it
  (B200 / B300 for new deploys; B200 when the image's Triton lacks sm_103a). Give Modal runs their
  own lock (`ADAPT_GPU_LOCK=…/gpu-modal-<m>.lock`) so they don't queue behind the 4090.
- Thinking is always off. Use the subject's own chat template. Every runner start runs
  `template.check` (markers derivable, no reasoning block left open, system turn accepted) and
  refuses to gate otherwise.
- Smoke test first: `$A profile model=<m> families=typo_mt limit=5 llm=claude-opus-5-5`. Read the rendered question and
  the answers in the viewer before running anything bigger.

### 1. Profile: gate the registered banks on the subject
`$A profile model=<m> families=<the full-build, generated and originals-only families of §What can be built>` asks each item's own gate question(s) and writes `gate/<family>.jsonl` with
origin `original`. It reads `registry.frozen_bank_path` (the registered default bank), so it gates
today's items; ids already in the gate log are SKIPPED unless `regate=true`.
- Use greedy plus 10 samples at T=0.7 (chain: T=0.8, top_p 0.95, 10/10; every other knob:
  references/families.md, top).
- multihop and the bridge families also gate every bridge question: the bridge is the scored latent.
- Own-answer families (poetry, basic_readout implicit) stamp the subject's own word as the gold.
- Then `python -m wsbench.viewer.build` and look at the failures per family. Check the answers
  themselves before you choose a knob: "right idea, wrong format", "wrong language" and "refused"
  each need a different fix from "doesn't know".
- A grading miss (a valid alias or translation) is a grader bug. Fix the forms or use `llm=opus`.
  Never fix it by lowering the bar.

### 2. Rebuild what is model-specific (no difficulty change)
Follow `references/porting.md`:
- poetry: the subject's own rhyme. Bank v5 needs a free line-two leg the adapt gate does not have
  yet (plan 0060): until then poetry cannot be ported to v5 (report it, don't freeze v1 items
  under the v5 header).
- basic_readout implicit: the subject's own favourite.
- moral_rationale: NOT today (§What can be built): do not run `$A moral` — on a profiled set it
  rewrites the reasons and keeps Qwen's `options`. Target (plan 0060): the subject's side, reasons
  sampled from its own draws, option lists rebuilt for those reasons.
- directed_modulation: the compliance screen.
- agentic_misalignment: rollouts, the clean twins included (plan 0060 D5; `$A agentic`).
- jailbreak_recognition: positions and template (`carry`); the v2 controls are re-screened on the
  subject by `carry` (plan 0060 A2).
- multi_concept_directed_modulation: the prefill render (bank v2, 116 items).
- jlens_concept_pr: re-capture.
- Layer remap: by depth fraction, for every family (`wsbench plan` does it from `n_layers`).

### 3. Refill each family down its difficulty ladder
Until plan 0060 lands, only the families §What can be built marks full build (typo_mt, association,
and via `auto` relational_multihop / arithmetic_intermediates) are refilled; the rest of this
section is the general procedure.

For each family below its target count (the registered bank's size):
1. Read the family's entry in `references/families.md`: its latent, invariants, ordered tiers
   (tier 0 = the original difficulty, each later tier easier on the knob that mattered most), and
   the fields the registered bank requires.
2. Pick the tier from the profile. Start at the tier whose description matches the subject's
   failure pattern; don't step down blindly.
3. Generate candidates:
   - Deterministic families (`wsbench/adapt/generate.py`: chain, relational, arithmetic):
     `$A generate model=<m> family=<f> tier=<t> n=<n>`. Arithmetic keeps the original per-variant
     counts as quotas, and its t0 ranges are read off the bank itself.
   - Authored families (`wsbench/adapt/author.py` `BRIEFS`: association, multihop, multilingual,
     typo, poetry, the five mt families typo_mt / multilingual_mt / multilingual_typo /
     multilingual_multihop / basic_readout_mt, user_modeling, basic_readout implicit, role_bound
     (pair objects), buggy_code (executed twins)). **No brief exists for conjunctive_association or
     moral_rationale dilemmas**: those refill only from the registered bank. `$A author model=<m>
     family=<f> tier=<t> n=30 steer="<what it got wrong>"`. Opus writes against the brief, with
     items this subject passed as few-shots and an ALREADY-USED list. The procedure is in
     `references/authoring.md`.
4. `$A gate model=<m> families=<f> llm=claude-opus-5-5` lints every candidate (leak, format, the
   family's invariants) and then gates it. Failed lint is dropped before any GPU time.
5. Read the misses in the viewer, then adjust:
   - Steer the next wave by the failure pattern.
   - Cap any single template, topic or relation at 20% of the family.
   - Pilot ~30 candidates at a new tier before generating hundreds.
6. The blind-MC `mc` blocks the briefs and generators don't write (association: lint requires it, so
   an association candidate without `mc` is rejected before the GPU; multihop; chain per-slot;
   poetry `mc.candidates`) must exist in the candidate payload. **No MC builder takes adapted items
   yet.** `scripts/build_multihop_mc.py`, `association_distractors.py`, `moral_distractors.py`,
   `mc_leakage_r4.py` and `role_bound_distractors_v3.py` read and WRITE the frozen `evals/` files
   (hard-coded paths): never run them for an adapted set, it rewrites the bank of record.
   `r4_mc_distractors.py` writes only to `--out` but reads frozen banks only. Only
   `scripts/poetry/build_mc.py` takes `--draft` / `--out` over an arbitrary bank. A field built by hand into
   `adapted/<m>/<family>.json` is lost at the next `freeze` (it rebuilds from gate-log payloads +
   `patches`). For an id ALREADY in the gate log the only route is `adapt patch` (applied at freeze;
   never linted or gated): a rewritten `cand/` row is ignored (`store.pending` / `add_candidates`
   skip gated ids) and `gate regate=true` re-gates the gate-log payload, not the cand row. A new
   item can carry the field in its `cand/` row before its first `gate`. An adapted-item `adapt mc`
   step is open (plan 0060).
7. Stop rules (report, never pad):
   - **full**: target reached.
   - **partial**: the easiest tier is exhausted with yield ≥ 3%, or the budget is hit.
   - **ooc** (out of capability): yield < 3% on ≥ 60 candidates at the easiest tier that still
     carries the latent, AND the bank is under half its target. Above half, the same stop is
     `partial` with `refill` noting why it stopped (a 48/49 bank is usable, not ooc).
   - **blocked**: needs something absent (no J-lens for the subject, no misaligned rollouts).

`$A auto model=<m> family=<f>` runs steps 3–4 down the ladder for the deterministic families;
`$A fill model=<m> families=<f,...>` does the same for authored families (waves steered by
`run.miss_steer`: lint reasons, what the subject wrote instead, and what passed).

### 4. Freeze, verify, floors, audit
`$A freeze model=<m> families=<the families built>` (never bare) writes `<family>.json` and
`report.json`. It takes the header of the registered bank; every ORIGINAL is the registered item
itself plus the subject-side overlays (own-answer gold, `gate_variant`, `families.SUBJECT_FIELDS`,
token restamps), and original ids the registered bank lacks are never selected; new items are
the gate-log payloads. It refuses (writing nothing) a family whose items lack
`families.REQUIRED_ITEM_FIELDS`, whose originals lack their `SUBJECT_FIELDS`, or, for the six
multilingual / mt families, a subject without `native_langs.json` (plan 0060 A1.1 / A1.10). It
records `bank` / `bank_version` per family and writes `status: absent`, `exclude_from_macro`
and a `note` (an existing note is kept) for every registered family the set lacks (A1.6).
Then:
- Eyeball 10 random new items per family in the viewer: is the latent the same kind as the
  originals, is the answer unambiguous, and did nothing leak?
- `pytest tests/test_adapt.py`, then `WSB_BANK_ROOT=adapted/<m> wsbench plan out=<dir>` and every
  adapted bank through its family's judge with `dry_run=True`. A non-zero exit = a required field is
  missing.
- **Floors (two protocols; record which, and keep both records — `adapt floors stage=judge`
  rewrites `floors/floors.json` with only its own record, so merge after it runs).** Every floor
  command below that FREEZES writes the bank of record by default: `wsbench freeze` writes
  `evals/baselines/<kind>.json` unless `dst=` is given; always pass `dst=adapted/<m>/floors/…`.
  - *Bench protocol* (the one the 27B floors and `wsbench report` use): the Opus 5.5 prompt-only
    reader in summary mode, `po-opus-v1+sonnet55-fallback`:
    `WSB_BANK_ROOT=adapted/<m> wsbench baseline kind=prompt_only_opus stage=build|ask|readouts
    out=<dir>`, then `stage=fallback_ask|fallback_readouts src=<dir> out=<fb>`, judged with
    `wsbench run all=True readouts_root=<dir>/readouts out=<results dir> allow_missing=True`. **`stage=build`
    uses the subject's tokenizer** under `WSB_BANK_ROOT` (`report.json` `model`, via
    `adapt.author.tokenizer`; plan 0060 A1.9).
  - *Stock-subject protocol* (secondary): `$A floors model=<m>` (the stock subject reads each
    prompt; native aggregate, one layer; each family's own judge on `claude-opus-5-5`). Not
    comparable with the bench protocol; label it.
  - *Options-only*: `wsbench baseline kind=lucky_guessing` reads every family's options through
    `bank_path`, so it honours `WSB_BANK_ROOT` (plan 0060 A1.9; knowledge_cutoff and wrong_intermediate,
    absent from the adapted sets, still read the registered bank).
  - Under `WSB_BANK_ROOT`, `wsbench freeze` defaults `dst=` to `<root>/floors/<file>`, refuses a
    `dst` under `evals/baselines/`, and merges the result into `floors/floors.json`, which keeps
    one record per protocol (`protocol`, `prompt_version`, `judge`, `families`); `adapt floors
    stage=judge` writes its own `stock-subject-v1` record the same way (plan 0060 A1.9). The topic guesser reads `evals/baselines/topics/<family>.json`, keyed
    by Qwen item ids, so adapted items have no topics, and `scripts/baselines/make_topics.py` writes
    `evals/`: the adapted topic floor is an open item (plan 0060).
  - `wsbench report` under `WSB_BANK_ROOT` still draws the frozen 27B floors (`cli.py`); read the
    adapted floors from `floors/floors.json`. Easier items can raise a floor; flag a family whose
    floor saturates in `report.json`.
- Write `report.json.note` per family: what changed and why, in one sentence each.
- **A family gained or changed a gate leg** (e.g. multihop originals' bridge; poetry's free
  line-two leg once plan 0060 lands): `profile families=<f> regate=true` (originals) AND `gate
  families=<f> regate=true` (passing new items), then refill and re-freeze. Old records otherwise
  keep passing without the leg. When a leg was REMOVED or made an annotation (chain v2's `first`),
  use `gate regate=all`: it re-asks the failed new items too (every row is re-linted first, so a v1
  chain with an intermediate below 10 is lint-retired).
- `report.json` → `code` stamps the git HEAD and an adapt-package hash on every write. Check it:
  `python -c "from wsbench.adapt import store; print(store.code_stamp())"` vs
  `report.json` `code.adapt_sha256`. A bank frozen under an older stamp than the gate logic you
  changed needs a regate.

## Refresh an existing set to a newer bench

**Status (2026-11-02): blocked on plan 0060 Phase A. Do not refresh a set with today's code.**
Until that lands, report an adapted set's families as they are (SKILL §State) and never quote a
judged number from a family §State marks broken, retired or headline-None. Every ad-hoc route was
checked and each one ends in a new header over old items, Qwen's options under the subject's gold,
or a rewritten bank of record.

### Why there is no safe ad-hoc refresh (verified traps in today's code)
- `profile` skips ids already in the gate log (they keep their v1 payloads) unless `regate=true`;
  `select` never filters to the ids in the current bank, so ids a bank version retired come back
  (typo_mt's 15 arithmetic items, association's 7).
- For an already-gated id, a rewritten `cand/` row is ignored (`store.pending` / `add_candidates`
  skip gated ids) and `gate regate=true` re-lints and re-gates the GATE-LOG payload. `adapt patch`
  is applied only at freeze and never reaches that payload.
- `gate` lints first and association lint requires `mc`: regating or importing a v1 association
  item without `mc` appends a rejected record, and last-record-wins makes it permanent.
- `freeze` deep-copies the registered header every time, so header fields cannot be set per
  subject: multilingual / mt headers keep Qwen's `contract.native_langs` (`['en','zh']`), which the
  judges read (`multitoken/family.py`, `mcrx.py`), and the dry run passes.
- A bare `freeze` re-freezes every family with gate rows, writing new headers over v1 rows of every
  family not refreshed.
- `profile` on poetry v5 or moral v3 restamps the subject's gold but keeps Qwen's `mc.candidates` /
  `options`: the judge runs, against the wrong options.
- Adapted-only items (origin `authored` / `generated`; 158 (kimi) to 1,129 (qwen3.5-4b) per set) are v1-shaped and
  post-processed (`_post_freeze` remapped arithmetic `cell.layer` non-invertibly; non-Qwen sets
  token-restamped). Re-gating them and re-freezing remaps layers twice; leaving them in puts v1 items
  under a v2+ header that still runs where no field is hard-required.
- The repo's MC builders (`build_multihop_mc.py`, `association_distractors.py`,
  `moral_distractors.py`, `mc_leakage_r4.py`, `role_bound_distractors_v3.py`) and `wsbench freeze` (floors; `evals/baselines/` unless
  `dst=`) write the bank of record. Never run them for an adapted set.
- `drop` / `patch` records are unversioned: v1 audit decisions (gemma's 161 moral patches,
  olmo-3-7b's moral drops) would be applied to v3 items.
- Registered families a set lacks are SKIPPED (printed) under `WSB_BANK_ROOT` with `all=True`
  (`cli.py` `RunFamilies`, `readplan.families()`), and exit 2 only when named explicitly: 5 for 9
  sets (introspection, knowledge_cutoff, msdm, multihop_mt_v2, wrong_intermediate; nyt_connections too), 7 for glm / kimi
  (+ jlens, agentic). They appear in no report row, so a macro silently spans fewer families.

### Target procedure (once plan 0060 Phase A lands; commands named there)
0. Gate log: on Agam's box use it; elsewhere `adapt seed` rebuilds gate payloads from the frozen
   set (post-freeze fields stripped; deterministic families regenerated instead).
1. Diff: `adapt status` (bank version per family, stamp match, stale audit records). Delete only
   `REMOVED_FAMILIES` files; keep retired / superseded ones, unrefilled.
2. Per family, the mode plan 0060 §1 assigns: **upgrade** (judge-side fields only, e.g. `mc`,
   pools, twins: `adapt upgrade` writes a new gate record, prior gate result copied, nothing
   re-asked) or **rebuild** (the bank's questions or gate changed: basic_readout v5, basic_readout_mt
   v4, poetry v5, moral re-key). multilingual v3 is an upgrade (prompts unchanged), after the
   subject's `native_langs` is measured: originals re-profiled from the registered bank, new
   items authored against v2-shaped briefs, v1 adapted-only items retired.
3. Re-gate only where the SUBJECT gate changed; judge-side changes (relgate-v4, role_bound's action
   gate, um-v3.4) need no regate.
4. Refill, `freeze families=<refreshed>` (provenance-stamped rows only), verify every present family
   `dry_run=True`, floors under both protocols into `adapted/<m>/floors/`, independent re-audit.
5. Record `bank_version` per family in `report.json`, update `adapted/README.md`, re-produce readouts.

## Families the adapt machinery does not cover

`families.get` raises "unknown family" for every row but typo (in the adapt `FAMILIES`, just not
refilled), so `profile` / `gate` cannot gate them yet. Do not
copy the 27B bank into `adapted/<m>/` for them: a missing family is reported, never back-filled.

| family | why not | what porting needs |
|---|---|---|
| multihop_mt_v2 | its shortcut gate (no shortcut probe reaches the answer) is specific to the gated model | the answer + bridge legs fit `families.py` (`capable/questions.py` already asks them); add a must-NOT-reach leg type for `shortcut_probes` (global-workspace `multihop_v2/gate_modal.py`) |
| wrong_intermediate | the item is a specific Qwen error (it answers via the wrong intermediate) | re-elicit the subject's own wrong-intermediate errors; no adapt code |
| knowledge_cutoff | a model-specific error gate (G0 / G1) | `$A kcutoff $M [cutoff=YYYY-MM]` (plan 0060 Phase E): G0 re-run on the subject, G1 dropped, options / units rebuilt; then `freeze families=knowledge_cutoff`. nocot items not built (`references/families.md`) |
| model_specific_directed_modulation | model-specific by design (G0 defaults + G1 text gate) | `$A msdm $M` (plan 0060 Phase E): the subject's own defaults (G0 + compliance), G1 dropped, options / units rebuilt; then `freeze families=model_specific_directed_modulation` |
| nyt_connections | the targets are the model's own groupings and connection labels (plan 0062) | `$A nyt_connections $M [stage=solve/stability/options/build/all] [limit=] [llm=] [herrings=<pilot alt_b2.json>]` (plan 0060 Phase E): the subject solves each registered puzzle (greedy + 16 @ T 0.7, top-p 0.95) and names its groups; the family's >= 12/16 stability rule re-run; options rebuilt around its labels (NYT gold, shared Opus herrings, foil, Opus EQUIV filter); frontier gate dropped; then `freeze families=nyt_connections`. Work files hold NYT text: they live in `$WSB_CACHE/nyt/adapt/`, never `adapted/`. `regate=true` refuses `limit=`. `scripts/nyt_connections_bar.py` refuses an adapted headline (the frozen floor is Qwen's) |
| introspection | injected concept vectors are the subject's own activations | rebuild vectors (`scripts/introspection_build_v2.py`, `introspection_export_vectors.py`) |
| unverbalized_hint | retired (plan 0058); Qwen token positions | none |
| typo | superseded by typo_mt (out of `all`) | stop refilling it; keep the frozen file only for old results |

Removed and never to be adapted: medical_diagnosis{,_alt} (plan 0058), hallucination (plan 0040),
multihop_mt (plan 0041), brew_intermediates (plans 0029 / 0033).

## On another box (not Agam's RunPod box)

Everything under `/workspace/agam/`, the 4090, `/dev/shm/compute.env`, the `runpod` ControlMaster,
gw-olens' `adapt_mp_subject_modal.py` / `kimi_wsbench_modal.py` / `subject_*_modal.py`, the
`/workspace/agam/hf_tok/<m>` tokenizer dirs (glm-5.3-flash, kimi-k2), and `atlas/normal_gated.py`
(hard-codes those paths) exist only there. Elsewhere:
- `ADAPT_ENV`, `HF_HOME`, `ADAPT_GPU_LOCK` and `MODAL_ENVIRONMENT` (default `agam`) to your own
  values; `HF_HUB_OFFLINE=0` or pre-download the pinned revision; deploy `scripts/adapt_modal.py`
  into your own Modal environment and set `ADAPT_BACKEND=modal`.
- Re-stage a subject's `tokenizer_dir` / `chat_template` from the pinned HF revision into
  `src/wsbench/adapt/data/templates/` and point `subjects.py` at it (done for glm-5.3, kimi-k2).
- **Claude auth.** The default reads the keyless OAuth token from Modal Dict `anthropic-oauth` in
  `MODAL_ENVIRONMENT` (only Agam's env has it). Set `WSB_ANTHROPIC_AUTH=sdk` to use the
  Anthropic SDK's own credentials (`ANTHROPIC_PROFILE` / federation). `adapt_box.sh` runs `unset
  ANTHROPIC_API_KEY`, so an inline key does not survive it: call `python -m wsbench.adapt`
  directly. `adapt floors stage=judge` honours it too (plan 0060 A1.9).
- **Per-subject Modal apps** (`scripts/adapt_modal.py`, plan 0060 A3). Each `backend="modal"`
  Subject names its app (`modal_app`) and how it is served: `modal_gpu` (fallbacks in order),
  `modal_tp`, `modal_engines` (TP engines per container, one per GPU set: DeepSeek-V4 = one
  B300:8 with 8 TP=1 engines, "always 8xB300"), `modal_replicas` (containers the chunks fan out
  over), `modal_image` (recipe `default` | `glm53` | `dsv4`), `modal_volume` + `modal_weights`,
  `modal_engine` (extra `vllm.LLM` kwargs). Subjects with the default fields share
  `adapt-subject-llm` (one H200). `modal_built=False` (glm-5.3-flash: Agam's text-only app, not
  rebuilt per D1) is refused by both the deploy script and `RemoteRunner`.
  Prerequisites: the weights volume exists in the env (`glm53-weights` holding
  `hf/nvidia__GLM-5.3-NVFP4`; `v4-flash`); kimi-k2 has none, so its first load writes ~1 TB into
  `adapt-hf-cache`. The glm53 image pulls the vLLM fork from a public HF repo (no secret).
  Deploy once per app, from the repo root, with the Modal client venv:

  ```bash
  MODAL=/root/.cache/cfinf-modal-venv/bin/modal
  export MODAL_PROFILE=safety-sahan-2 MODAL_ENVIRONMENT=camila-blank
  $MODAL deploy scripts/adapt_modal.py                         # adapt-subject-llm (shared)
  ADAPT_SUBJECT=glm-5.3 $MODAL deploy scripts/adapt_modal.py   # adapt-glm-5.3: B300:8|B200:8, TP8
  ADAPT_SUBJECT=kimi-k2 $MODAL deploy scripts/adapt_modal.py   # adapt-kimi-k2: B300:8, TP8
  ```

  Then run `python -m wsbench.adapt … model=<key>` with the same `MODAL_ENVIRONMENT`;
  `RemoteRunner` finds the app by name. It sends TOKEN IDS (the local render, tokenized without
  added specials), so `<bos>` / `[gMASK]<sop>` is never doubled: an app deployed before A3 took
  text and must be redeployed. The first call boots the engine (GLM-5.3: localize ~440 GB to
  NVMe + load + JIT, ~15-20 min; `scaledown_window` keeps it warm 10 min between calls), so
  batch every candidate into ONE generation run per stage. Check Blackwell stock first.
- **Tokenizers off the box.** `glm-5.3` loads its tokenizer from the hub at the pinned revision
  plus the in-repo `data/templates/glm53_nvfp4_nothink.jinja`; `kimi-k2` loads the hub's
  remote-code tokenizer (`trust_remote_code`, needs `tiktoken`, in the `gpu` extra) with its
  official template as-is: every Kimi render opens with the template's default system turn ("You
  are Kimi, an AI assistant created by Moonshot AI.") unless the ask has its own system message
  (sets are built fresh, so Agam's earlier renders need not match). `glm-5.3-flash` still points
  at Agam's `/workspace/agam/hf_tok` (not refreshed, plan 0060 D1).
- The box `Runner` hands vLLM rendered text; `RemoteRunner` sends token ids. For a tokenizer that
  auto-adds a BOS the render already carries, the two backends can differ by that token.

## Tailoring to smaller and bigger subjects

**Read the failing answers before touching difficulty.** A format failure needs a format fix, not
an easier tier:
- **Format variants** (change only the ask/render, never the latent, gold rule or scorer). Pilot each
  on ~30 failed originals and keep the best by yield. Record `gate_variant` / `eval_render` in the item,
  and add the read rule to `references/porting.md` so the producer reads that render.
  - `chat_prefill`: the assistant turn is prefilled with a stem. Qwen3.5-0.8B poetry went 1 → 100
    (line 1 + line-2 stem, read at `last_newline`).
  - `system_one_word`: a strict one-word system turn. Gemma-4-31B moral went 37 → 161; the reasons
    were re-elicited the same way.
  - `ask_roles` + re-grading. OLMo-3-7B role_bound went 0 → 100; it had answered with names
    instead of roles.
- **After a grader change, re-grade the stored answers first** (`regrade`), before generating anything.
- **A real limit looks like the wrong computation, not the wrong format**: a chain applied for one
  step only, arithmetic stopping at the first step, an invented bridge. Report those families `ooc`
  with two such answers.
- **A family whose kept golds are almost all one value is unusable.** Example: the 0.8B's moral sides
  were 57/61 "no", so a constant readout scores well. Exclude it from the macro.

**Small subjects (≤ ~4B):** expect format failures and empty multi-step families. Walk the format
variants before the ladder, and keep the ladder's easiest tier honest: it must still carry the latent.

**Big subjects (≥ ~30B, MoE, 1T):**
- **Backends:**
  - ≤ 9B: the 4090.
  - Dense 30B-class: `scripts/adapt_modal.py` (edit its `gpu=` for B200 / B300).
  - MoE / 100B-class+: tensor-parallel vLLM or HF model-parallel (§On another box).
  - 1T (Kimi-K2): its B300:8 model-parallel gate app. Batch every candidate into ONE generation run.
- **They pass most originals.** The work is the model-specific families and gating, plus a few refills.
- **If their lenses were already read on the 27B bank**, re-score instead of re-reading
  (`atlas/normal_gated.py`, Agam's box only):
  - gate every item from the profile, every leg, with audit drops applied;
  - re-gold poetry, basic_readout and moral on the subject, and re-judge them on the existing readouts,
    seeding each judge dir with the original `cells.jsonl` so unchanged golds are cache hits;
  - drop families with fewer than 10 passing items;
  - report as-is vs gated vs the registered-family headcount (28 = registered families minus
    typo (superseded) and unverbalized_hint (retired); count it from the registry, it changes).
- Then score them on their own adaptive set like any subject.

**Any tokenizer:**
- **Re-derive banks that store token positions** (MCDM, jailbreak) by character
  span in the subject's own render. Require 0 mismatches.
- **Gate in the exact read render**: no system turn unless the read has one. association,
  conjunctive and role_bound are READ in the `chat_summarize` render, and (plan 0060 D10) their
  knowledge legs (association's referent, role_bound's asked question) are asked in it, as a
  follow-up after the subject's greedy summary with the read render as a checked token prefix.
  Leak screens stay the plain continuation (`references/families.md` "Gate in the read render").
  Records gated before D10 need a regate, not a regrade.
- **A frozen item's `gate_variant` never picks its eval render**; only adapted items' variants do
  (`readplan` poetry).

**Lessons from the 2026-10-23 round (each has an audit or pilot behind it):**
- **Selection caps:**
  - role_bound: at most 12 uses of any role; relational: at most 20 per relation.
- **role_bound strict grading:** `ADAPT_ROLE_BOUND_STRICT=1` credits only answers that name the roles.
  Small subjects that answer with names pass the lenient grader but score 0 under the strict one, so
  they stay out of the macro.
- **Possessive and split blanks** (relational on Gemma / Kimi): read the final piece of the blank and
  verify by character span. Drop a scene if the tokenizer merges the blank into the name.
- **Arithmetic and chain:** the pre-registered 27B read cell (`cells=frozen`) scores about 0 on other
  subjects. Reading every position mostly matches other items' values (9B pilot: chance .70, real
  lift +.04 to +.10), so report the lift over a permutation null next to any every-position number.
- **Scoring models whose lens was read on the 27B bank:** `atlas/normal_gated.py`. Their own-set
  scoring uses the subject's `-adapt` apps in gw-olens: `subject_*_modal.py` / `adapt_mp_subject_modal.py`,
  and for Kimi, `kimi_wsbench_modal.py` in adaptive mode (all Agam's box / env only).

**Ops:**
- **tmux:** wait on sessions with `tmux has-session -t "=name"` (exact match).

## report.json (schema) and audit decisions
Per family: `status` (full / partial / untried / ooc / blocked), `note`, `change`, counts
(`target`, `n_items`, `n_new`, `n_original_pass`, ...), `exclude_from_macro` (consumers and
`wsbench report` leave it out of the macro) and, from the 2026-11 refresh on, `bank_version` (the
registered bank the family was ported from). Top level: `model`, `hf_id`, `n_layers` (the read
plan's subject depth), `read_band`, `code`, and the audit decisions, which `freeze`, `fill` and
`auto` honour:
- `drops[family][id] = reason`: written by `adapt drop family= ids=a,b reason=` (never by hand);
- `patches[family][id] = {set, note}`: one item's fields fixed in the adapted copy only, written by
  `adapt patch family= id= set='{json}' note=`.
Every step writes its own entry (agentic, carry included); writes are atomic and locked.
`adapt status model=<m>` prints the per-family state.

## Process hygiene
- GPU commands (`profile gate auto fill agentic moral floors`, except their Claude-only stages)
  take the box lock `$ADAPT_GPU_LOCK` (default `/workspace/agam/logs/gpu.lock`) inside
  `adapt_box.sh` only; `python -m wsbench.adapt` called directly takes no lock. A chain script that
  holds it (`exec 9>LOCK; flock 9`) passes the fd down. Never take it in a tmux command line ending
  in `exec bash` (the shell keeps it).
- Unknown CLI keys are errors. `regrade` never undoes `adapt moral`'s side checks.
- The model-grade cache persists (`adapted/.grade_cache/<grader>.jsonl`); `author` writes after
  every call; the gate, regrade and fill are resumable (gated ids are skipped).

## Rules
- The gate is the subject itself, with its own template and thinking off. Never use OpenRouter
  stand-ins (a provider that cannot turn reasoning off is a different render), and never use
  another model's answers.
- Same gate rule as the banks: greedy right AND ≥ 8/10 (10/10 for chain). Don't lower it
  to fill a family.
- Never pad:
  - synthsys user_modeling items score echo, not inference;
  - a family that can't be filled is reported `partial` / `ooc` with its real count; a short family
    whose ladder was never tried is `untried` (never `partial`).
- Keep pairs atomic: twins, ab/ba, think/dont_think pairs pass or drop together.
- Record every knob in `adapt.knobs` and every family's change in `report.json`. Anyone reading a
  number must be able to tell what difficulty, and which bank version, it was measured at.
- Opus authors; it never grades its own items as correct. The subject grades by answering. A
  deterministic grader or the repo grader checks the answer.
- Claude calls (`llm=` grading, `author`) on Agam's box use the judges' keyless OAuth token
  (`wsbench/adapt/auth.py`; Modal Dict `anthropic-oauth`, read only); on a 401 there, stop and ask
  Agam to run `push-judge-token`. Elsewhere use `WSB_ANTHROPIC_AUTH=sdk` (§On another box). Never
  export `ANTHROPIC_API_KEY` into a shell or commit one.
- API budget: before any authoring batch over ~2k items, check the org's rate-limit headroom (the
  judges share it) and pace to it. Before any big run, check that no other session is already
  running it (one agent per shared run).

## References
- `references/families.md`: per family, the latent, gate, required keys and registered-bank
  fields, invariants, and difficulty ladder.
- `references/authoring.md`: the Opus authoring prompt, the per-family briefs, and failure-steered
  waves.
- `references/porting.md`: layers, tokenizer, read positions, the model-specific regeneration
  procedures, and judging an adapted bank.
- `references/pitfalls.md`: what went wrong before, plus known defects in the frozen banks.
