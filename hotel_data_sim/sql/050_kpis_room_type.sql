-- Mismos KPIs, por tipo de habitación.
CREATE OR REPLACE TABLE gold_daily_kpis_room_type AS
WITH m AS (SELECT as_of_date AS today FROM meta),
cal AS (
  SELECT r.hotel_id, r.room_type, r.rooms, CAST(d.date AS DATE) AS stay_date
  FROM dim_room_type r CROSS JOIN dim_date d CROSS JOIN m
  WHERE CAST(d.date AS DATE) BETWEEN m.today - 520 AND m.today + 180
),
sold AS (
  SELECT hotel_id, room_type, stay_date, COUNT(*) AS rooms_sold, SUM(rate_usd) AS room_revenue_usd
  FROM fact_room_night WHERE status = 'activa' GROUP BY hotel_id, room_type, stay_date
)
SELECT c.hotel_id, c.room_type, c.stay_date, c.stay_date < m.today AS is_actual, c.rooms AS rooms_available,
       COALESCE(s.rooms_sold, 0) AS rooms_sold,
       COALESCE(s.rooms_sold, 0) * 1.0 / c.rooms AS occupancy,
       COALESCE(s.room_revenue_usd, 0) AS room_revenue_usd,
       CASE WHEN COALESCE(s.rooms_sold, 0) > 0 THEN s.room_revenue_usd / s.rooms_sold END AS adr_usd
FROM cal c CROSS JOIN m
LEFT JOIN sold s ON s.hotel_id = c.hotel_id AND s.room_type = c.room_type AND s.stay_date = c.stay_date;
