"""Plan 0085: the frozen strict-ATI subset for Qwen3.6-27B is exactly eight families."""

import json

import pytest

from wsbench import registry
from wsbench.baselines import text_inversion as ti
from wsbench.results import ATI_MACRO_EXCEPTIONS, FamilyResult, macro, markdown_table

STRICT_ATI_FAMILIES = {
    "introspection",
    "moral_rationale",
    "wrong_intermediate",
    "knowledge_cutoff",
    "conjunctive_association",
    "model_specific_directed_modulation",
    "model_multihop",
    "poetry",
}


@pytest.fixture(autouse=True)
def _registered_set(monkeypatch, real_families):
    """The registered Qwen3.6-27B set (no adapted root) with every real family registered."""
    monkeypatch.delenv("WSB_BANK_ROOT", raising=False)


def _row(family: str, n: int, gate: str, n_ids: int | None = None, **extras) -> FamilyResult:
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.5,
        ci95=None,
        n_items=n,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config={"scope": ti.SCOPE},
        counts={},
        extras={"ati_gate": gate, "ati_n_ids": n if n_ids is None else n_ids, **extras},
    )


def _registered_rows() -> list[FamilyResult]:
    """One ATI row per family the runner would judge under anti_text_inversion=True: every
    registered family through ``subset_entry`` (NotInScope = skipped, anything else fails)."""
    rows = []
    for fam in registry.drop_superseded(sorted(registry.FAMILIES)):
        try:
            entry = ti.subset_entry(fam, ti.FROZEN)
        except ti.NotInScope:
            continue
        n = len(entry["ids"])
        rows.append(_row(fam, n, entry["gate"], ati_subset=ti.SUBSET_VERSION))
    return rows


def test_registered_strict_ati_macro_admits_exactly_the_eight():
    m = macro(_registered_rows())
    assert set(m["families"]) == STRICT_ATI_FAMILIES
    assert m["ati_subset"] == ti.SUBSET_VERSION == "ati-subset-v2"
    reasons = {e["family"]: e["reason"] for e in m["excluded"]}
    # shown, but under n >= 20 and not an exception
    small = ("jailbreak_recognition", "user_modeling", "role_bound_association", "basic_readout_st")
    assert reasons == dict.fromkeys(small, "n<20 (ATI)")


@pytest.mark.parametrize("fam", ["nyt_connections", "hinted_cutoff"])
def test_nyt_and_hinted_cutoff_are_out(fam):
    frozen = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    assert fam not in frozen and fam in frozen["_not_gated"] and fam not in ti.PINNED_ENTRIES
    assert "plan 0085" in ti.NOT_GATED[fam] and "Camila 2026-11-08" in ti.NOT_GATED[fam]
    with pytest.raises(ti.NotInScope):
        ti.subset_entry(fam, ti.FROZEN)


def test_model_multihop_is_served_from_its_pinned_entry():
    e = ti.subset_entry("model_multihop", ti.FROZEN)
    assert len(e["ids"]) == e["n_ati"] == 22 and e["n_bank"] == 283
    assert e["gate"] == ti.GATE_VERSION and e["variant"] == "mmh_bridge"
    assert e["pinned"] == ti.PINNED_ENTRIES["model_multihop"]
    # still out of the generic gate, and the file's reason follows the code
    assert "model_multihop" in ti.NOT_GATED and "model_multihop" not in ti.gated_families()
    frozen = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    assert frozen["_not_gated"]["model_multihop"] == ti.NOT_GATED["model_multihop"]


def test_frozen_source_records_the_subset_version_and_family_templates():
    src = json.loads(ti.FROZEN.read_text(encoding="utf-8"))["_source"]
    assert src["subset_version"] == ti.SUBSET_VERSION
    assert src["family_templates"] == ti.FAMILY_PANEL_TEMPLATES
    assert ti.panel_source(3)["family_templates"] == ti.FAMILY_PANEL_TEMPLATES
    assert ti.panel_source(3)["subset_version"] == ti.SUBSET_VERSION


