# dory-4b: notes on the looped subject

Subject: `nvidia/NVIDIA-Nemotron-Labs-Dory1.0-4B-BF16` @ `ee517dd388a9b348890ae1e00dacc5eb4d0c750d`.
Dory has 8 input blocks, then the same 20 blocks run k times ("loops"), then 8 output blocks. It
shares all weights across loops and has no loop counter.

## Subject definition: the 2-loop model
The set is built on the k = 2 model. This is NVIDIA's default (`config.json`
`n_recurrent_loops: 2`, per-loop KV), and it is the loop count the mOre-lenses Oracle lenses run
their reader at (`agu18dec/mOre-lenses` `dory-4b/*/olens.json` `reader_loops: 2`). Every step uses
the 2-loop model: gating, refills, the model-specific rebuilds, the floors (`stock-subject-v1`)
and the read renders.

- **Serving:** vLLM 0.33.0's native `DoryForCausalLM` on the `adapt-dory-4b` app (recipe `dory`).
- **Reads, introspection and lenses:** transformers PR 50099 pinned at
  `shan18/transformers@fcc6924d`, with the unrolled view applied.
- **Render:** the hub chat template with `enable_thinking=False`, which pre-fills an empty
  `<think></think>`.
- **Native languages:** `['en']`, by the plan-0089 lab rule (NVIDIA is an American lab). This is a
  decision, not a measurement.

## Layers: the unrolled view
The read layers are indices of the mOre-lenses unrolled view (`dory-4b/code/looped.py` @
`65c77744`, sha256 `41efcd5d…`).

| index | 0-7 | 8-27 | 28-35 | 36-55 | 56-63 | 64-83 | 84-103 | 104-111 |
|---|---|---|---|---|---|---|---|---|
| section | input | pass 1 | output after 1 loop | pass 2 | output after 2 loops | pass 3 | pass 4 | output after 4 loops |

Layer L is the output of entry L, which is `hidden_states[L + 1]` of the view.

- **Entries the subject computes.** The 2-loop forward runs only entries 0-27, 36-55 and 56-63
  (`looped.py` `on_path`).
- **Exit 1 is not one of them.** The output section after 1 loop (28-35) runs only in capture
  mode, as a side branch off the loop stream, and the 2-loop output never passes through it.
- **Passes 3-4 and exit 4 (≥ 64)** are not computed by the subject at all.
- **Capture equals the plain forward.** Capture-mode states of path entries are bitwise equal to
  the plain 2-loop forward's (max abs diff 0.0, lens producer parity check and J-lens fit check).

## The read band and the depth remap
`report.json`:
- `n_layers = 64`, the unrolled indices 0..63 of the 2-loop view.
- `read_band = (15, 19, 23, 27, 39, 43, 47, 51, 55, 59, 63)`.

Why these sites:
- The Oracle lenses read entries 11, 15, …, 107 (every 4th). Of those, the 2-loop model computes
  11, 15, 19, 23, 27 | 39, 43, 47, 51, 55 | 59, 63 (31 and 35 are exit 1).
- Site 11 is dropped. It sits at 11/56 = 20% of the 2-loop path's depth, shallower than the bench
  grid's first layer (27B layer 20/64 = 31%).
- That leaves exactly 11 sites, so `subjects.remap_layer`'s table rule maps the 27B grid one to
  one: `GRID_27B[i]` (20, 24, …, 60) → `band[i]`. Every site is read once and no grid layer
  folds onto another. A 12-site band would nearest-snap the grid onto only 8 sites.
- Grid depths .31 → .94 pair with path depths .27 → .98, monotone.
- Off-grid layers snap into the band and can never land on 28-35 or ≥ 64
  (`tests/test_adapt_dory.py`). These are lite rows such as `[56, 60]` → `[59, 63]`, and buggy_code
  read cells.
- `min_grid_positions` is a property of the render length (the template), not of depth. It is set
  per family by the usual adapt route and has nothing to do with looping.

Every lens arm reads only these sites. The J-lens reads 10 of them: its target is entry 62
(penultimate on the 2-loop path), so it has no row for 63. This follows the V4-Flash precedent.

