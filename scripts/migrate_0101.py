"""Plan 0101 §8: the one-shot migration (the multi-token families take the plain keys, family
directories move under their category). Every move and mechanical rewrite comes from the literal
tables below; run once, kept as the record. NOT idempotent: ``apply`` refuses a migrated tree.

    uv run python scripts/migrate_0101.py plan [--out DIR]     # dry run: per-rule diffs, residue
    uv run python scripts/migrate_0101.py apply                # moves, rewrites, formatter, check
    uv run python scripts/migrate_0101.py check
    uv run python scripts/migrate_0101.py set DIR [--apply]    # one adapted set / lens store
    uv run python scripts/migrate_0101.py branch BASE..HEAD    # an open branch (plan §8.7)
"""

import argparse
import ast
import difflib
import hashlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tokenize
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- the tables (plan §0.1, §0.2)

# the key every renamed family had before -> its key after (registry.PRE_0101_KEYS)
KEYS = {
    "basic_readout": "basic_readout_st",
    "basic_readout_mt": "basic_readout",
    "multihop": "multihop_st",
    "multihop_mt": "multihop",
    "multihop_mt_v2": "multihop",
    "multilingual": "multilingual_st",
    "multilingual_mt": "multilingual",
    "typo": "typo_st",
    "typo_mt": "typo",
}
# family (key AFTER the rename) -> category directory
CATEGORY = {
    "association": "basic",
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
    "jlens_concept_pr": "jlens_comparison",  # `precision` at apply; renamed by plan 0105
}
CATEGORIES = tuple(dict.fromkeys(CATEGORY.values()))
# Directory moves made by LATER plans, applied by `check` after the recorded moves of `apply`
# (``APPLIED`` is a frozen record and keeps the paths of its day): plan 0105 renamed the category
# `precision` to `jlens_comparison`, bytes unchanged.
LATER_MOVES = (
    ("evals/precision", "evals/jlens_comparison"),
    ("src/wsbench/evals/precision", "src/wsbench/evals/jlens_comparison"),
)
UNMOVED = ("baselines", "fast", "hallucinationbench")
# the directory name each family has BEFORE the move -> its key after (32; no multihop_mt_v2 dir)
OLD_DIR = {
    old: new
    for new in CATEGORY
    for old in [next((o for o, n in KEYS.items() if n == new and o != "multihop_mt_v2"), new)]
}
# bank header "family" value (the source repo's vocabulary, never rewritten) -> key after (F9)
HEADER = {
    "basic-readout": "basic_readout_st",
    "basic-readout-hard": "basic_readout",
    "multihop": "multihop_st",
    "multihop-hard": "multihop",
    "multilingual": "multilingual_st",
    "multilingual-hard": "multilingual",
    "typo": "typo_st",
    "typo-hard": "typo",
}
# result-stamp prefixes per pre-0101 key (plan §3.2): the longest match names the holder
STAMPS = {
    "basic_readout": ("br-mc-", "bank-"),
    "basic_readout_mt": ("mc-brmt-", "mt-regex-", "mc-2026-"),
    "multihop": ("bank-",),
    "multihop_mt": ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
    "multihop_mt_v2": ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
    "multilingual": ("mcrx-", "bank-", "mt-regex-2026-10-30+leg-regex"),
    "multilingual_mt": ("mt-regex-",),
    "typo": ("bank-",),
    "typo_mt": ("mt-regex-", "mc-2026-"),
}
# test modules renamed with their family (plan §9.1)
TEST_MODULES = {
    "test_basic_readout_mt.py": "test_basic_readout.py",
    "test_basic_readout_mt_sarin_drop.py": "test_basic_readout_sarin_drop.py",
    "test_basic_readout.py": "test_basic_readout_st.py",
    "test_basic_readout_bank_v7.py": "test_basic_readout_st_bank_v7.py",
    "test_basic_readout_quote_line.py": "test_basic_readout_st_quote_line.py",
    "test_basic_readout_slices.py": "test_basic_readout_st_slices.py",
    "test_basic_readout_sum_check.py": "test_basic_readout_st_sum_check.py",
    "test_multihop_mt.py": "test_multihop.py",
    "test_multihop_mt_kant_option.py": "test_multihop_kant_option.py",
    "test_multihop.py": "test_multihop_st.py",
    "test_multihop_bank_v5.py": "test_multihop_st_bank_v5.py",
    "test_multihop_derived_forms.py": "test_multihop_st_derived_forms.py",
    "test_multihop_dropped_items.py": "test_multihop_st_dropped_items.py",
    "test_multihop_mc_bank_skip.py": "test_multihop_st_mc_bank_skip.py",
    "test_multihop_quote_line.py": "test_multihop_st_quote_line.py",
    "test_multihop_target_prefix.py": "test_multihop_st_target_prefix.py",
    "test_multilingual_mt.py": "test_multilingual.py",
    "test_multilingual.py": "test_multilingual_st.py",
    "test_typo_mt.py": "test_typo.py",
    "test_typo.py": "test_typo_st.py",
}
# R9: python identifiers that embed a key, per file (path BEFORE the move)
IDENTIFIERS = {
    "src/wsbench/adapt/families.py": {
        "_basic_readout_mt": "_basic_readout",
        "_basic_readout": "_basic_readout_st",
        "_multihop": "_multihop_st",
    },
    "src/wsbench/baselines/lucky_guessing.py": {
        "_basic_readout": "_basic_readout_st",
        "_multihop": "_multihop_st",
    },
    "src/wsbench/readplan.py": {"_multihop": "_multihop_st"},
}
# KEEP (plan §8.2). Never read for rewriting:
KEEP_FILES = {
    "src/wsbench/registry.py",
    "scripts/migrate_0101.py",
    "scripts/manifest_0101.py",
    "scripts/migrate_0101_residue.txt",
    "tests/test_migrate_0101.py",
    "tests/test_family_paths.py",
    ".claude/skills/adapt-bank/SKILL_AUDIT.md",
    ".claude/skills/adapt-bank/SKILL_AUDIT_RESPONSE.md",
}
# tests of the legacy / rename machinery: R1 (imports) and R2 / R3 (data paths) only
KEEP_TESTS = {
    "tests/test_rename_multihop_mt.py",
    "tests/test_legacy_family_names.py",
    "tests/test_rename_wrong_intermediate.py",
    "tests/test_adapted_exclusions_alias.py",
}
# ... and every test file that mentions one of these (computed by grep at the commit it runs on)
KEEP_GREP = re.compile(
    r"\b(canonical|legacy_names|lookup_names|stored_family|family_dir|hash_name|"
    r"REUSED_FAMILY_KEYS|LEGACY_FAMILY_NAMES|multihop_mt_v2|multihop_mt_regex|wrong_bridge)\b"
)
# a key literal used for its SPELLING is never rewritten (plan §2.3)
SPELLING_METHODS = {
    "startswith",
    "endswith",
    "removeprefix",
    "removesuffix",
    "split",
    "rsplit",
    "partition",
    "replace",
    "find",
    "rfind",
    "index",
    "count",
    "fnmatch",
    "fnmatchcase",
}
# `"<key>" in <name>`: these names hold a STRING (an id, a line, a path), not a collection of keys
STRING_NAMES = {"name", "item_id", "iid", "ln", "line", "text", "path", "stem", "label"}
STRING_ATTRS = {"stdout", "stderr", "name", "stem", "text"}
# a name compared with a key-spelled literal that is NOT a family: `sub == "typo"`, `cfg.screen`
FIELD_NAMES = re.compile(r"sub|screen|kind", re.I)
# Sites no rule rewrites, (path BEFORE the move, text on the line); each is listed in the dry
# run's kept-sites.txt with its reason (review c3):
KEEP_SITES = {
    # W3: one constant is both a read path and a string written into the bank header
    ("scripts/introspection_build_v2.py", 'VEC = "evals/introspection/vectors"'),
    # W4: meta written into the vendored (committed) Wikidata tables
    ("scripts/build_wd_tables.py", '"items": "evals/wrong_intermediate/items_v4.json"'),
    # W6: a SCREEN kind of multilingual_typo (`question | complete | describe | typo`)
    ("scripts/mc_options_r5.py", '"typo",'),
    ("scripts/mc_options_r5.py", '"typo": "A short text in another language'),
    ("scripts/mc_options_r5.py", 'cfg.screen == "typo"'),
    # W7: `_header` writes `v1_bank = evals/<this argument>/items.json` into the bank header
    ("scripts/build_multilingual_v2.py", '_header(v1, "multilingual",'),
    ("scripts/build_multilingual_v2.py", '_header(v1, "multilingual_mt",'),
    # W9: the expectation of an input that sits inside a longer string (residue): edit both
    ("tests/test_adapt_dataround.py", "families=multihop_mt waves=40"),
}
# `"<key>" in <name>` where <name> is a STRING, not a collection of keys (file, line text)
IN_STRING = {("scripts/evidence_mh2.py", '"multihop" in ln')}
LIVE_CODE = ("src/", "atlas/", "viewer_app/", ".claude/skills/")  # R3 is reported there
RULES = ("R1", "R2", "R3", "R8", "R4", "R9", "R5", "R6", "R7")  # priority on overlap
STAGING = ".migrate_0101_staging"
MARKER = "migrate_0101_applied"
RECORD = "migrate_0101_before"
RESIDUE_FILE = "scripts/migrate_0101_residue.txt"
RESIDUE_CLASSES = ("leave", "edit")  # what the reviewer writes in place of `?`
MANIFEST = "tests/golden/manifest_0101_pre.json"
SET_MARKER = ("family_keys", "0101")
BARE_KEYS = ("basic_readout", "multihop", "multilingual", "typo")
APPLIED = "scripts/migrate_0101_applied.json"  # the committed record of `apply` (commit 4)


