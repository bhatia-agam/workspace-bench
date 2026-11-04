"""Plan 0060 A2 (judge side): per-set resource overlays for adapted-only item ids.

Under ``WSB_BANK_ROOT=adapted/<m>`` a judge resource looked up by registered id (or by a
registered value) reads the registered file with the set's ``<root>/<family>/<file>`` entries
ADDED (``registry.load_resource``). For every family the tests pin:

(a) registered items are judged exactly as without ``WSB_BANK_ROOT`` (registered ids always
    resolve to registered entries, and no overlay entry can reach a registered item);
(b) an adapted-only fixture takes the per-set path;
(c) an adapted-only id with no per-set entry is a loud error, never the old silent fallback.
"""

import copy
import json
from pathlib import Path

import pytest

from wsbench import readplan, registry
from wsbench.banks import load_bank

ROOT_ENV = registry.BANK_ROOT_ENV


def _root(tmp_path: Path, monkeypatch, files: dict[str, object]) -> Path:
    """An adapted set dir with ``files`` (relative path -> JSON), set as ``WSB_BANK_ROOT``."""
    root = tmp_path / "adapted" / "m"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(ROOT_ENV, str(root))
    return root


@pytest.fixture(autouse=True)
def _no_bank_overrides(monkeypatch):
    monkeypatch.delenv(ROOT_ENV, raising=False)
    for k in list(__import__("os").environ):
        if k.startswith(registry.BANK_FILE_ENV_PREFIX):
            monkeypatch.delenv(k)


# ------------------------------------------------------------------------- the helper


def test_merge_overlay_adds_and_never_shadows():
    base = {"version": "r", "subjects": {"a": [1]}, "passive": ["x"]}
    over = {"version": "o", "subjects": {"a": [1], "b": [2]}, "passive": ["x", "y"]}
    got, added = registry.merge_overlay(base, over, ("subjects", "passive"))
    assert got == {"version": "r", "subjects": {"a": [1], "b": [2]}, "passive": ["x", "y"]}
    assert added == {"subjects/b", "passive/y"}
    assert base == {"version": "r", "subjects": {"a": [1]}, "passive": ["x"]}  # not mutated
    with pytest.raises(SystemExit, match="differs from the registered entry"):
        registry.merge_overlay(base, {"subjects": {"a": [9]}}, ("subjects",))


def test_merge_overlay_refuses_a_shape_mismatch():
    base = {"subjects": {"a": [1]}, "passive": ["x"], "meta": {"inner": 1}}
    with pytest.raises(SystemExit, match="shape differs from the registered file"):
        registry.merge_overlay(base, {"subjects": ["b"]}, ("subjects",))  # map <- list
    with pytest.raises(SystemExit, match="shape differs from the registered file"):
        registry.merge_overlay(base, {"passive": {"y": 1}}, ("passive",))  # list <- map
    with pytest.raises(SystemExit, match="shape differs from the registered file"):
        registry.merge_overlay(base, {"meta": {"inner": {"k": 1}}}, ("meta.inner",))
    assert base == {"subjects": {"a": [1]}, "passive": ["x"], "meta": {"inner": 1}}


def test_load_resource_is_the_registered_file_without_bank_root(tmp_path, monkeypatch):
    reg = registry.resource_path("multihop", "split_subjects.json")
    data, added = registry.load_resource("multihop", "split_subjects.json", ("subjects",))
    assert data == json.loads(reg.read_text(encoding="utf-8")) and added == frozenset()
    assert registry.overlay_path("multihop", "split_subjects.json") is None
    _root(tmp_path, monkeypatch, {})  # a set with no overlay file: still the registered file
    assert registry.overlay_path("multihop", "split_subjects.json") is None
    assert registry.load_resource("multihop", "split_subjects.json", ("subjects",))[0] == data


def test_adapted_only_needs_bank_root(tmp_path, monkeypatch):
    assert not registry.adapted_only("multihop", "not-registered")
    _root(tmp_path, monkeypatch, {})
    assert registry.adapted_only("multihop", "not-registered")
    assert not registry.adapted_only("multihop", "nhop-cube-element")


# ------------------------------------------------------------------------------ multihop


