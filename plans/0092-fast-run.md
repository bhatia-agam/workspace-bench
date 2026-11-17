# 0092: faster runs (parallel families, uncapped digest concurrency, judge while readouts land)

Issue #484.

## Problem

One lens costs hours of wall-clock although the judge work is small. Measured (rl-affw-x4, union,
Opus judge): 80,700 calls, 168M output tokens. The time goes to three throttles, none of which
protects a score:

1. `wsbench run` defaults: `family_workers=3`, `concurrency=64`, `rpm=240`. At 240 requests a
   minute the full bench's 80,700 calls take 5.6 hours whatever the concurrency. Every in-house run
   already overrides these (`concurrency=256 rpm=30000`, one process per family).
2. `digest.FAMILY_DEFAULTS` pins `summ_concurrency` to 8 for `jailbreak_recognition` and 4 for
   `agentic_misalignment`. These two families set the wall-clock: with 32 digest slots the fast
   jailbreak read spends 42 min on 1,705 per-layer digests (about 48 s a call); with 256 slots the
   same stage measured 7 min (2026-11-17, mlnla11-rl600, `--fast`).
3. `run` skips a family whose readouts file does not exist yet, so judging cannot overlap the read:
   the caller must wait for every file, or script its own polling loop (the in-house
   `affw_driver.py`).

## Goal

`--fast` end to end in about 30 minutes and the full bench in about an hour, with a wide read
fan-out. This plan is the bench half: defaults and a waiting `run`. The reader half lives in the
in-house producer and is out of scope here.

## Non-goals, invariants

- **No prompt, fingerprint or cache key changes.** Concurrency, rpm, token pacing and worker counts
  are not part of any call fingerprint (`cache.py`, `mcjudge` fingerprint), `prompt_version` or
  `plan_sha`; a cached run replays with 0 new calls after this change (replay test below).
