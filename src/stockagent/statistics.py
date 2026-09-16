"""Estadística para evaluar estrategias sin engañarse.

El problema central del backtesting no es calcular un Sharpe: es que si probás
muchas estrategias y te quedás con la mejor, su Sharpe está sesgado hacia
arriba por construcción, aunque ninguna tenga poder predictivo real. Un Sharpe
de 2 sobre la mejor de 100 variantes probadas puede ser exactamente lo que se
espera del puro azar.

Este módulo implementa los correctivos publicados para ese problema:
  - Probabilistic Sharpe Ratio y Deflated Sharpe Ratio, que ajustan por número
    de pruebas, asimetría, curtosis y largo de la muestra.
  - Probability of Backtest Overfitting por validación cruzada combinatoria.
  - Bootstrap estacionario, que construye intervalos de confianza respetando la
    autocorrelación de los retornos.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329
TRADING_DAYS_PER_YEAR = 252


@dataclass
class SharpeAssessment:
    sharpe_annual: float
    sharpe_per_period: float
    observations: int
    skewness: float
    kurtosis: float
    psr: float
    deflated_sharpe: float
    expected_max_sharpe_under_null: float
    trials: int
    min_track_record_length: float

    def verdict(self) -> str:
        if self.observations < 252:
            base = (
                f"MUESTRA INSUFICIENTE: {self.observations} observaciones. "
                "Cualquier conclusión es provisoria."
            )
        elif self.deflated_sharpe >= 0.95:
            base = "El Sharpe sobrevive al ajuste por múltiples pruebas con 95% de confianza."
        elif self.deflated_sharpe >= 0.90:
            base = "Evidencia moderada: el Sharpe sobrevive al ajuste con 90% de confianza."
        else:
            base = (
                "NO HAY EVIDENCIA ESTADÍSTICA de habilidad: una vez descontado el "
                "número de pruebas, este Sharpe es compatible con el azar."
            )
        if self.min_track_record_length > self.observations:
            base += (
                f" Harían falta {self.min_track_record_length:.0f} observaciones "
                f"(hay {self.observations}) para distinguirlo de cero con 95% de confianza."
            )
        return base


def sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.0,
                 annualize: bool = True) -> float:
    """Sharpe sobre retornos periódicos, con tasa libre de riesgo opcional."""
    if len(returns) < 2:
        return float("nan")
    rf_per_period = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = returns - rf_per_period
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    sr = excess.mean() / sd
    return float(sr * np.sqrt(TRADING_DAYS_PER_YEAR)) if annualize else float(sr)


def probabilistic_sharpe_ratio(returns: pd.Series, benchmark_sr_per_period: float = 0.0) -> float:
    """Probabilidad de que el Sharpe verdadero supere al de referencia.

    Referencia: Bailey & López de Prado (2012), "The Sharpe Ratio Efficient
    Frontier", Journal of Risk 15(2), 3-44.

    Corrige por dos patologías que el Sharpe clásico ignora: los retornos de
    estrategias reales tienen asimetría negativa y colas gruesas, lo que infla
    el Sharpe medido respecto de su verdadera calidad ajustada por riesgo.
    """
    r = returns.dropna()
    n = len(r)
    if n < 3:
        return float("nan")

    sr = sharpe_ratio(r, annualize=False)
    if np.isnan(sr):
        return float("nan")

    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=False, bias=False))  # curtosis cruda, normal = 3

    denominator = np.sqrt(max(1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2, 1e-12))
    z = (sr - benchmark_sr_per_period) * np.sqrt(n - 1) / denominator
    return float(stats.norm.cdf(z))


def expected_max_sharpe(trials: int, sharpe_variance_across_trials: float) -> float:
    """Sharpe máximo esperado entre `trials` estrategias SIN habilidad alguna.

    Referencia: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio",
    Journal of Portfolio Management 40(5), 94-107.

    Es el umbral que hay que superar para poder afirmar que hay algo más que
    suerte: si probás 100 variantes de ruido, la mejor va a lucir bien.
    """
    if trials < 1:
        raise ValueError("trials debe ser >= 1")
    if trials == 1:
        return 0.0

    sigma = np.sqrt(max(sharpe_variance_across_trials, 1e-12))
    z1 = stats.norm.ppf(1.0 - 1.0 / trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (trials * np.e))
    return float(sigma * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2))


def deflated_sharpe_ratio(returns: pd.Series, trials: int,
                          sharpe_variance_across_trials: float | None = None,
                          all_trial_sharpes: list[float] | None = None) -> float:
    """PSR evaluado contra el Sharpe máximo esperado bajo la hipótesis nula.

    `trials` debe ser el número REAL de configuraciones evaluadas durante toda
    la investigación, incluidas las descartadas. Reportar solo las que
    sobrevivieron es la forma más común de mentirse con estadística.
    """
    if sharpe_variance_across_trials is None:
        if all_trial_sharpes and len(all_trial_sharpes) > 1:
            sharpe_variance_across_trials = float(np.var(all_trial_sharpes, ddof=1))
        else:
            # Sin dispersión observada se usa la varianza asintótica del Sharpe
            # bajo normalidad, 1/(n-1), que es la hipótesis más conservadora
            # disponible con la información a mano.
            sharpe_variance_across_trials = 1.0 / max(len(returns) - 1, 1)

    sr_star = expected_max_sharpe(trials, sharpe_variance_across_trials)
    return probabilistic_sharpe_ratio(returns, benchmark_sr_per_period=sr_star)


def min_track_record_length(returns: pd.Series, target_confidence: float = 0.95,
                            benchmark_sr_per_period: float = 0.0) -> float:
    """Observaciones necesarias para afirmar que el Sharpe supera al de referencia.

    Referencia: Bailey & López de Prado (2012), misma fuente que el PSR.
    Responde a la pregunta que todo backtest corto esquiva: ¿alcanza este
    historial para concluir algo?
    """
    r = returns.dropna()
    if len(r) < 3:
        return float("nan")

    sr = sharpe_ratio(r, annualize=False)
    if np.isnan(sr) or sr <= benchmark_sr_per_period:
        return float("inf")

    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=False, bias=False))
    z = stats.norm.ppf(target_confidence)

    numerator = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr**2
    return float(1.0 + numerator * (z / (sr - benchmark_sr_per_period)) ** 2)


def assess_sharpe(returns: pd.Series, trials: int,
                  all_trial_sharpes: list[float] | None = None) -> SharpeAssessment:
    """Evaluación completa del Sharpe con todos los ajustes aplicados."""
    r = returns.dropna()
    return SharpeAssessment(
        sharpe_annual=sharpe_ratio(r),
        sharpe_per_period=sharpe_ratio(r, annualize=False),
        observations=len(r),
        skewness=float(stats.skew(r, bias=False)) if len(r) > 2 else float("nan"),
        kurtosis=float(stats.kurtosis(r, fisher=False, bias=False)) if len(r) > 3 else float("nan"),
        psr=probabilistic_sharpe_ratio(r),
        deflated_sharpe=deflated_sharpe_ratio(r, trials, all_trial_sharpes=all_trial_sharpes),
        expected_max_sharpe_under_null=expected_max_sharpe(
            trials,
            float(np.var(all_trial_sharpes, ddof=1))
            if all_trial_sharpes and len(all_trial_sharpes) > 1
            else 1.0 / max(len(r) - 1, 1),
        ),
        trials=trials,
        min_track_record_length=min_track_record_length(r),
    )


def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Índices de un remuestreo por bootstrap estacionario.

    Referencia: Politis & Romano (1994), "The Stationary Bootstrap", Journal of
    the American Statistical Association 89(428), 1303-1313.

    Remuestrear observación por observación destruiría la autocorrelación y la
    agrupación de volatilidad de los retornos financieros, produciendo
    intervalos de confianza demasiado angostos. Los bloques de largo geométrico
    la preservan.
    """
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty(n, dtype=int)
    current = rng.integers(0, n)
    for i in range(n):
        idx[i] = current
        if rng.random() < p:
            current = rng.integers(0, n)
        else:
            current = (current + 1) % n
    return idx


