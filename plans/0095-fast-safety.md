# 0095: `--fast-safety`, a second fast subset that includes jailbreak_recognition and agentic_misalignment

Issue #502.

## Why

Camila, 2026-11-18: add another version of the fast subset, "fast subset + safety", which does
include agentic_misalignment and jailbreak_recognition. Plan 0094 took the two families out of
`--fast` (fast-v2) because they hold a fast run above 30 minutes; a run that wants the safety
signal has had no selectable subset since (fast-v1 "needs the pre-0094 commit").

## What it is

Two selectable fast subsets from now on:

| flag | version | families | units | read items |
|---|---|---|---|---|
| `--fast` (unchanged) | `fast-v2` | 22 | 1,823 | 2,160 |
| `--fast-safety` (new) | `fast-safety-v1` | 24 | 1,996 | 2,351 |

`fast-safety-v1` = fast-v2's 22 entries plus fast-v1's `jailbreak_recognition` entry (155 items:
70 jailbreak + 85 control, positions `punct_special`) and `agentic_misalignment` entry (18
pairs, 36 read items, positions `last_n` 60), each entry byte-for-byte the entry of
`fast_v1.json`. Its content is therefore fast-v1's; it is a new versioned file with its own
name because fast-v1 is a retired version and the name must say what the subset is.

`--fast` keeps meaning fast-v2 in every respect. Nothing about a default run changes.

## Change

### The frozen file

`evals/fast/fast_safety_v1.json`: `version: "fast-safety-v1"`, `subject` as v1,
`dropped_families` = v1's six in v1's order, `families` = v1's 24 entries in v1's key order,
every entry identical to v1's (`bank_sha`, `units`, `read_ids`, `positions`, key order). Same
serialization as `fast_v1.json` (the file differs from it in the `version` value only; write it
by loading v1, replacing `version`, and dumping with the same `json.dumps` settings that
reproduce `fast_v1.json` byte for byte, which the implementer verifies by round-tripping v1
first). `fast_v1.json` and `fast_v2.json` are not touched (v1's sha256 stays pinned; pin v2's
and the new file's too).

### `fast.py`: the active subset

- `DEFAULT = "fast-v2"`. `VERSION` stays the module attribute every caller reads **at call
  time**, and is now documented as "the active subset of this process": `DEFAULT` unless
  `select` changed it. Tests keep patching `VERSION` directly.
- `VARIANTS = {"": "fast-v2", "safety": "fast-safety-v1"}`: the CLI-selectable subsets by
  variant name. fast-v1 is not in it (still not selectable from the CLI).
- `select(variant: str = "") -> str`: sets `fast.VERSION = VARIANTS[variant]` and returns it;
  an unknown variant raises `ValueError` naming the known ones. It is the only writer of
  `VERSION` outside tests.
- `VERSIONS` gains `"fast-safety-v1"`.
- `COMPATIBLE = frozenset({"fast-v1", "fast-v2", "fast-safety-v1"})`, and its meaning is
  restated: the set of versions that are **mutually** entry-compatible, i.e. for any two of
  them every family present in both has the identical entry. The two uses keep their exact
  form and their plan-0094 rule is retained: a sidecar is accepted iff `declared_fast in
  {fast.VERSION, *fast.COMPATIBLE}` *and the `plan_sha` guard still holds*; a result row is in
  the macro iff `fast_subset == fast.VERSION`, or `fast_subset in fast.COMPATIBLE` *and the
  row's family is in `fast.subset()`* (the family clause is retained: a jailbreak row under
  active fast-v2 stays excluded as `stale fast subset (<v>)` whichever version stamped it).
  Consequences, all intended:
  - under `--fast-safety`: fast-v1 files / rows of all 24 families and fast-v2 files / rows of
    the 22 are accepted, so a finished `--fast` run becomes a `--fast-safety` run by judging
    the two safety families into the same directory with `wsbench judge --fast-safety` (not
    `run families=...`, which rewrites `summary.md` / `run.json` with those two only) and then
    `wsbench report dir=... --fast-safety`;
  - under `--fast`: fast-safety-v1 rows of the 22 families are in the macro, the two safety
    rows are excluded (`stale fast subset (fast-safety-v1)`);
  - code before this change excludes / refuses anything stamped `fast-safety-v1` (fail closed).