def _alt(names: Iterable[str]) -> str:
    return "|".join(sorted(map(re.escape, names), key=len, reverse=True))


_FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", -1)  # the text of an f-string (3.12+)
B0, B1 = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"
KEY_RE = re.compile(rf"{B0}({_alt(KEYS)}){B1}")
END = r"(?=[/\"'\s)`,;:\]}>|]|\.(?:\s|$)|$)"  # what may follow a path's family segment
R1_RE = re.compile(rf"(wsbench)([./])(evals)\2({_alt(OLD_DIR)}){B1}")
R1_FROM_RE = re.compile(
    rf"^(\s*from wsbench\.evals) import ({_alt(OLD_DIR)})( as \w+)?[ \t]*$", re.M
)
R2_RE = re.compile(rf"(?<![A-Za-z0-9_.-])(?<!wsbench/)evals/({_alt(OLD_DIR)}){END}")
R3_RE = re.compile(rf'"evals"\s*/\s*"({_alt(OLD_DIR)})"')
R4_TEXT_RE = re.compile(rf"([\"'])({_alt(KEYS)})\1")
R5_RE = re.compile(rf"{B0}((?:--)?famil(?:y|ies)[= ])([A-Za-z0-9_,]+)(?![A-Za-z0-9_-])")
# the `adapt` SUBCOMMAND that is named after its family (W10): `$A multihop_mt`, `adapt multihop_mt`
R5_CMD_RE = re.compile(
    r"((?:\$A|wsbench\.adapt|(?<![A-Za-z0-9_])adapt) )(multihop_mt)(?![A-Za-z0-9_-])"
)
# R2 never rewrites a string STORED in bank bytes / plan rows (W1-W3), nor a path of the
# global-workspace checkout a builder reads (W4): the same spelling, another repository
STORED_PATH_RE = re.compile(
    r"evals/introspection/vectors/(?:concept|gaussian)_vectors_L\d+\.npy|"
    r"evals/model_multihop/frozen_v2\.json"
)
FOREIGN_PREFIX_RE = re.compile(r"(?:<gw>/|gw-mmh/|global-workspace |/root/gw[\w-]*/)$")
# a family README sits one level deeper after the move: its links to the repository root
README_UP_RE = re.compile(r"(?<=\]\()\.\./\.\./(?!\.\.)")
# a line about a stored FIELD whose values are spelled like keys (`subfamily`: `typo`)
FIELD_LINE_RE = re.compile(r"subfamil")
R6_RE = re.compile(rf"{B0}({_alt(KEYS)})(\.jsonl\.meta\.json|\.jsonl|\.json){B1}")
R6_DIR_RE = re.compile(rf"(?<=/)({_alt(KEYS)})(?=/)")
R7_RE = re.compile(rf"(?<!`)(`{{1,2}})({_alt(KEYS)})\1(?!`)|\*\*({_alt(KEYS)})\*\*")
R8_RE = re.compile(rf"(WSB_BANK_FILE_)({_alt(k.upper() for k in KEYS)})(?![A-Za-z0-9_])")
FAMILY_FIELD_RE = re.compile(  # non-python text: a "family" entry or comparison before a literal
    r"""(["']family["']\s*:\s*|\[["']family["']\]\s*[=!]=\s*|\.get\(["']family["']\)\s*[=!]=\s*)$"""
)
FIXTURE_LINE_RE = re.compile(r"fixtures|golden|adapted_v1")
# a line of prose about the HISTORY of a key: its keys are former ones by intent, so the prose
# rules (R5 / R6 / R7) leave the line to the residue
HISTORY_LINE_RE = re.compile(
    r"multihop_mt_v2|multihop_mt_regex|wrong_bridge|HASH_FAMILY_NAMES|REUSED_FAMILY_KEYS|"
    r"LEGACY_FAMILY_NAMES|\b(?:then|once|was|still|formerly|been|now) keyed\b|keyed `|"
    r"\bhash (?:key|name)\b|\bhash(?:es)?\s+(?:as|under)\b|its hash$|key becomes|"
    r"\bformer key|\brenamed\b|\b(?:was|were) (?:removed|deleted)\b|\bremoved (?:on|from)\b"
)
# in python prose (comments, docstrings) only the keys that are not also English words or
# parameter names are rewritten as a code span: ``typo`` may be a variable
PY_SPAN_KEYS = frozenset(k for k in KEYS if k.endswith(("_mt", "_mt_v2")) or k == "basic_readout")
# post-migration marks (plan §8.1): a `_st` key, or a (category, family-of-that-category) pair
_PAIRS = "|".join(
    rf"{re.escape(c)}[./]({_alt(f for f, cat in CATEGORY.items() if cat == c)})" for c in CATEGORIES
)
MARK_RES = (
    re.compile(rf"{B0}(basic_readout|multihop|multilingual|typo)_st{B1}"),
    re.compile(rf"(?<![A-Za-z0-9_.-])evals/(?:{_PAIRS}){B1}".replace("[./]", "/")),
    re.compile(rf"wsbench([./])evals\1(?:{_PAIRS}){B1}"),
)


class Refused(SystemExit):
    """A precondition failed: nothing was changed (exit 2)."""

    def __init__(self, why: str):
        print(f"migrate_0101: refused: {why}", file=sys.stderr)
        super().__init__(2)


# ---------------------------------------------------------------- git and files


def git(root: Path, *args: str, check: bool = True) -> str:
    got = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and got.returncode:
        raise SystemExit(f"git {' '.join(args)}: {got.stderr.strip()}")
    return got.stdout


def git_dir(root: Path) -> Path:
    return Path(git(root, "rev-parse", "--absolute-git-dir").strip())


def tracked(root: Path) -> list[str]:
    """Every tracked file, plus (for a dry run on a tree with uncommitted new files) the
    untracked ones git does not ignore; ``apply`` runs on a clean tree, where the two agree."""
    got = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    return sorted({f for f in got.split("\0") if f and (root / f).is_file()})


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def has_mark(text: str) -> str:
    """The first post-migration mark in ``text`` ("" when it holds none)."""
    for rx in MARK_RES:
        m = rx.search(text)
        if m:
            return m.group(0)
    return ""


# ---------------------------------------------------------------- scope


def _is_text_scope(path: str) -> bool:
    """Plan §8.3 phase 3: the files the text rewrite covers (paths BEFORE the move)."""
    p = Path(path)
    top, suf = p.parts[0], p.suffix
    if path in KEEP_FILES:
        return False
    if top in ("src", "tests") and suf == ".py":
        return not path.startswith(("tests/golden/", "tests/fixtures/", "src/wsbench/adapt/data/"))
    if top in ("scripts", "atlas") and suf in (".py", ".sh"):
        return True
    if top == "viewer_app" and suf == ".py" and len(p.parts) == 2:
        return True
    if path.startswith(".claude/skills/") and suf in (".py", ".md"):
        return True
    if path in (
        "docs/producing_readouts.md",
        "docs/summarizer.md",
        "docs/adapt_judge_inputs.md",
        "evals/baselines/README.md",
        "evals/fast/README.md",
        "adapted/README.md",
    ):
        return True
    return len(p.parts) == 3 and top == "evals" and p.parts[1] in OLD_DIR and p.name == "README.md"


def text_scope(root: Path) -> list[str]:
    return sorted(f for f in tracked(root) if _is_text_scope(f))


def keep_tests(root: Path) -> set[str]:
    """The test files that get R1 / R2 / R3 only: the four named ones plus every test that
    mentions the legacy machinery (computed here, on the tree the script runs on)."""
    out = {f for f in KEEP_TESTS if (root / f).is_file()}
    for f in tracked(root):
        is_test = f.startswith("tests/") and f.endswith(".py") and _is_text_scope(f)
        if is_test and KEEP_GREP.search((root / f).read_text(encoding="utf-8")):
            out.add(f)
    return out


# ---------------------------------------------------------------- moves


def _dest_dir(tree: str, old: str) -> str:
    new = OLD_DIR[old]
    return f"{tree}/{CATEGORY[new]}/{new}"


