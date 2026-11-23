# Plan 0113: the adapted sets' directed_modulation banks on bank v2

Camila (issue #547): regular directed modulation is "just regular, not 'don't think'"; "the 17
adapted sets should have the dont think dm change". Plan 0109 moved the registered bank to
`items_v2.json` and left the adapted sets on the first bank. This plan re-derives the family's
bank in every set under `adapted/` from bank v2, with the adapt tooling as it is (no code
change).

## What the tooling does now that `store.original_bank` returns bank v2

- `adapt freeze families=directed_modulation` keeps only `original` rows whose id the registered
  bank has (`run.registered_rows`), so every `dm-pair-NN-neg` item leaves the set; each kept
  item is the registered item with its recorded gate, unchanged. The header is bank v2's
  (`version: 2`), so a result under `WSB_BANK_ROOT` stamps `dm-2026-10-31+expressed+bank-v2`.
  The header's `gate` / `counts` / `removed_items` text is the registered bank's (Qwen3.6-27B),
  as for every adapted bank; the set's own counts are in `report.json`.
- That first freeze is a drop-only step, so `report.json` records a `plan_lineage` step (the
  set's existing readouts judge at that commit, dropped ids' cells removed).
- `adapt profile families=directed_modulation ids=<the 37 dm-think-NN>` gates the new registered
  items on the subject with the family's compliance gate (the reply is the carrier word for word
  and never names the concept; greedy AND >= 8/10 at T 0.7); a second freeze adds the ones that
  pass. That step adds items, so it records no lineage: readouts need the new items read.
- Target 102 (the registered size). The family has no Brief and no refill route (`refill.POLICY`
  / `FILL_POLICY`), so a set short of 102 ships short with status `untried`, as before.
- In the 13 sets with a surviving gate log no think item whose twin had failed comes back: the
  failing member of every dropped pair (107 pairs) is the think item. That is not on record for
  the four seeded sets (next section).
- Side effects of any freeze on main today: the report's `code` stamp moves, and registered
  families a set lacks get their `absent` entry (`user_modeling_hard` everywhere; nine more on
  olmo-3.1-32b, whose copy on main is still the pre-rebuild set).

## Gate logs

`gate/` is git-ignored. The run trees' logs were used for 13 sets (they reproduce the shipped
banks exactly: ids and rates). For gemma-4-31b-it, glm-5.3-flash, qwen3.6-35b-a3b and
deepseek-v4-flash no log survives on the box; their logs were seeded from the bank shipped at
5a5d8376 (each shipped item with its recorded `adapt.gate`, marked `seeded_from`; not re-run on
the subject), which is all a freeze reads for this family. Each of those four reports says so
in the family's note, and its `n_original_gated` counts log rows, seeded ones included.

A seeded log has no row for an original the set had not shipped. Six registered think items were
in that state (a member of their pair had failed; which one was not on record), so they were
gated afresh on their subjects (`adapt profile ids=...`, audit follow-up):

| set | id | greedy | rate | outcome |
|---|---|---|---|---|
| deepseek-v4-flash | dm-pair-23-pos | wrong | 0.0 | fails |
| glm-5.3-flash | dm-pair-03-pos | right | 0.9 | passes, ships |
| glm-5.3-flash | dm-pair-19-pos | right | 0.0 | fails |
| glm-5.3-flash | dm-pair-23-pos | wrong | 0.4 | fails |
| qwen3.6-35b-a3b | dm-pair-04-pos | right | 0.7 | fails |
| qwen3.6-35b-a3b | dm-pair-13-pos | right | 0.9 | passes, ships |

gemma-4-31b-it shipped every registered original, so it had none.

## Result (2026-11-23)

