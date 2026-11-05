"""Plan 0066 §5.4 / §11.3-11.5: the wrong_intermediate role cues for the refill's templates
(``CUES_VERSION`` wbcues-v2): registered cues byte-identical, no cached call re-asked, the ATI
restamp script, every adapt-admitted template cued. The judge's verified pick stands
(``judge-only-v1``): no verdict reads the cues, so the rival-check role-tie tests that exercised
them went with that check; the cues are data the adapt refill keys on."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from wsbench import mc, registry
from wsbench.adapt import wrong_intermediate as wb
from wsbench.baselines import text_inversion as ti
from wsbench.evals.wrong_intermediate import judge as wj
from wsbench.evals.wrong_intermediate import prompts as wp

REPO = Path(__file__).resolve().parents[1]
# the 17 templates that had cues before the bump, and sha256 of their ROLE_CUES / raw _CUES
# entries (json, sort_keys, ensure_ascii=False), computed on the pre-bump judge.py (dc3040c)
PRE_TEMPLATES = (
    "film_director", "painting_creator", "novel_author", "composition_composer",
    "album_performer", "song_performer", "album_label", "doctoral_advisor", "person_father",
    "person_mother", "org_founder", "game_developer", "product_manufacturer", "namesake",
    "song_lyricist", "character_creator", "tv_network",
)  # fmt: skip
PRE_ROLE_CUES_SHA = "30ad18a45e33267d7216d4820163ce3f2648dc8c636a62777f12eff063eadd82"
PRE_RAW_CUES_SHA = "e4675733ba4afd3f397d794452e5be64af0106e0563da59a0ccd593eac6eb179"
# the instrument without the cues stamp (judge-only-v1, qline-v2) and the frozen MC call key
PRE_PROMPT_VERSION = "wb-mc-2026-10-31r+judge-only-v1+qline-v2+wbforms-v4+bank-v4"
PRE_MC_VERSION = "wb-mc-2026-10-31r+rv-2026-10-31e"
NEW_TEMPLATES = (
    "film_screenwriter", "song_composer", "tv_creator", "novel_publisher", "film_producer",
    "opera_librettist", "album_producer", "aircraft_manufacturer",
)  # fmt: skip


def _sha(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _restamp_script():
    spec = importlib.util.spec_from_file_location(
        "ati_wi_cues", REPO / "scripts/ati_restamp_wi_cues.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pre_existing_cues_byte_identical():
    assert set(PRE_TEMPLATES) <= set(wj.ROLE_CUES)
    assert _sha({k: wj.ROLE_CUES[k] for k in PRE_TEMPLATES}) == PRE_ROLE_CUES_SHA
    assert _sha({k: wj._CUES[k] for k in PRE_TEMPLATES}) == PRE_RAW_CUES_SHA
    assert set(wj.ROLE_CUES) == set(PRE_TEMPLATES) | set(NEW_TEMPLATES)


def test_every_registered_template_keeps_its_cues():
    bank = json.loads(registry.bank_path("wrong_intermediate").read_text(encoding="utf-8"))
    used = {it["template"] for it in bank["items"]}
    assert used <= set(PRE_TEMPLATES) and not used & set(NEW_TEMPLATES)


@pytest.mark.parametrize("template", NEW_TEMPLATES)
def test_new_template_has_cues(template):
    cues = wj.ROLE_CUES[template]
    assert cues and all(c == c.strip() and c for c in cues)
    assert all(c == mc.fold(c) for c in cues if c.isascii())  # folded, as the matcher reads


def test_cues_version_in_prompt_version_and_call_keys_unchanged():
    assert wp.CUES_VERSION == "wbcues-v2"
    assert "+" + wp.CUES_VERSION + "+" in wp.PROMPT_VERSION
    assert wp.PROMPT_VERSION.replace("+" + wp.CUES_VERSION, "", 1) == PRE_PROMPT_VERSION
    assert wj._mc_version(wp.PROMPT_VERSION) == PRE_MC_VERSION == wp.MC_CALL_VERSION
    # the summary-mode stamp is the native one plus a digest tail: the key strips it there too
    tail = "+digest-v5-task-extractive+sj-v10"
    assert wj._mc_version(wp.PROMPT_VERSION + tail) == PRE_MC_VERSION + tail
    assert not hasattr(wj, "_audit_version")  # no rival audit call since judge-only-v1


def test_digest_fingerprints_do_not_key_the_family_prompt_version():
    from wsbench import digest

    src = Path(digest.__file__).read_text(encoding="utf-8")
    # every digest / layered / store fingerprint starts from the digest's own version, never pv
    assert "def _fp(*parts: Any) -> str:\n    return fingerprint(DIGEST_PROMPT_VERSION" in src
    assert "    return fingerprint(\n        DIGEST_PROMPT_VERSION," in src


def test_every_adapt_template_is_cued_and_admitted():
    assert set(wb.ADAPT_TEMPLATE_CATEGORY) == set(NEW_TEMPLATES)
    assert all(t in wj.ROLE_CUES for t in wb.ADAPT_TEMPLATE_CATEGORY)
    admitted = set(wb.admitted_templates())
    assert set(NEW_TEMPLATES) <= admitted and all(t in wj.ROLE_CUES for t in admitted)
    assert wb.category_of("film_screenwriter") == "filmmaker"
    assert wb.category_of("song_composer") == "musician"
    assert wb.category_of("novel_publisher") == "company"
    assert wb.category_of("opera_librettist") == "writer"
    assert "building_architect" not in admitted and wb.category_of("building_architect") is None
    # musician templates that are not performer templates: no band rule
    assert not {"song_composer", "album_producer"} & wb.PERFORMER_TEMPLATES


def _pre_cues(frozen: dict) -> dict:
    """``frozen`` with the family's entry as it stood before the cues stamp."""
    pre = copy.deepcopy(frozen)
    e = pre["wrong_intermediate"]
    e["instrument"] = PRE_PROMPT_VERSION
    e.pop("restamped_from", None)
    e.pop("restamp_note", None)
    return pre


