"""The pages, as HTML strings built from store queries. Each function takes the opened store
and the request's view (bench, model, subset, chosen runs) and returns a page body."""

import json
from dataclasses import dataclass, field
from typing import Any

from wsbench.viewer import meta
from wsbench.viewer.app import components as c
from wsbench.viewer.app.components import esc, url
from wsbench.viewer.query import (
    BENCH_TITLES,
    CORE,
    MACRO,
    METHOD_TITLES,
    SUBSET_TITLES,
    Store,
    gate_cards,
)

MAX_DEFAULT_RUNS = 6
FLOORS = (("prompt_only", "Prompt only"), ("lucky_guess", "Lucky guess"), ("chance", "Chance"))
FLOOR_COLOR = {"prompt_only": "#64748b", "lucky_guess": "#94a3b8", "chance": "#cbd5e1"}
LAYER_KINDS = {
    "judge": ("Judge verdict per layer", "exact",
              "The scorer ran on each layer separately (regex and native evals)."),
    "expected": ("Expected answer appears in the readout", "proxy",
                 "Share of questions whose readouts at this layer contain the expected answer as "
                 "text. A string match, not a judge verdict."),
    "cited": ("Judge's quote comes from this layer", "proxy",
              "Among questions where the judge quoted evidence: share whose quote is found in "
              "this layer's readouts. Shows where the credited evidence sits."),
    "hb": ("Hallucination rate per layer", "exact",
           "Weighted share of claims that are hallucinated, from the HB index."),
}  # fmt: skip
WANTS = (("right", "right ✓"), ("wrong", "wrong ✗"), ("undecided", "undecided"))


@dataclass
class View:
    """What the request is looking at; parsed once from the query string."""

    bench: str
    model: str
    subset: str = "full"
    runs: list[str] = field(default_factory=list)  # chosen run ids, [] = default
    default_subset: str = "full"  # what a link without subset= means: core where it exists

    def args(self, **extra: Any) -> dict[str, Any]:
        base = {"bench": self.bench, "model": self.model}
        if self.subset != self.default_subset:
            base["subset"] = self.subset
        if self.runs:
            base["runs"] = ",".join(self.runs)
        return base | extra

    @property
    def pct(self) -> bool:
        return self.bench == "hb"


def make_view(db: Store, q: dict[str, str]) -> View:
    benches = db.benches()
    bench = q.get("bench") if q.get("bench") in benches else (benches[0] if benches else "wsb")
    models = [m["model"] for m in db.models(bench)]
    model = q.get("model") if q.get("model") in models else (models[0] if models else "")
    subsets = db.subsets(bench, model)
    default = CORE if CORE in subsets else "full"  # the core tier is the bench's default
    subset = q.get("subset") if q.get("subset") in subsets else default
    runs = [r for r in (q.get("runs") or "").split(",") if r]
    return View(bench, model, subset, runs, default)


def chosen_runs(db: Store, v: View) -> tuple[list[dict], list[dict]]:
    """``(shown, all)`` runs of the view."""
    runs = db.runs(v.bench, v.model)
    if v.runs:
        shown = [r for r in runs if r["run_id"] in v.runs]
    else:  # the lenses the alias file marks `"default": true`, else the first few
        shown = [r for r in runs if r.get("default")] or runs[:MAX_DEFAULT_RUNS]
    return shown, runs


NOT_RUN = "This lens's run has no readouts or judged results for this eval."


def lens_chip(r: dict, color: str = "") -> str:
    """A lens's short label; the full id on hover and, with its description, in a popover.
    ``color`` is the lens's bar color, shown as a swatch."""
    swatch = f'<i class="sw" style="background:{color}"></i>' if color else ""
    desc = r.get("description") or "No description yet: add one to lens_aliases.json in the store."
    return (
        f'<details class="lens"><summary title="{esc(r["lens"])}">{swatch or c.method_dot(r["method"])}'
        f'<span>{esc(r["label"])}</span></summary><div class="lens-pop"><b>{esc(r["label"])}</b>'
        f"<code>{esc(r['lens'])}</code><p>{esc(desc)}</p>"
        f"<small>{esc(METHOD_TITLES.get(r['method'], r['method']))} · judge "
        f"{esc(r.get('judge') or '?')} · {esc(r.get('mode') or '')}</small></div></details>"
    )


