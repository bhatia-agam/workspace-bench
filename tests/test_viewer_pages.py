"""The viewer's read-time facts: registry categories, the sets a store has data for, who scores
an eval, the method palette, HallucinationBench's leaf table and the labels on a run."""

import os
import re
from pathlib import Path

import pytest

from wsbench import fast, registry, tiers
from wsbench.viewer import meta, query, store
from wsbench.viewer.query import CORE, Store

MODEL = "toy-model"
RUN = "wsb__toy-model__lens-a"
# registered evals of five categories, and one name the registry does not know
EVALS = (
    "poetry", "multilingual", "association", "user_modeling", "role_bound_association",
    "relational_multihop", "jailbreak_recognition", "not_in_the_registry",
)  # fmt: skip


def _store(root: Path, subsets: tuple[str, ...] = ("full",), note: str | None = None) -> Store:
    """A catalog with one run and the evals above, scored in ``subsets``; the set ``fast`` (the
    current fast subset) scores only the evals that subset holds."""
    current = set(fast.subset(fast.DEFAULT))
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO run (run_id, bench, lens, label, method, model, meta) VALUES (?,?,?,?,?,?,?)",
        (RUN, "wsb", "lens-a", "lens-a", "olens", MODEL, "{}"),
    )
    for n, name in enumerate(EVALS):
        cat.execute(
            "INSERT INTO eval (bench, model, eval, title, grp, ord, n_items)"
            " VALUES (?,?,?,?,?,?,?)",
            ("wsb", MODEL, name, name.title(), "a group stored at ingest", n, 10),
        )
        for subset in subsets:
            if subset == "fast" and name not in current:
                continue
            cat.execute(
                "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
                (RUN, name, subset, -1, "lens", 0.5, 0.4, 0.6, 10, note),
            )
    cat.commit()
    cat.close()
    return Store(root)


def _score(root: Path, rows: list[tuple]) -> None:
    """Headline lens rows ``(run, eval, subset[, note])`` added to a store."""
    cat = store.catalog(root)
    for run, name, subset, *note in rows:
        cat.execute(
            "INSERT OR REPLACE INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (run, name, subset, -1, "lens", 0.5, None, None, 10, note[0] if note else None),
        )
    cat.commit()
    cat.close()


def test_categories_are_the_registrys_and_every_eval_is_listed_once(tmp_path: Path, monkeypatch):
    registry.load_all()
    monkeypatch.setattr(query, "also_in", dict)  # a benchmark without second listings
    groups = _store(tmp_path / "s").groups("wsb", MODEL)
    titles = [g["title"] for g in groups]
    # the registry's order, its titles without the parenthesis; unknown evals go last
    assert titles == ["Basic", "Association", "Safety", "Anti-bag-of-features", "Other"]
    assert [g["key"] for g in groups][:2] == ["basic", "association"]
    by_title = {g["title"]: g["evals"] for g in groups}
    assert [e["eval"] for e in by_title["Basic"]] == ["poetry", "multilingual"]
    assoc = {e["eval"]: e for e in by_title["Association"]}
    assert set(assoc) == {"association", "user_modeling"}
    # role-bound association is under anti-bag-of-features only
    own = {e["eval"]: e for e in by_title["Anti-bag-of-features"]}
    assert set(own) == {"role_bound_association", "relational_multihop"}
    listed = [e["eval"] for g in groups for e in g["evals"]]
    assert len(listed) == len(set(listed))
    assert [e["eval"] for e in by_title["Other"]] == ["not_in_the_registry"]
    # every registry category has a short title, and the table copied here matches the module
    assert all(query.category_title(k) for k in registry.CATEGORIES)
    assert query.category_title("basic") == "Basic"
    assert query.category_title("jlens_comparison") == "J-lens comparison"


def test_a_second_category_listing_follows_the_benchmarks_table(tmp_path: Path, monkeypatch):
    """Where the benchmark's ``groups.ALSO_IN`` lists an eval under a second category, that
    category shows it too, marked; without the table every eval is listed once."""
    from wsbench import groups as bench_groups

    registry.load_all()
    db = _store(tmp_path / "s")
    monkeypatch.setattr(
        bench_groups, "ALSO_IN", {"association": ("role_bound_association",)}, raising=False
    )
    assert query.also_in() == {"association": ("role_bound_association",)}
    by_title = {g["title"]: g["evals"] for g in db.groups("wsb", MODEL)}
    assoc = {e["eval"]: e for e in by_title["Association"]}
    assert assoc["role_bound_association"]["also_in"] == "Anti-bag-of-features"
    assert "also_in" not in assoc["association"]
    own = {e["eval"]: e for e in by_title["Anti-bag-of-features"]}
    assert "also_in" not in own["role_bound_association"]  # it stays in its own category
    monkeypatch.delattr(bench_groups, "ALSO_IN")
    assert query.also_in() == {}
    listed = [e["eval"] for g in db.groups("wsb", MODEL) for e in g["evals"]]
    assert len(listed) == len(set(listed))


