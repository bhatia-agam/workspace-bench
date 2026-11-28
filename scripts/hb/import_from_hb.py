"""Import HallucinationBench (`camila-blank/hallucination-bench` @ ecfae41) into this repository
(plan 0120 stage A): copy the tracked files and apply the mechanical rewrites M1-M5.
`--check` rebuilds the import and diffs it against the tree; the residual is the hand edits."""

import argparse
import difflib
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HB_HEAD = "ecfae41"
OLD, NEW = "hallucination_bench", "wsbench.hb"
BANKS = "evals/hallucinationbench"
EVALS = (
    "wsbench_chat",
    "wsbench_chat_x3",
    "story",
    "agentic_misalignment",
    "sibling_probe",
    "overrefusal",
    "benign_roleplay",
    "calibration",
)
INDEX_FILES = ("v8_manifest.json", "v8_persistent_failures.json", "methods.json")
# the three trees whose *.py files are rewritten (HB prefix -> prefix here)
CODE = {
    "src/hallucination_bench/": "src/wsbench/hb/",
    "tests/": "tests/hb/",
    "scripts/": "scripts/hb/",
}
NO_REWRITE = ("tests/fixtures/",)  # fixtures are data: bytes unchanged

# M2: the test helpers and test modules that HB imported by bare name (tests/hb is a package)
M2 = re.compile(
    r"^(\s*)from (conftest|index_helpers|v7_rebuild_fixture|test_\w+) import ", re.MULTILINE
)
# M1: the package name, except where it is another repository's module of the same name
M1 = re.compile(rf"(?<![\w./(]){OLD}(?![\w)])")
M1_KEPT = {  # HB file -> lines that keep the old name (global-workspace's judge module)
    "src/hallucination_bench/evals/wsbench_chat/expand.py": 2,
}