def moves(root: Path, strict: bool = True) -> list[tuple[str, str]]:
    """Every ``(source, destination)`` rename, directories and files, from the tables. With
    ``strict`` a missing family directory is an error."""
    out: list[tuple[str, str]] = []
    for tree in ("evals", "src/wsbench/evals"):
        for old in OLD_DIR:
            if (root / tree / old).is_dir():
                out.append((f"{tree}/{old}", _dest_dir(tree, old)))
            elif strict:
                raise Refused(f"{tree}/{old} is missing")
    files = tracked(root)
    for f in files:
        p = Path(f)
        parts = p.parts
        name = p.name
        stem = name.split(".", 1)[0]
        ext = name[len(stem) :]
        if parts[0] == "adapted" and len(parts) == 3 and ext == ".json" and stem in KEYS:
            out.append((f, f"adapted/{parts[1]}/{KEYS[stem]}.json"))
        elif parts[:2] == ("examples", "readouts") and len(parts) == 3 and stem in KEYS:
            if ext in (".jsonl", ".jsonl.meta.json"):
                out.append((f, f"examples/readouts/{KEYS[stem]}{ext}"))
        elif parts[:2] == ("evals", "baselines") and len(parts) == 4 and stem in KEYS:
            if parts[2] in ("topics", "confusers") and ext == ".json":
                out.append((f, f"evals/baselines/{parts[2]}/{KEYS[stem]}.json"))
        elif parts[0] == "tests" and len(parts) == 2 and name in TEST_MODULES:
            out.append((f, f"tests/{TEST_MODULES[name]}"))
    overlays = {
        "/".join(Path(f).parts[:3])
        for f in files
        if Path(f).parts[0] == "adapted" and len(Path(f).parts) > 3 and Path(f).parts[2] in KEYS
    }
    out += [(d, f"{Path(d).parent.as_posix()}/{KEYS[Path(d).name]}") for d in sorted(overlays)]
    dests = Counter(d for _s, d in out)
    twice = [d for d, n in dests.items() if n > 1]
    if twice:
        raise Refused(f"two sources land on {twice[:3]}")
    return out


def new_path(path: str, mv: list[tuple[str, str]]) -> str:
    """Where a tracked file sits after the moves."""
    for src, dst in mv:
        if path == src:
            return dst
        if path.startswith(src + "/"):
            return dst + path[len(src) :]
    return path


def path_today(path: str, mv: list[tuple[str, str]]) -> str:
    """``new_path`` followed by the moves of later plans (``LATER_MOVES``): where a file of the
    base commit sits in today's tree. For a record whose moves were made under the category
    names of the apply commit (``APPLIED``); moves computed from today's ``CATEGORY`` already
    end in today's directories and pass through unchanged."""
    return new_path(new_path(path, mv), list(LATER_MOVES))


# ---------------------------------------------------------------- the text rules


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    new: str
    rule: str


def _offsets(text: str) -> list[int]:
    out, n = [0], 0
    for line in text.split("\n"):
        n += len(line) + 1
        out.append(n)
    return out


def _py_literals(text: str, path: str) -> tuple[list[Span], set[int], list[tuple[int, int]]]:
    """Python source: the R4 spans (a whole string literal that IS a key, outside the KEEP
    patterns), the start offsets of key literals KEPT for a KEEP pattern, and the spans of every
    string and comment token (R5 / R6 / R7 apply only inside those)."""
    lines = text.split("\n")
    offs = _offsets(text)

    def pos(lineno: int, col: int) -> int:
        return offs[lineno - 1] + len(lines[lineno - 1].encode("utf-8")[:col].decode("utf-8"))

    tree = ast.parse(text)
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node

    def is_field(n: ast.AST) -> bool:
        """``x["<field>"]`` / ``x.get("<field>")``: a stored field (``family``, ``subfamily``,
        ...) whose values are data vocabulary, compared or assigned."""
        if isinstance(n, ast.Subscript):
            return isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            return bool(n.args) and isinstance(n.args[0], ast.Constant)
        return False

    def is_field_name(n: ast.AST) -> bool:
        """A name that holds such a field's value: ``sub``, ``cfg.screen``, ``kind``."""
        ident = n.id if isinstance(n, ast.Name) else getattr(n, "attr", "")
        return isinstance(n, ast.Name | ast.Attribute) and bool(FIELD_NAMES.search(ident))

    def collapses(lit: ast.Dict | ast.Set) -> bool:
        """Two members of one literal would translate to the same key."""
        keys = lit.keys if isinstance(lit, ast.Dict) else lit.elts
        new = [KEYS[k.value] for k in keys if isinstance(k, ast.Constant) and k.value in KEYS]
        pairs = zip(lit.keys, lit.values, strict=True) if isinstance(lit, ast.Dict) else ()
        same = any(
            isinstance(k, ast.Constant)
            and isinstance(v, ast.Constant)
            and k.value in KEYS
            and v.value in KEYS
            and KEYS[k.value] == KEYS[v.value]
            for k, v in pairs
        )
        return same or len(set(new)) < len(new)

    def kept(node: ast.Constant) -> bool:
        up = parent.get(id(node))
        if isinstance(up, ast.Attribute) and up.attr in SPELLING_METHODS:
            return True  # "key".startswith(...)
        if isinstance(up, ast.Call) and node in up.args and isinstance(up.func, ast.Attribute):
            base = up.func.value
            if up.func.attr in SPELLING_METHODS or (isinstance(base, ast.Name) and base.id == "re"):
                return True
        if any(f == path and snip in lines[node.lineno - 1] for f, snip in KEEP_SITES):
            return True
        if isinstance(up, ast.Call) and node in up.args:
            fn = up.func
            if (fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")) in SPELLING_METHODS:
                return True  # fnmatch(name, "key")
        if isinstance(up, ast.Dict | ast.Set) and collapses(up):
            return True  # {"multihop_mt_v2": "multihop_mt"}: two members would become one
        if isinstance(up, ast.Tuple | ast.List | ast.Set):
            cmp = parent.get(id(up))
            if (
                isinstance(cmp, ast.Compare)
                and up in cmp.comparators
                and isinstance(cmp.ops[0], ast.In | ast.NotIn)
                and (is_field(cmp.left) or is_field_name(cmp.left))
            ):
                return True  # it.get("subfamily") in ("typo", "novel")
        if isinstance(up, ast.Dict):
            for k, v in zip(up.keys, up.values, strict=True):
                # a FIELD value ("family", "subfamily", "by", ...): bank or row vocabulary as
                # often as a key, so only a human can tell (a key -> key table is rewritten)
                if v is node and isinstance(k, ast.Constant) and k.value not in KEYS:
                    return True
        if isinstance(up, ast.Assign) and any(is_field(t) for t in up.targets):
            return True  # x["subfamily"] = "typo"
        if isinstance(up, ast.Compare):
            sides = [up.left, *up.comparators]
            if any(is_field(s) or is_field_name(s) for s in sides if s is not node):
                return True  # x["subfamily"] == "typo", sub == "typo", cfg.screen == "typo"
            if up.left is node and isinstance(up.ops[0], ast.In | ast.NotIn):
                right = up.comparators[0]
                if isinstance(right, ast.JoinedStr) or (
                    isinstance(right, ast.Constant) and isinstance(right.value, str)
                ):
                    return True
                if (isinstance(right, ast.Name) and right.id in STRING_NAMES) or (
                    isinstance(right, ast.Attribute) and right.attr in STRING_ATTRS
                ):
                    return True  # "multihop" in item_id
                if (path, lines[node.lineno - 1].strip()) in IN_STRING or any(
                    f == path and snip in lines[node.lineno - 1] for f, snip in IN_STRING
                ):
                    return True
        if isinstance(up, ast.keyword) and up.arg == "family":
            call: ast.AST | None = parent.get(id(up))
            while call is not None:  # family="<key>" inside dict(...) / json.dumps(...)
                if isinstance(call, ast.Call):
                    fn = call.func
                    name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
                    if name in ("dict", "dumps", "dump"):
                        return True
                call = parent.get(id(call))
        return False

    spans: list[Span] = []
    keeps: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and node.value in KEYS):
            continue
        if not isinstance(node.value, str) or node.end_lineno != node.lineno:
            continue
        a, b = pos(node.lineno, node.col_offset), pos(node.lineno, node.end_col_offset or 0)
        if not re.fullmatch(rf"([\"']){re.escape(node.value)}\1", text[a:b]):
            continue  # a part of a longer (concatenated, prefixed or f-) string: not a key literal
        if kept(node):
            keeps.add(a)
        else:
            spans.append(Span(a, b, text[a] + KEYS[node.value] + text[a], "R4"))
    prose: list[tuple[int, int]] = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type in (tokenize.STRING, tokenize.COMMENT, _FSTRING_MIDDLE):
            a = offs[tok.start[0] - 1] + tok.start[1]
            b = offs[tok.end[0] - 1] + tok.end[1]
            prose.append((a, b))
    return spans, keeps, prose


