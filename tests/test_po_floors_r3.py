"""Round 3 floors: the campaign's Opus 5.5 prompt-only floors (with the Sonnet 5 fallback for
the ids Opus refused; new fallback runs use Sonnet 5.5 since 2026-11-01, the committed Sonnet 5
floors stay readable history) frozen into ``evals/baselines/prompt_only_summary.json`` and drawn by
``wsbench report``; and the opt-in judge column (``report alt_judge=<dir>``) for the two
Sonnet-pinned families. Every rule is tested both ways: the lenient shape still fails and the
strict shape that should pass passes."""

import json
from pathlib import Path

import pytest

from wsbench.baselines import prompt_only as po
from wsbench.baselines import prompt_only_opus as poo
from wsbench.cli import _po_text, main
from wsbench.judge_config import DEFAULT_JUDGE
from wsbench.results import (
    FamilyResult,
    alt_judge_cell,
    alt_judge_matches,
    markdown_table,
    write_results,
)

REPO = Path(__file__).resolve().parents[1]
FROZEN = REPO / "evals" / "baselines" / "prompt_only_summary.json"
SUMM = {"model": "claude-opus-5-5", "max_items": 10, "concurrency": 256, "timeout": 900.0}


def _result(
    family: str,
    pv: str,
    *,
    judge: str = DEFAULT_JUDGE,
    value: float = 0.4,
    layers: list[int] | None = None,
    rows: list[dict] | None = None,
    **cfg_extra: object,
) -> FamilyResult:
    cfg: dict = {
        "judge_model": judge,
        "prompt_version": pv,
        "layers_judged": layers,
        "aggregate": "summary",
        "summarizer": dict(SUMM),
        **cfg_extra,
    }
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=value,
        ci95=(value - 0.1, value + 0.1),
        n_items=10,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config=cfg,
        counts={
            "n_expected_cells": 10,
            "n_missing_cells": 0,
            "n_unjudged_cells": 0,
            "n_empty_cells": 0,
        },
        extras={"n_items_decided": 10},
        rows=rows or [],
    )


def _spv(family: str) -> str:
    return f"{po.instrument_versions()[family]}+digest-v5-task-extractive+sj-v10"


# ------------------------------------------------------------------ freeze: fallback protocol


def _fb_cfg(fams: dict, protocol: str = po.PO_FALLBACK) -> dict:
    legacy = protocol == po.PO_FALLBACK_SONNET5
    return {
        "protocol": protocol,
        "reader": f"{poo.READER}+claude-sonnet-5-fallback" if legacy else poo.FALLBACK_READER,
        "primary": poo.MODEL,
        "fallback": "claude-sonnet-5" if legacy else poo.FALLBACK_MODEL,
        "framing": poo.FRAMING,
        "draws": 1,
        "families": fams,
    }


def _ids(n: int) -> list[str]:
    return [f"i{k}" for k in range(n)]


def test_fallback_not_measurable_counts_ids_refused_by_both_not_opus_alone():
    # too strict before: Opus refused 69% but Sonnet served every one -> measurable
    frozen = {"f": {"rate": 0.2, "n_items": 54, "n_items_decided": 54, "ci95": [0.1, 0.3]}}
    st = {"n_ids": 54, "refused_opus": _ids(37), "served_by_sonnet": _ids(37), "refused_both": []}
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}), {})
    e = frozen["f"]
    assert e["not_measurable"] is False and e["n_refused_ask"] == 0
    assert e["refusal_rate_opus"] == pytest.approx(37 / 54) and e["n_served_by_fallback"] == 37
    assert e["label"] == "Opus 5.5 + Sonnet 5.5 fallback (0 refused by both)"
    assert e["protocol"] == po.PO_FALLBACK == "po-opus-v1+sonnet55-fallback"
    # a legacy Sonnet 5 fallback run still freezes under its own protocol and label
    frozen = {"f": {"rate": 0.2, "n_items": 54, "n_items_decided": 54, "ci95": [0.1, 0.3]}}
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}, po.PO_FALLBACK_SONNET5), {})
    e = frozen["f"]
    assert e["label"] == "Opus 5.5 + Sonnet 5 fallback (0 refused by both)"
    assert e["protocol"] == po.PO_FALLBACK_SONNET5 == "po-opus-v1+sonnet5-fallback"
    # still fails when too many ids were refused by BOTH readers (or never digested)
    frozen = {
        "f": {
            "rate": 0.2,
            "n_items": 10,
            "n_items_decided": 10,
            "ci95": [0.1, 0.3],
            "digest_unserved": ["i9"],
        }
    }
    st = {
        "n_ids": 10,
        "refused_opus": _ids(5),
        "served_by_sonnet": _ids(3),
        "refused_both": ["i3", "i4"],
    }
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}), {})
    e = frozen["f"]
    assert e["n_refused"] == 3 and e["refusal_share"] == pytest.approx(0.3)
    assert e["not_measurable"] is True


