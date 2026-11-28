"""Plan 0098: the run tiers (fast / core / full), the categories and the core macro."""

import json

import pytest

from wsbench import cli, fast, readplan, registry, runner, tiers
from wsbench.cli import main
from wsbench.results import FamilyResult, core_macro, macro, markdown_table

CATEGORY = {
    "basic_readout_st": "basic",
    "basic_readout": "basic",
    "multihop_st": "basic",
    "multihop": "basic",
    "multilingual_st": "basic",
    "multilingual": "basic",
    "typo_st": "basic",
    "typo": "basic",
    "multilingual_typo": "basic",
    "multilingual_multihop": "basic",
    "poetry": "basic",
    "directed_modulation": "basic",
    "multi_concept_directed_modulation": "basic",
    "association": "association",  # plan 0107: `basic` before
    "chain_intermediates": "computational",
    "buggy_code": "computational",
    "arithmetic_intermediates": "computational",
    "user_modeling": "association",
    "user_modeling_hard": "association",
    "association_hard": "association",
    "conjunctive_association": "association",
    "agentic_misalignment": "safety",
    "jailbreak_recognition": "safety",
    "relational_multihop": "anti_bag_of_features",
    "role_bound_association": "anti_bag_of_features",
    "moral_rationale": "logical_processing",
    "nyt_connections": "logical_processing",
    "model_specific_directed_modulation": "model_specific",
    "model_multihop": "model_specific",
    "introspection": "model_specific",
    "knowledge_cutoff": "model_specific",
    "hinted_cutoff": "model_specific",
    "wrong_intermediate": "model_specific",
    "jlens_concept_pr": "jlens_comparison",
}
CORE = {
    "agentic_misalignment", "jailbreak_recognition", "arithmetic_intermediates", "buggy_code",
    "nyt_connections", "moral_rationale", "poetry", "introspection",
    "multi_concept_directed_modulation", "wrong_intermediate", "relational_multihop",
    "role_bound_association", "knowledge_cutoff", "model_specific_directed_modulation",
    "model_multihop", "chain_intermediates", "hinted_cutoff", "conjunctive_association",
    "user_modeling_hard", "association_hard",
}  # fmt: skip
# 17 until 2026-11-21, when conjunctive_association joined (Camila); 18 until plan 0114
# (2026-11-23), when the two hard banks joined
N = 20
CORE_UNTIL_0114 = (
    "agentic_misalignment", "jailbreak_recognition", "arithmetic_intermediates", "buggy_code",
    "nyt_connections", "moral_rationale", "poetry", "introspection",
    "multi_concept_directed_modulation", "wrong_intermediate", "relational_multihop",
    "role_bound_association", "knowledge_cutoff", "model_specific_directed_modulation",
    "model_multihop", "chain_intermediates", "hinted_cutoff", "conjunctive_association",
)  # fmt: skip


# ---------------------------------------------------------------- categories and tiers


def test_every_family_has_its_category(real_families):
    assert list(registry.CATEGORIES) == [
        "basic",
        "computational",
        "association",
        "safety",
        "anti_bag_of_features",
        "logical_processing",
        "model_specific",
        "jlens_comparison",
    ]
    assert registry.CATEGORIES["basic"] == "Basic (adapted from the J-lens paper)"
    assert registry.CATEGORIES["anti_bag_of_features"] == "Anti-bag-of-features"
    assert registry.CATEGORIES["jlens_comparison"] == "J-lens comparison"  # plan 0105
    assert registry.LEGACY_CATEGORIES == {"precision": "jlens_comparison"}
    assert registry.LEGACY_FAMILY_CATEGORIES == {"association": "basic"}  # plan 0107
    assert {s.name: s.group for s in real_families.values()} == CATEGORY


