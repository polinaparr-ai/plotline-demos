-- chart:   region_price_change
-- metrics: median_price, sales_count
-- Compares calendar 2025 with 2024: the last two complete years (2026 is provisional).
SELECT
    coalesce(region, 'All')        AS region,
    coalesce(property_type, 'All') AS property_type,
    COUNT(*) FILTER (WHERE year(sale_month) = 2024)            AS sales_2024,
    COUNT(*) FILTER (WHERE year(sale_month) = 2025)            AS sales_2025,
    MEDIAN(price_gbp) FILTER (WHERE year(sale_month) = 2024)   AS median_2024,
    MEDIAN(price_gbp) FILTER (WHERE year(sale_month) = 2025)   AS median_2025
FROM analytics.sales
WHERE ppd_category = 'A'
  AND year(sale_month) IN (2024, 2025)
GROUP BY GROUPING SETS ((region, property_type), (region), (property_type), ())
ORDER BY region, property_type;
