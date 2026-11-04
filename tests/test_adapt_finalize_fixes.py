"""Fixes from finalizing the big-model adapted sets (DeepSeek-V4-Pro, Kimi-K3, Muse-Spark-Open):
empty leak draws, slow-tokenizer offsets, the floors' pre-registered cell, the msdm gold's forms
and the freeze note's lost items. Offline, with fakes."""

import copy
import dataclasses
import json
import re

import pytest

from wsbench.adapt import floors, msdm, run, store
from wsbench.adapt.gate import Ask, grade_leg

# ------------------------------------------------------- 1. empty draws in leak legs


def _llm_says_grief(ask, texts):
    """The model grader: "does this text state the gold?" (never called on an empty text)."""
    assert all(t.strip() for t in texts)
    return ["grief" in t for t in texts]


def _leak_legs(greedy, samples, max_rate=0.0):
    det = Ask("x", "leak", ("grief",), prompt="p", grade="contains",
              meta={"leak": True, "max_rate": max_rate})  # fmt: skip
    llm = Ask("x", "leak", ("grief",), prompt="p", grade="llm",
              meta={"leak": True, "max_rate": max_rate})  # fmt: skip
    return (
        grade_leg(det, greedy, samples, 0.8),
        grade_leg(llm, greedy, samples, 0.8, llm=_llm_says_grief),
    )


@pytest.mark.parametrize(
    ("greedy", "samples", "passed"),
    [
        ("She sat.", ["", "  ", "She walked."] + ["She sat."] * 7, True),  # empties excluded
        ("", ["She sat."] * 5 + ["\n"] * 5, True),  # an empty greedy does not block
        ("She sat.", ["", "grief took her"] + ["She sat."] * 8, False),  # a real hit still fails
        ("grief", ["", "She sat."], False),  # a leaking greedy still fails
    ],
)
def test_leak_leg_empty_draws_are_non_evidence_in_both_kinds(greedy, samples, passed):
    det, llm = _leak_legs(greedy, samples)
    assert det.passed is llm.passed is passed
    assert det.rate == llm.rate and det.decided == llm.decided
    n_empty = sum(not s.strip() for s in samples)
    assert det.decided == len(samples) - n_empty  # empties are not in the denominator
    assert [s["ok"] for s in det.samples] == [s["ok"] for s in llm.samples]
    assert all(s["ok"] is None for s in det.samples if not s["text"].strip())


def test_leak_leg_loose_rate_counts_only_non_empty_draws():
    # max_rate 1/4 over the 4 non-empty draws: 1 hit passes (it would not over 10 if empties
    # counted as decided-but-missing, nor if the floor were the raw sample count)
    samples = ["grief", "fine", "fine", "fine"] + [""] * 6
    det, llm = _leak_legs("ok", samples, max_rate=1 / 4)
    assert det.passed and llm.passed and det.rate == llm.rate == 0.75


def test_leak_leg_all_empty_is_undecided_and_fails_in_both_kinds():
    for greedy in ("", "She sat."):
        det, llm = _leak_legs(greedy, ["", " ", "\n"])
        for leg in (det, llm):
            assert not leg.passed and leg.rate is None and leg.decided == 0
            assert leg.reason and "every sampled continuation is empty" in leg.reason
        assert det.reason == llm.reason


def test_non_leak_legs_carry_no_reason_key():
    from wsbench.adapt.gate import _leg_dict

    leg = grade_leg(Ask("x", "surface", ("iron",)), "Iron", ["iron"] * 10, 0.8)
    assert leg.reason is None and "reason" not in _leg_dict(leg)


# ------------------------------------------------------- 2. slow-tokenizer offsets

_PIECES = re.compile(r"'s|\s?\w+|[^\w\s]")


class _FastTok:
    is_fast = True

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        ms = list(_PIECES.finditer(text))
        out = {"input_ids": list(range(len(ms)))}
        if return_offsets_mapping:
            out["offset_mapping"] = [m.span() for m in ms]
        return out


class _SlowTok:
    """A Python tokenizer: no offset mapping (raises like HF's, or omits the key)."""

    is_fast = False

    def __init__(self, omit=False):
        self.vocab: list[str] = []
        self.omit = omit

    def encode(self, text, add_special_tokens=False):
        ids = []
        for piece in _PIECES.findall(text):
            if piece not in self.vocab:
                self.vocab.append(piece)
            ids.append(self.vocab.index(piece))
        return ids

    def decode(self, ids):
        return "".join(self.vocab[i] for i in ids)

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        if return_offsets_mapping and not self.omit:
            raise NotImplementedError("return_offset_mapping is not available (Python tokenizer)")
        return {"input_ids": self.encode(text)}


STIM = "Avery's landlord is Sam. Sam's sibling is Riley. In other words, Riley is Avery's"


@pytest.mark.parametrize("omit", [False, True])
def test_slow_tokenizer_offsets_equal_the_fast_path(omit):
    fast = run.char_offsets(_FastTok(), STIM)
    assert run.char_offsets(_SlowTok(omit=omit), STIM) == fast
    items = [{"id": "rel-x-a", "stimulus": STIM}]
    assert run._check_blank(_SlowTok(omit=omit), items) == (items, [])


