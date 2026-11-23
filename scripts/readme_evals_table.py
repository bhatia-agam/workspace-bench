# ruff: noqa: E501  (the one-line descriptions and the table rows are long strings)
"""The README's table of evals, written from the registry so that it cannot drift.

    python scripts/readme_evals_table.py            # print the table
    python scripts/readme_evals_table.py --write    # replace it in README.md, between the markers

Category, page, sets, scorer and number of questions come from the code (``registry``, ``tiers``,
``fast``, ``readplan``, ``groups``); only the one-line "what it tests" is written here.
``tests/test_readme.py`` fails when the README's table is not this one.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from wsbench import fast, readplan, registry, tiers  # noqa: E402

START, END = "<!-- evals table: start -->", "<!-- evals table: end -->"

WHAT = {
    "basic_readout": "The multi-word answer to a factual question the model has read but not yet answered.",
    "basic_readout_st": "The same with a one-word answer.",
    "directed_modulation": "A concept the model was told to think about, not think about, or hide while copying a sentence.",
    "multi_concept_directed_modulation": "Up to three concepts, or who does what to whom, held in mind while writing a dictated sentence.",
    "multihop": "The unstated multi-word bridge of a two- or three-hop fact.",
    "multihop_st": "The unstated one-word bridge of a two-hop fact.",
    "multilingual": "The multi-word answer to a non-English prompt, in the prompt's language.",
    "multilingual_multihop": "The bridge of a non-English two-hop prompt.",
    "multilingual_st": "The one-word answer to a non-English prompt.",
    "multilingual_typo": "The intended word behind a misspelling in a non-English sentence.",
    "poetry": "The rhyme word the model plans at the end of a couplet's first line.",
    "typo": "The intended multi-word term behind a misspelling.",
    "typo_st": "The intended word behind a misspelling. Replaced by `typo`: runs only when named.",
    "arithmetic_intermediates": "The intermediate values of an expression answered with no working shown.",
    "buggy_code": "The bug in a short program, and no bug in its clean twin.",
    "chain_intermediates": "The running value of a two- or three-step arithmetic chain.",
    "association": "A concept a scene implies but never names.",
    "conjunctive_association": "A compound state a vignette implies: what is felt, about what, towards whom.",
    "user_modeling": "An attribute of the user that a chat implies.",
    "user_modeling_hard": "One to three things a chat implies about its user, every one of them stated.",
    "agentic_misalignment": "The model's plan to take a misaligned action before it writes it, and none on the clean twin.",
    "jailbreak_recognition": "The model noticing that a turn is a jailbreak, and not on harmless role-play.",
    "relational_multihop": "The relation between two people across two hops, which a bag of words cannot express.",
    "role_bound_association": "Who does what to whom in a scene: the direction, not just the words.",
    "moral_rationale": "The reason behind a one-token answer to a hard dilemma.",
    "nyt_connections": "The grouping the model has in mind before it answers a word puzzle.",
    "hinted_cutoff": "That the model uses a hint in the prompt which its reply never mentions.",
    "introspection": "A concept injected into the model's activations.",
    "knowledge_cutoff": "The stable wrong answer the model gives about things it does not know.",
    "model_multihop": "A bridge that only this model believes.",
    "model_specific_directed_modulation": "An obscure concept the model was told to think about.",
    "wrong_intermediate": "The wrong bridge the model resolves on its way to a wrong answer.",
    "jlens_concept_pr": "Whether the concepts a lens states agree with the J-lens tokens at the same activation. In no macro.",
}


def scored_by(name: str) -> str:
    """The registry's scorer of record: a rule (``scorer`` is set) or the family's Claude judge."""
    spec = registry.FAMILIES[name]
    return f"rule ({spec.scorer})" if spec.scorer else "Claude judge"


def table() -> str:
    """The table and the lines under it, as they stand in the README."""
    registry.load_all()
    fast_set = set(fast.families())
    lines = [
        "| category | eval | in | what it tests | scored by | questions |",
        "|---|---|---|---|---|---|",
    ]
    for category, title in registry.CATEGORIES.items():
        short = title.split(" (")[0]
        names = sorted(n for n, s in registry.FAMILIES.items() if s.group == category)
        for name in (n for n in names if n not in registry.RETIRED_FAMILIES):
            sets = [t for t, on in (("core", name in tiers.CORE), ("fast", name in fast_set)) if on]
            page = f"{registry.family_rel(name).as_posix()}/README.md"
            lines.append(
                f"| {short} | [`{name}`]({page}) | {', '.join(sets) or '-'} | {WHAT[name]} "
                f"| {scored_by(name)} | {len(readplan.plan(name)):,} |"
            )
    lines.append("")
    lines.append(
        f"`group=<category>` selects a category by its key ({', '.join(registry.CATEGORIES)})."
    )
    return "\n".join(lines)


def replace(text: str) -> str:
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n{table()}\n{END}{tail}"


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        readme = REPO / "README.md"
        readme.write_text(replace(readme.read_text(encoding="utf-8")), encoding="utf-8")
    else:
        print(table())
