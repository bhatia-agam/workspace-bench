"""`wsbench read`: evals read through an engine from the residual store into readouts files the
judge takes, the two-question try-out on top of it, and the Modal launcher's calls (all fakes)."""

import json
import sys
import types

import pytest
from test_residual_store import REV, Subject, Tok, spec

from wsbench import cli, readouts, readplan, reads
from wsbench.produce import read

A = [spec("a1", family="alpha"), spec("a2", family="alpha", ids=(20, 21, 22, 23))]
B = [spec("b1", family="beta", positions=(0,), layers=(7,))]


class Engine:
    """A fake served engine: one readout string per cell, and a count of decode calls."""

    name, sampler = "fake", "hf"

    def __init__(self):
        self.tok = Tok()
        self.calls = []
        self.closed = False

    def decode(self, cells):
        self.calls.append(len(cells))
        return [[f"read {c.id} L{c.layer} p{c.pos} h{int(c.h[1])}"] for c in cells]

    def close(self):
        self.closed = True


def jobs():
    return [read.Job("alpha", list(A), "sha-alpha"), read.Job("beta", list(B), "sha-beta")]


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


@pytest.fixture
def env(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from wsbench.produce import store as st

    where = st.Store(tmp_path / "store", REV, "fp32")
    for family, specs in (("alpha", A), ("beta", B)):
        st.cells_for(where, family, specs, Tok(), backend=Subject())
    return st, where, tmp_path / "out"


def run(where, out, engine, **kw):
    kw = {"reader": "toy-lens", "sampling": "prose1", **kw}
    return read.read_evals(jobs(), engine, where, Tok(), out, **kw)


def test_stored_evals_are_read_with_no_subject_and_small_evals_share_one_decode(env):
    _, where, out = env
    engine = Engine()
    done = run(where, out, engine)  # no subject model at all
    assert engine.calls == [9]  # alpha's 8 cells and beta's 1 in one pack
    assert [(d["family"], d["status"], d["cells"], d["from_store"]) for d in done] == [
        ("alpha", "read", 8, 8),
        ("beta", "read", 1, 1),
    ]
    rows = lines(out / "alpha.jsonl")
    assert rows[0] == {
        "id": "a1",
        "layer": 2,
        "pos": 1,
        "token": " t11",
        "samples": ["read a1 L2 p1 h11"],
    }
    assert lines(out / "beta.jsonl") == [
        {"id": "b1", "layer": 7, "pos": 0, "token": " t10", "samples": ["read b1 L7 p0 h10"]}
    ]
    side = readouts.read_sidecar(out / "alpha.jsonl")
    assert side == {
        "reads": "full",
        "sampling": "prose1",
        "reader": "toy-lens",
        "arm": "toy-lens",
        "layers": [2, 5],
        "plan_sha": "sha-alpha",
    }
    # the judge's loader takes the file as it is
    cells, _ = readouts.load_readouts(out / "alpha.jsonl")
    assert len(cells) == 8


def test_a_second_call_reads_nothing(env):
    _, where, out = env
    run(where, out, Engine())
    engine = Engine()
    done = run(where, out, engine)
    assert engine.calls == [] and {d["status"] for d in done} == {"exists"}


def test_packs_hold_at_most_pack_cells_and_a_large_eval_gets_its_own(env):
    _, where, out = env
    engine = Engine()
    run(where, out, engine, pack_cells=8)
    assert engine.calls == [8, 1]


def test_missing_cells_are_captured_before_the_engine_decodes(env, tmp_path):
    st, _, out = env
    subject = Subject()
    subject.release = lambda: setattr(subject, "released", True)
    engine = Engine()
    done = run(st.Store(tmp_path / "empty", REV, "fp32"), out, engine, subject=subject)
    assert subject.forwards == 3 and subject.released and engine.calls == [9]
    assert [d["captured"] for d in done] == [8, 1]
    with pytest.raises(st.StoreError, match="not in the residual store"):
        run(st.Store(tmp_path / "empty2", REV, "fp32"), tmp_path / "o2", Engine())


def test_several_processes_write_parts_and_the_last_one_joins_them(env):
    _, where, out = env
    run(where, out, Engine(), shard=0, shards=2)
    # nothing is complete until every process has written its part, even an empty one
    assert not (out / "alpha.jsonl").exists() and not (out / "beta.jsonl").exists()
    assert (out / "parts" / "beta.0of2.jsonl").exists()
    run(where, out, Engine(), shard=1, shards=2)
    assert len(lines(out / "beta.jsonl")) == 1
    assert [r["id"] for r in lines(out / "alpha.jsonl")] == ["a1"] * 4 + ["a2"] * 4
    assert readouts.read_sidecar(out / "alpha.jsonl")["plan_sha"] == "sha-alpha"


def test_a_plan_file_is_read_under_its_own_hash_and_line_separators_are_escaped(env, tmp_path):
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(s.row()) for s in [*A, *B]) + "\n")
    got = read.plan_file_jobs(plan)
    assert [j.family for j in got] == ["alpha", "beta"]
    assert got[0].plan_sha == reads.plan_sha_rows(s.row() for s in A)
    cell = types.SimpleNamespace(id="a", layer=1, pos=2, token="t")
    separator = chr(0x2028)
    text = read.row(cell, [f"one{separator}two"])
    assert separator not in text and json.loads(text)["samples"] == [f"one{separator}two"]


