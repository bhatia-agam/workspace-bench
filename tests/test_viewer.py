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
    # plan 0101: the plain key is the multi-token family, `_st` the single-token one; the family
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


# ------------------------------------------------------------------ plan 0101 keys, tiers


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

    from wsbench import fast

    run = {"poetry": SimpleNamespace(config={"fast_subset": fast.VARIANTS["safety"]})}
    assert wsb.fast_subset_of(run) == "fast-safety"
    assert (
        wsb.fast_subset_of({"poetry": SimpleNamespace(config={"fast_subset": "fast-v2"})}) == "fast"
    )
    assert (  # a run stamped with an earlier version of the safety variant
        wsb.fast_subset_of({"poetry": SimpleNamespace(config={"fast_subset": "fast-safety-v1"})})
        == "fast-safety"
    )
