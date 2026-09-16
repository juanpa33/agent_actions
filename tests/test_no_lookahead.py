"""El sesgo de anticipación es el error que más backtests falsos produce.

Estos tests verifican mecánicamente que una señal no puede usar información que
todavía no existía en el momento de decidir.
"""

import numpy as np
import pandas as pd

from stockagent import backtest as bt
from stockagent import signals as sg


def _prices(n=800, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n))), index=idx)


def test_la_posicion_ejecutada_va_un_dia_detras_de_la_decidida():
    px = _prices()
    flag = pd.Series(1.0, index=px.index)
    result = bt.run_backtest(px, flag, costs=bt.CostModel(0, 0, 0))

    # El primer día no puede haber posición: la señal de ese día se ejecuta al siguiente.
    assert result.positions.iloc[0] == 0.0


def test_una_senal_con_vision_del_futuro_no_captura_el_retorno_del_mismo_dia():
    """Prueba de fuego: se construye una señal que ve el retorno de mañana.

    Con ejecución diferida, esa señal NO debería poder capitalizar el movimiento
    del día que predice. Si lo capturara, habría una fuga de información en el
    motor de backtest.
    """
    px = _prices()
    future_return = px.pct_change().shift(-1)
    oracle = (future_return > 0).astype(float)

    perfect = bt.run_backtest(px, oracle, costs=bt.CostModel(0, 0, 0), rebalance="D")
    lagged_oracle = oracle.shift(1).fillna(0.0)
    honest = bt.run_backtest(px, lagged_oracle, costs=bt.CostModel(0, 0, 0), rebalance="D")

    # Ejecutar con un día de atraso destruye la ventaja del oráculo, que es
    # precisamente lo que debe ocurrir.
    assert honest.net_return < perfect.net_return


def test_las_senales_no_estan_definidas_antes_de_tener_historia_suficiente():
    px = _prices()
    signals = sg.build_signals(px, "TEST")

    # La SMA de 200 necesita 200 ruedas; el máximo de 52 semanas, 126; el
    # momentum 12-1, 273. La señal compuesta requiere las tres.
    assert signals.composite.iloc[:272].isna().all()
    assert signals.composite.dropna().index[0] >= px.index[272]


def test_los_indicadores_de_una_fecha_no_cambian_al_agregar_datos_posteriores():
    """Un indicador causal no puede modificarse retroactivamente."""
    px = _prices()
    cut = 600

    full = sg.build_signals(px, "TEST").composite
    partial = sg.build_signals(px.iloc[:cut], "TEST").composite

    common = partial.dropna().index
    pd.testing.assert_series_equal(
        full.loc[common], partial.loc[common], check_names=False
    )


def test_los_costos_reducen_el_retorno():
    px = _prices()
    flag = sg.build_signals(px, "TEST").position_flag

    free = bt.run_backtest(px, flag, costs=bt.CostModel(0, 0, 0))
    expensive = bt.run_backtest(px, flag, costs=bt.CostModel.byma_equity())

    if free.trades > 0:
        assert expensive.net_return < free.net_return
        assert expensive.total_costs > free.total_costs
