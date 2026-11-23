# Plan 0116: association_hard bank v3 (four known-issue items dropped, a strictly gated refill toward 100)

Camila, 2026-11-23: drop the four items the family README lists as known issues and refill the
bank toward 100 items with new items made by the same recipe and the same gate; each new
candidate is gated on ONE gating run (an item that fails that run and would pass a second is
dropped, not admitted); report the yield honestly if it falls short of 100, loosen nothing.

Base: `origin/main` @ 3fd1035d. Worktree `/root/tmp/wsb-0116`, branch
`camila/0116-assoc-hard-v3`. Scratch (not durable, outside the repo): `/root/tmp/assoc-hard/v3/`.

**What does not move.** `CALL_VERSION` (`assoc-hard-v1`), every judge prompt, `gate.py` and
`GATE_VERSION` (`gate-h2`, its sha256 pin), the read plan's shape (the 19 summarize-suffix and
chat-tail sites, layers 20..60), `bank.STAMP` (the option-order seed), `items.json` (bank v2,
byte-identical, with its four frozen inputs and its builder), the tier (`full`; `tiers.py`,
`evals/fast/`, `evals/residuals/` are not touched: another branch moves the family), `adapted/`,
`evals/baselines/anti_text_inversion.json`, `tests/golden/manifest_0101_pre.json`, and
everything of `association`. The stamp becomes `assoc-hard-v1+gate-h2+bank-v3` (`BANK_TAG`
only).

## 1. The four drops (builder table `V3_DROP`, echoed in `edits.v3.dropped_from_v2`)

| item | gold | reason |
|---|---|---|
| `ah-b1-ob32-farm-milk-sugar-prism` | a refractometer | blind-guessable: the blind guesser picks it 14 times of 20 over the four measurements that exist (5 and 2 of 5 in `reguess_v1.json`, 3 and 4 on the two floor runs); it stayed in v2 because one gating measurement was under 3 of 5 |
| `ah-b2-ob06-zampogna-presepe-montano` | una zampogna | accepted forms `Italian bagpipe` / `意大利风笛` also fit the distractor `una piva` |
| `ah-b2-ob18-festival-shirt-spirals` | tie-dye | accepted forms `扎染` / `绞缬` also fit the distractor `shibori` |
| `ah-b2-ob26-railway-sky-white-ring` | a solar halo | accepted form `a ring around the sun` also fits the distractor `a corona` |

(The first name is read from the bank at build time; the builder refuses a table entry that is
not a v2 item.) The other 52 items of v2 are carried **byte-identical per item** (scene,
options, order, forms, gate and guess records); they are not re-gated and their forms are not
re-derived. Bank v2 kinds: 30 obscure, 9 complex_qualified, 17 complex_unnatural; kept: 26 / 9 / 17.

## 2. New candidates: the v2 recipe, one gating run per gate

Target 48 new items in v2's proportions (0.54 / 0.16 / 0.30 of 100, minus the kept): **28
obscure, 7 complex_qualified, 13 complex_unnatural.** v2's end-to-end yield was 56 of 323
authored (obscure 23%, complex_qualified 9%, complex_unnatural 18%); the wave is sized for a
lower yield (§2.3 is stricter than v2's rule).

### 2.1 Authoring, lint, options (the authoring run's scripts, verbatim prompts)

The scripts of the v2 authoring run (`/root/tmp/assoc-hard/full/scripts/`: `author.py`,
`briefs.py`, `lint.py`, `options.py`, `grade.py`, `domains.py`, `build_B.py`'s alias
extension) are copied to scratch and run with their prompts unchanged (`INTRO`, `FAIR["B"]`,
`RULES`, the three `B_*` kind texts, the b1-gate lessons of waves b2 / b3, `options.SYSTEM` with
the `samecat` and `balanced` recipes, `ALIAS_SYSTEM`, `SCREEN_SYSTEM`, `STRICT_SYSTEM`; Opus 5.5,
low effort for authoring, 7 items and 2 non-English per call). Only paths, the library import
path (the family moved under `association/association/` in plan 0101) and the wave tags change.

- Two authoring sub-waves, `b4` then `b5`, both written before anything is gated; `b5`'s avoid
  lists hold `b4`'s golds. Palettes: every design-B gold palette of waves b1 to b3 (obscure 14,
  complex_qualified 10 one-word-head palettes of b2 / b3, complex_unnatural 10 of b2 / b3: the
  two forms that passed), each once per sub-wave, sub-wave b4 with the first settings list and
  b5 with the second. Lessons: b3's text (with its domain-steering paragraph) for b3's
  palettes, b2's text (the same lessons without that paragraph) for the others. 68 batches,
  476 items asked for.