# ------------------------------------------------------------------ chrome


def controls(db: Store, v: View, path: str, extra: str = "", pick_runs: bool = True) -> str:
    """The bench / model / subset dropdowns and the method chooser, one GET form."""
    benches = [(b, BENCH_TITLES.get(b, b)) for b in db.benches()]
    models = [
        (
            m["model"],
            f"{m['model']}  ·  {m['n_evals']} evals" + ("" if m["n_runs"] else "  ·  no runs"),
        )
        for m in db.models(v.bench)
    ]
    subsets = [(s, SUBSET_TITLES[s]) for s in db.subsets(v.bench, v.model)]
    parts = [
        c.select("bench", benches, v.bench, "Bench"),
        c.select("model", models, v.model, "Subject model"),
    ]
    if len(subsets) > 1:
        parts.append(c.select("subset", subsets, v.subset, "Subset"))
    if pick_runs:
        shown, runs = chosen_runs(db, v)
        ids = {r["run_id"] for r in shown}
        if len(runs) > 1:
            boxes = "".join(
                f'<label>{c.method_dot(r["method"])}<input type="checkbox" value="{esc(r["run_id"])}"'
                f"{' checked' if r['run_id'] in ids else ''}> {esc(r['label'])}"
                f"<small>{esc(r['lens']) if r['lens'] != r['label'] else ''}</small></label>"
                for r in runs
            )
            parts.append(
                f'<details class="pick"><summary>Methods <b>{len(shown)}/{len(runs)}</b></summary>'
                f'<div class="pick-menu" data-runs>{boxes}<button type="button" class="btn"'
                f' onclick="applyRuns(this)">Apply</button></div></details>'
                f'<input type="hidden" name="runs" value="{esc(",".join(v.runs))}">'
            )
    return (
        f'<form class="controls" method="get" action="{esc(path)}">{"".join(parts)}{extra}</form>'
    )


def nav(v: View, active: str) -> str:
    links = (("scores", "/"), ("layers", "/layers"), ("filter", "/filter"), ("search", "/search"),
             ("bookmarks", "/bookmarks"))  # fmt: skip
    items = "".join(
        f'<a href="{esc(url(href, **v.args()))}"{" class=on" if name == active else ""}>'
        f"{name.capitalize()}</a>"
        for name, href in links
    )
    return (
        f'<header class="top"><a class="brand" href="/">Bench viewer</a><nav>{items}</nav></header>'
    )


def crumbs(v: View, *parts: tuple[str, str | None]) -> str:
    out = [f'<a href="{esc(url("/", **v.args()))}">{esc(BENCH_TITLES.get(v.bench, v.bench))}</a>']
    for text, href in parts:
        out.append(
            f'<a href="{esc(href)}">{esc(text)}</a>' if href else f"<span>{esc(text)}</span>"
        )
    return '<div class="crumbs">' + "<i>/</i>".join(out) + "</div>"


def empty(text: str) -> str:
    return f'<div class="empty">{esc(text)}</div>'


# ------------------------------------------------------------------ scores