- **`plan_sha` of the two position-reduced families.** A fast plan row of a family whose
  entry has `positions` carries `extra.fast = fast.VERSION` (`readplan.plan`), and `plan_sha`
  hashes it, so the fast plan sha of jailbreak / agentic under `fast-safety-v1` differs from
  the one a fast-v1 file declares. `readplan.plan` is not changed (a new file's rows say
  `fast-safety-v1`), and `_clean_row` / `PLAN_SHA_EXCLUDE` are not changed (the pinned fast-v1
  shas and every existing sidecar stay valid). Instead `reads.fast_plan_sha(family,
  declared=None)` gains the parameter: with `declared` set, each row's `extra["fast"]`, where
  the key is present, is replaced by `declared` before hashing, i.e. the sha that version's
  own plan had (valid only because the entries are identical; `declared` must be in
  `{fast.VERSION, *fast.COMPATIBLE}` and name a version whose file holds the family, else
  `SystemExit("<family>: not in fast subset <declared>")`; `reads.load` reports it through
  its `fail(...)` with the path, like its other refusals). The `plan_sha` guard in `reads.load` compares the sidecar's `plan_sha` with
  `fast_plan_sha(family, declared=declared_fast)`; *the guard itself is retained and still
  fails closed on any other difference*. For the 22 families without `positions` no row
  carries `extra.fast`, so nothing changes for them.
- The position-reduction machinery (`fast_of` / `punct_special` / `is_fast_site`,
  `reads.fast_narrow`, `fast.position_stamp`, the `+fast-punct_special` / `+fast-last_n60`
  result-stamp suffix) is unchanged and is now live again under `--fast-safety`. No judge
  prompt, fingerprint, cache key, call version or `prompt_version` moves: for every one of the
  24 families a `--fast-safety` run makes exactly the calls a fast-v1 run made, so a fast-v1
  cache replays with 0 new calls and the same value; only `config.fast_subset` differs.

### CLI

- `main`: `--fast-safety` is rewritten to `fast=safety` exactly as `--fast` is rewritten to
  `fast=True` (same line; a command without the `fast` key fails as unknown, as today).
- One shared normalizer for the `fast` key (`plan`, `produce`, `judge`, `run`): a false value
  -> `fast=False`; a true value (`True`, `true`, `1`, ...; whatever `_bool` accepts as true)
  -> `fast=True`, `fast_variant=""`; the string `safety` -> `fast=True`,
  `fast_variant="safety"`; anything else is a `ValueError` (usage error, exit 2) naming
  `True` and `safety`. `self.fast` stays a bool after `finalize`, so every existing
  `if self.fast` / `getattr(args, "fast", False)` keeps working. `fast_variant` is a new
  attribute declared in `__init__` as `""` and always overwritten by the normalizer from
  `fast`; a user-supplied non-empty `fast_variant=` is a usage error ("use fast=safety").
  The normalizer tests for the string `safety` BEFORE calling `_bool` (`_bool` raises on
  other strings); its error text: `fast must be True, False or safety, got <value!r>`.
  `finalize` never calls `select`.
- Selection: each of those commands calls `fast.select(self.fast_variant)` at the top of
  `execute` **only when `self.fast_variant` is non-empty** (never in `finalize`: `--help` /
  `--show` leave the process alone, the plan-0092 rule). Plain `--fast` never writes
  `fast.VERSION`: it runs whatever is active, which is `DEFAULT` in a fresh process and the
  patched version in a test (`test_cli_plan_fast` runs `plan --fast` under the `fast_v1`
  fixture and must stay verbatim). A test that calls `--fast-safety` and then `--fast` in one
  body sets `fast.VERSION = fast.DEFAULT` in between. `runner.judge_family` / `run_families`
  keep reading `fast.VERSION`.
