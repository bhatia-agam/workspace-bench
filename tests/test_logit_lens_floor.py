"""Plan 0071 (logit-lens floor): the frozen logit-lens L63 floor
(``evals/baselines/logit_lens.json``): freeze checks, the entry schema, the report column beside a
matching summary row, and the committed file."""

import json
from pathlib import Path

import pytest

from wsbench.baselines import logit_lens as ll
from wsbench.baselines import prompt_only as po
from wsbench.cli import floor_columns, main, summary_floor_columns
from wsbench.judge_config import DEFAULT_JUDGE
from wsbench.results import ATI_SCOPE, FamilyResult, markdown_table, write_results

REPO = Path(__file__).resolve().parents[1]
SUMM = {"model": "claude-opus-5-5", "max_items": 10, "concurrency": 256, "timeout": 900.0}


def _spv(family: str) -> str:
    """The full stamp a live single-layer summary row of ``family`` carries (the judge's own)."""
    return ll.live_instrument(family)


def _result(family: str, pv: str, *, value: float = 0.3, **cfg_extra: object) -> FamilyResult:
    cfg: dict = {
        "judge_model": DEFAULT_JUDGE,
        "prompt_version": pv,
        "layers_judged": [63],
        "sampling": "tokens10",
        "reader": "logit_lens",
        "reads_checked": "sidecar",
        "aggregate": "summary",
        "summarizer": dict(SUMM),
        **cfg_extra,
    }
    rows = [{"id": f"i{k}", "pass": k < 3} for k in range(10)]
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
        rows=rows,
    )


def _source(tmp_path: Path, **extra: object) -> Path:
    p = tmp_path / f"run_config_{len(extra)}_{abs(hash(str(extra)))}.json"
    p.write_text(json.dumps({"protocol": ll.PROTOCOL, "model": "Qwen/Qwen3.6-27B", **extra}))
    return p


def _run(tmp_path: Path, name: str, *results: FamilyResult) -> Path:
    d = tmp_path / name
    for r in results:
        write_results(d / r.family, r)
    return d


def test_freeze_entry_schema_ati_and_source(tmp_path, real_families):
    spv = _spv("association")
    full = _run(tmp_path, "full", _result("association", spv))
    ati = _run(
        tmp_path, "ati", _result("association", spv, value=0.1, scope=ATI_SCOPE, items=["i0"])
    )
    src = _source(tmp_path, bench={"x": "y"}, junk=1)
    dst = tmp_path / "ll.json"
    got = ll.freeze(full, ati, dst, source=src)
    assert next(iter(got)) == "_source"
    s = got["_source"]
    assert (s["protocol"], s["layer"], s["k"], s["method"]) == (ll.PROTOCOL, 63, 10, "logit_lens")
    assert s["model"] == "Qwen/Qwen3.6-27B" and "junk" not in s
    e = got["association"]
    assert e["rate"] == 0.3 and e["protocol"] == ll.PROTOCOL
    assert e["instrument"] == spv and e["layers_judged"] == [63] and e["aggregate"] == "summary"
    assert e["summarizer"] == po.summarizer_key({"summarizer": SUMM})
    assert e["ati"]["rate"] == 0.1 and e["ati"]["instrument"] == spv
    assert json.loads(dst.read_text()) == got
    assert ll.floors(dst) == {"association": e}


