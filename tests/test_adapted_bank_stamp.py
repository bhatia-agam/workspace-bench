"""Plan 0072 Phase 0.2: under ``WSB_BANK_ROOT`` a result's ``+bank-v<N>`` tag names the judged
adapted bank's header version, so a stale set is never stamped as a refreshed one; call keys,
re-frozen sets, unversioned headers and runs without a root are unchanged, and the floor column
still compares the registered stamp."""

import json

from wsbench import registry, results, runner
from wsbench.evals.association.association import prompts as assoc_prompts
from wsbench.results import FamilyResult

REG_ASSOC = registry.FAMILIES["association"].judge.prompt_version


def _bank(root, family, version):
    hdr = {"family": family, "items": []}
    if version is not None:
        hdr["version"] = version
    (root / f"{family}.json").write_text(json.dumps(hdr), encoding="utf-8")


def _result(family, pv):
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.5,
        ci95=None,
        n_items=1,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config={"prompt_version": pv, "judge_model": registry.FAMILIES[family].judge.model},
        counts={},
    )


def test_registered_stamp_carries_the_registered_version(real_families):
    assert "+bank-v5" in REG_ASSOC and assoc_prompts.BANK_TAG == "bank-v5"


def test_stale_set_is_stamped_with_its_own_version(tmp_path, monkeypatch, real_families):
    _bank(tmp_path, "association", 3)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    got = runner.adapted_bank_stamp("association", REG_ASSOC + "+digest-v5-x")
    assert got == REG_ASSOC.replace("+bank-v5", "+bank-v3") + "+digest-v5-x"
    assert "+bank-v5" not in got


def test_refrozen_set_and_no_root_are_unchanged(tmp_path, monkeypatch, real_families):
    assert runner.adapted_bank_stamp("association", REG_ASSOC) == REG_ASSOC  # no root
    _bank(tmp_path, "association", 5)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert runner.adapted_bank_stamp("association", REG_ASSOC) == REG_ASSOC


def test_untouched_without_a_versioned_header_or_tag(tmp_path, monkeypatch, real_families):
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    um = registry.FAMILIES["user_modeling"].judge.prompt_version
    _bank(tmp_path, "user_modeling", None)  # adapted user_modeling headers carry no version
    assert runner.adapted_bank_stamp("user_modeling", um + "+bank-v3") == um + "+bank-v3"
    (tmp_path / "conjunctive_association.json").write_text("[]", encoding="utf-8")  # bare list
    pv = "x+bank-v5"
    assert runner.adapted_bank_stamp("conjunctive_association", pv) == pv
    _bank(tmp_path, "typo", 1)
    assert runner.adapted_bank_stamp("typo", "no-tag") == "no-tag"  # no +bank-v tag at all


def test_only_the_registered_versions_tag_moves(tmp_path, monkeypatch, real_families):
    _bank(tmp_path, "association", 3)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    # a tag that is not the registered version (v50 starts with v5) is never rewritten
    assert runner.adapted_bank_stamp("association", "a+bank-v50+b") == "a+bank-v50+b"


def test_a_bank_file_pin_wins(tmp_path, monkeypatch, real_families):
    _bank(tmp_path, "association", 3)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(
        registry.BANK_FILE_ENV_PREFIX + "ASSOCIATION", str(tmp_path / "association.json")
    )
    assert runner.adapted_bank_stamp("association", REG_ASSOC) == REG_ASSOC


def test_result_stamps_and_the_floor_column(tmp_path, monkeypatch, real_families):
    _bank(tmp_path, "association", 3)
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    r = _result("association", REG_ASSOC)
    r.config["instrument_of_record"] = REG_ASSOC
    assert results.floor_applies(r)
    runner.stamp_adapted_bank("association", r)
    assert (
        "+bank-v3" in r.config["prompt_version"] and "+bank-v3" in r.config["instrument_of_record"]
    )
    assert r.config["registered_prompt_version"] == REG_ASSOC
    assert results.floor_applies(r)  # the floor is still drawn beside it
    r2 = _result("association", REG_ASSOC.replace("+bank-v5", "+bank-v3"))
    assert not results.floor_applies(r2)  # a bare v3 stamp is not the floor's instrument


def test_summary_floor_is_drawn_beside_a_restamped_row(real_families):
    """Summary rows (the default) match the registered summary floor under the registered stamp,
    and a floor frozen from re-stamped rows under the re-stamp; any other stamp matches neither."""
    from wsbench.baselines import prompt_only as po

    pv = REG_ASSOC + "+digest-v5-x"
    entry = {"instrument": pv, "summarizer": None, "judge_model": "claude-opus-5-5"}
    cfg = {"aggregate": "summary", "prompt_version": pv, "judge_model": "claude-opus-5-5"}
    assert po.summary_floor_matches(entry, cfg)
    re_stamped = {**cfg, "prompt_version": pv.replace("+bank-v5", "+bank-v3"),
                  "registered_prompt_version": pv}  # fmt: skip
    assert po.summary_floor_matches(entry, re_stamped)  # the registered floor, as before
    adapted_floor = {**entry, "instrument": re_stamped["prompt_version"]}
    assert po.summary_floor_matches(adapted_floor, re_stamped)  # a floor of the re-stamped rows
    bare = {**cfg, "prompt_version": re_stamped["prompt_version"]}
    assert not po.summary_floor_matches(entry, bare)


def test_floor_freeze_accepts_a_restamped_run_dir(tmp_path, monkeypatch, real_families):
    """A stale adapted set's prompt-only run (re-stamped +bank-v3) still freezes: the check reads
    the registered stamp, and the floor's instrument is the row's own re-stamped one."""
    from test_po_floors_r3 import _result, _spv

    from wsbench.baselines import prompt_only as po
    from wsbench.results import write_results

    spv = _spv("association")
    r = _result("association", spv, layers=[44])
    r.config["registered_prompt_version"] = spv
    r.config["prompt_version"] = spv.replace("+bank-v5", "+bank-v3")
    run = tmp_path / "run"
    write_results(run / "association", r)
    dst = tmp_path / "floors" / "prompt_only_summary.json"
    dst.parent.mkdir()
    po.freeze(run, dst)
    got = json.loads(dst.read_text())["association"]
    assert got["instrument"] == r.config["prompt_version"]
    assert po.summary_floor_matches(got, r.config)
    r.config.pop("registered_prompt_version")  # a bare re-stamp is refused as before
    write_results(run / "association", r)
    import pytest

    with pytest.raises(ValueError, match="re-judge first"):
        po.freeze(run, dst)


def test_native_floor_freeze_roundtrips_a_restamped_row(tmp_path, real_families):
    """A native prompt-only floor frozen from a re-stamped adapted row stores the registered stamp
    (what the native loader compares), so `floors()` reads it back."""
    from test_po_floors_r3 import _result

    from wsbench.baselines import prompt_only as po
    from wsbench.results import write_results

    pv = registry.FAMILIES["association"].judge.prompt_version
    r = _result("association", pv, layers=[44])
    r.config.pop("aggregate", None)
    r.config["registered_prompt_version"] = pv
    r.config["prompt_version"] = pv.replace("+bank-v5", "+bank-v3")
    run = tmp_path / "run"
    write_results(run / "association", r)
    dst = tmp_path / "prompt_only.json"
    po.freeze(run, dst)
    assert json.loads(dst.read_text())["association"]["instrument"] == pv
    assert "association" in po.floors(dst)