## Introspection
`HFEngine.load` unrolls a Dory load (`looped.unroll`, exits 1/2/4, reader 2), so inject block 12
and read block 39 are unrolled entries. It runs on app `adapt-introspection-dory-4b`.

Engine checks (`introspection/engine_diagnostic.json`), all passed:
- beta 0 is an exact no-op;
- the steer is local: pre-span states are unchanged at 12 and 39, and the in-span state is
  h + β|h|u to bf16 precision;
- the steer reaches block 39 and the 2-loop output.

Measured calibration: NO-GO. Median RR is 0.04 at every beta (beta-0 baseline 0.039), and steered
replies change but never name the concept, even at β = 16. Status `ooc`.

## multihop: frozen early at Camila's request (2026-11-19)

Camila asked at ~19:00Z on 2026-11-19 to "just finish it now". The data-round loop (`dory-loop`, round L4) was stopped during the authoring phase of multihop fill waves 20-23. Nothing from that wave reached `cand/multihop.jsonl`, which was backed up first and still holds 1459 valid lines. multihop ships as **partial** with 86 of 100 items. Its stop rules had **not** fired: this is an early freeze, not an objective stop. The record is in report.json under `families.multihop.early_freeze`.

Per-wave yields in L4 (4 parallel waves of up to 120):

| waves | tier | authored | bank gain |
|---|---|---|---|
| 0-3 | t1 | 20 | +2 (83 -> 85) |
| 4-7 | t2 | 16 | +1 (85 -> 86) |
| 8-11 | t2 | 21 | +0 |
| 12-15 | t2 | 39 | +0 |
| 16-19 | t2 | 4 | +0 |

Authoring evidence. "Refusal" is the API stop_reason refusal. "Max_tokens empty" means the call wrote no text after 32k tokens of thinking, which triggers the low-effort retry. "Still empty" means the retry also ran out of max_tokens without parseable text.

| round | calls | refusal | max_tokens empty | still empty after retry |
|---|---|---|---|---|
| L2 | 97 | 16 | 53 | 23 |
| L3 | 145 | 31 | 72 | 33 |
| L4 | 210 | 41 | 97 | 65 |

These are genuine refusals or runs where thinking used up the token budget. They are not a parse, transport or auth bug, and no code was changed. The few candidates that were authored mostly failed the one-cue screen or the subject gate.

## Final freeze (2026-11-19)

Following Camila's "finish it now", the steps after the early freeze were:

1. `final 1` with the stock driver, which includes model_multihop. check_min_grid reported no MISSING/HIGH rows.
2. An independent audit dropped 120 rows.
3. `final 2`, then six addendum audits. Each re-freeze back-fills the freed slots from rows that already passed the gate, so every round of filled rows was audited, the must-drops were applied, and the set was re-frozen. This continued until a re-freeze added nothing new.

| round | rows added by the re-freeze | must-drops |
|---|---|---|
| final 2 | 48 | 16 |
| final 3 | 13 | 8 |
| final 4 | 8 | 4 |
| final 5 | 3 | 1 |
| final 6 | 1 | 1 |
| final 7 | 1 | 0 |

`final 7` is the shipped bank.

**Lucky guessing.** The report-only lucky measurement on the final bank (`outputs/adapt/dory-4b/final_report_7`) puts basic_readout above chance + 5: blind .272 and described .292, against .20. Every other MC family is within the bar. No rows were dropped for this, because the final measurement is report-only.

**model_multihop.** The mmh-1 confirm passed: blind .033 and described .026 after dropping its leakers, against chance .19. The 12 confirm leakers were dropped, leaving 92 items. The status is `refill_pending` because tier C was not run (early freeze). The family stays in the macro.

**Status relabels, with no rule changed.**
- poetry goes from partial to ooc. The stop rule is unchanged, applied to the final count of 16.
- relational_multihop ships as partial at 18, with the early-freeze note.

**Out of the macro.** multilingual_multihop and multilingual_typo have 0 items and are marked `exclude_from_macro`.
