"""v1.2.0: ``wrong_bridge`` was renamed ``wrong_intermediate`` (Camila 2026-11-03). The new key is
the family; the old one is a deprecated alias (CLI, readout file names, out dirs, digest stores,
ATI / floor keys); and the rename moves no hash: ``plan_sha``, the ATI ``bank_sha`` and the
lucky-guessing seeds are the pre-rename values, so readouts produced before the rename (sidecar
``plan_sha`` below, read off the campaign's ``readouts64/<arm>/wrong_bridge.jsonl.meta.json``)
still pass the plan check."""

import hashlib
import json
import random
from pathlib import Path

import pytest
from summary_fakes import FakeLLM
from test_wrong_intermediate import BEETHOVEN, answer, run_items, toy_file

from wsbench import readplan, reads, registry, runner
from wsbench.baselines import lucky_guessing
from wsbench.baselines import text_inversion as ti
from wsbench.cli import _family
from wsbench.evals.wrong_intermediate import prompts as wp

REPO = Path(__file__).resolve().parents[1]
# plan_sha / ATI bank_sha of the family on origin/main before the rename (30064aec); the plan_sha
# is the one every campaign sidecar of the family carries
PRE_PLAN_SHA = "0c247af522d39b73be377775cae115f9ab5f8619bf2a328be90e48b146b83f3f"
PRE_BANK_SHA_PREFIX = "23a8ac85bac7"
# plan 0066 §5.4: CUES_VERSION bump (Camila-approved); was
# "wb-mc-2026-10-31r+rv-2026-11-01h+wbaudit-v2+wbforms-v4+bank-v4" (the role cues only; the
# prompt bytes and both call keys are unchanged, tests/test_refill_wi_cues.py)
PRE_PROMPT_VERSION = "wb-mc-2026-10-31r+rv-2026-11-01h+wbaudit-v2+wbcues-v2+wbforms-v4+bank-v4"


def test_new_name_is_the_family():
    registry.load_all()
    assert "wrong_intermediate" in registry.FAMILIES and "wrong_bridge" not in registry.FAMILIES
    spec = registry.FAMILIES["wrong_intermediate"]
    assert spec.bank == Path("evals/wrong_intermediate/items_v4.json")
    assert (REPO / "evals/wrong_intermediate").is_dir() and not (
        REPO / "evals/wrong_bridge"
    ).exists()
    assert (REPO / "examples/readouts/wrong_intermediate.jsonl").is_file()
    for f in ("anti_text_inversion", "lucky_guessing", "prompt_only_summary"):
        d = json.loads((REPO / f"evals/baselines/{f}.json").read_text(encoding="utf-8"))
        assert "wrong_intermediate" in d and "wrong_bridge" not in d, f
    # the removed sibling keeps its own (historical) key
    assert "wrong_bridge_true" in registry.REMOVED_FAMILIES


def test_old_name_is_a_deprecated_alias(capsys):
    assert registry.LEGACY_FAMILY_NAMES["wrong_bridge"] == "wrong_intermediate"
    assert registry.canonical("wrong_bridge") == "wrong_intermediate"
    assert registry.legacy_names("wrong_intermediate") == ["wrong_bridge"]
    assert _family("wrong_bridge") == "wrong_intermediate"
    err = capsys.readouterr().err
    assert err.strip() == "note: family 'wrong_bridge' was renamed to 'wrong_intermediate'"
    assert _family("wrong_intermediate") == "wrong_intermediate"
    assert capsys.readouterr().err == ""
    assert registry.bank_path("wrong_bridge") == registry.bank_path("wrong_intermediate")


def test_plan_sha_unchanged_by_the_rename():
    assert reads.plan_sha("wrong_intermediate") == PRE_PLAN_SHA
    assert reads.plan_sha("wrong_bridge") == PRE_PLAN_SHA
    rows = [s.row() for s in readplan.plan("wrong_bridge")]
    assert {r["family"] for r in rows} == {"wrong_intermediate"}
    # it is the hash alias that keeps it: the same rows hashed under the new key would differ
    assert registry.hash_name("wrong_intermediate") == "wrong_bridge"
    raw = hashlib.sha256()
    for r in rows:
        d = reads._clean_row(r)
        d["family"] = "wrong_intermediate"
        raw.update(json.dumps(d, sort_keys=True, ensure_ascii=False).encode() + b"\n")
    assert raw.hexdigest() != PRE_PLAN_SHA
    # every other family hashes its own key
    assert registry.hash_name("association") == "association"


