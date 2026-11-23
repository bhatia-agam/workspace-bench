"""Runs manifest adapter: each listed run is fetched from its volume (judged results, judge
caches and indexes into a local cache; readout files stay where they are) and ingested with
the WorkspaceBench and HallucinationBench adapters. The format is in the viewer README."""

import hashlib
import json
import re
import shutil
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from wsbench import registry
from wsbench import results as wsb_results
from wsbench.viewer import remote, store
from wsbench.viewer.ingest import hb, wsb

READOUT_MODES = ("none", "index", "copy")
METHOD_ALIASES = {
    "s3d": "olens", "o-lens": "olens", "olens": "olens", "model_continuation": "continuation",
    "logit-lens": "logit_lens", "j-lens": "jlens", "mlnla": "nla", "r-lens": "rlens",
    "jpp": "jpp_lens", "j++": "jpp_lens", "jpp-lens": "jpp_lens", "j++ lens": "jpp_lens",
}  # fmt: skip
# manifest key -> the names a runs file may use for it (the first present one wins)
ALIASES = {
    "lens": ("lens", "lens_id"),
    "label": ("label", "alias"),
    "judge_wall_seconds": ("judge_wall_seconds", "judge_seconds"),
    "judge_usd": ("judge_usd", "judge_usd_list", "judge_cost"),
    "total_usd": ("total_usd", "total_usd_list", "total_cost"),
    "read_wall_seconds": ("read_wall_seconds", "read_seconds"),
    "total_wall_seconds": ("total_wall_seconds", "start_to_score_seconds"),
}
NUMBERS = (
    "cells", "read_gpu_hours", "read_wall_seconds", "judge_wall_seconds", "judge_calls",
    "judge_usd", "total_usd", "total_wall_seconds",
)  # fmt: skip
TEXTS = (
    "bench",
    "method",
    "lens",
    "label",
    "run",
    "set",
    "model",
    "volume",
    "environment",
    "readouts",
    "judged",
    "judged_ati",
    "report",
    "results_file",
    "timing_note",
    "bench_commit",
    "engine",
    "state",
    "note",
)
FINISHED = re.compile(r"^\s*(done|finished|complete|completed|judged|scored|ok)\b", re.I)
JUDGED_FILES = ("results.json", "cells.jsonl", "reader_judge.json", "report.json")
SHARD_RE = re.compile(r"^(?P<stem>.+?)\.[^.]+\.\d+of\d+\.jsonl$")
# the set a manifest entry names -> the store's subset; any other text is a description
SET_KINDS = {
    "full": "full", "core": "core", "fast": "fast", "fast-safety": "fast-safety",
    "fast_safety": "fast-safety", "ati": "ati", "anti-text-inversion": "ati",
    "anti_text_inversion": "ati", "anti text inversion": "ati",
}  # fmt: skip
SCOPES = {"fast": "fast", "fast-safety": "fast", "ati": wsb_results.ATI_SCOPE}  # config.scope
FAST_SUFFIX = {"fast": "-fast", "fast-safety": "-fast-safety"}  # a derived run's name
# the entry kinds whose store subset is read from the results' own fast subset stamp
# (`wsb.fast_subset_of`): the current fast subset is `fast`, an earlier one has its own name,
# so a run may hold several fast sets side by side. `fast-safety` is no set of a new run (the
# fast subset has no such variant any more); the name is still read for a folder judged as it.
FAST_KINDS = ("fast", "fast-safety")
SET_INDEX = "sets.json"  # in a run's derived/ work folder: {store subset: folder name}
# files an entry names beside the manifest (else on the volume), and what places a run
NAMED_FILES = ("report", "results_file", "families_file")
SOURCE_KEYS = ("bench", "model", "lens", "run", "volume", "environment", "judged", "readouts",
               "judged_ati")  # fmt: skip
HB_SKIP = ("cache.jsonl",)  # the benchmark's raw call cache: not read by the viewer
# what an ingest leaves in a run's cache folder once the run is stored: the files `viewer
# check` and a facts update read again (results, reports, indexes, summaries, the set index:
# all JSON). The judge-call caches, cell files and readout files (all JSON lines) are in the
# run database by then and can be fetched again, so they are removed, with any unfinished
# download.
REMOVABLE = ("*.jsonl", "*.part")
# HallucinationBench: the per-layer result files of the benign role-play family are read once
# at ingest and by nothing afterwards (the score check reads the index)
REMOVABLE_HB = ("results.json",)
RUN_INDEX = "_run.json"  # a run's own index over all families, in its _index/ cache folder
# family folder of a run -> the eval whose readout files it holds, for the families whose
# cells are not in a judged file
HB_READOUTS = {
    "overrefusal": "overrefusal", "benign_roleplay": "benign_roleplay",
    "agentic_misalignment": "am_situation",
}  # fmt: skip

PART_OUTCOMES = ("n_parts_refused", "n_parts_too_long", "n_parts_all_dropped")
OWN_CALLS = ("relational_multihop",)  # scorers that make their own API calls


# ------------------------------------------------------------------ the manifest


def normalise(raw: Mapping[str, Any], defaults: Mapping[str, Any] | None = None) -> dict:
    """One manifest entry with the viewer's field names; unknown numbers stay None."""
    e = dict(defaults or {}) | dict(raw)
    for key, names in ALIASES.items():
        e[key] = next((e[n] for n in names if e.get(n) is not None), None)
    bench = str(e.get("bench") or "wsb")
    if e.get("bench_commit") is None:
        names = ("judge_commit_hb", "bench_commit_hb") if bench == "hb" else ("bench_commit_wsb",)
        e["bench_commit"] = next((e[n] for n in names if e.get(n)), None)
    out: dict[str, Any] = {k: (None if e.get(k) is None else str(e[k])) for k in TEXTS}
    out["bench"] = bench
    method = (out["method"] or "other").lower()
    method = METHOD_ALIASES.get(method, method)
    out["method"] = method if method in wsb.METHODS else "other"
    out["given_method"] = raw.get("method")
    for k in NUMBERS:
        v = e.get(k)
        out[k] = v if isinstance(v, int | float) and not isinstance(v, bool) else None
    integ = e.get("integrity")
    if isinstance(integ, str):
        integ = {"label": integ, "reason": e.get("integrity_reason") or ""}
    out["integrity"] = integ if isinstance(integ, dict) else None
    out["derived"] = [d for d in e.get("derived") or [] if isinstance(d, dict) and d.get("judged")]
    out["sources"] = list(e.get("sources") or [])
    out["label"] = out["label"] or out["lens"]
    for key in ("judged", "readouts", "judged_ati"):  # `.../hb/<family>/` names a pattern
        if out[key] and "<" in out[key]:
            out[key] = out[key].split("<", 1)[0]
    ff = e.get("families_file")
    out["families_file"] = str(ff) if isinstance(ff, str) and ff else None
    return out


