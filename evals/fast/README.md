# The fast subset (`fast-v2`)

`fast_v2.json` is the frozen subset behind `--fast`, the subset of record (plan 0094, Camila
2026-11-17): a smaller, higher-signal, item-vetted cut of the Qwen3.6-27B bench. 22 families,
1,823 scored units, 2,160 read items. It is defined on the registered Qwen3.6-27B banks only;
it changes no bank, no family instrument, no existing result and no ATI entry. Code:
`src/wsbench/fast.py` (the files, the per-unit outcomes, the rescore), `readplan.py`
(`plan(fast=True)`; the `punct_special` / `fast_of` positions rules of `fast-v1`), `reads.py`
(loading).

Its numbers are a different scale from the full bench: fewer families, the easy items removed,
introspection's read reduced. Never put a fast value beside a full-bench value, a frozen floor
or an ATI value; `wsbench report` refuses to mix them and blanks the floor columns on a fast
table.

## `fast-v2` and `fast-v1`

`fast_v1.json` (plan 0090, Camila 2026-11-15/16; 24 families, 1,996 scored units, 2,351 read
items) is kept frozen, byte for byte (its sha256 is pinned in `tests/test_fast_subset.py`).
`fast_v2.json` is that file without `jailbreak_recognition` and `agentic_misalignment`: the
other 22 entries are identical (`bank_sha`, `units`, `read_ids`, key order), and
`dropped_families` lists the two after v1's six. Why they were dropped ("exclude jailbreak and
agentic"), measured on the fast subset with s3d-rl600 on 2026-11-17:

- they take 23 to 38 minutes to judge after their readouts land, against 1 to 13 minutes for
  the other 22 families, so they alone hold a fast run above 30 minutes;
- they change no ordering of the measured arms: without them each arm's fast macro moves by at
  most 0.028 (s3d .535 -> .538, rl-affw .491 -> .497, Q9 .478 -> .484, NLA .442 -> .449,
  prompt-only .475 -> .480, J-lens .116 -> .119, logit lens .063 -> .067);
- agentic's fast `pair_rate` also moves by about 0.07 between identical runs.

What this means in use:

- `--fast` is `fast-v2`; `fast-v1` is not selectable from the CLI. Under `--fast` the two
  families are outside the subset like any dropped family ("<family>: not in fast-v2": skipped
  by `run`, exit 2 in `judge` and `plan`). A `fast-v1` run of them needs the commit before plan
  0094.
- For each of the 22 families a `fast-v2` run makes exactly the calls a `fast-v1` run made (a
  cache written under `fast-v1` replays with no new call) and gives the same value; only the
  `fast_subset` stamp differs.
- A readouts file whose sidecar declares `"fast": "fast-v1"` is judged as it is for those 22
  families (same fast plan rows, same `plan_sha`); a new file declares `"fast": "fast-v2"`.
