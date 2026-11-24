"""The tools the dashboard assistant can call.

The LLM decides which tools it needs; Plotline decides what actually runs.
Every tool has:
  - a JSON schema (what Claude sees),
  - a level (1 understand / 2 interrogate / 3 extend) checked against the user's role,
  - a component (which part of Plotline it exercises, shown live in the UI),
  - an implementation that returns `content` for the model and `display` for the person.
"""
from __future__ import annotations

import ast
import json
import pathlib
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from plotline import policy, sandbox, scout, semantic, store

ROOT = pathlib.Path(__file__).resolve().parents[1]
from plotline.paths import PUBLISHED as DIST  # noqa: E402
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]  # fixed categorical order


@dataclass
class Turn:
    """Per-request state shared by tools: who is asking, what they are looking at."""
    dashboard_id: str
    role: str
    user: str
    question: str = ""
    context: dict = field(default_factory=dict)
    last_chart: dict | None = None
    last_sql: str | None = None
    evidence: list = field(default_factory=list)
    prefs: dict | None = None


def manifest() -> dict:
    return json.loads((DIST / "dashboard.json").read_text())


def _chart(chart_id: str) -> dict:
    for c in manifest()["charts"]:
        if c["id"] == chart_id:
            return c
    raise ValueError(f"No chart {chart_id!r}. Charts: {[c['id'] for c in manifest()['charts']]}")


def _records(df: pd.DataFrame, n: int = 120) -> dict:
    df = df.head(n).copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]) or (len(df) and hasattr(df[c].iloc[0], "isoformat")):
            df[c] = df[c].astype(str).str[:10]
        elif pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(4)
    return {"columns": list(df.columns), "rows": json.loads(df.to_json(orient="values"))}


# ---------------------------------------------------------------- level 1 · understand
def get_dashboard_context(turn: Turn, section: str = "overview") -> dict:
    m = manifest()
    findings = store.list_findings(m["dashboard_id"], status="approved")
    base = {"title": m["title"], "version": m["version"], "coverage": m["coverage"], "freshness": m["freshness"]}
    parts = {
        "overview": {**base, "tabs": m["tabs"], "key_findings": m["key_findings"],
                     "data_sources": m["data_sources"], "metrics": m["metrics"]},
        "charts": {"charts": [{k: c.get(k) for k in ("id", "title", "tab", "type", "description", "query",
                                                     "methodology", "metrics", "filters", "data_columns")}
                              for c in m["charts"]]},
        "notes": {"analyst_notes": m["analyst_notes"]},
        "findings": {"approved_findings": [{k: f[k] for k in ("title", "summary", "evidence", "approved_by")} for f in findings]},
    }
    content = parts if section == "all" else parts.get(section, parts["overview"])
    if section in ("overview", "all"):
        content = dict(content) if section != "all" else content
        if section == "overview":
            content["approved_findings"] = parts["findings"]["approved_findings"]
            content["analyst_notes"] = m["analyst_notes"]
    return {"content": content,
            "display": {"title": f"Read dashboard manifest · {section}",
                        "summary": f"dashboard.json v{m['version']}: {len(m['charts'])} charts, "
                                   f"{len(findings)} approved finding(s)", "file": "dashboard.json"}}


def get_metric_definition(turn: Turn, name: str) -> dict:
    d = semantic.definition(name)
    return {"content": d,
            "display": {"title": f"Semantic layer · {name}",
                        "summary": d.get("description") or d.get("definition") or d.get("label", ""),
                        "sql": d.get("example_sql"), "file": "semantic_layer.json"}}


