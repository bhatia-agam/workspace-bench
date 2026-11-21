"""Family registry: each ``wsbench.evals.<family>`` package registers one ``EvalSpec`` on import."""

import copy
import functools
import importlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wsbench.judge_config import JudgeConfig, ResolvedJudge
from wsbench.results import FamilyResult

# src layout (uv-managed checkout); a wheel install would resolve to site-packages.
REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILIES: dict[str, "EvalSpec"] = {}  # filled by register(); EvalSpec is defined below
BANK_ROOT_ENV = "WSB_BANK_ROOT"  # a per-model bank directory, e.g. adapted/qwen3.5-4b
BANK_FILE_ENV_PREFIX = "WSB_BANK_FILE_"  # + FAMILY upper-cased: one family's bank file

# Former family keys -> current keys (pure renames; the instrument, bank and prompt_version did
# not change). Old names keep working on the command line, as readout file names, in stored
# results.json files and as keys of evals/baselines/anti_text_inversion.json.
LEGACY_FAMILY_NAMES: dict[str, str] = {
    "introspection_inject": "introspection",
    "cutoff_confab": "knowledge_cutoff",
    # canonical() is single-step, so both former keys point straight at the current one
    "dm_category_default": "model_specific_directed_modulation",
    "directed_modulation_obscure": "model_specific_directed_modulation",  # plan 0034 O1
    "wrong_bridge": "wrong_intermediate",  # v1.2.0 (Camila 2026-11-03)
    # 2026-11-04: the multi-token multihop family took the key multihop_mt (the key of the
    # regex-scored family removed on 2026-10-30, listed as multihop_mt_regex since then,
    # REUSED_FAMILY_KEYS). Plan 0101 (2026-11-20): the multi-token families take the plain keys.
    # canonical() is single-step, so multihop_mt_v2 points straight at the current key, and it
    # is listed BEFORE multihop_mt: a file under multihop_mt_v2 still wins over one under
    # multihop_mt, which may be the removed regex family's (``legacy_names`` keeps dict order).
    "multihop_mt_v2": "multihop",
    "multihop_mt": "multihop",
    "basic_readout_mt": "basic_readout",
    "multilingual_mt": "multilingual",
    "typo_mt": "typo",
    # The bare keys basic_readout / multihop / multilingual / typo are NOT here: typed today they
    # mean the multi-token family; what was written under them before 2026-11-20 is told apart by
    # content (REUSED_FAMILY_KEYS, ``owner``).
}

# Renamed families whose former key stays INSIDE their hashed identities: the read plan's
# ``plan_sha`` (``reads.plan_sha_rows``), the ATI ``bank_sha`` (``text_inversion.bank_fingerprint``)
# and the lucky-guessing seeds all hash the family name, so a rename would void every readout
# sidecar, ATI entry and seeded floor produced under the old key. These families hash as their
# former key (``hash_name``); the rename is a label change only. (The 2026-10-26 renames
# predate plan_sha and keep hashing their current key.)
HASH_FAMILY_NAMES: dict[str, str] = {
    "wrong_intermediate": "wrong_bridge",  # v1.2.0, retained
    # retained from 2026-11-04 (it was HASH_FAMILY_NAMES["multihop_mt"]): the multi-token
    # multihop family still hashes as multihop_mt_v2
    "multihop": "multihop_mt_v2",
    # plan 0101: every renamed family hashes under exactly the string it hashed under before
    "basic_readout": "basic_readout_mt",
    "multilingual": "multilingual_mt",
    "typo": "typo_mt",
    "basic_readout_st": "basic_readout",
    "multihop_st": "multihop",
    "multilingual_st": "multilingual",
    "typo_st": "typo",
}

# The key each family had on main just before plan 0101: what every site that embedded the RAW
# key then (option orders, the dev split, capable / onecue / builder cache keys, adapt seeds, the
# authoring prompt, the lens producer's row hash and sampling seed) embeds now: the inverse of
# the rename. It differs from ``hash_name`` for ONE family: the multi-token multihop family is
# multihop_mt here and multihop_mt_v2 there, because the 2026-11-04 rename froze only the
# plan_sha / bank_sha / seed sites and let the raw-key sites move to multihop_mt.
FROZEN_KEY_NAMES: dict[str, str] = {
    "basic_readout": "basic_readout_mt",
    "multihop": "multihop_mt",
    "multilingual": "multilingual_mt",
    "typo": "typo_mt",
    "basic_readout_st": "basic_readout",
    "multihop_st": "multihop",
    "multilingual_st": "multilingual",
    "typo_st": "typo",
}

# The key every family had on main just before plan 0101 -> its key now: the map for files frozen
# in the old vocabulary (evals/fast/*.json, the archived floor, goldens) and for pre-0101 layout
# paths (``repo_path``). Never used for user input.
PRE_0101_KEYS: dict[str, str] = {
    "basic_readout": "basic_readout_st",
    "basic_readout_mt": "basic_readout",
    "multihop": "multihop_st",
    "multihop_mt": "multihop",
    "multihop_mt_v2": "multihop",
    "multilingual": "multilingual_st",
    "multilingual_mt": "multilingual",
    "typo": "typo_st",
    "typo_mt": "typo",
}
if {
    new: old for old, new in PRE_0101_KEYS.items() if old != "multihop_mt_v2"
} != FROZEN_KEY_NAMES:  # the two tables are one rename, read in both directions
    raise RuntimeError("registry.FROZEN_KEY_NAMES is not the inverse of PRE_0101_KEYS")


@dataclass(frozen=True)
class Reused:
    """Both holders of a key that two families have held (plan 0101 §3.2)."""

    live: str  # the family the key means when typed today (a current key)
    other: str  # the family that held it before (a current or removed key)
    live_stamps: tuple[str, ...]  # result-stamp prefixes of ``live``
    # CLOSED list of the prefixes ``other`` ever wrote under this key; None = every stamp that is
    # not live's (the 2026-11-04 entry: the removed regex family has no bank to compare)
    other_stamps: tuple[str, ...] | None
    live_header: str | None = None  # bank header "family" value of ``live``'s banks
    other_header: str | None = None
    since: str = ""  # for messages


