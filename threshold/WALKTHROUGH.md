# Stakeholder walkthrough

Open this folder in VS Code (`code ~/Downloads/plotline-threshold`) and start the dashboard in the terminal with `./run.sh`.

| # | Show | Open / run | Say |
|---|---|---|---|
| 1 | **Data** | `1_data/samples/raw_as_published.csv`, then `./pl tables` | 3.2m Land Registry sales, as published: no headers, codes for everything. |
| 2 | **Model** | `2_models/analytics_sales.sql`, then `1_data/samples/analytics_sales.csv` | Raw rows become one clean table: labels, regions, price bands. |
| 3 | **Scout** | `3_scout/catalog.yml` | What each table means and its traps. AI tools search this. |
| 4 | **Semantic layer** | `4_semantic_layer/metrics.yml` | One agreed definition per metric. |
| 5 | **SQL** | `5_sql/region_yoy.sql`, then `./pl sql 5_sql/region_yoy.sql` | Each chart's query, run live. |
| 6 | **Python** | `6_python/stamp_duty_pullforward.py`, then `./pl run 6_python/stamp_duty_pullforward.py` | What SQL can't do: baselines and statistics. |
| 7 | **Dashboard code** | `7_dashboard/build_dashboard.py` | The web app is written in Python. |
| 8 | **Published output** | `./pl publish`, then `8_published/threshold/dashboard.json` | The page, plus everything an AI needs to understand it. |
| 9 | **Probe it** | Browser: http://localhost:8765 → **Ask this dashboard** | Ask, filter, drill down, extend. |

Optional: `9_personalisation/house_style.yml` (answer style), `plotline.yml` (the whole environment on one page), `plotline/` (the Plotline engine).

Questions that demo well in step 9:
- Why did sales spike in March 2025?
- Show me this for London flats.
- Can we split the rush by first-time buyers?
- How much of the rush was just timing?
- Save this analysis as a new tab.

Before a take: `./run.sh --fresh`.