def test_fallback_opus_only_rides_only_on_the_same_instrument():
    prior = {
        "f": {
            "protocol": po.PO_OPUS,
            "instrument": "pv+digest-v5",
            "value": 0.1,
            "n": 20,
            "ci": [0.0, 0.2],
            "refusal_share": 0.65,
            "not_measurable": True,
            "label": "Opus 5.5 (65 refused)",
        }
    }
    base = {"rate": 0.22, "n_items": 100, "n_items_decided": 100, "ci95": [0.1, 0.3]}
    st = {"n_ids": 100, "refused_opus": _ids(65), "served_by_sonnet": _ids(65), "refused_both": []}
    frozen = {"f": {**base, "instrument": "pv+digest-v5"}}
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}), prior)
    assert frozen["f"]["opus_only"]["not_measurable"] is True
    assert frozen["f"]["opus_only"]["value"] == 0.1
    # another instrument (or a non-Opus prior entry) is never attached
    frozen = {"f": {**base, "instrument": "pv2+digest-v5"}}
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}), prior)
    assert "opus_only" not in frozen["f"]
    frozen = {"f": {**base, "instrument": "pv+digest-v5"}}
    po._po_fallback_entries(frozen, _fb_cfg({"f": st}), {"f": {**prior["f"], "protocol": None}})
    assert "opus_only" not in frozen["f"]


def test_po_opus_entry_has_label_and_explicit_flag():
    frozen = {"f": {"rate": 0.3, "n_items": 10, "n_items_decided": 10, "ci95": [0.1, 0.5]}}
    po._po_opus_entries(frozen, {"families": {"f": {"n_ids": 10, "refused": ["a"]}}})
    assert frozen["f"]["not_measurable"] is False and frozen["f"]["label"] == "Opus 5.5 (1 refused)"
    frozen = {"f": {"rate": 0.3, "n_items": 10, "n_items_decided": 7, "ci95": [0.1, 0.5]}}
    po._po_opus_entries(frozen, {"families": {"f": {"n_ids": 10, "refused": ["a", "b", "c"]}}})
    assert frozen["f"]["not_measurable"] is True


def _po_run(tmp_path: Path, family: str, pv: str, name: str) -> Path:
    run = tmp_path / name
    write_results(run / family, _result(family, pv, layers=[44]))
    return run


def test_freeze_opus_then_fallback_end_to_end(tmp_path, monkeypatch, real_families):
    dst = tmp_path / "po_summary.json"
    dst.write_text(json.dumps({"_source": {"base_model": "Qwen"}, "typo": {"rate": 0.9}}))
    monkeypatch.setattr(po, "FROZEN_SUMMARY", dst)
    monkeypatch.setattr(po, "ARCHIVE_QWEN_SUMMARY", tmp_path / "archive" / "qwen.json")
    spv = _spv("association")
    opus_cfg = tmp_path / "opus.json"
    opus_cfg.write_text(
        json.dumps(
            {
                "protocol": po.PO_OPUS,
                "model": poo.MODEL,
                "framing": poo.FRAMING,
                "template_sha": "t",
                "draws": 1,
                "families": {"association": {"n_ids": 10, "refused": ["i0", "i1", "i2"]}},
            }
        )
    )
    po.freeze(_po_run(tmp_path, "association", spv, "opus"), dst, source=opus_cfg)
    got = json.loads(dst.read_text())
    assert "typo" not in got  # the stale stock-Qwen entry is archived, not kept
    assert (tmp_path / "archive" / "qwen.json").exists()
    assert got["association"]["not_measurable"] is True  # 30% refused by Opus alone
    fb_cfg = tmp_path / "fb.json"
    st = {"n_ids": 10, "refused_opus": _ids(3), "served_by_sonnet": _ids(3), "refused_both": []}
    fb_cfg.write_text(json.dumps(_fb_cfg({"association": st})))
    po.freeze(_po_run(tmp_path, "association", spv, "fb"), dst, source=fb_cfg)
    got = json.loads(dst.read_text())
    e = got["association"]
    assert e["protocol"] == po.PO_FALLBACK and e["not_measurable"] is False
    assert e["opus_only"]["not_measurable"] is True
    assert got["_source"]["protocol"] == po.PO_OPUS and got["_source"]["template_sha"] == "t"
    assert got["_source"]["fallback"]["fallback"] == poo.FALLBACK_MODEL


