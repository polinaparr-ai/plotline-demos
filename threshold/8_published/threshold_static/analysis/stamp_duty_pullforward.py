"""Methodology: how many sales did the April 2025 Stamp Duty change pull forward?

Question
    Completions in England jumped in March 2025 and collapsed in April. Was that extra
    demand, or sales that would have happened anyway, moved earlier to beat the tax change?

Method
    1. England only (Wales has Land Transaction Tax), market sales (ppd_category = 'A').
    2. Expected sales for each price band and month of 2025 = the average of the same
       month in 2023 and 2024 (captures seasonality), scaled by the band's growth between
       Jul–Sep 2023 and Jul–Sep 2024 (captures trend before anyone was reacting to the change).
    3. Excess = actual − expected in Jan–Mar 2025. Shortfall = expected − actual in Apr–Jun 2025.
       Payback = shortfall / excess. Near 100% means the spike was almost entirely timing.
    4. How unusual was March? We compare log(actual / expected) for March 2025 with the same
       residual for every 2023–2024 month (leave-one-year-out baseline), and report a z-score.

Limitations
    - Buyer type is not recorded, so first-time buyers are inferred from price bands.
    - The baseline assumes 2025 would have looked like 2023–24 without the change.
    - Late registrations could still add a few March 2025 sales; numbers are as of the extract date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW_EXCESS = ["2025-01-01", "2025-02-01", "2025-03-01"]
WINDOW_SHORTFALL = ["2025-04-01", "2025-05-01", "2025-06-01"]


def monthly_by_band(con) -> pd.DataFrame:
    return con.execute("""
        SELECT sale_month, price_band, COUNT(*) AS sales
        FROM analytics.sales
        WHERE ppd_category = 'A' AND country = 'England'
          AND sale_month BETWEEN DATE '2023-01-01' AND DATE '2025-12-01'
        GROUP BY ALL
    """).df()


def expected_sales(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sale_month"] = pd.to_datetime(df["sale_month"])
    df["year"], df["month"] = df.sale_month.dt.year, df.sale_month.dt.month
    wide = df.pivot_table(index=["price_band", "month"], columns="year", values="sales").reset_index()

    q3 = df[df.month.isin([7, 8, 9])].groupby(["price_band", "year"]).sales.sum().unstack()
    growth = (q3[2024] / q3[2023]).rename("growth")
    wide = wide.merge(growth, left_on="price_band", right_index=True)
    wide["expected_2025"] = (wide[2023] + wide[2024]) / 2 * wide["growth"]
    # Leave-one-year-out baselines for 2023 and 2024, to measure normal noise.
    wide["expected_2024"] = wide[2023] * wide["growth"]
    wide["expected_2023"] = wide[2024] / wide["growth"]

    rows = []
    for _, r in wide.iterrows():
        for y in (2023, 2024, 2025):
            rows.append({
                "sale_month": pd.Timestamp(year=y, month=int(r.month), day=1),
                "price_band": r.price_band, "actual": r[y], "expected": r[f"expected_{y}"],
            })
    out = pd.DataFrame(rows).sort_values(["price_band", "sale_month"]).reset_index(drop=True)
    out["log_ratio"] = np.log(out.actual / out.expected)
    return out


def summarise(monthly: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    m = monthly.copy()
    m["key"] = m.sale_month.dt.strftime("%Y-%m-01")
    calib = m[m.sale_month.dt.year < 2025]
    noise_sd = calib.groupby("price_band").log_ratio.std().rename("noise_sd")

    ex = m[m.key.isin(WINDOW_EXCESS)].assign(d=lambda x: x.actual - x.expected).groupby("price_band").d.sum()
    sh = m[m.key.isin(WINDOW_SHORTFALL)].assign(d=lambda x: x.expected - x.actual).groupby("price_band").d.sum()
    mar = m[m.key == "2025-03-01"].set_index("price_band")

    s = pd.DataFrame({"excess_jan_mar": ex, "shortfall_apr_jun": sh}).join(noise_sd)
    s["net"] = s.excess_jan_mar - s.shortfall_apr_jun
    s["payback"] = s.shortfall_apr_jun / s.excess_jan_mar
    s["march_actual"] = mar.actual
    s["march_expected"] = mar.expected
    s["march_vs_expected"] = mar.actual / mar.expected - 1
    s["march_z"] = mar.log_ratio / s.noise_sd
    s = s.reset_index()

    tot = s[["excess_jan_mar", "shortfall_apr_jun", "march_actual", "march_expected"]].sum()
    findings = {
        "excess_jan_mar": int(round(tot.excess_jan_mar)),
        "shortfall_apr_jun": int(round(tot.shortfall_apr_jun)),
        "payback": float(tot.shortfall_apr_jun / tot.excess_jan_mar),
        "march_vs_expected": float(tot.march_actual / tot.march_expected - 1),
        "min_march_z": float(s.march_z.min()),
        "band_most_affected": s.sort_values("march_vs_expected").iloc[-1].price_band,
    }
    return s, findings


def sdlt(price: float, bands: pd.DataFrame, regime: str, buyer: str) -> float:
    """Stamp duty for one purchase. First-time buyer relief only applies at or below the cap."""
    b = bands[(bands.regime == regime) & (bands.buyer_type == buyer)]
    cap = b.upper_gbp.max()
    if buyer == "first_time_buyer" and price > cap:
        return sdlt(price, bands, regime, "standard")
    tax = 0.0
    for _, r in b.iterrows():
        upper = r.upper_gbp if pd.notna(r.upper_gbp) else np.inf
        if price > r.lower_gbp:
            tax += (min(price, upper) - r.lower_gbp) * r.rate
    return tax


def tax_change_by_price(con) -> pd.DataFrame:
    bands = con.execute("SELECT * FROM ref.sdlt_bands").df()
    rows = []
    for price in [100_000, 200_000, 275_000, 350_000, 450_000, 550_000, 750_000, 1_200_000]:
        row = {"price": price}
        for buyer in ("standard", "first_time_buyer"):
            before = sdlt(price, bands, "2022-09-23 to 2025-03-31", buyer)
            after = sdlt(price, bands, "from 2025-04-01", buyer)
            row[f"{buyer}_before"], row[f"{buyer}_after"] = before, after
            row[f"{buyer}_increase"] = after - before
        rows.append(row)
    return pd.DataFrame(rows)


def run(con) -> dict:
    monthly = expected_sales(monthly_by_band(con))
    summary, findings = summarise(monthly)
    return {
        "frames": {
            "pullforward_monthly": monthly.drop(columns="log_ratio"),
            "pullforward_summary": summary,
            "sdlt_increase": tax_change_by_price(con),
        },
        "findings": findings,
    }


if __name__ == "__main__":
    import duckdb, pathlib, json
    db = pathlib.Path(__file__).resolve().parents[1] / "1_data" / "warehouse.duckdb"
    res = run(duckdb.connect(str(db), read_only=True))
    print(res["frames"]["pullforward_summary"].round(2).to_string())
    print(json.dumps(res["findings"], indent=2, default=str))
