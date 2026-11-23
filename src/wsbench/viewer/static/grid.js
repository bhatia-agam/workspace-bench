// The question page. One JSON payload per open method holds every layer x position, so moving
// with the arrow keys never asks the server. Keys: <- -> positions, up/down layers, j/k
// questions, h next cell with the expected answer, / search, n next match, b bookmark, ? help.
(function () {
  const HAS_EXPECTED = 1, HAS_QUOTE = 2;
  // Method names and colours, and the claim-map leaves with their verdicts, come with the page's
  // data (one palette, defined in meta.py); these are filled in init().
  let LEAVES = {}, METHODS = {}, LEAF_INFO = {}, AXES = [];
  let S = null; // page state
  const dot = (m) => '<i class="dot m-' + esc(m) + '" title="' + esc(METHODS[m] || m) + '"></i>';
  const mchip = (m) => '<span class="mchip mc-' + esc(m) + '" title="' + esc(METHODS[m] || m) + '">' + dot(m) + esc((S.D.methods[m] || {}).alias || m) + "</span>";
  const integ = (r) => (r.integrity ? '<span class="tag integ" title="' + esc(r.integrityReason || "") + '">' + esc(r.integrity) + "</span>" : "");

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
  const $ = (id) => document.getElementById(id);
  const lsGet = (k, d) => { try { const v = JSON.parse(localStorage.getItem(k)); return v == null ? d : v; } catch (e) { return d; } };
  const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* full */ } };
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const showTok = (t) => (t == null ? "·" : t.replace(/\n/g, "⏎").replace(/ /g, "␣") || "∅");

  function init() {
    const el = $("qdata");
    if (!el || el.dataset.ready) return;
    el.dataset.ready = "1";
    const D = JSON.parse(el.textContent);
    LEAVES = {}; LEAF_INFO = {}; METHODS = {}; AXES = D.axes || [];
    (D.leaves || []).forEach((l) => { LEAVES[l.leaf] = l.title; LEAF_INFO[l.leaf] = l; });
    Object.keys(D.methods || {}).forEach((m) => { METHODS[m] = D.methods[m].title; });
    const saved = lsGet("bv.open." + D.bench + "." + D.model, null);
    const known = new Set(D.runs.map((r) => r.id));
    let open = new URLSearchParams(location.search).get("runs") ? D.open : (saved || D.open);
    open = open.filter((r) => known.has(r));
    if (!open.length) open = D.runs.slice(0, 3).map((r) => r.id);
    S = { D, open, data: {}, layer: D.layer != null ? +D.layer : null, pos: D.pos != null ? +D.pos : null,
          find: D.find || "", seg: null, expanded: null, loading: 0 };
    const list = lsGet("bv.qlist", null);
    if (list && list.eval === D.eval && list.model === D.model && list.ids.includes(D.item.item)) S.ids = list.ids;
    else S.ids = D.ids;
    renderHead();
    loadAll();
  }

  // ---------------------------------------------------------------- data

  function loadAll() {
    S.open.forEach((rid) => { if (!S.data[rid]) load(rid); });
    renderAll();
  }

  function load(rid) {
    const D = S.D, item = D.item.item;
    S.loading++;
    fetch("/api/cells?run=" + encodeURIComponent(rid) + "&eval=" + encodeURIComponent(D.eval) + "&item=" + encodeURIComponent(item))
      .then((r) => r.json())
      .then((d) => {
        S.loading--;
        if (!S || S.D.item.item !== item) return;
        prep(d);
        S.data[rid] = d;
        renderAll();
      })
      .catch(() => { S.loading--; S.data[rid] = { error: "could not load", cells: {}, layers: [], positions: [] }; renderAll(); });
  }

  function prep(d) {
    // readouts that cannot be had here: no cells at all (the server sends one placeholder
    // cell holding the marker), and a notice in the pane where the readouts would be
    if (d.readouts && d.readouts.available === false) { d.unavailable = d.readouts; d.cells = {}; d.layers = []; d.positions = []; }
    const terms = (d.terms || []).filter((t) => t && String(t).length > 1 || /^\d$/.test(t));
    if (terms.length) {
      const parts = terms.map((t) => {
        const s = reEsc(String(t));
        return (/^[\p{L}\p{N}]/u.test(t) ? "(?<![\\p{L}\\p{N}_])" : "") + s + (/[\p{L}\p{N}]$/u.test(t) ? "(?![\\p{L}\\p{N}_])" : "");
      });
      try { d.termRe = new RegExp(parts.join("|"), "giu"); } catch (e) { d.termRe = null; }
    }
    d.quotesLow = (d.quotes || []).map((q) => q.toLowerCase());
    d.claim = Object.values(d.cells || {}).some((c) => c.g); // a claim-map run (HB main, story)
    // exact per-layer verdicts, when the result row has them (native and regex evals)
    d.lv = {};
    const v0 = ((d.verdicts || [])[0] || {}).detail || {};
    if (v0.layers && typeof v0.layers === "object") {
      Object.keys(v0.layers).forEach((k) => {
        const e = v0.layers[k];
        let ok = null;
        if (Array.isArray(v0.passing_layers)) ok = v0.passing_layers.includes(+k);
        else if (typeof e === "boolean") ok = e;
        else if (e && typeof e === "object") {
          if (typeof e.flagged === "boolean") ok = !e.flagged; // a false alarm at this layer
          else for (const f of ["expressed", "pass", "correct", "hit"]) if (typeof e[f] === "boolean") { ok = e[f]; break; }
        }
        if (ok != null && +k >= 0) d.lv[k] = ok;
      });
    }
  }

  function axes() {
    const layers = new Set(), pos = new Map();
    S.open.forEach((rid) => {
      const d = S.data[rid];
      if (!d || !d.layers) return;
      d.layers.forEach((l) => layers.add(l));
      d.positions.forEach((p) => { if (!pos.has(p.p) || pos.get(p.p) == null) pos.set(p.p, p.t); });
    });
    const sites = ((S.D.item.meta || {}).sites) || [];
    sites.forEach((s) => { if (pos.has(s.pos) && pos.get(s.pos) == null) pos.set(s.pos, s.token); });
    S.layers = Array.from(layers).sort((a, b) => a - b);
    S.positions = Array.from(pos.keys()).sort((a, b) => a - b);
    S.tokens = pos;
    if (S.layers.length && !S.layers.includes(S.layer)) S.layer = pickLayer();
    if (S.positions.length && !S.positions.includes(S.pos)) S.pos = pickPos();
  }

  function flagAt(d, l, p) { const c = d && d.cells && d.cells[l + ":" + p]; return c ? c.f : 0; }

  function pickLayer() {
    for (const rid of S.open) {
      const d = S.data[rid];
      if (!d || !d.cells) continue;
      for (const want of [HAS_QUOTE, HAS_EXPECTED]) {
        for (const l of S.layers) for (const p of S.positions) if (flagAt(d, l, p) & want) return l;
      }
    }
    return S.layers[Math.floor(S.layers.length / 2)];
  }

  function pickPos() {
    for (const rid of S.open) {
      const d = S.data[rid];
      if (!d || !d.cells) continue;
      for (const want of [HAS_QUOTE, HAS_EXPECTED]) {
        for (const p of S.positions) if (flagAt(d, S.layer, p) & want) return p;
      }
    }
    return S.positions[S.positions.length - 1];
  }

  // ---------------------------------------------------------------- head

  function verdictBadge(r) {
    if (r.pass === 1) return '<i class="v ok">✓</i>';
    if (r.pass === 0) return '<i class="v no">✗</i>';
    if (r.score != null) return '<i class="v num">' + (S.D.pct ? (100 * r.score).toFixed(1) + "%" : r.score.toFixed(2)) + "</i>";
    return '<i class="v un">·</i>';
  }

  function renderHead() {
    const D = S.D, it = D.item, i = S.ids.indexOf(it.item);
    const chips = (xs, cls) => (xs || []).map((x) => '<span class="chip ' + cls + '">' + esc(x) + "</span>").join("");
    let answer = "";
    if (it.hidden) answer = '<div class="private">This question is private (nocot). Start the viewer with private=True to see it.</div>';
    else if (!D.pct) {
      answer = '<div class="answer"><div><label>Expected answer</label>' + (chips(it.expected, "gold") || '<span class="hint">not in the bank</span>') + "</div>" +
        ((it.intermediates || []).length ? "<div><label>Hidden intermediates the lens should show</label>" + chips(it.intermediates, "gold soft") + "</div>" : "") + "</div>";
    }
    const runs = D.runs.filter((r) => S.open.includes(r.id)).map((r) => '<span class="rv" title="' + esc(r.label + "  ·  " + r.lens) + '">' + dot(r.method) + verdictBadge(r) + "</span>").join("");
    let prompt = "";
    if (!it.hidden) {
      const meta = it.meta || {};
      prompt = '<details class="prompt" ' + (lsGet("bv.prompt.open", true) ? "open" : "") + ' id="qprompt"><summary>Prompt' + (meta.response ? " and response (read sites marked)" : "") + "</summary><pre>" + esc(it.prompt || "") + "</pre>" +
        (meta.response ? '<pre class="resp" id="qresp"></pre>' : "") + "</details>";
    }
    $("qhead").innerHTML =
      '<div class="qtitle"><h2>' + esc(it.item) + "</h2>" + (it.private ? '<i class="lock">private</i>' : "") +
      '<span class="hint">' + (i + 1) + " / " + S.ids.length + " in " + esc(D.evalTitle) + '</span><span class="rvs">' + runs + "</span>" +
      '<span class="sp"></span><input id="qfind" type="search" placeholder="search readouts  ( / )" value="' + esc(S.find) + '">' +
      '<span id="qfindn" class="hint"></span>' +
      '<button class="btn sm" data-act="prev" title="previous question (k)">‹ prev</button><button class="btn sm" data-act="next" title="next question (j)">next ›</button>' +
      '<button class="btn sm" data-act="mark" title="bookmark this cell (b); Shift+B adds a note">☆ bookmark</button>' +
      '<button class="btn sm" data-act="help" title="keys (?)">?</button></div>' + answer + prompt +
      '<details class="howjudged"><summary>How this eval is judged' + (D.scoredBy ? ' <span class="hint">scored by ' + esc(D.scoredBy) + "</span>" : "") + "</summary>" +
      (D.scoredBy ? '<p class="by-line">Scored by: <b>' + esc(D.scoredBy) + "</b></p>" : "") + "<p>" + esc(D.judgedBy || "") + "</p>" +
      (D.summaryNote ? '<p class="hint">' + esc(D.summaryNote) + "</p>" : "") +
      (D.gates || []).map((g) => '<div class="gate"><b>' + esc(g.name) + "</b><p>" + esc(g.text) + "</p></div>").join("") + "</details>";
    const p = $("qprompt");
    if (p) p.addEventListener("toggle", () => lsSet("bv.prompt.open", p.open));
    const f = $("qfind");
    f.addEventListener("input", () => { S.find = f.value; renderAll(); });
    f.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); nextMatch(e.shiftKey ? -1 : 1); } if (e.key === "Escape") f.blur(); });
  }

  function renderResponse() {
    const el = $("qresp");
    if (!el) return;
    const meta = S.D.item.meta || {}, text = meta.response || "";
    const sites = (meta.sites || []).slice().sort((a, b) => a.char - b.char);
    let out = "", at = 0;
    sites.forEach((s) => {
      // a site's `char` is the offset just after its token in the response
      const end = Math.min(text.length, s.char), start = Math.max(at, end - Math.max(1, (s.token || "").length));
      out += esc(text.slice(at, start));
      out += '<span class="site' + (s.pos === S.pos ? " cur" : "") + '" data-p="' + s.pos + '" title="read site, pos ' + s.pos + '">' + esc(text.slice(start, end) || s.token) + "</span>";
      at = Math.max(at, end);
    });
    el.innerHTML = out + esc(text.slice(at));
  }

  // ---------------------------------------------------------------- strip (positions x layers)

  function cellWeight(c) {
    if (!c || !c.g) return null;
    let w = 0, n = 0;
    c.g.forEach((g) => { if (g.w != null) { w += g.w; n++; } });
    return n ? w / n : null;
  }

  const trimTok = (t) => String(t == null ? "" : t).trim();

  // The whole prompt's tokens, when ingest stored them and they line up with this question's
  // read positions (same token at the same index); otherwise null: read positions only.
  function fullTokens() {
    const toks = S.D.item.tokens;
    if (!Array.isArray(toks) || !toks.length || !S.positions.length) return null;
    const n = toks.length, at = (p) => (p >= 0 ? p : n + p);
    let ok = 0, seen = 0;
    for (const p of S.positions) {
      const i = at(p);
      if (i < 0 || i >= n) return null;
      const t = S.tokens.get(p);
      if (t == null) continue;
      seen++;
      if (trimTok(toks[i]) === trimTok(t)) ok++;
    }
    return seen && ok / seen < 0.9 ? null : { toks, at };
  }

  function tokClass(p) {
    let cls = "tok", any = 0;
    S.open.forEach((rid) => { any |= flagAt(S.data[rid], S.layer, p); });
    if (any & HAS_EXPECTED) cls += " hit";
    if (any & HAS_QUOTE) cls += " quote";
    if (p === S.pos) cls += " cur";
    return cls;
  }

  function renderStrip() {
    const D = S.D;
    if (!S.positions.length) {
      const gone = S.open.some((r) => S.data[r] && S.data[r].unavailable);
      $("qstrip").innerHTML = S.loading ? '<div class="empty">loading readouts…</div>' : '<div class="empty">' + (gone ? "The readouts of the open runs are not available here; verdicts and judge calls are shown below." : "No readouts stored for this question in the open methods.") + "</div>";
      return;
    }
    const full = fullTokens();
    let toks = "", mode;
    if (full) {
      const byIndex = new Map(S.positions.map((p) => [full.at(p), p]));
      full.toks.forEach((t, i) => {
        const p = byIndex.get(i);
        toks += p == null ? '<span class="tok dim">' + esc(showTok(t)) + "</span>"
          : '<span class="' + tokClass(p) + ' read" data-p="' + p + '" title="read position ' + p + '">' + esc(showTok(t)) + "</span>";
      });
      mode = "whole prompt (" + full.toks.length + " tokens, subject tokenizer) · " + S.positions.length + " read positions outlined";
    } else {
      let prev = null;
      S.positions.forEach((p) => {
        if (prev != null && p - prev > 1) toks += '<span class="gap" title="' + (p - prev - 1) + ' positions not read">…</span>';
        toks += '<span class="' + tokClass(p) + '" data-p="' + p + '" title="pos ' + p + '">' + esc(showTok(S.tokens.get(p))) + "</span>";
        prev = p;
      });
      mode = "read positions only (" + S.positions.length + " tokens; no stored tokenization of the whole prompt for this question)";
    }
    let maps = "";
    S.open.forEach((rid) => {
      const d = S.data[rid], run = D.runs.find((r) => r.id === rid);
      if (!d || !d.cells) return;
      maps += '<div class="map"><div class="map-name" title="' + esc(run.lens) + '">' + mchip(run.method) + esc(run.label) + integ(run) + '</div><div class="map-scroll"><canvas data-run="' + esc(rid) + '"></canvas></div></div>';
    });
    const anyClaim = S.open.some((r) => S.data[r] && S.data[r].claim);
    const anyLv = S.open.some((r) => S.data[r] && S.data[r].lv && Object.keys(S.data[r].lv).length);
    const legend = (anyClaim ? '<span><i class="sw" style="background:#dc2626"></i>hallucinated share of the cell</span><span><i class="sw" style="background:#dcfce7"></i>no hallucination</span>'
      : D.pct ? "" : '<span><i class="sw" style="background:#16a34a"></i>expected answer in the readout (text match)</span><span><i class="sw" style="background:#d97706"></i>the judge\'s quote is from here</span>') +
      (anyLv ? '<span><i class="sw" style="background:#15803d"></i><i class="sw" style="background:#f87171"></i>bar at the left: the judge\'s verdict for that layer (exact)</span>' : "");
    $("qstrip").innerHTML =
      '<div class="strip"><div class="strip-h"><b>Prompt tokens</b><span class="hint">' + esc(mode) + ' · ← → move</span></div><div class="toks">' + toks + "</div></div>" +
      '<div class="maps"><div class="strip-h"><b>Layers × positions</b><span class="hint">↑ ↓ change layer · click a cell</span><span class="legend">' + legend + "</span></div>" + maps + "</div>" + (anyClaim ? claimLegend() : "");
    const lg = $("cmlegend");
    if (lg) lg.addEventListener("toggle", () => lsSet("bv.cmlegend.open", lg.open));
    drawMaps();
    const cur = $("qstrip").querySelector(".tok.cur");
    if (cur) { const box = cur.parentElement; if (cur.offsetTop < box.scrollTop || cur.offsetTop + cur.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = cur.offsetTop - box.clientHeight / 2; }
  }

  // The claim-map legend: every leaf in its colour, grouped under its verdict. A block of its
  // own between the maps and the panes, so it never covers readout text.
  function claimLegend() {
    const groups = (S.D.verdicts || []).map((v) => {
      const leaves = (S.D.leaves || []).filter((l) => l.verdict === v.id);
      return '<div class="cmgroup"><b title="' + esc(v.what) + '"><i class="vdot" style="background:' + esc(v.color) + '"></i>' + esc(v.title) + "</b>" +
        leaves.map((l) => '<span class="lchip leaf-' + esc(l.leaf) + '" title="' + esc(l.text + (l.weight != null ? "  ·  weight " + l.weight : "")) + '">' + esc(l.title) + "</span>").join("") + "</div>";
    }).join("");
    return '<details class="cmlegend" id="cmlegend" ' + (lsGet("bv.cmlegend.open", true) ? "open" : "") + '><summary>Claim-map legend <span class="hint">segment colour = leaf, grouped by verdict</span></summary><div class="cmgroups">' + groups + "</div></details>";
  }

  // One canvas per open method: layers down (deepest on top), read positions across, layer
  // numbers on the left, tokens on top. It fills the row's width.
  function drawMaps() {
    const box = document.querySelector("#qstrip .maps");
    if (!box) return;
    const canvases = Array.from(box.querySelectorAll("canvas"));
    const n = S.positions.length, L = S.layers.slice().reverse();
    const left = 40, bar = 14, avail = box.clientWidth - 30 - left - bar;
    const cw = Math.max(6, Math.min(40, Math.floor(avail / n)));
    const ch = canvases.length <= 1 ? 20 : canvases.length === 2 ? 16 : 13;
    const every = Math.max(1, Math.ceil(13 / cw));
    const dpr = window.devicePixelRatio || 1;
    canvases.forEach((cv, k) => {
      const d = S.data[cv.dataset.run];
      const top = k === 0 ? 58 : 8;
      const w = left + bar + n * cw + 2, h = top + L.length * ch + 2;
      cv.width = w * dpr; cv.height = h * dpr;
      cv.style.width = w + "px"; cv.style.height = h + "px";
      const g = cv.getContext("2d");
      g.scale(dpr, dpr);
      const x0 = left + bar, xi = S.positions.indexOf(S.pos), yi = L.indexOf(S.layer);
      if (k === 0) {
        S.positions.forEach((p, x) => {
          if (x % every && x !== xi) return;
          g.save();
          g.translate(x0 + x * cw + cw / 2 + 3, top - 5);
          g.rotate(-Math.PI / 3);
          g.fillStyle = x === xi ? "#111827" : "#6b7280";
          g.font = (x === xi ? "bold " : "") + "10px ui-monospace, Menlo, monospace";
          g.fillText(showTok(S.tokens.get(p)).slice(0, 9), 0, 0);
          g.restore();
        });
      }
      L.forEach((l, y) => {
        const yy = top + y * ch;
        g.fillStyle = y === yi ? "#111827" : "#6b7280";
        g.font = (y === yi ? "bold " : "") + "10px ui-monospace, Menlo, monospace";
        g.textAlign = "right";
        g.fillText("L" + l, left - 6, yy + ch / 2 + 3.5);
        g.textAlign = "left";
        if (d.lv && d.lv[l] != null) { g.fillStyle = d.lv[l] ? "#15803d" : "#f87171"; g.fillRect(left, yy, bar - 5, ch - 2); }
        S.positions.forEach((p, x) => {
          const c = d.cells[l + ":" + p];
          let col = "#eef0f3";
          if (c) {
            if (c.g || d.claim) {
              const wt = cellWeight(c);
              col = wt == null ? "#e2e5ea" : wt === 0 ? "#dcfce7" : "rgba(220,38,38," + (0.25 + 0.75 * Math.min(1, wt * 2)).toFixed(2) + ")";
            } else col = c.f & HAS_QUOTE ? "#d97706" : c.f & HAS_EXPECTED ? "#16a34a" : "#dfe3e8";
          }
          g.fillStyle = col;
          g.fillRect(x0 + x * cw, yy, cw - 1.5, ch - 2);
        });
      });
      if (xi >= 0 && yi >= 0) { // the current cell: a band along its row and column, a dark frame
        g.fillStyle = "rgba(17,24,39,.07)";
        g.fillRect(x0, top + yi * ch - 1, n * cw, ch);
        g.fillRect(x0 + xi * cw - 1, top, cw + 0.5, L.length * ch);
        g.strokeStyle = "#111827"; g.lineWidth = 2;
        g.strokeRect(x0 + xi * cw - 1, top + yi * ch - 1, cw + 0.5, ch);
      }
      cv.onclick = (e) => {
        const r = cv.getBoundingClientRect();
        const px = Math.floor((e.clientX - r.left - x0) / cw), py = Math.floor((e.clientY - r.top - top) / ch);
        if (S.positions[px] != null && L[py] != null) go(L[py], S.positions[px]);
      };
    });
  }

  // ---------------------------------------------------------------- panes

  function marks(text, d, findLow) {
    // per character: 1 expected term, 2 judge quote, 4 search match
    const m = new Uint8Array(text.length);
    if (d.termRe) { d.termRe.lastIndex = 0; let x; while ((x = d.termRe.exec(text))) { if (!x[0].length) { d.termRe.lastIndex++; continue; } m.fill(m[x.index] | 1, x.index, x.index + x[0].length); } }
    const low = text.toLowerCase();
    (d.quotesLow || []).forEach((q) => { let i = low.indexOf(q); while (i >= 0 && q.length) { for (let k = i; k < i + q.length; k++) m[k] |= 2; i = low.indexOf(q, i + q.length); } });
    if (findLow) { let i = low.indexOf(findLow); while (i >= 0) { for (let k = i; k < i + findLow.length; k++) m[k] |= 4; i = low.indexOf(findLow, i + findLow.length); } }
    return m;
  }

  function paint(text, m, segOf, segs) {
    let out = "", i = 0;
    while (i < text.length) {
      let j = i + 1;
      while (j < text.length && m[j] === m[i] && (!segOf || segOf[j] === segOf[i])) j++;
      let cls = (m[i] & 1 ? " t" : "") + (m[i] & 2 ? " q" : "") + (m[i] & 4 ? " f" : "");
      let attr = "";
      if (segOf && segOf[i] >= 0) { const sg = segs[segOf[i]]; cls += " seg leaf-" + sg.leaf + (S.seg === sg ? " sel" : ""); attr = ' data-seg="' + segOf[i] + '" title="' + esc(leafName(sg.leaf)) + '"'; }
      out += cls || attr ? '<span class="' + cls.trim() + '"' + attr + ">" + esc(text.slice(i, j)) + "</span>" : esc(text.slice(i, j));
      i = j;
    }
    return out;
  }

  // "False claim (Hallucination)": the leaf with the verdict it belongs to
  function leafName(leaf) {
    const info = LEAF_INFO[leaf];
    return info ? info.title + " (" + info.verdict_title + ")" : leaf;
  }

  function readoutHtml(d) {
    const c = d.cells[S.layer + ":" + S.pos];
    if (!c) return '<div class="empty sm">no readout at this layer and position</div>';
    const findLow = S.find.trim().toLowerCase();
    return c.s.map((text, n) => {
      const m = marks(text, d, findLow);
      let segOf = null, segs = null;
      if (c.g) {
        segs = c.g;
        segOf = new Int16Array(text.length).fill(-1);
        segs.forEach((sg, k) => { if (sg.i === n) for (let x = sg.a; x < Math.min(sg.b, text.length); x++) segOf[x] = k; });
      }
      return '<div class="sample"><span class="sn">' + (c.s.length > 1 ? "sample " + (n + 1) : "readout") + "</span><div class=\"txt\">" + paint(text, m, segOf, segs) + "</div></div>";
    }).join("") || '<div class="empty sm">empty readout</div>';
  }

  const SKIP = new Set(["_statements", "_n_statements", "id", "item"]);
  function kv(obj, skip) {
    return Object.entries(obj || {}).filter(([k, v]) => !(skip && skip.has(k)) && v != null && v !== "").map(([k, v]) => {
      let val;
      if (typeof v === "boolean" && k === "flagged") val = v ? '<span class="pill no">yes: a false alarm</span>' : "no"; // true is the bad outcome
      else if (typeof v === "boolean") val = '<i class="v ' + (v ? "ok" : "no") + '">' + (v ? "✓" : "✗") + "</i>";
      else if (Array.isArray(v) && v.length && v.every((x) => typeof x === "string")) val = '<ul class="lines">' + v.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>";
      else if (typeof v === "object") val = '<code class="json">' + esc(JSON.stringify(v)) + "</code>";
      else val = esc(v);
      return '<div class="kv"><span>' + esc(k.replace(/_/g, " ")) + "</span><div>" + val + "</div></div>";
    }).join("");
  }

  function optionsHtml(opts, chosen, gold) {
    if (!Array.isArray(opts) || !opts.length) return "";
    const letter = typeof chosen === "string" && /^[A-Z]$/.test(chosen) ? chosen.charCodeAt(0) - 65 : -1;
    return '<ol class="opts" type="A">' + opts.map((o, i) => {
      const text = typeof o === "string" ? o : JSON.stringify(o);
      const isGold = gold != null && (i === gold || text === gold);
      const isPick = i === letter || (typeof chosen === "string" && chosen.length > 1 && text === chosen);
      return '<li class="' + (isGold ? "gold " : "") + (isPick ? "pick" : "") + '">' + esc(text) + (isPick ? ' <em>← judge picked</em>' : "") + (isGold ? ' <em class="g">expected</em>' : "") + "</li>";
    }).join("") + "</ol>";
  }

  function verdictHtml(v, n, total) {
    const d = v.detail || {};
    const head = v.pass === 1 ? '<span class="pill ok">right</span>' : v.pass === 0 ? '<span class="pill no">wrong</span>' : '<span class="pill un">no verdict</span>';
    const gold = d.gold_idx != null ? d.gold_idx : d.gold_position != null ? d.gold_position : d.gold;
    const first = ["choice", "pick", "picked", "answer", "word", "choice_kind", "outcome", "quote", "why", "reasoning", "rationale", "score"];
    const firstObj = {};
    first.forEach((k) => { if (d[k] != null && typeof d[k] !== "object") firstObj[k] = d[k]; });
    const skip = new Set([...SKIP, ...first, "options", "pass", "correct", "layers"]);
    const checks = {}, rest = {};
    Object.entries(d).forEach(([k, val]) => {
      if (skip.has(k)) return;
      if (typeof val === "boolean" || k === "gates") checks[k] = val; else rest[k] = val;
    });
    return '<div class="verdict">' + (total > 1 ? '<span class="hint">row ' + (n + 1) + " of " + total + "</span> " : "") + head +
      kv(firstObj) + optionsHtml(d.options, d.choice || d.pick, gold) +
      (d.layers && d.layers[S.layer] && typeof d.layers[S.layer] === "object" ? '<div class="sub">The judge at layer ' + S.layer + " (exact, this layer only)</div>" + kv(d.layers[S.layer]) : "") +
      (Object.keys(checks).length ? '<div class="sub">Checks the code ran on the pick</div>' + kv(checks) : "") +
      (Object.keys(rest).length ? "<details><summary>all " + Object.keys(rest).length + " other fields of the result row</summary>" + kv(rest) + "</details>" : "") + "</div>";
  }

  function digestPart(j) {
    const r = j.result || {};
    const rows = (r.items || []).concat((r.rare || []).map((x) => Object.assign({ rare: 1 }, x)));
    if (!rows.length) return "";
    return '<table class="dg"><tbody>' + rows.map((x) => {
      const m = /\[L(-?\d+) pos (-?\d+)\]/.exec(x.where || "");
      const jump = m ? ' data-l="' + m[1] + '" data-p="' + m[2] + '" class="jump" title="go to this cell"' : "";
      return "<tr><td>" + esc(x.statement) + (x.rare ? ' <span class="hint">rare</span>' : "") + '<div class="ev">“' + esc(x.evidence || "") + '”</div></td><td class="n">' + esc(x.count == null ? "" : "×" + x.count) + "</td><td" + jump + ">" + esc(x.where || "") + "</td></tr>";
    }).join("") + "</tbody></table>";
  }

  // the summarizer's full text for one lens and question, fetched once and filled in when it lands
  const DIGESTS = {};
  function digestText(rid) {
    const key = rid + "|" + S.D.eval + "|" + S.D.item.item;
    if (key in DIGESTS) return DIGESTS[key] == null ? "loading…" : DIGESTS[key];
    DIGESTS[key] = null;
    fetch("/api/digest?run=" + encodeURIComponent(rid) + "&eval=" + encodeURIComponent(S.D.eval) + "&item=" + encodeURIComponent(S.D.item.item))
      .then((r) => r.json()).then((d) => {
        DIGESTS[key] = d.text || "(not stored)";
        document.querySelectorAll("pre.digest").forEach((pre) => { if (pre.dataset.digest === rid) pre.textContent = DIGESTS[key]; });
      }).catch(() => { delete DIGESTS[key]; });
    return "loading…";
  }

  function judgeHtml(rid, d) {
    if (d.claim) return hbJudgeHtml(d);
    let out = "";
    const calls = d.judgments.filter((j) => !j.stage.startsWith("digest"));
    const total = d.verdicts.length;
    out += '<div class="sec"><h5>Verdict</h5>' + (total ? d.verdicts.slice(0, 12).map((v, n) => verdictHtml(v, n, total)).join("") + (total > 12 ? '<div class="hint">' + (total - 12) + " more rows not shown</div>" : "") : '<div class="hint">no result row for this question</div>') + "</div>";
    if (calls.length) {
      // the calls of this layer, the one made on the selected position first
      const here = calls.filter((j) => j.layer == null || j.layer < 0 || j.layer === S.layer).sort((a, b) => (b.pos === S.pos) - (a.pos === S.pos));
      out += '<div class="sec"><h5>Judge calls <span class="hint">' + here.length + (here.length < calls.length ? " at this layer, " + calls.length + " in all" : "") + "</span></h5>" +
        here.slice(0, 8).map((j) => '<div class="call"><span class="stage">' + esc(j.stage) + (j.layer != null && j.layer >= 0 ? " · L" + j.layer : "") + (j.pos != null ? " · pos " + j.pos : "") + "</span>" +
          '<div class="sub">what the judge answered</div>' + (j.result && typeof j.result === "object" ? kv(j.result) : '<div class="hint">' + esc(j.result == null ? "no answer (refused or failed)" : j.result) + "</div>") +
          (Object.keys(j.meta || {}).length ? '<div class="sub">what the code stored with the call</div>' + (Array.isArray(j.meta.options) ? optionsHtml(j.meta.options, j.result && j.result.choice, null) : "") + kv(j.meta, new Set(["options"])) : "") + "</div>").join("") + "</div>";
    }
    if (d.has_digest) out += '<div class="sec"><h5>Summary the judge read</h5><p class="hint">The summarizer condensed every layer and position of this question into this text. The judge read only this.</p><pre class="digest" data-digest="' + esc(rid) + '">' + esc(digestText(rid)) + "</pre></div>";
    const part = d.judgments.find((j) => j.stage === "digest" && j.layer === S.layer);
    const st = (d.verdicts.find((v) => v.detail && v.detail._statements) || { detail: {} }).detail;
    if (d.mode === "summary" || part) {
      out += '<div class="sec"><h5>What the judge read</h5><p class="hint">' + (d.mode === "summary" ? "Summary mode: the judge never sees raw readouts. All layers and positions of this question are condensed into one digest, and the judge reads that. One verdict for the whole question." : "The judge reads a digest of this layer's readouts, not the raw readouts.") + "</p>";
      if (part) out += '<div class="sub">Digest of layer ' + S.layer + ' (what the digest step kept from this layer)</div>' + digestPart(part);
      if (st._statements) {
        out += '<div class="sub">Top statements of the full digest <span class="hint">' + st._statements.length + " of " + st._n_statements + " · bold = supported at layer " + S.layer + "</span></div><table class=\"dg\"><tbody>" +
          st._statements.slice(0, 14).map((x) => '<tr class="' + ((x.layers || []).includes(S.layer) ? "on" : "") + '"><td>' + esc(x.statement) + '<div class="ev">“' + esc(x.evidence || "") + '”</div></td><td class="n">' + esc(x.support || "") + "</td></tr>").join("") + "</tbody></table>";
      }
      out += "</div>";
    }
    return out;
  }

  function hbJudgeHtml(d) {
    const c = d.cells[S.layer + ":" + S.pos];
    if (!c) return "";
    const segs = c.g || [];
    let w = 0, n = 0;
    const byLeaf = {};
    segs.forEach((g) => { byLeaf[g.leaf] = (byLeaf[g.leaf] || 0) + 1; if (g.w != null) { w += g.w; n++; } });
    const j = c.j || { r: {}, m: {} };
    let out = '<div class="sec"><h5>Score of this cell</h5><div class="hbscore"><b>' + (n ? (100 * w / n).toFixed(1) + "%" : "—") + "</b><span>" + w.toFixed(1) + " weighted hallucinations / " + n + " claims</span>" +
      (j.r && j.r.scored === false ? '<span class="pill no">not scored: the claim map or continuation check did not settle</span>' : "") + "</div>" +
      '<div class="leafs">' + Object.entries(byLeaf).map(([k, v]) => '<span class="leaf-' + k + ' lchip">' + esc(LEAVES[k] || k) + " " + v + "</span>").join("") + "</div>" +
      (j.r && j.r.rationale ? '<p class="rat">' + esc(j.r.rationale) + "</p>" : "") + "</div>";
    out += '<div class="sec"><h5>Segments <span class="hint">click a coloured span above</span></h5>' + segs.map((g, k) => {
      const text = (c.s[g.i] || "").slice(g.a, g.b);
      let chk = "";
      if (g.chk) chk = '<div class="sub">Continuation check</div>' + kv(g.chk);
      const tags = Object.assign({}, g.tags);
      delete tags.raw_leaf; delete tags.status;
      // the span classifier's axes, where the store has them for this segment
      const ax = {};
      AXES.forEach((k) => { if (tags[k] != null && tags[k] !== "") { ax[k] = tags[k]; delete tags[k]; } });
      const axes = Object.keys(ax).length ? '<div class="sub">Span classifier</div>' + kv(ax) : "";
      return '<div class="segrow leaf-b-' + g.leaf + (S.seg === g ? " sel" : "") + '" data-seg="' + k + '"><div class="segtop"><span><span class="lchip leaf-' + g.leaf + '">' + esc(LEAVES[g.leaf] || g.leaf) + '</span><span class="hint">' + esc((LEAF_INFO[g.leaf] || {}).verdict_title || "") + '</span></span><span class="hint">weight ' + (g.w == null ? "— (not a claim)" : g.w) + "</span></div>" +
        '<div class="segtext">' + esc(text) + "</div>" + (g.why ? '<div class="why">' + esc(g.why) + "</div>" : "") +
        (g.con ? '<div class="quote no">contradicted by: “' + esc(g.con) + "”</div>" : "") + (g.sup ? '<div class="quote ok">supported by: “' + esc(g.sup) + "”</div>" : "") +
        axes + (S.seg === g ? chk + (Object.keys(tags).length ? '<div class="sub">Tags</div>' + kv(tags) : "") : "") + "</div>";
    }).join("") + "</div>";
    if (j.m && Array.isArray(j.m.mentions) && j.m.mentions.length) out += '<div class="sec"><h5>Detected mentions <span class="hint">in this family a claim counts only where it overlaps one</span></h5>' + j.m.mentions.map((m) => '<div class="kv"><span>' + esc(String(m.kind || "mention").replace(/_/g, " ")) + "</span><div>“" + esc(m.quote || "") + "”</div></div>").join("") + "</div>";
    if (j.m && j.m.stages) out += '<div class="sec"><h5>Pipeline stages</h5>' + kv(j.m.stages) + "</div>";
    return out;
  }

  function renderPanes() {
    const D = S.D, root = $("qpanes");
    const closed = D.runs.filter((r) => !S.open.includes(r.id));
    let html = "";
    S.open.forEach((rid) => {
      const run = D.runs.find((r) => r.id === rid), d = S.data[rid];
      let body;
      if (!d) body = '<div class="empty sm">loading…</div>';
      else if (d.private) body = '<div class="private">private question</div>';
      else if (d.error) body = '<div class="empty sm">' + esc(d.error) + "</div>";
      else if (d.unavailable) body = '<div class="noreadouts"><b>Readouts not available here</b>They are at <code>' + esc(d.unavailable.where || "") + "</code>" + (d.unavailable.why ? "<br>" + esc(d.unavailable.why) : "") + '</div><div class="jd">' + judgeHtml(rid, d) + "</div>";
      else body = (d.readouts && d.readouts.available ? '<div class="ondemand">readouts read on demand from ' + esc(d.readouts.where || "") + "</div>" : "") + '<div class="ro">' + readoutHtml(d) + '</div><div class="jd">' + judgeHtml(rid, d) + "</div>";
      html += '<section class="pane' + (S.expanded === rid ? " expanded" : "") + '" data-run="' + esc(rid) + '"><header>' + mchip(run.method) + '<div class="pt"><b title="' + esc(run.lens + (run.description ? "\n" + run.description : "")) + '">' + esc(run.label) + "</b><small>" + esc(METHODS[run.method] || "") + (S.layer == null ? "" : " · L" + S.layer + " · pos " + S.pos + " " + esc(showTok(S.tokens.get(S.pos)))) + "</small></div>" + integ(run) + verdictBadge(run) +
        '<button class="ib" data-act="expand" title="expand / restore">⤢</button><button class="ib" data-act="close" title="remove this pane">×</button></header><div class="pbody">' + body + "</div></section>";
    });
    const keep = {};
    root.querySelectorAll(".pane").forEach((p) => { const b = p.querySelector(".pbody"); if (b) keep[p.dataset.run] = b.scrollTop; });
    root.innerHTML = html || '<div class="empty">No method open. Add one below.</div>';
    root.querySelectorAll(".pane").forEach((p) => { if (keep[p.dataset.run] && S.keepScroll) p.querySelector(".pbody").scrollTop = keep[p.dataset.run]; });
    window.Panes.layout(root);
    let add = $("qadd");
    if (!add) { add = document.createElement("div"); add.id = "qadd"; root.after(add); }
    add.innerHTML = closed.length ? '<label class="sel"><span>Add a method pane</span><select id="qaddsel"><option value="">choose…</option>' + closed.map((r) => '<option value="' + esc(r.id) + '">' + esc((METHODS[r.method] || "") + " · " + r.label) + "</option>").join("") + "</select></label>" : "";
    const sel = $("qaddsel");
    if (sel) sel.onchange = () => { if (sel.value) { S.open.push(sel.value); saveOpen(); loadAll(); } };
  }

  function saveOpen() { lsSet("bv.open." + S.D.bench + "." + S.D.model, S.open); }

  function countMatches() {
    const el = $("qfindn"), f = S.find.trim().toLowerCase();
    if (!el) return;
    if (!f) { el.textContent = ""; return; }
    let n = 0;
    matchCells(f).forEach(() => n++);
    el.textContent = n + " cells";
  }

  function matchCells(f) {
    const out = [];
    S.layers.forEach((l) => S.positions.forEach((p) => {
      for (const rid of S.open) {
        const c = S.data[rid] && S.data[rid].cells && S.data[rid].cells[l + ":" + p];
        if (c && c.s.some((t) => t.toLowerCase().includes(f))) { out.push([l, p]); break; }
      }
    }));
    return out;
  }

  function renderAll() {
    axes();
    renderStrip();
    renderPanes();
    renderResponse();
    countMatches();
    S.keepScroll = false;
  }

  // ---------------------------------------------------------------- moves

  function go(layer, pos) {
    if (layer === S.layer && pos === S.pos) return;
    S.keepScroll = layer === S.layer;
    S.layer = layer; S.pos = pos; S.seg = null;
    renderAll();
    syncUrl();
  }

  function syncUrl() {
    const u = new URL(location.href);
    u.searchParams.set("l", S.layer); u.searchParams.set("p", S.pos);
    u.searchParams.set("runs", S.open.join(","));
    history.replaceState(null, "", u);
  }

  function step(dl, dp) {
    if (!S.layers.length) return;
    const li = S.layers.indexOf(S.layer), pi = S.positions.indexOf(S.pos);
    const nl = S.layers[Math.max(0, Math.min(S.layers.length - 1, li + dl))];
    const np = S.positions[Math.max(0, Math.min(S.positions.length - 1, pi + dp))];
    go(nl, np);
  }

  function nextFlag(dir) {
    const cells = [];
    S.layers.forEach((l) => S.positions.forEach((p) => {
      if (S.open.some((rid) => { const c = S.data[rid] && S.data[rid].cells && S.data[rid].cells[l + ":" + p]; return c && (c.g ? (cellWeight(c) || 0) > 0 : c.f & (HAS_EXPECTED | HAS_QUOTE)); })) cells.push([l, p]);
    }));
    jump(cells, dir);
  }

  function nextMatch(dir) { const f = S.find.trim().toLowerCase(); if (f) jump(matchCells(f), dir); }

  function jump(cells, dir) {
    if (!cells.length) return;
    const key = (c) => S.layers.indexOf(c[0]) * 100000 + S.positions.indexOf(c[1]);
    const cur = key([S.layer, S.pos]);
    let pick = dir > 0 ? cells.find((c) => key(c) > cur) : cells.slice().reverse().find((c) => key(c) < cur);
    if (!pick) pick = dir > 0 ? cells[0] : cells[cells.length - 1];
    go(pick[0], pick[1]);
  }

  function question(d) {
    const i = S.ids.indexOf(S.D.item.item), id = S.ids[i + d];
    if (id == null) return;
    const D = S.D;
    fetch("/api/item?bench=" + D.bench + "&model=" + encodeURIComponent(D.model) + "&eval=" + encodeURIComponent(D.eval) + "&item=" + encodeURIComponent(id))
      .then((r) => r.json())
      .then((res) => {
        D.item = res.item; D.runs = res.runs;
        S.data = {}; S.pos = null; S.seg = null;
        const u = new URL(location.href);
        u.pathname = "/q/" + encodeURIComponent(D.eval) + "/" + encodeURIComponent(id);
        u.searchParams.delete("p");
        history.pushState(null, "", u);
        document.querySelectorAll(".crumbs span:last-child").forEach((el) => { el.textContent = id; });
        renderHead();
        loadAll();
      });
  }

  function bookmark(withNote) {
    const D = S.D;
    const note = withNote ? prompt("Note for this bookmark") : "";
    if (note === null) return;
    fetch("/api/bookmark", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bench: D.bench, model: D.model, eval: D.eval, item: D.item.item, run_id: S.open[0] || null, layer: S.layer, pos: S.pos, note }) })
      .then((r) => r.json()).then(() => toast("bookmarked L" + S.layer + " · pos " + S.pos));
  }

  function toast(text) {
    let t = $("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t); }
    t.textContent = text; t.className = "show";
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.className = ""; }, 1600);
  }

  function help() {
    const h = $("qhelp");
    h.innerHTML = h.innerHTML ? "" : '<div class="helpbox"><b>Keys</b><span><kbd>←</kbd><kbd>→</kbd> position</span><span><kbd>↑</kbd><kbd>↓</kbd> layer</span><span><kbd>j</kbd><kbd>k</kbd> next / previous question</span><span><kbd>h</kbd><kbd>H</kbd> next / previous highlighted cell</span><span><kbd>/</kbd> search readouts, <kbd>n</kbd><kbd>N</kbd> next / previous match</span><span><kbd>b</kbd> bookmark, <kbd>B</kbd> with a note</span><span><kbd>?</kbd> this help</span></div>';
  }

  // ---------------------------------------------------------------- events (registered once)

  document.addEventListener("keydown", (e) => {
    if (!S || !$("qapp")) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    if (k === "ArrowLeft") step(0, -1);
    else if (k === "ArrowRight") step(0, 1);
    else if (k === "ArrowUp") step(1, 0);
    else if (k === "ArrowDown") step(-1, 0);
    else if (k === "j") question(1);
    else if (k === "k") question(-1);
    else if (k === "h") nextFlag(1);
    else if (k === "H") nextFlag(-1);
    else if (k === "n") nextMatch(1);
    else if (k === "N") nextMatch(-1);
    else if (k === "/") { const f = $("qfind"); f.focus(); f.select(); }
    else if (k === "b") bookmark(false);
    else if (k === "B") bookmark(true);
    else if (k === "?") help();
    else return;
    e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    if (!S || !$("qapp")) return;
    const t = e.target;
    const tok = t.closest(".tok, .site");
    if (tok && tok.dataset.p != null) return go(S.layer, +tok.dataset.p);
    const jumpEl = t.closest(".jump");
    if (jumpEl) { const l = +jumpEl.dataset.l, p = +jumpEl.dataset.p; if (S.layers.includes(l) && S.positions.includes(p)) go(l, p); return; }
    const segEl = t.closest("[data-seg]");
    if (segEl) {
      const pane = segEl.closest(".pane"), d = S.data[pane.dataset.run], c = d.cells[S.layer + ":" + S.pos];
      const sg = c.g[+segEl.dataset.seg];
      S.seg = S.seg === sg ? null : sg; S.keepScroll = true;
      renderPanes();
      const row = document.querySelector('.pane[data-run="' + CSS.escape(pane.dataset.run) + '"] .segrow.sel');
      if (row && t.closest(".ro")) row.scrollIntoView({ block: "nearest" });
      return;
    }
    const act = t.closest("[data-act]");
    if (!act) return;
    const a = act.dataset.act, pane = act.closest(".pane");
    if (a === "prev") question(-1);
    else if (a === "next") question(1);
    else if (a === "mark") bookmark(e.shiftKey);
    else if (a === "help") help();
    else if (a === "close") { S.open = S.open.filter((r) => r !== pane.dataset.run); if (S.expanded === pane.dataset.run) S.expanded = null; saveOpen(); renderAll(); }
    else if (a === "expand") { S.expanded = S.expanded === pane.dataset.run ? null : pane.dataset.run; S.keepScroll = true; renderPanes(); }
  });

  window.addEventListener("popstate", () => { if ($("qapp")) location.reload(); });
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  if (document.readyState !== "loading") init();
})();