# path -> the 0-based lines where a KEEP site, a stored string or a foreign path was left alone
_KEPT_SITES: dict[str, list[int]] = {}


def _identifiers(text: str, table: Mapping[str, str]) -> list[Span]:
    offs = _offsets(text)
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.NAME and tok.string in table:
            a = offs[tok.start[0] - 1] + tok.start[1]
            out.append(Span(a, a + len(tok.string), table[tok.string], "R9"))
    return out


def find_spans(text: str, path: str) -> tuple[list[Span], list[int]]:
    """Every rule's proposed rewrites of one file (``path`` BEFORE the move), overlaps resolved
    by rule priority, and the offsets of R3 joins in live code (reported, never rewritten)."""
    if mark := has_mark(text):
        raise Refused(f"{path} already holds a post-migration mark ({mark!r})")
    cand: list[Span] = []
    for m in R1_RE.finditer(text):
        sep, new = m.group(2), OLD_DIR[m.group(4)]
        cand.append(
            Span(m.start(), m.end(), f"wsbench{sep}evals{sep}{CATEGORY[new]}{sep}{new}", "R1")
        )
    for m in R1_FROM_RE.finditer(text):
        old = m.group(2)
        new = OLD_DIR[old]
        alias = m.group(3) or (f" as {old}" if new != old else "")
        cand.append(
            Span(m.start(), m.end(), f"{m.group(1)}.{CATEGORY[new]} import {new}{alias}", "R1")
        )
    lines = text.split("\n")
    offs = _offsets(text)
    kept_sites: list[int] = []

    def lineno(at: int) -> int:
        lo, hi = 0, len(offs) - 1
        while lo < hi:  # the last line start <= at
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if offs[mid] <= at else (lo, mid - 1)
        return lo

    def site(at: int) -> bool:
        line = lines[lineno(at)]
        return any(f == path and snip in line for f, snip in KEEP_SITES)

    for m in R2_RE.finditer(text):
        tail = text[m.start() : m.start() + 120]
        before = text[max(0, m.start() - 24) : m.start()]
        if STORED_PATH_RE.match(tail) or FOREIGN_PREFIX_RE.search(before) or site(m.start()):
            kept_sites.append(m.start())
            continue
        new = OLD_DIR[m.group(1)]
        cand.append(Span(m.start(), m.end(), f"evals/{CATEGORY[new]}/{new}", "R2"))
    if re.fullmatch(rf"evals/({_alt(OLD_DIR)})/README\.md", path):
        for m in README_UP_RE.finditer(text):
            cand.append(Span(m.start(), m.end(), "../../../", "R2"))
    if re.search(r"^\s*from wsbench\.evals import [^\n]*,", text, re.M):
        raise Refused(f"{path}: a multi-name `from wsbench.evals import a, b` (split it first)")
    live_joins: list[int] = []
    for m in R3_RE.finditer(text):
        if path.startswith(LIVE_CODE):
            live_joins.append(m.start())
        else:
            new = OLD_DIR[m.group(1)]
            cand.append(Span(m.start(), m.end(), f'"evals" / "{CATEGORY[new]}" / "{new}"', "R3"))
    for m in R8_RE.finditer(text):
        new = KEYS[m.group(2).lower()].upper()
        cand.append(Span(m.start(), m.end(), m.group(1) + new, "R8"))
    prose: list[tuple[int, int]] | None = None
    strings: list[tuple[int, int]] = []
    fenced: list[tuple[int, int]] = []
    if path.endswith(".py"):
        r4, keeps, prose = _py_literals(text, path)
        cand += r4
        kept_sites += [a for a in keeps if site(a)]
        strings = [(a, b) for a, b in prose if text[a] != "#" and "\n" in text[a:b]]
        if path in IDENTIFIERS:
            cand += _identifiers(text, IDENTIFIERS[path])
    else:
        # an excerpt of a frozen file quoted in a ```json block stays verbatim (W8)
        fenced = [m.span() for m in re.finditer(r"^```json\n.*?^```", text, re.M | re.S)]

    def in_prose(a: int, b: int) -> bool:
        return prose is None or any(s <= a and b <= e for s, e in prose)

    def paragraph(at: int) -> str:
        """The lines a history remark covers: the blank-line-delimited block around ``at``; in
        python the docstring's own paragraph, a run of comment lines, or the one line."""
        n = lineno(at)
        doc = next(((a, b) for a, b in strings if a <= at < b), None)
        comment = lines[n].lstrip().startswith("#")
        if prose is not None and doc is None and not comment:
            return lines[n]

        def inside(k: int) -> bool:
            if not 0 <= k < len(lines) or not lines[k].strip():
                return False
            if doc is not None:
                return doc[0] <= offs[k] + len(lines[k]) and offs[k] < doc[1]
            return prose is None or lines[k].lstrip().startswith("#")

        lo = hi = n
        while inside(lo - 1):
            lo -= 1
        while inside(hi + 1):
            hi += 1
        return "\n".join(lines[lo : hi + 1])

    def history(at: int) -> bool:
        return bool(HISTORY_LINE_RE.search(paragraph(at)))

    def frozen_text(at: int) -> bool:
        """No prose rule applies: a quoted frozen file, a stored-field line, a KEEP site."""
        if any(a <= at < b for a, b in fenced) or FIELD_LINE_RE.search(lines[lineno(at)]):
            return True
        if site(at):
            kept_sites.append(at)
            return True
        return False

    if prose is None:
        for m in R4_TEXT_RE.finditer(text):
            before = text[max(0, m.start() - 40) : m.start()]
            if FAMILY_FIELD_RE.search(before) or history(m.start()) or frozen_text(m.start()):
                continue
            q = m.group(1)
            cand.append(Span(m.start(), m.end(), q + KEYS[m.group(2)] + q, "R4"))
    for m in R5_RE.finditer(text):
        parts = m.group(2).split(",")
        flag = m.group(1)
        if flag.endswith(" ") and not flag.startswith("--"):
            continue  # "family multihop" is prose; only `--family multihop` is a CLI form
        if not any(p in KEYS for p in parts) or not in_prose(m.start(), m.end()):
            continue
        if history(m.start()) or frozen_text(m.start()):
            continue
        new = ",".join(KEYS.get(p, p) for p in parts)
        cand.append(Span(m.start(2), m.end(2), new, "R5"))
    for m in R5_CMD_RE.finditer(text):
        if in_prose(m.start(), m.end()) and not history(m.start()) and not frozen_text(m.start()):
            cand.append(Span(m.start(2), m.end(2), KEYS[m.group(2)], "R5"))
    for m in [*R6_RE.finditer(text), *R6_DIR_RE.finditer(text)]:
        if not in_prose(m.start(), m.end()) or FIXTURE_LINE_RE.search(lines[lineno(m.start())]):
            continue
        if history(m.start()) or frozen_text(m.start()):
            continue
        cand.append(Span(m.start(1), m.end(1), KEYS[m.group(1)], "R6"))
    for m in R7_RE.finditer(text):
        key = m.group(2) or m.group(3)
        if not in_prose(m.start(), m.end()) or (path.endswith(".py") and key not in PY_SPAN_KEYS):
            continue
        if history(m.start()) or frozen_text(m.start()):
            continue
        a = m.start(2) if m.group(2) else m.start(3)
        cand.append(Span(a, a + len(key), KEYS[key], "R7"))
    _KEPT_SITES[path] = sorted({lineno(at) for at in kept_sites})
    cand.sort(key=lambda s: (RULES.index(s.rule), s.start))
    taken: list[Span] = []
    for s in cand:
        if all(s.end <= t.start or t.end <= s.start for t in taken):
            taken.append(s)
    return sorted(taken, key=lambda s: s.start), live_joins


def apply_spans(text: str, spans: Iterable[Span]) -> str:
    out, at = [], 0
    for s in sorted(spans, key=lambda s: s.start):
        out += [text[at : s.start], s.new]
        at = s.end
    return "".join([*out, text[at:]])


def allowed_rules(path: str, keep: set[str]) -> tuple[str, ...]:
    """The rules applied to a file: everything, or imports and data paths only for a KEEP test."""
    return ("R1", "R2", "R3") if path in keep else RULES


def residue_of(text: str, spans: list[Span], path: str) -> list[str]:
    """``path:line:text`` of every word-boundary key hit that no rule rewrites (prose, unquoted
    keys, KEEP patterns, bank-header vocabulary), one row per line."""
    covered = [(s.start, s.end) for s in spans]
    offs = _offsets(text)
    lines = text.split("\n")
    rows: dict[int, str] = {}
    for m in KEY_RE.finditer(text):
        if any(a <= m.start() and m.end() <= b for a, b in covered):
            continue
        n = next(i for i, o in enumerate(offs) if o > m.start()) - 1
        rows[n] = f"{path}:{n + 1}:{lines[n].strip()}"
    return [rows[n] for n in sorted(rows)]


