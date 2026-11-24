"""A readout method written outside the package: `wsbench produce method=package.module:ClassName`
loads it, and its `sampling_kind` is what the readouts sidecar declares. The bundled methods keep
their names and their sampling kinds."""

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from wsbench import cli, readplan, reads
from wsbench.produce import METHODS, Producer, method
from wsbench.produce.methods import NLA, JLens, LogitLens, OLens, RLens, load, sampling_of
from wsbench.readouts import read_sidecar

MODULE = '''
from wsbench.produce.methods import Readout


class Sentences:
    """A method that writes sentences and says so."""

    name = "sentences"
    layers = None
    sampling_kind = "prose1"

    def __init__(self, prefix="seen"):
        self.prefix = prefix

    def bind(self, backend):
        pass

    def read(self, h, layer):
        return Readout(samples=[f"{self.prefix} at {layer}"])


class Undeclared(Sentences):
    name = "undeclared"
    sampling_kind = None


class Wrong(Sentences):
    sampling_kind = "prose"


NOT_A_CLASS = 3
'''


@pytest.fixture
def mine(tmp_path, monkeypatch):
    """An importable module `my_lens_methods` outside the package."""
    (tmp_path / "my_lens_methods.py").write_text(MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "my_lens_methods"


def test_an_import_path_gives_an_instance_of_that_class(mine):
    m = method(f"{mine}:Sentences", prefix="read")
    assert type(m).__name__ == "Sentences" and m.prefix == "read"
    assert m.read(None, 36).samples == ["read at 36"]
    assert f"{mine}:Sentences" not in METHODS  # the bundled table is not written to


def test_a_method_declares_its_own_sampling_kind(mine):
    assert sampling_of(method(f"{mine}:Sentences")) == "prose1"
    # without the attribute the label is what it was before: the token label
    assert sampling_of(method(f"{mine}:Undeclared")) == "tokens10"
    with pytest.raises(ValueError, match="sampling_kind is one of"):
        sampling_of(method(f"{mine}:Wrong"))


def test_the_bundled_methods_keep_their_names_and_sampling_kinds():
    assert sorted(METHODS) == ["jlens", "logit_lens", "nla", "olens", "rlens"]
    assert [type(method(n)) for n in ("logit_lens", "jlens", "rlens", "olens", "nla")] == [
        LogitLens,
        JLens,
        RLens,
        OLens,
        NLA,
    ]
    kinds = {n: sampling_of(method(n)) for n in METHODS}
    assert kinds == {
        "logit_lens": "tokens10",
        "jlens": "tokens10",
        "rlens": "tokens10",
        "olens": "prose1",
        "nla": "prose1",
    }
    assert sampling_of(OLens(bullet=True)) == "bullet4"


def test_an_unknown_bundled_name_fails_as_before():
    with pytest.raises(KeyError, match=r"unknown method 'nope'; known \["):
        method("nope")


@pytest.mark.parametrize(
    ("spec", "why"),
    [
        ("no_such_module_anywhere:Lens", "cannot import it"),
        ("my_lens_methods:Missing", "cannot import it"),
        ("my_lens_methods:NOT_A_CLASS", "is not a class"),
        ("my_lens_methods:", "expected package.module:ClassName"),
        (":Sentences", "expected package.module:ClassName"),
    ],
)
def test_a_path_that_does_not_resolve_says_why(mine, spec, why):
    with pytest.raises(KeyError, match=why):
        load(spec)


def test_the_sidecar_declares_the_methods_own_kind(mine, tmp_path, monkeypatch):
    monkeypatch.setattr(readplan, "plan", lambda family, **kw: [])
    monkeypatch.setattr(reads, "plan_sha", lambda family: "sha-of-the-toy-plan")
    out = tmp_path / "toy.jsonl"
    Producer(backend=SimpleNamespace(), method=method(f"{mine}:Sentences")).run_family("toy", out)
    meta = read_sidecar(out)
    assert (meta["sampling"], meta["reader"], meta["arm"]) == ("prose1", "sentences", "sentences")


class FakeProducer:
    """Stands in for the model load of `wsbench produce`; records what it was asked for."""

    counts = None
    calls: ClassVar[list] = []

    def __init__(self, spec):
        self.method = method(spec)

    @classmethod
    def load(cls, model, spec, **kw):
        cls.calls.append(("load", spec))
        return cls(spec)

    def run_family(self, family, out, **kw):
        self.calls.append(("run_family", family, str(out)))
        return out


@pytest.fixture
def produce(monkeypatch):
    import wsbench.produce as produce_pkg

    FakeProducer.calls = []
    monkeypatch.setattr(produce_pkg, "Producer", FakeProducer)
    return FakeProducer.calls


def test_produce_takes_an_import_path(mine, produce, capsys):
    spec = f"{mine}:Sentences"
    assert cli.main(["produce", "family=poetry", f"method={spec}", "store=none"]) == 0
    assert produce == [
        ("load", spec),
        ("run_family", "poetry", "outputs/readouts/sentences/poetry.jsonl"),
    ]


def test_produce_with_a_bundled_name_writes_where_it_did(produce):
    assert cli.main(["produce", "family=poetry", "method=logit_lens", "store=none"]) == 0
    assert produce[-1] == ("run_family", "poetry", "outputs/readouts/logit_lens/poetry.jsonl")


def test_produce_refuses_a_path_it_cannot_import_before_any_model_load(produce, capsys):
    argv = ["produce", "family=poetry", "method=no_such_module_anywhere:Lens", "store=none"]
    assert cli.main(argv) == cli.EXIT_USAGE
    assert "cannot import it" in capsys.readouterr().err and produce == []


def test_produce_refuses_an_unknown_name_as_before(produce, capsys):
    assert cli.main(["produce", "family=poetry", "method=nope", "store=none"]) == cli.EXIT_USAGE
    assert "unknown method 'nope'; known [" in capsys.readouterr().err and produce == []


def test_show_prints_the_path_unchanged(capsys):
    assert cli.main(["produce", "family=poetry", "method=my.pkg:Lens", "--show"]) == 0
    assert json.loads(capsys.readouterr().out)["method"] == "my.pkg:Lens"
