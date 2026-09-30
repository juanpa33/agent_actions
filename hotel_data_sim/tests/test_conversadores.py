from types import SimpleNamespace

import pytest

from hotelsim import channels, llm
from hotelsim.assistant import Conversation


def test_asistente_offline_responde_con_datos(world):
    c = Conversation("assistant")
    r = c.ask("¿Cómo vino agosto en México?")
    assert [t["name"] for t in r.tool_calls] == ["kpis"] and "MEX01" in r.text
    assert "MEX01" not in Conversation("assistant").ask("ritmo de reservas en mendoza").text


def test_asistente_no_puede_proponer_precios(world, clean_queue):
    r = Conversation("assistant").ask("Proponé cambios de precio")
    assert not channels.list_queue()
    assert "propose_price_changes" not in [t["name"] for t in r.tool_calls]


def test_agente_propone_pero_no_publica(world, clean_queue):
    c = Conversation("agent")
    r = c.ask("Proponé los cambios de los próximos 14 días")
    names = [t["name"] for t in r.tool_calls]
    assert names == ["recommend_prices", "propose_price_changes"]
    pend = channels.list_queue("propuesto")
    assert pend and all(e["status"] == "propuesto" for e in pend)
    assert "Nada se publicó" in r.text


# ---- ClaudeEngine con un cliente simulado (no hay red ni credenciales en los tests)
class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None}


def resp(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks),
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0))


class FakeEngine(llm.ClaudeEngine):
    def __init__(self, script):
        import anthropic
        self.anthropic, self.script, self.seen = anthropic, list(script), []
        self.model, self.effort, self.fallbacks = "fake", "medium", True

    def _create(self, system, messages, schemas):
        self.seen.append((system, [m["role"] for m in messages], [s["name"] for s in schemas]))
        return self.script.pop(0)


def test_claude_engine_ciclo_de_herramientas(world):
    eng = FakeEngine([
        resp("tool_use", Block(type="text", text="miro"), Block(type="tool_use", id="t1", name="pickup", input={"days_ahead": 7})),
        resp("end_turn", Block(type="text", text="Listo: el ritmo es estable.")),
    ])
    c = Conversation("assistant", engine=eng)
    r = c.ask("¿cómo viene el ritmo?")
    assert r.text == "Listo: el ritmo es estable." and r.tool_calls == [dict(name="pickup", args={"days_ahead": 7}, ok=True)]
    roles = [m["role"] for m in c.history]
    assert roles == ["user", "assistant", "user", "assistant"]                # el resultado de la herramienta vuelve como user
    assert c.history[2]["content"][0]["type"] == "tool_result" and not c.history[2]["content"][0]["is_error"]
    assert "approve" not in eng.seen[0][2] and "propose_price_changes" not in eng.seen[0][2]   # asistente: solo lectura
    assert r.usage["input_tokens"] == 20


def test_claude_engine_maneja_herramienta_fallida_y_rechazo(world):
    eng = FakeEngine([resp("tool_use", Block(type="tool_use", id="t1", name="kpis", input={"group_by": "year"})),
                      resp("refusal", Block(type="text", text=""))])
    r = Conversation("assistant", engine=eng).ask("kpis")
    assert r.stop_reason == "refusal" and "no pudo responder" in r.text
    assert r.tool_calls[0]["ok"] is False


def test_agente_expone_herramienta_de_propuesta_pero_nunca_de_aprobacion(world):
    eng = FakeEngine([resp("end_turn", Block(type="text", text="ok"))])
    Conversation("agent", engine=eng).ask("hola")
    tools_seen = eng.seen[0][2]
    assert "propose_price_changes" in tools_seen and not any("approve" in t for t in tools_seen)
