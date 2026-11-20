# introspection

*Renamed from `introspection_inject` on 2026-10-26. Plan 0045 (2026-10-30, Camila's
"Introspection" feedback) moved the family to bank v2 (`items_v2.json`): paired controls,
near-duplicate equivalents, shipped vectors, a stricter judge and a lite site. `items.json` is
the frozen v1 and stays untouched.*

A concept vector is injected into Qwen3.6-27B's user turn at layer 12; the visible text never
names it. Can a lens reading the UNSTEERED positions downstream name the injected concept?
**In the macro** (Camila, 2026-10-25). Its macro value is the **paired** 125-item protocol β=4
headline rate (`metric = pass_rate`); controls never enter it. Ported from the source repo
(global-workspace `origin/main` 120174e4, plan rev 17 §7.2; port plan
`plans/0016-four-model-specific-families.md`; v2: `plans/0045-wsb-bp-introspection.md`).

## Headline (`jhead-v2`): the paired LLM judge

The headline is an LLM judge with one loose naming rule, "the concept or a close equivalent,
mentioned in any way", paired against the gaussian twin. Result stamp
`ii-grid-2026-11-v4+twinrx-v4+jhead-v2` (`PROMPT_VERSION`).

- **Judge** (calls keyed `CALL_VERSION = "ii-grid-2026-11-v4"`): a blind forced choice over the
  cluster's five concepts, "no injected concept" and "cannot tell" (native per cell, summary per
  unit on its digest). An option is named if a sample names that concept or a close equivalent,
  in any way; the rubric has no further exclusions (labels inside names, titles, codes or
  acronyms, related words, hypernyms, buried words) and no exact-word tie-break. Code only
  verifies the pick: the quote is in the readouts (`digest.quote_ok`) and names no option
  outside A(c).
- **Paired** (decision Q12): `pass = pass_unpaired and not` the gaussian twin's own judge
  verdict naming the target, with the same judge, rubric and read window as the hit (Paired
  controls, below). Controls, floors, `paired_all_twins` and `beta0_prior_rate` are the judge's.
- **The regex as a diagnostic.** A deterministic regex for the target or a Q12 equivalent in any
  loaded raw readout (inflection tolerant, names and acronyms skipped; the round-4 headline
  `rxhead-v1`), paired against the same regex on the twin, is reported on inject, gaussian and
  cross rows as `rx_pass_unpaired`, `rx_cells`, `rx_quote` (inject rows also `rx_pass`,
  `rx_twin_quote`) and in `extras.regex_paired` / `extras.regex_unpaired` (and per
  sub-headline) and `extras.regex_per_layer_any_position`. It never sets `pass`: a regex cannot
  tell a concept the readout presents from an incidental mention. Every run computes it; the old
  regex-only switch `opts=judge=off` is removed, and any `opts=judge=` exits 2.

The all-layer config reads ~1,056 readouts per item, so a "mentioned anywhere" rule saturates
there: under the round-4 regex its random twin named the target in 25% of items (all-layer
unpaired .800, paired .584 on the final O-lens readouts), which the pairing removes. Report the
twin's rate beside the headline.

## Bank (`items_v2.json`, version 2, built by `scripts/introspection_build_v2.py`)