# Keys that two families have held -> both holders. A store, out dir, readout root or adapted set
# written before a rename may hold the other family's files under the reused key, so a file or
# directory under the live family's former key wins there (``lookup_names``); a stored result
# under the reused key is attributed by its ``prompt_version`` (``stored_family``).
REUSED_FAMILY_KEYS: dict[str, Reused] = {
    # 2026-11-04, retained unchanged in behaviour. A stored result under multihop_mt whose stamp
    # starts with one of the live prefixes (the MC stamps, summary and native, and the
    # opts=judge=regex diagnostic) is the multi-token multihop family's, read under its current
    # key (now multihop); ANY other stamp (mc-2026-09-16, mt-regex-2026-09-23, later regex
    # versions, an empty one) is the removed regex family's, read as multihop_mt_regex
    # (``other_stamps=None``: that family has no bank to compare).
    "multihop_mt": Reused(
        "multihop",
        "multihop_mt_regex",
        ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
        None,
        "multihop-hard",
        None,
        "2026-11-04",
    ),
    # Plan 0101: the four bare keys named the single-token family until 2026-11-20 and name the
    # multi-token one since. The stamp prefixes are every stamp either member ever wrote (floors,
    # ATI files, adapted floors and lens scores; the longest match decides, so the single-token
    # multilingual family's opts=judge=regex diagnostic mt-regex-2026-10-30+leg-regex beats
    # mt-regex-). For the multilingual pair mc-ml- and mc-2026- are in NEITHER tuple: both
    # members are mt_family families whose unpinned opts=judge=mc diagnostic stamps them, so
    # such a result is refused (RenamedKey), never guessed.
    "basic_readout": Reused(
        "basic_readout",
        "basic_readout_st",
        ("mc-brmt-", "mt-regex-", "mc-2026-"),
        ("br-mc-", "bank-"),
        "basic-readout-hard",
        "basic-readout",
        "2026-11-20 (plan 0101)",
    ),
    "multihop": Reused(
        "multihop",
        "multihop_st",
        ("mh2-mc-", "mt-regex-2026-10-30+md+fz"),
        ("bank-",),
        "multihop-hard",
        "multihop",
        "2026-11-20 (plan 0101)",
    ),
    "multilingual": Reused(
        "multilingual",
        "multilingual_st",
        ("mt-regex-",),
        ("mcrx-", "bank-", "mt-regex-2026-10-30+leg-regex"),
        "multilingual-hard",
        "multilingual",
        "2026-11-20 (plan 0101)",
    ),
    "typo": Reused(
        "typo",
        "typo_st",
        ("mt-regex-", "mc-2026-"),
        ("bank-",),
        "typo-hard",
        "typo",
        "2026-11-20 (plan 0101)",
    ),
}
# True until the next version tag: `wsbench` prints one line when one of the four swapped bare
# keys is typed (``cli._family``). The guards above are permanent; only the notice goes.
SWAP_NOTICE = True
NO_NOTICE_ENV = "WSB_NO_RENAME_NOTICE"
_NOTICED: set[str] = set()


def swap_notice(name: str) -> str | None:
    """The one line to print (once per key per process) when one of the four swapped bare keys
    is typed, else None: ``'multihop' is the multi-token family since 2026-11-20 ...``. Off
    with ``SWAP_NOTICE = False`` or ``$WSB_NO_RENAME_NOTICE``."""
    r = REUSED_FAMILY_KEYS.get(name)
    if r is None or r.other_stamps is None or name != r.live:
        return None
    if not SWAP_NOTICE or os.environ.get(NO_NOTICE_ENV) or name in _NOTICED:
        return None
    _NOTICED.add(name)
    return (
        f"note: {name!r} is the multi-token family since 2026-11-20 (was {frozen_name(name)}); "
        f"the single-token family is {r.other!r}"
    )


# Families deleted from the bench -> why (never registered again; plan 0017). Old run dirs may
# still hold their results.json, so results.macro excludes them (reason "removed"); a removed
# family's former keys are listed too.
REMOVED_FAMILIES: dict[str, str] = {
    "ttt": "removed 2026-10-26 (#97): too close to next-token prediction",
    "ttt_move": "removed 2026-10-26 (#97): too close to next-token prediction",
    "brew_intermediates": "removed 2026-10-29 (plan 0029): the prompt alone solves it",
    "wrong_bridge_true": (
        "removed 2026-10-30 (Camila, plan 0050): not part of the benchmark; wrong_intermediate "
        "reports the true-bridge pick as true_bridge_rate"
    ),
    "hallucination": "removed 2026-10-30 (plan 0040): replaced by HallucinationBench "
    "(github.com/camila-blank/hallucination-bench); its index is reported in WSB "
    "(README §HallucinationBench)",
    "multihop_mt_regex": (
        "removed 2026-10-30: superseded by multihop_mt_v2 (Camila), which was keyed multihop_mt "
        "from 2026-11-04 and is keyed multihop since 2026-11-20; this family was keyed "
        "multihop_mt until 2026-11-04"
    ),
    "medical_diagnosis": "removed 2026-10-31 (Camila, plan 0058): taken out of the benchmark",
    "medical_diagnosis_alt": "removed 2026-10-31 (Camila, plan 0058): taken out of the "
    "benchmark with medical_diagnosis",
    "unverbalized_hint": "removed 2026-11-07 (Camila, plan 0081): outdated; retired since "
    "2026-10-31 (plan 0058)",
}

# The eval categories (plan 0098): ``EvalSpec.group`` -> title, in README order.
# ``jlens_comparison`` (``precision`` until plan 0105) holds jlens_concept_pr, which is in no
# macro.
CATEGORIES: dict[str, str] = {
    "basic": "Basic (adapted from the J-lens paper)",
    "computational": "Computational",
    "association": "Association",
    "safety": "Safety",
    "anti_bag_of_features": "Anti-bag-of-features",
    "logical_processing": "Logical processing",
    "model_specific": "Model-specific",
    "jlens_comparison": "J-lens comparison",
}
# A former category key -> its key of today (plan 0105). A category is a directory and a
# ``wsbench list`` column, never an input, so the only reader is ``repo_path`` (a stored
# ``evals/precision/...`` path string).
LEGACY_CATEGORIES: dict[str, str] = {"precision": "jlens_comparison"}
# A family that changed category after plan 0101 -> the category it left (plan 0107:
# ``association`` moved from ``basic`` to ``association``; directory, package and ``group`` only,
# no instrument). The former category is still a category, so the only reader is ``repo_path``
# (a stored ``evals/basic/association/...`` path string) and the ``WSB_BANK_FILE_*`` hint.
LEGACY_FAMILY_CATEGORIES: dict[str, str] = {"association": "basic"}

# Families retired from the bench FOR NOW -> why (plan 0058; reversible, unlike REMOVED_FAMILIES).
# The package, bank, tests and floors stay and the family is still registered and runnable by
# name (`families=<name>`), but it is left out of every `all` default (``drop_superseded``), the
# macro (reason "retired"), the README family list and the ATI file. Restoring one = deleting its
# entry here and re-adding its README entry, Judges row and ATI ``NOT_GATED`` line (plan 0058).
# Empty since plan 0081 removed unverbalized_hint, its only user; the mechanism stays.
RETIRED_FAMILIES: dict[str, str] = {}


