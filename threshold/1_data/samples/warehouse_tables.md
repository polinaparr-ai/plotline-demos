# Warehouse tables

| Table | Rows | Columns |
|---|---:|---|
| ref.district_region | 328 | district, lad_code, region, country |
| ref.district_successor | 17 | old_district, district |
| ref.sdlt_bands | 13 | regime, buyer_type, lower_gbp, upper_gbp, rate |
| raw.price_paid | 3,244,237 | transaction_id, price, transfer_date, postcode, property_type, old_new, duration, paon, saon, street, locality, town_city, district, county, ppd_category, record_status |
| analytics.sales | 3,244,237 | transaction_id, price_gbp, sale_date, sale_month, postcode, postcode_district, property_type, is_new_build, tenure, town_city, district, county, region, country, ppd_category, price_band |

Raw files: pp-2023.csv, pp-2024.csv, pp-2025.csv, pp-2026.csv (565 MB).
