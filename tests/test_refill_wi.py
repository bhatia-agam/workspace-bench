"""wrong_intermediate refill (plan 0066 §5, §10 WI, §11.2 / §11.5): multi-dir pools, the hub share
over the union, the entity-kind check, per-item categories, the admitted templates."""

import hashlib
import json
from pathlib import Path

import pytest
from test_adapt_phase_e import MODEL, WBRunner, _ent, _no_fetch, _pool

from wsbench.adapt import refill, store
from wsbench.adapt import wrong_intermediate as wb
from wsbench.evals.wrong_intermediate.judge import ROLE_CUES


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    return tmp_path / MODEL


@pytest.fixture(autouse=True)
def _clean_item_categories(monkeypatch):
    monkeypatch.setattr(wb, "ADAPT_ITEM_CATEGORY", {})


def _claims(**props):
    """Pool-shaped claims: {P31: [Q..], P106: [...], P39: [...]}."""
    return {
        p: [{"rank": "normal", "mainsnak": {"datavalue": {"type": "wikibase-entityid",
                                                          "value": {"id": q}}}} for q in qs]
        for p, qs in props.items()
    }  # fmt: skip


def _e(label, **props):
    return {"labels": {"en": {"value": label}}, "aliases": {}, "claims": _claims(**props),
            "sitelinks_n": 20}  # fmt: skip


# a synthetic frozen class table (the real one is vendored by scripts/build_wd_tables.py)
# parentless classes are keys with [] (the build keeps them): "absent" means "never seen"
_LEAF_IDS = {"Q5", "Q7275", "Q1048835", "Q42603", "Q116", "Q82955", "Q1028181", "Q2526255",
             "Q482980"}  # fmt: skip
LEAVES: dict[str, list[str]] = {
    q: []
    for q in sorted(
        {q for v in wb.CATEGORY_P31.values() for q in v}
        | {q for v in wb.OCCUPATION_ROOTS.values() for q in v}
        | set(wb.GROUP_P31)
        | _LEAF_IDS
    )
}
PARENTS = {
    **LEAVES,
    "Qcarmaker": ["Q13235160"],  # -> manufacturer
    "Qindie_label": ["Q18127"],  # -> record label
    "Qcable_net": ["Q1254874"],  # -> television network
    "Q3624078": ["Q7275"],  # sovereign state -> state
    "Q6256": ["Q1048835"],  # country -> political territorial entity
    "Qtwo_up": ["Qone_up"],
    "Qone_up": ["Q783794"],  # two steps from company: beyond P31_STEPS
    "Q6625963": ["Q36180"],  # novelist -> writer
    "Q488205": ["Q177220", "Q753110"],  # singer-songwriter -> singer, songwriter
    "Q177220": ["Q639669"],  # singer -> musician
    "Q753110": ["Q482980", "Q36834"],  # songwriter -> author, composer
    "Q36834": ["Q639669", "Q482980"],  # composer -> musician, author
    "Q169470": ["Q901"],  # physicist -> scientist (a scholar root)
    "Qparticle_theorist": ["Qtheorist"],
    "Qtheorist": ["Q169470"],  # 3 steps to scientist
    "Qfar1": ["Qfar2"],
    "Qfar2": ["Qfar3"],
    "Qfar3": ["Qfar4"],
    "Qfar4": ["Q36180"],  # 4 steps to writer: beyond OCC_STEPS
}


