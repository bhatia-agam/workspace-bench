"""A candidate ``adapt mc`` dropped (no options built) is rejected by lint before the gate, in
every MC family, including multihop_st and basic_readout whose required keys omit ``mc``."""

import pytest

from wsbench.adapt import lint


@pytest.mark.parametrize("family", ["multihop_st", "association", "basic_readout"])
def test_lint_rejects_an_mc_build_drop(family):
    item = {
        "name": "x-au-t1-w100c0-x",
        "prompt": "Fact: something ",
        "target": "y",
        "intermediates": ["z"],
        "eval_render": "plain",
        "readout": {"kind": "last"},
        "mc": {"gold": "z"},
        "adapt": {"mc_build": {"dropped": True}},
    }
    assert lint.lint(family, item)  # rejected (by the drop flag or, earlier, a missing key)
    item["adapt"]["mc_build"]["dropped"] = False
    assert not any(p.startswith("mc: the MC builder dropped") for p in lint.lint(family, item))


def test_lint_multihop_drop_flag_is_the_reason():
    item = {
        "name": "mh-au-t1-w100c0-x",
        "prompt": "Fact: something ",
        "target": "y",
        "intermediates": ["z"],
        "eval_render": "plain",
        "readout": {"kind": "last"},
        "adapt": {"mc_build": {"dropped": True}},
    }
    assert lint.lint("multihop_st", item) == [
        "mc: the MC builder dropped this candidate (no options)"
    ]
