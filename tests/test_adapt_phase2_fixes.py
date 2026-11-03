"""Plan 0060 phase-2 fixes (fakes only: no GPU, Modal or API): r4b ``--bank`` in ``assemble``,
idempotent ``adapt mc`` builds, ``fill`` building MC options before the gate, moral incomplete
option lists, and the subject ``max_model_len`` default."""

import copy
import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from wsbench.adapt import mcstage, store
from wsbench.banks import label_of

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
EVALS = REPO / "evals"
sys.path.insert(0, str(SCRIPTS))


def _items(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["items"] if isinstance(raw, dict) else raw


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / model)
    return tmp_path


# ---------------------------------------------------------------- r4b_mc_refine --bank


def test_r4b_assemble_reads_the_bank_not_the_registered_one(tmp_path):
    """Adapted-only ids are absent from the registered bank: ``assemble`` must build its option
    lists over ``--bank`` (it raised KeyError on every adapted-only id)."""
    r = importlib.import_module("r4b_mc_refine")
    f = "basic_readout_mt"
    its = copy.deepcopy(_items(EVALS / f / "items_v4.json")[:2])
    for i, it in enumerate(its):
        it["name"] = f"brh-au-x{i}"
    bank_path = tmp_path / "bank.json"
    bank_path.write_text(json.dumps({"family": f, "items": its}), encoding="utf-8")
    ids = [label_of(it["name"]) for it in its]
    bank = {iid: {**it, "id": iid} for iid, it in zip(ids, its, strict=True)}
    lists = {
        (iid, "readout"): {
            "gold": it["mc"]["readout"]["gold"],
            "topic": "a topic",
            "v3": list(it["mc"]["readout"]["distractors"]),
        }
        for iid, it in zip(ids, its, strict=True)
    }
    key = "WSB_BANK_FILE_BASIC_READOUT_MT"
    before = os.environ.get(key)
    r.BANK, r.OUT = bank_path, tmp_path / "refine.json"
    try:
        got = r.assemble(f, lists, {}, bank)
    finally:
        r.BANK, r.OUT = None, None
    assert os.environ.get(key) == before  # the override is scoped to the call
    assert [it.id for it in got] == ids
    for it, src in zip(got, its, strict=True):
        assert it.meta["topics"] == ["a topic"]
        gold = src["mc"]["readout"]["gold"]
        assert it.lists[0][it.golds[0] - 1] == gold
        assert set(it.lists[0]) == {gold, *src["mc"]["readout"]["distractors"]}


# ---------------------------------------------------------------- adapt mc: idempotent builds


def _brmt_cand(name: str) -> dict:
    it = copy.deepcopy(_items(EVALS / "basic_readout_mt" / "items_v4.json")[0])
    it["name"] = name
    it["adapt"] = {"origin": "authored", "tier": "t1"}
    return it


def _brmt_runner(monkeypatch, seen: list):
    """The real r4_mc_distractors main (its LLM ``run`` faked) and the real r4b ``load_lists``
    on its pools: a pools file carrying a previous build's ids raises KeyError there."""
    gen = importlib.import_module("r4_mc_distractors")
    r = importlib.import_module("r4b_mc_refine")

    def fake_gen_run(family, only=None, note="", bank=None):
        return {
            label_of(it["name"]): {"readout": {
                "topic": "dynasty", "kind": "dynasty", "gold": it["mc"]["readout"]["gold"],
                "distractors": list(it["mc"]["readout"]["distractors"]), "spares": [],
            }}
            for it in _items(bank)
        }  # fmt: skip

    monkeypatch.setattr(gen, "run", fake_gen_run)

    def runner(script, argv):
        seen.append((script, argv))
        arg = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
        if script == "r4_mc_distractors":
            assert gen.main(argv) == 0
        elif script == "r4b_mc_refine" and "--pass2" not in argv and "--resume" not in argv:
            pools = json.loads(Path(arg["--pools"]).read_text(encoding="utf-8"))
            r.BANK, r.OUT = Path(arg["--bank"]), Path(arg["--out"])
            try:
                r.load_lists(argv[0], pools)  # KeyError on a stale pool id
            finally:
                r.BANK, r.OUT = None, None
            Path(arg["--out"]).write_text(json.dumps({"pass": 2, "items": {}}), "utf-8")
        elif script == "build_r4b_mc_banks":
            Path(arg["--out"]).write_text(
                json.dumps({"items": _items(Path(arg["--bank"]))}), encoding="utf-8"
            )

    return runner


