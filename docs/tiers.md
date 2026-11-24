# Tiers: core, full, fast

`run` and `plan` take one of three tiers. The tier picks the families; `families=a,b`
names them instead (a tier flag together with `families=` is a usage error).

| tier | flag | what runs | families | macro |
|---|---|---|---|---|
| `fast` | `--fast` | the frozen fast subset: a seeded random half of core without the two safety families, the strict ATI subset whole ([Fast subset](fast_subset.md)) | 18 | the fast macro |
| `core` | none (the default), or `--core` | the core families, each with its full registered bank and its unchanged instrument | 20 | the **core macro**: the mean over the core rows |
| `full` | `--full` (`all=True` is its synonym) | every family except a superseded or retired one | 33 | the macro over every row |

Core, by registry key: `agentic_misalignment`, `jailbreak_recognition`,
`arithmetic_intermediates`, `buggy_code`, `nyt_connections`, `moral_rationale`, `poetry`,
`introspection`, `multi_concept_directed_modulation`, `wrong_intermediate`,
`relational_multihop`, `role_bound_association`, `knowledge_cutoff`,
`model_specific_directed_modulation`, `model_multihop`, `chain_intermediates`, `hinted_cutoff`,
`conjunctive_association`, `user_modeling_hard`, `association_hard`
(`wsbench.tiers.CORE`; tagged `core` in [The evals](../README.md#the-evals) and in the `tier` column of
`wsbench list`). Core has 20 families today (the values of `conjunctive_association` sit below
its text floors, see its README). The two hard banks, `user_modeling_hard` and
`association_hard`, are core families by the owner's decision, and with core they joined the
fast subset, which was re-cut as `fast-v6`; the registered `user_modeling` and `association`
banks are in full only and in no core-half cut (`fast-v4` and later). `association_hard` is in core although the
prompt-only reader solves nearly every item of it (the owner's decision): its value compares
lenses with each other, not a lens with a reader of the text (its README). Neither hard
bank is adapted: under an adapted set (`WSB_BANK_ROOT=adapted/<m>`) both families have no
bank, so an adapted set's core macro covers at most 18 of the 20 core families.

When to use which: `fast` for quick iteration, `core` for the number a method is reported on,
`full` to check that a method does not regress on basic functionality. Core is a subset of full
as family sets, and a core family is judged exactly as in a full run (same items, read plan,
judge calls and cache), so a core run directory is a prefix of a full one. `wsbench report`
prints a `**core macro**` row (`N of 20 families`) under the macro row whenever the directory
holds a core family that is averaged, and a `core macro:` line; with a full run directory the
macro row is the full macro and the core row is the core one. The fast subset is its own scale
and reports no core macro.
