# Meridian Commerce

A complete, locally generated commerce intelligence demo for Plotline. Meridian is a fictional presentation brand. All historical transactions come from a real, attributed public dataset; the scenario assumptions are explicitly hypothetical.

## Open the finished dashboard

Open **dist/index.html** in a browser, or use **dist/meridian-standalone.html** for a single file you can send to someone. All charts, fonts, map geometry and generated results are included locally. No API key, Python server or internet connection is required to use the built dashboard.

For a localhost preview:

```sh
python3 -m http.server 8788 --directory dist
```

Visit http://localhost:8788. The preview server serves files only; it does not execute queries or retrain models.

## Rebuild from SQL and Python

Python 3.10 or later is required. Run these commands from this folder:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build_dashboard.py
```

On Windows, use `.venv\Scripts\python` instead. The initial build downloads and reads the original 43.5 MB workbook, caches it as Parquet, creates a local DuckDB database, executes every query, trains two classifiers and writes the HTML site into `dist/`. Later builds reuse the downloaded workbook and typed cache. Delete `data/transactions.parquet` to reread the original workbook. No spreadsheet or source rows are silently overwritten.

## The five views

- **Commerce:** period and market filters, prior-year revenue comparison, reconciled Sankey revenue flows, a world map, product search and CSV export.
- **Customers:** rules-based recency/frequency/value segments, lasso selection, customer drill-down, historic spend mix and cohort activity. The snapshot is 30 November 2011. Customer views do not inherit the Commerce date filter.
- **Decision lab:** order value, volume, credit reduction, assumed contribution margin and campaign investment; a revenue bridge; a rotatable Plotly 3D surface with an interactive contour fallback when WebGL is unavailable.
- **Model diagnostics:** genuinely trained random forest and logistic regression models, ROC/AUC, precision–recall, a threshold-linked confusion matrix, F1, accuracy, Brier score and held-out permutation importance.
- **Data & logic:** source attribution, cleaning rules, reconciliation checks and an inspectable SQL library. SQL badges open the specific query behind a chart.

Press Cmd/Ctrl+K to switch views. Each view has a CSV export. Plotly provides chart hover, selection, zoom and PNG export where applicable.

## Shareable packages

- `Meridian-dashboard.zip`: the ready-to-use website and single-file HTML, with no Python required.
- `Meridian-source-and-data.zip`: source code, SQL, generated dashboard and original downloaded dataset. Regenerable Parquet/DuckDB caches and the virtual environment are deliberately excluded.
- Run `.venv/bin/python package_demo.py` after a rebuild to refresh both ZIPs and the standalone HTML.

## Project structure

```text
build_dashboard.py       Main generator: queries, modelling, figures, HTML
prepare_data.py          Original dataset download and typed cache
requirements.txt        Pinned direct Python dependencies
sql/                    Ten readable, editable SQL files
web/index.html          Dashboard template
web/style.css           Responsive design
web/app.js              Browser navigation, exploration and scenario arithmetic
web/fonts/              Local Inter fonts, with OFL licence
data/raw/               Original UCI download, workbook and Natural Earth geometry
data/transactions.parquet   Typed source rows, before analysis cleaning
data/commerce.duckdb     Local queryable database
data/source.json        Provenance, licence and source archive SHA-256
data/build-audit.json    SQL hashes, row counts, model scores, build checks
data/model-metrics.json Model evaluation results
dist/                   Ready-to-share HTML website
qa/                     Browser checks, screenshots and verification tools
```

## Definitions and limits

- The original dataset contains 1,067,371 rows from 1 December 2009 to 9 December 2011. Analysis ends on 30 November 2011 to avoid treating the incomplete final month as comparable.
- Merchandise codes must match the explicit numeric product-code pattern in `01_ledger.sql`. Non-positive prices, zero quantities and administrative lines are excluded. Exact duplicate rows are removed as a documented demo policy; that policy should be confirmed with a real client before applying it to their data.
- Negative quantities or cancellation-prefixed invoices count as credit transactions. **Net merchandise sales = gross merchandise sales minus credits**, by posting date. This is not audited accounting revenue or profit. Credits are not individually matched to original invoices.
- Customer IDs missing in the source remain included in financial totals but are excluded from customer segmentation, cohorts and model features. The Sankey reconciles to identified gross sales, not total net sales.
- All shown amounts are in GBP, including international orders. There is no source currency conversion.
- Customer cohorts measure purchase activity in each month after first observed purchase. They do not imply subscription retention or prove customer churn. Immature months are blank, not zero.
- RFM segments are transparent rules, not a fitted clustering algorithm. They use the full available purchase history up to the cutoff.
- Prior-year lines align calendar dates one year forward and aggregate by week. First and final displayed weeks can be partial. The selected date ranges are explicit.
- Decision-lab volume and order-value effects compound. Contribution = `(incremental gross + saved credits) × assumed margin − campaign investment`. No margin field exists in the source. This is sensitivity analysis, not a causal model or an out-of-sample sales forecast.
- Repeat-purchase models use 180 days of earlier behaviour to predict a purchase in the next 90 days. Training cutoff: 1 September 2010. Evaluation cutoff: 1 June 2011. IDs are excluded as inputs. The same customer can appear at both temporal snapshots. Models are untuned examples, not production-ready. The evaluation outcomes are not used in fitting.
- Browser controls explore precomputed aggregates or model outputs and run disclosed scenario arithmetic. The browser does not execute SQL or Python, contact a live database or retrain the classifiers. Edit SQL/Python and rebuild to refresh the site.
- This public-data demo contains no authentication system. Real access control belongs in the hosting/application architecture.

## Data attribution and licences

**Dataset:** Chen, D. (2012). *Online Retail II* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D. Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The dashboard contains cleaned, aggregated and modelled adaptations, with modifications documented above. Source: https://archive.ics.uci.edu/dataset/502/online+retail+ii.

**Map:** Natural Earth, 1:110m country geometry, public domain. https://www.naturalearthdata.com/about/terms-of-use/. Country markers are approximate centres and represent country-level sales, not shipping routes or customer addresses.

**Fonts:** Inter by Rasmus Andersson, distributed under the SIL Open Font License. See `web/fonts/OFL.txt` and `dist/fonts/OFL.txt`.

**Charts:** Plotly.js is bundled locally with its licence notice retained. Other Python dependencies retain their respective licences. The generated site does not make runtime requests to chart, font, map or analytics CDNs.
