# The fast subsets (`fast-v2`, `fast-safety-v1`)

`fast_v2.json` is the frozen subset behind `--fast`, the subset of record (plan 0094, Camila
2026-11-17): a smaller, higher-signal, item-vetted cut of the Qwen3.6-27B bench. 22 families,
1,823 scored units, 2,160 read items. `fast_safety_v1.json` is the frozen subset behind
`--fast-safety` (plan 0095, Camila 2026-11-18): the same 22 families plus
`jailbreak_recognition` and `agentic_misalignment`, 24 families, 1,996 scored units, 2,351 read
items. Both are defined on the registered Qwen3.6-27B banks only; they change no bank, no family
instrument, no existing result and no ATI entry. Code: `src/wsbench/fast.py` (the files, the
active subset, the per-unit outcomes, the rescore), `readplan.py` (`plan(fast=True)`; the
`punct_special` / `fast_of` positions rules of the two safety families), `reads.py` (loading).

| flag | version | families | units | read items |
|---|---|---|---|---|
| `--fast` | `fast-v2` | 22 | 1,823 | 2,160 |
| `--fast-safety` | `fast-safety-v1` | 24 | 1,996 | 2,351 |

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
  by `run`, exit 2 in `judge` and `plan`). A fast run of them is `--fast-safety` (below).
- For each of the 22 families a `fast-v2` run makes exactly the calls a `fast-v1` run made (a
  cache written under `fast-v1` replays with no new call) and gives the same value; only the
  `fast_subset` stamp differs.
- A readouts file whose sidecar declares `"fast": "fast-v1"` is judged as it is for those 22
  families (same fast plan rows, same `plan_sha`); a new file declares `"fast": "fast-v2"`.
- A `fast-v1` result row of one of the 22 families stays in the macro; a `fast-v1` jailbreak /
  agentic row is listed as excluded (`stale fast subset (fast-v1)`, or the row's own reason first when it is incomplete or has no value). An existing `fast-v1`
  results directory therefore reports the `fast-v2` macro over its 22 rows with no migration.
- The position-reduction rules (`last_n`, `punct_special`, the `+fast-<kind>` stamp) exist only
  in the two safety families' entries (`fast-safety-v1` and `fast-v1`). No `fast-v2` entry has a
  `positions` rule.

## `fast-safety-v1`

`fast_safety_v1.json` (`--fast-safety` = `fast=safety` on `plan`, `produce`, `judge`, `run` and
`report`) is the fast subset with the safety signal: `fast-v2`'s 22 entries plus `fast-v1`'s
`jailbreak_recognition` and `agentic_misalignment` entries, each byte for byte the entry of
`fast_v1.json`. The file differs from `fast_v1.json` in its `version` value only; it has its own
name because `fast-v1` is a retired version and the name says what the subset is.

- The two reduced reads are `fast-v1`'s: `jailbreak_recognition`, 155 items (70 jailbreak, 85
  control) read at punctuation, newline and special-token positions (`punct_special`, stamp
  `+fast-punct_special`); `agentic_misalignment`, 18 pairs (36 read items) read at the last 60
  positions (`last_n` 60, stamp `+fast-last_n60`).
- The cost: the two families take 23 to 38 minutes to judge after their readouts land, against
  1 to 13 minutes for the other 22, and agentic's fast `pair_rate` moves by about 0.07 between
  identical runs, so do not rank arms on it from one run.
- For every one of the 24 families a `--fast-safety` run makes exactly the calls a `fast-v1` run
  made (a `fast-v1` cache replays with no new call) and gives the same value; only the
  `fast_subset` stamp differs. `fast-v2` and `fast-safety-v1` macros are different scales (22
  vs 24 families): never put them in one column without the label.
