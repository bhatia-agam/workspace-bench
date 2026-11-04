"""The r5-rebuilt MC option banks (scripts/mc_options_r5.py): each new bank is its predecessor with
the leaking content distractor lists rebuilt (``r5_mc.changed``) and the items that still leaked
dropped (``r5_mc.dropped``); registered and stamped, and the read plan of record is unchanged."""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _driver():
    spec = importlib.util.spec_from_file_location(
        "mc_options_r5", REPO / "scripts/mc_options_r5.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_driver_families(real_families):
    """Each family the driver rebuilds: its starting bank exists, the bank it freezes is the next
    version beside it, and once frozen that bank is the registered one."""
    r5 = _driver()
    assert sorted(r5.CFGS) == [
        "basic_readout_mt",
        "multihop_mt_v2",
        "multilingual",
        "multilingual_mt",
        "multilingual_multihop",
        "multilingual_typo",
    ]
    for name, cfg in r5.CFGS.items():
        start, new = REPO / cfg.bank, REPO / cfg.new
        assert cfg.name == name and name in real_families and start.is_file(), name
        assert new == start.with_name(f"items_v{cfg.version}.json"), name
        if new.is_file():
            assert real_families[name].bank == Path(cfg.new), name
            assert json.loads(new.read_text(encoding="utf-8"))["supersedes"] == start.name
