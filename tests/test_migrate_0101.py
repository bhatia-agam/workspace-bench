"""Plan 0101 T15: the migration script on a synthetic mini-tree (no real data): its refusals,
its KEEP files and patterns, the word boundaries of its rules, the `association` family /
category move."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("migrate_0101", REPO / "scripts/migrate_0101.py")
mig = importlib.util.module_from_spec(_spec)
sys.modules["migrate_0101"] = mig
_spec.loader.exec_module(mig)

FAMILIES = ("association", "conjunctive_association", "multihop", "multihop_mt", "typo")
CODE = """\
from wsbench.evals.association import prompts
from wsbench.evals.association.judge import run
from wsbench.evals import multihop_mt
from wsbench.evals import typo as typo_pkg
import wsbench.evals.conjunctive_association.judge as cj

BANK = "evals/association/items_v5.json"
OTHER = "evals/baselines/prompt_only.json"
TABLE = {"multihop": 1, "multihop_mt": 2, "multilingual_multihop": 3, "relational_multihop": 4}
GOLDEN = "multihop_mc_options_v5.json"


def f(family, header, name, line):
    if family.startswith("multilingual"):
        return {"family": "multihop"}
    if header["family"] == "typo" or header.get("family") == "typo":
        return "multilingual-mt"
    if "multihop" in f"{line}":
        return "typo_mt_v2_options"
    x = {}
    x["subfamily"] = "typo"
    return name == "typo", multihop_mt, typo_pkg, cj, prompts, run
"""
KEEP_TEST = """\
from wsbench import registry
from wsbench.evals.multihop_mt import prompts


def test_old_name():
    assert registry.canonical("multihop_mt_v2") == "multihop_mt"
    assert (registry.REPO_ROOT / "evals/multihop_mt").is_dir() and prompts
"""


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A git checkout with five families in the flat layout, a pre-manifest and a clean tree."""
    monkeypatch.setenv("MIGRATE_0101_RUFF", f"{sys.executable} -m ruff")
    root = tmp_path / "repo"
    for fam in FAMILIES:
        (root / "evals" / fam).mkdir(parents=True)
        (root / "evals" / fam / "items.json").write_text(
            json.dumps({"family": fam.replace("_", "-"), "items": [{"id": f"{fam}-1"}]})
        )
        (root / "evals" / fam / "README.md").write_text(f"# `{fam}`\n\nBank: `evals/{fam}/`.\n")
        pkg = root / "src/wsbench/evals" / fam
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(f'NAME = "{fam}"\n')
    (root / "evals/baselines").mkdir()
    (root / "evals/baselines/prompt_only.json").write_text(
        json.dumps({"_source": {"m": 1}, "multihop": {"rate": 0.5}, "multihop_mt": {"rate": 0.25}},
                   indent=1) + "\n"
    )  # fmt: skip
    (root / "src/wsbench/evals/__init__.py").write_text('"""Families."""\n')
    (root / "src/wsbench/mod.py").write_text(CODE)
    (root / "src/wsbench/registry.py").write_text('KEEP = "multihop"\n')
    (root / "tests/golden").mkdir(parents=True)
    (root / "tests/test_rename_multihop_mt.py").write_text(KEEP_TEST)
    (root / "tests/test_multihop_mt.py").write_text('NAME = "multihop_mt"\n')
    (root / "tests/test_multihop.py").write_text('NAME = "multihop"\n')
    (root / "scripts").mkdir()
    (root / "scripts/migrate_0101_residue.txt").write_text("")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    (root / mig.MANIFEST).write_text(json.dumps({"base_sha": head.stdout.strip()}))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "manifest")
    return root


def _classify_residue(root):
    plan = mig.build_plan(root, strict=False)
    rows = "".join(f"leave\t{r}\n" for r in plan.residue())
    (root / mig.RESIDUE_FILE).write_text(rows)
    _git(root, "commit", "-q", "-am", "residue")


