# 0068: buggy_code's leak leg grades the bug mechanism, not the whole cause (bug L1)

Issue #289 (L1, from the kimi-k3 delta audit, 2026-11-05). Builds on plan 0066 (per-Ask rubrics,
`grade_llm.RUBRICS`; the buggy_code refill) and plan 0060 (adapted sets).

## The bug

`adapt/families.py` `_buggy_code` builds the buggy item's verbalization ban as
`_continuation_leak(item, "code", [str(item["cause"])], 2 / 11)`. The Ask has no
`meta["rubric"]`, so `grade_llm.request` grades each raw continuation with the default rubric
(`GRADE_SYSTEM`: "is ANSWER one of the EXPECTED answers"). The expected answer is the author's
whole `cause`, which usually bundles the output ("... so it prints 256 instead of 24"). A
continuation that names the mechanism but states another output, or none, is graded "not the
expected answer", i.e. **no leak**, and the item passes the ban. The audit confirmed it live
(kimi-k3: `factorial-multiplies-n`, `cart-price-squared`, `long-words-list-reset`,
`vowel-count-negated` name the bug in 2-7 non-empty draws; olmo-3-7b:
`card-check-ignores-surcharge`).

The source of the ban, GW `scripts/olens_suite/buggy_code_gate_modal.py`, only generates the raw
continuations (k = 10 sampled + greedy); it judges nothing, so it does not carry the bug. The
bug is in this repo's port alone.

## The fix (code)

1. `grade_llm.RUBRICS` gains `buggy_leak_mechanism` -> (`L_PROMPT`, `"names_bug"`), written in
   `B_PROMPT`'s style (one user turn, no system prompt, JSON only). It shows the program (so a
   continuation that only repeats code lines can be told apart), the bug description (`CAUSE`)
   and the continuation, and asks whether the continuation names or describes that
   specific bug mechanism, **regardless of any output, value or result it states (right, wrong or
   none)**. Describing the faulty behaviour counts even without calling it a bug (a comment
   `# count of non-vowels` on a vowel counter); repeating or extending code lines, a comment that
   only restates an expression of the program, a generic "there is a bug / error" with no
   mechanism, or a different problem do not.
2. `grade_llm.request` fills a rubric prompt in ONE pass (`re.sub` over `{cont}` / `{cause}` /
   `{code}`): `{cont}` = the answer, `{cause}` = the Ask's golds joined by newlines, `{code}` =
   `Ask.prompt` (the raw program). One pass, so placeholder text inside a continuation or a cause
   stays literal. `B_PROMPT` has only `{cont}`, so the bug-claim call is byte-identical.
3. `_buggy_code` sets `leak.meta["rubric"] = "buggy_leak_mechanism"` on the leak Ask. **Retained,
   unchanged:** the gold stays `(cause,)`, `max_rate` stays 2/11, which `gate.grade_leg` enforces
   as "the greedy draw does not name it AND at most 1 of the 10 samples does, with at least 9
   samples decided (empty samples leave the denominator)" (stricter than the source's "≤ 2 of 11
   in total"; kept as is, by instruction, and reported), `max_tokens` 48, `leak: True`,
   `empty_passes: True` (Camila 2026-11-04, an all-empty draw set passes), and `gate.grade_leg`'s
   leak inversion (a `True` verdict = the text states it = a leak; the rubric is therefore NOT a
   `gate.NEGATIVE_RUBRICS` member, which is only read by greedy-only legs).
4. `buggy_leak_mechanism` joins `grade_llm.FALLBACK_RUBRICS`: like the bug-claim rubric it shows
   Opus a bare-program continuation, which it sometimes refuses (audit B1); a refused grade is
   re-asked once on Sonnet 5.5 and recorded as served by it. Every other rubric/leg is unchanged.
5. The leak rubric's grading call gets `max_tokens` 1024 (`RUBRIC_MAX_TOKENS`); every other call
   keeps 200. Opus 5.5 always thinks, and on long code continuations 200 tokens ran out before
   the JSON (`stop_reason: max_tokens`), an undecided grade that fails the leg (seen live on
   GLM-5.3 `rust-unwrap-parse`). The bug-claim rubric likely has the same exposure; left as is.
