"""``group=<category>``: the families of one eval category.

The categories are the registry's (``registry.CATEGORIES``): a family's category is its
``EvalSpec.group``, which is also the directory it lives under and its category in the README's
'The evals'. This module only selects by it: every family is in exactly one category. Anti-text
inversion is an item subset inside families, not a category; pick it with
``anti_text_inversion=True``."""

from wsbench import registry

ALIASES = {"computation": "computational"}  # the name used in conversation for the category


def names() -> list[str]:
    """The categories, in README order."""
    return list(registry.CATEGORIES)


def families(group: str) -> list[str]:
    """The registered families of category ``group`` (registry order), superseded and retired
    ones left out, as ``all`` does."""
    category = ALIASES.get(group, group)
    if category not in registry.CATEGORIES:
        raise ValueError(f"unknown group {group!r}; known groups: {', '.join(names())}")
    registry.load_all()
    members = [n for n, spec in registry.FAMILIES.items() if spec.group == category]
    return registry.drop_superseded(sorted(members))


def title(group: str) -> str:
    """A category's heading in the README: ``association`` -> ``Association``."""
    return registry.CATEGORIES[ALIASES.get(group, group)]
