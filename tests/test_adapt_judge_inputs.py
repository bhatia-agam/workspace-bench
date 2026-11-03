"""Plan 0060 A2.0: the judge-input audit table (``wsbench.adapt.judge_inputs``).

(i) every registered family has an entry, and a family registered without one fails;
(ii) every REGISTERED item passes ``check_item`` (the table describes the banks of record);
(iii) per family, an "adapted-only" fixture (a registered item with a new id) either passes
``check_item`` or is reported, and the cheap lookups behind the reports are pinned so a fixture
that passes takes the registered item's code path (no silent ``[]`` / default fallback);
(iv) the read plan of an adapted-only clone equals its original's under ``WSB_BANK_ROOT``."""

import copy
import json
import shutil

import pytest

from wsbench import readplan, registry
from wsbench.adapt import judge_inputs as ji

ALL = sorted(ji.FAMILIES)


def _bank(family):
    raw = json.loads(registry.frozen_bank_path(family).read_text(encoding="utf-8"))
    if family == "jlens_concept_pr":
        return {k: v for k, v in raw.items() if k != "prompts"}, raw["prompts"], raw
    if isinstance(raw, list):
        return None, raw, raw
    return {k: v for k, v in raw.items() if k != "items"}, raw["items"], raw


def _clone(family, item, suffix="-zz-adapted"):
    """The registered item with a new id (the shape of an adapted-only item)."""
    c = copy.deepcopy(item)
    key = ji.FAMILIES[family].id_key
    c[key] = f"{c[key]}{suffix}"
    if key == "name" and "id" in c:
        c["id"] = f"{c['id']}{suffix}"
    return c


# --------------------------------------------------------------------------- (i) coverage


def test_table_covers_every_registered_family(real_families):
    assert ji.uncovered_families() == []
    assert set(ji.FAMILIES) == set(real_families)


def test_a_new_family_without_an_entry_fails(real_families, monkeypatch):
    spec = next(iter(real_families.values()))
    import dataclasses

    monkeypatch.setitem(
        registry.FAMILIES, "brand_new_family", dataclasses.replace(spec, name="brand_new_family")
    )
    assert ji.uncovered_families() == ["brand_new_family"]
    with pytest.raises(KeyError):
        ji.check_item("brand_new_family", {"id": "x"})


@pytest.mark.parametrize("family", ALL)
def test_entry_is_well_formed_and_matches_the_bank_shape(family):
    fi = ji.FAMILIES[family]
    assert fi.family == family
    for x in fi.inputs:
        assert x.kind in ji.KINDS and x.absent in ji.ABSENT and x.cls in ji.CLASSES, x
        assert x.where, x
    raw = json.loads(registry.frozen_bank_path(family).read_text(encoding="utf-8"))
    want = "manifest" if family == "jlens_concept_pr" else type(raw).__name__
    assert fi.shape == want
    _h, items, _ = _bank(family)
    assert all(fi.id_key in it for it in items), (family, fi.id_key)
    # the derived constants are consistent with the inputs
    assert set(ji.REQUIRED_ITEM_FIELDS[family]) <= set(items[0])


def test_subject_fields_are_pinned():
    assert ji.SUBJECT_FIELDS["multihop"] == ("readout",)
    assert ji.SUBJECT_FIELDS["poetry"] == (
        "intermediates",
        "mc",
        "qwen_commits",
        "gate_variant",
        "prompt_only_opus",
        "regate",
    )
    assert ji.SUBJECT_FIELDS["jailbreak_recognition"] == ("read",)
    assert ji.SUBJECT_FIELDS["arithmetic_intermediates"] == ("cell",)
    assert ji.SUBJECT_FIELDS["association"] == ()
    assert ji.SUBJECT_FIELDS["multilingual_mt"] == ("units",)


