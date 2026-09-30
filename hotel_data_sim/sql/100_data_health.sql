-- Salud y frescura de datos (para el tablero y para que el asistente sepa cuán "en vivo" está todo).
CREATE OR REPLACE TABLE gold_source_health AS SELECT * FROM silver_source_health;
CREATE OR REPLACE TABLE gold_data_quality AS SELECT * FROM silver_dq;