def scores_page(db: Store, v: View) -> str:
    shown, runs = chosen_runs(db, v)
    scores = db.scores(v.bench, v.model, v.subset)
    groups = db.groups(v.bench, v.model)
    counts = db.subset_counts(v.bench, v.model, v.subset)
    floors = [(k, t) for k, t in FLOORS if any(k in s for s in scores.values())]
    top = 1.0
    if v.pct:
        vals = [
            s["value"] for e in scores.values() for s in e.values() if s.get("value") is not None
        ]
        top = max([*vals, 0.01]) * 1.15

    scored_runs = {k for sc in scores.values() for k in sc}

    def eval_link(e: dict) -> str:
        return url(f"/eval/{c.seg(e['eval'])}", **v.args())

    paint = {r["run_id"]: c.run_color(n) for n, r in enumerate(shown)}
    head = "".join(
        f'<th class="run">{lens_chip(r, paint[r["run_id"]])}</th>' for r in shown
    ) + "".join(f'<th class="run floor"><span>{esc(t)}</span></th>' for _k, t in floors)
    rows = []
    macro = scores.get(MACRO)
    if macro:
        cells = "".join(
            c.score_cell(macro.get(r["run_id"]), "c-" + r["method"], v.pct, top, paint[r["run_id"]])
            for r in shown
        )
        cells += "".join('<td class="sc none"></td>' for _ in floors)
        n = next((s["n"] for s in macro.values() if s.get("n")), "")
        rows.append(
            f'<tr class="macro"><td class="name"><b>Macro</b><small>mean over evals in this '
            f'subset</small></td><td class="n">{esc(n)} evals</td>{cells}</tr>'
        )
    side = []
    for g, evs in groups:
        if v.subset != "full":
            evs = [e for e in evs if e["eval"] in scores]
        if not evs:
            continue
        gid = "g-" + c.seg(g)
        rows.append(
            f'<tr class="grp" id="{esc(gid)}"><td colspan="{2 + len(shown) + len(floors)}">'
            f"{esc(g)}<small>{len(evs)} evals</small></td></tr>"
        )
        links = []
        for e in evs:
            sc = scores.get(e["eval"], {})
            n = (
                counts.get(e["eval"])
                or next(
                    (s["n"] for k, s in sc.items() if s.get("n") and k not in dict(FLOORS)), None
                )
                or e["n_items"]
            )
            why = e.get("readme") or NOT_RUN
            cells = "".join(
                c.score_cell(sc[r["run_id"]], "c-" + r["method"], v.pct, top, paint[r["run_id"]])
                if r["run_id"] in sc
                else c.not_run(why)
                if r["run_id"] in scored_runs
                else '<td class="sc none">—</td>'
                for r in shown
            )
            cells += "".join(c.score_cell(sc.get(k), "floor", v.pct, top) for k, _t in floors)
            goal = meta.first_sentence(e["what"] or "", 150)
            rows.append(
                f'<tr id="e-{esc(e["eval"])}"><td class="name"><a href="{esc(eval_link(e))}">'
                f"{esc(e['title'])}</a><small>{c.inline_md(goal)}</small></td>"
                f'<td class="n">{esc(n or "—")}</td>{cells}</tr>'
            )
            links.append(
                f'<a href="{esc(eval_link(e))}">{esc(e["title"])}<small>{esc(n or "")}</small></a>'
            )
        side.append(
            f'<details open><summary><a href="#{esc(gid)}">{esc(g)}</a><small>{len(evs)}</small>'
            f"</summary>{''.join(links)}</details>"
        )
    if not rows:
        table = empty("No evals for this bench and model yet. Run `wsbench viewer ingest`.")
    else:
        table = (
            f'<table class="scores"><thead><tr><th>Eval</th><th class="n">Questions</th>{head}'
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )
    note = ""
    if v.bench == "hb":
        note = "Hallucination rate, lower is better. Headline = mean over the judged layers."
    elif v.subset == CORE:
        note = ("The core tier: the evals a method is reported on, each on its whole question "
                "set, with the core macro. Same verdicts as the full bench.")  # fmt: skip
    elif v.subset == "fast-safety":
        note = ("The fast subset plus jailbreak recognition and agentic misalignment. "
                "Not comparable with the full-bench column: different question set.")  # fmt: skip
    elif v.subset == "fast":
        note = ("The frozen fast questions only. "
                "Not comparable with the full-bench column: different question set.")  # fmt: skip
    elif v.subset == "ati":
        note = "Only questions that text-only readers could not solve from the prompt."
    elif not runs:
        note = "No runs ingested for this model: the table lists its question set only."
    else:
        note = (
            "Pass rate with 95% CI. Dimmed floors were measured with another judge prompt version."
        )
    return (
        nav(v, "scores")
        + controls(db, v, "/")
        + f'<div class="layout"><aside class="side">{"".join(side)}</aside><main>'
        f'<p class="note">{esc(note)}</p>{table}</main></div>'
    )