def test_freeze_accepts_agentic_summary_stamp_base_only(tmp_path, monkeypatch, real_families):
    from wsbench.evals.agentic_misalignment import prompts as amp

    dst = tmp_path / "po_summary.json"
    monkeypatch.setattr(po, "FROZEN_SUMMARY", dst)
    # agentic's summary stamp base (summ-c3 replaces the native narrative stage) is accepted
    good = f"{amp.SUMMARY_STAMP_VERSION}+digest-v5-task-extractive+sj-v10"
    assert not good.startswith(po.instrument_versions()["agentic_misalignment"])
    po.freeze(_po_run(tmp_path, "agentic_misalignment", good, "ok"), dst)
    assert json.loads(dst.read_text())["agentic_misalignment"]["instrument"] == good
    # an older Stage C (or any other base) is still refused
    with pytest.raises(ValueError, match="re-judge first"):
        po.freeze(_po_run(tmp_path, "agentic_misalignment", "am-old+digest-v5", "bad"), dst)
    with pytest.raises(ValueError, match="re-judge first"):
        po.freeze(_po_run(tmp_path, "association", "assoc-old+digest-v5", "bad2"), dst)
    assert po.summary_bases("association", "b") == ("b",)
    assert po.summary_bases("no_such_family", None) == ()


# ------------------------------------------------------------------ the committed floor file


SONNET_DIGEST = ("agentic_misalignment", "jailbreak_recognition")
# families whose result stamp moved after the refreeze on a scoring-only rule change: the floor of
# record stays on the stamp it was measured under (so `report` does not draw it) until it is
# re-scored from its cached judge answers; an entry leaves once its floor is refreshed.
# 2026-11-04 (pre-merge review): the cut-mid-name line rule, the English plural rule and the
# pass / fail vote, on banks this series replaces later.
PENDING_RESCORE: dict[str, str] = {
    "multilingual_multihop": "mcrx-2026-11-03d+mc-ml-2026-11-01b",
    "multilingual_typo": (
        "mt-regex-2026-10-30+v2+ln-2026-11-03a+rawrx-v2+plural-v1+anchor-support-v1+langleg-v1"
        "+bank-v3"
    ),
}


def test_committed_floor_file_is_the_refreeze(real_families):
    """The committed floors are the 2026-11-04 refreeze: every family's floor is on its
    current summary instrument (so `report` draws it), read by Opus 5.5 with the Sonnet 5.5
    fallback where Opus declined (agentic_misalignment only), none refused by both."""
    got = json.loads(FROZEN.read_text(encoding="utf-8"))
    fams = {k: v for k, v in got.items() if not k.startswith("_")}
    assert set(fams) == set(poo.families())  # every category but jlens_concept_pr
    versions = po.instrument_versions()
    for fam, e in fams.items():
        assert e["protocol"] in (po.PO_OPUS, po.PO_FALLBACK), fam
        assert isinstance(e["not_measurable"], bool) and e["label"], fam
        assert not e["not_measurable"], fam
        # agentic and jailbreak digest on their Sonnet 5 pin, the rest on Opus
        digest_model = "claude-sonnet-5" if fam in SONNET_DIGEST else "claude-opus-5-5"
        assert e["aggregate"] == "summary" and e["summarizer"]["model"] == digest_model, fam
        bases = po.summary_bases(fam, versions[fam])
        if fam in PENDING_RESCORE:  # still exactly on the stamp before the rule change
            bases = (PENDING_RESCORE[fam],)
        assert any(e["instrument"].startswith(f"{b}+") for b in bases), (fam, e["instrument"])
        assert "+digest-" in e["instrument"], fam
    fb = {f for f, e in fams.items() if e["protocol"] == po.PO_FALLBACK}
    assert fb == {"agentic_misalignment"}
    assert fams["agentic_misalignment"]["n_refused_ask"] == 0
    assert fams["agentic_misalignment"]["opus_only"]["not_measurable"] is False
    # the two Sonnet-pinned families' floors were judged by their pinned judge
    assert fams["agentic_misalignment"]["judge_model"] == "claude-sonnet-5"
    assert fams["jailbreak_recognition"]["judge_model"] == "claude-sonnet-5"
    assert got["_source"]["fallback"]["fallback"] == "claude-sonnet-5-5"
    # role_bound's floor is its pair headline (pair-v1) and is drawn, not marked saturated
    assert fams["role_bound_association"]["saturated"] is False
    assert fams["role_bound_association"]["instrument"].startswith("oa-v3.1+bank-v2+maj3v+")
    # moral_rationale's floor is judged with its summary rules (majority of 3, near quotes)
    assert fams["moral_rationale"]["instrument"].startswith("ec-v9+nq1+maj3v+")
    assert (REPO / "evals/baselines/archive/prompt_only_summary.qwen-2026-10-29.json").exists()


# ------------------------------------------------------------------ report cells


