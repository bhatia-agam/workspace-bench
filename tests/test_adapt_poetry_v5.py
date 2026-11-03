"""plan 0060 A2: poetry bank v5 rebuilt on a subject (``wsbench.adapt.poetry``), with fakes for
the subject's runner, Opus and the judge (no GPU, no API)."""

import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wsbench.adapt import families as fams
from wsbench.adapt import poetry as po
from wsbench.adapt import run, store
from wsbench.adapt.gate import Ask, gate_record, grade_leg

MODEL = "qwen3.5-4b"
PROMPT = (
    "A rhyming couplet:\nThe dawn broke through the clouds of silver gray,\n"
    "And ushered in another working "
)


def _record(item: dict, answers: dict[str, tuple[str, list[str]]]) -> dict:
    """gate_record + finalize over ``{leg: (greedy, samples)}`` for one item's asks."""
    legs = {}
    for a in fams.get("poetry").asks(item):
        if a.leg in answers:
            g, s = answers[a.leg]
            legs[a.leg] = grade_leg(a, g, s, 0.8)
    return po.finalize(gate_record(legs))


def _free(words: list[str]) -> tuple[str, list[str]]:
    texts = [f"And I will greet the {w}\n" for w in words]
    return texts[0], texts[1:]


def test_free_word_and_site_plan():
    assert po.free_word("\nAnd sing until the end of day,\nmore") == "day"
    assert po.free_word("And sing until the end of day") == ""  # unfinished: no newline
    assert po.free_word("And sing until the end of day", eos_ends_line=True) == "day"
    assert po.site_plan(["day", "Day", "way", ""]) == ("day", 2)
    assert po.site_plan(["day", "way"]) == ("", 1)  # a tie has no modal word
    assert po.line_one_prefix(PROMPT) == (
        "A rhyming couplet:\nThe dawn broke through the clouds of silver gray,\n"
    )


def test_asks_add_the_free_leg_and_d6_variants(monkeypatch):
    item = {"name": "p", "prompt": PROMPT}
    monkeypatch.delenv("ADAPT_POETRY_VARIANTS", raising=False)
    legs = {a.leg: a for a in fams.get("poetry").asks(item)}
    assert set(legs) == {"surface", "surface:plain", "free:plain"}
    assert legs["free:plain"].prompt == po.line_one_prefix(PROMPT)  # the stub is cut
    assert legs["free:plain"].grade == "free_line" and legs["free:plain"].max_tokens == 40
    assert legs["surface"].meta["annotation"]  # the chat question certifies nothing
    monkeypatch.setenv("ADAPT_POETRY_VARIANTS", "fewshot,prefill")
    legs = {a.leg: a for a in fams.get("poetry").asks(item)}
    assert {"surface:fewshot", "free:fewshot", "surface:prefill", "free:prefill"} <= set(legs)
    pre = legs["free:prefill"]
    assert pre.prefill == "The dawn broke through the clouds of silver gray,\n"
    assert pre.meta["eos_ends_line"] and pre.messages[-1]["content"] == "Write a rhyming couplet."
    assert legs["free:fewshot"].prompt.endswith(po.line_one_prefix(PROMPT))


def test_v5_rule_couples_free_and_stub_words(monkeypatch):
    monkeypatch.delenv("ADAPT_POETRY_VARIANTS", raising=False)
    item = {"name": "p", "prompt": PROMPT, "intermediates": ["day"]}
    stub = ("day.", ["day"] * 10)
    chat = ("Sure, here it is", ["Sure"] * 10)
    ok = _record(item, {"surface": chat, "surface:plain": stub,
                        "free:plain": _free(["day"] * 5 + ["way", "ray", "play"] * 2)})  # fmt: skip
    assert ok["pass"] and ok["render"] == "surface:plain" and ok["poetry"]["site_hits"] == 5
    assert ok["poetry"]["chat"]["passed"] is False  # recorded only
    few = _record(item, {"surface:plain": stub, "free:plain": _free(["day"] * 3 + ["way"] * 2
                                                                    + list("abcdef"))})  # fmt: skip
    assert not few["pass"] and "3/11 < 4" in few["poetry"]["why"]["plain"]
    other = _record(item, {"surface:plain": stub, "free:plain": _free(["way"] * 11)})
    assert not other["pass"] and "not the read-site 'way'" in other["poetry"]["why"]["plain"]
    tie = _record(item, {"surface:plain": stub, "free:plain": _free(["day", "way"] * 5 + ["x"])})
    assert not tie["pass"] and tie["poetry"]["why"]["plain"] == "no unique modal free word"
    # chat alone never certifies (v5 certifies in the read render)
    chat_ok = ("day", ["day"] * 10)
    only_chat = _record(item, {"surface": chat_ok, "surface:plain": ("12", ["12"] * 10),
                               "free:plain": _free(["day"] * 11)})  # fmt: skip
    assert not only_chat["pass"]
    # restamp: the subject's gold, commitments (every leg's words) and free leg on the item
    out = run.restamp("poetry", {"name": "p", "prompt": PROMPT, "intermediates": ["way"]}, ok)
    assert out["intermediates"] == ["day"] and out["authored_rhyme"] == "way"
    assert out["gate_variant"] == "plain" and out["line_one_end"] == "gray"
    assert out["regate"]["leg"] == "free+plain" and out["regate"]["site_words"]["day"] == 5
    assert out["qwen_commits"]["day"] == 16 and out["qwen_commits"]["sure"] == 11


