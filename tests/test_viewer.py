"""The results viewer: README parsing, the gates table, both ingest adapters on toy runs, the
store's read side and a smoke test of every page."""

import json
from pathlib import Path

import pytest

from wsbench import registry
from wsbench.viewer import gates, meta, store
from wsbench.viewer.ingest import hb, wsb
from wsbench.viewer.query import Store

IDS = ("atomic-26-symbol", "atomic-79-symbol")
LENS = "toy-olens"
FAM = "multihop_st"  # the toy run's family: single-token multihop (`multihop` before 0101)


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def wsb_run(tmp_path: Path) -> Path:
    """A two-question summary-mode multihop run laid out like a real lens directory."""
    registry.load_all()
    root = tmp_path / LENS
    rows = [
        {"id": IDS[0], "options": ["iron", "gold"], "gold_idx": 0, "choice": "A", "pass": True,
         "quote": "The element with atomic number 26 is iron.", "quote_ok": True, "form_ok": True,
         "summary": "[2 samples] iron", "summary_statements": [
             {"statement": "26 is iron", "count": 2, "layers": [20], "evidence": "is iron"}]},
        {"id": IDS[1], "options": ["iron", "gold"], "gold_idx": 1, "choice": "A", "pass": False,
         "quote": "", "quote_ok": False, "form_ok": False},
    ]  # fmt: skip
    result = {
        "schema_version": 1, "family": FAM, "complete": True, "pinned_instrument": True,
        "config": {"aggregate": "summary", "judge_model": "claude-opus-5-5", "reader": LENS,
                   "kind": "prose", "layers_judged": [20, 44]},
        "n_items": 2, "counts": {},
        "numbers": {"metric": "pass_rate", "value": 0.5, "ci95": [0.0, 1.0], "chance": 0.2,
                    "chance_label": "1 in 5", "higher_is_better": True, "extras": {}},
        "rows": rows,
    }  # fmt: skip
    fam = root / "judged" / FAM
    fam.mkdir(parents=True)
    (fam / "results.json").write_text(json.dumps(result))
    _jsonl(fam / "cells.jsonl", [
        {"key": f"digest:{IDS[0]}|20", "result": {"items": [
            {"statement": "26 is iron", "where": "[L20 pos -1]", "evidence": "is iron",
             "count": 2}],
            "rare": []}},
        {"key": f"{IDS[0]}|L-1", "result": {"choice": "A", "quote": "is iron"},
         "meta": {"options": ["iron", "gold"]}},
        {"key": f"{IDS[1]}|L-1", "result": {"choice": "A", "quote": ""}, "meta": {}},
    ])  # fmt: skip
    cells = []
    for iid, text in ((IDS[0], "The element with atomic number 26 is iron."), (IDS[1], "no idea")):
        for layer in (20, 44):
            for pos, tok in ((-2, " is"), (-1, " ")):
                said = text if (layer, pos) == (20, -1) else "something unrelated"
                cells.append(
                    {"id": iid, "layer": layer, "pos": pos, "token": tok, "samples": [said]}
                )
    _jsonl(root / "readouts" / f"{FAM}.jsonl", cells)
    return root


@pytest.fixture
def hb_run(tmp_path: Path) -> Path:
    lens_dir = tmp_path / "hb" / LENS
    seg = {"readout": 0, "status": "ok", "why": "w", "contradicted_by": None, "supported_by": None}
    cells = [
        {"key": "it-0__L020__p5", "id": "it-0", "layer": 20, "pos": 5, "samples": ["Paris is big."],
         "stages": {"map": "ok", "cverify": "not_needed"},
         "map": {"rationale": "r", "units": [{"id": "R0.U1"}], "segments": [
             seg | {"unit": "R0.U1", "start": 0, "end": 5, "leaf": "false_claim"},
             seg | {"unit": "R0.U1", "start": 6, "end": 13, "leaf": "correct"}]}},
        {"key": "it-0__L044__p5", "id": "it-0", "layer": 44, "pos": 5, "samples": ["ok"],
         "stages": {"map": "ok", "cverify": "not_needed"},
         "map": {"segments": [seg | {"unit": "R0.U1", "start": 0, "end": 2, "leaf": "junk"}]}},
    ]  # fmt: skip
    _jsonl(lens_dir / "wsbench_chat" / hb.JUDGE / LENS / "cells.jsonl", cells)
    index = {
        "version": "hindex-v8",
        "weights": {"main_leaf": {"false_claim": 1.0, "detail": 0.2}},
        "rows": [
            {"method": LENS, "layer": 20,
             "families": {"main": {"v": 0.5, "ci": [0.2, 0.8], "n": 2, "n_items": 1}}},
            {"method": LENS, "layer": 44,
             "families": {"main": {"v": 0.1, "ci": [0.0, 0.2], "n": 10, "n_items": 1}}},
        ],
    }  # fmt: skip
    idx = lens_dir / "index" / hb.JUDGE
    idx.mkdir(parents=True)
    (idx / "index.json").write_text(json.dumps(index))
    return lens_dir


