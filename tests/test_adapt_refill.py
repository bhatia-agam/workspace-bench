"""Plan 0066 shared core (offline: fake author / gate / waves, no GPU or API): the refill policy,
the sha-pinned pools, buggy_code's pair selection and fill, the freeze guard and the CLI."""

import copy
import hashlib
import json
import shutil
import subprocess

import pytest

from wsbench.adapt import refill as rf
from wsbench.adapt import run, store

MODEL = "qwen3.5-4b"  # a registered subject on the Qwen tokenizer (no token restamp)


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    return tmp_path / MODEL


def _leg(ok=True):
    return {"greedy": {"text": "x", "ok": ok}, "samples": [], "rate": 1.0 if ok else 0.0}


def _row(item, ok=True, origin="original", bugclaim=True):
    legs = {"surface": _leg(ok)}
    if bugclaim and item.get("src") == "clean":
        legs["bugclaim"] = _leg(ok)
    return {"id": store.item_id(item), "origin": origin, "item": item,
            "gate": {"pass": ok, "rate": 1.0 if ok else 0.0, "legs": legs},
            "selected": ok}  # fmt: skip


def _pair(slug, tier="t1", crash=False, ok=True, clean_ok=None):
    b = {"name": f"buggy-au-{tier}-w1c0-{slug}", "src": "buggy",
         "consequence_class": "crash" if crash else "value",
         "adapt": {"origin": "authored", "tier": tier}}  # fmt: skip
    c = {"name": f"buggy-au-clean-{tier}-w1c0-{slug}", "src": "clean",
         "adapt": {"origin": "authored", "tier": tier}}  # fmt: skip
    return [_row(b, ok, "authored"), _row(c, ok if clean_ok is None else clean_ok, "authored")]


