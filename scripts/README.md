# scripts/

What each script here is for. These are the builders of the question banks, the jobs that ran
the floors, and the checks that were run on results. They are not part of the `wsbench`
package: nothing in `wsbench run` needs them.

Three things to know before moving or deleting one:

- Many are loaded by tests by their path, and some by `src/wsbench/adapt/`. Search for the
  script's name over the whole repository, `evals/` and `adapted/` included, before you move it.
- A builder is the record of how a frozen bank was made. It stays even when the bank will never
  be built again; the eval's page under `evals/` links to it.
- Scripts whose job is done and that nothing names live in [`archive/`](archive/README.md).

Every script has a row below; `tests/test_scripts_index.py` fails when one is missing. A script
that starts a remote job says "on Modal".

## Question banks, by eval

| script | what it does |
|---|---|
| `brmt_readme.py` | Rewrites the prompt blocks and counts in the `basic_readout` page from the code and the bank. |
| `build_brmt_v2.py` | Builds `items_v2.json` of `basic_readout`: question form, name forms per language, new distractors, gates. |
| `build_basic_readout_v2.py` | Builds `items_v2.json` of `basic_readout_st`: question-form prompts, frozen options, the gate on the reference model. |
| `build_mh2_bank_v2.py` | Builds `items_v2.json` of `multihop` from the first bank: same items, added unit kinds and forms. |
| `evidence_mh2.py` | Offline evidence for the `multihop` fixes, from cached readouts and the bank. |
| `build_multihop_mc.py` | Builds `items_v2.json` of `multihop_st`: the frozen multiple-choice block of every item. |
| `build_multilingual_v2.py` | Builds `items_v2.json` of the four multilingual evals from the first banks, offline. |
| `multilingual_v2_curation.py` | The hand-reviewed tables that `build_multilingual_v2.py` reads. |
| `typo_mt_drop_arith.py` | Wrote `items_v2.json` of `typo` without the arithmetic items, and the same change in the per-model sets. |
| `mcdm_bank_v2.py` | Builds `items_v2.json` of `multi_concept_directed_modulation`: the first bank plus the entity items. |
| `poetry/author_couplets.py` | Authors candidate couplets for `poetry` with a Claude model. |
| `poetry/build_mc.py` | Builds the rhyme-word candidates of `poetry` items. |
| `poetry/opus_gate.py` | The gate that keeps a `poetry` item only when a prompt-only Claude reader fails it. |
| `poetry/qwen_gate.py` | The rhyme gate of `poetry` on the reference model: request rows and the grade. |
| `build_chain_v2.py` | Builds `items_v2.json` of `chain_intermediates`: two-digit intermediates, frozen option lists. |
| `build_chain_v3.py` | Builds `items_v3.json` of `chain_intermediates`: the kept items plus new gated chains. |
| `rescore_chain_cached.py` | Re-scores cached `chain_intermediates` runs with the fixed quote check; no judge calls. |
| `buggy_twin_gate_modal.py` | Gates new clean twins of `buggy_code` on the reference model, on Modal. |
| `buggy_twin_gate_grade.py` | Grades the generations of that gate with a Claude model. |
| `association_distractors.py` | Authors, lints and screens the option lists of `association`. |
| `association_hard_grid.py` | The option-grid pass of `association_hard`; its output is committed beside the bank. |
| `association_hard_forms.py` | The name-forms pass of `association_hard`; its output is committed beside the bank. |
| `association_hard_forms_audit.py` | Audits the accepted forms of new `association_hard` golds; a list read by hand. |
| `association_hard_reguess.py` | Re-measures an options-only guesser on `association_hard` in the bank's option order. |
| `build_association_hard_bank.py` | Builds the `association_hard` bank from the candidate file and the committed passes. |
| `build_association_hard_bank_v3.py` | Builds `items_v3.json` of `association_hard`: the kept items plus gated new candidates. |
| `conjunctive/make_v2_bank.py` | Builds `items_v2.json` of `conjunctive_association`: adds the role-swapped twin of each option. |
| `conjunctive/make_v3_bank.py` | Builds `items_v3.json`: adds two never-gold confusers per cluster. |
| `conjunctive/make_v4_bank.py` | Builds `items_v4.json`: wider option lists with authored same-topic confusers. |
| `conjunctive/make_v5_bank.py` | Builds `items_v5.json`: adds equally typical confusers where guessers' picks concentrate. |
| `conjunctive/make_v6_bank.py` | Builds `items_v6.json`: adds distractors that share the third axis. |
| `build_user_modeling_hard_bank.py` | Builds the `user_modeling_hard` bank from the authoring run's candidate files. |
| `umh_wave_candidate.py` | Writes the harder wave's candidate file that the `user_modeling_hard` builder reads. |
| `draft_agentic_targets.py` | Drafts `targets.json` of `agentic_misalignment`: the designed act of each scenario. |
| `draft_agentic_twins.py` | Drafts the clean twins of `agentic_misalignment` items, for review by hand. |
| `agentic_twin_gate_modal.py` | Builds the gate request rows for those twins and converts the sampler's output back. |
| `agentic_twin_gate_grade.py` | Builds and grades the twins' gate. |
| `build_agentic_twins_bank.py` | Builds the `agentic_misalignment` bank with its clean twins from the gate outputs. |
| `build_jailbreak_v2.py` | Builds `items_v2.json` of `jailbreak_recognition`: the positives plus negative controls. |
| `author_roles_lexicon.py` | Drafts `roles_v1.json` of `role_bound_association` with a Claude model. |
| `role_bound_distractors_v3.py` | Authors `distractors_v3.json` of `role_bound_association`. |
| `make_relational_options.py` | Writes the pinned option lists of `relational_multihop` under `tests/golden/`. |
| `moral_distractors.py` | Authors, verifies and screens the `moral_rationale` option lists, then freezes the bank. |
| `moral_adversarial.py` | Builds `items_v4.json` of `moral_rationale`: adversarial option lists. |
| `moral_v5.py` | Builds `items_v5.json` of `moral_rationale`: lists a reader without readouts picks from at chance. |
| `moral_v7.py` | Builds `items_v7.json` of `moral_rationale`: distractors taken from other models' answers. |
| `moral_llm_harvest_modal.py` | Asks two hosted models the `moral_rationale` dilemmas for `moral_v7.py`, on Modal. |
| `moral_rejudge_cases.py` | Re-judges the audited `moral_rationale` cases under a later judge prompt. |
| `build_nyt_connections_bank.py` | Builds the ids-only `nyt_connections` bank from the pilot bank, which stays outside the repository. |
| `nyt_connections_bar.py` | The pre-declared comparison of `nyt_connections` against its prompt-only floor. |
| `build_hinted_cutoff_bank.py` | Builds a `hinted_cutoff` bank from the source project's frozen set. |
| `hinted_cutoff_replay.py` | Validation of `hinted_cutoff`: replays the source's frozen judge answers through this eval's scorer. |
| `introspection_export_vectors.py` | Writes the `introspection` injection vectors as `.npy` files. |
| `introspection_build_v2.py` | Builds `items_v2.json` of `introspection` from the first bank. |
| `introspection_offline_evidence.py` | Offline evidence for `introspection`: the source's verdicts through this repository's scoring. |
| `kc_near_aliases.py` | The near-alias scan of `knowledge_cutoff` and the build of `items_v2.json`. |
| `build_model_multihop_bank.py` | Builds the `model_multihop` bank from the source project's frozen set. |
| `model_multihop_replay.py` | Validation of `model_multihop`: replays the source's frozen summaries and judge answers. |
| `dmo_control_plan.py` | Writes the control-arm plan rows of `model_specific_directed_modulation`. |
| `wrong_intermediate_mc_options.py` | Builds `items_v2.json` of `wrong_intermediate`: frozen options and name forms. |
| `qwen_sample_modal.py` | The one shared sampler of the reference model for item gates, on Modal. |

