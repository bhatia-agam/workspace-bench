"""The user_modeling_hard bank (plan 0106 §2): ``bank.validate`` (V1-V14) on the committed bank
and on mutated copies, the header, the family's own leak test, and the builder on a fixture."""

import copy
import hashlib
import importlib.util
import json
from collections import Counter

import pytest

from wsbench import mc, registry
from wsbench.evals.association.user_modeling_hard import bank as bk

FAMILY = "user_modeling_hard"
FINE = "umh-fine-w1000-A"
MIXED = "umh-state-w4015-A"
THREE = "umh-three-w1000-B"
GOAL = "umh-stance-w1001-B"  # its goal list was redrawn (validation -> a chance to vent)
EXPERTISE = "umh-expertise-w1004-A"
# the authoring run's files this bank was built from (they stay out of the repo)
CANDIDATE_SHA256 = "4be2e2321bd3d88004cd39cf3815b5671da64273e0e680f65bf831cab737a7ee"
# (review r3: `optometrist` joined the profession pool; `profession` and `diet` got broader lists)
POOLS_SHA256 = "612443d26f61823eb442aea4abae2c3b99b64412aac291b6c430afd0040af1c2"


def _doc() -> dict:
    return json.loads(registry.bank_path(FAMILY).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def frozen():
    doc = _doc()
    pools_path = registry.resource_path(FAMILY, "option_pools.json")
    pools = json.loads(pools_path.read_text(encoding="utf-8"))
    return {k: v for k, v in doc.items() if k != "items"}, doc["items"], pools, pools_path


@pytest.fixture
def bank(frozen):
    header, items, pools, _path = frozen
    return copy.deepcopy(header), copy.deepcopy(items), pools


def item(items: list[dict], name: str) -> dict:
    return next(it for it in items if it["name"] == name)


def findings(header: dict, items: list[dict], pools: dict | None, **kw) -> list[str]:
    """``validate`` with the counted header keys recomputed, so a mutation shows its own rule."""
    return bk.validate({**header, **bk.counts(items)}, items, pools=pools, **kw)


def rules(found: list[str]) -> set[str]:
    return {f.split(" ", 1)[0] for f in found}


# ---------------------------------------------------------------- the committed bank


def test_the_committed_bank_is_valid(frozen):
    header, items, pools, pools_path = frozen
    assert bk.validate(header, items, pools=pools, sources={"option_pools.json": pools_path}) == []
    assert bk.validate(header, items) == []  # the judge's loader for a bank with no pools beside


def test_header(frozen):
    header, items, _pools, _path = frozen
    assert header["family"] == "user-modeling-hard" and header["version"] == 2
    assert header["subject"] == "Qwen/Qwen3.6-27B" and "status" not in header
    for key, want in bk.counts(items).items():
        assert header[key] == want, key
    # read from the header, not pinned: items may still leave the bank in validation (§2.3)
    assert header["n_items"] == len(items) and sum(header["kinds"].values()) == len(items)
    assert header["n_parts"] == sum(len(i["parts"]) for i in items)
    assert set(header["kinds"]) == set(bk.KINDS) and "life" not in bk.KINDS
    assert header["source_sha256"] == {
        "bank_candidate.json": CANDIDATE_SHA256,
        "option_pools.json": POOLS_SHA256,
    }
    for key in ("inclusion_rule", "known_issues", "gate", "read", "edits", "broader_by_type"):
        assert header[key], key
    assert isinstance(header["min_render_tokens"], int) and header["min_render_tokens"] > 0
    assert len(header["inclusion_rule"]) == 4
    edits = header["edits"]
    assert not set(edits["dropped"]) & {i["name"] for i in items}
    assert set(edits["kept_flagged"]) == {i["name"] for i in items if "flag" in i}


def test_item_shape(frozen):
    _header, items, _pools, _path = frozen
    for it in items:
        assert it["name"].startswith(f"umh-{it['kind']}-") and it["subfamily"] == it["kind"]
        assert it["name"].endswith("-" + it["request_variant"])
        assert it["readout"] == {"kind": "every_token"} and it["eval_render"] == "chat_context"
        assert it["target"] == " + ".join(p["gold"] for p in it["parts"])
        assert it["messages"][0] == {"role": "system", "content": "You are a helpful assistant."}
        # what stays out of the repo (plan 0106 §2.2)
        for key in ("qwen_reply_greedy", "open_probe_answers", "units", "intermediates", "attr"):
            assert key not in it, key
        assert set(it["authoring"]) == {"model", "wave", "cues", "tempting_wrong"}
        for p in it["parts"]:
            assert set(p["open_probe"]) == {"n_stated", "n_samples"}
            assert set(p["gate"]) == {"greedy", "n_correct", "n_samples", "stem_dropped"}


def test_one_gold_per_part_unique_options_and_the_seeded_order(frozen):
    _header, items, _pools, _path = frozen
    hist: Counter = Counter()
    for it in items:
        for k, p in enumerate(it["parts"]):
            opts = p["options"]
            assert [mc.fold(o) for o in opts].count(mc.fold(p["gold"])) == 1
            assert len({mc.fold(o) for o in opts}) == len(opts) == bk.n_options(p["type"])
            assert opts[p["gold_position"] - 1] == p["gold"]
            assert p["option_seed"] == f"umh-v1|{it['name']}|p{k}"
            # reproducible from the seed alone, whatever order the options come in
            assert bk.option_order(reversed(opts), p["option_seed"]) == opts
            assert bk.option_order(sorted(opts), p["option_seed"]) == opts
            hist[(len(opts), p["gold_position"])] += 1
    # the gold sits at every position of a 7-option list (roughly uniform: none above 25%)
    seven = {pos: n for (n_opts, pos), n in hist.items() if n_opts == 7}
    assert set(seven) == set(range(1, 8)) and max(seven.values()) / sum(seven.values()) < 0.25


def test_goal_lists_and_expertise_balance(frozen):
    _header, items, _pools, _path = frozen
    parts = [p for it in items for p in it["parts"]]
    for p in parts:
        if p["type"] == "goal":
            assert not {"validation", "reassurance"} <= set(p["options"])
    levels = Counter(p["gold"] for p in parts if p["type"] == "expertise")
    assert set(levels) == {"beginner", "intermediate", "advanced", "expert"}
    assert max(levels.values()) / sum(levels.values()) <= bk.EXPERTISE_MAX_SHARE
    redrawn = [p for p in parts if "redrawn" in p]
    assert all(p["type"] == "goal" for p in redrawn)
    # review r1 swapped the redrawn value of umh-stance-w1047-B out again (`someone to decide
    # for them`: the user asks the assistant to choose)
    REDRAWN_THEN_SWAPPED = item(items, "umh-stance-w1047-B")["parts"][0]  # noqa: N806
    assert REDRAWN_THEN_SWAPPED["redrawn"]["added"] not in REDRAWN_THEN_SWAPPED["options"]
    for p in redrawn:
        if p is REDRAWN_THEN_SWAPPED:  # the one named exception: its redrawn value left again
            assert p["redrawn"]["added"] in {s["removed"] for s in p["swapped"]}
        else:
            assert p["redrawn"]["added"] in p["options"]
        assert p["redrawn"]["removed"] not in p["options"]
        # the options-only guess was measured again on the redrawn list: none guessable (3 of 5)
        assert "stale" not in p["blind_guess"] and p["blind_guess"]["n"] == 5
        assert p["blind_guess"]["hits"] < 3 and "rerun" in p["blind_guess"]


# review r1 F3: stated, not implied (plan 0106 §2.4's own rule). The reviewer's seven, then the
# items of the same gold with the same stating pattern as one already dropped
STATED_R1 = (
    "umh-three-w1040-A",  # newlywed: "We only submitted the marriage registration last month"
    "umh-life-w1002-A",  # widowed: "My husband ... the first spring since his funeral"
    "umh-life-w2000-A",  # on sabbatical: "hold my post until next September ... my year off"
    "umh-life-w2008-A",  # studying abroad: "My student visa ... my host university"
    "umh-three-w1033-A",  # bricklayer: "a CV that wasn't about laying bricks on site"
    "umh-three-w1061-A",  # empty nester: "so their bedrooms sit empty"
    "umh-three-w2005-A",  # new parent: "the paternity... the leave forms ... Registered her"
    "umh-life-w1025-A",  # single parent, as the dropped umh-life-w1027-B
    "umh-three-w1020-A",
    "umh-three-w1058-A",
    "umh-two-w1032-A",  # recovering from surgery, as the dropped umh-three-w2004-A
    "umh-three-w1066-A",  # on sabbatical, as umh-life-w1010-A
    "umh-three-w2013-A",  # newlywed, as umh-three-w1040-A
    "umh-life-w1012-A",
    "umh-life-w2011-A",
    "umh-two-w2031-A",
)
# review r1 F3: distractors the reviewer found to be true of the user as well
# (umh-life-w1003-A left with the `life` kind in review r3)
ALSO_TRUE_R1 = (
    ("umh-stance-w1043-B", 0, "ammunition for an argument"),
    ("umh-three-w1010-B", 2, "anxious"),
)
# review r2: the state-distractor audit (every state part screened against the whole message)
ALSO_TRUE_R2 = (
    ("umh-two-w1051-A", 1, "embarrassed"),
    ("umh-state-w4014-A", 0, "frustrated"),
    ("umh-state-w4007-A", 1, "insecure"),
    ("umh-state-w4015-A", 0, "frustrated"),
    ("umh-state-w4015-A", 1, "disappointed"),
    ("umh-state-w4026-A", 1, "anxious"),
    ("umh-state-w4100-A", 1, "anxious"),
    ("umh-state-w4108-A", 1, "anxious"),
    ("umh-state-w4112-A", 1, "nostalgic"),
)
# review r2: a mixed-state list without the other situation's feeling was guessable twice
GUESSABLE_R2 = ("umh-state-w4005-A", "umh-state-w4023-A")
# review r3 S6(a): multi-trait items whose life-type part the chat states (the reviewer's four,
# then every other one read the same way), and the two other items the review names
STATED_R3 = (
    "umh-three-w2019-A",  # new homeowner: "Got the keys Friday and the first mortgage withdrawal"
    "umh-three-w1064-A",  # expecting a baby: "My wife's 20-week scan ... Her due date"
    "umh-three-w1018-A",  # unemployed: "The agency contract ended in March and nobody renewed it"
    "umh-three-w2020-A",  # recent immigrant: "Eight weeks since landing and my green card"
    "umh-two-w1037-A",  # expecting a baby, as umh-three-w1064-A
    "umh-three-w1026-A",
    "umh-three-w2021-A",
    "umh-two-w1042-A",  # changing careers: "I left accounting ... three weeks into a bootcamp"
    "umh-three-w1057-A",  # moving house: "The removal van's booked for Saturday ... the new flat"
    "umh-three-w1029-A",  # long-distance relationship: "six hours behind me ... the next flight"
    "umh-three-w2006-A",
    "umh-three-w1038-A",  # divorcing: "the family court will divide the shop lease and the house"
    "umh-three-w1055-A",  # newly single: "his name comes off it. Six years together"
    "umh-three-w2008-A",  # foster parent: "the boy who arrived last month ... the court order"
    "umh-two-w1011-A",  # halal: "the meat is zabiha certified"
    "umh-two-w1027-A",  # engaged: "since I proposed in March and the date's set"
)
# review r3 S6(b): the list without an also-true distractor was guessable twice
GUESSABLE_R3 = ("umh-state-w4021-A", "umh-stance-w1042-B")
# review r3 S6(b): the reviewer's cases and their analogues
ALSO_TRUE_R3 = (
    ("umh-three-w1010-B", 2, "frustrated"),
    ("umh-three-w1010-B", 2, "burned out"),
    ("umh-state-w1032-A", 0, "resentful"),
    ("umh-three-w1001-B", 2, "resentful"),
    ("umh-state-w1058-A", 0, "disappointed"),
    # found by the re-judging: the readouts state the distractor beside the gold
    ("umh-state-w1039-A", 0, "burned out"),
    ("umh-state-w1039-A", 0, "frustrated"),
    ("umh-state-w4100-A", 0, "frustrated"),
)


def test_review_r1_items_that_state_the_value_are_gone(frozen):
    header, items, _pools, _path = frozen
    names = {it["name"] for it in items}
    assert not names & set(STATED_R1)
    assert set(STATED_R1) <= set(header["edits"]["dropped"])
    # the reviewer's fourth state case had no list that the options-only guesser could not
    # pick the gold from once `anxious` was out: redrawn once, then dropped (the build's rule)
    assert "umh-state-w1021-A" not in names
    assert "guessable" in header["edits"]["dropped"]["umh-state-w1021-A"]
    for name in GUESSABLE_R2:  # review r2: the same rule
        assert name not in names and "guessable" in header["edits"]["dropped"][name]
    r3 = (*STATED_R3, *GUESSABLE_R3)  # review r3: the same two rules
    assert not names & set(r3) and set(r3) <= set(header["edits"]["dropped"])
    assert all("guessable" in header["edits"]["dropped"][name] for name in GUESSABLE_R3)
    assert len(header["edits"]["dropped"]) == 28 + len(r3) == 46  # 28 through review r2
    assert 9 + len(STATED_R1) + 1 + len(GUESSABLE_R2) == 28
    # review r3 removed the `life` kind: 28 items of the candidate, 8 of them dropped by name
    # before (so 20 left the bank with the kind), and no item of the bank is of that kind
    life = header["edits"]["dropped_kinds"]
    assert set(life) == {"life"} and life["life"]["n_items"] == 28
    assert sum(name.startswith("umh-life-") for name in header["edits"]["dropped"]) == 8
    assert not [it for it in items if it["kind"] == "life" or it["name"].startswith("umh-life-")]
    assert header["n_items"] == 177 - 46 - (28 - 8) == 111
    # the one life-type part left is flagged for the owner (its occupation gold was relabelled)
    assert [
        (it["name"], k) for it in items for k, p in enumerate(it["parts"]) if p["type"] == "life"
    ] == [("umh-two-w1035-A", 1)]
    assert "umh-two-w1035-A" in header["edits"]["kept_flagged"]


def test_review_r1_distractors_that_are_also_true_are_swapped(frozen):
    header, items, pools, _path = frozen
    for name, k, value in (*ALSO_TRUE_R1, *ALSO_TRUE_R2, *ALSO_TRUE_R3):
        p = item(items, name)["parts"][k]
        assert value not in p["options"], (name, k, value)
        assert value in [s["removed"] for s in p["swapped"]]
    swapped = [(it, k, p) for it in items for k, p in enumerate(it["parts"]) if "swapped" in p]
    # r1: 19 parts / 20 swaps, less the two parts of umh-state-w4005-A (dropped in r2); r2: 10
    # swaps, 9 of them in parts r1 had not touched: 26 parts / 28 swaps. Review r3 took 11 of
    # those parts (12 swaps) out with their items (7 parts / 8 swaps of the `life` kind, three
    # parts of dropped multi-trait items, umh-state-w4021-A p0) and added 8 swaps, 5 of them in
    # parts not touched before
    assert len(swapped) == 17 + 9 - 11 + 5 == 20
    assert len(header["edits"]["options_swapped"]) == 18 + 10 - 12 + 8 == 24
    for it, k, p in swapped:
        assert len(p["options"]) == bk.n_options(p["type"])  # the count is kept
        for s in p["swapped"]:
            assert s["added"] in p["options"] and s["removed"] not in p["options"]
            assert s["added"] in bk.pool_values(pools, p["type"]) and s["added"] != p["gold"]
        # the order is still the seeded shuffle of the final list (the position policy)
        assert p["options"] == bk.option_order(p["options"], bk.option_seed(it["name"], k))
        # the options-only guess was measured again on the final list: none guessable
        assert "stale" not in p["blind_guess"] and p["blind_guess"]["n"] == 5
        assert p["blind_guess"]["hits"] < 3 and "swapped" in p["blind_guess"]["rerun"]
        # never a value of a sibling part (V7), never the excluded goal pair (V11)
        assert set(p["near_neighbours"]) <= set(p["options"]) - {p["gold"]}
    # a swap never touches a user message: every chat is the candidate's, byte for byte
    assert header["source_sha256"]["bank_candidate.json"] == CANDIDATE_SHA256


def test_no_part_gold_or_form_in_its_chat(frozen):
    """The family's own leak test: ``tests/test_task_notes.py`` reads only top-level ``target``
    fields, which is vacuous for part golds. V8 through ``mc.form_in`` on the committed bank."""
    _header, items, _pools, _path = frozen
    for it in items:
        chat = bk.user_text(it)
        assert chat == it["messages"][1]["content"]
        for k, p in enumerate(it["parts"]):
            hits = mc.form_hits(chat, [p["gold"], *p["forms"]])
            assert not hits, (it["name"], k, hits)


def test_labels(frozen):
    _header, items, _pools, _path = frozen
    for it in items:
        for p in it["parts"]:
            if it.get("mixed_state"):
                assert p["judge_label"] == "emotional state" and p["type"] == "state"
            else:
                assert p["judge_label"] == p["attr_label"]
            assert not bk.CHAT_BOUND.search(p["judge_label"].lower())
    mixed = [it for it in items if it.get("mixed_state")]
    assert mixed and all(it["kind"] == "state" and len(it["parts"]) == 2 for it in mixed)
    ordinal = [
        p["attr_label"] for it in mixed for p in it["parts"] if "situation" in p["attr_label"]
    ]
    assert ordinal  # the gated ordinal labels stay as metadata
    assert not bk.CHAT_BOUND.search("current life situation")  # a plain label, not chat-bound


# ---------------------------------------------------------------- each rule fires


def test_v1_names_kinds_and_part_counts(bank):
    header, items, pools = bank
    items.append(copy.deepcopy(items[0]))
    assert "V1" in rules(findings(header, items, pools))
    header, items, pools = bank
    del items[-1]
    item(items, FINE)["name"] = "umh fine/1"
    assert any("label-safe" in f for f in findings(header, items, pools))
    item(items, THREE)["kind"] = "four"
    assert any("unknown kind" in f for f in findings(header, items, pools))


def test_v1_parts_must_fit_the_kind(bank):
    header, items, pools = bank
    item(items, THREE)["parts"].pop()
    assert any(f.startswith(f"V1 {THREE}: a three item") for f in findings(header, items, pools))
    del item(items, MIXED)["mixed_state"]
    assert any(f.startswith(f"V1 {MIXED}: mixed_state") for f in findings(header, items, pools))


def test_v2_messages(bank):
    header, items, pools = bank
    item(items, FINE)["messages"].append({"role": "assistant", "content": "Sure."})
    assert rules(findings(header, items, pools)) == {"V2"}
    item(items, FINE)["messages"] = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": " "},
    ]
    assert rules(findings(header, items, pools)) == {"V2"}