def canonical(name: str) -> str:
    """The current key of ``name``: a former key maps to its new one, any other name is kept."""
    return LEGACY_FAMILY_NAMES.get(name, name)


def legacy_names(name: str) -> list[str]:
    """The former keys of the current family ``name`` (empty for a family never renamed)."""
    return [old for old, new in LEGACY_FAMILY_NAMES.items() if new == name]


class RenamedKey(SystemExit):
    """A file, directory, result or variable under a reused key belongs to the other family of
    the pair, or cannot be attributed (exit 2; the message names the rename and both keys)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.args = (message,)


def row_ids(rows: Iterable[Any]) -> list[str]:
    """The item ids of result rows (``id``, else ``name`` / ``item``; a per-slot id such as
    ``c0334|s1`` cut at ``|``)."""
    out = []
    for r in rows or ():
        raw = r.get("id", r.get("name", r.get("item"))) if isinstance(r, dict) else None
        if raw is not None:
            out.append(str(raw).split("|", 1)[0])
    return out


def _pair(name: str) -> tuple[str, Reused] | None:
    """``(bare key, record)`` of the plan-0101 pair ``name`` is a member of (a reused key with a
    closed ``other_stamps`` list, both holders live), else None."""
    for key, r in REUSED_FAMILY_KEYS.items():
        if r.other_stamps is not None and name in (r.live, r.other):
            return key, r
    return None


def partner(name: str) -> str | None:
    """The other member of ``name``'s plan-0101 pair, else None."""
    hit = _pair(name)
    if hit is None:
        return None
    return hit[1].other if name == hit[1].live else hit[1].live


def shared_key(name: str) -> str | None:
    """The bare key both members of ``name``'s plan-0101 pair have held, else None."""
    hit = _pair(name)
    return hit[0] if hit else None


def frozen_name(name: str) -> str:
    """The key ``name`` had on main just before plan 0101 (``FROZEN_KEY_NAMES``, else ``name``
    itself; never canonicalized). Like a hash name it is an opaque input of a seed, cache key or
    hash, never a lookup key or a file name, and is applied once, to a CURRENT key."""
    return FROZEN_KEY_NAMES.get(name, name)


def from_pre_0101(key: str) -> str:
    """The current key of a key written before plan 0101 (``PRE_0101_KEYS``, else
    ``canonical``)."""
    return PRE_0101_KEYS.get(key, canonical(key))


def rekey_pre_0101[V](d: Mapping[str, V]) -> dict[str, V]:
    """``d`` with its pre-0101 family keys translated (``PRE_0101_KEYS``; any other key kept as
    written), order kept; two keys landing on one key is a ``ValueError``."""
    out: dict[str, V] = {}
    for k, v in d.items():
        new = PRE_0101_KEYS.get(k, k)
        if new in out:
            raise ValueError(f"two keys land on {new!r} (one of them {k!r})")
        out[new] = v
    return out


def lookup_names(name: str) -> list[str]:
    """The keys a file or directory of the current family ``name`` may sit under, in lookup
    order: ``name``, then its former keys. A plan-0101 pair: the single-token member looks under
    its own key and the bare key, the multi-token member under its key and its former keys
    (every hit under the bare key is checked by content, ``owner``). The 2026-11-04 reused key
    (no content check possible): the former keys first, so a pre-rename root's file of the
    removed family is never read as this one's."""
    old = legacy_names(name)
    hit = _pair(name)
    if hit is not None:
        return [name, hit[0]] if name == hit[1].other else [name, *old]
    return [*old, name] if name in REUSED_FAMILY_KEYS else [name, *old]


def _stamp_holder(r: Reused, stamp: str) -> str | None:
    """Which holder wrote ``stamp`` (the longest matching prefix over both tuples decides);
    None when neither did."""
    if r.other_stamps is None:
        return r.live if stamp.startswith(r.live_stamps) else r.other
    best, who = -1, None
    for holder, prefixes in ((r.live, r.live_stamps), (r.other, r.other_stamps)):
        for pre in prefixes:
            if stamp.startswith(pre) and len(pre) > best:
                best, who = len(pre), holder
    return who


def _renamed(key: str, r: Reused, what: str) -> RenamedKey:
    return RenamedKey(
        f"{what}: the key {key!r} was reused on {r.since or 'a rename'} (it names {r.live!r} "
        f"now and named {r.other!r} before)"
    )


def stored_family(
    stored_key: str, prompt_version: str | None, ids: Iterable[str] | None = None
) -> str:
    """The family a stored result under ``stored_key`` (the key AS STORED, not canonicalized)
    stamped ``prompt_version`` belongs to. A key no two families held: ``canonical``. A reused
    key: by stamp; an empty stamp is settled by the result's own item ids (``ids``, when given
    and they identify a holder: ``owner``, which raises on ids of both) and is otherwise the
    live family's (for the 2026-11-04 key, whose other holder is a removed family, every
    non-live stamp, empty included, is that family's); a non-empty stamp of neither holder is a
    ``RenamedKey``."""
    r = REUSED_FAMILY_KEYS.get(stored_key)
    if r is None:
        return canonical(stored_key)
    stamp = str(prompt_version or "")
    if r.other_stamps is not None and not stamp:
        return (owner(stored_key, ids=ids) if ids is not None else None) or r.live
    who = _stamp_holder(r, stamp)
    if who is None:
        raise _renamed(stored_key, r, f"a result stamped {stamp!r}")
    return who


def owner(
    key: str,
    *,
    stamp: str | None = None,
    header: str | None = None,
    ids: Iterable[str] | None = None,
    plan_sha: tuple[str, str, str] | None = None,
) -> str | None:
    """Which holder of the reused ``key`` the evidence identifies; None with no evidence (and
    for a key that is not reused). ``stamp``: a result stamp. ``plan_sha``: ``(sha, the live
    family's plan sha, the other's)``. ``header``: a bank header's "family" value. ``ids``: item
    ids (the live family when they meet only its banks, the other when only the other's, None
    when neither, ``RenamedKey`` when both). Kinds of evidence that disagree, or a non-empty
    stamp of neither holder, raise ``RenamedKey``."""
    r = REUSED_FAMILY_KEYS.get(key)
    if r is None:
        return None
    found: list[str] = []
    if stamp:
        who = _stamp_holder(r, stamp)
        if who is None:
            raise _renamed(key, r, f"a result stamped {stamp!r}")
        found.append(who)
    if plan_sha is not None and plan_sha[0] in plan_sha[1:]:
        found.append(r.live if plan_sha[0] == plan_sha[1] else r.other)
    if header is not None:
        if r.live_header is not None and header == r.live_header:
            found.append(r.live)
        elif r.other_header is not None and header == r.other_header:
            found.append(r.other)
    if ids is not None and r.other_stamps is not None:
        have = {str(i) for i in ids}
        in_live, in_other = have & family_ids(r.live), have & family_ids(r.other)
        if in_live and in_other:
            raise _renamed(key, r, "item ids of both families")
        if in_live or in_other:
            found.append(r.live if in_live else r.other)
    if len(set(found)) > 1:
        raise _renamed(key, r, "evidence of both families")
    return found[0] if found else None


