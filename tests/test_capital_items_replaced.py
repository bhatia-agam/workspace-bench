"""2026-11-04: the country<->capital items leave basic_readout (bank v8),
multilingual (bank v5) and basic_readout_mt (bank v7), each replaced by a new gated item of the same
kind, so every bank keeps its size. Kept items are byte-identical to the frozen banks'."""

import collections
import json
import re
from pathlib import Path

import pytest

from wsbench import readplan, registry
from wsbench.banks import label_of, load_bank
from wsbench.basic.prompts import prompt_version_of
from wsbench.multitoken import prompts as mp
from wsbench.multitoken.options import alias_note, option_aliases

REPO = Path(__file__).resolve().parents[1]
CAPITALS = (
    "athens",
    "berlin",
    "cairo",
    "madrid",
    "moscow",
    "nairobi",
    "ottawa",
    "paris",
    "rome",
    "tokyo",
)
BR_DROP = [f"br-ent-cap-{c}" for c in CAPITALS]
BR_ADD = [
    "br-ent-ath-biles",
    "br-ent-ath-phelps",
    "br-ent-ath-tendulkar",
    "br-ent-lmk-angkor",
    "br-ent-lmk-borobudur",
    "br-ent-lmk-machu",
    "br-ent-lmk-petra",
    "br-ent-mus-coltrane",
    "br-ent-mus-goodman",
    "br-ent-mus-starr",
]
ML_DROP = [
    "b3-ml-de-capital-austria",
    "b3-ml-fr-capital-england",
    "b3-ml-it-capital-france",
    "b3-ml-pt-capital-japan",
]
ML_ADD = [
    "b3-ml-de-family-nephew",
    "b3-ml-fr-color-snow",
    "b3-ml-it-family-aunt",
    "b3-ml-pt-color-grass",
]
BANKS = {  # family: (frozen bank, new bank, new version, dropped, added)
    "basic_readout": ("items_v7.json", "items_v8.json", 8, BR_DROP, BR_ADD),
    "multilingual": ("items_v4.json", "items_v5.json", 5, ML_DROP, ML_ADD),
    "basic_readout_mt": (
        "items_v6.json",
        "items_v7.json",
        7,
        ["brh-ent-bonaire-capital"],
        ["brh-ent-usumacinta-border-watercourse"],
    ),
}
CAPITAL = re.compile(r"capital|hauptstadt|capitale|seat of government", re.I)


def _raw(fam: str, name: str) -> dict:
    return json.loads((REPO / "evals" / fam / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("fam", sorted(BANKS))
def test_new_bank_is_the_frozen_bank_with_the_capital_items_replaced(fam):
    old_name, new_name, version, dropped, added = BANKS[fam]
    old, new = _raw(fam, old_name), _raw(fam, new_name)
    assert new["version"] == version and new["supersedes"] == old_name
    assert new["capital_swap"]["date"] == "2026-11-05"
    olds = {it["name"]: it for it in old["items"]}
    news = {it["name"]: it for it in new["items"]}
    assert set(dropped) <= set(olds) and not set(dropped) & set(news)
    assert set(news) == (set(olds) - set(dropped)) | set(added)
    assert len(new["items"]) == len(old["items"])  # the bank keeps its size
    for n, it in news.items():  # every kept item byte-identical
        if n not in added:
            assert it == olds[n], n
    kept = [it["name"] for it in new["items"] if it["name"] not in added]
    assert kept == [it["name"] for it in old["items"] if it["name"] not in dropped]  # same order
    for n in added:  # the new items are written for this swap and gated
        assert news[n]["source"] == "capital-swap-2026-11-05", n
        text = {k: v for k, v in news[n].items() if k != "source"}  # the source tag names the swap
        assert not CAPITAL.search(
            json.dumps(text, ensure_ascii=False).replace("capital-swap", "")
        ), n


def test_registered_banks_and_stamps(real_families):
    assert registry.bank_path("basic_readout").name == "items_v8.json"
    assert registry.bank_path("multilingual").name == "items_v5.json"
    assert registry.bank_path("basic_readout_mt").name == "items_v7.json"
    assert prompt_version_of("basic_readout") == "br-mc-2026-11-01-v5b+brsum-v2+qline-v2+bank-v8"
    assert mp.ML_BANK_TAGS["multilingual"] == "bank-v5"
    assert mp.BRMT_PROMPT_VERSION == "mc-brmt-2026-10-31r+norival-v1+qline-v2+bank-v7"


def test_basic_readout_v8_entity_mix_and_gold_slots():
    items = _raw("basic_readout", "items_v8.json")["items"]
    ent = [it for it in items if it["subfamily"] == "entity"]
    assert len(ent) == 35 and not any(it["slice"] == "cap" for it in items)
    assert collections.Counter(it["slice"] for it in ent) == {"ath": 15, "lmk": 11, "mus": 9}
    # the dropped items' freed slots: entity stays 7 per slot and every kept item keeps its slot
    slots = collections.Counter(it["mc"]["gold_position"] for it in ent)
    assert slots == dict.fromkeys(range(5), 7)
    for it in ent:
        m = it["mc"]
        assert m["gold"] not in m["distractors"] and len(m["distractors"]) == 4
        assert it["gate"]["correct"] >= 8 and it["gate"]["n"] == 10


def test_multilingual_v5_keeps_the_alias_note_and_language_lists():
    _h, items = load_bank(REPO / "evals/multilingual/items_v5.json")
    # the alias table is in every MC question: unchanged, so no kept item's MC prompt moves
    assert alias_note(option_aliases(items)) == mp.ML_ALIAS_NOTE
    by_lang: dict[str, set[tuple[str, ...]]] = collections.defaultdict(set)
    for it in items:
        by_lang[it["lang"]].add(tuple(it["mc"]["language"]["distractors"]))
    for lang in ("de", "fr", "it", "pt"):
        assert len(by_lang[lang]) == 1, lang  # one language list per language, as round 4 built
    assert not any(it["mc_type"] == "capital" for it in items)


def test_brmt_v7_reads_with_its_own_plan(real_families):
    h = _raw("basic_readout_mt", "items_v7.json")
    assert "read_plan_bank" not in h
    ids = {s.id for s in readplan.plan("basic_readout_mt")}
    assert len(ids) == 90 and "brh-ent-usumacinta-border-watercourse" in ids


@pytest.mark.parametrize("fam", ["multilingual", "basic_readout_mt"])
def test_topic_labels_cover_the_new_items(fam):
    topics = json.loads((REPO / "evals/baselines/topics" / f"{fam}.json").read_text("utf-8"))
    for n in BANKS[fam][4]:
        assert topics["items"][label_of(n)], n


def test_kept_items_read_exactly_as_before(real_families, monkeypatch):
    """The new plans' rows for the kept items equal the frozen banks' rows, so every earlier
    readout of a kept item serves the new bank (only the sidecar's plan_sha moves)."""
    for fam, (old_name, _new, _v, dropped, added) in BANKS.items():
        new_rows = {s.id: s.row() for s in readplan.plan(fam, layers=None)}
        env = registry.BANK_FILE_ENV_PREFIX + fam.upper()
        monkeypatch.setenv(env, f"evals/{fam}/{old_name}")
        old_rows = {s.id: s.row() for s in readplan.plan(fam, layers=None)}
        monkeypatch.delenv(env)
        for i, row in new_rows.items():
            if i not in {label_of(n) for n in added}:
                assert row == old_rows[i], (fam, i)
        assert not {label_of(n) for n in dropped} & set(new_rows)