def test_plan_0060_floor_fields_are_in_the_table():
    """§1's last column is a floor of REQUIRED_ITEM_FIELDS / the adapted-only fields."""
    floor = {
        "association": {"mc"},
        "multihop": {"mc"},
        "chain_intermediates": {"mc"},
        "conjunctive_association": {"bank_version", "inverted_label"},
        "multilingual": {"mc", "mc_roles", "lang"},
        "multilingual_mt": {"mc_roles", "lang"},
        "multilingual_multihop": {"mc_roles", "mc"},
        "basic_readout": {"slice", "task_context", "mc"},
        "basic_readout_mt": {"name_forms"},
        "poetry": {"line_one_end", "mc", "qwen_commits"},
        "moral_rationale": {"options", "bank_version"},
    }
    for fam, keys in floor.items():
        assert keys <= set(ji.REQUIRED_ITEM_FIELDS[fam]), fam
    assert ji.ADAPTED_ONLY_FIELDS["multihop"] == ("split_subject",)
    for fam in ("multilingual", "multilingual_mt", "multilingual_typo", "multilingual_multihop"):
        assert "version" in ji.REQUIRED_HEADER_FIELDS[fam]
    for fam in ("multilingual", "multilingual_mt", "multilingual_typo", "multilingual_multihop"):
        assert "contract.native_langs" in ji.REQUIRED_HEADER_FIELDS[fam]
    assert "contract.native_langs" in ji.REQUIRED_HEADER_FIELDS["typo_mt"]
    assert "contract.native_langs" in ji.REQUIRED_HEADER_FIELDS["basic_readout_mt"]
    assert set(ji.SUBJECT_FIELDS["moral_rationale"]) >= {
        "options",
        "reason_class",
        "reasons",
        "look_for_reasons",
        "subject_answer",
    }
    for fam in ("multilingual", "multilingual_mt", "multilingual_typo", "multilingual_multihop"):
        assert "units" in ji.SUBJECT_FIELDS[fam]  # native units per native_langs (A1.10)
    assert set(ji.SUBJECT_FIELDS["poetry"]) >= {"mc", "qwen_commits", "regate", "prompt_only_opus"}


# --------------------------------------------------------------- (ii) registered banks pass


@pytest.mark.parametrize("family", ALL)
def test_every_registered_item_passes(family):
    header, items, _ = _bank(family)
    bad = {}
    for it in items:
        got = ji.check_item(family, it, header, registered=True, adapted_bank=False)
        if got:
            bad[ji.item_id(it)] = got
    assert not bad, dict(list(bad.items())[:3])


def test_registered_ids_decide_original_vs_adapted_only():
    _h, items, _ = _bank("multihop")
    assert ji.item_id(items[0]) in ji.registered_ids("multihop")
    assert ji.item_id(_clone("multihop", items[0])) not in ji.registered_ids("multihop")


# ------------------------------------------------- (iii) adapted-only fixtures, per family

# what check_item reports for a registered item with only its id changed; families absent
# here must pass unchanged (their judge reads nothing keyed on the id)
EXPECT_REPORTED = {
    "multihop": "missing: split_subject",
    "basic_readout_mt": "exonyms.json",
    "agentic_misalignment": "exit: agentic targets",
    "relational_multihop": "rel-{scene}-a/b",
}


@pytest.mark.parametrize("family", ALL)
def test_adapted_only_clone_passes_or_is_reported(family):
    header, items, _ = _bank(family)
    clone = _clone(family, items[0])
    got = ji.check_item(family, clone, header, adapted_bank=False)
    want = EXPECT_REPORTED.get(family)
    if want is None:
        assert got == [], got
    else:
        assert got and any(want in p for p in got), got


def test_multihop_split_subject_field_replaces_the_id_lookup(monkeypatch):
    from wsbench.basic import mcjudge_bank

    _h, items, _ = _bank("multihop")
    orig = {**items[0], "id": ji.item_id(items[0])}  # banks.load_bank sets id = label_of(name)
    terms = mcjudge_bank.split_subject(orig)
    assert terms  # the registered id resolves through split_subjects.json
    clone = _clone("multihop", orig)
    assert mcjudge_bank.split_subject(clone) == []  # the hazard: rule silently off
    clone["split_subject"] = terms
    assert ji.check_item("multihop", clone) == []

    # with the field the judge never consults the id-keyed file
    class Boom(dict):
        def get(self, *a, **k):
            raise AssertionError("split_subjects.json consulted for an item with split_subject")

    monkeypatch.setattr(mcjudge_bank, "_SUBJECTS", {"multihop": Boom()})
    assert mcjudge_bank.split_subject(clone) == terms


def test_multihop_element_rule_is_keyed_on_the_id():
    from wsbench.basic.mcjudge_bank import element_item

    _h, items, _ = _bank("multihop")
    el = next(it for it in items if it["name"].endswith("-element"))
    assert element_item({"id": ji.item_id(el)})
    clone = _clone("multihop", el, suffix="-v2")  # nhop-cube-element-v2: pattern broken
    clone["split_subject"] = ["cube"]
    assert not element_item({"id": ji.item_id(clone)})
    got = ji.check_item("multihop", clone)
    assert any("nhop-*-element" in p for p in got), got


