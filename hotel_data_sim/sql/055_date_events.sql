-- Evento (si hay) que cae en cada fecha de estadía.
CREATE OR REPLACE TABLE gold_date_events AS
SELECT e.hotel_id, CAST(d.date AS DATE) AS stay_date,
       MIN(e."event") AS event_name,
       MAX(CASE e.expected_impact WHEN 'alto' THEN 3 WHEN 'medio' THEN 2 ELSE 1 END) AS impact_level
FROM silver_events e
JOIN dim_date d ON d.date >= e.start_date AND d.date <= e.end_date
GROUP BY e.hotel_id, CAST(d.date AS DATE);
