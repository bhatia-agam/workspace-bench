# Plan 0120: HallucinationBench moves into this repository (stage A: the code and banks, unchanged; stages B–E outlined)

Camila, 2026-11-27: HallucinationBench (HB, `camila-blank/hallucination-bench`, `main` @
`ecfae41`, index `hindex-v8`) becomes part of this repository so that it can use the run
infrastructure built here (stored activations, `wsbench read`, the Modal launcher, the
cross-process judge pacers, one judge process per family). A one-time capture of HB's items
into the stored-activation dataset is approved. Changes to `benign_roleplay` wait for the
jailbreak changes she is making here. A fast subset of HB is undecided (§7).

Base: `origin/main` @ 401e7bda. Worktree `/root/tmp/wsb-0120`, branch
`camila/0120-hb-into-wsb`. HB source checkout: `/root/tmp/hb-v8-final` (`ecfae41`). Frozen v8
judge outputs: `/dev/shm/hb-v8-full/v8-full` (volatile; archive `/workspace/hb-v8-full`).

This plan supersedes plan 0040's decision "the hallucination benchmark lives in another
repository". Plan 0040's "the index is ingested as a vendored file" is retained through stages
A–D and superseded only when `hindex-v9` is built here (§6). It **retains** these invariants of
plans 0040 and 0080, restated here because the code that encodes them is touched:

- **I1. The HB index never enters any WSB macro, tier or fast subset.** No HB eval is in
  `tiers.CORE`, in `evals/fast/`, in the ATI subset, in the floors, or in `results.macro`. The
  report block stays a separate section with `in_macro: false`.
- **I2. One number per (method, layer)**, `full` where the method has every family, else
  `matched (no sibling)`; joint rows are kept apart.
- **I3. An arm is mapped to an HB method only when its checkpoint is verified identical**
  (`methods.json`), never by alias.
- **I4. Adapted sets carry no hallucination family.** `REMOVED_FAMILIES["hallucination"]`
  stays; the key `hallucination` is not reused.
- **I5 (HB's own rule). A change to any HB prompt, bank, scoring rule or weight is a new index
  version.** Stages A and B change none; the frozen `hindex-v8` numbers must come out the same.

## 0. Why a sub-package and not six ordinary families

A WSB family is one pass rate over items, in summary mode, with floors, ATI, lucky-guessing and
capable tables. An HB family is not: its units are claims (character-weighted leaf shares),
situation cells, refusal lines, probe-validated units and prompts; every method has per-layer
rows and a joint 11-layer row; the index is a weighted macro (Σ 20, `matched` Σ 19) with its
own cluster bootstraps, a hashed manifest and persistent-failure exclusions. Registering the
evals through `EvalSpec` alone would need about a dozen table and count-pin edits each (the
list in plan 0108 §"sites") and a `digest.NATIVE_ONLY` entry each (that set is pinned to
exactly `{jlens_concept_pr}`), for instruments that share none of that machinery.

So: HB's code is a sub-package `wsbench.hb` with its own command `wsbench hb …` (the precedent
is `wsbench viewer …`, dispatched in `cli.main` before `COMMANDS`). What it takes from WSB is
the **run infrastructure**, in stage B: the judge transport and pacers, and the read plan /
capture / store / `read` path. It registers no `EvalSpec` in stage A.

## 1. Stage A (this PR): move the code, banks and tests; no behaviour change

Critique rounds 1 and 2 (2026-11-27) are folded in: test layout, the WSB scan tests, `final`'s
persistent-failures path, the gates and their HB-side baseline, the script list, the rewrite
scope, `DATA`, the pinned-checkout environment.

### 1.1 What moves where

