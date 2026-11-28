"""Plan 0072 Phase 0.3: the fail-closed ``plan_sha`` lineage of an adapted set. ``adapt freeze``
records a re-freeze that only DROPS items (every kept plan row unchanged, no id added); guard
(iii) of ``reads.load`` then accepts a readout of the older plan through that chain, with the
dropped items' cells removed. Everything else refuses as before."""

import copy
import json
import os

import pytest

from wsbench import readplan, reads, registry
from wsbench.adapt import run, store
from wsbench.judge_config import JudgeConfig, resolve
from wsbench.readouts import write_sidecar
from wsbench.registry import JudgeArgs

MODEL = "qwen3.5-4b"
FAM = "association"


@pytest.fixture
def mdir(tmp_path, monkeypatch, real_families):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    for k in list(os.environ):
        if k.startswith(registry.BANK_FILE_ENV_PREFIX):
            monkeypatch.delenv(k)
    monkeypatch.delenv(registry.BANK_ROOT_ENV, raising=False)
    return tmp_path / MODEL


def _row(item, ok=True):
    leg = {"greedy": {"text": "x", "ok": ok}, "samples": [], "rate": 1.0 if ok else 0.0}
    return {"id": store.item_id(item), "origin": "original", "item": copy.deepcopy(item),
            "gate": {"pass": ok, "rate": 1.0 if ok else 0.0, "legs": {"surface": leg}},
            "selected": ok}  # fmt: skip


def _gate(d, rows):
    (d / "gate").mkdir(parents=True, exist_ok=True)
    with (d / "gate" / f"{FAM}.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _items():
    return store.original_bank(FAM)[1]


def _freeze():
    run.freeze(MODEL, [FAM])
    reads._specs.cache_clear()  # same process: the judge's plan cache keys on env, not files


def _readouts(d, monkeypatch, tmp_path, name="r"):
    """A full readout file of the set's CURRENT plan, with that plan's sha in its sidecar."""
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(d))
    reads._specs.cache_clear()
    path = tmp_path / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for s in readplan.plan(FAM, layers=None):
            for layer in s.layers:
                for pos in range(100, 119):  # 19 contiguous positions
                    fh.write(json.dumps({"id": s.id, "layer": layer, "pos": pos,
                                         "samples": ["- x"]}) + "\n")  # fmt: skip
    write_sidecar(path, sampling="prose1", plan_sha=reads.plan_sha(FAM))
    return path


def _args(path, tmp_path):
    return JudgeArgs(
        readouts=path, out=tmp_path / "o", judge=resolve(JudgeConfig(prompt_version="t")),
        layers=None, items=None, limit=0, allow_missing=True, concurrency=1, rpm=1.0,
        dry_run=True,
    )  # fmt: skip


def _lineage(d):
    rep = json.loads((d / "report.json").read_text())
    return rep["families"][FAM].get(reads.LINEAGE_KEY) or []


def _load(path, tmp_path, monkeypatch, d):
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(d))
    reads._specs.cache_clear()
    return reads.load(_args(path, tmp_path), FAM)


def test_drop_only_refreeze_loads_kept_items_only(mdir, tmp_path, monkeypatch):
    items = _items()[:6]
    _gate(mdir, [_row(it) for it in items])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    _gate(mdir, [_row(items[5], ok=False)])  # the gate fails one item: a drop
    _freeze()
    (step,) = _lineage(mdir)
    assert step["dropped"] == [store.item_id(items[5])] and step["from"] != step["to"]
    cells, rep = _load(path, tmp_path, monkeypatch, mdir)
    assert {c.id for c in cells} == {store.item_id(it) for it in items[:5]}
    assert rep.plan_lineage["n_dropped_items"] == 1 and rep.plan_lineage["n_dropped_cells"] > 0
    assert reads.config_stamps(_args(path, tmp_path))  # no crash without a remembered report


def test_without_the_root_the_same_file_refuses(mdir, tmp_path, monkeypatch):
    items = _items()[:6]
    _gate(mdir, [_row(it) for it in items])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    _gate(mdir, [_row(items[5], ok=False)])
    _freeze()
    assert _lineage(mdir)
    reads._specs.cache_clear()
    with pytest.raises(SystemExit) as e:
        reads.load(_args(path, tmp_path), FAM)  # registered plan, no lineage to walk
    assert e.value.code == 2


