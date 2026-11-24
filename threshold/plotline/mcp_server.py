"""Scout MCP: the environment's data tools for any MCP client (Claude Desktop, Claude Code, ...).

Same tools, same policy as the dashboard assistant. The UI-only tools (navigate, render, save)
are left out. Two transports share one handler:

  stdio   python plotline/mcp_server.py                 (local clients start it themselves)
  HTTP    POST /mcp on plotline/server.py               (remote clients; Bearer $PLOTLINE_MCP_TOKEN)

Claude Code:  claude mcp add plotline-scout -- <abs>/.venv/bin/python <abs>/plotline/mcp_server.py
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from plotline import policy, tools  # noqa: E402

CFG = yaml.safe_load((ROOT / "plotline.yml").read_text())["mcp"]
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = ("Scout MCP for the Plotline environment. Start with search_schema or get_dashboard_context. "
                "Prefer query_metric (approved definitions) over execute_sql. Market sales are ppd_category = 'A'. "
                "Months from January 2026 are provisional. Buyer type is not recorded.")


def exposed(role: str) -> list[str]:
    allowed = policy.allowed_tools(role)
    return [t for t in CFG["tools"] if t in allowed]


def handle(msg: dict, role: str, user: str) -> dict | None:
    """Handle one JSON-RPC message. Returns the response, or None for notifications."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification (e.g. notifications/initialized)
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "plotline-scout", "version": "0.1.0"},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": n, "description": tools.TOOLS[n]["description"],
                              "inputSchema": tools.TOOLS[n]["schema"]} for n in exposed(role)]})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in exposed(role):
            return ok({"content": [{"type": "text", "text": f"Tool {name!r} is not available to role {role}."}], "isError": True})
        turn = tools.Turn(dashboard_id=tools.manifest()["dashboard_id"], role=role, user=user)
        try:
            res = tools.call(turn, name, args)
            return ok({"content": [{"type": "text", "text": json.dumps(res["content"], default=str)}], "isError": False})
        except Exception as e:  # noqa: BLE001 - tool errors are results, not protocol errors
            return ok({"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    role = os.environ.get("PLOTLINE_MCP_ROLE", CFG.get("role", "analyst"))
    user = f"mcp:{os.environ.get('USER', 'local')}"
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            out = handle(msg, role, user)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if out is not None:
            sys.stdout.write(json.dumps(out, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
