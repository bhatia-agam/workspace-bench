# 0070: the prompt-only control never reads a reply

Issue #349. Rule (Camila, 2026-11-04): "can you ensure that our control is NEVER reading a
reply, only ever the prompt?"

## Problem

`prompt_only_opus.build` decodes each item's render through its LAST full-read site. In six
registered families that site lies inside assistant-turn text, so the Opus prompt-only reader was
shown a reply (Qwen's own, a bench prefill in Qwen's mouth, or an earlier assistant turn):

| family | ids | reply text before the site |
|---|---|---|
| basic_readout | 100 / 100 | the prefilled answer stem "My one-word answer is:" (6 tokens) |
| directed_modulation | 100 / 100 | the dictated sentence, prefilled (8–9 tokens) |
| model_specific_directed_modulation | 98 / 98 | the same (8–9 tokens) |
| multi_concept_directed_modulation | 116 / 116 | the target sentence, prefilled (12 tokens) |
| introspection | 508 / 1762 | the protocol's earlier assistant turn |
| jailbreak_recognition | 29 / 172 | earlier assistant turns of multi-turn conversations (up to 944 tokens) |

Counts come from a box audit of the frozen prompts (string-level, Qwen markup); the token-level
detector below reproduces exactly the same id sets on every registered family (and finds no reply
in hinted_cutoff, fixed by plan 0064). Every other family's prefix is byte-identical under the new
cut, so its floor stays valid as frozen.

## Change

1. **`baselines/prompt_cut.py`** (new): token-level, template-agnostic.
   - `turn_marks(tok)` probes the subject tokenizer's own chat template, with thinking off as
     every chat render is built: one-, two- and three-turn renders give the assistant `header`,
     the fixed rest of the generation prompt (`think`: Qwen's empty think block, may be empty),
     the assistant `end` marker (may be empty, e.g. GLM) and the `user` turn header. It calls
     `apply_chat_template` rather than checking `chat_template` (Kimi-K3's remote-code tokenizer
     has none but overrides the method); a failing call, or shorter renders that are not
     prefixes of the longer ones, exits loudly (SystemExit) rather than guess. When the user
     header found by the common-suffix rule starts with the user turn's own closing tokens (a
     default system turn precedes the probe in OLMo / Muse), those move to `end`, so dropping a
     turn leaves no orphan end marker.
   - `assistant_turns` / `reply_tokens`: assistant turns in token ids; a turn holds reply text
     when any token after its header (and after the fixed think block) up to its end marker /
     the next turn decodes to non-whitespace. A control / added token inside that text means
     another turn sits there (a system or tool turn under a template with no end marker, e.g.
     GLM): exit loudly rather than over- or under-cut.
   - `prompt_only_ids(ids, last, marks, tok)`: unchanged (`ids[: last + 1]`) when no assistant
     turn before the cut holds text; else every such turn is dropped whole and, when the site
     lies inside one, the prefix ends at its generation prompt (header + fixed think block),
     i.e. exactly where the prompt ends. Same rule as the box fix that produced the leak-free
     single-guess control.
   - `assert_no_reply`: raises if reply tokens remain.
2. **`prompt_only_opus.build`**: chat and captured renders go through `prompt_only_ids` +
   `assert_no_reply`; `plain` / `bare` renders have no template and no assistant turn, and keep
   the old cut (marks are only probed when a chat render is met, so a raw-only adapted set never
   needs a template). Each row is stamped `prompt_cut: "reply-free-v2"`. `token` (what the
   question quotes as "the final token of the text below") is the cut prefix's own last token;
   `pos` and the new `site_token` stay the read site's and place the readout cell where the
   lens's last cell is. (v1 quoted the read-site token, which for the 922 rows cut inside a
   reply was a reply token, e.g. basic_readout's ':' and the DM sentences' '.'; review of #350.)
