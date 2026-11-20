"""The on-disk layout of an adapted model, ``adapted/<model>/`` (SKILL.md §Layout)."""

import fcntl
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from wsbench import registry
from wsbench.banks import load_bank as load_wrapped
from wsbench.readouts import ids_in
from wsbench.registry import (
    REPO_ROOT,
    RenamedKey,
    _bank_file_ids,
    lookup_names,
    owner,
    partner,
    root_bank,
    shared_key,
)


def model_dir(model: str, root: Path = REPO_ROOT) -> Path:
    return root / "adapted" / model


def item_id(item: dict) -> str:
    return str(item.get("id") or item.get("name"))


def original_bank(family: str) -> tuple[dict[str, Any], list[dict]]:
    """The frozen bank, header and items, whether wrapped or a plain list. The header never
    carries ``read_plan_bank``: that names a sibling file of the registered bank whose read plan
    the registered bank reuses, while an adapted bank is read at its own items' plan."""
    from wsbench.readplan import READ_PLAN_BANK
    from wsbench.registry import frozen_bank_path

    path = frozen_bank_path(family)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return {}, raw
    # the registered bank's own plan lineage (plan 0083) describes that file, never a set's plan
    own = ("items", READ_PLAN_BANK, "plan_lineage")
    if raw.get("items") and "name" not in raw["items"][0]:
        header = {k: v for k, v in raw.items() if k not in own}
        return header, raw["items"]
    header, items = load_wrapped(path)
    return {k: v for k, v in header.items() if k not in own}, items


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # split on "\n" only: str.splitlines() also breaks on U+2028 / U+0085 etc., which a subject's
    # answer can contain raw inside a JSON string (ensure_ascii=False)
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()
    ]


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _legacy_ok(base: Path, family: str, suffix: str = ".jsonl") -> Path:
    """``base/<family><suffix>``, or the file under a former family key when only that exists
    (a pre-v1.2.0 ``wrong_bridge.jsonl``, a set's ``multihop_mt_v2.json`` written before the
    2026-11-04 rename; for a reused key the former key's file wins, ``registry.lookup_names``)."""
    bare = shared_key(family)
    for key in lookup_names(family):
        path = base / f"{key}{suffix}"
        if not path.exists():
            continue
        if key == bare and suffix == ".jsonl":
            # a work file under the bare key of a renamed pair (plan 0101 §5.5): by its row ids,
            # against the registered banks and then the set's own banks. Candidate ids are in no
            # bank, so an unidentified file is this family's only under its OWN key.
            ids = ids_in(path)
            who = owner(key, ids=ids) if ids else None
            if ids and who is None:
                for member in (family, partner(family)):
                    bank = root_bank(base.parent, str(member))
                    if bank is not None and ids & _bank_file_ids(bank):
                        who = member
                        break
            if who is None and key != family:
                continue
            if who is not None and who != family:
                if key == family:  # never the path a writer of this family appends to
                    raise RenamedKey(
                        f"{path} holds rows of {who!r}, written before the key {key!r} was "
                        f"reused (plan 0101); move it to {who}{suffix}"
                    )
                continue
        return path
    return base / f"{family}{suffix}"


def bank_file(model: str, family: str) -> Path:
    """The set's bank of ``family`` (``<model dir>/<family>.json``, or one written under a former
    family key)."""
    base = model_dir(model)
    return root_bank(base, family) or base / f"{family}.json"


def report_key(section: dict[str, Any] | None, family: str) -> str:
    """The key of ``family``'s entry in a section of a set's ``report.json`` (``families``,
    ``drops``): the first one present in ``registry.lookup_names`` order (a set written before a
    rename keeps its entry under the former key), else ``family``."""
    section = section or {}
    bare = shared_key(family)
    for key in lookup_names(family):
        if key not in section:
            continue
        if key == bare:
            # a set written before plan 0101 keeps the SINGLE-token family under the bare key:
            # the entry's own evidence decides (its item ids, or the registered bank it names);
            # without any, the bare key is the multi-token family's (what it means today)
            who = _entry_owner(key, section[key])
            if who is not None and who != family:
                continue
            if who is None and key != family:
                continue
        return key
    return family


