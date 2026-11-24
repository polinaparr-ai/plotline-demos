/* Threshold dashboard runtime.
 * Draws what app/build_dashboard.py describes, and exposes window.PlotlineDashboard:
 * the small, fixed set of operations the assistant may ask the page to perform. */
(function () {
  "use strict";
  const T = window.THRESHOLD;
  const M = T.manifest;
  const C = {ink: "#1c3029", ink2: "#4b5c53", muted: "#76857c", grid: "#e9eee6", line: "#d3dccf",
    green: "#2d6a4f", greenSoft: "#9cc3a8", blue: "#2a78d6", orange: "#eb6834", aqua: "#1baf7a"};
  const PROVISIONAL = M.freshness.provisional_from;
  const state = {tab: "market", filters: {region: "All", property_type: "All"}, selection: null, selectedChart: null};
  const rendered = new Set();
  const plots = {};

  // ---------- data helpers ----------
  const rows = (name) => {
    const d = T.data[name];
    return d.data.map((r) => Object.fromEntries(d.columns.map((c, i) => [c, r[i]])));
  };
  const cache = {};
  const R = (name) => (cache[name] = cache[name] || rows(name));
  const fmtInt = (v) => Math.round(v).toLocaleString("en-GB");
  const fmtGBP = (v) => "£" + (v >= 1e6 ? (v / 1e6).toFixed(2) + "m" : Math.round(v / 1000) + "k");
  const fmtPct = (v, d = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v * 100).toFixed(d) + "%";
  const monthLabel = (s) => new Date(s + "T00:00:00").toLocaleDateString("en-GB", {month: "short", year: "numeric"});
  const bandLabel = (b) => b.slice(3);

  // ---------- Plotly theme (shared by every chart) ----------
  function layout(extra) {
    return Object.assign({
      font: {family: "Inter, system-ui, sans-serif", size: 12, color: C.ink2},
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
      margin: {l: 56, r: 16, t: 12, b: 40},
      hoverlabel: {bgcolor: "#fff", bordercolor: C.line, font: {family: "Inter", color: C.ink, size: 12}},
      xaxis: {gridcolor: "rgba(0,0,0,0)", linecolor: C.line, tickcolor: C.line, ticks: "outside", ticklen: 4, tickfont: {color: C.muted}},
      yaxis: {gridcolor: C.grid, zeroline: false, tickfont: {color: C.muted}, rangemode: "tozero"},
      legend: {orientation: "h", x: 0, y: 1.12, font: {size: 12, color: C.ink2}},
      bargap: 0.18, hovermode: "closest",
    }, extra || {});
  }
  const CONFIG = {displayModeBar: false, responsive: true};

  function draw(id, data, lay) {
    const el = document.getElementById("plot-" + id);
    if (!el) return;
    Plotly.react(el, data, layout(lay), CONFIG);
    plots[id] = el;
    if (!el._wired) {
      el._wired = true;
      el.on("plotly_click", (ev) => selectPoint(id, ev.points[0]));
    }
  }

  function provisionalShape() {
    return {type: "rect", xref: "x", yref: "paper", x0: PROVISIONAL, x1: "2026-09-30", y0: 0, y1: 1,
      fillcolor: "#76857c", opacity: 0.07, line: {width: 0}, layer: "below"};
  }
  const provisionalNote = {xref: "x", yref: "paper", x: "2026-05-15", y: 1, yanchor: "bottom", showarrow: false,
    text: "Provisional", font: {size: 11, color: C.muted}};

  // ---------- charts ----------
  const charts = {
    sales_monthly() {
      const f = state.filters;
      const d = R("market_monthly").filter((r) => r.region === f.region && r.property_type === f.property_type);
      const colors = d.map((r) => r.sale_month === "2025-03-01" ? C.orange : r.sale_month >= PROVISIONAL ? C.greenSoft : C.green);
      const mar = d.find((r) => r.sale_month === "2025-03-01");
      draw("sales_monthly", [{type: "bar", x: d.map((r) => r.sale_month), y: d.map((r) => r.sales_count),
        marker: {color: colors, cornerradius: 3}, name: "Sales",
        customdata: d.map((r) => [monthLabel(r.sale_month), r.sale_month >= PROVISIONAL ? " (provisional)" : ""]),
        hovertemplate: "%{customdata[0]}%{customdata[1]}<br><b>%{y:,}</b> sales<extra></extra>"}],
      {shapes: [provisionalShape()], annotations: [provisionalNote, mar && {x: "2025-03-01", y: mar.sales_count, text: "Mar 2025: stamp duty deadline",
        showarrow: true, arrowhead: 0, ax: -90, ay: -8, font: {size: 12, color: C.ink}, arrowcolor: C.muted}].filter(Boolean),
        xaxis: {type: "date", tickformat: "%b %Y", dtick: "M6", linecolor: C.line, tickfont: {color: C.muted}},
        yaxis: {gridcolor: C.grid, tickfont: {color: C.muted}, tickformat: ",~s"}, showlegend: false});
    },
    median_price_monthly() {
      const f = state.filters;
      const d = R("market_monthly").filter((r) => r.region === f.region && r.property_type === f.property_type);
      const firm = d.filter((r) => r.sale_month < PROVISIONAL), prov = d.filter((r) => r.sale_month >= "2025-12-01");
      const tr = (rs, dash, name) => ({type: "scatter", mode: "lines", x: rs.map((r) => r.sale_month), y: rs.map((r) => r.median_price),
        line: {color: C.green, width: 2, dash}, name, hovertemplate: "%{x|%b %Y}<br><b>£%{y:,.0f}</b> median<extra></extra>"});
      draw("median_price_monthly", [tr(firm, "solid", "Median price"), tr(prov, "dot", "Provisional")],
        {shapes: [provisionalShape()], showlegend: false, hovermode: "x",
          xaxis: {type: "date", tickformat: "%b %y", linecolor: C.line, tickfont: {color: C.muted}},
          yaxis: {gridcolor: C.grid, tickprefix: "£", tickformat: ",.0f", tickfont: {color: C.muted}, rangemode: "normal"}});
    },
    region_price_change() {
      const d = R("region_price_change").filter((r) => r.region !== "All").sort((a, b) => a.median_change - b.median_change);
      const hl = state.filters.region;
      const all = R("region_price_change").find((r) => r.region === "All");
      draw("region_price_change", [
        {type: "scatter", mode: "markers", name: "Headline median change", y: d.map((r) => r.region), x: d.map((r) => r.median_change),
          error_x: {type: "data", symmetric: false, array: d.map((r) => r.ci_high - r.median_change),
            arrayminus: d.map((r) => r.median_change - r.ci_low), color: "#b9c6b6", thickness: 2, width: 0},
          marker: {size: 10, color: d.map((r) => r.region === hl ? C.orange : C.green), line: {color: "#fff", width: 2}},
          customdata: d.map((r) => [r.ci_low, r.ci_high, r.sales_2025, r.significant ? "" : " · not distinguishable from zero"]),
          hovertemplate: "<b>%{y}</b><br>Median %{x:+.1%} (95%% CI %{customdata[0]:+.1%} to %{customdata[1]:+.1%})<br>%{customdata[2]:,} sales in 2025%{customdata[3]}<extra></extra>"},
        {type: "scatter", mode: "markers", name: "Mix-adjusted change", y: d.map((r) => r.region), x: d.map((r) => r.mix_adjusted_change),
          marker: {size: 9, symbol: "circle-open", color: C.blue, line: {width: 2}},
          hovertemplate: "<b>%{y}</b><br>Mix-adjusted %{x:+.1%}<extra></extra>"}],
      {margin: {l: 170, r: 16, t: 26, b: 36}, legend: {orientation: "h", x: 0, y: 1.1},
        shapes: [{type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: {color: C.line, width: 1}},
          {type: "line", x0: all.median_change, x1: all.median_change, yref: "paper", y0: 0, y1: 1, line: {color: C.green, width: 1, dash: "dot"}}],
        annotations: [{x: all.median_change, yref: "paper", y: 0, yanchor: "top", text: "E&W " + fmtPct(all.median_change), showarrow: false, font: {size: 10.5, color: C.green}, yshift: -2}],
        xaxis: {tickformat: "+.0%", gridcolor: C.grid, zeroline: false, tickfont: {color: C.muted}},
        yaxis: {tickfont: {color: C.ink2}, gridcolor: "rgba(0,0,0,0)", automargin: true}});
    },
    band_vs_expected() {
      const d = R("pullforward_monthly").filter((r) => r.sale_month >= "2024-01-01");
      const bands = [...new Set(d.map((r) => r.price_band))].sort();
      const months = [...new Set(d.map((r) => r.sale_month))].sort();
      const z = bands.map((b) => months.map((m) => { const r = d.find((x) => x.price_band === b && x.sale_month === m); return r ? r.actual / r.expected - 1 : null; }));
      const cd = bands.map((b) => months.map((m) => { const r = d.find((x) => x.price_band === b && x.sale_month === m); return r ? [Math.round(r.actual), Math.round(r.expected), monthLabel(m)] : null; }));
      draw("band_vs_expected", [{type: "heatmap", x: months, y: bands.map(bandLabel), z, customdata: cd, zmid: 0, zmin: -0.8, zmax: 0.8,
        xgap: 2, ygap: 2,
        colorscale: [[0, "#1c5cab"], [0.25, "#86b6ef"], [0.5, "#f0efec"], [0.75, "#f0a08f"], [1, "#b8322f"]],
        colorbar: {tickformat: "+.0%", thickness: 10, len: 0.9, outlinewidth: 0, tickfont: {color: C.muted, size: 11}, title: {text: "vs expected", font: {size: 11, color: C.muted}}},
        hovertemplate: "<b>%{y}</b> · %{customdata[2]}<br>%{customdata[0]:,} sales vs %{customdata[1]:,} expected<br><b>%{z:+.0%}</b><extra></extra>"}],
      {margin: {l: 100, r: 10, t: 26, b: 40}, xaxis: {type: "date", tickformat: "%b %y", dtick: "M2", tickfont: {color: C.muted}},
        yaxis: {autorange: "reversed", tickfont: {color: C.ink2}},
        shapes: [{type: "line", x0: "2025-03-16", x1: "2025-03-16", yref: "paper", y0: -0.02, y1: 1.02, line: {color: C.ink, width: 1.5, dash: "dot"}}],
        annotations: [{x: "2025-03-16", yref: "paper", y: 1.02, yanchor: "bottom", text: "1 April 2025 change", showarrow: false, font: {size: 11, color: C.ink}}]});
    },
    pullforward_by_band() {
      const d = R("pullforward_summary");
      const x = d.map((r) => bandLabel(r.price_band));
      draw("pullforward_by_band", [
        {type: "bar", name: "Extra sales, Jan–Mar 2025", x, y: d.map((r) => r.excess_jan_mar), marker: {color: C.blue, cornerradius: 3},
          hovertemplate: "%{x}<br>%{y:,.0f} more sales than expected<extra></extra>"},
        {type: "bar", name: "Missing sales, Apr–Jun 2025", x, y: d.map((r) => r.shortfall_apr_jun), marker: {color: C.orange, cornerradius: 3},
          customdata: d.map((r) => r.payback), hovertemplate: "%{x}<br>%{y:,.0f} fewer than expected<br>Payback %{customdata:.0%}<extra></extra>"}],
      {barmode: "group", bargroupgap: 0.08, margin: {l: 56, r: 10, t: 30, b: 70}, xaxis: {tickangle: -30, tickfont: {color: C.muted, size: 11}},
        yaxis: {gridcolor: C.grid, tickformat: ",~s", tickfont: {color: C.muted}}});
    },
    sdlt_increase() {
      const d = R("sdlt_increase");
      const x = d.map((r) => fmtGBP(r.price));
      draw("sdlt_increase", [
        {type: "bar", name: "Standard buyer", x, y: d.map((r) => r.standard_increase), marker: {color: C.blue, cornerradius: 3},
          customdata: d.map((r) => [r.standard_before, r.standard_after]),
          hovertemplate: "Price %{x}<br>Standard: £%{customdata[0]:,.0f} → £%{customdata[1]:,.0f}<br><b>+£%{y:,.0f}</b><extra></extra>"},
        {type: "bar", name: "First-time buyer", x, y: d.map((r) => r.first_time_buyer_increase), marker: {color: C.orange, cornerradius: 3},
          customdata: d.map((r) => [r.first_time_buyer_before, r.first_time_buyer_after]),
          hovertemplate: "Price %{x}<br>First-time buyer: £%{customdata[0]:,.0f} → £%{customdata[1]:,.0f}<br><b>+£%{y:,.0f}</b><extra></extra>"}],
      {barmode: "group", bargroupgap: 0.08, margin: {l: 60, r: 10, t: 30, b: 40},
        xaxis: {title: {text: "Purchase price", font: {size: 11, color: C.muted}}, tickfont: {color: C.muted}},
        yaxis: {gridcolor: C.grid, tickprefix: "£", tickformat: ",.0f", tickfont: {color: C.muted}}});
    },
    band_monthly() {
      const reg = state.filters.region;
      const pick = [["01 Under £125k", C.aqua], ["02 £125k–250k", C.blue], ["04 £300k–425k", C.orange]];
      const d = R("price_band_monthly").filter((r) => r.region === reg);
      const traces = pick.map(([b, col]) => {
        const s = d.filter((r) => r.price_band === b);
        return {type: "scatter", mode: "lines", name: bandLabel(b), x: s.map((r) => r.sale_month), y: s.map((r) => r.sales_count),
          line: {color: col, width: 2}, hovertemplate: bandLabel(b) + "<br>%{x|%b %Y}: <b>%{y:,}</b><extra></extra>"};
      });
      draw("band_monthly", traces, {shapes: [provisionalShape()], annotations: [provisionalNote], hovermode: "x unified",
        xaxis: {type: "date", tickformat: "%b %Y", dtick: "M6", linecolor: C.line, tickfont: {color: C.muted}},
        yaxis: {gridcolor: C.grid, tickformat: ",~s", tickfont: {color: C.muted}}});
    },
    new_build_premium() {
      const reg = state.filters.region;
      const d = R("new_build_premium").filter((r) => r.region === reg);
      const types = ["Detached", "Semi-detached", "Terraced", "Flat/maisonette"];
      const get = (t, nb) => d.find((r) => r.property_type === t && r.is_new_build === nb) || {};
      draw("new_build_premium", [
        {type: "bar", name: "Existing homes", x: types, y: types.map((t) => get(t, false).median_price), marker: {color: C.blue, cornerradius: 3},
          customdata: types.map((t) => get(t, false).sales_count), hovertemplate: "%{x} · existing<br><b>£%{y:,.0f}</b> median · %{customdata:,} sales<extra></extra>"},
        {type: "bar", name: "New builds", x: types, y: types.map((t) => get(t, true).median_price), marker: {color: C.orange, cornerradius: 3},
          customdata: types.map((t) => [get(t, true).sales_count, get(t, true).median_price / get(t, false).median_price - 1]),
          hovertemplate: "%{x} · new build<br><b>£%{y:,.0f}</b> median · %{customdata[0]:,} sales<br>Premium %{customdata[1]:+.0%}<extra></extra>"}],
      {barmode: "group", bargroupgap: 0.08, margin: {l: 60, r: 10, t: 30, b: 40},
        yaxis: {gridcolor: C.grid, tickprefix: "£", tickformat: ",.0f", tickfont: {color: C.muted}}});
    },
    district_movers() {
      const reg = state.filters.region;
      let d = R("district_movers");
      if (reg !== "All") d = d.filter((r) => r.region === reg);
      d = d.slice().sort((a, b) => b.median_change - a.median_change);
      const n = Math.min(8, Math.floor(d.length / 2));
      const top = d.slice(0, n), bottom = d.slice(-n).reverse();
      const max = Math.max(...d.map((r) => Math.abs(r.median_change)), 0.01);
      const row = (r) => `<tr data-district="${r.district}"><td>${titleCase(r.district)} <span class="reg">${reg === "All" ? r.region : ""}</span></td>
        <td>${fmtGBP(r.median_2025)}</td><td>${fmtInt(r.sales_2025)}</td>
        <td><b>${fmtPct(r.median_change)}</b><span class="bar" style="width:${Math.abs(r.median_change) / max * 60}px;background:${r.median_change >= 0 ? C.green : C.orange}"></span></td></tr>`;
      document.getElementById("plot-district_movers").innerHTML = `<table class="dtable"><thead><tr><th>Local authority</th><th>Median 2025</th><th>Sales 2025</th><th>Change in median</th></tr></thead><tbody>
        <tr class="sep"><td colspan="4">Largest rises</td></tr>${top.map(row).join("")}
        <tr class="sep"><td colspan="4">Largest falls</td></tr>${bottom.map(row).join("")}</tbody></table>`;
      rendered.add("district_movers");
    },
  };
  const titleCase = (s) => s.toLowerCase().replace(/(^|[\s,(-])([a-z])/g, (m, a, b) => a + b.toUpperCase()).replace(/\bOf\b/g, "of").replace(/\bUpon\b/g, "upon").replace(/\bAnd\b/g, "and");

  function renderKpis() {
    const f = state.filters;
    const m = R("market_monthly").filter((r) => r.region === f.region && r.property_type === f.property_type);
    const sum = (y) => m.filter((r) => r.sale_month.startsWith(y)).reduce((a, r) => a + r.sales_count, 0);
    const s24 = sum("2024"), s25 = sum("2025");
    const mon = (k) => (m.find((r) => r.sale_month === k) || {}).sales_count || 0;
    const y = R("region_yoy").find((r) => r.region === f.region && r.property_type === f.property_type) || {};
    const nb = m.filter((r) => r.sale_month.startsWith("2025"));
    const nbShare = nb.reduce((a, r) => a + r.new_build_share * r.sales_count, 0) / Math.max(1, nb.reduce((a, r) => a + r.sales_count, 0));
    const delta = (v) => `<b class="${v >= 0 ? "up" : "down"}">${fmtPct(v)}</b>`;
    const rp = R("region_price_change").find((r) => r.region === f.region);
    const k = [
      {id: "sales_monthly", label: "Sales in 2025", value: fmtInt(s25), delta: `${delta(s25 / s24 - 1)} on 2024`},
      {id: "median_price_monthly", label: "Median price, 2025", value: "£" + fmtInt(y.median_2025 || 0),
        delta: `${delta(y.median_2025 / y.median_2024 - 1)} on 2024`},
      {id: "sales_monthly", label: "March 2025 completions", value: fmtInt(mon("2025-03-01")), delta: `${delta(mon("2025-03-01") / mon("2024-03-01") - 1)} on March 2024`, dark: true},
      {id: "sales_monthly", label: "New-build share, 2025", value: (nbShare * 100).toFixed(1) + "%", delta: "&nbsp;"},
    ];
    document.getElementById("kpis").innerHTML = k.map((x) => `<div class="kpi${x.dark ? " dark" : ""}" data-kpi-chart="${x.id}">
      <div class="kpi-label"><span>${x.label}</span></div><div class="kpi-value">${x.value}</div><div class="kpi-delta">${x.delta}</div></div>`).join("");
  }

  function renderTab(tab) {
    const ids = (M.tabs.find((t) => t.id === tab) || {charts: []}).charts;
    ids.forEach((id) => { if (charts[id]) { charts[id](); rendered.add(id); } });
    if (tab === "market") renderKpis();
  }
  function rerenderFiltered() {
    const ids = (M.tabs.find((t) => t.id === state.tab) || {charts: []}).charts;
    ids.forEach((id) => { const c = M.charts.find((x) => x.id === id); if (c && (c.filters.length || id === "region_price_change")) charts[id](); });
    if (state.tab === "market") renderKpis();
    updateScopeText();
  }
  function updateScopeText() {
    const f = state.filters;
    const scope = [f.region === "All" ? "England & Wales" : f.region, f.property_type === "All" ? "" : f.property_type.replace("/maisonette", "s").toLowerCase()].filter(Boolean).join(" · ");
    const h = document.querySelector("#tab-market h1");
    if (h) h.textContent = (f.property_type === "All" ? scope + " housing market" : scope);
    // Takeaways describe England & Wales as a whole, so hide them while filtered.
    document.querySelectorAll(".takeaway[data-takeaway]").forEach((el) => (el.hidden = f.region !== "All" || f.property_type !== "All"));
  }

  // ---------- tabs & filters ----------
  function openTab(tab) {
    document.querySelectorAll("[data-tab-panel]").forEach((s) => (s.hidden = s.dataset.tabPanel !== tab));
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    state.tab = tab;
    document.getElementById("filters").style.visibility = ["source", "architecture", "findings"].includes(tab) ? "hidden" : "visible";
    if (M.tabs.some((t) => t.id === tab)) renderTab(tab);
    if (tab === "source") Source.init();
    if (tab === "findings") Findings.load();
    if (tab.startsWith("custom-")) Custom.render(tab);
    document.getElementById("content").scrollTo?.(0, 0); window.scrollTo(0, 0);
  }
  document.querySelector("nav").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) openTab(b.dataset.tab); });

  const fRegion = document.getElementById("f-region"), fType = document.getElementById("f-type"), fReset = document.getElementById("f-reset");
  fRegion.innerHTML = M.filters.region.map((r) => `<option value="${r}">${r === "All" ? "England & Wales" : r}</option>`).join("");
  fType.innerHTML = M.filters.property_type.map((r) => `<option value="${r}">${r === "All" ? "All types" : r}</option>`).join("");
  function setFilters(f, flash) {
    if (f.region !== undefined) { state.filters.region = M.filters.region.includes(f.region) ? f.region : "All"; fRegion.value = state.filters.region; }
    if (f.property_type !== undefined) { state.filters.property_type = M.filters.property_type.includes(f.property_type) ? f.property_type : "All"; fType.value = state.filters.property_type; }
    fReset.hidden = state.filters.region === "All" && state.filters.property_type === "All";
    if (flash) [fRegion, fType].forEach((s) => { s.classList.add("changed"); setTimeout(() => s.classList.remove("changed"), 1800); });
    rerenderFiltered();
  }
  fRegion.onchange = () => setFilters({region: fRegion.value});
  fType.onchange = () => setFilters({property_type: fType.value});
  fReset.onclick = () => setFilters({region: "All", property_type: "All"});

  // Card chips: open source, ask about chart
  document.addEventListener("click", (e) => {
    const src = e.target.closest("[data-open-source]");
    if (src) { openTab("source"); Source.open(src.dataset.openSource); return; }
    const ask = e.target.closest("[data-ask-chart]");
    if (ask) { const c = M.charts.find((x) => x.id === ask.dataset.askChart); state.selectedChart = c.id;
      window.dispatchEvent(new CustomEvent("plotline:select", {detail: {chart_id: c.id, label: c.title}})); return; }
    const kpi = e.target.closest("[data-kpi-chart]");
    if (kpi) highlight(kpi.dataset.kpiChart);
  });

  function selectPoint(chartId, p) {
    const c = M.charts.find((x) => x.id === chartId);
    let label = c.title;
    const x = p.x, y = p.y, series = p.data && p.data.name;
    if (c.type === "heatmap") label = `${p.y} · ${monthLabel(p.x)} · ${fmtPct(p.z, 0)} vs expected`;
    else if (/^\d{4}-\d{2}-\d{2}/.test(String(x))) label = `${monthLabel(String(x).slice(0, 10))} · ${typeof y === "number" ? (y > 2000 && chartId.includes("price") ? "£" + fmtInt(y) : fmtInt(y)) : y}${series && series !== "Sales" ? " · " + series : ""}`;
    else if (typeof x === "number") label = `${y} · ${series} ${fmtPct(x)}`;
    else label = `${x} · ${series || ""} ${typeof y === "number" ? fmtInt(y) : y}`;
    state.selection = {chart_id: chartId, chart_title: c.title, x: String(x), y, z: p.z, series, label};
    state.selectedChart = chartId;
    window.dispatchEvent(new CustomEvent("plotline:select", {detail: {chart_id: chartId, label, point: state.selection}}));
  }

  function highlight(chartId, note) {
    const c = M.charts.find((x) => x.id === chartId);
    if (!c) return false;
    if (state.tab !== c.tab) openTab(c.tab);
    document.querySelectorAll(".card.highlight").forEach((el) => { el.classList.remove("highlight"); el.querySelector(".ai-note")?.remove(); });
    const card = document.getElementById("card-" + chartId);
    card.classList.add("highlight");
    if (note) { const n = document.createElement("div"); n.className = "ai-note"; n.textContent = note; card.appendChild(n); }
    card.scrollIntoView({behavior: "smooth", block: "center"});
    setTimeout(() => { card.classList.remove("highlight"); card.querySelector(".ai-note")?.remove(); }, 9000);
    return true;
  }

  // ---------- custom tabs (assistant: "save this analysis as another tab") ----------
  const Custom = {
    tabs: {},
    add({title, figure, note}) {
      const id = "custom-" + Object.keys(this.tabs).length;
      this.tabs[id] = {title, figure, note};
      const nav = document.getElementById("custom-nav");
      nav.hidden = false;
      const b = document.createElement("button");
      b.className = "nav-item"; b.dataset.tab = id;
      b.innerHTML = `<span class="nav-ico ico-star"></span>${escapeHtml(title)}`;
      nav.appendChild(b);
      const s = document.createElement("section");
      s.className = "tab"; s.dataset.tabPanel = id; s.hidden = true;
      s.innerHTML = `<div class="page-head"><h1>${escapeHtml(title)}</h1></div>
        ${note ? `<div class="takeaway"><span class="takeaway-label">Note</span><p>${escapeHtml(note)}</p></div>` : ""}
        <article class="card"><div class="plot" style="height:420px" id="plot-${id}"></div></article>`;
      document.getElementById("custom-sections").appendChild(s);
      openTab(id);
      return id;
    },
    render(id) { const t = this.tabs[id]; if (t && t.figure) Plotly.react("plot-" + id, t.figure.data, layout(t.figure.layout || {}), CONFIG); },
  };

  // ---------- public API for the conversational layer ----------
  window.PlotlineDashboard = {
    manifest: M,
    getContext() {
      return {active_tab: state.tab, filters: Object.assign({}, state.filters), selected_chart: state.selectedChart,
        selection: state.selection, visible_charts: (M.tabs.find((t) => t.id === state.tab) || {charts: []}).charts};
    },
    clearSelection() { state.selection = null; state.selectedChart = null; },
    apply(action) {
      const a = action || {};
      switch (a.type) {
        case "open_tab": if (document.querySelector(`[data-tab-panel="${a.tab}"]`)) { openTab(a.tab); return {ok: true}; } return {ok: false, error: "unknown tab"};
        case "set_filters": if (!M.tabs.some((t) => t.id === state.tab)) openTab("market"); setFilters(a.filters || {}, true); return {ok: true, filters: state.filters};
        case "highlight_chart": return {ok: highlight(a.chart_id, a.note)};
        case "add_tab": return {ok: true, tab: Custom.add(a)};
        default: return {ok: false, error: "unsupported action " + a.type};
      }
    },
    getRole: () => document.getElementById("role").value,
    layout,
  };

  // ---------- Source browser ----------
  const ROLE_NOTES = {
    "dashboard.json": "Manifest the assistant reads",
    "1_data/samples/raw_as_published.csv": "Raw data as published (no headers)",
    "1_data/samples/analytics_sales.csv": "Modelled table, sample rows",
    "2_models/analytics_sales.sql": "Data model",
    "3_scout/catalog.yml": "Scout catalog",
    "4_semantic_layer/metrics.yml": "Metric definitions",
    "7_dashboard/build_dashboard.py": "Builds this page",
    "plotline/tools.py": "Assistant tools",
  };

  const Source = {
    ready: false, current: null,
    async init() {
      if (this.ready) return;
      this.ready = true;
      const el = document.getElementById("source-tree");
      try {
        const tree = await (await fetch("/api/source/tree")).json();
        el.innerHTML = tree.groups.map((g) => `<h4>${g.title}</h4>` + g.files.map((f) => {
          const parts = f.split("/");
          return `<button class="${parts.length === 1 ? "top" : ""}" data-src="${f}" title="${f}">${f}</button>`;
        }).join("")).join("");
        el.onclick = (e) => { const b = e.target.closest("[data-src]"); if (b) this.open(b.dataset.src); };
        if (!this.current) this.open("dashboard.json");
      } catch (err) {
        el.innerHTML = `<p class="muted">Start the Plotline server (<code>python -m plotline.server</code>) to browse source.</p>`;
      }
    },
    async open(path) {
      this.current = path;
      await this.init();
      document.querySelectorAll("#source-tree [data-src]").forEach((b) => b.classList.toggle("on", b.dataset.src === path));
      document.querySelectorAll("#pipeline li").forEach((li) => li.classList.toggle("on", li.dataset.openSource === path));
      const head = document.getElementById("viewer-head"), body = document.getElementById("viewer-body");
      head.innerHTML = `<b>${path}</b><span>${ROLE_NOTES[path] || ROLE_NOTES[path.replace(/^dist\/threshold\//, "")] || ""}</span>`;
      body.innerHTML = `<div class="note">Loading…</div>`;
      const res = await fetch("/api/source/file?path=" + encodeURIComponent(path));
      const j = await res.json();
      if (j.kind === "table") {
        body.innerHTML = `<div class="note">${j.rows.toLocaleString()} rows · ${j.columns.length} columns · showing first ${j.preview.length}</div>
          <table><thead><tr>${j.columns.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${j.preview.map((r) => `<tr>${r.map((v) => `<td>${escapeHtml(String(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
      } else {
        body.innerHTML = `<pre>${highlightCode(j.text || j.error || "", path).split("\n").map((l) => `<span class="ln">${l || " "}</span>`).join("")}</pre>`;
      }
      document.querySelector(".viewer-body").scrollTop = 0;
    },
  };

  function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }
  function highlightCode(src, path) {
    const ext = path.split(".").pop();
    const KW = {
      sql: /\b(SELECT|FROM|WHERE|GROUP BY|GROUPING SETS|ORDER BY|AND|OR|AS|WITH|COUNT|MEDIAN|AVG|SUM|CASE|WHEN|THEN|ELSE|END|FILTER|IN|LIMIT|JOIN|LEFT|ON|BETWEEN|DATE|coalesce|year)\b/g,
      py: /\b(def|return|import|from|for|in|if|else|elif|class|with|as|not|and|or|None|True|False|lambda|try|except|raise|yield|while)\b/g,
      js: /\b(const|let|var|function|return|if|else|for|async|await|new|class|switch|case|default|try|catch|this)\b/g,
    }[ext === "html" ? "js" : ext];
    const out = [];
    for (const line of src.split("\n")) {
      let l = line.length > 600 ? line.slice(0, 600) + " … [" + (line.length - 600).toLocaleString() + " more characters: the embedded chart data]" : line;
      l = escapeHtml(l);
      const cm = ext === "sql" ? /(--.*)$/ : ["py", "yml", "yaml"].includes(ext) ? /(#.*)$/ : ext === "js" ? /(\/\/.*)$/ : null;
      let comment = "";
      if (cm) { const m = l.match(cm); if (m && !/["'][^"']*$/.test(l.slice(0, m.index))) { comment = `<span class="tk-c">${m[1]}</span>`; l = l.slice(0, m.index); } }
      l = l.replace(/(&quot;.*?&quot;|'[^']*')/g, '<span class="tk-s">$1</span>');
      if (ext === "json") l = l.replace(/^(\s*)<span class="tk-s">(&quot;[^&]*&quot;)<\/span>:/, '$1<span class="tk-key">$2</span>:');
      if (["yml", "yaml"].includes(ext)) l = l.replace(/^(\s*-?\s*)([\w.]+):/, '$1<span class="tk-key">$2</span>:');
      if (KW) l = l.replace(KW, (m) => `<span class="tk-k">${m}</span>`);
      out.push(l + comment);
    }
    return out.join("\n");
  }

  // ---------- Architecture: light up on tool calls ----------
  const COMPONENT_COLOR = {context: "#40916c", semantic: "#b07d1e", scout: "#2a78d6", query: "#1b7f8c", python: "#8a4fd1", dashboard: "#d1573a"};
  const STORES = {context: "extract", semantic: "warehouse", scout: "warehouse", query: "warehouse", python: "warehouse", dashboard: "findings"};
  function archReset() {
    document.querySelectorAll("#arch .on, #arch .done").forEach((n) => n.classList.remove("on", "done"));
    document.getElementById("arch-log").innerHTML = ""; document.getElementById("arch-empty").hidden = true;
  }
  function archLight(ids, color) {
    ids.forEach((id) => { const n = document.getElementById(id); if (!n) return; n.style.setProperty("--hl", color); n.style.setProperty("--hlf", color + "22"); n.classList.add("on"); });
  }
  function archSettle() { document.querySelectorAll("#arch .on").forEach((n) => { n.classList.remove("on"); if (n.tagName === "g") n.classList.add("done"); }); }
  window.addEventListener("plotline:turn", (e) => {
    if (e.detail.phase === "start") { archReset(); archLight(["arch-ui", "e-ui-api", "arch-api", "e-api-llm", "arch-llm"], "#40916c"); }
    if (e.detail.phase === "end") { archSettle(); }
  });
  window.addEventListener("plotline:step", (e) => {
    const s = e.detail;
    if (s.status === "running") {
      archSettle(); archLight(["arch-llm"], "#40916c");
      const col = COMPONENT_COLOR[s.component] || "#40916c";
      const store = ["get_metric_definition", "render_chart", "navigate_dashboard", "save_finding"].includes(s.tool) ? null : STORES[s.component];
      const ids = ["e-llm-" + s.component, "arch-" + s.component];
      if (store) ids.push(`e-${s.component}-${store}`, "arch-" + store);
      if (s.tool === "navigate_dashboard" || s.tool === "render_chart") ids.push("e-dashboard-ui", "arch-ui");
      if (s.tool === "save_finding") ids.push("e-dashboard-findings", "arch-findings");
      archLight(ids, col);
      const li = document.createElement("li");
      li.style.setProperty("--hl", col);
      li.innerHTML = `<i class="dot"></i><b>${s.tool}</b><span>${escapeHtml(s.title || "")}</span>`;
      document.getElementById("arch-log").appendChild(li);
      document.getElementById("arch-empty").hidden = true;
    }
  });

  // ---------- Findings ----------
  const Findings = {
    async load() {
      const el = document.getElementById("findings-list");
      let list = [];
      try { list = (await (await fetch(`/api/findings?dashboard_id=${M.dashboard_id}`)).json()).findings; } catch (e) { /* static mode */ }
      document.getElementById("findings-count").textContent = list.length || "";
      if (!el || state.tab !== "findings") return;
      if (!list.length) { el.innerHTML = `<div class="empty">No saved findings yet.</div>`; return; }
      el.innerHTML = list.map((f) => `<article class="finding" data-id="${f.id}">
        <div class="finding-head"><div><h3>${escapeHtml(f.title)}</h3><div class="q">Asked: “${escapeHtml(f.question || "")}”</div></div>
        <div style="display:flex;gap:8px;align-items:center"><span class="status ${f.status}">${f.status === "approved" ? "Approved" : "Draft"}</span>
        ${f.status !== "approved" ? `<button class="approve" data-approve="${f.id}">Approve</button>` : ""}</div></div>
        <div class="body">${escapeHtml(f.summary)}</div>
        ${f.figure ? `<div class="plot-sm" id="fplot-${f.id}"></div>` : ""}
        <div class="meta"><span>${(f.evidence || []).map(escapeHtml).join(" · ")}</span><span>${f.created_at.slice(0, 10)} · ${escapeHtml(f.saved_by)}</span></div>
      </article>`).join("");
      list.forEach((f) => { if (f.figure) Plotly.react("fplot-" + f.id, f.figure.data, layout(f.figure.layout || {}), CONFIG); });
      el.onclick = async (e) => {
        const b = e.target.closest("[data-approve]"); if (!b) return;
        await fetch("/api/findings/approve", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({id: b.dataset.approve, approved_by: "Head of Housing analytics"})});
        this.load();
      };
    },
  };
  window.addEventListener("plotline:finding-saved", () => Findings.load());

  // ---------- boot ----------
  // Deep links for demos: #tab=stamp_duty&region=London&type=Flat/maisonette
  const H = new URLSearchParams(location.hash.slice(1));
  setFilters({region: H.get("region") || undefined, property_type: H.get("type") || undefined});
  openTab(H.get("tab") || "market");
  Findings.load();
  window.addEventListener("plotline:layout", () => setTimeout(() => Object.values(plots).forEach((p) => p.offsetParent && Plotly.Plots.resize(p)), 300));
})();
