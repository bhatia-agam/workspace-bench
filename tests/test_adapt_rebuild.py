"""Plan 0060 A2: the basic_readout v5 and basic_readout_mt v4 rebuilds and the ``adapt mc`` stage
(fakes only: no GPU, Modal or API)."""

import collections
import copy
import json
import types
from pathlib import Path

import pytest

from wsbench import mc, registry
from wsbench.adapt import author, mcstage, rebuild, store
from wsbench.adapt import families as fams
from wsbench.adapt import run as arun
from wsbench.adapt.gate import NO_FALLBACK, Ask, RemoteRunner, grade_leg
from wsbench.adapt.lint import lint
from wsbench.banks import label_of

ROOT = Path(__file__).resolve().parents[1]
BR_V5 = ROOT / "evals/basic_readout/items_v5.json"
BRMT_V4 = ROOT / "evals/basic_readout_mt/items_v4.json"


def _bank(path: Path) -> tuple[dict, list[dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if k != "items"}, raw["items"]


def _by_name(items: list[dict], name: str) -> dict:
    return copy.deepcopy(next(it for it in items if it["name"] == name))


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    return tmp_path


# ---------------------------------------------------------------- basic_readout: gold slots


def test_gold_slots_reproduce_the_registered_deal():
    """The freeze step's deal is the bank's own (mc_leakage_r4 balance): on the registered v5
    items it gives every registered ``mc.gold_position``."""
    _h, items = _bank(BR_V5)
    slots = rebuild.gold_slots(items)
    assert {label_of(it["name"]): it["mc"]["gold_position"] for it in items} == slots


def test_balance_runs_over_the_shipped_set_only():
    header, items = _bank(BR_V5)
    header = copy.deepcopy(header)
    shipped = [copy.deepcopy(it) for i, it in enumerate(items) if i % 3]  # a set's selection
    lists = [it["mc"]["distractors"] for it in shipped]
    notes = rebuild.balance_gold_positions(header, shipped)
    assert notes and [it["mc"]["distractors"] for it in shipped] == lists  # lists untouched
    by_sub = collections.defaultdict(collections.Counter)
    for it in shipped:
        by_sub[it["subfamily"]][it["mc"]["gold_position"]] += 1
    for counts in by_sub.values():
        assert max(counts.values()) - min(counts.values()) <= 1
    rec = header["mc_leakage"]["gold_order"]
    assert rec["procedure"] == rebuild.GOLD_ORDER_PROCEDURE and "rule" in rec
    total = sum(sum(c.values()) for c in rec["slot_counts_1based"].values())
    assert total == len(shipped)


def test_balance_refuses_items_without_options():
    with pytest.raises(SystemExit, match=r"mc\.distractors"):
        rebuild.balance_gold_positions({}, [{"name": "x", "subfamily": "entity", "mc": {}}])


# ---------------------------------------------------------------- implicit: the subject's gold


def _instrument() -> dict:
    return _by_name(_bank(BR_V5)[1], "br-imp-instrument")  # piano; violin saxophone cello ...


def _never_names(block: dict, own: str) -> bool:
    dal = block.get("distractor_aliases") or {}
    return not any(
        mc.form_in(own, [f]) or mc.form_in(f, [own])
        for d in block["distractors"]
        for f in [d, *dal.get(d, [])]
    )


def test_subject_mc_keeps_the_registered_gold_when_the_subject_agrees():
    it = _instrument()
    out = rebuild.subject_mc(it["mc"], "Piano", rebuild.registered_pool(it), it["prompt"])
    assert out["gold"] == "piano" and out["aliases"] == it["mc"]["aliases"]
    assert out["distractors"] == it["mc"]["distractors"] and out["subject_gold"] == "Piano"


def test_subject_mc_swaps_a_distractor_that_is_the_subjects_answer():
    it = _instrument()
    out = rebuild.subject_mc(it["mc"], "Violin", rebuild.registered_pool(it), it["prompt"])
    assert out["gold"] == "violin" and out["aliases"] == ["fiddle", "小提琴"]
    assert len(out["distractors"]) == 4 and _never_names(out, "Violin")
    assert "piano" in out["distractors"]  # topped up from the pool, with its forms
    assert out["distractor_aliases"]["piano"] == ["钢琴"]
    assert "violin" not in out["distractor_aliases"]


def test_subject_mc_new_answer_and_exhausted_pool():
    it = _instrument()
    out = rebuild.subject_mc(it["mc"], "oboe", rebuild.registered_pool(it), it["prompt"])
    assert out["gold"] == "oboe" and out["aliases"] == [] and _never_names(out, "oboe")
    assert out["distractors"] == it["mc"]["distractors"]
    block = {"gold": "x", "distractors": ["a", "b", "c", "d"]}
    assert rebuild.subject_mc(block, "a", [], "") is None  # the pool cannot replace 'a'
    assert rebuild.subject_mc(block, "", [("e", [])], "") is None
    # a pool option written in the question is never added
    got = rebuild.subject_mc(block, "a", [("why", []), ("e", [])], "why so?")
    assert got["distractors"] == ["b", "c", "d", "e"]


def _row(item: dict, origin: str, ok: bool = True) -> dict:
    iid = store.item_id(item)
    gate = {"pass": ok, "rate": 1.0, "legs": {"surface": {"own": item.get("target")}}}
    return {"id": iid, "origin": origin, "item": item, "gate": gate, "selected": ok}


def test_subject_fields_marks_and_rekeys(mdir):
    _h, items = _bank(BR_V5)
    imp = arun.restamp("basic_readout", _instrument(), {"legs": {"surface": {"own": "Violin"}}})
    ent = _by_name(items, "br-ent-ath-ali")
    pieces = ("queen", "king", "rook", "bishop", "knight", "pawn")
    flat = {"name": "brx", "subfamily": "implicit", "topic": "chess piece",
            "candidates": [{"option": o, "aliases": []} for o in pieces]}  # fmt: skip
    cand = author._finish(author._br_v5(flat), author.BRIEFS["basic_readout"], "basic_readout",
                          "demo", "t1", 0, "")  # fmt: skip
    store.add_candidates("demo", "basic_readout", [cand])
    rec = {"legs": {"surface": {"own": "Rook"}}}
    gated = arun.restamp("basic_readout", copy.deepcopy(cand), rec)
    failed = _by_name(items, "br-imp-cartoonchara")
    store.record_gates("demo", "basic_readout", [_row(imp, "original"), _row(ent, "original"),
                                                 _row(gated, "authored"),
                                                 _row(failed, "original", ok=False)])  # fmt: skip
    got = rebuild.subject_fields("demo")
    assert got == {"marked": 3, "short": 0}
    rows = store.gated("demo", "basic_readout")
    for iid in ("br-imp-instrument", "br-ent-ath-ali", "brx"):
        assert rows[iid]["item"][fams.SUBJECT_MARKER] == "demo"
        assert rows[iid]["gate"]["pass"]  # the gate result is carried, never re-asked
    assert rows["br-ent-ath-ali"]["item"]["mc"] == ent["mc"]  # registered block verbatim
    m = rows["br-imp-instrument"]["item"]["mc"]
    assert m["gold"] == "violin" and _never_names(m, "Violin")
    m = rows["brx"]["item"]["mc"]
    assert m["gold"] == "rook" and _never_names(m, "Rook") and "spares" not in m
    assert len(m["distractors"]) == 4
    assert fams.SUBJECT_MARKER not in rows["br-imp-cartoonchara"]["item"]
    assert rebuild.subject_fields("demo") == {"marked": 0, "short": 0}  # idempotent
    assert fams.SUBJECT_FIELDS["basic_readout"] == ("mc",)


def test_freeze_balances_the_shipped_set(mdir, monkeypatch):
    _h, items = _bank(BR_V5)
    subj = types.SimpleNamespace(label="Demo", hf_id="demo/x", n_layers=0, read_band=(),
                                 tokenizer="qwen3.6")  # fmt: skip
    monkeypatch.setattr(arun, "get_subject", lambda m: subj)
    kept = [copy.deepcopy(it) for i, it in enumerate(items) if i % 4]
    for it in kept:
        it["mc"]["gold_position"] = 0  # provisional slots
        it[fams.SUBJECT_MARKER] = "demo"
    store.record_gates("demo", "basic_readout", [_row(it, "original") for it in kept])
    arun.freeze("demo", ["basic_readout"])
    bank = json.loads((mdir / "demo" / "basic_readout.json").read_text(encoding="utf-8"))
    by_sub = collections.defaultdict(collections.Counter)
    for it in bank["items"]:
        by_sub[it["subfamily"]][it["mc"]["gold_position"]] += 1
    assert all(max(c.values()) - min(c.values()) <= 1 for c in by_sub.values())
    assert bank["mc_leakage"]["gold_order"]["procedure"] == rebuild.GOLD_ORDER_PROCEDURE
    assert json.loads(BR_V5.read_text(encoding="utf-8"))["items"][0] == items[0]  # evals intact


# ---------------------------------------------------------------- basic_readout v5 Brief + lint


def test_br_v5_brief_builds_lint_clean_items():
    b = author.BRIEFS["basic_readout"]
    ent = author._br_v5(
        {
            "name": "br-ent-cap-oslo", "subfamily": "entity", "slice": "cap", "subject": "Oslo",
            "prompt": "Oslo is the capital of which country? Answer in one word.",
            "target": "Norway", "aliases": ["挪威"],
            "distractors": [{"option": c, "aliases": []}
                            for c in ("Sweden", "Denmark", "Finland", "Iceland")],
            "task_context": "the model was asked which country a capital city belongs to",
        }
    )  # fmt: skip
    ent = author._finish(ent, b, "basic_readout", "demo", "entity", 0, "")
    assert lint("basic_readout", ent) == []
    assert ent["mc"]["gold"] == "Norway" and ent["mc"]["gold_position"] == 0
    assert ent["readout"]["kind"] == "question_through_end" and ent["eval_render"] == "chat"
    bad = copy.deepcopy(ent)
    bad["mc"]["distractors"][0] = "Norway"
    assert any("names or is named" in p for p in lint("basic_readout", bad))
    bad = copy.deepcopy(ent)
    bad["mc"]["distractors"][0] = "Oslo"
    assert any("in prompt" in p for p in lint("basic_readout", bad))
    pieces = ["queen", "king", "rook", "bishop", "knight", "pawn"]
    imp = author._br_v5({"name": "br-imp-x", "subfamily": "implicit", "topic": "chess piece",
                         "candidates": pieces})  # fmt: skip
    imp = author._finish(imp, b, "basic_readout", "demo", "t1", 0, "")
    assert imp["prompt"] == "What is your favorite chess piece? Answer in one word."
    assert lint("basic_readout", imp) == [] and imp["mc"]["spares"][0]["option"] == "pawn"
    assert any("missing" in p for p in lint("basic_readout", {**ent, "task_context": ""}))


def test_br_v5_flat_roundtrip_on_the_registered_bank():
    _h, items = _bank(BR_V5)
    for it in items:
        flat = author._flat_br_v5(copy.deepcopy(it))
        x = {k: flat.get(k) for k in author.BRIEFS["basic_readout"].keys if k in flat}
        got = author._br_v5(x)
        assert got["mc"]["gold"] == it["mc"]["gold"], it["name"]
        assert got["mc"]["distractors"] == it["mc"]["distractors"], it["name"]
        dal = {k: v for k, v in it["mc"]["distractor_aliases"].items() if v}
        assert got["mc"]["distractor_aliases"] == dal, it["name"]
        if it["subfamily"] != "implicit":
            assert got["mc"]["aliases"] == it["mc"]["aliases"]


# ---------------------------------------------------------------- basic_readout_mt v4 gate


def _brmt_items() -> list[dict]:
    return _bank(BRMT_V4)[1]


def test_brmt_gate_asks_the_v4_question():
    it = _brmt_items()[0]
    fam = fams.get("basic_readout_mt")
    asks = fam.asks(it)
    assert len(asks) == 1
    a = asks[0]
    assert a.messages == ({"role": "user", "content": it["prompt"]},)  # no system turn
    assert a.prefill == "" and a.prompt is None and a.grade == "name_forms"
    forms = [f for fs in it["name_forms"]["readout"].values() for f in fs]
    assert set(a.golds) == set(forms) and a.max_tokens == fams.BRMT_MAX_TOKENS
    assert (fam.temperature, fam.top_p, fam.top_k) == (0.7, 0.8, 20)
    assert "name_forms" in NO_FALLBACK
    # the other mt families keep _asked(CONTINUE, plain=True)
    _h, ml = store.original_bank("multilingual_mt")
    legs = fams.get("multilingual_mt").asks(ml[0])
    assert {x.leg for x in legs} == {"surface", "surface:plain"}
    assert legs[0].messages[0]["role"] == "system"


def test_brmt_name_forms_grader_any_language():
    it = next(x for x in _brmt_items() if x["name"] == "brh-ar-ain-jalut")
    ask = fams.get("basic_readout_mt").asks(it)[0]
    zh = "这场战役是阿因贾鲁特战役。"
    leg = grade_leg(ask, "It was the Battle of Ain Jalut in 1260.", [zh] * 8 + ["Hattin"] * 2, 0.8)
    assert leg.passed and leg.rate == 0.8

    def llm(_a, texts):  # a deterministic grader is never second-guessed
        raise AssertionError("name_forms must not fall back to the model grader")

    assert not grade_leg(ask, "The Battle of Hattin", ["Hattin"] * 10, 0.8, llm).passed


class _Runner:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def sample(self, asks, draws, temperature, top_p=1.0, top_k=-1):
        self.calls.append((draws, temperature, top_p, top_k))
        return [(self.answer, [self.answer] * draws) for _ in asks]


def test_brmt_gate_rows_sample_at_the_v4_header(mdir):
    it = copy.deepcopy(_brmt_items()[0])
    r = _Runner("The Aghlabids ruled it.")
    rows = arun._gate_rows("demo", "basic_readout_mt", [it], r, 10, None, None)
    assert r.calls == [(10, 0.7, 0.8, 20)]
    assert rows[0]["gate"]["pass"] and rows[0]["sampling"]["top_k"] == 20
    # an explicit temperature= resets the family's sampling (as before)
    r2 = _Runner("x")
    arun._gate_rows("demo", "basic_readout_mt", [it], r2, 10, 0.5, None)
    assert r2.calls == [(10, 0.5, 1.0, -1)]


def test_remote_runner_sends_top_k_only_when_set():
    sent = []
    r = object.__new__(RemoteRunner)
    r.replicas, r.seed, r._bos, r._lead = 1, 0, "", []
    r.tok = lambda text, add_special_tokens=False: {"input_ids": [ord(c) for c in text]}
    r.remote = types.SimpleNamespace(sample=types.SimpleNamespace(
        remote=lambda *a: sent.append(a) or [("g", ["s"])]))  # fmt: skip
    ask = Ask("i", "surface", ("x",), prompt="hi", max_tokens=3)
    r.sample([ask], 1, 0.7, 0.8)
    r.sample([ask], 1, 0.7, 0.8, top_k=20)
    assert len(sent[0]) == 6 and sent[1][6] == 20


def test_adapt_modal_fan_out_keeps_top_k(monkeypatch):
    pytest.importorskip("modal")
    import importlib.util

    monkeypatch.delenv("ADAPT_SUBJECT", raising=False)
    path = ROOT / "scripts/adapt_modal.py"
    spec = importlib.util.spec_from_file_location("_adapt_modal_rb", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    log = []

    def eng(k):
        def call(name, args):
            log.append(args)
            out = [(f"p{p}", []) for p in args[0]]
            return types.SimpleNamespace(result=lambda: out)

        return call

    m.fan_out([eng(0), eng(1)], "sample", (list(range(4)), [5] * 4, 2, 0.7, 0.8, 100, 20))
    assert [a[5:] for a in log] == [(100, 20), (102, 20)]


def test_brmt_v4_brief_build_lint_and_overlays(mdir):
    class Tok:
        def encode(self, text, add_special_tokens=False):
            return list(range(max(1, len(text) // 4)))

    flat = {
        "name": "brh-au-x", "subfamily": "entity",
        "prompt": "Which Muslim ruling house governed Sicily from 831 until the Norman conquest?",
        "target": "Kalbid dynasty", "target_alts": ["Kalbids"],
        "name_forms_zh": ["卡尔布王朝"],
        "distractors": ["Fatimid Caliphate", "Zirid dynasty", "Hafsid dynasty", "Idrisid dynasty"],
        "exonyms": {"ru": ["Кальбиты"], "de": []},
    }  # fmt: skip
    b = author.BRIEFS["basic_readout_mt"]
    it = author.mt.stamp(author._brmt_v4(dict(flat)), Tok(), b.include_target)
    it = author._finish(it, b, "basic_readout_mt", "demo", "t1", 0, "")
    assert lint("basic_readout_mt", it) == []
    assert it["eval_render"] == "chat" and it["readout"] == {"kind": "all_from_end",
                                                             "lite": "final_token"}  # fmt: skip
    nf = {"en": ["Kalbid dynasty", "Kalbids"], "zh": ["卡尔布王朝"]}
    assert it["name_forms"]["readout"] == nf
    assert it["exonyms"] == {"readout": {"ru": ["Кальбиты"]}}
    asks = fams.get("basic_readout_mt").asks(it)
    assert set(asks[0].golds) == {"Kalbid dynasty", "Kalbids", "卡尔布王朝"}
    leak = copy.deepcopy(it)
    leak["prompt"] = "Which dynasty, the Kalbids, ruled Sicily?"
    assert any(p.startswith("leak") for p in lint("basic_readout_mt", leak))
    # freeze step: adapted-only entries to the overlay files; registered ids never; keys popped
    orig = copy.deepcopy(_brmt_items()[0])
    other = {**copy.deepcopy(it), "name": "brh-au-y"}
    other.pop("exonyms")
    notes, files = rebuild.freeze_step("demo", "basic_readout_mt", {}, [orig, it, other])
    assert notes and set(files) == {"basic_readout_mt/exonyms.json",
                                    "basic_readout_mt/hidden_rivals.json"}  # fmt: skip
    ex = files["basic_readout_mt/exonyms.json"]["items"]
    assert ex == {"brh-au-x": {"readout": {"ru": ["Кальбиты"]}}, "brh-au-y": {}}
    assert files["basic_readout_mt/hidden_rivals.json"]["items"] == {"brh-au-x": {},
                                                                     "brh-au-y": {}}  # fmt: skip
    assert "exonyms" not in it and "hidden_rivals" not in orig
    assert rebuild.freeze_step("demo", "basic_readout_mt", {}, [orig]) == ([], {})


def test_registered_v4_items_lint_clean():
    for it in _brmt_items()[:20]:
        assert not [p for p in lint("basic_readout_mt", it) if not p.startswith("units")], it


# ---------------------------------------------------------------- adapt mc stage


def test_mc_steps_never_touch_evals(tmp_path):
    for fam in mcstage.FAMILIES:
        calls = mcstage.steps(fam, tmp_path / "in.json", tmp_path, tmp_path / "out.json")
        assert calls and all("--bank" in argv for _s, argv in calls)
        assert str(tmp_path / "out.json") in calls[-1][1]
        assert not any("evals" in a for _s, argv in calls for a in argv)
    with pytest.raises(SystemExit, match="no builder"):
        mcstage.steps("poetry", tmp_path, tmp_path, tmp_path)
    with pytest.raises(SystemExit, match="evals"):
        mcstage._not_evals(registry.REPO_ROOT / "evals" / "multihop" / "x.json")


def _brmt_cand(name: str, dis: list[str]) -> dict:
    it = copy.deepcopy(_brmt_items()[0])
    it["name"] = name
    it["mc"]["readout"]["distractors"] = dis
    it["adapt"] = {"origin": "authored", "tier": "t1"}
    return it


def test_mc_build_writes_options_into_pending_candidates(mdir, monkeypatch):
    keep = _brmt_cand("brh-au-a", ["Rustamid dynasty", "Idrisid dynasty", "Zirid dynasty",
                                   "Hafsid dynasty"])  # fmt: skip
    drop = _brmt_cand("brh-au-b", ["P", "Q", "R", "S"])
    orig = copy.deepcopy(_brmt_items()[1])  # an original never goes to the builder
    store.add_candidates("demo", "basic_readout_mt", [keep, drop, orig])
    seen = []

    def fake(script, argv):
        seen.append((script, argv))
        if script == "build_r4b_mc_banks":
            bank = json.loads(Path(argv[argv.index("--bank") + 1]).read_text(encoding="utf-8"))
            assert [it["name"] for it in bank["items"]] == ["brh-au-a", "brh-au-b"]
            it = copy.deepcopy(bank["items"][0])
            new = ["Rustamid dynasty", "Buyid dynasty", "Samanid dynasty", "Saffarid dynasty"]
            it["mc"]["readout"]["distractors"] = new
            out = Path(argv[argv.index("--out") + 1])
            out.write_text(json.dumps({"items": [it]}), encoding="utf-8")

    monkeypatch.setattr(mcstage, "run_builder", fake)
    assert mcstage.build("demo", "basic_readout_mt") == {"built": 1, "dropped": 1}
    assert [s for s, _a in seen] == ["r4_mc_distractors", *["r4b_mc_refine"] * 3,
                                     "build_r4b_mc_banks"]  # fmt: skip
    work = mdir / "demo" / "mc" / "basic_readout_mt"
    assert all(str(work) in a for _s, argv in seen for a in argv if a.endswith(".json"))
    cands = {c["name"]: c for c in store._read_jsonl(store.cand_path("demo", "basic_readout_mt"))}
    a = cands["brh-au-a"]
    assert a["mc"]["readout"]["distractors"][1] == "Buyid dynasty"
    assert a["hidden_rivals"] == {"readout": ["Idrisid dynasty", "Zirid dynasty",
                                              "Hafsid dynasty"]}  # fmt: skip
    assert a["adapt"]["mc_build"]["builders"][-1] == "build_r4b_mc_banks"
    assert "mc" not in cands["brh-au-b"] and cands["brh-au-b"]["adapt"]["mc_build"]["dropped"]
    assert cands[orig["name"]] == orig
    assert any("mc" in p for p in lint("basic_readout_mt", cands["brh-au-b"]))


def test_mc_build_basic_readout_skips_implicit(mdir, monkeypatch):
    b = author.BRIEFS["basic_readout"]
    imp = author._finish(author._br_v5({"name": "br-imp-q", "topic": "chess piece",
                                        "candidates": ["queen", "king", "rook", "bishop", "pawn"]}),
                         b, "basic_readout", "demo", "t1", 0, "")  # fmt: skip
    ent = copy.deepcopy(_by_name(_bank(BR_V5)[1], "br-ent-ath-ali"))
    ent["name"], ent["adapt"] = "br-ent-ath-x", {"origin": "authored"}
    store.add_candidates("demo", "basic_readout", [imp, ent])

    def fake(script, argv):
        if "--bank-out" in argv:
            bank = json.loads(Path(argv[argv.index("--bank") + 1]).read_text(encoding="utf-8"))
            assert [it["name"] for it in bank["items"]] == ["br-ent-ath-x"]
            Path(argv[argv.index("--bank-out") + 1]).write_text(json.dumps(bank), "utf-8")

    monkeypatch.setattr(mcstage, "run_builder", fake)
    assert mcstage.build("demo", "basic_readout") == {"built": 1, "dropped": 0}


def test_adapt_mc_cli_needs_families():
    from wsbench.adapt.__main__ import main

    with pytest.raises(SystemExit, match="families= is required"):
        main(["mc", "model=demo"])
    with pytest.raises(SystemExit, match="stage=subject"):
        mcstage.run("demo", ["multihop"], "subject")


# ---------------------------------------------------------------- PR #245 review


def _fresh_script(name: str):
    """A fresh import of ``scripts/<name>.py`` (as ``mcstage.run_builder`` loads it)."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(f"_t_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    return mod


def test_mc_steps_carry_review_and_the_r4b_passes(tmp_path):
    calls = mcstage.steps("association", tmp_path / "in.json", tmp_path, tmp_path / "o.json",
                          "adapt mc auto-build, demo, 2026-11-03")  # fmt: skip
    frz = next(a for s, a in calls if s == "association_distractors" and a[0] == "freeze")
    assert frz[frz.index("--review") + 1] == "adapt mc auto-build, demo, 2026-11-03"
    calls = mcstage.steps("basic_readout_mt", tmp_path / "in.json", tmp_path, tmp_path / "o.json")
    refine = [a for s, a in calls if s == "r4b_mc_refine"]
    assert len(refine) == 3 and "--pass2" in refine[1]
    assert {"--resume", "--gate-described"} <= set(refine[2]) and "--pass2" not in refine[2]
    assert [s for s, _a in calls][-1] == "build_r4b_mc_banks"
    # the real refine main accepts the argv and runs pass 1 / pass 2 / resume in that order
    seen = []
    for argv in refine:
        m = _fresh_script("r4b_mc_refine")
        (tmp_path / "r4_pools.json").write_text("{}", encoding="utf-8")

        def fake_run(fam, pools, rounds, pass2=False, resume=False, *a, _m=m, **k):
            seen.append((pass2, resume, "described" in _m.GATE_VARIANTS))
            return {"pass": 1 + len(seen), "items": {}}

        m.run = fake_run
        assert m.main(argv) == 0
    assert seen == [(False, False, False), (True, False, False), (False, True, True)]
    out = json.loads((tmp_path / "r4b_distractors.json").read_text(encoding="utf-8"))
    assert out["pass"] >= 2  # build_r4b_mc_banks's requirement


def test_mc_build_association_runs_the_real_builder(mdir, monkeypatch):
    """`adapt mc families=association` through steps() with the REAL association_distractors
    main (its LLM calls faked; mc_leakage_r4 faked): freeze gets --review, options land."""
    words = ["anvil", "barrel", "candle", "kettle", "ladder", "mirror", "pillow", "saddle",
             "teapot", "violin", "wagon", "zipper"]  # fmt: skip
    cands = []
    for name, gold, scene in [
        ("association-au-a", "camping", "A tent pitched by the lake."),
        ("association-au-b", "skiing", "Fresh powder on the slopes."),
    ]:
        cands.append({"name": name, "prompt": scene, "intermediates": [gold],
                      "mc": {"gold": gold, "distractors": []},
                      "adapt": {"origin": "authored"}})  # fmt: skip
    golds = {c["prompt"]: c["intermediates"][0] for c in cands}
    store.add_candidates("demo", "association", cands)

    def fake_call(prompts, schema):
        out = []
        for _sys, user in prompts:
            name = schema["name"]
            if name == "assoc_options":
                out.append({"category": "thing", "aliases": [], "candidates": words})
            elif name == "entail_check":
                out.append({"flagged": []})
            else:
                gold = next(g for sc, g in golds.items() if sc in user)
                opts = [ln.split(". ", 1)[1] for ln in user.splitlines() if ". " in ln[:6]]
                out.append({"choice": opts.index(gold) + 1})
        return out

    ran = []

    def runner(script, argv):
        ran.append(script)
        if script == "association_distractors":
            m = _fresh_script(script)
            m.call = fake_call
            assert m.main(argv) == 0, argv
        else:  # mc_leakage_r4: round = no-op, freeze = the input bank as is
            if "--bank-out" in argv:
                src = Path(argv[argv.index("--bank") + 1]).read_text(encoding="utf-8")
                Path(argv[argv.index("--bank-out") + 1]).write_text(src, encoding="utf-8")

    monkeypatch.setattr(mcstage, "run_builder", runner)
    assert mcstage.build("demo", "association") == {"built": 2, "dropped": 0}
    assert ran.count("association_distractors") == 3
    got = {c["name"]: c for c in store._read_jsonl(store.cand_path("demo", "association"))}
    for c in got.values():
        assert len(c["mc"]["distractors"]) == 7 and c["mc"]["gold"] == c["intermediates"][0]


def test_br_freeze_refuses_unmarked_implicit_and_strips_working_fields():
    _h, items = _bank(BR_V5)
    imp = _by_name(items, "br-imp-instrument")
    ent = _by_name(items, "br-ent-ath-ali")
    with pytest.raises(SystemExit, match="stage=subject"):
        rebuild.freeze_step("demo", "basic_readout", {}, [copy.deepcopy(imp), ent])
    imp[fams.SUBJECT_MARKER] = "other-model"
    with pytest.raises(SystemExit, match="implicit"):
        rebuild.freeze_step("demo", "basic_readout", {}, [copy.deepcopy(imp), ent])
    imp[fams.SUBJECT_MARKER] = "demo"
    imp["mc"]["spares"] = [{"option": "oboe", "aliases": []}]
    ent[fams.SUBJECT_MARKER] = "demo"
    shipped = [imp, ent]
    rebuild.freeze_step("demo", "basic_readout", {}, shipped)
    assert all(fams.SUBJECT_MARKER not in it and "spares" not in it["mc"] for it in shipped)


def test_br_freeze_checks_the_marker_on_non_originals_only():
    # originals: A1's row-level `_subject_fields_missing` enforces the marker before freeze_step
    _h, items = _bank(BR_V5)
    imp = copy.deepcopy(_by_name(items, "br-imp-instrument"))
    imp.pop(fams.SUBJECT_MARKER, None)
    imp["adapt"] = {"origin": "authored"}
    with pytest.raises(SystemExit, match="stage=subject"):
        rebuild.freeze_step("demo", "basic_readout", {}, [copy.deepcopy(imp)])
    imp["adapt"] = {"origin": "original"}
    rebuild.freeze_step("demo", "basic_readout", {}, [imp])


def test_brmt_exonyms_follow_the_registered_rule():
    it = {
        "name": "brh-au-x", "adapt": {"origin": "authored"},
        "name_forms": {"readout": {"en": ["Kalbid dynasty", "Kalbids"]}},
        "mc": {"readout": {"gold": "Kalbid dynasty",
                           "distractors": ["Zirid dynasty", "Hafsid dynasty", "Fatimid Caliphate",
                                           "Idrisid dynasty"]}},
        "hidden_rivals": {"readout": ["Aghlabid dynasty"]},
        "exonyms": {"readout": {
            "ru": ["Кальбиты", "Жд"],          # kept; under 3 letters dropped
            "de": ["Kalbiden", "Kalbids"],     # kept; already listed dropped
            "fr": ["Zirides", "Zirid"],        # 'Zirid' is held by a distractor's name
            "es": ["Aghlabid"],                # held by a hidden rival
            "fa": ["Rustamid"],                # another bank entity's name
        }},
    }  # fmt: skip
    other = {"name": "brh-au-y", "adapt": {"origin": "authored"},
             "name_forms": {"readout": {"en": ["Rustamid dynasty"]}},
             "mc": {"readout": {"gold": "Rustamid dynasty", "distractors": []}}}  # fmt: skip
    _notes, files = rebuild.freeze_step("demo", "basic_readout_mt", {}, [it, other])
    ex = files["basic_readout_mt/exonyms.json"]["items"]["brh-au-x"]
    assert ex == {"readout": {"ru": ["Кальбиты"], "de": ["Kalbiden"], "fr": ["Zirides"]}}
    assert files["basic_readout_mt/hidden_rivals.json"]["items"]["brh-au-x"] == {
        "readout": ["Aghlabid dynasty"]
    }