# sha256 over every upper-case string constant of the judge's prompts module (system / user /
# audit / summary prompts, task note, instrument stamps), computed on the pre-rename module;
# plan 0066 §5.4: CUES_VERSION bump (Camila-approved): only PROMPT_VERSION moved; was
# "a7292ad975d25e80747110b467276e40815e8ce0b60519d3618ec029ab801e5e"
PRE_PROMPTS_SHA = "6291963fcde768c97f830296beacdf5f6aae34794db013aa83671b0efd2d6a7b"
PROMPT_CONSTANTS = (
    "RIVAL_VERSION", "AUDIT_VERSION", "MC_CALL_VERSION", "FORMS_VERSION", "BANK_TAG",
    "PROMPT_VERSION", "WB_MC_SEED", "RIVAL_RULE", "SYSTEM", "AUDIT_SYSTEM", "AUDIT_USER", "CANNOT",
    "USER", "BLOCK", "KIND_NOTE_PROSE", "KIND_NOTE_TOKENS", "USER_SUMMARY", "TASK_NOTE",
)  # fmt: skip


def test_instrument_and_prompt_bytes_unchanged_by_the_rename():
    assert wp.PROMPT_VERSION == PRE_PROMPT_VERSION
    blob = "\x00".join(f"{k}={getattr(wp, k)}" for k in sorted(PROMPT_CONSTANTS))
    assert hashlib.sha256(blob.encode()).hexdigest() == PRE_PROMPTS_SHA


def test_ati_bank_sha_unchanged_by_the_rename():
    entry = ti.subset_entry("wrong_intermediate")  # a bank_sha mismatch would exit (re-gate)
    assert entry["bank_sha"].startswith(PRE_BANK_SHA_PREFIX)
    assert ti.bank_fingerprint("wrong_intermediate") == entry["bank_sha"]
    assert ti.subset_entry("wrong_bridge") == entry


def test_lucky_guessing_seeds_unchanged_by_the_rename():
    def pre(seed, *key):  # the pre-rename _rng, keyed by the old family name
        h = hashlib.sha256(":".join(str(k) for k in (seed, *key)).encode()).digest()[:8]
        return random.Random(int.from_bytes(h, "big"))

    for key in (("x", "examples"), ("x", 0, 3)):
        new = lucky_guessing._rng(7, "wrong_intermediate", *key).random()
        assert new == pre(7, "wrong_bridge", *key).random()
    assert lucky_guessing._rng(7, "poetry", "x").random() == pre(7, "poetry", "x").random()


def test_pre_rename_readout_file_passes_the_plan_check(tmp_path, monkeypatch):
    FakeLLM.install(monkeypatch, judge=answer(7, ""))
    path = toy_file(tmp_path, plan_sha=PRE_PLAN_SHA)
    legacy = path.with_name("wrong_bridge.jsonl")
    path.rename(legacy)
    path.with_name(path.name + ".meta.json").rename(legacy.with_name(legacy.name + ".meta.json"))
    r = run_items(tmp_path, legacy, [BEETHOVEN])
    assert r.family == "wrong_intermediate" and r.config["reads_checked"] == "sidecar"
    # a drifted plan still fails: the alias does not switch the check off
    drift = tmp_path / "drift"
    drift.mkdir()
    with pytest.raises(SystemExit):
        run_items(drift, toy_file(drift, plan_sha="0" * 64), [BEETHOVEN])


def test_legacy_readout_file_and_out_dir_are_reused(tmp_path):
    root = tmp_path / "readouts"
    root.mkdir()
    (root / "wrong_bridge.jsonl").write_text("", encoding="utf-8")
    assert runner.readouts_path(root, "wrong_intermediate") == root / "wrong_bridge.jsonl"
    out = tmp_path / "judged"
    assert registry.family_dir(out, "wrong_intermediate") == out / "wrong_intermediate"
    (out / "wrong_bridge").mkdir(parents=True)
    assert registry.family_dir(out, "wrong_intermediate") == out / "wrong_bridge"
    (out / "wrong_intermediate").mkdir()  # the new dir wins once it exists
    assert registry.family_dir(out, "wrong_intermediate") == out / "wrong_intermediate"


def test_adapted_bank_under_the_old_name(tmp_path, monkeypatch):
    bank = tmp_path / "wrong_bridge.json"
    bank.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert registry.bank_path("wrong_intermediate") == bank
    monkeypatch.delenv(registry.BANK_ROOT_ENV)
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "WRONG_BRIDGE", str(bank))
    assert registry.bank_path("wrong_intermediate") == bank


def test_gate_seeds_and_old_gate_rows_keep_the_old_key(tmp_path):
    from wsbench import gate_sampling

    def pre(blob):
        return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:4], "big")

    assert ti.qwen_seed("wrong_intermediate", "x") == pre("wrong_bridge|x")
    assert gate_sampling.seed("wrong_intermediate", "x", 1) == pre("wrong_bridge|x|1")
    assert ti.qwen_seed("poetry", "x") == pre("poetry|x")
    row = {"family": "wrong_bridge", "id": "x"}
    (tmp_path / "prompts.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert [r["family"] for r in ti._prompts(tmp_path, {"wrong_intermediate"})] == [
        "wrong_intermediate"
    ]


def test_judge_default_out_dir_reuses_the_old_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old = Path("outputs") / "arm" / "wrong_bridge"
    old.mkdir(parents=True)
    assert registry.family_dir(Path("outputs") / "arm", "wrong_intermediate") == old