def test_v3_options(bank):
    header, items, pools = bank
    p = item(items, FINE)["parts"][0]
    p["options"][0], p["options"][1] = p["options"][1], p["options"][0]
    p["gold_position"] = p["options"].index(p["gold"]) + 1
    found = findings(header, items, pools)
    assert rules(found) == {"V3"} and "seeded shuffle" in found[0]
    p["gold_position"] = 7 if p["gold_position"] != 7 else 6
    assert any("gold_position" in f for f in findings(header, items, pools))
    p["options"] = p["options"][:-1]
    assert any("6 options, a fine_occ part has 7" in f for f in findings(header, items, pools))
    q = item(items, THREE)["parts"][1]
    q["options"][0] = q["options"][1]
    assert any("options repeat" in f for f in findings(header, items, pools))
    r = item(items, MIXED)["parts"][0]
    r["options"][0] = "cannot tell from the readout"
    assert any("cannot-tell text" in f for f in findings(header, items, pools))
    s = item(items, GOAL)["parts"][0]
    s["option_seed"] = "umh-v1|other|p0"
    assert any("option_seed" in f for f in findings(header, items, pools))


def test_v4_pools_and_neighbours(bank):
    header, items, pools = bank
    p = item(items, FINE)["parts"][0]
    p["near_neighbours"] = [p["gold"]]
    assert rules(findings(header, items, pools)) == {"V4"}
    header, items, pools = bank[0], copy.deepcopy(bank[1]), bank[2]
    p = item(items, FINE)["parts"][0]
    p["near_neighbours"] = []
    k = next(i for i, o in enumerate(p["options"]) if o != p["gold"])
    p["options"][k] = "chimney sweep"
    p["options"] = bk.option_order(p["options"], p["option_seed"])
    p["gold_position"] = p["options"].index(p["gold"]) + 1
    found = findings(header, items, pools)
    assert rules(found) == {"V4"} and "outside the fine_occ pool" in found[0]
    assert "V4" not in rules(findings(header, items, None))  # no pools file: the shape only