def _entry(spv: str, **kw: object) -> dict:
    return {
        "rate": 0.54,
        "instrument": spv,
        "judge_model": DEFAULT_JUDGE,
        "summarizer": po.summarizer_key({"summarizer": SUMM}),
        **kw,
    }


def test_report_draws_the_label_and_not_measurable_cells():
    spv = "bank-x+digest-v5"
    row = _result("association", spv, layers=[44])
    fb = _entry(
        spv,
        protocol=po.PO_FALLBACK,
        not_measurable=False,
        refusal_rate_opus=0.9,
        n_refused_ask=0,
        n_ids=100,
        opus_only={"value": 0.07, "not_measurable": True, "refusal_share": 0.9},
    )
    text = _po_text("association", fb)
    assert text.startswith("0.540 [Opus 5.5 + Sonnet 5.5 fallback; Opus refused 90%, both 0/100")
    assert "Opus alone not measurable (90% refused)" in text
    md = markdown_table(
        [row], None, floors={"po": {}}, summary_floors={"po": {"association": (fb, text)}}
    )
    assert "| 0.540 [Opus 5.5 + Sonnet 5.5 fallback" in md
    # the legacy Sonnet 5 protocol keeps its own label; an unknown protocol gets none
    legacy = _po_text("association", {**fb, "protocol": po.PO_FALLBACK_SONNET5})
    assert legacy.startswith("0.540 [Opus 5.5 + Sonnet 5 fallback; Opus refused 90%")
    assert po.floor_label({**fb, "protocol": "po-opus-v1+other-fallback"}) == ""
    # a not_measurable floor on the row's own instrument says so (not a silent withheld dash)
    nm = _entry(spv, protocol=po.PO_OPUS, not_measurable=True, refusal_share=0.69, n_refused=37)
    nm_text = _po_text("association", nm)
    assert nm_text.startswith("not measurable (69% refused)") and "0.540" not in nm_text
    md = markdown_table(
        [row], None, floors={"po": {}}, summary_floors={"po": {"association": (nm, nm_text)}}
    )
    assert "not measurable (69% refused)" in md and "match the frozen summary floor" not in md
    # ... but never on another instrument (withheld, with the override legend)
    other = _result("association", "bank-y+digest-v5", layers=[44])
    md = markdown_table(
        [other], None, floors={"po": {}}, summary_floors={"po": {"association": (nm, nm_text)}}
    )
    assert "not measurable" not in md and "match the frozen summary floor" in md
    # a measured floor is not drawn as a rate when flagged not_measurable
    assert not po.summary_floor_applies(nm, row.config) and po.summary_floor_matches(nm, row.config)


def test_report_cli_shows_the_committed_floors(tmp_path, real_families):
    got = json.loads(FROZEN.read_text(encoding="utf-8"))
    e = got["association"]
    cfg_extra = {"summarizer": {**e["summarizer"], "concurrency": 256}}
    r = _result("association", e["instrument"], judge=e["judge_model"], value=0.97)
    r.config.update(cfg_extra)
    run = tmp_path / "run"
    write_results(run / "association", r)
    assert main(["report", f"dir={run}"]) == 0
    md = (run / "summary.md").read_text()
    assert f"{e['rate']:.3f} [Opus 5.5; 0 refused]" in md


# jailbreak_recognition left the route (its digest is its Sonnet 5 judge pin;
# test_jailbreak_floor_is_on_the_sonnet_digest)
SONNET55_FALLBACK_FAMILIES = (
    "introspection",
    "moral_rationale",
    "user_modeling",
    "model_specific_directed_modulation",
)


def _live_config(family: str, entry: dict, aux_models: dict | None = None) -> dict:
    """The config a live summary row of ``family`` carries on this branch: the summarizer comes
    from ``digest.config`` (not copied from the frozen entry), so a protocol change shows."""
    from wsbench import digest
    from wsbench.registry import JudgeArgs

    args = JudgeArgs(
        readouts=Path("x"),
        out=Path("y"),
        judge=None,
        layers=None,
        items=None,
        limit=0,
        allow_missing=False,
        concurrency=256,
        rpm=0.0,
        dry_run=False,
        aux_models=aux_models or {},
        extra={},
    )
    return {
        **digest.config(args, None, family),
        "prompt_version": entry["instrument"],
        "judge_model": entry["judge_model"],
    }


