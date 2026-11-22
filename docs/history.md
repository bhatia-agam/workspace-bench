# History

Notes on how the bench changed, kept verbatim from the README they were written in. The README and
the other pages describe the bench as it is now.

## Renamed and removed families

`outputs/` is git-ignored. The in-house alternative to step 2 is
`wsbench convert-gen-dir gen_dir=GEN/ out=outputs/readouts/<arm>/<family>.jsonl kind=prose|tokens`,
which turns the `<gen_dir>/<label>/L###.jsonl` layout into the contract; `convert-read-json`
(legacy) does the same for the write-cell `read.json` of multi_concept_directed_modulation.
Four families were renamed on 2026-10-26 (`introspection_inject` -> `introspection`, `ttt_move` ->
`ttt`, `cutoff_confab` -> `knowledge_cutoff`, `dm_category_default` ->
`directed_modulation_obscure`; instruments unchanged), and `directed_modulation_obscure` became
`model_specific_directed_modulation` on 2026-10-30 (plan 0034; bank and native instrument
unchanged, ATI entry key moved): the surviving old names still work in
`family=` / `families=`, as `<family>.jsonl` readout file names, in stored `results.json` files
and as ATI subset keys. `ttt` (formerly `ttt_move`) was removed the same day (#97) as too close to
next-token prediction: in the source repo's ttt README (global-workspace
`evals/workspace-bench/hillclimbing_evals/multi_token/ttt/README.md`, per-layer table) the plain
logit-lens argmax at the read site scored 0.733 at L60, above the O-lens's 0.587 at that layer.
Its `results.json` in an old run dir is excluded from the macro (reason `removed`).
v1.2.0 (2026-11-03): `wrong_intermediate` was renamed from `wrong_bridge` (Camila). A pure
label change: the bank, judge prompts, instrument string, item ids and scores are unchanged, and
the family still hashes under `wrong_bridge` (`registry.HASH_FAMILY_NAMES`), so `plan_sha`, the
ATI `bank_sha` and the seeded floors do not move and readouts produced before the rename pass
the plan check. `family=wrong_bridge` still works (a one-line note on stderr), as do
`wrong_bridge.jsonl` readout files and `wrong_bridge/` out dirs and digest stores.

### Renamed in 0101 (2026-11-20)

The multi-token ("hard") families took the plain keys, the single-token families became
`<key>_st`, and every family directory moved under its category (plan 0101). No instrument
changed: banks, prompts, judge stamps, seeds, option lists, `plan_sha` and cached judge calls
are the same bytes, so a number from before the rename is the number of the same family today.

| family | key before | key now | directory under `evals/` before | now |
|---|---|---|---|---|
| Basic readout | `basic_readout_mt` | `basic_readout` | `basic_readout_mt/` | `basic/basic_readout/` |
| Basic readout (single-token) | `basic_readout` | `basic_readout_st` | `basic_readout/` | `basic/basic_readout_st/` |
| Multihop | `multihop_mt` (`multihop_mt_v2` until 2026-11-04) | `multihop` | `multihop_mt/` | `basic/multihop/` |
| Multihop (single-token) | `multihop` | `multihop_st` | `multihop/` | `basic/multihop_st/` |
| Multilingual | `multilingual_mt` | `multilingual` | `multilingual_mt/` | `basic/multilingual/` |
| Multilingual (single-token) | `multilingual` | `multilingual_st` | `multilingual/` | `basic/multilingual_st/` |
| Typo | `typo_mt` | `typo` | `typo_mt/` | `basic/typo/` |
| Typo (single-token, superseded) | `typo` | `typo_st` | `typo/` | `basic/typo_st/` |

