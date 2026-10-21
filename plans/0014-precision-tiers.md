# 0014 — Precision tiers: `tier=lite|standard|max`

Camila, 2026-10-20: one public repo where a user picks how much judging to pay for. Three tiers;
**the ranking between methods must be the same in all three.**

## 1. The tiers

| tier | default judge (every LLM family, aux stages included) | pins kept | jailbreak read | agentic Stage A positions |
|---|---|---|---|---|
| `lite` | `google/gemini-3.8-flash` | jailbreak + agentic -> `claude-sonnet-5` | `read=lite` (punct ∪ last 16 content tokens + `<|im_end|>`) | `stride=S_LITE` (§6) |
| `standard` (default; today's public behaviour, byte-identical) | `google/gemini-3.8-flash` | jailbreak + agentic -> `claude-sonnet-5` | `read=span` | stride 1 |
| `max` | `claude-opus-5-5` | **agentic only** -> `claude-sonnet-5` (Camila 2026-10-21: Opus 5.5 refuses Stage B) | `read=span` | stride 1 |

- `max` also moves every auxiliary stage to `claude-opus-5-5`. No family sets `aux_models`
  today. The summarizer and jlens Stage A follow `args.judge.model` (`summarizer.aux_judge`,
  jlens `extract_judge`), so they move with the main judge. The regex scorer of record stays the
  regex scorer, and the tier only changes the model that interprets token bags.
- Budget target for `lite`: ≤ ~$100 of Sonnet per five-layer arm, plus the Gemini spend
  (unchanged from `standard`, ~$20–30).

## 2. Code

1. **`src/wsbench/tiers.py`** (new). `Tier = Literal["lite","standard","max"]`, `DEFAULT_TIER =
   "standard"`, and one frozen table per tier:
   `default_model`, `keep_pins: frozenset[str]` (family names whose `JudgeConfig.model` survives),
   `family_opts: dict[family, dict[str,str]]` (`lite`: `{"jailbreak_recognition": {"read":
   "lite"}, "agentic_misalignment": {"stride": str(S_LITE)}}`, others empty).
   `tier_config(spec.judge, family, tier) -> JudgeConfig` is **the identity for `lite` and
   `standard`**: the registry's own configs and pins already are those tiers' instruments, so
   any family pin, including a future one, survives unchanged. Only under `max` is `model`
   replaced by `claude-opus-5-5`, for every family not in `max.keep_pins =
   {agentic_misalignment}`. The tier table, not a precedence rule, decides per family. Under
   `max`, any non-empty `aux_models` value is replaced the same way. `reasoning` is left as the family set it. The
   Anthropic route never sends `reasoning`, and Opus 5.5 takes the `always_thinks` `effort: low`
   path (llm.py), so an explicit Gemini `{"effort": "minimal"}` on hallucination/jlens is inert
   under `max`. Record that in the README rather than rewriting it.
2. **`judge_config.resolve`** is unchanged. Exactly two call sites resolve a family judge and
   switch to `resolve(tier_config(spec.judge, name, tier), flag=, env=)`: `runner.run_families`
   (runner.py:157) and `cli.JudgeFamily.execute` (cli.py:163). `baseline`, `capable` and their
   bare `JudgeConfig()` resolves are untouched and get no `tier=`. The precedence is **flag > env > tier table**. `pinned` keeps its meaning,
   "no override took effect", now measured against the *tier's* instrument for that family. So a
   `max` run of a Gemini family on Opus 5.5 is `pinned=True`, and the same run under
   `judge_model=google/gemini-3.8-flash` is `pinned=False`.
3. **CLI** (`run`, `judge`, `report`, `list`; **not `plan`**, because the read plan stays the
   full grid so one set of readouts serves every tier): `tier=` argument, default `standard`
   (**except `report`, whose default is `""` = detect from the results**), and an invalid value is
   a usage error (exit 2). **`JudgeArgs.tier`** (new field, default
   `"standard"`) carries it into the family, and `mcjudge.base_config` stamps `config["tier"]`
   from it, so every family's config gets it from one place. Per family, the runner builds
   `opts_for[name] = {**tier.family_opts.get(name, {}), **user_opts}` (in both
   `run_families` and `JudgeFamily.execute`; today one dict is shared across families). The
   user's `opts=` wins, so `opts=read=span` on a `lite` run is allowed and the result is then
   off-tier (see 4). `runner.judge_family` (the one place `JudgeArgs(...)` is built, runner.py:71-85)
   passes **`tier=args.tier`** into `JudgeArgs(...)`, next to
   `aux_models=tier_config(...).aux_models` (which replaces `spec.judge.aux_models`). Every
   reader of the shared `opts` dict (`needs_llm` at runner.py:169, `_one` at runner.py:183)
   switches to `opts_for[s.name]`, so there is one source of opts. **`tier` never enters any cache fingerprint** (mcjudge, agentic A/B/C,
   summarizer). That keeps every `standard` cache valid. A `lite` jailbreak run reuses cached
   `span` cells at no cost **only when it reads the same `cells.jsonl`**: the cache is
   `<out>/cells.jsonl`, and the README tells users to copy that file into a fresh `out` rather
   than writing over the `standard` `results.json`.
4. **Completeness (the retained invariants):**
   - jailbreak: today "`regime != "span"` -> `complete=False`, never in the macro". This becomes
     "`regime != tier's regime of record` -> `complete=False`". **`read=punct` stays a diagnostic
     that is never complete in any tier**, `read=lite` is complete only under `tier=lite`, and
     `read=span` is complete under `standard`/`max`.
   - jailbreak decides this from `args.tier` and the merged `read` opt. It never infers the tier
     from the opt.
   - agentic: `complete` additionally requires `stride == tier's stride` (1 for
     `standard`/`max`). The check goes in `agentic_misalignment/score.py` (the `complete =`
     expression, ~line 206) as an added clause `int(config["stride"]) == tier_stride(args.tier)`.
     Today any stride passes the `is_subset` check unflagged, so a strided
     `standard` run becomes incomplete. That is a deliberate tightening, and agentic is never in
     the macro anyway. **The existing conditions (pinned, no subset, not a dry run, every
     misaligned item has a Stage C record, zero unjudged cells) are retained.**
5. **Stamping:** every `results.json` `config` gets `"tier"`, `run.json` gets a top-level
   `"tier"`, and a `tier: X` line is written above the table **by the callers**
   (`cli._write_summary`, `ReportRuns.execute`), never inside `results.markdown_table`. The
   `run` path's `summary.md` keeps having no floors. `tier` is added to the `runner.Options`
   protocol and to `cli.JudgeOptions`/the `run` config. **No `FamilyResult` field and no
   `SCHEMA_VERSION` bump.** Readers use `r.config.get("tier", "standard")`, so old files read
   as `standard`.
6. **Macro / report:** `ReportRuns.execute` collects `config.tier` (missing = `standard`) of
   every result *before* calling `macro`. With more than one tier and no `tier=` it prints the
   tiers found and returns `EXIT_USAGE`, and `report tier=X` filters to one tier. The floors use
   the detected (or filtered) tier on both the table path (`floor_columns`) and the `json=True`
   path. With no `tier=` (detect), a single-tier or old directory reports under its detected tier
   and writes `summary.md` as today. Only an explicit `tier=X` filters and writes
   `summary_<tier>.md`. `run` is
   single-tier by construction. `results.macro` itself is unchanged, and so are the
   complete/pass-rate inclusion rules.
7. **Floors:** the `prompt_only.floors()` / `lucky_guessing.floors()` signatures are
   **unchanged**. Tier filtering happens after the zero-argument call, inside
   `cli.floor_columns(tier="standard")` and the report `json=True` path. `floor_columns()` with
   no argument returns today's output.
   A prompt-only floor shows if its frozen `judge_model` is `None`/`"regex"` (as today, in every
   tier, since the regex scorer of record is tier-independent) or equals `tier_config(...).model`
   for that family. Lucky-guessing filtering is per variant: a `blind`/`described` entry
   shows if it has no `model` key or its stamped `model` (lucky_guessing.py:538) equals the
   tier's default model (the same rule on the `json=True` path),
   `uniform` (`seeded-uniform`) always shows in the raw `json=True` floors, and a family
   drops from the table's lucky column when both blind and described are filtered out. So under
   `max` the lucky column is empty, not `— / —`. So the Gemini-judged floors show
   under `lite`/`standard` and drop under `max`, and the regex floors show everywhere. `freeze
   kind=prompt_only` reads `r.config.get("tier", "standard")`, refuses (exit 2) when it is not
   `standard` or when jailbreak's `config["read"]` is not `span`, and stamps `tier` on its
   entries, until floors are keyed by tier. `freeze kind=lucky_guessing` is unchanged: its
   inputs come from `baseline` (no tier), and its tier filtering comes from the stamped `model`. Freezing Opus 5.5 floors is out of scope
   here and listed in the README as a known gap.
8. **`jailbreak_recognition/judge.py`:** `lite_positions` (already drafted in this branch) =
   `sorted(punct_positions ∪ range(max(span[0], turn_end-16), turn_end+1))`. It is ⊆
   `grid_positions` per item (equal for the 11 short turns) and fix the draft docstring's
   "strict". Over the bank it is 1,859 positions (vs 28,799), i.e. 9,295 cells per five-layer arm.
9. **`wsbench list`**: the judge-model column follows `tier=`. `calls_per_arm` keeps its
   meaning (`standard`), and the lite figures go into the jailbreak/agentic `calls_per_arm`
   strings ("…; lite ≈ N"). No new column, so test_list.py's `?` count holds.
10. **Spend:** `_anthropic_once` records tokens but no dollars, so `spend_usd` stays 0 on the
    Anthropic route. The README cost table is worked out offline from token counts and list
    prices, and says so. An Anthropic price table is out of scope.

## 3. Tests (new; no pre-existing test assertion changes except the one sanctioned in item 5)
1. `tier_config`: for each tier × {a Gemini family, jailbreak, agentic, a multitoken family},
   the model, aux models and reasoning (left as the family set it). A stub family pinned to a
   non-default model that is in no `keep_pins` survives `lite`/`standard` unchanged and moves
   to Opus 5.5 only under `max` (tests/test_runner.py:158-162 must pass unmodified).
2. Precedence: flag > env > tier, and `pinned` flips exactly when an override differs from the
   tier instrument.
3. `lite_positions` ⊆ `grid_positions` for every bank item, `turn_end` always included, 1,859
   positions over the bank (one layer).
4. Completeness matrix: (tier, jailbreak regime) and (tier, agentic stride) -> `complete`, with
   punct never complete.
5. `standard` is unchanged in substance: identical cache fingerprints, calls,
   `numbers`/`complete`/`pinned`. The only addition is a `tier` key in `config` and `run.json`.
   The existing golden/results tests pass **unmodified**. The one sanctioned edit is adding
   `"tier"` to the exact key-set assertion at tests/test_runner.py (run.json keys), plus any
   other exact-config-key-set assertion, each named in the PR body. Any other edit to a
   pre-existing test is out of plan.
5b. End-to-end through the CLI (offline, `run_calls`/LLM monkeypatched): `run ... tier=lite`
   writes results with `config.tier == "lite"` and jailbreak `complete=True`. Unit tests that
   build `JudgeArgs(tier=...)` directly are not enough.
6. `report` over mixed tiers with no `tier=` exits 2, a lite-only directory reports as lite into `summary.md`, `tier=` filtering works, and floors follow the tier (max: empty lucky column, regex prompt-only floors still shown).
7. A fingerprint test: the same jailbreak cell under `tier=lite` and `tier=standard` has the
   same fingerprint.
8. `max` on Opus 5.5 takes the `always_thinks` path (a mocked client sees `effort: low`).

Pre-existing tests that must pass **unmodified**: tests/test_lucky_guessing.py:350-381,
tests/test_results.py:148, tests/test_agentic_misalignment.py:604-652,
tests/test_list.py:49, tests/test_readme.py:96-97. For that last one, README §Judges keeps the
rows `| jailbreak_recognition | claude-sonnet-5 |` and `| agentic_misalignment | claude-sonnet-5 |`
verbatim, and the tier table is a separate table.

## 4. Docs
README §Judges: the tier table, the cost per five-layer arm per tier, the ranking evidence (§6)
and the rule "compare methods only within one tier". Family READMEs: jailbreak §Read sites
(`read=lite`), agentic §Readout input (`stride` under `lite`). CLAUDE.md: the judge layer bullet
and the tier resolver.

## 5. Out of scope
Opus 5.5 floors; any prompt change; re-judging stored results.

## 6. Evidence and the `S_LITE` choice (validation, 2026-10-20/21)
- `standard` vs `max` judge (22 Gemini families vs Opus 5.5, 11 paper methods): macro Kendall
  0.964.
- jailbreak `read=lite` vs `span`: offline over 18 O-lens arms, Spearman 0.77 (noise floor of
  span vs itself: 0.83 median). Live Sonnet `read=lite` on the 11 paper methods: (fill in).
- agentic stride 4/8/16/32 vs 1 on the 11 paper methods, Sonnet 5: (fill in). `S_LITE` = the
  largest stride whose ranking matches stride 1 within noise and costs ≤ ~$50 per arm.
