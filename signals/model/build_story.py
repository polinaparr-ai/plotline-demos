"""Turn predictions + prices into site/story.json for the story page."""
import json
from pathlib import Path
import sys
import numpy as np, pandas as pd, duckdb
sys.path.insert(0, str(Path(__file__).resolve().parent))
import intel_features

ROOT = Path(__file__).resolve().parents[1]
SECTOR = {
 "Chips": "NVDA AVGO AMD QCOM TXN AMAT INTC",
 "Software & web": "MSFT ORCL CRM ADBE INTU NOW GOOGL META NFLX AAPL IBM CSCO ACN",
 "Retail & consumer": "AMZN TSLA HD COST WMT MCD LOW SBUX NKE TGT BKNG F GM DIS",
 "Staples": "PG KO PEP PM MO MDLZ CL KHC",
 "Health": "LLY UNH JNJ ABBV MRK TMO ABT DHR AMGN PFE ISRG ELV MDT GILD CVS BMY CI",
 "Finance": "BRK-B JPM V MA BAC WFC SPGI GS MS BLK SCHW AXP C USB MET AIG COF",
 "Industrials": "CAT GE UNP HON RTX UPS LMT DE BA MMM EMR GD FDX ADP",
 "Energy, utilities & other": "XOM CVX COP NEE SO DUK LIN PLD VZ T CMCSA",
}
SECTOR = {t: s for s, ts in SECTOR.items() for t in ts.split()}

c = duckdb.connect(str(ROOT / "data" / "signals.duckdb"), read_only=True)
P = c.execute("select * from predictions_intel").df()
P0 = c.execute("select * from predictions_price").df()
W = c.execute("select * from weekly_close").df()
px = c.execute("select date, ticker, adj_close from prices").df()
px["date"] = pd.to_datetime(px["date"])
missing = sorted(set(P.ticker) - set(SECTOR)); assert not missing, missing

P["inside"] = (P.y >= P.q10) & (P.y <= P.q90)
s = P.dropna(subset=["y"]).copy()
dates = sorted(P.date.unique())
live_d, last_d = dates[-1], dates[-2]          # live week starts at live_d; last scored week starts at last_d
r2 = lambda v: round(float(v) * 100, 2)

# 1. every scored week: share of stocks inside their cone, average move
weeks = s.groupby("date").agg(cov=("inside", "mean"), ret=("y", "mean"), width=("q90", "mean"))
widths = P.assign(w=P.q90 - P.q10).groupby("date").w.mean()
weeks_out = [{"d": d.strftime("%Y-%m-%d"), "cov": round(float(r["cov"]), 3), "ret": r2(r["ret"])} for d, r in weeks.iterrows()]

# 2. last week: the cone break
lw = s[s.date == last_d]
last_week = [{"t": r.ticker, "s": SECTOR[r.ticker], "lo": r2(r.q10), "mid": r2(r.q50), "hi": r2(r.q90), "y": r2(r.y)}
             for r in lw.itertuples()]

# 3. live week: the bet, and how it's going so far (daily closes since live_d)
lv = P[P.date == live_d].set_index("ticker")
d = px[px.date >= live_d].pivot(index="date", columns="ticker", values="adj_close")
sofar = d.iloc[-1] / d.iloc[0] - 1
top = lv.pred_ex.nlargest(10).index.tolist(); bot = lv.pred_ex.nsmallest(10).index.tolist()
live = [{"t": t, "s": SECTOR[t], "ex": r2(r.pred_ex), "lo": r2(r.q10), "mid": r2(r.q50), "hi": r2(r.q90),
         "sofar": r2(sofar[t]), "rank": int(i)} for i, (t, r) in enumerate(lv.sort_values("pred_ex", ascending=False).iterrows())]
cur_w = float(widths.loc[live_d])
prev_wider = widths[(widths.index < live_d) & (widths >= cur_w)]
wider_since = prev_wider.index.max().strftime("%Y-%m-%d") if len(prev_wider) else None

# 4. NVDA daily, last ~6 weeks, with the two cones
nv = px[(px.ticker == "NVDA") & (px.date >= live_d - pd.Timedelta(weeks=6))].sort_values("date")
nv_close = W[(W.ticker == "NVDA")].set_index("date").close
def cone(dt):
    r = P[(P.date == dt) & (P.ticker == "NVDA")].iloc[0]; base = float(nv_close.loc[dt])
    return {"from": dt.strftime("%Y-%m-%d"), "base": round(base, 2), "lo": round(base * (1 + r.q10), 2),
            "mid": round(base * (1 + r.q50), 2), "hi": round(base * (1 + r.q90), 2)}
