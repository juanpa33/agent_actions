-- Mezcla de canales por mes de estadía (solo estadías ya ocurridas): volumen, ingreso bruto y neto de comisión.
CREATE OR REPLACE TABLE gold_channel_mix AS
WITH base AS (
  SELECT hotel_id, channel, CAST(date_trunc('month', stay_date) AS DATE) AS month,
         COUNT(*) AS room_nights, SUM(rate_usd) AS gross_usd, SUM(net_rate_usd) AS net_usd
  FROM fact_room_night CROSS JOIN meta
  WHERE status = 'activa' AND stay_date < meta.as_of_date
  GROUP BY hotel_id, channel, CAST(date_trunc('month', stay_date) AS DATE)
)
SELECT b.*, b.gross_usd - b.net_usd AS commission_usd,
       b.gross_usd / b.room_nights AS adr_gross_usd, b.net_usd / b.room_nights AS adr_net_usd,
       b.room_nights * 1.0 / SUM(b.room_nights) OVER (PARTITION BY b.hotel_id, b.month) AS share_room_nights
FROM base b;
