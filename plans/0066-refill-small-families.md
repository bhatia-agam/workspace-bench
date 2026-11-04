# 0066: refill the five small families of the plan-0060 adapted sets

Issue #266. (Written as 0064; renumbered to 0066 because main merged plans 0064 hinted-cutoff-prompt-only and 0065 math-shortcuts meanwhile.) Builds on plan 0060 (PR #230; Phase A2 / Phase E code merged in #250–#258). Sets affected:
`adapted/glm-5.3` (#259), the six small sets (#263), and deepseek-v4-pro / muse-spark-open /
kimi-k3 (being finalized).

## Camila's ask (2026-11-04, verbatim)

> refill buggy code, msdm, knowledge cutoff, wrong intermediate, and multihop mt v2. the agent
> skill should specify that families that are small should be refilled (unless the model is
> totally incapable like a really small model).

These earlier decisions carry over and are restated so that nothing is lost:
- **D4 / 2026-11-02:** for the model-specific families (msdm, knowledge_cutoff,
  wrong_intermediate, multihop_mt_v2), the target is the SUBJECT's own answer or preference. Items
  are **not** gated on the frontier "unguessable" check or the ATI panel.
- **D7:** thinking is off. Every gate runs on the subject, in its own chat template (or the
  family's registered plain render), and never through a stand-in model.
- **SKILL §Rules:** the gate rule of each family is never lowered to fill it. Pairs are atomic.
  Nothing is padded. Every knob is recorded in `adapt.knobs` and in `report.json`.

## Where the sets stand (measured from the gate logs, 2026-11-04)

`n shipped / registered target : status`:

| family | glm-5.3 | 0.8b | 2b | 4b | 9b | qwen3-8b | olmo-3-7b | v4-pro | muse | kimi-k3 |
|---|---|---|---|---|---|---|---|---|---|---|
| buggy_code (items / 63) | 28 = **7 pairs** | 0 | 0 | 0 (**0 pairs**) | 19 | 18 | 5 | 14 | 22 | 20 |
| msdm (/ 98) | 41 | 1 | 1 | 2 | 17 | 36 | 4 | 61 | 34 | 51 |
| knowledge_cutoff (/ 108) | 18 | 0 | 2 | 5 | 17 | 63 | 27 | 52 | 8 | 8 |
| wrong_intermediate (/ 100) | 33 | 0 | 1 | 33 | 41 | 46 | 3 | 7 | 22 | 26 |
| multihop_mt_v2 (/ 70) | 9 | 0 | 0 | 1 | 7 | 15 | 3 | 12 | 8 | 9 |

Why each family loses items. The figures are from the last gate record of each id in
`adapted/<m>/gate/<family>.jsonl`.

| family | where the funnel loses items | what was sampled from |
|---|---|---|
| buggy_code | GLM passes 43/63 items, but only 7 of the 24 registered pairs pass on both sides. 4b passes 9/63 items and 0 pairs. | the 63 registered items only (24 twin pairs + 15 orphans); `fill` was never run |
| msdm | GLM (report.json): 130 elicited → 76 G0-stable → 63 compliant → 41 with ≥ 2 options (31%). 4b, 9b and 8b: 106, 99 and 65 of 130 fail G0 stability (T = 1.0, ≥ 7/10). | 130 categories (98 bank + 32 `retired_panel_gate`) |
| knowledge_cutoff | GLM: 181 → 119 stable (62 unstable or refusing) → 101 of those answered right or not flagged stale → 18 pass. Kimi-K3: 135 answered right. 4b and 9b: about 120 unstable and 15–37 null labels. | 181 questions (108 bank + 73 pool) |
| wrong_intermediate | GLM: 258k candidates → 873 E1 → 179 pass the consistency gate → 40 clean after adjudication → 35 with an mc block → 33 after the audit. | the GW scrape (21 templates, `min_sl` 8–30) |
| multihop_mt_v2 | Strong subjects (GLM, Kimi) fail on the shortcut leg (S1 drop_b1, S2 adversary). Small subjects fail G1. | the 70 registered items only |

**The main finding.** For four of the five families, the source pipeline already produced a much
larger pool of candidates. Phase E sampled only from the registered bank and its retired items.
Each larger pool sits on this box, with its full provenance:

| family | unused source pool (already built, model-independent) | size |
|---|---|---|
| msdm | `/workspace/gw-evals-feas/outputs/feas/self_answers/{step1,step2,step3/b1,step3/b2}/cats.json` (key, topic, noun, the source's own `question`, domain) and `direct.<peer>.jsonl` (the greedy answers of 9 peers) | 1,072 + 2,897 + 1,934 + 1,975 ≈ 7.9k categories, before dedupe |
| knowledge_cutoff | `/workspace/gw-evals-feas/outputs/feas/cutoff_confab/scale/b1/gate.json` `rows` (2,726: question, prompt, stratum, domain, event_date, truth) and `scale/b2/questions.json` (2,696), with `gen.<peer>.jsonl` | 5,422 questions. 114 of today's 181 come from b1; the other 67 (batches kc2–kc4) are in neither file, and b2 paraphrases some of them |
| multihop_mt_v2 | `/workspace/gw-mh-v2/outputs/multihop_v2/` candidate and adversary pools (the 9 that `finalize.py` reads). 1,621 candidates carry S1 + S2 ablations, all 70 bank items among them. | 1,384 clean new candidates after dropping adversary `problem` / `factual_issue` rows (+~2.5k that lack S2); fewer distinct entity chains |
| wrong_intermediate | already-screened items dropped for want of an MC category (7 templates: 165 of GLM's 873 E1); beyond that, re-scraping (lower `min_sl`; more templates) | 19% of E1 on GLM, on every subject with no new GPU |
| buggy_code | no pool. The `buggy_code` Brief already authors executed pairs (`author._buggy`), and `select` already keeps pairs atomic (plan 0060 A2). | — |

All five refills therefore follow the same rule: **draw more candidates of the family's own
construction, from the family's own source, and gate them with the family's unchanged gate.**
Only buggy_code needs new authoring.

## 1. The generic policy: refill until target, or until out of capacity

### 1.1 Target and unit
`target(f)` is the size of the registered bank, counted in the unit the headline scores:

| family | unit | target | why |
|---|---|---|---|
| buggy_code | **complete buggy/clean pairs** | 24 (the registered `twin` pairs) | The headline is `pair_rate` over pairs, and orphans enter only the per-item extras. The 63-item target depends on every orphan passing (24 pairs + 14 clean orphans + 1 buggy orphan), and GLM's buggy orphan fails. Today `fill` would loop on it until `max_waves`. |
| msdm | categories | 98 | |
| knowledge_cutoff | items | 108 | |
| wrong_intermediate | items | 100 | |
| multihop_mt_v2 | items | 70 | |

### 1.2 The loop (one code path for all five)
For each family, the refill works through its candidate **source** in seeded waves. In order, the
sources are: the unused pool (for wrong_intermediate, the already-screened items of unmapped
templates), then (wrong_intermediate) a re-scrape, then (buggy_code) authoring
down the Brief's tiers. Each wave is gated with the family's own stages, then `select` is
re-run. The loop stops at the first of these:

1. **full:** `have(f) >= target(f)`.
2. **ooc (out of capacity; objective):** at least `n_min(f)` candidates have been gated at the
   family's easiest level, the cumulative yield `landed / tried` at that level is below
   `y_min(f)`, **and** `have(f) < target(f) / 2`.
3. **partial, pool exhausted:** every source is used up and `have < target`. Record `refill:
   "pool exhausted"` and keep the counts. Running out of candidates is a limit of the pool, not of
   the subject, so it is never `ooc`.
4. **partial, budget:** the Claude-call or GPU budget passed to the command is spent. Record which
   budget.
5. **partial, cap binding** (buggy_code): the current tier is the crash-only tier, the crash cap
   binds, and the last wave gained 0 pairs in `have`. Record `refill: "crash cap binding"`. This
   stops a subject that passes only crash pairs, instead of burning waves to `max_waves`.
6. **partial, low yield above half:** condition 2 holds except `have >= target / 2`, for example a
   48/49 bank. This keeps today's rule (`run.fill`: "Gemma buggy_code stopped at 48/49").

Yield is counted in the family's unit: for buggy_code, pairs landed per pair object authored; for
the rest, items that pass the gate per candidate gated. Before a family's full run, it gets a
**pilot** of `n_min(f)` candidates **at the easiest level**. For buggy_code, `pilot=true` starts
`fill` at the last tier (`t2`) instead of `t1`. If the pilot already meets condition 2, the family
stops there as `ooc`. If it does not, the full run starts from the first tier as usual. This
makes "genuinely incapable" cheap to establish.

| family | easiest level | `n_min` | `y_min` | why this threshold |
|---|---|---|---|---|
| buggy_code | tier `t2` (an obvious crash) | 60 pair objects | 3% | today's `OOC_MIN` / `OOC_YIELD` |
| msdm | the ext pool (no tiers: the target is a preference) | 200 categories | 3% | GLM 31%, 9b 14%; 4b 1.5% and 2b 0.8% fall below it |
| knowledge_cutoff | the ext pool, all strata | 1,000 questions | 1% | Qwen's own design funnel was 146 / 2,726 = 5.4%. At exactly 1% the 5.2k pool yields about 52 items, just under half the target, so `y_min` sits at the edge where refilling stops paying. |
| wrong_intermediate | the expanded scrape | 200k screened candidates | 5 × 10⁻⁵ items / candidate | GLM 1.3 × 10⁻⁴ and 4b 1.3 × 10⁻⁴ pass it; olmo (1.2 × 10⁻⁵), 2b and 0.8b fall below it |
| multihop_mt_v2 | 2-hop pool candidates (G1 is the binding leg on small subjects) | 300 candidates | 3% | |

**What counts toward `tried` / `landed`.** Candidates **already gated with the same construction
on the same subject count**, so the pilot only tops the tally up to `n_min`:
- msdm: the 130 already elicited;
- knowledge_cutoff: the 181;
- wrong_intermediate: round 1's screened candidates (258k on every subject). So 0.8b, 2b and olmo
  already meet the 200k rule, and their `ooc` needs no new screening;
- multihop_mt_v2: the registered 2-hop items already gated;
- buggy_code: only authored pair objects at the tier in question. Originals are not authored at a
  tier, so they do not count. `fill` zeroes `tried` / `landed` when it steps down a tier, so the
  tally is kept per tier in the refill block (`tally[tier] = {tried, landed}`). On reaching
  `t2`, `fill` seeds its counters from `tally["t2"]`, the pilot's, instead of 0.

The `stop_status` tests pin each of these. The level is therefore "any candidates of the same
construction", not only the new source. One exception: a subject whose round-1 funnel is flagged
as a suspected pipeline fault (v4-pro wrong_intermediate, 7 items from 625 E1, §8) cannot be
`ooc` until that check clears. `refill` refuses `ooc` while `report.json` carries
`refill_hold: <reason>` for the family.

`n_min` and `y_min` are constants in a new `wsbench.adapt.refill.POLICY` table. They are
recorded in each family's `report.json` `refill` block, so a reader can see which rule stopped
the refill.

### 1.3 Code: `src/wsbench/adapt/refill.py` (new) and `adapt refill`
- `POLICY: dict[family, Policy(unit, target_fn, n_min, y_min, sources)]`.
- `stop_status(have, target, tried, landed, n_min, y_min, exhausted, budget_hit) -> (status,
  reason)`. This is the pure function of §1.2. Unit-tested, and also called by `run.fill` and
  `run.auto`, so the authored and generated families share it. **`fill` keeps its existing
  wave-sizing, its tier step-down after 3 waves under 30% (it already resets `tried` / `landed`
  per tier), and `miss_steer`.** Only the final status call moves here. Today `fill` applies
  only conditions 1, 2 and 5. `refill.py` adds 3 and 4.
- The CLI is `python -m wsbench.adapt refill model=<m> families=a,b [waves=] [claude_budget=]
  [gpu_minutes=] [pilot=true]`, and it dispatches per family:
  - buggy_code → `run.fill` (target in pairs, §2);
  - msdm → `msdm.run(..., pool="ext", wave=...)`;
  - knowledge_cutoff → `kcutoff.run(..., pool="ext", wave=...)`;
  - wrong_intermediate → `wrong_intermediate.run(..., pool=<dir1,dir2,...>)`;
  - multihop_mt_v2 → `mhmt2.run(..., stage="refill")`.
- Each wave appends to the family's gate log, exactly as the stages do today: append-only, and
  the last record per id wins. **Resume skips ids already in the gate log**, so a re-run never
  re-asks the subject.
- Writes `report.json` `families.<f>.refill = {route, unit, target, have, tried, landed,
  yield, waves, n_min, y_min, tally, pool_size, pool_used, stop, budget}`. Today `refill` is a
  string (run.py:1196). The schema change goes into SKILL.md §report.json, and every reader of
  the field (`adapt status`, the README generator, tests) is updated. An old string value is read
  as `{stop: <string>}`. Writes `status` from
  `stop_status`.
- `freeze` writes the family's `change` from the refill block. This fixes the audit nit:
  `report.json` still says "original items only" for wrong_intermediate, msdm and
  knowledge_cutoff, although generated or pool items ship.
- **Freeze guard:** for the five families plus the existing refill families (`fill`:
  typo_mt, association, basic_readout, basic_readout_mt; `auto`: arithmetic, relational, chain),
  freeze refuses to write a family whose status would be `untried` while `n_items < target`.
  `allow_untried=true` overrides the guard and stamps the reason into `note`. The guard checks
  only the families named in `families=`, and **only when `families=` is given**. A bare
  freeze (every family) does not apply it, so an existing set's never-refilled short families
  (chain, typo_mt, …) do not block a re-freeze.
  - **Placement:** `run.freeze(..., strict: bool = False)`. The library default keeps today's
    behaviour, so the existing tests that freeze small fixtures stay valid unchanged:
    test_adapt_phase_e.py:176-181 asserts `untried` on a 3-of-70 mh2 freeze, and
    test_adapt_self_answer.py, test_adapt_phase_e.py and test_adapt.py freeze msdm, kcutoff,
    wrong_intermediate, typo_mt and association fixtures.
  - The **CLI** `python -m wsbench.adapt freeze` passes `strict=True`, which is the path the
    runbook and every set build uses. New tests cover both defaults.

## 2. buggy_code: authored executed pairs through `fill`

**Lever:** `fill` with the existing `buggy_code` Brief (tiers `t1` value bug, `t2` obvious crash).
`author._buggy` runs both programs (`verify.verify_python`), writes the symmetric `twin`, and uses
the `-au-` / `-au-clean-` ids that `run.buggy_twin` / `select` / `_buggy_twins` already pair.

**Retained invariants, restated where they are modified:**
- **The family stays pair-scored.** The judge pairs on the symmetric `twin`, and `select` keeps
  each `{id, twin}` pair atomic: a failed clean twin drops its buggy partner, and the reverse. The
  refill target becomes 24 **pairs**, *and the `src` quota (buggy ≤ 25, clean ≤ 38) still caps
  the item mix*.
- **The consequence leg** (`families._buggy_code`: chat "What happens when this program is
  run?", greedy + 10 at T = 0.7, LLM-graded, threshold 4/6) is unchanged. **The buggy
  verbalization ban** (≤ 2/11 raw continuations name `cause`) is unchanged.
- The Brief's invariants are unchanged: deterministic, no hint words, no off-by-one / aliasing /
  subtle-exception bugs, and a clean twin that always runs to completion.

**Code changes**
1. `run.fill`, for buggy_code:
   - **`select` is still called exactly as today**, with the item cap `len(originals)` = 63 and the
     `src` quota. Only the stop rule counts in pairs.
   - `have = selected_pairs(select(family, rows, 63, quota))`. The new `run.selected_pairs(rows)`
     counts groups of 2 whose members are each other's `twin`. `target_pairs = 24`, the
     registered pair count. "full" means `have >= target_pairs`.
   - `tried` counts authored pair objects gated, and **`landed` counts authored pairs whose two
     twins both pass the gate, before the quota and the class cap**. Both feed `stop_status`.
     `have` (the stop target) is the pair count after `refill.buggy_selection` (§2.4).
   - The wave size is halved as for `PAIR_KEYS`, since one pair object becomes two items.

   `select` itself is unchanged. Passing 24 as its item cap would ship at most 12 pairs, so the
   test in §10 pins the call.
   - **`freeze` uses the same pair rule** (run.py:755, 829-851 derive `target = len(originals)`
     and reset a `full` to `partial` below 63 items). For buggy_code, freeze computes `have` and
     `target` through the same `refill.buggy_selection` function as `fill`. It writes
     `target_pairs` / `n_pairs` beside the item counts in report.json, and both its status and
     the freeze guard use pairs. Tested: a 24-pair, 55-item freeze is `full`.
2. **A clean-twin gate leg.** Plan 0030 §1 gated every new clean twin with (b) "the bare-program
   continuation does not claim a bug, error, crash or wrong result" (`buggy_twin_gate_grade.py`
   `B_PROMPT`). The adapt gate has no such leg, so an authored clean twin could ship even though
   the subject "sees" a bug in it, and that would distort the twin false-alarm rate.
   - **The rule is the source's, verbatim:** the GREEDY bare-program continuation (256 tokens, as
     in `buggy_twin_gate_modal.py`) must not claim a bug. A greedy-only leg is used, not greedy +
     samples, so no stricter rule is invented (decision 2 offers ≤ 2/11 as an alternative).
   - **New grader code:** `grade_llm.grader` has one fixed rubric ("does the answer state the
     gold"), and `gate.py`'s `meta.leak` only inverts that. So add a per-Ask rubric path:
     `Ask.meta["rubric"] = "buggy_bug_claim"` selects `B_PROMPT` from `buggy_twin_gate_grade.py`,
     moved into `grade_llm.RUBRICS` with its `.format` double-brace escapes un-doubled (the
     rubric is filled by `str.replace`), and parses `{"bug_claim": bool}`. The leg passes on
     `false`. The rubric id is added to the grade-cache key, so it never collides with a
     "correct" verdict for the same text. `run._regrade_asks` learns the same leg, and
     `_regrade_row` (which loops over stored legs only, run.py:1017) fails a clean row that lacks
     it, so a pre-0066 record can never pass by regrade. `profile regate=true` re-asks all 63
     originals; buggy-original flips from sampling noise are listed in the PR.
   - **Mechanism:** `run_gate` samples every Ask with the same `draws` (gate.py:797), and
     `grade_leg` needs a decided sample (gate.py:310). So add a per-Ask override,
     `Ask.meta["draws"] = 0`: `run_gate` generates only the greedy continuation for that Ask, and
     `grade_leg` with zero samples passes iff the greedy grade is decided and has no bug claim.
     An undecided greedy grade fails, as an undecided grade does today. Other Asks are
     unaffected (tested).
   - Added to `families._buggy_code` for `src == "clean"`. It applies to **every** clean item,
     originals included. `refill families=buggy_code` first re-asks the leg on every passing
     clean row that lacks it, originals and authored (`run.regate_missing_bugclaim`, re-lint
     first), before authoring anything. The narrower routes are `profile families=buggy_code
     regate=true` (originals only) and `gate families=buggy_code regate=true` (passing authored
     rows only).

   *The consequence leg and the buggy ban are unchanged.*
3. `lint._buggy`, for authored items only. Add the `wsb-new-questions` guards the adapt lint
   lacks:
   - the buggy and clean `verified` strings differ;
   - no forbidden imports or IO (`random`, `time`, `open`, `input`, `eval`);
   - for buggy items, the stdout is not a copy of visible literals. Objective rule: the full
     stdout (whitespace-normalised) must not equal a concatenation, with optional single spaces,
     of string / number literals that appear in the code. That catches "Ann Ann" from
     `print(first + " " + first)`. A stdout that merely contains a literal (`70` from `[70, 95,
     88]`) passes, as wsb-new-questions treats that as n/a;
   - single-line stdout, or ` | `-joined as the bank does.

   The existing lint is unchanged: verify status, crash vs class, `level2_tokens` not in the code.
4. **Mix and diversity on a normalised field.** `category` is free text: every registered label
   is unique, so a cap on it never binds. The cap uses `consequence_class` (value / categorical /
   crash) instead. Authored crash pairs (tier `t2`) may make up at most 20% of the shipped
   authored pairs; the registered bank has 1 crash in 25 buggy items. So a subject that passes
   only `t2` cannot fill the family with an easier, different latent: it stays `partial` / `ooc`
   on its value / categorical yield. `report.json` records the class mix of the shipped set
   beside the registered one (9 categorical, 7 value, 1 crash, 8 unset).
   - **Where the cap applies: final selection only, never yield.** Tier and pilot yield
     (`landed`) count authored pairs whose two twins both pass the gate, **before** the class
     cap. So a `t2` pilot whose crash pairs pass is never `ooc` because of the cap.
   - **The algorithm, `refill.buggy_selection(rows)`**, used by both `fill` and `freeze`. Its
     input is ALL gated rows:
     1. Keep every both-pass group (pairs atomic) and order them: originals first (as `select`
        does today), then authored non-crash pairs in gate order, then authored crash pairs in
        gate order, admitted only up to `floor(n_nc / 4)`, where `n_nc` is the number of
        authored non-crash pairs.
     2. Then run the existing `select` (item cap 63, `src` quota) over that ordered,
        crash-trimmed list.

     So crash pairs gated first (by the pilot) can never use up the buggy quota ahead of later
     non-crash pairs. `have` is the pair count of the result. A subject that passes only crash pairs therefore keeps a
     non-zero yield but a low `have`, and stops as `partial` (budget / `max_waves`), not `ooc`.
     That is reported honestly as "passes only the crash tier".

**Yield and cost (GLM):** GLM passes 68% of the original items, but only 29% of the registered
pairs. Authored t1 pairs are easier (small literals, one-step bugs). I estimate a 40–60% pair
yield, so 17 more pairs need about 30–45 pair objects in 1–2 waves. Claude: about 3 authoring
calls per 60-item wave, plus about 22 grading calls per buggy item (11 consequence + 11 leak, cached) and 12 per clean item
(11 consequence + 1 greedy bug-claim),
which is about 2–3k calls. GPU: 2 waves of about 120 items × 23 short generations on the GLM app
take about 15 min of B300:8 (~2 GPU-h), plus the boot.

**Small subjects:** the wsb-new-questions record is "a 2B kept 5 pairs, 4 of them rounding". I
expect 4b and 9b to reach partial or full on t1/t2, and 0.8b and 2b to hit the pilot `ooc` rule
(< 3% on 60 pair objects at t2). olmo is uncertain.

## 3. msdm: the GW category pool

**Lever:** the source's own category pool, about 7.9k categories, deduped against the bank, its
`retired_panel_gate` and each other by key and by folded noun. Items are built exactly as the
bank's were and run through the unchanged `adapt msdm` stages.

**Retained invariants, restated where they are modified:**
- **G0 is unchanged:** direct question greedy + 10 at **T = 1.0**, a canonical label that is not
  a refusal, **≥ 7/10 agree** (`MIN_AGREE = 7`), *and the greedy named reveal after the
  teacher-forced carrier names the same label*. That label is the gold, and it is the subject's
  own preference. There is no frontier gate.
- **Compliance is unchanged:** the DM instruction alone; greedy + ≥ 8/10 at T = 0.7 reproduce the
  carrier verbatim and never name the gold.
- **Options are unchanged:** K ≤ 5, at least 2 (`MIN_OPTIONS`), and no distractor names the gold
  (same label, or one is a written form of the other). Units come from the source's symmetric
  procedure over **all** options (Opus generate + verify + `filter_forms`), so the gold and the
  distractors share one procedure.

**Code changes (`msdm.py`)**
1. Add `pool="ext"` to `candidates()`, after the bank and `retired_panel_gate` (origin
   `refill`). It reads the box-only pool file `$WSB_POOL_DIR/msdm_pool.jsonl` (sha256-pinned, decision 3), built
   once by `scripts/build_adapt_pools.py msdm` from the GW paths above. Its header records the
   source paths, each source file's sha256 and the dedupe counts. **Every row is mapped into the
   bank item's own shape**, so `build_options` runs unchanged:
   - From `cats.json`: `key → id`, plus `topic`, `noun`, `question`, `domain` and `type`.
   - **Every one of the 7,878 rows is also in its step's `gate.json` `rows`** (0 missing in all
     four steps), with the source's normalised labels. For all rows:
     - `gold` ← Qwen's label. `build_options` reads Qwen as `peer:qwen3.6-27b` from `gold`
       (msdm.py:369 overwrites any `peers["qwen3.6-27b"]`), so the pool row must not put Qwen in
       `peers`;
     - `peers` ← `peer`, `legacy` ← `legacy`;
     - `g0.qwen_samples`, and `options` / `option_sources` as stored. Any raw string goes through
       the step's per-key `maps` (raw → label).
   - **Where present** (2,227 rows: 420 + 823 + 498 + 486, the Qwen-G0-stable ones),
     `g1_pass1.{opus,sonnet}.typ_recall` ← the row's Opus / Sonnet typical answers, so the top two
     §6 tiers (`opus_typical`, `sonnet_typical`) are kept. Other rows' options start at peer
     greedy. These Opus / Sonnet answers are option SOURCES only, never a gate (D4: no frontier
     gate).
2. **Item construction for a pool row:**
   - `id = key`;
   - `user = contract.prompt` with `{topic}` and `{carrier}` filled in;
   - `carrier` is a seeded draw (`set_c_seed`, keyed by id) from the **registered bank's 10
     carriers**. Every carrier is therefore one the judge's `MIN_CARRIER_TOKENS = 7` and the
     reveal were frozen with.
   - `question = row.question`, the source's own wording. `msdm.question()` today uses only
     `QUESTION_OVERRIDES` or `topic` (msdm.py:161-162), so it changes to prefer
     `item["question"]` when present. Of the 32 `retired_panel_gate` categories, 30 are in the
     four `cats.json` files (2 are step0 and keep the default). Only ids whose source question
     actually differs from the question used today are re-asked (`s2_genus_of_typical_owl_strigidae`;
     the other two that differ are already `QUESTION_OVERRIDES`), and the change is noted in
     `report.json`. Re-sampling the rest at T = 1.0 would add only noise.
   - `noun` and `topic` are copied from the row.

   *The option priority is then the source's §6 order unchanged.*
3. **`pool` becomes a mode (`"none" | "retired" | "ext"`) through every stage**, not a bool
   only in `candidates()`. `_plan` builds its id map from `candidates(True)` (msdm.py:492) and
   skips any id missing from it with `continue`, so an ext row would be elicited but never built,
   silently. `_plan` / `canon` / `units` / `build` therefore take the same mode; `True` maps to
   `"retired"` for compatibility. A test asserts an ext row reaches the gate log.
4. `elicit` / `canon` / `units` / `build` take `wave=<k>, wave_size=200`: the next 200 unseen pool
   rows in seeded order, with ids already in `elicit.json` skipped. Without `pool=ext` the stages
   are byte-identical to today's.
5. **Diversity cap:** at most 2 shipped categories per `domain` (the registered bank's maximum).
   The `type` mix is reported beside the registered mix (food_drink 36%, technical_variants 31%,
   taxonomy 21%, untyped 10%), not capped: the pool has only those types, so a per-type cap
   would contradict the bank's own mix. Enforced at freeze `select` for non-original rows.
6. **Category validity legs (new for refill rows; validity, not guessability).** The bank's
   categories went through the source's membership and label checks before G0 mattered
   (README "membership / … / label QA"; items carry `member_check`, `label_qa`). Raw pool rows
   have had neither, so after G0 and compliance each refill row also needs both of these:
   - **membership:** one Claude call per row, using the source's member-check prompt, asks
     whether the SUBJECT's gold is a genuine member of the category. A non-member fails
     (`msdm: gold not a member`).
   - **label QA:** the source's label-QA call over the category, the gold and the options. It
     passes only with `verdict ∈ {keep, keep_with_aliases}`, the source's "clean" condition minus
     its frontier part. The source fills its `{preds}` slot with the frontier pass-2
     predictions, which are dropped. Here `{preds}` is filled with the item's built distractor
     options (peer / legacy / subject low-probability labels), the strings the judge will
     actually show. That substitution is the one deviation from verbatim, and it is noted in the
     pinned prompt's docstring.

   Both prompts are pinned verbatim in `msdm.py` from gw-evals-feas
   `scripts/feas/self_answers/v2/step3_checks.py` (the member prompt at line 64; the clean rule at
   line 148 is `member AND pass2 AND verdict ∈ {keep, keep_with_aliases}`). `pass2` (the second
   G1 pass) and `recognisable_strict` stay dropped: `references/families.md` classifies them as
   frontier-reader screens (D4). *G0, compliance and the option rules above are unchanged; these legs only add
   validity.* Note that today's msdm items (bank + retired) ship the subject's gold with no
   membership check either. The same leg applies to every built msdm item (Claude only, no
   GPU), so the GLM set is re-built with it.

**Yield and cost:**
- **GLM:** 31% on the 130 registered and retired categories. Those were Qwen-selected, so the
  random pool may be lower; I estimate 20–30%. 57 more categories need about 200–300 pool rows,
  which is 1–2 waves.
- **Claude:** about 0.55 canon calls per category, plus 2 membership / label calls for each G0- and
  compliance-passing row, plus 2 units calls for the categories that ship (with peers' labels,
  options are rarely all registered). That is about 400 calls per wave.
- **GPU:** about 23 generations per category; 130 categories took 3 min on the GLM app in phase 1,
  so a wave takes about 5 min.
- **Small subjects:** 9b (14%) and qwen3-8b (28%) should reach the target. 4b (1.5%), 2b, 0.8b
  and olmo (3%) face the 200-category pilot, and 4b / 2b / 0.8b are expected to be `ooc`: their
  T = 1.0 preferences are not stable, which is a real property and not a format failure.

## 4. knowledge_cutoff: the GW question pool

**Lever:** the source's full 5,422-question pool (b1 + b2), deduped against the bank,
`retired_panel_gate`, `g3_leak_items` and `retired_hygiene`. The questions were authored around
Qwen's cutoff, and stratum B (975 in b1 + 1,004 in b2 = 1,979 future-dated events, no known
truth) is exactly where a newer subject can still confabulate.

**Retained invariants, restated where they are modified:**
- **G0 is unchanged:** the item's `user` turn, greedy + 10 at **T = 1.0**. The canonical greedy
  label is specific (not a refusal, not a null label), **≥ 7/10 agree**, *and it is
  **incorrect** by the source rule verbatim*. That means a known truth that differs, unless VERIFY
  says it is correct; with no known truth, the item is incorrect only if VERIFY flags it stale or
  impossible. The gold is the subject's own wrong answer, with no frontier gate.
- **G3 is unchanged:** no gold form appears in the prompt.
- **`truth` stays the AUTHOR's.** VERIFY's `true_answer` is kept only as `verify_truth` and
  offered as one more option. A VERIFY verdict is reused only under the same gold and `cutoff=`. A
  failed Claude reply is never cached.
- **Options are unchanged:** K = 5 in seeded order (`SHUFFLE_SEED`), built from the gold, the
  truth, peers by source tier, the subject's low-probability samples, then FILL. Units come from
  the ALIAS call over all options, because no pool option is registered.

**Code changes (`kcutoff.py`)**
1. Add `pool="ext"` to `candidates()` (origin `refill`). It reads
   `$WSB_POOL_DIR/kcutoff_pool.jsonl` (sha256-pinned), built by `scripts/build_adapt_pools.py kcutoff`. Each row holds
   `{id, question, user, answer_type, event_date, stratum, domain, truth: {authored, canonical,
   pre_cutoff_analog}, options, option_sources}`, in the **bank item's own shape**.
   - **Source fields.** b1: `scale/b1/gate.json` `rows` give `key`, `question`, `prompt` (→
     `user`), stratum, domain and event date, and `truth` is a plain string that becomes
     `{authored, canonical}`. b2: `scale/b2/questions.json` rows carry `key` (b2_00000…), and `user` comes
     from `scale/b2/gen_in.jsonl`, **joined by key**.
   - **Peer distractors become `options` / `option_sources`.** `kcutoff.build_options` reads
     distractors only from `item["options"]` / `option_sources`, and it strips `panel` as a
     QWEN_FIELD. So the pool builder turns each peer's greedy label into an option tagged
     `peer:<m>` (gemma4, nemotron, mistral4, glm47) or `legacy:<m>` (llama, gemma,
     mistral), plus `peer:qwen3.6-27b` for Qwen's label. These are the source tiers the bank
     used. b1 labels come from `gate.json` `maps` (raw → label). **b2 has no `maps`**, and its
     peer greedies are 64-token prose ("I do not have information about an iPad Air announced in
     March 2025, …"). So a b2 peer string becomes an option only if it passes an objective
     short-answer filter: not a refusal (`selfans.looks_refusal`), at most 6 words / 40 characters
     after `selfans.norm`, no sentence punctuation mid-string, and matching `answer_type` (a
     numeral for number items). Anything else is left out, and those b2 items rely on FILL.
     Refusals and null labels never become options.
   - **b2 truth:** `truth = {authored: true_answer, canonical: norm(true_answer),
     pre_cutoff_analog}` from the b2 row (`true_answer` null → no truth, as for stratum B in b1).
     b1 maps `truth` → `authored` / `canonical` and `analog` → `pre_cutoff_analog`.
   - With that, *the option rule really is unchanged*: gold, truth, peers by tier, the subject's
     low-probability samples, then FILL.
   - **Dedupe by content, not only by id.** 67 of the 181 bank / retired / g3 items (kc2–kc4) have
     ids in neither b1 nor b2, and b2 paraphrases some of them: 12 of the 67 have a token
     Jaccard > 0.7 with a b2 question (e.g. the ROG Xbox Ally sale date, the ESCAPADE question at
     0.89). The builder drops a pool question if, against bank + `retired_panel_gate` +
     `g3_leak_items` + `retired_hygiene`, it has the same normalised `(event_date, truth)` with a
     **non-null** truth and a shared entity token, or a question token Jaccard ≥ 0.6. Within b1 ∪ b2 it keeps the first of
     any such pair, in seeded order. Both drop counts are written to the pool header.
2. **`pool` becomes the same `"none" | "retired" | "ext"` mode as msdm (§3.3), carried through
   every stage.** `kcutoff.canon` (:237), `verify` (:317) and the build plan (:452) build their id
   maps from `candidates(True)` and `continue` on a missing id, so without this an ext row is
   elicited and then silently never verified or built. Tested: an ext row reaches the gate log.
   `elicit` / `canon` / `verify` / `units` / `build` take `wave=<k>, wave_size=1000`, with resume
   by id. `cutoff=` keeps its meaning (only events from cutoff + 2 months). The default is still
   unset, as on GLM (decision 4).
3. **Diversity:** at most 20% of shipped refill items per `domain`. `report.json` records the
   `label_type` mix (stale / confab) and the stratum mix of the shipped set beside the registered
   55 / 53 (51 plausible + 2 weird) and A 96 / B 12. Refill will lean toward stratum B and confab. That is **reported, not
   capped** (decision 5): in the family's `report.json` `note` (freeze writes it from the refill
   block) and in its row of `adapted/README.md`.

**Yield and cost:**
- **GLM:** 10% on the 181 Qwen-selected items. Stratum A (2025 events) is mostly known to GLM, and
  stratum B gives most of the yield. I estimate 2–4% over the pool, which is 100–200 items from
  5.2k, so the target of 108 is reachable after about 3–5 waves.
- **Claude:** per question, about 0.6 canon + about 0.5 VERIFY (stable items only), plus FILL +
  ALIAS for those that ship. That is about 1.2k calls per 1,000-question wave, or about 5–6k for
  GLM. Pace to rate-limit headroom (SKILL: over 2k calls).
- **GPU:** 11 generations of 64 tokens per question. 181 questions took about 3 min, so a wave
  takes about 15 min of B300:8.
- **Small subjects:** qwen3-8b (35%), olmo (15%) and 9b (10%) should fill. 4b (2.8% on the bank
  items) is borderline but above the 1% rule. 0.8b (0/181) is expected `ooc`.

## 5. wrong_intermediate: recover unmapped templates, then a larger Wikidata scrape

**Lever, in source order (piloted first):**
- **Source 0: already-screened items lost for want of an MC category (no GPU).** Seven scraped
  templates have no `TEMPLATE_CATEGORY` entry (`scripts/wrong_intermediate_mc_options.py:43-59`):
  film_screenwriter, song_composer, person_mother, namesake, tv_creator, novel_publisher and
  building_architect. `ITEM_CATEGORY` covers only 4 registered ids, so `bank` drops these items.
  On GLM, 165 of 873 E1 rows come from them, and 5 of the 40 adjudicated-clean items (2
  person_mother, 2 film_screenwriter, 1 namesake) are exactly the 5 lost between "40 clean" and
  "35 with an mc".
  - **All category lookups go through one adapt `category_of`**, which consults
    `ADAPT_TEMPLATE_CATEGORY` / `ADAPT_ITEM_CATEGORY` and then the registered tables. It is used by
    `option_pool`, `build_mc`, `bank` and `entity_kinds`.
  - **person_mother and namesake, which need no new cues.** The judge already has
    `ROLE_CUES` for both (`evals/wrong_intermediate/judge.py:341-361`). They mix kinds, so each
    item gets its category **per item** from B''s entity through the §5.3 allowlist: the first
    category whose allowlist B' passes, with person categories decided by P106. No category
    means the item is dropped. These go into an adapt-side `ITEM_CATEGORY` extension
    (`wrong_intermediate.ADAPT_ITEM_CATEGORY`, computed, never hand-edited). The registered
    builder's tables are not edited, so its `--check` stays byte-identical.
  - **The other four, admitted with new role cues (decision 6):** film_screenwriter →
    filmmaker, song_composer → musician, tv_creator → filmmaker, novel_publisher → company. The
    judge credits a pick only with a cue from `ROLE_CUES[template]` near the name (`option_line`,
    judge.py:438, `.get(template, ())`), so each gets cues (§5.4). Their categories go into an
    adapt-side `ADAPT_TEMPLATE_CATEGORY`; the registered builder's tables are not edited.
    building_architect has no fitting category and stays out.
- **(a) Halve `min_sl`** (floor 5) for the templates that have both a category and cues, giving
  more and more obscure subjects. Obscurity raises the E1 rate (wrong bridges) but lowers how
  often the true-bridge hop 2 is answered right. The net effect is unknown, so pilot it.
- **(b) New templates in the re-scrape (decision 6):** song_lyricist (in the registered bank;
  cues exist), film_producer → filmmaker, opera_librettist → writer, album_producer → musician,
  aircraft_manufacturer → company. Each gets cues (§5.4) and reuses an existing `hop2`, so
  `grade`'s value matchers are unchanged. Their scrape definitions are added to GW `scrape.py`
  (a global-workspace change, run on the box; the round-2 pool is box data).

**Invariant for every admitted template:** it has a `ROLE_CUES` entry, so no item is ever judged
under the cue-less credit path (`judge_inputs` already flags a template with no cues). A test
asserts this over every shipped set.

The scrape runs in global-workspace (`scripts/wrong_bridge/scrape.py`, QLever plus
`wbgetentities`; CPU). The output goes to a new pool dir,
`/workspace/gw-wrong-bridge/outputs/wrong_bridge_r2/`. **r2 writes only candidate ids not in
round 1.** Lowering `min_sl` re-returns every round-1 pair, and those keep their round-1
candidate rows and entities.

**Retained invariants, restated where they are modified:**
- **E1 is unchanged:** p2 wrong, the true-bridge p2b right, p1 names B' ≠ B, B' resolves to an
  entity of B's kind, and p2 = hop2(B'). It still drops a leak, a year within 5 and an ambiguous
  B'.
- **The consistency gate is unchanged:** greedy A' and B'; **≥ `MIN_SAMPLE_AGREE` = 4 / 10** T =
  0.7 samples give A', and ≥ 4/10 give B'; inject B' → A', inject B → A, hop2(B') → A'. **logP(A')
  > logP(A) and logP(B') > logP(B)**, and a runner without `cont_logprobs` still fails every item.
  A' must not be a default answer (**< `HUB_FRAC` 3%**). *That share is now computed over the
  union of all screened pools of that template*, the SUBJECT's answers as before. B' must not be
  credited on S.
- **Adjudication is unchanged:** the registered Claude clean-error audit, same system prompt. It
  is a validity check, not a frontier gate.
- **Caps are unchanged:** one item per S, ≤ 20 per template, ≤ 4 per B'. Applied over the union.
- **The mc build is unchanged:** the v2 pool rule and the v4 forms rule. *An item whose B' has no
  entity of its category's kind is dropped.* §5.3 makes that check strict.

**Code changes (`wrong_intermediate.py`)**
1. `pool=` accepts a comma-separated list. `load_pool` merges `candidates.jsonl` /
   `entities.json` across the dirs. The first dir has precedence: round 1's candidate row and
   entities win for round-1 ids and QIDs, since labels and sitelinks will have drifted since
   2026-10-09. A later dir's differing copy of a known id is ignored and counted, never an abort.
   `screen` already resumes by key.
2. `grade`: `HUB_FRAC`'s denominator is the merged template population. This is a test-pinned
   change of scope, not of the threshold. Round-1 items are re-graded over the merged population,
   so a currently shipped item can flip, either way. Flips are listed per set in the refill PR,
   like the §5.3 entity-check drops, and never applied silently.
3. **An entity-based category check at `bank`** (audit F3: "Soviet Union" shipped as a
   manufacturer). Neither existing check can catch that case:
   - `bridge_kind` puts every non-human, non-group entity in "org", so a country is "B's kind"
     for a company bridge;
   - `wrong_intermediate_mc_options.kind_of(name, category)` returns `category` for every
     category except musician / band.

   So add `CATEGORY_P31: dict[category, frozenset[QID]]`, an allowlist over B''s own Wikidata
   `P31`, taken from the claim-bearing entity stores: the pool's `entities.json` ∪ the work dir's
   `entities_extra.json` (written by `wikidata_resolver` with claims). `wikidata_extra.json`
   holds labels / aliases only and is NOT a claim source. A B' with a missing entity or empty
   claims is a loud error that stops the stage, never a drop. The pool holds only the B' entities,
   not their classes, so "one P279 step" uses a **frozen class → superclass table**
   (`src/wsbench/adapt/data/wd_class_parents.json`). It is fetched once, at build time, for every
   P31 class seen on any B' across the pools, and vendored with its fetch date. No network access
   happens at gate time.
   - company: it must cover every template mapped to the company category, not only
     manufacturers: business / enterprise / company (Q4830453, Q6881511, Q783794), manufacturer
     (Q167270 and subclasses), record label (Q18127), television network / channel (Q1616075,
     Q2001305), video game developer / publisher (Q210167, Q1137109), publishing house /
     publisher (Q2085381, Q479716), aircraft manufacturer (Q936518). Calibration also covers the
     source-0 novel_publisher items' B'. The exact list is finalised
     against the B' of every currently shipped company item, as below;
   - band: the `bridge_kind` group set;
   - person categories (painter, writer, musician, composer, filmmaker, scholar,
     historical_leader): **Q5**. The check targets kind mismatches (a country as a company), not
     occupations. The registered labels are loose: `ITEM_CATEGORY` maps Marx to
     historical_leader, Ayn Rand is a scholar gold, and org_founder / person_father B' often hold
     no office. So P106 is **not** required for the check.
   - **P106 only assigns a category** to the mixed-kind person_mother / namesake items. Each P106
     value goes through the frozen table, a bounded ≤ 3-step P279 closure (novelist → writer,
     singer-songwriter → musician, physicist → scholar). Categories are tried in a fixed
     priority, musician (band if B' is a group) > composer > writer > painter > filmmaker >
     scholar > historical_leader, and the first match wins. A human B' with no matching P106 gets
     historical_leader only if it has P39 or a monarch / head-of-state occupation; otherwise it is
     dropped. A non-human B' gets company if it passes the company allowlist, band if it passes
     the group set, and is dropped otherwise.

   B' must pass its category's allowlist, otherwise `bank: B' not of the category's kind`.
   **Calibration:** all 100 registered items' B' must pass (a test; any exception is fixed in the
   allowlist, never excused). The rule is then applied to every shipped item across the 10 sets,
   and **a shipped item that fails it is dropped** (`adapt drop`, reason `entity-kind`), since it
   breaks the existing E1 intent. Each drop is listed per set in the refill PR. This tightens
   existing intent (E1 requires B' of B's kind) and lowers no bar. The test pins `Q15180` (Soviet
   Union) as rejected for company, and a real manufacturer B' from the GLM set as accepted.

**5.4 The judge-instrument change (decision 6)**
- **Code:** `evals/wrong_intermediate/judge.py` `_CUES` gains one entry per newly admitted
  template:
  - film_screenwriter: "screenplay screenwrit writ wrot script 编剧 編劇";
  - song_composer: "compos wrot writ 作曲";
  - tv_creator: "creat develop showrunner 创 創";
  - novel_publisher: "publish publication imprint 出版";
  - film_producer: "produc 制片 製片";
  - opera_librettist: "librett libretto wrot writ 作词 作詞 剧本 劇本";
  - album_producer: "produc 制作 製作";
  - aircraft_manufacturer: "manufactur built build produc maker 制造 製造".

  **#273 review (2026-11-04):** the performer cues `record` (album_producer) and `song`
  (song_composer) were removed. `_SUBJECT_STOP` excludes them on purpose, and they credited the
  performer ("Johnny Cash recorded it…"). The loose nouns `series` (tv_creator) and `aircraft`
  (aircraft_manufacturer) were removed, as was `made` (aircraft_manufacturer), which let "Air
  France made its last flight" credit an airline. Simplified 剧本 and traditional 作詞 were added
  for opera_librettist. A subject word of the prompt itself ("series" in "the TV series
  Breaking Bad") used to tie an actor's line through the subject-word rule. The same bump
  therefore adds `series`, `show`, `television`, 电视 and 電視 to `_SUBJECT_STOP`; no registered
  prompt yields any of them as a subject word (tested), so no registered verdict changes.

  Final wording is reviewed in the PR. The cue rule is unchanged: a Latin cue is a word start, a
  CJK cue a substring.
- **No registered template's cues change.** A test pins every pre-existing `ROLE_CUES` entry
  byte-for-byte, so the registered bank's verdicts are provably unchanged.
- **Version bump, per the repo invariants:** a new `CUES_VERSION = "wbcues-v2"` in
  `evals/wrong_intermediate/prompts.py`, appended to `PROMPT_VERSION` (`... + "+" +
  CUES_VERSION`). **`judge._mc_version` (judge.py:741-748) strips the tags that never enter a
  call (`AUDIT_VERSION`, `FORMS_VERSION`, `BANK_TAG`) from the call fingerprint, and
  `CUES_VERSION` is added to that strip tuple.** The cues never enter a call, so no cached MC call
  is invalidated. Tested: `_mc_version(PROMPT_VERSION)` is unchanged. The README's role-cue sentence (`evals/wrong_intermediate/README.md:208`) is
  updated, and the version table there gains the row. The cues are not a judge prompt, so
  `test_prompts_in_readme` is unaffected; the cue list is documented in prose.
- **Consequences of the bump, planned:**
  - every wrong_intermediate floor's stamp goes stale, so the floors are **re-measured on every
    set**: the registered bank's (`evals/baselines/` prompt-only and lucky-guessing entries) and
    each of the 10 adapted sets' `floors/floors.json`, under both protocols. These are Claude-only
    jobs, run after the independent review;
  - the ATI entry's instrument stamp goes stale. Since no registered verdict can change (pinned
    above), it is re-stamped with a documented restamp script in the style of
    `scripts/ati_restamp_rename.py`, not re-gated;
  - **pre-existing assertions that break on the bump:**
    - `tests/test_rename_wrong_intermediate.py:87` (`wp.PROMPT_VERSION == PRE_PROMPT_VERSION`)
      and its `PRE_PROMPTS_SHA`, since `PROMPT_VERSION` is in `PROMPT_CONSTANTS`;
    - `test_ati_bank_sha_unchanged_by_the_rename`, because `text_inversion.subset_entry` exits on
      an instrument mismatch (text_inversion.py:1743) until the ATI entry is restamped.

    These are the sanctioned exception, **pending Camila's OK**. So the cue additions, the bump,
    the ATI restamp (script plus the updated `evals/baselines/anti_text_inversion.json`, offline,
    in the code PR, not deferred) and those test edits go on a **stacked branch**
    (`camila/0066-wi-cues`), merged only on her OK. The main code PR admits only person_mother /
    namesake, which have cues, and needs no bump, so it stays green without touching a
    pre-existing assertion.

**Yield and cost:**
- **GLM, source 0:** the 6 admitted templates recover all 5 lost clean items at once (2
  person_mother, 2 film_screenwriter, 1 namesake), so 33 → about 38, at no GPU cost. Then 33 items per
  258k candidates is about 1.3 × 10⁻⁴, and the remaining ~64 items need about 500k new
  candidates, unless obscurity changes the rate. **Pilot:** (a) on 3 templates (film_director,
  novel_author, album_performer), about 60k candidates. Extrapolate before scraping more. If (a)
  and (b) together cannot reach 500k candidates, the family stops as `partial, pool exhausted`.
- **GPU:** phase 1 screened 339k prompts and gated them in 46 min on the GLM app, so 500k
  candidates (≈ 650k screen prompts) take about 1.5 h, or about 12 B300-h.
- **Claude:** about 1 adjudication call per gate pass (~180 per 258k), so about 400 calls.
- **Small subjects:** 4b, 9b and 8b already produce 33–46 items with E1 counts of 850–1,800, so
  the larger scrape should roughly double them. 0.8b (0), 2b (1) and olmo (3) are expected to
  fail the 200k-candidate `ooc` rule.
- **v4-pro (7 items from 625 E1)** is anomalous and is checked before its refill (§8).

## 6. multihop_mt_v2: the GW candidate pool, gated on the subject

**Lever:** the GW multihop_v2 candidates that are not in the bank. The bank's builder,
`gw-mh-v2/scripts/oracle_lens_evals/multihop_v2/finalize.py`, draws from 9 candidate pools. Of
those candidates, 1,621 carry both generator (S1) and independent-adversary (S2) ablations, and
all 70 bank items are among them. **Dropping the 70 bank items and the 167 whose adversary row
has a `problem` or `factual_issue` leaves 1,384 clean new candidates** (877 3-hop / 507 2-hop).
They are in the bank's own pre-gate schema: prompt, spans, units, bridges, `probes`,
`shortcut_accept`. The adversary's ablations are prompt rewrites with no model in the loop, so
they are not re-run. The ~2.5k generator candidates that lack S2 are out of scope (§9.7).

**Retained invariants, restated where they are modified:**
- **The source verdict's adversary-row rule** (`gate_modal.verdict`): an item whose adversary row
  is missing, has a `problem`, or has a non-empty `factual_issue` fails. Registered items had
  already passed it, so `adapt/mhmt2.verdict` never checks it. **The pool builder enforces it
  before gating**, so such rows never reach the GPU.
- **One item per entity** (`finalize.py` `entities()` / `taken`: the target plus every unit form).
  A candidate sharing an entity with a bank item is dropped before gating (71 such). Within the
  refill, the pool holds variants of the same chain (`-r0` / `-s0` / `-t0`; about 811 entity
  groups, an estimate only). At selection, `mhmt2.select_refill` (new; freeze's `select` calls it
  for multihop_mt_v2 non-original rows) applies finalize's greedy `taken` rule: walk the passers
  in order, keep one if none of its entities is taken yet, then add its entities. The order is
  `finalize.py:196-206` orders them: true 3-hop (not relabeled) first, then by gate margin (the
  smallest surplus over a leg's threshold, larger first). Seed id breaks ties. The "audited seeds"
  tier has no refill analogue and is dropped. No select / freeze code enforces an entity rule for
  mh2 today, so this is new. The pool builder reports the number of distinct entity groups, which is the real
  ceiling.
- **The staged gate is unchanged (`mhmt2.stage_asks` / `verdict`):** chat, no system turn,
  thinking off, stem `My answer is:`, T = 0.7, 24 tokens, `contains_target`. G1 is greedy ∧ ≥
  16/20; G2 / G3 are greedy ∧ ≥ 8/10; the three-hop G4ctx_b2 is ≥ 5/10.
- **The shortcut leg is unchanged:** every stored S1 + S2 ablation must NOT reach the target. A
  greedy hit or more than 4/20 fails the item, and nothing is excused.
- **The `relabel_b2` rule is unchanged:** a 3-hop item whose only hits hide bridge 1 is frozen as a
  2-hop item through bridge 2, with every role-keyed field remapped.
- **The bank's fresh-eye review is replaced by an equivalent targeted-shortcut step, not by a
  factual check.** `review_overrides.json` holds 11 overrides, and 10 of them drop items for
  shortcuts found by targeted probes. So for each refill item that passes the staged gate, one
  Claude call (`mhmt2.REVIEW_SYS`, pinned in the module) proposes up to 4 more prompt ablations
  that might reach the target without the bridge(s). The call is model-blind and states the
  adversary's brief. Those ablations are then asked on the subject as extra must-not-reach legs,
  under the same greedy / > 4/20 rule. The same call also returns a `factual_issue` field, and a
  non-empty one fails the item, matching the adversary rule above.
- **The family's authoring lint, which is new code in `adapt/lint.py`:** a bridge form may not
  contain, or be contained in, a target or a target_alt, and no bridge `answers` entry may occur
  in its own question (the wsb-new-questions families.md rule). `adapt/lint.py` has no
  multihop_mt_v2 entry today. The rule applies to refill candidates only: three frozen bank items
  trip it, and they are known defects.

**Code changes**
1. `$WSB_POOL_DIR/mh2_pool.json` (sha256-pinned), built by `scripts/build_adapt_pools.py mh2` from the same 9 pools
   `finalize.py` reads. It holds each clean new candidate with its `shortcut_probes`, assembled
   from the generator's `probes` (S1) and the adversary probes (S2) exactly as `finalize` builds
   them, plus its entity set. `tests/test_adapt_refill.py` pins that assembly against the 70
   bank items, which are all in the pools: the rebuilt `shortcut_probes` texts must equal the
   bank's.
2. **Order of operations.** Gate first, then build the judge-side fields; never build options for
   items that will fail.
   1. `mhmt2.gate_items(..., pool="ext", wave_size=300)`, origin `refill`, resumable: lint →
      staged gate → `relabel_b2` where it applies. `relabel_b2` and `subject_item` must tolerate a
      candidate with no `mc` / `name_forms` yet (asserted in a test).
   2. The review step above, with its extra legs, for the items that pass.
   3. `mhmt2.build_fields(model, ids)`, a new stage over the passing items in their
      **post-relabel** role layout, so nothing needs remapping:
      - **Unit `kind` is a judge input.** `multitoken/family.py:1309-1330` `bank_entities` keys
        the rival pools by `units[].kind` (multihop_mt_v2: person / work / event), and `_rivals`
        feeds `singles_out` / `list_gate` in the name gates (:1704, :2031, :2082-2089). So a refill
        unit's kind changes its own credit and every other item's rivals. The builder's hand tables
        are keyed by bank names (`UNIT_KIND` defaults to "person"; `TARGET_KIND` / `ZH_FORMS` raise on
        unseen names), so refill units are classified, never defaulted:
        - one Claude call classifies the unit into the bank's `KINDS` (person, work, event, place, other);
        - where the unit resolves to a Wikidata entity, the class is checked mechanically: Q5 is
          person, and a P31 in a frozen work / event class set gives that kind;
        - an invalid kind, a Claude–Wikidata disagreement, or a "not sure" answer **fails the
          item**; nothing is guessed.

        `kind` is added to `judge_inputs.REQUIRED_ITEM_PATHS["multihop_mt_v2"]` (`units[].kind`).
        The bank keeps its hand tables (`--check` byte-identical);
      - `full_forms` / `forms_excluded` and `name_forms.en` follow the `build_mh2_bank_v2.py`
        rules, refactored into importable functions (the frozen bank stays byte-identical:
        `--check`);
      - `mc`: **seed** `mc[role] = {"gold": <the unit's English gold>}` on each passing item
        (`r4_mc_distractors.specs()` reads `it["mc"][role]["gold"]`, lines 186–205). Then run the
        bank's own chain: `r4_mc_distractors.py --bank` (an Opus TOPIC call, then Opus-listed
        candidates screened against Wikidata, lines 54–68, 220, 380; **needs Wikimedia network
        access at build time**) → `r4b_mc_refine.py --bank` (Opus revision, kept only when neither
        the options-only nor the topic guesser solves the item in more than 1 of 5 draws) →
        `build_r4b_mc_banks.py --bank`. All three already list multihop_mt_v2 (`BANKS`), so the
        work is wiring in an adapted gate-log payload list as `--bank` input, not a new builder.
        This does **not** go through `mcstage`, which reads only `store.pending` before a gate. An
        item whose r4b list ends with fewer than 4 distractors fails, as the bank's rule
        requires;
      - **`name_forms.zh`, after `mc` exists.** The builder's check `_zh_problems`
        (build_mh2_bank_v2.py:763-781) needs a Chinese name for every distractor, for the target
        and for the other bridge's gold. So one Opus call per item returns Chinese names for the
        bridge gold(s), every r4b distractor and the target, and these feed a per-item `ZH_FORMS`
        overlay. `_zh_problems` then runs unchanged over it, and an item with any problem fails.
        Only the gold's zh forms ship in `name_forms.zh`, as for the bank. The others exist only
        for the check, which is exactly what the registered v4 items were checked against;
      - **bank-shape fields the GW candidates carry wrong or lack:** `readout` is set to the
        bank's `{"kind": "all", "lite": {"kind": "final_token"}}`; every GW candidate has the v1
        `final_prompt_token` read, and per `judge_inputs._p_mh2_readout` (:424-429) one such item
        flips the family's read plan. `n_render_tokens` is computed (the plain render, the
        subject's tokenizer). For a true 3-hop item, `bridges[1].question = CTX_QUESTION`, as
        `finalize.py` sets it;
      - then `mt.stamp` and `creditable` are **re-run on the final units, always with the
        subject's tokenizer**. `mhmt2._tokenizer()` returns None for qwen3.6-tokenizer subjects
        (0.8b–9b), because registered items carry Qwen counts, but refill items carry none, so
        `build_fields` loads the Qwen tokenizer explicitly in that case. An item left with no creditable multi-token form fails.

      `build_fields` writes a new gate record per item: the gate legs are copied and the fields
      added, last record wins.
4. **(decision 7) The adversary over the S1-only candidates.** If a subject's refill ends `partial,
   pool exhausted` with the 1,384, `scripts/build_adapt_pools.py mh2 --adversary` runs the GW
   independent adversary (`gw-mh-v2/scripts/oracle_lens_evals/multihop_v2/adversary.py`, ported
   with its prompt verbatim, one Opus call per candidate, model-blind) over the ~2.5k generator
   candidates that lack S2. It applies the same `problem` / `factual_issue` rule and the entity
   dedupe, and appends them to a new sha-pinned pool version (`mh2_pool.v2.json`). This is
   model-independent, so it is built once and shared by every subject. About 2.5k Claude calls.
3. **The judge path for adapted-only ids.** Today's sets ship only registered mh2 ids. A refill
   item is adapted-only, so the per-set resource overlay (`registry.adapted_only`,
   `_adapted_entry`; the C2 bug fixed in #258 for registered ids) must accept it without an
   `exonyms.json` entry, or freeze must write one. The fix is in scope. Acceptance is a **real
   summary-mode judge run** over a set containing a refill item (rc 0, the item decided), not only
   `dry_run`.

**Yield and cost:**
- **GLM:** 13% on the bank. I estimate 8–13% on the pool. The per-entity ceiling is what bounds it:
  the 1,313 non-bank-entity candidates collapse to about 811 entity groups (generous
  union-find), so at 8–13% roughly 65–105 groups pass. The target of 70 is likely but not certain, and the pool
  builder's group count decides early whether `partial, pool exhausted` is the expected
  outcome.
- **GPU:** 70 items took 4 min, so a wave of 300 takes about 20 min of B300:8, plus the review
  legs (≤ 4 extra probes × 21 draws per passing item).
- **Claude:** per passing item, 1 review + about 1 zh call + the r4/r4b chain (about 15 calls), so
  about 1.5k for GLM.
- **Small subjects:** 4b and 9b fail G1 (66/70 and 57/70), so 4b, 2b and 0.8b are expected to be
  `ooc` on the 2-hop pilot. qwen3-8b (21%) should fill.

## 7. SKILL.md and the references (Camila's rule)

In `.claude/skills/adapt-bank/SKILL.md`, a new subsection **§3a "Small families must be
refilled"**, referenced from the runbook and §Rules:

> Every family with a refill route (`wsbench.adapt.refill.POLICY`: buggy_code, msdm,
> knowledge_cutoff, wrong_intermediate, multihop_mt_v2, plus the `fill` / `auto` families) that
> ships below its target MUST be refilled with `$A refill $M families=<f>` before freeze. The only
> acceptable reasons to ship it short are the objective stops of plan 0066 §1.2:
> - **`ooc`:** at least `n_min` candidates gated at the easiest level, yield below `y_min`, and
>   the bank under half its target. The thresholds are in the POLICY table, for example msdm
>   below 3% on 200 categories and knowledge_cutoff below 1% on 1,000 questions;
> - **`partial`**, because the pool is exhausted, the budget is spent, or the yield is low with the
>   bank above half its target.
>
> `untried` is not a final status for these families: `freeze` refuses it unless
> `allow_untried=true` with a reason. "The subject is small" is not a reason by itself. A small
> subject stops through the pilot (`refill pilot=true`), which costs `n_min` candidates. Report
> the stop reason and the counts in `note`.

The SKILL changes, by location:
- **§What can be built:** buggy_code moves from "originals only" to "full build (authored
  pairs)".
- **§Families the adapt machinery does not cover:** the msdm, knowledge_cutoff,
  wrong_intermediate and multihop_mt_v2 rows gain the refill route.
- **Runbook:** step 4 gains `$A refill`. Step 5's freeze note lists the stop.
- **`references/families.md`:** each of the five entries gets a "Refill" line with the source,
  unit, policy and retained invariants. The "Open: no refill" lines are removed.
- **`references/porting.md`:** gets the pool file provenance.
- **`.claude/skills/wsb-new-questions/references/families.md` buggy_code:** points at `adapt
  refill` for per-model banks.

## 8. Rollout (local-first, as in plan 0060; nothing is pushed until audited)

Each subject is run in its own tmux session from the local run tree (`/workspace/wsb-runs`,
branch `camila/0060-runs`, never pushed), writing to `logs/<m>/refill_<family>_<ts>.log`. A chain
`status` file is written as in phase 1/2. The order:

1. **Code PR** (this plan's implementation) merged with green CI. Then build the pool files once
   on the box (`scripts/build_adapt_pools.py all`, CPU) and **pin their sha256 in
   `refill.POOL_SHA256` in a small follow-up PR**; the loaders refuse until then. Do the WI
   re-scrape (CPU) in parallel, and pin `mh2_pool.v2.json` the same way if decision 7 triggers.
2. **glm-5.3:**
   1. **Apply every new leg and re-grade to the existing items first**, so that `have` is
      measured on the final rules. **Mandatory order:** freeze now fails every buggy_code clean
      row that has no `bugclaim` leg (`refill.row_passes`), originals AND authored `-au-clean-`
      rows alike. So on ANY existing set, `refill families=buggy_code` (which first re-asks the
      missing leg on every passing clean row, after a re-lint, before authoring anything) or
      `gate families=buggy_code regate=true` (passing authored rows) plus `profile ... regate=true`
      (originals) MUST run
      before any re-freeze that includes buggy_code. `profile regate=true` alone covers originals
      only, so it does not clear sets that ship authored pairs: gemma-4-31b-it, glm-5.3-flash,
      kimi-k2, olmo-3.1-32b and qwen3.6-35b-a3b ship 4 / 8 / 2 / 18 / 12 `-au-` items. Otherwise the family ships 0
      pairs. Freeze prints a clear error naming the count of clean rows without the leg, and the
      strict (CLI) freeze refuses the family:
      - `refill families=buggy_code`, whose first step re-asks the missing `bugclaim` leg on every
        passing clean row, originals and authored (§2.2);
      - msdm: the membership / label-QA legs on all built items (§3.5);
      - msdm: the source questions for the 32 retired categories (§3.2);
      - wrong_intermediate: the hub share over the union and the entity check (§5.2–5.3), with
        flips listed;
      - wrong_intermediate source 0 (§5).
   2. `refill pilot=true` for all five;
   3. the full refill;
   4. re-run `stop_status` immediately before freeze. If anything dropped since the last wave
      and the family is short again, it goes back into the refill. Then freeze the five
      families, named;
   5. an independent delta audit of the new items, added to AUDIT.md, with drops applied;
   6. floors re-measured under both protocols for the five;
   7. a PR updating `adapted/glm-5.3`.

   Expected cost: about 30 B300-h plus 14–16k Claude calls (multihop's r4 chain is about 70 calls
   per item, §11.11). In addition, the wrong_intermediate
   instrument bump (§5.4) means that family's floors are re-measured on the registered bank and on
   every adapted set, and the ATI entry is restamped (Claude only, after review).
3. **The six small subjects** (qwen3.5-0.8b, 2b, 4b, 9b, qwen3-8b, olmo-3-7b), in that order,
   with the same steps, one PR. They run on the RunPod-style local runner or Modal as in #263. The
   pilots decide `ooc`, and 0.8b / 2b are expected to stop at the pilot for most families.
4. **deepseek-v4-pro, muse-spark-open, kimi-k3:** after their plan-0060 sets are frozen and
   merged, never mid-run (do not merge main into `wsb-runs` while a chain runs). First check
   v4-pro's wrong_intermediate (7 items from 625 E1; is the gate dropping on logprobs?) and its
   `blocked` buggy_code status.

Keep the apps warm with `scripts_local/keepalive.py` during Claude-only stages, and cap
`max_containers` on shared GPUs.

**Rollout checks found on GLM-5.3 (2026-11-04), required at every later subject's rollout:**
- **Read-span minimum.** A family's `min_full_positions` comes from Qwen3.6-27B's renders. A
  subject whose chat template leaves fewer positions after the prompt (GLM-5.3:
  `<|assistant|><think></think>`) makes every judge of that family exit 2. On GLM the shortest
  renders were association / conjunctive / role_bound 13 (of 19), arithmetic 33 (of 34, 60/566
  items) and user_modeling 34 (of 37, 3/87). Measure every family's shortest span over
  `WSB_BANK_ROOT=adapted/<m> wsbench plan` with the subject's tokenizer, and record it in the
  bank header `adapt.min_grid_positions` or, for a bare-list bank (conjunctive, role_bound),
  in `report.json` `families.<f>.min_grid_positions` (read by `reads.min_full_positions`).
  kimi-k3, deepseek-v4-pro, muse-spark-open, OLMo and every other subject with a shorter
  template than Qwen need the same check. `freeze` does not write it yet (a re-freeze drops
  the bank-header value; the report entry survives).
- **wrong_intermediate floors are stale on the 9 other adapted sets** after the #273 instrument
  bump (`wbcues-v2`). They are re-measured at each set's refill rollout, when its
  wrong_intermediate bank changes anyway.

## 9. Decisions (Camila, 2026-11-04)

1. **buggy_code target: 24 pairs**, keeping the `src` quota (buggy 25 / clean 38).
2. **The clean-twin leg is greedy only**, as in the source (§2.2).
3. **The three pools stay on the box only, NOT in the public repo.** `scripts/build_adapt_pools.py`
   writes them to a box directory (`$WSB_POOL_DIR`, default `/workspace/wsb-runs/pools/`). Each
   pool's sha256 is pinned in code (`refill.POOL_SHA256`) and in this plan once built. Every
   loader refuses a missing file or a sha mismatch with a SystemExit naming both hashes. Tests use
   small synthetic fixture pools with monkeypatched pins. The frozen Wikidata class table
   (`data/wd_class_parents.json`, CC0 Wikidata facts, no authored text) is not a pool and is
   vendored.
4. **knowledge_cutoff `cutoff=` stays unset.**
5. **The knowledge_cutoff label / stratum mix is REPORTED, not capped.** It goes in the family's
   `report.json` `note` and in its row of `adapted/README.md`.
6. **wrong_intermediate: ADD role cues for the new templates.** The admitted templates are the
   already-screened film_screenwriter → filmmaker, song_composer → musician, tv_creator →
   filmmaker and novel_publisher → company, plus the §5b re-scrape templates song_lyricist (cues
   exist), film_producer → filmmaker, opera_librettist → writer, album_producer → musician and
   aircraft_manufacturer → company. building_architect stays out (no category). This is a
   judge-instrument change, handled per §5.4: a version bump and floors re-measured on every set.
7. **multihop_mt_v2: run the adversary over the ~2.5k S1-only candidates** if the 1,384 clean
   ones do not fill a subject (§6.4).
8. **msdm: apply the validity legs to existing items too** (§3.6).

## 10. Tests (new, offline, fake runners and fake Claude: `tests/test_adapt_refill.py` for the policy, pools and freeze guard, plus one file per family, `tests/test_refill_{buggy,msdm,kcutoff,wi,mh2}.py`)

- **Pools (decision 3):** each loader refuses a missing pool file and a sha256 mismatch
  (SystemExit naming both hashes); no pool file is tracked by git (a test checks `git ls-files`
  for `*_pool.json*`).
- **Policy:** `stop_status` cases: full; ooc (yield < `y_min` on ≥ `n_min`, under half); partial
  low-yield above half (48/49); partial with pool exhausted under half (never ooc); partial on
  budget; a pilot that stops at `ooc`; buggy "crash cap binding" stops after a zero-gain `t2` wave
  with the cap binding. `POLICY` covers the five families. `freeze` refuses
  `untried` below target unless `allow_untried=true` when called with `strict=True` (the CLI
  default); `run.freeze()`'s library default stays non-strict, so existing fixture tests are
  untouched.
- **buggy_code:**
  - the `fill` target is the registered pair count; `selected_pairs` counts only mutual twins;
  - a failed clean twin drops its buggy partner (pre-existing select behaviour, asserted);
  - the `src` quota is still enforced;
  - `fill` calls `select` with the item cap 63 (not 24), and "full" means 24 selected pairs;
  - clean items carry the new no-bug-claim leg (greedy only, rubric `buggy_bug_claim`), and a
    fake grader receives `B_PROMPT` verbatim with a distinct cache key; buggy items still carry
    the ≤ 2/11 ban and the 4/6 consequence threshold;
  - the new lint rejects equal twin outputs, forbidden imports and the "Ann Ann" literal-copy
    output, and accepts a `70`-in-`[70, 95, 88]` output;
  - the per-Ask `draws = 0` override generates only greedy for the clean leg and leaves other
    Asks' draws unchanged;
  - the `consequence_class` cap is applied two-pass (non-crash first, then crash ≤ floor(n_nc /
    4)), independent of order; a `t2`-only pilot whose pairs all pass is NOT `ooc` (yield counts
    before the cap); the class mix is written to the report;
  - the per-tier tally: reaching `t2` seeds `fill`'s counters from the pilot's `t2` tally.
- **msdm:**
  - pool loader dedupe (key, folded noun) against the bank and retired items;
  - a pool row → item has `user == contract.prompt` filled in and a carrier from the registered
    10;
  - `MIN_AGREE == 7`, `DIRECT_T == 1.0`, `COMPLY_THRESHOLD == 0.8`, `MIN_OPTIONS == 2` asserted
    unchanged;
  - `pool=ext` absent → elicit inputs byte-identical to today;
  - the domain cap; the type mix is reported, not capped;
  - a non-member gold, and a label-QA verdict outside {keep, keep_with_aliases}, each fail the
    validity legs;
  - a pool item with Opus answers gets built options that can carry `opus_typical` and
    `peer:qwen3.6-27b` (Qwen's label comes from `gold`); a pool item without them still gets its
    normalised gate.json peers;
  - `msdm.question()` prefers `item["question"]`, and a registered item with no `question` is
    unchanged;
  - `pool="ext"` flows through `_plan` / canon / units / build: an ext row reaches the gate log,
    and `pool=True` behaves as `"retired"`.
- **knowledge_cutoff:**
  - pool loader (b1 + the b2 questions joined to `gen_in.jsonl` keys / `user`; b1 string truth →
    `{authored, canonical}`);
  - a pool item's built options include a `peer:` / `legacy:` label (proving peer tiers reach
    `build_options`);
  - content dedupe drops the ESCAPADE b2 paraphrase of its bank item and keeps an unrelated
    question;
  - G0's 7/10 and the incorrect rule unchanged;
  - `truth` is the author's, never VERIFY's;
  - G3 on a refill item;
  - K = 5 seeded order.
- **wrong_intermediate:**
  - multi-pool merge dedupe and the conflicting-id refusal;
  - `MIN_SAMPLE_AGREE == 4`, `HUB_FRAC == 0.03` asserted;
  - the hub share over the union;
  - the entity allowlist rejects the audit's Soviet Union (Q15180) as a company B' and accepts a
    real manufacturer, a record label and a TV network via the frozen class table; a musician B'
    all 100 registered B' pass; the P106 closure assigns novelist → writer, singer-songwriter →
    musician and a physicist → scholar for person_mother / namesake items, in the fixed priority
    order;
  - every pre-existing `ROLE_CUES` entry is byte-identical; each newly admitted template has
    cues; `PROMPT_VERSION` ends with `CUES_VERSION`;
  - person_mother / namesake items get a per-item category from the allowlist or are dropped;
    every template in a shipped set has a `ROLE_CUES` entry; the registered builder's `--check`
    is unchanged;
  - the multi-dir merge prefers round 1's rows and entities, and counts differing later copies
    without aborting;
  - a round-1 item whose hub status flips over the union is reported, not silently changed;
  - caps over the union.
- **multihop_mt_v2:**
  - the S1 + S2 assembly equals the bank's `shortcut_probes` on the 70 bank items;
  - the pool builder drops adversary `problem` / `factual_issue` rows and bank-entity overlaps,
    and selection keeps one item per entity group;
  - `build_fields` seeds `mc[role].gold` before r4 runs, and an item whose r4b list has fewer
    than 4 distractors fails; a refill unit's kind is validated (an invalid kind or a
    disagreement fails the item), and its rivals in `bank_entities` come from its kind's pool;
    `judge_inputs` now requires `units[].kind`; the frozen bank's `--check` still passes;
  - zh runs after r4b: `_zh_problems` sees a validated Chinese name for every option, the target
    and the other bridge, and an item with a problem fails;
  - `relabel_b2` / `subject_item` accept a candidate with no `mc` / `name_forms`; `build_fields`
    runs after relabel and re-runs `mt.stamp` / `creditable` (an item with no creditable form
    fails);
  - the review step's extra ablations are must-not-reach legs, and a review `factual_issue`
    fails the item;
  - `select_refill` keeps items by finalize's greedy `taken` rule, true 3-hop first, then by
    margin;
  - `build_fields` sets the bank `readout`, `n_render_tokens` and the 3-hop `CTX_QUESTION`, and
    stamps `probe_token_lens` with an explicit Qwen tokenizer for qwen3.6-tokenizer subjects;
    one refill item never flips the family's read plan (judge_inputs check);
  - the staged gate with a fake runner fails an item on a shortcut hit;
  - gate constants unchanged;
  - a built refill item passes `judge_inputs.check_bank` and `families.required_item_fields`;
  - under `WSB_BANK_ROOT` a fixture set with an adapted-only mh2 id judges with rc 0 (a C2
    regression for adapted-only ids).
- **No pre-existing test assertion changes.** The sanctioned exceptions: (i) if a test pins
  `families._buggy_code`'s leg list for clean items, it gains the new leg (§2.2); (ii) on the
  stacked `camila/0066-wi-cues` branch only, pending Camila's OK, the §5.4 stamp tests
  (`test_rename_wrong_intermediate.py:87` + `PRE_PROMPTS_SHA`, and the ATI rename test via the
  restamp). Any other diff
  under `tests/` that modifies an existing assertion is a review blocker.

## 11. Revisions after critique round 6 (applied; they supersede the sections above where they differ)

1. **`units[].kind` path syntax (blocker).** `run.has_path` / `get_path` (run.py:587-603) walk
   dict keys only. So `units[].kind` in `judge_inputs.REQUIRED_ITEM_PATHS` would read as missing
   on every item, which breaks `tests/test_adapt.py:890-900` and every mh2 freeze. The same change
   teaches `has_path` / `get_path` an `a[].b` form: true iff `a` is a non-empty list and every
   element has `b`. It gets its own unit test, and `run.py` (`has_path`) is in the Files list. The
   pre-existing `missing_required(family, registered items) == []` assertion must stay green
   unmodified: every registered v4 mh2 item carries `units[].kind`.
2. **The WI calibration runs offline.** The registered B' claims are not in the repo:
   `wikidata_v3.json` holds labels / aliases, and items hold only QIDs. So the build-time script
   (`scripts/build_wd_tables.py`, run on the box: it reads the pool's `entities.json` by exact
   path, then fetches what is missing from Wikidata) also writes
   `src/wsbench/adapt/data/wd_registered_bprime.json`. That is a small CC0 table `{qid: {P31,
   P106, P39}}` for the 100 registered B', vendored next to `wd_class_parents.json`. The
   "all 100 registered B' pass" test reads only these vendored tables. The tables are produced in
   the implementation PR if the box has network access to Wikidata; otherwise in the pin PR (§8
   step 1), with the test skipped and saying why until they exist.
3. **Where `CUES_VERSION` goes (stacked branch).** It is inserted before the forms tag:
   `PROMPT_VERSION = MC_CALL_VERSION + "+" + AUDIT_VERSION + "+" + CUES_VERSION + "+" +
   FORMS_VERSION + "+" + BANK_TAG`. That keeps `tests/test_r4c_wrong_intermediate_forms.py:59`
   (`endswith("+wbforms-v4+bank-v4")`), `test_r4_review208.py:206` and
   `test_r4e_split_and_option_audit.py:169` green unmodified. The new test checks that
   `"+" + CUES_VERSION + "+"` is in `PROMPT_VERSION` (it does not require `endswith`).
4. **No cached call is re-asked (stacked branch).** `CUES_VERSION` is stripped in **both**
   `judge._mc_version` (judge.py:741-748) and `judge._audit_version` (751-756, which today strips
   only `FORMS_VERSION`; the rival-audit calls key on it, judge.py:1045). Tests check that
   `_mc_version(PROMPT_VERSION)` and `_audit_version(PROMPT_VERSION)` are byte-identical before
   and after the bump, and that the digest / summary call fingerprints do not key on the family
   `PROMPT_VERSION`. If any does, that path strips the tag too. Only then does "no registered
   verdict can change" hold, which is the premise for restamping the ATI entry instead of
   re-gating it.
5. **Which templates the main PR admits vs the stacked branch.**
   - **Main code PR:** `ADAPT_TEMPLATE_CATEGORY` is empty, and the adapt `category_of` admits a
     template only if `template in ROLE_CUES`. Source 0 therefore recovers only person_mother /
     namesake, through `ADAPT_ITEM_CATEGORY`. The lower-`min_sl` re-scrape (a) covers only
     templates that already have both a category and cues. GLM's source-0 gain is 33 → about 36.
   - **Stacked `camila/0066-wi-cues` (merged on Camila's OK):** the four already-screened
     templates (film_screenwriter, song_composer, tv_creator, novel_publisher) enter
     `ADAPT_TEMPLATE_CATEGORY`. The cues for those four and for the five re-scrape templates are
     added, along with the `CUES_VERSION` bump, the ATI restamp, the sanctioned stamp-test edits,
     and the cue tests (pre-existing entries byte-identical, `+CUES_VERSION+` present, both strip
     functions unchanged).
   - **§8:** source 0's four, and the re-scrape's (b) templates, run only after that branch
     merges. The extra source-0 gain from them (the 2 film_screenwriter items on GLM) is counted
     only then.
6. **Minors applied:**
   - **The greedy-only clean leg** is its own group `bugclaim`, not `surface:*`, which
     `gate_record` treats as alternatives. Its leg `rate` is 1.0 (pass) or 0.0 (fail), so it
     never sets the item rate to None.
   - **Freeze enforces the new legs.** A buggy clean row without a `bugclaim` leg, or a built
     msdm row without its member / QA legs, counts as not passing in freeze's selection and in
     the `stop_status` recheck. A set therefore cannot ship rows that skipped the new legs.
   - **mh2 review ablations** are stored in the item's `shortcut_probes` with `origin:
     "review"`, so `mhmt2.verdict` / `stage_asks` see them on any regate or regrade.
   - **Paths and names:**
     - the WI judge files are `src/wsbench/evals/wrong_intermediate/{judge,prompts}.py`;
     - the msdm carrier draw is seeded by the registered header's `set_c_seed` value (20261023)
       plus the id, a seeded choice among the 10 registered carriers;
     - `fill` today applies conditions 1, 2 and 5, and the crash-cap stop is new;
     - `stop_status` takes `(have, target, tried, landed, n_min, y_min, exhausted, budget_hit,
       cap_binding=False, hold=None)`;
     - the CLI is `python -m wsbench.adapt refill model=<m> families=...`;
     - the Files list gains the stacked-branch files.
   - **Pinned MEMBER / QA prompts** are un-doubled (`{{` → `{`) for `str.replace`, as `B_PROMPT`
     is.
   - **Freeze guard for the five families** is keyed on the **absence of a `refill` block** in
     `report.json` while `n_items < target` (`n_pairs < 24` for buggy_code), not on `untried`.
     msdm / kcutoff are already `partial` from their retired rows. The `untried` rule still
     covers the `fill` / `auto` families.

7. **knowledge_cutoff content dedupe (Camila 2026-11-04, after implementation).** The dedupe
   exists to catch paraphrases of BANK items. So:
   - against the bank refs (bank + `retired_panel_gate` + `g3_leak_items` + `retired_hygiene`): the
     non-null (event_date, truth) + shared-entity branch, or question-token Jaccard ≥ 0.6 **after
     stopword removal**;
   - within the pool: only exact or near-exact duplicates (stopword-free Jaccard ≥ 0.9), with no
     truth branch.

   Templated questions about different entities (US ambassador to China vs to the UK) both
   survive. The plain-token ≥ 0.6 rule within b1 ∪ b2 had dropped about 395 rows (≈ 7%), many of
   them such templated pairs.
8. **buggy_code `bugclaim` leg on an empty greedy (Camila 2026-11-04).** An empty continuation is
   non-evidence, as in the leak legs (finalize fix 1). Because the leg is greedy-only, that means
   undecided, so it **fails** (reason "the greedy continuation is empty"). It never passes.
9. **multihop Wikidata class QIDs:** every work / event class QID is verified against Wikidata
   (through the existing fetch path), with its label recorded next to it in the code, before
   merge. A small real smoke (~20 candidates) of the adversary, the r4 chain and the Wikidata
   checks runs before merge.
10. **`claude_budget`** counts cache hits too. That is deliberately conservative, and the
    docstring says so.

11. **multihop smoke results (2026-11-04, ~20 candidates, live Claude + Wikidata, no GPU).** All
    three never-run paths (the adversary, the Wikidata kind checks, and r4 → r4b → build → zh →
    stamp) ran end to end. Three bugs were fixed:
    - the adversary call now sends the GW structured-output schema;
    - adversary retries are fresh calls;
    - Wikidata disambiguation / name pages count as unresolved, not as "not a person".

    Two consequences:
    - **MC guesser gate (decided: over-gate items ship).** This follows the registered bank's
      precedent (19 of 70 v4 lists over the gate) and Camila's rule that per-model targets need not
      be frontier-unguessable (D4). r4b's guesser screen improves lists, but an item over the gate
      still ships. `build_fields` fails an
      item only when it has fewer than 4 distractors. The smoke had 13 of 17 three-hop-heavy items
      over the gate, because related golds pair up across the two lists. The over-gate count is
      in the r4b build output (`n_over_gate`). `build_fields` returns it, and it is recorded per set
      in `report.json` (`families.multihop_mt_v2.mc_over_gate` plus a "mc over gate: N/M items" (r4b counts items, not lists)
      note segment), quoted in each set's `AUDIT.md` and its `adapted/README.md` row. The floors
      show the effect. Enforcing the gate would fail most 3-hop refill items, and that
      is flagged for Camila.
    - **Cost:** the r4 chain costs about 68 Claude calls per item at `--rounds 1`
      (`R4_CALLS_PER_ITEM` = 70). The multihop Claude cost for GLM is therefore about 5k or more,
      not 1.5k; the §8 GLM estimate is about 30 B300-h and about 14–16k Claude calls. The adversary
      runs on a bounded thread pool (16 workers, the shared RPM pacer, order-independent output),
      which keeps decision 7's ~2.5k run to roughly 30–40 min instead of about 8 h.
    - **Tokenizer:** `build_fields` needs the `gpu` extra (transformers), so it runs with
      `/root/torchvenv/bin/python` on this box. `subject_tokenizer` fails loudly when the extra is
      missing; it never silently skips the stamp.

12. **Families merged on main while this plan was open (noted, not built here).**
    - **hinted_cutoff** (plans 0063 / 0064): pairs built from Qwen3.6-27B's own behaviour. The
      influenced twin is past Qwen's effective cutoff, and the controls are pairs Qwen answers
      without the hint. Since plan 0064 it reads the prompt only, with Qwen's chat-templated ids.
      For an adapted set the pairs must be re-derived on the subject: its own no-hint failures
      past its cutoff, plus matched controls, rendered in the subject's template. Until a port
      exists, the family is `absent` in every adapted set, with that reason in `report.json`.
    - **math_shortcuts** (plan 0065): labels come from Qwen's own greedy correctness plus its
      10-sample show-your-work explanations (I = an illogical shortcut, N = valid derivations).
      An adapted set needs that labelling re-run on the subject, with the frozen judge
      unchanged. Until then it is `absent`.

    Neither family has a refill route, and neither is in `refill.POLICY`. A port is a separate
    plan, like Phase E's.

13. **Pools built and pinned (§8 step 1, 2026-11-04).** `scripts/build_adapt_pools.py all` on the
    box, from the default exact source paths (`/workspace/gw-evals-feas/outputs/feas/self_answers/`,
    `/workspace/gw-evals-feas/outputs/feas/cutoff_confab/scale/`,
    `/workspace/gw-mh-v2/outputs/multihop_v2/`), written to `$WSB_POOL_DIR` =
    `/workspace/wsb-runs/pools/` (box only, never committed). Two builds gave identical bytes.
    `refill.POOL_SHA256`:

    | pool | rows | sha256 |
    |---|---|---|
    | `msdm_pool.jsonl` | 7,782 (of 7,878; 95 bank / retired keys, 1 duplicate noun) | `b1936e2efc4ac61230f69ab4d70da622ba1da83e7348ed25d24c795e6af3b073` |
    | `kcutoff_pool.jsonl` | 5,273 (115 bank-ref ids, 34 bank-ref paraphrases dropped) | `0597d19caace1866a860dffb697a024e4ee12ab5245090591f54c6ba9ff3e614` |
    | `mh2_pool.json` | 1,312 (1,384 clean minus 72 sharing a bank entity; 831 three-hop; 808 entity groups) | `553df6a6de636ddad043b63bcb21b7e38cc35cb2a89a13f7749e6910d2b29926` |

    `mh2_pool.v2.json` (decision 7) was built on 2026-11-04 for GLM-5.3 (see 15).

14. **multihop_mt_v2 on GLM-5.3: no ooc while a harder level is untried (Camila-delegated,
    2026-11-04).** The 2-hop pilot passed 2 of 300 pool candidates (prior 9 of 70), about 2.97 %,
    just under `y_min`. But 266 of the 296 gate failures passed G1 and recall and then reached
    the target through an S1 / S2 shortcut ablation: the subject was too capable for the
    2-hop level, not incapable. `refill` now asks the family's `untried_levels(model)` hook
    (`mhmt2`: the pool's 3-hop candidates not yet gated) and declares no ooc while any level
    remains untried. The pilot still stops at `n_min`. Once every level has been gated, the §1.2
    rule applies unchanged on the easiest-level tally. The refill block records
    `untried_levels`. GLM's own run gated the 3-hop candidates through the direct
    `mhmt2.refill_wave` loop before this landed (recorded as a deviation in its report and audit).
    **Known limitation of `contains_target` (not changed):** it matches the target anywhere in
    the 24-token continuation, so a verbose subject's explanation ("**Socrates** (e.g., Plato
    was … pupil of Socrates)") can count as a shortcut hit. On GLM's pilot, matching only the
    answer head would have changed 12 of 276 shortcut failures (1 of 54 on the registered
    bank). The registered rule stays as it is.
15. **`mh2_pool.v2.json` built and pinned (decision 7, 2026-11-04).** GLM-5.3's multihop_mt_v2
    refill did not fill on the 1,312 v1 candidates, so `scripts/build_adapt_pools.py mh2
    --adversary` ran the GW adversary (Opus, 16 workers) over the S1-only generator candidates:
    3,384 items = v1's 1,312 plus 2,072 new clean ones (587 adversary drops, 125 bank-entity
    drops; 2,276 three-hop; 1,555 entity groups), sha256
    `7e3e4d16da32ddef44a9d452474a4ddb12cf1be104ec6c8161bfebc9bf394629`. Unlike v1, this build is
    not byte-reproducible from scratch: adversary retries are fresh Claude calls (§11.11). The
    pinned file and its adversary reply cache (`mh2_adversary_s1.*`) are kept on the box under
    `$WSB_POOL_DIR` (cache in `mh2_adversary_cache/`). `mhmt2.load_pool` prefers it once pinned.

## Files

```
plans/0066-refill-small-families.md            (this plan)
src/wsbench/adapt/refill.py                    new: POLICY, stop_status, refill dispatcher
src/wsbench/adapt/__main__.py                  + `refill` subcommand; freeze allow_untried
src/wsbench/adapt/run.py                       has_path/get_path a[].b; fill: pair have/target (select cap stays 63), stop_status; freeze guard + change text; _regrade_asks clean leg
src/wsbench/adapt/families.py                  _buggy_code: clean-twin no-bug-claim leg
src/wsbench/adapt/lint.py                      _buggy: twin-differ, IO, literal-copy guards; new multihop_mt_v2 bridge/target lint
src/wsbench/adapt/msdm.py                      pool=ext, waves, item construction, domain cap, membership / label-QA validity legs
src/wsbench/adapt/kcutoff.py                   pool=ext, waves, domain cap, mix report
src/wsbench/adapt/wrong_intermediate.py        multi-dir pool, hub share over union, CATEGORY_P31 entity check
src/wsbench/adapt/mhmt2.py                     pool gate, entity rule, REVIEW_SYS legs, build_fields stage
src/wsbench/adapt/grade_llm.py                 per-Ask rubric path (buggy B_PROMPT), rubric id in the cache key
$WSB_POOL_DIR/{msdm_pool.jsonl,kcutoff_pool.jsonl,mh2_pool.json}   box-only, NOT committed; sha256 pinned in refill.POOL_SHA256 (decision 3)
scripts/build_adapt_pools.py                   new: builds the pool files from the GW outputs, sha-stamped
scripts/build_mh2_bank_v2.py                   rules refactored into importable functions (output byte-identical: --check)
scripts/{r4_mc_distractors,r4b_mc_refine,build_r4b_mc_banks}.py   adapted gate-log payloads as --bank input
src/wsbench/adapt/judge_inputs.py              multihop_mt_v2 requires units[].kind
src/wsbench/adapt/gate.py                      per-Ask draws override (clean-twin greedy-only leg)
src/wsbench/adapt/data/wd_class_parents.json   frozen Wikidata class -> superclass table (WI entity check)
src/wsbench/multitoken/family.py / registry    adapted-only mh2 ids under WSB_BANK_ROOT (if freeze does not write overlays)
.claude/skills/adapt-bank/SKILL.md             §3a, runbook, status tables
.claude/skills/adapt-bank/references/{families,porting}.md
.claude/skills/wsb-new-questions/references/families.md
tests/test_adapt_refill.py, tests/test_refill_{buggy,msdm,kcutoff,wi,mh2}.py   new
scripts/build_wd_tables.py; src/wsbench/adapt/data/{wd_class_parents,wd_registered_bprime}.json   vendored CC0 Wikidata tables
--- stacked branch camila/0066-wi-cues (Camila's OK) ---
src/wsbench/evals/wrong_intermediate/{judge,prompts}.py   cues for 9 templates, CUES_VERSION, strip in _mc_version + _audit_version
evals/wrong_intermediate/README.md             role-cue sentence + version row
evals/baselines/anti_text_inversion.json; scripts/ati_restamp_wi_cues.py   ATI restamp
tests/test_rename_wrong_intermediate.py         sanctioned stamp edit (:87, PRE_PROMPTS_SHA)
```