def test_core_and_full_membership(real_families):
    assert tiers.TIERS == ("fast", "core", "full") and tiers.DEFAULT == "core"
    assert len(tiers.CORE) == N and set(tiers.CORE) == CORE
    assert tiers.core() == sorted(CORE)
    full = tiers.full()
    assert full == registry.drop_superseded(sorted(registry.FAMILIES))
    assert set(tiers.core()) < set(full) and "typo_st" not in full and "jlens_concept_pr" in full
    # the registered user_modeling bank is in full only (its hard bank is the core family)
    assert "user_modeling" in full and "user_modeling" not in tiers.CORE
    # plan 0114: the two hard banks joined at the end of the list, every earlier member and
    # its place kept; their easy siblings are in full only and in no fast subset of today
    assert tiers.CORE[:18] == CORE_UNTIL_0114
    assert tiers.CORE[18:] == ("user_modeling_hard", "association_hard")
    for easy in ("user_modeling", "association"):
        assert tiers.tier_of(easy) == "full" and easy not in tiers.CORE
        assert easy not in fast.families() and tiers.tier_of(f"{easy}_hard") == "core"
    assert tiers.families("core") == tiers.core() and tiers.families("full") == full
    assert tiers.families("fast") == fast.families()
    with pytest.raises(ValueError):
        tiers.families("nope")
    assert set(tiers.core()) <= set(readplan.families())


def test_core_invariant(real_families, monkeypatch):
    for key in ("WSB_BANK_ROOT", "WSB_BANK_FILE_AGENTIC_MISALIGNMENT"):
        monkeypatch.delenv(key, raising=False)
    tiers.check()
    sup, held = registry.superseded(), registry.not_in_macro()
    for name in tiers.CORE:
        assert name in registry.FAMILIES and name not in sup and name not in held, name
        assert name not in registry.RETIRED_FAMILIES and name in tiers.full(), name
    assert tiers.tier_of("poetry") == "core" and tiers.tier_of("multihop_st") == "full"
    assert tiers.tier_of("typo_st") == "" and tiers.tier_of("nope") == ""
    monkeypatch.setitem(registry.RETIRED_FAMILIES, "poetry", "retired (test stand-in)")
    with pytest.raises(ValueError, match="poetry"):
        tiers.check()


# ---------------------------------------------------------------- CLI


def _show(capsys, *argv: str) -> dict:
    assert main([*argv, "--show"]) == 0
    return json.loads(capsys.readouterr().out)


def test_tier_flags_are_argv_rewrites(capsys):
    run = ["run", "readouts_root=r", "out=o"]
    assert _show(capsys, *run)["tier"] == "core"
    assert _show(capsys, *run, "--core")["tier"] == "core"
    assert _show(capsys, *run, "--full")["tier"] == "full"
    assert _show(capsys, *run, "tier=full")["tier"] == "full"
    assert _show(capsys, *run, "all=True")["tier"] == "full"
    assert _show(capsys, *run, "families=poetry")["tier"] == ""
    shown = _show(capsys, *run, "--fast")
    assert shown["tier"] == "fast" and shown["all"] is True and shown["fast"] is True
    assert _show(capsys, *run, "--fast", "families=poetry")["tier"] == ""
    assert _show(capsys, "plan")["tier"] == "core"
    assert _show(capsys, "plan", "--full")["tier"] == "full"
    assert _show(capsys, "plan", "families=all")["tier"] == ""


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        (["families=poetry", "--core"], "families="),
        (["families=poetry", "--full"], "families="),
        (["all=True", "--core"], "all=True"),
        (["all=True", "families=poetry"], "exactly one"),
        (["--fast", "--core"], "--fast"),
        (["--fast-safety", "--full"], "--fast"),
        (["tier=fast"], "use --fast"),
        (["tier=nope"], "tier"),
    ],
)
def test_run_tier_usage_errors(extra, needle, capsys):
    assert main(["run", "readouts_root=r", "out=o", *extra]) == 2
    assert needle in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra",
    [
        ["families=poetry", "--core"],
        ["families=all", "--full"],
        ["--fast", "--core"],
        ["tier=fast"],
    ],
)
def test_plan_tier_usage_errors(extra, capsys):
    assert main(["plan", *extra]) == 2
    assert capsys.readouterr().err


def test_a_command_without_tiers_rejects_the_flag(capsys):
    assert main(["report", "dir=x", "--core"]) == 2


@pytest.fixture
def ran(real_families, monkeypatch, tmp_path):
    """``run`` with the judging replaced: returns the family names each call was given."""
    seen: list[list[str]] = []

    def fake(specs, args, **kw):
        seen.append([s.name for s in specs])
        return [], 0

    monkeypatch.setattr(runner, "run_families", fake)
    monkeypatch.delenv("WSB_BANK_ROOT", raising=False)
    return seen