def test_no_eval_of_the_store_is_left_out_of_the_groups(tmp_path: Path):
    db = _store(tmp_path / "s")
    listed = {e["eval"] for g in db.groups("wsb", MODEL) for e in g["evals"]}
    assert listed == set(EVALS)


def test_scored_by_comes_from_the_registry(tmp_path: Path):
    registry.load_all()
    for name, spec in registry.FAMILIES.items():
        want = query.SCORED_BY_RULE if spec.scorer else query.SCORED_BY_JUDGE
        assert query.scored_by("wsb", name) == want
    assert query.scored_by("wsb", "multilingual") == "rule (regex)"
    assert query.scored_by("wsb", "poetry") == "Claude judge"
    assert query.scored_by("wsb", "typo_mt") == "rule (regex)"  # a former key of `typo`
    assert query.scored_by("wsb", "not_in_the_registry") == ""
    assert query.scored_by("hb", "main") == "Claude judge"
    evs = {e["eval"]: e for e in _store(tmp_path / "s").evals("wsb", MODEL)}
    assert evs["multilingual"]["scored_by"] == "rule (regex)"
    assert evs["multilingual"]["grp"] == "Basic"  # the registry's category, not the stored one


def test_a_set_is_offered_only_where_the_store_has_data(tmp_path: Path):
    assert list(query.SUBSET_TITLES.values()) == [
        "Core", "Full", "Fast", "Fast with safety (an earlier fast subset)", "Anti-text-inversion"
    ]  # fmt: skip
    assert "poetry" in tiers.CORE and "multilingual" not in tiers.CORE
    # the sets are the benchmark's own, read when asked: the core tier and the current subset
    assert "conjunctive_association" in tiers.CORE
    assert _store(tmp_path / "tier")._core("wsb") == set(tiers.CORE)
    assert set(Store._current_fast()) == set(fast.subset(fast.DEFAULT)) <= set(tiers.CORE)
    full = _store(tmp_path / "full")
    assert full.subsets("wsb", MODEL) == [CORE, "full"]  # core: a core eval has a full score
    fast_only = _store(tmp_path / "fast", ("fast",))
    assert fast_only.subsets("wsb", MODEL) == ["fast"]  # no full run: neither full nor core
    both = _store(tmp_path / "both", ("full", "fast-safety", "ati"))
    assert both.subsets("wsb", MODEL) == [CORE, "full", "fast-safety", "ati"]
    assert Store(tmp_path / "full").subsets("wsb", "a-model-with-no-scores") == ["full"]


def _facts(root: Path, rid: str, **facts) -> None:
    """A `run_facts` row for ``rid`` (what a runs manifest gives ingest)."""
    cat = store.catalog(root)
    cols = {"run_id": rid, "run_name": rid.rsplit("__", 1)[-1]} | facts
    cat.execute(
        f"INSERT INTO run_facts ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        tuple(cols.values()),
    )
    cat.commit()
    cat.close()


def test_derived_sets_are_labelled_from_the_stored_sets(tmp_path: Path):
    assert query.DERIVED == "derived from the full run"
    db = _store(tmp_path / "plain", ("full", "fast"))
    # no stored set rows: the core rows are the page's own derivation, fast says nothing
    assert set(db.derived_runs("wsb", MODEL, CORE)) == {RUN}
    assert db.derived_runs("wsb", MODEL, "fast") == {}
    assert db.derived_runs("wsb", MODEL, "full") == {}
    root = tmp_path / "sets"
    _store(root, ("full", "fast"))
    cat = store.catalog(root)
    cat.executemany(
        "INSERT INTO run_set (run_id, subset, derived, origin, note) VALUES (?,?,?,?,?)",
        [(RUN, "full", 0, "judged", ""), (RUN, "fast", 1, "full run", "cut from the full run")],
    )
    cat.commit()
    cat.close()
    db = Store(root)
    assert db.derived_runs("wsb", MODEL, "fast") == {RUN: "cut from the full run"}
    assert db.derived_runs("wsb", MODEL, "full") == {}
    # a run ingested before the sets were recorded says it in its macro's note
    old = tmp_path / "old"
    _store(old, ("full", "fast"))
    cat = store.catalog(old)
    cat.execute(
        "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
        (RUN, query.MACRO, "fast", -1, "lens", 0.5, None, None, 8,
         "full-run verdicts on the fast questions (not a separate fast run)"),
    )  # fmt: skip
    cat.commit()
    cat.close()
    assert set(Store(old).derived_runs("wsb", MODEL, "fast")) == {RUN}


