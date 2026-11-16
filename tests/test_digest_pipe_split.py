"""The " | " token split keeps a token that itself holds "|" (Qwen's ``<|im_end|>``) whole, in the
digest's evidence grounding and in the quote verifier; the bare "|" split cut it into three parts,
so every multi-token span holding one failed."""

from wsbench import digest


def test_token_level_keeps_special_tokens_whole():
    pieces = ("<|file_sep|>", "这首", "Compiler", "Run")
    assert digest._token_level("<|file_sep|> | 这首 | Compiler", pieces) == 0
    assert digest._token_level("Compiler | Run", pieces) == 0  # the bare split still works
    assert digest._token_level("Compiler|Run", pieces) == 0
    assert digest._token_level("<|file_sep|> | Nope", pieces) is None
    assert digest.token_splits("a|b") == [["a", "b"]]
    assert digest.token_splits("plain") == []


def test_digest_and_quote_gate_keep_im_end_whole():
    ln = digest.Line(
        "<|im_end|> | Paris | <|endoftext|> | capital",
        ("<|im_end|>", "Paris", "<|endoftext|>", "capital"),
        "[L20 pos 5]",
        20,
        5,
    )
    other = digest.Line("x | y", ("x", "y"), "[L20 pos 6]", 20, 6)
    span = "<|im_end|> | Paris | <|endoftext|>"
    result = {"items": [{"statement": "Paris among end tokens", "key": "Paris",
                         "where": "[L20 pos 5]", "evidence": span, "count": 1}]}  # fmt: skip
    kept, dropped = digest.ground(result, [ln, other], 10)
    assert dropped == 0 and [g.line for g in kept] == [ln] and kept[0].key == "Paris"
    assert digest.line_holds(span, ln) and digest.quote_ok(span, [ln, other])
    assert digest.line_holds("Paris | capital", ln)
    assert digest.line_holds("Paris", ln) and not digest.line_holds("Rome", ln)
    assert not digest.line_holds("<|im_end|> | x", ln)
    assert not digest.quote_ok("<|im_end|> | Rome", [ln, other])


def test_single_special_token_and_scored_parts():
    ln = digest.Line(
        "<|im_end|> | Paris",
        ("<|im_end|>", "Paris"),
        "[L20 pos 5]",
        20,
        5,
        scores=(0.123, 0.5),
    )
    assert digest._token_level("<|im_end|>", ln.pieces) == 0
    assert digest.line_holds("<|im_end|>", ln) and digest.quote_ok("<|im_end|>", [ln])
    assert digest.line_holds("<|im_end|> (0.12) | Paris", ln)  # its own real score
    assert not digest.line_holds("<|im_end|> (0.99) | Paris", ln)
    assert not digest.line_holds("<|im_end|>|Paris", ln)  # unspaced around a special token
