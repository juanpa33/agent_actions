-- Una fila por noche-habitación vendida (explota cada reserva por noche).
CREATE OR REPLACE TABLE fact_room_night AS
SELECT r.res_key, r.hotel_id, r.room_type, r.channel,
       CAST(d.date AS DATE) AS stay_date,
       r.created_at, r.cancelled_at, r.status,
       r.total_usd / r.nights AS rate_usd,
       r.net_usd   / r.nights AS net_rate_usd
FROM fact_reservation r
JOIN dim_date d ON d.date >= r.checkin AND d.date < r.checkout;