# ---------------------------------------------------------------- the command


def test_read_keys_exist_and_an_unknown_key_is_refused(capsys):
    documented = {
        "lens", "out", "engine", "families", "plan", "fast", "store", "dataset",
        "dataset_revision", "revision", "dtype", "pack_cells", "greedy", "sampler",
        "server_args", "in_flight", "work", "judge", "judged", "limit", "shard", "shards",
        "check", "launcher", "gpus", "modal_gpu", "modal_volume", "modal_mount",
        "modal_secret", "modal_app", "modal_timeout", "modal_sglang",
    }  # fmt: skip
    assert documented <= set(cli.Read().to_dict())
    base = ["read", "lens=l", "out=o", "families=multihop"]
    assert cli.main([*base, "no_such_key=1"]) == cli.EXIT_USAGE
    assert "no_such_key" in capsys.readouterr().err
    for argv, message in [
        (["sampler=fancy"], "sampler is hf or native"),
        (["launcher=slurm"], "launcher is local or modal"),
        (["launcher=modal"], "needs modal_volume"),
        (["launcher=modal", "modal_volume=v", "shards=2"], "sets shard= and shards= itself"),
        (["launcher=modal", "modal_volume=v", "judge=True"], "fetch them"),
        (["judge=True", "shards=2", "shard=1"], "needs every eval's whole file"),
        (["join=True", "check=True"], "join=True only joins parts"),
        (["pack_cells=0"], "pack_cells must be >= 1"),
    ]:
        assert cli.main([*base, *argv]) == cli.EXIT_USAGE
        assert message in capsys.readouterr().err
    assert cli.main(["read", "lens=l", "out=o", "plan=p.jsonl", "judge=True"]) == cli.EXIT_USAGE
    assert "has no judge here" in capsys.readouterr().err


@pytest.fixture
def served(env, monkeypatch):
    """The command with a fake bundle and engine in place of the served package."""
    st, where, out = env
    engine = Engine()
    seen = {}

    def open_engine(name, lens, **options):
        seen.update(name=name, lens=lens, **options)
        bundle = types.SimpleNamespace(name="toy-lens", model_revision=REV, sampling_kind="prose1")
        return bundle, engine

    def subject(*args, **kw):
        made = Subject()
        made.tokenizer = engine.tok  # the subject and the bundle share one tokenizer
        return made

    def capture_process(argv):
        seen.setdefault("captures", []).append(list(argv))
        return cli.main(["capture", *argv])

    monkeypatch.setattr(read, "open_engine", open_engine)
    monkeypatch.setattr(read, "load_bundle", lambda lens: open_engine("sglang", lens)[0])
    monkeypatch.setattr(st, "Subject", subject)
    monkeypatch.setattr(cli, "_capture_process", capture_process)
    return where, out, engine, seen


