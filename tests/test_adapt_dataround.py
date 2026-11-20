"""Plan 0091: plan 0075's data-round rules as ``adapt dataround`` (offline: fixture sets, fake
lucky-guessing measurements, a fake ``stream_json``), and the ``adapt_set.sh`` / ``gated_merge.sh``
drivers (DRY_RUN, a stub ``gh``)."""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from wsbench.adapt import __main__ as cli
from wsbench.adapt import dataround as dr
from wsbench.adapt import refill as rf
from wsbench.adapt import run, store

M = "some-new-subject"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda model, root=None: tmp_path / "adapted" / model)
    monkeypatch.setattr(store, "code_stamp", lambda: {})
    d = tmp_path / "adapted" / M
    d.mkdir(parents=True)
    return d


def _bank(d: Path, family: str, items: list[dict]) -> None:
    (d / f"{family}.json").write_text(json.dumps({"family": family, "items": items}))


def _report(d: Path, **kw) -> None:
    (d / "report.json").write_text(json.dumps(kw))


def _measure(run_dir: Path, family: str, hits: dict[str, dict[str, int]], chance: float = 0.125,
             variants=("blind", "described")) -> None:  # fmt: skip
    """A lucky-guessing out dir: ``hits[id][guesser]`` correct draws of 5."""
    fd = run_dir / family
    fd.mkdir(parents=True, exist_ok=True)
    for v in variants:
        per = {i: {"draws": [{"correct": k < h.get(v, 0)} for k in range(5)]}
               for i, h in hits.items()}  # fmt: skip
        (fd / f"{v}.json").write_text(json.dumps({"analytic_floor": chance, "per_item": per}))


def _items(n: int, prefix: str = "a") -> list[dict]:
    return [{"id": f"{prefix}{i}"} for i in range(n)]


# ---------------------------------------------------------------- D1-D3
def _leaky_family(mdir: Path, tmp_path: Path, family: str = "association"):
    """10 items, two leakers that push blind over chance + 5 (9/50 = 0.18 > 0.175)."""
    _bank(mdir, family, _items(10))
    _report(mdir, families={})
    hits = {f"a{i}": {} for i in range(10)}
    hits["a0"] = {"blind": 5, "described": 5}  # D3 10/10
    hits["a1"] = {"blind": 4, "described": 1}  # D1-D2: the failing blind guesser >= 3/5
    return hits


def test_a_single_run_flag_is_pending_not_dropped(mdir, tmp_path):
    hits = _leaky_family(mdir, tmp_path)
    out = tmp_path / "out"
    _measure(out / "c1_1", "association", hits)
    d = dr.decide(M, "association", out / "c1_1" / "association", out)
    assert d["drop_ids"] == [] and set(d["pending"]) == {"a0", "a1"}
    assert d["rates_before"]["blind"] > d["bar"]


def test_a_flag_in_two_separate_runs_drops_and_rates_recompute(mdir, tmp_path):
    hits = _leaky_family(mdir, tmp_path)
    out = tmp_path / "out"
    _measure(out / "c1_1", "association", hits)
    _measure(out / "c1_2", "association", hits)
    d = dr.decide(M, "association", out / "c1_2" / "association", out)
    assert d["drop_ids"] == ["a0", "a1"]
    assert d["drops"]["a0"]["rule"] == "d3_10of10" and d["drops"]["a0"]["prior_runs"] == ["c1_1"]
    assert d["still_failing"] == [] and d["rates_after"]["blind"] == 0.0


def test_a_leaker_below_the_family_bar_is_not_flagged(mdir, tmp_path):
    """D1-D2 needs a guesser that FAILS the family bar; D3 (10/10) holds whatever the rate."""
    _bank(mdir, "association", _items(100))
    _report(mdir)
    hits = {f"a{i}": {} for i in range(100)}
    hits["a1"] = {"blind": 4, "described": 1}  # blind 4/500 = 0.008 << 0.175: not a leaker
    out = tmp_path / "out"
    for r in ("c1_1", "c1_2"):
        _measure(out / r, "association", hits)
    assert dr.decide(M, "association", out / "c1_2" / "association", out)["drop_ids"] == []


