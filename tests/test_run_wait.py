"""Plan 0092: the new ``judge`` / ``run`` defaults, ``wsbench run wait=`` (pending families, the
ready rule, ``_READS_DONE``), the failed-call line and the atomic sidecar. Offline, no real
sleep."""

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from summary_fakes import summary_args

from wsbench import cli, digest, llm, readouts, registry, runner
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult

GEMINI = "google/gemini-3.8-flash"
ROW = json.dumps({"id": "a", "layer": 36, "pos": 1, "samples": ["x"]}) + "\n"


def _ok(args: JudgeArgs, family: str = "ok") -> FamilyResult:
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.75,
        ci95=(0.5, 1.0),
        n_items=4,
        higher_is_better=True,
        chance=0.2,
        chance_label="1/5",
        complete=args.judge.pinned,
        pinned_instrument=args.judge.pinned,
        config={
            "judge_model": args.judge.model,
            "prompt_version": "v1",
            "aggregate": args.extra.get("aggregate", "native"),
        },
        counts={
            "n_expected_cells": 4,
            "n_missing_cells": 0,
            "n_unjudged_cells": 0,
            "n_empty_cells": 0,
            "skipped_rows": 0,
            "spend_usd": 1.5,
        },
        extras={},
    )


def _spec(name: str, run=_ok, model: str = GEMINI) -> EvalSpec:
    return register(
        EvalSpec(
            name=name,
            title=name.title(),
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
    """No network: ``llm.preflight`` records its calls; a client would fail the test."""
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    seen: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: seen.append((model, reasoning)))
    registry.FAMILIES.clear()
    return seen


def _land(root: Path, name: str, sidecar: bool = True) -> Path:
    """A family's readouts file, then (the producer's order) its sidecar."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.jsonl"
    path.write_text(ROW)
    if sidecar:
        readouts.write_sidecar(path, sampling="prose1")
    return path


class Ticker:
    """The runner's clock, sleep and future wait, patched: every poll tick advances the fake
    clock by ``runner.POLL`` and runs the callbacks registered for that tick (1-based)."""

    def __init__(self, monkeypatch):
        self.t = 0.0
        self.ticks = 0
        self.at: dict[int, list] = {}
        real_wait = runner.wait_futures
        monkeypatch.setattr(runner, "_clock", lambda: self.t)
        monkeypatch.setattr(runner, "_sleep", lambda d: self._tick(d))

        def wait(fs, timeout=None, return_when=None):
            done = real_wait(fs, timeout=0.01, return_when=return_when)
            self._tick(timeout)
            return done

        monkeypatch.setattr(runner, "wait_futures", wait)

    def _tick(self, d: float) -> None:
        assert d == runner.POLL
        self.t += d
        self.ticks += 1
        for fn in self.at.pop(self.ticks, []):
            fn()

    def on(self, tick: int, fn) -> None:
        self.at.setdefault(tick, []).append(fn)


@pytest.fixture
def ticker(monkeypatch):
    return Ticker(monkeypatch)


def _run(root: Path, out: Path, *extra: str) -> int:
    return main(
        ["run", "opts=aggregate=native", "all=True", f"readouts_root={root}", f"out={out}", *extra]
    )


def _manifest(out: Path) -> dict:
    return json.loads((out / "run.json").read_text())


# ---------------------------------------------------------------- defaults (plan §1, §2)


def test_defaults():
    for cmd in (cli.RunFamilies(), cli.JudgeFamily()):
        assert cmd.concurrency == 256 and cmd.rpm == 30000.0 and cmd.itpm == 60_000_000
    run = cli.RunFamilies()
    assert run.family_workers == 8 and run.wait == 0 and run.settle == 0
    # commands with their own defaults are not touched
    assert cli.Baseline().concurrency == 64 and cli.Baseline().rpm == 240.0
    assert cli.Capable().concurrency == 64 and cli.Capable().rpm == 240.0


def test_run_and_judge_apply_itpm_and_help_does_not(offline, tmp_path, monkeypatch):
    raised: list[int] = []
    monkeypatch.setattr(cli, "_raise_fd_limit", lambda: raised.append(1))
    _spec("g")
    root = tmp_path / "r"
    path = _land(root, "g")
    assert main(["run", "-h"]) == 0 and main(["run", "all=True", "out=o", "--show"]) == 2
    assert llm._ITPM == 0 and raised == []  # --help / a usage error leave the process alone
    assert _run(root, tmp_path / "o") == 0
    assert llm._ITPM == 60_000_000 and raised == [1]
    assert _run(root, tmp_path / "o", "itpm=0") == 0
    assert llm._ITPM == 0
    argv = ["judge", "opts=aggregate=native", "family=g", f"readouts={path}"]
    assert main([*argv, f"out={tmp_path / 'j'}", "itpm=1200"]) == 0
    assert llm._ITPM == 1200 and raised == [1, 1, 1]
    assert main([*argv, f"out={tmp_path / 'j'}", "itpm=-1"]) == 2


def test_itpm_is_not_stamped_in_results(offline, tmp_path):
    _spec("g")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "g")
    assert _run(root, out) == 0
    result = json.loads((out / "g" / "results.json").read_text())
    assert "itpm" not in result["config"] and "itpm" not in result
    assert "itpm" not in _manifest(out) and "itpm" not in _manifest(out)["families"]["g"]


def test_fd_limit_is_raised_to_the_hard_limit_best_effort(monkeypatch):
    import resource

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda which, lim: calls.append(lim))
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, 4096))
    cli._raise_fd_limit()
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, resource.RLIM_INFINITY))
    cli._raise_fd_limit()
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, 1 << 20))
    cli._raise_fd_limit()
    monkeypatch.setattr(resource, "getrlimit", lambda which: (1 << 20, 1 << 20))
    cli._raise_fd_limit()  # already above: left alone
    assert calls == [(4096, 4096), (65536, resource.RLIM_INFINITY), (65536, 1 << 20)]

    def refuse(which, lim):
        raise OSError("not permitted")

    monkeypatch.setattr(resource, "getrlimit", lambda which: (1024, 4096))
    monkeypatch.setattr(resource, "setrlimit", refuse)
    cli._raise_fd_limit()  # swallowed


@pytest.mark.parametrize("family", ["jailbreak_recognition", "agentic_misalignment"])
def test_digest_concurrency_cap_is_gone_and_the_rest_is_retained(family):
    a = summary_args(Path("r"), Path("o"), "pv")
    s = digest.settings(a, family)
    assert s.concurrency is None and s.timeout == 1800.0
    assert s.fallback == digest.settings(a, family).fallback != digest.settings(a).fallback
    assert "summ_concurrency" not in digest.FAMILY_DEFAULTS[family]
    assert digest.FAMILY_DEFAULTS[family]["summ_fallback"] == "none+claude-opus-5"
    assert "summ_concurrency" in digest.FAMILY_DEFAULT_KEYS
    five = summary_args(Path("r"), Path("o"), "pv", extra={"summ_concurrency": "5"})
    assert digest.settings(five, family).concurrency == 5


def test_agentic_keeps_its_other_digest_defaults():
    d = digest.FAMILY_DEFAULTS["agentic_misalignment"]
    assert d == {
        "summ_max": "25",
        "summ_timeout": "1800",
        "summ_fallback": "none+claude-opus-5",
        "summ_rare": "25",
    }
    s = digest.settings(summary_args(Path("r"), Path("o"), "pv"), "agentic_misalignment")
    assert s.max_items == 25 and s.max_rare == 25


# ---------------------------------------------------------------- 2b: failed calls are loud


def _failing(n: int):
    def run(args):
        for _ in range(n):
            llm._note_error(llm.Spend())  # what llm._one does when a call's retries run out
        return _ok(args)

    return run


LINE = (
    "{f}: {n} judge call(s) failed after retries; affected cells are unjudged or their items "
    "were digested on fewer layers"
)


def test_run_reports_failed_calls_per_family(offline, tmp_path, capsys):
    _spec("bad", _failing(3))
    _spec("good")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "bad")
    _land(root, "good")
    assert _run(root, out) == 0
    err = capsys.readouterr().err.splitlines()
    assert err == [LINE.format(f="bad", n=3)]  # one line, and none for the clean family
    fams = _manifest(out)["families"]
    assert fams["bad"]["complete"] is True and fams["good"]["complete"] is True  # unchanged


def test_judge_reports_failed_calls(offline, tmp_path, capsys):
    _spec("bad", _failing(1))
    _spec("good")
    path = _land(tmp_path / "r", "bad")
    argv = ["judge", "opts=aggregate=native", f"readouts={path}"]
    assert main([*argv, "family=bad", f"out={tmp_path / 'b'}"]) == 0
    assert capsys.readouterr().err.splitlines() == [LINE.format(f="bad", n=1)]
    assert main([*argv, "family=good", f"out={tmp_path / 'g'}"]) == 0
    assert capsys.readouterr().err == ""


def test_failed_calls_are_reported_when_the_family_then_exits(offline, tmp_path, capsys):
    def run(args):
        llm._note_error(llm.Spend())
        raise SystemExit("no cells in scope")

    _spec("bad", run)
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "bad")
    assert _run(root, out) == 2
    assert capsys.readouterr().err.splitlines() == [
        LINE.format(f="bad", n=1),
        "bad: failed (no cells in scope)",
    ]


# ---------------------------------------------------------------- the sidecar


def test_write_sidecar_is_atomic_and_leaves_no_tmp(tmp_path, monkeypatch):
    path = tmp_path / "f.jsonl"
    path.write_text(ROW)
    side = readouts.write_sidecar(path, sampling="prose1", reader="one")
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["f.jsonl", "f.jsonl.meta.json"]
    replaced: list[tuple[str, str]] = []
    real = os.replace

    def replace(src, dst):
        # the whole new sidecar is on disk under the temporary name before it takes the place
        assert json.loads(Path(src).read_text())["reader"] == "two"
        assert json.loads(Path(dst).read_text())["reader"] == "one"
        replaced.append((Path(src).name, Path(dst).name))
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    readouts.write_sidecar(path, sampling="prose1", reader="two")
    assert replaced == [(f"f.jsonl.meta.json.{os.getpid()}.tmp", "f.jsonl.meta.json")]
    assert readouts.read_sidecar(path)["reader"] == "two"
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["f.jsonl", side.name]

    def broken(src, dst):
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(OSError):
        readouts.write_sidecar(path, sampling="prose1", reader="three")
    assert readouts.read_sidecar(path)["reader"] == "two"  # the old one is intact, no .tmp left
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["f.jsonl", side.name]


def test_producer_removes_a_stale_sidecar_before_it_appends(tmp_path):
    from wsbench import readplan
    from wsbench.produce.methods import Readout
    from wsbench.produce.producer import Producer, Row

    out = tmp_path / "poetry.jsonl"
    side = readouts.sidecar_path(out)
    seen: list[bool] = []

    class Fake(Producer):
        def read_spec(self, spec, *, layers=None):
            seen.append(side.exists())  # never while the file grows
            return [Row(spec.id, 36, 0, "t", Readout(samples=["x"]))]

    ids = [s.id for s in readplan.plan("poetry")[:3]]
    p = Fake(backend=None, method=SimpleNamespace(name="fake", layers=None))  # type: ignore[arg-type]
    p.run_family("poetry", out, items=ids[:1])
    assert seen == [False] and side.exists() and runner.readouts_ready(out)
    first = side.read_text()
    p.run_family("poetry", out, items=ids)  # a resume: the first run's sidecar is stale
    assert seen == [False, False, False] and side.exists() and runner.readouts_ready(out)
    assert len(out.read_text().splitlines()) == 3 and json.loads(first)["reader"] == "fake"


# ---------------------------------------------------------------- the ready rule


def test_ready_rule(tmp_path, monkeypatch):
    path = tmp_path / "f.jsonl"
    assert not runner.readouts_ready(path)  # no file
    path.write_text(ROW)
    side = readouts.sidecar_path(path)
    assert not runner.readouts_ready(path)  # no sidecar, settle=0
    side.write_text("{}")
    assert runner.readouts_ready(path)
    st = path.stat()
    os.utime(side, (st.st_atime, st.st_mtime - 10))
    assert not runner.readouts_ready(path)  # a sidecar older than the file
    assert not runner.readouts_ready(path, settle=1)  # settle is for sidecar-less files only
    os.utime(side, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert runner.readouts_ready(path)  # equal mtimes count
    for bad in ('{"sampling": ', "[1]", '"x"'):  # half a sidecar, not an object
        side.write_text(bad)
        os.utime(side, (st.st_atime, st.st_mtime + 5))
        assert not runner.readouts_ready(path)
    side.unlink()
    monkeypatch.setattr(runner, "_wall", lambda: st.st_mtime + 19)
    assert not runner.readouts_ready(path, settle=20)
    monkeypatch.setattr(runner, "_wall", lambda: st.st_mtime + 20.5)
    assert runner.readouts_ready(path, settle=20) and not runner.readouts_ready(path)


# ---------------------------------------------------------------- wait


def test_a_ready_files_are_judged_without_waiting(offline, ticker, tmp_path, capsys):
    _spec("g")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "g")
    assert _run(root, out, "wait=30") == 0
    assert ticker.ticks == 0 and "landed after" not in capsys.readouterr().out
    m = _manifest(out)
    assert m["wait"] == 30.0 and m["families"]["g"]["status"] == "ok"
    assert "waited_s" not in m["families"]["g"]


def test_b_a_file_that_lands_after_two_polls_is_judged_late(offline, ticker, tmp_path, capsys):
    _spec("early")
    _spec("late")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "early")
    ticker.on(1, lambda: (root / "late.jsonl").write_text(ROW))  # the file, no sidecar yet
    ticker.on(2, lambda: _land(root, "late"))
    assert _run(root, out, "wait=60") == 0
    printed = capsys.readouterr().out
    assert "late: readouts landed after 4s" in printed and "early: readouts landed" not in printed
    assert ticker.ticks == 2
    fams = _manifest(out)["families"]
    assert fams["late"]["status"] == "ok" and fams["late"]["waited_s"] == 4.0
    assert fams["early"]["status"] == "ok" and "waited_s" not in fams["early"]
    assert (out / "late" / "results.json").exists()
    summary = (out / "summary.md").read_text()
    assert summary.count("| ok |") == 2 and "skipped" not in summary  # both rows, as today


def test_c_sidecar_less_file_pends_unless_settled(offline, ticker, tmp_path, monkeypatch):
    _spec("g")
    root, out = tmp_path / "r", tmp_path / "o"
    path = _land(root, "g", sidecar=False)
    assert _run(root, out, "wait=6") == 0
    fam = _manifest(out)["families"]["g"]
    assert fam == {
        "status": "skipped",
        "error": f"readouts at {path} not ready after 6s (no current sidecar)",
    }
    assert ticker.ticks == 3
    # settle=20: ready once the file has not changed for 20 s (10 ticks of the fake clock)
    base = path.stat().st_mtime
    monkeypatch.setattr(runner, "_wall", lambda: base + ticker.t - 6.0 + 0.5)  # 0.5: float slack
    assert _run(root, out, "wait=600", "settle=20") == 0
    fam = _manifest(out)["families"]["g"]
    assert fam["status"] == "ok" and fam["waited_s"] == 20.0 and ticker.ticks == 13


def test_c_sidecar_older_than_the_file_is_not_ready(offline, ticker, tmp_path, capsys):
    _spec("g")
    root, out = tmp_path / "r", tmp_path / "o"
    path = _land(root, "g")
    st = path.stat()
    os.utime(readouts.sidecar_path(path), (st.st_atime, st.st_mtime - 60))
    assert _run(root, out, "wait=2", "settle=0") == 0
    assert _manifest(out)["families"]["g"]["status"] == "skipped"
    assert f"g: skipped (readouts at {path} not ready after 2s (no current sidecar))" in (
        capsys.readouterr().out
    )


def test_d_a_file_that_never_appears_is_skipped_after_the_wait(offline, ticker, tmp_path, capsys):
    ran: list[str] = []

    def run(args):
        ran.append("x")
        return _ok(args)

    _spec("absent", run)
    _spec("good")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "good")
    assert _run(root, out, "wait=5") == 0  # exit code as for a skipped family
    msg = f"no readouts at {root / 'absent.jsonl'} after waiting 5s"
    assert f"absent: skipped ({msg})" in capsys.readouterr().out
    fams = _manifest(out)["families"]
    assert fams["absent"] == {"status": "skipped", "error": msg} and fams["good"]["status"] == "ok"
    assert ran == [] and ticker.ticks == 3  # 2 s ticks: 0, 2, 4, then 6 >= 5
    assert f"- absent: skipped — {msg}" in (out / "summary.md").read_text()


def test_e_wait_zero_is_the_pre_0092_run(offline, ticker, tmp_path, capsys, monkeypatch):
    def stale(args, family):
        raise SystemExit(f"{family}: stale subset entry; re-gate")

    monkeypatch.setattr(runner, "ati_entry", stale)
    _spec("absent")
    _spec("nosidecar")
    _spec("stale")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "nosidecar", sidecar=False)  # wait=0 never asks for a sidecar
    _land(root, "stale")
    assert _run(root, out) == 0
    cap = capsys.readouterr()
    assert ticker.ticks == 0
    assert cap.out.splitlines()[0] == f"absent: skipped (no readouts at {root / 'absent.jsonl'})"
    fams = _manifest(out)["families"]
    assert list(fams) == ["absent", "nosidecar", "stale"]
    assert fams["absent"] == {
        "status": "skipped",
        "error": f"no readouts at {root / 'absent.jsonl'}",
    }
    assert fams["nosidecar"]["status"] == "ok" and fams["stale"]["status"] == "ok"
    assert set(_manifest(out)) == {
        "started",
        "finished",
        "families",
        "judge_overrides",
        "readouts_root",
        "aggregate",
    }
    assert all("waited_s" not in f for f in fams.values())
    # under the ATI flag: the file check comes first, so a stale entry of a family with no file
    # is skipped (never failed), with and without wait=
    for extra, absent in (
        ((), f"no readouts at {root / 'absent.jsonl'}"),
        (("wait=2",), f"no readouts at {root / 'absent.jsonl'} after waiting 2s"),
    ):
        assert _run(root, out, "anti_text_inversion=True", *extra) == 2
        cap = capsys.readouterr()
        fams = _manifest(out)["families"]
        assert fams["absent"] == {"status": "skipped", "error": absent}
        assert fams["stale"] == {"status": "failed", "error": "stale: stale subset entry; re-gate"}
        assert "stale: failed (stale: stale subset entry; re-gate)" in cap.err
        assert f"absent: skipped ({absent})" in cap.out


def test_f_family_outside_the_fast_subset_is_skipped_at_once(offline, ticker, tmp_path, capsys):
    ran: list[str] = []

    def run(args):
        ran.append("x")
        return _ok(args)

    _spec("notfast", run)
    root, out = tmp_path / "r", tmp_path / "o"
    root.mkdir()
    argv = ["run", "--fast", "all=True", f"readouts_root={root}", f"out={out}", "wait=600"]
    assert main(argv) == 0
    assert "notfast: skipped (not in fast-v2)" in capsys.readouterr().out
    assert _manifest(out)["families"]["notfast"] == {"status": "skipped", "error": "not in fast-v2"}
    assert ticker.ticks == 0 and ran == [] and offline == []


@pytest.mark.parametrize("bad", ["dry_run=True", "layers=each"])
def test_g_wait_refuses_dry_run_and_layers_each(offline, tmp_path, capsys, bad):
    _spec("g")
    cmd = cli.RunFamilies()
    cmd.all, cmd.readouts_root, cmd.out, cmd.wait = True, "r", "o", 5
    key, value = bad.split("=")
    setattr(cmd, key, value == "True" if key == "dry_run" else value)
    with pytest.raises(ValueError, match="wait="):
        cmd.finalize()
    assert _run(tmp_path / "r", tmp_path / "o", "wait=5", bad) == 2
    assert "wait=" in capsys.readouterr().err and not (tmp_path / "o").exists()
    assert _run(tmp_path / "r", tmp_path / "o", "wait=-1") == 2
    assert _run(tmp_path / "r", tmp_path / "o", "wait=1", "settle=-1") == 2


def test_h_outcomes_stay_in_specs_order(offline, ticker, tmp_path, capsys):
    done: list[str] = []

    def run(args):
        done.append(args.readouts.stem)
        return _ok(args)

    for name in ("a", "b", "c"):
        _spec(name, run)
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "c")
    ticker.on(1, lambda: _land(root, "b"))
    ticker.on(3, lambda: _land(root, "a"))
    assert _run(root, out, "wait=60", "json=True") == 0
    assert done == ["c", "b", "a"]  # finished in landing order
    lines = capsys.readouterr().out.strip().splitlines()
    payload = json.loads(lines[-1])  # the JSON payload is still the last stdout line
    assert list(payload["statuses"]) == ["a", "b", "c"]
    fams = _manifest(out)["families"]
    assert list(fams) == ["a", "b", "c"]
    assert [fams[n].get("waited_s") for n in fams] == [6.0, 2.0, None]
    assert [x for x in lines if "landed after" in x] == [
        "b: readouts landed after 2s",
        "a: readouts landed after 6s",
    ]


def test_i_preflight_covers_pending_families_before_any_submit(offline, ticker, tmp_path):
    at_first_run: list[int] = []

    def run(args):
        at_first_run.append(len(offline))
        return _ok(args)

    _spec("ready", run)
    _spec("pending", run, model="claude-sonnet-5")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "ready")
    ticker.on(2, lambda: _land(root, "pending"))
    argv = ["run", "all=True", f"readouts_root={root}", f"out={out}", "wait=60"]  # summary mode
    assert main(argv) == 0
    models = {m for m, _r in offline}
    assert models == {GEMINI, "claude-sonnet-5", digest.DEFAULT_MODEL}
    assert at_first_run == [len(offline), len(offline)]  # nothing was preflighted after a submit
    assert _manifest(out)["families"]["pending"]["status"] == "ok"


def test_i_preflight_failure_of_a_pending_family_exits_3_before_any_call(
    offline, ticker, tmp_path, monkeypatch, capsys
):
    def preflight(model, reasoning):
        if model == "claude-sonnet-5":
            raise llm.JudgeConfigError("ANTHROPIC_API_KEY is missing")

    monkeypatch.setattr(llm, "preflight", preflight)
    ran: list[str] = []

    def run(args):
        ran.append("x")
        return _ok(args)

    _spec("ready", run)
    _spec("pending", run, model="claude-sonnet-5")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "ready")
    assert _run(root, out, "wait=60") == 3
    assert ran == [] and ticker.ticks == 0
    assert "ANTHROPIC_API_KEY is missing" in capsys.readouterr().err


def test_j_reads_done_ends_the_wait_at_once(offline, ticker, tmp_path, capsys):
    _spec("early")
    _spec("late")
    _spec("never")
    _spec("half")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "early")

    def finish():
        _land(root, "late")  # lands together with the sentinel: still taken
        _land(root, "half", sidecar=False)
        (root / runner.READS_DONE).write_text("")

    ticker.on(1, finish)
    assert _run(root, out, "wait=3600") == 0
    assert ticker.ticks == 1
    fams = _manifest(out)["families"]
    assert fams["late"]["status"] == "ok" and fams["late"]["waited_s"] == 2.0
    never = f"no readouts at {root / 'never.jsonl'}"  # today's message, no "after waiting"
    assert fams["never"] == {"status": "skipped", "error": never}
    assert fams["half"] == {
        "status": "skipped",
        "error": f"readouts at {root / 'half.jsonl'} not ready after 3600s (no current sidecar)",
    }
    assert f"never: skipped ({never})" in capsys.readouterr().out
    # a sentinel left from an earlier read ends the wait before the first tick
    ticker.ticks = 0
    (root / "late.jsonl").unlink()
    assert _run(root, out, "wait=3600") == 0 and ticker.ticks == 0
    assert _manifest(out)["families"]["late"]["status"] == "skipped"


def test_k_worker_exception_propagates_and_pending_is_not_submitted(offline, ticker, tmp_path):
    ran: list[str] = []

    def boom(args):
        raise RuntimeError("unexpected")

    def run(args):
        ran.append("x")
        return _ok(args)

    _spec("boom", boom)
    _spec("pending", run)
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "boom")
    ticker.on(3, lambda: _land(root, "pending"))  # would land later
    with pytest.raises(RuntimeError, match="unexpected"):
        _run(root, out, "wait=60")
    assert ran == [] and ticker.ticks <= 2 and not (out / "run.json").exists()


def test_l_family_workers_zero_runs_every_family_at_once(offline, tmp_path):
    barrier = threading.Barrier(5, timeout=5)

    def run(args):
        barrier.wait()  # BrokenBarrierError (timeout) propagates unless all five run together
        return _ok(args)

    root, out = tmp_path / "r", tmp_path / "o"
    for n in ("a", "b", "c", "d", "e"):
        _spec(n, run)
        _land(root, n)
    assert _run(root, out) == 0  # the default
    assert _run(root, out, "family_workers=0") == 0
    assert {v["status"] for v in _manifest(out)["families"].values()} == {"ok"}


def test_l_family_workers_two_caps_at_two(offline, tmp_path):
    lock = threading.Lock()
    active = {"n": 0, "max": 0}
    pair = threading.Barrier(2, timeout=5)

    def run(args):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        pair.wait()  # two at a time do run together
        with lock:
            active["n"] -= 1
        return _ok(args)

    root, out = tmp_path / "r", tmp_path / "o"
    for n in ("a", "b", "c", "d"):
        _spec(n, run)
        _land(root, n)
    assert _run(root, out, "family_workers=2") == 0
    assert active["max"] == 2


def test_pending_families_count_for_the_pool_size(offline, ticker, tmp_path):
    """The pool is sized over runnable + pending, so two late families still run together."""
    barrier = threading.Barrier(2, timeout=5)

    def run(args):
        barrier.wait()
        return _ok(args)

    _spec("a", run)
    _spec("b", run)
    root, out = tmp_path / "r", tmp_path / "o"
    ticker.on(1, lambda: (_land(root, "a"), _land(root, "b")))
    assert _run(root, out, "wait=60") == 0
    assert {v["status"] for v in _manifest(out)["families"].values()} == {"ok"}


def test_interrupt_while_waiting_skips_the_pending_families(offline, ticker, tmp_path):
    _spec("early")
    _spec("pending")
    root, out = tmp_path / "r", tmp_path / "o"
    _land(root, "early")

    def interrupt():
        raise KeyboardInterrupt

    ticker.on(2, interrupt)
    assert _run(root, out, "wait=60") == 130
    fams = _manifest(out)["families"]
    assert fams["early"]["status"] == "ok"
    assert fams["pending"] == {"status": "skipped", "error": "interrupted"}


def test_legacy_key_file_counts_and_its_line_prints_once(offline, ticker, tmp_path, capsys):
    """A pending family is re-evaluated through ``readouts_path``, so a former key's file counts;
    the "reading legacy" line prints once, at submit."""
    _spec("introspection")
    root, out = tmp_path / "r", tmp_path / "o"
    root.mkdir()
    old = next(k for k, v in registry.LEGACY_FAMILY_NAMES.items() if v == "introspection")
    ticker.on(2, lambda: _land(root, old))
    assert _run(root, out, "wait=60") == 0
    printed = capsys.readouterr().out
    assert printed.count(f"introspection: reading legacy {old}.jsonl") == 1
    assert _manifest(out)["families"]["introspection"]["waited_s"] == 4.0
