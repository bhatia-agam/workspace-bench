# 0071: a frozen logit-lens final-layer (L63) floor

(Plan number 0071 is shared with `0071-ati-all-readers-fail.md`, written on main the same week;
this one is cited as "plan 0071 (logit-lens floor)".)

Issue #352. Decision: Camila, 2026-11-05, as the issue records it: "can you also include a logit
lens L60 baseline ... and ship this to the repo as an official baseline"; then, the same day,
before the PR opened: "make the logit lens baseline final layer, not L60" and "let's officially
replace this". The floor of record is therefore layer 63, the output of the last of
Qwen3.6-27B's 64 blocks; the L60 version (0.130 full / 0.100 ATI) was never merged and is kept
only as a reference number.

**Superseded text.** The sections down to "Checks" are the plan as written for the first freeze
(2026-11-05, synced 2026-11-07). Where they describe the committed file, its numbers, its `ati`
attachment, its `_source` or the freeze guard, the section "2026-11-17 port onto main" and its
"Review fixes" list at the end are the current statement; each superseded passage is marked.

## What it is

The plainest token readout of Qwen3.6-27B's residual stream: the bench's own
`wsbench.produce.methods.LogitLens` (`W_U · final_norm(h)`, the model's own final norm module and
unembedding, no artifact, top-10 tokens) read at **layer 63 only** (the final block: the readout is the model's own next-token
distribution at each read position), at every plan cell of every
family, then judged by each family's own **summary** instrument exactly like a lens's single-layer
row (`layers=63`). A lens's per-family score can be read against it the way it is read against the
prompt-only floor: what does reading the activation with no learned reader already give?

It is a floor beside the existing two (lucky guessing, prompt-only), not a gate: nothing is
excluded or rescaled by it, and it never enters the macro.

## Frozen file: `evals/baselines/logit_lens.json`

- `_source`: `protocol` = `logit-lens-L63-v1`, `method` = `logit_lens`, `layer` = 63, `k` = 10,
  `sampling` = `tokens10` (written by `freeze`), then the generation record's `model`
  (`Qwen/Qwen3.6-27B`), `producer`, `bench`, `verified` and `measured`. *(First freeze: `bench`
  listed the SHA each family's readouts were planned at, 0b7cba39 / 7285f7d8 / 675867259. Since
  the 2026-11-17 refreeze it names the main commit every family was judged at, 23966deb, and the
  one family read through a plan lineage.)* A `partial=True` freeze adds `kept_from`.
