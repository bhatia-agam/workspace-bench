# 0061: `reads=lite` reads the full positions for the directed-modulation families, user_modeling and basic_readout

## Decision

Camila (2026-11-02): "for ALL directed modulation eval families lite should be the same positions
as normal. user modeling should also be the same, and basic readout."

The families, and the lite rule each has today:

| family | full positions (unchanged) | lite today | lite after |
|---|---|---|---|
| `directed_modulation` | every token of the teacher-forced carrier | `final_token` (the carrier's closing ".") | `same` |
| `model_specific_directed_modulation` (aliases `dm_category_default`, `directed_modulation_obscure`; its `nothink` / `alice` control rows, built from `readplan.plan(NAME)`) | every carrier token | `final_token` | `same` |
| `multi_concept_directed_modulation` | `last_n` = every token of the prefilled target sentence | `offset_from_end k=6` (the `' to'`) | `same` |
| `user_modeling` | `all` = every token of the chat_context render | `final_token` | `same` |
| `basic_readout` (every bank: the default `items_v5.json` rows `question_through_end`, and any bank whose rows take the `final_prompt_token` / `chat` paths) | unchanged per row | the bank row's `readout.lite`, else `final_token` | `same` |

`basic_readout_mt` is NOT in scope (it is a separate family; not named in the decision).

`same` = `reads=lite` selects exactly the `reads=full` cells, and `lite_layers = None` (every full
layer), as association (r2) and conjunctive_association (r3, #222) already do. A lite run then
differs from full only in its `+reads-lite` stamp.

## Changes

1. `src/wsbench/readplan.py`
   - New module constant `LITE_SAME_FAMILIES = ("basic_readout", "directed_modulation",
     "model_specific_directed_modulation", "multi_concept_directed_modulation", "user_modeling")`
     with a comment citing this plan and the decision. `SAME = {"kind": "same"}`.
   - `directed_modulation`, `model_specific_directed_modulation`,
     `multi_concept_directed_modulation`, `user_modeling` rows: `lite_positions=dict(SAME)`;
     `lite_layers` stays `None`. Their `positions`, `layers`, render, text/prefill/assistant/
     messages and `note` content describing the full read are unchanged; only the `note`'s lite
     clause is reworded ("lite = the same positions (plan 0061)").
   - `_final_token_families_items`: for `family in LITE_SAME_FAMILIES` every row's
     `lite_positions` is `dict(SAME)` on **all three** paths (`question_through_end`,
     `chat` prefill, plain), overriding the bank row's `readout.lite`. The other families on this
     path (`typo`, `wrong_bridge`) keep their current lite (`FINAL`, or the bank's `lite` for
     `wrong_bridge`'s `all_positions` rows) — **retained invariant**.
   - The bank files are NOT edited (their `readout.lite` keys stay as the historical record;
     the plan row is what the judge reads, never the bank).
   - **Retained invariant:** `plan_sha` is unchanged for every family (`reads.py` never hashes the
     lite site), so every existing full readouts file, its sidecar and the frozen FINAL64 inputs
     stay valid; no new reads are needed (lite was always a subset of full).
2. `src/wsbench/evals/multi_concept_directed_modulation/judge.py` `_windows`: `reads=lite` now
   takes the **full** path (write-cell region labels from the sentence window tokens, AND the
   write-compliance gate), exactly as `reads=full`. The `' to'`-cell check and its exit-2 are
   deleted, and `LITE_TOKEN` with them if nothing else uses it. The `prompt_only:` reader branch
   (one cell per item, every cell in-sentence, no compliance gate) is **retained unchanged**.
   Docstring updated.
3. `src/wsbench/reads.py` `load` (critique r1, r2): "lite is full" (`reads.lite_is_full(sp, ids)`)
   = the loaded id set is non-empty AND every loaded id has a plan row in `sp` with
   `lite_positions == {"kind": "same"}` and `lite_layers is None` (an unplanned id, or an empty
   `sp` from a failed `specs()`, makes it false: today's lite path). Such a run gets the
   **same completeness checks as `reads=full`**: `check_full` (sidecar file) / `_report_only`
   (sidecar-less) on the selected cells, so `partial_ids` / `partial_ids_unenforced` /
   `complete` match full. Before that (after the prompt_only early return and guard (i)), if the
   file has a sidecar (any `reads`), the family's `min_full_positions > 1`, and every (item,
   layer) holds one position, exit 2: "`<path>`: reads=lite with 1 position per cell, but this
   family's lite rule is `same` (lite = the full positions, plan 0061); the file was produced
   under a superseded lite rule — re-produce it, or judge the full file with reads=lite". This
   replaces the MCDM `' to'` guard and catches stale lite files for every `same` family,
   **including association, conjunctive_association and jlens_concept_pr** (intended: their lite
   is `same` too; jlens has `min_full_positions = 1`, so only its completeness accounting changes).
   `select` stays as is (identity for declared-lite files, rule applied once — **retained**);
   guard (i) (declared lite file under a full run) and guard (iii) (plan_sha drift) are
   **retained unchanged**. Families with any non-`same` lite rule keep today's lite behaviour
   exactly (no span check).
4. No other judge branches on `reads.mode == "lite"` for these families (checked: DM, MSDM, UM,
   basic_readout judges); digest / summary-mode code is untouched. The `+reads-lite` stamp
   (`reads.stamp`) is **retained**: lite results stay distinguishable from full.
5. `evals/baselines/lucky_guessing.json`: no change (none of these families has lite-specific
   floors; only conjunctive_association does).
6. Tests — the ONLY sanctioned edits to pre-existing tests (each asserts the old lite rule this
   plan replaces; the edit must assert the new rule, not delete the check):
   - `tests/test_directed_modulation.py::test_dm_lite_judges_final_carrier_token` → rename to
     `test_dm_lite_judges_full_carrier`; assert `spec.lite_positions == {"kind": "same"}`,
     `lite_layers is None`, the lite run judges the same cells as full, stamp ends `+reads-lite`.
   - `tests/test_msdm_plan0034.py::test_dmo_lite_final_token_and_full_span` → assert `same`
     (rename to `test_dmo_lite_same_as_full_span`); its full-span assertions are kept.
   - `tests/test_mcdm_v2.py::test_readplan_mcdm_lite_row` → `same`;
     `test_mcdm_lite_skips_compliance_and_reads_to` → becomes
     `test_mcdm_lite_matches_full` (a lite run's regions, compliance and value equal the full
     run's on the same file; stamp `+reads-lite`). The declared-lite-file-with-non-`' to'`-cell
     exit-2 assertion is removed with the check it tested.
   - `tests/test_user_modeling.py::test_lite_keeps_only_final_position` → rename
     `test_lite_keeps_all_positions` (lite judges every cell full does; stamp `+reads-lite`);
     line ~465 assertion → `{"kind": "same"}` and `lite_layers is None`.
   - `tests/test_basic_readout.py::test_basic_readout_lite_is_final_token` → rename
     `test_basic_readout_lite_is_same`; `rep.lite_rule` records `{"kind": "same"}` and the kept
     cells become every position of the fixture (all 9 × layers 20, 24), not `[(20, 8), (24, 8)]`. The bank-content
     assertion at line ~192 (`it["readout"] == {... "lite": {"kind": "final_token"}}`) is kept:
     the bank is not edited.
   - `tests/test_readplan.py`: `test_user_modeling_reads_every_position` (docstring, the
     `final_token` assertion, and `lite_select(...) == [len-1]` → all positions) and
     `test_basic_readout_v2_all_chat_prefill` (its lite assertion) updated to `same`;
     `test_basic_readout_v2_positions` (explicit rule, not the plan's lite) is untouched; any assertion about `typo` / `wrong_bridge` /
     other families is untouched.
   - `tests/test_reads.py::test_produce_lite_then_judge_lite_keeps_the_lite_site` hard-codes
     MCDM as its non-idempotent-rule example: re-target it (and its docstring) to `multihop`
     (`offset_from_end`), adjusting the position range to that family's row; every assertion is
     kept.
   - `test_mcdm_lite_matches_full`: one tokened 12-cell sentence fixture (`_rows` writes tokens),
     judged full and lite; compare regions, compliance, item rows and `value` (not `extras` /
     `complete` wholesale).
   - New tests in `tests/test_reads.py` for change 3: (a) a `same` family's lite run on a gapped
     sidecar file exits 2 like full (and lists the partial ids with `allow_missing`); (b) a
     declared-lite one-position-per-cell file for a `same` family exits 2 with the superseded
     message; (c) a non-`same` family (e.g. `multihop`) lite run is unaffected.
   - New test in `tests/test_readplan.py`: for each of the five families, every plan row has
     `lite_positions == {"kind": "same"}` and `lite_layers is None`, and
     `readplan.plan(f, reads="lite")` selects the same (id, pos, layer) cells as
     `reads="full"`; `typo` / `wrong_bridge` lite rows are unchanged; `plan_sha(f)` equals the
     value computed on `origin/main` c2fd6929 before this change (hard-coded per family, with a
     comment that the values pin plan 0061's no-reread claim and may be refreshed by a later bank
     change).
   Any other test that fails is a regression to fix in code, not by editing the test.
7. Docs and comments: README.md:129 (basic_readout), :232 (UM), :282 (MSDM);
   evals/directed_modulation/README.md:125-131; evals/model_specific_directed_modulation/README.md
   :73-76 and the results row at :133 ("final O-lens, lite") marked stale;
   evals/multi_concept_directed_modulation/README.md:47-51 and the `# ' to' only` command comment
   (:179); evals/user_modeling/README.md:38-40; evals/basic_readout/README.md:265-266; the
   `reads.py` lite-is-full rule in `docs/producing_readouts.md` (one sentence); code comments
   in readplan.py (UM comment, `_final_token_families_items` "the stem's ':'" comment, MCDM note)
   and src/wsbench/evals/directed_modulation/__init__.py:25. Each say "lite = the same positions as
   full (plan 0061, Camila 2026-11-02); lite results judged before this are stale". The MSDM
   README's "lite carries no signal … never a headline" paragraph is replaced by the same note.

Why a code constant, not `evals/<family>/lite_rule.json`: `LITE_SITE_FAMILIES`
(readplan.py:100) are the families whose lite site came out of the plan 0032 §2.6 support-share
procedure, frozen in that file; these five never had a procedure-chosen site, so the decision
lives in `readplan.py` beside their plan rows.

`scripts/audit_run.py` will flag every existing lite result of these five as "not the frozen
plan rule" — consistent with "lite results judged before this are stale".

## Not changed

Full positions, layers, banks, judges' full-mode behaviour, prompt versions of full runs, any
other family's lite rule, the macro rule (`results.py` still refuses mixed reads modes).

## Verification

`uv run pytest -q` green (baseline main green first); `ruff check` + `ruff format --check` on
touched files; the plan_sha test above.

## Critique log

- r1: unsanctioned `test_reads.py` MCDM test (retargeted to a multihop k=2 item, positive range
  kept); lite completeness / stale declared-lite gap (change 3); MCDM fixture shape; doc locations.
- r2: S1 "lite is full" definition pinned (unplanned ids / empty specs -> today's lite path); the
  1-position guard fires for any sidecar file (M2); jlens_concept_pr named (M1); the MCDM
  declared-lite exit-2 assertion is kept, now raised by the reads.py guard (M4).