| set | dont_think removed | new think passed / 37 | think (kept + new) | secret | preference | items / 102 | status | po-opus floor (n) |
|---|---|---|---|---|---|---|---|---|
| deepseek-v4-flash | 34 | 36 | 70 (34 + 36) | 15 | 15 | 100 | untried | 1.000 (100) |
| deepseek-v4-pro | 27 | 32 | 59 (27 + 32) | 15 | 15 | 89 | untried | 1.000 (89) |
| dory-4b | 12 | 15 | 27 (12 + 15) | 9 | 15 | 51 | untried | 1.000 (51) |
| gemma-4-31b-it | 35 | 37 | 72 (35 + 37) | 15 | 15 | 102 | full | 1.000 (102) |
| glm-5.3 | 35 | 37 | 72 (35 + 37) | 15 | 15 | 102 | full | 1.000 (102) |
| glm-5.3-flash | 32 | 36 | 69 (33 + 36) | 15 | 15 | 99 | untried | 1.000 (99) |
| kimi-k2 | 21 | 23 | 44 (21 + 23) | 15 | 15 | 74 | untried | 1.000 (74) |
| kimi-k3 | 35 | 37 | 72 (35 + 37) | 15 | 15 | 102 | full | 1.000 (102) |
| muse-spark-open | 35 | 37 | 72 (35 + 37) | 15 | 15 | 102 | full | 1.000 (102) |
| olmo-3-7b | 10 | 9 | 19 (10 + 9) | 15 | 12 | 46 | untried | 1.000 (46) |
| olmo-3.1-32b | 31 | 34 | 65 (31 + 34) | 15 | 15 | 95 | untried | 1.000 (95) |
| qwen3-8b | 32 | 35 | 67 (32 + 35) | 15 | 15 | 97 | untried | 1.000 (97) |
| qwen3.5-0.8b | 28 | 31 | 59 (28 + 31) | 11 | 15 | 85 | untried | 1.000 (85) |
| qwen3.5-2b | 15 | 22 | 37 (15 + 22) | 12 | 15 | 64 | untried | 1.000 (64) |
| qwen3.5-4b | 32 | 35 | 67 (32 + 35) | 15 | 15 | 97 | untried | 1.000 (97) |
| qwen3.5-9b | 35 | 37 | 72 (35 + 37) | 15 | 15 | 102 | full | 1.000 (102) |
| qwen3.6-35b-a3b | 33 | 36 | 70 (34 + 36) | 15 | 15 | 100 | untried | 1.000 (100) |

Not screened: plan 0075's D1-D7 rules do not cover the family (no option list frozen in the
bank, not a lucky-run family). Floors: the po-opus-v1 summary prompt-only floor of the family
was re-measured on every set (saturated at 1.000 everywhere, no Opus refusal). The new entries
are on the reply-free prompt-only input and carry `prompt_cut: reply-free-v2` (plan 0070); the
entries they replace were measured before that cut on 15 sets and carried no `prompt_cut`.
Each entry keeps the digest fallback mode its set had for the family on main (`none` on 15
sets, `default+claude-sonnet-5-5` on dory-4b, re-judged from the same readouts to match;
olmo-3.1-32b had no entry and takes the family default `none`); `adapt floors` excludes the family, so there is no stock-subject-v1 entry to redo,
and the `stock-subject (legacy, pre-summary-mode)` entries of the old banks stay as records.
A one-family po-opus `wsbench freeze` rewrites the floors file's `_source` and drops entries
without a po-opus `protocol` stamp; those were restored from git, so each floors file differs
only in the family's entry (olmo-3.1-32b: its legacy `floors.json` was migrated to the
`protocols` layout by the tool and gained its first `prompt_only_summary.json`).

ATI: no set's `anti_text_inversion*.json` has an entry for the family; no ATI file changed.

## Not in this plan

- The judge / digest prompt wording that still names the "suppress" / "not to think" case
  (#547): unchanged.
- inkling-2-mini: no `adapted/inkling-2-mini/` directory is on main yet (only the subject's code,
  #544). Its set is built from main after plan 0109, so it starts on bank v2.
- The olmo-3.1-32b rebuild that is not on main yet: it must carry this bank when it lands.
- Lens readouts and results of the sets: the 9 to 38 added items per set need reading.