def test_marks_do_not_trip_on_the_pristine_spellings():
    for ok in (
        "from wsbench.evals.association.judge import run",
        "from wsbench.evals.association import prompts",
        "wsbench/evals/association/judge.py",
        'BANK = "evals/association/items_v5.json"',
        "evals/typo/items.json and evals/multihop_mt/README.md",
        "multihop_stamp = first_step",
    ):
        assert mig.has_mark(ok) == "", ok
    for bad in (
        '"multihop_st"',
        "typo_st",
        "evals/basic/association/items_v5.json",
        "evals/association/conjunctive_association/items_v4.json",
        "from wsbench.evals.association.user_modeling import judge",
        "wsbench/evals/model_specific/introspection/judge.py",
    ):
        assert mig.has_mark(bad), bad


def test_the_rewrite_refuses_a_file_that_holds_a_mark():
    with pytest.raises(mig.Refused):
        mig.find_spans('NAME = "multihop_st"\n', "src/wsbench/x.py")
    with pytest.raises(mig.Refused):
        mig.find_spans("from wsbench.evals.basic.typo import SPEC\n", "src/wsbench/x.py")
    mig.find_spans(CODE, "src/wsbench/mod.py")  # the pristine spellings do not raise


def test_rules_keep_the_word_boundaries_and_the_keep_patterns():
    spans, _live = mig.find_spans(CODE, "src/wsbench/mod.py")
    new = mig.apply_spans(CODE, spans)
    # R1: imports, the family `association` under `basic`, the category package untouched
    assert "from wsbench.evals.basic.association import prompts" in new
    assert "from wsbench.evals.basic.association.judge import run" in new
    assert "from wsbench.evals.basic import multihop as multihop_mt" in new
    assert "from wsbench.evals.basic import typo_st as typo_pkg" in new
    assert "import wsbench.evals.association.conjunctive_association.judge as cj" in new
    # R2: a family path moves, an unmoved directory does not
    assert 'BANK = "evals/basic/association/items_v5.json"' in new
    assert 'OTHER = "evals/baselines/prompt_only.json"' in new
    # R4: whole key literals swap in ONE pass; longer names stay whole
    assert '{"multihop_st": 1, "multihop": 2, "multilingual_multihop": 3, ' in new
    assert '"relational_multihop": 4}' in new and 'name == "typo_st"' in new
    # KEEP patterns: golden names, spelling logic, header vocabulary, field values, `in <str>`
    for kept in (
        '"multihop_mc_options_v5.json"',
        'family.startswith("multilingual")',
        '{"family": "multihop"}',
        'header["family"] == "typo"',
        'header.get("family") == "typo"',
        '"multilingual-mt"',
        '"multihop" in f"{line}"',
        '"typo_mt_v2_options"',
        'x["subfamily"] = "typo"',
    ):
        assert kept in new, kept
    assert [s.rule for s in spans].count("R4") == 3
    residue = mig.residue_of(CODE, spans, "src/wsbench/mod.py")
    assert any('{"family": "multihop"}' in r for r in residue)
    assert any('x["subfamily"] = "typo"' in r for r in residue)


def test_prose_rules_and_their_history_exception():
    md = (
        "Run `wsbench judge family=typo_mt readouts=examples/readouts/typo_mt.jsonl`.\n"
        "The family `multihop` reads one token; **typo** is superseded.\n"
        "\n"
        "It was keyed `multihop_mt_v2` until 2026-11-04, then `multihop_mt`.\n"
        "The same paragraph: `typo_mt` 0.46 -> 0.67 stays with it.\n"
        "\n"
        "| typo | a table cell |\n"
        "\n"
        "Set WSB_BANK_FILE_MULTIHOP_MT or WSB_BANK_FILE_TYPO; adapted/x/multihop_mt/y.json.\n"
    )
    spans, _live = mig.find_spans(md, "docs/summarizer.md")
    new = mig.apply_spans(md, spans).split("\n")
    assert new[0] == "Run `wsbench judge family=typo readouts=examples/readouts/typo.jsonl`."
    assert new[1] == "The family `multihop_st` reads one token; **typo_st** is superseded."
    # a history remark keeps its WHOLE paragraph (never half of one)
    assert new[3] == "It was keyed `multihop_mt_v2` until 2026-11-04, then `multihop_mt`."
    assert new[4] == "The same paragraph: `typo_mt` 0.46 -> 0.67 stays with it."
    assert new[6] == "| typo | a table cell |"
    assert (
        new[8] == "Set WSB_BANK_FILE_MULTIHOP or WSB_BANK_FILE_TYPO_ST; adapted/x/multihop/y.json."
    )
    residue = mig.residue_of(md, spans, "docs/summarizer.md")
    assert [r.split(":")[1] for r in residue] == ["4", "5", "7"]
    py = '"""``typo`` is a parameter here; ``typo_mt`` is the family."""\n'
    spans, _live = mig.find_spans(py, "src/wsbench/x.py")
    assert mig.apply_spans(py, spans) == py.replace("``typo_mt``", "``typo``")
    # ordinary words are not history: "keyed by", "a hash of", "removed the option"
    plain = "Tables are keyed by family; a hash of `typo_mt` rows; we removed the option.\n"
    spans, _live = mig.find_spans(plain, "docs/summarizer.md")
    assert "`typo`" in mig.apply_spans(plain, spans)


