"""Motor de recomendación de precios (revenue management) — reglas transparentes.

Por qué reglas y no un modelo opaco: en un MVP con un hotel real, cada recomendación
debe poder explicarse en una línea al revenue manager ("ocupación proyectada 94% por
pickup, evento de impacto alto, competencia +12%"). El modelo estadístico entra después,
cuando hay historia real que lo justifique.

Método:
  1. Proyección de ocupación final por "pickup method": lo reservado hoy (OTB) más lo
     que faltó reservar en el mismo punto del año pasado (STLY), ajustado por el ritmo
     (pace) de este año. Si no hay historia comparable, se usa la curva de lead time.
  2. Reglas por ocupación proyectada, ritmo, evento, últimas habitaciones y competencia.
  3. Barreras: paso máximo por recomendación, piso/techo por hotel y por tipo de habitación,
     y "no mover" si el cambio es < 2%.

La función `recommend` es pura (DataFrame → DataFrame): sirve igual para el día de hoy
y para el backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .gold import connect

MIN_CHANGE = 0.02


def _lead_booked_fraction(days_out: np.ndarray) -> np.ndarray:
    """Fracción esperada de la demanda final ya reservada a `days_out` días de la estadía."""
    frac = np.zeros_like(days_out, dtype=float)
    for ch in C.CHANNELS.values():
        theta = ch["lead"] / 2.0
        z = np.maximum(days_out, 0) / theta
        frac += ch["share"] * np.exp(-z) * (1 + z)    # 1 - CDF gamma(2)
    return np.clip(frac, 0.03, 1.0)


def load_features(horizon_days: int = 45, hotel_id: str | None = None) -> pd.DataFrame:
    """Features de pricing desde gold para los próximos `horizon_days` días."""
    con = connect(read_only=True)
    q = """
    SELECT p.hotel_id, p.room_type, p.stay_date, p.days_out, p.capacity, p.otb_now, p.pickup_7d,
           p.otb_stly, p.final_ly, p.bar_direct_usd AS bar_usd, p.available_rooms, p.event_name, p.event_impact,
           c.comp_median_usd, c.comp_min_usd, c.comp_max_usd
    FROM gold_pickup p
    LEFT JOIN gold_compset c ON c.hotel_id = p.hotel_id AND c.stay_date = p.stay_date
    WHERE p.days_out BETWEEN 0 AND ?
    """
    params = [horizon_days]
    if hotel_id:
        q += " AND p.hotel_id = ?"
        params.append(hotel_id)
    df = con.execute(q + " ORDER BY p.hotel_id, p.room_type, p.stay_date", params).df()
    con.close()
    df["stay_date"] = pd.to_datetime(df.stay_date)
    df["bar_usd"] = df.bar_usd.round(0)   # el ARI vuelve de moneda local: quita centavos de redondeo
    return df


def _bounds(hotel_id: str, room: str) -> tuple[float, float]:
    h = C.HOTEL_BY_ID[hotel_id]
    ratio = h.base_usd[room] / h.base_usd["STD"]
    return h.floor_usd * ratio, h.ceiling_usd * ratio


def recommend(feat: pd.DataFrame) -> pd.DataFrame:
    df = feat.copy()
    n = len(df)
    if n == 0:
        return df.assign(proj_occ=[], rec_bar_usd=[], change_pct=[], action=[], reasons=[], confidence=[])
    cap = df.capacity.to_numpy(float)
    otb = df.otb_now.to_numpy(float)
    stly = df.otb_stly.to_numpy(float)
    fly = df.final_ly.to_numpy(float)
    dout = df.days_out.to_numpy(float)

    # 1) proyección
    has_ly = (stly >= 3) & (fly >= 3)
    pace = np.where(has_ly, otb / np.maximum(stly, 1), 1.0)
    pace_c = np.clip(pace, 0.6, 1.6)
    proj_pickup = otb + np.maximum(fly - stly, 0) * np.sqrt(pace_c)
    proj_curve = otb / _lead_booked_fraction(dout)
    proj = np.where(has_ly, 0.7 * proj_pickup + 0.3 * proj_curve, proj_curve)
    proj = np.maximum(proj, otb)
    proj_occ = proj / cap
    df["pace_vs_stly"] = np.where(has_ly, pace, np.nan)
    df["proj_occ"] = proj_occ

    # 2) reglas (aditivas, en fracción)
    mult = np.zeros(n)
    reasons: list[list[str]] = [[] for _ in range(n)]

    def add(mask, val, text):
        mask = np.asarray(mask)
        mult[mask] += val if np.isscalar(val) else val[mask]
        for i in np.nonzero(mask)[0]:
            reasons[i].append(text(i) if callable(text) else text)

    far = dout > 45
    damp = np.where(far, 0.5, 1.0)       # lejos de la fecha, el pronóstico es menos confiable
    pct = lambda i: f"{proj_occ[i]:.0%}"  # noqa: E731
    add(proj_occ >= 1.0, 0.12 * damp, lambda i: f"demanda proyectada ≥ capacidad ({pct(i)})")
    add((proj_occ >= 0.92) & (proj_occ < 1.0), 0.08 * damp, lambda i: f"ocupación proyectada alta ({pct(i)})")
    add((proj_occ >= 0.82) & (proj_occ < 0.92), 0.04 * damp, lambda i: f"ocupación proyectada firme ({pct(i)})")
    add((proj_occ < 0.40) & (dout <= 21), -0.10, lambda i: f"ocupación proyectada baja ({pct(i)}) a {int(dout[i])} días")
    add((proj_occ >= 0.40) & (proj_occ < 0.50) & (dout <= 14), -0.06, lambda i: f"ocupación proyectada floja ({pct(i)}) a {int(dout[i])} días")
    add((proj_occ >= 0.50) & (proj_occ < 0.60) & (dout <= 7), -0.04, lambda i: f"ocupación proyectada ({pct(i)}) sin cubrir a {int(dout[i])} días")
    add(has_ly & (pace >= 1.25) & (proj_occ >= 0.7), 0.03, lambda i: f"ritmo de reservas {pace[i]:.2f}× vs año pasado")
    add(has_ly & (pace <= 0.8) & (dout <= 30) & (proj_occ < 0.8), -0.03, lambda i: f"ritmo de reservas {pace[i]:.2f}× vs año pasado")
    ev = df.event_impact.fillna(0).to_numpy()
    evname = df.event_name.fillna("").to_numpy()
    add((ev >= 3) & (proj_occ >= 0.6), 0.08, lambda i: f"evento de impacto alto: {evname[i]}")
    add((ev == 2) & (proj_occ >= 0.6), 0.05, lambda i: f"evento de impacto medio: {evname[i]}")
    avail = df.available_rooms.to_numpy(float)
    add(np.nan_to_num(avail, nan=99) <= 2, 0.06, lambda i: f"quedan {int(avail[i])} habitaciones")

    cur = df.bar_usd.to_numpy(float)
    target = cur * (1 + mult)

    # 3) competencia (solo informativa + acota extremos). Comp set está medido para tipo STD: se escala por tipo.
    ratio = np.array([C.HOTEL_BY_ID[h].base_usd[r] / C.HOTEL_BY_ID[h].base_usd["STD"]
                      for h, r in zip(df.hotel_id, df.room_type)])
    comp = df.comp_median_usd.to_numpy(float) * ratio
    has_comp = ~np.isnan(comp)
    df["comp_median_room_usd"] = np.where(has_comp, comp, np.nan)
    over = has_comp & (target > comp * 1.30) & (proj_occ < 0.95)
    under = has_comp & (target < comp * 0.85) & (dout > 2)
    for i in np.nonzero(over)[0]:
        reasons[i].append(f"tope por competencia (mediana comp ×1.30 = ${comp[i] * 1.30:.0f})")
    for i in np.nonzero(under)[0]:
        reasons[i].append(f"piso por competencia (mediana comp ×0.85 = ${comp[i] * 0.85:.0f})")
    target = np.where(over, comp * 1.30, target)
    target = np.where(under, comp * 0.85, target)

    # 4) barreras
    lo = np.array([_bounds(h, r)[0] for h, r in zip(df.hotel_id, df.room_type)])
    hi = np.array([_bounds(h, r)[1] for h, r in zip(df.hotel_id, df.room_type)])
    step_lo, step_hi = cur * (1 - C.MAX_STEP_PCT), cur * (1 + C.MAX_STEP_PCT)
    rec = np.clip(np.clip(target, step_lo, step_hi), lo, hi)
    rec = np.clip(np.round(rec), np.ceil(step_lo), np.floor(step_hi))   # el redondeo no debe violar el paso máximo
    rec = np.clip(rec, np.ceil(lo), np.floor(hi))
    change = rec / cur - 1.0
    hold = np.abs(change) < MIN_CHANGE
    rec = np.where(hold, cur, rec)
    change = np.where(hold, 0.0, change)
    clipped = (~hold) & ((np.abs(np.clip(target, step_lo, step_hi) - rec) > 0.5))
    for i in np.nonzero(clipped)[0]:
        reasons[i].append("ajustado por piso/techo del hotel")

    conf = np.where(has_ly & (dout <= 30), "alta", np.where(has_ly | (dout <= 14), "media", "baja"))
    df["rec_bar_usd"] = rec
    df["change_pct"] = change
    df["action"] = np.where(hold, "mantener", np.where(change > 0, "subir", "bajar"))
    df["reasons"] = [r if r else ["sin señales fuertes: mantener"] for r in reasons]
    df["confidence"] = conf
    return df


def recommendations(horizon_days: int = 45, hotel_id: str | None = None, only_changes: bool = True) -> pd.DataFrame:
    rec = recommend(load_features(horizon_days, hotel_id))
    if only_changes:
        rec = rec[rec.action != "mantener"]
    return rec.reset_index(drop=True)
