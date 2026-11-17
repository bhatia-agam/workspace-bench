"""``wsbench run``: judge several families concurrently, fail-soft, one preflight per model."""

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from wsbench import digest, fast, llm, mc, mcjudge, reads, registry
from wsbench.baselines import text_inversion
from wsbench.family import fail
from wsbench.judge_config import ResolvedJudge, resolve
from wsbench.llm import JudgeConfigError
from wsbench.registry import EvalSpec, JudgeArgs
from wsbench.results import FamilyResult, read_results, write_results

Status = Literal["ok", "skipped", "failed"]


@dataclass
class FamilyOutcome:
    family: str
    status: Status
    result: FamilyResult | None = None
    error: str | None = None  # for skipped / failed
    exit_code: int = 0  # 3 JudgeConfigError, 2 SystemExit
    waited_s: float | None = None  # run wait=: seconds until its readouts were ready (late only)


class Options(Protocol):
    """The judge options ``wsbench judge`` passes down (``cli.JudgeOptions``)."""

    judge_model: str | None
    layers: list[int] | None
    items: list[str] | None
    limit: int
    allow_missing: bool
    concurrency: int
    rpm: float
    dry_run: bool
    anti_text_inversion: bool
    opt: list[str]


class RunOptions(Options, Protocol):
    """``wsbench run``'s options: the judge options plus the thread count (0 = every family at
    once). ``wait`` / ``settle`` (plan 0092) are read with ``getattr``, default 0, and ``procs``
    (one judge process per family, plan 0092 §5) with default False."""

    family_workers: int