def test_freeze_partial_src_is_refused_or_keeps_provenance(tmp_path, real_families):
    """``_source`` describes the run being frozen: a ``src`` that leaves an existing entry in
    place is refused, and with ``partial=True`` the kept entry stays under the generation record
    it was frozen with (``_source.kept_from``), through any number of partial re-freezes."""
    dst = tmp_path / "ll.json"
    a = _run(tmp_path, "a", _result("association", _spv("association")))
    ll.freeze(a, None, dst, source=_source(tmp_path, producer="p1", measured="d1"))
    b = _run(tmp_path, "b", _result("multihop_st", _spv("multihop_st")))
    before = dst.read_text()
    with pytest.raises(ValueError, match=r"does not re-measure \(association\)"):
        ll.freeze(b, None, dst, source=_source(tmp_path, measured="d2"))
    assert dst.read_text() == before
    got = ll.freeze(b, None, dst, source=_source(tmp_path, measured="d2"), partial=True)
    assert set(ll.floors(dst)) == {"association", "multihop_st"}
    # the new record is the latest run's only, never a merge with the previous run's
    assert got["_source"]["measured"] == "d2" and "producer" not in got["_source"]
    (kept,) = got["_source"]["kept_from"]
    assert kept["families"] == ["association"]
    assert (kept["source"]["producer"], kept["source"]["measured"]) == ("p1", "d1")
    c = _run(tmp_path, "c", _result("poetry", _spv("poetry")))
    got = ll.freeze(c, None, dst, source=_source(tmp_path, measured="d3"), partial=True)
    by_fam = {
        f: k["source"]["measured"] for k in got["_source"]["kept_from"] for f in k["families"]
    }
    assert by_fam == {"association": "d1", "multihop_st": "d2"}
    # a src that re-measures every entry needs no flag and leaves no kept_from
    both = _run(
        tmp_path, "all", *(_result(f, _spv(f)) for f in ("association", "multihop_st", "poetry"))
    )
    got = ll.freeze(both, None, dst, source=_source(tmp_path, measured="d4"))
    assert got["_source"]["measured"] == "d4" and "kept_from" not in got["_source"]


@pytest.mark.parametrize(
    ("override", "msg"),
    [
        ({"aggregate": None}, "not a summary-mode run"),
        ({"layers_judged": [44]}, r"not \[63\]"),
        ({"layers_judged": [20, 63]}, r"not \[63\]"),
        ({"sampling": "prose1"}, "sampling"),
        ({"limit": 3}, "subset run"),
        ({"items": ["i0"]}, "subset run"),
        ({"scope": ATI_SCOPE}, "full-bank run"),
        ({"prompt_version": "assoc-old+digest-v5"}, "re-judge first"),
        ({"reader": "jlens-public"}, "logit-lens floor needs"),
        ({"reader": None}, "logit-lens floor needs"),
        ({"reads_checked": "no_sidecar"}, "logit-lens floor needs"),
        ({"dry_run": True}, "dry run"),
    ],
)
def test_freeze_refuses(tmp_path, real_families, override, msg):
    r = _result("association", _spv("association"))
    r.config.update(override)
    with pytest.raises(ValueError, match=msg):
        ll.freeze(_run(tmp_path, "bad", r), None, tmp_path / "ll.json", source=_source(tmp_path))


def test_freeze_refuses_bad_source_and_bank_root(tmp_path, real_families, monkeypatch):
    run = _run(tmp_path, "ok", _result("association", _spv("association")))
    with pytest.raises(ValueError, match="protocol"):
        ll.freeze(run, None, tmp_path / "ll.json", source=_source(tmp_path, protocol="po-opus-v1"))
    monkeypatch.setenv("WSB_BANK_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="registered banks only"):
        ll.freeze(run, None, tmp_path / "ll.json", source=_source(tmp_path))


def test_freeze_checks_readouts_sidecar(tmp_path, real_families, monkeypatch):
    from wsbench import reads

    monkeypatch.setattr(reads, "plan_sha", lambda family: "main-sha")
    run = _run(tmp_path, "ok", _result("wrong_intermediate", _spv("wrong_intermediate")))
    ro = tmp_path / "readouts"
    ro.mkdir()
    meta = ro / "wrong_bridge.jsonl.meta.json"  # the legacy file name is accepted
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "main-sha"}))
    got = ll.freeze(run, None, tmp_path / "ll.json", source=_source(tmp_path), readouts=ro)
    assert got["wrong_intermediate"]["plan_sha"] == "main-sha"
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "old-sha"}))
    with pytest.raises(ValueError, match="plan_sha"):
        ll.freeze(run, None, tmp_path / "b.json", source=_source(tmp_path), readouts=ro)
    meta.write_text(json.dumps({"reader": "jlens-public", "plan_sha": "main-sha"}))
    with pytest.raises(ValueError, match="declares reader"):
        ll.freeze(run, None, tmp_path / "c.json", source=_source(tmp_path), readouts=ro)
    meta.unlink()
    with pytest.raises(ValueError, match="no wrong_intermediate"):
        ll.freeze(run, None, tmp_path / "d.json", source=_source(tmp_path), readouts=ro)


