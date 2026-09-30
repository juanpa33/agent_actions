"""Modo sin conexión: enrutador de intenciones por palabras clave sobre las mismas herramientas.

No es un LLM: sirve para probar el producto completo (tablero, herramientas, cola de
aprobación) sin credenciales y para tests deterministas. Con credenciales, `ClaudeEngine`
entiende preguntas libres, encadena herramientas y redacta el análisis.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from . import tools as T
from .llm import Reply

HOTEL_WORDS = {"MDZ01": ["mdz01", "mendoza", "vinedos", "viñedos", "lujan", "luján"],
               "CTG01": ["ctg01", "cartagena", "getsemani", "getsemaní"],
               "MEX01": ["mex01", "mexico", "méxico", "cdmx", "reforma"]}
MONTH_NAMES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MONTHS = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                                          "agosto", "septiembre", "octubre", "noviembre", "diciembre"])}
NOTE = "\n\n_(Modo sin conexión: respuestas con reglas fijas. Con `ANTHROPIC_API_KEY` el asistente usa Claude y entiende preguntas libres.)_"


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _hotel(text: str) -> str | None:
    t = _norm(text)
    for hid, words in HOTEL_WORDS.items():
        if any(_norm(w) in t for w in words):
            return hid
    return None


def _days(text: str, default: int) -> int:
    m = re.search(r"(\d+)\s*d[ií]as", _norm(text))
    return max(1, min(120, int(m.group(1)))) if m else default


def table(rows: list[dict], cols: list[tuple[str, str]], fmt: dict | None = None, limit: int = 12) -> str:
    fmt = fmt or {}
    if not rows:
        return "_(sin datos)_"
    head = "| " + " | ".join(h for _, h in cols) + " |\n|" + "---|" * len(cols) + "\n"
    body = ""
    for r in rows[:limit]:
        cells = []
        for k, _ in cols:
            v = r.get(k)
            if v is None:
                cells.append("")
            elif k in fmt:
                cells.append(fmt[k](v))
            elif isinstance(v, float):
                cells.append(f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}")
            else:
                cells.append(str(v))
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


pct = lambda v: f"{v:.0%}"   # noqa: E731
usd = lambda v: f"${v:,.0f}"  # noqa: E731


class OfflineEngine:
    name = "offline"

    def run(self, system: str, history: list[dict], registry, schemas) -> Reply:
        raw = history[-1]["content"]
        text = raw if isinstance(raw, str) else ""
        text = re.sub(r"^\[Fecha de los datos:[^\]]*\]\n?", "", text)
        t = _norm(text)
        hotel = _hotel(text)
        calls: list[dict] = []

        def call(name, **kw):
            out = T.execute(name, {k: v for k, v in kw.items() if v is not None}, registry)
            calls.append(dict(name=name, args=kw, ok="error" not in out))
            return out

        agent = "propose_price_changes" in registry
        if agent and re.search(r"propon|propone|proponer|aprobacion|enviar a aprob|cola", t) and not re.search(r"pendiente", t):
            return self._propose(text, hotel, calls, call)
        if re.search(r"pendiente", t) and agent:
            out = call("list_pending")
            rows = out.get("pendientes", [])
            body = table(rows, [("id", "ID"), ("hotel_id", "Hotel"), ("room_type", "Hab."), ("stay_date", "Fecha"),
                                ("current_usd", "Actual"), ("new_usd", "Propuesto")], {"current_usd": usd, "new_usd": usd}, 25)
            return Reply(f"**Propuestas pendientes de aprobación humana: {len(rows)}**\n\n{body}" + NOTE, calls, self.name)
        if re.search(r"recomend|precio|tarifa|subir|bajar|pricing|revenue|yield", t):
            if not agent:
                return Reply("Las recomendaciones de precio las genera el **agente de pricing** (modo agente). "
                             "Desde el asistente puedo mostrarte KPIs, pickup, competencia, paridad y canales." + NOTE, calls, self.name)
            out = call("recommend_prices", hotel_id=hotel, horizon_days=_days(text, 30), limit=12)
            recs = out.get("recommendations", [])
            body = table(recs, [("hotel_id", "Hotel"), ("room_type", "Hab."), ("stay_date", "Fecha"), ("current_usd", "Actual"),
                                ("new_usd", "Sugerido"), ("change_pct", "Cambio"), ("proj_occ", "Ocup. proy."), ("confidence", "Confianza")],
                         {"current_usd": usd, "new_usd": usd, "change_pct": lambda v: f"{v:+.0%}", "proj_occ": pct}, 12)
            why = "\n".join(f"- {r['hotel_id']} {r['room_type']} {r['stay_date']}: " + "; ".join(r["reasons"]) for r in recs[:4])
            return Reply(f"**Recomendaciones de precio** (mayor impacto primero; {out.get('total_changes_available', 0)} cambios disponibles en total)\n\n{body}\n"
                         f"Por qué, en los primeros casos:\n{why}\n\nDecime «proponé los cambios» y los dejo en la cola para que una persona los apruebe." + NOTE,
                         calls, self.name)
        if re.search(r"paridad|parity", t):
            out = call("parity_alerts", hotel_id=hotel, limit=8)
            return Reply("**Paridad de tarifas (OTA vs. directo)**\n\n" + table(out["resumen"], [("hotel_id", "Hotel"), ("channel", "Canal"), ("fechas", "Fechas"), ("con_fuga", "Con diferencia >1%")])
                         + "\nPrimeras fechas con diferencia:\n\n" + table(out["detalle"], [("hotel_id", "Hotel"), ("room_type", "Hab."), ("stay_date", "Fecha"), ("channel", "Canal"), ("diff_pct", "Dif."), ("breach_type", "Tipo")],
                                                                         {"diff_pct": lambda v: f"{v:+.1%}"}, 8) + NOTE, calls, self.name)
        if re.search(r"canal|booking|expedia|despegar|comision", t):
            out = call("channel_mix", hotel_id=hotel, months=3)
            return Reply("**Mezcla de canales, últimos 3 meses** (USD)\n\n" + table(out["rows"], [("hotel_id", "Hotel"), ("channel", "Canal"), ("room_nights", "Noches"), ("gross_usd", "Bruto"), ("net_usd", "Neto de comisión"), ("adr_neto", "ADR neto")],
                                                                                   {"room_nights": lambda v: f"{v:,.0f}", "gross_usd": usd, "net_usd": usd, "adr_neto": usd}, 15) + NOTE, calls, self.name)
        if re.search(r"competen|compset|mercado|rate shop", t):
            out = call("compset", hotel_id=hotel, days_ahead=_days(text, 30))
            return Reply("**Posición de precio vs. competencia** (tipo Standard; índice >1 = más caro que la mediana)\n\n" + table(out["resumen"], [("hotel_id", "Hotel"), ("rate_index_promedio", "Índice prom."), ("nuestra_bar_usd", "Nuestra BAR"), ("mediana_comp_usd", "Mediana comp.")],
                                                                                                                                      {"rate_index_promedio": lambda v: f"{v:.2f}", "nuestra_bar_usd": usd, "mediana_comp_usd": usd}) + NOTE, calls, self.name)
        if re.search(r"pickup|ritmo|pace|reservas|on the books|otb", t):
            out = call("pickup", hotel_id=hotel, days_ahead=_days(text, 30))
            return Reply(f"**Ritmo de reservas, próximos {_days(text, 30)} días** vs. mismo momento del año pasado\n\n" + table(out["resumen"], [("hotel_id", "Hotel"), ("otb_occupancy", "Ocup. reservada"), ("otb_now", "Noches OTB"), ("otb_stly", "OTB año pasado"), ("pace_vs_stly", "Ritmo"), ("pickup_7d", "Pickup 7d")],
                                                                                                                                   {"otb_occupancy": pct, "pace_vs_stly": lambda v: f"{v:.2f}×", "otb_now": lambda v: f"{v:,.0f}", "otb_stly": lambda v: f"{v:,.0f}", "pickup_7d": lambda v: f"{v:+,.0f}"}) + NOTE, calls, self.name)
        if re.search(r"frescura|actualiz|calidad|datos|fuente|cuarentena|en vivo|tiempo real", t):
            out = call("data_freshness")
            return Reply(f"**Frescura de datos** (ahora simulado: {out['ahora_simulado']})\n\n" + table(out["fuentes"], [("source", "Fuente"), ("hotel_id", "Hotel"), ("registros", "Eventos"), ("ultimo_evento", "Último evento"), ("minutos_desde_ultimo_evento", "Min. desde último")], limit=10)
                         + "\nCalidad:\n\n" + table(out["calidad"], [("check", "Chequeo"), ("value", "Valor")], {"value": lambda v: f"{v:,.0f}"}, 20) + NOTE, calls, self.name)
        if re.search(r"ocupacion|adr|revpar|kpi|como vino|como viene|como nos fue|ingresos|mes", t):
            ctx = T.get_context()
            today = date.fromisoformat(ctx["as_of"][:10])
            month = next((n for w, n in MONTHS.items() if w in t), None)
            if "mes pasado" in t:
                first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            elif month:
                first = date(today.year if month <= today.month else today.year - 1, month, 1)
            else:
                first = today.replace(day=1)
            last = (date(first.year + (first.month == 12), first.month % 12 + 1, 1) - timedelta(days=1))
            out = call("kpis", hotel_id=hotel, date_from=first.isoformat(), date_to=last.isoformat(), group_by="month")
            partial = "" if last < today else " (el mes incluye fechas futuras: reservas *on the books*)"
            return Reply(f"**KPIs {MONTH_NAMES[first.month - 1]} {first.year}**{partial}\n\n" + table(out["rows"], [("hotel_id", "Hotel"), ("occupancy", "Ocupación"), ("adr_usd", "ADR"), ("revpar_usd", "RevPAR"), ("room_revenue_usd", "Ingreso hab."), ("cancelled_room_nights", "Noches canceladas")],
                                                                      {"occupancy": pct, "adr_usd": usd, "revpar_usd": usd, "room_revenue_usd": usd, "cancelled_room_nights": lambda v: f"{v:,.0f}"}) + NOTE, calls, self.name)
        ejemplos = ("- «¿Cómo vino septiembre en Mendoza?» (KPIs)\n- «¿Cómo viene el ritmo de reservas los próximos 30 días?»\n"
                    "- «¿Qué canales nos dejan más neto?»\n- «¿Estamos caros vs. la competencia en Cartagena?»\n"
                    "- «¿Hay fugas de paridad con Booking?»\n- «¿Qué tan frescos están los datos?»")
        if agent:
            ejemplos += "\n- «Recomendame precios para los próximos 14 días»\n- «Proponé los cambios» (quedan pendientes de aprobación humana)"
        return Reply("No entendí bien la consulta. Algunas cosas que puedo responder:\n\n" + ejemplos + NOTE, calls, self.name)

    def _propose(self, text, hotel, calls, call) -> Reply:
        out = call("recommend_prices", hotel_id=hotel, horizon_days=_days(text, 30), limit=15, min_abs_change_pct=0.04)
        recs = out.get("recommendations", [])
        changes = [{k: r[k] for k in ("hotel_id", "room_type", "stay_date", "current_usd", "new_usd", "reasons")} for r in recs]
        if not changes:
            return Reply("No encontré cambios de precio con señal suficiente para proponer." + NOTE, calls, self.name)
        res = call("propose_price_changes", changes=changes)
        acc, rej = res.get("accepted", []), res.get("rejected", [])
        body = table(acc, [("id", "ID"), ("hotel_id", "Hotel"), ("room_type", "Hab."), ("stay_date", "Fecha"), ("current_usd", "Actual"), ("new_usd", "Propuesto")],
                     {"current_usd": usd, "new_usd": usd}, 20)
        return Reply(f"Dejé **{len(acc)} propuestas** en la cola (rechazadas por validación: {len(rej)}). **Nada se publicó**: una persona tiene que aprobarlas "
                     f"(`hotelsim approve --user <nombre>` o el botón del tablero).\n\n{body}" + NOTE, calls, self.name)