def test_family_templates_are_verbatim_in_the_baselines_readme():
    readme = (registry.REPO_ROOT / "evals" / "baselines" / "README.md").read_text()
    assert all(t in readme for t in ti.FAMILY_PANEL_TEMPLATES.values())
    assert not set(ti.FAMILY_PANEL_TEMPLATES) & set(ti.PANEL_TEMPLATES)


def test_panel_prompt_reads_a_family_template():
    q = ti.panel_prompt({"prefix": "P", "variant": "mmh_bridge"})
    assert q == ti.FAMILY_PANEL_TEMPLATES["mmh_bridge"].format(prefix="P")


def test_pinned_family_without_an_entry_is_skipped(tmp_path):
    """An adapted set (or any file) with no entry: the not-gated path applies as before."""
    dst = tmp_path / "ati.json"
    dst.write_text(json.dumps({"_not_gated": {}}), encoding="utf-8")
    with pytest.raises(ti.NotInScope):
        ti.subset_entry("model_multihop", dst)
    with pytest.raises(ti.NotInScope):
        ti.subset_entry("model_multihop", tmp_path / "missing.json")


def test_pinned_entry_keeps_the_bank_sha_guard(tmp_path):
    frozen = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    frozen["model_multihop"]["bank_sha"] = "0" * 64
    dst = tmp_path / "ati.json"
    dst.write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(SystemExit, match="bank_sha"):
        ti.subset_entry("model_multihop", dst)


def test_poetry_exception_only_on_the_registered_panel_and_a_full_run():
    assert set(ATI_MACRO_EXCEPTIONS) == {"poetry", "model_multihop"}
    assert macro([_row("poetry", 16, ti.GATE_VERSION)])["families"] == ["poetry"]
    adapted = macro([_row("poetry", 16, ti.ADAPTED_GATE_VERSION)])
    assert adapted["excluded"] == [{"family": "poetry", "reason": "n<20 (ATI)"}]
    smoke = macro([_row("poetry", 3, ti.GATE_VERSION, n_ids=16)])
    assert smoke["excluded"] == [{"family": "poetry", "reason": "n<20 (ATI)"}]


def test_macro_excludes_a_row_of_another_subset_definition():
    old = _row("introspection", 124, ti.GATE_VERSION, ati_subset="ati-subset-v1")
    unstamped = _row("moral_rationale", 56, ti.GATE_VERSION)
    m = macro([old, unstamped])
    assert m["families"] == ["moral_rationale"]
    assert m["excluded"] == [
        {"family": "introspection", "reason": "stale ATI subset (ati-subset-v1)"}
    ]
    assert m["ati_subset"] == ti.SUBSET_VERSION
    assert f"({ti.SUBSET_VERSION})" in markdown_table([old, unstamped], m)


def test_adapted_rows_are_never_stale_by_subset_version():
    """The definition is Qwen's: an adapted set's row is not checked against it."""
    r = _row("poetry", 40, ti.ADAPTED_GATE_VERSION, ati_subset="ati-subset-v1")
    assert macro([r])["families"] == ["poetry"]
    assert "ati_subset" not in macro([r])  # an adapted report names no Qwen definition


def test_full_bank_macro_carries_no_subset_version():
    r = _row("introspection", 125, ti.GATE_VERSION)
    r.config = {}
    assert "ati_subset" not in macro([r])


def test_full_gate_carries_a_pinned_entry_over(tmp_path, monkeypatch):
    """A full gate() rewrite never asks a pinned family; its prior entry survives."""
    dst = tmp_path / "ati.json"
    entry = {"gate": ti.GATE_VERSION, "ids": ["x"], "n_ati": 1}
    dst.write_text(json.dumps({"_source": {}, "model_multihop": entry}), encoding="utf-8")
    monkeypatch.setattr(ti, "is_panel_layout", lambda root: True)
    monkeypatch.setattr(ti, "_gate_panel", lambda *a, **k: ({}, {}))
    ti.gate(tmp_path / "run", dst=dst)
    written = json.loads(dst.read_text(encoding="utf-8"))
    assert written["model_multihop"] == entry
    assert written["_source"]["subset_version"] == ti.SUBSET_VERSION