def test_cell_text_marks_incomplete():
    """A missing cell (no readout) and an unjudged one (a readout the judge left undecided) are
    different gaps, and the cell names each."""
    e = {"rate": 0.29, "complete": False, "counts": {"n_unjudged_cells": 1}}
    assert ll.cell_text(e) == "0.290 (incomplete: 1 unjudged)"
    e = {"rate": 0.29, "complete": False, "counts": {"n_missing_cells": 3}}
    assert ll.cell_text(e) == "0.290 (incomplete: 3 missing)"
    e = {"rate": 0.29, "complete": False, "counts": {"n_missing_cells": 3, "n_unjudged_cells": 2}}
    assert ll.cell_text(e) == "0.290 (incomplete: 3 missing, 2 unjudged)"
    assert ll.cell_text({"rate": 0.29, "complete": False, "counts": {}}) == "0.290 (incomplete)"
    assert ll.cell_text({"rate": 0.5, "complete": True}) == "0.500"


def test_freeze_keeps_an_incomplete_run_and_labels_it(tmp_path, real_families):
    """An incomplete run stays freezable (scored on its judged items): the entry says
    ``complete: false`` and its report cell names the gap."""
    r = _result("association", _spv("association"))
    r.complete = False
    r.counts.update(n_missing_cells=2, n_unjudged_cells=1)
    got = ll.freeze(_run(tmp_path, "inc", r), None, tmp_path / "ll.json", source=_source(tmp_path))
    e = got["association"]
    assert e["complete"] is False
    assert ll.cell_text(e) == "0.300 (incomplete: 2 missing, 1 unjudged)"


def test_live_instrument_is_the_judges_full_stamp(real_families):
    """The live stamp comes from the family's own judge (a dry run, no call), so it carries the
    segments no prefix rule knows: the registered base alone is not the instrument."""
    live = ll.live_instrument("conjunctive_association")
    assert live == "comp-v6+bank-v6+maj+digest-v5-task-extractive+sj-v10"
    cfg = ll.live_config("conjunctive_association")
    assert cfg["aggregate"] == "summary" and cfg["layers_judged"] == [63]
    assert cfg["sampling"] == "tokens10" and cfg["dry_run"] is True


@pytest.mark.parametrize(
    "stale",
    [
        "comp-v6+bank-v6+maj-noinv+digest-v5-task-extractive+sj-v10",  # the retired rule
        "comp-v6+bank-v6+digest-v5-task-extractive+sj-v10",  # the base, no rule segment
        "comp-v6+bank-v6+maj+digest-v5-task-extractive-layered-v1x4+sj-v10",  # another digest tail
    ],
)
def test_freeze_refuses_a_stale_middle_segment(tmp_path, real_families, stale):
    """Regression (review of the 2026-11-17 port): the guard compared only the stamp's base
    prefix and digest tail, so a run on conjunctive_association's retired ``+maj-noinv`` rule
    froze. The FULL live stamp is compared; the same run on the live stamp freezes."""
    fam = "conjunctive_association"
    assert stale.startswith(f"{po.instrument_versions()[fam]}+")  # the old rule let it through
    bad = _run(tmp_path, "bad", _result(fam, stale))
    with pytest.raises(ValueError, match="re-judge first"):
        ll.freeze(bad, None, tmp_path / "ll.json", source=_source(tmp_path))
    ok = _run(tmp_path, "ok", _result(fam, _spv(fam)))
    assert fam in ll.freeze(ok, None, tmp_path / "ll.json", source=_source(tmp_path))
    # the ATI run is held to the same full stamp
    ati = _run(tmp_path, "ati", _result(fam, stale, scope=ATI_SCOPE, items=["i0"]))
    with pytest.raises(ValueError, match="re-judge first"):
        ll.freeze(ok, ati, tmp_path / "ll.json", source=_source(tmp_path))


def test_freeze_refuses_ati_without_scope_or_entry(tmp_path, real_families):
    spv = _spv("association")
    full = _run(tmp_path, "full", _result("association", spv))
    src = _source(tmp_path)
    with pytest.raises(ValueError, match="anti_text_inversion"):
        a = _run(tmp_path, "ati", _result("association", spv))
        ll.freeze(full, a, tmp_path / "a.json", source=src)
    ati = _run(tmp_path, "ati2", _result("multihop_st", _spv("multihop_st"), scope=ATI_SCOPE))
    with pytest.raises(ValueError, match="no full-bank entry"):
        ll.freeze(full, ati, tmp_path / "b.json", source=src)