@pytest.mark.parametrize("family", SONNET55_FALLBACK_FAMILIES)
def test_committed_floor_applies_to_a_live_row_whatever_the_refusal_model(family, real_families):
    """The four families digest with the Sonnet 5.5 refusal fallback; their committed floors were
    digested with it (2026-11-04 refreeze) or, model_specific_directed_modulation's, with the
    retired Sonnet 5 fallback. Either matches a live row (the fallback model is not part of the
    instrument), but a changed fallback MODE or any other digest setting does not."""
    e = json.loads(FROZEN.read_text(encoding="utf-8"))[family]
    cfg = _live_config(family, e)
    live_fb = cfg["summarizer"]["fallback"]
    assert live_fb == "default+claude-sonnet-5-5"
    assert e["summarizer"]["fallback"].startswith("default+claude-sonnet-5")
    assert po.summary_floor_matches(e, cfg)
    assert po.summary_floor_applies(e, cfg) == (not e.get("not_measurable"))
    for model in ("claude-sonnet-5", "claude-sonnet-5-5"):
        other = {**e, "summarizer": {**e["summarizer"], "fallback": f"default+{model}"}}
        assert po.summary_floor_matches(other, cfg)
    # the other direction: the fallback mode, or another digest key, still splits instruments
    for summ in (
        {**cfg["summarizer"], "fallback": "none"},
        {**cfg["summarizer"], "fallback": "default"},
        {**cfg["summarizer"], "max_items": cfg["summarizer"]["max_items"] + 1},
    ):
        assert not po.summary_floor_matches(e, {**cfg, "summarizer": summ})
    # the stored provenance keeps the full fallback string
    assert po.summarizer_key(cfg)["fallback"] == live_fb


def test_jailbreak_floor_is_on_the_sonnet_digest(real_families):
    """jailbreak_recognition digests on its judge pin claude-sonnet-5 with the client-side
    claude-opus-5 refusal re-run; the refrozen floor was digested the same way, so it matches a
    live row, and a floor digested on Opus 5.5 would not."""
    from wsbench import registry

    e = json.loads(FROZEN.read_text(encoding="utf-8"))["jailbreak_recognition"]
    spec = registry.get("jailbreak_recognition")
    cfg = _live_config("jailbreak_recognition", e, aux_models=dict(spec.judge.aux_models))
    assert cfg["summarizer"]["model"] == "claude-sonnet-5" == e["summarizer"]["model"]
    assert cfg["summarizer"]["fallback"] == "none+claude-opus-5"
    assert po.summary_floor_matches(e, cfg)
    opus = {**e, "summarizer": {**e["summarizer"], "model": "claude-opus-5-5"}}
    assert not po.summary_floor_matches(opus, cfg)


@pytest.mark.parametrize(
    "family", sorted(k for k in json.loads(FROZEN.read_text(encoding="utf-8")) if k[0] != "_")
)
def test_every_committed_floor_matches_its_live_row(family, real_families):
    """Every committed floor is on the instrument a live row of its family carries on this branch
    (the family's digest settings from ``digest.config``, its judge pin and aux models), so
    ``report`` draws it."""
    from wsbench import registry

    e = json.loads(FROZEN.read_text(encoding="utf-8"))[family]
    spec = registry.get(family)
    cfg = _live_config(family, e, aux_models=dict(spec.judge.aux_models))
    assert e["judge_model"] == spec.judge.model
    assert po.summary_floor_matches(e, cfg), (family, e["summarizer"], cfg["summarizer"])


@pytest.mark.parametrize(
    "family",
    ["association", "role_bound_association", "chain_intermediates", "arithmetic_intermediates"],
)
def test_committed_floor_rows_under_each_layer_mode(family, real_families):
    """A prompt-only readout is one cell per id, so every committed floor carries the single-layer
    digest instrument: it is drawn beside a single-layer row and an all-layer
    ``summ_layers=union`` row. A default all-layer row of a non-numbers family is digested layered
    (``-layered-v1x4``) and draws none; the numbers digests (chain, arithmetic) never run layered,
    so their floor is drawn at every layer count."""
    from wsbench import digest, registry
    from wsbench.registry import JudgeArgs

    e = json.loads(FROZEN.read_text(encoding="utf-8"))[family]
    spec = registry.get(family)
    base = e["instrument"].split("+digest-")[0]

    def row(n_layers: int, extra: dict) -> dict:
        args = JudgeArgs(
            readouts=Path("x"),
            out=Path("y"),
            judge=None,
            layers=None,
            items=None,
            limit=0,
            allow_missing=False,
            concurrency=256,
            rpm=0.0,
            dry_run=False,
            aux_models=dict(spec.judge.aux_models),
            extra=digest.resolve_layer_mode(family, extra, n_layers),
        )
        return {
            **digest.config(args, None, family),
            "prompt_version": digest.prompt_version(base, args, family),
            "judge_model": e["judge_model"],
        }

    numbers = family in ("chain_intermediates", "arithmetic_intermediates")
    assert po.summary_floor_applies(e, row(1, {}))
    assert po.summary_floor_applies(e, row(11, {"summ_layers": "union"}))
    layered = row(11, {})
    assert ("-layered-v1x4" in layered["prompt_version"]) is not numbers
    assert po.summary_floor_applies(e, layered) is numbers


