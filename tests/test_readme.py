"""The public docs: an entry for every family in docs/evals.md and a row in the README table, the
judges table in docs/judges.md, Credits, NOTICE.md, CITATION.cff."""

import re

from wsbench import registry
from wsbench.registry import REPO_ROOT

GROUPS = [
    "Basic (adapted from the J-lens paper)",
    "Computational",
    "Association",
    "Safety",
    "Anti-bag-of-features",
    "Logical processing",
    "Model-specific",
    "J-lens comparison (not in any macro)",
]
LABELS = ("*What it is:*", "*Example:*", "*Judged by:*")


def _specs():
    registry.load_all()
    return sorted(registry.FAMILIES.values(), key=lambda s: s.name)


def _listed_specs():
    """The families with a README entry: every registered one except a retired one (plan 0058:
    ``registry.RETIRED_FAMILIES`` keeps its code and bank, but not its README entry)."""
    return [s for s in _specs() if s.name not in registry.RETIRED_FAMILIES]


def _readme() -> str:
    return (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _evals() -> str:
    """The page with one entry per family (what it is, example, judged by)."""
    return (REPO_ROOT / "docs" / "evals.md").read_text(encoding="utf-8")


def _judges() -> str:
    """The judges page: the table of judge model and prompt version, and why these judges."""
    return (REPO_ROOT / "docs" / "judges.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert m, f"no section {heading!r}"
    return m.group(1)


def test_every_family_has_an_entry_with_three_labelled_lines():
    specs = _listed_specs()
    assert len(specs) >= 9
    text = _evals()
    lines = text.splitlines()
    for s in specs:
        heads = [i for i, ln in enumerate(lines) if ln.startswith(f"**{s.title}**")]
        assert len(heads) == 1, s.title
        i = heads[0]
        assert f"](../{registry.family_rel(s.name).as_posix()}/README.md)" in lines[i], s.name
        body = lines[i + 1 : i + 4]
        assert [ln.startswith(f"- {lab}") for ln, lab in zip(body, LABELS, strict=True)] == [
            True,
            True,
            True,
        ], (s.name, body)
        # exactly three: the next line is blank or a new heading/entry
        nxt = lines[i + 4] if i + 4 < len(lines) else ""
        assert not nxt.startswith("- *"), (s.name, nxt)
    for g in GROUPS:
        assert re.search(rf"^### {re.escape(g)}$", text, re.M), g
    order = [text.index(f"### {g}") for g in GROUPS]
    assert order == sorted(order)


def test_the_readme_table_has_one_row_per_family_with_its_page_and_category():
    table = _section(_readme(), "The evals")
    rows = re.findall(
        r"^\| ([^|]+) \| \[`(\w+)`\]\(([^)]+)\)[^|]*\| [^|]+ \| [\d,]+ \|$", table, re.M
    )
    assert [name for _, name, _ in rows] == sorted(
        {name for _, name, _ in rows}, key=[name for _, name, _ in rows].index
    ), "a family is listed twice"
    by_name = {name: (cat, link) for cat, name, link in rows}
    assert set(by_name) == {s.name for s in _listed_specs()}
    for s in _listed_specs():
        cat, link = by_name[s.name]
        assert link == f"{registry.family_rel(s.name).as_posix()}/README.md", s.name
        assert re.sub(r"[^a-z]", "", cat.lower()) == s.group.replace("_", ""), (s.name, cat)


def test_group_membership_matches_registry():
    text = _evals()
    by_group = {"basic": "Basic (adapted from the J-lens paper)"}
    by_group |= {"computational": "Computational", "association": "Association"}
    by_group |= {"safety": "Safety", "anti_bag_of_features": "Anti-bag-of-features"}
    by_group |= {"logical_processing": "Logical processing", "model_specific": "Model-specific"}
    by_group |= {"jlens_comparison": "J-lens comparison (not in any macro)"}
    starts = {g: text.index(f"### {g}") for g in GROUPS}
    ends = [*sorted(starts.values()), len(text)]
    for s in _listed_specs():
        g = by_group[s.group]
        lo = starts[g]
        hi = ends[ends.index(lo) + 1]
        assert lo < text.index(f"**{s.title}**") < hi, (s.name, g)


def test_retired_families_have_no_entry_but_are_named():
    # plan 0058: a retired family (code and bank kept) leaves the family list and Judges table,
    # and the README says it is retired
    text = _evals()
    for name in registry.RETIRED_FAMILIES:
        s = registry.FAMILIES[name]
        assert not any(ln.startswith(f"**{s.title}**") for ln in text.splitlines()), name
        assert f"| {name} |" not in _judges(), name
        assert f"`{name}` (retired" in text, name


def test_credits_cover_every_source_and_no_in_house_family():
    specs = _specs()
    credits = _section(_readme(), "Credits")
    notice = (REPO_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for s in specs:
        if s.sources:
            assert s.sources in credits, (s.name, s.sources)
            assert s.sources in notice, (s.name, s.sources)
        else:
            assert s.name not in credits and s.title not in credits, s.name
    assert "DeepSeek" not in credits
    for banned in ("CC-CEDICT", "nocot-bench", "Feng"):
        assert banned not in credits and banned not in notice, banned


def test_judges_table_pins():
    judges = _judges()
    for s in _listed_specs():
        assert s.name in judges and s.judge.prompt_version in judges, s.name
    assert "| agentic_misalignment | claude-sonnet-5 |" in judges
    assert "| jailbreak_recognition | claude-sonnet-5 |" in judges
    assert (
        "deepseek" not in judges.lower().replace("deepseek v4 flash; changed", "")
        and "refuses" in judges
    )


def test_citation_cff_required_keys():
    cff = (REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(r"^cff-version: 1\.2\.0$", cff, re.M)
    assert re.search(r"^title: .*workspace-bench", cff, re.M)
    assert re.search(r"^authors:\n(\s+- .*\n)+", cff, re.M)
    assert re.search(r"family-names: Blank", cff) and re.search(r"given-names: Camila", cff)
    assert re.search(r"^repository-code: https://github\.com/\S+$", cff, re.M)
    assert re.search(r"^license: MIT$", cff, re.M)
    assert "preferred-citation:" in cff


def test_notice_sections():
    notice = (REPO_ROOT / "NOTICE.md").read_text(encoding="utf-8")
    for needle in (
        "MIT",
        "ODC-BY",
        "Apache-2.0",
        "LMSYS-Chat-1M Dataset License Agreement",
        "CC BY-NC-SA 4.0",
        "non-commercial",
        "Transluce",
    ):
        assert needle in notice, needle
