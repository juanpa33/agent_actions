-- BigQuery — oro: KPIs diarios (referencia, NO ejecutada aquí). Traducción de ../../sql/040_daily_kpis.sql.
-- Cambios de dialecto respecto de DuckDB: DATE_SUB/DATE_DIFF, TIMESTAMP_SUB, APPROX_QUANTILES para medianas.
CREATE OR REPLACE TABLE `hotel_gold.daily_kpis` AS
SELECT s.hotel_id, s.stay_date,
       COUNT(*)                                   AS rooms_sold,
       SUM(s.rate_usd)                            AS room_revenue_usd,
       COUNT(*) / ANY_VALUE(h.total_rooms)        AS occupancy,
       SAFE_DIVIDE(SUM(s.rate_usd), COUNT(*))     AS adr_usd,
       SUM(s.rate_usd) / ANY_VALUE(h.total_rooms) AS revpar_usd
FROM `hotel_silver.fact_room_night` s
JOIN `hotel_gold.dim_hotel` h USING (hotel_id)
WHERE s.status = 'activa'
GROUP BY s.hotel_id, s.stay_date;
