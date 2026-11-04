"""basic_readout reports its entity / processing / implicit slices as
numbers of their own in extras (decided n, passes, pass rate, bootstrap 95% CI)."""

from wsbench.basic import mcjudge_basic as mj


def test_each_slice_is_its_own_number():
    scope = [
        {"id": "e1", "subfamily": "entity"},
        {"id": "e2", "subfamily": "entity"},
        {"id": "p1", "subfamily": "processing"},
        {"id": "i1", "subfamily": "implicit"},
        {"id": "i2", "subfamily": "implicit"},
        {"id": "i3", "subfamily": "implicit"},
    ]
    rows = [
        {"id": "e1", "pass": True, "choice_kind": "gold"},
        {"id": "e2", "pass": False, "choice_kind": "cannot_tell"},
        {"id": "p1", "pass": True, "choice_kind": "gold"},
        {"id": "i1", "pass": True, "choice_kind": "gold"},
        {"id": "i2", "pass": True, "choice_kind": "gold"},
        {"id": "i3", "pass": None, "choice_kind": None},  # undecided: not in the slice's n
    ]
    got = mj._pick_extras(rows, scope)["pass_by_subfamily"]
    assert set(got) == {"entity", "processing", "implicit"}
    assert got["entity"]["n"] == 2 and got["entity"]["n_pass"] == 1
    assert got["entity"]["pass_rate"] == 0.5
    lo, hi = got["entity"]["ci95"]
    assert 0.0 <= lo <= 0.5 <= hi <= 1.0
    assert got["implicit"] == {"n": 2, "n_pass": 2, "pass_rate": 1.0, "ci95": [1.0, 1.0]}
    assert got["processing"]["n"] == 1
