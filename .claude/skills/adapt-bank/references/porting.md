# Porting: layers, tokenizer, read sites, and the model-specific families

## Layers
- Every read grid is in absolute Qwen3.6-27B layers, out of 64. The sets are:
  - `GRID` = 20..60 step 4
  - `SIX` = 20,28,36,44,52,60
  - `FIVE` = 20,36,44,52,60
  - arithmetic: [56, 60]
  - multi_concept_directed_modulation: [44,52,56,60]
  - agentic: GRID + 63
- Remap by depth fraction with `wsbench.adapt.subjects.remap_layers(layers, n_layers)`:
  `min(n - 1, round(L * n / 64))` (Python `round`: halves go to the even neighbour), then drop
  duplicates. `wsbench plan` applies it; never remap a plan again.
  - Qwen3.5-4B and 9B (32 blocks): L → L/2 (GRID → 10..30 step 2).
  - 0.8B and 2B (24 blocks): GRID stays 11 distinct layers, 8 9 10 12 14 15 16 18 20 21 22.
  - Gemma-4-31B (60 blocks): 19 22 26 30 34 38 41 45 49 52 56.
  - Gemma-4-31B: read `num_hidden_layers` from the config. The earlier port used a hand table
    (global-workspace c3ff939c `scripts/ola/port/wsbench_gemma.py` LAYER_REMAP).
- If the lens has a trained band, snap each remapped layer to the nearest band layer. That's what
  the prior Qwen-sizes port did.
- Since plan 0032 only arithmetic's `item.cell.layer` is a layer the judge reads from the bank:
  rewrite it in the adapted bank (freeze does). buggy_code `header.read_cells` and
  multi_concept_directed_modulation `header.layers` are still rewritten by freeze / carry but no
  longer read (`readplan.BANK_LAYERS` is empty): both read GRID remapped by depth.

## Tokenizer and positions
- **The Qwen3.5 sizes share Qwen3.6-27B's tokenizer, chat template and special tokens.** Every
  token index carries over unchanged:
  - multihop `readout.offsets`
  - mt `probe_token_lens`
  - jailbreak `read.tokens`
  - multi_concept_directed_modulation `last_n 12`

  Verify by re-rendering one item per family with the subject's tokenizer and diffing the ids.
- Any other tokenizer (Gemma) needs these re-stamped:
  - `probe_token_lens` (count = min over {s, lower, title} × {bare, leading space}). Then drop
    items whose required unit has no multi-token form left.
  - the multihop `offsets` (`[-2]` when the final token is a bare space)
  - jailbreak `read.{span, n_tokens, tokens, positions}` (GW c3ff939c `port_jailbreak`)
  - `last_n 12` → the sentence's own token count
  - user_modeling's `from_last_sentence_start` rule, which matches literal `<|im_start|>` /
    `<|im_end|>` and silently falls back to every token. Alias the subject's turn markers.
  - relational `BLANK_TOKEN "'s"`
- Gemma has no `<think>` block. The arithmetic cells assume Qwen's
  template tail, so re-derive them.

## Judging an adapted bank
`WSB_BANK_ROOT=adapted/<model> wsbench run families=<the adapted ones> readouts_root=… out=…`
- Every family's bank load goes through `registry.bank_path`.
- Judge an adapted bank via `WSB_BANK_ROOT` only, never `WSB_BANK_FILE_<FAMILY>`. The per-set
  judge resources (`adapted/<m>/<family>/<file>`, plan 0060 A2: `registry.load_resource`) and
  the loud "adapted-only id has no per-set entry" errors key on the root; a bank-file override
  reads the registered resources only and silently falls back for adapted-only ids.
- If a family is missing from the root, that's an error, not a fallback to another model's bank.
  So list only the families present in `adapted/<model>/report.json`.
- The frozen floors (`evals/baselines/`) were measured on the original banks. Re-measure them on an
  adapted bank before drawing them beside it (SKILL.md §4 Floors). `wsbench report` under
  `WSB_BANK_ROOT` still draws the frozen 27B floors (`cli.py`), so read the adapted ones from
  `adapted/<model>/floors/floors.json` and say which protocol they are.
