/* plotline-chat.js — the conversational layer for any published Plotline dashboard.
 *
 *   <script src="/sdk/plotline-chat.js"></script>
 *   <script>Plotline.init({ dashboardId: "customer_retention", conversational: true });</script>
 *
 * Talks to the Plotline API (POST /api/dashboard/chat, server-sent events). Never holds an
 * API key and never runs code from the server: UI changes arrive as structured actions that
 * the dashboard's own window.PlotlineDashboard.apply() performs.
 */
(function () {
  "use strict";
  const COMPONENTS = {
    context: {label: "Analysis context", color: "#40916c"},
    semantic: {label: "Semantic layer", color: "#b07d1e"},
    scout: {label: "Scout", color: "#2a78d6"},
    query: {label: "Query engine", color: "#1b7f8c"},
    python: {label: "Python", color: "#8a4fd1"},
    dashboard: {label: "Dashboard", color: "#d1573a"},
  };
  const LEVELS = {1: "Understand", 2: "Interrogate", 3: "Extend"};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  function md(text) {
    const lines = esc(text).split("\n");
    let html = "", inList = false;
    const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/(^|[\s(])\*([^*]+)\*/g, "$1<em>$2</em>");
    for (const l of lines) {
      if (/^\s*[-•]\s+/.test(l)) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + inline(l.replace(/^\s*[-•]\s+/, "")) + "</li>"; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (l.trim()) html += "<p>" + inline(l) + "</p>";
    }
    return html + (inList ? "</ul>" : "");
  }

  const Plotline = {
    opts: null, config: null, busy: false, selection: null,
    conversationId: sessionStorage.getItem("plotline_conversation") || null,

    async init(opts) {
      this.opts = Object.assign({endpoint: "/api/dashboard/chat", conversational: true}, opts);
      if (!this.opts.conversational) return;
      this.mount();
      try { this.config = await (await fetch("/api/config")).json(); } catch (e) { this.config = null; }
      this.renderIntro();
      this.loadStyle();
      document.getElementById("ask-toggle")?.addEventListener("click", () => this.toggle());
      window.addEventListener("plotline:select", (e) => { this.select(e.detail); this.toggle(true); });
      window.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); this.toggle(); } });
      // Deep links for demos: #chat=open&ask=<suggestion id>&role=analyst
      const H = new URLSearchParams(location.hash.slice(1));
      if (H.get("role")) { const r = document.getElementById("role"); if (r) r.value = H.get("role"); }
      if (H.get("chat") === "open" || H.get("ask")) this.toggle(true);
      const s = H.get("ask") && (this.config?.suggestions || []).find((x) => x.id === H.get("ask"));
      if (s) setTimeout(() => this.ask(s.text, s.id), 600);
    },

    mount() {
      const el = document.createElement("aside");
      el.className = "pl-chat";
      el.innerHTML = `
        <header class="pl-head">
          <div><div class="pl-title"><span class="pl-spark"></span>Ask this dashboard</div>
          <div class="pl-sub" id="pl-mode">Connecting…</div></div>
          <div class="pl-head-actions"><button class="pl-style-btn" id="pl-style-btn" title="How answers are written"><span id="pl-style-label">Style</span> ▾</button><button class="pl-icon" id="pl-new" title="New conversation">↺</button><button class="pl-icon" id="pl-close" title="Close">✕</button></div>
        </header>
        <div class="pl-style" id="pl-style" hidden>
          <div class="pl-style-title">How should answers look?</div>
          <div class="pl-presets" id="pl-presets"></div>
          <label class="pl-style-label" for="pl-custom">Your instructions</label>
          <textarea id="pl-custom" rows="3" maxlength="800" placeholder="e.g. Give answers as visuals and keep text short. I mostly care about London."></textarea>
          <div class="pl-style-foot"><span></span><button id="pl-style-save">Save</button></div>
        </div>
        <div class="pl-trace" id="pl-trace">${Object.entries(COMPONENTS).map(([k, c]) => `<span class="pl-pill" data-c="${k}" style="--c:${c.color}"><i></i>${c.label}</span>`).join("")}</div>
        <div class="pl-log" id="pl-log"></div>
        <div class="pl-compose">
          <div class="pl-selection" id="pl-selection" hidden></div>
          <form id="pl-form"><textarea id="pl-input" rows="2" placeholder="Ask about this dashboard…"></textarea>
          <button type="submit" id="pl-send" title="Send">↑</button></form>
        </div>`;
      document.body.appendChild(el);
      this.el = el;
      el.querySelector("#pl-close").onclick = () => this.toggle(false);
      el.querySelector("#pl-style-btn").onclick = () => { const b = el.querySelector("#pl-style"); b.hidden = !b.hidden; };
      el.querySelector("#pl-style-save").onclick = () => this.saveStyle();
      el.querySelector("#pl-new").onclick = () => { this.conversationId = null; sessionStorage.removeItem("plotline_conversation"); this.renderIntro(); };
      const input = el.querySelector("#pl-input");
      el.querySelector("#pl-form").onsubmit = (e) => { e.preventDefault(); this.ask(input.value); };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.ask(input.value); } });
    },

    async loadStyle() {
      try {
        const j = await (await fetch("/api/preferences", {credentials: "include"})).json();
        this.style = j;
        this.renderStyle();
      } catch (e) { /* no server */ }
    },
    renderStyle() {
      const j = this.style; if (!j || !j.current) return;
      const box = this.el.querySelector("#pl-presets");
      box.innerHTML = Object.entries(j.presets).map(([k, p]) => `<button class="pl-preset${k === j.current.preset ? " on" : ""}" data-p="${k}"><b>${esc(p.label)}</b><span>${esc(p.description)}</span></button>`).join("");
      box.onclick = (e) => { const b = e.target.closest("[data-p]"); if (!b) return; box.querySelectorAll(".pl-preset").forEach((x) => x.classList.toggle("on", x === b)); };
      this.el.querySelector("#pl-custom").value = j.current.custom || "";
      this.el.querySelector("#pl-style-label").textContent = j.current.label + (j.current.custom ? " +" : "");
    },
    async saveStyle() {
      const preset = this.el.querySelector(".pl-preset.on")?.dataset.p || "balanced";
      const custom = this.el.querySelector("#pl-custom").value;
      const r = await fetch("/api/preferences", {method: "POST", credentials: "include", headers: {"Content-Type": "application/json"}, body: JSON.stringify({preset, custom})});
      const j = await r.json();
      if (j.current) { this.style.current = j.current; this.renderStyle(); }
      const btn = this.el.querySelector("#pl-style-save"); btn.textContent = "✓ Saved";
      setTimeout(() => { btn.textContent = "Save"; this.el.querySelector("#pl-style").hidden = true; }, 900);
    },

    toggle(force) {
      const open = force === undefined ? !document.body.classList.contains("chat-open") : force;
      document.body.classList.toggle("chat-open", open);
      window.dispatchEvent(new Event("plotline:layout"));
      if (open) setTimeout(() => this.el.querySelector("#pl-input").focus(), 250);
    },

    modeLabel() {
      const c = this.config;
      if (!c) return "Server not reachable";
      return c.mode === "live" ? `Live · ${c.model}` : "Scripted";
    },

    renderIntro() {
      this.el.querySelector("#pl-mode").textContent = this.modeLabel();
      this.el.querySelector("#pl-mode").className = "pl-sub " + (this.config && this.config.mode === "live" ? "live" : "scripted");
      const sug = (this.config && this.config.suggestions) || [];
      this.el.querySelector("#pl-log").innerHTML = `
        <div class="pl-intro">
          <div class="pl-sugs">${sug.map((s) => `<button class="pl-sug" data-script="${s.id}" data-text="${esc(s.text)}"><span class="pl-lv lv${s.level}">L${s.level}</span>${esc(s.text)}</button>`).join("")}</div>
        </div>`;
      this.el.querySelectorAll(".pl-sug").forEach((b) => (b.onclick = () => this.ask(b.dataset.text, b.dataset.script)));
    },

    select(detail) {
      this.selection = detail;
      const box = this.el.querySelector("#pl-selection");
      box.hidden = false;
      box.innerHTML = `<span>About: <b>${esc(detail.label)}</b></span><button title="Clear">✕</button>`;
      box.querySelector("button").onclick = () => { this.selection = null; box.hidden = true; window.PlotlineDashboard?.clearSelection(); };
      this.el.querySelector("#pl-input").placeholder = "Ask about this…";
    },

    async ask(text, scriptId) {
      text = (text || "").trim();
      if (!text || this.busy) return;
      this.busy = true;
      const input = this.el.querySelector("#pl-input");
      input.value = "";
      const log = this.el.querySelector("#pl-log");
      log.querySelector(".pl-intro")?.remove();
      const ctx = window.PlotlineDashboard ? window.PlotlineDashboard.getContext() : {};
      const sel = this.selection;
      log.insertAdjacentHTML("beforeend", `<div class="pl-msg pl-user">${sel ? `<div class="pl-about">${esc(sel.label)}</div>` : ""}${esc(text)}</div>`);
      const turn = document.createElement("div");
      turn.className = "pl-msg pl-bot";
      turn.innerHTML = `<div class="pl-steps"></div><div class="pl-charts"></div><div class="pl-answer"><span class="pl-thinking"><i></i><i></i><i></i></span></div><div class="pl-meta" hidden></div>`;
      log.appendChild(turn);
      this.scroll();
      this.el.querySelectorAll(".pl-pill").forEach((p) => p.classList.remove("on", "used"));
      window.dispatchEvent(new CustomEvent("plotline:turn", {detail: {phase: "start", question: text}}));

      const state = {text: "", steps: {}, evidence: [], figure: null, sql: [], tables: []};
      const body = {
        dashboard_id: this.opts.dashboardId, dashboard_version: this.opts.dashboardVersion,
        conversation_id: this.conversationId, question: text, script_id: scriptId || null,
        role: window.PlotlineDashboard ? window.PlotlineDashboard.getRole() : "viewer",
        context: Object.assign({}, ctx, sel ? {selected_chart: sel.chart_id, selection: sel.point || {label: sel.label}} : {}),
      };
      try {
        const res = await fetch(this.opts.endpoint, {method: "POST", headers: {"Content-Type": "application/json"}, credentials: "include", body: JSON.stringify(body)});
        if (!res.ok) throw new Error((await res.json()).error || res.statusText);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const {value, done} = await reader.read();
          if (done) break;
          buf += dec.decode(value, {stream: true});
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
            if (chunk.startsWith("data: ")) this.handle(JSON.parse(chunk.slice(6)), turn, state, text);
          }
        }
      } catch (err) {
        turn.querySelector(".pl-answer").innerHTML = `<p class="pl-err">${esc(err.message)}</p>`;
      }
      this.busy = false;
      this.selection = null;
      this.el.querySelector("#pl-selection").hidden = true;
      this.el.querySelector("#pl-input").placeholder = "Ask a follow-up…";
      window.PlotlineDashboard?.clearSelection();
      window.dispatchEvent(new CustomEvent("plotline:turn", {detail: {phase: "end"}}));
    },

    handle(ev, turn, state, question) {
      const steps = turn.querySelector(".pl-steps");
      if (ev.event === "meta") {
        this.conversationId = ev.conversation_id;
        if (ev.style) turn.dataset.style = ev.style + (ev.custom_instructions ? " + your instructions" : "");
        sessionStorage.setItem("plotline_conversation", ev.conversation_id);
      } else if (ev.event === "step") {
        const comp = COMPONENTS[ev.component] || COMPONENTS[(state.steps[ev.id] || {}).component] || COMPONENTS.context;
        if (ev.status === "running") {
          state.steps[ev.id] = ev;
          steps.insertAdjacentHTML("beforeend", `<details class="pl-step running" id="pl-${ev.id}-${Date.now() % 1e6}" data-step="${ev.id}" style="--c:${comp.color}">
            <summary><i class="pl-dot"></i><span class="pl-st">${esc(ev.title)}</span><span class="pl-lv lv${ev.level}">L${ev.level}</span><span class="pl-ms"></span></summary><div class="pl-detail"></div></details>`);
          const pill = this.el.querySelector(`.pl-pill[data-c="${ev.component}"]`);
          this.el.querySelectorAll(".pl-pill.on").forEach((p) => p.classList.replace("on", "used"));
          pill?.classList.add("on");
        } else {
          const node = [...steps.querySelectorAll(`[data-step="${ev.id}"]`)].pop();
          if (!node) return;
          node.classList.remove("running");
          node.classList.add(ev.status);
          node.querySelector(".pl-st").textContent = ev.title || node.querySelector(".pl-st").textContent;
          node.querySelector(".pl-ms").textContent = ev.ms != null ? (ev.ms >= 1000 ? (ev.ms / 1000).toFixed(1) + "s" : ev.ms + "ms") : "";
          node.querySelector(".pl-detail").innerHTML = this.detail(ev);
          if (ev.sql) state.sql.push(ev.sql);
          if (ev.table) state.tables.push({title: ev.title, table: ev.table});
          if (ev.chart) { state.figure = ev.chart; this.chart(turn, ev.chart); }
          node.querySelectorAll("[data-open-source]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); window.PlotlineDashboard?.apply({type: "open_tab", tab: "source"}); setTimeout(() => document.querySelector(`#source-tree [data-src="${b.dataset.openSource}"]`)?.click(), 400); }));
        }
        window.dispatchEvent(new CustomEvent("plotline:step", {detail: Object.assign({}, state.steps[ev.id] || {}, ev, {component: (state.steps[ev.id] || ev).component})}));
      } else if (ev.event === "action") {
        const r = window.PlotlineDashboard ? window.PlotlineDashboard.apply(ev.action) : {ok: false};
        const last = [...steps.querySelectorAll(".pl-step")].pop();
        if (last && r && r.ok) last.querySelector(".pl-st").insertAdjacentHTML("beforeend", ' <span class="pl-ok">✓ applied</span>');
      } else if (ev.event === "text_block") {
        if (state.text && !state.text.endsWith("\n")) state.text += "\n\n";
      } else if (ev.event === "text") {
        state.text += ev.delta;
        turn.querySelector(".pl-answer").innerHTML = md(state.text);
        this.scroll();
      } else if (ev.event === "error") {
        turn.querySelector(".pl-answer").insertAdjacentHTML("beforeend", `<p class="pl-err">${esc(ev.message)}</p>`);
      } else if (ev.event === "done") {
        this.el.querySelectorAll(".pl-pill.on").forEach((p) => p.classList.replace("on", "used"));
        if (!state.text) turn.querySelector(".pl-answer").innerHTML = "";
        const meta = turn.querySelector(".pl-meta");
        meta.hidden = false;
        const lvl = ev.level || 1;
        const usage = ev.usage ? ` · ${((ev.usage.input_tokens + ev.usage.output_tokens) / 1000).toFixed(1)}k tokens` : "";
        meta.innerHTML = `<div class="pl-meta-line"><span class="pl-lv lv${lvl}">Level ${lvl} · ${LEVELS[lvl]}</span><span>${ev.tools} tool${ev.tools === 1 ? "" : "s"} · ${Math.round(ev.elapsed_ms / 1000)}s</span></div>
          <div class="pl-actions">${state.sql.length ? `<button data-a="sql">View SQL</button>` : ""}${state.tables.length ? `<button data-a="data">View data</button>` : ""}<button data-a="save">Save finding</button></div>
          <div class="pl-extra"></div>`;
        state.evidence = ev.evidence || [];
        meta.querySelector(".pl-actions").onclick = (e) => this.metaAction(e, turn, state, question);
        this.scroll();
      }
    },

    detail(ev) {
      let h = ev.summary ? `<div class="pl-sum">${esc(ev.summary)}</div>` : "";
      if (ev.blocked) h += `<div class="pl-blocked">Blocked by policy</div>`;
      if (ev.action) h += `<div class="pl-code"><pre>${esc(JSON.stringify(ev.action.type === "add_tab" ? {type: ev.action.type, title: ev.action.title} : ev.action, null, 1))}</pre></div>`;
      if (ev.sql) h += `<div class="pl-label">SQL</div><div class="pl-code"><pre>${esc(ev.sql)}</pre></div>`;
      if (ev.code) h += `<div class="pl-label">Python</div><div class="pl-code"><pre>${esc(ev.code)}</pre></div>`;
      if (ev.stdout) h += `<div class="pl-label">Output</div><div class="pl-code"><pre>${esc(ev.stdout)}</pre></div>`;
      if (ev.table) h += this.table(ev.table, 8);
      if (ev.file) h += `<button class="pl-link" data-open-source="${esc(ev.file)}">Open ${esc(ev.file)} in Source →</button>`;
      return h;
    },

    table(t, n) {
      const rows = t.rows.slice(0, n);
      const fmt = (v) => typeof v === "number" ? (Math.abs(v) < 1 && v !== 0 ? v.toFixed(3) : v.toLocaleString("en-GB", {maximumFractionDigits: 1})) : esc(v);
      return `<div class="pl-table"><table><thead><tr>${t.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${r.map((v) => `<td>${fmt(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>${t.rows.length > n ? `<div class="pl-more">+ ${t.rows.length - n} more rows</div>` : ""}</div>`;
    },

    chart(turn, fig) {
      const box = document.createElement("div");
      box.className = "pl-chart";
      box.innerHTML = `<div class="pl-chart-title">${esc(fig.title)}</div><div class="pl-chart-plot"></div>${fig.note ? `<div class="pl-chart-note">${esc(fig.note)}</div>` : ""}`;
      turn.querySelector(".pl-charts").appendChild(box);
      const base = window.PlotlineDashboard ? window.PlotlineDashboard.layout(fig.layout) : fig.layout;
      Plotly.newPlot(box.querySelector(".pl-chart-plot"), fig.data, Object.assign(base, {height: 230, margin: Object.assign({l: 50, r: 10, t: 24, b: 50}, (fig.layout || {}).margin)}), {displayModeBar: false, responsive: true});
    },

    async metaAction(e, turn, state, question) {
      const b = e.target.closest("button"); if (!b) return;
      const extra = turn.querySelector(".pl-extra");
      if (b.dataset.a === "sql") extra.innerHTML = state.sql.map((s) => `<div class="pl-code"><pre>${esc(s)}</pre></div>`).join("");
      if (b.dataset.a === "data") extra.innerHTML = state.tables.map((t) => `<div class="pl-label">${esc(t.title)}</div>${this.table(t.table, 15)}`).join("");
      if (b.dataset.a === "save") {
        const first = state.text.split("\n").find((l) => l.trim()) || question;
        const title = first.replace(/\*\*/g, "").split(/(?<=[.!?])\s/)[0].slice(0, 120);
        await fetch("/api/findings", {method: "POST", headers: {"Content-Type": "application/json"}, credentials: "include",
          body: JSON.stringify({title, summary: state.text.replace(/\*\*/g, ""), question, evidence: state.evidence, figure: state.figure})});
        b.textContent = "✓ Saved as draft"; b.disabled = true;
        window.dispatchEvent(new Event("plotline:finding-saved"));
      }
      this.scroll();
    },

    scroll() { const log = this.el.querySelector("#pl-log"); log.scrollTop = log.scrollHeight; },
  };

  window.Plotline = Plotline;
})();
