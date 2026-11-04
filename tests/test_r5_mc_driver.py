"""scripts/mc_options_r5.py's offline stages: the per-family search size a re-run uses, and the
records ``drops`` writes when fresh draws over a frozen bank extend the drops or undo an
extension. No Claude call."""

import argparse
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _driver():
    spec = importlib.util.spec_from_file_location(
        "mc_options_r5", REPO / "scripts/mc_options_r5.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_search_lists_are_the_recorded_ones():
    """Each family's ``search_lists`` is the number of candidate lists its repair round played, as
    its frozen bank's ``r5_mc.rule`` records it (no repair round: the default), so a re-run of the
    committed driver searches as the recorded run did."""
    r5 = _driver()
    assert {n: c.search_lists for n, c in r5.CFGS.items()} == {
        "basic_readout_mt": 5,
        "multihop_mt_v2": 5,
        "multilingual": r5.SEARCH_LISTS,
        "multilingual_mt": r5.SEARCH_LISTS,
        "multilingual_multihop": 4,
        "multilingual_typo": 5,
    }
    for name, cfg in r5.CFGS.items():
        new = REPO / cfg.new
        if new.is_file():  # frozen by the bank's own change
            rule = json.loads(new.read_text(encoding="utf-8"))["r5_mc"]["rule"]
            m = re.search(r"played (\d+) candidate lists per list", rule)
            assert m is None or int(m.group(1)) == cfg.search_lists, name


def test_start_bank_reapplies_a_folded_edit(tmp_path, monkeypatch):
    """A rebuild that started from a small edit of an earlier bank, which the series folded into
    the new bank instead of keeping its own file, starts from that edit re-applied: the record
    under ``cfg.edit`` in the new bank's header. Every other family starts from ``cfg.bank``."""
    r5 = _driver()
    monkeypatch.setattr(r5, "WORK", tmp_path)
    for name, cfg in r5.CFGS.items():
        path = r5.start_bank(cfg)
        if not cfg.edit:
            assert path == REPO / cfg.bank, name
            continue
        start = json.loads(path.read_text(encoding="utf-8"))
        old = json.loads((REPO / cfg.bank).read_text(encoding="utf-8"))
        rec = json.loads((REPO / cfg.new).read_text(encoding="utf-8"))[cfg.edit]
        assert start[cfg.edit] == rec and path.parent == tmp_path / name
        gone = set(rec.get("removed") or [])
        assert [it["name"] for it in start["items"]] == [
            it["name"] for it in old["items"] if it["name"] not in gone
        ]
        cut = rec.get("removed_options") or {}
        by = {it["name"]: it for it in old["items"]}
        for it in start["items"]:
            for role, blk in it["mc"].items():
                want = by[it["name"]]["mc"][role]["distractors"]
                want = [d for d in want if d not in cut.get(it["name"], {}).get(role, [])]
                assert blk["distractors"] == want, (name, it["name"], role)
    assert r5.CFGS["basic_readout_mt"].edit == r5.CFGS["multihop_mt_v2"].edit == "v5"


def _lucky(d: Path, variant: str, hits: dict[str, int], chance: float = 0.2) -> None:
    """A lucky-guessing result in ``d``: one five-option list per item, ``hits[id]`` of 5 draws
    on the gold."""
    per = {
        k: {"n_options": [5], "draws": [{"correct": i < h} for i in range(5)]}
        for k, h in hits.items()
    }
    mean = sum(hits.values()) / (5 * len(hits))
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{variant}.json").write_text(
        json.dumps({"aggregate": {"mean": mean, "n_items": len(hits)}, "analytic_floor": chance,
                    "per_item": per}),
        encoding="utf-8",
    )  # fmt: skip


