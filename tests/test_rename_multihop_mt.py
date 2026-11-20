"""2026-11-04: ``multihop_mt_v2`` was renamed ``multihop_mt``; plan 0101 (2026-11-20) then gave
the family the plain key ``multihop``. The current key is the family; both earlier ones are former
keys (CLI, readout file names, out dirs, digest stores, stored results, adapted sets); and neither
rename moved a hash: ``plan_sha``, the ATI ``bank_sha``, the lucky-guessing and gate seeds, the
stamps, the call keys and the prompt bytes are the values from before 2026-11-04.

``multihop_mt`` was also the key of the regex-scored family removed on 2026-10-30, now listed as
``multihop_mt_regex``. So a file or directory under ``multihop_mt_v2`` wins over one under
``multihop_mt`` (``registry.lookup_names``), and a stored ``multihop_mt`` result is the removed
family's unless its stamp is the live family's (``registry.stored_family``)."""

import hashlib
import json
import random
from pathlib import Path

from wsbench import gate_sampling, readplan, reads, registry, runner
from wsbench.adapt import store
from wsbench.baselines import lucky_guessing
from wsbench.baselines import text_inversion as ti
from wsbench.cli import _family
from wsbench.evals.basic.multihop import prompts as P  # noqa: N812
from wsbench.multitoken import family as fam
from wsbench.results import FamilyResult, macro, read_results, write_results

REPO = Path(__file__).resolve().parents[1]
# plan_sha / ATI bank fingerprint of the family before the rename; the plan_sha is the one every
# readout sidecar of the family carries
PRE_PLAN_SHA = "1d5f2e2fa84bc1596c063420468a7e69185cfa5e717f1e54e6cac30606445fb8"
PRE_BANK_SHA = "a82a3d0d553a5d15a55626ea862b52a6c469b83bd39f9634f0b55f6fb685afd9"
# sha256 over every upper-case constant of the family's prompts module before the rename
PRE_PROMPTS_SHA = "560bc94fe4e16e9f39079d56686259e243558c516e84fc5bd7c9660e3510c60a"
PRE_STAMP = "mh2-mc-2026-11-01+norival-v1+qline-v2+bank-v6"
PRE_CALL_VERSION = "mh2-mc-2026-11-01+rv-2026-10-31e+optrv-v1+bank-v4"


def test_new_name_is_the_family(real_families):
    assert "multihop" in registry.FAMILIES
    assert not {"multihop_mt", "multihop_mt_v2"} & set(registry.FAMILIES)
    spec = registry.FAMILIES["multihop"]
    assert spec.bank == Path("evals/basic/multihop/items_v6.json")
    assert (REPO / "evals/basic/multihop").is_dir() and not (REPO / "evals/multihop_mt_v2").exists()
    assert (REPO / "examples/readouts/multihop.jsonl").is_file()
    for f in ("lucky_guessing", "prompt_only_summary"):
        d = json.loads((REPO / f"evals/baselines/{f}.json").read_text(encoding="utf-8"))
        assert "multihop" in d and not {"multihop_mt", "multihop_mt_v2"} & set(d), f
    ati = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    assert "multihop" in ati["_not_gated"]
    assert not {"multihop_mt", "multihop_mt_v2"} & set(ati["_not_gated"])


def test_old_names_are_former_keys(capsys):
    for old in ("multihop_mt_v2", "multihop_mt"):
        assert registry.LEGACY_FAMILY_NAMES[old] == "multihop"
        assert registry.canonical(old) == "multihop"  # single-step, straight to the current key
        assert _family(old) == "multihop"
        err = capsys.readouterr().err
        assert err.strip() == f"note: family {old!r} was renamed to 'multihop'"
        assert registry.bank_path(old) == registry.bank_path("multihop")
    # multihop_mt_v2 is listed BEFORE multihop_mt: its files win (the latter may be the removed
    # regex family's)
    assert registry.legacy_names("multihop") == ["multihop_mt_v2", "multihop_mt"]