def attribute_rows[R: dict[str, Any]](rows: list[R], *, canonicalize: bool = True) -> list[R]:
    """Rows (gate rows, answers) with each row's ``family`` re-keyed IN PLACE by its own id:
    ``canonical`` for a key no pair shares, ``owner(key, ids=[id])`` for a plan-0101 bare key
    (``RenamedKey`` when the id is in neither member's banks). ``canonicalize=False`` (readers
    that never canonicalized): only the pre-0101 keys of ``PRE_0101_KEYS`` are translated, any
    other former key stays as stored."""
    for row in rows:
        key = row.get("family")
        if not isinstance(key, str):
            continue
        r = REUSED_FAMILY_KEYS.get(key)
        if r is None or r.other_stamps is None:
            if canonicalize:
                row["family"] = canonical(key)
            elif key in PRE_0101_KEYS:
                # a pre-0101 key no pair shares (the `_mt` keys) names exactly one family: its
                # rows keep serving it, whoever reads them (any other former key: as stored)
                row["family"] = PRE_0101_KEYS[key]
            continue
        who = owner(key, ids=[str(row.get("id"))])
        if who is None:
            raise _renamed(key, r, f"row {row.get('id')!r} is in neither family's banks")
        row["family"] = who
    return rows


def _bank_file_ids(path: Path) -> frozenset[str]:
    """Item ids of one bank file (``id``, and ``label_of(name)`` for a name-keyed item); empty
    for a file that is not a bank."""
    from wsbench.banks import label_of

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    items = raw if isinstance(raw, list) else raw.get("items", []) if isinstance(raw, dict) else []
    out = set()
    for it in items if isinstance(items, list) else []:
        if isinstance(it, dict):
            if it.get("id") is not None:
                out.add(str(it["id"]))
            if it.get("name") is not None:
                out.add(label_of(str(it["name"])))
    return frozenset(out)


@functools.cache
def _family_ids(family: str, root: str) -> frozenset[str]:
    out: set[str] = set()
    for path in sorted(family_root(family).glob("items*.json")):
        out |= _bank_file_ids(path)
    if root:
        bank = root_bank(Path(root), family)
        if bank is not None:
            out |= _bank_file_ids(bank)
    return frozenset(out)


def family_ids(family: str) -> frozenset[str]:
    """Every item id of every registered bank version of ``family`` plus, under
    ``$WSB_BANK_ROOT``, the set's bank of the family when it has one (never the exiting
    ``bank_path``: a set may lack the partner's bank). Cached per (family, root)."""
    root = bank_root()
    return _family_ids(canonical(family), str(root) if root else "")


def _header_family(path: Path) -> str | None:
    """A bank file's header "family" value (None: no header, a list-shaped or unreadable file)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fam = raw.get("family") if isinstance(raw, dict) else None
    return fam if isinstance(fam, str) else None


def root_bank(base: Path, family: str) -> Path | None:
    """THE rule for "which file under an adapted root is this family's bank": the first
    ``lookup_names`` file that exists and, under a plan-0101 bare key, passes the header rule
    (the multi-token family takes it unless its header is the single-token one's; the
    single-token family only when its header IS its own). A bare-key file WITHOUT a header is
    decided by its item ids against the two families' registered banks, and is a ``RenamedKey``
    when they do not say. None when the root has none."""
    hit = _pair(family)
    for key in lookup_names(family):
        path = Path(base) / f"{key}.json"
        if not path.exists():
            continue
        if hit is not None and key == hit[0]:
            header, r = _header_family(path), hit[1]
            if header is None and r.other_header is not None:
                ids = _bank_file_ids(path)
                in_live = ids & _family_ids(r.live, "")
                in_other = ids & _family_ids(r.other, "")
                if bool(in_live) == bool(in_other):
                    raise _renamed(key, r, f"{path} has no header and its ids do not say whose")
                mine = bool(in_live) if family == r.live else bool(in_other)
            else:
                mine = header != r.other_header if family == r.live else header == r.other_header
            if r.other_header is not None and not mine:
                continue
        return path
    return None


def bank_pins(family: str) -> list[str]:
    """THE ``WSB_BANK_FILE_<NAME>`` variables that pin ``family``: its key, its former keys
    and, for the single-token member of a plan-0101 pair, the bare key too (so a pre-rename pin
    is seen, never silently ignored)."""
    names = [family, *legacy_names(family)]
    hit = _pair(family)
    if hit is not None and hit[0] not in names:
        names.append(hit[0])
    return [BANK_FILE_ENV_PREFIX + n.upper() for n in names]


def bank_pin(family: str) -> tuple[str, str] | None:
    """``(variable, value)`` of the first SET ``WSB_BANK_FILE_*`` variable that pins ``family``
    (``bank_pins``), else None. For the single-token member of a plan-0101 pair a variable named
    for the bare key is not its pin when the file it names carries the multi-token family's
    header: that is a legitimate pin of the partner, and must not disable this family."""
    hit = _pair(family)
    for var in bank_pins(family):
        value = os.environ.get(var)
        if not value:
            continue
        if (
            hit is not None
            and family == hit[1].other
            and var == (BANK_FILE_ENV_PREFIX + hit[0].upper())
        ):
            path = Path(value) if Path(value).is_absolute() else REPO_ROOT / value
            live = hit[1].live_header
            if live is not None and path.is_file() and _header_family(path) == live:
                continue
        return var, value
    return None


def hash_name(name: str) -> str:
    """The key ``name`` hashes under in plan_sha / bank_sha / seeds: its frozen former key for a
    family in ``HASH_FAMILY_NAMES``, else ``name`` itself (never canonicalized: the plan 0034
    restamp hashes rows under a former key on purpose, ``scripts/ati_restamp_rename.py``). A hash
    name is an opaque hash input, never a lookup key or a file name, and is applied once, to a
    CURRENT key (it is not idempotent across a renamed pair)."""
    return HASH_FAMILY_NAMES.get(name, name)


def _row_item_id(row: Any) -> str | None:
    """The item id a cache row's ``key`` starts with (``digest:`` / ``ntok:`` prefix dropped,
    cut at the first ``|``)."""
    key = row.get("key") if isinstance(row, dict) else None
    if not isinstance(key, str):
        return None
    for pre in ("digest:", "ntok:"):
        key = key.removeprefix(pre)
    return key.split("|", 1)[0]


def dir_owner(path: Path, key: str | None = None) -> str | None:
    """Which family's results a per-family directory holds, by content: its ``results.json``
    (``stored_family`` of the stored key and stamp), else the item ids of the first 2,000 rows
    of ``cells.jsonl`` or (a digest store directory) ``L*.jsonl`` (``owner``), else None.
    ``key``: the reused key the directory sits under (default: its name)."""
    path = Path(path)
    key = path.name if key is None else key
    res = path / "results.json"
    if res.is_file():
        try:
            d = json.loads(res.read_text(encoding="utf-8"))
            try:
                return stored_family(
                    str(d["family"]),
                    (d.get("config") or {}).get("prompt_version"),
                    row_ids(d.get("rows") or []),
                )
            except RenamedKey:  # a stamp both members can write: the rows' own ids
                who = owner(str(d["family"]), ids=row_ids(d.get("rows") or []))
                if who is not None:
                    return who
        except (OSError, ValueError, KeyError, AttributeError):
            pass
    ids: list[str] = []
    for f in [path / "cells.jsonl", *sorted(path.glob("L*.jsonl"))]:
        if not f.is_file():
            continue
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if len(ids) >= 2000:
                    break
                try:
                    iid = _row_item_id(json.loads(line))
                except ValueError:
                    continue
                if iid:
                    ids.append(iid)
    return owner(key, ids=ids) if ids else None


def dir_family(path: Path, name: str | None = None) -> str | None:
    """The CURRENT family of a per-family results directory named ``name`` (default: its own
    name), for viewers that walk a run tree: by its ``results.json`` (key and stamp), else, for a
    plan-0101 bare key, by its cache rows' item ids. None when a bare-key directory cannot be
    attributed (the caller skips it): an old tree's ``multihop/`` is the single-token family."""
    path = Path(path)
    name = path.name if name is None else name
    r = REUSED_FAMILY_KEYS.get(name)
    if r is None:
        return canonical(name)
    try:
        who = dir_owner(path, name)
    except RenamedKey:
        return None
    return who if who is not None or r.other_stamps is not None else r.live


