# Tiers: core, full, fast

`run` and `plan` take one of three tiers. The tier picks the families; `families=a,b`
names them instead (a tier flag together with `families=` is a usage error).

| tier | flag | what runs | families | macro |
|---|---|---|---|---|
| `fast` | `--fast` (`--fast-safety`) | the frozen fast subset ([Fast subset](fast_subset.md)) | 22 (24) | the fast macro |
| `core` | none (the default), or `--core` | the core families, each with its full registered bank and its unchanged instrument | 17 | the **core macro**: the mean over the core rows |
| `full` | `--full` (`all=True` is its synonym) | every family except a superseded or retired one | 31 | the macro over every row |

Core, by registry key: `agentic_misalignment`, `jailbreak_recognition`,
`arithmetic_intermediates`, `buggy_code`, `nyt_connections`, `moral_rationale`, `poetry`,
`introspection`, `multi_concept_directed_modulation`, `wrong_intermediate`,
`relational_multihop`, `role_bound_association`, `knowledge_cutoff`,
`model_specific_directed_modulation`, `model_multihop`, `chain_intermediates`, `hinted_cutoff`
(`wsbench.tiers.CORE`; tagged `core` in [The evals](../README.md#the-evals) and in the `tier` column of
`wsbench list`). Core has 17 families today. A hard user_modeling bank (new items, in
preparation) will join it as its 18th; the registered `user_modeling` bank is in full only.

When to use which: `fast` for quick iteration, `core` for the number a method is reported on,
`full` to check that a method does not regress on basic functionality. Core is a subset of full
as family sets, and a core family is judged exactly as in a full run (same items, read plan,
judge calls and cache), so a core run directory is a prefix of a full one. `wsbench report`
prints a `**core macro**` row (`N of 17 families`) under the macro row whenever the directory
holds a core family that is averaged, and a `core macro:` line; with a full run directory the
macro row is the full macro and the core row is the core one. The fast subset is its own scale
and reports no core macro.
