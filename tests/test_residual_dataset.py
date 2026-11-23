"""The published residuals as the store's `pull`: an item in the dataset is pulled, not
captured; an item recorded under another key is not taken; the shipped map is well formed."""

import importlib.util
import json

import pytest
from test_residual_store import REV, Subject, Tok, spec

from wsbench import cli, registry, tiers
from wsbench.produce import dataset as ds


@pytest.fixture
def env(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from wsbench.produce import store as st

    return st, st.Store(tmp_path / "store", REV, "fp32"), tmp_path / "dataset"


def publish(st, root, folder, specs, *, subdir="float32-capture", part_rows=120_000, keys=None):
    """A fake dataset folder holding ``specs``, and the map entry that describes it."""
    located = [st.locate(s, Tok()) for s in specs]
    items = st.capture(located, Subject())
    ds.write_folder(root / subdir / folder if subdir else root / folder, items, part_rows)
    return {"items": keys or {i.id: i.key for i in items}}


def mapping(folders, *, dtype="fp32", subdir="float32-capture", revision=REV):
    capture = {"subdir": subdir, "model_revision": revision, "folders": folders}
    return {"repo": "someone/residuals", "revision": "abc", "captures": {dtype: capture}}


def residuals(root, folders, **kw):
    return ds.Residuals("fp32", REV, ds.local_fetch(root), mapping(folders, **kw))


def test_an_item_in_the_dataset_is_pulled_not_captured(env):
    st, where, root = env
    specs = [spec("a"), spec("b"), spec("c")]
    pull = residuals(root, {"full/toy": publish(st, root, "full/toy", specs[:2])})
    subject = Subject()
    cells, counts = st.cells_for(where, "toy", specs, subject.tokenizer, pull=pull, backend=subject)
    assert (counts.store, counts.pulled, counts.captured) == (0, 8, 4)
    assert subject.forwards == 1  # only c, which the dataset does not hold
    assert cells[3].h.tolist() == [5.0, 13.0, 0.0, 0.0] and cells[3].token == " t13"
    assert pull.downloaded == [
        "float32-capture/full/toy/index.json",
        "float32-capture/full/toy/part-000.safetensors",
    ]
    # pulled items are in the store now: the next read touches neither dataset nor subject
    pull.downloaded.clear()
    again = Subject()
    _, counts = st.cells_for(where, "toy", specs, again.tokenizer, pull=pull, backend=again)
    assert (counts.store, counts.pulled, counts.captured) == (12, 0, 0)
    assert again.forwards == 0 and pull.downloaded == []


def test_a_fully_published_plan_needs_no_subject(env):
    st, where, root = env
    specs = [spec("a"), spec("b")]
    pull = residuals(root, {"full/toy": publish(st, root, "full/toy", specs)})
    cells, counts = st.cells_for(where, "toy", specs, Tok(), pull=pull)  # no backend at all
    assert counts.pulled == 8 and len(cells) == 8


def test_an_item_recorded_under_another_key_is_not_taken(env):
    st, where, root = env
    published = [spec("a", positions=(0, 2)), spec("b")]  # a was captured at other positions
    pull = residuals(root, {"full/toy": publish(st, root, "full/toy", published)})
    subject = Subject()
    specs = [spec("a"), spec("b")]
    _, counts = st.cells_for(where, "toy", specs, subject.tokenizer, pull=pull, backend=subject)
    assert (counts.pulled, counts.captured, subject.forwards) == (4, 4, 1)
    with pytest.raises(st.StoreError, match="nor in the dataset"):
        st.cells_for(st.Store(where.root, "f" * 20), "toy", [spec("a")], Tok(), pull=pull)


def test_a_map_that_does_not_describe_the_folder_takes_nothing(env):
    st, _, root = env
    # the map claims today's key for an item the folder holds at other positions
    entry = publish(st, root, "full/toy", [spec("a", positions=(0, 2))])
    entry["items"]["a"] = st.locate(spec("a"), Tok()).key
    pull = residuals(root, {"full/toy": entry})
    assert pull("toy", [st.locate(spec("a"), Tok())]) == []
    assert pull.downloaded == ["float32-capture/full/toy/index.json"]  # no vector file


def test_another_model_revision_or_dtype_pulls_nothing(env):
    st, _, root = env
    folders = {"full/toy": publish(st, root, "full/toy", [spec("a")])}
    at = [st.locate(spec("a"), Tok())]
    for pull in (
        ds.Residuals("fp32", "f" * 20, ds.local_fetch(root), mapping(folders)),
        ds.Residuals("bf16", REV, ds.local_fetch(root), mapping(folders)),
    ):
        assert pull.capture is None and pull("toy", at) == [] and pull.downloaded == []


def test_items_are_found_by_id_and_key_whatever_the_folder_is_called(env):
    st, where, root = env
    # the 16-bit capture sits in the dataset root, under the names evals had when it was made
    folders = {
        "full/toy_old_name": publish(st, root, "full/toy_old_name", [spec("a")], subdir=""),
        "fast/toy": publish(st, root, "fast/toy", [spec("b")], subdir=""),
    }
    pull = ds.Residuals(
        "bf16", REV, ds.local_fetch(root), mapping(folders, dtype="bf16", subdir="")
    )
    specs = [spec("a"), spec("b")]
    _, counts = st.cells_for(st.Store(where.root, REV, "bf16"), "toy", specs, Tok(), pull=pull)
    assert counts.pulled == 8
    assert sorted(pull.downloaded) == [
        "fast/toy/index.json",
        "fast/toy/part-000.safetensors",
        "full/toy_old_name/index.json",
        "full/toy_old_name/part-000.safetensors",
    ]


def test_only_the_part_files_that_hold_wanted_rows_are_downloaded(env):
    st, _, root = env
    specs = [spec(x) for x in "abcd"]  # 4 rows each, 3 rows per part: 6 parts
    pull = residuals(root, {"full/toy": publish(st, root, "full/toy", specs, part_rows=3)})
    (item,) = pull("toy", [st.locate(spec("c"), Tok())])  # rows 8..11: parts 2 and 3
    assert [f.rsplit("/", 1)[1] for f in pull.downloaded] == [
        "index.json",
        "part-002.safetensors",
        "part-003.safetensors",
    ]
    assert item.rows == st.locate(spec("c"), Tok()).rows
    assert item.acts.tolist() == [
        [2.0, 11.0, 0, 0],
        [2.0, 13.0, 0, 0],
        [5.0, 11.0, 0, 0],
        [5.0, 13.0, 0, 0],
    ]


def test_the_map_script_and_the_store_compute_the_same_key(env):
    st, _, _ = env
    path = registry.REPO_ROOT / "scripts/residuals_map.py"
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("m", path))
    module.__spec__.loader.exec_module(module)
    for s in (spec("a"), spec("b", positions=(0,), layers=(7,))):
        at = st.locate(s, Tok())
        assert module.item_key(at.ids, at.positions, list(s.layers), None) == at.key
    steered = spec("a")
    steered.extra["steering"] = {"type": "concept", "beta": 2.0}
    at = st.locate(steered, Tok())
    assert module.item_key(at.ids, at.positions, [2, 5], steered.extra["steering"]) == at.key


