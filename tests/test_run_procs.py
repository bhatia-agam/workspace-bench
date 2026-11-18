"""Plan 0092 §5: ``wsbench run`` judges one ``wsbench judge`` process per family (the spawn seam
faked, so no subprocess and no network; one real, offline subprocess smoke), ``judge outcome=``
and the pacer files the processes share."""

import json
import os
import signal
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pydra
import pytest

from wsbench import cli, fast, llm, readouts, registry, runner
from wsbench.baselines import text_inversion
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult, write_results
from wsbench.runner import FamilyOutcome

GEMINI = "google/gemini-3.8-flash"
ROW = json.dumps({"id": "a", "layer": 36, "pos": 1, "samples": ["x"]}) + "\n"
REPO = Path(__file__).resolve().parents[1]
registry.load_all()  # before any test isolates the registry: the smoke needs the real families
RUN_ONLY = ("all", "families", "readouts_root", "family_workers", "wait", "settle", "json")
RUN_ONLY += ("hb_method", "include_superseded", "dry_run", "procs")
TIMEOUT = 20  # seconds a fake child waits for the test's own events before failing the test


def _result(family: str, aggregate: str = "native", pinned: bool = True) -> FamilyResult:
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.75,
        ci95=(0.5, 1.0),
        n_items=4,
        higher_is_better=True,
        chance=0.2,
        chance_label="1/5",
        complete=pinned,
        pinned_instrument=pinned,
        config={"judge_model": GEMINI, "prompt_version": "v1", "aggregate": aggregate},
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


def _ok(args: JudgeArgs, family: str = "ok") -> FamilyResult:
    return _result(family, args.extra.get("aggregate", "native"), args.judge.pinned)


def _in_process(args: JudgeArgs) -> FamilyResult:
    pytest.fail("process mode must not run a family in the parent")


def _spec(name: str, run=_in_process) -> EvalSpec:
    return register(
        EvalSpec(
            name=name,
            title=name.title(),
            group="logic",
            bank=Path(f"evals/{name}/items.json"),
            judge=JudgeConfig(model=GEMINI),
            metric="pass_rate",
            higher_is_better=True,
            run=run,
        )
    )


def _land(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.jsonl"
    path.write_text(ROW)
    readouts.write_sidecar(path, sampling="prose1")
    return path


@pytest.fixture
def offline(monkeypatch):
    """No network: ``llm.preflight`` records its calls; a client would fail the test."""
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.delenv(llm.SLOTS_ENV, raising=False)
    monkeypatch.delenv(llm.PACER_ENV, raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    seen: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: seen.append((model, reasoning)))
    monkeypatch.setattr(runner, "die_with_parent", lambda: None)  # never on the test process
    registry.FAMILIES.clear()
    return seen


@pytest.fixture(autouse=True)
def rundirs(monkeypatch, tmp_path):
    """Every run-private directory of a test is made under this one (and must be gone after)."""
    d = tmp_path / "rundirs"
    d.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(d))
    return d


class Child:
    """A Popen-like fake of one judge process: its script runs in ``wait()`` (the worker
    thread), and ``terminate`` / ``kill`` end it like a signal."""

    def __init__(self, cmd, env, script):
        self.cmd, self.env, self.script = list(cmd), dict(env), script
        self.kv = dict(a.split("=", 1) for a in cmd[4:])
        self.family = self.kv["family"]
        self.returncode: int | None = None
        self.started = threading.Event()  # wait() was entered
        self.done = threading.Event()
        self.terminated = False
        self._ran = False

    def finish(self, code: int) -> None:
        if not self.done.is_set():
            self.returncode = code
            self.done.set()

    def wait(self, timeout=None):
        self.started.set()
        if not self._ran:
            self._ran = True
            self.script(self)
        if not self.done.wait(timeout):
            raise subprocess.TimeoutExpired(self.cmd, timeout)
        return self.returncode

    def poll(self):
        return self.returncode if self.done.is_set() else None

    def terminate(self):
        self.terminated = True
        self.finish(-signal.SIGTERM)

    def kill(self):
        self.finish(-signal.SIGKILL)

    # what a script does
    def ok(self) -> None:
        write_results(Path(self.kv["out"]), _result(self.family))
        self.outcome("ok")
        self.finish(0)

    def outcome(self, status: str, error: str | None = None, exit_code: int = 0) -> None:
        oc = FamilyOutcome(self.family, status, error=error, exit_code=exit_code)
        runner.write_outcome(Path(self.kv["outcome"]), oc)

    def fail(self, code: int, error: str) -> None:
        self.outcome("failed", error, code)
        self.finish(code)

    def hang(self) -> None:
        """Run until terminated."""
        assert self.done.wait(TIMEOUT), f"{self.family}: never terminated"


