"""SEC EDGAR market intelligence for the universe, into DuckDB.

Tables written:
  filings      every filing for each company: form, filing date, acceptance time, 8-K item codes
  insider_tx   open-market insider purchases (P) and sales (S): who, when filed, shares, value

Insider data: SEC quarterly Form 3/4/5 data sets (2018Q1 to latest published quarter), then
individual Form 4 XML filings after that. Everything keyed by FILING date, so features only
use what was public at the time.
"""
import io, json, sys, time, zipfile, urllib.request, urllib.error
from pathlib import Path
import pandas as pd, duckdb
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "sec_insider"
UA = {"User-Agent": "PlotlineDemo research-bot admin@plotline-demo.invalid"}
con = duckdb.connect(str(ROOT / "signals.duckdb"))
tickers = [t for (t,) in con.execute("select distinct ticker from prices where ticker <> 'SPY'").fetchall()]

_last = [0.0]
def get(url, binary=False):
    for attempt in range(4):
        wait = 0.12 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read(); return b if binary else b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None

# ---- 1. ticker -> CIK ----------------------------------------------------------------
m = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
cik_of = {v["ticker"].replace(".", "-"): int(v["cik_str"]) for v in m.values()}
missing = [t for t in tickers if t not in cik_of]
print("no CIK for", missing)
ciks = {t: cik_of[t] for t in tickers if t in cik_of}
t_of = {c: t for t, c in ciks.items()}

# ---- 2. filings index ----------------------------------------------------------------
rows = []
def take(block, t, c):
    for i in range(len(block["form"])):
        rows.append((t, c, block["form"][i], block["filingDate"][i], block["acceptanceDateTime"][i],
                     block["items"][i], block["accessionNumber"][i], block["primaryDocument"][i]))
for t, c in ciks.items():
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{c:010d}.json"))
    take(sub["filings"]["recent"], t, c)
    for f in sub["filings"].get("files", []):
        older = get(f"https://data.sec.gov/submissions/{f['name']}")
        if older: take(json.loads(older), t, c)
filings = pd.DataFrame(rows, columns=["ticker", "cik", "form", "filing_date", "accepted", "items", "accession", "doc"])
filings["filing_date"] = pd.to_datetime(filings["filing_date"])
filings = filings[filings.filing_date >= "2014-01-01"]
con.execute("CREATE OR REPLACE TABLE filings AS SELECT * FROM filings")
print("filings", len(filings), filings.form.value_counts().head(6).to_dict())

# ---- 3. insider trades, bulk quarters ------------------------------------------------
tx = []
quarters = [f"{y}q{q}" for y in range(2018, 2027) for q in range(1, 5)]
last_bulk_end = None
for qq in quarters:
    path = RAW / f"{qq}_form345.zip"
    if not path.exists():
        b = get(f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{qq}_form345.zip", binary=True)
        if b is None: break
        path.write_bytes(b)
    z = zipfile.ZipFile(path)
    rd = lambda n, cols: pd.read_csv(io.BytesIO(z.read(n)), sep="\t", usecols=cols, dtype=str, on_bad_lines="skip")
    sub = rd("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "ISSUERCIK", "DOCUMENT_TYPE"])
    sub = sub[sub.ISSUERCIK.astype(int).isin(t_of) & sub.DOCUMENT_TYPE.isin(["4", "4/A"])]
    nd = rd("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE"])
    nd = nd[nd.TRANS_CODE.isin(["P", "S"])]
    own = rd("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"]).drop_duplicates("ACCESSION_NUMBER")
    j = nd.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER", how="left")
    for r in j.itertuples():
        tx.append((t_of[int(r.ISSUERCIK)], r.FILING_DATE, r.TRANS_DATE, r.TRANS_CODE, r.TRANS_SHARES, r.TRANS_PRICEPERSHARE, r.RPTOWNERCIK, r.RPTOWNER_RELATIONSHIP, r.ACCESSION_NUMBER))
    last_bulk_end = qq
    print(qq, len(j), "trades")
bulk = pd.DataFrame(tx, columns=["ticker", "filing_date", "trans_date", "code", "shares", "price", "owner", "role", "accession"])
bulk["filing_date"] = pd.to_datetime(bulk.filing_date, format="%d-%b-%Y", errors="coerce")
bulk["trans_date"] = pd.to_datetime(bulk.trans_date, format="%d-%b-%Y", errors="coerce")

# ---- 4. insider trades after the last bulk quarter, from Form 4 XML -------------------
y, q = int(last_bulk_end[:4]), int(last_bulk_end[-1])
gap_start = pd.Timestamp(year=y + (q == 4), month=(q % 4) * 3 + 1, day=1)
todo = filings[(filings.form.isin(["4", "4/A"])) & (filings.filing_date >= gap_start)]
print("parsing", len(todo), "Form 4 XMLs filed since", gap_start.date())
xml_rows = []
for k, r in enumerate(todo.itertuples()):
    doc = r.doc.split("/")[-1]
    url = f"https://www.sec.gov/Archives/edgar/data/{r.cik}/{r.accession.replace('-', '')}/{doc}"
    body = get(url)
    if not body: continue
    try:
        x = ET.fromstring(body.encode())
    except Exception:
        continue
    if int(x.findtext("issuer/issuerCik", "0")) != r.cik: continue      # company as owner, skip
    owner = x.findtext("reportingOwner/reportingOwnerId/rptOwnerCik")
    rel = x.find("reportingOwner/reportingOwnerRelationship")
    role = ",".join(e.tag for e in (rel if rel is not None else []) if (e.text or "").strip() in ("1", "true"))
    for t_ in x.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = t_.findtext("transactionCoding/transactionCode")
        if code not in ("P", "S"): continue
        xml_rows.append((r.ticker, r.filing_date, t_.findtext("transactionDate/value"), code,
                         t_.findtext("transactionAmounts/transactionShares/value"),
                         t_.findtext("transactionAmounts/transactionPricePerShare/value"), owner, role, r.accession))
    if k % 500 == 0: print("  ", k, "/", len(todo))
recent = pd.DataFrame(xml_rows, columns=bulk.columns)
recent["trans_date"] = pd.to_datetime(recent.trans_date, errors="coerce")
ins = pd.concat([bulk, recent], ignore_index=True)
ins["shares"] = pd.to_numeric(ins.shares, errors="coerce"); ins["price"] = pd.to_numeric(ins.price, errors="coerce")
ins["value"] = ins.shares * ins.price
ins = ins.dropna(subset=["filing_date", "value"]).drop_duplicates()
con.execute("CREATE OR REPLACE TABLE insider_tx AS SELECT * FROM ins")
print("insider trades", len(ins), ins.groupby("code").value.agg(["count", "sum"]).to_dict(), "max filing", ins.filing_date.max())
