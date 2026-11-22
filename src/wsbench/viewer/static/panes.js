// Side-by-side panes: a CSS grid whose column widths the user drags, with close / expand per
// pane. Widths are fractions kept in localStorage per pane count. No dependencies.
(function () {
  const KEY = "bv.panes.widths.";

  function load(n) {
    try {
      const w = JSON.parse(localStorage.getItem(KEY + n) || "null");
      if (Array.isArray(w) && w.length === n) return w;
    } catch (e) { /* ignore */ }
    return Array(n).fill(1);
  }

  function apply(root, widths) {
    const cols = [];
    widths.forEach((w, i) => {
      if (i) cols.push("6px");
      cols.push("minmax(260px, " + w.toFixed(3) + "fr)");
    });
    root.style.gridTemplateColumns = cols.join(" ");
  }

  // layout(root): root's children are .pane elements; inserts drag handles between them.
  function layout(root) {
    root.querySelectorAll(":scope > .handle").forEach((h) => h.remove());
    const panes = Array.from(root.querySelectorAll(":scope > .pane"));
    const expanded = panes.find((p) => p.classList.contains("expanded"));
    if (expanded) {
      panes.forEach((p) => { p.style.display = p === expanded ? "" : "none"; });
      root.style.gridTemplateColumns = "1fr";
      return;
    }
    panes.forEach((p) => { p.style.display = ""; });
    const widths = load(panes.length);
    panes.slice(1).forEach((p, i) => {
      const h = document.createElement("div");
      h.className = "handle";
      h.title = "drag to resize, double-click to reset";
      h.addEventListener("mousedown", (ev) => drag(ev, root, widths, i));
      h.addEventListener("dblclick", () => {
        widths.fill(1);
        localStorage.removeItem(KEY + widths.length);
        apply(root, widths);
      });
      root.insertBefore(h, p);
    });
    apply(root, widths);
  }

  function drag(ev, root, widths, i) {
    ev.preventDefault();
    const panes = Array.from(root.querySelectorAll(":scope > .pane"));
    const a = panes[i].getBoundingClientRect().width;
    const b = panes[i + 1].getBoundingClientRect().width;
    const total = widths[i] + widths[i + 1];
    const x0 = ev.clientX;
    document.body.classList.add("dragging");
    function move(e) {
      const na = Math.max(260, Math.min(a + b - 260, a + e.clientX - x0));
      widths[i] = (total * na) / (a + b);
      widths[i + 1] = total - widths[i];
      apply(root, widths);
    }
    function up() {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.classList.remove("dragging");
      localStorage.setItem(KEY + widths.length, JSON.stringify(widths));
    }
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  window.Panes = { layout };
})();