- `config.concurrency` / `config.rpm` are stamped into every result by `mcjudge.base_config`; they
  change with the defaults, are provenance only and are compared by nothing (`results.py:586` and
  `baselines/prompt_only.py` ignore the summarizer's `concurrency` / `timeout`; no golden pins them).
- `summ_timeout`, `summ_fallback`, `summ_max`, `summ_rare` family defaults are retained unchanged;
  only the two `summ_concurrency` entries go.
- `opts=summ_concurrency=N`, `concurrency=`, `rpm=`, `family_workers=` keep working as overrides.
- With `wait=0` (the default) `run` is byte-identical to today: same order of checks, same
  messages, outcomes and exit codes.
- The process-wide pacer (`llm._PACER`) still bounds the whole run by `rpm=`.

## Changes

### 1. Defaults (`cli.py`)

- `JudgeOptions.concurrency`: 64 -> 256. `JudgeOptions.rpm`: 240 -> 30000. `JudgeOptions` also
  feeds `wsbench judge`, so every script that shells out without explicit values
  (`scripts/ati_panel_judge.sh`, the `adapt_set.sh` flows) inherits them.
- `RunFamilies.family_workers`: 3 -> 8 (amended after the first end-to-end run, 2026-11-17: a `run`
  is one process on one core, and 24 families at once at 256 saturated it and dropped 1,225
  calls' connections; process-per-family judging is a follow-up), where 0 means "every family at once"
  (`workers = n` when `family_workers <= 0`, else `min(n, family_workers)`).
- `run` and `judge` raise the soft `RLIMIT_NOFILE` to `min(hard, 65536)` in `execute()` (not
  `finalize()`, so `--help` / `--show` do not touch the process; best effort: `ImportError`,
  `ValueError`, `OSError` are swallowed): 256 x many families exhausts 1024 descriptors
  (seen in-house, "Too many open files" on every call).
- The README says what to lower on a rate-limited key (`rpm=`, `itpm=`, then `concurrency=`).
- `baseline`, `capable`, `adapt` and other commands with their own concurrency defaults are not
  touched.

### 2. Token pacing replaces the two fixed digest caps (`llm.py`, `digest.py`, `cli.py`)

Why the caps exist: plan 0021 set agentic's digest concurrency to 4 "since each call is about 0.9M
input tokens against the org's 10M tokens/min", and plan 0037 set jailbreak's to 8 (bundles average
~361k tokens, up to 1.7M). `rpm=` paces requests, not tokens, so a fixed slot count was the only
guard. The limit is now 100M input tokens / min (Opus 5.5 and Sonnet 5, response headers
2026-11-17), and fast-subset reads are 4 to 25 times smaller, but 256 calls of 0.9M tokens at once
would still be 230M. So the guard becomes a token budget:

- `llm.py`: a second process-wide, thread-safe pacer `_TOKEN_PACER` beside `_PACER` (same
  `threading.Lock` design, a `reset()` like `_PACER`'s). Module setting
  `llm.set_itpm(tokens_per_minute)` (0 = off, the library default, so hand-built callers are
  unchanged). **`_pace(rpm)` is not changed** (seven test files replace it with a one-argument
  fake). A new `async _pace_tokens(est)` is awaited once per call, before the `for attempt` retry
  loop, in `_one` (`est = (len(system) + len(user)) // 3`) and in `_one_text`
  (`est = len(user) // 3`; it has no system prompt). When on, the call's start slot is
  `max(now, next)` and `next` advances by `est * 60 / itpm` seconds; when off it returns at once.
  A call larger than the whole budget still runs. Retries do not reserve again; a refusal re-run
  is a second `_one` / `_one_text` call and does reserve again. One budget is shared by every
  model (the Opus and Sonnet limits are separate, so this is conservative), reservations are
  FIFO (large agentic digests can queue ahead of small calls), and output tokens per minute are
  not paced.
- `cli.py`: `JudgeOptions.itpm` (default 60_000_000; 0 = off), applied with `llm.set_itpm` in
  `judge` / `run` before any call. Not stamped in results.
- `digest.py`: remove `"summ_concurrency": "8"` (jailbreak_recognition) and `"4"`
  (agentic_misalignment) from `FAMILY_DEFAULTS`; their digests then run at the run's
  `concurrency` like every other family (`Settings.concurrency=None` -> `args.concurrency`), *and
  their `summ_timeout=1800`, `summ_fallback` and (agentic) `summ_max` / `summ_rare` defaults are
  retained*. `FAMILY_DEFAULT_KEYS` keeps `summ_concurrency`.

### 2a. A cross-process cap on calls in flight (`llm.py`; amended 2026-11-17)

Measured on the full bench (mlnla11-rl600, 29 families, one `wsbench judge` process each, 256
slots each): 10,523 calls failed after their retries with "would exceed your organization's rate
limit of 15,000,000 output tokens per minute". Output tokens cannot be paced up front (a call's
length is unknown), and per-process settings cannot see the other processes. So:

- `WSB_SLOTS=<dir>:<n>` (environment, read per call; unset = off, nothing changes): at most `n`
  API attempts in flight across every process that shares the directory. One attempt holds one
  `flock`ed slot file (`<dir>/<i>.slot`, random probes, jittered polling sleep through `_sleep`;
  the kernel frees a dead process's slots). The slot is taken inside the retry loop, after the
  rpm slot, around the API call only, in `_one` and `_one_text`. A malformed value is a
  `JudgeConfigError`.
- Not a CLI option and not stamped: it is an operator setting of the machine, like the key.
- Tests: off without the variable; two slots admit two holders and a third only after a release;
  a call waits for a slot, runs, and releases it; a bad value raises.

### 2c. `items=` under `--fast` is a partial run (amended 2026-11-17)

`--fast items=a,b` was a usage error (plan 0090). It now judges that part of the fast items (ids
outside `fast-v1` exit 2) and the result is always `complete=False` with
`extras.fast_items_subset`. Purpose: a slow family can be judged in parallel item groups that fill
the cache. Measured on real caches: a subset run of jailbreak, knowledge_cutoff and hinted_cutoff
made 0 new calls against the full run's cache, i.e. call keys do not depend on the item set.
Sanctioned test edit: `["items=t1"]` leaves `test_cli_fast_refused_combinations`' parameter list.
NOT done here: a full pass that replays such a cache exactly. `scripts/cache_only_run.py` over a
finished run's cache reproduced jailbreak exactly but scored 2 knowledge_cutoff items and agentic
differently, because calls that failed or were too long are not recorded in the cache and the
replay cannot re-ask them; that needs a change in `digest.py` and its own plan.

### 2b. Failed calls are reported loudly (`runner.py`); completeness is NOT changed

Known and pre-existing: a per-layer digest lost to a failed call (retries exhausted) leaves the
item in `col.partial`; it is digested and judged on its remaining layers and the row can still be
`complete=True`. `col.partial` also holds layers lost to the evidence check (`all_dropped`), which
is routine (58 of 1,530 existing summary results have such items, all complete), so the partial
counters cannot tell the two apart and this plan does not change the completeness rule (a
separate change would need a `failed_layers` record in `digest.py`). Instead:

- after each family, `judge` / `run` print one stderr line when the family's calls recorded
  errors (`<family>: N judge call(s) failed after retries; affected cells are unjudged or their
  items were digested on fewer layers`), using the error count the family's `Spend` / call
  metadata already tallies (`n_errors`; if a family exposes none, the line is omitted for it).
- the validation run's gate is 0 such lines.

### 3. `wsbench run wait=SECONDS` (`cli.py`, `runner.py`, `readouts.py`, `produce/producer.py`)

New `RunFamilies.wait` (float seconds, default 0 = today's behaviour) and `settle` (float seconds,
default 0 = a sidecar is required).

- With `wait > 0`, a family whose readouts are not ready is **pending**, not skipped. Ready
  families are submitted immediately; `run_families` then loops: every `POLL` seconds (module
  constant 2.0, a seam tests patch, as is the clock) it (i) collects finished futures, (ii)
  (implementation: `concurrent.futures.wait(in_flight, timeout=POLL,
  return_when=FIRST_COMPLETED)`, and an explicit sleep of `POLL` when nothing is in flight, never
  a busy loop) re-evaluates `readouts_path(readouts_root, name)` for each pending family (so legacy / reused
  keys count; the "reading legacy ..." line prints once, at submit) and submits the ones that
  became ready, (iii) stops waiting when nothing is pending, when `wait` seconds have passed since
  `run_families` started, or when the sentinel file `readouts_root/_READS_DONE` exists (the
  producer's "no more files are coming"; checked after (ii), so files that landed with it are
  still taken). It then waits for the in-flight families as today.
- **Ready** = the readouts file exists AND its sidecar `<file>.meta.json` exists, parses as a JSON
  object, and has `mtime >= ` the readouts file's mtime. With `settle > 0` a file without a
  sidecar whose mtime is at least `settle` seconds old is also ready (for sidecar-less producers;
  opt-in because a slow writer looks settled).
- `readouts.write_sidecar` becomes atomic (write `<name>.<pid>.tmp`, `os.replace`), so a reader
  never sees half a sidecar. `Producer.run_family` deletes an existing sidecar before it appends to a
  readouts file, and writes it again at the end, so a resumed file is not "ready" while it grows
  (after a crash the file stays sidecar-less until the next resume finishes; the `reads` guards
  are then report-only at `wait=0`, as for any sidecar-less file).
  The docs tell other producers: write the JSONL (ideally to a temporary name, then rename), then
  the sidecar, last; when copying files in, copy the sidecar last (a copy tool that does not
  preserve mtimes can otherwise leave the sidecar older than the file); delete a stale
  `_READS_DONE` before a new read starts (nothing in this repo writes or removes it).
- A family still pending when waiting stops is `skipped` with: `no readouts at <path> after
  waiting <wait>s` if the file does not exist, `readouts at <path> not ready after <wait>s (no
  current sidecar)` if it does (also when the sentinel ended the wait), or today's
  `no readouts at <path>` when the sentinel ended the wait and the file does not exist. `<wait>`
  is formatted `:g`. Exit code as for a skipped family today (0).
- Unexpected worker exceptions keep today's behaviour: the loop checks done futures each tick, and
  an exception re-raises at once after `cancel_futures` (pending families are dropped).
  `KeyboardInterrupt` during the poll sleep takes the existing path: pending and unstarted
  families become `skipped` ("interrupted"; the handler's `setdefault` is extended to pending
  families), in-flight ones finish their batch, exit 130.
- Order of checks under `wait > 0`: the `--fast` membership check stays first (a family outside
  the subset is skipped at once and never waited for; a fast bank failure is `failed`). The
  `anti_text_inversion` scope check runs when the family's file is ready, i.e. at submit time,
  exactly where it runs today relative to the file check (a stale ATI entry of a family whose file
  never lands stays `skipped`, not `failed`).
- Preflight: `needs_llm` and the digest preflight are computed over runnable + pending families
  before the first submit (a regex-scorer pending family gets only its digest preflight, as a
  runnable one does today); a failure still exits 3 before any call.
- Refused in `finalize` (`ValueError`): `wait > 0` with `dry_run=True` (prompts print one family
  at a time) and with `layers=each` (`_run_each` skips missing files itself and calls
  `run_families` per sub-run).
- Pool: created with `workers` computed over runnable + pending (`1 if dry_run` kept).
  Submission stays on `executor.submit`. The runner reads `getattr(args, "wait", 0)` and
  `getattr(args, "settle", 0)` (existing tests hand-build namespaces without them), as it does
  for `fast`.
- `run.json` gains top-level `wait` only when `wait > 0` (as `hb_method` is written only when
  set; `tests/test_runner.py:105` pins the exact key set of a default run) and, per family
  submitted late, `waited_s`; `summary.md` and
  the per-family lines are unchanged, outcomes stay in `specs` order, and with `json=True` the
  JSON payload stays the last stdout line. A late submit prints
  `<family>: readouts landed after <t>s`.
- `wait` composes with `--fast`, `anti_text_inversion`, `layers=<list>`, `reads=lite`.

### 4. Docs

- README Quickstart shared-keys paragraph (README.md:85) and `docs/producing_readouts.md` §4: the
  new defaults, `itpm=`, `wait=`, the ready rule, `_READS_DONE`, the one-command pattern (start the
  read, then `wsbench run --fast all=True readouts_root=DIR out=DIR wait=3600`; the reader writes
  each family's sidecar last and `_READS_DONE` at the end).
- `docs/summarizer.md` (:37, :95), `evals/agentic_misalignment/README.md` (:526, "summ_concurrency
  4") and `evals/jailbreak_recognition/README.md` (:151, "summ_concurrency=8"): the caps are gone,
  token pacing guards instead; the failed-call completeness rule.
- `CLAUDE.md`: :32 ("default 240" becomes "library default 240; CLI default 30000"), :615 (`family_workers=3`), plus one paragraph (defaults,
  `itpm`, `wait`, ready rule, 2b).

## Tests (`tests/test_run_wait.py`, `tests/test_token_pacer.py`, plus edits)

Pre-existing assertions this plan changes, and only these:
- `tests/test_cli.py:362`: help text `family_workers=3` -> `family_workers=8`.
- `tests/test_cli.py:123`: `r.config["concurrency"] == 64 and r.config["rpm"] == 240.0` ->
  `256` / `30000.0`.
- `tests/test_jailbreak_recognition.py:1171-1175`: the `FAMILY_DEFAULTS["jailbreak_recognition"]`
  dict loses `"summ_concurrency": "8"` (timeout and fallback entries stay).
- `tests/conftest.py`: the autouse `_reset_pacer` fixture also calls `llm.set_itpm(0)` and
  `llm._TOKEN_PACER.reset()` before and after each test (a fixture addition, no assertion change;
  `main([...])` in one test would otherwise leave the 60M budget on for the next).
Any other pre-existing test that fails is a bug in the implementation, not a stale test.

New:
- Defaults: 256 / 30000 / `family_workers` 0 / `itpm` 60_000_000 / `wait` 0 / `settle` 0.
- `digest.settings(args, "jailbreak_recognition").concurrency is None`, same for agentic; timeout
  1800 and fallback retained; `opts=summ_concurrency=5` still gives 5.
- Replay: judge a jailbreak stub and an agentic stub with `opts=summ_concurrency=8` at
  `concurrency=64`, then again into the same `out=` at the new defaults; the second run makes 0
  new calls (`FakeLLM` call log) and the results are equal apart from `config.concurrency` /
  `config.rpm` / `config.summarizer.concurrency`.
- Token pacer: off by default (no delay); with `set_itpm(600)` three calls of an estimated 10
  tokens are spaced 1 s apart (patched `_sleep` / clock); thread-safe reserve; one reservation per
  call across retries; a call above the budget still runs; `set_itpm(0)` restores off (fixture
  resets it).
- 2b: a family whose calls recorded errors prints the stderr line; one without errors prints
  nothing; `complete` is whatever it was.
- `write_sidecar` leaves no `.tmp` and replaces atomically; `run_family` removes a stale sidecar
  before appending (producer test with the existing fake backend, if one exists; else a unit test
  of the helper it calls).
- `wait` (fixtures write a sidecar unless the case says otherwise; clock and `POLL` patched; no
  real sleep, no network): (a) file + sidecar present at start -> judged, no waiting; (b) file and
  sidecar appear after two polls -> judged, late line, `waited_s` in run.json; (c) file without
  sidecar: pending forever under `settle=0`, ready under `settle=20` once old enough; sidecar
  older than the file is not ready; (d) never appears -> skipped, "after waiting" message, exit 0;
  file without sidecar at the deadline -> the "not ready" message; (e) `wait=0` -> pre-0092
  messages and order byte for byte (including a stale ATI entry with a missing file = skipped);
  (f) not-in-fast family under `--fast wait=...` skipped immediately; (g) `dry_run=True wait=5`
  and `layers=each wait=5` -> `ValueError`; (h) outcomes in `specs` order when families finish out
  of order; (i) preflight covers a pending family's judge and digest models before any submit;
  (j) `_READS_DONE` ends the wait at once, pending families skipped with today's message, a file
  that landed together with it is still judged; (k) a worker exception while another family is
  pending propagates and the pending one is not submitted; (l) `family_workers=0` runs all
  families concurrently, `family_workers=2` caps at 2.

## Files

```
src/wsbench/cli.py                  defaults, itpm, wait / settle, fd limit
src/wsbench/runner.py               pending families, polling, ready rule, 2b
src/wsbench/llm.py                  token pacer
src/wsbench/digest.py               drop two summ_concurrency family defaults
src/wsbench/readouts.py             atomic write_sidecar
src/wsbench/produce/producer.py     stale sidecar removed on resume
tests/test_run_wait.py, tests/test_token_pacer.py    new
tests/test_cli.py, tests/test_jailbreak_recognition.py    the three sanctioned edits
tests/conftest.py                   pacer fixture resets the token pacer
README.md, docs/producing_readouts.md, docs/summarizer.md, CLAUDE.md,
evals/agentic_misalignment/README.md, evals/jailbreak_recognition/README.md
plans/0092-fast-run.md
```

## Validation before merge

`uv run ruff check`, `uv run ruff format --check`, `uv run pytest -q`. Then on real readouts of one
arm (mlnla11-rl600, full-position files of all 30 families), in tmux, one in-process
`wsbench run all=True` at the new defaults into a fresh `out=`:
- gate: 0 failed-call lines (2b), every row `complete` as in the reference
  run of the same readouts (qmain), undecided counts not above the reference's by more than
  judge-noise (reported per family), values within the run-to-run noise already measured;
- report: wall-clock per family and total, peak RSS, 429 retry counts.
If the gate fails on agentic or jailbreak, lower `itpm` and re-run; if it still fails, restore a
bounded family default (`summ_concurrency` 32, the value three full in-house arms ran at) and
record why. The same run with `--fast` gives the fast-subset judge time.

## 5. `run` judges one process per family (amended 2026-11-17, revised after review)

Why: the in-process validation failed. One `wsbench run all=True` of the full bench at the new
defaults (8 families at a time, 256 slots each) lost hundreds of calls to
`APIConnectionError [ReadError / ConnectError]` within 17 minutes; a `run` is one Python process
on one core. One `wsbench judge` process per family at the same settings (with `WSB_SLOTS`) lost
none. So `run` spawns a child per family. This supersedes three statements above: "the
process-wide pacer bounds the whole run" (true per process; across children the shared pacer
below does it), "process-per-family judging is a follow-up" (§1), and `WSB_SLOTS` "unset = off"
(§2a: still true for `judge`; `run` in process mode sets one). With `wait=0` the families'
results, messages, outcomes and exit codes are as before; stdout interleaving and the number of
preflight calls (each child preflights its own judge and digest model again, one or two tiny
calls per family) differ.

### Mode switch
- `RunFamilies.procs` (tri-state): the explicit key wins, else env `WSB_RUN_PROCS` (`0` / `1`),
  else ON. Forced off in `RunFamilies.finalize` under `dry_run=True` and `layers=each`
  (`_run_each` copies the config before calling `run_families`).
- `runner.run_families` uses processes only when `getattr(args, "procs", False)` is true AND its
  `env` parameter is None (a caller-supplied env mapping keeps threads), so hand-built namespaces
  keep threads.
- `tests/conftest.py`: an autouse fixture sets `WSB_RUN_PROCS=0` (21 test files call
  `main(["run", ...])` against families registered or patched in-process). A fixture addition, no
  assertion change.

### Supervisor (`runner.py`)
- The `ThreadPoolExecutor` loop stays; in process mode it submits `_one_proc` in place of `_one`
  with the same `dest` the loop already computes (so `out_of` is honoured). `_one_proc` checks a
  stop flag, spawns the child, waits for it, and returns the `FamilyOutcome`. Pending / `wait=`
  logic, `specs` order, `waited_s` and the exit-code rule (130 > 3 > 2 > 0) are unchanged.
- Parent-side checks stay in the parent, in today's order: fast membership, the readiness /
  missing-file check, the ATI scope check, `_seed_preflights` (a failure exits 3 before any
  spawn).
- `family_workers` stays "families at once" (default 8; 0 = all; fix the comment at its
  declaration). The parent flushes its stdout before each spawn and before the final JSON
  payload.

### Child
- Command: `[sys.executable, "-m", "wsbench", "judge", "family=<name>", "readouts=<found path>",
  "out=<dest>", "outcome=<dest>/outcome.json", "concurrency=<n>", "rpm=<x>", "itpm=<n>"]` plus,
  when set: `judge_model`, `layers`, `items`, `limit`, `allow_missing`, `anti_text_inversion`,
  `ati_variant`, `ati_opt_in`, `fast=True`, and `opts=",".join(args.opt)` (`args.opt` already
  carries `reads=` / `sampling=`). Never forwarded: `all`, `families`, `readouts_root`,
  `family_workers`, `wait`, `settle`, `json`, `hb_method`, `include_superseded`, `dry_run`,
  `procs`. A spawn seam (`runner._spawn(cmd, env) -> Popen-like`) lets tests fake it.
- Child env: the parent's environment plus `PYTHONUNBUFFERED=1`, `WSB_SLOTS` and `WSB_PACER`
  (below), passed through `env=` only; the parent never mutates `os.environ`. stdout / stderr are
  inherited.
- New `judge` key `outcome=PATH` (it shows in `--help`; documented as "written for `run`"). With
  it, `JudgeFamily.execute` runs option parsing, judge resolution and the family inside the same
  fail-soft function `run` uses (`runner._one`), atomically writes `{family, status, error,
  exit_code}` to PATH, and exits with that `exit_code` (0 / 2 / 3). Without `outcome=`, `judge`
  is untouched.
- Parent: deletes a stale outcome file before spawning and deletes it again after reading. An
  outcome with `status == "ok"` loads `results.read_results(dest)` into the `FamilyOutcome` (an
  unreadable `results.json` then raises). No outcome file: exit 2 or 3 -> failed with that code,
  error `judge process exited <code>`; a negative return code -> failed, exit code 2, error
  `judge process killed by signal <N>` (one OOM-killed family must not discard the others); any
  other exit (an uncaught traceback, exit 1) -> terminate the other children and raise, today's
  "other exceptions propagate".
- `run.json` gains no key (`tests/test_runner.py:105` pins the set).

### Interrupts and cleanup
- Children start in their own session (`start_new_session=True`) and, on Linux, set
  `PR_SET_PDEATHSIG(SIGTERM)` (best effort) so they die with the parent.
- First `KeyboardInterrupt`: set the stop flag (no new spawn; a future that has started but not
  spawned returns `skipped ("interrupted")`), wait for in-flight children to finish, exit 130.
  A second `KeyboardInterrupt` during that wait: terminate (`killpg`) every tracked child, mark
  them `skipped ("interrupted")`, exit 130.
- The parent installs SIGTERM / SIGHUP handlers for the duration of the run that raise into the
  same cleanup; a `finally` kills every tracked child still alive and restores the handlers.

### Budgets across the children
- The parent creates a fresh local directory `tempfile.mkdtemp(prefix="wsb-run-")` (never under
  `out`: that is often a network volume, and a results directory must not hold 1,500 lock files)
  with `slots/` and `pacer/` inside, removed in the `finally`. Before spawning it probes `flock`
  once there; a failure exits 3 with a clear message.
- `WSB_SLOTS`: a value already in the environment is inherited as is; else
  `<tmp>/slots:<runner.RUN_SLOTS>` with `RUN_SLOTS = 1500` (account-specific: about what a 15M
  output-tokens-a-minute limit carries; with 8 x 256 = 2,048 requested slots the cap is meant to
  bind).
- `rpm` / `itpm` stay budgets of the whole run: the parent sets `WSB_PACER=<tmp>/pacer`. When the
  variable is set, `_Pacer.reserve` and `_TokenPacer.reserve` keep `next` in one small file each
  there: one fd kept open per process and pacer, the existing `threading.Lock` held together
  with an exclusive `flock`, `pread` / `pwrite`, no fsync, nothing awaited inside; an empty or
  torn file reads as 0; `reset()` truncates the file. The clock stays `llm._now()`
  (`time.monotonic`: system-wide on Linux, so comparable across the run's processes, and the seam
  the pacer tests patch). `_pace(rpm)` keeps its one-argument signature. Without the variable the
  pacers are in-memory exactly as before.

### Tests (`tests/test_run_procs.py`)
With the spawn seam faked (no real subprocess, no network): the built argv parsed back through
`JudgeFamily` gives the same field values as the run's (every forwarded key), and holds none of
the non-forwarded ones; outcome mapping for ok / failed 2 / failed 3 / no outcome file with exit
2 / killed by a signal (failed, others unaffected) / exit 1 (raises, others terminated) / ok
with unreadable results (raises); a stale `outcome.json` is ignored; `specs` order; `wait=` late
submit in process mode; first interrupt = 130 after waiting, second interrupt terminates the
children; SIGTERM runs the cleanup; `dry_run=True`, `layers=each` and a caller `env` force
threads; `WSB_RUN_PROCS=0` and `procs=False` force threads, `procs=True` beats the env; the
temporary directory is removed; a failing `flock` probe exits 3; an inherited `WSB_SLOTS` is not
replaced. `judge outcome=` writes the file and exits with its code for an ok family, a
`SystemExit` family, a `JudgeConfigError` family and a bad `opts=`.
One real-subprocess smoke, offline: `run families=typo_mt readouts_root=examples/readouts
out=TMP opts=aggregate=native allow_missing=True procs=True` with the API-key variables removed
from the child env (verified by the reviewer: exit 0, `pass_rate=0.5 n=85`); its `results.json`
bytes equal those of `judge` with the same arguments; use `capfd`.
Shared pacer: two reservers on one `WSB_PACER` directory are spaced by the budget (patched
clock); a torn file reads as 0; unset = in-memory as before.

### Docs and files added by this section
README Quickstart paragraph, `docs/producing_readouts.md` §4 and the CLAUDE.md Driver paragraph
(process mode, `procs=`, `WSB_RUN_PROCS`, the run-private slots / pacer directory, children
preflight again); `tests/test_run_procs.py`; the `tests/conftest.py` fixture.

### Validation before merge (replaces the in-process gate above)
`wsbench run all=True` (process mode, defaults) on the mlnla11-rl600 full readouts: 0
connection-error or rate-limit lines, failed-call lines only of the `max_tokens` kind, every row
`complete` as in the per-family-process reference run of 2026-11-17, wall-clock reported.
