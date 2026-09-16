"""IPC de INDEC vía la API de Series de Tiempo del Estado argentino.

Por qué importa: el retorno nominal en pesos de una acción argentina es, en su
mayor parte, inflación. Sin deflactar, una acción que perdió poder adquisitivo
aparece como ganadora. Cualquier análisis de YPFD en ARS que ignore el IPC mide
la máquina de imprimir billetes, no la empresa.

Fuente: https://apis.datos.gob.ar/series/api/ (datos de INDEC).
Documentación: https://datosgobar.github.io/series-tiempo-ar-api/
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from ..provenance import MissingDataError, TracedSeries, observed

_API = "https://apis.datos.gob.ar/series/api/series"

IPC_NIVEL_GENERAL = "148.3_INIVELNAL_DICI_M_26"
"""IPC nivel general, nacional, base diciembre 2016 = 100. Frecuencia mensual.

Si INDEC rebasea o discontinúa la serie, este identificador deja de resolver y
`fetch_ipc` falla ruidosamente en lugar de devolver datos viejos o inventados.
"""


def fetch_ipc(start: date, end: date, series_id: str = IPC_NIVEL_GENERAL,
              timeout: int = 30) -> TracedSeries:
    """Descarga el índice IPC mensual. Lanza excepción si la serie no resuelve."""
    params = {
        "ids": series_id,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "format": "json",
        "limit": 5000,
    }
    response = requests.get(_API, params=params, timeout=timeout,
                            headers={"User-Agent": "stockagent/1.0"})
    response.raise_for_status()
    payload = response.json()

    rows = payload.get("data", [])
    if not rows:
        raise MissingDataError(
            f"La API de series de tiempo no devolvió datos para el IPC "
            f"'{series_id}' entre {start} y {end}. Puede que INDEC haya "
            "rebaseado la serie. Verificá el identificador vigente en "
            "https://datos.gob.ar/ antes de continuar. No se estima el IPC."
        )

    idx = pd.to_datetime([r[0] for r in rows])
    values = pd.to_numeric([r[1] for r in rows], errors="coerce")
    ipc = pd.Series(values, index=idx, name="ipc").sort_index()

    if ipc.isna().any():
        missing = ipc[ipc.isna()].index.strftime("%Y-%m").tolist()
        raise MissingDataError(
            f"El IPC tiene meses sin valor: {missing}. Se aborta en vez de "
            "interpolar: un IPC interpolado falsea el retorno real."
        )

    return observed(
        data=ipc,
        source_id=f"indec:{series_id}",
        source_url=f"{_API}?ids={series_id}",
        raw_payload=response.text,
        notes=(
            "IPC nivel general nacional, mensual, publicado por INDEC y servido "
            "por la API de Series de Tiempo del Estado argentino."
        ),
    )


def deflate(nominal: pd.Series, ipc_monthly: pd.Series, base: pd.Timestamp | None = None) -> pd.Series:
    """Convierte una serie nominal diaria en ARS a pesos constantes.

    El IPC es mensual y el precio es diario: se propaga el índice del mes
    corriente hacia adelante (`ffill`) sin inventar valores intermedios. Se
    asume que el índice de un mes aplica a todos sus días, que es la
    interpretación estándar y conservadora.

    Los días posteriores al último IPC publicado quedan FUERA del resultado: el
    IPC se publica con rezago y extrapolarlo sería fabricar el dato más
    sensible del cálculo.
    """
    if ipc_monthly.empty:
        raise MissingDataError("Serie de IPC vacía: no se puede deflactar.")

    monthly = ipc_monthly.copy()
    monthly.index = pd.to_datetime(monthly.index).to_period("M")

    periods = nominal.index.to_period("M")
    aligned = pd.Series(periods.map(monthly), index=nominal.index, dtype="float64")

    last_published = monthly.index.max()
    within_coverage = periods <= last_published
    aligned = aligned.where(within_coverage)

    base_value = monthly.iloc[-1] if base is None else float(monthly.loc[base.to_period("M")])
    real = nominal * (base_value / aligned)
    return real.dropna()
