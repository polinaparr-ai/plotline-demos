"""Semantic layer: turns a request for metrics by name into SQL.

Charts and the assistant never write their own definition of "sales" or "median price".
They ask for `sales_count by region`, and this module writes the SQL from
semantic_layer/metrics.yml, including the default filters everyone agreed on.
"""
from __future__ import annotations

import datetime as dt
import pathlib
from typing import Any

import yaml

from plotline.paths import SEMANTIC as SPEC_PATH


class SemanticError(ValueError):
    pass


def load() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text())


def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def _date(v: str) -> str:
    try:
        d = dt.date.fromisoformat(str(v)[:10])
    except ValueError as e:
        raise SemanticError(f"Not a date: {v!r} (use YYYY-MM-DD)") from e
    return f"DATE '{d.isoformat()}'"


def compile_query(metrics: list[str], dimensions: list[str] | None = None,
                  filters: dict | None = None, start: str | None = None,
                  end: str | None = None, order_by: str | None = None,
                  limit: int = 500) -> str:
    spec = load()
    dims = dimensions or []
    unknown_m = [m for m in metrics if m not in spec["metrics"]]
    unknown_d = [d for d in dims + list((filters or {}).keys()) if d not in spec["dimensions"]]
    if not metrics:
        raise SemanticError("Ask for at least one metric.")
    if unknown_m:
        raise SemanticError(f"Unknown metric(s) {unknown_m}. Available: {sorted(spec['metrics'])}")
    if unknown_d:
        raise SemanticError(f"Unknown dimension(s) {unknown_d}. Available: {sorted(spec['dimensions'])}")

    select = [f"{spec['dimensions'][d]['sql']} AS {d}" for d in dims]
    select += [f"{spec['metrics'][m]['sql']} AS {m}" for m in metrics]

    where = [f["sql"] + f"   -- {f['name']}" for f in spec["model"]["default_filters"]]
    for dim, val in (filters or {}).items():
        col = spec["dimensions"][dim]["sql"]
        if isinstance(val, list):
            where.append(f"{col} IN ({', '.join(_literal(v) for v in val)})")
        else:
            where.append(f"{col} = {_literal(val)}")
    tcol = spec["model"]["time_dimension"]
    if start:
        where.append(f"{tcol} >= {_date(start)}")
    if end:
        where.append(f"{tcol} <= {_date(end)}")

    sql = "SELECT\n    " + ",\n    ".join(select)
    sql += f"\nFROM {spec['model']['table']}"
    sql += "\nWHERE " + "\n  AND ".join(where)
    if dims:
        sql += "\nGROUP BY ALL"
        if order_by and order_by.lstrip("-") in dims + metrics:
            sql += f"\nORDER BY {order_by.lstrip('-')}{' DESC' if order_by.startswith('-') else ''}"
        else:
            sql += "\nORDER BY " + ", ".join(str(i + 1) for i in range(len(dims)))
    sql += f"\nLIMIT {int(min(limit, 500))}"
    return sql


def definition(name: str) -> dict:
    spec = load()
    if name in spec["metrics"]:
        m = dict(spec["metrics"][name])
        m["name"] = name
        m["applied_filters"] = spec["model"]["default_filters"]
        m["table"] = spec["model"]["table"]
        m["freshness"] = spec["model"]["freshness"]
        m["example_sql"] = compile_query([name], ["sale_year"])
        return m
    if name in spec["dimensions"]:
        return {"name": name, "kind": "dimension", **spec["dimensions"][name]}
    if name in spec.get("glossary", {}):
        return {"name": name, "kind": "glossary", "definition": spec["glossary"][name]}
    raise SemanticError(
        f"No metric, dimension or glossary term called {name!r}. "
        f"Metrics: {sorted(spec['metrics'])}. Dimensions: {sorted(spec['dimensions'])}.")
