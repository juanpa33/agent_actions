"""La procedencia debe ser imposible de eludir."""

import pandas as pd
import pytest

from stockagent.provenance import (
    ContaminatedDataError, DataKind, TracedSeries, observed, synthetic,
)


def _series(n=10):
    return pd.Series(range(n), index=pd.bdate_range("2024-01-01", periods=n), dtype=float)


def test_dato_observado_es_apto_para_reporte():
    ts = observed(_series(), "yahoo:TEST", "https://example.com")
    ts.assert_report_safe()
    assert ts.provenance.kind is DataKind.OBSERVED


def test_dato_sintetico_no_puede_reportarse():
    ts = synthetic(_series(), "test")
    with pytest.raises(ContaminatedDataError):
        ts.assert_report_safe()


def test_la_contaminacion_sintetica_sobrevive_a_las_derivaciones():
    """Ningún encadenamiento de cálculos puede 'lavar' el origen sintético."""
    ts = synthetic(_series(), "test")
    derived = ts
    for step in range(5):
        derived = derived.derive(derived.data * 2, f"paso_{step}")

    assert derived.provenance.kind is DataKind.SYNTHETIC
    with pytest.raises(ContaminatedDataError):
        derived.assert_report_safe()


def test_mezclar_real_con_sintetico_contamina_el_resultado():
    real = observed(_series(), "yahoo:TEST", "https://example.com")
    fake = synthetic(_series(), "test")
    mixed = real.derive(real.data + fake.data, "suma", extra_parents=[fake])

    assert mixed.provenance.kind is DataKind.SYNTHETIC
    with pytest.raises(ContaminatedDataError):
        mixed.assert_report_safe()


def test_la_derivacion_de_datos_reales_conserva_el_linaje_completo():
    real = observed(_series(), "yahoo:TEST", "https://example.com")
    returns = real.derive(real.data.pct_change().dropna(), "retornos")

    assert len(returns.lineage) == 2
    assert returns.lineage[0].source_id == "yahoo:TEST"
    assert "yahoo:TEST" in returns.provenance.parents
    returns.assert_report_safe()


def test_el_reporte_de_linaje_incluye_url_y_momento_de_descarga():
    real = observed(_series(), "yahoo:TEST", "https://example.com/data.csv")
    text = real.lineage_report()
    assert "https://example.com/data.csv" in text
    assert "yahoo:TEST" in text
