"""Comparación cabeza a cabeza entre estrategias.

Condición para que la comparación signifique algo: mismos datos, mismos costos,
misma ejecución diferida a t+1, misma frecuencia de rebalanceo y misma
corrección estadística. Cualquier asimetría convierte la comparación en una
demostración de lo que uno ya quería probar.

Corrección clave: al evaluar N estrategias y quedarse con la mejor, el Deflated
Sharpe debe usar trials = N. Es el mismo problema de siempre — la mejor de
varias luce bien por construcción — y acá se aplica a nosotros mismos.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest as bt
from . import statistics as st
from . import strategies as strat


@dataclass
class StrategyEvaluation:
    name: str
    description: str
    reference: str
    result: bt.BacktestResult
    assessment: st.SharpeAssessment
    sharpe_ci: tuple[float, float, float]
    pvalue: float
    walk_forward: bt.WalkForwardResult | None = None

    @property
    def never_traded(self) -> bool:
        """La estrategia se quedó en efectivo todo el período."""
        return self.result.time_in_market == 0.0

    @property
    def ci_includes_zero(self) -> bool:
        lo, _, hi = self.sharpe_ci
        if np.isnan(lo) or np.isnan(hi):
            return False  # sin intervalo no se puede afirmar nada, ni a favor ni en contra
        return bool(lo <= 0 <= hi)


@dataclass
class Comparison:
    asset: str
    evaluations: list[StrategyEvaluation]
    pbo: dict[str, float] | None
    period: tuple[pd.Timestamp, pd.Timestamp]
    observations: int
    warnings: list[str]

    def best_by_sharpe(self) -> StrategyEvaluation:
        return max(self.evaluations, key=lambda e: e.result.sharpe)

    def table(self) -> str:
        lines = [
            "| Estrategia | Retorno neto | CAGR | Sharpe | IC 95% | Caída máx. | Oper. | Costos | % invertido | DSR |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for e in self.evaluations:
            if e.never_traded:
                lines.append(
                    f"| {e.name} | — | — | — | — | — | 0 | — | 0% | — |"
                )
                continue
            lo, _, hi = e.sharpe_ci
            zero = " ⚠" if e.ci_includes_zero else ""
            lines.append(
                f"| {e.name} | {e.result.net_return * 100:+.1f}% | "
                f"{e.result.cagr * 100:+.1f}% | {e.result.sharpe:.2f} | "
                f"[{lo:.2f}, {hi:.2f}]{zero} | {e.result.max_drawdown * 100:.1f}% | "
                f"{e.result.trades} | {e.result.total_costs * 100:.2f}% | "
                f"{e.result.time_in_market * 100:.0f}% | {e.assessment.deflated_sharpe:.3f} |"
            )
        return "\n".join(lines)

    def verdict(self) -> str:
        """Lectura honesta del resultado, incluyendo el caso en que no hay ganador."""
        lines: list[str] = []

        survivors = [e for e in self.evaluations if e.assessment.deflated_sharpe >= 0.95]
        bh = next((e for e in self.evaluations if "mantener" in e.name.lower()), None)
        active = [e for e in self.evaluations if e is not bh]

        if not survivors:
            lines.append(
                "NINGUNA estrategia supera el Deflated Sharpe al 95%. Con esta muestra "
                "no se puede afirmar que ninguna de las dos tenga habilidad: las "
                "diferencias entre ellas son compatibles con el azar."
            )
        else:
            nombres = ", ".join(e.name for e in survivors)
            lines.append(f"Superan el ajuste por múltiples pruebas: {nombres}.")

        if bh is not None and active:
            mejor_activa = max(active, key=lambda e: e.result.net_return)
            delta = mejor_activa.result.net_return - bh.result.net_return
            if delta > 0:
                lines.append(
                    f"La mejor estrategia activa ({mejor_activa.name}) le sacó "
                    f"{delta * 100:+.1f} puntos porcentuales a comprar y mantener."
                )
            else:
                lines.append(
                    f"NINGUNA estrategia activa le ganó a comprar y mantener. La mejor "
                    f"({mejor_activa.name}) quedó {delta * 100:.1f} puntos por debajo. "
                    "Operar agregó costos, riesgo operativo y trabajo, sin compensación."
                )

        idle = [e.name for e in self.evaluations if e.never_traded]
        if idle:
            lines.append(
                f"NO ABRIÓ POSICIÓN EN NINGÚN MOMENTO: {', '.join(idle)}. La regla de "
                "entrada nunca se cumplió en este período, así que la estrategia quedó "
                "en efectivo. No es un empate: es no haber participado."
            )

        with_zero = [e.name for e in self.evaluations if e.ci_includes_zero]
        if with_zero:
            lines.append(
                f"Intervalo de confianza del Sharpe incluye el cero en: {', '.join(with_zero)}. "
                "Para esas, no se puede descartar que el retorno sea puro azar."
            )

        if self.observations < 504:
            lines.append(
                f"ADVERTENCIA: {self.observations} observaciones. Es una muestra chica "
                "para distinguir estrategias entre sí; las conclusiones son provisorias."
            )

        return "\n".join(f"- {line}" for line in lines)


def compare_strategies(
    prices: pd.Series,
    asset: str,
    catalog: strat.StrategyCatalog | None = None,
    costs: bt.CostModel | None = None,
    rebalance: str = "W-FRI",
    run_walk_forward: bool = True,
    volatility_weights: pd.Series | None = None,
) -> Comparison:
    """Corre todas las estrategias del catálogo sobre el mismo activo."""
    cat = catalog or strat.StrategyCatalog()
    cost_model = costs or bt.CostModel.us_equity()
    px = prices.dropna()

    warnings: list[str] = []
    results = cat.build_all(px)
    evaluations: list[StrategyEvaluation] = []

    for strategy in results:
        # Comprar y mantener se evalúa sin dimensionamiento por volatilidad: es
        # el comparador crudo, y escalarlo lo convertiría en otra estrategia.
        weights = None if "mantener" in strategy.name.lower() else volatility_weights

        result = bt.run_backtest(
            px, strategy.position, weights, cost_model, rebalance=rebalance
        )

        evaluations.append(
            StrategyEvaluation(
                name=strategy.name,
                description=strategy.description,
                reference=strategy.reference,
                result=result,
                # trials = cantidad de estrategias comparadas: al quedarnos con la
                # mejor de N, el listón estadístico sube.
                assessment=st.assess_sharpe(result.returns, trials=cat.n_strategies),
                sharpe_ci=st.bootstrap_sharpe_ci(result.returns),
                pvalue=st.bootstrap_pvalue(result.returns),
            )
        )

    pbo = None
    matrix = pd.DataFrame({e.name: e.result.returns for e in evaluations}).dropna()
    try:
        pbo = st.probability_of_backtest_overfitting(matrix, n_splits=8)
    except ValueError as exc:
        warnings.append(f"PBO no calculable: {exc}")

    if run_walk_forward:
        for evaluation, strategy in zip(evaluations, results):
            if "mantener" in strategy.name.lower():
                continue
            try:
                builder = _make_builder(strategy.name, cat)
                evaluation.walk_forward = bt.walk_forward(
                    px, builder, n_folds=4, costs=cost_model
                )
            except ValueError as exc:
                warnings.append(f"{strategy.name}: sin walk-forward — {exc}")

    return Comparison(
        asset=asset,
        evaluations=evaluations,
        pbo=pbo,
        period=(px.index[0], px.index[-1]),
        observations=len(px),
        warnings=warnings,
    )


def _make_builder(strategy_name: str, catalog: strat.StrategyCatalog):
    """Devuelve un constructor de señales para la validación walk-forward."""

    def builder(sub_prices: pd.Series):
        if "Momentum" in strategy_name:
            return strat.momentum_trend(sub_prices, catalog.signal_config).position, None
        if "Reversión" in strategy_name:
            return strat.mean_reversion(sub_prices, catalog.reversion_config).position, None
        return strat.buy_and_hold(sub_prices).position, None

    return builder


def render_comparison(comparison: Comparison) -> str:
    """Sección de reporte con la comparación entre estrategias."""
    out = [
        f"## Comparación de estrategias — {comparison.asset}",
        "",
        f"Período: {comparison.period[0]:%Y-%m-%d} a {comparison.period[1]:%Y-%m-%d} "
        f"({comparison.observations} ruedas)",
        "",
        comparison.table(),
        "",
        "⚠ = el intervalo de confianza del Sharpe incluye el cero: no se puede "
        "afirmar que esa estrategia tenga habilidad.",
        "",
        "### Veredicto",
        "",
        comparison.verdict(),
        "",
    ]

    if comparison.pbo is not None:
        out += ["### Sobreajuste", "", st.interpret_pbo(comparison.pbo.get("pbo", float("nan"))), ""]

    out += ["### Qué hace cada una", ""]
    for e in comparison.evaluations:
        out += [f"**{e.name}**  ", f"{e.description}  ", f"*{e.reference}*", ""]

    wf = [e for e in comparison.evaluations if e.walk_forward]
    if wf:
        out += ["### Validación fuera de muestra", ""]
        for e in wf:
            out += [f"**{e.name}**", "", "```", e.walk_forward.summary(), "```", ""]

    if comparison.warnings:
        out += ["### Advertencias", ""] + [f"- {w}" for w in comparison.warnings] + [""]

    return "\n".join(out)
