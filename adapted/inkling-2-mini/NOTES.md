# inkling-2-mini: notes on the looped subject

Built 2026-11-23 on workspace-bench main **5a5d8376** (#544, the Subject, on top of #546, directed_modulation
bank v2). Later merges were not picked up mid-build: #549 (user_modeling_hard v4), #551 (chain_intermediates
bank v3, fast-v5), #570 (the other sets' DM v2), #569. **chain_intermediates here is on bank v2 and may be
re-gated on v3 as a follow-up.**

## Subject definition

- thinkingmachines/Inkling-2-Mini @b85c3cfa615fc413cc9af3379f491b963f3b586a. Camila: the released mixed
  NVFP4 / MXFP8 checkpoint is the subject.
- A looped MoE VLM, used text only:
  - 24 blocks; blocks 6-17 run 3 passes. Passes 2-3 restart from the pre-loop state and take gated
    messages from the previous pass.
  - Every block's input is an attention mix over 6-block "block states" (attention residuals).
- Template: a pinned no-think template, `data/templates/inkling2_mini_nothink.jinja`.
  - effort "none" (system line "Thinking effort level: 0");
  - the generation prompt opens `<|message_model|><|content_text|>`;
  - `reply_end` `<|end_message|>`; no BOS.
- native_langs `['en']`: an American lab, by lab decision (plan 0089).

## Gate vs lens read side (coordinator 2026-11-23)

| side | engine | numerics |
|---|---|---|
| **gate** (every subject answer in this set) | vLLM image `vllm/vllm-openai@sha256:c2dc759f…449e` (tag inkling-2-mini, vLLM 0.35 nightly), Modal **B200 only** (no sm90 kernel) | NVFP4 **W4A4**, per-token NVFP4 activation quantization, as the checkpoint specifies |
| **lens activations** (J-lens fit, J-lens / logit-lens readouts, introspection, the stored activations) | HF **transformers 5.24.0**, B200 | modelopt is not implemented: experts **dequantized to bf16, no activation quantization** |

An Oracle lens should be matched against this split.

**Parity** (B200, 12 chat prompts; `scripts/inkling_parity_modal.py`):
- Unrolled vs stock logits: bitwise equal.
- hidden_states[0..47]: bitwise equal. Stock's last element is its final-mixed, normed state.
- Hooks fire once each, in order; capture is bitwise equal to plain.
- Greedy: stock == unrolled.
- **vLLM vs HF greedy:** 2 of 12 prompts are identical over 48 tokens. Teacher-forced top-1 agreement is
  98.0% (vLLM scoring HF's greedy) and 96.3% (HF scoring vLLM's).

**Pass/fail agreement on the set** (`/root/tmp/wsb-inkling/hfagree/hf_agree_150.json`):
- Method: 150 random frozen items re-asked by HF greedy with the same template, the same family asks and
  the same graders. Compared against vLLM's greedy verdicts.
- Result: **96.7% agree** (145 of 150).
  - Per family: role_bound 11/14, multilingual 8/9, poetry 1/2.
  - Every other sampled family agrees fully: arithmetic 32/32, user_modeling 16/16, multihop_st 11/11,
    typo 9/9, and others.

## Layers: the unrolled view and the read sites

`wsbench.adapt.inkling_loop.unroll`: 48 entries in execution order.

| entries | section |
|---|---|
| 0-5 | pre-loop |
| 6-17 / 18-29 / 30-41 | passes 1 / 2 / 3 of blocks 6-17 |
| 42-47 | post-loop |

- Entry L = the output of that block call = unrolled `hidden_states[L+1]`.
- **Read / inject sites**, Camila 2026-11-23, verbatim: "do every other layer, including unrolling the loop
  part. it's the same way dory was trained, just on the looped layers."
  - That is odd entries **1, 3, …, 47** (24 sites; `subjects.INKLING_READ_BAND`, the one definition).
  - Passes 1 and 2 are included.
- The bench's 11-layer grid remaps by depth to sites 15, 19, 21, 25, 27, 31, 33, 37, 39, 43, 45.
- Introspection injects at entry 9 (12/64 by depth; a site).

## J-lens and logit lens