class Spawner:
    def __init__(self):
        self.scripts: dict = {}
        self.children: dict[str, Child] = {}
        self.order: list[str] = []
        self.seen: dict[str, threading.Event] = {}

    def event(self, name: str) -> threading.Event:
        return self.seen.setdefault(name, threading.Event())

    def __call__(self, cmd, env):
        child = Child(cmd, env, self.scripts.get(cmd[4].split("=", 1)[1], Child.ok))
        self.children[child.family] = child
        self.order.append(child.family)
        self.event(child.family).set()
        return child


@pytest.fixture
def spawner(monkeypatch):
    s = Spawner()
    monkeypatch.setattr(runner, "_spawn", s)
    return s


def _families(tmp_path, *names):
    root, out = tmp_path / "r", tmp_path / "o"
    root.mkdir(exist_ok=True)
    for n in names:
        _spec(n)
        _land(root, n)
    return root, out


def _run(root, out, names, *extra) -> int:
    fams = "families=" + ",".join(names)
    argv = ["run", fams, f"readouts_root={root}", f"out={out}", "opts=aggregate=native"]
    return main([*argv, "procs=True", *extra])


def _manifest(out: Path) -> dict:
    return json.loads((out / "run.json").read_text())


def _config(*argv: str) -> cli.RunFamilies:
    cfg = cli.RunFamilies()
    pydra.apply_overrides(cfg, ["all=True", "readouts_root=r", "out=o", *argv])
    return cfg


# ---------------------------------------------------------------- the child's command


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["judge_model=claude-sonnet-5", "layers=20,36", "limit=3", "allow_missing=True"],
        ["layers=20", "items=a,b|c", "concurrency=7", "rpm=11.5", "itpm=1234"],
        ["opts=aggregate=native,summ_layers=union", "reads=lite", "sampling=prose1", "itpm=0"],
        ["anti_text_inversion=True", "ati_variant=v", "ati_opt_in=nyt_connections"],
        ["fast=True", "items=a,b", "wait=5", "settle=2", "family_workers=3", "json=True"],
        ["fast=safety", "items=a,b", "limit=2"],
        ["hb_method=m", "include_superseded=True", "procs=True"],
    ],
)
def test_child_argv_parses_back_to_the_runs_values(monkeypatch, argv):
    """Every forwarded key gives the child ``JudgeFamily`` the run's value, and no run-only key
    is in the command."""
    monkeypatch.setattr(text_inversion, "frozen_path", lambda variant: Path("x"))
    run = _config(*argv)
    cmd = runner.judge_argv("fam", run, Path("r/fam.jsonl"), Path("o/fam"))
    assert cmd[1:4] == ["-m", "wsbench", "judge"]
    keys = [a.split("=", 1)[0] for a in cmd[4:]]
    assert len(keys) == len(set(keys)) and not set(keys) & set(RUN_ONLY)
    assert keys[:7] == ["family", "readouts", "out", "outcome", "concurrency", "rpm", "itpm"]
    child = cli.JudgeFamily()
    pydra.apply_overrides(child, cmd[4:])
    assert child.family == "fam" and child.readouts == Path("r/fam.jsonl")
    assert child.out == Path("o/fam") and child.outcome == Path("o/fam/outcome.json")
    forwarded = ("judge_model", "layers", "items", "limit", "allow_missing", "concurrency")
    forwarded += ("rpm", "itpm", "anti_text_inversion", "ati_variant", "ati_opt_in", "opt")
    forwarded += ("fast", "each", "dry_run")
    for k in forwarded:
        assert getattr(child, k) == getattr(run, k), k
    assert type(child.rpm) is type(run.rpm) and type(child.itpm) is type(run.itpm)


