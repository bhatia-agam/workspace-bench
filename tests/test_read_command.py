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
        (["judge=True", "shards=2", "shard=1"], "whole read in this call"),
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

    monkeypatch.setattr(read, "open_engine", open_engine)
    monkeypatch.setattr(st, "Subject", lambda *a, **k: Subject())
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


def test_the_modal_launcher_maps_one_container_per_gpu(monkeypatch):
    from wsbench.produce import modal_launch

    calls = {"image": [], "ran": []}

    class Image:
        def __getattr__(self, step):
            def record(*args, **kw):
                calls["image"].append((step, args, kw))
                return self

            return record

    class Function:
        def __init__(self, fn, kw):
            self.fn, self.kw = fn, kw

        def map(self, argvs):
            calls["ran"] = list(argvs)
            return [0, 2, 0][: len(calls["ran"])]

    class App:
        def __init__(self, name):
            calls["app"] = name

        def function(self, **kw):
            calls["function"] = kw
            return lambda fn: Function(fn, kw)

        def run(self):
            import contextlib

            return contextlib.nullcontext()

    fake = types.SimpleNamespace(
        Image=types.SimpleNamespace(from_registry=lambda *a, **k: Image()),
        App=App,
        Volume=types.SimpleNamespace(from_name=lambda name, **k: f"volume:{name}"),
        Secret=types.SimpleNamespace(from_name=lambda name: f"secret:{name}"),
    )
    monkeypatch.setitem(sys.modules, "modal", fake)
    code = modal_launch.launch(
        ["families=poetry", "lens=/data/lens", "out=/data/out", "store=/data/store"],
        gpus=3, gpu="B200", volume="my-volume", mount="/data", secret="", app_name="reads",
        timeout=60, sglang="sglang[all]==9.9",
    )  # fmt: skip
    assert code == 2  # the worst container's exit code
    assert calls["ran"][1] == [
        "families=poetry", "lens=/data/lens", "out=/data/out", "store=/data/store",
        "shard=1", "shards=3", "launcher=local",
    ]  # fmt: skip
    assert len(calls["ran"]) == 3 and calls["app"] == "reads"
    assert calls["function"]["gpu"] == "B200" and calls["function"]["secrets"] == []
    assert calls["function"]["volumes"] == {"/data": "volume:my-volume"}
    assert ("pip_install", ("sglang[all]==9.9", *modal_launch.PACKAGES), {}) in calls["image"]


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
    sent = seen["argv"]
    assert "families=poetry,multihop" in sent and "lens=/data/lens" in sent
    assert not any(a.startswith(("modal_", "launcher=", "gpus=", "shard")) for a in sent)


def test_a_folder_that_is_no_bundle_is_a_usage_error(tmp_path, capsys):
    pytest.importorskip("torch")
    argv = ["read", "families=multihop", f"lens={tmp_path}", f"out={tmp_path / 'o'}"]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert capsys.readouterr().err.startswith("read: ")
