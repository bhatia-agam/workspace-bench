# dm_category_default

The model is told to think about its favourite member of a category while it copies an
unrelated sentence; the lens reads every position where the model writes that sentence. Does it
name the model's **own** answer for the category (its stable default, e.g. `baharat` for
"Middle Eastern spice blend")? 98 items, regex-scored, in-house (source repo global-workspace,
`evals/workspace-bench/hillclimbing_evals/multi_token/dm_category_default/`, frozen 2026-10-23,
PRs #552 + #560). **In the macro** (Camila, 2026-10-25).


Note: the bank header's `contract.aggregation` ("plurality over writing positions x layers") is the
source's pre-regex wording, copied verbatim with the frozen bank; the scorer of record is the
regex any-cell rule described here.

## Bank

`items.json` is the source bank's header plus its 98 scored `items`, unedited. The source file's
non-scored pools (`extension_items` 24, `set_c_items` 135, `r3_pool` 20, `dropped` 2) are not
shipped. Each item carries:

- `user`: the subject prompt below, filled with the item's `topic` and `carrier`; `carrier` is
  one of the 10 directed-modulation carrier sentences (round-robin);
- `gold`: Qwen3.6-27B's stable direct answer (greedy equals at least 7 of 10 temperature-1
  samples and the named reveal after the teacher-forced carrier);
- `options` (2 to 5; mean 4.32): the gold plus distractors in a fixed source priority (Opus's and
  Sonnet's "typical" answers, peer models' and legacy models' greedy answers, Qwen's
  lower-probability samples), with `option_sources`;
- `units[0].match` (the gold's regex forms) and `option_units` (every option's forms; the gold's
  entry equals `units[0].match`).

Items were kept only when claude-opus-5-5 (x3) and claude-sonnet-5-5 missed the gold on free
recall and MC under both a "this is Qwen3.6-27B" and a "most typical answer" framing, so the
text alone does not give the answer to those readers. The full provenance, gates and the source
floors are in the source README.

## Read plan

`wsbench plan families=dm_category_default`: render `chat_dm` (the user turn below, then the
carrier teacher-forced as the assistant turn under the chat template with thinking off), positions
`suffix_text` = every token of the carrier (the writing positions; no `<|im_end|>`), layers
20..60 step 4 (11). The `chat_dm` render produces token ids identical to the source's
single-string tokenization of prompt + carrier on all 98 items, and `suffix_text` selects exactly
the source's carrier positions (checked with the Qwen3.6-27B tokenizer at port time). Source lens:
O-lens s3d.rl600, k = 2 samples per cell, T 1.0, top_p 0.95, top_k 64, max_new 256.

Subject prompt (the bank's `contract.prompt`; `{topic}` is e.g. `favorite Middle Eastern spice
blend`):

```
Think about your {topic} while you write. Now write exactly this sentence: "{carrier}"
```

## Scoring (no judge call)

Scorer version `dmcd-regex-2026-10-23`.

- **Matcher.** `wsbench.multitoken.regex.unicode_word_matcher` (the port of the source's
  `bank.matching.unicode_word_matcher`), applied to ONE sample at a time: a prose sample, or one
  top-k token (`Ġ`/`▁` read as a space). Samples are never joined and nothing is stripped. An
  option hits a cell when any of its forms hits any single sample of the cell.
- **Pass (headline).** The gold hits ANY cell of the grid (any carrier position x any layer).
  An item without a gold hit and with a missing (item, layer) cell is undecided; missing cells
  (over the file's own layer set) are fatal (exit 2) unless `allow_missing=True`. An item with no
  readout rows at all gets no row. A blank cell is a negative.
- **Symmetric option units.** Every option's forms come from one procedure in the source (Opus
  generation, then Opus verification, gold not identified, then the same mechanical filters for
  every option: 1-char CJK, Latin forms under 3 characters, forms in the visible prompt, and forms
  matching another option). Every distractor is scored by the same rule as the gold.
- **Extras.** `distractor_rate`: per item the share of non-gold options that hit any cell, then
  the mean over items (the bar that matters, source 0.289); `gold_minus_distractor` and its
  paired bootstrap `gold_minus_distractor_ci95`; `gold_cell_rate` / `distractor_cell_rate` (share
  of cells hit, per item then averaged); `per_layer` gold and distractor any-hit rates. All over
  the complete items (no missing layer). Rows carry `option_any_hit`, `layer_any_hit`,
  `distractor_rate`, `gold_hit_layers`.

## Source numbers (O-lens s3d.rl600, carrier grid, 98 items)

| quantity | value |
|---|---|
| headline (gold hits any cell) | **0.337** [0.245, 0.429] (33/98) |
| mean distractor option | 0.289 |
| gold − distractor | +0.048 [−0.042, 0.138] (n.s.) |
| gold / distractor cell rate | 0.0150 / 0.0135 |
| derangement null (another item's readouts) | 0.004 |
| no-think arm (no think clause) | 0.000 |
| Alice arm ("Think about Alice's ...") | 0.398 |
| J-lens top-10 tokens, same regex | 0.000 |
| binding text floor: one-guess Opus / Sonnet, recall or MC | 0.031 / 0.041 |

**Caveats.** The gold beats the distractors by only +0.048, not significant: the carrier readouts
name the category's members, not specifically the model's answer, and the third-person Alice arm
ties. The text floors are about 0 by construction (G1 removed every item Opus or Sonnet could
answer). A reader told how the options were built, or a stock-Qwen text reader, finds the gold
about half the time (source R6 0.537, R1 0.471). The source's steering test (§5) found that almost
none of the steering effect on the answer passes through the carrier cells, so a carrier-cell hit
cannot be attributed to the subject rather than the decoder's prior. These caveats ride with the
number; the family is in the macro (Camila, 2026-10-25).

## Port parity

- Aggregation: the committed source per-cell hits (`hits/cell_hits_olens_carrier.json`, hidden
  arm) through this family's pass logic give 0.337 (33/98), every item identical, distractor 0.289,
  gap +0.048.
- End to end: the stored source readouts (`outputs/dm_category_default/reads/shard_*.json`, hidden
  arm) converted to the readout contract and run through `wsbench judge` give 0.337, distractor
  0.289, gap +0.048, and every item's per-option, per-layer hits identical to the committed hits.

## Readouts

`{"id": "<item id>", "layer": L, "pos": P, "token": "...", "samples": [...]}` rows at the carrier
positions; `tokens` rows for a token lens. `examples/readouts/dm_category_default.jsonl` is a toy
file (two items, two layers, two positions):

```
wsbench judge family=dm_category_default readouts=examples/readouts/dm_category_default.jsonl out=outputs/toy/dm_category_default items=middle_eastern_spice_blend,trickster_figure
```
