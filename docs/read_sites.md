# Read sites for the association families (association, conjunctive, role-bound)

The readouts files of `association`, `conjunctive_association` and `role_bound_association` are
produced from a **summarize-prompt render**, read only at the prompt's suffix and the chat tail:
every token position of the summary sentence is read and fed to the summarizer. For
`association` the scene is the item's `prompt`. This page is the producer contract.

## Why

Over the positions of a bare stimulus render, a lens that merely echoes the current token hands
the judge the story itself, and the judge — not the lens — does the interpretation. Appending a
summarize request gives the lens a read site with a fixed semantic job, and reading only there
closes the loophole.

## Render

```
<|im_start|>user
{stimulus}   (association: {prompt})

Summarize the preceding story in one sentence.<|im_end|>
<|im_start|>assistant
<think>

</think>

```

i.e. the chat template with `enable_thinking=False` (empty think block), no system prompt, no
prefill. Story positions are unaffected by a suffix that follows them (causal attention), so a
producer that already holds a bare-render capture only has to capture the new tail.

## Sites

The 19 positions from the first suffix token through the end of the render, at the 11 grid
layers `readplan.GRID` = 20 / 24 / … / 60 (`layers=all` reads every model layer, 64 on
Qwen3.6-27B):

| rel (from end) | token |
|---|---|
| 18 | `Sum` |
| 17 | `mar` |
| 16 | `ize` |
| 15 | ` the` |
| 14–10 | ` preceding` ` story` ` in` ` one` ` sentence` |
| 9 | `.` |
| 8 | `<|im_end|>` |
| 7 | `\n` |
| 6 | `<|im_start|>` |
| 5 | `assistant` |
| 4 | `\n` |
| 3 | `<think>` |
| 2 | `\n\n` |
| 1 | `</think>` |
| 0 | `\n\n` |

All 19 sites are shipped so the judged grid is the same for every lens; the families'
`layers=` / `items=` keys still restrict.

`association_hard` is read at the same 19 sites as `association` (its scene is the item's
`prompt` too).

## Role-bound

- **Layers:** `readplan.GRID` (20..60 step 4, 11 layers) at the 19 sites.
  `wsbench plan role_bound_association` emits them as `suffix_text_then_tail`; the loader
  requires the whole 19-position span per (item, layer) (`min_full_positions = 19`, contiguous,
  ending at the final token). A judge-side story-echo guard refuses (or, under `allow_missing`,
  drops and counts) any cell read before the suffix.
- **Single-statement rule:** whatever the site, a relation counts only if ONE statement (one
  `- ` bullet of one sample, or one token list) names agent, action and patient.

## Producing a readouts file

One row per (item, layer, site) in the readout contract of the [top-level README](../README.md), `pos`
indexing the render above, `token` the site's token, e.g.

```
{"id": "q01_a", "layer": 52, "pos": 68, "token": "\n\n", "samples": ["- After a long day, Laura packed boxes in the kitchen, meticulously clearing the house before…"]}
```

(The files under `examples/readouts/` are dry-run fixtures; `wsbench plan` is the read site of
record.)

## relational_multihop

Read: every position starting after the second sentence, its full stop included, so
"Avery's landlord is Sam. Sam's sibling is Riley. In other words, Riley is Avery's" is read from
". In other words, Riley is Avery's".

| rule | positions (Qwen3.6-27B) |
|---|---|
| `{"kind": "suffix_text", "text": ". In other words, P3 is P1's"}` | the full stop of sentence two through the possessive blank: 9 (52 items), 10 (36), 11 (6), 12 (6); 966 per layer |

Render `bare`, layers `readplan.GRID` (L20..60 step 4). `rel-s00-a` resolves to indices 12..20 =
`. ▁In ▁other ▁words , ▁Riley ▁is ▁Avery 's` (the model's `tokenizer.json`). `wsbench plan`
asserts the anchor `". In other words"` occurs once per stimulus; `adapt` freezing refuses a
tokenizer whose span does not start on a token ending in `.`; the judge raises if a read
starts elsewhere.

## moral_rationale

| positions | layers |
|---|---|
| every position of the chat render (`{"kind": "all"}`: user-turn template, stimulus, assistant header) | `readplan.GRID` |

Render: the chat template with `enable_thinking=False`, the item's `stimulus` as the user turn
(and its `system` turn when the bank carries one), no prefill. A read needs one contiguous run
of >= 6 positions per (item, layer) ending at the item's last position
(`EvalSpec.min_full_positions = 6`), so a file holding only the last five positions exits 2.