def test_role_bound_new_pair_falls_back_to_v2_unless_built(monkeypatch):
    from wsbench.evals.role_bound_association import judge

    _h, items, _ = _bank("role_bound_association")
    clone = _clone("role_bound_association", items[0])
    clone["pair_id"] = f"{clone['pair_id']}-zz"
    got = ji.check_item("role_bound_association", clone)
    assert any("distractors_v3.json" in p for p in got), got
    # once an entry is built for the new pair, the oa-v3 block path is taken
    built = {
        **judge.distractors_v3(),
        clone["pair_id"]: judge.distractors_v3()[items[0]["pair_id"]],
    }
    monkeypatch.setattr(judge, "distractors_v3", lambda: built)
    assert ji.check_item("role_bound_association", clone) == []
    calls = []
    monkeypatch.setattr(judge, "build_block_v2", lambda *a, **k: calls.append(1))
    from wsbench.evals.role_bound_association import gate

    judge.build_block_v3(clone, [*items, clone], gate.load_lexicon())
    assert calls == []  # no silent fallback to the leaking oa-v2 block


def test_role_bound_unlexiconed_role_and_action_are_reported():
    _h, items, _ = _bank("role_bound_association")
    clone = _clone("role_bound_association", items[0])
    clone["role_a"], clone["action"] = "zz-unknown-role", "zz-unknown-action"
    got = " ".join(ji.check_item("role_bound_association", clone))
    assert "roles_v1.json" in got and "actions_v1.json" in got


def test_user_modeling_unknown_gold_is_reported_and_would_crash():
    from wsbench.evals.user_modeling import options

    _h, items, _ = _bank("user_modeling")
    country = next(it for it in items if it["attr_class"] == "Country")
    clone = _clone("user_modeling", country)
    assert ji.check_item("user_modeling", clone) == []  # a registered gold resolves
    clone["attr"] = "zz_atlantis"
    got = " ".join(ji.check_item("user_modeling", clone))
    assert "VALUE_ALIASES" in got and "COUNTRY_REGIONS" in got
    with pytest.raises(KeyError):  # the judge's value gate on a verified gold pick
        options.forms_of("zz atlantis")
    clone["attr_class"] = "Hobby"
    assert any(p.startswith("exit:") for p in ji.check_item("user_modeling", clone))


def test_directed_modulation_concept_needs_a_group():
    _h, items, _ = _bank("directed_modulation")
    clone = _clone("directed_modulation", items[0])
    assert ji.check_item("directed_modulation", clone) == []
    clone["concept"] = "zz-ungrouped"
    assert any("distractor_groups.json" in p for p in ji.check_item("directed_modulation", clone))


def test_mcdm_relation_naming_rules():
    header, items, _ = _bank("multi_concept_directed_modulation")
    rel = next(it for it in items if it.get("roles"))
    clone = _clone("multi_concept_directed_modulation", rel)
    assert ji.check_item("multi_concept_directed_modulation", clone, header) == []
    clone["name"] = "x-" + clone["name"]
    clone["roles"] = {**clone["roles"], "agent": "Zzyzx"}
    got = " ".join(ji.check_item("multi_concept_directed_modulation", clone, header))
    assert "b-*" in got and "name_aliases_v2.json" in got
    bad = {**header, "target_sentence": "Something else."}
    got = ji.check_item("multi_concept_directed_modulation", items[0], bad)
    assert any("off_task" in p for p in got)


def test_agentic_new_id_needs_a_target_entry(monkeypatch):
    _h, items, _ = _bank("agentic_misalignment")
    clone = _clone("agentic_misalignment", items[0])
    assert any(p.startswith("exit:") for p in ji.check_item("agentic_misalignment", clone))
    have = ji._agentic_targets()
    monkeypatch.setattr(ji, "_agentic_targets", lambda: frozenset({clone["id"], *have}))
    assert ji.check_item("agentic_misalignment", clone) == []


