# Plan 0110: chain_intermediates bank v3, the 66 flawed chains dropped and refilled

Camila, 2026-11-20, on the per-item vetting of the fast families: "fix multilingual scoring and
drop the 66 chained items (how many are left? can we refill?)". 54 are left; this plan refills
the family to 120.

The vetting (2026-11, every item of bank v2 read against 23 arms' outcomes and the raw readouts
of two) marked 66 of the 120 items `drop`:

- **41: the scored intermediate is not required.** It lies between two add / subtract steps
  ("Add 3. Add 7."): the answer is the start plus the net offset, so the model need not hold
  the value in between, and a lens that fails to find it has missed nothing. A structural
  argument, supported by the lenses' slot hit rates (0.04-0.15 on such slots, 0.20-0.25 on the
  others); the vetting did not re-run the model. 13 depth-2 items, 28 depth-3.
- **23 more: a chance-prone gold.** 10, 12, 15 and 25 are digest keys of 20-54% of OTHER items'
  digests, so a slot with one of them as its gold can be credited from numbers the lens says
  about any chain. (31 items have such a gold; 8 of them are among the 41.)
- **2 duplicates**: `chain-w2-d2p-0039` is the same prompt as `chain-d2p-0352`, and
  `chain-v2-d2p-0015` (10, double, double) is the first two steps of `chain-d3p-0753`.

## What changes

- **Bank v3**, `evals/computational/chain_intermediates/items_v3.json` (`version: 3`,
  `supersedes: items_v2.json`); `items_v2.json` and `items.json` are frozen and stay byte for
  byte.
  - kept, byte-identical and in bank v2's order, with their v2 MC lists: the 54 items the
    vetting kept (49 depth-2, 5 depth-3);
  - removed: the 66 (35 depth-2, 31 depth-3), listed with their reason in the header's
    `selection.dropped_v2` and in `scripts/build_chain_v3.py` (`DROPPED`);
  - added: 66 new seed-last plain chains `chain-v3-d<depth>p-NNNN` (64 depth-2, 2 depth-3);
  - 120 items, 113 depth-2 and 7 depth-3, 127 scored intermediates (bank v2: 84 / 36 / 156).
- **Construction rules of a new item** (`construction_v3` in the header; `violations` and
  `select` in the builder). C1: every pair of adjacent steps is one additive and one scaling
  step (no add-add: the flaw above; no scale-scale: x4, x6, x9, a quarter compose the same
  way). C2: no value two steps on is one generator step from the value before the slot. C3: an
  intermediate is in neither prompt order, at least 3 from the start, the answer and the other
  intermediate, not the digit reversal of start / answer, not two prompt numerals side by side.
  C4: no intermediate in {10, 12, 15, 25}, none a multiple of 10. C5: intermediates 11..99,
  start 6..60 (bank v2's generator drew 2..30), answer 2..99, operands 3..9. C6, on the bank:
  the prompt is in no earlier chain bank (registered or adapted); a new item shares its (start,
  first step) and its (start, first intermediate) with no other item; a gold value names at
  most 4 slots of the bank and at most 3 new ones.
- **Gate of a new item** (Qwen3.6-27B, chat render, thinking off, greedy + 10 samples at T=0.8
  / top_p 0.95 / 16 tokens; `scripts/qwen_sample_modal.py`, run on 2026-11-20): bank v2's strict
  bar on the item (greedy and 10 of 10 correct, no draw writing an intermediate) and four
  behavioural probes at greedy + 8 of 10: step 1 alone gives intermediate 1; (depth 3) steps
  1-2 give intermediate 2; the last step from the last intermediate gives the answer; the item
  with its first operation altered gives the new answer. 403 construction-valid candidates (240
  depth-2, 163 depth-3; of 1,836 and 1,251,600 generated) -> strict gate 207 and 8 -> with the
  probes 200 and 4 -> 64 and 2 selected, one per class shape per round, round-robin over
  step-kind tuples within a shape. The 138 other passers are a reserve, not in the repo.
- **The builder**, `scripts/build_chain_v3.py` (`candidates`, `requests`, `freeze`, `check`):
  deterministic, reproduces the candidates and, from the gate samples, the bank byte for byte;
  `freeze` refuses an existing file; `check` re-runs every rule and both flaw filters on the
  frozen file (the test suite calls it).
- **Read plan.** Bank v3 has its own 120-row plan (`5966480f...`; bank v2: `bf888e2f...`). The
  54 kept items' rows are identical, so their readouts serve bank v3; drop + add is not a
  drop-only step, so the bank records no `plan_lineage` and a readouts file needs the 66 new
  items read and a sidecar on the new `plan_sha`.
- **Stamp.** `judge.bank_tag(header)`: bank v<N> >= 3 adds `+bank-v<N>` to every RESULT stamp of
  the family, so the registered instrument is
  `chain-mc-2026-10-30+heads-v5+start-op+key-ex2+bank-v3` (`judge.instrument`), a native result
  reads `chain-free-2026-10-30+bank-v3` and an `opts=judge=free` one
  `chain-free-2026-10-30+start-op+bank-v3`, *and `items_v2.json`, `items.json` and the adapted
  banks, whose headers say version 2 or none, keep the stamps they have*. No prompt, gate or
  call key changes (`MC_CALL_VERSION`, `NATIVE_PROMPT_VERSION`), so the kept items' cached judge
  calls replay, *and `NATIVE_PROMPT_VERSION`, which is also the ATI gate's instrument, is
  retained as it is*.
- **Toy readouts.** `examples/readouts/chain_intermediates.jsonl` holds three bank-v3 ids; the
  v1 toy file the v1-era tests score is kept as `tests/fixtures/chain_intermediates_v1_toy.jsonl`.

## One change to the prepared bank

The scratch bank this plan started from (2026-11-20) held `chain-v3-d2p-0010` (34, halve up,
subtract 7) and `chain-v3-d2p-0088` (34, halve down, subtract 5): two step texts, one
computation (34 halved is 17 either way), the kind of pair the vetting reports as "shares first
step". C6 now also keys on (start, first intermediate); `chain-v3-d2p-0088` is out and the next
admissible passer, `chain-v3-d2p-0204`, is in. The other 65 new items are the prepared ones;
21 of them have other MC lists than in the scratch file (the lists are drawn from one seeded
stream). Every one of the 66 has its gate record from the 2026-11-20 run; nothing was re-gated.

## What the refill does to the family

- **Depth 3 falls from 36 items to 7.** 31 of bank v2's 36 depth-3 items had a flaw (28 the
  add-add slot). Under C1 a depth-3 chain alternates adding and scaling; Qwen3.6-27B passes the
  strict gate on 8 of 163 such candidates and the probes on 4 of those (2 more are refused by
  C6: a shared first step, a gold already at its cap). The depth mix was not a target of the
  owner's decision; whether 7 is enough is hers to say (a lower gate bar for depth 3, or more
  candidates, would be a new plan).
