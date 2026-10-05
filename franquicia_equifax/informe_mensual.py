"""Informe mensual en un solo comando: Excel -> tablero HTML -> PDF -> (opcional) mail.

Uso:
    python informe_mensual.py                 # genera tablero y PDF, NO envía nada
    python informe_mensual.py --enviar        # además manda el PDF por mail a los destinatarios

La configuración está en config/informe.json (copiá config/informe.ejemplo.json).
Ese archivo no se versiona: tiene rutas locales y direcciones de mail.
La contraseña del mail NUNCA va en el archivo: se toma de la variable de entorno
indicada en "smtp.variable_password" (por defecto VIRTUS_SMTP_PASSWORD).

Para correrlo solo una vez por mes:
  - Linux / Mac (cron, el día 5 a las 9:00):
        0 9 5 * * cd /ruta/a/franquicia_equifax && VIRTUS_SMTP_PASSWORD=... python3 informe_mensual.py --enviar
  - Windows: Programador de tareas -> Crear tarea básica -> Mensual -> Iniciar programa:
        python.exe  informe_mensual.py --enviar   (Iniciar en: la carpeta franquicia_equifax)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))

import exportar_pdf  # noqa: E402
import extraer_datos  # noqa: E402
import extraer_prospeccion  # noqa: E402
import generar_tablero  # noqa: E402


def M(x: float) -> str:
    return f"{x / 1e6:,.1f} M".replace(",", "X").replace(".", ",").replace("X", ".")


def cuerpo_mail(r: dict) -> str:
    lineas = [
        "Hola,",
        "",
        f"Adjunto el informe mensual de Virtus (franquicia Equifax Cuyo) con la liquidación de {r['ultimo_mes']}.",
        "",
        f"• Cobrado de Equifax en {r['ultimo_mes']}: {M(r['ingreso_ultimo'])}",
        f"• Gastos e impuestos del mes: {M(r['gastos_ultimo'])}",
        f"• Repartido a socios: {M(r['socios_ultimo'])}",
        f"• Últimos 12 meses ({r['periodo_12m']}): cobrado {M(r['ingreso_12m'])}, a socios {M(r['socios_12m'])}",
        f"• Punto de equilibrio mensual: {M(r['equilibrio'])}",
    ]
    if r.get("prospeccion"):
        p = r["prospeccion"]
        lineas.append(f"• Prospección: {p['llamadas']:.0f} llamadas, {p['interesados']:.0f} interesados, "
                      f"{p['cerrados']:.0f} altas y {p['por_cerrar']:.0f} por cerrar")
    lineas += ["", "El detalle, las conclusiones y las ideas de optimización están en el PDF adjunto.", "",
               "Informe generado automáticamente. Documento interno: no reenviar fuera de la sociedad."]
    return "\n".join(lineas)


def enviar(cfg: dict, pdf: Path, resumen: dict) -> None:
    smtp = cfg["smtp"]
    password = os.environ.get(smtp.get("variable_password", "VIRTUS_SMTP_PASSWORD"))
    if not password:
        sys.exit(f"Falta la contraseña: definí la variable de entorno {smtp.get('variable_password', 'VIRTUS_SMTP_PASSWORD')}.")
    if not cfg.get("destinatarios"):
        sys.exit("No hay destinatarios en config/informe.json.")
    msg = EmailMessage()
    msg["From"] = cfg["remitente"]
    msg["To"] = ", ".join(cfg["destinatarios"])
    if cfg.get("copia"):
        msg["Cc"] = ", ".join(cfg["copia"])
    msg["Subject"] = cfg.get("asunto", "Informe mensual Virtus · {mes}").format(mes=resumen["ultimo_mes"])
    msg.set_content(cuerpo_mail(resumen))
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                       filename=f"Informe_Virtus_{resumen['ultimo_mes']}.pdf")
    with smtplib.SMTP(smtp["host"], smtp.get("port", 587)) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(smtp.get("usuario", cfg["remitente"]), password)
        s.send_message(msg)
    print(f"Mail enviado a {msg['To']}" + (f" (cc {msg['Cc']})" if cfg.get("copia") else ""))


def main() -> None:
    ruta_cfg = AQUI / "config" / "informe.json"
    if not ruta_cfg.exists():
        sys.exit("Falta config/informe.json. Copiá config/informe.ejemplo.json y completá las rutas.")
    cfg = json.loads(ruta_cfg.read_text())
    datos = AQUI / "datos"
    salida = AQUI / "salida"

    # Si hay IDs de Drive, se bajan las planillas vivas y reemplazan a las rutas locales.
    drive = cfg.get("drive") or {}
    if any(drive.values()):
        import descargar_drive
        print("0/4 Descargando planillas de Google Drive...")
        tk = descargar_drive.token(cfg["credenciales_google"])
        if drive.get("liquidaciones"):
            descargar_drive.descargar(drive["liquidaciones"], str(datos / "drive_liquidaciones.xlsx"), tk)
            cfg["excel_liquidaciones"] = str(datos / "drive_liquidaciones.xlsx")
        if drive.get("prospeccion"):
            descargar_drive.descargar(drive["prospeccion"], str(datos / "drive_prospeccion.xlsx"), tk)
            cfg["excel_prospeccion"] = str(datos / "drive_prospeccion.xlsx")
        if drive.get("gestion_prospectos"):
            descargar_drive.descargar(drive["gestion_prospectos"], str(datos / "drive_gestion_prospectos.xlsx"), tk)
            cfg["excel_gestion_prospectos"] = str(datos / "drive_gestion_prospectos.xlsx")

    print("1/4 Leyendo liquidaciones...")
    extraer_datos.main(os.path.expanduser(cfg["excel_liquidaciones"]), str(datos / "virtus_mensual.json"))
    if cfg.get("excel_prospeccion"):
        print("2/4 Leyendo prospección...")
        extraer_prospeccion.main(os.path.expanduser(cfg["excel_prospeccion"]), str(datos / "prospeccion.json"),
                                 cfg.get("anio_prospeccion", dt.date.today().year))
    else:
        print("2/4 Sin planilla de prospección configurada.")
    if cfg.get("excel_gestion_prospectos"):
        import extraer_crm
        print("    Leyendo gestión de prospectos...")
        extraer_crm.main(os.path.expanduser(cfg["excel_gestion_prospectos"]), str(datos / "crm.json"),
                         cfg.get("anio_prospeccion", dt.date.today().year))
    print("3/4 Generando tablero y PDF...")
    html = salida / "tablero_virtus.html"
    generar_tablero.main(str(datos / "virtus_mensual.json"), str(html))
    resumen = json.loads((salida / "resumen.json").read_text())
    pdf = salida / f"Informe_Virtus_{resumen['ultimo_mes']}.pdf"
    exportar_pdf.exportar(str(html), str(pdf))
    if "--enviar" in sys.argv:
        print("4/4 Enviando por mail...")
        enviar(cfg["envio"], pdf, resumen)
    else:
        print("4/4 No se envió nada (agregá --enviar para mandar el mail). Vista previa del mail:\n")
        print(cuerpo_mail(resumen))


if __name__ == "__main__":
    main()
