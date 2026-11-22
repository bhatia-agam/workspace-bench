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

  function closeMenus(e) {
    document.querySelectorAll("details.pick[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  }

  function init() { questionFilter(); }
  document.addEventListener("click", closeMenus);
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSettle", init);
  if (document.readyState !== "loading") init();
})();
