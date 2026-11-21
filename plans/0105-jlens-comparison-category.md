# 0105: the category `precision` becomes `jlens_comparison` ("J-lens comparison")

Camila, 2026-11-21:

> "rename precision category to 'j-lens comparison'"

## What

The eval category that holds one family, `jlens_concept_pr` (in no macro), changes its key and
title. The family key, its bank, prompts, stamp and its METRIC name (`precision`, with
`recall@10` in `extras`) do not change.

| | before | now |
|---|---|---|
| `registry.CATEGORIES` key (same, last, position) | `precision` | `jlens_comparison` |
| title (README heading, viewer / atlas section) | Precision | J-lens comparison |
| data directory | `evals/precision/jlens_concept_pr/` | `evals/jlens_comparison/jlens_concept_pr/` |
| package | `wsbench.evals.precision.jlens_concept_pr` | `wsbench.evals.jlens_comparison.jlens_concept_pr` |

## Why

"Precision" named the category after the family's metric; the category is about how a lens
compares with the J-lens at the same activation, and the owner wants it called that. After the
rename the word "precision" in code and prose always means the metric.

## Changes

```
src/wsbench/registry.py                      CATEGORIES entry; LEGACY_CATEGORIES; repo_path clause
src/wsbench/evals/jlens_comparison/          git mv of src/wsbench/evals/precision/ (7 files); group=
evals/jlens_comparison/                      git mv of evals/precision/ (3595 files, byte-identical)
src/wsbench/viewer/build.py                  GROUPS title (viewer_app and atlas read it)
atlas/site/app.js                            short label for the new title (the old one kept for old exports)
scripts/migrate_0101.py                      CATEGORY value; LATER_MOVES, used by `check`
scripts/manifest_0101_declare.py             CATEGORY_RENAMES rule (below)
tests/golden/manifest_0101_declared.json     the ledger entry
tests/                                       imports; the pinned category list / title / layout; new tests
README.md, CLAUDE.md, NOTICE.md, docs/, .claude/skills/adapt-bank/references/, plans/README.md
```

- The move is `git mv` of the two directories; a sha256 manifest of all 3595 data files before
  and after is identical. The one data-tree file edited afterwards is the family README (its
  own path in a heading), which is prose.
- Left alone on purpose: the metric name (`metric="precision"`, `by_layer[...]["precision"]`,
  `CHANCE_LABEL_UNMEASURED`, README prose "precision / recall@10"), the family title "J-lens
  concept precision", `atlas/build.py`'s family description, earlier plans, and the frozen
  records `tests/golden/manifest_0101_pre.json` (`"category": "precision"`) and
  `scripts/migrate_0101_applied.json` (the moves as `apply` made them).
- The skill scripts' Modal ignore pattern is `**/jlens_concept_pr/gen-*`, which does not name
  the category; nothing to change.
- No CLI key or filter takes a category name (`wsbench list` and `report json=True` only print
  it), so there is no alias to keep. The README gets a "Renamed in 0105" table.

## Stored paths

No stored string names the old directory. Searched: every tracked text file under `evals/`
(including `evals/jlens_comparison/jlens_concept_pr/manifest.json` and the `gen-*` trees),
`adapted/`, `tests/golden/`, `tests/fixtures/` for `evals/precision` / `evals.precision`. The
only hits were the family README (prose, edited) and `scripts/migrate_0101_applied.json` (a
record, kept). The "bank" strings of the adapted `report.json` files are all pre-0101 paths
(`evals/<family>/...`), which `registry.repo_path` already resolves through `family_root`, so
they follow the family wherever its category goes. No frozen bytes were rewritten.

For a file written outside the repository between plan 0101 and this plan,
`registry.LEGACY_CATEGORIES = {"precision": "jlens_comparison"}` gives `repo_path` one more
clause: `evals/<old category>/<family>/...` resolves into the family's directory when the
family sits under the category the old name maps to. Any other path is unchanged.

`scripts/migrate_0101.py check` replays the recorded moves of `apply`; `LATER_MOVES` composes
this plan's move after them. It reports the same 19 differences before and after this plan
(11 baseline / ATI JSON files and 8 new data files of plans 0099 / 0103 and the fast-v3 cut),
none about this family: the check has not been clean since those plans and is not a gate here.

## The manifest ledger (T1)

The manifest of plan 0101 records no path of a family (which is why 0101's own directory move
left every family's rows equal to the golden's). The rename therefore moves exactly ONE row of
`jlens_concept_pr`, `list.category` (`precision` -> `jlens_comparison`), the column `wsbench
list` prints. The stamp (`jlens-pr-v3+fw-v2+sense-v1`), bank (`manifest.json`, sha256
`af5b59c9...`), plan sha, file shas, seeds, options, tables, run and lens-store rows equal the
golden's.

T1's rule refuses a declaration without a stamp or bank bump, and `manifest_0101_declare.py`
refused this one. Bumping the stamp would be wrong (it would orphan every cached judge call for
a change no judge sees), and so would waiving `list` in general (it also holds the metric,
tier, judge model and item count). The minimal rule, in `verdict` / `declare`:

- `CATEGORY_RENAMES = {"precision": "jlens_comparison"}` (pinned equal to
  `registry.LEGACY_CATEGORIES` by a test) lists the renames.
- `category_renamed(golden rows, tree rows)` is the golden rows with `list.category` replaced
  when the table maps the golden's value to exactly the tree's value; otherwise the golden rows.
- A family whose rows differ from the golden's under the golden's own stamp and bank still
  fails ("instrument moved without a stamp or bank change") UNLESS its rows equal
  `category_renamed(...)`, in which case it needs a ledger entry (same triple, the tree's
  `rows_sha256`) like any declared change. The ledger hash then pins the family as usual.
- When such a family later declares a stamp change, the kept sections are compared with the
  renamed golden rows, so the category row is set aside and no other row is.

T1 is not weakened: an unlisted category value, the metric row, or any other row moving with or
without the rename fails as before (`test_t1_category_rename_is_the_only_bumpless_declaration`).

Entry (`python scripts/manifest_0101_declare.py jlens_concept_pr --plan 0105 --note '...'
--write`): `rows_sha256 34a1d54be1da5a729c5877c7424d4579a9b28a2038bb161d552be55aa8c53891`.
T1 names three families: `conjunctive_association` (0103), `nyt_connections` (0099) and
`jlens_concept_pr: category 'precision' -> 'jlens_comparison'`.

## Tests

- pinned values updated: `tests/test_tiers.py` (category list, family -> category),
  `tests/test_family_paths.py` (`LAYOUT`), `tests/test_readme.py` (heading).
- new: the title and `LEGACY_CATEGORIES` (`test_tiers`), the `repo_path` clause
  (`test_family_paths`), the T1 rule on synthetic manifests (`test_rename_0101`).

## Gates

`uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`, `uv run wsbench
list` (the family under `jlens_comparison`). Nothing to run in tmux: no pipeline changes.
