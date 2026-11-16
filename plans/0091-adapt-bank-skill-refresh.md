# 0091: adapt-bank skill refresh (quickstart, sizing, decision table, first-class data round)

Issue #479. Camila, 2026-11-16: "make sure it is FULLY UPDATED and it is really really easy to
make new workspacebenches for models".

## Why

- The adapt-bank skill still describes 2026-11-02. It says "refresh blocked until plan 0060",
  points to Agam's RunPod box and the 4090, calls poetry and moral "not buildable", and says
  native languages come from a measurement.
- Plans 0072-0090 then rebuilt every set. Three builds ran in the last days: the small-Qwen
  refill with rescue judging, Agam's five sets under plan 0089, and the new deepseek-v4-flash
  set (#469).
- All three builds drove the pipeline with scripts copied from run tree to run tree, each with
  hard-coded paths:
  - plan 0075's data round: `dec.py`, `leaks.py`, `newleaks.py`, `screen.sh`, `capscan.py`,
    `mhcheck.py`, `umcheck.py`, `gcap.py`;
  - the merge gate: `gated_merge.sh`;
  - the stage chains: `build.sh`, `refill.sh`, `cycle.sh` / `cycle2.sh`, `driver.sh`,
    `loop.sh`, `step.sh`.

  The same rules were rewritten three times. Every new agent has to find a run tree to copy from.

## Changes

### 1. `src/wsbench/adapt/dataround.py` + `python -m wsbench.adapt dataround` (new)

This module ports plan 0075's "Data round rules" from the run-tree scripts. The rules do not
change.

- **`stage=leakers run=<dir> [root=<dir>] [history=c*,final*] [apply=true]`** implements D1-D3
  (`dec.py`).
  - Inputs: `run` is one lucky-guessing measurement, `wsbench baseline kind=lucky_guessing
    variant=blind,described draws=5 out=<run>`, with one `<family>/{blind,described}.json` per
    family. `root` defaults to `run`'s parent.
  - **Earlier runs:** as in `dec.py` and plan 0075, these are the other directories under `root`
    whose names match `c*` / `final*`, the driver's cycle and final measurements. Each one holds
    a measurement of the family. A report-only or ad hoc run elsewhere never confirms a drop,
    and a directory reached twice through a symlink counts once. `history=` widens the patterns
    explicitly.
  - **Only `run`'s own flags can drop.** The driver's cycle makes two lucky runs, `c<T>_1` and
    `c<T>_2`, and passes the second as `run`, so the first is its earlier run: a cycle can
    confirm on its own. An item flagged only in `c<T>_1` stays.
  - Family bar: chance + 5 points per guesser, with chance = the run's `analytic_floor`.
  - Per-run test (D1-D2): a guesser that fails the family bar gets >= 3/5 on the item, AND
    blind + described together reach >= 4/10.
  - D3: blind + described get 10/10.
  - Blind-only family (fewer than 4 items): blind >= 4/5 on a failing blind guesser.
  - **Two-run rule:** an item is dropped only when it is flagged in `run` AND in at least one
    earlier run. It is checked against that run's own failing guessers.
  - Pending items: an item flagged only in `run` is listed as pending and kept.
  - Loop: the rates are recomputed after each confirmed drop, and the pass repeats until it
    drops nothing.
  - Scope: only shipped items count, so ids already in `report.json` `drops` are skipped.
  - role_bound drops take both twins (`-ab` / `-ba`).
  - Output: `<run>/leakers.json`. With `apply=true`, each confirmed id goes through
    `run.drop` with the D1-D3 reason. Without it, it prints the `adapt drop` commands.
- **`stage=screens out=<dir> [apply=true] [llm=claude-opus-5-5] [only=d4,d5,d6,d7]`** runs D4-D7
  on the shipped bank:
  - D5, capitals: `capscan.py`'s multilingual regex over the prompt-side text of the 15 text
    families. It keeps the two figurative typo_mt rows.
  - D7, user_modeling Country and Gender caps: each class is capped at 20%, and the newest rows
    over the cap drop first. This is `gcap.py`'s rule. The run trees scripted only the Gender
    cap; they kept Country under the cap through the authoring steer and printed its share.
    Plan 0075's written D7 caps both, so the port applies both. Checked on every merged
    plan-0075 set: zero Country or Gender drops, so the shipped practice does not change.
  - D4, bridge shortcuts: an Opus check of multihop / multilingual_multihop (`mhcheck.py`'s
    prompt). It keeps `*firstname*` ids, as every run tree did.
  - D6 / D6b, places in the gold country: Opus checks of user_modeling Country rows
    (`umcheck.py`'s two prompts).
  - LLM answers are cached in `<out>`, so a re-run only pays for new items.
  - Output: `<out>/screens.json`; `apply=true` drops through `run.drop` with the decision's
    reason.
- **`stage=counts`** (shipped units per family plus the drop total) and **`stage=lucky`** (the
  MC families, split into blind+described or blind-only) are the driver's queries.
- **`stage=short`** prints the families that are below target and still have a refill route
  (`refill.POLICY`, `refill.FILL_POLICY`) and whose status is not an objective `ooc` or
  `blocked`. It also prints the families whose last refill stopped on `max waves`. The driver
  reads this list.
- **Tests:** `tests/test_adapt_dataround.py` covers:
  - the per-run test;
  - the two-run rule: a single-run flag is pending, a two-run flag drops;
  - the blind-only path and D3;
  - re-iteration after a drop;
  - the role_bound twin pairing;
  - the capital regex, its keep list, and money-sense "capital" not hitting;
  - the 20% caps (newest dropped first, originals last);
  - `short`'s exclusion of ooc / blocked and its listing of max-waves stops;
  - the CLI's key check.

  The LLM screens are tested with a fake `stream_json`.

### 2. `scripts/adapt_set.sh` (new): the stage driver

`scripts/adapt_set.sh <model> <phase> [...]`, where `phase` is `build | refill | cycle <tag> | mmh <tag> |
loop <first> <last> | final | status`. It runs the plan-0089 order:

- **`build`:** the native_langs decision record, profile, the basic_readout subject golds, the
  nl upgrade, poetry, the moral re-key (`MORAL_VARIANT`), carry, agentic plus the newest
  pinned pool, msdm, kcutoff, multihop_mt, wrong_intermediate (`WI_POOLS`), nyt, model_multihop,
  arithmetic / chain ladders, and status.
- **`refill`:**
  - buggy_code;
  - the fill families with `waves=16`;
  - the pool families;
  - a second pass with `waves=$MAX_WAVES` (default 40) over every family `dataround stage=short`
    lists as stopped on max waves.
- **`cycle`:**
  1. poetry settle;
  2. a named freeze;
  3. onecue screen / repair / patch, in the first cycle only;
  4. `dataround stage=screens apply=true`, then a freeze;
  5. `LUCKY_RUNS` (default 2) separate lucky runs on the MC families. Two runs per cycle let one
     cycle confirm a drop on its own: a deliberate choice that matches the v4f run tree, while
     plan 0075 counted one run per cycle. Each run is still a separate measurement, so the
     two-run rule itself does not change; `LUCKY_RUNS=1` gives 0075's cadence;
  6. `dataround stage=leakers apply=true`, then a freeze (no model_multihop confirm: that is the
     `mmh` phase).
- **`mmh <tag>`:** model_multihop's FRESH confirm run, after the freeze and the item audit, as
  plan 0078 orders. It is its own phase, because plan 0078
  blocks the family after 3 failed confirms, so the driver never re-confirms on every cycle.
- **`loop`:**
  - Each round first back-fills the families `stage=short` names. The routes are
    plan 0075's: poetry `ADAPT_FILL_TIERS=poetry=v6` + settle, role_bound
    `ADAPT_ROLE_BOUND_STRICT=1`, basic_readout `fill` + `mc stage=subject`, and user_modeling
    authored as Occupation / Religion only.
  - It then runs a cycle.
  - It stops on plan 0075's own rule: the cycle dropped nothing (the `report.json` drop total
    did not move) AND the back-fill landed nothing (no family's shipped count rose across the
    back-fill freeze). `<last>` bounds it.
- **`final [tag]`:** the strict freeze with every family named, then one report-only lucky
  measure (`final_report_<tag>`), so the shipped lists are measured ones (§2.7).
  - The steps after it are the audit's, and the skill's Quickstart lists them: the independent
    audit, its must-drops with no new authoring, `final 2` (the re-freeze back-fills from
    rows already passing), an addendum for those rows, then the floors.
- **Every step:**
  - logs to `$ADAPT_LOGS/<step>.log` and records ok / FAIL in `<phase>.status`;
  - is skipped when already ok (resumable);
  - is retried only on the Claude OAuth refresh race.
- **Environment:** the script sources `$ADAPT_ENV_FILE` if set. Otherwise it needs the
  documented variables. It refuses to run with `ANTHROPIC_API_KEY` set.
- **Tests:** `DRY_RUN=1` prints the commands and runs nothing. A pytest runs every phase dry on
  a temporary fixture set and checks the command lines (`bash -n` plus the expected
  sequence).

### 3. `scripts/gated_merge.sh` and `scripts/download_weights_modal.py` (new)

The merge gate that plan 0089 and the skill require, which so far lived only in run trees.

- It refuses a PR with no checks, and refuses unless every check's bucket is pass or skipping.
- The gate never pipes `gh pr checks` into the merge.
- It merges with `--squash` from outside the caller's checkout.
- A pytest runs it against a stub `gh` on PATH and covers: no checks, a failing check, all
  green.

`download_weights_modal.py` is the CPU download of a pinned snapshot into a subject's Modal volume.
It generalizes the plan-0089 run tree's script. Its `cache_subdir` / `check_revision` helpers are
tested.

`scripts/wd_add_leaves.py` gets two small fixes:
- a usage guard, because `--help` used to create a table file named `--help`;
- the merged class count is written to `meta.n_classes` (the plan-0089 follow-up nit).

### 3b. `tests/test_adapt_skill_docs.py` (new)

This test keeps the skills from going stale again. It checks that:
- every `python -m wsbench.adapt <cmd>` / `$A <cmd>` the skills name is a real subcommand;
- every repo `scripts/...` path they name exists;
- the registered-bank table in `references/families.md` equals `registry.bank_path`;
- the driver's family lists plus the side builds are exactly the 30 families.

### 4. Skills and CLAUDE.md

**`adapt-bank/SKILL.md`** is restructured around a new head:

- **Quickstart.** The subject's HF id + revision -> `Subject` + `PLAN_0075_SETS` + a Modal deploy
  -> smoke -> `adapt_set.sh build` -> introspection / hinted_cutoff -> `refill` ->
  `loop` -> `final` -> audit -> floors -> README row / census -> data PR via
  `gated_merge.sh`.
- **Scope:** the 30 families, the objective-stop rule, and when introspection counts as
  `ooc`.
- **The environment block:** `WSB_ANTHROPIC_AUTH=sdk`, `ANTHROPIC_PROFILE=default`, Modal env,
  never `ANTHROPIC_API_KEY`.
- **GPU sizing:** small / mid / big MoE / 1T, with the measured GPU $ and wall clock of the
  three runs.
- **A decision table of stops:**
  - a yield stop vs `ooc`;
  - pool exhausted;
  - a `max waves` stop;
  - the multihop_mt 3-hop level;
  - agentic below 20 pairs;
  - introspection calibration NO-GO;
  - a hinted_cutoff short or failed bar;
  - a WD class missing in wrong_intermediate;
  - Opus refusals.
- **Checklists** for AUDIT.md and for the README row / census.

Stale sections are removed:

- §State (2026-11-02);
- §What can be built (until plan 0060);
- the 4090 runbook;
- §Refresh "blocked";
- Agam-box instructions.

The detailed procedure the new head links to is kept and corrected. Stale lines in
`references/*.md` are fixed. **wsb-new-questions:** native languages by lab decision; banks are
judged through `WSB_BANK_ROOT` / `WSB_BANK_FILE_<FAMILY>`; the leaker rule; the repo URL.
**CLAUDE.md:** a pointer to the skill, the driver and `dataround`.

Two pieces of current practice are not on main yet, and the skill says so:

- agentic pools v4-v7 and the `chat_tokens` length-gate fix are in the open sq-refill / agam5
  branches;
- rescue judging (`summ_refusal_chain`, the layered stage-2 rescue, `am_pins`) is on the local
  sq-refill branch, and the global " | " split fix is in its own PR.

The skill documents each as "pending: use once merged" rather than as present.

## Not in this PR

- No bench data, and nothing under `adapted/`.
- No change to any gate, judge or refill rule.
- No pre-existing test is modified.