def get_chart_data(turn: Turn, chart_id: str, filters: dict | None = None, limit: int = 200) -> dict:
    c = _chart(chart_id)
    df = pd.read_parquet(DIST / c["data"])
    applied = {}
    f = dict(turn.context.get("filters") or {})
    f.update(filters or {})
    for col in ("region", "property_type"):
        # Rollup tables carry an 'All' row per dimension; pick the user's selection or the total.
        want = f.get(col, "All")
        if col not in df.columns:
            continue
        if want == "*":  # every value except the rollup, for comparisons in one call
            df = df[df[col] != "All"]
            applied[col] = "each"
        elif isinstance(want, list):
            df = df[df[col].isin(want)]
            applied[col] = want
        elif (df[col] == "All").any() or want != "All":
            df = df[df[col] == want]
            applied[col] = want
    rec = _records(df, min(limit, 600))
    turn.evidence.append(f"chart data: {chart_id}")
    return {"content": {"chart": c["title"], "source": c["data"], "filters_applied": applied,
                        "total_rows": len(df), **rec},
            "display": {"title": f"Published data · {c['title']}",
                        "summary": f"{len(df):,} rows from {c['data']}" + (f" · {applied}" if applied else ""),
                        "table": rec}}


def _docstring_and_outline(path: pathlib.Path) -> str:
    tree = ast.parse(path.read_text())
    doc = ast.get_docstring(tree) or ""
    funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    return doc + "\n\nFunctions: " + ", ".join(funcs)


def get_source_query(turn: Turn, chart_id: str, include: str = "both", full_code: bool = False) -> dict:
    c = _chart(chart_id)
    out, files = {"chart": c["title"]}, []
    if include in ("sql", "both") and c.get("query"):
        out["sql"] = (DIST / c["query"]).read_text()
        files.append(c["query"])
    if include in ("methodology", "both") and c.get("methodology"):
        p = DIST / c["methodology"]
        out["methodology"] = p.read_text() if full_code else _docstring_and_outline(p)
        files.append(c["methodology"])
    turn.evidence.append(" + ".join(files))
    return {"content": out,
            "display": {"title": f"Source · {c['title']}", "summary": " · ".join(files) or "no source",
                        "sql": out.get("sql"), "code": out.get("methodology") if full_code else None,
                        "file": files[0] if files else None}}


# ---------------------------------------------------------------- level 2 · interrogate
def search_schema(turn: Turn, query: str) -> dict:
    res = scout.search(query)
    return {"content": res,
            "display": {"title": f"Scout · search “{query}”",
                        "summary": ", ".join(f"{r['table']} ({r['access']})" for r in res["results"]) or "no matches",
                        "file": "scout/catalog.yml"}}


def describe_table(turn: Turn, table: str) -> dict:
    con = policy.connect()
    try:
        res = scout.describe(con, table)
    finally:
        con.close()
    return {"content": res,
            "display": {"title": f"Scout · profile {table}",
                        "summary": f"{res['row_count']:,} rows · {len(res['columns'])} columns · access: {res.get('access')}"}}


def query_metric(turn: Turn, metrics: list, dimensions: list | None = None, filters: dict | None = None,
                 start: str | None = None, end: str | None = None, order_by: str | None = None,
                 limit: int = 200) -> dict:
    sql = semantic.compile_query(metrics, dimensions, filters, start, end, order_by, limit)
    sql, df, truncated = policy.run_sql(sql)
    rec = _records(df, 150)
    turn.last_sql = sql
    turn.evidence.append(f"semantic query: {', '.join(metrics)}" + (f" by {', '.join(dimensions)}" if dimensions else ""))
    return {"content": {"sql": sql, "row_count": len(df), "truncated": truncated, **rec},
            "display": {"title": f"Semantic layer query · {', '.join(metrics)}" + (f" by {', '.join(dimensions)}" if dimensions else ""),
                        "summary": f"{len(df):,} rows · SQL generated from metric definitions", "sql": sql, "table": rec}}


def execute_sql(turn: Turn, sql: str, purpose: str = "") -> dict:
    sql, df, truncated = policy.run_sql(sql)
    rec = _records(df, 150)
    turn.last_sql = sql
    turn.evidence.append("SQL: " + (purpose or "ad-hoc query"))
    return {"content": {"row_count": len(df), "truncated": truncated, **rec},
            "display": {"title": f"Read-only SQL · {purpose or 'query'}",
                        "summary": f"{len(df):,} rows" + (" (capped)" if truncated else "") + " · passed policy checks",
                        "sql": sql, "table": rec}}