def test_report_column_matches_summary_rows(tmp_path, monkeypatch, real_families):
    spv = _spv("association")
    dst = tmp_path / "ll.json"
    ll.freeze(
        _run(tmp_path, "full", _result("association", spv, value=0.25)),
        None,
        dst,
        source=_source(tmp_path),
    )
    monkeypatch.setattr(ll, "FROZEN", dst)
    native = floor_columns()
    assert native[ll.COLUMN] == {}  # summary-mode only: no native cell
    summ = summary_floor_columns()
    entry, text = summ[ll.COLUMN]["association"]
    assert text == "0.250" and ll.floor_applies(entry, _result("association", spv).config)
    row = _result("association", spv, value=0.5)
    other = _result("association", spv, value=0.5)
    other.config["summarizer"] = {**SUMM, "max_items": 20}  # another digest setting
    md = markdown_table([row], None, floors=native, summary_floors=summ)
    assert f"| {ll.COLUMN} |" in md.splitlines()[0] and "0.250" in md
    md2 = markdown_table([other], None, floors=native, summary_floors=summ)
    assert "0.250" not in md2


def test_freeze_cli(tmp_path, real_families, monkeypatch, capsys):
    from wsbench import reads

    monkeypatch.setattr(reads, "plan_sha", lambda family: "s")
    full = _run(tmp_path, "full", _result("association", _spv("association")))
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "association.jsonl.meta.json").write_text(
        json.dumps({"reader": "logit_lens", "plan_sha": "s"})
    )
    dst = tmp_path / "ll.json"
    args = ["freeze", "kind=logit_lens", f"src={full}", f"dst={dst}", f"readouts={ro}"]
    assert main(args) == 2  # source= is required
    assert "needs src=" in capsys.readouterr().err
    assert main([*args, f"source={_source(tmp_path)}"]) == 0
    assert "association" in ll.floors(dst)
    monkeypatch.setenv("WSB_BANK_ROOT", str(tmp_path))
    assert main([*args, f"source={_source(tmp_path)}"]) == 2
    assert "registered banks only" in capsys.readouterr().err


def test_committed_floor_file():
    got = json.loads(ll.FROZEN.read_text(encoding="utf-8"))
    s = got["_source"]
    assert (s["protocol"], s["layer"], s["k"]) == (ll.PROTOCOL, 63, 10)
    fams = {f for f in got if not f.startswith("_")}
    assert len(fams) == 29 and "jlens_concept_pr" not in fams
    for f in fams:
        e = got[f]
        assert e["layers_judged"] == [63] and e["aggregate"] == "summary", f
        assert e["protocol"] == ll.PROTOCOL and e["rate"] is not None, f
        assert len(e["plan_sha"]) == 64, f


def test_report_hides_column_when_no_row_draws_it(tmp_path, monkeypatch, real_families):
    spv = _spv("association")
    dst = tmp_path / "ll.json"
    ll.freeze(_run(tmp_path, "f", _result("association", spv, value=0.25)), None, dst,
              source=_source(tmp_path))  # fmt: skip
    monkeypatch.setattr(ll, "FROZEN", dst)
    match = _run(tmp_path, "match", _result("association", spv, value=0.5))
    assert main(["report", f"dir={match}"]) == 0
    assert f"| {ll.COLUMN} |" in (match / "summary.md").read_text()
    row = _result("association", spv, value=0.5)
    row.config["summarizer"] = {**SUMM, "max_items": 20}
    other = _run(tmp_path, "other", row)
    assert main(["report", f"dir={other}"]) == 0
    assert ll.COLUMN not in (other / "summary.md").read_text()