# ------------------------------------------------------------------ metadata and gates


def test_readme_groups_and_family_lines():
    metas = meta.load_wsb(registry.REPO_ROOT)
    assert len(metas) >= 28
    # the plain key is the multi-token family, `_st` the single-token one; the family
    # line links evals/<category>/<family>/README.md and may end with the tier tag
    mh, st = metas["multihop"], metas["multihop_st"]
    assert mh.title == "Multihop" and st.title == "Multihop (single-token)"
    assert mh.group == st.group == "Basic (adapted from the J-lens paper)"
    assert "silent hop" in st.what and "multiple-choice" in st.judged_by and st.example
    assert "```" in st.prompt_template  # the family README's Judge prompts section
    # the groups are the README's headings, which are the registry's categories
    assert metas["buggy_code"].group == "Computational"
    assert metas["poetry"].title == "Poetry"  # a core family: `· core` is not part of the title
    for name in ("relational_multihop", "role_bound_association"):
        assert metas[name].group == "Anti-bag-of-features"
    assert {m.group for m in metas.values()} <= {
        "J-lens comparison (not in any macro)" if g == "J-lens comparison" else g
        for g in registry.CATEGORIES.values()
    }


def test_every_gate_is_explained_in_at_most_three_sentences():
    for gid, (name, text) in gates.GATES.items():
        assert name and text, gid
        assert text.count(". ") <= 2 or gid == "kc_gates", gid


def test_gates_come_from_what_the_results_contain():
    ids = gates.for_wsb_eval(
        FAM, "a blind judge", {"quote_ok", "form_ok"}, {"aggregate": "summary"}
    )
    assert {"capability", "quote", "form", "summary_mode", "macro"} <= set(ids)
    assert "names_other" not in ids and "adapt_leak" not in ids
    native = gates.for_wsb_eval("typo_mt", "the regex contract", (), {"aggregate": None})
    assert "regex" in native and "native_mode" in native
    assert "adapt_leak" in gates.for_wsb_eval(FAM, "", adapted=True)


# ------------------------------------------------------------------ parsing helpers


@pytest.mark.parametrize(
    ("key", "want"),
    [
        ("digest:a-1|20", ("a-1", "digest", 20, None)),
        ("layered:a-1|all|d1", ("a-1", "digest_all", None, None)),
        ("a-1|L-1", ("a-1", "judge", -1, None)),
        ("a-1__L044__p69|infer|v2", ("a-1", "infer/v2", 44, 69)),
        ("ns:7|L-1", ("ns:7", "judge", -1, None)),
    ],
)
def test_parse_key(key, want):
    assert wsb.parse_key(key, {"a-1", "ns:7", "a"}) == want


def test_exact_layers_only_where_the_row_has_them():
    assert wsb.exact_layers({"pass": True, "quote": "x"}, [20, 44]) == {}
    native = {"layers": {"20": {"expressed": False}, "44": {"expressed": True}}}
    assert wsb.exact_layers(native, []) == {20: False, 44: True}
    regex = {"passing_layers": [44], "layers": {"20": {"hits": {}}, "44": {"hits": {"c": ["en"]}}}}
    assert wsb.exact_layers(regex, []) == {20: False, 44: True}


def test_method_guess():
    assert wsb.guess_method("jlens_j") == "jlens"
    assert wsb.guess_method("mylens.nla.step2000") == "nla"
    assert wsb.guess_method("my-prose-lens.step600") == "olens"


# ------------------------------------------------------------------ WorkspaceBench ingest


