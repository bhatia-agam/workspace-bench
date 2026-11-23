"""``wsbench viewer <ingest|serve> ...``: fill the results store or serve the viewer. Each
command is a pydra config, like every wsbench command:
``key=value`` and ``--show``."""

import json
import sys
from pathlib import Path
from typing import Any

import pydra

from wsbench import registry
from wsbench.viewer import store

USAGE = """usage: wsbench viewer <command> [key=value ...] [--show | --help]

  ingest <dir> adapter=wsb|hb|bank|tokens [store=DIR]   add a lens (or the question banks)
  ingest <runs.json> adapter=manifest [store=DIR]       add the runs a manifest lists
  check [store=DIR]      every manifest run's scores against its own result files
  sources [store=DIR]    runs whose readout files are gone from this machine
  serve [store=DIR] [port=8600]                  open the viewer on http://127.0.0.1:<port>

ingest keys
  adapter=wsb   <dir> = a judged run (<family>/results.json) or a lens dir with judged/,
                judged_ati/, readouts/.  readouts=DIR  lens=NAME  model=qwen3.6-27b
                method=olens|nla|jlens|jpp_lens|rlens|logit_lens|other  label=TEXT  items=id1,id2
                families=a,b
  adapter=hb    <dir> = <out>/<lens> (holds <family>/<judge>/<arm>/cells.jsonl and
                index/<judge>/index.json).  hb_repo=DIR (bank + README)  lens=  method=  label=
                families=main,story  items=id1,id2  safety_dir=DIR (a second directory with
                or/ and br_index_root/: overrefusal, benign role-play)  readouts=DIR (their
                hb_*.jsonl readout files)
  adapter=tokens <dir> = a workspace-bench checkout: tokenize every prompt of model= with the
                subject tokenizer (offline), so the token strip shows the whole prompt
  adapter=bank  <dir> = a workspace-bench checkout: every model's questions (adapted/<model>/)
  adapter=manifest  <runs.json> = a runs manifest (README, 'Runs manifest'): each finished run
                is fetched from its volume and ingested, one lens at a time; a run in
                progress or unchanged is reported and left.  run=NAME lens=ID bench=wsb|hb
                (only those)  readouts=none|index|copy (none: readouts stay on the volume and
                are read on demand; index: fetch each eval's readout file once for the cell
                index and flags; copy: keep all text)  cache=DIR (downloads; default
                $WSB_VIEWER_CACHE or ~/.cache/wsbench-viewer)  hb_repo=DIR  families=a,b
                environment=NAME (the Modal environment of runs that name none)
                keep_downloads=True (keep the judge-call caches and cell files in the cache;
                by default they are removed once the run is stored, the result files stay)
  common        store=DIR (default $WSB_VIEWER_STORE or outputs/viewer_store)
                build_dir=DIR (build the database on a fast local disk, then move it)
                force=True (re-ingest an unchanged source)
check keys      run=RUN_ID (one run)  cache=DIR (the ingest cache, to re-read result files)
serve keys      host=127.0.0.1  port=8600  private=False (True shows items marked private)
"""


class Options(pydra.Config):
    """A viewer command's keys: defaults in ``__init__``, checks in ``finalize``."""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class Ingest(Options):
    def __init__(self) -> None:
        super().__init__()
        self.src = pydra.REQUIRED  # the directory to ingest; also the one bare argument
        self.adapter = "wsb"
        self.store = None
        self.readouts = None
        self.lens = None
        self.model = None
        self.method = None
        self.label = None
        self.items = None
        self.families = None
        self.hb_repo = None
        self.repo = None
        self.build_dir = None
        self.force = False
        self.copy_max_mb = 4096
        self.judge = None
        self.safety_dir = None
        self.run = None  # adapter=manifest: only the run of this name
        self.bench = None
        self.cache = None
        self.environment = None
        self.keep_downloads = False  # adapter=manifest: leave every download in the cache

    def finalize(self) -> None:
        if self.adapter not in ADAPTERS:
            raise ValueError(f"adapter must be one of {', '.join(ADAPTERS)}, not {self.adapter!r}")
        self.force = _bool(self.force)
        self.keep_downloads = _bool(self.keep_downloads)
        self.copy_max_mb = int(self.copy_max_mb)
        if self.adapter == "manifest":
            self.readouts = self.readouts or "none"
        for key in ("items", "families", "model"):
            setattr(self, key, _text(getattr(self, key)))
        for key in (
            "src",
            "store",
            "readouts",
            "lens",
            "method",
            "label",
            "hb_repo",
            "repo",
            "build_dir",
            "judge",
            "safety_dir",
            "run",
            "bench",
            "cache",
            "environment",
        ):
            v = getattr(self, key)
            setattr(self, key, None if v is None else str(v))


