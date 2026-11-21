# Archived scripts

One-off scripts whose job is done. Each was moved here only after a search showed that no test,
source file, script or doc outside `plans/` mentions it. They still run from here (their repo-root
lookups were adjusted); the plans that introduced them name the old path under `scripts/`.

| script | was at | what it did |
|---|---|---|
| `enumeration_audit.py` | `scripts/` | Plan 0012 §4.2 audit: how many passing cells rest on a readout that lists 5+ same-type candidates. |
| `agentic_stage_c_compare.py` | `scripts/` | Plan 0012 §3.1 validation: agentic Stage C v1 against v2 on the same cached Stage B accounts. |
| `drop_frac_0083.py` | `scripts/` | Plan 0083 migration, already applied: dropped arithmetic's `frac` variant from the bank, ATI file, floors and adapted sets. |
| `conjunctive/composition_check.py` | `scripts/conjunctive/` | Plan 0049 C2 diagnostic: does a passing quote hold a credit word for every varied axis. |
| `poetry/freeze_bank.py` | `scripts/poetry/` | Plan 0038 §3: froze poetry bank v2 from the gate-passing pool. |
| `poetry/proxy_e0.py` | `scripts/poetry/` | Plan 0038 §5 pre-registration: the deterministic proxy of poetry's rule on cached readouts. |

Not archived although their names carry a round or version: `agentic_pool_v3..v7.py`,
`mc_leakage_r4.py`, `conjunctive/make_v2..v5_bank.py` and the other bank builders are imported by
tests or source, or are linked from a family README as the record of how a frozen bank was built.
