# Plan 0114: the two hard banks join core and the fast subset (fast-v6)

The owner, 2026-11-23:

1. `user_modeling_hard` and `association_hard` are **core** families, and therefore **fast**
   families.
2. The easy `user_modeling` and `association` stay in the full tier only: not core, in no
   core-half cut.
3. The fast rule is unchanged (plan 0104): the core tier without `jailbreak_recognition` and
   `agentic_misalignment`, a seeded random half of each family's scored units (seed 20261121),
   the strict ATI subset of a family whole. Neither new family has an ATI entry.

`association_hard` joins core although the prompt-only reader solves nearly every item of it
(the owner's decision; its value compares lenses with each other). Its logit-lens L63 floor was
frozen separately (plans 0115 and 0116, merged while this branch was open). No test requires a core
family to have a logit-lens floor (`tests/test_po_floors_r3.py` forbids a core family in
`PENDING_FLOOR`, the prompt-only table, which is empty: both families have a frozen prompt-only
summary floor and a lucky-guessing floor).

Precedents followed: plan 0104 (conjunctive_association joined core through a listed
`TIER_MOVES` entry; the fast subset is a seeded half of core) and plan 0110 (the fast-v5 re-cut:
same command and seed, every other family's rows byte-identical).

## What changes

- **`tiers.CORE`**: 18 -> 20. The two families are appended, `user_modeling_hard` then
  `association_hard`; *every earlier member and its place in the tuple is retained*. `full()` is
  unchanged: both were already in it.
- **Manifest ledger**: the move is declared by listing it and by nothing else:
  `TIER_MOVES` in `scripts/manifest_0101_declare.py` gains `"user_modeling_hard": ("full",
  "core")` and `"association_hard": ("full", "core")`; *conjunctive_association's line is
  retained*. Both families were registered after the golden, so "before" is the tier their
  ledger entries were declared with, and `tier_moved` reads their two tier rows as before the
  move ahead of the ledger hash. The ledger file is not edited by hand,
  `tests/golden/manifest_0101_pre.json` is not regenerated, and no stamp moves.
  `python scripts/manifest_0101_declare.py <family> --plan 0114 --note '...' --write` was run
  for both and answered `refused: <family>: already declared in this state` (exit 2): with the
  move listed, the rows the entry hashes are the declared ones, which is what plan 0104
  designed ("the move needs no ledger entry of its own and stales none") and what
  `tests/test_rename_0101.py` asserts for a family registered after the golden. So
  `tests/golden/manifest_0101_declared.json` is byte-identical to main's and T1 passes.
- **`fast-v6`**: `python scripts/fast_cut_core_half.py --version fast-v6 --seed 20261121`, then
  `--check`. `evals/fast/fast_v6.json` (sha256 `ee2858db...`; cut again after bank v3 of association_hard,
  "After the merge of origin/main (#575)" below) is `fast_v5.json` with `version`
  changed and two entries and cut records inserted:

  | family | units | ATI | random | fast units | read items | stratum |
  |---|---|---|---|---|---|---|
  | association_hard | 99 | 0 | 50 | 50 | 50 | none |
  | user_modeling_hard | 155 | 0 | 78 | 78 | 78 | none |

  Both are scored by item (one result row per item with a tri-state `pass`; the headline is the
  pass rate over the decided items), so they take the cut's default unit (a plan row) and
  `fast.units`' general branch; no code of the cut or of the rescore changes.
  **Invariant: the 16 families of fast-v5 have the same bytes in fast-v6** (`bank_sha`, units,
  read ids, cut record), so every fast-v5 result row and FAST readouts file stays valid
  (`fast.compatible`, `fast.same_reads`). Totals: 18 families, 1,331 units, 1,569 read items
  (fast-v5: 16 / 1,203 / 1,441).
- **`fast.py`**: `fast-v6` in `VERSIONS` and `KEY_ERA` ("0101"), `DEFAULT = "fast-v6"`.
  *`fast_v5.json` and every older file stay registered, frozen and readable*
  (`report fast_version=fast-v5`; `compatible`, `same_reads`, `ati_view` and the viewer's
  per-version subsets are not edited).
- **Not touched**: every bank, every floor file, `evals/baselines/anti_text_inversion.json`,
  everything under `adapted/`, `fast_v5.json` and older, every stamp,
  `text_inversion.STALE_NO_ITEM_PENDING_AUDIT`. No model, GPU or judge call.

## Files

```
plans/0114-hard-evals-core.md            new
plans/README.md                          row
src/wsbench/tiers.py                     CORE + 2
src/wsbench/fast.py                      fast-v6 registered, DEFAULT
scripts/manifest_0101_declare.py         TIER_MOVES + 2
scripts/fast_cut_core_half.py            docstring / help text only
evals/fast/fast_v6.json                  new (the cut)
evals/fast/README.md                     fast-v6, counts, the second re-cut
README.md                                evals table (generated), tier counts, residual-store table
docs/tiers.md, docs/fast_subset.md, docs/producing_readouts.md, docs/results_contract.md
CLAUDE.md, AGENTS.md, tests/golden/README.md
evals/association/association_hard/README.md, evals/association/user_modeling_hard/README.md
evals/basic/directed_modulation/README.md   the default's name
tests/test_fast_core_half.py, tests/test_fast_subset.py, tests/test_rename_0101.py,
tests/test_tiers.py, tests/test_association_hard.py, tests/test_viewer_pages.py,
tests/test_run_procs.py, tests/test_run_wait.py, tests/test_check_command.py
```

## Tests

New:

- `tests/test_fast_core_half.py::test_fast_v6_is_fast_v5_with_the_two_hard_families_added`:
  the frozen fast-v5 file's sha256; its 16 entries and cut records byte-identical in fast-v6;
  fast-v5's text is fast-v6's without the two families (and `version`); `compatible` /
  `same_reads` / the macro accept a fast-v5 row of each of the 16; the two new families' cut
  sizes (50 of 99, 78 of 155, `ceil(n / 2)`, the seeded draw reproduced); the easy
  `user_modeling` and `association` in neither core nor any core-half cut; an old fast-v5
  directory still read under `fast.use("fast-v5")`.
- `tests/test_tiers.py`: the 18 earlier members of `CORE` in their order, the two new ones
  after them, the easy siblings full-only.
- The two families are in `TABLE` and `V6_FAST_PLAN_SHA`, so the parametrized cut, count and
  plan-sha tests run on them.

Pre-existing assertions changed, each forced by this change:

| test | change | why |
|---|---|---|
| `test_fast_core_half.py` (throughout) | the default's name `fast-v5` -> `fast-v6`, its sha256, `TABLE` and the plan shas + 2 families, 16 -> 18 families, 1,203 -> 1,331 units, 1,441 -> 1,569 read items, the simulated next version `fast-v6` -> `fast-v7` | the default version and its family count |
| `test_fast_core_half.py::test_fast_v5_is_fast_v4_recut_for_chain_intermediates_alone` | reads `fast_v5.json` itself instead of the default's file, over fast-v5's 16 families; `compatible` / `same_reads` asserted against fast-v5 and against the default | the default is no longer fast-v5; every assertion about fast-v4 vs fast-v5 is kept |
| `test_fast_subset.py` | `V6` in the registered versions and `KEY_ERA`; the default's name in `test_select_and_use` and `test_every_test_starts_on_the_default_subset` | fast version registered / default |
| `test_rename_0101.py` | `FROZEN_FAST_FILES` and `CORE_HALF_RECORDS` gain fast-v5 (now a frozen predecessor, sha-pinned); fast-v6 in the core-half versions; the `TIER_MOVES` equality lists the two moves | fast default / the listed mechanism |
| `test_tiers.py` | `CORE` + 2, `N = 20`, the `tier: core (20 families` notice | CORE count and members |
| `test_association_hard.py` | `tier_of == "core"`, `len(CORE) == 20`, the family's fast entry (50) instead of `NotInFast` (now asserted for the easy `association`) | CORE and fast membership |
| `test_viewer_pages.py` | `of 20 core evals`, `len(CORE) == 20` | CORE count |
| `test_run_procs.py`, `test_run_wait.py` | the default's name in two messages | fast default |
| `test_check_command.py` | `check fast_subset` counts 18 bank files, not 16 | fast family count |

Not changed, and failing: `tests/test_residual_dataset.py::test_the_shipped_map_covers_the_core_set`
asserts that the published float32 residual capture holds a folder for every core eval.
After the merge of origin/main (#560) the shipped map has `full/user_modeling_hard` (the
bank-v2 capture: 110 of bank v4's 155 items are stored, the 45 items of the harder wave are
not), so the test fails for `full/association_hard` only, which has not been captured and
uploaded (`wsbench capture --fast check=True`: 0 of 50 items in the dataset). Loosening the
assertion is not sanctioned by this plan and capturing needs a GPU, so it is left for the
owner: capture and upload the family and rebuild `evals/residuals/map.json`, or exempt a
family that is not captured yet.

## After review (2026-11-23)

- **Merged origin/main (#555-#560).** One conflict, the README's residual-store table. (These
  counts are of association_hard's bank v2 and are superseded by the next section's.) It was
  counted again on the merged tree with `wsbench capture families=all check=True` and `--fast
  check=True` (offline, empty store):

  | set | evals | cells in the plan | stored | not stored |
  |---|---|---|---|---|
  | every eval | 32 | 3,498,830 | 3,355,874 | 142,956 |
  | core | 20 | 3,139,911 | 3,005,469 | 134,442 |
  | fast | 18 | 555,291 | 485,639 | 69,652 |

  Not stored: association_hard 11,704 cells (56 items; fast 5,852, 28), user_modeling_hard
  80,542 (45 of 155; fast 39,534, 22 of 78), chain_intermediates 19,602 (66 of 120; fast
  10,989, 37 of 60), knowledge_cutoff 22,594 (39, by design; fast 13,277, 23), multilingual
  2,915 (9), multilingual_typo 1,199 (3), multilingual_multihop 649 (2), basic_readout 462
  (1), jlens_concept_pr 3,289 (nothing to capture; counted in the every-eval row, as before).
  The README's timing note counts core as 20 evals and 4,852 questions (plan rows).
- **An old fast directory under the new default says what it lacks.** A fast-v5 run has 16
  rows, all still counted under fast-v6, and no stale row to point at the difference (plans
  0104 and 0110 never added a family). `fast.not_in_run(stamps, against=None)`: when a row is
  of another registered version that is `compatible` for its family, the families the active
  version holds that none of those versions holds and that have no row.
  `cli.fast_header` prints `2 families of fast-v6 not in this run: association_hard,
  user_modeling_hard` under the scope line, only while the active subset is the default (a
  directory reported with `fast_version=` is reported as it was), and the viewer's
  `stamp_note` appends the same sentence to the run's set note. *Which rows are compatible,
  the macro and every score are unchanged*; the viewer still files the run under `fast`.
  Tests: `test_a_fast_v5_directory_under_the_default_names_the_families_it_lacks`
  (`tests/test_fast_core_half.py`, a synthetic 16-row fast-v5 directory through `report`) and
  `test_a_run_of_the_previous_fast_cut_says_which_families_it_lacks` (`tests/test_viewer.py`).
  No pre-existing assertion changed.
- Docs: the easy banks are "in no core-half cut (`fast-v4` and later)" (`user_modeling` is in
  the frozen fast-v1 .. fast-v3 files); `docs/tiers.md` says that an adapted set has no bank
  for either hard family, so its core macro covers at most 18 of the 20.

## After the merge of origin/main (#575, 34af4b2a)

Main moved while the branch was open: plan 0115 froze association_hard's logit-lens L63 floor,
plan 0116 (#575) replaced its 56-item bank v2 with the 99-item bank v3 (`items_v3.json`, stamp
`assoc-hard-v1+gate-h2+bank-v3`, declared in the ledger by that plan), and the inkling-2-mini
adapted sets landed. Merged; conflicts in `CLAUDE.md`, `README.md` (the evals-table row),
`plans/README.md`, the family README and `tests/test_association_hard.py::test_registration`,
each resolved to both sides' content (main's bank v3 file, stamp and counts *and this plan's
`tier_of == "core"`*).

- **Ledger.** `tests/golden/manifest_0101_declared.json` is main's file, byte for byte. With
  the two `TIER_MOVES` lines retained, `manifest_0101_declare.py <family> --plan 0114 --note
  ... --write` again answers `refused: <family>: already declared in this state` (exit 2) for
  both families, association_hard now against plan 0116's bank-v3 entry. Nothing written.
- **`fast-v6` cut again, under the same name.** The branch's first `fast_v6.json` held 28 of
  bank v2's 56 association_hard items and failed `--check` on the merged tree (its `bank_sha`
  is bank v2's). `fast-v6` has never been on main, has no published result and no file outside
  this branch, so the file was regenerated instead of taking a new version: same command,
  same seed (`--version fast-v6 --seed 20261121`), then `--check`. sha256 `a3a8e426...` ->
  `ee2858db...`. association_hard: 99 units, no ATI id, `ceil(99 / 2)` = 50 fast units (an odd
  count rounds up, as user_modeling_hard's 155 -> 78), 50 read items, stratum `none`.
  **Verified: the other 17 entries and cut records (the 16 of fast-v5 and
  user_modeling_hard) are byte-identical to the first cut, and the 16 to `fast_v5.json`**; the
  file with association_hard removed serialises to the same bytes before and after. A
  family's draw depends on the seed, its name and its own units only. Totals: 18 families,
  1,331 units, 1,569 read items (the first cut: 1,309 / 1,547).
- **Tests of this branch updated for the new cut** (none predates the branch in the form
  changed): `V6_SHA256`, `TABLE["association_hard"]` (99, 0, 50, 50, 50),
  `V6_FAST_PLAN_SHA["association_hard"]`, the totals 1,331 / 1,569 and the (99, 50) pair in
  `test_fast_v6_is_fast_v5_with_the_two_hard_families_added` (`tests/test_fast_core_half.py`);
  the fast-entry size 50 in `tests/test_association_hard.py::test_registration`.
- **README residual-store table**, counted again on the merged tree with the same two commands
  (`wsbench capture families=all check=True` and `--fast check=True`, offline, empty store):

  | set | evals | cells in the plan | stored | not stored |
  |---|---|---|---|---|
  | every eval | 32 | 3,507,817 | 3,355,874 | 151,943 |
  | core | 20 | 3,148,898 | 3,005,469 | 143,429 |
  | fast | 18 | 559,889 | 485,639 | 74,250 |

  Only association_hard moved: 20,691 cells in the plan (99 items x 209), none stored (fast
  10,450, 50 items); bank v2's 56 items were 11,704 (fast 5,852). Every other family's line
  is the one of the section above. The README's timing note counts core as 20 evals and 4,895
  questions, and the fast subset reads 1,569 of its 18 families' 4,669.
- `tests/test_residual_dataset.py::test_the_shipped_map_covers_the_core_set` still fails for
  `full/association_hard` only (now 99 items to capture); `evals/residuals/map.json` and that
  test are not touched here.

`tests/test_readme_style.py` keeps dates and plan numbers out of `README.md` and `docs/`, so
`docs/tiers.md` says that association_hard's logit-lens floor is measured "on its own branch"
without naming plan 0115; the plan number is in this file, `CLAUDE.md` and the family README.

Gates: `pytest` (the known flake `tests/test_run_procs.py::test_second_interrupt_terminates_the_children`
deselected), `ruff check`, `ruff format --check`, `fast_cut_core_half.py --check`,
`readme_evals_table.py --write` leaving no diff.

## The residual test (2026-11-24)

`tests/test_residual_dataset.py::test_the_shipped_map_covers_the_core_set` now lists
`association_hard` by name as `awaiting_capture` (the owner: "don't block things"). The
published dataset holds the eval since its revision e312d946 (the 56 questions of bank v2), and
the 99 questions of bank v3 are offered in the dataset's pull request 1, but
`evals/residuals/map.json` still pins an earlier revision, so the map names no
`full/association_hard` folder and reads of the eval run the model. The test also asserts that
no listed eval is in the map, so the entry has to leave the list in the change that moves the
map. Every sentence above that says this test fails describes the branch before this change.