def render_chart(turn: Turn, title: str, chart_type: str, x: list, series: list, y_format: str = "number",
                 x_title: str = "", note: str = "") -> dict:
    if len(series) > 6:
        raise ValueError("At most 6 series; fold the rest into 'Other'.")
    tickformat = {"percent": "+.0%", "gbp": ",.0f", "number": ",~s"}.get(y_format, ",~s")
    data = []
    for i, s in enumerate(series):
        col = s.get("color") if s.get("color") in PALETTE else PALETTE[i]
        if chart_type == "line":
            data.append({"type": "scatter", "mode": "lines+markers", "name": s["name"], "x": x, "y": s["values"],
                         "line": {"color": col, "width": 2}, "marker": {"size": 6}})
        else:
            data.append({"type": "bar", "name": s["name"], "x": x, "y": s["values"],
                         "marker": {"color": col, "cornerradius": 3}})
    layout = {"barmode": "group", "showlegend": len(series) > 1, "margin": {"l": 56, "r": 12, "t": 30, "b": 60},
              "yaxis": {"tickformat": tickformat, "tickprefix": "£" if y_format == "gbp" else "", "gridcolor": "#e9eee6"},
              "xaxis": {"title": {"text": x_title}, "type": "category" if chart_type != "line" else "-"}}
    fig = {"data": data, "layout": layout, "title": title, "note": note}
    turn.last_chart = fig
    return {"content": {"rendered": True, "title": title, "series": [s["name"] for s in series], "points": len(x)},
            "display": {"title": f"New chart · {title}", "summary": note or f"{len(series)} series, {len(x)} points",
                        "chart": fig}}


# ---------------------------------------------------------------- level 3 · extend
def execute_python(turn: Turn, code: str, input_sql: str | None = None, purpose: str = "") -> dict:
    df = None
    if input_sql:
        input_sql, df, _ = policy.run_sql(input_sql, max_rows=500_000)
    res = sandbox.run(code, df)
    turn.evidence.append("Python: " + (purpose or "analysis"))
    if res.get("error"):
        raise RuntimeError(res["error"] + ("\nstdout:\n" + res["stdout"] if res.get("stdout") else ""))
    return {"content": {"stdout": res["stdout"], "result": res.get("result"),
                        "input_rows": None if df is None else len(df)},
            "display": {"title": f"Python sandbox · {purpose or 'analysis'}",
                        "summary": f"{'' if df is None else f'{len(df):,} input rows · '}{res.get('isolation', '')}",
                        "sql": input_sql, "code": code, "stdout": res["stdout"][:1500]}}


# ---------------------------------------------------------------- dashboard control & knowledge
def navigate_dashboard(turn: Turn, action: str, tab: str | None = None, filters: dict | None = None,
                       chart_id: str | None = None, note: str | None = None, title: str | None = None) -> dict:
    m = manifest()
    tabs = [t["id"] for t in m["tabs"]] + ["source", "architecture", "findings"]
    if action == "open_tab":
        if tab not in tabs:
            raise ValueError(f"Unknown tab {tab!r}. Tabs: {tabs}")
        ui = {"type": "open_tab", "tab": tab}
        label = f"Open the {tab.replace('_', ' ')} tab"
    elif action == "set_filters":
        f = {k: v for k, v in (filters or {}).items() if k in ("region", "property_type")}
        for k, v in f.items():
            if v not in m["filters"][k]:
                raise ValueError(f"{v!r} is not a valid {k}. Options: {m['filters'][k]}")
        ui = {"type": "set_filters", "filters": f}
        label = "Set filters " + ", ".join(f"{k} = {v}" for k, v in f.items())
    elif action == "highlight_chart":
        _chart(chart_id)
        ui = {"type": "highlight_chart", "chart_id": chart_id, "note": note}
        label = f"Highlight {chart_id}"
    elif action == "add_tab":
        if not turn.last_chart:
            raise ValueError("Render a chart first with render_chart, then add it as a tab.")
        ui = {"type": "add_tab", "title": title or turn.last_chart["title"], "figure": turn.last_chart, "note": note}
        label = f"Add tab “{ui['title']}”"
    else:
        raise ValueError("action must be open_tab, set_filters, highlight_chart or add_tab")
    return {"content": {"queued_ui_action": ui["type"], "ok": True},
            "display": {"title": f"Dashboard · {label}", "summary": "",
                        "action": ui}}


