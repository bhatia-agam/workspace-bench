"""``wsbench check``: a registry of named gates and sanity checks. Each entry is a name, one
line on what it guards and the dotted path of a function returning ``(ok, why)``."""

import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wsbench import registry

Outcome = tuple[bool, str]
PLUGIN_ENV = "WSB_CHECKS"  # name=package.module:function[,name2=...]: checks added from outside


@dataclass(frozen=True)
class Check:
    """``target`` is ``package.module:function``, imported only when the check runs. The
    function takes its options as keyword arguments (strings) and returns ``(ok, why)``."""

    name: str
    guards: str
    target: str

    def function(self) -> Callable[..., Outcome]:
        module, _, attr = self.target.partition(":")
        return getattr(importlib.import_module(module), attr)

    def options(self) -> dict[str, bool]:
        """``{option: required}`` read off the function's keyword arguments."""
        params = inspect.signature(self.function()).parameters.values()
        named = [p for p in params if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)]
        return {p.name: p.default is inspect.Parameter.empty for p in named}

    def run(self, **options: str) -> Outcome:
        return self.function()(**options)


REGISTRY: dict[str, Check] = {}


def register(name: str, guards: str, target: str) -> Check:
    """Add a check. ``target`` is the dotted path ``package.module:function``."""
    if ":" not in target:
        raise ValueError(f"check {name!r}: target must be package.module:function, got {target!r}")
    REGISTRY[name] = Check(name, guards, target)
    return REGISTRY[name]


def load_plugins(env: dict[str, str] | None = None) -> None:
    """Register the checks named in ``$WSB_CHECKS`` (``name=package.module:function``, comma
    separated). The one-line description is the function's docstring."""
    for pair in (os.environ if env is None else env).get(PLUGIN_ENV, "").split(","):
        if not pair.strip():
            continue
        name, sep, target = pair.strip().partition("=")
        if not sep:
            raise ValueError(f"{PLUGIN_ENV}: expected name=package.module:function, got {pair!r}")
        check = register(name, "", target)
        doc = (inspect.getdoc(check.function()) or "external check").split("\n\n")[0]
        register(name, " ".join(doc.split()), target)


def all_checks() -> dict[str, Check]:
    """Built-in checks plus the ``$WSB_CHECKS`` plug-ins, in registration order."""
    load_plugins()
    return dict(REGISTRY)


def run(name: str, **options: str) -> Outcome:
    """Run one check by name. An unknown name, an option the check does not take or a missing
    required option is a ``ValueError``; an exception inside the check is a FAIL with its text."""
    checks = all_checks()
    if name not in checks:
        raise ValueError(f"unknown check {name!r}; known: {', '.join(checks)}")
    check = checks[name]
    takes = check.options()
    if extra := sorted(set(options) - set(takes)):
        raise ValueError(f"{name} does not take {extra}; it takes {sorted(takes) or 'no options'}")
    if missing := sorted(k for k, required in takes.items() if required and k not in options):
        raise ValueError(f"{name} needs {', '.join(f'{k}=' for k in missing)}")
    try:
        ok, why = check.run(**options)
    except SystemExit as e:  # the guards fail closed with SystemExit(reason)
        return False, str(e.code)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return bool(ok), " ".join(str(why).split())


def offline() -> list[str]:
    """The checks ``wsbench check all`` runs: those with no required option."""
    return [n for n, c in all_checks().items() if not any(c.options().values())]


def needing_options() -> dict[str, list[str]]:
    """The checks ``check all`` cannot run, each with the options it requires."""
    out = {}
    for name, check in all_checks().items():
        if required := [k for k, needed in check.options().items() if needed]:
            out[name] = required
    return out


# ------------------------------------------------------------------ helpers for check functions


def pytest_outcome(*paths: str) -> Outcome:
    """Run test files of this checkout as a check (the tests already hold the assertions)."""
    cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *paths]
    p = subprocess.run(cmd, cwd=registry.REPO_ROOT, capture_output=True, text=True)
    lines = [x for x in p.stdout.strip().splitlines() if x.strip()] or [p.stderr.strip()[-200:]]
    if p.returncode == 0:
        return True, f"{lines[-1].strip()} ({', '.join(paths)})"
    failed = next((x for x in lines if x.startswith(("FAILED", "ERROR"))), lines[-1])
    return False, failed.strip()


def _quiet(fn: Callable[[], Any]) -> tuple[Any, str]:
    """``(result, captured stdout + stderr)`` of a call that prints; a ``SystemExit`` is
    returned as its code."""
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        try:
            result = fn()
        except SystemExit as e:
            result = e.code if isinstance(e.code, int) else 2
            print(e.code)
    return result, out.getvalue()


# ------------------------------------------------------------------------------ built-in checks


def fast_subset() -> Outcome:
    from wsbench import fast

    names = fast.families()
    for name in names:
        fast.entry(name)  # SystemExit when the registered bank's sha256 moved
    return True, f"{len(names)} bank files match the sha256 the fast subset was frozen on"


def ati_subset() -> Outcome:
    from wsbench.baselines import text_inversion as ti

    registry.load_all()
    served, skipped = [], []
    for name in sorted(registry.FAMILIES):
        try:
            ti.subset_entry(name)
            served.append(name)
        except ti.NotInScope:
            skipped.append(name)
    return True, (
        f"{len(served)} families' entries match their judge instrument and bank; "
        f"{len(skipped)} not gated by design"
    )


