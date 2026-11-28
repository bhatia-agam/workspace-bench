"""Plan 0101 §4: outside ``registry.py`` no code builds a family's data path or module name by
hand. Scan 1 (code) and scan 3 (the ``evals/`` paths docs and tests write exist)."""

import ast
import re
from pathlib import Path

import pytest

from wsbench import registry

REPO = registry.REPO_ROOT
UNMOVED = ("baselines", "fast", "hallucinationbench")
# one alternation over categories and (pre-0101 and current) family keys: `association` is both
NAMES = sorted(
    {*registry.CATEGORIES, *registry._layout(), *registry.PRE_0101_KEYS, *registry.FAMILIES}
    | {registry.frozen_name(f) for f in registry._layout()},
    key=lambda n: (-len(n), n),
)
FAMILY_PATH = re.compile(rf"^evals/({'|'.join(map(re.escape, NAMES))})(/|$)")
EXEMPT = {
    REPO / "src/wsbench/registry.py",
    # HallucinationBench (plan 0120), imported unchanged: each builds a path inside ANOTHER
    # WorkspaceBench checkout (its pinned one, in the pre-0101 layout)
    REPO / "src/wsbench/hb/evals/benign_roleplay/bank.py",
    REPO / "src/wsbench/hb/evals/sibling_probe/bank.py",
}


def code_files() -> list[Path]:
    out = [*(REPO / "src/wsbench").rglob("*.py"), *(REPO / "atlas").glob("*.py")]
    out += (REPO / ".claude/skills").rglob("*.py")
    return sorted(f for f in out if f not in EXEMPT and "__pycache__" not in f.parts)


