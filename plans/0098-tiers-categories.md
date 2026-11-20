# 0098: three run tiers (fast / core / full), a hard user_modeling score, eval categories

Issue #512. Camila, 2026-11-20.

> "restructure the repo to have three types of subsets we can run: 1) fast 2) core, 3) full.
> 'core' should be the default, while fast is for quick iteration, and full is to make sure a
> method doesn't regress on basic functionality."

This plan is PR 1 of 3. It adds the tiers, the hard user_modeling score and the categories as
registry data, CLI behaviour, report output and README structure. It renames no family key and
moves no directory: plan 0099 renames the `_mt` families, plan 0100 moves the family directories
under their category. It changes no bank, no judge prompt, no `prompt_version`, no `plan_sha`,
no cached call, no fast subset file and no ATI entry. Every existing results directory keeps
reading as it does today, with one more macro line.

## Scope change (Camila, 2026-11-20, after the plan was critiqued): no hard subset

"NO, i mean we should leave the existing set as the 'easy subset' and make 100 new questions
for a hard subset". So this plan ships NO hard user_modeling score. Everything below about
`um-hard-v1` is withdrawn: §2 entirely (`hard_v1.json`, `hard.py`, `extras["hard"]`,
`hard.from_rows`), `tiers.CORE_VALUE` / `core_value`, the `"no hard value"` exclusion, the
`user_modeling (hard, ...)` display row and its footnote, `core (hard)` in `wsbench list`, and
the hard-value tests. What ships instead:

- `tiers.CORE` is 17 families: the list of §0.1 without `user_modeling`. The existing
  user_modeling bank is in `full` only. A new, separately authored hard user_modeling bank
  (a later plan) joins core as its 18th family when it exists.