class Serve(Options):
    def __init__(self) -> None:
        super().__init__()
        self.store = None
        self.host = "127.0.0.1"
        self.port = 8600
        self.private = False  # True shows items marked private

    def finalize(self) -> None:
        self.store = None if self.store is None else str(self.store)
        self.host = str(self.host)
        self.port = int(self.port)
        self.private = _bool(self.private)


class Check(Options):
    def __init__(self) -> None:
        super().__init__()
        self.store = None
        self.run = None
        self.cache = None

    def finalize(self) -> None:
        for key in ("store", "run", "cache"):
            v = getattr(self, key)
            setattr(self, key, None if v is None else str(v))


class Sources(Options):
    def __init__(self) -> None:
        super().__init__()
        self.store = None

    def finalize(self) -> None:
        self.store = None if self.store is None else str(self.store)


ADAPTERS = ("wsb", "hb", "bank", "tokens", "manifest")
COMMANDS: dict[str, type[Options]] = {
    "ingest": Ingest, "serve": Serve, "check": Check, "sources": Sources,
}  # fmt: skip
EXIT_USAGE = 2


def _bool(v: object) -> bool:
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes")


def _text(v: object) -> str | None:
    """A comma list as text, however pydra parsed it (``a,b`` may arrive as a list or tuple)."""
    if v is None or isinstance(v, str):
        return v
    return ",".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)


def _list(v: str | None) -> list[str] | None:
    return [x for x in v.split(",") if x] if v else None


def _mb(n: int) -> str:
    return f"{n / 2**20:.1f} MB"


def _differs(r: dict) -> None:
    """Say where the judged folder and the run's own results file disagree."""
    for subset, bad in (r.get("differs") or {}).items():
        if bad:
            print(f"  {subset}: {len(bad)} evals differ from the run's results file:")
            for line in bad[:5]:
                print(f"    {line}")


