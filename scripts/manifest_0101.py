"""Plan 0101 §11.1: the manifest of every instrument output a family key or path could move
(hashes, seeds, option orders, prompts, call keys, fingerprints), offline. Family keys are written
through ``registry.frozen_name``, so the same file gives the same bytes before and after the rename.

    uv run python scripts/manifest_0101.py --out tests/golden/manifest_0101_pre.json  # on main
    uv run python scripts/manifest_0101.py --check tests/golden/manifest_0101_pre.json
"""

import argparse
import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
import io
import json
import os
import random as _random
import re
import shutil
import subprocess
import sys
import tempfile
import types
from collections.abc import Callable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# The environment is normalised BEFORE wsbench is imported: no bank root, bank pin, cache dir,
# route or key of the calling shell reaches the manifest (WSB_NO_NYT / WSB_NO_NOCOT included: the
# two fetched sources are stubbed below, as tests/conftest.py stubs them).
for _k in list(os.environ):
    if _k.startswith(("WSB_", "WSBENCH_")):
        os.environ.pop(_k)

from wsbench import cache as cache_mod  # noqa: E402
from wsbench import (  # noqa: E402
    digest,
    fast,
    gate_sampling,
    llm,
    mcjudge,
    nocot,
    nyt,
    reads,
    registry,
    runner,
    split,
    tiers,
)
from wsbench.judge_config import JudgeConfig, resolve  # noqa: E402

BASE_SHA = "030dd09b195b6a9db1ccd941f615f252f4091f80"  # origin/main the pre-manifest is made on
REPO = registry.REPO_ROOT
N_ITEMS = 5  # the recorded run's fixed items per family
N_PROBE = 3
PROBE_MODEL = "manifest-0101-probe"  # no adapted set of this name exists: the stores read empty
LENS_SUBJECT = "qwen3.5-4b"
LENS_ARM = "manifest-0101-arm"
MODES = ("native", "summary")
MAX_FILES_LISTED = 200  # a family directory with more files records only its tree sha
# (frozen family key, mode) pairs that record zero LLM calls by design; any other zero fails
ZERO_CALL_EXCEPTIONS: dict[str, dict[str, str]] = {
    "model_specific_directed_modulation": {
        "native": "regex judge: no LLM call (its summary mode records digest calls)"
    },
    "multilingual_mt": {"native": "scorer of record is the regex contract: no LLM call"},
    "multilingual_typo": {"native": "scorer of record is the regex contract: no LLM call"},
    "typo_mt": {"native": "scorer of record is the regex contract: no LLM call"},
}
# Shared modules with family-keyed upper-case tables, a table's defining module before its
# importers: a family's MEMBERSHIP in each is recorded (a re-keyed table must hold the same
# families), and its VALUE for the instrument tables of TABLE_VALUES (stamps, call and option-seed
# versions, task notes, rules, tags, pools, digest defaults). Other values are prose or code.
TABLE_MODULES = (
    "wsbench.basic.prompts",
    "wsbench.basic.mcjudge_basic",
    "wsbench.basic.mcjudge_bank",
    "wsbench.basic.family",
    "wsbench.multitoken.prompts",
    "wsbench.multitoken.options",
    "wsbench.multitoken.regex",
    "wsbench.multitoken.mcrx",
    "wsbench.multitoken.family",
    "wsbench.readplan",
    "wsbench.digest",
    "wsbench.tiers",
    "wsbench.baselines.text_inversion",
    "wsbench.baselines.lucky_guessing",
    "wsbench.baselines.prompt_only",
    "wsbench.capable.questions",
    "wsbench.adapt.onecue",
    "wsbench.adapt.families",
)
TABLE_VALUES = {
    "wsbench.basic.prompts": ("DIGEST_TASK_NOTES", "FAMILY_PROMPT_VERSIONS", "FAMILY_RULES"),
    "wsbench.basic.mcjudge_basic": ("CANNOT_OF", "OPTIONS_VERSIONS"),
    "wsbench.basic.mcjudge_bank": ("CALL_VERSIONS",),
    "wsbench.multitoken.prompts": ("DIGEST_TASK_NOTES", "ML_BANK_TAGS"),
    "wsbench.multitoken.options": ("R4_LANG_POOLS",),
    "wsbench.multitoken.family": ("CALL_VERSIONS", "MC_FAMILIES", "MC_PROFILES"),
    "wsbench.digest": ("FAMILY_DEFAULTS",),
    "wsbench.baselines.text_inversion": ("ATI_EXCLUDE", "STRICTER_PASS_FIELD"),
    "wsbench.baselines.lucky_guessing": (
        "DESCRIPTIONS",
        "FAMILY_RULES",
        "GUESS_QUESTION",
        "STANDARD_POINTS_BY_FAMILY",
        "SYSTEM_QUESTION_BY_FAMILY",
    ),
}
IMPORTS: list[dict[str, str]] = []  # every private import, recorded in the output


def fz(key: str) -> str:
    """The pre-0101 key of a current family key (identity while ``registry.frozen_name`` does
    not exist or its table is empty)."""
    f: Callable[[str], str] = getattr(registry, "frozen_name", lambda k: k)
    return f(key)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def need(module: str, names: tuple[str, ...], role: str) -> Any:
    """Import a ``wsbench`` module and require ``names`` on it: a missing one is an error, never
    a silent omission."""
    mod = importlib.import_module(module)
    missing = [n for n in names if not hasattr(mod, n)]
    if missing:
        raise SystemExit(f"manifest_0101: {module} lacks {missing} ({role})")
    IMPORTS.append({"module": module, "names": ", ".join(names), "role": role})
    return mod


