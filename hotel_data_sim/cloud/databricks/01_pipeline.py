# Databricks — pipeline declarativo bronce → plata (referencia de implementación).
#
# ESTADO: referencia escrita a partir de la documentación oficial; NO se ejecutó en este
# entorno (requiere un workspace de Databricks). Antes de usarla, verificá nombres y versión
# vigentes: la documentación actual agrupa Delta Live Tables bajo "Lakeflow pipelines" y
# algunas APIs/decoradores cambiaron de nombre. Ver docs/FUENTES.md.
#
# Mapeo con el simulador local (src/hotelsim):
#   ingest.py  → Auto Loader (cloudFiles): ingesta incremental de archivos nuevos, con checkpoint
#   silver.py  → parseo por fuente + expectativas (cuarentena) + apply_changes (MERGE por clave)
#   sql/*.sql  → 02_gold.sql (vistas materializadas)
#
# Zona de aterrizaje sugerida: un Volume de Unity Catalog con la misma estructura de carpetas
# que `data/landing/` del simulador (pms_opera/, pms_mews/, pms_cloudbeds/, cm_reservations/, ...).
import dlt
from pyspark.sql import functions as F

LANDING = spark.conf.get("hotel.landing", "/Volumes/hotel/raw/landing")


def autoloader(path: str, fmt: str, **opts):
    r = (spark.readStream.format("cloudFiles")
         .option("cloudFiles.format", fmt)
         .option("cloudFiles.inferColumnTypes", "true"))
    for k, v in opts.items():
        r = r.option(k, v)
    return (r.load(f"{LANDING}/{path}")
            .withColumn("_source_file", F.col("_metadata.file_path"))
            .withColumn("_ingested_at", F.current_timestamp()))


# ---------------------------------------------------------------- BRONCE (crudo, sin rechazar nada)
@dlt.table(name="bronze_pms_opera", comment="Eventos de reserva crudos del PMS tipo Opera")
def bronze_pms_opera():
    return autoloader("pms_opera", "json")          # lo malformado queda en _rescued_data


@dlt.table(name="bronze_pms_mews", comment="Eventos de reserva crudos del PMS tipo Mews")
def bronze_pms_mews():
    return autoloader("pms_mews", "json")


@dlt.table(name="bronze_pms_cloudbeds", comment="Export CSV del PMS tipo Cloudbeds")
def bronze_pms_cloudbeds():
    return autoloader("pms_cloudbeds", "csv", header="true")


@dlt.table(name="bronze_cm_reservations", comment="Reservas de OTAs vía channel manager")
def bronze_cm_reservations():
    return autoloader("cm_reservations", "json")


# ---------------------------------------------------------------- PLATA: esquema común por fuente
def _common(df, source: str):
    return df.select(
        F.lit(source).alias("source"), "hotel_id", "native_id", "event_type", "event_ts", "created_at",
        "checkin", "checkout", "room_type", "total_local", "currency", "channel", "ext_ref", "guest",
        "_ingested_at")


@dlt.view(name="v_opera_events")
def v_opera_events():
    b = dlt.read_stream("bronze_pms_opera")
    room = F.create_map([F.lit(x) for kv in {"DBLSTD": "STD", "DBLSUP": "SUP", "JRSTE": "STE"}.items() for x in kv])
    chan = F.create_map([F.lit(x) for kv in {"WEB": "DIRECT", "BKG": "BOOKING", "EXP": "EXPEDIA",
                                             "DSP": "DESPEGAR", "COR": "CORP"}.items() for x in kv])
    df = b.select(
        F.col("hotelId").alias("hotel_id"),
        F.col("reservation.resvNameId").alias("native_id"),
        F.when(F.col("eventType").endswith("CANCELLED"), "cancelled").otherwise("created").alias("event_type"),
        F.to_timestamp("eventTimestamp").alias("event_ts"),
        F.to_timestamp("reservation.createdAt").alias("created_at"),
        F.to_date("reservation.arrival").alias("checkin"), F.to_date("reservation.departure").alias("checkout"),
        room[F.col("reservation.roomCategory")].alias("room_type"),
        F.col("reservation.totalAmount").cast("double").alias("total_local"),
        F.col("reservation.currencyCode").alias("currency"),
        chan[F.col("reservation.sourceCode")].alias("channel"),
        F.regexp_replace("reservation.externalReference", r"\D", "").alias("ext_ref"),
        F.col("reservation.guestName").alias("guest"), "_ingested_at")
    return _common(df, "pms_opera")
# v_mews_events, v_cloudbeds_events y v_cm_events siguen el mismo patrón (ver silver.py: parse_mews,
# parse_cloudbeds, parse_cm para las reglas de parseo: fechas dd/mm/yyyy, coma decimal, desfase UTC).


# ---------------------------------------------------------------- PLATA: cuarentena + estado actual
RULES = {"importe_positivo": "total_local > 0", "fechas_coherentes": "checkout > checkin",
         "con_clave": "native_id IS NOT NULL"}


@dlt.table(name="silver_events_valid")
@dlt.expect_all_or_drop(RULES)                       # los que violan una regla se descartan de acá…
def silver_events_valid():
    return dlt.read_stream("v_opera_events")         # (unir el resto de fuentes con unionByName)


@dlt.table(name="silver_quarantine", comment="…y se guardan acá para auditarlos")
def silver_quarantine():
    bad = " OR ".join(f"NOT ({r})" for r in RULES.values())
    return dlt.read_stream("v_opera_events").where(bad)


dlt.create_streaming_table("silver_reservation_pms")
dlt.apply_changes(                                     # equivalente a MERGE: el último evento gana
    target="silver_reservation_pms", source="silver_events_valid",
    keys=["hotel_id", "native_id"], sequence_by=F.col("event_ts"), stored_as_scd_type=1)

# El cruce PMS ↔ channel manager (referencia normalizada + coincidencia difusa por hotel, habitación,
# fechas, canal, importe USD y huésped) es un join batch sobre ambas tablas: ver silver.build_reservations.
