#!/bin/sh
# One-command demo:  ./run.sh            (scripted assistant, no API key needed)
#                    ANTHROPIC_API_KEY=sk-... ./run.sh     (live Claude)
#                    ./run.sh --fresh    (also clears saved findings and conversations)
set -e
cd "$(dirname "$0")"
# Load the API key (and any PLOTLINE_* settings) from .env if present. Never commit .env.
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f 1_data/warehouse.duckdb ] || .venv/bin/python 1_data/ingest.py
[ "$1" = "--fresh" ] && rm -f .plotline/state.sqlite
.venv/bin/python -m plotline.publish
exec .venv/bin/python -m plotline.server