def _stored_core(root: Path, names: tuple[str, ...]) -> None:
    cat = store.catalog(root)
    for name, value, n in (*((name, 0.7, 10) for name in names), (query.MACRO, 0.61, 17)):
        cat.execute(
            "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            (RUN, name, CORE, -1, "lens", value, None, None, n, "stored"),
        )
    cat.commit()
    cat.close()


def test_the_stored_core_set_wins_over_the_pages_own_mean(tmp_path: Path):
    root = tmp_path / "s"
    _store(root)
    derived = Store(root).scores("wsb", MODEL, CORE)
    assert derived[query.MACRO][RUN]["value"] == pytest.approx(0.5)  # the mean of the core rows
    today = tuple(e for e in EVALS if e in tiers.CORE)  # the run's evals of today's core tier
    assert set(derived) - {query.MACRO} == set(today) and len(today) == 4
    _stored_core(root, today)
    core = Store(root).scores("wsb", MODEL, CORE)
    assert (
        core[query.MACRO][RUN]["value"] == pytest.approx(0.61) and core[query.MACRO][RUN]["n"] == 17
    )
    assert core["poetry"][RUN]["value"] == pytest.approx(0.7)


def test_core_rows_stored_under_an_earlier_core_list_give_way_to_todays(tmp_path: Path):
    """A store written before an eval joined the core tier holds core rows without it: the
    page shows today's tier from the full rows; a run that named its own list keeps it."""
    root = tmp_path / "s"
    _store(root)
    _stored_core(root, ("poetry",))  # the tier as it was: one eval short of today's
    core = Store(root).scores("wsb", MODEL, CORE)
    assert RUN in core["role_bound_association"] and core["poetry"][RUN]["value"] == 0.5
    assert core[query.MACRO][RUN]["n"] == 4 and "of 20 core evals" in core[query.MACRO][RUN]["note"]
    assert len(tiers.CORE) == 20
    _facts(root, RUN, entry=store.dumps({"families_file": "results/core.txt"}))
    own = Store(root).scores("wsb", MODEL, CORE)
    assert own[query.MACRO][RUN]["n"] == 17 and own["poetry"][RUN]["value"] == pytest.approx(0.7)
    assert RUN not in own.get("role_bound_association", {})  # only what the run's list holds


def test_integrity_of_a_run_and_of_an_eval_come_from_the_stored_facts(tmp_path: Path):
    root = tmp_path / "s"
    _store(root)
    assert Store(root).runs("wsb", MODEL)[0]["integrity"] == ""  # no facts: no label
    _facts(root, RUN, integrity="provisional", integrity_reason="2 items undecided")
    cat = store.catalog(root)
    cat.executemany(
        "INSERT INTO run_eval (run_id, eval, integrity, reason, facts) VALUES (?,?,?,?,?)",
        [
            (RUN, "poetry", "incomplete", "3 unjudged cells", "{}"),
            (RUN, "multilingual", "", "", "{}"),
        ],
    )
    cat.commit()
    cat.close()
    db = Store(root)
    run = db.runs("wsb", MODEL)[0]
    assert (run["integrity"], run["integrity_reason"]) == ("provisional", "2 items undecided")
    assert db.eval_marks("wsb", MODEL) == {RUN: {"poetry": ("incomplete", "3 unjudged cells")}}
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    client = TestClient(create_app(root))
    page = client.get("/?subset=full").text
    assert 'title="3 unjudged cells">incomplete</span>' in page
    assert 'title="2 items undecided">provisional</span>' in page
    assert "3 unjudged cells" in client.get("/eval/poetry?subset=full").text


