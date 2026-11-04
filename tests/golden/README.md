# Golden files

Data the tests compare the port against, byte for byte: option lists, rendered prompts, marker
offsets and regex verdicts. Most are frozen outputs of the source repo's own scripts (Camila's
private `global-workspace`, 2026-09-15..22); the rest (`capable_questions.json` and the option
lists of the families this repo drew itself) pin this repo's own builders. They are inputs to
`tests/test_<family>.py`, never regenerated here.

The scripts that produced the source-repo goldens (`make_<family>.py`, importing that repo by an
absolute path) were removed in the 2026-09-23 audit because nobody outside that machine could
run them; they are in the git history before that commit if a golden ever has to be rebuilt.

## In-repo v2 pins (plan 0012, 2026-10-10)

`moral_rationale_options_v2.json`, `moral_rationale_prompt_v2.txt` and
`agentic_misalignment_prompts_v2.json` pin this repo's own ec-v2 / am-design-v2 builders and
templates. They are NOT source-repo records: the source-repo files beside them
(`moral_rationale_options.json`, `moral_rationale_prompt.txt`, `agentic_misalignment_prompts.json`)
are kept unchanged as the v1 record, and the v1 option lists are still asserted through
`build_mcs(..., contrast=False)`.

## In-repo role_bound oa-v2 pins (plan 0055, 2026-10-30)

`role_bound_association_options_v2.json` (every item's v2 block, golds and reversed golds:
near-role distractors from `evals/role_bound_association/roles_v1.json`, distinct name prefixes)
and `role_bound_association_prompt_v2.txt` (SYSTEM + a rendered native user prompt) pin this
repo's own oa-v2 builder. The source-repo `role_bound_association_options.json` /
`_prompt.txt` stay unchanged as the oa-v1 record, still asserted through `build_block` (v1).

## conjunctive_association v2 pins (plan 0049, 2026-10-30)

`conjunctive_association_options_v2.json` and `conjunctive_association_prompt_v2.txt` pin this
repo's comp-v2 builder on bank v2 (`items_v2.json`: the cluster grid plus every option's
role-swapped twin). The source-repo record `conjunctive_association_options.json` /
`conjunctive_association_prompt.txt` stays unchanged and is still asserted against the v1 file.

## relational_multihop rel-v3 (#209 round 6, 2026-11-01)

`relational_multihop_options_v3.json` pins the current rel-v3 list (one 19-line list per item:
18 content options (12 composed chains over a two-word and a three-word relation set, 5 single
relations, 1 near form), cannot tell last), written by the same script. The rel-v2 file below
is the retired list, still rebuilt by `build_options(..., version="v2")` and checked.

## relational_multihop rel-v2 (plan 0043, 2026-10-30; retired by rel-v3)

`relational_multihop_options_v2.json` pins this repo's own rel-v2 `judge.build_options` (one
14-line list per item: 13 content options (8 composed chains, 4 single relations, 1 near form;
see `evals/relational_multihop/README.md` §Option list), cannot tell last), written by `scripts/make_relational_options.py` (no API; `--check` diffs).
`relational_multihop_options.json` and `relational_multihop_prompt.txt` are kept unchanged as the
rel-v1 record (the source repo's two-call X/Y pool); no test reads them any more.

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
