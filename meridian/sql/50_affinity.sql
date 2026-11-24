-- Products bought together. A basket is one invoice. Lift = how much more often two products
-- share a basket than chance would predict (1 = no link). Only products and pairs seen in at
-- least $minsup baskets are kept, so rare coincidences do not show up as patterns.
WITH basket AS (
 SELECT DISTINCT invoice, stock_code FROM ledger
 WHERE signed_value > 0 AND invoice_date >= $start::TIMESTAMP AND invoice_date < $end::TIMESTAMP
), total AS (SELECT count(DISTINCT invoice) AS baskets FROM basket),
item AS (SELECT stock_code, count(*) AS baskets FROM basket GROUP BY 1 HAVING count(*) >= $minsup),
pair AS (
 SELECT a.stock_code AS item_a, b.stock_code AS item_b, count(*) AS together
 FROM basket a JOIN basket b ON a.invoice = b.invoice AND a.stock_code < b.stock_code
 WHERE a.stock_code IN (SELECT stock_code FROM item) AND b.stock_code IN (SELECT stock_code FROM item)
 GROUP BY 1, 2 HAVING count(*) >= $minsup
)
SELECT item_a, item_b, together, ia.baskets AS baskets_a, ib.baskets AS baskets_b,
 total.baskets AS baskets_total,
 together * 1.0 * total.baskets / (ia.baskets * ib.baskets) AS lift
FROM pair JOIN item ia ON ia.stock_code = item_a JOIN item ib ON ib.stock_code = item_b
CROSS JOIN total ORDER BY together DESC;