def test_the_command_reads_a_plan_file_end_to_end(served, tmp_path, capsys):
    where, out, engine, seen = served
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(s.row()) for s in [*A, *B]) + "\n")
    argv = [
        "read", f"plan={plan}", "lens=bundles/toy", f"out={out}", f"store={where.root}",
        "model=m", f"revision={REV}", "dataset=none",
    ]  # fmt: skip
    assert cli.main([*argv, "greedy=True", "server_args=--max-running-requests 8"]) == 0
    text = capsys.readouterr().out
    assert "alpha: 8 cells = 8 from the store + 0 pulled from the dataset + 0 captured" in text
    assert f"readouts -> {out}/<eval>.jsonl (2 read, 0 already there)" in text
    assert seen["name"] == "sglang" and seen["greedy"] is True and seen["sampler"] == "hf"
    assert seen["server_args"] == ["--max-running-requests", "8"] and "work" not in seen
    assert engine.closed and len(lines(out / "alpha.jsonl")) == 8
    assert cli.main([*argv, "check=True"]) == 0
    assert "alpha: 8 cells in the plan = 8 in the store" in capsys.readouterr().out
    # a lens made for another model revision is refused before anything is read
    assert cli.main([*argv[:-3], "model=m", "revision=" + "f" * 20, "dataset=none"]) == 2
    assert "the lens was made for model revision" in capsys.readouterr().err


def test_the_two_question_try_out_runs_on_what_the_command_produced(
    served, tmp_path, monkeypatch, capsys, real_families
):
    """`wsbench read families=multihop limit=2` with the fake engine, then `wsbench try` on its
    file: plan -> read -> judge (dry run, no key) -> report, on the benchmark's own eval."""
    from wsbench.adapt import template

    where, out, engine, _ = served
    monkeypatch.setattr(template, "bos_prefix", lambda tok: [])
    engine.tok = Words()
    argv = [
        "read", "families=multihop", "limit=2", "lens=bundles/toy", f"out={out}",
        f"store={where.root}", "dataset=none",
    ]  # fmt: skip
    monkeypatch.setattr(cli, "_subject_revision", lambda model, revision, need=True: REV)
    assert cli.main(argv) == 0
    text = capsys.readouterr().out
    assert "multihop:" in text and "captured (2 forward passes)" in text
    side = readouts.read_sidecar(out / "multihop.jsonl")
    assert side["plan_sha"] == reads.plan_sha("multihop") and side["sampling"] == "prose1"
    ids = sorted(s.id for s in readplan.plan("multihop"))[:2]
    assert {r["id"] for r in lines(out / "multihop.jsonl")} == set(ids)
    tried = [
        "try", "family=multihop", f"readouts={out / 'multihop.jsonl'}", "dry_run=True",
        f"out={tmp_path / 'try'}",
    ]  # fmt: skip
    assert cli.main(tried) == 0
    shown = capsys.readouterr().out
    assert "== wsbench try: multihop, 2 item(s)" in shown and "== judge (dry run" in shown
    assert (tmp_path / "try" / "plan" / "multihop.jsonl").exists()


class Words:
    """A toy tokenizer for plain renders: one id per whitespace-separated word."""

    def __init__(self):
        self.vocab = {}

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [self.vocab.setdefault(w, len(self.vocab) + 1) for w in text.split()]}

    def _word(self, i):
        return next(w for w, n in self.vocab.items() if n == i)

    def convert_ids_to_tokens(self, ids):
        return ["Ġ" + self._word(i) for i in ids]

    def decode(self, ids):
        return " " + self._word(ids[0])


# ---------------------------------------------------------------- the Modal launcher


