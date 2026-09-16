"""Construcción del universo de análisis.

El top 10 del NASDAQ por capitalización NO se escribe a mano en el código. Las
capitalizaciones cambian todas las ruedas y una lista transcripta hoy está mal
dentro de unos meses, sin que nada avise. Se resuelve contra dos fuentes en
cadena:

1. Composición del índice Nasdaq-100 tomada de las tenencias publicadas del ETF
   QQQ (Invesco), que replica el índice y publica su cartera a diario.
2. Capitalización de mercado de cada componente vía yfinance, para ordenarlos.

Solo si ambas fallan se usa una lista de respaldo, que está fechada y emite una
advertencia visible en el reporte. Un dato viejo usado a sabiendas es aceptable;
un dato viejo usado sin saberlo, no.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date

import requests

_QQQ_HOLDINGS_URL = (
    "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
    "?audienceType=Investor&action=download&ticker=QQQ"
)

FALLBACK_DATE = date(2026, 9, 15)
FALLBACK_TOP10 = ("NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "AVGO", "META", "TSLA", "MU", "AMD")
"""Respaldo de último recurso, por capitalización, al 15-sep-2026.

Transcripto de compilaciones públicas de capitalización bursátil consultadas en
esa fecha. NO es una fuente primaria y NO se actualiza solo. Si el reporte
indica que se usó esta lista, verificala antes de operar.
"""


@dataclass
class UniverseResolution:
    tickers: tuple[str, ...]
    source: str
    resolved_on: date
    is_fallback: bool
    warnings: list[str]

    def summary(self) -> str:
        head = f"Universo ({len(self.tickers)}): {', '.join(self.tickers)}"
        origin = f"Fuente: {self.source} — resuelto el {self.resolved_on}"
        if self.is_fallback:
            return (
                f"{head}\n{origin}\n"
                f"ADVERTENCIA: se usó la lista de respaldo fechada {FALLBACK_DATE}. "
                "El ranking real por capitalización puede haber cambiado. Verificalo."
            )
        return f"{head}\n{origin}"


def fetch_nasdaq100_constituents(timeout: int = 30) -> list[str]:
    """Descarga los componentes del Nasdaq-100 desde las tenencias del ETF QQQ."""
    response = requests.get(
        _QQQ_HOLDINGS_URL, timeout=timeout, headers={"User-Agent": "stockagent/1.0"}
    )
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    column = None
    tickers: list[str] = []

    for row in reader:
        if column is None:
            for candidate in ("Holding Ticker", "HoldingTicker", "Ticker", "Symbol"):
                if candidate in row:
                    column = candidate
                    break
            if column is None:
                raise ValueError(
                    f"El CSV de tenencias no tiene columna de ticker reconocible. "
                    f"Columnas: {list(row.keys())}"
                )
        value = (row.get(column) or "").strip().upper()
        if value and value.isalpha():
            tickers.append(value)

    if len(tickers) < 50:
        raise ValueError(f"Solo se extrajeron {len(tickers)} tickers del QQQ; el archivo cambió de formato.")
    return tickers


def rank_by_market_cap(tickers: list[str], top_n: int = 10) -> tuple[list[tuple[str, float]], list[str]]:
    """Ordena tickers por capitalización de mercado actual.

    Los símbolos cuya capitalización no se puede obtener se EXCLUYEN y se
    reportan. No se les asigna un valor estimado: un activo rankeado con una
    capitalización inventada desplaza a uno real del top 10.
    """
    import yfinance as yf

    caps: list[tuple[str, float]] = []
    failures: list[str] = []

    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).get_info()
            cap = info.get("marketCap")
            if cap:
                caps.append((ticker, float(cap)))
            else:
                failures.append(ticker)
        except Exception:  # noqa: BLE001 - un símbolo caído no debe frenar el resto
            failures.append(ticker)

    caps.sort(key=lambda item: item[1], reverse=True)
    return caps[:top_n], failures


def resolve_nasdaq_top(top_n: int = 10, allow_fallback: bool = True) -> UniverseResolution:
    """Determina las N mayores del NASDAQ, con degradación explícita si falla la red."""
    warnings: list[str] = []

    try:
        constituents = fetch_nasdaq100_constituents()
        ranked, failures = rank_by_market_cap(constituents, top_n)
        if failures:
            warnings.append(
                f"No se pudo obtener capitalización de {len(failures)} símbolos "
                f"(excluidos del ranking): {', '.join(failures[:10])}"
                + (" ..." if len(failures) > 10 else "")
            )
        if len(ranked) >= top_n:
            return UniverseResolution(
                tickers=tuple(t for t, _ in ranked),
                source="Tenencias del ETF QQQ (Invesco) + capitalización de Yahoo Finance",
                resolved_on=date.today(),
                is_fallback=False,
                warnings=warnings,
            )
        warnings.append(f"Solo se rankearon {len(ranked)} símbolos; se esperaban {top_n}.")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Falló la resolución dinámica del universo: {type(exc).__name__}: {exc}")

    if not allow_fallback:
        raise RuntimeError(
            "No se pudo resolver el universo desde las fuentes y el respaldo está "
            f"deshabilitado. Detalle: {warnings}"
        )

    warnings.append(
        f"Se usó la lista de respaldo del {FALLBACK_DATE}. Verificá el ranking "
        "vigente antes de tomar decisiones."
    )
    return UniverseResolution(
        tickers=FALLBACK_TOP10[:top_n],
        source=f"Lista de respaldo fechada {FALLBACK_DATE} (NO es fuente primaria)",
        resolved_on=date.today(),
        is_fallback=True,
        warnings=warnings,
    )