def _mh_items() -> list[dict]:
    return load_bank(registry.frozen_bank_path("multihop"))[1]


def _mh_view(items):
    from wsbench.basic import mcjudge_bank as mj

    return {it["id"]: mj.element_item(it) for it in items}


def _mh_forms(items):
    from wsbench.basic import mcjudge_bank as mj

    return {it["id"]: mj.gold_forms(it) for it in items}


def test_multihop_registered_unchanged_under_overlay(tmp_path, monkeypatch):
    from wsbench.basic import mcjudge_bank as mj

    items = _mh_items()
    before, forms = _mh_view(items), _mh_forms(items)
    known = next(iter(mj.derived_forms()))
    _root(
        tmp_path,
        monkeypatch,
        {
            "multihop/derived_forms.json": {
                "forms": {"Newland": ["Newlandish"], known: mj.derived_forms()[known]}
            }  # an equal registered entry is allowed
        },
    )
    flagged = [{**it, "element_bridge": not before[it["id"]]} for it in items]
    assert _mh_view(items) == before
    assert _mh_view(flagged) == before  # a flag on a registered id never overrides the id rule
    assert _mh_forms(items) == forms


def test_multihop_adapted_item_takes_the_per_set_path(tmp_path, monkeypatch):
    from wsbench.basic import mcjudge_bank as mj

    _root(tmp_path, monkeypatch, {"multihop/derived_forms.json": {"forms": {"Newland": ["Nl"]}}})
    num = {"mc": {"bridge_type": "number"}}
    assert mj.derived_forms()["Newland"] == ["Nl"]
    assert mj.gold_forms({"id": "ad-1", "mc": {"gold": "Newland", "aliases": []}}) == [
        "Newland",
        "Nl",
    ]
    assert mj.element_item({"id": "ad-periodic", "element_bridge": True, **num})
    assert not mj.element_item({"id": "nhop-x-element", "element_bridge": False, **num})
    assert not mj.element_item({"id": "ad-text", "mc": {"bridge_type": "text"}})


def test_multihop_missing_entry_is_loud(tmp_path, monkeypatch):
    from wsbench.basic import mcjudge_bank as mj

    _root(tmp_path, monkeypatch, {})
    with pytest.raises(SystemExit, match="element_bridge"):
        mj.element_item({"id": "ad-1", "mc": {"bridge_type": "number"}})


# ----------------------------------------------------------------- role_bound_association

RB = "role_bound_association"


def _rb_bank() -> list[dict]:
    return json.loads(registry.frozen_bank_path(RB).read_text(encoding="utf-8"))


def _rb_view(bank):
    from wsbench.evals.role_bound_association import gate, judge

    blocks = judge.blocks_of(bank, bank, gate.load_lexicon())
    return {k: (b.text, b.golds, b.unlexiconed) for k, b in blocks.items()}


# an unlexiconed NEAR role of the registered "CEO": adding it to the lexicon globally would give
# every registered CEO item a new conflicting_role term ("chairperson")
_RB_OVERLAY = {
    f"{RB}/roles_v1.json": {
        "roles": {
            "chairman": {"terms": ["chairman", "chairperson"], "near": []},
            "zookeeper": {"terms": ["zookeeper", "keeper"], "near": ["chairman"]},
            "otter": {"terms": ["otter"], "near": []},
        },
        "block": {"zoo-kin": ["zoo aunt"]},
    },
    f"{RB}/actions_v1.json": {"actions": {"fed fish to": ["fed fish to", "feeds fish to"]}},
    f"{RB}/display_terms_v1.json": {"roles": {"aquarist": ["fish keeper"]}},
    f"{RB}/distractors_v3.json": {
        "pairs": {
            "ad-zoo": {
                "roles": ["aquarist", "visitor", "vet"],
                "actions": ["chased", "comforted", "scolded", "interrogated"],
            }
        }
    },
}


def _rb_adapted(bank) -> dict:
    it = copy.deepcopy(bank[0])
    it.update(
        id="ad-zoo-ab",
        pair_id="ad-zoo",
        role_a="zookeeper",
        role_b="otter",
        action="fed fish to",
        names={"a": "Ingrid", "b": "Pip"},
        stimulus="Ingrid, the zookeeper, fed fish to Pip, the otter.",
    )
    return it