def test_v5_near_duplicate_options(bank):
    assert bk.near_duplicate("school nurse", "school nurses")
    assert bk.near_duplicate("a chance to vent", "chance to vent")
    assert bk.near_duplicate("complete novice", "novice")  # the subset test
    assert not bk.near_duplicate("school nurse", "ICU nurse")
    assert not bk.near_duplicate("validation", "reassurance")  # the pair V5 cannot see: V11
    header, items, _pools = bank
    p = item(items, FINE)["parts"][0]
    k = next(i for i, o in enumerate(p["options"]) if o == "ICU nurse")
    p["options"][k] = "school nurses"
    assert "V5" in rules(findings(header, items, None))


def test_v6_forms(bank):
    header, items, pools = bank
    p = item(items, FINE)["parts"][0]
    p["forms"] = [*p["forms"], "ICU nurse"]
    found = findings(header, items, pools)
    assert rules(found) == {"V6"} and "collides with the option 'ICU nurse'" in found[0]
    p["forms"] = [*p["forms"][:-1], "nurse"]
    found = findings(header, items, pools)
    assert any("is a broader term of type 'fine_occ'" in f for f in found)
    p["forms"] = [*p["forms"][:-1], "school health nurse"]  # CONTAINS a broader term: stays
    assert "V6" not in rules(findings(header, items, pools))


