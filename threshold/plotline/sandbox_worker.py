"""Python sandbox as a separate service (docker compose `sandbox`).

The container runs on an internal-only network (no route to the internet), with a read-only
filesystem except /tmp and no secrets in its environment. The app posts code plus a Parquet
input; the worker runs it with the same runner and limits as plotline/sandbox.py.
"""
from __future__ import annotations

import base64
import io
import json
import os
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from plotline import sandbox  # noqa: E402


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        df = pd.read_parquet(io.BytesIO(base64.b64decode(body["parquet"]))) if body.get("parquet") else None
        out = json.dumps(sandbox.run_local(body.get("code", ""), df), default=str).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("SANDBOX_PORT", "9000"))), H).serve_forever()