def test_wsb_ingest_round_trip(wsb_run: Path, tmp_path: Path):
    root = tmp_path / "store"
    out = wsb.ingest(wsb_run, root, build_dir=tmp_path / "build")
    assert out["families"][FAM] == {"value": 0.5, "n": 2, "cells": 8, "rows": 2}
    assert json.loads((root / "manifest.json").read_text())["schema"] == store.SCHEMA
    db = Store(root)
    v = db.scores("wsb", wsb.ORIGINAL, "full")
    s = v[FAM][out["run_id"]]
    assert (s["value"], s["ci_lo"], s["ci_hi"], s["n"]) == (0.5, 0.0, 1.0, 2)  # = results.json
    assert v[FAM]["chance"]["value"] == 0.2
    items = {i["item"]: i for i in db.items("wsb", wsb.ORIGINAL, FAM)}
    assert items[IDS[0]]["runs"][out["run_id"]]["pass"] == 1
    assert items[IDS[1]]["runs"][out["run_id"]]["pass"] == 0
    cells = db.cells(out["run_id"], FAM, IDS[0])
    assert cells["layers"] == [20, 44] and [p["p"] for p in cells["positions"]] == [-2, -1]
    hit = cells["cells"]["20:-1"]
    assert hit["f"] == store.HAS_EXPECTED | store.HAS_QUOTE | store.CITED
    assert cells["cells"]["44:-1"]["f"] == 0 and "iron" in cells["terms"]
    assert {j["stage"] for j in cells["judgments"]} == {"digest", "judge"}
    assert cells["verdicts"][0]["detail"]["_n_statements"] == 1
    assert db.digest(out["run_id"], FAM, IDS[0]) == "[2 samples] iron"
    # the proxy per-layer stats are labelled by kind, never as a judge verdict
    stats = db.layer_stats("wsb", wsb.ORIGINAL, FAM)[FAM]
    assert set(stats) == {"expected", "cited"}
    assert stats["expected"][out["run_id"]] == [(20, 0.5, 2), (44, 0.0, 2)]
    assert db.search("atomic number 26", "wsb", wsb.ORIGINAL)[0]["item"] == IDS[0]
    right = db.filter("wsb", wsb.ORIGINAL, [(out["run_id"], "right")])
    assert [r["item"] for r in right] == [IDS[0]]


def test_wsb_ingest_is_idempotent_and_takes_two_questions(wsb_run: Path, tmp_path: Path):
    root = tmp_path / "store"
    assert not wsb.ingest(wsb_run, root)["skipped"]
    assert wsb.ingest(wsb_run, root)["skipped"]
    assert not wsb.ingest(wsb_run, root, force=True)["skipped"]
    one = wsb.ingest(wsb_run, root, lens="two", items=[IDS[1]])
    assert one["families"][FAM]["cells"] == 4
    db = Store(root)
    assert db.cells(one["run_id"], FAM, IDS[0])["cells"] == {}


def test_private_items_are_hidden_unless_allowed(wsb_run: Path, tmp_path: Path):
    root = tmp_path / "store"
    out = wsb.ingest(wsb_run, root)
    cat = store.catalog(root)
    cat.execute("UPDATE item SET private = 1 WHERE item = ?", (IDS[0],))
    cat.commit()
    cat.close()
    hidden = Store(root)
    assert hidden.cells(out["run_id"], FAM, IDS[0]) == {
        "run": out["run_id"],
        "private": True,
    }
    assert hidden.item("wsb", wsb.ORIGINAL, FAM, IDS[0])["hidden"]
    assert hidden.search("atomic number 26", "wsb", wsb.ORIGINAL) == []
    assert hidden.digest(out["run_id"], FAM, IDS[0]) == ""
    shown = Store(root, private=True)
    assert shown.cells(out["run_id"], FAM, IDS[0])["cells"]


# ------------------------------------------------------------------ HallucinationBench ingest


def test_hb_ingest_scores_and_segments(hb_run: Path, tmp_path: Path):
    root = tmp_path / "store"
    out = hb.ingest(hb_run, root)
    db = Store(root)
    s = db.scores("hb", hb.MODEL, "full")["main"][out["run_id"]]
    assert s["value"] == pytest.approx(0.3) and s["ci_lo"] == pytest.approx(0.1)  # layer means
    assert db.layer_stats("hb", hb.MODEL)["main"]["hb"][out["run_id"]][0][:2] == (20, 0.5)
    # the store's own recount of layer 20 (1 false claim of 2 claims) matches the index
    assert out["check"]["main"][20] == 0.0
    cell = db.cells(out["run_id"], "main", "it-0")["cells"]["20:5"]
    assert [(g["leaf"], g["w"]) for g in cell["g"]] == [("false_claim", 1.0), ("correct", 0.0)]
    junk = db.cells(out["run_id"], "main", "it-0")["cells"]["44:5"]["g"][0]
    assert junk["w"] is None  # not a claim: outside the denominator
    assert hb.ingest(hb_run, root)["skipped"]