def test_role_bound_global_lexicon_would_change_registered_pairs(tmp_path, monkeypatch):
    """Why the overlay is scoped: merged into the shared lexicon, an added role feeds
    conflicting_role for a REGISTERED role (its near list names it)."""
    from wsbench.evals.role_bound_association import gate

    reg = gate.load_lexicon()
    _root(tmp_path, monkeypatch, _RB_OVERLAY)
    merged = gate.adapted_lexicon()
    quote = "Chairperson Dale signed the memo"
    assert "chairman" in reg.near("CEO") and not reg.has("chairman")
    assert not gate.conflicting_role(quote, "Dale", "CEO", reg)
    assert gate.conflicting_role(quote, "Dale", "CEO", merged)


def test_role_bound_registered_unchanged_under_overlay(tmp_path, monkeypatch):
    from wsbench.evals.role_bound_association import gate

    bank = _rb_bank()
    before = _rb_view(bank)
    _root(tmp_path, monkeypatch, _RB_OVERLAY)
    reg = gate.load_lexicon()
    assert all(gate.lexicon_for(it, reg) is reg for it in bank)
    assert _rb_view(bank) == before


def test_role_bound_adapted_pair_takes_the_per_set_path(tmp_path, monkeypatch):
    from wsbench.evals.role_bound_association import gate, judge

    bank = _rb_bank()
    it = _rb_adapted(bank)
    _root(tmp_path, monkeypatch, _RB_OVERLAY)
    lex = gate.lexicon_for(it, gate.load_lexicon())
    assert lex.has("zookeeper") and lex.actions is not None and lex.display is not None
    block = judge.build_block_v3(it, [*bank, it], lex)
    assert block.distractor_roles == ("aquarist", "visitor", "vet")  # oa-v3, never oa-v2
    assert "(also: fish keeper)" in block.text  # the set's display terms
    assert block.unlexiconed == ()
    q = "Ingrid feeds fish to Pip"
    assert gate.action_ref(q, "fed fish to", ["Pip"], lex.actions)
    assert not gate.action_ref(q, "fed fish to", ["Pip"])  # registered lexicon: literal only
    g = gate.check(q, [], [], ("Ingrid", "zookeeper"), ("Pip", "otter"), lex, "fed fish to")
    assert g["action_ref"] and g["agent_ref"] and g["patient_ref"]


def test_role_bound_missing_entries_are_loud(tmp_path, monkeypatch):
    from wsbench.evals.role_bound_association import gate, judge

    bank = _rb_bank()
    it = _rb_adapted(bank)
    reg = gate.load_lexicon()
    # registered bank: the old silent fallbacks (oa-v2 block, literal role) are unchanged
    assert judge.build_block_v3(it, [*bank, it], reg).distractor_roles == ()
    _root(tmp_path, monkeypatch, {})
    with pytest.raises(SystemExit, match="no lexicon entry"):
        gate.lexicon_for(it, reg)
    with pytest.raises(SystemExit, match="no oa-v3 distractors"):
        judge.build_block_v3(it, [*bank, it], reg)


# --------------------------------------------------------------------------- user_modeling

UM = "user_modeling"
_UM_VALUES = {
    f"{UM}/values.json": {
        "values": {
            "liechtenstein": {
                "class": "Country",
                "aliases": ["liechtenstein", "liechtensteiner", "vaduz", "列支敦士登"],
                "region": "north-west europe",
                "neighbours": ["iceland", "finland"],
                "exclude": ["united kingdom"],
            },
            "zookeeper": {"class": "Occupation", "aliases": ["zookeeper", "zoo keeper"]},
        }
    }
}


def _um_bank() -> list[dict]:
    return json.loads(registry.frozen_bank_path(UM).read_text(encoding="utf-8"))["items"]


def _um_adapted(bank, name, cls, attr) -> dict:
    src = next(it for it in bank if it["attr_class"] == cls)
    return {**copy.deepcopy(src), "name": name, "attr": attr}


