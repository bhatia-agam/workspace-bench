# Porting to another model

Every bank was gated on Qwen3.6-27B: the model does the task before a lens is asked to read it.
`wsbench capable model=<openrouter-model>` re-runs that gate on any model — it asks each bank's
own question, grades the answers with the repo judge, and reports the share of items answered
right in at least 8 of 10 draws (10 of 10 for chain):

```
wsbench capable model=google/gemini-3.8-flash families=poetry,moral_rationale draws=10
```

Seven families are model-specific by construction and must be re-gated rather than re-scored:
**poetry**, whose scored latent is the rhyme word this model would commit to,
**moral_rationale**, whose per-item side and reasons are sampled from this model in the read
conversation,
**model_specific_directed_modulation**, whose gold is
this model's own favourite in the category, **knowledge_cutoff**, whose gold is this
model's stable wrong answer to a post-cutoff or obscure-fact question,
**hinted_cutoff**, whose twins are defined by which dated questions this model cannot answer without a correct hint and answers silently with it (its read positions are this model's own prompt-render tokens),
**model_multihop**, whose bridges are this model's own stable beliefs about an invented entity's country or a "current" holder (its read positions are this model's tokenizer indices), and
**nyt_connections**, whose labels are this model's own stable groupings and its names for them.
[AGENTS.md](../AGENTS.md) has the per-family table, the sanity checks to run before trusting a
number, and what has made an item harder so far.