def _rewrite(text, path="scripts/x.py"):
    spans, _live = mig.find_spans(text, path)
    return mig.apply_spans(text, spans)


def test_stored_and_foreign_paths_are_never_rewritten():
    # W1-W3: the introspection vector path is bank bytes carried in plan rows
    stored = (
        'assert steer["vector_file"] == "evals/introspection/vectors/concept_vectors_L12.npy"\n'
    )
    assert _rewrite(stored, "tests/test_introspection.py") == stored
    gauss = 'reg = {"path": "evals/introspection/vectors/gaussian_vectors_L12.npy"}\n'
    assert _rewrite(gauss, "tests/test_x.py") == gauss
    vec = 'VEC = "evals/introspection/vectors"\nBANK = "evals/introspection/items_v2.json"\n'
    out = _rewrite(vec, "scripts/introspection_build_v2.py")
    assert 'VEC = "evals/introspection/vectors"\n' in out  # a KEEP site: two constants by hand
    assert '"evals/model_specific/introspection/items_v2.json"' in out
    assert mig._KEPT_SITES["scripts/introspection_build_v2.py"] == [0]
    # the directory itself still moves where it is a plain path of this repository
    assert "evals/model_specific/introspection/vectors" in _rewrite(
        'OUT = REPO / "evals/introspection/vectors"\n', "scripts/introspection_export_vectors.py"
    )
    # W4: the same spelling in ANOTHER repository, or written into a sha-pinned header
    for kept in (
        'FROZEN_REL = "evals/model_multihop/frozen_v2.json"\n',
        '"source_frozen": "global-workspace evals/model_multihop/frozen_v2.json",\n',
        "    --frozen <gw>/evals/model_multihop/frozen_v2.json \\\n",
        "python x.py --frozen /root/gw-mmh/evals/model_multihop/x.json\n",
    ):
        assert _rewrite(kept, "docs/summarizer.md") == kept, kept
    stored = 'H = {"source_frozen": "evals/model_multihop/frozen_v2.json"}\n'
    assert _rewrite(stored, "scripts/build_model_multihop_bank.py") == stored
    ours = 'BANK = "evals/model_multihop/items.json"\n'
    assert "evals/model_specific/model_multihop/items.json" in _rewrite(ours)
    meta = 'reg_meta = {"items": "evals/wrong_intermediate/items_v4.json"}\n'
    assert _rewrite(meta, "scripts/build_wd_tables.py") == meta


def test_field_values_and_spelling_uses_are_kept():
    code = (
        "def f(it, sub, cfg, name, item_id, kind):\n"
        '    a = it.get("subfamily") in ("typo", "novel")\n'
        '    b = it["subfamily"] in {"typo"}\n'
        '    c = sub == "typo" or cfg.screen == "typo" or kind != "multihop"\n'
        '    d = "multihop" in item_id or "multihop" in name\n'
        '    e = name.find("multihop") + name.count("typo") + name.index("multilingual")\n'
        '    g = fnmatch(name, "multihop") or fnmatch.fnmatch(name, "typo")\n'
        '    h = {"multihop_mt_v2": "multihop_mt"}\n'
        '    i = {"multihop_mt", "multihop_mt_v2"}\n'
        '    j = {"multihop_mt_v2": 1, "multihop_mt": 2}\n'
        "    return a, b, c, d, e, g, h, i, j\n"
    )
    assert _rewrite(code) == code
    # ... while identity uses next to them still translate
    live = (
        "def f(family, seen, row):\n"
        '    x = Row(family="multihop")\n'
        '    return family == "typo", "typo_mt" in seen, {"typo": "typo_mt"}, x\n'
    )
    out = _rewrite(live)
    assert 'family == "typo_st", "typo" in seen, {"typo_st": "typo"}' in out
    assert 'Row(family="multihop_st")' in out


