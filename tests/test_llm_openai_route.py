"""Plan 0096 part 2: the ``openai`` route (``WSBENCH_OPENAI_ROUTE=wif``) for structured and free
text calls, ``WSBENCH_OPENROUTER_MAX_OUT``, the shared chat-response rules, cross-route refusal
re-runs to and from ``openai``, and ``judge_effort=``. Ported from the plan-0059 branch tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from openrouter_fakes import (
    APIError,
    FakeStream,
    OpenRouterClient,
    completion,
    quiet,
    text_stream,
)
from test_llm_refusal_rerun import ModelAwareClient, _resp

from wsbench import family, llm, mcjudge, registry, runner
from wsbench.baselines import ati_remote as ar
from wsbench.cli import main
from wsbench.judge_config import DEFAULT_REASONING, JUDGE_EFFORTS, JudgeConfig, resolve
from wsbench.llm import JudgeConfigError, Spend
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult

SCHEMA = llm.schema_block("t", {"a": {"type": "integer"}}, ["a"])
LUNA = "openai/gpt-6-luna"
OR_MODEL = "deepseek/deepseek-v4-flash"
SONNET, SONNET55, OPUS5 = "claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5"
WIF_ENV = {
    "MODAL_IDENTITY_TOKEN": "jwt",
    "OPENAI_IDENTITY_PROVIDER_ID_MODAL": "idp-1",
    "OPENAI_SERVICE_ACCOUNT_ID": "sa-1",
    "OPENAI_PROJECT_ID": "proj-1",
}
LONG = "This model's maximum context length is 1050000 tokens"


class AuthenticationError(Exception):
    """Named as the openai SDK class (in ``llm._FATAL``)."""

    status_code = 401


class PermissionDeniedError(Exception):
    status_code = 403

    def __init__(self, message: str, body: object = None) -> None:
        super().__init__(message)
        self.body = body


class BadRequestError(Exception):
    status_code = 400


class TokenPost:
    """The token endpoint: a fresh access token per exchange (``tok-1``, ``tok-2``, ...);
    ``statuses`` scripts the status of the first exchanges (default: every one is a 200)."""

    def __init__(self, statuses: list[int] | None = None) -> None:
        self.n = 0
        self.statuses = list(statuses or [])

    async def __call__(self, url: str, payload: dict) -> tuple[int, Any]:
        status = self.statuses.pop(0) if self.statuses else 200
        if status != 200:
            return status, {"error": "scripted"}
        self.n += 1
        return 200, {"access_token": f"tok-{self.n}", "expires_in": 3600}


class FakeOpenAI:
    """One shared outcome script across every ``AsyncOpenAI`` the WIF clients build (one per
    access token); each call records the token it was made with. A list outcome is the chunks
    of a streamed answer."""

    def __init__(self, outcomes: list[Any]):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.built: list[tuple[str, str | None, dict[str, str]]] = []
        self.closed = 0

    def factory(self, key: str, base_url: str | None, headers: dict[str, str]) -> Any:
        self.built.append((key, base_url, headers))

        async def create(**kw: Any) -> Any:
            self.calls.append({**kw, "_token": key})
            out = self.outcomes.pop(0)
            if isinstance(out, BaseException):
                raise out
            return FakeStream(out) if kw.get("stream") else out

        async def close() -> None:
            self.closed += 1

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close
        )


def install(monkeypatch, fake: FakeOpenAI, post: TokenPost | None = None, **others: Any):
    """``WSBENCH_OPENAI_ROUTE=wif`` with ``fake`` behind the WIF clients of the ``openai`` route
    and ``others`` (``anthropic=``, ``openrouter=``) behind the other routes; returns the list of
    built routes and the token endpoint."""
    quiet(monkeypatch)
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")
    post = post or TokenPost()
    clients = ar.Clients(
        "openai-wif", env=WIF_ENV, factory=fake.factory, token=ar.WifToken(WIF_ENV, post=post)
    )
    built: list[str] = []

    def make(route: str, key: str) -> Any:
        built.append(route)
        if route == "openai":
            assert key == ""  # no key on this route
            return llm._WifClient(clients)
        assert route in others, f"no client expected on the {route} route"
        return others[route]

    monkeypatch.setattr(llm, "_make_client", make)
    return built, post


def _json(model: str = LUNA, **kw: Any) -> tuple[list, Spend]:
    got: list[Any] = []
    spend = llm.stream_json(
        [("s", "u")], schema=SCHEMA, model=model, on_result=lambda i, r: got.append(r), **kw
    )
    return got, spend


def _text(model: str = LUNA, **kw: Any) -> tuple[list, Spend, list]:
    got: list[Any] = []
    served: list[Any] = []
    kw.setdefault("thinking", False)
    kw.setdefault("max_tokens", 400)
    spend = llm.stream_text(
        ["u"],
        model=model,
        on_result=lambda i, r: got.append(r),
        on_served=lambda i, m: served.append(m),
        **kw,
    )
    return got, spend, served


def _plain(content: str = '{"a": 1}', **kw: Any) -> Any:
    """An OpenAI completion: token usage, no cost field."""
    resp = completion(content, **kw)
    resp.usage = SimpleNamespace(prompt_tokens=120, completion_tokens=30)
    return resp


# ---------------------------------------------------------------- routing


def test_openai_route_only_with_the_env(monkeypatch):
    for m in (LUNA, "openai/gpt-6-astra", "openai/gpt-oss-120b", OR_MODEL):
        assert llm.route(m) == "openrouter"  # env unset (conftest clears it): unchanged
    assert llm.route(SONNET) == "anthropic"
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")
    assert llm.route(LUNA) == llm.route("openai/gpt-5-nano") == "openai"
    assert llm.route("openai/gpt-oss-20b") == "openrouter"  # open weights: other providers
    assert llm.route(OR_MODEL) == "openrouter" and llm.route(SONNET) == "anthropic"
    assert llm.api_key(LUNA) == ""  # no key: the WIF client exchanges a token
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "yes")
    with pytest.raises(JudgeConfigError, match="expected 'wif'"):
        llm.route(LUNA)
    assert llm.route(SONNET) == "anthropic"  # a claude-* id never reads the variable


def test_reasoning_for_treats_openai_as_openrouter():
    assert llm._DEFAULT_MAX_TOKENS["openai"] == 8000
    both = {"effort": "low", "anthropic_effort": "default"}
    for r in ("openai", "openrouter"):
        assert llm.reasoning_for(r, both) == {"effort": "low"}
        assert llm.reasoning_for(r, {"anthropic_effort": "default"}) == {"effort": "minimal"}
        assert llm.reasoning_for(r, None) == {"effort": "minimal"}
    assert llm.reasoning_for("anthropic", both) == {"anthropic_effort": "default"}


# ---------------------------------------------------------------- structured calls


def test_openai_route_request_shape_and_max_out(monkeypatch, capsys):
    fake = FakeOpenAI([_plain(), _plain()])
    built, _post = install(monkeypatch, fake)
    got, spend = _json(reasoning={"effort": "low"}, temperature=0.0)
    assert "dropping temperature=0.0" in capsys.readouterr().out  # one printed line
    monkeypatch.setenv(llm.MAX_OUT_ENV, "900")
    _json(reasoning=None, max_tokens=300)
    assert got == [{"a": 1}] and built == ["openai", "openai"]
    first, second = fake.calls
    assert first["model"] == "gpt-6-luna"  # the openai/ prefix stripped
    assert first["max_completion_tokens"] == llm._DEFAULT_MAX_TOKENS["openai"]
    assert second["max_completion_tokens"] == 900  # the output budget replaces the request
    assert first["reasoning_effort"] == "low" and "reasoning_effort" not in second
    for c in fake.calls:
        assert not {"temperature", "extra_body", "max_tokens", "reasoning"} & set(c)
        assert c["messages"] == [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ]
        assert c["response_format"] == {"type": "json_schema", "json_schema": SCHEMA}
    assert fake.built[0] == ("tok-1", None, {"OpenAI-Project": "proj-1"})
    assert (spend.input_tokens, spend.output_tokens, spend.usd) == (120, 30, 0.0)
    assert fake.closed == 2  # the batch closes the client it built


def test_openai_route_401_re_exchanges_then_succeeds(monkeypatch):
    fake = FakeOpenAI([AuthenticationError("expired"), _plain()])
    _built, post = install(monkeypatch, fake)
    got, spend = _json()
    assert got == [{"a": 1}] and post.n == 2
    assert [c["_token"] for c in fake.calls] == ["tok-1", "tok-2"]
    assert spend.calls == 1 and spend.retries == 0 and spend.errors == 0


def test_openai_route_a_last_401_is_fatal(monkeypatch):
    n = ar.AUTH_REFRESHES + 1
    fake = FakeOpenAI([AuthenticationError("bad identity") for _ in range(n)])
    install(monkeypatch, fake)
    with pytest.raises(JudgeConfigError, match="AuthenticationError"):
        _json()
    assert len(fake.calls) == n and len({c["_token"] for c in fake.calls}) == n


def test_openai_route_403_is_fatal_even_when_flagged(monkeypatch):
    """R1: the moderation carve-out stays OpenRouter-only."""
    body = {"code": 403, "metadata": {"flagged_input": "the prompt", "reasons": ["x"]}}
    fake = FakeOpenAI([PermissionDeniedError("Your input was flagged", body)])
    install(monkeypatch, fake)
    with pytest.raises(JudgeConfigError):
        _json(mark_refusals=True)


def test_openai_route_failed_token_exchange_is_raised_never_degraded(monkeypatch):
    """R1: a ``JudgeConfigError`` raised inside a call (the WIF exchange was refused) is
    re-raised, never a ``None`` result."""
    fake = FakeOpenAI([_plain()])
    install(monkeypatch, fake, post=TokenPost([400]))
    with pytest.raises(JudgeConfigError, match="token exchange failed"):
        _json()
    assert fake.calls == []


def test_openai_route_transient_token_exchange_is_retried(monkeypatch):
    """R1: a 429 / 5xx from the token endpoint is transient."""
    fake = FakeOpenAI([_plain()])
    _built, post = install(monkeypatch, fake, post=TokenPost([503, 429]))
    got, spend = _json()
    assert got == [{"a": 1}] and spend.retries == 2 and spend.errors == 0 and post.n == 1


def test_openai_route_missing_wif_env_is_a_config_error(monkeypatch):
    quiet(monkeypatch)
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")
    for k in WIF_ENV:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(JudgeConfigError, match="openai-wif"):
        _json()  # the real _make_client: no secret, no Modal identity
    with pytest.raises(JudgeConfigError, match="openai-wif"):
        llm.require_credentials(LUNA)
    for k, v in WIF_ENV.items():
        monkeypatch.setenv(k, v)
    llm.require_credentials(LUNA)  # the token source builds: no network call


@pytest.mark.parametrize("route", ["openai", "openrouter"])
def test_chat_routes_share_the_refusal_and_length_rules(monkeypatch, route):
    """R3: one helper reads both chat routes. A refusal is ``content_filter`` or a
    ``message.refusal`` with NO content (part 1's rule); an unparsable body cut at the output cap
    is one failed call, never retried; a garbled body is still a parse retry."""
    outcomes = [
        _plain("", refusal="no"),
        _plain('{"a": 1}', finish_reason="content_filter"),
        _plain('{"a": 2}', refusal="a note beside an answer"),  # content wins: an answer
        _plain('{"a":', finish_reason="length"),
        _plain('{"a": 3}', finish_reason="length"),  # cut, but parseable: used
        _plain("not json"),
        _plain('{"a": 4}'),
    ]
    if route == "openai":
        fake: Any = FakeOpenAI(outcomes)
        install(monkeypatch, fake)
        model = LUNA
    else:
        script = list(outcomes)
        fake = OpenRouterClient(lambda model, kw: script.pop(0))
        quiet(monkeypatch)
        monkeypatch.setattr(llm, "_make_client", lambda route, key: fake)
        model = OR_MODEL
    got, spend = _json(model, mark_refusals=True)
    assert got == [llm.REFUSED_JSON] and spend.refusals == 1 and spend.retries == 0
    got, spend = _json(model)
    assert got == [None] and spend.refusals == 1
    assert _json(model)[0] == [{"a": 2}]
    got, spend = _json(model)
    assert got == [None] and (spend.errors, spend.retries, spend.calls) == (1, 0, 1)
    assert _json(model)[0] == [{"a": 3}]
    got, spend = _json(model)
    assert got == [{"a": 4}] and (spend.retries, spend.errors) == (1, 0)
    assert len(fake.calls) == 7


@pytest.mark.parametrize("route", ["openai", "openrouter"])
def test_too_long_needs_the_output_cap_on_the_chat_routes(monkeypatch, route):
    """R2 / R13: a context-length 400 is ``TOO_LONG_JSON`` under ``mark_refusals`` only while
    ``WSBENCH_OPENROUTER_MAX_OUT`` is set; unset it is a plain error ("prompt is too long" alone
    is too-long everywhere, as before)."""
    assert llm.OPENROUTER_TOO_LONG == (
        "maximum context length",
        "context length",
        "context window",
        "prompt is too long",
    )

    def run(message: str, **kw: Any) -> tuple[list, Spend]:
        err = BadRequestError(f"Error code: 400 - {message}")
        if route == "openai":
            install(monkeypatch, FakeOpenAI([err]))
            return _json(LUNA, **kw)
        quiet(monkeypatch)
        monkeypatch.setattr(llm, "_make_client", lambda r, k: OpenRouterClient(lambda m, kw: err))
        return _json(OR_MODEL, **kw)

    got, spend = run(LONG, mark_refusals=True)  # the cap is unset: a plain error
    assert got == [None] and (spend.errors, spend.retries) == (1, 0)
    assert run("prompt is too long: 9 tokens", mark_refusals=True)[0] == [llm.TOO_LONG_JSON]
    monkeypatch.setenv(llm.MAX_OUT_ENV, "8000")
    for phrase in llm.OPENROUTER_TOO_LONG:
        got, spend = run(f"this endpoint's {phrase} is 131072 tokens", mark_refusals=True)
        assert got == [llm.TOO_LONG_JSON] and (spend.errors, spend.retries) == (1, 0)
    assert run(LONG)[0] == [None]  # without mark_refusals: None
    got, _spend = run("too many tokens: max_tokens exceeds the limit", mark_refusals=True)
    assert got == [None]  # an output request over the cap is not a too-long input


def test_too_long_on_the_anthropic_route_never_reads_the_cap(monkeypatch):
    quiet(monkeypatch)
    monkeypatch.setenv(llm.MAX_OUT_ENV, "8000")

    def answer(model, kw):
        raise BadRequestError(f"Error code: 400 - {LONG}")

    monkeypatch.setattr(llm, "_make_client", lambda r, k: ModelAwareClient(answer))
    assert _json(SONNET, mark_refusals=True)[0] == [None]  # only "prompt is too long" counts
    monkeypatch.setenv(llm.MAX_OUT_ENV, "zero")  # never read on the Anthropic route
    ok = ModelAwareClient(lambda model, kw: _resp('{"a": 1}'))
    monkeypatch.setattr(llm, "_make_client", lambda r, k: ok)
    assert _json(SONNET)[0] == [{"a": 1}]
    assert ok.calls[0]["max_tokens"] == llm._DEFAULT_MAX_TOKENS["anthropic"]


@pytest.mark.parametrize("bad", ["zero", "0", "-5", "1.5"])
def test_max_out_bad_value_is_a_config_error(monkeypatch, bad):
    quiet(monkeypatch)
    monkeypatch.setenv(llm.MAX_OUT_ENV, bad)
    orc = OpenRouterClient(lambda model, kw: completion('{"a": 1}'))
    monkeypatch.setattr(llm, "_make_client", lambda r, k: orc)
    with pytest.raises(JudgeConfigError, match=llm.MAX_OUT_ENV):
        _json(OR_MODEL)
    with pytest.raises(JudgeConfigError, match=llm.MAX_OUT_ENV):
        _text(OR_MODEL)
    assert orc.calls == []


def test_max_out_sets_the_openrouter_budget_both_ways(monkeypatch):
    quiet(monkeypatch)
    orc = OpenRouterClient(lambda model, kw: completion('{"a": 1}'))
    monkeypatch.setattr(llm, "_make_client", lambda r, k: orc)
    _json(OR_MODEL)
    _json(OR_MODEL, max_tokens=300)
    monkeypatch.setenv(llm.MAX_OUT_ENV, "500")
    _json(OR_MODEL)
    _json(OR_MODEL, max_tokens=300)
    _json(OR_MODEL, max_tokens=64000)
    assert [c["max_tokens"] for c in orc.calls] == [8000, 300, 500, 500, 500]


# ---------------------------------------------------------------- free text


@pytest.mark.parametrize("thinking", [True, False])
def test_openai_text_request_and_spend(monkeypatch, thinking):
    fake = FakeOpenAI([text_stream("the answer")])
    built, _post = install(monkeypatch, fake)
    got, spend, served = _text(thinking=thinking)
    assert got == ["the answer"] and served == [] and built == ["openai"]
    (kw,) = fake.calls
    assert kw["model"] == "gpt-6-luna" and kw["stream"] is True
    assert kw["stream_options"] == {"include_usage": True}
    assert kw["max_completion_tokens"] == 400
    assert kw["messages"] == [{"role": "user", "content": "u"}]  # user only, no system block
    assert not {"extra_body", "max_tokens", "temperature", "response_format"} & set(kw)
    if thinking:
        assert "reasoning_effort" not in kw  # the model's default
    else:
        assert kw["reasoning_effort"] == "low"  # minimal is sent as low on this route
    assert (spend.calls, spend.input_tokens, spend.output_tokens) == (1, 7, 3)


def test_openai_text_budget_doubles_to_the_ceiling(monkeypatch):
    fake = FakeOpenAI([text_stream("", "length") for _ in range(3)])
    install(monkeypatch, fake)
    got, spend, _served = _text(max_tokens=16_000)
    assert got == [""] and spend.calls == 3  # "" after the ceiling is a valid result
    assert [c["max_completion_tokens"] for c in fake.calls] == [16_000, 32_000, 64_000]


def test_max_out_is_the_starting_budget_of_free_text(monkeypatch):
    """R4: the cap is where a chat-route text call starts; doubling still runs to the ceiling."""
    monkeypatch.setenv(llm.MAX_OUT_ENV, "1000")
    fake = FakeOpenAI([text_stream("", "length"), text_stream("", "length"), text_stream("ok")])
    install(monkeypatch, fake)
    assert _text(max_tokens=400)[0] == ["ok"]
    assert [c["max_completion_tokens"] for c in fake.calls] == [1000, 2000, 4000]
    orc = OpenRouterClient(lambda model, kw: text_stream("ok"))
    quiet(monkeypatch)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: orc)
    assert _text(OR_MODEL, max_tokens=400)[0] == ["ok"]
    assert orc.calls[0]["max_tokens"] == 1000
    assert llm._TEXT_BUDGET_CEILING == 64_000


@pytest.mark.parametrize("mark", [True, False])
def test_openai_text_refusals(monkeypatch, mark):
    fake = FakeOpenAI([text_stream("partial", "content_filter"), text_stream("", refusal="no")])
    install(monkeypatch, fake)
    want = [llm.REFUSED] if mark else [None]
    got, spend, _served = _text(mark_refusals=mark)
    assert got == want and spend.refusals == 1
    assert _text(mark_refusals=mark)[0] == want


def test_openai_text_stream_errors_and_auth(monkeypatch):
    stream_error = APIError("An error occurred during streaming")
    fake = FakeOpenAI(
        [
            [*text_stream("half")[:1], stream_error],  # raised from the stream iterator
            text_stream("x", "error"),  # finish_reason == "error"
            AuthenticationError("expired"),  # a 401 at create: re-exchange, no retry spent
            text_stream("done"),
        ]
    )
    _built, post = install(monkeypatch, fake)
    got, spend, _served = _text()
    assert got == ["done"] and spend.retries == 2 and spend.errors == 0 and post.n == 2
    assert [c["_token"] for c in fake.calls] == ["tok-1", "tok-1", "tok-1", "tok-2"]
    body = {"code": 403, "metadata": {"flagged_input": "the prompt"}}
    install(monkeypatch, FakeOpenAI([PermissionDeniedError("flagged", body)]))
    with pytest.raises(JudgeConfigError):
        _text(mark_refusals=True)  # a 403 is fatal on this route, flagged or not
    install(monkeypatch, FakeOpenAI([text_stream("ok")]), post=TokenPost([400]))
    with pytest.raises(JudgeConfigError, match="token exchange failed"):
        _text()
    fake = FakeOpenAI([text_stream("ok")])
    install(monkeypatch, fake, post=TokenPost([503]))
    got, spend, _served = _text()
    assert got == ["ok"] and spend.retries == 1


def test_openai_text_stream_error_with_a_fatal_code_raises(monkeypatch):
    err = APIError("no access")
    err.body = {"code": 401}
    install(monkeypatch, FakeOpenAI([[err]]))
    with pytest.raises(JudgeConfigError):
        _text()


# ---------------------------------------------------------------- cross-route refusal re-runs


def _declined() -> Any:
    return _plain("", finish_reason="content_filter")


def test_json_rerun_from_openai_to_anthropic(monkeypatch):
    """R4: the cap follows the route of the model actually called: Luna's call is capped, the
    Anthropic fallback never reads the variable."""
    monkeypatch.setenv(llm.MAX_OUT_ENV, "900")
    fake = FakeOpenAI([_declined()])
    ant = ModelAwareClient(lambda model, kw: _resp('{"a": 1}', model=model))
    built, _post = install(monkeypatch, fake, anthropic=ant)
    got, spend = _json(LUNA, refusal_model=SONNET55, reasoning={"effort": "low"}, temperature=0.0)
    assert got == [{"a": 1, llm.SERVED_BY: SONNET55}] and built == ["openai", "anthropic"]
    assert fake.calls[0]["max_completion_tokens"] == 900
    assert fake.calls[0]["reasoning_effort"] == "low" and "temperature" not in fake.calls[0]
    (again,) = ant.calls
    assert again["model"] == SONNET55
    assert again["max_tokens"] == llm._DEFAULT_MAX_TOKENS["anthropic"]  # its route's default
    assert "temperature" not in again and "fallbacks" not in again
    assert again["output_config"]["effort"] == "low"  # no anthropic key left: the repo default
    assert spend.refusals == 1 and fake.closed == 1


def test_json_rerun_from_anthropic_to_openai(monkeypatch):
    monkeypatch.setenv(llm.MAX_OUT_ENV, "900")
    fake = FakeOpenAI([_plain('{"a": 2}')])
    ant = ModelAwareClient(lambda model, kw: _resp("", "refusal"))
    built, _post = install(monkeypatch, fake, anthropic=ant)
    got, _spend = _json(
        SONNET,
        refusal_model=LUNA,
        reasoning={"anthropic_effort": "default"},
        temperature=0.0,
        max_tokens=20_000,
    )
    assert got == [{"a": 2, llm.SERVED_BY: LUNA}] and built == ["anthropic", "openai"]
    assert ant.calls[0]["max_tokens"] == 20_000  # the Anthropic primary is never capped
    (again,) = fake.calls
    assert again["model"] == "gpt-6-luna" and again["max_completion_tokens"] == 900
    assert again["reasoning_effort"] == "low"  # reasoning_for's minimal default, sent as low
    assert "temperature" not in again  # sent only to an openrouter re-run
    monkeypatch.delenv(llm.MAX_OUT_ENV)
    fake.outcomes.append(_plain('{"a": 3}'))
    _json(SONNET, refusal_model=LUNA, refusal_reasoning={"effort": "high"})
    assert fake.calls[-1]["max_completion_tokens"] == llm._DEFAULT_MAX_TOKENS["openai"]
    assert fake.calls[-1]["reasoning_effort"] == "high"  # refusal_reasoning as given


def test_json_rerun_between_the_two_chat_routes(monkeypatch):
    """``openai`` and ``openrouter`` are different routes: a second client is built, and
    ``temperature`` goes to the OpenRouter call only (the caller's value, although the ``openai``
    primary dropped it)."""
    fake = FakeOpenAI([_declined(), _plain('{"a": 5}')])
    script = [completion('{"a": 4}'), completion("", finish_reason="content_filter")]
    orc = OpenRouterClient(lambda model, kw: script.pop(0))
    built, _post = install(monkeypatch, fake, openrouter=orc)
    got, _spend = _json(LUNA, refusal_model=OR_MODEL, temperature=0.0, reasoning={"effort": "low"})
    assert got == [{"a": 4, llm.SERVED_BY: OR_MODEL}] and built == ["openai", "openrouter"]
    assert "temperature" not in fake.calls[0] and orc.calls[0]["temperature"] == 0.0
    assert orc.calls[0]["extra_body"]["reasoning"] == {"effort": "low"}
    got, _spend = _json(OR_MODEL, refusal_model=LUNA, temperature=0.0)
    assert got == [{"a": 5, llm.SERVED_BY: LUNA}] and built[2:] == ["openrouter", "openai"]
    assert orc.calls[1]["temperature"] == 0.0 and "temperature" not in fake.calls[1]


def test_text_rerun_crosses_to_and_from_openai(monkeypatch):
    monkeypatch.setenv(llm.MAX_OUT_ENV, "1000")
    fake = FakeOpenAI([text_stream("", "content_filter"), text_stream("from luna")])
    answers = [_resp("from opus", model=OPUS5), _resp("", "refusal")]
    ant = ModelAwareClient(lambda model, kw: answers.pop(0))
    built, _post = install(monkeypatch, fake, anthropic=ant)
    got, _spend, served = _text(LUNA, refusal_model=OPUS5, thinking=True)
    assert got == ["from opus"] and served == [OPUS5] and built == ["openai", "anthropic"]
    assert fake.calls[0]["max_completion_tokens"] == 1000  # the chat route starts at the cap
    assert ant.calls[0]["max_tokens"] == 400  # the Anthropic call keeps the caller's budget
    got, _spend, served = _text(SONNET, refusal_model=LUNA)
    assert got == ["from luna"] and served == [LUNA] and built[2:] == ["anthropic", "openai"]
    assert ant.calls[1]["max_tokens"] == 400
    assert fake.calls[1]["max_completion_tokens"] == 1000
    assert fake.calls[1]["reasoning_effort"] == "low"


def test_fallback_credentials_on_the_openai_route(monkeypatch, mk_args, tmp_path):
    """R10: ``api_key`` is ``""`` on the ``openai`` route, so the up-front check builds the WIF
    token source and names the way out."""
    quiet(monkeypatch)
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")
    for k in WIF_ENV:
        monkeypatch.delenv(k, raising=False)
    args = mk_args(tmp_path / "r.jsonl")  # a claude-* judge: Luna is on another route
    with pytest.raises(JudgeConfigError, match="opts=fallback=none") as e:
        family.require_fallback_key(args, "fam", LUNA)
    assert "openai-wif" in str(e.value)
    for k, v in WIF_ENV.items():
        monkeypatch.setenv(k, v)
    family.require_fallback_key(args, "fam", LUNA)  # the identity is there: nothing


# ---------------------------------------------------------------- judge_effort


def test_resolve_effort_table():
    assert JUDGE_EFFORTS == ("default", "minimal", "low", "medium", "high")
    fam = JudgeConfig(model=OR_MODEL, reasoning={"effort": "low"})
    assert resolve(fam) == resolve(fam, effort=None)  # absent: unchanged
    assert resolve(fam).reasoning == {"effort": "low"} and resolve(fam).pinned
    j = resolve(fam, effort="high")
    assert j.reasoning == {"effort": "high"} and j.pinned is False and j.model == OR_MODEL
    assert resolve(fam, effort="default").reasoning is None
    plain = JudgeConfig(model=OR_MODEL)
    assert resolve(plain).reasoning == DEFAULT_REASONING
    assert resolve(plain, effort="minimal").reasoning == {"effort": "minimal"}
    assert resolve(plain, effort="minimal").pinned is False
    # a non-Claude override of a Claude family: the effort replaces the minimal default
    opus = JudgeConfig(reasoning={"anthropic_effort": "default"})
    assert resolve(opus, flag=OR_MODEL).reasoning == DEFAULT_REASONING
    assert resolve(opus, flag=OR_MODEL, effort="low").reasoning == {"effort": "low"}
    # unset on a Claude judge: today's resolution
    assert resolve(opus).reasoning == {"anthropic_effort": "default"} and resolve(opus).pinned


def test_resolve_effort_on_the_openai_route(monkeypatch):
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "wif")
    cfg = JudgeConfig(prompt_version="v", reasoning={"effort": "low", "anthropic_effort": "x"})
    r = resolve(cfg, flag=LUNA, env={}, effort="high")
    assert (r.reasoning, r.pinned) == ({"effort": "high"}, False)
    assert resolve(cfg, flag=LUNA, env={}).reasoning == {"effort": "low"}  # non-Anthropic keys
    assert resolve(JudgeConfig(), flag=LUNA, env={}).reasoning == DEFAULT_REASONING
    assert resolve(cfg, flag=LUNA, env={}, effort="default").reasoning is None


def test_resolve_effort_with_a_claude_judge_or_a_bad_level_exits_2():
    with pytest.raises(SystemExit) as e:
        resolve(JudgeConfig(), effort="low")  # the default judge is claude-opus-5-5
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        resolve(JudgeConfig(model=OR_MODEL), effort="max")
    assert e.value.code == 2


def _result(args: JudgeArgs, name: str) -> FamilyResult:
    return FamilyResult(
        family=name,
        metric="pass_rate",
        value=0.5,
        ci95=(0.0, 1.0),
        n_items=1,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=args.judge.pinned,
        config={"judge_model": args.judge.model, "reasoning": args.judge.reasoning},
        counts=mcjudge.base_counts(
            n_expected=1, n_unjudged=0, n_empty=0, skipped_rows=0, spend=Spend()
        ),
    )


def _spec(name: str, run, model: str = OR_MODEL) -> EvalSpec:
    return register(
        EvalSpec(
            name=name,
            title=name,
            group="logic",
            bank=Path(f"evals/{name}/items.json"),
            judge=JudgeConfig(model=model),
            metric="pass_rate",
            higher_is_better=True,
            run=run,
        )
    )


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    seen: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: seen.append((model, reasoning)))
    registry.FAMILIES.clear()
    return seen


def _readouts(root: Path, *names: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    row = json.dumps({"id": "a", "layer": 36, "pos": 1, "samples": ["x"]}) + "\n"
    for n in names:
        (root / f"{n}.jsonl").write_text(row)


def _run_argv(root: Path, out: Path, *extra: str, families: str) -> list[str]:
    native = "opts=aggregate=native"
    return ["run", native, f"families={families}", f"readouts_root={root}", f"out={out}", *extra]


def test_run_judge_effort_is_recorded_only_when_given(offline, tmp_path):
    seen_reasoning: list[dict | None] = []

    def run(args: JudgeArgs) -> FamilyResult:
        seen_reasoning.append(args.judge.reasoning)
        return _result(args, "g1")

    _spec("g1", run)
    root = tmp_path / "r"
    _readouts(root, "g1")
    assert main(_run_argv(root, tmp_path / "a", "judge_effort=low", families="g1")) == 0
    run_json = json.loads((tmp_path / "a" / "run.json").read_text())
    assert run_json["judge_effort"] == "low" and "judge_effort" not in run_json["judge_overrides"]
    assert run_json["families"]["g1"]["pinned_instrument"] is False
    assert offline == [(OR_MODEL, {"effort": "low"})] and seen_reasoning == [{"effort": "low"}]
    mcjudge._PREFLIGHTED.clear()
    assert main(_run_argv(root, tmp_path / "b", families="g1")) == 0
    assert "judge_effort" not in json.loads((tmp_path / "b" / "run.json").read_text())
    assert seen_reasoning[-1] == DEFAULT_REASONING  # unset: today's resolution
    assert offline[-1] == (OR_MODEL, DEFAULT_REASONING)
    # `judge`, and the process-mode child path (`judge outcome=`, runner._one), resolve it too
    argv = ["judge", "opts=aggregate=native", "family=g1", f"readouts={root / 'g1.jsonl'}"]
    assert main([*argv, f"out={tmp_path / 'j'}", "judge_effort=default"]) == 0
    assert seen_reasoning[-1] is None
    outcome = tmp_path / "k" / "outcome.json"
    assert main([*argv, f"out={tmp_path / 'k'}", f"outcome={outcome}", "judge_effort=high"]) == 0
    assert seen_reasoning[-1] == {"effort": "high"}
    assert json.loads(outcome.read_text())["status"] == "ok"


def test_judge_effort_with_a_claude_judge_and_a_bad_value_exit_2(offline, tmp_path, capsys):
    _spec("c1", lambda a: _result(a, "c1"), model="claude-opus-5-5")
    root = tmp_path / "r"
    _readouts(root, "c1")
    with pytest.raises(SystemExit) as e:
        main(_run_argv(root, tmp_path / "o", "judge_effort=low", families="c1"))
    assert e.value.code == 2
    argv = ["judge", "opts=aggregate=native", "family=c1", f"readouts={root / 'c1.jsonl'}"]
    with pytest.raises(SystemExit) as e:  # as a bad opts= on judge: fail() exits 2
        main([*argv, f"out={tmp_path / 'j'}", "judge_effort=low"])
    assert e.value.code == 2
    assert "is a claude-* judge" in capsys.readouterr().err
    outcome = tmp_path / "k" / "outcome.json"  # a run's child: a failed family, exit 2
    assert main([*argv, f"out={tmp_path / 'k'}", f"outcome={outcome}", "judge_effort=low"]) == 2
    assert json.loads(outcome.read_text())["exit_code"] == 2
    assert main([*argv, f"out={tmp_path / 'j'}", "judge_effort=extreme"]) == 2
    assert offline == []  # nothing preflighted


def test_judge_argv_emits_judge_effort_only_when_given(tmp_path):
    base: dict[str, Any] = {
        "concurrency": 4, "rpm": 100.0, "judge_model": LUNA, "layers": None, "items": None,
        "limit": 0, "allow_missing": False, "opt": [],
    }  # fmt: skip
    plain = SimpleNamespace(**base)  # a hand-built namespace without the attribute
    cmd = runner.judge_argv("fam", plain, Path("r/fam.jsonl"), Path("o/fam"))
    assert not [a for a in cmd if a.startswith("judge_effort")]
    cmd = runner.judge_argv(
        "fam", SimpleNamespace(**base, judge_effort=None), Path("r.jsonl"), Path("o")
    )
    assert not [a for a in cmd if a.startswith("judge_effort")]
    cmd = runner.judge_argv(
        "fam", SimpleNamespace(**base, judge_effort="low"), Path("r.jsonl"), Path("o")
    )
    assert "judge_effort=low" in cmd and cmd.index("judge_effort=low") > cmd.index(
        f"judge_model={LUNA}"
    )


# ---------------------------------------------------------------- a bad env value ends as exit 3


def test_a_bad_openai_route_value_is_exit_3_not_a_traceback(offline, tmp_path, monkeypatch, capsys):
    """R11: ``llm.route`` raises on a bad value; ``judge`` and ``run`` end as exit 3 with it."""
    _spec("g1", lambda a: _result(a, "g1"), model=LUNA)
    root = tmp_path / "r"
    _readouts(root, "g1")
    monkeypatch.setenv(llm.OPENAI_ROUTE_ENV, "yes")
    argv = ["judge", "family=g1", f"readouts={root / 'g1.jsonl'}"]
    for opts in ("opts=aggregate=native", "opts=summ_model=openai/gpt-6-luna"):
        assert main([*argv, opts, f"out={tmp_path / 'j'}"]) == 3
        outcome = tmp_path / "k" / "outcome.json"
        assert main([*argv, opts, f"out={tmp_path / 'k'}", f"outcome={outcome}"]) == 3
        run = ["run", opts, "families=g1", f"readouts_root={root}", f"out={tmp_path / 'o'}"]
        assert main(run) == 3
    assert "expected 'wif' or unset" in capsys.readouterr().err
    assert offline == []


def test_an_exhausted_quota_is_fatal_not_a_rate_limit():
    """Seen live 2026-11-18: OpenAI answers a project over its spend limit with a 429 whose
    body is type insufficient_quota; that fails every call, so it is a config error, while a
    plain 429 stays a rate limit."""

    def err(**body):
        e = RuntimeError("429")
        e.status_code, e.body = 429, body
        return e

    quota = err(type="insufficient_quota", code="project_spend_limit_exceeded")
    rate = err(type="requests", code="rate_limit_exceeded")
    assert llm._out_of_quota(quota) and not llm._out_of_quota(rate)
    assert not llm._out_of_quota(ValueError("x"))


def test_openai_route_spend_limit_fails_the_run_at_the_first_call(monkeypatch):
    """The 429 OpenAI sends for a project over its spend limit is a config error at the first
    attempt (no backoff, no second request), on structured and free-text calls alike."""

    class RateLimitError(Exception):
        status_code = 429

        def __init__(self) -> None:
            super().__init__("Your project has reached its configured enforced spend limit.")
            self.body = {"type": "insufficient_quota", "code": "project_spend_limit_exceeded"}

    for call in (_json, lambda: _text(thinking=True, max_tokens=100)):
        fake = FakeOpenAI([RateLimitError(), _plain()])
        install(monkeypatch, fake)
        with pytest.raises(JudgeConfigError, match="spend limit"):
            call()
        assert len(fake.calls) == 1


def test_openai_route_never_sends_minimal_effort(monkeypatch):
    """Live 2026-11-18: gpt-6-luna answers 400 to reasoning_effort=minimal, so a Luna judge
    resolved with the repo's default ``{"effort": "minimal"}`` (no judge_effort=) is sent
    ``low``; every other level goes through as given."""
    assert [llm._openai_effort(e) for e in ("minimal", "none", "low", "high")] == [
        "low",
        "none",
        "low",
        "high",
    ]
    fake = FakeOpenAI([_plain()])
    install(monkeypatch, fake)
    got, _spend = _json(reasoning=dict(DEFAULT_REASONING))
    assert got == [{"a": 1}] and fake.calls[0]["reasoning_effort"] == "low"
