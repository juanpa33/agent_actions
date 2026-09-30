-- Una fila por reserva unificada (PMS + channel manager ya cruzados en silver).
CREATE OR REPLACE TABLE fact_reservation AS
SELECT res_key, hotel_id, room_type, channel,
       CAST(checkin AS DATE) AS checkin, CAST(checkout AS DATE) AS checkout, nights,
       CAST(created_at AS TIMESTAMP) AS created_at, CAST(cancelled_at AS TIMESTAMP) AS cancelled_at,
       status, total_local, currency, total_usd, commission_pct, net_usd,
       match_status, in_pms, in_cm
FROM silver_reservation;