## Option lists against guessing

| script | what it does |
|---|---|
| `baselines/make_topics.py` | Authors the per-item topic lines the topic guesser sees. |
| `mc_leakage_r4.py` | Rebuilds an eval's distractors until no options-only, described or topic guesser beats chance by the margin. |
| `r4_mc_distractors.py` | Authors same-topic distractor pools for the multiple-choice lists. |
| `r4_mc_select.py` | Chooses each list's distractors from its pool under the lucky-guessing gate. |
| `build_r4_mc_banks.py` | Writes the new bank files of that pass; only the distractor lists change. |
| `r4b_mc_refine.py` | Refines the lists that still let a guesser beat chance. |
| `r4b_confuser_audit.py` | Audits that every list holds two same-topic confusers that stay plausible when the topic is known. |
| `build_r4b_mc_banks.py` | Writes the new bank files of the second pass. |
| `r4c_dirhams_gate.py` | The guesser gate behind one option decision in `basic_readout`; a record, builds no bank. |
| `common_confusers_r5.py` | Adds frequency-matched, equally common confusers to `basic_readout_st` and `association` lists. |
| `mc_options_r5.py` | Rebuilds the option lists of the multi-word evals whose lucky-guessing floors failed the standard. |

## Floors and the anti-text-inversion subset