def _gate_log(d, family, rows):
    (d / "gate").mkdir(parents=True, exist_ok=True)
    with (d / "gate" / f"{family}.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


# ============================================================================ policy
def test_policy_covers_the_five_families_with_the_plan_thresholds():
    five = {"buggy_code", "model_specific_directed_modulation", "knowledge_cutoff",
            "wrong_intermediate", "multihop_mt"}  # fmt: skip
    assert set(rf.POLICY) == five
    want = {
        "buggy_code": ("pairs", 60, 0.03),
        "model_specific_directed_modulation": ("categories", 200, 0.03),
        "knowledge_cutoff": ("items", 1000, 0.01),
        "wrong_intermediate": ("items", 200_000, 5e-5),
        "multihop_mt": ("items", 300, 0.03),
    }
    for fam, (unit, n_min, y_min) in want.items():
        p = rf.POLICY[fam]
        assert (p.unit, p.n_min, p.y_min) == (unit, n_min, y_min), fam
    # the registered bank v2: items.json's 24 pairs + 40 new gated pairs
    assert rf.POLICY["buggy_code"].target == rf.registered_pairs() == 64
    for fam in set(want) - {"buggy_code"}:
        assert rf.POLICY[fam].target == len(store.original_bank(fam)[1])


def test_stop_status_cases():
    s = rf.stop_status
    assert s(98, 98, 0, 0, 200, 0.03, False, False)[0] == "full"
    # ooc: yield < y_min on >= n_min, under half
    st, why = s(2, 98, 200, 3, 200, 0.03, False, False)
    assert st == "ooc" and "yield" in why
    # not yet n_min: keep going
    assert s(2, 98, 199, 0, 200, 0.03, False, False) == (None, "")
    # low yield above half (48/49): partial, never ooc
    st, why = s(48, 49, 60, 1, 60, 0.03, False, False)
    assert st == "partial" and "low yield above half" in why
    # pool exhausted under half: partial, never ooc
    st, why = s(10, 98, 150, 1, 200, 0.03, True, False)
    assert (st, why) == ("partial", "pool exhausted")
    # budget, named
    st, why = s(10, 98, 50, 10, 200, 0.03, False, "gpu_minutes 30")
    assert st == "partial" and "gpu_minutes 30" in why
    # a pilot that meets condition 2 stops at ooc (buggy: 60 pair objects at t2, < 3%)
    assert s(0, 24, 60, 1, 60, 0.03, False, False)[0] == "ooc"
    # crash cap binding (buggy): zero-gain t2 wave with the cap binding
    assert s(5, 24, 20, 20, 60, 0.03, False, False, cap_binding=True) == (
        "partial", "crash cap binding")  # fmt: skip
    # refill_hold blocks ooc
    st, why = s(2, 100, 300_000, 1, 200_000, 5e-5, False, False, hold="v4-pro funnel check")
    assert st == "partial" and "v4-pro funnel check" in why


# ============================================================================ pools
def test_pool_loader_refuses_unpinned_missing_and_mismatch(tmp_path, monkeypatch):
    monkeypatch.setenv("WSB_POOL_DIR", str(tmp_path))
    monkeypatch.setitem(rf.POOL_SHA256, "msdm", None)
    with pytest.raises(SystemExit, match="not pinned"):
        rf.load_pool("msdm")
    data = b'{"header": {"n": 1}}\n{"id": "k1"}\n'
    good = hashlib.sha256(data).hexdigest()
    monkeypatch.setitem(rf.POOL_SHA256, "msdm", good)
    with pytest.raises(SystemExit, match="missing"):
        rf.pool_path("msdm")
    (tmp_path / "msdm_pool.jsonl").write_bytes(data + b"{}\n")
    bad = hashlib.sha256(data + b"{}\n").hexdigest()
    with pytest.raises(SystemExit, match=f"pinned {good}, file {bad}"):
        rf.load_pool("msdm")
    (tmp_path / "msdm_pool.jsonl").write_bytes(data)
    assert rf.load_pool("msdm") == [{"header": {"n": 1}}, {"id": "k1"}]
    assert rf.pool_path("msdm") == tmp_path / "msdm_pool.jsonl"
    obj = b'{"items": []}'
    (tmp_path / "mh2_pool.json").write_bytes(obj)
    monkeypatch.setitem(rf.POOL_SHA256, "mh2", hashlib.sha256(obj).hexdigest())
    assert rf.load_pool("mh2") == {"items": []}
    with pytest.raises(SystemExit, match="unknown pool"):
        rf.load_pool("nope")


def test_pool_dir_default_and_no_pin_yet(monkeypatch):
    monkeypatch.delenv("WSB_POOL_DIR", raising=False)
    assert str(rf.pool_dir()) == "/workspace/wsb-runs/pools"
    assert set(rf.POOL_FILES) == set(rf.POOL_SHA256) == {"msdm", "kcutoff", "mh2", "mh2v2"}


def test_no_pool_file_is_tracked_by_git():
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    from wsbench.registry import REPO_ROOT

    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True,
                         text=True, timeout=30)  # fmt: skip
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = [f for f in out.stdout.splitlines() if "_pool.json" in f.rsplit("/", 1)[-1]]
    assert tracked == []


# ============================================================================ has_path a[].b
def test_has_path_and_get_path_list_form():
    it = {"units": [{"kind": "person", "f": {"en": 1}}, {"kind": "work", "f": {"en": 2}}]}
    assert run.has_path(it, "units[].kind") and run.has_path(it, "units[].f.en")
    assert run.get_path(it, "units[].kind") == ["person", "work"]
    assert not run.has_path({"units": [{"kind": "x"}, {}]}, "units[].kind")
    assert not run.has_path({"units": []}, "units[].kind")
    assert not run.has_path({"units": {"kind": "x"}}, "units[].kind")
    assert not run.has_path({}, "units[].kind")
    assert run.get_path({}, "units[].kind") is None
    assert run.has_path({"a": {"b": 1}}, "a.b") and run.get_path({"a": {"b": 1}}, "a.b") == 1


