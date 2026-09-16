"""Generación del reporte en Markdown.

Regla de redacción del reporte: toda cifra va acompañada de su incertidumbre o
de la advertencia de que no la tiene. Un reporte que dice "Sharpe 1,8" sin decir
que el intervalo de confianza incluye el cero está ocultando el resultado más
importante.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .pipeline import AssetAnalysis
from .provenance import DataKind
from .statistics import interpret_pbo
from .universe import UniverseResolution


def render_report(
    analyses: list[AssetAnalysis],
    universe: UniverseResolution | None = None,
    pbo: dict[str, float] | None = None,
    global_warnings: list[str] | None = None,
    trials_evaluated: int = 1,
) -> str:
    now = datetime.now(timezone.utc)
    out: list[str] = []

    out.append("# Reporte de análisis cuantitativo de acciones")
    out.append(f"\nGenerado: {now:%Y-%m-%d %H:%M} UTC\n")

    out.append("> **Este reporte no es asesoramiento financiero.** Es el resultado de un")
    out.append("> procedimiento estadístico sobre datos históricos. El desempeño pasado no")
    out.append("> predice el futuro, y toda inversión puede perder la totalidad del capital.")
    out.append("> Las decisiones son responsabilidad exclusiva de quien las toma.\n")

    if global_warnings:
        out.append("## Advertencias de esta corrida\n")
        for w in global_warnings:
            out.append(f"- {w}")
        out.append("")

    out.append("## Cómo leer este reporte\n")
    out.append(
        "El indicador decisivo NO es el retorno del backtest sino el **Deflated Sharpe "
        "Ratio (DSR)**, que descuenta el hecho de haber probado varias configuraciones. "
        f"En esta corrida se declararon **{trials_evaluated} configuraciones evaluadas**. "
        "Un DSR por debajo de 0,95 significa que el resultado NO es distinguible de la "
        "suerte, por atractivo que luzca el retorno."
    )
    out.append("")

    out.append("## Resumen de señales vigentes\n")
    out.append("| Activo | Fecha | Momentum 12-1 | Sobre SMA200 | Cerca máx. 52s | Score | Decisión |")
    out.append("|---|---|---|---|---|---|---|")
    for a in analyses:
        b = a.signals.latest_breakdown()
        if b.get("estado"):
            out.append(f"| {a.display_name} | — | — | — | — | — | SIN DATOS |")
            continue
        out.append(
            f"| {a.display_name} | {b['fecha']} | "
            f"{b['momentum_12_1'] * 100:+.1f}% ({b['momentum_vota']}) | "
            f"{b['sobre_sma200']} | "
            f"{b['cercania_max_52s'] * 100:.0f}% ({b['cerca_del_maximo_vota']}) | "
            f"{b['score_compuesto']:.2f} | **{b['decision']}** |"
        )
    out.append("")
    out.append(
        "La decisión exige que al menos 2 de 3 señales independientes coincidan. "
        "`EFECTIVO` significa no tener el papel, no significa venderlo en corto."
    )
    out.append("")

    out.append("## Validez estadística\n")
    out.append("| Activo | Sharpe | IC 95% | p-valor | DSR | Veredicto |")
    out.append("|---|---|---|---|---|---|")
    for a in analyses:
        s = a.sharpe_assessment
        lo, _, hi = a.sharpe_ci
        crosses_zero = "**incluye 0**" if (lo <= 0 <= hi) else "no incluye 0"
        out.append(
            f"| {a.display_name} | {s.sharpe_annual:.2f} | "
            f"[{lo:.2f}, {hi:.2f}] ({crosses_zero}) | "
            f"{a.bootstrap_pvalue:.3f} | {s.deflated_sharpe:.3f} | "
            f"{'PASA' if s.deflated_sharpe >= 0.95 else 'NO PASA'} |"
        )
    out.append("")
    out.append(
        "El intervalo de confianza surge de bootstrap estacionario (Politis & Romano, "
        "1994), que preserva la autocorrelación de los retornos. Si el intervalo "
        "incluye el cero, no se puede afirmar que la estrategia tenga habilidad."
    )
    out.append("")

    if pbo is not None:
        out.append("### Probabilidad de sobreajuste del backtest\n")
        out.append(f"{interpret_pbo(pbo.get('pbo', float('nan')))}")
        out.append(f"\n(Calculado sobre {pbo.get('n_combinations', 0)} particiones combinatorias.)\n")

    for a in analyses:
        out.append(f"\n---\n\n## {a.display_name} ({a.ticker})\n")
        out.append(f"Moneda de análisis: **{a.currency}**\n")

        out.append("### Calidad de los datos\n")
        out.append(f"- {a.reconciliation.summary()}")
        if a.anomalies:
            for kind, days in a.anomalies.items():
                out.append(f"- Anomalía `{kind}`: {', '.join(days[:5])}" + (" ..." if len(days) > 5 else ""))
        else:
            out.append("- Sin anomalías detectadas (precios positivos, sin fechas duplicadas, sin saltos extremos).")
        out.append("")

        out.append("### Desempeño histórico de la estrategia\n")
        out.append("```")
        out.append(a.backtest.summary())
        out.append("```\n")

        s = a.sharpe_assessment
        out.append("### Lectura estadística\n")
        out.append(f"- Observaciones: {s.observations}")
        out.append(f"- Asimetría: {s.skewness:+.2f} | Curtosis: {s.kurtosis:.2f}")
        out.append(f"- Probabilistic Sharpe Ratio: {s.psr:.3f}")
        out.append(f"- Sharpe máximo esperado por azar entre {s.trials} pruebas: {s.expected_max_sharpe_under_null:.3f}")
        out.append(f"- Deflated Sharpe Ratio: **{s.deflated_sharpe:.3f}**")
        out.append(f"\n> {s.verdict()}\n")

        if a.walk_forward:
            out.append("### Validación fuera de muestra\n")
            out.append("```")
            out.append(a.walk_forward.summary())
            out.append("```\n")
            out.append("| Tramo | Entrenamiento | Prueba | Sharpe IS | Sharpe OOS | Retorno OOS |")
            out.append("|---|---|---|---|---|---|")
            for f in a.walk_forward.folds:
                out.append(
                    f"| {f['fold']} | {f['train_desde']}..{f['train_hasta']} | "
                    f"{f['test_desde']}..{f['test_hasta']} | {f['sharpe_is']:.2f} | "
                    f"{f['sharpe_oos']:.2f} | {f['retorno_oos'] * 100:+.1f}% |"
                )
            out.append("")

        if a.event_results:
            out.append("### Estudio de eventos\n")
            out.append(
                "Retornos anormales medidos contra un modelo de mercado estimado sobre "
                "250 ruedas previas a cada evento (MacKinlay, 1997).\n"
            )
            for agg in a.event_aggregates:
                out.append(f"- {agg.describe()}")
            out.append("\n<details><summary>Eventos individuales</summary>\n")
            for r in sorted(a.event_results, key=lambda x: x.event_date, reverse=True)[:30]:
                link = f" [fuente]({r.source_url})" if r.source_url else ""
                out.append(f"- {r.describe()}{link}")
            out.append("\n</details>\n")

        if a.warnings:
            out.append("### Advertencias\n")
            for w in a.warnings:
                out.append(f"- {w}")
            out.append("")

        out.append("<details><summary>Procedencia de los datos</summary>\n")
        out.append("```")
        out.append(a.prices.lineage_report())
        out.append("```\n</details>\n")

    if universe:
        out.append("\n---\n\n## Universo analizado\n")
        out.append("```")
        out.append(universe.summary())
        out.append("```\n")
        for w in universe.warnings:
            out.append(f"- {w}")

    out.append("\n---\n\n## Limitaciones\n")
    out.append(
        "1. **Tamaño de muestra.** Dos años de datos diarios son ~500 observaciones. "
        "Alcanza para describir el período, no para validar una estrategia con "
        "confianza. Las conclusiones ganan solidez con 10 o más años.\n"
        "2. **Sesgo de supervivencia.** Analizar las mayores empresas de HOY selecciona "
        "justamente a las que subieron. Cualquier estrategia parece buena sobre las "
        "ganadoras conocidas de antemano.\n"
        "3. **Costos de transacción.** Los valores usados son estimaciones y no las "
        "condiciones de tu cuenta. En BYMA pueden cambiar el resultado por completo.\n"
        "4. **Riesgo específico argentino.** YPF está expuesta a controles de cambio, "
        "regulación de precios internos y litigios internacionales. Son riesgos de cola "
        "que ninguna serie de precios de dos años refleja.\n"
        "5. **El régimen puede cambiar.** Todo lo anterior supone que el futuro se parece "
        "estadísticamente al pasado. Cuando eso deja de valer, el modelo falla justo "
        "cuando más importa.\n"
    )

    return "\n".join(out)


def assert_no_synthetic_data(analyses: list[AssetAnalysis]) -> None:
    """Barrera final: aborta si algún dato sintético llegó hasta el reporte."""
    for a in analyses:
        a.prices.assert_report_safe()
        for p in a.prices.lineage:
            if p.kind is DataKind.SYNTHETIC:
                raise RuntimeError(f"Dato sintético en el reporte: {a.ticker} / {p.source_id}")