@pytest.mark.parametrize("namespace", [False, True])
def test_child_argv_names_the_active_fast_subset(monkeypatch, namespace):
    """Plan 0095: under fast the child is told the ACTIVE subset (``fast=safety`` by reverse
    lookup of ``fast.VERSION`` in ``fast.VARIANTS``, with or without ``fast_variant`` on the
    namespace) and selects it itself; the default and a test-patched fast-v1 stay ``fast=True``."""
    run = _config("fast=safety")
    assert run.fast is True and run.fast_variant == "safety"
    args = run
    if namespace:  # a Python caller's hand-built namespace: no fast_variant attribute
        keys = ("concurrency", "rpm", "judge_model", "layers", "items", "limit", "allow_missing")
        args = SimpleNamespace(**{k: getattr(run, k) for k in keys}, opt=[], fast=True)

    def fast_arg() -> list[str]:
        cmd = runner.judge_argv("fam", args, Path("r/fam.jsonl"), Path("o/fam"))
        return [a for a in cmd[4:] if a.split("=", 1)[0].startswith("fast")]

    assert fast_arg() == ["fast=True"]  # finalize selected nothing: the default subset
    assert fast.select("safety") == "fast-safety-v1"
    cmd = runner.judge_argv("fam", args, Path("r/fam.jsonl"), Path("o/fam"))
    assert fast_arg() == ["fast=safety"]
    child = cli.JudgeFamily()
    pydra.apply_overrides(child, cmd[4:])
    assert child.fast is True and child.fast_variant == "safety"
    monkeypatch.setattr(fast, "VERSION", "fast-v1")
    assert fast_arg() == ["fast=True"]
    args.fast = False
    monkeypatch.setattr(fast, "VERSION", "fast-safety-v1")
    assert fast_arg() == []


def test_child_environment_and_the_run_directory(offline, spawner, rundirs, tmp_path):
    """The children get the parent's environment plus the unbuffered flag, the run's slots and
    its pacer directory; the parent's own environment is untouched and the directory is gone."""
    root, out = _families(tmp_path, "a")
    made: list[Path] = []

    def script(child):
        made.extend(rundirs.iterdir())
        assert (made[0] / "slots").is_dir() and (made[0] / "pacer").is_dir()
        child.ok()

    spawner.scripts["a"] = script
    before = dict(os.environ)
    assert _run(root, out, ["a"]) == 0
    env = spawner.children["a"].env
    assert len(made) == 1 and made[0].name.startswith("wsb-run-")
    assert env["PYTHONUNBUFFERED"] == "1"
    assert (
        env[llm.SLOTS_ENV] == f"{made[0] / 'slots'}:{runner.RUN_SLOTS}" and runner.RUN_SLOTS == 1500
    )
    assert env[llm.PACER_ENV] == str(made[0] / "pacer")
    added = ("PYTHONUNBUFFERED", llm.SLOTS_ENV, llm.PACER_ENV)
    assert {k: v for k, v in env.items() if k not in added} == {
        k: v for k, v in before.items() if k not in added
    }
    assert dict(os.environ) == before
    assert list(rundirs.iterdir()) == []
    assert not out.is_relative_to(made[0]) and not made[0].is_relative_to(out)


def test_inherited_wsb_slots_is_not_replaced(offline, spawner, rundirs, tmp_path, monkeypatch):
    root, out = _families(tmp_path, "a")
    monkeypatch.setenv(llm.SLOTS_ENV, f"{tmp_path / 'mine'}:7")
    assert _run(root, out, ["a"]) == 0
    assert spawner.children["a"].env[llm.SLOTS_ENV] == f"{tmp_path / 'mine'}:7"
    assert list(rundirs.iterdir()) == []


def test_failing_flock_probe_exits_3_before_any_spawn(
    offline, spawner, rundirs, tmp_path, monkeypatch, capsys
):
    root, out = _families(tmp_path, "a")

    def no_locks(d):
        raise OSError(38, "Function not implemented")

    monkeypatch.setattr(runner, "_probe_flock", no_locks)
    assert _run(root, out, ["a"]) == 3
    assert spawner.order == [] and list(rundirs.iterdir()) == []
    err = capsys.readouterr().err
    assert "file locks do not work" in err and "procs=False" in err
    assert not (out / "run.json").exists()


# ---------------------------------------------------------------- outcome mapping


def test_outcomes_map_in_specs_order(offline, spawner, tmp_path, capsys):
    """ok / failed 2 / failed 3 from the outcome file; exit 2 without one; a signal fails that
    family only. Outcomes stay in ``specs`` order whatever finishes first."""
    names = ["e", "d", "c", "b", "a"]
    root, out = _families(tmp_path, *names)

    def last(child):  # "e" finishes after every other family
        for n in names[1:]:
            assert spawner.event(n).wait(TIMEOUT)
            assert spawner.children[n].done.wait(TIMEOUT)
        child.ok()

    spawner.scripts.update(
        e=last,
        d=lambda c: c.finish(2),
        c=lambda c: c.fail(3, "no key for claude"),
        b=lambda c: c.fail(2, "no cells in scope"),
        a=lambda c: c.finish(-signal.SIGKILL),
    )
    assert _run(root, out, names, "family_workers=0") == 3
    fams = _manifest(out)["families"]
    assert list(fams) == names
    assert fams["e"]["status"] == "ok" and fams["e"]["value"] == 0.75
    assert fams["e"]["results_path"] == str(out / "e" / "results.json")
    assert fams["d"] == {"status": "failed", "error": "judge process exited 2"}
    assert fams["c"] == {"status": "failed", "error": "no key for claude"}
    assert fams["b"] == {"status": "failed", "error": "no cells in scope"}
    assert fams["a"] == {"status": "failed", "error": "judge process killed by signal 9"}
    assert set(_manifest(out)) == {
        "started",
        "finished",
        "families",
        "judge_overrides",
        "readouts_root",
        "aggregate",
    }
    err = capsys.readouterr().err
    assert "a: failed (judge process killed by signal 9)" in err
    assert not any((out / n / "outcome.json").exists() for n in names)
    summary = (out / "summary.md").read_text()
    assert "- c: failed — no key for claude" in summary


