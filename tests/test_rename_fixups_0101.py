"""Plan 0101 (review of commit 2): pair behaviour that needed a fix-up, on the real pair
``multihop`` (multi-token, the bare key since 2026-11-20) / ``multihop_st`` (single-token, which
held the key before), and the guards the rename added."""

import importlib.util
import json
from types import SimpleNamespace

import pytest
import test_ati_panel as panel
import test_audit_run as audit
import test_text_inversion as flat

from wsbench import fast, reads, registry, runner
from wsbench.adapt import store
from wsbench.baselines import text_inversion as ti
from wsbench.registry import RenamedKey

REPO = registry.REPO_ROOT
LIVE, OTHER = "multihop", "multihop_st"
LIVE_ID, OTHER_ID = "mh2-henry-james-pragmatism", "atomic-26-symbol"
LIVE_HEADER, OTHER_HEADER = "multihop-hard", "multihop"
_spec = importlib.util.spec_from_file_location(
    "_fixups_lens", REPO / "scripts/lens_readouts_modal.py"
)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)


@pytest.fixture
def pair(real_families):
    registry._family_ids.cache_clear()
    yield registry.REUSED_FAMILY_KEYS[LIVE]
    registry._family_ids.cache_clear()


def _bank(path, header=None, ids=()):
    doc = {"items": [{"id": i} for i in ids]}
    if header is not None:
        doc["family"] = header
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------- S1


def test_uncanonicalized_readers_still_translate_the_pre_0101_keys(pair):
    rows = [
        {"family": "typo_mt", "id": "x"},  # a pre-0101 key no pair shares: one family
        {"family": "multihop_mt", "id": "x"},
        {"family": "multihop_mt_v2", "id": "x"},
        {"family": "wrong_bridge", "id": "x"},  # any other former key: as stored
        {"family": LIVE, "id": OTHER_ID},  # a bare key: by the row's own id
        {"family": "moral_rationale", "id": "x"},
    ]
    got = [r["family"] for r in registry.attribute_rows(rows, canonicalize=False)]
    assert got == ["typo", "multihop", "multihop", "wrong_bridge", OTHER, "moral_rationale"]


def test_latest_answers_serves_a_pre_0101_key_under_the_current_one(tmp_path):
    path = tmp_path / "draw0.jsonl"
    rows = [
        {"family": "typo_mt", "id": "a", "error": "", "answer": "x"},
        {"family": "multihop", "id": OTHER_ID, "error": "", "answer": "y"},  # single-token then
        {"family": "multihop_mt", "id": LIVE_ID, "error": "", "answer": "z"},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert list(ti.latest_answers(path)) == [("typo", "a"), (OTHER, OTHER_ID), (LIVE, LIVE_ID)]


# ---------------------------------------------------------------- S2


def test_a_bare_pin_of_the_live_family_does_not_disable_its_partner(pair, tmp_path, monkeypatch):
    mine = _bank(tmp_path / "live.json", LIVE_HEADER)
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(mine))
    assert registry.bank_pin(LIVE) == ("WSB_BANK_FILE_MULTIHOP", str(mine))
    assert registry.bank_pin(OTHER) is None  # the partner's legitimate pin is not this one's
    assert registry.bank_path(LIVE) == mine
    assert registry.bank_path(OTHER) == registry.frozen_bank_path(OTHER)
    # the three consumers: none treats the family as pinned
    assert runner.adapted_bank_stamp(OTHER, "x+bank-v2") == "x+bank-v2"
    monkeypatch.setattr(fast, "subset", lambda v=None: {OTHER: {"bank_sha": fast.bank_sha(OTHER)}})
    assert fast.entry(OTHER)["bank_sha"] == fast.bank_sha(OTHER)
    step = {"from": "a", "to": "b", "dropped": ["x"]}
    monkeypatch.setattr(reads, "_registered_header", lambda f: {reads.LINEAGE_KEY: [step]})
    assert reads.lineage_drops(OTHER, "a", "b") == ["x"]  # not None: the family is not pinned
    assert reads.lineage_drops(LIVE, "a", "b") is None  # the pinned family fails closed
    # a bare variable naming the partner's own bank, or a header-less one, still refuses
    theirs = _bank(tmp_path / "other.json", OTHER_HEADER)
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP", str(theirs))
    assert registry.bank_pin(OTHER) == ("WSB_BANK_FILE_MULTIHOP", str(theirs))
    with pytest.raises(RenamedKey, match="WSB_BANK_FILE_MULTIHOP_ST"):
        registry.bank_path(OTHER)
    with pytest.raises(SystemExit):
        fast.entry(OTHER)


def test_a_missing_pinned_file_names_the_variable_that_is_set(monkeypatch):
    monkeypatch.setenv("WSB_BANK_FILE_MULTIHOP_MT_V2", "no/such/bank.json")
    with pytest.raises(SystemExit, match=r"WSB_BANK_FILE_MULTIHOP_MT_V2=no/such/bank\.json"):
        registry.bank_path("multihop_mt")


# ---------------------------------------------------------------- S3


