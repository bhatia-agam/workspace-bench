"""association_hard (plan 0108) in the shared tables: the lucky guessers, the ATI scope, the
adapt tooling, the capable questions, the authoring validator, the read plan and the ledger."""

import hashlib
import importlib.util
import json

import pytest

from wsbench import readplan, registry
from wsbench.adapt import families as adapt_families
from wsbench.adapt import judge_inputs
from wsbench.baselines import lucky_guessing as lg
from wsbench.baselines import text_inversion as ti
from wsbench.capable import questions as capq

FAMILY = "association_hard"
OBSCURE = "ah-b1-ob04-aboriginal-tube-circular-breath"
COMPLEX = "ah-b1-cu01-frozen-concert-strings"
# sha256 of the `association` ledger entry (sorted JSON) as on 34de102e: this plan must not move it
ASSOCIATION_LEDGER_SHA256 = "53e932baefba1ca045945aba10272e7849cf21079d7e8b3e97b7ba59ee996f27"


@pytest.fixture(scope="module")
def items() -> dict[str, dict]:
    doc = json.loads(registry.bank_path(FAMILY).read_text(encoding="utf-8"))
    return {it["name"]: it for it in doc["items"]}


def test_lucky_guessing_builds_the_lists_in_bank_order(items):
    built = {it.id: it for it in lg.build_family(FAMILY)}
    assert set(built) == set(items)
    it = built[COMPLEX]
    assert it.lists == [items[COMPLEX]["mc"]["options"]] and not it.multi
    assert it.golds == [items[COMPLEX]["mc"]["gold_position"]] and it.n_options == [8]
    assert it.meta == {"topic": "an impossible-material instrument", "kind": "complex_unnatural"}
    assert lg.topic_of(built[OBSCURE]) == lg.fine_topic(items[OBSCURE]["mc"])
    assert FAMILY in lg.TOPIC_FAMILIES and lg.topic_source(FAMILY) == "meta"
    assert lg.analytic_floor(list(built.values())) == pytest.approx(1 / 8)
    assert "unusual material" in lg.DESCRIPTIONS[FAMILY]
    for name in ("FAMILY_RULES", "GUESS_QUESTION", "CANDS_FAMILIES", "MARK_FAMILIES"):
        assert FAMILY not in getattr(lg, name)
    # the easy family's builder and description are as they were
    assert lg.DESCRIPTIONS["association"] == (
        "which concept an unseen short scene evokes without naming it"
    )
    assert len(lg.build_family("association")) == 91


def test_ati_scope_leaves_the_family_out(real_families):
    assert "plan 0108" in ti.NOT_GATED[FAMILY]
    assert FAMILY not in ti.gated_families()
    with pytest.raises(ti.NotInScope, match="not gated"):
        ti.subset_entry(FAMILY)
    assert "association" not in ti.NOT_GATED  # the easy family keeps its (empty) entry


def test_no_adapted_set_carries_the_family(real_families):
    assert "plan 0108" in adapt_families.NOT_ADAPTED[FAMILY]
    assert FAMILY not in adapt_families.FAMILIES and FAMILY not in adapt_families.REGENERATE
    assert "association" in adapt_families.FAMILIES
    assert FAMILY not in judge_inputs.FAMILIES
    assert set(adapt_families.NOT_ADAPTED) <= set(ti.NOT_GATED)


def test_capable_asks_the_gate_question_of_each_kind(items):
    qs = {q.id: q for q in capq.build(FAMILY)}
    assert set(qs) == set(items)
    assert qs[OBSCURE].ask == f"{capq.NAME_REFERENT}\n\n{items[OBSCURE]['prompt']}"
    assert qs[COMPLEX].ask == f"{capq.NAME_COMPOUND}\n\n{items[COMPLEX]['prompt']}"
    assert qs[COMPLEX].golds[0] == "a violin made of ice" and "ice violin" in qs[COMPLEX].golds
    assert qs[COMPLEX].reference == 0.9 and qs[COMPLEX].meta["kind"] == "complex_unnatural"
    assert capq.build("association")[0].ask.startswith(capq.NAME_REFERENT)


def test_the_authoring_validator_refuses_the_family():
    path = registry.REPO_ROOT / ".claude/skills/wsb-new-questions/scripts/validate_bank.py"
    spec = importlib.util.spec_from_file_location("validate_bank_ah", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "plan 0108" in mod.NOT_AUTHORABLE[FAMILY] and FAMILY not in mod.REQUIRED


def test_read_plan_is_the_association_read(items):
    rows = readplan.plan(FAMILY)
    assert [s.row()["id"] for s in rows] == list(items)
    row, easy = rows[0].row(), readplan.plan("association")[0].row()
    for key in ("render", "positions", "layers", "suffix"):
        assert row[key] == easy[key], key
    assert row["render"] == "chat_summarize" and row["text"] == items[row["id"]]["prompt"]
    assert row["lite_positions"] == {"kind": "same"}
    assert FAMILY not in readplan.LITE_SITE_FAMILIES
    assert not (registry.family_root(FAMILY) / "lite_rule.json").exists()


def test_the_ledger_has_the_family_and_the_easy_entry_did_not_move():
    path = registry.REPO_ROOT / "tests/golden/manifest_0101_declared.json"
    families = json.loads(path.read_text(encoding="utf-8"))
    # the entry is the one declared with bank v3 (plan 0116); plan 0108 declared the first
    assert FAMILY in families and "0116" in str(families[FAMILY]["plan"])
    assert len(families) >= 7  # the six earlier entries stay
    blob = json.dumps(families["association"], sort_keys=True, ensure_ascii=False).encode()
    assert hashlib.sha256(blob).hexdigest() == ASSOCIATION_LEDGER_SHA256