def test_keep_sites_hold_both_sides_of_a_pair():
    # W6: a screen kind; W7: the argument a builder writes into a bank header; W9: an expectation
    screen = 'C = Cfg(\n    "typo",\n)\nSYS = {"typo": "A short text in another language"}\n'
    assert _rewrite(screen, "scripts/mc_options_r5.py") == screen
    header = 'h = _header(v1, "multilingual", n=1)\nm = _header(v1, "multilingual_mt", n=1)\n'
    assert _rewrite(header, "scripts/build_multilingual_v2.py") == header
    assert _rewrite(header, "scripts/other.py") != header
    pair = 'assert "families=multihop_mt waves=40" in r.stdout\n'
    assert _rewrite(pair, "tests/test_adapt_dataround.py") == pair
    assert "families=multihop waves" in _rewrite(pair, "tests/test_other.py")


def test_frozen_excerpts_and_field_lines_stay_verbatim():
    md = (
        "Text `typo_mt`.\n\n```json\n"
        '{"dropped_families": ["typo_mt", "..."], "families": {"multihop": {}}}\n'
        "```\n\n| `name`, `subfamily` | `novel` (typo_mt), `typo` (multilingual_typo) |\n"
    )
    out = _rewrite(md, "evals/fast/README.md")
    assert out.startswith("Text `typo`.") and '["typo_mt", "..."]' in out
    assert '{"multihop": {}}' in out and "`typo` (multilingual_typo)" in out


def test_cli_rules_have_boundaries_and_follow_the_subcommand():
    for kept in (
        "x --family multihop-hard --bank b.json\n",
        "wsbench judge family=typo-hard\n",
        "# see tests/golden/multihop/x.json\n",
        "tests/fixtures/adapted_v1/multilingual/y.json\n",
    ):
        assert _rewrite(kept, "docs/summarizer.md") == kept, kept
    sh = 'step multihop_mt $A multihop_mt model="$M"\n'
    assert _rewrite(sh, "scripts/adapt_set.sh") == 'step multihop_mt $A multihop model="$M"\n'
    assert mig.shell_words(sh, "scripts/adapt_set.sh") == [f"scripts/adapt_set.sh:1:{sh.strip()}"]
    doc = "- **Code:** `$A multihop_mt model=<m>`; run `python -m wsbench.adapt multihop_mt`.\n"
    assert _rewrite(doc, "docs/summarizer.md").count("multihop_mt") == 0
    assert (
        _rewrite("adapt multihop_mt_v2 files\n", "docs/summarizer.md").count("multihop_mt_v2") == 1
    )


def test_a_multi_name_family_import_is_refused():
    with pytest.raises(mig.Refused):
        mig.find_spans("from wsbench.evals import typo, poetry\n", "src/wsbench/x.py")


def test_a_family_readme_keeps_its_links_to_the_repository_root():
    md = "See [0063](../../plans/0063.md), [typo](../typo_mt/README.md), [x](../../../y).\n"
    out = _rewrite(md, "evals/hinted_cutoff/README.md")
    assert "](../../../plans/0063.md)" in out and "](../typo/README.md)" in out
    assert "](../../../y)" in out and _rewrite(md, "docs/summarizer.md").count("../../plans") == 1


def test_dynamic_paths_lists_what_no_rule_can_see():
    code = (
        'a = EVALS / "multihop/items.json"\n'
        'b = (EVALS / sub).glob("*.json")\n'
        'c = Path("evals") / family / "items.json"\n'
        'd = [*(root / "evals").glob("*/README.md")]\n'
        'e = REPO / "evals" / fam\n'
        'f = f"evals/{name}/items.json"\n'
        'g = sorted((SRC / "evals").iterdir())\n'
        'h = REPO / "docs" / "x.md"\n'
    )
    got = mig.dynamic_paths(code, "tests/test_x.py")
    assert [r.split(":")[1] for r in got] == ["1", "2", "3", "4", "5", "6", "7"]
    sh = 'FAMS=basic_readout,multihop\nfor F in poetry typo; do\nP="a multihop_mt b"\nx=1 # typo\n'
    assert [r.split(":")[1] for r in mig.shell_words(sh, "scripts/adapt_set.sh")] == ["1", "2", "3"]
    assert mig.shell_words(sh, "scripts/x.py") == []


