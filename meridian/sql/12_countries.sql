SELECT country, sum(gross_sales) AS gross, sum(credits) AS credits,
 sum(net_sales) AS net, count(DISTINCT CASE WHEN gross_sales>0 THEN invoice END) AS orders,
 count(DISTINCT CASE WHEN gross_sales>0 THEN customer_id END) AS customers
FROM orders WHERE purchased_at >= $start AND purchased_at < $end
 AND ($market='all' OR market=$market)
GROUP BY country ORDER BY net DESC;