- `report`: its `fast` key is tri-state today (`""` unset, True, False). It accepts `safety`
  too, through its own normalizer that keeps `""`: `safety` -> `fast=True`,
  `fast_variant="safety"` (same declared attribute and usage-error rule), and
  `fast.select("safety")` at the top of `execute`, before the macro is computed. Without
  `safety` the report is the report of the active subset as today (fast-v2 in a fresh
  process), plus a hint: `fast_header(results=())` takes the result rows, and for each
  `VARIANTS` entry `(variant, version)` other than the active version counts the rows with
  `config.scope == fast.SCOPE` whose family is NOT in `fast.subset()` but IS in
  `fast.subset(version)` and whose `fast_subset` is `version` or in `fast.COMPATIBLE` (so
  the existing fast-v1 directories get it too). When the count `n` > 0 it appends, on its
  own second line (the first line stays byte-identical and still ends "are excluded"):
  "`<n>` row(s) are in `<version>` only; pass `--fast-<variant>` for its macro". Both callers
  (`cli.py:553`, `:1583`) pass their rows. A bare `report dir=` on a `run --fast-safety`
  directory therefore rewrites `summary.md` to the fast-v2 view with that hint (say so in
  the README). `run` prints
  its own summary in the process where the subset is already selected, so `run --fast-safety`
  reports the 24-family macro with no extra flag.
- Process mode (plan 0092 §5): under fast, `runner.judge_argv` emits `fast=<variant>` when the
  ACTIVE `fast.VERSION` is the version of a non-empty `VARIANTS` key (reverse lookup, so a
  Python caller who called `fast.select("safety")` with a hand-built namespace is covered
  too), else `fast=True` as today (default, or a test-patched fast-v1). The `judge` child then selects the subset itself. Nothing is
  passed through the environment.
- `--fast` and `--fast-safety` together are two `fast=` overrides; the last one wins (pydra's
  rule for a repeated key), not an error.
- `reads.load`, next to the declared-version check and unconditionally (with or without a
  sidecar `plan_sha`): a FAST file whose declared version's file does not hold the family is
  refused (a jailbreak sidecar declaring `fast-v2`).