| script | what it does |
|---|---|
| `ati_qwen_modal.py` | Panel answers from the reference model, on Modal. |
| `ati_qwen_pinned_modal.py` | The same requests at a pinned model revision with read-only weights, on Modal. |
| `ati_openrouter_modal.py` | Panel answers from the hosted readers, on Modal. |
| `ati_openrouter_only_modal.py` | The same with only an OpenRouter secret and a cap on attempts, on Modal. |
| `ati_ask_claude_oauth.py` | Panel answers from the Claude reader with a bearer token, capped and counted. |
| `ati_panel_judge.sh` | Judges every panel answerer's draws with `wsbench run`. |
| `ati_argon_decisive.py` | Counts the items one more panel reader could still move. |
| `ati_rederive.py` | Re-derives the frozen subset file from the stored per-reader statuses; `--check` compares. |
| `ati_restamp_conj_v6.py` | Restamps the frozen entry of `conjunctive_association` for `items_v6.json`, keeping its ids. |
| `ati_restamp_rename.py` | Moves a renamed eval's frozen entry to its new key. |
| `ati_restamp_wi_cues.py` | Restamps the frozen entry of `wrong_intermediate` to the judge instrument with role cues. |
| `prompt_only_qwen_modal.py` | Prompt-only summaries from the reference model at each eval's current read positions, on Modal. |

## Per-model sets (`adapted/`)

| script | what it does |
|---|---|
| `adapt_set.sh` | Builds one per-model set phase by phase; the driver the `adapt-bank` skill uses. |
| `adapt_box.sh` | Runs `python -m wsbench.adapt` on the development machine with its environment set. |
| `adapt_modal.py` | Serves a subject model's generation for the adaptation pipeline, on Modal. |
| `download_weights_modal.py` | Downloads one pinned model snapshot into a Modal volume before a subject's first deploy. |
| `adapt_set_audit.py` | Reports the shortfalls of a per-model set and audits it before it ships. |
| `adapt_gate_on_reference_bank.py` | Gates a subject on the reference model's banks and records its own golds. |
| `adapt_gated_rescore.py` | Re-scores a lens read on the reference banks, on the questions its subject answers. |
| `adapt_rejudge_own_answers.sh` | Re-judges the three own-answer evals of a subject's runs with the subject's golds. |
| `adapt_introspection_modal.py` | The GPU side of `python -m wsbench.adapt introspection` for a subject one GPU serves, on Modal. |
| `adapt_introspection_mp_modal.py` | The same for the large subjects that need several GPUs, on Modal. |
| `adapt_jlens.py` | Builds `jlens_concept_pr` for a new subject: rollouts, read positions, J-lens tokens. |
| `adapt_jlens_modal.py` | Runs `adapt_jlens.py` on Modal for subjects too large for the development machine. |
| `adapt_jlens_glm53_modal.py` | The same recipe for one subject that needs its own fitted lens and several GPUs, on Modal. |
| `fit_jlens_modal.py` | Fits a J-lens for a subject that has no published one, on Modal. |
| `lens_readouts_modal.py` | Reads the per-subject lenses on a per-model set, on Modal. |
| `inkling_parity_modal.py` | The parity check of one subject's checkpoint against its serving stacks, on Modal. |
| `build_adapt_pools.py` | Builds the refill pools and prints the hashes that `wsbench.adapt.refill` pins. |
| `build_mmh_pool.py` | Builds the `model_multihop` candidate pool for the per-model sets. |
| `build_wd_tables.py` | Builds the frozen Wikidata tables of the `wrong_intermediate` entity check. |
| `wd_add_leaves.py` | Adds missing classes to that class table; it only grows. |
| `wrong_intermediate_finer.py` | Builds finer kind lists for dropped `wrong_intermediate` items and re-admits them. |
| `wrong_intermediate_rebuild_mc.py` | Rebuilds the option block of a set's `wrong_intermediate` items. |
| `wrong_intermediate_rescrape.py` | Scrapes more `wrong_intermediate` candidates and keeps the new ones. |
| `agentic_pool_v3.py` | Authors `agentic_pool_v3.json`, a pool of `agentic_misalignment` pairs used only by per-model sets. |
| `agentic_pool_v4.py` | Authors `agentic_pool_v4.json`, the next pool, by the same rules. |
| `agentic_pool_v5.py` | Authors `agentic_pool_v5.json` with a private instance of the previous script. |
| `agentic_pool_v6.py` | Authors `agentic_pool_v6.json` the same way. |
| `agentic_pool_v7.py` | Authors `agentic_pool_v7.json` the same way. |
| `agentic_prefill_check.py` | Checks that each shipped pool original's prefill commits to its target act. |
| `hinted_cutoff_adapt/probe.py` | The cutoff probe of a subject for `hinted_cutoff`. |
| `hinted_cutoff_adapt/pilot_select.py` | Picks the pilot's base candidates from the probe. |
| `hinted_cutoff_adapt/propose_series.py` | Proposes new question series for a date window with a Claude model. |
| `hinted_cutoff_adapt/merge_bank.py` | Merges the source bank's items and the later window's drafted items into one bank. |
| `hinted_cutoff_adapt/subject_ccut.py` | Runs a stage of the source pipeline with the subject in the reference model's place. |
| `hinted_cutoff_adapt/subject_gen.py` | The generation step of that pipeline, served by the subject's Modal app. |
| `hinted_cutoff_adapt/refinish.py` | Re-derives the finish field of generation rows under the current length slack. |
| `hinted_cutoff_adapt/guess_rate.py` | Rates how guessable each answer is from its question alone, one item per call. |
| `hinted_cutoff_adapt/carry_forward.py` | Keeps a twin dropped by an earlier audit out of a re-paired set. |
| `hinted_cutoff_adapt/drop_pairs.py` | Applies audited pair drops so the frozen file, the gate and the bank agree. |
| `hinted_cutoff_adapt/finalize.py` | Writes the subject's frozen file that `python -m wsbench.adapt hinted_cutoff` reads. |

