WITH first_order AS (
 SELECT customer_id, date_trunc('month',min(purchased_at)) AS cohort
 FROM orders WHERE customer_id IS NOT NULL AND gross_sales>0 GROUP BY customer_id
), activity AS (
 SELECT DISTINCT o.customer_id,f.cohort,date_diff('month',f.cohort,date_trunc('month',o.purchased_at)) AS month_index
 FROM orders o JOIN first_order f USING(customer_id) WHERE o.gross_sales>0
), sizes AS (SELECT cohort,count(*) AS customers FROM first_order GROUP BY cohort)
SELECT CAST(a.cohort AS DATE) AS cohort,a.month_index,count(DISTINCT a.customer_id) AS active,
 max(s.customers) AS cohort_size, count(DISTINCT a.customer_id)::DOUBLE/max(s.customers) AS retention
FROM activity a JOIN sizes s USING(cohort)
WHERE a.month_index<=11 GROUP BY a.cohort,a.month_index ORDER BY a.cohort,a.month_index;
