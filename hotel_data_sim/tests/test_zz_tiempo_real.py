"""Va al final: avanza el reloj simulado (modifica el estado compartido)."""
from hotelsim import config as C, pipeline
from hotelsim.ingest import get_clock, ingest


def test_ingesta_es_idempotente(world):
    ingest()                              # absorbe lo que hayan dejado tests previos (p. ej. ARI de un push)
    assert ingest()["files"] == 0


def test_tick_procesa_solo_lo_nuevo_y_avanza_el_reloj(world):
    antes = get_clock()
    n_antes = len(list(C.LANDING.rglob("*.*")))
    stats = pipeline.tick(60, log=lambda *a: None)
    assert get_clock() > antes
    assert 0 < stats["bronze"]["files"] < 15                     # incremental: no reprocesa la historia
    assert len(list(C.LANDING.rglob("*.*"))) > n_antes
    from hotelsim.gold import connect
    c = connect(read_only=True)
    assert str(c.execute("SELECT as_of_ts FROM meta").fetchone()[0]).startswith(f"{get_clock():%Y-%m-%d %H}")
    c.close()


def test_precio_aprobado_llega_al_ari_despues_de_un_tick(world, clean_queue):
    from hotelsim import channels
    from hotelsim.gold import connect
    from datetime import timedelta
    d = (get_clock() + timedelta(days=30)).date().isoformat()
    c = connect(read_only=True)
    actual = c.execute(f"SELECT bar_direct_usd FROM gold_pickup WHERE hotel_id='MDZ01' AND room_type='STD' AND stay_date='{d}'").fetchone()[0]
    c.close()
    nuevo = round(actual * 1.1)
    e = channels.propose([dict(hotel_id="MDZ01", room_type="STD", stay_date=d, current_usd=actual, new_usd=nuevo)])["accepted"][0]
    channels.approve([e["id"]], "Test Humano")
    pipeline.refresh(log=lambda *a: None)
    c = connect(read_only=True)
    despues = c.execute(f"SELECT bar_direct_usd FROM gold_pickup WHERE hotel_id='MDZ01' AND room_type='STD' AND stay_date='{d}'").fetchone()[0]
    c.close()
    assert abs(despues - nuevo) <= 1