# ------------------------------------------------------------------ one eval


def eval_page(db: Store, v: View, name: str, want: str = "") -> str:
    e = db.eval(v.bench, v.model, name)
    if e is None:
        return nav(v, "scores") + empty(f"No eval {name!r} for {v.model}.")
    shown, _runs = chosen_runs(db, v)
    scores = db.scores(v.bench, v.model, v.subset).get(name, {})
    items = db.items(v.bench, v.model, name, v.subset)
    bars = []
    for n, r in enumerate(shown):
        s = scores.get(r["run_id"])
        if s:
            bars.append({"label": c.short_label(r["label"], 28), "value": s["value"],
                         "lo": s["ci_lo"], "hi": s["ci_hi"], "color": c.SERIES[n % 8],
                         "kind": "lens"})  # fmt: skip
    for k, t in FLOORS:
        if k in scores:
            s = scores[k]
            bars.append({"label": t, "value": s["value"], "lo": s["ci_lo"], "hi": s["ci_hi"],
                         "color": FLOOR_COLOR[k], "kind": k})  # fmt: skip
    stats = db.layer_stats(v.bench, v.model, name).get(name, {})
    layer_html = ""
    for kind in ("judge", "hb", "expected", "cited"):
        if kind not in stats:
            continue
        series = [
            {"label": c.short_label(r["label"], 28), "color": c.SERIES[n % 8],
             "points": stats[kind].get(r["run_id"], [])}
            for n, r in enumerate(shown)
        ]  # fmt: skip
        title, tag, tip = LAYER_KINDS[kind]
        layer_html += (
            f'<div class="card"><h4>{esc(title)} <span class="tag {tag}">{tag}</span></h4>'
            f'<p class="hint">{esc(tip)}</p>{c.line_chart(series, v.pct)}{c.legend(series)}</div>'
        )
        break
    gates_html = "".join(
        f'<div class="gate"><b>{esc(g["name"])}</b><p>{esc(g["text"])}</p></div>'
        for g in gate_cards(e["gates"])
    )
    example = (
        f'<div class="block"><h4>Example</h4><p>{c.inline_md(e["example"])}</p></div>'
        if e["example"] else ""
    )  # fmt: skip
    first = next((i for i in items if not i["private"]), None)
    try_link = ""
    if first:
        href = url(f"/q/{c.seg(name)}/{c.seg(first['item'])}", **v.args())
        try_link = f'<a class="btn" href="{esc(href)}">Open the first question →</a>'
    template = (
        f'<details class="tmpl"><summary>Judge prompt template (from the eval\'s README)</summary>'
        f'<div class="md">{c.md(e["prompt_template"])}</div></details>'
        if e["prompt_template"] else ""
    )  # fmt: skip
    left = (
        f'<div class="card info"><div class="grp-tag">{esc(e["grp"])}</div><h2>{esc(e["title"])}</h2>'
        f'<div class="facts"><span><b>{len(items) or e["n_items"]}</b> questions</span>'
        f"<span>metric <b>{esc(e['metric'] or 'pass_rate')}</b></span>"
        f"<span>{'lower' if e['higher_is_better'] == 0 else 'higher'} is better</span></div>"
        f'<div class="block"><h4>What it tests</h4><p>{c.inline_md(e["what"] or "—")}</p></div>'
        f'{example}<div class="block judged"><h4>How it is judged</h4>'
        f"<p>{c.inline_md(e['judged_by'] or '—')}</p>{template}</div>"
        f'<div class="block"><h4>Gates</h4><div class="gates">{gates_html or "—"}</div></div></div>'
    )
    right = (
        f'<div class="card"><h4>Scores <span class="hint">{esc(SUBSET_TITLES[v.subset])}, 95% CI'
        f"</span></h4>{c.bar_chart(bars, v.pct) or empty('no scores ingested')}</div>{layer_html}"
    )

    # the question list, with a per-method verdict and quick filters
    run_head = "".join(
        f'<th title="{esc(r["lens"])}">{c.method_dot(r["method"])}<span>{esc(r["label"])}</span></th>'
        for r in shown
    )
    body = []
    for it in items:
        href = url(f"/q/{c.seg(name)}/{c.seg(it['item'])}", **v.args())
        marks = "".join(
            f'<td class="vc" data-run="{n}" data-pass="{"" if (x := it["runs"].get(r["run_id"], {})).get("pass") is None else x["pass"]}">'
            f"{c.badge(x.get('pass'), x.get('score') if v.pct else None)}</td>"
            for n, r in enumerate(shown)
        )
        exp = (
            "private"
            if it["private"] and not it["expected"]
            else ", ".join(map(str, it["expected"]))
        )
        lock = ' <i class="lock" title="private item">private</i>' if it["private"] else ""
        body.append(
            f'<tr data-item="{esc(it["item"])}"><td class="id"><a href="{esc(href)}">{esc(it["item"])}'
            f'</a>{lock}</td><td class="exp">{esc(exp[:90])}</td>{marks}</tr>'
        )
    chips = ""
    if len(shown) >= 1 and not v.pct:
        opts = "".join(f'<option value="{n}">{esc(c.short_label(r["label"], 26))}</option>'
                       for n, r in enumerate(shown))  # fmt: skip
        wants = '<option value="1">right ✓</option><option value="0">wrong ✗</option><option value="">undecided</option>'
        second = (
            f'<span>and</span><select id="fb">{"<option value=-1>(any)</option>" + opts}</select>'
            f'<select id="fbw">{wants.replace("value=\"0\"", "value=\"0\" selected")}</select>'
            if len(shown) > 1 else ""
        )  # fmt: skip
        chips = (
            f'<div class="qfilter"><span>Show questions where</span><select id="fa">'
            f'<option value="-1">(all questions)</option>{opts}</select><select id="faw">{wants}'
            f'</select>{second}<span id="fcount" class="hint"></span></div>'
        )
    qtable = (
        f'<div class="card"><h4>Questions</h4>{chips}<div class="qwrap"><table class="qlist" '
        f'id="qlist"><thead><tr><th>Question</th><th>Expected</th>{run_head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div></div>"
    )
    return (
        nav(v, "scores")
        + controls(db, v, f"/eval/{c.seg(name)}")
        + f'<div class="page">{crumbs(v, (e["grp"], None), (e["title"], None))}'
        f'<div class="split"><div>{left}</div><div>{right}{try_link}</div></div>{qtable}</div>'
    )