def set_kind(entry: Mapping[str, Any]) -> str | None:
    """The store subset an entry's ``set`` names (full, core, fast, fast-safety, ati), or None
    when it is a description."""
    return SET_KINDS.get(str(entry.get("set") or "").strip().lower())


def is_path(text: str | None) -> bool:
    """A value that can be a path on a volume (a sentence is not)."""
    return bool(text) and not re.search(r"[\s()]", text.strip())


def group(entries: list[dict], problems: Mapping[int, str] | None = None) -> list[dict]:
    """Place every entry: ``[{entry, role, into, why}]`` in manifest order. ``role`` is
    ``run`` (ingested as a run of its own), ``set`` (one set of the full run ``into`` of the
    same lens: its core tier, its anti-text-inversion results, or a fast run derived from
    it, named ``<run>-fast`` or ``<run>-fast-<more>``; a run may have several fast entries,
    one per judged folder) or ``unplaced`` (with ``why``). A ``set`` entry is folded into
    its run's entry (``judged_ati``, ``derived``, ``families_file``, ``members``), so the sets
    of one run are ingested together and never as a second run under the same id.
    ``problems`` (``{id(entry): why}``) are entries already known to be unusable: each is
    ``unplaced``, and so are the sets of a full entry that is."""
    problems = problems or {}
    full: dict[tuple, dict] = {}
    for e in entries:
        key = (e["bench"], e["model"], e["lens"], e["run"])
        if e["bench"] != "hb" and set_kind(e) == "full" and key not in full:
            full[key] = e
    out, taken, folded = [], {}, set()
    for e in entries:
        kind = set_kind(e)
        lens = (e["bench"], e["model"], e["lens"])
        base = None
        if e["bench"] != "hb" and kind not in (None, "full"):
            base = full.get((*lens, e["run"]))
            suffix = FAST_SUFFIX.get(kind)
            if base is None and suffix and e["run"].endswith(suffix):
                base = full.get((*lens, e["run"][: -len(suffix)]))
            if base is None and suffix:  # `<run>-fast-<anything>`: one more fast set of <run>
                at = e["run"].find(suffix + "-")
                base = full.get((*lens, e["run"][:at])) if at > 0 else None
        plan = {"entry": e, "role": "run", "into": None, "why": ""}
        if id(e) in problems:
            plan |= {"role": "unplaced", "why": problems[id(e)]}
        elif base is not None and base is not e and id(base) in problems:
            plan |= {"role": "unplaced", "why": f"its full entry failed: {problems[id(base)]}"}
        elif base is not None and base is not e:
            plan |= {"role": "set", "into": base}
            why = ""
            # one entry per set of a run; a fast set is known by its judged folder, since a
            # run may have a set on the current fast subset and one on an earlier subset
            mark = (id(base), kind, e["judged"].strip("/") if kind in FAST_KINDS else "")
            if mark in folded:
                why = f"a second {kind} entry for run {base['run']}" + (
                    " from the same judged folder" if kind in FAST_KINDS else ""
                )
            elif kind == "core":
                if is_path(e["judged"]) and e["judged"].strip("/") != base["judged"].strip("/"):
                    why = "a core entry is the core tier of its full run's own judged folder"
                elif e["families_file"]:
                    base["families_file"] = e["families_file"]
            elif not is_path(e["judged"]):
                why = f"its judged value is not a path: {e['judged']!r}"
            elif kind == "ati":
                base["judged_ati"] = e["judged"]
            else:
                same = e["judged"].strip("/")
                base["derived"] = [
                    d
                    for d in base["derived"]
                    if d.get("set") != kind
                    or (kind in FAST_KINDS and str(d.get("judged")).strip("/") != same)
                ] + [{"set": kind, "judged": e["judged"], "run": e["run"], "state": e["state"]}]
            if why:
                plan |= {"role": "unplaced", "why": why}
            else:
                folded.add(mark)
                base.setdefault("members", []).append(
                    {"set": kind, "run": e["run"], "judged": e["judged"], "state": e["state"]}
                    | ({"results_file": e["results_file"]} if e.get("results_file") else {})
                )
        elif kind == "core":
            plan |= {
                "role": "unplaced",
                "why": "a core entry needs the full entry of the same lens and run",
            }
        elif (*lens, e["run"]) in taken:
            other = taken[(*lens, e["run"])]
            plan |= {"role": "unplaced",
                     "why": f"run {e['run']} of this lens is already listed with set "
                            f"{other['set']!r}; set {e['set']!r} would replace it"}  # fmt: skip
        else:
            taken[(*lens, e["run"])] = e
        out.append(plan)
    return out