def fake_modal(monkeypatch, codes):
    """A stand-in `modal`: records the image steps, the function settings and every call."""
    import contextlib

    calls = {"image": [], "functions": [], "ran": []}

    class Image:
        def __getattr__(self, step):
            def record(*args, **kw):
                calls["image"].append((step, args, kw))
                return self

            return record

    class Function:
        def __init__(self, kw):
            self.kw = kw

        def _run(self, args):
            calls["ran"].append(("gpu" if "gpu" in self.kw else "cpu", list(args)))
            return codes(args)

        def remote(self, args):
            return self._run(args)

        def map(self, argvs):
            return [self._run(a) for a in argvs]

    class App:
        def __init__(self, name):
            calls["app"] = name

        def function(self, **kw):
            calls["functions"].append(kw)
            return lambda fn: Function(kw)

        def run(self):
            return contextlib.nullcontext()

    class Volume:
        def __init__(self, name, read_only=False):
            self.name, self.ro = name, read_only

        def read_only(self):
            return Volume(self.name, True)

        def __eq__(self, other):
            return (self.name, self.ro) == (other.name, other.ro)

        __hash__ = None

    @contextlib.contextmanager
    def enable_output():
        calls["output"] = "on"
        yield

    fake = types.SimpleNamespace(
        enable_output=enable_output,
        Image=types.SimpleNamespace(from_registry=lambda *a, **k: Image()),
        App=App,
        Volume=types.SimpleNamespace(from_name=lambda name, **k: Volume(name)),
        Secret=types.SimpleNamespace(from_name=lambda name: f"secret:{name}"),
    )
    monkeypatch.setitem(sys.modules, "modal", fake)
    return calls, Volume


LAUNCH = {
    "gpus": 3, "gpu": "B200", "volume": "my-volume", "mount": "/data", "secret": "",
    "app_name": "reads", "timeout": 60, "sglang": "sglang[all]==9.9",
}  # fmt: skip
ARGV = ["families=poetry", "lens=/lens/toy", "out=/data/out", "store=/data/store"]


def test_the_launcher_captures_once_reads_per_gpu_then_joins(monkeypatch):
    from wsbench.produce import modal_launch

    calls, volume = fake_modal(monkeypatch, lambda args: 0)
    code = modal_launch.launch(
        ARGV, capture_argv=["families=poetry", "store=/data/store"], **LAUNCH,
        model_volume="weights", lens_volume="bundles",
    )  # fmt: skip
    assert code == 0
    ran = calls["ran"]
    assert ran[0] == ("gpu", ["capture", "families=poetry", "store=/data/store"])  # one model load
    assert ran[2] == (
        "gpu",
        ["read", *ARGV, "shard=1", "shards=3", "launcher=local", "capture=False"],
    )
    assert ran[-1] == ("cpu", ["read", *ARGV, "shards=3", "join=True", "launcher=local"])
    assert [kind for kind, _ in ran] == ["gpu", "gpu", "gpu", "gpu", "cpu"] and calls[
        "app"
    ] == "reads"
    gpu_fn, cpu_fn = calls["functions"]
    assert gpu_fn["gpu"] == "B200" and "gpu" not in cpu_fn and gpu_fn["secrets"] == []
    assert gpu_fn["volumes"] == {
        "/data": volume("my-volume"),
        "/model": volume("weights", True),
        "/lens": volume("bundles", True),
    }
    assert ("pip_install", ("sglang[all]==9.9", *modal_launch.PACKAGES), {}) in calls["image"]
    assert "accelerate" in modal_launch.PACKAGES  # a capture loads the model with device_map=
    assert calls["output"] == "on"  # the containers' lines are shown where the command runs


def test_the_launcher_stops_at_the_first_failing_step(monkeypatch):
    from wsbench.produce import modal_launch

    calls, _ = fake_modal(monkeypatch, lambda args: 3 if args[0] == "capture" else 0)
    assert modal_launch.launch(ARGV, capture_argv=["families=poetry"], **LAUNCH) == 3
    assert [a[0] for _, a in calls["ran"]] == ["capture"]  # no read after a failed capture
    calls, _ = fake_modal(monkeypatch, lambda args: 2 if "shard=1" in args else 0)
    assert modal_launch.launch(ARGV, capture_argv=None, **LAUNCH) == 2  # the worst shard
    assert all("join=True" not in a for _, a in calls["ran"]) and len(calls["ran"]) == 3
    # no capture step asked (the baseline): the shards, then the join
    calls, _ = fake_modal(monkeypatch, lambda args: 1 if "join=True" in args else 0)
    assert modal_launch.launch(ARGV, capture_argv=None, **LAUNCH) == 1
    assert [kind for kind, _ in calls["ran"]] == ["gpu", "gpu", "gpu", "cpu"]


