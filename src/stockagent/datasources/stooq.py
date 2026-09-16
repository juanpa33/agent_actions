"""Descarga de precios desde Stooq (CSV público, sin API key).

Actúa como segunda fuente independiente para validar a Yahoo. Dos proveedores
que coinciden no garantizan que el dato sea correcto, pero un desacuerdo sí
garantiza que al menos uno está mal, y eso es información accionable.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import requests

from ..provenance import TracedSeries, observed

_CSV_URL = "https://stooq.com/q/d/l/?s={symbol}&d1={d1}&d2={d2}&i=d"

# Stooq usa su propia nomenclatura de símbolos.
_SYMBOL_MAP = {
    "NVDA": "nvda.us",
    "AAPL": "aapl.us",
    "MSFT": "msft.us",
    "GOOGL": "googl.us",
    "AMZN": "amzn.us",
    "META": "meta.us",
    "AVGO": "avgo.us",
    "TSLA": "tsla.us",
    "MU": "mu.us",
    "AMD": "amd.us",
    "YPF": "ypf.us",
    "^NDX": "^ndx",
    "^GSPC": "^spx",
}


def to_stooq_symbol(ticker: str) -> str | None:
    """Traduce un símbolo al formato de Stooq. None si no hay equivalencia conocida.

    Devolver None es deliberado: es preferible saltear la validación cruzada de
    forma explícita antes que adivinar un símbolo y comparar contra el activo
    equivocado.
    """
    if ticker in _SYMBOL_MAP:
        return _SYMBOL_MAP[ticker]
    if ticker.endswith(".BA"):
        # Stooq no publica BYMA de forma confiable.
        return None
    return None


def fetch_close(ticker: str, start: date, end: date, timeout: int = 30) -> TracedSeries | None:
    """Descarga cierres diarios. None si el símbolo no existe en Stooq."""
    symbol = to_stooq_symbol(ticker)
    if symbol is None:
        return None

    url = _CSV_URL.format(
        symbol=symbol, d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")
    )
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "stockagent/1.0"})
    response.raise_for_status()
    text = response.text

    if "Date,Open" not in text:
        # Stooq responde HTTP 200 con cuerpo "No data" cuando no tiene la serie.
        return None

    df = pd.read_csv(io.StringIO(text))
    df["Date"] = pd.to_datetime(df["Date"])
    close = df.set_index("Date")["Close"].sort_index()
    close.index = close.index.normalize()

    return observed(
        data=close,
        source_id=f"stooq:{symbol}",
        source_url=url,
        raw_payload=text,
        notes="Cierre diario ajustado, usado como segunda fuente de validación.",
    )