def test_d6_prefill_render_certifies_and_is_recorded(monkeypatch):
    monkeypatch.setenv("ADAPT_POETRY_VARIANTS", "prefill")
    item = {"name": "p", "prompt": PROMPT}
    rec = _record(item, {"surface:plain": ("12", ["12"] * 10),
                         "free:plain": _free(["day"] * 11),
                         "surface:prefill": ("day", ["day"] * 10),
                         "free:prefill": (" I greet the day", [" so day"] * 10)})  # fmt: skip
    assert rec["pass"] and rec["render"] == "surface:prefill"  # EOS ends the chat line
    assert run.restamp("poetry", item, rec)["gate_variant"] == "chat_prefill"


class FakeRunner:
    """The subject: free / stub legs end on the registered gold, except ``weak`` ids (3/11)."""

    def __init__(self, gold: dict[str, str], weak: set[str]):
        self.gold, self.weak = gold, weak

    def sample(self, asks: list[Ask], draws, temperature, top_p=1.0):
        out = []
        for a in asks:
            g = self.gold[a.item_id]
            if a.leg.startswith("free"):
                ws = [g] * 11 if a.item_id not in self.weak else [g] * 3 + list("abcdefgh")
                text = _free(ws)
                out.append(text)
            elif a.leg == "surface:plain":
                out.append((f"{g}.\n", [f"{g}."] * draws))
            else:
                out.append(("Sure! Here it is", ["Sure"] * draws))
        return out


class FakeTok:
    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}

    def decode(self, ids, **_kw):
        return "".join(map(chr, ids))


def _fake_opus(lines: dict[str, list[str]]):
    calls = []

    def ask(content: str) -> dict:
        calls.append(content)
        line = next(k for k in lines if k in content)
        quoted = ", ".join(f'"{w}"' for w in lines[line])
        return {"answer": f"Probably a rhyme such as {quoted}.", "refused": False,
                "stop_reason": "end_turn", "error": ""}  # fmt: skip

    return ask, calls


def _assert_a1_overlay_ships_row(family: str, reg: dict, row: dict) -> None:
    """A1's freeze (``run.build_original``): the REGISTERED item, restamped from the gate record,
    with ``gate_variant`` / ``needs_reasons`` and ONLY ``families.SUBJECT_FIELDS`` laid over it
    from the row. It must ship exactly the row's item (minus ``adapt`` and the marker): a field
    a stage writes that SUBJECT_FIELDS lacks would otherwise ship as Qwen's."""
    import copy

    it = run.restamp(family, copy.deepcopy(reg), row["gate"])
    src = row["item"]
    for k in ("gate_variant", "needs_reasons"):
        if k in src:
            it[k] = copy.deepcopy(src[k])
    for path in fams.SUBJECT_FIELDS[family]:
        head, *rest = path.split(".")
        if not rest:
            it[head] = copy.deepcopy(src[head])
            continue
        cur, val = it.setdefault(head, {}), src
        for part in path.split("."):
            val = val[part]
        for part in rest[:-1]:
            cur = cur.setdefault(part, {})
        cur[rest[-1]] = copy.deepcopy(val)
    want = {k: v for k, v in src.items() if k not in ("adapt", fams.SUBJECT_MARKER)}
    assert {k: v for k, v in it.items() if k != "adapt"} == want


@pytest.fixture
def adapted(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "model_dir", lambda m, root=None: tmp_path / "adapted" / m)
    monkeypatch.delenv("ADAPT_POETRY_VARIANTS", raising=False)
    return tmp_path


