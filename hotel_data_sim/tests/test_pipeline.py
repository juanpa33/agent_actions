"""El pipeline debe reconciliar contra la verdad del simulador y detectar la suciedad inyectada."""
import pandas as pd

from hotelsim import config as C


def silver(name):
    return pd.read_parquet(C.SILVER / f"{name}.parquet")


def dq():
    d = silver("dq")
    return dict(zip(d["check"], d["value"]))


def test_invariantes_de_capacidad(world):
    for (h, room, d), sold in world.sold.items():
        assert 0 <= sold <= C.HOTEL_BY_ID[h].rooms[room]


def test_reservas_reconcilian_con_la_verdad(world):
    res = silver("reservation")
    truth = len(world.bookings)
    assert abs(len(res) - truth) / truth < 0.03          # diferencia = registros en cuarentena
    truth_rev = sum(b.total_usd for b in world.bookings.values() if not b.cancelled_at)
    rev = res[res.status == "activa"].total_usd.sum()
    assert abs(rev - truth_rev) / truth_rev < 0.02


def test_detecta_suciedad_inyectada():
    m = dq()
    assert m["cuarentena"] > 0                            # líneas malformadas / importes inválidos
    assert m["duplicados_eliminados"] > 0                 # reenvíos
    assert m["fx_faltante"] == 0


def test_cruce_entre_sistemas():
    m = dq()
    assert m["cruce.cruzada_por_referencia"] > 1000
    assert m["cruce.cruzada_por_similitud"] > 0           # OTAs sin referencia en el PMS
    assert m["cruce.solo_channel_manager"] > 0            # aún no llegaron al PMS
    res = silver("reservation")
    cruzadas = res[res.in_pms & res.in_cm]
    assert (cruzadas.channel.isin(C.OTA_CHANNELS)).all()
    assert res.res_key.is_unique


def test_monedas_normalizadas_a_usd():
    res = silver("reservation")
    assert set(res.currency) == {"ARS", "COP", "MXN", "USD"} or set(res.currency) <= {"ARS", "COP", "MXN", "USD"}
    adr = (res.total_usd / res.nights)
    assert adr.between(20, 1500).mean() > 0.99            # ARS/COP mal convertidos se verían como miles o centavos


def test_bronze_conserva_lo_malformado():
    from hotelsim.ingest import read_bronze
    assert (~read_bronze("pms_opera").parse_ok).sum() + (~read_bronze("cm_reservations").parse_ok).sum() > 0