def test_the_shipped_map_covers_the_core_set():
    m = ds.load_map()
    assert m["repo"] == ds.REPO and len(m["revision"]) == 40
    fp32, bf16 = m["captures"]["fp32"], m["captures"]["bf16"]
    assert fp32["subdir"] == "float32-capture" and bf16["subdir"] == ""
    assert fp32["model_revision"] == bf16["model_revision"]
    for capture in (fp32, bf16):
        for folder, info in capture["folders"].items():
            assert folder.split("/")[0] in ("full", "fast")
            assert all(len(key) == 24 for key in info["items"].values()), folder
    # the float32 capture holds a folder for every eval of the core set, by today's name
    assert {f"full/{name}" for name in tiers.core()} <= set(fp32["folders"])


def test_source_reads_the_dataset_key(env, tmp_path):
    assert ds.source("none", "", "fp32", REV) is None and ds.source("", "", "fp32", REV) is None
    local = ds.source(str(tmp_path), "", "fp32", REV)
    assert local.fetch("a/b") == tmp_path / "a/b"
    assert ds.source("someone/residuals", "", "fp32", REV).dtype == "fp32"


def test_capture_pulls_by_default_and_check_downloads_nothing(env, tmp_path, monkeypatch, capsys):
    st, where, root = env
    specs = [spec(x) for x in "abc"]
    folders = {"full/toy": publish(st, root, "full/toy", specs[:2])}
    monkeypatch.setattr(ds, "load_map", lambda: mapping(folders))
    subject = Subject()
    monkeypatch.setattr(st, "Subject", lambda *a, **k: subject)
    plan = tmp_path / "plan.jsonl"
    plan.write_text("\n".join(json.dumps(s.row()) for s in specs) + "\n")
    argv = ["capture", f"plan={plan}", f"store={where.root}", "model=m", f"revision={REV}"]
    assert cli.main([*argv, f"dataset={root}", "check=True"]) == 0
    line = "toy: 12 cells in the plan = 0 in the store + 8 in the dataset + 4 in neither"
    assert line in capsys.readouterr().out
    assert subject.forwards == 0 and not (where.root / REV[:12]).exists()
    assert cli.main([*argv, f"dataset={root}"]) == 0
    assert "8 pulled from the dataset + 4 captured (1 forward passes)" in capsys.readouterr().out
    assert cli.main([*argv, "dataset=none", "check=True"]) == 0
    assert "= 12 in the store + 0 in the dataset + 0 in neither" in capsys.readouterr().out
    assert {"dataset", "dataset_revision", "check"} <= set(cli.Capture().to_dict())