def file_family(path: Path, stem: str | None = None) -> str | None:
    """The CURRENT family of a readouts file named ``<stem>.jsonl`` (default: its own stem): a
    plan-0101 bare key by the file's item ids, None when they do not say."""
    from wsbench.readouts import ids_in

    stem = Path(path).stem if stem is None else stem
    r = REUSED_FAMILY_KEYS.get(stem)
    if r is None or r.other_stamps is None:
        return canonical(stem)
    try:
        return owner(stem, ids=ids_in(Path(path)))
    except (RenamedKey, OSError):
        return None


def stale_floor_key(key: str, stamp: str | None) -> bool:
    """A frozen floor / ATI entry under a plan-0101 bare ``key`` whose instrument stamp is the
    OTHER member's: a file written before the rename (its keys were never migrated)."""
    r = REUSED_FAMILY_KEYS.get(key)
    if r is None or r.other_stamps is None or not stamp:
        return False
    return _stamp_holder(r, str(stamp)) == r.other


def family_dir(root: Path, name: str) -> Path:
    """``root/<name>``, or ``root/<former key>`` when only a directory under a former key exists
    (an out dir or digest store written before the rename keeps its cached verdicts); for the
    2026-11-04 reused key a former key's directory wins (``lookup_names``; no content check:
    the removed family has no bank to compare). A directory under a plan-0101 bare key is taken
    only when its content (``dir_owner``) is this family's, or unidentified under the family's
    own key; the partner's directory is skipped, and ``RenamedKey`` when it sits under the
    family's own key with no other candidate."""
    hit = _pair(name)
    for key in lookup_names(name):
        path = Path(root) / key
        if not path.exists():
            continue
        if hit is not None and key == hit[0]:
            who = dir_owner(path, key)
            if not (who == name or (who is None and key == name)):
                continue
        return path
    own = Path(root) / name
    if hit is not None and own.exists():
        r = hit[1]
        raise RenamedKey(
            f"{own} holds results of {partner(name)!r}, written before {r.since} when that "
            f"family was keyed {hit[0]!r}; use a fresh out= or rename the directory to "
            f"{partner(name)!r}"
        )
    return own


def bank_path(family: str) -> Path:
    """The bank a family judges (plan 0032 §2.12): ``$WSB_BANK_FILE_<FAMILY>`` (one family's
    whole bank file, read at call time) > ``$WSB_BANK_ROOT/<family>.json`` (an adapted bank; a
    family missing there is an error, never a silent fall-back to the frozen bank of another
    model) > ``REPO_ROOT / EvalSpec.bank`` (the registered file: ``items.json``, or a versioned
    ``items_v<N>.json`` once the family switches). There is no ``items.json`` literal fallback."""
    family = canonical(family)
    var, one = bank_pin(family) or ("", "")
    if one:  # one family's whole bank file (ATI refill candidates, pinned test fixtures)
        path = Path(one) if Path(one).is_absolute() else REPO_ROOT / one
        if not path.is_file():
            raise SystemExit(f"{var}={one}: no such bank file{_moved_hint(one)}")
        _check_pin(family, var, path)
        return path
    root = os.environ.get(BANK_ROOT_ENV)
    if root:
        base = Path(root) if Path(root).is_absolute() else REPO_ROOT / root
        # an adapted set written under a former key (``lookup_names``: the current key first,
        # except for the 2026-11-04 reused key); a bare key's file by its header (``root_bank``)
        found = root_bank(base, family)
        if found is None:
            path = base / f"{family}.json"
            hit = _pair(family)
            hint = ""
            if hit is not None and (base / f"{hit[0]}.json").exists():
                hint = (
                    f"; {base / (hit[0] + '.json')} is the bank of {partner(family)!r} "
                    f"(the key {hit[0]!r} was reused on {hit[1].since})"
                )
            raise SystemExit(f"{BANK_ROOT_ENV}={root} has no bank for {family!r} ({path}){hint}")
        return found
    return REPO_ROOT / _spec_for_bank(family).bank


