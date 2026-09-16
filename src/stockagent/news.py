"""Recolección de eventos noticiosos con fecha verificable.

POSTURA EXPLÍCITA DE ESTE MÓDULO: no produce puntajes de sentimiento.

Un número de sentimiento generado leyendo titulares no es una medición. No tiene
unidad, no tiene error estándar, no es reproducible entre corridas y nadie puede
auditarlo. Usarlo para decidir una inversión es usar una intuición con formato
de dato.

Lo que este módulo sí hace es conseguir EVENTOS FECHADOS de fuentes oficiales, y
clasificarlos con reglas transparentes que cualquiera puede leer y refutar. El
efecto de cada tipo de evento sobre el precio lo mide después `events.py` con
retornos anormales, que sí tienen propiedades estadísticas conocidas.

Fuente primaria: SEC EDGAR. Es obligatoria, oficial, está fechada al minuto y es
gratuita. Para YPF, los formularios 6-K contienen los hechos relevantes que la
empresa reporta también a la CNV argentina.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

import requests

from .provenance import MissingDataError

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}"

USER_AGENT = "stockagent research contact@example.com"
"""SEC exige un User-Agent con contacto real y limita a 10 pedidos por segundo.
Reemplazá el correo por el tuyo: usar uno falso puede hacer que bloqueen tu IP.
Ver https://www.sec.gov/os/accessing-edgar-data"""


@dataclass
class NewsEvent:
    """Un hecho fechado y verificable. Cada campo debe poder rastrearse a su fuente."""

    event_date: date
    ticker: str
    category: str
    label: str
    source: str
    url: str
    raw_form: str = ""

    def __str__(self) -> str:
        return f"{self.event_date} [{self.category}] {self.ticker}: {self.label} <{self.url}>"


# Reglas de clasificación. Son deliberadamente simples y legibles: cualquiera
# puede verificar por qué un hecho quedó en una categoría, y discutirlo.
# Un clasificador opaco convertiría a esta etapa en una caja negra más.
_FORM_CATEGORIES: dict[str, str] = {
    "8-K": "hecho_relevante",
    "6-K": "hecho_relevante",
    "10-Q": "resultados_trimestrales",
    "10-K": "resultados_anuales",
    "20-F": "resultados_anuales",
    "S-1": "emision_capital",
    "424B2": "emision_deuda",
    "424B5": "emision_deuda",
    "SC 13D": "cambio_control_accionario",
    "SC 13G": "participacion_significativa",
    "DEF 14A": "asamblea_accionistas",
}

_KEYWORD_CATEGORIES: tuple[tuple[str, str], ...] = (
    (r"\b(earnings|results|resultados|quarter|trimestr)\b", "resultados_trimestrales"),
    (r"\b(guidance|outlook|proyecc)\b", "revision_guidance"),
    (r"\b(dividend|dividendo|buyback|recompra)\b", "retorno_al_accionista"),
    (r"\b(notes|bond|tender offer|obligaciones negociables|deuda)\b", "financiamiento"),
    (r"\b(acquisition|merger|adquisic|fusion)\b", "fusiones_adquisiciones"),
    (r"\b(litigation|lawsuit|juicio|demanda|ruling|fallo)\b", "litigio"),
    (r"\b(export control|sanction|tariff|arancel|restricc)\b", "regulatorio_comercial"),
    (r"\b(ceo|cfo|board|director|renunci|resign)\b", "cambio_directivo"),
)


def classify(form: str, title: str = "") -> str:
    """Asigna una categoría según el tipo de formulario y, si no alcanza, el título."""
    form_clean = form.strip().upper()
    if form_clean in _FORM_CATEGORIES:
        base = _FORM_CATEGORIES[form_clean]
        if base == "hecho_relevante" and title:
            for pattern, category in _KEYWORD_CATEGORIES:
                if re.search(pattern, title, flags=re.IGNORECASE):
                    return category
        return base

    for pattern, category in _KEYWORD_CATEGORIES:
        if re.search(pattern, f"{form} {title}", flags=re.IGNORECASE):
            return category
    return "sin_clasificar"


