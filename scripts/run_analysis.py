#!/usr/bin/env python3
"""Corrida completa del análisis.

Uso:
    python scripts/run_analysis.py                    # NVDA + YPFD.BA + top 10 NASDAQ
    python scripts/run_analysis.py --solo NVDA,YPFD.BA
    python scripts/run_analysis.py --sin-eventos      # saltea el estudio de eventos
    python scripts/run_analysis.py --anios 3

Requiere conexión a internet: descarga precios de Yahoo Finance y Stooq,
presentaciones de SEC EDGAR y la composición del Nasdaq-100 desde las tenencias
del ETF QQQ. No hay modo "sin datos": el programa no inventa series.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from stockagent import backtest as bt  # noqa: E402
from stockagent import news as nw  # noqa: E402
from stockagent import pipeline as pl  # noqa: E402
from stockagent import report as rp  # noqa: E402
from stockagent import signals as sg  # noqa: E402
from stockagent import compare as cmpx  # noqa: E402
from stockagent import statistics as st  # noqa: E402
from stockagent import strategies as strat  # noqa: E402
from stockagent import universe as uv  # noqa: E402
from stockagent.datasources import yahoo  # noqa: E402
from stockagent.provenance import MissingDataError, dump_lineage  # noqa: E402


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_pipeline_config(cfg: dict, years: float) -> pl.PipelineConfig:
    e = cfg["estrategia"]
    v = cfg["validacion"]
    return pl.PipelineConfig(
        years=years,
        trials_evaluated=int(v["configuraciones_evaluadas"]),
        target_annual_vol=float(e["volatilidad_objetivo_anual"]),
        atr_multiple=float(e["multiplo_atr_stop"]),
        rebalance=e["rebalanceo"],
        walk_forward_folds=int(v["tramos_walk_forward"]),
        benchmark=cfg["activos"]["benchmark"]["ticker"],
        signal_config=sg.SignalConfig(
            momentum_lookback_months=int(e["momentum_lookback_meses"]),
            momentum_skip_months=int(e["momentum_skip_meses"]),
            trend_sma_window=int(e["sma_tendencia"]),
            high_52w_window=int(e["maximo_52_semanas"]),
            high_52w_threshold=float(e["umbral_cercania_maximo"]),
            vote_threshold=float(e["umbral_voto"]),
        ),
    )


def cost_from(cfg: dict, key: str) -> bt.CostModel:
    c = cfg["costos"][key]
    return bt.CostModel(
        commission=float(c["comision"]),
        market_fees=float(c["derechos_mercado"]),
        slippage=float(c["deslizamiento"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Análisis cuantitativo de acciones")
    parser.add_argument("--config", default=str(ROOT / "config" / "analysis.yaml"))
    parser.add_argument("--anios", type=float, default=None)
    parser.add_argument("--solo", default=None, help="Lista de tickers separados por coma")
    parser.add_argument("--sin-eventos", action="store_true")
    parser.add_argument("--sin-nasdaq-top", action="store_true")
    parser.add_argument(
        "--comparar",
        action="store_true",
        help="Comparar momentum vs reversión a la media vs comprar y mantener",
    )
    parser.add_argument("--salida", default=str(ROOT / "reports" / "reporte.md"))
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    years = args.anios or float(cfg["ventana"]["anios_reportados"])
    pconf = build_pipeline_config(cfg, years)
    start, end = pl.default_window(years)

    print(f"Ventana de descarga: {start} a {end} "
          f"(se reportan los últimos {years:g} años; el resto es calentamiento de indicadores)")

    global_warnings: list[str] = []
    analyses: list[pl.AssetAnalysis] = []
    comparisons: list[str] = []
    lineage: dict = {}

    # --- Benchmark: necesario para el modelo de mercado del estudio de eventos ---
    print(f"Descargando benchmark {pconf.benchmark} ...")
    try:
        bench = yahoo.fetch_ohlcv(pconf.benchmark, start, end)
        market_returns = bench.data["close"].pct_change().dropna()
    except MissingDataError as exc:
        print(f"ERROR: no se pudo descargar el benchmark: {exc}", file=sys.stderr)
        print("El estudio de eventos requiere un índice de referencia. Se aborta.", file=sys.stderr)
        return 1

    selected = [t.strip() for t in args.solo.split(",")] if args.solo else None

    # --- NVIDIA ---
    if selected is None or "NVDA" in selected:
        print("Analizando NVDA ...")
        try:
            prices, recon, anomalies, warns = pl.load_asset(
                "NVDA", start, end, float(cfg["validacion"]["tolerancia_discrepancia_fuentes_pct"])
            )
            events = [] if args.sin_eventos else _safe_events("NVDA", start, global_warnings)
            analyses.append(
                pl.analyze_asset(
                    "NVDA", prices, market_returns, pconf, cost_from(cfg, "eeuu"),
                    recon, anomalies, warns, display_name="NVIDIA", currency="USD",
                    news_events=events,
                )
            )
            lineage["NVDA"] = prices
        except (MissingDataError, ValueError) as exc:
            global_warnings.append(f"NVDA no pudo analizarse: {exc}")
            print(f"  FALLÓ: {exc}", file=sys.stderr)

    # --- YPF local en BYMA, convertido a USD CCL ---
    if selected is None or "YPFD.BA" in selected:
        print("Analizando YPFD.BA (BYMA) con conversión a USD CCL ...")
        try:
            usd_prices, ccl, ypf_warns = pl.prepare_ypf_local(start, end)
            print(f"  CCL implícito: {ccl.data.iloc[-1]:,.0f} ARS/USD "
                  f"al {ccl.data.index[-1]:%Y-%m-%d}")
            recon, anomalies, warns = _validate_local(usd_prices, ypf_warns)
            events = [] if args.sin_eventos else _safe_events("YPF", start, global_warnings)
            analyses.append(
                pl.analyze_asset(
                    "YPFD.BA", usd_prices, market_returns, pconf, cost_from(cfg, "byma"),
                    recon, anomalies, warns,
                    display_name="YPF (BYMA en USD CCL)", currency="USD CCL",
                    news_events=events,
                )
            )
            lineage["YPFD.BA"] = usd_prices
        except (MissingDataError, ValueError) as exc:
            global_warnings.append(f"YPFD.BA no pudo analizarse: {exc}")
            print(f"  FALLÓ: {exc}", file=sys.stderr)

    # --- Top 10 del NASDAQ ---
    resolution = None
    if not args.sin_nasdaq_top and selected is None:
        print("Resolviendo el top 10 del NASDAQ por capitalización ...")
        resolution = uv.resolve_nasdaq_top(
            int(cfg["nasdaq_top"]["cantidad"]),
            allow_fallback=bool(cfg["nasdaq_top"]["permitir_respaldo"]),
        )
        print(f"  {resolution.summary().splitlines()[0]}")
        if resolution.is_fallback:
            global_warnings.append(
                f"El universo del NASDAQ usó la lista de respaldo del {uv.FALLBACK_DATE}."
            )

        for ticker in resolution.tickers:
            if ticker == "NVDA":
                continue
            print(f"  Analizando {ticker} ...")
            try:
                prices, recon, anomalies, warns = pl.load_asset("" + ticker, start, end)
                analyses.append(
                    pl.analyze_asset(
                        ticker, prices, market_returns, pconf, cost_from(cfg, "eeuu"),
                        recon, anomalies, warns, currency="USD", news_events=None,
                    )
                )
                lineage[ticker] = prices
            except (MissingDataError, ValueError) as exc:
                global_warnings.append(f"{ticker} omitido: {exc}")
                print(f"    omitido: {exc}", file=sys.stderr)

    if not analyses:
        print("No se pudo analizar ningún activo. Revisá la conectividad.", file=sys.stderr)
        return 1

    # --- Comparación entre estrategias, si se pidió ---
    if args.comparar:
        print("\nComparando estrategias (momentum vs reversión vs comprar y mantener) ...")
        catalogo = strat.StrategyCatalog(signal_config=pconf.signal_config)
        for a in analyses:
            close = a.prices.data["close"] if hasattr(a.prices.data, "columns") else a.prices.data
            costos = cost_from(cfg, "byma") if a.ticker.endswith(".BA") else cost_from(cfg, "eeuu")
            try:
                comparacion = cmpx.compare_strategies(
                    close.dropna(), a.display_name, catalog=catalogo,
                    costs=costos, rebalance=pconf.rebalance,
                )
                comparisons.append(cmpx.render_comparison(comparacion))
                mejor = comparacion.best_by_sharpe()
                print(f"  {a.display_name}: mejor por Sharpe -> {mejor.name}")
            except (ValueError, KeyError) as exc:
                global_warnings.append(f"{a.ticker}: comparación no realizada — {exc}")
                print(f"  {a.display_name}: falló la comparación — {exc}", file=sys.stderr)

    # --- PBO sobre el conjunto de estrategias evaluadas ---
    pbo = None
    if len(analyses) >= 2:
        matrix = pd.DataFrame({a.ticker: a.backtest.returns for a in analyses}).dropna()
        try:
            pbo = st.probability_of_backtest_overfitting(matrix, n_splits=8)
        except ValueError as exc:
            global_warnings.append(f"PBO no calculable: {exc}")

    # --- Barrera anti datos sintéticos y escritura ---
    rp.assert_no_synthetic_data(analyses)
    markdown = rp.render_report(
        analyses, universe=resolution, pbo=pbo,
        global_warnings=global_warnings, trials_evaluated=pconf.trials_evaluated,
    )

    if comparisons:
        markdown += "\n\n---\n\n" + "\n\n---\n\n".join(comparisons)

    out_path = Path(args.salida)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    lineage_path = out_path.with_suffix(".procedencia.json")
    dump_lineage(lineage, str(lineage_path))

    print(f"\nReporte:     {out_path}")
    print(f"Procedencia: {lineage_path}")
    print(f"Activos analizados: {len(analyses)}")
    if global_warnings:
        print(f"Advertencias: {len(global_warnings)} (ver el reporte)")
    return 0


def _safe_events(ticker: str, since: date, global_warnings: list[str]) -> list[nw.NewsEvent]:
    """Descarga eventos de SEC EDGAR sin frenar el análisis si la fuente falla."""
    try:
        events = nw.fetch_sec_filings(ticker, since)
        print(f"  {len(events)} presentaciones ante la SEC desde {since}")
        return events
    except Exception as exc:  # noqa: BLE001
        global_warnings.append(
            f"No se pudieron obtener eventos de SEC EDGAR para {ticker}: "
            f"{type(exc).__name__}: {exc}. El estudio de eventos queda sin realizar "
            "para ese activo (no se sustituye por estimaciones)."
        )
        return []


def _validate_local(prices, extra_warnings: list[str]):
    """Valida la serie convertida a USD. Stooq no cubre BYMA: no hay segunda fuente."""
    from stockagent.datasources import crossvalidate

    recon = crossvalidate.reconcile("YPFD.BA", prices, None)
    anomalies = crossvalidate.detect_data_anomalies(prices.data["close"])
    warns = list(extra_warnings)
    warns.append(
        "YPFD.BA no tiene segunda fuente pública confiable: la serie depende "
        "únicamente de Yahoo Finance. Además, la conversión a USD depende de la "
        "razón del ADR, verificable en los formularios 6-K de SEC EDGAR."
    )
    for kind, days in anomalies.items():
        warns.append(f"Anomalía '{kind}': {days[:5]}" + (" ..." if len(days) > 5 else ""))
    return recon, anomalies, warns


if __name__ == "__main__":
    raise SystemExit(main())
