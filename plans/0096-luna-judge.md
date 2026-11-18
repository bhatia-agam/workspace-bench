# Plan 0096: an OpenRouter judge (GPT Luna) can run every family

Status: critiqued (three rounds), ready to implement. Owner: Camila. Scope: `llm.py`, `judge_config.py`,
`mcjudge.py`, `digest.py`, `family.py`, four family judges, docs, tests.
No bank, prompt, call key, fingerprint or `prompt_version` moves.

**Invariant every step is checked against.** A run whose `args.judge.pinned` is true, with
default options, makes byte-identical SDK requests and has byte-identical cache keys,
fingerprints and `config`. Its rows and extras are byte-identical except for the additive
provenance keys of step 4, which appear only where a fallback served a call. "Pinned" below
always means `args.judge.pinned` (never a comparison with the registry spec's model: test
fixtures run `resolve(JudgeConfig())`, pinned on a model that is not the family's).

## Step 0 (before any `src/` edit): pin the pinned path

`tests/test_pin_requests_0096.py` + `tests/golden/pin_requests_0096.json` (and a section in
`tests/golden/README.md`): for each of the four families, on `args.judge.pinned`, summary mode
(hinted_cutoff / model_multihop also native), with ONE declined call so the fallback fires,
capture the SDK-level kwargs of every judge and fallback request (model, max_tokens, system /
messages, output_config / thinking, betas, fallbacks, temperature) and the result `config`,
through the Anthropic-shaped fakes `fake_client_installer` / `ModelAwareClient`
(`tests/test_llm_refusal_rerun.py`, as `test_agentic_refusal_rerun.py` uses them), NOT the
conftest OpenRouter shim (it drops exactly the keywords that could move). The capture runs at
`concurrency=1` and sorts requests by `(model, sha256 of system + messages)`; the golden stores
each request's `system` / `messages` as a sha256 and every other kwarg verbatim. The test uses only
API that exists on `origin/main`. The implementer writes it and generates the golden on the
untouched tree first; the main session confirms the golden by running the same test file
against `origin/main`'s `src/` before accepting the diff. After the change it must pass
unedited.

## Problem

A run with `judge_model=openai/gpt-6-luna` (OpenRouter route) hits Claude-only assumptions:

1. **Free-text stage.** `llm.stream_text_async` raises `JudgeConfigError("free-text stage
   requires a claude-* model")` for any OpenRouter model and requires a `claude-*`
   `refusal_model`. agentic_misalignment (three free-text stages) therefore exits 3 under a Luna
   judge, with Luna or Opus digests alike. Plan 0005 wrote "raises ... for now": a port that was
   never done.
2. **Refusal fallbacks are route-locked.** `llm.stream_json_async` refuses a `refusal_model` on
   another route; `digest._fallback_opt` refuses a non-`claude-*` client-side refusal model.
3. **Refusal fallbacks are switched off by an override.** hinted_cutoff (`_Caller`),
   model_multihop (`_refusal_model`), agentic_misalignment (summary Stage C) and
   jailbreak_recognition (summary draws) enable their fallback only when `args.judge.pinned`. A
   Luna judge is never pinned, so a call Luna declines is simply lost.

Two items of the report are answered here, not changed:

- **The digest pins stay.** agentic_misalignment and jailbreak_recognition keep
  `DIGEST_MODEL = "claude-sonnet-5"` (`JudgeConfig.aux_models["digest"]`) under a judge
  override, exactly as every other family keeps the default Opus 5.5 digest under one:
  `judge_model=` moves the judge, `opts=summ_model=` moves the digest. Nothing couples them
  today and this plan adds no coupling. (A Luna-digest run of these two families is
  `opts=summ_model=openai/gpt-6-luna`; step 3 makes its `none+claude-opus-5` refusal re-run
  legal across routes.)
- **`pinned=False` under a non-default judge is the definition** (README §Judges:
  `pinned_instrument` is true only when the resolved model equals the family pin). It stays.
  What was wrong is that fallbacks keyed on it (item 3); after this plan nothing but the
  instrument-identity stamps reads `judge.pinned`.

## Design

### 1. `llm.py`: free-text primitive on the OpenRouter route

- New `_openrouter_text_once(client, user, *, model, thinking, max_tokens, timeout, spend,
  mark_refusals)`, the OpenRouter twin of `_anthropic_text_once`, same contract (returns the
  stripped text, `""` valid; `None` / `REFUSED` for a refusal):
  - `client.chat.completions.create(stream=True, stream_options={"include_usage": True},
    model=, max_tokens=budget, messages=[{"role": "user", "content": user}], timeout=,
    extra_body={"usage": {"include": True}, "provider": {"require_parameters": True},
    "reasoning": ...})`; user-only message, no system block, no `response_format` (as the
    Anthropic twin sends it).
  - Reasoning: `thinking=True` -> `{"enabled": True}` (OpenRouter documents this as medium
    effort; the analogue of Anthropic `adaptive`); `thinking=False` -> `OPENROUTER_MIN_REASONING =
    {"effort": "minimal"}`, the value every structured OpenRouter judge call already runs at
    (`judge_config.DEFAULT_REASONING`, "Gemini cannot turn reasoning off"), so a no-thinking
    stage never 400s on a model that cannot disable reasoning. `judge_config.DEFAULT_REASONING`
    becomes an alias of the `llm` constant (one definition; `judge_config` already imports
    `llm`). The implementer confirms both request shapes against the OpenRouter reasoning-tokens
    documentation before coding and records the doc URL in the PR; if the documented shape
    differs, the documented one wins and the plan line is corrected.
  - Accumulate `choices[0].delta.content` over the stream; keep the last non-null
    `finish_reason`, the `usage` of the final chunk (cost -> `spend.usd` by the rule of
    `_openrouter_once`; prompt / completion tokens -> `spend.input_tokens` / `output_tokens`),
    and any `delta.refusal` text. `spend.calls += 1` once per completed stream.
  - Mid-stream errors. The OpenAI SDK never yields an error chunk: it raises
    `openai.APIError` (no `status_code`) from the stream iterator for SSE data with an `error`
    key. On the OpenRouter text route `_one_text` therefore treats as transient: an exception
    named `APIError` with no `status_code` raised while iterating, `finish_reason == "error"`,
    and a stream that ends with no chunk that has `choices` (the last two raise `ValueError`
    inside `_openrouter_text_once`). The stream is closed on every exit path. The test fake
    raises an SDK-shaped exception from its iterator.
  - Refusal = `finish_reason == "content_filter"`, or a non-empty refusal with empty text:
    `spend.refusals += 1`, print `  llm refusal: <model>`, return `REFUSED` if
    `mark_refusals` else `None`. Stated limit: with no schema, a refusal written as ordinary
    content ("I can't help with that") is an answer; the text fallback fires only on
    `content_filter`, a `refusal` field or the moderation 403.
  - Budget doubling, same loop as the Anthropic twin: empty text and `finish_reason ==
    "length"` and `budget < _TEXT_BUDGET_CEILING` -> `budget *= 2`, re-ask. The retained
    invariant, restated: the ceiling stays `_TEXT_BUDGET_CEILING = 64_000` for both routes, and
    `""` after the ceiling is still a valid (cached) result.
- `_one_text` gains a leading `route_` parameter and dispatches like `_one`; its backoff /
  fatal classification is unchanged, plus `_one`'s existing OpenRouter moderation rule (a 403
  with `flagged_input` is one refusal: `REFUSED` under `mark_refusals`, else `None`, never a
  `JudgeConfigError`).