# ------------------------------------------------------------------ one question (shell)


def question_page(db: Store, v: View, name: str, item: str, q: dict[str, str]) -> str:
    e = db.eval(v.bench, v.model, name)
    it = db.item(v.bench, v.model, name, item)
    if e is None or it is None:
        return nav(v, "scores") + empty(f"No question {item!r} in {name!r}.")
    shown, runs = chosen_runs(db, v)
    items = db.items(v.bench, v.model, name, v.subset)
    if item not in {x["item"] for x in items}:
        items = db.items(v.bench, v.model, name, "full")
    ids = [x["item"] for x in items if db.private or not x["private"]]
    verdicts = next((x["runs"] for x in items if x["item"] == item), {})
    data = {
        "bench": v.bench, "model": v.model, "subset": v.subset, "eval": name,
        "evalTitle": e["title"], "pct": v.pct, "item": it, "ids": ids,
        "runs": [
            {"id": r["run_id"], "label": r["label"], "method": r["method"], "lens": r["lens"],
             "description": r["description"],
             "pass": verdicts.get(r["run_id"], {}).get("pass"),
             "score": verdicts.get(r["run_id"], {}).get("score")}
            for r in runs
        ],
        # open the first three chosen methods that have something on this question
        "open": ([r["run_id"] for r in shown if r["run_id"] in verdicts]
                 or [r["run_id"] for r in shown])[:3],
        "layer": q.get("l"), "pos": q.get("p"), "find": q.get("find") or "",
        "judgedBy": e["judged_by"], "gates": gate_cards(e["gates"]),
    }  # fmt: skip
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    back = url(f"/eval/{c.seg(name)}", **v.args())
    return (
        nav(v, "scores")
        + f'<div class="qpage" id="qapp">{crumbs(v, (e["grp"], None), (e["title"], back), (item, None))}'
        '<div id="qhead"></div><div id="qstrip"></div><div id="qpanes"></div>'
        '<div id="qhelp" class="help"></div></div>'
        f'<script type="application/json" id="qdata">{blob}</script>'
    )