def load(path: Path) -> list[dict]:
    """The runs of a manifest file: a list, or an object with ``runs`` whose other scalar keys
    (``volume``, ``environment``, ``model`` ...) are defaults for every run."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    runs = raw.get("runs") if isinstance(raw, dict) else raw
    if not isinstance(runs, list):
        raise SystemExit(f"{path}: not a runs manifest (a list of runs, or an object with `runs`)")
    defaults = {}
    if isinstance(raw, dict):
        defaults = {k: v for k, v in raw.items() if k in TEXTS and isinstance(v, str)}
    out = []
    for n, r in enumerate(runs):
        e = normalise(r, defaults)
        missing = [k for k in ("lens", "run", "judged", "volume") if not e[k]]
        if missing:
            raise SystemExit(f"{path}: run {n} lacks {', '.join(missing)}")
        out.append(e)
    return out


def finished(entry: Mapping[str, Any]) -> bool:
    """A run without a state is a finished one; a state must say so."""
    return entry.get("state") is None or bool(FINISHED.match(entry["state"]))


def entry_run_id(entry: Mapping[str, Any]) -> str:
    model = entry.get("model") or (hb.MODEL if entry["bench"] == "hb" else wsb.ORIGINAL)
    return store.run_id(entry["bench"], model, entry["lens"], entry["run"])


def work_dir(cache: Path, rid: str) -> Path:
    return cache / "ingest" / rid


# ------------------------------------------------------------------ what the result files say


def family_integrity(family: str, result: Mapping[str, Any], stamp: Mapping[str, Any] | None):
    """``(label, reason, counters)`` of one judged WorkspaceBench family from its own
    results.json and the judge's exit stamp: ``incomplete`` by the benchmark's rule,
    ``provisional`` while cells are unjudged or missing, items undecided or unsummarized, a
    summary part or layered call failed, or the judge ended with a non-zero exit code."""
    counts = result.get("counts") or {}
    extras = (result.get("numbers") or {}).get("extras") or {}
    gated: dict[str, Any] = {
        "unjudged_cells": counts.get("n_unjudged_cells"),
        "missing_cells": counts.get("n_missing_cells"),
        "items_undecided": extras.get("n_items_undecided"),
    }
    if family in OWN_CALLS:
        gated["items_api_failed"] = extras.get("n_items_api_failed")
    summary = extras.get("summary")
    if isinstance(summary, dict):
        gated["items_unsummarized"] = summary.get("n_items_unsummarized")
        parts = summary.get("n_parts_unsummarized")
        outcomes = [summary.get(k) for k in PART_OUTCOMES]
        if parts is not None and all(v is not None for v in outcomes):
            gated["parts_failed"] = parts - sum(outcomes)
        if "n_layered_items" in summary:
            gated["layered_failed"] = summary.get("n_layered_failed")
    bad = {k: v for k, v in gated.items() if v}
    why = [f"{v} {k.replace('_', ' ')}" for k, v in bad.items()]
    if stamp is not None and stamp.get("rc") not in (0, None):
        why.append(f"judge exit code {stamp['rc']}")
    labels = []
    if not result.get("complete"):
        labels.append("incomplete")
        why.insert(0, "incomplete by the benchmark's rule")
    if bad or (stamp is not None and stamp.get("rc") not in (0, None)):
        labels.append("provisional")
    facts = {k: v for k, v in gated.items() if v is not None} | {"complete": result.get("complete")}
    return ", ".join(labels), "; ".join(why), facts


def wsb_headline(judged: Path) -> dict[str, Any]:
    """``{family: value}`` read straight from each results.json (``numbers.value``), plus
    ``_macro`` from report.json when the directory has one, and each family's integrity."""
    values: dict[str, float | None] = {}
    integrity: dict[str, tuple] = {}
    for fam, fdir in wsb.family_dirs(judged).items():
        raw = json.loads((fdir / "results.json").read_text(encoding="utf-8"))
        values[fam] = (raw.get("numbers") or {}).get("value")
        stamp_path = fdir / "reader_judge.json"
        stamp = json.loads(stamp_path.read_text(encoding="utf-8")) if stamp_path.exists() else None
        integrity[fam] = family_integrity(fam, raw, stamp)
    report = judged / "report.json"
    if report.exists():
        macro = (json.loads(report.read_text(encoding="utf-8")).get("macro") or {}).get("value")
        if macro is not None:
            values[wsb.MACRO] = macro
    return {"values": values, "integrity": integrity}


def hb_headline(index: Mapping[str, Any], lens: str) -> dict[str, dict[str, float]]:
    """``{family: {layer: value}}`` of the per-layer index rows of ``lens``."""
    rows = index.get("rows") or []
    mine = [r for r in rows if r.get("method") == lens] or rows
    out: dict[str, dict[str, float]] = {}
    for r in mine:
        if not isinstance(r.get("layer"), int):
            continue
        for fam, v in (r.get("families") or {}).items():
            if isinstance(v, dict) and v.get("v") is not None:
                out.setdefault(fam, {})[str(r["layer"])] = v["v"]
    return out


def merge_indexes(indexes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """One index from the per-family index files of a run (each holds its own family's rows):
    rows are joined by (method, layer), every other key is taken from the first file that has
    it, and dictionaries are merged."""
    out: dict[str, Any] = {}
    rows: dict[tuple, dict] = {}
    for idx in indexes:
        for k, v in idx.items():
            if k == "rows":
                continue
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = v | out[k]
            else:
                out.setdefault(k, v)
        for r in idx.get("rows") or []:
            key = (r.get("method"), r.get("layer"))
            have = rows.setdefault(key, {"method": r.get("method"), "layer": r.get("layer")})
            for k, v in r.items():
                if k == "families":
                    have.setdefault("families", {}).update(v or {})
                elif k not in ("method", "layer"):
                    have.setdefault(k, v)
    out["rows"] = list(rows.values())
    return out


# ------------------------------------------------------------------ ingest


def clean(work: Path, more: tuple[str, ...] = ()) -> tuple[int, int]:
    """Remove the re-fetchable downloads (``REMOVABLE`` and the names in ``more``) from a
    run's cache folder; ``(files removed, bytes freed)``. Result files, reports, indexes and
    the set index stay."""
    n = size = 0
    if not work.is_dir():
        return n, size
    for pattern in (*REMOVABLE, *more):
        for p in sorted(work.rglob(pattern)):
            if p.is_file() and not p.is_symlink():
                size += p.stat().st_size
                p.unlink()
                n += 1
    return n, size


def _under(entries: Iterable[remote.Entry], base: str) -> list[tuple[remote.Entry, str]]:
    """The entries below ``base`` with their path relative to it."""
    base = base.strip("/") + "/"
    return [(e, e.path[len(base) :]) for e in entries if e.path.startswith(base)]


def _signature(entry: Mapping[str, Any], used: Iterable[remote.Entry], mode: str) -> str:
    # keys added after the first stores were written count only when they say something
    later = ("families_file", "members", "results_file", "timing_note")
    entry = {k: v for k, v in entry.items() if v or k not in later}
    text = json.dumps(entry, sort_keys=True, default=str) + f"|{mode}|{store.SCHEMA}|"
    text += "|".join(sorted(e.sig() for e in used))
    return "manifest:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _unchanged(cat, root: Path, rid: str, sig: str) -> bool:
    old = cat.execute("SELECT source_sig FROM run WHERE run_id = ?", (rid,)).fetchone()
    return bool(old and old["source_sig"] == sig and store.run_db_path(root, rid).exists())


def _facts(cat, rid: str, entry: Mapping[str, Any], sig: str, readouts: str, headline: Any):
    """The run's manifest facts and its integrity: the manifest's own label when it gives one,
    else what the per-eval rows say."""
    integ = entry.get("integrity") or {}
    label, reason = integ.get("label"), integ.get("reason") or ""
    if label is None:
        rows = cat.execute(
            "SELECT eval, integrity, reason FROM run_eval WHERE run_id = ? AND integrity != ''"
            " ORDER BY eval",
            (rid,),
        ).fetchall()
        labels = {part for r in rows for part in r["integrity"].split(", ")}
        label = ", ".join(x for x in ("partial", "provisional", "incomplete") if x in labels)
        reason = "; ".join(f"{r['eval']}: {r['reason']}" for r in rows)
    cat.execute(
        "INSERT OR REPLACE INTO run_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, entry["run"], entry["set"], entry["bench_commit"], entry["engine"], entry["cells"],
         entry["read_gpu_hours"], entry["read_wall_seconds"], entry["judge_wall_seconds"],
         entry["judge_calls"], entry["judge_usd"], entry["total_usd"],
         entry["total_wall_seconds"], label, reason, readouts, store.dumps(headline),
         store.dumps(entry)),
    )  # fmt: skip
    cat.execute("UPDATE run SET source_sig = ? WHERE run_id = ?", (sig, rid))
    cat.commit()


