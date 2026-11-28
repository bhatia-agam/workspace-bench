"""The read plan: every family plans, positions rules resolve on real token strings, and the
CLI writes one JSONL per family."""

import json

import pytest

from wsbench import readplan, registry
from wsbench.cli import main

# a Qwen chat render of one user-modelling item, as byte-level BPE display strings
UM_TOKENS = [
    *["<|im_start|>", "system", "Ċ", "You", "Ġare", "Ġhelpful", ".", "<|im_end|>", "Ċ"],
    *["<|im_start|>", "user", "Ċ", "I", "Ġlove", "Ġsopa", "."],
    *["ĠWrite", "Ġa", "Ġbio", "Ġfor", "Ġme", "."],
    *["<|im_end|>", "Ċ", "<|im_start|>", "assistant", "Ċ", "<think>", "ĊĊ", "</think>", "ĊĊ"],
]
POEM = [
    "A",
    "Ġrhyming",
    "Ġcouplet",
    ":",
    "Ċ",
    "The",
    "Ġroute",
    "Ġahead",
    ",",
    "Ċ",
    "And",
    "Ġwhere",
    "Ġhe",
    "'d",
    "Ġ",
]


def test_every_family_plans_and_rows_serialize():
    fams = readplan.families()
    assert len(fams) == 34  # + 4 (plan 0016), - ttt (0017), + unverbalized_hint, + 2 (0027),
    # - brew_intermediates (0029), - wrong_bridge_true (2026-10-30), - hallucination (0040),
    # - multihop_mt_regex (removed 2026-10-30), - medical_diagnosis{,_alt} (0058;
    # unverbalized_hint retired, not removed), + nyt_connections (0062),
    # + hinted_cutoff (0063), + math_shortcuts (0065), - math_shortcuts (dropped 2026-11-05),
    # + model_multihop (0076), - unverbalized_hint (removed, 0081), + user_modeling_hard (0106),
    # + association_hard (0108)
    for fam in fams:
        specs = readplan.plan(fam)
        assert specs, fam
        ids = [s.id for s in specs]
        assert len(set(ids)) == len(ids), fam
        for s in specs:
            assert s.render in readplan.RENDERS, (fam, s.render)
            assert s.layers and all(isinstance(L, int) for L in s.layers), fam
            row = s.row()
            json.dumps(row)  # serializable
            assert row["positions"]["kind"] and "family" in row and "id" in row
            if s.render not in ("captured",):
                assert s.text or s.messages, (fam, s.id)


def test_plans_match_the_bank_specs():
    arith = {s.id: s for s in readplan.plan("arithmetic_intermediates")}
    s = arith["addmul-000"]
    # plan 0032 §2.1.2: every family reads GRID
    assert s.positions == {"kind": "all_from_end"} and s.layers == readplan.GRID
    assert s.extra["frozen_cell"] == {"layer": 60, "pos": -8}
    buggy = {s.id: s for s in readplan.plan("buggy_code")}
    assert buggy["py-quantity-refund-credit"].layers == readplan.GRID
    mcdm = readplan.plan("multi_concept_directed_modulation")[0]
    assert mcdm.layers == readplan.GRID and mcdm.positions == {"kind": "last_n", "n": 12}
    conj = readplan.plan("conjunctive_association")[0]
    assert conj.layers == readplan.GRID and conj.suffix == readplan.SUMMARIZE_SUFFIX
    multihop = readplan.plan("multihop_st")  # plan 0048 C2 (sanctioned): full = every token
    assert {s.positions["kind"] for s in multihop} == {"all_from_end"}
    poetry = readplan.plan("poetry")[0]
    assert poetry.positions == {"kind": "line_one_tail"} and poetry.layers == readplan.GRID
    jb = readplan.plan("jailbreak_recognition")[0]
    span = jb.positions["positions"]
    assert jb.render == "chat_context" and jb.messages[-1]["role"] == "user"
    assert jb.layers == readplan.GRID
    implicit = next(s for s in readplan.plan("basic_readout_st") if s.render == "chat_prefill")
    assert implicit.prefill == readplan.ANSWER_STEM
    assert span[0] == 3 and span[-1] == 745 and len(span) == 743  # every token of the last turn