DYNAMIC_RES = (
    re.compile(r'"evals"\s*/\s*(?!"|\')[A-Za-z_(]'),  # ... / "evals" / family
    re.compile(r"evals/\{"),  # f"evals/{family}/..."
    re.compile(r"\b\w*EVALS\w*\s*/\s*"),  # EVALS / "multihop/x.json", EVALS / sub
    re.compile(r'Path\("evals"\)\s*/'),  # Path("evals") / family
    re.compile(
        r"evals.*\.(?:glob|rglob|iterdir)\(|\.(?:glob|rglob)\([^)]*evals"
    ),  # a walk of evals/
)


def dynamic_paths(text: str, path: str) -> list[str]:
    """Lines no rule can rewrite and no key hit reveals: a family path built from a VARIABLE or
    from a name bound to the evals root, and every walk (``glob`` / ``rglob`` / ``iterdir``)
    of ``evals/`` or ``src/wsbench/evals``, which finds categories, not families, after the
    move (a guard built on one would pass vacuously). Listed for the hand edits."""
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        if any(rx.search(line) for rx in DYNAMIC_RES):
            out.append(f"{path}:{n}:{line.strip()}")
    return out


def shell_words(text: str, path: str) -> list[str]:
    """Shell lines with a family key as a bare WORD (a list, quoted or not, a case label, a loop
    word): after the swap `multihop` names the other family, and no rule rewrites a bare word."""
    if not path.endswith(".sh"):
        return []
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        bare = re.sub(r"(?:^|\s)#.*$", "", line)  # a quoted word list is a list too
        if KEY_RE.search(re.sub(r"famil(?:y|ies)=\S+", "", bare)):
            out.append(f"{path}:{n}:{line.strip()}")
    return out


# ---------------------------------------------------------------- JSON files rewritten in place


def _tr(key: str) -> str:
    return KEYS.get(key, key)


def _rekey(d: Any, where: str) -> Any:
    if not isinstance(d, dict):
        return d
    out: dict[str, Any] = {}
    for k, v in d.items():
        if _tr(k) in out:
            raise Refused(f"{where}: two keys land on {_tr(k)!r}")
        out[_tr(k)] = v
    return out


def _load_styled(path: Path) -> tuple[Any, str]:
    """A JSON file and its trailing newline; any other style than ``indent=1,
    ensure_ascii=False`` is refused (the untouched remainder must stay byte-identical)."""
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    body = json.dumps(doc, indent=1, ensure_ascii=False)
    for tail in ("\n", ""):
        if body + tail == raw:
            return doc, tail
    raise Refused(f"{path} does not round-trip as json.dumps(indent=1, ensure_ascii=False)")


def _floor_like(doc: Any, where: str) -> Any:
    """A file keyed by family at the top level (floors, ATI): top-level keys, ``_not_gated``,
    ``_source.pins.plan_sha`` keys and ``_source.kept_from[].families``; an entry's own
    ``"family"`` value. No rate, stamp, bank_sha or id list changes."""
    out = _rekey(doc, where)
    for k, v in list(out.items()):
        if isinstance(v, dict) and isinstance(v.get("family"), str) and not k.startswith("_"):
            out[k] = {**v, "family": _tr(v["family"])}
    if isinstance(out.get("_not_gated"), dict):
        out["_not_gated"] = _rekey(out["_not_gated"], where + " _not_gated")
    src = out.get("_source")
    if isinstance(src, dict):
        src = dict(src)
        pins = src.get("pins")
        if isinstance(pins, dict) and isinstance(pins.get("plan_sha"), dict):
            src["pins"] = {**pins, "plan_sha": _rekey(pins["plan_sha"], where + " pins")}
        if isinstance(src.get("kept_from"), list):
            src["kept_from"] = [
                {**e, "families": [_tr(f) for f in e["families"]]}
                if isinstance(e, dict) and isinstance(e.get("families"), list)
                else e
                for e in src["kept_from"]
            ]
        out["_source"] = src
    return out


def _translate(kind: str, doc: Any, where: str) -> Any:
    if kind == "floor":
        return _floor_like(doc, where)
    if kind == "topic":
        return {**doc, "family": _tr(doc["family"])} if isinstance(doc.get("family"), str) else doc
    if kind == "report":
        out = dict(doc)
        for sec in ("families", "drops", "patches"):
            if isinstance(out.get(sec), dict):
                if sec != "families":
                    for iid in out[sec].get("multihop_mt") or {}:
                        if not str(iid).startswith("mh2-"):
                            raise Refused(f"{where}: {sec}.multihop_mt holds {iid!r} (not mh2-*)")
                out[sec] = _rekey(out[sec], f"{where} {sec}")
        out[SET_MARKER[0]] = SET_MARKER[1]
        return out
    if kind == "floors":
        out = dict(doc)
        if isinstance(out.get("families"), dict):
            out["families"] = _rekey(out["families"], where)
        if isinstance(out.get("protocols"), dict):
            protos = {}
            for name, p in out["protocols"].items():
                p = dict(p) if isinstance(p, dict) else p
                for sec in ("families", "prompt_version"):
                    if isinstance(p, dict) and isinstance(p.get(sec), dict):
                        p[sec] = _rekey(p[sec], f"{where} {name}.{sec}")
                protos[name] = p
            out["protocols"] = protos
        return out
    if kind == "scores":
        rows = []
        for r in doc:
            r = dict(r)
            if isinstance(r.get("family"), str) and r["family"] in KEYS:
                want = _stamp_holder(r["family"], str(r.get("instrument") or ""))
                if want is None:
                    raise Refused(f"{where}: {r['family']} row stamped {r.get('instrument')!r}")
                r["family"] = want
            if isinstance(r.get("families"), list):
                r["families"] = [_tr(f) for f in r["families"]]
            rows.append(r)
        return rows
    raise ValueError(kind)


def _stamp_holder(old_key: str, stamp: str) -> str | None:
    """The key AFTER the rename of the family that wrote ``stamp`` under ``old_key``: by the
    longest matching prefix over the two members of its pair; None when no prefix matches or
    the stamp is the OTHER member's (a mis-keyed row)."""
    new = KEYS[old_key]
    partner_old = next((o for o in KEYS if KEYS[o] != new and KEYS[o].removesuffix("_st")
                        == new.removesuffix("_st") and o != "multihop_mt_v2"), None)  # fmt: skip
    best, who = -1, None
    for key in filter(None, (old_key, partner_old)):
        for pre in STAMPS[key]:
            if stamp.startswith(pre) and len(pre) > best:
                best, who = len(pre), key
    return new if who == old_key else None


def json_kind(path: str) -> str | None:
    """Which in-place translation a tracked JSON file gets (None: untouched)."""
    p = Path(path)
    parts = p.parts
    if parts[:2] == ("evals", "baselines") and p.suffix == ".json":
        if len(parts) == 3 and not p.name.startswith("lucky_guessing_moral"):
            return "floor"
        if len(parts) == 4 and parts[2] in ("topics", "confusers"):
            return "topic"
    if parts[0] == "adapted" and len(parts) >= 3 and p.suffix == ".json":
        rest = "/".join(parts[2:])
        if rest == "report.json":
            return "report"
        if rest == "floors/floors.json":
            return "floors"
        if rest in ("floors/prompt_only_summary.json", "floors/lucky_guessing.json"):
            return "floor"
        if len(parts) == 3 and p.name.startswith("anti_text_inversion"):
            return "floor"
        if rest == "lenses/scores.json":
            return "scores"
    return None


def json_rewrites(root: Path) -> dict[str, str]:
    """``{path BEFORE the move: new text}`` of every in-place JSON file that changes."""
    out = {}
    for f in tracked(root):
        kind = json_kind(f)
        if kind is None:
            continue
        doc, tail = _load_styled(root / f)
        new = json.dumps(_translate(kind, doc, f), indent=1, ensure_ascii=False) + tail
        if new != (root / f).read_text(encoding="utf-8"):
            out[f] = new
    return out


def check_reports(root: Path) -> list[str]:
    """Every adapted ``report.json`` ``families`` entry of a renamed family against the set's
    bank file: the bank's header value is the family's (F9). Returns the problems."""
    bad = []
    for f in tracked(root):
        if json_kind(f) != "report":
            continue
        doc = json.loads((root / f).read_text(encoding="utf-8"))
        for old in doc.get("families") or {}:
            if old not in KEYS:
                continue
            bank = (root / f).parent / f"{old}.json"
            if not bank.is_file():
                continue  # an entry without a bank (a family the set does not ship)
            header = json.loads(bank.read_text(encoding="utf-8"))
            value = header.get("family") if isinstance(header, dict) else None
            if HEADER.get(value) != KEYS[old]:
                bad.append(f"{f}: families.{old} -> {KEYS[old]}, but {bank.name} is {value!r}")
    return bad


# ---------------------------------------------------------------- the plan (computed once)


