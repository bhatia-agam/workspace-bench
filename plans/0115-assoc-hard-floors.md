# Plan 0115: association_hard, the two deferred measurements (Oracle lens (SFT), logit lens L63)

Plan 0108 registered `association_hard` (bank v2, 56 items, `assoc-hard-v1+gate-h2+bank-v2`)
and deferred, for want of a GPU, the Oracle lens (SFT) read and the frozen final-layer
logit-lens floor (§6.3, §11). This plan measures both. **No bank, stamp, prompt or gate
change**; tiers, the fast subset, the ATI file and the adapted sets are untouched.

## (A) Oracle lens (SFT), `s3d-sft251`

Read on 2026-11-23: the 56 items on the registered read plan (`plan_sha` `2560571b`; layers
20, 24, ..., 60, the 19 summarize-suffix and chat-tail sites; 11704 cells, the same cell keys
as the stored `s3d-rl600` read, no empty sample), by the driver that made the stored Oracle
lens (RL) shards (plan-file mode, three Modal GPUs), then judged twice as plan 0108 §8.2
(`wsbench judge layers=20,...,60`, digests shared, judge calls fresh). The run configs differ
from the stored Oracle lens (RL) run's in the reader and the digest store path only.

| arm | pass rate [95% CI] | second judging | obscure | complex_qualified | complex_unnatural | items differing |
|---|---|---|---|---|---|---|
| Oracle lens (SFT) `s3d-sft251` | 0.893 [0.804, 0.964] (50 / 56) | 0.893 (50 / 56) | 27 / 30 | 9 / 9 | 14 / 17 | 2 |

First-ask rate = headline, 0 undecided, 0 quote re-asks. The two items that differ: `a
pamonha` (fails the first judging) and `a solar halo` (fails the second). Fails in both:
korfball, a green flash, ein Archiv in einem U-Boot (majority pick another cell of the grid),
um trator de chocolate and un coche de galleta (the bare head).

Paired on the first judgings, exact McNemar (arm only / other only):

| against | other's rate | SFT only / other only | p |
|---|---|---|---|
| prompt-only `po-opus-v1` (the frozen floor) | 0.982 | 1 / 6 | 0.125 |
| Oracle lens (RL) `s3d-rl600` | 0.929 | 1 / 3 | 0.625 |
| NLA `mlnla11-rl600` | 0.821 | 6 / 2 | 0.289 |
| J-lens `jlens-public` | 0.161 | 41 / 0 | < 1e-11 |

The only item the lens passes and the prompt-only reader fails is `a library in a helicopter`;
the one it passes and the Oracle lens (RL) fails is `a red tide`. On 56 items the Oracle lens
(SFT) is not separated from the Oracle lens (RL) or from the floor; the order of the point
estimates is floor > RL > SFT > NLA.

Not done: a hand read of these verdicts (plan 0108's hand read covers its own arms).

## (B) Logit lens L63 floor

All 56 items read at layer 63 by the bundled producer (`wsbench.produce` `Producer`, method
`logit_lens`, `layers=[63]`, one Modal GPU, the recipe of plans 0109 / 0110 / 0112; 1064 cells
= 56 x 19 sites, sidecar on the bank's own `plan_sha`), judged with `wsbench run
families=association_hard layers=63` (0 missing, 0 unjudged, complete; every digest and judge
call new) and frozen with `wsbench freeze kind=logit_lens partial=True`.

**0.036** [0.000, 0.089], 2 of 56: obscure 1 / 30 (`a mirage`, a listed form), complex_qualified
0 / 9, complex_unnatural 1 / 17 (`a library in a helicopter`, on the token pair `library |
helicopter` through the quote-only re-judge). Majority pick the bare head on 10 of the 26
compounds. `evals/baselines/logit_lens.json` differs from main by the one new entry and
`_source` (main's record moves under `kept_from` with chain_intermediates, the earlier
`kept_from` records unchanged). 31 entries; the raw mean moves from 0.122 to 0.119.

## Files

```
evals/baselines/logit_lens.json                       the association_hard entry, _source
evals/association/association_hard/README.md          two table rows, two paragraphs, history
evals/baselines/README.md, docs/baselines.md          the family's floors paragraph, the raw mean
CLAUDE.md                                             the raw mean, the family's floors sentence
tests/test_logit_lens_floor.py                        the committed entry count, 30 -> 31
plans/0108-association-hard.md                        an "After plan 0115" paragraph
plans/0115-assoc-hard-floors.md, plans/README.md
```

`tests/test_po_floors_r3.py::PENDING_FLOOR` was already empty (the prompt-only floor was
frozen by plan 0108) and has no logit-lens counterpart; the manifest ledger entry does not
move: `tests/test_rename_0101.py` passes on the tree with the new entry, nothing was re-declared.

## Cost and scratch

Modal GPU time, upper bounds from wall time: the SFT read 3 containers for at most 6.6 min
(shards 5.1 + 4.9 + 5.3 min) = 0.33 GPU-h; the L63 read one GPU for under 2 min = 0.03 GPU-h.
Scratch, not durable, outside the repo: `/root/tmp/assoc-hard/floors0115/` (`sft/run/readouts`,
`sft/runs/j{1,2}-s3d-sft251`, `ll63/{out,judged,run_config.json,logit_lens.before.json}`,
`analysis.json`, logs). The SFT shards are on the Modal volume `wsbench-bp64-readouts` under
`s3d-sft251/ah-0115-sft-20261123/`.

## Still open (plan 0108 §11, unchanged)

Core and the fast cut (owner decision), an ATI panel, the road to 100 items, the owner's own
read of the 30 verdicts set aside.
