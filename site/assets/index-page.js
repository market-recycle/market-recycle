(function () {
  "use strict";
  const $ = id => document.getElementById(id);

  function dateText(iso) {
    if (!iso) return "—";
    const d = new Date(iso + "T12:00:00Z");
    return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric", timeZone: "UTC" });
  }

  function fact(term, value) {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = term;
    const dd = document.createElement("dd"); dd.textContent = value;
    div.append(dt, dd);
    return div;
  }

  function stamp(word, detail) {
    const s = document.createElement("p");
    s.className = "stamp";
    s.textContent = word;
    const small = document.createElement("small");
    small.textContent = detail;
    s.appendChild(small);
    return s;
  }

  function render(rec, weights) {
    const fig = $("figure"), facts = $("facts");
    fig.innerHTML = ""; facts.innerHTML = "";
    if (!rec.latest) {
      const p = document.createElement("p");
      p.className = "figure-pending";
      p.textContent = "The first value publishes once methodology version 1.0 takes effect.";
      const q = document.createElement("p");
      q.className = "figure-change muted";
      q.textContent = "The methodology is in draft and open for review. The first value will be published with at least 24 months of history.";
      fig.append(stamp("Draft", "methodology " + rec.methodology_version.replace("-draft", "")), p, q);
      facts.append(fact("Methodology", "Version " + rec.methodology_version.replace("-draft", " (draft)")), fact("Base", monthLabel(rec.base_month) + " = " + rec.base_value));
      return;
    }
    const L = rec.latest;
    const m = document.createElement("p"); m.className = "figure-month"; m.textContent = rec.short_name + ", " + L.label;
    const v = document.createElement("p"); v.className = "figure-value"; v.textContent = L.value.toFixed(1);
    fig.append(stamp("Published", dateText(L.published)), m, v);
    if (L.change_pct !== null && L.change_pct !== undefined) {
      const c = document.createElement("p"); c.className = "figure-change";
      const s = document.createElement("span");
      s.className = L.change_pct >= 0 ? "up" : "down";
      s.textContent = (L.change_pct >= 0 ? "Up " : "Down ") + Math.abs(L.change_pct).toFixed(1) + "%";
      c.append(s, document.createTextNode(" from the previous month"));
      fig.append(c);
    }
    facts.append(
      fact("Published", dateText(L.published)),
      fact("Next publication", dateText(rec.next_publication)),
      fact("Methodology", "Version " + L.methodology_version),
      fact("Base", monthLabel(rec.base_month) + " = " + rec.base_value)
    );
    if (rec.history.length > 1) {
      $("chart-section").hidden = false;
      lineChart($("chart"), rec.history.map(h => ({ x: h.month, y: h.value })), {
        label: rec.name + " by month", format: y => y.toFixed(1), baseline: rec.base_value,
      });
    }
  }

  function showWeights(w) {
    document.querySelectorAll("[data-w]").forEach(td => {
      const v = w && w[td.dataset.w];
      td.textContent = v == null ? "Set at v1.0" : Math.round(v * 100) + "%";
    });
  }

  fetch("/data/index.json", { cache: "no-cache" })
    .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(rec => {
      render(rec);
      // Published weights live with the methodology; show them once a value is published.
      return fetch("/data/methodology.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null)
        .then(meth => showWeights(meth && meth.weights_published ? meth.weights : null));
    })
    .catch(() => {
      $("figure").innerHTML = "<p class='figure-pending'>The index data couldn't be loaded. Refresh the page to try again.</p>";
    });
})();
