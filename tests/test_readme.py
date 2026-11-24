"""The public docs: an entry for every family in docs/evals.md and a row in the README table, the
judges table in docs/judges.md, Credits, NOTICE.md, CITATION.cff."""

import importlib.util
import re

from wsbench import registry, tiers
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


def _evals_table():
    spec = importlib.util.spec_from_file_location(
        "readme_evals_table", REPO_ROOT / "scripts" / "readme_evals_table.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_readme_table_is_the_one_the_registry_gives():
    """Category, page, sets (core, fast) and questions of every eval, and what `group=`
    selects, are written by ``scripts/readme_evals_table.py --write``: never by hand."""
    gen = _evals_table()
    text = _readme()
    assert text == gen.replace(text), "run: python scripts/readme_evals_table.py --write"
    table = gen.table()
    listed = [s.name for s in _listed_specs()]
    assert set(gen.WHAT) == set(listed)
    for s in _listed_specs():
        row = next(ln for ln in table.splitlines() if f"[`{s.name}`]" in ln)
        assert row.startswith(f"| {registry.CATEGORIES[s.group].split(' (')[0]} |"), s.name
        assert ("core" in row.split("|")[3]) == (s.name in tiers.CORE), s.name
        assert ("rule" in row.split("|")[5]) == bool(s.scorer), s.name
    # a group is one registry category, plus the one documented addition
    assert "`group=<category>` selects a category by its key" in table
    assert "`group=association` also selects `role_bound_association`" in table


def _table_rows() -> dict[str, tuple[str, int]]:
    """The README's table of evals: name -> (the sets it is in, its questions)."""
    rows = {}
    for line in _readme().splitlines():
        m = re.match(r"\| [^|]+ \| \[`(\w+)`\]\([^)]+\) \| ([^|]+) \| .* \| ([\d,]+) \|$", line)
        if m:
            rows[m.group(1)] = (m.group(2), int(m.group(3).replace(",", "")))
    return rows


def test_the_counts_in_the_prose_are_the_registry_s():
    """How many evals and questions each set has is stated in prose in the README and in
    docs/tiers.md; the numbers are held to the registry, the tiers and the fast subset."""
    from wsbench import fast, readplan

    rows = _table_rows()
    full, core, quick = tiers.full(), tiers.core(), fast.families()
    assert set(full) <= set(rows)  # the table also lists an eval that is in no set
    questions = {name: rows[name][1] for name in full}
    in_fast = sum(len(readplan.plan(name, fast=True)) for name in quick)
    text = _readme()
    assert f"| `--full` | Every eval: {len(full)}. |" in text
    assert f"The {len(core)} core evals, the set a method is reported on." in text
    assert f"{len(core)} evals and {sum(questions[n] for n in core):,} questions" in text
    assert f"It has {len(full)} now, {sum(questions.values()):,}\n  questions" in text
    assert (
        f"{len(quick)} core evals (every core eval but the two safety ones), "
        f"{in_fast:,} of their {sum(questions[n] for n in quick):,} questions read"
    ) in text
    assert f"The fast subset is now {in_fast:,} questions in {len(quick)} evals\n" in text
    table = (REPO_ROOT / "docs" / "tiers.md").read_text(encoding="utf-8")
    for tier, n in (("fast", len(quick)), ("core", len(core)), ("full", len(full))):
        row = next(ln for ln in table.splitlines() if ln.startswith(f"| `{tier}` |"))
        assert row.split("|")[4].strip() == str(n), tier


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