def test_the_command_hands_its_keys_to_the_launcher(monkeypatch):
    from wsbench.produce import modal_launch

    seen = {}
    monkeypatch.setattr(
        modal_launch, "launch", lambda argv, **kw: seen.update(argv=argv, **kw) or 0
    )
    argv = [
        "read", "families=poetry,multihop", "lens=/data/lens", "out=/data/out",
        "store=/data/store", "launcher=modal", "gpus=4", "modal_volume=vol", "modal_gpu=H200",
        "modal_secret=hf", "modal_app=mine", "modal_timeout=120", "modal_mount=/mnt",
        "modal_sglang=sglang[all]==1.2",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    assert (seen["gpus"], seen["gpu"], seen["volume"], seen["mount"]) == (4, "H200", "vol", "/mnt")
    assert (seen["secret"], seen["app_name"], seen["timeout"]) == ("hf", "mine", 120)
    assert seen["sglang"] == "sglang[all]==1.2"
    assert seen["capture_argv"] == ["families=poetry,multihop", "store=/data/store", *DEFAULTS]
    assert (seen["model_volume"], seen["model_mount"]) == ("", "/model")
    assert (seen["lens_volume"], seen["lens_mount"]) == ("", "/lens")
    sent = seen["argv"]
    assert "families=poetry,multihop" in sent and "lens=/data/lens" in sent
    assert not any(a.startswith(("modal_", "launcher=", "gpus=", "shard", "join=")) for a in sent)
    assert not any(a.startswith(("capture=", "in_flight_total=", "judge")) for a in sent)


def test_a_baseline_on_modal_asks_for_no_capture_step(monkeypatch):
    from wsbench.produce import modal_launch

    seen = {}
    monkeypatch.setattr(modal_launch, "launch", lambda argv, **kw: seen.update(kw) or 0)
    argv = [
        "read", "method=model_continuation", "model_dir=/model/qwen", "families=poetry",
        "out=/data/out", "launcher=modal", "modal_volume=vol", "modal_model_volume=weights",
    ]  # fmt: skip
    assert cli.main(argv) == 0
    assert seen["capture_argv"] is None and seen["model_volume"] == "weights"


def test_a_folder_that_is_no_bundle_is_a_usage_error(tmp_path, capsys):
    pytest.importorskip("torch")
    argv = ["read", "families=multihop", f"lens={tmp_path}", f"out={tmp_path / 'o'}"]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert capsys.readouterr().err.startswith("read: ")


# ---------------------------------------------------------------- capture, join, timing

DEFAULTS = [  # the capture keys a read hands on besides its evals and store
    "model=Qwen/Qwen3.6-27B",
    "revision=6a9e13bd6fc8f0983b9b99948120bc37f49c13e9",
    "dtype=fp32",
    "device=cuda",
    "reads=full",
    "dataset=agu18dec/workspacebench_residuals",
]


def plan_argv(tmp_path, where, out, specs):
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(s.row()) for s in specs) + "\n")
    return [
        "read", f"plan={plan}", "lens=bundles/toy", f"out={out}", f"store={where.root}",
        "model=m", f"revision={REV}", "dataset=none",
    ]  # fmt: skip


def test_missing_cells_are_captured_by_a_child_process_before_the_read(served, tmp_path, capsys):
    where, out, engine, seen = served
    new = spec("n1", family="gamma", ids=(30, 31, 32, 33))
    argv = plan_argv(tmp_path, where, out, [*A, new])
    assert cli.main(argv) == 0
    text = capsys.readouterr().out
    assert "1 item(s) need the subject model: wsbench capture, in its own process" in text
    (child,) = seen["captures"]  # one capture process, with the read's evals, store and subject
    assert f"store={where.root}" in child and f"revision={REV}" in child and "shard=0" not in child
    assert "gamma: 4 cells = 0 from the store + 0 pulled from the dataset + 4 captured" in text
    # the read itself then finds everything in the store
    assert "gamma: 4 cells = 4 from the store" in text and engine.calls == [12]
    # nothing missing: no child process at all
    assert cli.main(plan_argv(tmp_path, where, tmp_path / "again", [*A, new])) == 0
    assert len(seen["captures"]) == 1