def _moved_hint(value: str) -> str:
    """For a missing ``WSB_BANK_FILE_*`` file whose path has the pre-0101 shape
    ``evals/<family>/...``, or names the category a family has left
    (``LEGACY_FAMILY_CATEGORIES``): where the family directory is now (empty on the flat
    layout)."""
    parts = Path(value).parts
    if len(parts) < 3 or parts[0] != "evals":
        return ""
    if _layout().get(parts[2]) == parts[1]:
        return ""  # already a path of today's layout: nothing moved
    if len(parts) >= 4 and LEGACY_FAMILY_CATEGORIES.get(parts[2]) == parts[1]:
        return (
            f"; the family {parts[2]!r} left the category {parts[1]!r} (plan 0107): "
            f"{family_rel(parts[2]) / Path(*parts[3:])}"
        )
    fam = from_pre_0101(parts[1])
    if not _layout().get(fam):
        return ""
    return (
        "; family directories moved under category folders on 2026-11-20 (plan 0101): "
        f"{family_rel(fam) / Path(*parts[2:])}"
    )


def _check_pin(family: str, var: str, path: Path) -> None:
    """A pinned bank file must not be the partner's (plan 0101): a variable named for the bare
    key needs a header that positively matches the multi-token family, and is refused for the
    single-token one (rename the variable); any other variable only refuses the partner's
    header. No check for a family outside a pair."""
    hit = _pair(family)
    if hit is None:
        return
    key, r = hit
    header = _header_family(path)
    bare = var == BANK_FILE_ENV_PREFIX + key.upper()
    own, theirs = (
        (r.live_header, r.other_header) if family == r.live else (r.other_header, r.live_header)
    )
    if bare and family == r.other:
        raise RenamedKey(
            f"{var}={path}: {var} pins {r.live!r} since {r.since}; rename the variable to "
            f"{BANK_FILE_ENV_PREFIX}{family.upper()}"
        )
    if (bare and header != own) or (header is not None and header == theirs):
        raise RenamedKey(
            f"{var}={path}: the file's header is {header or 'none'!r}; {var} pins {family!r} "
            f"(the key {key!r} was reused on {r.since})"
        )


def frozen_bank_path(family: str) -> Path:
    """The family's registered bank of record (``REPO_ROOT / EvalSpec.bank``), ignoring the
    ``WSB_BANK_*`` overrides: what the adapt / viewer / lucky-guessing tools treat as the frozen
    27B bank (a versioned ``items_v<N>.json`` once the family switches, plan 0032 §2.12)."""
    return REPO_ROOT / _spec_for_bank(family).bank


def bank_root() -> Path | None:
    """``$WSB_BANK_ROOT`` as a path (relative = under REPO_ROOT), or None for the registered
    bank."""
    root = os.environ.get(BANK_ROOT_ENV)
    if not root:
        return None
    return Path(root) if Path(root).is_absolute() else REPO_ROOT / root


def resource_path(family: str, name: str) -> Path:
    """A judge resource of the REGISTERED instrument: ``family_root(family) / name``."""
    return family_root(family) / name


@functools.cache
def _layout() -> dict[str, str]:
    """family -> category, read from the package tree without importing anything:
    ``wsbench/evals/<category>/<family>/__init__.py``. A family package directly under
    ``wsbench/evals`` (the pre-0101 flat layout) has category ``""``. A family in two categories,
    or a category that is not a key of ``CATEGORIES``, is a ``ValueError``."""
    root = Path(__file__).resolve().parent / "evals"
    out: dict[str, str] = {}

    def packages(d: Path) -> list[Path]:
        return [s for s in sorted(d.iterdir()) if (s / "__init__.py").is_file()]

    for d in packages(root):
        inner = packages(d)
        if not inner:  # a family package of the flat layout
            inner, category = [d], ""
        elif d.name not in CATEGORIES:
            raise ValueError(f"{d}: {d.name!r} is not a category (registry.CATEGORIES)")
        else:
            category = d.name
        for fam in inner:
            if fam.name in out:
                raise ValueError(f"family {fam.name!r} sits in two places under {root}")
            out[fam.name] = category
    return out


def category_of(family: str) -> str:
    """The category directory of ``family`` (``""`` on the flat layout); an unknown family is
    a ``KeyError``."""
    return _layout()[canonical(family)]


def family_rel(family: str) -> Path:
    """``evals/<category>/<family>`` (REPO_ROOT-relative): the family's data directory, as
    ``EvalSpec.bank``, messages and README links spell it. A family without a package (a test's
    toy family) sits directly under ``evals/``."""
    family = canonical(family)
    category = _layout().get(family, "")
    return Path("evals") / category / family if category else Path("evals") / family


def family_root(family: str) -> Path:
    """The family's data directory: ``REPO_ROOT / family_rel(family)``."""
    return REPO_ROOT / family_rel(family)


def _package_name(family: str) -> str:
    category = _layout().get(family, "")
    return f"wsbench.evals.{category}.{family}" if category else f"wsbench.evals.{family}"


def family_packages() -> list[str]:
    """The dotted name of every family package, in family order."""
    return [_package_name(f) for f in sorted(_layout())]


def family_module(family: str, sub: str = "") -> Any:
    """The family's package, or its submodule ``sub`` (``"prompts"``, ``"judge"``), imported by
    NAME: the one place a family's module path is built."""
    name = _package_name(canonical(family))
    return importlib.import_module(f"{name}.{sub}" if sub else name)


_UNMOVED = ("baselines", "fast", "hallucinationbench")


def repo_path(rel: str | Path) -> Path:
    """``REPO_ROOT / rel``, except that a path of an earlier layout resolves into the family's
    directory of today. In order:

    1. a path of today's layout, ``evals/<category>/<family>/...``, is taken as written. This
       comes first because ``association`` is a category, a family key and a pre-0101 family
       directory at once: ``evals/association/association/...`` (the family since plan 0107),
       ``evals/association/user_modeling/...`` and ``.../conjunctive_association/...`` are
       today's paths, never the pre-0101 family directory plus a subdirectory;
    2. ``evals/<former category key>/<family>/...`` (``LEGACY_CATEGORIES``, plan 0105) and
       ``evals/<the category a family left>/<family>/...`` (``LEGACY_FAMILY_CATEGORIES``, plan
       0107: ``evals/basic/association/...``) -> ``family_root(family) / <rest>``;
    3. ``evals/baselines|fast|hallucinationbench/...`` as written;
    4. ``evals/<pre-0101 family key>/<rest>`` -> ``family_root(from_pre_0101(key)) / <rest>``
       (``evals/association/items_v5.json`` -> ``evals/association/association/items_v5.json``);
    5. anything else as written.

    ONLY for path strings frozen inside data (introspection's ``vector_file`` plan-row strings,
    the "bank" strings of adapted report.json). Never for user input."""
    path = Path(rel)
    if path.is_absolute():
        return path
    parts = path.parts
    layout = _layout()
    if len(parts) >= 2 and parts[0] == "evals":
        if len(parts) >= 3 and layout.get(parts[2]) == parts[1] != "":
            return REPO_ROOT / path
        if len(parts) >= 3 and layout.get(parts[2], "") == LEGACY_CATEGORIES.get(parts[1]):
            return family_root(parts[2]).joinpath(*parts[3:])
        if (
            len(parts) >= 3
            and parts[2] in layout
            and (LEGACY_FAMILY_CATEGORIES.get(parts[2]) == parts[1])
        ):
            return family_root(parts[2]).joinpath(*parts[3:])
        if parts[1] in _UNMOVED:
            return REPO_ROOT / path
        pre = {frozen_name(f) for f in layout} | set(PRE_0101_KEYS)
        if parts[1] in pre:
            return family_root(from_pre_0101(parts[1])).joinpath(*parts[2:])
    return REPO_ROOT / path


