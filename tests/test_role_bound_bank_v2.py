"""role_bound_association bank v2: items.json without the 4 pairs whose stories carry a stray tab,
on items.json's read plan and option lists (cached calls stay valid)."""

import json

from wsbench import readplan, reads, registry
from wsbench.adapt import store
from wsbench.evals.role_bound_association import gate, prompts
from wsbench.evals.role_bound_association import judge as rb

FAMILY = "role_bound_association"
V1 = registry.REPO_ROOT / "evals/role_bound_association/items.json"
V2 = registry.REPO_ROOT / "evals/role_bound_association/items_v2.json"
GARBLED = {  # the four stories with a tab inside a word, e.g. "mildly amusing \tray without"
    "oa-boss-employee-envy-ba",
    "oa-veteran-recruit-lookdown-ba",
    "oa-officer-informant-protect-ba",
    "oa-guard-prisoner-fear-ab",
}


def _v1() -> list[dict]:
    return json.loads(V1.read_text(encoding="utf-8"))


def _v2() -> dict:
    return json.loads(V2.read_text(encoding="utf-8"))


def test_v2_is_registered_and_supersedes_items_json():
    raw = _v2()
    assert registry.bank_path(FAMILY) == V2 == registry.frozen_bank_path(FAMILY)
    assert raw["version"] == 2 and raw["supersedes"] == raw["read_plan_bank"] == V1.name
    assert raw["family"] == FAMILY and len(raw["items"]) == 92


def test_v2_drops_the_garbled_stories_and_their_pair_partners():
    v1, raw = _v1(), _v2()
    assert {it["id"] for it in v1 if "\t" in it["stimulus"]} == GARBLED  # nothing else garbled
    pairs = {it["pair_id"] for it in v1 if it["id"] in GARBLED}
    assert set(raw["dropped"]) == pairs and len(pairs) == 4
    # every other item byte for byte, in order; whole pairs only (pair-v1 scores pairs)
    assert raw["items"] == [it for it in v1 if it["pair_id"] not in pairs]
    kept = {it["pair_id"] for it in raw["items"]}
    assert all(sum(it["pair_id"] == p for it in raw["items"]) == 2 for p in kept)
    assert not any("\t" in json.dumps(it, ensure_ascii=False) for it in raw["items"])
    assert not any(c in it["stimulus"] for it in raw["items"] for c in "\t\r\x0b\x0c")


def test_read_plan_and_options_stay_items_json(monkeypatch):
    """One read, one plan_sha: bank v2 reads at items.json's 100 rows, and every kept item's
    option block (distractor names drawn from items.json's pool) is items.json's, so cached
    judge calls re-score bank v2 with no new call."""
    after_rows = [s.row() for s in readplan.plan(FAMILY)]
    after_sha = reads.plan_sha(FAMILY)
    items, pool = rb.load_items()
    lex = gate.load_lexicon()
    after = rb.blocks_of(items, pool, lex)
    assert len(items) == 92 and len(pool) == 100 == len(after_rows)
    monkeypatch.setenv(registry.BANK_FILE_ENV_PREFIX + "ROLE_BOUND_ASSOCIATION", str(V1))
    assert [s.row() for s in readplan.plan(FAMILY)] == after_rows
    assert reads.plan_sha(FAMILY) == after_sha
    v1, pool1 = rb.load_items()
    assert v1 == pool1 == pool
    before = rb.blocks_of(v1, pool1, lex)
    assert {i: after[i] for i in after} == {i: before[i] for i in after}


def test_read_plan_bank_works_for_a_bank_keyed_on_id(tmp_path):
    a = {"id": "a", "pair_id": "p", "stimulus": "A story."}
    b = {"id": "b", "pair_id": "q", "stimulus": "Another story."}
    (tmp_path / "items.json").write_text(json.dumps([a, b]), encoding="utf-8")
    v2 = tmp_path / "items_v2.json"
    v2.write_text(json.dumps({"read_plan_bank": "items.json", "items": [b]}), encoding="utf-8")
    header, items = readplan.bank_file(v2)
    assert items == [b] and readplan.read_plan_items(v2, header, items) == [a, b]


def test_stamp_keeps_the_call_key():
    assert prompts.CALL_VERSION == "oa-v3.1" and prompts.BANK_TAG == "bank-v2"
    assert prompts.PROMPT_VERSION == "oa-v3.1+bank-v2" == registry.get(FAMILY).judge.prompt_version


def test_instrument_follows_the_judged_bank(monkeypatch, tmp_path):
    """The registered bank v2 stamps +bank-v2; the frozen items.json and an adapted plain-list
    bank stamp the call key alone."""
    assert rb.instrument() == "oa-v3.1+bank-v2"
    monkeypatch.setenv("WSB_BANK_FILE_ROLE_BOUND_ASSOCIATION", str(V1))
    assert rb.instrument() == "oa-v3.1"
    monkeypatch.delenv("WSB_BANK_FILE_ROLE_BOUND_ASSOCIATION")
    adapted = json.loads(V1.read_text(encoding="utf-8"))[:2]
    (tmp_path / f"{FAMILY}.json").write_text(json.dumps(adapted), encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert rb.instrument() == "oa-v3.1"


def test_an_adapted_bank_with_the_v2_header_keeps_the_call_key(monkeypatch, tmp_path):
    """adapt.run.freeze wraps a new adapted bank in the registered bank's header (version 2,
    changes, dropped) plus an ``adapt`` record; it still stamps the call key alone, never
    +bank-v2."""
    header, items = store.original_bank(FAMILY)
    assert header["version"] == 2
    bank = {**header, "adapt": {"model": "m", "hf_id": "org/m"}, "items": items[:2]}
    (tmp_path / f"{FAMILY}.json").write_text(json.dumps(bank), encoding="utf-8")
    monkeypatch.setenv(registry.BANK_ROOT_ENV, str(tmp_path))
    assert rb.instrument() == "oa-v3.1"
    # the same header without the adapt record is the registered bank's: +bank-v2
    del bank["adapt"]
    (tmp_path / f"{FAMILY}.json").write_text(json.dumps(bank), encoding="utf-8")
    assert rb.instrument() == "oa-v3.1+bank-v2"


def test_an_adapted_bank_plans_its_own_items():
    header, items = store.original_bank(FAMILY)
    assert readplan.READ_PLAN_BANK not in header and header["supersedes"] == V1.name
    assert len(items) == 92
