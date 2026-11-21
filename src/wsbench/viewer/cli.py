"""``wsbench viewer <ingest|serve|bank> ...``: fill the results store, serve the viewer, or
build the static bank browser. Each command is a pydra config, like every wsbench command:
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
  serve [store=DIR] [port=8600]                  open the viewer on http://127.0.0.1:<port>
  bank [out=outputs/viewer]                      the static per-model bank browser

ingest keys
  adapter=wsb   <dir> = a judged run (<family>/results.json) or a lens dir with judged/,
                judged_ati/, readouts/.  readouts=DIR  lens=NAME  model=qwen3.6-27b
                method=olens|nla|jlens|logit_lens|other  label=TEXT  items=id1,id2
                families=a,b
  adapter=hb    <dir> = <out>/<lens> (holds <family>/<judge>/<arm>/cells.jsonl and
                index/<judge>/index.json).  hb_repo=DIR (bank + README)  lens=  method=  label=
                families=main,story  items=id1,id2  safety_dir=DIR (a second directory with
                or/ and br_index_root/: overrefusal, benign role-play)  readouts=DIR (their
                hb_*.jsonl readout files)
  adapter=tokens <dir> = a workspace-bench checkout: tokenize every prompt of model= with the
                subject tokenizer (offline), so the token strip shows the whole prompt
  adapter=bank  <dir> = a workspace-bench checkout: every model's questions (adapted/<model>/)
  common        store=DIR (default $WSB_VIEWER_STORE or outputs/viewer_store)
                build_dir=DIR (build the database on a fast local disk, then move it)
                force=True (re-ingest an unchanged source)
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

    def finalize(self) -> None:
        if self.adapter not in ADAPTERS:
            raise ValueError(f"adapter must be one of {', '.join(ADAPTERS)}, not {self.adapter!r}")
        self.force = _bool(self.force)
        self.copy_max_mb = int(self.copy_max_mb)
        for key in ("items", "families", "model"):
            setattr(self, key, _text(getattr(self, key)))
        for key in ("src", "store", "readouts", "lens", "method", "label", "hb_repo", "repo",
                    "build_dir", "judge", "safety_dir"):  # fmt: skip
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


class Bank(Options):
    def __init__(self) -> None:
        super().__init__()
        self.out = "outputs/viewer"

    def finalize(self) -> None:
        self.out = str(self.out)


ADAPTERS = ("wsb", "hb", "bank", "tokens")
COMMANDS: dict[str, type[Options]] = {"ingest": Ingest, "serve": Serve, "bank": Bank}
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


def _ingest(o: Ingest) -> int:
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
    if isinstance(command, Serve):
        return _serve(command)
    from wsbench.viewer import build

    build.main(command["out"])
    return 0


if __name__ == "__main__":
    registry.load_all()
    sys.exit(main(sys.argv[1:]))