def test_an_added_item_records_nothing_and_refuses(mdir, tmp_path, monkeypatch):
    items = _items()[:7]
    _gate(mdir, [_row(it) for it in items[:6]])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    _gate(mdir, [_row(items[6])])  # one more passing original: an added id
    _freeze()
    assert _lineage(mdir) == []
    with pytest.raises(SystemExit) as e:
        _load(path, tmp_path, monkeypatch, mdir)
    assert e.value.code == 2


def test_drop_plus_add_records_nothing(mdir, tmp_path, monkeypatch):
    items = _items()[:7]
    _gate(mdir, [_row(it) for it in items[:6]])
    _freeze()
    _gate(mdir, [_row(items[0], ok=False), _row(items[6])])
    _freeze()
    assert _lineage(mdir) == []


def test_a_changed_kept_row_records_nothing_and_refuses(mdir, tmp_path, monkeypatch):
    items = _items()[:6]
    _gate(mdir, [_row(it) for it in items])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    iid = store.item_id(items[0])
    store.update_report(MODEL, lambda r: r.setdefault("patches", {}).setdefault(FAM, {}).update(
        {iid: {"set": {"prompt": items[0]["prompt"] + " Changed."}, "note": "t"}}))  # fmt: skip
    _gate(mdir, [_row(items[5], ok=False)])  # a drop AND a changed render
    _freeze()
    assert _lineage(mdir) == []
    with pytest.raises(SystemExit):
        _load(path, tmp_path, monkeypatch, mdir)


def test_mc_only_refreeze_keeps_the_sha(mdir, tmp_path, monkeypatch):
    items = _items()[:6]
    _gate(mdir, [_row(it) for it in items])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    iid = store.item_id(items[0])
    mc = copy.deepcopy(items[0]["mc"])
    mc["distractors"] = list(reversed(mc["distractors"]))
    store.update_report(MODEL, lambda r: r.setdefault("patches", {}).setdefault(FAM, {}).update(
        {iid: {"set": {"mc": mc}, "note": "t"}}))  # fmt: skip
    _freeze()
    assert _lineage(mdir) == []  # options are not in the plan: equal sha, nothing to record
    cells, rep = _load(path, tmp_path, monkeypatch, mdir)
    assert rep.plan_lineage is None and len({c.id for c in cells}) == 6


def test_two_drop_steps_chain_with_the_union_removed(mdir, tmp_path, monkeypatch):
    items = _items()[:6]
    _gate(mdir, [_row(it) for it in items])
    _freeze()
    path = _readouts(mdir, monkeypatch, tmp_path)
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    _gate(mdir, [_row(items[5], ok=False)])
    _freeze()
    _gate(mdir, [_row(items[4], ok=False)])
    _freeze()
    assert len(_lineage(mdir)) == 2
    cells, rep = _load(path, tmp_path, monkeypatch, mdir)
    assert {c.id for c in cells} == {store.item_id(it) for it in items[:4]}
    assert rep.plan_lineage["n_dropped_items"] == 2


def test_lineage_step_rules():
    a = [{"id": "x", "family": FAM, "render": "r1"}, {"id": "y", "family": FAM, "render": "r2"}]
    assert reads.lineage_step(a, a) is None  # equal sha
    step = reads.lineage_step(a, a[:1])
    assert step["dropped"] == ["y"] and step["to"] == reads.plan_sha_rows(a[:1])
    assert reads.lineage_step(a, [{**a[0], "render": "r9"}]) is None  # a changed kept row
    assert reads.lineage_step(a, [a[0], {"id": "z", "family": FAM}]) is None  # an added id
    assert reads.lineage_step([*a, a[0]], a[:1]) is None  # a repeated id
    # the excluded keys (layers, note) may move without voiding the record
    assert reads.lineage_step(a, [{**a[0], "layers": [3], "note": "n"}])["dropped"] == ["y"]