def test_default_shows_one_run_per_lens(tmp_path: Path):
    from wsbench.viewer.app import pages

    root = tmp_path / "s"
    _store(root, ("full", "fast"))
    cat = store.catalog(root)
    for rid, when, subsets in (("wsb__toy-model__lens-a__newer", 20.0, ("full", "fast")),
                               ("wsb__toy-model__lens-a__fast-only", 30.0, ("fast",))):  # fmt: skip
        cat.execute(
            "INSERT INTO run (run_id, bench, lens, label, method, model, meta, ingested_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (rid, "wsb", "lens-a", rid[-9:], "olens", MODEL, "{}", when),
        )
        for subset in subsets:
            cat.execute(
                "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, "poetry", subset, -1, "lens", 0.5, None, None, 10, None),
            )
    cat.commit()
    cat.close()
    (root / store.ALIASES).write_text('{"lens-a": {"label": "Lens A", "default": true}}')
    db = Store(root)
    for subset in ("full", "fast", "core"):
        view = pages.make_view(db, {"subset": subset})
        shown, runs = pages.chosen_runs(db, view)
        # of the three runs of the lens: those with a full set, then the most evals in the set
        assert [r["run_id"] for r in shown] == [RUN], subset
        assert len(runs) == 3
    picked = pages.make_view(db, {"runs": "wsb__toy-model__lens-a__fast-only"})
    assert [r["run_id"] for r in pages.chosen_runs(db, picked)[0]] == [
        "wsb__toy-model__lens-a__fast-only"
    ]


OLD_ONLY = "user_modeling"  # an eval of an earlier fast subset that the current one dropped
EARLIER = query.EARLIER_FAST


def test_fast_is_the_current_subset_and_an_earlier_one_is_labelled(tmp_path: Path):
    """Rows a store holds under `fast` from an earlier fast subset are a set of their own,
    titled as an earlier fast subset with its evals; "Fast" is the current subset alone."""
    assert OLD_ONLY in fast.subset("fast-v3") and OLD_ONLY not in fast.subset(fast.DEFAULT)
    assert query.subset_title("fast") == "Fast"
    assert query.subset_title(EARLIER, 22) == "Earlier fast subset (22 evals)"
    named = query.subset_title("fast-v3", 22)  # a run stored under the subset it was judged on
    assert named == "Fast subset (fast-v3, an earlier fast subset of 22 evals)"
    for name in (EARLIER, "fast-v3", "fast-unstamped", "fast-safety"):
        assert (
            query.is_earlier_fast(name)
            and "earlier fast subset" in query.subset_title(name).lower()
        )
        assert query.subset_title(name) != "Fast"
    assert not query.is_earlier_fast("fast") and not query.is_earlier_fast("full")
    # no stamp: an eval outside the current subset says the rows are an earlier subset's
    root = tmp_path / "evals"
    _store(root, ("full",))
    _score(root, [(RUN, e, "fast") for e in ("poetry", OLD_ONLY)])
    db = Store(root)
    assert db.subsets("wsb", MODEL) == [CORE, "full", EARLIER]
    assert db.title("wsb", MODEL, EARLIER) == "Earlier fast subset (2 evals)"
    assert db.scores("wsb", MODEL, "fast") == {} and db.run_subsets("wsb", MODEL)[RUN][EARLIER] == 2
    assert set(db.scores("wsb", MODEL, EARLIER)) == {"poetry", OLD_ONLY}
    assert [(s["subset"], s["title"]) for s in db.run_sets(RUN)] == [
        ("full", "Full"), (EARLIER, "Earlier fast subset (2 evals)")
    ]  # fmt: skip
    # a stamp in the stored note decides, also where every eval is one the current subset has
    for note, want in (
        ("full-run verdicts on the fast-v3 questions (not a separate fast run)", EARLIER),
        (f"full-run verdicts on the {fast.DEFAULT} questions (not a separate fast run)", "fast"),
    ):
        root = tmp_path / want
        _store(root, ("full",))
        _score(root, [(RUN, "poetry", "fast"), (RUN, query.MACRO, "fast", note)])
        assert Store(root).subsets("wsb", MODEL) == [CORE, "full", want]
        assert set(Store(root).derived_runs("wsb", MODEL, want)) == {RUN}
    # the stamp of a set row (what ingest records for a judged fast run) is read the same way
    root = tmp_path / "set-note"
    _store(root, ("fast",))
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO run_set VALUES (?,?,?,?,?)", (RUN, "fast", 0, "judged", "scored on fast-v3")
    )
    cat.commit()
    cat.close()
    assert Store(root).subsets("wsb", MODEL) == [EARLIER]
    # no stamp and current evals, but the store's question list is another subset's
    root = tmp_path / "members"
    _store(root, ("fast",))
    assert Store(root).subsets("wsb", MODEL) == ["fast"]
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO subset_item VALUES ('wsb', ?, 'fast', 'poetry', 'one-question')", (MODEL,)
    )
    cat.commit()
    cat.close()
    assert Store(root).subsets("wsb", MODEL) == [EARLIER]


