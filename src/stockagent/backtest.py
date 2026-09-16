"""Backtest con las tres precauciones que hacen la diferencia entre medir y fantasear.

1. NO HAY SESGO DE ANTICIPACIÓN. La señal calculada con el cierre de t se
   ejecuta al día t+1. Un backtest que opera al mismo cierre que usó para
   decidir asume que se puede ver el precio antes de que exista, y esa sola
   licencia alcanza para convertir una estrategia perdedora en ganadora.

2. LOS COSTOS SE COBRAN. Comisiones, derechos de mercado y deslizamiento se
   descuentan en cada cambio de posición. En BYMA los costos superan
   holgadamente al retorno de muchas estrategias de rotación frecuente.

3. LA EVALUACIÓN ES FUERA DE MUESTRA. `walk_forward` separa el período donde se
   definen las reglas del período donde se las mide. El desempeño dentro de
   muestra no es evidencia de nada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind
from . import statistics as st


@dataclass
class CostModel:
    """Costos de transacción por operación, en tanto por uno sobre el nominal.

    Los valores por defecto son órdenes de magnitud documentados públicamente,
    NO las condiciones de tu cuenta. Reemplazalos por los de tu comitente antes
    de tomar cualquier decisión: la rentabilidad de una estrategia de rotación
    semanal es muy sensible a este número.
    """

    commission: float = 0.0005
    market_fees: float = 0.0001
    slippage: float = 0.0005

    @property
    def total_one_way(self) -> float:
        return self.commission + self.market_fees + self.slippage

    @classmethod
    def us_equity(cls) -> "CostModel":
        """Acciones en EE.UU.: comisión cero en la mayoría de los brokers minoristas.

        El costo real es el deslizamiento contra el punto medio del spread.
        Estimación conservadora para los papeles más líquidos del NASDAQ.
        """
        return cls(commission=0.0000, market_fees=0.0000, slippage=0.0005)

    @classmethod
    def byma_equity(cls) -> "CostModel":
        """Acciones en BYMA: mucho más caro y con menor liquidez.

        Incluye comisión del agente, derechos de mercado y un deslizamiento
        mayor por menor profundidad del libro. Verificá los valores contra el
        tarifario de tu ALyC.
        """
        return cls(commission=0.0050, market_fees=0.0008, slippage=0.0020)


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    positions: pd.Series
    trades: int
    total_costs: float
    gross_return: float
    net_return: float
    cagr: float
    volatility: float
    sharpe: float
    max_drawdown: float
    drawdown_peak: pd.Timestamp | None
    drawdown_trough: pd.Timestamp | None
    time_in_market: float
    benchmark_return: float | None = None
    benchmark_cagr: float | None = None
    benchmark_max_drawdown: float | None = None

    def summary(self) -> str:
        lines = [
            f"Período: {self.equity_curve.index[0]:%Y-%m-%d} a {self.equity_curve.index[-1]:%Y-%m-%d}"
            f" ({len(self.equity_curve)} ruedas)",
            f"Retorno neto total: {self.net_return * 100:+.2f}%",
            f"Retorno bruto (sin costos): {self.gross_return * 100:+.2f}%",
            f"Costos acumulados: {self.total_costs * 100:.2f}% del capital ({self.trades} operaciones)",
            f"CAGR: {self.cagr * 100:+.2f}%",
            f"Volatilidad anualizada: {self.volatility * 100:.2f}%",
            f"Sharpe: {self.sharpe:.2f}",
            f"Caída máxima: {self.max_drawdown * 100:.2f}%",
            f"Tiempo invertido: {self.time_in_market * 100:.1f}% de las ruedas",
        ]
        if self.benchmark_return is not None:
            lines.append(
                f"Comprar y mantener: {self.benchmark_return * 100:+.2f}% "
                f"(CAGR {self.benchmark_cagr * 100:+.2f}%, "
                f"caída máxima {self.benchmark_max_drawdown * 100:.2f}%)"
            )
            delta = self.net_return - self.benchmark_return
            lines.append(
                f"Diferencia contra comprar y mantener: {delta * 100:+.2f} puntos porcentuales"
            )
        return "\n".join(lines)


def run_backtest(
    prices: pd.Series,
    position_flag: pd.Series,
    weights: pd.Series | None = None,
    costs: CostModel | None = None,
    rebalance: str = "W-FRI",
    execution_lag: int = 1,
) -> BacktestResult:
    """Simula la estrategia sobre una serie de precios.

    `position_flag` es 1 (invertido) o 0 (efectivo). `weights` escala el tamaño
    de la posición entre 0 y 1; si es None, la posición es completa.

    `rebalance` limita los cambios de posición a fechas de rebalanceo, de modo
    que la estrategia no reaccione a cada oscilación diaria. El default semanal
    corresponde al horizonte elegido de semanas a meses.
    """
    cost_model = costs or CostModel()

    px = prices.dropna()
    flag = position_flag.reindex(px.index)

    target = flag if weights is None else (flag * weights.reindex(px.index)).clip(0.0, 1.0)

    # Solo se permite cambiar la posición en las fechas de rebalanceo; entre
    # ellas se mantiene la anterior.
    rebalance_dates = px.resample(rebalance).last().index
    is_rebalance = pd.Series(px.index.isin(_snap(px.index, rebalance_dates)), index=px.index)
    target_on_rebalance = target.where(is_rebalance)
    held = target_on_rebalance.ffill()

    # Ejecución diferida: la posición decidida con el cierre de t rige desde t+1.
    executed = held.shift(execution_lag).fillna(0.0)

    asset_returns = px.pct_change().fillna(0.0)
    gross = executed * asset_returns

    turnover = executed.diff().abs().fillna(executed.abs())
    cost_drag = turnover * cost_model.total_one_way
    net = gross - cost_drag

    equity = (1.0 + net).cumprod()
    equity.iloc[0] = 1.0

    years = max((px.index[-1] - px.index[0]).days / 365.25, 1e-9)
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0
    mdd, peak, trough = ind.max_drawdown(equity)

    bench_equity = (1.0 + asset_returns).cumprod()
    bench_mdd, _, _ = ind.max_drawdown(bench_equity)

    return BacktestResult(
        equity_curve=equity,
        returns=net,
        positions=executed,
        trades=int((turnover > 1e-9).sum()),
        total_costs=float(cost_drag.sum()),
        gross_return=float((1.0 + gross).prod() - 1.0),
        net_return=float(equity.iloc[-1] - 1.0),
        cagr=float(cagr),
        volatility=float(net.std(ddof=1) * np.sqrt(st.TRADING_DAYS_PER_YEAR)),
        sharpe=st.sharpe_ratio(net),
        max_drawdown=mdd,
        drawdown_peak=peak,
        drawdown_trough=trough,
        time_in_market=float((executed > 0).mean()),
        benchmark_return=float(bench_equity.iloc[-1] - 1.0),
        benchmark_cagr=float(bench_equity.iloc[-1] ** (1.0 / years) - 1.0),
        benchmark_max_drawdown=bench_mdd,
    )


@dataclass
class WalkForwardResult:
    folds: list[dict]
    oos_returns: pd.Series
    oos_sharpe: float
    in_sample_sharpe_mean: float
    degradation: float

    def summary(self) -> str:
        lines = [
            f"Validación walk-forward con {len(self.folds)} tramos:",
            f"  Sharpe medio dentro de muestra:  {self.in_sample_sharpe_mean:.2f}",
            f"  Sharpe fuera de muestra:         {self.oos_sharpe:.2f}",
            f"  Degradación:                     {self.degradation * 100:+.1f}%",
        ]
        if self.degradation < -0.50:
            lines.append(
                "  LECTURA: el desempeño se derrumba fuera de muestra. Es la firma "
                "característica del sobreajuste."
            )
        elif self.oos_sharpe <= 0:
            lines.append("  LECTURA: la estrategia no genera retorno fuera de muestra.")
        else:
            lines.append("  LECTURA: el desempeño se sostiene fuera de muestra.")
        return "\n".join(lines)


def walk_forward(
    prices: pd.Series,
    signal_builder,
    n_folds: int = 4,
    min_train_days: int = 252,
    costs: CostModel | None = None,
) -> WalkForwardResult:
    """Evalúa la estrategia en ventanas sucesivas, entrenando y midiendo por separado.

    `signal_builder(sub_prices) -> (position_flag, weights|None)`.

    Las ventanas son expansivas y estrictamente cronológicas: cada tramo fuera
    de muestra es posterior a su tramo de entrenamiento. La validación cruzada
    aleatoria, habitual en aprendizaje automático, es inválida con series
    temporales financieras porque filtra información del futuro hacia el pasado.
    """
    px = prices.dropna()
    if len(px) < min_train_days + n_folds * 21:
        raise ValueError(
            f"Serie demasiado corta para walk-forward: {len(px)} ruedas. "
            f"Se necesitan al menos {min_train_days + n_folds * 21}."
        )

    test_size = (len(px) - min_train_days) // n_folds
    folds: list[dict] = []
    oos_chunks: list[pd.Series] = []
    is_sharpes: list[float] = []

    for k in range(n_folds):
        train_end = min_train_days + k * test_size
        test_end = train_end + test_size if k < n_folds - 1 else len(px)

        train_px = px.iloc[:train_end]
        test_px = px.iloc[:test_end]  # incluye historia previa para calcular indicadores

        train_flag, train_w = signal_builder(train_px)
        is_result = run_backtest(train_px, train_flag, train_w, costs)

        test_flag, test_w = signal_builder(test_px)
        full_result = run_backtest(test_px, test_flag, test_w, costs)
        oos_slice = full_result.returns.iloc[train_end:test_end]

        oos_sharpe = st.sharpe_ratio(oos_slice) if len(oos_slice) > 30 else float("nan")
        folds.append(
            {
                "fold": k + 1,
                "train_desde": train_px.index[0].strftime("%Y-%m-%d"),
                "train_hasta": train_px.index[-1].strftime("%Y-%m-%d"),
                "test_desde": px.index[train_end].strftime("%Y-%m-%d"),
                "test_hasta": px.index[test_end - 1].strftime("%Y-%m-%d"),
                "sharpe_is": is_result.sharpe,
                "sharpe_oos": oos_sharpe,
                "retorno_oos": float((1.0 + oos_slice).prod() - 1.0),
            }
        )
        is_sharpes.append(is_result.sharpe)
        oos_chunks.append(oos_slice)

    oos_returns = pd.concat(oos_chunks)
    oos_sharpe = st.sharpe_ratio(oos_returns)
    is_mean = float(np.nanmean(is_sharpes))
    degradation = (oos_sharpe - is_mean) / abs(is_mean) if is_mean not in (0.0, np.nan) else float("nan")

    return WalkForwardResult(
        folds=folds,
        oos_returns=oos_returns,
        oos_sharpe=oos_sharpe,
        in_sample_sharpe_mean=is_mean,
        degradation=float(degradation),
    )


def _snap(index: pd.DatetimeIndex, targets: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Lleva cada fecha de rebalanceo a la rueda efectiva más cercana hacia atrás."""
    snapped = []
    for t in targets:
        candidates = index[index <= t]
        if len(candidates):
            snapped.append(candidates[-1])
    return pd.DatetimeIndex(sorted(set(snapped)))
