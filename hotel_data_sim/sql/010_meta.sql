-- Reloj de la simulación ("ahora" de los datos) y metadatos de corrida.
CREATE OR REPLACE TABLE meta AS
SELECT CAST(as_of_ts AS TIMESTAMP) AS as_of_ts, CAST(as_of_date AS DATE) AS as_of_date
FROM silver_meta;