def test_v7_within_an_item(bank):
    header, items, pools = bank
    a, b = item(items, MIXED)["parts"]
    a["forms"] = [*a["forms"], b["options"][0]]
    found = findings(header, items, pools)
    assert any(f.startswith(f"V7 {MIXED} p0") for f in found)
    header, items, pools = bank[0], copy.deepcopy(bank[1]), bank[2]
    it = item(items, MIXED)
    it["parts"][1] = copy.deepcopy(it["parts"][0])
    assert any("two parts share a gold" in f for f in findings(header, items, None))


def test_v8_a_stated_value(bank):
    header, items, pools = bank
    it = item(items, FINE)
    word = next(w for w in bk.user_text(it).split() if len(w) > 7 and w.isalpha())
    it["parts"][0]["forms"].append(word)
    found = findings(header, items, pools)
    assert rules(found) == {"V8"} and "stated, not implied" in found[0]


def test_v9_gate_evidence(bank):
    header, items, pools = bank
    item(items, FINE)["parts"][0]["gate"]["n_correct"] = 7
    assert rules(findings(header, items, pools)) == {"V9"}
    item(items, FINE)["parts"][0]["gate"]["n_correct"] = 8
    item(items, FINE)["parts"][0]["open_probe"]["n_stated"] = 2
    assert rules(findings(header, items, pools)) == {"V9"}