def save_finding(turn: Turn, title: str, summary: str) -> dict:
    f = store.save_finding(dashboard_id=turn.dashboard_id, dashboard_version=manifest()["version"],
                           title=title, summary=summary, question=turn.question,
                           evidence=turn.evidence[-6:], figure=turn.last_chart, saved_by=turn.user)
    return {"content": {"saved": True, "id": f["id"], "status": "draft (needs approval before reuse)"},
            "display": {"title": f"Saved finding · {title}", "summary": "",
                        "finding_id": f["id"]}}


# ---------------------------------------------------------------- registry
S = {"type": "string"}
_FV = {"anyOf": [S, {"type": "array", "items": S}]}
FILTERS = {"type": "object", "properties": {"region": _FV, "property_type": _FV}, "additionalProperties": False}

TOOLS: dict[str, dict[str, Any]] = {
    "get_dashboard_context": {
        "fn": get_dashboard_context, "component": "context",
        "description": "Read the published dashboard manifest: tabs, charts, key findings, the analyst's tested hypotheses, limitations, freshness and approved findings. Call this first for questions about what the dashboard shows or how it was built.",
        "schema": {"type": "object", "properties": {"section": {"type": "string", "enum": ["overview", "charts", "notes", "findings", "all"]}}}},
    "get_metric_definition": {
        "fn": get_metric_definition, "component": "semantic",
        "description": "Get the approved definition of a metric, dimension or glossary term from the semantic layer: SQL expression, default filters, owner, caveats and data freshness.",
        "schema": {"type": "object", "properties": {"name": S}, "required": ["name"]}},
    "get_chart_data": {
        "fn": get_chart_data, "component": "context",
        "description": "Read the published results behind a chart (the extract the page draws from). Cheap: no warehouse query. Filters default to what the user has selected on the page. A filter can be a list of values, or '*' for every value, so you can compare all regions in ONE call instead of one call per region.",
        "schema": {"type": "object", "properties": {"chart_id": S, "filters": FILTERS, "limit": {"type": "integer"}}, "required": ["chart_id"]}},
    "get_source_query": {
        "fn": get_source_query, "component": "context",
        "description": "Inspect how a chart was calculated: its SQL file and/or the docstring of its Python methodology (set full_code for the whole file).",
        "schema": {"type": "object", "properties": {"chart_id": S, "include": {"type": "string", "enum": ["sql", "methodology", "both"]},
                                                    "full_code": {"type": "boolean"}}, "required": ["chart_id"]}},
    "search_schema": {
        "fn": search_schema, "component": "scout",
        "description": "Scout: search the documented warehouse for tables and columns relevant to a question, including notes on traps and access. Use when the dashboard's own data may not answer the question.",
        "schema": {"type": "object", "properties": {"query": S}, "required": ["query"]}},
    "describe_table": {
        "fn": describe_table, "component": "scout",
        "description": "Scout: profile one table: columns, types, row count, value lists and ranges.",
        "schema": {"type": "object", "properties": {"table": S}, "required": ["table"]}},
    "query_metric": {
        "fn": query_metric, "component": "semantic",
        "description": "Run a new aggregation using approved metric definitions. Prefer this to raw SQL. Metrics: sales_count, median_price, mean_price, total_value, new_build_share, leasehold_share. Dimensions: sale_month, sale_quarter, sale_year, region, country, district, property_type, tenure, is_new_build, price_band, postcode_district. Filters are {dimension: value or [values]}. start/end are YYYY-MM-DD on sale_month. order_by is a column name, prefix '-' for descending.",
        "schema": {"type": "object", "properties": {
            "metrics": {"type": "array", "items": S}, "dimensions": {"type": "array", "items": S},
            "filters": {"type": "object"}, "start": S, "end": S, "order_by": S, "limit": {"type": "integer"}},
            "required": ["metrics"]}},
    "execute_sql": {
        "fn": execute_sql, "component": "query",
        "description": "Run one read-only SELECT against the warehouse (DuckDB dialect). Allowed tables: analytics.sales, ref.district_region, ref.district_successor, ref.sdlt_bands. Use schema-qualified names. Results are capped at 200 rows, so aggregate. Remember ppd_category = 'A' for market sales.",
        "schema": {"type": "object", "properties": {"sql": S, "purpose": S}, "required": ["sql", "purpose"]}},
    "render_chart": {
        "fn": render_chart, "component": "dashboard",
        "description": "Draw a supplementary chart in the conversation with the dashboard's styling. chart_type bar or line. Each series is {name, values}. y_format number, gbp or percent (values as fractions).",
        "schema": {"type": "object", "properties": {
            "title": S, "chart_type": {"type": "string", "enum": ["bar", "line"]}, "x": {"type": "array"},
            "series": {"type": "array", "items": {"type": "object", "properties": {"name": S, "values": {"type": "array"}}, "required": ["name", "values"]}},
            "y_format": {"type": "string", "enum": ["number", "gbp", "percent"]}, "x_title": S, "note": S},
            "required": ["title", "chart_type", "x", "series"]}},
    "execute_python": {
        "fn": execute_python, "component": "python",
        "description": "Level 3: run Python (pandas as pd, numpy as np, scipy.stats as stats) in an isolated worker with no network. If input_sql is given it runs first (read-only, same policy, up to 500k rows) and the result is available as `df`. Print what you need and/or assign a JSON-friendly `result`. Use for statistical tests, baselines and models.",
        "schema": {"type": "object", "properties": {"code": S, "input_sql": S, "purpose": S}, "required": ["code", "purpose"]}},
    "navigate_dashboard": {
        "fn": navigate_dashboard, "component": "dashboard",
        "description": "Control the page with a structured action: open_tab (tab: market, stamp_duty, places, source, architecture, findings), set_filters (filters: region, property_type), highlight_chart (chart_id, optional short note shown on the chart), add_tab (adds the last rendered chart as a new tab with title and note).",
        "schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["open_tab", "set_filters", "highlight_chart", "add_tab"]},
            "tab": S, "filters": FILTERS, "chart_id": S, "note": S, "title": S}, "required": ["action"]}},
    "save_finding": {
        "fn": save_finding, "component": "dashboard",
        "description": "Save the current investigation as a draft finding (with its evidence and last chart). Only when the user asks to save. A reviewer approves it before it is reused.",
        "schema": {"type": "object", "properties": {"title": S, "summary": S}, "required": ["title", "summary"]}},
}

