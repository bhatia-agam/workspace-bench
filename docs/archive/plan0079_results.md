# Plan 0079 results: mOre-lenses O-lenses and neuronpedia J-lenses on the adapted sets

Plan: `plans/0079-more-lenses-adapted.md` (issue #400; code #401, #404, #419, #420, #433). Plot: `docs/archive/plan0079/macro.png`. Per subject: every
`agu18dec/mOre-lenses` checkpoint with a WorkspaceBench tag (inverter, the 4B / 9B `L20`
inverter variant, distill, RL i600) and the subject's neuronpedia J-lens, judged on the subject's
full adapted set (`adapted/<m>/`, `WSB_BANK_ROOT`) and on that set's anti-text-inversion subset
(`adapted/<m>/anti_text_inversion.json`).

## Read and judge (restated)

- Read spec = each checkpoint's `olens.json` at `agu18dec/mOre-lenses@441fd264`: residual after
  block L (base model, adapter off) at every plan cell; inverters `scaled` (frozen global scale,
  `continuation_raw`), distill / RL `unit` (alpha 16000, `concepts_raw`); the vector replaces the
  slot token's input embedding; T 1.0, top-p 0.95, top-k 64, 256 new tokens, thinking off, one
  sample per activation (`prose1`). J-lens: the bench's `JLens` cosine readout, top 10
  (`tokens10`), `neuronpedia/jacobian-lens@e166deb5`.
- **qwen3.5-9b's J-lens is the BASE-model lens**, `qwen3.5-9b-pt/.../Qwen3.5-9B-Base_jacobian_lens.pt`
  (fitted on Qwen3.5-9B-Base, not the instruct model), applied to the chat subject's activations
  (Camila 2026-11-06). Labelled `jlens (base-model lens)` in every table.
- **No OLMo J-lens:** neuronpedia's `olmo-3-1025-7b` lens is fitted on `allenai/Olmo-3-1025-7B`
  (the base model); the subject is `allenai/Olmo-3-7B-Instruct`. No J-lens was fitted.
- Layers: the plan's own layers inside each lens's even band (9B / 4B 10..30 even, 8B
  12..22 + 26..34, 2B / 0.8B 8..22 even = 8 layers; the plans' odd layers 9 / 15 / 21 and the
  last-block 23 / 31 are not read). Every arm of a subject is judged at the same `layers=`.
- Judging: the bench defaults (summary mode, layered digest, Opus 5.5 + family pins),
  `wsbench run all=True` minus `jlens_concept_pr` (blocked) and `introspection` (ooc). ATI scores
  are the same judge caches rescored with `anti_text_inversion=True` (identical `layers=`).
- ATI subset (plan 0071's rule, the subject in the Qwen slot): an item is kept iff the subject,
  the Claude slot (Opus 5.5), astra (`--route openai-wif`) and argon (`--route gemini-wif`) all
  fail every one of 3 guess-form draws; families with n < 20 are shown but out of the ATI macro.
  `multilingual_typo` is out by construction (`ATI_EXCLUDE_ALL`), and the registered hand-audit
  exclusions (`ATI_EXCLUDE`) apply where the same id is in the set.
- Floors: stock-subject-v1 (the subject itself, native single-layer) and po-opus-v1 (Opus reads
  the prompt only, single-layer digest) from `adapted/<m>/floors/floors.json`; neither is the
  lens instrument (8 / 11-layer layered digest). ATI floors: the stock-subject floor's per-item
  verdicts on the ATI ids that have a floor row (its `n=` can be below the subset size).
- A blank ATI cell where `n (ATI)` > 0 means the subset scores no item. Examples: a pair-scored
  family whose ATI ids are halves of different pairs, or a family with <= 5 surviving ids after
  the hand-audit exclusions. jailbreak_recognition's ATI rows also score all of their controls,
  so their `scores.json` `n_items` is larger than the id count; the macro gate uses the id count.
- † = complete:false (out of the macro). MACRO (bench rule) = `results.macro` of that view;
  MACRO common = families complete in every arm's view of that scope. CI = normal approximation
  from the family CIs.

## Snapshot and caveats

- **Sets: main `3c552e22`.** The store is keyed by item, so a refresh only produces and judges
  new ids (plan 0079 §5's incremental store, keyed by row). The ATI files record each family's
  `bank_sha`; a family whose bank has changed fails closed (`subset_entry`) until it is re-gated.
- **Set-side gaps (allow_missing, † and out of the macro):** basic_readout on qwen3-8b (1 item),
  qwen3.5-2b (1) and qwen3.5-0.8b (2) has no read position on the subject's render (#289), and
  qwen3.5-9b multihop_mt has items with a span shorter than the family minimum.
- **One-item judge failures (†, out of that arm's bench macro):** a layered digest failed again
  on every retry, so the family counts differ by one between some arms. The affected cells are the
  † rows in the per-subject tables. "MACRO common" compares like with like.
- **Families with no items on this set:** the family is not run, and its old results are listed
  as "not re-judged" and excluded. These are the plan 0075 out-of-capability families:
  qwen3.5-0.8b multihop, qwen3.5-2b wrong_intermediate and qwen3.5-4b multilingual_multihop. The
  same applies to ATI families with 0 ids. After plan 0083's frac drop (#436),
  arithmetic_intermediates keeps 0 or 1 ATI ids on 9B / 8B / 4B (the dropped frac items were
  the ones every reader failed), so it leaves the ATI macro there.
- agentic_misalignment is never in the macro (pair-scored, < 20 pairs). Its † mostly comes from
  Opus refusals.
- The `po-opus-v1` floor in `floors.json` predates #350 (prompt-only re-measure). Treat it as
  indicative only.


## Headline: macro per subject and stage (full set / ATI subset)

| subject | stage | full macro [CI] (fam) | ATI macro [CI] (fam) | Agam README headline_23 |
|---|---|---|---|---|
| qwen3.5-9b | inverter | 0.498 [0.48,0.52] (25) | 0.216 [0.15,0.29] (3) | 0.522 |
| qwen3.5-9b | inverter L20 | 0.521 [0.50,0.54] (26) | 0.211 [0.14,0.28] (3) | — |
| qwen3.5-9b | inverter L20 (L20..30 view) | 0.484 [0.46,0.50] (25) | 0.205 [0.14,0.27] (3) | — |
| qwen3.5-9b | distill | 0.548 [0.53,0.57] (26) | 0.190 [0.12,0.26] (3) | 0.595 |
| qwen3.5-9b | RL i600 | 0.597 [0.58,0.62] (26) | 0.191 [0.13,0.26] (3) | 0.659 |
| qwen3.5-9b | jlens (base-model lens) | 0.199 [0.18,0.21] (26) | 0.051 [0.01,0.09] (3) | — |
| qwen3-8b | inverter | 0.391 [0.37,0.41] (25) | 0.089 [0.05,0.12] (4) | 0.417 |
| qwen3-8b | distill | 0.405 [0.39,0.42] (25) | 0.109 [0.07,0.15] (4) | 0.450 |
| qwen3-8b | RL i600 | 0.514 [0.49,0.53] (25) | 0.109 [0.07,0.15] (4) | 0.537 |
| qwen3-8b | jlens | 0.142 [0.13,0.15] (25) | 0.035 [0.01,0.06] (4) | — |
| qwen3.5-4b | inverter | 0.499 [0.48,0.52] (24) | 0.137 [0.08,0.20] (2) | 0.439 |
| qwen3.5-4b | inverter L20 | 0.502 [0.48,0.52] (24) | 0.118 [0.05,0.18] (2) | — |
| qwen3.5-4b | inverter L20 (L20..30 view) | 0.475 [0.46,0.49] (24) | 0.118 [0.06,0.17] (2) | — |
| qwen3.5-4b | distill | 0.526 [0.50,0.56] (24) | 0.167 [0.10,0.24] (2) | 0.517 |
| qwen3.5-4b | RL i600 | 0.604 [0.58,0.63] (24) | 0.167 [0.11,0.23] (2) | 0.595 |
| qwen3.5-4b | jlens | 0.264 [0.24,0.29] (23) | 0.049 [0.00,0.09] (2) | — |
| qwen3.5-2b | inverter | 0.431 [0.41,0.45] (14) | 0.062 [0.03,0.10] (2) | 0.336 |
| qwen3.5-2b | distill | 0.504 [0.46,0.55] (14) | 0.072 [0.04,0.11] (2) | 0.421 |
| qwen3.5-2b | RL i600 | 0.585 [0.56,0.61] (14) | 0.124 [0.08,0.16] (2) | 0.477 |
| qwen3.5-2b | jlens | 0.209 [0.18,0.23] (14) | 0.015 [-0.00,0.03] (2) | — |
| qwen3.5-0.8b | inverter | 0.297 [0.26,0.33] (11) | 0.032 [0.01,0.05] (2) | 0.300 |
| qwen3.5-0.8b | distill | 0.327 [0.30,0.36] (11) | 0.036 [0.01,0.06] (2) | 0.359 |
| qwen3.5-0.8b | RL i600 | 0.383 [0.36,0.40] (11) | 0.036 [0.01,0.06] (2) | 0.406 |
| qwen3.5-0.8b | jlens | 0.126 [0.09,0.16] (11) | 0.004 [-0.00,0.01] (2) | — |

## ATI subset sizes per family (n_ati / n_bank; * = n < 20, out of the ATI macro)

- **qwen3.5-9b**: arithmetic_intermediates 1/464*, association 0/98*, basic_readout 0/100*, basic_readout_mt 0/120*, chain_intermediates 0/120*, conjunctive_association 24/100, jailbreak_recognition 7/86*, knowledge_cutoff 26/108, model_specific_directed_modulation 4/98*, moral_rationale 53/184, multilingual 0/80*, multilingual_mt 0/97*, multilingual_multihop 0/22*, multilingual_typo 0/92*, poetry 18/95*, relational_multihop 0/82*, role_bound_association 2/100*, user_modeling 3/126*, wrong_intermediate 4/11*
- **qwen3-8b**: arithmetic_intermediates 0/433*, association 0/98*, basic_readout 8/100*, basic_readout_mt 0/104*, chain_intermediates 0/120*, conjunctive_association 25/100, jailbreak_recognition 11/86*, knowledge_cutoff 55/108, model_specific_directed_modulation 9/98*, moral_rationale 57/178, multilingual 0/89*, multilingual_mt 1/99*, multilingual_typo 0/88*, poetry 23/94, relational_multihop 0/38*, role_bound_association 3/94*, user_modeling 4/126*, wrong_intermediate 17/29*
- **qwen3.5-4b**: arithmetic_intermediates 0/409*, association 0/100*, basic_readout 0/100*, basic_readout_mt 0/118*, chain_intermediates 0/120*, conjunctive_association 25/100, jailbreak_recognition 9/86*, knowledge_cutoff 6/24*, model_specific_directed_modulation 2/98*, moral_rationale 51/183, multilingual 0/69*, multilingual_mt 1/94*, multilingual_typo 0/98*, poetry 4/21*, relational_multihop 0/24*, role_bound_association 0/90*, user_modeling 2/99*, wrong_intermediate 4/11*
- **qwen3.5-2b**: arithmetic_intermediates 0/44*, association 0/98*, basic_readout 2/100*, basic_readout_mt 0/120*, chain_intermediates 0/2*, conjunctive_association 22/100, jailbreak_recognition 9/86*, knowledge_cutoff 3/4*, model_specific_directed_modulation 0/1*, moral_rationale 97/170, multilingual 0/34*, multilingual_mt 0/3*, multilingual_typo 0/88*, poetry 0/2*, relational_multihop 0/62*, role_bound_association 9/96*, user_modeling 0/86*
- **qwen3.5-0.8b**: association 0/97*, basic_readout 4/100*, basic_readout_mt 0/120*, conjunctive_association 22/100, jailbreak_recognition 9/86*, knowledge_cutoff 1/2*, model_specific_directed_modulation 0/2*, moral_rationale 126/178, multilingual 0/9*, poetry 0/1*, role_bound_association 0/8*, user_modeling 3/107*

## Per subject: family x lens stage


### qwen3.5-9b

| family | n (full) | n (ATI) | inverter full | inverter ATI | inverter L20 full | inverter L20 ATI | inverter L20 (L20..30 view) full | inverter L20 (L20..30 view) ATI | distill full | distill ATI | RL i600 full | RL i600 ATI | jlens (base-model lens) full | jlens (base-model lens) ATI | stock floor full | stock floor ATI | po floor full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic_misalignment | 23 | n/g | 0.000 [0.00,0.00] † | — | 0.043 [0.00,0.14] † | — | 0.091 [0.00,0.23] † | — | 0.000 [0.00,0.00] † | — | 0.045 [0.00,0.15] † | — | 0.000 [0.00,0.00] † | — | 0.789 | — | 0.000 |
| arithmetic_intermediates | 464 | 1 | 0.256 [0.21,0.30] | 0.000 [0.00,0.00] | 0.252 [0.21,0.29] | 0.000 [0.00,0.00] | 0.231 [0.19,0.27] | 1.000 [1.00,1.00] | 0.297 [0.25,0.34] | 1.000 [1.00,1.00] | 0.334 [0.29,0.37] | 1.000 [1.00,1.00] | 0.022 [0.01,0.04] | 0.000 [0.00,0.00] | 0.497 | 1.000 (n=1) | 0.989 |
| association | 98 | 0 | 0.918 [0.86,0.97] | — | 0.969 [0.94,1.00] | — | 0.959 [0.92,0.99] | — | 0.949 [0.90,0.99] | — | 0.918 [0.87,0.97] | — | 0.500 [0.41,0.60] | — | 0.969 | — | 0.977 |
| basic_readout | 100 | 0 | 0.960 [0.92,0.99] | — | 0.900 [0.84,0.95] | — | 0.900 [0.84,0.96] | — | 0.920 [0.87,0.97] | — | 0.890 [0.83,0.94] | — | 0.440 [0.35,0.54] | — | 0.890 | — | 0.934 |
| basic_readout_mt | 120 | 0 | 0.942 [0.90,0.98] | — | 0.883 [0.82,0.94] | — | 0.900 [0.84,0.95] | — | 0.908 [0.85,0.96] | — | 0.950 [0.91,0.98] | — | 0.142 [0.07,0.21] | — | 0.983 | — | 1.000 |
| buggy_code | 25 | n/g | 0.160 [0.04,0.32] | — | 0.120 [0.00,0.28] | — | 0.120 [0.00,0.28] | — | 0.200 [0.04,0.36] | — | 0.080 [0.00,0.20] | — | 0.000 [0.00,0.00] | — | 0.360 | — | 0.960 |
| chain_intermediates | 120 | 0 | 0.242 [0.17,0.32] | — | 0.167 [0.11,0.24] | — | 0.150 [0.09,0.23] | — | 0.183 [0.12,0.26] | — | 0.233 [0.16,0.32] | — | 0.025 [0.00,0.06] | — | 0.550 | — | 1.000 |
| conjunctive_association | 100 | 24 | 0.040 [0.01,0.08] | 0.000 [0.00,0.00] | 0.030 [0.00,0.07] | 0.042 [0.00,0.12] | 0.020 [0.00,0.05] | 0.042 [0.00,0.12] | 0.070 [0.02,0.12] | 0.000 [0.00,0.00] | 0.120 [0.06,0.19] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.030 | 0.000 (n=24) | 0.275 |
| directed_modulation | 100 | n/g | 0.610 [0.52,0.70] | — | 0.620 [0.53,0.71] | — | 0.620 [0.53,0.71] | — | 0.650 [0.56,0.74] | — | 0.640 [0.55,0.73] | — | 0.320 [0.23,0.41] | — | — | — | 1.000 |
| jailbreak_recognition | 153 | 7 | 0.659 [0.54,0.77] | 0.271 [-0.03,0.74] | 0.659 [0.54,0.77] | 0.271 [0.00,0.59] | 0.668 [0.55,0.78] † | 0.113 [-0.06,0.50] | 0.638 [0.50,0.76] | 0.083 [-0.10,0.47] | 0.726 [0.62,0.83] | 0.684 [0.21,0.99] | 0.105 [0.05,0.16] | 0.000 [0.00,0.00] | — | — (n=0) | 0.880 |
| knowledge_cutoff | 108 | 26 | 0.463 [0.37,0.56] | 0.385 [0.19,0.54] | 0.370 [0.28,0.46] | 0.269 [0.12,0.42] | 0.398 [0.31,0.49] | 0.308 [0.15,0.46] | 0.444 [0.35,0.54] | 0.269 [0.12,0.46] | 0.481 [0.39,0.57] | 0.308 [0.15,0.46] | 0.148 [0.08,0.22] | 0.077 [0.00,0.19] | 0.435 | 0.308 (n=26) | 0.028 |
| model_multihop | 108 | n/g | 0.806 [0.70,0.89] | — | 0.843 [0.77,0.90] | — | 0.852 [0.77,0.90] | — | 0.806 [0.71,0.89] | — | 0.889 [0.81,0.95] | — | 0.574 [0.44,0.66] | — | 0.870 | — | — |
| model_specific_directed_modulation | 98 | 4 | 0.337 [0.26,0.43] | 0.250 [0.00,0.75] | 0.367 [0.28,0.47] | 0.500 [0.00,1.00] | 0.378 [0.29,0.48] | 0.500 [0.00,1.00] | 0.408 [0.32,0.50] | 0.500 [0.00,1.00] | 0.500 [0.41,0.60] | 0.250 [0.00,0.75] | 0.010 [0.00,0.03] | 0.000 [0.00,0.00] | 0.429 | 0.000 (n=4) | 0.878 |
| moral_rationale | 184 | 53 | 0.484 [0.41,0.55] | 0.264 [0.15,0.38] | 0.522 [0.45,0.60] | 0.321 [0.21,0.45] | 0.478 [0.40,0.55] | 0.264 [0.15,0.38] | 0.582 [0.51,0.65] | 0.302 [0.19,0.42] | 0.560 [0.49,0.63] | 0.264 [0.15,0.40] | 0.375 [0.30,0.45] | 0.075 [0.02,0.15] | 0.821 | 0.679 (n=53) | 0.370 |
| multi_concept_directed_modulation | 116 | n/g | 0.500 [0.41,0.59] | — | 0.509 [0.41,0.61] | — | 0.456 [0.37,0.55] | — | 0.491 [0.40,0.58] | — | 0.535 [0.45,0.63] | — | 0.281 [0.20,0.37] | — | — | — | 0.956 |
| multihop | 60 | n/g | 0.950 [0.90,1.00] | — | 0.933 [0.87,0.98] | — | 0.933 [0.87,0.98] | — | 0.950 [0.88,1.00] | — | 0.933 [0.85,0.98] | — | 0.667 [0.55,0.78] | — | 0.983 | — | 0.951 |
| multihop_mt | 14 | n/g | 0.714 [0.50,0.93] † | — | 0.714 [0.50,0.93] † | — | 0.714 [0.50,0.93] † | — | 0.786 [0.57,1.00] † | — | 0.714 [0.50,0.93] † | — | 0.214 [0.00,0.43] † | — | — | — | — |
| multilingual | 80 | 0 | 0.412 [0.30,0.53] | — | 0.463 [0.35,0.56] | — | 0.375 [0.28,0.47] | — | 0.588 [0.47,0.69] | — | 0.662 [0.55,0.76] | — | 0.188 [0.10,0.28] | — | 0.938 | — | 0.938 |
| multilingual_mt | 97 | 0 | 0.340 [0.25,0.43] | — | 0.680 [0.59,0.77] | — | 0.515 [0.41,0.61] | — | 0.546 [0.45,0.65] | — | 0.866 [0.79,0.93] | — | 0.010 [0.00,0.03] | — | 0.969 | — | 0.964 |
| multilingual_multihop | 20 | 0 | 0.100 [0.00,0.25] | — | 0.200 [0.05,0.40] | — | 0.000 [0.00,0.00] | — | 0.300 [0.10,0.50] | — | 0.450 [0.25,0.65] | — | 0.000 [0.00,0.00] | — | 1.000 | — | 0.387 |
| multilingual_typo | 92 | 0 | 0.152 [0.09,0.23] | — | 0.326 [0.23,0.42] | — | 0.228 [0.15,0.32] | — | 0.315 [0.23,0.41] | — | 0.576 [0.48,0.67] | — | 0.011 [0.00,0.03] | — | 0.859 | — | 0.750 |
| nyt_connections | 53 | n/g | 0.365 [0.23,0.50] † | — | 0.340 [0.23,0.45] | — | 0.396 [0.26,0.51] | — | 0.415 [0.30,0.55] | — | 0.377 [0.25,0.49] | — | 0.321 [0.21,0.45] | — | 0.547 | — | 0.245 |
| poetry | 95 | 18 | 0.253 [0.17,0.35] | 0.056 [0.00,0.17] | 0.211 [0.14,0.29] | 0.056 [0.00,0.17] | 0.242 [0.16,0.34] | 0.167 [0.00,0.33] | 0.263 [0.18,0.36] | 0.111 [0.00,0.28] | 0.347 [0.24,0.44] | 0.222 [0.06,0.44] | 0.074 [0.02,0.13] | 0.056 [0.00,0.17] | 0.011 | 0.000 (n=1) | 0.000 |
| relational_multihop | 82 | 0 | 0.585 [0.49,0.70] | — | 0.695 [0.60,0.79] | — | 0.720 [0.62,0.82] | — | 0.793 [0.70,0.88] | — | 0.732 [0.63,0.82] | — | 0.000 [0.00,0.00] | — | 0.585 | — | 0.974 |
| role_bound_association | 100 | 2 | 0.180 [0.08,0.30] | — | 0.160 [0.06,0.28] | — | 0.140 [0.04,0.24] | — | 0.200 [0.08,0.32] | — | 0.220 [0.12,0.34] | — | 0.000 [0.00,0.00] | — | 0.940 | 1.000 (n=1) | 0.538 |
| typo_mt | 100 | n/g | 0.820 [0.74,0.89] | — | 0.770 [0.69,0.85] | — | 0.720 [0.64,0.80] | — | 0.920 [0.86,0.97] | — | 0.980 [0.95,1.00] | — | 0.000 [0.00,0.00] | — | 0.900 | — | 1.000 |
| user_modeling | 126 | 3 | 0.921 [0.87,0.96] | 0.667 [0.00,1.00] | 0.913 [0.86,0.96] | 0.333 [0.00,1.00] | 0.921 [0.87,0.97] | 0.333 [0.00,1.00] | 0.952 [0.91,0.98] | 0.667 [0.00,1.00] | 0.976 [0.94,1.00] | 1.000 [1.00,1.00] | 0.794 [0.72,0.86] | 0.000 [0.00,0.00] | 0.865 | 0.000 (n=3) | 0.272 |
| wrong_intermediate | 11 | 4 | 0.364 [0.09,0.64] | 0.000 [0.00,0.00] | 0.636 [0.36,0.91] | 0.250 [0.00,0.75] | 0.455 [0.18,0.73] | 0.000 [0.00,0.00] | 0.455 [0.18,0.73] | 0.250 [0.00,0.75] | 0.545 [0.27,0.82] | 0.000 [0.00,0.00] | 0.182 [0.00,0.45] | 0.000 [0.00,0.00] | 0.636 | 0.000 (n=2) | 0.000 |
| **MACRO** (bench rule; ATI: families with >= 20 ATI ids) |  |  | **0.498 [0.48,0.52]** (25 fam) | **0.216 [0.15,0.29]** (3 fam) | **0.521 [0.50,0.54]** (26 fam) | **0.211 [0.14,0.28]** (3 fam) | **0.484 [0.46,0.50]** (25 fam) | **0.205 [0.14,0.27]** (3 fam) | **0.548 [0.53,0.57]** (26 fam) | **0.190 [0.12,0.26]** (3 fam) | **0.597 [0.58,0.62]** (26 fam) | **0.191 [0.13,0.26]** (3 fam) | **0.199 [0.18,0.21]** (26 fam) | **0.051 [0.01,0.09]** (3 fam) |  |  |  |
| **MACRO common full** (24 fam) |  |  | **0.491 [0.47,0.51]** |  | **0.522 [0.50,0.54]** |  | **0.488 [0.47,0.51]** |  | **0.550 [0.53,0.57]** |  | **0.601 [0.58,0.62]** |  | **0.198 [0.18,0.21]** |  |  |  |  |
| **MACRO common ati** (3 fam) |  |  |  | **0.216 [0.15,0.29]** |  | **0.211 [0.14,0.28]** |  | **0.205 [0.14,0.27]** |  | **0.190 [0.12,0.26]** |  | **0.191 [0.13,0.26]** |  | **0.051 [0.01,0.09]** |  |  |  |


### qwen3-8b

| family | n (full) | n (ATI) | inverter full | inverter ATI | distill full | distill ATI | RL i600 full | RL i600 ATI | jlens full | jlens ATI | stock floor full | stock floor ATI | po floor full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic_misalignment | 25 | n/g | 0.040 [0.00,0.14] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.476 | — | 0.000 |
| arithmetic_intermediates | 433 | 0 | 0.312 [0.27,0.36] | — | 0.353 [0.31,0.40] | — | 0.411 [0.36,0.45] | — | 0.060 [0.04,0.09] | — | 0.205 | — | 0.970 |
| association | 98 | 0 | 0.888 [0.83,0.95] | — | 0.898 [0.84,0.95] | — | 0.939 [0.89,0.98] | — | 0.480 [0.38,0.57] | — | 0.857 | — | 0.988 |
| basic_readout | 100 | 8 | 0.838 [0.76,0.91] † | 0.375 [0.12,0.75] | 0.859 [0.79,0.93] † | 0.375 [0.12,0.75] | 0.838 [0.77,0.91] † | 0.250 [0.00,0.62] | 0.485 [0.38,0.58] † | 0.250 [0.00,0.62] | 0.707 | 0.000 (n=8) | 0.835 |
| basic_readout_mt | 104 | 0 | 0.808 [0.73,0.88] | — | 0.827 [0.75,0.89] | — | 0.891 [0.83,0.95] | — | 0.173 [0.11,0.25] | — | 0.971 | — | 1.000 |
| buggy_code | 19 | n/g | 0.053 [0.00,0.16] | — | 0.000 [0.00,0.00] | — | 0.158 [0.00,0.32] | — | 0.053 [0.00,0.16] | — | 0.053 | — | 0.947 |
| chain_intermediates | 120 | 0 | 0.025 [0.00,0.06] | — | 0.042 [0.01,0.07] | — | 0.133 [0.07,0.20] | — | 0.008 [0.00,0.03] | — | 0.092 | — | 0.975 |
| conjunctive_association | 100 | 25 | 0.020 [0.00,0.05] | 0.000 [0.00,0.00] | 0.030 [0.00,0.07] | 0.000 [0.00,0.00] | 0.030 [0.00,0.07] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.040 | 0.000 (n=24) | 0.261 |
| directed_modulation | 94 | n/g | 0.245 [0.16,0.33] | — | 0.245 [0.16,0.33] | — | 0.234 [0.15,0.32] | — | 0.096 [0.04,0.16] | — | — | — | 1.000 |
| jailbreak_recognition | 164 | 11 | 0.279 [0.18,0.38] | 0.000 [0.00,0.00] | 0.186 [0.10,0.28] | 0.000 [0.00,0.00] | 0.407 [0.28,0.53] | 0.091 [0.00,0.27] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | — | — (n=0) | 0.834 |
| knowledge_cutoff | 108 | 55 | 0.231 [0.16,0.31] | 0.091 [0.02,0.16] | 0.269 [0.19,0.36] | 0.164 [0.07,0.27] | 0.324 [0.24,0.41] | 0.182 [0.09,0.29] | 0.056 [0.02,0.10] | 0.018 [0.00,0.05] | 0.130 | 0.164 (n=55) | 0.000 |
| model_multihop | 214 | n/g | 0.621 [0.51,0.70] | — | 0.636 [0.54,0.72] | — | 0.715 [0.62,0.79] | — | 0.416 [0.33,0.49] | — | 0.704 | — | — |
| model_specific_directed_modulation | 98 | 9 | 0.204 [0.12,0.30] | 0.111 [0.00,0.33] | 0.255 [0.17,0.35] | 0.111 [0.00,0.33] | 0.306 [0.21,0.40] | 0.111 [0.00,0.33] | 0.041 [0.01,0.08] | 0.000 [0.00,0.00] | 0.306 | 0.222 (n=9) | 0.827 |
| moral_rationale | 178 | 57 | 0.506 [0.44,0.58] | 0.263 [0.16,0.39] | 0.539 [0.47,0.61] | 0.228 [0.12,0.33] | 0.539 [0.47,0.61] | 0.211 [0.11,0.32] | 0.337 [0.27,0.40] | 0.123 [0.05,0.21] | 0.736 | 0.561 (n=57) | 0.337 |
| multi_concept_directed_modulation | 116 | n/g | 0.325 [0.24,0.41] | — | 0.325 [0.24,0.41] | — | 0.395 [0.31,0.48] | — | 0.114 [0.06,0.18] | — | — | — | 0.965 |
| multihop | 58 | n/g | 0.862 [0.78,0.95] | — | 0.879 [0.79,0.95] | — | 0.862 [0.78,0.95] | — | 0.500 [0.38,0.64] | — | 0.966 | — | 0.973 |
| multihop_mt | 39 | n/g | 0.821 [0.69,0.95] | — | 0.923 [0.82,1.00] | — | 0.872 [0.77,0.97] | — | 0.154 [0.05,0.28] | — | — | — | — |
| multilingual | 89 | 0 | 0.236 [0.16,0.33] | — | 0.438 [0.33,0.54] | — | 0.809 [0.72,0.89] | — | 0.101 [0.04,0.17] | — | 0.921 | — | 0.933 |
| multilingual_mt | 99 | 1 | 0.333 [0.24,0.43] | — | 0.394 [0.30,0.48] | — | 0.838 [0.77,0.91] | — | 0.010 [0.00,0.03] | — | 0.879 | — (n=0) | 0.923 |
| multilingual_multihop | 7 | n/g | 0.571 [0.14,1.00] | — | 0.143 [0.00,0.43] | — | 0.714 [0.43,1.00] | — | 0.000 [0.00,0.00] | — | 1.000 | — | 0.438 |
| multilingual_typo | 88 | 0 | 0.080 [0.03,0.14] | — | 0.148 [0.08,0.23] | — | 0.568 [0.47,0.67] | — | 0.000 [0.00,0.00] | — | 0.864 | — | 0.722 |
| nyt_connections | 293 | n/g | 0.137 [0.10,0.17] | — | 0.188 [0.14,0.23] | — | 0.218 [0.17,0.27] | — | 0.208 [0.16,0.26] | — | 0.208 | — | 0.116 |
| poetry | 94 | 23 | 0.096 [0.04,0.16] | 0.000 [0.00,0.00] | 0.117 [0.05,0.19] | 0.043 [0.00,0.13] | 0.128 [0.06,0.20] | 0.043 [0.00,0.13] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.011 | 0.000 (n=6) | 0.000 |
| relational_multihop | 38 | 0 | 0.395 [0.24,0.55] | — | 0.579 [0.42,0.74] | — | 0.553 [0.39,0.71] | — | 0.000 [0.00,0.00] | — | 0.421 | — | 1.000 |
| role_bound_association | 94 | 3 | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.894 | 1.000 (n=3) | 0.538 |
| typo_mt | 100 | n/g | 0.840 [0.76,0.91] | — | 0.980 [0.95,1.00] | — | 0.980 [0.95,1.00] | — | 0.000 [0.00,0.00] | — | 0.870 | — | 1.000 |
| user_modeling | 126 | 4 | 0.841 [0.77,0.90] | 0.500 [0.00,1.00] | 0.905 [0.86,0.95] | 0.500 [0.00,1.00] | 0.921 [0.87,0.97] | 0.750 [0.25,1.00] | 0.651 [0.57,0.73] | 0.000 [0.00,0.00] | 0.524 | 0.000 (n=4) | 0.304 |
| wrong_intermediate | 29 | 17 | 0.448 [0.28,0.62] | 0.176 [0.00,0.35] | 0.414 [0.24,0.59] | 0.118 [0.00,0.29] | 0.448 [0.28,0.66] | 0.176 [0.00,0.35] | 0.103 [0.00,0.24] | 0.000 [0.00,0.00] | 0.414 | 0.111 (n=9) | 0.069 |
| **MACRO** (bench rule; ATI: families with >= 20 ATI ids) |  |  | **0.391 [0.37,0.41]** (25 fam) | **0.089 [0.05,0.12]** (4 fam) | **0.405 [0.39,0.42]** (25 fam) | **0.109 [0.07,0.15]** (4 fam) | **0.514 [0.49,0.53]** (25 fam) | **0.109 [0.07,0.15]** (4 fam) | **0.142 [0.13,0.15]** (25 fam) | **0.035 [0.01,0.06]** (4 fam) |  |  |  |
| **MACRO common full** (25 fam) |  |  | **0.391 [0.37,0.41]** |  | **0.405 [0.39,0.42]** |  | **0.514 [0.49,0.53]** |  | **0.142 [0.13,0.15]** |  |  |  |  |
| **MACRO common ati** (4 fam) |  |  |  | **0.089 [0.05,0.12]** |  | **0.109 [0.07,0.15]** |  | **0.109 [0.07,0.15]** |  | **0.035 [0.01,0.06]** |  |  |  |

- **not re-judged on this set** (a judge run refused or failed; excluded): jlens-ati/arithmetic_intermediates, jlens-ati/association, qwen3-8b.inv.s6795-ati/arithmetic_intermediates, qwen3-8b.inv.s6795-ati/association, qwen3-8b.rl.i600-ati/arithmetic_intermediates, qwen3-8b.rl.i600-ati/association, qwen3-8b.sft-ati/arithmetic_intermediates, qwen3-8b.sft-ati/association


### qwen3.5-4b

| family | n (full) | n (ATI) | inverter full | inverter ATI | inverter L20 full | inverter L20 ATI | inverter L20 (L20..30 view) full | inverter L20 (L20..30 view) ATI | distill full | distill ATI | RL i600 full | RL i600 ATI | jlens full | jlens ATI | stock floor full | stock floor ATI | po floor full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic_misalignment | 23 | n/g | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.643 | — | 0.000 |
| arithmetic_intermediates | 409 | 0 | 0.396 [0.35,0.44] | — | 0.401 [0.35,0.45] | — | 0.369 [0.32,0.42] | — | 0.474 [0.43,0.52] | — | 0.521 [0.47,0.57] | — | 0.083 [0.06,0.11] | — | 0.416 | — | 0.978 |
| association | 100 | 0 | 0.930 [0.88,0.98] | — | 0.940 [0.89,0.98] | — | 0.950 [0.90,0.99] | — | 0.960 [0.92,0.99] | — | 0.950 [0.90,0.99] | — | 0.670 [0.58,0.76] | — | 0.940 | — | 1.000 |
| basic_readout | 100 | 0 | 0.890 [0.83,0.94] | — | 0.950 [0.90,0.99] | — | 0.960 [0.91,0.99] | — | 0.930 [0.88,0.97] | — | 0.910 [0.85,0.96] | — | 0.500 [0.41,0.60] | — | 0.900 | — | 0.954 |
| basic_readout_mt | 118 | 0 | 0.839 [0.77,0.91] | — | 0.856 [0.79,0.92] | — | 0.864 [0.80,0.92] | — | 0.856 [0.79,0.92] | — | 0.881 [0.81,0.93] | — | 0.212 [0.14,0.29] | — | 0.965 | — | 1.000 |
| buggy_code | 25 | n/g | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.080 [0.00,0.20] | — | 0.080 [0.00,0.20] | — | 0.040 [0.00,0.12] † | — | 0.200 | — | 0.900 |
| chain_intermediates | 120 | 0 | 0.592 [0.51,0.68] | — | 0.625 [0.53,0.71] | — | 0.642 [0.57,0.72] | — | 0.658 [0.57,0.74] | — | 0.575 [0.49,0.67] | — | 0.250 [0.17,0.33] | — | 0.541 | — | 0.967 |
| conjunctive_association | 100 | 25 | 0.010 [0.00,0.03] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.020 [0.00,0.05] | 0.000 [0.00,0.00] | 0.050 [0.01,0.10] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.010 | 0.000 (n=25) | 0.361 |
| directed_modulation | 94 | n/g | 0.362 [0.27,0.46] | — | 0.372 [0.28,0.48] | — | 0.362 [0.27,0.47] | — | 0.362 [0.27,0.46] | — | 0.394 [0.30,0.50] | — | 0.128 [0.06,0.19] | — | — | — | 1.000 |
| jailbreak_recognition | 152 | 9 | 0.709 [0.62,0.79] | 0.667 [0.40,1.00] | 0.621 [0.50,0.73] | 0.192 [-0.06,0.64] | 0.614 [0.49,0.73] | 0.273 [-0.06,0.53] | 0.566 [0.44,0.68] | 0.207 [-0.03,0.50] | 0.609 [0.48,0.72] | 0.303 [-0.05,0.54] | 0.023 [0.00,0.06] | 0.000 [0.00,0.00] | — | — (n=0) | 0.849 |
| knowledge_cutoff | 24 | 6 | 0.417 [0.25,0.62] | 0.167 [0.00,0.50] | 0.458 [0.25,0.67] | 0.167 [0.00,0.50] | 0.458 [0.25,0.67] | 0.167 [0.00,0.50] | 0.583 [0.38,0.79] | 0.167 [0.00,0.50] | 0.417 [0.21,0.62] | 0.167 [0.00,0.50] | 0.083 [0.00,0.21] | 0.000 [0.00,0.00] | 0.652 | 0.500 (n=6) | 0.000 |
| model_multihop | 120 | n/g | 0.850 [0.75,0.93] | — | 0.900 [0.83,0.96] | — | 0.858 [0.76,0.94] | — | 0.900 [0.84,0.95] | — | 0.892 [0.82,0.96] | — | 0.667 [0.54,0.77] | — | 0.950 | — | — |
| model_specific_directed_modulation | 98 | 2 | 0.173 [0.10,0.26] | 0.000 [0.00,0.00] | 0.173 [0.10,0.26] | 0.000 [0.00,0.00] | 0.173 [0.10,0.26] | 0.000 [0.00,0.00] | 0.214 [0.14,0.30] | 0.000 [0.00,0.00] | 0.224 [0.14,0.32] | 0.000 [0.00,0.00] | 0.020 [0.00,0.05] | 0.000 [0.00,0.00] | 0.398 | 0.000 (n=2) | 0.888 |
| moral_rationale | 183 | 51 | 0.470 [0.40,0.54] | 0.275 [0.16,0.39] | 0.443 [0.37,0.52] | 0.235 [0.12,0.37] | 0.399 [0.32,0.47] | 0.235 [0.14,0.35] | 0.508 [0.44,0.58] | 0.333 [0.20,0.47] | 0.601 [0.53,0.67] | 0.333 [0.22,0.45] | 0.301 [0.23,0.37] | 0.098 [0.02,0.20] | 0.721 | 0.549 (n=51) | 0.246 |
| multi_concept_directed_modulation | 116 | n/g | 0.368 [0.28,0.46] | — | 0.395 [0.31,0.49] | — | 0.377 [0.29,0.46] | — | 0.430 [0.34,0.52] | — | 0.474 [0.39,0.57] | — | 0.298 [0.22,0.38] | — | — | — | 0.982 |
| multihop | 59 | n/g | 0.814 [0.71,0.90] | — | 0.847 [0.75,0.93] | — | 0.847 [0.76,0.93] | — | 0.780 [0.68,0.88] | — | 0.831 [0.73,0.92] | — | 0.525 [0.39,0.66] | — | 0.966 | — | 1.000 |
| multihop_mt | 2 | n/g | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 0.500 [0.00,1.00] | — | 1.000 [1.00,1.00] | — | 0.500 [0.00,1.00] | — | — | — | — |
| multilingual | 69 | 0 | 0.333 [0.22,0.43] | — | 0.478 [0.36,0.61] | — | 0.406 [0.29,0.52] | — | 0.536 [0.41,0.67] | — | 0.638 [0.52,0.75] | — | 0.261 [0.16,0.38] | — | 0.884 | — | 0.944 |
| multilingual_mt | 94 | 1 | 0.309 [0.21,0.40] | — | 0.532 [0.44,0.63] | — | 0.319 [0.22,0.40] | — | 0.532 [0.44,0.64] | — | 0.819 [0.74,0.89] | — | 0.011 [0.00,0.03] | — | 0.904 | — (n=0) | 0.857 |
| multilingual_typo | 98 | 0 | 0.163 [0.09,0.23] | — | 0.163 [0.09,0.24] | — | 0.092 [0.04,0.15] | — | 0.245 [0.16,0.33] | — | 0.602 [0.51,0.70] | — | 0.010 [0.00,0.03] | — | 0.755 | — | 0.878 |
| nyt_connections | 13 | n/g | 0.692 [0.46,0.92] | — | 0.615 [0.31,0.85] | — | 0.615 [0.31,0.85] | — | 0.692 [0.46,0.92] | — | 0.769 [0.54,1.00] | — | 0.692 [0.46,0.92] | — | 0.615 | — | 0.385 |
| poetry | 21 | 4 | 0.190 [0.05,0.38] | 0.250 [0.00,0.75] | 0.048 [0.00,0.14] | 0.000 [0.00,0.00] | 0.048 [0.00,0.14] | 0.000 [0.00,0.00] | 0.238 [0.10,0.43] | 0.000 [0.00,0.00] | 0.286 [0.10,0.48] | 0.000 [0.00,0.00] | 0.048 [0.00,0.14] | 0.000 [0.00,0.00] | 0.000 | — (n=0) | 0.000 |
| relational_multihop | 24 | 0 | 0.333 [0.17,0.54] | — | 0.333 [0.12,0.54] | — | 0.375 [0.17,0.58] | — | 0.500 [0.29,0.71] | — | 0.667 [0.46,0.83] | — | 0.000 [0.00,0.00] | — | 0.458 | — | 0.833 |
| role_bound_association | 90 | 0 | 0.022 [0.00,0.07] | — | 0.022 [0.00,0.07] | — | 0.022 [0.00,0.07] | — | 0.044 [0.00,0.11] | — | 0.089 [0.02,0.18] | — | 0.000 [0.00,0.00] | — | 0.978 | — | 0.455 |
| typo_mt | 100 | n/g | 0.600 [0.51,0.69] | — | 0.560 [0.46,0.65] | — | 0.470 [0.37,0.57] | — | 0.820 [0.75,0.89] | — | 0.980 [0.95,1.00] | — | 0.000 [0.00,0.00] | — | 0.900 | — | 1.000 |
| user_modeling | 99 | 2 | 0.909 [0.85,0.96] | 0.000 [0.00,0.00] | 0.919 [0.86,0.97] | 0.500 [0.00,1.00] | 0.909 [0.85,0.96] | 0.500 [0.00,1.00] | 0.919 [0.86,0.97] | 0.500 [0.00,1.00] | 0.970 [0.93,1.00] | 1.000 [1.00,1.00] | 0.778 [0.69,0.85] | 0.000 [0.00,0.00] | 0.818 | 0.000 (n=2) | 0.286 |
| wrong_intermediate | 11 | 4 | 0.364 [0.09,0.64] | 0.250 [0.00,0.75] | 0.182 [0.00,0.45] | 0.000 [0.00,0.00] | 0.091 [0.00,0.27] | 0.000 [0.00,0.00] | 0.364 [0.09,0.64] | 0.250 [0.00,0.75] | 0.364 [0.09,0.64] | 0.250 [0.00,0.75] | 0.091 [0.00,0.27] | 0.000 [0.00,0.00] | 0.364 | 0.000 (n=1) | 0.091 |
| **MACRO** (bench rule; ATI: families with >= 20 ATI ids) |  |  | **0.499 [0.48,0.52]** (24 fam) | **0.137 [0.08,0.20]** (2 fam) | **0.502 [0.48,0.52]** (24 fam) | **0.118 [0.05,0.18]** (2 fam) | **0.475 [0.46,0.49]** (24 fam) | **0.118 [0.06,0.17]** (2 fam) | **0.526 [0.50,0.56]** (24 fam) | **0.167 [0.10,0.24]** (2 fam) | **0.604 [0.58,0.63]** (24 fam) | **0.167 [0.11,0.23]** (2 fam) | **0.264 [0.24,0.29]** (23 fam) | **0.049 [0.00,0.09]** (2 fam) |  |  |  |
| **MACRO common full** (23 fam) |  |  | **0.521 [0.50,0.54]** |  | **0.524 [0.50,0.55]** |  | **0.495 [0.48,0.52]** |  | **0.546 [0.51,0.58]** |  | **0.627 [0.60,0.65]** |  | **0.264 [0.24,0.29]** |  |  |  |  |
| **MACRO common ati** (2 fam) |  |  |  | **0.137 [0.08,0.20]** |  | **0.118 [0.05,0.18]** |  | **0.118 [0.06,0.17]** |  | **0.167 [0.10,0.24]** |  | **0.167 [0.11,0.23]** |  | **0.049 [0.00,0.09]** |  |  |  |

- **not re-judged on this set** (a judge run refused or failed; excluded): jlens-ati/arithmetic_intermediates, jlens-ati/role_bound_association, jlens/multilingual_multihop, qwen3.5-4b.inv.L20.end-L20view-ati/arithmetic_intermediates, qwen3.5-4b.inv.L20.end-L20view-ati/role_bound_association, qwen3.5-4b.inv.L20.end-L20view/multilingual_multihop, qwen3.5-4b.inv.L20.end-ati/arithmetic_intermediates, qwen3.5-4b.inv.L20.end-ati/role_bound_association, qwen3.5-4b.inv.L20.end/multilingual_multihop, qwen3.5-4b.inv.end-ati/arithmetic_intermediates, qwen3.5-4b.inv.end-ati/role_bound_association, qwen3.5-4b.inv.end/multilingual_multihop, qwen3.5-4b.rl.i600-ati/arithmetic_intermediates, qwen3.5-4b.rl.i600-ati/role_bound_association, qwen3.5-4b.rl.i600/multilingual_multihop, qwen3.5-4b.sft-ati/arithmetic_intermediates, qwen3.5-4b.sft-ati/role_bound_association, qwen3.5-4b.sft/multilingual_multihop


### qwen3.5-2b

| family | n (full) | n (ATI) | inverter full | inverter ATI | distill full | distill ATI | RL i600 full | RL i600 ATI | jlens full | jlens ATI | stock floor full | stock floor ATI | po floor full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic_misalignment | 9 | n/g | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.125 [0.00,0.43] † | — | 0.000 [0.00,0.00] | — | 0.625 | — | 0.000 |
| arithmetic_intermediates | 44 | 0 | 0.364 [0.23,0.50] | — | 0.432 [0.27,0.57] | — | 0.455 [0.30,0.59] | — | 0.068 [0.00,0.16] | — | 0.231 | — | 1.000 |
| association | 98 | 0 | 0.867 [0.80,0.93] | — | 0.898 [0.84,0.95] | — | 0.878 [0.82,0.94] | — | 0.684 [0.59,0.77] | — | 0.918 | — | 1.000 |
| basic_readout | 100 | 2 | 0.838 [0.77,0.91] † | 0.500 [0.00,1.00] | 0.848 [0.78,0.91] † | 0.500 [0.00,1.00] | 0.828 [0.75,0.90] † | 0.500 [0.00,1.00] | 0.465 [0.37,0.57] † | 0.500 [0.00,1.00] | 0.808 | 0.500 (n=2) | 0.919 |
| basic_readout_mt | 120 | 0 | 0.742 [0.66,0.82] | — | 0.824 [0.76,0.89] | — | 0.881 [0.82,0.93] | — | 0.208 [0.14,0.28] | — | 0.933 | — | 1.000 |
| buggy_code | 3 | n/g | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 | — | 1.000 |
| chain_intermediates | 2 | 0 | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 1.000 | — | 1.000 |
| conjunctive_association | 100 | 22 | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.010 [0.00,0.03] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 | 0.000 (n=22) | 0.280 |
| directed_modulation | 57 | n/g | 0.368 [0.25,0.49] | — | 0.351 [0.23,0.47] | — | 0.421 [0.30,0.54] | — | 0.123 [0.05,0.21] | — | — | — | 1.000 |
| jailbreak_recognition | 140 | 9 | 0.419 [0.31,0.52] | 0.000 [0.00,0.00] | 0.451 [0.30,0.57] | -0.037 [-0.10,0.00] | 0.528 [0.40,0.64] | 0.093 [-0.05,0.40] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | — | — (n=0) | 0.767 |
| knowledge_cutoff | 4 | 3 | 0.500 [0.00,1.00] | 0.333 [0.00,1.00] | 0.500 [0.00,1.00] | 0.333 [0.00,1.00] | 0.500 [0.00,1.00] | 0.333 [0.00,1.00] | 0.250 [0.00,0.75] | 0.000 [0.00,0.00] | 0.000 | 0.000 (n=1) | 0.000 |
| model_multihop | 15 | n/g | 0.800 [0.57,1.00] | — | 0.867 [0.64,1.00] | — | 0.800 [0.54,1.00] | — | 0.800 [0.57,1.00] | — | 1.000 | — | — |
| model_specific_directed_modulation | 1 | 0 | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 0.000 [0.00,0.00] | — | 1.000 | — | 1.000 |
| moral_rationale | 170 | 97 | 0.300 [0.24,0.37] | 0.124 [0.06,0.20] | 0.312 [0.25,0.38] | 0.144 [0.08,0.22] | 0.412 [0.33,0.49] | 0.247 [0.16,0.33] | 0.088 [0.05,0.14] | 0.031 [0.00,0.07] | 0.629 | 0.495 (n=97) | 0.160 |
| multi_concept_directed_modulation | 116 | n/g | 0.404 [0.32,0.49] | — | 0.430 [0.34,0.52] | — | 0.456 [0.37,0.54] | — | 0.272 [0.19,0.36] | — | — | — | 0.965 |
| multihop | 11 | n/g | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 1.000 [1.00,1.00] | — | 0.636 [0.36,0.91] | — | 0.909 | — | 1.000 |
| multilingual | 34 | 0 | 0.588 [0.44,0.74] | — | 0.647 [0.50,0.79] | — | 0.706 [0.56,0.85] | — | 0.235 [0.12,0.38] | — | 0.529 | — | 0.971 |
| multilingual_mt | 3 | 0 | 0.333 [0.00,1.00] | — | 0.333 [0.00,1.00] | — | 0.667 [0.00,1.00] | — | 0.000 [0.00,0.00] | — | 1.000 | — | — |
| multilingual_typo | 88 | 0 | 0.023 [0.00,0.06] | — | 0.080 [0.02,0.14] | — | 0.114 [0.06,0.18] | — | 0.011 [0.00,0.03] | — | 0.261 | — | 0.722 |
| nyt_connections | — | n/g | — | — | — | — | — | — | — | — | — | — | — |
| poetry | 2 | 0 | 0.000 [0.00,0.00] | — | 0.500 [0.00,1.00] | — | 1.000 [1.00,1.00] | — | 0.000 [0.00,0.00] | — | 0.000 | — | 0.000 |
| relational_multihop | 62 | 0 | 0.306 [0.19,0.42] | — | 0.468 [0.34,0.58] | — | 0.565 [0.44,0.69] | — | 0.000 [0.00,0.00] | — | 0.177 | — | 1.000 |
| role_bound_association | 96 | 9 | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.896 | — (n=0) | 0.700 |
| typo_mt | 100 | n/g | 0.580 [0.48,0.68] | — | 0.700 [0.61,0.79] | — | 0.900 [0.84,0.96] | — | 0.000 [0.00,0.00] | — | 0.720 | — | 1.000 |
| user_modeling | 86 | 0 | 0.744 [0.65,0.84] | — | 0.860 [0.79,0.93] | — | 0.884 [0.81,0.95] | — | 0.663 [0.56,0.77] | — | 0.686 | — | 0.152 |
| **MACRO** (bench rule; ATI: families with >= 20 ATI ids) |  |  | **0.431 [0.41,0.45]** (14 fam) | **0.062 [0.03,0.10]** (2 fam) | **0.504 [0.46,0.55]** (14 fam) | **0.072 [0.04,0.11]** (2 fam) | **0.585 [0.56,0.61]** (14 fam) | **0.124 [0.08,0.16]** (2 fam) | **0.209 [0.18,0.23]** (14 fam) | **0.015 [-0.00,0.03]** (2 fam) |  |  |  |
| **MACRO common full** (14 fam) |  |  | **0.431 [0.41,0.45]** |  | **0.504 [0.46,0.55]** |  | **0.585 [0.56,0.61]** |  | **0.209 [0.18,0.23]** |  |  |  |  |
| **MACRO common ati** (2 fam) |  |  |  | **0.062 [0.03,0.10]** |  | **0.072 [0.04,0.11]** |  | **0.124 [0.08,0.16]** |  | **0.015 [-0.00,0.03]** |  |  |  |

- **not re-judged on this set** (a judge run refused or failed; excluded): jlens-ati/poetry, jlens-ati/wrong_intermediate, jlens/wrong_intermediate, qwen3.5-2b.inv.end-ati/poetry, qwen3.5-2b.inv.end-ati/wrong_intermediate, qwen3.5-2b.inv.end/wrong_intermediate, qwen3.5-2b.rl.i600-ati/poetry, qwen3.5-2b.rl.i600-ati/wrong_intermediate, qwen3.5-2b.rl.i600/wrong_intermediate, qwen3.5-2b.sft-ati/poetry, qwen3.5-2b.sft-ati/wrong_intermediate, qwen3.5-2b.sft/wrong_intermediate


### qwen3.5-0.8b

| family | n (full) | n (ATI) | inverter full | inverter ATI | distill full | distill ATI | RL i600 full | RL i600 ATI | jlens full | jlens ATI | stock floor full | stock floor ATI | po floor full |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| agentic_misalignment | 2 | n/g | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] † | — | 0.000 [0.00,0.00] | — | 0.500 | — | 0.000 |
| association | 97 | 0 | 0.711 [0.62,0.79] | — | 0.773 [0.68,0.85] | — | 0.773 [0.68,0.85] | — | 0.526 [0.42,0.63] | — | 0.763 | — | 0.978 |
| basic_readout | 100 | 4 | 0.837 [0.77,0.91] † | 0.750 [0.25,1.00] | 0.816 [0.73,0.89] † | 0.750 [0.25,1.00] | 0.755 [0.67,0.83] † | 0.500 [0.00,1.00] | 0.357 [0.27,0.45] † | 0.000 [0.00,0.00] | 0.653 | 0.500 (n=4) | 0.848 |
| basic_readout_mt | 120 | 0 | 0.650 [0.56,0.73] | — | 0.686 [0.60,0.76] | — | 0.739 [0.65,0.82] | — | 0.167 [0.11,0.23] | — | 0.822 | — | 1.000 |
| conjunctive_association | 100 | 22 | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.010 [0.00,0.03] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 | 0.000 (n=22) | 0.327 |
| directed_modulation | 82 | n/g | 0.195 [0.11,0.29] | — | 0.305 [0.21,0.40] | — | 0.280 [0.18,0.38] | — | 0.061 [0.02,0.11] | — | — | — | 1.000 |
| jailbreak_recognition | 132 | 9 | 0.198 [0.11,0.29] | 0.000 [0.00,0.00] | 0.128 [0.06,0.20] | 0.000 [0.00,0.00] | 0.279 [0.16,0.39] | 0.111 [0.00,0.33] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | — | — (n=0) | 0.837 |
| knowledge_cutoff | 2 | 1 | 1.000 [1.00,1.00] | 1.000 [1.00,1.00] | 1.000 [1.00,1.00] | 1.000 [1.00,1.00] | 0.500 [0.00,1.00] | 1.000 [1.00,1.00] | 0.000 [0.00,0.00] | 0.000 [0.00,0.00] | 0.000 | — (n=0) | 0.500 |
| model_multihop | 7 | n/g | 0.857 [0.57,1.00] | — | 1.000 [1.00,1.00] | — | 0.857 [0.57,1.00] | — | 0.714 [0.43,1.00] | — | 0.857 | — | — |
| model_specific_directed_modulation | 2 | 0 | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 | — | 1.000 |
| moral_rationale | 178 | 126 | 0.163 [0.11,0.22] | 0.063 [0.02,0.11] | 0.157 [0.11,0.21] | 0.071 [0.03,0.12] | 0.174 [0.12,0.24] | 0.071 [0.03,0.12] | 0.034 [0.01,0.06] | 0.008 [0.00,0.02] | 0.337 | 0.278 (n=126) | 0.106 |
| multi_concept_directed_modulation | 116 | n/g | 0.193 [0.12,0.26] | — | 0.272 [0.19,0.36] | — | 0.272 [0.19,0.35] | — | 0.140 [0.08,0.20] | — | — | — | 0.964 |
| multilingual | 9 | 0 | 0.778 [0.44,1.00] | — | 0.778 [0.44,1.00] | — | 1.000 [1.00,1.00] | — | 0.444 [0.11,0.78] | — | 0.333 | — | 0.800 |
| poetry | 1 | 0 | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 | — | 0.000 |
| role_bound_association | 8 | 0 | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 0.000 [0.00,0.00] | — | 1.000 | — | 0.250 |
| typo_mt | 100 | n/g | 0.380 [0.29,0.47] | — | 0.500 [0.41,0.60] | — | 0.680 [0.60,0.77] | — | 0.010 [0.00,0.03] | — | 0.430 | — | 1.000 |
| user_modeling | 107 | 3 | 0.673 [0.59,0.76] | 0.333 [0.00,1.00] | 0.785 [0.71,0.86] | 0.333 [0.00,1.00] | 0.822 [0.75,0.90] | 0.333 [0.00,1.00] | 0.411 [0.32,0.50] | 0.333 [0.00,1.00] | 0.393 | 0.000 (n=2) | 0.113 |
| **MACRO** (bench rule; ATI: families with >= 20 ATI ids) |  |  | **0.297 [0.26,0.33]** (11 fam) | **0.032 [0.01,0.05]** (2 fam) | **0.327 [0.30,0.36]** (11 fam) | **0.036 [0.01,0.06]** (2 fam) | **0.383 [0.36,0.40]** (11 fam) | **0.036 [0.01,0.06]** (2 fam) | **0.126 [0.09,0.16]** (11 fam) | **0.004 [-0.00,0.01]** (2 fam) |  |  |  |
| **MACRO common full** (11 fam) |  |  | **0.297 [0.26,0.33]** |  | **0.327 [0.30,0.36]** |  | **0.383 [0.36,0.40]** |  | **0.126 [0.09,0.16]** |  |  |  |  |
| **MACRO common ati** (2 fam) |  |  |  | **0.032 [0.01,0.05]** |  | **0.036 [0.01,0.06]** |  | **0.036 [0.01,0.06]** |  | **0.004 [-0.00,0.01]** |  |  |  |

- **not re-judged on this set** (a judge run refused or failed; excluded): jlens/multihop, qwen3.5-0.8b.inv.end/multihop, qwen3.5-0.8b.rl.i600/multihop, qwen3.5-0.8b.sft/multihop


## Spend (ledger)

```
ati_qwen3-8b.jsonl           calls   32415  $   136.93
ati_qwen3.5-0.8b.jsonl       calls   15858  $    89.76
ati_qwen3.5-2b.jsonl         calls   18841  $    97.46
ati_qwen3.5-4b.jsonl         calls   27978  $   117.76
ati_qwen3.5-9b.jsonl         calls   34002  $   143.54
qwen3-8b.jsonl               calls  312599  $ 17193.22
qwen3.5-0.8b.jsonl           calls   78907  $  4645.26
qwen3.5-2b.jsonl             calls   90136  $  5474.50
qwen3.5-4b.jsonl             calls  313319  $ 16575.39
qwen3.5-9b.jsonl             calls  260144  $ 13936.91
CLAUDE TOTAL $58410.73; producer GPU-hours 295.1 (H100, ~$1166)
```