def test_v10_header_counts_and_sources(bank, tmp_path):
    header, items, pools = bank
    header["n_items"] += 1
    found = bk.validate(header, items, pools=pools)
    assert rules(found) == {"V10"} and "n_items" in found[0]
    header, items, pools = bank[0], bank[1][:-1], bank[2]
    header["n_items"] -= 1
    assert "V10" in rules(bk.validate(header, items, pools=pools))  # the other counts moved too
    other = tmp_path / "pools.json"
    other.write_text("{}")
    found = findings(bank[0], bank[1], pools, sources={"option_pools.json": other})
    assert any(f.startswith("V10 source_sha256[option_pools.json]") for f in found)


def test_v11_validation_and_reassurance(bank):
    header, items, pools = bank
    p = item(items, GOAL)["parts"][0]
    assert p["gold"] == "reassurance" and "validation" not in p["options"]
    k = next(i for i, o in enumerate(p["options"]) if o != p["gold"])
    p["options"][k] = "validation"
    p["near_neighbours"] = []
    assert "V11" in rules(findings(header, items, pools))


def test_v12_expertise_balance(bank):
    header, items, pools = bank
    # too few expertise parts for a four-level scale to meet the bar: not checked
    few = [it for it in items if it["kind"] in ("stance", "fine")][:20]
    few += [it for it in items if it["kind"] == "expertise" and it["target"] == "beginner"][:2]
    assert "V12" not in rules(findings(header, copy.deepcopy(few), pools))
    for it in items:
        for p in it["parts"]:
            if p["type"] == "expertise" and p["gold"] == "expert":
                p["gold"], p["forms"] = "beginner", []
                p["gold_position"] = p["options"].index("beginner") + 1
    found = findings(header, items, pools)
    assert rules(found) == {"V12"} and "'beginner' is the gold of 12 of 18" in found[0]


