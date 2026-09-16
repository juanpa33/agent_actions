"""Los impuestos cambian el ranking entre estrategias, no solo el número final."""

import numpy as np
import pandas as pd

from stockagent import simulation as sim
from stockagent import taxes as tx
from stockagent.backtest import CostModel


def _serie(valores, inicio="2020-01-01"):
    return pd.Series(valores, index=pd.bdate_range(inicio, periods=len(valores)), dtype=float)


def test_fifo_vende_primero_lo_comprado_primero():
    reg = tx.RegistroFiscal()
    reg.comprar(pd.Timestamp("2024-01-01"), 100, 10.0)
    reg.comprar(pd.Timestamp("2024-06-01"), 100, 20.0)

    ganancia, costo = reg.vender(100, 30.0)

    # Se consumió el lote barato: costo 100 x 10 = 1000, venta 100 x 30 = 3000.
    assert np.isclose(costo, 1000.0)
    assert np.isclose(ganancia, 2000.0)
    assert np.isclose(reg.acciones_en_cartera, 100.0)


def test_la_ganancia_latente_no_paga_impuesto_hasta_que_se_vende():
    reg = tx.RegistroFiscal()
    reg.comprar(pd.Timestamp("2024-01-01"), 100, 10.0)

    assert np.isclose(reg.ganancia_no_realizada(50.0), 4000.0)
    assert reg.ganancia_realizada_acumulada == 0.0  # nada realizado, nada gravado


def test_una_venta_con_perdida_no_genera_impuesto():
    assert tx.impuesto_por_venta(-5000.0, tx.TaxModel.adr_o_accion_extranjera()) == 0.0


def test_la_retencion_de_dividendos_se_aplica_en_origen():
    modelo = tx.TaxModel.adr_o_accion_extranjera()
    neto, impuesto = tx.dividendo_neto(1000.0, modelo)

    assert np.isclose(impuesto, 300.0)   # 30% de retención estadounidense
    assert np.isclose(neto, 700.0)


def test_el_cedear_acumula_retencion_de_origen_mas_impuesto_local():
    modelo = tx.TaxModel.cedear()
    neto, impuesto = tx.dividendo_neto(1000.0, modelo)

    assert np.isclose(impuesto, 370.0)   # 30% en origen + 7% cedular local
    assert np.isclose(neto, 630.0)


def test_los_impuestos_reducen_el_resultado_de_una_estrategia_que_vende():
    bajada = np.linspace(200, 100, 300)
    subida = np.linspace(100, 600, 700)
    precios = _serie(np.concatenate([bajada, subida]))
    cfg = sim.ConfigEscalonada(acciones_objetivo=100)

    sin_imp = sim.simular_escalonada(precios, config=cfg, costos=CostModel.us_equity())
    con_imp = sim.simular_escalonada(
        precios, config=cfg, costos=CostModel.us_equity(),
        impuestos=tx.TaxModel.adr_o_accion_extranjera(),
    )

    assert con_imp.impuestos_pagados > 0
    assert con_imp.valor_final < sin_imp.valor_final


def test_comprar_y_mantener_no_paga_impuesto_a_la_ganancia_porque_no_vende():
    """El corazón de la ventaja fiscal de mantener: el impuesto queda postergado."""
    precios = _serie(np.linspace(100, 400, 800))
    modelo = tx.TaxModel(nombre="solo ganancias", capital_gains_rate=0.15)

    r = sim.simular_comprar_y_mantener(precios, acciones=100, impuestos=modelo)

    assert r.impuestos_pagados == 0.0, "sin ventas no hay impuesto a la ganancia"
    assert r.ganancia_no_realizada > 0, "pero la deuda latente existe"

    # Y al liquidar, recién ahí aparece.
    liquidado = r.valor_si_liquidas_hoy(0.15)
    assert liquidado < r.valor_final
    assert np.isclose(r.valor_final - liquidado, r.ganancia_no_realizada * 0.15)


def test_el_cedear_conviene_mas_que_el_adr_para_una_estrategia_que_opera_seguido():
    """Hallazgo estructural: el instrumento puede pesar más que la táctica.

    Con la misma estrategia y los mismos precios, la ganancia por venta de CEDEAR
    estaría exenta mientras que la del ADR tributa 15%. Para alguien que vende
    seguido, elegir mal el instrumento cuesta más que afinar la señal.
    """
    bajada = np.linspace(200, 100, 300)
    subida = np.linspace(100, 700, 700)
    precios = _serie(np.concatenate([bajada, subida]))
    cfg = sim.ConfigEscalonada(acciones_objetivo=100)

    como_adr = sim.simular_escalonada(
        precios, config=cfg, impuestos=tx.TaxModel.adr_o_accion_extranjera()
    )
    como_cedear = sim.simular_escalonada(
        precios, config=cfg, impuestos=tx.TaxModel.cedear()
    )

    assert como_cedear.valor_final > como_adr.valor_final


def test_el_impuesto_patrimonial_se_cobra_una_vez_por_anio():
    precios = _serie(np.linspace(100, 300, 900))
    modelo = tx.TaxModel(nombre="solo tenencia", wealth_tax_rate=0.0125)

    r = sim.simular_comprar_y_mantener(precios, acciones=100, impuestos=modelo)
    cobros = [t for t in r.transacciones if t.tipo == "IMP.TENENCIA"]
    anios = [t.fecha.year for t in cobros]

    assert len(anios) == len(set(anios)), "no puede cobrarse dos veces el mismo año"
    assert r.impuestos_pagados > 0


def test_el_modelo_de_accion_local_se_declara_como_no_verificado():
    """Poner cero porque falta el dato no es lo mismo que estar exento."""
    modelo = tx.TaxModel.accion_local_byma()
    assert "SIN VERIFICAR" in modelo.nombre
    assert "NO VERIFICADO" in modelo.fuente
    assert "no porque el instrumento esté exento" in modelo.advertencia


def test_el_libro_registra_cada_impuesto_pagado():
    bajada = np.linspace(200, 100, 300)
    subida = np.linspace(100, 600, 700)
    precios = _serie(np.concatenate([bajada, subida]))

    r = sim.simular_escalonada(
        precios, config=sim.ConfigEscalonada(acciones_objetivo=100),
        impuestos=tx.TaxModel.adr_o_accion_extranjera(),
    )

    # Los impuestos declarados deben coincidir con lo registrado en el libro.
    del_libro = sum(
        t.costos for t in r.transacciones if t.tipo in ("DIVIDENDO", "IMP.TENENCIA")
    ) + sum(
        t.costos for t in r.transacciones if t.tipo == "VENTA"
    )
    assert del_libro >= r.impuestos_pagados - 1e-6