def test_slow_tokenizer_offsets_refuse_a_lossy_decode():
    class Lossy(_SlowTok):
        def decode(self, ids):
            return super().decode(ids).replace("'", "")

    with pytest.raises(SystemExit, match="incremental decode"):
        run.char_offsets(Lossy(), STIM)


# ------------------------------------------------------- 3. floors keep the registered cell


def test_floor_subsample_always_keeps_the_registered_position():
    pos = list(range(-120, 0))  # all_from_end over a 120-token render
    plain = floors.subsample(pos)
    assert len(plain) == floors.MAX_POS
    for reg in range(-120, 0):
        got = floors.subsample(pos, [reg])
        assert reg in got and len(got) == floors.MAX_POS
        assert got == [p for p in pos if p in set(got)]  # pos order, no duplicates
        assert floors.subsample(pos, [reg]) == got  # deterministic
    missed = next(p for p in pos if p not in plain)
    got = floors.subsample(pos, [missed])
    assert len(set(got) ^ set(plain)) == 2  # one even pick swapped for the registered cell
    assert floors.subsample(pos, [plain[3]]) == plain  # already picked: unchanged
    assert floors.subsample(pos[:10], [-5]) == pos[:10]  # under the cap: every position
    assert floors.subsample(pos, [999]) == plain  # not a position of this render: ignored
    assert set(floors.subsample(pos, [-7, -8, -7])) >= {-7, -8}


def test_floor_registered_pos_reads_the_frozen_cell():
    from wsbench.readplan import ReadSpec

    def spec(cell):
        return ReadSpec("arithmetic_intermediates", "a", "chat", {"kind": "all_from_end"}, [1],
                        extra={"frozen_cell": cell} if cell is not None else {})  # fmt: skip

    assert floors.registered_pos(spec({"layer": 40, "pos": -7})) == [-7]
    assert floors.registered_pos(spec({"layer": 40, "pos": None})) == []  # D8: none registered
    assert floors.registered_pos(spec(None)) == []


# ------------------------------------------------------- 4. the msdm gold keeps a form


def test_filter_forms_with_gold_drops_the_colliding_distractor_form():
    cands = {"bun cha": ["bun cha", "bun"], "bun bo": ["bun bo", "beef noodle"]}
    sym, _ = msdm.filter_forms(cands, visible="")
    assert sym["bun cha"] == ["bun cha"]  # symmetric: the gold loses "bun" (fires on "bun bo")
    forms, dropped = msdm.filter_forms(cands, visible="", gold="bun cha")
    assert forms["bun cha"] == ["bun cha", "bun"]
    assert forms["bun bo"] == ["beef noodle"]
    assert ("bun bo", msdm.GOLD_COLLIDES) in dropped["bun bo"]


def _plan(options, item_id="s1_test_cat"):
    it = {"id": item_id, "topic": "favorite noodle dish", "noun": "noodle dish"}
    g = {"pass": True, "stable": True, "gold": options[0], "n_eq": 10, "reveal": options[0],
         "samples": [options[0]] * 10}  # fmt: skip
    return {item_id: {"item": it, "origin": "original", "g0": g,
                      "rec": {"direct": {"greedy": options[0]}, "reveal": options[0]},
                      "options": list(options),
                      "option_sources": {o: ["x"] for o in options}}}  # fmt: skip


def _build(monkeypatch, options, unit):
    from wsbench.adapt.gate import Leg

    ok = Leg(greedy={"text": "", "ok": True}, samples=[], rate=1.0, decided=0, passed=True,
             question="q")  # fmt: skip
    rows = []
    monkeypatch.setattr(msdm, "_bank", lambda: ({}, []))
    monkeypatch.setattr(msdm, "_plan", lambda model: _plan(options))
    monkeypatch.setattr(msdm, "_load", lambda model, name: {"s1_test_cat": unit})
    monkeypatch.setattr(msdm, "_legs", lambda p, h: {"surface": ok, "reveal": ok,
                                                       "compliance": ok})  # fmt: skip
    monkeypatch.setattr(store, "record_gates", lambda m, f, r: rows.extend(r))
    monkeypatch.setattr(store, "update_report", lambda m, fn: None)
    msdm.build("m")
    return rows[0]


def _unit(options, cands, visible=""):
    forms, dropped = msdm.filter_forms(cands, visible)  # what stage=units stores (symmetric)
    return {"options": list(options), "forms": forms,
            "dropped": {o: [list(x) for x in v] for o, v in dropped.items()}}  # fmt: skip


