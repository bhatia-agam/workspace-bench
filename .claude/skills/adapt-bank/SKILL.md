---
name: adapt-bank
description: Build a per-model WorkspaceBench set (adapted/<model>/) for a new subject model end to end, or refill / re-audit an existing one. It gates every registered bank on the subject, rebuilds the model-specific families, refills each family to target with items of the same kind that the subject passes, runs plan 0075's data round (D1-D7 screens, the two-run leaker rule), then audits, floors and ships the set. Use when someone wants WorkspaceBench for a model other than Qwen3.6-27B (Qwen3.5-0.8B up to 1T MoE: Qwen, OLMo, Gemma, GLM, Kimi, DeepSeek, Muse, any HF chat model), asks for "adaptive", "per-model", "re-gated", "ported" or "refreshed" banks, asks why an adapted set fails to judge, or asks why a lens scores low on a small model.
---

# Adapt WorkspaceBench to a subject model

Every registered bank was gated on Qwen3.6-27B. A lens that says nothing about an intermediate the
model never computed is not wrong, so on any other model the banks are re-gated, and the items the
subject fails are replaced with items it passes. **The goal is a bank where every item:**
- **(a)** tests the same kind of latent as its family;
- **(b)** is something this subject computes (greedy right, ≥ 8/10 sampled);
- **(c)** is still valid for the family's judge, read site and null.

Easier is fine. A different kind of latent is not. **Change the difficulty of what is asked.
Never change the construction rules, the gate or the scorer.**

## Quickstart: a new subject, end to end

