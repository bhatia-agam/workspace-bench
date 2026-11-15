# 0089: rebuild Agam's five adapted sets (gemma-4-31b-it, glm-5.3-flash, kimi-k2, olmo-3.1-32b, qwen3.6-35b-a3b)

Camila, 2026-11-15: "update agam's 5 … make sure they have 30 families and are gated". The five
older sets under `adapted/` were built by Agam in October on the v1 banks. Plan 0060 D1/D2
left them out of the refresh. This plan rebuilds them FRESH from the registered banks, to the
standard of the ten sets rebuilt under plans 0060-0087.

## The ask, restated

- **30 families** = the 31 families `all` runs (`registry.drop_superseded`) minus
  `jlens_concept_pr`. `hinted_cutoff` and `introspection` are in scope on every set.
- **Every item is gated on the subject itself**: thinking off, its own chat template, greedy
  right and >= 8/10 samples (10/10 chain).
- **The data-round rules of plan 0075 apply unchanged**:
  - the strict chance+5 guessing bar per family;
  - the >= 2-of-5 leaker rule, confirmed in two separate lucky runs;
  - the item-quality review (#391);
  - the capital, landmark, Gender / Country 20% and relational composition screens.
- **Small families are refilled** with more waves, using the funded pools of plan 0077. A
  family is `ooc` / `blocked` only on an objective stop with evidence: the subject can't do the
  task, or a technical blocker that can be shown. Budget is never the reason.
- **Native languages are set by lab decision, not measured**:
  - Google (Gemma) and AI2 (OLMo): `['en']`.
  - Alibaba (Qwen), Moonshot (Kimi) and Zhipu (GLM): `['en','zh']`.
- **An independent fresh-context audit** writes `AUDIT.md` before each set's data PR. There is
  one data PR per set, merged through `gated_merge.sh`.

## Code changes (this PR)

1. **`glm-5.3-flash` becomes a built subject.**
   - It was Agam's external text-only app (`modal_built=False`, an Agam-box `tokenizer_dir`).
   - vLLM 0.31.0 registers `Glm5NextForConditionalGeneration`, so it runs on the default image
     as its own app `adapt-glm-5.3-flash`:
     - TP4 on B200:4, with H200:4 as the fallback;
     - weights are ~328 GB FP8;
     - `language_model_only`.
   - The pinned snapshot lives on a new volume `glm53-flash` in hub-cache layout, mounted at
     `/hf` as kimi-k3's is.
   - The tokenizer comes from the hub at the pinned revision.
   - The no-think template is `data/templates/glm53_flash_nothink.jinja`. It is the upstream
     template with GLM-5.3's two edits: default effort `low`, and the generation prompt
     `<|assistant|><think></think>`.
     - A test checks it token for token against the upstream render at
       `reasoning_effort="low"` + `</think>`, with and without a system turn.
2. **`kimi-k2` keeps the kimi-k3 recipe** (vLLM 0.31.0 default image, B300:8 TP8, native block
   FP8). The only new thing: the pinned ~1.03 TB snapshot is on a new volume `kimi-k2`
   (`modal_weights`), downloaded once by a CPU function. No B300 container downloads weights.
3. **The five keys join `refill.PLAN_0075_SETS`.** A key outside it keeps registered-size
   targets and skips the 0075 capital re-check and strict-freeze guard. With it, the targets
   match the ten sets: association 100, basic_readout_mt 120, typo_mt / multihop / role_bound /
   multilingual mt families 100.
   - *Retained:* every other key still gets the registered size and the old guard. A
     stand-in key (`some-new-subject`) keeps that rule tested.
4. **Doc strings and skill text** no longer call glm-5.3-flash / kimi-k2 Agam-only.

## Pre-existing test changes (each sanctioned here)

| test | change | why |
|---|---|---|
| `test_adapt_refill_0075.py::test_adapted_target_raises_never_lowers` | gemma's assertion moves from "registered size" to 120 (all five keys); the registered-size rule is asserted on `some-new-subject` | change 3 |
| `test_adapt_refill_0075.py::test_guard_is_unchanged_outside_the_ten_sets` | stand-in `other` key gemma -> `some-new-subject`; plus gemma now gets the 0075 guard | change 3 |
| `test_adapt_subject_modal.py::test_kimi_needs_nothing_from_agams_box` | extended only (volume / weights; flash checked for Agam paths) | change 2 |
| `test_adapt_subject_modal.py::test_remote_runner_refuses_apps_adapt_modal_does_not_build` | refusal tested on a monkeypatched fake external subject instead of glm-5.3-flash | change 1 |
| `test_adapt_subject_modal.py::test_deploy_refuses_an_external_app` | now runs the deploy script from a temp tree whose subjects.py registers an unbuilt subject; new `test_deploy_builds_glm53_flash` covers the flash / kimi-k2 deploy specs | change 1 |

Camila reviewed and approved these diffs before push (2026-11-15).

## Per-set build (data PRs, one per set)

The build runs in a local run tree with Agam's October dirs moved aside first. So no old row is
carried over, `run.shipped_ids` starts empty, and freeze notes list only this build's rows. Each
data PR then replaces the whole `adapted/<m>/` dir.

The order follows the 0060 phase scripts, the 0075 cycle drivers and plans 0077 / 0078 / 0084 /
0087. It is written down in the run tree.

1. Native-langs decision record.
2. Profile the 17 item-gated families, then the basic_readout subject golds and the nl upgrade.
3. Poetry v5 (variants fewshot, prefill), moral v3 re-key, carry (jailbreak re-screen, MCDM),
   and agentic twins plus pool v3.
4. Phase E: msdm, kcutoff, multihop_mt, wrong_intermediate (r1-r4 pools), nyt_connections,
   model_multihop (plus tier C when under 100).
5. Ladders: arithmetic bank v2 (no `frac`, plan 0083) and chain.
6. `adapt refill` for every family below target, buggy_code (24 pairs) included.
7. Freeze with every family named.
   - The onecue screen / repair / patch (plan 0087) runs before the first lucky run.
   - Then the item-quality screens and the lucky loop until it converges.
   - The final strict freeze comes last.
8. hinted_cutoff (plan 0084 pipeline re-run on the subject) and introspection:
   - The mid-size subjects use the single-GPU engine.
   - kimi-k2 / glm-5.3-flash need a multi-GPU residual stack. That stack is its own code PR,
     or a shown technical blocker.
9. Audit, floors (po-opus-v1 and stock-subject), notes, the README row and the census in
   `tests/test_typo_mt.py`.

## Cost (GPU; Claude API spend is logged per set, not capped)

Estimate: ~$2.6k–3.5k GPU for the core builds, plus hinted_cutoff and introspection, against a
hard stop of $4,000. Any projection past the stop is reported before it is crossed.
