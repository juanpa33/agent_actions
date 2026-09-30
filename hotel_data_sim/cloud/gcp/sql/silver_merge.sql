-- BigQuery — plata: estado actual por reserva desde el bronce (referencia, NO ejecutada aquí).
-- Equivale a silver.collapse() del simulador: MERGE por clave, el evento más reciente gana,
-- deduplicando reenvíos (Pub/Sub → BigQuery entrega al menos una vez).
-- Se programa como consulta programada (o Dataform) cada pocos minutos.
MERGE `hotel_silver.reservation_pms` T
USING (
  SELECT * EXCEPT (rn) FROM (
    SELECT
      JSON_VALUE(attributes, '$.hotel_id')                         AS hotel_id,
      JSON_VALUE(data, '$.reservation.resvNameId')                 AS native_id,
      IF(JSON_VALUE(data, '$.eventType') LIKE '%CANCELLED', 'cancelled', 'created') AS event_type,
      TIMESTAMP(JSON_VALUE(data, '$.eventTimestamp'))              AS event_ts,
      TIMESTAMP(JSON_VALUE(data, '$.reservation.createdAt'))       AS created_at,
      DATE(JSON_VALUE(data, '$.reservation.arrival'))              AS checkin,
      DATE(JSON_VALUE(data, '$.reservation.departure'))            AS checkout,
      CAST(JSON_VALUE(data, '$.reservation.totalAmount') AS FLOAT64) AS total_local,
      JSON_VALUE(data, '$.reservation.currencyCode')               AS currency,
      ROW_NUMBER() OVER (PARTITION BY JSON_VALUE(attributes, '$.hotel_id'),
                                      JSON_VALUE(data, '$.reservation.resvNameId')
                         ORDER BY TIMESTAMP(JSON_VALUE(data, '$.eventTimestamp')) DESC, message_id DESC) AS rn
    FROM `hotel_bronze.reservation_events`
    WHERE JSON_VALUE(attributes, '$.source') = 'pms_opera'
      AND publish_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY)   -- ventana incremental
  ) WHERE rn = 1
) S
ON T.hotel_id = S.hotel_id AND T.native_id = S.native_id
WHEN MATCHED AND S.event_ts > T.event_ts THEN UPDATE SET
  event_type = S.event_type, event_ts = S.event_ts, total_local = S.total_local
WHEN NOT MATCHED THEN INSERT ROW;
