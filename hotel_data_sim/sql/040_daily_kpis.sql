-- KPIs diarios por hotel: ocupación, ADR, RevPAR. Fechas pasadas = reales; futuras = "on the books".
CREATE OR REPLACE TABLE gold_daily_kpis AS
WITH m AS (SELECT as_of_date AS today FROM meta),
cal AS (
  SELECT h.hotel_id, h.total_rooms, CAST(d.date AS DATE) AS stay_date
  FROM dim_hotel h CROSS JOIN dim_date d CROSS JOIN m
  WHERE CAST(d.date AS DATE) BETWEEN m.today - 520 AND m.today + 180
),
sold AS (
  SELECT hotel_id, stay_date, COUNT(*) AS rooms_sold,
         SUM(rate_usd) AS room_revenue_usd, SUM(net_rate_usd) AS net_revenue_usd
  FROM fact_room_night WHERE status = 'activa' GROUP BY hotel_id, stay_date
),
canc AS (
  SELECT hotel_id, stay_date, COUNT(*) AS cancelled_room_nights
  FROM fact_room_night WHERE status = 'cancelada' GROUP BY hotel_id, stay_date
),
pos AS (
  SELECT hotel_id, CAST(business_date AS DATE) AS stay_date, SUM(revenue_usd) AS fnb_revenue_usd
  FROM silver_pos GROUP BY hotel_id, CAST(business_date AS DATE)
)
SELECT c.hotel_id, c.stay_date, c.stay_date < m.today AS is_actual,
       c.total_rooms AS rooms_available,
       COALESCE(s.rooms_sold, 0) AS rooms_sold,
       COALESCE(s.rooms_sold, 0) * 1.0 / c.total_rooms AS occupancy,
       COALESCE(s.room_revenue_usd, 0) AS room_revenue_usd,
       COALESCE(s.net_revenue_usd, 0) AS net_revenue_usd,
       CASE WHEN COALESCE(s.rooms_sold, 0) > 0 THEN s.room_revenue_usd / s.rooms_sold END AS adr_usd,
       COALESCE(s.room_revenue_usd, 0) / c.total_rooms AS revpar_usd,
       COALESCE(k.cancelled_room_nights, 0) AS cancelled_room_nights,
       p.fnb_revenue_usd,
       (COALESCE(s.room_revenue_usd, 0) + COALESCE(p.fnb_revenue_usd, 0)) / c.total_rooms AS trevpar_usd
FROM cal c CROSS JOIN m
LEFT JOIN sold s ON s.hotel_id = c.hotel_id AND s.stay_date = c.stay_date
LEFT JOIN canc k ON k.hotel_id = c.hotel_id AND k.stay_date = c.stay_date
LEFT JOIN pos  p ON p.hotel_id = c.hotel_id AND p.stay_date = c.stay_date;