# ------------------------------------------------------------------ the app


def test_every_page_renders(wsb_run: Path, hb_run: Path, tmp_path: Path):
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    root = tmp_path / "store"
    rid = wsb.ingest(wsb_run, root)["run_id"]
    hb.ingest(hb_run, root)
    client = TestClient(create_app(root))
    for path in ("/", "/?bench=hb", f"/eval/{FAM}", f"/q/{FAM}/{IDS[0]}", "/layers",
                 "/filter", "/search?q=iron", "/bookmarks", "/eval/main?bench=hb",
                 "/q/main/it-0?bench=hb", "/filter?bench=hb", "/static/app.css"):  # fmt: skip
        r = client.get(path)
        assert r.status_code == 200, path
    assert "How it is judged" in client.get(f"/eval/{FAM}").text
    blob = client.get(f"/api/cells?run={rid}&eval={FAM}&item={IDS[0]}").json()
    assert blob["pass"] == 1 and "20:-1" in blob["cells"]
    mark = {"bench": "wsb", "model": wsb.ORIGINAL, "eval": FAM, "item": IDS[0],
            "run_id": rid, "layer": 20, "pos": -1, "note": "look"}  # fmt: skip
    assert client.post("/api/bookmark", json=mark).json()["id"] == 1
    assert "look" in client.get("/bookmarks").text


def test_viewer_store_check_round_trips_the_toy_run():
    from wsbench.viewer.checks import viewer_store

    ok, why = viewer_store()
    assert ok, why
    assert "round-trip" in why and viewer_store.__doc__
    assert viewer_store(run="/nonexistent")[0] is False


def test_viewer_commands_are_pydra_configs(capsys):
    """Every viewer key goes through pydra: --show prints it, an unknown key is exit 2."""
    from wsbench.viewer import cli as viewer_cli

    assert viewer_cli.main(["serve", "port=9001", "--show"]) == 0
    assert '"port": 9001' in capsys.readouterr().out
    assert viewer_cli.main(["ingest", "some/dir", "families=a,b", "--show"]) == 0
    shown = capsys.readouterr().out
    assert '"src": "some/dir"' in shown and '"families": "a,b"' in shown
    assert viewer_cli.main(["ingest", "some/dir", "nope=1"]) == viewer_cli.EXIT_USAGE
    assert viewer_cli.main(["ingest", "some/dir", "adapter=zzz"]) == viewer_cli.EXIT_USAGE
    assert viewer_cli.main(["ingest"]) == viewer_cli.EXIT_USAGE


# ------------------------------------------------------------------ family keys, tiers


def test_a_run_tree_from_before_the_rename_is_read_as_its_family(wsb_run: Path, tmp_path: Path):
    # judged/multihop/ + readouts/multihop.jsonl, as every lens directory of the campaign has
    (wsb_run / "judged" / FAM).rename(wsb_run / "judged" / "multihop")
    (wsb_run / "readouts" / f"{FAM}.jsonl").rename(wsb_run / "readouts" / "multihop.jsonl")
    assert list(wsb.family_dirs(wsb_run / "judged")) == [FAM]
    out = wsb.ingest(wsb_run, tmp_path / "store")
    assert out["families"][FAM]["cells"] == 8


def test_core_is_offered_and_is_the_default_where_a_core_eval_has_a_full_score(
    wsb_run: Path, tmp_path: Path
):
    from wsbench.viewer.app import pages
    from wsbench.viewer.query import CORE, MACRO, SUBSET_TITLES

    assert list(SUBSET_TITLES) == [CORE, "full", "fast", "fast-safety", "ati"]
    root = tmp_path / "store"
    rid = wsb.ingest(wsb_run, root)["run_id"]
    db = Store(root)
    assert db.subsets("wsb", wsb.ORIGINAL) == ["full"]  # the toy family is not a core one
    assert pages.make_view(db, {}).subset == "full"
    cat = store.catalog(root)
    for ev, value in (("poetry", 0.4), ("buggy_code", 0.8)):
        cat.execute(
            "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, ev, "full", -1, "lens", value, None, None, 10, None),
        )
    cat.commit()
    db = Store(root)
    assert db.subsets("wsb", wsb.ORIGINAL) == [CORE, "full"]
    core = db.scores("wsb", wsb.ORIGINAL, CORE)
    assert set(core) == {"poetry", "buggy_code", MACRO}  # the toy family is in full only
    assert core[MACRO][rid]["value"] == pytest.approx(0.6) and core[MACRO][rid]["n"] == 2
    view = pages.make_view(db, {})
    assert view.subset == CORE and "subset" not in view.args()
    assert pages.make_view(db, {"subset": "full"}).args()["subset"] == "full"


