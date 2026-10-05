"""Genera el tablero de control (un único HTML, funciona sin internet).

Uso:
    python generar_tablero.py [datos/virtus_mensual.json] [salida/tablero_virtus.html]

Lee la serie que produce extraer_datos.py, calcula los indicadores del negocio
y arma el texto de análisis con esos números, así cada vez que se agrega una
liquidación al Excel alcanza con volver a correr los dos scripts.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import crm
import prospeccion

AQUI = Path(__file__).parent
MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Rubros que se pagan todos los meses aunque no se venda nada (estructura).
RUBROS_FIJOS = ["Equipo comercial", "Call center", "Contadora", "Oficina y alquiler",
                "Tarjeta de crédito", "Promoción y merchandising", "Fee Equifax"]


def etiqueta(mes: str) -> str:
    a, m = mes.split("-")
    return f"{MESES_ES[int(m) - 1]}-{a[2:]}"


def M(x: float) -> str:
    """Formato en millones estilo argentino: 12,3 M."""
    return f"{x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x: float, dec: int = 0) -> str:
    return f"{x * 100:.{dec}f}%".replace(".", ",")


def deflactor(ipc: dict) -> dict[str, float]:
    """Factor para llevar pesos de cada mes a pesos del mes base."""
    idx, acum = {}, 1.0
    for mes in sorted(ipc["mensual"]):
        acum *= 1 + ipc["mensual"][mes] / 100
        idx[mes] = acum
    base = idx[ipc["base"]]
    return {m: base / v for m, v in idx.items()}


def por_rubro(m: dict) -> dict[str, float]:
    r = defaultdict(float)
    for g in m["gastos"]:
        r[g["rubro"]] += g["monto"]
    return dict(r)


def analizar(datos: dict, ipc: dict) -> dict:
    f = deflactor(ipc)
    socios = datos["socios"]
    meses = datos["meses"]
    con_detalle = [m for m in meses if m.get("ingreso")]
    for m in meses:
        m["etiqueta"] = etiqueta(m["mes"])
        m["factor_real"] = f.get(m["mes"], 1.0)
        m["rubros"] = por_rubro(m)
        m["pct_gastos"] = m["total_gastos"] / m["ingreso"] if m.get("ingreso") else None

    ing = [m["ingreso"] for m in con_detalle]
    l12 = con_detalle[-12:]
    prev = con_detalle[:-12]
    real = lambda m, k: m[k] * m["factor_real"]

    tot = {k: sum(m[k] for m in con_detalle) for k in ("ingreso", "total_gastos", "neto_socios", "resguardo")}
    tot12 = {k: sum(m[k] for m in l12) for k in ("ingreso", "total_gastos", "neto_socios", "resguardo")}
    rub12 = defaultdict(float)
    for m in l12:
        for k, v in m["rubros"].items():
            rub12[k] += v

    # Primer y último semestre, en pesos constantes.
    ini, fin = con_detalle[:6], con_detalle[-6:]
    real_ini = st.mean(real(m, "ingreso") for m in ini)
    real_fin = st.mean(real(m, "ingreso") for m in fin)

    # Estructura fija del último mes y punto de equilibrio.
    ult = con_detalle[-1]
    fijos_ult = sum(v for k, v in ult["rubros"].items() if k in RUBROS_FIJOS)
    variable_ro = sum(g["monto"] for g in ult["gastos"] if g["concepto"].startswith("Variable"))
    fijos_ult -= variable_ro
    # Costos que acompañan al ingreso: impuestos + bancos (últimos 6 meses).
    var6 = sum(m["rubros"].get("Impuestos", 0) + m["rubros"].get("Bancos e imp. al cheque", 0) for m in fin)
    tasa_var = var6 / sum(m["ingreso"] for m in fin)
    equilibrio = fijos_ult / (1 - tasa_var)

    # Estructura fija por mes (para la curva de apalancamiento).
    for m in con_detalle:
        m["fijos"] = sum(v for k, v in m["rubros"].items() if k in RUBROS_FIJOS)

    cv12 = st.pstdev(m["ingreso"] for m in l12) / st.mean(m["ingreso"] for m in l12)
    top2 = sorted(l12, key=lambda m: -m["ingreso"])[:2]
    meses_bajo_eq = [m for m in con_detalle if m["ingreso"] < equilibrio * 1.5]

    # Evolución de costos puntuales (nominal vs inflación).
    def primero_ultimo(rubro_concepto: str):
        serie = [(m["mes"], sum(g["monto"] for g in m["gastos"] if rubro_concepto in g["concepto"].lower()))
                 for m in con_detalle]
        serie = [(k, v) for k, v in serie if v > 0]
        return serie[0], serie[-1]

    cont0, cont1 = primero_ultimo("contadora")
    infl_cont = f[cont0[0]] / f[cont1[0]]

    # Socios: acumulado y promedio.
    acum = {s: sum(m["reparto"].get(s, 0) for m in meses) for s in socios}
    acum_real = {s: sum(m["reparto"].get(s, 0) * m["factor_real"] for m in meses) for s in socios}
    reint = {s: sum(m["reintegros"].get(s, 0) for m in meses) for s in socios}
    cc_mg = sum(m["rubros"].get("Call center", 0) for m in con_detalle)

    bancos12 = rub12.get("Bancos e imp. al cheque", 0)
    imp12 = rub12.get("Impuestos", 0)
    tarjeta12 = rub12.get("Tarjeta de crédito", 0)
    reint12 = rub12.get("Reintegros y viajes", 0)
    promo12 = rub12.get("Promoción y merchandising", 0)
    cc12 = rub12.get("Call center", 0)
    imp_ult = ult["rubros"].get("Impuestos", 0)

    # Meses sin provisión de impuestos (solo "impuestos varios").
    sin_prov = [m for m in con_detalle if m["mes"] >= "2025-08" and m["rubros"].get("Impuestos", 0) < 100_000]

    return {
        "tot": tot, "tot12": tot12, "rub12": dict(sorted(rub12.items(), key=lambda x: -x[1])),
        "l12_desde": l12[0]["etiqueta"], "l12_hasta": l12[-1]["etiqueta"], "prev_n": len(prev),
        "n_meses": len(con_detalle), "desde": con_detalle[0]["etiqueta"], "hasta": ult["etiqueta"],
        "real_ini": real_ini, "real_fin": real_fin, "crec_real": real_fin / real_ini - 1,
        "ini_rango": f'{ini[0]["etiqueta"]} a {ini[-1]["etiqueta"]}', "fin_rango": f'{fin[0]["etiqueta"]} a {fin[-1]["etiqueta"]}',
        "fijos_ult": fijos_ult, "tasa_var": tasa_var, "equilibrio": equilibrio, "ult": ult["etiqueta"],
        "ult_ingreso": ult["ingreso"], "variable_ro": variable_ro,
        "cv12": cv12, "top2": [(m["etiqueta"], m["ingreso"]) for m in top2],
        "top2_share": sum(m["ingreso"] for m in top2) / tot12["ingreso"],
        "max": max(con_detalle, key=lambda m: m["ingreso"]), "min": min(con_detalle, key=lambda m: m["ingreso"]),
        "meses_bajo_eq": [m["etiqueta"] for m in meses_bajo_eq],
        "cont0": cont0, "cont1": cont1, "infl_cont": infl_cont,
        "acum": acum, "acum_real": acum_real, "reint": reint, "cc_mg": cc_mg,
        "bancos12": bancos12, "imp12": imp12, "tarjeta12": tarjeta12, "reint12": reint12,
        "promo12": promo12, "cc12": cc12, "imp_ult": imp_ult,
        "sin_prov": [m["etiqueta"] for m in sin_prov],
        "pct_ingreso_min_max": (min(m["pct_gastos"] for m in con_detalle), max(m["pct_gastos"] for m in con_detalle)),
    }


def textos(a: dict) -> dict[str, str]:
    """Conclusiones e ideas, con los números del análisis."""
    t, t12 = a["tot"], a["tot12"]
    mx, mn = a["max"], a["min"]
    conclusiones = [
        ("El negocio es muy rentable en caja… cuando la comisión llega.",
         f"En los últimos 12 meses ({a['l12_desde']} a {a['l12_hasta']}) Equifax transfirió <b>{M(t12['ingreso'])}</b>; "
         f"la estructura consumió <b>{M(t12['total_gastos'])}</b> ({pct(t12['total_gastos'] / t12['ingreso'])}) y a los socios les quedó "
         f"<b>{M(t12['neto_socios'])}</b> ({pct(t12['neto_socios'] / t12['ingreso'])}). Ojo al compararlo con el 19–24% de margen neto "
         f"que se publica para franquicias de servicios: ese margen es <i>después</i> de pagar sueldos, y acá los cuatro socios trabajan en el "
         f"negocio sin sueldo. Lo que reciben es sueldo y ganancia juntos."),
        ("El ingreso es muy volátil y está concentrado en pocos meses.",
         f"El coeficiente de variación de los últimos 12 meses es <b>{pct(a['cv12'])}</b>. Dicho simple: un mes normal se aleja del promedio en más de la mitad. "
         f"Solo {a['top2'][0][0]} y {a['top2'][1][0]} explican el <b>{pct(a['top2_share'])}</b> del año. El mejor mes ({mx['etiqueta']}, {M(mx['ingreso'])}) "
         f"fue {mx['ingreso'] / mn['ingreso']:.0f} veces el peor ({mn['etiqueta']}, {M(mn['ingreso'])}). Para una franquicia que cobra comisión, "
         f"esto es lo más importante que hay que gestionar."),
        ("Creció fuerte incluso descontando la inflación.",
         f"En pesos constantes de {a['hasta']}, el cobro promedio pasó de <b>{M(a['real_ini'])}</b> por mes ({a['ini_rango']}) a "
         f"<b>{M(a['real_fin'])}</b> ({a['fin_rango']}): <b>{'+' if a['crec_real'] >= 0 else ''}{pct(a['crec_real'])}</b> real. La cartera de Cuyo está madurando."),
        ("La estructura fija es chica frente a un buen mes, pero pesa mucho en uno malo.",
         f"Hoy la estructura fija ronda <b>{M(a['fijos_ult'])}</b> por mes (equipo comercial fijo, call center, contadora, oficina, tarjeta, promoción). "
         f"Impuestos y bancos se llevan cerca de <b>{pct(a['tasa_var'], 1)}</b> de lo cobrado. Con eso, el <b>punto de equilibrio</b> es de unos "
         f"<b>{M(a['equilibrio'])}</b> por mes. Los gastos fueron del {pct(a['pct_ingreso_min_max'][0])} al {pct(a['pct_ingreso_min_max'][1])} "
         f"del ingreso según el mes. Eso es <i>apalancamiento operativo</i>: los costos casi no se mueven y el resultado sube o baja con la comisión."),
        ("Los impuestos se pagaron a los saltos, sin provisión.",
         f"Entre {a['sin_prov'][0]} y {a['sin_prov'][-1]} casi no se descontaron impuestos (solo “impuestos varios”). Desde may-26 aparecen VEP, IVA faltante y "
         f"Ganancias juntos: en {a['ult']} los impuestos fueron <b>{M(a['imp_ult'])}</b>, el {pct(a['imp_ult'] / a['ult_ingreso'])} de lo cobrado ese mes. "
         f"Se repartió plata que en parte era del fisco, y después hubo que devolverla con meses flojos.") if a["sin_prov"] else
        ("Impuestos", ""),
        ("Algunos costos crecieron más rápido que la inflación.",
         f"La contadora pasó de {M(a['cont0'][1])} ({etiqueta(a['cont0'][0])}) a {M(a['cont1'][1])} ({etiqueta(a['cont1'][0])}): "
         f"+{pct(a['cont1'][1] / a['cont0'][1] - 1)} nominal contra +{pct(a['infl_cont'] - 1)} de inflación. "
         f"En cambio, el call center sigue en 1 M fijo desde el inicio, así que en términos reales hoy cuesta menos."),
        ("Hay gastos sin detalle y gastos que benefician a un socio en particular.",
         f"La tarjeta de crédito ({M(a['tarjeta12'])} en 12 meses) figura como un solo número. Los reintegros y viajes ({M(a['reint12'])}) "
         f"se pagan antes de repartir, así que los financian los cuatro socios según su %. El call center ({M(a['cc_mg'])} acumulado) se transfiere "
         f"a MG junto con su parte. No hay nada irregular en eso, pero conviene que quede escrito y con precio de mercado."),
    ]
    ideas = [
        ("Computar el impuesto al cheque contra Ganancias", "Impuestos", "Alta", "Baja",
         f"Los bancos y el impuesto a los créditos y débitos costaron <b>{M(a['bancos12'])}</b> en 12 meses. Si Virtus tiene Certificado MiPyME "
         f"como micro o pequeña empresa, puede tomar el 100% del impuesto como pago a cuenta de Ganancias (si no, solo una parte). "
         f"Ahorro posible: hasta <b>{M(a['bancos12'])}</b> por año. Pedíselo a la contadora esta semana.",
         a["bancos12"]),
        ("Provisión mensual de impuestos en un fondo money market", "Impuestos", "Alta", "Baja",
         f"Separar todos los meses cerca del {pct(a['tasa_var'], 0)} de lo cobrado para IVA, Ganancias e IIBB, antes de repartir. "
         f"Suscribir y rescatar FCI está exento del impuesto al cheque, y la plata rinde mientras espera el vencimiento. "
         f"Así se evita repartir en un buen mes lo que después falta en uno malo, como pasó en {a['ult']}.",
         None),
        ("Fondo de resguardo con meta y regla fija", "Caja", "Alta", "Baja",
         f"Hoy el resguardo es chico (en promedio {M(a['tot12']['resguardo'] / 12)} por mes) y se usa para lo que surja. Con un "
         f"{pct(a['cv12'])} de variabilidad, la meta razonable es 2 a 3 meses de estructura: <b>{M(2 * a['fijos_ult'])} a {M(3 * a['fijos_ult'])}</b>. "
         f"Regla simple: cuando el mes supera el punto de equilibrio, 10% del excedente va al fondo hasta llegar a la meta.",
         None),
        ("Pasar parte de los costos fijos a variables", "Estructura", "Alta", "Media",
         f"El variable comercial que empezó en ago-26 va en la dirección correcta. En ventas B2B lo habitual es 60% fijo y 40% variable. "
         f"Se puede hacer lo mismo con el call center ({M(a['cc12'])} al año, hoy 100% fijo): una parte fija más un monto por alta o por reunión lograda. "
         f"Si 30% de lo fijo pasa a variable, en un mes malo se ahorran unos <b>{M(0.3 * a['fijos_ult'])}</b>. "
         f"El impacto anual estimado supone 3 meses flojos por año.",
         0.3 * a["fijos_ult"] * 3),
        ("Tarjeta de crédito: detalle, tope y categoría", "Gastos", "Media", "Baja",
         f"Es de los rubros más grandes ({M(a['tarjeta12'])} en 12 meses) y el Excel no muestra en qué se gastó. "
         f"Propuesta: cargar el resumen con categorías (software, publicidad, viajes, personal), poner un tope mensual y no mezclar gastos personales. "
         f"Con un 20% de ahorro, que suele aparecer apenas se mira el detalle: <b>{M(0.2 * a['tarjeta12'])}</b> por año.",
         0.2 * a["tarjeta12"]),
        ("Política de reintegros y viajes", "Gobierno", "Media", "Baja",
         f"Reintegros y viajes sumaron {M(a['reint12'])}. Hace falta un presupuesto anual por socio, aprobación previa de los viajes y comprobantes. "
         f"Si un gasto beneficia a un solo socio, se descuenta de su parte y no del bruto.",
         None),
        ("Actualizar honorarios y alquiler por índice", "Gastos", "Media", "Baja",
         f"Ajustar contadora y alquiler por IPC o cada 6 meses, en lugar de saltos negociados. La contadora creció "
         f"{pct(a['cont1'][1] / a['cont0'][1] - 1)} contra {pct(a['infl_cont'] - 1)} de inflación: vale la pena revisar qué incluye el abono "
         f"(sueldos, IIBB, balance).",
         None),
        ("Medir la venta, no solo la plata", "Crecimiento", "Alta", "Media",
         "El Excel registra dinero pero no actividad: altas por mes, abonos activos, bajas, ticket promedio y comisión por producto. "
         "Con esos datos se puede anticipar la comisión, saber qué producto conviene empujar y medir si eventos como el sponsor de San Juan o "
         "las “Altas amigas” generan ventas.",
         None),
        ("Crecer en San Juan y San Luis con referidores", "Crecimiento", "Media", "Media",
         "Mendoza tiene unas 24 mil empresas empleadoras (5° del país). San Juan y San Luis tienen menos densidad pero menos competencia. "
         "Un programa de referidos pago <i>por alta</i> con estudios contables, inmobiliarias, cámaras empresarias y agencias de autos "
         "(el “Altas amigas” llevado a escala) suma ventas sin sumar costo fijo.",
         None),
        ("Calendario de liquidación y control de cobranza", "Caja", "Media", "Baja",
         "Ventas de ene-26 entraron en marzo y las de jul-26 y ago-26 entraron las dos en septiembre. Anotar la fecha de cada cobro y reclamar los "
         "atrasos a Equifax. Mientras tanto, conviene pagar un adelanto fijo mensual a los socios y hacer un ajuste trimestral, así los atrasos no llegan "
         "a los bolsillos.",
         None),
        ("Una plantilla única por mes", "Gobierno", "Media", "Baja",
         "Cada hoja tiene un formato distinto. En 2025 hay montos cargados como texto, abr-25 y may-25 tienen cifras idénticas y dic-25 se partió "
         "en dos hojas. Una tabla con fecha, concepto, rubro, monto y estado permite que este tablero se actualice solo.",
         None),
    ]
    return {"conclusiones": [c for c in conclusiones if c[1]], "ideas": ideas}


def main(entrada: str, salida: str) -> None:
    datos = json.loads(Path(entrada).read_text())
    ipc = json.loads((AQUI / "config" / "ipc.json").read_text())
    a = analizar(datos, ipc)
    tx = textos(a)
    payload = {
        "socios": datos["socios"],
        "rubros": datos["rubros"],
        "rubrosFijos": RUBROS_FIJOS,
        "meses": [{k: m.get(k) for k in ("mes", "etiqueta", "venta", "hoja", "nota", "ingreso", "saldo_anterior",
                                          "disponible", "total_gastos", "resguardo", "neto_socios", "shares", "reparto",
                                          "reintegros", "rubros", "gastos", "factor_real", "fijos", "pct_gastos",
                                          "diferidos", "solo_reparto")} for m in datos["meses"]],
        "analisis": {k: a[k] for k in ("tot", "tot12", "rub12", "l12_desde", "l12_hasta", "n_meses", "desde", "hasta",
                                        "crec_real", "real_ini", "real_fin", "fijos_ult", "tasa_var", "equilibrio",
                                        "cv12", "acum", "acum_real", "reint", "cc_mg")},
        "conclusiones": tx["conclusiones"],
        "ideas": tx["ideas"],
        "ipcNota": ipc["_fuente"],
        "ipcBase": etiqueta(ipc["base"]),
        "prospeccion": None,
    }
    opciones = json.loads((AQUI / "config" / "tablero.json").read_text()) if (AQUI / "config" / "tablero.json").exists() else {}
    ruta_p = Path(entrada).parent / "prospeccion.json"
    if ruta_p.exists():
        pa = prospeccion.analizar(json.loads(ruta_p.read_text()), tuple(opciones.get("excluir_comerciales", [])))
        payload["prospeccion"] = {**pa, **prospeccion.textos(pa)}
    ruta_c = Path(entrada).parent / "crm.json"
    if ruta_c.exists() and payload["prospeccion"]:
        ca = crm.analizar(json.loads(ruta_c.read_text()))
        payload["prospeccion"]["crm"] = {**ca, **crm.textos(ca)}
    html = (AQUI / "plantilla.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    Path(salida).parent.mkdir(parents=True, exist_ok=True)
    Path(salida).write_text(html)
    # Resumen corto para el cuerpo del mail del informe mensual.
    ult = [m for m in datos["meses"] if m.get("ingreso")][-1]
    resumen = {
        "ultimo_mes": ult["etiqueta"], "ingreso_ultimo": ult["ingreso"], "gastos_ultimo": ult["total_gastos"],
        "socios_ultimo": ult["neto_socios"], "periodo_12m": f"{a['l12_desde']} a {a['l12_hasta']}",
        "ingreso_12m": a["tot12"]["ingreso"], "gastos_12m": a["tot12"]["total_gastos"], "socios_12m": a["tot12"]["neto_socios"],
        "equilibrio": a["equilibrio"], "crec_real": a["crec_real"],
        "prospeccion": {k: payload["prospeccion"]["total"][k] for k in ("llamadas", "interesados", "cerrados", "por_cerrar")}
        if payload["prospeccion"] else None,
    }
    (Path(salida).parent / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    print(f"Tablero -> {salida}")
    print(f"  12m: ingreso {M(a['tot12']['ingreso'])}, gastos {M(a['tot12']['total_gastos'])}, socios {M(a['tot12']['neto_socios'])}")
    print(f"  equilibrio {M(a['equilibrio'])}/mes, CV {pct(a['cv12'])}, crecimiento real {pct(a['crec_real'])}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(AQUI / "datos" / "virtus_mensual.json"),
         sys.argv[2] if len(sys.argv) > 2 else str(AQUI / "salida" / "tablero_virtus.html"))