# ---------------------------------------------------------------------------- unchanged rules
def test_unchanged_rules_and_constants():
    assert wb.MIN_SAMPLE_AGREE == 4
    assert wb.HUB_FRAC == 0.03
    assert (wb.PER_TEMPLATE, wb.PER_BRIDGE) == (20, 4)
    assert (wb.DRAWS, wb.TEMPERATURE, wb.MAX_NEW) == (10, 0.7, 24)
    assert (wb.N_DISTRACTORS, wb.MC_SEED) == (4, "wb-mc-adapt-2026-11-02")
    # the registered adjudication prompt, byte for byte
    sha = hashlib.sha256(wb.ADJ_SYS.encode()).hexdigest()
    assert sha == "c0e2bd996c8d1fc3264eb9b0252cb633436d82cbdba8264a5acf276860f33545"
    # E1 / consistency / logP checks: the same hard checks
    c = {
        "id": "x", "vkind": "year", "hop2": "birth_year", "answer": {"value": 1931},
        "Bp_answer": 1946, "Bp_label": "Steven Spielberg", "Bp_names": ["Steven Spielberg"],
        "B_label": "Jan Kowalczyk", "B_aliases": [],
        "prompt_2hop": "Fact: The director of the 1975 film Jawz was born in the year",
        "prompt_hop1": "Fact: The 1975 film Jawz was directed by",
    }  # fmt: skip
    outs = {"p2": (" 1946.", [" 1946."] * 10), "p1": (" Spielberg.", [" Spielberg."] * 10),
            "injBp": " 1946.", "injB": " 1931.", "p2bp": " 1946."}  # fmt: skip
    checks = wb._gate_legs(c, outs, {})[2]
    assert set(checks) == {
        "greedy_Ap", "greedy_Bp", "not_default_answer", "samples_Ap", "samples_Bp", "inject_Bp",
        "inject_B", "hop2_Bp", "not_credited", "lp_A", "lp_B",
    }  # fmt: skip
    assert not checks["lp_A"] and not checks["lp_B"]  # no cont_logprobs: fails, never skipped
    assert refill.POLICY[refill.WI].n_min == 200_000 and refill.POLICY[refill.WI].y_min == 5e-5


