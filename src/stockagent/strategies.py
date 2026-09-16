"""Catálogo de estrategias comparables entre sí.

Todas exponen la misma interfaz —serie de precios entra, señal de posición
sale— para que la comparación sea justa: mismos costos, misma ejecución
diferida, misma vara estadística. Si dos estrategias se evalúan con criterios
distintos, la comparación no dice nada.

Ninguna estrategia de este módulo permite posiciones cortas ni apalancamiento:
la posición es 1 (invertido) o 0 (efectivo), acorde al perfil conservador.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import signals as sg


@dataclass
class MeanReversionConfig:
    """Parámetros de la estrategia de reversión a la media.

    Implementa literalmente la regla intuitiva: comprar cuando el precio está
    cerca de su mínimo, vender cuando llega cerca de su máximo.
    """

    buy_within_pct_of_low: float = 0.10
    """Comprar cuando el precio está a un 10% o menos por encima del mínimo."""

    sell_within_pct_of_high: float = 0.95
    """Vender cuando el precio alcanza el 95% o más de su máximo."""

    lookback: str | int = "expanding"
    """'expanding' usa el mínimo y máximo HISTÓRICOS (toda la historia previa,
    que es el sentido literal de 'mínimo histórico'). Un entero usa una ventana
    móvil de esa cantidad de ruedas, p.ej. 252 para mínimos y máximos del año."""

    min_history: int = 252


@dataclass
class StrategyResult:
    name: str
    description: str
    reference: str
    position: pd.Series


def momentum_trend(prices: pd.Series, config: sg.SignalConfig | None = None) -> StrategyResult:
    """Momentum con filtro de tendencia: la estrategia original del sistema.

    Compra cuando al menos 2 de 3 señales coinciden en que el activo viene
    subiendo. Es, deliberadamente, lo contrario de comprar barato: compra caro
    con la hipótesis de que siga subiendo.
    """
    signal_set = sg.build_signals(prices, "estrategia", config)
    return StrategyResult(
        name="Momentum + tendencia",
        description=(
            "Compra cuando 2 de 3 señales de tendencia coinciden (momentum 12-1, "
            "precio sobre SMA200, cerca del máximo de 52 semanas). Efectivo si no."
        ),
        reference="Moskowitz, Ooi & Pedersen (2012); Faber (2007); George & Hwang (2004)",
        position=signal_set.position_flag,
    )


def mean_reversion(prices: pd.Series, config: MeanReversionConfig | None = None) -> StrategyResult:
    """Reversión a la media: comprar cerca de mínimos, vender cerca de máximos.

    Máquina de estados con tres reglas:
      1. Sin posición y el precio está a menos de X% del mínimo -> COMPRAR.
      2. Con posición y el precio alcanza el Y% del máximo -> VENDER.
      3. En cualquier otro caso -> mantener lo que se venía haciendo.

    Nota importante sobre la evidencia: la reversión a la media está documentada
    en De Bondt & Thaler (1985), "Does the Stock Market Overreact?", Journal of
    Finance 40(3), 793-805. Pero allí el efecto aparece en horizontes de 3 a 5
    AÑOS y sobre CARTERAS de decenas de papeles, no sobre acciones individuales
    en plazos de semanas. Esta implementación aplica la regla al horizonte y al
    activo individual que el usuario pidió evaluar, que no son las condiciones
    del estudio original. El backtest existe justamente para medir esa
    diferencia en vez de discutirla.

    Los mínimos y máximos se calculan SOLO con información disponible hasta cada
    fecha: `expanding()` incluye el dato del día pero ninguno posterior.
    """
    cfg = config or MeanReversionConfig()

    if cfg.lookback == "expanding":
        low = prices.expanding(min_periods=cfg.min_history).min()
        high = prices.expanding(min_periods=cfg.min_history).max()
        ventana = "histórico (toda la historia previa)"
    else:
        window = int(cfg.lookback)
        low = prices.rolling(window, min_periods=window).min()
        high = prices.rolling(window, min_periods=window).max()
        ventana = f"ventana móvil de {window} ruedas"

    dist_from_low = prices / low - 1.0       # 0 = está exactamente en el mínimo
    frac_of_high = prices / high             # 1 = está exactamente en el máximo

    position = pd.Series(np.nan, index=prices.index, name="posicion_reversion")
    in_position = False

    for ts in prices.index:
        d_low, f_high = dist_from_low.get(ts, np.nan), frac_of_high.get(ts, np.nan)

        if np.isnan(d_low) or np.isnan(f_high):
            position.loc[ts] = np.nan
            continue

        if not in_position and d_low <= cfg.buy_within_pct_of_low:
            in_position = True
        elif in_position and f_high >= cfg.sell_within_pct_of_high:
            in_position = False

        position.loc[ts] = 1.0 if in_position else 0.0

    return StrategyResult(
        name="Reversión a la media",
        description=(
            f"Compra cuando el precio está a menos de {cfg.buy_within_pct_of_low:.0%} "
            f"por encima del mínimo {ventana}; vende cuando alcanza el "
            f"{cfg.sell_within_pct_of_high:.0%} del máximo."
        ),
        reference="De Bondt & Thaler (1985) — advertencia: validado a 3-5 años sobre carteras",
        position=position,
    )


def buy_and_hold(prices: pd.Series) -> StrategyResult:
    """Comprar y no tocar nada.

    Es el comparador que de verdad importa. Una estrategia que no le gana a esto
    no justifica su complejidad, su riesgo operativo ni sus costos: podés
    obtener el mismo resultado comprando una vez y yéndote a dormir.
    """
    return StrategyResult(
        name="Comprar y mantener",
        description="Comprado el 100% del tiempo. Sin operaciones ni decisiones.",
        reference="Comparador de referencia",
        position=pd.Series(1.0, index=prices.index, name="posicion_bh"),
    )


@dataclass
class StrategyCatalog:
    """Conjunto de estrategias que se comparan en una corrida.

    La cantidad de estrategias acá es lo que hay que declarar como
    `configuraciones_evaluadas` en el Deflated Sharpe: probar tres y declarar
    una infla la significancia del resultado.
    """

    signal_config: sg.SignalConfig = field(default_factory=sg.SignalConfig)
    reversion_config: MeanReversionConfig = field(default_factory=MeanReversionConfig)

    def build_all(self, prices: pd.Series) -> list[StrategyResult]:
        return [
            momentum_trend(prices, self.signal_config),
            mean_reversion(prices, self.reversion_config),
            buy_and_hold(prices),
        ]

    @property
    def n_strategies(self) -> int:
        return 3