def _entry_owner(key: str, entry: Any) -> str | None:
    """Which member of a renamed pair a report entry under the bare ``key`` belongs to: by the
    item ids a ``drops`` / ``patches`` entry is keyed by, else by the pre-0101 ``"bank":
    "evals/<family>/..."`` string a ``families`` entry carries. None when it does not say."""
    if not isinstance(entry, dict):
        return None
    bank = entry.get("bank")
    if isinstance(bank, str) and bank.startswith("evals/"):
        parts = Path(bank).parts
        if len(parts) >= 3 and parts[1] in registry.PRE_0101_KEYS:  # the pre-0101 layout
            return registry.PRE_0101_KEYS[parts[1]]
        if len(parts) >= 4 and parts[2] in registry.FAMILIES:
            return parts[2]
    try:
        return owner(key, ids=[str(i) for i in entry])
    except RenamedKey:
        return None


def report_entry(section: dict[str, Any] | None, family: str) -> dict[str, Any]:
    """``section[family]`` of a set's ``report.json`` (``families``, ``drops``), or the entry
    written under a former family key (``report_key``); ``{}`` when there is none, and when
    the only entry under the family's bare key is its plan-0101 partner's (a pre-rename report
    that holds the single-token family alone)."""
    section = section or {}
    key = report_key(section, family)
    entry = section.get(key, {})
    if key == shared_key(family) and _entry_owner(key, entry) not in (None, family):
        return {}
    return entry


def report_slot(report: dict[str, Any], section: str, family: str) -> dict[str, Any]:
    """``report[section]``'s entry of ``family``, created when missing: a writer's view of
    ``report_entry``, so an update lands on the entry that readers see."""
    sec = report.setdefault(section, {})
    return sec.setdefault(report_key(sec, family), {})


def gate_path(model: str, family: str) -> Path:
    return _legacy_ok(model_dir(model) / "gate", family)


def cand_path(model: str, family: str) -> Path:
    return _legacy_ok(model_dir(model) / "cand", family)


def gated(model: str, family: str) -> dict[str, dict]:
    """Every gated candidate, last record per id (a re-gate appends)."""
    return {str(r["id"]): r for r in _read_jsonl(gate_path(model, family))}


def record_gates(model: str, family: str, rows: list[dict]) -> None:
    _append_jsonl(gate_path(model, family), rows)


def pending(model: str, family: str) -> list[dict]:
    """Candidates written but not yet gated."""
    done = gated(model, family)
    return [c for c in _read_jsonl(cand_path(model, family)) if item_id(c) not in done]


def add_candidates(model: str, family: str, items: list[dict]) -> int:
    """Append candidates whose id is new to both the candidate file and the gate log."""
    seen = set(gated(model, family)) | {item_id(c) for c in _read_jsonl(cand_path(model, family))}
    fresh = [it for it in items if item_id(it) not in seen]
    _append_jsonl(cand_path(model, family), fresh)
    return len(fresh)


