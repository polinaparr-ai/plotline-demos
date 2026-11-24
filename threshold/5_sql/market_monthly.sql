-- chart:   sales_monthly, median_price_monthly, KPI tiles
-- metrics: sales_count, median_price, new_build_share   (semantic_layer/metrics.yml)
-- grain:   month x region x property_type, with 'All' rollups so the dashboard filters
--          can switch without another query.
SELECT
    sale_month,
    coalesce(region, 'All')        AS region,
    coalesce(property_type, 'All') AS property_type,
    COUNT(*)                                             AS sales_count,
    MEDIAN(price_gbp)                                    AS median_price,
    AVG(CASE WHEN is_new_build THEN 1.0 ELSE 0.0 END)    AS new_build_share
FROM analytics.sales
WHERE ppd_category = 'A'                -- market sales only (semantic layer default filter)
GROUP BY GROUPING SETS (
    (sale_month, region, property_type),
    (sale_month, region),
    (sale_month, property_type),
    (sale_month)
)
ORDER BY sale_month, region, property_type;