@dataclass
class Plan:
    moves: list[tuple[str, str]]
    keep: set[str]
    texts: dict[str, str]  # path before the move -> original text
    spans: dict[str, list[Span]]  # every proposed span
    live_joins: dict[str, list[int]]
    jsons: dict[str, str]

    def new_text(self, path: str) -> str:
        rules = allowed_rules(path, self.keep)
        return apply_spans(self.texts[path], [s for s in self.spans[path] if s.rule in rules])

    def applied(self, path: str) -> list[Span]:
        rules = allowed_rules(path, self.keep)
        return [s for s in self.spans[path] if s.rule in rules]

    def residue(self) -> list[str]:
        out = []
        for path, text in self.texts.items():
            # in a KEEP test the proposed-but-withheld rewrites are in keep-proposed.diff
            out += residue_of(text, self.spans[path], path)
        return out


def build_plan(root: Path, strict: bool = True) -> Plan:
    mv = moves(root, strict)
    keep = keep_tests(root)
    texts, spans, joins = {}, {}, {}
    for f in text_scope(root):
        texts[f] = (root / f).read_text(encoding="utf-8")
        spans[f], joins[f] = find_spans(texts[f], f)
    bad = check_reports(root)
    if bad:
        raise Refused("; ".join(bad[:5]))
    return Plan(mv, keep, texts, spans, joins, json_rewrites(root))


def _diff(old: str, new: str, a: str, b: str) -> str:
    return "".join(
        difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{a}", f"b/{b}", n=1)
    )


def _test_value_ranges(text: str) -> list[tuple[int, int]]:
    """Offsets of a test file's assert statements, parametrize argument lists and module-level
    constants: a rewrite there changes what a test expects."""
    offs = _offsets(text)
    tree = ast.parse(text)
    out = []

    def add(n: ast.AST) -> None:
        out.append((offs[n.lineno - 1], offs[(n.end_lineno or n.lineno)]))  # type: ignore[attr-defined]

    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            add(node)
    for node in ast.walk(tree):
        parametrize = isinstance(node, ast.Call) and (
            getattr(node.func, "attr", "") == "parametrize"
        )
        if isinstance(node, ast.Assert) or parametrize:
            add(node)
    return out


def write_plan(plan: Plan, out: Path) -> dict[str, int]:
    """The reviewable dry run (plan §8.4): one diff per rule, the test-value hunks, what R4-R9
    WOULD do in the KEEP tests, the JSON key changes, the moves, the residue, the counts."""
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = Counter()
    per_rule: dict[str, list[str]] = {r: [] for r in RULES}
    values, proposed, live, dyn, shell, kept = [], [], [], [], [], []
    for path, text in plan.texts.items():
        dst = new_path(path, plan.moves)
        applied = plan.applied(path)
        for rule in RULES:
            mine = [s for s in applied if s.rule == rule]
            if mine:
                counts[rule] += len(mine)
                per_rule[rule].append(_diff(text, apply_spans(text, mine), path, dst))
        withheld = [s for s in plan.spans[path] if s not in applied]
        if withheld:
            counts["keep-proposed"] += len(withheld)
            proposed.append(_diff(text, apply_spans(text, withheld), path, dst))
        if path.startswith("tests/") and path.endswith(".py"):
            ranges = _test_value_ranges(text)
            inside = [s for s in applied if any(a <= s.start < b for a, b in ranges)]
            if inside:
                counts["tests-values"] += len(inside)
                values.append(_diff(text, apply_spans(text, inside), path, dst))
        lines = text.split("\n")
        offs = _offsets(text)
        for at in plan.live_joins[path]:
            n = next(i for i, o in enumerate(offs) if o > at) - 1
            live.append(f"{path}:{n + 1}:{lines[n].strip()}")
        dyn += dynamic_paths(text, path)
        shell += shell_words(text, path)
        kept += [f"{path}:{n + 1}:{lines[n].strip()}" for n in _KEPT_SITES.get(path, [])]
    for rule, diffs in per_rule.items():
        (out / f"{rule}.diff").write_text("".join(diffs), encoding="utf-8")
    (out / "tests-values.diff").write_text("".join(values), encoding="utf-8")
    (out / "keep-proposed.diff").write_text("".join(proposed), encoding="utf-8")
    (out / "R3-live-code.txt").write_text("".join(x + "\n" for x in live), encoding="utf-8")
    (out / "dynamic-paths.txt").write_text("".join(x + "\n" for x in dyn), encoding="utf-8")
    (out / "shell-words.txt").write_text("".join(x + "\n" for x in shell), encoding="utf-8")
    (out / "kept-sites.txt").write_text("".join(x + "\n" for x in kept), encoding="utf-8")
    (out / "moves.txt").write_text(
        "".join(f"{s} -> {d}\n" for s, d in plan.moves), encoding="utf-8"
    )
    (out / "keep-tests.txt").write_text(
        "".join(f + "\n" for f in sorted(plan.keep)), encoding="utf-8"
    )
    jdiff = []
    for path, new in plan.jsons.items():
        jdiff.append(_diff(plan_text(plan, path), new, path, new_path(path, plan.moves)))
    (out / "json-keys.diff").write_text("".join(jdiff), encoding="utf-8")
    residue = plan.residue()
    (out / "residue.txt").write_text("".join(r + "\n" for r in residue), encoding="utf-8")
    counts |= {
        "moves": len(plan.moves),
        "json-files": len(plan.jsons),
        "residue": len(residue),
        "text-files": len(plan.texts),
        "text-files-changed": sum(1 for p in plan.texts if plan.applied(p)),
        "keep-tests": len(plan.keep),
        "R3-live-code": len(live),
        "dynamic-paths": len(dyn),
        "shell-words": len(shell),
        "kept-sites": len(kept),
    }
    (out / "counts.json").write_text(json.dumps(dict(sorted(counts.items())), indent=1) + "\n")
    return dict(counts)


def plan_text(plan: Plan, path: str) -> str:
    return _ROOT.joinpath(path).read_text(encoding="utf-8")


# ---------------------------------------------------------------- apply


def preconditions(root: Path) -> None:
    """Plan §8.1: a clean, never-migrated tree whose pre-manifest was made on an ancestor."""
    if (git_dir(root) / MARKER).exists():
        raise Refused(f"{git_dir(root) / MARKER} exists: the migration ran here already")
    for tree in ("evals", "src/wsbench/evals"):
        for cat in CATEGORIES:
            d = root / tree / cat
            if cat not in OLD_DIR and d.exists():
                raise Refused(f"{d} exists: the tree is migrated")
        if (root / tree / "basic").exists():
            raise Refused(f"{root / tree / 'basic'} exists: the tree is migrated")
    if git(root, "status", "--porcelain").strip():
        raise Refused("the work tree is not clean")
    manifest = root / MANIFEST
    if not manifest.is_file():
        raise Refused(f"{MANIFEST} is missing (the pre-migration manifest is commit 1)")
    base = json.loads(manifest.read_text(encoding="utf-8")).get("base_sha", "")
    got = subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=root)
    if not base or got.returncode:
        raise Refused(f"{MANIFEST}: base_sha {base[:8]!r} is not an ancestor of HEAD")


def ruff_cmd() -> list[str]:
    """``uv run ruff`` (the version pinned in uv.lock), or ``$MIGRATE_0101_RUFF``."""
    return shlex.split(os.environ.get("MIGRATE_0101_RUFF", "uv run ruff"))


def data_files(files: Iterable[str]) -> list[str]:
    tops = ("evals/", "adapted/", "examples/", "tests/golden/", "tests/fixtures/",
            "src/wsbench/adapt/data/")  # fmt: skip
    return [f for f in files if f.startswith(tops)]


def apply(root: Path, strict: bool = True) -> int:
    preconditions(root)
    plan = build_plan(root, strict)
    gd = git_dir(root)
    (gd / MARKER).write_text(git(root, "rev-parse", "HEAD"), encoding="utf-8")
    files = tracked(root)
    record = {
        "head": git(root, "rev-parse", "HEAD").strip(),
        "moves": plan.moves,
        "data": {f: sha256(root / f) for f in data_files(files)},
        # (the residue file is classified by a reviewer, possibly after `apply`: not pinned)
        "keep": {
            f: sha256(root / f) for f in sorted(KEEP_FILES - {RESIDUE_FILE}) if (root / f).is_file()
        },
        "keep_tests": {
            f: dict(Counter(KEY_RE.findall(plan.new_text(f)))) for f in sorted(plan.keep)
        },
        "text": sorted(plan.texts),
        "json": sorted(plan.jsons),
        "residue": plan.residue(),
    }
    (gd / RECORD).write_text(json.dumps(record), encoding="utf-8")
    # phase 2: every source into the staging directory, then to its destination (collision-free:
    # the swaps, and `evals/association` the family before `evals/association` the category)
    (root / STAGING).mkdir()
    for n, (src, _dst) in enumerate(plan.moves):
        git(root, "mv", src, f"{STAGING}/{n}")
    for n, (_src, dst) in enumerate(plan.moves):
        (root / dst).parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", f"{STAGING}/{n}", dst)
    (root / STAGING).rmdir()
    inits = []
    for cat in CATEGORIES:
        init = root / "src/wsbench/evals" / cat / "__init__.py"
        if init.parent.is_dir():
            init.write_text(f'"""The {cat} families (plan 0101: one package per category)."""\n')
            inits.append(init.relative_to(root).as_posix())
    # phase 3: the text rewrite, written at each file's new path
    changed_py = []
    for path in plan.texts:
        new = plan.new_text(path)
        dst = new_path(path, plan.moves)
        if new != plan.texts[path]:
            (root / dst).write_text(new, encoding="utf-8")
            if dst.endswith(".py"):
                changed_py.append(dst)
    # phase 4: JSON keys
    for path, new in plan.jsons.items():
        (root / new_path(path, plan.moves)).write_text(new, encoding="utf-8")
    # phase 5: the formatter, on the rewritten python only
    if changed_py:
        ruff = ruff_cmd()
        for extra in (["check", "--fix", "--select", "I", "--force-exclude", "-q"],
                      ["format", "--force-exclude", "-q"]):  # fmt: skip
            for i in range(0, len(changed_py), 200):
                subprocess.run([*ruff, *extra, *changed_py[i : i + 200]], cwd=root, check=False)
    git(root, "add", "-A", "--", *inits)
    git(root, "add", "-u")
    return check(root)


