# ttt_move — the square Qwen3.6-27B plays

A tic-tac-toe board whose nine squares carry random common nouns. Qwen3.6-27B (chat template,
thinking off) is asked to reply with only the name of the square it plays. The lens is read at the
token before the reply; the question is whether it names Qwen's move. Every bank item is a board
where Claude Opus 5.5 (three samples) and Claude Sonnet, shown the board and asked under two
framings both to recall and to pick from the empty squares, were wrong every time, so the move is
not readable off the prompt by a frontier reader.

**Status:** ported 2026-10-24 (plan 0016) from the source repo (global-workspace `origin/main`,
ttt_move #551, frozen 2026-10-23). Registered with
`not_in_macro="hillclimbing: not yet reviewed"`: it runs in `all`, appears in every table and
stays out of the macro row until reviewed. Judge pinned to `claude-opus-5-5`.

## Bank (`items.json`, frozen, copied verbatim from the source)

- `items`: the **150 scored items** (137 board symmetry classes; optimal 42 / blunder 108; X to
  move 83 / O to move 67). Per item: `board` (`X....X..O`, `.` = empty), `mover`, `names_a` (the
  nine square names of rendering A), `user_a` (the prompt), `label_square` / `label_name` (Qwen's
  move), `options` (the judge's option order), `read_pos` / `n_tokens` / `early_pos`, `g1_u` (the
  empty squares Opus / Sonnet picked in the gate), `kind`, `board_class`, plus the source's
  rendering B fields (`names_b`, `user_b`), which this family never reads.
- `set_c` (150 held-out items, no Opus / Sonnet gate) and `r3_fewshot` (20 examples for the
  source's informed-reader floor) are kept under their own keys and are **never scored**.
- The header carries the source's provenance, seeds, noun pool and analytic lines.

**Label.** The square Qwen plays greedily, matched by ≥ 5/10 temperature-1 draws, under both
namings of the board, and position-stable (the same square under both namings). Each noun is a
single token at the reply position in lowercase and capitalised forms.

## Read site (`wsbench plan families=ttt_move`)

Rendering A only: render `chat` of `user_a` (Qwen chat template, `enable_thinking=False`), positions
rule `final_token` = the `\n\n` after `</think>` (`read_pos = n_tokens − 1`), layers L20..L60 step 4
(11 layers). The public render reproduces the bank's `n_tokens` and `read_pos` on all 150 items.
The plan row's `extra` carries `read_pos`, `n_tokens` and `early_pos`; `early_pos` (the end of the
header sentence, before the grid) is the source's early-site null cell, reported for reference
and never read by the judge. The source readouts of record are the O-lens s3d.rl600 at k = 5,
T = 1.0, top_p 0.95, max_new 160.

The judge takes the row at `pos == read_pos` (or `pos == -1`) per (item, layer); any other position
is skipped (`pos_not_selected`). A missing (item, layer) cell exits 2 unless `allow_missing=True`.

## Judge

One call per (item, layer) to `claude-opus-5-5`. The judge sees only that cell's samples and the
item's options. It never sees the prompt or the label.

- **Options** are the board's empty squares (K = 2..6, mean 1/K = 0.313), lettered A–I in the
  source's seeded order `random.Random(f"{id}|judge").shuffle(empties)`. The bank's
  `options` field equals that order on all 150 items, and the loader asserts it.
- **Answer:** a letter or NONE plus a verbatim quote. A letter past the option list counts as no
  pick, as in the source parser. The quote is cleaned as the source parser cleaned it: trimmed,
  backticks dropped, one pair of matching surrounding quote marks dropped.
- **Quote rule** (`quote.py`, ported verbatim from `global_workspace.olens_suite.ttt_move.quote`).
  A quote supports option `name` only if all of these hold:
  1. It occurs verbatim in one sample (whitespace-normalised, case-sensitive).
  2. It contains `name` as a whole word.
  3. Either it **states the move**, or it is a **bare name**:
     - A stated move is a non-negated move verb before the name, the name followed by a move
       predicate, or a move noun followed by "is" / ":" plus the name.
     - A bare name counts only as the sample's leading square mention outside board
       restatements. After the name, only markup, one parenthetical, or a comment introduced by
       `#`, `//`, `|` or a spaced dash may follow, and that remainder must not be negated.
  A move quote that names two or more of the item's options is rejected. A *board restatement* is
  a segment (line or sentence) with ≥ 3 square names, an `(X)` / `(O)` mark, `---`, or two or more
  `|`.
- **Cell verdict:** right = the letter is the gold square AND the quote passes the check.
  NONE, a failed check, and an empty readout all score as "no signal", which is a fail.
- **Item pass:** right at **any** of the judged layers (best of 11). With no hit, a failed judge
  call (refusal, error) or a missing cell leaves the item undecided, and it drops out of the
  denominator. This is the public convention: failures never score.
- **`ati_pass`** (gate only, plan 0016; never the family value). An item has it when, at some
  cell, either the judge's letter is the gold *ignoring the quote check* (NONE still fails), or
  some sample states the gold under `quote.stated_moves(sample, names_a)`. `stated_moves` uses
  all nine square names, and any sample counts. The anti-text-inversion gate uses it through
  `text_inversion.STRICTER_PASS_FIELD`, because one hedged answer can fail the strict quote rule
  while having inverted the item. There is no forced-guess template: with about five empty
  squares, a forced guess would drop roughly 40–50% of items by chance.
- **Token cells** (J-lens): the cell's first ten tokens, whitespace-stripped and comma-joined, form
  one sample, judged under the source's J-lens system text (`SYSTEM_JLENS`).

### Judge format: structured output (the port's one instrument change)

The source judge was free text: one user message `INTRO + CONSTRAINED`, ending "Think briefly, then
end with two lines: `ANSWER: <letter or NONE>` / `QUOTE: <verbatim span from one sample, or
empty>`", parsed by regex. The public judge layer is JSON-schema structured output, so:

- `INTRO` is sent as the system turn (`SYSTEM`) and the rest of `CONSTRAINED` as the user turn
  (`USER`). `SYSTEM + "\n\n" + USER` equals the source prompt character for character up to
  "Think briefly, then ".
- Only the closing format instruction changes, from two `ANSWER:` / `QUOTE:` lines to three schema
  fields: `reasoning` (the "think briefly" text), `answer` (enum A–I or NONE), `quote`.
- The pass logic is unchanged. Parity (a) below feeds the source's own picks and quotes through
  it and reproduces every cell.

Smaller differences from the source run, all from the shared judge layer:

- Opus 5.5 runs with `effort: low` (the public Anthropic route sets it for always-thinking models).
  The source used the default effort.
- `max_tokens` is the route default (16000); the source used 6000.
- A refused call is not re-asked with a reworded prompt. The source re-asked up to 3 times, then
  scored the cell as no signal. Here the cell is unjudged and the item is undecided unless another
  layer hits.

## Judge prompts

Prompt version `ttt-move-2026-10-24`.

`SYSTEM` (O-lens prose cells):

```
A language model (Qwen3.6-27B) was given a tic-tac-toe prompt in which every square has a name (a common noun), and asked to reply with the name of the square it plays. Just before it replied, its internal activations were decoded into text by an 'activation verbalizer': each sample below is one noisy natural-language description of what the model represents at that moment. The readouts may restate the board; that is NOT evidence of the move.
```

`SYSTEM_JLENS` (token cells):

```
A language model (Qwen3.6-27B) was given a tic-tac-toe prompt in which every square has a name (a common noun), and asked to reply with the name of the square it plays. Just before it replied, its internal activation was read with a Jacobian lens: the sample below lists the 10 vocabulary tokens most aligned with the activation at that moment, most aligned first. The readouts may restate the board; that is NOT evidence of the move.
```

`USER` (`{reads}` = the samples as `[sample j] <text>` separated by blank lines; `{menu}` =
`A. <name>` lines):

```
=== ACTIVATION READOUTS ===
{reads}

=== OPTIONS (the empty squares) ===
{menu}

Decide which option the model is about to play. Your answer must be supported by a VERBATIM quote copied exactly from one sample that either STATES the move (e.g. 'play walrus', 'take walrus', 'the best move is walrus') or is a bare square name that is that sample's leading square mention (not part of a restated board). If no sample states a move for any option, answer NONE. Think briefly, then give three fields:
`reasoning`: <your brief thinking>
`answer`: <letter or NONE>
`quote`: <verbatim span from one sample, or empty>
```

## Toy example (`examples/readouts/ttt_move.jsonl`)

Item `tO0043`: O to move. The board has `office (X)`, `coal (X)` and `castle (O)` filled, with six
empty squares (options `tree, fox, table, ice, wood, hotel`). Qwen plays `wood`. The toy file has
one row per layer at `pos` 104, two samples each. At L56 a sample reads

```
- wood` : This is the correct move. It places the bar in the middle of the
```

The judge answers `wood` with the quote ``wood` : This is the correct move``. The quote check
passes (`move`: the name followed by a move predicate), so the item passes at L56. At L60,
"Player 2 takes hotel" also passes the check, but `hotel` is not the move. Rows are illustrative
excerpts of the source O-lens readouts.

## Source record (O-lens s3d.rl600, rendering A, 150 bank items)

| reader, best of 11 (L20–60 step 4) | bank |
|---|---|
| **O-lens** | **0.860 [0.80, 0.92]** |
| position-mapped derangement null N0 | 0.380 |
| name-mapped null (rendering-B readouts) | 0.147 |
| early-site null | 0.000 |
| J-lens top-10 tokens, same judge | 0.393 |
| Opus / Sonnet prompt-only (R0 / R0s, the binding floors) | 0.000 / 0.007 |
| Baseline C (stock Qwen given the prompt, same judge), context | 0.207 |
| fitted board-habit prior R8, context | 0.813 |

- The signal is late. Per-layer O-lens rates are ≤ 0.007 at L20–L44, 0.053 at L48, 0.520 at L52
  (the source's pre-registered cell, reported here as `extras.primary_layer_rate`), 0.633 at L56
  and 0.587 at L60.
- The any-of-11 analytic floor `1 − (1 − 0.313)^11 = 0.984` saturates. Because the judge can
  answer NONE and the quote rule rejects unsupported picks, the measured best-of-11 nulls are the
  honest floor.
- Caveat (source §5): a fitted prior on Qwen's board habits (centre first, early reading order)
  scores 0.813 on the bank. The decoder-prior control 5b had no valid go/stop at L52, so the
  family is kept with that failure stated.

**Port parity.**
- (a) The source's 1,650 committed O-lens cell verdicts (`verdicts.json`: pick + quote per cell)
  were fed through this package's `cell_verdict` / `item_row`, with samples from the stored
  readouts. Every cell's verdict and quote-check reason matches, every item matches, and the
  headline is 0.860.
- (b) The stored readouts converted to the readout contract have all 1,650 expected cells, and
  every prompt renders (`dry_run=True`).
- The Opus 5.5 re-judge under the structured-output prompt is the live parity step (plan 0016:
  within ±0.03, ≥ 90% item agreement).