def test_msdm_build_gold_keeps_its_form_and_an_emptied_distractor_is_dropped(monkeypatch):
    opts = ["bun cha", "bun", "mi quang"]
    # the gold's form "bun" collides with the distractor "bun" (its label, its only form)
    cands = {"bun cha": ["bun cha", "bun cha hanoi", "bun"], "bun": ["bun"],
             "mi quang": ["mi quang", "quang noodles"]}  # fmt: skip
    unit = _unit(opts, cands)
    assert "bun" not in unit["forms"]["bun cha"]  # the symmetric rule took the gold's "bun"
    row = _build(monkeypatch, opts, unit)
    assert row["gate"]["pass"], row["gate"]["reasons"]
    it = row["item"]
    assert "bun" in it["option_units"]["bun cha"] and it["units"][0]["match"][-1] == "bun"
    assert it["options"] == ["bun cha", "mi quang"]  # the emptied distractor left
    assert set(it["option_sources"]) == set(it["options"]) == set(it["option_units"])


def test_msdm_build_below_min_options_after_dropping_fails(monkeypatch):
    opts = ["bun cha", "bun"]
    unit = _unit(opts, {"bun cha": ["bun cha", "bun"], "bun": ["bun"]})
    row = _build(monkeypatch, opts, unit)
    assert not row["gate"]["pass"]
    assert row["gate"]["reasons"] == [f"options: 1 (need {msdm.MIN_OPTIONS})"]


def test_msdm_build_gold_with_no_creditable_form_fails_explicitly(monkeypatch):
    opts = ["bun cha", "mi quang"]
    # the gold's only form is in the visible prompt: nothing creditable survives
    unit = _unit(opts, {"bun cha": ["bun cha"], "mi quang": ["mi quang"]}, visible="bun cha")
    row = _build(monkeypatch, opts, unit)
    assert not row["gate"]["pass"]
    assert any("gold has no creditable form" in r for r in row["gate"]["reasons"])


# ------------------------------------------------------- 5. the freeze note names lost items


def test_freeze_note_names_every_item_that_lost_every_form(tmp_path, monkeypatch):
    from wsbench.adapt import native_langs as nl

    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    d = tmp_path / "qwen3.5-4b"
    _h, items = store.original_bank("typo_mt")
    keep = [copy.deepcopy(it) for it in items[:4]]
    # item 1 (a passing original) and item 3 (a FAILING original) lose every form: the note names
    # only items that could have shipped, i.e. passing originals
    lost = {store.item_id(keep[1]), store.item_id(keep[3])}
    (d / "gate").mkdir(parents=True)
    rows = [{"id": store.item_id(it), "origin": "original", "item": it, "selected": i != 3,
             "gate": {"pass": i != 3, "rate": 1.0 if i != 3 else 0.0, "legs": {"surface": {
                 "greedy": {"text": "x", "ok": i != 3}, "samples": [], "rate": 1.0}}}}
            for i, it in enumerate(keep)]  # fmt: skip
    (d / "gate" / "typo_mt.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    nl.record("qwen3.5-4b", ["en", "zh"], "plan 0054 R6 on the subject, thinking off")

    real = run.get_subject
    monkeypatch.setattr(
        run, "get_subject", lambda m: dataclasses.replace(real(m), tokenizer="other-tok")
    )

    def fake_restamp(model, family, its):  # item 1 loses every multi-token form
        gone = [store.item_id(it) for it in its if store.item_id(it) in lost]
        return [it for it in its if store.item_id(it) not in lost], [run.lost_forms_note(gone)]

    monkeypatch.setattr(run, "restamp_tokens", fake_restamp)
    run.freeze("qwen3.5-4b", ["typo_mt"])
    bank = json.loads((d / "typo_mt.json").read_text())
    assert {store.item_id(it) for it in bank["items"]} == {store.item_id(keep[i]) for i in (0, 2)}
    notes = json.loads((d / "report.json").read_text())["families"]["typo_mt"]["freeze_notes"]
    mine = [n for n in notes if n.startswith(run.RESTAMP_NOTE)]
    lost_id = store.item_id(keep[1])
    assert mine == [f"{run.RESTAMP_NOTE}1 items lost every multi-token form: {lost_id}"]


def test_stock_judge_passes_cells_all_for_a_bank_without_registered_cells(tmp_path, monkeypatch):
    """V4-Pro finalize: an adapted arithmetic bank with ``cell.pos`` None (no pre-registered
    cell) made the stock judge exit 2; ``judge_opts`` adds ``cells=all`` for it only."""
    import json as _json

    monkeypatch.setattr(store, "model_dir", lambda m, *a, **k: tmp_path / m)
    (tmp_path / "m").mkdir()
    bank = {"family": "arithmetic_intermediates",
            "items": [{"name": "a1", "cell": {"layer": 40, "pos": None}}]}  # fmt: skip
    (tmp_path / "m" / "arithmetic_intermediates.json").write_text(_json.dumps(bank))
    reg = {"family": "chain_intermediates", "items": [{"name": "c1", "cell": {"pos": -3}}]}
    (tmp_path / "m" / "chain_intermediates.json").write_text(_json.dumps(reg))
    assert floors.judge_opts("m", "arithmetic_intermediates") == "opts=aggregate=native,cells=all"
    assert floors.judge_opts("m", "chain_intermediates") == "opts=aggregate=native"
    assert floors.judge_opts("m", "association") == "opts=aggregate=native"  # no bank file