# ---------------------------------------------------------------- check


def _residue_key(row: str) -> tuple[str, str]:
    """``(path, text)`` of a ``path:line:text`` residue row: a classification holds while the
    line's text does, wherever an unrelated edit moves it."""
    path, _line, text = [*row.split(":", 2), "", ""][:3]
    return path, text


def _only_pycache(d: Path) -> bool:
    return all(p.name == "__pycache__" or (p.is_dir() and _only_pycache(p)) for p in d.iterdir())


def _applied(root: Path) -> dict[str, Any] | None:
    """The committed record of the migration commit (``APPLIED``), None before it exists."""
    path = root / APPLIED
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _at_apply(root: Path, applied: dict[str, Any] | None) -> bool:
    """Whether the checkout is the tree ``apply`` produced: no committed record yet (``apply``
    is running, or a scratch tree), or HEAD's tree is the recorded one with nothing modified."""
    if applied is None:
        return True
    tree = git(root, "rev-parse", "HEAD^{tree}", check=False).strip()
    dirty = [ln for ln in git(root, "status", "--porcelain").split("\n") if ln.strip()]
    return tree == applied["tree"] and not dirty


def _base_record(root: Path, applied: dict[str, Any]) -> dict[str, Any]:
    """The data half of the `apply` record, rebuilt from the committed record and the base
    commit's blobs, for a checkout where `apply` never ran (a fresh clone)."""
    base = applied["base"]
    names = git(root, "ls-tree", "-r", "--name-only", "-z", base).split("\0")
    data = {}
    for f in data_files(n for n in names if n):
        blob = subprocess.run(
            ["git", "show", f"{base}:{f}"], cwd=root, check=True, capture_output=True
        ).stdout
        data[f] = hashlib.sha256(blob).hexdigest()
    return {
        "head": base,
        "moves": applied["moves"],
        "data": data,
        "json": applied["json"],
        "text": applied["text_data"],
    }


def check(root: Path) -> int:
    """The post-checks of plan §8.5; prints every failure and returns 1 on any.

    The FULL check (data, KEEP files, KEEP-test key counts, strays, residue) is a gate on the
    migration commit alone: it holds at the tree ``apply`` produced, whose hash the committed
    record ``APPLIED`` pins. Every later commit edits the KEEP files and tests by hand (plan §15
    rows 5-6), so at any other tree only the DATA half runs: every data file of the base
    commit is at its new path with its bytes (a rewritten JSON: its exact key translation), no
    data file was added, the trees hold category directories only. Markdown under the data
    trees is prose the later commits edit and is not compared there."""
    gd = git_dir(root)
    applied = _applied(root)
    full = _at_apply(root, applied)
    if (gd / RECORD).is_file():
        rec = json.loads((gd / RECORD).read_text(encoding="utf-8"))
    elif applied is not None:
        rec = _base_record(root, applied)
    else:
        raise Refused(f"{gd / RECORD} is missing: `apply` has not run in this checkout")
    if not full:
        assert applied is not None
        rec = {**rec, "keep": {}, "keep_tests": {}, "residue": []}
        print(
            f"check: KEEP comparison skipped: recorded at apply ({APPLIED}: check "
            f"{applied['check']!r} at tree {applied['tree'][:12]}); data half only"
        )
    mv = [tuple(m) for m in rec["moves"]]
    bad: list[str] = []
    rewritten = set(rec["json"]) | set(rec["text"])
    want_data = set()
    for f, digest in rec["data"].items():
        dst = path_today(f, mv)  # type: ignore[arg-type]
        want_data.add(dst)
        if not (root / dst).is_file():
            bad.append(f"missing data file {dst} (was {f})")
        elif f in rec["json"]:
            old = json.loads(git(root, "show", f"{rec['head']}:{f}"))
            new = json.loads((root / dst).read_text(encoding="utf-8"))
            if new != _translate(str(json_kind(f)), old, f):
                bad.append(f"{dst}: not the key translation of {f}")
        elif not full and dst.endswith(".md"):
            continue  # prose: edited by hand after the migration commit
        elif f not in rewritten and sha256(root / dst) != digest:
            bad.append(f"{dst}: bytes changed (was {f})")
    now_data = set(data_files(tracked(root)))
    for extra in sorted(now_data - want_data)[:20]:
        bad.append(f"extra data file {extra}")
    for f, digest in rec["keep"].items():
        if not (root / f).is_file() or sha256(root / f) != digest:
            bad.append(f"KEEP file {f} changed")
    for f, hits in rec["keep_tests"].items():
        dst = path_today(f, mv)  # type: ignore[arg-type]
        now = dict(Counter(KEY_RE.findall((root / dst).read_text(encoding="utf-8"))))
        if now != hits:
            bad.append(f"KEEP test {dst}: a key occurrence changed ({hits} -> {now})")
    for tree, ok in (("evals", {*CATEGORIES, *UNMOVED}), ("src/wsbench/evals", set(CATEGORIES))):
        for d in sorted((root / tree).iterdir()):
            if d.is_dir() and d.name not in ok and d.name != "__pycache__" and not _only_pycache(d):
                bad.append(f"{tree}/{d.name}: not a category directory")
    if (root / STAGING).exists():
        bad.append(f"{STAGING} is still there")
    stray = [ln for ln in git(root, "status", "--porcelain").split("\n") if ln.startswith("??")]
    bad += [f"stray file {ln[3:]}" for ln in stray[:20] if full]
    classified: dict[tuple[str, str], str] = {}
    if (root / RESIDUE_FILE).is_file():
        for ln in (root / RESIDUE_FILE).read_text(encoding="utf-8").split("\n"):
            if ln and not ln.startswith("#"):
                cls, _, row = ln.partition("\t")
                classified[_residue_key(row.split("\t", 1)[0])] = cls
    unlisted = [r for r in rec["residue"] if _residue_key(r) not in classified]
    if unlisted:
        bad.append(f"{len(unlisted)} residue line(s) not in {RESIDUE_FILE}, e.g. {unlisted[0]!r}")
    open_rows = [
        r for r in rec["residue"] if classified.get(_residue_key(r)) not in RESIDUE_CLASSES
    ]
    if len(open_rows) > len(unlisted):
        n = len(open_rows) - len(unlisted)
        bad.append(f"{n} residue line(s) not classified {' / '.join(RESIDUE_CLASSES)} (still `?`)")
    for b in bad:
        print(f"check: {b}", file=sys.stderr)
    verdict = f"FAILED ({len(bad)})" if bad else "ok"
    print(
        f"check: {len(rec['data'])} data files, {len(mv)} moves, {len(rec['text'])} text files, "
        f"{len(rec['json'])} JSON files: {verdict}"
    )
    return 1 if bad else 0


# ---------------------------------------------------------------- one adapted set outside git


def _ids_of(path: Path) -> set[str]:
    """Item ids of a bank file, a JSONL of rows (``id``, or a cache ``key`` cut at ``|``), or
    the first such file of a directory."""
    if path.is_dir():
        out: set[str] = set()
        for f in sorted(path.rglob("*.json*")):
            out |= _ids_of(f)
            if len(out) > 2000:
                break
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    out = set()
    if path.suffix == ".json":
        try:
            doc = json.loads(text)
        except ValueError:
            return out
        rows = doc.get("items", []) if isinstance(doc, dict) else doc
        rows = rows if isinstance(rows, list) else []
        if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
            rows = doc["rows"]
    else:
        rows = []
        for line in text.split("\n")[:5000]:
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    for r in rows:
        if not isinstance(r, dict):
            continue
        inner = r.get("row") if isinstance(r.get("row"), dict) else r
        for field in ("id", "name"):
            if inner.get(field) is not None:
                out.add(str(inner[field]))
        if isinstance(r.get("key"), str):
            out.add(r["key"].removeprefix("digest:").removeprefix("ntok:").split("|", 1)[0])
    return out