- Compatibility. `fast-v1`, `fast-v2` and `fast-safety-v1` are mutually entry-compatible
  (`fast.COMPATIBLE`): every family present in two of the files has the identical entry in
  both. So, under `--fast-safety`, `fast-v1` files and rows of all 24 families and `fast-v2`
  files and rows of the 22 are accepted; under `--fast`, `fast-safety-v1` files and rows of the
  22 families are accepted and the two safety rows are excluded (`stale fast subset
  (fast-safety-v1)`). A sidecar's `plan_sha` is checked as its declared version's own
  (`reads.fast_plan_sha(family, declared=)`: the two reduced families' plan rows carry the
  version in `extra.fast`, so their sha differs by version), and a file is refused when its
  declared version's file does not hold the family. Code before plan 0095 refuses or excludes
  anything stamped `fast-safety-v1`.
- A finished `--fast` run becomes a `--fast-safety` run by judging the two safety families into
  the same directory with `wsbench judge family=<f> --fast-safety` (not `run families=...`, which
  rewrites `summary.md` / `run.json` with those two only), then `wsbench report dir=<dir>
  --fast-safety`.
- `report`: `run --fast-safety` prints the 24-family macro itself. A later `wsbench report
  dir=<dir>` without the flag is the `fast-v2` view (it rewrites `summary.md` so) with a hint
  line counting the rows that are in `fast-safety-v1` only; pass `--fast-safety` for the
  24-family macro. `--fast` and `--fast-safety` together: the last one wins.

## How it was chosen

Selected on 23 arms' full results (19 lenses, logit-lens L63, 3 prompt-only draws) and then
vetted item by item. The rules:

- Drop only families that are saturated or basic and do not separate methods:
  `typo`, `association`, `multihop_st`, `multilingual_st`, `chain_intermediates`, `multilingual`. (`jlens_concept_pr` is not in the macro
  and is not in the subset either.)
- Keep `nyt_connections`, `hinted_cutoff`, `user_modeling`, `multihop`.
- Within a kept family, drop questions every trained lens solves, and questions the vetting
  marked `drop` (broken gold, scoring artefact, prompt-guessable).
- The frozen strict ATI subset (`ati-subset-v2`, 350 ids in 8 families) is contained whole: no
  ATI id is ever dropped, whatever the two rules above say (`tests/test_fast_subset.py`).
- `introspection`: only the 125 headline units (`inject|protocol:trial1|b4|*`) and the rows
  their twins read.
- `fast-safety-v1` (and `fast-v1`), `agentic_misalignment`: the 18 pairs whose original misbehaves in at least
  one of the 8 gate rollouts (4 pairs at 0/8 are cut), read at the last 60 positions of each
  item.
- `fast-safety-v1` (and `fast-v1`), `jailbreak_recognition`: 155 of 172 items, read at punctuation, newline and
  special-token positions only.
- `fast-v2`: drop `jailbreak_recognition` and `agentic_misalignment` (above); nothing else
  changes. `fast-safety-v1` keeps them.

Bank or gold fixes the vetting found are not applied here (a separate ATI revision).

## Per-family counts

"Scored units" is what the fast value averages; "read items" is the read-plan rows needed to
score them (a pair is two rows, an introspection headline also needs the rows its twins read, a
`nyt_connections` unit is one slot of a puzzle row). Counted from `fast_v2.json`; the two
rows only `fast-safety-v1` (and `fast-v1`) holds are below its total.

| family | scored units | read items | positions |
|---|---|---|---|
| arithmetic_intermediates | 91 | 91 | full |
| basic_readout_st | 78 | 78 | full |
| basic_readout | 72 | 72 | full |
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
| multihop | 37 | 37 | full |
| multilingual_multihop | 87 | 87 | full |
| multilingual_typo | 86 | 86 | full |
| nyt_connections | 22 | 22 | full |
| poetry | 80 | 80 | full |
| relational_multihop | 100 | 100 | full |
| role_bound_association | 45 | 90 | full |
| user_modeling | 45 | 45 | full |
| wrong_intermediate | 93 | 93 | full |
| **total (`fast-v2`, 22 families)** | **1,823** | **2,160** | |
| agentic_misalignment (`fast-safety-v1` / `fast-v1`) | 18 | 36 | last 60 positions (`last_n`) |
| jailbreak_recognition (`fast-safety-v1` / `fast-v1`) | 155 (70 jailbreak, 85 control) | 155 | punctuation, newline and special tokens (`punct_special`) |
| **total (`fast-safety-v1` / `fast-v1`, 24 families)** | **1,996** | **2,351** | |

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

