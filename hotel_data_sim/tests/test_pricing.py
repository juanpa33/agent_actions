import numpy as np
import pandas as pd
import pytest

from hotelsim import config as C, pricing


def feat(**over):
    base = dict(hotel_id="MDZ01", room_type="STD", stay_date=pd.Timestamp("2026-10-10"), days_out=10, capacity=24,
                otb_now=10, otb_stly=10, final_ly=14, pickup_7d=2, bar_usd=100.0, available_rooms=14,
                event_name=None, event_impact=0, comp_median_usd=np.nan, comp_min_usd=np.nan, comp_max_usd=np.nan)
    base.update(over)
    return pd.DataFrame([base])


def rec(**over):
    return pricing.recommend(feat(**over)).iloc[0]


def test_sube_con_demanda_fuerte_y_evento():
    r = rec(otb_now=23, otb_stly=15, final_ly=20, available_rooms=1, event_impact=3, event_name="X")
    assert r.action == "subir" and r.rec_bar_usd > 100 and r.proj_occ >= 0.95
    assert any("evento" in x for x in r.reasons)


def test_baja_cerca_de_la_fecha_con_baja_ocupacion():
    r = rec(otb_now=3, otb_stly=8, final_ly=12, days_out=5)
    assert r.action == "bajar" and r.rec_bar_usd < 100


def test_mantiene_sin_senales():
    r = rec()
    assert r.action == "mantener" and r.rec_bar_usd == 100.0


def test_barreras_paso_maximo_y_piso_techo():
    r = rec(otb_now=24, otb_stly=12, final_ly=24, available_rooms=0, event_impact=3, event_name="X", bar_usd=100.0)
    assert r.rec_bar_usd <= 100 * (1 + C.MAX_STEP_PCT) + 1e-9
    r = rec(otb_now=1, otb_stly=10, final_ly=14, days_out=3, bar_usd=62.0)            # piso MDZ01 STD = 60
    assert r.rec_bar_usd >= C.HOTEL_BY_ID["MDZ01"].floor_usd


def test_tope_por_competencia():
    r = rec(otb_now=20, otb_stly=15, final_ly=20, available_rooms=4, comp_median_usd=90.0)
    assert r.rec_bar_usd <= 90 * 1.30 + 1


def test_recomendaciones_reales_respetan_reglas(world):
    df = pricing.recommendations(45)
    assert len(df) > 0
    assert (df.change_pct.abs() <= C.MAX_STEP_PCT + 1e-9).all()
    for r in df.itertuples():
        h = C.HOTEL_BY_ID[r.hotel_id]
        ratio = h.base_usd[r.room_type] / h.base_usd["STD"]
        assert h.floor_usd * ratio - 1 <= r.rec_bar_usd <= h.ceiling_usd * ratio + 1
        assert r.reasons


def test_backtest_la_senal_ordena_por_ocupacion_final(world):
    from hotelsim import backtest
    out = backtest.run()
    s = out["signal"].set_index("action")
    assert s.loc["subir", "ocupacion_final_media"] > s.loc["bajar", "ocupacion_final_media"] + 0.15