# ------------------------------------------------------------------ layers


def layers_page(db: Store, v: View, name: str, kind: str) -> str:
    shown, _ = chosen_runs(db, v)
    stats = db.layer_stats(v.bench, v.model, name or None)
    kinds = [k for k in LAYER_KINDS if any(k in s for s in stats.values())]
    if kind not in kinds:
        kind = kinds[0] if kinds else "expected"
    evs = db.evals(v.bench, v.model)
    extra = c.select(
        "eval", [("", "All evals")] + [(e["eval"], e["title"]) for e in evs], name, "Eval"
    )
    if kinds:
        extra += c.select(
            "kind", [(k, LAYER_KINDS[k][0]) for k in kinds], kind, "Per-layer measure"
        )
    title, tag, tip = LAYER_KINDS[kind]
    colors = {r["run_id"]: c.SERIES[n % 8] for n, r in enumerate(shown)}
    legend = c.legend({"label": r["label"], "color": colors[r["run_id"]]} for r in shown)
    cards = []
    for e in evs:
        st = stats.get(e["eval"], {}).get(kind)
        if not st:
            continue
        series = [{"label": r["label"], "color": colors[r["run_id"]],
                   "points": st.get(r["run_id"], [])} for r in shown]  # fmt: skip
        href = url(f"/eval/{c.seg(e['eval'])}", **v.args())
        if name:
            cards.append(f'<div class="card wide"><h4>{esc(e["title"])}</h4>'
                         f"{c.line_chart(series, v.pct, 900, 320)}</div>")  # fmt: skip
        else:
            cards.append(f'<a class="card mini" href="{esc(url("/layers", **v.args(eval=e["eval"], kind=kind)))}">'
                         f'<h5>{esc(e["title"])}</h5>{c.line_chart(series, v.pct, 280, 130, True)}</a>')  # fmt: skip
        _ = href
    body = "".join(cards) or empty("No per-layer data for this selection.")
    return (
        nav(v, "layers")
        + controls(db, v, "/layers", extra)
        + f'<div class="page"><h2>{esc(title)} <span class="tag {tag}">{tag}</span></h2>'
        f'<p class="note">{esc(tip)}</p>{legend}<div class="grid-cards">{body}</div></div>'
    )


# ------------------------------------------------------------------ filter


