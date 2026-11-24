"""Scout: data discovery over the client's warehouse.

Two halves:
  - the catalog (scout/catalog.yml): what people wrote about each table, and
  - live profiling: row counts, ranges and sample values read from the warehouse.

`search` ranks tables and columns for a plain-language question, so the assistant
(or an analyst's AI tool, via Scout MCP) gets a short, relevant answer instead of the
whole schema in its context window.
"""
from __future__ import annotations

import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
from plotline.paths import SCOUT_CATALOG as CATALOG  # noqa: E402

SYNONYMS = {
    "first": ["buyer", "ftb"], "ftb": ["first", "buyer"], "buyer": ["first", "buyer_type"],
    "price": ["price_gbp", "price_band"], "region": ["region", "district"],
    "tax": ["sdlt", "stamp"], "stamp": ["sdlt", "tax"], "duty": ["sdlt"],
    "new": ["is_new_build", "build"], "flat": ["property_type"], "house": ["property_type"],
    "council": ["district"], "area": ["district", "postcode_district", "region"],
    "address": ["paon", "saon", "street"], "mortgage": ["buyer"], "cash": ["buyer"],
    "investor": ["buyer", "ppd_category"], "repossession": ["ppd_category"],
}


def catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text())


def _tokens(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9_]+", text.lower())
    out = []
    for t in toks:
        if len(t) > 2:
            out.append(t.rstrip("s"))
            out += SYNONYMS.get(t, [])
    return out


def search(query: str, limit: int = 4) -> dict:
    cat = catalog()
    q = _tokens(query)
    hits = []
    for table, meta in cat["tables"].items():
        blob_parts = [table, meta.get("summary", ""), *meta.get("notes", [])]
        score = sum(2 for t in q if t in (table + " " + meta.get("summary", "")).lower())
        matched_cols = []
        for col, desc in meta.get("columns", {}).items():
            s = sum(3 if t in col else 1 for t in q if t in col or t in desc.lower())
            if s:
                matched_cols.append((s, col, desc))
                score += s
        matched_notes = [n for n in meta.get("notes", []) if any(t in n.lower() for t in q)]
        score += 2 * len(matched_notes)
        if score:
            hits.append({
                "table": table, "score": score, "summary": meta["summary"],
                "access": meta.get("access"), "grain": meta.get("grain"),
                "matching_columns": {c: d for _, c, d in sorted(matched_cols, reverse=True)[:6]},
                "relevant_notes": matched_notes,
            })
    hits.sort(key=lambda h: -h["score"])
    return {"query": query, "results": hits[:limit],
            "searched": f"{len(cat['tables'])} documented tables"}


def describe(con, table: str) -> dict:
    cat = catalog()["tables"]
    if table not in cat:
        raise ValueError(f"{table!r} is not in the Scout catalog. Known: {sorted(cat)}")
    meta = cat[table]
    out = {"table": table, **{k: v for k, v in meta.items() if k != "columns"}}
    schema, name = table.split(".")
    cols = con.execute("""SELECT column_name, data_type FROM information_schema.columns
                          WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position""",
                       [schema, name]).fetchall()
    out["row_count"] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    out["columns"] = [{"name": c, "type": t, "description": meta.get("columns", {}).get(c, "")}
                      for c, t in cols]
    if meta.get("access") == "assistant_readable":
        # Profiling: a few distinct values per low-cardinality text column.
        for col in out["columns"]:
            if col["type"] == "VARCHAR":
                n = con.execute(f"SELECT approx_count_distinct({col['name']}) FROM {table}").fetchone()[0]
                if n <= 12:
                    col["values"] = [r[0] for r in con.execute(
                        f"SELECT DISTINCT {col['name']} FROM {table} ORDER BY 1").fetchall()]
                else:
                    col["distinct_values_approx"] = n
            elif col["type"] in ("DATE", "BIGINT", "DOUBLE", "TIMESTAMP"):
                lo, hi = con.execute(f"SELECT min({col['name']}), max({col['name']}) FROM {table}").fetchone()
                col["range"] = [str(lo), str(hi)]
    else:
        out["profiling"] = "Skipped: table is restricted for the assistant."
    return out
