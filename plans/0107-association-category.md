# 0107: the family `association` moves from the category `basic` to `association`

Camila, 2026-11-21:

> "move basic association from basic to association in the repo"

## What

One family changes category. Its key, title, bank, prompts, stamp, read plan and tier do not
change.

| | before | now |
|---|---|---|
| `EvalSpec.group` / `wsbench list` category | `basic` | `association` |
| data directory | `evals/basic/association/` | `evals/association/association/` |
| package | `wsbench.evals.basic.association` | `wsbench.evals.association.association` |
| README entry, viewer / atlas section | Basic (adapted from the J-lens paper) | Association |

```
evals/association/association/               git mv of evals/basic/association/ (8 files)
  README.md                                  its own path in one sentence (prose)
  items.json  items_v2.json .. items_v5.json byte-identical
  distractor_screen_v2.json  lite_rule.json  byte-identical
src/wsbench/evals/association/association/   git mv of src/wsbench/evals/basic/association/
  __init__.py                                group="association"
  prompts.py                                 the README path in the module docstring
  judge.py                                   unchanged
src/wsbench/registry.py                      LEGACY_FAMILY_CATEGORIES; repo_path clause; _moved_hint
src/wsbench/viewer/build.py                  GROUPS: the family listed under "Association"
src/wsbench/baselines/lucky_guessing.py      import path
scripts/manifest_0101_declare.py             CATEGORY_MOVES rule (below)
scripts/migrate_0101.py                      LATER_MOVES; path_today(root=)
scripts/{association_distractors,mc_leakage_r4,common_confusers_r5}.py   path strings
tests/golden/manifest_0101_declared.json     the ledger entry
tests/                                       imports, path / category pins, new tests
plans/0107-association-category.md, plans/README.md
README.md, CLAUDE.md, docs/adapt_judge_inputs.md, evals/baselines/README.md, .claude/skills/
```

## Invariants

- **Location and category only. No instrument changes**, for `association` or any other
  family: stamp (`assoc-mc-2026-11-01-v3+gate-a2+bank-v5`), bank (`items_v5.json`, sha256
  `c95f68d4...`), prompts, `plan_sha`, call keys and cache fingerprints, lucky-guessing and
  prompt-only floors, the ATI entry, the fast subsets (the family is in none) are what they
  were. A sha256 listing of every file under `evals/` before and after differs only in the 8
  moved paths and the family README's one edited sentence.
- **The frozen manifest golden `tests/golden/manifest_0101_pre.json` is not rewritten**, nor is
  `scripts/manifest_0101.py`; T1 still pins both shas. The move is declared in the ledger.
- **Tier membership does not change**: `association` is in `full`, not in `core`, not in a fast
  subset. `tiers.CORE` and the `evals/fast/*.json` files are untouched.
- **No reported number changes.** There is no per-category score: `results.macro`,
  `core_macro` and the fast macro average families, and the family is in the same ones as
  before. The category is a `wsbench list` / `report json=True` column, a README heading and a
  viewer section. Family counts by category become basic 13 (was 14), association 3 (was 2);
  the README's "Moved in 0107" note says so for anyone who groups by category downstream.
- Historical records keep their paths: earlier plans, `scripts/migrate_0101_applied.json`,
  and `scripts/migrate_0101.py`'s `CATEGORY` (below).

## Paths: `association` is a family key, a category, and a pre-0101 directory

After the move the family's directory is `evals/association/association/`. Nothing builds that
path by hand: `registry._layout` reads the package tree, and `family_rel` / `family_root` /
`family_module` / `resource_path` follow it (so `EvalSpec.bank`, the README link check and the
adapt tools moved with the directory). `_layout` already handles a family package named like its
category package (it reads exactly two levels).

`registry.repo_path` (stored path strings only) keeps its order, now documented as a numbered
list, and gains one clause:

1. today's layout as written: `evals/<category>/<family>/...` when the family sits in that
   category. So `evals/association/association/...`, `evals/association/user_modeling/...` and
   `evals/association/conjunctive_association/...` are never read as the pre-0101 family
   directory plus a subdirectory. This clause was first before and stays first.
2. a former category key (`LEGACY_CATEGORIES`, 0105), **and the category a family left**
   (`LEGACY_FAMILY_CATEGORIES = {"association": "basic"}`, this plan):
   `evals/basic/association/...` -> `evals/association/association/...`. Plan 0105 gave the old
   category name this courtesy for files written outside the repository between 0101 and the
   rename; the same reason holds here (`adapt freeze` writes the bank's repo-relative path into
   a set's `report.json`, so a set frozen between 0101 and today carries
   `evals/basic/association/items_v5.json`). No such string is tracked in the repo today
   (searched `adapted/`, `evals/`, `tests/golden/`, `tests/fixtures/`, `examples/`). The clause
   is per family: `evals/basic/<any other family>/...` is unchanged.