- `wsbench baseline kind=prompt_only_opus stage=build` hard-codes the `Qwen/Qwen3.6-27B` tokenizer
  (`baselines/prompt_only_opus.py`): for a non-Qwen subject the render is decoded wrong until it
  takes the subject's tokenizer.
- ATI does not apply to adapted banks: `text_inversion` is scoped to the frozen 27B banks and its
  `bank_sha` guard refuses any other bank.
- Judge a refreshed set with every family `dry_run=True` first. A non-zero exit means a field the
  registered bank's judge requires (`mc`, `mc.candidates`, `mc_roles`, a consistent `bank_version`)
  was not built.
- A dry run catches only the exits. Many judge inputs fall back SILENTLY for an adapted-only id:
  - id-keyed resources, e.g. multihop `split_subjects.json`, role_bound `distractors_v3.json`,
    user_modeling's value pools, basic_readout_mt `exonyms.json`;
  - id-pattern rules (multihop `nhop-*-element`);
  - Qwen defaults (`native_langs`).

  Every family's judge inputs and their classes are in
  [`docs/adapt_judge_inputs.md`](../../../../docs/adapt_judge_inputs.md) (plan 0060 A2.0). Its
  machine-readable source is `src/wsbench/adapt/judge_inputs.py`, which provides
  `REQUIRED_ITEM_FIELDS`, `SUBJECT_FIELDS`, `ADAPTED_ONLY_FIELDS` and
  `check_item(family, item, header)`. Run `check_bank` over a refreshed set before judging it.