def overlay_path(family: str, name: str) -> Path | None:
    """The per-set overlay of a judge resource (plan 0060 A2): ``$WSB_BANK_ROOT/<family>/<name>``
    when ``WSB_BANK_ROOT`` is set and that file exists, else None (never under the registered
    bank)."""
    root = bank_root()
    if root is None:
        return None
    family = canonical(family)
    # the single-token member of a plan-0101 pair never looks under the bare key: no set has an
    # overlay directory of it, so a bare-key overlay directory is the multi-token family's
    hit = _pair(family)
    skip = hit[0] if hit is not None and family == hit[1].other else None
    keys = [k for k in lookup_names(family) if k != skip]
    return next((got for key in keys if (got := _overlay_at(str(root), key, name))), None)


@functools.cache
def _overlay_at(root: str, family: str, name: str) -> Path | None:
    """One existence check per (set dir, family, file): judges look resources up per item, and
    a set dir is written before it is judged."""
    path = Path(root) / family / name
    return path if path.is_file() else None


def merge_overlay(
    base: Any, over: Any, keys: Iterable[str], *, where: str = "overlay"
) -> tuple[Any, frozenset[str]]:
    """``(merged, added)``: ``base`` (never mutated) with the overlay's entries ADDED under each
    dotted path of ``keys`` (``"subjects"``, ``"groups.pair"``): a key absent from the
    registered map is added; a key the registered map has must carry the identical value, else
    SystemExit (an overlay never shadows a registered entry). A list at a path (``passive``)
    merges as a set of members. ``added`` = every added entry as ``"<path>/<key>"``. Every other
    overlay field (``version``, ``note``) is ignored."""
    out = copy.deepcopy(base)
    added: set[str] = set()
    for path in keys:
        parts = path.split(".")
        src: Any = over
        for p in parts:
            src = src.get(p) if isinstance(src, Mapping) else None
        if src is None:
            continue
        dst = out
        for p in parts[:-1]:
            dst = dst.setdefault(p, {})
            if not isinstance(dst, dict):
                raise SystemExit(f"{where}: {path} shape differs from the registered file")
        reg = dst.get(parts[-1])
        if not isinstance(src, (list, Mapping)):
            raise SystemExit(f"{where}: {path!r} must be a map or a list")
        if reg is not None and isinstance(reg, list) != isinstance(src, list):
            raise SystemExit(f"{where}: {path} shape differs from the registered file")
        if reg is not None and not isinstance(reg, (list, Mapping)):
            raise SystemExit(f"{where}: {path} shape differs from the registered file")
        if isinstance(src, list):
            have_l = list(dst.get(parts[-1]) or [])
            new = [x for x in src if x not in have_l]
            dst[parts[-1]] = have_l + new
            added |= {f"{path}/{x}" for x in new}
            continue
        have = dst.setdefault(parts[-1], {})
        for k, v in src.items():
            if k in have:
                if have[k] != v:
                    raise SystemExit(
                        f"{where}: {path}/{k} differs from the registered entry (an overlay "
                        "only adds entries; registered keys resolve to registered entries)"
                    )
                continue
            have[k] = v
            added.add(f"{path}/{k}")
    return out, frozenset(added)


_RESOURCE_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[Any, frozenset[str]]] = {}


def load_resource(
    family: str, name: str, keys: Iterable[str], *, registered: Path | None = None
) -> tuple[Any, frozenset[str]]:
    """``(data, added)``: the registered resource (``registered``, default
    :func:`resource_path`; a missing file reads as ``{}``) with the per-set overlay
    (:func:`overlay_path`) merged on it by :func:`merge_overlay`. With no ``WSB_BANK_ROOT`` or no
    overlay file: exactly the registered file, ``added`` empty. Cached per (registered file,
    overlay file); the caller must not mutate the result."""
    reg = registered if registered is not None else resource_path(family, name)
    over = overlay_path(family, name)
    ks = tuple(keys)
    key = (str(reg), str(over or ""), ks)
    if key not in _RESOURCE_CACHE:
        base = json.loads(reg.read_text(encoding="utf-8")) if reg.is_file() else {}
        if over is None:
            _RESOURCE_CACHE[key] = (base, frozenset())
        else:
            data = json.loads(over.read_text(encoding="utf-8"))
            _RESOURCE_CACHE[key] = merge_overlay(base, data, ks, where=str(over))
    return _RESOURCE_CACHE[key]


def registered_ids(family: str) -> frozenset[str]:
    """Ids of the family's REGISTERED bank (:func:`frozen_bank_path`, never the ``WSB_BANK_*``
    overrides): ``label_of(name)`` for name-keyed items, else ``id``. What decides "registered"
    vs "adapted-only" for every per-set overlay lookup."""
    return _registered_ids(_frozen_bank_str(family))


@functools.cache
def _frozen_bank_str(family: str) -> str:
    """:func:`frozen_bank_path` once per family (it may list the evals package on each call when
    the registry was emptied, and the per-item overlay checks call it per item)."""
    return str(frozen_bank_path(family))


@functools.cache
def _registered_ids(path: str) -> frozenset[str]:
    from wsbench.banks import label_of

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("items", [])
    out = set()
    for it in items:
        if it.get("name"):
            out.add(label_of(str(it["name"])))
        elif it.get("id"):
            out.add(str(it["id"]))
    return frozenset(out)


def registered_values(family: str, field_name: str) -> frozenset[str]:
    """Every value of item field ``field_name`` in the family's REGISTERED bank (e.g.
    role_bound's ``pair_id``)."""
    return _registered_values(_frozen_bank_str(family), field_name)


@functools.cache
def _registered_values(path: str, field_name: str) -> frozenset[str]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw if isinstance(raw, list) else raw.get("items", [])
    return frozenset(str(it[field_name]) for it in items if it.get(field_name) is not None)


