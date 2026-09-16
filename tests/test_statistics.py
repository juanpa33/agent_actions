"""La estadística correctiva debe rechazar el ruido y reconocer la señal."""

import numpy as np
import pandas as pd
import pytest

from stockagent import statistics as st


def test_el_ruido_puro_no_pasa_el_deflated_sharpe():
    """El caso que más importa: ruido que por azar luce bien debe ser rechazado."""
    rng = np.random.default_rng(1)
    # Se eligen 200 series de ruido y se toma la MEJOR, tal como haría alguien
    # optimizando parámetros. Su Sharpe será alto por construcción.
    candidates = [pd.Series(rng.normal(0, 0.01, 500)) for _ in range(200)]
    best = max(candidates, key=lambda s: st.sharpe_ratio(s))
    sharpes = [st.sharpe_ratio(s, annualize=False) for s in candidates]

    naive_sharpe = st.sharpe_ratio(best)
    dsr = st.deflated_sharpe_ratio(best, trials=200, all_trial_sharpes=sharpes)

    assert naive_sharpe > 0.5, "la mejor de 200 series de ruido debería lucir atractiva"
    assert dsr < 0.95, "el DSR debe rechazar la mejor serie de ruido puro"


def test_el_sharpe_maximo_esperado_crece_con_el_numero_de_pruebas():
    """Cuantas más configuraciones probás, más alto el listón que hay que superar."""
    variance = 0.002
    values = [st.expected_max_sharpe(n, variance) for n in (2, 10, 100, 1000)]
    assert all(a < b for a, b in zip(values, values[1:]))


def test_una_sola_prueba_no_impone_penalizacion():
    assert st.expected_max_sharpe(1, 0.01) == 0.0


def test_el_psr_penaliza_la_asimetria_negativa():
    """Dos series con igual Sharpe pero distinta asimetría no valen lo mismo."""
    rng = np.random.default_rng(5)
    symmetric = pd.Series(rng.normal(0.0005, 0.01, 1000))
    skewed = pd.Series(-rng.gumbel(-0.0005, 0.0078, 1000))

    # Se igualan media y desvío para aislar el efecto de la asimetría.
    skewed = (skewed - skewed.mean()) / skewed.std() * symmetric.std() + symmetric.mean()

    assert skewed.skew() < -0.3
    assert st.probabilistic_sharpe_ratio(skewed) < st.probabilistic_sharpe_ratio(symmetric)


def test_el_intervalo_bootstrap_de_una_serie_sin_habilidad_incluye_el_cero():
    rng = np.random.default_rng(11)
    noise = pd.Series(rng.normal(0, 0.01, 1000))
    lo, _, hi = st.bootstrap_sharpe_ci(noise, n_boot=500)
    assert lo < 0 < hi


def test_el_pvalor_bootstrap_detecta_una_media_realmente_positiva():
    rng = np.random.default_rng(13)
    strong = pd.Series(rng.normal(0.0015, 0.008, 1000))
    weak = pd.Series(rng.normal(0.0, 0.008, 1000))
    assert st.bootstrap_pvalue(strong, n_boot=500) < 0.10
    assert st.bootstrap_pvalue(weak, n_boot=500) > 0.10


def test_el_bootstrap_estacionario_preserva_bloques_contiguos():
    """Si el remuestreo no conservara bloques, destruiría la autocorrelación."""
    rng = np.random.default_rng(17)
    idx = st.stationary_bootstrap_indices(1000, mean_block=21.0, rng=rng)
    consecutive = np.sum(np.diff(idx) == 1)
    # Con bloques de largo medio 21, la mayoría de los pasos son contiguos.
    assert consecutive > 700


def test_el_pbo_distingue_el_ruido_de_la_habilidad_real():
    """Prueba discriminativa del PBO.

    No se verifica un valor absoluto: con pocas configuraciones y pocos bloques
    el estimador del PBO tiene alta varianza muestral, y fijar un umbral rígido
    sería exigirle una precisión que no tiene. Lo que sí debe cumplir es
    SEPARAR los dos casos: cuando una de las configuraciones tiene ventaja
    genuina y persistente, el PBO tiene que caer marcadamente respecto del caso
    en que todas son ruido.
    """
    noise_pbos, skill_pbos = [], []

    for seed in range(8):
        rng = np.random.default_rng(seed)
        noise = pd.DataFrame(rng.normal(0, 0.01, (600, 15)))
        noise_pbos.append(
            st.probability_of_backtest_overfitting(noise, n_splits=8)["pbo"]
        )

        with_skill = noise.copy()
        with_skill[0] = rng.normal(0.0015, 0.01, 600)  # ventaja real y estable
        skill_pbos.append(
            st.probability_of_backtest_overfitting(with_skill, n_splits=8)["pbo"]
        )

    assert np.mean(skill_pbos) < np.mean(noise_pbos) / 2.0
    assert np.mean(noise_pbos) > 0.20, "ruido puro debe mostrar sobreajuste sustancial"


def test_el_largo_minimo_de_historial_crece_cuando_el_sharpe_es_bajo():
    rng = np.random.default_rng(23)
    high = pd.Series(rng.normal(0.002, 0.01, 800))
    low = pd.Series(rng.normal(0.0002, 0.01, 800))
    assert st.min_track_record_length(low) > st.min_track_record_length(high)


def test_el_pbo_exige_al_menos_dos_configuraciones():
    with pytest.raises(ValueError):
        st.probability_of_backtest_overfitting(pd.DataFrame({"a": np.zeros(300)}))
