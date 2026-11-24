"""Weekly walk-forward backtest. Usage: backtest.py [price|intel]

price: price and volume features only. intel: adds SEC filing features (model/intel_features.py).

At each Friday close t, for every stock, predict next week's return using only
prices known at t. Retrain once a year on all earlier weeks (1-week embargo),
predict the following year out-of-sample. Writes site/data.json.
"""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, duckdb
from sklearn.ensemble import HistGradientBoostingRegressor as HGB

ROOT = Path(__file__).resolve().parents[1]
COST_BPS = 10          # per side, on turnover
TOP_N = 10
FIRST_TEST_YEAR = 2019
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "price"
assert VARIANT in ("price", "intel")

con = duckdb.connect(str(ROOT / "data" / "signals.duckdb"), read_only=True)
px = con.execute("SELECT date, ticker, adj_close, volume FROM prices").df()
px["date"] = pd.to_datetime(px["date"])

# ---- weekly panel (Friday closes) -------------------------------------------
close = px.pivot(index="date", columns="ticker", values="adj_close").sort_index()
vol = px.pivot(index="date", columns="ticker", values="volume").sort_index()
wk_close = close.resample("W-FRI").last()
wk_vol = vol.resample("W-FRI").sum()
last_day = close.index.max()
if wk_close.index[-1] > last_day:                 # current week incomplete -> drop
    wk_close, wk_vol = wk_close.iloc[:-1], wk_vol.iloc[:-1]

spy = wk_close.pop("SPY"); wk_vol = wk_vol.drop(columns="SPY")
r = wk_close.pct_change()
spy_r = spy.pct_change()

# ---- features (all known at Friday close t) ----------------------------------
def lagret(n): return wk_close / wk_close.shift(n) - 1
feat = {
    "ret_1w": r,
    "ret_4w": lagret(4),
    "ret_12w": lagret(12),
    "ret_26w": lagret(26),
    "mom_12_1": wk_close.shift(4) / wk_close.shift(52) - 1,
    "vol_12w": r.rolling(12).std(),
    "vol_52w": r.rolling(52).std(),
    "off_52w_high": wk_close / wk_close.rolling(52).max() - 1,
    "volume_surge": np.log(wk_vol.rolling(4).mean() / wk_vol.rolling(52).mean()),
    "beta_52w": r.rolling(52).cov(spy_r) .div(spy_r.rolling(52).var(), axis=0),
}
long = pd.concat({k: v.stack() for k, v in feat.items()}, axis=1)
long.index.names = ["date", "ticker"]
# cross-sectional ranks (0..1) are robust to regime level shifts
ranked = long.groupby(level="date").rank(pct=True).add_suffix("_rk")
X = long.join(ranked)
mkt = pd.DataFrame({"spy_1w": spy_r, "spy_4w": spy / spy.shift(4) - 1,
                    "spy_vol_12w": spy_r.rolling(12).std()})
X = X.join(mkt, on="date")
if VARIANT == "intel":
    sys.path.insert(0, str(ROOT / "model"))
    import intel_features
    F = intel_features.build(con, wk_close.index, list(wk_close.columns))
    F = F.join(F.groupby(level="date").rank(pct=True).add_suffix("_rk"))
    X = X.join(F, how="left").fillna({c: 0 for c in F.columns})
con.close()

fwd = r.shift(-1)                                   # next week's return
fwd_ex = fwd.sub(fwd.mean(axis=1), axis=0)          # vs equal-weight universe
X["y"] = fwd.stack()
X["y_ex"] = fwd_ex.stack()
X = X.dropna(subset=[c for c in X.columns if c not in ("y", "y_ex")])
FEATS = [c for c in X.columns if c not in ("y", "y_ex")]

# ---- walk-forward -------------------------------------------------------------
dates = X.index.get_level_values("date")
preds = []
last_year = dates.max().year
for year in range(FIRST_TEST_YEAR, last_year + 1):
    start = pd.Timestamp(f"{year}-01-01")
    train = X[(dates < start - pd.Timedelta(weeks=1))].dropna(subset=["y"])
    test = X[(dates >= start) & (dates < pd.Timestamp(f"{year + 1}-01-01"))]
    if test.empty: continue
    common = dict(max_iter=300, learning_rate=0.04, max_leaf_nodes=15,
                  min_samples_leaf=300, l2_regularization=1.0, random_state=7)
    out = pd.DataFrame(index=test.index)
    out["pred_ex"] = HGB(**common).fit(train[FEATS], train["y_ex"]).predict(test[FEATS])
    # quantile band, then split-conformal widening: fit on train minus its last
    # 52 weeks, find the stretch factor k that gives 80% coverage on those weeks.
    tdates = train.index.get_level_values("date")
    cut = tdates.max() - pd.Timedelta(weeks=52)
    fit_part, cal = train[tdates <= cut], train[tdates > cut]
    qs = {}
    for q in (0.1, 0.5, 0.9):
        cal_m = HGB(loss="quantile", quantile=q, **common).fit(fit_part[FEATS], fit_part["y"])
        qs[q] = cal_m.predict(cal[FEATS])
    lo_w, hi_w = qs[0.5] - qs[0.1], qs[0.9] - qs[0.5]
    ks = np.linspace(0.5, 3, 101)
    cov = [((cal["y"] >= qs[0.5] - k * lo_w) & (cal["y"] <= qs[0.5] + k * hi_w)).mean() for k in ks]
    k = float(ks[np.argmax(np.array(cov) >= 0.8)])
    for q in (0.1, 0.5, 0.9):
        m = HGB(loss="quantile", quantile=q, **common).fit(train[FEATS], train["y"])
        out[f"q{int(q*100)}"] = m.predict(test[FEATS])
    out["q10"] = out["q50"] - k * (out["q50"] - out["q10"])
    out["q90"] = out["q50"] + k * (out["q90"] - out["q50"])
    print(year, "band stretch k =", round(k, 2))
    out[["y", "y_ex"]] = test[["y", "y_ex"]]
    preds.append(out)
    print(year, "train rows", len(train), "test rows", len(test))
