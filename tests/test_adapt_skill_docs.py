"""Plan 0091: the adapt-bank skill's commands, paths and bank table stay true to the code."""

import re
from pathlib import Path

import pytest

from wsbench import registry
from wsbench.adapt.__main__ import KEYS

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / ".claude/skills/adapt-bank"
DOCS = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md")),
        REPO / ".claude/skills/wsb-new-questions/SKILL.md"]  # fmt: skip


def _text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in DOCS)


def test_every_documented_adapt_subcommand_exists():
    cmds = set(re.findall(r"(?:python -m wsbench\.adapt|\$A) ([a-z_]+)\b", _text()))
    assert cmds, "no adapt commands found"
    assert sorted(cmds - set(KEYS)) == []


def test_documented_adapt_commands_take_key_value_args():
    """The adapt CLI takes only key=value pairs: a positional ``$A <cmd> $M`` is an error."""
    bad = re.findall(
        r"(?:python -m wsbench\.adapt|\$A) [a-z_]+ (?!model=)\$?[A-Za-z<][^\s`|]*", _text()
    )
    bad = [b for b in bad if "=" not in b.split()[-1]]
    assert bad == []


def test_every_documented_script_exists():
    """Every ``scripts/...`` path of this repo the skills name exists (a path under a scripts/
    subdirectory this repo does not have is a global-workspace path, GW in families.md)."""
    paths = set(re.findall(r"\bscripts/[\w./-]+\.(?:py|sh)\b", _text()))
    ours = {p for p in paths if p.count("/") == 1 or (REPO / p).parent.is_dir()}
    missing = sorted(p for p in ours if not (REPO / p).exists()
                     and not (REPO / ".claude/skills/wsb-new-questions" / p).exists())  # fmt: skip
    assert len(ours) > 10 and missing == []


def test_registered_bank_table_matches_the_registry(real_families):
    text = (SKILL / "references/families.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| ([a-z_]+) \| `([^`]+)` \|$", text, re.M))
    want = {f: str(registry.bank_path(f).relative_to(registry.REPO_ROOT))
            for f in registry.drop_superseded(sorted(registry.FAMILIES))}  # fmt: skip
    assert table == want


def test_the_driver_builds_the_30_families(real_families):
    """Scope: the families `all` runs minus jlens_concept_pr; the driver freezes the item families
    and the build / side builds install the rest."""
    scope = set(registry.drop_superseded(sorted(registry.FAMILIES))) - {"jlens_concept_pr"}
    assert len(scope) == 30
    sh = (REPO / "scripts/adapt_set.sh").read_text(encoding="utf-8")
    frozen = set(re.search(r"^FREEZE_FAMS=\$PROFILE_FAMS,(\S+)", sh, re.M).group(1).split(","))
    frozen |= set(re.search(r"^PROFILE_FAMS=(\S+)", sh, re.M).group(1).split(","))
    own = {"agentic_misalignment", "jailbreak_recognition", "multi_concept_directed_modulation",
           "introspection", "hinted_cutoff"}  # fmt: skip
    assert frozen | own == scope and not frozen & own


def test_download_weights_helpers():
    pytest.importorskip("modal")
    import importlib.util

    spec = importlib.util.spec_from_file_location("dlw", REPO / "scripts/download_weights_modal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.cache_subdir("adapt-hf-cache") == "hub" and mod.cache_subdir("kimi-k2") == "hf/hub"
    assert mod.check_revision("a" * 40) == "a" * 40
    with pytest.raises(SystemExit):
        mod.check_revision("main")
