# Golden files

Data the tests compare the port against, byte for byte: option lists, rendered prompts, marker
offsets and regex verdicts. Most are frozen outputs of the source repo's own scripts (Camila's
private `global-workspace`, 2026-09-15..22); the rest (`capable_questions.json` and the option
lists of the families this repo drew itself) pin this repo's own builders. They are inputs to
`tests/test_<family>.py`, never regenerated here.

The scripts that produced the source-repo goldens (`make_<family>.py`, importing that repo by an
absolute path) were removed in the 2026-09-23 audit because nobody outside that machine could
run them; they are in the git history before that commit if a golden ever has to be rebuilt.

## Family keys in these files (plan 0101, 2026-11-20)

The goldens keep the family keys of before plan 0101, in their file names and inside them, and
their bytes: they are frozen records, and the rename moved no instrument. Read them with this
table (the left column is what a file name or a key inside a golden says):

| in a golden | the family today |
|---|---|
| `basic_readout_mt` | `basic_readout` (multi-token) |
| `basic_readout` | `basic_readout_st` |
| `multihop_mt`, `multihop_mt_v2` | `multihop` (multi-token) |
| `multihop` | `multihop_st` |
| `multilingual_mt` | `multilingual` (multi-token) |
| `multilingual` | `multilingual_st` |
| `typo_mt` | `typo` (multi-token) |
| `typo` | `typo_st` |

So `basic_readout_options.json` and `multihop_mc_options*.json` pin the single-token families,
`*_mt_options*.json` the multi-token ones, and `multilingual_v2_options.json` is
`multilingual_st`'s. A golden keyed by family inside (`capable_questions.json`,
`mt_regex_units*.json`) is translated by the test that reads it
(`registry.rekey_pre_0101` / `from_pre_0101`), never rewritten; a golden whose values hash a
family key (`plan_sha_pre_0090.json`, the fast-subset row hashes) is reproduced through
`registry.hash_name` / `frozen_name`. `manifest_0101_pre.json` is the manifest of every
family's hashes, seeds, option orders, prompt shas and call keys recorded on main before the
rename, in pre-0101 keys; `scripts/manifest_0101.py --check` compares the tree against it and
neither file is ever regenerated (the golden embeds the sha of the script that made it; the
script has since gained one `try` in `plan_entry`, so that a family whose bank changed after an
older fast version was frozen is recorded as `unavailable` instead of ending the run, and
T1 pins both shas and the golden's bytes). `--check` itself reports
every later instrument change as a difference; the permanent guard is T1 of
`tests/test_rename_0101.py`, whose rule is `verdict` in `scripts/manifest_0101_declare.py`:
**every family's manifest rows equal either the migration golden's or the state recorded for it
in the ledger `manifest_0101_declared.json`, and a ledger entry is only valid with a stamp or
bank version that differs from the golden's.**

- A family whose rows equal the golden's passes.
- A family whose rows differ, and a family the golden does not have, needs a ledger entry
  `{prompt_version, bank_file, bank_sha256, rows_sha256, plan, note}` whose stamp, bank file and
  bank sha256 AND `rows_sha256` (the sha256 of the family's whole manifest entry as canonical
  JSON) equal the current tree's. So a later edit of an already declared family fails until it
  is declared again.
- No declaration without a bump: rows that differ while the stamp and the bank both equal the
  golden's fail ("instrument moved without a stamp or bank change"), with or without an entry.
  One exception (plan 0105), a category rename listed in `manifest_0101_declare.CATEGORY_RENAMES`
  (= `registry.LEGACY_CATEGORIES`): the manifest holds no path of a family, so a renamed
  category directory moves exactly one row, `list.category`, and there is no stamp or bank to
  bump. An entry with the golden's own stamp and bank declares it while that row holds the
  listed new name and every other row equals the golden's; the same row is set aside when the
  family later declares a stamp change.
- A tier move is declared by listing it (plan 0104): `manifest_0101_declare.TIER_MOVES` holds
  `family -> (tier before, tier today)`; today `conjunctive_association`, `user_modeling_hard`
  and `association_hard`, each `full -> core` (the last two: plan 0114). Which
  tier a family is in changes what a bare `run` judges, never how the family is judged, so
  there is no stamp or bank to bump. For a listed family that holds the listed tier, its two
  tier rows (`list.tier` and its `tiers.CORE` membership) are read as they were before the
  move, before the comparison and before the ledger hash (`tier_moved`): the move needs no
  ledger entry and stales none, whether the family is the golden's, already declared, or
  registered after the golden (then "before" is the tier its entry was declared with). The
  waiver is that family's, those two rows' and that pair's only: any other family's tier or
  core membership moving, and a listed family in a tier that is neither its listed before nor its listed after, fail
  like any other row. To move a family's tier, add or replace its line (a test pins the table
  against `tiers` and the golden); a family that moves back loses its line.
