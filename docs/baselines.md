# Baselines

Every judged pass rate is read against measured floors in [`evals/baselines/`](../evals/baselines/README.md):
**lucky guessing** (the repo judge shown only each family's option lists: blind, described and
seeded-uniform variants, five draws at temperature 1.0, stamped with the family's judge prompt
version) and **prompt-only** (Claude Opus 5.5 given the prompt text, no activation, judged
by each family's own summary instrument; protocol `po-opus-v1`, with the ids Opus refuses
re-asked on Sonnet 5.5, `po-opus-v1+sonnet55-fallback`; the stock-Qwen summary
floors are archived in `evals/baselines/archive/`).
`wsbench baseline` measures, `wsbench freeze` records, `wsbench report` draws the floors beside
each family, only while the floor's stamp matches the row's instrument (summary prompt_version,
digest settings and judge). Each prompt-only cell carries its reader and refusal label, e.g.
`0.892 [Opus 5.5 + Sonnet 5.5 fallback; Opus refused 19%, both 0/93; Opus alone 0.933]`; a floor
with more than 20% of its ids refused by every reader prints `not measurable (NN% refused)`.
A third floor, **logit lens L63** (`evals/baselines/logit_lens.json`, protocol
`logit-lens-L63-v1`): the bench's own `logit_lens` method read at the final layer (63 of 64, the
model's own next-token distribution) and judged by each family's summary instrument
(`layers=63`), drawn beside a registered-bank summary row that ran its instrument (never beside an adapted
subject's row); it never enters the macro
(full set 0.122 over 30 families, strict ATI 0.046
over 7; `evals/baselines/README.md`).

**Anti-text-inversion subset.** `anti_text_inversion=True` on `judge` / `run` scores each family
only on the items a reader of the prompt text (no activation) cannot answer. Four readers are
asked what the model is thinking about in the prompt, three draws each, every draw judged by the
family's own scorer: Qwen3.6-27B itself (thinking off) and the frontier group (Claude Opus 5.5,
or Sonnet 5.5 where Opus refuses, GPT-6 Astra and Gemini 4 Argon). An item is in the subset iff
EVERY reader fails every draw; if any one reader gets it in any draw, it is out
(gate `panel-v2`). It keeps a lens from being credited for reading the prompt. The subset is frozen in
`evals/baselines/anti_text_inversion.json` (`wsbench text-inversion stage=...` rebuilds it).
Families not gated or with no surviving item are skipped under the flag (never run on the full
bank); a family whose entry was gated under another judge instrument, or on another bank (the
entry's `bank_sha`), fails and has to be re-gated. Families with fewer than 20 surviving items are shown
but left out of the macro, and so is an ATI result gated under a retired rule (`stale ATI gate`).
The strict-ATI macro for Qwen3.6-27B is frozen (subset version
`ati-subset-v2`). It averages exactly eight families:
- introspection (124 items)
- moral_rationale (56)
- wrong_intermediate (42)
- knowledge_cutoff (39)
- conjunctive_association (26)
- model_specific_directed_modulation (25)
- model_multihop (22): always in; its entry is pinned from a family-specific panel run.
- poetry (16): an explicit exception to the 20-item minimum.

nyt_connections and hinted_cutoff are out. nyt_connections' survivors are model-specific
groupings. hinted_cutoff's hint is in both twins, so a subset score is noise; it stays in the full
set.
No directed-modulation family other than
model_specific_directed_modulation is in the subset (both others state the concept in the prompt).
`multihop_st` is not gated by design (one surviving item is not a
subset). `multihop` is excluded by design (the panel names every bridge
from the prompt, 0 of 70 survived).
Details and the per-family counts are in
[`evals/baselines/README.md`](../evals/baselines/README.md#anti-text-inversion-subset-anti_text_inversionjson).