3. `evals/baselines|fast|hallucinationbench/...` as written.
4. the pre-0101 reading: `evals/association/items_v5.json` ->
   `evals/association/association/items_v5.json` (it was `evals/basic/association/...`; the
   F8 pin in `tests/test_family_paths.py` is updated). A bare `evals/association` keeps the
   pre-0101 reading too (the family's directory), as before.

`registry._moved_hint` (the message for a missing `WSB_BANK_FILE_*` file) names the new place
for an `evals/basic/association/...` value.

## `scripts/migrate_0101.py`

Its tables record the migration `apply` made, and `tests/test_migrate_0101.py` replays that
migration on a toy tree and asserts `evals/basic/association/...` (R1/R2 rewrites, "moved under
`basic` exactly once"). So **`CATEGORY["association"]` stays `"basic"`** (0105 could edit the
value in place because no replay test names `precision`; here that would rewrite the tests of
the migration itself). Instead:

- `LATER_MOVES` gains the two directory moves, which `check` composes onto the recorded moves.
- `path_today(path, mv, root)` applies a later move only to a file that is no longer at its
  path of the apply commit. Without this a replayed `apply` + `check` (a tree still in the
  applied layout) would look for the file under `association/association`.
- `test_tables_agree_with_the_registry_and_the_plan` compares the registry with
  `{**mig.CATEGORY, **moved_since}`, `moved_since = {"association": "association"}`, and pins
  that table against `LEGACY_FAMILY_CATEGORIES` and `LATER_MOVES`.

`migrate_0101.py check` reports the same 19 differences as on main (those of plans 0099 / 0103
and the fast-v3 cut), none about this family.

## The manifest ledger (T1)

As in 0105 the manifest holds no family path, so exactly one row moves:
`families.association.list.category`, `basic` -> `association` (verified by diffing the manifest
of main against this tree's: one path). T1 refuses a change under the golden's own stamp and
bank, and a stamp bump would orphan every cached judge call for a change no judge sees.

`CATEGORY_RENAMES` cannot express this (`basic` is still the category of 13 families), so the
ledger gets a per-family rule beside it, in `category_renamed(g, c, fam)`:

- `CATEGORY_MOVES = {"association": ("basic", "association")}`: family (manifest key) ->
  (category in the golden, category today). A test pins it against
  `registry.LEGACY_FAMILY_CATEGORIES` and the live layout.
- The golden's `list.category` is replaced for the comparison only when the family is the
  listed one and the (golden, tree) values are exactly the listed pair. `verdict` and `declare`
  pass the family; everything else in them is 0105's path: a ledger entry with the golden's own
  triple and the tree's `rows_sha256` is required, every other row must equal the golden's, and
  a later stamp change of the family sets aside that one row.

Not waived (`test_t1_category_move_waives_one_row_of_one_family`): another family of `basic`
showing `association`, the listed family under any other category or the reverse move, any
other row (`plan`, `stamps`, `files`, `run`, `list.metric`, `list.tier`) moving with it.

Entry (`python scripts/manifest_0101_declare.py association --plan 0107 --note '...' --write`):
`rows_sha256 cf73f3e785022d474020d0aae4cc63e78edf01dcace5d95e10fe965fc8826543`.

## Tests

- pinned values updated, all category / path pins of this one family: `tests/test_tiers.py`
  (`CATEGORY`), `tests/test_family_paths.py` (`LAYOUT`, F8's expected path and its as-written
  path), `tests/test_basic_association.py` (`SPEC.group`), `tests/test_adapt.py` (the bank path
  `adapt freeze` records), `tests/test_migrate_0101.py` (the layout comparison), the literal
  bank paths / imports in the association tests and `tests/test_common_confusers_r5.py`.
- new: the doubled segment and the `repo_path` cases (`test_family_paths`), the
  `LEGACY_FAMILY_CATEGORIES` pin (`test_tiers`), the T1 move rule on the real ledger entry and
  on synthetic manifests (`test_rename_0101`), `LATER_MOVES` / `path_today` (`test_migrate_0101`).

## Gates

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`; `uv run wsbench list`
(the family under `association`); `wsbench plan families=association limit=2` and
`reads.plan_sha("association")` equal to main's. Nothing to run in tmux: no pipeline changes.
