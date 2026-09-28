"""Análisis del Excel de prospección telefónica (lo usa generar_tablero.py).

Calcula el embudo llamada → respuesta → interés → cierre por comercial, por mes
y por día de la semana, detecta patrones y arma los textos de la pestaña.
Con tan pocos días, cada porcentaje va con su intervalo de confianza para no
sacar conclusiones de la casualidad.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics as st
from collections import defaultdict

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
CAMPOS = ("llamadas", "respondieron", "interesados", "no_interesados")


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de confianza del 95% para una proporción (método de Wilson)."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def sumar(filas) -> dict:
    t = {k: sum(f[k] for f in filas) for k in CAMPOS}
    t["dias"] = len(filas)
    t["tasa_respuesta"] = t["respondieron"] / t["llamadas"] if t["llamadas"] else 0
    t["tasa_interes"] = t["interesados"] / t["respondieron"] if t["respondieron"] else 0
    t["interes_por_llamada"] = t["interesados"] / t["llamadas"] if t["llamadas"] else 0
    t["ic_interes"] = wilson(t["interesados"], t["llamadas"])
    t["llamadas_por_dia"] = t["llamadas"] / t["dias"] if t["dias"] else 0
    return t


def corr(xs, ys) -> float | None:
    try:
        return st.correlation(xs, ys) if len(xs) > 4 else None
    except st.StatisticsError:
        return None


def analizar(p: dict) -> dict:
    dias = p["dias"]
    for d in dias:
        f = dt.date.fromisoformat(d["fecha"])
        d["dow"] = f.weekday()
        d["etiqueta"] = f"{f.day}-{MESES_ES[f.month - 1]}"
        d["mes"] = d["fecha"][:7]
    comerciales = sorted({d["comercial"] for d in dias})
    cierres = defaultdict(lambda: {"cerrados": 0.0, "por_cerrar": 0.0})
    for c in p["cierres"]:
        cierres[c["comercial"]]["cerrados"] += c["cerrados"]
        cierres[c["comercial"]]["por_cerrar"] += c["por_cerrar"]
    cierres_mes = defaultdict(float)
    for c in p["cierres"]:
        cierres_mes[f"{p['anio']}-{c['mes']:02d}"] += c["cerrados"]

    total = sumar(dias)
    total["cerrados"] = sum(c["cerrados"] for c in cierres.values())
    total["por_cerrar"] = sum(c["por_cerrar"] for c in cierres.values())

    por_com = {}
    for c in comerciales:
        filas = [d for d in dias if d["comercial"] == c]
        t = sumar(filas)
        t.update(cierres[c])
        t["desde"], t["hasta"] = filas[0]["etiqueta"], filas[-1]["etiqueta"]
        t["tope_10"] = sum(1 for d in filas if d["respondieron"] == 10)
        t["corr_volumen_interes"] = corr([d["llamadas"] for d in filas], [d["interesados"] / d["llamadas"] for d in filas])
        t["corr_volumen_respuesta"] = corr([d["llamadas"] for d in filas], [d["respondieron"] / d["llamadas"] for d in filas])
        por_com[c] = t

    meses = sorted({d["mes"] for d in dias})
    por_mes = []
    for m in meses:
        fila = {"mes": m, "etiqueta": f"{MESES_ES[int(m[5:]) - 1]}-{m[2:4]}", "cerrados": cierres_mes.get(m, 0.0)}
        for c in comerciales:
            filas = [d for d in dias if d["mes"] == m and d["comercial"] == c]
            fila[c] = sumar(filas) if filas else None
        fila["total"] = sumar([d for d in dias if d["mes"] == m])
        por_mes.append(fila)

    por_dow = []
    for i in range(7):
        filas = [d for d in dias if d["dow"] == i]
        if filas:
            t = sumar(filas)
            t["dia"] = DIAS[i]
            por_dow.append(t)

    # ¿Cuántas llamadas hacen falta para un alta? (solo meses con cierres registrados)
    llam_con_cierre = sum(pm["total"]["llamadas"] for pm in por_mes if pm["cerrados"] > 0)
    int_con_cierre = sum(pm["total"]["interesados"] for pm in por_mes if pm["cerrados"] > 0)
    cerr_total = sum(pm["cerrados"] for pm in por_mes)
    sin_cierre = [pm for pm in por_mes if pm["cerrados"] == 0]
    int_sin_cierre = sum(pm["total"]["interesados"] for pm in sin_cierre)

    return {
        "comerciales": comerciales, "total": total, "por_com": por_com, "por_mes": por_mes, "por_dow": por_dow,
        "llam_por_alta": llam_con_cierre / cerr_total if cerr_total else None,
        "int_a_alta": cerr_total / int_con_cierre if int_con_cierre else None,
        "int_sin_cierre": int_sin_cierre, "meses_sin_cierre": [pm["etiqueta"] for pm in sin_cierre],
        "avisos": p["avisos"],
        "dias": [{k: d[k] for k in ("comercial", "fecha", "etiqueta", "dow", "mes") + CAMPOS} for d in dias],
    }


def textos(a: dict) -> dict:
    t, pc = a["total"], a["por_com"]
    mejor_dow = max(a["por_dow"], key=lambda x: x["interes_por_llamada"])
    peor_dow = min(a["por_dow"], key=lambda x: x["interes_por_llamada"])
    # Evolución de la tasa de interés del comercial con más meses.
    principal = max(pc, key=lambda c: pc[c]["llamadas"])
    serie = [(pm["etiqueta"], pm[principal]) for pm in a["por_mes"] if pm[principal] and pm[principal]["dias"] >= 3]
    otro = [c for c in a["comerciales"] if c != principal]
    patrones = []
    patrones.append((
        "Atienden casi todas las llamadas: la tasa de contacto es altísima.",
        f"De {t['llamadas']:.0f} llamadas, {t['respondieron']:.0f} tuvieron respuesta (<b>{pct(t['tasa_respuesta'])}</b>). "
        f"En llamadas en frío B2B lo habitual es 8–12% por llamada y 18–25% con dueños de PyME. Hay dos explicaciones posibles: "
        f"se llama a bases tibias (clientes, referidos o contactos previos) o “respondió” incluye cualquier contacto, aunque no sea con quien decide. "
        f"Conviene separar <i>atendió</i> de <i>habló con quien decide</i>."))
    topes = ", ".join(f"{c} en {pc[c]['tope_10']} de {pc[c]['dias']:.0f} días" for c in a["comerciales"] if pc[c]["tope_10"])
    if topes:
        patrones.append((
            "El día termina al llegar a 10 conversaciones.",
            f"Ningún día supera 10 respuestas, y muchos terminan justo en 10 ({topes}). Parece que la meta real es "
            f"<b>10 conversaciones por día</b>, no una cantidad de llamadas. Es una buena meta, pero explica por qué los días con más llamadas "
            f"son los días en que costó más que atiendan."))
    cv = pc[principal]["corr_volumen_respuesta"]
    if cv is not None and cv < -0.3:
        patrones.append((
            f"Más llamadas en el día no significa más interesados ({principal}).",
            f"En los días de {principal}, cuantas más llamadas hizo, menor fue la tasa de respuesta (correlación {str(round(cv, 2)).replace('.', ',')}) y también el interés "
            f"por llamada ({str(round(pc[principal]['corr_volumen_interes'], 2)).replace('.', ',')}). No es cansancio: es la regla de “llamar hasta 10”. "
            f"Los días en que la base atiende poco necesitan más discado. Por eso lo que hay que mejorar es la <b>calidad de la base</b>, no el esfuerzo."))
    if len(serie) >= 2:
        (e0, s0), (e1, s1) = serie[0], serie[-1]
        patrones.append((
            f"El interés de {principal} bajó de {pct(s0['tasa_interes'])} a {pct(s1['tasa_interes'])} de los que atienden.",
            f"En {e0}, {pct(s0['tasa_interes'])} de los que atendieron se mostraron interesados. En {e1}, {pct(s1['tasa_interes'])}. "
            f"Suele pasar cuando se agota la mejor parte de la base (los contactos más calientes se llaman primero) o cuando se empieza a "
            f"registrar el interés con un criterio más exigente. Hay que revisar de qué lista salió cada llamada."))
    if a["int_a_alta"] is not None:
        patrones.append((
            "El cuello de botella está después del “me interesa”.",
            f"En los meses con cierres registrados hicieron falta unas <b>{a['llam_por_alta']:.0f} llamadas por alta</b> y convirtió "
            f"<b>{pct(a['int_a_alta'])}</b> de los interesados. En {', '.join(a['meses_sin_cierre'])} hubo <b>{a['int_sin_cierre']:.0f} interesados</b> "
            f"y ningún cierre registrado, y los {t['por_cerrar']:.0f} “por cerrar” de julio no se actualizaron. Se genera interés, pero no hay un "
            f"seguimiento visible hasta el alta: ahí se pierde la mayor parte del valor."))
    if otro:
        o = pc[otro[0]]
        patrones.append((
            f"{otro[0]} dejó de registrar llamadas después del {o['hasta']}.",
            f"{otro[0]} registró {o['dias']:.0f} días ({o['desde']} a {o['hasta']}), con {pct(o['interes_por_llamada'])} de interesados por llamada, "
            f"contra {pct(pc[principal]['interes_por_llamada'])} de {principal}. Si sigue en el equipo, faltan sus datos. Si no, conviene saberlo "
            f"para medir la capacidad real del equipo."))
    lo, hi = mejor_dow["ic_interes"]
    patrones.append((
        f"Por día de la semana: {mejor_dow['dia'].lower()} rindió más y {peor_dow['dia'].lower()} menos, pero todavía no es concluyente.",
        f"{mejor_dow['dia']}: {pct(mejor_dow['interes_por_llamada'])} de interesados por llamada ({mejor_dow['llamadas']:.0f} llamadas en "
        f"{mejor_dow['dias']} días). {peor_dow['dia']}: {pct(peor_dow['interes_por_llamada'])}. Con tan pocos datos, el rango probable de "
        f"{mejor_dow['dia'].lower()} va de {pct(lo)} a {pct(hi)}, así que se superpone con el resto. Los estudios grandes marcan martes a jueves "
        f"como los mejores días y lunes y viernes como los peores. Para confirmarlo acá hacen falta 2 o 3 meses más de registro."))
    patrones.append((
        "No hay datos de horario.",
        "El Excel anota llamadas por día, no por hora, así que no se puede saber a qué hora conviene llamar. Los estudios coinciden en dos ventanas: "
        "10 a 12 h y 16 a 18 h, en el horario del prospecto. Agregar una columna de hora (o usar un discador que la registre) resuelve esto en pocas semanas."))

    benchmark = [
        ("Llamadas por día y por comercial", f"{t['llamadas_por_dia']:.0f}", "40–80 (SDR full time); 80–100 para PyMEs", "Bajo si es jornada completa; razonable si es media jornada."),
        ("Tasa de contacto (atiende / llamadas)", pct(t["tasa_respuesta"]), "8–12% en frío; 18–25% con dueños de PyME", "Muy alta: base tibia, o criterio amplio de “respondió”."),
        ("Interesados / conversaciones", pct(t["tasa_interes"]), "≈5% (reuniones por conversación); 15–17% los mejores", "Muy alta: conviene definir qué cuenta como “interesado”."),
        ("Llamadas por alta", f"{a['llam_por_alta']:.0f}" if a["llam_por_alta"] else "–", "≈40 llamadas por reunión; cientos por venta", "Muy bueno en julio; sin cierres registrados después."),
        ("Intentos por prospecto", "No se registra", "8 intentos promedio para llegar a quien decide; 80% de las ventas llegan después del 5° contacto", "Hay que medir cuántos contactos lleva cada alta."),
        ("Horario", "No se registra", "10–12 h y 16–18 h", "Agregar la hora a cada llamada."),
    ]
    sugerencias = [
        ("Pasar del Excel por día a un registro por llamada", "Una fila por llamada con fecha, hora, comercial, empresa, rubro, origen del contacto (base, referido, cliente), "
         "resultado y próximo paso. Con eso salen solos los horarios, las mejores bases y el embudo por comercial. Alcanza con Google Sheets y un formulario, o un CRM gratuito."),
        ("Definir las etapas con criterio único", "“Respondió” = habló con quien decide. “Interesado” = aceptó una propuesta o una reunión con fecha. “Por cerrar” = tiene "
         "propuesta enviada. “Cerrado” = alta en Equifax. Hoy la tasa de interés es tan alta que probablemente mezcla curiosidad con intención real."),
        ("Cadencia de seguimiento para cada interesado", f"Hubo {a['int_sin_cierre']:.0f} interesados sin cierre registrado. Una cadencia simple: mail o WhatsApp el mismo día, "
         "llamada a las 48 h, otra a los 7 días y una última a los 15. Asignar cada interesado a quien cierra (el equipo comercial) con fecha límite."),
        ("Medir por comercial: conversaciones, interesados reales y altas", "Mantener la meta de 10 conversaciones por día, pero medir el resultado con altas y con el "
         "costo por alta (lo que se le paga al comercial dividido las altas). Es la forma de comparar el call center fijo de 1 M con pagar por alta."),
        ("Probar horarios y días a propósito", "Durante 4 semanas, repartir los bloques de llamadas entre 10–12 h y 16–18 h y anotar la hora. Con unas 400 llamadas registradas "
         "ya se puede ver si el horario cambia el resultado en Cuyo."),
        ("Mejorar la base antes que el volumen", "Priorizar contactos con teléfono directo del dueño o gerente, rubros que ya compraron (inmobiliarias, financieras, "
         "comercios con venta a crédito) y referidos de clientes. Una base mejor sube el contacto y el interés sin más horas de llamadas."),
        ("Guion corto y práctica semanal", "Guion de 30 segundos (quién soy, por qué llamo, qué problema resuelve el informe Equifax, una pregunta), manejo de las 3 "
         "objeciones más comunes y 30 minutos semanales escuchando llamadas. Según los estudios, el coaching frecuente puede multiplicar la conversión."),
        ("Cerrar el circuito con finanzas", "Cruzar cada alta con la comisión que paga Equifax: así se sabe cuánto vale una llamada y cuánto se puede invertir en "
         "prospección. Por ejemplo, un variable por alta para quien prospecta, en la línea del variable comercial que ya se aplica desde ago-26."),
    ]
    return {"patrones": patrones, "benchmark": benchmark, "sugerencias": sugerencias}