- `stream_text_async`: the `route(model) != "anthropic"` raise is deleted; the client is built
  for `route(model)`. Everything else in its contract is retained: no client when there is
  nothing to call, `""` valid, `on_served` before `on_result`.
- **Structured calls get the same refusal rule** (`_openrouter_once`): `finish_reason ==
  "content_filter"`, or a non-empty `message.refusal` with empty content (both read with
  `getattr`, so the conftest `SimpleNamespace` fakes pass unchanged) -> `spend.refusals += 1`,
  `REFUSED_JSON` under `mark_refusals`, else `None`; `_openrouter_once` gains the
  `mark_refusals` keyword and `_one` passes it. Without this a declined structured Luna call is
  a `JSONDecodeError`, retried 12 times and lost as an error, and step 4 would do nothing for
  model_multihop and jailbreak. This reaches every OpenRouter `stream_json` caller (the adapt
  stages too) and never a pin; the outcome without `mark_refusals` is still `None`, with one
  counted refusal instead of 12 retries + one error.
- The section comment and docstrings say "both routes"; plan 0005 gets a one-line "superseded
  by plan 0096" note at the "for now" sentence (plans are history; nothing else there moves).

### 2. `llm.py`: a refusal model may be on the other route

Applies to `stream_json_async` and `stream_text_async` alike. The check becomes: `refusal_model
== model` raises (unchanged message shape: `refusal_model=... must be another model`); a
different route is legal.

- When `route(refusal_model) != route(model)`: `api_key(refusal_model)` is resolved **before any
  call** (a missing key for the fallback route is a `JudgeConfigError` up front, never a
  mid-run surprise), and a second client is built with `_make_client` and closed in the same
  `finally`. Same-route refusal models keep sharing the primary's client (today's behaviour,
  byte-identical).
- The re-run's request is re-shaped for its route by one new helper,
  `llm.reasoning_for(route_, reasoning) -> dict | None`: on `anthropic` keep only
  `ANTHROPIC_REASONING_KEYS` (None when empty); on `openrouter` keep every other key, and when
  none is left use `OPENROUTER_MIN_REASONING`. `ANTHROPIC_REASONING_KEYS` moves to `llm`
  (`judge_config` re-exports it), and `judge_config.resolve` calls the helper so the rule has
  one home; `resolve`'s outputs are unchanged for every existing input (a test pins the table).
  **The helper is applied only to a cross-route re-run.** A primary call, and a same-route
  re-run, send `reasoning` exactly as today. `reasoning_for` accepts `None` and returns a copy
  of the constant, never the constant itself.
