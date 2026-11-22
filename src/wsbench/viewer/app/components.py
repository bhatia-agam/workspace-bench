"""Small HTML builders shared by the pages: escaping, links, selects, score cells, inline SVG
charts and a minimal markdown renderer for README excerpts."""

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from wsbench.viewer.query import METHOD_TITLES

METHOD_CLASS = {"olens": "m-olens", "nla": "m-nla", "jlens": "m-jlens", "logit_lens": "m-logit"}
SERIES = ("#4f46e5", "#0d9488", "#d97706", "#9333ea", "#dc2626", "#0284c7", "#65a30d", "#64748b")


def esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def url(path: str, **params: Any) -> str:
    """A link that keeps only the parameters that are set."""
    q = {k: v for k, v in params.items() if v not in (None, "", [], False)}
    return path + ("?" + urlencode(q, doseq=True) if q else "")


def seg(text: str) -> str:
    return quote(str(text), safe="")


def select(name: str, options: Sequence[tuple[str, str]], value: str | None, label: str) -> str:
    opts = "".join(
        f'<option value="{esc(v)}"{" selected" if v == value else ""}>{esc(t)}</option>'
        for v, t in options
    )
    return (
        f'<label class="sel"><span>{esc(label)}</span>'
        f'<select name="{esc(name)}" onchange="this.form.requestSubmit()">{opts}</select></label>'
    )


def run_color(n: int) -> str:
    """The color of the n-th shown lens: its bars, chart series and column dot."""
    return SERIES[n % len(SERIES)]


def method_dot(method: str) -> str:
    title = METHOD_TITLES.get(method, method)
    return f'<i class="dot {METHOD_CLASS.get(method, "m-other")}" title="{esc(title)}"></i>'


def short_label(label: str, limit: int = 30) -> str:
    """A display label cut to fit a chart axis. Aliases are short already; an un-aliased name
    keeps its start and never gets a leading ellipsis."""
    return label if len(label) <= limit else label[: limit - 1] + "…"


def not_run(reason: str) -> str:
    """A cell for an eval this run has no score for, with the reason on hover."""
    return f'<td class="sc none why" title="{esc(reason)}">not run</td>'


def fmt(value: float | None, pct: bool = False) -> str:
    if value is None:
        return "—"
    # Every score is a rate, so show it as a percentage; `pct` forces it for values above 1.
    return f"{100 * value:.1f}%" if pct or 0 <= value <= 1 else f"{value:.2f}"


def score_cell(
    s: Mapping[str, Any] | None, cls: str = "", pct: bool = False, top: float = 1.0,
    color: str = "",
) -> str:  # fmt: skip
    """A number over a thin bar with its 95% CI whisker; ``top`` is the bar's full scale and
    ``color`` the bar's own color (one per lens column)."""
    if not s or s.get("value") is None:
        return '<td class="sc none">—</td>'
    v = s["value"]
    if v > 1.0 and top <= 1.0:  # a 1-10 grade rather than a rate
        top = 10.0
    w = max(0.0, min(1.0, v / top)) * 100
    ci = ""
    title = fmt(v, pct)
    if s.get("ci_lo") is not None and s.get("ci_hi") is not None:
        lo = max(0.0, min(1.0, s["ci_lo"] / top)) * 100
        hi = max(0.0, min(1.0, s["ci_hi"] / top)) * 100
        ci = f'<i class="ci" style="left:{lo:.1f}%;width:{max(hi - lo, 0.5):.1f}%"></i>'
        title += f"  95% CI [{fmt(s['ci_lo'], pct)}, {fmt(s['ci_hi'], pct)}]"
    if s.get("n") is not None:
        title += f"  n={s['n']}"
    if s.get("note"):
        title += f"  ·  {s['note']}"
    paint = f";background:{color}" if color else ""
    stale = " stale" if "different judge prompt" in (s.get("note") or "") else ""
    return (
        f'<td class="sc {cls}{stale}" title="{esc(title)}"><b>{fmt(v, pct)}</b>'
        f'<span class="bar"><i class="fill" style="width:{w:.1f}%{paint}"></i>{ci}</span></td>'
    )


def badge(passed: int | None, score: float | None = None) -> str:
    if passed == 1:
        return '<i class="v ok" title="right">✓</i>'
    if passed == 0:
        return '<i class="v no" title="wrong">✗</i>'
    if score is not None:
        return f'<i class="v num" title="score">{score:.2f}</i>'
    return '<i class="v un" title="no item-level verdict">·</i>'


