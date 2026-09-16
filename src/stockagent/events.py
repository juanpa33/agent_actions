"""Estudio de eventos: convierte noticias en estadística medible.

Por qué este módulo existe en lugar de un "puntaje de sentimiento".

Pedirle a un modelo de lenguaje que lea titulares y devuelva un número entre -1
y +1 produce una cifra que parece un dato y no lo es: no es reproducible, no
tiene error de medición conocido, no se puede auditar y no hay forma de saber si
predice algo. Incorporarla a una decisión de inversión es incorporar una opinión
disfrazada de medición.

La metodología de estudio de eventos resuelve el mismo problema con estadística
verificable. Está establecida desde Fama, Fisher, Jensen & Roll (1969),
"The Adjustment of Stock Prices to New Information", International Economic
Review 10(1), 1-21, y sistematizada en MacKinlay (1997), "Event Studies in
Economics and Finance", Journal of Economic Literature 35(1), 13-39.

El procedimiento es: se fecha el evento con precisión, se estima el retorno
NORMAL esperado del activo con un modelo de mercado ajustado sobre una ventana
anterior al evento, y se mide cuánto se desvió el retorno efectivo de ese
esperado. Esa desviación es el retorno anormal, y tiene un error estándar
calculable, de modo que se puede decir si el movimiento fue estadísticamente
distinguible del ruido normal del papel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class EventStudyConfig:
    estimation_window: int = 250
    """Ruedas usadas para estimar el modelo de mercado. MacKinlay (1997) sugiere
    en torno a 250 para datos diarios."""

    estimation_gap: int = 30
    """Ruedas entre el fin de la ventana de estimación y el evento. Evita que la
    filtración previa de información contamine la estimación del comportamiento
    normal."""

    event_window_pre: int = 1
    event_window_post: int = 3
    min_estimation_obs: int = 100


@dataclass
class EventResult:
    event_date: pd.Timestamp
    label: str
    category: str
    alpha: float
    beta: float
    r_squared: float
    residual_std: float
    abnormal_returns: pd.Series
    car: float
    car_tstat: float
    car_pvalue: float
    estimation_obs: int
    source_url: str = ""

    @property
    def significant(self) -> bool:
        return self.car_pvalue < 0.05

    def describe(self) -> str:
        mark = "significativo" if self.significant else "no distinguible del ruido"
        return (
            f"{self.event_date:%Y-%m-%d} [{self.category}] {self.label}: "
            f"retorno anormal acumulado {self.car * 100:+.2f}% "
            f"(t = {self.car_tstat:+.2f}, p = {self.car_pvalue:.3f}) — {mark}"
        )


def estimate_market_model(
    asset_returns: pd.Series, market_returns: pd.Series, event_date: pd.Timestamp,
    config: EventStudyConfig
) -> tuple[float, float, float, float, int]:
    """Ajusta r_activo = alfa + beta * r_mercado por mínimos cuadrados, previo al evento."""
    end = event_date - pd.Timedelta(days=1)
    pre = asset_returns.index[asset_returns.index <= end]
    if len(pre) < config.estimation_gap + config.min_estimation_obs:
        raise ValueError(
            f"Historia insuficiente antes de {event_date:%Y-%m-%d}: "
            f"{len(pre)} ruedas disponibles."
        )

    window_end = pre[-config.estimation_gap]
    window_start_pos = max(0, len(pre) - config.estimation_gap - config.estimation_window)
    window_start = pre[window_start_pos]

    mask = (asset_returns.index >= window_start) & (asset_returns.index <= window_end)
    y = asset_returns[mask]
    x = market_returns.reindex(y.index)

    valid = y.notna() & x.notna()
    y, x = y[valid], x[valid]
    if len(y) < config.min_estimation_obs:
        raise ValueError(f"Solo {len(y)} observaciones válidas para estimar el modelo.")

    slope, intercept, r_value, _, _ = stats.linregress(x.to_numpy(), y.to_numpy())
    residuals = y - (intercept + slope * x)
    return float(intercept), float(slope), float(r_value**2), float(residuals.std(ddof=2)), len(y)


def run_event_study(
    asset_returns: pd.Series,
    market_returns: pd.Series,
    event_date: date | pd.Timestamp,
    label: str,
    category: str = "sin_clasificar",
    config: EventStudyConfig | None = None,
    source_url: str = "",
) -> EventResult:
    """Mide el retorno anormal alrededor de un evento fechado."""
    cfg = config or EventStudyConfig()
    ts = pd.Timestamp(event_date).normalize()

    alpha, beta, r2, resid_std, n_obs = estimate_market_model(
        asset_returns, market_returns, ts, cfg
    )

    # El evento se ancla a la primera rueda en o posterior a su fecha: una
    # noticia de sábado impacta el lunes.
    future = asset_returns.index[asset_returns.index >= ts]
    if len(future) == 0:
        raise ValueError(f"No hay ruedas posteriores a {ts:%Y-%m-%d}.")
    anchor_pos = asset_returns.index.get_loc(future[0])

    start = max(0, anchor_pos - cfg.event_window_pre)
    end = min(len(asset_returns), anchor_pos + cfg.event_window_post + 1)
    window = asset_returns.iloc[start:end]

    expected = alpha + beta * market_returns.reindex(window.index)
    abnormal = (window - expected).dropna()

    car = float(abnormal.sum())
    # Bajo independencia serial de los residuos, la varianza del acumulado es
    # la suma de las varianzas diarias (MacKinlay 1997, sección 4.4.2).
    car_se = resid_std * np.sqrt(len(abnormal))
    tstat = car / car_se if car_se > 0 else float("nan")
    pvalue = float(2 * (1 - stats.t.cdf(abs(tstat), df=max(n_obs - 2, 1)))) if not np.isnan(tstat) else float("nan")

    return EventResult(
        event_date=ts,
        label=label,
        category=category,
        alpha=alpha,
        beta=beta,
        r_squared=r2,
        residual_std=resid_std,
        abnormal_returns=abnormal,
        car=car,
        car_tstat=float(tstat),
        car_pvalue=pvalue,
        estimation_obs=n_obs,
        source_url=source_url,
    )


@dataclass
class CategoryAggregate:
    category: str
    n_events: int
    mean_car: float
    median_car: float
    tstat: float
    pvalue: float
    hit_rate: float

    def describe(self) -> str:
        if self.n_events < 5:
            return (
                f"[{self.category}] {self.n_events} eventos: muestra demasiado chica "
                f"para inferir. CAR medio {self.mean_car * 100:+.2f}% (sin valor estadístico)."
            )
        verdict = (
            "efecto sistemático detectado" if self.pvalue < 0.05
            else "sin efecto sistemático distinguible de cero"
        )
        return (
            f"[{self.category}] {self.n_events} eventos: CAR medio "
            f"{self.mean_car * 100:+.2f}%, mediana {self.median_car * 100:+.2f}%, "
            f"t = {self.tstat:+.2f}, p = {self.pvalue:.3f}, "
            f"{self.hit_rate * 100:.0f}% positivos — {verdict}."
        )


def aggregate_by_category(results: list[EventResult]) -> list[CategoryAggregate]:
    """Agrega los retornos anormales por tipo de evento (CAAR) con test t transversal.

    Esta es la pregunta que de verdad importa para operar: no si una noticia
    puntual movió el precio, sino si una CLASE de noticia lo mueve de forma
    sistemática. Con menos de 5 eventos por categoría no se reporta inferencia:
    sería numerología.
    """
    by_category: dict[str, list[EventResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    aggregates: list[CategoryAggregate] = []
    for category, items in sorted(by_category.items()):
        cars = np.array([r.car for r in items])
        n = len(cars)
        if n >= 2 and cars.std(ddof=1) > 0:
            tstat = cars.mean() / (cars.std(ddof=1) / np.sqrt(n))
            pvalue = float(2 * (1 - stats.t.cdf(abs(tstat), df=n - 1)))
        else:
            tstat, pvalue = float("nan"), float("nan")

        aggregates.append(
            CategoryAggregate(
                category=category,
                n_events=n,
                mean_car=float(cars.mean()),
                median_car=float(np.median(cars)),
                tstat=float(tstat),
                pvalue=pvalue,
                hit_rate=float((cars > 0).mean()),
            )
        )
    return aggregates
