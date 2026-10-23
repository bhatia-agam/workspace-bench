"""Anti-text-inversion gate and flag: item adapter, gate rules, scope lookup, readout write policy,
and the ``anti_text_inversion=True`` plumbing (offline)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from wsbench import llm, mcjudge, readplan, registry
from wsbench.baselines import text_inversion as ti
from wsbench.cli import main
from wsbench.judge_config import JudgeConfig
from wsbench.registry import EvalSpec, JudgeArgs, register
from wsbench.results import FamilyResult, macro


def _results(path: Path, family: str, rows: list[dict], value: float | None, **cfg) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    d = {
        "family": family,
        "config": {"prompt_version": "v1", "judge_model": "claude-opus-5-5", **cfg},
        "numbers": {"metric": "score" if family == "buggy_code" else "pass_rate", "value": value},
        "rows": rows,
    }
    (path / "results.json").write_text(json.dumps(d))
    return path / "results.json"


def _answers(out: Path, d: int, rows: list[tuple[str, str, str]]) -> None:
    """(family, id, status) with status ok | refusal | error."""
    (out / "answers").mkdir(parents=True, exist_ok=True)
    with (out / "answers" / f"draw{d}.jsonl").open("w") as fh:
        for fam, i, st in rows:
            r = {"family": fam, "id": i, "draw": d, "answer": "text" if st == "ok" else ""}
            r["error"] = {"ok": "", "refusal": "refusal", "error": "boom"}[st]
            if st == "refusal":
                r["refused"] = True
            fh.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------- item adapter


def test_draw_verdicts_any_pass_wins_undecided_beats_fail(tmp_path):
    rows = [
        {"id": "a", "pass": False},
        {"id": "a", "pass": True},  # any cell passes -> item passes
        {"id": "b", "pass": False},
        {"id": "b", "pass": None},  # no pass, one undecided -> undecided
        {"id": "c", "pass": False},
    ]
    p = _results(tmp_path / "r", "fam", rows, value=0.5)  # decided: a True, c False
    assert ti.draw_verdicts(p) == {"a": True, "b": None, "c": False}


def test_draw_verdicts_drift_guard_and_missing_pass(tmp_path):
    p = _results(tmp_path / "r", "fam", [{"id": "a", "pass": True}], value=0.0)
    with pytest.raises(ValueError, match="adapter rate"):
        ti.draw_verdicts(p)
    p = _results(tmp_path / "s", "fam", [{"id": "a", "correct": True}], value=1.0)
    with pytest.raises(ValueError, match="no 'pass'"):
        ti.draw_verdicts(p)


def test_draw_verdicts_buggy_threshold(tmp_path):
    rows = [
        {"id": "a", "score": ti.BUGGY_PASS_SCORE, "judged": True},
        {"id": "b", "score": ti.BUGGY_PASS_SCORE - 1, "judged": True},
        {"id": "c", "score": None, "judged": False},
    ]
    p = _results(tmp_path / "r", "buggy_code", rows, value=5.5)
    assert ti.draw_verdicts(p) == {"a": True, "b": False, "c": None}


# ---------------------------------------------------------------- gate


@pytest.fixture
def two_families(monkeypatch):
    monkeypatch.setattr(ti, "gated_families", lambda: ["fam", "refused"])
    ids = {"fam": ["a", "b", "c", "d", "e"], "refused": ["x", "y"]}
    monkeypatch.setattr(readplan, "plan", lambda f: [SimpleNamespace(id=i) for i in ids[f]])
    monkeypatch.setattr(
        registry, "get", lambda f: SimpleNamespace(judge=SimpleNamespace(prompt_version="v1"))
    )
    monkeypatch.setattr(registry, "load_all", lambda: None)


def test_gate_outcomes_and_refusal_rule(tmp_path, two_families):
    out = tmp_path / "o"
    for d in range(3):
        _answers(
            out,
            d,
            [
                ("fam", "a", "ok"),
                ("fam", "b", "ok"),
                ("fam", "c", "ok"),
                ("fam", "d", "error" if d == 1 else "ok"),
                ("fam", "e", "ok"),
                ("refused", "x", "refusal"),
                ("refused", "y", "ok"),
            ],
        )
        # a fails every draw (ATI); b passes draw 2 (invertible); c undecided once (unverified);
        # d has no answer in draw 1 and the judge called the missing cell a fail (unverified);
        # e fails every draw (ATI)
        rows = [
            {"id": "a", "pass": False},
            {"id": "b", "pass": d == 2},
            {"id": "c", "pass": None if d == 0 else False},
            {"id": "d", "pass": False},
            {"id": "e", "pass": False},
        ]
        value = 1 / 5 if d == 2 else 0.0
        _results(out / "judged" / f"draw{d}" / "fam", "fam", rows, value)
    dst = tmp_path / "ati.json"
    frozen = ti.gate(out, dst=dst)
    e = frozen["fam"]
    assert e["ids"] == ["a", "e"]
    assert (e["n_ati"], e["n_invertible"], e["n_unverified"]) == (2, 1, 2)
    assert e["draw_pass"]["d"] == [False, None, False]
    assert e["instrument"] == "v1"
    written = json.loads(dst.read_text())
    assert "refused" not in written and "policy refusal" in written["_not_gated"]["refused"]
    assert set(ti.NOT_GATED) <= set(written["_not_gated"])


def test_gate_refuses_a_pilot_run(tmp_path, two_families):
    out = tmp_path / "o"
    for d in range(3):
        _answers(out, d, [("fam", i, "ok") for i in "abcde"] + [("refused", "x", "refusal")])
        rows = [{"id": i, "pass": False} for i in "abcde"]
        _results(out / "judged" / f"draw{d}" / "fam", "fam", rows, 0.0, limit=3)
    with pytest.raises(ValueError, match="subset"):
        ti.gate(out, dst=None)


# ---------------------------------------------------------------- scope lookup


def _frozen(tmp_path: Path, entry: dict | None, not_gated: dict | None = None) -> Path:
    d: dict = {"_not_gated": not_gated or {}}
    if entry is not None:
        d["fam"] = entry
    p = tmp_path / "ati.json"
    p.write_text(json.dumps(d))
    return p


def test_subset_entry_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(
        registry, "get", lambda f: SimpleNamespace(judge=SimpleNamespace(prompt_version="v2"))
    )
    ok = {"instrument": "v2", "ids": ["a"], "n_bank": 3, "judge_model": "m"}
    assert ti.subset("fam", _frozen(tmp_path, ok)) == ["a"]
    with pytest.raises(SystemExit, match="re-gate"):
        ti.subset("fam", _frozen(tmp_path, {**ok, "instrument": "v1"}))
    with pytest.raises(SystemExit, match="no item survives"):
        ti.subset("fam", _frozen(tmp_path, {**ok, "ids": []}))
    with pytest.raises(SystemExit, match="run the gate first"):
        ti.subset("fam", _frozen(tmp_path, None))
    with pytest.raises(SystemExit, match="policy refusal"):
        ti.subset("fam", _frozen(tmp_path, None, {"fam": "policy refusal: 90%"}))
    with pytest.raises(SystemExit, match="not gated"):
        ti.subset("hallucination", _frozen(tmp_path, None))


# ---------------------------------------------------------------- readout write policy


def test_write_readouts_last_position_unless_all_positions_family(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    prompts = [
        {
            "family": "fam",
            "id": "a",
            "positions": [-3, -1, -2],
            "tokens": ["x", "z", "y"],
            "layers": [20, 44],
            "layer": 44,
            "n_tokens": 10,
        },
        {
            "family": "brew_intermediates",
            "id": "b",
            "positions": [4, 7],
            "tokens": ["p", "q"],
            "layers": [20, 44],
            "layer": 44,
            "n_tokens": 9,
        },
        {
            "family": "buggy_code",
            "id": "c",
            "positions": [5],
            "tokens": ["t"],
            "layers": [60],
            "layer": 60,
            "n_tokens": 6,
        },
        {
            "family": "fam",
            "id": "gone",
            "positions": [-1],
            "tokens": ["z"],
            "layers": [44],
            "layer": 44,
            "n_tokens": 4,
        },
    ]
    (out / "prompts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in prompts))
    _answers(
        out,
        0,
        [
            ("fam", "a", "ok"),
            ("brew_intermediates", "b", "ok"),
            ("buggy_code", "c", "ok"),
            ("fam", "gone", "refusal"),
        ],
    )
    layers = ti.write_readouts(out, draws=1)
    assert layers == {"fam": [44], "brew_intermediates": [44], "buggy_code": [60]}

    def rows(f):
        path = out / "readouts" / "draw0" / f"{f}.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()]

    assert [(r["id"], r["layer"], r["pos"], r["token"]) for r in rows("fam")] == [
        ("a", 44, -1, "z")
    ]  # last position only; the refused item has no row
    assert [r["pos"] for r in rows("brew_intermediates")] == [4, 7]
    assert [(r["layer"], r["pos"]) for r in rows("buggy_code")] == [(60, 5)]


# ---------------------------------------------------------------- flag plumbing


def _args(**kw) -> JudgeArgs:
    base = {
        "readouts": Path("r"),
        "out": Path("o"),
        "judge": None,
        "layers": None,
        "items": None,
        "limit": 0,
        "allow_missing": False,
        "concurrency": 1,
        "rpm": 1.0,
        "dry_run": False,
    }
    return JudgeArgs(**{**base, **kw})


def test_is_subset_ignores_the_ati_scope_items():
    assert mcjudge.is_subset(_args(items=["a"]))
    assert not mcjudge.is_subset(_args(items=["a"], scope="anti_text_inversion"))
    assert mcjudge.is_subset(_args(items=["a"], scope="anti_text_inversion", limit=1))


def _fr(family: str, n: int, scope: str | None) -> FamilyResult:
    return FamilyResult(
        family=family,
        metric="pass_rate",
        value=0.5,
        ci95=None,
        n_items=n,
        higher_is_better=True,
        chance=None,
        chance_label=None,
        complete=True,
        pinned_instrument=True,
        config={"scope": scope} if scope else {},
        counts={},
    )


def test_ati_macro_drops_small_families():
    m = macro([_fr("big", 30, "anti_text_inversion"), _fr("small", 5, "anti_text_inversion")])
    assert m["families"] == ["big"]
    assert m["excluded"] == [{"family": "small", "reason": "n<20 (ATI)"}]
    assert macro([_fr("small", 5, None)])["families"] == ["small"]  # full-bank runs unchanged


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.delenv("WSBENCH_JUDGE_MODEL", raising=False)
    monkeypatch.setattr(llm, "_make_client", lambda r, k: pytest.fail("no client in tests"))
    monkeypatch.setattr(llm, "preflight", lambda model, reasoning: None)
    registry.FAMILIES.clear()


def test_run_flag_scopes_each_family_and_stamps_results(offline, tmp_path, monkeypatch):
    seen: dict[str, JudgeArgs] = {}

    def run(args: JudgeArgs) -> FamilyResult:
        seen[args.readouts.stem] = args
        r = _fr(args.readouts.stem, len(args.items or []), None)
        r.complete = not mcjudge.is_subset(args)
        return r

    for name in ("one", "two", "ungated", "stale"):
        register(
            EvalSpec(
                name=name,
                title=name,
                group="logic",
                bank=Path("x"),
                judge=JudgeConfig(),
                metric="pass_rate",
                higher_is_better=True,
                run=run,
            )
        )
    entries = {
        "one": {"ids": ["a", "b"], "n_bank": 10, "judge_model": "claude-opus-5-5"},
        "two": {"ids": ["c"], "n_bank": 4, "judge_model": "claude-opus-5-5"},
    }

    def entry(family):
        if family == "stale":
            raise SystemExit("stale: re-gate")
        if family not in entries:
            raise ti.NotInScope(f"{family}: not gated for anti_text_inversion (test)")
        return entries[family]

    monkeypatch.setattr(ti, "subset_entry", entry)
    root, out = tmp_path / "r", tmp_path / "o"
    root.mkdir()
    for n in ("one", "two", "ungated", "stale"):
        (root / f"{n}.jsonl").write_text(
            json.dumps({"id": "a", "layer": 1, "pos": 0, "samples": ["x"]}) + "\n"
        )
    code = main(
        ["run", "all=True", f"readouts_root={root}", f"out={out}", "anti_text_inversion=True"]
    )
    assert code == 2  # the stale family fails (re-gate); the ungated one is only skipped
    assert "ungated" not in seen and "stale" not in seen  # neither reached its judge
    assert seen["one"].items == ["a", "b"] and seen["two"].items == ["c"]
    assert seen["one"].scope == "anti_text_inversion"
    res = json.loads((out / "one" / "results.json").read_text())
    assert res["config"]["scope"] == "anti_text_inversion"
    assert res["numbers"]["extras"]["ati_n_bank"] == 10
    assert res["complete"] is True
    summary = (out / "summary.md").read_text()
    assert "- ungated: skipped — ungated: not gated" in summary
    assert "- stale: failed — stale: re-gate" in summary


def test_flag_and_items_are_exclusive(offline, tmp_path, capsys):
    argv = ["run", "all=True", f"readouts_root={tmp_path}", f"out={tmp_path}"]
    assert main([*argv, "anti_text_inversion=True", "items=a"]) == 2
    assert "drop items=" in capsys.readouterr().err


def test_template_is_verbatim_in_the_baselines_readme():
    readme = (registry.REPO_ROOT / "evals" / "baselines" / "README.md").read_text()
    assert f"```\n{ti.TEMPLATE}\n```" in readme


def test_refusal_with_partial_text_is_not_usable():
    row = {"answer": "The model has", "error": "", "refused": True, "stop_reason": "refusal"}
    assert not ti.usable(row)
    assert not ti.usable({**row, "refused": False})  # the stop_reason alone marks it
    assert ti.usable({"answer": "x", "error": "", "stop_reason": "end_turn"})


def test_draw_verdicts_requires_an_item_id(tmp_path):
    p = _results(tmp_path / "r", "fam", [{"pass": True}], value=1.0)
    with pytest.raises(ValueError, match="no id"):
        ti.draw_verdicts(p)


def test_judge_command_exit_codes_under_the_flag(offline, tmp_path, monkeypatch, capsys):
    def run(args):
        return _fr("x", 1, None)

    for name in ("ungated", "stale"):
        register(
            EvalSpec(
                name=name,
                title=name,
                group="logic",
                bank=Path("x"),
                judge=JudgeConfig(),
                metric="pass_rate",
                higher_is_better=True,
                run=run,
            )
        )

    def entry(family):
        if family == "stale":
            raise SystemExit("stale: re-gate")
        raise ti.NotInScope(f"{family}: not gated")

    monkeypatch.setattr(ti, "subset_entry", entry)
    r = tmp_path / "r.jsonl"
    r.write_text("")
    base = ["judge", f"readouts={r}", f"out={tmp_path / 'o'}", "anti_text_inversion=True"]
    assert main([*base, "family=ungated"]) == 0
    assert main([*base, "family=stale"]) == 2
    assert "re-gate" in capsys.readouterr().err


def test_gate_families_merges_a_second_answerer(tmp_path, two_families):
    dst = tmp_path / "ati.json"
    dst.write_text(
        json.dumps(
            {
                "_source": {"answerer": "claude-opus-5-5"},
                "_not_gated": {"fam": "policy refusal: 90% (opus)", "keep": "policy refusal"},
                "other": {"answerer": "claude-opus-5-5", "ids": ["z"]},
            }
        )
    )
    out = tmp_path / "o"
    for d in range(3):
        _answers(out, d, [("fam", i, "ok") for i in "abcde"])
        rows = [{"id": i, "pass": i == "a"} for i in "abcde"]
        _results(out / "judged" / f"draw{d}" / "fam", "fam", rows, 1 / 5)
    frozen = ti.gate(out, dst=dst, families=["fam"], answerer="claude-sonnet-5-5")
    assert frozen["fam"]["answerer"] == "claude-sonnet-5-5"
    written = json.loads(dst.read_text())
    assert written["fam"]["ids"] == ["b", "c", "d", "e"]
    assert written["other"] == {"answerer": "claude-opus-5-5", "ids": ["z"]}  # untouched
    assert "fam" not in written["_not_gated"] and "keep" in written["_not_gated"]
    assert written["_source"] == {"answerer": "claude-opus-5-5"}
