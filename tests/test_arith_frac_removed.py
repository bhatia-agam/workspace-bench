"""Plan 0083: the ``frac`` variant of arithmetic_intermediates is gone from the registered bank,
the generator, select / freeze and every adapted set (with each set's drop-only lineage)."""

import json
import os
import random
from pathlib import Path

import pytest

from wsbench import registry
from wsbench.adapt import gen_arith, generate
from wsbench.adapt.run import _arith_pool_ok

REPO = Path(__file__).resolve().parents[1]
FAM = "arithmetic_intermediates"
SETS = sorted(p.parent for p in (REPO / "adapted").glob(f"*/{FAM}.json"))


def test_generator_never_builds_frac():
    assert "frac" in gen_arith.RETIRED_VARIANTS
    for table in (gen_arith.STEPS, gen_arith.FRACTION_T0, gen_arith.T1, gen_arith.T2):
        assert "frac" not in table
    assert "frac" not in generate.gen_arith_variants()
    assert "frac" not in generate.GENERATORS[FAM].supports
    header = {"variants": {"frac": {"tolerance": "rel5pct", "cell": {"layer": 60, "pos": -8}}}}
    with pytest.raises(KeyError):
        gen_arith.build("frac", random.Random(0), {"pool": (3, 7), "k": (1, 2), "m_max": 200},
                        header)  # fmt: skip


def test_pool_filter_drops_a_retired_variant():
    """frac items with a full null pool (>= 8 separable peers each) would pass the pool rule:
    only the retired-variant filter drops them."""
    bank = json.loads((registry.family_root(FAM) / "items_v2.json").read_text(encoding="utf-8"))
    items = [it for it in bank["items"] if it["variant"] == "subsub"][:20]
    fracs = [
        {**items[0], "name": f"frac-x{k}", "variant": "frac", "pair": None,
         "tolerance": "rel5pct", "intermediates": [str(2.0 * 1.5**k)]}
        for k in range(12)
    ]  # fmt: skip
    assert min(gen_arith.null_sets([dict(f) for f in fracs]).values()) >= 8
    kept = _arith_pool_ok([*items, *fracs])
    assert {it["name"] for it in kept} == {it["name"] for it in items}


def test_registered_bank_has_no_frac():
    raw = json.loads((registry.family_root(FAM) / "items_v2.json").read_text(encoding="utf-8"))
    assert not (registry.family_root(FAM) / "items.json").exists()
    assert "frac" not in raw["variants"] and "frac" in raw["removed_variants"]
    assert raw["bank_version"] == 2
    assert not any(it["variant"] == "frac" for it in raw["items"])


@pytest.mark.parametrize("d", SETS, ids=lambda d: d.name)
def test_adapted_sets_have_no_frac(d, monkeypatch, real_families):
    from wsbench import reads, registry

    raw = json.loads((d / f"{FAM}.json").read_text(encoding="utf-8"))
    assert "frac" not in raw["variants"]
    assert not any(it["variant"] == "frac" for it in raw["items"])
    e = json.loads((d / "report.json").read_text(encoding="utf-8"))["families"][FAM]
    note = e.get("plan_0083")
    assert (note is not None) == ("frac" in raw.get("removed_variants", []))
    if note is None:
        return
    assert note["after"] == len(raw["items"]) == e["n_items"]
    assert note["before"] - note["dropped_frac"] == note["after"]
    if note["dropped_frac"] == 0:  # the variant was in the header only: plan unchanged
        return
    for k in list(os.environ):
        if k.startswith(registry.BANK_FILE_ENV_PREFIX):
            monkeypatch.delenv(k)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(d))
    reads._specs.cache_clear()
    try:
        step = e[reads.LINEAGE_KEY][-1]
        assert step["to"] == reads.plan_sha(FAM) and len(step["dropped"]) == note["dropped_frac"]
    finally:
        reads._specs.cache_clear()