- one entry per family (29: 26 of the v1.0.0 core families, multihop_mt (the former
  `multihop_mt_v2` key), nyt_connections, hinted_cutoff; jlens_concept_pr excluded as for
  prompt-only, the superseded `typo` and model_multihop absent), in the **same schema as a summary
  prompt-only entry** (`rate`, `saturated`, `ci95`, `metric`, `higher_is_better`, `n_items`,
  `n_items_decided`, `counts`, `judge_model`, `instrument`, `layers_judged` = `[63]`, `complete`,
  `aggregate` = `summary`, `summarizer`, `decided`, `digest_unserved`, `written`), plus
  `protocol`, `plan_sha` (main's read plan, when frozen with `readouts=`) and, where the family
  has an ATI run, `ati` = `{rate, ci95, n_items, n_items_decided, complete, instrument}`
  (`logit_lens.ATI_KEYS`: the bench's own `anti_text_inversion=True` scoring of the same judged
  cells; a cache replay, zero calls). *(First freeze: `ati` on 13 families of the earlier gate.
  Now: on the 7 families of the frozen `ati-subset-v2` macro that have an entry.)*
- No macro is stored: the floor never enters the macro. The README records the raw-mean averages
  for reference: **0.121** full set, **0.046** strict ATI (7 families). *(First freeze: 0.082 /
  0.052.)*

*(Superseded: the check below was the prompt-only freeze check, a base-prefix match; it is now
the full live stamp, see "Review fixes".)* An entry is frozen only when its judged
`prompt_version` is the family's CURRENT summary instrument (the prompt-only freeze check,
reused): the families whose instrument moved after
v1.0.0 (#286: multihop_mt_v2 `xrole-v1`, wrong_intermediate `wbcues-v2`) are re-judged at main
from the same readouts (digests reused from the summary store) before freezing.

## Code

- Review fixes: freeze refuses a run whose `config.reader` is not a logit lens (`READERS`:
  `logit_lens`, the bundled producer's method name, or `logitlens-L63`, the wsb-bp arm) or that
  was read without a sidecar; `source=` is required with `protocol` = `logit-lens-L63-v1` and
  replaces `_source` wholesale (no stale provenance); `readouts=` checks each sidecar's reader and
  `plan_sha` against current main and records `plan_sha`; the library refuses under
  `$WSB_BANK_ROOT`; an incomplete entry's cell says so; both report legends name the floor; the
  column is hidden when no row can draw it.
- `src/wsbench/baselines/logit_lens.py` (new): `PROTOCOL`, `LAYER`, `K`, `FROZEN`;
  `freeze(src, ati_src, dst, source)` folds `src/<family>/results.json` (refused unless every run is
  summary mode, `layers_judged == [63]`, sampling `tokens10`, a full run — not `items` / `limit` —
  and on the family's current instrument) and `ati_src/<family>/results.json` (scope
  `anti_text_inversion`, same instrument) into the file; `floors()` returns the entries;
  `floor_applies(entry, config)` = `prompt_only.summary_floor_matches` (same instrument, digest
  settings and judge model), so the floor is drawn only beside a summary row that ran its
  instrument, exactly like the summary prompt-only floor. The entry builder is factored out of
  `prompt_only.freeze` (`entry_of(r, summary)`), behavior unchanged for prompt-only.
- `wsbench freeze kind=logit_lens src=<judged dir> ati_src=<ati dir> source=<run_config.json>`
  (registered banks only; under `$WSB_BANK_ROOT` it is refused with a clear message — adapted
  subjects get their own floor later).
- `wsbench report`: a third floor column `logit lens L63` whenever the frozen file has entries
  (summary rows: the frozen rate where the row ran the entry's instrument — the existing
  `results.summary_floor_applies` path, which the entry schema satisfies — else `—`; native rows:
  `—`, the floor is summary-mode only); `json=True` adds `floors.logit_lens`. The ATI branch keeps
  skipping every floor column, as today. `summary_floor_columns` reads the first two native
  columns by position (`list(native)[:2]`), so the lucky / prompt-only cells are unchanged.

## Reproduction (documented in `evals/baselines/README.md`)

```
uv run wsbench produce family=<f> method=logit_lens layers=63 out=<dir>/<f>.jsonl   # per family
uv run wsbench run all=True readouts_root=<dir> layers=63 out=<judged>
uv run wsbench run all=True readouts_root=<dir> layers=63 anti_text_inversion=True out=<ati>
uv run wsbench freeze kind=logit_lens src=<judged> ati_src=<ati> readouts=<dir> source=<run_config.json>
```

The committed numbers were produced by the wsb-bp Modal producer (the same `LogitLens.read` math,
batched; for the first freeze, cell positions verified identical to the J-lens arm's L60 cells,
as there is no J-lens L63). *(First freeze: judged with the frozen v1.0.0 instruments, current
main's for the two moved families. The committed file is the 2026-11-17 refreeze: every family
judged with main's instrument at 23966deb.)*

## Docs and version

README "Baselines" paragraph and an `evals/baselines/README.md` section (per-family table). No
version bump: no score, macro or instrument changes (the package stays 1.2.0).

## Tests

New `tests/test_logit_lens_floor.py`: freeze builds the entry schema from synthetic summary
results; refuses a native run, a run judged at another layer set, a subset run, a stale
instrument; `floor_applies` mirrors `summary_floor_matches`; the report draws the column beside a
matching summary row and `—` beside a native row; the committed file loads, has 29 families,
`layers_judged == [63]` everywhere and the `_source` protocol. No pre-existing test assertion
changes (the report-table tests that pin the column count get the new column only if they build
the table from the frozen files; any such update is listed in the PR).

## Checks

`ruff check`, `ruff format --check`, `pytest -q`.

## 2026-11-17 port onto main

The branch was last synced with main on 2026-11-07. Main moved 60 commits since, and the floor
was checked entry by entry against it before merging.

- **Staleness.** 24 of the 29 entries were no longer on their family's live summary instrument
  (`report` would not have drawn them; the freeze guard of the time, a base-prefix match, would
  have refused 23 of them and accepted one, conjunctive_association's `comp-v5+maj-noinv` run
  against the live `comp-v5+maj`, which is what the full-stamp guard under "Review fixes" closes); 8 of those were also on
  a bank whose read plan had moved (arithmetic_intermediates, basic_readout, basic_readout_mt,
  buggy_code, hinted_cutoff, multihop, multilingual, user_modeling), and `multihop_mt_v2` is now
  registered as `multihop_mt`. Only directed_modulation, knowledge_cutoff,
  model_specific_directed_modulation, nyt_connections and typo_mt still matched.
- **Refreeze.** All 29 families were re-judged at main 23966deb from L63 readouts of the same arm
  (`logitlens-L63`, producer d6fc56523): the 2026-11-05 cells for every item whose plan row is
  unchanged, and the cells the same arm produced on 2026-11-07 for the items later banks added or
  changed. No GPU work was needed: every plan item of every family has its cells. The judge and
  digest calls were all served from the caches of the 2026-11-17 re-score of that arm (bench
  7dc89c94 + #482), whose 29 values the run reproduces exactly, so no call was made. Every entry
  is complete (0 missing, 0 unjudged cells); the two incomplete entries of the first freeze
  (buggy_code, jailbreak_recognition) are gone.
- **Numbers.** Raw mean of the 29 entries **0.121** (was 0.082). Strict ATI **0.046** over 7
  families: the 8 of the frozen `ati-subset-v2` macro (plan 0085) minus model_multihop, which has
  no entry (was 0.052 over 13 families of the earlier gate). `ati` is attached only for those 7.
  The unchanged-instrument entry knowledge_cutoff still moved, 0.014 to 0.054: the digest
  token-split fix (#482) changes a token readout's digest without changing the stamp, which is
  why all 29 were re-run, not only the 24.
- **Code.** `logit_lens._plan_sha` accepts readouts of an older plan exactly as `reads` guard
  (iii) does, through the registered bank's recorded drop-only `plan_lineage`
  (`reads.lineage_drops`; plan 0083, arithmetic bank v1 to v2), and records main's `plan_sha`;
  any other plan difference is still refused. The merge with main needed one resolution, in
  `ReportRuns`: the logit-lens column is built from `floor_columns` / `summary_floor_columns`,
  which main now skips for ATI rows *and for fast-subset rows* (plan 0090), so the column is
  suppressed on both, like the other two floors; the hide-when-no-row-draws-it rule is retained.
  `entry_of` is still a verbatim move of main's entry builder.
- **Tests.** New in `tests/test_logit_lens_floor.py`:
  `test_every_committed_entry_matches_its_live_row` (registered, not superseded key; the full
  live stamp, digest settings and judge model, see "Review fixes"; the twin of the prompt-only
  `test_every_committed_floor_matches_its_live_row`), `test_every_committed_entry_is_on_the_registered_plan`
  (`plan_sha` equals `reads.plan_sha`; nyt_connections and knowledge_cutoff excepted, whose plans
  the test suite renders from synthetic text) and
  `test_freeze_accepts_a_recorded_drop_only_plan_lineage`. Both committed-file tests fail on the
  2026-11-05 file. No assertion of a test that exists on main changed.
- **Not done.** model_multihop has no entry: its only L63 logit-lens readouts are a conversion of
  another producer's grids (sidecar reader `gw-mmh-v2-logit`), which `freeze` refuses by design.
  An entry needs either `wsbench produce family=model_multihop method=logit_lens layers=63` (one
  GPU job) or a decision to admit that reader.

### Review fixes (2026-11-17, after an independent review of the port)

The 29 entries' values are unchanged by these.

1. **Never beside an adapted subject.** The floor is Qwen3.6-27B's own activations ("adapted
   subjects get their own floor later"), but `floor_applies` matched on stamp, digest settings
   and judge only, and an adapted row can carry all three unchanged (measured on real results: a
   Kimi-K3 single-layer model_specific_directed_modulation row matched the entry).
   `logit_lens.floor_applies` is now `on_registered_bank(config)` *and the summary prompt-only
   row match is retained* (`prompt_only.summary_floor_applies`, itself untouched: prompt-only
   floors draw exactly as before). `on_registered_bank` reads the signals the report already
   keys adapted sets on: `$WSB_BANK_ROOT` at report time (then there is no column at all), a
   re-stamped row's `config.registered_prompt_version`, and `config.bank_root`, which
   `runner.stamp_adapted_bank` now records on every result judged under a root. Remaining gap,
   stated in the docstring: an adapted `results.json` written before `config.bank_root` existed,
   not re-stamped, and reported with no `$WSB_BANK_ROOT`, carries no trace of its bank.
   `results.summary_floor_applies` dispatches a logit-lens entry (by its `protocol`) to
   `logit_lens.floor_applies`, and the hide-the-column check in `report` calls that same
   function, so the table and the check cannot disagree.
2. **The full live stamp.** The guard and the committed-file test compared the stamp's base
   prefix and digest tail, so a family-specific middle segment was unchecked
   (conjunctive_association `+maj`, model_specific_directed_modulation `+joined-…`,
   moral_rationale `+nq1+maj3v`, role_bound_association / user_modeling `+maj3v`).
   `logit_lens.live_config(family)` runs the family's own judge `dry_run` (no call) on an empty
   readouts file with this floor's sidecar and returns the config a live row carries;
   `live_instrument` is its stamp. `_check` refuses any run whose stamp is not exactly that, and
   the test compares the stamp, digest settings and judge model of every committed entry with it.
   Regression test: the `comp-v5+maj-noinv+digest-…` run is refused.
3. **`dry_run` refused; incomplete labelled.** `_check` refuses a `dry_run` run. An incomplete
   run stays freezable, scored on its judged items with `complete: false`; its cell now names
   missing cells (no readout) and unjudged cells separately (`incomplete: 3 missing, 2 unjudged`).
4. **Lineage tied to the run.** When the sidecar's plan differs from main's and is accepted
   through the bank's `plan_lineage`, the judged run's own `config.plan_lineage` (written by
   `reads` guard iii) must have `from` = the sidecar's sha and `to` = main's; a run that records
   a lineage is refused against readouts already on main's plan. A run on main's plan records no
   plan sha at all (no such field in `results.json`), so there the sidecar is tied to the run only
   by `config.reader` and the directory named; documented in `_plan_sha`.
5. **Partial freezes.** `_source` describes the run being frozen, so a `src` that would leave an
   existing entry in place is refused; `partial=True` keeps such entries and lists them under
   `_source.kept_from` with the record they were frozen under.
6. **Docs.** This file's superseded passages are marked; the issue's quote is given as written
   ("L60"); `evals/baselines/README.md` says what a final-layer readout is (the model's own
   output distribution over the read span, not a weak reader); `plans/README.md` indexes both
   plans numbered 0071.
