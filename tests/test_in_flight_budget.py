"""`wsbench run in_flight_total=N`: in-flight judge calls split by each family's work."""

from pathlib import Path
from types import SimpleNamespace

from wsbench import runner


def test_shares_follow_the_work_and_keep_a_floor():
    work = {"introspection": 38.9, "hinted_cutoff": 10.9, "poetry": 0.5, "waited_for": 0.0}
    got = runner.in_flight_shares(work, 176)
    assert sum(got.values()) == 176
    assert got["introspection"] > got["hinted_cutoff"] > got["poetry"] >= 2
    assert got["waited_for"] == got["poetry"]  # no estimate yet: counted as the smallest
    assert runner.in_flight_shares({"a": 1.0, "b": 1.0}, 3) == {"a": 2, "b": 2}  # the floor wins
    assert runner.in_flight_shares({}, 10) == {}


def test_judge_argv_takes_the_family_share():
    args = SimpleNamespace(
        concurrency=12,
        rpm=600.0,
        judge_model="",
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        opt=[],
        _in_flight_shares={"a": 40},
    )
    argv = runner.judge_argv("a", args, Path("r.jsonl"), Path("out"))
    assert "concurrency=40" in argv
    assert "concurrency=12" in runner.judge_argv("b", args, Path("r.jsonl"), Path("out"))
    del args._in_flight_shares  # off: every family gets `concurrency`
    assert "concurrency=12" in runner.judge_argv("a", args, Path("r.jsonl"), Path("out"))
