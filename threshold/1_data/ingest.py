"""Step 1 — Ingest HM Land Registry Price Paid Data into a local DuckDB warehouse.

This stands in for the client's warehouse. In a real Plotline engagement this
data already lives in Snowflake / BigQuery / Postgres and nothing is copied;
Scout and the query engine connect to it read-only.

Source: HM Land Registry Price Paid Data (Open Government Licence v3.0)
        https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads
Region lookup: ONS Local Authority District to Region (December 2024) Lookup in England

Run:  .venv/bin/python 1_data/ingest.py
"""
from __future__ import annotations

import json
import pathlib
import urllib.request

import duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "1_data" / "raw"
DB = ROOT / "1_data" / "warehouse.duckdb"
SAMPLES = ROOT / "1_data" / "samples"
MODELS = ROOT / "2_models"
YEARS = [2023, 2024, 2025, 2026]
PPD_URL = "https://price-paid-data.publicdata.landregistry.gov.uk/pp-{year}.csv"
ONS_URL = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
           "LAD24_RGN24_EN_LU/FeatureServer/0/query?where=1%3D1&outFields=*&f=json&resultRecordCount=1000")

# The published CSVs have no header row. Column names come from Land Registry's
# documentation, which is exactly the kind of context Scout keeps next to the table.
PPD_COLUMNS = {
    "transaction_id": "VARCHAR", "price": "BIGINT", "transfer_date": "TIMESTAMP",
    "postcode": "VARCHAR", "property_type": "VARCHAR", "old_new": "VARCHAR",
    "duration": "VARCHAR", "paon": "VARCHAR", "saon": "VARCHAR", "street": "VARCHAR",
    "locality": "VARCHAR", "town_city": "VARCHAR", "district": "VARCHAR",
    "county": "VARCHAR", "ppd_category": "VARCHAR", "record_status": "VARCHAR",
}

# Price Paid district names that differ from ONS names, plus all of Wales
# (the ONS lookup only covers England).
DISTRICT_FIXES = {
    "CITY OF BRISTOL": "South West", "CITY OF PLYMOUTH": "South West",
    "CITY OF KINGSTON UPON HULL": "Yorkshire and The Humber",
    "CITY OF NOTTINGHAM": "East Midlands", "CITY OF DERBY": "East Midlands",
    "HEREFORDSHIRE": "West Midlands", "WREKIN": "West Midlands",
    "CITY OF PETERBOROUGH": "East of England", "CITY OF WESTMINSTER": "London",
    "ST HELENS": "North West",
}
WALES = {
    "CARDIFF", "RHONDDA CYNON TAFF", "SWANSEA", "CARMARTHENSHIRE", "NEWPORT", "CAERPHILLY",
    "FLINTSHIRE", "BRIDGEND", "THE VALE OF GLAMORGAN", "CONWY", "NEATH PORT TALBOT",
    "PEMBROKESHIRE", "WREXHAM", "GWYNEDD", "POWYS", "DENBIGHSHIRE", "MONMOUTHSHIRE",
    "TORFAEN", "CEREDIGION", "BLAENAU GWENT", "ISLE OF ANGLESEY", "MERTHYR TYDFIL",
}

# Councils abolished in the April 2023 reorganisations. Sales registered against the
# old names are mapped to the successor authority so district trends are continuous.
DISTRICT_SUCCESSORS = {
    **{d: "SOMERSET" for d in ["SOUTH SOMERSET", "SOMERSET WEST AND TAUNTON", "MENDIP", "SEDGEMOOR"]},
    **{d: "NORTH YORKSHIRE" for d in ["HARROGATE", "SCARBOROUGH", "HAMBLETON", "SELBY", "CRAVEN",
                                      "RYEDALE", "RICHMONDSHIRE"]},
    **{d: "CUMBERLAND" for d in ["CARLISLE", "ALLERDALE", "COPELAND"]},
    **{d: "WESTMORLAND AND FURNESS" for d in ["BARROW-IN-FURNESS", "SOUTH LAKELAND", "EDEN"]},
}

# Stamp Duty Land Tax bands for residential purchases in England (gov.uk).
# Wales uses Land Transaction Tax instead, which is why the analysis flags Wales separately.
SDLT_BANDS = [
    # regime, buyer, lower, upper, rate
    ("2022-09-23 to 2025-03-31", "standard", 0, 250000, 0.00),
    ("2022-09-23 to 2025-03-31", "standard", 250000, 925000, 0.05),
    ("2022-09-23 to 2025-03-31", "standard", 925000, 1500000, 0.10),
    ("2022-09-23 to 2025-03-31", "standard", 1500000, None, 0.12),
    ("2022-09-23 to 2025-03-31", "first_time_buyer", 0, 425000, 0.00),
    ("2022-09-23 to 2025-03-31", "first_time_buyer", 425000, 625000, 0.05),
    ("from 2025-04-01", "standard", 0, 125000, 0.00),
    ("from 2025-04-01", "standard", 125000, 250000, 0.02),
    ("from 2025-04-01", "standard", 250000, 925000, 0.05),
    ("from 2025-04-01", "standard", 925000, 1500000, 0.10),
    ("from 2025-04-01", "standard", 1500000, None, 0.12),
    ("from 2025-04-01", "first_time_buyer", 0, 300000, 0.00),
    ("from 2025-04-01", "first_time_buyer", 300000, 500000, 0.05),
]