def test_v13_judge_labels(bank):
    header, items, pools = bank
    p = item(items, MIXED)["parts"][0]
    p["judge_label"] = p["attr_label"]  # an ordinal label: the chat-blind check could not read it
    found = [f for f in findings(header, items, pools) if f.startswith("V13")]
    assert len(found) == 2 and "needs the chat" in found[1]
    header, items, pools = bank[0], copy.deepcopy(bank[1]), bank[2]
    item(items, FINE)["parts"][0]["judge_label"] = "job"
    assert rules(findings(header, items, pools)) == {"V13"}


def test_v14_min_render_tokens(bank):
    header, items, pools = bank
    del header["min_render_tokens"]
    assert rules(findings(header, items, pools)) == {"V14"}
    assert findings(header, items, pools, require_tokens=False) == []
    header["min_render_tokens"] = True
    assert rules(findings(header, items, pools)) == {"V14"}


# ---------------------------------------------------------------- the builder


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_user_modeling_hard_bank",
        registry.REPO_ROOT / "scripts/build_user_modeling_hard_bank.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _candidate(frozen, names: list[str]) -> dict:
    """A candidate file in the authoring run's shape, rebuilt from committed items (the real
    one stays out of the repo): the gating open-probe condition under its key, the candidate's
    own option order, the goal list as it was before the redraw, one form the builder removes."""
    _header, items, _pools, _path = frozen
    out = []
    for name in names:
        it = copy.deepcopy(item(items, name))
        for p in it["parts"]:
            p["open_probe"] = {"second|q1": p["open_probe"], "same|q1": {"n_stated": 0}}
            p["options"] = sorted(p["options"])  # the candidate's order is discarded
            if "redrawn" in p:
                k = p["options"].index(p["redrawn"]["added"])
                p["options"][k] = p["redrawn"]["removed"]
                p["near_neighbours"] = [*p["near_neighbours"], p["redrawn"]["removed"]]
            for swap in reversed(p.get("swapped", ())):  # the list as it was before the swap
                p["options"][p["options"].index(swap["added"])] = swap["removed"]
                p["near_neighbours"] = [x for x in p["near_neighbours"] if x != swap["added"]]
            for key in ("judge_label", "gold_position", "option_seed", "redrawn", "swapped"):
                p.pop(key, None)
            p["blind_guess"] = {"hits": 0, "n": 5, "chance": 0.14}
        it["parts"][0]["forms"].append("junk form")
        it["qwen_reply_greedy"] = "a reply that stays out of the bank"
        it["authoring"]["user_text"] = "stays out"
        out.append(it)
    return {"subject": "Qwen/Qwen3.6-27B", "items": out}


@pytest.fixture
def build(frozen, tmp_path, monkeypatch):
    names = [THREE, FINE, MIXED, GOAL, EXPERTISE]
    mod = _builder()
    monkeypatch.setattr(mod, "DROP", {EXPERTISE: "dropped by the test"})
    monkeypatch.setattr(mod, "KEEP_FLAGGED", {})
    monkeypatch.setattr(mod, "GOLD_RELABEL", {})  # (its item is not in the fixture)
    monkeypatch.setattr(mod, "FORM_DROPS", [(n, 0, "junk form", "test") for n in names[:4]])
    swaps = {k: v for k, v in mod.OPTION_SWAPS.items() if k.split("|")[0] in names}
    assert set(swaps) == {f"{MIXED}|p0", f"{MIXED}|p1"}  # the fixture's swapped parts
    monkeypatch.setattr(mod, "OPTION_SWAPS", swaps)
    monkeypatch.setattr(mod, "load_tokenizer", lambda model: None)  # as on a box without it
    src, pools = tmp_path / "bank_candidate.json", tmp_path / "option_pools.json"
    src.write_text(json.dumps(_candidate(frozen, names), ensure_ascii=False), encoding="utf-8")
    pools.write_bytes(frozen[3].read_bytes())
    argv = ["--src", str(src), "--pools", str(pools), "--out", str(tmp_path / "out" / "items.json")]
    (tmp_path / "out").mkdir()
    return mod, argv, tmp_path / "out"


