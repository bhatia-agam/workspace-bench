from pathlib import Path

import pytest

from wsbench import registry
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, JudgeArgs, get, load_all, register
from wsbench.results import FamilyResult, macro


def _spec(name="stub"):
    return EvalSpec(
        name=name,
        title="Stub",
        group="logic",
        bank=Path("evals/stub/items.json"),
        judge=JudgeConfig(),
        metric="pass_rate",
        higher_is_better=True,
        run=lambda args: None,
    )


def test_register_get_and_duplicate():
    s = register(_spec())
    assert registry.FAMILIES["stub"] is s
    assert get("stub") is s
    with pytest.raises(ValueError):
        register(_spec())


def test_get_error_lists_known():
    registry.FAMILIES.clear()
    register(_spec("beta"))
    register(_spec("alpha"))
    with pytest.raises(KeyError) as ei:
        get("nope")
    assert "alpha, beta" in str(ei.value)


MC_FAMILIES = {
    "moral_rationale",
    "relational_multihop",
    "role_bound_association",
    "conjunctive_association",
}


def test_load_all_registers_families_idempotently():
    load_all()
    assert set(registry.FAMILIES) >= MC_FAMILIES
    load_all()  # a second import registers nothing twice (would raise)
    assert set(registry.FAMILIES) >= MC_FAMILIES


def test_repo_root_and_judge_args():
    assert (registry.REPO_ROOT / "pyproject.toml").exists()
    fields = set(JudgeArgs.__dataclass_fields__)
    assert fields == {
        "readouts",
        "out",
        "judge",
        "layers",
        "items",
        "limit",
        "allow_missing",
        "concurrency",
        "rpm",
        "dry_run",
        "aux_models",
        "extra",
        "scope",
    }


def test_multihop_mt_removed(real_families):
    # Camila 2026-10-30: "remove it from workspacebench because it has been superceded by v2"
    assert "multihop_mt_regex" in registry.REMOVED_FAMILIES
    assert "multihop_mt_regex" not in registry.FAMILIES
    assert "multihop_mt_regex" not in registry.superseded()
    assert "multihop" in registry.FAMILIES  # the successor stays registered
    assert "multihop" in registry.drop_superseded(sorted(registry.FAMILIES))
    # typo_st -> typo (plan 0033 T1, Camila 2026-10-30: "just keep the hard version")
    assert registry.superseded() == {"typo_st": "typo"}


def test_unverbalized_hint_is_removed(real_families):
    # plan 0058 retired it (Camila 2026-10-31: "also get rid of unverbalized hint for now"); plan
    # 0081 removed it (Camila 2026-11-07: "get rid of the outdated evals like unverbalized_hint")
    assert "unverbalized_hint" in registry.REMOVED_FAMILIES
    assert "unverbalized_hint" not in registry.RETIRED_FAMILIES
    assert "unverbalized_hint" not in registry.FAMILIES
    assert not (registry.REPO_ROOT / "evals/unverbalized_hint").exists()
    assert not (registry.REPO_ROOT / "src/wsbench/evals/unverbalized_hint").exists()
    assert "unverbalized_hint" not in registry.superseded()
    for path in sorted((registry.REPO_ROOT / "evals" / "baselines").glob("*.json")):
        assert "unverbalized_hint" not in path.read_text(encoding="utf-8"), path.name
    # a stale results.json of it in an old run dir stays out of the macro, reason "removed"
    m = macro([_result("unverbalized_hint")])
    assert m["families"] == []
    assert [(e["family"], e["reason"]) for e in m["excluded"]] == [("unverbalized_hint", "removed")]


def _result(family):
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.3,
        ci95=(0.2, 0.4),
        n_items=10,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config={"judge_model": "m", "prompt_version": "v"},
        counts={},
    )


# plan 0081: RETIRED_FAMILIES is empty since unverbalized_hint, its only user, was removed; the
# mechanism stays, so its tests retire a registered stand-in family via monkeypatch
STAND_IN = "association"


@pytest.fixture
def retired_stand_in(real_families, monkeypatch):
    assert STAND_IN in registry.FAMILIES and STAND_IN not in registry.RETIRED_FAMILIES
    monkeypatch.setitem(registry.RETIRED_FAMILIES, STAND_IN, "retired (test stand-in)")
    return STAND_IN


def test_retired_family_is_out_of_all_but_registered(retired_stand_in):
    # plan 0058: reversible, so the family stays registered and runnable by name with its bank,
    # but `all` skips it
    assert retired_stand_in not in registry.REMOVED_FAMILIES
    assert retired_stand_in in registry.FAMILIES
    assert registry.bank_path(retired_stand_in).exists()
    assert retired_stand_in not in registry.drop_superseded(sorted(registry.FAMILIES))
    assert retired_stand_in not in registry.superseded()


def test_retired_family_is_skipped_not_failed_under_ati(retired_stand_in):
    # plan 0058 review: out of the ATI file, a by-name anti_text_inversion run skips it
    # (NotInScope) instead of failing with "run the gate first", and the gate refuses it
    from wsbench.baselines import text_inversion as ti

    with pytest.raises(ti.NotInScope, match="retired"):
        ti.subset_entry(retired_stand_in)
    with pytest.raises(ValueError, match="retired"):
        ti.gate(families=[retired_stand_in])


def test_retired_family_leaves_the_macro(retired_stand_in):
    # plan 0058: results.macro's ``retired=`` defaults to registry.RETIRED_FAMILIES (reason
    # "retired"); passing retired={} does not exclude it as retired (the toy row may still fail
    # a later check, e.g. its judge)
    m = macro([_result(retired_stand_in)], superseded={}, held_out={}, removed={}, retired={})
    assert all(e["reason"] != "retired" for e in m["excluded"])
    m = macro([_result(retired_stand_in)], superseded={}, held_out={}, removed={})
    assert [(e["family"], e["reason"]) for e in m["excluded"]] == [(retired_stand_in, "retired")]
