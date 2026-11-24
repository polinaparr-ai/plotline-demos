"""Export a static, server-free copy of the published dashboard for hosting on a plain web host.

    .venv/bin/python -m plotline.export_static [out_dir]      # default: 8_published/threshold_static

Runs the assistant in scripted mode (no API calls, no cost) for every suggested question and every
role, records the event streams with their timing, and writes them next to a copy of the published
dashboard. static/replay.js answers the page's /api/* requests from those recordings, so the
dashboard, source browser and suggested questions work without a backend. Typed questions are
matched to a recording by the same keywords the scripted agent uses.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

os.environ["PLOTLINE_MODE"] = "scripted"
os.environ.pop("PLOTLINE_ACCESS_CODE", None)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plotline import agent, policy, server, store  # noqa: E402

# Story order: save_tab follows pullforward so it saves that chart.
ORDER = ["overview", "march", "london", "ftb", "collapse", "pullforward", "save_tab"]
MAX_GAP_MS = 1500


def main() -> None:
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else server.DIST.parent / "threshold_static"
    tmp = tempfile.mkdtemp()
    store.DB = pathlib.Path(tmp) / "state.sqlite"   # never touch the real findings/conversations

    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path: str, cookie: str = "") -> urllib.request.addinfourl:
        return urllib.request.urlopen(urllib.request.Request(base + path, headers={"Cookie": cookie}))

    page = get("/index.html")
    cookie = page.headers["Set-Cookie"].split(";")[0]
    api: dict[str, object] = {}
    api["/api/config"] = json.load(get("/api/config", cookie))
    api["/api/preferences"] = json.load(get("/api/preferences", cookie))
    api["/api/source/tree"] = tree = json.load(get("/api/source/tree", cookie))
    files = {}
    for g in tree["groups"]:
        for f in g["files"]:
            files[f] = json.load(get("/api/source/file?path=" + urllib.parse.quote(f), cookie))

    sugs = {s["id"]: s for s in server.SUGGESTIONS}
    manifest = json.loads((server.DIST / "dashboard.json").read_text())
    recordings: dict[str, dict[str, dict]] = {}
    seen: set[str] = set()
    for role in policy.ROLES:
        recordings[role] = {}
        conv = None
        for sid in ORDER:
            body = {"dashboard_id": manifest["dashboard_id"], "dashboard_version": manifest["version"],
                    "conversation_id": conv, "question": sugs[sid]["text"], "script_id": sid, "role": role, "context": {}}
            req = urllib.request.Request(base + "/api/dashboard/chat", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Cookie": cookie})
            events, t0, last = [], time.time(), 0
            with urllib.request.urlopen(req) as res:
                for line in res:
                    line = line.decode().strip()
                    if not line.startswith("data: "):
                        continue
                    ev = json.loads(line[6:])
                    ms = int((time.time() - t0) * 1000)
                    gap = min(ms - last, MAX_GAP_MS)
                    last = ms
                    if ev["event"] == "meta":
                        conv = ev["conversation_id"]
                    events.append([gap, ev])
            path = "/api/findings?dashboard_id=" + manifest["dashboard_id"]
            new = [f for f in json.load(get(path, cookie))["findings"] if f["id"] not in seen]
            seen.update(f["id"] for f in new)
            recordings[role][sid] = {"events": events, "findings": new}
            print(f"  {role:15} {sid:12} {len(events):4} events  {len(new)} findings")

    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(server.DIST, out)
    (out / "static").mkdir()
    keywords = {k: kws for k, (_, kws) in agent.SCRIPTS.items()}
    data = {"api": api, "files": files, "recordings": recordings, "keywords": keywords,
            "suggestions": {s["id"]: s["text"] for s in server.SUGGESTIONS}}
    (out / "static" / "recordings.js").write_text("window.PLOTLINE_STATIC = " + json.dumps(data, separators=(",", ":")) + ";\n")
    shutil.copy(pathlib.Path(__file__).parent / "sdk" / "replay.js", out / "static" / "replay.js")

    html = (out / "index.html").read_text()
    tag = '<script src="sdk/plotline-chat.js"></script>'
    assert tag in html
    html = html.replace(tag, '<script src="static/recordings.js"></script>\n<script src="static/replay.js"></script>\n' + tag, 1)
    (out / "index.html").write_text(html)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    print(f"Static export: {out}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
