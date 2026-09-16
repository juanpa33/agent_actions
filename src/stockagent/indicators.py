"""Indicadores con respaldo en literatura académica revisada por pares.

Criterio de inclusión, aplicado estrictamente: un indicador entra solo si existe
evidencia publicada de que su poder predictivo sobrevive fuera de la muestra en
la que fue descubierto. Cada función cita su referencia.

Lo que quedó AFUERA y por qué:
  - Cruces de MACD, RSI, estocástico y bandas de Bollinger con parámetros
    optimizados. La revisión de Park & Irwin (2007), "What Do We Know About the
    Profitability of Technical Analysis?", Journal of Economic Surveys 21(4),
    documenta que los resultados positivos en mercados desarrollados se
    desvanecen a partir de los años noventa y son en gran medida atribuibles al
    sesgo de data snooping.
  - Ondas de Elliott, Fibonacci, patrones chartistas. No producen reglas
    falsables, así que no son evaluables científicamente.
  - Cualquier parámetro elegido por su desempeño en estos datos. Los valores
    usados acá son los de los papers originales, no ajustados a esta muestra.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21


def log_returns(prices: pd.Series) -> pd.Series:
    """Retornos logarítmicos. Se usan por aditividad temporal, no por costumbre."""
    return np.log(prices / prices.shift(1)).dropna()


def time_series_momentum(prices: pd.Series, lookback_months: int = 12,
                         skip_months: int = 1) -> pd.Series:
    """Momentum de series de tiempo 12-1.

    Referencia: Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum",
    Journal of Financial Economics 104(2), 228-250. Documentan que el signo del
    retorno de los últimos 12 meses predice el del mes siguiente en 58 clases de
    activos y 25 años de datos.

    Se saltea el mes más reciente por el efecto de reversión de corto plazo
    identificado en Jegadeesh (1990), Journal of Finance 45(3), 881-898.
    """
    lookback = lookback_months * TRADING_DAYS_PER_MONTH
    skip = skip_months * TRADING_DAYS_PER_MONTH
    past = prices.shift(skip)
    return (past / past.shift(lookback) - 1.0).rename(f"tsmom_{lookback_months}_{skip_months}")


def trend_filter_sma(prices: pd.Series, window: int = 200) -> pd.Series:
    """Filtro de tendencia por media móvil simple: 1 si el precio está encima, 0 si no.

    Referencia: Faber (2007), "A Quantitative Approach to Tactical Asset
    Allocation", Journal of Wealth Management 9(4). La media de 200 ruedas
    (equivalente a 10 meses) no mejora el retorno: reduce la volatilidad y,
    sobre todo, la caída máxima, al mantener al inversor fuera del mercado
    durante los tramos bajistas sostenidos.

    La ventana de 200 es el valor canónico del paper. No se optimizó acá, y ese
    es el punto: un parámetro elegido por su desempeño en esta muestra sería
    ruido con apariencia de señal.
    """
    sma = prices.rolling(window, min_periods=window).mean()
    return (prices > sma).astype(float).where(sma.notna()).rename(f"trend_sma{window}")


def distance_to_52w_high(prices: pd.Series, window: int = 252) -> pd.Series:
    """Cercanía al máximo de 52 semanas, en tanto por uno.

    Referencia: George & Hwang (2004), "The 52-Week High and Momentum
    Investing", Journal of Finance 59(5), 2145-2176. La proximidad al máximo
    anual predice retornos futuros y explica buena parte del momentum
    tradicional.
    """
    high = prices.rolling(window, min_periods=window // 2).max()
    return (prices / high).rename("dist_52w_high")


def realized_volatility(returns: pd.Series, window: int = 63,
                        annualize: bool = True) -> pd.Series:
    """Volatilidad realizada por desvío estándar móvil.

    La ventana de 63 ruedas (un trimestre) equilibra capacidad de reacción y
    error de estimación. Se usa para dimensionar posiciones, no para predecir
    dirección.
    """
    vol = returns.rolling(window, min_periods=window // 2).std()
    if annualize:
        vol = vol * np.sqrt(TRADING_DAYS_PER_YEAR)
    return vol.rename(f"vol_{window}d")


def average_true_range(high: pd.Series, low: pd.Series, close: pd.Series,
                       window: int = 14) -> pd.Series:
    """Average True Range.

    Referencia: Wilder (1978), "New Concepts in Technical Trading Systems".

    ADVERTENCIA DE HONESTIDAD METODOLÓGICA: a diferencia de los demás
    indicadores de este módulo, el ATR NO tiene respaldo académico como
    predictor de retornos. Es una medida descriptiva de rango de precios, usada
    acá exclusivamente para calibrar stops en unidades de volatilidad del
    activo. No entra en la generación de señales direccionales.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean().rename(f"atr_{window}")


def cross_sectional_momentum_rank(returns_by_asset: pd.DataFrame,
                                  lookback_months: int = 12,
                                  skip_months: int = 1) -> pd.DataFrame:
    """Ranking percentil de momentum entre activos (0 = peor, 1 = mejor).

    Referencia: Jegadeesh & Titman (1993), "Returns to Buying Winners and
    Selling Losers", Journal of Finance 48(1), 65-91. Confirmado fuera de
    muestra en Jegadeesh & Titman (2001), Journal of Finance 56(2), 699-720.

    El ranking es transversal: compara cada activo contra sus pares en la misma
    fecha, de modo que el resultado no depende del nivel general del mercado.
    """
    lookback = lookback_months * TRADING_DAYS_PER_MONTH
    skip = skip_months * TRADING_DAYS_PER_MONTH
    past = returns_by_asset.shift(skip)
    momentum = past / past.shift(lookback) - 1.0
    return momentum.rank(axis=1, pct=True)


def max_drawdown(equity: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    """Caída máxima desde el pico previo, con fechas de pico y valle."""
    if equity.empty:
        return 0.0, None, None
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    trough = dd.idxmin()
    peak = equity.loc[:trough].idxmax() if trough is not None else None
    return float(dd.min()), peak, trough


def rolling_beta(asset_returns: pd.Series, market_returns: pd.Series,
                 window: int = 252) -> pd.Series:
    """Beta móvil contra un índice de referencia, por mínimos cuadrados."""
    common = asset_returns.index.intersection(market_returns.index)
    a, m = asset_returns.loc[common], market_returns.loc[common]
    cov = a.rolling(window, min_periods=window // 2).cov(m)
    var = m.rolling(window, min_periods=window // 2).var()
    return (cov / var).rename(f"beta_{window}d")