def bar_chart(bars: Sequence[Mapping[str, Any]], pct: bool = False, width: int = 560) -> str:
    """Horizontal bars with CI whiskers: ``[{label, value, lo, hi, color, kind}]``."""
    if not bars:
        return ""
    row, pad_l, pad_r = 26, 190, 56
    top = max([b["value"] or 0 for b in bars] + [b.get("hi") or 0 for b in bars] + [1e-9])
    top = 1.0 if (not pct and top <= 1.0) else top * 1.1
    inner = width - pad_l - pad_r
    h = row * len(bars) + 22
    out = [f'<svg class="chart" viewBox="0 0 {width} {h}" role="img">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        x = pad_l + inner * t
        out.append(f'<line x1="{x:.1f}" y1="4" x2="{x:.1f}" y2="{h - 18}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{h - 5}" class="tick">{fmt(top * t, pct)}</text>')
    for n, b in enumerate(bars):
        y = 6 + n * row
        v = b["value"] or 0
        w = inner * v / top
        dash = ' stroke-dasharray="3 3" fill-opacity=".35"' if b.get("kind") != "lens" else ""
        out.append(f'<text x="{pad_l - 8}" y="{y + 13}" class="lab">{esc(b["label"])}</text>')
        out.append(
            f'<rect x="{pad_l}" y="{y + 3}" width="{max(w, 1):.1f}" height="14" rx="2"'
            f' fill="{b["color"]}" stroke="{b["color"]}"{dash}/>'
        )
        if b.get("lo") is not None and b.get("hi") is not None:
            x1, x2 = pad_l + inner * b["lo"] / top, pad_l + inner * b["hi"] / top
            out.append(
                f'<line x1="{x1:.1f}" y1="{y + 10}" x2="{x2:.1f}" y2="{y + 10}" class="err"/>'
            )
            for x in (x1, x2):
                out.append(
                    f'<line x1="{x:.1f}" y1="{y + 6}" x2="{x:.1f}" y2="{y + 14}" class="err"/>'
                )
        tx = pad_l + inner * max(v, b.get("hi") or 0) / top + 6
        out.append(f'<text x="{tx:.1f}" y="{y + 14}" class="val">{fmt(b["value"], pct)}</text>')
    out.append("</svg>")
    return "".join(out)


def line_chart(
    series: Sequence[Mapping[str, Any]], pct: bool = False, width: int = 560, height: int = 220,
    small: bool = False,
) -> str:  # fmt: skip
    """Per-layer lines: ``[{label, color, points: [(layer, rate, n)]}]``."""
    pts = [p for s in series for p in s["points"]]
    if not pts:
        return '<div class="empty">no per-layer data</div>'
    xs = sorted({p[0] for p in pts})
    top = max(p[1] for p in pts)
    top = 1.0 if (not pct and top <= 1.0) else max(top * 1.15, 1e-9)
    pl, pr, pt, pb = (30, 8, 8, 18) if small else (40, 12, 10, 24)
    iw, ih = width - pl - pr, height - pt - pb
    span = (xs[-1] - xs[0]) or 1

    def xy(layer: float, v: float) -> tuple[float, float]:
        return pl + iw * (layer - xs[0]) / span, pt + ih * (1 - v / top)

    out = [f'<svg class="chart{" small" if small else ""}" viewBox="0 0 {width} {height}">']
    for t in (0, 0.5, 1.0):
        y = pt + ih * (1 - t)
        out.append(f'<line x1="{pl}" y1="{y:.1f}" x2="{width - pr}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{pl - 5}" y="{y + 3:.1f}" class="tick r">{fmt(top * t, pct)}</text>')
    step = max(1, len(xs) // (6 if small else 12))
    for layer in xs[::step]:
        x, _ = xy(layer, 0)
        out.append(f'<text x="{x:.1f}" y="{height - 6}" class="tick">L{layer}</text>')
    for s in series:
        if not s["points"]:
            continue
        d = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
                     for i, (x, y) in enumerate(xy(p[0], p[1]) for p in s["points"]))  # fmt: skip
        out.append(f'<path d="{d}" fill="none" stroke="{s["color"]}" stroke-width="1.8"/>')
        if not small:
            for p in s["points"]:
                x, y = xy(p[0], p[1])
                tip = f"{s['label']} · L{p[0]} · {fmt(p[1], pct)} · n={p[2]}"
                out.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{s["color"]}">'
                    f"<title>{esc(tip)}</title></circle>"
                )
    out.append("</svg>")
    return "".join(out)


def legend(series: Iterable[Mapping[str, Any]]) -> str:
    items = "".join(
        f'<span><i style="background:{s["color"]}"></i>{esc(s["label"])}</span>' for s in series
    )
    return f'<div class="legend">{items}</div>'


def md(text: str) -> str:
    """Enough markdown for README excerpts: fenced code, headings, bullets, inline code, bold."""

    def inline(s: str) -> str:
        s = esc(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![*\w])\*([^*\s][^*]*)\*(?!\w)", r"<i>\1</i>", s)
        return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)

    out, para, code = [], [], None
    for line in text.split("\n"):
        if line.startswith("```"):
            if code is None:
                if para:
                    out.append(f"<p>{inline(' '.join(para))}</p>")
                    para = []
                code = []
            else:
                out.append(f"<pre>{esc(chr(10).join(code))}</pre>")
                code = None
        elif code is not None:
            code.append(line)
        elif not line.strip():
            if para:
                out.append(f"<p>{inline(' '.join(para))}</p>")
                para = []
        elif m := re.match(r"^(#{2,5}) (.+)$", line):
            if para:
                out.append(f"<p>{inline(' '.join(para))}</p>")
                para = []
            out.append(f"<h5>{inline(m.group(2))}</h5>")
        else:
            para.append(line.strip())
    if code is not None:
        out.append(f"<pre>{esc(chr(10).join(code))}</pre>")
    if para:
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "".join(out)


def inline_md(text: str) -> str:
    s = esc(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
