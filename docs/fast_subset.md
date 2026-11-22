# Fast subset (`--fast`, `--fast-safety`)

`--fast` is the fast tier of [Tiers](tiers.md). The full bench is slow because it has so many questions. `--fast` runs **`fast-v3`**, a frozen,
smaller, higher-signal subset of the Qwen3.6-27B bench: 22 families, 1,823 questions (scored
units), 2,160 read items ([`evals/fast/`](../evals/fast/README.md): the files, the selection and
vetting rules, per-family counts).
`--fast-safety` runs **`fast-safety-v2`**: the same subset plus the two safety families
`jailbreak_recognition` and `agentic_misalignment`, for a run that wants the safety signal and
can take the extra time.

| flag | version | families | units | read items |
|---|---|---|---|---|
| `--fast` | `fast-v3` | 22 | 1,823 | 2,160 |
| `--fast-safety` | `fast-safety-v2` | 24 | 1,996 | 2,351 |

```bash
uv run wsbench plan --fast out=outputs/plan-fast                         # the fast read plan
uv run wsbench run --fast all=True readouts_root=outputs/readouts/mylens out=outputs/judged/mylens-fast
uv run wsbench report dir=outputs/judged/mylens-fast --fast
# with jailbreak_recognition and agentic_misalignment: the same commands with --fast-safety
uv run wsbench run --fast-safety all=True readouts_root=outputs/readouts/mylens out=outputs/judged/mylens-fast-safety
uv run wsbench report dir=outputs/judged/mylens-fast-safety --fast-safety
```

- **What it is.** The same families, banks, judges and prompts, on fewer items. A full readouts
  file is always judgeable with `--fast` (the judge keeps the fast items itself), so existing readouts need no re-read; a producer that wants the smaller read
  follows `wsbench plan --fast` (`docs/producing_readouts.md` § Fast subset). `--fast` is
  `fast=True` and `--fast-safety` is `fast=safety` on `plan`, `produce`, `judge`, `run` and
  `report` (given both, the last one wins).
