#!/usr/bin/env python3
"""Experimento controlado: ¿en qué tipo de mercado gana cada estrategia?

QUÉ ES ESTO Y QUÉ NO ES
=======================
Esto NO dice nada sobre NVIDIA, YPF ni ningún activo real. Usa series
SINTÉTICAS generadas con propiedades matemáticas conocidas.

Para qué sirve entonces: para responder una pregunta que los datos de mercado
NO pueden responder bien. Con datos reales tenemos un solo camino histórico, y
un solo camino no permite distinguir habilidad de suerte. Acá se simulan
cientos de caminos por cada tipo de mercado, así que se puede medir con qué
FRECUENCIA gana cada estrategia, no solo si ganó una vez.

Es la misma lógica de un ensayo clínico: no alcanza con un paciente que mejoró.

Los tres regímenes simulados:
  1. TENDENCIAL      — deriva positiva sostenida (una empresa en crecimiento)
  2. LATERAL         — oscila alrededor de un valor fijo (rango, sin tendencia)
  3. DECADENCIA      — deriva negativa sostenida (un negocio que se deteriora)

Uso:
    python scripts/experimento_estrategias.py
    python scripts/experimento_estrategias.py --caminos 500
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from stockagent import backtest as bt  # noqa: E402
from stockagent import compare as cmp  # noqa: E402
from stockagent import strategies as strat  # noqa: E402

DIAS = 1500          # ~6 años, para que los indicadores tengan margen de arranque
POR_ANIO = 252


def camino_tendencial(rng, n=DIAS, mu=0.25, sigma=0.35):
    """Movimiento browniano geométrico con deriva positiva."""
    dt = 1.0 / POR_ANIO
    shocks = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), n)
    return 100.0 * np.exp(np.cumsum(shocks))


def camino_lateral(rng, n=DIAS, media_log=np.log(100.0), vida_media=60, sigma=0.30):
    """Proceso de Ornstein-Uhlenbeck: el precio vuelve a su valor central.

    Es el único de los tres regímenes donde la reversión a la media es una
    propiedad REAL de la serie, no una esperanza del que opera.
    """
    dt = 1.0 / POR_ANIO
    theta = np.log(2.0) / (vida_media * dt)  # velocidad de retorno a la media
    x = np.empty(n)
    x[0] = media_log
    ruido = rng.normal(0.0, 1.0, n)
    for t in range(1, n):
        x[t] = x[t - 1] + theta * (media_log - x[t - 1]) * dt + sigma * np.sqrt(dt) * ruido[t]
    return np.exp(x)


def camino_decadencia(rng, n=DIAS, mu=-0.20, sigma=0.40):
    """Deriva negativa sostenida: el negocio se deteriora de verdad.

    Es el escenario que pone a prueba la regla de comprar cerca de mínimos: acá
    cada nuevo mínimo es seguido por otro más bajo.
    """
    dt = 1.0 / POR_ANIO
    shocks = rng.normal((mu - 0.5 * sigma**2) * dt, sigma * np.sqrt(dt), n)
    return 100.0 * np.exp(np.cumsum(shocks))


REGIMENES = {
    "TENDENCIAL (deriva +25%/año)": camino_tendencial,
    "LATERAL (oscila, sin tendencia)": camino_lateral,
    "DECADENCIA (deriva -20%/año)": camino_decadencia,
}


def correr_un_camino(precios: pd.Series, catalogo, costos):
    """Corre las tres estrategias sobre un camino y devuelve sus retornos netos."""
    salidas = {}
    for estrategia in catalogo.build_all(precios):
        pesos = None
        resultado = bt.run_backtest(precios, estrategia.position, pesos, costos, rebalance="W-FRI")
        salidas[estrategia.name] = {
            "retorno": resultado.net_return,
            "sharpe": resultado.sharpe,
            "caida_max": resultado.max_drawdown,
            "operaciones": resultado.trades,
            "tiempo_invertido": resultado.time_in_market,
            # Una estrategia que nunca abre posición no tiene Sharpe definido.
            # No es un error de cálculo: es que no operó, y hay que decirlo.
            "nunca_opero": 1.0 if resultado.time_in_market == 0.0 else 0.0,
        }
    return salidas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caminos", type=int, default=200)
    parser.add_argument("--semilla", type=int, default=20260916)
    args = parser.parse_args()

    catalogo = strat.StrategyCatalog()
    costos = bt.CostModel.us_equity()
    nombres = ["Momentum + tendencia", "Reversión a la media", "Comprar y mantener"]

    print("=" * 78)
    print(" EXPERIMENTO CONTROLADO SOBRE SERIES SINTÉTICAS")
    print("=" * 78)
    print()
    print(" Estos números NO describen a NVIDIA, YPF ni ningún activo real.")
    print(" Son series simuladas con propiedades matemáticas conocidas, para medir")
    print(" en qué tipo de mercado funciona cada estrategia y con qué frecuencia.")
    print()
    print(f" Caminos simulados por régimen: {args.caminos}")
    print(f" Duración de cada camino: {DIAS} ruedas (~6 años)")
    print(f" Costos aplicados: {costos.total_one_way * 100:.2f}% por operación")
    print()

    resumen_global = {}

    for titulo, generador in REGIMENES.items():
        rng = np.random.default_rng(args.semilla)
        acumulado = {n: {"retorno": [], "sharpe": [], "caida_max": [], "operaciones": [],
                         "tiempo_invertido": [], "nunca_opero": []} for n in nombres}

        for _ in range(args.caminos):
            valores = generador(rng)
            idx = pd.bdate_range("2019-01-01", periods=len(valores))
            precios = pd.Series(valores, index=idx)
            for nombre, metricas in correr_un_camino(precios, catalogo, costos).items():
                for clave, valor in metricas.items():
                    acumulado[nombre][clave].append(valor)

        print("-" * 78)
        print(f" RÉGIMEN: {titulo}")
        print("-" * 78)
        print(f" {'Estrategia':<24} {'Retorno mediano':>16} {'Sharpe med.':>12} "
              f"{'Caída máx.':>11} {'Oper.':>7} {'Sin operar':>11}")

        medianas = {}
        for nombre in nombres:
            datos = acumulado[nombre]
            ret = float(np.median(datos["retorno"]))
            medianas[nombre] = ret
            sharpe_med = float(np.nanmedian(datos["sharpe"]))
            sin_operar = float(np.mean(datos["nunca_opero"]))
            sharpe_txt = f"{sharpe_med:>12.2f}" if not np.isnan(sharpe_med) else f"{'s/d':>12}"
            print(f" {nombre:<24} {ret * 100:>15.1f}% {sharpe_txt} "
                  f"{np.median(datos['caida_max']) * 100:>10.1f}% "
                  f"{np.median(datos['operaciones']):>7.0f} "
                  f"{sin_operar * 100:>10.0f}%")

        # Con qué frecuencia cada estrategia activa le gana a comprar y mantener.
        # Una mediana favorable no alcanza: importa la consistencia.
        bh = np.array(acumulado["Comprar y mantener"]["retorno"])
        print()
        for nombre in nombres[:2]:
            activa = np.array(acumulado[nombre]["retorno"])
            gana_bh = float((activa > bh).mean())
            print(f" {nombre} le gana a comprar y mantener en "
                  f"{gana_bh * 100:.0f}% de los caminos")

        for nombre in nombres[:2]:
            sin_operar = float(np.mean(acumulado[nombre]["nunca_opero"]))
            if sin_operar > 0.05:
                print(f" AVISO: {nombre} no llegó a abrir posición en "
                      f"{sin_operar * 100:.0f}% de los caminos (quedó en efectivo todo el período)")

        mom = np.array(acumulado["Momentum + tendencia"]["retorno"])
        rev = np.array(acumulado["Reversión a la media"]["retorno"])
        print(f" Momentum le gana a Reversión en {float((mom > rev).mean()) * 100:.0f}% de los caminos")
        print()

        resumen_global[titulo] = {
            "medianas": medianas,
            "mom_vs_rev": float((mom > rev).mean()),
            "mom_vs_bh": float((mom > bh).mean()),
            "rev_vs_bh": float((rev > bh).mean()),
        }

    print("=" * 78)
    print(" CONCLUSIÓN DEL EXPERIMENTO")
    print("=" * 78)
    print()
    for titulo, datos in resumen_global.items():
        ganadora = max(datos["medianas"].items(), key=lambda kv: kv[1])
        print(f" {titulo}")
        print(f"   Mejor por retorno mediano: {ganadora[0]} ({ganadora[1] * 100:+.1f}%)")
        print(f"   Momentum supera a Reversión en {datos['mom_vs_rev'] * 100:.0f}% de los caminos")
        print()

    print(" Recordatorio: esto mide el COMPORTAMIENTO de las estrategias según el")
    print(" tipo de mercado. Para saber a qué régimen se parecen NVIDIA o YPF hay")
    print(" que correr el análisis sobre sus datos reales.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
