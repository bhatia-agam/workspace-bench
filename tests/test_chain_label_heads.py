"""chain_intermediates heads-v4: a number a lowercase word continues ("20 steps in order.") is a
count, a label or an operand, never a stated result (judge.result_head / judge.label_head);
heads-v5: unless the continuation calls it the result or the answer ("12 is the result")."""

from wsbench import digest
from wsbench.evals.chain_intermediates import judge as chain
from wsbench.evals.chain_intermediates import prompts
from wsbench.readouts import Cell


def test_answer_head_shapes():
    # heads-v1..v3 shapes are unchanged
    shapes = ("15\n\n**Explanation:**", "**28**", "17```", "24\n</think>", "1. Start", "11.**")
    shapes += ("28 + 6 - 5", "1st step", "8GB", "10.5")
    assert [chain.answer_head(s) for s in shapes] == [15, 28, 17, 24] + [None] * 6
    # real lens heads a lowercase word continues: counts, labels, operands
    for s in (
        "20 steps in order. Here is the step-by-step calculation:",
        "25 divided by 2 is 12.5.",
        "22 of 72 (halve it).",
        "17 by 3 The first step is to multiply 17 by 3.",
        "- 12 is the starting number. Apply the rule twice.",
        "3 and apply the rule: round up",
    ):
        assert chain.answer_head(s) is None, s
    # a capitalised heading, a CJK word or markdown after the number keeps the head
    for s, v in (
        ("- 7 Explanation: First, divide 10 by 2 to get 5.", 7),
        ("12 What is the final result?", 12),
        ("16 解析\uff1a42 + 2 = 44", 16),
        ("22 ``` **Explanation of the Calculation:**", 22),
        ("17 ### Explanation Adding 5 to the initial number 12 results in 17.", 17),
    ):
        assert chain.answer_head(s) == v, s


def test_result_statement_keeps_the_head_and_is_no_label():
    """heads-v5: "N is / was / equals (the) (final) result / answer" states N as the result."""
    for s in (
        "12 is the result: 24 / 2 = 12",
        "12 is the result",
        "12 is the answer.",
        "12 is the result of halving 24.",
        "12 was the answer",
        "12 equals the final result",
        "- **12** is the final answer.",
    ):
        assert chain.answer_head(s) == 12, s
        assert not chain.label_head(s, 12), s
    # other lowercase continuations are still counts, labels or operands
    for s in ("12 is the starting number", "12 is resultant", "12 results from halving"):
        assert chain.answer_head(s) is None, s
    assert chain.label_head("12 is the starting number", 12)


def test_result_statement_quote_is_a_hit():
    opts = [9, 12, 14, 7, 16, 11, 20, 5]
    for quote, sample in (
        ("12 is the result", "12 is the result: 24 / 2 = 12"),
        ("12 is the answer.", "12 is the answer."),
        ("12 was the answer", "Halving 24: 12 was the answer"),
    ):
        v = _slot(quote, 12, opts, (sample,))
        assert v["kind"] == "hit", (quote, v)


def test_result_statement_counts_in_the_tie_gate():
    ops = chain.op_pattern(["halve_up"])
    cells = [Cell("x", 44, 60, ("12 is the result of halving 24.",) * 2, None, None)]
    assert chain.answer_head_counts(cells, ops) == {12: 2}


# chain-w2-d2p-0171 (lens B RL600): start 15, +5 -> 20, +2 -> 22. The judge picked 20 on a key
# example that opens "20 steps in order." and goes on to compute 28 + 8 (20 is a count, not a
# result)
OPTS_0171 = [17, 25, 20, 23, 18, 22, 16, 21]
STEPS = (
    "20 steps in order. Here is the step-by-step calculation: 1. **Start with the initial "
    "number:** 28 2. **First instruction:** Add 8 $$28 + 8 ="
)
OTHER = "$ and the second number is $20$. **Step 1: Subtract 10 from the starting number**"


def _slot(quote: str, gold: int, opts: list[int], samples: tuple[str, ...]) -> dict:
    lines = digest.native_lines([Cell("x", 44, 60, samples, None, None)])
    res = {"choice": opts.index(gold) + 1, "quote": quote, "basis": "stated_result"}
    return chain.summary_verdict_mc(res, gold, opts, lines, None, {})


def test_count_quote_is_not_a_stated_result():
    v = _slot("20 steps in order.", 20, OPTS_0171, (STEPS, OTHER))
    assert v["kind"] == "label" and not v["hit"]
    # a bare "20" whose only holding line uses it as a count is a label too
    assert _slot("20", 20, OPTS_0171, (STEPS,))["kind"] == "label"
    # ... but not when another line holding the quote names 20 otherwise (the rule before)
    assert _slot("20", 20, OPTS_0171, (STEPS, OTHER))["kind"] == "hit"


def test_real_results_still_pass():
    opts = [9, 12, 14, 7, 16, 11, 20, 5]
    for quote, gold, sample in (
        ("16\u22127=9", 9, "Step 2: 16\u22127=9, so the answer is 9."),
        ("the final result is 12", 12, "Halve 24: the final result is 12."),
        ("12", 12, "12\n\n**Explanation:** halve 24 to get 12."),
        ("**14**", 14, "**14**"),
        ("20 steps: 15 + 5 = 20", 20, "20 steps: 15 + 5 = 20, then add 2."),
    ):
        v = _slot(quote, gold, opts, (sample,))
        assert v["kind"] == "hit", (quote, v)


def test_tie_gate_counts_result_heads_only():
    # chain-d2p-0298 (lens B RL600): 24 halved -> 12. "25 divided by 2" and "22 of 23" are operands,
    # so they no longer out-head the gold's "24 / 2 = 12"
    ops = chain.op_pattern(["halve_up", "add"])
    cells = [
        Cell("x", 56, 60, ("25 divided by 2 (half of 25).\n2. Round it.",) * 4, None, None),
        Cell("x", 60, 60, ("22 of 23 exactly (i.e., $22 \\div 2$).",) * 3, None, None),
        Cell("x", 44, 63, ("12\n\n$24 / 2 = 12$, then add 6.",) * 2, None, None),
    ]
    heads = chain.answer_head_counts(cells, ops)
    assert heads == {12: 2}
    assert not chain.head_tie(12, [11, 27, 25, 15, 22, 21, 12, 29], heads)


def test_stamp():
    assert prompts.HEADS_VERSION == "heads-v5" and prompts.MC_CALL_VERSION == "chain-mc-2026-10-30"
    assert prompts.PROMPT_VERSION == "chain-mc-2026-10-30+heads-v5+start-op+key-ex2"
