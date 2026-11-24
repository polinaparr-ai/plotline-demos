"""Plotline publish: turn an analysis project into an LLM-ready dashboard.

    .venv/bin/python -m plotline.publish

Produces dist/threshold/:
    index.html            presentation layer (built by app/build_dashboard.py)
    dashboard.json        manifest: charts, metrics, dimensions, findings, notes, lineage
    semantic_layer.json   the definitions this dashboard was built on
    queries/*.sql         the SQL behind every chart
    analysis/*.py         the methodology behind every modelled number
    data/*.parquet        the published extract each chart reads
    sdk/plotline-chat.js  the conversational layer, injected at publish time

The HTML is for people. Everything else is for the assistant: it can fetch exactly the
context it needs instead of parsing the page.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import shutil
import sys

import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from plotline import paths, policy  # noqa: E402

DIST = paths.PUBLISHED
DASHBOARD_ID = "uk_housing_threshold"


def _load_module(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


app = _load_module(paths.DASHBOARD_BUILD)


def run_queries(con) -> dict:
    frames = {}
    for sql_file in sorted(paths.SQL.glob("*.sql")):
        frames[sql_file.stem] = con.execute(sql_file.read_text()).df()
        print(f"  query     {sql_file.name:28s} {len(frames[sql_file.stem]):>6,} rows")
    return frames


def run_analysis(con) -> tuple[dict, dict]:
    frames, findings = {}, {}
    for py in sorted(paths.PYTHON.glob("*.py")):
        res = _load_module(py).run(con)
        frames.update(res["frames"])
        findings[py.stem] = res["findings"]
        print(f"  analysis  {py.name:28s} -> {', '.join(res['frames'])}")
    return frames, findings


def _release_info() -> dict:
    """When Land Registry published our files, and the latest sale they contain."""
    import email.utils
    info = {}
    rel = paths.RAW / "release.json"
    if rel.exists():
        dates = [email.utils.parsedate_to_datetime(v).date() for v in json.loads(rel.read_text()).values()]
        info["extract_date"] = max(dates).isoformat()
    con = policy.connect()
    info["latest_sale"] = con.execute("SELECT max(sale_date) FROM analytics.sales").fetchone()[0].isoformat()
    con.close()
    return info


def build_manifest(frames: dict, findings: dict) -> dict:
    spec = yaml.safe_load(paths.SEMANTIC.read_text())
    # Version bumps only when what the dashboard says changes (code, definitions or results).
    h = hashlib.sha256()
    for f in sorted([*paths.SQL.glob("*.sql"), *paths.PYTHON.glob("*.py"), paths.SEMANTIC, paths.DASHBOARD_BUILD]):
        h.update(f.read_bytes())
    for name in sorted(frames):
        h.update(pd.util.hash_pandas_object(frames[name].astype(str), index=False).values.tobytes())
    content_hash = h.hexdigest()[:16]
    previous = DIST / "dashboard.json"
    prev = json.loads(previous.read_text()) if previous.exists() else {}
    version = prev.get("version", 0) + (0 if prev.get("content_hash") == content_hash else 1)
    charts = []
    for c in app.CHARTS:
        entry = {k: v for k, v in c.items() if k != "tab"}
        entry["tab"] = c["tab"]
        df = frames[pathlib.Path(c["data"]).stem]
        entry["data_columns"] = list(df.columns)
        entry["data_rows"] = len(df)
        charts.append(entry)
    return {
        "dashboard_id": DASHBOARD_ID,
        "version": version,
        "content_hash": content_hash,
        "title": "Threshold · UK housing market monitor",
        "published_at": dt.datetime.now().isoformat(timespec="seconds"),
        "published_by": "Housing analytics team",
        "data_sources": [
            {"table": "analytics.sales", "origin": "HM Land Registry Price Paid Data, OGL v3.0",
             "rows": int(frames["market_monthly"].query("region == 'All' and property_type == 'All'").sales_count.sum())},
            {"table": "ref.district_region", "origin": "ONS LAD to Region lookup, December 2024"},
            {"table": "ref.sdlt_bands", "origin": "gov.uk SDLT rates"},
        ],
        "coverage": "England and Wales, completions January 2023 to September 2026",
        "freshness": {**spec["model"]["freshness"], **_release_info()},
        "metrics": sorted({m for c in app.CHARTS for m in c["metrics"]}),
        "dimensions": sorted({d for c in app.CHARTS for d in c["dimensions"]}),
        "filters": {"region": sorted(frames["market_monthly"].region.unique().tolist()),
                    "property_type": ["All", "Detached", "Semi-detached", "Terraced", "Flat/maisonette"]},
        "tabs": [{"id": t["id"], "title": t["title"], "heading": t["heading"],
                  "charts": [c["id"] for c in app.CHARTS if c["tab"] == t["id"]]} for t in app.TABS],
        "charts": charts,
        "key_findings": findings,
        "analyst_notes": app.ANALYST_NOTES,
        "semantic_layer": "semantic_layer.json",
        "ui_actions": ["open_tab", "set_filters", "highlight_chart", "add_tab"],
    }


def publish() -> pathlib.Path:
    print(f"Publishing {DASHBOARD_ID} -> {DIST.relative_to(ROOT)}")
    DIST.mkdir(parents=True, exist_ok=True)
    con = policy.connect()
    frames = run_queries(con)
    a_frames, findings = run_analysis(con)
    frames.update(a_frames)
    con.close()

    manifest = build_manifest(frames, findings)
    for sub in ("data", "queries", "analysis"):
        shutil.rmtree(DIST / sub, ignore_errors=True)
        (DIST / sub).mkdir(parents=True)
    for name, df in frames.items():
        df.to_parquet(DIST / "data" / f"{name}.parquet", index=False)
    for f in paths.SQL.glob("*.sql"):
        shutil.copy(f, DIST / "queries" / f.name)
    for f in paths.PYTHON.glob("*.py"):
        shutil.copy(f, DIST / "analysis" / f.name)

    spec = yaml.safe_load(paths.SEMANTIC.read_text())
    (DIST / "semantic_layer.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    (DIST / "dashboard.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    app.build(DIST, frames, findings, manifest, ROOT / "plotline" / "sdk")
    print(f"  manifest  dashboard.json v{manifest['version']} · {len(manifest['charts'])} charts")
    return DIST


if __name__ == "__main__":
    publish()
