"""Orquestación del análisis de punta a punta.

Secuencia: descarga con procedencia -> validación cruzada y detección de
anomalías -> ajustes de mercado argentino -> señales -> backtest -> estadística
correctiva -> estudio de eventos -> reporte.

Si un paso crítico falla, el pipeline ABORTA. No degrada silenciosamente a una
versión aproximada del análisis: un reporte incompleto que parece completo es
más peligroso que ningún reporte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from . import backtest as bt
from . import events as ev
from . import news as nw
from . import signals as sg
from . import statistics as st
from .argentina import implied_ccl, real_ars, to_usd, validate_ccl_continuity, validate_ccl_level
from .datasources import crossvalidate, stooq, yahoo
from .provenance import MissingDataError, TracedSeries


@dataclass
class AssetAnalysis:
    ticker: str
    display_name: str
    prices: TracedSeries
    currency: str
    signals: sg.SignalSet
    backtest: bt.BacktestResult
    sharpe_assessment: st.SharpeAssessment
    sharpe_ci: tuple[float, float, float]
    bootstrap_pvalue: float
    walk_forward: bt.WalkForwardResult | None
    reconciliation: crossvalidate.ReconciliationReport
    anomalies: dict[str, list[str]]
    event_results: list[ev.EventResult] = field(default_factory=list)
    event_aggregates: list[ev.CategoryAggregate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineConfig:
    years: float = 2.0
    trials_evaluated: int = 1
    """Número de configuraciones probadas en toda la investigación. Es el
    insumo del Deflated Sharpe: subdeclararlo infla artificialmente la
    significancia estadística del resultado."""

    target_annual_vol: float = 0.15
    atr_multiple: float = 3.0
    rebalance: str = "W-FRI"
    walk_forward_folds: int = 4
    benchmark: str = "^NDX"
    signal_config: sg.SignalConfig = field(default_factory=sg.SignalConfig)


def load_asset(ticker: str, start: date, end: date, tolerance_pct: float = 1.0):
    """Descarga un activo de la fuente primaria y lo valida contra la secundaria."""
    primary = yahoo.fetch_ohlcv(ticker, start, end)

    try:
        secondary = stooq.fetch_close(ticker, start, end)
    except Exception as exc:  # noqa: BLE001 - la validación es deseable, no obligatoria
        secondary = None
        reconciliation_note = f"Stooq no respondió ({type(exc).__name__}); sin validación cruzada."
    else:
        reconciliation_note = ""

    report = crossvalidate.reconcile(ticker, primary, secondary, tolerance_pct)
    anomalies = crossvalidate.detect_data_anomalies(primary.data["close"])

    warnings: list[str] = []
    if reconciliation_note:
        warnings.append(reconciliation_note)
    if not report.clean:
        warnings.append(report.summary())
    for kind, days in anomalies.items():
        warnings.append(f"Anomalía '{kind}' en {ticker}: {days[:5]}" + (" ..." if len(days) > 5 else ""))

    return primary, report, anomalies, warnings


def analyze_asset(
    ticker: str,
    prices: TracedSeries,
    market_returns: pd.Series,
    config: PipelineConfig,
    cost_model: bt.CostModel,
    reconciliation: crossvalidate.ReconciliationReport,
    anomalies: dict[str, list[str]],
    warnings: list[str],
    display_name: str = "",
    currency: str = "USD",
    news_events: list[nw.NewsEvent] | None = None,
) -> AssetAnalysis:
    """Corre señales, backtest, estadística y estudio de eventos sobre un activo."""
    close = prices.data["close"] if isinstance(prices.data, pd.DataFrame) else prices.data
    close = close.dropna()

    if len(close) < 260:
        raise MissingDataError(
            f"{ticker}: solo {len(close)} ruedas. Las señales requieren al menos 252 "
            "(media de 200 y máximo de 52 semanas). No se producen señales parciales."
        )

    signal_set = sg.build_signals(close, ticker, config.signal_config)
    daily_returns = close.pct_change().dropna()
    weights = sg.volatility_target_weight(
        daily_returns, target_annual_vol=config.target_annual_vol
    )

    position = signal_set.position_flag
    if isinstance(prices.data, pd.DataFrame) and {"high", "low"}.issubset(prices.data.columns):
        position = sg.apply_atr_stop(
            close, prices.data["high"], prices.data["low"], position,
            atr_multiple=config.atr_multiple,
        )

    result = bt.run_backtest(close, position, weights, cost_model, rebalance=config.rebalance)

    assessment = st.assess_sharpe(result.returns, trials=config.trials_evaluated)
    ci = st.bootstrap_sharpe_ci(result.returns)
    pvalue = st.bootstrap_pvalue(result.returns)

    walk = None
    try:
        def builder(sub_prices: pd.Series):
            s = sg.build_signals(sub_prices, ticker, config.signal_config)
            w = sg.volatility_target_weight(
                sub_prices.pct_change().dropna(), target_annual_vol=config.target_annual_vol
            )
            return s.position_flag, w

        walk = bt.walk_forward(close, builder, n_folds=config.walk_forward_folds, costs=cost_model)
    except ValueError as exc:
        warnings.append(f"{ticker}: no se pudo validar walk-forward — {exc}")

    event_results: list[ev.EventResult] = []
    if news_events:
        for event in news_events:
            try:
                event_results.append(
                    ev.run_event_study(
                        daily_returns, market_returns, event.event_date,
                        event.label, event.category, source_url=event.url,
                    )
                )
            except (ValueError, KeyError) as exc:
                warnings.append(
                    f"{ticker}: evento {event.event_date} omitido del estudio — {exc}"
                )

    return AssetAnalysis(
        ticker=ticker,
        display_name=display_name or ticker,
        prices=prices,
        currency=currency,
        signals=signal_set,
        backtest=result,
        sharpe_assessment=assessment,
        sharpe_ci=ci,
        bootstrap_pvalue=pvalue,
        walk_forward=walk,
        reconciliation=reconciliation,
        anomalies=anomalies,
        event_results=event_results,
        event_aggregates=ev.aggregate_by_category(event_results) if event_results else [],
        warnings=warnings,
    )


def prepare_ypf_local(start: date, end: date) -> tuple[TracedSeries, TracedSeries, list[str]]:
    """Prepara YPFD.BA en dólares CCL, con todas las validaciones del caso argentino.

    Devuelve (precios en USD-CCL, serie de CCL, advertencias).

    Se analiza en dólares y no en pesos nominales porque el retorno nominal en
    ARS es dominado por la inflación: mediría la moneda, no la empresa.
    """
    warnings: list[str] = []

    local = yahoo.fetch_ohlcv("YPFD.BA", start, end)
    adr = yahoo.fetch_ohlcv("YPF", start, end)

    ccl = implied_ccl(local, adr, prices_are_split_adjusted=True)
    ccl_series = ccl.data

    continuity = validate_ccl_continuity(ccl_series)
    warnings.extend(continuity)
    if continuity:
        warnings.append(
            "El CCL implícito muestra un salto en una fecha de acción societaria. "
            "Esto invalida la serie en dólares hasta que se corrija la razón del ADR "
            "o el ajuste por split del proveedor."
        )

    warnings.extend(validate_ccl_level(ccl_series, official_fx=None))

    usd_close = to_usd(local, ccl)

    ohlc_usd = pd.DataFrame(
        {
            "close": usd_close.data,
            "high": (local.data["high"] / ccl_series).reindex(usd_close.data.index),
            "low": (local.data["low"] / ccl_series).reindex(usd_close.data.index),
            "open": (local.data["open"] / ccl_series).reindex(usd_close.data.index),
            "volume": local.data["volume"].reindex(usd_close.data.index),
        }
    ).dropna(subset=["close"])

    usd_traced = local.derive(
        ohlc_usd,
        operation="ypfd_ohlc_en_usd_ccl",
        extra_parents=[ccl],
        notes="OHLC de YPFD.BA convertido a dólares con el CCL implícito diario.",
    )
    return usd_traced, ccl, warnings


def default_window(years: float = 2.0, today: date | None = None) -> tuple[date, date]:
    """Ventana de descarga.

    Se descarga MÁS historia de la que se reporta: las señales necesitan 252
    ruedas previas de calentamiento para estar definidas en el primer día del
    período analizado. Pedir exactamente 2 años dejaría el primer año sin señal.
    """
    end = today or date.today()
    start = end - timedelta(days=int(365.25 * (years + 1.5)))
    return start, end