def test_tables_agree_with_the_registry_and_the_plan():
    """The script's literal tables are the registry's (it ran once; the tree is migrated)."""
    from wsbench import registry

    assert set(mig.CATEGORY.values()) == set(registry.CATEGORIES)
    # `mig.CATEGORY` is the layout the migration APPLIED (its text rules and the tests above
    # replay it); a family that changed category since is listed here and in `LATER_MOVES`
    moved_since = {"association": "association"}  # plan 0107: from `basic`
    today = {**mig.CATEGORY, **moved_since}
    assert registry._layout() == today and len(mig.CATEGORY) == 32
    assert {f: mig.CATEGORY[f] for f in moved_since} == registry.LEGACY_FAMILY_CATEGORIES
    for f, category in moved_since.items():
        for tree in ("evals", "src/wsbench/evals"):
            was, now = f"{tree}/{mig.CATEGORY[f]}/{f}", f"{tree}/{category}/{f}"
            assert (was, now) in mig.LATER_MOVES
            assert mig.path_today(f"{was}/x.json", []) == f"{now}/x.json"
    assert registry.PRE_0101_KEYS == mig.KEYS
    registry.load_all()
    for new, category in today.items():
        assert registry.FAMILIES[new].group == category, new
    # the directory each family had before the move is its frozen (pre-0101) key
    assert {registry.frozen_name(new): new for new in mig.CATEGORY} == mig.OLD_DIR
    assert mig.KEYS["multihop_mt_v2"] == mig.KEYS["multihop_mt"] == "multihop"
    for header, family in mig.HEADER.items():
        r = registry.REUSED_FAMILY_KEYS[registry.shared_key(family)]
        assert header == (r.live_header if family == r.live else r.other_header)
    for old, prefixes in mig.STAMPS.items():  # the stamp table is the registry's, per old key
        if old == "multihop_mt_v2":
            continue
        new = mig.KEYS[old]
        r = registry.REUSED_FAMILY_KEYS[registry.shared_key(new)]
        assert prefixes == (r.live_stamps if new == r.live else r.other_stamps), old


def test_apply_moves_rewrites_and_checks(tree):
    _classify_residue(tree)
    before = (tree / "evals/multihop/items.json").read_bytes()
    keep = (tree / "src/wsbench/registry.py").read_bytes()
    assert (
        mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 0
    )  # strict tables, lenient tree
    # the pair swapped, `association` moved under `basic` exactly once, the category is new
    assert (tree / "evals/basic/multihop_st/items.json").read_bytes() == before
    assert json.loads((tree / "evals/basic/multihop/items.json").read_text())["family"] == (
        "multihop-mt"
    )
    assert (tree / "evals/basic/association/items.json").is_file()
    assert (tree / "evals/association/conjunctive_association/items.json").is_file()
    assert not (tree / "evals/basic/association/association").exists()
    assert sorted(p.name for p in (tree / "evals").iterdir()) == [
        "association",
        "baselines",
        "basic",
    ]
    assert (tree / "src/wsbench/evals/basic/__init__.py").is_file()
    assert (tree / "tests/test_multihop.py").read_text() == 'NAME = "multihop"\n'
    assert (tree / "tests/test_multihop_st.py").read_text() == 'NAME = "multihop_st"\n'
    # a KEEP file is byte-identical; a KEEP test gets imports and data paths only
    assert (tree / "src/wsbench/registry.py").read_bytes() == keep
    kept = (tree / "tests/test_rename_multihop_mt.py").read_text()
    assert 'registry.canonical("multihop_mt_v2") == "multihop_mt"' in kept
    assert "from wsbench.evals.basic.multihop import prompts" in kept
    assert '"evals/basic/multihop"' in kept
    floors = json.loads((tree / "evals/baselines/prompt_only.json").read_text())
    assert floors == {"_source": {"m": 1}, "multihop_st": {"rate": 0.5}, "multihop": {"rate": 0.25}}
    # the marker and the record live under .git/, the staging dir is gone, nothing is stray
    gd = mig.git_dir(tree)
    assert (gd / mig.MARKER).is_file() and (gd / mig.RECORD).is_file()
    assert not (tree / mig.STAGING).exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True
    ).stdout
    assert "??" not in status
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 0


