-- Weekly net merchandise sales (weeks start Monday). Only complete weeks are kept.
SELECT date_trunc('week', invoice_date)::DATE AS week, sum(signed_value) AS net, count(DISTINCT invoice) AS orders
FROM ledger WHERE invoice_date >= TIMESTAMP '2009-12-07' AND invoice_date < TIMESTAMP '2011-11-28'
GROUP BY 1 ORDER BY 1;
