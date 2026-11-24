"""Plotline API for published dashboards (demo server, standard library only).

    .venv/bin/python -m plotline.server            # http://localhost:8765
    ANTHROPIC_API_KEY=... .venv/bin/python -m plotline.server     # live Claude

Routes
  GET  /                        the published dashboard (dist/threshold)
  GET  /api/config              mode (live / scripted), model, suggested questions
  POST /api/dashboard/chat      question -> server-sent events (steps, text, UI actions, done)
  GET  /api/findings            saved findings for a dashboard
  POST /api/findings            save a finding from the page
  POST /api/findings/approve    approve a finding (it then feeds future answers)
  GET  /api/source/tree|file    read-only source browser for the demo

For each chat request the server: identifies the user from the session, checks they can see
the dashboard, resolves their role to an allowed tool set, loads conversation history,
runs the agent and streams events back. API keys never leave this process.
"""
from __future__ import annotations

import json
import mimetypes
import os
import pathlib
import secrets
import sys
import time
import traceback
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plotline import agent, mcp_server, personalisation, policy, store, tools  # noqa: E402

from plotline.paths import PUBLISHED as DIST  # noqa: E402
PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")              # 0.0.0.0 inside a container
ACCESS_CODE = os.environ.get("PLOTLINE_ACCESS_CODE")   # set this on any public deployment