def _readout_files(
    volume: remote.Volume, listing: list[remote.Entry], base: str, families: Iterable[str]
) -> dict[str, list[remote.Entry]]:
    """Per family, the readout files under ``base``: ``merged/<family>.jsonl`` (or
    ``<family>.jsonl``), else the read's shards ``<family>.<set>.<i>of<n>.jsonl``."""
    rel = {r: e for e, r in _under(listing, base)}
    out: dict[str, list[remote.Entry]] = {}
    for fam in families:
        names = registry.lookup_names(fam)
        whole = next(
            (rel[p] for n in names for p in (f"merged/{n}.jsonl", f"{n}.jsonl") if p in rel), None
        )
        if whole is not None:
            out[fam] = [whole]
            continue
        shards = [
            e for r, e in sorted(rel.items())
            if "/" not in r and (m := SHARD_RE.match(r)) and m.group("stem") in names
        ]  # fmt: skip
        if shards:
            out[fam] = shards
    return out


def resolve_files(entry: dict, manifest_dir: Path) -> str:
    """Resolve the files an entry names (``report``, ``results_file``, ``families_file``):
    a local file (absolute, or beside the manifest) first, else a path on the run's volume.
    A local file replaces the value by its absolute path. Returns '' or, when a file is in
    neither place, the reason naming both places tried."""
    for key in NAMED_FILES:
        given = entry.get(key)
        if not given:
            continue
        tried = Path(given) if Path(given).is_absolute() else manifest_dir / given
        if tried.is_file():
            entry[key] = str(tried)
            continue
        where = f"volume {entry['volume']}"
        found = False
        if is_path(given) and not Path(given).is_absolute():
            volume = remote.open_volume(entry["volume"], entry.get("environment"))
            where = volume.url(given)
            try:
                found = bool(volume.ls(given))
            except remote.UnavailableError:
                found = False
        if not found:
            return f"{key} {given!r}: no local file {tried} and nothing at {where}"
    return ""


def _named_file(entry: Mapping[str, Any], key: str, volume: remote.Volume) -> Path:
    """The local copy of a file an entry names: the local file, else fetched from the volume."""
    given = entry[key]
    if Path(given).is_file():
        return Path(given)
    listed = volume.ls(given) if is_path(given) else []
    if not listed:
        raise SystemExit(f"{key} {given!r}: not a local file and nothing at {volume.url(given)}")
    dest = remote.cache_path(volume.url(given))
    remote.fetch_to(volume, listed[0], dest)
    return dest


def _report(entry: Mapping[str, Any], volume: remote.Volume, judged: Path) -> str:
    """Put the run's report.json beside its judged families: the manifest's ``report`` (a
    local file, else a path on the volume), else the one already there, else the macro by the
    bench's own rule over these results. Returns where it came from."""
    dest = judged / "report.json"
    if entry.get("report"):
        src = _named_file(entry, "report", volume)
        shutil.copyfile(src, dest)
        return str(src)
    if dest.exists():
        return "report.json in the judged directory"
    results = [wsb_results.read_results(d) for d in wsb.family_dirs(judged).values()]
    try:
        macro = wsb_results.macro(results)
    except SystemExit:
        return ""
    dest.write_text(json.dumps({"macro": macro, "written_by": "wsbench viewer"}), "utf-8")
    return "the bench's macro rule over the judged families (the run has no report.json)"


def _families_file(entry: Mapping[str, Any], volume: remote.Volume) -> list[str] | None:
    """The core families a ``families_file`` lists (one per line); None when the entry names
    none: the benchmark's own core tier is used."""
    if not entry.get("families_file"):
        return None
    text = _named_file(entry, "families_file", volume).read_text(encoding="utf-8")
    return [x.strip() for x in text.splitlines() if x.strip() and not x.startswith("#")]


def _differs(
    entry: Mapping[str, Any], headline: Mapping[str, Any], volume,
    stored: Mapping[str, str] | None = None,
) -> dict[str, list]:  # fmt: skip
    """Per set, the evals whose stored result differs from the run's own ``results_file``
    (``{eval: {"value": ...}}``): a second, independent reference beside the judged folder.
    ``stored`` (``{a set entry's judged folder: its store subset}``) places a fast entry,
    whose subset is the one its results are stamped with."""
    main = next(iter(headline), None)
    stored = stored or {}
    files = [(main, entry.get("results_file"))] + [
        (stored.get(str(m["judged"]).strip("/"), m["set"]), m.get("results_file"))
        for m in entry.get("members") or []
        if m["set"] != "core"
    ]
    out: dict[str, list] = {}
    for subset, given in files:
        if not given or subset not in headline:
            continue
        ref = json.loads(_named_file({"f": given}, "f", volume).read_text(encoding="utf-8"))
        have = headline[subset]
        out[subset] = [
            f"{fam}: judged folder {have.get(fam)} != {Path(given).name} {v.get('value')}"
            for fam, v in ref.items()
            if isinstance(v, dict) and v.get("value") is not None
            and (have.get(fam) is None or abs(have[fam] - v["value"]) > 1e-9)
        ]  # fmt: skip
    return out


def _source_fields(entry: Mapping[str, Any]) -> list:
    """What decides which files a run is ingested from; every other key is a fact about it."""
    derived = sorted(
        (str(d.get("set")), str(d.get("judged")).strip("/"), str(d.get("run")))
        for d in entry.get("derived") or []
    )
    return [str(entry.get(k) or "").strip("/") for k in SOURCE_KEYS] + [derived]