3. **Guards**: `ask`, `write_readouts`, `ask_fallback` and `write_fallback_readouts` exit when any
   prompt row lacks the current `prompt_cut` stamp (a stale prompts file may hold reply text).
   Answers are keyed by `prompt_sha` of the exact question (`reader_prompt`), as
   `adapt.poetry._latest` does: an answer to an older prompt is never a cache hit in `ask` /
   `fallback_ask` and never served by `write_readouts` / `primary` / `write_fallback_readouts`.
   `run_config.json` of both readout stages records `prompt_cut`; `freeze` refuses any
   `po-opus-v1*` run config without the current stamp, and the legacy
   `po-opus-v1+sonnet5-fallback` run outright (its 2026-10-31 inputs held reply text; before
   reading anything) and copies it onto each frozen entry. `source=` is optional: without it
   (or with another reader's config) `freeze` cannot check the cut, so it freezes as before
   but refuses to replace an entry of the destination that carries `prompt_cut`
   (`_never_downgrade`; review of the port, 2026-11-17). The pre-existing test fixtures that
   hand-write prompt rows, answers and run configs gain the stamp / `prompt_sha` (sanctioned
   here: the guards are new; no assertion changes).
3b. **Adapted poetry gate** (`adapt.poetry.read_prefix`): a `chat_prefill` item's po-opus-v1
   input had the couplet's first line in the assistant's mouth; it now stops at the generation
   prompt. Cached adapted answers no longer match by `prompt_sha`; re-measuring the adapted
   poetry floors is a follow-up.
   **Consequence, open decision (review of the port, 2026-11-17).** That input is now the
   same string for every `chat_prefill` item of a set (the chat prompt through the generation
   prompt; nothing of the item is in it). The Opus text-leak gate (`opus_gate`: an item is kept
   only if the prompt-only reader never passes it on 3 decided draws) therefore passes every
   `chat_prefill` item by construction, up to a chance guess, while `plain` and
   `plain_fewshot` items are still gated on a prefix that shows line one. So the gate no longer
   screens `chat_prefill` items for text leakage, and a set's poetry items are gated unevenly
   by render. Behaviour is left as is here (the rule is "never a reply", and line one IS reply
   text in that render); whether to gate `chat_prefill` items on something else (e.g. line one
   shown as plain text, outside the prompt-only protocol) or to accept an ungated render is
   Camila's call. `tests/test_prompt_cut.py::test_adapted_poetry_chat_prefill_prefix_stops_at_the_generation_prompt`
   pins what `read_prefix` returns.
4. **Stamp decision: the protocol stays `po-opus-v1`; the input revision is the new
   `prompt_cut` field.** The reader, question, framing, draw count and fallback are unchanged,
   and for 23 of the 29 families the input is byte-identical, so their frozen `po-opus-v1`
   floors remain exactly right. Renaming the protocol (`po-opus-v2`) would either invalidate
   those floors for no change or need dual-protocol code in every reader of `PO_OPUS` /
   `PO_FALLBACKS` (freeze, labels, `scripts/nyt_connections_bar.py`, poetry gate, adapt).
   An entry re-measured under the cut is told apart by `prompt_cut: "reply-free-v2"`.
5. **Re-measure** the six families on the registered Qwen3.6-27B banks with the bench's own
   stages: `stage=build` → `ask` (Opus 5.5, one draw) → `readouts` → `fallback_ask` /
   `fallback_readouts` (Sonnet 5.5 for Opus refusals) → `wsbench run ... allow_missing=True`
   (current instruments) → `wsbench freeze kind=prompt_only` into
   `evals/baselines/prompt_only_summary.json` (Opus run first, then the fallback run for the
   families with refusals, as the committed floors were made). Every other entry and `_source`
   stay byte-identical (`_source` describes the original run; the re-measured entries carry
   their own `protocol` / `prompt_cut`).

## Result (2026-11-05, measured; re-asked after the review of #350)

**Superseded by "2026-11-17 port onto main" below wherever the two differ**: the floors in this
section's table are on banks and instruments main has since replaced and are not the committed
ones; the family count (29) and "23 byte-identical" are 30 and 24 today; the Sonnet 5 test split
in the last paragraph no longer exists. Kept as the record of the first measurement.

The first measurement (`reply-free-v1`) still quoted the read-site token, a reply token on 922
rows, and its answer cache was keyed by id only; its floors are superseded. Re-measured under
`reply-free-v2` in a fresh dir (no cached answer): all 2,348 ids answered by Opus 5.5 with no
refusal (no Sonnet fallback needed), judged with the CURRENT instruments (`wsbench run ...
allow_missing=True`, every row complete), frozen with `wsbench freeze kind=prompt_only`;
`_source` restored to the original run's record. Several committed entries were already stale
against main's instruments (e.g. basic_readout `br-mc-2026-10-30b` → `br-mc-2026-11-01-v5b`,
jailbreak `jb-v3` → `jb-v4+…+guard-r6`, introspection `twinrx-v3` → `twinrx-v4+rxhead-v1`), so
old → new mixes the cut with those instrument changes. jailbreak's v2 questions are identical to
v1's (its cut rows end in the prompt, so the quoted token did not change): 0.802 → 0.837 is one
fresh draw's sampling spread.

