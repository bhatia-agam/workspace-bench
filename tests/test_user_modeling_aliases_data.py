"""The user_modeling lexicon moved from Python literals to ``aliases.json``: the loaded tables
are identical to the former literals (values, order and container types)."""

import hashlib
import json

from wsbench.evals.association.user_modeling import aliases

TABLES = (
    "UM_OPTION_POOL",
    "UM_EXCLUDE",
    "NEIGHBOURS",
    "COUNTRY_REGIONS",
    "COUNTRY_UNGROUPED",
    "SHOWN_POOL",
    "DISPLAY",
    "VALUE_ALIASES",
)
# sha256 of the canonical dump below, computed from the Python-literal module before the move
# (main @ 23966deb). Key and item order are part of it: option lists are drawn in pool order.
LITERALS_SHA256 = "07055c87aa1da61093bbbf7ebbd7db7eeab6eb951a1dd65311ecb862909590f0"
SIZES = {
    "UM_OPTION_POOL": 11,
    "UM_EXCLUDE": 11,
    "NEIGHBOURS": 23,
    "COUNTRY_REGIONS": 7,
    "COUNTRY_UNGROUPED": 3,
    "SHOWN_POOL": 1,
    "DISPLAY": 1,
    "VALUE_ALIASES": 107,
}


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def test_tables_equal_the_former_python_literals():
    assert {name: len(getattr(aliases, name)) for name in TABLES} == SIZES
    assert sum(len(forms) for forms in aliases.VALUE_ALIASES.values()) == 3797
    dump = {name: _plain(getattr(aliases, name)) for name in TABLES}
    canonical = json.dumps(dump, ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode()).hexdigest() == LITERALS_SHA256


def test_container_types_are_the_former_ones():
    for name in ("UM_OPTION_POOL", "NEIGHBOURS", "COUNTRY_REGIONS", "SHOWN_POOL", "VALUE_ALIASES"):
        table = getattr(aliases, name)
        assert isinstance(table, dict) and all(type(v) is tuple for v in table.values()), name
    assert all(type(v) is frozenset for v in aliases.UM_EXCLUDE.values())
    assert type(aliases.COUNTRY_UNGROUPED) is tuple
    assert aliases.DISPLAY == {"single": "single (never married)"}
    # the alias class shares the Religion pool object, as the literal module did
    assert aliases.UM_OPTION_POOL["ReligiousAffiliation"] is aliases.UM_OPTION_POOL["Religion"]
    assert list(aliases.UM_OPTION_POOL)[-1] == "ReligiousAffiliation"


def test_data_file_is_packaged_beside_the_module():
    assert aliases.DATA_FILE.name == "aliases.json" and aliases.DATA_FILE.is_file()
    raw = json.loads(aliases.DATA_FILE.read_text(encoding="utf-8"))
    assert tuple(raw) == TABLES
    assert "ReligiousAffiliation" not in raw["UM_OPTION_POOL"]  # derived by the loader
