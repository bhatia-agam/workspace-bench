"""The FastHTML app: routes only. Pages are built in ``pages``, data comes from ``query``."""

import hmac
import threading
from pathlib import Path
from typing import Any

from fasthtml.common import Beforeware, Link, NotStr, Script, Title, fast_app
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from wsbench.viewer import meta
from wsbench.viewer.app import pages
from wsbench.viewer.query import BENCH_TITLES, Store

# FastHTML serves static extensions (css, js) relative to static_path: /static/app.css
STATIC = Path(__file__).resolve().parents[1] / "static"
ASSET_VERSION = "9"


COOKIE = "bench_viewer_key"


def key_gate(key: str) -> Beforeware:
    """Link-key access for a hosted viewer: ``/?key=<KEY>`` once sets an HttpOnly cookie and
    redirects to the clean URL; any request without the key or the cookie gets 403."""

    def ok(value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(str(value).encode(), key.encode())

    def gate(req, sess):  # type: ignore[no-untyped-def]  (FastHTML injects by name)
        if ok(req.query_params.get("key")):
            resp = RedirectResponse(str(req.url.remove_query_params("key")), status_code=303)
            resp.set_cookie(COOKIE, key, httponly=True, secure=True, samesite="lax",
                            max_age=90 * 86400)  # fmt: skip
            return resp
        if not ok(req.cookies.get(COOKIE)):
            return HTMLResponse("<h3>403: this viewer needs its link key</h3>", status_code=403)
        return None

    return Beforeware(gate)


def create_app(store_root: Path, private: bool = False, key: str | None = None) -> Any:
    """The viewer app over one store. ``private`` shows items marked private; ``key`` puts
    the whole app behind a link key (hosted deployments)."""
    db = Store(store_root, private=private)
    # the runs page counts each run's stored readout text once; do it before the first visit
    threading.Thread(target=db.runs_table, daemon=True).start()
    hdrs = (
        Link(rel="stylesheet", href=f"/static/app.css?v={ASSET_VERSION}"),
        Script(src=f"/static/app.js?v={ASSET_VERSION}", defer=True),
        Script(src=f"/static/panes.js?v={ASSET_VERSION}", defer=True),
        Script(src=f"/static/grid.js?v={ASSET_VERSION}", defer=True),
    )
    app, rt = fast_app(
        pico=False, surreal=False, hdrs=hdrs, secret_key="bench-viewer", canonical=False,
        static_path=str(STATIC.parent),
        middleware=(Middleware(GZipMiddleware, minimum_size=800),), bodykw={"hx-boost": "true"},
        title="Bench viewer", before=key_gate(key) if key else None,
    )  # fmt: skip

    def page(title: str, body: str) -> tuple:
        return Title(f"{title} · Bench viewer"), NotStr(body)

    def view(req: Request) -> tuple[pages.View, dict[str, str]]:
        q = dict(req.query_params)
        return pages.make_view(db, q), q

    @rt("/")
    def scores(req: Request):
        v, _q = view(req)
        return page(BENCH_TITLES.get(v.bench, v.bench), pages.scores_page(db, v))

    @rt("/eval/{name}")
    def one_eval(req: Request, name: str):
        v, _q = view(req)
        return page(name, pages.eval_page(db, v, name))

    @rt("/q/{name}/{item:path}")
    def question(req: Request, name: str, item: str):
        v, q = view(req)
        return page(item, pages.question_page(db, v, name, item, q))

    @rt("/layers")
    def layers(req: Request):
        v, q = view(req)
        return page("Layers", pages.layers_page(db, v, q.get("eval") or "", q.get("kind") or ""))

    @rt("/filter")
    def filter_(req: Request):
        v, q = view(req)
        return page("Filter", pages.filter_page(db, v, q))

    @rt("/search")
    def search(req: Request):
        v, q = view(req)
        return page("Search", pages.search_page(db, v, q))

    @rt("/runs")
    def runs(req: Request):
        v, _q = view(req)
        return page("Runs", pages.runs_page(db, v))

    @rt("/bookmarks")
    def bookmarks(req: Request):
        v, _q = view(req)
        return page("Bookmarks", pages.bookmarks_page(db, v))

    @rt("/bookmarks/delete", methods=["POST"])
    async def bookmark_delete(req: Request):
        form = await req.form()
        db.delete_bookmark(int(form.get("id") or 0))
        return RedirectResponse("/bookmarks", status_code=303)

    @rt("/api/cells")
    def api_cells(run: str, eval: str, item: str):
        return JSONResponse(db.cells(run, eval, item))

    @rt("/api/digest")
    def api_digest(run: str, eval: str, item: str):
        return JSONResponse({"text": db.digest(run, eval, item)})

    @rt("/api/item")
    def api_item(bench: str, model: str, eval: str, item: str):
        it = db.item(bench, model, eval, item)
        verdicts = {
            r["run_id"]: r
            for r in db.q(
                "SELECT run_id, pass, score FROM verdict WHERE eval = ? AND item = ?", (eval, item)
            )
        }
        runs = [
            {
                "id": r["run_id"], "label": r["label"], "method": meta.method_key(r["method"]),
                "lens": r["lens"], "description": r["description"],
                "integrity": r["integrity"], "integrityReason": r["integrity_reason"],
                "pass": verdicts[r["run_id"]]["pass"] if r["run_id"] in verdicts else None,
                "score": verdicts[r["run_id"]]["score"] if r["run_id"] in verdicts else None,
            }
            for r in db.runs(bench, model)
        ]  # fmt: skip
        return JSONResponse({"item": it, "runs": runs})

    @rt("/api/bookmark", methods=["POST"])
    async def api_bookmark(req: Request):
        return JSONResponse({"id": db.add_bookmark(await req.json())})

    return app


def serve(
    store_root: Path, host: str = "127.0.0.1", port: int = 8600, private: bool = False
) -> None:
    import uvicorn

    print(f"bench viewer: http://{host}:{port}  (store {store_root}, private items "
          f"{'shown' if private else 'hidden'})")  # fmt: skip
    uvicorn.run(create_app(store_root, private), host=host, port=port, log_level="warning")
