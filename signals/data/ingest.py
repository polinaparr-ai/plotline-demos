"""Pull ~10y of daily adjusted prices for a large-cap US universe into DuckDB.

Universe: today's S&P 100 members (approx.). Note: using today's members is
survivorship-biased; point-in-time membership is a later fix.
"""
import json, time, urllib.request, datetime as dt
from pathlib import Path
import duckdb, pandas as pd

ROOT = Path(__file__).resolve().parent
UNIVERSE = """AAPL MSFT NVDA AMZN GOOGL META BRK-B AVGO TSLA JPM LLY V UNH XOM MA JNJ PG HD COST ABBV
MRK WMT NFLX CVX BAC KO ORCL CRM AMD PEP ADBE TMO LIN MCD CSCO ACN ABT WFC DIS INTU QCOM
TXN DHR IBM VZ AMGN CAT GE PFE CMCSA NOW AMAT UNP PM SPGI NEE ISRG LOW RTX HON GS BKNG
T UPS COP PLD BLK ELV SBUX MS LMT MDT DE SCHW AXP C GILD ADP CVS BA MDLZ MO SO DUK CL
MMM TGT USB BMY CI NKE INTC EMR GD F GM KHC MET AIG COF FDX SPY""".split()


def fetch(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1=1420070400&period2=9999999999&interval=1d&events=div,split"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return pd.DataFrame({
        "date": [dt.datetime.utcfromtimestamp(t).date() for t in r["timestamp"]],
        "ticker": sym,
        "close": q["close"],
        "adj_close": r["indicators"]["adjclose"][0]["adjclose"],
        "volume": q["volume"],
    }).dropna(subset=["adj_close"])


frames, failed = [], []
for s in UNIVERSE:
    try:
        frames.append(fetch(s))
    except Exception as e:
        failed.append((s, str(e)[:60]))
    time.sleep(0.3)

def clean(g):
    """Repair adjustment glitches: the adjusted series jumps >25% on a day the raw
    close barely moved (<10%). Real splits do the opposite, so they're untouched.
    Rescale all earlier adjusted prices so that day's adjusted return = raw return."""
    g = g.sort_values("date").copy()
    ra, rc = g["adj_close"].pct_change(), g["close"].pct_change()
    for i in g.index[(ra.abs() > 0.25) & (rc.abs() < 0.10)]:
        pos = g.index.get_loc(i)
        factor = (1 + ra.iloc[pos]) / (1 + rc.iloc[pos])
        g.iloc[:pos, g.columns.get_loc("adj_close")] *= factor
        print(f"  fixed {g['ticker'].iloc[0]} {g['date'].iloc[pos]}: adj {ra.iloc[pos]:+.1%} vs close {rc.iloc[pos]:+.1%}")
    return g


df = pd.concat(clean(f) for f in frames)
con =duckdb.connect(str(ROOT / "signals.duckdb"))
con.execute("CREATE OR REPLACE TABLE prices AS SELECT * FROM df")
print(con.execute("SELECT count(DISTINCT ticker), count(*), min(date), max(date) FROM prices").fetchone())
print("failed:", failed)