def test_with_capture_off_a_missing_cell_is_an_error_and_nothing_is_read(served, tmp_path, capsys):
    where, out, engine, seen = served
    argv = plan_argv(tmp_path, where, out, [*A, spec("n1", family="gamma")])
    assert cli.main([*argv, "capture=False"]) == cli.EXIT_USAGE
    assert "not in the residual store" in capsys.readouterr().err
    assert "captures" not in seen and engine.calls == [] and engine.closed


def test_a_failed_capture_step_stops_the_read(served, tmp_path, monkeypatch, capsys):
    where, out, engine, _ = served
    monkeypatch.setattr(cli, "_capture_process", lambda argv: 7)
    argv = plan_argv(tmp_path, where, out, [spec("n1", family="gamma")])
    assert cli.main(argv) == 7 and engine.calls == []
    assert "the capture step failed (exit 7)" in capsys.readouterr().err


def test_the_read_prints_and_saves_timing_and_token_counts(served, tmp_path, capsys):
    where, out, engine, _ = served
    engine.tokens = [[1, 2, 3]] * 9  # what the engine keeps: one token list per readout row
    assert cli.main(plan_argv(tmp_path, where, out, [*A, *B])) == 0
    text = capsys.readouterr().out
    assert "alpha: 8 cells read, 24 tokens," in text and "beta: 1 cells read, 3 tokens," in text
    assert "read 9 cells, 27 readout tokens in 1 pack(s):" in text
    saved = json.loads((out / "read_stats.json").read_text())
    assert saved["total"]["cells"] == 9 and saved["total"]["tokens"] == 27
    assert saved["total"]["packs"] == 1 and saved["total"]["forward_passes"] == 0
    assert [(d["family"], d["cells"], d["tokens"]) for d in saved["evals"]] == [
        ("alpha", 8, 24),
        ("beta", 1, 3),
    ]


def test_join_writes_the_files_that_separate_containers_could_not(served, tmp_path, capsys):
    where, out, _, _ = served
    argv = plan_argv(tmp_path, where, out, [*A, *B])
    # two containers that never see each other's parts: each reads its shard into its own
    # copy of the folder, and the parts are brought together afterwards (a volume does this)
    for i in (0, 1):
        own = tmp_path / f"container{i}"
        mine = [a.replace(f"out={out}", f"out={own}") for a in argv]
        assert cli.main([*mine, "shards=2", f"shard={i}"]) == 0
        assert not (own / "alpha.jsonl").exists()
        (out / "parts").mkdir(parents=True, exist_ok=True)
        for part in (own / "parts").glob("*.jsonl"):
            (out / "parts" / part.name).write_bytes(part.read_bytes())
    capsys.readouterr()
    assert not list(out.glob("*.jsonl"))  # 4 parts, no eval file, no sidecar
    assert cli.main([*argv, "shards=2", "join=True"]) == 0
    text = capsys.readouterr().out
    assert "alpha: 8 rows joined from 2 parts" in text and "(2 of 2 evals joined)" in text
    assert [r["id"] for r in lines(out / "alpha.jsonl")] == ["a1"] * 4 + ["a2"] * 4
    assert readouts.read_sidecar(out / "beta.jsonl")["reader"] == "toy-lens"
    # a part that never arrived: the eval is named, nothing is written for it, exit 1
    (out / "parts" / "alpha.1of2.jsonl").unlink()
    (out / "alpha.jsonl").unlink()
    assert cli.main([*argv, "shards=2", "join=True"]) == 1
    assert "alpha: not joined, missing alpha.1of2.jsonl" in capsys.readouterr().out
    assert not (out / "alpha.jsonl").exists()


