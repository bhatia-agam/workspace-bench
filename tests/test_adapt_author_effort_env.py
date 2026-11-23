"""ADAPT_AUTHOR_EFFORT: every authoring call starts at that effort (speed only, the same brief);
unset keeps the model default first (tests/test_adapt_author_effort_retry.py)."""

from test_adapt_author_effort_retry import FAM, MODEL, _empty, _ok, _session, mdir  # noqa: F401

from wsbench.adapt import author


def test_env_effort_is_used_from_the_first_call(mdir, monkeypatch):  # noqa: F811
    monkeypatch.setenv(author.EFFORT_ENV, "low")
    calls: list[dict] = []
    _session(monkeypatch, [_ok()], calls)
    assert author.author(MODEL, FAM, "t1", 1, wave=100) == 10
    assert len(calls) == 1
    assert calls[0]["thinking"] == {"type": "adaptive"}
    assert calls[0]["output_config"] == {"effort": "low"}


def test_low_start_is_not_retried_again(mdir, monkeypatch):  # noqa: F811
    monkeypatch.setenv(author.EFFORT_ENV, "low")
    calls: list[dict] = []
    _session(monkeypatch, [_empty(), _ok()], calls)
    assert author.author(MODEL, FAM, "t1", 1, wave=100) == 0
    assert len(calls) == 1


def test_medium_start_falls_back_to_low_once(mdir, monkeypatch):  # noqa: F811
    monkeypatch.setenv(author.EFFORT_ENV, "medium")
    calls: list[dict] = []
    _session(monkeypatch, [_empty(), _ok()], calls)
    assert author.author(MODEL, FAM, "t1", 1, wave=100) == 10
    assert [c["output_config"]["effort"] for c in calls] == ["medium", "low"]


def test_unset_env_keeps_the_model_default(mdir, monkeypatch):  # noqa: F811
    monkeypatch.delenv(author.EFFORT_ENV, raising=False)
    calls: list[dict] = []
    _session(monkeypatch, [_ok()], calls)
    author.author(MODEL, FAM, "t1", 1, wave=100)
    assert "output_config" not in calls[0]