def test_current_and_earlier_fast_sets_are_two_sets_side_by_side(tmp_path: Path):
    """One store, two runs under `fast`: one on the current subset, one on an earlier one.
    Each view holds its own run; a run with both sets (the earlier one stored under the
    subset it was judged on) lists both, each titled."""
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    root = tmp_path / "s"
    _store(root, ("full", "fast"))
    old = "wsb__toy-model__lens-b"
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO run (run_id, bench, lens, label, method, model, meta) VALUES (?,?,?,?,?,?,?)",
        (old, "wsb", "lens-b", "lens-b", "nla", MODEL, "{}"),
    )
    cat.commit()
    cat.close()
    _score(root, [(old, e, "fast") for e in ("poetry", OLD_ONLY)])
    _score(root, [(RUN, e, "fast-v3") for e in ("poetry", OLD_ONLY, "multilingual")])
    db = Store(root)
    assert db.subsets("wsb", MODEL) == [CORE, "full", "fast", EARLIER, "fast-v3"]
    assert {r for sc in db.scores("wsb", MODEL, "fast").values() for r in sc} == {RUN}
    assert {r for sc in db.scores("wsb", MODEL, EARLIER).values() for r in sc} == {old}
    assert {r for sc in db.scores("wsb", MODEL, "fast-v3").values() for r in sc} == {RUN}
    sets = {s["subset"]: s["title"] for s in db.run_sets(RUN)}
    assert sets == {
        "full": "Full",
        "fast": "Fast",
        "fast-v3": "Fast subset (fast-v3, an earlier fast subset of 3 evals)",
    }
    client = TestClient(create_app(root))
    home = client.get("/").text
    for title in (
        ">Fast</option>",
        ">Earlier fast subset (2 evals)</option>",
        ">Fast subset (fast-v3, an earlier fast subset of 3 evals)</option>",
    ):
        assert title in home, title
    page = client.get(f"/?subset={EARLIER}").text
    assert "<b>Earlier fast subset (2 evals)</b> set" in page and "an earlier fast subset" in page
    assert "<b>Fast</b> set" in client.get("/?subset=fast").text
    assert "<b>Fast subset (fast-v3" in client.get("/?subset=fast-v3").text
    runs = client.get("/runs").text
    row = next(r for r in runs.split("<tr>") if ">lens-b</a>" in r)
    assert "Earlier fast subset (2 evals)" in row and ">Fast<" not in row
    # a store whose fast rows are all an earlier subset's: a link to the fast set shows them,
    # under their own title
    only = tmp_path / "only"
    _store(only, ("full",))
    _score(only, [(RUN, e, "fast") for e in ("poetry", OLD_ONLY)])
    text = TestClient(create_app(only)).get("/?subset=fast").text
    assert "<b>Earlier fast subset (2 evals)</b> set" in text and "<b>Fast</b> set" not in text