def test_committed_entry_is_restamped_and_subset_entry_accepts_it():
    """The refreeze re-gated the entry under the judge-only instrument; only the cues stamp moved
    since, so the script restamped it (no verdict reads the cues) and re-running it is a no-op."""
    mod = _restamp_script()
    registry.load_all()
    entry = ti.subset_entry("wrong_intermediate")
    assert entry["instrument"] == wp.PROMPT_VERSION
    assert entry["restamped_from"] == PRE_PROMPT_VERSION
    assert entry["bank_sha"] == ti.bank_fingerprint("wrong_intermediate")
    frozen = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    assert mod.restamp(frozen) is frozen


def test_restamp_script_restamps_only_a_cues_move():
    mod = _restamp_script()
    registry.load_all()
    frozen = json.loads(ti.FROZEN.read_text(encoding="utf-8"))
    pre = _pre_cues(frozen)
    sha = pre["wrong_intermediate"]["bank_sha"]
    e = pre["wrong_intermediate"]
    out = mod.restamp(pre, bank_sha=sha)
    assert out["wrong_intermediate"]["instrument"] == wp.PROMPT_VERSION
    assert {k: v for k, v in out["wrong_intermediate"].items() if k != "instrument"} == {
        **{k: v for k, v in e.items() if k != "instrument"},
        "restamped_from": PRE_PROMPT_VERSION,
        "restamp_note": mod.NOTE,
    }
    assert mod.restamp(out, bank_sha=sha) is out  # a restamped entry is left as is
    with pytest.raises(SystemExit, match="bank_sha"):
        mod.restamp(pre, bank_sha="0" * 64)
    other = copy.deepcopy(pre)
    other["wrong_intermediate"]["instrument"] = PRE_PROMPT_VERSION.replace(
        "wbforms-v4", "wbforms-v3"
    )
    with pytest.raises(SystemExit, match="more than the cues stamp"):
        mod.restamp(other, bank_sha=sha)