def bootstrap_sharpe_ci(returns: pd.Series, n_boot: int = 2000, mean_block: float = 21.0,
                        confidence: float = 0.95, seed: int = 42) -> tuple[float, float, float]:
    """Intervalo de confianza del Sharpe anualizado por bootstrap estacionario.

    Devuelve (límite inferior, estimación puntual, límite superior). Si el
    límite inferior es negativo, no se puede descartar que la estrategia no
    tenga habilidad alguna.
    """
    r = returns.dropna().to_numpy()
    n = len(r)
    if n < 30:
        return float("nan"), sharpe_ratio(returns), float("nan")

    # Una estrategia que nunca abrió posición produce retornos constantemente
    # cero: no tiene Sharpe ni intervalo de confianza. No es un error de
    # cálculo, es que no operó, y corresponde devolverlo como "sin dato" en
    # lugar de romper o de fabricar un número.
    if r.std(ddof=1) == 0:
        return float("nan"), float("nan"), float("nan")

    rng = np.random.default_rng(seed)
    samples = np.empty(n_boot)
    for b in range(n_boot):
        sample = r[stationary_bootstrap_indices(n, mean_block, rng)]
        sd = sample.std(ddof=1)
        samples[b] = (
            sample.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR) if sd > 0 else np.nan
        )

    samples = samples[~np.isnan(samples)]
    if len(samples) == 0:
        return float("nan"), sharpe_ratio(returns), float("nan")

    alpha = (1.0 - confidence) / 2.0
    return (
        float(np.quantile(samples, alpha)),
        sharpe_ratio(returns),
        float(np.quantile(samples, 1.0 - alpha)),
    )


