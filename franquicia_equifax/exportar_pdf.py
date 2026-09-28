"""Exporta el tablero a un PDF A4 estático (portada + Finanzas + Prospección).

Uso:
    python exportar_pdf.py [salida/tablero_virtus.html] [salida/informe_virtus.pdf]

Abre el tablero en modo impresión (?pdf) con un Chromium sin ventana y lo
imprime. Requiere Playwright:
    pip install playwright && python -m playwright install chromium
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AQUI = Path(__file__).parent
ANCHO_UTIL_PX = 718  # A4 (210 mm) menos 10 mm de margen por lado, a 96 dpi

PIE = """<div style="font-size:8px;color:#898781;width:100%;padding:0 10mm;display:flex;justify-content:space-between;
font-family:system-ui,-apple-system,'Segoe UI',sans-serif"><span>Virtus · Franquicia Equifax Cuyo · Informe mensual · Uso interno</span>
<span>Página <span class="pageNumber"></span> de <span class="totalPages"></span></span></div>"""


def exportar(html: str, pdf: str) -> None:
    from playwright.sync_api import sync_playwright

    url = Path(html).resolve().as_uri() + "?pdf=1"
    with sync_playwright() as p:
        opciones = {}
        # En entornos con Chromium preinstalado (p. ej. PLAYWRIGHT_BROWSERS_PATH) se puede forzar el ejecutable.
        if os.environ.get("CHROMIUM_PATH"):
            opciones["executable_path"] = os.environ["CHROMIUM_PATH"]
        navegador = p.chromium.launch(**opciones)
        pagina = navegador.new_page(viewport={"width": ANCHO_UTIL_PX, "height": 1000})
        errores = []
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.goto(url)
        pagina.wait_for_selector("body[data-listo='1']", timeout=15000)
        pagina.emulate_media(media="screen")
        Path(pdf).parent.mkdir(parents=True, exist_ok=True)
        pagina.pdf(path=pdf, format="A4", print_background=True,
                   margin={"top": "10mm", "bottom": "14mm", "left": "10mm", "right": "10mm"},
                   display_header_footer=True, header_template="<span></span>", footer_template=PIE)
        navegador.close()
    if errores:
        raise RuntimeError("Errores en la página: " + "; ".join(errores))
    print(f"PDF -> {pdf}")


if __name__ == "__main__":
    exportar(sys.argv[1] if len(sys.argv) > 1 else str(AQUI / "salida" / "tablero_virtus.html"),
             sys.argv[2] if len(sys.argv) > 2 else str(AQUI / "salida" / "informe_virtus.pdf"))