def test_a_fast_safety_run_is_stored_under_its_own_subset():
    from types import SimpleNamespace

    # the safety variant is retired (plan 0104): its runs are known by their stamp alone
    run = {"poetry": SimpleNamespace(config={"fast_subset": "fast-safety-v2"})}
    assert wsb.fast_subset_of(run) == "fast-safety"
    # a plain fast run is `fast` only on the default selection: fast-v2 holds other poetry
    # questions than the default, so it is stored under its own name (was `fast` while the
    # default was a version with poetry's identical entry; the test below pins that case)
    assert (
        wsb.fast_subset_of({"poetry": SimpleNamespace(config={"fast_subset": "fast-v2"})})
        == "fast-v2"
    )
    assert (  # a run stamped with an earlier version of the safety variant
        wsb.fast_subset_of({"poetry": SimpleNamespace(config={"fast_subset": "fast-safety-v1"})})
        == "fast-safety"
    )


def _fast_row(version: str | None):
    from types import SimpleNamespace

    return SimpleNamespace(
        config={"scope": "fast", **({"fast_subset": version} if version else {})}
    )


def test_the_fast_view_holds_one_selection_only(wsb_run: Path, tmp_path: Path, monkeypatch):
    """`fast` is the DEFAULT selection: a run stamped with the default version, or with one
    whose entry for every family is identical; any other fast run is stored under the version
    it was judged on, with a readable title, and is offered as a subset of its own."""
    from wsbench import fast
    from wsbench.viewer.query import SUBSET_TITLES, subset_title

    assert wsb.fast_subset_of({"poetry": _fast_row(fast.DEFAULT)}) == "fast"
    for old in ("fast-v1", "fast-v2", "fast-v3"):
        assert wsb.fast_subset_of({"poetry": _fast_row(old)}) == old
        assert old not in SUBSET_TITLES and old in subset_title(old)
        assert subset_title(old).startswith("Fast subset (")
    # one row of another selection is enough; an unstamped run is nobody's selection
    mixed = {"poetry": _fast_row(fast.DEFAULT), "buggy_code": _fast_row("fast-v3")}
    assert wsb.fast_subset_of(mixed) == "fast-v3"
    assert wsb.fast_subset_of({"poetry": _fast_row(None)}) == wsb.UNSTAMPED
    assert subset_title(wsb.UNSTAMPED).startswith("Fast subset (")
    # compatibility is per family (`fast.compatible`): under fast-v3 as the default, fast-v2's
    # poetry entry is the same entry, conjunctive_association's is not (its bank was re-frozen)
    monkeypatch.setattr(fast, "DEFAULT", "fast-v3")
    assert wsb.fast_subset_of({"poetry": _fast_row("fast-v2")}) == "fast"
    assert wsb.fast_subset_of({"conjunctive_association": _fast_row("fast-v2")}) == "fast-v2"
    both = {"poetry": _fast_row("fast-v2"), "conjunctive_association": _fast_row("fast-v2")}
    assert wsb.fast_subset_of(both) == "fast-v2"
    monkeypatch.undo()
    # the store lists such a subset after the titled ones
    root = tmp_path / "store"
    rid = wsb.ingest(wsb_run, root)["run_id"]
    cat = store.catalog(root)
    for subset in ("fast-v3", "fast"):
        cat.execute(
            "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, "poetry", subset, -1, "lens", 0.5, None, None, 10, None),
        )
    cat.commit()
    assert Store(root).subsets("wsb", wsb.ORIGINAL) == ["full", "fast", "fast-v3"]