P = pd.concat(preds)
P[["q10", "q50", "q90"]] = np.sort(P[["q10", "q50", "q90"]].values, axis=1)  # no crossing

# ---- strategies ---------------------------------------------------------------
test_dates = sorted(P.index.get_level_values("date").unique())

def run(selector):
    """selector(date) -> list of tickers to hold over the following week."""
    w_prev, rets = pd.Series(dtype=float), []
    for d in test_dates:
        names = selector(d)
        w = pd.Series(1 / len(names), index=names)
        turnover = w.sub(w_prev, fill_value=0).abs().sum()
        nxt = fwd.loc[d, names]
        if nxt.isna().all():                       # live week: not yet scored
            break
        gross = (w * nxt.fillna(0)).sum()
        rets.append((d, gross - turnover * COST_BPS / 1e4))
        drift = w * (1 + nxt.fillna(0)); w_prev = drift / drift.sum()
    return pd.Series(dict(rets))

model_sel = lambda d: P.loc[d]["pred_ex"].nlargest(TOP_N).index.tolist()
mom_sel = lambda d: long.loc[d]["mom_12_1"].dropna().nlargest(TOP_N).index.tolist()
ew_sel = lambda d: long.loc[d].index.tolist()

strat = pd.DataFrame({
    "model": run(model_sel),
    "momentum": run(mom_sel),
    "equal_weight": run(ew_sel),
})
strat["spy"] = spy_r.shift(-1).reindex(strat.index)
cum = (1 + strat).cumprod()

def stats(s):
    yrs = len(s) / 52
    cagr = (1 + s).prod() ** (1 / yrs) - 1
    sharpe = s.mean() / s.std() * np.sqrt(52)
    eq = (1 + s).cumprod(); mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=round(cagr * 100, 1), sharpe=round(sharpe, 2), max_dd=round(mdd * 100, 1),
                total=round((eq.iloc[-1] - 1) * 100, 0))

summary = {k: stats(strat[k]) for k in strat}
scored = P.dropna(subset=["y"])
ic = scored.groupby(level="date").apply(lambda g: g["pred_ex"].corr(g["y_ex"], method="spearman"))
ic_year = ic.groupby(ic.index.year).mean().round(3)
hit = float(((np.sign(scored["q50"]) == np.sign(scored["y"]))).mean())
cover = float(((scored["y"] >= scored["q10"]) & (scored["y"] <= scored["q90"])).mean())
print(pd.DataFrame(summary).T)
print("IC by year:", ic_year.to_dict(), "mean", round(ic.mean(), 3))
print(f"direction hit rate {hit:.3f}, 80% band coverage {cover:.3f}")

# ---- results per variant ------------------------------------------------------------
spread = scored.groupby(level="date").apply(lambda g: g.nlargest(TOP_N, "pred_ex")["y"].mean() - g.nsmallest(TOP_N, "pred_ex")["y"].mean())
res = {"variant": VARIANT, "summary": summary, "ic_mean": round(float(ic.mean()), 4),
       "ic_by_year": {int(k): float(v) for k, v in ic_year.items()},
       "ic_t": round(float(ic.mean() / ic.std() * np.sqrt(len(ic))), 2),
       "hit_rate": round(hit, 4), "band_coverage": round(cover, 4),
       "spread_weekly": round(float(spread.mean()) * 100, 3), "spread_win": round(float((spread > 0).mean()), 3),
       "cum": [{"d": d.strftime("%Y-%m-%d"), **{k: round(float(v), 4) for k, v in row.items()}} for d, row in cum.iterrows()]}
(ROOT / "model" / f"results_{VARIANT}.json").write_text(json.dumps(res))
print("IC t-stat", res["ic_t"], "spread/wk", res["spread_weekly"], "win", res["spread_win"])

# ---- persist predictions for downstream story building ---------------------------
wcon = duckdb.connect(str(ROOT / "data" / "signals.duckdb"))
Pdf = P.reset_index()
wcon.execute(f"CREATE OR REPLACE TABLE predictions_{VARIANT} AS SELECT * FROM Pdf")
Wdf = wk_close.stack().rename("close").reset_index()
wcon.execute("CREATE OR REPLACE TABLE weekly_close AS SELECT * FROM Wdf")
wcon.close()
