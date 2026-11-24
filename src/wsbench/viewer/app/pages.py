"""The pages, as HTML strings built from store queries. Each function takes the opened store
and the request's view (bench, model, subset, chosen runs) and returns a page body."""

import json
from dataclasses import dataclass, field, replace
from typing import Any

from wsbench.viewer import meta
from wsbench.viewer.app import components as c
from wsbench.viewer.app.components import esc, url
from wsbench.viewer.query import (
    BENCH_TITLES,
    CORE,
    DERIVED,
    EARLIER_FAST,
    FAST,
    LUCKY_NOTE,
    MACRO,
    METHOD_TITLES,
    SCORED_BY_RULE,
    Store,
    gate_cards,
    is_earlier_fast,
    scored_by,
)
from wsbench.viewer.store import JOINT_LAYER

SUMMARIZER_NOTE = (
    "In summary mode the readouts of every eval, the rule-scored ones included, first pass "
    "through the Claude summarizer."
)
FLOORS = (
    ("prompt_only", "Prompt only"),
    ("lucky_guess", "Lucky guess (options only)"),
    ("chance", "Chance"),
)
FLOOR_HELP = {"lucky_guess": LUCKY_NOTE}  # a floor column's heading, on hover
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
           "Weighted share of claims that are hallucinated: the index row of each layer."),
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
    cat: str = ""  # the score table's category filter, "" = every category

    def args(self, **extra: Any) -> dict[str, Any]:
        base = {"bench": self.bench, "model": self.model}
        if self.subset != self.default_subset:
            base["subset"] = self.subset
        if self.runs:
            base["runs"] = ",".join(self.runs)
        return base | extra

    def home(self, **extra: Any) -> dict[str, Any]:
        """The score table's link parameters: ``args`` plus the category filter."""
        return self.args(**({"cat": self.cat} | extra))

    @property
    def pct(self) -> bool:
        return self.bench == "hb"


def make_view(db: Store, q: dict[str, str]) -> View:
    benches = db.benches()
    bench = q.get("bench") if q.get("bench") in benches else (benches[0] if benches else "wsb")
    models = [m["model"] for m in db.models(bench)]
    model = q.get("model") if q.get("model") in models else (models[0] if models else "")
    subsets = db.subsets(bench, model)
    # the core set is the bench's default; a store without it opens on the first set it has
    default = CORE if CORE in subsets else "full" if "full" in subsets else subsets[0]
    subset = q.get("subset") if q.get("subset") in subsets else default
    if q.get("subset") == FAST and FAST not in subsets and EARLIER_FAST in subsets:
        subset = EARLIER_FAST  # the store's fast rows are an earlier subset's: shown as that
    runs = [r for r in (q.get("runs") or "").split(",") if r]
    return View(bench, model, subset, runs, default, q.get("cat") or "")


def chosen_runs(db: Store, v: View) -> tuple[list[dict], list[dict]]:
    """``(shown, all)`` runs of the view."""
    runs = db.runs(v.bench, v.model)
    if v.runs:
        shown = [r for r in runs if r["run_id"] in v.runs]
    else:  # the lenses the alias file marks `"default": true`, else the first run of each method
        first: dict[str, dict] = {}
        for r in runs:
            first.setdefault(meta.method_key(r["method"]), r)
        shown = one_per_lens(db, v, [r for r in runs if r.get("default")]) or list(first.values())
    return shown, runs


def one_per_lens(db: Store, v: View, runs: list[dict]) -> list[dict]:
    """Of the default runs, one per lens: a lens with several runs in the store is shown by the
    run that has scores in the view's set, then the one with a full set, then the one with the
    most evals in the view's set, then the newest. The others stay in the run chooser."""
    sets = db.run_subsets(v.bench, v.model)
    look = "full" if v.subset == CORE else v.subset

    def rank(r: dict) -> tuple:
        have = sets.get(r["run_id"], {})
        return (look in have, "full" in have, have.get(look, 0), r.get("ingested_at") or 0)

    best: dict[str, dict] = {}
    for r in runs:
        if r["lens"] not in best or rank(r) > rank(best[r["lens"]]):
            best[r["lens"]] = r
    keep = {r["run_id"] for r in best.values()}
    return [r for r in runs if r["run_id"] in keep]


def styles(shown: list[dict]) -> dict[str, dict[str, str]]:
    """Each shown run's colour and dash: its method's colour, shaded per run of that method."""
    return meta.run_styles(shown)


def integrity_tag(r: dict) -> str:
    """The run's integrity label (partial, provisional, ...) where the store has one."""
    if not r.get("integrity"):
        return ""
    reason = r.get("integrity_reason") or ""
    return f'<span class="tag integ" title="{esc(reason)}">{esc(r["integrity"])}</span>'


NOT_RUN = "This lens's run has no readouts or judged results for this eval."