def test_two_consecutive_mc_builds(mdir, monkeypatch):
    """Build A, gate A, author B, build B: the second build must not see A's pools."""
    f = "basic_readout_mt"
    seen: list = []
    monkeypatch.setattr(mcstage, "run_builder", _brmt_runner(monkeypatch, seen))
    a = _brmt_cand("brh-au-a")
    store.add_candidates("demo", f, [a])
    assert mcstage.build("demo", f) == {"built": 1, "dropped": 0}
    a_built = store.pending("demo", f)[0]
    store.record_gates("demo", f, [{"id": store.item_id(a_built), "origin": "authored",
                                    "item": a_built, "gate": {"pass": True}}])  # fmt: skip
    store.add_candidates("demo", f, [_brmt_cand("brh-au-b")])
    assert mcstage.build("demo", f) == {"built": 1, "dropped": 0}
    works = {Path(a).parent for s, argv in seen if s == "r4_mc_distractors"
             for a in argv if a.endswith("r4_pools.json")}  # fmt: skip
    assert len(works) == 2
    assert all(w.parent == mdir / "demo" / "mc" / f for w in works)
    cands = {c["name"]: c for c in store._read_jsonl(store.cand_path("demo", f))}
    assert cands["brh-au-b"]["adapt"]["mc_build"]["work"].startswith("build-")


def test_mc_build_skips_already_built_pending_rows(mdir, monkeypatch):
    """A rerun after the gate crashed (built rows still pending) rebuilds nothing: no second
    Opus spend, and basic_readout_mt keeps the first build's hidden_rivals."""
    f = "basic_readout_mt"
    seen: list = []
    monkeypatch.setattr(mcstage, "run_builder", _brmt_runner(monkeypatch, seen))
    store.add_candidates("demo", f, [_brmt_cand("brh-au-a")])
    assert mcstage.build("demo", f) == {"built": 1, "dropped": 0}
    first = store.pending("demo", f)[0]
    n = len(seen)
    assert mcstage._todo("demo", f) == []
    mcstage.build("demo", f)
    assert len(seen) == n  # no builder ran
    assert store.pending("demo", f)[0] == first


def test_mc_build_work_dir_is_keyed_by_the_pending_set(mdir):
    a, b = _brmt_cand("brh-au-a"), _brmt_cand("brh-au-b")
    w1 = mcstage.work_dir("demo", "basic_readout_mt", [a, b])
    assert w1 == mcstage.work_dir("demo", "basic_readout_mt", [b, a])  # a rerun resumes
    assert w1 != mcstage.work_dir("demo", "basic_readout_mt", [b])


# ---------------------------------------------------------------- fill: MC build before gate


@pytest.mark.parametrize(
    ("family", "want"),
    [
        ("basic_readout_mt", ["author", "mc", "gate"]),
        ("association", ["author", "mc", "gate"]),
        ("basic_readout", ["author", "mc", "gate", "subject"]),
        ("typo_mt", ["author", "gate"]),
    ],
)
def test_fill_builds_mc_between_author_and_gate(mdir, monkeypatch, family, want):
    from wsbench.adapt import author, rebuild
    from wsbench.adapt import run as arun

    calls = []
    monkeypatch.setattr(author, "author", lambda m, f, *a, **k: calls.append("author"))
    monkeypatch.setattr(
        mcstage, "build", lambda m, f: calls.append("mc") or {"built": 0, "dropped": 0}
    )
    monkeypatch.setattr(arun, "lint_and_gate", lambda *a, **k: calls.append("gate") or ([], {}))
    monkeypatch.setattr(rebuild, "subject_fields", lambda m, ids=None: calls.append("subject"))
    arun.fill("qwen3.5-4b", family, llm=None, max_waves=1, runner=object())
    assert calls == want


# ---------------------------------------------------------------- moral: incomplete option lists

MORAL_MODEL = "qwen3.5-4b"