def test_exit_code_2_without_a_config_error(offline, spawner, tmp_path):
    root, out = _families(tmp_path, "a", "b")
    spawner.scripts["b"] = lambda c: c.fail(2, "no cells in scope")
    assert _run(root, out, ["a", "b"]) == 2
    spawner.scripts["b"] = Child.ok
    assert _run(root, out, ["a", "b"]) == 0


def test_any_other_exit_raises_and_terminates_the_others(offline, spawner, rundirs, tmp_path):
    root, out = _families(tmp_path, "a", "b")

    def crash(child):  # an uncaught traceback in the child, once "b" is running
        assert spawner.event("b").wait(TIMEOUT)
        assert spawner.children["b"].started.wait(TIMEOUT)
        child.finish(1)

    spawner.scripts.update(a=crash, b=Child.hang)
    with pytest.raises(RuntimeError, match="a: judge process exited 1"):
        _run(root, out, ["a", "b"])
    assert spawner.children["b"].terminated
    assert list(rundirs.iterdir()) == [] and not (out / "run.json").exists()


def test_exit_0_without_an_outcome_raises(offline, spawner, tmp_path):
    root, out = _families(tmp_path, "a")
    spawner.scripts["a"] = lambda c: c.finish(0)
    with pytest.raises(RuntimeError, match="exited 0 without an outcome"):
        _run(root, out, ["a"])


def test_ok_with_unreadable_results_raises(offline, spawner, rundirs, tmp_path):
    root, out = _families(tmp_path, "a")

    def script(child):
        (out / "a").mkdir(parents=True, exist_ok=True)
        (out / "a" / "results.json").write_text("{not json")
        child.outcome("ok")
        child.finish(0)

    spawner.scripts["a"] = script
    with pytest.raises(ValueError):
        _run(root, out, ["a"])
    assert list(rundirs.iterdir()) == []


def test_stale_outcome_file_is_ignored(offline, spawner, tmp_path):
    """An ``outcome.json`` (and results) left by an earlier run is deleted before the spawn."""
    root, out = _families(tmp_path, "a")
    write_results(out / "a", _result("a"))
    stale = out / "a" / "outcome.json"
    stale.write_text(json.dumps({"family": "a", "status": "ok", "error": None, "exit_code": 0}))
    at_spawn: list[bool] = []

    def script(child):
        at_spawn.append(stale.exists())
        child.finish(2)

    spawner.scripts["a"] = script
    assert _run(root, out, ["a"]) == 2
    assert at_spawn == [False] and not stale.exists()
    assert _manifest(out)["families"]["a"] == {
        "status": "failed",
        "error": "judge process exited 2",
    }


def test_out_of_destination_is_honoured(offline, spawner, tmp_path):
    """``_one_proc`` gets the ``dest`` the loop computes, so ``out_of`` reaches the child."""
    root, out = _families(tmp_path, "a")
    args = _config("opts=aggregate=native", "procs=True")
    specs = [registry.get("a")]
    outcomes, code = runner.run_families(
        specs, args, readouts_root=root, out=out, out_of=lambda name: out / "elsewhere" / name
    )
    assert code == 0 and outcomes[0].status == "ok"
    assert spawner.children["a"].kv["out"] == str(out / "elsewhere" / "a")
    assert spawner.children["a"].kv["readouts"] == str(root / "a.jsonl")


def test_parent_checks_stay_in_the_parent(offline, spawner, tmp_path, capsys):
    """A missing file is skipped and the preflight runs in the parent, before any spawn."""
    root, out = _families(tmp_path, "a")
    _spec("absent")
    at_spawn: list[int] = []
    spawner.scripts["a"] = lambda c: (at_spawn.append(len(offline)), c.ok())
    assert _run(root, out, ["absent", "a"]) == 0
    assert spawner.order == ["a"] and at_spawn == [1] and [m for m, _r in offline] == [GEMINI]
    fams = _manifest(out)["families"]
    assert fams["absent"]["status"] == "skipped" and "no readouts at" in fams["absent"]["error"]