def _refresh(cat, root: Path, cache: Path, rid: str, entry, used, mode: str, sig: str, volume):
    """A run whose files on the volume are as they were at its last ingest and whose entry
    still names the same folders: only its facts changed (timings, cost, notes, label, the
    report or families file). They are updated in place, nothing is downloaded and the run
    database is not rebuilt. Returns the result, or None when the run must be ingested."""
    row = cat.execute(
        "SELECT f.entry, f.headline, f.readouts, r.source_sig FROM run_facts f JOIN run r"
        " USING (run_id) WHERE run_id = ?",
        (rid,),
    ).fetchone()
    if row is None or not store.run_db_path(root, rid).exists():
        return None
    old = store.loads(row["entry"], {})
    if _signature(old, used, mode) != row["source_sig"]:
        return None  # the files changed since they were ingested
    if _source_fields(old) != _source_fields(entry):
        return None
    headline = store.loads(row["headline"], {})
    changed = sorted(k for k in set(old) | set(entry) if old.get(k) != entry.get(k))
    if entry["bench"] != "hb":
        main = cat.execute(
            "SELECT subset FROM run_set WHERE run_id = ? AND derived = 0 AND origin = 'judged'",
            (rid,),
        ).fetchone()
        subset = main["subset"] if main else next(iter(headline), "full")
        if entry.get("report"):
            src = _named_file(entry, "report", volume)
            report = json.loads(src.read_text(encoding="utf-8"))
            macro = report.get("macro") or {}
            if macro.get("value") is not None:
                wsb._score(
                    cat,
                    rid,
                    wsb.MACRO,
                    subset,
                    -1,
                    "lens",
                    macro["value"],
                    None,
                    len(macro.get("families") or []),
                    "the run's own macro (report.json)",
                )
                headline.setdefault(subset, {})[wsb.MACRO] = macro["value"]
            judged = work_dir(cache, rid) / "judged"
            if judged.is_dir():  # what `viewer check` re-reads
                shutil.copyfile(src, judged / "report.json")
        families = _families_file(entry, volume)
        if families:
            cat.execute("DELETE FROM score WHERE run_id = ? AND subset = ?", (rid, wsb.CORE))
            wsb.write_core_scores(cat, rid, None, None, families)
    cat.execute(
        "UPDATE run SET label = ?, method = ? WHERE run_id = ?",
        (entry["label"], entry["method"], rid),
    )
    _facts(cat, rid, entry, sig, row["readouts"], headline)
    # where each derived folder was stored: its set rows name the derived run as their origin
    origins: dict[str, list[str]] = {}
    for r in cat.execute(
        "SELECT subset, origin FROM run_set WHERE run_id = ? AND derived = 1 ORDER BY subset",
        (rid,),
    ):
        origins.setdefault(r["origin"], []).append(r["subset"])
    placed = {}
    for d in entry.get("derived") or []:
        names = origins.get(d.get("run") or d["judged"]) or []
        if names:
            placed[str(d["judged"]).strip("/")] = names.pop(0)
    return {"status": "facts updated", "run_id": rid, "changed": changed,
            "sets": sorted({r["subset"] for r in _stored_sets(root, rid)}), "placed": placed,
            "differs": _differs(entry, headline, volume, placed)}  # fmt: skip


def _wrong_scope(judged: Path, want: Any, name: str) -> str:
    """Why a fetched judged folder is not the set ``name``: its results are stamped as
    another subset (``want``: the subset scope the set has, None for a whole-bank set, which
    may carry a family's own scope but never a subset's; ... = not checked)."""
    if want is ...:
        return ""
    subsets = set(SCOPES.values())
    for fdir in sorted(p for p in judged.iterdir() if (p / "results.json").is_file()):
        with open(fdir / "results.json", "rb") as fh:
            head = fh.read(65536).decode("utf-8", "replace")
        m = re.search(r'"scope":\s*(null|"[^"]*")', head)
        scope = None if m is None or m.group(1) == "null" else m.group(1).strip('"')
        if (scope in subsets) if want is None else (scope != want):
            return f"{fdir.name}/results.json is stamped scope {scope!r}: not a {name!r} result"
    return ""


def _stored_sets(root: Path, rid: str) -> list:
    cat = store.catalog(root, readonly=True)
    rows = cat.execute("SELECT subset FROM run_set WHERE run_id = ?", (rid,)).fetchall()
    cat.close()
    return rows


def remove_run(cat, root: Path, rid: str) -> None:
    """Take one run out of the store: its catalog rows and its run database."""
    for table in (*store.PER_RUN_TABLES, "run_facts", "run"):
        cat.execute(f"DELETE FROM {table} WHERE run_id = ?", (rid,))
    cat.commit()
    store.run_db_path(root, rid).unlink(missing_ok=True)


def _remove_folded(cat, root: Path, entry, derived: Mapping[str, Any], address: str) -> str:
    """A derived run that an earlier ingest stored as a run of its own (from the same judged
    folder) is now a set of its full run: the separate copy is removed. Returns its id."""
    model = entry["model"] or wsb.ORIGINAL
    rid = store.run_id("wsb", model, entry["lens"], derived["run"])
    row = cat.execute("SELECT source FROM run WHERE run_id = ?", (rid,)).fetchone()
    facts = cat.execute("SELECT 1 FROM run_facts WHERE run_id = ?", (rid,)).fetchone()
    if row is None or facts is None or row["source"] != address:
        return ""
    remove_run(cat, root, rid)
    return rid


def _sibling(judged: str, name: str) -> str:
    return judged.strip("/").rsplit("/", 1)[0] + "/" + name


def _fast_run_judged(entry: Mapping[str, Any]) -> str:
    """Where the reader keeps the fast set derived from a full run: run ``<run>-fast``."""
    parts = entry["judged"].strip("/").split("/")
    return "/".join(f"{p}-fast" if p == entry["run"] else p for p in parts)


