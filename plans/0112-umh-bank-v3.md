# Plan 0112: user_modeling_hard bank v4 (the harder wave, strictly gated on one draw), `umh-v3`, frozen floors

Camila, 2026-11-23, on the harder wave of 86 new items (`/root/tmp/um-hard/harder/REPORT.md`):

1. adopt the harder items, "but they must be strictly gated (just gate the rest)";
2. drop the three near-stated items: `umh-two-w1035-A` (its `divorcing` part) and the wave's two
   `engaged` items, `umh-two-w5320-B` and `umh-two-w5120-B`;
3. then "add to core". **Not in this plan**: core membership and the fast-subset re-cut are one
   separate step (`tiers.py`, `evals/fast/` and `manifest_0101_declare.TIER_MOVES` are not
   touched here).

4. (2026-11-23, on the plan's first build and its independent review) **drop the 19 items that
   were admitted only on a second gating draw**: "strictly gated" means one draw per item for
   every item.

The file keeps its name. **Bank v3 was this plan's first build** (175 items: the 156 that pass
the gate on one draw plus those 19), stamped `umh-v3+bank-v3`; it was judged and had floors
frozen on the branch and was never merged. Decision 4 changes the bank, and the family's rule
is that a bank never changes under a stamp that has results, frozen or not (review r4 F1), so
the registered bank is **v4**, `umh-v3+bank-v4`. This file describes bank v4; where a number
of the first build is given it is marked.

This plan also closes review r4's three should-fix findings on plan 0106 (F1 stamp, F2 the
one-sided distractor swaps, F3 the echo re-ask text) and freezes the family's floors, so the
family leaves `PENDING_FLOOR`.

## What changes