- A `fast-v1` result row of one of the 22 families stays in the macro; a `fast-v1` jailbreak /
  agentic row is listed as excluded (`stale fast subset (fast-v1)`, or the row's own reason first when it is incomplete or has no value). An existing `fast-v1`
  results directory therefore reports the `fast-v2` macro over its 22 rows with no migration.
- The position-reduction rules (`last_n`, `punct_special`, the `+fast-<kind>` stamp) exist only
  in `fast-v1`'s two entries; the code keeps them for that frozen file and its tests. No
  `fast-v2` entry has a `positions` rule.

## How it was chosen

Selected on 23 arms' full results (19 lenses, logit-lens L63, 3 prompt-only draws) and then
vetted item by item. The rules:

- Drop only families that are saturated or basic and do not separate methods:
  `typo_mt`, `association`, `multihop`, `multilingual`, `chain_intermediates`, `multilingual_mt`. (`jlens_concept_pr` is not in the macro
  and is not in the subset either.)
- Keep `nyt_connections`, `hinted_cutoff`, `user_modeling`, `multihop_mt`.
- Within a kept family, drop questions every trained lens solves, and questions the vetting
  marked `drop` (broken gold, scoring artefact, prompt-guessable).
- The frozen strict ATI subset (`ati-subset-v2`, 350 ids in 8 families) is contained whole: no
  ATI id is ever dropped, whatever the two rules above say (`tests/test_fast_subset.py`).
- `introspection`: only the 125 headline units (`inject|protocol:trial1|b4|*`) and the rows
  their twins read.
- `fast-v1` only, `agentic_misalignment`: the 18 pairs whose original misbehaves in at least
  one of the 8 gate rollouts (4 pairs at 0/8 are cut), read at the last 60 positions of each
  item.
- `fast-v1` only, `jailbreak_recognition`: 155 of 172 items, read at punctuation, newline and
  special-token positions only.
- `fast-v2`: drop `jailbreak_recognition` and `agentic_misalignment` (above); nothing else
  changes.

Bank or gold fixes the vetting found are not applied here (a separate ATI revision).

## Per-family counts

"Scored units" is what the fast value averages; "read items" is the read-plan rows needed to
score them (a pair is two rows, an introspection headline also needs the rows its twins read, a
`nyt_connections` unit is one slot of a puzzle row). Counted from `fast_v2.json`; the two
`fast-v1`-only rows are below the total.

| family | scored units | read items | positions |
|---|---|---|---|
| arithmetic_intermediates | 91 | 91 | full |
| basic_readout | 78 | 78 | full |
| basic_readout_mt | 72 | 72 | full |
| buggy_code | 61 | 122 | full |
| conjunctive_association | 98 | 98 | full |
| directed_modulation | 62 | 62 | full |
| hinted_cutoff | 105 | 210 | full |
| introspection | 125 | 251 | full |
| knowledge_cutoff | 143 | 143 | full |
| model_multihop | 91 | 91 | full |
| model_specific_directed_modulation | 94 | 94 | full |
| moral_rationale | 106 | 106 | full |
| multi_concept_directed_modulation | 102 | 102 | full |
| multihop_mt | 37 | 37 | full |
| multilingual_multihop | 87 | 87 | full |
| multilingual_typo | 86 | 86 | full |
| nyt_connections | 22 | 22 | full |
| poetry | 80 | 80 | full |
| relational_multihop | 100 | 100 | full |
| role_bound_association | 45 | 90 | full |
| user_modeling | 45 | 45 | full |
| wrong_intermediate | 93 | 93 | full |
| **total (`fast-v2`, 22 families)** | **1,823** | **2,160** | |
| agentic_misalignment (`fast-v1` only) | 18 | 36 | last 60 positions (`last_n`) |
| jailbreak_recognition (`fast-v1` only) | 155 (70 jailbreak, 85 control) | 155 | punctuation, newline and special tokens (`punct_special`) |
| **total (`fast-v1`, 24 families)** | **1,996** | **2,351** | |

## The file

```json
{"version": "fast-v2", "subject": "Qwen3.6-27B",
 "dropped_families": ["typo_mt", "..."],
 "families": {"<family>": {
     "bank_sha": "<sha256 of the registered bank file's bytes at freeze>",
     "units": {"<group>": ["<unit id>", "..."]},
     "read_ids": ["<plan item id>", "..."],
     "positions": {"kind": "punct_special"} }}}
```

- `units`: the scored units by group. Every family has the single group `all`, except
  `fast-v1`'s `jailbreak_recognition` (`jailbreak`, `control`; value = recall − control
  false-recognition rate, as in the family).
- `read_ids`: the read-plan item ids, in plan order. `wsbench plan --fast` writes exactly these
  rows; `--fast` judges exactly these items.
- `positions` (optional; `fast-v1`'s two entries only): the fast positions rule, applied within
  the family's full positions; absent = the full positions.
- `bank_sha`: `fast.entry` refuses (exit 2) to serve ids for a bank file whose bytes changed,
  and under `WSB_BANK_ROOT` / a `WSB_BANK_FILE_<FAMILY>` pin. The hash covers the registered
  bank file only, not companion files a plan or judge also reads (a header's `read_plan_bank`,
  knowledge_cutoff's `obscure_items.json`, agentic's `targets_v2.json`); id drift in those is
  caught by the freeze test (`read_ids` ⊆ the plan's ids) and by the loader.

## How a fast value is computed

The family judges the fast read items with its own instrument, unchanged (the judge prompts are
verbatim; in `fast-v1` that included the two reduced families' scope sentences, and the
`+fast-punct_special` / `+fast-last_n60` result stamp stated the reduced read). `fast.rescore` then replaces the value by
the mean over the entry's units (per group; groups combine with the family's signs), with a
percentile bootstrap over units (2,000 resamples, within group, seed 0;
`extras.fast_ci = "unit-bootstrap"`). The families' own cluster bootstraps (hinted_cutoff,
model_multihop; in `fast-v1` also agentic and jailbreak) are not reproduced, so a fast CI is not the family's
CI. The family's own value stays in `extras.fast_family_value`; a unit without an outcome is
listed in `extras.fast_units_missing`, and more than 10% of them make the result incomplete. The
value recomputed over every unit must reproduce the family's own value, else the result is
incomplete and carries `extras.fast_rescore_mismatch`.

## Re-freezing

A frozen file is never edited in place. A registered bank that changes (any byte) makes
`tests/test_fast_subset.py` and every `--fast` run of that family fail until the subset is
re-frozen: re-select on that bank, write a new versioned file (`fast_v3.json`), add it to
`fast.VERSIONS` and bump `fast.VERSION`, and keep the invariants the tests pin (every family
registered and in the macro, `read_ids` ⊆ the plan's ids in plan order, the strict ATI subset
contained whole, `bank_sha` = the registered file's sha256). An older version belongs in
`fast.COMPATIBLE` only while every family of the new subset has the identical entry in it (as
`fast-v1` has for `fast-v2`; a re-selection of any family's items ends that): result rows of a
compatible older version stay in the macro for the families still in the subset, and its
readouts sidecars are accepted. Every other row stamped with an older version is left out of
the macro (`stale fast subset (<v>)`).

`fast_v1.json` was selected from judged runs of 23 arms and an item-by-item vetting pass that are
not in this repo (run outputs are never committed); the file itself is the record.
