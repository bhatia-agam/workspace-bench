# Response to the qwen3.5-0.8b audit (AUDIT.md, 2026-10-21)

The audit is left as written. Applied 2026-10-21: every recommended drop is recorded in `report.json`
→ `drops`, and the set was re-frozen. agentic and hallucination drops were removed from those banks
directly. No refill: this is a small subject, and short families stay short and labelled.

- **Macro exclusions** set as recommended (8 families each; see `report.json` → `exclude_from_macro`).
- **Report entries** back-filled for hallucination, jailbreak_recognition and mcdm; stale status and
  notes corrected (2B arithmetic `freeze_notes`; 0.8B multilingual_multihop → `ooc`).
- **Skill fix:** the strict grader accepted part of a multi-word answer ("gigi" for "dokter gigi").
  `STRICT_FORM` now says a partial answer is wrong, and its cache key is versioned (`strict2`) so
  lenient verdicts aren't reused.
- **Skill fix (recurring in every audit):** moral items whose stored reason argues the other side
  are dropped here, and `moral.apply` now runs a Claude check of reason vs committed side
  (`_verify_sides`). It caught 7/7 of this audit's 2B flags with 0/10 false rejections.
- Patches the audit suggested (2B association `bf-newyear` gold, typo_mt "roller coaster" form)
  are not applied yet.
- **Floors:** `floors/floors.json` once tmux `small-floors` finishes.

## 2026-10-24 refill review ("can we really not get good questions for 0.8B?")
Re-read every absent/excluded family's gate log, then ran new waves (generation on Modal vLLM via
`ADAPT_BACKEND=modal`, same template, sampling and gate rule; grading local). Report:
`outputs/q08b_refill/REPORT.md`.
- **poetry 1 -> 100 (full, back in the macro).** Format fix, not a bar change: the 0.8B restates
  the couplet in chat and emits digits in plain. New opt-in `chat_prefill` render (assistant turn
  prefilled with line 1 + the line-2 stem; latent and read site unchanged; `gate_variant:
  chat_prefill`, read at `last_newline`). Grader fix: an echoed stub tail is skipped before the
  committed word is taken (gate.own_word). 36 originals + 64 authored common rhymes.
- **role_bound 0 -> 100 (full).** Authored scenes whose setting makes both roles explicit; originals
  fail because the 0.8B names the people, not the roles.
- **user_modeling 52 -> 100.** +48 selfdescribe (strong cues). 42 synthsys originals remain, so it
  stays excluded until an audit decides; read selfdescribe separately.
- **typo_mt 5 -> 29 (partial, excluded).** Lint-bound: common long words are single tokens.
- Confirmed out of capability (evidence in report.json notes): chain, arithmetic (one step only),
  relational (one hop), multihop_mt, multilingual_mt, multilingual_multihop, multilingual (1/21
  high-resource pilot), multilingual_typo, buggy_code (1/32 pilot, no atomic pair), moral (57 of
  its 61 consistent sides are no/false). brew left to the brew-tokenizer work.
- These new items were not independently audited; an audit pass on poetry / role_bound /
  user_modeling is the next step before they enter a published macro.
