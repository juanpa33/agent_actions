#!/usr/bin/env python3
"""Simulación en dinero: ¿cuánto hubiera ganado con 100 acciones?

Compara cuatro formas de manejar la misma posición, con los mismos datos y los
mismos costos:

  1. ORÁCULO      - comprar en el mínimo real y vender en el máximo real.
                    IMPOSIBLE de ejecutar. Es el techo teórico, y sirve para ver
                    cuánto de la "ganancia soñada" es inalcanzable por definición.
  2. ESCALONADA   - comprar cerca de mínimos, vender de a pedazos cerca de
                    máximos, recomprar en las bajas. Guarda un núcleo que nunca
                    vende.
  3. TODO O NADA  - la misma regla pero vendiendo la posición entera.
  4. COMPRAR Y MANTENER - comprar una vez y no tocar nada.

Todas cobran los dividendos que la empresa pagó realmente, en sus fechas reales.

Uso:
    python scripts/simular_acciones.py
    python scripts/simular_acciones.py --ticker NVDA --acciones 100 --anios 2
    python scripts/simular_acciones.py --ticker NVDA --anios 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from stockagent import simulation as sim  # noqa: E402
from stockagent.backtest import CostModel  # noqa: E402
from stockagent.datasources import yahoo  # noqa: E402
from stockagent.pipeline import default_window  # noqa: E402
from stockagent.provenance import MissingDataError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulación de una posición en dinero")
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--acciones", type=int, default=100)
    parser.add_argument("--anios", type=float, default=2.0)
    parser.add_argument("--fraccion-venta", type=float, default=0.25,
                        help="Qué porción se vende en cada toma de ganancia")
    parser.add_argument("--nucleo", type=float, default=0.25,
                        help="Porción de la posición que nunca se vende")
    parser.add_argument("--salida", default=str(ROOT / "reports" / "simulacion.md"))
    args = parser.parse_args()

    start, end = default_window(args.anios)
    print(f"Descargando {args.ticker} ({start} a {end}) ...")

    try:
        precios_t, dividendos_t = yahoo.fetch_prices_and_dividends(args.ticker, start, end)
    except MissingDataError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        print("No se simula con datos inventados. Revisá la conectividad.", file=sys.stderr)
        return 1

    precios = precios_t.data["close"]
    dividendos = dividendos_t.data
    costos = CostModel.byma_equity() if args.ticker.endswith(".BA") else CostModel.us_equity()
    moneda = "ARS" if args.ticker.endswith(".BA") else "USD"

    print(f"  {len(precios)} ruedas, de {precios.index[0]:%Y-%m-%d} a {precios.index[-1]:%Y-%m-%d}")
    print(f"  Precio: {precios.iloc[0]:,.2f} -> {precios.iloc[-1]:,.2f} "
          f"({(precios.iloc[-1] / precios.iloc[0] - 1) * 100:+.1f}%)")
    print(f"  Dividendos pagados en el período: {len(dividendos)}"
          + (f", total {dividendos.sum():,.4f} por acción" if len(dividendos) else ""))
    print()

    # Fecha común de arranque: todas las estrategias deben partir del mismo día
    # y con el mismo capital, o la comparación mide el calendario y no la táctica.
    cfg_base = sim.ConfigEscalonada(acciones_objetivo=args.acciones)
    try:
        inicio_comun = sim.fecha_primera_senal(precios, cfg_base)
    except ValueError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    print(f"  Todas las estrategias arrancan el {inicio_comun:%Y-%m-%d} "
          f"(precio {precios.loc[inicio_comun]:,.2f}), con el mismo capital.")
    print()

    resultados = []

    # 1. El techo imposible
    oraculo = sim.simular_oraculo(precios, args.acciones, costos, desde=inicio_comun)
    resultados.append(oraculo)

    # 2. Escalonada: vende de a pedazos y recompra
    cfg_escalonada = sim.ConfigEscalonada(
        acciones_objetivo=args.acciones,
        fraccion_venta=args.fraccion_venta,
        fraccion_nucleo=args.nucleo,
    )
    escalonada = sim.simular_escalonada(precios, dividendos, cfg_escalonada, costos)
    resultados.append(escalonada)

    # 3. Todo o nada: misma regla, vende la posición entera
    cfg_todo = sim.ConfigEscalonada(
        acciones_objetivo=args.acciones, fraccion_venta=1.0, fraccion_nucleo=0.0,
    )
    todo_o_nada = sim.simular_escalonada(
        precios, dividendos, cfg_todo, costos, nombre="Todo o nada (vende la posición entera)"
    )
    resultados.append(todo_o_nada)

    # 4. Comprar y mantener, desde la misma fecha y con el mismo capital
    comprar_mantener = sim.simular_comprar_y_mantener(
        precios, dividendos, args.acciones, costos, desde=inicio_comun
    )
    resultados.append(comprar_mantener)

    print("=" * 74)
    print(f" SIMULACIÓN: {args.acciones} acciones de {args.ticker}")
    print("=" * 74)
    print()
    for r in resultados:
        print(r.resumen(moneda))
        print()

    print("-" * 74)
    print(" COMPARACIÓN")
    print("-" * 74)
    referencia = comprar_mantener.valor_final
    for r in resultados:
        delta = r.valor_final - referencia
        marca = "" if r is comprar_mantener else f"  ({delta:+,.2f} vs comprar y mantener)"
        print(f" {r.nombre[:46]:<46} {moneda} {r.valor_final:>13,.2f}{marca}")
    print()

    brecha = oraculo.valor_final - escalonada.valor_final
    print(f" Lo que cuesta NO ser adivino: {moneda} {brecha:,.2f}")
    print(f" El oráculo logra {oraculo.retorno_pct * 100:+.1f}% y la estrategia real "
          f"{escalonada.retorno_pct * 100:+.1f}%.")
    print()

    print("-" * 74)
    print(" LIBRO DE OPERACIONES - Escalonada")
    print("-" * 74)
    print(escalonada.libro())
    print()

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(_reporte(args, resultados, moneda, precios, dividendos), encoding="utf-8")
    print(f"Reporte guardado en: {salida}")
    return 0


def _reporte(args, resultados, moneda, precios, dividendos) -> str:
    oraculo, escalonada, todo_o_nada, comprar_mantener = resultados
    out = [
        f"# Simulación: {args.acciones} acciones de {args.ticker}",
        "",
        "> No es asesoramiento financiero. Es una simulación sobre datos históricos.",
        "",
        f"Período: {precios.index[0]:%Y-%m-%d} a {precios.index[-1]:%Y-%m-%d} "
        f"({len(precios)} ruedas)  ",
        f"Precio: {moneda} {precios.iloc[0]:,.2f} → {moneda} {precios.iloc[-1]:,.2f} "
        f"({(precios.iloc[-1] / precios.iloc[0] - 1) * 100:+.1f}%)  ",
        f"Dividendos pagados: {len(dividendos)}"
        + (f" (total {moneda} {dividendos.sum():,.4f} por acción)" if len(dividendos) else ""),
        "",
        "## Resultados",
        "",
        f"| Estrategia | Capital inicial | Valor final | Ganancia | % | Dividendos | Costos | Oper. |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in resultados:
        out.append(
            f"| {r.nombre} | {r.capital_inicial:,.0f} | {r.valor_final:,.0f} | "
            f"**{r.ganancia:+,.0f}** | {r.retorno_pct * 100:+.1f}% | "
            f"{r.dividendos_cobrados:,.2f} | {r.costos_totales:,.2f} | "
            f"{r.n_compras + r.n_ventas} |"
        )

    brecha = oraculo.valor_final - escalonada.valor_final
    out += [
        "",
        "## Lectura",
        "",
        f"**El oráculo es inalcanzable.** Compra en el mínimo real y vende en el "
        f"máximo real, cosa que solo se puede hacer mirando el gráfico terminado. "
        f"La diferencia contra la estrategia ejecutable es de {moneda} "
        f"{brecha:,.2f}: eso es lo que cuesta no ser adivino, y no hay técnica que "
        f"lo recupere.",
        "",
    ]

    delta_esc = escalonada.valor_final - comprar_mantener.valor_final
    if delta_esc > 0:
        out.append(
            f"**La escalonada le ganó a comprar y mantener** por {moneda} {delta_esc:,.2f}."
        )
    else:
        out.append(
            f"**La escalonada NO le ganó a comprar y mantener**: quedó {moneda} "
            f"{abs(delta_esc):,.2f} por debajo, después de {escalonada.n_compras + escalonada.n_ventas} "
            f"operaciones y {moneda} {escalonada.costos_totales:,.2f} en costos. "
            f"Todo ese trabajo destruyó valor en lugar de crearlo."
        )

    delta_todo = escalonada.valor_final - todo_o_nada.valor_final
    out += [
        "",
        f"**Vender de a pedazos contra vender todo:** la escalonada terminó "
        f"{moneda} {delta_todo:+,.2f} respecto de liquidar la posición entera. "
        f"Guardar un núcleo protege del escenario en que la regla de venta se "
        f"equivoca y el activo sigue subiendo sin vos.",
        "",
        "## Libro de operaciones — Escalonada",
        "",
        "```",
        escalonada.libro(maximo=60),
        "```",
        "",
        "## Advertencias",
        "",
        "- Un solo camino histórico no permite distinguir habilidad de suerte. "
        "Este resultado es lo que pasó, no lo que pasará.",
        "- Los costos usados son estimaciones. Reemplazalos por los de tu comitente.",
        "- **No se modelan impuestos.** En Argentina pueden cambiar el resultado neto "
        "de forma sustancial, y el tratamiento difiere entre acción local, ADR y "
        "dividendos.",
        "- Los precios NO están ajustados por dividendos, justamente para poder "
        "sumarlos como plata que entra. Por eso no coinciden con los gráficos que "
        "muestran precio ajustado.",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