def resolve_cik(ticker: str, timeout: int = 30) -> int:
    """Obtiene el CIK de un ticker desde el índice oficial de la SEC.

    Se resuelve contra la fuente en lugar de mantener una tabla local, para que
    el código no dependa de un identificador transcripto a mano que puede estar
    mal o quedar desactualizado.
    """
    response = requests.get(_TICKER_MAP_URL, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    mapping = response.json()

    target = ticker.upper().split(".")[0]
    for entry in mapping.values():
        if entry.get("ticker", "").upper() == target:
            return int(entry["cik_str"])

    raise MissingDataError(
        f"No se encontró el CIK de '{ticker}' en el índice de la SEC. "
        "Los emisores que no cotizan en EE.UU. no tienen CIK; para esos casos "
        "hay que usar la fuente regulatoria local (CNV en Argentina)."
    )


def fetch_sec_filings(ticker: str, since: date, forms: tuple[str, ...] = ("8-K", "6-K"),
                      timeout: int = 30) -> list[NewsEvent]:
    """Descarga presentaciones ante la SEC posteriores a `since`.

    Los formularios 8-K (emisores de EE.UU.) y 6-K (emisores extranjeros, como
    YPF) son el canal por el que las empresas están obligadas a comunicar hechos
    relevantes. Su fecha es exacta, lo que es un requisito imprescindible del
    estudio de eventos: un evento mal fechado por un día destruye la medición.
    """
    cik = resolve_cik(ticker, timeout=timeout)
    response = requests.get(
        _SUBMISSIONS_URL.format(cik=cik), timeout=timeout, headers={"User-Agent": USER_AGENT}
    )
    response.raise_for_status()
    payload = response.json()

    recent = payload.get("filings", {}).get("recent", {})
    if not recent:
        raise MissingDataError(f"EDGAR no devolvió presentaciones para {ticker} (CIK {cik}).")

    events: list[NewsEvent] = []
    for form, filing_date, accession, document, items in zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
        recent.get("items", [""] * len(recent.get("form", []))),
    ):
        if form not in forms:
            continue
        parsed = datetime.strptime(filing_date, "%Y-%m-%d").date()
        if parsed < since:
            continue

        url = _FILING_URL.format(
            cik=cik, accession_nodash=accession.replace("-", ""), document=document
        )
        events.append(
            NewsEvent(
                event_date=parsed,
                ticker=ticker,
                category=classify(form, items),
                label=f"{form} {items}".strip(),
                source="SEC EDGAR",
                url=url,
                raw_form=form,
            )
        )

    return sorted(events, key=lambda e: e.event_date)


def load_manual_events(path: str) -> list[NewsEvent]:
    """Carga eventos curados a mano desde un JSON.

    Sirve para hechos que no llegan a EDGAR: medidas macroeconómicas
    argentinas, decisiones del BCRA, controles de exportación de semiconductores.

    Cada registro EXIGE una URL: un evento sin fuente verificable no se carga.
    Formato:
      [{"date": "2026-08-04", "ticker": "YPFD.BA", "category": "split",
        "label": "Split 10:1 efectivo en BYMA", "url": "https://..."}]
    """
    with open(path, encoding="utf-8") as fh:
        records = json.load(fh)

    events: list[NewsEvent] = []
    for i, record in enumerate(records):
        missing = [k for k in ("date", "ticker", "category", "label", "url") if not record.get(k)]
        if missing:
            raise MissingDataError(
                f"El evento #{i + 1} de {path} no tiene {missing}. "
                "Todo evento requiere fuente verificable: sin URL no se carga."
            )
        events.append(
            NewsEvent(
                event_date=datetime.strptime(record["date"], "%Y-%m-%d").date(),
                ticker=record["ticker"],
                category=record["category"],
                label=record["label"],
                source=record.get("source", "curado manualmente"),
                url=record["url"],
            )
        )
    return sorted(events, key=lambda e: e.event_date)


def sentiment_score(*args, **kwargs):  # noqa: D401
    """No implementado, a propósito.

    Si necesitás incorporar el contenido de las noticias y no solo su ocurrencia,
    el camino defendible es: definir categorías antes de mirar los precios,
    clasificar con reglas auditables, y medir el efecto de cada categoría con
    `events.aggregate_by_category`. Así la hipótesis se formula antes que el
    resultado, que es lo que distingue una prueba de una racionalización.
    """
    raise NotImplementedError(
        "Este proyecto no genera puntajes de sentimiento. Un número inventado "
        "leyendo titulares no es un dato y no puede sustentar una decisión de "
        "inversión. Usá el estudio de eventos de events.py."
    )