def _ingest_manifest(o: Ingest) -> int:
    from wsbench.viewer.ingest import reader

    src = Path(o["src"]).expanduser()
    if not src.is_file():
        raise SystemExit(f"viewer ingest: {src} is not a runs manifest file")
    root = store.root(o["store"])
    out = reader.ingest_manifest(
        src, root, run=o["run"], lens=o["lens"], bench=o["bench"], environment=o["environment"],
        cache=Path(o["cache"]) if o["cache"] else None, readouts=o["readouts"],
        build_dir=Path(o["build_dir"]) if o["build_dir"] else None,
        repo=Path(o["repo"]) if o["repo"] else None,
        hb_repo=Path(o["hb_repo"]) if o["hb_repo"] else None, force=o["force"],
        families=_list(o["families"]), keep_downloads=o["keep_downloads"],
    )  # fmt: skip
    if not out:
        print("no run of the manifest matches")
    said: set[str] = set()
    for r in out:
        head = f"{r['bench']} {r['run']} {r['lens']}" + (f" [{r['set']}]" if r.get("set") else "")
        n, freed = r.get("cleaned") or (0, 0)
        if n and r["run_id"] not in said:  # once per run, not once per set entry
            said.add(r["run_id"])
            print(f"{r['run_id']}: removed {n} downloaded files from the cache ({_mb(freed)}): "
                  "judge-call caches, cell and readout files, now in the run database; what "
                  "the score check reads stays (keep_downloads=True keeps all)")  # fmt: skip
        if r["status"] == "ingested":
            print(f"{head}: ingested as {r['run_id']}: {r['evals']} evals, sets "
                  f"{', '.join(r['sets'])}; database {_mb(r['db_bytes'])}, downloaded "
                  f"{r['downloaded_files']} files ({_mb(r['downloaded_bytes'])}), "
                  f"{r['seconds']} s")  # fmt: skip
            lazy = r["readouts"]["on_volume"]
            if lazy:
                print(f"  readouts of {len(lazy)} evals stay on the volume (read on demand)")
            for gone in r.get("removed") or []:
                print(f"  removed the separate run {gone}: it is now a set of this run")
            _differs(r)
        elif r["status"] == "facts updated":
            print(f"{head}: files unchanged, facts updated in place ({r['run_id']}): "
                  f"{', '.join(r.get('changed') or []) or 'as its full run'}")  # fmt: skip
            _differs(r)
        elif r["status"] == "set ingested":
            from wsbench.viewer.query import is_earlier_fast, subset_title

            what = r.get("subset") or ""
            note = f" ({subset_title(what)})" if is_earlier_fast(what) else ""
            print(f"{head}: stored as a set of {r['run_id']}{note}")
        elif r["status"] == "unchanged":
            print(f"{head}: unchanged, skipped (force=True re-ingests)")
        elif r["status"] == "failed":
            print(f"{head}: FAILED, the store keeps what it had: {r.get('why')}")
        else:
            print(f"{head}: {r['status']}, skipped ({r.get('why')}); run the same command "
                  "again when it is finished")  # fmt: skip
    failed = sum(1 for r in out if r["status"] == "failed")
    if failed:
        print(f"{failed} of {len(out)} entries FAILED (exit code 1)")
    print(f"check the scores: wsbench viewer check store={root}")
    return 1 if failed else 0


def _check(o: Check) -> int:
    from wsbench.viewer import checks

    root = store.root(o["store"])
    got = checks.store_scores(
        root, [o["run"]] if o["run"] else None, Path(o["cache"]) if o["cache"] else None
    )
    if not got:
        print(f"{root}: no run ingested from a manifest")
    bad = 0
    for rid, r in got.items():
        state = "ok" if not r["mismatches"] else f"{len(r['mismatches'])} MISMATCHES"
        print(f"{rid}: {r['checked']} scores, {state} (against {r['against']})")
        for line in r["mismatches"]:
            print(f"  {line}")
        bad += len(r["mismatches"])
    return 1 if bad else 0


def _sources(o: Sources) -> int:
    import os

    from wsbench.viewer import checks

    root = store.root(o["store"])
    rows = checks.missing_sources(root)
    for r in rows:
        where = os.path.commonpath(r["missing"]) if len(r["missing"]) > 1 else r["missing"][0]
        print(f"{r['run_id']}: {len(r['missing'])} readout files gone ({where}); "
              f"{r['n_without_text']} of {r['n_cells']} cells have no text in the store and "
              "show the 'not available' marker")  # fmt: skip
    print(f"{len(rows)} runs with readout files that no longer exist")
    return 0