def download() -> bool:
    """Fetch any yearly file that is missing or has changed on Land Registry's side. Returns True if anything changed."""
    RAW.mkdir(parents=True, exist_ok=True)
    release_file = RAW / "release.json"
    release = json.loads(release_file.read_text()) if release_file.exists() else {}
    changed = False
    for year in YEARS:
        url, target = PPD_URL.format(year=year), RAW / f"pp-{year}.csv"
        head = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30)
        remote_size, modified = int(head.headers["Content-Length"]), head.headers["Last-Modified"]
        if not target.exists() or target.stat().st_size != remote_size:
            print(f"downloading {target.name} ({remote_size / 1e6:,.0f} MB, released {modified})")
            urllib.request.urlretrieve(url, target)
            changed = True
        release[target.name] = modified
    release_file.write_text(json.dumps(release, indent=1))
    lookup = RAW / "lad_rgn.json"
    if not lookup.exists():
        urllib.request.urlretrieve(ONS_URL, lookup)
    return changed


def build() -> None:
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute("CREATE SCHEMA raw; CREATE SCHEMA ref; CREATE SCHEMA analytics;")

    files = [str(RAW / f"pp-{y}.csv") for y in YEARS]
    cols = ", ".join(f"'{k}': '{v}'" for k, v in PPD_COLUMNS.items())
    con.execute(f"""
        CREATE TABLE raw.price_paid AS
        SELECT * FROM read_csv({files}, header=false, columns={{{cols}}})
    """)

    feats = json.loads((RAW / "lad_rgn.json").read_text())["features"]
    rows = [(f["attributes"]["LAD24NM"].upper(), f["attributes"]["LAD24CD"],
             f["attributes"]["RGN24NM"], "England") for f in feats]
    rows += [(d, None, r, "England") for d, r in DISTRICT_FIXES.items()]
    rows += [(d, None, "Wales", "Wales") for d in sorted(WALES)]
    con.execute("CREATE TABLE ref.district_region (district VARCHAR, lad_code VARCHAR, region VARCHAR, country VARCHAR)")
    con.executemany("INSERT INTO ref.district_region VALUES (?, ?, ?, ?)", rows)

    con.execute("CREATE TABLE ref.district_successor (old_district VARCHAR, district VARCHAR)")
    con.executemany("INSERT INTO ref.district_successor VALUES (?, ?)", list(DISTRICT_SUCCESSORS.items()))

    con.execute("CREATE TABLE ref.sdlt_bands (regime VARCHAR, buyer_type VARCHAR, lower_gbp BIGINT, upper_gbp BIGINT, rate DOUBLE)")
    con.executemany("INSERT INTO ref.sdlt_bands VALUES (?, ?, ?, ?, ?)", SDLT_BANDS)

    # The modelled table analysts and the semantic layer use: see 2_models/.
    for model in sorted(MODELS.glob("*.sql")):
        con.execute(model.read_text())
    unmatched = con.execute("SELECT count(*) FROM analytics.sales WHERE region IS NULL").fetchone()[0]
    assert unmatched == 0, f"{unmatched} sales have no region"
    con.execute("CREATE INDEX idx_sales_month ON analytics.sales (sale_month)")

    for t in ["raw.price_paid", "ref.district_region", "ref.district_successor", "ref.sdlt_bands", "analytics.sales"]:
        print(f"{t:24s} {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:>10,} rows")
    con.close()


def write_samples() -> None:
    """Small files to open in the IDE. The real data is millions of rows."""
    SAMPLES.mkdir(exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    with open(RAW / "pp-2025.csv") as src, open(SAMPLES / "raw_as_published.csv", "w") as out:
        for _, line in zip(range(50), src):
            out.write(line)
    con.execute(f"""COPY (SELECT * FROM analytics.sales WHERE sale_month = DATE '2025-03-01'
                         ORDER BY transaction_id LIMIT 200) TO '{SAMPLES / "analytics_sales.csv"}' (HEADER)""")
    lines = ["# Warehouse tables", "", "| Table | Rows | Columns |", "|---|---:|---|"]
    for schema, table in con.execute("""SELECT table_schema, table_name FROM information_schema.tables
                                        ORDER BY table_schema DESC, table_name""").fetchall():
        n = con.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
        cols = [r[0] for r in con.execute(f"DESCRIBE {schema}.{table}").fetchall()]
        lines.append(f"| {schema}.{table} | {n:,} | {', '.join(cols)} |")
    files = sorted(RAW.glob("pp-*.csv"))
    lines += ["", f"Raw files: {', '.join(f.name for f in files)} "
                  f"({sum(f.stat().st_size for f in files) / 1e6:,.0f} MB)."]
    (SAMPLES / "warehouse_tables.md").write_text("\n".join(lines) + "\n")
    con.close()


if __name__ == "__main__":
    download()
    build()
    write_samples()