nvda = {"daily": [{"d": x.date.strftime("%Y-%m-%d"), "c": round(float(x.adj_close), 2)} for x in nv.itertuples()],
        "cones": [cone(last_d), cone(live_d)]}

# 5. track record
s["dir"] = (s.pred_ex > 0) == (s.y_ex > 0)
spread = s.groupby("date").apply(lambda g: g.nlargest(10, "pred_ex").y.mean() - g.nsmallest(10, "pred_ex").y.mean())
top_g = s.groupby("date").apply(lambda g: g.nlargest(10, "pred_ex").y.mean())
uni_g = s.groupby("date").y.mean()
race = pd.DataFrame({"top": (1 + top_g).cumprod(), "all": (1 + uni_g).cumprod(),
                     "bot": (1 + s.groupby("date").apply(lambda g: g.nsmallest(10, "pred_ex").y.mean())).cumprod()})
record = {
    "inside": round(float(s.inside.mean()) * 100, 1),
    "dir": round(float(s.dir.mean()) * 100, 1),
    "spread_win": round(float((spread > 0).mean()) * 100, 0),
    "n_weeks": int(len(weeks)), "n_preds": int(len(s)),
    "race": [{"d": d.strftime("%Y-%m-%d"), **{k: round(float(v), 3) for k, v in r.items()}} for d, r in race.iterrows()],
}

# 6. explorer: weekly close + cone per stock from 2023
stocks = {}
for t, g in W[W.date >= "2022-12-01"].groupby("ticker"):
    pp = P[P.ticker == t].set_index("date")
    rows = []
    for x in g.sort_values("date").itertuples():
        row = {"d": x.date.strftime("%Y-%m-%d"), "c": round(float(x.close), 2)}
        if x.date in pp.index:
            q = pp.loc[x.date]; row["q"] = [round(float(x.close * (1 + q[k])), 2) for k in ("q10", "q50", "q90")]
        rows.append(row)
    stocks[t] = {"s": SECTOR[t], "w": rows}

# 7. what the filings add: cones in earnings weeks, price-only vs with filings
fil = c.execute("select ticker, filing_date, items from filings where form in ('8-K','8-K/A')").df()
fil["filing_date"] = pd.to_datetime(fil.filing_date)
earn = fil[fil["items"].fillna("").str.contains("2.02", regex=False)]
def earn_flag(df):
    m = df[["date", "ticker"]].merge(earn[["ticker", "filing_date"]], on="ticker")
    m = m[(m.filing_date > m.date) & (m.filing_date <= m.date + pd.Timedelta(days=7))]
    k = set(zip(m.date, m.ticker)); return np.array([(a, b) in k for a, b in zip(df.date, df.ticker)])
cmp = {}
for name, Q in (("price", P0), ("intel", P)):
    q = Q.dropna(subset=["y"]).copy(); q["inside"] = (q.y >= q.q10) & (q.y <= q.q90); q["w"] = q.q90 - q.q10
    e = earn_flag(q)
    cmp[name] = {"earn_inside": round(float(q[e].inside.mean()) * 100, 1), "other_inside": round(float(q[~e].inside.mean()) * 100, 1),
                 "earn_width": round(float(q[e].w.mean()) * 100, 1), "other_width": round(float(q[~e].w.mean()) * 100, 1),
                 "n_earn": int(e.sum())}
q = s.copy(); q["earn"] = earn_flag(q)
cmp["earn_move"] = round(float(q[q.earn].y.abs().mean()) * 100, 1); cmp["other_move"] = round(float(q[~q.earn].y.abs().mean()) * 100, 1)
F = intel_features.build(c, pd.DatetimeIndex(dates), sorted(P.ticker.unique())).reset_index()
q = q.merge(F[["date", "ticker", "ins_buyers_90d"]], on=["date", "ticker"], how="left")
g = q.ins_buyers_90d >= 2
cmp["cluster_n"] = int(g.sum()); cmp["cluster_ex"] = round(float(q[g].y_ex.mean()) * 100, 2); cmp["rest_ex"] = round(float(q[~g].y_ex.mean()) * 100, 2)

