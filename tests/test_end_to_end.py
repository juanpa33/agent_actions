"""Prueba de extremo a extremo del pipeline, sin red.

Usa datos SINTÉTICOS marcados como tales, lo que permite verificar dos cosas a
la vez: que el encadenamiento completo funciona, y que la barrera anti
contaminación impide publicar un reporte construido sobre ellos.
"""

import numpy as np
import pandas as pd
import pytest

from stockagent import backtest as bt
from stockagent import pipeline as pl
from stockagent import report as rp
from stockagent.datasources import crossvalidate
from stockagent.provenance import ContaminatedDataError, synthetic


def _ohlcv(n=900, seed=101):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.018, n))), index=idx)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * (1 + np.abs(rng.normal(0, 0.008, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.008, n))),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
        },
        index=idx,
    )


def test_el_pipeline_completo_corre_y_produce_resultados_coherentes():
    frame = _ohlcv()
    prices = synthetic(frame, "activo_de_prueba")
    market = _ohlcv(seed=202)["close"].pct_change().dropna()

    analysis = pl.analyze_asset(
        "PRUEBA", prices, market, pl.PipelineConfig(trials_evaluated=3),
        bt.CostModel.us_equity(),
        crossvalidate.reconcile("PRUEBA", prices, None),
        crossvalidate.detect_data_anomalies(frame["close"]),
        [],
    )

    assert analysis.backtest.equity_curve.notna().all()
    assert 0.0 <= analysis.backtest.time_in_market <= 1.0
    assert analysis.backtest.total_costs >= 0.0
    assert 0.0 <= analysis.sharpe_assessment.psr <= 1.0
    assert 0.0 <= analysis.sharpe_assessment.deflated_sharpe <= 1.0
    assert analysis.walk_forward is not None
    assert len(analysis.walk_forward.folds) == 4

    breakdown = analysis.signals.latest_breakdown()
    assert breakdown["decision"] in ("COMPRAR/MANTENER", "EFECTIVO")


def test_el_reporte_se_niega_a_publicar_datos_sinteticos():
    """La barrera final del sistema: es imposible publicar un reporte de laboratorio."""
    frame = _ohlcv()
    prices = synthetic(frame, "activo_de_prueba")
    market = _ohlcv(seed=202)["close"].pct_change().dropna()

    analysis = pl.analyze_asset(
        "PRUEBA", prices, market, pl.PipelineConfig(), bt.CostModel.us_equity(),
        crossvalidate.reconcile("PRUEBA", prices, None), {}, [],
    )

    with pytest.raises((ContaminatedDataError, RuntimeError)):
        rp.assert_no_synthetic_data([analysis])


def test_el_reporte_incluye_incertidumbre_y_advertencias():
    """Ninguna cifra puede presentarse sin su contexto estadístico."""
    frame = _ohlcv()
    prices = synthetic(frame, "activo_de_prueba")
    market = _ohlcv(seed=202)["close"].pct_change().dropna()

    analysis = pl.analyze_asset(
        "PRUEBA", prices, market, pl.PipelineConfig(trials_evaluated=5),
        bt.CostModel.us_equity(),
        crossvalidate.reconcile("PRUEBA", prices, None), {}, [],
    )

    markdown = rp.render_report([analysis], trials_evaluated=5)

    assert "no es asesoramiento financiero" in markdown
    assert "Deflated Sharpe" in markdown
    assert "IC 95%" in markdown
    assert "Limitaciones" in markdown
    assert "Sesgo de supervivencia" in markdown
    assert "5 configuraciones evaluadas" in markdown