def test_preflight_failure_exits_3_before_any_spawn(
    offline, spawner, rundirs, tmp_path, monkeypatch
):
    root, out = _families(tmp_path, "a")

    def boom(model, reasoning):
        raise llm.JudgeConfigError("no key")

    monkeypatch.setattr(llm, "preflight", boom)
    assert _run(root, out, ["a"]) == 3
    assert spawner.order == [] and list(rundirs.iterdir()) == []


def test_family_workers_caps_the_children_at_once(offline, spawner, tmp_path):
    names = ["a", "b", "c", "d"]
    root, out = _families(tmp_path, *names)
    lock, live, peak = threading.Lock(), [0], [0]
    gate = threading.Barrier(2, timeout=TIMEOUT)

    def script(child):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        gate.wait()  # two at a time, or the test fails
        with lock:
            live[0] -= 1
        child.ok()

    spawner.scripts.update(dict.fromkeys(names, script))
    assert _run(root, out, names, "family_workers=2") == 0
    assert peak[0] == 2


def test_wait_submits_a_late_family_in_process_mode(offline, spawner, tmp_path, monkeypatch):
    root, out = _families(tmp_path, "early")
    _spec("late")
    clock = [0.0]
    real_wait = runner.wait_futures

    def tick(d):
        assert d == runner.POLL
        clock[0] += d
        if clock[0] == 2 * runner.POLL:
            _land(root, "late")

    def wait(fs, timeout=None, return_when=None):
        done = real_wait(fs, timeout=0.01, return_when=return_when)
        tick(timeout)
        return done

    monkeypatch.setattr(runner, "_clock", lambda: clock[0])
    monkeypatch.setattr(runner, "_sleep", tick)
    monkeypatch.setattr(runner, "wait_futures", wait)
    assert _run(root, out, ["early", "late"], "wait=60") == 0
    assert spawner.order == ["early", "late"]
    fams = _manifest(out)["families"]
    assert fams["early"]["status"] == "ok" and "waited_s" not in fams["early"]
    assert fams["late"]["status"] == "ok" and fams["late"]["waited_s"] == 2 * runner.POLL


# ---------------------------------------------------------------- interrupts and cleanup


def _interrupt_once_running(monkeypatch, spawner, name: str):
    """``as_completed`` raises ``KeyboardInterrupt`` in the main thread once ``name`` runs."""

    def as_completed(fs):
        assert spawner.event(name).wait(TIMEOUT)
        assert spawner.children[name].started.wait(TIMEOUT)
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, "as_completed", as_completed)