def _ingest(o: Ingest) -> int:
    if o["adapter"] == "manifest":
        return _ingest_manifest(o)
    src = Path(o["src"]).expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"viewer ingest: {src} is not a directory")
    root = store.root(o["store"])
    build = Path(o["build_dir"]) if o["build_dir"] else None
    if o["adapter"] == "bank":
        from wsbench.viewer.ingest import wsb

        out = wsb.ingest_banks(root, src, _list(o["model"]))
        for model, n in out.items():
            print(f"  {model}: {n} questions")
        print(f"banks -> {root}")
        return 0
    if o["adapter"] == "tokens":
        from wsbench.viewer import tokens
        from wsbench.viewer.ingest import wsb

        out = tokens.ingest(root, o["model"] or wsb.ORIGINAL, _list(o["families"]))
        print(f"token strip mode: {out['mode']}" + (f" ({out['why']})" if out["why"] else ""))
        print(f"  {sum(out['families'].values())} prompts in {len(out['families'])} evals")
        return 0
    if o["adapter"] == "wsb":
        from wsbench.viewer.ingest import wsb

        out = wsb.ingest(
            src, root, lens=o["lens"], model=o["model"] or wsb.ORIGINAL, method=o["method"],
            label=o["label"], readouts=Path(o["readouts"]) if o["readouts"] else None,
            repo=Path(o["repo"]) if o["repo"] else registry.REPO_ROOT, items=_list(o["items"]),
            families=_list(o["families"]), build_dir=build, force=o["force"],
            copy_max_mb=o["copy_max_mb"],
        )  # fmt: skip
    elif o["adapter"] == "hb":
        from wsbench.viewer.ingest import hb

        out = hb.ingest(
            src, root, lens=o["lens"], model=o["model"] or hb.MODEL, method=o["method"],
            label=o["label"], hb_repo=Path(o["hb_repo"]) if o["hb_repo"] else None,
            items=_list(o["items"]), families=_list(o["families"]), build_dir=build,
            force=o["force"], judge=o["judge"],
            safety_dir=Path(o["safety_dir"]) if o["safety_dir"] else None,
            readouts=Path(o["readouts"]) if o["readouts"] else None,
        )  # fmt: skip
    else:  # finalize() admits only ADAPTERS
        raise AssertionError(o["adapter"])
    if out.get("skipped"):
        print(f"{out['run_id']}: unchanged, skipped (force=True re-ingests)")
    else:
        for fam, f in out.get("families", {}).items():
            value = "—" if f.get("value") is None else f"{100 * f['value']:.1f}%"
            print(f"  {fam:38s} value {value:>6s}  n {f.get('n')}  cells {f.get('cells')}")
        print(f"{out['run_id']} -> {store.run_db_path(root, out['run_id'])}")
    print(f"open it: wsbench viewer serve store={root}")
    return 0


def _serve(o: Serve) -> int:
    try:
        from wsbench.viewer.app.main import serve
    except ImportError as e:
        raise SystemExit(
            f"viewer serve needs the viewer extra: uv sync --extra viewer ({e})"
        ) from e
    root = store.root(o["store"])
    if not (root / "catalog.db").exists():
        raise SystemExit(f"{root}: no catalog.db; run `wsbench viewer ingest` first")
    serve(root, host=o["host"], port=o["port"], private=o["private"])
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print(USAGE)
        return 0 if argv and argv[0] in ("-h", "--help") else EXIT_USAGE
    name, rest = argv[0], argv[1:]
    if any(a in ("-h", "--help") for a in rest):
        print(USAGE)
        return 0
    command = COMMANDS[name]()
    # the one bare argument of `ingest` is its directory: `ingest <dir>` = `ingest src=<dir>`
    if name == "ingest":
        rest = [a if "=" in a or a.startswith("--") else f"src={a}" for a in rest]
    try:
        show = pydra.apply_overrides(command, rest)
    except (ValueError, TypeError, AttributeError, IndexError) as e:
        print(f"viewer {name}: {e}\n\n{USAGE}", file=sys.stderr)
        return EXIT_USAGE
    if show:
        print(json.dumps(command.to_dict(), indent=1))
        return 0
    if isinstance(command, Ingest):
        return _ingest(command)
    if isinstance(command, Check):
        return _check(command)
    if isinstance(command, Sources):
        return _sources(command)
    return _serve(command)


if __name__ == "__main__":
    registry.load_all()
    sys.exit(main(sys.argv[1:]))
