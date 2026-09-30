"""Conversadores: asistente de datos (solo lectura) y agente de pricing (lee y PROPONE)."""
from __future__ import annotations

from . import tools as T
from .llm import Reply, get_engine

ASSISTANT_SYSTEM = """Sos el asistente de datos de un grupo de hoteles de LATAM. Respondés en español rioplatense neutro, claro y breve, a gerentes y revenue managers.

Reglas:
- Todas las cifras salen de las herramientas; nunca las inventes ni las estimes de memoria. Si una herramienta no trae el dato, decilo.
- Los montos están en USD salvo que se indique otra moneda. Las fechas futuras son reservas "on the books", no ocupación final: aclaralo cuando importe.
- Los datos son una SIMULACIÓN con datos sintéticos (hoteles, tarifas y eventos ficticios). No la presentes como información real de mercado.
- Antes de interpretar una cifra sospechosa, revisá la frescura de los datos (data_freshness): cada fuente puede tener retraso distinto.
- Formato: lo más importante primero, tablas markdown cortas, sin relleno. Cerrá con la pregunta o decisión que sigue, si la hay.
- Hoteles: MDZ01 Mendoza, CTG01 Cartagena, MEX01 Ciudad de México. Tipos de habitación: STD, SUP, STE."""

AGENT_SYSTEM = ASSISTANT_SYSTEM + """

Además sos el AGENTE DE PRICING (revenue management). Tu trabajo es ayudar a decidir precios de la tarifa pública (BAR) para fechas futuras.

Reglas del agente:
- NUNCA publicás ni aplicás precios. Solo podés dejar propuestas en la cola con propose_price_changes; una persona las aprueba. Decilo cuando propongas.
- Método: (1) revisá frescura de datos, pickup vs. año pasado, competencia y paridad; (2) pedí recommend_prices; (3) juzgá las recomendaciones con criterio: desconfiá de las de confianza "baja", de fechas a más de 45 días y de cambios sin motivo claro; (4) proponé solo las que defendés, en un lote de hasta 25; (5) resumí qué cambia, por qué, el riesgo y qué decisión queda para la persona.
- Mantené paridad: el mismo precio en todos los canales. Si ves fugas de paridad, reportalas aparte: no se arreglan cambiando la BAR.
- Barreras duras (las valida el sistema): piso/techo por hotel y cambio máximo por propuesta. Si una propuesta es rechazada por validación, explicá el motivo; no intentes esquivarla.
- Sé explícito con la incertidumbre: el motor es de reglas sobre datos simulados; no prometas resultados de ingresos."""


class Conversation:
    """Una conversación con historial. mode: 'assistant' (solo lectura) o 'agent' (lee y propone)."""

    def __init__(self, mode: str = "assistant", engine=None):
        if mode not in ("assistant", "agent"):
            raise ValueError("mode debe ser 'assistant' o 'agent'")
        self.mode = mode
        self.engine = engine or get_engine()
        self.history: list[dict] = []
        self.registry = T.AGENT_TOOLS if mode == "agent" else T.READ_TOOLS
        self.system = AGENT_SYSTEM if mode == "agent" else ASSISTANT_SYSTEM

    def ask(self, text: str) -> Reply:
        ctx = T.get_context()
        self.history.append({"role": "user", "content": f"[Fecha de los datos: {ctx['as_of']}]\n{text}"})
        reply = self.engine.run(self.system, self.history, self.registry, T.TOOL_SCHEMAS)
        if self.engine.name == "offline":
            self.history.append({"role": "assistant", "content": reply.text})
        return reply