def test_poetry_stages_end_to_end_with_fakes(adapted, monkeypatch):
    import pronouncing

    _h, originals = store.original_bank("poetry")
    items = originals[:4]
    ids = [store.item_id(it) for it in items]
    gold = {store.item_id(it): it["intermediates"][0] for it in items}
    run.profile(MODEL, ["poetry"], limit=4, runner=FakeRunner(gold, weak={ids[3]}))
    rows = po.subject_rows(MODEL)
    assert [r["id"] for r in rows] == ids[:3]  # the weak item fails the free leg
    assert all(r["item"]["qwen_commits"].get("sure") == 11 for r in rows)  # the subject's words
    # Qwen's candidates / opus record never ride on a subject row before stage=opus_gate
    assert all(r["item"]["mc"] == {"candidates": []} for r in rows)
    assert all("prompt_only_opus" not in r["item"] for r in rows)
    assert items[0]["mc"]["candidates"] and "prompt_only_opus" in items[0]

    # tier A: Opus prompt-only on the subject's read render, cached per draw file
    lines = {it["prompt"].split("\n")[1]: [] for it in items[:3]}
    for it in items[:3]:
        end, g = po.line_one_end(it["prompt"]), gold[store.item_id(it)]
        lines[it["prompt"].split("\n")[1]] = [w for w in pronouncing.rhymes(end) if w != g][:40]
    ask, calls = _fake_opus(lines)
    po.tier_a(MODEL, ask=ask, tok=FakeTok())
    assert len(calls) == 9
    assert all(it["prompt"].split("\n")[2] not in c for it in items[:3] for c in calls)
    po.tier_a(MODEL, ask=ask, tok=FakeTok())
    assert len(calls) == 9  # the answer files are the cache

    # mc: the registered builder with --draft/--out (vet faked: it calls Opus)
    seen = []

    def script(args):
        seen.append(args[0])
        if args[0] == "vet":
            Path(args[args.index("--out") + 1]).write_text("{}")
            return
        po.run_script(args)

    mcs = po.build_mc(MODEL, script=script, tok=FakeTok())
    assert seen == ["vet", "build"] and set(mcs) == set(ids[:3])
    draft = json.loads((adapted / "adapted" / MODEL / "poetry" / "draft.json").read_text())
    assert all("mc" not in it and it["qwen_commits"] for it in draft["items"])
    for iid, mc in mcs.items():
        assert gold[iid] not in mc["candidates"] and "sure" not in mc["candidates"]
        assert any(t == "A" for t in mc["tiers"].values())

    # opus gate: ids[0] is picked on gate1 -> it fails; the rest pass with the subject fields
    def judge(bank, root, out):
        rows_ = [json.loads(x) for x in (Path(root) / "poetry.jsonl").read_text().splitlines()]
        assert json.loads(Path(bank).read_text())["items"][0]["adapt"]["model"] == MODEL
        return SimpleNamespace(
            config={"prompt_version": "poetry-free-x+reads-lite"},
            rows=[{"id": r["id"], "pass": r["id"] == ids[0] and Path(root).name == "gate1",
                   "kind": "cannot"} for r in rows_],
        )  # fmt: skip

    tally = po.opus_gate(MODEL, ask=ask, judge=judge, tok=FakeTok())
    assert tally == {"pass": 2, "fail:opus": 1}
    live = {r["id"]: r for r in run.live_rows(MODEL, "poetry")}
    picked, ok = live[ids[0]], live[ids[1]]
    assert not picked["gate"]["pass"] and picked["item"]["prompt_only_opus"]["picked_gold"] == 1
    assert ok["gate"]["pass"] and ok["gate"]["legs"]["opus_gate"]["passed"]
    assert ok["item"]["prompt_only_opus"]["instrument"] == "poetry-free-x"
    # what A1's freeze requires of a passing original: the marker and every SUBJECT_FIELDS path
    it = ok["item"]
    assert it[fams.SUBJECT_MARKER] == MODEL
    for path in fams.SUBJECT_FIELDS["poetry"]:
        cur = it
        for part in path.split("."):
            cur = cur[part]
    assert it["mc"] == mcs[ids[1]] and it["mc"] != items[1]["mc"]  # never Qwen's candidates
    _assert_a1_overlay_ships_row("poetry", items[1], ok)
    header = json.loads((adapted / "adapted" / MODEL / "poetry" / "header.json").read_text())
    assert header["opus_gate"]["picked"] == [ids[0]] and header["qwen_regate"]["n_passed"] == 3

    # regrade keeps a stage-built row as it is (its opus leg is not a gate question)
    assert run._regrade_row("poetry", ok, grade=None) is ok

    run.freeze(MODEL, ["poetry"])
    bank = json.loads((adapted / "adapted" / MODEL / "poetry.json").read_text())
    assert [store.item_id(i) for i in bank["items"]] == ids[1:3]
    assert bank["opus_gate"]["subject"] == MODEL  # the subject's header record, not Qwen's