| family | committed (reply in prefix) | reply-free-v1 (superseded) | reply-free-v2 |
|---|---|---|---|
| basic_readout | 0.840 | 0.840 | 0.900 |
| directed_modulation | 1.000 | 1.000 | 1.000 |
| introspection | 0.000 | 0.000 | 0.000 |
| jailbreak_recognition | 0.895 | 0.802 | 0.837 |
| model_specific_directed_modulation | 0.582 | 0.673 | 0.643 |
| multi_concept_directed_modulation | 0.965 | 0.982 | 0.974 (2 undecided) |

On the box, every registered family's built prompt rows were checked through the exact reader
question (`reader_prompt`): the quoted text equals the prefix, holds no reply token (token-level
detector), and the quoted token is the prefix's own last token (2,348 + all other families'
rows, 0 failures); only the 922 cut-inside-a-reply rows changed their quoted token.

`tests/test_po_floors_r3.py`'s "committed Sonnet 5 floor applies to a live Sonnet 5.5 row"
property keeps its two still-Sonnet-5 families (moral_rationale, user_modeling; the report test
moves from introspection to user_modeling), and a new test pins that the three re-frozen
families (now frozen with the Sonnet 5.5 digest fallback) match a live row directly. That test
edit is sanctioned here: the property is retained, only the data it is checked on moved.

## 2026-11-17 port onto main

The PR sat 461 commits behind main. Since the result above, main re-froze every prompt-only floor
(the 2026-11-04 refreeze and the banks registered after it, `evals/baselines/README.md` "Floors
of record"), so the six entries measured on 2026-11-05 were on superseded banks and instruments
(e.g. basic_readout bank v8 replaced the capital items; `+brsum-v2+qline-v2+bank-v8`). Main's
entries for the six are on the current instruments but were built with the old cut. The port
keeps main's file and re-measures the six on it; the 2026-11-05 table above is history.

**Audit on today's registered banks** (30 families, 5,763 prompt-only ids; Qwen3.6-27B
tokenizer, `prompt_cut.reply_tokens` on the old cut `ids[: last + 1]` and on the new cut;
`read_plan_bank` banks on their own ids, `text_inversion.judged_bank_ids`). The affected set is
still exactly the six; the three families added since (hinted_cutoff bank v2, model_multihop,
nyt_connections) read a `captured` / `chat` render that ends at the generation prompt and hold
no reply; the 11 `plain` / `bare` families have no template.

| family | ids with reply text, old cut | new cut | reply tokens (old cut) | where |
|---|---|---|---|---|
| basic_readout (bank v8) | 100 / 100 | 0 | 6 | the prefilled answer stem |
| directed_modulation | 100 / 100 | 0 | 7–9 | the dictated sentence, prefilled |
| model_specific_directed_modulation | 98 / 98 | 0 | 7–9 | the same |
| multi_concept_directed_modulation | 116 / 116 | 0 | 12 | the target sentence, prefilled |
| introspection | 508 / 1,762 | 0 | 18 | the protocol's earlier assistant turn (250 inject + 250 gaussian + 8 beta0 rows; all 250 ids the refreeze asked) |
| jailbreak_recognition | 29 / 172 | 0 | 12–944 | earlier assistant turns of multi-turn conversations |
| the other 24 families | 0 / 3,415 | 0 | — | — |

951 rows change under the cut, every other row's ids are identical to the old cut's. Built for
all 30 families, the exact reader question (`reader_prompt`: prefix + quoted token) holds no
reply token in any of the 5,763 rows, and the quoted token is the prefix's own last token in all
of them (it differs from `site_token` on the 922 rows cut inside a reply).

**Re-measure** (§5's stages, `reply-free-v2`, fresh dir): 2,348 ids asked of Opus 5.5, 0 refused
(no Sonnet 5.5 fallback run), judged by `wsbench run ... allow_missing=True` on the registered
instruments (each identical to the refreeze entry's `instrument`; jailbreak on its Sonnet 5
digest / judge pins with the Opus 5 refusal re-run), 0 digests refused, every row complete,
frozen with `wsbench freeze kind=prompt_only`. Only the six entries were taken into
`prompt_only_summary.json`; `_source`, the key order and the other 24 entries are byte-identical
to main's. introspection was asked and judged on its full grid (1,762 ids; the refreeze asked
its 250 headline rows with `opts=scope=headline`), so its entry is now `complete: true`.

| family | main (old cut, reply in prefix) | reply-free-v2 [95% CI] | n | Opus refused |
|---|---|---|---|---|
| basic_readout | 0.810 | 0.890 [0.83, 0.95] | 100 | 0 / 100 |
| directed_modulation | 1.000 | 1.000 | 100 | 0 / 100 |
| introspection | 0.000 | 0.000 | 125 | 0 / 1,762 |
| jailbreak_recognition | 0.895 | 0.884 [0.80, 0.96] | 172 | 0 / 172 |
| model_specific_directed_modulation | 0.582 | 0.592 [0.50, 0.68] | 98 | 0 / 98 |
| multi_concept_directed_modulation | 0.965 | 0.965 (2 of 116 undecided) | 114 | 0 / 116 |

