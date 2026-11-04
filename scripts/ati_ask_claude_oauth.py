"""ATI panel answers from the Claude slot with an OAuth bearer token, capped and counted.

``text_inversion.ask_claude`` unchanged (panel template, draws, retry and refusal rules); only its
SDK client is built from ``ANTHROPIC_AUTH_TOKEN``. Usage: evals/baselines/README.md.
"""

import argparse
import atexit
import json
import sys
import time
from pathlib import Path

import anthropic

from wsbench import llm
from wsbench.baselines import text_inversion as ti

COUNT = {"calls": 0}
_REAL = anthropic.AsyncAnthropic


def _client_factory(cap: int, model: str):
    """An ``AsyncAnthropic`` stand-in for ``text_inversion._ask``: the bearer-token client with
    the OAuth beta header, every ``messages.create`` (preflight and retries too) counted and
    refused past ``cap``."""

    def make(*_a, **kw):
        key = llm.api_key(model)
        if not key.startswith(llm.OAUTH_PREFIX):
            raise SystemExit("set ANTHROPIC_AUTH_TOKEN (an OAuth access token) for this process")
        c = _REAL(
            auth_token=key[len(llm.OAUTH_PREFIX) :],
            api_key=None,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
            max_retries=kw.get("max_retries", 4),
            timeout=kw.get("timeout", 900),
        )
        create = c.messages.create

        async def counted(*a, **k):
            if COUNT["calls"] >= cap:
                raise SystemExit(f"Claude call cap {cap} reached")  # not retried by _ask_one
            COUNT["calls"] += 1
            return await create(*a, **k)

        c.messages.create = counted
        return c

    return make


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="the panel root (prompts.jsonl)")
    ap.add_argument("--families", required=True, help="comma list")
    ap.add_argument("--slot", default="opus", choices=sorted(ti.CLAUDE_SLOTS))
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--cap", type=int, required=True, help="max messages.create calls")
    a = ap.parse_args()
    model = ti.CLAUDE_SLOTS[a.slot]
    anthropic.AsyncAnthropic = _client_factory(a.cap, model)
    t0 = time.time()

    def record() -> None:
        row = {
            "t": time.time(),
            "stage": "ati_ask_claude",
            "model": model,
            "calls": COUNT["calls"],
            "wall_s": round(time.time() - t0, 1),
        }
        with (a.out / "ledger.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    atexit.register(record)
    n_fail = ti.ask_claude(a.out, ti.DRAWS, a.concurrency, a.families.split(","), a.slot)
    print(f"failed answers: {n_fail}; Claude calls this pass: {COUNT['calls']}", flush=True)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