- **The 54 kept items were not re-filtered.** None has either flaw the removal was for; 33
  break a rule a new item must satisfy (19 a scale-then-scale slot, 12 a one-step shortcut, 6 a
  round gold, 4 a gold near the start or answer, 4 an operand of 2, 2 a concatenation of prompt
  numerals). The vetting judged them sound.

## Floors (bank v2 -> bank v3, measured 2026-11-23)

- **Lucky guessing** (Opus 5.5, 5 fresh draws, 127 lists): blind 0.103 -> 0.110 ±0.011,
  described 0.133 -> 0.143 ±0.018, seeded-uniform 0.102 -> 0.108; analytic chance 0.092 ->
  0.119 (fewer depth-3 items, which need both lists right).
- **Prompt-only summary** (`po-opus-v1`, reply-free-v2, 0 of 120 refused): 0.967 -> 0.983
  [0.958, 1.000] (kept 53 of 54, new 65 of 66).
- **Logit lens L63**: 0.000 -> 0.000 (0 of 120). All 120 items read in one run by the bundled
  `Producer` (`logit_lens`, `layers=[63]`, one Modal GPU), judged with `layers=63`, frozen with
  `wsbench freeze kind=logit_lens partial=True source=<run record>`.

## Fast subset

chain_intermediates is a core family, so `fast-v4` holds it (60 units of bank v2, pinned by
bank v2's sha256). Re-cut as documented (`evals/fast/README.md`, "Re-cutting"): the next
version with the same command and seed,

```
python scripts/fast_cut_core_half.py --version fast-v5 --seed 20261121
```

`fast_v5.json` differs from `fast_v4.json` in `version` and in chain_intermediates' entry alone
(60 units of bank v3: 23 kept items, 37 new; 13 units in common with fast-v4's). The other 15
families' entries and cut records are byte-identical, so their fast-v4 result rows and FAST
readouts files stay valid (`fast.compatible`, `fast.same_reads`); 1,203 units and 1,441 read
items as before. `fast.DEFAULT` / `VARIANTS` -> `fast-v5`, `fast.VERSIONS` and `KEY_ERA` gain
it, `fast_v4.json` stays registered and frozen (an old fast-v4 directory is reported with
`fast_version=fast-v4`; `fast.entry` fails closed there for chain_intermediates only).

The README's procedure says to re-gate a stale ATI entry first, because the cut reads ATI ids
through `text_inversion.subset_entry`. The cut asks only for the eight strict-ATI families'
entries; chain_intermediates has no ATI id and is not one of them, so the cut ran with its entry
stale (next section) and holds nothing that a re-gate could change, unless a re-gate found 20
ATI items among the 66 new ones.

## ATI: not re-gated; chain_intermediates' stale entry with no id is still "no ATI item"

`evals/baselines/anti_text_inversion.json` does not change (the owner's standing rule), and no
gate was run. The ATI subset is re-checked later in a full audit (issue #559).

- The registered entry of chain_intermediates is gate `panel-v2`, instrument
  `chain-free-2026-10-30`, `n_bank` 120, `n_ati` 0, `ids: []`, guarded by bank v2's `bank_sha`
  (`01c412a7...`). No ATI id is lost: there is none. Its `status` table holds bank v2's 120
  ids, 66 of them no longer in the bank.
- The guard hashes the registered bank's plan rows and items, so ANY bank change stales the
  entry, a drop-only one included (plan 0083 dropped arithmetic's `frac` items and re-derived
  its entry in the ATI file from the stored statuses); a `plan_lineage` does not reach it.
- Left alone, the stale entry would make `text_inversion.subset_entry("chain_intermediates")`
  exit "gated on a different bank ... re-gate" where it raised `NotInScope`: `judge` / `run
  anti_text_inversion=True` would fail the family (exit 2), `wsbench check ati_subset` would
  fail, and `report --fast anti_text_inversion=True` would exit on any fast run directory with
  a chain row (`fast.ati_view` catches `NotInScope` only), i.e. the strict-ATI view of every
  fast run, the family being core (review of PR #551, M1).
- **The rule (the owner's decision, the narrowest form of option (b)): chain_intermediates
  only, listed by name.** `text_inversion.STALE_NO_ITEM_PENDING_AUDIT =
  {"chain_intermediates": <bank v3's bank_fingerprint>}`. In `subset_entry`, an entry whose
  `bank_sha` differs from the bank in use raises `text_inversion.StaleNoItem`, a subclass of
  `NotInScope`, only when the family is in that table AND the bank in use is the one recorded
  there (bank v3: a `WSB_BANK_FILE_*` pin to bank v1, or a later bank v4, exits "re-gate"
  again; review r2, S2) AND the entry's gate is the registered `panel-v2` AND its
  `ids` list is empty; the message says the entry is stale and awaits the audit (#559). *The
  stale check is retained unchanged for every other entry: one with at least one id, a zero-id
  entry of any family not on the list (eight other registered entries hold no id today), and any
  entry of an adapted set's gate (`adapted-panel-v1`) all still exit "gated on a different bank
  ... re-gate"; the instrument-mismatch and retired-gate exits, which come first, are retained
  with no exception.* What the rule does not say: that bank v3 has no ATI item. That is the
  audit's question (Opus read 65 of the 66 new items' intermediates from the prompt in one
  draw, so a survivor of the all-fail rule is unlikely).
- So the family is skipped under `anti_text_inversion=True` and left out of the strict-ATI view
  of a fast run, as before the bank change. `wsbench check ati_subset` passes and its line ends
  with `NOTE: chain_intermediates: entry gated on another bank with no ATI id, served as no ATI
  item on the bank recorded for it until the ATI audit (issue #559)`. The strict-ATI macro, its eight families and
  their 350 ids are not touched.
- Not done: (a) re-gating the entry on bank v3 (the panel of plan 0019), which the audit covers.

## Manifest ledger

Declared with `scripts/manifest_0101_declare.py chain_intermediates --plan 0110 --note ...
--write` (new bank, new stamp); the entry's hash covers the family's rows, its `fast-v5` plan
row included. The other families' `fast-v5` rows are their `fast-v4` rows and need no entry.
The entry was declared a second time within this PR: `STALE_NO_ITEM_PENDING_AUDIT` is a
family-keyed table of `text_inversion`, which the manifest records as a row of
chain_intermediates (`tables`), so the rows hash moved under the same stamp and bank. The tool
refuses that for an entry already in the ledger, so the ledger file was taken from main (where
the family has no entry) and the one entry written again by the tool; no stamp was bumped.
That was clean only because the entry had never been on main. When the audit (#559) re-gates
the entry and takes the name off the table, the row disappears and the rows hash moves again
under the same stamp and bank, with the entry on main: the tool will refuse, and that change
needs a stamp bump or a listed waiver in the tool (as plans 0104 / 0105 / 0107 added for tier
and category rows), not a ledger restore.

## Not in this plan

- The ATI entry (above).
- The adapted sets: every `adapted/<model>/chain_intermediates.json` derives from bank v2 and
  keeps its items and its stamp. `wsbench.adapt`'s chain generator does not apply C1-C6, so a
  refill of an adapted set still writes add-add chains.
- More depth-3 items.
- The native prompt-only entry (`prompt_only.json`, stamped `chain-free-2026-09-16`, never
  drawn).

## Tests

`tests/test_chain_bank_v3.py` (new): the three bank files' sha256; v3 = v2 minus the drop table
plus 66; the filter re-run on the frozen bank (no flaw anywhere, every rule on the new items,
and bank v2 failing it on 64 items); MC lists (kept = v2's, rank balance); the plan (its sha,
kept rows identical, no lineage); the stamp by bank version, on headers and on a call-free
judged row; the prompt-only freeze's accepted stamps; the toy file.

Assertions of existing tests that move, all forced by the bank or the fast version:

- `tests/test_chain_intermediates.py::test_bank_v2`: the registered bank file's name,
  `items_v2.json` -> `items_v3.json` (the bank-v2 assertions below it are unchanged);
  `test_reads_full_rejects_v1_span_file` takes its three v1-era ids from the registered bank
  (bank v2's first three are dropped ids); `EXAMPLE` points at the fixture copy of the v1 toy.
- `tests/test_chain_label_heads.py::test_stamp`: `PROMPT_VERSION == "chain-mc-...+key-ex2"` ->
  `INSTRUMENT_V2 == "chain-mc-...+key-ex2"` and `PROMPT_VERSION == INSTRUMENT_V2 + "+bank-v3"`.
- `tests/golden/plan_sha_pre_0090.json`: chain_intermediates' three values (bank v3's plan).
- `tests/test_fast_core_half.py`: the default version `fast-v4` -> `fast-v5`, its sha256,
  chain_intermediates' fast plan sha, the simulated next version `fast-v5` -> `fast-v6`; new
  test `test_fast_v5_is_fast_v4_recut_for_chain_intermediates_alone`.
- `tests/test_fast_subset.py`, `test_run_wait.py`, `test_run_procs.py`, `test_rename_0101.py`:
  the name of the default version in the assertions that state it, and `fast-v5` in the sets
  of registered versions; `test_rename_0101.FROZEN_FAST_FILES` gains `fast-v4` (a frozen record
  now, sha-pinned), kept out of the "one selection" comparison of the five older files.
- `tests/golden/capable_questions.json`: chain_intermediates' first question (bank v2's first
  item was dropped). `tests/test_adapt_0060_a2c.py::test_chain_gate_is_v2_rule_...` takes
  `chain-d3p-0753` where it took the dropped `chain-d3p-0637` (no assertion moves).
- `scripts/summary_mode_compare.py` `BASE_PAIRS`: the bank-v3 pair of the native and
  `opts=judge=free` stamps.

The stale zero-id ATI entry (section "ATI"). The first version of this PR recorded the entry
as a pending re-gate and inverted five assertions (commit 73e664d5); with the rule above they
are back in their form on main, except where noted:

- `tests/test_ati_freeze.py::_registered_rows`, `tests/test_check_command.py`
  (`test_ati_subset_passes`, `test_the_offline_checks_name_things_by_role`), the comment in
  `tests/test_ati_fingerprint.py`: as on main.
- `tests/test_refilled_banks.py`: `PENDING_REGATE = {}` as on main.
  `test_every_panel_entry_is_gated_on_the_current_bank` leaves out exactly the families of
  `STALE_NO_ITEM_PENDING_AUDIT` (one added clause: the chain entry IS stale by `bank_sha`, so
  "no entry is stale" cannot hold literally; a stale zero-id entry of any other family fails
  it), and a new test holds the list equal to the registered stale zero-id entries.
- `tests/test_text_inversion.py::test_chain_ati_field_unchanged`: `subset_entry` raising
  `NotInScope` on the registered bank, as on main; `entry["bank_sha"] == bank_fingerprint` is
  asserted under a pin to `items_v2.json` (the entry is bank v2's, so the equality with the
  registered bank cannot hold).
- `tests/test_association_v2.py`: unchanged (its bank-v2 pin still gets "re-gate").
- New (`test_stale_entry_without_ids_is_no_ati_item_for_the_listed_family_only`): the listed
  family, stale + zero ids -> `StaleNoItem`; refused with "gated on a different bank": the
  chain entry under a pin to bank v1 and with another recorded bank (a later bank), the
  chain entry given an id, the chain entry under `adapted-panel-v1`, poetry's entry with
  another `bank_sha` with and without ids, association's registered zero-id entry under its
  bank-v2 pin; the instrument mismatch still exits. `check ati_subset` passes on the registered
  tree with the note; `report --fast anti_text_inversion=True` on a fast-v5 directory with a
  poetry and a chain row returns normally and leaves chain out
  (`test_the_strict_ati_view_leaves_a_chain_row_out`); the macro's eight families and 350 ids
  (`test_strict_ati_macro_is_unchanged_by_the_stale_chain_entry`).