# ============================================================================ buggy selection
def test_selected_pairs_counts_mutual_twins_only():
    rows = [*_pair("a"), _row({"name": "o1", "src": "clean"})]
    rows.append(_row({"name": "x1", "src": "buggy", "twin": "x2"}))
    rows.append(_row({"name": "x2", "src": "clean", "twin": "zz"}))  # not mutual
    assert rf.selected_pairs(rows) == 1


def test_buggy_selection_crash_pairs_never_displace_non_crash_and_cap():
    crash = [r for i in range(4) for r in _pair(f"c{i}", "t2", crash=True)]  # the pilot, first
    nc = [r for i in range(5) for r in _pair(f"n{i}")]
    got = rf.buggy_selection(crash + nc, 63, None)
    ids = [r["id"] for r in got]
    assert ids[:10] == [r["id"] for r in nc]  # non-crash first, in gate order
    assert rf.selected_pairs(got) == 5 + 5 // 4  # crash <= floor(n_nc / 4)
    assert ids[10:] == [r["id"] for r in crash[:2]]
    # independent of order
    assert rf.selected_pairs(rf.buggy_selection(nc + crash, 63, None)) == 6
    # quota still caps the item mix: only 3 buggy -> 3 pairs, the first non-crash ones
    got = rf.buggy_selection(crash + nc, 63, {"buggy": 3, "clean": 38})
    assert [r["id"] for r in got] == [r["id"] for r in nc[:6]]
    # a failed clean twin drops its buggy partner (pre-existing select behaviour)
    got = rf.buggy_selection(_pair("f", clean_ok=False) + _pair("g"), 63, None)
    assert [r["id"] for r in got] == [r["id"] for r in _pair("g")]


def test_bugclaim_leg_required_on_clean_rows():
    no_claim = [_row(r["item"], origin="authored", bugclaim=False) for r in _pair("a")]
    assert rf.row_passes("buggy_code", no_claim[0])  # buggy member: gate pass is enough
    assert not rf.row_passes("buggy_code", no_claim[1])
    assert rf.buggy_selection(no_claim, 63, None) == []
    alt = copy.deepcopy(no_claim[1])
    alt["gate"]["legs"]["bugclaim:greedy"] = _leg()
    assert rf.row_passes("buggy_code", alt)


def test_select_hook_applies_to_new_rows_only(monkeypatch):
    from wsbench.adapt import mhmt2

    rows = [_row({"id": "o1"}), _row({"id": "n1"}, origin="refill"), _row({"id": "o2"}),
            _row({"id": "n2"}, origin="refill")]  # fmt: skip
    monkeypatch.delattr(mhmt2, "select_refill", raising=False)
    assert rf.apply_select_hook("multihop_mt", rows) == rows  # no hook: identity
    monkeypatch.setattr(mhmt2, "select_refill", lambda rs: list(reversed(rs))[:1], raising=False)
    got = [r["id"] for r in rf.apply_select_hook("multihop_mt", rows)]
    assert got == ["o1", "o2", "n2"]
    monkeypatch.setattr(mhmt2, "row_passes", lambda r: r["id"] != "o2", raising=False)
    passes = [r["gate"]["pass"] for r in rf.freeze_rows("multihop_mt", rows)]
    assert passes == [True, False, True]


# ============================================================================ freeze (buggy pairs)
def _registered_buggy_size():
    """(pairs, items) of the registered bank: the freeze's pair target and item cap."""
    return rf.registered_pairs(), len(store.original_bank("buggy_code")[1])


def _registered_buggy_rows(n_orphans_pass):
    _h, items = store.original_bank("buggy_code")
    rows, orphans = [], 0
    for it in items:
        ok = True
        if not it.get("twin"):
            ok = it["src"] == "clean" and orphans < n_orphans_pass
            orphans += ok
        rows.append(_row(copy.deepcopy(it), ok))
    return rows