def test_lineage_walk_is_bounded_and_needs_a_root(tmp_path, monkeypatch):
    rep = {"families": {FAM: {reads.LINEAGE_KEY: [
        {"from": "a", "to": "b", "dropped": ["1"]}, {"from": "b", "to": "a", "dropped": []},
        {"from": "b", "to": "c", "dropped": ["2"]}]}}}  # fmt: skip
    (tmp_path / "report.json").write_text(json.dumps(rep))
    monkeypatch.delenv(registry.BANK_ROOT_ENV, raising=False)
    assert reads.lineage_drops(FAM, "a", "c") is None  # no root
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert reads.lineage_drops(FAM, "a", "c") == ["1", "2"]
    assert reads.lineage_drops(FAM, "a", "z") is None  # the cycle a<->b terminates
    assert reads.lineage_drops(FAM, "c", "a") is None  # never backwards
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + FAM.upper(), str(tmp_path / "x.json"))
    assert reads.lineage_drops(FAM, "a", "c") is None  # a bank-file pin overrides the set


# ---------------------------------------------------------------- registered lineage (plan 0083)

ARITH = "arithmetic_intermediates"
ARITH_V1_SHA = "ad92c18203e8c526ef3a4e02d80fc0a17063ee1d1a5cd3584d6992b198b8e715"


def _arith_readouts(tmp_path, ids, sha):
    path = tmp_path / "arith.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i in ids:
            for layer in readplan.GRID:
                for pos in range(-42, 0):
                    fh.write(json.dumps({"id": i, "layer": layer, "pos": pos,
                                         "samples": ["- x"]}) + "\n")  # fmt: skip
    write_sidecar(path, sampling="prose1", plan_sha=sha)
    return path


@pytest.fixture
def noroot(monkeypatch, real_families):
    for k in list(os.environ):
        if k.startswith(registry.BANK_FILE_ENV_PREFIX):
            monkeypatch.delenv(k)
    monkeypatch.delenv(registry.BANK_ROOT_ENV, raising=False)
    reads._specs.cache_clear()
    yield
    reads._specs.cache_clear()


def test_registered_header_records_the_frac_drop(noroot):
    """The registered arithmetic bank v2 carries its v1 -> v2 drop-only step (plan 0083)."""
    raw = json.loads(registry.bank_path(ARITH).read_text(encoding="utf-8"))
    (step,) = raw["plan_lineage"]
    assert step["from"] == ARITH_V1_SHA and step["to"] == reads.plan_sha(ARITH)
    assert len(step["dropped"]) == 116 and all(i.startswith("frac-") for i in step["dropped"])


def test_v1_readouts_load_on_v2_without_frac_cells(noroot, tmp_path):
    path = _arith_readouts(tmp_path, ["absval-052", "frac-000"], ARITH_V1_SHA)
    cells, rep = reads.load(_args(path, tmp_path), ARITH)
    assert {c.id for c in cells} == {"absval-052"}
    assert rep.plan_lineage["from"] == ARITH_V1_SHA and rep.plan_lineage["n_dropped_items"] == 116
    assert rep.plan_lineage["n_dropped_cells"] > 0


def test_unknown_sha_still_refuses_without_root(noroot, tmp_path):
    path = _arith_readouts(tmp_path, ["absval-052"], "0" * 64)
    with pytest.raises(SystemExit) as e:
        reads.load(_args(path, tmp_path), ARITH)
    assert e.value.code == 2


def test_bank_file_pin_still_refuses_the_registered_lineage(noroot, tmp_path, monkeypatch):
    path = _arith_readouts(tmp_path, ["absval-052"], ARITH_V1_SHA)
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + ARITH.upper(),
                       str(registry.bank_path(ARITH)))  # fmt: skip
    reads._specs.cache_clear()
    with pytest.raises(SystemExit) as e:
        reads.load(_args(path, tmp_path), ARITH)
    assert e.value.code == 2


def test_a_root_never_reads_the_registered_header(noroot, tmp_path, monkeypatch):
    """Under WSB_BANK_ROOT only the set's report.json counts (a root with no report refuses)."""
    want = reads.plan_sha(ARITH)
    assert len(reads.lineage_drops(ARITH, ARITH_V1_SHA, want) or []) == 116
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path / "no-such-set"))
    assert reads.lineage_drops(ARITH, ARITH_V1_SHA, want) is None
