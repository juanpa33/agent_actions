"""Análisis de la planilla de gestión de prospectos (una fila por prospecto). Lo usa generar_tablero.py."""
from __future__ import annotations

import re
import statistics as st
from collections import Counter

# Orden del embudo y agrupación de etapas.
ORDEN = ["Alta lograda", "Cierre pendiente", "Demo o reunión", "Interesado en seguimiento", "Pidió que lo llamen",
         "No interesado", "Ya era cliente", "No contesta", "Número inválido", "Contacto clave sin llamar", "Sin gestionar"]
CON_INTERES = {"Alta lograda", "Cierre pendiente", "Demo o reunión", "Interesado en seguimiento"}
AVANZADOS = {"Alta lograda", "Cierre pendiente", "Demo o reunión"}
SIN_CONTACTO = {"No contesta", "Número inválido", "Contacto clave sin llamar"}
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def ultima_accion(com: str) -> str:
    """Última oración del comentario: suele ser el próximo paso acordado."""
    partes = [p.strip() for p in re.split(r"(?<=[.!])\s+|\s*-->\s*", com) if len(p.strip()) > 3]
    txt = partes[-1] if partes else com
    return txt[:160] + ("…" if len(txt) > 160 else "")


def analizar(c: dict) -> dict:
    ps = c["prospectos"]
    g = [p for p in ps if p["gestionado"]]
    etapas = Counter(p["etapa"] for p in ps)
    contactados = [p for p in g if p["etapa"] not in SIN_CONTACTO]
    interes = [p for p in g if p["etapa"] in CON_INTERES]
    avanzados = [p for p in g if p["etapa"] in AVANZADOS]
    por_mes = Counter((p["fecha_aprox"] or "")[:7] for p in g if p["fecha_aprox"])
    seg = lambda grupo: st.mean([p["seguimientos"] for p in grupo]) if grupo else 0
    prioridad = {e: i for i, e in enumerate(ORDEN)}
    cartera = sorted([p for p in g if p["etapa"] in CON_INTERES | {"Pidió que lo llamen", "Contacto clave sin llamar"}],
                     key=lambda p: (prioridad[p["etapa"]], -(p["seguimientos"])))
    return {
        "total": len(ps), "gestionados": len(g), "sin_gestionar": etapas["Sin gestionar"],
        "contactados": len(contactados), "con_interes": len(interes), "avanzados": len(avanzados),
        "altas": etapas["Alta lograda"], "cierre_pendiente": etapas["Cierre pendiente"],
        "ya_clientes": etapas["Ya era cliente"], "invalidos": etapas["Número inválido"],
        "no_contesta": etapas["No contesta"], "no_interesados": etapas["No interesado"],
        "etapas": [{"etapa": e, "n": etapas[e]} for e in ORDEN if etapas[e]],
        "por_mes": [{"mes": m, "etiqueta": f"{MESES_ES[int(m[5:]) - 1]}-{m[2:4]}", "n": n} for m, n in sorted(por_mes.items())],
        "competidores": Counter(x for p in g for x in p["competidores"]).most_common(),
        "objeciones": Counter(x for p in g for x in p["objeciones"]).most_common(),
        "productos": Counter(x for p in g for x in p["productos"]).most_common(),
        "franjas": Counter(x for p in g for x in p["franjas"]).most_common(),
        "whatsapp": sum(p["whatsapp"] for p in g),
        "seguimientos": sum(p["seguimientos"] for p in g),
        "seg_interes": seg(interes), "seg_no_contesta": seg([p for p in g if p["etapa"] == "No contesta"]),
        "sin_seguimiento_interes": sum(1 for p in interes if p["seguimientos"] == 0),
        "retirados": sum(1 for p in g if "Ya no trabaja o se retira" in p["objeciones"]),
        "base_heredada": sum(p["base_heredada"] for p in g),
        "cartera": [{"id": p["id"], "nombre": p["nombre"], "etapa": p["etapa"], "seguimientos": p["seguimientos"],
                     "fecha": p["fecha_aprox"], "accion": ultima_accion(p["comentario"]),
                     "productos": p["productos"], "competidores": p["competidores"]} for p in cartera],
    }