# ---------------------------------------------------------------------------- multi-dir pools
def _write_pool(d, cands, ents):
    d.mkdir(parents=True)
    (d / "candidates.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cands))
    (d / "entities.json").write_text(json.dumps(ents))


def test_multi_pool_merge_first_dir_wins_and_counts_differing_copies(tmp_path):
    r1, r2 = tmp_path / "r1", tmp_path / "r2"
    _write_pool(r1, [{"id": "a", "S_label": "old"}, {"id": "b", "leak": True}],
                {"Q1": _e("Old label"), "Q2": _e("Same")})  # fmt: skip
    _write_pool(r2, [{"id": "a", "S_label": "drifted"}, {"id": "b", "leak": True},
                     {"id": "c"}, {"id": "b2", "leak": False}],
                {"Q1": _e("New label"), "Q2": _e("Same"), "Q3": _e("Fresh")})  # fmt: skip
    cands, ents, stats = wb.merge_pools(f"{r1},{r2}")
    assert [c["id"] for c in cands] == ["a", "b", "c", "b2"]
    assert cands[0]["S_label"] == "old"  # round 1's row wins for its id
    assert wb.label(ents["Q1"]) == "Old label" and "Q3" in ents
    assert stats == {"cand_differ": 1, "cand_same": 1, "ent_differ": 1, "ent_same": 1}
    got, ents2 = wb.load_pool(f" {r1} , {r2} ")  # spaces tolerated; leaks dropped after merge
    assert [c["id"] for c in got] == ["a", "c", "b2"] and ents2 == ents
    assert [c["id"] for c in wb.load_pool(str(r1))[0]] == ["a"]  # one dir: as before
    assert [c["id"] for c in wb.load_pool(f"{r1},{r2}", limit=2)[0]] == ["a", "c"]
    with pytest.raises(SystemExit, match=r"no entities\.json"):
        (tmp_path / "bare").mkdir()
        (tmp_path / "bare" / "candidates.jsonl").write_text("")
        wb.load_pool(f"{r1},{tmp_path / 'bare'}")


# ---------------------------------------------------------------------------- hub share
def _hub_cand(i, year):
    return {
        "id": f"film_director.QS{i}.QB{i}.birth_year", "template": "film_director",
        "hop2": "birth_year", "vkind": "year", "S": f"QS{i}", "S_label": f"Film {i}",
        "S_year": 1900, "B": f"QB{i}", "B_label": f"Director {i}", "B_aliases": [],
        "B_kind": "human", "answer": {"value": year, "names": [str(year)]},
        "prompt_2hop": f"Fact: The director of the 1900 film Film {i} was born in the year",
        "prompt_hop1": f"Fact: The 1900 film Film {i} was directed by",
        "prompt_hop2_true": f"Fact: Director {i} was born in the year", "leak": False,
    }  # fmt: skip


def test_hub_share_over_the_union_and_flips_reported(tmp_store, tmp_path):
    e1c = _hub_cand(0, 1931)  # the E1 candidate: answers Spielberg's 1946
    ents = {"Q8877": _ent("Steven Spielberg", occ="Q2526255", P569=1946),
            "QB0": _ent("Director 0", P569=1931)}  # fmt: skip
    r1_fill = [_hub_cand(i, 1800) for i in range(1, 40)]  # answer 1800 (right): no hub
    r2_fill = [_hub_cand(i, 1700) for i in range(40, 80)]  # answer 1946 with another p1: hub
    _write_pool(tmp_path / "r1", [e1c, *r1_fill], ents)
    _write_pool(tmp_path / "r2", r2_fill, {})
    screen = []
    for c in [e1c, *r1_fill, *r2_fill]:
        k = wb.keys_for(c)
        p2 = " 1946." if c in (e1c, *r2_fill) else " 1800."
        p1 = " Steven Spielberg." if c is e1c else " John Doe."
        screen += [{"key": k["p2"], "greedy": p2}, {"key": k["p1"], "greedy": p1},
                   {"key": k["p2b"], "greedy": f" {c['answer']['value']}."}]  # fmt: skip
    wd = wb.work_dir(MODEL)
    wd.mkdir(parents=True)
    (wd / "screen.jsonl").write_text("".join(json.dumps(r) + "\n" for r in screen))

    (e1,) = wb.grade(MODEL, str(tmp_path / "r1"))
    assert e1["id"] == e1c["id"] and e1["answer_hub_share"] == 0.0
    assert not (wd / "hub_flips.json").exists()  # first grade: nothing to compare against
    (e1u,) = wb.grade(MODEL, f"{tmp_path / 'r1'},{tmp_path / 'r2'}")
    # 40 other prompts of the template give 1946 with another bridge: 40 / 80 screened
    assert e1u["answer_hub_share"] == pytest.approx(40 / 80)
    (run1,) = json.loads((wd / "hub_flips.json").read_text())
    flips = run1["flips"]
    assert flips == [{"id": e1c["id"], "was_hub": False, "now_hub": True, "old_share": 0.0,
                      "new_share": 0.5}]  # fmt: skip
    assert run1["at"] and run1["wave"] is None
    # a later regrade with no flips appends; it never overwrites the first run's diff
    wb.grade(MODEL, f"{tmp_path / 'r1'},{tmp_path / 'r2'}", wave=3)
    runs = json.loads((wd / "hub_flips.json").read_text())
    assert [r["flips"] for r in runs] == [flips, []] and runs[1]["wave"] == 3
    assert wb.hub_flips([e1u], [e1]) == [{**flips[0], "was_hub": True, "now_hub": False,
                                          "old_share": 0.5, "new_share": 0.0}]  # fmt: skip


def test_record_hub_flips_wraps_a_legacy_bare_list(tmp_store):
    wd = wb.work_dir(MODEL)
    wd.mkdir(parents=True)
    legacy = [{"id": "x", "was_hub": False, "now_hub": True, "old_share": 0.0, "new_share": 0.5}]
    (wd / "hub_flips.json").write_text(json.dumps(legacy))
    runs = wb.record_hub_flips(MODEL, [], wave=1)
    assert runs[0]["flips"] == legacy and runs[0]["at"] is None
    assert runs[1]["flips"] == [] and runs[1]["wave"] == 1
    assert json.loads((wd / "hub_flips.json").read_text()) == runs


# ---------------------------------------------------------------------------- entity-kind check
def test_entity_allowlist_by_kind_via_the_class_table():
    def ok(cat, **props):
        return wb.kind_ok(cat, wb.entity_facts(_e("x", **props)), PARENTS)

    # the audit's F3: the Soviet Union shipped as a manufacturer
    assert not ok("company", P31=["Q3624078", "Q6256"])
    assert ok("company", P31=["Qcarmaker"])  # a manufacturer, one step through the table
    assert ok("company", P31=["Qindie_label"])  # a record label
    assert ok("company", P31=["Qcable_net"])  # a television network
    assert ok("company", P31=["Q783794"]) and ok("company", P31=["Q936518"])
    assert not ok("company", P31=["Qtwo_up"])  # two P279 steps: beyond P31_STEPS
    assert not ok("company", P31=["Q5"])
    assert ok("band", P31=["Q5741069"]) and not ok("band", P31=["Q5"])
    for cat in wb.PERSON_CATEGORIES:  # occupations are not required for the check
        assert ok(cat, P31=["Q5"]) and not ok(cat, P31=["Q783794"])
    assert not ok("no_such_category", P31=["Q5"])
    assert wb.CATEGORY_P31["band"] == wb.GROUP_P31
    # the group set is bridge_kind's
    assert all(wb.bridge_kind(_e("g", P31=[q])) == "group" for q in wb.GROUP_P31)


def test_parentless_class_is_handled_and_a_missing_class_is_loud():
    table = {"Q5": [], "Qparentless_state": [], "Qcarmaker": ["Q13235160"]}
    state = wb.entity_facts(_e("x", P31=["Qparentless_state"]))
    assert not wb.kind_ok("company", state, table)  # present with [] : a decided "no"
    assert wb.item_category(state, {**table, **LEAVES}) is None
    assert wb.kind_ok("company", wb.entity_facts(_e("x", P31=["Qcarmaker"])), table)
    unseen = wb.entity_facts(_e("x", P31=["Qunseen1", "Qunseen2"]))
    with pytest.raises(SystemExit, match=r"Qunseen1.*Qunseen2.*build_wd_tables"):
        wb.kind_ok("company", unseen, table)
    # a direct hit needs no lookup; the occupation walk is loud on an unseen class too
    assert wb.kind_ok("writer", wb.entity_facts(_e("x", P31=["Q5", "Qunseen1"])), table)
    with pytest.raises(SystemExit, match="Qunseen_occ"):
        wb.item_category(wb.entity_facts(_e("x", P31=["Q5"], P106=["Qunseen_occ"])), table)
    it = {"name": "product_manufacturer-Q1-founded_year", "template": "product_manufacturer",
          "intermediates": ["X"], "mc": {"category": "company"},
          "wikidata": {"B_prime": "Q77"}}  # fmt: skip
    with pytest.raises(SystemExit, match="Qunseen1"):
        wb.entity_kind_failures([it], {"Q77": _e("X", P31=["Qunseen1"])}, table)


def test_build_wd_tables_extra_sources_exact_paths(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_wd_tables", Path(__file__).resolve().parents[1] / "scripts" / "build_wd_tables.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    adapted = tmp_path / "adapted"
    a = adapted / "m1" / "gate" / "wrong_bridge.work" / "entities_extra.json"
    b = adapted / "m2" / "gate" / "wrong_intermediate.work" / "entities_extra.json"
    for f in (a, b):
        f.parent.mkdir(parents=True)
        f.write_text("{}")
    (adapted / "m3" / "gate" / "wrong_bridge.work").mkdir(parents=True)  # no store: skipped
    r2 = tmp_path / "r2" / "entities.json"
    assert mod.extra_sources(adapted, r2) == [str(a), str(b)]
    assert "does not exist yet" in capsys.readouterr().out
    r2.parent.mkdir()
    r2.write_text("{}")
    assert mod.extra_sources(adapted, r2) == [str(a), str(b), str(r2)]


def test_missing_entity_or_empty_claims_is_loud():
    with pytest.raises(SystemExit, match="no entity"):
        wb.facts_of("Q404", {})
    with pytest.raises(SystemExit, match="empty claims"):
        wb.facts_of("Q404", {"Q404": {"labels": {}, "claims": {}}})
    it = {"name": "tv_network-Q1-founded_year", "template": "tv_network",
          "intermediates": ["X"], "wikidata": {"B_prime": "Q404"}}  # fmt: skip
    with pytest.raises(SystemExit):
        wb.entity_kind_failures([it], {}, PARENTS)


def test_entity_kind_failures_list_shipped_ids(tmp_store, tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "class_parents", lambda: PARENTS)
    items = [
        {"name": "product_manufacturer-Q1-founded_year", "template": "product_manufacturer",
         "intermediates": ["Soviet Union"], "mc": {"category": "company"},
         "wikidata": {"B_prime": "Q15180"}},
        {"name": "product_manufacturer-Q2-founded_year", "template": "product_manufacturer",
         "intermediates": ["Carco"], "mc": {"category": "company"},
         "wikidata": {"B_prime": "Q77"}},
    ]  # fmt: skip
    ents = {"Q15180": _e("Soviet Union", P31=["Q3624078", "Q6256"]),
            "Q77": _e("Carco", P31=["Qcarmaker"])}  # fmt: skip
    assert wb.entity_kind_failures(items, ents) == [("product_manufacturer-Q1-founded_year",
                                                     "company")]  # fmt: skip
    # the shipped-set lister reads the set and the pool's claims; it mutates nothing
    tmp_store.mkdir(parents=True)
    bank = tmp_store / "wrong_intermediate.json"
    bank.write_text(json.dumps({"version": 4, "items": items}))
    before = bank.read_text()
    _write_pool(tmp_path / "pool", [], ents)
    got = wb.shipped_entity_failures(MODEL, str(tmp_path / "pool"))
    assert got == [("product_manufacturer-Q1-founded_year", "company")]
    assert bank.read_text() == before


# ---------------------------------------------------------------------------- per-item category
def test_per_item_category_from_occupations_closure_and_priority():
    def cat(**props):
        return wb.item_category(wb.entity_facts(_e("x", **props)), PARENTS)

    assert cat(P31=["Q5"], P106=["Q6625963"]) == "writer"  # novelist -> writer
    assert cat(P31=["Q5"], P106=["Q488205"]) == "musician"  # singer-songwriter -> musician
    assert cat(P31=["Q5"], P106=["Q169470"]) == "scholar"  # physicist -> scientist
    assert cat(P31=["Q5"], P106=["Qparticle_theorist"]) == "scholar"  # 3 steps
    assert cat(P31=["Q5"], P106=["Qfar1"]) is None  # 4 steps: beyond the bounded closure
    # a composer is a musician one P279 step up: the nearest root decides
    assert cat(P31=["Q5"], P106=["Q36834"]) == "composer"
    # the fixed priority across occupations
    assert cat(P31=["Q5"], P106=["Q1028181", "Q6625963"]) == "writer"  # writer > painter
    assert cat(P31=["Q5"], P106=["Q36834", "Q177220"]) == "musician"  # musician > composer
    assert cat(P31=["Q5"], P106=["Q2526255", "Q169470"]) == "filmmaker"  # filmmaker > scholar
    assert cat(P31=["Q5"], P106=["Q169470", "Q82955"]) == "scholar"  # scholar > leader
    assert cat(P31=["Q5"], P106=["Q82955"]) == "historical_leader"  # politician
    # a human with no matching occupation: leader only with an office or a monarch occupation
    assert cat(P31=["Q5"], P106=["Q42603"], P39=["Q30461"]) == "historical_leader"
    assert cat(P31=["Q5"], P106=["Q116"]) == "historical_leader"
    assert cat(P31=["Q5"], P106=["Q42603"]) is None
    assert cat(P31=["Q5"]) is None
    # non-humans: company, band, or nothing
    assert cat(P31=["Qcarmaker"]) == "company"
    assert cat(P31=["Q5741069"]) == "band"
    assert cat(P31=["Q3624078", "Q6256"]) is None
    assert wb.CATEGORY_PRIORITY == ("musician", "composer", "writer", "painter", "filmmaker",
                                    "scholar", "historical_leader")  # fmt: skip


def test_mixed_items_get_a_category_from_their_bridge_or_none():
    b = wb.mc_builder()
    items = [
        {"name": "person_mother-Q9001-birth_year", "template": "person_mother",
         "intermediates": ["Ann Novel"], "wikidata": {"B_prime": "Q1"}},
        {"name": "namesake-Q9002-death_year", "template": "namesake",
         "intermediates": ["Some Priest"], "wikidata": {"B_prime": "Q2"}},
        {"name": "film_director-Q9003-birth_year", "template": "film_director",
         "intermediates": ["Dir"], "wikidata": {"B_prime": "Q404"}},  # not mixed: untouched
    ]  # fmt: skip
    ents = {"Q1": _e("Ann Novel", P31=["Q5"], P106=["Q6625963"]),
            "Q2": _e("Some Priest", P31=["Q5"], P106=["Q42603"])}  # fmt: skip
    assert wb.category_of(items[0]) is None  # before: no category (the builder drops it)
    assert b.category_of(items[0]) is None
    got = wb.assign_item_categories(items, ents, PARENTS)
    assert got == {"person_mother-Q9001-birth_year": "writer", "namesake-Q9002-death_year": None}
    assert wb.ADAPT_ITEM_CATEGORY == {"person_mother-Q9001-birth_year": "writer"}
    assert wb.category_of(items[0]) == "writer" and wb.category_of(items[1]) is None
    # the registered builder's tables are never edited
    assert "person_mother-Q9001-birth_year" not in b.ITEM_CATEGORY
    assert "person_mother" not in b.TEMPLATE_CATEGORY
    with pytest.raises(SystemExit, match="no entity"):
        wb.assign_item_categories([{**items[0], "wikidata": {"B_prime": "Q404"}}], ents, PARENTS)
    assert wb.assign_item_categories(
        [{**items[0], "wikidata": {"B_prime": "Q404"}}], ents, PARENTS, strict=False
    ) == {"person_mother-Q9001-birth_year": None}


def _gated_row(rid, s, bp, template, strength=8):
    e = {
        "id": rid, "S": s, "Bp": bp, "B": "Q9", "template": template, "hop2": "birth_year",
        "vkind": "year", "Bp_answer": 1946, "answer": {"value": 1931}, "Bp_label": f"X{bp}",
        "Bp_names": [f"X{bp}"], "B_label": "Y", "B_aliases": [], "prompt_2hop": "p",
    }  # fmt: skip
    ev = {"p2_samples_Ap": strength, "p1_samples_Bp": 10, "lp_Ap_minus_A": 1.0}
    return {"id": rid, "e1": e, "evidence": ev, "gate": {"pass": True}}


def _bank_fixture(tmp_path, gated, ents):
    wd = wb.work_dir(MODEL)
    wd.mkdir(parents=True)
    (wd / "gated.jsonl").write_text("".join(json.dumps(r) + "\n" for r in gated))
    (wd / "adjudicated.jsonl").write_text(
        "".join(json.dumps({"id": r["id"], "clean": True}) + "\n" for r in gated)
    )
    _write_pool(tmp_path / "pool", [], ents)
    return str(tmp_path / "pool")


def test_bank_kind_check_drops_and_assigns_mixed_categories(tmp_store, tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "class_parents", lambda: PARENTS)
    gated = [
        _gated_row("su", "Q1", "Q15180", "product_manufacturer", 10),  # strongest, a country
        _gated_row("car", "Q2", "Q77", "product_manufacturer", 9),
        _gated_row("mom", "Q3", "Q88", "person_mother", 8),
        _gated_row("mom2", "Q4", "Q89", "person_mother", 7),  # a priest: no category
        _gated_row("scr", "Q5", "Q90", "film_screenwriter", 6),  # not admitted in this PR
    ]
    ents = {"Q15180": _e("Soviet Union", P31=["Q3624078", "Q6256"]),
            "Q77": _e("Carco", P31=["Qcarmaker"]),
            "Q88": _e("Ann Novel", P31=["Q5"], P106=["Q6625963"]),
            "Q89": _e("Some Priest", P31=["Q5"], P106=["Q42603"]),
            "Q90": _e("Scribe", P31=["Q5"], P106=["Q28389"])}  # fmt: skip
    pool = _bank_fixture(tmp_path, gated, ents)
    seen = {}

    def make_mc(item, opts, wd, topic, kinds=None):
        cat = wb.category_of(item)
        seen[item["template"]] = cat
        return None if cat is None else {"gold": item["intermediates"][0], "category": cat}

    rows = wb.bank(MODEL, pool, registered=[], wd={}, r4={}, fetch=_no_fetch, make_mc=make_mc,
                   kind_check=True)  # fmt: skip
    why = {r["item"]["wikidata"]["B_prime"]: r["gate"].get("drop") for r in rows}
    assert why["Q15180"] == wb.ENTITY_KIND_DROP and why["Q15180"].startswith("entity-kind")
    assert why["Q77"] is None and why["Q88"] is None
    assert why["Q89"].startswith("no mc") and why["Q90"].startswith("no mc")
    assert seen["person_mother"] in ("writer", None)  # the last person_mother row: the priest
    mom = next(r for r in rows if r["item"]["wikidata"]["B_prime"] == "Q88")
    assert mom["item"]["mc"]["category"] == "writer"
    # without the check (a direct call's default) the country still ships: the old behaviour
    wb.work_dir(MODEL).joinpath("gated.jsonl").write_text(json.dumps(gated[0]) + "\n")
    rows = wb.bank(MODEL, pool, registered=[], wd={}, r4={}, fetch=_no_fetch, make_mc=make_mc)
    assert rows[0]["gate"]["pass"]
    # a B' the claim stores lack stops the checked stage
    bad = _gated_row("ghost", "Q6", "Q404", "product_manufacturer")
    wb.work_dir(MODEL).joinpath("gated.jsonl").write_text(json.dumps(bad) + "\n")
    wb.work_dir(MODEL).joinpath("adjudicated.jsonl").write_text(
        json.dumps({"id": "ghost", "clean": True}) + "\n"
    )
    with pytest.raises(SystemExit, match="Q404"):
        wb.bank(MODEL, pool, registered=[], wd={}, r4={}, fetch=_no_fetch, make_mc=make_mc,
                kind_check=True)  # fmt: skip


def test_claims_come_from_entities_extra_not_wikidata_extra(tmp_store, tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "class_parents", lambda: PARENTS)
    gated = [_gated_row("car", "Q2", "Q77", "product_manufacturer")]
    pool = _bank_fixture(tmp_path, gated, {})
    wd = wb.work_dir(MODEL)
    # labels-only cache: never a claim source
    (wd / "wikidata_extra.json").write_text(json.dumps({"entities": {"Q77": {"labels": {}}}}))
    kw = {"registered": [], "wd": {}, "r4": {}, "fetch": _no_fetch, "kind_check": True,
          "make_mc": lambda item, *a, **k: {"gold": item["intermediates"][0]}}  # fmt: skip
    with pytest.raises(SystemExit, match="Q77"):
        wb.bank(MODEL, pool, **kw)
    (wd / "entities_extra.json").write_text(json.dumps({"Q77": _e("Carco", P31=["Qcarmaker"])}))
    assert wb.bank(MODEL, pool, **kw)[0]["gate"]["pass"]


# ---------------------------------------------------------------------------- admitted templates
def test_no_new_template_in_this_pr_and_every_admitted_one_has_cues():
    assert wb.ADAPT_TEMPLATE_CATEGORY == {}
    admitted = wb.admitted_templates()
    assert admitted and all(t in ROLE_CUES for t in admitted)
    assert {"person_mother", "namesake"} <= set(admitted)
    for t in ("film_screenwriter", "song_composer", "tv_creator", "novel_publisher",
              "building_architect", "film_producer", "aircraft_manufacturer"):  # fmt: skip
        assert t not in admitted and wb.category_of(t) is None
    assert wb.category_of("film_director") == "filmmaker"
    # a cue-less template never gets a category, even through an item table
    it = {"name": "film_screenwriter-Q1-birth_year", "template": "film_screenwriter",
          "intermediates": ["X"]}  # fmt: skip
    assert wb.category_of(it, {"film_screenwriter-Q1-birth_year": "filmmaker"}) is None


def test_every_template_in_a_shipped_set_has_role_cues():
    sets = sorted((store.REPO_ROOT / "adapted").glob(f"*/{wb.FAMILY}.json"))
    for path in sets:
        _h, items = store.load_wrapped(path)
        assert {it["template"] for it in items} <= set(ROLE_CUES), path


# ---------------------------------------------------------------------------- calibration
def test_registered_bprime_all_pass_their_category():
    if not (wb.CLASS_TABLE.exists() and wb.REGISTERED_BPRIME.exists()):
        pytest.skip("vendored Wikidata tables absent: run scripts/build_wd_tables.py (§11.2)")
    reg = wb.registered_bprime()
    _h, items = store.original_bank(wb.FAMILY)
    assert len(items) == 100
    fails = []
    for it in items:
        q = str(it["wikidata"]["B_prime"])
        assert q in reg, q
        if not wb.kind_ok(it["mc"]["category"], reg[q]):
            fails.append((it["name"], it["mc"]["category"], reg[q]["P31"]))
    assert not fails, fails
    # the audit's case: the Soviet Union (Q15180, its Wikidata P31 on 2026-11-04) is no company
    # under the real table, nor any other category's kind
    su = {
        "P31": [
            "Q113393649",
            "Q1323642",
            "Q1335818",
            "Q160016",
            "Q17007978",
            "Q3024240",
            "Q3624078",
            "Q512187",
            "Q6256",
            "Q6688521",
            "Q7275",
            "Q842112",
            "Q849866",
        ]
    }
    # the pool scrape predates 4 of these live classes: an unseen class is loud, never a drop
    table = wb.class_parents()
    unseen = sorted(q for q in su["P31"] if q not in table)
    assert unseen == ["Q113393649", "Q160016", "Q17007978", "Q6688521"]
    with pytest.raises(SystemExit, match=r"Q113393649.*rebuild the tables"):
        wb.kind_ok("company", su)
    seen = {"P31": [q for q in su["P31"] if q in table]}
    assert not any(wb.kind_ok(c, seen) for c in wb.CATEGORY_P31)
    assert wb.item_category({**seen, "P106": [], "P39": []}) is None


# ---------------------------------------------------------------------------- refill hooks
def test_refill_wave_and_prior_tally_over_the_merged_pool(tmp_store, tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "class_parents", lambda: {})  # every B' here is a human (Q5)
    pool, _reg, answers = _pool(tmp_path / "x")
    assert wb.prior_tally(MODEL) == (0, 0)
    assert refill.prior_tally(MODEL, refill.WI) == (0, 0)  # the driver uses the module hook

    def ask(system, user):
        return {"clean": True, "reason": "ok", "category": "clean"}

    runner = WBRunner(answers)
    res = wb.refill_wave(MODEL, wave=0, runner=runner, pool=str(pool), wave_size=1, ask=ask,
                         fetch=_no_fetch)  # fmt: skip
    assert res["tried"] == 1 and res["pool_size"] == 2 and res["pool_used"] == 1
    assert res["exhausted"] is False and res["landed"] == 1  # the registered Beethoven item
    assert res["claude_calls"] == 1
    res = wb.refill_wave(MODEL, wave=1, runner=runner, pool=str(pool), ask=ask, fetch=_no_fetch)
    assert res["tried"] == 1 and res["exhausted"] is True and res["landed"] == 1
    assert wb.prior_tally(MODEL) == (2, 2)
    monkeypatch.setenv(wb.REFILL_POOL_ENV, "/a,/b")
    assert wb.refill_pool() == "/a,/b" and wb.refill_pool("/c") == "/c"


def test_band_is_a_valid_musician_bprime_on_performer_templates_only():
    """Coordinator ruling 2026-11-04: on album_performer / song_performer the "musician" category
    accepts a musical group (Bad Religion on glm-5.3, Slayer on qwen3.5-4b), not only Q5; a band
    is still not a musician elsewhere, and a person still is."""
    band = {"P31": ["Q215380"], "P106": [], "P39": []}  # musical group
    ensemble = {"P31": ["Q2088357"], "P106": [], "P39": []}  # musical ensemble
    person = {"P31": ["Q5"], "P106": [], "P39": []}
    for tpl in ("album_performer", "song_performer"):
        assert wb.kind_ok("musician", band, LEAVES, template=tpl)
        assert wb.kind_ok("musician", ensemble, LEAVES, template=tpl)
        assert wb.kind_ok("musician", person, LEAVES, template=tpl)
    assert not wb.kind_ok("musician", band, LEAVES, template="song_lyricist")
    assert not wb.kind_ok("musician", band, LEAVES)
    assert not wb.kind_ok("composer", band, LEAVES, template="album_performer")