def test_freeze_accepts_a_recorded_drop_only_plan_lineage(tmp_path, real_families, monkeypatch):
    """Readouts of an older plan are accepted exactly as the judge accepts them (reads guard iii):
    through the registered bank's recorded drop-only ``plan_lineage`` (plan 0083, arithmetic bank
    v1 -> v2). The entry records main's plan; with no recorded chain the freeze still refuses."""
    from wsbench import reads

    fam = "arithmetic_intermediates"
    monkeypatch.setattr(reads, "plan_sha", lambda family: "main-sha")
    asked: list[tuple[str, str, str]] = []

    def drops(family: str, have: str, want: str) -> list[str] | None:
        asked.append((family, have, want))
        return ["dropped-id"] if have == "v1-sha" else None

    monkeypatch.setattr(reads, "lineage_drops", drops)
    step = {"from": "v1-sha", "to": "main-sha", "n_dropped_items": 1, "n_dropped_cells": 0}
    run = _run(tmp_path, "ok", _result(fam, _spv(fam), plan_lineage=step))
    ro = tmp_path / "readouts"
    ro.mkdir()
    meta = ro / f"{fam}.jsonl.meta.json"
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "v1-sha"}))
    got = ll.freeze(run, None, tmp_path / "ll.json", source=_source(tmp_path), readouts=ro)
    assert got[fam]["plan_sha"] == "main-sha"
    assert asked == [(fam, "v1-sha", "main-sha")]
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "other-sha"}))
    with pytest.raises(ValueError, match="plan_sha"):
        ll.freeze(run, None, tmp_path / "b.json", source=_source(tmp_path), readouts=ro)
    # the judged run itself must record the accepted step (reads guard iii writes it): a run
    # with no record, or judged from another plan or onto another plan, is not these readouts'
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "v1-sha"}))
    for i, lineage in enumerate(
        (None, {**step, "from": "v0-sha"}, {**step, "to": "older-main-sha"})
    ):
        cfg = {} if lineage is None else {"plan_lineage": lineage}
        other = _run(tmp_path, f"other{i}", _result(fam, _spv(fam), **cfg))
        with pytest.raises(ValueError, match="not judged from these readouts"):
            ll.freeze(other, None, tmp_path / "c.json", source=_source(tmp_path), readouts=ro)
    # and a run that went through a lineage does not belong to readouts already on main's plan
    meta.write_text(json.dumps({"reader": "logitlens-L63", "plan_sha": "main-sha"}))
    with pytest.raises(ValueError, match="judged through a plan lineage"):
        ll.freeze(run, None, tmp_path / "d.json", source=_source(tmp_path), readouts=ro)


_COMMITTED = sorted(k for k in json.loads(ll.FROZEN.read_text(encoding="utf-8")) if k[0] != "_")


@pytest.mark.parametrize("family", _COMMITTED)
def test_every_committed_entry_matches_its_live_row(family, real_families):
    """Every committed logit-lens entry is on the instrument a live single-layer summary row of
    its family carries on this branch, so ``report`` draws it and ``freeze`` would accept it (the
    prompt-only twin is ``test_po_floors_r3.test_every_committed_floor_matches_its_live_row``).
    The live row is the family's own judge, dry-run (:func:`logit_lens.live_config`), so the
    WHOLE stamp is compared (base, every family segment, bank tag, digest tail), with the digest
    settings and the judge model; the key is registered and not superseded. A family whose
    instrument or digest moves must be re-judged and re-frozen in the same PR."""
    from wsbench import registry

    e = json.loads(ll.FROZEN.read_text(encoding="utf-8"))[family]
    assert family in registry.FAMILIES, f"{family}: not a registered family key (renamed?)"
    spec = registry.get(family)
    assert not spec.superseded_by, family
    cfg = ll.live_config(family)
    assert e["instrument"] == ll.live_instrument(family), family
    assert e["judge_model"] == cfg["judge_model"], family
    assert ll.floor_applies(e, cfg), (family, e["summarizer"], cfg.get("summarizer"))
    if "ati" in e:
        assert e["ati"]["instrument"] == e["instrument"], family


# two plans render from pinned network sources the test suite replaces with synthetic text
# (conftest ``_offline_nyt`` / ``_offline_nocot``), so their committed shas cannot be re-derived
_NETWORK_PLANS = ("nyt_connections", "knowledge_cutoff")


@pytest.mark.parametrize("family", [f for f in _COMMITTED if f not in _NETWORK_PLANS])
def test_every_committed_entry_is_on_the_registered_plan(family, real_families):
    """Every committed entry was scored on the registered bank's current read plan (its item
    set and read positions): a bank that gains, loses or changes an item moves ``plan_sha``."""
    from wsbench import reads

    e = json.loads(ll.FROZEN.read_text(encoding="utf-8"))[family]
    assert e["plan_sha"] == reads.plan_sha(family), family