def ingest_wsb(entry, root: Path, volume, cache: Path, *, readouts: str, build_dir, repo,
               force: bool, families, keep_downloads: bool = False) -> dict[str, Any]:  # fmt: skip
    kind = set_kind(entry)
    if not is_path(entry["judged"]):
        return {"status": "failed", "why": f"its judged value is not a path: {entry['judged']!r}"}
    judged = entry["judged"].strip("/")
    lens_dir = judged.rsplit("/", 1)[0]
    listing = volume.ls(lens_dir)
    ro_base = (entry["readouts"] or lens_dir).strip("/")
    if not (ro_base + "/").startswith(lens_dir + "/"):
        listing += volume.ls(ro_base)
    ati = (entry["judged_ati"] or _sibling(judged, "judged_ati")).strip("/")
    if not (ati + "/").startswith(lens_dir + "/"):
        listing += volume.ls(ati)
    derived = [d for d in entry["derived"] if d.get("state") is None or FINISHED.match(d["state"])]
    if not entry["derived"] and kind == "full" and _fast_run_judged(entry) != judged:
        derived = [
            {"set": "fast", "judged": _fast_run_judged(entry), "run": entry["run"] + "-fast"}
        ]
    derived_files = {d["judged"]: volume.ls(d["judged"]) for d in derived}
    derived = [dict(d) for d in derived if derived_files[d["judged"]]]
    taken: set[str] = set()
    for n, d in enumerate(derived):  # each derived folder's own place in the work folder
        d["dir"] = d["set"] if d["set"] not in taken else f"{d['set']}.{n}"
        taken.add(d["dir"])

    def judged_files(entries, base):
        return [(e, r) for e, r in _under(entries, base)
                if r.rsplit("/", 1)[-1] in JUDGED_FILES and r.count("/") <= 1]  # fmt: skip

    main = judged_files(listing, judged)
    fams = sorted({r.split("/")[0] for _e, r in main if r.endswith("/results.json")})
    if families:
        fams = [f for f in fams if f in families]
    if not fams:
        return {"status": "not judged yet", "why": f"no <eval>/results.json under {judged}"}
    ati_files = judged_files(listing, ati)
    ro_all = [
        e for e, r in _under(listing, ro_base)
        if r.endswith(".jsonl") and (r.startswith("merged/") or "/" not in r)
    ]  # fmt: skip
    used = [e for e, _r in main + ati_files] + ro_all
    used += [e for d in derived for e, _r in judged_files(derived_files[d["judged"]], d["judged"])]
    sig = _signature(entry, used, readouts)
    rid = entry_run_id(entry)
    cat = store.catalog(root)
    same = _unchanged(cat, root, rid, sig)
    old = cat.execute("SELECT set_name FROM run_facts WHERE run_id = ?", (rid,)).fetchone()
    cat.close()
    if same and not force:
        return {"status": "unchanged", "run_id": rid}
    if not same and not force:
        cat = store.catalog(root)
        got = _refresh(cat, root, cache, rid, entry, used, readouts, sig, volume)
        cat.close()
        if got:
            return got
    was = set_kind({"set": old["set_name"]}) if old else None
    if old and kind != "full" and was != kind and (was or kind):
        return {"status": "failed", "why": f"the store holds this run as set "
                f"{old['set_name']!r}; a {entry['set']!r} entry never replaces it"}  # fmt: skip
    core_families = _families_file(entry, volume)

    work = work_dir(cache, rid)
    # fetched now: the result files of every set (small next to the rest, and kept). Fetched
    # eval by eval while the run is ingested, and removed again once the eval is in the run
    # database: the full run's judge-call caches and readout files. The judge-call caches of
    # the other sets are never read (their cells and judge calls are the full run's).
    calls = "cells.jsonl"
    pairs, heavy = [], {}  # heavy: eval -> its (entry, destination) pairs
    for e, r in main:
        if r.endswith("/" + calls):
            if r.split("/")[0] in fams:
                heavy.setdefault(r.split("/")[0], []).append((e, work / "judged" / r))
        elif r.split("/")[0] in fams or "/" not in r:
            pairs.append((e, work / "judged" / r))
    pairs += [(e, work / "judged_ati" / r) for e, r in ati_files if not r.endswith("/" + calls)]
    for d in derived:
        pairs += [(e, work / "derived" / d["dir"] / r)
                  for e, r in judged_files(derived_files[d["judged"]], d["judged"])
                  if not r.endswith("/" + calls)]  # fmt: skip
    n_got, n_bytes = remote.fetch_all(volume, pairs)
    addresses: dict[str, str] = {}
    lazy: dict[str, list[tuple[str, int]]] = {}
    ro = _readout_files(volume, listing, ro_base, wsb.family_dirs(work / "judged"))
    for fam, files in ro.items():
        if readouts != "none" and len(files) == 1:
            dest = work / "readouts" / f"{fam}.jsonl"
            heavy.setdefault(fam, []).append((files[0], dest))
            addresses[str(dest)] = volume.url(files[0].path)
            dest.parent.mkdir(parents=True, exist_ok=True)
        else:
            lazy[fam] = [(volume.url(e.path), e.size) for e in files]
    tally = {"files": n_got, "bytes": n_bytes, "removed": 0, "freed": 0}

    def bring(fam: str) -> None:
        got = remote.fetch_all(volume, heavy.get(fam, ()))
        tally["files"], tally["bytes"] = tally["files"] + got[0], tally["bytes"] + got[1]

    def drop(fam: str) -> None:
        for _e, dest in () if keep_downloads else heavy.get(fam, ()):
            if dest.is_file():
                tally["removed"], tally["freed"] = (
                    tally["removed"] + 1,
                    (tally["freed"] + dest.stat().st_size),
                )
                dest.unlink()

    # everything is checked before the store is touched: a folder that holds another set
    # than the entry names is refused, and the run in the store stays as it is
    wrong = _wrong_scope(work / "judged", SCOPES.get(kind) if kind else ..., entry["set"])
    if (work / "judged_ati").is_dir():
        wrong = wrong or _wrong_scope(work / "judged_ati", SCOPES["ati"], "anti-text-inversion")
    for d in derived:
        wrong = wrong or _wrong_scope(work / "derived" / d["dir"], SCOPES.get(d["set"]), d["set"])
    if wrong:
        return {"status": "failed", "why": wrong}
    names: dict[str, dict] = {}  # store subset -> the derived folder stored under it
    for d in derived:
        ddir = work / "derived" / d["dir"]
        d["subset"] = wsb.fast_set_of(ddir) if d["set"] in FAST_KINDS else d["set"]
        if d["subset"] in names:
            other = names[d["subset"]]
            return {"status": "failed", "why": f"{d['judged']} and {other['judged']} are both "
                    f"scored on the set {d['subset']!r}: one run holds a set once"}  # fmt: skip
        names[d["subset"]] = d
    report_from = _report(entry, volume, work / "judged")
    head = wsb_headline(work / "judged")

    out = wsb.ingest(
        work, root, lens=entry["lens"], model=entry["model"] or wsb.ORIGINAL,
        method=entry["method"], label=entry["label"],
        readouts=work / "readouts" if (work / "readouts").is_dir() else None,
        repo=repo or registry.REPO_ROOT, families=list(families) if families else None,
        build_dir=build_dir, force=True, copy_max_mb=2**40 if readouts == "copy" else 0,
        run_name=entry["run"], source=volume.url(judged),
        source_name=lambda p: addresses.get(str(p), volume.url(ro_base)),
        remote_readouts=lazy, core_families=core_families,
        before_family=bring, after_family=drop,
    )  # fmt: skip
    n_got, n_bytes = tally["files"], tally["bytes"]
    cat = store.catalog(root)
    model = entry["model"] or wsb.ORIGINAL
    stored = cat.execute(
        "SELECT subset FROM run_set WHERE run_id = ? AND derived = 0 AND origin = 'judged'", (rid,)
    ).fetchone()
    headline = {(stored["subset"] if stored else "full"): head["values"]}
    for fam, (label, why, facts) in head["integrity"].items():
        cat.execute(
            "INSERT OR REPLACE INTO run_eval VALUES (?,?,?,?,?)",
            (rid, fam, label, why, store.dumps(facts)),
        )
    if (work / "judged_ati").is_dir() and kind == "full":
        headline["ati"] = wsb_headline(work / "judged_ati")["values"]
        wsb.write_set(cat, rid, "ati", True, "judged_ati/",
                      "the anti-text-inversion questions of the full run's readouts, judged as "
                      "their own set")  # fmt: skip
    for d in derived:
        ddir = work / "derived" / d["dir"]
        cat.execute("DELETE FROM score WHERE run_id = ? AND subset = ?", (rid, d["subset"]))
        wsb.ingest_subset(cat, rid, model, ddir, d["subset"])
        note = d.get("note") or (
            f"the {d['set']} questions of the full run, cut from its readouts and judged again "
            "from its judge caches"
        )
        if d["set"] in FAST_KINDS:  # the stamp tells the page which fast subset this is
            stamp = wsb.stamp_note(
                {f: wsb_results.read_results(p) for f, p in wsb.family_dirs(ddir).items()}
            )
            note += f" ({stamp})" if stamp else ""
        wsb.write_set(cat, rid, d["subset"], True, d.get("run") or d["judged"], note)
        headline[d["subset"]] = wsb_headline(ddir)["values"]
    if derived:  # where `viewer check` finds each set's result files again
        (work / "derived" / SET_INDEX).write_text(
            json.dumps({d["subset"]: d["dir"] for d in derived}), encoding="utf-8"
        )
    placed = {str(d["judged"]).strip("/"): d["subset"] for d in derived}
    removed = [
        r for d in derived
        if d.get("run") and (r := _remove_folded(cat, root, entry, d, volume.url(d["judged"])))
    ]  # fmt: skip
    _facts(cat, rid, entry, sig, volume.url(ro_base), headline)
    cat.close()
    return {
        "status": "ingested", "run_id": rid, "evals": len(out["families"]),
        "families": out["families"], "report": report_from, "removed": removed,
        "placed": placed, "differs": _differs(entry, headline, volume, placed),
        "sets": sorted({r["subset"] for r in _stored_sets(root, rid)}),
        "downloaded_files": n_got, "downloaded_bytes": n_bytes,
        "cleaned": (tally["removed"], tally["freed"]),
        "readouts": {"mode": readouts, "on_volume": sorted(lazy),
                     "indexed": sorted(set(ro) - set(lazy))},
    }  # fmt: skip