def filter_page(db: Store, v: View, q: dict[str, str]) -> str:
    runs = db.runs(v.bench, v.model)
    if len(runs) < 1:
        return nav(v, "filter") + controls(db, v, "/filter", pick_runs=False) + empty("No runs.")
    ids = [r["run_id"] for r in runs]
    a = q.get("a") if q.get("a") in ids else ids[0]
    b = q.get("b") if q.get("b") in ids else (ids[1] if len(ids) > 1 else "")
    name = q.get("eval") or ""
    evs = db.evals(v.bench, v.model)
    titles = {e["eval"]: e["title"] for e in evs}
    run_opts = [(r["run_id"], f"{METHOD_TITLES.get(r['method'], '')} · {r['label']}") for r in runs]
    eval_sel = c.select(
        "eval", [("", "All evals")] + [(e["eval"], e["title"]) for e in evs], name, "Eval"
    )
    if v.pct:
        extra = (
            c.select("a", run_opts, a, "Higher on")
            + c.select("b", run_opts, b, "than on")
            + eval_sel
        )
        rows = db.score_diff(a, b, name or None) if b else []
        body = "".join(
            f'<tr><td>{esc(titles.get(r["eval"], r["eval"]))}</td><td class="id"><a href="'
            f'{esc(url(f"/q/{c.seg(r['eval'])}/{c.seg(r['item'])}", **v.args(runs=f"{a},{b}")))}">'
            f"{esc(r['item'])}</a></td><td>{c.fmt(r['a'], True)}</td><td>{c.fmt(r['b'], True)}</td>"
            f"<td><b>{100 * (r['a'] - r['b']):+.1f} pt</b></td></tr>"
            for r in rows
        )
        table = (
            '<table class="qlist"><thead><tr><th>Eval</th><th>Item</th><th>A</th><th>B</th>'
            f"<th>A minus B</th></tr></thead><tbody>{body}</tbody></table>"
        )
        note = ("HallucinationBench has no right / wrong per item. Items are ranked by the "
                "difference in their hallucination rate (all layers pooled) between two lenses.")  # fmt: skip
        return (
            nav(v, "filter") + controls(db, v, "/filter", extra, pick_runs=False)
            + f'<div class="page"><p class="note">{esc(note)}</p><div class="card">{table}</div></div>'
        )  # fmt: skip
    aw = q.get("aw") if q.get("aw") in dict(WANTS) else "right"
    bw = q.get("bw") if q.get("bw") in dict(WANTS) else "wrong"
    extra = (
        c.select("a", run_opts, a, "Method A") + c.select("aw", WANTS, aw, "is")
        + c.select("b", [("", "(no second condition)"), *run_opts], b, "and method B")
        + c.select("bw", WANTS, bw, "is") + eval_sel
    )  # fmt: skip
    preds = [(a, aw)] + ([(b, bw)] if b and b != a else [])
    hits = db.filter(v.bench, v.model, preds, name or None, v.subset)
    by_method: dict[str, dict] = {}
    for r in runs:
        by_method.setdefault(r["method"], r)
    presets = []
    ol = by_method.get("olens")
    for other in ("nla", "jlens", "logit_lens"):
        if ol and other in by_method:
            o = by_method[other]
            href = url("/filter", **v.args(a=ol["run_id"], aw="right", b=o["run_id"], bw="wrong"))
            presets.append(
                f'<a class="chip" href="{esc(href)}">O-lens right, {METHOD_TITLES[other]} wrong</a>'
            )
            href = url("/filter", **v.args(a=ol["run_id"], aw="wrong", b=o["run_id"], bw="right"))
            presets.append(
                f'<a class="chip" href="{esc(href)}">O-lens wrong, {METHOD_TITLES[other]} right</a>'
            )
    if not presets and len(runs) > 1:
        href = url("/filter", **v.args(a=ids[0], aw="right", b=ids[1], bw="wrong"))
        presets.append(f'<a class="chip" href="{esc(href)}">first right, second wrong</a>')
    groups: dict[str, list[dict]] = {}
    for h in hits:
        groups.setdefault(h["eval"], []).append(h)
    open_runs = ",".join(dict.fromkeys(p[0] for p in preds))
    cards = []
    for ev, rows in groups.items():
        links = "".join(
            f'<a class="qchip" href="{esc(url(f"/q/{c.seg(ev)}/{c.seg(r['item'])}", **v.args(runs=open_runs)))}">'
            f"{esc(r['item'])}<small>{esc(', '.join(map(str, r['expected']))[:40])}</small></a>"
            for r in rows
        )
        cards.append(f'<div class="card"><h4>{esc(titles.get(ev, ev))} <span class="hint">{len(rows)}'
                     f' questions</span></h4><div class="qchips">{links}</div></div>')  # fmt: skip
    summary = f"{len(hits)} questions in {len(groups)} evals"
    return (
        nav(v, "filter")
        + controls(db, v, "/filter", extra, pick_runs=False)
        + f'<div class="page"><div class="presets">{"".join(presets)}</div>'
        f'<p class="note">{esc(summary)} · uses the judge\'s item-level verdicts only</p>'
        f"{''.join(cards) or empty('No question matches.')}</div>"
    )


