# Running the judge: options, throughput and waiting on a producer

Reference for `wsbench judge` and `wsbench run`. The short version is in the [README](../README.md#run-it).

Output layout: `<out>/<family>/results.json` (the result) and `cells.jsonl` (every judge
verdict, so a re-run only pays for what is missing); `<out>/summary.md` (the table) and
`run.json` (per-family status and spend). Shared keys on `judge` and `run`: `layers=20,36`,
`items=a,b`, `limit=N`, `allow_missing=True`, `dry_run=True`, `judge_model=`, `judge_effort=`, `concurrency=`,
`rpm=`, `itpm=`, `opts=k=v`, `anti_text_inversion=True` (judge each family only on the items that
every panel reader (Qwen3.6-27B, Opus 5.5, GPT-6 Astra, Gemini 4 Argon) fails to answer from
the prompt alone; see [Baselines](baselines.md)); `--help` prints a command's
keys, `--show` the resolved config.

Throughput defaults of `judge` and `run` (plan 0092): `concurrency=256` calls in flight per
family, `rpm=30000` requests a minute and `itpm=60000000` estimated input tokens a minute, the
last two shared by the whole run (`itpm=0` turns the token budget off; a call is estimated at
its prompt's characters / 3 and is never refused for its size). `run` judges eight families at a time (`family_workers=8`; `family_workers=0` = all at once, `N` caps it). None of these
enters a cache key, a prompt version or a score; `concurrency` and `rpm` are recorded in
`config`. On a rate-limited key lower `rpm=` first, then `itpm=`, then `concurrency=`. Both
commands raise the process's soft open-file limit to the hard limit (at most 65536). When calls
of a family fail after their retries, one stderr line says how many
(`<family>: N judge call(s) failed after retries; ...`); a rerun into the same `out=` asks only
those again.

`run` judges each family in its own `wsbench judge` process (`procs=True`, the default;
`procs=False` or `WSB_RUN_PROCS=0` judges them in threads of one process, as do `dry_run=True` and
`layers=each`). One Python process is one CPU core, and eight families at `concurrency=256` in one
process dropped connections (2026-11-17). The run checks the files and the ATI / `--fast` scope
and preflights each judge model itself, then starts the processes; each one preflights its own
models again (one or two tiny calls per family) and prints its own lines, so the families' output
interleaves. `rpm=` and `itpm=` stay budgets of the whole run, and at most 1,500 API calls are in
flight across the processes (`WSB_SLOTS=<dir>:<n>` in the environment replaces that cap): the run
keeps the lock files for this in a private directory under the system temporary directory, which
must be on a local disk that supports `flock`, and removes it at the end. Ctrl-C lets the running
families finish and exits 130; a second Ctrl-C terminates them.

`run wait=SECONDS` judges while a producer is still writing: a family whose readouts are not
ready is waited for instead of skipped, and is judged as soon as they are. Ready means the
file exists and its sidecar `<family>.jsonl.meta.json` exists, parses as a JSON object and is
not older than the file, so a producer writes the sidecar last. `run` looks every 2 s and stops
waiting when no family is pending, after `SECONDS`, or when `readouts_root/_READS_DONE` exists
(the producer's "no more files are coming"); families still pending are then skipped. One
command for a read in progress:
`wsbench run --fast all=True readouts_root=DIR out=DIR wait=3600`
(`docs/producing_readouts.md` §4 has the rules for producers, and `settle=` for files without
a sidecar). `wait=` is refused with `dry_run=True` and with `layers=each`.

**`all` means every family except a superseded or retired one** (the full tier; `run --full` is
`run all=True`, and `plan --full` is `plan families=all`). `run all=True`, `plan families=all`
and the `families=all` default of `capable`, `baseline` and `text-inversion` skip `typo_st`
(superseded by `typo`, plan 0033: Camila 2026-10-30, "just keep the hard version";
`multihop_mt_regex`, the former example, was removed on 2026-10-30, plan 0041) and any family
in `registry.RETIRED_FAMILIES` (none today; plan 0058); name one (`families=typo_st`) or pass
`run all=True include_superseded=True` to run it anyway. Their banks stay frozen in `evals/`.
`medical_diagnosis` and `medical_diagnosis_alt` were removed on 2026-10-31 (Camila, plan 0058),
and `unverbalized_hint` (retired 2026-10-31 by plan 0058) on 2026-11-07 (Camila, plan 0081).

Renamed and removed evals, and the keys older files may use: [history.md](history.md).