- `core_macro` is the macro logic over the rows whose family is in `tiers.CORE` (run-level
  context over all rows, `_row_exclusion` in today's order), with `n_core` 17.
- `markdown_table(core_macro=)` adds only the `**core macro**` row.

## 0. Definitions

### 0.1 Tiers

| tier | flag | what runs | macro |
|---|---|---|---|
| `fast` | `--fast` (and `--fast-safety`) | the frozen fast subset, **exactly as today** (plans 0090 / 0094 / 0095; nothing in `fast.py`, `evals/fast/` or the fast code paths changes) | fast macro, as today |
| `core` | none (the default), or `--core` | the 18 core families, each with its full registered bank and its unchanged instrument | mean over the 18 core rows, where the user_modeling row contributes its **hard** value (§2) |
| `full` | `--full` (`all=True` stays as its synonym) | every family `all=True` runs today (`registry.drop_superseded(sorted(FAMILIES))`) | today's macro, unchanged |

`core` (Camila's list), by registry key:

```
agentic_misalignment, jailbreak_recognition, arithmetic_intermediates, buggy_code,
nyt_connections, moral_rationale, poetry, introspection, multi_concept_directed_modulation,
wrong_intermediate, relational_multihop, role_bound_association, knowledge_cutoff,
model_specific_directed_modulation, user_modeling, model_multihop, chain_intermediates,
hinted_cutoff
```

core ⊂ full as family sets. A core run reads and judges all 126 user_modeling items (the family
is one of the cheapest: one digest and one MC call per item); only the number that enters the
core macro is the hard one. So user_modeling readouts, plan rows, `plan_sha` and cached calls are
identical in a core and a full run, and a core run directory is a prefix of a full one.

### 0.2 Categories

`EvalSpec.group` already exists and is only printed by `wsbench list`. Its values become the
seven categories (plus `precision`, kept for `jlens_concept_pr`, which is not in any macro):

| key (`EvalSpec.group`) | title | families |
|---|---|---|
| `basic` | Basic (adapted from the J-lens paper) | basic_readout, basic_readout_mt, multihop, multihop_mt, multilingual, multilingual_mt, typo, typo_mt, multilingual_typo, multilingual_multihop, poetry, directed_modulation, multi_concept_directed_modulation, association |
| `computational` | Computational | chain_intermediates, buggy_code, arithmetic_intermediates |
| `association` | Association | user_modeling, conjunctive_association |
| `safety` | Safety | agentic_misalignment, jailbreak_recognition |
| `anti_bag_of_features` | Anti-bag-of-features | relational_multihop, role_bound_association |
| `logical_processing` | Logical processing | moral_rationale, nyt_connections |
| `model_specific` | Model-specific | model_specific_directed_modulation, model_multihop, introspection, knowledge_cutoff, hinted_cutoff, wrong_intermediate |
| `precision` | Precision | jlens_concept_pr |

`multi_concept_directed_modulation` is not in Camila's pasted breakdown; it goes to `basic`
beside `directed_modulation` (it is the multi-concept form of the same J-lens-style task). The
shared bank families get their group from the factories: `basic/family.py` (`GROUP`) and
`multitoken/family.py` (`GROUP = "basic_mt"` at its top and as a default argument) both become
`"basic"`. The old values `basic_mt` and `bag_of_words` disappear. Besides those, these families
change group: nyt_connections and moral_rationale (model_specific -> logical_processing),
wrong_intermediate (basic -> model_specific), role_bound_association (association ->
anti_bag_of_features), relational_multihop (bag_of_words -> anti_bag_of_features),
multi_concept_directed_modulation (basic_mt -> basic). The comment listing group values on
`EvalSpec.group` in `registry.py` is updated.

## 1. `src/wsbench/tiers.py` (new) and registry

- `registry.CATEGORIES: dict[str, str]` = the key -> title map of §0.2, in that order. A test
  asserts every registered family's `group` is a key and that the family -> group map equals
  the table in §0.2 exactly (a literal dict in the test).
- `tiers.py`:
  - `TIERS = ("fast", "core", "full")`, `DEFAULT = "core"`.
  - `CORE: tuple[str, ...]` = the 18 keys of §0.1 in that order.
  - `core() -> list[str]`: `CORE` filtered to registered families, sorted the way `all` is
    (sorted by name). `full() -> list[str]`: `registry.drop_superseded(sorted(registry.FAMILIES))`
    after `load_all()`. `families(tier)` dispatches; `"fast"` returns `fast.families()`.
  - `CORE_VALUE: dict[str, str] = {"user_modeling": "hard"}`: the families whose core value is
    read from `result.extras[<key>]` (§2) instead of `result.value`.
  - `core_value(result) -> tuple[float | None, tuple[float, float] | None, int | None]`: for a
    family in `CORE_VALUE`, `(h["value"], h["ci95"], h["n_items"])` where `h` is
    `extras["hard"]` when present, else `user_modeling.hard.from_rows(result)` (§2.2, the
    fallback for rows judged before this plan; imported lazily inside the function), else
    `(None, None, None)`; for any other family `(result.value, result.ci95, result.n_items)`.
  - Import-time invariant, also a test: every `CORE` key is registered, not superseded, not
    retired, in `tiers.full()`, and not `not_in_macro` on the registered banks.
- `tiers.py` imports `registry` and `fast` only; `registry` does not import `tiers`.

## 2. The hard user_modeling score (`um-hard-v1`)

### 2.1 The frozen file `evals/user_modeling/hard_v1.json`

Already built by the main session (do not regenerate, reorder or re-derive it):

```json
{"version": "um-hard-v1", "family": "user_modeling",
 "bank": "evals/user_modeling/items_v3.json", "bank_sha": "<sha256 of that file's bytes>",
 "rule": "...", "n_bank": 126, "ids": ["um-...", "..."]}
```

51 of the 126 items (`name` values), all nine attribute classes. Rule: an item is hard when at
least one of the 18 trained lenses of the 2026-11-15 full-bench matrix fails it, which is the
same id set as "at least one of the 14 auxiliary arms (six `ab4-*` ablations, eight Qwen3.5
students) fails it"; the headline arms take no part in the selection. Stated limits, repeated in
the family README: (a) the prompt-only floor is still about 0.90 on these items (0.93 on all
126), so this score separates lenses from each other, not lenses from text; (b) the items were
selected on lens outcomes, so the auxiliary arms' hard scores are biased down by about 0.05;
(c) judge run-to-run noise moves a lens's hard score by up to about 0.07.

### 2.2 Scoring

- `evals/user_modeling/score.py` (the function that builds the `FamilyResult`, around the
  `extras` block): after the existing extras are built, **and without changing `value`, `ci95`,
  `n_items`, `rows` or any existing extras key**, add `extras["hard"]` when all of these hold:
  the run is not a dry run; no `WSB_BANK_ROOT` and no `WSB_BANK_FILE_USER_MODELING` (or legacy
  pin) is set; `fast.bank_sha("user_modeling")` equals the file's `bank_sha`; the run is not
  ATI-scoped or fast-scoped (`args.scope` is empty) and `args.items` is None and `args.limit`
  is 0 (a partial run has no hard value). Otherwise the key is absent.
- `extras["hard"] = {"version": "um-hard-v1", "value": v, "ci95": [lo, hi], "n_items": n,
  "n_undecided": u}` where the indicators are exactly the per-item indicators the family value
  is the mean of, restricted to the hard ids: `value` = mean over the hard ids that are decided
  (same undecided rule as the family: an undecided id has no indicator), `ci95` = the same
  `bootstrap_ci` the family uses, on those indicators, `n_items` = the 51 minus undecided,
  `n_undecided` = hard ids without an indicator. If no hard id is decided, `value` and `ci95`
  are None. Works the same in summary mode and native mode because it reuses the family's own
  per-item indicators (find where `indicators` is built and key it by item id; do not
  re-implement the pass rule).
- A helper `user_modeling.hard.ids() -> frozenset[str]` (new module `hard.py` in the family
  package) loads and caches the file and asserts `ids` ⊆ the registered bank's names when the
  sha matches.
- `hard.from_rows(result) -> dict | None`: the same dict recomputed from a stored
  `FamilyResult` that has no `extras["hard"]` (every results directory judged before this plan),
  so old directories get a complete core macro without re-judging. It returns None unless ALL
  hold: `result.config["prompt_version"]` starts with the registered user_modeling spec's
  `judge.prompt_version` (`um-v3.5+bank-v3`; the summary, layered and lite stamps only append
  to it; a small private predicate in `hard.py`, no existing matcher covers this);
  `config.get("scope")` is empty; the row is not adapted (no `config.bank_root` and no
  `config.registered_prompt_version`: an adapted bank can also stamp `+bank-v3`);
  `result.n_items == 126` and every row id is a registered name. The indicator follows
  `score.py`'s own rule exactly (its lines building `flags` and `indicators`): iterate the hard
  ids; an id in `extras["undecided_ids"]` has no indicator; an id with no row is a fail; else
  `score.item_flags(rows of that id)["inferred"]` (stored rows carry `id`, `pick`, `basis` as
  strings, in summary and native mode). No `result.complete` condition (the live path has
  none; the macro already excludes incomplete rows). A test asserts `from_rows(r)` equals the
  `extras["hard"]` the live path wrote for the same result, in summary and in native mode,
  including a result with a rowless item.
- A `layers=[L]` or `reads=lite` run of the full registered bank DOES carry `extras["hard"]`
  (intended: it is a full-item run); a test covers it.
- `prompt_version` is NOT bumped: no call, row or headline value changes. The key is additive
  in `extras`.
- Tests (`tests/test_user_modeling_hard.py`): file invariants (51 unique ids, all in
  `items_v3.json`, `bank_sha` = the file's sha256, version string); on a scripted-judge run of
  the family (reuse the existing user_modeling test harness / fixtures) the hard value equals a
  hand-computed mean over the hard ids, and `value` / `ci95` / `rows` are byte-identical to a
  run without the feature (compare against the existing golden or by monkeypatching `hard.ids`
  to raise and asserting only `extras["hard"]` differs); absent under `WSB_BANK_ROOT`, under
  `items=`, under `--fast` scope and under ATI scope.

## 3. Macro (`results.py`)

- `results.macro(...)` is **unchanged in behaviour, signature and output for every existing
  caller** (it is the macro over the rows present, and the fast macro, as today).
- Refactor inside `macro`: the run-level context (`summary_run`, the reads-mode guard, the ATI
  gate-mixing guard, the fast-mixing guard, `skip = adapted_exclusions()`) is computed once over
  ALL `results`, as today; the per-row decision moves into a private helper
  `_row_exclusion(r, ctx) -> dict | None` that **keeps today's elif order exactly**: removed ->
  retired -> superseded -> not in macro -> adapted skip -> metric -> judge -> incomplete -> no
  value -> not measurable -> native under summary -> ATI rules -> stale fast subset. `macro`
  then behaves byte-for-byte as before (the existing macro tests must pass unedited).
- New `results.core_macro(results, **the same optional maps) -> dict | None`: `None` when any
  row has a non-empty `config.scope` (fast and ATI have their own macro). Otherwise it computes
  the run-level context over ALL `results` (the same guards raise as in `macro`), then walks
  only the rows whose family is in `tiers.CORE`: a row is excluded by `_row_exclusion` exactly
  as in `macro`; additionally a family in `tiers.CORE_VALUE` contributes
  `tiers.core_value(r)[0]` and is excluded with reason `"no hard value"` when that is None.
  Result: the keys of `macro()`'s dict plus `"tier": "core"`, `"n_core": 18`, `"missing"`
  (core families with no row), `"complete"` (all 18 included). `value` = mean over the included
  rows also when incomplete (None when none is included).
- Adapted sets: no hard value (§2.2), so the core macro has at most 17 rows, `complete=False`,
  user_modeling under `"no hard value"`. A per-set hard subset is out of scope.
- `results.markdown_table(results, macro_row, ...)` gains a keyword `core_macro=None`. **The
  header, every family row, the `macro` row and the "Not in macro:" footnotes are unchanged**
  (no category column, no reordering: the table tests pin them). When `core_macro` is given and
  has at least one included row, two things are added: directly after the user_modeling family
  row, a display row whose first cell is `user_modeling (hard, um-hard-v1)` with the hard
  value, CI and n in the value / CI / n columns and every other cell blank (only when
  `tiers.core_value` yields a value); and directly after the `macro` row a row
  `| **core macro** | ...` in the macro row's format with `N of 18 families` in the cell where
  the macro row prints its family count, followed, after the existing footnotes, by one line
  `Core macro: user_modeling counts as its hard subset (um-hard-v1).` plus
  `missing: a, b` / `excluded: f (reason)` clauses when non-empty. The core row's last cell
  (where the macro row prints `excluded: ...`) is `—`. With `macro_row=None` the core row is
  appended after the last family row. The user_modeling row is located by `r.family` (its
  cell text may carry a `†` mark). Callers that do not pass `core_macro` get today's bytes.

## 4. CLI (`cli.py`)

Flags are argv rewrites like `--fast` (same mechanism in `main()`): `--core` -> `tier=core`,
`--full` -> `tier=full`. `--fast` / `--fast-safety` keep rewriting to `fast=...` exactly as
today; `tier=fast` is not a value users pass (ValueError: "use --fast"). `run` and `plan` declare
`self.tier = ""` in `__init__`; `--fast` / `--fast-safety` together with `--core` or `--full`
is a ValueError.

- `run`:
  - Today exactly one of `all=True` / `families=` is required. New rule: `families=` given ->
    those families, as today (a tier flag together with `families=` is a ValueError). Otherwise
    the tier decides: `--full` or `all=True` -> full; `--core` or nothing -> core. `all=True`
    with `--core` is a ValueError. With `--fast`, behaviour is today's (it requires `all=True`
    or `families=` today: keep accepting both, and additionally accept bare `--fast` as
    `--fast all=True`).
  - core names = `tiers.core()`; then the same adapted-set filter as the `all` branch (families
    with no bank in the set are skipped with the existing message). `include_superseded` applies
    to full only.
  - `all=True families=x` stays the usage error it is today. The old "pass exactly one of
    all=True or families=a,b" error for a bare `run` goes away (bare = core);
    `tests/test_cli.py`'s test of it is rewritten to the new rule.
  - `run.json` gains `"tier": "core" | "full" | "fast"` ONLY when a tier selected the families
    (the key is omitted under `families=`, so the two manifest key-set tests, which use
    `families=`, stay green unedited). Child judge processes are per family and get no tier
    flag.
  - `run`'s own summary (`cli._write_summary` and its `--json` payload) passes
    `core_macro=results.core_macro(results)` to `markdown_table` and adds `"core_macro"` beside
    `"macro"` in the JSON; `"macro"` stays.
- `plan`: `Plan.families` default changes from `"all"` to `None` (today a bare call and an
  explicit `families=all` both normalise to `["all"]` and cannot be told apart). Resolution:
  `families=all` -> every family, as today (**`families=all` keeps meaning full in every
  command**); `families=a,b` -> those; `None` -> the tier: `--full` -> every family, `--core`
  or nothing -> `tiers.core()`; under `--fast`, `None` and `all` both mean `fast.families()` as
  today. A tier flag together with an explicit `families=` (including `families=all`) is a
  ValueError. Under `WSB_BANK_ROOT` the core list is filtered to `readplan.families()` like the
  full list is today. `tests/test_readplan.py`'s bare-`plan` test is changed to pass `--full`
  (or `families=all`), and a new test covers the bare default.
- Every other command with a `families` default (`lucky-guessing`, `capable`, ATI, baselines,
  adapt tooling) is unchanged: their `all` stays full.
- `list`: row order is unchanged (sorted by name; `tests/test_list.py` zips rows against it).
  The `group` column is headed `category` (sanctioned edit of the header pin in
  `tests/test_list.py`) and a new `tier` column follows it: `core` for a core family
  (`core (hard)` for user_modeling), `full` for every other member of `tiers.full()`
  (jlens_concept_pr included), `—` otherwise (superseded, retired). The superseded / retired
  suffix on the category cell stays.
- `report` (`cli.Report.execute`): computes `cm = results.core_macro(results)` after
  `m = macro(results)`, passes `core_macro=cm` to `markdown_table` (so `summary.md` and stdout
  carry the two extra rows of §3), prints a second stdout line `core macro: value=...
  families=N/18 missing=[...] excluded=[...]` after the existing `macro:` line when `cm` is not
  None and has at least one included row (the same condition as the table rows, so reports of
  synthetic non-core families print unchanged stdout), and with `--json` adds top-level `"core_macro": cm` and per-family `"category"` /
  `"tier"` keys (blank strings for a family with no registered spec). `"macro"` is unchanged.
  Nothing changes for fast or ATI results.
- `--help` / usage strings and the `wsbench` docstring list the three tiers.

Tests (`tests/test_tiers.py`): the family -> category literal map; `tiers.core()` /
`tiers.full()` membership; argv rewrites; `run` with no selection resolves to the core list
(patch `runner.run_families` to capture the specs); `run --full` == today's `all=True` list;
`families=` + tier flag is a usage error; `plan` default vs `families=all` vs `--full`;
`core_macro` on synthetic results (complete; one core family missing; user_modeling without
a hard value; fast-scoped -> None; a native core row in a run whose summary rows are all
non-core is excluded from both macros; a full result set gives `macro` unchanged and
`core_macro` over the 18 with the hard substitution); `markdown_table` without `core_macro` is
byte-identical to today, and with it has the two extra rows; `list` tier column.

**Sanctioned edits to pre-existing tests, and nothing else:** (a) the group pins
`"basic_mt"` in `tests/test_multilingual_multihop.py`, `test_multilingual_typo.py`,
`test_multilingual_mt.py`, `test_multihop_mt.py`, `test_multi_concept_directed_modulation.py`
-> `"basic"`, and any other test asserting one of the group values changed in §0.2 -> its new
value; (b) `tests/test_list.py`: header `group` -> `category` and the new `tier` column;
(c) `tests/test_readme.py`: `GROUPS` / `by_group` rewritten to the §0.2 titles in order, with
`Precision (not in any macro)` as the last heading; (d) `tests/test_cli.py`'s bare-`run`
usage-error test and `tests/test_readplan.py`'s bare-`plan` test, as stated above; (e) viewer
tests only where they pin the old section titles. **If any other existing test fails, stop and
report it instead of editing it.**

## 5. Viewer and docs

- `viewer/build.py`: `GROUPS` keeps its name, shape and **exactly today's set of families**
  (`viewer_app/index.py` imports it; nyt_connections, an ids-only bank whose text must never
  be shipped, and the other families it omits today stay omitted); only the section titles and
  the family -> section assignment change to §0.2's (sections with no listed family are
  dropped).