Every other family kept its key and moved from `evals/<family>/` to
`evals/<category>/<family>/` (code: `wsbench.evals.<category>.<family>`); the categories are the
headings of [The evals](../README.md#the-evals): `basic`, `computational`, `association`, `safety`,
`anti_bag_of_features`, `logical_processing`, `model_specific`, `precision` (since 2026-11-21
`jlens_comparison`, see [below](#renamed-in-0105-2026-11-21)). `association` is
both a category (`evals/association/`) and a family (under `basic/` then; since 2026-11-21
`evals/association/association/`, see [below](#moved-in-0107-2026-11-21)).
`evals/baselines/`, `evals/fast/` and `evals/hallucinationbench/` did not move.

- **The four plain keys changed meaning.** `family=multihop` is now the multi-token family.
  `wsbench` prints one line on stderr the first time one of the four is typed (`note:
  'multihop' is the multi-token family since 2026-11-20 (was multihop_mt); the single-token
  family is 'multihop_st'`); `WSB_NO_RENAME_NOTICE=1` turns it off, and it is removed at the
  next version tag. The `_mt` keys still work (a one-line rename note).
- **Old files are read as the family that wrote them.** A readouts file, results directory,
  digest store, floor entry or adapted bank under a plain key is attributed by its content (the
  sidecar's `plan_sha`, the result's stamp, the bank header, the item ids), not by its name:
  `readouts_root=` trees and run directories from before the rename judge and report as before,
  with no new judge calls. A file of the other member of the pair is refused (exit 2, naming
  the family to pass) and never judged under the wrong key. These checks are permanent.
- **Frozen files keep the old keys by design.** The fast-subset files (`evals/fast/*.json`),
  everything under `tests/golden/` and `tests/fixtures/`, bank headers (`"family":
  "multihop-hard"` is the multi-token bank, `"multihop"` the single-token one) and the hashed
  key of each family (`registry.hash_name`) are frozen bytes; the code translates them at load.
- **Published artefacts are not renamed.** The adapted sets already pushed to Hugging Face,
  viewer and atlas exports, and HallucinationBench's WSB method names keep the keys they were
  published under; read them with the table above (`wsbench` reads both vocabularies).
- **Adapted sets and lens stores outside this repository** are migrated with
  `uv run python scripts/migrate_0101.py set <dir> [--apply]` (see `adapted/README.md`).

### Renamed in 0105 (2026-11-21)

One category changed its name; no family key, bank, prompt, stamp or number changed.

| category | key before | key now | title before | title now | directory under `evals/` before | now |
|---|---|---|---|---|---|---|
| J-lens comparison | `precision` | `jlens_comparison` | Precision | J-lens comparison | `precision/jlens_concept_pr/` | `jlens_comparison/jlens_concept_pr/` |

The code moved with it (`wsbench.evals.precision.jlens_concept_pr` ->
`wsbench.evals.jlens_comparison.jlens_concept_pr`). The family is still `jlens_concept_pr` and
its metric is still called `precision`. A category is never typed on the command line, so
nothing to re-learn there: `wsbench list` and `report json=True` now print `jlens_comparison`
in the `category` column where they printed `precision`, and the viewer section is titled
"J-lens comparison"; exports published before the rename keep the title "Precision".

### Moved in 0107 (2026-11-21)

One family changed category; no family key, bank, prompt, stamp or number changed.

| family | key | category before | category now | directory under `evals/` before | now |
|---|---|---|---|---|---|
| Association | `association` | `basic` | `association` | `basic/association/` | `association/association/` |

The code moved with it (`wsbench.evals.basic.association` ->
`wsbench.evals.association.association`). The family key `association` is also the category's
key, so its directory has the name twice. `wsbench list` and `report json=True` now print
`association` in the family's `category` column, its entry in [The evals](../README.md#the-evals) sits under
Association, and the viewer lists it there. Nothing is typed differently: `family=association`,
its readouts file `association.jsonl`, its results, cached judge calls, floors and tier (`full`)
are what they were. No score is computed per category (the macro, the core macro and the fast
macro average families, and the family is in the same ones as before), so no reported number
moves; anyone who averages families by category on their own now has 13 families under Basic
(12 without the superseded `typo_st`) and 3 under Association.