def test_freeze_buggy_registered_pairs_and_7_singletons_is_full(mdir):
    pairs, size = _registered_buggy_size()  # 64 pairs, 143 items (24 and 63 on items.json)
    _gate_log(mdir, "buggy_code", _registered_buggy_rows(7))
    run.freeze(MODEL, ["buggy_code"], strict=True)
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    assert rep["n_items"] == 2 * pairs + 7 and rep["target"] == size
    assert (rep["n_pairs"], rep["target_pairs"], rep["status"]) == (pairs, pairs, "full")


def test_freeze_buggy_clean_without_bugclaim_drops_its_pair(mdir):
    rows = _registered_buggy_rows(7)
    clean = next(r for r in rows if r["item"].get("twin") and r["item"]["src"] == "clean")
    del clean["gate"]["legs"]["bugclaim"]
    _gate_log(mdir, "buggy_code", rows)
    run.freeze(MODEL, ["buggy_code"])  # library default: no guard
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    pairs, _size = _registered_buggy_size()
    assert (rep["n_pairs"], rep["n_items"], rep["status"]) == (pairs - 1, 2 * pairs + 5, "untried")
    bank = json.loads((mdir / "buggy_code.json").read_text())
    assert clean["id"] not in {store.item_id(it) for it in bank["items"]}
    assert clean["item"]["twin"] not in {store.item_id(it) for it in bank["items"]}


def test_freeze_warns_and_notes_clean_rows_without_bugclaim(mdir, capsys):
    rows = _registered_buggy_rows(7)
    stale = [r for r in rows if r["item"]["src"] == "clean" and r["gate"]["pass"]]
    for r in stale:  # every clean row gated before plan 0066
        del r["gate"]["legs"]["bugclaim"]
    _gate_log(mdir, "buggy_code", rows)
    want = rf.bugclaim_warning(len(stale))
    assert f"{len(stale)} clean rows have no bugclaim leg" in want
    assert "refill families=buggy_code" in want and "gate families=buggy_code regate=true" in want
    run.freeze(MODEL, ["buggy_code"])  # library default: shipped, but loudly
    assert want in capsys.readouterr().out
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    assert rep["n_pairs"] == 0 and rep["freeze_notes"][0] == want


def test_strict_freeze_refuses_clean_rows_without_bugclaim_unless_allowed(mdir):
    rows = _registered_buggy_rows(7)
    clean = next(r for r in rows if r["item"].get("twin") and r["item"]["src"] == "clean")
    del clean["gate"]["legs"]["bugclaim"]
    _gate_log(mdir, "buggy_code", rows)
    for fams in (["buggy_code"], None):  # the CLI's whole-set freeze too
        with pytest.raises(SystemExit, match="1 clean rows have no bugclaim leg"):
            run.freeze(MODEL, fams, strict=True)
    assert not (mdir / "buggy_code.json").exists()
    run.freeze(MODEL, ["buggy_code"], strict=True, allow_untried="regate pending")
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    assert rep["freeze_notes"][0] == rf.bugclaim_warning(1)
    assert rep["n_pairs"] == _registered_buggy_size()[0] - 1


