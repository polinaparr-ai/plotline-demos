-- chart:   district_movers
-- metrics: median_price, sales_count
-- Local authorities with at least 500 market sales in each year, 2025 vs 2024.
WITH d AS (
    SELECT
        district, region,
        COUNT(*) FILTER (WHERE year(sale_month) = 2024)          AS sales_2024,
        COUNT(*) FILTER (WHERE year(sale_month) = 2025)          AS sales_2025,
        MEDIAN(price_gbp) FILTER (WHERE year(sale_month) = 2024) AS median_2024,
        MEDIAN(price_gbp) FILTER (WHERE year(sale_month) = 2025) AS median_2025
    FROM analytics.sales
    WHERE ppd_category = 'A'
      AND year(sale_month) IN (2024, 2025)
    GROUP BY district, region
)
SELECT *,
       median_2025 / median_2024 - 1 AS median_change,
       sales_2025 / sales_2024 - 1   AS sales_change
FROM d
WHERE sales_2024 >= 500 AND sales_2025 >= 500
ORDER BY median_change DESC, district;
