# workspace-bench — agent runbook

`wsbench` is a growing set of evals of whether an activation-reading lens (prose "O-lens" samples or
top-k "J-lens" tokens) surfaces what a model computes but never writes. Every family plugs
into the shared package in `src/wsbench/` (client, judge config, cache, readout contract,
results schema, registry, runner, CLI, `readplan` = the producer-facing read plan, `capable/` =
the porting gate, `produce/` = the optional HF-transformers producer behind the `gpu` extra).
`plans/` is the 2026-09-15..17 design history of the nine-family restructure, not a current
pointer (`plans/README.md`). Public docs: `README.md`, `NOTICE.md`, `CITATION.cff`.

## Readout contract (input to every family)
Stated once, in README §Quickstart (the contract block) and `docs/producing_readouts.md`; do not
restate it here. Code facts only: `load_readouts` counts malformed lines (never fatal), keeps the
first duplicate `(id, layer, pos)`, counts empty readouts (a result, not a missing cell).
`wsbench convert-gen-dir gen_dir=GEN out=F.jsonl kind=prose|tokens` converts the in-house
`<gen_dir>/<label>/L###.jsonl` layout (id = directory name, layer = filename).

## Judge layer (`llm.py`, `judge_config.py`)
- Default judge `claude-opus-5-5` (Anthropic; plan 0023, Camila 2026-10-29; Gemini 3.8 Flash via
  OpenRouter before). Pins: agentic_misalignment + jailbreak_recognition -> `claude-sonnet-5` (jailbreak: kept by
  the plan 0037 J8.5 smoke, `evals/jailbreak_recognition/judge_smoke_v2.json`),
  introspection -> `claude-opus-5-5` at default effort (reasons: README §Judges and the family
  READMEs). jlens runs all three stages on the default judge. Opus 5.5 cannot disable thinking:
  `llm.always_thinks` models get low effort unless a family sets `anthropic_effort`. Tests script
  OpenRouter-shaped fakes; `tests/conftest.py` routes them through the OpenRouter path.
- Override precedence and what `pinned_instrument` means: README §Judges (the bullets under
  the table); not restated here.
- Routes by model id: `claude-*` -> Anthropic SDK (`ANTHROPIC_API_KEY`, or with no key and
  `ANTHROPIC_PROFILE` set, the SDK's `ant auth login` profile; structured output,
  refusal -> `None`); else OpenRouter via the OpenAI SDK (`OPENROUTER_API_KEY`, `sk-or-…`).
  Shared: JSON-schema output, 11 jittered retries (`_ATTEMPTS = 12`) on 408/409/429/5xx/
  timeouts, process-wide thread-safe RPM pacer (`rpm=`, default 240), `preflight` fail-fast,
  `Spend` tally. Structured Anthropic calls run at `effort: low` on always-thinking models unless
  the family sets `reasoning={"anthropic_effort": "default"|<level>}` (introspection: its
  source instrument ran at default effort; knowledge_cutoff sets OpenRouter `{"effort": "low"}`); `resolve` keeps only the reasoning keys
  of the route the judge resolves to (`anthropic_effort` on Anthropic, every other key on
  OpenRouter; plan 0023), so an Opus judge of knowledge_cutoff gets `None`, not `effort: low`. A failed
  call returns `None` and never scores. `stream_json_async` is the primitive, `stream_json`
  wraps it (`temperature` dropped on the Anthropic route); `stream_text[_async]` is agentic's
  free-text Anthropic-only primitive. Both take `refusal_model=`: a call the model declines is
  re-run once, same request, on that model (client-side, for models that reject the server-side
  `fallbacks` parameter); a served JSON result carries `llm.SERVED_BY`, a served text fires
  `on_served`, and only refusals move (a `max_tokens` stop or an error stays the primary's
  outcome). `mcjudge.run_calls(refusal_model=)` passes it through and caches the serving model
  with the row, under the judge's fingerprint: a later run with another refusal model (or none)
  reuses that row (no stale-fallback check, unlike the digest). The digest's equivalent is `summ_fallback=none+<model>`, and
  `digest.OUTPUT_CAPS` gives a digest model its own per-call output cap (`Settings.max_tokens`).

## Family conventions
- `wsbench/family.py` holds the helpers the newer families share: `require_cells` (missing
  cells exit 2 unless `allow_missing=True`; a dry run only reports), `cell_text` (a token bag is
  judged scored but verified against bare tokens), `last_pos_rows`, `quote_in` (verbatim after
  `mc.fold`), `tri_state` (pass / fail / undecided), `rate` / `mean`, `pass_rate_result` (the
  pass-rate `FamilyResult` epilogue: decided-only value, bootstrap CI, completeness, counts).
  A pass-rate family's `run()` is: load bank -> `item_scope` -> `load_readouts` -> select cells ->
  `cell_text` -> `Call`s -> `run_calls` -> per-cell verdicts -> per-item rows -> `pass_rate_result`
  -> `with_readout_count`. `chain_intermediates/judge.py` is a complete example (native free recall plus, since plan 0038, a per-slot MC summary path and an item-level permutation null).
- `mcjudge.py`: `Call` + `run_calls` (one schema per batch, fingerprint `(prompt_version, model,
  reasoning, temperature, system, user)`, cache `{result, meta}` in `<out>/cells.jsonl`,
  `validate` re-queues an invalid answer); `Preflighter` (one preflight per model per process);
  `item_scope` = bank ∩ `items=` then `limit=`; `base_config` / `base_counts`. `mc.py`: seeds,
  shuffles, `fold`, `letter_index` (a lone letter or a letter with its own option text).
  `summarizer.py` (the J-lens bag -> prose step) is deleted (plan 0032): native token paths judge
  `family.render_bag(tokens)` (no scores); summary mode digests every method the same way.
- `reads.py` (plan 0032) is THE loader every family calls (`reads.load(args, family, ids=,
  positions=)`, never `load_readouts` directly; `test_no_family_calls_load_readouts_directly`):
  sidecar `<file>.meta.json` (declared sampling `bullet4|prose1|tokens10`), the `reads=lite`
  selection (`ReadSpec.lite_positions` / `lite_layers`), the `reads=full` span check
  (`EvalSpec.min_full_positions` / `full_contiguous`), the plan-layer and `plan_sha` guards (with a
  sidecar; sidecar-less files are report-only). `base_config` / `runner.finalize_reads` stamp
  `config.reads/sampling/sampling_source/reader/reads_checked/layers_judged` (+`lite_rule`).
  `mc.options_with_cannot` builds every MC list (cannot-tell last); `mc.token_note(flat_types,
  multi_select=)` is THE token-list rule (Q4); `digest.quote_ok` THE quote verifier
  (`statement_lines` for relational content, `number_flood`); `wsbench.numerals` reads numerals in
  any language.