def test_only_cycle_runs_confirm(mdir, tmp_path):
    """A report-only or ad hoc run (not c* / final*) never confirms a drop, a symlinked copy of
    the current run neither."""
    hits = _leaky_family(mdir, tmp_path)
    out = tmp_path / "out"
    _measure(out / "debug_run", "association", hits)
    _measure(out / "c2_1", "association", hits)
    (out / "c2_copy").symlink_to(out / "c2_1")
    assert dr.decide(M, "association", out / "c2_1" / "association", out)["drop_ids"] == []
    hist = dr.history(out, "association", out / "c2_1", ("*",))
    assert set(hist["a0"]) == {"debug_run"}  # an explicit history= pattern opts a run in


def test_dropped_ids_are_out_of_scope(mdir, tmp_path):
    hits = _leaky_family(mdir, tmp_path)
    _report(mdir, drops={"association": {"a0": "earlier"}})
    out = tmp_path / "out"
    for r in ("c1_1", "c1_2"):
        _measure(out / r, "association", hits)
    d = dr.decide(M, "association", out / "c1_2" / "association", out)
    assert d["n_shipped"] == 9 and d["drop_ids"] == []  # a1 alone: blind 4/45 is under the bar


def test_blind_only_family(mdir, tmp_path):
    _bank(mdir, "poetry", _items(3))
    _report(mdir)
    out = tmp_path / "out"
    hits = {"a0": {"blind": 4}, "a1": {"blind": 3}, "a2": {}}
    for r in ("c1_1", "c1_2"):
        _measure(out / r, "poetry", hits, chance=0.25, variants=("blind",))
    d = dr.decide(M, "poetry", out / "c1_2" / "poetry", out)
    assert d["blind_only"] and d["drop_ids"] == ["a0"]


def test_role_bound_drops_take_both_twins():
    assert dr.twins("role_bound_association", {"rb-x-ab"}) == ["rb-x-ab", "rb-x-ba"]
    assert dr.twins("association", {"x-ab"}) == ["x-ab"]


def test_leakers_writes_and_applies(mdir, tmp_path, monkeypatch):
    hits = _leaky_family(mdir, tmp_path)
    out = tmp_path / "out"
    for r in ("c1_1", "c1_2"):
        _measure(out / r, "association", hits)
    seen = []
    monkeypatch.setattr(run, "drop", lambda m, f, ids, reason: seen.append((f, ids, reason)))
    dr.leakers(M, out / "c1_2", apply=True)
    assert seen == [("association", ["a0", "a1"], seen[0][2])] and "c1_1" in seen[0][2]
    assert json.loads((out / "c1_2" / "leakers.json").read_text())["association"]["drop_ids"]
    seen.clear()
    dr.leakers(M, out / "c1_2", apply=False)  # dry: prints the commands, drops nothing
    assert seen == []


# ---------------------------------------------------------------- D4-D7
def test_capital_screen(mdir):
    _bank(mdir, "multihop_st", [
        {"id": "m1", "prompt": "The army that captured the Byzantine capital ..."},
        {"id": "m2", "prompt": "a capital gains tax on shares"},
        {"id": "m3", "prompt": "Il a visité la capitale du pays"},
        {"id": "m4", "prompt": "A trip through London"},
    ])  # fmt: skip
    _bank(mdir, "typo", [{"id": "tyh-real-gastronomy", "prompt": "the capital of taste"}])
    _bank(mdir, "user_modeling", [{"name": "u1", "messages": "[{'role': 'user', 'content': "
                                   "'I live in the capital'}]"}])  # fmt: skip
    _report(mdir)
    hits = dr.capital_hits(M)
    assert [i for i, _ in hits["multihop_st"]] == ["m1", "m3"]
    assert "typo" not in hits and [i for i, _ in hits["user_modeling"]] == ["u1"]


