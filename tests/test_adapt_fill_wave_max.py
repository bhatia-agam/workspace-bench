"""``run.WAVE_MAX``: the largest wave ``fill`` authors (``ADAPT_FILL_WAVE_MAX``, default 60)."""

import importlib


def test_wave_max_defaults_to_60_and_reads_the_env(monkeypatch):
    from wsbench.adapt import run

    monkeypatch.delenv("ADAPT_FILL_WAVE_MAX", raising=False)
    assert importlib.reload(run).WAVE_MAX == 60
    monkeypatch.setenv("ADAPT_FILL_WAVE_MAX", "240")
    assert importlib.reload(run).WAVE_MAX == 240
    monkeypatch.delenv("ADAPT_FILL_WAVE_MAX")
    importlib.reload(run)