- **125 concepts in 25 fixed clusters of 5 semantic neighbours** (Agam's 50 paper words + 75 new
  words in the same register; `clusters`, `concepts`). Options per item: the concept's cluster,
  "no injected concept" and, LAST, "cannot tell from the readout" (7 options; the six
  substantive ones keep v1's seeded order, seed 20261023; cannot-tell is never shuffled in).
- **Prompts.** `protocol` (primary): Agam's four-turn injected-thought protocol at Trial 1,
  thinking off, prefilled through `... The thought is about the word "`; the trial turn
  (positions 97–116) is steered. `neutral` (secondary): Agam's four neutral prompts, no
  prefill; the user content is steered.
- **2,250 scored items:** inject 1,250 (125 concepts × β 4 / 2 × protocol + 4 neutral),
  gaussian 500 (norm-matched random direction, same β; protocol + one rotated neutral prompt),
  cross 500 (another cluster's concept vector, judged against THIS item's options; same layout
  as gaussian). Plus **12 `beta0_rows`** (protocol Trial 1–8 + the 4 neutral prompts, no
  injection), each judged against all 25 clusters (`options_by_cluster`).
- **Twins** (v2, every inject item): `twins = {gaussian, cross, beta0}`. gaussian =
  `gaussian|<prompt>|b<β>|<c>` (protocol: the same prompt; neutral: the concept's one rotated
  gaussian prompt), cross = `cross|<prompt>|b<β>|<c>`, beta0 = `beta0|<same prompt>|b0||<c's
  cluster>`. All are existing plan rows: the pairing adds no plan row and no GPU cell.
- **Headline = the 125 protocol β = 4 inject items** (`headline: true`). Everything else is
  reported in `extras` and every other result row carries `excluded_from_rate: true`.
- `renders`: the 12 distinct renders (`protocol:trial1..8`, `neutral:<key>`), regenerated with
  the source renderer and the `Qwen/Qwen3.6-27B` tokenizer: `input_ids`, `tokens`, `inject_span`,
  `grid`, `null`, `echo`, and (v2) `lite`, the reads=lite site as absolute positions.
- Items and `beta0_rows` are the source bank (v1 verbatim plus the v2 fields above);
  `largest_class_share`, `agam_reproduction`, `vector_space_check` and the G3 leak lint are the
  source's provenance. The source's pre-grid header keys (`read_layers` [20, 36, 44, 52, 60],
  `primary_layer`, chance "1/6") moved to `spec.legacy_v1`; the grid of record is below.

## Near-duplicate options (decision Q12: "these terms should count")

Some clusters hold near-duplicates (machines / gadgets / robots, bags / backpacks, trees /
leaves / forests, youths / teenagers / children). They **count as the concept**, through the
bank's frozen `equivalents` table: A(c) = {c} ∪ `equivalents[c]` is the accept set, used
identically by the headline, the floors, the twin's judge verdict and the regex diagnostic. The table is
symmetric (no one-directional rows); cliques and pairs:

- From Q12 (Camila's groups): {machines, gadgets, contraptions}; robots ↔ machines;
  bags ↔ backpacks; {trees, leaves, forests}; {youths, teenagers, children}.
- Proposed by the plan (site: "Decisions taken (override if you disagree)"): bags ↔ purses,
  bags ↔ suitcases, purses ↔ wallets, trees ↔ branches, trees ↔ roots, elders ↔ grandparents,
  snow ↔ blizzards, poetry ↔ sonnets, novels ↔ stories, sadness ↔ grief, empires ↔ kingdoms,
  emperors ↔ pharaohs, ash ↔ soot, deserts ↔ dunes.
- Every other concept: A(c) = {c}. The relation is not transitive (bags ~ purses and purses ~
  wallets do not make bags ~ wallets).

`concepts[].extra_forms` lists non-option words that name a concept: **gadgets: devices,
machines: devices, robots: robotics**. The judge's menu renders, for EVERY option alike (so the
gold is never singled out), its "also" words and the shown options it is "same as":
`gadgets (also: devices; same as: contraptions, machines)`, `youths (same as: children,
teenagers)`. The judge still picks the option literally named (a readout saying "backpack" makes
it pick `backpacks`, which then counts for the `bags` item).

"Same as" groups on one token line: the shared token-list rule says a line holding two or more
options singles out none of them; the family adds ONE clause after it (the only relaxation of
the shared note, sanctioned by Q12): a line whose options are all "same as" one another singles
them out together. The scorer narrows it mechanically: a pick counts for item c only if the pick
is in A(c) AND every option the verified quote names (`judge.quote_options`: label, surface or
"also" forms, `mc.form_in`) is in A(c). "trees | leaves" passes the `trees` item but not the
`branches` item (trees ~ branches, but leaves ∉ A(branches)).

## Paired controls (decision Q12: the random-vector twin voids a hit)

An inject item is a hit only if the judge does not also name the target on its MATCHED gaussian
twin, judged by the same judge, with the same rubric, on the same cells as the hit:

- **The twin's judge verdict** is its unit's own pick credited to A(c) (`judge.credited`: in
  A(c), quote verified, the quote names no option outside A(c)). Native: any judged cell of the
  grid; summary: its one call on the digest of every loaded cell, i.e. the same layers ×
  positions as the hit (protocol: 24 positions × 11 layers). A "cannot tell" / "no injected
  concept" pick is not a twin hit.
- `pass = pass_unpaired and not` that twin hit; a missing gaussian twin, or one whose judge was
  unavailable, makes `pass` None (undecided, `n_twin_missing`), never scored unpaired.
- Only the twin's judge verdict voids: a twin sample that merely matches a form of A(c) by
  regex feeds the regex diagnostic (`rx_twin_quote`, `rx_pass`; below), never `pass`.
- The cross and beta0 twins are **reported columns only** (`paired_all_twins` voids on any of the
  three; `beta0_prior_rate` = share of items whose unsteered beta0 readout the judge credits to
  A(c), the lens's prior). Reason: beta0 is one shared readout per cluster, so voiding on it
  would make whole clusters unwinnable for a lens with a prior.
- Rows carry `pass_unpaired`, `twin_hits = {gaussian|cross|beta0: {judge, judge_decided,
  quote}}` (`quote` = the twin's verified quote at its first credited cell; None for beta0),
  `paired_all_twins`, `beta0_prior`; `extras` carries `headline_unpaired`, `paired_all_twins`,
  `beta0_prior_rate`, `n_twin_missing`, `voided` (each voided headline item with its twin id and
  `twin_quote`) and the same columns per sub-headline.
- **The twins are always judged with their item:** any scope (`opts=scope=`, `items=`, `limit=`)
  adds the twins of its inject items.

**Regex diagnostic matcher** (`judge.regex_hits` / `judge.twin_regex`, deterministic): a loaded
sample of a readout's cells names a form of A(c): every word of A(c) with its `surface_forms`
(label, singular / plural, irregulars such as oasis / cacti, curated Chinese of ≥ 2 characters;
never a 1-character form such as 金 / 雪) plus its "also" words, word boundaries,
case-insensitive, CJK as a substring; the last word of every Latin form also matches its regular
inflections (`judge.inflected`, `twinrx-v4`: "dreaming" names dreams, "glued" glue). Token
cells: each token, stripped, as a whole (tokens are never stitched). It reads exactly the cells
the run loaded, never the digest. Name rule: an acronym of
a lower-case form before the noun an acronym names ("GLUE test") or a capitalised word beside
another capitalised word of a multi-word name or title ("Judea Pearl", "String of Pearls") is
skipped; a Title-Case heading or label, or a short quoted Title-Case answer
(`'The concept appears to be **"Shopping Bag."**'`), is not.

Plan 0045 measurement (when a twin still voided on its judge OR a regex match): the offline
effect on the source verdicts (protocol β4, native, all 11 layers × 24 positions;
`scripts/introspection_offline_evidence.py`, which runs this module's `_row` / `pair` /
`summarize`; the source verdicts carry no quotes, so the group check is not applied offline):

| reader | unpaired v1 (A(c) = {c}) | unpaired (A(c)) | paired, judge leg only | paired, regex leg only | paired (judge OR regex void; the plan-0045 headline) | `paired_all_twins` | `beta0_prior_rate` |
|---|---|---|---|---|---|---|---|
| O-lens s3d.rl600 | 0.856 | 0.888 | 0.640 | 0.696 | **0.640** | 0.544 | 0.304 |
| J-lens | 0.376 | 0.416 | 0.416 | 0.416 | **0.416** | 0.408 | 0.000 |

The gaussian twin voids 31 O-lens passes (e.g. `inject|protocol:trial1|b4|information`: PASS →
FAIL, its gaussian twin's readout is judged to name "information"; `…|trumpets` stays PASS):
the O-lens names these concepts under a norm-matched random-vector injection too. The J-lens is
untouched by the pairing. A(c) adds O-lens passes for pharaohs, youths, branches, contraptions
and J-lens passes for blizzards, dunes, grief, leaves, novels; it also raises the O-lens floors
(gaussian 0.200 → 0.256, cross 0.216 → 0.272, beta0 0.224 → 0.304).

## The steer and the vectors

`wsbench plan families=introspection` writes 1,762 rows: every inject and gaussian item
and the 12 beta0 rows. Cross items get no row: a cross item's activation is bit-for-bit its
partner's inject activation (the visible text is identical across concepts), so it reads the
partner's readout (`readout_of`; the partner row lists it in `extra.readout_reused_by`). Each
row is `render: captured` with `extra.input_ids`, the read positions (the grid) × layers
20–60 step 4, and `extra.steering`:

- concept: `{type: concept, concept, beta, inject_layer: 12, token_span: [97, 116] | the
  neutral prompt's user span, formula, vector_file, vector_row}`: `h <- h + beta * ||h|| * v_hat`
  on the output residual of decoder block 12 at every position of the (inclusive) span, LoRA
  adapter disabled, `v = vector_file[vector_row]`, `v_hat = v / ||v||`;
- gaussian: `{type: gaussian, seed, rng, vector_file, vector_row, ...}`, injected the same way;
- beta0: `{type: none, beta: 0}` (a plain forward; no file, no row).

**The vectors ship with the bank** (plan 0045 §2.3, Camila: "include the vectors in the public
repo"):

| file | shape | dtype | rows | sha256 |
|---|---|---|---|---|
| `vectors/concept_vectors_L12.npy` | (125, 5120) | float32, RAW (un-normalised) | `concepts[]` order | `3cd9bbdf4c2863915d46e57b90a5ced6fe6a1c9b28e6aed7b9c20c0a5426c8a0` |
| `vectors/gaussian_vectors_L12.npy` | (500, 5120) | float32, RAW `randn` draws | gaussian items in bank order | `27a420ab60137b7c4c72ebbc163713f23f35d967718d5f452d2fa43d8d1265a2` |

The concept vectors are the source's vectors of record (`ii_modal.py --mode vectors`,
`vectors.json` sha256 `d663b8ca…a47a`), converted losslessly; every row matches the bank's
`vector_fingerprint` (`sha256(json.dumps([round(x, 3) for x in v]))[:16]`, 125/125) and
`vector_norm_L12` (norms 1.47–2.50). The gaussian rows are `torch.Generator().manual_seed(seed);
torch.randn(5120, generator=g)` on CPU (bit-identical under torch 2.9.1 and 2.15.0); shipping
them removes the dependency on torch's RNG. `scripts/introspection_export_vectors.py`
regenerates both (CPU only). The bank's `vectors` block records path, sha256, dtype, shape and
row order; `items[].vector.row` indexes the file. Licence: NOTICE.md.

The recipe (`vector_recipe` in the bank, Agam's, unchanged): the residual at layer 12 on the
LAST token (the final `\n\n` of the generation prompt) of the chat-templated user turn `Tell me
about {word}` (lowercase, thinking off, adapter disabled), minus the mean over the paper's 100
printed baseline entries (`vector_recipe.baseline_words`, `butterflies` twice).

**Produce with `wsbench produce`, or your own steered forward.** `wsbench produce` applies
`extra.steering` itself (`Producer.steering`: a forward hook on decoder block `inject_layer`,
the dose above over `token_span`, `v` from the shipped file); it refuses any other steering
type. The ML-NLA arm maps the same fields to xreader `steer` records
(`scripts/plan_to_xreader_jobs.py`, gpu workstream), so every arm steers from one definition.

**Adapted sets of the large MoE subjects (plan 0067).** glm-5.3, deepseek-v4-pro,
muse-spark-open and kimi-k3 are measured by `scripts/adapt_introspection_mp_modal.py`, a
multi-GPU stack behind `wsbench.adapt.introspection_ops`. `measure` is recorded as an op list,
executed batched and sharded with the same dose formula at the same block output, and replayed.
The stack, the packing and the residual mode are recorded in the adapted bank's
`calibration.engine`. Two subjects have a non-plain residual, set in `spec.residual`:
- V4-Pro: `mhc_raw_flat_28672`, the four mHC streams flattened.
- Kimi-K3: `attnres_full_sum`, the norm of full_sum, added into prefix_sum.

For those subjects the plan rows carry `steering.residual`. `wsbench produce` refuses such rows,
because its plain block-output hook would apply a different dose, so produce them with that
subject's stack.

`extra.diagnostic_positions` (`null`: the 2 positions before the span, causally blind; `echo`:
one steered token) are the source's diagnostics; they are never scored and a producer may skip
them.

## Read grid and lite site

Every unsteered position from just after the steered span through the last prompt token, × all
11 layers 20–60: protocol 24 positions (117–140: `<|im_end|>`, the assistant header with its
empty think block, and every prefill token up to the open quote) = 264 cells; neutral 9
positions (the template tokens `<|im_end|>` … final `\n\n`; meeting_note 23–31) = 99 cells.
Readout ids are the plan row ids; `pos` is the absolute index into `input_ids`. Rows at other
positions or layers are skipped and counted. Full-read completeness: `min_full_positions = 9`,
explicit positions (`full_contiguous = False`). Any layer subset works (`layers=`).

**`reads=lite`** reads one position per row at every grid layer, fixed from the bank (never
chosen by pass rate): protocol `[140]` (the final token, the open quote), neutral `[grid[1]]`
(the `\n` after `<|im_end|>`, e.g. meeting_note 24). Twins are read at their own render's lite
site. The neutral site is checked by a support test, no judge outcome:
`scripts/introspection_offline_evidence.py --lite-support` counts gold-bearing digest evidence
lines at the final token vs `grid[1]` over the `reads=full` all-layer runs; unless `grid[1]`
beats the final token by more than 10 points, the neutral rule becomes `final_token`.

## Scoring

- **Native (`opts=aggregate=native`): one blind call per (scored unit, cell)** on
  `claude-opus-5-5` (pinned, the source judge of record): the cell's samples and the unit's
  seven options, never the prompt, the dose or the gold. A prose cell shows every sample
  verbatim; a token cell shows its tokens as ONE `" | "`-joined ranked list under the shared
  token-list rule (`mc.token_note` of the registered spec) and the "same as" clause. Cross units
  judge the partner's cells with their own options; each beta0 activation is judged once per
  cluster.
- **None rule and quote gate.** "no injected concept" is the answer exactly when no cluster
  concept can be quoted; "cannot tell from the readout" when the samples neither name a concept
  nor clearly report no injection. A concept pick whose quote fails `digest.quote_ok` (a prose
  span inside one sample; one token or several tokens of ONE list joined by `" | "`; a word spelled
  across adjacent positions of one layer) is forced to none, as is an out-of-range choice
  (`extras.audit.forced_none`). An empty cell names nothing. Cannot-tell is never a hit on an
  inject item and never a false positive on a control (`extras.audit.cannot_tell`).
  `extras.audit.quote_lacks_label` counts verified picks whose quote is not the literal label;
  `extras.audit.quote_in_name_or_code` (never scored) counts picks quoted inside a capitalised
  name, a digit, a hyphen-code or an acronym.
- **Pass (unpaired): ANY judged cell picks an option of A(c) whose quote names no option outside
  A(c)** (max over the grid); **the headline `pass` is paired** (above). An unavailable judge call
  is no pick (source rule) and is counted in `n_unjudged_cells` (`complete: false`). A unit with
  no judged cell at all is undecided. Grid cells the readouts file lacks count as missing (fatal
  unless `allow_missing=True`); a unit whose readout id has no row at all gets no result row.
- **Floors on the identical grid** (`extras.floors["<prompt>|b<β>"]`), with the same A(c):
  gaussian / cross: share of items on which any cell credits the item's own concept; beta0:
  share of (activation, cluster concept) pairs on which any cell credits that concept
  (`chance_hits`). **Floor of record = the max of the beta0, cross and gaussian floors**
  (`extras.floor_of_record`, `extras.margin_over_floor`). `extras.false_alarm_any_of_grid` =
  share of units with ANY concept picked. Native runs also report
  `extras.layer_pick_columns` (items whose gold / a distractor was picked at any cell).
- `extras.subheadlines` carries the four inject rates (protocol / neutral × β 4 / 2), each
  with its unpaired rate and the regex diagnostic columns (`regex_paired`, `regex_unpaired`); `extras.headline_per_layer_any_position` the
  headline's per-layer (unpaired) hit rate.
- **Scopes** (`opts=scope=`): `all` (default), `protocol`, `headline` (the 125 headline items and
  their twins: 125 gaussian + 125 cross units and the trial-1 beta0 row's 25 units). A scope
  other than `all` is never `complete`.

**Text-inversion caveat.** A text-only reader sees ONE prompt, byte-identical across all 125
headline items, and the same option set across a cluster's five items, each of which is gold
once: it is bounded at ~1/5 within a cluster by construction (`extras.informed_text_bound`). The
ATI gate reads the UNPAIRED pass (a text reader's twin is just another draw of the same text).

## Source numbers and port parity (v1 instrument)

s3d.rl600 O-lens (k = 3, T = 0.8, top-p 0.95, 96 new tokens) and J-lens top-10 on the grid,
judged by Opus 5.5 in the source repo under the v1 rubric (unpaired, A(c) = {c}):

| reader · sub-headline | any-of-grid hit | floors β0 / cross / gaussian | floor of record |
|---|---|---|---|
| **O-lens · protocol β4 (headline)** | **0.856** | 0.215 / 0.216 / 0.200 | 0.216 (cross), margin +0.64 |
| O-lens · neutral β4 | 0.922 | 0.140 / 0.128 / 0.128 | 0.140 |
| J-lens · protocol β4 | 0.376 | 0.016 / 0.016 / 0.000 | 0.016 |
| J-lens · neutral β4 | 0.458 | 0.018 / 0.016 / 0.016 | 0.018 |
| O-lens protocol / neutral β2 | 0.680 / 0.866 | 0.215 / 0.140 (record) | |

Text-only Opus prompt-only readers (5 concept options, told a concept was injected): 0.190
protocol, 0.207 neutral. The v1 port reproduced every number above from the committed per-cell
verdicts, and its prompts were byte-identical to the source judge's. **v2 ends that parity**
(new menu, rubric and token rendering): v2 numbers come from the campaign run, not the source
cache.

## Judge prompts (`ii-grid-2026-11-v4`)

The system prompt, schema `introspection_verdict` (`choice` integer, `quote`):

```text
You are judging readouts of a language model's internal activations in an interpretability benchmark. One internal
activation was turned into text. You get the readout samples for that activation and a numbered
list of OPTIONS: five concept words, the option "no injected concept" and, last, the option
"cannot tell from the readout". A concept option may list "also" words (other words that name
it) and the options it is "same as" (options that count as the same concept).

Decide which ONE concept option the readout names.
- An option is named if a sample names that concept or a close equivalent, in any way.
- Options marked "same as" one another count as ONE concept: answer with any one of them.
- If different samples name different options, choose the one named most often / most
  prominently. In a token list, an option counts only where the token-line rule in the user
  turn singles it out.
- Choose "no injected concept" when no sample names a concept option.
- Choose "cannot tell from the readout" when the samples neither name a concept option nor
  clearly report that no concept was injected.
- For a concept choice, "quote" must be the shortest span copied VERBATIM from one sample that
  names it; for a token line whose options are all "same as" one another, quote the whole line
  (its tokens joined by " | "). Otherwise "quote" is "".
Judge only what is written. Return JSON {"choice": <option number>, "quote": "..."}.
```

The user turn: `{options}` = one `N. <option>` line per option in the item's order (an option
with "also" words or "same as" options renders as `label (also: …; same as: …)`); `{note}` = the
prose note, or the token-list note followed by the spec-rendered token rule and the "same as"
clause; `{samples}` = the samples joined by newlines, each rendered with the sample template.

```text
OPTIONS:
{options}

{note}

{samples}
```

Prose note:

```text
The samples below are independent free-text readouts of the same activation.
```

Token-list note (then `mc.token_note` of the spec, `digest.SUMMARY_NOTE_TOKENS` below, then the
clause):

```text
The sample below is ONE ranked list of the top vocabulary tokens read from this activation.
```

The "same as" clause (`SAME_AS_LINE`):

```text
Options marked "same as" one another count as ONE option for the line rule above: a line whose options are all "same as" one another singles them out together; answer with any one of them.
```

Sample template:

```text
[sample {n}]
{sample}
```

## Summary mode (the default; `opts=aggregate=native` opts out)

Use a separate `out=` dir per mode.

- **Hook.** Every unit's cells are selected and accounted for first (`n_expected` / `n_missing`
  exactly as native), then ALL of each readout's loaded cells (every read layer and position, no
  token cap drop: the global cap with hierarchical overflow) go to ONE `digest.collapse` call with a
  per-readout task note (`item_task_notes`: the prompt kind's note; controls and twins get their
  prompt kind's note, so floors and pairs stay matched), then the calls are built.
- **Refusals.** `FAMILY_DEFAULTS["introspection"] = {"summ_fallback": "default+claude-sonnet-5-5"}`
  (audit F3; Sonnet 5 before 2026-11-01): a digest Opus declines re-runs server-side on a fallback
  model, and one still declined re-runs on Sonnet 5.5 (`extras.digest_served_by`); a unit still
  unsummarized is undecided (`extras.summary.n_units_unsummarized`), not a lens failure.
- **Judged unit: one call per scored unit** on the digest of the unit's `readout_of` activation,
  shared by every unit that reads it; the beta0 / cross / gaussian control units and the twins
  are judged exactly like the inject units.
- **None rule and quote gate** as native, with `digest.quote_ok` against the digest's evidence
  lines only (never the note-taker's statements; a quote spanning a bullet mark `⁞` verifies, as
  the mark folds to a space). An empty digest names nothing. The regex diagnostic reads the loaded
  raw cells, not the digest.
- **Rows** gain `summary`, `summary_statements`, `summary_evidence`, `summary_truncated` and
  `summary_state`; `picks` / `hit_cells` carry the synthetic `L-1` cell; `earliest_layer` and
  `extras.headline_per_layer_any_position` are omitted. The result records
  `config.aggregate = "summary"`, `config.summarizer`, `config.source_kind` and
  `prompt_version = ii-grid-2026-11-v4+twinrx-v4+jhead-v2+digest-v5-task-extractive-layered-v1x4+sj-v10`
  for a multi-layer run under the defaults (`digest.prompt_version`; no `-layered-v1x4` for one
  layer; `+reads-lite` on a lite run).

The summary-mode system prompt is `SYSTEM` with its input sentence replaced by `SUMMARY_INPUT`:

```text
A language model's internal activations, at every read layer and token position, were turned
into text. You get a digest of the readouts (described in the note in the user turn) and a
numbered list of OPTIONS
```

The summary-mode user turn (`{options}` as native, `{note}` below, `{summary}` = the digest):

```text
OPTIONS:
{options}

{note}

{summary}
```

The digest notes, shared with every hooked family (`wsbench.digest`): `{note}` is
`SUMMARY_NOTE` under `summ_render=extractive` (the default) or `SUMMARY_NOTE_ABSTRACTIVE` under
`abstractive`, followed on a token-lens file by `SUMMARY_NOTE_TOKENS` (= `mc.token_note` of the
spec) and the "same as" clause.

`SUMMARY_NOTE`:

```text
The readout below is a digest of the readouts across every read layer and position: for each read layer, a note-taker who did not see the passage picked the most prominent readout samples, then samples carrying content seen in only one or a few samples, and the layers' picks are merged, the most-stated first. Each line is marked with how many readout samples state its content ([N samples], or [N samples, M layers] when it was seen at M read layers): counted per claim, so a sample that only lists the word among others of its kind, or only restates the question, is not counted; compare these counts when weighing lines against each other. Each line is one real readout sample (a free-text generation, or one ranked list of top tokens). Treat each line as a separate sample: pieces on different lines never combine. Any quote must be copied from inside one line, without the bracketed marker.
```

`SUMMARY_NOTE_ABSTRACTIVE`:

```text
The readout below is a digest of the readouts across every read layer and position, written layer by layer by a note-taker who did not see the passage, most prominent first, then content seen in only one or a few samples. Each line is one statement in the note-taker's words, how many samples state it (counted per claim), and a verbatim evidence span from one real readout sample. The statements are not evidence: judge what the evidence spans show, treat each line as a separate sample (pieces on different lines never combine), and copy any quote from inside one evidence span.
```

`SUMMARY_NOTE_TOKENS`:

```text
A line whose items are separated by " | " is one ranked list of the top vocabulary tokens read from ONE activation, best first. Several tokens of the same line may jointly express one meaning, and a quote from such a line is one token or several tokens of that same line joined by " | ". Tokens of adjacent positions at the same layer may be joined only to spell one word split across them; such a quote is that word. Tokens on different lines never combine otherwise, and a relation (who does what to whom) must be stated within one sample (for a free-text sample, within one of its "- " bullets; in a free-text sample, bullets are separated by ⁞). A line that holds two or more of the options singles out none of those options, whatever their rank. A line that holds a run of interchangeable words or names of one kind (numbers, months, colours, countries, cities, people, works, ...) singles out none of the words on it, whatever their rank, even when only one of them is an option. Otherwise, an option that is the only option on its line is singled out by it.
```

Task notes (the digest's `task` variant; the task type, never the item's prompt, options or
gold). Family-level `DIGEST_TASK_NOTE`:

```text
the model reads a short request, and its activations may or may not have been steered toward a concept, which may appear in only one or a few readouts
```

Protocol items, their twins and controls (`TASK_NOTE_PROTOCOL`):

```text
the model was asked whether it detects an injected thought and what it is about; a concept may appear in only one or a few readouts
```

Neutral items, their twins and controls (`TASK_NOTE_NEUTRAL`):

```text
the model was given an ordinary short request; its activations may have been steered toward a concept, which may appear in only one or a few readouts
```

## Commands

```bash
wsbench plan families=introspection out=outputs/plan             # 1,762 steered rows (full)
wsbench plan families=introspection reads=lite out=outputs/plan  # the same rows, lite sites
wsbench produce family=introspection method=jlens out=R.jsonl    # applies the steer
wsbench judge family=introspection readouts=R.jsonl out=DIR dry_run=True
wsbench judge family=introspection readouts=R.jsonl out=DIR opts=scope=headline
wsbench judge family=introspection readouts=R.jsonl out=DIR      # full controls run
```

## History

- 2026-11-04 (`ii-grid-2026-11-v4+twinrx-v4+jhead-v2`): the paired LLM judge, with one "close
  equivalent, in any way" naming rule, is the headline again; the round-4 regex headline
  credited incidental mentions and is now a diagnostic, and only the twin's own judge verdict
  voids a hit.
