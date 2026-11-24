"""Visualisation as code: builds the Threshold web app from query results.

Called by plotline/publish.py. Everything a viewer sees is defined here:
  - CHARTS: the chart registry (also becomes the charts section of dashboard.json),
  - TABS: page structure,
  - the Plotly theme, KPI tiles and written takeaways, filled in from the data.
The browser code in app/static/dashboard.js only draws what this file describes.
"""
from __future__ import annotations

import html
import json
import pathlib
import shutil

import pandas as pd

APP = pathlib.Path(__file__).resolve().parent

TABS = [
    {"id": "market", "title": "Market", "icon": "chart",
     "heading": "England & Wales housing market",
     "lede": "Every residential sale registered with HM Land Registry since January 2023."},
    {"id": "stamp_duty", "title": "Stamp duty", "icon": "spike",
     "heading": "The April 2025 stamp duty cliff",
     "lede": "Buyers raced to complete before tax relief shrank on 1 April 2025. How much of it was timing?"},
    {"id": "places", "title": "Places", "icon": "pin",
     "heading": "Where prices moved",
     "lede": "Local authorities and property types, 2025 against 2024."},
]

# Each chart: what it shows, where its numbers come from and how they were made.
CHARTS = [
    {"id": "sales_monthly", "tab": "market", "type": "bar", "title": "Sales per month",
     "query": "queries/market_monthly.sql", "data": "data/market_monthly.parquet",
     "metrics": ["sales_count"], "dimensions": ["sale_month", "region", "property_type"],
     "filters": ["region", "property_type"],
     "description": "Market sales by completion month. Months from January 2026 are provisional (registration lag)."},
    {"id": "median_price_monthly", "tab": "market", "type": "line", "title": "Median price paid",
     "query": "queries/market_monthly.sql", "data": "data/market_monthly.parquet",
     "metrics": ["median_price"], "dimensions": ["sale_month", "region", "property_type"],
     "filters": ["region", "property_type"],
     "description": "Monthly median price. Moves with the mix of homes sold, as well as with values."},
    {"id": "region_price_change", "tab": "market", "type": "dot", "title": "Median price change by region, 2025 vs 2024",
     "query": "queries/region_yoy.sql", "methodology": "analysis/regional_price_change.py",
     "data": "data/region_price_change.parquet",
     "metrics": ["median_price"], "dimensions": ["region"], "filters": [],
     "description": "Headline change with a 95% bootstrap interval, and the mix-adjusted change (property-type weighted)."},
    {"id": "band_vs_expected", "tab": "stamp_duty", "type": "heatmap", "title": "Sales against expected, by price band (England)",
     "query": "queries/price_band_monthly.sql", "methodology": "analysis/stamp_duty_pullforward.py",
     "data": "data/pullforward_monthly.parquet",
     "metrics": ["sales_count"], "dimensions": ["sale_month", "price_band"], "filters": [],
     "description": "Each cell is actual sales relative to a seasonal baseline from 2023–24. Red is above expected, blue below."},
    {"id": "pullforward_by_band", "tab": "stamp_duty", "type": "bar", "title": "Extra sales before the deadline, and the dip after",
     "query": "queries/price_band_monthly.sql", "methodology": "analysis/stamp_duty_pullforward.py",
     "data": "data/pullforward_summary.parquet",
     "metrics": ["sales_count"], "dimensions": ["price_band"], "filters": [],
     "description": "Excess sales Jan–Mar 2025 compared with the shortfall Apr–Jun 2025, by price band (England)."},
    {"id": "sdlt_increase", "tab": "stamp_duty", "type": "bar", "title": "Extra stamp duty from 1 April 2025",
     "methodology": "analysis/stamp_duty_pullforward.py", "data": "data/sdlt_increase.parquet",
     "metrics": [], "dimensions": [], "filters": [],
     "description": "Increase in Stamp Duty at example prices, standard buyer vs first-time buyer, from ref.sdlt_bands."},
    {"id": "band_monthly", "tab": "stamp_duty", "type": "line", "title": "Monthly sales by price band",
     "query": "queries/price_band_monthly.sql", "data": "data/price_band_monthly.parquet",
     "metrics": ["sales_count"], "dimensions": ["sale_month", "price_band", "region"], "filters": ["region"],
     "description": "Three bands that tell the story: untouched by the change (under £125k), new 2% charge (£125k–250k) and lost first-time buyer relief (£300k–425k)."},
    {"id": "district_movers", "tab": "places", "type": "table", "title": "Local authorities: biggest price movers",
     "query": "queries/district_movers.sql", "data": "data/district_movers.parquet",
     "metrics": ["median_price", "sales_count"], "dimensions": ["district", "region"], "filters": ["region"],
     "description": "Authorities with at least 500 sales in both years, ranked by change in median price."},
    {"id": "new_build_premium", "tab": "places", "type": "bar", "title": "New-build premium by property type, 2025",
     "query": "queries/new_build_premium.sql", "data": "data/new_build_premium.parquet",
     "metrics": ["median_price", "sales_count"], "dimensions": ["property_type", "is_new_build", "region"],
     "filters": ["region"],
     "description": "Median price of new builds against existing homes of the same type."},
]