def test_a_second_apply_is_refused(tree):
    _classify_residue(tree)
    assert mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 0
    with pytest.raises(mig.Refused):
        mig.main(["--root", str(tree), "--partial-tree", "apply"])  # the marker
    (mig.git_dir(tree) / mig.MARKER).unlink()
    with pytest.raises(mig.Refused):
        mig.main(
            ["--root", str(tree), "--partial-tree", "apply"]
        )  # the migrated layout (and a dirty tree)
    _git(tree, "commit", "-q", "-m", "migrated")
    with pytest.raises(mig.Refused):
        mig.main(
            ["--root", str(tree), "--partial-tree", "apply"]
        )  # committed: still the migrated layout


def test_apply_refuses_a_dirty_tree_and_an_unclassified_residue(tree):
    (tree / "stray.txt").write_text("x")
    with pytest.raises(mig.Refused):
        mig.main(["--root", str(tree), "--partial-tree", "apply"])
    (tree / "stray.txt").unlink()
    assert (
        mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 1
    )  # the residue file is empty: check fails


def test_check_fails_while_a_residue_row_is_unclassified(tree):
    plan = mig.build_plan(tree, strict=False)
    rows = plan.residue()
    assert rows
    (tree / mig.RESIDUE_FILE).write_text("".join(f"?\t{r}\n" for r in rows))
    _git(tree, "commit", "-q", "-am", "residue, not classified")
    assert mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 1
    # a third column (the reviewer's replacement text) is accepted
    done = "".join(f"{'edit' if i else 'leave'}\t{r}\tnew text\n" for i, r in enumerate(rows))
    (tree / mig.RESIDUE_FILE).write_text(done)
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 0


def test_check_sees_a_changed_data_byte(tree):
    _classify_residue(tree)
    assert mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 0
    (tree / "evals/basic/typo_st/items.json").write_text("{}")
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 1


def test_plan_writes_the_reviewable_dry_run_and_changes_nothing(tree, tmp_path):
    out = tmp_path / "plan"
    assert mig.main(["--root", str(tree), "--partial-tree", "plan", "--out", str(out)]) == 0
    names = {p.name for p in out.iterdir()}
    assert {"R1.diff", "R4.diff", "keep-proposed.diff", "residue.txt", "moves.txt",
            "tests-values.diff", "json-keys.diff", "counts.json"} <= names  # fmt: skip
    assert (
        'registry.canonical("multihop") == "multihop"' in (out / "keep-proposed.diff").read_text()
    )
    assert "evals/association -> evals/basic/association" in (out / "moves.txt").read_text()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tree, capture_output=True, text=True
    ).stdout
    assert status == ""


def test_set_migrates_an_adapted_set_by_content(tree, tmp_path):
    d = tmp_path / "set"
    (d / "gate").mkdir(parents=True)
    (d / "multihop.json").write_text(json.dumps({"family": "multihop", "items": [{"id": "a"}]}))
    (d / "multihop_mt.json").write_text(
        json.dumps({"family": "multihop-hard", "items": [{"id": "b"}]})
    )
    (d / "gate/multihop.jsonl").write_text(json.dumps({"id": "a"}) + "\n")
    (d / "report.json").write_text(
        json.dumps({"families": {"multihop": {"n": 1}, "multihop_mt": {"n": 1}}}, indent=1) + "\n"
    )
    assert mig.main(["--root", str(tree), "--partial-tree", "set", str(d)]) == 0  # dry run
    assert (d / "multihop_mt.json").is_file()
    assert mig.main(["--root", str(tree), "--partial-tree", "set", str(d), "--apply"]) == 0
    assert json.loads((d / "multihop_st.json").read_text())["family"] == "multihop"
    assert json.loads((d / "multihop.json").read_text())["family"] == "multihop-hard"
    assert json.loads((d / "gate/multihop_st.jsonl").read_text()) == {"id": "a"}
    report = json.loads((d / "report.json").read_text())
    assert list(report["families"]) == ["multihop_st", "multihop"]
    assert report["family_keys"] == "0101"
    with pytest.raises(mig.Refused):
        mig.main(["--root", str(tree), "--partial-tree", "set", str(d), "--apply"])  # the marker