def test_class_caps_drop_the_newest_rows(mdir):
    items = [{"name": f"o{i}", "attr_class": "Occupation"} for i in range(6)]
    items += [{"name": "g-orig", "attr_class": "Gender"}]
    items += [{"name": f"g{w}", "attr_class": "Gender", "adapt": {"origin": "authored", "wave": w}}
              for w in (1, 2, 3)]  # fmt: skip
    _bank(mdir, "user_modeling", items)
    _report(mdir)
    caps = dr.class_caps(M)  # Gender 4/10: 2/8 is still 25%, so 3 leave (1/7); the original stays
    assert caps["Gender"]["ids"] == ["g1", "g2", "g3"] and caps["Gender"]["after"] == "1/7"
    assert "Country" not in caps


def test_class_caps_recheck_after_the_other_cap(mdir):
    """Country at the cap, Gender over it: Gender's drops shrink the family, so Country is
    re-capped (20/100 would end at 20/87 = 23% after a single pass)."""
    items = [{"name": f"c{i}", "attr_class": "Country"} for i in range(20)]
    items += [{"name": f"g{i}", "attr_class": "Gender"} for i in range(30)]
    items += [{"name": f"o{i}", "attr_class": "Occupation"} for i in range(50)]
    _bank(mdir, "user_modeling", items)
    _report(mdir)
    caps = dr.class_caps(M)
    n_after = 100 - len(caps["Country"]["ids"]) - len(caps["Gender"]["ids"])
    for c in ("Country", "Gender"):
        left = int(caps[c]["after"].split("/")[0])
        assert left <= 0.2 * n_after and caps[c]["after"].endswith(f"/{n_after}")


def test_role_bound_and_suffixed_keys_end_to_end(mdir, tmp_path):
    """Per-item keys may carry a ``#<list>`` suffix; role_bound drops take both twins."""
    items = [{"id": f"rb{i}-{t}"} for i in range(5) for t in ("ab", "ba")]
    _bank(mdir, "role_bound_association", items)
    _report(mdir)
    hits = {f"rb{i}-ab#0": {} for i in range(5)}
    hits["rb0-ab#0"] = {"blind": 5, "described": 5}
    out = tmp_path / "out"
    for r in ("c1_1", "c1_2"):
        _measure(out / r, "role_bound_association", hits)
    d = dr.decide(M, "role_bound_association", out / "c1_2" / "role_bound_association", out)
    assert d["drop_ids"] == ["rb0-ab", "rb0-ba"]


def _fake_stream(answer):
    def stream(prompts, *, schema, model, on_result, concurrency):
        for i, (_s, u) in enumerate(prompts):
            on_result(i, answer(u))

    return stream


def test_llm_screens_are_cached_and_keep_firstname(mdir, tmp_path, monkeypatch):
    _bank(mdir, "multihop_st", [{"id": "mh-a", "prompt": "Q1", "target": "x"},
                             {"id": "mh-firstname-b", "prompt": "Q2", "target": "y"}])  # fmt: skip
    _bank(mdir, "user_modeling", [
        {"name": "u1", "attr_class": "Country", "attr": "Japan",
         "messages": [{"role": "user", "content": "near Tokyo"}]},
        {"name": "u2", "attr_class": "Country", "attr": "Japan",
         "messages": [{"role": "user", "content": "Mount Fuji"}]},
    ])  # fmt: skip
    _report(mdir)
    monkeypatch.setattr(dr, "_schema", lambda *a: {})
    calls = []

    def answer(u):
        calls.append(u)
        if u.startswith("Question"):
            return {"shortcut": True, "why": "direct"}
        return {"places": [], "in_gold_country": "Tokyo" in u or "Fuji" in u}

    seen = []
    monkeypatch.setattr(run, "drop", lambda m, f, ids, reason: seen.append((f, ids)))
    out = tmp_path / "scr"
    rep = dr.screens(M, out, apply=True, only=("d4", "d6"), stream=_fake_stream(answer))
    assert [i for i, _ in rep["d4"]["multihop_st"]] == ["mh-a"]
    assert [i for i, _ in rep["d6"]["d6"]] == ["u1", "u2"] and rep["d6"]["d6b"] == []
    assert ("multihop_st", ["mh-a"]) in seen and ("user_modeling", ["u1", "u2"]) in seen
    n = len(calls)
    dr.screens(M, out, only=("d4", "d6"), stream=_fake_stream(answer))
    assert len(calls) == n  # every text cached


