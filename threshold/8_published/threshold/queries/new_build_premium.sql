-- chart:   new_build_premium
-- metrics: median_price, sales_count
-- 2025 median price of new builds and existing homes, by property type.
SELECT
    coalesce(region, 'All') AS region,
    property_type,
    is_new_build,
    COUNT(*)          AS sales_count,
    MEDIAN(price_gbp) AS median_price
FROM analytics.sales
WHERE ppd_category = 'A'
  AND year(sale_month) = 2025
  AND property_type <> 'Other'
GROUP BY GROUPING SETS ((region, property_type, is_new_build), (property_type, is_new_build))
ORDER BY region, property_type, is_new_build;