def test_unaffected_family_floor_matches_the_live_row(real_families):
    e = json.loads(FROZEN.read_text(encoding="utf-8"))["association"]
    cfg = _live_config("association", e)
    assert po.summary_floor_matches(e, cfg)
    assert not po.summary_floor_matches(e, {**cfg, "judge_model": "claude-other"})


def test_report_cli_shows_the_committed_floor_for_a_sonnet55_row(tmp_path, real_families):
    """End to end: a ``wsbench report`` over a row built from the live digest config draws the
    committed floor of a family digested with the Sonnet 5.5 refusal fallback (not '—')."""
    e = json.loads(FROZEN.read_text(encoding="utf-8"))["introspection"]
    assert not e.get("not_measurable")
    cfg = _live_config("introspection", e)
    r = _result("introspection", e["instrument"], judge=e["judge_model"], value=0.97)
    r.config.update(cfg)
    run = tmp_path / "run"
    write_results(run / "introspection", r)
    assert main(["report", f"dir={run}"]) == 0
    md = (run / "summary.md").read_text()
    assert f"{e['rate']:.3f} [Opus 5.5; 0 refused]" in md
    # a row whose fallback mode differs gets no floor
    r.config["summarizer"] = {**cfg["summarizer"], "fallback": "none"}
    write_results(run / "introspection", r)
    assert main(["report", f"dir={run}"]) == 0
    assert f"{e['rate']:.3f} [Opus 5.5" not in (run / "summary.md").read_text()


# ------------------------------------------------------------------ opt-in judge column


def test_alt_judge_cell_matches_only_the_same_measurement():
    pv = "jb-v2+digest-v5"
    pinned = _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44])
    opus = _result("jailbreak_recognition", pv, judge="claude-opus-5-5", value=0.7, layers=[44])
    assert alt_judge_matches(pinned, opus)
    assert alt_judge_cell(pinned, opus) == "0.700 [0.600, 0.800] (claude-opus-5-5; n=10)"
    # an override run is never `complete` (not the pin): only real gaps are flagged
    opus.complete = False
    assert alt_judge_cell(pinned, opus) == "0.700 [0.600, 0.800] (claude-opus-5-5; n=10)"
    opus.counts["n_unjudged_cells"] = 2
    assert alt_judge_cell(pinned, opus).endswith("n=10; 2 cells unjudged or missing)")
    opus.extras["n_pairs_undecided"] = 1
    assert alt_judge_cell(pinned, opus).endswith("n=10; 2 cells unjudged or missing; 1 undecided)")
    opus.counts["n_unjudged_cells"] = 0
    opus.extras["n_pairs_undecided"] = 0
    # the lite row of the same readouts matches its own lite run
    lite = _result(
        "jailbreak_recognition", pv + "+reads-lite", judge="claude-sonnet-5", reads="lite"
    )
    opus_lite = _result(
        "jailbreak_recognition", pv + "+reads-lite", judge="claude-opus-5-5", reads="lite"
    )
    assert alt_judge_matches(lite, opus_lite)
    # never: the same judge, another instrument, other layers, another read mode, other
    # digest settings, a subset run, or no row at all
    assert alt_judge_cell(pinned, None) == "—"
    same = _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44])
    assert not alt_judge_matches(pinned, same)
    for bad in (
        _result("jailbreak_recognition", "jb-v1+digest-v5", judge="claude-opus-5-5", layers=[44]),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[48]),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=None),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], reads="lite"),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], limit=3),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], items=["a"]),
        _result("agentic_misalignment", pv, judge="claude-opus-5-5", layers=[44]),
    ):
        assert not alt_judge_matches(pinned, bad)
    other_digest = _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44])
    other_digest.config["summarizer"] = {**SUMM, "max_items": 25}
    assert not alt_judge_matches(pinned, other_digest)
    # throughput-only digest keys do not matter
    fast = _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44])
    fast.config["summarizer"] = {**SUMM, "concurrency": 8, "timeout": 60.0}
    assert alt_judge_matches(pinned, fast)


