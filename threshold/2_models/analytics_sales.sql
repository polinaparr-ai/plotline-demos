-- analytics.sales: one row per registered residential sale.
-- Built from raw.price_paid: readable labels, regions, Stamp Duty price bands.
-- Address columns (house number, flat, street) stay in raw.price_paid.

CREATE TABLE analytics.sales AS
SELECT
    p.transaction_id,
    p.price                                   AS price_gbp,
    CAST(p.transfer_date AS DATE)             AS sale_date,
    CAST(date_trunc('month', p.transfer_date) AS DATE) AS sale_month,
    p.postcode,
    split_part(p.postcode, ' ', 1)            AS postcode_district,
    CASE p.property_type WHEN 'D' THEN 'Detached' WHEN 'S' THEN 'Semi-detached'
         WHEN 'T' THEN 'Terraced' WHEN 'F' THEN 'Flat/maisonette' ELSE 'Other' END AS property_type,
    p.old_new = 'Y'                           AS is_new_build,
    CASE p.duration WHEN 'F' THEN 'Freehold' WHEN 'L' THEN 'Leasehold' ELSE 'Unknown' END AS tenure,
    p.town_city, coalesce(s.district, p.district) AS district, p.county,
    r.region, r.country,
    p.ppd_category,
    CASE
      WHEN p.price < 125000 THEN '01 Under £125k'
      WHEN p.price < 250000 THEN '02 £125k–250k'
      WHEN p.price < 300000 THEN '03 £250k–300k'
      WHEN p.price < 425000 THEN '04 £300k–425k'
      WHEN p.price < 500000 THEN '05 £425k–500k'
      WHEN p.price < 625000 THEN '06 £500k–625k'
      WHEN p.price < 925000 THEN '07 £625k–925k'
      ELSE '08 £925k+' END                    AS price_band
FROM raw.price_paid p
LEFT JOIN ref.district_successor s ON s.old_district = p.district
LEFT JOIN ref.district_region r ON r.district = coalesce(s.district, p.district)
WHERE p.record_status = 'A'
    ;
