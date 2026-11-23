"""`wsbench produce family=` reads its activations from the residual store: zero forward passes
when the store holds the plan, a pull before any forward pass, and the same rows either way."""

import json

import pytest
from test_residual_dataset import publish, residuals
from test_residual_store import REV, Subject, Tok, spec

from wsbench import cli, readplan, reads
from wsbench.produce import Producer
from wsbench.produce.methods import Readout

SPECS = [spec("a"), spec("b", ids=(20, 21, 22, 23)), spec("c", positions=(0, 4))]


class TopToken:
    """A token method: reads the cell's vector back as its "tokens", so rows show the vector."""

    name = "logit_lens"
    layers = None

    def bind(self, backend):
        pass

    def read(self, h, layer):
        return Readout(tokens=[f"L{layer}", f"tok{int(h[1])}"], scores=[float(h[0]), 0.0])


@pytest.fixture
def env(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from wsbench.produce import store as st

    monkeypatch.setattr(readplan, "plan", lambda family, **kw: list(SPECS))
    monkeypatch.setattr(reads, "plan_sha", lambda family: "sha-of-the-toy-plan")
    return st, st.Store(tmp_path / "store", REV, "fp32"), tmp_path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_stored_plan_is_read_with_zero_forward_passes_and_gives_the_same_rows(env):
    _, where, tmp = env
    plain = Subject()
    Producer(backend=plain, method=TopToken()).run_family("toy", tmp / "plain.jsonl")
    assert plain.forwards == 3  # no store: one forward pass per item

    first = Subject()
    p = Producer(backend=first, method=TopToken(), store=where)
    p.run_family("toy", tmp / "first.jsonl")
    assert first.forwards == 3 and (p.counts.captured, p.counts.store) == (12, 0)

    again = Subject()
    p = Producer(backend=again, method=TopToken(), store=where)
    p.run_family("toy", tmp / "again.jsonl")
    assert again.forwards == 0
    assert (p.counts.store, p.counts.pulled, p.counts.captured, p.counts.forwards) == (12, 0, 0, 0)
    assert rows(tmp / "again.jsonl") == rows(tmp / "first.jsonl") == rows(tmp / "plain.jsonl")
    assert rows(tmp / "again.jsonl")[3] == {
        "id": "a",
        "layer": 5,
        "pos": 3,
        "token": " t13",
        "tokens": ["L5", "tok13"],
        "scores": [5.0, 0.0],
    }
    sidecar = json.loads((tmp / "again.jsonl.meta.json").read_text())
    assert sidecar["sampling"] == "tokens10" and sidecar["plan_sha"] == "sha-of-the-toy-plan"


def test_the_dataset_is_asked_before_the_subject_runs(env):
    st, where, tmp = env
    pull = residuals(tmp / "ds", {"full/toy": publish(st, tmp / "ds", "full/toy", SPECS[:2])})
    subject = Subject()
    p = Producer(backend=subject, method=TopToken(), store=where, pull=pull)
    p.run_family("toy", tmp / "out.jsonl")
    assert subject.forwards == 1  # only c, which the dataset does not hold
    assert (p.counts.store, p.counts.pulled, p.counts.captured) == (0, 8, 4)
    assert "8 pulled from the dataset + 4 captured (1 forward passes)" in p.counts.line("toy")


def test_a_cell_stored_for_another_plan_is_refused_and_read_again(env):
    st, where, tmp = env
    old = [spec("a", positions=(0, 2)), *SPECS[1:]]  # a was stored at other positions
    st.cells_for(where, "toy", old, Tok(), backend=Subject())
    subject = Subject()
    p = Producer(backend=subject, method=TopToken(), store=where)
    p.run_family("toy", tmp / "out.jsonl")
    assert (p.counts.refused, p.counts.store, p.counts.captured, subject.forwards) == (1, 8, 4, 1)
    assert [(r["id"], r["pos"]) for r in rows(tmp / "out.jsonl")[:2]] == [("a", 1), ("a", 3)]


def test_a_resumed_file_reads_only_the_items_it_lacks(env):
    _, where, tmp = env
    out = tmp / "out.jsonl"
    out.write_text(json.dumps({"id": "a", "layer": 2, "pos": 1, "tokens": ["x"]}) + "\n")
    subject = Subject()
    p = Producer(backend=subject, method=TopToken(), store=where)
    p.run_family("toy", out)
    assert subject.forwards == 2 and {r["id"] for r in rows(out)[1:]} == {"b", "c"}


def test_chunks_cover_every_item_in_plan_order(env):
    _, where, tmp = env
    subject = Subject()
    p = Producer(backend=subject, method=TopToken(), store=where)
    with (tmp / "out.jsonl").open("w") as fh:
        p._run_from_store("toy", list(SPECS), fh, chunk=2)
    got = rows(tmp / "out.jsonl")
    assert [r["id"] for r in got] == ["a"] * 4 + ["b"] * 4 + ["c"] * 4
    assert p.counts.captured == 12 and subject.forwards == 3


# ---------------------------------------------------------------- the command


def test_produce_keys_exist_and_an_unknown_key_is_refused(capsys):
    documented = {"store", "dataset", "dataset_revision", "revision", "dtype"}
    assert documented <= set(cli.Produce().to_dict())
    assert cli.main(["produce", "family=multihop", "no_such_key=1"]) == cli.EXIT_USAGE
    assert "no_such_key" in capsys.readouterr().err
    assert cli.main(["produce", "family=multihop", "dtype=fp16"]) == cli.EXIT_USAGE
    assert cli.main(["produce", "family=multihop", "model=other/model"]) == cli.EXIT_USAGE
    assert "revision=<sha> is required" in capsys.readouterr().err
    # without a store no revision is needed: the old forward-pass path
    assert (
        cli.main(["produce", "family=multihop", "model=other/model", "store=none", "--show"]) == 0
    )


def test_produce_reads_the_store_by_default_and_store_none_turns_it_off(env, monkeypatch, capsys):
    _, where, tmp = env
    seen = {}

    def load(model, method, **kw):
        seen.update(kw)
        return Producer(backend=Subject(), method=TopToken(), store=kw["store"], pull=kw["pull"])

    monkeypatch.setattr(Producer, "load", staticmethod(load))
    monkeypatch.setattr(readplan, "families", lambda: ["toy"])
    argv = ["produce", "family=toy", f"out={tmp / 'o.jsonl'}", "dataset=none"]
    assert cli.main([*argv, f"store={where.root}"]) == 0
    out = capsys.readouterr().out
    assert "toy: 12 cells = 0 from the store + 0 pulled from the dataset + 12 captured" in out
    assert seen["store"].root == where.root and seen["dtype"] == "float32"
    assert len(seen["revision"]) == 40  # the default model's pinned revision
    (tmp / "o.jsonl").unlink()
    assert cli.main([*argv, f"store={where.root}", "dtype=bf16"]) == 0
    assert seen["dtype"] == "bfloat16" and seen["store"].dtype == "bf16"
    (tmp / "o.jsonl").unlink()
    capsys.readouterr()
    assert cli.main([*argv, "store=none"]) == 0
    assert seen["store"] is None and seen["dtype"] == "bfloat16"
    assert "from the store" not in capsys.readouterr().out