def test_strict_freeze_guard_for_a_policy_family(mdir):
    rows = _registered_buggy_rows(7)
    for r in rows[:6]:
        r["gate"]["pass"] = False
    _gate_log(mdir, "buggy_code", rows)
    run.freeze(MODEL, ["buggy_code"])  # library default: unchanged behaviour
    run.freeze(MODEL)  # families omitted: no guard even when strict
    run.freeze(MODEL, strict=True)
    with pytest.raises(SystemExit, match="never refilled"):
        run.freeze(MODEL, ["buggy_code"], strict=True)
    store.update_report(MODEL, lambda r: r["families"]["buggy_code"].update(
        refill="easiest tier yield < 3% on >= 60 candidates"))  # fmt: skip
    run.freeze(MODEL, ["buggy_code"], strict=True)  # an old string block counts as a refill
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    assert rf.refill_block(rep) == {"stop": "easiest tier yield < 3% on >= 60 candidates"}
    assert rep["change"].endswith("; refill: easiest tier yield < 3% on >= 60 candidates")
    block = {"route": "run.fill", "unit": "pairs", "target": 24, "have": 20, "tried": 40,
             "landed": 10, "yield": 0.25, "stop": "max waves (8)", "pilot": False}  # fmt: skip
    store.update_report(MODEL, lambda r: r["families"]["buggy_code"].update(refill=block))
    run.freeze(MODEL, ["buggy_code"], strict=True)
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    assert rep["change"].startswith("refill via run.fill: 20/24 pairs")
    assert "stop: max waves (8)" in rep["change"]
    # a pilot that did not stop the family as ooc is not a refill
    store.update_report(MODEL, lambda r: r["families"]["buggy_code"].update(
        refill={**block, "pilot": True}, status="partial"))  # fmt: skip
    with pytest.raises(SystemExit, match="only a pilot"):
        run.freeze(MODEL, ["buggy_code"], strict=True)


def test_strict_freeze_guard_untried_fill_family_and_allow_untried(mdir):
    _h, items = store.original_bank("association")
    _gate_log(mdir, "association", [_row(copy.deepcopy(it)) for it in items[:3]])
    run.freeze(MODEL, ["association"])  # library default: untried, written
    rep = json.loads((mdir / "report.json").read_text())["families"]["association"]
    assert rep["status"] == "untried" and "note" not in rep
    with pytest.raises(SystemExit, match="untried"):
        run.freeze(MODEL, ["association"], strict=True)
    run.freeze(MODEL, ["association"], strict=True, allow_untried="subject too small to author")
    rep = json.loads((mdir / "report.json").read_text())["families"]["association"]
    assert "allow_untried" in rep["note"] and "subject too small to author" in rep["note"]
    run.freeze(MODEL, ["association"], strict=True, allow_untried="subject too small to author")
    rep2 = json.loads((mdir / "report.json").read_text())["families"]["association"]
    assert rep2["note"] == rep["note"]  # stamped once


# ============================================================================ CLI
def test_cli_freeze_is_strict_and_refill_keys(monkeypatch):
    from wsbench.adapt import __main__ as cli

    seen = {}
    monkeypatch.setattr(run, "freeze", lambda m, f, **kw: seen.update(m=m, f=f, **kw))
    monkeypatch.setattr(run, "status", lambda m: None)
    cli.main(["freeze", f"model={MODEL}", "families=association"])
    assert seen["strict"] is True and seen["allow_untried"] is False
    cli.main(["freeze", f"model={MODEL}", "families=association", "allow_untried=late model"])
    assert seen["allow_untried"] == "late model"
    cli.main(["freeze", f"model={MODEL}", "allow_untried=true"])
    assert seen["f"] is None and seen["allow_untried"] is True
    got = {}
    monkeypatch.setattr(rf, "refill", lambda m, f, **kw: got.update(m=m, f=f, **kw))
    cli.main(["refill", f"model={MODEL}", "families=knowledge_cutoff,buggy_code", "waves=3",
              "gpu_minutes=30", "claude_budget=500", "pilot=true"])  # fmt: skip
    assert got["f"] == ["knowledge_cutoff", "buggy_code"] and got["pilot"] is True
    assert (got["waves"], got["gpu_minutes"], got["claude_budget"]) == (3, 30.0, 500)
    with pytest.raises(SystemExit, match="unknown argument"):
        cli.main(["refill", f"model={MODEL}", "families=buggy_code", "wave=3"])
    with pytest.raises(SystemExit, match="unknown argument"):
        cli.main(["freeze", f"model={MODEL}", "strict=false"])


