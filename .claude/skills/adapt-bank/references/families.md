# Families: latent, gate, invariants, difficulty ladder

Each entry gives what must stay fixed and the ordered tiers. T0 is the original difficulty; each
later tier eases the knob that matters most, and the **floor** is the easiest version that still
carries the latent. Below the floor the family is `ooc`, never padded.

Source paths: GW = global-workspace (on Agam's box `/workspace/agam/global-workspace`; any
checkout of it elsewhere), WB = this repo. "Gen" names the original generator; "Gate" is how the
subject is asked.

**"Bank now"** (added 2026-11-02) names each family's registered bank (`EvalSpec.bank`, what
`profile` / `freeze` read) and the fields its judge requires. The 11 adapted sets were built from
the v1 banks and lack these fields; see SKILL.md §State and §Refresh. Where "Bank now" and an older
line of the same entry disagree, "Bank now" is current.

Default gate: chat template, thinking off, assistant stem, greedy + 10 @ T=0.7 (top_p 1), pass =
greedy right AND ≥ 8/10. Exceptions (the bank's own gate sampling, `families.py`): chain
T=0.8, top_p 0.95, 10/10. Regeneration steps: moral 8 @ T=0.8 top_p 0.95; agentic 8 @ T=0.9
top_p 0.95, 512 tokens, keep a misaligned scenario at rate ≥ `MIN_RATE` 0.375, `blocked` under
`MIN_KEPT` 5 misaligned; floors T=1.0, 256 tokens.

Tokenizer-tied fields (`readout.offsets`, `probe_token_lens`, `eval_positions`, `read.tokens`,
`last_n 12`) carry over unchanged for the Qwen3.5 sizes. On other tokenizers they must be
re-stamped (`references/porting.md`).

---

## Basic (single token) — association, basic_readout and multihop are now BLIND-MC judges
## (basic_readout / multihop: `basic/family.py` `MC_FAMILIES`; association: its own
## `evals/association/judge.py`): every item needs its frozen `mc` block, or the judge exits 2.
## No MC builder takes adapted items yet: SKILL.md §3 step 6.
## typo stays on the bank judge (and is superseded by typo_mt).

### association — the referent a vignette evokes but never names
- **Keys:** `name, prompt, intermediates[1], source, consistency, gate_variant:"referent",
  eval_render:"plain", readout{final_prompt_token,[-1]}`. Add `aliases` (for gating only).
- **Gate (plan 0060 D10, in the read render):** after the subject's greedy summary of the scene
  (`chat_summarize`), the follow-up "The story you just summarized describes something it never
  names. Reply with the single word or short phrase that names it, and nothing else." Graded
  `contains` against target + aliases; misses go to the LLM grader (synonyms are common).
  Greedy right AND >= 8/10. See [Gate in the read render](#gate-in-the-read-render-plan-0060-d10).
- **Invariants:**
  - no target or alias (stem-loose) in the prompt;
  - ends in `.!?`;
  - ≥ 8 words;
  - one dominant referent.
- **Ladder:**
  - T0: oblique scenes with affective or historical referents.
  - T1: concrete-noun referents (objects, places, sports, foods) with 3+ distinctive cues.
  - T2: near-defining cues (anvil + horseshoe + sparks → blacksmith), 1–2 short sentences, English
    only.
  - Floor: T2. Below that the cue list *is* the definition, so it is still a latent but an easy one.
    Flag it in the note.
- **Main knob:** cue strength.
- **Bank now:** `items_v3` (93 items; plan 0039 + round 4): `mc` {gold, aliases, distractors[7]}
  (lint requires it, `adapt/lint.py`), leakage-screened on the bank of record
  (`scripts/association_distractors.py`, `scripts/mc_leakage_r4.py`, topic guesser; these write
  `evals/`, never run them for an adapted set); quote gate + pins. Read render `chat_summarize`
  (19-position suffix span × GRID; lite = all positions), so `eval_render` / `readout` are no longer
  needed. The adapt gate's referent question is asked in that render too (plan 0060 D10; records
  gated before it carry no `sampling.gate_render` and `adapt regrade` skips them: regate), and
  regating a v1 association item without `mc` is destructive (lint rejects it, last record wins). 7 v1 ids left the bank: drop them.

### basic_readout — the obvious next concept (entity / processing / implicit)
- **Keys:** `name, subfamily, prompt, target, intermediates, units[{role:"readout",lang:"en",
  headline:true,match:[…]}], consistency, source, gate_variant, eval_render, readout`. Put case and
  number-word variants in `units.match` (`["6","six"]`).
- **Gate:**
  - entity and processing: the chat gate prompt plus stem, graded `contains`.
  - implicit: see porting.md (own favourite).
- **Gen:** GW `scripts/oracle_lens_evals/gen_basic_readout.py` (templates over hand lists).
- **Ladder:**
  - entity:
    - T0: as is.
    - T1: only the top-frequency entities (G20 capitals, world-famous athletes and musicians).
    - T2: drop the scientist and landmark templates.
  - processing:
    - T0: as is.
    - T1: single-digit arithmetic, day/month succession, plurals.
- **Invariants:**
  - target not in the prompt;
  - the prompt ends exactly before the answer;
  - the implicit gold is never authored.
- **Bank now:** `items_v5` (plan 0053; only 18/100 prompts kept from v1): question form with
  `task_context`, `slice`, `gate`, and `mc` with a balanced `gold_position` (built on the bank of
  record by `mc_leakage_r4.py balance`, which writes `evals/`). `restamp` rewrites `mc` for implicit items (`run.py`), but a distractor must also never
  equal the subject's own favourite (plan 0053). v6 is opt-in. The entity / processing ladder above
  predates v2: re-port from v5's items, then (once plan 0060 lands) refill with v5-shaped questions.

### multihop — the silent bridge (atomic number 26 → **iron**, surface "Fe")
- **Keys:** `name, prompt, target, intermediates(bridges), source, consistency, gate_variant,
  eval_render:"plain", readout{last_word_token,[-1] or [-2]}`. The offset is tokenizer-specific.
- **Gate (two legs):**
  - surface: continuation and chat fill-in for `target`;
  - **bridge:** a direct question whose answer is the bridge ("Which element has atomic number
    26?").
  - The bank never gated the bridge leg. New items carry `bridge_question`; the 100 originals get
    theirs from `src/wsbench/adapt/data/multihop_bridges.json` (model-independent, authored once).
- **Invariants:**
  - bridge ≠ target;
  - neither appears in the prompt;
  - starts with "Fact:";
  - one-word target;
  - no trailing space.
- **Ladder:**
  - T0: as is.
  - T1: famous bridges plus common relations (country → capital, language, currency;
    author → book).
  - T2: the most famous bridges only (Paris, Einstein, Japan) with the easiest final relation
    (capital, continent, language).
  - Floor: T2. One hop is the minimum, and there is no 0-hop.
- **Main knob:** bridge salience.
- **Bank now:** `items_v3` (plan 0048, `MC_BANK_FAMILIES`): `mc` per item
  (built on the bank of record: `scripts/build_multihop_mc.py` wrote v2, `mc_leakage_r4.py` v3;
  both write `evals/`;
  no adapted-item builder yet), leakage-screened; quote + `mc.form_in` + number-flood gates;
  every-position reads. The authoring brief writes no `mc`: build it after the gate.

### multilingual — the English concept behind a non-English answer
- **Keys:** `name, prompt, target, intermediates[1 English gloss], reference_concepts, source,
  consistency, gate_variant, eval_render:"plain", readout{final_prompt_token,[-1]}`.
- **Gate:** continue or fill in "in the same language as the text". An English answer counts as
  wrong.
- **Invariants:**
  - no cognate (fold(gloss) vs target `SequenceMatcher` < 0.85);
  - neither the target nor the gloss in the prompt;
  - exactly one gloss.
- **Ladder:**
  - T0: about 15 languages.
  - T1: fr, de, es, it, pt, plus the subject's best other L2 from the profile.
  - T2: those languages with relations limited to numbers, days, colours and basic opposites, plus
    an explicit cue word.
- **Main knob:** language resource level.
- **Bank now:** `items_v3` (plan 0054): language units hold NAMES only, every unit required, items
  carry `mc` + `mc_roles` + `lang`; header `contract.native_langs` (measured per subject, plan 0054
  R6); scorer `mc+regex`. The author already emits the v2 shape (`author.py`); the gate legs still
  check the surface form only (no language-name leg). A v1 adapted bank silently runs the v1
  fallback (`v1_scorer="bank"`).

### typo — the corrected word
- **Keys:** `name, prompt, intermediates[1], source, consistency, gate_variant:"family_chat",
  eval_render:"plain", readout{final_prompt_token,[-1]}`.
- **Gate:** "The last word of this text is misspelled. Reply with that word spelled correctly."
  Graded `first_word`.
- **Invariants:**
  - the prompt ends in the misspelling, with no punctuation;
  - the misspelling is not a dictionary word and the correction is;
  - edit distance 1–2;
  - the correction doesn't appear elsewhere in the prompt.
- **Ladder:**
  - T0: as is.
  - T1: edit distance 1, common words of 6+ letters, strong sentence context, no proper nouns.
- **Caveat:** the prompt-only baseline already scores 1.00. Always report the family beside its
  floor.
- **Bank now:** superseded by typo_mt (`superseded_by`, out of `all` and the macro). Don't refill it.

### poetry — the rhyme word the subject commits to (model-specific; see porting.md)
- **Keys:** `name, prompt` (format `"A rhyming couplet:\n<line 1>,\n<line-2 stub> "`),
  `intermediates[1] = the subject's word`, `authored_rhyme` if it differs.
- **Read site:** `line_one_newline`.
- **Gate (own):** continue the stub. The greedy first word must rhyme with line 1's end word (CMU,
  not identical to it) and ≥ 8/10 samples must give the same word.
- **Ladder:**
  - T0: as is.
  - T1: idiomatic or cliché second lines with one strong completion, and common end words with dense
    rhyme sets.
  - T2: short lines (≤ 8 words) and monosyllabic end words.
- **Invariants:**
  - the rhyme word doesn't appear in line 2;
  - line 1's end word is in CMU.
- **Bank now (supersedes the gate above):** `items_v5` (plan 0038 + round 5; only 10/100 prompts
  kept from v1). The latent is the word the subject ends line two with when it writes line two
  FREELY from line one's newline (the modal line-final word of 11 free draws, ≥ 4 of them) AND the
  same word after the stub (≥ 8/10) (`evals/poetry/README.md`). Items carry `line_one_end`, a
  `qwen_commits`-style record of the subject's commitments, and `mc.candidates`
  (`scripts/poetry/build_mc.py`, after the gate); the headline is a blind free-response judge with
  a rival veto, but `run_family` builds the option set for every item, so a bank without
  `mc.candidates` exits. `families._poetry` gates the stub leg only: the free line-two leg is not
  in the adapt gate yet (plan 0060).

### directed_modulation — the held concept while copying a carrier (model-specific, porting.md)
- **Ladder** (only if compliance fails):
  - T0: original carriers.
  - T1: shorter carriers (≤ 8 words), plus a stronger "copy exactly" instruction.
- Never relax the equality rule. Pairs are atomic.

---

## Basic (multi-token) — regex scorer of record (`multitoken/regex.py`)

These rules apply to every new item in this group:
- **Units:** `units[] = {role, required, multi_token, forms:{lang:[…]}, match:[flattened forms]}`.
  `probe_token_lens.units[role][lang][i]` must align with `forms` (count = min over
  {s, lower, title} × {bare, leading space}, no specials; see GW `gen_hard_mt.make_ntok`).
- **Multi-token:** every required non-language unit needs ≥ 1 multi-token form.
- **Common keys:** `name, subfamily, prompt, target, target_alts, source, eval_render:"plain",
  readout{final_prompt_token,[-1]}, intermediates, units, probe_token_lens, consistency,
  consistency_strict, consistency_greedy, gate_variant, [lang, typo_word, bridges,
  bridge_consistency, mc]`.
- **Leak rule:** no word of ≥ 4 letters from target or forms appears in the prompt. Echo guard
  applies.
- **Gate:** chat, thinking off, stem "My answer is:". A sample passes if it contains `target` or any
  of `target_alts`. Each bridge question is a separate leg with the same rule.
- **MC:** families with `mc` need `{gold, distractors[4]}` written by Opus (same kind, same
  specificity). Language options come from `R4_LANG_POOLS` (the old pl…ko-only rule is gone).
- **Bank now:** basic_readout_mt `items_v4` (0/99 prompts shared with v1; `gate_v2`, `name_forms`;
  scorer of record `mc` + tolerant name gate); multilingual_mt `items_v4`, multilingual_typo
  `items_v3`, multilingual_multihop `items_v4` (`mc_roles`, v2 language units, `bridge_l2_*`;
  multilingual_multihop scores `mc+regex`, the other two regex with the `+v2+ln-…` tag); typo_mt
  `items_v2` (85 items, arithmetic dropped). Port `mc_roles` and the v2 units with the items.
  basic_readout_mt v4's gate is the question in chat, no system turn, graded by `name_forms`; the
  adapt gate (`_asked(CONTINUE, plain=True)`) does not match it, so the family is not buildable
  until plan 0060.
- **Lint:** GW `src/global_workspace/olens_suite/bank/lint.py::lint_hard_item` is the reference.
  Port its checks; don't skip them.

### basic_readout_mt — a multi-token proper name (entity) or name + language (l2_factual)
- **Ladder:**
  - T0: long tail ("long-tail, no school facts").
  - T1: "famous": names a well-read adult knows (Qwen3.5-2B went from 37% to 77% on entity items).
  - T2: textbook entities (famous dynasties, capitals of large countries, top-100 historical
    figures).
- l2_factual items: only the subject's strong L2s.

### multihop_mt — removed 2026-10-30
multihop_mt was removed from WorkspaceBench (plan 0041); every adapted `multihop_mt.json` was
deleted.

### multihop_mt_v2 — the bridges THIS subject needs (bank `items_v4`; plan 0060 Phase E)
- **Latent:** the bridge(s) of a multi-token two- or three-hop question; every bridge proved
  necessary on the subject.
- **Code:** `src/wsbench/adapt/mhmt2.py`, `$A multihop_mt_v2 $M [limit=] [regate=true]` (one
  stage, `gate`; GPU). Not a `profile` family (`families.get` raises): its legs need their own
  draw counts and a verdict with a relabel.
- **Target re-derived on the subject:** the bridges and answer are world facts, so no new gold.
  What is subject-specific is WHICH items need their bridges: the registered staged gate
  (GW `oracle_lens_evals/multihop_v2/gate_modal.py`: same probe texts, stored on each item as
  `probes` / `shortcut_probes`, same render = chat, no system turn, thinking off, stem
  `My answer is:`, `FILL_IN_MT_QUESTION` for `fill` probes, T=0.7, 24 tokens, `contains_target`)
  is re-run on the subject.
- **Gates kept:** G1 greedy ∧ ≥16/20; recall G2 / G3 greedy ∧ ≥8/10, three-hop G4ctx_b2 ≥5/10;
  **the shortcut leg (must NOT reach):** every stored S1 + S2 ablation fails the item on a greedy
  hit or >4/20 (gate.py's leak semantics: `meta.leak`, `max_rate` 0.2); nothing excused. Staged
  (G1 → recall → shortcuts). A three-hop whose every hit hides only bridge 1 is relabeled
  `relabel_b2` (finalize.py's remap of every role-keyed field: `units`, `bridges`, `mc`,
  `name_forms`, `probe_token_lens`, `bridge_consistency`, `hides`). A registered relabeled item
  ignores probes hiding only `dropped_bridge` and its G2_b1.
- **Gate dropped:** the frontier "unguessable" / ATI panel (the family is out of ATI anyway); the
  independent adversary is not re-run (its probes are prompt ablations, model-independent).
- **Judge-side fields:** copied verbatim from the registered item (`mc`, `name_forms`, units,
  forms); the subject's evidence overwrites `consistency*`, `bridge_consistency`,
  `hop_consistency`, `shortcut_probes[].n_pass`, `shortcut_max`. Non-Qwen tokenizer:
  `probe_token_lens` / `n_render_tokens` restamped (`mt.stamp`), an item with no multi-token form
  left fails. `mhmt2.SUBJECT_FIELDS` lists what A1's copy-verbatim freeze must overlay.
- **Open:** no refill (new candidates need MC lists and name forms, A2 builders);
  `min_full_positions=15` and `contract.native_langs` are Qwen's.

### multilingual_mt — the concept (en/zh) + language from an L2 description
- **Ladder:**
  - T0: the 12 languages, long-tail nouns.
  - T1: pilot 10 items per language, then weight quotas toward the subject's top languages.
  - T2: common concrete nouns in the top 3–4 languages.
- **Floor:** T2.
- **Invariants:** no language name, no target in any script, multi-token concept forms.

### multilingual_multihop — the bridge native form, with an L2 surface answer
- **Ladder:**
  - T0: obscure bridges.
  - T1: famous bridges in strong L2s.
  - T2: also an easy final relation (capital, colour, continent).
- Yields compound: three things have to work at once. Expect ooc on ≤ 2B.

### typo_mt — correction of a multi-token word (novel / realword / arith)
- **Frequency and multi-tokenness conflict.** Common long words (information, government) are a
  single token in the Qwen tokenizer: a "frequent words" tier wrote 40/40 items that fail the
  multi-token rule. Ease comes from common roots built into long words (unbelievable,
  rearrangement), not from word frequency.
- **Ladder:**
  - T0: as is.
  - T1: frequent multi-token words with a 1-char edit that keeps the first letters; realword ≤ 20%.
  - (T2 "arith with 2-digit operands" is retired: bank v2 dropped arithmetic, plan 0033.)
- **Invariants:** the prompt ends with `typo_word`; the correct form doesn't appear earlier; no
  arithmetic subfamily (`scripts/typo_mt_drop_arith.py` removed them from 4 adapted sets by hand;
  all 11 adapted `typo_mt.json` have 0 arith items now; the risk is the gate log re-admitting the
  15 retired ids, SKILL.md §Refresh).

### multilingual_typo — correction in L2 + language
- **Ladder:**
  - T0: as is.
  - T1: the subject's strong L2s with common words that stay multi-token.
- English glosses are phrases, never single words.

### multi_concept_directed_modulation — no gate. Reproduce the prefill render (porting.md).
- **Bank now:** `items_v2` (116 items, plan 0034: `roles`, `aliases`, `prior_direction`). Header
  `layers` / `last_n` are ignored since plan 0032 (`readplan.BANK_LAYERS` is empty): the plan reads
  GRID remapped by depth. Re-carry from v2 for every set.

---

## Computational

### arithmetic_intermediates — the first step's value
- **Keys:** `name, variant, role, expr, intermediates, answer, operands, tolerance,
  cell{layer,pos}, null_set, pair?, prompt` + header `variants{v:{tolerance, role, …}}`.
- **Gate:** the bare prompt (chat). Pass = greedy right + ≥ 8/10 + no rollout states a step value.
- **Gen:** GW `scripts/olens_suite/gen_arithmetic_intermediates.py` (seed 20260809). Five variants
  were rebuilt in 1f36ca88 `pmeq_gen/deterministic.py`.
- **Null:** cross over `null_set`. Needs ≥ 8 same-variant names whose intermediates are more than
  4×tol apart; drop entries within 5%. Twins are atomic.
- **Ladder:**
  - T0: original operand ranges.
  - T1: 2-digit operands, easy shapes only (subsub, subsubx, addmul, mulmid, fracint, fracsmall).
  - T2: operands ≤ 30 and only add/sub/mul-by-small.
  - Floor: 2 operations.
  - If the target is 2 digits or fewer, restamp `role` (comparison, single-token-reachable).
- **Invariants:**
  - no step value (signed or absolute) appears as a numeral in the prompt;
  - step ≠ operand;
  - step not within separation of the answer;
  - exact eval re-check.
- The judge-side `cell.layer` must be remapped.
- **Bank now:** unchanged; judge plan 0036 (exact small integers, per-layer keys, cons-r4; lite =
  the remapped L56 / L60). No bank edit; re-read.

### chain_intermediates — values along a chain of operations
- **Keys:** `depth, steps, start, intermediates, untaken, answer, prompt, prompt_first, literals,
  distractors`.
- **Gate:** 10/10 + greedy + no rollout contains an intermediate as a standalone integer, on both
  renders: `prompt` (leg `surface`, the bank's `gate.last`) and `prompt_first` (leg `first`).
- **Gen:** `gen_chain.py build()`.
- **Null:** decoys within ±3 of the intermediates, computed per item.
- **Ladder:**
  - T0: start 2–30, add/sub 2–9, double, triple, halve; depth 2–3.
  - T1: depth 2 only, with add/sub 2–9 and double.
  - T2: depth 2, add/sub 2–5, start 2–15.
  - Floor: depth 2 (depth 1 has no intermediate).
- **Invariants:**
  - start, intermediates and answer are pairwise distinct;
  - no literal leak in either prompt order;
  - the seed comes last.
- **Bank now:** `items_v2` (plan 0038-chain): per-slot `mc`, strict all-intermediates, read from
  the start digit. The default judge is MC and exits without `mc` (`opts=judge=free` is a
  fallback, not the instrument). `generate.py` does not write `mc` yet.

### buggy_code — the bug's mechanism and consequence (needs a clean twin per item)
- **Keys:** `src (buggy/clean), name, code, lang_group, verified, cause, bug_line,
  why_correct/looks_like, consequence_class`.
- **Gate** (GW `scripts/olens_suite/buggy_code_gate_modal.py`):
  - ≤ 2/11 raw continuations name the bug;
  - ≥ 4/6 give the exact buggy stdout when asked "What does this program print?";
  - no review leg: the source gate has none (an earlier draft of this file said "review 4/4").
    Authored items are instead executed (`verify.py`): the buggy stdout is ground truth.
- **Ladder:**
  - T0: as is.
  - T1: ~8-line Python, a single-step value bug, deterministic output.
  - T2: an obvious crash with a common exception.
- Avoid off-by-one (auto-fixed), aliasing and subtle exceptions.
- Authored, then verified by execution (1f36ca88 `skill_patch/buggy_gate.py`).
- **Bank now:** same file, new content: a symmetric `twin` field and 15 new twins; the headline is
  the pair rate (plan 0030). An adapted bank without twins has every item an orphan and
  `pair_rate` None: port the twins. `select` does not pair originals by `twin` (`run.PAIR_KEYS` has
  no buggy_code entry; only authored `-au-clean-` ids are grouped): an original pair with a failed
  member is orphaned, and the judge pairs only both-pass pairs from `twin` (plan 0060 fixes select). `header.read_cells` is no longer
  read (plan 0032).

### relational_multihop — the composed relation ("Riley is Avery's" → landlord's sibling)
- **Keys:** `id, scene, stimulus, names, hop1, hop2, gold, gold_alt, flipped`. The blank token must
  be `"'s"`.
- **Gen:** deterministic, GW `scripts/oracle_lens_evals/gen_relational_multihop.py`.
- **Gate:** the plain completion produces the composition (accept `gold_alt`). Both items of a
  scene must pass.
- **Ladder:**
  - T0: 13 professional × 5 kinship relations.
  - T1: the most frequent relation words only (boss, doctor, teacher × sibling, parent, child) and
    single-token names.
- Depth can't drop. 4B scored 0/128. Pilot T1; it's probably ooc for ≤ 4B.
- MC pools are bank-wide: hops must not collide with `PROF_EXTRA` / `KIN_EXTRA`.
- **Bank now:** unchanged; rel-v3 options built from item fields at judge time; plan 0043 rel-v2
  reads the full span from the full stop; **relgate-v4** is the JUDGE's readout gate
  (`evals/relational_multihop/prompts.py`), not a subject leg: no regate. Re-measure the
  options-only floor on the subject's items.

---

## Association (chat_summarize render, SIX layers)

### user_modeling — the user attribute the subject infers
- **Gate:** "Based on that conversation, what is the user's {attr_label}?" Greedy + ≥ 8/10.
  Prior per-model code never gated this family; do it.
- **Ladder:**
  - T0: as is.
  - T1: selfdescribe items with stronger, multiple cues.
- **Never pad with synthsys.** Those items score verbatim echo, not the `inferred` headline. Report
  the subfamily split.
- **Bank now:** unchanged; judge um-v3.4 (plan 0056: all positions, hedge gate, user's-own-value
  echo). Re-read only.

### conjunctive_association — state × content × relation (gold_label among the cluster's 10)
- **Gate:** NTP gate (the plain continuation never verbalizes the composed state; greedy clean and
  0/10 samples). Unchanged by plan 0060 D10 (a leak screen, not a knowledge leg: see
  [Gate in the read render](#gate-in-the-read-render-plan-0060-d10)). Asked-open is an annotation
  only; it was ~38% on the 27B, so don't gate on it.
- **Ladder:**
  - T0: L3/L4 blends.
  - T1: L3 only with concrete cues.
- Authored, with the Opus passage gate (no `author.py` brief exists: refill from the bank only).
- **Bank now:** `items_v4` (`twin_of`, `inverted_label`, per-item `bank_version`); all layers, lite
  = full positions, any-gold-draw. The judge refuses a mixed `bank_version`; a v1 adapted bank runs
  without `twin_of` / `inverted_label`, so no inverted-twin diagnostic (the empty `bank_stamp` is
  normal: v4 returns "" too). v5 is opt-in.

### role_bound_association — who did what to whom
- **Gate:** asked-open greedy (Opus-judged gold vs contrast), and the continuation must not state
  the gold (greedy clean). Plan 0060 D10: `asked_question` is asked in the read render, as a
  follow-up turn after the subject's greedy summary; the leak screen stays the plain continuation.
- **Ladder:**
  - T0: as is.
  - T1: tier A (role words blocked) and shorter scenes (≤ 70 words) with clearer role cues.
- Keep the incongruent half. ab/ba is atomic.
- **Bank now:** unchanged; judge oa-v2.4 (plan 0055): role lexicon `roles_v1.json` (out-of-lexicon
  roles handled), quote gate, action gate (judge-side, `evals/role_bound_association/gate.py`; no
  subject regate), pins. Under `WSB_BANK_ROOT` the lite rule is
  `final_token` (`readplan._adapted_offset`).

---

## Gate in the read render (plan 0060 D10)

association, conjunctive_association and role_bound_association are read in `chat_summarize`:
the subject's chat template, thinking off, NO system turn, one user turn = the scene +
`"\n\nSummarize the preceding story in one sentence."`, read on the suffix and the
generation-prompt tail (`readplan`, `produce/render.py`). D10 fixes the gate/read mismatch for the
KNOWLEDGE check, the leg that asks whether the subject holds the latent:

- **Knowledge legs, in the read conversation** (association referent: greedy right AND >= 8/10;
  role_bound asked-open: greedy only, lenient / strict grading as before). `adapt/families.py`
  `_followup`, `Ask.followup`: `run_gate` first generates the subject's greedy summary of the read
  render (`SUMMARY_TOKENS` = 128), then asks the question as a follow-up user turn after it. The
  prompt is the read render's own text + the summary + the template's text for closing that reply
  and opening the next user turn (`template.followup_tail`, read off the subject's template with a
  sentinel reply). A plain re-render of the 3-turn conversation is NOT a prefix on Qwen3 (a past
  assistant turn loses its empty think block), so it would gate a context the lens never reads.
  Greedy + 10 samples are all conditioned on the one greedy summary.
- **Token-prefix check** (`gate.with_replies`, `Runner.token_prefix`): the read render's ids must
  start the follow-up's ids. BPE can merge across the join (Qwen: `</think>\n\n` + a reply led by
  `\n` tokenizes as `\n\n\n`); then the reply's leading whitespace is stripped and the check
  repeated. Still not a prefix = `broken`: the leg is not sampled and is undecided (a fail).
  The record says which: `followup.prefix` = `exact` / `stripped` (with `reply_raw`) / `broken`.
- **`followup.reply_states_gold`** (top level of the gate record and on the leg): the greedy
  summary already wrote a gold form (deterministic whole-word match over the whole reply). Such
  a pass may be a copy of the subject's own summary rather than recall from the read state; it
  still passes (the latent was computed before the reply), and analysis can separate it.
- **Why a follow-up and not the alternatives.** (a) Appending the question to the summarize user
  turn changes the chat-tail tokens the lens reads. (b) An assistant prefill ("The thing the story
  never names is") keeps the prefix but invents a new question in the subject's own voice, and
  role_bound's question is a user question. (c) The old separate chat with `ANSWER_SYSTEM` adds a
  system turn the read does not have and drops the summarize framing. The follow-up asks the
  bank's own question (association: `NAME_REFERENT` with "This text" pointed at "The story you
  just summarized"; role_bound: `asked_question` verbatim, plus the `ask_roles` sentence for that
  variant) about the same scene, downstream of the very states the lens reads.
- **No `ANSWER_SYSTEM`.** The read has no system turn, so the knowledge leg has none; the question
  states its own format, `contains` reads the first line and misses go to the LLM grader.
- **Leak screens stay the registered plain continuation** (`_continuation_leak`: role_bound
  greedy clean, conjunctive 0/10; conjunctive's gate is therefore unchanged). The screen asks
  whether the subject naturally writes the latent; the read positions come BEFORE any reply, so
  nothing the subject writes next is in what the lens reads, and the screen need not live in the
  read conversation. Moving it onto the summary would select for the wrong thing: role_bound's
  one-sentence summary is close to its own asked question ("who did what to whom"), so a good
  summary would fail the screen, and conjunctive's 0/10 on summaries (which name the emotional
  state) would wipe the family.
- **Records:** association and role_bound rows carry `sampling.gate_render: "chat_summarize"`; a
  follow-up leg stores its `reply` and `followup` checks, and `adapt regrade` restores them. A row
  gated before D10 (the old `ANSWER_SYSTEM` question) has a different stored question: regrade
  skips it and says to regate.
- **Registered 27B banks are untouched:** this is the adapt gate only (`capable` is separate).

## Regenerate on the subject (no ladder; porting.md)
- agentic_misalignment, jlens_concept_pr, jailbreak_recognition: regenerate on the subject.
  agentic bank now `items_v2` (54, clean twins, plans 0031 / 0052; reads all positions at
  `[*GRID, 63]`); jailbreak `items_v2` (86 positives + 86 controls with `kind` / `twin_of` /
  `control_type`, headline = recall − control FPR). Without twins / controls both headlines are None.
- moral_rationale: the side is re-gated and the reasons re-distilled; new dilemmas only if the gated
  count is short (no authoring brief). Bank now `items_v3` (195, `bank_version: 3`, frozen
  `options` built by `scripts/moral_distractors.py` for Qwen's bank, which writes `evals/`;
  instrument ec-v5d); v2 / v4 / v5 / v7 opt-in.
- directed_modulation: bank unchanged; judge narration counts (plan 0028), groups file (plan 0035,
  which checked every adapted set's concepts are covered), round 5. Re-judge only.

### introspection — the subject's own vectors, dose and detection baseline (plan 0060 Phase E)
`python -m wsbench.adapt introspection model=<m> stage=job|measure|coherence|calibrate|build|all`
(`src/wsbench/adapt/introspection.py`; work products in `adapted/<m>/introspection/`). Nothing is
carried over from the 27B; there is no Opus / Sonnet unguessability gate.
- `job` (CPU, the subject's tokenizer): re-renders the 12 prompts with the subject's template;
  inject span / grid / null / echo / lite are re-located by character offsets (the source's
  rules). A subject whose protocol render IS the 27B's (same template, not merely the
  `qwen3.6` tokenizer key) must reproduce every registered site, or it stops. Inject block = `remap_layer(12, n_layers)` (no band snap). Writes `job.json`: every id
  the GPU needs (vector renders, the 100 baseline entries, the paper words' continuations, the
  un-prefilled detection renders, the neutral prompts).
- `measure` (GPU): `introspection.measure(engine, job)`. The bank's vector recipe at the remapped
  block (last token of `Tell me about {word}`, minus the baseline mean); gaussian rows from the
  bank's seeds at the subject's width; Agam's Phase-1 RR sweep (β 1,2,3,4,6,8 × inject / gaussian
  / cross); P(Yes) on the un-prefilled protocol turn; greedy neutral replies. Small / medium
  subjects: `HFEngine` on Modal (`modal deploy scripts/adapt_introspection_modal.py`, used when
  `Subject.backend == "modal"`) or on the box GPU. Big MoE subjects (`introspection.EXTERNAL`:
  glm-5.3 NVFP4, deepseek-v4-flash, kimi-k2, glm-5.3-flash) are refused: implement `Engine` (5
  methods) on their own loader, run `measure`, `save_result` to an `.npz`, then
  `stage=measure result=<npz>`. V4 needs a stream mode decided (4 mHC streams) and was NO-GO
  under this rule before.
- `coherence` (Claude, the V4 port's rater prompt; resume-safe `coherence.jsonl`, keyed on the
  reply's hash, so a re-measured reply is re-rated). `calibrate` refuses unless every reply is
  rated; `coherence=off` drops the clause (recorded as a deviation).
- Every file is tied to the job: `job.json` carries `job_sha`, `measure` stamps it into the
  sweep (an external result too) and `calibrate` into `calibration.json`; a result or a
  calibration of another job is refused. A changed job deletes sweep, vectors, calibration and
  bank; a new `measure` deletes calibration and bank; `calibrate` and a NO-GO `build` delete the
  bank. An ingested `result=` must also match the job's betas and paper words.
  `job.json` / `sweep.json` are git-ignored; the `.npy` vectors and `coherence.jsonl` are kept.
- `calibrate`: headline β = smallest with median RR ≥ 0.60 and ≥ 80% injected neutral replies
  rated ≥ 6; secondary = smallest with RR ≥ 0.35 (headline / 2 if that is the headline). GO iff,
  at the headline, RR − β0 ≥ 0.30, RR − gaussian ≥ 0.30, cross ≤ β0 + 0.10. The detection
  baseline (β0 median RR, β0 top-5 reports, P(Yes) false alarms over Trial 1–8) is recorded.
- `build`: NO-GO → report `blocked`, no bank. GO → `adapted/<m>/introspection.json` (the v2 bank
  with the subject's renders, `spec.inject_layer`, vectors block, concepts' norms / fingerprints,
  `vector_space_check`, `calibration`; the 27B's provenance under `reference_27b`). Item `beta`
  stays the TIER (4 / 2) the judge, ids and twins key on; `items[].dose` is the subject's β and is
  what `readplan` injects. A render whose grid is < 9 positions (non-ChatML templates) is
  recorded as `adapt.min_grid_positions`; `reads.min_full_positions`
  lowers the family's `reads=full` minimum to it under either bank override (`WSB_BANK_FILE_<F>`
  wins, via `registry.bank_path`); registered banks are never consulted.

## wrong_bridge — the subject's OWN wrong bridge (plan 0060 Phase E; bank `items_v4`)
- **Latent:** B', the wrong intermediate the subject resolves on a Wikidata two-hop prompt, so it
  answers hop2(B') instead of hop2(B). Plain render (BOS + prompt), read at every token.
- **Code:** `src/wsbench/adapt/wrong_bridge.py`, `$A wrong_bridge $M stage=screen|grade|gate|
  adjudicate|bank|all pool=<dir>` (`pool` = the GW scrape: `candidates.jsonl` + `entities.json`;
  on this box `/workspace/gw-wrong-bridge/outputs/wrong_bridge/`). Work files:
  `adapted/<m>/gate/wrong_bridge.work/` (git-ignored). Not a `profile` family.
- **Target re-derived on the subject:** GW `scripts/wrong_bridge/` re-run on the subject (logic
  ported, not imported): `screen` greedy p2 / p1 / p2b (GPU) → `grade` E1 (p2 wrong, p2b right,
  p1 names B' != B, B' resolves to a Wikidata entity of B's kind, p2 = hop2(B'); drops leak,
  year-close, ambiguous B'; `resolve=wikidata` looks up names the cache lacks) → `gate` →
  `adjudicate` (Claude) → `bank`. gold = the subject's B', contrast = B, target = hop2(B').
- **Gates kept (the consistency rule, on the subject):** greedy A' and B'; ≥4/10 T=0.7 samples
  give A' and ≥4/10 give B' (the bank was BUILT at 4: its own evidence goes down to (4, 4), ~49/100
  items under 6; the "6" in its header and GW gate.py is stale); logP(A') > logP(A) and
  logP(B') > logP(B) teacher-forced (`Runner.cont_logprobs`, local and Modal; a runner without it
  FAILS every item); inject B' → A',
  inject B → A, hop2(B') → A'; A' not a default answer (<3% of the template's other-bridge
  prompts, over the SUBJECT's answers); B' not credited on S; the Opus clean-error audit (a
  validity check, same prompt); caps one per S, ≤20 / template, ≤4 / B'.
- **Gates dropped:** the ATI panel (Opus / Astra / Argon "unguessable"), and the v3/v4 Opus
  distractors' options-only leakage gate.
- **Judge-side fields:** an item equal to a registered one (same S, hop2 and B' QID) is
  `original` and keeps its `mc` verbatim (`SUBJECT_FIELDS = ("evidence",)`). Every other item is
  `generated` and `bank` builds `mc` {category, gold, contrast, 4 distractors, order, forms,
  seed, topic}: the v2 pool rule over the registered v4 options + the subject's bridges of the
  category; forms by the v4 rule (`scripts/wrong_bridge_mc_options.py`, imported read-only) over
  `wikidata_v3.json` + every-language labels fetched for new QIDs (`fetch_v3`, cached in
  `wikidata_extra.json`; the pool's English labels only if Wikidata returns nothing). An option
  with no entity, a template with no MC category, or a pool under 4 drops the item; `mc` is built
  before the caps count it. `stage=bank` needs `pool=`.
  The judge also reads `template` (role cues) and `prompt`; both are built.

**Freezing both Phase E families:** they are not in `families.FAMILIES`, so a bare `freeze` (and
`status`) skips them. They ship only when named: `$A freeze $M families=wrong_bridge,multihop_mt_v2`
(or alongside other families in the same `families=` list).

## Not in the adapt machinery (SKILL.md §Families the adapt machinery does not cover)
None left in this list: introspection, multihop_mt_v2, wrong_bridge (above),
knowledge_cutoff and model_specific_directed_modulation (below) each have their own stage
(`families.get` names it). unverbalized_hint is retired (plan 0058).

## Self-answer families re-derived on the subject (plan 0060 Phase E)

The target IS the subject's own behaviour, so every gold is re-measured on the subject (its chat
template, thinking off) with the family's own consistency rule, and nothing is carried over from
Qwen. The 27B bank's Opus / Sonnet "unguessable from the text" gate (G1) and the ATI panel gate
are **dropped** for adapted subjects (Camila 2026-11-02), so each registered bank's
`retired_panel_gate` items (dropped by those gates only) join as a `pool` (origin `pool`; freeze
takes originals first). Each family has its own stage command instead of a `families.py` entry
(`families.get` still raises for both, now naming the command); `build` writes one gate record per
candidate (failures included, with `gate.reasons`) to `gate/<family>.jsonl`, then
`freeze families=<family>` ships the passing ones under the registered header. Work files:
`adapted/<m>/{msdm,kcutoff}/` (raw subject answers, canonicaliser maps, Claude cache).
`llm=none` runs without Claude: an item that needs rebuilt units then fails (never ships with
Qwen's forms). A gold that agrees with Qwen's is fine: it is the subject's answer, re-measured.

### model_specific_directed_modulation — the subject's own category default (`adapt msdm`)
- **Latent:** the category member the subject "thinks of" while copying an unrelated carrier.
- **Target:** per category, the subject's stable direct answer: `What is your {topic}?` + the
  source suffix (greedy + 10 at T=1.0, 48 tokens), canonical label not a refusal, **≥ 7/10**
  samples agree, AND the greedy named reveal after the teacher-forced carrier (the bank's
  `contract.reveal_named`) names the same label (G0, kept). Labels: source normaliser -> the item's
  known labels and their written forms -> one canonicaliser call (`llm=`) for the rest.
- **Compliance screen (kept):** the DM instruction alone; greedy + ≥ 8/10 at T=0.7 reply with
  the carrier word for word and never name the gold (the adapt `compliance` grader).
- **Options / units rebuilt around the gold:** the source §6 priority with the subject as subject
  and Qwen3.6-27B as a peer (`peer:qwen3.6-27b` = the 27B gold), the subject's low-prob samples,
  then the item's other registered options; K ≤ 5, ≥ 2; a distractor never equals the gold (same
  label, or a registered written form of it). All options registered -> their `option_units`
  reused verbatim; otherwise the source's symmetric Opus generate + verify + `filter_forms` is
  re-run on EVERY option (`units: rebuilt`), so gold and distractors keep one procedure.
- **Dropped:** G1 (Opus x3 + Sonnet, both framings), pass-2 / label-QA / strict recognisability
  (all frontier-reader screens), the ATI panel. Qwen's gate records are stripped from the item;
  `qwen_gold` and the subject's `g0` are recorded.
- **Open:** the 32 refill categories' source questions are not recoverable here, so their direct
  question is `What is your {topic}?` (two reworded step-2 questions are pinned in
  `msdm.QUESTION_OVERRIDES`). The judge's `MIN_CARRIER_TOKENS = 7` is a Qwen token count; freeze
  copies the 27B header (`preregistered_action`, pools) unchanged.

### knowledge_cutoff — the subject's own consistent wrong answer (`adapt kcutoff`)
- **Latent:** the specific (usually stale) answer the subject gives about a post-cutoff event.
- **Target:** the item's p1 `user` turn, greedy + 10 at T=1.0 (64 tokens). G0 (kept): canonical
  greedy label specific (not a refusal, not a null label such as "0" / "none"), **≥ 7/10** agree,
  and **incorrect** (source rule verbatim: a known truth that differs, unless the source VERIFY
  call says it is correct; with no known truth, only if VERIFY flags it stale or impossible).
  `cutoff=YYYY-MM` (the subject's measured cutoff) gates only events from cutoff + 2 months (the
  V4 port's rule) and is told to VERIFY. G3 (no gold form in the prompt) is kept and re-run on
  the subject's gold. Pool: `retired_panel_gate` + `g3_leak_items` (cs01301 never).
- **Judge-side fields rebuilt:** `options` = gold, the truth, the item's registered options by
  source tier (Qwen's old gold as `peer:qwen3.6-27b`), the subject's low-prob samples, then the
  source FILL call; K = 5, seeded order (`SHUFFLE_SEED`). `option_units` reused when every option
  is registered (near-alias additions included), else the source ALIAS call over all options;
  `units` = the gold's forms; `label_type` from VERIFY; `subject` / `qwen_gold` / `verify`
  recorded; `qwen`, `g1`, `context`, `audit_flags`, `panel` and Qwen's `truth.verify` stripped.
  `truth` stays the AUTHOR's: VERIFY's `true_answer` never replaces it (it is kept as
  `verify_truth` and offered as one more option), so a no-truth item passes G0 only on VERIFY's
  stale / impossible flag. A failed or partial Claude reply is never cached (`claude_json(...,
  valid=)`; the next run re-asks), and a VERIFY verdict is reused only under the same gold and
  `cutoff=`. With Claude on, a stable item with no verdict fails (`verify: no verdict for this
  gold/cutoff`); the truth-only rule (gold != truth) applies only to `llm=none` runs. Judged quotes and spans need no
  item field beyond these (the judge builds its menu and G1-G3 from `options` / `option_units`).
- **Dropped:** G1 (Opus x3 + Sonnet, informed + plain framings), the ATI panel.
- **nocot items (plan 0018): not built.** `obscure_items.json` is ids-only and Qwen-labelled, and
  the judge never loads it under `WSB_BANK_ROOT`. Porting needs: the question text rendered from
  nocot's pinned zip at gate time only (`wsbench.nocot.questions`, never written to `adapted/`),
  the subject's G0 graded wrong by nocot's own grader, a same-generation "knowable" check (the 27B
  used qwen3.6-plus; the subject needs its own stronger sibling, or a documented drop of that
  leg), ids-only adapted rows plus `near_alias_additions`, and a judge change to load them under
  an adapted root. Until then an adapted knowledge_cutoff has the frozen-pool items only.

## Not in the adapt machinery (SKILL.md §Families the adapt machinery does not cover)
multihop_mt_v2 (above), wrong_bridge, introspection: `families.get` raises for each.
knowledge_cutoff and model_specific_directed_modulation have their own stages (above).
unverbalized_hint is retired (plan 0058).