def frozen_pins() -> Outcome:
    return pytest_outcome(
        "tests/test_fast_subset.py",
        "tests/test_fast_core_half.py",
        "tests/test_ati_freeze.py",
        "tests/test_bank_versions.py",
    )


def readme_prompts() -> Outcome:
    return pytest_outcome("tests/test_prompts_in_readme.py")


def readouts_contract(readouts: str, family: str = "") -> Outcome:
    from wsbench import readplan
    from wsbench.readouts import load_readouts

    path = Path(readouts)
    if not path.is_file():
        return False, f"no such file: {path}"
    cells, rep = load_readouts(path)
    bad = {k: v for k, v in rep.skipped.items() if v}
    what = f"{len(cells)} cells of {len({c.id for c in cells})} items, kind {rep.kind}"
    if bad:
        return False, f"{what}; rows not read: {json.dumps(bad)}"
    if not cells:
        return False, "no readout rows"
    if family:
        registry.load_all()
        fam = registry.canonical(family)
        known = {s.id for s in readplan.plan(fam)}
        strangers = sorted({c.id for c in cells} - known)
        if strangers:
            return False, f"{len(strangers)} id(s) not in the {fam} read plan, e.g. {strangers[0]}"
        what += f", every id in the {fam} read plan"
    return True, what


def judge_dry_run(family: str = "") -> Outcome:
    from wsbench import cli

    registry.load_all()
    examples = registry.REPO_ROOT / "examples" / "readouts"
    names = [registry.canonical(family)] if family else sorted(registry.FAMILIES)
    ran = 0
    with tempfile.TemporaryDirectory(prefix="wsb-check-") as tmp:
        for name in names:
            file = examples / f"{name}.jsonl"
            if not file.is_file():
                if family:
                    return False, f"no example readouts {file}"
                continue
            # allow_missing: the toy files hold a few cells, not the whole read plan
            argv = ["judge", f"family={name}", f"readouts={file}", f"out={tmp}/{name}"]
            argv += ["dry_run=True", "allow_missing=True"]
            code, text = _quiet(lambda argv=argv: cli.main(argv))
            if code:
                return False, f"{name}: exit {code}: {text.strip().splitlines()[-1][:160]}"
            ran += 1
    return True, f"{ran} families build their first judge prompt from examples/readouts, no call"


def capable_gate(model: str, family: str = "", limit: str = "0", dry_run: str = "False") -> Outcome:
    from wsbench import cli

    argv = ["capable", f"model={model}", f"limit={limit}", f"dry_run={dry_run}"]
    argv += [f"families={family}"] if family else []
    code, text = _quiet(lambda: cli.main(argv))
    lines = [x.strip() for x in text.strip().splitlines() if x.strip()] or [""]
    if code:
        return False, f"exit {code}: {lines[-1][:200]}"
    rated = [x for x in lines if " gate=" in x]
    return True, "; ".join(x.split(" accuracy=")[0] for x in rated) or lines[-1][:200]


def adapt_gate(model: str) -> Outcome:
    root = registry.REPO_ROOT / "adapted" / model
    report = root / "report.json"
    if not report.is_file():
        return False, f"no adapted set at {root} (report.json missing)"
    families = json.loads(report.read_text(encoding="utf-8")).get("families", {})
    n_items = n_pass = n_bare = 0
    for name in sorted(families):
        path = next(
            (p for k in registry.lookup_names(name) if (p := root / f"{k}.json").is_file()), None
        )
        if path is None:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw.get("items", []) if isinstance(raw, dict) else raw
        for it in items:
            gate = (it.get("adapt") or {}).get("gate") if isinstance(it, dict) else None
            n_items += 1
            if not isinstance(gate, dict) or "pass" not in gate:
                n_bare += 1
            elif gate["pass"]:
                n_pass += 1
            else:
                return False, f"{name}: item {it.get('id', it.get('name'))} ships a failed gate"
    what = f"{model}: {n_pass} of {n_items} shipped items carry a passing gate record"
    return True, what + (f", {n_bare} carry no per-item record" if n_bare else "")


_HERE = "wsbench.checks"
register(
    "fast_subset",
    "The registered banks are byte-identical to the ones the fast subset was frozen on.",
    f"{_HERE}:fast_subset",
)
register(
    "ati_subset",
    "Every anti-text-inversion entry still matches its family's judge instrument and bank.",
    f"{_HERE}:ati_subset",
)
register(
    "frozen_pins",
    "The pinned tests of the fast subset, the ATI freeze and the bank versions pass.",
    f"{_HERE}:frozen_pins",
)
register(
    "readme_prompts",
    "Every judge prompt in the code is verbatim in its family README.",
    f"{_HERE}:readme_prompts",
)
register(
    "readouts_contract",
    "A readouts file parses under the contract (readouts=FILE; family=F also checks its ids).",
    f"{_HERE}:readouts_contract",
)
register(
    "judge_dry_run",
    "Each family builds its first judge prompt from the example readouts, with no API call.",
    f"{_HERE}:judge_dry_run",
)
register(
    "capable_gate",
    "A subject model answers the banks' own gate questions (model=M; live calls unless "
    "dry_run=True).",
    f"{_HERE}:capable_gate",
)
register(
    "adapt_gate",
    "An adapted set (model=<adapted/ folder>) ships only items with a passing gate record.",
    f"{_HERE}:adapt_gate",
)