- **How it was chosen.** On 23 arms' full results (19 lenses, logit-lens L63, 3 prompt-only
  draws), then vetted item by item. Six families that are saturated or basic and do not
  separate methods are dropped (`typo`, `association`, `multihop_st`, `multilingual_st`,
  `chain_intermediates`, `multilingual`; `jlens_concept_pr` is not in the macro and not in
  the subset). Some of the frozen subset files (`evals/fast/*.json`) and their goldens name
  families by other keys (there the six read `typo_mt`, `association`,
  `multihop`, `multilingual`, `chain_intermediates`, `multilingual_mt`): they are frozen
  bytes, and `fast.subset` translates them to the registry's keys at load. `--fast` also leaves out `jailbreak_recognition` and `agentic_misalignment`: on a
  fast run they take 23 to 38 minutes to judge after their readouts land, against 1 to 13
  minutes for the other 22 families, and they change no ordering of the measured arms (without
  them each arm's fast macro moves by at most 0.028). Within a kept family, questions every trained lens solves and questions the
  vetting marked broken, artefactual or prompt-guessable are dropped. The frozen strict ATI
  subset (`ati-subset-v2`, 350 ids in 8 families) is contained whole.
- **Reduced reads.** `introspection`: only the 125 headline units and the rows their twins
  read. Every `--fast` family is read at its full positions. **`--fast-safety` only**:
  `agentic_misalignment`, the
  18 pairs whose original misbehaves in at least one of the 8 gate rollouts, read at the last 60
  positions of each item (stamp `+fast-last_n60`), and `jailbreak_recognition`, 155 of 172
  items, read at punctuation, newline and special-token positions only (stamp
  `+fast-punct_special`); their judge prompts are unchanged, including the sentences
  describing the read scope, and the result stamp is what states the reduced read. The two take
  23 to 38 minutes to judge after their readouts land.
- **A different scale.** A fast value is the mean over the subset's units (`fast.rescore`; CI = a
  bootstrap over units, not the families' own cluster bootstraps; the family's own value on the
  fast items stays in `extras.fast_family_value`). The items every trained lens solves are gone, so fast numbers
  are **not comparable with** full-bench numbers, the frozen lucky-guessing and
  prompt-only floors (measured on the full banks; `report` blanks those columns) or ATI numbers.
  `report` and the macro refuse to mix fast and non-fast rows (`report ... --fast` /
  `fast=False` picks one kind); the macro row of a fast table is the mean over the fast families.
  A `fast-v1` results directory (24 families) reports the `--fast` macro over the 22 families
  as it is: its jailbreak / agentic rows are listed as excluded (`stale fast subset (fast-v1)`, or the row's own reason first when it is incomplete or has no value).
- **The two subsets together, and files of other subset versions.** Compatibility is per
  family (`fast.compatible`): a file or row
  of another version is used when that version holds the family with the identical entry.
  The frozen files in the repo are `fast-v1`, `fast-v2`, `fast-safety-v1`, `fast-v3` and
  `fast-safety-v2`. They hold identical entries
  for every family they share except `conjunctive_association`, whose entry is identical in
  `fast-v3` and `fast-safety-v2` only: its rows of the other three versions read
  `stale fast subset (<v>)`, while its FAST readouts files of those versions are judged as they
  are, the reads being the same. For every other family
  readouts and results move between the versions: under `--fast-safety`
  a file or row of any of the 24 families, of any of these versions, is used as
  it is; under `--fast` a row of the 22 from a 24-family version is in the macro and the two
  safety rows are excluded. A finished `--fast` run becomes a `--fast-safety` run by judging the two
  families into the same directory (`wsbench judge family=<f> --fast-safety`, not `run
  families=...`, which rewrites `summary.md` / `run.json` with those two only) and then `report
  dir=... --fast-safety`. A bare `report dir=` on a `run --fast-safety` directory rewrites
  `summary.md` to the `--fast` view, with a line saying how many rows are in the `--fast-safety`
  subset only; pass `--fast-safety` for the 24-family macro. `--fast` and `--fast-safety` numbers
  are different scales: never put them side by side as one column without the label.
- **Limits.** Qwen3.6-27B's registered banks only: `--fast` exits 2 under `WSB_BANK_ROOT` or a
  `WSB_BANK_FILE_<FAMILY>` pin, and when a registered bank is not the one the subset was frozen on. Summary mode
  and full reads only: `--fast` with `anti_text_inversion=True`, `reads=lite`,
  `layers=each`, `opts=aggregate=native` or `opts=judge=...` is a usage error. `items=` under `--fast` judges a part of the fast items (ids outside the subset exit 2) and always gives an incomplete result: it fills the cache, e.g. to judge a slow family in parallel groups before one full pass. Give a fast run
  its own `out=` (it would overwrite a full run's `results.json`); judge and digest calls are
  keyed as in a full run, so a fast run given a full run's `cells.jsonl` (a copy of the family
  out dir, or `summ_store=`) re-uses its cached calls.

Fidelity of the fast subset against the full bench:

| arm | full bench (30 families) | `--fast` (22 families) |
|---|---|---|
| O-lens s3d (native) | 0.600 | 0.538 |
| rl-affw (whitened affine) | 0.559 | 0.497 |
| Q9 xaff (9B reader) | 0.543 | 0.484 |
| NLA | 0.542 | 0.449 |
| prompt-only (Opus 5.5, no activations; mean of 3 draws) | 0.600 | 0.480 |
| J-lens (public) | 0.193 | 0.119 |
| logit lens (L63) | 0.096 | 0.067 |

11-layer union. The fast numbers are a different scale (fewer
easy questions), so they are never compared with full-bench numbers; the order of the arms is what
carries over. The same arms on `--fast-safety` (24 families): 0.535, 0.491, 0.478, 0.442, 0.475, 0.116, 0.063. Measured for the
24 families: across 19 lenses the item selection (with full-position reads of
the two reduced families) correlates 0.988 with the full macro (rank 0.995) and keeps the sign of
all 153 significant pairwise differences.
`--fast-safety` only, the two families `--fast` leaves out: jailbreak_recognition at the reduced
positions keeps arm order but loses about 0.04 of recall minus control FPR on average (8 arms);
agentic_misalignment at the last 60 positions finds 10 of the 13 pair hits the full read finds
plus new ones, at a higher level (mean pair rate about 0.19 vs 0.08) and with run-to-run noise
(0.07) about as large as its spread across arms, so its single-run row should not be used to rank
arms.
