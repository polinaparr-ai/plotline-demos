-- As-of snapshot. Features use purchases strictly before the supplied cutoff.
WITH history AS (
 SELECT customer_id, arg_max(country,purchased_at) AS country,
 date_diff('day',max(purchased_at),$cutoff::TIMESTAMP) AS recency,
 count(DISTINCT invoice) AS frequency, sum(gross_sales) AS monetary,
 avg(gross_sales) AS average_order, sum(units) AS units,
 min(purchased_at) AS first_purchase, max(purchased_at) AS last_purchase
 FROM orders WHERE customer_id IS NOT NULL AND gross_sales>0 AND purchased_at<$cutoff
 GROUP BY customer_id
)
SELECT *, CASE WHEN recency<=45 AND frequency>=8 THEN 'Champions'
 WHEN recency<=90 AND frequency>=3 THEN 'Loyal'
 WHEN recency>90 AND frequency>=3 THEN 'At risk'
 WHEN recency<=90 AND frequency<3 THEN 'New & promising'
 ELSE 'Hibernating' END AS segment,
 CASE WHEN country='United Kingdom' THEN 'uk' ELSE 'international' END AS market
FROM history ORDER BY monetary DESC;