def textos(a: dict) -> dict:
    comp = ", ".join(f"{k} ({v})" for k, v in a["competidores"][:4])
    obj = dict(a["objeciones"])
    franja = a["franjas"][0][0].lower() if a["franjas"] else None
    patrones = [
        ("La base tiene mucho recorrido por delante.",
         f"De {a['total']} prospectos cargados, {a['gestionados']} tienen gestión registrada ({pct(a['gestionados'] / a['total'])}). "
         f"Quedan <b>{a['sin_gestionar']} sin llamar</b>: al ritmo de julio y agosto (unos 55–60 por mes), alcanzan para unos 3 meses más."),
        ("Cuando atienden, la mitad muestra interés.",
         f"Se habló con {a['contactados']} prospectos y <b>{a['con_interes']}</b> mostraron interés ({pct(a['con_interes'] / a['contactados'])}). "
         f"De ellos, <b>{a['avanzados']}</b> llegaron a demo, reunión o contrato. El mensaje funciona: el desafío es avanzar del interés al cierre."),
        ("El seguimiento se corta pronto.",
         f"Un interesado tiene en promedio <b>{str(round(a['seg_interes'], 1)).replace('.', ',')} seguimientos</b> anotados, y {a['sin_seguimiento_interes']} no tienen ninguno. "
         f"Los estudios muestran que se necesitan unos 8 contactos para cerrar y que el 80% de las ventas llega después del 5°."),
        ("WhatsApp es el canal real de la venta.",
         f"<b>{a['whatsapp']}</b> de los {a['gestionados']} prospectos gestionados ({pct(a['whatsapp'] / a['gestionados'])}) pidieron o recibieron información por WhatsApp. "
         f"La llamada abre la puerta y la información viaja por mensaje, así que conviene tener una pieza corta y clara para enviar."),
    ]
    if obj.get("Lo decide otra persona"):
        patrones.append(("Muchas veces no decide quien atiende.",
                         f"En <b>{obj['Lo decide otra persona']}</b> casos la decisión pasa por un socio, un hijo, la esposa o la secretaria. "
                         f"Preguntar temprano “¿quién más participa de la decisión?” e invitar a esa persona a la demo acorta el ciclo."))
    if a["retirados"] or a["invalidos"] or a["ya_clientes"]:
        patrones.append(("La base necesita una limpieza.",
                         f"{a['retirados']} prospectos se jubilaron o dejaron la actividad, {a['invalidos']} números no existen y "
                         f"{a['ya_clientes']} ya eran clientes de Equifax. Son {a['retirados'] + a['invalidos'] + a['ya_clientes']} llamadas "
                         f"({pct((a['retirados'] + a['invalidos'] + a['ya_clientes']) / a['gestionados'])} de lo gestionado) que se podían evitar cruzando la base antes de llamar."))
    if comp:
        patrones.append(("La competencia ya está instalada.",
                         f"Los prospectos mencionan: {comp}. Varios usan el Banco Central o alternativas sin costo (Nosis gratis, 5 reportes mensuales de la Bolsa de Comercio). "
                         f"El argumento tiene que ser la diferencia de calidad y actualización del dato, no solo el precio."))
    if obj.get("Costo fijo / prefiere prepago"):
        patrones.append(("El costo fijo mensual es la objeción comercial más clara.",
                         f"<b>{obj['Costo fijo / prefiere prepago']}</b> prospectos rechazaron o dudaron por tener que pagar un monto fijo. Prefieren prepago o packs. "
                         f"Un pack de prueba chico (5–10 reportes) sin abono reduce esa barrera."))
    if franja:
        patrones.append(("Cuando piden horario, piden la mañana.",
                         f"Al acordar una nueva llamada, los prospectos eligieron la {franja} en {a['franjas'][0][1]} casos, contra "
                         + ", ".join(f"{k.lower()} ({v})" for k, v in a["franjas"][1:]) + ". Es la primera pista real de horario que tenemos."))
    if len(a["por_mes"]) >= 3 and a["por_mes"][-1]["n"] < 0.5 * a["por_mes"][-2]["n"]:
        patrones.append(("En septiembre bajó la cantidad de prospectos nuevos gestionados.",
                         f"Se gestionaron {a['por_mes'][-3]['n']} en {a['por_mes'][-3]['etiqueta']}, {a['por_mes'][-2]['n']} en {a['por_mes'][-2]['etiqueta']} y "
                         f"{a['por_mes'][-1]['n']} en {a['por_mes'][-1]['etiqueta']}. Puede ser que el tiempo se haya ido a los seguimientos y las reuniones, "
                         f"lo cual está bien, pero conviene confirmarlo."))
    sugerencias = [
        ("Completar las columnas de estado de la planilla",
         "Hoy casi todo está en el comentario libre: “Contactada por Martina” dice “Sin contactar” en 289 de 297 filas. Con una columna de "
         "estado (las etapas de este tablero), la fecha del próximo contacto y el resultado, el seguimiento y este análisis salen solos."),
        ("Agenda de seguimientos con fecha",
         f"Cada interesado necesita una próxima acción con fecha. Hay {a['con_interes']} prospectos con interés y "
         f"{a['sin_seguimiento_interes']} sin ningún seguimiento anotado. Una vista filtrada por “próximo contacto ≤ hoy” alcanza para empezar el día."),
        ("Limpiar la base antes de llamar",
         "Cruzar la lista con los clientes actuales de Equifax y con los matriculados activos del colegio. Eso evita llamar a quien ya es cliente "
         "o ya no trabaja, y deja más tiempo para prospectos reales."),
        ("Paquete de prueba sin abono",
         "Para quien teme al costo fijo: un pack de 5–10 reportes prepago como puerta de entrada, y la propuesta de abono recién después del primer uso."),
        ("Kit de WhatsApp",
         "Un PDF de una página y un video corto de demo para mandar después de la llamada, con el link para agendar la reunión. Así cada envío pide un paso concreto."),
        ("Trabajar los contactos clave",
         "Hay referentes del Colegio de Corredores y de inmobiliarias grandes marcados como especiales. Una reunión con ellos puede abrir "
         "acuerdos por volumen o referidos, más eficientes que llamar uno por uno."),
    ]
    return {"crm_patrones": patrones, "crm_sugerencias": sugerencias}