def parse_opts(pairs: Sequence[str]) -> dict[str, str]:
    """``opts=KEY=VALUE,...`` -> dict; a malformed pair, or a bad summary-mode option
    (``aggregate`` / ``summ_*``), is a usage error (exit 2). ``aggregate`` defaults to
    ``digest.DEFAULT_AGGREGATE`` (summary, plan 0024); ``opts=aggregate=native`` opts out."""
    out: dict[str, str] = {}
    for p in pairs:
        if "=" not in p:
            fail(f"opts= expects KEY=VALUE pairs, got {p!r}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    out.setdefault("aggregate", digest.DEFAULT_AGGREGATE)
    digest.validate(out)  # a bad summary-mode option exits 2 before any family starts
    return out


def warn_mode_change(out: Path, aggregate: str, family: str) -> None:
    """Warn (stderr) when ``out`` already holds a ``results.json`` of the other aggregate mode:
    rerunning a pre-0024 native out dir under the summary default overwrites it family by family,
    and the macro then drops the native rows that remain (plan 0024)."""
    prev = out / "results.json"
    if not prev.exists():
        return
    try:
        old = json.loads(prev.read_text(encoding="utf-8")).get("config", {}).get("aggregate")
    except (OSError, ValueError):
        return
    old = old or "native"
    if old != aggregate:
        print(
            f"warning: {family}: {prev} is an aggregate={old} result; this run is "
            f"aggregate={aggregate} and overwrites it (use a separate out= dir to keep both)",
            file=sys.stderr,
        )


def ati_entry(args: Any, family: str) -> dict[str, Any]:
    """``text_inversion.subset_entry`` of ``family`` from the ``ati_variant=`` file, with the
    ``ati_opt_in=`` families (plan 0088)."""
    variant = getattr(args, "ati_variant", "") or ""
    opt_in = getattr(args, "ati_opt_in", None) or ()
    if not variant and not opt_in:  # the default: exactly the pre-0088 call
        return text_inversion.subset_entry(family)
    dst = text_inversion.frozen_path(variant)
    return text_inversion.subset_entry(family, dst, opt_in=opt_in)


def judge_family(
    spec: EvalSpec,
    args: Options,
    readouts: Path,
    out: Path,
    *,
    judge: ResolvedJudge,
    opts: Mapping[str, str],
) -> FamilyResult:
    """Run one family with an already-resolved judge and pre-parsed ``opts=``; write its
    ``results.json`` and print the one-line summary. Under ``anti_text_inversion`` the family's
    items are its frozen subset (``text_inversion.subset``, which exits for an ungated or stale
    family) and the result is stamped with the scope. Under ``fast`` (plan 0090) the items are
    the family's fast read ids, and the result is rescored on the fast units and stamped."""
    items, scope, ati = args.items, "", None
    fast_entry = fast.entry(spec.name) if getattr(args, "fast", False) else None
    fast_partial = 0
    if fast_entry is not None:
        read_ids = list(fast_entry["read_ids"])
        if args.items is not None:
            # plan 0092 §2c: items= under --fast is a PART of the fast items (a warm-up of the
            # cache, e.g. one group of a family judged in parallel groups); never a full result
            want = set(args.items)
            stray = sorted(want - set(read_ids))
            if stray:
                raise SystemExit(f"{spec.name}: items= not in {fast.VERSION}: {stray[:5]}")
            read_ids = [i for i in read_ids if i in want]
            fast_partial = len(read_ids)
        items, scope = read_ids, fast.SCOPE
    if spec.name not in digest.NATIVE_ONLY:  # those run native under either mode
        warn_mode_change(out, opts.get("aggregate", "native"), spec.name)
    if getattr(args, "anti_text_inversion", False):
        ati = ati_entry(args, spec.name)
        items, scope = list(ati["ids"]), text_inversion.SCOPE
    # v1.1.0: a multi-layer summary run of a non-numbers family defaults to summ_layers=layered
    if (
        "summ_layers" not in opts
        and spec.name not in digest.NATIVE_ONLY
        and opts.get("aggregate") == "summary"
    ):  # (the layer count may load the file: only when it can matter)
        opts = digest.resolve_layer_mode(spec.name, opts, run_layer_count(readouts, args.layers))
    jargs = JudgeArgs(
        readouts=readouts,
        out=out,
        judge=judge,
        layers=args.layers,
        items=items,
        limit=args.limit,
        allow_missing=args.allow_missing,
        concurrency=args.concurrency,
        rpm=args.rpm,
        dry_run=args.dry_run,
        aux_models=spec.judge.aux_models,
        extra=dict(opts),
        scope=scope,
    )
    with llm.error_tally() as errors:
        try:
            result = spec.run(jargs)
        finally:
            if errors.n:  # plan 0092 §2b: loud, and no change to the completeness rule
                print(
                    f"{spec.name}: {errors.n} judge call(s) failed after retries; affected "
                    "cells are unjudged or their items were digested on fewer layers",
                    file=sys.stderr,
                )
    finalize_reads(jargs, result)
    stamp_adapted_bank(spec.name, result)
    if opts.get("aggregate") == "summary" and result.config.get("aggregate") != "summary":
        if spec.name not in digest.NATIVE_ONLY:
            fail(f"{spec.name}: aggregate=summary but the family ran native (not hooked)")
        result.config["aggregate"] = "native"
        result.extras["summary_mode_note"] = digest.NATIVE_ONLY[spec.name]
    if fast_entry is not None:
        stamp_fast(spec.name, result, fast_entry)
        if fast_partial:
            result.complete = False
            result.extras["fast_items_subset"] = fast_partial
    if ati is not None:
        result.config["scope"] = scope
        result.extras["ati_n_bank"] = ati["n_bank"]
        result.extras["ati_n_ids"] = len(ati["ids"])  # the macro's ATI count (plan 0071 §1a)
        result.extras["ati_judge_model"] = ati.get("judge_model")
        result.extras["ati_gate"] = ati.get("gate", "plan-0014")
        if result.extras["ati_gate"] == text_inversion.GATE_VERSION:  # plan 0085: registered only
            result.extras["ati_subset"] = text_inversion.SUBSET_VERSION
        if ati.get("provisional"):  # a reduced-panel gate (decision R1-ATI): say which readers
            result.extras["ati_provisional"] = True
        if ati.get("provisional") or ati.get("status_order"):  # reduced panel, even if cleared
            result.extras["ati_panel"] = ati.get("panel")
        if "argon_decisive_items" in ati:  # cleared: argon could move no item (R1-ATI argon)
            result.extras["ati_argon_decisive_items"] = ati["argon_decisive_items"]
        # plan 0088: an opted-in family, an adapted set's macro exception
        if spec.name in (getattr(args, "ati_opt_in", None) or ()):
            result.extras["ati_opt_in"] = True
        if ati.get("macro_exception") and ati.get("gate") != text_inversion.GATE_VERSION:
            result.extras["ati_macro_exception"] = ati["macro_exception"]
    path = write_results(out, result)
    spend = result.counts.get("spend_usd", 0.0) or 0.0
    print(
        f"{spec.name}: {result.metric}={result.value} n={result.n_items} "
        f"spend=${spend:.2f} pinned={result.pinned_instrument} complete={result.complete} "
        f"-> {path}"
    )
    return result


STAMP_KEYS = ("prompt_version", "instrument_of_record")


def _header_version(path: Path) -> int | None:
    """A wrapped bank's header ``version`` (None for a bare list or a header without one)."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    v = raw.get("version") if isinstance(raw, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def adapted_bank_stamp(family: str, pv: str) -> str:
    """Plan 0072 Phase 0.2: under ``$WSB_BANK_ROOT`` (and no ``WSB_BANK_FILE_<FAMILY>`` pin) a
    stamp's ``+bank-v<N>`` tag, N being the REGISTERED bank's header version, names the judged
    adapted bank's header version M instead when M != N, so a stale set is never stamped as a
    refreshed one. Call keys never change (only the result stamp), a set whose header matches
    the registered one keeps the stamp byte for byte, and no root = unchanged."""
    if not os.environ.get(registry.BANK_ROOT_ENV) or "+bank-v" not in pv:
        return pv
    fam = registry.canonical(family)
    names = [fam, *registry.legacy_names(fam)]
    if any(os.environ.get(registry.BANK_FILE_ENV_PREFIX + n.upper()) for n in names):
        return pv
    try:
        reg = _header_version(registry.frozen_bank_path(fam))
        got = _header_version(registry.bank_path(fam))
    except (SystemExit, KeyError, OSError, ValueError):
        return pv
    if reg is None or got is None or reg == got:
        return pv
    return re.sub(rf"\+bank-v{reg}(?=\+|$)", f"+bank-v{got}", pv, count=1)


def stamp_adapted_bank(family: str, result: FamilyResult) -> None:
    """``adapted_bank_stamp`` on the result's stamps (``STAMP_KEYS`` of ``config``). A rewritten
    ``prompt_version`` keeps the registered one in ``config.registered_prompt_version``, which
    ``results.floor_applies`` compares instead (the floor column is unchanged by the rewrite)."""
    for k in STAMP_KEYS:
        v = result.config.get(k)
        if isinstance(v, str) and (new := adapted_bank_stamp(family, v)) != v:
            if k == "prompt_version":
                result.config["registered_prompt_version"] = v
            result.config[k] = new


def stamp_fast(family: str, result: FamilyResult, entry: Mapping[str, Any]) -> None:
    """Plan 0090: the fast value (``fast.rescore``), ``config.scope`` / ``fast_subset``, and,
    for a family whose fast entry reduces the positions, the ``+fast-<kind>`` suffix on the
    result's stamps (once)."""
    fast.rescore(family, result)
    result.config["scope"] = fast.SCOPE
    result.config["fast_subset"] = fast.VERSION
    if rule := entry.get("positions"):
        tag = fast.position_stamp(rule)
        for k in STAMP_KEYS:
            v = result.config.get(k)
            if isinstance(v, str) and not v.endswith(tag):
                result.config[k] = v + tag


def finalize_reads(args: JudgeArgs, result: FamilyResult) -> None:
    """The load's stamps on every result, whatever the family's own config builder (plan 0032
    §2.0 / §2.6): ``config.reads`` / ``sampling`` / ``sampling_source`` / ``reader`` /
    ``reads_checked`` / ``layers_judged``; ``+reads-lite`` on a lite ``prompt_version``; the
    partial ids, missing layers and sampling diag counts in ``extras``; ``complete=False`` when
    the load left items partial or layers missing, or a summary item was truncated (stride)."""
    for k, v in reads.config_stamps(args).items():
        result.config.setdefault(k, v)
    pv = result.config.get("prompt_version")
    if isinstance(pv, str):
        result.config["prompt_version"] = reads.stamp(pv, reads.mode(args))
    result.config.setdefault("token_note_version", mc.TOKEN_NOTE_VERSION)
    for k, v in reads.extras_of(args).items():
        if v:  # only what the load found (a clean load adds nothing, as a direct call)
            result.extras.setdefault(k, v)
    summ = result.extras.get("summary")
    truncated = result.extras.get("summary_complete") is False or (
        isinstance(summ, dict) and summ.get("summary_complete") is False
    )
    if reads.incomplete(args) or truncated:
        result.complete = False
    elif not result.complete and (n := refusals_only(args, result)):
        # audit F3 ("never score a refusal as a fail"; the prompt-only 20% rule applied to lens
        # rows): a summary row whose ONLY shortfall is final digest refusals is measured on its
        # decided items; results.macro then leaves it out as "not measurable" above 20%
        result.complete = True
        result.extras["complete_with_digest_refusals"] = n


def refusals_only(args: JudgeArgs, result: FamilyResult) -> int:
    """The number of items whose digest was finally refused (or too long, or with more than
    ``digest.PARTIAL_UNDECIDED_SHARE`` of its layers unserved), when those are the
    ONLY reason ``result`` is incomplete: a summary-mode, pinned, full (not subset) run with no
    missing cells, every unjudged item a refused digest the family scores as undecided (its
    ``extras.n_items_undecided`` covers them), the shared 5% empty rule met, and no
    family-forced incompleteness (``extras.incomplete_reason``: introspection's ``scope=``
    sub-scopes, jailbreak's sub-grid regimes); else 0. A failed
    judge call (transient, a rerun retries it) keeps a run incomplete."""
    summ = result.extras.get("summary")
    summ = summ if isinstance(summ, dict) else result.extras
    refused = sum(
        int(summ.get(k) or 0)
        for k in ("n_digest_refused", "n_digest_too_long", "n_items_partial_undecided")
    )
    undecided = result.extras.get("n_items_undecided")
    c = result.counts
    ok = (
        refused > 0
        and not result.extras.get("incomplete_reason")  # a family's own sub-scope / regime
        and result.config.get("aggregate") == "summary"
        and result.pinned_instrument
        and not mcjudge.is_subset(args)
        and isinstance(undecided, int)
        and undecided >= refused
        and int(c.get("n_missing_cells") or 0) == 0
        and int(c.get("n_unjudged_cells") or 0) == refused
        and int(c.get("n_empty_cells") or 0) <= 0.05 * result.n_items
    )
    return refused if ok else 0


def readouts_path(root: Path, name: str) -> Path | None:
    """``root/<family>.jsonl`` (or a former family key's file, ``registry.lookup_names``), None
    when there is none."""
    return next(
        (p for key in registry.lookup_names(name) if (p := root / f"{key}.jsonl").exists()), None
    )


POLL = 2.0  # seconds between looks at the pending families of `run wait=` (a seam for tests)
READS_DONE = "_READS_DONE"  # readouts_root/_READS_DONE: the producer's "no more files are coming"
_clock = time.monotonic  # seams: tests patch these instead of the time module
_sleep = time.sleep
_wall = time.time


def readouts_ready(path: Path, settle: float = 0.0) -> bool:
    """Plan 0092: a readouts file is ready when it exists and its sidecar exists, parses as a
    JSON object and is not older than the file. With ``settle > 0`` a file with no sidecar whose
    mtime is at least ``settle`` seconds old is ready too."""
    from wsbench.readouts import sidecar_path

    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return False
    side = sidecar_path(path)
    try:
        side_mtime = side.stat().st_mtime_ns
    except OSError:
        return settle > 0 and _wall() - mtime / 1e9 >= settle
    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(meta, dict) and side_mtime >= mtime


def _ready_path(root: Path, name: str, settle: float) -> Path | None:
    """The family's readouts file (``readouts_path``, so a former key's file counts) when it is
    ready, else None."""
    found = readouts_path(root, name)
    return found if found is not None and readouts_ready(found, settle) else None


def _pending_message(root: Path, name: str, wait: float, sentinel: bool) -> str:
    """Why a family still pending when the wait stopped is skipped."""
    found = readouts_path(root, name)
    if found is not None:
        return f"readouts at {found} not ready after {wait:g}s (no current sidecar)"
    path = root / f"{name}.jsonl"
    return (
        f"no readouts at {path}" if sentinel else f"no readouts at {path} after waiting {wait:g}s"
    )


def run_layer_count(path: Path, layers: Sequence[int] | None) -> int:
    """How many layers a run reads: ``layers=`` when given, else the sidecar's declared
    ``layers``, else the layers present in the file (one load)."""
    if layers is not None:
        return len(set(layers))
    from wsbench.readouts import read_sidecar

    meta = read_sidecar(path) if Path(path).exists() else None
    if meta and isinstance(meta.get("layers"), list):
        return len(set(meta["layers"]))
    return len(file_layers(path)) if Path(path).exists() else 0


def file_layers(path: Path) -> list[int]:
    """The layers present in a readouts file (one cheap pass, no parsing beyond the layer)."""
    from wsbench.readouts import load_readouts

    return load_readouts(path)[1].layers


def each_configs(path: Path) -> list[tuple[str, list[int] | None]]:
    """``layers=each``: the all-layer config, then one config per layer in the file."""
    return [("all", None), *((f"L{k}", [k]) for k in file_layers(path))]


def _one(
    spec: EvalSpec,
    args: Options,
    readouts: Path,
    out: Path,
    judge: ResolvedJudge | None = None,
    opts: Mapping[str, str] | None = None,
) -> FamilyOutcome:
    """One family, fail-soft: ``JudgeConfigError`` -> failed/3, ``SystemExit`` (missing cells,
    refused input) -> failed/2. Anything else propagates. Without ``opts`` / ``judge`` (``judge
    outcome=``, a ``run``'s child process) the option parsing and the judge resolution happen
    here, under the same rule."""
    try:
        if opts is None:
            opts = parse_opts(args.opt)
        if judge is None:
            judge = resolve(spec.judge, flag=args.judge_model, env=os.environ)
        result = judge_family(spec, args, readouts, out, judge=judge, opts=opts)
    except JudgeConfigError as e:
        print(f"{spec.name}: judge config error: {e}", file=sys.stderr)
        return FamilyOutcome(spec.name, "failed", error=str(e), exit_code=3)
    except SystemExit as e:
        text = e.code if isinstance(e.code, str) else f"exit {e.code}"
        print(f"{spec.name}: failed ({text})", file=sys.stderr)
        return FamilyOutcome(spec.name, "failed", error=text, exit_code=2)
    return FamilyOutcome(spec.name, "ok", result=result)


# ---------------------------------------------------------------- process mode (plan 0092 §5)

RUN_PROCS_ENV = "WSB_RUN_PROCS"  # 0 / 1: the default of `run procs=` (the key wins; unset = on)
PACER_ENV = llm.PACER_ENV
RUN_SLOTS = 1500  # API calls in flight across a run's judge processes (about a 15M OTPM account)
OUTCOME = "outcome.json"  # <out>/<family>/outcome.json: a child's status, read and deleted


def write_outcome(path: Path, oc: FamilyOutcome) -> None:
    """``judge outcome=PATH``: the family's ``{family, status, error, exit_code}``, atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"family": oc.family, "status": oc.status, "error": oc.error, "exit_code": oc.exit_code}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _read_outcome(path: Path) -> dict[str, Any] | None:
    """A child's outcome file, None when there is none or it is not one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = isinstance(data, dict) and data.get("status") in ("ok", "skipped", "failed")
    return data if ok else None


def die_with_parent() -> None:
    """Linux: have the kernel send this process SIGTERM when the thread that started it exits
    (``PR_SET_PDEATHSIG``), so a ``run``'s judge processes do not outlive it; best effort."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(1, int(signal.SIGTERM), 0, 0, 0)
    except (OSError, AttributeError, ImportError, ValueError):
        pass


def judge_argv(name: str, args: Any, readouts: Path, dest: Path) -> list[str]:
    """The ``wsbench judge`` command of one family of a ``run``: the judge keys that are set,
    never the run-only ones (``all``, ``families``, ``readouts_root``, ``family_workers``,
    ``wait``, ``settle``, ``json``, ``hb_method``, ``include_superseded``, ``dry_run``,
    ``procs``)."""
    cmd = [sys.executable, "-m", "wsbench", "judge", f"family={name}", f"readouts={readouts}"]
    cmd += [f"out={dest}", f"outcome={dest / OUTCOME}"]
    cmd += [f"concurrency={args.concurrency}", f"rpm={args.rpm}"]
    if (itpm := getattr(args, "itpm", None)) is not None:
        cmd.append(f"itpm={itpm}")
    if args.judge_model:
        cmd.append(f"judge_model={args.judge_model}")
    if args.layers is not None:
        cmd.append("layers=" + ",".join(str(k) for k in args.layers))
    if args.items is not None:
        cmd.append("items=" + ",".join(args.items))
    if args.limit:
        cmd.append(f"limit={args.limit}")
    if args.allow_missing:
        cmd.append("allow_missing=True")
    if getattr(args, "anti_text_inversion", False):
        cmd.append("anti_text_inversion=True")
    if variant := getattr(args, "ati_variant", ""):
        cmd.append(f"ati_variant={variant}")
    if opt_in := getattr(args, "ati_opt_in", None):
        cmd.append("ati_opt_in=" + ",".join(opt_in))
    if getattr(args, "fast", False):
        cmd.append("fast=True")
    if args.opt:  # carries reads= / sampling= already
        cmd.append("opts=" + ",".join(args.opt))
    return cmd


class _Child(subprocess.Popen):
    """A judge process in its own session; ``terminate`` / ``kill`` signal its whole group."""

    def _signal_group(self, sig: int) -> None:
        if self.poll() is not None:
            return
        try:
            os.killpg(self.pid, sig)
        except OSError:
            self.send_signal(sig)

    def terminate(self) -> None:
        self._signal_group(signal.SIGTERM)

    def kill(self) -> None:
        self._signal_group(signal.SIGKILL)


def _spawn(cmd: Sequence[str], env: Mapping[str, str]) -> Any:
    """Start one judge process (stdout / stderr inherited, its own session). A seam: tests
    return a Popen-like object (``wait``, ``poll``, ``terminate``, ``kill``)."""
    return _Child(list(cmd), env=dict(env), start_new_session=True)


def _probe_flock(d: Path) -> None:
    """Take and release one ``flock`` in ``d``; raises ``OSError`` where locks do not work."""
    import fcntl

    fd = os.open(d / "probe", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _on_signal(signum: int, _frame: Any) -> None:
    raise SystemExit(128 + signum)  # SIGTERM / SIGHUP: unwind through run_families' cleanup


class _Procs:
    """Process mode of ``run_families``: one ``wsbench judge`` child per family, a run-private
    local directory holding the slots and the pacer files the children share, and the cleanup
    (signal handlers, children still alive, the directory)."""

    def __init__(self, args: Any) -> None:
        self.args = args
        self.stop = threading.Event()  # no new child is started
        self.killed = threading.Event()  # the children were terminated: theirs is no result
        self.lock = threading.Lock()
        self.children: dict[str, Any] = {}
        self.tmp: Path | None = None
        self.env: dict[str, str] = {}
        self._handlers: dict[int, Any] = {}

    def start(self) -> str | None:
        """Make the directory, probe ``flock`` there, build the children's environment and
        install the SIGTERM / SIGHUP handlers; returns the problem when locks do not work."""
        self.tmp = Path(tempfile.mkdtemp(prefix="wsb-run-"))
        slots, pacer = self.tmp / "slots", self.tmp / "pacer"
        try:
            slots.mkdir()
            pacer.mkdir()
            _probe_flock(slots)
        except (OSError, ImportError) as e:
            return (
                f"file locks do not work in {self.tmp} ({e}); the judge processes share their "
                f"budgets through them. Set TMPDIR to a local directory, or pass procs=False"
            )
        self.env = dict(os.environ)  # the parent's own environment is never changed
        self.env["PYTHONUNBUFFERED"] = "1"
        if not self.env.get(llm.SLOTS_ENV):  # an operator's value is inherited as is
            self.env[llm.SLOTS_ENV] = f"{slots}:{RUN_SLOTS}"
        self.env[PACER_ENV] = str(pacer)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            # (not in the main thread: no handler; the caller's finally still cleans up)
            with contextlib.suppress(ValueError, OSError):
                if signal.getsignal(sig) is signal.SIG_IGN:
                    continue  # e.g. under nohup: the run keeps ignoring the hangup
                self._handlers[sig] = signal.signal(sig, _on_signal)
        return None

    def terminate(self) -> None:
        """Terminate every tracked child still alive; none is started afterwards."""
        self.stop.set()
        self.killed.set()
        with self.lock:
            for child in self.children.values():
                if child.poll() is None:
                    child.terminate()

    def close(self) -> None:
        """The ``finally`` of a run: kill what is still alive, restore the handlers, remove the
        directory."""
        self.stop.set()
        try:
            for sig in self._handlers:  # a second signal must not abort the cleanup
                with contextlib.suppress(ValueError, OSError, TypeError):
                    signal.signal(sig, signal.SIG_IGN)
            with self.lock:
                alive = [c for c in self.children.values() if c.poll() is None]
            if alive:
                self.terminate()
                for child in alive:
                    try:
                        child.wait(timeout=10)
                    except Exception:  # still there after SIGTERM
                        child.kill()
                        child.wait()
        finally:
            for sig, old in self._handlers.items():
                # a handler installed from C reads back as None: restore the default
                with contextlib.suppress(ValueError, OSError, TypeError):
                    signal.signal(sig, signal.SIG_DFL if old is None else old)
            self._handlers.clear()
            if self.tmp is not None:
                shutil.rmtree(self.tmp, ignore_errors=True)


def _one_proc(procs: _Procs, spec: EvalSpec, readouts: Path, dest: Path) -> FamilyOutcome:
    """One family as a child ``wsbench judge`` process: spawn it, wait, map its outcome file
    (written by ``_one`` in the child) or, without one, its exit code. Exit 2 / 3 and a signal
    are a failed family; any other exit terminates the other children and raises."""
    name = spec.name
    interrupted = FamilyOutcome(name, "skipped", error="interrupted")
    if procs.stop.is_set():
        return interrupted
    path = dest / OUTCOME
    path.unlink(missing_ok=True)  # a stale one of an earlier run
    cmd = judge_argv(name, procs.args, readouts, dest)
    with procs.lock:
        if procs.stop.is_set():
            return interrupted
        sys.stdout.flush()
        child = _spawn(cmd, procs.env)
        procs.children[name] = child
    code = child.wait()
    data = _read_outcome(path)
    path.unlink(missing_ok=True)
    if code < 0 and procs.killed.is_set():
        return interrupted
    if data is not None:
        if data["status"] == "ok":  # an unreadable results.json raises
            return FamilyOutcome(name, "ok", result=read_results(dest))
        return FamilyOutcome(
            name, data["status"], error=data.get("error"), exit_code=int(data.get("exit_code") or 0)
        )
    if code in (2, 3):
        error, exit_code = f"judge process exited {code}", code
    elif code < 0:  # e.g. the OOM killer: this family failed, the others go on
        error, exit_code = f"judge process killed by signal {-code}", 2
    else:
        procs.terminate()
        raise RuntimeError(f"{name}: judge process exited {code} without an outcome")
    print(f"{name}: failed ({error})", file=sys.stderr)
    return FamilyOutcome(name, "failed", error=error, exit_code=exit_code)


def _seed_preflights(judges: Mapping[str, ResolvedJudge]) -> None:
    """Preflight each distinct (model, reasoning) once, through the module attribute (so one
    monkeypatch counts the runner and the families), and seed ``mcjudge._PREFLIGHTED``."""
    seen: dict[str, ResolvedJudge] = {}
    for j in judges.values():
        seen.setdefault(mcjudge.preflight_key(j.model, j.reasoning), j)
    for k, j in seen.items():
        with mcjudge._PREFLIGHT_LOCK:
            if k in mcjudge._PREFLIGHTED:
                continue
            llm.preflight(j.model, j.reasoning)
            mcjudge._PREFLIGHTED.add(k)


def run_families(
    specs: Sequence[EvalSpec],
    args: RunOptions,
    *,
    readouts_root: Path,
    out: Path,
    env: Mapping[str, str] | None = None,
    out_of: Callable[[str], Path] | None = None,
) -> tuple[list[FamilyOutcome], int]:
    """Judge ``specs`` from ``readouts_root/<family>.jsonl`` into ``out/<family>/``.

    Order of operations: parse ``opts=`` once (a bad pair is one ``SystemExit``, nothing
    started); resolve every judge once; skip families with no readouts file; unless
    ``dry_run=True``, preflight each distinct judge model once (a failure aborts with exit 3
    before any thread starts); then run the rest in a ``ThreadPoolExecutor`` with
    ``min(len(runnable), family_workers)`` workers (every family at once when
    ``family_workers <= 0``; 1 under ``dry_run`` so printed prompts do not interleave). The
    process-wide pacer is shared, so ``rpm=`` bounds the whole run.

    ``args.wait > 0`` (plan 0092): a family whose readouts are not ready (``readouts_ready``) is
    pending instead of skipped. Every ``POLL`` seconds the pending ones are looked at again and
    submitted as they become ready, until none is pending, ``wait`` seconds have passed or
    ``readouts_root/_READS_DONE`` exists; the rest are then skipped. The preflight covers them.

    Returns the outcomes in ``specs`` order and the exit code: 130 if interrupted, else 3 if
    any family hit a ``JudgeConfigError``, else 2 if any raised ``SystemExit``, else 0.
    ``KeyboardInterrupt`` cancels unstarted families (``skipped``, "interrupted") and waits for
    in-flight ones to finish their current batch (they are recorded normally).

    Process mode (plan 0092 §5: ``args.procs`` true and no ``env`` passed): the same loop submits
    ``_one_proc``, one ``wsbench judge`` child per family, after the same parent-side checks and
    preflight; the children share ``rpm`` / ``itpm`` and a cap on calls in flight through a
    run-private directory. A second ``KeyboardInterrupt`` terminates the children."""
    procs = _Procs(args) if getattr(args, "procs", False) and env is None else None
    env = os.environ if env is None else env
    opts = parse_opts(args.opt)
    judges = {s.name: resolve(s.judge, flag=args.judge_model, env=env) for s in specs}
    outcomes: dict[str, FamilyOutcome] = {}
    runnable: list[tuple[EvalSpec, Path]] = []
    wait = float(getattr(args, "wait", 0) or 0)
    settle = float(getattr(args, "settle", 0) or 0)
    started = _clock()
    pending: list[EvalSpec] = []  # wait > 0: families whose readouts are not ready yet

    def admit(s: EvalSpec) -> Path | None:
        """The file check and the ATI scope check of one family: its readouts path when it can
        run, else None with its skipped / failed outcome recorded."""
        readouts = readouts_root / f"{s.name}.jsonl"
        # a readout file written under a former family key (registry.LEGACY_FAMILY_NAMES; for a
        # reused key the former key's file wins, registry.lookup_names)
        found = readouts_path(readouts_root, s.name)
        if found is not None and found != readouts:
            print(f"{s.name}: reading legacy {found.name}")
            readouts = found
        if not readouts.exists():
            msg = f"no readouts at {readouts}"
            print(f"{s.name}: skipped ({msg})")
            outcomes[s.name] = FamilyOutcome(s.name, "skipped", error=msg)
            return None
        if getattr(args, "anti_text_inversion", False):
            # checked before any preflight: an out-of-scope family is skipped, a stale or
            # missing subset entry fails (re-gate); neither spends a call
            try:
                ati_entry(args, s.name)
            except text_inversion.NotInScope as e:
                print(f"{s.name}: skipped ({e.code})")
                outcomes[s.name] = FamilyOutcome(s.name, "skipped", error=str(e.code))
                return None
            except SystemExit as e:
                print(f"{s.name}: failed ({e.code})", file=sys.stderr)
                outcomes[s.name] = FamilyOutcome(s.name, "failed", error=str(e.code), exit_code=2)
                return None
        return readouts

    for s in specs:
        if getattr(args, "fast", False):
            # plan 0090, before anything else: a family outside the fast subset is skipped, a
            # bank override or a bank that changed since the freeze fails; neither spends a call
            try:
                fast.entry(s.name)
            except fast.NotInFast:
                print(f"{s.name}: skipped (not in {fast.VERSION})")
                outcomes[s.name] = FamilyOutcome(s.name, "skipped", error=f"not in {fast.VERSION}")
                continue
            except SystemExit as e:
                print(f"{s.name}: failed ({e.code})", file=sys.stderr)
                outcomes[s.name] = FamilyOutcome(s.name, "failed", error=str(e.code), exit_code=2)
                continue
        if wait > 0 and _ready_path(readouts_root, s.name, settle) is None:
            pending.append(s)  # plan 0092: waited for, not skipped
            continue
        if (readouts := admit(s)) is not None:
            runnable.append((s, readouts))
    # a family with a deterministic scorer of record makes no call unless opts=judge=mc; under
    # wait > 0 the pending families are preflighted with the runnable ones, before any submit
    candidates = [s for s, _r in runnable] + pending
    needs_llm = [s for s in candidates if not s.scorer or opts.get("judge") == "mc"]
    to_preflight: dict[str, ResolvedJudge] = {s.name: judges[s.name] for s in needs_llm}
    if opts.get("aggregate") == "summary":  # every family's digest model (plan 0020)
        for s in candidates:
            to_preflight[f"digest:{s.name}"] = digest.preflight_judge(opts, s.judge.aux_models)
    if to_preflight and not args.dry_run:
        try:
            _seed_preflights(to_preflight)
        except JudgeConfigError as e:
            print(f"judge config error: {e}", file=sys.stderr)
            return [], 3

    n = len(candidates)
    cap = n if args.family_workers <= 0 else min(n, args.family_workers)  # 0 = all at once
    workers = 1 if args.dry_run else max(1, cap)
    interrupted = False
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wsbench-family")
    futures: dict[Future[FamilyOutcome], str] = {}
    waited: dict[str, float] = {}

    def submit(s: EvalSpec, readouts: Path) -> None:
        dest = out_of(s.name) if out_of is not None else registry.family_dir(out, s.name)
        if procs is not None:
            fut = executor.submit(_one_proc, procs, s, readouts, dest)
        else:
            fut = executor.submit(_one, s, args, readouts, dest, judges[s.name], opts)
        futures[fut] = s.name

    try:
        if procs is not None and (problem := procs.start()) is not None:
            print(f"run: {problem}", file=sys.stderr)
            executor.shutdown(wait=False)
            return [], 3
        for s, readouts in runnable:
            submit(s, readouts)
        collected: set[Future[FamilyOutcome]] = set()
        while pending:
            # (ii) submit the pending families whose readouts became ready
            still: list[EvalSpec] = []
            for s in pending:
                if _ready_path(readouts_root, s.name, settle) is None:
                    still.append(s)
                    continue
                t = round(_clock() - started, 1)
                print(f"{s.name}: readouts landed after {t:g}s")
                if (readouts := admit(s)) is not None:
                    runnable.append((s, readouts))
                    waited[s.name] = t
                    submit(s, readouts)
            pending[:] = still
            # (iii) stop: nothing pending, the producer's sentinel, or the deadline
            sentinel = (readouts_root / READS_DONE).exists()
            if not pending or sentinel or _clock() - started >= wait:
                for s in pending:
                    msg = _pending_message(readouts_root, s.name, wait, sentinel)
                    print(f"{s.name}: skipped ({msg})")
                    outcomes[s.name] = FamilyOutcome(s.name, "skipped", error=msg)
                pending.clear()
                break
            # (i) one tick: collect finished families (a worker exception re-raises here)
            in_flight = [f for f in futures if f not in collected]
            if in_flight:
                done, _ = wait_futures(in_flight, timeout=POLL, return_when=FIRST_COMPLETED)
                for fut in done:
                    oc = fut.result()
                    outcomes[oc.family] = oc
                    collected.add(fut)
            else:
                _sleep(POLL)
        for fut in as_completed(futures):
            oc = fut.result()
            outcomes[oc.family] = oc
    except KeyboardInterrupt:
        interrupted = True
        print("interrupted: cancelling unstarted families", file=sys.stderr)
        # unstarted families are cancelled; in-flight ones cannot be and finish their batch
        if procs is None:
            executor.shutdown(wait=True, cancel_futures=True)
        else:  # no new child; the running ones finish, unless interrupted again
            procs.stop.set()
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except KeyboardInterrupt:
                print("interrupted again: terminating the judge processes", file=sys.stderr)
                procs.terminate()
                executor.shutdown(wait=True)
        for fut, name in futures.items():
            if fut.done() and not fut.cancelled() and fut.exception() is None:
                outcomes[name] = fut.result()
        for s in [*(s for s, _readouts in runnable), *pending]:
            outcomes.setdefault(s.name, FamilyOutcome(s.name, "skipped", error="interrupted"))
    except BaseException:
        # an unexpected worker exception propagates (plan), but must not leave the other
        # families spending in the background
        if procs is not None:
            procs.stop.set()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    finally:
        if procs is not None:  # children still alive, the signal handlers, the directory
            procs.close()
    for name, t in waited.items():
        if name in outcomes:
            outcomes[name].waited_s = t

    ordered = [outcomes[s.name] for s in specs]
    if interrupted:
        code = 130
    elif any(o.exit_code == 3 for o in ordered):
        code = 3
    elif any(o.exit_code == 2 for o in ordered):
        code = 2
    else:
        code = 0
    return ordered, code


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_manifest(
    outcomes: Sequence[FamilyOutcome],
    *,
    started: datetime,
    finished: datetime,
    args: Options,
    out: Path,
    readouts_root: Path,
    env: Mapping[str, str] | None = None,
) -> dict:
    """The ``run.json`` payload: per-family status plus the judge overrides in force."""
    env = os.environ if env is None else env
    families: dict[str, dict] = {}
    for o in outcomes:
        d: dict = {"status": o.status}
        if o.error is not None:
            d["error"] = o.error
        if o.result is not None:
            r = o.result
            d.update(
                results_path=str(out / o.family / "results.json"),
                value=r.value,
                complete=r.complete,
                pinned_instrument=r.pinned_instrument,
                spend_usd=r.counts.get("spend_usd"),
            )
            if "n_calls" in r.extras:
                d["n_calls"] = r.extras["n_calls"]
        if o.waited_s is not None:  # plan 0092: submitted late under wait=
            d["waited_s"] = o.waited_s
        families[o.family] = d
    manifest: dict = {
        "started": _iso(started),
        "finished": _iso(finished),
        "families": families,
        "judge_overrides": {"flag": args.judge_model, "env": env.get("WSBENCH_JUDGE_MODEL")},
        # the effective aggregate mode (plan 0024: summary unless opts=aggregate=native)
        "aggregate": parse_opts(list(getattr(args, "opt", None) or []))["aggregate"],
        "readouts_root": str(readouts_root),
    }
    if getattr(args, "hb_method", ""):  # plan 0040: `wsbench report` prints its HB index
        manifest["hb_method"] = args.hb_method
    if wait := float(getattr(args, "wait", 0) or 0):  # plan 0092: only when set
        manifest["wait"] = wait
    return manifest