- Shared judges: `basic/` (the bank judge, `bank_family(name, title, sources=, not_in_macro=)`;
  `MC_FAMILIES` dispatch to a blind forced-choice judge instead, over options frozen in the bank
  (`item["mc"]`), cannot-tell last. Two modules, written in parallel by the two family PRs and
  kept side by side (unifying them is a follow-up): basic_readout (plan 0053) on
  `basic/mcjudge_basic.py` (quote gate: `quote_ok` or `nearquote.close_lines`, the option named
  by the quote or, cut mid-name, where its line continues it or its sample ends inside the
  name, `form_via`; number-flood void, bare-mention ruling, the asked-sum void
  `other_sum`; options seeded and calls keyed by `OPTIONS_VERSIONS`, not the result stamp;
  its prompts are `SYSTEM_MC` / `USER_MC` / `BR_CANNOT` in `basic/prompts.py`, kept OUT of the
  shared `PROMPTS` so they never stale the other basic families' stamp), and multihop (plan 0048,
  `MC_BANK_FAMILIES`) on `basic/mcjudge_bank.py` (gates: the quote verifies, verbatim or
  near-verbatim, and names the gold in itself (or, cut mid-name, where its line continues it or its
  sample ends inside the name) by name, alias or a derived form from the frozen `evals/multihop/derived_forms.json` (`gold_forms`), names no other option, and
  is no number flood; no split rule; the gate version `GATE_VERSION` joins the result stamp while
  the calls keep `CALL_VERSIONS`; strings in the family's `prompts.MC`); per-family strings `FAMILY_RULES` (typo) are added to that family's own `PROMPTS` (`FORBIDDEN_TEMPLATE` / `FORBIDDEN_FAMILIES` is empty since plan 0058 removed medical_diagnosis{,_alt}; the mechanism stays); `FAMILY_PROMPT_VERSIONS` / `prompt_version_of` give a newer family its own stamp so adding a rule never stales the older families' `bank-2026-10-10` ATI entries and floors; `DIGEST_TASK_NOTES_TEXT` is in every basic family's PROMPTS, so a new note line must be added to every basic README) and `multitoken/`
  (`mt_family(name, title, calls_per_arm=, scorer=)`): basic_readout_mt (plan 0051) is
  `scorer="mc"`: the MC judge of record (`multitoken.prompts.mc_system` / `BRMT_SYSTEM`, options
  `mc.options_with_cannot`) plus the deterministic name gate (code verifies the pick and never
  overrules it; `rival_quote` is reported only), since audit fix F4
  `multitoken.family.tolerant_gate` (quote verified by `digest.quote_ok` or near-verbatim via
  `nearquote.close_lines`; the gold named by the quote, a near quote's matched block, or, for a
  quote cut mid-name, where its own line continues it or its sample ends inside the name (no
  rescue through any other line), with
  case endings / Arabic clitics / Hangul particles / fuzzy spellings and the frozen
  `evals/basic_readout_mt/exonyms.json`; `name_gate` itself is the old strict rule), headline = the `readout`
  unit only (`BRMT_HEADLINE_UNITS`; `McFamily` in `MC_FAMILIES` holds a family's MC config, the
  default is the regex families' diagnostic unchanged), bank v2 `items_v2.json` built by
  `scripts/build_brmt_v2.py` (gate record `gate_v2.json`; README prompt blocks by
  `scripts/brmt_readme.py`); `opts=judge=regex` is its unpinned diagnostic. For the other mt
  families the scorer of record is the deterministic regex
  contract `multitoken/regex.py` (a port of the source repo's `bank/matching.py` +
  `contract.py` + `conjunctive.py`; no call, `spend_usd` 0, `EvalSpec.scorer="regex"`, pinned by
  goldens `tests/golden/mt_regex_*.json` made by the source code); the forced-choice judge is
  `opts=judge=mc` (never pinned). Token bags are matched as raw tokens natively (each token one
  sample; the `summarizer.summarize` step and `SUMMARIZED_SCORER_VERSION` are deleted, plan 0032
  §2.3); under summary mode the contract runs on the digest's evidence samples and `judge_model`
  = the digest model. Their
  families are three-line packages under `evals/`. Option
  lists are pinned by goldens in `tests/golden/`. A spec with `scorer` set is not preflighted by
  `run` unless `opts=judge=mc`, and `wsbench list` shows the scorer in the judge column.
- The four multilingual families (plan 0054) judge `items_v2.json` banks built offline by
  `scripts/build_multilingual_v2.py` (curation in `scripts/multilingual_v2_curation.py`; run it
  with `--check` after any edit, a test enforces it): language units hold NAMES only
  (`multitoken/languages.py`, "Polish" case-sensitive), every unit required, items carry
  `mc_roles` + `mc.language`. multilingual / multilingual_multihop score `mc+regex`
  (`multitoken/mcrx.py`: a blind MC content role, credited only with a `quote_ok` quote whose
  line holds a native-language form — or, since audit fix F4, any line that singles out the gold
  does — AND the content regex units AND the language leg). The language is never an MC role:
  `regex.language_leg` scores it once per item on the RAW samples of every read cell (credited by
  >= 1 naming sample; `rows[].language_naming_samples` is the count); the language pins stay in
  the multilingual_multihop digest only so the content judge's input is unchanged. A v2 language
  unit is SCORED on `languages.naming_forms` (F6: naming contexts only, never a bare adjective /
  demonym; `re:` forms are regexes, `regex.unicode_word_matcher`), swapped in by
  `regex.scored_units` for items
  with `mc_roles` (the bank file stays frozen; `--check` still holds); multilingual's options show
  their accepted forms (`options.display_options`, F5); multilingual_mt /
  multilingual_typo stay regex with the `+v2+ln-…` tag (their language unit is scored by the same
  leg, `family.item_language_leg`, `+langleg-v1`), which `_spec_pv` stamps only while the v2 bank
  is the one judged (a `WSB_BANK_FILE_*` pin to `items.json` scores and stamps exactly as v1, as
  `test_mt_regex.py` / `test_multitoken_family.py` / `test_summary_mode_multitoken.py` do). The
  ATI gate field of the four is `content_hit`; `text_inversion.ATI_EXCLUDE` freezes the
  hand-audited obvious ids, and <= `MIN_ATI_ITEMS` survivors means no ATI number.
- Baselines (`baselines/`): `lucky_guessing` (option lists from the judges' own builders, blind /
  described / uniform, plus round 4's `topic` guesser, the MC leakage standard's: it reads a
  frozen topic file `evals/baselines/topics/<family>.json` where one exists (main's families:
  `lists` / `item` forms), else each item's builder topic `meta["topic"]` for
  `TOPIC_FAMILIES` (association, basic_readout, multihop, poetry, directed_modulation;
  `topic_source` picks; keep both paths). Bank v3 of basic_readout / multihop / association /
  poetry was rebuilt for it by `scripts/mc_leakage_r4.py`, evals/baselines/README.md; a rebuilt
  list never drops an observed confuser, a distractor a cached judge picked or the readouts name
  as a rival, which is why poetry is on bank v5 and basic_readout on its successor v7, `mc_leakage_r4.py
  observe`; v5 also keeps every v2 option the digest of a v2 non-pass cell names (poetry: as a
  line ending), reviews r6 / r7; basic_readout v5 fixes each gold's slot, `mc.gold_position`,
  balanced per subfamily by `mc_leakage_r4.py balance`, so no positional prior beats chance)
  and `prompt_only`; `wsbench freeze` stamps entries with the family's
  `prompt_version`, and `report` shows a floor only while the stamp matches. Prompt-only ids
  Opus 5.5 refuses are re-asked on Sonnet 5.5 (`po-opus-v1+sonnet55-fallback`, 2026-11-01); the
  committed floors carry the frozen Sonnet 5 protocol (`po.PO_FALLBACK_SONNET5`), still read and
  labelled (`po.PO_FALLBACKS`), never written; `prompt_only_opus.fallback_rows` ignores answers
  of any other fallback model in a resumed dir. A summary floor matches a row regardless of the
  digest's client-side refusal model (`po._floor_match_key` keeps only the fallback mode), so the
  Sonnet 5 floors still draw beside Sonnet 5.5 rows.
  `text_inversion` builds the anti-text-inversion subset (`evals/baselines/anti_text_inversion.json`,
  plan 0019 panel gate, which replaced plan 0014's Opus-only gate): Qwen3.6-27B + the frontier
  group (Claude slot opus/sonnet, `openai/gpt-6-astra`, `google/gemini-4-argon`) x 3 draws, each
  judged by the family's scorer; ATI iff Qwen failed OR every frontier reader failed
  (`panel_verdict`). Layout: `answers/<answerer>/draw{d}`, `readouts/<answerer>/draw{d}`,
  `judged/<answerer>/draw{d}`; the flat plan-0014 layout is still gated by the old rule
  (`_gate_legacy`). `anti_text_inversion=True` sets each family's `items` to it with
  `JudgeArgs.scope`, which `is_subset` ignores; ungated / empty families are skipped
  (`NotInScope`, exit 0), a stale (instrument or, on panel entries, `bank_sha`) or missing entry
  fails (exit 2). API `reasoning_extraction` refusals are recorded once and never retried or
  reworded; `claude_slot.json` (`stage=slots`) moves a family Opus refuses on > 20% of items to
  Sonnet. A crafted family (`CRAFTED`) that would go ungated is a stop-and-report (SystemExit).
  chain_intermediates is gated on `any_of_3` and knowledge_cutoff on `ati_pass`
  (`STRICTER_PASS_FIELD`); directed_modulation / moral_rationale / jailbreak / user_modeling /
  conjunctive have their own item adapters (rowless items count as fails in `ROWLESS_IS_FAIL`
  families' denominators). Gotchas: **OpenRouter (astra, argon) is only ever called from Modal**
  (`scripts/ati_openrouter_modal.py`, secret `openrouter`), never from a dev box; astra also has
  a direct OpenAI route, `--route openai-wif` (workload identity federation, Modal secret
  `openai-wif`, `wsbench.baselines.ati_remote`; same request; rows record `route`), and argon a
  direct Gemini route, `--route gemini-wif` (Google WIF on Vertex, no secret, ONLY under
  `modal run -e camila-blank`; `max_output_tokens` = the same 16000 ceiling); Qwen requests
  are token ids built by `qwen_prompt_ids` (`</think>` is an added token with `special: false`,
  so `split_special_tokens` alone does not keep it plain text). `WSB_BANK_FILE_<FAMILY>`
  (`registry.bank_path`) points one family at another bank file (refill candidates, fixtures).
- Per-set judge resources (plan 0060 A2): under `WSB_BANK_ROOT=adapted/<m>` a resource the judge
  looks up by registered id / value reads `registry.load_resource(family, file, keys)`: the
  registered `evals/<family>/<file>` with `adapted/<m>/<family>/<file>` entries ADDED (a differing
  registered key exits; registered ids always read registered entries; no root = byte-identical).
  `registry.adapted_only(family, id)` gates the loud "no per-set entry" errors. role_bound's
  lexicons are read bank-wide, so its overlay is SCOPED to adapted pair ids (`gate.lexicon_for`);
  user_modeling's adapted golds read `adapted/<m>/user_modeling/values.json`, never a pool
  extension. Judge an adapted bank via `WSB_BANK_ROOT` only, never `WSB_BANK_FILE_<FAMILY>`:
  the overlays and the loud missing-entry errors key on the root. Tests:
  `tests/test_adapt_judge_overlays.py`.
- jailbreak_recognition (plan 0037): bank `items_v2.json` = 86 positives + 86 gated controls
  (`kind`, `control_type twin|roleplay`); headline = recall − control FPR (can be negative, in
  the macro); a file with only one kind's readouts scores `value=None` (a cached v1 arm, or HB's
  controls-only `hb_only` bank). Rebuild: `scripts/build_jailbreak_v2.py` (stages; Qwen gate on
  Modal). Summary mode: the digest runs on the judge pin `claude-sonnet-5`
  (`JudgeConfig.aux_models["digest"]`), and a digest or judge call Sonnet declines re-runs once
  on `claude-opus-5` (`summ_fallback=none+claude-opus-5`; judge draws via
  `run_calls(refusal_model=)`); a digest both decline is UNDECIDED (state `undecided`, out of
  both denominators; any other unserved control still scores as FLAGGED); rows record
  `digest_model` / `judge_model` / `judge_served_by`; `judge.summary_pinned` replaces
  `digest.pinned` (which wants the repo-default digest model). The summary judge asks ONE
  question per item (`ITEM_SYSTEM` carries the family's `RECOGNITION_RULES` verbatim,
  `ITEM_USER`; calls keyed `jb-item-q2`, keys `<item key>#d1..#d3`) in `N_DRAWS = 3` draws,
  majority of all draws (`judge.draw_majority`; a failed draw counts in the half), a yes
  counting only with a quote `judge.verify_quote` passes; summary rows carry `answers` / `draws`,
  not per-line labels. No kind guards (`+guard-off`): only the quote checks verify a
  recognition. Native runs and the ATI gate keep `NATIVE_PROMPT_VERSION`
  (`jb-v4+pins-r1+pins-r3+guard-off`); the summary stamp adds `+sonnet-digest+item-q2+opus5-fb+test-pins`.
  The gate grader falls back to Sonnet 5, recorded per label (historical: it built the frozen
  v2 bank). Gotcha (the `summ_fallback=default+claude-sonnet-5-5` families,
  `digest.REFUSAL_MODEL`): the digest fingerprint does not key the fallback, so
  `digest._stale_fallback` makes a cached row another client-side refusal model served (incl. a
  pre-switch Sonnet 5 row: `SERVED_BY` in `RETIRED_REFUSAL_MODELS`, no `SERVED_VIA`) a cache
  miss; never drop the `SERVED_VIA` tag when caching a fallback-served digest. The judge pins
  (agentic, jailbreak) stay `claude-sonnet-5`.
- Introspection on the big MoE subjects (plan 0067): `adapt/introspection_ops.py` records
  `introspection.measure` as ops (vector ids by call order), executes them batched / sharded on a
  `Stack` (`TorchStack`, `apply_steer` = `Backend.steered`'s math), replays; the GPU side is
  `scripts/adapt_introspection_mp_modal.py` (calib gate `g0_pass` before any run; parts on the
  `wsb-introspection-mp` volume). A non-plain residual (`spec.residual`) is refused by `Producer`.
- Per-family read regimes, pass rules and floors are documented in each `evals/<family>/README.md`
  (the source of truth); do not restate them here. Twelve families keep their own `judge.py`
  (+ `score.py`): Camila's originals (agentic, jailbreak, jlens_concept_pr, moral, relational,
  role-bound, conjunctive, user_modeling; hallucination left for HallucinationBench, plan 0040),
  directed_modulation, hinted_cutoff, knowledge_cutoff and wrong_intermediate (plan 0050: a blind 6-way MC over B',
  the true bridge B and four same-category distractors frozen in bank v2 by
  `scripts/wrong_intermediate_mc_options.py`; a gold pick is credited only with a verified or
  near-verbatim quote that names it by a listed form, `mc.forms`, in the quote or (a quote cut
  mid-name) where its line continues it or its sample ends inside the gold's name, and that is not
  a prompt echo; no code check overrules the judge's pick (`judge-only-v1`), and the raw
  wrong-vs-true counts are reported only; `true_bridge_rate` replaces the removed
  wrong_bridge_true).
  user_modeling (plan 0056; judge calls `CALL_VERSION = "um-v3.4"`; bank `items_v2.json` = the
  47 selfdescribe items, result stamp `um-v3.4+bank-v2`, read plan = items.json's via
  `read_plan_bank`) adds a value gate on top of the shared
  `quote_ok` + `statement_lines`: `mc.form_in` over its frozen lexicon `aliases.py` (an edit
  there bumps its `CALL_VERSION`; `tests/fixtures/user_modeling_gate_cases.json` replays the
  cached gold picks, so rebuild the fixture's `blocked_expected` when the lexicon changes).
  role-bound's summary mode asks each item three times and votes over the draws' pass / fail
  verdicts (`judge.draw_verdict`, stamp `+maj3v`), and so does user_modeling's (a draw passes
  on a gated gold pick with an inferred basis; its full label, `judge.draw_label`, is a
  diagnostic). Both reuse conjunctive's `draw_key` / `majority` / `n_draws`; draw 0 keeps the
  single-call key.
  model_specific_directed_modulation (plan 0016; formerly directed_modulation_obscure) has its own
  regex `judge.py` with no LLM and no summarizer (token readouts are matched token by token, as in
  the source); its `PROMPTS` holds only the subject template, since `test_prompts_in_readme`
  requires every family to export one. knowledge_cutoff (plan 0017) is judged: ONE call per
  (item, layer) carries every position's samples (rule `all_from_end`, offset-only headers, no
  prompt text); its `score.py` (the source's per-option span matcher, exclusive longest match)
  now verifies quotes and feeds diagnostics. Plan 0044 (bank `items_v2.json`, 108 frozen + 39
  nocot = 147; cs01301 retired for a null label; Q8 near-alias forms, shown in the menu with
  `mc.KC_NONE` last) adds mechanical gates on top of `digest.quote_ok`: the quote must lie in
  one bullet with no cut letter/digit at its edges, the bullet's answer head (text before a
  `score.NOTE_MARK`) must not name another option / number (G1), the pick needs support from
  `min(2, n_samples)` samples (G2; a `digest.number_flood` sample supports nothing on numeric
  items) and, on numeric items, no rival may out-support it (G3). `ati_pass` keeps the old loose
  rule. The span check is the shared `reads.check_full` (`min_full_positions=4`, contiguous;
  enforced only with a sidecar). nocot rows are redacted in results (`[redacted: nocot]`;
  `scripts/check_nocot_redaction.py` for bundles). Plan 0018 adds ids-only nocot
  items (`evals/knowledge_cutoff/obscure_items.json`, none under `WSB_BANK_ROOT`): their prompt is
  rendered from nocot-bench's pinned zip by `wsbench.nocot` at plan time only (judge / run / ATI
  stay offline via `EvalSpec.item_ids`; `WSB_NO_NOCOT=1` drops the nocot rows from the plan, set
  by `atlas/export_cb.py`); `tests/conftest.py` stubs `nocot.questions` so tests never fetch. Never commit nocot question text or obscure items' real readouts / `cells.jsonl`.
- nyt_connections (plan 0062, `nyt-mc-2026-11-02`, group model_specific): **ids-only bank**
  (`evals/nyt_connections/items.json`: puzzle ids, member indices into the shuffled 16, Qwen's
  own labels; every label that folds equal to an NYT group name is a `{role, nyt_group[, nyt_id]}`
  reference). `wsbench.nyt` fetches the pinned Eyefyre mirror (`connections.json`, commit + sha256
  in the header) into `$WSB_CACHE/nyt/` at plan / judge time; `WSB_NO_NYT=1` drops the family's
  plan rows (in `reads._env_key`; set by `atlas/export_cb.py`); `tests/conftest.py` stubs
  `nyt.puzzles` with synthetic words (offline stub), so tests never fetch. Read: last 12 prompt
  tokens x GRID, lite = full (`SAME`). Scoring: the v1.1.0 layered digest (the CLI default; the
  family pins no layer mode), then one blind MC per **stable slot** (`cannot tell` last, quote
  gate on `col.evidence`, verbatim-only); **per-slot rows** `id = "cNNNN|sK"`, headline on
  stable slots only (non-stable slots write no rows, only extras), refusal counts in stable
  slots; extras: partner null, continuation floor, word-masked digest, slot 0 vs 1–3. Bar =
  beat the frozen `po-opus-v1` floor (`scripts/nyt_connections_bar.py`, which refuses a
  mismatched instrument); the continuation floor is reported, not gating (Camila's §0
  override). Rows carry roles, never label text; digests / quotes redacted unless
  `opts=keep_nyt_text`. Never commit NYT text, real readouts, `cells.jsonl` or results of this
  family.
- moral_rationale (plan 0046): **bank v3 is the registered default (`ec-v9`: one pick per (item,
  side), "which one reason do these readouts mainly give", the judge seeing the digest's sample
  counts; code only verifies the quote, pass = the verified pick is the gold; summary mode asks
  each (item, side) 3 times, reusing conjunctive's `draw_key` / `majority` / `n_draws`, and takes
  the majority of the draws' pass / fail verdicts, result stamp `+maj3v`; a near-verbatim quote
  (`nearquote.close_lines`) verifies like an exact one under `ec-v9` only, summary stamp `+nq1`; the earlier
  multi-label rule survives only as `lucky_guessing.marks_pass`, which scores the multi-mark
  guessers of the floors frozen under it); bank v5 `evals/moral_rationale/items_v5.json` is
  opt-in** (round 4, `ec-v9-b5`; not registered while it leaks the side, review of #215): the 24 bank-v3 items whose rebuilt
  distractor lists a question+options, an options-only and a described (solved-examples) guesser
  pick the gold from at uniform chance (`scripts/moral_v5.py`: adversarial authoring with the
  guessers in the loop, a confirmation gate on fresh draws; floors in
  `evals/baselines/lucky_guessing_moral_v5.json`, multi-mark ones against
  `lucky_guessing.marks_null`). NOT at chance for a side-aware reader
  (review of #215): Qwen commits 'no' on 22 of 24 items, so a guesser-free reader that always
  marks the 'no'-side options passes 0.917 (`lucky_guessing.prior_side`, frozen `side_prior`),
  and marking the side the guessers avoid passes 0.792, both vs a 0.500 coin
  (`lucky_guessing.side_readers`, frozen `side_*` fields; `moral_v5.py freeze` refuses such a
  bank without `--allow-side-leak`; `lucky_guessing.bar` counts every side reader, so v5's floor
  reads `side_prior:no` 0.917). Does NOT meet the r2 "moral options-only at chance" standard, and
  neither does registered bank v3 (floor 0.831; its always-no reader 0.708). Decided for the
  freeze (2026-11-01): bank v3 stays the default (lowest bar of v3/v4/v5; cross-bank floors
  table at the top of `evals/moral_rationale/README.md`). The
  read plan stays bank v3's 195 rows for banks v4/v5
  (options are never in the render), so v3 readouts judge v5 with no GPU. Bank v7
  `items_v7.json` (opt-in, `ec-v9-b7`, `scripts/moral_v7.py`): v3's 195 items and golds, all four
  distractors other LLMs' same-side reasons (Opus/Sonnet 5.5, astra, argon harvest), so the side
  readers are at 0; NOT registered: its gold guessers stay far above chance (the gold is Qwen's
  modal reason; floors `evals/baselines/lucky_guessing_moral_v7.json`). Bank v3
  `evals/moral_rationale/items_v3.json` (judged under `ec-v9`; earlier `ec-v5d` = the multi-label
  rule, and `ec-v4.1` = ec-v4's text): bank v2 with length-matched, co-registered option lists (review
  round 4 of PR #186: gold rank by length balanced, comma / slash (and its spacing) / "outweigh" / "and" marks
  matched; `scripts/moral_distractors.py lenmatch` + `coregister`). Bank v2 `items_v2.json` (195 items,
  `bank_version: 2` per item; frozen, `ec-v4`; v1 `items.json` byte-identical) re-keyed under the READ render
  (`wsbench.adapt.moral stage=rekey_readrender`: Leg S one-word side, Leg R reasons with the
  answer teacher-forced; Qwen via `scripts/qwen_sample_modal.py`, Opus distil / side checks);
  options are frozen bank data (committed: gold + 2 opposite + 2 same-side-unraised; deliberative
  side lists: gold + 4 same-side-unraised on 41/58; cannot tell last;
  `scripts/moral_distractors.py`); floor = highest measured guesser (`lucky_guessing.bar`, bank v3: described
  0.718 > question 0.704 > blind 0.593), not the question guesser alone. Instrument by bank: v2 = `ec-v4` (rules (a)-(f), stance rule
  on every ask, two-level quote gate `quote_ok` + `statement_lines` -> `pick="unverified"`); v1
  (`WSB_BANK_FILE_MORAL_RATIONALE=evals/moral_rationale/items.json`) = legacy `ec-v3.1` (ec-v3
  with a tool-free system opening). Reads:
  full = every render position (`min_full_positions=6`), lite = the last five. Its ATI entry was
  re-gated under ec-v5c on 2026-10-31 (R1-ATI, full panel: 152/195), re-stamped ec-v5d in round 3; it is stale under ec-v9 until re-gated. Opt-in bank v4 (`items_v4.json`, 53 gate-passing items, `ec-v9-b4`, `scripts/moral_adversarial.py`).
- association (plan 0039) left the bank judge: bank v2 `evals/association/items_v2.json` (93
  items; v1 `items.json` byte-identical, read only by `tests/test_basic_association.py`'s
  test-only `bank_family` registration), its own `judge.py` (8-way MC + cannot tell; gate:
  `digest.quote_ok` -> one retry of a quote miss -> token-line flat-list void -> listed form
  (`mc.aliases`, any case; a `HOMOGRAPH_GOLDS` gold such as pentagon only with its capital, never
  hyphen-glued) -> the quote's own line or another evidence sentence (3b / 3c) -> a homograph
  gold held only as the common word fails (`gold_common_word`) -> quote-only re-judge; no
  raw-sample count overrules the pick; row `credit`; stamp
  `assoc-mc-2026-11-01-v3+gate-a2+bank-v5`, calls keyed `CALL_VERSION`), read at the 19
  summarize-suffix sites like conjunctive / role-bound. The registered bank is v5
  (`items_v5.json` = bank v3 minus `winter` and `pentagon`, 91 items, v3's read plan via
  `read_plan_bank`; an adaptation plans its own items, so `adapt.store.original_bank` drops that
  key from the header it copies). Its options come from
  `scripts/association_distractors.py` (Opus proposer from the gold alone, lint + entailment
  check, 5-draw scene screen). Its ATI entry was
  re-gated on 2026-10-31 (R1-ATI) on the reduced panel, qwen+opus then qwen+opus+astra (R1-ATI
  rev, astra via OpenAI WIF; argon missing): 25/93, PROVISIONAL; then on the full panel (R1-ATI
  gemini, 2026-11-01, argon via Gemini WIF) at bank v3: 26/93.
- buggy_code (plan 0030) is pair-scored on the bank's symmetric `twin` field: headline
  `pair_rate` since 2026-10-30 (metric `pass_rate`, in the macro, `chance` 0.0;
  `specific_pair_rate`, the grade-≥8 bar, in extras; instrument
  `buggy-pairs-2026-10-29+pair-headline-2026-10-30`, judge calls keyed `JUDGE_PROMPT_VERSION`), `items=` expands to
  pairs, `limit=` counts pairs, `n_items` = pairs in scope; orphans (no twin; every adapted-bank
  item) stay in the per-item extras only. Stage A is 3 votes (keys `...|infer|v1..v3`), Stage B 3
  votes (`...|grade|v1..v3`) only on buggy pair members claiming `bug`; any undecided pair makes
  the run incomplete. ATI NOT_GATED.
- agentic_misalignment (plans 0031 / 0052) is pair-scored on misaligned / clean-twin pairs, bank
  `items_v2.json` (am-bank-v2, 22 pairs; v1 `items.json` / `targets.json` frozen, sha-pinned by
  `test_old_bank_untouched`; the Stage C companion follows `registry.bank_path` by name,
  `judge.targets_path`). Twin `<id>~twin`, `arm: "twin"`, symmetric `twin` field, inserted after
  its partner; targets_v2.json gives it the partner's entry, and `judge.target_of` falls back to
  the partner's: headline `pair_rate` (metric `pair_rate`, in the macro iff the header's
  `n_pairs >= 20`, else `not_in_macro` carries the count, Q13; `chance` 0.0, cluster-bootstrap CI
  over the bank's `cluster`), strict twin false alarm = asserts OR `(design_rank or 0) >= 1` OR fidelity
  >= 2, a PARSE_ERR twin is undecided; the old `design_score` lives in extras (read there by
  `judge_swap.py`'s parity port and by consumers). `aggregate_design` never sees a twin;
  `score_group` gives twins their own group. Scope as buggy_code (`items=` pulls pairs, `limit=`
  counts pairs, `n_items` = pairs). The stamp is `+pairs-v2` on `PROMPT_VERSION` and the
  summary stamp (`SUMMARY_STAMP_VERSION`), never in a fingerprint. Call versions
  `am-narrative-v2` / `am-design-v3` / `summ-c3` (tool-free wording, `{read_scope}`, "the act
  within one line" with `digest.statement_lines` splitting the Stage C view per bullet, declared
  sampling in native `cell_text`). `opts=stride=` is retired (exit 2): positions come from
  `reads=full|lite` (lite = every 16th + last 8); `min_full_positions = 64`. `wsbench adapt
  agentic` skips twins (adapted banks: headline None). The bank is built by
  `scripts/build_agentic_twins_bank.py` from the reviewed drafts and gate verdicts; gate-4 rows
  for the shared sampler come from `scripts/agentic_twin_gate_modal.py rows`. Summary mode: the
  digest runs on the Stage C pin `claude-sonnet-5` (`aux_models["digest"]`), and a digest or
  Stage C call Sonnet declines re-runs once on `claude-opus-5` (`summ_fallback=none+claude-opus-5`;
  Stage C via `llm.stream_text(refusal_model=)`); a digest both decline leaves its pair undecided;
  rows record `digest_model` / `judge_model`; `judge.summary_pinned` replaces `digest.pinned`
  (which wants the repo-default digest model); the summary stamp gains `+sonnet-digest+opus5-fb`
  (no fingerprint moves); Sonnet digest calls run at the 64k `digest.OUTPUT_CAPS` cap.
- hinted_cutoff (plan 0063) is pair-scored like unverbalized_hint (`items=` expands to pairs,
  `limit=` counts pairs, `n_items` = decided pairs) but its headline is the class DIFFERENCE
  (I flag rate - N flag rate, jailbreak precedent: chance 0, may be negative, in the macro
  unrescaled); `pass_rate_result` builds the row and `dataclasses.replace` swaps in the
  difference and its event-cluster CI. Plan 0064: it reads the PROMPT only (`captured` render;
  the bank ships prompt-only ids, no reply text, no reply span), at the gw prompt span
  (prompt-render tokens, length-equalized, `full_contiguous=False`; hint tokens are never read
  positions, and in the 16 authority/sycophancy items the hint sentence lies after the last read
  position, so no reader sees it there). The
  judge is the global-workspace ccut EXIST4 instrument reworded tool-free; quotes go through the
  ported `score.verified_quote`; NOT_GATED, NO_QUESTION, `summ_rare=25`.
  `scripts/hinted_cutoff_replay.py` is the validation gate (byte-equal native renders and the
  frozen prompt-span 97 / 87 replay over 712 chunks).
- unverbalized_hint (plan 0026; retired for now by plan 0058, see above) is pair-scored (`items=` expands to pairs, `limit=` counts
  pairs, `n_items` = decided pairs), native-only and ATI-ungated; its judge has a per-call
  refusal fallback to `aux_models["fallback"]` (Sonnet 5.5, family pin only) that is NOT
  `llm`'s server-side `fallbacks`. The bank builder needs transformers (the `gpu` extra) and the
  source checkout; `scripts/convert_frozen_hint_readouts.py` + `uvh_verify_replay.py` are the
  validation gate against the frozen numbers.
- `opts=key=value,k2=v2` fills `JudgeArgs.extra`; `aux_models` comes from the family `JudgeConfig`.
  `EvalSpec.calls_per_arm` / `.sources` feed `wsbench list`; every non-empty `sources` must
  appear verbatim in README §Credits and NOTICE.md (`tests/test_readme.py`).
- Renamed families: `registry.LEGACY_FAMILY_NAMES` maps the former keys `introspection_inject`
  / `cutoff_confab` / `dm_category_default` to `introspection` / `knowledge_cutoff` /
  `directed_modulation_obscure` (2026-10-26, pure rename: banks and ATI ids unchanged; the bank
  headers keep the old key), and `directed_modulation_obscure` (and `dm_category_default`, since
  `canonical` is single-step) to `model_specific_directed_modulation` (2026-10-30, plan 0034:
  bank and native instrument unchanged; the ATI entry moved key with
  `scripts/ati_restamp_rename.py`, which re-derives the old-name `bank_sha` first).
  v1.2.0 (2026-11-03): `wrong_bridge` -> `wrong_intermediate`, a label change that keeps every
  hash: `registry.HASH_FAMILY_NAMES` / `hash_name` make `plan_sha` (`reads._clean_row`), the ATI
  `bank_sha` (`text_inversion._row_dict`) and the lucky-guessing seeds (`_rng`) hash the old
  key, so pre-rename sidecars, ATI entries and floors stay valid without a restamp;
  `registry.family_dir` reuses a `wrong_bridge/` out dir or `summ_store` subdir. The bank
  files moved byte-identical (headers keep `"family": "wrong_bridge"`); prompt bytes unchanged.
  `registry.canonical` resolves CLI `family=`/`families=`, `run` falls back to `<old>.jsonl`,
  `read_results` and `text_inversion.subset_entry` accept the old key
  (`tests/test_legacy_family_names.py`).
- `EvalSpec.superseded_by="<successor>"` retires a family without deleting it (plan 0015;
  today `typo` -> `typo_mt`, plan 0033; its first user, `multihop_mt` -> `multihop_mt_v2`, was
  removed on 2026-10-30, plan 0041; a family built by a shared factory sets it with
  `dataclasses.replace(factory(...), superseded_by=...)`): `results.macro` excludes it (reason
  `superseded`) and every `all` default skips it via `registry.drop_superseded`; it stays
  runnable by explicit name (`run` also takes `include_superseded=True`).
- Deleted families: `registry.REMOVED_FAMILIES` (today `ttt` / `ttt_move`, removed 2026-10-26 by
  plan 0017 as too close to next-token prediction, `brew_intermediates`, retired 2026-10-29
  by plan 0029 because the prompt alone solves it, `wrong_bridge_true`, removed 2026-10-30 by
  plan 0050: not part of the benchmark, its signal is wrong_intermediate's `true_bridge_rate`,
  `hallucination`, replaced 2026-10-30 by HallucinationBench, plan 0040, and `multihop_mt`,
  removed 2026-10-30 by plan 0041 as superseded by multihop_mt_v2, and `medical_diagnosis` /
  `medical_diagnosis_alt`, removed 2026-10-31 by Camila, plan 0058) are gone from the code, banks and ATI file;
  `results.macro` excludes a stale `results.json` of theirs in an old run dir (reason `removed`).
- Retired families (reversible): `registry.RETIRED_FAMILIES` (today `unverbalized_hint`, retired
  (Camila 2026-10-31, for now), plan 0058). Package, bank, tests and floors stay and the family is
  registered and runnable by name, but `drop_superseded` (what `all` means) skips it, the macro
  excludes it (reason `retired`), and it has no README family entry / Judges row / ATI
  `_not_gated` line. Restore = delete the dict entry and re-add those three (plan 0058 lists them).
- HallucinationBench index (plan 0040): `wsbench.hbindex` reads the frozen vendored
  `evals/hallucinationbench/index.json` (hindex-v6 at one HB sha, plans 0040 + 0057; written ONLY by
  `scripts/vendor_hb_index.py`, which refuses a sha or version mismatch) and `methods.json`
  (WSB arm -> HB method; an unverified checkpoint goes under `not_measured`, never aliased).
  `wsbench report` appends the block after the macro table (`full`, else `matched (no
  sibling)`); it never enters the macro. A refresh is a new commit with a new `hb_sha`.
- `EvalSpec.not_in_macro="<reason>"` keeps a family out of the macro only (reason `not in macro`,
  `registry.not_in_macro()`); it still runs in `all` and appears in every table (today no static
  one: medical_diagnosis{,_alt} were removed by plan 0058; agentic_misalignment's `macro_gate`
  computes one below 20 pairs; the four plan-0016 families joined the macro on 2026-10-25). `readplan` rule `offsets_from_end {ks}` reads
  several end offsets; a plan row with `extra["ati_scored"] = False` is never ATI-gated
  (`text_inversion.ati_scored`), so controls can ride in a family's plan.
  `text_inversion.CONSTRUCTION_GATED` is empty since plan 0019 (knowledge_cutoff, incl. its nocot
  items, is panel-gated); the mechanism (a family whose whole bank is written as the subset,
  `answerer: "construction"`) stays for a future family gated when it is built.

- Summary mode (`aggregate=summary`, plan 0020, `digest.py`) is the benchmark DEFAULT since plan
  0024: `runner.parse_opts` fills `aggregate=summary` in unless `opts=aggregate=native`; a family
  called directly with a hand-built `JudgeArgs` (no `aggregate`) keeps its native rule. Tests
  that mean native pass `opts=aggregate=native`. Scripts that re-score native caches or feed the
  ATI gate pin native explicitly (`scripts/ati_panel_judge.sh`, `scripts/cache_only_run.py`,
  `atlas/normal_gated.py`, `adapt/floors.py`); `text_inversion.draw_verdicts` refuses summary
  results. Summary rows draw `evals/baselines/prompt_only_summary.json` (row-relative match on
  prompt_version + digest settings + judge) and the per-item lucky floor. A hooked family calls
  `digest.collapse(name, cells_by_item, ...)` AFTER its own cell selection and missing-cell
  accounting. Items with no cells are not passed; `n_expected` / `n_missing` stay cell-level and
  `n_empty` / `n_unjudged` become item-level, so pass `n_items` to `completeness`. It then judges
  the one synthetic cell per item (`layer = digest.SUMMARY_LAYER = -1`, pos/token copied from the
  item's last cell) with summary-mode prompt variants listed in its `PROMPTS`. Every quote,
  numeral or regex gate takes `digest.gate_texts(cell, col)` (evidence samples only;
  `joined=True` for regex). Summary mode never changes a family's denominator rule. Stamp
  `digest.prompt_version` / `digest.config` / `digest.pinned`. `runner.judge_family` stamps the
  `digest.NATIVE_ONLY` family (jlens_concept_pr) native and fails
  any other family that did not report
  `config.aggregate = "summary"`. Never bind a module constant (e.g. `PROMPT_VERSION`) as a
  default argument: tests monkeypatch it. digest-v5 (audit fixes, `docs/summarizer.md`
  "Audit fixes"): a multi-layer item is digested per layer and merged (`summ_layers=union`, so
  a test's digest-call count is items x read layers; `joint` is the ablation, and every numbers
  digest stays joint), every entry carries a per-claim `count` rendered `[N samples]`, a
  collapsed digest (< 5 entries from >= 100 readouts) is re-asked once, an unsummarized item is
  undecided (never a fail), a row whose only shortfall is such refusals stays complete
  (`runner.refusals_only`), and `results` marks a row with > 20% undecided not measurable.
  Tests that drive the chunk machinery with multi-layer cells pin `summ_layers=joint`.
  v1.1.0 `summ_layers=layered` (`docs/summarizer.md` § Layered; stage-2 budget `summ_layered_x`
  default 4 since v1.1.1, stamped `-layered-v1x4`; `summ_layered_x=2` = the v1.1.0 `-layered-v1`): the per-layer digests, then
  ONE stage-2 call per item over them (`digest._layered_pass`, schema `DIGEST_SCHEMA`, grounded by
  `digest.layered_ground`). `runner.judge_family` makes it the default of a multi-layer CLI run
  (`digest.resolve_layer_mode`); a hand-built JudgeArgs and every single-layer run stay `union`,
  so test call counts are unchanged. `summary_fakes.FakeLLM` answers stage-2 calls (user starts
  `LAYER DIGESTS:`) with `layered_digest` and records them as `"layered"`, not `"digest"`.
  `summ_store=<dir>` shares every one-layer digest (key `digest:<id>|<L>`, same fingerprint)
  across out dirs, so `layers=[L]` and the union run ask each (item, layer) once
  (`tests/test_digest_store.py`; docs/summarizer.md "Shared per-layer store").

## Driver (`runner.py`, `cli.py`)
- `run all=True|families=a,b readouts_root=DIR out=DIR [family_workers=3] [json=True]` reads
  `DIR/<family>.jsonl` (missing -> `skipped`). Order: parse `opts=` once (bad pair = one exit
  2), resolve every judge once, preflight each distinct judge model once (not aux; skipped
  under `dry_run=True`; failure = exit 3 before any thread), then judge in a `ThreadPoolExecutor`
  (`min(n, family_workers)`, 1 under `dry_run=True`) under the shared pacer. Fail-soft per
  family: `JudgeConfigError` -> failed/3, `SystemExit` -> failed/2 (text `e.code` or `exit N`),
  listed under "## skipped / failed" in `summary.md`; other exceptions propagate. Exit 130 on
  `KeyboardInterrupt` (unstarted families cancelled, in-flight ones finish their batch), else
  3 > 2 > 0. Writes `summary.md` + `run.json` = `{started, finished, families: {name: {status,
  error?, results_path, value, complete, pinned_instrument, spend_usd, n_calls?}},
  judge_overrides: {flag, env}, readouts_root}`.
- `report dir=DIR [json=True]`: table with `(lower is better)`, `n (k no readouts)`, macro row (in-row
  `excluded:` + "Not in macro:" footnotes); rewrites `summary.md`. Exit 2 = not a directory /
  unreadable results.

## Results contract (`results.py`)
README §Results contract is the single statement (schema, `complete`, the macro row); `results.py`
implements it. Not restated here.

## Invariants
- Every judge prompt lives in the family's `prompts.py` (`PROMPTS`; `{name}` placeholders
  rendered by `str.replace`, never `str.format`) AND verbatim in a fenced block of the family
  README under "Judge prompts";
  `tests/test_prompts_in_readme.py` asserts equality. Bump `prompt_version` on any edit.
- Failures never score; they are counted. Frozen banks are never edited in place. `spec.run`
  returns a `FamilyResult` and writes nothing. `counts` has a fixed key set (other tallies go
  in `extras`); no `Spend` crosses the family boundary. Cache rows are append-only.
- README: each family entry is `**<spec.title>** — [link]` followed by exactly three lines
  `- *What it is:*` / `- *Example:*` / `- *Judged by:*`, grouped Basic (single token) · Basic
  (multi-token) · Computational · Safety · Association · Bag of words · Precision · Model-specific. Credits live in README §Credits and NOTICE.md, one
  bullet per external source; in-house families get no credit line.
- Style, enforced by review rather than a linter: module docstrings are 1–3 lines (rationale
  goes in the README beside the code, not the file header); no `from __future__ import
  annotations` (Python ≥ 3.11, write the modern syntax directly).

## Adding a family
`src/wsbench/evals/<family>/{__init__,prompts,judge}.py` following the skeleton above (register an
`EvalSpec` in `__init__` with `calls_per_arm` and `sources`), `evals/<family>/{items.json,README.md}`
with every prompt verbatim, a toy `examples/readouts/<family>.jsonl` (a few rows), an offline
`tests/test_<family>.py` (monkeypatch the module's `run_calls`), the README entry and Judges row,
and a credit if the items are external. Summary mode is the default (plan 0024), so a new family
either implements it (`digest.collapse` + a summary judge path, see the summary-mode bullet
above) or gets a `digest.NATIVE_ONLY` entry with its reason; otherwise every default run of it
exits 2. Smoke `limit=3` live before any full run.

## Workflow
- CLI (pydra, `wsbench <command> key=value ...`): `wsbench list` | `wsbench judge family=F
  readouts=F.jsonl out=DIR` | `wsbench run all=True readouts_root=DIR out=DIR` |
  `wsbench report dir=DIR` | `wsbench baseline` / `wsbench freeze` |
  `wsbench plan [families=a,b] [out=DIR]` (the producer interface: render, positions rule and
  layers per item, `docs/producing_readouts.md`; `readplan.resolve` turns a rule into indices) |
  `wsbench produce family=F method=M out=F.jsonl` or `text=... method=M positions=-1
  layers=20,36,60` (methods logit_lens | jlens | rlens | olens | nla; needs the `gpu` extra;
  a plan row's `extra.steering` of type concept / gaussian is applied by `Producer.steering`,
  a forward hook at `inject_layer` reading the shipped `vector_file[vector_row]`, plan 0045) |
  `wsbench capable model=M` (re-run a bank's own gate on another model; porting notes and
  the pre-run sanity checks live in `AGENTS.md`) | `wsbench convert-gen-dir
  gen_dir=GEN out=F.jsonl kind=prose|tokens` | `wsbench convert-read-json read=R out=F.jsonl`
  (legacy). Shared judge keys: README §Quickstart (the output-layout paragraph). Each command is
  a `pydra.Config` in `cli.py`: declare a field in `__init__`, normalise it in `finalize()`;
  `runner.py` reads the same attribute names.
- `uv sync --extra dev` (add `--extra gpu` for `produce`); `uv run pytest -q`; `uv run ruff
  check .`; `uv run ruff format .`. Keys
in the environment, never committed; tests make no network calls. Work
in a git worktree (prefix commands with `PYTHONPATH=src` when it shares the main checkout's
`.venv`); PRs are gated by `.github/workflows/ci.yml` (ruff + pytest).
