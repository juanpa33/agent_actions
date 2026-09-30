-- Paridad de tarifas: precio publicado en cada OTA vs. el canal directo (misma moneda local).
CREATE OR REPLACE TABLE gold_parity AS
WITH direct AS (
  SELECT hotel_id, room_type, CAST(stay_date AS DATE) AS stay_date, rate_amount AS direct_local
  FROM silver_ari WHERE channel = 'DIRECT'
)
SELECT a.hotel_id, a.room_type, CAST(a.stay_date AS DATE) AS stay_date, a.channel,
       d.direct_local, a.rate_amount AS channel_local, a.currency,
       a.rate_amount / d.direct_local - 1.0 AS diff_pct,
       ABS(a.rate_amount / d.direct_local - 1.0) > 0.01 AS breach,
       CASE WHEN a.rate_amount < d.direct_local THEN 'OTA más barata que directo'
            WHEN a.rate_amount > d.direct_local THEN 'OTA más cara que directo' END AS breach_type
FROM silver_ari a
JOIN direct d ON d.hotel_id = a.hotel_id AND d.room_type = a.room_type AND d.stay_date = CAST(a.stay_date AS DATE)
WHERE a.channel <> 'DIRECT';
