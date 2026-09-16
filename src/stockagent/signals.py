"""Combinación de señales en una decisión long-only con salida a efectivo.

Decisión de diseño deliberada: las señales se combinan con PESOS IGUALES, no
con pesos optimizados sobre los datos históricos.

El motivo es estadístico, no estético. Optimizar los pesos sobre una muestra de
dos años (~500 observaciones) con varias señales consume los grados de libertad
disponibles y produce una combinación ajustada al ruido de esa muestra en
particular. La evidencia de que las combinaciones simples e iguales resisten
mejor fuera de muestra está en DeMiguel, Garlappi & Uppal (2009), "Optimal
Versus Naive Diversification", Review of Financial Studies 22(5), 1915-1953:
la regla ingenua 1/N supera consistentemente a los esquemas optimizados una vez
que se contabiliza el error de estimación.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class SignalConfig:
    """Parámetros de las señales, todos tomados de los papers originales.

    Ningún valor de esta clase fue elegido por su desempeño en los datos de este
    proyecto. Cambiarlos para mejorar el backtest es exactamente el
    procedimiento que invalida el backtest.
    """

    momentum_lookback_months: int = 12  # Moskowitz, Ooi & Pedersen (2012)
    momentum_skip_months: int = 1       # Jegadeesh (1990)
    trend_sma_window: int = 200         # Faber (2007)
    high_52w_window: int = 252          # George & Hwang (2004)
    high_52w_threshold: float = 0.75    # umbral estructural: 25% por debajo del máximo
    vote_threshold: float = 0.60        # mayoría de señales de acuerdo
    vol_window: int = 63


@dataclass
class SignalSet:
    """Señales individuales y su agregación, para un activo."""

    ticker: str
    momentum: pd.Series
    trend: pd.Series
    near_high: pd.Series
    composite: pd.Series
    position_flag: pd.Series
    config: SignalConfig = field(default_factory=SignalConfig)

    def latest_breakdown(self) -> dict[str, object]:
        """Estado de cada señal en la última fecha disponible, para el reporte."""
        if self.composite.dropna().empty:
            return {"ticker": self.ticker, "estado": "SIN DATOS SUFICIENTES"}

        last = self.composite.dropna().index[-1]
        return {
            "ticker": self.ticker,
            "fecha": last.strftime("%Y-%m-%d"),
            "momentum_12_1": _safe(self.momentum, last),
            "momentum_vota": _vote_label(self.momentum, last, lambda v: v > 0),
            "sobre_sma200": _vote_label(self.trend, last, lambda v: v > 0.5),
            "cercania_max_52s": _safe(self.near_high, last),
            "cerca_del_maximo_vota": _vote_label(
                self.near_high, last, lambda v: v >= self.config.high_52w_threshold
            ),
            "score_compuesto": _safe(self.composite, last),
            "decision": "COMPRAR/MANTENER" if self.position_flag.get(last, 0) > 0 else "EFECTIVO",
        }


def build_signals(prices: pd.Series, ticker: str, config: SignalConfig | None = None) -> SignalSet:
    """Calcula las tres señales y su voto agregado sobre una serie de precios.

    Todas las señales en la fecha t usan exclusivamente información disponible
    hasta el cierre de t. La ejecución se difiere a t+1 en el backtest.
    """
    cfg = config or SignalConfig()

    momentum = ind.time_series_momentum(
        prices, cfg.momentum_lookback_months, cfg.momentum_skip_months
    )
    trend = ind.trend_filter_sma(prices, cfg.trend_sma_window)
    near_high = ind.distance_to_52w_high(prices, cfg.high_52w_window)

    votes = pd.DataFrame(
        {
            "momentum": (momentum > 0).astype(float).where(momentum.notna()),
            "trend": trend,
            "near_high": (near_high >= cfg.high_52w_threshold)
            .astype(float)
            .where(near_high.notna()),
        }
    )

    # Se exige que las tres señales estén definidas: un voto calculado sobre un
    # subconjunto de señales no es comparable con uno calculado sobre todas.
    composite = votes.mean(axis=1).where(votes.notna().all(axis=1)).rename("score")
    position_flag = (composite >= cfg.vote_threshold).astype(float).where(composite.notna())

    return SignalSet(
        ticker=ticker,
        momentum=momentum,
        trend=trend,
        near_high=near_high,
        composite=composite,
        position_flag=position_flag,
        config=cfg,
    )


def volatility_target_weight(returns: pd.Series, target_annual_vol: float = 0.15,
                             window: int = 63, max_weight: float = 1.0) -> pd.Series:
    """Peso de la posición inversamente proporcional a la volatilidad realizada.

    Referencia: Moreira & Muir (2017), "Volatility-Managed Portfolios", Journal
    of Finance 72(4), 1611-1644. Reducir exposición cuando la volatilidad sube
    mejora el Sharpe, porque la volatilidad es persistente y predecible mientras
    que los retornos esperados no lo son en la misma medida.

    El tope en `max_weight` impide apalancamiento: es un requisito del perfil
    conservador, no una elección estadística.
    """
    vol = ind.realized_volatility(returns, window=window, annualize=True)
    weight = (target_annual_vol / vol).clip(upper=max_weight)
    return weight.where(vol.notna() & (vol > 0)).rename("peso_vol_target")


def apply_atr_stop(prices: pd.Series, high: pd.Series, low: pd.Series,
                   position_flag: pd.Series, atr_multiple: float = 3.0,
                   atr_window: int = 14) -> pd.Series:
    """Aplica un stop por volatilidad: sale a efectivo si el precio cae N ATR desde el pico.

    El stop se mide en unidades de volatilidad propia del activo y no en un
    porcentaje fijo, porque un 8% significa cosas muy distintas en NVDA que en
    una acción de BYMA.

    Advertencia metodológica: la evidencia académica sobre stops es ambigua.
    Reducen la caída máxima pero también recortan ganancias al salir en retrocesos
    transitorios. Se incluye porque el perfil elegido es conservador, no porque
    haya prueba de que mejore el retorno esperado.
    """
    atr = ind.average_true_range(high, low, prices, window=atr_window)

    result = position_flag.copy()
    in_position = False
    stopped_out = False
    peak = np.nan

    for ts in position_flag.index:
        flag = position_flag.get(ts, np.nan)
        price = prices.get(ts, np.nan)
        current_atr = atr.get(ts, np.nan)

        if np.isnan(flag) or np.isnan(price):
            result.loc[ts] = np.nan
            continue

        if flag <= 0:
            # La señal de entrada se apagó: se libera el bloqueo y una futura
            # señal puede volver a abrir posición.
            in_position, stopped_out, peak = False, False, np.nan
        elif in_position:
            peak = max(peak, price)
            if not np.isnan(current_atr) and price < peak - atr_multiple * current_atr:
                in_position, stopped_out, peak = False, True, np.nan
        elif not stopped_out:
            in_position, peak = True, price
        # Si `stopped_out` sigue activo con la señal encendida, NO se reingresa:
        # un stop que vuelve a comprar al día siguiente no protege de nada, solo
        # paga costos. La reentrada exige que la señal se apague y vuelva a
        # encenderse, lo que confirma una nueva tendencia en lugar de un rebote.

        result.loc[ts] = 1.0 if in_position else 0.0

    return result.rename("posicion_con_stop")


def _safe(series: pd.Series, ts) -> float:
    value = series.get(ts, np.nan)
    return float(value) if not pd.isna(value) else float("nan")


def _vote_label(series: pd.Series, ts, predicate) -> str:
    value = series.get(ts, np.nan)
    if pd.isna(value):
        return "sin dato"
    return "SÍ" if predicate(value) else "NO"
