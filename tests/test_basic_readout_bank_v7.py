"""basic_readout bank v7 = bank v5 with Big Ben's gold option reading "England / UK", so a readout
answering UK picks the gold the judge sees. Nothing else moves."""

import json
from pathlib import Path

from wsbench import reads, registry
from wsbench.basic import mcjudge_basic as mj
from wsbench.basic.prompts import BR_CANNOT, prompt_version_of
from wsbench.digest import Line

REPO = Path(__file__).resolve().parents[1]
V5 = REPO / "evals/basic_readout/items_v5.json"
V7 = REPO / "evals/basic_readout/items_v7.json"
BIG = "br-ent-lmk-big"


def _raw(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_only_big_ben_changes():
    v5 = {it["name"]: it for it in _raw(V5)["items"]}
    v7 = _raw(V7)
    assert v7["version"] == 7 and v7["supersedes"] == "items_v5.json"
    changed = [it["name"] for it in v7["items"] if it != v5[it["name"]]]
    assert changed == [BIG] and len(v7["items"]) == 100
    big = next(it for it in v7["items"] if it["name"] == BIG)
    old = v5[BIG]
    assert big["mc"]["gold"] == "England / UK" and old["mc"]["gold"] == "England"
    assert big["mc"]["aliases"] == ["England", *old["mc"]["aliases"]]
    assert {k: v for k, v in big["mc"].items() if k not in ("gold", "aliases")} == {
        k: v for k, v in old["mc"].items() if k not in ("gold", "aliases")
    }
    assert {k: v for k, v in big.items() if k != "mc"} == {
        k: v for k, v in old.items() if k != "mc"
    }


def _opts(path: Path, iid: str) -> mj.Options:
    it = next(i for i in _raw(path)["items"] if i["name"] == iid)
    return mj.options_for(
        {**it, "id": iid}, pv=mj.options_version("basic_readout"), cannot=BR_CANNOT
    )


def test_option_order_and_slots_are_v5s():
    for it in _raw(V7)["items"]:
        a, b = _opts(V7, it["name"]), _opts(V5, it["name"])
        if it["name"] == BIG:
            assert [o if o != "England / UK" else "England" for o in a.shown] == b.shown
        else:
            assert a.shown == b.shown


def test_a_uk_answer_names_the_gold():
    o = _opts(V7, BIG)
    res = {"choice": mj.LETTERS[o.gold_pos], "quote": "Big Ben is in the UK"}
    assert mj.score(res, o, [Line("Big Ben is in the UK.")], numeric=False).passed
    res = {"choice": mj.LETTERS[o.gold_pos], "quote": "Big Ben is in England"}
    assert mj.score(res, o, [Line("Big Ben is in England.")], numeric=False).passed


def test_registered_and_read_plan_unchanged(real_families, monkeypatch):
    # bank v8 (2026-11-05: the capital items replaced) keeps v7's Big Ben item and option seed
    assert registry.bank_path("basic_readout") == V7.with_name("items_v8.json")
    assert prompt_version_of("basic_readout").endswith("+bank-v8")
    assert mj.call_pv("basic_readout", prompt_version_of("basic_readout")) == "br-mc-2026-11-01-v5b"
    big8 = next(it for it in _raw(V7.with_name("items_v8.json"))["items"] if it["name"] == BIG)
    assert big8 == next(it for it in _raw(V7)["items"] if it["name"] == BIG)
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "BASIC_READOUT", str(V7))
    assert reads.plan_sha("basic_readout").startswith("195a60c7c52e32f0")  # v7's readouts' plan