def test_alt_judge_requires_the_same_readouts():
    """Another reader's (or sampling's, or bank's) judge-override run is not the same
    readouts under another judge, so it never draws beside the row."""
    pv = "jb-v3+digest-v5"
    ids = {"reader": "final-olens-rl600-x4", "sampling": "bullet4", "bank_version": "am-bank-v2"}
    pinned = _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44], **ids)
    same = _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], **ids)
    # the same readouts under another judge still match (and throughput/stamp-only keys
    # such as concurrency or sampling_source do not matter)
    assert alt_judge_matches(pinned, same)
    same.config.update(concurrency=8, sampling_source="flag")
    assert alt_judge_matches(pinned, same)
    assert alt_judge_cell(pinned, same).startswith("0.400 [0.300, 0.500] (claude-opus-5-5")
    for key, other in (
        ("reader", "nla-ml-rl600"),
        ("sampling", "prose1"),
        ("bank_version", "v0-old"),
        ("reader", None),
    ):
        bad = _result(
            "jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], **{**ids, key: other}
        )
        assert not alt_judge_matches(pinned, bad), key
        assert alt_judge_cell(pinned, bad) == "—", key
    # results stamped without these keys on either side (legacy / reader-less) still match
    assert alt_judge_matches(
        _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44]),
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", layers=[44], reader=""),
    )


def test_report_alt_judge_column_is_opt_in_and_outside_the_macro(tmp_path, real_families):
    pv = "jb-v2+digest-v5"
    run, alt = tmp_path / "run", tmp_path / "opus"
    write_results(
        run / "jailbreak_recognition",
        _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44]),
    )
    write_results(
        alt / "jailbreak_recognition",
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", value=0.7, layers=[44]),
    )
    assert main(["report", f"dir={run}"]) == 0
    assert "opt-in judge" not in (run / "summary.md").read_text()
    assert main(["report", f"dir={run}", f"alt_judge={alt}"]) == 0
    md = (run / "summary.md").read_text()
    assert "| opt-in judge |" in md and "0.700 [0.600, 0.800] (claude-opus-5-5; n=10)" in md
    assert "Never in the macro" in md
    head, sep = md.split("\n")[:2]
    assert head.count("|") == sep.count("|")  # one separator per column
    assert main(["report", f"dir={run}", f"alt_judge={tmp_path / 'missing'}"]) == 2


def test_report_alt_judge_json(tmp_path, real_families, capsys):
    pv = "jb-v2+digest-v5"
    run, alt = tmp_path / "run", tmp_path / "opus"
    write_results(
        run / "jailbreak_recognition",
        _result("jailbreak_recognition", pv, judge="claude-sonnet-5", layers=[44]),
    )
    write_results(
        alt / "jailbreak_recognition",
        _result("jailbreak_recognition", pv, judge="claude-opus-5-5", value=0.7, layers=[44]),
    )
    assert main(["report", f"dir={run}", f"alt_judge={alt}", "json=True"]) == 0
    fam = json.loads(capsys.readouterr().out)["families"][0]
    assert fam["alt_judge"]["judge_model"] == "claude-opus-5-5"
    assert fam["alt_judge"]["value"] == 0.7


# ------------------------------------------------------------------ fallback readouts


def _src(tmp_path: Path, name: str, prompts: list[dict], answers: list[dict]) -> Path:
    d = tmp_path / name
    (d / "answers").mkdir(parents=True)
    (d / "prompts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in prompts))
    (d / "answers" / "draw0.jsonl").write_text("".join(json.dumps(r) + "\n" for r in answers))
    return d


def _p(fam: str, i: str) -> dict:
    return {"family": fam, "id": i, "prefix": "P", "token": "?", "pos": 3, "n_tokens": 4}


def _a(fam: str, i: str, text: str = "x", refused: bool = False, answerer: str = poo.MODEL) -> dict:
    return {
        "family": fam,
        "id": i,
        "answerer": answerer,
        "answer": "" if refused else text,
        "error": "refusal" if refused else "",
        **({"refused": True} if refused else {}),
    }


def test_fallback_readouts_serve_only_opus_refusals(tmp_path):
    src = _src(
        tmp_path,
        "opus",
        [_p("f", "a"), _p("f", "b"), _p("f", "c"), _p("g", "old")],
        [_a("f", "a", "opus a"), _a("f", "b", refused=True), _a("f", "c", refused=True),
         _a("g", "old", "stale")],
    )  # fmt: skip
    # a later dir replaces every row of the family it holds (g's re-asked bank)
    src2 = _src(tmp_path, "g2", [_p("g", "new")], [_a("g", "new", "fresh")])
    out = tmp_path / "fb"
    out.mkdir()
    sonnet, retired = poo.FALLBACK_MODEL, "claude-sonnet-5"
    (out / poo.FALLBACK_ANSWERS).write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (
                _a("f", "b", "sonnet b", answerer=sonnet),
                _a("f", "c", refused=True, answerer=sonnet),
                # retired Sonnet 5 answers later in the same file are never served (not this
                # protocol): neither over a Sonnet 5.5 answer nor over a Sonnet 5.5 refusal
                _a("f", "b", "sonnet5 b", answerer=retired),
                _a("f", "c", "sonnet5 c", answerer=retired),
            )
        )
    )
    stats = poo.write_fallback_readouts(out, [src, src2])
    f = stats["f"]
    assert f["refused_opus"] == ["b", "c"] and f["served_by_sonnet"] == ["b"]
    assert f["refused_both"] == ["c"] and f["refusal_rate_both"] == 0.3333
    assert f["not_measurable"] is True
    rows = [json.loads(x) for x in (out / "readouts/f.jsonl").read_text().splitlines()]
    # the Opus answer is kept where Opus answered; Sonnet only fills its refusal
    assert [(r["id"], r["samples"]) for r in rows] == [("a", ["opus a"]), ("b", ["sonnet b"])]
    g = [json.loads(x) for x in (out / "readouts/g.jsonl").read_text().splitlines()]
    assert [r["id"] for r in g] == ["new"] and stats["g"]["n_ids"] == 1
    cfg = json.loads((out / "readouts/run_config.json").read_text())
    assert cfg["protocol"] == po.PO_FALLBACK and cfg["fallback"] == "claude-sonnet-5-5"
    meta = json.loads((out / "readouts/f.jsonl.meta.json").read_text())
    assert meta["reader"] == poo.FALLBACK_READER and meta["protocol"] == po.PO_FALLBACK
    assert poo.FALLBACK_PROTOCOL == po.PO_FALLBACK
    assert poo.NOT_MEASURABLE_REFUSAL_SHARE == po.NOT_MEASURABLE_REFUSAL_SHARE


