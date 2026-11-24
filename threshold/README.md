# Threshold · an LLM-ready Plotline dashboard

Every residential property sale in England and Wales since January 2023 (HM Land Registry, 3.2m rows): from raw CSV to SQL, Python, a published dashboard and an assistant that can explain, query and extend it.

```
./run.sh                    # dashboard + assistant at http://localhost:8765 (live Claude via .env)
./run.sh --fresh            # same, with findings, conversations and styles cleared
PLOTLINE_MODE=scripted ./run.sh   # fixed answers for word-perfect recordings
./pl help                   # run any step from the terminal
```

For the stakeholder tour, see **[WALKTHROUGH.md](WALKTHROUGH.md)**.

## Where everything lives

```
1_data/              raw Land Registry files, samples to open, ingest.py, warehouse.duckdb
2_models/            SQL that builds analytics.sales from the raw rows
3_scout/             catalog: what each table means and its traps
4_semantic_layer/    one definition per metric
5_sql/               the query behind each chart
6_python/            analysis SQL can't do: baselines, statistics
7_dashboard/         Python that builds the web app
8_published/         the output: index.html + dashboard.json manifest, SQL, methods, data
9_personalisation/   house style and answer presets
plotline/            the Plotline engine: publish, assistant, tools, policy, MCP, server
plotline.yml         the whole environment on one page
```

## Terminal

| Command | Does |
|---|---|
| `./pl tables` | List warehouse tables |
| `./pl sql 5_sql/region_yoy.sql` | Run a SQL file (or a quoted query) |
| `./pl run 6_python/stamp_duty_pullforward.py` | Run an analysis |
| `./pl refresh` | Get the latest Land Registry release (published monthly), rebuild, republish |
| `./pl publish` | Build `8_published/` |
| `./pl serve` | Start the dashboard |

## Assistant

12 tools in three levels: understand (manifest, definitions, published data), interrogate (Scout, semantic layer, read-only SQL) and extend (sandboxed Python). Roles decide which levels a user gets: Viewer 1, Analyst 1–2, Data scientist 1–3. It can also open tabs, set filters, highlight charts, add tabs and save findings.

**Style:** users pick a preset (Balanced, Visual first, Executive brief, Analyst detail) and can add their own instructions from the chat's Style button. Organisation rules live in `9_personalisation/house_style.yml`.

**MCP:** the same data tools for Claude Desktop or Claude Code:
```
claude mcp add plotline-scout -- "$PWD/.venv/bin/python" "$PWD/plotline/mcp_server.py"
```

**Cost:** about $0.03–0.05 per question, $0.25–0.30 for a Python investigation (Opus 5.5, medium effort).

## Settings
`.env` (hidden in VS Code, never committed) holds `ANTHROPIC_API_KEY`, `PLOTLINE_MCP_TOKEN` and, for any public deployment, `PLOTLINE_ACCESS_CODE`. Model and effort are in `plotline.yml`.

`Dockerfile` and `docker-compose.yml` run the same environment in containers if it ever moves to a server. They haven't been tested here.

## Data
Contains HM Land Registry data © Crown copyright and database right 2026, licensed under the Open Government Licence v3.0. ONS district-to-region lookup, OGL v3.0. Stamp Duty rates from gov.uk. "Threshold" is a fictional product name.