def test_user_modeling_registered_unchanged_under_overlay(tmp_path, monkeypatch):
    from wsbench.evals.user_modeling import options as uo

    bank = _um_bank()
    before = uo.build_options(bank)
    forms = {o: (uo.forms_of(o), uo.shadow_forms(o), uo.sibling_forms(o)) for v in before.values()
             for o in v[0]}  # fmt: skip
    _root(tmp_path, monkeypatch, _UM_VALUES)
    extra = [
        _um_adapted(bank, "um-ad-country-00", "Country", "liechtenstein"),
        _um_adapted(bank, "um-ad-occupation-00", "Occupation", "zookeeper"),
    ]
    after = uo.build_options([*bank, *extra])
    assert {k: v for k, v in after.items() if k in before} == before
    assert {o: (uo.forms_of(o), uo.shadow_forms(o), uo.sibling_forms(o)) for o in forms} == forms


def test_user_modeling_adapted_gold_takes_the_per_set_path(tmp_path, monkeypatch):
    from wsbench.evals.user_modeling import options as uo
    from wsbench.evals.user_modeling.aliases import COUNTRY_REGIONS, UM_OPTION_POOL

    bank = _um_bank()
    _root(tmp_path, monkeypatch, _UM_VALUES)
    ctry = _um_adapted(bank, "um-ad-country-00", "Country", "liechtenstein")
    occ = _um_adapted(bank, "um-ad-occupation-00", "Occupation", "zookeeper")
    got = uo.build_options([*bank, ctry, occ])
    opts, gold = got["um-ad-country-00"]
    assert opts[gold - 1] == "liechtenstein"
    assert {"iceland", "finland"} <= set(opts) and "united kingdom" not in opts
    nw = set(COUNTRY_REGIONS["north-west europe"])
    assert not (set(opts) - {"liechtenstein", "iceland", "finland"}) & nw  # other regions only
    assert len(opts) == 10
    assert uo.forms_of("liechtenstein")[0] == "liechtenstein"
    assert "liechtenstein" not in UM_OPTION_POOL["Country"]  # the class pool is never extended
    assert "japanese" in uo.sibling_forms("liechtenstein")
    o2, g2 = got["um-ad-occupation-00"]
    assert o2[g2 - 1] == "zookeeper" and len(o2) == 10
    assert uo.forms_of("zookeeper") == ("zookeeper", "zoo keeper")


def test_user_modeling_missing_entries_are_loud(tmp_path, monkeypatch):
    from wsbench.evals.user_modeling import options as uo

    bank = _um_bank()
    ad = _um_adapted(bank, "um-ad-country-00", "Country", "atlantis")
    uo.build_options([*bank, ad])  # registered bank: options still build silently (unchanged)
    with pytest.raises(KeyError):
        uo.forms_of("atlantis")
    _root(tmp_path, monkeypatch, _UM_VALUES)
    with pytest.raises(SystemExit, match="atlantis"):
        uo.build_options([*bank, ad])


def test_user_modeling_values_file_never_shadows(tmp_path, monkeypatch):
    from wsbench.evals.user_modeling import options as uo

    _root(tmp_path, monkeypatch, {
        f"{UM}/values.json": {"values": {"japan": {"class": "Country", "aliases": ["x"],
                                                  "region": None}}}
    })  # fmt: skip
    with pytest.raises(SystemExit, match="registered value"):
        uo.adapted_values()
    _root(tmp_path / "b", monkeypatch, {
        f"{UM}/values.json": {"values": {"andorra": {"class": "Country", "aliases": ["andorra"]}}}
    })  # fmt: skip
    with pytest.raises(SystemExit, match="region"):
        uo.adapted_values()


# ------------------------------------------------------------------------ basic_readout_mt

BRMT = "basic_readout_mt"


def _brmt_items() -> list[dict]:
    return load_bank(registry.frozen_bank_path(BRMT))[1]


def _brmt_view(items):
    from wsbench.multitoken import family as mf

    return {
        it["id"]: [
            mf.gate_name_forms(it, u["role"]) for u in it["units"] if u["role"] != "language"
        ]
        for it in items
    }


def _brmt_adapted(items) -> dict:
    src = items[0]
    return {**copy.deepcopy(src), "name": "brh-ad-new", "id": "brh-ad-new"}