_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}


def validate(name: str, args: Any) -> None:
    """Tool inputs are validated here because eager input streaming skips server-side checks."""
    if not isinstance(args, dict):
        raise ValueError("Tool input must be a JSON object.")
    schema = TOOLS[name]["schema"]
    for req in schema.get("required", []):
        if req not in args:
            raise ValueError(f"Missing required field {req!r}.")
    for k, v in args.items():
        spec = schema["properties"].get(k)
        if spec is None:
            raise ValueError(f"Unknown field {k!r}.")
        t = _TYPES.get(spec.get("type"))
        if t and v is not None and not isinstance(v, t):
            raise ValueError(f"Field {k!r} should be {spec['type']}.")
        if "enum" in spec and v not in spec["enum"]:
            raise ValueError(f"Field {k!r} must be one of {spec['enum']}.")


def definitions(role: str) -> list[dict]:
    allowed = policy.allowed_tools(role)
    return [{"name": n, "description": t["description"], "input_schema": t["schema"], "eager_input_streaming": True}
            for n, t in TOOLS.items() if n in allowed]


def call(turn: Turn, name: str, args: dict) -> dict:
    if name not in TOOLS:
        raise ValueError(f"Unknown tool {name}")
    if name not in policy.allowed_tools(turn.role):
        raise policy.PolicyError(
            f"{name} is a level {policy.TOOL_LEVEL[name]} tool; the {policy.ROLES[turn.role]['label']} role allows up to level "
            f"{policy.ROLES[turn.role]['max_level']}.")
    validate(name, args)
    fn: Callable = TOOLS[name]["fn"]
    return fn(turn, **args)
