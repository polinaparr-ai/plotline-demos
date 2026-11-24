"""Where everything lives. Read from plotline.yml so the layout is defined in one place."""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = yaml.safe_load((ROOT / "plotline.yml").read_text())

RAW = ROOT / CONFIG["data"]["raw"]
SAMPLES = ROOT / CONFIG["data"]["samples"]
WAREHOUSE = ROOT / CONFIG["data"]["warehouse"]
MODELS = ROOT / CONFIG["models"]["sql"]
SCOUT_CATALOG = ROOT / CONFIG["scout"]["catalog"]
SEMANTIC = ROOT / CONFIG["semantic_layer"]["definitions"]
SQL = ROOT / CONFIG["analysis"]["sql"]
PYTHON = ROOT / CONFIG["analysis"]["python"]
DASHBOARD_BUILD = ROOT / CONFIG["dashboards"][0]["build"]
DASHBOARD = DASHBOARD_BUILD.parent
PUBLISHED = ROOT / CONFIG["dashboards"][0]["publish_to"]
HOUSE_STYLE = ROOT / CONFIG["personalisation"]["house_style"]
STATE_DB = ROOT / CONFIG["store"]["path"]
