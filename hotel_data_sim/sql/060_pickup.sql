-- Pickup y ritmo (pace) de reservas para los próximos 120 días, por hotel y tipo de habitación.
-- otb_* = noches-habitación "on the books" en cada momento de referencia, reconstruidas con
-- created_at / cancelled_at. STLY = "same time last year" (364 días atrás: mismo día de la semana).
CREATE OR REPLACE TABLE gold_pickup AS
WITH m AS (SELECT as_of_ts AS now_ts, as_of_date AS today FROM meta),
cur AS (
  SELECT f.hotel_id, f.room_type, f.stay_date,
         SUM(CASE WHEN f.created_at <= m.now_ts
                   AND (f.cancelled_at IS NULL OR f.cancelled_at > m.now_ts) THEN 1 ELSE 0 END) AS otb_now,
         SUM(CASE WHEN f.created_at <= m.now_ts - INTERVAL 7 DAY
                   AND (f.cancelled_at IS NULL OR f.cancelled_at > m.now_ts - INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS otb_7d_ago,
         SUM(CASE WHEN f.created_at <= m.now_ts - INTERVAL 30 DAY
                   AND (f.cancelled_at IS NULL OR f.cancelled_at > m.now_ts - INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS otb_30d_ago,
         SUM(CASE WHEN f.status = 'activa' THEN f.rate_usd ELSE 0 END) AS otb_revenue_usd
  FROM fact_room_night f CROSS JOIN m
  WHERE f.stay_date BETWEEN m.today AND m.today + 120
  GROUP BY f.hotel_id, f.room_type, f.stay_date
),
ly AS (
  SELECT f.hotel_id, f.room_type, f.stay_date + 364 AS stay_date,
         SUM(CASE WHEN f.created_at <= m.now_ts - INTERVAL 364 DAY
                   AND (f.cancelled_at IS NULL OR f.cancelled_at > m.now_ts - INTERVAL 364 DAY) THEN 1 ELSE 0 END) AS otb_stly,
         SUM(CASE WHEN f.status = 'activa' THEN 1 ELSE 0 END) AS final_ly
  FROM fact_room_night f CROSS JOIN m
  WHERE f.stay_date BETWEEN m.today - 364 AND m.today + 120 - 364
  GROUP BY f.hotel_id, f.room_type, f.stay_date
),
cal AS (
  SELECT r.hotel_id, r.room_type, r.rooms, CAST(d.date AS DATE) AS stay_date
  FROM dim_room_type r CROSS JOIN dim_date d CROSS JOIN m
  WHERE CAST(d.date AS DATE) BETWEEN m.today AND m.today + 120
),
bar AS (
  SELECT hotel_id, room_type, CAST(stay_date AS DATE) AS stay_date,
         MAX(CASE WHEN channel = 'DIRECT' THEN rate_usd END) AS bar_direct_usd,
         MAX(CASE WHEN channel = 'DIRECT' THEN available END) AS available_rooms
  FROM silver_ari GROUP BY hotel_id, room_type, CAST(stay_date AS DATE)
)
SELECT c.hotel_id, c.room_type, c.stay_date,
       c.stay_date - m.today AS days_out, c.rooms AS capacity,
       COALESCE(u.otb_now, 0) AS otb_now,
       COALESCE(u.otb_7d_ago, 0) AS otb_7d_ago,
       COALESCE(u.otb_30d_ago, 0) AS otb_30d_ago,
       COALESCE(u.otb_now, 0) - COALESCE(u.otb_7d_ago, 0) AS pickup_7d,
       COALESCE(u.otb_now, 0) - COALESCE(u.otb_30d_ago, 0) AS pickup_30d,
       COALESCE(l.otb_stly, 0) AS otb_stly,
       COALESCE(l.final_ly, 0) AS final_ly,
       CASE WHEN COALESCE(u.otb_now, 0) > 0 THEN u.otb_revenue_usd / u.otb_now END AS otb_adr_usd,
       b.bar_direct_usd, b.available_rooms,
       e.event_name, COALESCE(e.impact_level, 0) AS event_impact
FROM cal c CROSS JOIN m
LEFT JOIN cur u ON u.hotel_id = c.hotel_id AND u.room_type = c.room_type AND u.stay_date = c.stay_date
LEFT JOIN ly  l ON l.hotel_id = c.hotel_id AND l.room_type = c.room_type AND l.stay_date = c.stay_date
LEFT JOIN bar b ON b.hotel_id = c.hotel_id AND b.room_type = c.room_type AND b.stay_date = c.stay_date
LEFT JOIN gold_date_events e ON e.hotel_id = c.hotel_id AND e.stay_date = c.stay_date;