_P1, _P2, _P3 = "parents[1]", "parents[2]", "parents[3]"
_HB = '"evals" / "hallucinationbench"'
_REPO12 = (
    "REPO = Path(__file__).resolve().parents[1]",
    "REPO = Path(__file__).resolve().parents[2]",
    1,
)
_REPO23 = (
    "REPO = Path(__file__).resolve().parents[2]",
    "REPO = Path(__file__).resolve().parents[3]",
    1,
)
_MODAL_REPO = (
    '_REPO = _HERE.parents[2] if len(_HERE.parents) > 2 else Path("/root")',
    '_REPO = _HERE.parents[3] if len(_HERE.parents) > 3 else Path("/root")',
    1,
)
# M3: every repository-relative location, by file: (text in HB, text here, occurrences)
M3: dict[str, list[tuple[str, str, int]]] = {
    "src/hallucination_bench/__init__.py": [
        (
            f"REPO_ROOT = Path(__file__).resolve().{_P2}",
            f"REPO_ROOT = Path(__file__).resolve().{_P3}",
            1,
        ),
        ('DATA = REPO_ROOT / "data"', f"DATA = REPO_ROOT / {_HB}", 1),
    ],
    "tests/test_am_audit.py": [
        (f'{_P1} / "scripts" / "am_audit.py"', f'{_P2} / "scripts" / "hb" / "am_audit.py"', 1),
    ],
    "tests/test_am_verify.py": [
        (f'{_P1} / "scripts" / "am_audit.py"', f'{_P2} / "scripts" / "hb" / "am_audit.py"', 1),
    ],
    "tests/test_sibling_probe.py": [
        (
            f'{_P1} / "data" / "sibling_probe" / "pilot"',
            f'{_P2} / {_HB} / "sibling_probe" / "pilot"',
            1,
        ),
    ],
    "tests/test_am_v8.py": [
        _REPO12,
        (
            'REPO / "scripts" / "v8" / "seed_am_root.py"',
            'REPO / "scripts" / "hb" / "v8" / "seed_am_root.py"',
            1,
        ),
    ],
    "tests/test_persistent_failures_script.py": [
        (
            f'{_P1} / "scripts" / "v8" / "persistent_failures.py"',
            f'{_P2} / "scripts" / "hb" / "v8" / "persistent_failures.py"',
            1,
        ),
    ],
    "tests/test_final_olens_arm.py": [
        (f"ROOT = Path(__file__).resolve().{_P1}", f"ROOT = Path(__file__).resolve().{_P2}", 1),
    ],
    "tests/v7_rebuild_fixture.py": [
        ('FIXTURE = Path("tests") / "fixtures"', 'FIXTURE = Path("tests") / "hb" / "fixtures"', 1),
    ],
    "tests/test_benign_roleplay.py": [
        (
            f'REPO_ROOT / "src" / "{OLD}" / "evals"',
            'REPO_ROOT / "src" / "wsbench" / "hb" / "evals"',
            1,
        ),
    ],
    "tests/test_v7_rebuild_identity.py": [
        _REPO12,
        ('REPO / "tests" / "fixtures"', 'REPO / "tests" / "hb" / "fixtures"', 1),
        (
            'REPO / "tests" / "v7_rebuild_fixture.py"',
            'REPO / "tests" / "hb" / "v7_rebuild_fixture.py"',
            1,
        ),
    ],
    "scripts/build_story_bank.py": [
        _REPO12,
        ('OUT = REPO / "data" / "story"', f'OUT = REPO / {_HB} / "story"', 1),
    ],
    "scripts/build_am_bank.py": [
        _REPO12,
        (
            'OUT = REPO / "data" / "agentic_misalignment"',
            f'OUT = REPO / {_HB} / "agentic_misalignment"',
            1,
        ),
    ],
    "scripts/am_audit.py": [_REPO12],
    "scripts/build_dev_v2.py": [
        (
            f'{_P1} / "data" / "calibration" / "dev_v2.jsonl"',
            f'{_P2} / {_HB} / "calibration" / "dev_v2.jsonl"',
            1,
        ),
    ],
    "scripts/main_x3/gen_modal.py": [
        (f'{_P2} / "data" / "wsbench_chat"', f'{_P3} / {_HB} / "wsbench_chat"', 1),
    ],
    "scripts/main_x3/seed_summaries.py": [_REPO23],
    "scripts/main_x3/joint_bundle.py": [_REPO23],
    "scripts/main_x3/merge_readouts.py": [_REPO23],
    "scripts/main_x3/build_bank.py": [
        _REPO23,
        ('WSB = REPO / "data" / "wsbench_chat"', f'WSB = REPO / {_HB} / "wsbench_chat"', 1),
    ],
    "scripts/main_x3/build_seeds.py": [
        _REPO23,
        ('REPO / "data/wsbench_chat/items.json"', f'REPO / "{BANKS}/wsbench_chat/items.json"', 1),
    ],
    "scripts/overrefusal/sample_modal.py": [
        _MODAL_REPO,
        (
            'candidates: str = "data/overrefusal/candidates.jsonl"',
            f'candidates: str = "{BANKS}/overrefusal/candidates.jsonl"',
            1,
        ),
    ],
    "scripts/overrefusal/probe_modal.py": [
        _MODAL_REPO,
        # local side: the package directory in this checkout
        (f'_REPO / "src" / "{OLD}"', '_REPO / "src" / "wsbench" / "hb"', 2),
        # container side: only the hb directory is mounted (wsbench is a namespace package there)
        (f'"/root/src/{OLD}"', '"/root/src/wsbench/hb"', 1),
        ('_REPO / "data/overrefusal/probes"', f'_REPO / "{BANKS}/overrefusal/probes"', 4),
        ('_REPO / "data/overrefusal/items.json"', f'_REPO / "{BANKS}/overrefusal/items.json"', 2),
    ],
    "scripts/sibling_probe/um_probes_modal.py": [
        (
            f'_HERE.{_P2} / "src" / "{OLD}" / "evals" / "sibling_probe"',
            f'_HERE.{_P3} / "src" / "wsbench" / "hb" / "evals" / "sibling_probe"',
            1,
        ),
        ("if len(_HERE.parents) > 2", "if len(_HERE.parents) > 3", 1),
        (
            'distractors: str = "data/sibling_probe/um_country_distractors.json"',
            f'distractors: str = "{BANKS}/sibling_probe/um_country_distractors.json"',
            1,
        ),
    ],
    "scripts/sibling_probe/um_lexicons.py": [
        (
            'OUT = REPO_ROOT / "data" / "sibling_probe" / "um_lexicons.json"',
            f'OUT = REPO_ROOT / {_HB} / "sibling_probe" / "um_lexicons.json"',
            1,
        ),
    ],
    "scripts/sibling_probe/gen_items.py": [
        (
            'PILOT = REPO_ROOT / "data" / "sibling_probe" / "pilot"',
            f'PILOT = REPO_ROOT / {_HB} / "sibling_probe" / "pilot"',
            1,
        ),
    ],
    "scripts/sibling_probe/um_ladder.py": [
        (
            'DATA = REPO_ROOT / "data" / "sibling_probe"',
            f'DATA = REPO_ROOT / {_HB} / "sibling_probe"',
            1,
        ),
        (
            'REPO_ROOT / "scripts" / "sibling_probe"',
            'REPO_ROOT / "scripts" / "hb" / "sibling_probe"',
            1,
        ),
    ],
}
# Left as written on purpose (plan 0120 M1 / M3): help, error and provenance texts that name
# `data/...`; `REPO_ROOT / "outputs" / ...` script defaults (this repository's gitignored
# outputs/); `<another checkout> / "data" / "sibling_probe"` in um_ladder.py (HB_SIBLING_SRC_ROOT).