def test_run_defaults_to_core_and_full_is_all(ran, tmp_path):
    base = ["run", f"readouts_root={tmp_path}", f"out={tmp_path / 'o'}"]
    assert main(base) == 0
    assert main([*base, "--core"]) == 0
    assert main([*base, "--full"]) == 0
    assert main([*base, "all=True"]) == 0
    assert main([*base, "families=typo_st,poetry"]) == 0
    assert main([*base, "all=True", "include_superseded=True"]) == 0
    assert ran[0] == ran[1] == sorted(CORE)
    assert ran[2] == ran[3] == registry.drop_superseded(sorted(registry.FAMILIES))
    assert ran[4] == ["typo_st", "poetry"]
    assert ran[5] == sorted(registry.FAMILIES)


def test_run_fast_bare_is_fast_all(ran, tmp_path):
    base = ["run", "--fast", f"readouts_root={tmp_path}", f"out={tmp_path / 'o'}"]
    assert main(base) == 0 and main([*base, "all=True"]) == 0
    assert ran[0] == ran[1] == registry.drop_superseded(sorted(registry.FAMILIES))


def test_run_json_names_the_tier_only_when_it_selected(real_families, monkeypatch, tmp_path):
    def fake(specs, args, **kw):
        return [runner.FamilyOutcome(family=specs[0].name, status="skipped", error="none")], 0

    monkeypatch.setattr(runner, "run_families", fake)
    base = ["run", f"readouts_root={tmp_path}"]
    for argv, want in (
        ([], "core"),
        (["--full"], "full"),
        (["--core"], "core"),
        (["--fast"], "fast"),
        (["families=poetry"], None),
        # the pre-0098 spelling keeps its manifest keys
        (["all=True"], None),
        (["--fast", "all=True"], None),
    ):
        out = tmp_path / ("o-" + "-".join(argv).replace("=", ""))
        assert main([*base, f"out={out}", *argv]) == 0
        assert json.loads((out / "run.json").read_text()).get("tier") == want, argv


