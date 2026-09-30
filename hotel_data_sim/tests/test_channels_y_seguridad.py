import json

import pytest

from hotelsim import channels, config as C, tools


def change(**o):
    c = dict(hotel_id="MDZ01", room_type="STD", stay_date="2026-10-20", current_usd=100.0, new_usd=110.0, reasons=["test"])
    c.update(o)
    return c


def test_valida_limites_duros(clean_queue):
    r = channels.propose([change(new_usd=125.0), change(new_usd=10.0), change(hotel_id="XXX"),
                          change(stay_date="2030-01-01"), change(room_type="ZZZ"), change(new_usd=108.0)])
    assert len(r["accepted"]) == 1 and len(r["rejected"]) == 5      # +25%, bajo piso, hotel, fecha, habitación


def test_agente_no_puede_aprobar(clean_queue):
    e = channels.propose([change()])["accepted"][0]
    for quien in ("", "agente", "Claude", "IA"):
        with pytest.raises(channels.ValidationError):
            channels.approve([e["id"]], quien)
    assert channels.list_queue("propuesto")[0]["id"] == e["id"]      # sigue sin publicar
    assert "approve" not in " ".join(tools.AGENT_TOOLS) and "approve" not in " ".join(tools.READ_TOOLS)


def test_aprobacion_humana_publica_en_todos_los_canales(clean_queue, world):
    e = channels.propose([change(stay_date="2026-10-22")])["accepted"][0]
    res = channels.approve([e["id"]], "Ana Pérez")
    assert res["published"] == [e["id"]]
    assert {p["channel"] for p in res["pushes"]} == set(channels.PRICE_CHANNELS)    # misma tarifa en todos: paridad
    files = list(C.OUTBOX.glob("*_MDZ01_*.json"))
    payload = json.loads(files[-1].read_text())
    assert payload["connector"] == "mock" and payload["rates"]
    audit = [json.loads(x) for x in (C.OUTBOX / "audit.jsonl").read_text().splitlines()]
    assert audit[-1]["event"] == "approve" and audit[-1]["by"] == "Ana Pérez"
    assert channels.list_queue("propuesto") == []


def test_propuesta_reemplaza_a_la_anterior(clean_queue):
    channels.propose([change(new_usd=105.0)])
    channels.propose([change(new_usd=112.0)])
    pend = channels.list_queue("propuesto")
    assert len(pend) == 1 and pend[0]["new_usd"] == 112.0


@pytest.mark.parametrize("q", ["DROP TABLE meta", "SELECT 1; SELECT 2", "SELECT * FROM silver_reservation",
                               "SELECT * FROM read_parquet('/etc/passwd')", "COPY meta TO '/tmp/x'",
                               "ATTACH '/tmp/x.db'", "INSERT INTO meta VALUES (1)"])
def test_run_sql_bloquea_lo_peligroso(q):
    assert "error" in tools.run_sql(q)


def test_run_sql_permite_select_y_limita_filas(world):
    out = tools.run_sql("SELECT * FROM gold_daily_kpis")
    assert "error" not in out and len(out["rows"]) == tools.MAX_ROWS
    assert "error" in tools.run_sql("SELECT nope FROM gold_daily_kpis")   # error SQL devuelto, no excepción


def test_ejecucion_de_herramienta_inexistente_o_invalida():
    assert "error" in tools.execute("approve", {}, tools.AGENT_TOOLS)
    assert "error" in tools.execute("kpis", {"group_by": "year"}, tools.READ_TOOLS)
    assert "error" in tools.execute("kpis", {"basura": 1}, tools.READ_TOOLS)
