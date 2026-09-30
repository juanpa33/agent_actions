# Fuentes y qué se verificó

Regla de este documento: cada afirmación sobre un producto externo tiene enlace. Lo que **no** pude
verificar está marcado como *supuesto* o *definición de trabajo*. Las búsquedas son de septiembre de 2026;
las APIs y nombres comerciales cambian, revisá la página vigente antes de construir sobre ellas.

## 1. Sistemas que usan los hoteles (qué se modela y por qué)

| Tipo | Sistema | Qué aporta al producto de datos | Fuente |
|---|---|---|---|
| PMS | **Oracle OPERA Cloud** (vía OHIP) | Plataforma de integración por API; las APIs de distribución intercambian disponibilidad, tarifas, inventario y reservas con canales, RMS y CRS | [Oracle OHIP](https://www.oracle.com/hospitality/integration-platform/) · [AltexSoft: integrar con OPERA](https://www.altexsoft.com/blog/opera-pms-integration/) |
| PMS | **Mews** | *Connector API* (datos y servicios) y *Channel Manager API* (ARI hacia el channel manager, reservas de vuelta) | [Mews Open API](https://docs.mews.com/) · [Channel Manager API](https://docs.mews.com/channel-manager-api) |
| PMS | **Cloudbeds** | API con reservas, huéspedes, tarifas, disponibilidad y finanzas; webhooks | [Cloudbeds API](https://developers.cloudbeds.com/docs/about-cloudbeds-api) · [sitio](https://www.cloudbeds.com/cloudbeds-api/) |
| Channel manager | **SiteMinder** (SiteConnect) | API *push* de dos vías: empuja ARI, recibe reservas nuevas/modificadas/canceladas | [SiteMinder developer](https://developer.siteminder.com/get-started/siteminder-apis) · [SiteConnect](https://developer.siteminder.com/siteminder-apis/channels/siteconnect/api-reference) |
| Channel manager LATAM | **Omnibees** | Distribución y channel manager con fuerte presencia en LATAM; integra con +60 PMS/RMS (dato de la propia empresa) | [Omnibees channel manager](https://omnibees.com/en/solucao/channel-manager-2/) · [nota Shiji](https://www.shijigroup.com/press-news/omnibees-and-shiji-horizon-distribution-partner-to-expand-global-connectivity-in-latin-american-hospitality) |
| OTA | **Booking.com** (Connectivity APIs) | *Rates & Availability API* para cargar inventario, precios y restricciones; exige certificación | [Connectivity docs](https://developers.booking.com/connectivity/docs) · [R&A API](https://developers.booking.com/connectivity/docs/ari) · [Going live](https://developers.booking.com/connectivity/docs/going_live) · [Requisitos para ser partner](https://connectivity.booking.com/s/article/Requirements-for-becoming-a-Booking-com-Connectivity-Partner?language=en_US) |

Hechos de la documentación que condicionan el diseño:

- **Booking.com**: el límite general es de **10.000 llamadas por minuto** por proveedor (hay endpoints con límites menores, p. ej. `/xml/reservationssummary` 700/min), y se espera cargar **al menos un año** de tarifas y disponibilidad por propiedad ([FAQ R&A](https://developers.booking.com/connectivity/docs/con-faq-rates-availability)). Publicar precios directamente requiere ser *Connectivity Partner* certificado: por eso el agente de este MVP **no** se conecta a Booking, usa un conector simulado (`channels.MockOTAConnector`) y en producción se publica a través del channel manager del hotel o de un partner certificado.
- **Mews / SiteMinder**: ambos separan el flujo de ARI (del hotel hacia los canales) del de reservas (de los canales hacia el hotel). El simulador reproduce esa asimetría: las reservas de OTAs aparecen primero en el channel manager y **bajan al PMS con minutos (a veces días) de retraso** (`sources._emit_ts`).

*Supuesto*: los formatos crudos del simulador (`pms_opera`, `pms_cloudbeds`, `pms_mews`, `cm_reservations`) son **imitaciones genéricas** del estilo de cada tipo de sistema, no los esquemas oficiales. No los usé como referencia de campo a campo de ninguna API. Con un cliente real se reemplazan los adaptadores de `silver.py`.

## 2. Plataformas de datos

| Tema | Qué dice la documentación | Fuente |
|---|---|---|
| Arquitectura medallion | Capas bronce (crudo) → plata (validado) → oro (enriquecido/para negocio); mejora progresiva de calidad | [Databricks](https://docs.databricks.com/aws/en/lakehouse/medallion) · [Microsoft Learn](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion) |
| Ingesta incremental | **Auto Loader** (`cloudFiles`) procesa archivos nuevos a medida que llegan, con *exactly-once* vía checkpoint; Databricks recomienda usarlo dentro de pipelines declarativos (*Lakeflow pipelines*, sucesor de Delta Live Tables) | [Auto Loader](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/) · [producción](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/production) |
| Streaming en GCP | **BigQuery subscription**: Pub/Sub escribe los mensajes directo en una tabla de BigQuery (Storage Write API), sin pipeline propio; entrega **al menos una vez**; si hace falta *exactly-once* o transformaciones, usar Dataflow | [BigQuery subscriptions](https://docs.cloud.google.com/pubsub/docs/bigquery) · [Plantilla Dataflow Pub/Sub→BQ](https://docs.cloud.google.com/dataflow/docs/guides/templates/provided/pubsub-to-bigquery) · [Tutorial](https://docs.cloud.google.com/dataflow/docs/tutorials/dataflow-stream-to-bigquery) |

El código de `cloud/` **no se ejecutó** en este entorno (no hay workspace de Databricks ni proyecto de GCP): es
una traducción escrita desde esa documentación. Lo que sí corre y está testeado es el equivalente local
(`ingest.py`, `silver.py`, `sql/`).

## 3. Definiciones de KPI

- **Ocupación** = noches-habitación vendidas ÷ disponibles. **ADR** = ingreso de habitaciones ÷ habitaciones vendidas. **RevPAR** = ingreso de habitaciones ÷ disponibles = ADR × ocupación. Fuentes: [Mews: RevPAR vs ADR](https://www.mews.com/en/blog/revpar-vs-adr) · [AltexSoft](https://www.altexsoft.com/blog/revpar-occupancy-rate-adr-hotel-metrics/) · [HospitalityNet](https://www.hospitalitynet.org/news/4126420.html). El test `test_kpis_coherentes` verifica RevPAR = ADR × ocupación.
- **Pickup, pace, OTB, STLY**: **no encontré una fuente citable** con definiciones formales en esta búsqueda. Son *definiciones de trabajo* del simulador, de uso corriente en revenue management: OTB = noches reservadas hoy para una fecha futura (*on the books*); pickup = OTB hoy − OTB a N días atrás; STLY = mismo momento del año pasado (se alinea 364 días atrás para conservar el día de la semana); pace = OTB ÷ OTB STLY. Validalas con el revenue manager del cliente.
- **Benchmarking de mercado (STR)**: los informes STR comparan ocupación, ADR y RevPAR contra un compset ([ejemplo divulgativo](https://chekin.com/en/blog/str-report-for-hotels/)). El MVP reemplaza eso con un *rate shopper* simulado; en producción se integra el proveedor que el hotel ya contrate.

## 4. Lo que es inventado (y se declara en el tablero)

Hoteles, habitaciones, tarifas, tipos de cambio, eventos, elasticidades, cancelaciones, comisiones (15/16/14 %) y
volúmenes son sintéticos y **no representan ningún hotel ni el mercado**. Las comisiones y la participación por
canal son supuestos de trabajo, no datos de las OTAs.