def test_fallback_stage_needs_src(tmp_path):
    rc = main(["baseline", "kind=prompt_only_opus", "stage=fallback_readouts", f"out={tmp_path}"])
    assert rc == 2


def test_fallback_ask_resumes_on_sonnet55_and_reasks_retired_rows(tmp_path, monkeypatch):
    """A resumed fallback run counts only Sonnet 5.5 rows as done: an id a retired Sonnet 5 run
    answered is re-asked on Sonnet 5.5; an id Sonnet 5.5 answered (or refused) is not."""
    import asyncio
    from types import SimpleNamespace

    src = _src(
        tmp_path,
        "opus",
        [_p("f", "a"), _p("f", "b"), _p("f", "c")],
        [_a("f", "a", "opus a"), _a("f", "b", refused=True), _a("f", "c", refused=True)],
    )
    out = tmp_path / "fb"
    out.mkdir()
    (out / poo.FALLBACK_ANSWERS).write_text(
        json.dumps(_a("f", "b", "sonnet5 b", answerer="claude-sonnet-5"))
        + "\n"
        + json.dumps(_a("f", "c", refused=True, answerer=poo.FALLBACK_MODEL))
        + "\n"
    )
    models: list[str] = []

    class Msgs:
        async def create(self, **kw):
            models.append(kw["model"])
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="sonnet55 b")],
                stop_reason="end_turn",
                usage=SimpleNamespace(output_tokens=1, input_tokens=1),
            )

    monkeypatch.setattr(poo, "client", lambda: SimpleNamespace(messages=Msgs()))
    assert asyncio.run(poo._ask_fallback(out, [src], 4)) == 0
    assert models == ["claude-sonnet-5-5"]  # only b, and on Sonnet 5.5
    asyncio.run(poo._ask_fallback(out, [src], 4))
    assert models == ["claude-sonnet-5-5"]  # resumable: the Sonnet 5.5 rows are done
    stats = poo.write_fallback_readouts(out, [src])
    assert stats["f"]["served_by_sonnet"] == ["b"] and stats["f"]["refused_both"] == ["c"]
    rows = [json.loads(x) for x in (out / "readouts/f.jsonl").read_text().splitlines()]
    assert [(r["id"], r["samples"]) for r in rows] == [("a", ["opus a"]), ("b", ["sonnet55 b"])]


def test_retired_lang_off_floor_matches_a_live_row_without_lang(real_families):
    """summ_lang was removed (#208): live rows carry no ``lang`` key while the floors frozen
    before it carry ``lang: False`` (typo_mt's, still committed). Off and absent are one
    instrument; a labelled (``lang: True``) digest is still a different one, on either side."""
    e = json.loads(FROZEN.read_text(encoding="utf-8"))["typo_mt"]
    assert e["summarizer"].get("lang") is False
    cfg = _live_config("typo_mt", e)
    assert "lang" not in cfg["summarizer"]
    assert po.summary_floor_matches(e, cfg)
    on = {**cfg, "summarizer": {**cfg["summarizer"], "lang": True}}
    assert not po.summary_floor_matches(e, on)
    e_on = {**e, "summarizer": {**e["summarizer"], "lang": True}}
    assert not po.summary_floor_matches(e_on, cfg)
