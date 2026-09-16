"""La simulación en dinero tiene que cuadrar como una cuenta bancaria."""

import numpy as np
import pandas as pd
import pytest

from stockagent import simulation as sim
from stockagent.backtest import CostModel


def _serie(valores, inicio="2020-01-01"):
    return pd.Series(valores, index=pd.bdate_range(inicio, periods=len(valores)), dtype=float)


def _v(n=900, seed=3, deriva=0.0004):
    rng = np.random.default_rng(seed)
    return _serie(100 * np.exp(np.cumsum(rng.normal(deriva, 0.018, n))))


def test_la_caja_cuadra_con_el_libro_de_operaciones():
    """Ninguna plata aparece ni desaparece: el saldo final debe surgir del libro."""
    precios = _v()
    r = sim.simular_escalonada(precios, costos=CostModel(0.001, 0, 0.001))

    caja_reconstruida = r.capital_inicial + sum(t.neto for t in r.transacciones)
    assert np.isclose(caja_reconstruida, r.caja_final, atol=0.01), (
        "el saldo de caja no se explica por las operaciones registradas"
    )

    valor = r.acciones_finales * r.precio_final + r.caja_final
    assert np.isclose(valor, r.valor_final, atol=0.01)


def test_los_dividendos_se_cobran_solo_si_hay_acciones():
    """Sin tenencia no hay cobro: es una obviedad contable que conviene testear."""
    precios = _serie(np.linspace(100, 300, 800))  # sube siempre: nunca compra
    dividendos = _serie([1.0] * 4, inicio="2020-06-01").iloc[:4]
    dividendos.index = pd.to_datetime(["2020-06-01", "2020-09-01", "2020-12-01", "2021-03-01"])

    r = sim.simular_escalonada(precios, dividendos)

    assert r.acciones_finales == 0.0
    assert r.dividendos_cobrados == 0.0


def test_los_dividendos_entran_a_la_caja_por_cada_accion():
    idx = pd.bdate_range("2020-01-01", periods=800)
    precios = pd.Series(100.0, index=idx)  # precio fijo: aísla el efecto del dividendo
    fecha = idx[400]
    dividendos = pd.Series([2.0], index=[fecha])

    r = sim.simular_escalonada(precios, dividendos)

    cobros = [t for t in r.transacciones if t.tipo == "DIVIDENDO"]
    assert len(cobros) == 1
    assert np.isclose(cobros[0].bruto, 2.0 * cobros[0].acciones)
    assert np.isclose(r.dividendos_cobrados, cobros[0].bruto)


def test_el_nucleo_nunca_se_vende():
    """La protección contra el escenario de vender todo y quedarse afuera."""
    bajada = np.linspace(200, 100, 300)
    subida = np.linspace(100, 600, 600)
    precios = _serie(np.concatenate([bajada, subida]))

    cfg = sim.ConfigEscalonada(acciones_objetivo=100, fraccion_nucleo=0.25, fraccion_venta=0.5)
    r = sim.simular_escalonada(precios, config=cfg)

    assert r.acciones_finales >= 25.0 - 1e-6, "no puede vender por debajo del núcleo"


def test_sin_nucleo_puede_liquidar_toda_la_posicion():
    bajada = np.linspace(200, 100, 300)
    subida = np.linspace(100, 600, 600)
    precios = _serie(np.concatenate([bajada, subida]))

    cfg = sim.ConfigEscalonada(acciones_objetivo=100, fraccion_nucleo=0.0, fraccion_venta=1.0)
    r = sim.simular_escalonada(precios, config=cfg)

    assert r.acciones_finales < 1.0


def test_la_ejecucion_usa_el_precio_del_dia_siguiente():
    """La señal de hoy no se puede ejecutar al precio de hoy: ya pasó."""
    precios = _v(seed=11)
    r = sim.simular_escalonada(precios)

    for t in r.transacciones:
        if t.tipo == "DIVIDENDO":
            continue
        assert np.isclose(t.precio, float(precios.loc[t.fecha])), (
            "cada operación debe ejecutarse al precio de su propia fecha de ejecución"
        )


