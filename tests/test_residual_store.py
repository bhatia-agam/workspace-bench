"""The residual store: stored cells are read without the subject model, a cell that is not the
plan's is refused, and `wsbench capture` takes its documented keys (fakes, CPU)."""

import json
import subprocess
import sys

import pytest

from wsbench import cli
from wsbench.readplan import ReadSpec

REV = "0123456789abcdef0123"


def spec(item, ids=(10, 11, 12, 13, 14), positions=(1, 3), layers=(2, 5), family="toy"):
    return ReadSpec(
        family=family,
        id=item,
        render="captured",
        positions={"kind": "positions", "positions": list(positions)},
        layers=list(layers),
        extra={"input_ids": list(ids)},
        lite_positions={"kind": "same"},
    )


class Tok:
    def convert_ids_to_tokens(self, ids):
        return [f"Ġt{i}" for i in ids]

    def decode(self, ids):
        return f" t{ids[0]}"


class Subject:
    """A fake subject model that counts its forward passes; h = [layer, token id, 0, 0]."""

    def __init__(self):
        self.tokenizer = Tok()
        self.forwards = 0

    def capture(self, ids, layers, positions):
        import torch

        self.forwards += 1
        return {
            la: torch.tensor([[float(la), float(ids[p]), 0.0, 0.0] for p in positions])
            for la in layers
        }


@pytest.fixture
def store(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from wsbench.produce import store as st

    return st, st.Store(tmp_path / "store", REV, "fp32")


def test_a_full_store_is_read_with_zero_forward_passes(store):
    st, where = store
    specs = [spec("a"), spec("b", ids=(20, 21, 22, 23))]
    first = Subject()
    cells, counts = st.cells_for(where, "toy", specs, first.tokenizer, backend=first)
    assert (counts.captured, counts.store, counts.forwards, first.forwards) == (8, 0, 2, 2)
    again = Subject()
    cells2, counts2 = st.cells_for(where, "toy", specs, again.tokenizer, backend=again)
    assert again.forwards == 0 and counts2.forwards == 0
    assert (counts2.store, counts2.pulled, counts2.captured) == (8, 0, 0)
    assert [(c.id, c.layer, c.pos, c.token) for c in cells2] == [
        (c.id, c.layer, c.pos, c.token) for c in cells
    ]
    # plan order: items as given, layers outermost, then positions; the vector is the cell's own
    assert [(c.id, c.layer, c.pos) for c in cells2[:4]] == [
        ("a", 2, 1),
        ("a", 2, 3),
        ("a", 5, 1),
        ("a", 5, 3),
    ]
    assert cells2[3].h.tolist() == [5.0, 13.0, 0.0, 0.0] and cells2[3].token == " t13"
    # and with no subject at all: the store alone serves the plan
    cells3, _ = st.cells_for(where, "toy", specs, Tok())
    assert len(cells3) == 8


def test_only_the_missing_items_are_captured(store):
    st, where = store
    subject = Subject()
    st.cells_for(where, "toy", [spec("a")], subject.tokenizer, backend=subject)
    both = [spec("a"), spec("b")]
    _, counts = st.cells_for(where, "toy", both, subject.tokenizer, backend=subject)
    assert (counts.store, counts.captured, counts.forwards, subject.forwards) == (4, 4, 1, 2)
    assert "4 from the store" in counts.line("toy") and "4 captured" in counts.line("toy")


def test_a_missing_item_is_pulled_before_the_subject_runs(store):
    st, where = store
    subject = Subject()
    asked = []

    def pull(family, missing):
        asked.append((family, [at.spec.id for at in missing]))
        return st.capture([at for at in missing if at.spec.id == "b"], Subject())

    specs = [spec("a"), spec("b"), spec("c")]
    st.cells_for(where, "toy", [spec("a")], subject.tokenizer, backend=subject)
    _, counts = st.cells_for(where, "toy", specs, subject.tokenizer, pull=pull, backend=subject)
    assert asked == [("toy", ["b", "c"])]
    assert (counts.store, counts.pulled, counts.captured) == (4, 4, 4)
    assert subject.forwards == 2  # a (before) and c; b came from the dataset
    # the pulled item is in the store now: nothing is asked for again
    _, counts = st.cells_for(where, "toy", specs, Tok())
    assert (counts.store, counts.pulled, counts.captured) == (12, 0, 0)


def test_a_pulled_item_with_another_key_is_not_used(store):
    st, where = store

    def pull(family, missing):  # the dataset holds the item, but captured at other positions
        return st.capture([st.locate(spec("a", positions=(0, 2)), Tok())], Subject())

    with pytest.raises(st.StoreError, match="not in the residual store"):
        st.cells_for(where, "toy", [spec("a")], Tok(), pull=pull)


@pytest.mark.parametrize(
    "changed",
    [
        {"positions": (1, 4)},  # another position
        {"layers": (2, 6)},  # another layer
        {"ids": (10, 11, 12, 99, 14)},  # another prompt
    ],
)
def test_a_cell_stored_for_another_plan_is_refused_never_read(store, changed):
    st, where = store
    subject = Subject()
    st.cells_for(where, "toy", [spec("a")], subject.tokenizer, backend=subject)
    with pytest.raises(st.StoreError, match="not in the residual store"):
        st.cells_for(where, "toy", [spec("a", **changed)], Tok())  # no subject: an error
    cells, counts = st.cells_for(
        where, "toy", [spec("a", **changed)], subject.tokenizer, backend=subject
    )
    assert counts.refused == 1 and counts.store == 0 and counts.captured == 4
    assert "refused" in counts.line("toy")
    want = st.locate(spec("a", **changed), Tok())
    assert [(c.layer, c.pos, c.token) for c in cells] == want.rows


def test_another_revision_or_dtype_is_another_store(store, tmp_path):
    st, where = store
    subject = Subject()
    st.cells_for(where, "toy", [spec("a")], subject.tokenizer, backend=subject)
    for other in (
        st.Store(where.root, "f" * 20, "fp32"),
        st.Store(where.root, REV, "bf16"),
    ):
        with pytest.raises(st.StoreError, match="not in the residual store"):
            st.cells_for(other, "toy", [spec("a")], Tok())
    # a pack moved by hand into another store's folder is an error, not a read
    src, dst = where.folder("toy"), st.Store(where.root, REV, "bf16").folder("toy")
    dst.mkdir(parents=True)
    for f in src.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    with pytest.raises(st.StoreError, match="written for revision"):
        st.cells_for(st.Store(where.root, REV, "bf16"), "toy", [spec("a")], Tok())
    with pytest.raises(ValueError, match="revision sha"):
        st.Store(tmp_path, "main")
    with pytest.raises(ValueError, match="dtype"):
        st.Store(tmp_path, REV, "fp16")


def test_the_key_covers_ids_positions_layers_and_steering(store):
    st, _ = store
    base = st.locate(spec("a"), Tok())
    assert base.key == st.locate(spec("a"), Tok()).key
    assert base.key == st.locate(spec("renamed"), Tok()).key  # the id is the lookup, not the key
    steered = spec("a")
    steered.extra["steering"] = {"type": "concept", "beta": 2.0}
    others = [
        spec("a", positions=(1, 4)),
        spec("a", layers=(2,)),
        spec("a", ids=(1, 2, 3, 4)),
        steered,
    ]
    assert len({base.key, *(st.locate(s, Tok()).key for s in others)}) == 5


def test_plan_file_rows_and_shards(tmp_path):
    from wsbench.produce import store as st

    rows = [spec(x).row() for x in "dcba"] + [spec("z", family="other").row()]
    path = tmp_path / "plan.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    plans = st.read_plan_file(path)
    assert sorted(plans) == ["other", "toy"] and [s.id for s in plans["toy"]] == list("dcba")
    assert plans["toy"][0] == spec("d")
    assert [s.id for s in st.shard(plans["toy"])] == list("abcd")
    assert [s.id for s in st.shard(plans["toy"], 1, 2)] == ["b", "d"]
    with pytest.raises(ValueError, match="shard 2 of 2"):
        st.shard(plans["toy"], 2, 2)
    path.write_text(json.dumps({"id": "a", "layers": [1], "bogus": 1}) + "\n")
    with pytest.raises(ValueError, match="not a plan row"):
        st.read_plan_file(path)
    path.write_text("\n".join(json.dumps(spec("a").row()) for _ in range(2)))
    with pytest.raises(ValueError, match="twice"):
        st.read_plan_file(path)


# ---------------------------------------------------------------- the command


def test_capture_keys_exist_and_an_unknown_key_is_refused(capsys):
    documented = {
        "families", "plan", "store", "model", "revision", "dtype", "device", "reads", "fast",
        "limit", "shard", "shards",
    }  # fmt: skip
    assert documented <= set(cli.Capture().to_dict())
    assert cli.main(["capture", "families=multihop", "no_such_key=1"]) == cli.EXIT_USAGE
    assert "no_such_key" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv, message",
    [
        ([], "give families="),
        (["families=multihop", "plan=p.jsonl"], "plan= replaces"),
        (["families=multihop", "dtype=fp16"], "dtype is fp32 or bf16"),
        (["families=multihop", "model=some/model"], "revision=<sha> is required"),
        (["families=multihop", "shard=2", "shards=2"], "shard=2 is not one of"),
        (["--fast", "reads=lite"], "drop reads=lite"),
    ],
)
def test_capture_usage_errors(argv, message, capsys):
    assert cli.main(["capture", *argv]) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err