def _docstrings(tree: ast.AST) -> set[int]:
    """ids of the string constants that are bare expression statements (docstrings, notes)."""
    return {
        id(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
    }


def _is_evals_root(node: ast.AST) -> bool:
    """``"evals"``, ``X / "evals"`` or ``Path("evals")``."""
    if isinstance(node, ast.Constant):
        return node.value == "evals"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return isinstance(node.right, ast.Constant) and node.right.value == "evals"
    if isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        return name == "Path" and _is_evals_root(node.args[0])
    return False


def hand_built_paths(source: str) -> list[str]:
    """Every place ``source`` spells a family data path itself: a string that starts
    ``evals/<category or family>``, an f-string that starts ``evals/{...}``, or a
    ``... / "evals" / <anything but baselines | fast | hallucinationbench>`` join."""
    tree = ast.parse(source)
    docs = _docstrings(tree)
    inside_fstring = {
        id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values
    }
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docs or id(node) in inside_fstring:
                continue
            if FAMILY_PATH.match(node.value):
                bad.append(f"line {node.lineno}: {node.value[:60]!r}")
        elif isinstance(node, ast.JoinedStr) and node.values:
            head = node.values[0]
            text = head.value if isinstance(head, ast.Constant) else ""
            if isinstance(text, str) and (text == "evals/" or FAMILY_PATH.match(text)):
                bad.append(f"line {node.lineno}: an f-string starting {text!r}")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _is_evals_root(node.left):
                right = node.right
                if not (isinstance(right, ast.Constant) and right.value in UNMOVED):
                    bad.append(f'line {node.lineno}: a `/ "evals" / ...` join')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            # a one-level walk of evals/ finds categories, not families, after the move
            walks = node.func.attr in ("iterdir", "glob", "rglob")
            if (
                walks
                and _is_evals_root(node.func.value)
                and not isinstance(node.func.value, ast.Constant)
            ):
                bad.append(f"line {node.lineno}: a walk of evals/ ({node.func.attr})")
    return bad


def by_name_imports(source: str) -> list[str]:
    """``import_module`` calls given an f-string or literal that starts ``wsbench.evals.``."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if name != "import_module":
            continue
        arg = node.args[0]
        head = arg.values[0] if isinstance(arg, ast.JoinedStr) and arg.values else arg
        text = head.value if isinstance(head, ast.Constant) else ""
        if isinstance(text, str) and text.startswith("wsbench.evals."):
            bad.append(f"line {node.lineno}: import_module({text!r}...)")
    return bad


def test_scanners_see_the_patterns():
    assert hand_built_paths('x = "evals/poetry/items_v5.json"')
    assert hand_built_paths('x = REPO_ROOT / "evals" / family / "items.json"')
    assert hand_built_paths('x = Path("evals") / name')
    assert hand_built_paths('x = f"evals/{family}/items.json"')
    assert hand_built_paths('x = REPO_ROOT / "evals/poetry/items_v5.json"')
    assert hand_built_paths('for d in (WSB / "evals").iterdir(): pass')
    assert hand_built_paths('x = list((REPO / "evals").glob("*/README.md"))')
    assert not hand_built_paths('x = list((REPO / "evals" / "baselines").glob("*.json"))')
    assert not hand_built_paths('x = REPO_ROOT / "evals" / "baselines" / "x.json"')
    assert not hand_built_paths('x = REPO_ROOT / "evals"')
    assert not hand_built_paths('"""evals/poetry/README.md is prose here."""')
    assert not hand_built_paths('x = "see evals/poetry/README.md"')
    assert not hand_built_paths('x = "evals/baselines/prompt_only.json"')
    assert by_name_imports('importlib.import_module(f"wsbench.evals.{f}.prompts")')
    assert by_name_imports('import_module("wsbench.evals.poetry")')
    assert not by_name_imports('importlib.import_module(f"wsbench.adapt.{name}")')


def test_no_code_builds_a_family_path_by_hand():
    bad = {
        str(f.relative_to(REPO)): hits
        for f in code_files()
        if (hits := hand_built_paths(f.read_text(encoding="utf-8")))
    }
    assert not bad, bad


def test_no_code_or_test_imports_a_family_by_built_name():
    files = [*code_files(), *sorted((REPO / "tests").rglob("*.py"))]
    bad = {
        str(f.relative_to(REPO)): hits
        for f in files
        if f.name != "test_family_paths.py"
        and (hits := by_name_imports(f.read_text(encoding="utf-8")))
    }
    assert not bad, bad


# ---------------------------------------------------------------- scan 3: written paths exist

_PATH = re.compile(r"(?<![\w./-])evals/[\w./*<>{}\[\]|$-]+")
_SKILL_AUDITS = {"SKILL_AUDIT.md", "SKILL_AUDIT_RESPONSE.md"}
# a file a README says does NOT exist; bank versions and directories tests assert are gone
ABSENT_ON_PURPOSE = (
    "evals/basic/basic_readout/hidden_rivals.json",
    "evals/basic/basic_readout/items_v5.json",
    "evals/basic/multihop_st/items_v4.json",
    "evals/basic/multihop/items_v5.json",
    "evals/association/user_modeling/items_v2.json",
    "evals/multihop_mt_v2",
    "evals/wrong_bridge",
    "evals/unverbalized_hint",
)
# Paths written on purpose that are not files of this checkout (the list may only shrink):
KNOWN_MISSING = {
    # paths of the source repos (global-workspace, the J-lens repo), quoted in credits
    "evals/workspace-bench/hillclimbing_evals/multi_token/dm_category_default",
    "evals/workspace-bench/jlens_pr",
    "evals/chint_cutoff",
    "evals/chint_cutoff/frozen_v2.json",
    "evals/model_multihop/frozen_v2.json",
    "evals/diagnostic/misalignment_exhaustive_bank.json",
    *ABSENT_ON_PURPOSE,
    # the pre-0101 layout strings the introspection bank stores (plan rows carry them; resolved
    # by ``registry.repo_path``): tests quote them as the bank writes them
    "evals/introspection/vectors/concept_vectors_L12.npy",
    "evals/introspection/vectors/gaussian_vectors_L12.npy",
    # toy banks of test-registered families
    "evals/stub/items.json",
    "evals/old/items.json",
    "evals/other/items.json",
}


def doc_files() -> list[Path]:
    out = [REPO / n for n in ("README.md", "CLAUDE.md", "AGENTS.md", "NOTICE.md")]
    out += [REPO / "docs" / f"{n}.md" for n in ("producing_readouts", "summarizer")]
    # the reference pages split out of the README (they hold its family paths now)
    split = (
        "running",
        "tiers",
        "fast_subset",
        "baselines",
        "judges",
        "porting",
        "evals",
    )
    out += [REPO / "docs" / f"{n}.md" for n in (*split, "results_contract", "hallucinationbench")]
    out.append(REPO / "docs/adapt_judge_inputs.md")
    out += [f for f in (REPO / ".claude/skills").rglob("*.md") if f.name not in _SKILL_AUDITS]
    out += [registry.family_root(f) / "README.md" for f in registry._layout()]
    # tests/hb (HallucinationBench's suite, plan 0120) writes paths of ANOTHER checkout: skipped
    hb = REPO / "tests" / "hb"
    out += sorted(f for f in (REPO / "tests").rglob("*.py") if hb not in f.parents)
    return [f for f in out if f.is_file()]


def written_paths(text: str) -> list[str]:
    """The concrete ``evals/...`` paths in ``text`` (a glob, a ``<placeholder>``, a ``{field}``
    or an alternation is skipped; trailing punctuation dropped)."""
    out = []
    for m in _PATH.finditer(text):
        path = m.group(0).rstrip(".,:;-/")
        if not re.search(r"[*<>{}\[\]|$]", path):
            out.append(path)
    return out


def test_written_paths_parser():
    text = "see `evals/poetry/items_v5.json`, evals/<family>/README.md and evals/*/x.json."
    assert written_paths(text) == ["evals/poetry/items_v5.json"]
    assert written_paths("wsbench/evals/poetry/judge.py") == []


def test_every_written_evals_path_exists():
    missing: dict[str, list[str]] = {}
    seen: set[str] = set()
    for f in doc_files():
        if f.name in ("test_family_paths.py", "test_migrate_0101.py"):
            continue  # these two hold both layouts' paths on purpose
        for path in written_paths(f.read_text(encoding="utf-8")):
            # docs name a family's code src-relative (`evals/<family>/judge.py`)
            here = (REPO / path).exists() or (REPO / "src/wsbench" / path).exists()
            if not here and path not in KNOWN_MISSING:
                missing.setdefault(str(f.relative_to(REPO)), []).append(path)
            seen.add(path)
    assert not missing, missing
    assert seen >= KNOWN_MISSING, sorted(KNOWN_MISSING - seen)  # no stale allowance
    # a path a test asserts is ABSENT must still sit in a directory that exists, or a
    # mis-rewritten path would make the assertion vacuous
    for path in ABSENT_ON_PURPOSE:
        assert (REPO / path).parent.is_dir(), path


# ---------------------------------------------------------------- the helpers


# plan 0101 §0.2: every family's category directory
LAYOUT = {
    "association": "association",  # plan 0107: `basic` before
    "basic_readout": "basic",
    "basic_readout_st": "basic",
    "directed_modulation": "basic",
    "multi_concept_directed_modulation": "basic",
    "multihop": "basic",
    "multihop_st": "basic",
    "multilingual": "basic",
    "multilingual_st": "basic",
    "multilingual_multihop": "basic",
    "multilingual_typo": "basic",
    "poetry": "basic",
    "typo": "basic",
    "typo_st": "basic",
    "arithmetic_intermediates": "computational",
    "buggy_code": "computational",
    "chain_intermediates": "computational",
    "conjunctive_association": "association",
    "user_modeling": "association",
    "user_modeling_hard": "association",
    "association_hard": "association",
    "agentic_misalignment": "safety",
    "jailbreak_recognition": "safety",
    "relational_multihop": "anti_bag_of_features",
    "role_bound_association": "anti_bag_of_features",
    "moral_rationale": "logical_processing",
    "nyt_connections": "logical_processing",
    "hinted_cutoff": "model_specific",
    "introspection": "model_specific",
    "knowledge_cutoff": "model_specific",
    "model_multihop": "model_specific",
    "model_specific_directed_modulation": "model_specific",
    "wrong_intermediate": "model_specific",
    "jlens_concept_pr": "jlens_comparison",
}


def test_layout_is_one_category_per_family(real_families):
    layout = registry._layout()
    assert set(layout) == set(real_families)
    assert layout == LAYOUT and set(layout.values()) == set(registry.CATEGORIES)
    for name, spec in real_families.items():
        assert layout[name] == spec.group == registry.category_of(name)
        assert spec.bank.parts[: len(registry.family_rel(name).parts)] == (
            registry.family_rel(name).parts
        )
        assert registry.family_root(name).is_dir()
        assert registry.family_module(name).SPEC is spec
        assert registry.family_module(name, "prompts").PROMPTS
    assert sorted(registry.family_packages()) == sorted(
        registry.family_module(f).__name__ for f in layout
    )
    with pytest.raises(KeyError):
        registry.category_of("no_such_family")


def test_repo_path():
    vec = "evals/introspection/vectors/concept_vectors_L12.npy"
    assert registry.repo_path(vec) == registry.family_root("introspection") / "vectors" / (
        "concept_vectors_L12.npy"
    )
    assert registry.repo_path(vec).exists()
    assert registry.repo_path("evals/baselines/prompt_only.json") == (
        REPO / "evals/baselines/prompt_only.json"
    )
    assert registry.repo_path("docs/summarizer.md") == REPO / "docs/summarizer.md"
    assert registry.repo_path("/abs/x.json") == Path("/abs/x.json")
    # F8: `association` is a pre-0101 family key AND a category. A pre-0101 path of the family
    # resolves into the family's directory (under the category `association` since plan 0107,
    # hence the doubled segment); a new-layout path is taken as written
    assert registry.repo_path("evals/association/items_v5.json") == (
        REPO / "evals/association/association/items_v5.json"
    )
    for as_written in (
        "evals/association/conjunctive_association/items_v4.json",
        "evals/association/association/items_v5.json",
        "evals/basic/multihop_st/items_v5.json",
    ):
        assert registry.repo_path(as_written) == REPO / as_written and (REPO / as_written).exists()
    # plan 0107: the family `association` left `basic` for the category `association`. A path
    # stored under the category it left resolves into today's directory, at any depth
    doubled = REPO / "evals/association/association"
    assert registry.family_root("association") == doubled and doubled.is_dir()
    assert registry.family_rel("association") == Path("evals/association/association")
    assert registry.LEGACY_FAMILY_CATEGORIES == {"association": "basic"}
    for stored, rest in (
        ("evals/basic/association/items_v5.json", "items_v5.json"),
        ("evals/basic/association/distractor_screen_v2.json", "distractor_screen_v2.json"),
        ("evals/basic/association", ""),
        ("evals/association/items_v4.json", "items_v4.json"),  # pre-0101
        ("evals/association", ""),  # pre-0101: the bare name was the family's directory
        ("evals/association/association/items_v4.json", "items_v4.json"),  # today
    ):
        assert registry.repo_path(stored) == (doubled / rest if rest else doubled), stored
        assert registry.repo_path(stored).exists(), stored
    # ... and nothing else: the category's other families (as written, never
    # read as the pre-0101 family directory plus a subdirectory), another family under `basic`,
    # an unknown family under `basic`, and the same family under a category it never sat in
    for as_written in (
        "evals/association/user_modeling/items_v3.json",
        "evals/association/user_modeling/README.md",
        "evals/association/conjunctive_association/items_v6.json",
        "evals/basic/poetry/README.md",
    ):
        assert registry.repo_path(as_written) == REPO / as_written and (REPO / as_written).exists()
    for as_written in ("evals/basic/no_such_family/x.json", "evals/safety/association/x.json"):
        assert registry.repo_path(as_written) == REPO / as_written
    assert not (REPO / "evals/basic/association").exists()
    # a missing WSB_BANK_FILE_* path of the old directory is told where the family is now
    assert registry._moved_hint("evals/basic/association/items_v5.json").endswith(
        "evals/association/association/items_v5.json"
    )
    assert registry._moved_hint("evals/association/items_v5.json").endswith(
        "evals/association/association/items_v5.json"
    )
    assert registry._moved_hint("evals/basic/poetry/items.json") == ""
    # a path already in today's layout gets no hint (review of #525)
    assert registry._moved_hint("evals/association/association/items_v9.json") == ""
    assert registry._moved_hint("evals/association/user_modeling/items_v9.json") == ""
    # plan 0105: a path stored under the category's former name resolves into today's directory
    assert registry.repo_path("evals/precision/jlens_concept_pr/manifest.json") == (
        REPO / "evals/jlens_comparison/jlens_concept_pr/manifest.json"
    )
    assert registry.repo_path("evals/jlens_concept_pr/manifest.json") == (
        REPO / "evals/jlens_comparison/jlens_concept_pr/manifest.json"
    )
    assert registry.repo_path("evals/precision/no_such_family/x.json") == (
        REPO / "evals/precision/no_such_family/x.json"
    )
    # a pre-0101 path of a renamed family lands in the family that had that key
    assert registry.repo_path("evals/multihop/items_v5.json") == (
        REPO / "evals/basic/multihop_st/items_v5.json"
    )
    assert registry.repo_path("evals/multihop_mt/items_v6.json") == (
        REPO / "evals/basic/multihop/items_v6.json"
    )


def test_frozen_and_pre_0101_maps_are_inverse():
    # plan 0101 §3.1: FROZEN_KEY_NAMES is the inverse of PRE_0101_KEYS minus multihop_mt_v2
    inverse = {new: old for old, new in registry.PRE_0101_KEYS.items() if old != "multihop_mt_v2"}
    assert inverse == registry.FROZEN_KEY_NAMES
    assert registry.frozen_name("poetry") == "poetry"
    assert registry.rekey_pre_0101({"poetry": 1, "typo": 2}).keys() >= {"poetry"}
