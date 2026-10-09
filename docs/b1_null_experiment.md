# B1 null experiment + bank judge v2: s3d-rl600 readout (plan 0012 §1.4, §2.3)

2026-10-09. One arm only: `s3d-rl600`, the O-lens headline arm. Camila asked to compare the s3d
numbers before deciding anything; the other three planned arms (`nla-rl-L42`, `jlens`, `logit`)
were not run. Judge `google/gemini-3.8-flash` (pinned), same cells for every column.

- **v1** = `bank-2026-09-16` (naming only), run from commit 8677010.
- **v2** = `bank-2026-10-09` (meaning; plan 0012 Appendix A), run from commit a50ac5d.
- **Random null:** each item graded against 3 other items' targets (seeded bank-level
  derangements).
- **Near-miss foil:** each item graded against up to 3 same-type wrong answers
  (`evals/<f>/null_foils.json`).
- Rates are percent of items, any layer, with 95% bootstrap CIs.
- Every run was complete: 0 unjudged cells and 0 failed or undecided null calls.

## Bank families

| family | judge | pass | random null | near-miss foil | lift (null) | lift (foil) | foil credits surface-free |
|---|---|---|---|---|---|---|---|
| association | v1 | 86.0 [79, 93] | 4.0 [2, 6] | 17.3 [13, 22] | 82.0 | 68.7 | 32.1 (n=112) |
| association | v2 | 90.0 [84, 95] | 5.0 [3, 8] | 22.3 [17, 28] | 85.0 | 67.7 | 56.7 (n=171) |
| basic_readout | v1 | 99.0 [96, 100] | 6.0 [3, 9] | 61.3 [54, 68] | 93.0 | 37.7 | 3.0 (n=843) |
| basic_readout | v2 | 98.0 [95, 100] | 6.0 [4, 9] | 61.0 [54, 68] | 92.0 | 37.0 | 4.8 (n=818) |
| multihop | v1 | 99.0 [97, 100] | 6.0 [3, 9] | 35.7 [29, 43] | 93.0 | 63.3 | 8.0 (n=250) |
| multihop | v2 | 99.0 [97, 100] | 6.3 [4, 9] | 36.8 [30, 44] | 92.7 | 62.2 | 14.1 (n=256) |
| multilingual | v1 | 100.0 [100, 100] | 13.0 [9, 17] | 63.6 [56, 71] | 87.0 | 36.4 | 70.3 (n=817) |
| multilingual | v2 | 100.0 [100, 100] | 14.0 [10, 18] | 65.1 [58, 73] | 86.0 | 34.9 | 72.4 (n=848) |
| poetry | v1 | 54.0 [44, 64] | 24.0 [19, 29] | 24.0 [19, 29] | 30.0 | 30.0 | 18.8 (n=138) |
| poetry | v2 | 53.0 [43, 63] | 24.0 [19, 29] | 23.7 [19, 29] | 29.0 | 29.3 | 18.2 (n=137) |
| typo | v1 | 100.0 [100, 100] | 11.3 [8, 15] | 16.3 [12, 20] | 88.7 | 83.7 | 22.8 (n=162) |
| typo | v2 | 100.0 [100, 100] | 11.3 [8, 15] | 17.3 [13, 22] | 88.7 | 82.7 | 31.3 (n=179) |

Prompt-only floors, re-judged under v2 (`evals/baselines/prompt_only.json`):

| family | prompt-only floor |
|---|---|
| association | 33 |
| basic_readout | 71 |
| multihop | 91 |
| multilingual | 77 |
| poetry | 59 |
| typo | 100 |

## Regex families (random null only, $0)

| family | pass | random null |
|---|---|---|
| basic_readout_mt | 71.0 | 0.0 |
| multihop_mt | 32.0 | 0.0 |
| multilingual_mt | 62.0 | 0.0 |
| multilingual_multihop | 39.8 | 0.0 |
| multilingual_typo | 78.0 | 0.0 |
| typo_mt | 83.0 | 0.0 |

A partner's exact multi-token form essentially never appears by chance, so on this scorer a raw
pass rate is already a lift.

## Validation

- **Sanity set:** 23 of 23 held-out cases pass 3/3 on fresh caches. One case,
  "swapped his pills" → "poison the rival", was reworded before the passing run because it was
  ambiguous: swapping pills is not necessarily poisoning, and no rival is named. On the
  original wording v2 credited it 1/3.
- **Flips v1 → v2:** 8 items flip, and a blind fresh-context audit labels **7 of 8 correct**:
  - Correctly gained: winter (from "It was January"; borderline), boxing (a depicted bout),
    Troy (特洛伊人), beekeeping.
  - Correctly lost: autumn (it appears only inside a list of the four seasons), and small and
    start (v1 had credited the synonyms "little" and "begins").
  - **Error:** poetry `great` credited from "greatness", a derived word that the poetry rule
    excludes.
  - The plan's merge bar is ≥ 90% correct. 7/8 is 87.5%, on n=8.
- **Leniency audit:** 60 foil credits per version, labelled blind to version. Lenient share is
  **v1 13.3%, v2 15.0%** (8/60 vs 9/60), evenly spread across families. Nearly all the errors
  rest on a synonym or translation of the real target, or on a word that appears only inside a
  list or boilerplate. The other foil credits are legitimate: the readout really names the
  sibling ("2 + 2 = 5", "huit", "nièce").

## Decision gate (plan 0012 §1.4), on one arm

1. **Arm-rank flips:** not evaluable with one arm.
2. **Judge leniency:** no. v2's `lenient_share` (0.15) is below 0.20 and only +0.02 over v1.
3. → Suggested: keep the raw headline. The nulls stay as diagnostic extras.

**Exception worth Camila's attention: poetry.** A random other item's rhyme word passes 24% of
the time, against 53–54% for the real target, so the lift is only about 30. The prompt-only
floor (59) sits above the lens (53). Common rhyme words ("day", "fly", "night") appear in many
readouts. This is the one bank family where the raw rate overstates what the lens shows. In
basic_readout and multilingual, the high foil rates (61–65%) are mostly real alternatives the
readout names. They do not inflate pass, because the target itself also passes.

## Not done (would be next if B1 is pursued)

- The other three arms, which are needed for the rank-flip test.
- A fix for the `greatness` error: add "a derived word (great → greatness) is not credit" to
  `FAMILY_RULE_POETRY`, then rerun poetry v2.
- Cost so far: v1 run $20.2, v2 run ~$20, sanity and prompt-only < $3, foil drafting (Opus 5.5)
  a few dollars.

Artifacts: `/workspace/root/ext/wsb-runs/{v1,v2}/s3d-rl600/`, `/workspace/root/ext/wsb-runs/b1/`
(tables, flips, foil-credit samples, audit JSONs).
