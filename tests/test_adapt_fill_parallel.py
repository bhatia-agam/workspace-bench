"""``run.PARALLEL`` waves (``ADAPT_FILL_PARALLEL``) and the mlmh cross-lane dedupe in lint."""

import importlib

from wsbench.adapt import lint, run, store


def test_parallel_defaults_to_1_and_reads_the_env(monkeypatch):
    monkeypatch.delenv("ADAPT_FILL_PARALLEL", raising=False)
    assert importlib.reload(run).PARALLEL == 1
    monkeypatch.setenv("ADAPT_FILL_PARALLEL", "4")
    assert importlib.reload(run).PARALLEL == 4
    monkeypatch.delenv("ADAPT_FILL_PARALLEL")
    importlib.reload(run)


def test_author_waves_runs_each_wave_once_and_restores_add_candidates():
    calls, add = [], store.add_candidates

    def write(model, family, tier, n, steer="", wave=0):
        calls.append((tier, n, steer, wave))
        assert store.add_candidates is not add  # appends are serialised while lanes run

    run._author_waves(write, "m", "multilingual_multihop", "t2", 240, "s", [105, 106, 107])
    assert sorted(calls) == [("t2", 240, "s", w) for w in (105, 106, 107)]
    assert store.add_candidates is add


def _it(i, lang="ru", bridge="Eiffel Tower", target="Париж", origin="authored"):
    return {"name": i, "lang": lang, "intermediates": [bridge], "target": target,
            "adapt": {"origin": origin}}  # fmt: skip


def test_mlmh_dedupe_against_the_bank_and_across_lanes():
    logged = [_it("orig-1", origin="original")]
    items = [
        _it("a"),  # same L2 / bridge / answer as a passing bank row
        _it("b", lang="id", target="Paris"),
        _it("c", lang="id", target="paris "),  # case / space fold: a duplicate of b
        _it("d", bridge="Louvre", target="Париж"),
    ]
    out = lint.lint_pairs("multilingual_multihop", items, logged)
    assert set(out) == {"a", "c"}
    assert "orig-1" in out["a"][0] and "b" in out["c"][0]