- A declaration by stamp only (bank file and sha256 equal the golden's) waives the family's
  `stamps` and `run` sections alone; `plan`, `files`, `seeds`, `options`, `tables`, `lens_store`
  and every other section must still equal the golden's. A declaration with a new bank compares
  nothing against the golden; the ledger hash covers the family.
- Every section outside `families` (the shared digest prompts, the F4 record, the script's
  tables and imports) must equal the golden's; `shared.n_families` may grow only by the
  families the golden does not have. A deliberate shared change needs an edit of that check.
- A family missing from the tree fails.
- Fast versions cut after the golden (a version the golden has for no family): a family's
  `plan.fast_plan_sha` row for one is set aside, before the comparison and before the ledger
  hash, when it is the family's row under one of the golden's versions (the same plan rows under
  a new name; for the two position-reduced families, whose rows hash the version string, the
  row recomputed under the older version's name). Cutting a fast version therefore needs no
  entry from the families it leaves alone and stales no earlier entry. Any other new-version row
  fails ("its fast plan moved"), except in a family declared with a new bank, where it is part
  of what the ledger hash holds.

The ledger is written by `python scripts/manifest_0101_declare.py <family> --plan <NNNN> --note
'<what moved>' --write`, which refuses when the family's stamp and bank equal the golden's or
its previous entry's (bump first), and when there is nothing to declare. One reviewable entry
per declared change; today: `nyt_connections` (plan 0099), `conjunctive_association` (plan
0103: comp-v6 on bank v6) and `jlens_concept_pr` (plan 0105: category `precision` ->
`jlens_comparison`, no instrument row moved). `tests/fixtures/` follows the same rule (`adapted_v1/` is a
set from before the rename, kept unmigrated on purpose).

## In-repo v2 pins (plan 0012, 2026-10-10)

`moral_rationale_options_v2.json`, `moral_rationale_prompt_v2.txt` and
`agentic_misalignment_prompts_v2.json` pin this repo's own ec-v2 / am-design-v2 builders and
templates. They are NOT source-repo records: the source-repo files beside them
(`moral_rationale_options.json`, `agentic_misalignment_prompts.json`)
are kept unchanged as the v1 record, and the v1 option lists are still asserted through
`build_mcs(..., contrast=False)`.

## In-repo role_bound oa-v2 pins (plan 0055, 2026-10-30)

`role_bound_association_options_v2.json` (every item's v2 block, golds and reversed golds:
near-role distractors from `evals/anti_bag_of_features/role_bound_association/roles_v1.json`, distinct name prefixes)
and `role_bound_association_prompt_v2.txt` (SYSTEM + a rendered native user prompt) pin this
repo's own oa-v2 builder. The source-repo `role_bound_association_options.json` /
`_prompt.txt` stay unchanged as the oa-v1 record, still asserted through `build_block` (v1).

## conjunctive_association v2 pins (plan 0049, 2026-10-30)

`conjunctive_association_options_v2.json` pins this
repo's comp-v2 builder on bank v2 (`items_v2.json`: the cluster grid plus every option's
role-swapped twin). The source-repo record `conjunctive_association_options.json`
stays unchanged and is still asserted against the v1 file.

## relational_multihop rel-v3 (#209 round 6, 2026-11-01)

`relational_multihop_options_v3.json` pins the current rel-v3 list (one 19-line list per item:
18 content options (12 composed chains over a two-word and a three-word relation set, 5 single
relations, 1 near form), cannot tell last), written by the same script. The rel-v2 file below
is the retired list, still rebuilt by `build_options(..., version="v2")` and checked.

## relational_multihop rel-v2 (plan 0043, 2026-10-30; retired by rel-v3)

`relational_multihop_options_v2.json` pins this repo's own rel-v2 `judge.build_options` (one
14-line list per item: 13 content options (8 composed chains, 4 single relations, 1 near form;
see `evals/anti_bag_of_features/relational_multihop/README.md` §Option list), cannot tell last), written by `scripts/make_relational_options.py` (no API; `--check` diffs).
`relational_multihop_options.json` is kept unchanged as the
rel-v1 record (the source repo's two-call X/Y pool); no test reads it any more.

## multihop bank v5 pin (2026-11-04)

`multihop_mc_options_v5.json` pins the shown option lists (`mcjudge_bank.options_of`, cannot tell
last) of all 98 items of bank v5: bank v3's lists on bank v4's 68 items and the 30 new items'
lists. `multihop_mc_options.json` stays the bank v2 record, still asserted against `items_v2.json`.

## user_modeling um-v3.5 pin (bank v3, 2026-11-04)

`user_modeling_options_v5.json` (the fifth options golden; bank v3, um-v3.5) pins
`options.build_options` on bank v3's 126 items under um-v3.5 (`aliases.NEIGHBOURS` for the new
items' Country / Occupation golds). Its 47 bank-v2
entries equal `user_modeling_options_v4.json`'s byte for byte; that file stays the um-v3.4 record
of all 100 `items.json` items.

## directed_modulation bank v2 pin (plan 0109, 2026-11-20)

`directed_modulation_options_v2.json` pins `judge.option_sets` over the registered bank v2
(`items_v2.json`: no dont_think items, 37 new think items). `directed_modulation_options.json`
is unchanged and still pins the lists of the frozen 100-item `items.json`, asserted through the
same builder (the relatedness groups of the new concepts were added to
`distractor_groups.json`; no `items.json` list moved).

## Read plans before plan 0090 (2026-11-16)

`plan_sha_pre_0090.json` pins every family's non-fast read plan as it was before the fast subset
(plan 0090) touched `readplan.py` / `reads.py`: `plan_sha`, and the sha256 of the written plan
rows under `reads=full` and `reads=lite`. It was written once, under pytest (the conftest stubs
set nyt_connections' and knowledge_cutoff's nocot texts), on the pre-0090 code, by
`tests/test_fast_subset.py` with `WSB_WRITE_GOLDEN_0090=1`. A deliberate plan change (a new bank
version) regenerates it the same way; `--fast` must never move it.
Since plan 0101 the writer emits today's family keys while this file keeps the pre-0101 ones, so
a regeneration takes only the changed family's three values from the writer's output (plan 0109,
2026-11-20: `directed_modulation`, bank v2's 102-row plan; plan 0110, 2026-11-23:
`chain_intermediates`, bank v3's 120-row plan; every other row is unchanged).

## Pinned-path request pin (plan 0096, 2026-11-18)

`pin_requests_0096.json` holds, for agentic_misalignment, jailbreak_recognition, hinted_cutoff
and model_multihop on their own pinned judge (summary mode; hinted_cutoff and model_multihop
also native), with one declined call so the refusal fallback fires: every SDK request of the
run (every keyword as sent, `system` / `messages` as a sha256 each, sorted by model and that
hash) and the result's `config`. It was written by `tests/test_pin_requests_0096.py`
(`WSB_PIN_0096_WRITE=1`) on the tree BEFORE plan 0096's first `src/` edit, through the
Anthropic-shaped fake client, and pins that plan's invariant: a pinned run with default options
sends byte-identical requests and stamps a byte-identical `config`. Never regenerate it on a
later tree; a change that makes the test fail has moved the pinned instrument.
