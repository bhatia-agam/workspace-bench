"""build_multihop_mc --bank leaves out an item it cannot build (a country gold outside COUNTRIES)
instead of failing the whole adapted build; adapt mc then drops it before the gate."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import build_multihop_mc as m  # noqa: E402


def _country_item(name: str, gold: str) -> dict:
    return {
        "name": name,
        "prompt": "Fact: The country where the city of Cape Town lies borders the country ",
        "target": "Namibia",
        "intermediates": [gold],
        "bridge_type": "country",
    }


def test_bank_skips_an_unbuildable_item(tmp_path, capsys):
    known = next(iter(m.COUNTRIES))
    unknown = "Atlantis Republic"
    assert unknown not in m.COUNTRIES
    bank = tmp_path / "b.json"
    items = [_country_item("mh-a", unknown), _country_item("mh-b", known)]
    bank.write_text(json.dumps({"family": "multihop", "items": items}), encoding="utf-8")
    out = tmp_path / "o.json"
    assert m.main(["--bank", str(bank), "--out", str(out)]) == 0
    got = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert [it["name"] for it in got] == ["mh-b"]
    assert got[0]["mc"]["gold"] == known
    assert "skip mh-a" in capsys.readouterr().out


def test_registered_build_still_raises_on_unknown_gold():
    with pytest.raises(ValueError, match="not in COUNTRIES"):
        m.build_mc(_country_item("mh-a", "Atlantis Republic"))


def test_bank_skips_a_number_gold_past_the_word_table(tmp_path, capsys):
    n = max(m.NUMBER_WORDS) + 1
    item = {
        "name": "mh-n",
        "prompt": "Fact: The number of states in the United States is ",
        "target": "x",
        "intermediates": [str(n)],
        "bridge_type": "number",
    }
    bank = tmp_path / "b.json"
    bank.write_text(json.dumps({"family": "multihop", "items": [item]}), encoding="utf-8")
    out = tmp_path / "o.json"
    assert m.main(["--bank", str(bank), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["items"] == []
    assert "skip mh-n" in capsys.readouterr().out
