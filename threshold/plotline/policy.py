"""Execution policy, enforced in code, not in the prompt.

The assistant can ask for anything. What actually runs is decided here:
  - which tools a role may call (three levels of questioning),
  - which tables SQL may touch, statement type, row caps and timeouts,
  - Python runs in a separate process with no network and a time limit.
"""
from __future__ import annotations

import pathlib
import re
import threading

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
from plotline.paths import WAREHOUSE  # noqa: E402

ALLOWED_TABLES = {"analytics.sales", "ref.district_region", "ref.district_successor", "ref.sdlt_bands"}
BLOCKED_COLUMNS = {"paon", "saon", "street"}  # address detail, only in raw.price_paid anyway
MAX_ROWS = 200
TIMEOUT_S = 20

# Level 1: understand the analysis. Level 2: interrogate the data. Level 3: extend it.
TOOL_LEVEL = {
    "get_dashboard_context": 1, "get_metric_definition": 1, "get_chart_data": 1,
    "get_source_query": 1, "navigate_dashboard": 1, "save_finding": 1,
    "search_schema": 2, "describe_table": 2, "query_metric": 2, "execute_sql": 2,
    "render_chart": 2,
    "execute_python": 3,
}
ROLES = {
    "viewer": {"label": "Viewer", "max_level": 1},
    "analyst": {"label": "Analyst", "max_level": 2},
    "data_scientist": {"label": "Data scientist", "max_level": 3},
}


class PolicyError(PermissionError):
    pass


def allowed_tools(role: str) -> set[str]:
    max_level = ROLES.get(role, ROLES["viewer"])["max_level"]
    return {t for t, lvl in TOOL_LEVEL.items() if lvl <= max_level}


def connect() -> duckdb.DuckDBPyConnection:
    # No reading local files or URLs from SQL, and no writes.
    return duckdb.connect(str(WAREHOUSE), read_only=True, config={"enable_external_access": False})


def validate_sql(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    sql = sql.strip().rstrip(";")
    try:
        stmts = duckdb.extract_statements(sql)
    except duckdb.Error as e:
        raise PolicyError(f"SQL did not parse: {e}") from e
    if len(stmts) != 1:
        raise PolicyError("Exactly one statement is allowed.")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise PolicyError(f"Only SELECT queries are allowed, got {stmts[0].type.name}.")
    try:
        tables = {t.lower() for t in con.get_table_names(sql, qualified=True)}
    except duckdb.Error as e:
        raise PolicyError(f"SQL did not parse: {e}") from e
    qualified = set()
    for t in tables:
        if "." in t:
            qualified.add(t)
        else:
            raise PolicyError(f"Use schema-qualified table names (e.g. analytics.sales), got {t!r}.")
    denied = qualified - ALLOWED_TABLES
    if denied:
        raise PolicyError(f"Table(s) not readable by the assistant: {sorted(denied)}. "
                          f"Allowed: {sorted(ALLOWED_TABLES)}.")
    used = set(re.findall(r"[a-z_]+", sql.lower()))
    if used & BLOCKED_COLUMNS:
        raise PolicyError(f"Column(s) {sorted(used & BLOCKED_COLUMNS)} are restricted.")
    return sql


def run_sql(sql: str, max_rows: int = MAX_ROWS):
    """Validate, then run with a row cap and a timeout. Returns (sql, DataFrame, truncated)."""
    con = connect()
    try:
        sql = validate_sql(con, sql)
        timer = threading.Timer(TIMEOUT_S, con.interrupt)
        timer.start()
        try:
            df = con.execute(f"SELECT * FROM ({sql}) AS q LIMIT {max_rows + 1}").df()
        except duckdb.InterruptException as e:
            raise PolicyError(f"Query stopped after {TIMEOUT_S}s.") from e
        finally:
            timer.cancel()
    finally:
        con.close()
    truncated = len(df) > max_rows
    return sql, df.head(max_rows), truncated
