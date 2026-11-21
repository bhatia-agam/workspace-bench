"""The ledger of instrument changes declared since plan 0101, and T1's comparison rule.

``scripts/manifest_0101.py`` and ``tests/golden/manifest_0101_pre.json`` are frozen (the golden
embeds the sha of the script that made it; the script has since gained one ``try`` in
``plan_entry``, without which it exits on a family whose bank changed after an older fast
version was frozen, and T1 pins both shas). A family whose manifest rows differ from the
golden's, or that the golden does not have, must be recorded in
``tests/golden/manifest_0101_declared.json``:

    {"<family>": {"prompt_version", "bank_file", "bank_sha256", "rows_sha256", "plan", "note"}}

``rows_sha256`` hashes the family's whole manifest entry as it is now, so a later change to a
declared family is caught like a change to an undeclared one. ``verdict`` is the rule
(``tests/test_rename_0101.py`` T1 runs it); this script writes an entry:

    python scripts/manifest_0101_declare.py <family> --plan 0099 --note "..." [--write]

It rebuilds the manifest of the current tree (``manifest_0101.py --out <tmp> --any-tree``) and
REFUSES unless the family's result stamp or registered bank (file name or sha256) differs from
the golden's and, when the family already has an entry, from that entry's: a change is declared
by bumping the stamp or the bank version, never by re-hashing. Family keys are the manifest's
(pre-0101 names); a current key is translated.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/manifest_0101.py"
GOLDEN = REPO / "tests/golden/manifest_0101_pre.json"
LEDGER = REPO / "tests/golden/manifest_0101_declared.json"
TRIPLE = (("prompt_version", "stamps"), ("bank_file", "files"), ("bank_sha256", "files"))
# what a stamp-only declaration may move: the stamps and the recorded run (call keys, cache
# fingerprints); plan_sha, file shas, seeds, option lists, tables and lens-store rows may not
STAMP_SECTIONS = frozenset({"stamps", "run"})
COMMAND = (
    "python scripts/manifest_0101_declare.py {family} --plan <NNNN> --note '<what moved>' --write"
)


class Refused(Exception):  # noqa: N818 (as migrate_0101.Refused)
    """Nothing to declare, or a change without a stamp or bank version bump."""


def paths(a: Any, b: Any, path: str = "") -> list[str]:
    """The JSON paths at which two documents differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted({*a, *b}):
            if k in a and k in b:
                out += paths(a[k], b[k], f"{path}/{k}")
            else:
                out.append(f"{path}/{k}: only in {'the golden' if k in a else 'this tree'}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in paths(x, y, f"{path}[{i}]")]  # fmt: skip
    return [] if a == b else [f"{path}: {str(a)[:80]!r} != {str(b)[:80]!r}"]


def triple(rows: Mapping[str, Any]) -> dict[str, Any]:
    """What declares a change: the result stamp and the registered bank's file name and sha."""
    return {key: rows[sec][key] for key, sec in TRIPLE}


def rows_sha256(rows: Mapping[str, Any]) -> str:
    """The family's manifest entry as canonical JSON (sorted keys, no spaces), hashed."""
    text = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fix(family: str, what: str) -> str:
    return (
        f"instrument of {family} differs from the migration golden and from its declared state "
        f"({what}); if the change is deliberate, bump the stamp or bank version and update "
        f"tests/golden/manifest_0101_declared.json with `{COMMAND.format(family=family)}`"
    )


FAST_ROWS = ("plan", "fast_plan_sha")  # {fast version: the family's fast plan sha}


def new_fast_rows(
    fam: str, g: Mapping[str, Any], c: Mapping[str, Any], golden_versions: set[str],
    fast_as: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:  # fmt: skip
    """``c`` without its ACCEPTABLE rows for fast versions cut after the golden, and one line
    per row that is not acceptable (those stay in the entry). A fast version the golden has for
    NO family is new; its row for a family is acceptable iff it equals the family's row under a
    golden version (the same plan rows under a new name), directly or, for a family whose rows
    hash the version string, as recomputed under that golden version's name
    (``fast_as[fam][new] = {"row": that row, "as": {old: sha}}``, from ``fast_equivalents``;
    ignored unless ``row`` is this very row). What this returns is what
    ``verdict`` compares and what ``rows_sha256`` hashes for the ledger, so cutting a fast
    version later moves no family's declared state."""
    sec, key = FAST_ROWS
    have, was = dict(c.get(sec, {}).get(key, {})), g.get(sec, {}).get(key, {})
    new = sorted(v for v in have if v not in golden_versions)
    if not new:
        return dict(c), []
    bad = []
    for v in new:
        sha = have[v]
        eq = fast_as.get(fam, {}).get(v, {})
        # an equivalence counts only for the very row it was computed for
        as_old = eq.get("as", {}) if eq.get("row") == sha else {}
        if any(sha == old_sha or as_old.get(old) == old_sha for old, old_sha in was.items()):
            del have[v]
        else:
            bad.append(
                f"/families/{fam}/{sec}/{key}/{v}: the row of a fast version cut after the "
                f"golden is not the family's row under any of the golden's versions "
                f"({sorted(was)}): its fast plan moved"
            )
    return {**c, sec: {**c[sec], key: have}}, bad


def fast_equivalents(golden: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """``{family: {new version: {"row": sha, "as": {golden version: sha}}}}``: for each row of
    a fast version the
    golden does not have that equals none of the family's golden rows, the family's fast plan
    sha under the new version recomputed as each golden version would have declared it
    (``reads.fast_plan_sha(family, declared=old)``), for the golden versions whose entry for the
    family is identical (``fast.compatible``). Reads the live code; ``verdict`` stays pure."""
    sys.path.insert(0, str(REPO / "src"))
    from wsbench import fast, reads, registry

    registry.load_all()
    sec, key = FAST_ROWS
    known = {v for g in golden["families"].values() for v in g.get(sec, {}).get(key, {})}
    by_frozen = {registry.frozen_name(f): f for f in registry.FAMILIES}
    out: dict[str, Any] = {}
    saved = fast.VERSION
    try:
        for fam, c in current["families"].items():
            was = golden["families"].get(fam, {}).get(sec, {}).get(key, {})
            for v, sha in c.get(sec, {}).get(key, {}).items():
                if v in known or sha in was.values() or fam not in by_frozen:
                    continue
                fast.VERSION = v
                for old in was:
                    if fast.compatible(old, by_frozen[fam], against=v):
                        as_old = reads.fast_plan_sha(by_frozen[fam], declared=old)
                        rec = out.setdefault(fam, {}).setdefault(v, {"row": sha, "as": {}})
                        rec["as"][old] = as_old
    finally:
        fast.VERSION = saved
    return out


def verdict(
    golden: Mapping[str, Any],
    current: Mapping[str, Any],
    ledger: Mapping[str, Any],
    *,
    script_sha256: str | None = None,
    fast_as: Mapping[str, Any] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """T1's rule: ``(declared, failures)``.

    Per family: rows equal to the golden's pass. Rows that differ, and a family the golden does
    not have, need a ledger entry whose triple (stamp, bank file, bank sha256) AND
    ``rows_sha256`` equal the current tree's, and the triple must differ from the golden's (no
    declaration without a bump). A declaration by stamp only (the bank file and sha equal the
    golden's) waives ``stamps`` and ``run`` alone: every other section must still equal the
    golden's. A declaration with a new bank compares nothing against the golden; the ledger
    hash covers the family. A family missing from the tree fails.

    Fast versions cut after the golden (``new_fast_rows``): a family's row for one is set
    aside, before the comparison and before the ledger hash, when it is the family's row under
    a golden version; so cutting a fast version needs no declaration from the families it
    leaves alone and does not stale an earlier declaration. Any other new-version row is a
    failure, except for a family declared with a NEW BANK (its fast plan may be new too): there
    the row stays in the entry the ledger hash covers.

    Outside ``families`` every section must equal the golden's, except ``shared.n_families``
    (the golden's count plus the families it does not have) and, when ``script_sha256`` is
    given, the manifest's own ``script_sha256``, which must then equal that value (T1 pins the
    sha of the script that made the golden and the sha of the script as it is now)."""
    gf, cf = golden["families"], current["families"]
    declared: dict[str, str] = {}
    failures: list[str] = []
    sec_f, key_f = FAST_ROWS
    golden_versions = {v for g in gf.values() for v in g.get(sec_f, {}).get(key_f, {})}
    for fam in sorted({*gf, *cf}):
        if fam not in cf:
            failures.append(f"/families/{fam}: in the golden, not in this tree")
            continue
        c, g = cf[fam], gf.get(fam)
        if g is not None and c == g:
            continue
        now, entry = triple(c), ledger.get(fam)
        if g is not None:
            new_bank = any(now[k] != triple(g)[k] for k in ("bank_file", "bank_sha256"))
            c, bad = new_fast_rows(fam, g, c, golden_versions, fast_as or {})
            if bad and not new_bank:
                failures += bad
                continue
            if c == g:
                continue
        if g is not None and now == triple(g):
            diffs = paths(g, c, f"/families/{fam}")
            failures.append(
                f"{fam}: instrument moved without a stamp or bank change ({len(diffs)} row(s): "
                + " | ".join(diffs[:5])
                + "). "
                + _fix(fam, "its stamp and bank still equal the golden's")
            )
            continue
        if not isinstance(entry, Mapping):
            what = "no ledger entry" + ("" if g is not None else "; a new family needs one too")
            failures.append(_fix(fam, what))
            continue
        if {k: entry.get(k) for k in now} != now:
            what = f"ledger entry is for {triple_text(entry)}, the tree has {triple_text(now)}"
            failures.append(_fix(fam, what))
            continue
        if entry.get("rows_sha256") != rows_sha256(c):
            what = "its rows changed again after it was declared, under the same stamp and bank"
            failures.append(_fix(fam, what))
            continue
        if g is not None and all(now[k] == triple(g)[k] for k in ("bank_file", "bank_sha256")):
            kept = sorted({*g, *c} - STAMP_SECTIONS)
            diffs = []
            for sec in kept:
                diffs += paths(g.get(sec), c.get(sec), f"/families/{fam}/{sec}")
            if diffs:
                failures.append(
                    f"{fam}: declared by a stamp change only (same bank as the golden), which "
                    f"covers `stamps` and `run`, but {len(diffs)} other row(s) moved: "
                    + " | ".join(diffs[:5])
                )
                continue
        how = "new family" if g is None else "; ".join(
            f"{k} {triple(g)[k]!r} -> {now[k]!r}" for k in now if now[k] != triple(g)[k]
        )  # fmt: skip
        declared[fam] = f"{how} (plan {entry.get('plan')}: {entry.get('note')})"
    n_new = sum(1 for f in cf if f not in gf)
    # Every section outside `families` is shared by several families (the digest prompts, the F4
    # record) or is the frozen script's own table, so no family's declaration covers it. A
    # DELIBERATE shared change (a new digest version, a new script constant) therefore needs a
    # conscious edit of this check plus its own note in the ledger / tests/golden/README.md.
    for sec in sorted({*golden, *current} - {"families"}):
        g, c = golden.get(sec), current.get(sec)
        if sec == "script_sha256" and script_sha256 is not None:
            if c != script_sha256:
                failures.append(
                    f"/script_sha256: {c!r} is not the pinned script's {script_sha256!r}"
                )
            continue
        if sec == "shared" and isinstance(g, dict) and isinstance(c, dict):
            g, c = dict(g), dict(c)
            if c.pop("n_families", None) != g.pop("n_families", None) + n_new:
                failures.append("/shared/n_families: not the golden's count plus the new families")
        failures += [f"global section moved: {d}" for d in paths(g, c, f"/{sec}")]
    return declared, failures


def triple_text(t: Mapping[str, Any]) -> str:
    return ", ".join(f"{k}={t.get(k)!r}" for k, _ in TRIPLE)


def declare(
    golden: Mapping[str, Any],
    current: Mapping[str, Any],
    ledger: Mapping[str, Any],
    family: str,
    plan: str,
    note: str,
    fast_as: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The ledger entry of ``family`` for the current tree, or :class:`Refused`."""
    if family not in current["families"]:
        raise Refused(f"{family}: not a family of this tree's manifest")
    c, g, prev = current["families"][family], golden["families"].get(family), ledger.get(family)
    if g is not None:  # the basis `verdict` compares and hashes (acceptable new fast rows aside)
        sec, key = FAST_ROWS
        known = {v for x in golden["families"].values() for v in x.get(sec, {}).get(key, {})}
        c, _ = new_fast_rows(family, g, c, known, fast_as or {})
    now, sha = triple(c), rows_sha256(c)
    if g is not None and c == g:
        raise Refused(f"{family}: its rows equal the golden's; nothing to declare")
    if g is not None and now == triple(g):
        raise Refused(
            f"{family}: rows differ from the golden but its stamp and bank are the golden's "
            f"({triple_text(now)}); bump the stamp or the bank version first"
        )
    if isinstance(prev, Mapping):
        if prev.get("rows_sha256") == sha:
            raise Refused(f"{family}: already declared in this state")
        if {k: prev.get(k) for k in now} == now:
            raise Refused(
                f"{family}: rows differ from its declared state but its stamp and bank are the "
                f"ledger entry's ({triple_text(now)}); bump the stamp or the bank version first"
            )
    return {**now, "rows_sha256": sha, "plan": plan, "note": note}


def build_current() -> dict[str, Any]:
    """The current tree's manifest, from the frozen script in its own process."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "manifest_now.json"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--out", str(out), "--any-tree"],
            capture_output=True, text=True, cwd=REPO,
        )  # fmt: skip
        if r.returncode != 0:
            raise SystemExit(r.stdout[-2000:] + r.stderr[-4000:])
        return json.loads(out.read_text(encoding="utf-8"))


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    path = LEDGER if path is None else path  # read at call time (tests patch LEDGER)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("family")
    ap.add_argument("--plan", required=True, help="the plan that declares the change (0099)")
    ap.add_argument("--note", required=True, help="what moved, in one line")
    ap.add_argument("--write", action="store_true", help=f"update {LEDGER.relative_to(REPO)}")
    args = ap.parse_args(argv)
    golden, current, ledger = json.loads(GOLDEN.read_text("utf-8")), build_current(), load_ledger()
    family = args.family
    if family not in current["families"]:
        sys.path.insert(0, str(REPO / "src"))
        from wsbench import registry

        family = registry.frozen_name(family)
    try:
        fast_as = fast_equivalents(golden, current)
        entry = declare(golden, current, ledger, family, args.plan, args.note, fast_as)
    except Refused as e:
        print(f"manifest_0101_declare: refused: {e}", file=sys.stderr)
        return 2
    print(json.dumps({family: entry}, indent=1, ensure_ascii=False))
    if args.write:
        ledger = dict(sorted({**ledger, family: entry}.items()))
        LEDGER.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {LEDGER.relative_to(REPO)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