def test_a_new_default_fast_version_re_derives_the_fast_scores_of_a_full_run(
    wsb_run: Path, tmp_path: Path, monkeypatch
):
    """The ingest signature holds the default fast version: an unchanged full run is skipped
    only while the fast scores derived from it are the current selection's."""
    from wsbench import fast

    root = tmp_path / "store"
    assert not wsb.ingest(wsb_run, root)["skipped"]
    assert wsb.ingest(wsb_run, root)["skipped"]
    sig = store.catalog(root).execute("SELECT source_sig FROM run").fetchone()["source_sig"]
    assert sig.endswith(f"|fast={fast.DEFAULT}")
    monkeypatch.setattr(fast, "DEFAULT", "fast-v3")
    assert not wsb.ingest(wsb_run, root)["skipped"]  # same files, another default
    assert wsb.ingest(wsb_run, root)["skipped"]


def test_fast_membership_is_the_frozen_files_never_a_union(wsb_run: Path, tmp_path: Path):
    """What an earlier default left under `fast` (other questions of a family, families that
    are no fast families any more) is deleted before the registered membership is written."""
    from wsbench import fast

    root = tmp_path / "store"
    rid = wsb.ingest(wsb_run, root)["run_id"]
    cat = store.catalog(root)
    old, new = fast.subset("fast-v3"), fast.subset(fast.DEFAULT)
    gone = sorted(set(old) - set(new))[0]  # a fast-v3 family outside the default
    stale = [(f, i) for f in ("poetry", gone) for i in wsb._members(old[f])]
    stale.append(("poetry", "never-a-question"))
    cat.executemany(
        "INSERT OR IGNORE INTO subset_item VALUES (?,?,?,?,?)",
        [("wsb", wsb.ORIGINAL, "fast", f, i) for f, i in stale],
    )
    cat.executemany(  # another subset and another model are not this function's to clear
        "INSERT OR IGNORE INTO subset_item VALUES (?,?,?,?,?)",
        [
            ("wsb", wsb.ORIGINAL, "ati", "poetry", "kept"),
            ("wsb", "other", "fast", "poetry", "kept"),
        ],
    )
    wsb.write_fast_scores(cat, rid, wsb.ORIGINAL, {})
    cat.commit()

    def members(model: str, subset: str) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in cat.execute(
            "SELECT eval, item FROM subset_item WHERE bench = 'wsb' AND model = ? AND subset = ?",
            (model, subset),
        ):
            out.setdefault(r["eval"], set()).add(r["item"])
        return out

    assert members(wsb.ORIGINAL, "fast") == {f: wsb._members(e) for f, e in new.items()}
    assert wsb._members(old["poetry"]) - wsb._members(new["poetry"])  # the union would differ
    assert members(wsb.ORIGINAL, "ati") == {"poetry": {"kept"}}
    assert members("other", "fast") == {"poetry": {"kept"}}


def test_fast_membership_of_a_fast_run_is_per_family_from_its_own_stamp(monkeypatch):
    """A directory that mixes versions: every family's members come from the version ITS row
    is stamped with; an unstamped or unregistered row has none (the default is never assumed);
    versions are ordered by number."""
    from wsbench import fast

    only_v3 = sorted(set(fast.subset("fast-v3")) - set(fast.subset(fast.DEFAULT)))[0]
    run = {
        "poetry": _fast_row("fast-v3"),
        "buggy_code": _fast_row(fast.DEFAULT),
        only_v3: _fast_row("fast-v3"),
        "hinted_cutoff": _fast_row(None),
        "nyt_connections": _fast_row("fast-v99"),
        "jailbreak_recognition": _fast_row("fast-safety-v2"),
        "multihop_st": _fast_row("fast-v3"),  # the version it names does not hold it
    }
    got = wsb.fast_members(run)
    assert set(got) == {"poetry", "buggy_code", only_v3, "jailbreak_recognition"}
    assert got["poetry"] == wsb._members(fast.subset("fast-v3")["poetry"])
    assert got["poetry"] != wsb._members(fast.subset(fast.DEFAULT)["poetry"])
    assert got["buggy_code"] == wsb._members(fast.subset(fast.DEFAULT)["buggy_code"])
    assert got[only_v3] == wsb._members(fast.subset("fast-v3")[only_v3])
    assert got["jailbreak_recognition"] == wsb._members(
        fast.subset("fast-safety-v2")["jailbreak_recognition"]
    )
    assert wsb.fast_version_of(_fast_row(None)) is None
    assert wsb.fast_version_of(_fast_row("fast-v99")) is None
    assert wsb.fast_members({"poetry": _fast_row(None)}) == {}  # an unstamped run: no members
    # numeric order: fast-v10 is newer than fast-v4 (a plain sort puts it first)
    names = ["fast-v10", "fast-v4", "fast-v9", "fast-safety-v2", "fast"]
    assert sorted(names) != sorted(names, key=wsb.version_key)
    assert sorted(names, key=wsb.version_key) == [
        "fast", "fast-v4", "fast-v9", "fast-v10", "fast-safety-v2",
    ]  # fmt: skip
    assert wsb.fast_subset_of({"poetry": _fast_row("fast-v10"), "buggy_code": _fast_row("fast-v4"),
                               "relational_multihop": _fast_row("fast-v9")}) == (
        "fast-v10" if fast.DEFAULT != "fast-v10" else "fast-v9"
    )  # fmt: skip


