"""agentic_misalignment Stage C parsing: a malformed or non-object reply is PARSE_ERR (an undecided
record), never a crash of the whole run (seen live: a Stage C reply with a missing comma)."""

import json

from wsbench.evals.safety.agentic_misalignment.prompts import (
    parse_design_score,
    parse_design_score_summary,
)

GOOD = {
    "identified_family": "none",
    "asserts_misaligned_plan": False,
    "design_rank": 0,
    "design_fidelity": 0,
}


def test_malformed_object_is_parse_error():
    out = parse_design_score('note {"identified_family": "leaking" "design_rank": 2}')
    assert out["identified_family"] == "PARSE_ERR" and out["design_rank"] is None


def test_non_object_json_and_no_json_are_parse_errors():
    assert parse_design_score("[1, 2, 3]")["identified_family"] == "PARSE_ERR"
    assert parse_design_score('"just a string"')["identified_family"] == "PARSE_ERR"
    assert parse_design_score("no json here")["identified_family"] == "PARSE_ERR"
    assert parse_design_score("null")["identified_family"] == "PARSE_ERR"
    assert parse_design_score("3")["identified_family"] == "PARSE_ERR"


def test_summary_parser_survives_a_malformed_reply():
    out = parse_design_score_summary('```json\n{"identified_family": "none" "x": 1}\n```')
    assert out["identified_family"] == "PARSE_ERR"


def test_valid_replies_parse_as_before():
    plain = parse_design_score(json.dumps(GOOD))
    wrapped = parse_design_score("Here it is:\n" + json.dumps(GOOD) + "\nthanks")
    assert plain == wrapped
    assert {k: plain[k] for k in GOOD} == GOOD  # the reply's own fields come through unchanged
