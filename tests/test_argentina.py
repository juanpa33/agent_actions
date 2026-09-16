"""El caso argentino: split 10:1 de YPFD, CCL implícito y deflación por IPC.

Estos tests reconstruyen el escenario real del 4-ago-2026 para verificar que el
cálculo del CCL sobrevive a la acción societaria y que detecta el error si el
proveedor de datos ajusta mal.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stockagent import argentina as ar
from stockagent.datasources.indec import deflate
from stockagent.provenance import MissingDataError, synthetic


def _escenario_split(ccl_real=1450.0, adr_usd=50.0, n=120):
    """Construye precios sintéticos alrededor del split del 4-ago-2026.

    Verdad de laboratorio: el CCL vale exactamente `ccl_real` todos los días.
    Cualquier método correcto debe recuperar ese valor a ambos lados del split.
    """
    idx = pd.bdate_range("2026-06-01", periods=n)
    split = pd.Timestamp("2026-08-04")

    adr = pd.Series(adr_usd, index=idx)

    # Precio local CRUDO: antes del split 1 acción = 1 ADS, después 10 acciones = 1 ADS.
    local_raw = pd.Series(
        [adr_usd * ccl_real if d < split else adr_usd * ccl_real / 10.0 for d in idx],
        index=idx,
    )
    # Precio local AJUSTADO por split: el proveedor divide por 10 todo el pasado.
    local_adj = pd.Series(
        [v / 10.0 if d < split else v for d, v in zip(idx, local_raw)], index=idx
    )
    return idx, local_raw, local_adj, adr


def _traced(series, name):
    return synthetic(pd.DataFrame({"close": series}), name)


def test_la_razon_del_adr_cambia_en_la_fecha_del_split():
    assert ar.shares_per_ads_on(date(2026, 8, 3)) == 1.0
    assert ar.shares_per_ads_on(date(2026, 8, 4)) == 10.0
    assert ar.shares_per_ads_on(date(2026, 12, 1)) == 10.0


def test_el_ccl_es_continuo_sobre_series_ajustadas_por_split():
    """Con precios ajustados, la razón efectiva es constante y el CCL no salta."""
    _, _, local_adj, adr = _escenario_split(ccl_real=1450.0)

    ccl = ar.implied_ccl(_traced(local_adj, "ypfd"), _traced(adr, "ypf"),
                         prices_are_split_adjusted=True)

    assert np.allclose(ccl.data.to_numpy(), 1450.0), "el CCL debe ser constante"
    assert ar.validate_ccl_continuity(ccl.data) == []


def test_el_ccl_es_continuo_sobre_series_crudas_con_razon_por_fecha():
    """Con precios crudos, la razón variable en el tiempo produce el mismo resultado."""
    _, local_raw, _, adr = _escenario_split(ccl_real=1450.0)

    ccl = ar.implied_ccl(_traced(local_raw, "ypfd"), _traced(adr, "ypf"),
                         prices_are_split_adjusted=False)

    assert np.allclose(ccl.data.to_numpy(), 1450.0)
    assert ar.validate_ccl_continuity(ccl.data) == []


def test_aplicar_mal_el_split_produce_un_salto_de_10x_que_la_validacion_detecta():
    """El error que este módulo existe para atrapar.

    Si se usan precios ajustados pero se aplica la razón vigente por fecha (1
    antes del split), el CCL histórico queda dividido por 10. Un salto así en la
    fecha exacta de una acción societaria no es economía: es un error de datos.
    """
    _, _, local_adj, adr = _escenario_split(ccl_real=1450.0)

    mal = ar.implied_ccl(_traced(local_adj, "ypfd"), _traced(adr, "ypf"),
                         prices_are_split_adjusted=False)

    warnings = ar.validate_ccl_continuity(mal.data)
    assert warnings, "la validación tiene que detectar el salto"
    assert "10" in warnings[0], "y señalar que el factor es compatible con un split"


def test_la_validacion_de_nivel_avisa_cuando_falta_el_tipo_de_cambio_oficial():
    ccl = pd.Series(1450.0, index=pd.bdate_range("2026-01-01", periods=60))
    warnings = ar.validate_ccl_level(ccl, official_fx=None)
    assert any("NIVEL" in w for w in warnings)


def test_un_ccl_por_debajo_del_oficial_se_marca_como_implausible():
    idx = pd.bdate_range("2026-01-01", periods=60)
    oficial = pd.Series(1400.0, index=idx)
    ccl_malo = pd.Series(700.0, index=idx)  # mitad del oficial: imposible con cepo
    assert ar.validate_ccl_level(ccl_malo, oficial)


def test_la_conversion_a_dolares_invierte_exactamente_el_ccl():
    idx = pd.bdate_range("2026-01-01", periods=50)
    local = pd.Series(np.linspace(30000, 40000, 50), index=idx)
    ccl_series = pd.Series(1450.0, index=idx)

    usd = ar.to_usd(_traced(local, "ypfd"), synthetic(ccl_series, "ccl"))
    assert np.allclose(usd.data.to_numpy(), local.to_numpy() / 1450.0)


def test_el_ccl_exige_superposicion_suficiente_entre_ambos_mercados():
    """Feriados distintos entre BYMA y NYSE no deben producir un CCL silencioso."""
    a = pd.Series(1.0, index=pd.bdate_range("2026-01-01", periods=10))
    b = pd.Series(1.0, index=pd.bdate_range("2026-06-01", periods=10))
    with pytest.raises(MissingDataError):
        ar.implied_ccl(_traced(a, "ypfd"), _traced(b, "ypf"))


def test_la_deflacion_no_extrapola_mas_alla_del_ultimo_ipc_publicado():
    """El IPC se publica con rezago. Extrapolarlo sería fabricar el dato clave."""
    precios = pd.Series(100.0, index=pd.bdate_range("2026-01-01", periods=120))
    ipc = pd.Series(
        [100.0, 102.0, 104.0],
        index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]),
    )

    real = deflate(precios, ipc)

    assert real.index.max() < pd.Timestamp("2026-04-01"), (
        "no debe haber valores deflactados para meses sin IPC publicado"
    )


def test_la_deflacion_revela_la_perdida_real_de_una_serie_nominal_plana():
    """Un precio nominal constante bajo inflación PIERDE poder adquisitivo.

    Es el error de medición que invalida analizar acciones argentinas en pesos
    nominales: lo que parece estabilidad es una caída real.
    """
    idx = pd.bdate_range("2026-01-01", periods=85)
    nominal = pd.Series(1000.0, index=idx)
    ipc = pd.Series(
        [100.0, 110.0, 121.0, 133.1],
        index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]),
    )

    real = deflate(nominal, ipc)
    assert real.iloc[-1] < real.iloc[0], "en pesos constantes la serie debe caer"
    assert np.isclose(real.iloc[0] / real.iloc[-1], 1.331, rtol=0.01)


def test_deflactar_sin_ipc_falla_en_vez_de_devolver_la_serie_nominal():
    precios = pd.Series(100.0, index=pd.bdate_range("2026-01-01", periods=10))
    with pytest.raises(MissingDataError):
        deflate(precios, pd.Series(dtype=float))