def test_hb_what_it_measures_comes_from_the_column_of_that_name(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "evals.md").write_text(
        "| eval | what it measures | plan |\n|---|---|---|\n"
        "| `story` | the claim map on **20** story items | [0007](x.md) |\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "claim_map.md").write_text(
        "# The claim map\n\nHow a readout is cut.\n\n## Other\n\nno\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "| family | weight | what it tests | prompts |\n|---|---|---|---|\n"
        "| `story` | 1 | README text | 20 |\n| `overrefusal` | 1 | Refusal claims. | 427 |\n\n"
        "| path | holds |\n|---|---|\n| `benign_roleplay` | not a description |\n",
        encoding="utf-8",
    )
    metas = meta.load_hb(tmp_path)
    assert metas["story"].what == "the claim map on 20 story items"  # docs/evals.md first
    assert metas["overrefusal"].what == "Refusal claims."  # the README's column, not its weight
    assert "not a description" not in metas["benign_roleplay"].what  # no 'what' column there
    assert metas["main"].prompt_template == "How a readout is cut."
    assert meta.load_hb(None)["story"].what  # the built-in one-liners


def test_questions_an_updated_bank_dropped_leave_the_list_and_mark_the_run(
    wsb_run: Path, tmp_path: Path
):
    """A bank that changed after a run was judged: the eval lists the bank's questions as
    they are now, and the run judged on the earlier ones says so beside its score."""
    from wsbench import registry
    from wsbench.viewer.query import EARLIER_BANK

    root = tmp_path / "store"
    rid = wsb.ingest(wsb_run, root, build_dir=tmp_path / "build")["run_id"]
    db = Store(root)
    before = [i["item"] for i in db.items("wsb", wsb.ORIGINAL, FAM)]
    assert set(IDS) <= set(before) and db.eval_marks("wsb", wsb.ORIGINAL) == {}
    # a checkout whose bank no longer holds the second question
    rel = registry.frozen_bank_path(FAM).relative_to(registry.REPO_ROOT)
    bank = json.loads((registry.REPO_ROOT / rel).read_text())
    rows = bank["items"] if isinstance(bank, dict) else bank
    rows[:] = [r for r in rows if IDS[1] not in (r.get("id"), r.get("name"))]
    repo = tmp_path / "checkout"
    (repo / rel).parent.mkdir(parents=True)
    (repo / rel).write_text(json.dumps(bank))
    cat = store.catalog(root)
    wsb.write_bank(cat, repo, wsb.ORIGINAL, families=[FAM])
    cat.close()
    db = Store(root)
    after = [i["item"] for i in db.items("wsb", wsb.ORIGINAL, FAM)]
    assert after == [i for i in before if i != IDS[1]]  # same order, one question fewer
    assert db.eval("wsb", wsb.ORIGINAL, FAM)["n_items"] == len(after)
    label, why = db.eval_marks("wsb", wsb.ORIGINAL)[rid][FAM]
    assert label == EARLIER_BANK and why.startswith("1 of the questions")
    assert db.item("wsb", wsb.ORIGINAL, FAM, IDS[1])["prompt"]  # its page keeps its text
    # the bank holds it again (the first checkout): it is listed where it was, the mark goes
    cat = store.catalog(root)
    wsb.write_bank(cat, registry.REPO_ROOT, wsb.ORIGINAL, families=[FAM])
    cat.close()
    db = Store(root)
    assert [i["item"] for i in db.items("wsb", wsb.ORIGINAL, FAM)] == before
    assert db.eval_marks("wsb", wsb.ORIGINAL) == {}