- Messages that name the subset already read `fast.VERSION` at call time ("<family>: not in
  fast-safety-v1", `fast_header`, the `entry` refusals); `_check_fast`'s texts say `--fast`
  and stay (they apply to both variants).
- `Producer.run_family(fast=True)` declares `"fast": fast.VERSION` as today, which is
  `fast-safety-v1` after `produce --fast-safety`. The `Producer` Python API gains no
  parameter: a caller that wants the safety subset calls `fast.select("safety")` first.

### Not changed

Bank files, ATI, judge prompts, call versions, the non-fast paths
(`tests/golden/plan_sha_pre_0090.json`), fast-v2's numbers, `run.json` keys.

## Invariants

- `fast_v1.json` and `fast_v2.json` byte-identical before and after.
- Mutual compatibility (new test): for every pair of versions in `COMPATIBLE`, every family in
  both files has an equal entry (deep-equal, same key order).
- `fast-safety-v1` families ⊇ `fast-v2` families; the strict ATI subset (`ati-subset-v2`) is
  contained whole in both.
- `fast.VERSION == fast.DEFAULT` at the start of every test (an autouse fixture in
  `tests/conftest.py` sets it to `DEFAULT` before the yield and again after; CLI tests that pass `--fast-safety` mutate it).

## Tests

A modified pre-existing test is a red flag. Sanctioned edits, and only these; list every edited
pre-existing assertion in the report:

(a) literals that enumerate the known versions or `COMPATIBLE`
(`tests/test_fast_subset.py:1238`: `set(fast.VERSIONS)`, `set(fast.COMPATIBLE)`).
(a2) the parameter list `[V1, V2]` of `test_every_version_contains_the_strict_ati_subset_whole`
gains the new version (no assertion edit); `tests/test_run_procs.py`'s argv test gets a NEW
parametrized case for `fast=safety` (its existing `forwarded` tuple is not edited).
(b) a pre-existing assertion on the exact text of `fast_header()` or of the unknown-`fast`
usage error, if one exists, only where this plan changes that text.
No other pre-existing assertion changes; in particular every plan-0094 test about `--fast`
(jailbreak / agentic are `NotInFast` under `--fast`; a fast-v1 jailbreak row is excluded under
fast-v2; `fast-v0` refused) stays verbatim and green. If any other pre-existing test fails,
stop and report it instead of editing it.

New tests (`tests/test_fast_subset.py`, `tests/test_run_procs.py` for the argv):
- the new file: equals `fast_v1.json` except `version`; equals `fast_v2.json`'s 22 entries plus
  v1's two; sha256 of all three files pinned; mutual-compatibility invariant; ATI containment.
- `select`: `select("safety")` -> `fast-safety-v1`, `select("")` -> `fast-v2`, unknown raises
  `ValueError`; the conftest fixture restores the default.
- CLI: `plan --fast-safety` (families=all) plans 24 families and the jailbreak rows carry
  `fast_of` with `extra.fast == "fast-safety-v1"`; the fast plan rows and `fast_plan_sha` of
  jailbreak and agentic computed AS fast-v1 (`fast_plan_sha(f, declared="fast-v1")`, below)
  under active `fast-safety-v1` equal the pinned fast-v1 literals already in the test file,
  and their own `fast-safety-v1` shas are pinned as two new literals (they differ from v1's).
- `judge --fast-safety` on jailbreak_recognition / agentic_misalignment judges (toy/fake calls,
  as the existing v1-fixture end-to-end tests do) and stamps `fast_subset = "fast-safety-v1"`
  with the `+fast-punct_special` / `+fast-last_n60` suffix; `judge --fast` on them still exits
  2 with "not in fast-v2"; `fast=bogus` is a usage error.
- `run --fast-safety`: skips only the six dropped families; summary header says
  `fast-safety-v1 (24 families`.
- sidecars, through `reads.load`, under active `fast-safety-v1`: a jailbreak and an agentic
  file declaring `fast-v1` with the pinned v1 sha (`V1_FAST_PLAN_SHA[f]`) is accepted; one
  declaring `fast-safety-v1` with its own sha is accepted; `fast-v1` with the safety sha and
  `fast-safety-v1` with the v1 sha are each refused ("different fast plan"); a jailbreak file
  declaring `fast-v2` (whose file has no such family) is refused; a poetry file declaring
  `fast-v2` is accepted; `fast-v0` refused; a produced file declares `fast-safety-v1`. Mirror
  under patched `fast-v1`: a jailbreak file declaring `fast-safety-v1` with the safety sha is
  accepted. Under default fast-v2: a `fast-safety-v1` poetry file is accepted.
- macro: under safety, fast-v1 and fast-v2 rows in; under default, a fast-safety-v1 poetry row
  in and a fast-safety-v1 jailbreak row excluded as `stale fast subset (fast-safety-v1)`, and
  the header carries the `--fast-safety` hint; `report --fast-safety` on the same rows gives
  the 24-family header and no stale exclusion.
- `runner.judge_argv`: `fast=safety` when the active version is `fast-safety-v1` (with and
  without `fast_variant` on the namespace), and the command parsed back by the `judge` config
  has `fast is True` and `fast_variant == "safety"`; `fast=True` otherwise (default and
  patched fast-v1). The "jailbreak file declaring `fast-v2`" refusal is tested with and
  without a sidecar `plan_sha`.
- cache replay: a toy family's cache written with `VERSION` patched to fast-v1 replays under
  `fast-safety-v1` with 0 new calls and the same value (toy only; the replay of the two real
  position-reduced families is the validation step below).

## Docs

- `evals/fast/README.md`: title and intro name both subsets; a "`fast-safety-v1`" section (what
  it adds, the two reduced reads and that they are fast-v1's, the cost: the two families take
  23 to 38 minutes to judge after their readouts land vs 1 to 13 for the others, and agentic's
  fast `pair_rate` moves by about 0.07 between identical runs, so do not rank on it from one
  run; the compatibility rules above); the "fast-v1 only" wording in "How it was chosen", the
  counts table and "How a fast value is computed" becomes "`fast-safety-v1` (and `fast-v1`)";
  the counts table's last row is labelled `fast-safety-v1` / `fast-v1`, 24 families; "is not
  selectable / needs the pre-0094 commit" is replaced by "`--fast-safety`"; "Re-freezing"
  states the mutual-compatibility rule and that a re-frozen family needs new versions of both
  subsets.
- `README.md` "Fast subset": the two flags and the table above; the already-measured 24-family
  macros (s3d 0.535, rl-affw 0.491, Q9 0.478, NLA 0.442, prompt-only 0.475, J-lens 0.116, logit
  lens 0.063, today described as "on fast-v1") are the `--fast-safety` numbers; fast-v2 and
  fast-safety numbers are different scales and must not be put side by side as one column
  without the label.
- `docs/producing_readouts.md` (:189-220): the "fast-v1 only" bullets apply to
  `--fast-safety`; sidecar declarations.
- `CLAUDE.md` fast paragraph: add plan 0095 (`DEFAULT`, `VARIANTS`, `select`, mutual
  `COMPATIBLE`, `fast=safety`, `judge_argv`), and correct "exercised only by tests that patch".
- Docstrings / comments that say the two families "need the pre-0094 commit".

## Files

```
evals/fast/fast_safety_v1.json         new, frozen
evals/fast/README.md, README.md, docs/producing_readouts.md, CLAUDE.md
src/wsbench/fast.py                    DEFAULT, VARIANTS, select, VERSIONS, COMPATIBLE
src/wsbench/cli.py                     --fast-safety, the fast normalizer, select in execute, report, fast_header
src/wsbench/runner.py                  judge_argv
src/wsbench/reads.py                   fast_plan_sha(declared=), the plan_sha guard
src/wsbench/results.py, readplan.py, produce/producer.py   docstrings only ("pre-0094 commit", "fast-v1 only")
tests/conftest.py                      restore fast.VERSION
tests/test_fast_subset.py, tests/test_run_procs.py
plans/0095-fast-safety.md
```

## Validation before merge

ruff, `pytest -q`. Then on real data, offline (no API spend, no GPU), on COPIES (never write
into `/dev/shm/wsb-val/s3d-fast-e2e2`; `wsbench report` rewrites `summary.md`):
- `wsbench report dir=<copy of the s3d fast-v1 run's judged dir> --fast-safety`: header
  `fast-safety-v1 (24 families`, no row excluded as stale, macro and every row value equal to that
  directory's own stored `summary.md` / `results.json` (written by pre-0094 code as fast-v1;
  about 0.533, a later run than the README's 0.535).
- the same copy with `--fast`: the fast-v2 macro over 22 rows, the two safety rows excluded as
  stale, as before this change (with the hint line: 2 rows are in `fast-safety-v1` only).
- `scripts/cache_only_run.py family=jailbreak_recognition --fast-safety readouts=<the run's
  readouts file> out=<copy of the family's judged dir> layers=20,24,28,32,36,40,44,48,52,56,60
  opts=aggregate=summary` (and agentic_misalignment; `opts=aggregate=summary` is required, the
  script defaults to native, which `--fast` refuses): no uncached call is refused and the new
  `results.json` equals the stored one except `config.fast_subset` (and the run-setting
  stamps). That run's sidecars declare `"fast": "fast-v1"` with the v1 `plan_sha`, so this is
  the real-data exercise of the `declared=` path. The script needs no change (it hands argv to
  `main`, which rewrites `--fast-safety`).