- **The strict gate, a rule of the builder, on one draw per item.** The label gate that bank
  v1's items passed (`fgrade.py` of the authoring run): under the answer stem `My answer is:`,
  the greedy answer is the gold and at least 8 of 10 samples at T=0.7 are; *an empty sample
  counts as a sample that is not the gold* (42 of bank v2's 159 parts passed with one or two;
  the run rejected 48 candidate parts that failed only by them); the no-stem question decides
  only when the stem's GREEDY answer is empty. The wave had also let the no-stem question
  decide for a part whose stem samples failed with an empty one (39 of its 86 items).
  Re-drawing empty samples is not within the original rule, and it is not applied.
  - `scripts/build_user_modeling_hard_bank.py` takes the wave as a second source (`--wave
    wave5_candidate.json`, the same schema, gate evidence of the original rule on the wave's
    own draw) and drops by rule (`gate_fails`, the header's `edits.not_strictly_gated`) every
    candidate with a part under the bar: 38 items (the thirty-ninth is an `engaged` item,
    dropped by name). Every table of the builder applies to both sources.
  - **`gate_fails` fails closed** (review of the first build, S5): a part without a gate
    record, a record without `greedy_verdict` / `n_correct` / `n_samples` / `greedy` /
    `stem_dropped`, with another sample count than 10, or that claims to be a second draw
    (`draw` 2, `first_draw`) is a SystemExit. The first build read a missing greedy verdict as
    `gold`.
  - **The second draw, and why its 19 items are out.** "Just gate the rest": the stem question
    of the 44 failing parts of the 39 items was sampled again (Modal, `wsb-qwen-sample`,
    greedy + 40 samples, a fresh seed) and the SAME rule applied to that draw as written (the
    first 10 samples, an empty one wrong, nothing re-drawn): 19 items pass on every part, 20
    fail again. The first build admitted the 19 with the second draw as their gate record.
    The owner dropped them: they had two chances where every other item had one. Sized by the
    independent review from the 30 held-out samples of the same re-draw: the mean single-draw
    pass probability of the 19 is 0.50 and six are under 0.25; a typical draw admits about 15
    of the 39; an item with single-draw pass probability q is admitted with probability
    2q - q^2 under two chances. The 19 stay on record in `edits.second_draw_not_admitted`
    (both draws); the second draw is a diagnostic field of the candidate file (`second_draw`)
    and gates nothing. Diagnostic only: with empties re-drawn 36 of the 39 would pass.
  - **The wave's candidate file is built from the repo**: `scripts/umh_wave_candidate.py
    --harder <the wave's run dir> --redraw-table <redraw_table.json> --out
    wave5_candidate.json` (the first build's `mk_wave_src.py` lived in the scratch dir and
    substituted the second draw; this one never does). The run directory and both candidate
    files stay outside the repo, sha-pinned in the bank header.
  - **Six parts are gated by the no-stem leg** (review S2), by the rule as written (the
    stem's greedy answer was empty; 4 to 9 of the 10 stem samples were empty too; the no-stem
    leg gave 10 of 10, and 8 of 10 for `numb`): `umh-two-w5161-B` p1 (proud),
    `umh-two-w5344-B` p1 (Czech Republic), `umh-two-w5513-B` p1 (Orthodox Christian),
    `umh-three-w5392-B` p1 (Brazil), `umh-state-w5006-B` p1 (proud), `umh-state-w5108-B` p0
    (numb). Bank v2 had none. The rule treats one symptom two ways (an empty stem greedy goes
    to the no-stem leg whatever the stem samples were; a gold stem greedy with three empty
    samples is dropped). Not dropped: listed in the header (`edits.no_stem_leg`), in the
    family README's gate paragraph and pinned by a test. (The first build had a seventh,
    `umh-three-w5313-B` p1, which left with its item among the 19.)
- **Bank v4** (`items.json`, header `version: 4`): bank v2's 111 minus `umh-two-w1035-A`, plus
  45 wave-5 items (the 46 gated on the wave's draw minus one duplicate; the two `engaged`
  items and the 38 not strictly gated are out): **155 items, 229 parts** (two 44, three 8,
  state 53 with 14 mixed, expertise 16, stance 13, fine 21; request A 99, B 56; uniform
  chance 0.1011). After dropping the 19 the bank was 156 items (three 14 -> 8, two 53 -> 44,
  state 57 -> 54, fine 22 -> 21, as expected); the duplicate makes it 155 (state 53).
  - **One vignette twice** (review N4): `umh-state-w5053-B` and `umh-state-w5113-B` (the old
    car goes for scrap, a tape still in the deck, gold `nostalgic`). `umh-state-w5113-B` is
    dropped (`DROP`): the weaker label-gate record of the two (9 of 10 against 10 of 10);
    decided on the gate records. The choice costs the prompt-only floor one item: on the first
    build's judged rows the kept `umh-state-w5053-B` fails prompt-only and the SFT first ask,
    and the dropped copy passes both (RL and NLA pass both copies). With the other copy kept,
    prompt-only would be 110/155 (0.710); no comparison changes (review r2, S1).
  - Built only through the builder's tables; no user message edited; the 110 kept items are
    byte-identical to bank v2's except `umh-state-w1039-A` (one swap), and all 155 items are
    byte-identical to the first build's. New header keys: `provenance`,
    `request_variant_counts` (computed by `bank.counts`, checked by V10),
    `edits.not_strictly_gated`, `edits.second_draw_not_admitted`, `edits.no_stem_leg`,
    `plan_lineage`. `GOLD_RELABEL` is empty (its one entry left with `umh-two-w1035-A`;
    `optometrist` stays a pool value, `option_pools.json` is unchanged); its branch is tested
    on a fixture (review N5).
  - **Header counts are computed** (review S1): the first build's header said `three` had 8
    items when it had 14, inside the sha-pinned file. `known_issues` is now a function of the
    items and the build log (`known_issues(items, log)`); every count about the bank in it is
    counted, and a test ties them to the header.
  - **`plan_lineage`**: one drop-only step from the first build's read plan (`e38048d4`,
    `FIRST_BUILD_PLAN_SHA`) to bank v4's (`2f6f60fa`), 20 ids dropped, computed and checked
    by the builder (`reads.lineage_step`). It is what lets the L63 floor's readouts, made on
    the first build's plan, be judged without a re-read (`reads` guard iii).
- **Review r4 F2, one rule for every remaining also-true flag of a state list.** A fresh screen
  (review r3's audit prompt) of the first build's 271 parts flagged 43 distractors of its 96
  state parts (83 state parts are in bank v4). Rule: a distractor is replaced iff an accurate
  observer of how the user feels at the time of writing would be RIGHT to say it, through a
  span of its own, through the gold's own event being its defining event too, or (mixed
  lists) through the other situation; it stays when the message makes it only possible.
  Outcome: 1 swap (`disappointed` -> `relieved` in `umh-state-w1039-A` p0, replacement drawn
  by review r3's procedure, options-only guess 0 of 5), 42 kept.
  - **What the record supports** (review S4; an earlier version of this plan said "applied
    from the chat alone, before bank v3 was judged, with no arm outcome opened"). The screen
    (03:24 and 03:29) and the swap pick (03:25) precede the judging (03:29:28), so the one
    swap was fixed before judging. The 42 "kept" are the absence of a swap at build time. The
    written reasons (`bank_changes_v3.md`, 03:42) came 13 minutes after judging had started;
    35 of the 43 are one template sentence; the write-up moved no verdict. The pass was not
    blind for `umh-state-w1039-A` and `umh-state-w4019-A`, whose arm outcomes were known from
    review r3. No arm's verdict on the swapped part differs between the r3 run and the run
    after the swap, so the swap moves no number.
  - **Two bars in mixed lists.** Review r2's standing rule for a mixed-state list is "the
    other situation supports it", a lower bar than F2's "right to say it". `anxious` was
    removed from `umh-state-w4108-A` p1 for the gaffe span ("replayed it about forty times")
    and is kept in p0's list of the same message on that span; the same holds for
    `umh-state-w4026-A`. Recorded in `known_issues`; no stored verdict picks either.
  - By the same rule review r3's post-hoc swap of `burned out` in `umh-state-w1039-A` would
    have been kept; it stands and is disclosed.
- **Hand read of every new item** (the first build's 65; the 45 of bank v4 among them) for a
  stated or near-stated gold, an also-true distractor, a loose form, a part resting on one
  give-away noun: none dropped; 5 loose forms removed (`FORM_DROPS`).
- **Review r4 F3, `umh-v3`.** The echo re-ask has a second reason text,
  `UMH_RETRY_REASON_ECHO_QUOTE`, used when a statement that holds the copied quote is not in
  the draw's refused set (it states the gold in a word the chat lacks): it asks for those words
  of the same bullet instead of "Do not quote from that bullet again"
  (`judge.retry_reason`; the row records `n_echo_statements`). The condition is "a holding
  statement that is not itself an echo": it may state the gold in a word of its own or be a
  long own-worded bullet that only contains the copied span; the text is conditional and
  right in both cases (review N1: the docstring said only the first). *Everything else of the judge is
  retained: the gates, the refused set, the re-ask caps (two per draw, one after a refused
  quote), the first-ask headline, the quote check and every other prompt are unchanged.*
- **Stamp (review r4 F1).** `CALL_VERSION = "umh-v3"` (a prompt changed), `BANK_STAMP =
  "+bank-v4"`, registered instrument `umh-v3+bank-v4` (`umh-v3+bank-v3` is the first build's
  and stays its alone). The rule in CLAUDE.md now reads "a gate, a
  prompt or the bank never changes under a stamp that has results, frozen or not". The option
  seed prefix stays `umh-v1` (`bank.STAMP`).
- **`prompts.py`**: the stale comment ("130 of the 149 chats") cites the header's
  `request_variant_counts` instead of a typed number.
- **Floors, frozen on bank v4** (`tests/test_po_floors_r3.py::PENDING_FLOOR` is empty). No
  GPU and, the lucky `described` guesser aside, no new judge call: every digest and judge call
  of the 155 items is the first build's, replayed from its cache (call keys hold `umh-v3`, not the bank version), so each
  item scores exactly as it did among the 175.
  - lucky guessing (`lucky_guessing.json`, 4 variants, Opus 5.5, 5 draws): blind 0.114,
    described 0.093, question 0.077, seeded uniform 0.090; analytic uniform 0.101. Per kind against plan 0106's bar (the kind's
    chance + 0.05): `fine` misses on the blind guesser (0.276 against 0.193; 0.264 on the
    first build, 0.283 on bank v2); every other kind passes on all four. **Owner decision
    open** (plan 0106 §6.2). The `described` guesser's prompt shows solved examples drawn
    from the whole bank, so its 770 calls were drawn new on bank v4 (measured after the
    other floors, once the box's judge login was renewed). First build: 0.096.
  - prompt-only summary (`prompt_only_summary.json`, `po-opus-v1`, reply-free-v2, 0 of 155
    refused by Opus, so no Sonnet 5.5 fallback answer): **0.703** [0.63, 0.77] (109 of 155).
    The Opus answers are the earlier runs' (one draw per item, kept by `prompt_sha`: 110 of
    the first validation, 45 of the wave's final draw). As for plan 0109, the stock freeze
    rewrites `_source` without its `fallback` record, so main's file was kept and the one
    entry added.
  - logit lens L63 (`logit_lens.json`, `freeze kind=logit_lens partial=True`): the readouts
    are the first build's one run (all 175 items, the bundled producer, one Modal GPU, sidecar
    `plan_sha` `e38048d4`), judged with `layers=63` through the bank's `plan_lineage` (the
    run's `config.plan_lineage` records the step): **0.019** (3 of 155), `ci95` [0.00, 0.04].
    30 entries; the raw mean moves from 0.126 to 0.122.
  - The bank's sha256 is pinned in `tests/test_user_modeling_hard_bank.py` (plan 0106 §2.3:
    after validation).
- **Manifest ledger**: re-declared with `scripts/manifest_0101_declare.py user_modeling_hard
  --plan 0112 --note ... --write`.
- **Docs**: family README (bank v4, the strict gate, results, the new prompt verbatim),
  README.md, NOTICE.md, docs/evals.md, docs/judges.md, docs/tiers.md, docs/baselines.md,
  evals/baselines/README.md, AGENTS.md, CLAUDE.md, plan 0106 (an "After plan 0112" paragraph).

## Validation (2026-11-23)

Scratch, not durable, outside the repo: `/root/tmp/um-hard/validate/v3/REPORT.md` (the first
build, 175 items) and `/root/tmp/um-hard/validate/v3b/` (bank v4: `analysis_tables.md`,
`analysis.json`, the judged runs, the floors, the build and the scripts). The independent
review of the first build: `/root/tmp/um-hard/review-0112.md`.

Bank v4, `umh-v3+bank-v4`, from existing readouts (no lens re-read) and the first build's
judge cache (0 new calls; every row complete). Item pass rate with Wilson 95% intervals,
and exact McNemar against the prompt-only floor (arm only / floor only):

| arm | headline | first-ask | vs prompt-only, headline | vs prompt-only, first-ask |
|---|---|---|---|---|
| Oracle lens (RL) `s3d-rl600` | 0.910 [0.85, 0.95] (141/155) | 0.845 [0.78, 0.89] (131/155) | 34 / 2, p = 1.9e-08 | 32 / 9, p = 0.0004 |
| Oracle lens (SFT) `s3d-sft251` | 0.890 [0.83, 0.93] (138/155) | 0.774 [0.70, 0.83] (120/155) | 35 / 6, p = 4.9e-06 | 34 / 22, p = 0.14 |
| NLA `mlnla11-rl600` | 0.684 [0.61, 0.75] (106/155) | 0.574 [0.50, 0.65] (89/155) | 20 / 23, p = 0.76 | 17 / 36, p = 0.013 |
| J-lens `jlens-public` | 0.103 [0.06, 0.16] (16/155) | 0.097 [0.06, 0.15] (15/155) | 3 / 96 | 3 / 96 |
| rl-affw-x4 (the 110 kept items; no read of the new ones) | 0.900 [0.83, 0.94] (99/110) | 0.845 [0.77, 0.90] (93/110) | 18 / 2, p = 0.0004 | 16 / 5, p = 0.027 |
| prompt-only reader, Opus 5.5 (frozen floor) | 0.703 [0.63, 0.77] (109/155) | 0.697 [0.62, 0.76] (108/155) | | |
| logit lens L63 (frozen floor) | 0.019 [0.01, 0.06] (3/155) | 0.019 (3/155) | 0 / 106 | 0 / 105 |

What changed against the first build's reading: the Oracle lens (SFT) is no longer clear of
the floor on the first-ask rule (p = 0.14; 44 / 23, p = 0.014 on the 175), because the 19
dropped items were the hardest for the text floor (it passed 6 of them). On the 156 items
left after dropping the 19 (before the duplicate went) the arms score 0.910, 0.891, 0.686 and
the floor 0.705; `umh-state-w5113-B` passed on all four, hence 141 / 138 / 106 / 109 of 155.

The first build (175 items, `umh-v3+bank-v3`), for the record: Oracle lens (RL) 0.914 / 0.834,
Oracle lens (SFT) 0.891 / 0.777, NLA 0.674 / 0.560, J-lens 0.097 / 0.091, prompt-only 0.663 /
0.657, logit lens L63 0.017.

## Tests

`tests/test_user_modeling_hard_bank.py` (the bank's counts and sources; the strict gate on
the committed bank on one draw; the gate fails closed; a second draw admits nothing; the
no-stem parts pinned; computed header counts; the plan-lineage step; `GOLD_RELABEL` on a
fixture; the wave candidate script's gate record; the wave source required; the bank's
sha256), `tests/test_user_modeling_hard.py` (stamp, counts, the F3 re-ask, a FACT-rule fixture
for the dropped `umh-two-w1035-A`), `tests/test_user_modeling_hard_tables.py`,
`tests/test_po_floors_r3.py` (`PENDING_FLOOR` empty), `tests/test_logit_lens_floor.py` (30
entries).

## Files

```
scripts/build_user_modeling_hard_bank.py                     --wave, gate_fails, known_issues, plan_lineage
scripts/umh_wave_candidate.py                                the wave's candidate file, one draw per part
src/wsbench/readplan.py                                      user_modeling_hard_specs (the branch, factored)
src/wsbench/evals/association/user_modeling_hard/{prompts,judge,bank}.py
evals/association/user_modeling_hard/{items.json,README.md}
evals/baselines/{lucky_guessing,prompt_only_summary,logit_lens}.json, README.md
tests/golden/manifest_0101_declared.json                     (written by the declare script)
tests/test_user_modeling_hard{,_bank,_tables}.py, test_po_floors_r3.py, test_logit_lens_floor.py
scripts/summary_mode_compare.py                              (its stamp table)
README.md NOTICE.md AGENTS.md CLAUDE.md docs/{evals,judges,tiers,baselines}.md
plans/0106-user-modeling-hard.md plans/0112-umh-bank-v3.md plans/README.md
```

## Open, for the owner

1. `fine` misses the per-kind lucky-guessing bar on the blind guesser (0.276 against 0.193).
2. Core membership and the fast re-cut (decision 3), in their own step.
3. `expertise` still separates nothing (0.31 to 0.56 for every prose arm and the floor).
4. The six parts on the no-stem leg are in by the rule as written; dropping them (six items)
   would be a bank v5.
