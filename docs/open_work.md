# Open work

Judge every arm with `wsbench run` against the frozen floors: the O-lens RL and SFT checkpoints,
NLA RL and SFT, J-lens, R-Lens, logit lens and template lens. Arithmetic_intermediates
(permutation), chain_intermediates (`null_shuffled` / any-cell permutation) and jlens_concept_pr
(derangement foil) carry an empirical null; the rest have none yet. The multi-token regex contract
matches authored forms only, so a paraphrase or a multi-phrase description cannot hit it;
`opts=judge=mc` is the semantic alternative.