- **J-lens:** `/workspace/wsb-out/inkling-2-mini/jlens/lens.pt`,
  sha256 `03d0f773e5c0ed404dbfe42ff97c488aedc0f276a2d5846e05ecfa1b21fd954e`.
  - The Dory recipe: pile-10k first 25 docs ≥ 600 chars, skip_first 4, t_max 128, uniform weighting.
  - Sources are the sites below the target (1, 3, …, 45); target 46.
  - Deviations, listed in the provenance:
    - site 47 has no J row;
    - per-prompt fan-out over 25 B200s;
    - dim_batch 24;
    - no BOS (the tokenizer defines none).
  - Fit GPU: 1,941 container-s plus check and sanity.
- **Logit lens** = `W_U·norm(h)` (the bench `LogitLens`).
  - Inkling's own `final_input` block mix before the norm is not applied, since it needs every block state.
- **Readouts:** tokens10 at the 11 grid sites. They are cross-checked against the bench `JLens.read` /
  `LogitLens.read` (8 cells per job).
- Activations at every read cell are stored (fp16) on Modal volume `inkling-acts`, for an Oracle lens.

## Build and data round (Camila's speed request, 2026-11-23)

- **Build and refill:** parallel per-family chains running the driver's own commands, with
  `ADAPT_AUTHOR_EFFORT=low`, `ADAPT_FILL_PARALLEL=6` and `ADAPT_FILL_WAVE_MAX=120`.
  - A Claude OAuth outage paused every Claude step from 04:50Z to 06:37Z.
- **One data-round cycle** ran (c1: onecue, D4-D7 screens, 2 lucky runs, the two-run leaker rule:
  288 drops). Then the set was frozen. This is an **early_freeze**, "time-boxed at Camila's speed
  request, 2026-11-23".
  - Families short or untried ship as they are. `allow_untried` is stamped in their notes.
  - basic_readout's last refill wave was stopped unfinished.
- **Audits:**
  - The independent audit applied 184 drop ids (191 rows with role_bound twins).
  - Re-freezes back-filled from gate-passing rows. Addenda 1-4 (400 / 88 / 40 / 25 rows) dropped
    103 / 41 / 26 / 15, plus dorothy-baum (D4).
  - The final re-freeze is **drop-only**. Every gate-passing pool row no audit read was dropped
    ("drop-only final freeze … never audited; not shipped"), mostly relational_multihop's 2,740 repeats.
  - The last re-freeze adds nothing.
- **Known follow-up:** the Indonesian multilingual items list "Malay" as a wrong language option, which
  needs a list patch (AUDIT.md). The multilingual_typo rows where Malay is also correct were dropped.

## agentic_misalignment

- am-pool-v3 hit refill's objective stop (1/80).
- Per the coordinator, waves ran over the pinned pools v4..v7, newest last, with no threshold change
  (`agentic/pools_v4v7.json`): v4 0/80, v5 2/80, v6 1/80, v7 … each to the objective stop.
- 7 pairs; below 20, so out of the macro.

## Introspection: ooc

- Calibration NO-GO: peak median RR 0.043 at every beta (baseline 0.039); the coherence share stayed 1.0.
- Engine checks pass (`introspection/engine_diagnostic.json`):
  - β 0 is an exact no-op;
  - the steer is local (in-span = h + β|h|u to bf16, pre-span unchanged);
  - it reaches site 27 (span cosine change .128) and entry 47 (.017).

## hinted_cutoff: 41 pairs

- Probe: cutoff ~2025-02.
- The window was widened to `HC_P_WINDOW=2023-01-01,2025-06-30`, because the v2 window's confirm
  projection was 57.9 < 60. The 2023 pool is olmo's web-checked one, with 3 qids excluded as for
  qwen3.6-35b-a3b.
- Pairing used the R3 fallback (`v2_attempts=1 allow_leaky=True`), with `HC_GUESS_GAP=20`.
- Its own audit dropped 47 pairs.
- Bar: day AUROC 0.490, cell excess +0.052.
- Obscurity AUROC 0.788 (`date_leak.pass` false; not in the bar, as on dory / gemma / qwen3.6-35b).
- **Prompt-only predictors: predict_single I−N +0.000, predict_normal +0.000.**
- gw commit 2027ef208.

## Floors and ATI

- **Floors:** `po-opus-v1` (Sonnet 5.5 fallback) and `stock-subject-v1`.
  - Arithmetic's stock floor is not measured: the Modal stream was lost 4 times, including at 128-prompt
    chunks.
- **ATI:**
  - panel = subject (vLLM), Opus 5.5, astra (`openai-wif`), argon (`gemini-wif`);
  - rule = all fail all 3 draws;
  - output in `/root/tmp/ati-all/inkling-2-mini/`.