def adapted_only(family: str, item_id: str) -> bool:
    """An adapted bank is in use (``WSB_BANK_ROOT``) AND ``item_id`` is not in the family's
    registered bank: the case where a per-set entry is required and a missing one is a loud
    error. Always False for the registered bank."""
    return bank_root() is not None and str(item_id) not in registered_ids(family)


def _spec_for_bank(family: str) -> "EvalSpec":
    """The family's EvalSpec, also when the registry was emptied after import (the family
    package's ``SPEC``); an unknown family exits 2."""
    family = canonical(family)
    if family not in FAMILIES:
        load_all()
    if family in FAMILIES:
        return FAMILIES[family]
    try:
        spec = family_module(family).SPEC
    except (ImportError, AttributeError):
        raise SystemExit(f"no registered bank for family {family!r}") from None
    return spec  # type: ignore[no-any-return]


@dataclass
class JudgeArgs:
    """What ``cli.judge`` passes to every family. ``limit == 0`` means no limit."""

    readouts: Path
    out: Path
    judge: ResolvedJudge
    layers: list[int] | None
    items: list[str] | None
    limit: int
    allow_missing: bool
    concurrency: int
    rpm: float
    dry_run: bool
    aux_models: Mapping[str, str] = field(default_factory=dict)  # e.g. {"summarizer": model}
    extra: dict[str, str] = field(default_factory=dict)  # family options from opts=key=value
    scope: str = ""  # "anti_text_inversion": `items` is that frozen subset, not a partial run


@dataclass(frozen=True)
class EvalSpec:
    name: str  # family key, e.g. "moral_rationale"
    title: str  # README name, e.g. "Moral rationale"
    group: str  # the family's category: a key of CATEGORIES
    bank: Path  # the bank file, relative to REPO_ROOT (items.json; jlens_concept_pr: manifest.json)
    judge: JudgeConfig
    metric: str
    higher_is_better: bool
    run: Callable[[JudgeArgs], FamilyResult]  # returns a FamilyResult; writes nothing
    calls_per_arm: str = ""  # human string for `wsbench list`, e.g. "≈ 7k" (judge calls per arm)
    sources: str = ""  # credit substring that appears verbatim in README §Credits and NOTICE.md
    # a deterministic scorer of record ("regex"): `wsbench list` shows it as the judge and `run`
    # skips its preflight unless opts=judge=mc asks for the family's optional LLM judge
    scorer: str = ""
    # the family that replaces this one. A superseded family stays registered, frozen and
    # runnable by explicit name, but every "all" default skips it and the macro excludes it
    # (reason "superseded") — so its numbers never double-count beside its successor's.
    superseded_by: str = ""
    # why this family is kept out of the macro (e.g. "hillclimbing: not yet reviewed"); empty =
    # in the macro. It stays in `all` runs and reports, only the macro row skips it.
    not_in_macro: str = ""
    # a ``not_in_macro`` reason computed when the macro is assembled, not at import (it may read
    # the bank ``bank_path`` resolves under the live ``WSB_BANK_*`` overrides); "" = in the
    # macro. A non-empty static ``not_in_macro`` wins. See :func:`macro_reason`.
    macro_gate: Callable[[], str] | None = None
    # the family's item ids when they are not just its read plan's (knowledge_cutoff: the frozen
    # bank + the ids-only nocot items, whose plan rows need a network fetch). Feeds the ATI
    # construction entry and `wsbench list`; None = the readplan ids / the bank file's length.
    item_ids: Callable[[], list[str]] | None = None
    # plan 0032 §2.6.5: the reads=full span check (reads.check_full). A full read is ONE
    # contiguous run of >= min_full_positions positions ending at the item's max position per
    # (item, layer); full_contiguous=False (explicit-position rules) needs only the count.
    min_full_positions: int = 2
    full_contiguous: bool = True
    # plan 0032 §2.8.3: the summarizer's task context (no gold, no tool name); per-item notes
    # (a Mapping covering every item) when the family has several prompt kinds
    task_note: str = ""
    item_task_notes: Callable[[], Mapping[str, str]] | None = None
    # plan 0032 §2.7.2: option types that compete as a flat list (e.g. "numbers"); a run of them
    # singles out none (mc.token_note). multi_select: the judge may pick several options.
    flat_types: tuple[str, ...] = ()
    multi_select: bool = False
    # the judge holds TARGETS, not options (the basic bank families): mc.token_note(targets=True)
    # drops the lone-option clause (review of PR #140)
    targets_judge: bool = False


def register(spec: EvalSpec) -> EvalSpec:
    if spec.name in FAMILIES:
        raise ValueError(f"family {spec.name!r} is already registered")
    where = _layout().get(spec.name)
    # a family's directory IS its category (a test's stand-in under a real key may carry a
    # made-up group, which is no category at all)
    if where is not None and spec.group in CATEGORIES and spec.group != where:
        raise ValueError(
            f"family {spec.name!r} is in category {spec.group!r} but its package sits under "
            f"wsbench/evals/{where}/"
        )
    FAMILIES[spec.name] = spec
    return spec


def get(name: str) -> EvalSpec:
    try:
        return FAMILIES[name]
    except KeyError:
        known = ", ".join(sorted(FAMILIES)) or "(none)"
        raise KeyError(f"unknown family {name!r}; known families: {known}") from None


def load_all() -> None:
    """Import every family package (``family_packages``) so FAMILIES is populated. Idempotent."""
    for name in family_packages():
        importlib.import_module(name)


def superseded() -> dict[str, str]:
    """``{family: successor}`` for every superseded family (loads the registry)."""
    load_all()
    return {s.name: s.superseded_by for s in FAMILIES.values() if s.superseded_by}


def macro_reason(spec: EvalSpec) -> str:
    """Why ``spec`` is kept out of the macro now ("" = in it): its static ``not_in_macro``, else
    its ``macro_gate`` evaluated at call time."""
    if spec.not_in_macro or spec.macro_gate is None:
        return spec.not_in_macro
    return spec.macro_gate()


def not_in_macro() -> dict[str, str]:
    """``{family: reason}`` for every family kept out of the macro (loads the registry)."""
    load_all()
    reasons = {s.name: macro_reason(s) for s in FAMILIES.values()}
    return {name: why for name, why in reasons.items() if why}


def drop_superseded(names: Iterable[str]) -> list[str]:
    """``names`` minus the superseded and the retired (``RETIRED_FAMILIES``) families, order
    kept: what ``all`` means everywhere."""
    sup = superseded()
    return [n for n in names if n not in sup and n not in RETIRED_FAMILIES]