# The residual of `--check`: files (paths here) that carry a hand edit of plan 0120, by name.
# sha256 of the residual diff `--check` prints
RESIDUAL_SHA256 = "99e3a6fb7119facde1628fafbc0f65a00d41222ac952bfde09c4d15a7630aef2"
HAND_EDITS = {
    "src/wsbench/hb/cli.py": "H1",
    "src/wsbench/hb/final.py": "H2",
    "src/wsbench/hb/evals/overrefusal/cli.py": "H3",
    "src/wsbench/hb/paths.py": "H3",
    "src/wsbench/hb/evals/benign_roleplay/wsb.py": "H4",
    "tests/hb/conftest.py": "H5",
    "tests/hb/test_sibling_probe.py": "H6",
    "tests/hb/test_benign_roleplay.py": "H4 (the test's pinned-checkout environment), H7",
}


def git(hb: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(hb), *args], capture_output=True, text=True, check=True
    ).stdout


def locked_ruff() -> list[str]:
    """This repository's ruff, refused unless it is the version uv.lock pins."""
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    want = next(p["version"] for p in lock["package"] if p["name"] == "ruff")
    cmd = [sys.executable, "-m", "ruff"]
    got = subprocess.run([*cmd, "--version"], capture_output=True, text=True, check=True).stdout
    if got.split()[-1] != want:
        raise SystemExit(f"ruff is {got.strip()}, uv.lock pins {want}: run inside `uv run`")
    return cmd


def dest_of(rel: str) -> str | None:
    """Where a tracked HB file goes here; None = not imported."""
    for old, new in CODE.items():
        if rel.startswith(old) and (old != "scripts/" or rel.endswith(".py")):
            return new + rel[len(old) :]
    parts = rel.split("/")
    if parts[0] == "data" and len(parts) > 2:
        if parts[1] in EVALS or (
            parts[1] == "index" and parts[2] in INDEX_FILES and len(parts) == 3
        ):
            return f"{BANKS}/{'/'.join(parts[1:])}"
        raise SystemExit(f"unexpected data file {rel}")
    if rel.startswith("docs/results/"):
        return "docs/hb/results/" + rel[len("docs/results/") :]
    if rel == "README.md":
        return "docs/hb/README.md"
    if parts[0] == "plans" and len(parts) == 2 and rel.endswith(".md"):
        return "plans/hb/" + parts[1]
    return None


def rewritten(rel: str) -> bool:
    return rel.endswith(".py") and not rel.startswith(NO_REWRITE) and rel.startswith(tuple(CODE))


def rewrite(rel: str, text: str) -> str:
    """M3 (the table), then M1, then M2 (tests only) on one HB file."""
    for old, new, n in M3.get(rel, []):
        if text.count(old) != n:
            raise SystemExit(f"M3: {rel}: expected {n} x {old!r}, found {text.count(old)}")
        text = text.replace(old, new)
    text = M1.sub(NEW, text)
    if text.count(OLD) != M1_KEPT.get(rel, 0):
        raise SystemExit(f"M1: {rel}: {text.count(OLD)} unexpected {OLD!r} left")
    if rel.startswith("tests/"):
        text = M2.sub(r"\1from .\2 import ", text)
    return text


