"""Fetch the original UCI workbook and cache a typed, unmodified-row Parquet table."""
from pathlib import Path
import hashlib,json,urllib.request,zipfile
import pandas as pd
ROOT=Path(__file__).resolve().parent
URL='https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip'
def prepare():
 raw=ROOT/'data/raw';raw.mkdir(parents=True,exist_ok=True)
 archive=raw/'online-retail-ii.zip'
 if not archive.exists():
  print('Downloading original UCI archive...',flush=True);urllib.request.urlretrieve(URL,archive)
 xlsx=raw/'online_retail_II.xlsx'
 if not xlsx.exists():
  with zipfile.ZipFile(archive) as z:z.extract('online_retail_II.xlsx',raw)
 cache=ROOT/'data/transactions.parquet'
 if not cache.exists():
  frames=[]
  for sheet in pd.ExcelFile(xlsx).sheet_names:
   print('Reading',sheet,flush=True)
   f=pd.read_excel(xlsx,sheet_name=sheet,dtype={'Invoice':str,'StockCode':str,'Customer ID':str})
   f.columns=['invoice','stock_code','description','quantity','invoice_date','unit_price','customer_id','country']
   f['customer_id']=f.customer_id.str.replace(r'\.0$','',regex=True)
   f['quantity']=pd.to_numeric(f.quantity);f['unit_price']=pd.to_numeric(f.unit_price)
   frames.append(f)
  f=pd.concat(frames,ignore_index=True)
  import duckdb
  duckdb.connect().register('frame',f).execute(f"COPY frame TO '{cache}' (FORMAT PARQUET)")
  print('Cached',len(f),'source rows',flush=True)
 metadata={'title':'Online Retail II','creator':'Daqing Chen','publisher':'UCI Machine Learning Repository','doi':'10.24432/C5CG6D','source':'https://archive.ics.uci.edu/dataset/502/online+retail+ii','download':URL,'license':'CC BY 4.0','license_url':'https://creativecommons.org/licenses/by/4.0/','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'analysis_end_exclusive':'2011-12-01','note':'Historical data. Meridian is a fictional presentation brand, not the retailer. December 2011 is excluded because the source stops on 9 December.'}
 (ROOT/'data/source.json').write_text(json.dumps(metadata,indent=2))
 return cache
if __name__=='__main__':prepare()
