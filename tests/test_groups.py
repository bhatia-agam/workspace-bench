"""`group=<category>`: the families of one eval category (registry.CATEGORIES)."""

import pytest

from wsbench import cli, groups, registry


def test_a_group_is_a_registry_category():
    registry.load_all()
    assert groups.names() == list(registry.CATEGORIES)
    for name in groups.names():
        fams = groups.families(name)
        extra = set(groups.ALSO_IN.get(name, ()))
        assert fams and all(registry.FAMILIES[f].group == name or f in extra for f in fams), name
    # every family `all` runs is in its category's group; only ALSO_IN lists one twice
    listed = [f for name in groups.names() for f in groups.families(name)]
    twice = sorted(f for f in set(listed) if listed.count(f) > 1)
    assert twice == sorted(f for fams in groups.ALSO_IN.values() for f in fams)
    assert sorted(set(listed)) == registry.drop_superseded(sorted(registry.FAMILIES))


def test_the_named_categories():
    # the association category (the family `association` is in it) plus the one documented
    # addition: role-bound association, which stays in anti-bag-of-features as well
    association = ["association", "conjunctive_association", "role_bound_association",
                   "user_modeling", "user_modeling_hard"]  # fmt: skip
    assert groups.families("association") == association
    assert groups.ALSO_IN == {"association": ("role_bound_association",)}
    assert groups.families("anti_bag_of_features") == [
        "relational_multihop",
        "role_bound_association",
    ]
    assert registry.FAMILIES["role_bound_association"].group == "anti_bag_of_features"
    assert groups.families("safety") == ["agentic_misalignment", "jailbreak_recognition"]
    computation = ["arithmetic_intermediates", "buggy_code", "chain_intermediates"]
    assert groups.families("computational") == computation
    assert groups.families("computation") == computation  # the name used in conversation
    assert groups.title("computation") == "Computational"
    assert "typo_st" not in groups.families("basic")  # superseded: left out, as `all` does


def test_unknown_group_names_the_known_ones():
    with pytest.raises(ValueError, match="known groups: basic, computational, association"):
        groups.families("nope")


def test_plan_group_writes_only_that_group(tmp_path):
    code = cli.main(["plan", "group=safety", f"out={tmp_path}", "limit=1"])
    assert code == 0
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == sorted(groups.families("safety"))


def test_group_and_families_together_is_an_error(tmp_path):
    assert (
        cli.main(["plan", "group=safety", "families=poetry", f"out={tmp_path}"]) == cli.EXIT_USAGE
    )


def test_group_with_a_tier_flag_is_an_error(tmp_path, capsys):
    assert cli.main(["plan", "group=safety", "--full", f"out={tmp_path}"]) == cli.EXIT_USAGE
    assert "picks the families itself" in capsys.readouterr().err


def test_plan_group_under_fast_keeps_the_fast_families(tmp_path, capsys):
    assert cli.main(["plan", "group=basic", "--fast", "limit=1", f"out={tmp_path}"]) == 0
    out = capsys.readouterr().out
    assert "not in the fast subset, skipped:" in out
    assert {p.stem for p in tmp_path.glob("*.jsonl")} <= set(groups.families("basic"))


def test_run_group_dry_run_selects_the_group(tmp_path, capsys):
    args = ["run", "group=nope", f"readouts_root={tmp_path}", f"out={tmp_path / 'o'}"]
    assert cli.main(args) == cli.EXIT_USAGE
    assert "known groups" in capsys.readouterr().err


def test_show_names_the_families_a_group_selects(tmp_path, capsys):
    assert cli.main(["plan", "group=association", f"out={tmp_path}", "--show"]) == 0
    shown = capsys.readouterr().out
    assert "role_bound_association" in shown and "user_modeling" in shown