def write_json(path: Path, obj: Any) -> None:
    """Atomic: write a temp file beside it, then rename (a crash never leaves half a bank)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def report_lock(model: str) -> Iterator[None]:
    """Serialise report.json read-modify-writes across processes (steps run in parallel)."""
    lock = model_dir(model) / ".report.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def code_stamp() -> dict[str, str]:
    """Which pipeline wrote a report: the git HEAD, whether the tree was dirty, and a hash of the
    adapt package itself (uncommitted edits change it), so a stale bank is detectable."""
    import hashlib
    import subprocess

    h = hashlib.sha256()
    for f in sorted(Path(__file__).parent.glob("*.py")):
        h.update(f.name.encode() + f.read_bytes())
    try:

        def sh(*a: str) -> str:
            return subprocess.run(["git", "-C", str(REPO_ROOT), *a], capture_output=True,
                                  text=True, timeout=10).stdout.strip()  # fmt: skip

        git, dirty = sh("rev-parse", "--short", "HEAD"), sh("status", "--porcelain", "src")
    except (OSError, subprocess.SubprocessError):
        git, dirty = "", ""
    return {"git": git + ("+dirty" if dirty else ""), "adapt_sha256": h.hexdigest()[:16]}


# freeze's automatic note for a registered family the set lacks (plan 0060 A1.6)
ABSENT_NOTE = "absent: this set has no bank for the family (plan 0060 A1.6)"


def clear_built_absent(model: str, report: dict[str, Any]) -> list[str]:
    """Families whose bank is now on disk but whose entry still carries freeze's AUTOMATIC
    absence (``absent_auto``, set only when freeze added the exclusion; or the automatic note
    itself): the absence goes (``absent_auto``, ``exclude_from_macro``, the automatic note, an
    ``absent`` status). A family built by any writer (freeze, carry, agentic, introspection)
    rejoins the macro, also when a writer replaced the note in between; a hand-written note
    is kept, and an exclusion freeze did not add is never touched. Returns them."""
    root, out = model_dir(model), []
    for fam, e in (report.get("families") or {}).items():
        if not (e.get("absent_auto") or e.get("note") == ABSENT_NOTE):
            continue
        if not ((root / f"{fam}.json").exists() or (root / fam / "manifest.json").exists()):
            continue
        e.pop("absent_auto", None)
        e.pop("exclude_from_macro", None)
        if e.get("note") == ABSENT_NOTE:
            e.pop("note")
        if e.get("status") == "absent":
            e.pop("status")
        out.append(fam)
    return out


def update_report(model: str, mutate: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    """Locked read -> ``mutate(report)`` in place -> stale automatic absences cleared
    (``clear_built_absent``) -> atomic write (stamped with ``code_stamp``). Returns the new
    report. Plan 0101: a set with pre-rename keys is refused (``require_migrated``); every other
    set is stamped with ``SET_MARKER``, so a set created after the rename says that its keys
    are today's and ``scripts/migrate_0101.py set`` never translates them."""
    with report_lock(model):
        report = read_report(model)
        require_migrated(model, report)
        mutate(report)
        clear_built_absent(model, report)
        if not _former_key_left(model, report):
            report[SET_MARKER[0]] = SET_MARKER[1]
        report["code"] = code_stamp()
        write_json(model_dir(model) / "report.json", report)
        return report


# written into report.json by scripts/migrate_0101.py set, and by ``update_report`` for a set
# that holds no pre-rename key
SET_MARKER = ("family_keys", "0101")
# the one former key the write fence lets through (below): a set still holding it is written
# as before, and is NOT marked until `migrate_0101.py set` renames it
UNFENCED_FORMER_KEY = "multihop_mt_v2"


def _former_key_left(model: str, report: dict[str, Any]) -> bool:
    if (model_dir(model) / f"{UNFENCED_FORMER_KEY}.json").exists():
        return True
    return any(
        UNFENCED_FORMER_KEY in (report.get(sec) or {}) for sec in ("families", "drops", "patches")
    )


def pre_0101_evidence(model: str, report: dict[str, Any] | None = None) -> str:
    """What shows that a set was written before plan 0101 and never migrated ("" when nothing
    does): a report entry or a bank file under one of the `_mt` keys the rename retired, or a
    bank under a bare key whose header is the single-token family's."""
    report = read_report(model) if report is None else report
    if report.get(SET_MARKER[0]) == SET_MARKER[1]:
        return ""
    base = model_dir(model)
    # (not multihop_mt_v2: a set still under that 2026-11-04 former key holds one family's files
    # and is read and written through ``lookup_names`` as before)
    retired = ["basic_readout_mt", "multihop_mt", "multilingual_mt", "typo_mt"]
    for sec in ("families", "drops", "patches"):
        hit = [k for k in retired if k in (report.get(sec) or {})]
        if hit:
            return f"report.json {sec}.{hit[0]}"
    for key in retired:
        if (base / f"{key}.json").exists():
            return f"{key}.json"
    for key, r in registry.REUSED_FAMILY_KEYS.items():
        bank = base / f"{key}.json"
        other = r.other_header is not None and bank.is_file()
        if other and registry._header_family(bank) == r.other_header:
            return f"{key}.json (header {r.other_header!r}: the single-token family's)"
    return ""


def require_migrated(model: str, report: dict[str, Any] | None = None) -> None:
    """Plan 0101: nothing WRITES into a set that still uses the pre-rename family keys (reads,
    i.e. judging under ``WSB_BANK_ROOT``, work on it as it is)."""
    why = pre_0101_evidence(model, report)
    if why:
        raise SystemExit(
            f"{model_dir(model)} was written before plan 0101 ({why}); run "
            f"`scripts/migrate_0101.py set {model_dir(model)} --apply` first"
        )


def read_report(model: str) -> dict[str, Any]:
    path = model_dir(model) / "report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