def test_removed_family_has_its_own_key():
    assert "multihop_mt_regex" in registry.REMOVED_FAMILIES
    assert not {"multihop_mt", "multihop"} & set(registry.REMOVED_FAMILIES)
    entry = registry.REUSED_FAMILY_KEYS["multihop_mt"]
    assert (entry.live, entry.other, entry.other_stamps) == ("multihop", "multihop_mt_regex", None)
    # the live family's stamps are the ones the reused key recognises
    prefixes = entry.live_stamps
    assert P.MH2_PROMPT_VERSION.startswith(prefixes) and P.MH2_REGEX_VERSION in prefixes


def test_hashes_unchanged_by_the_rename():
    assert reads.plan_sha("multihop") == reads.plan_sha("multihop_mt_v2") == PRE_PLAN_SHA
    assert reads.plan_sha("multihop_mt") == PRE_PLAN_SHA
    rows = [s.row() for s in readplan.plan("multihop_mt_v2")]
    assert {r["family"] for r in rows} == {"multihop"}
    # the frozen hash key is still the pre-2026-11-04 one; the raw-key sites (plan 0101 §2.1)
    # embed the key of just before plan 0101 instead
    assert registry.hash_name("multihop") == "multihop_mt_v2"
    assert registry.frozen_name("multihop") == "multihop_mt"
    assert ti.bank_fingerprint("multihop") == PRE_BANK_SHA


def test_instrument_and_prompt_bytes_unchanged_by_the_rename():
    assert P.MH2_PROMPT_VERSION == PRE_STAMP
    assert fam.call_pv("multihop", PRE_STAMP) == PRE_CALL_VERSION
    consts = {k: getattr(P, k) for k in dir(P) if k.isupper()}
    blob = json.dumps(consts, sort_keys=True, ensure_ascii=False, default=str)
    assert hashlib.sha256(blob.encode()).hexdigest() == PRE_PROMPTS_SHA


def test_seeds_unchanged_by_the_rename():
    def pre(seed, *key):  # the lucky-guessing seed, keyed by the old family name
        h = hashlib.sha256(":".join(str(k) for k in (seed, *key)).encode()).digest()[:8]
        return random.Random(int.from_bytes(h, "big"))

    for key in (("x", "examples"), ("x", 0, 3)):
        new = lucky_guessing._rng(7, "multihop", *key).random()
        assert new == pre(7, "multihop_mt_v2", *key).random()

    def pre4(blob):
        return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:4], "big")

    assert ti.qwen_seed("multihop", "x") == pre4("multihop_mt_v2|x")
    assert gate_sampling.seed("multihop", "x", 1) == pre4("multihop_mt_v2|x|1")


def test_former_key_files_win_under_the_reused_key(tmp_path):
    # a pre-rename root may still hold the removed family's multihop_mt files: a file under
    # multihop_mt_v2 wins over one under multihop_mt, and the current key is tried first
    assert registry.lookup_names("multihop") == ["multihop", "multihop_mt_v2", "multihop_mt"]
    assert registry.lookup_names("wrong_intermediate") == ["wrong_intermediate", "wrong_bridge"]
    root = tmp_path / "readouts"
    root.mkdir()
    (root / "multihop_mt.jsonl").write_text("", encoding="utf-8")
    assert runner.readouts_path(root, "multihop") == root / "multihop_mt.jsonl"
    (root / "multihop_mt_v2.jsonl").write_text("", encoding="utf-8")
    assert runner.readouts_path(root, "multihop") == root / "multihop_mt_v2.jsonl"
    (root / "multihop.jsonl").write_text("", encoding="utf-8")
    assert runner.readouts_path(root, "multihop") == root / "multihop.jsonl"
    out = tmp_path / "judged"
    (out / "multihop_mt").mkdir(parents=True)
    assert registry.family_dir(out, "multihop") == out / "multihop_mt"
    (out / "multihop_mt_v2").mkdir()
    assert registry.family_dir(out, "multihop") == out / "multihop_mt_v2"
    (out / "multihop").mkdir()
    assert registry.family_dir(out, "multihop") == out / "multihop"


