# 0093: a rerun over a cache with halved digests must equal the first pass

Issue #491.

## Problem

`digest._collapse_hierarchical` halves a per-layer digest that is refused or too long, level by
level, up to `MAX_HALVINGS`. The best chunk claims seen at any level live in memory only
(`fallback` / `remember`); only the latest level is persisted (`bump` writes the
`<stem>|level` row). A rerun reads that row and starts the item there:

- an item out of halvings (persisted level 3) is skipped by `if k > MAX_HALVINGS: continue`, its
  `fallback` stays empty, and it ends in `col.unsummarized` with reason `refused`
  (`persisted_kind`), although the first pass judged it on its chunk digests
  (`direct[i] = fallback[i]`);
- an item persisted at level 1 or 2 loses the claims of the levels below.

So a rerun over a finished cache, online or offline, can score items differently from the run
that wrote the cache. Measured on a real fast-subset run (s3d-rl600, 2026-11-17, cache-only
replay): knowledge_cutoff had 19 level rows (7 / 6 / 6 at halvings 1 / 2 / 3); `cs01615` lost
layer 24 from its stage-2 input (new fingerprint, uncached) and `kc2_02377` went from 1 refused
layer of 11 to 5 (over `PARTIAL_UNDECIDED_SHARE`, undecided); agentic_misalignment lost pair
`t-power-acquire-credentials`. jailbreak_recognition, with no level rows, replayed exactly. An
in-memory emulation of the fix below (level rows dropped, every uncached stage-1 call answered
as a refusal) reproduced both families' rows, values, `complete` and `counts` exactly.

## Change (`src/wsbench/digest.py`, `_collapse_hierarchical` only)

On a run that finds a persisted level row for an item, the level walk restarts at level 0 and
REPLAYS every level below the persisted one from the cache, without sending anything:

- **The level row is authoritative: every level j below the persisted one ended in a bump.** A
  replayed level is read-only: no call, no level row, and no all-dropped invalidation
  `cache.put`. A call counts as served only if `_cached(...)` returns a row. Anything else (no
  row, a `result: None` row including an `all_dropped` invalidation, a stale-fallback row) is the
  refused / too-long marker of the persisted kind (the newest level row's kind is used for every
  replayed level; refused and too-long share every branch and only the last `bump` kind reaches
  `reasons`, so that is enough). After collecting the served chunk claims, the replayed level
  calls `remember` exactly as a bumping level does (`refused=True` with the lost layers at the
  chunk stage; `remember(chunk_claims, [])` if every chunk is served) and advances `level[i]`
  unconditionally. It never sets `final[i]`, `done`, `col.empty` or `col.chunks` at a replayed
  level, even when a final or single row is present (a cache written by several passes can hold a
  failed row at a level a later pass bumped past: reading it as `None` would end the item
  there).
- the walk therefore rebuilds `fallback` / `remember` exactly as the first pass did, then
  continues at the persisted level with today's behaviour (calls not cached there are sent);
- `bump` writes the level row only when the new level exceeds the persisted one (a rerun
  appends no rows; a first pass writes exactly today's rows);
- `n_fallback_events` and the other counters are whatever the replayed walk counts (so
  `n_fallback_events` becomes rerun-stable); call counters (`n_chunk_calls`) still count calls
  SENT, as today.

## Invariants (restated at the point of modification)

- No prompt, fingerprint, cache key or `prompt_version` changes; a FIRST pass (no level rows) is
  byte-identical to today, including the rows it writes and the calls it sends, in order.
- Cache rows stay append-only; a rerun over an unchanged cache and store writes no row and sends
  no call at a past level (with a `summ_store`, an out dir that had adopted only the level row
  adopts the past-level chunk rows once on its first run after the fix: expected) (`tests/test_digest_store.py` pins the row count on rerun,
  `tests/test_digest_hierarchical.py` pins "nothing re-sent").
- The `summ_store` path, which adopts only the newest level row, keeps working with one level row
  per stem.
- Refused and too-long keep sharing their branch; only the last kind reaches `reasons`.
- Never drop `SERVED_VIA` when a served row is re-read.

## Tests (`tests/test_digest_hierarchical.py`, additions only)

No pre-existing assertion changes. New, on the existing `FakeLLM` fixtures (pin
`summ_layers=joint` where the file already does):
- rerun equals first pass (same `Collapse` outcome per item: digest text / claims, `reasons`,
  `unsummarized`, `partial`) after: a refused final at level 2; a refused chunk at levels 1 and 2;
  refusal at every level (out of halvings: the item is judged on its remembered chunk claims on
  BOTH passes);
- the rerun sends no call and appends no cache row in each of those cases;
- a too-long outcome at level 0 followed by a served level 1 reruns identically;
- `n_fallback_events` equal on both passes;
- with a `summ_store`, the same rerun equality.
Add the rerun assertion to the scenario of `test_refused_final_moves_down_a_level` as a NEW test.
Also:
- a failed-then-refused history: run 1 the single call fails (a `None` row), run 2 the same call
  is refused and level 1 serves; run 3 equals run 2, sends nothing, appends nothing; the same
  with a failed chunk at level 0;
- an item that ends chunk-direct at persisted level 1 or 2 through a failed chunk, where the
  level below holds the better `fallback`;
- one `summ_layers=union` rerun-equality test with a refused layer part (the real failure shape),
  asserting `partial`, `refused_layers` and `served_by`;
- a fresh out dir adopting a level-3 stem from a `summ_store` equals a storeless fresh run.
Mark in each new test's docstring whether it fails on main (the refused-final rerun, the
out-of-halvings rerun, the union one must; "too-long at level 0 then served level 1" is a guard
that passes on main). Update the docstring of `_collapse_hierarchical` and the "rerun-stable"
comment near the unsummarized branch.

## Validation before merge

`uv run --extra dev ruff check .`, `ruff format --check .`, `pytest -q`. Then offline, on the
real caches of `/dev/shm/wsb-val/s3d-fast-e2e2/judged/{knowledge_cutoff,agentic_misalignment,
jailbreak_recognition}` (copies; `scripts/cache_only_run.py ... --fast opts=aggregate=summary
layers=20,...,60`): the result rows, value, `complete` and `counts` equal the stored
`results.json` for all three (today: knowledge_cutoff and agentic differ), and each copied
`cells.jsonl` has the same number of lines after the replay as before (offline, any digest call
that is sent writes a `None` row, so an unchanged count proves nothing was sent).

## Files

```
src/wsbench/digest.py                 _collapse_hierarchical: replay past levels on a rerun
tests/test_digest_hierarchical.py     new rerun tests
docs/summarizer.md                    one paragraph: reruns replay the halving levels
plans/0093-digest-rerun-levels.md
```
