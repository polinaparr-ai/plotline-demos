-- Predict a repeat purchase, and spend, in the next 90 days from 180 days of purchase history.
-- A temporal cutoff separates features and outcomes. Customer ID is never a feature.
WITH features AS (
 SELECT customer_id,
 date_diff('day',max(purchased_at),$cutoff::TIMESTAMP) AS recency,
 count(DISTINCT invoice) AS frequency, sum(gross_sales) AS monetary,
 avg(gross_sales) AS average_order, sum(units) AS units,
 date_diff('day',min(purchased_at),$cutoff::TIMESTAMP) AS observed_tenure,
 count(DISTINCT date_trunc('month',purchased_at)) AS active_months
 FROM orders WHERE customer_id IS NOT NULL AND gross_sales>0
 AND purchased_at >= $cutoff::TIMESTAMP - INTERVAL '180 days' AND purchased_at < $cutoff
 GROUP BY customer_id
), outcomes AS (
 SELECT customer_id, sum(gross_sales) AS next_spend FROM orders WHERE customer_id IS NOT NULL AND gross_sales>0
 AND purchased_at >= $cutoff AND purchased_at < $cutoff::TIMESTAMP + INTERVAL '90 days'
 GROUP BY customer_id
)
SELECT f.*, CASE WHEN o.customer_id IS NULL THEN 0 ELSE 1 END AS repeated, coalesce(o.next_spend, 0) AS next_spend
FROM features f LEFT JOIN outcomes o USING(customer_id) ORDER BY customer_id;