def test_builder_is_deterministic_and_reproduces_the_committed_items(build, frozen, capsys):
    mod, argv, out = build
    assert mod.main(argv) == 0
    doc = json.loads((out / "items.json").read_text(encoding="utf-8"))
    # (kind, name) order; the dropped item is gone; no tokenizer -> no min_render_tokens
    assert [i["name"] for i in doc["items"]] == [THREE, MIXED, GOAL, FINE]
    assert "min_render_tokens" not in doc and doc["n_items"] == 4 and doc["n_parts"] == 7
    assert doc["edits"]["dropped"] == {EXPERTISE: "dropped by the test"}
    assert doc["source_sha256"]["option_pools.json"] == POOLS_SHA256
    committed = {i["name"]: i for i in frozen[1]}
    for it in doc["items"]:  # the fixes, the redraw, the re-run guess and the seeded order
        want = copy.deepcopy(committed[it["name"]])
        for p in want["parts"]:
            if "redrawn" not in p and "swapped" not in p:  # (those carry the re-run guess)
                p["blind_guess"] = {"hits": 0, "n": 5}  # the fixture's own record
        assert it == want, it["name"]
    goal = doc["items"][2]["parts"][0]
    assert goal["redrawn"] == {"removed": "validation", "added": "a chance to vent"}
    assert doc["edits"]["lists_redrawn"] == [
        [GOAL, 0, "reassurance", "validation", "a chance to vent"]
    ]
    # review r1: the mixed item's two swapped distractors are applied again by the builder
    assert doc["edits"]["options_swapped"] == [
        [MIXED, k, gold, out_v, new_v, why]
        for k, gold in ((0, "betrayed"), (1, "burned out"))
        for out_v, new_v, why in mod.OPTION_SWAPS[f"{MIXED}|p{k}"]
    ]
    assert "junk form" not in json.dumps(doc["items"]) and "stays out" not in json.dumps(doc)
    # a bank built without the tokenizer is one the judge's loader refuses (V14)
    header = {k: v for k, v in doc.items() if k != "items"}
    assert [f.split()[0] for f in bk.validate(header, doc["items"])] == ["V14"]
    assert "validation findings: 0" in capsys.readouterr().out
    # deterministic: --check passes, a second run refuses, an edited file fails the check
    first = (out / "items.json").read_bytes()
    assert mod.main([*argv, "--check"]) == 0 and (out / "items.json").read_bytes() == first
    with pytest.raises(SystemExit, match="exists"):
        mod.main(argv)
    (out / "items.json").write_bytes(first.replace(b"grieving", b"grieving "))
    assert mod.main([*argv, "--check"]) == 1


def test_builder_moves_a_kind_outside_the_headline(build):
    mod, argv, out = build
    assert mod.main([*argv, "--outside-headline", "stance"]) == 0
    main = json.loads((out / "items.json").read_text(encoding="utf-8"))
    side = json.loads((out / mod.SIDE_FILE).read_text(encoding="utf-8"))
    assert [i["name"] for i in main["items"]] == [THREE, MIXED, FINE] and "stance" not in main[
        "kinds"
    ]
    assert [i["name"] for i in side["items"]] == [GOAL] and side["kinds"] == {"stance": 1}
    assert side["n_parts"] == 1 and "outside the headline" in side["note"] and "note" not in main
    assert mod.main([*argv, "--outside-headline", "stance", "--check"]) == 0
    with pytest.raises(SystemExit, match="unknown kind"):
        mod.main([*argv, "--outside-headline", "nonsense", "--check"])


def test_builder_refuses_a_table_entry_that_is_not_in_the_source(build, monkeypatch):
    mod, argv, _out = build
    monkeypatch.setattr(mod, "DROP", {"umh-life-w9999-A": "a typo"})
    with pytest.raises(SystemExit, match="not in --src"):
        mod.main(argv)


def test_builder_tables_are_the_headers(frozen):
    mod = _builder()
    edits = frozen[0]["edits"]
    assert edits["dropped"] == mod.DROP and edits["kept_flagged"] == mod.KEEP_FLAGGED
    assert [tuple(x) for x in edits["forms_removed"]] == mod.FORM_DROPS
    assert {f"{n}|p{k}" for n, k, *_ in edits["lists_redrawn"]} == set(mod.REGUESS)
    assert max(mod.REGUESS.values()) < mod.GUESSABLE_AT
    want = [
        [key.split("|p")[0], int(key.split("|p")[1]), out_v, new_v, why]
        for key, rows in mod.OPTION_SWAPS.items()
        for out_v, new_v, why in rows
    ]
    got = [[n, k, out_v, new_v, why] for n, k, _gold, out_v, new_v, why in edits["options_swapped"]]
    assert sorted(got) == sorted(want)
    # (review r3: a relabelled gold changes its list too, so its guess is re-run as a swap's is)
    assert set(mod.REGUESS_SWAPS) == set(mod.OPTION_SWAPS) | set(mod.GOLD_RELABEL)
    assert max(mod.REGUESS_SWAPS.values()) < mod.GUESSABLE_AT
    assert frozen[0]["inclusion_rule"] == mod.INCLUSION_RULE


class FakeTokenizer:
    """One token per whitespace word plus four template tokens per turn."""

    def apply_chat_template(self, messages, **_kw):
        return [0] * sum(4 + len(m["content"].split()) for m in messages)

    def convert_ids_to_tokens(self, ids):
        return ["x"] * len(ids)

    def decode(self, ids):
        return "x"


def test_min_render_tokens_is_the_shortest_render(frozen):
    mod = _builder()
    items = frozen[1][:5]
    want = min(sum(4 + len(m["content"].split()) for m in it["messages"]) for it in items)
    assert mod.min_render_tokens(items, FakeTokenizer()) == want


