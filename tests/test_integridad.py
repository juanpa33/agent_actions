"""El sistema debe fallar ruidosamente antes que entregar un número inventado."""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stockagent import news as nw
from stockagent import pipeline as pl
from stockagent import signals as sg
from stockagent.datasources import crossvalidate
from stockagent.provenance import MissingDataError, observed


def test_el_modulo_de_noticias_se_niega_a_producir_sentimiento():
    """Decisión de diseño verificada por test, para que nadie la revierta sin notarlo."""
    with pytest.raises(NotImplementedError) as exc:
        nw.sentiment_score("NVDA")
    assert "no es un dato" in str(exc.value)


def test_un_evento_manual_sin_url_es_rechazado():
    registros = [{"date": "2026-01-01", "ticker": "X", "category": "c", "label": "sin fuente"}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(registros, fh)
        ruta = fh.name
    try:
        with pytest.raises(MissingDataError) as exc:
            nw.load_manual_events(ruta)
        assert "url" in str(exc.value).lower()
    finally:
        Path(ruta).unlink()


def test_un_activo_con_historia_insuficiente_no_genera_senales_parciales():
    idx = pd.bdate_range("2025-01-01", periods=100)
    prices = observed(
        pd.DataFrame({"close": np.linspace(100, 120, 100)}, index=idx),
        "yahoo:CORTO", "https://example.com",
    )
    with pytest.raises(MissingDataError) as exc:
        pl.analyze_asset(
            "CORTO", prices, pd.Series(0.0, index=idx), pl.PipelineConfig(),
            __import__("stockagent.backtest", fromlist=["CostModel"]).CostModel(),
            crossvalidate.reconcile("CORTO", prices, None), {}, [],
        )
    assert "252" in str(exc.value)


def test_la_validacion_cruzada_detecta_una_discrepancia_entre_fuentes():
    idx = pd.bdate_range("2025-01-01", periods=60)
    buena = observed(pd.DataFrame({"close": np.full(60, 100.0)}, index=idx), "a", "u")
    mala = pd.Series(np.full(60, 100.0), index=idx)
    mala.iloc[30] = 150.0  # un dato corrupto en la segunda fuente
    secundaria = observed(mala, "b", "u")

    report = crossvalidate.reconcile("TEST", buena, secundaria, tolerance_pct=1.0)
    assert not report.clean
    assert "2025-02-11" in report.days_over_tolerance or len(report.days_over_tolerance) == 1


def test_la_ausencia_de_segunda_fuente_se_reporta_explicitamente():
    """No tener validación cruzada no es lo mismo que haberla pasado."""
    idx = pd.bdate_range("2025-01-01", periods=30)
    primaria = observed(pd.DataFrame({"close": np.full(30, 100.0)}, index=idx), "a", "u")
    report = crossvalidate.reconcile("TEST", primaria, None)

    assert not report.clean
    assert "SIN validación cruzada" in report.summary()


def test_se_detecta_un_split_sin_ajustar_como_salto_extremo():
    """Un split 10:1 no ajustado aparece como un -90% en un día."""
    idx = pd.bdate_range("2025-01-01", periods=200)
    precios = pd.Series(np.full(200, 1000.0), index=idx)
    precios.iloc[100:] = 100.0
    precios += np.random.default_rng(3).normal(0, 1.0, 200)

    anomalias = crossvalidate.detect_data_anomalies(precios)
    assert "saltos_extremos" in anomalias


def test_se_detectan_precios_congelados():
    """Una serie que no se mueve durante días suele ser una fuente rota, no un mercado."""
    idx = pd.bdate_range("2025-01-01", periods=100)
    precios = pd.Series(np.linspace(100, 110, 100), index=idx)
    precios.iloc[40:50] = precios.iloc[40]

    anomalias = crossvalidate.detect_data_anomalies(precios)
    assert "precio_congelado" in anomalias


def test_el_stop_por_atr_sale_de_la_posicion_ante_una_caida_fuerte():
    idx = pd.bdate_range("2025-01-01", periods=120)
    precios = pd.Series(np.concatenate([np.linspace(100, 150, 100), np.linspace(150, 90, 20)]), index=idx)
    high, low = precios * 1.01, precios * 0.99
    flag = pd.Series(1.0, index=idx)

    con_stop = sg.apply_atr_stop(precios, high, low, flag, atr_multiple=2.0)
    assert con_stop.iloc[-1] == 0.0, "el stop debe haber cortado la posición en la caída"
    assert con_stop.iloc[80] == 1.0, "y haber estado invertido durante la suba"


def test_el_peso_por_volatilidad_nunca_apalanca_en_el_perfil_conservador():
    rng = np.random.default_rng(5)
    quietos = pd.Series(rng.normal(0, 0.001, 300))  # volatilidad muy baja
    pesos = sg.volatility_target_weight(quietos, target_annual_vol=0.15, max_weight=1.0)
    assert pesos.dropna().max() <= 1.0


def test_el_peso_baja_cuando_sube_la_volatilidad():
    rng = np.random.default_rng(7)
    tranquilo = pd.Series(rng.normal(0, 0.005, 300))
    turbulento = pd.Series(rng.normal(0, 0.030, 300))
    w1 = sg.volatility_target_weight(tranquilo).dropna().mean()
    w2 = sg.volatility_target_weight(turbulento).dropna().mean()
    assert w2 < w1


def test_el_stop_no_reingresa_hasta_que_la_senal_se_apaga_y_vuelve():
    """Regresión: un stop que recompra al día siguiente no protege, solo paga costos.

    La reentrada debe exigir que la señal de entrada se apague y se vuelva a
    encender, confirmando una tendencia nueva en vez de un rebote pasajero.
    """
    idx = pd.bdate_range("2025-01-01", periods=160)
    subida = np.linspace(100, 150, 100)
    caida = np.linspace(150, 100, 30)
    recuperacion = np.linspace(100, 130, 30)
    precios = pd.Series(np.concatenate([subida, caida, recuperacion]), index=idx)
    high, low = precios * 1.01, precios * 0.99

    # La señal permanece encendida todo el tiempo: solo el stop puede sacarnos.
    siempre_encendida = pd.Series(1.0, index=idx)
    sin_reentrada = sg.apply_atr_stop(precios, high, low, siempre_encendida, atr_multiple=2.0)
    salidas = sin_reentrada[sin_reentrada == 0.0]
    assert len(salidas) > 0, "el stop debe dispararse durante la caída"
    assert sin_reentrada.loc[salidas.index[0]:].max() == 0.0, (
        "sin que la señal se apague, no puede haber reentrada"
    )

    # Ahora la señal sí se apaga durante la caída y se vuelve a encender.
    con_ciclo = pd.Series(1.0, index=idx)
    con_ciclo.iloc[100:130] = 0.0
    reentrada = sg.apply_atr_stop(precios, high, low, con_ciclo, atr_multiple=2.0)
    assert reentrada.iloc[-1] == 1.0, "tras el ciclo completo debe poder reingresar"