def test_first_interrupt_waits_for_the_children_and_exits_130(
    offline, spawner, rundirs, tmp_path, monkeypatch
):
    root, out = _families(tmp_path, "a", "b")
    waiting = threading.Event()

    class Pool(ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            waiting.set()  # the parent is now waiting for the children in flight
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def script(child):
        assert waiting.wait(TIMEOUT)
        child.ok()

    spawner.scripts["a"] = script
    monkeypatch.setattr(runner, "ThreadPoolExecutor", Pool)
    _interrupt_once_running(monkeypatch, spawner, "a")
    assert _run(root, out, ["a", "b"], "family_workers=1") == 130
    fams = _manifest(out)["families"]
    assert fams["a"]["status"] == "ok" and not spawner.children["a"].terminated
    assert fams["b"] == {"status": "skipped", "error": "interrupted"}
    assert spawner.order == ["a"] and list(rundirs.iterdir()) == []


def test_second_interrupt_terminates_the_children(
    offline, spawner, rundirs, tmp_path, monkeypatch, capsys
):
    root, out = _families(tmp_path, "a", "b")
    calls: list[bool] = []

    class Pool(ThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            calls.append(wait)
            if len(calls) == 1:  # the second Ctrl-C, while waiting for the children
                raise KeyboardInterrupt
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    spawner.scripts.update(a=Child.hang, b=Child.hang)
    monkeypatch.setattr(runner, "ThreadPoolExecutor", Pool)
    _interrupt_once_running(monkeypatch, spawner, "b")
    assert _run(root, out, ["a", "b"]) == 130
    assert spawner.children["a"].terminated and spawner.children["b"].terminated
    fams = _manifest(out)["families"]
    assert fams["a"] == {"status": "skipped", "error": "interrupted"}
    assert fams["b"] == {"status": "skipped", "error": "interrupted"}
    assert "terminating the judge processes" in capsys.readouterr().err
    assert list(rundirs.iterdir()) == []


def test_no_spawn_after_the_stop_flag(offline, spawner, tmp_path):
    """A future that starts after the stop flag was set returns skipped ("interrupted")."""
    root, out = _families(tmp_path, "a")
    procs = runner._Procs(_config("opts=aggregate=native"))
    procs.stop.set()
    oc = runner._one_proc(procs, registry.get("a"), root / "a.jsonl", out / "a")
    assert (oc.status, oc.error, oc.exit_code) == ("skipped", "interrupted", 0)
    assert spawner.order == []


def test_sigterm_runs_the_cleanup(offline, spawner, rundirs, tmp_path, monkeypatch):
    """SIGTERM during a run: the children are terminated, the directory is removed, the
    handlers are restored, and the process exits 128 + SIGTERM."""
    root, out = _families(tmp_path, "a")
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    spawner.scripts["a"] = Child.hang
    never = threading.Event()

    def as_completed(fs):
        assert spawner.event("a").wait(TIMEOUT)
        assert spawner.children["a"].started.wait(TIMEOUT)
        # only with the run's own handler in place (else the signal would end the test run)
        assert signal.getsignal(signal.SIGTERM) is runner._on_signal
        assert signal.getsignal(signal.SIGHUP) is runner._on_signal
        os.kill(os.getpid(), signal.SIGTERM)
        never.wait(TIMEOUT)  # the handler raises here, in the main thread
        pytest.fail("SIGTERM did not interrupt the run")

    monkeypatch.setattr(runner, "as_completed", as_completed)
    with pytest.raises(SystemExit) as e:
        _run(root, out, ["a"])
    assert e.value.code == 128 + signal.SIGTERM
    assert spawner.children["a"].terminated
    assert {s: signal.getsignal(s) for s in before} == before
    assert list(rundirs.iterdir()) == []


# ---------------------------------------------------------------- the mode switch


def test_procs_key_environment_and_default(monkeypatch):
    monkeypatch.delenv(runner.RUN_PROCS_ENV, raising=False)
    assert cli.RunFamilies().procs is None and _config().procs is True  # unset: on
    assert _config("procs=False").procs is False
    monkeypatch.setenv(runner.RUN_PROCS_ENV, "0")
    assert _config().procs is False
    assert _config("procs=True").procs is True  # the key beats the environment
    monkeypatch.setenv(runner.RUN_PROCS_ENV, "1")
    assert _config().procs is True
    assert _config("procs=False").procs is False
    monkeypatch.setenv(runner.RUN_PROCS_ENV, "maybe")
    with pytest.raises(ValueError, match="WSB_RUN_PROCS must be 0 or 1"):
        _config()


def test_dry_run_and_layers_each_force_threads(monkeypatch):
    monkeypatch.delenv(runner.RUN_PROCS_ENV, raising=False)
    assert _config("dry_run=True", "procs=True").procs is False
    assert _config("layers=each", "procs=True").procs is False
    assert _config("dry_run=True").procs is False and _config("layers=each").procs is False


@pytest.mark.parametrize("how", ["env0", "procs=False", "dry_run=True", "layers=each"])
def test_thread_mode_spawns_nothing(offline, spawner, rundirs, tmp_path, monkeypatch, how):
    root = tmp_path / "r"
    _spec("a", lambda args: _ok(args, "a"))
    _land(root, "a")
    argv = ["run", "families=a", f"readouts_root={root}", f"out={tmp_path / 'o'}"]
    argv.append("opts=aggregate=native")
    if how == "env0":
        monkeypatch.setenv(runner.RUN_PROCS_ENV, "0")
    else:
        monkeypatch.setenv(runner.RUN_PROCS_ENV, "1")
        argv.append(how)
    assert main(argv) == 0
    assert spawner.order == [] and list(rundirs.iterdir()) == []


def test_caller_env_and_hand_built_namespaces_keep_threads(offline, spawner, rundirs, tmp_path):
    root, out = tmp_path / "r", tmp_path / "o"
    spec = _spec("a", lambda args: _ok(args, "a"))
    _land(root, "a")
    args = _config("opts=aggregate=native", "procs=True")
    outcomes, code = runner.run_families([spec], args, readouts_root=root, out=out, env={})
    assert code == 0 and outcomes[0].status == "ok" and spawner.order == []
    bare = SimpleNamespace(
        judge_model=None,
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        concurrency=4,
        rpm=240.0,
        dry_run=False,
        anti_text_inversion=False,
        opt=["aggregate=native"],
        family_workers=3,
    )  # no `procs` attribute at all
    outcomes, code = runner.run_families([spec], bare, readouts_root=root, out=out)
    assert code == 0 and outcomes[0].status == "ok" and spawner.order == []
    assert list(rundirs.iterdir()) == []


# ---------------------------------------------------------------- judge outcome=


def _judge(tmp_path, name, *extra) -> tuple[int, dict | None]:
    path = _land(tmp_path / "r", name)
    dest = tmp_path / "o" / name
    outcome = dest / "outcome.json"
    argv = ["judge", f"family={name}", f"readouts={path}", f"out={dest}", f"outcome={outcome}"]
    code = main([*argv, *(extra or ["opts=aggregate=native"])])
    assert [p.name for p in dest.glob("*.tmp")] == []  # written atomically
    return code, json.loads(outcome.read_text()) if outcome.exists() else None


def test_judge_outcome_ok(offline, tmp_path, capsys):
    _spec("good", lambda args: _ok(args, "good"))
    code, data = _judge(tmp_path, "good")
    assert code == 0
    assert data == {"family": "good", "status": "ok", "error": None, "exit_code": 0}
    assert (tmp_path / "o" / "good" / "results.json").exists()
    assert "good: pass_rate=0.75" in capsys.readouterr().out


def test_judge_outcome_system_exit_family(offline, tmp_path, capsys):
    def nocells(args):
        raise SystemExit("no cells in scope")

    _spec("empty", nocells)
    code, data = _judge(tmp_path, "empty")
    assert code == 2
    assert data == {
        "family": "empty",
        "status": "failed",
        "error": "no cells in scope",
        "exit_code": 2,
    }
    assert "empty: failed (no cells in scope)" in capsys.readouterr().err


def test_judge_outcome_judge_config_error_family(offline, tmp_path, capsys):
    def nokey(args):
        raise llm.JudgeConfigError("no key for claude")

    _spec("bad", nokey)
    code, data = _judge(tmp_path, "bad")
    assert code == 3
    assert data == {
        "family": "bad",
        "status": "failed",
        "error": "no key for claude",
        "exit_code": 3,
    }
    assert "bad: judge config error: no key for claude" in capsys.readouterr().err


def test_judge_outcome_bad_opts(offline, tmp_path, capsys):
    _spec("good", lambda args: pytest.fail("a bad opts= pair starts no family"))
    code, data = _judge(tmp_path, "good", "opts=novalue")
    assert code == 2 and data is not None
    assert data["status"] == "failed" and data["exit_code"] == 2
    assert data["family"] == "good" and "opts= expects KEY=VALUE pairs" in capsys.readouterr().err


def test_judge_without_outcome_writes_none_and_help_lists_the_key(offline, tmp_path, capsys):
    _spec("good", lambda args: _ok(args, "good"))
    path = _land(tmp_path / "r", "good")
    dest = tmp_path / "o" / "good"
    argv = ["judge", "family=good", f"readouts={path}", f"out={dest}", "opts=aggregate=native"]
    assert main(argv) == 0
    assert sorted(p.name for p in dest.iterdir() if p.name.startswith("outcome")) == []
    capsys.readouterr()
    assert main(["judge", "--help"]) == 0
    assert "outcome=" in capsys.readouterr().out
    assert main([*argv, "outcome=x.json", "layers=each"]) == 2


# ---------------------------------------------------------------- one real subprocess, offline


def test_real_subprocess_smoke_matches_judge(tmp_path, monkeypatch, capfd, rundirs):
    """``run procs=True`` of the regex-scored typo_mt on the example readouts, with no API key
    in the child's environment: exit 0, and ``results.json`` byte-equal to ``judge``'s."""
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.delenv(llm.SLOTS_ENV, raising=False)
    monkeypatch.chdir(REPO)
    src = str(REPO / "src")  # the child imports this checkout, as the test process does
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")]))
    )
    opts = ["opts=aggregate=native", "allow_missing=True"]
    out = tmp_path / "run"
    argv = ["run", "families=typo_mt", "readouts_root=examples/readouts", f"out={out}"]
    assert main([*argv, *opts, "procs=True"]) == 0
    printed = capfd.readouterr()
    assert "typo_mt: pass_rate=0.5 n=85" in printed.out
    assert printed.out.rstrip().splitlines()[-1].startswith("wrote ")
    fam = _manifest(out)["families"]["typo_mt"]
    assert fam["status"] == "ok" and fam["value"] == 0.5
    assert not (out / "typo_mt" / "outcome.json").exists()
    assert list(rundirs.iterdir()) == []

    solo = tmp_path / "judge" / "typo_mt"
    judge = ["judge", "family=typo_mt", "readouts=examples/readouts/typo_mt.jsonl"]
    assert main([*judge, f"out={solo}", *opts]) == 0
    capfd.readouterr()
    a = (out / "typo_mt" / "results.json").read_bytes()
    assert a == (solo / "results.json").read_bytes()


# ---------------------------------------------------------------- the shared pacer


@pytest.fixture
def shared(monkeypatch, tmp_path):
    """``WSB_PACER`` on a fresh directory, a fixed clock, and pacers closed afterwards."""
    d = tmp_path / "pacer"
    monkeypatch.setenv(llm.PACER_ENV, str(d))
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    made: list = []

    def make(kind):
        made.append(kind())
        return made[-1]

    yield d, make
    monkeypatch.delenv(llm.PACER_ENV)
    for p in made:
        p.reset()  # without the variable: closes the descriptor
        assert p._shared is None


def test_two_reservers_on_one_directory_are_spaced_by_the_budget(shared):
    d, make = shared
    a, b = make(llm._Pacer), make(llm._Pacer)
    assert [a.reserve(60), b.reserve(60), a.reserve(60), b.reserve(120)] == [0.0, 1.0, 2.0, 3.0]
    assert a._next == 0.0 and b._next == 0.0  # the slot lives in the file
    ta, tb = make(llm._TokenPacer), make(llm._TokenPacer)
    assert [ta.reserve(10, 600), tb.reserve(10, 600), ta.reserve(10, 600)] == [0.0, 1.0, 2.0]
    assert sorted(p.name for p in d.iterdir()) == ["itpm", "rpm"]  # one file per pacer
    assert a.reserve(60) == 3.5  # rpm and itpm do not share a file


def test_torn_or_empty_pacer_file_reads_as_zero(shared):
    d, make = shared
    d.mkdir()
    (d / "rpm").write_bytes(b"\x01\x02\x03")
    a = make(llm._Pacer)
    assert a.reserve(60) == 0.0 and a.reserve(60) == 1.0
    a.reset()  # truncates the shared file
    assert (d / "rpm").read_bytes() == b""
    assert a.reserve(60) == 0.0
    (d / "rpm").write_bytes(b"\xff" * 8)  # eight bytes that are no time (NaN)
    assert make(llm._Pacer).reserve(60) == 0.0


def test_pace_goes_through_the_shared_file(shared, monkeypatch):
    d, _make = shared
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    monkeypatch.setattr(llm, "_sleep", sleep)
    llm.set_itpm(600)
    try:
        import asyncio

        async def go():
            await llm._pace(60)
            await llm._pace(60)
            await llm._pace_tokens(10)
            await llm._pace_tokens(10)

        asyncio.run(go())
    finally:
        llm.set_itpm(0)
        llm._PACER.reset()
        llm._TOKEN_PACER.reset()
    assert slept == [1.0, 1.0]
    assert sorted(p.name for p in d.iterdir()) == ["itpm", "rpm"]


def test_without_the_variable_the_pacers_are_in_memory(monkeypatch, tmp_path):
    monkeypatch.delenv(llm.PACER_ENV, raising=False)
    monkeypatch.setattr(llm, "_now", lambda: 100.0)
    monkeypatch.chdir(tmp_path)
    a, b = llm._Pacer(), llm._Pacer()
    assert [a.reserve(60), a.reserve(60), b.reserve(60)] == [0.0, 1.0, 0.0]
    assert a._next == 102.0 and a._shared is None
    t = llm._TokenPacer()
    assert [t.reserve(10, 600), t.reserve(10, 600)] == [0.0, 1.0] and t._shared is None
    a.reset()
    assert a._next == 0.0 and [p.name for p in tmp_path.iterdir()] == ["rundirs"]


def test_run_refuses_an_empty_items_list(tmp_path):
    """A child judge would read ``items=`` as "no restriction", so ``run`` refuses it."""
    cfg = cli.RunFamilies()
    cfg.all, cfg.readouts_root, cfg.out, cfg.items = True, str(tmp_path), str(tmp_path / "o"), ","
    with pytest.raises(ValueError, match="items= is empty"):
        cfg.finalize()


def test_a_hangup_the_launcher_ignores_stays_ignored():
    """Under nohup SIGHUP is ignored: the run must not replace that with its own handler."""
    old = signal.signal(signal.SIGHUP, signal.SIG_IGN)
    procs = runner._Procs(SimpleNamespace())
    try:
        assert procs.start() is None
        assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        assert signal.SIGHUP not in procs._handlers and signal.SIGTERM in procs._handlers
        tmp = procs.tmp
    finally:
        procs.close()
        still_ignored = signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
        signal.signal(signal.SIGHUP, old)
    assert still_ignored and tmp is not None and not tmp.exists()