_BRMT_OVERLAY = {
    f"{BRMT}/exonyms.json": {"items": {"brh-ad-new": {"readout": {"ru": ["НовоеИмя"]}}}},
}


def test_basic_readout_mt_registered_unchanged_under_overlay(tmp_path, monkeypatch):
    items = _brmt_items()
    before = _brmt_view(items)
    _root(tmp_path, monkeypatch, _BRMT_OVERLAY)
    assert _brmt_view(items) == before


def test_basic_readout_mt_adapted_item_takes_the_per_set_path(tmp_path, monkeypatch):
    from wsbench.multitoken import family as mf

    items = _brmt_items()
    ad = _brmt_adapted(items)
    _root(tmp_path, monkeypatch, _BRMT_OVERLAY)
    assert "НовоеИмя" in mf.gate_name_forms(ad, "readout")["ru"]


def test_basic_readout_mt_missing_entries_are_loud(tmp_path, monkeypatch):
    from wsbench.multitoken import family as mf

    ad = _brmt_adapted(_brmt_items())
    _root(tmp_path, monkeypatch, {})
    with pytest.raises(SystemExit, match=r"exonyms\.json"):
        mf.gate_name_forms(ad, "readout")
    _root(tmp_path / "b", monkeypatch, {f"{BRMT}/exonyms.json": {"items": {"brh-ad-new": {}}}})
    assert mf.gate_name_forms(ad, "readout") == mf.item_name_forms(ad, "readout")  # {} = none


# -------------------------------------------------------------------- agentic_misalignment

AG = "agentic_misalignment"


def _ag_root(tmp_path, monkeypatch, overlay: dict | None) -> None:
    files: dict[str, object] = {f"{AG}.json": {"items": []}}
    if overlay is not None:
        files[f"{AG}/targets_v2.json"] = overlay
    _root(tmp_path, monkeypatch, files)


def test_agentic_targets_overlay(tmp_path, monkeypatch):
    from wsbench.evals.agentic_misalignment import judge

    reg = judge.load_targets()
    rid = next(iter(reg))
    new = {"action": "A", "forms": ["a"], "not_credit": []}
    _ag_root(tmp_path, monkeypatch, {"items": {"ad-new": new, rid: reg[rid]}})
    got = judge.load_targets()
    assert {k: got[k] for k in reg} == reg  # (a) registered ids read registered targets
    assert got["ad-new"] == new  # (b)
    ad = {"id": "ad-new", "arm": "misaligned"}
    assert judge.item_targets([ad]) == {"ad-new": new}
    _ag_root(tmp_path / "b", monkeypatch, None)
    with pytest.raises(SystemExit):  # (c) no per-set target: item_targets fails loudly
        judge.item_targets([ad])
    _ag_root(tmp_path / "c", monkeypatch, {"items": {rid: new}})
    with pytest.raises(SystemExit, match="differs from the registered entry"):
        judge.load_targets()


# ------------------------------------------------------- multi_concept_directed_modulation

MCDM = "multi_concept_directed_modulation"


def _mcdm_items() -> list[dict]:
    return load_bank(registry.frozen_bank_path(MCDM))[1]


def _mcdm_bank() -> dict:
    """The registered bank copied in as the set's bank (the companion files resolve beside it)."""
    return {f"{MCDM}.json": json.loads(registry.frozen_bank_path(MCDM).read_text("utf-8"))}


def _mcdm_adapted() -> list[dict]:
    return [
        {"name": "x-alpha", "id": "x-alpha", "concepts": ["copper kettle", "wool scarf"],
         "stratum": "pair", "partner": "x-beta"},
        {"name": "x-beta", "id": "x-beta", "concepts": ["wool kettle", "copper scarf"],
         "stratum": "pair", "partner": "x-alpha"},
    ]  # fmt: skip


