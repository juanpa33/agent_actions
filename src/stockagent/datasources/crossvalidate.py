"""Reconciliación entre dos proveedores de precios independientes.

No busca "arreglar" discrepancias: las reporta. Si Yahoo y Stooq difieren en un
día, el dato de ese día es sospechoso y el analista tiene que saberlo antes de
apostar dinero sobre él.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..provenance import TracedSeries


@dataclass
class ReconciliationReport:
    ticker: str
    compared_days: int
    max_abs_pct_diff: float
    median_abs_pct_diff: float
    days_over_tolerance: list[str]
    tolerance_pct: float
    secondary_available: bool

    @property
    def clean(self) -> bool:
        return self.secondary_available and not self.days_over_tolerance

    def summary(self) -> str:
        if not self.secondary_available:
            return (
                f"{self.ticker}: SIN validación cruzada — no hay segunda fuente "
                f"para este símbolo. El dato depende de un único proveedor."
            )
        if self.clean:
            return (
                f"{self.ticker}: dos fuentes coinciden en {self.compared_days} días "
                f"(dif. mediana {self.median_abs_pct_diff:.4f}%, "
                f"máx {self.max_abs_pct_diff:.4f}%)."
            )
        return (
            f"{self.ticker}: DISCREPANCIA en {len(self.days_over_tolerance)} de "
            f"{self.compared_days} días por encima de {self.tolerance_pct}% "
            f"(máx {self.max_abs_pct_diff:.4f}%). Días: "
            f"{', '.join(self.days_over_tolerance[:10])}"
            + (" ..." if len(self.days_over_tolerance) > 10 else "")
        )


def reconcile(
    ticker: str,
    primary: TracedSeries,
    secondary: TracedSeries | None,
    tolerance_pct: float = 1.0,
) -> ReconciliationReport:
    """Compara cierres de dos proveedores sobre sus fechas en común.

    La tolerancia por defecto (1%) no es arbitraria: proveedores distintos
    aplican los ajustes por dividendos en momentos distintos y con redondeos
    distintos, lo que produce diferencias pequeñas y legítimas. Un salto mayor
    indica un error real de datos, típicamente un split mal aplicado.
    """
    if secondary is None:
        return ReconciliationReport(
            ticker=ticker,
            compared_days=0,
            max_abs_pct_diff=float("nan"),
            median_abs_pct_diff=float("nan"),
            days_over_tolerance=[],
            tolerance_pct=tolerance_pct,
            secondary_available=False,
        )

    a = primary.data["close"] if isinstance(primary.data, pd.DataFrame) else primary.data
    b = secondary.data["close"] if isinstance(secondary.data, pd.DataFrame) else secondary.data

    common = a.index.intersection(b.index)
    if len(common) == 0:
        return ReconciliationReport(
            ticker=ticker,
            compared_days=0,
            max_abs_pct_diff=float("nan"),
            median_abs_pct_diff=float("nan"),
            days_over_tolerance=[],
            tolerance_pct=tolerance_pct,
            secondary_available=False,
        )

    diff_pct = ((a.loc[common] - b.loc[common]) / b.loc[common] * 100.0).abs()
    over = diff_pct[diff_pct > tolerance_pct]

    return ReconciliationReport(
        ticker=ticker,
        compared_days=len(common),
        max_abs_pct_diff=float(diff_pct.max()),
        median_abs_pct_diff=float(diff_pct.median()),
        days_over_tolerance=[d.strftime("%Y-%m-%d") for d in over.index],
        tolerance_pct=tolerance_pct,
        secondary_available=True,
    )


def detect_data_anomalies(prices: pd.Series, jump_sigma: float = 8.0) -> dict[str, list[str]]:
    """Detecta patologías típicas de series de precios mal construidas.

    Un split no ajustado aparece como un retorno de -90% en un día. Con precios
    correctamente ajustados no debería haber ninguno.
    """
    anomalies: dict[str, list[str]] = {}

    nonpositive = prices[prices <= 0]
    if len(nonpositive):
        anomalies["precios_no_positivos"] = [d.strftime("%Y-%m-%d") for d in nonpositive.index]

    dupes = prices.index[prices.index.duplicated()]
    if len(dupes):
        anomalies["fechas_duplicadas"] = [d.strftime("%Y-%m-%d") for d in dupes]

    rets = np.log(prices / prices.shift(1)).dropna()
    if len(rets) > 30:
        sigma = rets.std()
        extreme = rets[rets.abs() > jump_sigma * sigma]
        if len(extreme):
            anomalies["saltos_extremos"] = [
                f"{d:%Y-%m-%d} ({r * 100:+.1f}%)" for d, r in extreme.items()
            ]

    flat = prices.diff() == 0
    runs, current = [], 0
    for ts, is_flat in flat.items():
        if is_flat:
            current += 1
        else:
            if current >= 5:
                runs.append(f"{ts:%Y-%m-%d} (fin de {current} días sin cambio)")
            current = 0
    if runs:
        anomalies["precio_congelado"] = runs

    return anomalies