One fresh draw per id, so old → new mixes the cut with sampling spread (items fail→pass /
pass→fail: basic_readout 9 / 1, model-specific DM 6 / 5, multi-concept DM 1 / 1). basic_readout
is the only move outside it: without the answer stem the reader names the answer on 9 more
items (all 11 remaining failures are implicit items).

**Tests.** The refreeze removed the "still frozen on Sonnet 5" split this plan's result section
describes (no committed entry carries the Sonnet 5 protocol any more), so that split and its two
tests are dropped; `tests/test_po_floors_r3.py` keeps every main-side test unchanged (the
sanctioned fixture stamps aside) and adds `test_reply_free_floor_carries_the_cut_and_matches_a_live_row`
(the six carry `prompt_cut == PROMPT_CUT` and match a live row) and
`test_committed_cut_stamps_are_the_current_cut`.

**Review of the port (2026-11-17).**
- *Merged header token (a silent leak, fixed).* `assistant_turns` searched the full header
  `<|im_start|>assistant\n`. Under olmo-3-7b, olmo-3.1-32b and qwen3-8b (templates that do not
  strip content) a reply that starts with a newline merges with the header's newline into one
  `\n\n` token, the header was not found, the reply stayed in the prefix, and
  `assert_no_reply` (the same detector) passed. Turns are now found by the header without its
  trailing whitespace tokens (`TurnMarks.header_core` / `user_core`); content that follows the
  core without the rest of the header is reply content. `assert_no_reply` additionally checks
  the decoded text (`reply_text`: what follows each assistant header string), which shares no
  code path with the token search. Verified on the three real tokenizers (replies starting
  with one or two newlines leaked before, are cut now) and on Qwen3.6-27B (the same replies do not merge there:
  the full header is in the ids, and the old and new cuts agree).
- *A site on the first token of a two-token end marker* (`<|im_end|>` of `<|im_end|>\n`) exited
  as "ambiguous"; it is now the end of that reply and cuts back to the generation prompt.
- *A whitespace-only assistant turn is a reply* (`has_content`: any content token) and is
  dropped; an empty turn is not. No registered row has one.
- *Registered banks unchanged.* All 5,763 prompt rows have the same token ids under the fixed
  code as under the measured one (2,348 of them the measured rows; the rebuilt `prompts.jsonl`
  is byte-identical), so the six floors stand.
- `freeze` without `source=` never replaces a stamped entry (§3); the fallback stages name the
  prompts file the stale rows came from (`require_cut_srcs`).
- The adapted poetry `chat_prefill` gate consequence is recorded in §3b (open decision).

## Not in this PR (follow-ups)

- The ATI panel prompts (`text_inversion.build`) use the same last-site cut; the ATI subset of
  basic_readout, model_specific_directed_modulation, introspection and jailbreak was gated on
  prefixes that held reply text. Re-gating needs the full panel (Qwen + Opus/Sonnet + astra +
  argon via Modal) and is left for its own plan.
- Adapted sets' committed prompt-only floors (`adapted/<m>/floors/prompt_only_summary.json`)
  were built with the old cut; they need a rebuild per set (the new code handles their
  templates or exits loudly). At the port (2026-11-17): 15 of the 16 sets carry a
  prompt-only summary, each with old-cut entries for five of the six families (no adapted
  introspection floor): 75 set × family floors (their own leak sets were not audited here; a set's
  poetry floor may be affected too where its items read as `chat_prefill`). Open decision
  before those rebuilds (§3b): the adapted poetry Opus gate now passes every `chat_prefill`
  item by construction, since its prompt-only input holds nothing of the item. A prompt-only dir built by an older checkout (unstamped `prompts.jsonl`,
  run config without `prompt_cut`) is refused by `ask` / `readouts` / the fallback stages /
  `freeze` on this code: rebuild with `stage=build` and re-ask.
- The box-side Qwen and single-guess controls already used the reply-free cut.

## Checks

`ruff check`, `ruff format --check`, `pytest -q`; `tests/test_prompt_cut.py`: Qwen-, GLM- and
Gemma-shaped templates (final-turn prefill cut at the generation prompt, byte-identical without a
reply, earlier assistant turns dropped, loud failures), a build regression on the real
basic_readout / directed_modulation / multi-concept DM / association plans, the stale-prompts
guard. On the box, the token-level detector matched the audit's leak ids on all 29 families.
