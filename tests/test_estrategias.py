"""La estrategia de reversión debe hacer exactamente lo que dice hacer."""

import numpy as np
import pandas as pd

from stockagent import backtest as bt
from stockagent import compare as cmp
from stockagent import strategies as strat


def _serie(valores, inicio="2020-01-01"):
    return pd.Series(valores, index=pd.bdate_range(inicio, periods=len(valores)), dtype=float)


def test_la_reversion_compra_cerca_del_minimo_y_vende_cerca_del_maximo():
    """Serie en V: baja hasta un piso y después sube hasta un techo."""
    bajada = np.linspace(100, 50, 300)      # cae hasta el mínimo
    subida = np.linspace(50, 200, 300)      # sube hasta el máximo
    precios = _serie(np.concatenate([bajada, subida]))

    cfg = strat.MeanReversionConfig(buy_within_pct_of_low=0.10, sell_within_pct_of_high=0.95)
    # Sin dropna: se indexa sobre la serie original para no desalinear las fechas.
    posicion = strat.mean_reversion(precios, cfg).position

    # En el piso de la V (índice 299, precio mínimo) tiene que estar comprado.
    assert posicion.iloc[299] == 1.0
    # En el techo (final de la serie) tiene que haber vendido.
    assert posicion.iloc[-1] == 0.0


def test_la_reversion_no_entra_nunca_si_el_precio_solo_sube():
    """Hallazgo central: en un activo que solo sube, nunca vuelve al mínimo.

    La regla 'esperá el mínimo histórico' deja al inversor mirando desde afuera
    todo el período, porque el mínimo queda cada vez más lejos hacia atrás.
    """
    precios = _serie(np.linspace(100, 1000, 800))

    cfg = strat.MeanReversionConfig(buy_within_pct_of_low=0.10)
    posicion = strat.mean_reversion(precios, cfg).position.dropna()

    assert (posicion == 0.0).all(), "no debería abrir posición en una subida sostenida"


def test_la_reversion_compra_repetidamente_en_una_caida_sostenida():
    """El problema del cuchillo que cae: cada nuevo mínimo dispara la compra."""
    precios = _serie(np.linspace(1000, 100, 800))

    cfg = strat.MeanReversionConfig(buy_within_pct_of_low=0.10)
    posicion = strat.mean_reversion(precios, cfg).position.dropna()

    # En caída libre el precio está siempre en su mínimo histórico: compra y
    # se queda comprado mientras el activo se desploma.
    assert posicion.iloc[-1] == 1.0
    assert (posicion == 1.0).mean() > 0.9


def test_la_reversion_no_usa_informacion_futura():
    """El mínimo de cada fecha se calcula solo con datos hasta esa fecha."""
    rng = np.random.default_rng(5)
    precios = _serie(100 * np.exp(np.cumsum(rng.normal(0, 0.015, 900))))

    completa = strat.mean_reversion(precios).position
    parcial = strat.mean_reversion(precios.iloc[:600]).position

    comunes = parcial.dropna().index
    pd.testing.assert_series_equal(
        completa.loc[comunes], parcial.loc[comunes], check_names=False
    )


def test_la_ventana_movil_es_mas_permisiva_que_el_minimo_historico():
    """Con ventana móvil el mínimo 'se olvida', así que hay más oportunidades de entrar."""
    rng = np.random.default_rng(11)
    precios = _serie(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, 1200))))

    historico = strat.mean_reversion(
        precios, strat.MeanReversionConfig(lookback="expanding")
    ).position.dropna()
    movil = strat.mean_reversion(
        precios, strat.MeanReversionConfig(lookback=252)
    ).position.dropna()

    assert movil.mean() >= historico.mean()


def test_comprar_y_mantener_esta_siempre_invertido():
    precios = _serie(np.linspace(100, 200, 500))
    assert (strat.buy_and_hold(precios).position == 1.0).all()


def test_el_catalogo_declara_cuantas_estrategias_compara():
    """El Deflated Sharpe necesita ese número: es la corrección por probar varias."""
    catalogo = strat.StrategyCatalog()
    precios = _serie(np.linspace(100, 200, 900))
    assert catalogo.n_strategies == len(catalogo.build_all(precios)) == 3


def test_la_comparacion_evalua_a_todas_con_la_misma_vara():
    rng = np.random.default_rng(17)
    precios = _serie(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, 1000))))

    comparacion = cmp.compare_strategies(
        precios, "PRUEBA", costs=bt.CostModel.us_equity(), run_walk_forward=False
    )

    assert len(comparacion.evaluations) == 3
    # Todas corrigen por la misma cantidad de pruebas: si no, la comparación
    # favorecería a la que se evaluó con el listón más bajo.
    assert {e.assessment.trials for e in comparacion.evaluations} == {3}


def test_el_veredicto_avisa_cuando_ninguna_estrategia_supera_el_ajuste():
    """Sobre ruido puro, el veredicto no debe coronar a ninguna ganadora."""
    rng = np.random.default_rng(23)
    precios = _serie(100 * np.exp(np.cumsum(rng.normal(0.0, 0.015, 900))))

    comparacion = cmp.compare_strategies(precios, "RUIDO", run_walk_forward=False)
    veredicto = comparacion.verdict()

    assert "NINGUNA" in veredicto or "incluye el cero" in veredicto


def test_el_veredicto_denuncia_cuando_nadie_le_gana_a_comprar_y_mantener():
    """En una subida sostenida, operar solo agrega costos."""
    precios = _serie(np.linspace(100, 500, 1000))

    comparacion = cmp.compare_strategies(precios, "SUBIDA", run_walk_forward=False)
    veredicto = comparacion.verdict()

    assert "comprar y mantener" in veredicto.lower()


def test_el_reporte_de_comparacion_incluye_la_tabla_y_las_advertencias():
    rng = np.random.default_rng(29)
    precios = _serie(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, 900))))

    comparacion = cmp.compare_strategies(precios, "PRUEBA", run_walk_forward=False)
    texto = cmp.render_comparison(comparacion)

    assert "Comparación de estrategias" in texto
    assert "Reversión a la media" in texto
    assert "Comprar y mantener" in texto
    assert "Veredicto" in texto
    assert "De Bondt & Thaler" in texto


def test_una_estrategia_que_nunca_opera_se_reporta_como_tal_y_no_rompe():
    """Regresión: antes el bootstrap explotaba con retornos constantes en cero.

    El caso es frecuente, no exótico: en el experimento controlado, la reversión
    a la media no llega a abrir posición en cerca de la mitad de los caminos
    alcistas, porque el precio nunca vuelve cerca de su mínimo histórico.
    """
    precios = _serie(np.linspace(100, 1000, 900))  # sube siempre: la reversión nunca entra

    comparacion = cmp.compare_strategies(precios, "SOLO_SUBE", run_walk_forward=False)
    reversion = next(e for e in comparacion.evaluations if "Reversión" in e.name)

    assert reversion.never_traded
    assert reversion.result.time_in_market == 0.0
    # Sin operaciones no hay Sharpe: debe informarse como sin dato, no inventarse.
    assert np.isnan(reversion.sharpe_ci[0])
    assert not reversion.ci_includes_zero, "sin intervalo no se puede afirmar nada"

    veredicto = comparacion.verdict()
    assert "NO ABRIÓ POSICIÓN" in veredicto
    assert "no haber participado" in veredicto

    # Y la tabla debe renderizar sin romperse.
    assert "Reversión a la media" in comparacion.table()
