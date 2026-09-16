"""El estudio de eventos debe recuperar un efecto que se sabe que está, y no
inventar uno donde no lo hay."""

import numpy as np
import pandas as pd
import pytest

from stockagent import events as ev


def _mercado_y_activo(n=600, beta=1.4, shock_pos=500, shock=0.0, seed=31):
    """Genera un activo que sigue al mercado con beta conocido, más un shock puntual."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-01", periods=n)
    market = pd.Series(rng.normal(0.0004, 0.010, n), index=idx)
    asset = beta * market + pd.Series(rng.normal(0.0, 0.006, n), index=idx)
    if shock:
        asset.iloc[shock_pos] += shock
    return asset, market, idx


def test_el_modelo_de_mercado_recupera_el_beta_verdadero():
    asset, market, idx = _mercado_y_activo(beta=1.4)
    alpha, beta, r2, resid, n = ev.estimate_market_model(
        asset, market, idx[500], ev.EventStudyConfig()
    )
    assert abs(beta - 1.4) < 0.15
    assert abs(alpha) < 0.001
    assert r2 > 0.5


def test_detecta_un_retorno_anormal_grande_e_inyectado():
    """Se inyecta un shock de +12% y el estudio debe encontrarlo y declararlo significativo."""
    asset, market, idx = _mercado_y_activo(shock_pos=500, shock=0.12)
    result = ev.run_event_study(asset, market, idx[500], "shock de prueba", "test")

    assert result.car > 0.08, "debe capturar la mayor parte del shock inyectado"
    assert result.significant
    assert result.car_pvalue < 0.01


def test_no_declara_significativo_un_dia_sin_evento():
    """Sin shock, el retorno anormal debe ser indistinguible del ruido."""
    asset, market, idx = _mercado_y_activo(shock=0.0)
    result = ev.run_event_study(asset, market, idx[500], "dia cualquiera", "test")
    assert not result.significant


def test_un_movimiento_explicado_por_el_mercado_no_es_anormal():
    """Si el activo cae porque cayó todo el mercado, eso NO es un retorno anormal.

    Es la distinción central del método: separar el movimiento atribuible al
    mercado del atribuible a la noticia de la empresa.
    """
    rng = np.random.default_rng(37)
    idx = pd.bdate_range("2023-01-01", periods=600)
    market = pd.Series(rng.normal(0.0004, 0.010, 600), index=idx)
    market.iloc[500] = -0.07  # derrumbe general del mercado
    asset = 1.0 * market + pd.Series(rng.normal(0.0, 0.005, 600), index=idx)

    result = ev.run_event_study(asset, market, idx[500], "caida general", "test")
    assert abs(result.car) < 0.03, "el movimiento explicado por el mercado no es anormal"
    assert not result.significant


def test_el_evento_se_ancla_a_la_siguiente_rueda_si_cae_en_dia_no_habil():
    asset, market, idx = _mercado_y_activo(shock_pos=500, shock=0.10)
    lunes = idx[500]
    assert lunes.weekday() < 5
    sabado = lunes - pd.Timedelta(days=2) if lunes.weekday() == 0 else None
    if sabado is not None:
        result = ev.run_event_study(asset, market, sabado, "noticia de sabado", "test")
        assert result.car > 0.05, "el shock del lunes debe quedar dentro de la ventana"


def test_la_agregacion_por_categoria_no_infiere_con_muestras_chicas():
    """Con pocos eventos no se reporta significancia: sería numerología."""
    asset, market, idx = _mercado_y_activo(shock=0.0)
    results = [
        ev.run_event_study(asset, market, idx[400 + 20 * k], f"e{k}", "categoria_chica")
        for k in range(3)
    ]
    agg = ev.aggregate_by_category(results)[0]
    assert agg.n_events == 3
    assert "demasiado chica" in agg.describe()


def test_la_agregacion_detecta_un_efecto_sistematico_por_categoria():
    """Diez eventos con shock consistente deben producir un CAAR significativo."""
    rng = np.random.default_rng(41)
    idx = pd.bdate_range("2021-01-01", periods=1200)
    market = pd.Series(rng.normal(0.0004, 0.010, 1200), index=idx)
    asset = 1.0 * market + pd.Series(rng.normal(0.0, 0.006, 1200), index=idx)

    posiciones = [600 + 50 * k for k in range(10)]
    for pos in posiciones:
        asset.iloc[pos] += 0.05

    results = [
        ev.run_event_study(asset, market, idx[pos], f"e{k}", "buenas_noticias")
        for k, pos in enumerate(posiciones)
    ]
    agg = ev.aggregate_by_category(results)[0]

    assert agg.n_events == 10
    assert agg.mean_car > 0.03
    assert agg.pvalue < 0.05
    assert "efecto sistemático detectado" in agg.describe()


def test_falla_si_no_hay_historia_suficiente_antes_del_evento():
    asset, market, idx = _mercado_y_activo(n=600)
    with pytest.raises(ValueError):
        ev.run_event_study(asset, market, idx[10], "muy temprano", "test")
