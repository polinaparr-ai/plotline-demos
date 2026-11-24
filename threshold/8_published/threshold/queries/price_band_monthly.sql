-- chart:   sales_by_price_band (heatmap), band_march_change
-- metrics: sales_count
-- Price bands follow the Stamp Duty thresholds that changed on 1 April 2025:
--   standard nil-rate band £250k -> £125k; first-time buyer nil-rate £425k -> £300k,
--   first-time buyer relief cap £625k -> £500k.
SELECT
    sale_month,
    price_band,
    coalesce(region, 'All') AS region,
    COUNT(*)                AS sales_count
FROM analytics.sales
WHERE ppd_category = 'A'
GROUP BY GROUPING SETS ((sale_month, price_band, region), (sale_month, price_band))
ORDER BY sale_month, price_band, region;