def test_capture_defaults_resolve(capsys):
    assert cli.main(["capture", "families=multihop", "--show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["dtype"] == "fp32" and shown["store"] == "outputs/store"
    assert len(shown["revision"]) == 40  # the default model's pinned revision


def test_capture_from_a_plan_file_fills_the_store_once(store, tmp_path, monkeypatch, capsys):
    st, where = store
    subject = Subject()
    monkeypatch.setattr(st, "Subject", lambda *a, **k: subject)
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(spec(x).row()) for x in "abc") + "\n")
    argv = ["capture", f"plan={plan}", f"store={where.root}", "model=m", f"revision={REV}"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "toy: 12 cells = 0 from the store + 0 pulled from the dataset + 12 captured" in out
    assert cli.main(argv) == 0
    assert "toy: 12 cells = 12 from the store" in capsys.readouterr().out
    assert subject.forwards == 3
    assert cli.main([*argv, "shards=2", "shard=1", "limit=1"]) == 0
    assert "toy: 4 cells = 4 from the store" in capsys.readouterr().out
    assert cli.main(["capture", "plan=nowhere.jsonl", f"revision={REV}", "model=m"]) == 2


def test_the_judge_path_imports_no_gpu_or_serving_package():
    code = (
        "import sys, wsbench.cli, wsbench.runner, wsbench.reads\n"
        "bad = sorted(m for m in ('torch', 'safetensors', 'transformers', 'sglang', 'modal',"
        " 'wsbench.produce.store') if m in sys.modules)\n"
        "print(bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