def test_resolve_each_rule():
    r = readplan.resolve
    assert r({"kind": "final_token"}, POEM) == [14]
    assert r({"kind": "offset_from_end", "k": 2}, POEM) == [-2]
    assert r({"kind": "last_n", "n": 3}, POEM) == [12, 13, 14]
    assert r({"kind": "all"}, POEM) == list(range(15))
    assert r({"kind": "all_from_end"}, POEM) == list(range(-15, 0))
    assert r({"kind": "positions", "positions": [1, 3, 99]}, POEM) == [1, 3]
    # the newline ending line one is the LAST newline: position 9, not the header's at 4
    assert r({"kind": "line_one_newline"}, POEM) == [9]
    # user modelling: from the request sentence ("Write a bio for me.") through the end
    got = r({"kind": "from_last_sentence_start"}, UM_TOKENS)
    assert got[0] == UM_TOKENS.index("ĠWrite") and got[-1] == len(UM_TOKENS) - 1
    # chain: from the question token through the end
    chain = [
        "The",
        "Ġstart",
        "Ġis",
        "Ġ23",
        ".",
        "ĠWhat",
        "Ġis",
        "Ġthe",
        "Ġfinal",
        "?",
        "<|im_end|>",
    ]
    assert r({"kind": "from_token", "token": " What"}, chain) == list(range(5, 11))
    # directed modulation: the carrier sentence's own tokens
    dm = [
        "Think",
        "Ġhard",
        ".",
        "<|im_end|>",
        "Ċ",
        "<|im_start|>",
        "assistant",
        "Ċ",
        "The",
        "Ġcommittee",
        "Ġmet",
        ".",
    ]
    assert r({"kind": "suffix_text", "text": "The committee met."}, dm) == [8, 9, 10, 11]
    # association families: the summarize suffix and everything after it
    story = [
        "Nora",
        "Ġwept",
        ".",
        "ĊĊ",
        "Sum",
        "mar",
        "ize",
        "Ġthe",
        "Ġstory",
        ".",
        "<|im_end|>",
        "Ċ",
        "<|im_start|>",
        "assistant",
        "Ċ",
        "<think>",
        "ĊĊ",
        "</think>",
        "ĊĊ",
    ]
    assert r({"kind": "suffix_text_then_tail", "text": "Summarize the story."}, story) == list(
        range(4, 19)
    )
    assert r({"kind": "suffix_text", "text": "Summarize the story."}, story) == list(range(4, 10))
    assert r({"kind": "final_token"}, []) == []


def test_cli_writes_one_file_per_family(tmp_path, capsys):
    assert main(["plan", "families=poetry,buggy_code", f"out={tmp_path}", "limit=3"]) == 0
    out = capsys.readouterr().out
    assert "poetry: 3 items" in out and "buggy_code: 3 items" in out
    rows = [json.loads(x) for x in (tmp_path / "poetry.jsonl").read_text().splitlines()]
    assert len(rows) == 3 and rows[0]["positions"] == {"kind": "line_one_tail"}
    assert rows[0]["layers"] == readplan.GRID and rows[0]["render"] == "plain" and rows[0]["text"]
    assert main(["plan", "families=nope", f"out={tmp_path}"]) == 2


def test_plan_all_skips_superseded_but_names_still_plan(tmp_path, real_families, monkeypatch):
    from wsbench.cli import main

    # plan 0081: RETIRED_FAMILIES is empty since unverbalized_hint was removed; a stand-in keeps
    # the retired branch exercised
    monkeypatch.setitem(registry.RETIRED_FAMILIES, "association", "retired (test stand-in)")

    assert main(["plan", "--full", f"out={tmp_path / 'all'}", "limit=1"]) == 0
    written = {p.stem for p in (tmp_path / "all").glob("*.jsonl")}
    assert "multihop" in written
    superseded = set(registry.superseded()) | set(registry.RETIRED_FAMILIES)  # + plan 0058
    assert not written & superseded
    assert len(written) == len(readplan.families()) - len(superseded)
    assert "typo" in written and "typo_st" not in written  # plan 0033 T1
    assert main(["plan", "families=typo_st", f"out={tmp_path / 'v1'}", "limit=1"]) == 0
    assert (tmp_path / "v1" / "typo_st.jsonl").exists()
    # plan 0058: a retired family is out of `all` but still plans by name
    assert "association" not in written
    assert main(["plan", "families=association", f"out={tmp_path / 'r'}", "limit=1"]) == 0
    assert (tmp_path / "r" / "association.jsonl").exists()


