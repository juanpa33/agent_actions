"""Herramientas que usan el asistente (solo lectura) y el agente de pricing (lectura + PROPONER).

Cada herramienta devuelve JSON serializable y acotado (pocas filas) para no inundar el
contexto del modelo. Ninguna herramienta puede aprobar ni publicar precios.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import duckdb
import pandas as pd

from . import channels, config as C, pricing
from .gold import connect

MAX_ROWS = 60
ALLOWED_TABLES = {
    "gold_daily_kpis", "gold_daily_kpis_room_type", "gold_pickup", "gold_compset", "gold_parity",
    "gold_channel_mix", "gold_source_health", "gold_data_quality", "gold_date_events",
    "dim_hotel", "dim_room_type", "dim_channel", "meta",
}
FORBIDDEN = re.compile(r"\b(attach|copy|export|install|load|pragma|call|create|insert|update|delete|drop|alter|"
                       r"read_parquet|read_csv|read_json|glob|set|use|import|silver_\w+|fact_\w+)\b", re.I)


def _df(df: pd.DataFrame, n: int = MAX_ROWS) -> list[dict]:
    df = df.head(n).copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            has_time = bool((df[c].dropna() != df[c].dropna().dt.normalize()).any())
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M" if has_time else "%Y-%m-%d")
    return json.loads(df.to_json(orient="records", double_precision=3))


def _sql(con: duckdb.DuckDBPyConnection, q: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(q, params or []).df()


def get_context() -> dict:
    con = connect(read_only=True)
    meta = _sql(con, "SELECT * FROM meta")
    hotels = _sql(con, "SELECT hotel_id, hotel_name, city, country, currency, pms, total_rooms FROM dim_hotel")
    con.close()
    return dict(as_of=str(meta.as_of_ts.iloc[0]), hotels=_df(hotels),
                room_types=C.ROOM_TYPES, channels=list(C.CHANNELS))


def kpis(hotel_id: str | None = None, date_from: str | None = None, date_to: str | None = None,
         group_by: str = "day") -> dict:
    """KPIs de ocupación, ADR y RevPAR (USD). group_by: day|week|month. Fechas pasadas = reales, futuras = on the books."""
    if group_by not in {"day", "week", "month"}:
        return dict(error="group_by debe ser day, week o month")
    con = connect(read_only=True)
    where, params = ["1=1"], []
    if hotel_id:
        where.append("hotel_id = ?"); params.append(hotel_id)
    if date_from:
        where.append("stay_date >= CAST(? AS DATE)"); params.append(date_from)
    if date_to:
        where.append("stay_date <= CAST(? AS DATE)"); params.append(date_to)
    bucket = "stay_date" if group_by == "day" else f"CAST(date_trunc('{group_by}', stay_date) AS DATE)"
    df = _sql(con, f"""
        SELECT hotel_id, {bucket} AS period, MIN(is_actual) AS is_actual_all,
               SUM(rooms_sold) AS rooms_sold, SUM(rooms_available) AS rooms_available,
               SUM(rooms_sold) * 1.0 / SUM(rooms_available) AS occupancy,
               SUM(room_revenue_usd) / NULLIF(SUM(rooms_sold), 0) AS adr_usd,
               SUM(room_revenue_usd) / SUM(rooms_available) AS revpar_usd,
               SUM(room_revenue_usd) AS room_revenue_usd, SUM(cancelled_room_nights) AS cancelled_room_nights
        FROM gold_daily_kpis WHERE {' AND '.join(where)}
        GROUP BY hotel_id, {bucket} ORDER BY hotel_id, period""", params)
    con.close()
    return dict(rows=_df(df), note="fechas futuras = reservas on-the-books, no ocupación final")


def pickup(hotel_id: str | None = None, days_ahead: int = 30) -> dict:
    """Ritmo de reservas de los próximos N días vs. mismo momento del año pasado (STLY), por hotel."""
    con = connect(read_only=True)
    params: list[Any] = [int(days_ahead)]
    extra = ""
    if hotel_id:
        extra = "AND hotel_id = ?"; params.append(hotel_id)
    df = _sql(con, f"""
        SELECT hotel_id, SUM(otb_now) AS otb_now, SUM(otb_stly) AS otb_stly, SUM(final_ly) AS final_ly,
               SUM(pickup_7d) AS pickup_7d, SUM(pickup_30d) AS pickup_30d, SUM(capacity) AS capacity,
               SUM(otb_now) * 1.0 / SUM(capacity) AS otb_occupancy,
               SUM(otb_now) * 1.0 / NULLIF(SUM(otb_stly), 0) AS pace_vs_stly
        FROM gold_pickup WHERE days_out BETWEEN 0 AND ? {extra} GROUP BY hotel_id ORDER BY hotel_id""", params)
    top = _sql(con, f"""
        SELECT hotel_id, stay_date, SUM(otb_now) AS otb_now, SUM(otb_stly) AS otb_stly, SUM(capacity) AS capacity,
               SUM(otb_now) * 1.0 / SUM(capacity) AS otb_occ, MAX(event_name) AS event
        FROM gold_pickup WHERE days_out BETWEEN 0 AND ? {extra}
        GROUP BY hotel_id, stay_date ORDER BY otb_occ DESC LIMIT 8""", params)
    con.close()
    return dict(resumen=_df(df), fechas_mas_cargadas=_df(top))


def compset(hotel_id: str | None = None, days_ahead: int = 30) -> dict:
    """Posición de precio (tipo Standard) vs. mediana de la competencia; rate_index > 1 = más caro que el mercado."""
    con = connect(read_only=True)
    params: list[Any] = [int(days_ahead)]
    extra = ""
    if hotel_id:
        extra = "AND hotel_id = ?"; params.append(hotel_id)
    df = _sql(con, f"""
        SELECT hotel_id, AVG(rate_index) AS rate_index_promedio, MIN(rate_index) AS rate_index_min,
               MAX(rate_index) AS rate_index_max, AVG(our_bar_usd) AS nuestra_bar_usd, AVG(comp_median_usd) AS mediana_comp_usd
        FROM gold_compset WHERE days_out BETWEEN 0 AND ? {extra} GROUP BY hotel_id ORDER BY hotel_id""", params)
    out = _sql(con, f"""
        SELECT hotel_id, stay_date, our_bar_usd, comp_median_usd, rate_index, event_name
        FROM gold_compset WHERE days_out BETWEEN 0 AND ? {extra} ORDER BY ABS(rate_index - 1) DESC LIMIT 8""", params)
    con.close()
    return dict(resumen=_df(df), fechas_mas_desalineadas=_df(out))


def parity_alerts(hotel_id: str | None = None, limit: int = 15) -> dict:
    """Fechas donde una OTA publica una tarifa distinta del canal directo (> 1%)."""
    con = connect(read_only=True)
    params: list[Any] = []
    extra = ""
    if hotel_id:
        extra = "AND hotel_id = ?"; params.append(hotel_id)
    tot = _sql(con, f"SELECT hotel_id, channel, COUNT(*) AS fechas, SUM(breach::INT) AS con_fuga FROM gold_parity WHERE 1=1 {extra} GROUP BY 1, 2 ORDER BY 1, 2", params)
    det = _sql(con, f"""SELECT hotel_id, room_type, stay_date, channel, direct_local, channel_local, currency, diff_pct, breach_type
        FROM gold_parity WHERE breach {extra} ORDER BY stay_date LIMIT {int(limit)}""", params)
    con.close()
    return dict(resumen=_df(tot), detalle=_df(det))


def channel_mix(hotel_id: str | None = None, months: int = 3) -> dict:
    """Mezcla de canales: noches, participación, ADR bruto/neto de comisión (últimos N meses cerrados)."""
    con = connect(read_only=True)
    params: list[Any] = [int(months)]
    extra = ""
    if hotel_id:
        extra = "AND hotel_id = ?"; params.append(hotel_id)
    df = _sql(con, f"""
        SELECT hotel_id, channel, SUM(room_nights) AS room_nights, SUM(gross_usd) AS gross_usd, SUM(net_usd) AS net_usd,
               SUM(gross_usd) / SUM(room_nights) AS adr_bruto, SUM(net_usd) / SUM(room_nights) AS adr_neto
        FROM gold_channel_mix, meta WHERE month >= CAST(date_trunc('month', meta.as_of_date) AS DATE) - 31 * ? {extra}
        GROUP BY hotel_id, channel ORDER BY hotel_id, net_usd DESC""", params)
    con.close()
    return dict(rows=_df(df))


def data_freshness() -> dict:
    """Frescura de cada fuente y métricas de calidad de datos (cuarentena, duplicados, cruces)."""
    con = connect(read_only=True)
    src = _sql(con, "SELECT * FROM gold_source_health ORDER BY source, hotel_id")
    dq = _sql(con, "SELECT * FROM gold_data_quality ORDER BY \"check\"")
    meta = _sql(con, "SELECT * FROM meta")
    con.close()
    return dict(ahora_simulado=str(meta.as_of_ts.iloc[0]), fuentes=_df(src), calidad=_df(dq, 40))


def run_sql(query: str) -> dict:
    """SELECT de solo lectura sobre tablas gold/dim (máx. 60 filas). Para preguntas que las otras herramientas no cubren."""
    q = query.strip().rstrip(";")
    if ";" in q or not re.match(r"^(with|select)\b", q, re.I):
        return dict(error="Solo se permite una sentencia SELECT/WITH.")
    if FORBIDDEN.search(q):
        return dict(error="La consulta usa palabras o tablas no permitidas. Tablas disponibles: " + ", ".join(sorted(ALLOWED_TABLES)))
    con = connect(read_only=True)
    try:
        df = con.execute(f"SELECT * FROM ({q}) LIMIT {MAX_ROWS}").df()
    except duckdb.Error as e:
        return dict(error=f"Error SQL: {str(e)[:300]}")
    finally:
        con.close()
    return dict(rows=_df(df), note=f"máx. {MAX_ROWS} filas")


def recommend_prices(hotel_id: str | None = None, horizon_days: int = 30, min_abs_change_pct: float = 0.0, limit: int = 25) -> dict:
    """Recomendaciones de precio (BAR directa, USD) del motor de reglas, ordenadas por impacto. NO las aplica."""
    rec = pricing.recommendations(horizon_days, hotel_id)
    rec = rec[rec.change_pct.abs() >= min_abs_change_pct]
    rec = rec.reindex(rec.change_pct.abs().sort_values(ascending=False).index).head(int(limit))
    rows = [dict(hotel_id=r.hotel_id, room_type=r.room_type, stay_date=r.stay_date.strftime("%Y-%m-%d"),
                 current_usd=float(r.bar_usd), new_usd=float(r.rec_bar_usd), change_pct=round(float(r.change_pct), 3),
                 proj_occ=round(float(r.proj_occ), 2), confidence=r.confidence, reasons=r.reasons)
            for r in rec.itertuples()]
    return dict(recommendations=rows, total_changes_available=int(len(pricing.recommendations(horizon_days, hotel_id))))


def propose_price_changes(changes: list[dict]) -> dict:
    """Envía cambios a la cola de APROBACIÓN HUMANA. No publica nada. Cada cambio: hotel_id, room_type, stay_date, current_usd, new_usd, reasons."""
    return channels.propose(changes, proposed_by="agente")


def list_pending() -> dict:
    return dict(pendientes=channels.list_queue("propuesto"))


READ_TOOLS: dict[str, Callable[..., dict]] = {
    "kpis": kpis, "pickup": pickup, "compset": compset, "parity_alerts": parity_alerts,
    "channel_mix": channel_mix, "data_freshness": data_freshness, "run_sql": run_sql,
}
AGENT_TOOLS: dict[str, Callable[..., dict]] = {**READ_TOOLS, "recommend_prices": recommend_prices,
                                               "propose_price_changes": propose_price_changes,
                                               "list_pending": list_pending}

_HOTEL = {"type": "string", "description": "ID de hotel: MDZ01 (Mendoza), CTG01 (Cartagena), MEX01 (CDMX). Omitir = todos."}
TOOL_SCHEMAS: dict[str, dict] = {
    "kpis": dict(description=kpis.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, date_from={"type": "string", "description": "YYYY-MM-DD"},
        date_to={"type": "string", "description": "YYYY-MM-DD"},
        group_by={"type": "string", "enum": ["day", "week", "month"]}), additionalProperties=False)),
    "pickup": dict(description=pickup.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, days_ahead={"type": "integer", "description": "Horizonte en días (1-120)"}), additionalProperties=False)),
    "compset": dict(description=compset.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, days_ahead={"type": "integer"}), additionalProperties=False)),
    "parity_alerts": dict(description=parity_alerts.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, limit={"type": "integer"}), additionalProperties=False)),
    "channel_mix": dict(description=channel_mix.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, months={"type": "integer"}), additionalProperties=False)),
    "data_freshness": dict(description=data_freshness.__doc__, input_schema=dict(type="object", properties={}, additionalProperties=False)),
    "run_sql": dict(description=run_sql.__doc__ + " Tablas: " + ", ".join(sorted(ALLOWED_TABLES)) +
                    ". Columnas clave: gold_daily_kpis(hotel_id, stay_date, is_actual, rooms_sold, occupancy, adr_usd, revpar_usd, room_revenue_usd), "
                    "gold_pickup(hotel_id, room_type, stay_date, days_out, otb_now, otb_stly, final_ly, pickup_7d, bar_direct_usd, event_name).",
                    input_schema=dict(type="object", properties=dict(query={"type": "string"}), required=["query"], additionalProperties=False)),
    "recommend_prices": dict(description=recommend_prices.__doc__, input_schema=dict(type="object", properties=dict(
        hotel_id=_HOTEL, horizon_days={"type": "integer"}, min_abs_change_pct={"type": "number"},
        limit={"type": "integer"}), additionalProperties=False)),
    "propose_price_changes": dict(description=propose_price_changes.__doc__, input_schema=dict(type="object", properties=dict(
        changes=dict(type="array", items=dict(type="object", properties=dict(
            hotel_id={"type": "string"}, room_type={"type": "string", "enum": C.ROOM_TYPES},
            stay_date={"type": "string"}, current_usd={"type": "number"}, new_usd={"type": "number"},
            reasons={"type": "array", "items": {"type": "string"}}),
            required=["hotel_id", "room_type", "stay_date", "current_usd", "new_usd"], additionalProperties=False))),
        required=["changes"], additionalProperties=False)),
    "list_pending": dict(description="Lista las propuestas de precio pendientes de aprobación humana.",
                         input_schema=dict(type="object", properties={}, additionalProperties=False)),
}


def execute(name: str, args: dict, registry: dict[str, Callable[..., dict]]) -> dict:
    fn = registry.get(name)
    if fn is None:
        return dict(error=f"herramienta no disponible: {name}")
    try:
        return fn(**args)
    except TypeError as e:
        return dict(error=f"argumentos inválidos: {e}")
    except Exception as e:   # un error de herramienta no debe tumbar la conversación
        return dict(error=f"{type(e).__name__}: {str(e)[:300]}")