def lens_chip(r: dict, style: dict[str, str] | None = None, derived: str | None = None) -> str:
    """A lens's short label with its method chip; the full id on hover and, with its
    description, in a popover. ``style`` is the run's line sample; ``derived`` (the store's
    note on how) adds the words that its scores in this set come from the full run."""
    mark = c.swatch(style) if style else c.method_dot(r["method"])
    desc = r.get("description") or "No description yet: add one to lens_aliases.json in the store."
    reason = r.get("integrity_reason")
    integ = (
        f"<p><b>{esc(r['integrity'])}</b>{': ' + esc(reason) if reason else ''}</p>"
        if r.get("integrity") else ""
    )  # fmt: skip
    tags = c.method_chip(r["method"]) + integrity_tag(r)
    if derived is not None:
        tags += f'<span class="tag derived" title="{esc(derived)}">{DERIVED}</span>'
    return (
        f'<details class="lens"><summary title="{esc(r["lens"])}">{mark}'
        f'<span>{esc(r["label"])}</span></summary><div class="lens-pop"><b>{esc(r["label"])}</b>'
        f"<code>{esc(r['lens'])}</code><p>{esc(desc)}</p>{integ}"
        f"<small>{esc(METHOD_TITLES.get(r['method'], r['method']))} · judge "
        f"{esc(r.get('judge') or '?')} · {esc(r.get('mode') or '')}</small></div></details>"
        f'<div class="lens-tags">{tags}</div>'
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
    subsets = [(s, db.title(v.bench, v.model, s)) for s in db.subsets(v.bench, v.model)]
    parts = [
        c.select("bench", benches, v.bench, "Bench"),
        c.select("model", models, v.model, "Subject model"),
    ]
    if len(subsets) > 1:
        parts.append(c.select("subset", subsets, v.subset, "Set"))
    if pick_runs:
        shown, runs = chosen_runs(db, v)
        ids = {r["run_id"] for r in shown}
        if len(runs) > 1:
            boxes = "".join(
                f'<label>{c.method_dot(r["method"])}<input type="checkbox" value="{esc(r["run_id"])}"'
                f"{' checked' if r['run_id'] in ids else ''}> {esc(r['label'])}"
                f"{integrity_tag(r)}"
                f"<small>{esc(r['lens']) if r['lens'] != r['label'] else ''}</small></label>"
                for r in runs
            )
            parts.append(
                f'<details class="pick"><summary>Runs <b>{len(shown)}/{len(runs)}</b></summary>'
                f'<div class="pick-menu" data-runs>{boxes}<button type="button" class="btn"'
                f' onclick="applyRuns(this)">Apply</button></div></details>'
                f'<input type="hidden" name="runs" value="{esc(",".join(v.runs))}">'
            )
    if v.cat and path == "/":
        parts.append(f'<input type="hidden" name="cat" value="{esc(v.cat)}">')
    return (
        f'<form class="controls" method="get" action="{esc(path)}">{"".join(parts)}{extra}</form>'
    )


def nav(v: View, active: str) -> str:
    links = (("scores", "/"), ("layers", "/layers"), ("filter", "/filter"), ("search", "/search"),
             ("runs", "/runs"), ("bookmarks", "/bookmarks"))  # fmt: skip
    items = "".join(
        f'<a href="{esc(url(href, **v.args()))}"{" class=on" if name == active else ""}>'
        f"{name.capitalize()}</a>"
        for name, href in links
    )
    return (
        f'<header class="top"><a class="brand" href="/">Bench viewer</a><nav>{items}</nav></header>'
        f"<style>{meta.palette_css()}</style>"
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

SET_NOTES = {
    CORE: "The core set: the evals a method is reported on, each on its whole question set, "
    "with the core macro. Same verdicts as the full set.",
    "full": "Pass rate with 95% CI. Dimmed floors were measured with another judge prompt version.",
    "fast": "The current fast subset: its frozen questions only. Not comparable with the full "
    "set's column: different question set.",
    "fast-safety": "An earlier fast subset with jailbreak recognition and agentic misalignment "
    "added. The fast subset no longer has this variant: it is shown for the runs that were "
    "scored on it. Not comparable with the Fast set or the full set's column.",
    "ati": "Only questions that text-only readers could not solve from the prompt.",
}
EARLIER_FAST_NOTE = (
    "Runs scored on an earlier fast subset: another selection of questions than the current "
    "fast subset has. Not comparable with the Fast set or the full set's column."
)


def set_note(subset: str) -> str:
    """One line on what a set is; an earlier fast subset is never described as the current."""
    if subset in SET_NOTES:
        return SET_NOTES[subset]
    return EARLIER_FAST_NOTE if is_earlier_fast(subset) else ""


def category_nav(v: View, groups: list[dict], shown: dict[str, int]) -> str:
    """The categories as links that filter the score table; the count is the evals listed."""
    total = len({e["eval"] for g in groups for e in g["evals"] if e["eval"] in shown})
    links = [
        f'<a class="chip{"" if v.cat else " on"}" href="{esc(url("/", **v.home(cat="")))}">All'
        f"<small>{total}</small></a>"
    ]
    for g in groups:
        n = sum(1 for e in g["evals"] if e["eval"] in shown)
        if not n:
            continue
        on = " on" if v.cat == g["key"] else ""
        links.append(
            f'<a class="chip{on}" href="{esc(url("/", **v.home(cat=g["key"])))}">{esc(g["title"])}'
            f"<small>{n}</small></a>"
        )
    return f'<nav class="cats" aria-label="Categories">{"".join(links)}</nav>'


def hb_families(db: Store, v: View) -> str:
    """HallucinationBench's index families: weight, what each tests, prompts in the store."""
    stored = {e["eval"]: e for e in db.evals(v.bench, v.model)}
    total = sum(meta.HB_FAMILY_WEIGHTS.values())
    rows = []
    names = list(meta.HB_EVALS) + [n for n in stored if n not in meta.HB_EVALS]
    for name in names:
        e = stored.get(name)
        title, _grp, _dir, _key, what, _judged = meta.HB_EVALS.get(name, (name, "", "", "", "", ""))
        w = meta.HB_FAMILY_WEIGHTS.get(name)
        weight = f"{w:g} of {total:g}" if w is not None else "—"
        if e:
            href = url(f"/eval/{c.seg(name)}", **v.args())
            head = f'<a href="{esc(href)}">{esc(e["title"])}</a>'
            prompts = esc(e["n_items"] if e["n_items"] else "—")
        else:
            head = esc(title)
            prompts = '<span class="hint">no data in this store</span>'
        rows.append(
            f'<tr><td class="fam">{head}<small><code>{esc(name)}</code></small></td>'
            f'<td class="num">{esc(weight)}</td>'
            f"<td>{c.inline_md((e or {}).get('what') or what)}</td>"
            f'<td class="by">{esc(scored_by(v.bench, name))}</td>'
            f'<td class="num">{prompts}</td></tr>'
        )
    return (
        '<div class="card" id="families"><h4>Families of the index</h4><div class="tablewrap">'
        '<table class="plain"><thead><tr><th>Family</th><th class="num">Weight in the index</th>'
        '<th>What it tests</th><th class="by">Scored by</th><th class="num">Prompts</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def hb_index_cards(db: Store, v: View, shown: list[dict], runs: list[dict]) -> str:
    """The HallucinationBench index as the runs' own index files have it: per run, one row per
    layer and the joint row, one column per family and per macro. The shown runs that have
    index rows; when none of them has, every run of the store that does."""
    have = [(r, db.hb_index(r["run_id"])) for r in shown]
    have = [(r, rows) for r, rows in have if rows]
    if not have:
        have = [(r, rows) for r in runs if (rows := db.hb_index(r["run_id"]))]
    stored = {e["eval"]: e["title"] for e in db.evals(v.bench, v.model)}
    cards = []
    for r, rows in have:
        fams = [
            k for k in meta.HB_EVALS if any(x["key"] == k and x["kind"] == "family" for x in rows)
        ]
        fams += sorted({x["key"] for x in rows if x["kind"] == "family"} - set(fams))
        macros = sorted({x["key"] for x in rows if x["kind"] != "family"})
        at = {(x["layer"], x["kind"] == "family", x["key"]): x for x in rows}
        layers = sorted({x["layer"] for x in rows}, key=lambda n: (n != JOINT_LAYER, n))
        cols = [(True, k) for k in fams] + [(False, k) for k in macros]

        def cell(x: dict | None) -> str:
            if not x or x.get("value") is None:
                return '<td class="num none">—</td>'
            ci = ""
            if x.get("ci_lo") is not None and x.get("ci_hi") is not None:
                ci = f"<small>[{c.fmt(x['ci_lo'], True)}, {c.fmt(x['ci_hi'], True)}]</small>"
            n = f"<small>n={x['n']}</small>" if x.get("n") is not None else ""
            return f'<td class="num"><b>{c.fmt(x["value"], True)}</b>{ci}{n}</td>'

        head = "".join(
            f'<th class="num">{esc(stored.get(k) or meta.HB_EVALS.get(k, (k,))[0])}'
            f"{'' if fam else ' (macro)'}</th>"
            for fam, k in cols
        )
        body = "".join(
            f"<tr{' class=macro' if layer == JOINT_LAYER else ''}><td>"
            f"{'joint (all layers)' if layer == JOINT_LAYER else f'L{layer}'}</td>"
            + "".join(cell(at.get((layer, fam, k))) for fam, k in cols)
            + "</tr>"
            for layer in layers
        )
        missing = [meta.HB_EVALS[k][0] for k in meta.HB_EVALS if k not in fams]
        none = (
            f'<p class="hint">No index rows in this store for: {esc(", ".join(missing))}.</p>'
            if missing else ""
        )  # fmt: skip
        cards.append(
            f'<div class="card"><h4>Index rows <span class="hint">{c.method_chip(r["method"])} '
            f"{esc(r['label'])} {integrity_tag(r)} · hallucination rate, 95% CI, n claims</span></h4>"
            f'<div class="tablewrap"><table class="plain layers"><thead><tr><th>Layer</th>{head}'
            f"</tr></thead><tbody>{body}</tbody></table></div>{none}</div>"
        )
    return "".join(cards)


def hb_taxonomy() -> str:
    """The claim-map taxonomy: every leaf under its verdict, in the readout view's colours."""
    blocks = []
    for verdict, (title, what, leaves) in meta.HB_VERDICTS.items():
        rows = "".join(
            f'<tr><td><span class="lchip leaf-{leaf}">{esc(name)}</span></td>'
            f"<td><code>{esc(leaf)}</code></td><td>{esc(text)}</td>"
            f'<td class="num">{meta.HB_MAIN_LEAF_WEIGHTS.get(leaf, 0):g}</td></tr>'
            for leaf, name, _shade, text in leaves
        )
        blocks.append(
            f'<tbody><tr class="vrow"><td colspan="4"><i class="vdot" style="background:'
            f'{meta.HB_VERDICT_INK[verdict]}"></i><b>{esc(title)}</b> <span class="hint">{esc(what)}'
            f"</span></td></tr>{rows}</tbody>"
        )
    story = ", ".join(f"{k} {w:g}" for k, w in meta.HB_STORY_LEAF_WEIGHTS.items())
    return (
        '<div class="card" id="taxonomy"><h4>Taxonomy of the claim map</h4>'
        '<p class="hint">Every segment of a readout gets one leaf; the leaves are grouped under '
        "six verdicts, with failed judge calls apart. The weight is what a segment of that leaf adds to the main family's "
        f"score. The story family weighs: {esc(story)}.</p>"
        '<div class="tablewrap"><table class="plain taxo"><thead><tr><th>Leaf</th><th>Id</th>'
        '<th>Meaning</th><th class="num">Weight</th></tr></thead>'
        f"{''.join(blocks)}</table></div></div>"
    )


def scores_page(db: Store, v: View) -> str:
    shown, runs = chosen_runs(db, v)
    scores = db.scores(v.bench, v.model, v.subset)
    groups = db.groups(v.bench, v.model)
    counts = db.subset_counts(v.bench, v.model, v.subset)
    derived = db.derived_runs(v.bench, v.model, v.subset)
    floors = [(k, t) for k, t in FLOORS if any(k in s for s in scores.values())]
    top = 1.0
    if v.pct:
        vals = [
            s["value"] for e in scores.values() for s in e.values() if s.get("value") is not None
        ]
        top = max([*vals, 0.01]) * 1.15

    scored_runs = {k for sc in scores.values() for k in sc}
    core_evals = db._core(v.bench)

    def eval_link(e: dict) -> str:
        return url(f"/eval/{c.seg(e['eval'])}", **v.args())

    paint = styles(shown)
    all_derived = bool(shown) and all(r["run_id"] in derived for r in shown)
    marks = db.eval_marks(v.bench, v.model)
    head = "".join(
        f'<th class="run">'
        f"{lens_chip(r, paint[r['run_id']], None if all_derived else derived.get(r['run_id']))}"
        "</th>"
        for r in shown
    ) + "".join(
        f'<th class="run floor" title="{esc(FLOOR_HELP.get(k, ""))}"><span>{esc(t)}</span></th>'
        for k, t in floors
    )
    rows = []
    macro = scores.get(MACRO)
    span = 3 + len(shown) + len(floors)
    if macro and not v.cat:
        cells = "".join(
            c.score_cell(macro.get(r["run_id"]), "", v.pct, top, paint[r["run_id"]]["color"])
            for r in shown
        )
        cells += "".join('<td class="sc none"></td>' for _ in floors)
        # the eval count of the first shown run that has a macro; each cell's own is on hover
        n = next(
            (macro[r["run_id"]]["n"] for r in shown if (macro.get(r["run_id"]) or {}).get("n")), ""
        )
        rows.append(
            f'<tr class="macro"><td class="name"><b>Macro</b><small>mean over evals in this '
            f'set</small></td><td class="by"></td><td class="n">{esc(n)} evals</td>{cells}</tr>'
        )
    # a set other than the full one lists the evals it has scores for; the full set lists all
    listed = {
        e["eval"]: 1
        for g in groups
        for e in g["evals"]
        if v.subset == "full"
        or e["eval"] in scores
        or (v.subset == CORE and e["eval"] in core_evals)
    }
    if v.cat and v.cat not in {g["key"] for g in groups}:
        v.cat = ""
    side = []
    for g in groups:
        evs = [e for e in g["evals"] if e["eval"] in listed]
        if not evs:
            continue
        gid = "g-" + c.seg(g["key"])
        href = url("/", **v.home(cat=g["key"]))
        side.append(
            f'<details open><summary><a href="{esc(href)}"{" class=on" if v.cat == g["key"] else ""}>'
            f"{esc(g['title'])}</a><small>{len(evs)}</small></summary>"
            + "".join(f'<a href="{esc(eval_link(e))}">{esc(e["title"])}</a>' for e in evs)
            + "</details>"
        )
        if v.cat and v.cat != g["key"]:
            continue
        rows.append(
            f'<tr class="grp" id="{esc(gid)}"><td colspan="{span}">'
            f"{esc(g['title'])}<small>{len(evs)} evals</small></td></tr>"
        )
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
                c.score_cell(
                    sc[r["run_id"]],
                    "",
                    v.pct,
                    top,
                    paint[r["run_id"]]["color"],
                    marks.get(r["run_id"], {}).get(e["eval"]),
                )
                if r["run_id"] in sc
                else c.not_run(why)
                if r["run_id"] in scored_runs
                else '<td class="sc none">—</td>'
                for r in shown
            )
            cells += "".join(c.score_cell(sc.get(k), "floor", v.pct, top) for k, _t in floors)
            goal = meta.first_sentence(e["what"] or "", 150)
            also = (
                f'<small class="also">also listed under {esc(e["also_in"])}</small>'
                if e.get("also_in") else ""
            )  # fmt: skip
            by = e["scored_by"]
            rows.append(
                f'<tr><td class="name"><a href="{esc(eval_link(e))}">'
                f"{esc(e['title'])}</a>{also}<small>{c.inline_md(goal)}</small></td>"
                f'<td class="by{" rule" if by == SCORED_BY_RULE else ""}">{esc(by or "—")}</td>'
                f'<td class="n">{esc(n or "—")}</td>{cells}</tr>'
            )
    if not rows:
        table = empty("No evals for this bench and model yet. Run `wsbench viewer ingest`.")
    else:
        table = (
            '<div class="tablewrap"><table class="scores"><thead><tr><th>Eval</th>'
            f'<th class="by">Scored by</th><th class="n">Questions</th>{head}'
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
    if v.bench == "hb":
        note = "Hallucination rate, lower is better. Headline = mean over the judged layers."
    elif not runs:
        note = "No runs ingested for this model: the table lists its question set only."
    else:
        note = set_note(v.subset)
    set_line = f"<b>{esc(db.title(v.bench, v.model, v.subset))}</b> set"
    if all_derived:
        notes = sorted({derived[r["run_id"]] for r in shown})
        set_line += f' <span class="tag derived" title="{esc("; ".join(notes))}">{DERIVED}</span>'
    extra = ""
    if v.bench == "hb":
        extra = hb_index_cards(db, v, shown, runs) + hb_families(db, v) + hb_taxonomy()
    summ = f" {SUMMARIZER_NOTE}" if v.bench == "wsb" and runs else ""
    return (
        nav(v, "scores")
        + controls(db, v, "/")
        + f'<div class="layout"><aside class="side">{"".join(side)}</aside><main>'
        f"{category_nav(v, groups, listed)}"
        f'<p class="note">{set_line} · {esc(note)}{esc(summ)}</p>'
        f"{c.method_legend(r['method'] for r in shown)}{table}{extra}</main></div>"
    )


# ------------------------------------------------------------------ one eval


def layer_rows(
    db: Store, v: View, name: str, shown: list[dict], paint: dict, headline: dict
) -> str:
    """The stored per-layer score rows of one eval (HallucinationBench: the index row of each
    layer), one column per shown run, with the headline row first."""
    per_layer = db.layer_scores(v.bench, v.model, name, v.subset)
    joint: dict[str, dict] = {}
    if v.bench == "hb":  # a run's own index rows win; the joint row exists only there
        for r in shown:
            for row in db.hb_index(r["run_id"]):
                if row["key"] != name or row["kind"] != "family":
                    continue
                if row["layer"] == JOINT_LAYER:
                    joint[r["run_id"]] = row
                else:
                    per_layer.setdefault(row["layer"], {})[r["run_id"]] = row
    if not per_layer and not joint:
        return ""

    def cell(s: dict | None) -> str:
        if not s or s.get("value") is None:
            return '<td class="num none">—</td>'
        ci = ""
        if s.get("ci_lo") is not None and s.get("ci_hi") is not None:
            ci = f"<small>[{c.fmt(s['ci_lo'], v.pct)}, {c.fmt(s['ci_hi'], v.pct)}]</small>"
        n = f"<small>n={s['n']}</small>" if s.get("n") is not None else ""
        return f'<td class="num" title="{esc(s.get("note") or "")}"><b>{c.fmt(s["value"], v.pct)}</b>{ci}{n}</td>'

    head = "".join(
        f'<th class="num" title="{esc(r["lens"])}">{c.swatch(paint[r["run_id"]])}'
        f"{esc(c.short_label(r['label'], 22))}</th>"
        for r in shown
    )
    rows = [
        '<tr class="macro"><td>headline</td>'
        + "".join(cell(headline.get(r["run_id"])) for r in shown)
        + "</tr>"
    ]
    if joint:
        rows.append(
            "<tr><td>joint (all layers)</td>"
            + "".join(cell(joint.get(r["run_id"])) for r in shown)
            + "</tr>"
        )
    for layer, by_run in sorted(per_layer.items()):
        if not any(r["run_id"] in by_run for r in shown):
            continue  # a layer only other runs were judged at
        rows.append(
            f"<tr><td>L{layer}</td>"
            + "".join(cell(by_run.get(r["run_id"])) for r in shown)
            + "</tr>"
        )
    title = "Index rows per layer" if v.bench == "hb" else "Score rows per layer"
    return (
        f'<div class="card"><h4>{title} <span class="hint">value, 95% CI, n</span></h4>'
        f'<div class="tablewrap"><table class="plain layers"><thead><tr><th>Layer</th>{head}</tr>'
        f"</thead><tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def eval_page(db: Store, v: View, name: str, want: str = "") -> str:
    e = db.eval(v.bench, v.model, name)
    if e is None:
        return nav(v, "scores") + empty(f"No eval {name!r} for {v.model}.")
    shown, _runs = chosen_runs(db, v)
    scores = db.scores(v.bench, v.model, v.subset).get(name, {})
    items = db.items(v.bench, v.model, name, v.subset)
    paint = styles(shown)
    derived = db.derived_runs(v.bench, v.model, v.subset)
    bars = []
    for r in shown:
        s = scores.get(r["run_id"])
        if s:
            bars.append({"label": c.short_label(r["label"], 28), "value": s["value"],
                         "lo": s["ci_lo"], "hi": s["ci_hi"],
                         "color": paint[r["run_id"]]["color"], "kind": "lens"})  # fmt: skip
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
            paint[r["run_id"]]
            | {"label": c.short_label(r["label"], 28), "points": stats[kind].get(r["run_id"], [])}
            for r in shown
        ]
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
    by = e["scored_by"]
    summ = f'<p class="hint">{esc(SUMMARIZER_NOTE)}</p>' if v.bench == "wsb" else ""
    cats = [g["title"] for g in db.groups(v.bench, v.model)
            if any(x["eval"] == name and x.get("also_in") for x in g["evals"])]  # fmt: skip
    also = f' <span class="hint">also listed under {esc(", ".join(cats))}</span>' if cats else ""
    left = (
        f'<div class="card info"><div class="grp-tag">{esc(e["grp"])}{also}</div>'
        f"<h2>{esc(e['title'])}</h2>"
        f'<div class="facts"><span><b>{len(items) or e["n_items"]}</b> questions</span>'
        f"<span>metric <b>{esc(e['metric'] or 'pass_rate')}</b></span>"
        f"<span>{'lower' if e['higher_is_better'] == 0 else 'higher'} is better</span>"
        f"<span>scored by <b>{esc(by or '—')}</b></span></div>"
        f'<div class="block"><h4>What it tests</h4><p>{c.inline_md(e["what"] or "—")}</p></div>'
        f'{example}<div class="block judged"><h4>How it is judged</h4>'
        f'<p class="by-line">Scored by: <b>{esc(by or "—")}</b></p>'
        f"<p>{c.inline_md(e['judged_by'] or '—')}</p>{summ}{template}</div>"
        f'<div class="block"><h4>Gates</h4><div class="gates">{gates_html or "—"}</div></div></div>'
    )
    notes = sorted({derived[r["run_id"]] for r in shown if r["run_id"] in derived})
    tag = (
        f' <span class="tag derived" title="{esc("; ".join(notes))}">{DERIVED}</span>'
        if notes else ""
    )  # fmt: skip
    marked = [(r, db.eval_marks(v.bench, v.model).get(r["run_id"], {}).get(name)) for r in shown]
    mark_lines = "".join(
        f'<p class="markline">{c.swatch(paint[r["run_id"]])}{esc(r["label"])} '
        f"{c.eval_mark(m)} <span>{esc(m[1])}</span></p>"
        for r, m in marked if m
    )  # fmt: skip
    right = (
        f'<div class="card"><h4>Scores <span class="hint">'
        f"{esc(db.title(v.bench, v.model, v.subset))} set, "
        f"95% CI</span>{tag}</h4>{c.bar_chart(bars, v.pct) or empty('no scores ingested')}"
        f"{c.method_legend(r['method'] for r in shown)}{mark_lines}</div>{layer_html}"
        f"{layer_rows(db, v, name, shown, paint, scores)}"
    )

    # the question list, with a per-method verdict and quick filters
    run_head = "".join(
        f'<th title="{esc(r["lens"])}">{c.swatch(paint[r["run_id"]])}<span>{esc(r["label"])}</span>'
        f"{integrity_tag(r)}</th>"
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
    defaults, _all = chosen_runs(db, replace(v, runs=[]))
    items = db.items(v.bench, v.model, name, v.subset)
    if item not in {x["item"] for x in items}:
        items = db.items(v.bench, v.model, name, "full")
    ids = [x["item"] for x in items if db.private or not x["private"]]
    verdicts = next((x["runs"] for x in items if x["item"] == item), {})
    data = {
        "bench": v.bench, "model": v.model, "subset": v.subset, "eval": name,
        "evalTitle": e["title"], "pct": v.pct, "item": it, "ids": ids,
        "runs": [
            {"id": r["run_id"], "label": r["label"], "method": meta.method_key(r["method"]),
             "lens": r["lens"], "description": r["description"],
             "integrity": r["integrity"], "integrityReason": r["integrity_reason"],
             "pass": verdicts.get(r["run_id"], {}).get("pass"),
             "score": verdicts.get(r["run_id"], {}).get("score")}
            for r in runs
        ],
        "methods": {k: {"title": t, "alias": a, "color": col}
                    for k, (t, a, col) in meta.METHODS.items()},
        "leaves": meta.hb_leaves(),
        "verdicts": [{"id": k, "title": t, "what": w, "color": meta.HB_VERDICT_INK[k]}
                     for k, (t, w, _l) in meta.HB_VERDICTS.items()],
        "axes": list(meta.HB_SPAN_AXES),
        "scoredBy": e["scored_by"],
        "summaryNote": SUMMARIZER_NOTE if v.bench == "wsb" else "",
        # open every chosen run that has something on this question: the runs the score
        # table and the eval page show. `defaults` names the store's default runs, so panes
        # a reader chose earlier are kept only while those defaults are the same
        "open": ([r["run_id"] for r in shown if r["run_id"] in verdicts]
                 or [r["run_id"] for r in shown]),
        "defaults": ",".join(r["run_id"] for r in defaults),
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
    paint = styles(shown)
    legend = c.method_legend(r["method"] for r in shown) + c.legend(
        paint[r["run_id"]] | {"label": r["label"]} for r in shown
    )
    cards = []
    for e in evs:
        st = stats.get(e["eval"], {}).get(kind)
        if not st:
            continue
        series = [paint[r["run_id"]] | {"label": r["label"], "points": st.get(r["run_id"], [])}
                  for r in shown]  # fmt: skip
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
    run_opts = [
        (r["run_id"], f"{METHOD_TITLES[meta.method_key(r['method'])]} · {r['label']}") for r in runs
    ]
    by_id = {r["run_id"]: r for r in runs}

    def picked(*ids: str) -> str:
        """The compared runs, each with its method chip and integrity label."""
        chips = "".join(
            f'<span class="cmp">{c.method_chip(by_id[i]["method"])}<b>{esc(by_id[i]["label"])}</b>'
            f"{integrity_tag(by_id[i])}</span>"
            for i in dict.fromkeys(ids) if i in by_id
        )  # fmt: skip
        return f'<div class="compared">{chips}</div>'

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
            '<div class="tablewrap"><table class="qlist"><thead><tr><th>Eval</th><th>Item</th>'
            f"<th>A</th><th>B</th><th>A minus B</th></tr></thead><tbody>{body}</tbody></table></div>"
        )
        note = ("HallucinationBench has no right / wrong per item. Items are ranked by the "
                "difference in their hallucination rate (all layers pooled) between two lenses.")  # fmt: skip
        return (
            nav(v, "filter") + controls(db, v, "/filter", extra, pick_runs=False)
            + f'<div class="page">{picked(a, b)}<p class="note">{esc(note)}</p>'
            f'<div class="card">{table}</div></div>'
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
    for other in ("nla", "jlens", "logit_lens", "continuation"):
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
        + f'<div class="page">{picked(a, b)}<div class="presets">{"".join(presets)}</div>'
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


# ------------------------------------------------------------------ runs


def _dash(text: str = "—") -> str:
    return f'<td class="num none" data-v="">{text}</td>'


def _num(value: float | None, text: str, note: str = "") -> str:
    """A fact cell: the value for sorting and its text; a fact the store lacks is a dash.
    ``note`` is the run's own note on its timings and costs, shown on hover."""
    if value is None:
        return _dash()
    if note:
        return f'<td class="num noted" data-v="{value}" title="{esc(note)}">{esc(text)}</td>'
    return f'<td class="num" data-v="{value}">{esc(text)}</td>'


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    s = round(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def readouts_where(src: dict) -> tuple[str, str]:
    """``(short text, detail)``: where a run's readout text is. In the store itself, or in
    files that are local, cached, on a volume or missing."""
    states: dict[str, int] = {}
    for f in src.get("files") or []:
        states[f["state"]] = states.get(f["state"], 0) + 1
    parts = [f"{k} ({n})" if len(states) > 1 or n > 1 else k for k, n in states.items()]
    n_cells, n_text = src.get("n_cells") or 0, src.get("n_with_text") or 0
    if n_cells and n_text >= n_cells:
        parts.insert(0, "in the store")
    elif n_text:
        parts.insert(0, f"in the store ({n_text} of {n_cells} cells)")
    detail = "\n".join(f"{f['state']}: {f['path']}" for f in (src.get("files") or [])[:12])
    return (", ".join(parts) or "—"), detail


RUN_COLUMNS = (
    ("Bench and model", ""), ("Method", ""), ("Run", ""), ("Run name", ""), ("Sets", ""),
    ("Cells", "num"), ("GPU-hours to read", "num"), ("Read wall-clock", "num"),
    ("Judge calls", "num"), ("Judge wall-clock", "num"), ("Judge cost", "num"),
    ("Total cost", "num"), ("Total wall-clock", "num"), ("Engine", ""), ("Bench commit", ""),
    ("Integrity", ""), ("Readouts", ""),
)  # fmt: skip


def runs_page(db: Store, v: View) -> str:
    """Every run of the store, one row each, with the facts its result files gave ingest."""
    rows = []
    # the runs with facts first; within each part the store's order (bench, model, method)
    table_rows = sorted(db.runs_table(), key=lambda r: r.get("facts") is None)
    for r in table_rows:
        f = r.get("facts") or {}
        sets = "".join(
            f'<span class="setchip" title="{esc(x["note"])}">{esc(x["title"])}'
            + (f' <span class="tag derived">{DERIVED}</span>' if x["derived"] else "")
            + "</span>"
            for x in r["sets"]
        )
        commit = f.get("bench_commit") or ""
        # evals taken from an update entry were judged at that entry's bench commit
        later: dict[str, list[str]] = {}
        for name, ev in sorted(db.run_evals(r["run_id"]).items()):
            if ev["facts"].get("update_run"):
                at = str(ev["facts"].get("bench_commit") or "?").split(" ")[0][:8]
                later.setdefault(f"{at} (run {ev['facts']['update_run']})", []).append(name)
        also = "".join(f"; {', '.join(v)} judged at {k}" for k, v in later.items())
        tn = f.get("timing_note") or ""  # the manifest's own words on these numbers
        where, detail = readouts_where(r["readouts"])
        home = url("/", bench=r["bench"], model=r["model"], runs=r["run_id"])
        usd = lambda x: f"${x:,.0f}" if x >= 100 else f"${x:,.2f}"  # noqa: E731
        rows.append(
            f'<tr><td class="bm">{esc(BENCH_TITLES.get(r["bench"], r["bench"]))}'
            f"<small>{esc(r['model'])}</small></td>"
            f'<td data-v="{esc(r["method"])}">{c.method_chip(r["method"])}</td>'
            f'<td class="runname"><a href="{esc(home)}" title="{esc(r["lens"])}">{esc(r["label"])}</a>'
            f"</td><td>{esc(f.get('run_name') or '—')}</td>"
            f'<td class="sets">{sets or "—"}</td>'
            + _num(f.get("cells"), f"{f.get('cells') or 0:,}", tn)
            + _num(f.get("read_gpu_hours"), f"{f.get('read_gpu_hours') or 0:.2f}", tn)
            + _num(f.get("read_wall_seconds"), duration(f.get("read_wall_seconds")), tn)
            + _num(f.get("judge_calls"), f"{f.get('judge_calls') or 0:,}", tn)
            + _num(f.get("judge_wall_seconds"), duration(f.get("judge_wall_seconds")), tn)
            + _num(f.get("judge_usd"), usd(f.get("judge_usd") or 0), tn)
            + _num(f.get("total_usd"), usd(f.get("total_usd") or 0), tn)
            + _num(f.get("total_wall_seconds"), duration(f.get("total_wall_seconds")), tn)
            + f"<td>{esc(f.get('engine') or '—')}</td>"
            + (
                f'<td title="{esc(commit + also)}"><code>{esc(commit.split(" ")[0][:8])}</code>'
                + (f' <span class="tag derived">+{len(later)}</span>' if later else "")
                + "</td>"
                if commit
                else "<td>—</td>"
            )
            + f'<td class="integ-cell">{integrity_tag(r) or "—"}'
            f"<small>{esc(r.get('integrity_reason') or '')}</small></td>"
            f'<td title="{esc(detail)}">{esc(where)}</td></tr>'
        )
    head = "".join(
        f'<th class="{cls}" data-sort title="sort by this column">{esc(t)}</th>'
        for t, cls in RUN_COLUMNS
    )
    table = (
        f'<div class="tablewrap wide"><table class="plain runs" id="runs"><thead><tr>{head}</tr>'
        f"</thead><tbody>{''.join(rows)}</tbody></table></div>"
        if rows else empty("No runs in this store yet. Run `wsbench viewer ingest`.")
    )  # fmt: skip
    note = (
        "One row per run, those with recorded facts first. A dash means the run's result files hold no such number. A set marked "
        f"'{DERIVED}' was not judged as that set. Click a column heading to sort."
    )
    return (
        nav(v, "runs") + f'<div class="page wide"><h2>Runs</h2><p class="note">{esc(note)}</p>'
        f"{c.method_legend(r['method'] for r in table_rows)}"
        f'<div class="card">{table}</div></div>'
    )