def test_offsets_from_end_reports_each_negative_offset():
    toks = [f"t{i}" for i in range(52)]
    assert readplan.resolve({"kind": "offsets_from_end", "ks": [10, 2, 1]}, toks) == [-10, -2, -1]
    assert readplan.resolve({"kind": "offsets_from_end", "ks": [60, 1]}, toks) == [
        -1
    ]  # out of range dropped


# the Qwen3.6-27B tokens of couplet-ahead-head's render (plain, no special tokens)
COUPLET = ["A", "Ġrh", "ym", "ing", "Ġcouple", "t", ":", "Ċ", "The", "Ġcaptain", "Ġpointed", "Ġat",
           "Ġthe", "Ġroute", "Ġahead", ",", "Ċ", "And", "Ġtold", "Ġhis", "Ġcrew", "Ġto", "Ġfollow",
           "Ġwhere", "Ġhe", "'d", "Ġ"]  # fmt: skip


def test_poetry_reads_the_line_one_tail():
    """plan 0038 P7: line one's last word through its newline; never a position of the
    line-two stub."""
    full = readplan.resolve({"kind": "line_one_tail"}, COUPLET)
    assert full == [14, 15, 16]
    assert readplan.resolve({"kind": "line_one_newline"}, COUPLET) == [16]
    # a multi-token word and trailing punctuation; the prefill anchor
    assert readplan.resolve({"kind": "line_one_tail"}, ["Ċ", "The", "Ġmac", "beth", '."', "Ċ"]) == [
        2, 3, 4, 5
    ]  # fmt: skip
    chat = ["<|im_start|>", "assistant", "Ċ", "The", "Ġsky", ",Ċ", "And", "Ġthe"]
    assert readplan.resolve({"kind": "line_one_tail", "anchor": "last_newline"}, chat) == [4, 5]


# ---------------------------------------------------------------- plan 0038 C7: chain read site

# chain-d3p-0611's chat render tail as Qwen tokenizes it (digits split: "23" is "2", "3")
CHAIN_0611 = [
    "<|im_start|>", "user", "Ċ", "Apply", "Ġthe", "Ġsteps", "Ċ", "Halve", "Ġit", ".", "Ċ",
    "The", "Ġstarting", "Ġnumber", "Ġis", "Ġ", "2", "3", ".", "ĠWhat", "Ġis", "Ġthe", "Ġfinal",
    "Ġnumber", "?", "<|im_end|>", "Ċ", "<|im_start|>", "assistant", "Ċ", "<think>", "ĊĊ",
    "</think>", "ĊĊ",
]  # fmt: skip


def test_chain_reads_from_last_start_digit():
    rule = {"kind": "from_text_last_token", "text": "The starting number is 23"}
    got = readplan.resolve(rule, CHAIN_0611)
    assert CHAIN_0611[got[0]] == "3" and CHAIN_0611[got[0] - 1] == "2"
    assert got == list(range(got[0], len(CHAIN_0611))) and CHAIN_0611[got[-1]] == "ĊĊ"


def test_chain_single_digit_start():
    toks = ["The", "Ġstarting", "Ġnumber", "Ġis", "Ġ", "7", ".", "ĠWhat", "?", "ĊĊ"]
    got = readplan.resolve(
        {"kind": "from_text_last_token", "text": "The starting number is 7"}, toks
    )
    assert got == [5, 6, 7, 8, 9]


def test_from_text_last_token_missing_text_reads_nothing():
    rule = {"kind": "from_text_last_token", "text": "The starting number is 99"}
    assert readplan.resolve(rule, CHAIN_0611) == []