ANALYST_NOTES = {
    "hypotheses_tested": [
        {"hypothesis": "The March 2025 spike was caused by the Stamp Duty change on 1 April 2025.",
         "status": "supported",
         "evidence": "Spike concentrated in bands where tax rose; under-£125k band (no change) stayed at its baseline."},
        {"hypothesis": "The spike was entirely sales moved forward in time.",
         "status": "partly supported",
         "evidence": "Shortfall in Apr–Jun 2025 recovers about half the Jan–Mar excess. The rest may have been paid back later or reflects extra demand."},
        {"hypothesis": "Prices fell after the change.",
         "status": "not supported",
         "evidence": "The April 2025 median dropped because cheaper homes made up more of the sales. By mid-2025 the median was back to its 2024 level."},
    ],
    "limitations": [
        "Buyer type is not recorded: first-time buyers are inferred from price bands.",
        "Months from January 2026 are provisional because of registration lag.",
        "Median price is not a house price index; mix of homes sold moves it.",
        "Wales has Land Transaction Tax, so Stamp Duty analysis uses England only.",
    ],
    "next_questions": [
        "Did payback continue after June 2025?",
        "Which local authorities had the largest spike relative to normal?",
        "Has the new-build share changed since the tax change?",
    ],
}


def _round(df: pd.DataFrame) -> list:
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]) or df[c].dtype == object and len(df) and hasattr(df[c].iloc[0], "isoformat"):
            df[c] = df[c].astype(str).str[:10]
        elif pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(4)
    return json.loads(df.to_json(orient="split", index=False))


def kpis(frames: dict) -> dict:
    m = frames["market_monthly"]
    allm = m[(m.region == "All") & (m.property_type == "All")].copy()
    allm["year"] = pd.to_datetime(allm.sale_month).dt.year
    s24, s25 = allm[allm.year == 2024].sales_count.sum(), allm[allm.year == 2025].sales_count.sum()
    mar = allm.set_index(pd.to_datetime(allm.sale_month).dt.strftime("%Y-%m")).sales_count
    r = frames["region_price_change"].set_index("region").loc["All"]
    nb = frames["region_yoy"]
    return {
        "sales_2025": int(s25), "sales_change": float(s25 / s24 - 1),
        "median_2025": float(r.median_2025), "median_change": float(r.median_change),
        "mix_adjusted_change": float(r.mix_adjusted_change),
        "march_2025": int(mar["2025-03"]), "march_change": float(mar["2025-03"] / mar["2024-03"] - 1),
        "april_2025": int(mar["2025-04"]),
    }


def build(out: pathlib.Path, frames: dict, findings: dict, manifest: dict, sdk_dir: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    assets = out / "assets"
    if assets.exists():
        shutil.rmtree(assets)
    shutil.copytree(APP / "static", assets)
    shutil.copytree(sdk_dir, out / "sdk", dirs_exist_ok=True)

    k = kpis(frames)
    payload = {
        "manifest": manifest,
        "kpis": k,
        "findings": findings,
        "data": {name: _round(df) for name, df in frames.items()},
    }
    pf = findings["stamp_duty_pullforward"]
    rp = findings["regional_price_change"]
    takeaways = {
        "market": (f"Sales rose {k['sales_change']:+.1%} in 2025, led by a March spike of {k['march_change']:+.0%} "
                   f"ahead of the stamp duty change."),
        "stamp_duty": (f"About {pf['excess_jan_mar']:,} extra completions in January–March 2025; "
                       f"{pf['payback']:.0%} were paid back by June."),
        "places": f"{rp['fastest_region']} rose most in 2025, {rp['slowest_region']} least.",
    }

    nav = "\n".join(
        f'<button class="nav-item{" active" if i == 0 else ""}" data-tab="{t["id"]}">'
        f'<span class="nav-ico ico-{t["icon"]}"></span>{html.escape(t["title"])}</button>'
        for i, t in enumerate(TABS))
    sections = "\n".join(_tab_section(t, takeaways[t["id"]]) for t in TABS)

    page = (APP / "template.html").read_text()
    page = (page.replace("{{NAV}}", nav)
                .replace("{{SECTIONS}}", sections)
                .replace("{{TITLE}}", html.escape(manifest["title"]))
                .replace("{{VERSION}}", str(manifest["version"]))
                .replace("{{PUBLISHED}}", manifest["published_at"][:10])
                .replace("{{EXTRACT}}", manifest["freshness"]["extract_date"])
                .replace("{{LATEST_SALE}}", pd.Timestamp(manifest["freshness"]["latest_sale"]).strftime("%-d %b %Y"))
                .replace("{{PAYLOAD}}", json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")))
    (out / "index.html").write_text(page)


def _tab_section(tab: dict, takeaway: str) -> str:
    charts = [c for c in CHARTS if c["tab"] == tab["id"]]
    cards = []
    for c in charts:
        method = (f'<button class="chip chip-link" data-open-source="{c["methodology"]}">Method</button>'
                  if c.get("methodology") else "")
        sql = (f'<button class="chip chip-link" data-open-source="{c["query"]}">SQL</button>'
               if c.get("query") else "")
        cards.append(f"""
      <article class="card card-{c['type']}" id="card-{c['id']}" data-chart="{c['id']}">
        <header class="card-head">
          <h3>{html.escape(c['title'])}</h3>
          <div class="card-tools">{sql}{method}
            <button class="chip chip-ask" data-ask-chart="{c['id']}" title="Ask about this chart">Ask</button></div>
        </header>
        <div class="plot" id="plot-{c['id']}"></div>
      </article>""")
    kpi = '<div class="kpis" id="kpis"></div>' if tab["id"] == "market" else ""
    return f"""
    <section class="tab" id="tab-{tab['id']}" data-tab-panel="{tab['id']}"{' hidden' if tab['id'] != 'market' else ''}>
      <div class="page-head"><h1>{html.escape(tab['heading'])}</h1></div>
      {kpi}
      <div class="takeaway" data-takeaway="{tab['id']}"><span class="takeaway-label">Takeaway</span><p>{html.escape(takeaway)}</p></div>
      <div class="grid grid-{tab['id']}">{''.join(cards)}</div>
    </section>"""
