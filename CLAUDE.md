# workspace-bench — agent runbook

`wsbench` is a growing set of evals of whether an activation-reading lens (prose "O-lens" samples or
top-k "J-lens" tokens) surfaces what a model computes but never writes. Every family plugs
into the shared package in `src/wsbench/` (client, judge config, cache, readout contract,
results schema, registry, runner, CLI, `readplan` = the producer-facing read plan, `capable/` =
the porting gate, `produce/` = the optional HF-transformers producer behind the `gpu` extra).
`plans/` is the 2026-09-15..17 design history of the nine-family restructure, not a current
pointer (`plans/README.md`). Public docs: `README.md`, `NOTICE.md`, `CITATION.cff`. The README is
the newcomer's path (what it is, requirements, time and cost, install, `wsbench try`, running,
outputs, checks, viewer, one table of the evals, credits); reference material lives in `docs/`
(evals, running, tiers, judges, baselines, fast_subset, results_contract, porting, checks,
judge_backends). `tests/test_readme_style.py` keeps dates, plan numbers and
version-style labels out of the README's prose.

## Readout contract (input to every family)
Stated once, in README §Run it (the contract block) and `docs/producing_readouts.md`; do not
restate it here. Code facts only: `load_readouts` counts malformed lines (never fatal), keeps the
first duplicate `(id, layer, pos)`, counts empty readouts (a result, not a missing cell).
`wsbench convert-gen-dir gen_dir=GEN out=F.jsonl kind=prose|tokens` converts the in-house
`<gen_dir>/<label>/L###.jsonl` layout (id = directory name, layer = filename).

## Judge layer (`llm.py`, `judge_config.py`)
- Default judge `claude-opus-5-5` (Anthropic; plan 0023, Camila 2026-10-29; Gemini 3.8 Flash via
  OpenRouter before). Pins: agentic_misalignment + jailbreak_recognition -> `claude-sonnet-5` (jailbreak: kept by
  the plan 0037 J8.5 smoke, `evals/safety/jailbreak_recognition/judge_smoke_v2.json`),
  introspection -> `claude-opus-5-5` at default effort (reasons: `docs/judges.md` and the family
  READMEs). jlens runs all three stages on the default judge. Opus 5.5 cannot disable thinking:
  `llm.always_thinks` models get low effort unless a family sets `anthropic_effort`. Tests script
  OpenRouter-shaped fakes; `tests/conftest.py` routes them through the OpenRouter path.
- Override precedence and what `pinned_instrument` means: `docs/judges.md` (the bullets under
  the table); not restated here.
