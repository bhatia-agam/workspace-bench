# Judge backends: live and Message Batches

Claude judge calls (`claude-*` models) can travel two ways. Both send the same requests and fill
the same caches, so a run can start on one and finish on the other.

| backend | how | price | speed |
|---|---|---|---|
| `live` (default) | one Messages request per call, `concurrency=` at a time | list price | bounded by `concurrency=`, `rpm=`, `itpm=` and the account's rate limits |
| `batches` | the calls of each stage go out as [Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing) | half price on every token | outside the live rate limits; each batch ends when the API gets to it: from 1 to over 20 minutes in our checks, at most 24 h, and every stage of a run waits for its own batch |

## Turn it on

```bash
uv run wsbench run all=True readouts_root=readouts/mylens out=outputs/judged/mylens judge_backend=batches
uv run wsbench judge family=multihop readouts=... out=... judge_backend=batches
# or, for any command that judges (children of `run` inherit it):
export WSB_JUDGE_BACKEND=batches
```

Leave it out (or `judge_backend=live`) for today's behaviour. From Python:
`llm.stream_json(..., backend="batches")`.

## What changes and what does not

- **Same requests.** A batch entry is the live call's request (`llm.anthropic_params`: model,
  `max_tokens`, the cached system block, messages, `output_config`), minus the HTTP `timeout`.
- **Same cache keys and results files.** Fingerprints do not include the backend. `cells.jsonl`
  rows written by either backend are hits for the other; rerun into the same `out=` to resume.
- **Stages still run in order.** A family that digests per layer, merges, then judges makes
  three rounds of batches, one after another.
- **Anything a batch does not settle is re-run live**, with the live path's retries: errored,
  expired, canceled and missing entries, unparsable bodies, and a refused call when the family
  uses the server-side refusal fallback (`fallbacks=` cannot be set on a batch request). A
  round with fewer than 20 calls is not worth a round trip and stays live.
- **Live only:** OpenRouter models, the free-text stages of `agentic_misalignment`
  (`llm.stream_text`), preflights and `count_tokens`.
- **Token ledger.** `$WSB_TOKEN_LEDGER` rows of batch calls carry `"batch": true` (bill them at
  half price).

## Resume without paying twice

Set a journal directory and keep it with the run's outputs:

```bash
export WSB_JUDGE_BATCH_DIR=outputs/judged/mylens/.judge_batches
```

Every submitted batch is recorded there. If the process stops while a batch is running (a
revoked token, a killed container), the next run with the same directory collects that batch
instead of sending its requests again. Without the variable an interrupted run re-sends them.

## Settings

| variable | default | meaning |
|---|---|---|
| `WSB_JUDGE_BACKEND` | `live` | `live` or `batches` |
| `WSB_JUDGE_BATCH_DIR` | unset | journal directory (see above) |
| `WSB_JUDGE_BATCH_MAX_REQUESTS` | 5000 | requests per batch (the API allows 100,000) |
| `WSB_JUDGE_BATCH_MAX_BYTES` | 64000000 | request bytes per batch (the API allows 256 MB) |
| `WSB_JUDGE_BATCH_MIN_REQUESTS` | 20 | a smaller round runs live |
| `WSB_JUDGE_BATCH_POLL_SECONDS` | 20 | longest wait between status checks |

## Sizing the live backend

`concurrency=`, `rpm=` and `itpm=` set the live throughput (`docs/producing_readouts.md`,
"Throughput"); none is hardcoded in the package, and `WSB_SLOTS=<dir>:<n>` shares one cap between
several `wsbench judge` processes. Size them to the account, not to a habit:

1. Read the account's limits from any response's `anthropic-ratelimit-*` headers (requests,
   input tokens and output tokens a minute; cached input does not count as input).
2. Output tokens a minute (OTPM) is the limit a judge run meets first:
   `calls in flight x output tokens per call x 60 / seconds per call`, summed over every process
   on the account, must stay under it.

Measured on one multihop family with `claude-opus-5-5` (50 verdict, 30 per-layer digest and
10 merge calls; 0 retries and 0 rate-limit errors at `concurrency=12` and at 64):

| call | uncached input | cached input | output | seconds |
|---|---|---|---|---|
| per-layer digest | 1,300 tok | 1,900 tok | 1,550 tok | 20 to 25 |
| merge of the layers' digests | 20,900 tok | 1,900 tok | 7,400 tok | 140 |
| verdict | 7,000 tok | 760 tok | 50 tok | 4 |

So one in-flight digest call uses about 4,000 OTPM, and one in-flight verdict call about 105,000
input tokens a minute. On an account with 15M OTPM, 150,000 requests a minute and 100M input
tokens a minute, `concurrency=12` per family uses about 0.3% of the output limit. Recommended
there: `concurrency=64` per family with up to eight families at once and
`WSB_SLOTS=<dir>:500` as the shared cap: about 2M OTPM (13%) while digesting and about half the
input limit while judging (the default `itpm=60000000` paces that stage). 64 was the largest
value tested; go up in steps and watch `retries=` in the family log.

## Credentials the environment cannot carry

`llm.use_anthropic_client(factory)` makes every Anthropic client with `factory()` (an
`AsyncAnthropic`), e.g. one built with workload identity federation and a token provider.
