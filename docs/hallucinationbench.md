# HallucinationBench

[HallucinationBench](https://github.com/camila-blank/hallucination-bench) (HB) measures
hallucination; WorkspaceBench has no hallucination family of its own. Its index is the weighted share of a lens's claims that are
hallucinated (lower is better; index version `hindex-v8`, family weights main 9 / am_claims 3 /
am_situation 3 / sibling 1 / story 1 / overrefusal 1 / benign_roleplay 2). WSB vendors it frozen at one HB sha in
[`evals/hallucinationbench/`](../evals/hallucinationbench/README.md) and shows one number per (method,
layer): `full` where the method has every family, else `matched (no sibling)` (J-lens). `wsbench
report dir=D [hb_method=<name>]` appends it after the macro table, per judged layer plus the layer
mean for a multi-layer run. It is a separate number and never enters the WSB macro.
