-- Databricks SQL — capa oro (referencia, NO ejecutada aquí). Reusa la lógica de ../../sql/*.sql.
-- Portabilidad respecto de DuckDB (verificar contra la documentación vigente de Databricks SQL):
--   fecha - 7 días    →  date_sub(d, 7)            | ts - INTERVAL 7 DAY  → ts - INTERVAL 7 DAYS
--   d1 - d2 (días)    →  datediff(d1, d2)
--   MEDIAN(x)         →  median(x) o percentile_approx(x, 0.5)
--   date_trunc('month', d) sin cambios;   x::INT → CAST(x AS INT)
CREATE OR REPLACE MATERIALIZED VIEW hotel.gold.daily_kpis AS
SELECT s.hotel_id, s.stay_date,
       count(*)                                   AS rooms_sold,
       sum(s.rate_usd)                            AS room_revenue_usd,
       count(*) / any_value(h.total_rooms)        AS occupancy,
       sum(s.rate_usd) / count(*)                 AS adr_usd,
       sum(s.rate_usd) / any_value(h.total_rooms) AS revpar_usd
FROM hotel.silver.fact_room_night s
JOIN hotel.gold.dim_hotel h USING (hotel_id)
WHERE s.status = 'activa'
GROUP BY s.hotel_id, s.stay_date;