def test_bank_file_shas_are_not_pinned_before_validation():
    """Plan 0106 §2.3: the bank's sha256 enters the tests only after validation (items may
    still leave the bank); until then its SHAPE is pinned above. The pools file is final."""
    pools = registry.resource_path(FAMILY, "option_pools.json")
    assert hashlib.sha256(pools.read_bytes()).hexdigest() == POOLS_SHA256


# ---------------------------------------------------------------- review r3 (2026-11-23)


def test_review_r3_the_relabelled_gold(frozen):
    """Owner decision: the subject itself answers "Optometrist" for umh-two-w1035-A, so the gold
    `optician` is `optometrist`; `optician` is not kept as a distractor (also true of the user)."""
    header, items, pools, _path = frozen
    mod = _builder()
    p = item(items, "umh-two-w1035-A")["parts"][0]
    assert p["gold"] == "optometrist" and p["relabelled"] == {
        "from": "optician",
        "to": "optometrist",
    }
    assert "optician" not in p["options"] and "optician" not in p["near_neighbours"]
    assert not [f for f in p["forms"] if mc.fold(f) in ("optician", "optometrist")]
    assert p["gate"]["greedy"] == "Optometrist"
    assert "optometrist" in bk.pool_values(pools, "profession")
    assert header["edits"]["golds_relabelled"] == [
        ["umh-two-w1035-A", 0, old, new, why] for old, new, _forms, why in mod.GOLD_RELABEL.values()
    ]
    assert p["forms"] == mod.GOLD_RELABEL["umh-two-w1035-A|p0"][2]
    assert p["blind_guess"]["hits"] < mod.GUESSABLE_AT and "stale" not in p["blind_guess"]
    assert [
        (it["name"], k) for it in items for k, q in enumerate(it["parts"]) if "relabelled" in q
    ] == [("umh-two-w1035-A", 0)]


def test_review_r3_loose_forms_are_gone(frozen):
    """S6(c): no part lists a form the builder's FORM_RULES name for its gold, no form is a bare
    two-letter code, and the header records every removal."""
    header, items, _pools, _path = frozen
    mod = _builder()
    rules_of = {(gold, form) for gold, form, _why in mod.FORM_RULES}
    assert len(rules_of) == len(mod.FORM_RULES)
    for it in items:
        for k, p in enumerate(it["parts"]):
            for f in p["forms"]:
                assert (p["gold"], f) not in rules_of, (it["name"], k, f)
                assert sum(ch.isalpha() for ch in f) > mod.SHORT_FORM or " " in f, (it["name"], f)
    removed = header["edits"]["forms_removed_r3"]
    assert removed and all(
        (gold, form) in rules_of or why == mod.SHORT_FORM_WHY for _n, _k, gold, form, why in removed
    )
    names = {it["name"] for it in items}
    assert {n for n, *_ in removed} <= names
    # the reviewer's named cases
    gone = {(n, k, form) for n, k, _gold, form, _why in removed}
    for case in (
        ("umh-state-w1025-A", 0, "let down by a friend"),
        ("umh-two-w1046-A", 1, "pattern designer"),
        ("umh-expertise-w1014-A", 0, "moderate"),
        ("umh-expertise-w1017-A", 0, "master"),
        ("umh-three-w1000-B", 1, "AR"),
    ):
        assert case in gone, case


def test_review_r3_broader_classes_for_occupations(frozen):
    """S2 (b): the `profession` type has a broader list (the head nouns of its two-word values),
    no form of the bank is one of them (V6), and no broader term is a gold or an option."""
    header, items, _pools, _path = frozen
    broader = header["broader_by_type"]
    assert {"mechanic", "driver", "engineer", "developer", "analyst"} <= set(broader["profession"])
    values = {mc.fold(x) for it in items for p in it["parts"] for x in p["options"]}
    for t in ("profession", "diet"):
        assert broader[t] and not {mc.fold(x) for x in broader[t]} & values, t


def test_the_biography_request_count_in_the_public_docs_is_the_banks(frozen):
    """Review r3 S5: README.md and NOTICE.md said 149 and 132 for a bank with 130. The number
    each states for the chats that end in the biography request is tied to the bank here."""
    import re

    header, items, _pools, _path = frozen
    n = sum(it["request_variant"] == "A" for it in items)
    request = header["request_variants"]["A"]
    assert n == sum(it["messages"][-1]["content"].endswith(request) for it in items) == 93
    assert all(
        (it["request_variant"] == "A") == it["messages"][-1]["content"].endswith(request)
        for it in items
    )
    for name in ("README.md", "NOTICE.md"):
        text = (registry.REPO_ROOT / name).read_text(encoding="utf-8")
        stated = re.findall(r"biography\s+request\s+that\s+ends\s+(\d+)\s+of\s+them", text)
        assert stated == [str(n)], (name, stated)
    family = (registry.family_root(FAMILY) / "README.md").read_text(encoding="utf-8")
    assert f"{n} of the {len(items)}" in family