def test_a_headerless_bare_key_bank_is_decided_by_its_ids(pair, tmp_path):
    a = tmp_path / "a"
    a.mkdir()
    old = _bank(a / f"{LIVE}.json", ids=[OTHER_ID])  # the single-token family's, no header
    assert registry.root_bank(a, OTHER) == old
    assert registry.root_bank(a, LIVE) is None
    b = tmp_path / "b"
    b.mkdir()
    new = _bank(b / f"{LIVE}.json", ids=[LIVE_ID])
    assert registry.root_bank(b, LIVE) == new and registry.root_bank(b, OTHER) is None
    c = tmp_path / "c"
    c.mkdir()
    _bank(c / f"{LIVE}.json", ids=["in-neither-bank"])
    for family in (LIVE, OTHER):
        with pytest.raises(RenamedKey, match="has no header"):
            registry.root_bank(c, family)
    _bank(c / f"{LIVE}.json", ids=[LIVE_ID, OTHER_ID])
    with pytest.raises(RenamedKey):
        registry.root_bank(c, LIVE)


# ---------------------------------------------------------------- S4: guards new in commit 2


def test_draw_verdicts_expect(tmp_path, monkeypatch):
    p = tmp_path / "results.json"
    doc = {"family": "fam", "config": {}, "numbers": {"metric": "pass_rate", "value": 1.0},
           "rows": [{"id": "a", "pass": True}]}  # fmt: skip
    p.write_text(json.dumps(doc))
    assert ti.draw_verdicts(p) == ti.draw_verdicts(p, expect="fam") == {"a": True}
    with pytest.raises(RenamedKey, match="holds results of 'fam', not 'other'"):
        ti.draw_verdicts(p, expect="other")
    doc["family"] = "wrong_bridge"  # a former key reads as the current family
    p.write_text(json.dumps(doc))
    assert ti.draw_verdicts(p, expect="wrong_intermediate") == {"a": True}
    # a result under the 2026-11-04 reused key with a non-live stamp is the removed family's
    doc["family"], doc["config"] = "multihop_mt", {"prompt_version": "mc-2026-09-16"}
    p.write_text(json.dumps(doc))
    with pytest.raises(RenamedKey, match="multihop_mt_regex"):
        ti.draw_verdicts(p, expect="multihop_mt")


def test_the_panel_gate_stops_when_judged_results_give_no_verdict(tmp_path, fams):
    out = tmp_path / "o"
    for a in ("qwen", "opus", *ti.FRONTIER_OTHERS):
        panel._write(out, a, "fam", {i: [False, False, False] for i in "abcde"})
    # the answers were stored under another family key: no (fam, id) answer is usable
    for f in (out / "answers").rglob("*.jsonl"):
        f.write_text(f.read_text().replace('"family": "fam"', '"family": "fam_old_key"'))
    with pytest.raises(SystemExit, match="none of its 5 items has a verdict"):
        ti.gate(out, dst=tmp_path / "ati.json")
    assert not (tmp_path / "ati.json").exists()


fams = panel.fams
two_families = flat.two_families


def test_the_flat_gate_stops_when_judged_results_give_no_verdict(tmp_path, two_families):
    out = tmp_path / "o"
    for d in range(3):
        flat._answers(out, d, [("fam_old_key", i, "ok") for i in "abcde"])
        rows = [{"id": i, "pass": False} for i in "abcde"]
        flat._results(out / "judged" / f"draw{d}" / "fam", "fam", rows, 0.0)
    with pytest.raises(SystemExit, match="none of its 5 items has a verdict"):
        ti.gate(out, dst=tmp_path / "ati.json")


def _store_row(item_id):
    return json.dumps({"row_sha": f"sha-{item_id}", "row": {"id": item_id, "layer": 8, "pos": 0}})


def test_lens_store_reads_by_content_and_never_appends_to_the_partner(pair, tmp_path):
    arm = tmp_path / "subject" / "arm"
    arm.mkdir(parents=True)
    old = arm / f"{LIVE}.jsonl"  # written before the rename: the other family's cells
    old.write_text(_store_row(OTHER_ID) + "\n")
    assert lr.store_files(tmp_path, "subject", "arm", OTHER) == [old]
    assert lr.store_files(tmp_path, "subject", "arm", LIVE) == []
    assert lr.store_path(tmp_path, "subject", "arm", OTHER) == arm / f"{OTHER}.jsonl"
    with pytest.raises(SystemExit, match="is the store of 'multihop_st'"):
        lr.check_store_writable(lr.store_path(tmp_path, "subject", "arm", LIVE), LIVE)
    lr.check_store_writable(lr.store_path(tmp_path, "subject", "arm", OTHER), OTHER)  # absent
    old.write_text(_store_row(LIVE_ID) + "\n" + _store_row(OTHER_ID) + "\n")
    with pytest.raises(RenamedKey):
        lr.store_files(tmp_path, "subject", "arm", LIVE)  # both families' ids
    old.write_text(_store_row("in-neither-bank") + "\n")
    with pytest.raises(RenamedKey, match="neither family"):
        lr.store_files(tmp_path, "subject", "arm", OTHER)
    old.write_text("")
    lr.check_store_writable(old, LIVE)  # empty: writable
    # a family outside any pair: its own file, no content check
    assert lr.store_files(tmp_path, "subject", "arm", "moral_rationale") == []