def build(hb: Path, root: Path) -> tuple[list[str], list[str]]:
    """Write the import under `root` (laid out as this repository); (all files, rewritten *.py)."""
    files = git(hb, "ls-files", "-z").split("\0")
    out, code, touched = [], [], set()
    for rel in sorted(f for f in files if f):
        dest = dest_of(rel)
        if dest is None:
            continue
        p = root / dest
        p.parent.mkdir(parents=True, exist_ok=True)
        if rewritten(rel):
            src = (hb / rel).read_text(encoding="utf-8")
            new = rewrite(rel, src)
            p.write_text(new, encoding="utf-8")
            code.append(dest)
            if new != src:
                touched.add(dest)
        else:
            shutil.copyfile(hb / rel, p)
        out.append(dest)
    if missing := sorted(set(M3) - set(files)):
        raise SystemExit(f"M3 names files the checkout does not track: {missing}")
    # M4 + M5 with the locked ruff and this repository's configuration, on the rewritten files
    shutil.copyfile(REPO / "pyproject.toml", root / "pyproject.toml")
    before = {d: (root / d).read_bytes() for d in code}
    ruff = locked_ruff()
    for step in (["format", "--no-cache"], ["check", "--no-cache", "--select", "I", "--fix", "-q"]):
        subprocess.run([*ruff, *step, *code], cwd=root, check=True, capture_output=True)
    moved = {d for d in code if (root / d).read_bytes() != before[d]}
    if stray := sorted(moved - touched):
        raise SystemExit(f"M4/M5 changed files that M1-M3 did not touch: {stray}")
    (root / "pyproject.toml").unlink()
    return out, code


def check(root: Path, files: list[str], code: list[str]) -> int:
    """Diff the rebuilt import against this tree. Non-code files must be byte-identical; a *.py
    file may differ only if it is listed in HAND_EDITS (the diff is printed)."""
    bad, residual = [], []
    for dest in files:
        here = REPO / dest
        if not here.is_file():
            bad.append(f"missing: {dest}")
        elif here.read_bytes() != (root / dest).read_bytes():
            if dest in code and dest in HAND_EDITS:
                residual.append(dest)
            else:
                bad.append(f"differs: {dest}")
    text = ""
    for dest in residual:
        a = (root / dest).read_text(encoding="utf-8").splitlines(keepends=True)
        b = (REPO / dest).read_text(encoding="utf-8").splitlines(keepends=True)
        text += "".join(
            difflib.unified_diff(a, b, f"import/{dest}", f"tree/{dest}  [{HAND_EDITS[dest]}]")
        )
    sys.stdout.write(text)
    # the hand edits are pinned as a whole: a further change to a hand-edited file fails here
    got = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if got != RESIDUAL_SHA256:
        bad.append(f"the residual diff is not the recorded hand edits (sha256 {got})")
    for dest in sorted(set(HAND_EDITS) - set(residual)):
        bad.append(f"listed as hand-edited but identical to the import: {dest}")
    print(
        f"# {len(files)} imported files, {len(code)} rewritten *.py; residual in {len(residual)} "
        f"file(s): {', '.join(f'{d} [{HAND_EDITS[d]}]' for d in residual) or 'none'}",
        file=sys.stderr,
    )
    for line in bad:
        print(f"FAIL {line}", file=sys.stderr)
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hb", type=Path, help=f"a clean HallucinationBench checkout at {HB_HEAD}")
    ap.add_argument("--check", action="store_true", help="rebuild and diff against this tree")
    ap.add_argument("--force", action="store_true", help="overwrite an existing import")
    a = ap.parse_args()
    hb = a.hb.resolve()
    if not (head := git(hb, "rev-parse", "HEAD")).startswith(HB_HEAD):
        raise SystemExit(f"{hb} is at {head.strip()}, not {HB_HEAD}")
    if dirty := git(hb, "status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit(f"{hb} has modified tracked files:\n{dirty}")
    with tempfile.TemporaryDirectory(prefix="hb-import-") as tmp:
        files, code = build(hb, Path(tmp))
        if a.check:
            return check(Path(tmp), files, code)
        if (REPO / "src/wsbench/hb").exists() and not a.force:
            raise SystemExit("src/wsbench/hb exists (hand edits live there): --check, or --force")
        for dest in files:
            (REPO / dest).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(tmp) / dest, REPO / dest)
        (REPO / "tests/hb/__init__.py").touch()
    print(f"imported {len(files)} files ({len(code)} rewritten *.py) from {hb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