def test_chain_plan_row_uses_the_start_tail(real_families):
    rows = readplan.plan("chain_intermediates")
    assert len(rows) == 120
    for s in rows:
        assert s.positions["kind"] == "from_text_last_token"
        assert s.positions["text"].startswith("The starting number is ")
        assert s.positions["text"] in s.text
        assert s.layers == readplan.GRID


def test_chain_qwen_tokenizer():
    """The real Qwen3.6-27B tokenizer (skipped unless transformers and the cached tokenizer are
    available): every v2 item reads 27 positions, from the start's last digit to the onset."""
    transformers = pytest.importorskip("transformers")
    try:
        tok = transformers.AutoTokenizer.from_pretrained("Qwen/Qwen3.6-27B", local_files_only=True)
    except OSError:
        pytest.skip("Qwen3.6-27B tokenizer not cached")
    for s in readplan.plan("chain_intermediates"):
        text = tok.apply_chat_template(
            [{"role": "user", "content": s.text}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        toks = tok.convert_ids_to_tokens(tok(text, add_special_tokens=False)["input_ids"])
        got = readplan.resolve(s.positions, toks)
        assert len(got) == 27, s.id
        assert toks[got[0]] == str(s.positions["text"].split()[-1])[-1], s.id


# rel-s00-a as the Qwen3.6-27B tokenizer.json splits it (checked 2026-10-30, plan 0043 C1)
REL_S00A = ["A", "very", "'s", "Ġlandlord", "Ġis", "ĠSam", ".", "ĠSam", "'s", "Ġsibling", "Ġis"]
REL_S00A += ["ĠRiley", ".", "ĠIn", "Ġother", "Ġwords", ",", "ĠRiley", "Ġis", "ĠAvery", "'s"]


def test_relational_reads_from_full_stop():
    """plan 0043 C1: the relational read runs from the full stop of sentence two through the
    possessive blank."""
    import pytest

    from wsbench.mcjudge import load_bank

    rows = {s.id: s for s in readplan.plan("relational_multihop")}
    a = rows["rel-s00-a"]
    assert a.positions == {"kind": "suffix_text", "text": ". In other words, Riley is Avery's"}
    full = readplan.resolve(a.positions, REL_S00A)
    assert full == list(range(12, 21)) and REL_S00A[12] == "."
    for it in load_bank("relational_multihop"):
        assert it["stimulus"].count(readplan.RELATIONAL_ANCHOR) == 1
    with pytest.raises(ValueError, match="rel-x"):
        readplan.relational_tail({"id": "rel-x", "stimulus": "Avery's landlord is Sam"})


def test_user_modeling_reads_every_position():
    """Camila 2026-10-30 ("We should read at all positions", plan 0056): the UM read is
    every token of the chat render (system turn, user turn, template tail)."""
    rows = readplan.plan("user_modeling")  # bank v3: its own 126 rows
    assert len(rows) == 126 and all(list(s.layers) == list(readplan.GRID) for s in rows)
    rule = rows[0].positions
    assert rule == {"kind": "all"}
    assert readplan.resolve(rule, UM_TOKENS) == list(range(len(UM_TOKENS)))


def test_association_reads_summarize_suffix():
    """Plan 0039 §C2: association reads the conjunctive / role-bound render and 19 sites."""
    plan = readplan.plan("association")
    assert len(plan) == 93
    for s in plan:
        assert s.render == "chat_summarize" and s.suffix == readplan.SUMMARIZE_SUFFIX
        assert s.positions == {"kind": "suffix_text_then_tail", "text": "Summarize the "
                               "preceding story in one sentence."}  # fmt: skip
        assert s.layers == readplan.GRID and s.text
    # the real Qwen tail after the suffix: 10 suffix tokens + 9 chat-tail tokens = 19 sites
    toks = ["Os", "Ġtambores", ".", "ĊĊ", "Sum", "mar", "ize", "Ġthe", "Ġpreceding", "Ġstory",
            "Ġin", "Ġone", "Ġsentence", ".", "<|im_end|>", "Ċ", "<|im_start|>", "assistant", "Ċ",
            "<think>", "ĊĊ", "</think>", "ĊĊ"]  # fmt: skip
    got = readplan.resolve(plan[0].positions, toks)
    assert got == list(range(4, 23)) and len(got) == 19


def test_basic_readout_v2_all_chat_prefill():
    """Plan 0039 C2b/C4: every v2 item is a chat question with the answer stem prefilled, read
    from the first question token through the end."""
    rows = readplan.plan("basic_readout_st")
    assert len(rows) == 100
    for s in rows:
        assert s.render == "chat_prefill" and s.prefill == readplan.ANSWER_STEM, s.id
        assert s.positions == {"kind": "suffix_text_then_tail", "text": s.text}, s.id
        assert s.text.endswith("? Answer in one word.") and s.layers == readplan.GRID


def test_basic_readout_v2_positions():
    q = "What is the day before Monday? Answer in one word."
    toks = (
        ["<|im_start|>", "user", "Ċ", "What", "Ġis", "Ġthe", "Ġday", "Ġbefore", "ĠMonday", "?",
         "ĠAnswer", "Ġin", "Ġone", "Ġword", ".", "<|im_end|>", "Ċ", "<|im_start|>", "assistant",
         "Ċ", "<think>", "ĊĊ", "</think>", "ĊĊ", "My", "Ġone", "-word", "Ġanswer", "Ġis", ":"]
    )  # fmt: skip
    got = readplan.resolve({"kind": "suffix_text_then_tail", "text": q}, toks)
    assert got[0] == toks.index("What") and got[-1] == len(toks) - 1 and toks[got[-1]] == ":"
    assert got == list(range(3, len(toks)))  # the template header before the question is not read


def test_multihop_reads_every_token():
    """Plan 0036 C2: every token (negative offsets), on every layer."""
    from wsbench.banks import load_bank

    # bank v5 (registered) plans its own 98 rows: v3's 68 kept rows + 30 new items
    _h, items = load_bank(readplan.bank_path("multihop_st"))
    assert readplan.bank_path("multihop_st").name == "items_v5.json"
    rows = readplan.plan("multihop_st")
    assert len(rows) == 98 and [s.id for s in rows] == [it["id"] for it in items]
    for s in rows:
        assert s.positions == {"kind": "all_from_end"} and s.render == "plain"
        assert s.layers == readplan.GRID
    toks = ["Fact", ":", " The", " capital", " is", " "]
    assert readplan.resolve({"kind": "all_from_end"}, toks) == [-6, -5, -4, -3, -2, -1]


@pytest.mark.parametrize(
    "family", ["multilingual_st", "multilingual", "multilingual_multihop", "multilingual_typo"]
)
def test_multilingual_families_read_all_positions(family):
    """Plan 0033 B4: every prompt position."""
    from wsbench.readplan import plan, resolve

    toks = ["a", "b", "c", "d", "e"]
    for spec in plan(family)[:5]:
        assert spec.render == "plain"
        assert resolve(spec.positions, toks) == [0, 1, 2, 3, 4]


# plan_sha pins of five families; a later bank or read change may refresh them
PLAN_SHA = {
    # bank v8's own 100-row plan (the new items' rows; bank v7's plan was 195a60c7...)
    "basic_readout_st": "0a721338b8755307ce59797c3f8eaf24118b2ac55b1f7551e50c7f92e8a62c36",
    # bank v2's own 102-row plan (plan 0109; the 100-item items.json's plan was 1da94e9c...)
    "directed_modulation": "940bf69a0dbc0482120ab41fc24e0b1a5b948e8b6b1b5323e99b99bf2c5253b3",
    "model_specific_directed_modulation": (
        "ef00b1f9ec23cda8340e146cb34219fc56795f1585cd6856afd8682b8411e782"
    ),
    "multi_concept_directed_modulation": (
        "41ce9adb0a84f6a8dcd9f4f3393ab3ee18adbd75d89817e49c1d3c6b6eb901cf"
    ),
    # bank v3's own 126-row plan (items.json's 100-row plan, which bank v2 read, was 072e3108...)
    "user_modeling": "9cc43bf742edf7eb5b29f84ad815d79fc61d9769d9690ceafcf8f76e427aa709",
}


@pytest.mark.parametrize("family", sorted(PLAN_SHA))
def test_plan_sha_is_pinned(family):
    from wsbench import reads

    assert reads.plan_sha(family) == PLAN_SHA[family]