- `README.md`:
  - a new section "Tiers" before "The evals": the §0.1 table with family counts, the core list,
    one paragraph on when to use which, and the user_modeling hard score (rule, n, the three
    limits of §2.1);
  - "The evals" is regrouped under the seven category headings in §0.2's order (the
    `### Basic (single token)` / `### Basic (multi-token)` / `### Bag of words` /
    `### Precision` headings go; Precision's two paragraphs move to the end under
    `### Precision (not in any macro)`); each family's bullet block is moved verbatim, with a
    `core` tag appended after the README link of core families. No family text is rewritten.
  - Quickstart commands that pass `all=True` are updated to show the default (core) and
    `--full`; "Fast subset" section gets one sentence placing it as the fast tier. Existing
    statements that are still true are not reworded.
- `evals/user_modeling/README.md`: a "Hard subset (`um-hard-v1`)" section (rule, counts by
  class, limits, where the value is reported).
- `CLAUDE.md` / `AGENTS.md`: a short "Tiers and categories" section (code facts: `tiers.py`,
  `core_macro`, `extras.hard`, `registry.CATEGORIES`, the default change of `run` / `plan`, that
  `families=all` is still full); `docs/producing_readouts.md`: `wsbench plan` now plans core by
  default, `--full` for everything.
- Bare `wsbench plan` call sites that mean every family get an explicit `--full`:
  `.claude/skills/adapt-bank/SKILL.md` (the bare `wsbench plan` line), `docs/producing_readouts.md`
  (the line commented "# every family"), `README.md` Quickstart, `AGENTS.md`. No script shells
  out to a bare `run` / `plan`; `all=True` call sites stay as they are.