def _round_draws(work: Path, rest: int) -> None:
    """Round 1's draws over ten items: i0 solved by all three guessers, i1 and i2 by the two
    shown solved examples; the blind guesser at chance on the rest, the other two on ``rest`` of
    5 draws."""
    blind = {f"i{k}": 1 for k in range(10)} | {"i0": 5}
    shown = {f"i{k}": rest for k in range(10)} | {"i0": 5, "i1": 4, "i2": 5}
    for v, h in (("blind", blind), ("described", shown), ("topic", shown)):
        _lucky(work / "lucky_r1", v, h)


def test_drops_extend_records_the_fresh_draws(tmp_path, monkeypatch):
    """``drops --extend``: the bank frozen from the all-three rule failed on fresh draws; the
    extension drops the items both example-shown guessers solve and records those draws."""
    r5 = _driver()
    monkeypatch.setattr(r5, "WORK", tmp_path)
    cfg = r5.CFGS["multilingual_typo"]
    work = tmp_path / cfg.name
    _round_draws(work, rest=0)  # the kept items pass on the round's own draws
    args = argparse.Namespace(round=1, extend=False, base=False)
    assert r5.cmd_drops(cfg, args) == 0
    first = json.loads((work / "drops.json").read_text(encoding="utf-8"))
    assert list(first["dropped"]) == ["i0"] and first["still_failing"] == []
    with pytest.raises(SystemExit, match="no fresh draws"):
        r5.cmd_drops(cfg, argparse.Namespace(round=1, extend=True, base=False))
    # fresh draws over the nine kept items: the topic guesser fails (17 of 45 > 0.25)
    _lucky(work / "lucky_final", "topic", {f"i{k}": 1 for k in range(1, 10)} | {"i1": 5, "i2": 5})
    assert r5.cmd_drops(cfg, argparse.Namespace(round=1, extend=True, base=False)) == 0
    rec = json.loads((work / "drops.json").read_text(encoding="utf-8"))
    assert sorted(rec["dropped"]) == ["i0", "i1", "i2"]
    assert rec["still_failing"] == ["described", "topic"]
    assert rec["extended_after"] == {
        "topic_fresh_draws": 0.3778,
        "n_items": 9,
        "bank": "the 9 items left by the all-three rule",
    }
    assert not (work / "lucky_final").exists() and (work / "lucky_final_9/topic.json").is_file()


def test_drops_base_records_an_extension_not_kept(tmp_path, monkeypatch):
    """``drops --base`` after an extension whose frozen bank still failed on fresh draws: back to
    the all-three rule, with the extension's draws recorded as not kept."""
    r5 = _driver()
    monkeypatch.setattr(r5, "WORK", tmp_path)
    cfg = r5.CFGS["multilingual_multihop"]
    work = tmp_path / cfg.name
    _round_draws(work, rest=1)
    args = argparse.Namespace(round=1, extend=False, base=False)
    r5.cmd_drops(cfg, args)  # the kept items fail on the round's own draws: extended at once
    ext = json.loads((work / "drops.json").read_text(encoding="utf-8"))
    assert sorted(ext["dropped"]) == ["i0", "i1", "i2"] and ext["still_failing"]
    # fresh draws over the seven items the extension kept: the topic guesser still fails
    _lucky(work / "lucky_final", "topic", {f"i{k}": 1 for k in range(3, 10)} | {"i3": 5, "i4": 5})
    assert r5.cmd_drops(cfg, argparse.Namespace(round=1, extend=False, base=True)) == 0
    rec = json.loads((work / "drops.json").read_text(encoding="utf-8"))
    assert list(rec["dropped"]) == ["i0"] and rec["still_failing"] == []
    assert rec["extension_not_kept"] == {
        "topic_fresh_draws": 0.4286,
        "n_items": 7,
        "why": "dropping the 2 more items both described and topic still solved left the topic "
        "guesser at this rate on fresh draws (its per-item picks move with the solved examples "
        "it is shown), so the extension does not reach the standard and is not kept",
    }
    assert (work / "lucky_final_extended3/topic.json").is_file()
    with pytest.raises(SystemExit, match="exclude"):
        r5.cmd_drops(cfg, argparse.Namespace(round=1, extend=True, base=True))