def test_an_eval_whose_bank_ships_no_prompts_is_skipped_by_name(env, tmp_path, monkeypatch, capsys):
    st, where, _ = env
    monkeypatch.setattr(st, "Subject", lambda *a, **k: Subject())
    bare = spec("a")
    del bare.extra["input_ids"]
    with pytest.raises(st.NoPromptError, match="without a prompt"):
        st.locate(bare, Tok())
    plan = tmp_path / "plan.jsonl"
    plan.write_text(json.dumps(bare.row()) + "\n" + json.dumps(spec("b", family="ok").row()))
    argv = ["capture", f"plan={plan}", f"store={where.root}", "model=m", f"revision={REV}"]
    assert cli.main([*argv, "dataset=none", "check=True"]) == 0
    out = capsys.readouterr().out
    assert "toy: skipped, nothing to capture" in out and "ok: 4 cells in the plan" in out


def test_check_fetches_no_dataset_file(env, tmp_path, monkeypatch, capsys):
    st, where, root = env
    folders = {"full/toy": publish(st, root, "full/toy", [spec("a")])}
    monkeypatch.setattr(ds, "load_map", lambda: mapping(folders))

    def no_fetch(*args, **kw):
        def fetch(path):
            raise AssertionError(f"check=True fetched {path}")

        return fetch

    monkeypatch.setattr(ds, "hub_fetch", no_fetch)
    monkeypatch.setattr(st, "Subject", lambda *a, **k: Subject())
    plan = tmp_path / "plan.jsonl"
    plan.write_text(json.dumps(spec("a").row()) + "\n")
    argv = ["capture", f"plan={plan}", f"store={where.root}", "model=m", f"revision={REV}"]
    assert cli.main([*argv, "dataset=someone/residuals", "check=True"]) == 0
    assert "4 in the dataset + 0 in neither" in capsys.readouterr().out


def test_splice_replaces_and_adds_folders_and_leaves_the_rest(tmp_path):
    path = registry.REPO_ROOT / "scripts/residuals_map.py"
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("m", path))
    module.__spec__.loader.exec_module(module)
    old = mapping({"full/a": {"items": {"x": "1" * 24}}, "fast/a": {"items": {"y": "2" * 24}}})
    old["captures"]["bf16"] = {"subdir": "", "model_revision": REV, "folders": {"full/a": {}}}
    map_path, part_path = tmp_path / "map.json", tmp_path / "part.json"
    map_path.write_text(json.dumps(old))
    part = {
        "capture": "fp32",
        "model_revision": REV,
        "bench_commit": "c0ffee",
        "folders": {"full/a": {"items": {"z": "3" * 24}}, "full/b": {"items": {"w": "4" * 24}}},
    }
    part_path.write_text(json.dumps(part))
    module.splice(map_path, part_path, "newrev")
    got = json.loads(map_path.read_text())
    folders = got["captures"]["fp32"]["folders"]
    assert got["revision"] == "newrev" and sorted(folders) == ["fast/a", "full/a", "full/b"]
    assert folders["full/a"] == {"bench_commit": "c0ffee", "items": {"z": "3" * 24}}
    assert folders["fast/a"] == {"items": {"y": "2" * 24}}  # untouched, like the other capture
    assert got["captures"]["bf16"] == old["captures"]["bf16"]
    part["model_revision"] = "another"
    part_path.write_text(json.dumps(part))
    with pytest.raises(SystemExit, match="another model revision"):
        module.splice(map_path, part_path, "newrev")


def test_the_shipped_map_has_the_two_folders_keyed_at_their_own_commit():
    fp32 = ds.load_map()["captures"]["fp32"]["folders"]
    assert len(fp32["full/user_modeling_hard"]["items"]) == 111
    assert len(fp32["full/directed_modulation"]["items"]) == 102
    for folder in ("full/user_modeling_hard", "full/directed_modulation"):
        assert fp32[folder]["bench_commit"].startswith("5a5d8376")
    assert "bench_commit" not in fp32["full/poetry"]