# 8. this week's intelligence per stock (as of the live Friday, filings before it)
ins = c.execute("select ticker, filing_date, code, value, owner from insider_tx").df(); ins["filing_date"] = pd.to_datetime(ins.filing_date)
win = ins[(ins.filing_date < live_d) & (ins.filing_date >= live_d - pd.Timedelta(days=90))]
intel = {}
for t in P.ticker.unique():
    w_ = win[win.ticker == t]; f_ = fil[(fil.ticker == t) & (fil.filing_date < live_d)]
    le = earn[(earn.ticker == t) & (earn.filing_date < live_d)].filing_date.max()
    recent = f_[f_.filing_date >= live_d - pd.Timedelta(days=45)]
    tags = []
    for it in recent["items"].fillna(""):
        if "5.02" in it: tags.append("Executive change")
        if any(x in it for x in ("1.01", "2.01", "1.02")): tags.append("Deal or agreement")
    intel[t] = {"buys": int((w_.code == "P").sum()), "buyers": int(w_[w_.code == "P"].owner.nunique()), "buy_usd": round(float(w_[w_.code == "P"].value.sum())),
                "sales": int((w_.code == "S").sum()), "sale_usd": round(float(w_[w_.code == "S"].value.sum())),
                "last_earn": le.strftime("%Y-%m-%d") if pd.notna(le) else None,
                "earn_days": int((live_d - le).days) if pd.notna(le) else None, "tags": sorted(set(tags))}
import re
ALIAS = {"PM": ["Philip Morris", "PMI"], "CMCSA": ["Comcast"], "GOOGL": ["Google", "Alphabet"], "META": ["Meta"], "BRK-B": ["Berkshire"]}
def names_company(title, t, company):
    keys = ALIAS.get(t, []) + [company, company.split()[0] if len(company.split()[0]) > 4 else company]
    return any(re.search(r"\b" + re.escape(k) + r"\b", title, re.I) for k in keys if k)
def tidy(x):
    x = re.sub(r"\s+([,:;.!?%)])", r"\1", x); x = re.sub(r"([($])\s+", r"\1", x)
    return re.sub(r"\s*'\s*", "'", re.sub(r"\s+", " ", x)).strip()
ev_p = ROOT / "data" / "raw" / f"evidence_{live_d.date()}.json"
if ev_p.exists():
    for t, e in json.loads(ev_p.read_text()).items():
        if t in intel:
            intel[t]["name"] = e.get("company")
            intel[t]["news"] = [{"date": h["date"], "source": h["source"], "title": tidy(h["title"])}
                                for h in e.get("headlines_7d", []) if names_company(h["title"], t, e.get("company", ""))][:3]
            intel[t]["filings"] = [{"date": f["date"], "items": f["items"]} for f in e.get("filings_45d", [])]
brief_p = ROOT / "site" / "brief.json"
brief = json.loads(brief_p.read_text()) if brief_p.exists() else None
if brief and brief.get("week_from") != live_d.strftime("%Y-%m-%d"): brief = None

out = {
    "asof": px.date.max().strftime("%Y-%m-%d"),
    "last_week": {"from": last_d.strftime("%Y-%m-%d"), "to": live_d.strftime("%Y-%m-%d"),
                  "below": int((lw.y < lw.q10).sum()), "above": int((lw.y > lw.q90).sum()), "n": int(len(lw)),
                  "avg": r2(lw.y.mean()), "normal_inside": round(float(weeks["cov"].median()) * 100, 0),
                  "stocks": last_week},
    "live": {"from": live_d.strftime("%Y-%m-%d"), "days": int(len(d) - 1), "top": top, "bottom": bot,
             "top_sofar": r2(sofar[top].mean()), "bot_sofar": r2(sofar[bot].mean()),
             "all_sofar": r2(sofar.drop("SPY").mean()), "spy_sofar": r2(sofar["SPY"]),
             "width": round(cur_w * 100, 1), "width_normal": round(float(widths.median()) * 100, 1),
             "wider_since": wider_since, "stocks": live},
    "nvda": nvda, "weeks": weeks_out, "record": record, "stocks": stocks,
    "compare": cmp, "intel": intel, "brief": brief,
    "price_only": {k: json.loads((ROOT / "model" / f"results_{k}.json").read_text())["ic_mean"] for k in ("price", "intel")},
}
(ROOT / "site" / "story.json").write_text(json.dumps(out, separators=(",", ":")))
print({k: v for k, v in out["live"].items() if k != "stocks"})
print({k: v for k, v in out["last_week"].items() if k != "stocks"})
print({k: v for k, v in record.items() if k != "race"}, "race end", record["race"][-1])
print("compare", cmp)
print("size MB", round((ROOT / "site" / "story.json").stat().st_size / 1e6, 2))