## Families whose gold is the subject's own answer (stamped by `profile` / `gate`)
**Render caveat.** `gate_variant` records which render the subject committed in: `chat` (asked to
continue) or `plain` (raw continuation, the bank's read render). On Qwen3.5-4B, 65 of the 67
poetry passes were chat-only. A lens read in the plain render is then reading a context where the
subject may not have committed to that word. The producer must read the render in `gate_variant`,
or keep only `plain` items and report the count.

- **poetry** (this paragraph is the v1 stub gate that built the 11 sets; bank v5 adds the free
  line-two leg, `line_one_end` and `mc.candidates`: families.md §poetry "Bank now"): greedy plain
  continuation of the stub. Its first word must rhyme with line 1's end
  word (CMU), and ≥ 8/10 samples must give the same word. It becomes `intermediates[0]`; the
  authored word is kept as `authored_rhyme`. An echoed tail of line 2 is skipped before the first
  word is taken ("clear as a bell" after "...as clear as a" -> "bell").
  **Format scaffolds for small subjects** (opt-in, `ADAPT_POETRY_VARIANTS=fewshot,prefill`): a
  subject that restates the couplet in chat and emits digits in plain (Qwen3.5-0.8B: 0/100
  originals) gets two extra alternative legs: `surface:fewshot` (two complete couplets before the
  target, plain; `gate_variant: plain_fewshot`) and `surface:prefill` (user "Write a rhyming
  couplet.", the assistant turn prefilled with line 1 + the line-2 stem; `gate_variant:
  chat_prefill`). The latent (the rhyme planned at the end of line 1) and the read site (the
  newline ending line 1) are unchanged. `wsbench plan` reads `chat_prefill` items in the
  `chat_prefill` render at `last_newline` (inside the prefill) and `plain_fewshot` items with the
  few-shot prefix; **a producer must read that render**, never the bare couplet. 0.8B on 30
  originals: prefill 10/30, fewshot 1/30, plain 1/30, chat 0/30, so its poetry uses prefill only.
- **basic_readout implicit:** chat with the stem "My one-word answer is:". The greedy first word
  becomes `target`, `intermediates` and `units[].match` when ≥ 8/10 samples agree. Refill from the
  55 implicit topics in GW `scripts/oracle_lens_evals/gen_basic_readout.py`. Never author the
  gold.
- **moral_rationale** (the steps below are the v1 flow that built the 11 sets; the registered bank
  is now `items_v3`, see the box after them):
  1. The gate records the subject's side (`subject_answer`, consistent ≥ 8/10).
  2. For every item: ask the topic's `question` with the elicitation instruction, greedy + 8 samples
     at T=0.8, 96 tokens, thinking off.
  3. Opus distils reasons with `supports` from those draws (prior: 1f36ca88
     `pmeq_gen/skill_patch/moral_gate.py`).
  4. Set `look_for_reasons`: committed → the top reason for the side taken; deliberative → top yes
     and top no.
  5. Gate = token ∧ precise ∧ aligned ∧ **reason supports the side taken** (21 frozen items fail
     that last check; don't copy them).
  6. **Prose answerers** (Gemma-4-31B: 161/200 open with "This is a classic dilemma…"): run
     `moral stage=variant` before `apply`. It re-gates the originals with the system turn
     `item["system"]` ("Reply with exactly one word: yes or no / true or false. No other text.";
     `gate_variant: system_one_word`), which names both sides and so never suggests one. Pilot on
     30 Gemma failures: 25/30 consistent one-word (17 no / 8 yes), vs 1/30 as asked, 14/30 with an
     answer-stem prefill, 1/30 with "Start your reply with Yes or No". **The producer must read the
     same render:** `wsbench plan` emits `system` for these items (chat render, system + user, last
     5 positions = the assistant header before the side token). If the elicitation draws also open in
     prose (no yes/no, so `aligned` is vacuous), run `moral stage=variant_elicit` (system turn
     "Begin your reply with one word, yes or no. Then give one short sentence."; Gemma 57 → 91/100
     topics with a yes/no-led draw); move `moral/distilled.json` aside first (distil skips done topics).

  **Bank v3 (registered since #190):** 195 items, `bank_version: 3`, instrument `ec-v9`, frozen
  `options` per item (`scripts/moral_distractors.py`), `rekey` / `reason_side_ok`; side and reasons
  are sampled in the READ conversation (plan 0046). Two traps:
  - `adapt moral stage=rekey_readrender` (which AGENTS.md names for a new model) ignores `model=`:
    it samples Qwen3.6-27B (`moral.py` `run`, `scripts/qwen_sample_modal.py` `MODEL`). There is no
    subject version yet (plan 0060). Running it for another subject re-keys to Qwen's sides.
  - `profile` on v3 rewrites the side / reasons but keeps Qwen's `options`, so options and reasons
    disagree. `moral_distractors.py` builds options for the bank of record only (it writes
    `evals/moral_rationale/items_v3.json` from Qwen's `rekey.json`): a subject-keyed option build
    is open (plan 0060). Never run it for an adapted set.
  The judge checks `bank_version` per item and refuses a mix; v3 is a bare list (no header).

- **role_bound_association (gate only):** subjects that answer with names instead of roles
  (OLMo-3-7B, "Tony shaved Hank.") are graded through the name→role rewrite (`name_roles`:
  "the <role> (<name>)"); re-run `regrade` on sets gated before it existed. `gate_variant:
  ask_roles` appends "Answer with their roles or occupations, not their names." (OLMo-7B: +11/80).
  The read plan never uses the asked question, so the producer is unaffected.

## Regenerated on the subject
- **directed_modulation:** compliance gate (`grade="compliance"`): the reply is the carrier word for
  word (quotes stripped) and never names the concept, at ≥ 8/10. Pairs are atomic. The prior
  per-model banks skipped this screen; don't.
- **agentic_misalignment:**
  - Rollouts: n=8, T=0.9, 512 tokens (GW `scripts/diagnostic/rollout_vllm.py`).
  - Judge committed / deliberating / refusing with the repo's commitment judge.
  - Keep only items with misaligned rollouts; set `misalignment_rate`, `rollout_pick` and `prefill`.
  - Fewer than ~5 → status `blocked` ("not exhibited"). Never pad from another model.
- **jlens_concept_pr:**
  - Needs the subject's own J-lens: HF `neuronpedia/jacobian-lens` (qwen3.5-0.8b/2b/4b,
    gemma-4-31b, deepseek-v4-flash n=25) or one fitted with `scripts/fit_jlens_modal.py` (the
    official estimator, neuronpedia's recipe; validated on the 4B at per-layer cosine ≥ 0.927).
    `blocked` only if neither exists.
  - `scripts/adapt_jlens.py` / `adapt_jlens_modal.py` read the seed items from GW
    (`/workspace/agam/global-workspace/evals/workspace-bench/jlens_pr/items.json`), not from this
    repo's `evals/jlens_concept_pr`: `GW` is a hard-coded `Path` constant (`adapt_jlens.py:26`), not an env var: edit it to a
    local global-workspace checkout off Agam's box.
  - Roll out the seeds, pick the read position with `pick_read_position`, capture at the remapped
    layers, and write the top-10.
- **jailbreak_recognition:** items carry over; re-stamp positions (above). There's no gate on the
  positives. Bank v2 (plan 0037) adds 86 controls (`kind`, `twin_of`, `control_type twin|roleplay`)
  that were gated on Qwen (`capable/questions.py`); `carry` copies them from the registered bank
  WITHOUT re-screening them on the subject. Re-screen the controls on the subject before counting
  the net headline (recall − control FPR); without controls the headline is None. Optionally ask
  the subject outright whether the last turn tries to override its rules (≥ 8/10), and report the
  rate.
- **multi_concept_directed_modulation:** no gate. Reproduce the prefill render with the subject's
  template (`carry`, from bank v2, 116 items); header layers are no longer read.
- **agentic_misalignment v2 twins:** bank `items_v2` pairs each scenario with a clean twin (plans
  0031 / 0052); an adapted bank keeps only scenarios the subject misbehaves on and has no twins, so
  its headline is None (out of the macro). Port the twin of every kept scenario (and gate that the
  subject does NOT misbehave on it) to get a headline.

## Refill pools (plan 0066; box-only, sha256-pinned)

The three refill pools are model-independent and are built once on the box by
`scripts/build_adapt_pools.py <msdm|kcutoff|mh2|all> [--out DIR]` (default
`$WSB_POOL_DIR` = `/workspace/wsb-runs/pools/`). They are NEVER committed (decision 3). Each
file's sha256 is pinned in `wsbench.adapt.refill.POOL_SHA256`, and every loader refuses a missing
file or a mismatch. Sources (read by exact path):
- `msdm_pool.jsonl` ← gw-evals-feas `outputs/feas/self_answers/{step1,step2,step3/b1,step3/b2}/`
  `cats.json` + `gate.json` (normalised peer / legacy labels, Opus / Sonnet typical where present);
- `kcutoff_pool.jsonl` ← gw-evals-feas `outputs/feas/cutoff_confab/scale/b1/gate.json` rows and
  `scale/b2/{questions.json,gen_in.jsonl}` (joined by key), content-deduped against the bank;
- `mh2_pool.json` ← gw-mh-v2 `outputs/multihop_v2/` (the 9 candidate / adversary pools
  `finalize.py` reads), adversary `problem` / `factual_issue` rows dropped.

The vendored CC0 Wikidata tables `data/wd_class_parents.json` / `data/wd_registered_bprime.json`
(wrong_intermediate's entity check) are built by `scripts/build_wd_tables.py`.

## OLMo-3-7B-Instruct (scoped 2026-10-17; `allenai/Olmo-3-7B-Instruct` @ 6e5971d9)
- 32 blocks, untied embeddings (real `lm_head`), Dolma2 tokenizer (100k vocab vs Qwen's 248k).
- Same ChatML markers (`<|im_start|>` / `<|im_end|>`): user_modeling's `from_last_sentence_start`
  works. `'s` is one token: relational unchanged.
- The template injects a default system prompt ("... no access to any functions.
  <functions></functions>") when none is given, and has NO think block: every offset counted
  from the end of a Qwen chat render (arithmetic `cell.pos`) moves by the 4-token
  `<think>\n\n</think>\n\n` tail. Re-derive per item from the OLMo render, never by a constant.
- Re-stamp with the OLMo tokenizer: `probe_token_lens` for every `*_mt` family (then drop items
  whose required unit lost all multi-token forms, and apply the canonical-name rule), the
  multihop `offsets`, jailbreak `read.*` (`carry` refuses until done), mcdm `last_n`.
- J-lens: neuronpedia has only the base model (`allenai/Olmo-3-1025-7B`), so jlens is `blocked`
  for the Instruct subject unless a base-model lens is accepted.

## DeepSeek-V4-Flash (plan 0060 A3; `deepseek-ai/DeepSeek-V4-Flash` @ 60d8d707)
- 43 blocks, d 4096, tokenizer family `dsv4`. No Jinja template ships: the Subject pins
  `src/wsbench/adapt/data/templates/deepseek_v4_chat.jinja`, which reproduces
  `encoding_dsv4.encode_messages(thinking_mode="chat")` = `<bos><｜User｜>…<｜Assistant｜></think>`
  token for token (`tests/test_adapt_v4.py`; thinking stays off whatever `enable_thinking` says).
  `author.tokenizer` and `RemoteRunner` apply it with no `tokenizer_dir`.
- Role-named user marker (like GLM's `<|user|>`): `markers` gives turn_start `<｜User｜>`,
  turn_end `<｜Assistant｜>`, header_len 1, gen_tail `["</think>"]`; `bos_prefix` = `[<bos>]`.
  A system turn is its bare content right after `<bos>` with no marker (`template.system_rule`
  = `"bare"`).
- carry: the jailbreak re-stamp (span = the last user turn's content, turn_end `<｜Assistant｜>`)
  and the MCDM prefill check both hold on every item by character span.
- arithmetic (D8): the render ends `<｜Assistant｜></think>`, so Qwen's -7 cell has no
  counterpart. `Subject.arith_all_positions` makes freeze store `cell.pos = None` (`pos_qwen`
  kept); judge with `opts=cells=all` (summary mode does already) and report the lift over the
  permutation null beside it. The native `cells=frozen` judge refuses such a bank.
- `read_band` = J-lens `std-n1000` rows 0..40 (row r = block r; row 41 is the identity anchor,
  there is no L42 row).

## DeepSeek-V4-Pro (plan 0060; `deepseek-ai/DeepSeek-V4-Pro-0813` @ 72e1d323)
- 61 blocks, tokenizer family `dsv4`. Its `tokenizer.json` / `tokenizer_config.json` are V4-Flash's
  byte for byte, and its `encoding_dsv4.py` differs only in the thinking-mode reasoning-effort
  prompts, so the chat-mode render is Flash's: the Subject reuses `deepseek_v4_chat.jinja`
  (`tests/test_adapt_new_subjects.py` runs Pro's own encoder against it). Markers, `bos_prefix`,
  `system_rule = "bare"` and carry: as V4-Flash.
- arithmetic (D8): as V4-Flash, `arith_all_positions=True`.
- No J-lens: `read_band=()`. Served as ONE TP8 engine on B300:8 (`modal_engines=1`, unlike
  Flash's 8 TP=1 engines), the `dsv4` image, volume `v4-pro`.

## Kimi-K3 (plan 0060; `moonshotai/Kimi-K3` @ f831ab66)
- 93 blocks, tokenizer family `kimi3` (tiktoken remote code, `trust_remote_code`). No Jinja: the
  tokenizer's `apply_chat_template` renders XTML (`encoding_k3.py`), and its switch is
  `thinking` (default True); `enable_thinking` falls into `**kwargs` and is ignored, so without
  `Subject.thinking_kwarg="thinking"` every render opens the think channel after a
  `thinking_effort=max` system message (`template.check` refuses that).
- `thinking=False` drops the think channel: `<|open|>message role="user"<|sep|>{q}<|close|>message
  <|sep|><|end_of_msg|><|open|>message role="assistant"<|sep|><|open|>response<|sep|>`. Nothing
  is left open, so there is no prefill-close. The README's "always has thinking" describes the
  API; the encoder supports a non-thinking render and that is what is used (the smoke test should
  confirm replies are answers, not reasoning).
- `markers`: turn_start `<|open|>` (the one whose `role` attribute is `user`), turn_end
  `<|close|>`, header_len 7, gen_tail `message <|sep|> <|end_of_msg|> <|open|> message role="
  assistant" <|sep|> <|open|> response <|sep|>`; `bos_prefix = []`; `system_rule = "marker"`.
  carry's jailbreak re-stamp skips the whole header by `header_len` (every template now).
- Stops: `generation_config.json` eos `<|end_of_msg|>`; a reply ends `<|close|>response<|sep|>
  <|close|>message<|sep|>` first, and those markers are not special tokens (the detokenizer keeps
  them), so `Subject.reply_end="<|close|>"` makes `RemoteRunner` stop the engine on the
  `<|close|>` TOKEN (163588; sample and generate). A reply that writes the string as BPE text is
  untouched.
- Prompt ids: the template encodes content with specials disallowed, so re-encoding the
  rendered text would make a literal `<|close|>` / `<|sep|>` in a message (floors quote the
  subject's own render) a live control token. `Subject.template_ids=True`:
  `RemoteRunner.prompt_ids` takes the template's own ids, with prefill, reply and raw text
  encoded plain (`encode(..., allow_special_tokens=False)`); floors, follow-ups and wrong_bridge
  send `prompt_of(runner, ask)` ids.
- No J-lens: `read_band=()`. Default image (vLLM 0.31.0), TP8 on B300:8, engine kwargs
  `trust_remote_code`, `language_model_only=True`, `gpu_memory_utilization=0.95`; volume `kimi-k3`
  mounted at the default recipe's `/hf` (snapshot `/hf/hf/hub/models--moonshotai--Kimi-K3/...`).

## Muse-Spark-Open (plan 0060; `meta-models/Muse-Spark-Open-816B-A42B-NVFP4` @ 4239e4db)
- 62 blocks, tokenizer family `muse`; gated (the HF token needs access). No thinking-off mode:
  the pinned `data/templates/muse_spark_nothink.jinja` is the upstream template with three edits:
  `reasoning_effort` pinned `low` ("Reasoning strength: 8."), `current_date` pinned `2026-11-03`
  (upstream uses today's date), and the generation prompt `<|start|>assistant to=user<|message|>`
  (the answer channel; upstream leaves the recipient to the model, `to=self` = reasoning).
- `markers`: turn_start `<|start|>`, turn_end `<|eot|>`, header_len 3, gen_tail `<|start|>
  assistant to =user <|message|>`; `bos_prefix = [<|begin_of_text|>]` (the tokenizer does not add
  it); `system_rule = "marker"` (a system message joins the template's own system turn).
- Stops: `generation_config.json` eos `[200001, 200008]` (`<|end_of_text|>`, `<|eot|>`), which
  vLLM applies from the checkpoint dir.
- No J-lens: `read_band=()`. `muse` image (vLLM 0.33.0), TP8 on B300:8 (B200:8 fallback), volume
  `muse-spark` with the plain snapshot dir `hf/meta-models__Muse-Spark-Open-816B-A42B-NVFP4`.
- The image carries flashinfer's prebuilt JIT cache (`flashinfer-jit-cache` 0.7.2.post1+cu130,
  sm103a + sm100a providers): building `fused_moe_trtllm_sm100` at engine start segfaults
  cc1plus on B300 (gcc ICE, every TP rank, the container crash-loops). A first boot is ~25 min
  (weights ~6-12 min off the volume, then the trtllm fp4 MoE autotuner).

## Lens read band (`Subject.read_band`)
If the subject's lens reads only some layers (Qwen3-8B's OLens: even layers 12..34), set
`read_band` on the Subject. `remap_layer(s)` then depth-remaps and snaps to the nearest band layer
(ties go deeper), in the plan (`readplan.plan` reads `report.json` → `read_band`), at freeze
(arithmetic `cell.layer`, buggy_code `read_cells`) and in carry (mcdm `layers`). Never ask
consumers to snap at readout time: banks that store layers are judged by those layers.
