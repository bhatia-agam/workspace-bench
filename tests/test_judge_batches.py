"""Offline tests for the Message Batches judge backend: a fake Anthropic client, no network."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from wsbench import judge_batches, llm, mcjudge
from wsbench.cache import Cache
from wsbench.judge_config import ResolvedJudge
from wsbench.llm import JudgeConfigError, Spend, schema_block, stream_json

SCHEMA = schema_block("t", {"a": {"type": "integer", "minimum": 0}}, ["a"])
CLAUDE = "claude-opus-5-5"
REASONING = {"anthropic_effort": "medium"}


class AuthenticationError(Exception):
    status_code = 401


class APIConnectionError(Exception):
    status_code = None


class NotFoundError(Exception):
    status_code = 404


def _message(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=7,
            output_tokens=3,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=5,
        ),
    )


def _user(params: dict) -> str:
    return params["messages"][0]["content"]


def _answer(params: dict) -> Any:
    """The default batch outcome: a success whose object echoes the prompt number."""
    return SimpleNamespace(
        type="succeeded", message=_message(json.dumps({"a": int(_user(params))}))
    )


class Server:
    """What outlives one client: the submitted batches (as the API keeps them between runs)."""

    def __init__(self) -> None:
        self.batches: dict[str, list[dict]] = {}


class FakeClient:
    """``AsyncAnthropic``-shaped: ``messages.create`` (live) and ``messages.batches``."""

    def __init__(self, server: Server | None = None, *, answer=_answer, polls: int = 1):
        self.server = server or Server()
        self.answer = answer
        self.polls = polls  # retrieve() calls before a batch reads "ended"
        self.live: list[dict[str, Any]] = []
        self.beta_live: list[dict[str, Any]] = []
        self.created: list[list[dict]] = []
        self.retrieved: dict[str, int] = {}
        self.fail_retrieve: BaseException | None = None
        self.fail_results: list[BaseException] = []
        self.closed = False
        batches = SimpleNamespace(
            create=self._create, retrieve=self._retrieve, results=self._results
        )
        self.messages = SimpleNamespace(create=self._live, batches=batches)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta_live))

    async def _live(self, **kw: Any) -> Any:
        self.live.append(kw)
        return _message(json.dumps({"a": int(_user(kw)) + 1000}))  # +1000: answered live

    async def _beta_live(self, **kw: Any) -> Any:
        self.beta_live.append(kw)
        return _message(json.dumps({"a": int(_user(kw)) + 2000}))

    async def _create(self, *, requests: list[dict]) -> Any:
        self.created.append(requests)
        batch_id = f"msgbatch_{len(self.server.batches)}"
        self.server.batches[batch_id] = requests
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    async def _retrieve(self, batch_id: str) -> Any:
        if self.fail_retrieve is not None:
            raise self.fail_retrieve
        if batch_id not in self.server.batches:
            raise NotFoundError(batch_id)
        n = self.retrieved[batch_id] = self.retrieved.get(batch_id, 0) + 1
        status = "ended" if n >= self.polls else "in_progress"
        return SimpleNamespace(id=batch_id, processing_status=status)

    async def _results(self, batch_id: str) -> Any:
        async def stream() -> Any:
            for k, req in enumerate(reversed(self.server.batches[batch_id])):  # any order
                if k == 1 and self.fail_results:
                    raise self.fail_results.pop(0)
                result = self.answer(req["params"])
                if result is not None:  # None: the batch has no row for this request
                    yield SimpleNamespace(custom_id=req["custom_id"], result=result)

        return stream()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _fast(monkeypatch, tmp_path):
    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(llm, "_sleep", no_sleep)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("WSB_JUDGE_BATCH_MIN_REQUESTS", "1")
    for name in ("WSB_JUDGE_BACKEND", "WSB_JUDGE_BATCH_DIR", "WSB_TOKEN_LEDGER"):
        monkeypatch.delenv(name, raising=False)


def _client(monkeypatch, client: FakeClient) -> FakeClient:
    monkeypatch.setattr(llm, "_make_client", lambda r, k: client)
    return client


def _prompts(n: int) -> list[tuple[str, str]]:
    return [("judge these", str(i)) for i in range(n)]


def _run(n: int = 4, **kw: Any) -> tuple[dict[int, Any], Spend]:
    got: dict[int, Any] = {}
    kw.setdefault("backend", "batches")
    spend = stream_json(
        _prompts(n), schema=SCHEMA, model=CLAUDE, on_result=got.__setitem__, rpm=6e6, **kw
    )
    return got, spend


# ---------------------------------------------------------------- request parity


def test_batch_requests_are_the_live_requests(monkeypatch):
    live = _client(monkeypatch, FakeClient())
    _run(3, backend="live", reasoning=REASONING, max_tokens=777, timeout=12.0)
    batched = _client(monkeypatch, FakeClient())
    _run(3, reasoning=REASONING, max_tokens=777, timeout=12.0)
    assert len(live.live) == 3 and batched.live == [] and len(batched.created) == 1
    want = sorted(({k: v for k, v in kw.items() if k != "timeout"} for kw in live.live), key=_user)
    got = sorted((r["params"] for r in batched.created[0]), key=_user)
    assert got == want  # same model, max_tokens, cached system block, schema, effort
    assert all(kw["timeout"] == 12.0 for kw in live.live)
    assert got[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert got[0]["output_config"]["effort"] == "medium"
    assert "minimum" not in json.dumps(got[0]["output_config"])  # anthropic_schema applied


def test_custom_ids_are_stable_valid_and_unique():
    p = llm.anthropic_params("s", "u", schema=SCHEMA, model=CLAUDE, max_tokens=5)
    q = llm.anthropic_params("s", "v", schema=SCHEMA, model=CLAUDE, max_tokens=5)
    ids = judge_batches.unique_ids([p, q, p])
    assert ids == judge_batches.unique_ids([dict(p), dict(q), dict(p)])
    assert len(set(ids)) == 3 and ids[0][:-2] == ids[2][:-2] and ids[0] != ids[1]
    assert all(len(i) <= 64 and i.replace("-", "").isalnum() for i in ids)


def test_env_and_cli_select_the_backend(monkeypatch, tmp_path):
    client = _client(monkeypatch, FakeClient())
    _run(2, backend=None)
    assert len(client.live) == 2 and client.created == []  # the default is live
    monkeypatch.setenv("WSB_JUDGE_BACKEND", "batches")
    _run(2, backend=None)
    assert len(client.live) == 2 and len(client.created) == 1
    monkeypatch.setenv("WSB_JUDGE_BACKEND", "nope")
    with pytest.raises(JudgeConfigError, match="live or batches"):
        _run(2, backend=None)
    from wsbench import cli

    cmd = cli.JudgeFamily()
    assert cmd.judge_backend == ""
    cmd.judge_backend = "soon"
    with pytest.raises(ValueError, match="judge_backend"):
        cmd.finalize()


def test_non_anthropic_models_and_small_lists_stay_live(monkeypatch):
    monkeypatch.setenv("WSB_JUDGE_BATCH_MIN_REQUESTS", "5")
    client = _client(monkeypatch, FakeClient())
    got, _ = _run(4)
    assert client.created == [] and sorted(got.values(), key=str) == [
        {"a": 1000 + i} for i in range(4)
    ]
    got, _ = _run(5)
    assert len(client.created) == 1 and got == {i: {"a": i} for i in range(5)}


# ---------------------------------------------------------------- results


def test_results_land_by_index_with_usage_and_ledger(monkeypatch, tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("WSB_TOKEN_LEDGER", str(ledger))
    client = _client(monkeypatch, FakeClient(polls=3))
    got, spend = _run(4)
    assert got == {i: {"a": i} for i in range(4)}
    assert spend.calls == 4 and spend.input_tokens == 28 and spend.errors == 0
    assert client.retrieved == {"msgbatch_0": 3} and client.closed
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert len(rows) == 4 and all(r["batch"] is True and r["cache_read"] == 5 for r in rows)
    _run(2, backend="live")
    rows = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert all("batch" not in r for r in rows[4:])  # live rows are unchanged


def test_requests_are_chunked(monkeypatch):
    monkeypatch.setenv("WSB_JUDGE_BATCH_MAX_REQUESTS", "3")
    client = _client(monkeypatch, FakeClient())
    got, _ = _run(7)
    assert [len(b) for b in client.created] == [3, 3, 1]
    assert got == {i: {"a": i} for i in range(7)}


@pytest.mark.parametrize("kind", ["errored", "expired", "canceled", "missing", "garbled"])
def test_unsettled_entries_are_rerun_live(monkeypatch, kind):
    def answer(params: dict) -> Any:
        if _user(params) not in ("1", "3"):
            return _answer(params)
        if kind == "missing":
            return None
        if kind == "garbled":
            return SimpleNamespace(type="succeeded", message=_message("not json"))
        return SimpleNamespace(type=kind, error=SimpleNamespace(type="api_error"))

    client = _client(monkeypatch, FakeClient(answer=answer))
    got, spend = _run(5)
    assert sorted(_user(kw) for kw in client.live) == ["1", "3"]  # only those two, live
    assert got == {0: {"a": 0}, 1: {"a": 1001}, 2: {"a": 2}, 3: {"a": 1003}, 4: {"a": 4}}
    assert spend.errors == 0


def test_max_tokens_stop_is_a_failed_call_as_live(monkeypatch):
    def answer(params: dict) -> Any:
        return SimpleNamespace(type="succeeded", message=_message("{", "max_tokens"))

    client = _client(monkeypatch, FakeClient(answer=answer))
    got, spend = _run(2)
    assert got == {0: None, 1: None} and spend.errors == 2 and client.live == []


def test_refusals(monkeypatch):
    def answer(params: dict) -> Any:
        if _user(params) == "1":
            return SimpleNamespace(type="succeeded", message=_message("", "refusal"))
        return _answer(params)

    # no server-side fallback: the refusal is the answer, as live (marked or None)
    client = _client(monkeypatch, FakeClient(answer=answer))
    got, spend = _run(3, mark_refusals=True)
    assert got[1] == llm.REFUSED_JSON and spend.refusals == 1 and client.live == []
    got, _ = _run(3)
    assert got[1] is None
    # fallbacks= cannot ride in a batch: the declined request re-runs live with it
    client = _client(monkeypatch, FakeClient(answer=answer))
    got, spend = _run(3, fallbacks="default")
    assert all("fallbacks" not in r["params"] for r in client.created[0])
    assert [kw["fallbacks"] for kw in client.beta_live] == ["default"]
    assert got == {0: {"a": 0}, 1: {"a": 2001}, 2: {"a": 2}} and spend.refusals == 0
    # refusal_model: the client-side re-run is a live call on that model
    client = _client(monkeypatch, FakeClient(answer=answer))
    got, _ = _run(3, refusal_model="claude-sonnet-5-5")
    assert [kw["model"] for kw in client.live] == ["claude-sonnet-5-5"]
    assert got[1] == {"a": 1001, llm.SERVED_BY: "claude-sonnet-5-5"}


def test_a_broken_results_download_resumes(monkeypatch):
    client = _client(monkeypatch, FakeClient())
    client.fail_results = [APIConnectionError("reset")]
    got, _ = _run(4)
    assert got == {i: {"a": i} for i in range(4)} and client.live == []


def test_a_failing_batches_api_falls_back_to_live(monkeypatch):
    class OverloadedError(Exception):
        status_code = 400

    client = _client(monkeypatch, FakeClient())

    async def create(**_kw: Any) -> Any:
        raise OverloadedError("batches are not enabled")

    client.messages.batches.create = create
    got, _ = _run(3)
    assert got == {i: {"a": 1000 + i} for i in range(3)}


# ---------------------------------------------------------------- resume


def test_an_interrupted_run_reattaches_through_the_journal(monkeypatch, tmp_path):
    monkeypatch.setenv("WSB_JUDGE_BATCH_DIR", str(tmp_path / "journal"))
    server = Server()
    first = _client(monkeypatch, FakeClient(server))
    first.fail_retrieve = AuthenticationError("OAuth access token has been revoked.")
    with pytest.raises(JudgeConfigError, match="revoked"):
        _run(4)
    assert len(first.created) == 1 and first.live == [] and first.closed
    journal = judge_batches.Journal(tmp_path / "journal")
    assert list(journal.undelivered()) == ["msgbatch_0"]
    # the next run (a fresh token) collects the batch already paid for: nothing is re-sent
    second = _client(monkeypatch, FakeClient(server))
    got, _ = _run(4)
    assert second.created == [] and second.live == [] and got == {i: {"a": i} for i in range(4)}
    assert journal.undelivered() == {}
    # a delivered batch is never re-read: asking again is a new request, as live
    third = _client(monkeypatch, FakeClient(server))
    _run(4)
    assert len(third.created) == 1


def test_reattach_takes_only_the_missing_requests_and_submits_the_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("WSB_JUDGE_BATCH_DIR", str(tmp_path / "journal"))
    server = Server()
    first = _client(monkeypatch, FakeClient(server))
    first.fail_retrieve = AuthenticationError("revoked")
    with pytest.raises(JudgeConfigError):
        _run(3)
    second = _client(monkeypatch, FakeClient(server))
    got, _ = _run(5)  # prompts 0-2 are in the old batch, 3-4 are new
    assert [sorted(_user(r["params"]) for r in b) for b in second.created] == [["3", "4"]]
    assert got == {i: {"a": i} for i in range(5)}


def test_a_journaled_batch_that_no_longer_exists_is_resubmitted(monkeypatch, tmp_path):
    monkeypatch.setenv("WSB_JUDGE_BATCH_DIR", str(tmp_path / "journal"))
    journal = judge_batches.Journal(tmp_path / "journal")
    params = [
        llm.anthropic_params(s, u, schema=SCHEMA, model=CLAUDE, max_tokens=16000)
        for s, u in _prompts(2)
    ]
    journal.created("msgbatch_gone", judge_batches.unique_ids(params))
    client = _client(monkeypatch, FakeClient())
    got, _ = _run(2)
    assert len(client.created) == 1 and got == {0: {"a": 0}, 1: {"a": 1}}
    assert journal.undelivered() == {}


# ---------------------------------------------------------------- cache keys


def _judge(cache: Cache, n: int, backend: str | None) -> dict:
    calls = [mcjudge.Call(key=f"item{i}", system="judge these", user=str(i)) for i in range(n)]
    if backend:
        llm.set_backend(backend)
    return mcjudge.run_calls(
        calls,
        schema=SCHEMA,
        judge=ResolvedJudge(CLAUDE, REASONING, True, "family"),
        prompt_version="v-test",
        cache=cache,
        spend=Spend(),
        concurrency=4,
        rpm=6e6,
        dry_run=False,
    )


def _rows(path) -> set[tuple[str, str]]:
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    return {(r["key"], r["fp"]) for r in rows}


def test_cache_keys_match_and_a_run_can_switch_backends(monkeypatch, tmp_path):
    monkeypatch.setenv("WSB_JUDGE_BACKEND", "live")  # restored after the test
    _client(monkeypatch, FakeClient())
    live, batched, mixed = (tmp_path / f"{n}.jsonl" for n in ("live", "batched", "mixed"))
    _judge(Cache(live), 6, "live")
    _judge(Cache(batched), 6, "batches")
    assert _rows(live) == _rows(batched) and len(_rows(live)) == 6
    # started live (3 items), finished with batches: only the 3 uncached calls are batched
    _judge(Cache(mixed), 3, "live")
    client = _client(monkeypatch, FakeClient())
    out = _judge(Cache(mixed), 6, "batches")
    assert [len(b) for b in client.created] == [3] and client.live == []
    assert _rows(mixed) == _rows(live)
    assert out == {f"item{i}": {"a": i + (1000 if i < 3 else 0)} for i in range(6)}
    # ... and back: a batches-filled cache answers a live run without a call
    client = _client(monkeypatch, FakeClient())
    _judge(Cache(batched), 6, "live")
    assert client.live == [] and client.created == []


# ---------------------------------------------------------------- the transport alone


def test_run_rejects_duplicate_ids_and_settings_are_checked():
    async def go() -> None:
        await judge_batches.run(
            FakeClient(),
            [("a", {}), ("a", {})],
            lambda *_a: None,
            settings=judge_batches.Settings(),
        )

    with pytest.raises(ValueError, match="unique"):
        asyncio.run(go())
    with pytest.raises(ValueError):
        judge_batches.Settings(max_requests=judge_batches.API_MAX_REQUESTS + 1)


def test_injected_anthropic_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    client = FakeClient()
    llm.use_anthropic_client(lambda: client)
    try:
        got, _ = _run(2, backend="live")  # no key in the environment, no error
    finally:
        llm.use_anthropic_client(None)
    assert got == {0: {"a": 1000}, 1: {"a": 1001}} and client.closed
