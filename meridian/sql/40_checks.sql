SELECT 'Original workbook rows' AS check_name,count(*) AS value FROM raw_transactions
UNION ALL SELECT 'Exact duplicate rows removed',count(*)-(SELECT count(*) FROM (SELECT DISTINCT * FROM raw_transactions)) FROM raw_transactions
UNION ALL SELECT 'Merchandise ledger rows',count(*) FROM ledger
UNION ALL SELECT 'Anonymous ledger rows',count(*) FROM ledger WHERE customer_id IS NULL
UNION ALL SELECT 'Excluded partial December 2011 rows',count(*) FROM raw_transactions WHERE invoice_date>=TIMESTAMP '2011-12-01'
UNION ALL SELECT 'Missing purchase timestamps',count(*) FROM raw_transactions WHERE invoice_date IS NULL
UNION ALL SELECT 'Ledger reconciliation difference',round(abs(sum(gross_sales)-sum(credits)-sum(signed_value)),6) FROM ledger
UNION ALL SELECT 'Largest single credit note (£)',round(max(c),0) FROM (SELECT sum(credits) c FROM ledger GROUP BY invoice)
UNION ALL SELECT 'Largest credit note, % of all credits',round(100*max(c)/sum(c),1) FROM (SELECT sum(credits) c FROM ledger GROUP BY invoice);
