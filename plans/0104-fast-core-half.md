# 0104: the fast subset is a seeded random half of core

Camila, 2026-11-21: "make the updated version of the fast subset to be the core subset but with
a random seed choosing half the questions per eval family." Rulings given with it:

1. `jailbreak_recognition` and `agentic_misalignment` are excluded from fast.
2. The one exception to "random half": fast contains the FULL strict ATI subset.
3. It will be re-cut, same seed, when core's banks change (chain_intermediates' refilled bank
   and two new hard banks are coming), so the cut is one reproducible command.

And, the same day: "conjunctive association should be in core" (its own commit: core is 18
families; conjunctive_association is then an ordinary fast family).

## Why

`fast-v1` .. `fast-v3` were selected on outcomes: families that did not separate 23 arms were
dropped, and within a family the questions every trained lens solved, then an item-by-item
vetting pass. That made a sharp subset for those arms and a biased one for any new method, and
it could not be redone when a bank changed (the judged runs behind it are not in the repo).
A random half of the default tier needs no judged run, cannot favour a method, and is one
command.

## What `fast-v4` is

- **Families**: `tiers.CORE` minus the two safety families: 16 families.
- **Units**: per family `ceil(n / 2)` of its scored units, `n` = what the family's headline
  averages. The unit and the read rows it needs follow the conventions of `fast.units` and of
  the older files, derived from the registered bank and read plan alone
  (`scripts/fast_cut_core_half.py`, `UNITS`):

  | family | unit | read rows of a unit | stratum |
  |---|---|---|---|
  | buggy_code | pair (the clean twin's id) | both members | none |
  | hinted_cutoff | pair (`pair_id`) | the I and the N item | none |
  | role_bound_association | direction pair (`pair_id`, both directions in the bank) | both | none |
  | introspection | headline inject item | its row and the rows its twins read | none |
  | nyt_connections | stable slot `cNNNN|sK` | its puzzle | none |
  | multi_concept_directed_modulation | item with at least one concept (the 2 controls are never scored) | itself | the bank's `stratum` (concept count / relation) |
  | moral_rationale | item | itself | committed / deliberative (`must_surface_both`) |
  | model_multihop | item | itself | invented / cutoff (`cat`) |
  | knowledge_cutoff | item (plan row) | itself | frozen / nocot |
  | arithmetic_intermediates | item | itself | expression shape (`variant`) |
  | every other family | item (plan row) | itself | none |

- **The draw** (`draw`): `random.Random(f"{seed}|{registry.frozen_name(family)}")` over the
  family's units sorted by id; seed 20261121, chosen before any outcome was looked at and
  recorded in the file. The pre-0101 name keys the stream, so a rename never moves a draw; the
  version is NOT in the key (it was in the first cut of fast-v4, which was re-cut in place
  before merge).
  1. Every unit of the family in the registered strict ATI subset (`ati-subset-v2`) is taken.
  2. `n_total = max(ceil(n / 2), n_ati)`. The remaining `n_random = n_total - n_ati` units are
     drawn from the non-ATI units.
  3. **Strata, precisely (this is not "half of each stratum").** With `m_k` the non-ATI units
     of stratum k and `m` their sum, stratum k gets `n_random * m_k / m` random units: the
     floors first, then one more each to the largest fractional remainders until `n_random`
     is reached, ties to the stratum that sorts first. Then `rng.sample(sorted non-ATI units
     of k, quota_k)`, strata in sorted order. The ATI units of a stratum come on top of its
     quota, so a stratum rich in ATI units ends above half of its units and one poor in them
     below (moral_rationale: deliberative 18 ATI + 3 random of 29, committed 38 + 39 of 166;
     knowledge_cutoff: nocot 16 + 7 of 39, frozen 23 + 28 of 108). In a family with no ATI
     unit the quota is proportional to stratum size: half of each stratum up to rounding.
- **Positions**: every family's full read positions; no reduced-position rule (those existed
  only in the two safety families' entries).
- **The file** (`evals/fast/fast_v4.json`): `version`, `subject`, `seed`, `rule`,
  `excluded_families`, `cut` (per family `n_units`, `n_ati`, `n_random`, `n_total`,
  `n_read_ids`, `stratum_key`, per-stratum counts) and `families` (entries of the same shape as
  every earlier version: `bank_sha`, `units`, `read_ids`).
- **Counts**: 1,203 units, 1,441 read items (fast-v3: 22 families, 1,823 / 2,160).

A family's draw depends on the seed, its pre-0101 name and its own units, strata and ATI ids,
nothing else: not the version, not another family. Adding or removing a family, or changing
another family's bank, moves no other family's units, within a version and across versions. A
re-cut as fast-v5 after one family's bank changed therefore leaves every other family's entry
(`bank_sha`, `units`, `read_ids`) and `cut` row byte-identical, so their fast results and FAST
readouts stay valid (`fast.compatible`, `fast.same_reads`); the test simulates exactly that.

## The ATI exception is a bias, stated

The ATI units are not a random sample: they are the items no text-only reader solved. A
family's fast value is therefore pulled toward its ATI items by `n_ati / n_total`:
introspection 124/124, wrong_intermediate 42/50, moral_rationale 56/98, knowledge_cutoff 39/74,
conjunctive_association 26/50, model_specific_directed_modulation 25/49, poetry 16/50,
model_multihop 22/142; the eight other families have none. The README carries the table and
the size of the effect measured on existing full results.

## `--fast-safety` is retired

With the two safety families out of fast, the variant has nothing to select. `--fast-safety` /
`fast=safety` is a usage error on every command that says what to run instead
(`fast.RETIRED_VARIANTS`); `fast-safety-v1` / `-v2` stay registered and frozen. So that old
results stay readable, `wsbench report` takes `fast_version=<registered version>`: it reports a
directory under the version that produced it (`fast.use`). No strong reason to keep the flag
was found: the reduced-position machinery it exercised stays tested through the frozen files.

## Existing readouts and results

- **Results**: every fast-v1 / v2 / v3 / fast-safety row is `stale fast subset (<v>)` under
  fast-v4 (no entry is identical); `report fast_version=<v>` reports an old directory as it was.
- **FAST readouts files** of older versions hold other read ids than fast-v4 needs, so they are
  refused (`same_reads`: other items). **Full-family readouts files remain valid inputs**: a
  fast run is always judged from a full file, which `reads.load` narrows to the fast read ids.

## Code

- `scripts/fast_cut_core_half.py --version fast-v4 --seed 20261121 [--check]`: deterministic,
  refuses an existing target, refuses a strict-ATI family outside the family list. It reads
  the ATI ids through `text_inversion.subset_entry`, so an entry gated on another instrument
  or bank stops the cut, and it refuses `WSB_BANK_ROOT`, a `WSB_BANK_FILE_*` pin of one of its
  families, `WSB_NO_NYT` and `WSB_NO_NOCOT` up front. Offline only with a warm `$WSB_CACHE`:
  the plans of nyt_connections and of knowledge_cutoff's nocot rows render from their pinned
  sources.
- `fast.py`: `fast-v4` in `VERSIONS` / `KEY_ERA` ("0101"), `DEFAULT`, `VARIANTS = {"": DEFAULT}`,
  `RETIRED_VARIANTS`, `use(version)`.
- `cli.py`: `_fast_arg` refuses a retired variant; `report fast_version=`; `fast_header` names
  `fast_version=` for rows of other registered versions.
- `scripts/manifest_0101_declare.py`: (a) a fast version that reads a family differently from
  every golden version (a re-selection) has a fast plan of its own, so its row is set aside
  (`reselected`, computed with `fast.same_reads`); (b) **a tier move is declared by listing
  it**: `TIER_MOVES = {"conjunctive_association": ("full", "core")}` (`family -> (tier before,
  tier today)`, in the style of `CATEGORY_MOVES`). For a listed family that holds the listed
  tier, its two tier rows (`list.tier`, its `tiers.CORE` membership) are read as they were
  before the move, before the comparison and before the ledger hash (`tier_moved`). Neither
  (a) nor (b) stales a ledger entry. The invariants of the earlier plans are retained:
  `tests/golden/manifest_0101_pre.json` is never regenerated; an instrument row (stamps,
  prompts hash, bank hash, metric, run rows) that moves without a stamp or bank bump still
  fails T1; **an unlisted family's tier row or core membership is such a row and fails T1
  too**, as does a listed family in any tier but the listed one; and the ledger changes only
  through `scripts/manifest_0101_declare.py ... --write`.
  Why the listing is set aside before the ledger hash rather than declared by an entry of its
  own, as a category move is: the ledger holds one entry per family, and
  conjunctive_association's is taken by its bank-v6 declaration, whose stamp and bank are
  today's; a second declaration under the same stamp and bank would be a re-hash, which
  `declare` refuses by design. Set aside before the hash, the listed move leaves that entry
  valid, and a family registered after the golden (no golden row; its entry holds the tier it
  was declared with) can change tier later by the same listing, with no stamp bump. The fast
  re-selection itself needs no tier move: the two safety families left the fast subset, not
  their tier.
- `fast.ati_view(result)` and `wsbench report dir=<dir> --fast anti_text_inversion=True`: the
  strict-ATI table and macro of a fast run, with no new judging. Each fast row is restricted
  to the ids of its registered ATI entry (its per-unit outcomes from `fast.units`, the value
  by the family's own rule over them) and stamped as `runner` stamps a real ATI run, so
  `results.macro` applies its ATI rules unchanged (`n >= 20` plus `ATI_MACRO_EXCEPTIONS`, the
  gate and subset stamps). A family the ATI scope leaves out has no row; a usage error
  without `--fast`; nothing is written. **Same value as a real `anti_text_inversion=True` run
  over the same readouts** for the eight strict-ATI families, whose unit verdicts do not
  depend on which other items are judged. What differs: the CI (the fast unit bootstrap, not the family's own, e.g.
  model_multihop's cluster bootstrap); a gated id without an outcome is left out of the value
  and counted in `n_items_undecided` (over 10%: incomplete). `STRICTER_PASS_FIELD`
  (knowledge_cutoff: the panel's `ati_pass`) and `GATE_ANY_BASIS` are rules of the GATE
  (`text_inversion.draw_verdicts`: which panel answer counts as solving an item, hence which
  ids are gated); a lens run is scored on its headline pass field in an ATI run and in the
  view alike, so they make no difference between the two.
- No `ati_only` mechanism: with conjunctive_association in core all eight strict-ATI families
  are fast families.

- Viewer (`viewer/ingest/wsb.py`, `viewer/query.py`): the store subset `fast` is the default
  selection only. A fast run is stored under `fast` when every row is stamped with
  `fast.DEFAULT` or a version `fast.compatible` with it for that family, otherwise under the
  version it names (`fast-v3`; `query.subset_title` gives it a title), the safety versions
  under `fast-safety` as before. The ingest signature holds `fast.DEFAULT`, so a full run
  ingested under an earlier default is re-derived instead of skipped; the `fast` membership
  rows are deleted before the frozen file's membership is written (a function of the file,
  not of the run; never a union of two selections); a fast run's membership is read per
  family from each row's own stamp, and an unstamped row has none.
- `runner.run_families`: a fast run in process mode exits when the active version is not a
  selectable one (a child is told `fast=True` and judges `fast.DEFAULT`).

## Tests

`tests/test_fast_core_half.py` (determinism, `--check`, `n_total == max(ceil(n/2), n_ati)`, ATI
containment, strata, independence, safety families `NotInFast`, the retired flag, plan / run /
report smoke, old directories under `fast_version=`, a simulated fast-v5 re-cut with one
family's units changed (every other entry and `cut` row equal), the ATI view on synthetic rows
of seven strict-ATI families (view value == the family's unit rule on rows holding only the
gated ids; moral_rationale is left out, its rows need the judge's shape) and its CLI). `tests/test_fast_subset.py` keeps its
assertions by running on the versions it was written for (an autouse fixture makes fast-v3
active); the changed assertions are listed in the PR text. T1: no ledger entry is staled.

## Validation (existing data, no new judging)

The 23-arm full-bench unit matrix (`/root/tmp/wsb-fast/out/matrix.json`, older instruments for
nyt_connections and conjunctive_association, one knowledge_cutoff item missing): core macro on
all units vs the fast-v4 macro, per-family differences, the rank correlation of the arms, the
spread of the fast macro over 200 re-drawn seeds, and each ATI family's fast value on all fast
units vs the random part only. Numbers in `evals/fast/README.md`; an estimate, not a
measurement on today's instruments.

`tests/test_fast_core_half.py` also pins the 16 `reads.fast_plan_sha` values
(`V4_FAST_PLAN_SHA`; T1 sets a re-selected version's rows aside, so nothing else would notice
a change to how a fast row is built or hashed), runs `wsbench judge --fast` end to end under
the default subset on buggy_code (pairs) and nyt_connections (stable slots) with scripted
judges, and is part of `wsbench check frozen_pins`. T10 holds the selectable version to
today's banks and the older versions to their own bytes and to each other. Viewer:
`tests/test_viewer.py` (one selection per view, the signature, no union, per-family
membership, numeric version order).

## Notes from review (recorded, not acted on)

- **`largest_remainder` works in floats, and `rng.sample` is stable across today's CPython
  versions but not guaranteed by the language.** Two strata of different size with equal true
  remainders could tie differently under another rounding; `divmod(total * n, pool)` would be
  exact. Left as is: changing either could move the frozen file, and the file's sha256 pin
  plus the rebuild in the test (`--check`) catch any platform or version on which the draw
  differs. A re-cut on another Python is checked the same way before it is frozen.
- **role_bound_association's registered ATI entry (3 ids) is not forced into the cut.** It is
  below the strict macro's minimum, so "the strict ATI subset whole" holds as written;
  `fast.ati_view` returns no row for the family, where a real ATI run gives a row the macro
  excludes for `n < 20`. No macro effect.
- **introspection is not halved.** 124 of its 125 units are ATI ids, so fast reads 250 of its
  rows (fast-v3 read 251) and its fast value is its ATI value. This is the ATI exception
  applied as stated, and the family where "half" is furthest from what a reader expects.

## Open points (for the owner)

1. **The ATI exception costs about 0.02 of macro; an alternative is measured, not adopted.**
   *Adopted (fast-v4):* the strict-ATI ids are scored fast units. *Alternative:* the fast value
   of a family is computed on a seeded random half of ALL its units (`ceil(n / 2)`, ATI units
   in it only by chance); every strict-ATI id is read in addition, so the ATI view still
   works. From the 23-arm matrix (same caveats as Validation), macros over the 16 families:

   | arm | core, all units | adopted, this seed | adopted, 200 seeds mean ± sd | alternative, this seed | alternative, 200 seeds mean ± sd |
   |---|---|---|---|---|---|
   | s3d-rl600 | 0.439 | 0.433 | 0.417 ± 0.011 | 0.461 | 0.440 ± 0.011 |
   | rl-affw-x4 | 0.411 | 0.410 | 0.399 ± 0.009 | 0.431 | 0.412 ± 0.010 |
   | mlnla11-rl600 | 0.312 | 0.300 | 0.295 ± 0.010 | 0.319 | 0.313 ± 0.010 |
   | jlens-public | 0.149 | 0.138 | 0.140 ± 0.005 | 0.151 | 0.149 ± 0.006 |
   | logitlens-L63 | 0.058 | 0.053 | 0.057 ± 0.004 | 0.053 | 0.058 ± 0.004 |
   | po-draw0 | 0.445 | 0.440 | 0.421 ± 0.008 | 0.461 | 0.446 ± 0.009 |

   Over all 23 arms and 200 seeds the adopted design sits -0.0186 from the core macro, the
   alternative +0.0003 (unbiased), with the same seed noise (sd 0.0087 vs 0.0094).
   For the chosen seed alone the alternative happens to land further from core (mean
   |fast - core| 0.0143 vs 0.0088; Spearman of the arms 0.990 vs 0.996): one draw, within the
   seed noise. Read items: adopted 1,441, alternative 1,564 (+123).

   Per family, s3d-rl600:

   | family | all units | adopted fast | alternative fast | reads adopted | reads alternative |
   |---|---|---|---|---|---|
   | arithmetic_intermediates | 0.394 | 0.412 | 0.412 | 240 | 240 |
   | buggy_code | 0.375 | 0.469 | 0.469 | 64 | 64 |
   | chain_intermediates | 0.133 | 0.183 | 0.183 | 60 | 60 |
   | conjunctive_association | 0.320 | 0.280 | 0.380 | 50 | 63 |
   | hinted_cutoff | 0.034 | 0.017 | 0.017 | 118 | 118 |
   | introspection | 0.512 | 0.508 | 0.540 | 250 | 251 |
   | knowledge_cutoff | 0.274 | 0.301 | 0.203 | 74 | 99 |
   | model_multihop | 0.912 | 0.887 | 0.915 | 142 | 154 |
   | model_specific_directed_modulation | 0.265 | 0.286 | 0.286 | 49 | 66 |
   | moral_rationale | 0.610 | 0.510 | 0.622 | 98 | 120 |
   | multi_concept_directed_modulation | 0.465 | 0.456 | 0.456 | 57 | 57 |
   | nyt_connections | 0.629 | 0.689 | 0.689 | 43 | 43 |
   | poetry | 0.500 | 0.480 | 0.540 | 50 | 60 |
   | relational_multihop | 0.830 | 0.860 | 0.860 | 50 | 50 |
   | role_bound_association | 0.348 | 0.304 | 0.304 | 46 | 46 |
   | wrong_intermediate | 0.430 | 0.280 | 0.500 | 50 | 73 |

   *What would change in the code* (nothing of this is implemented): the cut's `draw` loses
   the ATI-first step (`n_total = ceil(n / 2)`, strata proportional to stratum size) and the
   entry gains a field: `units` = the random half (the value), `read_ids` = the rows of the
   half UNION the rows of the ATI ids. `fast.units` / `rescore` already score only `units`,
   so the headline needs nothing; `fast.ati_view` would take its outcomes from the judged
   rows of the ATI ids rather than from `units` (today it requires the gated ids to be fast
   units), which needs the per-family unit extraction to run on an explicit id list. The
   count rule in `tests/test_fast_core_half.py` (`TABLE`, `n_total == max(...)`), the
   containment test and the README tables change; it is a new version (fast-v5), since every
   ATI family's entry changes, and its rows stale fast-v4's for those eight families only.
2. **Strata of the random part** are proportional to the non-ATI units of each stratum, not to
   the whole family (kept, by the coordinator's ruling; stated precisely above and in the
   README).
3. The chosen seed draws high for some arms (its fast macro is above the 200-seed mean for
   s3d-rl600, rl-affw-x4 and prompt-only), so fast-v4's macro is closer to the core macro than
   the design's expected 0.02 offset. The seed is not changed.