def _registered_ids(root: Path) -> dict[str, set[str]]:
    """new key -> the item ids of its registered banks (either layout)."""
    out = {}
    for old, new in OLD_DIR.items():
        if new.removesuffix("_st") not in ("basic_readout", "multihop", "multilingual", "typo"):
            continue
        d = root / "evals" / CATEGORY[new] / new
        d = d if d.is_dir() else root / "evals" / old
        out[new] = set().union(*[_ids_of(f) for f in sorted(d.glob("items*.json"))])
    return out


def attribute(path: Path, old_key: str, ids_of: Mapping[str, set[str]]) -> str | None:
    """The key AFTER the rename of the family a file or directory under ``old_key`` belongs to,
    by content: a bank's header value, a result's stamp, else its item ids. None when the
    content does not say (and for an empty one)."""
    new = KEYS[old_key]
    if old_key not in ("basic_readout", "multihop", "multilingual", "typo"):
        return new  # an `_mt` key was never reused by another live family
    partner = new.removesuffix("_st")
    if path.is_file() and path.suffix == ".json":
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            doc = None
        if isinstance(doc, dict) and doc.get("family") in HEADER:
            return HEADER[doc["family"]]
    res = path / "results.json" if path.is_dir() else None
    if res is not None and res.is_file():
        doc = json.loads(res.read_text(encoding="utf-8"))
        stamp = str((doc.get("config") or {}).get("prompt_version") or "")
        return _stamp_holder(old_key, stamp) or partner
    ids = _ids_of(path)
    mine, theirs = ids & ids_of.get(new, set()), ids & ids_of.get(partner, set())
    if mine and theirs:
        raise Refused(f"{path} holds ids of both {new!r} and {partner!r}")
    return new if mine else partner if theirs else None


SET_PATTERNS = (  # relative to a set directory; `{k}` = a pre-0101 key
    "{k}.json",
    "{k}",
    "gate/{k}.jsonl",
    "cand/{k}.jsonl",
    "readouts/{k}.jsonl",
    "readouts/{k}.jsonl.meta.json",
    "readouts/*/{k}.jsonl",
    "readouts/*/{k}.jsonl.meta.json",
    "floors/readouts/**/{k}.jsonl",
    "floors/readouts/**/{k}.jsonl.meta.json",
    "floors/results/**/{k}",
    "mc/{k}",
    "judged/**/{k}",
    "*/{k}.jsonl",  # a lens cell store: <store>/<subject>/<arm>/<family>.jsonl
)


def migrate_set(root: Path, target: Path, do: bool) -> int:
    """An adapted set (or a lens cell store ``<store>/<subject>``) outside git: its bank files,
    overlay directory, per-family work files and JSON keys, two-phase, each bare-key path
    attributed by content first. Dry run unless ``do``; refuses a set that has the marker, and
    a target that shows no pre-0101 evidence (no path or JSON key under a retired `_mt` key, no
    bare-key path whose content is a single-token family's): such a set was written after the
    rename, its bare keys already name the multi-token families, and translating them would
    turn them into the `_st` ones."""
    target = target.resolve()
    report = target / "report.json"
    if report.is_file() and json.loads(report.read_text("utf-8")).get(SET_MARKER[0]):
        raise Refused(f"{target} already has the marker {SET_MARKER[0]!r}")
    ids_of = _registered_ids(root)
    for key in KEYS:  # the set's own banks identify its adapted-only ids
        bank = target / f"{key}.json"
        if bank.is_file():
            who = attribute(bank, key, ids_of)
            if who:
                ids_of.setdefault(who, set()).update(_ids_of(bank))
    todo: list[tuple[Path, Path]] = []
    unknown = []
    for pattern in SET_PATTERNS:
        for key in KEYS:
            for path in sorted(target.glob(pattern.format(k=key))):
                if pattern == "{k}" and not path.is_dir():
                    continue
                who = attribute(path, key, ids_of)
                if who is None and (path.is_dir() or path.stat().st_size):
                    unknown.append(path)
                    continue
                name = path.name.replace(key, who or KEYS[key], 1)
                if name != path.name:
                    todo.append((path, path.with_name(name)))
    if unknown:
        raise Refused("cannot attribute " + ", ".join(str(p) for p in unknown[:5]))
    todo = list(dict.fromkeys(todo))
    jsons = {}
    retired = re.compile('"(?:' + _alt(k for k in KEYS if k not in BARE_KEYS) + ')"')
    evidence = bool(todo)
    for f in sorted(target.rglob("*.json")):
        kind = json_kind("adapted/set/" + f.relative_to(target).as_posix())
        if kind is not None:
            evidence = evidence or bool(retired.search(f.read_text(encoding="utf-8")))
            doc, tail = _load_styled(f)
            jsons[f] = (
                json.dumps(_translate(kind, doc, str(f)), indent=1, ensure_ascii=False) + tail
            )
    if not evidence:
        raise Refused(
            f"{target} shows no pre-0101 evidence (nothing under a retired `_mt` key, no "
            "bare-key file of a single-token family): its keys are taken to be today's, "
            "nothing is translated"
        )
    for src, dst in todo:
        print(f"{'mv' if do else 'would mv'} {src} -> {dst}")
    print(f"{len(todo)} renames, {len(jsons)} JSON files" + ("" if do else " (dry run)"))
    if not do:
        return 0
    for f, new in jsons.items():
        f.write_text(new, encoding="utf-8")
    staged = []
    for n, (src, dst) in enumerate(sorted(todo, key=lambda t: -len(t[0].parts))):
        tmp = src.with_name(f".migrate_0101_{n}")
        src.rename(tmp)
        staged.append((tmp, dst))
    for tmp, dst in staged:
        if dst.exists():
            raise SystemExit(f"{dst} exists; the staged file is {tmp}")
        tmp.rename(dst)
    return 0


# ---------------------------------------------------------------- an open branch (plan §8.7)


def branch(root: Path, span: str) -> int:
    """Apply the moves and the rules to exactly the files a pre-migration branch touches or
    adds (``BASE..HEAD``), with the same KEEP list and refusals. The result is left staged."""
    if (root / "evals" / "basic").exists():
        raise Refused("this checkout is migrated; `branch` works from a pre-migration base")
    if git(root, "status", "--porcelain").strip():
        raise Refused("the work tree is not clean")
    touched = [f for f in git(root, "diff", "--name-only", span).split("\n") if f]
    mv = moves(root, strict=False)
    keep = keep_tests(root)
    n = 0
    for f in touched:
        if not (root / f).is_file() or not _is_text_scope(f):
            continue
        text = (root / f).read_text(encoding="utf-8")
        spans, _live = find_spans(text, f)
        rules = allowed_rules(f, keep)
        new = apply_spans(text, [s for s in spans if s.rule in rules])
        if new != text:
            (root / f).write_text(new, encoding="utf-8")
            n += 1
    for f in touched:
        dst = new_path(f, mv)
        if dst != f and (root / f).is_file():
            (root / dst).parent.mkdir(parents=True, exist_ok=True)
            git(root, "add", "--", f)
            git(root, "mv", f, dst)
    git(root, "add", "-u")
    print(f"{len(touched)} files touched by {span}: {n} rewritten; review, then commit")
    return 0


# ---------------------------------------------------------------- main

_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    global _ROOT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=_ROOT, help="the checkout (default: this one)")
    ap.add_argument(
        "--partial-tree",
        action="store_true",
        help="accept a tree without every family directory (the script's own tests)",
    )
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="dry run: write the per-rule diffs and the residue")
    p.add_argument("--out", type=Path, default=None)
    sub.add_parser("apply", help="run the migration (refuses a dirty or migrated tree)")
    sub.add_parser("check", help="the post-checks")
    p = sub.add_parser("set", help="migrate one adapted set outside git (dry run by default)")
    p.add_argument("dir", type=Path)
    p.add_argument("--apply", action="store_true", dest="do")
    p = sub.add_parser("branch", help="rewrite the files a pre-migration branch touches")
    p.add_argument("span")
    args = ap.parse_args(argv)
    _ROOT = root = args.root.resolve()
    strict = not args.partial_tree
    if args.cmd in (None, "plan"):
        out = getattr(args, "out", None) or root / "migrate_0101_plan"
        counts = write_plan(build_plan(root, strict), out)
        for k, v in sorted(counts.items()):
            print(f"{k:22s} {v}")
        print(f"-> {out}")
        return 0
    if args.cmd == "apply":
        return apply(root, strict)
    if args.cmd == "check":
        return check(root)
    if args.cmd == "set":
        return migrate_set(root, args.dir, args.do)
    return branch(root, args.span)


if __name__ == "__main__":
    sys.exit(main())