**State (2026-11-16).** 15 sets are on main under `adapted/` (`adapted/README.md`); deepseek-v4-flash is the 16th, not yet merged.
- Ten were rebuilt under plans 0060-0087. Plan 0089 rebuilt Agam's five, and deepseek-v4-flash
  is new (#469). Both of those were in flight on 2026-11-16, each with its data PR to come.
- The newest builds follow exactly this path. A set is **30 families** (§Scope).
- Expect 1-2 days of wall clock per set (§GPU sizing).

| # | step | how | done when |
|---|---|---|---|
| 0 | **Run tree + environment** | A git worktree off `origin/main` on a local branch (`git worktree add /root/tmp/wsb-<m> -b <m>-set origin/main`). The set's data stays LOCAL until it is frozen and audited. Write the environment below to `env.sh`. | `$PY -m wsbench.adapt` prints its usage |
| 1 | **Code PR: the subject** | §0 Set up the subject: a `Subject` in `src/wsbench/adapt/subjects.py` and the key in `refill.PLAN_0075_SETS`. Add a no-think template only if the upstream one cannot turn thinking off. Add a `read_band` if the subject has an O-lens. Weights go on a Modal volume (`scripts/download_weights_modal.py`). Deploy its app (`ADAPT_SUBJECT=<m> modal deploy scripts/adapt_modal.py`). Tests. Its own PR, merged through `scripts/gated_merge.sh <pr>`. | merged; the deploy is live |
| 2 | **Smoke** | `$A profile model=<m> families=typo limit=5 llm=claude-opus-5-5`. Read the renders and answers. | no template error; answers look like answers |
| 3 | **Build** | `NATIVE_LANGS=en,zh NATIVE_EVIDENCE="<lab>-lab model: native <langs> by Camila's lab decision (plan 0089), not measured" WI_POOLS=<dir1,...> scripts/adapt_set.sh <m> build` in tmux. Add `MORAL_VARIANT=system_one_word` for a prose answerer (Gemma). | `logs/adapt/<m>/build.status` ends `BUILD DONE`; read every `FAIL` line |
| 4 | **The two side builds** (separate tmux / agent; they overlap with 5-6) | introspection (§Introspection); hinted_cutoff (§hinted_cutoff, plan 0084) | each installed, or an objective, evidenced `ooc` / `partial` |
| 5 | **Refill** | `scripts/adapt_set.sh <m> refill`. Every refill route runs once; any family that stopped on `max waves` runs again with `MAX_WAVES=40`. | `REFILL DONE`; every short family has an objective stop (§Decision table) |
| 6 | **Data round** | `scripts/adapt_set.sh <m> loop 1 8`. Each round back-fills, freezes, runs the D4-D7 screens, two lucky runs and the D1-D3 leakers. It stops once a cycle drops nothing and the back-fill lands nothing. | `CONVERGED at <n>` in `logs/adapt/<m>/loop.status` |
| 7 | **Final freeze** | `scripts/adapt_set.sh <m> final 1`: a strict freeze with every family named, plus a report-only lucky measure | the strict freeze exits 0 |
| 8 | **Independent audit** | A fresh-context subagent writes `adapted/<m>/AUDIT.md` (§AUDIT.md checklist). Apply its must-drops with `adapt drop`, with NO new authoring. Then `final 2`: the re-freeze fills freed slots from rows that already pass. Audit those rows too, as an addendum. Then `scripts/adapt_set.sh <m> mmh 1`, the FRESH model_multihop confirm (plan 0078: freeze and audit come first; 3 failed confirms block the family). | the auditor's verdict is clean; the mmh confirm passed |
| 9 | **Floors** | §4 Floors: `po-opus-v1` (bench) and `stock-subject-v1`, both into `adapted/<m>/floors/` | `floors/floors.json` holds both records |
| 10 | **Ship** | Write a `note` per family (`adapt note`). Add the README row and bump the census (§Ship checklist). One data PR per set, merged ONLY through `scripts/gated_merge.sh <pr>`. | merged; main CI green |

The environment (`env.sh`; source it in every tmux session, or pass `ADAPT_ENV_FILE=env.sh` to the driver):

```bash
export MODAL_PROFILE=safety-sahan-2 MODAL_ENVIRONMENT=camila-blank ADAPT_BACKEND=modal
export WSB_ANTHROPIC_AUTH=sdk ANTHROPIC_PROFILE=default HF_HUB_OFFLINE=0
unset ANTHROPIC_API_KEY                    # never export one; the driver refuses to run with it set
export ADAPT_POETRY_VARIANTS=fewshot,prefill WSB_POOL_DIR=/workspace/wsb-runs/pools
export WSB_TOKEN_LEDGER=$PWD/logs/ledger_<m>.jsonl PYTHONUNBUFFERED=1 PYTHONPATH=$PWD/src
export PY=/root/torchvenv/bin/python A="$PY -m wsbench.adapt"
```

**The driver** is `scripts/adapt_set.sh <model> <phase>` (plan 0091). Run it with no arguments
for its help.
- Each step logs to `logs/adapt/<m>/<step>.log` and records `ok` / `FAIL` in
  `logs/adapt/<m>/<phase>.status`.
- A re-run skips the steps that are already `ok`.
- It retries only the Claude OAuth refresh race. A failed freeze, onecue, screens, lucky or
  leakers step stops the phase (`ABORT` in the status file). Any other failed step is logged as
  `FAIL` and the chain goes on. In `loop`, a failed back-fill step keeps that round from counting
  as converged.
- `loop` saves each round's count snapshots (`L<n>.counts{0,1,2}`), so a resumed round compares
  the same snapshots.
- `DRY_RUN=1` prints every command and runs nothing.
- Lucky runs, screens and onecue output go to `outputs/adapt/<m>/`.

Drive one phase per tmux session, and watch the `.status` files. The data-round rules it
applies are `python -m wsbench.adapt dataround` (`src/wsbench/adapt/dataround.py`):

| stage | what it does |
|---|---|
| `stage=screens out=<dir> [apply=true] [only=d4,d5,d6,d7]` | D5 capitals (regex), D4 bridge shortcuts and D6 places (Opus, cached in `<dir>`), then the D7 Country / Gender 20% caps |
| `stage=leakers run=<lucky dir> [root=<dir>] [apply=true]` | D1-D3 with the two-run rule: only `c*` / `final*` runs under `root` count as earlier runs; `history=` widens that |
| `stage=short` | prints which families to back-fill, which to re-wave, and which are final |
| `stage=counts` | the driver's convergence check |
| `stage=lucky` | the MC families and how to measure them |

Without `apply=true`, `screens` and `leakers` print the `adapt drop` commands instead of running
them.

**Merging** (plan 0089, fail closed): `scripts/gated_merge.sh <pr>` merges
only a PR that has checks and whose every check is pass or skipping. Never pipe
`gh pr checks` into `&& gh pr merge`. Bench data stays local until the set is frozen and
audited, then goes up as ONE data PR per set. Code changes go in their own PRs first.

## Scope: the 30 families, and when a family may ship short

- **30 families** = the 33 families `all` runs (`registry.drop_superseded`) minus `jlens_concept_pr`,
  `user_modeling_hard` and `association_hard` (plans 0106 and 0108: their items were selected on
  Qwen3.6-27B's own gates, so no adapted set carries them; `adapt.families.NOT_ADAPTED`).
  `introspection` and `hinted_cutoff` are in scope on every set.
- Every item is gated on the subject itself: thinking off, its own chat template, greedy right
  AND >= 8/10 sampled (10/10 for chain).
- A family ships short ONLY on an objective stop with evidence:
  - the subject cannot do the task (yield below the policy floor on enough candidates at the
    easiest level);
  - a pool is exhausted;
  - a technical blocker can be shown.
- **Budget is never a reason**, and neither is "the subject is small".
- `untried` is never final. A family with zero attempts ships nothing until it is tried.
- **Native languages are set by lab decision, not measured** (plan 0089). Google (Gemma), AI2
  (OLMo), Meta (Muse) and other American labs get `['en']`. Alibaba (Qwen), Moonshot (Kimi),
  Zhipu (GLM) and DeepSeek get `['en','zh']`. Record it with
  `adapt native_langs langs=... evidence=...`. The measurement route (`stage=measure`) stays
  for research only.
- **Introspection** has a pre-registered calibration rule (`adapt/introspection.py`). The
  headline beta needs median RR ≥ 0.60 and ≥ 80% coherent injected neutral replies (≥ 6/10).
  - A NO-GO on that measured calibration is the evidence for `ooc`. Record the peak RR, the
    beta grid and the controls in `introspection/calibration.json`, and the engine checks in
    `engine_diagnostic.json`.
  - Every subject so far is `ooc`: GLM-5.3, Kimi-K3, V4-Pro, Muse, Agam's five and V4-Flash,
    all with peak median RR ≤ 0.17.
- **Agentic** needs ≥ 20 pairs (`MACRO_MIN_PAIRS`) to enter the macro. Below that it ships
  `partial` and stays out of the macro, with its per-wave yields in the note.

## GPU sizing (measured on the 2026-11-14..16 builds)

The GPU is Modal list price, and the Claude API is not capped (`api-cost-free-gpu-only`). Report
GPU $ before any big fan-out. **The `camila-blank` Modal environment is capped at 16 containers
shared by every agent.** Check `modal container list` before starting a fan-out. The figures
below are snapshots: the plan-0089 and V4-Flash builds were still finishing.

| subject size | examples | serving (Subject fields) | GPU $ per set | wall clock | notes |
|---|---|---|---|---|---|
| small, ≤ 9B dense | qwen3.5-0.8b..9b, qwen3-8b, olmo-3-7b | shared `adapt-subject-llm`, 1×H200 (~$4.5/h) | refill round ~$60 (sq-refill: ~$290 GPU for all five sets, ~9.5 h of overlapping runs) | build ~1 day; refill round ~1 day | Expect format failures first; walk the format variants (§Tailoring) before the difficulty ladder |
| mid, 27-35B (dense or small-active MoE) | gemma-4-31b-it, olmo-3.1-32b, qwen3.6-35b-a3b | shared `adapt-subject-llm`, 1×H200 | ~$95 pipeline + ~$15 hinted_cutoff (21 h busy) | ~1-1.5 days | Introspection runs on the single-GPU engine (`adapt introspection stage=all`) |
| big MoE (~300 GB FP8) | glm-5.3-flash | own app, B200:4 TP4 (~$25/h), `modal_max_containers=1` | ~$530 pipeline + ~$55 hinted_cutoff | ~1.5 days | One container: concurrent stages queue behind each other. Run ONE refill at a time. Cold boot ~30 min |
| 1T-class MoE | kimi-k2, deepseek-v4-flash (also glm-5.3, kimi-k3, v4-pro, muse at 0060) | own app, B300:8 (~$56/h), TP8 or 8×TP1 engines | ~$1,000-1,200 pipeline (kimi-k2 ~$1,160; V4-Flash ~17 container-hours) + ~$60 hinted_cutoff probe | ~1.5-2 days | Cold boot 15-45 min, so batch every candidate into one generation run per stage. Keep the 1-container cap. Introspection needs a multi-GPU stack (`scripts/adapt_introspection_mp_modal.py`) |

**Claude API per set** (ledgered, uncapped): ~$1-1.5k for the pipeline. hinted_cutoff adds
$150-730 of Opus, mostly the silence judge `verb_judge` and `exist4`. Agam's five together came
to ~$6k by 2026-11-16 20Z.

## Decision table: what to do when a family stops short

| you see | meaning | do |
|---|---|---|
| `status: ooc`, stop `yield x/n < y_min on >= n_min ..., have < target/2` | an objective capability stop (plan 0066 §1.2) | Final. Never re-wave it. Note the counts. A `refill_hold` turns it `partial` until the fault is cleared |
| stop `low yield above half: ...` | the same yield rule, but the bank is over half full | Ship `partial`, with the stop in the note |
| stop `pool exhausted` | every candidate of the funded pool was gated | Ship `partial`. A new pool generation is a funded follow-up (plan 0077), never padding |
| stop `max waves (N)` | refill's own wave cap, NOT an objective stop | Re-run with more waves (`waves=40`). The driver's `refill` / `loop` phases do this automatically (`dataround stage=short` → `max_waves`) |
| stop `budget spent (...)` or `pilot: not ooc` | you capped it, or it was a pilot | Run the full refill. Budget is never a reason |
| multihop refill whose `untried_levels` is non-empty | the 3-hop level of the pool was never gated | Keep refilling. `refill` refuses `ooc` while a harder level has ungated candidates. A subject that fails 2-hop on shortcuts is too capable, not incapable |
| `untried` after a freeze | no refill was ever run | Run `adapt refill families=<f>` (the strict freeze refuses this) |
| full family short after the data round | screens and leakers dropped it below target | `loop` back-fills it. If the back-fill lands nothing, ship `partial` and give the count each rule dropped in the note |
| a family over chance + 5 with no confirmed leaker | a single-run flag is only pending | Run more cycles. Still over at the end: report it in the note with the failing runs. Never drop on one run |
| agentic below 20 pairs | the pools' yield on this subject | Run every pinned pool's waves, newest last (§Agentic). Still below: `partial`, out of the macro, with per-wave yields |
| introspection NO-GO | measured calibration below the rule | `ooc`, with `calibration.json` + `engine_diagnostic.json`, audited |
| hinted_cutoff short or the date bar fails | plan 0084 R19: the bar is the date checks | §hinted_cutoff: a widened window or a top-up pool, then re-run; never relax the bar |
| wrong_intermediate kind check misses a Wikidata class | the frozen class table lacks a deep leaf | `python scripts/wd_add_leaves.py src/wsbench/adapt/data/wd_class_parents.json Q...` (grow-only; plan 0089, #477) in a code PR, then re-run |
| Opus refuses a grading / judge call | content refusal | WSB judging falls back to Sonnet 5.5 (`summ_fallback=default+claude-sonnet-5-5`, the same for every arm). Rescue judging is pending (§Judging the set) |
| a step fails with `invalid_grant` / `authentication_error` | the Claude OAuth refresh race | The driver retries it. By hand: wait 1-3 min and re-run, since every stage resumes |
| the Modal app queues for an hour | a 1-container subject shared by two of your chains | Serialize the chains. Never raise `modal_max_containers` on main to get around it |

## The side builds and the families with their own rules

### Introspection (plan 0067; every set)
- **Up to ~35B (one GPU):** `$A introspection model=<m> stage=all llm=claude-opus-5-5`. It runs
  job → measure → coherence → calibrate → build.
- **Big MoE:** use `scripts/adapt_introspection_mp_modal.py`.
  - Steps, in order: `stage=job` → `calib_main` → `calib-report` → `run_main --shards N`
    (detached, in tmux) → `finish` → `stage=measure result=<npz>` → `calibrate` → `build`.
  - The module docstring gives the exact lines.
  - Stacks exist for glm-5.3, deepseek-v4-pro / v4-flash, muse-spark-open, kimi-k3, and (#474)
    kimi-k2 and glm-5.3-flash. A new big subject needs its own stack first, in its own code PR.
  - The xaff readers need `WSB_GW_XAFF` (a global-workspace checkout with PR #723).
- **The rule:** `ooc` on a measured NO-GO (§Scope). The engine checks (exact no-op, local steer)
  must pass first; otherwise it is a pipeline fault, not `ooc`.

### hinted_cutoff (plan 0084; every set)
The gw ccut v2 pipeline is re-run on the subject from `scripts/hinted_cutoff_adapt/`. It needs a
scratch copy of a global-workspace tree holding `evals/chint_cutoff/`, never a gw checkout.
PYTHONPATH = gw `src` + the cf_influence scripts dir + this repo's `src`.
1. **Probe:**
   - `probe.py stage=in out=<probe> per_month=40` → `subject_gen.py --model <m> --inp <probe>/base_in.jsonl --out <probe>/base_out.jsonl` → `probe.py stage=curve`.
   - This measures the subject's fade-out. If the fade-out is later than v2's 2024-01..2025-06
     window, set `HC_P_WINDOW=lo,hi` to move the window. GLM-5.3 and flash used 2025-03..2026-02;
     kimi-k2 was widened to 2024-04..2025-12.
   - `merge_bank.py` joins gw v2 with the later-drafted items.
2. **Pilot:**
   - `pilot_select.py n=150`, then the ccut stages through `subject_ccut.py` with
     `HC_CONFIRM_ALL=1`, from `screen_gen` to `verb_calib`. `[gen]` steps go through
     `subject_gen.py`.
   - It measures each stage's survival. The build's projection gate needs ≥ 60 pairs; a no-go
     there means widening the window, not lowering the bar.
3. **Build:** the same stages with `HC_SUBJECT=<m> HC_SURV=<pilot survivals>
   HC_P_WINDOW=lo,hi HC_GUESS_GAP=<caliper>` (R18).
4. **Finish:**
   - `finalize.py` refuses a failed bar. The bar (R19) is the date checks only:
     |day AUROC − 0.5| ≤ 0.10 and cell excess ≤ 0.10.
   - The prompt-only predictors (`predict_single`, `predict_normal`) are recorded, not gating.
     Report them PROMINENTLY in the note; GLM-5.3-flash's I − N was +0.41.
   - Install with `$A hinted_cutoff model=<m> frozen=<frozen_<m>.json> gw_commit=<sha>`.
5. **Audit drops:** `subject_ccut.py drop_pairs`, keeping `HC_GUESS_GAP` set. Then re-run
   finalize and install.
6. **Short set:** if the set comes out short, top it up (plan 0084 § Top-ups). Densify the
   window, or extend the pool by date: OLMo used a 2023 pool, with a web-check of the drafted
   items and the first audit carried forward.
   - Pool by date: v2's `bank_draft` → `bank_verify` → `bank` with `HC_P_WINDOW` on the new
     months, then `merge_bank.py --pre <bank>:<lo>:<hi>`. Densify: `propose_series.py` (new
     series for the fade window) → the same three stages → `merge_bank.py --extra <bank>`.
     Either way, run a 40-item web-check (≥ 39/40) and `--exclude-qid` every verified defect.
   - Re-pair under the same rule, then run `carry_forward.py <prior drops...> <out_dir> <out>`
     (BOTH twins of every pair an earlier audit dropped) beside a fresh audit; apply the union
     with `drop_pairs.py`.
   - A tokenizer without `offset_mapping` (Kimi-K2's tiktoken) is handled by `subject_ccut.py`'s
     `OffsetTok` automatically.

### Agentic (plans 0031 / 0052 / 0077)
- **Build:** `$A agentic model=<m> stage=all` builds the registered scenarios with clean twins.
  `$A agentic model=<m> pool=<v> waves=8` then runs waves of the sha-pinned adapt-only pair pool.
- **On main (2026-11-16) only `pool=v3` is pinned.**
  - am-pool-v4..v7 exist, with the newest `pool=vN` chaining every older pool. They carry v6's
    calm-twin authoring steer (all temptation inside the spans the twin replaces) and v7's more
    provocative originals.
  - The transformers-5 fix to `agentic_pool_v3.chat_tokens` is also there: `apply_chat_template`
    returns a BatchEncoding, so before the fix gate 3 recorded length ratio 1.0 for every twin.
  - All of this is in the open sq-refill / plan-0089 branches. Use them once merged. Until then,
    a set that needs more pairs than v3 gives ships `partial`.
- **Audit:** every new pool gets an independent audit before pinning.
- **A pair drop** (`adapt drop`) takes both members.

### Judging the set (after it ships)
- Judge only through `WSB_BANK_ROOT=adapted/<m>` (`references/porting.md` §Judging).
- **Pending on the sq-refill branch, not on main:**
  - `summ_refusal_chain=claude-opus-5-5+claude-fable-5-1+claude-haiku-5-5`: agentic re-runs only
    its unjudged items down the chain;
  - `am_pins`: decided items keep their Stage C reply;
  - the layered stage-2 rescue.
- **Also pending:** the global fix to the `" | "` evidence split, which was cutting `<|...|>`
  special tokens. It is its own PR.
- **A refused call is never cached:** each re-run re-asks it, and a decided item with a
  declined layer can drift.

## AUDIT.md checklist (an INDEPENDENT fresh-context agent writes it; never self-certify)
- **Header:** the subject (HF id @ revision) and the code sha. Say what was checked and how: every
  new item, plus a sample of originals per family.
- **Per family:** the count shipped, the target and the status; the item-quality checks (§4: legit
  distractors, no shortcut, one defensible gold, no near-duplicates, class caps); must-drops by id
  with a reason, and borderline cases kept with a reason.
- **The data-round record:**
  - each rule's drop count (D1-D7);
  - leakers still pending at the last measurement;
  - families still above chance + 5, with the failing runs;
  - the onecue flags kept as shipped.
- **Model-specific evidence:**
  - introspection (calibration numbers, engine checks);
  - hinted_cutoff (pair count, date checks, the prompt-only predictors);
  - agentic (pairs, per-wave yields, the pools used);
  - wrong_intermediate / knowledge_cutoff / msdm / multihop (the stops and pool use);
  - model_multihop (the confirm verdict).
- **Every objective stop**, checked against its `report.json` `refill` block.
- **Addenda:** the delta audit of rows the post-audit re-freeze filled, and any PR-review drops.
- **Verdict:** usable / usable with notes / not usable, per family.

## Ship checklist (the data PR)
- `adapt status` is clean, and every family has a `note`. That covers
  `exclude_from_macro` and the reason for every short or `ooc` family. Record
  `native_langs by decision` and the hinted_cutoff predictors.
- The verify step passes (§4: `wsbench plan --full` under the root, and each judge with `dry_run=True`).
- `floors/floors.json` holds `po-opus-v1` and `stock-subject-v1`.
- **`adapted/README.md`:** one row per set: path, serving (app, GPU), the family count, per-family
  status highlights, native langs, introspection / hinted_cutoff / agentic outcomes, and the
  floors. Link AUDIT.md.
- **Census:** bump `tests/test_typo_mt.py::test_no_reachable_typo_mt_bank_has_arith_items` (`len(paths) == N`,
  "bump per set"). It is the one pre-existing test a new set's PR changes by design.
- `pytest -q` and `ruff` pass locally. Push, open the PR (`Closes #<set issue>`), then run
  `scripts/gated_merge.sh <pr>`.

## Layout (everything this skill writes)

```
adapted/<model>/report.json            per-family: target, n_original, n_original_pass, n_items,
                                       n_new, status, change (what the difficulty knobs did), note
adapted/<model>/<family>.json          frozen adapted bank: the header + item shape of the
                                       REGISTERED bank (`registry.frozen_bank_path`, e.g.
                                       evals/association/association/items_v3.json, not items.json); each
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

`gate/`, `cand/`, `floors/{readouts,results}/`, `mc/`, `mmh/` and the grade cache are
git-ignored. They live only in the run tree that built the set, so archive it
(`/workspace/archive/...`) before deleting the tree. A later top-up of a set needs its gate log.


## Procedure

Keep a ◼/◻ todo tree in replies, one line per family. Do one subject at a time and finish it before
starting the next.

### 0. Set up the subject (the code PR of Quickstart step 1)
- Add it to `src/wsbench/adapt/subjects.py`. Copy the closest existing Subject:
  - the HF id and the pinned revision (the checkpoint its lenses were trained on);
  - the layer count and the tokenizer family;
  - `thinking_mode` if the hub template has a thinking switch;
  - for Modal: `backend="modal"`, `modal_app`, `modal_gpu` (fallbacks in order), `modal_tp`,
    `modal_image`, `modal_volume` + `modal_weights`, `modal_engine` kwargs and
    `modal_max_containers` (1 for a subject whose app is a multi-GPU container: concurrent
    stages then queue instead of booting a second B300:8; plan 0089 #473);
  - `read_band`: the layers of the subject's O-lens, if it reads only some.

  Pick the shared app if the model fits one H200, else the size class of §GPU sizing. Qwen3.5 shares the Qwen3.6 tokenizer and template, so token indices carry over; Gemma's
  don't. A subject whose upstream template always opens a reasoning block (GLM-5.3-Flash) or ships
  no Jinja at all (DeepSeek-V4: only `encoding_dsv4.py`) or has no thinking-off mode at all
  (Muse-Spark-Open: the generation prompt names the answer channel) needs a pinned no-think
  `chat_template` file checked against the vendor's own encoder on a few renders. A tokenizer
  whose thinking switch is not `enable_thinking` (Kimi-K3's remote-code XTML render takes
  `thinking`) sets `Subject.thinking_kwarg`: `load_tokenizer` renames the kwarg, so every render
  still says `enable_thinking=False`. A reply marker the engine does not stop on and the
  detokenizer keeps (K3's non-special `<|close|>`) goes in `Subject.reply_end`: `RemoteRunner`
  has the engine stop on that token id. A template that encodes message content with specials
  disallowed (K3) sets `Subject.template_ids`: prompt ids come from
  `apply_chat_template(tokenize=True)`, never from re-encoding the rendered text (callers send
  `runner.prompt(ask)`, `gate.prompt_of`). Per-subject notes: `references/porting.md`.
- **The read band.** An O-lens that reads exactly 11 layers maps the 27B grid one-to-one: the
  k-th grid layer goes to the k-th band layer (`subjects.remap_layer`'s table rule;
  `tests/test_adapt_v4.py::test_v4flash_read_band_reads_every_olens_layer`). Any other band snaps
  each grid layer by depth to the nearest band layer. A band that folds two grid layers together
  silently loses a layer, so test it.
- **Add the key to `refill.PLAN_0075_SETS`.** A key outside it keeps registered-size targets and
  skips the 0075 capital re-check and strict-freeze guard (plan 0089 change 3).
- **Weights:** download them once, on CPU, into the app's volume. Use
  `WSB_DL_VOLUME=<v> modal run --detach scripts/download_weights_modal.py --repo <hf id> --revision <sha>`
  (hub-cache layout under `hf/hub`; the shared `adapt-hf-cache` uses `hub`). Never let a GPU
  container download weights.
- **Generation runs on Modal** (`ADAPT_BACKEND=modal`). Deploy the subject's app with
  `ADAPT_SUBJECT=<m> modal deploy scripts/adapt_modal.py`; without `ADAPT_SUBJECT` it deploys the
  shared `adapt-subject-llm` H200 app. Every step (gate, moral, agentic, floors) generates
  through `RemoteRunner` from token ids, while rendering and grading stay local. A changed
  Subject's modal fields need a redeploy. The RunPod 4090 / `scripts/adapt_box.sh` route of the
  October sets is retired.
- Thinking is always off. Use the subject's own chat template. Every runner start runs
  `template.check` (markers derivable, no reasoning block left open, system turn accepted) and
  refuses to gate otherwise.
- Smoke test first: `$A profile model=<m> families=typo limit=5 llm=claude-opus-5-5`. Read the rendered question and
  the answers in the viewer before running anything bigger.

### 1. Profile: gate the registered banks on the subject
`$A profile model=<m> families=<the 17 item-gated families: adapt_set.sh's PROFILE_FAMS>` asks each item's own gate question(s) and writes `gate/<family>.jsonl` with
origin `original`. It reads `registry.frozen_bank_path` (the registered default bank), so it gates
today's items; ids already in the gate log are SKIPPED unless `regate=true`.
- Use greedy plus 10 samples at T=0.7 (chain: T=0.8, top_p 0.95, 10/10; every other knob:
  references/families.md, top).
- multihop_st and the bridge families also gate every bridge question: the bridge is the scored latent.
- Own-answer families (poetry, basic_readout_st implicit) stamp the subject's own word as the gold.
- Then read the failures per family in `adapted/<model>/gate/<family>.jsonl` (one record per
  candidate: the item, the subject's answers, the gate verdict). Check the answers
  themselves before you choose a knob: "right idea, wrong format", "wrong language" and "refused"
  each need a different fix from "doesn't know".
- A grading miss (a valid alias or translation) is a grader bug. Fix the forms or use `llm=opus`.
  Never fix it by lowering the bar.

### 2. Rebuild what is model-specific (no difficulty change)
Follow `references/porting.md`:
- poetry v5: the subject's own rhyme (`$A poetry stage=all`: gate → tier_a → mc → opus_gate;
  `ADAPT_POETRY_VARIANTS=fewshot,prefill`). Run `stage=settle` before every freeze that names
  poetry.
- basic_readout_st implicit: the subject's own favourite (`$A mc families=basic_readout_st
  stage=subject` after every gate).
- moral_rationale v3: re-keyed on the subject, with its side, its reasons and option lists rebuilt
  for them. Run `$A moral stage=rekey_readrender step=<requests_s|grade_s|requests_r|distil|verify|assemble>`,
  then `stage=options`, then `stage=adopt`. A prose answerer (Gemma) needs
  `variant=system_one_word`.
- The model-specific families (msdm, knowledge_cutoff, multihop, wrong_intermediate,
  nyt_connections, model_multihop, hinted_cutoff, introspection) are listed under §Families with
  their own build.
- directed_modulation: the compliance screen.
- agentic_misalignment: rollouts, the clean twins included (plan 0060 D5; `$A agentic`).
- jailbreak_recognition: positions and template (`carry`); the v2 controls are re-screened on the
  subject by `carry` (plan 0060 A2).
- multi_concept_directed_modulation: the prefill render (bank v2, 116 items).
- jlens_concept_pr: out of the 30 (§Scope). It needs the subject's J-lens; build it only on
  request.
- Layer remap: by depth fraction, for every family (`wsbench plan` does it from `n_layers`).

### 3. Refill each family down its difficulty ladder
`adapt refill` (§3a) drives every family with a refill route. `adapt_set.sh refill` / `loop` call
it for you. This section is the general procedure underneath: read it when you have to steer a
family by hand.

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
   - Authored families (`wsbench/adapt/author.py` `BRIEFS`: association, multihop_st, multilingual_st,
     typo_st, poetry, the five mt families typo / multilingual / multilingual_typo /
     multilingual_multihop / basic_readout, user_modeling, basic_readout_st implicit, role_bound
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
   an association candidate without `mc` is rejected before the GPU; multihop_st; chain per-slot;
   poetry `mc.candidates`) must exist in the candidate payload. **The frozen-bank MC builders do not take
   adapted items.** `scripts/build_multihop_mc.py`, `association_distractors.py`, `moral_distractors.py`,
   `mc_leakage_r4.py` and `role_bound_distractors_v3.py` read and WRITE the frozen `evals/` files
   (hard-coded paths): never run them for an adapted set, it rewrites the bank of record.
   `r4_mc_distractors.py` writes only to `--out` but reads frozen banks only. Only
   `scripts/poetry/build_mc.py` takes `--draft` / `--out` over an arbitrary bank. A field built by hand into
   `adapted/<m>/<family>.json` is lost at the next `freeze` (it rebuilds from gate-log payloads +
   `patches`). For an id ALREADY in the gate log the only route is `adapt patch` (applied at freeze;
   never linted or gated): a rewritten `cand/` row is ignored (`store.pending` / `add_candidates`
   skip gated ids) and `gate regate=true` re-gates the gate-log payload, not the cand row. A new
   item can carry the field in its `cand/` row before its first `gate`. `adapt mc` (and `fill`,
   on every wave) builds it for the pending adapted-only candidates of association, multihop_st,
   basic_readout_st and basic_readout; each build gets its own work dir
   `adapted/<m>/mc/<family>/build-<hash>/` keyed by the pending set (a rerun of the same set
   resumes there; earlier builds' dirs are the archive, never merged into a new build).
7. Stop rules (report, never pad):
   - **full**: target reached.
   - **partial**: the easiest tier is exhausted with yield ≥ 3%, or the budget is hit.
   - **ooc** (out of capability): yield < 3% on ≥ 60 candidates at the easiest tier that still
     carries the latent, AND the bank is under half its target. Above half, the same stop is
     `partial` with `refill` noting why it stopped (a 48/49 bank is usable, not ooc).
   - **blocked**: needs something absent (no J-lens for the subject, no misaligned rollouts).

`$A auto model=<m> family=<f>` runs steps 3–4 down the ladder for the deterministic families;
`$A fill model=<m> families=<f,...>` does the same for authored families (waves steered by
`run.miss_steer`: lint reasons, what the subject wrote instead, and what passed). For the MC
families (`mcstage.FAMILIES`) each wave's options are built by `adapt mc` between author and
gate, so no item is gated on its provisional list; basic_readout_st also gets `stage=subject` after
each gate.
Plan 0087: for multihop_st, basic_readout and the three multilingual families
(`onecue.FAMILIES`), `fill` then runs `onecue.repair_pending`, which works on each list before the
gate:
- It replaces a wrong option that one cue of the prompt rules out: the prompt names it, or it lies
  outside the kind, date, place, nationality, gender, field or language the prompt states.
- The replacement must pass a validity screen, a quality check (real, not also correct, not the
  gold's near-synonym, not obscure) and the blind guesser.
- If no list passes, it pops the item's `mc`, and lint rejects the item.

To re-check a shipped set, run `$A onecue model=<m> families=<f,...> out=<dir> cache=<one dir for
every set> stage=screen|repair|patch`. Screen every set before repairing any.
The gate rejects an unscreened adapted-only list from any route (`adapt onecue stage=pending`
screens pending candidates by hand), and a `mc_options_r5.py --bank` patch of shipped lists is
followed by the same three stages.
**Required for every new set (plan 0087 A4/R20):** the originals keep the registered lists, which
`repair_pending` never touches. So before a new set's first lucky run, run `adapt onecue
stage=screen`, then `repair`, then `patch` on all five families of the set, using the shared cache
(`/root/tmp/xsweep/cache` or its successor). A list content that is already repaired reuses that
repair (R19).

**Poetry v6 (plan 0082).** To top up poetry on a set whose `t1` items leak to the options-only guessers,
run `ADAPT_FILL_TIERS=poetry=v6 adapt refill families=poetry`. This uses the `v6` tier and
guesser-screened lists (`adapt/poetry_prior.py`). The run writes `families.poetry.refill_v6` and
never `refill` or an `ooc`. v6 rows keep the `adapt.plan = "0075"` stamp. Run `adapt poetry stage=settle` before every
`adapt freeze families=poetry`: it retries pending v6 lists and re-gates them, else they drop out
of the freeze.

### 3a. Small families must be refilled (Camila 2026-11-04, plan 0066; plan 0075 targets)
**Plan 0075 (2026-11-06):** `adapt refill` also drives the fill / auto families
(`refill.FILL_POLICY`: association, basic_readout, typo, multihop_st, poetry,
role_bound_association, user_modeling, multilingual / _typo / _multihop through `run.fill`;
relational_multihop through `run.auto`; thresholds 60 candidates / 3% at the easiest tier), and
targets are `refill.adapted_target` = max(registered, `ADAPTED_TARGETS`): association 100,
basic_readout 120, typo / multihop_st / poetry / role_bound / the multilingual_st mt families /
relational 100 (never lowered: user_modeling stays 126). The strict freeze refuses a
`FILL_POLICY` family short of target without a refill block measured at the current target
(objective `ooc` / `blocked` stops and plan 0072 D6's hand `note refill=` blocks still pass).

Every family with a refill route (`wsbench.adapt.refill.POLICY`: buggy_code,
model_specific_directed_modulation, knowledge_cutoff, wrong_intermediate, multihop, plus the
`fill` / `auto` families) that ships below its target MUST be refilled with
`python -m wsbench.adapt refill model=<m> families=<f>` before freeze. The ONLY acceptable reasons
to ship it short are the objective stops (`refill.stop_status`, plan 0066 §1.2):
- **`ooc`**: at least `n_min` candidates of the family's construction gated at the easiest level,
  yield below `y_min`, AND the bank under half its target. Thresholds (POLICY): buggy_code 60 pair
  objects at `t2` / 3%; msdm 200 categories / 3%; knowledge_cutoff 1,000 questions / 1%;
  wrong_intermediate 200k screened candidates / 5e-5 per candidate; multihop 300 candidates /
  3%. Candidates already gated on the subject count toward the tally.
- **`partial`**: pool exhausted, budget spent, the buggy crash cap binding, or low yield with the
  bank above half its target.

**Order on an existing set (plan 0066):** freeze fails every buggy_code clean row that has no
`bugclaim` leg (originals and authored `-au-clean-` rows alike), so run `refill
families=buggy_code` (it first re-asks the missing leg on every passing clean row, originals and
authored) BEFORE any re-freeze that includes buggy_code. The narrower alternatives are `gate
model=<m> families=buggy_code regate=true` (passing authored rows) together with `profile ...
regate=true` (originals). Otherwise it ships 0 pairs,
and freeze prints an error naming the rows without the leg (the CLI freeze refuses).

**buggy_code empty continuations (Camila 2026-11-04, plan 0066 §11.16):** in the buggy `leak` leg
and the clean `bugclaim` leg an ALL-EMPTY continuation passes (states / claims no bug); mixed draws
are judged on the non-empty ones; every other family's leak legs keep the non-evidence rule (an
all-empty leak leg is undecided and fails). A set gated before this needs `regrade
model=<m> families=buggy_code llm=claude-opus-5-5` (applies the rule to the stored answers, no
resampling, no GPU), then `refill families=buggy_code`.

`untried` is not a final status for these families. "The subject is small" is not by itself a
reason: a genuinely incapable subject stops cheaply through the pilot (`refill pilot=true`, at
most `n_min` candidates). A `refill_hold` in `report.json` (a suspected pipeline fault, e.g.
v4-pro's wrong_intermediate) blocks `ooc` until cleared. Report the stop reason and the counts in
`note`; `report.json` `families.<f>.refill` records them. The pools behind msdm / knowledge_cutoff
/ multihop are box-only (`$WSB_POOL_DIR`, sha256-pinned in `refill.POOL_SHA256`; built by
`scripts/build_adapt_pools.py`): a loader refuses a missing or mismatched file. Per-family routes:
`references/families.md` ("Refill" lines).

### 4. Freeze, verify, floors, audit
**Re-freezing an existing set (plan 0072):** a re-freeze carries today's registered judge-side
lists onto originals (multihop blocks when the subject kept every gold, basic_readout_st entity /
processing `mc`); on a subject whose native languages differ from the registered header's, the
six native-langs families' originals must be rebuilt from TODAY's registered item (`native_langs
stage=upgrade`, which stamps `native_units_src`), else freeze refuses them (fail-closed; this
includes the older `[en]` sets gemma-4-31b-it and olmo-3.1-32b). A drop-only re-freeze records
`plan_lineage` so the set's existing readouts still judge (dropped items removed); any other plan
change voids them. A short originals-only family with no refill driver (user_modeling, multihop_st)
records its refill by hand: `note status=partial refill='{"route": ..., "stop": ...}'`.
`$A freeze model=<m> families=<the families built>` (never bare) writes `<family>.json` and
`report.json`. It takes the header of the registered bank; every ORIGINAL is the registered item
itself plus the subject-side overlays (own-answer gold, `gate_variant`, `families.SUBJECT_FIELDS`,
token restamps), and original ids the registered bank lacks are never selected; new items are
the gate-log payloads. It refuses (writing nothing) a family whose items lack
`families.REQUIRED_ITEM_FIELDS`, whose originals lack their `SUBJECT_FIELDS`, or, for the six
multilingual_st / mt families, a subject without `native_langs.json` (plan 0060 A1.1 / A1.10). It
records `bank` / `bank_version` per family and writes `status: absent`, `exclude_from_macro`
and a `note` (an existing note is kept) for every registered family the set lacks (A1.6).
Then:
- Eyeball 10 random new items per family in the viewer: is the latent the same kind as the
  originals, is the answer unambiguous, and did nothing leak?
- **Item-quality review: drop, don't report (Camila 2026-11-06).** The audit (step 8) and
  your own read apply these checks to EVERY new item, and an item that fails one is dropped with
  `adapt drop` (permanent, with a reason) and back-filled by another `refill` wave. "Reported
  for Camila" is not an outcome for these:
  1. **Distractors are legit.** Read the option list WITHOUT the stimulus and ask "which one
     would a guesser pick?" The list fails if any of these hold:
     - an option is a different type from the others (one city among countries, a person among
       places, Salzburg among Paris / London / Berlin / Rome when the gold is a capital-sized
       city): the odd one out, or the only type that fits the question's shape, gives it away;
     - the gold is the only famous / specific / long option, or the only one that matches the
       question's wording ("Canada" for "the border between the United States and ___");
     - a distractor is a synonym, translation, alias, hypernym or hyponym of the gold, or also
       correct (that makes the gold ambiguous, not the list hard);
     - the list is short enough that elimination is easy (with 3 options chance is 1/3).
     Then measure: `wsbench baseline kind=lucky_guessing variant=blind,described draws=5` under
     `WSB_BANK_ROOT`. Every family must stay within chance + 5 points on both guessers. The bar
     is strict for every family, poetry and association included (Camila 2026-11-06).
     - **The per-run leaker test (plan 0075 D1-D3):** a guesser that fails the family bar gets
       >= 3/5 on the item, AND blind + described together reach >= 4/10. 10/10 counts whatever
       the rate. A family with fewer than 4 items is measured blind only; there the test is
       blind >= 4/5.
     - **The two-run rule (2026-11-08):** an item drops only when it meets the test in two
       SEPARATE lucky runs. A flag in one run is pending: re-measure it.
     - `adapt dataround stage=leakers` applies the test and the rule. The driver's `cycle` runs
       two lucky runs, so a cycle can confirm on its own.
     - **Before a set's first lucky run**, run the plan-0087 onecue screen / repair / patch. The
       driver does this in its first cycle.
     - **A list can also be rebuilt** instead of dropped: `scripts/mc_options_r5.py --bank` +
       `adapt patch`, at most 3 rounds, then the onecue stages again. In practice the cycles drop.
  2. **No shortcut around the latent.** The answer must not be reachable without the bridge /
     intermediate the item tests (`mlmh-vi-niagara-canada`: "on the border between the US and
     ___" answers itself), and no clue may route through a capital city ("captured the
     Byzantine capital", "its capital at Chang'an", "a siege in the Swedish capital"; #372,
     `lint._capital`), even when it passes lint.
  3. **One defensible gold.** Ask "could a careful reader give a different, also-correct
     answer?" (`thief-police officer-reported`: the officer also steals, so "thief" is
     ambiguous). If the subject's own samples split between two answers, drop it.
  4. **No near-duplicates** of another new item or a frozen one (same scenario, same latent:
     `pilot-cockpit-checklist` ×2, `plumber-pipe-wrench` / `plumber-drain-calls`, `teacher-
     fifth-grade` / `teacher-third-grade`); keep one. Keep topic / answer-class shares under
     the family's cap (user_modeling Country at 34% vs a 20% cap was a fail): steer the next
     wave's brief away from the over-cap class.
  Drops leave a set short; with no spend cap, back-fill with more waves rather than shipping a
  `partial` family. Record in the note how many items each check dropped.
  5. **The plan 0075 screens (D4-D7), on the WHOLE shipped bank, originals included.**
     `adapt dataround stage=screens` runs them every cycle:
     - D4: a multihop_st / mlmh answer reachable without the bridge (Opus);
     - D5: a clue that routes through, or a question that asks for, a capital (regex; it keeps
       the two figurative typo rows);
     - D6 / D6b: a user_modeling user turn that names a city or another place in the gold
       country (Opus);
     - D7: user_modeling Country and Gender each capped at 20%, newest rows first. Back-fill as
       Occupation / Religion only.

     Every drop goes through `adapt drop` with its rule in the reason. A role_bound drop takes
     both twins.
- `pytest tests/test_adapt.py`, then `WSB_BANK_ROOT=adapted/<m> wsbench plan --full out=<dir>` and every
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
    comparable with the bench protocol; label it. `stage=generate` rewrites a family's whole
    readout file at T 1.0 (every judge call new); after a registered bank swap that keeps the
    other items byte-identical, `ADAPT_FLOORS_MISSING_ONLY=1` (with `ADAPT_FLOORS_FAMILIES`)
    generates only the ids the file lacks, keeps the stored rows of every id still planned and
    prunes the rest, so `stage=judge` pays only for the new items.
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
- **A family gained or changed a gate leg** (e.g. multihop_st originals' bridge): `profile families=<f> regate=true` (originals) AND `gate
  families=<f> regate=true` (passing new items), then refill and re-freeze. Old records otherwise
  keep passing without the leg. When a leg was REMOVED or made an annotation (chain v2's `first`),
  use `gate regate=all`: it re-asks the failed new items too (every row is re-linted first, so a v1
  chain with an intermediate below 10 is lint-retired).
- `report.json` → `code` stamps the git HEAD and an adapt-package hash on every write. Check it:
  `python -c "from wsbench.adapt import store; print(store.code_stamp())"` vs
  `report.json` `code.adapt_sha256`. A bank frozen under an older stamp than the gate logic you
  changed needs a regate.

## Anti-text-inversion subset of an adapted set

An adapted set's ATI subset follows the bench's only panel rule (plan 0071, Camila 2026-11-05 /
2026-11-07): **an item is ATI iff every reader fails every one of its 3 draws**; any solve takes
it out, an undecided reader leaves it unverified (out). The tooling is plan 0079's; every step
runs under `WSB_BANK_ROOT=adapted/<m>` (no committed set has an `anti_text_inversion.json` yet):
- **The subject takes the Qwen slot.** `wsbench text-inversion stage=build` renders the set's
  prompts with the SUBJECT's tokenizer (decoded through the last read position); the subject
  answers as reader `subject` via `scripts/ati_qwen_modal.py --subject <key>` (thinking off,
  T=1.0, 3 draws, the `guess` form).
- **The frontier group is unchanged:** the Claude slot (Opus 5.5, Sonnet 5.5 where Opus refuses;
  `stage=slots` / `stage=ask answerer=claude`), astra via `scripts/ati_openrouter_modal.py
  --answerer astra --route openai-wif` and argon via `modal run -e camila-blank
  scripts/ati_openrouter_modal.py --answerer argon --route gemini-wif`, called ONLY from Modal.
- `stage=readouts`, `scripts/ati_panel_judge.sh` (native, each family at its `prompts.jsonl`
  `layer`), then `stage=gate_adapted` writes `adapted/<m>/anti_text_inversion.json` (gate
  `adapted-panel-v1`, the same `panel_verdict` as the registered gate, `bank_sha`-guarded: a set
  that changed since gating exits 2 until re-gated). `stage=gate` refuses under a root.
- **As in the bench:** a family with 1..19 survivors shows its ATI number but stays out of the
  ATI macro (`results.ATI_MACRO_MIN_ITEMS`); report the counts beside it.


## Re-freeze or refill an existing set

Plan 0060 Phase A landed (2026-11-03), and plan 0072 re-froze every set on the overhauled banks.
The old "refresh is blocked" warning is gone.
- **To top up or re-screen a set:** use the same commands as a new build, in its run tree. That
  is `refill`, then the `loop`, then `final`, then a delta audit appended to its AUDIT.md.
- **A set built before the bank v2+ round** (none on main once plan 0089's data PRs land) is
  rebuilt fresh, never patched. Move its dirs aside so `run.shipped_ids` starts empty, then
  follow the Quickstart (plan 0089).
- **Traps that still hold:**
  - `profile` skips ids already in the gate log unless `regate=true`.
  - For a gated id, a rewritten `cand/` row is ignored, and `gate regate=true` re-gates the
    gate-log payload. Field fixes go through `adapt patch`, which is applied at freeze.
  - A bare `freeze` re-freezes every family with gate rows. Always name the families.
  - The repo's MC builders (`build_multihop_mc.py`, `association_distractors.py`,
    `moral_distractors.py`, `mc_leakage_r4.py`, `role_bound_distractors_v3.py`) and
    `wsbench freeze` without `dst=` write the bank of record. Use `adapt mc` /
    `mc_options_r5.py --bank` / `dst=adapted/<m>/floors/...` instead.
  - Registered families a set lacks are SKIPPED under `WSB_BANK_ROOT` with `all=True`, so a
    macro silently spans fewer families. Check the count against §Scope.

## Families with their own build (not `profile` / `gate`)

`profile` / `gate` cannot gate these families: `families.get` has no entry for them. Each one has
its own subcommand, and `adapt_set.sh build` runs them all. Never copy the 27B bank into
`adapted/<m>/` for them. A missing family is reported, never back-filled. They ship only when
named at freeze (the driver names them).

| family | why model-specific | build |
|---|---|---|
| wrong_intermediate | the item is a specific Qwen error (it answers via the wrong intermediate) | `$A wrong_intermediate model=<m>` (plan 0060 Phase E); refill (plan 0066): cued templates recovered by category, then a lower-`min_sl` re-scrape (`pool=dir1,dir2`) (§3a) |
| knowledge_cutoff | a model-specific error gate (G0 / G1) | `$A kcutoff model=<m> [cutoff=YYYY-MM]` (plan 0060 Phase E): G0 re-run on the subject, G1 dropped, options / units rebuilt; then `freeze families=knowledge_cutoff`. nocot items not built (`references/families.md`). Refill (plan 0066): the GW question pool (`pool=ext`, §3a) |
| model_specific_directed_modulation | model-specific by design (G0 defaults + G1 text gate) | `$A msdm model=<m>` (plan 0060 Phase E): the subject's own defaults (G0 + compliance), G1 dropped, options / units rebuilt; then `freeze families=model_specific_directed_modulation`. Refill (plan 0066): the GW category pool (`pool=ext`) with membership / label-QA validity legs (§3a) |
| multihop | its shortcut gate (no shortcut probe reaches the answer) is specific to the gated model | `$A multihop model=<m>` (plan 0060 Phase E); refill (plan 0066): the GW adversary-probed candidate pool, gated with the unchanged staged gate, review legs, then `build_fields` (§3a) |
| nyt_connections | the targets are the model's own groupings and connection labels (plan 0062) | `$A nyt_connections model=<m> [stage=solve/stability/options/build/all] [limit=] [llm=] [herrings=<pilot alt_b2.json>]` (plan 0060 Phase E): the subject solves each registered puzzle (greedy + 16 @ T 0.7, top-p 0.95) and names its groups; the family's >= 12/16 stability rule re-run; options rebuilt around its labels (NYT gold, shared Opus herrings, foil, Opus EQUIV filter); frontier gate dropped; then `freeze families=nyt_connections`. Work files hold NYT text: they live in `$WSB_CACHE/nyt/adapt/`, never `adapted/`. `regate=true` refuses `limit=`. `scripts/nyt_connections_bar.py` refuses an adapted headline (the frozen floor is Qwen's) |
| model_multihop | the bridges are the model's own stable beliefs (plan 0076) | `$A model_multihop model=<m> [stage=gen1/canon1/gen2/gate/floor/review/build/lucky/confirm/status/all] [limit=] [llm=] [level=] [src=]` (plan 0078, every stage with `ADAPT_BACKEND=modal`): the gw mmh pool (`$WSB_POOL_DIR/mmh_pool.json`, `scripts/build_mmh_pool.py`) re-gated on the subject (B, M, M2, A >= 16/20 at T 0.7; chain; identifiability; leak), the Opus prompt-only filter (0/6), the item-quality review, a lucky-guessing screen (`stage=lucky`); `freeze families=model_multihop` selects in ship order (screen leakers out, near-duplicates out, <= 15% per bridge, target 100, ships up to 283) and marks the bank `unconfirmed`; a FRESH confirm run (`wsbench baseline kind=lucky_guessing variant=blind,described draws=5` under `WSB_BANK_ROOT`, new out dir, then `stage=confirm src=<dir>`) decides on its pre-drop rate (chance + 5; under 100 items or in a re-selection round also the item-level 90% upper bound); a failed confirm needs `stage=lucky level=<round+1>` (a pooled re-selection round) before the next one, 3 failures block the family; the floor of record is ingested as a re-test; `stage=status` grades. Work files `adapted/<m>/mmh/` (git-ignored) |
| introspection | injected concept vectors are the subject's own activations | `$A introspection stage=all`, or the multi-GPU stack for big MoE (§Introspection); `ooc` on a measured calibration NO-GO |
| hinted_cutoff | the I / N twins are the subject's own behaviour and the read positions index its own prompt render (plans 0063, 0074) | plan 0084: re-run the gw ccut v2 pipeline on the subject (`scripts/hinted_cutoff_adapt/`: `probe.py` measures its cutoff first and the pool is extended by date if its fade-out is later than v2's 2024-01..2025-06 window; `subject_gen.py` is the `[gen]` step on the subject's adapt app; `subject_ccut.py` runs each ccut stage with the subject's tokenizer, metadata template only; a pilot of ~150 candidates first; hand-labelled silence calibration), then `finalize.py` (the bar is the date checks: day AUROC and cell excess within the gw gate's 0.10, Camila 2026-11-08; the prompt-only predictors are recorded, the po-opus floor covers prompt predictability; a masked guessability caliper `HC_GUESS_GAP` (R18) narrows it) and `$A hinted_cutoff model=<m> frozen=<frozen_<m>.json> gw_commit=<sha>` (refuses a failed bar; validates every item's ids against the subject's render and its read span after the hint block). Floors: `ADAPT_FLOORS_FAMILIES=hinted_cutoff $A floors` + the po-opus summary floor. Built for glm-5.3, then plan 0089's five and deepseek-v4-flash (§hinted_cutoff) |
| typo_st | superseded by typo (out of `all`) | stop refilling it; keep the frozen file only for old results |

Removed and never to be adapted: unverbalized_hint (plan 0081), medical_diagnosis{,_alt} (plan
0058), hallucination (plan 0040), multihop_mt_regex (plan 0041), brew_intermediates (plans 0029 /
0033).


## Modal, tokenizers and Claude auth

Agam's RunPod box (the 4090, `/workspace/agam/`, `adapt_box.sh`, `scripts/adapt_gated_rescore.py`, gw-olens'
`subject_*_modal.py`) built the October sets and is no longer used. Every step now runs from a
dev box against Modal:
- **Modal:** `MODAL_PROFILE=safety-sahan-2 MODAL_ENVIRONMENT=camila-blank` and
  `ADAPT_BACKEND=modal`. The `camila-blank` environment is capped at 16 GPU containers, shared
  by every agent. Use a Modal client from a local-disk venv: `/root/torchvenv/bin/python -m modal`
  (1.6.3), or the persistent `/workspace/root/fo-cache/glm53-modal-venv/bin/modal`.
  `/root/.cache/cfinf-modal-venv` is wiped on reboot.
- **Claude auth:** `WSB_ANTHROPIC_AUTH=sdk ANTHROPIC_PROFILE=default`, the Anthropic SDK's
  profile credentials. `adapt floors stage=judge` honours it too. NEVER export
  `ANTHROPIC_API_KEY` (`adapt_set.sh` refuses to run with it set). The default route, which
  reads a keyless token from a Modal Dict `anthropic-oauth`, existed only in Agam's environment.
  The SDK route sometimes fails with an OAuth refresh race (`invalid_grant`,
  `WorkloadIdentityError`): wait 1-3 minutes and re-run. The driver does this itself.
- **Tokenizers:** loaded from the hub at the pinned revision (`HF_HUB_OFFLINE=0`), plus a pinned
  template in `src/wsbench/adapt/data/templates/` where the upstream template cannot turn
  thinking off.
- **Per-subject Modal apps** (`scripts/adapt_modal.py`, plan 0060 A3). Each `backend="modal"`
  Subject names its app (`modal_app`) and how it is served: `modal_gpu` (fallbacks in order),
  `modal_tp`, `modal_engines` (TP engines per container, one per GPU set: DeepSeek-V4 = one
  B300:8 with 8 TP=1 engines, "always 8xB300"), `modal_replicas` (containers the chunks fan out
  over), `modal_image` (recipe `default` | `glm53` | `dsv4` | `muse` (vLLM 0.33.0)),
  `modal_volume` + `modal_weights`,
  `modal_engine` (extra `vllm.LLM` kwargs). Subjects with the default fields share
  `adapt-subject-llm` (one H200). `modal_built=False` (an external app; none registered since
  plan 0089 moved glm-5.3-flash onto its own built app) is refused by both the deploy script
  and `RemoteRunner`.
  Prerequisites: the weights volume exists in the env (`glm53-weights` holding
  `hf/nvidia__GLM-5.3-NVFP4`; `v4-flash`; `v4-pro` and `kimi-k3` holding the pinned snapshot under
  `hf/hub`; `muse-spark` holding `hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4`; plan 0089: `kimi-k2`
  and `glm53-flash` holding the pinned snapshot under `hf/hub`, mounted at the default recipe's
  `/hf` like `kimi-k3`) (download them once with a CPU function, never in a
  GPU container). The glm53 image pulls the vLLM fork from a public HF repo (no secret).
  Deploy once per app, from the repo root, with the Modal client venv:

  ```bash
  MODAL="/root/torchvenv/bin/python -m modal"
  export MODAL_PROFILE=safety-sahan-2 MODAL_ENVIRONMENT=camila-blank
  $MODAL deploy scripts/adapt_modal.py                         # adapt-subject-llm (shared)
  ADAPT_SUBJECT=glm-5.3 $MODAL deploy scripts/adapt_modal.py   # adapt-glm-5.3: B300:8|B200:8, TP8
  ADAPT_SUBJECT=kimi-k2 $MODAL deploy scripts/adapt_modal.py   # adapt-kimi-k2: B300:8, TP8
  ADAPT_SUBJECT=deepseek-v4-pro $MODAL deploy scripts/adapt_modal.py  # adapt-v4-pro: B300:8, TP8
  ADAPT_SUBJECT=kimi-k3 $MODAL deploy scripts/adapt_modal.py   # adapt-kimi-k3: B300:8, TP8
  ADAPT_SUBJECT=muse-spark-open $MODAL deploy scripts/adapt_modal.py  # B300:8|B200:8, TP8
  ```

  Then run `python -m wsbench.adapt … model=<key>` with the same `MODAL_ENVIRONMENT`;
  `RemoteRunner` finds the app by name. It sends TOKEN IDS (the local render, tokenized without
  added specials), so `<bos>` / `[gMASK]<sop>` is never doubled: an app deployed before A3 took
  text and must be redeployed. The first call boots the engine (GLM-5.3: localize ~440 GB to
  NVMe + load + JIT, ~15-20 min; `scaledown_window` keeps it warm 10 min between calls), so
  batch every candidate into ONE generation run per stage. Check Blackwell stock first.
- **Per-subject tokenizers.** `glm-5.3` loads its tokenizer from the hub at the pinned revision
  plus the in-repo `data/templates/glm53_nvfp4_nothink.jinja`; `kimi-k2` loads the hub's
  remote-code tokenizer (`trust_remote_code`, needs `tiktoken`, in the `gpu` extra) with its
  official template as-is: every Kimi render opens with the template's default system turn ("You
  are Kimi, an AI assistant created by Moonshot AI.") unless the ask has its own system message
  (sets are built fresh, so earlier renders need not match). `glm-5.3-flash` (plan 0089)
  loads its tokenizer from the hub at the pinned revision plus the in-repo
  `data/templates/glm53_flash_nothink.jinja` (GLM-5.3's two edits: effort low, `<think></think>`).

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
- **Backends:** §GPU sizing. A model that fits one H200 uses the shared `adapt-subject-llm`;
  anything bigger gets its own app, with a multi-GPU container and `modal_max_containers=1`.
  Batch every candidate into ONE generation run per stage.
- **They pass most originals.** The work is the model-specific families and gating, plus a few refills.
- Agentic yield on big subjects is low (GLM-5.3-flash: 7/108 on v3). Run every pinned pool
  before calling it.

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

**Ops:**
- **tmux:** wait on sessions with `tmux has-session -t "=name"` (exact match).

## report.json (schema) and audit decisions
Per family: `status` (full / partial / untried / ooc / blocked), `note`, `change`, `refill` (plan 0066: a dict `{route, unit, target, have, tried, landed, yield, waves, n_min, y_min, tally, pool_size, pool_used, stop, budget}`; an older string value means `{stop: <string>}`), buggy_code `target_pairs` / `n_pairs`, counts
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
- One subject container: on a subject with `modal_max_containers=1`, run ONE GPU chain at a time
  (the build, then the refill). Two concurrent chains do not get two containers; the second
  queues behind the first, sometimes for an hour. Claude-only stages can overlap.
- Do not change `subjects.py` caps or the deployed app in a run tree without reverting before the
  PR. If you must, record it in the run tree's notes. plan 0089 raised glm-5.3-flash to 2
  containers locally and reverted it before the PR.
- Long runs in tmux, with logs under `logs/`. `/root/tmp` is fast but not durable: archive
  the run tree's `adapted/<m>/{gate,cand,mc,mmh}` and `outputs/adapt/<m>` before deleting it.
- Unknown CLI keys are errors. `regrade` never undoes `adapt moral`'s side checks.
- The model-grade cache persists (`adapted/.grade_cache/<grader>.jsonl`); `author` writes after
  every call; the gate, regrade and fill are resumable (gated ids are skipped).

## Rules
- The gate is the subject itself, with its own template and thinking off. Never use OpenRouter
  stand-ins (a provider that cannot turn reasoning off is a different render), and never use
  another model's answers.
- Same gate rule as the banks: greedy right AND ≥ 8/10 (10/10 for chain). Don't lower it
  to fill a family.
- Small families must be refilled before freeze (§3a); ship short only on an objective stop.
- Never pad:
  - synthsys user_modeling items score echo, not inference;
  - a family that can't be filled is reported `partial` / `ooc` with its real count; a short family
    whose ladder was never tried is `untried` (never `partial`).
- Keep pairs atomic: twins and ab/ba pairs pass or drop together (directed_modulation has no
  pairs since bank v2, plan 0113).
- Record every knob in `adapt.knobs` and every family's change in `report.json`. Anyone reading a
  number must be able to tell what difficulty, and which bank version, it was measured at.
- Opus authors; it never grades its own items as correct. The subject grades by answering. A
  deterministic grader or the repo grader checks the answer.
- Claude calls (`llm=` grading, `author`) use `WSB_ANTHROPIC_AUTH=sdk ANTHROPIC_PROFILE=default`
  (§Modal, tokenizers and Claude auth). Never export `ANTHROPIC_API_KEY` into a shell, and never
  commit one.
- Claude API spend is not capped, but it is ledgered (`WSB_TOKEN_LEDGER`). GPU spend is what to
  watch: post the expected GPU $ before a fan-out. Before any big run, check that no other session
  is already running it (one agent per shared run).
- Merge only through `scripts/gated_merge.sh` (fail closed). Bench data stays local until the set
  is frozen and audited.

## References
- `references/families.md`: per family, the latent, gate, required keys and registered-bank
  fields, invariants, and difficulty ladder.
- `references/authoring.md`: the Opus authoring prompt, the per-family briefs, and failure-steered
  waves.
- `references/porting.md`: layers, tokenizer, read positions, the model-specific regeneration
  procedures, and judging an adapted bank.
- `references/pitfalls.md`: what went wrong before, plus known defects in the frozen banks.