def test_mt_families_need_versioned_header_and_native_langs():
    header, items, _ = _bank("multilingual")
    clone = _clone("multilingual", items[0])
    assert ji.check_item("multilingual", clone, header) == []
    v1 = {k: v for k, v in header.items() if k != "version"}
    assert any("header.version" in p for p in ji.check_item("multilingual", clone, v1))
    th, titems, _ = _bank("typo_mt")
    got = ji.check_item("typo_mt", _clone("typo_mt", titems[0]), th)  # an adapted bank
    assert any("native_langs" in p for p in got)


def test_v1_shaped_items_are_reported():
    """The 11 adapted sets carry v1 items (SKILL.md §State): the table names what is missing."""
    _h, items, _ = _bank("association")
    v1 = {k: v for k, v in items[0].items() if k != "mc"}
    assert any(p.startswith("missing: mc") for p in ji.check_item("association", v1))
    mh, mitems, _ = _bank("multihop_mt_v2")
    bad = copy.deepcopy(mitems[0])
    bad["readout"] = {"kind": "final_prompt_token", "offsets": [-1]}
    assert any("v1 final-token" in p for p in ji.check_item("multihop_mt_v2", bad, mh))
    _mh, moral, _ = _bank("moral_rationale")
    m1 = {k: v for k, v in moral[0].items() if k != "bank_version"}
    got = ji.check_item("moral_rationale", m1)
    assert any("bank_version" in p for p in got)


# ------------------------------------------------- (iv) the read plan is id-independent

PLAN_SKIP = {
    "jlens_concept_pr": "a directory bank (manifest + items.json + reference dir)",
}