def test_mcdm_registered_unchanged_under_overlay(tmp_path, monkeypatch):
    from wsbench.evals.multi_concept_directed_modulation import options as mo

    items = _mcdm_items()
    before, names = mo.build(items), mo.name_aliases()
    over = {f"{MCDM}/name_aliases_v2.json": {"aliases": {"Carl": ["卡尔"]}}}
    _root(tmp_path, monkeypatch, {**_mcdm_bank(), **over})
    assert mo.build(items) == before
    got = mo.name_aliases()
    assert {k: got[k] for k in names} == names and got["Carl"] == ["卡尔"]
    assert [mo.item_partner(it) for it in items] == [mo.partner_of(it["name"]) for it in items]


def test_mcdm_adapted_items_take_the_explicit_fields(tmp_path, monkeypatch):
    from wsbench.evals.multi_concept_directed_modulation import options as mo

    items = _mcdm_items()
    names = {"aliases": {"Carl": ["卡尔"], "Dora": ["朵拉"]}}
    _root(tmp_path, monkeypatch, {**_mcdm_bank(), f"{MCDM}/name_aliases_v2.json": names})
    ad = _mcdm_adapted()
    sets = mo.build([*items, *ad])
    assert {"wool kettle", "copper scarf"} <= set(sets["x-alpha"].options)  # the partner
    rel = {"name": "r-carl-dora", "concepts": ["Carl being angry at Dora"], "partner": None,
           "roles": {"agent": "Carl", "patient": "Dora", "relation": "being angry at",
                     "cluster": "anger"}}  # fmt: skip
    assert mo.item_roles(rel) == rel["roles"]  # roles, not the b- prefix
    mo.check_adapted_people([rel])


def test_mcdm_missing_fields_are_loud(tmp_path, monkeypatch):
    from wsbench.evals.multi_concept_directed_modulation import options as mo

    ad = [{k: v for k, v in it.items() if k != "partner"} for it in _mcdm_adapted()]
    assert mo.item_partner(ad[0]) is None  # registered bank: the suffix rule (no partner)
    _root(tmp_path, monkeypatch, _mcdm_bank())
    with pytest.raises(SystemExit, match="partner"):
        mo.item_partner(ad[0])
    rel = {"name": "r-x", "concepts": ["Zed being angry at Yan"], "partner": None,
           "roles": {"agent": "Zed", "patient": "Yan", "relation": "being angry at",
                     "cluster": "anger"}}  # fmt: skip
    with pytest.raises(SystemExit, match="no name forms"):
        mo.check_adapted_people([rel])


# --------------------------------------------------------------------- directed_modulation

DM = "directed_modulation"


def _dm_items() -> list[dict]:
    return load_bank(registry.frozen_bank_path(DM))[1]


def test_dm_groups_overlay(tmp_path, monkeypatch):
    from wsbench.evals.directed_modulation import judge

    items = _dm_items()
    before = judge.option_sets(items)
    pair = next(it for it in items if it["subfamily"] == "pair")
    reg_group = judge.group_of(pair["concept"])
    sub, grp = reg_group.split(":", 1)
    _root(tmp_path, monkeypatch, {f"{DM}/distractor_groups.json": {"groups": {
        sub: {grp: ["ad-sibling"], "ad-new-group": ["ad-concept"]}}}})  # fmt: skip
    assert judge.option_sets(items) == before  # (a)
    assert judge.group_of("ad-sibling") == reg_group  # (b) joins a registered group
    ad = [{**copy.deepcopy(pair), "name": f"dm-ad-{c}", "id": f"dm-ad-{c}", "concept": c}
          for c in ("ad-sibling", "ad-concept")]  # fmt: skip
    got = judge.option_sets([*items, *ad])
    assert "ad-sibling" not in got[pair["id"]][0]  # never a distractor of its group's gold
    with pytest.raises(ValueError, match="no relatedness group"):  # (c) unchanged: loud
        judge.group_of("ad-ungrouped")
    _root(tmp_path / "b", monkeypatch, {f"{DM}/distractor_groups.json": {"groups": {
        sub: {"elsewhere": [pair["concept"]]}}}})  # fmt: skip
    with pytest.raises(SystemExit, match="another group"):
        judge.group_of(pair["concept"])


# ---------------------------------------------------------------------------- introspection


