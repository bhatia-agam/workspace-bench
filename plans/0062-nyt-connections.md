# Plan 0062: nyt_connections — can a lens read the connection Qwen will choose?

Status: FINAL rev 8.1 (2026-11-02; critique rounds 1–7 applied, round 7 found no substantive issues; targets v1.1.0 / #233). Family `nyt_connections`, group
`model_specific`. Pilot of record: global-workspace branch `camila/connections-feas`,
`docs/project/experiments/connections/README.md` (follow-ups 5–6) and its fresh-context `AUDIT.md`.

## 0. Decisions (Camila, 2026-11-02)

- **Bar = beat the prompt-only baseline.** Camila: "we just want to beat a prompt only baseline, i
  don't care whether the qwen option is picked more than nyt answer". The continuation floor and
  the slot-0 (next-text) concentration are therefore **reported, not gating**: the family is
  registered whatever they show, with both numbers beside the headline. This overrides the general
  "low continuation floor too" guidance for this family; the README says so in one line.
- **Per-category scoring, labels only** ("let's just keep the old way"), all four of Qwen's groups,
  same-connection distractors removed, headline on groups stable under 16 samples.
- **NYT text is never committed** (public repo, unlicensed mirror; the ids-only pattern of plan
  0018). Text exists only at plan time and in the user's local cache.
- **Summary step = the bench's v1.1.0 design** (#233, Camila 2026-11-02: "a single summary of the
  layer summaries"): per-layer digests, then ONE stage-2 Opus summary of all the layer digests
  (`summ_layers=layered`, the CLI default for every multi-layer config of a non-numbers family via
  `digest.resolve_layer_mode`), then the judge. Not the pilot's custom extractor, and not the v1.0
  mechanical `union` merge: the pilot numbers are re-measured, not ported.

## 1. Construct

Qwen3.6-27B sees an NYT Connections puzzle and answers with **member words only** ("Do not name or
explain the connections"); a follow-up turn names the connection it had in mind for each group (the
label). The lens reads the **last 12 tokens of the prompt**, before Qwen writes anything. Per Qwen
group (a *slot*): does the digest of the readouts point to **Qwen's** label, among labels of competing
groupings of the same words (the NYT label, red-herring labels) and an unrelated label?

Pilot (bank v1, 335 puzzles / 905 slots, custom uncapped extractor + union over L0–63, "none of these"
escape; **not comparable** to the bench's capped digest over GRID = 11 layers and `mc.CANNOT`; the
closest pilot analogue is s3d over L20–60:4):
- stable slots (n=89): unions 0.64–0.70 vs pilot prompt-only summary 0.47, forced direct guess 0.58,
  continuation floor 0.69; single layers rarely beat 0.47; slot 0 (51/89) carries it.
- model-specific slots (stable, Qwen wrong, label ≠ NYT connection; n=25): 0.32–0.36 vs 0.08/0.12,
  continuation 0.40.

The headline subset (stable) was chosen after the pilot on these same puzzles, so the bench run on
bank v1 is a **port check**, not a confirmation. A confirmation batch is possible on the ~333 older
puzzles in the mirror (2023-06..2024-05) that no pilot step touched; out of scope for this PR,
named in §9.

## 2. Bank v1 (`evals/nyt_connections/items.json`), ids-only

### 2.1 Source
`src/wsbench/nyt.py` fetches `connections.json` from `github.com/Eyefyre/NYT-Connections-Answers`
pinned to commit `0c42b26054d4d9e2b1d8fc7b1599925a97fb1ec7` (2026-10-31, 1233 puzzles, the exact
file the pilot used), sha256 `1bd17c9161c665dbdf2ea8011123a574b7e831cc6442fc7a73fd144d0371f534`,
cached as that one file under `$WSB_CACHE/nyt/` (default `~/.cache/wsbench/nyt/`). Fetch or hash
failure raises with the URL and both hashes. `WSB_NO_NYT=1` (like `NO_NOCOT_ENV`, `readplan.py`)
makes `readplan` return no rows for the family and is part of `reads._env_key`, so an offline box
can still plan every other family. **Retained invariant (plan 0018):** text only at plan time; no
NYT text in git, in result rows, in bundles or on the site; judging needs the cached file (the
judge resolves NYT labels and re-renders plan rows for `plan_sha`), which is fetched once.

Word order: the 16 words in NYT order (`[w.strip() for g in answers for w in g.members]`) shuffled
by `random.Random(f"conn-{nyt_id}")` (the pilot's `make_puzzles.py`); `nyt.words(nyt_id)` reproduces
it. User turn: `PROMPT_MEMBERS` (verbatim from the pilot, pinned by a test) with `{words}` filled by
`str.replace`, so the rendered text is byte-identical to the pilot's `.format`.

### 2.2 Committed fields
Header: `family`, `version: 1`, `frozen`, `source` (URL, commit, sha256), `subject_model`,
`answer_format`, `stability` (16 samples, T 0.7, top-p 0.95; stable iff ≥ 12/16), `options` (rule
below), `read_positions`, `excluded` (non-partition / unlabelled answers; herring collisions; and,
recorded as a selection made on a baseline, the 30 puzzles whose pilot prompt-only summary Opus
refused), `pilot` (global-workspace commit, pilot bank sha256 7621e197…), `contract: {native_langs:
["en"]}`, `counts`.

Per item: `id` (`c<NYT number, 4 digits>`), `nyt_id`, `date`, and `mc`: one entry per slot with
`slot` (Qwen output order 0–3), `members` (**indices** into the shuffled 16), `stability`, `stable`,
`correct`, `gold_same`, `model_specific`, `overlap_with_nyt`, and `options` — an ordered list where
each option is either `{role, label}` (committed text) or `{role, nyt_group: k}` /
`{role, nyt_id: N, nyt_group: k}` (resolved at load from the fetched JSON; `nyt_id` omitted = the
slot's own puzzle). NYT categories recur across puzzles (239 pilot option labels fold-equal an NYT
name of a *different* puzzle), so references span the whole mirror.

**Label rule (fixes the leak):** the builder folds every candidate label (`mc.fold` plus quote and
whitespace folding) and compares it with the puzzle's four NYT group names:
- a label equal (folded) to ANY NYT group name in the mirror is replaced by a reference — the
  slot's own puzzle first, else the lowest `nyt_id` carrying that name — for `qwen`, `alt` and
  `foil` alike;
- an `alt` equal to the slot's `gold` is dropped (12 pilot slots offered the gold label twice);
- an `alt` that is another NYT group of the same puzzle keeps role `alt` but becomes a reference;
- `qwen` and `foil` labels are model output (Qwen's follow-up names) and are committed even when they
  quote a puzzle word (112 do; single common English words are not the puzzle);
- the builder asserts no committed string equals (after folding) any NYT group name in the
  mirror, and that every reference resolves.

This makes bank v1 differ from the pilot bank in the all-slot extras (option sets shrink where
duplicates are dropped); stable/model-specific membership is unchanged (asserted).

Builder: `scripts/build_nyt_connections_bank.py --pilot-bank <off-repo items_v1.json>`; round-trips
words, members-as-words and NYT labels through `nyt.py` and asserts equality with the pilot bank.

## 3. Read plan

`readplan._plan` branch: `ReadSpec(family, id, "chat", {"kind": "last_n", "n": 12}, GRID,
text=<rendered user turn>, note=..., lite_positions=dict(SAME))`. **Retained invariant (plan 0061):**
lite = `SAME`, so a lite run differs from full only by its `+reads-lite` stamp. `EvalSpec`
`min_full_positions=12`, `full_contiguous=True`. `tests/test_readplan.py:37` family count 30 → 31 (and its comment); the family is NOT added to
`readplan.LITE_SAME_FAMILIES` (`test_readplan.py:443` pins that set to plan 0061's five).

Readouts: the pilot's bench-producer readouts (same render, positions and tokens for all 367
puzzles; layers 0–63 include GRID) may be cut to GRID and converted **only if**
`readplan.plan("nyt_connections")` rows equal the pilot specs field by field (a one-off script,
recorded in the README): re-key `key` → `id` (strip `/prompt`; refuse any other suffix), keep
absolute `pos`, and write a sidecar with scalars `sampling: "bullet4"`, `reader`, `layers` and
`plan_sha = reads.plan_sha("nyt_connections")` (the pilot meta holds lists and an empty plan_sha;
`readouts.load_readouts` reads `row["id"]`, `readouts.py:100`); otherwise re-produce
`final-olens-rl600-x4` at GRID (~6 GPU-h).

## 4. Scoring (summary mode, the bench default; chain_intermediates pattern)

**Retained invariants (plan 0024, digest audit F1, v1.1.0 #233):** summary mode never changes the
denominator; the family stamps `config.aggregate="summary"`; `summ_numbers=0` (so the layered
default applies; a numbers digest keeps the v1.0 non-per-layer path instead); the headline all-layer config runs
`summ_layers=layered` (per-layer digests stored in `summ_store` and reused by every single-layer
config, then one stage-2 summary per puzzle, `layered-v1`, `summ_layered_x` default 2), while every
single-layer run keeps `union` (byte-identical to v1.0); the family does NOT pin a layer mode
itself; an unsummarized puzzle makes all its slots undecided (`pass=None`). The quote gate (step 2)
uses `col.evidence[puzzle_id]` as `collapse` returns it in the active mode (for `layered`, the
stage-2 digest's grounded lines; the implementer verifies `quote_ok` against it in a test). `opts=aggregate=native` runs a **native diagnostic path** (not added to `NATIVE_ONLY`, which stays
jlens_concept_pr only; no summary-only mechanism is introduced, so `tests/test_layers_arbitrary.py`
and `tests/test_summary_mode_compare.py`, which run every family with a toy file in both modes, need
no edit): per stable slot, the same MC prompt with the item's raw readout lines (every read cell,
`[L<layer> pos <i>]` headers like the digest bundle) as the evidence instead of a digest, one call
per slot, quote-gated on `digest.native_lines(cells)` (the `quote_ok` contract, `digest.py:1028-1033`);
its own prompt (`NATIVE_MC`, asking for a quote "from the readouts") in `PROMPTS` and verbatim in the
README; rows (incl. redaction) and denominators as in summary mode. It is a diagnostic, never the
headline (the README says so). **Version pinning** (`scripts/summary_mode_compare.py:647-668`,
`tests/test_summary_mode_compare.py:334-345`): the native path stamps `prompt_version =
spec.judge.prompt_version` and the summary path `digest.prompt_version(spec.judge.prompt_version,
args, NAME)`; both use the same judge model, reasoning and `SAME_KEYS` config, exactly one row per
`cNNNN|sK`, no `excluded_from_rate` on headline rows (no `BASE_PAIRS` entry needed).

1. `digest.collapse` per puzzle. `EvalSpec.task_note = DIGEST_TASK_NOTE` (no gold, non-empty):
   the model is reading a 16-word grouping puzzle and has not answered yet; note the groupings and
   connections the readouts state.
2. Per stable slot, one MC call (`mcjudge.Call`): digest + the slot's labels shuffled by
   `mc.seeded_shuffle(f"{id}-{slot}")` + `mc.CANNOT` last (`mc.options_with_cannot`). The model
   must also return a `quote` from the digest supporting its pick; a pick whose quote fails
   `digest.quote_ok(quote, col.evidence[puzzle_id])` (`digest.py:1027`; `Line` objects, as chain does
   at `chain_intermediates/judge.py:864,878-880`) is scored as cannot-tell. The gate is verbatim-only
   (it does not check that the quoted line relates to the picked label; the prompt-only floor runs
   the same gate, and the README says so). Prompts tool-free
   (`mc.READOUT_PHRASE`), verbatim in the family README.
3. Partner null (chain's `null_partner` pattern, `chain_intermediates/judge.py:751-767`): the same MC
   on the digest of a seeded partner puzzle (`mc.seed_int(f"{NULL_SEED}|{id}|{slot}")` over the
   candidates restricted to puzzles SUMMARIZED in this run, so the partner has `col.evidence`;
   partner choice therefore depends on which digests were served, and under `items=` (e.g. the 3-id
   smoke) the pool is that subset, so a slot may have no partner — both said in the README) whose folded
   labels (its Qwen labels and NYT names) are disjoint from the slot's
   resolved options; no null for the slot if none qualifies; the quote gate uses the PARTNER's
   `col.evidence`. Extra `null_rate`.
4. **Continuation floor (measured, extra):** the same MC prompt with the slot's 4 member words (from
   `nyt.py`) as the only evidence, no readouts, **no quote gate** (there is no digest; the `quote`
   field is ignored); extra `continuation_rate`. Reported, not gating (§0).
5. **Word-masked ablation (extra):** the digest with every puzzle word blanked (case-insensitive,
   word-bounded), same MC; the quote gate checks against `col.evidence` lines blanked IDENTICALLY
   (`Line` is frozen, `digest.py:712`: blank with `dataclasses.replace` over both `text` and
   `pieces`), so a quote spanning a blank is not failed spuriously; extra `masked_rate` (pilot audit must-fix 2).
6. Rows (each slot row carries its puzzle's `col.row(puzzle)` fields, as chain's
   `row.update(col.row(i))`, `chain_intermediates/judge.py:938`, before redaction, so the frozen
   floor's `digest_unserved` and the refusal share are right): **headline rows = stable slots only;
   non-stable slots write NO result rows** (their picks go
   only into the extras: `pass_rate_result` sets `n_items = len(rows)`, `family.py:157`, and
   `results.decided_outcomes` needs one row per id, `results.py:217-219`), one row per slot with `id = "cNNNN|sK"` (the puzzle
   id in a separate `puzzle` field; the same ids as the lucky `Item`s, §5), `pass` True/False/`None`
   when undecided, so `results.decided_outcomes` (one row per id, `results.py:201-221`), the frozen
   floor's `decided` map and `shared_floor_text` all join per slot, and the 20% undecided rule
   (`results.py:178-197`) sees only them. `pass_rate_result(rows, n_items=<number of stable
   slots>)`; `n_empty` / `n_unjudged` are counted **per stable slot** (every stable slot of an
   empty or unsummarized puzzle counts), so numerator and `n_items` share a unit for the 5% rule
   (`results.py:143`); `n_expected` / `n_missing` stay cell-level over the headline puzzles;
   all-slot completeness goes in the extras. **Refusal accounting in the headline unit**
   (`runner.refusals_only`, `runner.py:191-208`, requires `n_unjudged_cells == n_digest_refused +
   n_digest_too_long + n_items_partial_undecided` and `extras.n_items_undecided >= refused`): the
   family overwrites those three `extras.summary` counts with the number of **stable slots of
   headline puzzles**, derived from `col.reasons[puzzle]` over headline puzzles: `refused` →
   `n_digest_refused`, `too_long` → `n_digest_too_long`, `partial_refused` →
   `n_items_partial_undecided`; a `layered_failed` puzzle's stable slots count in
   `n_unjudged_cells` and as undecided but in NONE of the three refusal keys, so the run stays
   incomplete exactly as for every other family (bench semantics, `runner.py:198-214`; never sum
   `diag["n_layered_failed"]`, which also counts refused/too-long stage 2s,
   `tests/test_layered_digest.py:371`). Making `layered_failed` count as a refusal would be a bench-
   level change to `runner.refusals_only`, out of scope. `extras.summary.count_units` is overwritten
   to "stable slots". Test: one stage-2-refused headline puzzle (refusals-only complete) and one
   `layered_failed` headline puzzle (incomplete), modelled on `test_layered_digest.py:184-197,362-372`; and keeps the puzzle-level and
   all-puzzle counts under separate keys (`n_puzzles_digest_refused`, …). A test: one refused
   headline puzzle with 2 stable slots plus one refused non-headline puzzle → the run is
   refusals-only complete. `extras.n_items_without_readouts` likewise counts stable slots. Extras (`_columns`): all slots, model-specific, slot 0
   vs slots 1–3 (each with its n), null, continuation, masked, cannot-tell rate, picks by role.
7. Result rows record picks **by role and slot**, never label text; digests and quotes are
   redacted from rows unless `opts=keep_nyt_text` (copy knowledge_cutoff's `_redact` /
   `REDACTED` / `keep_*_text`, `knowledge_cutoff/judge.py:68-70,422-447`), and
   `scripts/check_nocot_redaction.py` (or a sibling) checks bundles/site for this family.

## 5. Floors and gates

- **Prompt-only:** `po-opus-v1` unchanged (the generic open-model question; no per-family hook
  exists, `text_inversion.py:34-49`, and `tests/test_po_floors_r3.py:234-239` pins the protocol). It
  is not the pilot's Qwen-aware prompt summary (0.47); the README says so. It must be frozen before merge
  (test coverage of `poo.families()`): freeze to a temporary `dst` and merge ONLY the
  `nyt_connections` entry into the committed `evals/baselines/prompt_only_summary.json`, leaving its
  `_source` byte-identical (the stock `wsbench freeze` rebuilds `_source` and breaks
  `tests/test_po_floors_r3.py:253`, `prompt_only.py:237-265`); the entry's protocol must be
  `po-opus-v1`. If any nyt id is refused (Sonnet fallback), stop and ask Camila; never edit that test.
  Any `FAMILY_DEFAULTS` summarizer change (§9) lands BEFORE this freeze (`summary_floor_matches`
  keys on the summarizer settings).
- **Direct guess (the stronger text floor, pilot 0.58):** the lucky-guessing `question` variant
  (`GUESS_QUESTION` hook, `lucky_guessing.py:358`) with an nyt-specific system prompt via a new
  `SYSTEM_QUESTION_BY_FAMILY` dict beside `GUESS_QUESTION`, defaulting to `SYSTEM_QUESTION`
  (`run_family` hardcodes it today, `:1390-1401`; moral_rationale's fingerprints and floors stay
  unchanged), plus the `DESCRIPTIONS` entry (`test_lucky_guessing.py:30`). **Sanctioned edit to a pre-existing
  test:** `tests/test_lucky_guessing.py:445` becomes `set(lg.GUESS_QUESTION) == {"moral_rationale",
  "nyt_connections"}` (the rest of that test unchanged); `SYSTEM_QUESTION` itself is NOT changed
  (`:437` pins "answered with one word" in it): sees the 16 words (rendered at run time) + the
  slot's labels, picks Qwen's. One `Item` per stable slot (id `cNNNN|sK`), since `score_draw`
  passes an item only if every list is right. Plus the default blind/options-only variants; an
  options-only guesser > 5 points above uniform is reported in the README, not hidden.
- The lucky floors (`blind` = options-only, `described`, `topic` — the `LEAKAGE_GUESSERS` — and
  `question` = the direct guess) are frozen into
  `evals/baselines/lucky_guessing.json` (the per-item lucky cell beside summary rows needs them).
- `tests/test_mc_cannot_tell.py`: a `_last_option` branch for the family; `DESCRIPTIONS` entry; the
  round4/round5 fixtures that import every builder's SPEC get the family.
- `capable/questions.py`: `NO_QUESTION` (the gate is Qwen's own behaviour).
- `text_inversion.NOT_GATED` + the `_not_gated` reason in `anti_text_inversion.json`.

**Floor pairing under v1.1.0.** The headline row is `layered` (instrument
`<PV>+digest-v5-task-extractive-layered-v1+sj-v10`); the prompt-only floor is one prose cell, so it
is necessarily a single-layer (`union`) instrument, and `prompt_only.summary_floor_matches`
(stamps differ) never draws it beside the layered row automatically — true of every family's
all-layer row since #233. The bar is therefore computed by a family script,
`scripts/nyt_connections_bar.py <headline results dir>`, which reads the floor from the FROZEN
entry `evals/baselines/prompt_only_summary.json["nyt_connections"]` (its per-slot `decided` map and
`digest_unserved`), and REFUSES to compute unless the instruments match: the headline
`prompt_version` with the reads tag stripped (`_strip_reads`) and `-layered-v1[x<k>]` removed equals
the entry's `instrument`; `judge_model` matches; and `_floor_match_key` applied to BOTH summarizer keys
(`summarizer_key(headline config)` and the entry's `summarizer`, so the fallback-model and `lang`
normalization of `summary_floor_matches` applies to both), each with `layer_mode`/`layered` removed,
are equal. It also refuses an entry that is `not_measurable`, whose protocol is not `po-opus-v1`, or
whose `decided` map is empty (`decided_outcomes` returns `{}` on an id/`n_items` mismatch,
`results.py:201-221`) — never "0 paired". It
pairs only slots decided on both sides (joined on `cNNNN|sK`), reports n paired and the paired
difference with its bootstrap CI; its output is recorded in the family README. A small test: one
matching pair computes; one mismatched instrument is refused.

**Bar (pre-declared, §0):** headline pass rate (all-layer `layered`, `final-olens-rl600-x4`) vs the
frozen prompt-only floor, with a bootstrap 95% CI on the per-slot difference (headline − floor,
floor per slot from the frozen prompt-only cells) excluding 0; reported, not gating: exact
McNemar vs the direct guess. Not met → `not_in_macro` with the reason; registered either way.

## 6. Tests (all offline)

Autouse `tests/conftest.py` stub `_offline_nyt` (like `_offline_nocot`, `conftest.py:30-41`) giving
synthetic words and NYT group names for **every `nyt_id` the bank references** (bank items, every
cross-puzzle option reference, and the null-partner pool), names unique per (nyt_id, group) and
never equal to a committed label (`test_lucky_guessing.py:34-35` checks option uniqueness), so `test_readplan` (plans every family), the
`test_summary_default` dry run, the lucky builders and `test_mc_cannot_tell` never touch the network.
`tests/test_nyt_connections.py`: `nyt.py` fetch / sha check / shuffle / render through the real module
on a small fixture `connections.json` (like `tests/test_knowledge_cutoff_nocot.py`'s fixture zip);
the exact PROMPT_MEMBERS pin and `", ".join(words)` fill; label resolution incl. cross-puzzle
references; row ids / denominators; redaction; the quote gate; the null-partner disjointness;
the native diagnostic path (one row per stable slot; the family stamps `config.aggregate = "native"`
explicitly, since `mcjudge.base_config` never sets it and `runner` stamps it only for `NATIVE_ONLY`;
the MC answer field is named `choice` and the Call meta carries `gold_pos`, so
`tests/test_summary_mode_compare.py`'s fake-LLM oracle yields real passes; same `n_items`
and denominators as summary mode, `prompt_version` pinning as in §4), the refusals-only
completeness case (§4.6) (monkeypatch `run_calls`). The real no-NYT-text check over the committed
bank runs in the builder and in a test that is SKIPPED unless the cached pinned mirror exists
(stated in the test). Importing `wsbench.evals.nyt_connections` neither fetches nor reads the bank (lazy, inside `run`/
plan; `tests/test_agentic_twins.py:1138-1150` imports every family with no stub). `readplan` and the
judge call `nyt.puzzles()` through the module attribute
so the `_offline_nyt` monkeypatch reaches them; `nyt.py` uses `registry.bank_path` (no
`"items.json"` literal, `test_bank_versions.py::test_no_hardcoded_items_json`).
`examples/readouts/nyt_connections.jsonl`: synthetic puzzle words only, and at least one puzzle with
a stable slot (`tests/test_summary_mode_compare.py:316-317` requires every hooked family to decide
≥1 item in both modes). README *Example:* line: a
synthetic puzzle.

## 7. Validation (before merge)

1. Readouts per §3. 2. `wsbench judge family=nyt_connections items=<3 ids with stable slots>` live
smoke; read the digests and picks. 3. Full judge (all GRID layers, `layered`) + single layers L44 and L52; prompt-only
floor; direct guess; continuation, masked and null extras. 4. Record numbers in the family README
beside the pilot's, with the port-check caveat (§1). `wsbench list` shows 335 items; the README
states the headline n (89 stable slots over the puzzles that have them).

## 8. Files

New: `src/wsbench/nyt.py`; `scripts/nyt_connections_bar.py`; `src/wsbench/evals/nyt_connections/{__init__,prompts,judge}.py`;
`evals/nyt_connections/{items.json,README.md}`; `scripts/build_nyt_connections_bank.py`;
`examples/readouts/nyt_connections.jsonl`; `tests/test_nyt_connections.py`. Edited: `readplan.py`,
`reads.py` (`_env_key`), `tests/conftest.py`, `tests/test_readplan.py`,
`tests/test_mc_cannot_tell.py` (+ round4/5 fixtures as needed), `capable/questions.py`,
`baselines/{text_inversion,lucky_guessing}.py`, `evals/baselines/anti_text_inversion.json`,
`evals/baselines/prompt_only_summary.json` (frozen floor, nyt entry only), `scripts/check_nocot_redaction.py`
(or sibling), `atlas/export_cb.py` (repo root; `WSB_NO_NYT` beside `WSB_NO_NOCOT`), `README.md` (entry, Judges row, Credits), `NOTICE.md`, `plans/README.md`, `CLAUDE.md`.
CI: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`.

## 9. Risks and follow-ups

- The capped bench digest may drop groupings: ≤10 + ≤15 claims per layer digest, and under `layered`
  one stage-2 digest per puzzle of ≤20 prominent + ≤30 rare entries across all layers. The smoke
  checks it; remedies are a `FAMILY_DEFAULTS` `summ_max`/`summ_rare` entry or `summ_layered_x`
  (stamped `-layered-v1x<k>`), recorded in the README and decided BEFORE the floors are frozen.
- Small n (89 stable, 25 model-specific): wide CIs, said in the README.
- Shared idiolect: Qwen writes the labels and the lens shares Qwen's wording; the quote gate and the
  continuation/masked extras bound it but do not remove it.
- Follow-up (not this PR): bank v2 confirmation batch on the ~333 untouched older puzzles.