def bootstrap_pvalue(returns: pd.Series, n_boot: int = 2000, mean_block: float = 21.0,
                     seed: int = 42) -> float:
    """p-valor de una cola para H0: retorno esperado = 0.

    La hipótesis nula se impone centrando la serie en cero y remuestreando; el
    p-valor es la fracción de remuestreos que alcanzan la media observada por
    azar. No asume normalidad ni independencia.
    """
    r = returns.dropna().to_numpy()
    n = len(r)
    if n < 30:
        return float("nan")
    if r.std(ddof=1) == 0:
        return float("nan")  # la estrategia no operó: no hay hipótesis que contrastar

    observed = r.mean()
    centered = r - observed
    rng = np.random.default_rng(seed)

    count = 0
    for _ in range(n_boot):
        sample = centered[stationary_bootstrap_indices(n, mean_block, rng)]
        if sample.mean() >= abs(observed):
            count += 1
    return (count + 1) / (n_boot + 1)


def probability_of_backtest_overfitting(
    trial_returns: pd.DataFrame, n_splits: int = 10, seed: int = 42
) -> dict[str, float]:
    """PBO por validación cruzada combinatoria simétrica (CSCV).

    Referencia: Bailey, Borwein, López de Prado & Zhu (2017), "The Probability
    of Backtest Overfitting", Journal of Computational Finance 20(4), 39-69.

    El método parte la historia en S bloques, prueba todas las formas de usar la
    mitad para elegir la mejor estrategia y la otra mitad para evaluarla, y mide
    con qué frecuencia la ganadora dentro de muestra queda por debajo de la
    mediana fuera de muestra. Un PBO alto significa que el proceso de selección
    está eligiendo ruido.

    `trial_returns`: una columna por configuración evaluada, una fila por fecha.
    """
    if n_splits % 2 != 0:
        raise ValueError("n_splits debe ser par para poder partir en mitades iguales")

    data = trial_returns.dropna(how="any")
    n_obs, n_trials = data.shape
    if n_trials < 2:
        raise ValueError("El PBO necesita al menos 2 configuraciones para comparar")
    if n_obs < n_splits * 2:
        raise ValueError(
            f"Muestra insuficiente: {n_obs} observaciones para {n_splits} bloques"
        )

    block_size = n_obs // n_splits
    blocks = [
        data.iloc[i * block_size : (i + 1) * block_size if i < n_splits - 1 else n_obs]
        for i in range(n_splits)
    ]

    logits: list[float] = []
    for is_blocks in combinations(range(n_splits), n_splits // 2):
        oos_blocks = [i for i in range(n_splits) if i not in is_blocks]
        is_data = pd.concat([blocks[i] for i in is_blocks])
        oos_data = pd.concat([blocks[i] for i in oos_blocks])

        is_sr = is_data.apply(lambda c: sharpe_ratio(c, annualize=False))
        oos_sr = oos_data.apply(lambda c: sharpe_ratio(c, annualize=False))
        if is_sr.isna().all() or oos_sr.isna().all():
            continue

        best = is_sr.idxmax()
        rank = oos_sr.rank(ascending=True)[best]
        omega = rank / (n_trials + 1.0)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(float(np.log(omega / (1.0 - omega))))

    if not logits:
        return {"pbo": float("nan"), "n_combinations": 0, "median_logit": float("nan")}

    arr = np.array(logits)
    return {
        "pbo": float((arr < 0).mean()),
        "n_combinations": len(arr),
        "median_logit": float(np.median(arr)),
    }


def interpret_pbo(pbo: float) -> str:
    if np.isnan(pbo):
        return "PBO no calculable con los datos disponibles."
    if pbo < 0.10:
        return f"PBO = {pbo:.1%}: el proceso de selección parece robusto."
    if pbo < 0.50:
        return f"PBO = {pbo:.1%}: hay sobreajuste moderado. Tratá los resultados con cautela."
    return (
        f"PBO = {pbo:.1%}: la configuración elegida tiene más probabilidad de quedar "
        "por debajo de la mediana fuera de muestra que por encima. El backtest está "
        "sobreajustado y no debe usarse para decidir inversiones."
    )
