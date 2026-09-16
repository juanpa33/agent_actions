"""Ajustes específicos del mercado argentino para analizar YPFD (BYMA, ARS).

Analizar una acción argentina en pesos nominales es un error de medición, no de
opinión. Este módulo implementa las dos correcciones necesarias:

1. Conversión a dólares mediante el CCL implícito calculado del par YPFD/YPF.
   Es el tipo de cambio al que un inversor local efectivamente accede, y no
   depende de ninguna estimación: sale de dos precios de mercado observados.
2. Deflación por IPC, para medir el retorno en pesos de poder adquisitivo
   constante.

Riesgo estructural que este módulo vigila: el split 10:1 de YPFD del 4-ago-2026,
acompañado del cambio de la razón del ADR de 1:1 a 1:10. Si el proveedor de
datos aplica mal ese ajuste, el CCL sale multiplicado o dividido por 10 y toda
la serie en dólares queda inservible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .provenance import MissingDataError, TracedSeries


@dataclass(frozen=True)
class RatioChange:
    """Cambio en la cantidad de acciones locales que representa un ADS."""

    effective_date: date
    shares_per_ads: float
    source: str


# Historial de la razón del ADR de YPF.
#
# El 4-ago-2026 se hizo efectivo en BYMA el split 10:1 de las acciones YPFD y,
# simultáneamente, la razón del ADR pasó de 1 a 10 acciones Clase D por ADS, de
# modo que el precio del ADR quedó inalterado.
#
# VERIFICACIÓN OBLIGATORIA antes de operar: confirmar esta tabla contra el
# formulario 6-K correspondiente en SEC EDGAR
# (https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000904851)
# y contra el comunicado de YPF Investor Relations. Este archivo es una
# transcripción de información pública, no una fuente primaria.
YPF_ADR_RATIO_HISTORY: tuple[RatioChange, ...] = (
    RatioChange(date(1993, 1, 1), 1.0, "Emisión original: 1 ADS = 1 acción Clase D"),
    RatioChange(date(2026, 8, 4), 10.0, "Split 10:1 en BYMA; razón del ADS 1:1 -> 1:10"),
)


def shares_per_ads_on(day: date, history: tuple[RatioChange, ...] = YPF_ADR_RATIO_HISTORY) -> float:
    """Razón del ADR vigente en una fecha, para usar con precios SIN ajustar."""
    applicable = [c for c in history if c.effective_date <= day]
    if not applicable:
        raise MissingDataError(
            f"No hay razón de ADR conocida para {day}: es anterior al primer "
            "registro del historial."
        )
    return max(applicable, key=lambda c: c.effective_date).shares_per_ads


def effective_ratio_for_adjusted_series(
    history: tuple[RatioChange, ...] = YPF_ADR_RATIO_HISTORY,
) -> float:
    """Razón constante aplicable a series YA ajustadas por split.

    Razonamiento, explícito porque es donde se cometen los errores de 10x:

    Con precios crudos, CCL(t) = P_local(t) * R(t) / P_adr(t), con R variable.
    Un ajuste por split 10:1 divide por 10 todos los precios locales ANTERIORES
    al split, mientras que el ADR no sufre ajuste (su precio no cambió al
    modificarse la razón). Entonces, para t anterior al split:

        P_local_cruda(t) = P_local_ajustada(t) * 10  y  R(t) = 1
        => CCL(t) = P_local_ajustada(t) * 10 / P_adr(t)

    y para t posterior, P_local_cruda = P_local_ajustada y R = 10, lo que da la
    misma expresión. La razón efectiva sobre series ajustadas es por lo tanto
    CONSTANTE e igual a la razón vigente hoy.

    El resultado es limpio, pero descansa en que el proveedor haya ajustado la
    pata local y NO la del ADR. `validate_ccl_continuity` verifica justamente eso.
    """
    return max(history, key=lambda c: c.effective_date).shares_per_ads


def implied_ccl(
    local_ars: TracedSeries,
    adr_usd: TracedSeries,
    prices_are_split_adjusted: bool = True,
    history: tuple[RatioChange, ...] = YPF_ADR_RATIO_HISTORY,
) -> TracedSeries:
    """Calcula el dólar CCL implícito en pesos por dólar.

    CCL = precio local en ARS * acciones por ADS / precio del ADR en USD

    Es el costo efectivo en pesos de conseguir un dólar comprando la acción
    local, convirtiéndola en ADR y vendiéndolo en Nueva York.
    """
    local = _close_of(local_ars)
    adr = _close_of(adr_usd)

    common = local.index.intersection(adr.index)
    if len(common) < 20:
        raise MissingDataError(
            f"Solo hay {len(common)} días en común entre YPFD.BA y el ADR YPF. "
            "Sin superposición no se puede calcular el CCL implícito. "
            "Causa habitual: feriados distintos o un símbolo mal escrito."
        )

    local_c, adr_c = local.loc[common], adr.loc[common]

    if prices_are_split_adjusted:
        ratio = pd.Series(effective_ratio_for_adjusted_series(history), index=common)
        method = f"razón constante {ratio.iloc[0]:g} (series ajustadas por split)"
    else:
        ratio = pd.Series([shares_per_ads_on(d.date(), history) for d in common], index=common)
        method = "razón vigente por fecha (series sin ajustar)"

    ccl = (local_c * ratio / adr_c).rename("ccl_implicito")

    return local_ars.derive(
        ccl,
        operation="ccl_implicito",
        extra_parents=[adr_usd],
        notes=f"CCL = P_ARS * acciones_por_ADS / P_ADR_USD, usando {method}.",
    )


def validate_ccl_continuity(
    ccl: pd.Series,
    history: tuple[RatioChange, ...] = YPF_ADR_RATIO_HISTORY,
    window: int = 5,
    max_step_pct: float = 25.0,
) -> list[str]:
    """Verifica que el CCL no dé un salto artificial en las fechas de split.

    El tipo de cambio es una variable macroeconómica: puede saltar por una
    devaluación, pero no puede saltar exactamente el día de un split societario
    de una empresa. Un salto ahí es, casi con certeza, un error de ajuste del
    proveedor de datos, y típicamente de un factor cercano a 10.
    """
    warnings: list[str] = []

    for change in history:
        ts = pd.Timestamp(change.effective_date)
        before = ccl[ccl.index < ts].tail(window)
        after = ccl[ccl.index >= ts].head(window)
        if len(before) < 2 or len(after) < 2:
            continue

        med_before, med_after = float(before.median()), float(after.median())
        if med_before <= 0:
            continue
        step_pct = (med_after / med_before - 1.0) * 100.0

        if abs(step_pct) > max_step_pct:
            factor = med_after / med_before
            hint = ""
            for candidate in (10.0, 0.1):
                if abs(factor / candidate - 1.0) < 0.2:
                    hint = (
                        f" El salto es de un factor ~{candidate:g}, compatible con un "
                        "split aplicado a una sola de las dos patas del cálculo."
                    )
            warnings.append(
                f"El CCL salta {step_pct:+.1f}% alrededor de {change.effective_date} "
                f"({change.source}): {med_before:,.0f} -> {med_after:,.0f} ARS/USD.{hint} "
                "NO uses esta serie hasta resolverlo."
            )

    return warnings


def validate_ccl_level(ccl: pd.Series, official_fx: pd.Series | None = None,
                       max_gap_pct: float = 200.0) -> list[str]:
    """Contrasta el CCL implícito contra el tipo de cambio oficial.

    La brecha entre el CCL y el oficial es un fenómeno real y puede ser grande;
    lo que no es real es una brecha de varios cientos por ciento sostenida, que
    delata un error de escala en el cálculo.
    """
    warnings: list[str] = []
    if official_fx is None or official_fx.empty:
        return ["Sin tipo de cambio oficial: no se pudo validar el NIVEL del CCL implícito."]

    common = ccl.index.intersection(official_fx.index)
    if len(common) < 20:
        return ["Superposición insuficiente con el tipo de cambio oficial para validar el nivel."]

    gap = (ccl.loc[common] / official_fx.loc[common] - 1.0) * 100.0
    median_gap = float(gap.median())

    if median_gap > max_gap_pct:
        warnings.append(
            f"La brecha mediana CCL/oficial es {median_gap:.0f}%, por encima del "
            f"umbral de {max_gap_pct:.0f}%. Revisá la razón del ADR antes de confiar en la serie."
        )
    if median_gap < -20.0:
        warnings.append(
            f"La brecha mediana CCL/oficial es {median_gap:.0f}% (CCL por DEBAJO del oficial). "
            "Es económicamente implausible con control de cambios y sugiere error de escala."
        )
    return warnings


def to_usd(local_ars: TracedSeries, ccl: TracedSeries) -> TracedSeries:
    """Convierte una serie de precios en ARS a dólares CCL."""
    local = _close_of(local_ars)
    fx = ccl.data if isinstance(ccl.data, pd.Series) else ccl.data.iloc[:, 0]

    common = local.index.intersection(fx.index)
    if len(common) == 0:
        raise MissingDataError("No hay fechas en común entre el precio local y el CCL.")

    usd = (local.loc[common] / fx.loc[common]).rename("close_usd")
    return local_ars.derive(
        usd,
        operation="ars_a_usd_ccl",
        extra_parents=[ccl],
        notes="Precio local dividido por el CCL implícito del mismo día.",
    )


def real_ars(local_ars: TracedSeries, ipc: TracedSeries) -> TracedSeries:
    """Convierte precios nominales en ARS a pesos constantes del último mes publicado."""
    from .datasources.indec import deflate

    local = _close_of(local_ars)
    ipc_series = ipc.data if isinstance(ipc.data, pd.Series) else ipc.data.iloc[:, 0]
    real = deflate(local, ipc_series).rename("close_ars_real")

    return local_ars.derive(
        real,
        operation="deflacion_ipc",
        extra_parents=[ipc],
        notes=(
            "Precio en pesos constantes del último mes con IPC publicado. "
            "Los días posteriores a esa publicación se excluyen: el IPC no se extrapola."
        ),
    )


def _close_of(ts: TracedSeries) -> pd.Series:
    if isinstance(ts.data, pd.DataFrame):
        if "close" in ts.data.columns:
            return ts.data["close"]
        return ts.data.iloc[:, 0]
    return ts.data
