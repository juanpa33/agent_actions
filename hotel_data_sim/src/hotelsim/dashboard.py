"""Tablero de reporting: HTML autocontenido (gráficos SVG propios, sin dependencias externas).

`build_html(live=True)` lo arma para `hotelsim serve` (chat, aprobación y simulación en vivo).
`build_html(live=False)` genera un archivo estático para compartir (sin chat ni acciones).
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from . import channels, config as C, pricing
from .gold import connect

TEMPLATE_FILE = "dashboard.html"


def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M" if (df[c].dropna().dt.hour != 0).any() else "%Y-%m-%d")
    return json.loads(df.to_json(orient="records", double_precision=4))


def collect(rec_limit: int = 12) -> dict:
    con = connect(read_only=True)
    q = lambda sql, p=None: con.execute(sql, p or []).df()  # noqa: E731
    meta = q("SELECT * FROM meta").iloc[0]
    today = pd.Timestamp(meta.as_of_date)
    hotels = q("SELECT hotel_id, hotel_name, city, currency, pms, total_rooms FROM dim_hotel ORDER BY hotel_id")
    daily = q("""
        SELECT hotel_id, stay_date, is_actual, occupancy, adr_usd, revpar_usd, rooms_sold, room_revenue_usd
        FROM gold_daily_kpis WHERE stay_date BETWEEN CAST(? AS DATE) - 75 AND CAST(? AS DATE) + 60
        ORDER BY hotel_id, stay_date""", [today.date(), today.date()])
    roll = q("""
        SELECT hotel_id,
          SUM(CASE WHEN stay_date >= CAST(? AS DATE) - 30 THEN room_revenue_usd END) AS rev_30,
          SUM(CASE WHEN stay_date >= CAST(? AS DATE) - 30 THEN rooms_sold END) AS sold_30,
          SUM(CASE WHEN stay_date >= CAST(? AS DATE) - 30 THEN rooms_available END) AS avail_30,
          SUM(CASE WHEN stay_date < CAST(? AS DATE) - 30 THEN room_revenue_usd END) AS rev_prev,
          SUM(CASE WHEN stay_date < CAST(? AS DATE) - 30 THEN rooms_sold END) AS sold_prev,
          SUM(CASE WHEN stay_date < CAST(? AS DATE) - 30 THEN rooms_available END) AS avail_prev
        FROM gold_daily_kpis WHERE stay_date BETWEEN CAST(? AS DATE) - 60 AND CAST(? AS DATE) - 1
        GROUP BY hotel_id ORDER BY hotel_id""", [today.date()] * 8)
    monthly = q("""
        SELECT hotel_id, strftime(stay_date, '%Y-%m') AS month, SUM(rooms_sold) AS sold, SUM(rooms_available) AS avail,
               SUM(room_revenue_usd) AS rev, SUM(cancelled_room_nights) AS cancelled, MAX((NOT is_actual)::INT) AS has_future
        FROM gold_daily_kpis WHERE stay_date BETWEEN CAST(? AS DATE) - 400 AND CAST(? AS DATE) + 30
        GROUP BY hotel_id, strftime(stay_date, '%Y-%m') ORDER BY hotel_id, month""", [today.date(), today.date()])
    pace = q("""
        SELECT hotel_id, stay_date, SUM(otb_now) AS otb, SUM(otb_stly) AS otb_stly, SUM(capacity) AS capacity,
               SUM(pickup_7d) AS pickup_7d
        FROM gold_pickup WHERE days_out BETWEEN 0 AND 60 GROUP BY hotel_id, stay_date ORDER BY hotel_id, stay_date""")
    comp = q("""SELECT hotel_id, stay_date, rate_index, our_bar_usd, comp_median_usd, event_name
                FROM gold_compset WHERE days_out BETWEEN 0 AND 60 ORDER BY hotel_id, stay_date""")
    mix = q("""
        SELECT hotel_id, channel, SUM(room_nights) AS room_nights, SUM(gross_usd) AS gross_usd, SUM(net_usd) AS net_usd
        FROM gold_channel_mix, meta WHERE month >= CAST(date_trunc('month', meta.as_of_date) AS DATE) - 92
        GROUP BY hotel_id, channel ORDER BY hotel_id, net_usd DESC""")
    parity = q("SELECT hotel_id, channel, COUNT(*) AS fechas, SUM(breach::INT) AS con_diferencia FROM gold_parity GROUP BY 1, 2 ORDER BY 1, 2")
    parity_rows = q("""SELECT hotel_id, room_type, stay_date, channel, diff_pct FROM gold_parity WHERE breach
                       ORDER BY stay_date LIMIT 12""")
    health = q("SELECT * FROM gold_source_health ORDER BY source, hotel_id")
    dq = q("SELECT * FROM gold_data_quality ORDER BY \"check\"")
    events = q("""SELECT hotel_id, MIN(stay_date) AS desde, MAX(stay_date) AS hasta, event_name FROM gold_date_events, meta
                  WHERE stay_date BETWEEN meta.as_of_date AND meta.as_of_date + 90 GROUP BY hotel_id, event_name ORDER BY desde""")
    con.close()
    try:
        recs = pricing.recommendations(30)
        recs = recs.reindex(recs.change_pct.abs().sort_values(ascending=False).index).head(rec_limit)
        rec_rows = [dict(hotel_id=r.hotel_id, room_type=r.room_type, stay_date=r.stay_date.strftime("%Y-%m-%d"),
                         current_usd=float(r.bar_usd), new_usd=float(r.rec_bar_usd), change_pct=float(r.change_pct),
                         proj_occ=float(r.proj_occ), confidence=r.confidence, reasons=r.reasons) for r in recs.itertuples()]
    except Exception:   # tablero usable aunque falle el motor
        rec_rows = []
    return dict(
        as_of=str(meta.as_of_ts), today=str(today.date()), hotels=_records(hotels), daily=_records(daily),
        roll=_records(roll), monthly=_records(monthly), pace=_records(pace), comp=_records(comp), mix=_records(mix), parity=_records(parity),
        parity_rows=_records(parity_rows), health=_records(health), dq=_records(dq), events=_records(events),
        recs=rec_rows, pending=channels.list_queue("propuesto"),
    )


def build_html(live: bool = True, engine: str = "") -> str:
    from pathlib import Path
    tpl = (Path(__file__).parent / TEMPLATE_FILE).read_text(encoding="utf-8")
    state = collect(rec_limit=12 if live else 80)
    state["engine"] = engine
    data = json.dumps(state, ensure_ascii=False, default=str).replace("</", "<\\/")
    return tpl.replace("__DATA__", data).replace("__LIVE__", "true" if live else "false")