def test_adapted_set_under_the_old_name(tmp_path, monkeypatch):
    (tmp_path / "multihop_mt_v2.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert registry.bank_path("multihop") == tmp_path / "multihop_mt_v2.json"
    report = {"families": {"multihop_mt_v2": {"n_items": 3}}, "drops": {"multihop_mt_regex": {}}}
    assert store.report_entry(report["families"], "multihop") == {"n_items": 3}
    assert store.report_entry(report["drops"], "multihop") == {}


def test_adapted_reports_keep_the_removed_familys_drops_apart():
    # the removed regex family's drops (multihop-au-* ids) never sit under the current key; a set
    # rebuilt after the rename (plan 0089) has no regex drops and drops current multihop ids
    for m in ("gemma-4-31b-it", "olmo-3.1-32b", "qwen3.6-35b-a3b"):
        drops = json.loads((REPO / f"adapted/{m}/report.json").read_text(encoding="utf-8"))["drops"]
        assert "multihop_mt" not in drops and "multihop_mt_v2" not in drops, m  # migrated (0101)
        assert drops.get("multihop_mt_regex") or "multihop" in drops, m
        assert all(i.startswith("multihop-au-") for i in drops.get("multihop_mt_regex", {})), m
        assert not any(i.startswith("multihop-au-") for i in drops.get("multihop", {})), m
        # the current key holds current-family ids only (the multihop bank's mh2-* ids)
        assert all(i.startswith("mh2-") for i in drops.get("multihop", {})), m


def _stored(tmp_path: Path, family: str, pv: str) -> FamilyResult:
    d = tmp_path / family / pv.replace("+", "_")
    r = FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.5,
        ci95=None,
        n_items=2,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config={"prompt_version": pv},
        counts={},
    )
    write_results(d, r)
    return read_results(d)


def test_stored_results_are_told_apart_by_stamp(tmp_path):
    old = _stored(tmp_path, "multihop_mt", "mc-2026-09-16")  # the removed regex-scored family
    assert old.family == "multihop_mt_regex"
    assert _stored(tmp_path, "multihop_mt", "mt-regex-2026-09-23").family == "multihop_mt_regex"
    assert _stored(tmp_path, "multihop_mt", PRE_STAMP + "+digest-v5").family == "multihop"
    assert _stored(tmp_path, "multihop_mt_v2", PRE_STAMP).family == "multihop"
    assert _stored(tmp_path, "multihop_mt", P.MH2_REGEX_VERSION).family == "multihop"
    m = macro([old])
    assert m["excluded"] == [
        {
            "family": "multihop_mt_regex",
            "reason": "removed",
            "why": registry.REMOVED_FAMILIES["multihop_mt_regex"],
        }
    ]


def test_adapted_set_under_the_old_name_is_planned(tmp_path, monkeypatch):
    """Plan 0072 §2.1 (a #344 regression): ``readplan.families()`` (what ``plan`` and ``run
    all=True`` iterate under ``WSB_BANK_ROOT``) finds a set's ``multihop_mt_v2.json`` through the
    former-key lookup, as ``bank_path`` does; before the fix every adapted set silently skipped
    the family."""
    (tmp_path / "multihop_mt_v2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "typo_mt.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert readplan.families() == ["multihop", "typo"]
    # a reused key: a file under the removed family's key alone is still this family's file
    # (the removed family has no registered bank)
    (tmp_path / "multihop_mt_v2.json").unlink()
    (tmp_path / "multihop_mt.json").write_text("{}", encoding="utf-8")
    assert readplan.families() == ["multihop", "typo"]
    (tmp_path / "multihop_mt.json").unlink()
    assert readplan.families() == ["typo"]


def test_no_adapted_set_ships_a_former_key_and_every_set_plans_the_family(monkeypatch):
    """Plan 0101 retired the last in-repo ``multihop_mt_v2.json`` / ``multihop_mt.json``: every
    committed set that has the family ships ``multihop.json`` (header ``multihop-hard``) and
    plans it."""
    assert not list((REPO / "adapted").glob("*/multihop_mt_v2.json"))
    assert not list((REPO / "adapted").glob("*/multihop_mt.json"))
    sets = sorted(
        p.parent
        for p in (REPO / "adapted").glob("*/multihop.json")
        if json.loads(p.read_text(encoding="utf-8")).get("family") == "multihop-hard"
    )
    assert len(sets) == 16
    for d in sets:
        monkeypatch.setenv(registry.BANK_ROOT_ENV, str(d))
        assert registry.bank_path("multihop") == d / "multihop.json", d.name
        assert "multihop" in readplan.families(), d.name
        assert reads.plan_sha("multihop"), d.name
