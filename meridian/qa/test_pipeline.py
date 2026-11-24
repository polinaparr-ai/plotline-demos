"""Independent checks of SQL accounting and temporal model boundaries."""
from pathlib import Path
import json
import duckdb
ROOT=Path(__file__).resolve().parents[1]
con=duckdb.connect(str(ROOT/'data/commerce.duckdb'),read_only=True)
# An independent raw-ledger reconciliation, rather than relying on browser labels.
sales,credits,net=con.execute('SELECT sum(gross_sales),sum(credits),sum(signed_value) FROM ledger').fetchone()
assert abs(sales-credits-net)<.01
assert con.execute("SELECT count(*) FROM ledger WHERE invoice_date >= '2011-12-01'").fetchone()[0]==0
assert con.execute('SELECT count(*) FROM ledger WHERE unit_price<=0 OR quantity=0').fetchone()[0]==0
assert con.execute("SELECT count(*) FROM ledger WHERE gross_sales<0 OR credits<0 OR (gross_sales>0 AND credits>0)").fetchone()[0]==0
sql=(ROOT/'sql/30_model_features.sql').read_text()
for cutoff in ['2010-09-01','2011-06-01']:
 frame=con.execute(sql,{'cutoff':cutoff}).df()
 assert frame.customer_id.is_unique
 assert frame.repeated.isin([0,1]).all()
 assert frame.recency.min()>=0 and frame.recency.max()<=180
 assert frame.frequency.min()>0
 # Verify one customer's label directly from a separately written query.
 for customer in frame.iloc[::max(1,len(frame)//15)].itertuples():
  observed=con.execute("SELECT count(*)>0 FROM orders WHERE customer_id=? AND gross_sales>0 AND purchased_at>=CAST(? AS TIMESTAMP) AND purchased_at<CAST(? AS TIMESTAMP)+INTERVAL '90 days'",[customer.customer_id,cutoff,cutoff]).fetchone()[0]
  assert int(observed)==customer.repeated
print('Passed signed-ledger reconciliation, exclusion rules, customer uniqueness and independently recomputed model labels at both temporal cutoffs.')