def test_el_oraculo_es_un_techo_que_nadie_supera():
    """Propiedad que define al oráculo: con visión perfecta no se puede hacer peor."""
    for seed in (1, 2, 3, 4, 5):
        precios = _v(seed=seed, deriva=0.0002)
        oraculo = sim.simular_oraculo(precios, 100)
        real = sim.simular_escalonada(precios, config=sim.ConfigEscalonada(acciones_objetivo=100))

        assert oraculo.retorno_pct >= real.retorno_pct - 1e-9, (
            f"semilla {seed}: la estrategia real superó al oráculo, imposible"
        )


def test_el_oraculo_compra_antes_de_vender():
    precios = _v(seed=7)
    r = sim.simular_oraculo(precios, 100)

    compra = next(t for t in r.transacciones if t.tipo == "COMPRA")
    venta = next(t for t in r.transacciones if t.tipo == "VENTA")
    assert compra.fecha < venta.fecha


def test_los_costos_reducen_el_resultado_final():
    precios = _v(seed=13)
    barato = sim.simular_escalonada(precios, costos=CostModel(0, 0, 0))
    caro = sim.simular_escalonada(precios, costos=CostModel.byma_equity())

    if barato.n_compras + barato.n_ventas > 0:
        assert caro.valor_final < barato.valor_final
        assert caro.costos_totales > barato.costos_totales


def test_el_periodo_minimo_entre_operaciones_se_respeta():
    """Sin esta restricción, la estrategia vendería varias veces en la misma semana."""
    precios = _v(seed=17)
    cfg = sim.ConfigEscalonada(dias_minimos_entre_operaciones=60)
    r = sim.simular_escalonada(precios, config=cfg)

    operaciones = [t.fecha for t in r.transacciones if t.tipo in ("COMPRA", "VENTA")]
    for anterior, siguiente in zip(operaciones, operaciones[1:]):
        assert (siguiente - anterior).days >= 60


def test_comprar_y_mantener_conserva_las_acciones_y_cobra_dividendos():
    idx = pd.bdate_range("2020-01-01", periods=600)
    precios = pd.Series(np.linspace(100, 200, 600), index=idx)
    dividendos = pd.Series([1.5, 1.5], index=[idx[100], idx[300]])

    r = sim.simular_comprar_y_mantener(precios, dividendos, acciones=100)

    assert r.acciones_finales == 100.0
    assert np.isclose(r.dividendos_cobrados, 300.0)  # 2 pagos x 1,5 x 100 acciones
    assert r.n_ventas == 0


def test_una_serie_muy_corta_falla_en_vez_de_simular_igual():
    precios = _serie(np.linspace(100, 110, 50))
    with pytest.raises(ValueError):
        sim.simular_escalonada(precios)


def test_todas_las_estrategias_arrancan_con_el_mismo_capital():
    """Regresión: comparar estrategias que empiezan en fechas distintas no sirve.

    Si una arranca antes que otra, la diferencia de resultados mide el calendario
    además de la táctica, y no se puede separar una cosa de la otra.
    """
    precios = _v(seed=31, deriva=0.001)
    cfg = sim.ConfigEscalonada(acciones_objetivo=100)
    inicio = sim.fecha_primera_senal(precios, cfg)

    escalonada = sim.simular_escalonada(precios, config=cfg)
    mantener = sim.simular_comprar_y_mantener(precios, acciones=100, desde=inicio)
    oraculo = sim.simular_oraculo(precios, 100, desde=inicio)

    assert escalonada.fecha_inicio == mantener.fecha_inicio == oraculo.fecha_inicio == inicio
    assert np.isclose(escalonada.capital_inicial, mantener.capital_inicial, rtol=1e-9)
    assert np.isclose(escalonada.capital_inicial, oraculo.capital_inicial, rtol=1e-9)


def test_una_simulacion_sin_operaciones_se_declara_como_tal():
    """No operar es un resultado, y el resumen tiene que decirlo con claridad."""
    precios = _serie(np.linspace(100, 900, 900))  # sube siempre: nunca toca el mínimo
    r = sim.simular_escalonada(precios)

    assert r.nunca_opero
    assert "NUNCA ABRIÓ POSICIÓN" in r.resumen()
    assert r.ganancia == 0.0