# ------------------------------------------------------------------ search and bookmarks


def search_page(db: Store, v: View, q: dict[str, str]) -> str:
    text = (q.get("q") or "").strip()
    name = q.get("eval") or ""
    evs = db.evals(v.bench, v.model)
    titles = {e["eval"]: e["title"] for e in evs}
    extra = (
        f'<label class="sel grow"><span>Search readouts</span><input type="search" name="q" '
        f'value="{esc(text)}" placeholder="a word or exact phrase" autofocus></label>'
        + c.select(
            "eval", [("", "All evals")] + [(e["eval"], e["title"]) for e in evs], name, "Eval"
        )
        + '<button class="btn" type="submit">Search</button>'
    )
    hits = db.search(text, v.bench, v.model, v.runs or None, name or None) if text else []
    rows = "".join(
        f'<a class="hit" href="'
        f'{esc(url(f"/q/{c.seg(h['eval'])}/{c.seg(h['item'])}", **v.args(runs=h["run_id"], l=h["layer"], p=h["pos"], find=text)))}">'
        f'<div class="hit-meta">{c.method_dot(h["method"])}<b>{esc(c.short_label(h["label"], 34))}</b>'
        f"<span>{esc(titles.get(h['eval'], h['eval']))}</span><span>{esc(h['item'])}</span>"
        f"<span>L{h['layer']} · pos {h['pos']}</span></div>"
        f'<div class="hit-text">…{esc(h["pre"])}<mark>{esc(h["hit"])}</mark>{esc(h["post"])}…</div></a>'
        for h in hits
    )
    msg = f"{len(hits)} cells (up to 60 per method)" if text else "Type a word or phrase."
    return (
        nav(v, "search")
        + controls(db, v, "/search", extra)
        + f'<div class="page"><p class="note">{esc(msg)}</p>{rows}</div>'
    )


def bookmarks_page(db: Store, v: View) -> str:
    rows = []
    for b in db.bookmarks():
        if db.is_hidden(b["bench"], b["model"], b["eval"], b["item"]):
            continue
        vv = View(b["bench"], b["model"])
        href = url(f"/q/{c.seg(b['eval'])}/{c.seg(b['item'])}", **vv.args(
            runs=b["run_id"], l=b["layer"], p=b["pos"]))  # fmt: skip
        where = f"L{b['layer']} · pos {b['pos']}" if b["layer"] is not None else "whole question"
        rows.append(
            f"<tr><td>{esc(BENCH_TITLES.get(b['bench'], b['bench']))}</td><td>{esc(b['eval'])}</td>"
            f'<td class="id"><a href="{esc(href)}">{esc(b["item"])}</a></td><td>{esc(where)}</td>'
            f'<td>{esc(b["note"])}</td><td><form method="post" action="/bookmarks/delete">'
            f'<input type="hidden" name="id" value="{b["id"]}"><button class="btn sm">remove</button>'
            f"</form></td></tr>"
        )
    table = (
        '<table class="qlist"><thead><tr><th>Bench</th><th>Eval</th><th>Question</th><th>Where</th>'
        f"<th>Note</th><th></th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        if rows else empty("No bookmarks yet. Press b on a question page.")
    )  # fmt: skip
    return (
        nav(v, "bookmarks")
        + f'<div class="page"><h2>Bookmarks</h2><div class="card">{table}</div></div>'
    )