def ingest_hb(entry, root: Path, volume, cache: Path, *, build_dir, hb_repo, force: bool,
              families) -> dict[str, Any]:  # fmt: skip
    base = entry["judged"].strip("/")
    everything = _under(volume.ls(base), base)
    listing = [(e, r) for e, r in everything if "/out/" in r]
    listing = [(e, r) for e, r in listing if r.rsplit("/", 1)[-1] not in HB_SKIP]
    index_files = [(e, r) for e, r in listing if re.search(r"/out/index/[^/]+/index\.json$", r)]
    # the run's own index over all its families, beside the family folders: when it is there
    # it is the index, and the per-family ones are not merged
    whole = [(e, r) for e, r in everything if re.fullmatch(r"index/[^/]+/index\.json", r)]
    if not index_files and not whole:
        return {"status": "not judged yet", "why": f"no index.json under {base}"}
    used = [e for e, _r in listing + whole]
    # readout files of the families whose cells are not in a judged file: left on the volume
    # and read when a question is opened (they are not part of what decides a re-ingest)
    ro_files: dict[str, list[tuple[str, int]]] = {}
    for e, r in everything:
        fam, _, rest = r.partition("/readouts/")
        if rest.endswith(".jsonl") and fam in HB_READOUTS:
            ro_files.setdefault(HB_READOUTS[fam], []).append((volume.url(e.path), e.size))
    sig = _signature(entry, used, "hb")
    rid = entry_run_id(entry)
    cat = store.catalog(root)
    same = _unchanged(cat, root, rid, sig)
    got = None if same or force else _refresh(cat, root, cache, rid, entry, used, "hb", sig, volume)
    cat.close()
    if same and not force:
        return {"status": "unchanged", "run_id": rid}
    if got:
        return got

    work = work_dir(cache, rid)
    pairs, names = [], {}
    for e, r in listing:
        fam, rest = r.split("/out/", 1)
        if rest.startswith("index/"):
            if rest.endswith("/index.json"):
                pairs.append((e, work / "_index" / f"{fam.replace('/', '_')}.json"))
        elif hb.reads(rest):  # the rest of a judged tree is not read: not fetched
            pairs.append((e, work / "lens" / rest))
            names[str(work / "lens" / rest)] = volume.url(e.path)
    run_index = work / "_index" / RUN_INDEX
    if whole:
        pairs.append((whole[0][0], run_index))
    else:
        run_index.unlink(missing_ok=True)
    n_got, n_bytes = remote.fetch_all(volume, pairs)
    judge = (whole or index_files)[0][1].split("index/", 1)[1].split("/", 1)[0]
    if whole:
        index = json.loads(run_index.read_text(encoding="utf-8"))
    else:
        index = merge_indexes(
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((work / "_index").glob("*.json"))
        )
    dest = work / "lens" / "index" / judge / "index.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(index)
    if not dest.exists() or dest.read_text(encoding="utf-8") != text:
        dest.write_text(text, encoding="utf-8")
    out = hb.ingest(
        work / "lens", root, lens=entry["lens"], model=entry["model"] or hb.MODEL,
        method=entry["method"], label=entry["label"], hb_repo=hb_repo,
        families=list(families) if families else None, build_dir=build_dir, force=True,
        judge=judge, run_name=entry["run"], source=volume.url(base),
        source_name=lambda p: names.get(str(p), volume.url(base)),
        remote_readouts=ro_files,
    )  # fmt: skip
    cat = store.catalog(root)
    headline = {"index": hb_headline(index, entry["lens"])}
    readouts = (entry["readouts"] or base).strip("/")
    _facts(cat, rid, entry, sig, volume.url(readouts), headline)
    cat.close()
    return {
        "status": "ingested", "run_id": rid, "evals": len(headline["index"]),
        "families": out["families"], "sets": ["full"], "recount": out.get("check"),
        "downloaded_files": n_got, "downloaded_bytes": n_bytes,
        "readouts": {"mode": "copy", "on_volume": [], "indexed": sorted(out["families"])},
    }  # fmt: skip


