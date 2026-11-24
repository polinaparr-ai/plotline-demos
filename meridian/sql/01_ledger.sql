-- Canonical merchandise ledger. Exact duplicate rows are removed as a stated demo policy.
-- Keep missing customer IDs for financial totals; exclude them only from customer models.
CREATE OR REPLACE TABLE ledger AS
WITH deduplicated AS (SELECT DISTINCT * FROM raw_transactions), typed AS (
 SELECT *, CASE WHEN quantity < 0 OR upper(invoice) LIKE 'C%' THEN -abs(quantity * unit_price)
                 ELSE quantity * unit_price END AS signed_value,
 CASE WHEN country = 'United Kingdom' THEN 'uk' ELSE 'international' END AS market
 FROM deduplicated
 WHERE invoice_date >= TIMESTAMP '2009-12-01' AND invoice_date < TIMESTAMP '2011-12-01'
 AND quantity <> 0 AND unit_price > 0
 AND regexp_full_match(stock_code, '[0-9]{5}[A-Za-z]*')
)
SELECT *, CASE WHEN signed_value > 0 THEN signed_value ELSE 0 END AS gross_sales,
 CASE WHEN signed_value < 0 THEN -signed_value ELSE 0 END AS credits
FROM typed;
CREATE OR REPLACE TABLE orders AS
SELECT invoice, min(invoice_date) AS purchased_at, customer_id, country, market,
 sum(gross_sales) AS gross_sales, sum(credits) AS credits, sum(signed_value) AS net_sales,
 sum(CASE WHEN signed_value>0 THEN quantity ELSE 0 END) AS units,
 count(DISTINCT CASE WHEN signed_value>0 THEN stock_code END) AS products
FROM ledger GROUP BY invoice, customer_id, country, market;