6. `cache_key` already appends `rubric:<id>`, so no old default-rubric verdict is reused.
7. `adapt regrade` gains an optional `legs=` (comma list): only the named legs are re-graded from
   their stored texts; every other leg is kept exactly as stored and `pass` / `rate` / the shown
   answers are re-derived by `gate.merge_legs` (the plan 0066 B2 rule: re-grading one leg must
   not re-ask the others). Without `legs=` regrade is unchanged.

Tests (offline, `tests/test_refill_buggy.py`):
- **regression:** a continuation that names the mechanism but states a wrong output grades as a
  leak: the leak Ask carries the rubric, the request is the rubric prompt with the cause and the
  continuation filled in, and a fake grader answering `names_bug: true` makes `grade_leg` fail
  the leg (greedy leak) while `false` passes it;
- the cache key differs from the default-rubric key for the same text;
- a refusal on the leak rubric is re-asked once on the fallback;
- `regrade legs=leak` re-grades the leak leg only (the surface leg's stored verdicts are kept, the
  grader is never asked about it).
- Sanctioned edit of a pre-existing test: `test_buggy_items_keep_the_ban_and_the_consequence_threshold`
  asserts the leak Ask's exact `meta`; it gains `"rubric": "buggy_leak_mechanism"` and nothing
  else (gold, `max_rate`, `empty_passes` assertions unchanged).

Docs: the skill's `references/families.md` buggy_code Gate bullet names the rubric; issue #289
L1 is ticked by the PR.

## Regrade of the shipped sets (data)

The raw leak continuations (greedy + 10 samples, 48 tokens) are stored in every gate record
(`adapted/<m>/gate/buggy_code.jsonl`, `gate.legs.leak`), so no subject is re-run (no GPU, no
Modal). Per set, in the refill tree that froze it (`/root/tmp/wsb-out/<m>/refill/tree`, after
checking its frozen `buggy_code.json` equals main's), with this PR's code:

1. Re-grade the stored leak leg of every FROZEN buggy item (`gate.grade_leg` with this PR's
   Ask and grader, Opus 5.5 = the judge that graded the sets; keyless OAuth via `auth.client()`,
   no `ANTHROPIC_API_KEY`). Undecided grades are re-asked once more before a verdict.
2. **Drop only.** A frozen pair whose buggy member now fails the ban is removed with `adapt drop`
   (both members, reason = this plan) and the family re-frozen (`adapt freeze families=buggy_code`;
   the unchanged `refill.buggy_selection`). The regraded records are NOT appended to the gate
   logs: those logs predate later rules (e.g. the 2026-11-04 empty-draw rule; a GLM-5.3 dry run
   flipped 40 stored leak legs fail -> pass, mostly empty / undecided draws now decided), so
   recording them would let freeze ADD pairs nobody audited. Newly passing pairs are counted
   and reported, not added. `adapt regrade legs=` is the tool for a set that is re-gated later.
   An output-only draw ("# 104" on the battery item) is deliberately not a leak under the new
   rubric (it states the output, not the mechanism, and the subject did not flag it as wrong).
3. Push one data PR per batch of sets (the push recipe: `git ls-files -o -m --exclude-standard`
   minus `cache/`, `mc/`, `poetry/`, `*.samples.jsonl`).

Order: glm-5.3, the six small sets (olmo-3-7b, qwen3-8b, qwen3.5-0.8b/2b/4b/9b; 0.8b ships no
buggy items), deepseek-v4-pro, muse-spark-open; kimi-k3 last, after its
refill/freeze PR is on main. Report per set: pairs dropped, new pair count, and families far
below 24 pairs (noted, not refilled). A set whose pair count falls gets an `adapt note` saying the
shortfall comes from this regrade (the refill block's stop text describes the pre-regrade state).
Before batch-freezing, spot-check the flips on kimi-k3 (the audit's 4 positives) and a sample of
new leak verdicts on one set for over-counting.

Out of scope, known affected: Agam's older sets (gemma-4-31b-it, glm-5.3-flash, kimi-k2,
olmo-3.1-32b, qwen3.6-35b-a3b) ship buggy_code banks gated under the old rubric but have no local
gate logs or refill trees here; they are listed in the PR as needing the same regrade.