def test_row_sha_and_the_job_seed_hash_the_pre_rename_key():
    import hashlib

    def pre_0101(row):  # the script's row hash before plan 0101: the raw row
        return hashlib.sha256(
            json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    args = SimpleNamespace(subject="s", batch=0)
    subj = SimpleNamespace(hf_id="h", revision="r")
    for old, new in (
        ("multihop_mt", "multihop"),
        ("multihop", "multihop_st"),
        ("poetry", "poetry"),
    ):
        row = {"id": "a", "family": old, "layers": [8], "positions": {"kind": "final_token"}}
        sha = pre_0101(row)
        assert lr.row_sha({**row, "family": new}) == sha, new  # a stored cell is still found
        want = int(hashlib.sha256(f"arm|{old}|{sha}".encode()).hexdigest()[:8], 16)
        pack = [{"row_sha": sha, "row": {**row, "family": new}, "family": new}]
        got = lr._job(args, subj, "arm", {"kind": "olens", "path": "p"}, pack, 0)["seed"]
        assert got == want, new


def test_the_producer_resolves_a_pre_0101_vector_path():
    from wsbench.produce.producer import Producer

    p = Producer.__new__(Producer)
    p._vectors = {}
    rel = "evals/introspection/vectors/concept_vectors_L12.npy"  # as the bank writes it
    assert p._vector(rel, 0).shape == p._vector(str(registry.repo_path(rel)), 0).shape
    assert registry.repo_path(rel) == registry.family_root("introspection") / "vectors" / (
        "concept_vectors_L12.npy"
    )


def test_stored_keys_of_the_2026_11_04_rename():
    # T1: `multihop_mt_v2` only ever named the MC family, whatever the stamp
    assert registry.stored_family("multihop_mt_v2", "mc-2026-09-16") == "multihop"
    assert registry.stored_family("multihop_mt_v2", None) == "multihop"
    assert registry.stored_family("multihop_mt", "mc-2026-09-16") == "multihop_mt_regex"


def test_audit_run_audits_a_reused_key_result_as_the_family_that_wrote_it(tmp_path):
    # a `multihop_mt` result with the removed regex family's stamp is that family's (as
    # `read_results` reads it, plan 0101 §5.1): it is not audited against the live family's
    # instrument, and a live-stamped one still is
    old = audit._write(tmp_path / "a", "multihop_mt", prompt_version="mc-2026-09-16")
    r = audit.ar.audit_family(old)
    assert r["family"] == "multihop_mt_regex"
    assert not any("!= registry" in p for p in r["problems"])
    live = audit._write(tmp_path / "b", "multihop_mt")
    assert audit.ar.audit_family(live)["family"] == "multihop"
    stale = audit._write(tmp_path / "c", "moral_rationale", prompt_version="old")
    assert any("!= registry" in p for p in audit.ar.audit_family(stale)["problems"])


# ---------------------------------------------------------------- nit: adapt work files


def test_adapt_work_files_under_a_bare_key_are_content_checked(pair, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda m, root=None: tmp_path / "adapted" / m)
    gate = tmp_path / "adapted" / "m" / "gate"
    gate.mkdir(parents=True)
    old = gate / f"{LIVE}.jsonl"
    old.write_text(json.dumps({"id": OTHER_ID, "gate": {"pass": True}}) + "\n")
    assert store.gate_path("m", OTHER) == old  # the other family's log, found under the bare key
    with pytest.raises(RenamedKey, match="holds rows of 'multihop_st'"):
        store.gate_path("m", LIVE)  # never the file a writer of the live family appends to
    assert store.gated("m", OTHER) and not store.gated("m", "moral_rationale")
    # candidate ids are in no bank: an unidentified file is a family's only under its OWN key
    old.write_text(json.dumps({"id": "multihop-au-t1-w1c0-new"}) + "\n")
    assert store.gate_path("m", LIVE) == old
    assert store.gate_path("m", OTHER) == gate / f"{OTHER}.jsonl"
    # ... unless the set's own bank ships them
    _bank(tmp_path / "adapted" / "m" / f"{OTHER}.json", OTHER_HEADER, ["multihop-au-t1-w1c0-new"])
    assert store.gate_path("m", OTHER) == old
    with pytest.raises(RenamedKey):
        store.gate_path("m", LIVE)


def test_the_viewer_index_and_the_skill_scripts_do_not_walk_evals_one_level():
    text = (REPO / "viewer_app/index.py").read_text(encoding="utf-8")
    assert '(WSB / "evals").iterdir()' not in text and "family_root(f) for f in _layout()" in text
    for name in ("modal_gate.py", "modal_script.py"):
        src = (REPO / ".claude/skills/wsb-new-questions/scripts" / name).read_text("utf-8")
        assert 'ignore=["**/jlens_concept_pr/gen-*"]' in src
