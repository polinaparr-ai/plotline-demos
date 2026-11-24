SELECT stock_code, arg_max(description,invoice_date) AS description,
 sum(gross_sales) AS gross, sum(credits) AS credits, sum(signed_value) AS net,
 sum(CASE WHEN signed_value>0 THEN quantity ELSE 0 END) AS units,
 count(DISTINCT CASE WHEN signed_value>0 THEN invoice END) AS orders
FROM ledger WHERE invoice_date >= $start AND invoice_date < $end
 AND ($market='all' OR market=$market)
GROUP BY stock_code ORDER BY net DESC LIMIT 100;
