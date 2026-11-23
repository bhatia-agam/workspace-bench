# Plan 0109: directed_modulation bank v2, the regular family without "don't think"

Camila, 2026-11-20: regular directed modulation should be "just regular, not 'don't think'"; "the
secret items can stay. refill the bank with other regular dm questions".

The bank, its option lists, the stamp and the two text floors were built on 2026-11-20 as plan
0102 (branch `camila/0102-dm-regular`, commit 08c3e487, never merged). This plan ports that
commit onto main as it is after plans 0101 to 0107 (docs in `docs/`, the manifest ledger, the
tiers, `fast-v4`) and finishes what it left open: the logit-lens L63 entry, the fast files, the
ledger entry. No bank byte, option list, prompt or stamp differs from that commit.

## What changes

- **Bank v2**, `evals/basic/directed_modulation/items_v2.json` (`version: 2`, `supersedes:
  items.json`); `items.json` is frozen and stays byte for byte.
  - kept, byte-identical and in their original order: the 35 `think` items (`dm-pair-NN-pos`),
    the 15 secret and the 15 preference items;
  - removed: the 35 `dont_think` items (`dm-pair-NN-neg`);
  - added: 37 new `think` items (`dm-think-NN`), built from the source bank's five instruction
    templates with new concepts and new carriers, gated on Qwen3.6-27B (chat render, thinking
    off, greedy + 10 samples at T=0.7; the reply is the carrier word for word and never mentions
    the concept, greedy AND >= 8/10): 74 authored, 74 lint-clean, 74 pass, 37 selected, 37 held
    in reserve (not in the repo). The gate checks behaviour only, as for the source items.
  - 102 items: 72 think, 15 secret, 15 preference.
- **Relatedness groups.** `distractor_groups.json` gains the 37 new concepts, each in its prompt
  category's group (19 existing categories gain one concept, 18 categories are new). Additive:
  no existing concept moves, *and `items.json`'s option lists are unchanged*
  (`tests/golden/directed_modulation_options.json` still holds through the same builder). The
  file name stays, so an adapted set's overlay of that name is still found.
- **Option lists.** The distractor pool is the whole subfamily. The think pool grows from 35
  concepts to 72, so all 35 kept think items get new lists (same gold); the 30 secret /
  preference lists are unchanged. New golden `tests/golden/directed_modulation_options_v2.json`.
- **Read plan.** Bank v2 has its own 102-row plan (`940bf69a...`; `items.json`: `1da94e9c...`).
  The 65 kept items' rows are identical, so their readouts serve bank v2; a drop-and-add step is
  not a drop-only step, so the bank records no `plan_lineage` and a readouts file needs the 37
  new items read and a sidecar on the new `plan_sha`.
- **Stamp.** `judge.instrument(header)` (the buggy_code / user_modeling rule): bank v<N> >= 2
  stamps `+bank-v<N>`, so the registered instrument is `dm-2026-10-31+expressed+bank-v2`, *and
  `items.json` and the adapted banks, which carry no `version`, keep
  `dm-2026-10-31+expressed`*. No prompt, rubric or call key changes (`JUDGE_PROMPT_VERSION`
  stays `dm-2026-10-31`), so cached judge calls of kept secret / preference items replay.
- `white_bear` needs both twins of a pair: absent on bank v2, kept in code for `items.json` and
  the adapted banks.

## Floors

- **Lucky guessing** (Opus 5.5, 5 fresh draws, 102 items, measured 2026-11-20): blind 0.148 ->
  0.224, described 0.168 -> 0.202, seeded-uniform 0.190 -> 0.180, `topic` (a diagnostic, not a
  floor) 0.758 -> 0.759. The family's floor is `blind`, 0.224.
- **Prompt-only summary** (`po-opus-v1`, reply-free-v2, measured 2026-11-20): 1.000 -> 1.000
  (saturated, 0 of 102 refused).
  Both entries are the 2026-11-20 measurements, unchanged: they are stamped
  `dm-2026-10-31+expressed+bank-v2` (+ the digest tags of main's summary instrument for the
  prompt-only one) and the bank file is byte-identical, so they are valid on main.
- **Logit lens L63** (measured 2026-11-23): 0.220 (100 items) -> 0.412 [0.324, 0.510] (42 of
  102). All 102 items read in one run by the bundled `Producer` (`logit_lens`, `layers=[63]`,
  one Modal GPU), judged with `layers=63`, frozen with `wsbench freeze kind=logit_lens
  partial=True source=<run record>`.

## Fast subset

- `fast-v4`, the subset `--fast` runs, is a half of the core tier. directed_modulation is not
  core and is not in it: nothing to cut, `--fast` skips the family as before.
- The five older files (`fast-v1`, `fast-v2`, `fast-v3`, `fast-safety-v1`, `fast-safety-v2`) hold
  the family: 62 units of `items.json`, 17 of them dont_think items, with `items.json`'s
  `bank_sha`. **No successor is cut.** `scripts/fast_refreeze_bank.py` (conjunctive_association's
  case: a new bank with the same ids) refuses, because read ids are gone; the README's other case
  (re-select by the rules the files were chosen by) needs the outcomes of 23 arms on the new
  items, which do not exist; and none of the five is selectable since plan 0104. The entries
  stay as records: under one of those versions `fast.entry` fails closed for the family
  ("bank changed since <v> was frozen; re-freeze") and an all-families `plan` / `run` of that
  version exits 2. `tests/test_fast_subset.py` records this as `NOT_REFROZEN` beside `REFROZEN`.
  A new selection on bank v2 is the owner's call.

## ATI

directed_modulation is `NOT_GATED` (the instruction states the concept) and has no entry in
`evals/baselines/anti_text_inversion.json`; the file does not change and nothing is re-gated.

## Manifest ledger

Declared with `scripts/manifest_0101_declare.py directed_modulation --plan 0109 --note ...
--write` (new bank, new stamp). `manifest_0101_declare.fast_equivalents` gains one guard: a
fast version that has no plan for the family any more (its manifest row reads `unavailable`)
has no equivalent row, instead of ending the script.

## Not in this plan

- The adapted sets (`adapted/<model>/directed_modulation.json`) still derive from `items.json`
  and keep their dont_think items and their stamp.
- A fast subset that holds the family on bank v2 (above).

## Tests

`tests/test_directed_modulation_bank_v2.py` (new): the bank is `items.json` minus dont_think
plus 37, its own plan and the kept rows' equality, option lists by bank, the stamp by bank
version, the toy file. Tests of the scoring code that use the dont_think twin
(`test_directed_modulation.py`, the DM half of `test_summary_mode_dm.py`) pin `items.json` and a
byte copy of the old toy readouts (`tests/fixtures/directed_modulation_v1_toy.jsonl`), as
buggy_code's and user_modeling's v1 tests do.

`tests/test_fast_subset.py`: `NOT_REFROZEN = {directed_modulation: the five outcome-selected
versions}`; the per-(version, family) cases of the family move from the "on its registered bank"
tests to the "fails closed" test, the all-families `plan` / `run` tests of fast-v3 and
fast-safety-v2 expect exit 2 with the other families served, and the reproduction of the
fast-v3 / fast-safety-v2 cut runs with the family on the bank it had at that cut.
