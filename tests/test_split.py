"""Plan 0012 §5 report-only protocols and the §4.3 punctuation read."""

from wsbench.mcjudge import load_bank
from wsbench.readplan import GRID
from wsbench.split import is_dev, layer_protocols, mid_band


def test_mid_band_on_the_grid():
    assert mid_band(GRID) == [20, 24, 28, 32, 36, 40, 44, 48, 52]
    assert mid_band([56, 60]) == []


def test_dev_split_is_deterministic_and_about_thirty_percent():
    ids = [f"i{n}" for n in range(2000)]
    dev = [i for i in ids if is_dev("fam", i)]
    assert dev == [i for i in ids if is_dev("fam", i)]
    assert 0.27 < len(dev) / len(ids) < 0.33


def test_layer_protocols_pick_on_dev_and_score_on_test():
    ids = [f"i{n}" for n in range(400)]
    # layer 28 is right on every item, 20 on none; 60 (outside the band) on every item
    cp = {i: {20: False, 28: True, 60: True} for i in ids}
    out = layer_protocols(cp, family="fam", layers=[20, 28, 60])
    assert out["band"] == [20, 28] and out["fixed_layer"]["layer"] == 28
    assert out["fixed_layer"]["test"]["rate"] == 1.0
    assert out["mid_any_layer"]["rate"] == 1.0
    assert out["n_dev_items"] + out["n_test_items"] == 400
    # a pair id keeps both twins on the same side of the split
    out2 = layer_protocols(cp, family="fam", layers=[20, 28], group_of=lambda i: "one")
    assert {out2["n_dev_items"], out2["n_test_items"]} == {0, 400}


def test_punct_positions_are_a_small_subset_of_the_span():
    from wsbench.evals.jailbreak_recognition.judge import grid_positions, punct_positions

    items = load_bank("jailbreak_recognition")["items"]
    for it in items:
        p, g = punct_positions(it["read"]), grid_positions(it["read"])
        assert set(p) <= set(g) and p[-1] == int(it["read"]["span"][1]) and len(p) <= 11
