-- Named parameters are bound by DuckDB, not interpolated from browser input.
SELECT coalesce(sum(gross_sales),0) AS gross, coalesce(sum(credits),0) AS credits,
 coalesce(sum(net_sales),0) AS net,
 count(DISTINCT CASE WHEN gross_sales>0 THEN invoice END) AS orders,
 count(DISTINCT CASE WHEN gross_sales>0 THEN customer_id END) AS customers,
 count(DISTINCT CASE WHEN gross_sales>0 THEN country END) AS countries,
 coalesce(sum(CASE WHEN gross_sales>0 AND customer_id IS NOT NULL THEN gross_sales ELSE 0 END),0) AS identified_gross
FROM orders
WHERE purchased_at >= $start AND purchased_at < $end
 AND ($market='all' OR market=$market);