The frozen files keep the family keys of before plan 0101 (`typo_mt` above is today's `typo`;
`multihop` in a file is today's `multihop_st`): they are frozen bytes, and `fast.subset`
translates the keys at load (`registry.PRE_0101_KEYS`). Everything else in this README uses
today's keys.

- `units`: the scored units by group. Every family has the single group `all`, except
  `jailbreak_recognition` in `fast-safety-v1` and `fast-v1` (`jailbreak`, `control`; value = recall − control
  false-recognition rate, as in the family).
- `read_ids`: the read-plan item ids, in plan order. `wsbench plan --fast` / `--fast-safety`
  writes exactly these rows and judges exactly these items.
- `positions` (optional; the two safety families' entries only): the fast positions rule, applied within
  the family's full positions; absent = the full positions.
- `bank_sha`: `fast.entry` refuses (exit 2) to serve ids for a bank file whose bytes changed,
  and under `WSB_BANK_ROOT` / a `WSB_BANK_FILE_<FAMILY>` pin. The hash covers the registered
  bank file only, not companion files a plan or judge also reads (a header's `read_plan_bank`,
  knowledge_cutoff's `obscure_items.json`, agentic's `targets_v2.json`); id drift in those is
  caught by the freeze test (`read_ids` ⊆ the plan's ids) and by the loader.

## How a fast value is computed

The family judges the fast read items with its own instrument, unchanged (the judge prompts are
verbatim; in `fast-safety-v1` (and `fast-v1`) that includes the two reduced families' scope
sentences, and the `+fast-punct_special` / `+fast-last_n60` result stamp states the reduced read). `fast.rescore` then replaces the value by
the mean over the entry's units (per group; groups combine with the family's signs), with a
percentile bootstrap over units (2,000 resamples, within group, seed 0;
`extras.fast_ci = "unit-bootstrap"`). The families' own cluster bootstraps (hinted_cutoff,
model_multihop; in `fast-safety-v1` (and `fast-v1`) also agentic and jailbreak) are not reproduced, so a fast CI is not the family's
CI. The family's own value stays in `extras.fast_family_value`; a unit without an outcome is
listed in `extras.fast_units_missing`, and more than 10% of them make the result incomplete. The
value recomputed over every unit must reproduce the family's own value, else the result is
incomplete and carries `extras.fast_rescore_mismatch`.

## Re-freezing

A frozen file is never edited in place. A registered bank that changes (any byte) makes
`tests/test_fast_subset.py` and every `--fast` / `--fast-safety` run of that family fail until
the subsets are re-frozen: re-select on that bank, write new versioned files, add them to
`fast.VERSIONS`, point `fast.DEFAULT` / `fast.VARIANTS` at them, and keep the invariants the
tests pin (every family registered and in the macro, `read_ids` ⊆ the plan's ids in plan order,
the strict ATI subset contained whole, `bank_sha` = the registered file's sha256). A re-frozen
family needs new versions of both subsets (`fast-v3` and `fast-safety-v2`), since the two must
keep the identical entry for every family they share.

`fast.COMPATIBLE` is the set of versions that are mutually entry-compatible: for any two of
them, every family present in both files has the identical entry (today `fast-v1`, `fast-v2`,
`fast-safety-v1`; a re-selection of any family's items starts a new set). Result rows of a
compatible version stay in the macro for the families of the active subset, and its readouts
sidecars are accepted. Every other row stamped with another version is left out of the macro
(`stale fast subset (<v>)`).

`fast_v1.json` was selected from judged runs of 23 arms and an item-by-item vetting pass that are
not in this repo (run outputs are never committed); the file itself is the record.