def _adapted_like(family: str, **cfg: object) -> FamilyResult:
    return _result(family, _spv(family), value=0.5, **cfg)


def test_floor_is_not_drawn_beside_an_adapted_subject(tmp_path, monkeypatch, real_families):
    """The floor is Qwen3.6-27B's own final-layer activations, so it is never drawn beside
    another subject's row, even one whose stamp, digest settings and judge model equal the
    entry's (a real case: an adapted arithmetic_intermediates row carries the registered stamp
    byte for byte). The signals are ``$WSB_BANK_ROOT`` at report time, the row's
    ``config.bank_root`` and a re-stamped row's ``config.registered_prompt_version``. The
    prompt-only floor beside the same rows is unchanged."""
    fam = "association"
    spv = _spv(fam)
    dst = tmp_path / "ll.json"
    ll.freeze(_run(tmp_path, "f", _result(fam, spv, value=0.25)), None, dst,
              source=_source(tmp_path))  # fmt: skip
    monkeypatch.setattr(ll, "FROZEN", dst)
    entry = ll.floors(dst)[fam]
    registered = _result(fam, spv, value=0.5)
    rooted = _adapted_like(fam, bank_root="deepseek-v4-flash")
    restamped = _adapted_like(fam, registered_prompt_version=spv)
    restamped.config["prompt_version"] = spv.replace("+bank-v5", "+bank-v9")
    assert ll.floor_applies(entry, registered.config)
    for row in (rooted, restamped):
        assert not ll.floor_applies(entry, row.config)
    # prompt-only's own rule is untouched: the same entry matches all three rows
    for row in (registered, rooted, restamped):
        assert po.summary_floor_applies(entry, row.config)
    # the report: a registered row draws the column, an adapted-stamped row hides it
    reg_dir = _run(tmp_path, "reg", registered)
    assert main(["report", f"dir={reg_dir}"]) == 0
    assert f"| {ll.COLUMN} |" in (reg_dir / "summary.md").read_text()
    for name, row in (("rooted", rooted), ("restamped", restamped)):
        d = _run(tmp_path, name, row)
        assert main(["report", f"dir={d}"]) == 0
        assert ll.COLUMN not in (d / "summary.md").read_text(), name
    # a mixed table keeps the column for the registered row and shows a dash for the other
    md = markdown_table(
        [registered, _adapted_like("multihop_st", bank_root="kimi-k3")],
        None,
        floors=floor_columns(),
        summary_floors={
            **summary_floor_columns(),
            ll.COLUMN: {fam: (entry, "0.250"), "multihop_st": ({**entry}, "0.111")},
        },
    )
    assert "0.250" in md and "0.111" not in md
    # $WSB_BANK_ROOT at report time: no column at all, whatever the rows say
    monkeypatch.setenv("WSB_BANK_ROOT", str(REPO / "adapted" / "deepseek-v4-flash"))
    assert ll.COLUMN not in floor_columns() and ll.COLUMN not in summary_floor_columns()
    assert not ll.floor_applies(entry, registered.config)
    assert main(["report", f"dir={reg_dir}"]) == 0
    assert ll.COLUMN not in (reg_dir / "summary.md").read_text()


def test_adapted_runs_record_their_bank_root(monkeypatch):
    """``runner.stamp_adapted_bank`` records the root's directory name on every result judged
    under ``$WSB_BANK_ROOT`` (and nothing without one), the row-level signal
    ``on_registered_bank`` reads."""
    from wsbench import runner

    r = _result("association", "x+digest-v5-task-extractive+sj-v10")
    runner.stamp_adapted_bank("association", r)
    assert "bank_root" not in r.config and ll.on_registered_bank(r.config)
    monkeypatch.setenv("WSB_BANK_ROOT", "adapted/deepseek-v4-flash")
    runner.stamp_adapted_bank("association", r)
    assert r.config["bank_root"] == "deepseek-v4-flash"
    monkeypatch.delenv("WSB_BANK_ROOT")
    assert not ll.on_registered_bank(r.config)
