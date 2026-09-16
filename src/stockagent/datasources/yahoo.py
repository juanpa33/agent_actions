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


def fetch_prices_and_dividends(ticker: str, start: date, end: date):
    """Descarga precios SIN ajustar por dividendos, más los dividendos por separado.

    POR QUÉ ESTA FUNCIÓN EXISTE Y NO ALCANZA CON `fetch_ohlcv`:

    `fetch_ohlcv` usa auto_adjust=True, que descuenta los dividendos del precio
    histórico. Eso es correcto para medir retorno total en un backtest, pero es
    un error grave si además se quiere simular el COBRO de dividendos en
    efectivo: se contarían dos veces, una dentro del precio y otra como caja.

    Acá se devuelven precios ajustados por splits pero NO por dividendos, junto
    con la serie de dividendos efectivamente pagados. Así la simulación puede
    tratar al dividendo como lo que es: plata que entra a la cuenta en una
    fecha concreta.

    Devuelve (precios_ohlcv, dividendos_por_accion).
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise MissingDataError(
            "yfinance no está instalado. Ejecutá: pip install -r requirements.txt"
        ) from exc

    raw = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=False,   # el precio NO se ajusta por dividendos
        actions=True,        # y los dividendos vienen aparte
        progress=False,
    )

    if raw is None or raw.empty:
        raise MissingDataError(
            f"Yahoo Finance no devolvió datos para '{ticker}' entre {start} y {end}. "
            "No se generan datos de reemplazo."
        )

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    raw = raw.sort_index()

    columns = {c.lower(): c for c in raw.columns}
    needed = ["open", "high", "low", "close", "volume"]
    missing = [c for c in needed if c not in columns]
    if missing:
        raise MissingDataError(
            f"Faltan columnas {missing} en los datos de '{ticker}'. "
            f"Columnas recibidas: {list(raw.columns)}"
        )

    prices = raw[[columns[c] for c in needed]].copy()
    prices.columns = needed

    if "dividends" in columns:
        dividends = raw[columns["dividends"]]
        dividends = dividends[dividends > 0]
    else:
        dividends = pd.Series(dtype="float64")

    prices_traced = observed(
        data=prices,
        source_id=f"yahoo:{ticker}:sin_ajuste_dividendos",
        source_url=_BASE_URL.format(ticker=ticker),
        raw_payload=prices.to_csv(),
        notes=(
            "OHLCV ajustado por splits pero NO por dividendos, para poder simular "
            "el cobro de dividendos en efectivo sin contarlos dos veces."
        ),
    )
    dividends_traced = observed(
        data=dividends,
        source_id=f"yahoo:{ticker}:dividendos",
        source_url=_BASE_URL.format(ticker=ticker),
        raw_payload=dividends.to_csv(),
        notes=f"Dividendos por acción efectivamente pagados. {len(dividends)} pagos en el período.",
    )
    return prices_traced, dividends_traced