def test_fast_with_safety_is_shown_where_stored_and_never_derived_anew(tmp_path: Path, monkeypatch):
    """The fast variant with the two safety evals is gone from the benchmark: a store that
    holds it shows it, titled as an earlier fast subset; ingest derives it for no new run."""
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app
    from wsbench.viewer.ingest import reader, wsb

    assert "safety" not in fast.VARIANTS and "safety" in wsb.FAST_SUBSETS
    root = tmp_path / "s"
    _store(root, ("full", "fast-safety"))
    db = Store(root)
    assert db.subsets("wsb", MODEL) == [CORE, "full", "fast-safety"]
    title = db.title("wsb", MODEL, "fast-safety")
    assert title == f"Fast with safety (an earlier fast subset, {len(EVALS)} evals)"
    client = TestClient(create_app(root))
    assert f">{title}</option>" in client.get("/").text
    page = client.get("/?subset=fast-safety").text
    assert f"<b>{title}</b> set" in page and "no longer has this variant" in page
    # a new ingest of a full run derives the selectable fast subsets only
    derived: list[str] = []
    monkeypatch.setattr(wsb, "_write_fast", lambda *a: derived.append(a[6]))
    cat = store.catalog(tmp_path / "new")
    wsb.write_fast_scores(cat, RUN, wsb.ORIGINAL, {})
    cat.close()
    assert derived == ["fast"]
    # the manifest's documented set names: the README's table offers no fast-with-safety set
    readme = (Path(reader.__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith("| `set` |"))
    assert "`fast`" in row and "safety" not in row


def test_runs_page_lists_every_run_with_dashes_for_missing_facts(tmp_path: Path):
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app import pages
    from wsbench.viewer.app.main import create_app

    root = tmp_path / "s"
    _store(root, ("full", "fast"))
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO run (run_id, bench, lens, label, method, model, meta) VALUES (?,?,?,?,?,?,?)",
        (
            "wsb__toy-model__cont__r1",
            "wsb",
            "cont",
            "Continuation run",
            "continuation",
            MODEL,
            "{}",
        ),
    )
    cat.execute(
        "INSERT INTO run_set (run_id, subset, derived, origin, note) VALUES (?,?,?,?,?)",
        (RUN, "fast", 1, "full run", "cut from the full run"),
    )
    cat.commit()
    cat.close()
    _facts(root, "wsb__toy-model__cont__r1", set_name="fast", engine="sglang", cells=59790,
           read_gpu_hours=1.09, read_wall_seconds=414.3, judge_calls=5877, judge_usd=211.65,
           judge_wall_seconds=0.0, bench_commit="3378be28 (a branch)", integrity="incomplete",
           integrity_reason="one eval incomplete")  # fmt: skip
    text = TestClient(create_app(root)).get("/runs").text
    assert ">Runs</a>" in text and "GPU-hours to read" in text
    row = next(r for r in text.split("<tr>") if "Continuation run" in r)
    for want in ("59,790", "1.09", "6 min 54 s", "5,877", "$212", "<code>3378be28</code>",
                 "incomplete", "one eval incomplete", "sglang", "mc-continuation",
                 ">r1<"):  # fmt: skip
        assert want in row, want
    assert 'data-v="0.0">0 s' in row  # a measured zero is a number
    assert row.count('class="num none"') == 2  # total cost, total wall-clock: not in the files
    old = next(r for r in text.split("<tr>") if ">lens-a</a>" in r)
    assert old.count('class="num none"') == 8  # a run without facts: a dash in every fact
    assert "derived from the full run" in old and "0" not in re.sub(r"<[^>]+>", "", old)
    assert pages.duration(None) == "—" and pages.duration(8940) == "2 h 29 min"


def test_hallucinationbench_index_rows_are_shown_as_stored(tmp_path: Path):
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    root = tmp_path / "s"
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO eval (bench, model, eval, title, grp, ord, n_items) VALUES"
        " ('hb', ?, 'main', 'Chat (main)', 'Claim map', 0, 5)",
        (MODEL,),
    )
    cat.execute(
        "INSERT INTO run (run_id, bench, lens, label, method, model, meta) VALUES (?,?,?,?,?,?,?)",
        ("hb__r", "hb", "lens-a", "lens-a", "olens", MODEL, "{}"),
    )
    cat.execute("INSERT INTO score VALUES ('hb__r','main','full',-1,'lens',0.2,0.1,0.3,9,NULL)")
    joint = store.JOINT_LAYER
    rows = [(20, "main", "family", 0.111), (44, "main", "family", 0.222),
            (joint, "main", "family", 0.333), (44, "index", "macro", 0.444)]  # fmt: skip
    cat.executemany(
        "INSERT INTO hb_index (run_id, layer, key, kind, value, ci_lo, ci_hi, n, n_items)"
        " VALUES ('hb__r',?,?,?,?,0.1,0.5,100,5)",
        rows,
    )
    cat.commit()
    cat.close()
    client = TestClient(create_app(root))
    home = client.get("/?bench=hb").text
    for want in ("Index rows", "joint (all layers)", "11.1%", "22.2%", "33.3%", "44.4%",
                 "index (macro)", "No index rows in this store for", "Sibling substitution",
                 "Claude judge and a probe"):  # fmt: skip
        assert want in home, want
    page = client.get("/eval/main?bench=hb").text
    assert "joint (all layers)" in page and "33.3%" in page and "<td>L44</td>" in page
    assert "44.4%" not in page  # the eval page shows its own family