# ============================================================================ refill driver
def test_refill_driver_writes_the_block_and_stops_ooc(mdir, monkeypatch):
    from wsbench.adapt import kcutoff

    calls = []

    def wave(model, *, wave, runner=None, llm=None, **kw):
        calls.append(wave)
        return {"tried": 500, "landed": 2, "exhausted": False, "pool_size": 5000,
                "pool_used": 500 * (wave + 1), "claude_calls": 10}  # fmt: skip

    monkeypatch.setattr(kcutoff, "refill_wave", wave, raising=False)
    assert rf.refill(MODEL, ["knowledge_cutoff"], waves=8) == {"knowledge_cutoff": "ooc"}
    assert calls == [0, 1]
    rep = json.loads((mdir / "report.json").read_text())["families"]["knowledge_cutoff"]
    b = rep["refill"]
    assert set(b) >= {
        "route",
        "unit",
        "target",
        "have",
        "tried",
        "landed",
        "yield",
        "waves",
        "n_min",
        "y_min",
        "tally",
        "pool_size",
        "pool_used",
        "stop",
        "budget",
    }
    assert (b["tried"], b["landed"], b["waves"], b["n_min"], b["y_min"]) == (1000, 4, 2, 1000,
                                                                           0.01)  # fmt: skip
    assert (b["pool_size"], b["pool_used"], rep["status"]) == (5000, 1000, "ooc")


def test_refill_driver_no_ooc_while_a_harder_level_is_untried(mdir, monkeypatch):
    """multihop_mt: a 2-hop tally under y_min is not ooc while 3-hop pool candidates remain
    ungated (``mhmt2.untried_levels``); once none remain, the plan's ooc rule applies."""
    from wsbench.adapt import mhmt2

    left = {"n": 2}  # 3-hop candidates remain for the first two checks

    def wave(model, *, wave, runner=None, llm=None, **kw):
        left["n"] -= 1
        return {"tried": 300, "landed": 2, "exhausted": False, "claude_calls": 1}

    monkeypatch.setattr(mhmt2, "refill_wave", wave, raising=False)
    monkeypatch.setattr(mhmt2, "untried_levels", lambda m: ["3hop"] if left["n"] > 0 else [])
    assert rf.refill(MODEL, ["multihop_mt"])["multihop_mt"] == "ooc"
    b = json.loads((mdir / "report.json").read_text())["families"]["multihop_mt"]["refill"]
    assert b["waves"] == 2 and b["tried"] == 600 and b["untried_levels"] == []
    # the pilot still stops at n_min, never ooc, while the harder level is untried
    left["n"] = 5
    assert rf.refill(MODEL, ["multihop_mt"], pilot=True)["multihop_mt"] == "partial"
    b = json.loads((mdir / "report.json").read_text())["families"]["multihop_mt"]["refill"]
    assert b["stop"].startswith("pilot") and b["untried_levels"] == ["3hop"]


def test_refill_driver_hold_pilot_budget_and_missing_route(mdir, monkeypatch):
    from wsbench.adapt import kcutoff, mhmt2

    def wave(model, *, wave, runner=None, llm=None, **kw):
        return {"tried": 150, "landed": 30, "exhausted": False, "claude_calls": 400}

    monkeypatch.setattr(mhmt2, "refill_wave", wave, raising=False)
    # the pilot stops once n_min (300) candidates are tallied and yield is fine: not ooc
    assert rf.refill(MODEL, ["multihop_mt"], pilot=True)["multihop_mt"] == "partial"
    b = json.loads((mdir / "report.json").read_text())["families"]["multihop_mt"]["refill"]
    assert b["pilot"] is True and b["tried"] == 300 and b["stop"].startswith("pilot")
    # a Claude budget, counted from the waves' own call counts
    assert rf.refill(MODEL, ["multihop_mt"], claude_budget=300)["multihop_mt"] == "partial"
    b = json.loads((mdir / "report.json").read_text())["families"]["multihop_mt"]["refill"]
    assert "claude_budget 300" in b["stop"] and b["waves"] == 3  # waves accumulate across runs
    # refill_hold blocks ooc
    store.update_report(MODEL, lambda r: r.setdefault("families", {}).setdefault(
        "knowledge_cutoff", {}).update(refill_hold="pipeline check"))  # fmt: skip
    monkeypatch.setattr(kcutoff, "refill_wave", lambda m, **kw: {"tried": 1000, "landed": 0},
                        raising=False)  # fmt: skip
    assert rf.refill(MODEL, ["knowledge_cutoff"])["knowledge_cutoff"] == "partial"
    rep = json.loads((mdir / "report.json").read_text())["families"]["knowledge_cutoff"]
    assert "pipeline check" in rep["refill"]["stop"]
    monkeypatch.delattr(kcutoff, "refill_wave")
    with pytest.raises(SystemExit, match="not implemented yet"):
        rf.refill(MODEL, ["knowledge_cutoff"])
    with pytest.raises(SystemExit, match="no refill route"):
        rf.refill(MODEL, ["typo_mt"])


