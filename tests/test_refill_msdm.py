"""Plan 0066 §3 / §10 / §11: msdm refill from the GW category pool (pool modes, item construction,
waves, validity legs, domain cap, the pool builder), offline with a fake runner and fake Claude."""

import hashlib
import json
import re

import pytest

from wsbench.adapt import msdm, refill, store
from wsbench.adapt.selfans import norm

MODEL = "qwen3.5-4b"
OWL = "s2_genus_of_typical_owl_strigidae"
OWL_Q = "What is your favorite genus of typical owl in the family Strigidae?"
PINE = "s2_european_black_pine_subspecies"
STEW = "s1_persian_khoresh_stew"
A, B, C1, C2, C3 = (
    "s1_t_alpha_widget",
    "s2_t_greek_letter",
    "s3b1_t_gizmo_one",
    "s3b1_t_gizmo_two",
    "s3b2_t_gizmo_three",
)


class FakeRunner:
    """``Runner.sample`` scripted per (item id, leg); unscripted asks answer "" (a refusal).
    Records every ask's (id, leg, messages)."""

    def __init__(self, script=None):
        self.script, self.calls, self.asks = script or {}, [], []

    def sample(self, asks, draws, temperature, top_p=1.0):
        self.calls.append((len(asks), draws, temperature, top_p))
        out = []
        for a in asks:
            self.asks.append((a.item_id, a.leg, json.dumps(a.messages, ensure_ascii=False)))
            g, s = self.script.get((a.item_id, a.leg), ("", [""] * draws))
            out.append((g, (list(s) * draws)[:draws]))
        return out


class FakeClaude:
    """CANON / GENERATE / VERIFY as in test_adapt_self_answer, plus MEMBER and QA."""

    def __init__(self, member=True, verdict="keep"):
        self.member, self.verdict, self.prompts = member, verdict, []

    def __call__(self, prompt, valid=None):
        self.prompts.append(prompt)
        if "Known canonical labels" in prompt:
            lines = prompt.split("Strings:\n", 1)[1].split("\n\nReply", 1)[0].split("\n")
            return {"map": {s: s for s in lines if s}}
        if "For EACH answer list the strings" in prompt:
            opts = re.findall(r"^- (.+)$", prompt, re.M)
            return {"forms": {o: [o.title(), f"{o} letter"] for o in opts}}
        if "candidate strings were proposed" in prompt:
            return {"flags": {}}
        if prompt.startswith("Category question:"):
            return {"member": self.member, "reason": "r"}
        if prompt.startswith("You are auditing one item"):
            return {"verdict": self.verdict, "reason": "r", "aliases": ["Σ"]}
        raise AssertionError(prompt[:80])


@pytest.fixture
def tmp_model(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / "m" / model)
    return tmp_path / "m" / MODEL


# ------------------------------------------------------------------ a synthetic GW source tree


def _gate_row(key, topic, domain, gold, **kw):
    row = {
        "key": key,
        "domain": domain,
        "type": kw.pop("type", "taxonomy"),
        "topic": topic,
        "gold": gold,
        "n_eq": 9,
        "reveal": gold,
        "g0_stable": True,
        "g0": True,
        "legacy": {},
        "peer": {},
        "peer_diff": 0,
        "g1_opus": False,
        "g1": False,
    }
    row.update(kw)
    return row


def _cat(key, noun, domain, question=None, type_="taxonomy"):
    topic = f"favorite {noun}"
    return {
        "key": key,
        "topic": topic,
        "noun": noun,
        "question": question or f"What is your {topic}?",
        "domain": domain,
        "type": type_,
    }