def test_one_colour_per_method_and_runs_of_a_method_differ_by_shade_or_dash():
    assert list(meta.METHODS) == ["olens", "nla", "jlens", "logit_lens", "continuation", "other"]
    colours = [c for _t, _a, c in meta.METHODS.values()]
    assert len(set(colours)) == len(colours)
    assert len({a for _t, a, _c in meta.METHODS.values()}) == len(meta.METHODS)  # aliases
    assert meta.method_key("something new") == "other" and meta.method_key(None) == "other"
    methods = ["olens", "nla", "olens", "olens", "jlens", "olens"]
    runs = [{"run_id": f"r{n}", "method": m} for n, m in enumerate(methods)]
    st = meta.run_styles(runs)
    for r in runs:  # every run keeps its method's hue as the base
        assert st[r["run_id"]]["base"] == meta.method_color(r["method"])
    assert st["r0"]["color"] == meta.method_color("olens") and st["r0"]["dash"] == ""
    same = [(st[i]["color"], st[i]["dash"]) for i in ("r0", "r2", "r3", "r5")]
    assert len(set(same)) == 4  # four O-lens runs: four distinct shade + dash pairs
    assert st["r1"]["color"] == meta.method_color("nla")  # the first run of another method
    css = meta.palette_css()
    for key, (_t, _a, colour) in meta.METHODS.items():
        assert f"--m-{key}:{colour};" in css  # the stylesheet takes each colour from the table
    static = Path(meta.__file__).parent / "static"
    for name in ("app.css", "grid.js"):  # and no method colour is written a second time
        text = (static / name).read_text(encoding="utf-8").lower()
        hues = [c for k, (_t, _a, c) in meta.METHODS.items() if k != "other"]  # grey = page ink
        assert not any(colour in text for colour in hues), name


def test_leaf_table_covers_the_taxonomy():
    assert list(meta.HB_VERDICTS) == [
        "hallucination", "probe_candidate", "thinky", "correct", "unresolved", "junk", "failed"
    ]  # fmt: skip
    table = meta.HB_LEAF_VERDICT
    assert table["continuation_miss"] == "unresolved" and table["failed"] == "failed"
    assert {k for k, v in table.items() if v == "hallucination"} == {
        "detail", "false_claim", "substitution_category"
    }  # fmt: skip
    assert {k for k, v in table.items() if v == "probe_candidate"} == {
        "substitution_sibling", "supplementary_false", "ambiguous_topic"
    }  # fmt: skip
    assert set(meta.HB_MAIN_LEAF_WEIGHTS) <= set(table)
    assert sum(meta.HB_FAMILY_WEIGHTS.values()) == 20 and set(meta.HB_FAMILY_WEIGHTS) == set(
        meta.HB_EVALS
    )
    shades = [leaf["color"] for leaf in meta.hb_leaves()]
    assert len(set(shades)) == len(shades) == len(table)  # one shade per leaf
    css = meta.palette_css()
    assert all(f".leaf-{leaf}{{" in css for leaf in table)


def test_leaf_table_covers_every_leaf_a_store_holds(tmp_path: Path):
    """The toy store here; set ``WSB_VIEWER_TEST_STORE`` to check a real store too."""
    import json

    from wsbench.viewer.ingest import hb

    lens_dir = tmp_path / "hb" / "lens-a"
    seg = {"readout": 0, "status": "ok", "why": "w", "unit": "R0.U1"}
    leaves = ("false_claim", "correct", "junk", "continuation_miss", "unverifiable")
    cell = {
        "key": "it-0__L020__p5", "id": "it-0", "layer": 20, "pos": 5, "samples": ["x" * 40],
        "stages": {"map": "ok"},
        "map": {"segments": [seg | {"start": 5 * n, "end": 5 * n + 5, "leaf": leaf}
                             for n, leaf in enumerate(leaves)]},
    }  # fmt: skip
    path = lens_dir / "wsbench_chat" / hb.JUDGE / "lens-a" / "cells.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cell) + "\n", encoding="utf-8")
    idx = lens_dir / "index" / hb.JUDGE
    idx.mkdir(parents=True)
    row = {"method": "lens-a", "layer": 20, "families": {"main": {"v": 0.2, "n": 4, "n_items": 1}}}
    (idx / "index.json").write_text(json.dumps({"rows": [row]}))
    hb.ingest(lens_dir, tmp_path / "store")
    held = Store(tmp_path / "store").hb_leaves()
    assert held == set(leaves) and held <= set(meta.HB_LEAF_VERDICT)
    real = os.environ.get("WSB_VIEWER_TEST_STORE")
    if real:
        missing = Store(Path(real)).hb_leaves() - set(meta.HB_LEAF_VERDICT)
        assert not missing, f"leaves with no verdict in meta.HB_VERDICTS: {sorted(missing)}"


