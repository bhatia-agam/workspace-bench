# plans/

Design plans for the 2026-09-15..17 restructure that gave the benchmark its nine-family shape
and shared package. Historical: they record what was decided then, not the current state.
Numbering gaps (0009, 0011) are plans that were reverted. Families added later and every
read-site change since are documented in the family READMEs (`evals/<family>/README.md`) and
the git log.

Later plans in this directory follow the same `NNNN-<name>.md` convention. 0032
(`0032-wsb-bp-infra.md`) is the shared read / summarize / judge machinery of the 2026-10-30 fix
campaign; 0033-0056 are that campaign's family workstreams, one plan per family PR.

The family PRs were written in parallel and several picked the same number; the integration merge
kept the number of the first-merged plan and renumbered the rest. Code, READMEs and tests of the
renumbered families were updated to the new number; an old number left in a shared doc, or in a
plan file (historical, not rewritten), means the plan below by family context:

| old | new | plan |
|---|---|---|
| 0033 | 0047 | `0047-wsb-bp-brew.md` (0033 stays `0033-wsb-bp-typo.md`) |
| 0036 | 0048 | `0048-wsb-bp-multihop.md` (0036 stays `0036-wsb-bp-arithmetic.md`) |
| 0037 | 0049 | `0049-wsb-bp-conjunctive.md` (0037 stays `0037-wsb-bp-jailbreak.md`) |
| 0037 | 0050 | `0050-wrong-bridge-mc.md` |
| 0037 | 0051 | `0051-wsb-bp-basic-readout-mt.md` |
| 0038 | 0052 | `0052-wsb-bp-agentic.md` (0038 stays `0038-wsb-bp-chain.md`) |
| 0039 | 0053 | `0053-wsb-bp-basic-readout.md` (0039 stays `0039-wsb-bp-association.md`) |
| 0040 | 0054 | `0054-wsb-bp-multilingual.md` (0040 stays `0040-hallucination-to-hb.md`) |
| 0042 | 0055 | `0055-wsb-bp-role-bound.md` (0042 stays `0042-wsb-bp-jlens-pr.md`) |
| 0043 | 0056 | `0056-wsb-bp-user-modeling.md` (0043 stays `0043-wsb-bp-relational-multihop.md`) |

(Family keys in this list and in every plan file are the keys of the plan's own date; plan 0101
renamed eight of them on 2026-11-20, see the key table in the repository README. Plan files are
history and are not rewritten.)

Campaign plans by number: 0031 agentic clean twins, 0032 infra, 0033 typo / typo_mt, 0034 mcdm,
0035 directed_modulation, 0036 arithmetic, 0037 jailbreak, 0038 chain, 0039 association, 0040
hallucination -> HallucinationBench, 0041 multihop_mt_v2, 0042 jlens_concept_pr, 0043
relational_multihop, 0044 knowledge_cutoff, 0045 introspection, 0046 moral_rationale, 0047 brew,
0048 multihop, 0049 conjunctive_association, 0050 wrong_intermediate, 0051 basic_readout_mt, 0052
agentic_misalignment, 0053 basic_readout, 0054 the four multilingual families (v2 banks,
`mc+regex`), 0055 role_bound_association, 0056 user_modeling (um-v3.2), 0058 medical_diagnosis{,_alt}
removed and unverbalized_hint retired for now.

Plans after the campaign:

