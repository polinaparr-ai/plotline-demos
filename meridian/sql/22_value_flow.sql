-- Gross sales across three dimensions; each layer reconciles to identified gross sales.
WITH first_purchase AS (
 SELECT customer_id,min(purchased_at) AS first_at FROM orders WHERE gross_sales>0 AND customer_id IS NOT NULL GROUP BY customer_id
), joined AS (
 SELECT o.*,CASE WHEN country='United Kingdom' THEN 'United Kingdom' ELSE 'International' END AS origin,
 CASE WHEN f.first_at >= $start THEN 'New customers' ELSE 'Existing customers' END AS lifecycle,
 CASE WHEN gross_sales>=500 THEN '£500+ baskets' WHEN gross_sales>=150 THEN '£150–499 baskets' ELSE 'Under £150' END AS basket
 FROM orders o JOIN first_purchase f USING(customer_id)
 WHERE gross_sales>0 AND purchased_at >= $start AND purchased_at < $end AND ($market='all' OR market=$market)
)
SELECT origin,lifecycle,basket,sum(gross_sales) AS value FROM joined GROUP BY origin,lifecycle,basket;
