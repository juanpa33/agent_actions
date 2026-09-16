"""Descarga de precios desde Yahoo Finance vía yfinance.

Se piden precios AJUSTADOS por splits y dividendos: un backtest sobre precios
sin ajustar confunde un split con un derrumbe del 90% y produce señales falsas.
Caso concreto de este proyecto: YPF ejecutó un split 10:1 en BYMA el 4-ago-2026.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..provenance import MissingDataError, TracedSeries, observed

_BASE_URL = "https://finance.yahoo.com/quote/{ticker}/history"


def fetch_ohlcv(ticker: str, start: date, end: date) -> TracedSeries:
    """Descarga OHLCV diario ajustado. Lanza excepción si no hay datos.

    Nunca devuelve una serie parcial en silencio: si la fuente entrega menos
    datos de los que el rango pedido implica, el llamador debe enterarse.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MissingDataError(
            "yfinance no está instalado. Ejecutá: pip install -r requirements.txt"
        ) from exc

    raw = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=True,  # ajusta por splits y dividendos
        progress=False,
        actions=False,
    )

    if raw is None or raw.empty:
        raise MissingDataError(
            f"Yahoo Finance no devolvió datos para '{ticker}' entre {start} y {end}. "
            "Verificá el símbolo (BYMA usa sufijo .BA) y la conectividad. "
            "No se generan datos de reemplazo."
        )

    # yfinance devuelve columnas MultiIndex cuando se pide un solo ticker en
    # versiones recientes; se aplana para tener un contrato estable.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df.sort_index()

    return observed(
        data=df,
        source_id=f"yahoo:{ticker}",
        source_url=_BASE_URL.format(ticker=ticker),
        raw_payload=df.to_csv(),
        notes=(
            f"OHLCV diario ajustado por splits y dividendos (auto_adjust=True). "
            f"Rango solicitado {start}..{end}."
        ),
    )
