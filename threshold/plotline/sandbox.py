"""Level 3: run assistant-written Python in an isolated worker.

Isolation in this demo (macOS):
  - separate process, `python -I` (ignores env vars and user site-packages),
  - `sandbox-exec` profile: no network at all, file writes only inside its own temp folder,
  - CPU limit and wall-clock timeout, output size caps.
Data goes in as a Parquet file produced by a policy-checked SQL query; the worker never
gets a database connection. In production this would be a container or Firecracker VM per
request (or a managed code-execution sandbox), with the same contract.
"""
from __future__ import annotations

import json
import os
import pathlib
import resource
import shutil
import subprocess
import sys
import tempfile

TIMEOUT_S = 25
MAX_STDOUT = 6000
PYTHON = sys.executable

RUNNER = r'''
import io, json, sys, contextlib, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from scipy import stats
df = pd.read_parquet("input.parquet") if __import__("os").path.exists("input.parquet") else None
ns = {"pd": pd, "np": np, "stats": stats, "df": df}
buf = io.StringIO()
err = None
try:
    with contextlib.redirect_stdout(buf):
        exec(compile(open("code.py").read(), "analysis.py", "exec"), ns)
except Exception as e:
    import traceback
    err = "".join(traceback.format_exception_only(type(e), e)).strip()
def clean(v):
    if isinstance(v, pd.DataFrame):
        return {"columns": [str(c) for c in v.columns], "rows": json.loads(v.head(100).to_json(orient="values", date_format="iso"))}
    if isinstance(v, pd.Series):
        return json.loads(v.head(100).to_json(date_format="iso"))
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v)
    if isinstance(v, dict): return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [clean(x) for x in v]
    return v
out = {"stdout": buf.getvalue(), "error": err}
try:
    out["result"] = clean(ns.get("result"))
    json.dumps(out["result"])
except Exception:
    out["result"] = repr(ns.get("result"))[:2000]
open("output.json", "w").write(json.dumps(out, default=str))
'''


def _profile(workdir: str) -> str:
    return f"""(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{workdir}") (literal "/dev/null") (literal "/dev/dtracehelper"))
"""


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (TIMEOUT_S, TIMEOUT_S + 2))


def run(code: str, input_df=None) -> dict:
    """Run locally, or in the separate sandbox service when PLOTLINE_SANDBOX_URL is set."""
    url = os.environ.get("PLOTLINE_SANDBOX_URL")
    if not url:
        return run_local(code, input_df)
    import base64
    import io
    import urllib.request
    payload = {"code": code}
    if input_df is not None:
        buf = io.BytesIO()
        input_df.to_parquet(buf, index=False)
        payload["parquet"] = base64.b64encode(buf.getvalue()).decode()
    req = urllib.request.Request(url.rstrip("/") + "/run", json.dumps(payload).encode(), {"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(req, timeout=TIMEOUT_S + 10).read())
    out["isolation"] = "sandbox service: separate container, no internet route, read-only filesystem, no secrets"
    return out


def run_local(code: str, input_df=None) -> dict:
    work = tempfile.mkdtemp(prefix="plotline-py-")
    work_real = str(pathlib.Path(work).resolve())
    try:
        p = pathlib.Path(work_real)
        (p / "code.py").write_text(code)
        (p / "runner.py").write_text(RUNNER)
        if input_df is not None:
            input_df.to_parquet(p / "input.parquet", index=False)
        cmd = [PYTHON, "-I", "runner.py"]
        if shutil.which("sandbox-exec"):
            cmd = ["sandbox-exec", "-p", _profile(work_real)] + cmd
        try:
            proc = subprocess.run(cmd, cwd=work_real, capture_output=True, text=True, timeout=TIMEOUT_S,
                                  env={"PYTHONDONTWRITEBYTECODE": "1", "MPLCONFIGDIR": work_real, "HOME": work_real},
                                  preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return {"error": f"Stopped after {TIMEOUT_S}s.", "stdout": "", "result": None}
        out_file = p / "output.json"
        if not out_file.exists():
            return {"error": (proc.stderr or "Worker exited without output.")[-1500:], "stdout": "", "result": None}
        out = json.loads(out_file.read_text())
        out["stdout"] = out.get("stdout", "")[:MAX_STDOUT]
        out["isolation"] = "sandbox-exec: no network, writes confined to worker folder" if cmd[0] == "sandbox-exec" else "subprocess only"
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
