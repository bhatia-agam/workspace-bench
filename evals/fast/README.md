# The fast subset (`fast-v1`)

`fast_v1.json` is the frozen subset behind `--fast` (plan 0090, Camila 2026-11-15/16): a
smaller, higher-signal, item-vetted cut of the Qwen3.6-27B bench. 24 families,
1,996 scored units, 2,351 read items. It is defined on the registered Qwen3.6-27B banks only;
it changes no bank, no family instrument, no existing result and no ATI entry. Code:
`src/wsbench/fast.py` (the file, the per-unit outcomes, the rescore), `readplan.py` (the
`punct_special` / `fast_of` positions rules, `plan(fast=True)`), `reads.py` (loading).

Its numbers are a different scale from the full bench: fewer families, the easy items removed,
three reads reduced. Never put a fast value beside a full-bench value, a frozen floor or an ATI
value; `wsbench report` refuses to mix them and blanks the floor columns on a fast table.

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
- `agentic_misalignment`: the 18 pairs whose original misbehaves in at least one of the 8 gate
  rollouts (4 pairs at 0/8 are cut), read at the last 60 positions of each item.
- `jailbreak_recognition`: 155 of 172 items, read at punctuation, newline and special-token
  positions only.

Bank or gold fixes the vetting found are not applied here (a separate ATI revision).

## Per-family counts

"Scored units" is what the fast value averages; "read items" is the read-plan rows needed to
score them (a pair is two rows, an introspection headline also needs the rows its twins read, a
`nyt_connections` unit is one slot of a puzzle row). Counted from `fast_v1.json`.

| family | scored units | read items | positions |
|---|---|---|---|
| agentic_misalignment | 18 | 36 | last 60 positions (`last_n`) |
| arithmetic_intermediates | 91 | 91 | full |
| basic_readout | 78 | 78 | full |
| basic_readout_mt | 72 | 72 | full |
| buggy_code | 61 | 122 | full |
| conjunctive_association | 98 | 98 | full |
| directed_modulation | 62 | 62 | full |
| hinted_cutoff | 105 | 210 | full |
| introspection | 125 | 251 | full |
| jailbreak_recognition | 155 (70 jailbreak, 85 control) | 155 | punctuation, newline and special tokens (`punct_special`) |
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
| **total** | **1,996** | **2,351** | |

## The file

```json
{"version": "fast-v1", "subject": "Qwen3.6-27B",
 "dropped_families": ["typo_mt", "..."],
 "families": {"<family>": {
     "bank_sha": "<sha256 of the registered bank file's bytes at freeze>",
     "units": {"<group>": ["<unit id>", "..."]},
     "read_ids": ["<plan item id>", "..."],
     "positions": {"kind": "punct_special"} }}}
```

- `units`: the scored units by group. Every family has the single group `all`, except
  `jailbreak_recognition` (`jailbreak`, `control`; value = recall − control false-recognition
  rate, as in the family).
- `read_ids`: the read-plan item ids, in plan order. `wsbench plan --fast` writes exactly these
  rows; `--fast` judges exactly these items.
- `positions` (optional): the fast positions rule, applied within the family's full positions;
  absent = the full positions.
- `bank_sha`: `fast.entry` refuses (exit 2) to serve ids for a bank file whose bytes changed,
  and under `WSB_BANK_ROOT` / a `WSB_BANK_FILE_<FAMILY>` pin. The hash covers the registered
  bank file only, not companion files a plan or judge also reads (a header's `read_plan_bank`,
  knowledge_cutoff's `obscure_items.json`, agentic's `targets_v2.json`); id drift in those is
  caught by the freeze test (`read_ids` ⊆ the plan's ids) and by the loader.

## How a fast value is computed

The family judges the fast read items with its own instrument, unchanged (the judge prompts are
verbatim, including the two reduced families' scope sentences; the `+fast-punct_special` /
`+fast-last_n60` result stamp states the reduced read). `fast.rescore` then replaces the value by
the mean over the entry's units (per group; groups combine with the family's signs), with a
percentile bootstrap over units (2,000 resamples, within group, seed 0;
`extras.fast_ci = "unit-bootstrap"`). The families' own cluster bootstraps (agentic,
hinted_cutoff, jailbreak, model_multihop) are not reproduced, so a fast CI is not the family's
CI. The family's own value stays in `extras.fast_family_value`; a unit without an outcome is
listed in `extras.fast_units_missing`, and more than 10% of them make the result incomplete. The
value recomputed over every unit must reproduce the family's own value, else the result is
incomplete and carries `extras.fast_rescore_mismatch`.

## Re-freezing

The file is never edited in place. A registered bank that changes (any byte) makes
`tests/test_fast_subset.py` and every `--fast` run of that family fail until the subset is
re-frozen: re-select on that bank, write a new versioned file (`fast_v2.json`), bump
`fast.VERSION` / `fast.PATH`, and keep the invariants the tests pin (every family registered
and in the macro, `read_ids` ⊆ the plan's ids in plan order, the strict ATI subset contained
whole, `bank_sha` = the registered file's sha256). Results stamped with an older version are
left out of the macro (`stale fast subset (<v>)`).

`fast_v1.json` was selected from judged runs of 23 arms and an item-by-item vetting pass that are
not in this repo (run outputs are never committed); the file itself is the record.