@pytest.fixture
def planned(real_families, monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(cli.Plan, "_write", lambda self, names: seen.append(list(names)) or 0)
    monkeypatch.delenv("WSB_BANK_ROOT", raising=False)
    return seen


def test_plan_default_is_core_and_all_stays_full(planned):
    assert main(["plan"]) == 0 and main(["plan", "--core"]) == 0
    assert main(["plan", "families=all"]) == 0 and main(["plan", "--full"]) == 0
    assert main(["plan", "families=typo_st"]) == 0
    assert main(["plan", "--fast"]) == 0 and main(["plan", "--fast", "families=all"]) == 0
    full = registry.drop_superseded(readplan.families())
    assert planned[0] == planned[1] and set(planned[0]) == CORE and len(planned[0]) == N
    assert planned[2] == planned[3] == full
    assert planned[4] == ["typo_st"]
    assert planned[5] == planned[6] == fast.families()


def test_list_has_category_and_tier_columns(real_families, capsys):
    assert main(["list"]) == 0
    head, *rows = capsys.readouterr().out.splitlines()
    assert head.split()[:3] == ["family", "category", "tier"] and "group" not in head
    at = head.index("tier")
    cell = {ln.split()[0]: ln[at:].split("  ")[0].strip() for ln in rows}
    assert cell["user_modeling"] == "full" and cell["poetry"] == "core"
    assert cell["multihop_st"] == "full" and cell["jlens_concept_pr"] == "full"
    assert cell["typo_st"] == "—"
    assert {f for f, c in cell.items() if c == "core"} == CORE
    typo = next(ln for ln in rows if ln.startswith("typo_st "))
    assert "basic (superseded by typo)" in typo


# ---------------------------------------------------------------- the core macro


def _res(family: str, value: float | None = 0.5, **kw) -> FamilyResult:
    spec = registry.FAMILIES.get(family)
    base = {
        "family": family,
        "metric": "pass_rate",
        "value": value,
        "ci95": (0.4, 0.6) if value is not None else None,
        "n_items": 100,
        "higher_is_better": True,
        "chance": 0.1,
        "chance_label": None,
        "complete": True,
        "pinned_instrument": True,
        "config": {
            "judge_model": spec.judge.model if spec else "m",
            "prompt_version": "v1",
            "aggregate": "summary",
        },
        "counts": {},
    }
    base.update(kw)
    return FamilyResult(**base)


def _core_results(**over) -> list[FamilyResult]:
    out = []
    for i, f in enumerate(sorted(CORE)):
        out.append(_res(f, value=round(0.1 + 0.04 * i, 2), **over.get(f, {})))
    return out


@pytest.fixture
def clean(real_families, monkeypatch):
    for key in ("WSB_BANK_ROOT", "WSB_BANK_FILE_AGENTIC_MISALIGNMENT"):
        monkeypatch.delenv(key, raising=False)


def test_core_macro_complete(clean):
    results = _core_results()
    cm = core_macro(results)
    assert cm["value"] == pytest.approx(sum(r.value for r in results) / N)
    assert cm["tier"] == "core" and cm["n_core"] == N and cm["complete"] is True
    assert cm["families"] == sorted(CORE) and cm["missing"] == [] and cm["excluded"] == []
    assert set(cm) == {"value", "families", "excluded", "tier", "n_core", "missing", "complete"}
    m = macro(results)
    assert m["value"] == cm["value"] and set(m) == {"value", "families", "excluded"}


def test_core_macro_missing_family(clean):
    results = [r for r in _core_results() if r.family != "poetry"]
    cm = core_macro(results)
    assert cm["missing"] == ["poetry"] and cm["complete"] is False
    assert len(cm["families"]) == N - 1
    assert cm["value"] == pytest.approx(sum(r.value for r in results) / (N - 1))
    # user_modeling is a full-tier family: its row never enters the core macro
    with_um = [*results, _res("user_modeling", value=1.0)]
    assert core_macro(with_um) == cm and "user_modeling" in macro(with_um)["families"]
    assert core_macro([]) == {
        "value": None,
        "families": [],
        "excluded": [],
        "tier": "core",
        "n_core": N,
        "missing": sorted(CORE),
        "complete": False,
    }


def test_core_macro_is_none_for_scoped_rows(clean):
    results = _core_results()
    results[0].config["scope"] = fast.SCOPE
    assert core_macro(results) is None
    results[0].config["scope"] = "anti_text_inversion"
    assert core_macro(results) is None


def test_core_macro_shares_the_macro_exclusions(clean):
    # a native core row beside summary rows that are all non-core: out of both macros
    native = _res("poetry")
    native.config.pop("aggregate")
    results = [native, _res("multihop_st"), _res("basic_readout_st", complete=False)]
    m, cm = macro(results), core_macro(results)
    want = {"family": "poetry", "reason": "native under aggregate=summary"}
    assert want in m["excluded"] and cm["excluded"] == [want] and cm["families"] == []
    assert cm["value"] is None and m["families"] == ["multihop_st"]
    # the run-level guards raise for the core macro as for the macro
    mixed = [_res("poetry"), _res("multihop_st", config={"reads": "lite"})]
    with pytest.raises(SystemExit, match="only full reads are reported"):
        core_macro(mixed)
    # incomplete and wrong-judge core rows carry the macro's reasons
    results = _core_results(
        poetry={"complete": False},
        buggy_code={"config": {"judge_model": "other", "aggregate": "summary"}},
    )
    reasons = {e["family"]: e["reason"] for e in core_macro(results)["excluded"]}
    assert reasons == {"poetry": "incomplete", "buggy_code": "judge"}
    assert reasons == {e["family"]: e["reason"] for e in macro(results)["excluded"]}


def test_full_result_set_keeps_the_macro_and_adds_the_core_one(clean):
    core = _core_results()
    rest = [_res(f, value=0.9) for f in tiers.full() if f not in CORE]
    rest.append(_res("typo_st", value=0.9))
    results = sorted(core + rest, key=lambda r: r.family)
    m = macro(results)
    assert m == macro(results, None, None, None, None)
    assert set(CORE) < set(m["families"]) and "typo_st" not in m["families"]
    cm = core_macro(results)
    assert cm["families"] == sorted(CORE) and cm["complete"] is True
    assert cm["value"] == pytest.approx(sum(r.value for r in core) / N)
    assert cm["value"] != pytest.approx(m["value"])


# ---------------------------------------------------------------- the table


def test_table_without_core_macro_is_unchanged(clean):
    results = [*_core_results(), _res("multihop_st")]
    m = macro(results)
    plain = markdown_table(results, m)
    assert markdown_table(results, m, core_macro=None) == plain
    assert "core macro" not in plain
    # a core macro with no included row adds nothing either
    assert markdown_table(results, m, core_macro=core_macro([])) == plain
    other = [_res("multihop_st"), _res("basic_readout_st")]
    assert markdown_table(other, macro(other), core_macro=core_macro(other)) == markdown_table(
        other, macro(other)
    )


def test_table_with_core_macro_adds_one_row_and_a_note(clean):
    results = [r for r in _core_results() if r.family != "poetry"] + [_res("multihop_st")]
    results[0] = _res(results[0].family, complete=False)
    m, cm = macro(results), core_macro(results)
    plain = markdown_table(results, m).splitlines()
    lines = markdown_table(results, m, core_macro=cm).splitlines()
    core_row = (
        f"| **core macro** | pass_rate | {cm['value']:.3f} | — | {N - 2} of {N} families | — | — "
        "| — | — |"
    )
    note = f"Core macro: missing: poetry. excluded: {results[0].family} (incomplete)."
    at = next(i for i, ln in enumerate(lines) if ln.startswith("| **macro** |"))
    assert lines[at + 1] == core_row
    k = lines.index(note)
    assert lines[k - 1] == "" and lines[k - 2].startswith("- ") and k > lines.index("Not in macro:")
    # nothing else moved: without the row and the note (and its blank line) it is today's table
    assert lines[: at + 1] + lines[at + 2 : k - 1] + lines[k + 1 :] == plain
    # a complete core macro adds the row only
    full = _core_results()
    with_row = markdown_table(full, macro(full), core_macro=core_macro(full)).splitlines()
    without = markdown_table(full, macro(full)).splitlines()
    assert [ln for ln in with_row if not ln.startswith("| **core macro** |")] == without
    assert len(with_row) == len(without) + 1 and "Core macro:" not in "\n".join(with_row)
    assert f"| {N} of {N} families |" in "\n".join(with_row)
    # floor columns pad the row like the macro row; no macro row = after the last family row
    floors = {"lucky": {}, "prompt-only": {}}
    wide = markdown_table(results, m, floors=floors, core_macro=cm).splitlines()
    row = next(ln for ln in wide if ln.startswith("| **core macro** |"))
    assert row.count("|") == next(ln for ln in wide if ln.startswith("| **macro** |")).count("|")
    bare = markdown_table(results, None, core_macro=cm).splitlines()
    last = max(i for i, ln in enumerate(bare) if ln.startswith("| ") and "**" not in ln)
    assert bare[last + 1] == core_row and "**macro**" not in "\n".join(bare)


def test_report_prints_the_core_macro(clean, tmp_path, capsys):
    from wsbench.results import write_results

    for r in _core_results():
        write_results(tmp_path / r.family, r)
    assert main(["report", f"dir={tmp_path}", "floors=False"]) == 0
    out = capsys.readouterr().out
    assert "| **core macro** |" in out
    line = next(ln for ln in out.splitlines() if ln.startswith("core macro: "))
    assert f"families={N}/{N} missing=[] excluded=[]" in line
    assert "| **core macro** |" in (tmp_path / "summary.md").read_text()
    assert main(["report", f"dir={tmp_path}", "floors=False", "json=True"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["core_macro"]["complete"] is True and "macro" in payload
    by = {f["family"]: f for f in payload["families"]}
    assert by["poetry"]["tier"] == "core" and by["poetry"]["category"] == "basic"


def test_report_of_non_core_families_prints_no_core_line(clean, tmp_path, capsys):
    from wsbench.results import write_results

    for r in (_res("multihop_st"), _res("basic_readout_st")):
        write_results(tmp_path / r.family, r)
    assert main(["report", f"dir={tmp_path}", "floors=False"]) == 0
    out = capsys.readouterr().out
    assert "core macro" not in out and "macro: value=" in out
    assert main(["report", f"dir={tmp_path}", "floors=False", "json=True"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "core_macro" not in payload
    assert {f["family"]: (f["category"], f["tier"]) for f in payload["families"]} == {
        "multihop_st": ("basic", "full"),
        "basic_readout_st": ("basic", "full"),
    }


def test_core_and_full_together_is_a_usage_error(capsys):
    from wsbench.cli import main

    assert main(["plan", "--core", "--full"]) == 2
    assert "pick one" in capsys.readouterr().err


def test_bare_plan_names_its_tier(tmp_path, capsys):
    from wsbench.cli import main

    assert main(["plan", f"out={tmp_path / 'p'}", "limit=1"]) == 0
    assert "tier: core (20 families; --full for all" in capsys.readouterr().err