def test_opus_refusal_is_undecided_and_fails_the_item(adapted):
    rec = po.record(
        [SimpleNamespace(config={}, rows=[{"id": "a", "pass": False, "kind": "x"}])] * 2
        + [SimpleNamespace(config={}, rows=[])],
        po.tags("gate"),
        ["a"],
    )
    assert rec["a"]["draws"] == 2 and rec["a"]["undecided"] == ["gate2"]


def test_tags_never_collide_with_the_floor_draw():
    with pytest.raises(ValueError):
        po.tags("draw")


def test_main_exposes_the_poetry_stages(monkeypatch):
    from wsbench.adapt import __main__ as cli

    got = []
    monkeypatch.setattr(po, "run", lambda m, stage, regate=False: got.append((m, stage, regate)))
    cli.main(["poetry", f"model={MODEL}", "stage=tier_a"])
    assert got == [(MODEL, "tier_a", False)]
    with pytest.raises(SystemExit):
        cli.main(["poetry", f"model={MODEL}", "families=poetry"])


def test_build_mc_script_still_runs_standalone(tmp_path):
    """build_mc.py --draft/--out on a subject draft (the builder the mc stage calls)."""
    draft = {"items": [{"id": "p", "prompt": PROMPT, "intermediates": ["day"],
                        "line_one_end": "gray", "qwen_commits": {"day": 3, "way": 1}}]}  # fmt: skip
    (tmp_path / "d.json").write_text(json.dumps(draft))
    (tmp_path / "a.jsonl").write_text(json.dumps({"id": "p", "answer": '"stay" or "way"'}) + "\n")
    (tmp_path / "v.json").write_text(json.dumps({"p": ["say", "lay", "pray"]}))
    subprocess.run([sys.executable, str(po.BUILD_MC), "build", "--draft", str(tmp_path / "d.json"),
                    "--answers", str(tmp_path / "a.jsonl"), "--vet", str(tmp_path / "v.json"),
                    "--out", str(tmp_path / "o.json")], check=True,
                   env={"PYTHONPATH": str(po.REPO / "src"), "PATH": "/usr/bin:/bin"})  # fmt: skip
    (it,) = json.loads((tmp_path / "o.json").read_text())["items"]
    assert it["mc"]["candidates"][:1] == ["stay"] and "way" not in it["mc"]["candidates"]
    assert re.fullmatch(r"[ABC]", it["mc"]["tiers"]["say"])


def test_judge_draw_scopes_the_bank_override(tmp_path, monkeypatch):
    import wsbench.cli
    import wsbench.results

    monkeypatch.delenv("WSB_BANK_FILE_POETRY", raising=False)
    seen = {}

    def fake_main(argv):
        import os

        seen["bank"], seen["argv"] = os.environ.get("WSB_BANK_FILE_POETRY"), argv
        return 0

    monkeypatch.setattr(wsbench.cli, "main", fake_main)
    monkeypatch.setattr(wsbench.results, "read_results", lambda p: p)
    po.judge_draw(tmp_path / "b.json", tmp_path / "r", tmp_path / "o")
    assert seen["bank"] == str((tmp_path / "b.json").resolve())
    assert "families=poetry" in seen["argv"]
    import os

    assert "WSB_BANK_FILE_POETRY" not in os.environ  # the registered bank is the record again


def test_opus_cache_is_keyed_on_the_prompt(adapted):
    ask, calls = _fake_opus({"silver gray": ["stay"]})
    item = {"id": "p", "prompt": PROMPT, "gate_variant": "plain"}
    po.ask_draws(MODEL, [item], "tierA", ask=ask, tok=FakeTok())
    po.ask_draws(MODEL, [item], "tierA", ask=ask, tok=FakeTok())
    assert len(calls) == 3  # cached for the same prompt
    few = {**item, "gate_variant": "plain_fewshot"}
    po.ask_draws(MODEL, [few], "tierA", ask=ask, tok=FakeTok())
    assert len(calls) == 6 and "The cat lay sleeping" in calls[-1]  # a new render: asked again
    from wsbench.baselines import text_inversion as ti

    shas = {i: ti.prompt_sha(c) for i, c in po.prompt_contents([item], FakeTok()).items()}
    path = adapted / "adapted" / MODEL / "poetry" / "answers" / "tierA0.jsonl"
    assert po._latest(path, shas)["p"]["prompt_sha"] == shas["p"]  # never the fewshot answer
    assert po._latest(path, {"p": "other"}) == {}