def _md():
    spec = importlib.util.spec_from_file_location(
        "moral_distractors_p2", SCRIPTS / "moral_distractors.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _moral_entry(reg: dict) -> dict:
    gold = f"the gold reason of {reg['id']}"
    v1 = {k: reg[k] for k in ("id", "question", "stimulus")} | {"reason_class": "committed"}
    checks = {"leg_s": True, "token": True, "precise": True, "aligned": True,
              "reason_side_ok": True, "has_reason": True, "class_kept": True}  # fmt: skip
    v2 = {"reason_class": "committed", "look_for_reasons": [gold],
          "reasons": [{"text": gold, "supports": "no", "frequency": 9},
                      {"text": "an opposite reason", "supports": "yes", "frequency": 1}],
          "gold_reasons": [gold], "gold_terms": ["gold"], "must_surface_both": False,
          "answer_split": {"yes": 1, "no": 9, "other": 0}, "commit_answer": "No",
          "commit_direction": "no", "commit_precise": True, "gate_committed_token": True,
          "gate_aligned": True, "gate_reason_side_ok": True, "gate_pass": True,
          "gate_checks": checks}  # fmt: skip
    rk = {"model": MORAL_MODEL, "side_draws": {"yes": 1, "no": 9, "other": 0},
          "side_greedy": "No", "side_temperature": 0.7, "reason_temperature": 0.7,
          "reason_draws": [{"answer": "No", "draws": [gold] * 3}], "explain_split": {},
          "v1_look_for": [], "v1_gate_pass": True, "changed": False}  # fmt: skip
    return {"v1": v1, "v2": v2, "rekey": rk}


def test_moral_incomplete_list_drops_only_its_item(mdir, monkeypatch):
    """One list ``select`` never completed among complete ones: restyle and every later pass
    skip it (restyle raised TypeError on ``chosen=None``), freeze drops only its item with
    ``options_incomplete``, and adopt tallies fail:options_incomplete for it alone."""
    from wsbench.adapt import moral

    md = _md()
    monkeypatch.setattr(md.am, "claude_json", lambda tasks, schema, path, **k: {})
    _h, v3 = store.original_bank("moral_rationale")
    regs = v3[:3]
    d = mdir / "rk"
    work = d / "options"
    work.mkdir(parents=True)
    entries = [_moral_entry(r) for r in regs]
    (d / "rekey.json").write_text(json.dumps(entries), encoding="utf-8")
    state = {}
    for i, r in enumerate(regs):
        chosen = [{"text": f"distractor {k} of item {i}", "kind": kind, "source": "opus"}
                  for k, kind in enumerate(("opp", "opp", "same", "same"))]  # fmt: skip
        state[f"{r['id']}|committed"] = {
            "cands": {}, "rounds": 3, "chosen": None if i == 1 else chosen,
        }  # fmt: skip
    (work / "lists.json").write_text(json.dumps(state), encoding="utf-8")
    bank = d / "items_v3.json"
    for step in ("restyle", "harden", "lenmatch", "coregister", "gate"):
        assert md.main([step, "--rekey", str(d), "--out", str(work)]) == 0, step
    after = json.loads((work / "lists.json").read_text(encoding="utf-8"))
    bad = after[f"{regs[1]['id']}|committed"]
    assert bad["chosen"] is None and not ({"restyled", "hardened", "lenmatched"} & set(bad))
    assert md._final(bad) is None
    md.main(["freeze", "--rekey", str(d), "--out", str(work), "--bank", str(bank)])
    kept = json.loads(bank.read_text(encoding="utf-8"))
    assert [it["id"] for it in kept] == [regs[0]["id"], regs[2]["id"]]
    report = json.loads((d / "items_v3_report.json").read_text(encoding="utf-8"))
    rec = report["items"][regs[1]["id"]]
    assert rec["drop"] == "options_incomplete" and rec["incomplete"] == ["committed"]
    assert report["counts"]["drop_options_incomplete"] == 1
    tally = moral.adopt(MORAL_MODEL, str(d))
    assert tally["pass"] == 2 and tally["fail:options_incomplete"] == 1
    rows = store.gated(MORAL_MODEL, "moral_rationale")
    assert rows[regs[1]["id"]]["gate"]["drop"] == "options_incomplete"
    assert not rows[regs[1]["id"]]["gate"]["pass"]
    assert all(rows[r["id"]]["gate"]["pass"] for r in (regs[0], regs[2]))


# ---------------------------------------------------------------- subject max_model_len

TOKENIZER_SLACK = 1.5  # another tokenizer may need up to 1.5x Qwen's tokens for the same text
CHARS_PER_TOKEN = 3  # a conservative static bound for banks without a stored token count


def _longest_subject_prompts() -> dict[str, int]:
    """Token budget (prompt + max_tokens) of the longest prompt each long-prompt adapt step
    sends to the subject: carry's jailbreak re-screen, agentic rollouts, MCDM carry."""
    from wsbench.adapt import agentic, carry
    from wsbench.registry import frozen_bank_path

    def items(fam: str) -> list[dict]:
        raw = json.loads(frozen_bank_path(fam).read_text(encoding="utf-8"))
        return raw["items"] if isinstance(raw, dict) else raw

    jb = max(int(it["read"]["n_tokens"]) for it in items("jailbreak_recognition"))
    am = max(len(it.get("system") or "") + len(it["text"]) for it in items("agentic_misalignment"))
    mcdm = max(len(json.dumps(it, ensure_ascii=False))
               for it in items("multi_concept_directed_modulation"))  # fmt: skip
    return {
        "jailbreak_recognition": int(jb * TOKENIZER_SLACK) + carry.SCREEN_MAX_TOKENS,
        "agentic_misalignment": am // CHARS_PER_TOKEN + agentic.MAX_TOKENS,
        "multi_concept_directed_modulation": mcdm // CHARS_PER_TOKEN + 64,
    }


def test_subject_max_model_len_fits_the_longest_carry_prompt():
    from wsbench.adapt.subjects import SUBJECTS, Subject

    need = _longest_subject_prompts()
    assert need["jailbreak_recognition"] > 4096  # the phase-2 failure (4,259-token prompt)
    default = Subject.__dataclass_fields__["max_model_len"].default
    assert default >= max(need.values()), need
    for key, s in SUBJECTS.items():  # an explicit override never goes below the longest prompt
        assert s.max_model_len >= max(need.values()), (key, s.max_model_len, need)