| plan | family / scope |
|---|---|
| 0062 | `0062-nyt-connections.md`: the `nyt_connections` family (model-specific; ids-only NYT Connections bank v1, per-slot MC on the layered digest; bar = beat the prompt-only floor) |
| 0065 | `0065-math-shortcuts.md`: the `math_shortcuts` family (model-specific; Omni-MATH problems answered with no working, I = later explained by an illogical shortcut, N = validly; the frozen GUESS judge on the post-problem readouts; headline I − N flag rate). **Dropped 2026-11-05 (plan 0069).** |
| 0068 | `0068-buggy-leak-rubric.md`: buggy_code's adapt leak leg graded on the bug mechanism (`buggy_leak_mechanism` rubric), not as "the expected answer" of the whole cause (#289 L1); `adapt regrade legs=`; regrade of the shipped sets |
| 0069 | `0069-drop-math-shortcuts.md`: drop the `math_shortcuts` family (Camila 2026-11-05); a revert of #271 onto main, plan 0065 kept as history |
| 0070 | `0070-prompt-only-reply-free.md`: the prompt-only control never reads a reply (token-level cut at the prompt's end, `prompt_cut: reply-free-v2`); the six affected families' floors re-measured on the reply-free input, on the 2026-11-04 refreeze instruments after the 2026-11-17 port onto main |
| 0071 (ATI all-readers-fail) | `0071-ati-all-readers-fail.md`: the anti-text-inversion subset keeps only the items EVERY panel reader fails (gate `panel-v2`; issue #358, PR #359). Written on main the same week as the logit-lens plan below and given the same number; "plan 0071" in `text_inversion.py`, `results.py` and `runner.py` comments about the ATI gate, `ati_n_ids` or `n<20 (ATI)` means this one |
| 0071 (logit-lens floor) | `0071-logit-lens-floor.md`: cited as "plan 0071 (logit-lens floor)". A frozen logit-lens final-layer floor (`evals/baselines/logit_lens.json`, the bench's own `logit_lens` method at layer 63, the last block, judged by each family's summary instrument; a third report column, never in the macro) |
| 0072 | `0072-adapted-refresh-after-overhaul.md`: refresh the ten plan-0060 adapted sets after the 2026-11-05 overhaul (#295-#334, #344): impact per family, re-freeze order, new-item profiling, adapted option-list leak screen, floors after #350, GLM 4-lens re-judge, cost (draft) |
| 0081 | `0081-remove-unverbalized-hint.md`: remove the `unverbalized_hint` family (Camila 2026-11-07: outdated; retired since plan 0058): registry `REMOVED_FAMILIES`, code / bank / tests / examples / NOTICE section deleted, `RETIRED_FAMILIES` kept empty (tests on a stand-in) |
| 0085 | `0085-freeze-strict-ati.md`: the strict-ATI macro for Qwen3.6-27B frozen at 8 families (`ati-subset-v2`, Camila 2026-11-08): poetry admitted by exception, model_multihop's entry pinned from its family-specific panel run (`mmh_bridge`), nyt_connections and hinted_cutoff out |
| 0088 | `0088-glm-ati-subset.md`: GLM-5.3's committed ATI subsets (`adapted/glm-5.3`, Camila 2026-11-09): A (4-reader all-fail) default and B `with_qwen27b`; adapted macro exceptions per entry (poetry, wrong_intermediate, model_multihop); nyt_connections gated but off by default (`ati_opt_in=`, slot-id scope); GLM gate deviations recorded as provenance |
| 0089 | `0089-rebuild-agam-sets.md`: rebuild Agam's five adapted sets (gemma-4-31b-it, glm-5.3-flash, kimi-k2, olmo-3.1-32b, qwen3.6-35b-a3b) fresh to the ten sets' standard (Camila 2026-11-15): glm-5.3-flash on its own built vLLM app, kimi-k2 weights volume, the five keys in `PLAN_0075_SETS` |
| 0101 | `0101-rename-and-category-dirs.md`: the multi-token families take the plain keys (`basic_readout_mt` -> `basic_readout`, `multihop_mt` -> `multihop`, `multilingual_mt` -> `multilingual`, `typo_mt` -> `typo`), the single-token ones become `<key>_st`, and every family directory moves under its category (`evals/<category>/<family>/`, `wsbench.evals.<category>.<family>`); no instrument changes (`scripts/manifest_0101.py --check`); one-shot `scripts/migrate_0101.py` (record: `scripts/migrate_0101_applied.json`) |
| 0105 | `0105-jlens-comparison-category.md`: the category `precision` ("Precision") becomes `jlens_comparison` ("J-lens comparison") (Camila 2026-11-21): directory pair moved byte-identical, family key `jlens_concept_pr` and metric name `precision` unchanged, `registry.LEGACY_CATEGORIES`, ledger entry for the one moved manifest row (`list.category`) |
| 0107 | `0107-association-category.md`: the family `association` moves from the category `basic` to the category `association` (Camila 2026-11-21): `evals/association/association/`, `wsbench.evals.association.association`, `group="association"`; location only, no instrument, tier or number moved; `registry.LEGACY_FAMILY_CATEGORIES` + a `repo_path` clause for stored `evals/basic/association/...` strings; the manifest ledger's per-family `CATEGORY_MOVES` rule declares the one moved row (`list.category`) |