LOGIN_PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>Threshold</title>
<body style="font:15px Inter,system-ui,sans-serif;background:#f3f4ee;display:grid;place-items:center;height:100vh;margin:0">
<form method=post action=/login style="background:#fff;padding:28px 30px;border-radius:14px;border:1px solid #e1e7de;width:300px">
<h2 style="margin:0 0 6px;color:#174e3c">Threshold</h2><p style="color:#76857c;margin:0 0 16px">Enter the access code you were given.</p>
<input name=code type=password autofocus style="width:100%;padding:9px;border:1px solid #d3dccf;border-radius:8px;box-sizing:border-box">
<button style="margin-top:12px;width:100%;padding:9px;border:0;border-radius:8px;background:#174e3c;color:#fff">Open dashboard</button>
%s</form>"""

# Demo identity. In production: Supabase Auth session -> user, and a dashboard_access table.
SESSIONS: dict[str, str] = {}
DEMO_USER = "demo.analyst@client.example"
ACCESS = {DEMO_USER: {"uk_housing_threshold"}}
CONV_STATE: dict[str, dict] = {}

SUGGESTIONS = [
    {"id": "overview", "level": 1, "text": "What does this dashboard show, and how is a sale counted?"},
    {"id": "march", "level": 2, "text": "Why did sales spike in March 2025? Was it the same in every price band?"},
    {"id": "london", "level": 2, "text": "Show me this for London flats."},
    {"id": "ftb", "level": 2, "text": "Can we split the rush by first-time buyers?"},
    {"id": "pullforward", "level": 3, "text": "How much of the rush was just timing? Is the March spike statistically significant?"},
    {"id": "save_tab", "level": 1, "text": "Save this analysis as a new tab."},
    {"id": "collapse", "level": 2, "text": "Sales look much lower in 2026. Has the market collapsed?"},
]

SOURCE_GROUPS = [
    ("Your project", ["1_data/ingest.py", "1_data/samples/raw_as_published.csv", "1_data/samples/analytics_sales.csv",
                      "1_data/samples/warehouse_tables.md", "2_models/analytics_sales.sql", "3_scout/catalog.yml",
                      "4_semantic_layer/metrics.yml", "5_sql/market_monthly.sql", "5_sql/price_band_monthly.sql",
                      "5_sql/region_yoy.sql", "5_sql/district_movers.sql", "5_sql/new_build_premium.sql",
                      "6_python/stamp_duty_pullforward.py", "6_python/regional_price_change.py",
                      "7_dashboard/build_dashboard.py", "7_dashboard/template.html", "7_dashboard/static/dashboard.js",
                      "9_personalisation/house_style.yml", "plotline.yml"]),
    ("Published · 8_published/threshold", None),
    ("Plotline platform", ["plotline/publish.py", "plotline/tools.py", "plotline/agent.py", "plotline/policy.py",
                           "plotline/semantic.py", "plotline/scout.py", "plotline/sandbox.py", "plotline/store.py",
                           "plotline/server.py", "plotline/sdk/plotline-chat.css"]),
]


def published_files() -> list[str]:
    order = {"index.html": 0, "dashboard.json": 1, "semantic_layer.json": 2}
    files = [str(p.relative_to(DIST)) for p in DIST.rglob("*") if p.is_file() and not str(p.relative_to(DIST)).startswith("assets/")
             and not p.name.endswith(".css")]
    return sorted(files, key=lambda f: (order.get(f, 9), f.count("/"), f))


def source_tree() -> dict:
    groups = []
    for title, files in SOURCE_GROUPS:
        groups.append({"title": title, "files": published_files() if files is None else files})
    return {"groups": groups}


def resolve_source(path: str) -> pathlib.Path | None:
    allowed = {f for g in source_tree()["groups"] for f in g["files"]}
    if path not in allowed:
        return None
    cand = ROOT / path if (ROOT / path).exists() else DIST / path
    cand = cand.resolve()
    return cand if (str(cand).startswith(str(DIST.resolve())) or str(cand).startswith(str(ROOT.resolve()))) else None


class Handler(BaseHTTPRequestHandler):
    server_version = "Plotline/0.1"

    def log_message(self, fmt, *args):  # quieter console
        if args and "/api/" in str(args[0]):
            sys.stderr.write("  %s\n" % (args[0],))

    # ---------- helpers ----------
    def _user(self) -> str | None:
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        sid = c["plotline_session"].value if "plotline_session" in c else None
        return SESSIONS.get(sid)

    def _json(self, obj, status=200, extra_headers=None):
        body = json.dumps(obj, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # ---------- GET ----------
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/api/config":
            return self._json({"mode": "live" if agent.live_available() else "scripted", "model": agent.MODEL,
                               "effort": agent.EFFORT, "user": self._user(), "suggestions": SUGGESTIONS,
                               "roles": policy.ROLES})
        if url.path == "/api/findings":
            return self._json({"findings": store.list_findings(q.get("dashboard_id", "uk_housing_threshold"))})
        if url.path == "/api/preferences":
            user = self._user()
            if not user:
                return self._json({"error": "Not signed in."}, 401)
            return self._json({"current": personalisation.resolve(user),
                               "presets": {k: {"label": v["label"], "description": v["description"]}
                                           for k, v in personalisation.presets().items()}})
        if url.path == "/api/source/tree":
            return self._json(source_tree())
        if url.path == "/api/source/file":
            p = resolve_source(q.get("path", ""))
            if not p:
                return self._json({"error": "Not available in the source browser."}, 404)
            if p.suffix == ".parquet":
                import pandas as pd
                df = pd.read_parquet(p)
                prev = df.head(40).copy()
                for c in prev.columns:
                    if prev[c].dtype.kind == "f":
                        prev[c] = prev[c].round(4)
                return self._json({"kind": "table", "rows": len(df), "columns": list(df.columns),
                                   "preview": prev.astype(str).values.tolist()})
            return self._json({"kind": "text", "text": p.read_text()})
        return self._static(url.path)

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        if ACCESS_CODE and not self._user() and path == "/index.html":
            page = LOGIN_PAGE.replace("%s", "").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        target = (DIST / path.lstrip("/")).resolve()
        if not str(target).startswith(str(DIST.resolve())) or not target.is_file():
            self.send_error(404)
            return
        data = target.read_bytes()
        self.send_response(200)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text") or ctype.endswith("javascript") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        if path == "/index.html" and not self._user() and not ACCESS_CODE:
            sid = secrets.token_urlsafe(16)
            SESSIONS[sid] = DEMO_USER
            self.send_header("Set-Cookie", f"plotline_session={sid}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(data)

    # ---------- POST ----------
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/mcp":
            return self._mcp()
        if url.path == "/login":
            n = int(self.headers.get("Content-Length", 0))
            code = urllib.parse.parse_qs(self.rfile.read(n).decode()).get("code", [""])[0]
            if ACCESS_CODE and secrets.compare_digest(code, ACCESS_CODE):
                sid = secrets.token_urlsafe(16)
                SESSIONS[sid] = DEMO_USER
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"plotline_session={sid}; Path=/; HttpOnly; SameSite=Lax")
                self.end_headers()
                return None
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return None
        user = self._user()
        if not user:
            return self._json({"error": "Not signed in. Reload the dashboard."}, 401)
        body = self._body()
        if url.path == "/api/dashboard/chat":
            return self._chat(user, body)
        if url.path == "/api/findings":
            m = tools.manifest()
            f = store.save_finding(dashboard_id=m["dashboard_id"], dashboard_version=m["version"],
                                   title=body.get("title", "Finding")[:140], summary=body.get("summary", "")[:4000],
                                   question=body.get("question", ""), evidence=body.get("evidence", []),
                                   figure=body.get("figure"), saved_by=user)
            return self._json({"finding": f})
        if url.path == "/api/preferences":
            try:
                return self._json({"current": personalisation.save(user, body.get("preset", ""), body.get("custom", ""))})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if url.path == "/api/findings/approve":
            store.approve_finding(body["id"], body.get("approved_by", user))
            return self._json({"ok": True})
        self.send_error(404)

    def _mcp(self):
        """MCP over HTTP (stateless JSON responses). Remote MCP clients authenticate with a bearer token."""
        token = os.environ.get("PLOTLINE_MCP_TOKEN")
        auth = self.headers.get("Authorization", "")
        if not token or not secrets.compare_digest(auth, f"Bearer {token}"):
            return self._json({"error": "MCP needs Authorization: Bearer <PLOTLINE_MCP_TOKEN>."}, 401)
        msg = self._body()
        role = os.environ.get("PLOTLINE_MCP_ROLE", mcp_server.CFG.get("role", "analyst"))
        batch = msg if isinstance(msg, list) else [msg]
        out = [r for r in (mcp_server.handle(m, role, "mcp:remote") for m in batch) if r is not None]
        if not out:
            self.send_response(202)
            self.end_headers()
            return None
        return self._json(out if isinstance(msg, list) else out[0])

    def _chat(self, user: str, body: dict):
        m = tools.manifest()
        dash = body.get("dashboard_id")
        if dash not in ACCESS.get(user, set()) or dash != m["dashboard_id"]:
            return self._json({"error": "You don't have access to this dashboard."}, 403)
        role = body.get("role") if body.get("role") in policy.ROLES else "viewer"
        conv = body.get("conversation_id") or secrets.token_hex(8)
        question = (body.get("question") or "").strip()[:2000]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        def emit(ev: dict):
            try:
                self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        state = CONV_STATE.setdefault(conv, {})
        turn = tools.Turn(dashboard_id=dash, role=role, user=user, question=question,
                          context=body.get("context") or {}, last_chart=state.get("last_chart"),
                          evidence=list(state.get("evidence", [])), prefs=personalisation.resolve(user))
        mode = "live" if agent.live_available() else "scripted"
        stale = body.get("dashboard_version") not in (None, m["version"])
        emit({"event": "meta", "mode": mode, "model": agent.MODEL if mode == "live" else None, "role": role,
              "allowed_tools": sorted(policy.allowed_tools(role)), "conversation_id": conv,
              "dashboard_version": m["version"], "stale_page": stale, "style": turn.prefs["label"],
              "custom_instructions": bool(turn.prefs.get("custom"))})
        t0 = time.time()
        try:
            if mode == "live":
                history = store.load_conversation(conv, user, dash)
                messages, info = agent.run_live(turn, history, emit)
                store.save_conversation(conv, user, dash, messages)
            else:
                info = agent.run_scripted(turn, body.get("script_id"), emit)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            emit({"event": "error", "message": f"{type(e).__name__}: {e}"})
            info = {"level": 1, "tools": 0}
        state["last_chart"] = turn.last_chart
        state["evidence"] = turn.evidence[-10:]
        emit({"event": "done", **info, "elapsed_ms": int((time.time() - t0) * 1000), "evidence": turn.evidence[-6:],
              "has_chart": bool(turn.last_chart)})


def main():
    if not (DIST / "dashboard.json").exists():
        sys.exit("Publish first:  .venv/bin/python -m plotline.publish")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    mode = "live · " + agent.MODEL if agent.live_available() else "scripted (set ANTHROPIC_API_KEY for live Claude)"
    print(f"Threshold dashboard: http://localhost:{PORT}   assistant: {mode}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
