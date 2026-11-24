"""Weekly market-intelligence features from SEC filings, point-in-time.

A filing counts only from the day after its filing date, so a Friday's features
never use anything filed that Friday.
"""
import numpy as np, pandas as pd

GROUPS = {
    "Insider buying": ["ins_buy_val_90d", "ins_buyers_90d"],
    "Insider selling": ["ins_sell_val_90d", "ins_sellers_90d", "ins_sell_surge"],
    "Insider net": ["ins_net_90d"],
    "Earnings timing": ["k8_earn_days"],
    "Executive changes": ["k8_exec_90d"],
    "Deals": ["k8_deal_90d"],
    "Filing activity": ["k8_n_30d", "k8_fresh_7d"],
}
COLS = [c for g in GROUPS.values() for c in g]


def build(con, fridays, tickers):
    ins = con.execute("select ticker, filing_date, code, value, owner from insider_tx").df()
    fil = con.execute("select ticker, filing_date, form, items from filings where form in ('8-K','8-K/A')").df()
    ins["filing_date"] = pd.to_datetime(ins.filing_date); fil["filing_date"] = pd.to_datetime(fil.filing_date)
    days = pd.date_range("2014-01-01", fridays.max(), freq="D")
    out = []
    for t in tickers:
        it, ft = ins[ins.ticker == t], fil[fil.ticker == t]
        def daily(mask_df, col=None):
            s = (mask_df.groupby("filing_date")[col].sum() if col else mask_df.groupby("filing_date").size())
            return s.reindex(days, fill_value=0).astype(float).shift(1, fill_value=0)   # known next day
        b, s_ = it[it.code == "P"], it[it.code == "S"]
        buy_v, sell_v = daily(b, "value"), daily(s_, "value")
        roll = lambda x, n: x.rolling(f"{n}D").sum()
        # distinct insiders in 90 days, sampled at each Friday
        def distinct(df):
            vals = []
            for f in fridays:
                w = df[(df.filing_date < f) & (df.filing_date >= f - pd.Timedelta(days=90))]
                vals.append(w.owner.nunique())
            return pd.Series(vals, index=fridays, dtype=float)
        has = lambda code: ft["items"].fillna("").str.contains(code, regex=False)
        earn = daily(ft[has("2.02")]); execs = daily(ft[has("5.02")])
        deals = daily(ft[has("1.01") | has("2.01") | has("1.02")]); any8k = daily(ft)
        last_earn = pd.Series(np.where(earn > 0, days, pd.NaT), index=days).ffill()
        f = pd.DataFrame(index=fridays)
        bv90, sv90 = roll(buy_v, 90).reindex(fridays), roll(sell_v, 90).reindex(fridays)
        f["ins_buy_val_90d"] = np.log1p(bv90)
        f["ins_sell_val_90d"] = np.log1p(sv90)
        f["ins_buyers_90d"] = distinct(b)
        f["ins_sellers_90d"] = distinct(s_)
        f["ins_sell_surge"] = np.log1p(roll(sell_v, 30).reindex(fridays)) - np.log1p(roll(sell_v, 365).reindex(fridays) / 12)
        f["ins_net_90d"] = (bv90 - sv90) / (bv90 + sv90 + 1e5)
        f["k8_earn_days"] = pd.Series((fridays - pd.to_datetime(last_earn.reindex(fridays).values)).days, index=fridays).fillna(200).clip(upper=200)
        f["k8_exec_90d"] = roll(execs, 90).reindex(fridays)
        f["k8_deal_90d"] = roll(deals, 90).reindex(fridays)
        f["k8_n_30d"] = roll(any8k, 30).reindex(fridays)
        f["k8_fresh_7d"] = (roll(any8k, 7).reindex(fridays) > 0).astype(float)
        f["ticker"] = t
        out.append(f)
    F = pd.concat(out).rename_axis("date").reset_index().set_index(["date", "ticker"])
    return F[COLS]