- `stream_json_async` and `mcjudge.run_calls` gain `refusal_reasoning: dict | None = None`.
  `None` = not given (the helper above decides); a dict is the re-run's reasoning as is.
  The families pass `refusal_reasoning=` / `accept_served=` (step 4) to `run_calls` and
  `_batch` only when non-default; `run_calls` forwards `refusal_reasoning` to `stream_json`
  only when it is not `None` (the idiom at `mcjudge.py:118-119`); `accept_served` is consumed
  inside `run_calls` and never forwarded. So `kw`-inspecting fakes see today's kwargs on the pin. Reason: a family's own
  `anthropic_effort` is dropped by `resolve` for an OpenRouter judge, so the callee cannot
  recover it; without this a Sonnet 5.5 fallback under a Luna judge would run at `effort: low`
  while the same fallback on the pin runs at the family's `default`. Callers pass it only for
  a cross-route fallback (step 4).
- Cross-route re-run, the other per-route knobs (`stream_json_async` only): `max_tokens` the
  caller left `None` resolves to the refusal route's own `_DEFAULT_MAX_TOKENS`; `temperature`
  is not sent to an Anthropic refusal model (the existing drop rule) and is sent to an
  OpenRouter one (the caller's ORIGINAL value: today's code overwrites `temperature` with
  `None` on an Anthropic primary, so keep the original for an Anthropic -> OpenRouter re-run); `overflow_max_tokens` state carries over only between Anthropic calls (an
  OpenRouter re-run uses the plain cap); `fallbacks=` is never passed to the re-run (today's
  rule). Retained, restated: only refusals move (a `max_tokens` stop, an error or an
  unparsable body stays the primary's outcome), the re-run happens ONCE, a served JSON result
  carries `SERVED_BY`, a served text fires `on_served`.

### 3. `digest.py`: `summ_fallback` accepts any client-side refusal model

`_fallback_opt` accepts `none+<model>` and `default+<model>` for any non-empty model id (the
`claude-` test is dropped; the error text lists `<model>`). The three client-side re-run sites
(`_digest_pass`'s `on_retry` call, the `run(again, s.refusal_model, True)` site, the levels
re-run near `n_refusal_model_calls`) pass `reasoning=llm.reasoning_for(llm.route(model),
s.reasoning)` **iff** `llm.route(model) != llm.route(s.model)`, else `s.reasoning` as today.
Retained, restated at the point of change: the digest fingerprint and the fallback salt are
untouched; a fallback-served row still carries `SERVED_BY` + `SERVED_VIA = "client"` and
`_stale_fallback` still makes a row another client-side model served a cache miss.

A cross-route digest re-run keeps `s.max_tokens` and `overflow_kw` (the latter ignored off
Anthropic); a cap the other route's provider rejects is that run's configuration problem, not
re-shaped here.

Not in scope (recorded so the reviewer does not chase it): what a non-Claude **primary** digest
model sends (`reasoning={"anthropic_effort": ...}` reaches OpenRouter as-is today; server-side
`fallbacks=` is ignored on that route; `count_tokens` is Anthropic-only). The report did not
flag the Luna-digest setups as failing; changing their request would move existing runs.

### 4. Families: the refusal fallback no longer needs a pinned judge

One rule for all four: **the family's refusal fallback is on whenever the fallback model
differs from the resolved judge model**, whatever `judge.pinned` says, and off under
`opts=fallback=none`.

| family | site | today | after |
|---|---|---|---|
| hinted_cutoff | `_Caller.__init__` | `on and fb and fb != judge.model and judge.pinned` | `on and fb and fb != judge.model` |
| model_multihop | `_refusal_model` | `fb and fb != judge.model and judge.pinned` | `fallback on and fb and fb != judge.model` |
| agentic_misalignment | summary Stage C `refusal_model=` | `REFUSAL_MODEL if judge.pinned else None` | `REFUSAL_MODEL if fallback on and REFUSAL_MODEL != judge.model else None` |
| jailbreak_recognition | summary draws `refusal_model=` | same | same |

- **Fallback effort = the family's own instrument** (hinted_cutoff, model_multihop: their
  `JudgeConfig` sets `anthropic_effort: default`). In the cross-route branch ONLY, the
  fallback's reasoning is `judge_config.resolve(registry.FAMILIES[NAME].judge,
  flag=fb).reasoning`, looked up at call time (a module-level import of the spec is a cycle;
  agentic already reads `registry.FAMILIES[FAMILY]` this way): hinted_cutoff's fallback
  `ResolvedJudge` takes it, model_multihop passes it as `refusal_reasoning=`. agentic and
  jailbreak pass nothing (their family reasoning is `None`, which is what the helper yields
  for an Anthropic re-run; agentic's Stage C goes through `stream_text`, which has no
  reasoning parameter). A same-route fallback sends what it sends today
  (`args.judge.reasoning`; no `refusal_reasoning`, no registry lookup). hinted_cutoff's key suffix `|fb`, its "any
  failed call" trigger and `n_fallback_calls` are retained.
- `opts=fallback=on|none` (hinted_cutoff has it; default `on`) is read the same way by the
  other three, through one shared helper in `wsbench/family.py` (`fallback_on(args, name)`;
  any other value exits 2 with hinted_cutoff's message text unchanged), called at the top of each
  family's `run()` (hinted_cutoff's check moves there from `_Caller.__init__`), so a bad value exits 2 in native mode too (where agentic and jailbreak have
  no judge fallback and the value is otherwise unused). It turns off the JUDGE-call fallback
  only (the digest's is `opts=summ_fallback=`), and it is how a judge-comparison run gets a
  row whose judge calls are one model's. It keys no fingerprint.
- **`fallback=none` never reuses a fallback-served cache row.** `run_calls` caches a served
  row under the judge's fingerprint and agentic's `_batch` does the same, so a resumed out dir
  would silently mix. `run_calls` gains `accept_served: bool = True`; with `False` a cached
  row carrying a serving model is a miss (re-asked on the judge, the new row appended), and
  `_batch` gets the same switch. The three families pass `False` exactly when their fallback
  is off by `opts=fallback=none`. Default `True` = today's lookup, byte-identical. No `Cache`
  change: the newest non-failed row for `(key, fp)` wins. Consequences, stated: under
  `fallback=none` a key the judge declines again is re-asked on every resume (nothing is
  cached for it, as for any failed call today), and the served row stays in the file, a hit
  again for a later fallback-on run; if the judge itself answers on the re-ask, that newer row
  supersedes the served one for every later run. Tests assert on -> none -> on in both cases.
  hinted_cutoff needs nothing (its `|fb` rows are read only when the fallback is on).
- **Credentials up front.** When a family's effective fallback is on another route than the
  judge and the run is not a dry run, the family resolves `llm.api_key(fallback)` before its
  first call (a missing key is a `JudgeConfigError`, exit 3, naming `opts=fallback=none`);
  `digest.collapse` does the same for a cross-route `s.refusal_model`, also never on a dry run. Same-route: no new
  call (the pinned path is untouched).
- **Stamps.** With `args.judge.pinned` and the fallback on (the default) `config` is
  byte-identical to today. Otherwise (`not args.judge.pinned`, or `fallback=none`) agentic and
  jailbreak in summary mode, and model_multihop in both modes, add `config.judge_fallback`:
  the effective fallback model, `"none"` under `opts=fallback=none`, or `"same-as-judge"` when
  the judge is the fallback model. Native agentic / jailbreak have no judge fallback: no key.
  hinted_cutoff keeps its existing `config.fallback_model` and nothing else. `summary_pinned`
  (agentic, jailbreak) and model_multihop's `pinned` (in BOTH `_native`, which today takes
  `pass_rate_result`'s default, and `_summary`) gain "and `fallback_on`"; hinted_cutoff's
  existing `fallback=none` behaviour is left as it is. A Luna row still reports
  `pinned_instrument = false` and `complete = false`.
- **Provenance** (the additive keys of the invariant). agentic and jailbreak already record
  the serving model (`judge_model` / `judge_served_by`); unchanged. model_multihop and
  hinted_cutoff record nothing per row today. New, under names no family uses yet:
  - row `fallback_served_by`: the sorted list of distinct fallback models that served at least
    one of the row's judge calls; the key is absent when none did. model_multihop summary: the
    one MC call (`llm.SERVED_BY` threaded from `results[...]` past `decide()`); model_multihop
    native: any `|summ` or `|judge` call of any unit of the item; hinted_cutoff: any chunk of
    either twin whose `|fb` result was the one used (summary mode: either twin's one item call).
  - `extras.n_fallback_served_calls`: the number of judge calls a fallback served in this run's
    results (cache hits included), for these two families, present only when > 0.
  (hinted_cutoff's `n_fallback_calls`, attempted re-runs, is retained.)

### 5. Docs

README §Judges (the override bullets: fallbacks follow an override judge, `opts=fallback=none`,
the digest pin answer above, free-text stages on both routes; hinted_cutoff's "any failed
call" trigger means a Luna error or unparsable answer, not only a refusal, goes to Sonnet 5.5;
a single-key OpenRouter environment needs `opts=fallback=none` for the four families), the agentic / jailbreak /
hinted_cutoff / model_multihop family READMEs where they say "when pinned", `CLAUDE.md` judge
layer (`stream_text` is no longer Anthropic-only; cross-route `refusal_model`;
`reasoning_for`), `docs/summarizer.md` where `summ_fallback` is specified, and the
`stream_json_async` / `mcjudge.run_calls` docstrings ("same route" wording).

## Tests (offline; `tests/conftest.py` fakes)

- `test_llm_text.py`: OpenRouter free text through a fake streaming client: plain text;
  `thinking` True / False request bodies; empty + `length` doubles to the ceiling then returns
  `""`; `content_filter` and a moderation 403 -> `REFUSED` / `None`; an SDK-shaped
  `APIError` raised from the stream iterator, and `finish_reason == "error"`, are retried; spend tallies. The existing Anthropic tests pass unedited.
- `test_llm_refusal_rerun.py`: cross-route re-run both directions for JSON and text (second
  client built, closed, right reasoning / max_tokens / temperature per route; missing fallback
  key raises before the first call; same-route path builds one client as before);
  `refusal_model == model` still raises.
- `reasoning_for` / `judge_config.resolve` table test.
- digest: `summ_fallback=none+openai/gpt-6-luna` parses; a cross-route re-run sends OpenRouter
  reasoning; a same-route one sends `s.reasoning`.
- families: for each of the four, a non-pinned judge with a declined call is re-run on the
  fallback and recorded; `opts=fallback=none` leaves it lost; a judge equal to the fallback
  model gets none; a bad `fallback=` value exits 2. agentic: the three native stages run on an
  OpenRouter judge end to end (fake).
- structured OpenRouter refusal (`content_filter`, `message.refusal`) -> `REFUSED_JSON` and the
  re-run; `refusal_reasoning=` is what the re-run sends; `accept_served=False` re-asks a
  served row (a fallback-on run, then `fallback=none` on the same out dir, per family).
- Step 0's pin capture test passes unedited.
- New fakes are additive (a new `tests/openrouter_fakes.py`: an OpenRouter-shaped client whose
  responses can carry `finish_reason` / `message.refusal`, and a streaming one); additive
  helpers are not "edits of a pre-existing test". The "missing fallback key raises" test does
  not use `fake_client_installer` (it patches `llm.api_key`).
- **No pre-existing test is edited** except exactly these four, which pin deleted behaviour
  (the fourth, `tests/test_agentic_misalignment.py::test_non_claude_judge_raises`, the family
  twin of the first, was found by the implementer and left red; it is deleted, replaced by
  `tests/test_fallback_0096.py::test_agentic_native_stages_run_on_an_openrouter_judge`):
  `tests/test_llm_text.py::test_openrouter_model_raises`, the `"none+gpt-6"` entry of the bad
  list in `tests/test_llm_refusal_rerun.py` (~l.311), and the `default+gpt-5` / `none+gpt-5`
  params in `tests/test_digest_hierarchical.py` (~l.395). Each is listed in the PR body with
  its old and new assertion. Any other red pre-existing test is a stop-and-report, never an
  edit.

## Live smoke (after CI, before merge)

OpenRouter is only called from Modal (secret `openrouter`), never from the dev box; the smoke
also needs Anthropic credentials in the container (the Sonnet 5 digest and the Opus 5 / Sonnet
5.5 fallbacks). From Modal:
`llm.stream_text` on `openai/gpt-6-luna`, one prompt each for `thinking=True` / `False` and one
with `max_tokens=16` (budget doubling), then `wsbench judge family=agentic_misalignment
judge_model=openai/gpt-6-luna limit=1` on existing readouts, native and summary, and one
model_multihop `limit=3` run (its `temperature=0.0` under `require_parameters`). The PR records
the outcome; a request-shape error found here is fixed in the PR, not after it.

## Files

```
plans/0096-luna-judge.md                          new
plans/0005-agentic.md                             one-line superseded note
src/wsbench/llm.py                                steps 1-2
src/wsbench/judge_config.py                       reasoning_for / constants re-export
src/wsbench/mcjudge.py                            refusal_reasoning, accept_served
src/wsbench/digest.py                             step 3
src/wsbench/family.py                             fallback_on
src/wsbench/evals/{hinted_cutoff,model_multihop,agentic_misalignment,jailbreak_recognition}/judge.py   step 4
README.md, CLAUDE.md, docs/summarizer.md, evals/<4 families>/README.md   step 5
tests/test_pin_requests_0096.py, tests/golden/pin_requests_0096.json, tests/golden/README.md   step 0
tests/openrouter_fakes.py                         new fakes
tests/test_llm_text.py, test_llm_refusal_rerun.py, + family / digest tests   new cases
```

---

# Part 2 (Camila 2026-11-18): the direct-OpenAI route, and the summarizer follows the judge

Camila, on the review of part 1: "we can use openai wif, if we need openrouter just build it
for that. the summarizer should follow the judge based on the experiment we ran when we tested
how good luna was as the summarizer."

Why: the `openrouter` Modal secret is provider-blocked, and every Luna run of record (plan 0059
judge sweep, qmain `luna_lite`) went to OpenAI directly through workload identity federation,
with code that lives only on the unmerged branch `origin/camila/judge-sweep` (1d5fa75b; no
usable merge base with today's main, so this is a PORT with that branch as the reference, read
with `git show origin/camila/judge-sweep:<path>`; never a merge). The experiment: plan 0059
**Arm B** (the swept model writes the digest AND judges). Luna is the cheapest Arm B match to
Opus (`f64-lite-L32`: agreement 0.973, 3 / 18 flagged families, "matches"), while as judge of
Opus digests (Arm A) it does not match. Arm B's Luna configuration, the one validated:
`summ_model=openai/gpt-6-luna, summ_fallback=none, summ_effort=default` (which sent NO
reasoning field for a non-Claude digest), `summ_context=1050000`, `WSBENCH_OPENAI_ROUTE=wif`,
`WSBENCH_OPENROUTER_MAX_OUT=32000`, `judge_effort=low` (`default` for hinted_cutoff,
introspection, model_multihop).

**Invariant (unchanged from part 1, restated).** With `WSBENCH_OPENAI_ROUTE` unset and
`args.judge.pinned`, requests, cache keys, fingerprints and `config` are byte-identical:
`tests/test_pin_requests_0096.py` and its golden pass unedited, and so does every test of
part 1. No digest fingerprint of a `claude-*` digest model moves.

## 6. `llm.py`: route `openai` (port of plan 0059 addendum A, extended to free text)

- `WSBENCH_OPENAI_ROUTE=wif`: an `openai/*` id that is not `openai/gpt-oss*` routes to
  `"openai"`; unset = today's routing; any other value is a `JudgeConfigError`. `Route` gains
  `"openai"`; `api_key` returns `""` for it; `_make_client("openai", ...)` returns the branch's
  `_WifClient(ati_remote.Clients("openai-wif"))` (an `ati_remote.AbortError` ->
  `JudgeConfigError`). `ati_remote` is already on main (the ATI panel uses it); import lazily.
- Structured calls: port `_openai_once` (`max_completion_tokens`, `reasoning_effort` from the
  reasoning's `effort`, no `temperature`, no OpenRouter `extra_body`, model id through
  `ati_remote.route_model(model, "openai-wif")`, the 401 re-exchange loop up to
  `ati_remote.AUTH_REFRESHES`) and dispatch it from `_one`. Its response is read by the SAME
  rule as part 1's `_openrouter_once` (refusal = `content_filter` or `message.refusal` with no
  content; cost 0 on this route; token usage tallied): factor that rule into one helper both
  call, without changing what `_openrouter_once` returns for any input part 1's tests cover.
  `temperature` given to an `openai`-route batch is dropped with one printed line, as on the
  Anthropic route (so model_multihop's `temperature=0.0` cannot 404 there).
- Free text: `_openai_text_once`, the third twin (contract of `_openrouter_text_once`):
  streaming `chat.completions.create(stream=True, stream_options={"include_usage": True},
  max_completion_tokens=budget, messages=[user])`, `thinking=True` -> no `reasoning_effort`
  (the model's default), `thinking=False` -> `reasoning_effort="minimal"`; the same budget
  doubling to `_TEXT_BUDGET_CEILING`, refusal and mid-stream error rules; the 401 re-exchange.
  `_one_text` dispatches by route; a mid-stream status-less `APIError` is classified by its
  body code on both chat-completions routes (`openrouter`, `openai`).
- Too-long inputs on the `openai` route: a 400 whose error code is `context_length_exceeded`
  (or whose message holds one of the branch's `OPENROUTER_TOO_LONG` phrases) is
  `TOO_LONG_JSON` under `mark_refusals` (the digest then halves the bundle), exactly as
  "prompt is too long" is on the Anthropic route. The OpenRouter route's rule is NOT changed.
- `WSBENCH_OPENROUTER_MAX_OUT=<n>` is ported under its existing name (existing drivers set
  it): on the `openrouter` and `openai` routes it replaces every call's output cap; unset =
  today's caps; a non-positive / non-integer value is a `JudgeConfigError`. Never read on the
  Anthropic route. `_DEFAULT_MAX_TOKENS["openai"] = 8000` as on the branch.
- Part 1's route-generic pieces cover three routes: `reasoning_for` treats `openai` as
  `openrouter` (non-Anthropic keys; the minimal default); a cross-route refusal re-run may go
  to or from `openai`; `temperature` is sent only to an `openrouter` re-run.
- `count_tokens` stays Anthropic-only (the digest already degrades to its estimate).

## 7. `judge_effort=` (port of plan 0059)

`judge` / `run` key `judge_effort=minimal|low|medium|high|default` for non-Claude judges only
(a `claude-*` judge with it exits 2): replaces the reasoning `resolve` would give with
`{"effort": <level>}`, or `None` for `default`. Port `judge_config.resolve(effort=)`, the CLI
field, `runner` plumbing and `judge_argv` emission (only when given) from the branch. Unset =
today's resolution, byte-identical. It is in the judge fingerprint through `judge.reasoning`
as any reasoning is (no new key).

## 8. `digest.py`: a non-Claude digest model runs as Arm B ran

- `digest_reasoning(model, effort)` (port): `claude-*` -> `{"anthropic_effort": effort}`
  exactly as now; any other model -> `None` at `summ_effort=default`, else `{"effort":
  effort}`. `settings` uses it, so a Luna digest no longer sends `{"anthropic_effort": ...}`
  as OpenRouter / OpenAI reasoning (the item part 1 listed as out of scope). This moves the
  fingerprint of NON-Claude digests only (stated: existing Luna digest caches written by
  main's code, if any, are re-asked; the sweep branch's caches used this same value).
  `_default_digest` and `Settings.reasoning_on` (part 1) are updated to the same rule.
- A FAMILY-DEFAULT `summ_fallback` becomes `none` when the digest model is not `claude-*`
  (the validated Arm B instrument; `config.summarizer` shows `fallback: none`). An EXPLICIT
  `opts=summ_fallback=` is honoured for any digest model: `none+<model>` on either route as
  part 1 built it; an explicit `default` / `default+<model>` with a non-Claude digest model
  exits 2 (the server-side fallback is an Anthropic feature; the branch's rule and message).
- `summ_context=N` (port): the context window of the digest's budget arithmetic, default
  today's 1 000 000, values below 128 000 exit 2, in `KNOWN_KEYS`, in `Settings.to_json` only
  when not the default. Luna needs none (its 1.05M window is above the default); ported so a
  smaller-context digest model has a correct budget.

## 9. The summarizer follows the judge

The digest model of a run is, in order: `opts=summ_model=`; else **the judge model when the
judge is an override on a non-Anthropic route** (`not args.judge.pinned and
llm.route(args.judge.model) != "anthropic"`); else the family's `aux_models["digest"]` pin;
else `digest.DEFAULT_MODEL`. One place decides it (`digest.settings`), so the digest
preflight, `summarizer_judge`, stamps and `config.summarizer.model` all agree.

- Scope, stated: only a non-Claude override judge moves the digest. A `claude-*` override
  judge (`judge_model=claude-opus-5-5` on agentic, the Sonnet 5.5 refusal slot, any existing
  Claude judge-swap workflow) keeps the digest it has today; `summ_model=` still says
  otherwise. "Luna judge on Opus digests" (Arm A) is `opts=summ_model=claude-opus-5-5`.
- This replaces part 1's answer "the digest pins stay" for a Luna judge: under it, agentic and
  jailbreak digest on Luna too, and by section 8 their `none+claude-opus-5` family default
  digest fallback is off unless given explicitly.
- Part 1's JUDGE-call fallbacks are unchanged by this section (still on under a Luna judge
  unless `opts=fallback=none`; the experiment ran without them, the report asked for them).
- `runner`'s digest preflight and `judge_family` already take the model from
  `digest.settings` / `preflight_judge`; they must pass the resolved judge so the rule sees
  it (a preflight of the wrong digest model is a bug this section must not introduce).
- README §Judges states the rule and the experiment it rests on (plan 0059 Arm B, cell
  `f64-lite-L32`), and that the validated Luna instrument is `judge_effort=low`.

## Tests (part 2, offline)

- route: env unset = routing unchanged for `openai/*`; `wif` routes `openai/gpt-6-luna` to
  `openai` and leaves `openai/gpt-oss-*` on OpenRouter; a bad value raises.
- `_openai_once` / `_openai_text_once` through fakes of `ati_remote.Clients` (the branch's
  tests `tests/test_llm_openai_route.py` or equivalent are the starting point: port them):
  request kwargs, no temperature, 401 re-exchange then success, a last 401 fatal, refusal,
  length + budget doubling, too-long -> `TOO_LONG_JSON`, `MAX_OUT` cap, cross-route refusal to
  and from `openai`.
- `judge_effort`: resolution table; a Claude judge exits 2; unset is byte-identical.
- digest: `digest_reasoning` table; Claude digest fingerprints unchanged (the existing pins in
  `tests/test_digest_hierarchical.py` pass unedited); family-default fallback off for a
  non-Claude digest, explicit `none+<model>` kept, explicit `default` exits 2; `summ_context`.
- follow rule: for a family with no digest pin and for agentic / jailbreak: Luna override ->
  Luna digest; `summ_model=` wins; a Claude override keeps today's digest; a pinned judge keeps
  today's digest; the digest preflight asks the followed model.
- Part 1's tests that assert a Luna-judge run digests on the family pin or uses the family's
  digest fallback are part 1's own tests (written in this PR, not pre-existing on main): they
  are updated to the new rule and listed in the PR body. **Tests that exist on `origin/main`
  stay unedited**; a red one is a stop-and-report.

## Live smoke (part 2; replaces part 1's)

From Modal, env `camila-blank`, secret `openai-wif`, `WSBENCH_OPENAI_ROUTE=wif`: (a)
`llm.stream_text` on `openai/gpt-6-luna`, `thinking` True / False and a tiny budget; (b) one
structured call with `temperature=0.0`; (c) `wsbench judge` with `judge_model=openai/gpt-6-luna
judge_effort=low opts=fallback=none` on the toy readouts of agentic_misalignment (native and
summary), model_multihop and jailbreak_recognition (summary). The container holds no Anthropic
credentials, so a Claude call anywhere in (c) is a failure of section 9. Merge only after it.

## Files (part 2)

```
src/wsbench/llm.py                  route openai, _WifClient, _openai_once, _openai_text_once, MAX_OUT, too-long
src/wsbench/judge_config.py, cli.py, runner.py   judge_effort
src/wsbench/digest.py               digest_reasoning, fallback default, summ_context, follow rule
README.md, CLAUDE.md, docs/summarizer.md, evals/{agentic_misalignment,jailbreak_recognition}/README.md
tests/test_llm_openai_route.py, tests/test_digest_follow_0096.py, + updates to this PR's own tests
```

## Part 2 rulings (critique round 1; where a ruling and a sentence above disagree, the ruling wins)

R1. **Token-exchange errors (section 6).** In `_one` and `_one_text`, as on the branch: a
`JudgeConfigError` raised inside a call (a failed WIF exchange, `ati_remote.AbortError`) is
re-raised first, never degraded to `None`; `ati_remote.TransientExchangeError` (token endpoint
429 / 5xx) is transient. A last 401 is fatal; a 403 on the `openai` route is fatal even when
it names flagged input (the moderation carve-out stays OpenRouter-only). One test each.

R2. **Too-long inputs: the branch's `_too_long`, ported as it is.** On the `openrouter` and
`openai` routes the `OPENROUTER_TOO_LONG` phrases count only while
`WSBENCH_OPENROUTER_MAX_OUT` is set (without the cap a context-length 400 can be the output
request); otherwise only "prompt is too long", as today. The `context_length_exceeded` code
check of section 6 is dropped. Env unset = today's behaviour on every route.

R3. **`_chat_result`'s length rule is ported** into the helper both chat routes share: an
unparsable body with `finish_reason == "length"` is one failed call (`None`, one counted
error, never retried). The refusal rule stays part 1's (a `message.refusal` counts only with
empty content; the branch counted any), on purpose. The helper keeps `_openrouter_once`'s
signature usable by the conftest shim (`mark_refusals` optional).

R4. **`WSBENCH_OPENROUTER_MAX_OUT` sites.** It caps by the route of the model actually called:
`stream_json_async`'s primary and its refusal re-run each by their own route (an Anthropic
call never reads it; an `openai` / `openrouter` fallback of an Anthropic primary does). Free
text: it is the STARTING budget on the two chat routes; doubling still runs to
`_TEXT_BUDGET_CEILING`. The digest's own cap (`Settings.max_tokens`) is overridden inside
`llm` for a chat-route digest model, as on the branch. Tests: both cross-route directions.

R5. **`args.judge is None`** (`digest._probe`, used by `validate`, `resolve_layer_mode`,
`preflight_judge`): the follow rule is "a judge is present, not pinned, and on a
non-Anthropic route". `digest.preflight_judge(extra, aux_models, judge=None)`: the new
argument is optional and `None` means no follow (`tests/test_jailbreak_recognition.py` calls
it with two arguments and must stay green); `runner` passes the resolved judge. Section 8's
exit 2 for an explicit `default` fallback on a followed digest surfaces wherever `settings`
first sees the judge (the runner's digest preflight): one exit 2 before any family starts.
The explicit-fallback test reads `args.extra` BEFORE `_with_family` merges the defaults.

R6. **`judge_effort` plumbing.** `judge_config.resolve(..., effort=)` (sets `pinned=False`;
`fail` imported lazily); every resolve site passes it: `cli.JudgeFamily`, `runner._one` (the
process-mode child path) and `runner.run_families`' resolution; `runner.judge_argv` emits
`judge_effort=<v>` only when given (new code: the branch had no process mode); `run.json`
gets `judge_effort` only when given. Read it with `getattr(args, "judge_effort", None)`
(hand-built namespaces in `tests/test_run_procs.py` lack it).

R7. **What a bare `judge_model=openai/gpt-6-luna` runs, stated in README, not defaulted.**
The follow rule sets the digest model and section 8's fallback only. The judge runs at
`{"effort": "minimal"}` unless `judge_effort=` is given. The instrument plan 0059 validated
is, explicitly: `WSBENCH_OPENAI_ROUTE=wif WSBENCH_OPENROUTER_MAX_OUT=32000`,
`judge_effort=low` (`default` for hinted_cutoff, introspection, model_multihop: separate
jobs), `opts=summ_context=1050000`; README §Judges gives it as a recipe. Not validated by the
sweep, and README says so: agentic_misalignment with a Luna digest and judge (the sweep ran
agentic for `claude-*` only), whose free-text stages ignore `judge_effort`.

R8. **Stamps and reports.** The literals `+sonnet-digest+opus5-fb` (agentic, jailbreak) stay in
a Luna row's `prompt_version`, as they do under `summ_model=` today; `config.summarizer.model`
is the record. `report alt_judge=` matches rows on `config.summarizer`, so a Luna column
beside an Opus row needs `opts=summ_model=claude-opus-5-5`: one README sentence. The regex
families' digests follow too (consistent with Arm B).

R9. **`Settings.reasoning_on(model)`** = `digest_reasoning(model, <the run's summ_effort>)`
for every client-side re-run: a `claude-*` refusal model gets `{"anthropic_effort": effort}`
whatever the digest model's route (identical to today for Claude -> Claude); a non-Claude
one gets `None` at `default`, else `{"effort": effort}`. `_default_digest` is unchanged.
Part 1's test of a Claude digest with a Luna refusal model changes accordingly.

R10. **Credentials on the `openai` route.** `api_key` returns `""` there, so part 1's up-front
checks would pass vacuously: for an `openai`-route fallback, `family.require_fallback_key` and
the `digest.collapse` check build the WIF token source instead and turn its
`ati_remote.AbortError` into the same `JudgeConfigError` with the `opts=fallback=none` hint.

R11. **Tests and fixtures.** `tests/conftest.py` gains an autouse fixture clearing
`WSBENCH_OPENAI_ROUTE` and `WSBENCH_OPENROUTER_MAX_OUT` (an additive fixture is not an edit
of a test). `llm.route` now raises on a bad env value: every caller (`judge_config.resolve`
in `cli` / `runner`, `digest.settings`) must end as exit 3 with the message, not a traceback.
The branch tests to port from are `tests/test_llm_sweep.py` (~l.476-560),
`tests/test_digest_sweep.py`, `tests/test_judge_effort_ledger.py`. Any test this PR itself
added (not on `origin/main`) may be updated to the part 2 rules, e.g.
`tests/test_fallback_0096.py`'s model_multihop summary case, whose "every call has
temperature 0.0" assertion now also sees Luna digest calls; each such update is listed in the
PR body. Part 1's header lines "No ... fingerprint ... moves" and "The digest pins stay" are
superseded by part 2 for non-Claude digests and for a Luna judge.

R12. **Smoke.** Without Anthropic credentials the smoke cannot exercise a cross-route judge
fallback from the `openai` route; accepted. Section 6's "cannot 404" is "cannot be rejected".

R13. (round 2) R9: if `Settings` gains an `effort` field it stays OUT of `Settings.to_json`
(no Claude digest fingerprint may move); recovering the effort from `reasoning` is equally
fine. R2: the `openai`-route too-long test sets `WSBENCH_OPENROUTER_MAX_OUT`, with a companion
case unset that is a plain error.
