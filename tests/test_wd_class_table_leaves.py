"""The wrong_intermediate class table carries the walk-depth leaves a set needed (plan 0089)."""


def test_class_table_holds_the_olmo_31_32b_occupation_leaves():
    """plan 0089: olmo-3.1-32b's wrong_intermediate bank stopped on two classes the occupation walk
    expands past the table's depth (parents of Q4164871); the table now carries them as keys."""
    from wsbench.adapt import wrong_intermediate as wb

    parents = wb.class_parents()
    missing: set[str] = set()
    wb.closure(["Q4164871"], parents, 2, missing)
    assert not missing
    assert {"Q141523012", "Q141749534"} <= set(parents)