def test_join_then_judge_hands_run_the_folder_and_the_budget(served, monkeypatch):
    where, out, _, _ = served
    seen = {}
    monkeypatch.setattr(cli, "_run_command", lambda kind, args: seen.update(args=args) or 0)
    monkeypatch.setattr(cli.Read, "plans", lambda self: {"alpha": list(A)})
    monkeypatch.setattr(read, "job", lambda f, specs, **kw: read.Job(f, list(specs), "sha"))
    base = [
        "read", "families=alpha", "lens=bundles/toy", f"out={out}", f"store={where.root}",
        "dataset=none", "shards=2",
    ]  # fmt: skip
    monkeypatch.setattr(cli, "_subject_revision", lambda model, revision, need=True: REV)
    for i in (0, 1):
        assert cli.main([*base, f"shard={i}"]) == 0
    assert cli.main([*base, "join=True", "judge=True", "in_flight_total=352"]) == 0
    assert f"readouts_root={out}" in seen["args"] and "in_flight_total=352" in seen["args"]
    assert "families=alpha" in seen["args"]


# ---------------------------------------------------------------- totals after the join


def test_the_join_sums_the_shards_timing_into_one_file_and_one_line(served, tmp_path, capsys):
    where, out, engine, _ = served
    engine.tokens = [[1, 2, 3]] * 9
    extra = {"bank_seconds": 1.0, "server_start_seconds": 10.0, "request_seconds": 4.0}
    engine.stats = types.SimpleNamespace(as_dict=lambda: {"rows": 9, "seconds": 15.0, **extra})
    argv = plan_argv(tmp_path, where, out, [*A, *B])
    for i in (0, 1):
        assert cli.main([*argv, "shards=2", f"shard={i}"]) == 0
    part = json.loads((out / "parts" / "read_stats.0of2.json").read_text())
    assert part["total"]["engine"] == extra  # what the engine knows of its own time
    capsys.readouterr()
    assert cli.main([*argv, "shards=2", "join=True"]) == 0
    text = capsys.readouterr().out
    assert "read 9 cells, " in text and "over 2 of 2 shard(s):" in text and "GPU time" in text
    assert "(bank 2.0 s, server start 20.0 s, request 8.0 s)" in text
    assert "shard 0of2:" in text and "shard 1of2:" in text
    saved = json.loads((out / "read_stats.json").read_text())
    total = saved["total"]
    assert (total["cells"], total["shards"], total["packs"]) == (9, 2, 2)
    assert total["server_start_seconds"] == 20.0 and total["request_seconds"] == 8.0
    assert total["gpu_seconds"] == round(sum(s["wall_seconds"] for s in saved["shards"]), 1)
    assert total["wall_seconds"] == max(s["wall_seconds"] for s in saved["shards"])
    assert {(e["family"], e["cells"]) for e in saved["evals"]} == {("alpha", 8), ("beta", 1)}


def test_sum_stats_adds_totals_and_keeps_each_shard():
    def one(cells, wall, family):
        row = {"family": family, "status": "read", "cells": cells, "tokens": cells * 2}
        total = {"cells": cells, "tokens": cells * 2, "packs": 1, "decode_seconds": wall - 1}
        total |= {"wall_seconds": wall, "forward_passes": 0, "evals_read": 1}
        total["engine"] = {"server_start_seconds": 3.0, "request_seconds": wall - 5}
        return {"total": total, "evals": [row, {"family": "x", "status": "exists"}]}

    got = read.sum_stats([one(10, 11.0, "a"), one(30, 21.0, "a")])
    total = got["total"]
    assert (total["cells"], total["tokens"], total["packs"], total["shards"]) == (40, 80, 2, 2)
    assert total["decode_seconds"] == 30.0 and total["cells_per_second"] == round(40 / 30, 1)
    assert total["gpu_seconds"] == 32.0 and total["wall_seconds"] == 21.0
    assert total["server_start_seconds"] == 6.0 and total["request_seconds"] == 22.0
    assert "bank_seconds" not in total and total["evals_read"] == 1
    (row,) = got["evals"]
    assert (row["family"], row["cells"], row["tokens"], row["forward_passes"]) == ("a", 40, 80, 0)
    assert len(got["shards"]) == 2