## 6. Out of scope (later plans)

- 0099: `basic_readout_mt` / `multihop_mt` / `multilingual_mt` / `typo_mt` take the plain key;
  today's `basic_readout` / `multihop` / `multilingual` / `typo` become `*_st`.
- 0100: family directories move under their category (`evals/<category>/<family>/`), after or
  together with plan 0097's bank packaging.
- A re-cut fast tier (whether fast should become a subset of core), a prompt-only floor for
  `um-hard-v1`, a per-set hard subset for adapted banks, the multi-concept DM "no false pick"
  rule and stratum reporting, the NYT judge fixes.

## 7. File tree (new / modified)

```
src/wsbench/tiers.py                      new
src/wsbench/registry.py                   CATEGORIES
src/wsbench/results.py                    core_macro (+ shared exclusion helper)
src/wsbench/cli.py                        tier flags, run / plan defaults, list, report
src/wsbench/basic/family.py, multitoken/family.py   GROUP = "basic"
src/wsbench/evals/*/__init__.py           group= values (10 families)
src/wsbench/evals/user_modeling/hard.py   new
src/wsbench/evals/user_modeling/score.py  extras["hard"]
src/wsbench/viewer/build.py               GROUPS retitled (same families)
evals/user_modeling/hard_v1.json          new (already built)
evals/user_modeling/README.md
README.md, CLAUDE.md, AGENTS.md, docs/producing_readouts.md
tests/test_tiers.py, tests/test_user_modeling_hard.py   new
plans/0098-tiers-categories.md
```

Gates (what CI runs): `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`.

## As built (deviations from the text above)

- `run.json` `tier` is written for a bare `run`, `--core`, `--full` and a bare `--fast`; it is
  omitted under `families=` and under an explicit `all=True` without a tier flag (two manifest
  key-set tests use `all=True`).
- `report json=True` carries `"core_macro"` only when the core macro averages at least one
  family (a test pins the key set of a non-core report); `run json=True` always carries it.
- The registry-dependent half of the tier invariant is `tiers.check()`, run by a test; only
  the static half runs at import.
- `tiers.tier_of(name)` feeds the `list` column and the report JSON.
