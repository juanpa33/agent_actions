-- Posición de precio vs. competencia (última captura del rate shopper), tipo Standard.
CREATE OR REPLACE TABLE gold_compset AS
WITH last_shop AS (SELECT MAX(shop_date) AS shop_date FROM silver_compset),
comp AS (
  SELECT c.hotel_id, CAST(c.stay_date AS DATE) AS stay_date,
         MEDIAN(c.rate_usd) AS comp_median_usd, MIN(c.rate_usd) AS comp_min_usd, MAX(c.rate_usd) AS comp_max_usd,
         COUNT(*) AS competitors
  FROM silver_compset c JOIN last_shop l ON c.shop_date = l.shop_date
  GROUP BY c.hotel_id, CAST(c.stay_date AS DATE)
),
ours AS (
  SELECT hotel_id, CAST(stay_date AS DATE) AS stay_date, rate_usd AS our_bar_usd
  FROM silver_ari WHERE channel = 'DIRECT' AND room_type = 'STD'
)
SELECT c.hotel_id, c.stay_date, c.stay_date - m.as_of_date AS days_out,
       o.our_bar_usd, c.comp_median_usd, c.comp_min_usd, c.comp_max_usd, c.competitors,
       o.our_bar_usd / c.comp_median_usd AS rate_index,
       e.event_name
FROM comp c CROSS JOIN meta m
LEFT JOIN ours o ON o.hotel_id = c.hotel_id AND o.stay_date = c.stay_date
LEFT JOIN gold_date_events e ON e.hotel_id = c.hotel_id AND e.stay_date = c.stay_date;