## The fast subset, the residual map and generated pages

| script | what it does |
|---|---|
| `fast_cut_core_half.py` | Cuts a fast subset: a seeded random half of each core eval plus the whole strict anti-text-inversion subset. |
| `fast_refreeze_bank.py` | Cuts a new fast-subset file for evals whose bank changed bytes but not item ids. |
| `residuals_map.py` | Builds one capture's part of `evals/residuals/map.json`. |
| `readme_evals_table.py` | Writes the README's table of evals from the registry. |
| `vendor_hb_index.py` | Copies HallucinationBench's index into `evals/hallucinationbench/index.json`; its only writer. |

## Checks and comparisons of judged runs

| script | what it does |
|---|---|
| `audit_run.py` | Mechanical audit of a judged run directory: mode, sampling, reads and completeness per eval. |
| `cache_only_run.py` | Re-scores an eval from an existing judge cache with no API access. |
| `check_nocot_redaction.py` | Refuses a results tree that republishes readout text of items whose source asks not to be republished. |
| `bank_judge_sanity.py` | Runs the bank judge's sanity cases in `tests/fixtures/` live, three times each. |
| `judge_swap.py` | Compares this repository's verdicts with a source judge's, cell by cell. |
| `summary_mode_dev.py` | Writes the development slice of summary mode and scores its fidelity checks. |
| `summary_mode_compare.py` | Native against summary mode for one method: paired rates and a bootstrap interval. |
| `summary_mode_v2v3.py` | Two summary-mode runs of one method, paired by item. |
| `lite_site_table.py` | The support table behind the `reads=lite` sites of the three association evals. |

## The rename of eval folders

| file | what it is |
|---|---|
| `migrate_0101.py` | The one-shot migration that moved eval folders under their category; kept as the record. |
| `migrate_0101_applied.json` | What that migration applied. |
| `migrate_0101_residue.txt` | What it left for hand edits. |
| `manifest_0101.py` | The manifest of every instrument output that an eval key or path could move. |
| `manifest_0101_declare.py` | The ledger of instrument changes declared since, and the comparison rule. |

## Repository

| script | what it does |
|---|---|
| `gated_merge.sh` | Squash-merges a pull request only when it has checks and every one passed. |
