"""An adapted set's macro exclusion under a renamed family's former key (multihop_mt_v2) applies
to the current key that results carry; an entry under the current key wins."""

import json

from wsbench import results
from wsbench.registry import BANK_ROOT_ENV


def _root(tmp_path, monkeypatch, families):
    (tmp_path / "report.json").write_text(json.dumps({"families": families}), encoding="utf-8")
    monkeypatch.setenv(BANK_ROOT_ENV, str(tmp_path))


def test_former_key_exclusion_applies_to_current_key(tmp_path, monkeypatch):
    _root(
        tmp_path,
        monkeypatch,
        {
            "multihop_mt_v2": {"exclude_from_macro": True, "note": "ooc 2/64"},
            "poetry": {"exclude_from_macro": False},
        },
    )
    ex = results.adapted_exclusions()
    assert ex == {"multihop_mt": "ooc 2/64"}


def test_current_key_entry_wins_over_former_key(tmp_path, monkeypatch):
    _root(
        tmp_path,
        monkeypatch,
        {
            "multihop_mt": {"status": "partial"},
            "multihop_mt_v2": {"exclude_from_macro": True, "note": "stale"},
        },
    )
    assert results.adapted_exclusions() == {}


def test_no_root_is_empty(monkeypatch):
    monkeypatch.delenv(BANK_ROOT_ENV, raising=False)
    assert results.adapted_exclusions() == {}


def test_macro_drops_a_family_excluded_under_its_former_key(tmp_path, monkeypatch):
    from test_results import _res as _r

    _root(
        tmp_path, monkeypatch, {"multihop_mt_v2": {"exclude_from_macro": True, "note": "ooc 2/64"}}
    )
    m = results.macro([_r(family="multihop_mt", value=0.9), _r(family="association", value=0.5)])
    assert m["families"] == ["association"] and m["value"] == 0.5
    assert {"family": "multihop_mt", "reason": "adapted set: ooc 2/64"} in m["excluded"]


def test_current_key_exclusion_wins_and_keeps_its_note(tmp_path, monkeypatch):
    _root(
        tmp_path,
        monkeypatch,
        {
            "multihop_mt": {"exclude_from_macro": True, "note": "current"},
            "multihop_mt_v2": {"exclude_from_macro": False},
        },
    )
    assert results.adapted_exclusions() == {"multihop_mt": "current"}
    # both exclude: the current key's note, whatever order the report lists them in
    for fams in (
        {
            "multihop_mt": {"exclude_from_macro": True, "note": "current"},
            "multihop_mt_v2": {"exclude_from_macro": True, "note": "former"},
        },
        {
            "multihop_mt_v2": {"exclude_from_macro": True, "note": "former"},
            "multihop_mt": {"exclude_from_macro": True, "note": "current"},
        },
    ):
        _root(tmp_path, monkeypatch, fams)
        assert results.adapted_exclusions() == {"multihop_mt": "current"}
