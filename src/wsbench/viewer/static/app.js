// Small page behaviours outside the question page: the method chooser and the eval page's
// question filter. Everything re-initialises after an htmx swap.
(function () {
  window.applyRuns = function (btn) {
    const menu = btn.closest("[data-runs]");
    const ids = Array.from(menu.querySelectorAll("input:checked")).map((i) => i.value);
    const form = btn.closest("form");
    form.querySelector('input[name="runs"]').value = ids.join(",");
    form.requestSubmit();
  };

  function questionFilter() {
    const table = document.getElementById("qlist");
    if (!table || table.dataset.ready) return;
    table.dataset.ready = "1";
    const ctl = ["fa", "faw", "fb", "fbw"].map((id) => document.getElementById(id));
    const count = document.getElementById("fcount");
    const rows = Array.from(table.tBodies[0].rows);
    const params = new URLSearchParams(location.search);
    function apply() {
      const [a, aw, b, bw] = ctl.map((el) => (el ? el.value : "-1"));
      let n = 0;
      const ids = [];
      rows.forEach((tr) => {
        const got = (run) => { const td = tr.querySelector('td[data-run="' + run + '"]'); return td ? td.dataset.pass : ""; };
        const ok = (a === "-1" || got(a) === aw) && (b === "-1" || !ctl[2] || got(b) === bw);
        tr.hidden = !ok;
        if (ok) { n++; ids.push(tr.dataset.item); }
      });
      if (count) count.textContent = n + " of " + rows.length + " questions";
      // the question page walks this list with j / k
      try {
        const name = decodeURIComponent(location.pathname.split("/")[2] || "");
        localStorage.setItem("bv.qlist", JSON.stringify({ eval: name, model: params.get("model") || document.querySelector('select[name="model"]').value, ids }));
      } catch (e) { /* ignore */ }
    }
    ctl.forEach((el) => el && el.addEventListener("change", apply));
    apply();
  }

  // The runs table: a click on a heading sorts by that column (numbers by value, text by
  // text; cells without a value stay last), a second click reverses.
  function sortable() {
    const table = document.getElementById("runs");
    if (!table || table.dataset.ready) return;
    table.dataset.ready = "1";
    const heads = Array.from(table.tHead.rows[0].cells);
    heads.forEach((th, col) => th.addEventListener("click", () => {
      const dir = th.dataset.dir === "asc" ? "desc" : "asc";
      heads.forEach((h) => { delete h.dataset.dir; });
      th.dataset.dir = dir;
      const key = (tr) => { const td = tr.cells[col]; return td.dataset.v != null ? td.dataset.v : td.textContent.trim(); };
      const rows = Array.from(table.tBodies[0].rows);
      const numeric = rows.every((tr) => key(tr) === "" || key(tr) === "—" || !isNaN(parseFloat(key(tr))));
      rows.sort((a, b) => {
        const x = key(a), y = key(b), ex = x === "" || x === "—", ey = y === "" || y === "—";
        if (ex || ey) return ex === ey ? 0 : ex ? 1 : -1;
        const d = numeric ? parseFloat(x) - parseFloat(y) : x.localeCompare(y);
        return dir === "asc" ? d : -d;
      });
      rows.forEach((tr) => table.tBodies[0].appendChild(tr));
    }));
  }

  function closeMenus(e) {
    document.querySelectorAll("details.pick[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  }

  function init() { questionFilter(); sortable(); }
  document.addEventListener("click", closeMenus);
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  if (document.readyState !== "loading") init();
})();
