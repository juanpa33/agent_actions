"""Backtest honesto (y limitado) del motor de pricing sobre la historia simulada.

Para cada noche-habitación de los últimos 120 días se reconstruye lo que el motor habría
visto a 14 días de la estadía (reservado a esa fecha + ritmo del año pasado), se calcula la
recomendación y se compara contra lo que pasó.

Dos lecturas, de menor a mayor supuesto:

1. CALIDAD DE LA SEÑAL (sin supuestos de elasticidad): ¿las fechas en las que el motor
   sugería subir terminaron más llenas que aquellas en las que sugería bajar?
2. INGRESO CONTRAFÁCTICO (supone una elasticidad-precio de la demanda que se reserva después
   de la fecha de corte): ingreso ya reservado + lo que se habría reservado al precio
   sugerido. Se muestra para varias elasticidades, porque es la parte que no se observa.
   Es conservador en fechas agotadas: la demanda que ya se perdió por falta de cupo no es
   visible en los datos, así que el modelo no le acredita upside.

Es un ejercicio sobre datos SINTÉTICOS: sirve para validar la mecánica y el método, no
para prometer mejoras de ingresos en un hotel real.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pricing
from .gold import connect

CUTOFF_DAYS = 14
WINDOW_DAYS = 120
ELASTICITIES = (0.8, 1.2, 1.6)

SQL = f"""
WITH m AS (SELECT as_of_date AS today FROM meta),
n AS (
  SELECT hotel_id, room_type, stay_date,
         SUM(CASE WHEN created_at <= CAST(stay_date AS TIMESTAMP) - INTERVAL {CUTOFF_DAYS} DAY
                   AND (cancelled_at IS NULL OR cancelled_at > CAST(stay_date AS TIMESTAMP) - INTERVAL {CUTOFF_DAYS} DAY) THEN 1 ELSE 0 END) AS otb_t,
         SUM(CASE WHEN created_at <= CAST(stay_date AS TIMESTAMP) - INTERVAL {CUTOFF_DAYS} DAY
                   AND (cancelled_at IS NULL OR cancelled_at > CAST(stay_date AS TIMESTAMP) - INTERVAL {CUTOFF_DAYS} DAY) THEN rate_usd ELSE 0 END) AS otb_rev_t,
         SUM(CASE WHEN status = 'activa' THEN 1 ELSE 0 END) AS final_n,
         SUM(CASE WHEN status = 'activa' THEN rate_usd ELSE 0 END) AS final_rev,
         AVG(CASE WHEN channel = 'DIRECT' AND status = 'activa' THEN rate_usd END) AS bar_direct
  FROM fact_room_night GROUP BY hotel_id, room_type, stay_date
)
SELECT c.hotel_id, c.room_type, c.stay_date, r.rooms AS capacity, c.otb_t, c.otb_rev_t, c.final_n, c.final_rev,
       COALESCE(c.bar_direct, c.final_rev / NULLIF(c.final_n, 0)) AS bar_usd,
       l.otb_t AS otb_stly, l.final_n AS final_ly, e.event_name, COALESCE(e.impact_level, 0) AS event_impact
FROM n c CROSS JOIN m
JOIN dim_room_type r ON r.hotel_id = c.hotel_id AND r.room_type = c.room_type
LEFT JOIN n l ON l.hotel_id = c.hotel_id AND l.room_type = c.room_type AND l.stay_date = c.stay_date - 364
LEFT JOIN gold_date_events e ON e.hotel_id = c.hotel_id AND e.stay_date = c.stay_date
WHERE c.stay_date BETWEEN m.today - {WINDOW_DAYS} AND m.today - 1 AND c.final_n > 0
"""


def run() -> dict:
    con = connect(read_only=True)
    df = con.execute(SQL).df()
    con.close()
    if df.empty:
        return dict(n=0, summary=pd.DataFrame(), signal=pd.DataFrame())
    df["stay_date"] = pd.to_datetime(df.stay_date)
    feat = df.rename(columns={"otb_t": "otb_now"}).assign(
        days_out=CUTOFF_DAYS, available_rooms=lambda x: x.capacity - x.otb_now,
        comp_median_usd=np.nan, pickup_7d=np.nan)
    rec = pricing.recommend(feat)
    rec["final_occ"] = rec.final_n / rec.capacity

    signal = (rec.groupby("action").agg(casos=("final_occ", "size"), ocupacion_final_media=("final_occ", "mean"),
                                        pct_llenas_90=("final_occ", lambda s: (s >= 0.9).mean()),
                                        cambio_medio=("change_pct", "mean")).reset_index())

    remaining = np.maximum(rec.final_n - rec.otb_now, 0).to_numpy(float)
    rem_rev = np.maximum(rec.final_rev - rec.otb_rev_t, 0).to_numpy(float)
    price_rem = np.where(remaining > 0, rem_rev / np.maximum(remaining, 1), rec.bar_usd)
    ratio = (rec.rec_bar_usd / rec.bar_usd).to_numpy(float)
    room_left = (rec.capacity - rec.otb_now).clip(lower=0).to_numpy(float)
    rows = []
    for eps in ELASTICITIES:
        r_new = np.minimum(remaining * ratio ** (-eps), room_left)
        rev_new = rec.otb_rev_t.to_numpy(float) + r_new * price_rem * ratio
        rec[f"cf_rev_{eps}"] = rev_new
        for hid, g in rec.groupby("hotel_id"):
            idx = g.index
            actual, cf = float(g.final_rev.sum()), float(rec.loc[idx, f"cf_rev_{eps}"].sum())
            rows.append(dict(hotel_id=hid, elasticidad=eps, ingreso_real=actual, ingreso_contrafactual=cf, delta_pct=cf / actual - 1))
        actual, cf = float(rec.final_rev.sum()), float(rev_new.sum())
        rows.append(dict(hotel_id="TOTAL", elasticidad=eps, ingreso_real=actual, ingreso_contrafactual=cf, delta_pct=cf / actual - 1))
    summary = pd.DataFrame(rows)
    return dict(n=len(rec), changed=int((rec.action != "mantener").sum()), summary=summary, signal=signal)