def test_prior_tally_counts_the_gate_log(mdir):
    rows = [_row({"id": f"k{i}"}, ok=i < 3, origin="refill") for i in range(10)]
    rows.append({**_row({"id": "lint"}, ok=False), "gate": {"pass": False, "lint": ["x"]}})
    _gate_log(mdir, "knowledge_cutoff", rows)
    assert rf.prior_tally(MODEL, "knowledge_cutoff") == (10, 3)


# ============================================================================ fill (buggy pairs)
def _fake_buggy_fill(monkeypatch, mdir, rule):
    """author writes n pair objects at the tier; the gate passes each per ``rule(tier, i)``."""
    from wsbench.adapt import author

    authored, caps = [], []

    def fake_author(model, family, tier, n, steer="", wave=0):
        authored.append((tier, n, wave))
        items = []
        for i in range(n):
            for r in _pair(f"w{wave}i{i}", tier, crash=tier == "t2"):
                it = r["item"]
                it["name"] = it["name"].replace("-w1c0-", f"-w{wave}c0-")
                it["adapt"]["wave"] = wave
                items.append(it)
        store.add_candidates(model, family, items)
        return len(items)

    def fake_gate(model, family, runner, draws, temperature, llm, items=None):
        cands = store.pending(model, family)
        rows = []
        for i, c in enumerate(cands):
            rows.append(_row(c, rule(c["adapt"]["tier"], i // 2), "authored"))
        store.record_gates(model, family, rows)
        return rows, {}

    real_select = run.select

    def spy_select(family, rows, target, quota=None):
        caps.append(target)
        return real_select(family, rows, target, quota)

    monkeypatch.setattr(author, "author", fake_author)
    monkeypatch.setattr(run, "lint_and_gate", fake_gate)
    monkeypatch.setattr(run, "select", spy_select)
    return authored, caps


def test_fill_buggy_pilot_t2_all_pass_is_not_ooc_and_stops_on_the_crash_cap(mdir, monkeypatch):
    authored, caps = _fake_buggy_fill(monkeypatch, mdir, lambda tier, i: True)
    st = run.fill(MODEL, "buggy_code", llm=None, max_waves=8, runner=object(), pilot=True)
    assert st == "partial"
    assert {t for t, _n, _w in authored} == {"t2"} and len(authored) == 1
    pairs, size = _registered_buggy_size()
    assert caps and set(caps) == {size}  # select keeps the registered item cap, never the pairs
    rep = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]
    b = rep["refill"]
    assert b["stop"] == "crash cap binding" and b["unit"] == "pairs" and b["target"] == pairs
    assert b["tally"]["t2"]["landed"] == b["tally"]["t2"]["tried"] > 0  # before the cap
    assert b["authored_pairs"]["crash"] > 0 and b["have"] == 0


def test_fill_buggy_t2_seeds_from_the_pilot_tally_and_ooc(mdir, monkeypatch):
    # the pilot: 60 t2 pair objects, 1 landed (< 3%)
    pilot = [r for i in range(60) for r in _pair(f"p{i}", "t2", crash=True, ok=i == 0)]
    _gate_log(mdir, "buggy_code", pilot)
    authored, _caps = _fake_buggy_fill(monkeypatch, mdir, lambda tier, i: False)
    st = run.fill(MODEL, "buggy_code", llm=None, max_waves=8, runner=object())
    assert st == "ooc"
    # t1 stepped down after 3 low waves; t2's counters came from the pilot, so no t2 authoring
    assert [t for t, _n, _w in authored] == ["t1"] * 3
    assert len({w for _t, _n, w in authored}) == 3  # fresh wave ids
    b = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]["refill"]
    assert b["tally"]["t2"] == {"tried": 60, "landed": 1} and b["tally"]["t1"]["landed"] == 0


def test_fill_buggy_full_counts_pairs_and_pilot_is_buggy_only(mdir, monkeypatch):
    _gate_log(mdir, "buggy_code", _registered_buggy_rows(0))  # 24 registered pairs pass
    authored, _caps = _fake_buggy_fill(monkeypatch, mdir, lambda tier, i: True)
    assert run.fill(MODEL, "buggy_code", llm=None, runner=object()) == "full"
    assert authored == []
    with pytest.raises(SystemExit, match="buggy_code only"):
        run.fill(MODEL, "typo_mt", llm=None, runner=object(), pilot=True)


def test_fill_buggy_stops_on_claude_budget_through_refill(mdir, monkeypatch):
    """plan 0066 §1.2: `adapt refill` passes claude_budget to buggy_code's run.fill; author calls
    (ceil(n / 20) per wave) plus grading calls (the grader's cache growth) count against it."""

    class Grader:
        def __init__(self):
            self.cache = {}

        def __call__(self, ask, answers):
            return [True for _ in answers]

    grader = Grader()
    monkeypatch.setattr(run, "_llm", lambda name: grader)
    authored, _caps = _fake_buggy_fill(monkeypatch, mdir, lambda tier, i: False)
    real_gate = run.lint_and_gate

    def gate_and_grade(model, family, runner, draws, temperature, llm, items=None):
        assert llm is grader
        n = len(store.pending(model, family))
        grader.cache.update({f"k{len(grader.cache) + i}": True for i in range(n)})
        return real_gate(model, family, runner, draws, temperature, llm, items)

    monkeypatch.setattr(run, "lint_and_gate", gate_and_grade)
    st = rf.refill(MODEL, ["buggy_code"], waves=8, claude_budget=5, gpu_minutes=60, runner=object())
    assert st == {"buggy_code": "partial"}
    assert len(authored) == 1  # the first wave's calls (author + grades) exceed 5
    b = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]["refill"]
    assert b["stop"] == "budget spent (claude_budget 5)"
    n = authored[0][1]
    assert b["budget"]["claude_calls"] == -(-n // 20) + 2 * n  # 2 items per pair object
    assert b["budget"]["claude_budget"] == 5


def test_fill_buggy_claude_budget_counts_author_calls_without_a_grader(mdir, monkeypatch):
    authored, _caps = _fake_buggy_fill(monkeypatch, mdir, lambda tier, i: False)
    st = run.fill(MODEL, "buggy_code", llm=None, max_waves=8, runner=object(), claude_budget=3)
    assert st == "partial"
    b = json.loads((mdir / "report.json").read_text())["families"]["buggy_code"]["refill"]
    assert b["stop"] == "budget spent (claude_budget 3)"
    assert b["budget"]["claude_calls"] == sum(-(-n // 20) for _t, n, _w in authored) >= 3
    assert len(authored) == 2  # 30 pair objects a wave: 2 author calls each


def test_cli_pool_arg_passes_a_mode_through():
    """plan 0066: `pool=ext` reaches msdm / kcutoff as the mode string, booleans as before."""
    from wsbench.adapt.__main__ import _pool_arg

    assert _pool_arg("true") is True and _pool_arg("false") is False
    assert _pool_arg("ext") == "ext" and _pool_arg("Retired") == "retired"