- Lint as v2 (`wsbench.adapt.lint` guards, no content word of the gold in the scene, 1 to 3
  sentences, dedupe against both pilot waves, the registered `association` bank and every
  earlier kept candidate, so no gold of the 109 can come back, the four drops included).
- Options as v2 (`options.py`: obscure = seven members of the gold's fine category; complex =
  the balanced grid; its own blind-leak loop while writing a list, the alias audit, the scene
  screen 5 of 5).

### 2.2 The subject gate: ONE run

One Modal run of `scripts/qwen_sample_modal.py` (the script v2 used; `modal run`, an ephemeral
app, nothing deployed) over every screened candidate of both sub-waves: Qwen3.6-27B, thinking
off, greedy + 10 samples at T 0.7, 96 tokens, on the gate question of record (`obscure`:
`NAME_REFERENT`; complex kinds: the compound-aware question). Graded by v2's strict grader
(Opus, 3 draws, unanimous "whole"). Pass = greedy correct and at least 8 of 10. **An item that
fails is dropped; no item is sampled a second time.** A request with no usable reply (an
empty or missing sample) counts as wrong, never re-drawn (plan 0112's rule).

Not carried from v2 because they never gated: the open-question probes (two placements) and the
summary probe (they tripled the GPU time and feed no bank field), and the second gate question
per item (v2 asked both and gated on one).

### 2.3 The options-only gate, in bank order: ONE run per pass, strict

v2 dropped an item only when a guesser picked its gold at least 3 times of 5 in BOTH replicate
measurements; `a refractometer` (5, then 2) is the item that rule let through. For the new
items the rule is the strict one: **a new item is dropped when the blind or the described
guesser picks its gold at least 3 times of 5 in EITHER measurement of its one gating run.**
There is no list rebuild after a failed measurement and no second run.

- Complex kinds: `scripts/association_hard_grid.py` (unchanged prompts: parse, compose the
  missing cell, scene screen 5 of 5 on the new list, the two guessers in two replicate
  measurements). A list that does not parse into the 3 x 2 grid is dropped with the reason (v2
  dropped its one such item by owner decision).
- Obscure: `scripts/association_hard_reguess.py` on a provisional bank (the 52 kept + every
  new candidate still in), new obscure items only.
- The described guesser's examples are drawn from the provisional bank (kept items included);
  kept items are never measured in these passes.

Not carried from the v2 authoring run: `refine_B.py` / `drop_leakers.py` (list rebuilds with
the guessers in the loop, in the `association` seed's option order: plan 0108 showed the result
does not transfer to the bank's order, and a rebuilt list is a second chance) and v2's rule 1
(the same guessers in that other order); every new item is measured in bank order instead.

### 2.4 Forms

`scripts/association_hard_forms.py` on every option of every surviving new item
(`forms_v3.json`), then, because v2's reviews found forms of the wrong sense and forms that also
fit a distractor: a scene-aware audit of every accepted form of every new gold (Opus: does the
form, read alone, name this scene's referent, and could it equally name another option of the
list?), read by hand, with every drop in the builder's `FORM_DROPS_V3` table and its reason.
An item is never dropped for a form; forms are.

### 2.5 Selection to 100

After the gates, in authoring order (sub-wave, then kind, then batch, then position): fill
each kind to its target (28 / 7 / 13); if a kind falls short, the surplus of other kinds fills
the total to 48, in authoring order, while no kind's share of the bank moves more than 0.10
from v2's. The rule reads no lens outcome and no floor. If fewer than 48 pass, all of them are
in and the bank is short of 100.

## 3. Files

```
evals/association/association_hard/
  items.json  grid_v1.json  grid_run1.json  forms_v1.json  reguess_v1.json     unchanged (bank v2)
  items_v3.json                                                                new: the bank of record
  v3/cand_v3.json            the subject-gated new candidates (the builder's source)
  v3/qwen_requests.jsonl     the one subject-gate run: requests,
  v3/qwen_samples.jsonl.gz   raw replies,
  v3/qwen_gate.json          and the graded record of EVERY screened candidate
  v3/grid_v3.json  v3/reguess_v3.json  v3/forms_v3.json  v3/forms_audit_v3.json  v3/options_audit_v3.json
  README.md                                                                    counts, rules, numbers
scripts/build_association_hard_bank_v3.py   new: v2's kept items + the new ones -> items_v3.json
scripts/association_hard_{grid,reguess}.py   optional arguments for a v3 pass (v2 behaviour unchanged)
src/wsbench/evals/association/association_hard/{__init__,prompts}.py   bank path, BANK_TAG
evals/baselines/{prompt_only_summary,lucky_guessing,logit_lens}.json   the family's entries
tests/test_association_hard_bank_v3.py      new
tests/golden/manifest_0101_declared.json    via scripts/manifest_0101_declare.py only
docs, CLAUDE.md, README.md, plans/README.md
```

Unlike v2, the raw gate output of every run is committed (owner's instruction), so the v3 bank
rebuilds from the repo alone and CI runs the byte-identical rebuild. It means the scenes of
candidates that failed a gate are in the repo (in `v3/`), which v2 kept out.

The header of `items_v3.json`: `version: 3`; v2's `edits` carried and `edits.v3` added (the
four drops, per-stage counts, every new candidate's fate, the strict rule); `concepts` rebuilt
over the 100-odd items (a successor that ADDS items rebuilds the pool, so kept items' judge
calls do not replay from v2's cells: every arm is judged anew on v3); `source_sha256` names
`items.json` and the `v3/` inputs.

## 4. Floors and scores (all with 95% CIs; all items, the kept 52, the new items)

- prompt-only `po-opus-v1` (`wsbench baseline kind=prompt_only_opus`, judged twice as plan 0108
  §8.2, frozen into `prompt_only_summary.json` with `source=`);
- lucky guessing blind / described / topic / uniform (5 draws, bank order; topic stays
  `NOT_A_FLOOR` and is not gated on; **the per-kind bars of plan 0108 for the blind and the
  described guesser are a gate**, as in plan 0108: this line first said "reported, not gated
  on", which was a loosening and is withdrawn, §8);
- logit lens L63 (the bundled producer on one Modal GPU, `wsbench run layers=63`,
  `wsbench freeze kind=logit_lens partial=True`);
- the four lens arms through the driver at `/root/tmp/q9-final/gw-prod`
  (`wsb_stream_run.py`, plan-file mode, `--no-judge`): `s3d-rl600` Oracle lens (RL),
  `s3d-sft251` Oracle lens (SFT), `mlnla11-rl600` NLA, `jlens-public` J-lens, on the registered
  v3 read plan, each judged twice (digests shared, judge calls fresh) with
  `layers=20,...,60`.

## 5. Tests

Pre-existing tests change only where the bank change forces it; the list is reported with the
PR. Expected: the stamp literals and the bank path in `tests/test_association_hard.py`; counts
that name 56 items. `tests/test_association_hard_bank.py` keeps testing bank v2 unchanged; the
v3 bank gets its own file (valid, sha pin, kept items byte-identical to v2's, the four drops
absent, strict guess evidence on every new item, byte-identical rebuild from the repo).

## 6. Order of work

1. This plan. 2. Authoring, lint, options (API). 3. The subject gate (one Modal run, tmux).
4. Grid pass, provisional bank, bank-order pass, forms pass and audit (API). 5. Builder,
`items_v3.json`, registration, tests. 6. Reads and judging in one tmux session with a log;
floors frozen. 7. README, docs, ledger (`manifest_0101_declare.py association_hard --plan 116
--note ... --write`). 8. Full suite in tmux with a log.

## 7. The 100-item draft that failed the described-guesser gate (2026-11-23; never pushed)

**This section records the first build, a draft: it is NOT the bank of record (§8).** The draft
had 100 items: 52 kept + 48 new (28 obscure, 7 complex_qualified, 13 complex_unnatural), sha256
`37c5aebd...`; 81 candidates had passed everything and 33 of them were the reserve (§2.5). Its
floors and scores below were measured and frozen on the branch, never pushed; it missed plan
0108's per-kind bar on the described guesser (`complex_qualified` 0.225 against 0.217).

| stage | obscure | complex_qualified | complex_unnatural | all |
|---|---|---|---|---|
| authored | 184 | 140 | 140 | 464 |
| lint-clean | 151 | 121 | 89 | 361 |
| options built, scene screen 5 of 5 | 148 | 121 | 89 | 358 |
| subject gate passed (the one run) | 103 | 49 | 33 | 185 |
| options-only gate passed (strict, one run per pass) | 46 | 21 | 21 | 88 |
| bank rules and the hand read passed | 41 | 20 | 20 | 81 |
| in the bank | 28 | 7 | 13 | 48 |

**Gate runs: one of each.** Subject gate: 1 Modal run (358 requests, 3938 replies, 384 s on 3
H200s). Grid pass: 1 run. Bank-order pass: 1 run. Forms pass: 1 run. The two audits (forms,
option lists) are one run each and gate nothing by themselves (their marks are candidates for
the builder's hand tables). No candidate was sampled, measured or listed a second time.

**Deviations from the plan above.**

- §2.1 asked for 476 items; the author returned 464 (obscure batches came back short).
- §2.3: the strict "either measurement" rule removed 6 candidates that v2's "both" rule would
  have kept (5 complex, 1 obscure); 90 were guessable in both (34 complex, 56 obscure), and
  one more complex list did not fit the grid.
- Not in the plan: a hand table `CAND_DROP` (6 candidates past the gates: `curling`, which the
  authoring brief names as an example not to reuse; `a pitcher plant`, `a bandstand`,
  `cross-stitch`, where a distractor is a kind of the gold or fits the scene; two gavel items
  whose grid's other head is `a hammer`), proposed by an option-list audit
  (`v3/options_audit_v3.json`) and decided by hand from scene and options only; and one
  candidate dropped by V5 (near-duplicate options). All before any lens result existed.
- §2.4: 38 forms on 21 new items are in `FORM_DROPS_V3`; 21 marked forms on 9 items were kept
  by hand (the family README lists both).
- §3: `scripts/association_hard_forms_audit.py` is committed (it was a scratch script in plan
  0108); `v3/options_audit_v3.json` is added; `scripts/build_association_hard_bank.py`'s
  `build_item` takes the form-drop table as an optional argument (bank v2 rebuilds
  byte-identical).
- §4: the four lens arms read only the 48 new items (the bench pinned to a new-only bank file,
  whose plan rows are byte-identical to the registered plan's rows for those items); the kept
  52 items' cells are the stored reads of plans 0108 / 0115, merged per arm with a sidecar on
  bank v3's `plan_sha`. The L63 logit lens read all 100.

**Scores of the draft** (95% bootstrap CI over items, first judging; all 100 / kept 52 / new 48):

| arm | all | kept | new | second judging |
|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.930 [0.870, 0.970] | 0.923 [0.846, 0.981] | 0.938 [0.854, 1.000] | 0.930 |
| Oracle lens (SFT) `s3d-sft251` | 0.880 [0.810, 0.940] | 0.865 [0.769, 0.962] | 0.896 [0.792, 0.958] | 0.890 |
| NLA `mlnla11-rl600` | 0.810 [0.720, 0.890] | 0.808 [0.692, 0.904] | 0.812 [0.688, 0.917] | 0.800 |
| J-lens `jlens-public` | 0.200 [0.130, 0.280] | 0.173 [0.077, 0.288] | 0.229 [0.125, 0.354] | 0.200 |
| prompt-only `po-opus-v1` (floor) | 0.950 [0.900, 0.990] | 0.962 [0.904, 1.000] | 0.938 [0.854, 1.000] | 0.960 |
| logit lens L63 (floor) | 0.050 [0.010, 0.090] | 0.038 [0.000, 0.096] | 0.062 [0.000, 0.146] | |
| lucky blind | 0.012 [0.002, 0.024] | 0.008 [0.000, 0.019] | 0.017 [0.000, 0.037] | |
| lucky described | 0.134 [0.074, 0.194] | 0.054 [0.008, 0.115] | 0.221 [0.121, 0.321] | |
| lucky topic (not a floor) | 0.408 [0.318, 0.498] | 0.381 [0.258, 0.508] | 0.438 [0.300, 0.571] | |
| lucky uniform | 0.154 [0.124, 0.184] | 0.146 [0.104, 0.188] | 0.163 [0.117, 0.213] | |

**What failed.** §4 had demoted plan 0108's per-kind options-only bars from a gate to a
report. On the frozen floor the described guesser is over the bar on `complex_qualified` (0.225
against 0.217) and picks 11 new items 3 times of 5 or more, none of which it picked in their
gating run (other solved examples). The kept items carry the same kind of residue (3 of 52 on this floor, 5 of 56 on bank
v2's). What was decided is §8.

Modal GPU time, upper bounds from wall time: subject gate 0.32 GPU-h, the four lens reads 0.29
+ 0.29 + 0.04 + 0.50, the L63 read 0.03: 1.5 GPU-h. Scratch (not durable):
`/root/tmp/assoc-hard/v3/`.

## 8. The bank of record: 99 items (the reviewing main session's decision on the draft, 2026-11-23)

Decided by the reviewing main session, NOT by the owner (Camila), who should confirm it: the
per-kind described-guesser bar stays a GATE, as in plan 0108; nothing of the draft was pushed,
so the bank is finished as bank v3 (no v4), by this procedure, applied once with the rule
fixed beforehand and no further iteration. **This is a named exception to the family's rule
"no bank change under a stamp that has results"**: the 100-item draft was floored and judged
locally under the `...+bank-v3` stamp before the 99-item bank took that stamp. It was taken
because no result of the draft left the branch. The committed `v3/floor_run1/` and
`v3/floor_run2/` files are measurements of 100-item lists and say so in their `bank` field;
a local result directory of the draft must never be reported as bank v3. The procedure:

1. Drop the 11 new items the described guesser picked 3 of 5 or more on the draft's floor run
   (`FLOOR_DROP_1`; raw run `v3/floor_run1/`). Kept items are not dropped on a floor run (they
   were admitted on bank v2's floor of record); it hit `a didgeridoo` 5, `a fjord` 4, `a pickaxe
   made of rubber` 3.
2. Backfill once from the 33 reserve candidates, in authoring order, toward the per-kind
   targets: 5 obscure, 4 complex_qualified, 2 complex_unnatural (the reserve had enough of each;
   22 stay in reserve). No authoring, no re-gating, no re-sampling. The backfilled items'
   forms were read against the same audit (8 more forms in `FORM_DROPS_V3`).
3. Floor run 2 on that 100-item bank (`v3/floor_run2/`): blind 0.010, described 0.052. One new
   item was picked 3 of 5 or more by the described guesser (`woodturning`, 5 of 5; not a
   backfilled item) and is dropped with no backfill (`FLOOR_DROP_2`). Kept items hit: `a
   didgeridoo` 5, `a pickaxe made of rubber` 5, `a platypus` 5. **99 items: 53 obscure, 16
   complex_qualified, 30 complex_unnatural (52 kept + 27 / 7 / 13 new).**
4. The floor of the final bank is one more measurement (the third), reported as it is: blind
   0.010, described 0.091 (per kind 0.109 / 0.013 / 0.100), topic 0.394, uniform 0.147. **Every
   per-kind bar is met.** On it the described guesser again picks 3 of 5 or more five new
   golds (`Handschuhe aus Honig` 5, `una iglesia en un autobús` 5, `a reed boat` 4, `a sea stack`
   4, `a sitar` 4) and five kept ones (`a fjord` 5, `um trator de chocolate` 4, `a didgeridoo`,
   `a lithophone`, `a platypus` 3), and the blind guesser picks `una clepsidra` (new) 3 of 5.
   Nothing is acted on.

The procedure is a selection on the described guesser's own measurements, and its examples
change with the item list: the final described floor is an optimistic estimate for the new
items.

Reads and judging: the 11 backfilled items were read by the four lens arms on a pinned bank
file (plan rows byte-identical to the registered plan's); the files per arm are the kept 52
(stored), the 36 new items of the draft that remain (the draft's read) and the 11 (20691
cells). The L63 logit lens read all 99. Every arm judged twice on the final bank; one judge
call of the Oracle lens (SFT) arm failed in both judgings and was asked again (failed calls
never score).

| arm | all 99 [95% CI] | kept 52 | new 47 | second judging |
|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.899 [0.838, 0.949] | 0.923 [0.846, 0.981] | 0.872 [0.766, 0.957] | 0.899 |
| Oracle lens (SFT) `s3d-sft251` | 0.889 [0.818, 0.939] | 0.885 [0.788, 0.962] | 0.894 [0.809, 0.979] | 0.889 |
| NLA `mlnla11-rl600` | 0.818 [0.727, 0.889] | 0.788 [0.673, 0.904] | 0.851 [0.745, 0.957] | 0.828 |
| J-lens `jlens-public` | 0.242 [0.162, 0.323] | 0.212 [0.115, 0.327] | 0.277 [0.149, 0.404] | 0.202 |
| prompt-only `po-opus-v1` (floor) | 0.970 [0.939, 1.000] | 1.000 [1.000, 1.000] | 0.936 [0.851, 1.000] | 0.970 |
| logit lens L63 (floor) | 0.040 [0.010, 0.081] | 0.038 [0.000, 0.096] | 0.043 [0.000, 0.106] | |
| lucky blind | 0.010 [0.000, 0.026] | 0.004 [0.000, 0.012] | 0.017 [0.000, 0.051] | |
| lucky described | 0.091 [0.042, 0.139] | 0.077 [0.027, 0.146] | 0.106 [0.038, 0.191] | |
| lucky topic (not a floor) | 0.394 [0.303, 0.485] | 0.423 [0.296, 0.554] | 0.362 [0.234, 0.489] | |
| lucky uniform | 0.147 [0.117, 0.178] | 0.146 [0.104, 0.188] | 0.149 [0.102, 0.200] | |

Runs in total: one subject-gate run, one grid pass, one bank-order pass, one forms pass, two
audits, three floor measurements (draft, after the backfill, final). Additional Modal GPU
time for this section: four reads of 11 items (0.10 + 0.10 + 0.04 + 0.10 GPU-h) and one L63
read (0.04): about 0.4 GPU-h; 1.9 GPU-h for the plan.