def test_screens_refuse_an_unknown_screen(mdir, tmp_path):
    with pytest.raises(SystemExit):
        dr.screens(M, tmp_path, only=("d9",))


# ---------------------------------------------------------------- short / counts
def test_short_sorts_refill_max_waves_and_objective_stops(mdir):
    _report(mdir, families={
        "association": {"n_items": 90, "target": 100, "status": "partial",
                        "refill": {"stop": "max waves (16)"}},
        "multihop_st": {"n_items": 95, "target": 100, "status": "full",
                     "refill": {"stop": "100 >= target 100"}},  # full, then audit drops
        "wrong_intermediate": {"n_items": 30, "target": 100, "status": "partial",
                               "refill": {"stop": "pool exhausted"}},
        "knowledge_cutoff": {"n_items": 3, "target": 108, "status": "ooc"},
        "buggy_code": {"n_pairs": 20, "target_pairs": 24, "status": "partial",
                       "refill": {"stop": "low yield above half: yield 1/60 < 0.03"}},
        "nyt_connections": {"n_items": 10, "target": 300, "status": "partial"},  # no route
        "typo": {"n_items": 100, "target": 100, "status": "full"},
    })  # fmt: skip
    s = dr.short(M)
    assert s == {"refill": ["association", "multihop_st"], "max_waves": ["association"],
                 "final": ["buggy_code", "knowledge_cutoff", "wrong_intermediate"]}  # fmt: skip
    c = dr.counts(M)
    assert c["families"]["buggy_code"] == 20 and c["drops"] == 0


def test_the_stop_strings_short_reads_still_exist():
    """``short`` matches refill's stop wording; a rewording must update both."""
    src = (REPO / "src/wsbench/adapt/refill.py").read_text()
    runsrc = (REPO / "src/wsbench/adapt/run.py").read_text()
    assert 'f"max waves ({waves})"' in src and 'f"max waves ({max_waves})"' in runsrc
    for s in ("pool exhausted", "yield", "crash cap"):
        assert s in src
    assert "ladder exhausted" in runsrc
    assert set(dr.REFILL_ROUTES) >= set(rf.FILL_POLICY) | set(rf.POLICY)


def test_cli_keys_and_stages(mdir, capsys):
    with pytest.raises(SystemExit, match="unknown argument"):
        cli.main(["dataround", f"model={M}", "stage=short", "bogus=1"])
    with pytest.raises(SystemExit, match="run="):
        cli.main(["dataround", f"model={M}", "stage=leakers"])
    _report(mdir, families={})
    cli.main(["dataround", f"model={M}", "stage=short"])
    assert json.loads(capsys.readouterr().out) == {"refill": [], "max_waves": [], "final": []}


# ---------------------------------------------------------------- drivers
def _dry(tmp_path, *args, **env):
    e = {**os.environ, "DRY_RUN": "1", **env}
    e.pop("ANTHROPIC_API_KEY", None)
    return subprocess.run(["bash", str(REPO / "scripts/adapt_set.sh"), *args], cwd=tmp_path,
                          env=e, capture_output=True, text=True)  # fmt: skip