def test_introspection_vector_paths(tmp_path, monkeypatch):
    bank = tmp_path / "adapted" / "m" / "introspection.json"
    reg = {"path": "evals/introspection/vectors/concept_vectors_L12.npy"}
    assert readplan.vector_file(reg, bank) == reg["path"]  # (a) registered: unchanged
    own = {"path": "introspection/vectors/concept.npy", "relative_to": "bank"}
    assert readplan.vector_file(own, bank) == str(
        (tmp_path / "adapted/m/introspection/vectors/concept.npy").resolve()
    )  # (b) beside the adapted bank
    inside = registry.REPO_ROOT / "adapted" / "m" / "introspection.json"
    assert readplan.vector_file(own, inside) == "adapted/m/introspection/vectors/concept.npy"
    monkeypatch.setenv(ROOT_ENV, str(bank.parent))
    with pytest.raises(SystemExit, match="registered"):  # (c) Qwen's vectors on another subject
        readplan.vector_file(reg, bank)
    subj = {"path": "adapted/m/introspection/vectors/concept_vectors_L9.npy"}  # adapt writes this
    assert readplan.vector_file(subj, bank) == subj["path"]


# ------------------------------------------------- golden digests of the registered instrument
# sha256 of each view below, computed with NO WSB_BANK_ROOT from a `git archive origin/main`
# extract taken BEFORE this change (65bd284b, 2026-11-03): with no root the overlay code must
# reproduce main's registered outputs byte for byte.


def _digest(obj) -> str:
    import hashlib

    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=list)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _view_user_modeling():
    from wsbench.evals.user_modeling import options as uo

    opts = uo.build_options(_um_bank())
    shown = sorted({o for v in opts.values() for o in v[0]})
    return {
        "options": opts,
        "forms": {o: [uo.forms_of(o), uo.shadow_forms(o), uo.sibling_forms(o)] for o in shown},
    }


def _view_role_bound():
    return _rb_view(_rb_bank())


def _view_mcdm():
    import dataclasses

    from wsbench.evals.multi_concept_directed_modulation import options as mo

    sets = mo.build(_mcdm_items())
    return {
        "build": {k: dataclasses.asdict(v) for k, v in sets.items()},
        "names": mo.name_aliases(),
    }


def _view_multihop():
    return _mh_view(_mh_items())


def _view_brmt():
    return _brmt_view(_brmt_items())


def _view_agentic():
    from wsbench.evals.agentic_misalignment import judge

    return judge.load_targets()


def _view_dm():
    from wsbench.evals.directed_modulation import judge

    items = _dm_items()
    return {
        "groups": {it["concept"]: judge.group_of(it["concept"]) for it in items},
        "options": judge.option_sets(items),
    }


GOLDEN_VIEWS = {
    "user_modeling": _view_user_modeling,
    "role_bound_association": _view_role_bound,
    "multi_concept_directed_modulation": _view_mcdm,
    "multihop": _view_multihop,
    "basic_readout_mt": _view_brmt,
    "agentic_misalignment": _view_agentic,
    "directed_modulation": _view_dm,
}
GOLDEN = {
    "agentic_misalignment": "b1becfeeb4bff3e4ee78be09dbb28c316d823b3a60df9077ff3f6dcea5e426e1",
    "basic_readout_mt": "f50cc7ca29af8ded7699e6cb41b609c0e95c3bc4963c3979333befacb0245a1a",
    "directed_modulation": "fd243c54157a7ee801010ea58af6f84d5b1fe37157433d56be62d9f5e2762924",
    "multi_concept_directed_modulation": (
        "646c2023b0a6f780780533829d9693fc7c15ad470d03dc3f93901ac8d26ef0f0"
    ),
    # multihop: main's element_item over the registered bank v4 (its 68 ids are bank v3 items)
    "multihop": "ad5dca2ba01f967dfc583b9add742d2e106a0858c402b1abdf96a93e604244a9",
    "role_bound_association": "4d0286ea4d445553afd84311f5df01393c20dacbeb2053f69e7917636c0f9a72",
    "user_modeling": "818fb524c907945487730bc9a70978a60eab164b4544a0eda1176f1d9128607f",
}


@pytest.mark.parametrize("family", sorted(GOLDEN_VIEWS))
def test_registered_outputs_equal_main(family):
    assert _digest(GOLDEN_VIEWS[family]()) == GOLDEN[family]
