"""Capa GOLD: modelo dimensional y KPIs de revenue management, calculados con SQL.

El SQL vive en `sql/*.sql` (un archivo por tabla, en orden numérico) y se ejecuta con
DuckDB sobre los parquet de silver. Es SQL casi estándar: en Databricks SQL / BigQuery
cambian solo unas funciones de fecha (ver docs/ARQUITECTURA.md, sección "Portabilidad").
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from . import config as C

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    C.LAKE.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(C.GOLD_DB), read_only=read_only)


def _dimensions(con: duckdb.DuckDBPyConnection, as_of: pd.Timestamp) -> None:
    hotels = pd.DataFrame([dict(hotel_id=h.id, hotel_name=h.name, city=h.city, country=h.country,
                                currency=h.currency, pms=h.pms, total_rooms=h.total_rooms,
                                floor_usd=h.floor_usd, ceiling_usd=h.ceiling_usd) for h in C.HOTELS])
    rooms = pd.DataFrame([dict(hotel_id=h.id, room_type=r, rooms=n, base_usd=h.base_usd[r])
                          for h in C.HOTELS for r, n in h.rooms.items()])
    channels = pd.DataFrame([dict(channel=k, channel_label=v["label"], commission_pct=v["commission"],
                                  is_ota=k in C.OTA_CHANNELS) for k, v in C.CHANNELS.items()])
    lo = as_of - pd.Timedelta(days=C.HISTORY_DAYS + 400)
    hi = as_of + pd.Timedelta(days=C.FUTURE_DAYS + 60)
    dates = pd.DataFrame({"date": pd.date_range(lo, hi, freq="D")})
    dates["dow"] = dates.date.dt.dayofweek
    dates["month"] = dates.date.dt.month
    for name, df in (("dim_hotel", hotels), ("dim_room_type", rooms), ("dim_channel", channels), ("dim_date", dates)):
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
        con.unregister("_df")


def run_gold() -> list[str]:
    meta_path = C.SILVER / "meta.parquet"
    if not (C.SILVER / "reservation.parquet").exists():
        raise RuntimeError("Falta silver: corré primero `hotelsim init`.")
    as_of = pd.read_parquet(meta_path).as_of_date.iloc[0]
    con = connect()
    # vistas de silver
    for p in sorted(C.SILVER.glob("*.parquet")):
        con.execute(f"CREATE OR REPLACE VIEW silver_{p.stem} AS SELECT * FROM read_parquet('{p.as_posix()}')")
    _dimensions(con, pd.Timestamp(as_of))
    created = []
    for f in sorted(SQL_DIR.glob("*.sql")):
        sql = f.read_text(encoding="utf-8")
        con.execute(sql)
        created.append(f.stem)
    # los silver se exponen también para consultas de calidad/auditoría
    con.close()
    return created