@pytest.mark.parametrize("family", [f for f in ALL if f not in PLAN_SKIP])
def test_read_plan_of_an_adapted_only_clone_equals_the_original(family, tmp_path, monkeypatch):
    src = registry.frozen_bank_path(family)
    raw = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get(readplan.READ_PLAN_BANK):
        shutil.copy(src.parent / raw[readplan.READ_PLAN_BANK], tmp_path)
    items = raw if isinstance(raw, list) else raw["items"]
    orig = items[0]
    items.append(_clone(family, orig))
    if isinstance(raw, dict) and isinstance(raw.get("vectors"), dict):
        # an adapted bank names its subject's OWN vectors (readplan.vector_file refuses the
        # registered evals/ ones under WSB_BANK_ROOT, #243); the plan only resolves the path
        for v in raw["vectors"].values():
            if isinstance(v, dict) and str(v.get("path", "")).startswith("evals/"):
                v["path"] = "adapted/fixture/" + str(v["path"])[len("evals/") :]
    (tmp_path / f"{family}.json").write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "report.json").write_text(json.dumps({"n_layers": 64}), encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    rows = {r.id: r.row() for r in readplan.plan(family)}
    oid = ji.item_id(orig)
    cid = ji.item_id(_clone(family, orig))
    assert oid in rows and cid in rows, (oid, cid)
    a, b = dict(rows[oid]), dict(rows[cid])
    for r in (a, b):
        r.pop("id")
        r.get("extra", {}).pop("readout_reused_by", None)  # introspection: cross partners by id
    assert a == b


# ------------------------------------------------------------------ the markdown is in sync


def test_docs_table_is_in_sync():
    doc = (registry.REPO_ROOT / "docs/adapt_judge_inputs.md").read_text(encoding="utf-8")
    start, end = doc.index(ji.DOC_BEGIN), doc.index(ji.DOC_END) + len(ji.DOC_END)
    assert doc[start:end] + "\n" == ji.render_markdown(), (
        "docs/adapt_judge_inputs.md is stale: regenerate its table with "
        "wsbench.adapt.judge_inputs.render_markdown()"
    )


def test_review_fixes():
    """Independent review of the audit (2026-11-03): inputs it found missing."""
    # agentic twin_rule: a twin arm without it loses TWIN_RULE_OBJECT
    _h, items, _ = _bank("agentic_misalignment")
    twin = next(it for it in items if it["arm"] == "twin")
    assert twin.get("twin_rule")
    bare = {k: v for k, v in twin.items() if k != "twin_rule"}
    assert any("twin_rule" in p for p in ji.check_item("agentic_misalignment", bare))
    names = {x.name for x in ji.FAMILIES["agentic_misalignment"].inputs}
    assert {"twin_rule", "cluster", "low_power"} <= names
    # basic_readout_mt: only eval_render == "chat" takes the v4 read
    bh, bitems, _ = _bank("basic_readout_mt")
    plain = {**bitems[0], "eval_render": "plain"}
    assert any("eval_render" in p for p in ji.check_item("basic_readout_mt", plain, bh))
    # multihop: an empty split_subject is treated as absent by the judge
    _mh, mitems, _ = _bank("multihop")
    clone = _clone("multihop", mitems[0])
    clone["split_subject"] = []
    assert any("split_subject is empty" in p for p in ji.check_item("multihop", clone))
    # wrong_bridge: the subject regex is the judge's (case-insensitive, leading space)
    _wh, witems, _ = _bank("wrong_bridge")
    w = copy.deepcopy(witems[0])
    w["prompt"] = "  " + w["prompt"].replace("Fact:", "fact:", 1)
    assert ji.check_item("wrong_bridge", w) == []


def test_directed_modulation_bank_level_draw_check():
    header, items, _ = _bank("directed_modulation")
    assert ji.check_bank("directed_modulation", header, items) == {}
    sub = items[0]["subfamily"]
    small = [it for it in items if it["subfamily"] == sub][:3]
    got = ji.check_bank("directed_modulation", header, small)
    assert got and all(any("option draw" in p for p in ps) for ps in got.values())


def test_unverbalized_hint_bank_level_pair_check():
    header, items, _ = _bank("unverbalized_hint")
    assert ji.check_bank("unverbalized_hint", header, items) == {}
    first = items[0]
    partner = next(it for it in items if it["pair_id"] == first["pair_id"] and it is not first)
    lone = ji.check_bank("unverbalized_hint", header, [first])  # its partner missing
    assert lone and all(p[0].startswith("exit:") for p in lone.values())
    dup = {**partner, "name": partner["name"] + "-dup", "role": first["role"]}
    got = ji.check_bank("unverbalized_hint", header, [first, dup])
    assert set(got) == {ji.item_id(first), ji.item_id(dup)}


def test_introspection_unit_fields_are_required():
    _h, items, _ = _bank("introspection")
    for key in ("concept", "cluster", "gold", "options", "readout_of"):
        assert key in ji.REQUIRED_ITEM_FIELDS["introspection"]
    bare = {k: v for k, v in items[0].items() if k != "readout_of"}
    assert any(p.startswith("missing: readout_of") for p in ji.check_item("introspection", bare))


def test_poetry_too_few_surviving_candidates_exits():
    _h, items, _ = _bank("poetry")
    it = copy.deepcopy(items[0])
    assert ji.check_item("poetry", it) == []
    it["qwen_commits"] = {**it["qwen_commits"], **dict.fromkeys(it["mc"]["candidates"], 1)}
    got = ji.check_item("poetry", it)
    assert any(p.startswith("exit: poetry") for p in got), got


def test_check_bank_reports_duplicate_ids():
    _h, items, _ = _bank("multihop")  # name-keyed: load_bank raises
    got = ji.check_bank("multihop", _h, [items[0], copy.deepcopy(items[0])])
    assert any("duplicate item id" in p for p in got[ji.item_id(items[0])])
    _rh, ritems, _ = _bank("relational_multihop")  # id-keyed: by_id keeps one
    got = ji.check_bank("relational_multihop", None, [ritems[0], copy.deepcopy(ritems[0])])
    assert any(p.startswith("hazard: duplicate item id") for p in got[ritems[0]["id"]])


@pytest.mark.parametrize("family", ALL)
def test_check_bank_accepts_every_registered_bank(family):
    """No false rejects: the whole bank of record passes, bank-level checks included."""
    header, items, _ = _bank(family)
    got = ji.check_bank(family, header, items)
    # check_bank judges a bank as ADAPTED: typo_mt's registered header has no native_langs,
    # which an adapted header must carry (A1.10)
    if family == "typo_mt":
        got = {
            iid: [p for p in ps if not p.startswith("missing: header.contract.native_langs")]
            for iid, ps in got.items()
        }
    assert not {k: v for k, v in got.items() if v}, dict(list(got.items())[:3])


def test_known_empty_option_units_are_not_flagged():
    _h, items, _ = _bank("model_specific_directed_modulation")
    it = next(i for i in items if (i["id"], "butter") in ji.KNOWN_EMPTY_OPTION_UNITS)
    assert it["option_units"]["butter"] == []
    assert ji.check_item("model_specific_directed_modulation", it) == []
    other = _clone("model_specific_directed_modulation", it)  # another id: still flagged
    assert any("butter" in p for p in ji.check_item("model_specific_directed_modulation", other))