def _write_source(root):
    stew = {it["id"]: it for _o, it in msdm.candidates(True)}[STEW]
    src = {
        "step1": (
            [
                _cat(A, "alpha widget", "Widgets"),
                _cat(
                    STEW,
                    "Persian khoresh stew",
                    "Persian cuisine",
                    f"What is your {stew['topic']}?",
                ),  # bank key, today's question
                _cat("s1_t_spice_dup", "MIDDLE EASTERN SPICE BLEND", "x"),  # bank noun (folded)
                _cat("s1_t_no_gate", "orphan thing", "x"),  # not in gate.json
            ],
            {
                "rows": [
                    _gate_row(
                        A,
                        "favorite alpha widget",
                        "Widgets",
                        "widget a",
                        peer={"gemma4": "Widget B!"},
                        options=["widget a", "widget b"],
                    ),
                    _gate_row(STEW, "favorite Persian khoresh stew", "Persian cuisine", "gheymeh"),
                    _gate_row("s1_t_spice_dup", "favorite x", "x", "y"),
                ],
                "maps": {A: {"widget b!": "widget b"}},
            },
        ),
        "step2": (
            [
                _cat(B, "Greek letter name", "Greek letters"),
                _cat("s2_t_alpha_dup", "Alpha  Widget", "Widgets"),  # pool noun (folded)
                _cat(OWL, "genus of typical owl (Strigidae)", "Owls", OWL_Q),
                _cat(
                    PINE, "European black pine subspecies", "Pines", msdm.QUESTION_OVERRIDES[PINE]
                ),
            ],
            {
                "rows": [
                    _gate_row(
                        B,
                        "favorite Greek letter name",
                        "Greek letters",
                        "tau",
                        legacy={"llama": "Omega!"},
                        peer={"gemma4": "theta", "qwen": "x"},
                        qwen_samples=["tau"] * 9 + ["Sigma "],
                        options=["tau", "omega", "theta"],
                        option_sources={
                            "tau": ["gold"],
                            "omega": ["opus_typical"],
                            "theta": ["peer:gemma4"],
                        },
                        opus={"typ_recall": ["omega"] * 3, "inf_recall": ["tau"] * 3},
                        sonnet={"typ_recall": ["omega"], "inf_recall": ["tau"]},
                    ),
                    _gate_row("s2_t_alpha_dup", "favorite alpha widget", "Widgets", "q"),
                    _gate_row(OWL, "favorite genus", "Owls", "strix"),
                    _gate_row(PINE, "favorite pine", "Pines", "laricio"),
                ],
                "maps": {B: {"omega!": "omega", "sigma": "sigma"}},
            },
        ),
        "step3/b1": (
            [_cat(C1, "gizmo one", "Gizmos"), _cat(C2, "gizmo two", "gizmos ")],
            {
                "rows": [
                    _gate_row(C1, "favorite gizmo one", "Gizmos", "g1"),
                    _gate_row(C2, "favorite gizmo two", "gizmos ", "g2"),
                ],
                "maps": {},
            },
        ),
        "step3/b2": (
            [_cat(C3, "gizmo three", "Gizmos"), _cat(B, "Greek letter name", "Greek letters")],
            {
                "rows": [
                    _gate_row(C3, "favorite gizmo three", "Gizmos", "g3"),
                    _gate_row(B, "favorite Greek letter name", "x", "tau"),
                ],
                "maps": {},
            },
        ),
    }
    for rel, (cats, gate) in src.items():
        d = root / rel
        d.mkdir(parents=True)
        (d / "cats.json").write_text(json.dumps(cats), encoding="utf-8")
        (d / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
    return root


def _pin(monkeypatch, path):
    monkeypatch.setenv("WSB_POOL_DIR", str(path.parent))
    monkeypatch.setitem(refill.POOL_SHA256, "msdm", hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.fixture
def pool(tmp_path, monkeypatch):
    path = msdm.build_pool(tmp_path / "pools", root=_write_source(tmp_path / "gw"))
    _pin(monkeypatch, path)
    return path


def _ext():
    return {it["id"]: it for o, it in msdm.candidates("ext") if o == "refill"}


def _script(items):
    """B: the subject's stable default is sigma; every refill item copies its carrier."""
    s = {(iid, "compliance"): (it["carrier"], [it["carrier"]]) for iid, it in items.items()}
    s[(B, "surface")] = ("Sigma", ["sigma"] * 9 + ["omega"])
    s[(B, "reveal")] = ("Sigma.", [])
    return s


# ------------------------------------------------------------------ constants and modes


def test_gate_constants_unchanged():
    assert msdm.MIN_AGREE == 7 and msdm.DIRECT_T == 1.0 and msdm.DIRECT_DRAWS == 10
    assert msdm.COMPLY_THRESHOLD == 0.8 and msdm.COMPLY_T == 0.7
    assert msdm.K == 5 and msdm.MIN_OPTIONS == 2
    assert msdm.WAVE_SIZE == 200 and msdm.DOMAIN_CAP == 2
    assert msdm.KEEP_VERDICTS == ("keep", "keep_with_aliases")


def test_pool_mode_compat():
    assert msdm.pool_mode(True) == "retired" and msdm.pool_mode(False) == "none"
    assert [msdm.pool_mode(m) for m in msdm.POOL_MODES] == list(msdm.POOL_MODES)
    with pytest.raises(SystemExit):
        msdm.pool_mode("everything")
    assert msdm.candidates(True) == msdm.candidates("retired")
    assert len(msdm.candidates(False)) == 98 and len(msdm.candidates(True)) == 130


def test_pinned_prompts_are_verbatim_and_undoubled():
    assert "{{" not in msdm.MEMBER + msdm.QA and '{"member": true/false' in msdm.MEMBER
    assert msdm.QA.count("{preds}") == 1 and '"verdict": "..."' in msdm.QA
    it = {"topic": "favorite Greek letter name", "noun": "Greek letter name"}
    p = msdm.qa_prompt(it, "sigma", ["omega", "tau"])
    assert 'stable answer (the GOLD label) is "sigma". Other models predicted: omega, tau.' in p
    assert msdm.member_prompt(it, "sigma").startswith(
        'Category question: "What is your favorite Greek letter name?" (the answer should be a '
        'specific Greek letter name).\nProposed answer: "sigma".'
    )


def test_question_prefers_item_question():
    bank = {it["id"]: it for _o, it in msdm.candidates(True)}
    spice = bank["middle_eastern_spice_blend"]
    assert "question" not in spice
    assert msdm.question(spice) == "What is your favorite Middle Eastern spice blend?"
    assert msdm.question(bank[PINE]) == msdm.QUESTION_OVERRIDES[PINE]
    assert msdm.question({**spice, "question": "What is your pick?"}) == "What is your pick?"


# ------------------------------------------------------------------ the pool builder and loader


def test_build_pool_shape(pool, tmp_path):
    rows = [json.loads(x) for x in pool.read_text(encoding="utf-8").splitlines()]
    head = rows[0]["header"]
    assert head["kind"] == "msdm_pool" and head["n_rows"] == len(rows) - 1 == 5
    gw = tmp_path / "gw"
    for rel in ("step1", "step2", "step3/b1", "step3/b2"):
        s = head["sources"][rel]
        assert s["cats"] == str(gw / rel / "cats.json")
        assert s["gate_sha256"] == hashlib.sha256((gw / rel / "gate.json").read_bytes()).hexdigest()
    assert head["dedupe"] == {
        "rows_in": 12,
        "key_bank": 3,
        "noun_bank": 1,
        "key_pool": 1,
        "noun_pool": 1,
        "missing_gate": 1,
        "kept": 5,
    }
    # only the retired owl's source question differs (the pine's equals its override)
    assert head["source_questions"] == {OWL: OWL_Q}
    by = {r["id"]: r for r in rows[1:]}
    assert list(by) == [A, B, C1, C2, C3]
    b = by[B]
    assert b["gold"] == "tau" and b["peers"] == {"gemma4": "theta"}  # Qwen never in peers
    assert b["legacy"] == {"llama": "omega"}  # raw strings through the step's maps
    assert b["g0"]["qwen_samples"][-1] == "sigma"
    assert b["g1_pass1"] == {
        "opus": {"typ_recall": ["omega"] * 3},
        "sonnet": {"typ_recall": ["omega"]},
    }
    assert b["options"] == ["tau", "omega", "theta"] and b["option_sources"]["omega"]
    assert b["question"] == "What is your favorite Greek letter name?" and b["type"] == "taxonomy"
    a = by[A]
    assert (
        "g1_pass1" not in a and "option_sources" not in a and a["peers"] == {"gemma4": "widget b"}
    )
    assert "g1_pass1" not in by[C1] and "options" not in by[C1]
    # deterministic bytes
    again = msdm.build_pool(tmp_path / "again", root=gw)
    assert again.read_bytes() == pool.read_bytes()


def test_pool_loader_dedupes_against_bank_and_retired(tmp_path, monkeypatch):
    bank_header, bank = msdm._bank()
    retired = bank_header["retired_panel_gate"][0]
    rows = [
        {"header": {"kind": "msdm_pool"}},
        {"id": bank[0]["id"], "topic": "t", "noun": "n0"},  # bank key
        {"id": "x_retired_noun", "topic": "t", "noun": retired["noun"].upper()},
        {"id": "x_ok", "topic": "favorite ok thing", "noun": "ok thing"},
        {"id": "x_ok_dup", "topic": "t", "noun": "OK  thing"},  # folded noun, in pool
        {"id": "x_ok", "topic": "t", "noun": "other"},
    ]
    path = tmp_path / "p" / "msdm_pool.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    _pin(monkeypatch, path)
    assert list(_ext()) == ["x_ok"]


def test_pool_row_to_item(pool):
    header, bank = msdm._bank()
    regs = msdm.carriers(bank)
    assert len(regs) == 10
    from wsbench.evals.model_specific_directed_modulation.prompts import render_user

    ext = _ext()
    assert set(ext) == {A, B, C1, C2, C3}
    for it in ext.values():
        assert it["carrier"] in regs and it["split"] == "refill"
        assert it["user"] == render_user(it["topic"], it["carrier"])
        assert it["user"] == header["contract"]["prompt"].replace("{topic}", it["topic"]).replace(
            "{carrier}", it["carrier"]
        )
        assert msdm.question(it) == it["question"] and "source" not in it
    assert {iid: it["carrier"] for iid, it in _ext().items()} == {
        iid: it["carrier"] for iid, it in ext.items()
    }  # seeded, not random
    # under ext, the retired owl takes its source question; nothing else changes question
    changed = {it["id"] for o, it in msdm.candidates("ext") if o != "refill" and "question" in it}
    assert changed == {OWL}


# ------------------------------------------------------------------ pool=ext absent: unchanged


def test_without_ext_elicit_inputs_are_byte_identical(tmp_model, monkeypatch, tmp_path):
    monkeypatch.setitem(refill.POOL_SHA256, "msdm", None)  # any pool read would SystemExit
    seen = {}
    for name, pool_arg in (("a", True), ("b", "retired")):
        monkeypatch.setattr(store, "model_dir", lambda model, root=None, n=name: tmp_path / n)
        r = FakeRunner()
        msdm.elicit(MODEL, runner=r, pool=pool_arg)
        seen[name] = (r.asks, r.calls, (tmp_path / name / "msdm" / "elicit.json").read_bytes())
    assert seen["a"] == seen["b"]
    header, bank = msdm._bank()
    items = bank + header["retired_panel_gate"]
    direct = [json.loads(m) for i, leg, m in seen["a"][0] if leg == "surface"]
    want = [
        [
            {
                "role": "user",
                "content": (msdm.QUESTION_OVERRIDES.get(it["id"]) or f"What is your {it['topic']}?")
                + msdm.SUF,
            }
        ]
        for it in items
    ]
    assert direct == want
    rec = json.loads(seen["a"][2])
    assert len(rec) == 130 and not any("question" in v or "wave" in v for v in rec.values())


def test_without_ext_build_records_are_unchanged(tmp_model, monkeypatch):
    monkeypatch.setitem(refill.POOL_SHA256, "msdm", None)
    bank = {it["id"]: it for _o, it in msdm.candidates(True)}
    spice = "middle_eastern_spice_blend"
    car = bank[spice]["carrier"]
    script = {
        (spice, "surface"): ("Za'atar", ["za'atar"]),
        (spice, "reveal"): ("Za'atar.", []),
        (spice, "compliance"): (car, [car]),
    }
    msdm.run(MODEL, "all", limit=2, runner=FakeRunner(script), ask=FakeClaude())
    row = store.gated(MODEL, msdm.FAMILY)[spice]
    assert row["gate"]["pass"] and "validity" not in row["gate"]
    assert set(row["gate"]["legs"]) == {"surface", "reveal", "compliance"}
    assert msdm.row_passes(row)  # a pre-0066 build needs no legs
    report = json.loads((tmp_model / "report.json").read_text())
    assert set(report["families"][msdm.FAMILY]["rederive"]) == {
        "version",
        "elicited",
        "g0",
        "compliant",
        "pass",
    }
    assert "refill_note" not in report["families"][msdm.FAMILY]


# ------------------------------------------------------------------ waves and the gate log


def test_ext_wave_reaches_the_gate_log(tmp_model, pool):
    runner, claude = FakeRunner(_script(_ext())), FakeClaude()
    res = msdm.refill_wave(MODEL, wave=0, runner=runner, ask=claude, wave_size=3)
    rows = store.gated(MODEL, msdm.FAMILY)
    order = list(_ext())
    first = set(order[:3])
    assert res["tried"] == 130 + 3 and res["pool_size"] == 5 and res["pool_used"] == 3
    assert not res["exhausted"] and res["claude_calls"] > 0
    assert first <= set(rows) and not set(order[3:]) & set(rows)
    elicited = msdm._load(MODEL, "elicit.json")
    assert {elicited[i]["wave"] for i in first} == {0}
    assert elicited[OWL]["question"] == OWL_Q
    # wave 1: only the rest is asked, nothing re-asked
    n0 = len(runner.asks)
    res = msdm.refill_wave(MODEL, wave=1, runner=runner, ask=claude, wave_size=3)
    asked = {i for i, _leg, _m in runner.asks[n0:]}
    assert asked == set(order[3:]) and res["tried"] == 2 and res["exhausted"]
    assert res["pool_used"] == 5
    rows = store.gated(MODEL, msdm.FAMILY)
    b = rows[B]
    assert b["origin"] == "refill" and b["gate"]["pass"], b["gate"]["reasons"]
    assert set(b["gate"]["legs"]) >= {msdm.LEG_MEMBER, msdm.LEG_QA}
    assert msdm.row_passes(b) and refill.row_passes(msdm.FAMILY, b)
    assert res["landed"] == int(B in set(order[3:]))
    it = b["item"]
    assert it["gold"] == "sigma" and it["qwen_gold"] == "tau"
    assert "opus_typical" in it["option_sources"]["omega"]
    assert "peer:qwen3.6-27b" in it["option_sources"]["tau"]
    assert "peer:gemma4" in it["option_sources"]["theta"]
    assert it["adapt"]["validity"]["verdict"] == "keep" and it["adapt"]["origin"] == "refill"
    assert it["g0"]["question"] == it["question"] + msdm.SUF
    # the QA call shows the built distractors
    qa = [p for p in claude.prompts if p.startswith("You are auditing") and '"sigma"' in p]
    assert qa and f"Other models predicted: {', '.join(it['options'][1:])}." in qa[-1]
    # the other refill rows fail G0 (refusals), and fail visibly
    assert all(not rows[i]["gate"]["pass"] for i in order if i != B)
    assert msdm.prior_tally(MODEL) == (135, 1)
    note = json.loads((tmp_model / "report.json").read_text())["families"][msdm.FAMILY]
    assert note["refill_note"]["question_changed"] == [OWL]
    assert note["refill_note"]["type_mix"] == {"taxonomy": 1}


def test_plan_modes_never_drop_ext_rows(tmp_model, pool):
    msdm.elicit(MODEL, runner=FakeRunner(_script(_ext())), pool="ext", wave=0, wave_size=200)
    assert not set(_ext()) & set(msdm._plan(MODEL))  # pool=True behaves as "retired"
    assert msdm._plan(MODEL, True).keys() == msdm._plan(MODEL, "retired").keys()
    assert set(_ext()) <= set(msdm._plan(MODEL, "ext"))
    msdm.run(MODEL, "canon", pool="ext", ask=FakeClaude())
    msdm.run(MODEL, "units", pool="ext", ask=FakeClaude())
    msdm.run(MODEL, "build", pool="ext", ask=FakeClaude())  # no validity replies yet
    b = store.gated(MODEL, msdm.FAMILY)[B]
    assert not b["gate"]["pass"]
    assert b["gate"]["reasons"] == ["validity: membership / label QA not run (stage=validity)"]
    assert not msdm.row_passes(b)
    msdm.run(MODEL, "validity", pool="ext", ask=FakeClaude())
    assert msdm.row_passes(store.gated(MODEL, msdm.FAMILY)[B])


def test_question_change_re_asks_only_the_owl(tmp_model, pool):
    msdm.elicit(MODEL, runner=FakeRunner(), pool=True)  # the 130, pre-0066 records
    r = FakeRunner()
    msdm.elicit(MODEL, runner=r, pool="ext", wave=0, wave_size=0)
    assert {i for i, _leg, _m in r.asks} == {OWL}
    owl = next(json.loads(m) for _i, leg, m in r.asks if leg == "surface")
    assert owl[0]["content"] == OWL_Q + msdm.SUF
    r = FakeRunner()
    msdm.elicit(MODEL, runner=r, pool="ext", wave=1, wave_size=0)
    assert not r.asks


# ------------------------------------------------------------------ validity legs


@pytest.mark.parametrize(
    "member,verdict,reason",
    [
        (False, "keep", "msdm: gold not a member"),
        (True, "drop", "msdm: label QA verdict 'drop' (need keep or keep_with_aliases)"),
        (True, "keep_ok", "msdm: label QA verdict 'keep_ok' (need keep or keep_with_aliases)"),
    ],
)
def test_validity_legs_fail(tmp_model, pool, member, verdict, reason):
    claude = FakeClaude(member=member, verdict=verdict)
    msdm.refill_wave(MODEL, wave=0, runner=FakeRunner(_script(_ext())), ask=claude)
    b = store.gated(MODEL, msdm.FAMILY)[B]
    assert not b["gate"]["pass"] and b["gate"]["reasons"] == [reason]
    assert not msdm.row_passes(b)
    legs = b["gate"]["legs"]
    assert legs[msdm.LEG_MEMBER]["passed"] is member
    assert legs[msdm.LEG_QA]["passed"] is (verdict in msdm.KEEP_VERDICTS)


def test_keep_with_aliases_passes(tmp_model, pool):
    claude = FakeClaude(verdict="keep_with_aliases")
    msdm.refill_wave(MODEL, wave=0, runner=FakeRunner(_script(_ext())), ask=claude)
    assert msdm.row_passes(store.gated(MODEL, msdm.FAMILY)[B])


def test_failed_validity_replies_are_never_cached(tmp_model, pool):
    calls = []

    def flaky(prompt, valid=None):
        calls.append(prompt)
        if prompt.startswith("Category question:") and len(calls) < 1000:
            return None
        return FakeClaude()(prompt, valid)

    msdm.refill_wave(MODEL, wave=0, runner=FakeRunner(_script(_ext())), ask=flaky)
    assert B not in msdm._load(MODEL, "validity.json")
    assert not msdm.row_passes(store.gated(MODEL, msdm.FAMILY)[B])
    msdm.run(MODEL, "validity", pool="ext", ask=FakeClaude())
    assert msdm.row_passes(store.gated(MODEL, msdm.FAMILY)[B])


def test_row_passes_needs_the_legs():
    ok = {"passed": True}
    legs = {"surface": ok, "reveal": ok, "compliance": ok}
    both = {**legs, msdm.LEG_MEMBER: ok, msdm.LEG_QA: ok}
    req = {"required": True}
    assert not msdm.row_passes({"origin": "refill", "gate": {"pass": True, "legs": legs}})
    assert msdm.row_passes({"origin": "refill", "gate": {"pass": True, "legs": both}})
    assert not msdm.row_passes(
        {"origin": "original", "gate": {"pass": True, "legs": legs, "validity": req}}
    )
    assert msdm.row_passes({"origin": "original", "gate": {"pass": True, "legs": legs}})
    bad = {**both, msdm.LEG_QA: {"passed": False}}
    assert not msdm.row_passes({"origin": "refill", "gate": {"pass": True, "legs": bad}})
    assert not msdm.row_passes({"origin": "refill", "gate": {"pass": False, "legs": both}})


def test_validity_true_applies_to_existing_items(tmp_model, monkeypatch):
    monkeypatch.setitem(refill.POOL_SHA256, "msdm", None)
    bank = {it["id"]: it for _o, it in msdm.candidates(True)}
    spice = "middle_eastern_spice_blend"
    car = bank[spice]["carrier"]
    script = {
        (spice, "surface"): ("Za'atar", ["za'atar"]),
        (spice, "reveal"): ("Za'atar.", []),
        (spice, "compliance"): (car, [car]),
    }
    msdm.run(
        MODEL,
        "all",
        limit=1,
        runner=FakeRunner(script),
        ask=FakeClaude(member=False),
        validity=True,
    )
    row = store.gated(MODEL, msdm.FAMILY)[spice]
    assert row["gate"]["validity"]["required"] and not msdm.row_passes(row)
    assert row["gate"]["reasons"] == ["msdm: gold not a member"]


# ------------------------------------------------------------------ diversity


def _row(iid, domain, passed=True, type_="taxonomy"):
    return {
        "id": iid,
        "origin": "refill",
        "selected": passed,
        "item": {"id": iid, "domain": domain, "type": type_},
        "gate": {"pass": passed, "reasons": []},
    }


def test_domain_cap_keeps_order_and_counts_passing_rows():
    rows = [
        _row("a", "Gizmos"),
        _row("b", "gizmos ", passed=False),
        _row("c", "GIZMOS"),
        _row("d", "Gizmos"),
        _row("e", "Widgets", type_="food_drink"),
        _row("f", "gizmos"),
    ]
    out = msdm.select_refill(rows)
    assert [r["id"] for r in out] == list("abcdef")
    assert [r["gate"]["pass"] for r in out] == [True, False, True, False, True, False]
    assert out[3]["gate"]["reasons"] == ["diversity: domain cap (2 per domain)"]
    assert not out[3]["selected"] and rows[3]["gate"]["pass"]  # a copy, the input untouched
    # the type mix is reported, never capped
    note = msdm.refill_note(out, [{"type": "taxonomy"}, {"type": ""}])
    assert note["type_mix"] == {"food_drink": 1, "taxonomy": 2}
    assert note["registered_type_mix"] == {"taxonomy": 1, "untyped": 1}


def test_select_hook_wired_through_refill():
    orig = {**_row("o", "Gizmos"), "origin": "original"}
    rows = [orig, _row("a", "Gizmos"), _row("b", "Gizmos"), _row("c", "Gizmos")]
    out = refill.apply_select_hook(msdm.FAMILY, rows)
    assert [r["gate"]["pass"] for r in out] == [True, True, True, False]


def test_options_with_and_without_frontier_answers(pool):
    ext = _ext()
    opts, src = msdm.build_options(ext[B], "sigma", [])
    assert opts[0] == "sigma" and src["omega"][0] == "opus_typical"
    assert "sonnet_typical" in src["omega"] and "peer:qwen3.6-27b" in src["tau"]
    opts, src = msdm.build_options(ext[A], "widget c", [])
    assert "peer:gemma4" in src["widget b"] and "peer:qwen3.6-27b" in src["widget a"]
    assert not any(s.startswith(("opus", "sonnet")) for v in src.values() for s in v)
    assert norm(opts[0]) == "widget c"


def test_run_pool_false_elicits_only_the_bank(tmp_model, monkeypatch):
    monkeypatch.setitem(refill.POOL_SHA256, "msdm", None)
    r = FakeRunner()
    msdm.run(MODEL, "elicit", pool=False, runner=r)
    assert len({i for i, _leg, _m in r.asks}) == 98