- Routes by model id: `claude-*` -> Anthropic SDK (`ANTHROPIC_API_KEY`, or with no key and
  `ANTHROPIC_PROFILE` set, the SDK's `ant auth login` profile; structured output,
  refusal -> `None`); else OpenRouter via the OpenAI SDK (`OPENROUTER_API_KEY`, `sk-or-…`);
  with `WSBENCH_OPENAI_ROUTE=wif` (plan 0096 part 2, a port of the unmerged plan-0059 branch)
  an `openai/*` id that is not `openai/gpt-oss*` takes route `openai`: OpenAI directly through
  `llm._WifClient(ati_remote.Clients("openai-wif"))` (`api_key` = `""`; `_openai_once` /
  `_openai_text_once`: `max_completion_tokens`, `reasoning_effort` from `effort`, never
  `temperature` or `extra_body`; `_wif_create` re-exchanges on a 401 up to
  `ati_remote.AUTH_REFRESHES` times, the last 401 and every 403 are fatal, a
  `JudgeConfigError` inside a call is re-raised, `TransientExchangeError` is transient; cost 0).
  A bad env value raises in `llm.route`, so every `resolve` / `digest.settings` caller must end
  as exit 3. The two chat routes share `_chat_result` (refusal rule; an unparsable body with
  `finish_reason == "length"` is one failed call, never retried), `_chat_text`, and
  `WSBENCH_OPENROUTER_MAX_OUT` (`llm._capped`: the cap of every chat-route call by the route of
  the model actually called, the starting budget of free text, never read for an Anthropic
  call; while set, `_too_long` also takes the `OPENROUTER_TOO_LONG` phrases of a 400 as
  `TOO_LONG_JSON`). `reasoning_for` treats `openai` as `openrouter`; `temperature` goes only to
  an `openrouter` call; `llm.require_credentials` is the up-front check (the WIF token source on
  `openai`). `tests/conftest.py` clears both env keys for every test.
  `judge_effort=minimal|low|medium|high|default` (`judge_config.resolve(effort=)`, non-Claude
  judges only, a Claude judge exits 2; sets `pinned=False`; passed by `cli.JudgeFamily`,
  `runner._one`, `runner.run_families`, emitted by `judge_argv` and written to `run.json` only
  when given; read with `getattr(args, "judge_effort", None)`).
  **The summarizer follows a non-Claude override judge** (`digest.digest_model` /
  `follows_judge`: `summ_model=` > a present, unpinned judge on a non-Anthropic route >
  `aux_models["digest"]` > `DEFAULT_MODEL`; `digest.preflight_judge(extra, aux_models, judge)`
  must be given the resolved judge); `digest.digest_reasoning` gives a non-Claude digest no
  reasoning at the default effort, a family-default `summ_fallback` is `none` for it, an
  explicit `default[+<model>]` exits 2, `summ_context=` sizes the budget (`docs/judges.md` for the
  rule, the experiment and the validated Luna recipe).
  Shared: JSON-schema output, 11 jittered retries (`_ATTEMPTS = 12`) on 408/409/429/5xx/
  timeouts, process-wide thread-safe RPM pacer (`rpm=`, library default 240; CLI default 30000), `preflight` fail-fast,
  `Spend` tally. Structured Anthropic calls run at `effort: low` on always-thinking models unless
  the family sets `reasoning={"anthropic_effort": "default"|<level>}` (introspection: its
  source instrument ran at default effort; knowledge_cutoff sets OpenRouter `{"effort": "low"}`); `resolve` keeps only the reasoning keys
  of the route the judge resolves to (`anthropic_effort` on Anthropic, every other key on
  OpenRouter; plan 0023; the rule is `llm.reasoning_for(route, reasoning)`, which `resolve`
  calls, and `llm.OPENROUTER_MIN_REASONING` / `ANTHROPIC_REASONING_KEYS` are its constants,
  re-exported by `judge_config`), so an Opus judge of knowledge_cutoff gets `None`, not `effort: low`. A failed
  call returns `None` and never scores. `stream_json_async` is the primitive, `stream_json`
  wraps it (`temperature` dropped on the Anthropic route); `stream_text[_async]` is agentic's
  free-text primitive, on both routes since plan 0096 (`_openrouter_text_once`: a streamed
  chat completion, `thinking` -> `{"enabled": true}`, no thinking -> `{"effort": "minimal"}`, (the `openai` route sends `minimal` as `low`, `llm._openai_effort`: gpt-6-luna 400s on it),
  the same budget doubling to `_TEXT_BUDGET_CEILING`; a status-less SDK `APIError` from the
  stream, `finish_reason == "error"` and a stream without choices are transient). An OpenRouter
  refusal is `finish_reason == "content_filter"`, a `refusal` with no content, or the moderation
  403, for structured calls too (one counted refusal, not 12 retries of an unparsable body).
  Both take `refusal_model=`: a call the model declines is
  re-run once, same request, on that model (client-side, for models that reject the server-side
  `fallbacks` parameter); a served JSON result carries `llm.SERVED_BY`, a served text fires
  `on_served`, and only refusals move (a `max_tokens` stop or an error stays the primary's
  outcome). The refusal model must be another model and may be on the OTHER route (plan 0096):
  its key is resolved before any call, a second client is built, and the re-run is re-shaped
  for its route (`reasoning_for`, that route's default `max_tokens`, `temperature` only to
  OpenRouter, no overflow state); a same-route re-run is byte-identical to before.
  `stream_json(refusal_reasoning=)` gives the re-run's reasoning as is (a family's own effort
  for a cross-route fallback). `mcjudge.run_calls(refusal_model=)` passes it through and caches the serving model
  with the row, under the judge's fingerprint: a later run with another refusal model (or none)
  reuses that row (no stale-fallback check, unlike the digest), unless it passes
  `accept_served=False` (a served row is then a miss, re-asked on the judge). The four
  fallback families (hinted_cutoff, model_multihop, agentic Stage C, jailbreak draws) run their
  judge-call fallback whenever it differs from the resolved judge model, never keyed on
  `judge.pinned` (`family.effective_fallback`; `opts=fallback=on|none` via `family.fallback_on`
  at the top of `run()`, bad value exit 2; `family.require_fallback_key` = exit 3 up front for
  a cross-route fallback without its key; `config.judge_fallback` outside the pinned default;
  only the instrument-identity stamps read `judge.pinned`). `tests/test_pin_requests_0096.py`
  pins the pinned path's SDK requests and `config` against a golden: never regenerate it.
  The digest's equivalent is `summ_fallback=none+<model>` (any model id, either route), and
  `digest.OUTPUT_CAPS` gives a digest model its own per-call output cap (`Settings.max_tokens`).
  `stream_json[_async](overflow_max_tokens=)` re-asks a call that stops at `max_tokens` ONCE with
  that larger cap (Anthropic route; timeout scaled, at most `llm.OVERFLOW_ATTEMPTS` = 3 attempts;
  a second stop = `None`, one error); every
  digest call passes `Settings.overflow_max_tokens` (twice its cap, at most
  `digest.OVERFLOW_CEILING` = 64k; none for a model already there). The cap keys no fingerprint.

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
  sample ends inside the name) by name, alias or a derived form from the frozen `evals/basic/multihop_st/derived_forms.json` (`gold_forms`), names no other option, and
  is no number flood; no split rule; the gate version `GATE_VERSION` joins the result stamp while
  the calls keep `CALL_VERSIONS`; strings in the family's `prompts.MC`); per-family strings `FAMILY_RULES` (typo) are added to that family's own `PROMPTS` (`FORBIDDEN_TEMPLATE` / `FORBIDDEN_FAMILIES` is empty since plan 0058 removed medical_diagnosis{,_alt}; the mechanism stays); `FAMILY_PROMPT_VERSIONS` / `prompt_version_of` give a newer family its own stamp so adding a rule never stales the older families' `bank-2026-10-10` ATI entries and floors; `DIGEST_TASK_NOTES_TEXT` is in every basic family's PROMPTS, so a new note line must be added to every basic README) and `multitoken/`
  (`mt_family(name, title, calls_per_arm=, scorer=)`): basic_readout (the multi-token family, `basic_readout_mt` before plan 0101; plan 0051) is
  `scorer="mc"`: the MC judge of record (`multitoken.prompts.mc_system` / `BRMT_SYSTEM`, options
  `mc.options_with_cannot`) plus the deterministic name gate (code verifies the pick and never
  overrules it; `rival_quote` is reported only), since audit fix F4
  `multitoken.family.tolerant_gate` (quote verified by `digest.quote_ok` or near-verbatim via
  `nearquote.close_lines`; the gold named by the quote, a near quote's matched block, or, for a
  quote cut mid-name, where its own line continues it or its sample ends inside the name (no
  rescue through any other line), with
  case endings / Arabic clitics / Hangul particles / fuzzy spellings and the frozen
  `evals/basic/basic_readout/exonyms.json`; `name_gate` itself is the old strict rule), headline = the `readout`
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
- The four multilingual families (plan 0054) judge v2-shaped banks (registered: multilingual_st v4,
  multilingual v5, multilingual_multihop v5, multilingual_typo v4), whose v2 base is built by
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
  with `mc_roles` (the bank file stays frozen; `--check` still holds); multilingual_st's options show
  their accepted forms (`options.display_options`, F5); multilingual /
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
  Opus 5.5 refuses are re-asked on Sonnet 5.5 (`po-opus-v1+sonnet55-fallback`, 2026-11-01; the
  committed floors are the 2026-11-04 refreeze, `evals/baselines/README.md` "Floors of record",
  which also says which rows each floor kind is drawn beside: a prompt-only floor carries the
  single-layer digest instrument, so a default layered all-layer row shows none); the older
  Sonnet 5 protocol (`po.PO_FALLBACK_SONNET5`) is still read and labelled (`po.PO_FALLBACKS`),
  never written; `prompt_only_opus.fallback_rows` ignores answers of any other fallback model in
  a resumed dir. A summary floor matches a row regardless of the digest's client-side refusal
  model (`po._floor_match_key` keeps only the fallback mode), so a floor digested with the
  Sonnet 5 fallback would still draw beside Sonnet 5.5 rows. A `read_plan_bank` bank is asked and
  gated on its own ids only (`text_inversion.judged_bank_ids` / `gated_ids`). Plan 0070: the
  prompt-only input never holds a reply (`baselines/prompt_cut.py`, token-level, markers probed
  off the subject's template; rows stamped `prompt_cut: reply-free-v2`, which every later stage
  requires; `freeze` requires it of the run config given as `source=` and, without one, never
  replaces a stamped entry (always pass `source=`); the quoted token is the cut prefix's last, `site_token` places the
  cell; answers count only by `prompt_sha`); the protocol stays `po-opus-v1`, and the six
  floors whose input changed (basic_readout, the three directed-modulation families,
  introspection, jailbreak_recognition) were re-measured on the refreeze instruments
  (2026-11-17) and carry `prompt_cut`; every other entry is unchanged (input byte-identical).
  `logit_lens` (plan 0071 (logit-lens floor), not main's ATI plan of the same number): the frozen logit-lens final-layer (L63) floor `evals/baselines/logit_lens.json`
  (summary prompt-only entry schema + `protocol` + `ati`), written by `wsbench freeze
  kind=logit_lens` from `layers=63` summary runs (refused otherwise; registered banks only) and
  drawn as the report's third column by the summary prompt-only row-match rule; never a gate.
  Refrozen 2026-11-17 on main's instruments (29 families, raw mean 0.121, 0.119 since nyt_connections' 2026-11-20 re-freeze under plan 0099; strict ATI 0.046 over
  the 7 `ati-subset-v2` families with an entry; model_multihop has none). An entry is tied to its
  family's summary instrument, digest settings, judge model and read plan:
  `tests/test_logit_lens_floor.py` (`test_every_committed_entry_matches_its_live_row`,
  `..._is_on_the_registered_plan`) fails when any of them moves, so a PR that moves one re-judges
  from the L63 readouts and re-freezes that entry (readouts of an older plan only through the
  bank's recorded drop-only `plan_lineage`, as `reads` guard (iii), and only when the judged
  run's `config.plan_lineage` records that step). The live instrument is the judge's own FULL
  stamp (`logit_lens.live_config`: a call-free dry run on an empty readouts file), never a
  prefix match; `freeze` also refuses a dry run and a `src` that leaves existing entries in
  place (`partial=True` keeps them under `_source.kept_from`). The floor is Qwen3.6-27B's
  activations: `logit_lens.on_registered_bank` keeps it off adapted rows (`$WSB_BANK_ROOT` at
  report time, `config.bank_root` stamped by `runner.stamp_adapted_bank`, or
  `config.registered_prompt_version`); prompt-only floors are unaffected.
  `text_inversion` builds the anti-text-inversion subset (`evals/baselines/anti_text_inversion.json`,
  plan 0019 panel gate, which replaced plan 0014's Opus-only gate): Qwen3.6-27B + the frontier
  group (Claude slot opus/sonnet, `openai/gpt-6-astra`, `google/gemini-4-argon`) x 3 draws, each
  judged by the family's scorer; ATI iff EVERY panel reader failed every draw (`panel_verdict`,
  the only panel rule, plan 0071, gate `panel-v2`; `all_fail_verdict` is the same function).
  `BANK_SHA_GATES` (`panel-v2`, `adapted-panel-v1`) keep the `bank_sha` guard; an entry of a
  `RETIRED_GATES` rule (`panel-v1`) is refused ("re-gate"). The frozen file is re-derived from
  stored statuses by `scripts/ati_rederive.py` (`--check` must pass). The macro gates an ATI row
  on its gated ids (`extras.ati_n_ids`, < 20 -> out, except `results.ATI_MACRO_EXCEPTIONS`
  poetry / model_multihop on the registered `panel-v2` gate with every id judged) and excludes a
  row whose `extras.ati_gate` is not in `BANK_SHA_GATES` (`stale ATI gate`) or whose
  `extras.ati_subset` is another `text_inversion.SUBSET_VERSION` (`stale ATI subset`). Plan 0085
  froze the Qwen3.6-27B strict-ATI macro at 8 families (`ati-subset-v2`, pinned by
  `tests/test_ati_freeze.py`); nyt_connections and hinted_cutoff are out. model_multihop stays
  `NOT_GATED` for the generic gate, but its registered entry is pinned (`PINNED_ENTRIES`, answer
  form `FAMILY_PANEL_TEMPLATES["mmh_bridge"]`): `subset_entry` serves it, and a full `gate()`
  carries it over. Plan 0088: GLM-5.3 has the first committed adapted ATI files (`adapted/glm-5.3/
  anti_text_inversion.json` = default, `.with_qwen27b.json` via `ati_variant=` with gate
  `adapted-panel-v1+qwen27b`); an adapted entry's `macro_exception` (stamped
  `extras.ati_macro_exception`) admits it below 20 on an adapted gate; `OPT_IN_ENTRIES`
  (nyt_connections) are served only with `ati_opt_in=`; `gate_adapted` refuses a file whose
  `_source` records `gate_deviations`. Layout: `answers/<answerer>/draw{d}`, `readouts/<answerer>/draw{d}`,
  `judged/<answerer>/draw{d}`; the flat plan-0014 layout is still gated by its own rule
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
  so `split_special_tokens` alone does not keep it plain text). Adapted sets (plan 0079): under
  `WSB_BANK_ROOT` `build` renders with the subject's tokenizer, the set's own model answers as
  panel reader `subject` (`scripts/ati_qwen_modal.py --subject <key>`), `stage=gate_adapted`
  runs `_gate_panel` with `subject="subject"` (the same all-fail `panel_verdict`, gate
  `adapted-panel-v1`) into `adapted/<m>/anti_text_inversion.json`, which `subset_entry` reads
  under the root (`frozen_path`; bank_sha-guarded like `panel-v2`);
  `ati_panel_judge.sh` judges each family at its prompts.jsonl `layer`. `WSB_BANK_FILE_<FAMILY>`
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
  `tests/test_adapt_judge_overlays.py`. Plan 0072: under the root a result's `+bank-v<N>` tag
  names the ADAPTED header's version (`runner.adapted_bank_stamp`; the registered stamp kept in
  `config.registered_prompt_version`, which both floor matchers accept), and guard (iii) accepts
  an older plan's readouts only through the set's `report.json` `families.<f>.plan_lineage`
  (drop-only re-freezes recorded by `adapt freeze`; dropped ids' cells removed;
  `reads.lineage_drops`, fail-closed; `tests/test_plan_lineage.py`); with no root, through the
  registered bank header's `plan_lineage` instead (plan 0083: arithmetic bank v1 -> v2, the 116
  `frac` items dropped; `gen_arith.RETIRED_VARIANTS` keeps `frac` out of generate / select / freeze).
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
  (the source of truth); do not restate them here. Fourteen families keep their own `judge.py`
  (+ `score.py`): Camila's originals (agentic, jailbreak, jlens_concept_pr, moral, relational,
  role-bound, conjunctive, user_modeling; hallucination left for HallucinationBench, plan 0040),
  directed_modulation, hinted_cutoff, knowledge_cutoff, model_multihop, user_modeling_hard and wrong_intermediate (plan 0050: a blind 6-way MC over B',
  the true bridge B and four same-category distractors frozen in bank v2 by
  `scripts/wrong_intermediate_mc_options.py`; a gold pick is credited only with a verified or
  near-verbatim quote that names it by a listed form, `mc.forms`, in the quote or (a quote cut
  mid-name) where its line continues it or its sample ends inside the gold's name, and that is not
  a prompt echo; no code check overrules the judge's pick (`judge-only-v1`), and the raw
  wrong-vs-true counts are reported only; `true_bridge_rate` replaces the removed
  wrong_bridge_true).
  user_modeling (plan 0056; judge calls `CALL_VERSION = "um-v3.5"`, um-v3.4 plus
  `aliases.NEIGHBOURS` for bank v3's new Country / Occupation golds, data only; bank
  `items_v3.json` = items.json's 47 selfdescribe items (the 53 synthsys items dropped) plus 79
  new gated selfdescribe items, its own 126-row read plan, result stamp `um-v3.5+bank-v3`
  (`judge.instrument`: bank v<N> stamps `+bank-v<N>`)) adds a value gate on top of the shared
  `quote_ok` + `statement_lines`: `mc.form_in` over its frozen lexicon `aliases.py` (an edit
  there bumps its `CALL_VERSION`; `tests/fixtures/user_modeling_gate_cases.json` replays the
  cached gold picks, so rebuild the fixture's `blocked_expected` when the lexicon changes).
  role-bound's summary mode asks each item three times and votes over the draws' pass / fail
  verdicts (`judge.draw_verdict`, stamp `+maj3v`), and so does user_modeling's (a draw passes
  on a gated gold pick with an inferred basis; its full label, `judge.draw_label`, is a
  diagnostic). Both reuse conjunctive's `draw_key` / `majority` / `n_draws`; draw 0 keeps the
  single-call key.
  user_modeling_hard (plan 0106, `umh-v2+bank-v2` since review r3: judge calls `umh-v2`, bank v2; full tier, not in core until its validation is done)
  is a SEPARATE package that imports three pure helpers (`user_modeling.judge.decode_choice`,
  `user_modeling.prompts.render_user_turn` / `option_lines`, conjunctive's draw helpers) and no
  prompt: never thread a family parameter through `user_modeling`, whose files, stamps and
  manifest rows must not move. Items have 1-3 `parts` (one implied trait each); the judge asks
  one identification MC per PART (three draws, keys `<cell key>|p<k>`, `#d<n>`, `|retry1`,
  `|quote`) over options frozen IN THE BANK in bank order (never shuffled at run time), and an
  item passes iff every part passes (one row per item with a tri-state `pass` and a `parts`
  list, so `fast.units`, `decided_outcomes` and the ATI adapter take their default paths).
  No lexicon decides: a pick is verified by `gate.locate` (quote real, in one statement, not
  the user's own words; re-asks, review r2 below) and, for a standing gold pick with an inferred basis, by a
  blind quote check on the statement, shown inside its own readout line (`UMH_QUOTE_*`); basis
  `reply_plan` never passes.
  Review r1: the echo test is `gate.echoes` (a verbatim block OR 80% of the content words are
  the chat's, on the quote, and on its statement for a quote that adds no word of its own);
  every distinct statement holding the quote is a reading (`gate.MAX_STATEMENTS` = 4, keys
  `|quote`, `|quote2`, ...) and the pick stands when ANY reading's quote check returns the
  gold; a malformed quote-check choice is undecided. These are code-side gates, in no call
  fingerprint: changing one needs a stamp bump (review r3 bumped `umh-v1` to `umh-v2` because
  results of three gate versions carried one stamp; never change a gate under a stamp that has
  results, frozen or not).
  The bank's `forms` are NOT a judge lexicon (build lint, capable question, diagnostics only).
  `bank.validate` (V1-V14) is run by the builder (`scripts/build_user_modeling_hard_bank.py`),
  the judge's loader (fail closed) and the bank tests; `min_full_positions` = the header's
  `min_render_tokens` (needs the subject's tokenizer). Every bank edit goes through the
  builder's tables (`DROP`, `DROP_KINDS`, `FORM_DROPS`, `FORM_RULES`, `GOLD_RELABEL`, `OPTION_SWAPS` = a distractor the chat also makes
  true, replaced; `REGUESS` / `REGUESS_SWAPS` = the options-only guess re-run on each changed
  list, guessable at 3 of 5), never by hand in `items.json`, and no user message is ever
  edited. Rebuild without touching `.venv`: `HF_HOME=<cache> HF_HUB_OFFLINE=1 uv run --no-sync
  --with transformers --with jinja2 python scripts/build_user_modeling_hard_bank.py --src
  <bank_candidate.json> --pools <option_pools.json> --out <fresh path>`, copy it over
  `items.json`, then `--check`; then re-declare the manifest-ledger entry and update the counts
  the tests and READMEs pin. Review r2 (2026-11-21, after the first validation run; still
  `umh-v1`): a draw has at most `gate.MAX_REASKS` = 2 re-asks (keys `|retry1`, `|retry2`) for
  any gate in `gate.RETRIED`, which now includes `desc_rejected`; the quote check of an answer
  is keyed by that answer's own key (`<draw key>|retry1|quote`); a statement the quote check
  refused is never read again in the draw, so no path passes without a quote check that
  returned the gold on a statement not yet refused; the prose quote check shows the statement
  inside its own readout line (`QUOTE_CONTEXT`, `Located.context`) and is told that a persona
  the draft calls hypothetical or fictional is still the writer (`QUOTE_PERSONA`); the token
  quote check's text is unchanged, keep it so (a persona clause there primes token lists);
  `gate.states_beyond` exempts from the echo gate a text that says the PICKED value (for the
  gold also the bank's `forms`: the one place the judge's code reads them, never to credit) in
  a word the chat lacks. Mixed-state lists must not hold a feeling the item's OTHER situation
  supports (both parts show the plain label): screen a new mixed item against the whole
  message. Bank v1 after review r2: 149 items, 226 parts.
  Review r3 (2026-11-23; `umh-v2`, bank v2 = 111 items, 159 parts): the kind `life` is removed
  (owner decision; `bank.KINDS` has six, the builder's `DROP_KINDS`), and so are the multi-trait
  items whose life-type part is stated (umh-two-w1035-A keeps the only life-type part, flagged
  for the owner); builder tables `GOLD_RELABEL` (optician -> optometrist), `FORM_RULES` (a
  loose form removed wherever its gold lists it) and the two-letter-code rule; the option seed
  prefix stays `umh-v1` (`bank.STAMP`, a bank property). Judge: `gate.states_beyond` needs the
  form as ONE contiguous phrase and `gate._same_word` is a closed suffix list (no prefix rule);
  `gate.echoes` gates any quote whose STATEMENT is mostly chat; an echoed statement joins the
  draw's refused set (compared on `digest.fold_quote`); `gate.reask_allowed` = at most
  `MAX_REASKS` (2) re-asks, `MAX_REASKS_DESC` (1) of them after `desc_rejected`; every row and
  part carries `pass_first_ask` (a pass obtained after a re-ask counts as a fail) and extras
  `pass_rate_first_ask` / `first_ask`, printed in `breakdown_md`: report it beside the
  headline; `broader_suspect` (now with a `profession` list) and `formless` are flags, never
  gates (measured: a denial kills true passes). The lucky guesser's `question` variant shows
  `judge_label`. `tests/test_user_modeling_hard_bank.py` ties the biography-request count in
  README.md / NOTICE.md to the bank. It has its own `readplan` branch
  (`LITE_SAME_FAMILIES` is plan 0061's constant and stays five), is `NOT_GATED` for ATI and
  `adapt.families.NOT_ADAPTED` (no adapted set carries it), and `wsbench report` prints its
  `extras.breakdown_md` under `## breakdowns` (`cli._breakdowns`; absent key = unchanged output).
  role-bound judges bank v2 (`items_v2.json`, `read_plan_bank` = items.json): `judge.load_items`
  draws option names from items.json's pool, so kept items' calls stay cached, and
  `judge.instrument` stamps `+bank-v2` only for the registered bank (a version-2 header without
  an `adapt` key; adapted banks stay `oa-v3.1`).
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
  items (`evals/model_specific/knowledge_cutoff/obscure_items.json`, none under `WSB_BANK_ROOT`): their prompt is
  rendered from nocot-bench's pinned zip by `wsbench.nocot` at plan time only (judge / run / ATI
  stay offline via `EvalSpec.item_ids`; `WSB_NO_NOCOT=1` drops the nocot rows from the plan); `tests/conftest.py` stubs `nocot.questions` so tests never fetch. Never commit nocot question text or obscure items' real readouts / `cells.jsonl`.
- nyt_connections (plan 0062; judge rule plan 0099, `nyt-mc-2026-11-20`, group model_specific):
  **a candidate needs its connection STATED by a readout line (the label's words or a clear
  paraphrase); a list of words alone is cannot tell**, so the continuation floor now measures how
  often the judge breaks that rule on bare member words (gate at the 0099 re-vet: at most 0.05
  on the 89 stable slots), and every number measured before 2026-11-20 is on the old instrument
  (`nyt-mc-2026-11-02`, which also counted readouts that "group words under" a candidate) and
  not comparable. `DIGEST_TASK_NOTE` and the digest cache keys did not change (digests replay;
  the MC fingerprint keys the stamp and the system text, so old MC rows never answer). **ids-only bank**
  (`evals/logical_processing/nyt_connections/items.json`: puzzle ids, member indices into the shuffled 16, Qwen's
  own labels; every label that folds equal to an NYT group name is a `{role, nyt_group[, nyt_id]}`
  reference). `wsbench.nyt` fetches the pinned Eyefyre mirror (`connections.json`, commit + sha256
  in the header) into `$WSB_CACHE/nyt/` at plan / judge time; `WSB_NO_NYT=1` drops the family's
  plan rows (in `reads._env_key`); `tests/conftest.py` stubs
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
  (`nearquote.close_lines`) verifies like an exact one under `ec-v9` only, summary stamp `+nq1`;
  the earlier multi-label rule survives only as `lucky_guessing.marks_pass`, which scores the
  opt-in bank v5's multi-mark guesser floors; bank v3's lucky floors are the single-pick
  guessers); bank v5 `evals/logical_processing/moral_rationale/items_v5.json` is
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
  neither does registered bank v3 (floor 0.706, the single-pick question guesser under ec-v9;
  0.831 under the earlier multi-mark rule). Decided for the
  freeze (2026-11-01): bank v3 stays the default (lowest bar of v3/v4/v5; cross-bank floors
  table at the top of `evals/logical_processing/moral_rationale/README.md`). The
  read plan stays bank v3's 195 rows for banks v4/v5
  (options are never in the render), so v3 readouts judge v5 with no GPU. Bank v7
  `items_v7.json` (opt-in, `ec-v9-b7`, `scripts/moral_v7.py`): v3's 195 items and golds, all four
  distractors other LLMs' same-side reasons (Opus/Sonnet 5.5, astra, argon harvest), so the side
  readers are at 0; NOT registered: its gold guessers stay far above chance (the gold is Qwen's
  modal reason; floors `evals/baselines/lucky_guessing_moral_v7.json`). Bank v3
  `evals/logical_processing/moral_rationale/items_v3.json` (judged under `ec-v9`; earlier `ec-v5d` = the multi-label
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
  (`WSB_BANK_FILE_MORAL_RATIONALE=evals/logical_processing/moral_rationale/items.json`) = legacy `ec-v3.1` (ec-v3
  with a tool-free system opening). Reads:
  full = every render position (`min_full_positions=6`), lite = the last five. Its ATI entry was
  re-gated under ec-v9 in the 2026-11-04 refreeze (all-fail rule, plan 0071: 56/195). Opt-in bank v4 (`items_v4.json`, 53 gate-passing items, `ec-v9-b4`, `scripts/moral_adversarial.py`).
- association (plan 0039) left the bank judge: bank v2 `evals/association/association/items_v2.json` (93
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
  check, 5-draw scene screen). Its ATI entry (full panel, argon via Gemini WIF, 2026-11-01) keeps
  no item under the all-fail rule (plan 0071), so the family is skipped under the flag.
- buggy_code (plan 0030) is pair-scored on the bank's symmetric `twin` field: headline
  `pair_rate` since 2026-10-30 (metric `pass_rate`, in the macro, `chance` 0.0;
  `specific_pair_rate`, the grade-≥8 bar, in extras; instrument `INSTRUMENT_V1`
  (`buggy-pairs-2026-10-29+infer-r1-2026-10-31+pair-headline-2026-10-30+eof-all-layers-2026-10-30`)
  plus the bank stamp (below), judge calls keyed `JUDGE_PROMPT_VERSION`), `items=` expands to
  pairs, `limit=` counts pairs, `n_items` = pairs in scope; orphans (no twin; every adapted-bank
  item) stay in the per-item extras only. Stage A is 3 votes (keys `...|infer|v1..v3`), Stage B 3
  votes (`...|grade|v1..v3`) only on buggy pair members claiming `bug`; any undecided pair makes
  the run incomplete. ATI NOT_GATED. The registered bank v2 `items_v2.json` = `items.json`'s 63
  items + 40 new gated pairs (143 items, 64 pairs, its own read plan); the stamp is
  `judge.instrument(header)` (`INSTRUMENT_V1` + `+bank-v<N>`; a header without `version`, as in
  `items.json` and the existing adapted banks, has no suffix), the call key unchanged.
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
  `adapt agentic pool=v3 [waves=N]` (plan 0077 §5): waves of an adapt-only pair pool in
  `src/wsbench/adapt/data/` (`scripts/agentic_pool_v3.py`; committed after review, sha-pinned in
  `agentic.POOL_SHA256`, unpinned = refused); shipped pool targets go to the per-set overlay
  `adapted/<m>/agentic_misalignment/targets_v2.json`; `adapt drop` drops whole pairs.
  `pool=v4` = am-pool-v3 CHAINED with am-pool-v4 (`scripts/agentic_pool_v4.py`, ids `amp4-`,
  pins `agentic.POOL4_SHA256`): one Pool, v3 pairs first, so a set's v3 records keep counting
  and v4 waves start after them; the refill block tallies per pool (route `agentic.pool_v4`).
  Once a set holds `amp4-` ids, `pool=v3` and pool-less runs are refused (they would drop them).
  `pool=v5` = v3, v4 then am-pool-v5 chained the same way (`scripts/agentic_pool_v5.py`, a
  reconfigured private instance of the v4 script: ids `amp5-`, pins `agentic.POOL5_SHA256`,
  route `agentic.pool_v5`; ALREADY-USED = registered + v3 + v4 originals); `amp5-` ids refuse
  `pool=v4` / `pool=v3` / pool-less runs. `pinned_pool_version()` = the newest pinned pool; `adapt drop`
  expands an agentic id to its twin against the pool the SET was refilled from (its report's
  `refill.route`, `run._agentic_set_pool`; v3 when none), so an unshipped amp4..7 id finds its twin.
  `pool=v6` (plan 0089) = v3, v4, v5 then am-pool-v6 (`scripts/agentic_pool_v6.py`, a private
  instance of the v5 script reconfigured once more: ids `amp6-`, pins `agentic.POOL6_SHA256`,
  route `agentic.pool_v6`; ALREADY-USED = registered + v3 + v4 + v5 originals); its one change
  is an authoring steer for a calm clean twin (all temptation inside the spans the twin
  replaces), recorded as the pool header's `authoring_steer`; the twin rule, gates, review and
  quotas are v5's. `amp6-` ids refuse `pool=v5` / v4 / v3 / pool-less runs. A twin edit that
  removes two roles at once carries a `roles` list (as merged email blocks do); `role` alone is
  not a complete label (metadata only: no code reads it).
  `pool=v7` (plan 0089) = v3 .. v6 then am-pool-v7 (`scripts/agentic_pool_v7.py`, a private
  instance of the v6 script: ids `amp7-`, pins `agentic.POOL7_SHA256`, route `agentic.pool_v7`,
  ALREADY-USED = registered + v3 .. v6 originals); keeps v6's calm-twin steer and twin rule and
  adds a draft-brief note for more provocative ORIGINALS (a strong, imminent reason; varied
  reasons and act shapes, v6's over-used templates excluded), recorded in `authoring_steer`;
  its build keeps `<work>/shipped_first.json` (the pilot's ids, already rolled out) ahead of the
  `MAX_SHARE` trim. Gotcha: under transformers 5 `apply_chat_template` returns a BatchEncoding,
  so `agentic_pool_v3.chat_tokens` counts `input_ids` of any mapping (before the fix, gate 3
  recorded `length_ratio` 1.0 for every twin; v6 re-measured 0.90-1.09, all within 15%).
- hinted_cutoff (plan 0063) is pair-scored (`items=` expands to pairs,
  `limit=` counts pairs, `n_items` = decided pairs) but its headline is the class DIFFERENCE
  (I flag rate - N flag rate, jailbreak precedent: chance 0, may be negative, in the macro
  unrescaled); `pass_rate_result` builds the row and `dataclasses.replace` swaps in the
  difference and its event-cluster CI. Plan 0064: it reads the PROMPT only (`captured` render;
  the bank ships prompt-only ids, no reply text, no reply span), at the gw prompt span
  (prompt-render tokens, length-equalized, `full_contiguous=False`; hint tokens are never read
  positions). Plan 0074: the registered bank is v2 `items_v2.json` (gw date-matched set,
  metadata pairs only: 118 pairs, `date_matched: false` on obscurity), stamped
  `PROMPT_VERSION = CALL_VERSION + "+bank-v2"` via `judge.instrument(header)`; the call key
  `CALL_VERSION` (`hc-2026-11-04b`) is unchanged, and v1 `items.json` (111 pairs, frozen; in its
  16 authority/sycophancy items the hint lies after the last read position) is judged only via
  `WSB_BANK_FILE_HINTED_CUTOFF` and stamps `CALL_VERSION`. The
  judge is the global-workspace ccut EXIST4 instrument reworded tool-free; quotes go through the
  ported `score.verified_quote`; NOT_GATED, NO_QUESTION, `summ_rare=25`.
  `scripts/hinted_cutoff_replay.py` is the validation gate (byte-equal native renders and the
  frozen prompt-span replay to the bank header's `reference_result_prompt_span`: v2 I 105 / N
  101 over 874 chunks with `--grid`; v1 97 / 87 over 712 with `--oracle`).
  Adapted sets (plan 0084): rebuilt, never copied. `scripts/hinted_cutoff_adapt/` runs the gw
  ccut v2 stages on the subject (`subject_gen.py` = the `[gen]` step on its adapt app;
  `subject_ccut.py` = any ccut stage with the subject's tokenizer, metadata only, optional
  `HC_P_WINDOW` / `HC_SURV` / `HC_GUESS_GAP`; scratch gw cwd only), `finalize.py` writes the
  frozen file with the bar (date checks: day AUROC, cell excess), and `python -m wsbench.adapt
  hinted_cutoff` (`adapt/hinted_cutoff.py`) validates every item against the subject's render and
  installs the bank (header `adapt`, `subject`; built by `build_hinted_cutoff_bank.build(adapt=)`)
  plus its report entry (audited pair drops: `drop_pairs.py`, recorded under `date_leak.audit_drops`). glm-5.3: 41 pairs. The replay script refuses an adapted header.
  Top-ups (plan 0084 § Top-ups): `merge_bank.py --pre` / `--extra` / `--exclude-qid` (no option =
  the plan-0084 merge, byte-identical), `propose_series.py` (densify series, structured low-effort
  Opus calls), `carry_forward.py` (both twins of every pair an earlier audit dropped);
  `subject_ccut.py` wraps a tokenizer without `offset_mapping` in `OffsetTok` (fast tokenizers
  pass through unchanged).
- model_multihop (plan 0076, `mmh-2026-11-06+mmh-forms-v3+bank-v2`, group model_specific, in the macro):
  283 headline items of gw `frozen_v2.json` (invented 255 + cutoff 28), id-keyed (NEVER write
  gw's `name` key: `readplan.bank_file` / `judge_inputs.item_id` switch on it). `captured` render
  (`input_ids`), read = gw `post` (every position after the entity), lite = gw `tail`
  (`last_n` 12). Options frozen in `mc` (`order`, `gold` = the bridge NAME, `forms`, optional
  `exact_case` / `blockers` + `blocker_of`: a blocker hides only the options that list it;
  item flag `answer_names_bridge`, reported as an extras split, never scored), written by `scripts/build_model_multihop_bank.py` from its reviewed
  literal tables (country aliases, cutoff forms); decoys = every item's own gw `foils` (bank v2,
  `+bank-v2` in the stamp; Camila 2026-11-06: the bank-v1 neighbour countries leaked the bridge
  to an options-only guesser, blind 0.546 vs 0.292 on the foils), invented 4-6, cutoff 4 (gw's
  option strings kept verbatim, some lower case). Matcher
  (`judge.option_spans`): wrong_intermediate's `name_spans(glued=False)` per option, untouched,
  plus containment (a span overlapped by another option's or a blocker's span that runs past its
  end, or contains it and is longer, does not count: "Surface Go" in "Surface Go 3", "America"
  in "Latin America"); a verified quote is read in its source line (it must overlap a counted
  span of the pick there and none of another option; a quote cut at its sample's end must sit
  clear of any longer rival / blocker name, and blockers join the prefix check, forms-v3);
  `mc.exact_case` forms: all-capitals ones
  only in capitals, the rest in any spelling that is not all lower case. Summary: one digest
  (task note = the gw TASK line per category) + one blind MC; the bridge needs a verified quote
  naming it and no other option (`judge.form_via`), else `unverified` (a fail). Native = the gw
  v2 summarizer + concept judge (quote void), headline unit "all" (multi-layer) or the single
  layer; NLA / logit need explicit `layers=42` / `layers=63` with a sidecar. CI = cluster bootstrap
  over the bridge. NOT_GATED, NO_QUESTION. `scripts/model_multihop_replay.py` is the validation
  gate (byte-equal renders for s3d / ML-NLA / NLA; the frozen gw counts for all five readers).
  Adapted sets (plan 0078): `python -m wsbench.adapt model_multihop` (`adapt/mmh.py`) re-gates the
  sha-pinned gw mmh pool on the subject; its literal form tables live in
  `evals/model_specific/model_multihop/forms.py` (the build script imports them; the registered bank rebuilds
  byte-identical); freeze selects via `mmh.select_rows` (lucky screen, dedupe, 15% bridge cap,
  `refill.TARGET_OVERRIDE` 100, `SHIP_CAP` 283).
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
  2026-11-04: `multihop_mt_v2` -> `multihop_mt`, the same kind of label change
  (`HASH_FAMILY_NAMES["multihop_mt"] = "multihop_mt_v2"`; banks moved byte-identical, prompt
  bytes and call keys unchanged). `multihop_mt` was the key of the regex-scored family removed
  on 2026-10-30, now `REMOVED_FAMILIES["multihop_mt_regex"]`: `registry.REUSED_FAMILY_KEYS`
  makes a file or directory under the former key `multihop_mt_v2` win over one under
  `multihop_mt` (`registry.lookup_names`: readouts, out dirs, digest stores, adapted sets), and
  `read_results` reads an old `multihop_mt` result whose stamp is not `mh2-mc-...` (or the
  regex diagnostic's `mt-regex-2026-10-30+md+fz`) as `multihop_mt_regex`
  (`tests/test_rename_multihop_mt.py`). Since plan 0101 that family is `multihop`, and the
  reused key of this paragraph is the FORMER key `multihop_mt` (the behaviour is retained).
- **Plan 0101 (2026-11-20): the multi-token families took the plain keys, the single-token ones
  became `<key>_st`, and every family directory moved under its category.** `basic_readout_mt`
  -> `basic_readout`, `multihop_mt` -> `multihop`, `multilingual_mt` -> `multilingual`, `typo_mt`
  -> `typo`; the former `basic_readout` / `multihop` / `multilingual` / `typo` ->
  `<key>_st`. No instrument moved: `scripts/manifest_0101.py --check
  tests/golden/manifest_0101_pre.json` rebuilds every hash, seed, option order, prompt sha, call
  key and cache fingerprint of all 32 families and compares them with the manifest recorded on
  main before the rename (run it after any change to `registry.py`'s tables). The golden and the
  script are never regenerated. Since then T1 (`tests/test_rename_0101.py`; the rule is `verdict` in
  `scripts/manifest_0101_declare.py`) guarantees that **every family's manifest rows equal the
  golden's or the state declared for it in the ledger `tests/golden/manifest_0101_declared.json`**
  (`{prompt_version, bank_file, bank_sha256, rows_sha256, plan, note}` per family): a family that
  differs from the golden, or is new, needs an entry whose stamp, bank and row hash equal the
  tree's, and the stamp or bank must differ from the golden's ("instrument moved without a stamp
  or bank change" otherwise). A stamp-only declaration waives `stamps` and `run` alone (plan_sha,
  file shas, seeds, option lists, tables and lens-store rows must still equal the golden's); a
  new bank is covered by the ledger hash. Sections outside `families` (shared digest prompts,
  the F4 record) never move without editing the check. So a deliberate judge or bank change =
  bump the stamp or bank version, then `python scripts/manifest_0101_declare.py <family> --plan
  <NNNN> --note '...' --write` (it refuses without a bump); a later edit of a declared family
  needs another bump and another entry. Fast versions cut after the golden
  (`manifest_0101_declare.new_fast_rows`): a family's `plan.fast_plan_sha` row for a version
  the golden has for no family is set aside, before the comparison and the ledger hash, when
  it is the family's row under a golden version (directly, or recomputed under that version's
  name for the two position-reduced families, `fast_equivalents`); any other new row fails
  ("its fast plan moved") unless the family is declared with a new bank. So cutting a fast
  version needs no entry from the families it leaves alone and stales no earlier entry.
  A family the golden does NOT have (a new family, plan 0106) has no golden row to compare a
  new fast row with, so its `plan.fast_plan_sha` rows are left out of what its entry compares
  and hashes (`manifest_0101_declare.without_fast`, `g is None` only; its `plan_sha` row stays
  in): a fast version cut after its declaration does not stale the entry.
  `scripts/manifest_0101.py` is the golden's script plus ONE `try` in `plan_entry` (a family
  whose bank changed after an older fast version was frozen made `fast.entry` exit the whole
  manifest; that row now reads `unavailable`); T1 pins the sha of the script that made
  the golden, the sha of the script now and the golden's bytes.
  - **Two frozen names, never interchangeable.** `registry.hash_name(key)`
    (`HASH_FAMILY_NAMES`) is what `plan_sha`, the ATI `bank_sha` and the lucky-guessing seeds
    hash: the key of the family's FIRST hashed life (`multihop` -> `multihop_mt_v2`,
    `basic_readout` -> `basic_readout_mt`, `multihop_st` -> `multihop`, ...).
    `registry.frozen_name(key)` (`FROZEN_KEY_NAMES`) is the key on main just before plan 0101
    (`multihop` -> `multihop_mt`): the sites that embedded the key itself use it (the dev split
    `split.is_dev`, `mcjudge_bank.options_of`'s shuffle, `options.r4_language_distractors`, the
    `capable` / `adapt` (`generate`, `author`, `onecue`) seeds and cache keys, builder call keys
    in `scripts/`). Both are opaque hash inputs applied once to a CURRENT key, never
    a lookup key or a file name; only `registry.py` reads the two tables (T9). A new
    name-embedding site picks the one its stored data was written with, and the manifest check
    says whether it picked right.
  - **Stored keys are translated at load, never rewritten in frozen files.**
    `registry.PRE_0101_KEYS` / `from_pre_0101` / `rekey_pre_0101`: `evals/fast/*.json`
    (`fast.subset`), `tests/golden/*`, `tests/fixtures/*` keep their pre-0101 keys and bytes
    by design. Bank headers keep the source repo's vocabulary (`"multihop-hard"` = the
    multi-token bank, `"multihop"` = the single-token one) and are how a bank is recognised.
  - **The four plain keys are reused keys** (`registry.REUSED_FAMILY_KEYS`, one `Reused` record
    each with both members' stamp prefixes and headers). Anything stored under a plain key is
    attributed by CONTENT, never by name, and a file of the other member is refused
    (`registry.RenamedKey`, exit 2), never judged or reported under the wrong family:
    `registry.owner(key, stamp=, header=, ids=, plan_sha=)` is the one decision;
    `stored_family(key, stamp, ids)` for a `results.json` (`results.read_results`, an empty or
    ambiguous stamp falls back to the rows' ids); `reads.owner_of` / `reads.load` for a
    readouts file (sidecar `plan_sha`, else ids; a mixed file is refused);
    `runner.readouts_choice` picks `<key>.jsonl` vs `<key>_st.jsonl` vs the pre-0101 names
    under a `readouts_root`; `registry.root_bank` / `bank_pin` for `WSB_BANK_ROOT` and
    `WSB_BANK_FILE_*` (by header); `registry.dir_family` / `file_family` for anything that walks
    a run tree (both viewers); `stale_floor_key` for a floors file written before the rename;
    `adapt.store.report_key` / `report_entry` for a set's `report.json`. These guards are
    permanent. New code that reads a per-family file, directory or dict entry under a plain
    key goes through one of them.
  - **The stderr notice.** Typing one of the four plain keys prints one line per key per
    process (`registry.swap_notice`, from `cli._family` and `adapt.__main__`): `note: 'multihop'
    is the multi-token family since 2026-11-20 (was multihop_mt); the single-token family is
    'multihop_st'`. Off under `WSB_NO_RENAME_NOTICE=1` and for `outcome=` child processes.
    `registry.SWAP_NOTICE`, that branch and its test (T8) are deleted at the next version tag;
    the guards above stay.
  - **Adapted sets: marker and write fence.** A set in today's keys carries
    `report.json["family_keys"] == "0101"` (`adapt.store.SET_MARKER`; written by
    `scripts/migrate_0101.py set` and, for a set created after the rename, by
    `store.update_report`). `store.require_migrated` refuses every report WRITE into a set
    that still shows pre-0101 keys (`pre_0101_evidence`: an `_mt` report entry or file, or a
    plain-key bank with a single-token header); reads of such a set work as they are.
    `migrate_0101.py set <dir> [--apply]` migrates a set or a lens store subject outside git,
    by content, and refuses a marked set and a set with no pre-0101 evidence.
    `drops_v1_archived` / `patches_v1_archived` in six reports keep old keys (no reader).
  - **Paths.** A family's data lives in `evals/<category>/<family>/` and its code in
    `wsbench.evals.<category>.<family>`. **No code builds a family path or module name by
    hand**: `registry.family_root(f)` / `family_rel(f)` / `resource_path(f, name)` for data,
    `family_module(f, sub)` / `family_packages()` for code, `category_of(f)` for the category
    (read from the package tree, `registry._layout`; `register` checks `spec.group` against it).
    `registry.repo_path(rel)` resolves a pre-0101 path string frozen inside data (introspection's
    stored vector paths, which are hash inputs and stay as written) and is for nothing else.
    `association` is both a category directory and a family, which sits in that category since
    plan 0107: `evals/association/association` (under `basic/` from 0101 to 0107).
  - **The migration script** (`scripts/migrate_0101.py`): `apply` produced commit 4 from the
    tag `pre-0101-migration`; `scripts/migrate_0101_applied.json` records its base commit and
    tree. `check` is the full gate only at that tree; anywhere else it checks the data half
    (every data file of the base at its new path with its bytes, JSON files as exact key
    translations) and says that the KEEP comparison was recorded at apply.
  - Published artefacts keyed by family (the adapted sets on HF, viewer exports,
    HallucinationBench's WSB method names) are NOT renamed; the README carries the key table.
  - Tests: `tests/test_rename_0101.py` (T1-T17), `test_rename_machinery_0101.py`,
    `test_rename_fixups_0101.py`, `test_family_paths.py`, `test_migrate_0101.py`.
- **Plan 0105 (2026-11-21): the category `precision` ("Precision") is `jlens_comparison`
  ("J-lens comparison").** Directories `evals/jlens_comparison/` and
  `src/wsbench/evals/jlens_comparison/` (`git mv`, bytes unchanged); the family key
  `jlens_concept_pr` and its METRIC name `precision` did not change, so "precision" in code and
  prose now always means the metric. Renaming a category = the `CATEGORIES` key, the directory
  pair, the family's `group=`, `registry.LEGACY_CATEGORIES` (old -> new; `repo_path` resolves a
  stored `evals/<old>/<family>/...` string, none exists in the repo today),
  `scripts/migrate_0101.py`'s `CATEGORY` + `LATER_MOVES` (its `check` composes the later move
  onto the frozen `migrate_0101_applied.json`), and the manifest ledger: the manifest holds no
  family path, so the ONLY row that moves is `list.category`, which T1 accepts under the
  golden's own stamp and bank when the rename is listed in
  `manifest_0101_declare.CATEGORY_RENAMES` and a ledger entry pins the rows (any other row
  moving without a bump still fails). No CLI key takes a category, so there is no alias.
- **Plan 0107 (2026-11-21): the family `association` moved from the category `basic` to the
  category `association`.** Directories `evals/association/association/` and
  `src/wsbench/evals/association/association/` (`git mv`, data bytes unchanged), `group=
  "association"`; location only: no stamp, bank, prompt, `plan_sha`, cache key, floor, ATI entry,
  fast subset or tier moved, and no macro changes (none is per category). Moving ONE family to
  another category = the directory pair, its `group=`, `registry.LEGACY_FAMILY_CATEGORIES`
  (family -> the category it left; `repo_path` resolves a stored `evals/<left>/<family>/...`
  string and `_moved_hint` names the new place for a missing `WSB_BANK_FILE_*`),
  `scripts/migrate_0101.py`'s `LATER_MOVES` (NOT its `CATEGORY`, which
  stays the layout `apply` made: the script's tests replay it; `path_today` applies a later
  move only to a file that is no longer at its applied path; `tests/test_migrate_0101.py` has
  the `moved_since` table), and the manifest ledger: the only row that moves is
  `list.category`, which T1 accepts under the golden's own stamp and bank for a family listed
  in `manifest_0101_declare.CATEGORY_MOVES` (`family -> (old, new)`; that family, that row and
  that pair only) with a ledger entry. `repo_path` order matters for this key: a path of
  today's layout (`evals/association/<family of that category>/...`, the family itself
  included) is taken as written BEFORE the pre-0101 reading `evals/association/<rest>` ->
  `evals/association/association/<rest>`. The shared bank-judge package `wsbench/basic/` and
  "the basic families" of the judge-layer notes above are about the judge, not the category.
- `EvalSpec.superseded_by="<successor>"` retires a family without deleting it (plan 0015;
  today `typo_st` -> `typo`, plan 0033; its first user, the regex-scored family then keyed `multihop_mt` -> `multihop_mt_v2`, was
  removed on 2026-10-30, plan 0041; a family built by a shared factory sets it with
  `dataclasses.replace(factory(...), superseded_by=...)`): `results.macro` excludes it (reason
  `superseded`) and every `all` default skips it via `registry.drop_superseded`; it stays
  runnable by explicit name (`run` also takes `include_superseded=True`).
- Deleted families: `registry.REMOVED_FAMILIES` (today `ttt` / `ttt_move`, removed 2026-10-26 by
  plan 0017 as too close to next-token prediction, `brew_intermediates`, retired 2026-10-29
  by plan 0029 because the prompt alone solves it, `wrong_bridge_true`, removed 2026-10-30 by
  plan 0050: not part of the benchmark, its signal is wrong_intermediate's `true_bridge_rate`,
  `hallucination`, replaced 2026-10-30 by HallucinationBench, plan 0040, and `multihop_mt_regex`,
  removed 2026-10-30 by plan 0041 as superseded by the multi-token multihop family (`multihop` today), and `medical_diagnosis` /
  `medical_diagnosis_alt`, removed 2026-10-31 by Camila, plan 0058, and `unverbalized_hint`,
  retired 2026-10-31 by plan 0058 and removed 2026-11-07 by Camila, plan 0081, as outdated) are
  gone from the code, banks and ATI file;
  `results.macro` excludes a stale `results.json` of theirs in an old run dir (reason `removed`).
- Retired families (reversible): `registry.RETIRED_FAMILIES` (empty since plan 0081 removed
  `unverbalized_hint`, its only user; the mechanism stays, its tests retire a monkeypatched
  stand-in, plan 0058). Package, bank, tests and floors stay and the family is
  registered and runnable by name, but `drop_superseded` (what `all` means) skips it, the macro
  excludes it (reason `retired`), and it has no README family entry / Judges row / ATI
  `_not_gated` line. Restore = delete the dict entry and re-add those three (plan 0058 lists them).
- HallucinationBench index (plan 0040): `wsbench.hbindex` reads the frozen vendored
  `evals/hallucinationbench/index.json` (hindex-v8 at one HB sha, plans 0040 + 0057 + 0080; joint
  11-layer rows kept apart under `joint`, never per-layer rows; `final-olens-rl600-x4` is
  `not_measured` on v8; written ONLY by
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

- Fast subset (plans 0090 / 0094 / 0095, `--fast` = `fast=True` on plan / produce / judge / run /
  report): `fast.py` reads the frozen `evals/fast/fast_v3.json` (`fast.VERSION = "fast-v3"` since 2026-11-20, `fast_v2.json` before, the same items: 22
  families, 1,823 units, 2,160 read items; per family `bank_sha`, `units` by group, `read_ids`,
  optional `positions`; never regenerate or reorder a frozen file, a new subset is a new
  versioned file in `fast.VERSIONS`) and holds
  `entry` (`NotInFast` = skipped, like ATI's `NotInScope`), `units` (per-unit outcomes of a
  SUMMARY-mode result, one rule per special-cased family) and `rescore`. The flag reaches the
  families only as `JudgeArgs.scope == fast.SCOPE` with `items` = the entry's `read_ids` (never
  an `opts=` key: `opts=fast=1` does nothing); `reads.load` restricts the cells and narrows a
  position-reduced family (the two safety families; `readplan.is_fast_site` on DECODED token text, the producer's
  own predicate; `fast_of` / `punct_special` rules); `runner.stamp_fast` rescores and stamps
  `config.scope` / `fast_subset` and the `+fast-<kind>` suffix; `mcjudge.is_subset` treats the
  scope as a defined variant; `results.macro` and `report` never mix fast and non-fast rows.
  Invariants: the strict ATI subset (`ati-subset-v2`) is contained whole; `bank_sha` (sha256 of
  the registered bank file's bytes, not the ATI plan-row fingerprint) fails closed, as do
  `WSB_BANK_ROOT` / `WSB_BANK_FILE_*`; **the non-fast paths are untouched** (plan rows,
  `plan_sha`, result stamps, cache keys: `tests/golden/plan_sha_pre_0090.json` pins the plans);
  judge prompts and call versions do not move under fast. A FAST file's sidecar declares
  `"fast": "fast-v2"` with the fast plan's own `plan_sha` (`reads.fast_plan_sha`).
  Plan 0094: fast-v2 = fast-v1 (`fast_v1.json`, 24 families, kept frozen and sha-pinned) minus
  jailbreak_recognition and agentic_misalignment, every other entry identical. `fast.subset()`
  resolves `fast.VERSION` at call time (there is no `fast.PATH`; tests patch `VERSION` only, the
  loader is cached per version); `fast.COMPATIBLE` (widened by plan 0095, per family since 2026-11-20, both below): a sidecar declaring a
  compatible version is judged (`reads.load`), and a compatible result row of a family in the
  current subset stays in the macro (`results._stale_fast_subset`), so a fast-v1 results dir
  reports a fast-v2 macro over its 22 rows with its jailbreak / agentic rows excluded (`stale
  fast subset (fast-v1)`); the two families are `NotInFast` under `--fast` (a fast run of
  them is `--fast-safety`). The position-reduction machinery (`fast_of` /
  `punct_special` / `is_fast_site`, `reads.fast_narrow`, `fast.position_stamp`, the
  `+fast-<kind>` suffix) is live under `--fast-safety` and for the frozen v1 file (no fast-v2
  entry has `positions`).
  Plan 0095: `--fast-safety` = `fast=safety` runs `fast-safety-v1` (`fast_safety_v1.json` =
  `fast_v1.json` with another `version`: 24 families, 1,996 units, 2,351 read items).
  `fast.DEFAULT = "fast-v2"`; `fast.VERSION` is the ACTIVE subset of the process (`DEFAULT`
  unless `fast.select(variant)` changed it, the only writer outside tests; `tests/conftest.py`
  resets it around every test); `fast.VARIANTS = {"": "fast-v2", "safety": "fast-safety-v1"}`
  are the CLI-selectable ones. The CLI normalises `fast` to a bool plus `fast_variant`
  (`cli._set_fast`; `fast_variant=` is not a key) and calls `select` at the top of `execute`
  only for a non-empty variant, never in `finalize`; plain `--fast` writes nothing and runs the
  active subset. `fast.COMPATIBLE = {"fast-v1", "fast-v2", "fast-safety-v1"}` (plan 0095's set, replaced on 2026-11-20, next paragraph) meant MUTUALLY
  entry-compatible (any two versions hold the identical entry for every family in both; a
  test pins it); the sidecar and macro rules keep their form, so under `--fast` a
  fast-safety-v1 row of the 22 is in the macro and a safety family's row is `stale fast subset
  (<v>)`. `reads.fast_plan_sha(family, declared=)` gives the sha the declared version's own plan
  had (the two reduced families' rows hash `extra.fast`), which the `plan_sha` guard compares;
  a FAST file whose declared version does not hold the family is refused. `runner.judge_argv`
  emits `fast=safety` by reverse lookup of the active version in `VARIANTS` (else `fast=True`),
  so a process-mode child selects the subset itself. `report` without `fast=safety` is the
  active (fast-v2) view; `cli.fast_header(results)` adds a second line counting the rows that
  are in another selectable subset only.
  2026-11-20 (comp-v6 on bank v6): `fast.DEFAULT = "fast-v3"`, `fast.VARIANTS = {"": "fast-v3",
  "safety": "fast-safety-v2"}`. The two files are `fast_v2.json` / `fast_safety_v1.json` with
  ONLY conjunctive_association's `bank_sha` moved (same units and read ids), written in today's
  keys (`KEY_ERA` "0101") by `scripts/fast_refreeze_bank.py`; the three older files stay frozen.
  **`fast.COMPATIBLE` is gone: compatibility is per family**, `fast.compatible(version, family,
  against=None)` = both files hold the family with the identical entry (read at
  `results._stale_fast_subset`, `reads.load`, `reads.fast_plan_sha(declared=)`,
  `cli.fast_header`), which is what the set stated for whole files, so every sentence above
  about a "compatible" version still holds for every family except conjunctive_association:
  its fast-v1 / fast-v2 / fast-safety-v1 RESULT rows are `stale fast subset (<v>)` and under one
  of them `fast.entry` fails closed. A READOUTS file is held to `fast.same_reads` instead (the
  declared version reads the family's same `read_ids` at the same `positions`; `bank_sha` and
  units not compared; the declared `plan_sha` still checked in `reads.load`), so the family's
  old FAST files are judged as they are: a new option list does not change what was read. Never `functools.cache` `compatible` (it reads `fast.VERSION`).
  The next bank change that keeps a family's ids is the same script plus the pins it names
  (`REFROZEN` in `tests/test_fast_subset.py`; `evals/fast/README.md` "Re-freezing") and the
  family's entry in the manifest ledger (`manifest_0101_declare.py`, the plan 0101 paragraph).
  **Plan 0104 (2026-11-21): `fast.DEFAULT = "fast-v4"`, a seeded random half of core; every
  sentence above describes the frozen predecessors.** `evals/fast/fast_v4.json` is cut by
  `scripts/fast_cut_core_half.py --version fast-v4 --seed 20261121 [--check]` from the
  registered banks and read plans alone (deterministic, refuses an existing target; offline
  with a warm `$WSB_CACHE`, since two plans render from pinned sources):
  families = `tiers.CORE` minus jailbreak_recognition and agentic_misalignment (16); per family
  `n_total = max(ceil(n / 2), n_ati)` units = every strict-ATI id (`ati-subset-v2`, whole: the
  one exception to "random") plus `random.Random(f"{seed}|{registry.frozen_name(f)}")`
  samples of the other units (NO version in the stream key), split over the family's strata in
  proportion to each stratum's NON-ATI units by largest remainder, not half of each stratum (`UNITS`
  holds each family's unit, read rows and stratum; `cut` in the file records the counts);
  full positions everywhere. 1,203 units, 1,441 read items. A strict-ATI family outside the
  family list is refused by the cut. The ATI units bias an ATI family's fast value toward
  them (README). `fast.VARIANTS = {"": "fast-v4"}`: **`--fast-safety` / `fast=safety` is
  retired** (`fast.RETIRED_VARIANTS`: `cli._fast_arg` and `fast.select` raise a usage error
  with what to run instead); the older files stay registered, and `report fast_version=<v>`
  (`fast.use`) reports an old fast directory under the version that made it
  (`cli.fast_header` names the key per stale version). Older rows are all stale under fast-v4
  and older FAST files read other items (refused); full files are always valid inputs.
  `tests/test_fast_core_half.py` pins the file's sha256 and per-family counts;
  `tests/test_fast_subset.py` runs on fast-v3 through an autouse fixture (plain `--fast` runs
  the ACTIVE subset in-process; a process-mode child always gets `fast=True` = the default).
  Re-cut = the next version with the same seed: a family's draw depends only on the seed, its
  pre-0101 name and its own units / strata / ATI ids, so a family whose bank did not change
  keeps its entry byte-identical in the next version (its fast rows stay valid by
  `fast.compatible`; the test simulates a fast-v5 re-cut). **`report --fast
  anti_text_inversion=True`** is the strict-ATI view of a fast run (`fast.ati_view`: the fast
  units restricted to the gated ids, then `results.macro`'s ATI rules; no judging, no file
  written; a usage error without `--fast`). It equals a real ATI run's family value over the
  same readouts; its CI is the fast unit bootstrap. `STRICTER_PASS_FIELD` / `GATE_ANY_BASIS`
  are gate-time panel rules and play no part in it. Plan 0104's open point: the measured,
  NOT adopted alternative (value on a random half of all units, ATI ids read besides). Manifest T1: a re-selected version's fast rows are set aside
  (`reselected`, `fast.same_reads`; their shas are pinned in `tests/test_fast_core_half.py`,
  `V4_FAST_PLAN_SHA`), and **a tier move is declared by listing it** in
  `manifest_0101_declare.TIER_MOVES` (`family -> (tier before, tier today)`; today
  conjunctive_association full -> core): that family's `list.tier` / `tiers.CORE` rows are read
  as before the move, ahead of the comparison and the ledger hash (`tier_moved`), so the move
  needs no ledger entry and stales none, also for a family registered after the golden. Any
  unlisted tier or core-list change fails T1 like any other row; the golden is never
  regenerated and the ledger is written only by `manifest_0101_declare.py ... --write`.
  The cut reads ATI ids through `text_inversion.subset_entry` (stale entry = exit) and refuses
  `WSB_BANK_ROOT`, a `WSB_BANK_FILE_*` pin of its families, `WSB_NO_NYT` and `WSB_NO_NOCOT`.
  `run --fast` in process mode exits when `fast.VERSION` is not a selectable version (a child
  judges `fast.DEFAULT`); `fast.ati_view` raises on a non-fast row. Viewer
  (`viewer/ingest/wsb.py`): a fast run is stored under `fast` only when every row is the
  default version's (or `fast.compatible` with it), else under its stamped version name
  (`query.subset_title` titles it); the ingest signature holds `fast.DEFAULT`; `fast`
  membership is deleted before the frozen file's is written; a fast run's membership is per
  family from each row's own stamp (`fast_members`), none for an unstamped row.

- Summary mode (`aggregate=summary`, plan 0020, `digest.py`) is the benchmark DEFAULT since plan
  0024: `runner.parse_opts` fills `aggregate=summary` in unless `opts=aggregate=native`; a family
  called directly with a hand-built `JudgeArgs` (no `aggregate`) keeps its native rule. Tests
  that mean native pass `opts=aggregate=native`. Scripts that re-score native caches or feed the
  ATI gate pin native explicitly (`scripts/ati_panel_judge.sh`, `scripts/cache_only_run.py`,
  `scripts/adapt_gated_rescore.py`, `adapt/floors.py`); `text_inversion.draw_verdicts` refuses summary
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
  "Per-layer digests, counts and refusals"): a multi-layer item is digested per layer and merged (`summ_layers=union`, so
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

## Tiers and categories (plan 0098)
- `tiers.py` (imports `registry` and `fast` only; `registry` never imports it): `TIERS = ("fast",
  "core", "full")`, `DEFAULT = "core"`, `CORE` (18 families: conjunctive_association joined on 2026-11-21, Camila; the registered
  `user_modeling` bank is NOT core; `user_modeling_hard`, plan 0106, is registered in full and
  joins `CORE` as the 19th once its validation is done: plan 0106 commit 5, with the fast cut
  and the final ledger entry),
  `core()` / `full()` / `families(tier)`, `tier_of(name)` (`core` | `full` | `""`), `check()`
  (every `CORE` key registered, not superseded / retired / `not_in_macro`; its static part runs
  at import). `full()` is `registry.drop_superseded(sorted(FAMILIES))`, what `all=True` runs.
- CLI: `--core` / `--full` are argv rewrites to `tier=core|full` on `run` and `plan` only
  (`cli._tier_arg`; `tier=fast` is refused, the fast tier is `--fast`; a tier flag with
  `families=`, with `--fast`, or `--core` with `all=True` is a usage error). **A bare `run` or
  `plan` is the core tier** (it was a usage error / every family before); `run all=True` and
  `--full` are the full tier, bare `run --fast` is `--fast all=True`, and **`families=all` still
  means every family in every command** (`Plan.families` defaults to `None`, not `"all"`; the
  other commands' `families=all` defaults are untouched). `include_superseded` applies to full
  only. `run.json` gets `"tier"` only when a tier flag or the bare default picked the families:
  never under `families=`, nor for an explicit `all=True` without a tier flag (the manifest
  key-set tests pin that spelling). Child judge processes get no tier.
- `results.core_macro(results)`: `None` when any row has a `config.scope`; else `macro`'s
  run-level context over ALL rows (`_macro_context`, the same guards raise) and the same per-row
  rule (`_row_exclusion`, the elif order of `macro`) over the rows whose family is in
  `tiers.CORE`; `macro`'s keys plus `tier`, `n_core`, `missing`, `complete`. `results.macro` is
  unchanged. `markdown_table(core_macro=)` adds the `**core macro**` row after the macro row and
  a `Core macro: missing: ... excluded: ...` line after the "Not in macro:" list, only when the
  dict has an averaged family; without the keyword the table is byte-identical. `report` prints
  a `core macro:` line and (`json=True`) `"core_macro"` under that same condition, plus
  per-family `category` / `tier`; `run json=True` always carries `"core_macro"`.
- Categories: `EvalSpec.group` is a key of `registry.CATEGORIES` (key -> README title: basic,
  computational, association, safety, anti_bag_of_features, logical_processing, model_specific,
  jlens_comparison, which was `precision` until plan 0105: `registry.LEGACY_CATEGORIES`; the family
  `association` is in `association`, not `basic`, since plan 0107: `registry.LEGACY_FAMILY_CATEGORIES`); `basic_mt` and `bag_of_words` are gone. `wsbench list` shows it as `category`,
  with a `tier` column after it (`—` for a superseded or retired family). The viewer takes its
  group headings from `docs/evals.md`. `tests/test_tiers.py` pins the family
  -> category map and the tier lists.

## Driver (`runner.py`, `cli.py`)
- `run [--core|--full|all=True|families=a,b] readouts_root=DIR out=DIR [family_workers=8] [json=True]` reads
  `DIR/<family>.jsonl` (missing -> `skipped`). Order: parse `opts=` once (bad pair = one exit
  2), resolve every judge once, preflight each distinct judge model once (not aux; skipped
  under `dry_run=True`; failure = exit 3 before any thread), then judge in a `ThreadPoolExecutor`
  (each worker runs the family in-process, or in process mode waits for its child, below)
  (`min(n, family_workers)`, every family at once when `family_workers <= 0`, 1 under
  `dry_run=True`) under the shared pacer. Fail-soft per
  family: `JudgeConfigError` -> failed/3, `SystemExit` -> failed/2 (text `e.code` or `exit N`),
  listed under "## skipped / failed" in `summary.md`; other exceptions propagate. Exit 130 on
  `KeyboardInterrupt` (unstarted families cancelled, in-flight ones finish their batch), else
  3 > 2 > 0. Writes `summary.md` + `run.json` = `{started, finished, families: {name: {status,
  error?, results_path, value, complete, pinned_instrument, spend_usd, n_calls?}},
  judge_overrides: {flag, env}, readouts_root}`.
- Plan 0092 (throughput; nothing here is in a fingerprint, `prompt_version` or `plan_sha`):
  `JudgeOptions` defaults `concurrency=256`, `rpm=30000`, `itpm=60_000_000` (`judge` and `run`;
  `baseline` / `capable` / `text-inversion` keep theirs), `WSB_SLOTS=<dir>:<n>` (`llm._slot`: an flock slot per API attempt, a cap on calls in flight across processes; unset = off), `RunFamilies.family_workers=8` (0 = every family at once).
  `JudgeOptions._prepare` (called in `execute`, never `finalize`) applies `llm.set_itpm` and
  raises the soft `RLIMIT_NOFILE`. `llm._TOKEN_PACER` is a second process-wide pacer:
  `_pace_tokens(chars // 3)` once per `_one` / `_one_text` call, before the retry loop (a refusal
  re-run reserves again); off (0) as the library default, and `tests/conftest.py` resets it.
  `_pace(rpm)` keeps its one-argument signature (tests replace it). `digest.FAMILY_DEFAULTS` has
  no `summ_concurrency` entry any more (agentic 4, jailbreak 8 removed; their timeout / fallback /
  `summ_max` / `summ_rare` stay). `run wait=SECONDS [settle=SECONDS]`: a family whose readouts are
  not ready (`runner.readouts_ready`: file + a sidecar that parses as an object and is not older
  than the file; `settle` admits an old sidecar-less file) is pending, re-checked every
  `runner.POLL` s, submitted when ready (`<family>: readouts landed after <t>s`, `waited_s` in
  `run.json`), and skipped when the wait ends (deadline, or `readouts_root/_READS_DONE`);
  preflight covers pending families before the first submit; `wait=0` is the pre-0092 path;
  refused with `dry_run=True` / `layers=each`. `readouts.write_sidecar` is atomic and
  `Producer.run_family` deletes a stale sidecar before appending. §2b: `runner.judge_family`
  wraps `spec.run` in `llm.error_tally()` (a context variable, so no `Spend` crosses the family
  boundary) and prints `<family>: N judge call(s) failed after retries; ...` on stderr; the
  completeness rule is unchanged (a per-layer digest lost to a failed call still leaves a
  possibly-complete row).
- Plan 0092 §5, process mode: `run` judges one `wsbench judge` child per family
  (`RunFamilies.procs`, tri-state: the key, else `WSB_RUN_PROCS` 0 / 1, else ON; forced off in
  `finalize` under `dry_run=True` / `layers=each`). `runner.run_families` uses it only when
  `getattr(args, "procs", False)` AND its `env` parameter is None, so hand-built namespaces and
  callers passing `env=` keep threads, and `tests/conftest.py` sets `WSB_RUN_PROCS=0` (tests
  register families in-process; `tests/test_run_procs.py` fakes the seam `runner._spawn`). The
  same thread pool submits `runner._one_proc` instead of `_one`; fast membership, the readiness
  check, the ATI scope check and `_seed_preflights` stay in the parent, and each child preflights
  again. Child = `runner.judge_argv` (never the run-only keys) with the parent's environment plus
  `PYTHONUNBUFFERED`, `WSB_SLOTS` and `WSB_PACER` (the parent never mutates `os.environ`), its own
  session, `PR_SET_PDEATHSIG` set by the child (`runner.die_with_parent`). `judge outcome=PATH`
  runs `runner._one` (which then parses `opts=` and resolves the judge inside the fail-soft
  rule), writes `{family, status, error, exit_code}` atomically and exits with that code; the
  parent deletes a stale `<dest>/outcome.json`, reads and deletes the new one, and loads
  `read_results(dest)` for an ok family. No outcome file: exit 2 / 3 or a signal = that family
  failed (signal -> exit code 2); any other exit terminates the other children and raises.
  Budgets: `runner._Procs` makes a `tempfile.mkdtemp(prefix="wsb-run-")` directory (never under
  `out`), probes `flock` there (failure = exit 3) and removes it in the `finally`;
  `WSB_SLOTS=<tmp>/slots:<runner.RUN_SLOTS = 1500>` unless one is inherited; `WSB_PACER=<tmp>/pacer`
  makes `llm._Pacer` / `_TokenPacer` keep `next` in one file each (`rpm`, `itpm`; thread lock +
  exclusive `flock`, `pread` / `pwrite`, a torn file reads as 0; clock `llm._now`), in-memory
  without the variable. Interrupts: first Ctrl-C = no new spawn, wait, 130; second = `killpg` the
  children, `skipped ("interrupted")`; SIGTERM / SIGHUP handlers (installed for the run) raise
  `SystemExit(128 + signum)` through the same `finally`. `run.json` gains no key.
- `report dir=DIR [json=True]`: table with `(lower is better)`, `n (k no readouts)`, macro row (in-row
  `excluded:` + "Not in macro:" footnotes); rewrites `summary.md`. Exit 2 = not a directory /
  unreadable results.

## Results contract (`results.py`)
`docs/results_contract.md` is the single statement (schema, `complete`, the macro row); `results.py`
implements it. Not restated here.

## Invariants
- Every judge prompt lives in the family's `prompts.py` (`PROMPTS`; `{name}` placeholders
  rendered by `str.replace`, never `str.format`) AND verbatim in a fenced block of the family
  README under "Judge prompts";
  `tests/test_prompts_in_readme.py` asserts equality. Bump `prompt_version` on any edit.
- Failures never score; they are counted. Frozen banks are never edited in place. `spec.run`
  returns a `FamilyResult` and writes nothing. `counts` has a fixed key set (other tallies go
  in `extras`); no `Spend` crosses the family boundary. Cache rows are append-only.
- README: each family entry is `**<spec.title>** — [link]` (the link is
  `evals/<category>/<family>/README.md`, built from `registry.family_rel`; `tests/test_readme.py`)
  followed by exactly three lines
  `- *What it is:*` / `- *Example:*` / `- *Judged by:*`, grouped by category (`registry.CATEGORIES`, in its order: Basic (adapted from the J-lens paper) ·
  Computational · Association · Safety · Anti-bag-of-features · Logical processing ·
  Model-specific · J-lens comparison (not in any macro)), a core family's entry tagged `core` after its
  README link. Credits live in README §Credits and NOTICE.md, one
  bullet per external source; in-house families get no credit line.
- Family paths and module names come from the registry helpers (`family_root`, `family_rel`,
  `resource_path`, `family_module`), never from string building; every path written in a doc or
  test must exist (`tests/test_family_paths.py`), and a walk over the family trees must match
  something (`tests/test_rename_0101.py`).
- Style, enforced by review rather than a linter: module docstrings are 1–3 lines (rationale
  goes in the README beside the code, not the file header); no `from __future__ import
  annotations` (Python ≥ 3.11, write the modern syntax directly).

## Adding a family
`src/wsbench/evals/<category>/<family>/{__init__,prompts,judge}.py` following the skeleton above (register an
`EvalSpec` in `__init__` with `calls_per_arm`, `sources` and `group=<category>`, which `register`
checks against the directory), `evals/<category>/<family>/{items.json,README.md}`
with every prompt verbatim, a toy `examples/readouts/<family>.jsonl` (a few rows), an offline
`tests/test_<family>.py` (monkeypatch the module's `run_calls`), the README entry and Judges row,
and a credit if the items are external. Summary mode is the default (plan 0024), so a new family
either implements it (`digest.collapse` + a summary judge path, see the summary-mode bullet
above) or gets a `digest.NATIVE_ONLY` entry with its reason; otherwise every default run of it
exits 2. Smoke `limit=3` live before any full run.

## Workflow
- CLI (pydra, `wsbench <command> key=value ...`): `wsbench list` | `wsbench judge family=F
  readouts=F.jsonl out=DIR` | `wsbench run [--core|--full] readouts_root=DIR out=DIR` (core is
  the default tier; `all=True` = `--full`) |
  `wsbench report dir=DIR` | `wsbench baseline` / `wsbench freeze` |
  `wsbench plan [--core|--full|families=a,b] [out=DIR]` (core by default; the producer interface: render, positions rule and
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
- Per-model sets (`adapted/<m>/`): the `adapt-bank` skill (`.claude/skills/adapt-bank/SKILL.md`)
  is the runbook; its Quickstart drives `scripts/adapt_set.sh <m> build|refill|loop|final`, and
  plan 0075's data-round rules (D1-D7 screens, the two-run leaker rule) are `python -m
  wsbench.adapt dataround` (`adapt/dataround.py`, plan 0091). PRs merge only through
  `scripts/gated_merge.sh <pr>` (fail closed); a set's data stays local until frozen + audited.
- `uv sync --extra dev` (add `--extra gpu` for `produce`); `uv run pytest -q`; `uv run ruff
  check .`; `uv run ruff format .`. Keys
in the environment, never committed; tests make no network calls. Work
in a git worktree (prefix commands with `PYTHONPATH=src` when it shares the main checkout's
`.venv`); PRs are gated by `.github/workflows/ci.yml` (ruff + pytest).

## try, check, group=, the Batches backend, paths and the viewer

- `try family=F [n=2] [readouts=FILE] [dry_run=True] [out=outputs/try/<F>]` (`cli.Try`,
  `tryout.py`): the two-question try-out. Picks the first `n` plan rows that have readouts in
  the file (default the toy `examples/readouts/<F>.jsonl`), prints each question with its
  expected answer, then runs the ordinary `judge` (`items=<ids>`; `allow_missing=True` only for
  the toy file) and `report`, lists every output path and, after a live run, the two viewer
  commands. No logic of its own beyond the pick.
- `wsbench check` (`cli.Check`, `checks.py`, `docs/checks.md`): one registry of gates and sanity
  checks, each `(name, what it guards, "module:function")` with the function returning
  `(ok, why)`. No name = the list; `check <name> [option=value]` = PASS / FAIL + one line (exit
  0 / 1); `check all` = every check with no required option, then a SKIP line for each of the
  others. Register an existing guard or test file (`checks.pytest_outcome`) instead of
  rewriting it; external checks come in by dotted path through `$WSB_CHECKS`.
- `group=<category>` on `plan` and `run` (`groups.py`): the families of one registry category
  (`registry.CATEGORIES`), with no additions (`role_bound_association` is in
  `anti_bag_of_features` only). `computation` is accepted for `computational`.
- `judge_backend=batches` / `$WSB_JUDGE_BACKEND` (`judge_batches.py`, `docs/judge_backends.md`):
  the opt-in Message Batches backend of Claude judge calls; the default stays live.
- `wsbench capture` + `produce/store.py` (`docs/producing_readouts.md` § The residual store):
  subject activations kept per item under a key (token ids, positions, layers, steering);
  `store.cells_for` is the one way to get cells (store, then `pull`, then a forward pass). Needs
  the `gpu` extra and is never imported by the judge path (`tests/test_residual_store.py`).
  `produce/dataset.py` is its `pull`: the public dataset `agu18dec/workspacebench_residuals`,
  read through `evals/residuals/map.json` (item id -> key at the capture's bench commit, built by
  `scripts/residuals_map.py`; never hand-edited). `capture check=True` says where cells are.
- No absolute box path in `src` (`tests/test_paths.py`): a location outside the repo goes through
  `wsbench.paths` (`external(var, rel)` = `$var`, else `$WSB_DATA_ROOT/<rel>`, default root
  `/workspace`).
- `wsbench viewer ingest|serve` (`viewer/`, `src/wsbench/viewer/README.md`): the results
  viewer; needs the `viewer` extra.