def test_adapt_set_build_and_refill_dry(tmp_path):
    r = _dry(tmp_path, M, "build")
    assert r.returncode != 0 and "NATIVE_LANGS" in r.stderr  # the lab decision is required
    r = _dry(tmp_path, M, "build", NATIVE_LANGS="en", NATIVE_EVIDENCE="lab decision",
             WI_POOLS="/p/a,/p/b", MORAL_VARIANT="system_one_word")  # fmt: skip
    steps = [x.split(":")[0] for x in r.stdout.splitlines() if x.startswith("STEP ")]
    assert steps[:2] == ["STEP native_langs", "STEP profile"] and "STEP wrong_intermediate" in steps
    assert "variant=system_one_word" in r.stdout and "pool=/p/a,/p/b" in r.stdout
    r = _dry(tmp_path, M, "refill", DRY_SHORT='{"refill": ["multihop"], '
             '"max_waves": ["multihop"], "final": []}')  # fmt: skip
    assert "families=multihop waves=40" in r.stdout and r.stdout.rstrip().endswith("REFILL DONE")


def test_adapt_set_loop_dry_backfills_and_converges(tmp_path):
    r = _dry(tmp_path, M, "loop", "3", "5",
             DRY_SHORT='{"refill": ["poetry", "user_modeling", "basic_readout_st"], '
                       '"max_waves": [], "final": []}',
             DRY_LUCKY='{"both": ["association"], "blind_only": ["poetry"]}')  # fmt: skip
    out = r.stdout
    assert r.returncode == 0, r.stderr
    assert "ADAPT_FILL_TIERS=poetry=v6" in out and "wave=331" in out and "stage=subject" in out
    assert "onecue" in out and "stage=screens" in out and "variant=blind draws=5" in out
    assert "stage=leakers run=outputs/adapt/some-new-subject/c3_2" in out
    assert "CONVERGED at 3" in out and "c4-" not in out  # nothing landed, nothing dropped


def test_adapt_set_refuses_an_api_key(tmp_path):
    e = {**os.environ, "ANTHROPIC_API_KEY": "x"}
    e.pop("DRY_RUN", None)
    r = subprocess.run(["bash", str(REPO / "scripts/adapt_set.sh"), M, "status"], cwd=tmp_path,
                       env=e, capture_output=True, text=True)  # fmt: skip
    assert r.returncode == 2 and "ANTHROPIC_API_KEY" in r.stderr


def _gh_stub(tmp_path: Path, n_checks: int, watch_rc: int, green: str) -> dict:
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "gh.log"
    gh = bin_ / "gh"
    gh.write_text(f"""#!/usr/bin/env bash
echo "$*" >> {log}
case "$*" in
  *"--json name"*) echo {n_checks};;
  *--watch*) exit {watch_rc};;
  *"--json bucket"*) echo {green};;
  *"pr view"*) echo {"a" * 40};;
  *"pr merge"*) case "$*" in *"--match-head-commit {"a" * 40}"*) exit 0;; *) exit 9;; esac;;
esac
""")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "GATED_MERGE_WAIT": "0"}


@pytest.mark.parametrize(("n", "watch", "green", "rc", "merged"), [
    (0, 0, "true", 2, False),  # no checks: refuse
    (3, 1, "false", 1, False),  # a failing check
    (3, 0, "false", 1, False),  # watch passed but a bucket is not pass / skipping
    (3, 0, "true", 0, True),
])  # fmt: skip
def test_gated_merge_fails_closed(tmp_path, n, watch, green, rc, merged):
    env = _gh_stub(tmp_path, n, watch, green)
    r = subprocess.run(["bash", str(REPO / "scripts/gated_merge.sh"), "123"], env=env,
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode == rc, r.stdout
    assert ("pr merge" in (tmp_path / "gh.log").read_text()) is merged