| HB (`ecfae41`) | here |
|---|---|
| `src/hallucination_bench/**` (81 files, 30,009 lines) | `src/wsbench/hb/**`, same relative layout |
| `data/<eval>/**` (38 MB) | `evals/hallucinationbench/<eval>/**` (`wsbench_chat`, `wsbench_chat_x3`, `story`, `agentic_misalignment`, `sibling_probe`, `overrefusal`, `benign_roleplay`, `calibration`), **bytes unchanged, never passed through the rewrite** |
| `data/index/{v8_manifest.json,v8_persistent_failures.json,methods.json}` | `evals/hallucinationbench/index/`, bytes unchanged (manifest sha256 `3b0a3e9d…` stays). HB's `methods.json` (index method → arm per family) keeps its name; `evals/hallucinationbench/README.md` says in one line that it is the opposite direction of the existing `evals/hallucinationbench/methods.json` (readouts-root basename → index method), which stays |
| `tests/**` (64 test files, about 649 tests, fixtures 652 KB, `conftest.py`, `index_helpers.py`, `v7_rebuild_fixture.py`) | `tests/hb/**` as a **package** (`tests/hb/__init__.py`, empty) |
| every tracked `scripts/**/*.py` (23 files; tests load some by `spec_from_file_location`, and scripts import each other) | `scripts/hb/**`, same relative layout. No `.sh` file is moved |
| `docs/results/*` (three files), HB `README.md` | `docs/hb/results/`, `docs/hb/README.md` |
| HB `CLAUDE.md` | `src/wsbench/hb/CLAUDE.md` (paths rewritten by hand; it ships in the wheel, which is intended: it is the package's runbook) |
| `plans/00NN-*.md` (20 files) | `plans/hb/` unchanged (history; HB's numbers collide with WSB's) |
| `hbench` console script | `wsbench hb <args>` = `wsbench.hb.cli.main(args)`; the argparse CLI is unchanged except `prog="wsbench hb"` |

Not moved: `plots/`, `outputs/`, HB's `uv.lock`, the nine `.sh` drivers and every untracked
file (they stay in the archived HB repository, stage E).

Kept as they are here: `evals/hallucinationbench/{index.json,methods.json}`,
`src/wsbench/hbindex.py`, `scripts/vendor_hb_index.py` (`HB_SHA` unchanged). The vendored
`index.json` remains the index of record for `hindex-v8`; *it is still written only by
`vendor_hb_index.py`, sha-pinned, and an arm is never aliased (I3)*, and
`evals/hallucinationbench/README.md` and the root `CLAUDE.md` keep saying so. **The viewer is
not touched in stage A**: `viewer/ingest/hb.py` and `viewer/meta.load_hb` keep reading an HB
repository checkout given as `hb_repo=` (its bank paths and README); pointing them at this
checkout is stage E.

### 1.2 The transform, and the only edits allowed

The import is made by a deterministic script committed in the PR,
`scripts/hb/import_from_hb.py <hb checkout> [--check]`: it refuses a checkout whose `HEAD` is
not `ecfae41` or whose tracked files are modified (`git status --porcelain
--untracked-files=no` non-empty), runs its format and import-sort steps with this repository's
locked ruff, copies **`git ls-files` only** (the checkout on the box has untracked scripts and
plots; they are not imported) for the trees of §1.1, and applies the mechanical rewrites
M1–M5. `--check` re-runs it and diffs the result against the tree in the PR over the `*.py`
files that came from HB; **that residual diff must be exactly the named hand edits H1–H7 and
H9**, and is pasted into the PR. Files that did not come from HB's `*.py` are outside the
check: `src/wsbench/hb/CLAUDE.md` (H8, rewritten by hand), `tests/hb/__init__.py`,
`tests/hb/test_stage_a.py` (below), the script itself. That is what makes "unchanged
otherwise" checkable.

Mechanical rewrites, applied **only to `*.py` under `src/wsbench/hb`, `tests/hb`,
`scripts/hb`** (never to `evals/hallucinationbench/**`, fixtures, `.json`, `.md` or plans):

- **M1.** Import statements, dotted module strings and dotted references in docstrings and
  comments: `hallucination_bench` → `wsbench.hb` where it is the package (`import`, `from …
  import`, `"hallucination_bench.x.y"` strings as in `evals/__init__.py`, `cli.EVAL_CLIS`, the
  tests that compare them, `:class:` references). Help and error texts that mention `data/…`
  paths (`cli.py:522,809`, `wsbench_chat/bank.py:93`) stay as written. Not rewritten: `global_workspace.judges.hallucination_bench` (another
  repository's module, `wsbench_chat/expand.py`), and **the string `hbench` anywhere** (it is
  in index notes and error prefixes that reach output files; only `prog=` changes, H1).
- **M2.** Test-helper imports, because `tests/hb` is a package (WSB's `tests/` has no
  `__init__.py`, 77 WSB tests do `from conftest import …`, and `test_cache.py` /
  `test_readouts.py` exist in both suites): `from conftest import`, `from index_helpers
  import`, `from v7_rebuild_fixture import`, `from test_<x> import` → the same with a leading
  dot (`from .conftest import …`), at any indentation (about 30 are inside functions). `pytest tests/hb`, `pytest tests/test_cache.py` and a bare
  `pytest -q` must all collect.
- **M3.** Repository-relative locations: the one definition `REPO_ROOT` in
  `src/wsbench/hb/__init__.py` becomes `parents[3]`, and **the existing constant `DATA` keeps
  its name** with its one definition changed to `REPO_ROOT / "evals" / "hallucinationbench"`
  (about 30 modules and a test import `DATA`; none of those imports changes). A hand-built data
  path elsewhere (`parents[n] / "data"`, `REPO / "data/wsbench_chat/items.json"` in
  `main_x3/build_seeds.py:123`, the local `DATA` of `um_ladder.py:36`) is re-pointed at the same
  directory; `scripts` → `scripts/hb`, `tests` → `tests/hb`,
  `"src" / "hallucination_bench"` → `"src" / "wsbench" / "hb"`, and the repo-root depth of
  each moved test and script (`parents[1]` → `parents[2]` and so on). The implementer
  enumerates every `parents[`, `REPO`, `"data"`, `"scripts"`, `"tests"`, `"src"` site in the
  three trees (the critique lists `test_am_v8.py:35`, `test_v7_rebuild_identity.py:16-19`,
  `test_final_olens_arm.py:13`, `test_sibling_probe.py:20`, `test_am_audit.py:16`,
  `test_am_verify.py:27`, `test_persistent_failures_script.py:16`,
  `test_benign_roleplay.py:16,589`, `um_ladder.py:35-36,672`, `um_probes_modal.py:31-33`,
  `scripts/am_audit.py:34-35`, `scripts/main_x3/{build_bank,joint_bundle,seed_summaries,build_seeds,merge_readouts}.py`
  with their `sys.path.insert(REPO / "src")`, `main_x3/gen_modal.py:145`,
  `scripts/overrefusal/probe_modal.py:44-47`, `test_am_v8.py:396`) and the script handles each
  by an explicit table, not a blanket regex. Two special cases: the **container-side** path
  in `scripts/overrefusal/probe_modal.py:36-48`, `"/root/src/hallucination_bench"`, becomes
  `"/root/src/wsbench/hb"` (the container imports `wsbench.hb…` after M1; `wsbench` is a
  namespace package there because only the `hb` directory is mounted: never mount
  `src/wsbench` whole); and script defaults of the form `REPO_ROOT / "outputs" / …`
  (`um_lexicons.py:29`, `gen_items.py:55`, `um_ladder.py:35`) are left repository-root-relative
  on purpose (this repository's gitignored `outputs/`).
- **M4.** `ruff format` on the three trees after M1–M3 (shorter module names re-join wrapped
  lines); the format diff may touch only statements that contain a rewritten token. HB's tree
  was formatted with ruff 0.17.0 and this repository locks 0.16.7: G0(d) measures whether the
  locked ruff reformats untouched HB statements. If it does, those files get a separate,
  format-only step **M4b** (listed per file in the PR; no string value changes), and ruff is
  not bumped repository-wide.
- **M5.** `ruff check --select I --fix` on the three trees (M2's relative imports move to the
  end of their import block); it may touch only import blocks that hold a rewritten import.

Hand edits (each one named in the PR):

- **H1.** `cli.build_parser`: `prog="wsbench hb"`.
- **H2.** `final.load_persistent`: the manifest stores `"data/index/v8_persistent_failures.json"`
  relative to the working directory and must stay byte-identical. The loader tries
  `base / path` first, exactly as now (tests use a temp file), and only when that file does not
  exist maps a leading `data/` onto `DATA`. `index.json` keeps the manifest's path string
  verbatim.
- **H3.** `evals/overrefusal/cli.py:18`: the literal `"/workspace/hb-readouts-overrefusal-v2"`
  becomes a plain string constant `OR_READOUTS_V2_DEFAULT` in `hb/paths.py` (also in its
  `__all__`); `_readouts_root` keeps its order and its call-time read of `HBENCH_OR_READOUTS`
  (`tests/test_paths.py` skips files named `paths.py`). **`hb/paths.py` is otherwise
  byte-identical** apart from M1 in its docstring: every `HBENCH_*` variable and default stays, and
  the `HBENCH_*` variables read elsewhere (`HBENCH_X3_BANK`, `HBENCH_AM_ITEMS`,
  `HBENCH_STORY_ITEMS`, `HBENCH_WSBENCH_CHAT_ITEMS`, `HBENCH_AM_INTENT_OVERRIDES`,
  `HBENCH_OR_READOUTS`, `HBENCH_SAFETY_*`) keep their names and meaning.
- **H4.** `benign_roleplay/wsb.py` gets one helper `pinned_env()`: the caller's environment
  without `PYTHONPATH`, `UV_PROJECT_ENVIRONMENT` and every `WSB_*` / `WSBENCH_*` variable (which
  includes the `WSB_BANK_FILE_*` it already strips). The module's two subprocess sites that
  pass an environment (`run_calls`, `bank_path`; `_git` passes none) use it, **and `run_calls`
  keeps the order `{**pinned_env(), **c.env}`, so the `WSB_BANK_FILE_JAILBREAK_RECOGNITION` it
  sets for the HB-only bank is applied after the strip**,
  and so does the test's own pinned-checkout subprocess environment
  (`tests/hb/test_benign_roleplay.py:104-140`). Reason: the caller is now a WSB process, and an inherited
  `PYTHONPATH=<this checkout>/src` would make the subprocess in the checkout pinned to
  `0b18789` import this checkout's `jb-v4` code while `check_pin` still passes. **The family
  keeps judging in that separate pinned checkout (`$HBENCH_WSBENCH_PUB`), never with this
  checkout's `jailbreak_recognition`**; no benign-role-play judging is run in stage A; stage C
  replaces the mechanism. `test_no_wsb_logic_in_hb` moves unchanged (it bans `wsb_*` file
  names, nine function names and imports of `anthropic` / `openai` / `*.llm` in that package).
- **H5.** `tests/hb/conftest.py`: `os.environ.setdefault("HF_HUB_OFFLINE", "1")` at import
  (three tests call `AutoTokenizer.from_pretrained` and skip on failure; WSB's rule is no
  network in tests).
- **H6.** `tests/hb/test_sibling_probe.py:276` inserts `$HBENCH_WSBENCH_PUB/src` and imports
  `wsbench.produce.render`; inside this repository `wsbench` is already imported, so the test
  would silently compare against this checkout. **It always skips here**, with the reason
  "compares with a pinned WorkspaceBench checkout; cannot be imported beside this one"; it is
  one named G3 difference.
- **H7.** `tests/hb/test_benign_roleplay.py:589` reads HB's README: it points at
  `docs/hb/README.md`, whose asserted sentences are not edited.
- **H8.** `src/wsbench/hb/CLAUDE.md`: HB's runbook with its paths and command names rewritten
  by hand, plus three notes: H4's hazard; that `git_sha` in an index written by `wsbench hb
  final` is now this repository's commit (so `vendor_hb_index.py`, which accepts only `HB_SHA`,
  cannot vendor it: stage E); and that the vendored v8 file is the record (I3).
- **H9.** For tests that G0(b) shows to need box-only paths: a `skipif` on the missing path or
  variable (never an unconditional skip), each listed in the PR with its reason. On the box
  every such test keeps its G0(a) outcome; in CI it skips instead of failing.

New file, not from HB: `tests/hb/test_stage_a.py`: `prog` is `wsbench hb` (H1);
`load_persistent` prefers `base / path` and falls back to `DATA` for a `data/` path (H2);
`pinned_env()` drops `PYTHONPATH`, `UV_PROJECT_ENVIRONMENT`, `WSB_*`, `WSBENCH_*` and keeps the
rest (H4); `DATA` resolves to `evals/hallucinationbench` and holds the eight bank directories.

Not done in stage A: removing `from __future__ import annotations` (three package files, two
of them shipped standalone into a Modal image, and six scripts keep it), lint-driven changes,
docstring trims, renames. **The claim-map `VERSIONS` objects, `taxonomy_v2`, `units.py`, the
`cverify-v1` builder, the AM detector's canonical lines, `cache.py`'s row format
(`fingerprint`, not `fp`), the fingerprint tuple `(prompt version, model, effort, system,
user)` and every cache key string (`summ:…`, `:M`, `:CV:…`, …) are untouched (I5)**; the hash
pins (`test_registry_pins.py`, `test_v7_rebuild_identity.py`, `test_continuation_verifier.py`)
pass unmodified apart from M1–M3.

### 1.3 Repository rules for the imported tree

**WSB tests that scan the tree.** Each gets a scope exemption for the imported tree and
nothing else; *no assertion of a pre-existing WSB test changes value, and no family count,
tier list, category list, manifest-ledger entry or golden file moves (I1, I4)*:

| test | trips on | change |
|---|---|---|
| `test_no_token_interpreter.py::test_no_module_imports_interp` | `INTERP_*` names, `.summarize` attributes, `"summ:"` cache-key strings in `hb/` (cache keys must not be renamed, I5) | skip files under `src/wsbench/hb/` |
| `test_bank_versions.py::test_no_hardcoded_items_json` | about 13 `…items.json` literals in `hb/evals/*/bank.py`, `overrefusal/data.py` | skip files under `src/wsbench/hb/` |
| `test_family_paths.py::test_no_code_builds_a_family_path_by_hand` | `benign_roleplay/bank.py:27` (`evals/jailbreak_recognition/build_v2.json`, a path inside the pinned checkout, kept as written), `sibling_probe/bank.py:37` | those two files added to its `EXEMPT` with the reason |
| `test_family_paths.py::test_every_written_evals_path_exists` | `tests/hb/test_benign_roleplay.py:44` (`evals/jailbreak_recognition/items_v2.json`, the pinned checkout's pre-0101 layout) | skip `tests/hb/` in the walk (those paths are another checkout's); `KNOWN_MISSING` is not grown |
| `test_paths.py::test_no_box_path_literal_in_src` | `overrefusal/cli.py:18` | none (H3 removes the literal) |

The implementer runs the whole WSB suite and treats any further scan test that trips as the
same case: a path-scope exemption with a one-line reason, listed in the PR; a change to what a
test asserts about WSB's own tree is a stop-and-report.

**CLI.** `cli.main` dispatches `hb` before `COMMANDS`, as it does `viewer`, and the usage text
gains one `hb` line. *The `hb` branch
registers nothing and does not call `registry.load_all()`; `registry.FAMILIES`,
`readplan.families()`, `tiers.CORE` and `COMMANDS` are unchanged (I1, I4).*

**Ruff.** `pyproject.toml`: `extend-exclude =
["evals/hallucinationbench/sibling_probe/pilot"]` (HB excludes that verbatim pilot record);
per-file ignores for `src/wsbench/hb/**`, `tests/hb/**`, `scripts/hb/**` listing exactly the
rule codes that fire there under WSB's selection after M5 (on `src` before the move: N806,
N803, N812, N815, RUF001, RUF002, SIM118, SIM102, SIM300, SIM108, C416; tests and scripts are
measured by the implementer). No code is changed to satisfy a lint rule.

**Dependencies.** `dev` gains `matplotlib>=3.11.2` (`final.py` plots are called by
un-guarded tests; in HB it is a default dev dependency). New extra `hb =
["transformers>=5.11", "jinja2>=3.1"]` (the sibling tokenizer; both already in the lock through
`gpu`). `uv.lock` is regenerated and committed. CI keeps installing `.[dev]` only, so the
tokenizer tests skip there as they do without the tokenizer; scikit-learn stays behind its
`importorskip`. `anthropic` 1.6.0 and `openai` 3.14.1 in the lock satisfy HB's minimums.
CLAUDE.md's Workflow line is unchanged (`uv sync --extra dev`).

**Docs.** `docs/hallucinationbench.md` rewritten: HB lives in `src/wsbench/hb`, how to run
`wsbench hb …`, the index stays out of the macro (I1), the vendored v8 file is the record.
Version labels, plan numbers and dates stay inside code spans (`test_readme_style.py`), and
every `evals/…` path written in it, in `CLAUDE.md` and in `AGENTS.md` exists
(`test_every_written_evals_path_exists`). README: the one HallucinationBench sentence is
updated. `CLAUDE.md` / `AGENTS.md`: a short section pointing at `src/wsbench/hb/CLAUDE.md`,
which documents H4's hazard.

**Bank protection (plan 0097, PR #510, open).** If #510 has merged before this PR, the
`evals/hallucinationbench/<eval>` directories go through `wsbench pack`; if not, they are
plaintext like every other bank and #510 picks them up. They are already public in the HB
repository.

### 1.4 Acceptance gates for stage A

Environment: a `.venv` of this worktree (`uv sync --extra dev --extra hb`, local uv cache);
`outputs/` is gitignored; the frozen outputs are linked as HB has them,
`ln -s /dev/shm/hb-v8-full/v8-full outputs/v8-full`. Nothing writes under `/dev/shm/hb-v8-full`.

- **G0 (baseline, before the import, in `/root/tmp/hb-v8-final` at `ecfae41`).**
  (a) HB's suite with its own environment, per-test outcome (pass / skip with reason / fail)
  recorded to a file. (b) The same in an off-box environment: every `HBENCH_*` variable of
  `paths.py` plus `HBENCH_OR_READOUTS`, `HBENCH_X3_BANK`, `HBENCH_SAFETY_*` set to a
  nonexistent directory (unset would select the box defaults), an empty `HF_HOME`,
  `HF_HUB_OFFLINE=1`, without the `sibling` group; tests that fail there are the H9 list.
  (c) `hbench final` on the frozen outputs (the checkout's `outputs/v8-full` link exists; pass
  `--out <scratch> --plots <scratch>`, the default `--plots` overwrites tracked PNGs) and
  the G5 story rebuild, both with HB's own code: recorded whether each equals the frozen file.
  (d) This repository's locked ruff, `format --check`, on HB's untouched `src`, `tests`,
  `scripts`: result recorded (M4). Order: (a), (c), (d), then (b) in a throwaway environment
  (it must not re-sync HB's `.venv`).
  The frozen index was written at `5a59f8c`, before plan 0030 trimmed `index.py`, and some
  `cache.jsonl` files were appended to after their `cells.jsonl` was written, so equality is
  measured, not assumed. **G1 and G5 compare against (c)**; where (c) itself differs from the
  frozen file, the difference is reported and the gate is "the moved code equals HB's code".
- **G1 (index identity).** From the worktree root, `wsbench hb final --manifest
  evals/hallucinationbench/index/v8_manifest.json --methods
  evals/hallucinationbench/index/methods.json --out <scratch> --plots <scratch>` writes an
  `index.json` that equals G0(c)'s (expected: the frozen
  `/dev/shm/hb-v8-full/v8-full/final/index.json`) **byte for byte except `git_sha` and
  `manifest.path`** (`manifest.sha256` and
  `manifest.persistent_failures.path` equal). `final` re-hashes every manifest entry's derived
  file and recounts cells and failures from it, so this proves the scoring, index and bootstrap
  code is unchanged. About 9 min, no API.
- **G2 (the vendored file).** A check pasted into the PR (not committed) loads G1's output and
  `evals/hallucinationbench/index.json` and asserts equal values, CIs, `full`, `matched` and
  joint rows for the vendored methods (the vendoring script itself refuses any `git_sha` but
  `HB_SHA`, so it is not re-run and the vendored file is not regenerated).
- **G3.** `pytest tests/hb -q`: every test has the outcome it had in G0(a); the only allowed
  differences are H6's test and the three tokenizer tests if the HF cache is cold under H5,
  each named in the PR. `tests/hb/test_stage_a.py` passes.
- **G4.** `pytest -q` (whole suite; in tmux with a log, time recorded in the PR), `ruff check .`,
  `ruff format --check .` green; `scripts/hb/import_from_hb.py --check` leaves only H1–H7 and
  H9; every `scripts/hb/**/*.py` passes `py_compile`, and each one that builds an `argparse`
  parser and is not a Modal app answers `--help` with exit 0 (`build_dev_v2.py` has no parser
  and **rewrites `calibration/dev_v2.jsonl` whenever it is run**: it and `v8/or_common.py` are
  `py_compile` only). After G3, G4 and G5, `git status` shows no change under
  `evals/hallucinationbench/`.
- **G5 (cache lookup path).** G1 reads derived files, not caches, so it does not exercise
  fingerprints. The **story** eval is rebuilt from cache for all three arms with HB's existing
  no-API replay:
  `wsbench hb run --eval story --rebuild --readouts-root /root/tmp/hb29-pilot-in/story-readouts
  --arms s3d-rl600-all11,mlnla-rl600-all11,jlens --out <scratch>`, and the same with
  `--joint --rebuild` (the command needs the arms and a readouts root to start; the judge model
  defaults to `claude-opus-5-5`, which is the directory level below `story/`):
  1. Readouts: the manifest's `provenance.readouts.story` paths
     (`/root/tmp/hb29-pilot-in/story-readouts/<arm>/hallucination.jsonl`) are restored from the
     archive (`/workspace/hb-v8-full/inputs/root/tmp/hb29-pilot-in/…`, a few MB per arm) and
     their sha256 checked against the manifest. The joint rebuild reads the absolute `sources`
     recorded in `joint.json`, which are these same paths.
  2. Scratch root `<scratch>/story/claude-opus-5-5/<arm>/` per arm: `arm.json` and `joint.json`
     **copied** from the frozen arm directory (the rebuild reads `map_prompt` and
     `excuse_verifier` from them), `cache.jsonl` **symlinked** (the rebuild opens it read-only).
  3. Run the per-layer and the joint rebuild with `--out <scratch>`; they write `cells.jsonl`,
     `cells_joint.jsonl` and summary files into the scratch arm directories only.
  4. `cells.jsonl` and `cells_joint.jsonl` have the sha256 of G0(c)'s rebuild (expected: the
     manifest's), and no cell is reported unjudged.
  Main and agentic misalignment are not rebuilt (8 GB and 11 GB roots; the local disk has about
  5 GB free): stage A edits no prompt, key or fingerprint code, the hash-pin tests cover those
  objects, and this is said in the PR.

### 1.5 Files (new or modified)

```
src/wsbench/hb/                      (new: HB's package, 81 files; + CLAUDE.md)
src/wsbench/cli.py                   (modified: `hb` dispatch before COMMANDS, usage line)
evals/hallucinationbench/<eval>/     (new: 8 bank directories, bytes unchanged)
evals/hallucinationbench/index/      (new: v8 manifest, persistent failures, HB methods.json)
evals/hallucinationbench/README.md   (modified)
scripts/hb/                          (new; incl. import_from_hb.py)
tests/hb/                            (new: package; 64 test files, helpers, fixtures)
tests/hb/test_stage_a.py             (new, not from HB)
tests/test_no_token_interpreter.py, test_bank_versions.py, test_family_paths.py
                                     (modified: path-scope exemptions only, §1.3)
docs/hallucinationbench.md           (modified)   docs/hb/   (new)
plans/hb/                            (new: HB's 20 plans)   plans/0120-…md (this file)
pyproject.toml, uv.lock              (modified: dev + hb extra, ruff exclude and per-file ignores)
README.md, CLAUDE.md, AGENTS.md      (modified: pointers)
```

G1, G4 and G5 run in one tmux session with a timestamped log under `logs/` of the worktree
(`tail -f logs/<file>`); nothing is launched on GPUs in stage A.

## 2. Stage B1 (next PR): judge throughput

Measured on the frozen v8 caches (2026-11-27): one full judge pass over three methods is about
1.34M calls and 2.44B output tokens; main and agentic misalignment are 97% of it; NLA is 65%.
One `hbench` process at its defaults (64 calls in flight, 1,500 requests/min) would need about
14 h (J-lens), 40 h (O-lens), 84 h (NLA). The 2026-11-05 run took 5.5 h with 76 hand-launched
processes and ran into the organisation's output-token rate limit (2–3 retries per call).

- `wsbench.hb.llm.LLM` keeps its interface, its usage accounting, **its cache fingerprint tuple
  and row format (unchanged, I5)**, and its caller-side fallbacks with `meta.answered_by`; its
  transport acquires `wsbench.llm`'s cross-process slot (`WSB_SLOTS`) and the file-backed
  request and input-token pacers (`WSB_PACER`) around each API attempt. Throughput settings are
  in no fingerprint, as in WSB.
- `wsbench hb run-all method=<m> readouts=<root> out=<dir>`: one child process per (eval,
  stage group, layer shard), as `runner.py` does per family, in a run-private temp directory
  with `WSB_SLOTS` 1500; defaults concurrency 256. It replaces `jobs/job.sh`, `amstage.sh`,
  `or_*.sh`. Stages keep their order within an eval; evals and layers run side by side.
- The NLA joint claim map on Sonnet made 76k calls for 36k cells because long answers were cut
  at the output cap and re-asked (31% of all output tokens). Raising that stage's output cap or
  re-asking with a larger cap is **not** a prompt change but can change which answer is cached
  for a cell that previously failed; it is done only for cells with no successful row, and the
  count is reported.
- Gate: replay of the three methods' frozen roots makes zero API calls and reproduces G1; a
  fresh judge pass of one layer of one method (O-lens L44, all evals) is timed and its index row
  compared with the frozen row (judge noise expected; reported, not gated).

Expected after B1 (estimate from the organisation rate limits, not measured): the output-token
limit is the floor, roughly 0.5 h J-lens, 1–1.5 h O-lens, 3 h NLA when nothing else is judging.

## 3. Stage B2 (PR after B1): reads from stored activations

HB's repository has no read side; its readouts came from one-off scripts. HB's banks already
hold what the `captured` render needs (`capture_rows.json`: `input_ids` + `eval_positions`;
`sites[].pos`).

- A read-plan source for HB evals: `wsbench hb plan [evals=] out=` writes `ReadSpec` rows
  (render `captured` or explicit positions, layers `GRID`) under eval names `hb_main`,
  `hb_story`, `hb_agentic`, `hb_overrefusal`, `hb_roleplay`, `hb_sibling`, and `wsbench
  capture plan=<file>` / `wsbench read plan=<file>` take them as they take any cell list. The
  evals are **not** added to `readplan.families()` or the registry (I1, I4), so no family
  count or ledger pin moves.
- Sampling: HB's per-layer unit reads k = 3 prose samples (J-lens: one top-10 list); the joint
  unit uses sample 0 of each layer. The sidecar's `sampling` gains the value `prose3`; `read`
  and `produce` take `samples=3`.
- Size of the one-time capture (read sites only, 11 layers, 5,120 values, bf16): 1.79M vectors
  = 18.3 GB (benign role-play 10.7 GB, agentic 5.7 GB, overrefusal 1.3 GB, main 0.67 GB,
  story 0.02 GB). 1,075 prompts, 302k prompt tokens: the forward passes are minutes; expect
  under 2 GPU-hours including model load. Benign role-play's 86 shared prompts are WSB's
  jailbreak controls and may already be in the store (same token ids and positions → same key).
- Lens generations per prose method: about 1.13M without benign role-play, about 2.2M with it
  (if it is read at k = 1). At the measured 0.022 s per sequence (O-lens, B300) that is about
  7–14 GPU-hours per method through the batch reader; the served engine should be lower. NLA
  cannot use the served engine (it changes more than one input embedding) and reads through
  `produce`.
- The dataset is Agam's (`agu18dec/workspacebench_residuals`); HB's folders go up as a PR to it
  and `evals/residuals/map.json` gets the spliced part, or HB gets its own dataset if he prefers.
- Gate: readouts of O-lens re-read from the store for one layer agree with the stored v8
  readouts where sampling is deterministic (J-lens: token lists identical), and for sampled
  prose the index row is compared with the frozen one.

## 4. Stage C: index version `hindex-v9` (scoring changes; each needs its own plan section and re-judge)

Listed so that stages A and B leave room for them; none is designed here.

1. J-lens summariser: non-semantic tokens are junk, an all-junk readout is junk; the language of
   a token is not evidence about the text. J-lens also gets the interpreting summariser in
   overrefusal and benign role-play.
2. Agentic misalignment: "the CEO" for an executive is always `substitution_sibling`.
3. Overrefusal: renamed (it measures off-topic refusals); a unit counts only if every method has
   a digest, or the commonly refused prompts are removed (her choice, open).
4. User modelling (sibling): WSB's item changes (one item dropped, one rewording), a more
   generous commitment rule, a J-lens score.
5. Benign role-play: after the WSB jailbreak changes, it becomes this checkout's
   `jailbreak_recognition` on the HB-only bank plus the shared controls (the pinned subprocess of
   §1.2 is removed), with the Qwen gate re-checked on the 64 HB-only prompts.

## 5. Stage D: a fast tier (only if she wants one)

Can be designed offline from the frozen v8 cells with no API calls: candidate cuts are fewer
layers for the per-layer rows, a seeded half of the main items, and a position window for
agentic misalignment (every prompt token × 11 layers is 555k cells per method). The test is
whether the three methods' index values and order are preserved with intervals.

## 6. Stage E: retire the HB repository

Archive `camila-blank/hallucination-bench` with a pointer here once stage B1 has merged and a
full run has been made from this repository. The viewer's HB ingest (`BANKS`, `SAFETY_BANKS`,
`meta.load_hb`) moves to this checkout's layout then. `scripts/vendor_hb_index.py` and the `HB_SHA` pin
are removed when `hindex-v9` is built here; until then the vendored v8 file is the record.

## 7. Open, for Camila

- Fast tier: yes or no, after the B1 timing run.
- Overrefusal name and drop rule; how generous the user-modelling rule is; whether v9 replaces
  v8 as the headline.
- Where HB's activations live (PR to Agam's dataset, or a separate dataset).

## 8. Order of work (stage A)

0. G0 (a)-(c) in the HB checkout.
1. `scripts/hb/import_from_hb.py` (copy + M1-M5), then H1-H9 and `test_stage_a.py`.
2. `pyproject.toml`, `uv.lock`, CLI dispatch, the scan-test exemptions.
3. G3, then G4, then G1 / G2 / G5 in tmux.
4. Docs.