def ingest_entry(
    entry: Mapping[str, Any],
    store_root: Path,
    *,
    cache: Path | None = None,
    readouts: str = "none",
    build_dir: Path | None = None,
    repo: Path | None = None,
    hb_repo: Path | None = None,
    force: bool = False,
    families: list[str] | None = None,
    keep_downloads: bool = False,
) -> dict[str, Any]:
    """Ingest one manifest run. ``readouts``: ``none`` records where each eval's readout
    files are and reads a question's cells from there on demand (nothing is downloaded now, no
    per-cell flags or search); ``index`` fetches each eval's readout file once to index its
    cells and set the flags, keeping only flagged cells' text; ``copy`` also keeps every
    cell's text. HallucinationBench cells carry their samples in the judge's own cells file,
    which is always ingested. Once the run is in the store its cache folder keeps only what
    is read again (``clean``; ``cleaned`` = files removed, bytes freed); ``keep_downloads``
    leaves every download. Returns ``status`` = ingested | unchanged | in progress | not
    judged yet | failed, with the reason."""
    if readouts not in READOUT_MODES:
        raise SystemExit(f"readouts must be one of {', '.join(READOUT_MODES)}, not {readouts!r}")
    t0 = time.time()
    base = {"run": entry["run"], "lens": entry["lens"], "bench": entry["bench"],
            "run_id": entry_run_id(entry)}  # fmt: skip
    if not finished(entry):
        return base | {"status": "in progress", "why": f"state: {entry['state']}"}
    cache = remote.cache_root(cache)
    volume = remote.open_volume(entry["volume"], entry.get("environment"))
    try:
        if entry["bench"] == "hb":
            out = ingest_hb(entry, store_root, volume, cache, build_dir=build_dir,
                            hb_repo=hb_repo, force=force, families=families)  # fmt: skip
        else:
            out = ingest_wsb(
                entry,
                store_root,
                volume,
                cache,
                readouts=readouts,
                build_dir=build_dir,
                repo=repo,
                force=force,
                families=families,
                keep_downloads=keep_downloads,
            )
    except (remote.UnavailableError, SystemExit) as e:
        return base | {"status": "failed", "why": str(e)}
    except Exception as e:  # one broken run never stops the others; the command still fails
        return base | {"status": "failed", "why": f"{type(e).__name__}: {e}"}
    db = store.run_db_path(store_root, base["run_id"])
    if out["status"] in ("ingested", "unchanged", "facts updated") and not keep_downloads:
        # the run is in the store: what is left of its downloads (also an earlier ingest's)
        swept = clean(
            work_dir(cache, base["run_id"]), REMOVABLE_HB if entry["bench"] == "hb" else ()
        )
        before = out.get("cleaned") or (0, 0)
        out["cleaned"] = (before[0] + swept[0], before[1] + swept[1])
    return (
        base
        | out
        | {
            "seconds": round(time.time() - t0, 1),
            "db_bytes": db.stat().st_size if db.exists() else 0,
        }
    )


def ingest_manifest(
    manifest: Path, store_root: Path, *, run: str | None = None, lens: str | None = None,
    bench: str | None = None, environment: str | None = None, **options: Any,
) -> list[dict[str, Any]]:  # fmt: skip
    """Every run of the manifest (or the ones ``run`` / ``lens`` / ``bench`` name), one lens at
    a time, one result per entry. The entries of one run (its full, core, fast and
    anti-text-inversion sets) are ingested together as one store run (``group``). A run that
    is in progress, not judged yet or unchanged is reported and left; an entry that cannot be
    placed, or whose folder holds another set than it names, is ``failed`` and the store keeps
    what it has; the other runs are still ingested. ``environment`` is the Modal environment
    of runs whose entry names none; ``run`` names a run or one of its derived runs."""
    entries = load(manifest)
    problems: dict[int, str] = {}
    for entry in entries:
        entry["environment"] = entry["environment"] or environment
        entry["model"] = entry["model"] or (hb.MODEL if entry["bench"] == "hb" else wsb.ORIGINAL)
        if finished(entry) and (why := resolve_files(entry, Path(manifest).resolve().parent)):
            problems[id(entry)] = why
    plans = group(entries, problems)

    def wanted(e: Mapping[str, Any]) -> bool:
        return not ((run and e["run"] != run) or (lens and e["lens"] != lens)
                    or (bench and e["bench"] != bench))  # fmt: skip

    chosen = {id(p["into"] or p["entry"]) for p in plans if wanted(p["entry"])}
    done: dict[int, dict] = {}
    out = []
    for plan in plans:
        entry = plan["entry"]
        if id(plan["into"] or entry) not in chosen:
            continue
        head = {"run": entry["run"], "lens": entry["lens"], "bench": entry["bench"],
                "set": entry["set"]}  # fmt: skip
        if plan["role"] == "run":
            if id(entry) not in done:
                done[id(entry)] = ingest_entry(entry, store_root, **options)
            out.append(done[id(entry)] | {"set": entry["set"]})
            continue
        base = plan["into"]
        rid = entry_run_id(base or entry)
        if plan["role"] == "unplaced":
            out.append(head | {"run_id": rid, "status": "failed", "why": plan["why"]})
        elif not finished(entry):
            out.append(head | {"run_id": rid, "status": "in progress",
                               "why": f"state: {entry['state']}"})  # fmt: skip
        else:
            # the full entry comes first in every runs file seen; if not, ingest it now
            if id(base) not in done:
                done[id(base)] = ingest_entry(base, store_root, **options)
            got = done[id(base)]
            status = {"ingested": "set ingested"}.get(got["status"], got["status"])
            why = got.get("why") or ""
            # a fast entry is stored under the subset its results are stamped with
            name = (got.get("placed") or {}).get(str(entry["judged"]).strip("/"), set_kind(entry))
            stored = name in (got.get("sets") or [])
            if got["status"] in ("ingested", "facts updated") and not stored:
                status, why = "failed", f"the run has no {set_kind(entry)} scores to store"
            out.append(head | {"run_id": rid, "status": status, "into": base["run"],
                               "subset": name,
                               "why": f"its full run: {why}" if why and status != "failed"
                               else why})  # fmt: skip
    return out
