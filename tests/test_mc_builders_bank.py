"""The MC builders' adapted-bank mode (plan 0060 A2 "Builders take an adapted bank"): with
``--bank`` each builder reads the given bank and writes only where it is told (never evals/);
without it, each one reads and writes exactly the registered files it did before. Fakes only:
no API, GPU or network call."""

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
EVALS = REPO / "evals"
sys.path.insert(0, str(SCRIPTS))


def _mod(name: str):
    return importlib.import_module(name)


def _snapshot() -> dict[str, str]:
    """sha256 of every file the builders could write under evals/."""
    out = {}
    subs = ("multihop", "association", "basic_readout", "basic_readout_mt", "poetry",
            "multihop_mt_v2", "multilingual_multihop", "multilingual_mt", "multilingual_typo",
            "multilingual", "wrong_bridge", "baselines/topics")  # fmt: skip
    for sub in subs:
        for p in sorted((EVALS / sub).glob("*.json")):
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def evals_untouched():
    before = _snapshot()
    yield
    assert _snapshot() == before, "a builder wrote under evals/"


def _items(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["items"] if isinstance(raw, dict) else raw


def _write(path: Path, doc) -> Path:
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- build_multihop_mc


def test_multihop_default_unchanged(evals_untouched):
    m = _mod("build_multihop_mc")
    assert m.SRC == EVALS / "multihop/items.json" and m.DST == EVALS / "multihop/items_v2.json"
    assert m.main(["--check"]) == 0


def test_multihop_bank(tmp_path, evals_untouched):
    m = _mod("build_multihop_mc")
    reg = copy.deepcopy(_items(EVALS / "multihop/items.json")[0])
    new = {
        "name": "multihop-au-t1-w0c0-mh-x",
        "prompt": "Fact: The chemical symbol for the metal in hemoglobin is ",
        "target": "Fe",
        "intermediates": ["iron"],
        "bridge_aliases": ["铁"],
        "bridge_type": "element",
    }
    bank = _write(tmp_path / "bank.json", {"family": "multihop", "items": [reg, new]})
    out = tmp_path / "o" / "bank_mc.json"
    assert m.main(["--bank", str(bank), "--out", str(out)]) == 0
    got = json.loads(out.read_text(encoding="utf-8"))
    assert got["family"] == "multihop" and "version" not in got
    a, b = got["items"]
    assert a["mc"] == m.build_mc(reg)  # a registered name keeps its gold-table row
    assert b["mc"]["gold"] == "iron" and b["mc"]["aliases"] == ["铁"]
    assert len(b["mc"]["distractors"]) == 4 and "iron" not in b["mc"]["distractors"]


def test_multihop_refusals(tmp_path):
    m = _mod("build_multihop_mc")
    bank = _write(tmp_path / "b.json", [])
    with pytest.raises(SystemExit):
        m.main(["--bank", str(bank)])
    with pytest.raises(SystemExit):
        m.main(["--bank", str(bank), "--out", str(EVALS / "multihop" / "x.json")])
    with pytest.raises(SystemExit):
        m.main(["--out", str(tmp_path / "x.json")])


# ---------------------------------------------------------------- association_distractors


def test_association_default_paths():
    m = _mod("association_distractors")
    m.BANK = None
    assert m.V1 == EVALS / "association/items.json"
    assert m.V2 == EVALS / "association/items_v2.json"
    _header, items = m.v1_items()
    assert items == _items(EVALS / "association/items.json")


def test_association_bank(tmp_path, monkeypatch, evals_untouched):
    m = _mod("association_distractors")
    items = [
        {"name": "association-au-a", "prompt": "A tent by the lake.", "intermediates": ["camp"]},
        {"name": "association-au-b", "prompt": "Snow on the peaks.", "intermediates": ["ski"]},
    ]
    bank = _write(tmp_path / "bank.json", {"family": "association", "version": 1, "items": items})
    seen: list[str] = []

    def fake_call(prompts, schema):
        seen.extend(u for _s, u in prompts)
        return [{"category": "activity", "aliases": [], "candidates": ["hike"]} for _ in prompts]

    monkeypatch.setattr(m, "call", fake_call)
    work = tmp_path / "work"
    assert m.main(["propose", "--out", str(work), "--bank", str(bank)]) == 0
    assert len(seen) == 2
    # the "other bank golds" context is the adapted bank's, not the registered bank's
    assert "Other benchmark answers (prefer same-type ones as candidates): ski" in seen[0]
    state = {
        "association-au-a": {"status": "ok", "aliases": ["camping"], "category": "activity",
                             "distractors": ["hike", "swim"]},
        "association-au-b": {"status": "failed", "why": "gold lost"},
    }  # fmt: skip
    _write(work / "state.json", state)
    with pytest.raises(SystemExit):  # freeze with --bank needs --bank-out
        m.main(["freeze", "--out", str(work), "--review", "r", "--bank", str(bank)])
    dest = tmp_path / "bank_mc.json"
    args = ["freeze", "--out", str(work), "--review", "r", "--bank", str(bank)]
    assert m.main([*args, "--bank-out", str(dest)]) == 0
    got = json.loads(dest.read_text(encoding="utf-8"))
    assert got["version"] == 1 and got["family"] == "association"
    assert [it["name"] for it in got["items"]] == ["association-au-a"]
    assert got["items"][0]["mc"]["distractors"] == ["hike", "swim"]
    assert got["dropped_by_screen"] == {"association-au-b": "gold lost"}
    with pytest.raises(SystemExit):
        m.main([*args, "--bank-out", str(EVALS / "association" / "x.json")])
    m.BANK = None


# ---------------------------------------------------------------- mc_leakage_r4


def _fake_claude_json(tasks, schema, cache_path, concurrency=0):
    name = schema["name"]
    out = {}
    for k in tasks:
        if name == "mcleak_propose":
            cands = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
            out[k] = {"topic": "t", "candidates": [{"option": c, "forms": []} for c in cands]}
        else:
            out[k] = {}
    return out


def test_mc_leakage_default_paths():
    m = _mod("mc_leakage_r4")
    m.BANK, m.BANK_OUT = None, None
    fam = m.FAMS["basic_readout"]
    assert m.bank_in(fam.v2) == EVALS / "basic_readout/items_v2.json"
    assert (
        m.bank_out(EVALS / "basic_readout/items_v3.json") == EVALS / "basic_readout/items_v3.json"
    )
    _h, items = m.load(fam)
    assert [it["name"] for it in items] == [
        it["name"] for it in _items(EVALS / "basic_readout/items_v2.json")
    ]


def test_mc_leakage_balance_bank_matches_registered(tmp_path, evals_untouched):
    """``balance`` on a copy of bank v5 via --bank / --bank-out writes bank v5's bytes: the
    stage's logic is unchanged and only its paths move."""
    m = _mod("mc_leakage_r4")
    src = tmp_path / "v5.json"
    src.write_bytes((EVALS / "basic_readout/items_v5.json").read_bytes())
    dest = tmp_path / "v5_out.json"
    args = ["balance", "--family", "basic_readout", "--bank", str(src)]
    assert m.main([*args, "--bank-out", str(dest)]) == 0
    assert dest.read_bytes() == (EVALS / "basic_readout/items_v5.json").read_bytes()
    m.BANK, m.BANK_OUT = None, None


def test_mc_leakage_round_freeze_on_adapted(tmp_path, monkeypatch, evals_untouched):
    m = _mod("mc_leakage_r4")
    monkeypatch.setattr(m.am, "claude_json", _fake_claude_json)

    def item(name, sub, prompt, gold):
        return {
            "name": name, "subfamily": sub, "slice": sub, "prompt": prompt,
            "task_context": "the model was asked something",
            "mc": {"gold": gold, "aliases": [], "distractors": [], "distractor_aliases": {}},
        }  # fmt: skip

    items = [
        item("basic-au-imp-1", "implicit", "What is your favorite tree? Answer in one word.",
             "oak"),
        item("basic-au-ent-1", "entity", "What sport does X play? Answer in one word.",
             "golf"),
    ]  # fmt: skip
    bank = _write(tmp_path / "bank.json", {"family": "basic-readout", "version": 5,
                                           "items": items})  # fmt: skip
    work = tmp_path / "work"
    base = ["--family", "basic_readout", "--out", str(work), "--bank", str(bank)]
    assert m.main(["round", *base, "--round", "0"]) == 0
    assert (work / "basic_readout" / "bank_r0.json").exists()
    with pytest.raises(SystemExit):  # freeze with --bank needs --bank-out
        m.main(["freeze", *base, "--round", "0"])
    dest = tmp_path / "bank_mc.json"
    assert m.main(["freeze", *base, "--round", "0", "--bank-out", str(dest)]) == 0
    got = json.loads(dest.read_text(encoding="utf-8"))
    assert got["version"] == 5  # an adapted bank keeps its own header version
    for it in got["items"]:
        assert len(it["mc"]["distractors"]) == 4
        assert it["mc"]["gold"] not in it["mc"]["distractors"]
    with pytest.raises(SystemExit):
        m.main(["freeze", *base, "--round", "0", "--bank-out", str(EVALS / "x.json")])
    with pytest.raises(SystemExit):
        m.main(["relabel", *base, "--bank-out", str(dest)])
    m.BANK, m.BANK_OUT = None, None


# ---------------------------------------------------------------- r4_mc_distractors


def _brmt_items(n: int, src: str = "items_v2.json") -> list[dict]:
    return copy.deepcopy(_items(EVALS / "basic_readout_mt" / src)[:n])


def test_r4_default_and_bank(tmp_path, monkeypatch, evals_untouched):
    g = _mod("r4_mc_distractors")
    assert g.bank_path("basic_readout_mt") == EVALS / "basic_readout_mt/items_v2.json"
    assert g.bank_path("wrong_bridge") == EVALS / "wrong_bridge/items_v2.json"
    its = _brmt_items(2)
    bank = _write(tmp_path / "bank.json", {"family": "basic_readout_mt", "items": its})
    assert len(g.specs("basic_readout_mt", bank)) < len(g.specs("basic_readout_mt"))
    seen = {}

    def fake_run(family, only=None, note="", bank=None):
        seen["bank"] = bank
        return {"x": {"readout": {"gold": "g"}}}

    monkeypatch.setattr(g, "run", fake_run)
    out = tmp_path / "pools.json"
    assert g.main(["basic_readout_mt", "--out", str(out), "--bank", str(bank)]) == 0
    assert seen["bank"] == bank and "basic_readout_mt" in json.loads(out.read_text("utf-8"))
    with pytest.raises(SystemExit):
        g.main(["basic_readout_mt", "multihop_mt_v2", "--out", str(out), "--bank", str(bank)])
    with pytest.raises(SystemExit):
        g.main(["basic_readout_mt", "--out", str(EVALS / "x.json"), "--bank", str(bank)])


# ---------------------------------------------------------------- r4b_mc_refine


def test_r4b_refine_default_paths():
    r = _mod("r4b_mc_refine")
    r.BANK, r.OUT = None, None
    f = "basic_readout_mt"
    assert r.source_bank(f) == EVALS / f / "items_v3.json"
    assert r.refine_path(f) == EVALS / f / "r4b_distractors.json"
    assert r.topics_path(f) == EVALS / f / "r4b_topics.json"


def test_r4b_refine_bank(tmp_path, monkeypatch, evals_untouched):
    r = _mod("r4b_mc_refine")
    f = "basic_readout_mt"
    its = _brmt_items(2, "items_v3.json")
    bank = _write(tmp_path / "bank.json", {"family": f, "items": its})
    reg = json.loads((EVALS / f / "r4_distractors.json").read_text("utf-8"))["items"]
    pools = {f: {it["id"] if "id" in it else _label(it["name"]): reg[_label(it["name"])]
                 for it in its}}  # fmt: skip
    out = tmp_path / "refine.json"
    r.BANK, r.OUT = bank, out
    try:
        assert r.topics_path(f) == tmp_path / "refine.topics.json"
        lists = r.load_lists(f, pools)
        assert {k[0] for k in lists} == {_label(it["name"]) for it in its}
    finally:
        r.BANK, r.OUT = None, None
    monkeypatch.setattr(r, "run", lambda *a, **k: {"pass": 1, "items": {}})
    pp = _write(tmp_path / "pools.json", pools)
    assert r.main([f, "--pools", str(pp), "--bank", str(bank), "--out", str(out)]) == 0
    assert json.loads(out.read_text("utf-8")) == {"pass": 1, "items": {}}
    with pytest.raises(SystemExit):
        r.main([f, "--pools", str(pp), "--bank", str(bank)])
    with pytest.raises(SystemExit):
        r.main([f, "--pools", str(pp), "--bank", str(bank), "--out", str(EVALS / f / "x.json")])
    with pytest.raises(SystemExit):
        r.main([f, "multihop_mt_v2", "--pools", str(pp), "--bank", str(bank), "--out", str(out)])
    r.BANK, r.OUT = None, None


def _label(name: str) -> str:
    from wsbench.banks import label_of

    return label_of(name)


# ---------------------------------------------------------------- build_r4_mc_banks


def test_r4_banks_default_unchanged():
    b = _mod("build_r4_mc_banks")
    for fam in b.CONTENT_FAMILIES:
        gen = {fam: json.loads((EVALS / fam / "r4_distractors.json").read_text("utf-8"))["items"]}
        bank, _topics = b.build(fam, gen)
        text = json.dumps(bank, indent=1, ensure_ascii=False) + "\n"
        assert text == (EVALS / fam / "items_v3.json").read_text("utf-8"), fam


def test_r4_banks_bank(tmp_path, evals_untouched):
    b = _mod("build_r4_mc_banks")
    f = "basic_readout_mt"
    its = _brmt_items(3)
    bank = _write(tmp_path / "bank.json", {"family": f, "version": 2, "items": its})
    dist = EVALS / f / "r4_distractors.json"
    out, tops = tmp_path / "v3.json", tmp_path / "topics.json"
    args = ["--family", f, "--bank", str(bank), "--distractors", str(dist), "--out", str(out)]
    assert b.main([*args, "--topics-out", str(tops)]) == 0
    got = json.loads(out.read_text("utf-8"))
    assert got["version"] == 2
    reg = {it["name"]: it for it in _items(EVALS / f / "items_v3.json")}
    for it in got["items"]:
        assert it["mc"]["readout"]["distractors"] == reg[it["name"]]["mc"]["readout"]["distractors"]
    assert set(json.loads(tops.read_text("utf-8"))["items"]) == {_label(i["name"]) for i in its}
    with pytest.raises(SystemExit):
        b.main(["--family", f, "--bank", str(bank), "--distractors", str(dist),
                "--out", str(EVALS / f / "x.json")])  # fmt: skip
    with pytest.raises(SystemExit):
        b.main([*args, "--topics-out", str(EVALS / "baselines/topics/x.json")])
    with pytest.raises(SystemExit):
        b.main(["--out", str(out)])


# ---------------------------------------------------------------- build_r4b_mc_banks


def test_r4b_banks_default_unchanged(evals_untouched):
    b = _mod("build_r4b_mc_banks")
    assert b.main(["--check"]) == 0


def test_r4b_banks_bank(tmp_path, evals_untouched):
    b = _mod("build_r4b_mc_banks")
    f = "basic_readout_mt"
    its = _brmt_items(3, "items_v3.json")
    bank = _write(tmp_path / "bank.json", {"family": f, "version": 3, "items": its})
    dist = EVALS / f / "r4b_distractors.json"
    out = tmp_path / "v4.json"
    assert b.main([f, "--bank", str(bank), "--distractors", str(dist), "--out", str(out)]) == 0
    got = json.loads(out.read_text("utf-8"))
    assert got["version"] == 3 and "r4b_mc" in got
    reg = {it["name"]: it for it in _items(EVALS / f / "items_v4.json")}
    for it in got["items"]:
        assert it["mc"] == reg[it["name"]]["mc"]
    with pytest.raises(SystemExit):
        b.main([f, "--bank", str(bank), "--distractors", str(dist),
                "--out", str(EVALS / f / "x.json")])  # fmt: skip
    with pytest.raises(SystemExit):
        b.main([f, "--bank", str(bank), "--out", str(out)])
    with pytest.raises(SystemExit):
        b.main(["--out", str(out)])