def need_script(stem: str, names: tuple[str, ...], role: str) -> Any:
    """Load ``scripts/<stem>.py`` by file path, with ``modal`` masked for the import: a script
    that imports it at top level (``lens_readouts_modal``) guards the import and builds its
    Modal app only when the package is there, so masking gives the same module on a box with
    and without modal and never touches the Modal client."""
    path = REPO / "scripts" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"manifest_0101_{stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"manifest_0101: cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    had, saved = "modal" in sys.modules, sys.modules.get("modal")
    sys.modules["modal"] = None  # type: ignore[assignment]  # `import modal` -> ImportError
    try:
        spec.loader.exec_module(mod)
    finally:
        if had:
            sys.modules["modal"] = saved  # type: ignore[assignment]
        else:
            sys.modules.pop("modal", None)
    missing = [n for n in names if not hasattr(mod, n)]
    if missing:
        raise SystemExit(f"manifest_0101: scripts/{stem}.py lacks {missing} ({role})")
    IMPORTS.append({"module": f"scripts/{stem}.py", "names": ", ".join(names), "role": role})
    return mod


# ---------------------------------------------------------------- canonical values


def canonical(v: Any, f4: tuple[str, str] | None = None) -> Any:
    """A JSON value that is the same in every process and on every checkout: sets sorted,
    dataclasses and patterns spelled out, callables anonymous, paths by file name. No key or
    value is translated (an option or a word may be spelled like a family key) except the F4
    record: ``f4`` = (the record, its key-mapped form)."""
    if isinstance(v, str):
        return f4[1] if f4 is not None and v == f4[0] else v
    if v is None or isinstance(v, bool | int | float):
        return v
    if isinstance(v, Mapping):
        out = {str(k): canonical(x, f4) for k, x in v.items()}
        return dict(sorted(out.items()))
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        fields = {f.name: canonical(getattr(v, f.name), f4) for f in dataclasses.fields(v)}
        return {"__dataclass__": type(v).__name__, **fields}
    if isinstance(v, list | tuple):
        return [canonical(x, f4) for x in v]
    if isinstance(v, set | frozenset):
        return sorted((canonical(x, f4) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(v, re.Pattern):
        return {"__re__": v.pattern, "flags": v.flags}
    if isinstance(v, Path):
        return {"__path__": "<repo>" if v == REPO else v.name}
    if callable(v):
        return "<callable>"
    return {"__type__": type(v).__name__}


def blob_sha(v: Any) -> str:
    return sha(json.dumps(v, sort_keys=True, ensure_ascii=False))


def f4_record() -> tuple[str, str]:
    """(F4's printed record ``basic.prompts.DIGEST_TASK_NOTES_TEXT``, the same record with each
    line's family key mapped back through :func:`fz`)."""
    bp = need("wsbench.basic.prompts", ("DIGEST_TASK_NOTES", "DIGEST_TASK_NOTES_TEXT"), "F4")
    mapped = "\n".join(f"{fz(f)}: {n}" for f, n in bp.DIGEST_TASK_NOTES.items())
    return bp.DIGEST_TASK_NOTES_TEXT, mapped


# ---------------------------------------------------------------- offline stubs


def install_offline_stubs() -> None:
    """The two fetched sources, stubbed exactly as tests/conftest.py stubs them
    (``_offline_nyt`` / ``_offline_nocot``): synthetic NYT words and group names for every puzzle
    the committed bank references, synthetic question text for every nocot id. No fetch."""
    bank = json.loads(registry.frozen_bank_path("nyt_connections").read_text(encoding="utf-8"))
    stub = {
        int(n): {
            "id": int(n),
            "date": "2000-01-01",
            "groups": [
                {
                    "name": f"SYNTHETIC GROUP {int(n)}-{k}",
                    "members": [f"WORD{int(n)}X{4 * k + j}" for j in range(4)],
                    "level": k,
                }
                for k in range(4)
            ],
        }
        for n in nyt.referenced_ids(bank["items"])
    }
    nyt.puzzles = lambda: stub  # type: ignore[assignment]
    questions = {it["id"]: f"synthetic question {it['id']}" for it in nocot.load_obscure()[1]}
    nocot.questions = lambda: questions  # type: ignore[assignment]


# ---------------------------------------------------------------- the recording fakes

REC: dict[str, list[str]] = {"judge": [], "llm": [], "digest_fp": [], "lookups": []}


def _reset() -> None:
    for v in REC.values():
        v.clear()


def canned(schema: Mapping[str, Any]) -> Any:
    """A deterministic answer built from the JSON schema alone (first enum value, ``A`` for a
    free ``choice``, one array element, empty strings)."""

    def gen(s: Mapping[str, Any], name: str = "") -> Any:
        if "enum" in s:
            return s["enum"][0]
        if "const" in s:
            return s["const"]
        if "anyOf" in s:
            return gen(s["anyOf"][0], name)
        t = s.get("type")
        t = t[0] if isinstance(t, list) else t
        if t == "object":
            return {k: gen(x, k) for k, x in (s.get("properties") or {}).items()}
        if t == "array":
            item = s.get("items") or {"type": "string"}
            return [gen(item, name) for _ in range(max(1, int(s.get("minItems", 1))))]
        if t == "string":
            return {"choice": "A", "answer": "canned answer"}.get(name, "")
        if t == "integer":
            return int(s.get("minimum", 1))
        if t == "number":
            return float(s.get("minimum", 0))
        if t == "boolean":
            return False
        return None

    return gen(schema.get("schema", schema))


def _first_lines_digest(user: str, k: int = 3) -> dict:
    """tests/summary_fakes.first_lines_digest (the first ``k`` bundle samples, quoted whole),
    each keyed by the first number it holds, so a numbers digest has claims to judge."""
    lines = [ln[2:] for ln in user.splitlines() if ln.startswith("- ")]
    items = []
    for i, ln in enumerate(lines[:k]):
        num = re.search(r"\d+(?:\.\d+)?", ln)
        key = num.group(0) if num else ""
        items.append({"statement": f"STATEMENT-{i}", "key": key, "where": "", "evidence": ln})
    return {"items": items, "rare": []}


def _layered_digest(user: str, k: int = 50) -> dict:
    """tests/summary_fakes.layered_digest: every distinct sample shown, quoted whole."""
    got = re.findall(r"^  sample (\[L\d+ pos -?\d+\]): (.*)$", user, flags=re.M)
    seen: dict[str, str] = {}
    for where, text in got:
        seen.setdefault(text, where)
    return {
        "items": [
            {"statement": f"LAYERED-{i}", "key": "", "where": w, "evidence": t, "count": 10**6}
            for i, (t, w) in enumerate(list(seen.items())[:k])
        ],
        "rare": [],
    }


def _fake_stream_json(prompts: Any, *, schema: Any, model: str, on_result: Any, **_kw: Any) -> Any:
    name = str(schema.get("name", ""))
    for i, (system, user) in enumerate(prompts):
        REC["llm"].append("\t".join((name, model, sha(system), sha(user))))
        if name == "digest" and user.startswith("LAYER DIGESTS:"):
            r = _layered_digest(user)
        elif name == "digest":
            r = _first_lines_digest(user)
        else:
            r = canned(schema)
        on_result(i, r)
    return llm.Spend()


def _fake_stream_text(prompts: Any, *, model: str, on_result: Any, **_kw: Any) -> Any:
    for i, prompt in enumerate(prompts):
        REC["llm"].append("\t".join(("text", model, "-", sha(prompt))))
        on_result(i, "")
    return llm.Spend()


def install_recorders() -> None:
    """Patch the LLM primitives (every judge, digest and free-text call ends in
    ``llm.stream_json`` / ``llm.stream_text``), ``mcjudge.run_calls`` wherever a module bound it,
    the digest fingerprint and the cache lookup. Nothing reaches a client."""
    need("wsbench.llm", ("stream_json", "stream_text", "preflight", "count_tokens"), "patched")
    need("wsbench.mcjudge", ("run_calls", "Call"), "patched: records every judge call")
    need("wsbench.digest", ("_digest_fp",), "the digest fingerprint (digest.py:1825)")
    need("wsbench.cache", ("Cache", "fingerprint"), "patched: records every (key, fp) lookup")
    llm.stream_json = _fake_stream_json  # type: ignore[assignment]
    llm.stream_text = _fake_stream_text  # type: ignore[assignment]
    llm.preflight = lambda *a, **k: None  # type: ignore[assignment]
    llm.require_credentials = lambda *a, **k: None  # type: ignore[assignment]
    llm.count_tokens = lambda model, prompts, concurrency=8: [  # type: ignore[assignment]
        (len(s) + len(u)) // 3 for s, u in prompts
    ]
    real_run_calls = mcjudge.run_calls

    def run_calls(calls: Any, *, schema: Any, judge: Any, prompt_version: str, **kw: Any) -> Any:
        temperature = kw.get("temperature")
        for c in calls:
            fp = cache_mod.fingerprint(
                prompt_version, judge.model, judge.reasoning, temperature, c.system, c.user
            )
            row = (c.key, fp, sha(c.system), sha(c.user), prompt_version, schema.get("name", ""))
            REC["judge"].append("\t".join(map(str, row)))
        return real_run_calls(
            calls, schema=schema, judge=judge, prompt_version=prompt_version, **kw
        )

    for name, mod in list(sys.modules.items()):
        if name.startswith("wsbench") and mod is not None:
            for attr, val in list(vars(mod).items()):
                if val is real_run_calls:
                    setattr(mod, attr, run_calls)
    real_fp = digest._digest_fp

    def digest_fp(s: Any, task_note: str, text: str, salt: str = "") -> str:
        fp = real_fp(s, task_note, text, salt)
        REC["digest_fp"].append("\t".join((fp, task_note, sha(text), salt)))
        return fp

    digest._digest_fp = digest_fp  # type: ignore[assignment]
    real_get = cache_mod.Cache.get

    def get(self: Any, key: str, fp: str, **kw: Any) -> Any:
        REC["lookups"].append(f"{key}\t{fp}")
        return real_get(self, key, fp, **kw)

    cache_mod.Cache.get = get  # type: ignore[method-assign]


@contextlib.contextmanager
def quiet() -> Any:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


# ---------------------------------------------------------------- per-family entries


def family_package(spec: Any) -> Any:
    """The family's package, wherever it sits under ``wsbench.evals`` (found by its ``SPEC``)."""
    hits = [
        m
        for n, m in sys.modules.items()
        if n.startswith("wsbench.evals.") and m is not None and getattr(m, "SPEC", None) is spec
    ]
    if len(hits) != 1:
        raise SystemExit(f"manifest_0101: {spec.name}: {len(hits)} packages export its SPEC")
    return hits[0]


def bank_items(name: str) -> list[dict]:
    raw = json.loads(registry.frozen_bank_path(name).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [i for i in raw if isinstance(i, dict)]
    for key in ("items", "prompts"):
        if isinstance(raw.get(key), list):
            return [i for i in raw[key] if isinstance(i, dict)]
    return []


def bank_ids(name: str) -> list[str]:
    """Every item id of the registered bank, sorted (readout ids: a ``name`` goes through
    ``banks.label_of``)."""
    from wsbench.banks import label_of

    out = set()
    for it in bank_items(name):
        if it.get("id") is not None:
            out.add(str(it["id"]))
        elif it.get("name") is not None:
            out.add(label_of(str(it["name"])))
    return sorted(out)


def file_entry(name: str) -> dict[str, Any]:
    """Bank file sha and item count; sha256 of every other file of the family directory
    (located through the registry). ``README.md`` is left out: the migration rewrites its keys,
    paths and title, and its prompt blocks are pinned by the prompts row."""
    bank = registry.frozen_bank_path(name)
    root = bank.parent
    files = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and "__pycache__" not in p.parts and rel != "README.md" and p != bank:
            files[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    out: dict[str, Any] = {
        "bank_file": bank.name,
        "bank_sha256": hashlib.sha256(bank.read_bytes()).hexdigest(),
        "n_items": len(bank_items(name)),
        "n_other_files": len(files),
        "other_files_sha256": blob_sha(files),
    }
    if len(files) <= MAX_FILES_LISTED:
        out["other_files"] = files
    return out


def plan_entry(name: str) -> dict[str, Any]:
    ti = need("wsbench.baselines.text_inversion", ("bank_fingerprint", "qwen_seed"), "ATI")
    out: dict[str, Any] = {"plan_sha": reads.plan_sha(name), "fast_plan_sha": {}}
    saved = fast.VERSION
    try:
        for version in sorted(fast.VERSIONS):
            if name in fast.subset(version):
                fast.VERSION = version  # the plan of that subset, as `--fast[-safety]` selects it
                try:
                    out["fast_plan_sha"][version] = reads.fast_plan_sha(name, declared=version)
                except SystemExit:
                    # a version frozen before the family's bank changed has no plan for it any
                    # more (`fast.entry` fails closed): recorded, never a crash of the manifest.
                    # A constant: the error's wording must not reach a hashed row
                    out["fast_plan_sha"][version] = "unavailable"
    finally:
        fast.VERSION = saved
    out["ati_bank_fingerprint"] = ti.bank_fingerprint(name)
    return out


def stamp_entry(name: str, spec: Any, f4: tuple[str, str]) -> dict[str, Any]:
    """The result stamp, every ``*VERSION*`` / ``*STAMP*`` string of the family's own modules,
    and the sha over every upper-case constant of its ``prompts`` module."""
    pkg = family_package(spec)
    prompts = importlib.import_module(f"{pkg.__name__}.prompts")
    versions: dict[str, str] = {}
    for sub in ("", ".prompts", ".judge"):
        try:
            mod = importlib.import_module(pkg.__name__ + sub)
        except ImportError:
            continue
        for k, v in vars(mod).items():
            if k.isupper() and isinstance(v, str) and ("VERSION" in k or "STAMP" in k):
                versions[f"{sub.lstrip('.') or '__init__'}.{k}"] = v
    consts = {k: canonical(getattr(prompts, k), f4) for k in dir(prompts) if k.isupper()}
    return {
        "prompt_version": spec.judge.prompt_version,
        "judge_model": spec.judge.model,
        "judge_reasoning": canonical(spec.judge.reasoning),
        "aux_models": canonical(dict(spec.judge.aux_models)),
        "versions": dict(sorted(versions.items())),
        "prompts_constants": sorted(consts),
        "prompts_sha256": blob_sha(consts),
        "prompts_keys": sorted(getattr(prompts, "PROMPTS", {})),
    }


def table_entry(name: str, f4: tuple[str, str]) -> dict[str, Any]:
    """The family's place in every family-keyed upper-case table of :data:`TABLE_MODULES`:
    ``True`` for membership, and for a :data:`TABLE_VALUES` table its own value (a short scalar
    as is, anything else by sha). A table is recorded once, under the first module that has it."""
    out: dict[str, Any] = {}
    seen: set[int] = set()
    for module in TABLE_MODULES:
        mod = need(module, TABLE_VALUES.get(module, ()), "family-keyed tables")
        for k, v in sorted(vars(mod).items()):
            if not k.isupper() or k.startswith("_") or id(v) in seen:
                continue
            label = f"{module.removeprefix('wsbench.')}.{k}"
            if isinstance(v, Mapping):
                seen.add(id(v))
                if name not in v:
                    continue
                out[label] = True
                if k in TABLE_VALUES.get(module, ()):
                    c = canonical(v[name], f4)
                    short = isinstance(c, bool | int | float | str) and len(str(c)) < 200
                    out[label] = c if short else {"sha256": blob_sha(c)}
            elif isinstance(v, list | tuple | set | frozenset):
                seen.add(id(v))
                if any(isinstance(x, str) and x == name for x in v):
                    out[label] = True
    return dict(sorted(out.items()))


def list_entry(name: str, spec: Any) -> dict[str, Any]:
    """The family's ``wsbench list`` row minus its key and title."""
    cli = need("wsbench.cli", ("_n_items",), "the n-items column of `wsbench list`")
    return {
        "category": spec.group,
        "tier": tiers.tier_of(name),
        "n_items": cli._n_items(spec),
        "metric": spec.metric,
        "higher_is_better": spec.higher_is_better,
        "judge": spec.scorer or spec.judge.model,
        "calls_per_arm": spec.calls_per_arm,
        "sources": spec.sources,
        "superseded_by": fz(spec.superseded_by) if spec.superseded_by else "",
        "retired": name in registry.RETIRED_FAMILIES,
        "not_in_macro": spec.not_in_macro,
    }


def example_ids(name: str) -> tuple[Path, list[str]]:
    """``examples/readouts/<family>.jsonl`` and the first :data:`N_ITEMS` ids of the bank,
    sorted, that it holds."""
    path = REPO / "examples" / "readouts" / f"{name}.jsonl"
    have = set()
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            with contextlib.suppress(ValueError, KeyError, TypeError):
                have.add(str(json.loads(line)["id"]))
    bank = set(bank_ids(name))
    return path, sorted(have & bank if bank else have)[:N_ITEMS]


def run_entry(name: str, spec: Any, work: Path) -> dict[str, Any]:
    """An offline run of the family over its example readouts in native and summary mode,
    through ``runner.judge_family`` (the CLI's path), every call recorded."""
    path, ids = example_ids(name)
    out: dict[str, Any] = {"items": ids}
    for mode in MODES:
        _reset()
        dest = work / f"run-{name}-{mode}"
        args = SimpleNamespace(
            items=list(ids),
            layers=None,
            limit=0,
            allow_missing=True,
            concurrency=4,
            rpm=1e9,
            dry_run=False,
            fast=False,
            anti_text_inversion=False,
        )
        entry: dict[str, Any] = {}
        try:
            with quiet():
                opts = runner.parse_opts(["aggregate=native"] if mode == "native" else [])
                judge = resolve(spec.judge, env={})
                res = runner.judge_family(spec, args, path, dest, judge=judge, opts=opts)
            entry["result_prompt_version"] = res.config.get("prompt_version")
            entry["aggregate"] = res.config.get("aggregate") or "native"
            entry["value"] = res.value
            entry["n_items"] = res.n_items
        except SystemExit:
            entry["failed"] = "SystemExit"
        except llm.JudgeConfigError:
            entry["failed"] = "JudgeConfigError"
        entry["n_calls"] = len(REC["llm"])
        entry["n_judge_calls"] = len(REC["judge"])
        # judge calls: key, fingerprint, sha256(system), sha256(user), prompt_version, schema
        entry["judge_calls"] = sorted(REC["judge"])
        # every prompt sent: schema name ("digest", "text", ...), model, sha256(system | user)
        entry["llm_calls"] = sorted(REC["llm"])
        # digest fingerprints: fingerprint, the task note the digest is told, sha256(text), salt
        entry["digest_fingerprints"] = sorted(set(REC["digest_fp"]))
        # every cache lookup (judge, digest, token-count and stage keys): key, fingerprint
        entry["cache_lookups"] = sorted(set(REC["lookups"]))
        out[mode] = entry
        shutil.rmtree(dest, ignore_errors=True)
    return out


def options_entry(name: str, spec: Any) -> dict[str, Any]:
    """The shown option lists of the first :data:`N_ITEMS` items of the MC families that build
    them from the bank (the recorded prompts carry every family's lists as rendered)."""
    from wsbench.banks import load_bank

    bf = need("wsbench.basic.family", ("MC_FAMILIES", "MC_BANK_FAMILIES"), "MC dispatch")
    out: dict[str, Any] = {}
    if name in bf.MC_BANK_FAMILIES:
        mb = need("wsbench.basic.mcjudge_bank", ("options_of",), "F1: the option order")
        _h, items = load_bank(registry.frozen_bank_path(name))
        for it in sorted(items, key=lambda i: str(i["id"]))[:N_ITEMS]:
            shown, gold = mb.options_of(name, it)
            out[str(it["id"])] = {"shown": shown, "gold": gold}
    elif name in bf.MC_FAMILIES:
        ms = need(
            "wsbench.basic.mcjudge_basic",
            ("options_for", "options_version", "CANNOT_OF"),
            "basic_readout option order",
        )
        _h, items = load_bank(registry.frozen_bank_path(name))
        pv, cannot = ms.options_version(name), ms.CANNOT_OF[name]
        for it in sorted(items, key=lambda i: str(i["id"]))[:N_ITEMS]:
            out[str(it["id"])] = canonical(ms.options_for(it, pv=pv, cannot=cannot))
    elif spec.run.__module__ == "wsbench.multitoken.family":
        mo = need("wsbench.multitoken.options", ("option_sets",), "multi-token option order")
        _h, items = load_bank(registry.frozen_bank_path(name))
        sets = mo.option_sets(items)
        for iid in sorted(sets)[:N_ITEMS]:
            out[iid] = canonical(sets[iid])
    return out


def seed_entry(name: str) -> dict[str, Any]:
    """The ``hash_name`` sites and F2: the dev split of every item id, and for
    :data:`N_PROBE` probe ids the lucky-guessing seeds and call keys, ``gate_sampling.seed`` and
    ``qwen_seed``; the id prefix both adapt id builders derive from the key's spelling."""
    lg = need("wsbench.baselines.lucky_guessing", ("_rng",), "the lucky-guessing seed")
    ti = sys.modules["wsbench.baselines.text_inversion"]
    ids = bank_ids(name)
    dev = [iid for iid in ids if split.is_dev(name, iid)]
    probes = {}
    for iid in ids[:N_PROBE]:
        probes[iid] = {
            "lucky_examples_rng": lg._rng(0, name, iid, "examples").random(),
            "lucky_draw_rng": lg._rng(0, name, iid, 0, 0).random(),
            # the call key of lucky_guessing.py:1474, built here the way that line builds it
            "lucky_call_key": f"{registry.hash_name(name)}|blind|{iid}|d0",
            "gate_sampling_seed": gate_sampling.seed(name, iid, 0),
            "qwen_seed": ti.qwen_seed(name, iid),
        }
    return {
        "is_dev_n": len(dev),
        "is_dev_sha256": blob_sha(dev),
        "is_dev_first": dev[:N_PROBE],
        "probes": probes,
        # adapt/generate.py:306 and adapt/author.py:1635: `family.split('_')[0]`
        "id_prefix": name.split("_")[0],
    }


class _RandomProxy(types.ModuleType):
    """``random`` for one module: ``Random(seed)`` is logged, everything else passes through."""

    def __init__(self, log: list[Any]):
        super().__init__("random")
        self._log = log

    def __getattr__(self, attr: str) -> Any:
        return getattr(_random, attr)

    def Random(self, seed: Any = None) -> Any:  # noqa: N802
        text = seed if isinstance(seed, str | int) else f"<{type(seed).__name__}>"
        probe = _random.Random(seed)
        first = [probe.random() for _ in range(5)] if seed is not None else None
        self._log.append({"seed": text, "first": first})
        return _random.Random(seed)


def capable_entry(name: str, work: Path) -> Any:
    """F5: the reply and grade cache keys of the first :data:`N_PROBE` questions, from
    ``capable.run.run_family`` itself (one greedy and one sampled draw, canned answers)."""
    cq = need("wsbench.capable.questions", ("BUILDERS",), "which families have a question")
    cr = need("wsbench.capable.run", ("run_family",), "F5: the reply / grade cache keys")
    if name not in cq.BUILDERS:
        return None
    _reset()
    dest = work / f"capable-{name}"
    with quiet():
        cr.run_family(
            name,
            model="claude-opus-5-5",
            judge=resolve(JudgeConfig(), env={}),
            out=dest,
            draws=1,
            limit=N_PROBE,
        )
    shutil.rmtree(dest, ignore_errors=True)
    return sorted(REC["judge"])


def generate_entry(name: str) -> Any:
    """F6 (``adapt/generate.py:295``): the seeded rng of two (tier, seed) pairs, with the ids
    and the sha of the three items each generates."""
    gen = need("wsbench.adapt.generate", ("GENERATORS", "generate"), "F6: the generator rng")
    if name not in gen.GENERATORS:
        return None
    names = [t.name for t in gen.GENERATORS[name].tiers]
    out = []
    for tier, seed in ((names[0], 0), (names[-1], 1)):
        log: list[Any] = []
        real = gen.random
        gen.random = _RandomProxy(log)
        try:
            with quiet():
                items = gen.generate(name, tier, 3, seed, set())
            made: Any = {"n": len(items), "items_sha256": blob_sha(canonical(items))}
        except (SystemExit, Exception) as e:
            made = {"failed": type(e).__name__}
        finally:
            gen.random = real
        out.append({"tier": tier, "seed": seed, "rng": log, **made})
    return out


def author_entry(name: str) -> Any:
    """F12 and F6 (``adapt/author.py:1506`` / ``:1463``): the authoring prompt's sha per tier
    and the few-shot rng, for a subject with no stored set."""
    au = need("wsbench.adapt.author", ("BRIEFS", "render_brief", "_few_shots"), "F6 / F12")
    if name not in au.BRIEFS:
        return None
    out = {}
    for tier in au.BRIEFS[name].tiers:
        log: list[Any] = []
        real = au.random
        au.random = _RandomProxy(log)
        try:
            with quiet():
                prompt = au.render_brief(PROBE_MODEL, name, tier, 4)
            out[tier] = {"prompt_sha256": sha(prompt), "rng": log}
        except (SystemExit, Exception) as e:
            out[tier] = {"failed": type(e).__name__, "rng": log}
        finally:
            au.random = real
    return out


def language_entry(name: str) -> Any:
    """F11: the language-distractor lists of three probe golds, and the balanced lists over the
    registered bank's golds."""
    mo = need(
        "wsbench.multitoken.options",
        ("R4_LANG_POOLS", "r4_language_distractors", "r4b_balanced_language_distractors"),
        "F11: the language-distractor seeds",
    )
    if name not in mo.R4_LANG_POOLS:
        return None
    pool = sorted(mo.R4_LANG_POOLS[name])
    out: dict[str, Any] = {
        "pool_sha256": blob_sha(list(mo.R4_LANG_POOLS[name])),
        "closest": {g: mo.r4_language_distractors(name, g) for g in pool[:N_PROBE]},
    }
    golds = {}
    for it in bank_items(name):
        gold = ((it.get("mc") or {}).get("language") or {}).get("gold")
        if gold and it.get("name"):
            golds[str(it["name"])] = str(gold)
    if golds:
        try:
            bal = mo.r4b_balanced_language_distractors(name, golds)
            out["balanced"] = {
                "n": len(bal),
                "sha256": blob_sha(bal),
                "first": {k: bal[k] for k in sorted(bal)[:N_PROBE]},
            }
        except (KeyError, ValueError) as e:  # a gold outside the language table
            out["balanced"] = {"failed": type(e).__name__}
    return out


def onecue_entry(name: str) -> Any:
    """F13 and §2.3: the shown order, the cache keys and the gold's banned forms of the first
    three option-list rows of the registered bank (``onecue.rows_of``)."""
    oc = need(
        "wsbench.adapt.onecue",
        ("FAMILIES", "rows_of", "_order", "_gold_forms", "tasks_of"),
        "F13: the option-order seed and cache key; §2.3: the banned forms",
    )
    st = need("wsbench.adapt.store", ("original_bank",), "the registered bank, as adapt reads it")
    if name not in oc.FAMILIES:
        return None
    out = []
    for it in st.original_bank(name)[1]:
        rows = oc.rows_of(name, it)
        if not rows:
            continue
        row = rows[0]
        tasks, _orders = oc.tasks_of([row])
        target = str(it.get("target") or "")
        out.append(
            {
                "id": row.id,
                "role": row.role,
                "order_d0": oc._order(row, 0),
                "task_keys": sorted(tasks),
                "gold_forms": list(row.gold_forms),
                "has_target": bool(target),
                "target_in_gold_forms": bool(target) and target in row.gold_forms,
            }
        )
        if len(out) == N_PROBE:
            break
    return out


def lens_entry(name: str, lens: Any) -> Any:
    """F14: ``row_sha`` of the first three REAL plan rows of the family in the lens producer's
    plan of a subject it knows, and the ``_job`` seed derived from them."""
    if name in lens.UNSUPPORTED:
        return None
    rows = lens._plan_rows(name, LENS_SUBJECT)[:N_PROBE]
    pack = [{"row_sha": lens.row_sha(r), "row": r, "family": name} for r in rows]
    out: dict[str, Any] = {"rows": [[str(p["row"].get("id")), p["row_sha"]] for p in pack]}
    if pack:
        args = SimpleNamespace(subject=LENS_SUBJECT, batch=0)
        subj = SimpleNamespace(hf_id="probe/model", revision="0")
        spec = {"kind": "olens", "path": "probe"}
        out["job_seed"] = lens._job(args, subj, LENS_ARM, spec, pack, 0)["seed"]
    return out


# ---------------------------------------------------------------- F15: the builders


def builders_entry(work: Path) -> dict[str, Any]:
    """F15, per family the two scripts cover. ``common_confusers_r5``: ``requests`` and
    ``gate`` run for real on synthetic samples (the equivalence calls stubbed), so the request
    keys, the ``gate_r5.json`` keys and the equivalence-task keys are the script's own.
    ``r4b_mc_refine``: ``draw`` on a fixed toy list, keyed the way line 773 keys it."""
    cc = need_script(
        "common_confusers_r5", ("BANKS", "requests", "gate", "am"), "F15: the gate-row keys"
    )
    rf = need_script("r4b_mc_refine", ("draw", "FAMILIES"), "F15: the seeded draw")
    out: dict[str, Any] = {}
    dest = work / "common_r5"
    with quiet():
        req = cc.requests(dest)
    rows = [json.loads(ln) for ln in req.read_text(encoding="utf-8").split("\n") if ln.strip()]
    samples = dest / "samples.jsonl"
    samples.write_text(
        "".join(
            json.dumps({"key": r["key"], "greedy": False, "text": "no listed answer"}) + "\n"
            for r in rows
            for _ in range(cc.GATE_N)
        ),
        encoding="utf-8",
    )
    asked: list[str] = []

    def claude_json(tasks: Mapping[str, Any], *_a: Any, **_k: Any) -> dict[str, Any]:
        asked.extend(tasks)
        return {k: {"same": False} for k in tasks}

    real = cc.am.claude_json
    cc.am.claude_json = claude_json
    try:
        with quiet():
            rec = cc.gate(dest, samples)
    finally:
        cc.am.claude_json = real
    for fam in cc.BANKS:
        mine = [r for r in rows if r["family"] == fam]
        keys = [r["key"] for r in mine]
        # gate_r5.json and equivalence-task keys of this family, by the request rows' own prefix
        pre = sorted({k.split("|", 1)[0] for k in keys})
        gate_keys = [k for k, v in rec.items() if v["family"] == fam]
        equiv = sorted(k for k in asked if any(k.startswith(p + "|") for p in pre))
        out.setdefault(fz(fam), {})["common_confusers_r5"] = {
            "n_requests": len(keys),
            "request_keys_sha256": blob_sha(keys),
            "request_keys_first": keys[:N_PROBE],
            "request_seeds_first": [gate_sampling.seed(r["family"], r["key"], 0) for r in mine][
                :N_PROBE
            ],
            "gate_keys_sha256": blob_sha(gate_keys),
            "gate_keys_first": gate_keys[:N_PROBE],
            "n_equiv_tasks": len(equiv),
            "equiv_keys_sha256": blob_sha(equiv),
            "equiv_keys_first": equiv[:N_PROBE],
        }
    toy = {
        "cands": [{"name": f"cand-{i}", "round": i % 2, "enwiki": f"Cand {i}"} for i in range(9)],
        "fresh_round": 1,
    }
    for fam in rf.FAMILIES:
        key = f"{fz(fam)}|('toy-item', 'role')"
        out.setdefault(fz(fam), {})["r4b_mc_refine"] = {
            "draw_key": key,
            "draw_round_1": rf.draw(json.loads(json.dumps(toy)), key, 1),
            "draw_round_2": rf.draw(json.loads(json.dumps(toy)), key, 2),
        }
    shutil.rmtree(dest, ignore_errors=True)
    return out


# ---------------------------------------------------------------- the manifest


def build() -> dict[str, Any]:
    registry.load_all()
    install_offline_stubs()
    install_recorders()
    f4 = f4_record()
    lens = need_script(
        "lens_readouts_modal",
        ("row_sha", "_plan_rows", "_job", "UNSUPPORTED", "BAND"),
        "F14: the cell store's row hash and the sampling seed",
    )
    work = Path(tempfile.mkdtemp(prefix="manifest-0101-"))
    families: dict[str, Any] = {}
    try:
        builders = builders_entry(work)
        for name in sorted(registry.FAMILIES):
            spec = registry.FAMILIES[name]
            entry: dict[str, Any] = {
                "files": file_entry(name),
                "plan": plan_entry(name),
                "stamps": stamp_entry(name, spec, f4),
                "tables": table_entry(name, f4),
                "list": list_entry(name, spec),
                "run": run_entry(name, spec, work),
                "options": options_entry(name, spec),
                "seeds": seed_entry(name),
                "capable": capable_entry(name, work),
                "adapt_generate": generate_entry(name),
                "adapt_author": author_entry(name),
                "language_distractors": language_entry(name),
                "onecue": onecue_entry(name),
                "lens_store": lens_entry(name, lens),
                "builders": builders.pop(fz(name), None),
            }
            if fz(name) in families:
                raise SystemExit(f"manifest_0101: two families land on {fz(name)!r}")
            families[fz(name)] = entry
        if builders:
            raise SystemExit(f"manifest_0101: builder rows of unknown families: {sorted(builders)}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    seen: dict[str, dict[str, str]] = {}
    for imp in IMPORTS:  # one row per module, its names merged
        row = seen.setdefault(imp["module"], {"module": imp["module"], "names": "", "role": ""})
        names = sorted({*filter(None, row["names"].split(", ")), *imp["names"].split(", ")})
        roles = sorted({*filter(None, row["role"].split("; ")), imp["role"]})
        row["names"], row["role"] = ", ".join(names), "; ".join(roles)
    return {
        "manifest": "plan 0101 §11.1",
        "base_sha": BASE_SHA,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "notes": {
            "keys": "every family key is written through registry.frozen_name (the pre-0101 key)",
            "offline": "nyt.puzzles and nocot.questions are the synthetic stubs of "
            "tests/conftest.py; WSB_* / WSBENCH_* environment variables are cleared; no "
            "network, no API call",
            "plan_sha": "nyt_connections and knowledge_cutoff plan hashes are those of the "
            "stubbed renders (deterministic; not the fetched sources' hashes)",
            "readme": "README.md is left out of the family directory's file shas: the "
            "migration rewrites it (keys, paths, title)",
            "f4": "basic.prompts.DIGEST_TASK_NOTES_TEXT is stored with its keys mapped back "
            "through frozen_name, here and inside every prompts_sha256",
            "run": f"an offline run over examples/readouts/<family>.jsonl, at most {N_ITEMS} "
            "items, canned answers built from each call's schema",
        },
        "imports": sorted(seen.values(), key=lambda r: r["module"]),
        "zero_call_exceptions": ZERO_CALL_EXCEPTIONS,
        "shared": {
            "f4_record_sha256": sha(f4[1]),
            "digest_prompt_version": digest.DIGEST_PROMPT_VERSION,
            "digest_prompts_sha256": blob_sha(canonical(digest.PROMPTS)),
            "n_families": len(families),
        },
        "families": dict(sorted(families.items())),
    }


def zero_calls(doc: Mapping[str, Any]) -> list[str]:
    """(family, mode) pairs that recorded no LLM call outside the named exceptions."""
    bad = []
    for fam, entry in doc["families"].items():
        for mode in MODES:
            excused = mode in doc["zero_call_exceptions"].get(fam, {})
            if entry["run"][mode]["n_calls"] == 0 and not excused:
                bad.append(f"{fam} ({mode})")
    return bad


def render(doc: Mapping[str, Any]) -> str:
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if str(REPO) in text:
        raise SystemExit("manifest_0101: the output holds an absolute path of this checkout")
    return text


def differences(a: Any, b: Any, path: str = "") -> list[str]:
    """The JSON paths at which two documents differ (for ``--check``'s message)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted({*a, *b}):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in {'the file' if k in a else 'this tree'}")
            else:
                out += differences(a[k], b[k], f"{path}/{k}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) != len(b):
        if all(isinstance(x, str) for x in [*a, *b]):  # call lists: say which rows moved
            gone, new = sorted(set(a) - set(b)), sorted(set(b) - set(a))
            return [
                f"{path}: {len(a)} rows in the file, {len(b)} in this tree; only in the file "
                f"{gone[:3]!r}; only in this tree {new[:3]!r}"
            ]
        return [f"{path}: {len(a)} entries in the file, {len(b)} in this tree"]
    if isinstance(a, list) and isinstance(b, list):
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in differences(x, y, f"{path}[{i}]")]  # fmt: skip
    return [] if a == b else [f"{path}: {str(a)[:120]!r} != {str(b)[:120]!r}"]


def provenance_ok() -> str:
    """Empty when the tracked tree equals :data:`BASE_SHA` outside ``plans/`` and the two
    manifest files (what a pre-manifest must be made on); else what differs."""
    try:
        got = subprocess.run(
            ["git", "diff", "--name-only", BASE_SHA, "--"],
            cwd=REPO, capture_output=True, text=True, check=True,
        )  # fmt: skip
    except (OSError, subprocess.CalledProcessError) as e:
        return f"git diff against {BASE_SHA[:8]} failed ({e})"
    own = {"scripts/manifest_0101.py", "tests/golden/manifest_0101_pre.json"}
    stray = [f for f in got.stdout.split("\n") if f and f not in own and not f.startswith("plans/")]
    return f"the tree differs from {BASE_SHA[:8]} in {stray[:8]}" if stray else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--out", type=Path, help="write the manifest (the PRE manifest: on main)")
    how.add_argument("--check", type=Path, help="regenerate and compare byte for byte")
    ap.add_argument(
        "--any-tree",
        action="store_true",
        help="--out on a tree that is not the base commit (never for the golden)",
    )
    args = ap.parse_args()
    if args.out is not None and not args.any_tree:
        why = provenance_ok()
        if why:
            print(f"manifest_0101: refusing --out: {why}", file=sys.stderr)
            return 2
    doc = build()
    text = render(doc)
    bad = zero_calls(doc)
    if bad:
        print(f"manifest_0101: no call recorded for {', '.join(bad)}", file=sys.stderr)
        return 1
    n_calls = sum(e["run"][m]["n_calls"] for e in doc["families"].values() for m in MODES)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}: {len(doc['families'])} families, {n_calls} recorded calls, "
              f"{len(text.encode())} bytes")  # fmt: skip
        return 0
    want = args.check.read_text(encoding="utf-8")
    if text == want:
        print(f"{args.check}: identical ({len(doc['families'])} families, {n_calls} calls)")
        return 0
    diffs = differences(json.loads(want), json.loads(text))
    print(f"manifest_0101: {args.check} differs at {len(diffs)} place(s):", file=sys.stderr)
    for d in diffs[:60]:
        print(f"  {d}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
