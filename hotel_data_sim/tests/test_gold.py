def q(con, sql):
    return con.execute(sql).df()


def test_kpis_coherentes(con):
    k = q(con, "SELECT * FROM gold_daily_kpis WHERE is_actual")
    assert (k.rooms_sold <= k.rooms_available).all()
    assert k.occupancy.between(0, 1).all()
    ok = k[k.rooms_sold > 0]
    assert ((ok.revpar_usd - ok.adr_usd * ok.occupancy).abs() < 1e-6).all()     # RevPAR = ADR × ocupación


def test_pickup_no_supera_capacidad_y_es_monotono(con):
    p = q(con, "SELECT * FROM gold_pickup")
    assert (p.otb_now <= p.capacity).all()
    assert (p.pickup_7d == p.otb_now - p.otb_7d_ago).all()
    assert p.otb_stly.sum() > 0 and p.final_ly.sum() > 0                          # hay historia comparable


def test_paridad_solo_detecta_la_fuga_inyectada(con):
    p = q(con, "SELECT channel, SUM(breach::INT) AS n FROM gold_parity GROUP BY channel")
    n = dict(zip(p.channel, p.n))
    assert n["BOOKING"] > 0 and n["EXPEDIA"] == 0 and n["DESPEGAR"] == 0


def test_canales_netos_menores_a_brutos(con):
    m = q(con, "SELECT * FROM gold_channel_mix")
    assert (m.net_usd <= m.gross_usd + 1e-6).all()
    assert m[m.channel.isin(["DIRECT", "CORP"])].commission_usd.abs().max() < 1e-6


def test_compset_y_fuentes(con):
    assert q(con, "SELECT COUNT(*) n FROM gold_compset").n[0] > 0
    assert q(con, "SELECT COUNT(*) n FROM gold_source_health").n[0] >= 6
