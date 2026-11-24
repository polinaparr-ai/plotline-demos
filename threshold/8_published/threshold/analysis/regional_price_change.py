"""Methodology: how much did prices change by region, 2025 vs 2024, and how sure are we?

Method
    1. Market sales only (ppd_category = 'A'), calendar 2024 vs calendar 2025
       (the last two complete years; 2026 is provisional).
    2. Headline: change in median price.
    3. Uncertainty: 95% bootstrap interval for the change in median (400 resamples per region).
       If the interval spans zero, we say the change is not distinguishable from noise.
    4. Mix adjustment: the median moves when the mix of homes sold changes. We also compute a
       mix-adjusted change: the change in median within each property type, weighted by that
       type's share of 2024 sales. A big gap between headline and mix-adjusted means the
       headline is mostly about what sold, not what homes are worth.

Limitations
    - Not a repeat-sales house price index; the ONS/Land Registry UK HPI is the official measure.
    - The March 2025 stamp duty spike skews the 2025 mix towards the bands it affected most.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

N_BOOT = 400
RNG = np.random.default_rng(20251)


def load(con) -> pd.DataFrame:
    return con.execute("""
        SELECT region, property_type, year(sale_month) AS yr, price_gbp
        FROM analytics.sales
        WHERE ppd_category = 'A' AND year(sale_month) IN (2024, 2025) AND property_type <> 'Other'
        ORDER BY region, property_type, yr, price_gbp   -- fixed order so the seeded bootstrap is reproducible
    """).df()


def boot_median_change(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """95% bootstrap interval for median(b) / median(a) - 1."""
    na, nb = len(a), len(b)
    ma = np.median(a[RNG.integers(0, na, size=(N_BOOT, min(na, 60_000)))], axis=1)
    mb = np.median(b[RNG.integers(0, nb, size=(N_BOOT, min(nb, 60_000)))], axis=1)
    lo, hi = np.percentile(mb / ma - 1, [2.5, 97.5])
    return float(lo), float(hi)


def region_change(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = [("All", df)] + list(df.groupby("region"))
    for region, g in groups:
        a = g[g.yr == 2024].price_gbp.to_numpy()
        b = g[g.yr == 2025].price_gbp.to_numpy()
        lo, hi = boot_median_change(a, b)
        by_type = g.groupby(["property_type", "yr"]).price_gbp.median().unstack()
        weights = g[g.yr == 2024].property_type.value_counts(normalize=True)
        mix_adj = float(((by_type[2025] / by_type[2024] - 1) * weights).sum())
        rows.append({
            "region": region,
            "sales_2024": len(a), "sales_2025": len(b),
            "median_2024": float(np.median(a)), "median_2025": float(np.median(b)),
            "median_change": float(np.median(b) / np.median(a) - 1),
            "ci_low": lo, "ci_high": hi,
            "mix_adjusted_change": mix_adj,
            "significant": not (lo <= 0 <= hi),
        })
    return pd.DataFrame(rows)


def run(con) -> dict:
    out = region_change(load(con))
    eng = out[out.region != "All"]
    findings = {
        "england_wales_median_change": float(out.loc[out.region == "All", "median_change"].iloc[0]),
        "england_wales_mix_adjusted": float(out.loc[out.region == "All", "mix_adjusted_change"].iloc[0]),
        "fastest_region": eng.sort_values("median_change").iloc[-1].region,
        "slowest_region": eng.sort_values("median_change").iloc[0].region,
        "not_significant": sorted(eng.loc[~eng.significant, "region"].tolist()),
    }
    return {"frames": {"region_price_change": out}, "findings": findings}


if __name__ == "__main__":
    import duckdb, pathlib, json
    db = pathlib.Path(__file__).resolve().parents[1] / "1_data" / "warehouse.duckdb"
    res = run(duckdb.connect(str(db), read_only=True))
    print(res["frames"]["region_price_change"].round(4).to_string())
    print(json.dumps(res["findings"], indent=2))