def test_set_refuses_a_set_written_after_the_rename(tree, tmp_path, capsys):
    """Review c5 S1: a set with today's keys and no marker (nothing under an `_mt` key, its
    bare-key bank the multi-token family's) is not translated: `multihop` would become
    `multihop_st`."""
    d = tmp_path / "fresh"
    d.mkdir()
    bank = json.dumps({"family": "multihop-hard", "items": [{"id": "b"}]})
    (d / "multihop.json").write_text(bank)
    report = json.dumps({"families": {"multihop": {"n": 1}}}, indent=1) + "\n"
    (d / "report.json").write_text(report)
    for extra in ([], ["--apply"]):
        with pytest.raises(mig.Refused):
            mig.main(["--root", str(tree), "--partial-tree", "set", str(d), *extra])
        assert "no pre-0101 evidence" in capsys.readouterr().err
    assert (d / "report.json").read_text() == report and (d / "multihop.json").read_text() == bank
    # one retired key in a report is evidence: the same set is then translated as a whole
    (d / "report.json").write_text(
        json.dumps({"families": {"multihop": {"n": 1}}, "drops": {"typo_mt": {}}}, indent=1) + "\n"
    )
    (d / "multihop.json").write_text(json.dumps({"family": "multihop", "items": [{"id": "a"}]}))
    assert mig.main(["--root", str(tree), "--partial-tree", "set", str(d), "--apply"]) == 0
    assert list(json.loads((d / "report.json").read_text())["families"]) == ["multihop_st"]


def test_check_is_a_gate_on_the_migration_commit_only(tree, capsys):
    """Review c5 S2: with the committed record of `apply`, `check` at any later tree runs the
    data half only (hand edits to KEEP files and tests are the next commits' work), from the
    local record or, in a fresh clone, from the base commit's blobs."""
    _classify_residue(tree)
    assert mig.main(["--root", str(tree), "--partial-tree", "apply"]) == 0
    _git(tree, "commit", "-q", "-m", "migrated")
    rec = json.loads((mig.git_dir(tree) / mig.RECORD).read_text())
    applied = {
        "base": rec["head"],
        "tree": subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=tree, capture_output=True, text=True
        ).stdout.strip(),
        "check": "ok",
        "moves": rec["moves"],
        "json": rec["json"],
        "text_data": [f for f in rec["text"] if f in rec["data"]],
    }
    assert mig._at_apply(tree, applied) and mig._at_apply(tree, None)
    (tree / mig.APPLIED).write_text(json.dumps(applied))
    keep = tree / "src/wsbench/registry.py"
    keep.write_text(keep.read_text() + "\n# a hand edit of the next commit\n")
    (tree / "tests/test_new.py").write_text("def test_new():\n    pass\n")  # an untracked file
    assert not mig._at_apply(tree, applied)
    capsys.readouterr()
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 0
    assert "KEEP comparison skipped: recorded at apply" in capsys.readouterr().out
    (mig.git_dir(tree) / mig.RECORD).unlink()  # a fresh clone: no local record
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 0
    (tree / "evals/basic/typo_st/items.json").write_text("{}")  # the data half still gates
    assert mig.main(["--root", str(tree), "--partial-tree", "check"]) == 1


def test_the_committed_record_names_the_migration_commit():
    doc = json.loads((REPO / mig.APPLIED).read_text(encoding="utf-8"))
    assert doc["check"] == "ok" and len(doc["base"]) == 40 and len(doc["tree"]) == 40
    assert doc["counts"] == {
        "data_files": 7878, "moves": len(doc["moves"]), "text_files": 696,
        "json_files": len(doc["json"]),
    }  # fmt: skip
    assert len(doc["moves"]) == 242 and len(doc["json"]) == 75