def test_pages_show_categories_scoring_and_the_hallucinationbench_tables(
    tmp_path: Path, monkeypatch
):
    pytest.importorskip("fasthtml")
    monkeypatch.setattr(query, "also_in", dict)  # a benchmark without second listings
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    root = tmp_path / "s"
    _store(root, ("full", "fast"))
    cat = store.catalog(root)
    cat.execute(
        "INSERT INTO eval (bench, model, eval, title, grp, ord, n_items, what) VALUES"
        " ('hb', ?, 'main', 'Chat (main)', 'Claim map', 0, 5, 'what it tests')",
        (MODEL,),
    )
    for layer, value in ((-1, 0.2), (20, 0.3), (44, 0.1)):
        cat.execute(
            "INSERT INTO score VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("hb__run", "main", "full", layer, "lens", value, 0.1, 0.4, 7, None),
        )
    cat.execute(
        "INSERT INTO run (run_id, bench, lens, label, method, model, meta) VALUES (?,?,?,?,?,?,?)",
        ("hb__run", "hb", "lens-a", "lens-a", "olens", MODEL, "{}"),
    )
    cat.commit()
    cat.close()
    _facts(root, "hb__run", integrity="partial", integrity_reason="one family judged")
    client = TestClient(create_app(root))
    home = client.get("/").text  # the core set: the default
    assert "derived from the full run" in home and "rule (regex)" not in home
    full = client.get("/?subset=full").text
    assert "also listed under" not in full
    assert "rule (regex)" in full and "Claude judge" in full and "Scored by" in full
    assert "first pass through the Claude summarizer" in full
    assert full.count("Role_Bound_Association</a>") == 2  # one table row and one side link
    # with the benchmark's table, the second category lists the eval too, marked
    monkeypatch.setattr(query, "also_in", lambda: {"association": ("role_bound_association",)})
    both = client.get("/?subset=full").text
    assert "also listed under Anti-bag-of-features" in both
    assert both.count("Role_Bound_Association</a>") == 4  # two table rows and two side links
    monkeypatch.setattr(query, "also_in", dict)
    one = client.get("/?subset=full&cat=association").text
    assert "Role_Bound_Association" in one and ">Poetry</a><small" not in one
    assert "derived from the full run" not in client.get("/?subset=fast").text
    page = client.get("/eval/multilingual?subset=full").text
    assert "Scored by: <b>rule (regex)</b>" in page
    assert "first pass through the Claude summarizer" in page
    hb_home = client.get("/?bench=hb").text
    for text in ("Families of the index", "9 of 20", "Sibling substitution",
                 "no data in this store", "Taxonomy of the claim map", "Probe candidate",
                 "Excused continuation", "partial", "one family judged"):  # fmt: skip
        assert text in hb_home, text
    hb_eval = client.get("/eval/main?bench=hb").text
    assert "Index rows per layer" in hb_eval and "<td>L20</td>" in hb_eval and "L44" in hb_eval


def test_runs_page_shows_the_runs_own_timing_note_with_its_numbers(tmp_path: Path):
    pytest.importorskip("fasthtml")
    from starlette.testclient import TestClient

    from wsbench.viewer.app.main import create_app

    root = tmp_path / "s"
    _store(root, ("full",))
    note = "judge wall-clock is shared by three methods; the cost is an upper bound"
    _facts(root, RUN, set_name="full", cells=10, judge_wall_seconds=14880.0, judge_usd=3399.0,
           entry=store.dumps({"timing_note": note}))  # fmt: skip
    assert Store(root).run_facts(RUN)["timing_note"] == note
    text = TestClient(create_app(root)).get("/runs").text
    row = next(r for r in text.split("<tr>") if ">lens-a</a>" in r)
    # the manifest's words, as given, on every number of the row; none on the dashes
    assert row.count(f'title="{note}"') == 3
    for want in ("4 h 08 min", "$3,399", 'class="num noted" data-v="10"'):
        assert want in row, want
    assert 'class="num none" data-v="" title' not in row
