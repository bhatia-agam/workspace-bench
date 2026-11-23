"""``group=<category>``: the families of one eval category.

The categories are the registry's (``registry.CATEGORIES``): a family's category is its
``EvalSpec.group``, which is also the directory it lives under and its category in the README's
'The evals'. This module only selects by it; its one addition is ``ALSO_IN``. Anti-text
inversion is an item subset inside families, not a category; pick it with
``anti_text_inversion=True``."""

from wsbench import registry

ALIASES = {"computation": "computational"}  # the name used in conversation for the category
# One documented addition to the categories: `group=association` also selects the family that
# tests a role-bound association but lives in another category (anti_bag_of_features, where
# `group=anti_bag_of_features` still selects it too). Nothing else reads this table: a family's
# category, its directory, its README heading and the `wsbench list` column are the registry's.
ALSO_IN: dict[str, tuple[str, ...]] = {"association": ("role_bound_association",)}


def names() -> list[str]:
    """The categories, in README order."""
    return list(registry.CATEGORIES)


def families(group: str) -> list[str]:
    """The registered families of category ``group`` plus its ``ALSO_IN`` additions (registry
    order), superseded and retired ones left out, as ``all`` does."""
    category = ALIASES.get(group, group)
    if category not in registry.CATEGORIES:
        raise ValueError(f"unknown group {group!r}; known groups: {', '.join(names())}")
    registry.load_all()
    members = {n for n, spec in registry.FAMILIES.items() if spec.group == category}
    members |= {n for n in ALSO_IN.get(category, ()) if n in registry.FAMILIES}
    return registry.drop_superseded(sorted(members))


def title(group: str) -> str:
    """A category's heading in the README: ``association`` -> ``Association``."""
    return registry.CATEGORIES[ALIASES.get(group, group)]
