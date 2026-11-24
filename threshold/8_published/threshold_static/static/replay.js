/* replay.js — serves a static Plotline export without a backend.
 *
 * Load after static/recordings.js and before sdk/plotline-chat.js. Answers the page's /api/*
 * requests from recordings made in scripted mode (plotline/export_static.py), replaying each
 * answer's events with their original timing. Findings live in this browser tab only.
 */
(function () {
  "use strict";
  const S = window.PLOTLINE_STATIC;
  const realFetch = window.fetch.bind(window);
  const KEY = "plotline_static_findings";
  const VOLUME_CHARTS = ["sales_monthly", "band_vs_expected", "band_monthly", "pullforward_by_band"];
  const NO_MATCH = "This online version replays recorded answers, so it can only answer the suggested questions. " +
    "To ask your own, request a live demo at **hello@plotlineltd.com**.";

  const findings = () => JSON.parse(sessionStorage.getItem(KEY) || "[]");
  const setFindings = (l) => sessionStorage.setItem(KEY, JSON.stringify(l));
  const addFinding = (f) => setFindings([Object.assign({}, f, {id: Math.random().toString(16).slice(2, 12),
    created_at: new Date().toISOString(), status: "draft", approved_by: null}), ...findings()]);
  const json = (obj, status) => Promise.resolve(new Response(JSON.stringify(obj), {status: status || 200, headers: {"Content-Type": "application/json"}}));

  // Same rules as agent.match_script.
  function match(question, scriptId, context) {
    if (scriptId && S.keywords[scriptId]) return scriptId;
    const q = (question || "").toLowerCase();
    let best = null, top = 0;
    for (const [id, kws] of Object.entries(S.keywords)) {
      const n = kws.filter((k) => q.includes(k)).length;
      if (n > top) { best = id; top = n; }
    }
    if (best) return best;
    return VOLUME_CHARTS.includes((context || {}).selected_chart) ? "march" : null;
  }

  function stream(events, onDone) {
    const enc = new TextEncoder();
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    return new ReadableStream({
      async start(ctrl) {
        for (const [gap, ev] of events) {
          if (gap > 0) await sleep(gap);
          ctrl.enqueue(enc.encode("data: " + JSON.stringify(ev) + "\n\n"));
        }
        onDone && onDone();
        ctrl.close();
      },
    });
  }

  function chat(body) {
    const role = S.recordings[body.role] ? body.role : "viewer";
    const conv = body.conversation_id || "static-" + Math.random().toString(16).slice(2, 10);
    const id = match(body.question, body.script_id, body.context);
    let events, saved = [];
    if (id) {
      const rec = S.recordings[role][id];
      events = rec.events.map(([g, ev]) => [g, ev.event === "meta" ? Object.assign({}, ev, {conversation_id: conv}) : ev]);
      saved = rec.findings.map((f) => Object.assign({}, f, {question: body.question}));
    } else {
      const words = NO_MATCH.match(/\S+\s*/g);
      events = [[0, {event: "meta", conversation_id: conv, role}], [300, {event: "text_block"}],
        ...words.map((w) => [18, {event: "text", delta: w}]),
        [0, {event: "done", level: 1, tools: 0, elapsed_ms: 300 + words.length * 18, evidence: []}]];
    }
    return Promise.resolve(new Response(stream(events, () => saved.forEach(addFinding)),
      {headers: {"Content-Type": "text/event-stream"}}));
  }

  window.fetch = function (input, init) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    const path = url.pathname.replace(/^.*(?=\/api\/)/, "");
    if (!path.startsWith("/api/")) return realFetch(input, init);
    const method = ((init && init.method) || "GET").toUpperCase();
    const body = init && init.body ? JSON.parse(init.body) : {};

    if (path === "/api/config") {
      if (window.Plotline) window.Plotline.modeLabel = () => "Recorded answers";
      return json(S.api["/api/config"]);
    }
    if (path === "/api/preferences") return json(S.api["/api/preferences"]);
    if (path === "/api/source/tree") return json(S.api["/api/source/tree"]);
    if (path === "/api/source/file") {
      const f = S.files[url.searchParams.get("path")];
      return f ? json(f) : json({error: "Not available in the source browser."}, 404);
    }
    if (path === "/api/findings" && method === "GET") return json({findings: findings()});
    if (path === "/api/findings" && method === "POST") {
      addFinding(Object.assign({dashboard_id: "", dashboard_version: null, saved_by: "you"}, body));
      return json({ok: true});
    }
    if (path === "/api/findings/approve") {
      setFindings(findings().map((f) => f.id === body.id ? Object.assign(f, {status: "approved", approved_by: body.approved_by}) : f));
      return json({ok: true});
    }
    if (path === "/api/dashboard/chat") return chat(body);
    return json({error: "Not available in the static demo."}, 404);
  };

  // Answer style can't change recorded answers, so the style picker is hidden.
  const css = document.createElement("style");
  css.textContent = "#pl-style-btn{display:none}";
  document.head.appendChild(css);
})();
