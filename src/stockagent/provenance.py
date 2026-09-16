"""Trazabilidad de datos.

Regla central del proyecto: ninguna serie numérica puede circular por el
pipeline sin un registro de procedencia que diga de dónde salió, cuándo se
descargó y qué integridad tiene. Si un dato no tiene procedencia, no entra.

Esto no es burocracia: es la única defensa mecánica contra que un número
inventado o estimado se mezcle con datos de mercado reales.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import pandas as pd


class DataKind(str, Enum):
    """Naturaleza del dato. Determina si puede usarse para decidir dinero real."""

    OBSERVED = "observed"
    """Medición directa publicada por una fuente identificable (precio de cierre
    de un mercado, índice publicado por un organismo oficial). Es el único tipo
    admisible como insumo de una señal de inversión."""

    DERIVED = "derived"
    """Calculado de forma determinística a partir de datos OBSERVED mediante una
    fórmula explícita (retornos, medias móviles, CCL implícito). Trazable hasta
    los observados que lo originaron."""

    SYNTHETIC = "synthetic"
    """Generado artificialmente para tests. NUNCA puede llegar a un reporte:
    `assert_report_safe()` aborta el proceso si lo detecta."""


@dataclass(frozen=True)
class Provenance:
    """Partida de nacimiento de una serie de datos."""

    kind: DataKind
    source_id: str
    """Identificador estable de la fuente, p.ej. 'yahoo:NVDA' o 'indec:ipc_nivel_general'."""

    source_url: str
    """URL exacta consultada. Vacío solo para datos DERIVED."""

    retrieved_at: datetime
    """Momento de la descarga, en UTC."""

    rows: int
    first_obs: str | None = None
    last_obs: str | None = None
    content_sha256: str | None = None
    """Hash del contenido, para detectar que una fuente reescribió el pasado."""

    parents: tuple[str, ...] = ()
    """source_id de las series de las que deriva este dato."""

    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


@dataclass
class TracedSeries:
    """Una serie de pandas junto con su procedencia. El par es inseparable."""

    data: pd.Series | pd.DataFrame
    provenance: Provenance
    _lineage: list[Provenance] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self._lineage:
            self._lineage = [self.provenance]

    @property
    def lineage(self) -> list[Provenance]:
        """Cadena completa de procedencia, incluyendo la de los insumos."""
        return list(self._lineage)

    def derive(
        self,
        new_data: pd.Series | pd.DataFrame,
        operation: str,
        extra_parents: "list[TracedSeries] | None" = None,
        notes: str = "",
    ) -> "TracedSeries":
        """Produce una serie derivada heredando la procedencia.

        `operation` debe describir la transformación de forma que un tercero
        pueda reproducirla, p.ej. 'log_returns' o 'ccl = p_ars * ratio / p_usd'.
        """
        parents = [self]
        if extra_parents:
            parents.extend(extra_parents)

        # Una derivación de datos sintéticos sigue siendo sintética. La
        # contaminación se propaga hacia adelante a propósito, para que
        # ningún cálculo intermedio pueda "lavar" el origen de un dato.
        kinds = {p.provenance.kind for p in parents}
        kind = DataKind.SYNTHETIC if DataKind.SYNTHETIC in kinds else DataKind.DERIVED

        prov = Provenance(
            kind=kind,
            source_id=f"derived:{operation}",
            source_url="",
            retrieved_at=datetime.now(timezone.utc),
            rows=len(new_data),
            first_obs=_fmt_index(new_data, 0),
            last_obs=_fmt_index(new_data, -1),
            parents=tuple(p.provenance.source_id for p in parents),
            notes=notes or operation,
        )

        merged: list[Provenance] = []
        for p in parents:
            for item in p.lineage:
                if item not in merged:
                    merged.append(item)
        merged.append(prov)

        return TracedSeries(data=new_data, provenance=prov, _lineage=merged)

    def assert_report_safe(self) -> None:
        """Aborta si algún ancestro es sintético.

        Se invoca antes de escribir cualquier reporte. Es la barrera que impide
        que un dato de test se presente como dato de mercado.
        """
        contaminated = [p for p in self.lineage if p.kind is DataKind.SYNTHETIC]
        if contaminated:
            ids = ", ".join(p.source_id for p in contaminated)
            raise ContaminatedDataError(
                f"Se intentó reportar una serie con ancestros SINTÉTICOS: {ids}. "
                "Los datos sintéticos existen solo para tests y no pueden "
                "presentarse como información de mercado."
            )

    def lineage_report(self) -> str:
        lines = ["Cadena de procedencia:"]
        for i, p in enumerate(self.lineage, 1):
            lines.append(
                f"  {i}. [{p.kind.value}] {p.source_id}"
                f" | filas={p.rows}"
                f" | rango={p.first_obs}..{p.last_obs}"
                f" | descargado={p.retrieved_at:%Y-%m-%d %H:%M:%S}Z"
            )
            if p.source_url:
                lines.append(f"     url: {p.source_url}")
            if p.notes:
                lines.append(f"     nota: {p.notes}")
        return "\n".join(lines)


class ContaminatedDataError(RuntimeError):
    """Se intentó usar datos sintéticos como si fueran reales."""


class MissingDataError(RuntimeError):
    """Falta un dato requerido.

    Se lanza en lugar de rellenar, interpolar o estimar. Un pipeline que falla
    ruidosamente es preferible a uno que entrega un número plausible e incorrecto.
    """


def _fmt_index(obj: pd.Series | pd.DataFrame, pos: int) -> str | None:
    if len(obj) == 0:
        return None
    value = obj.index[pos]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return str(value)


def sha256_of(payload: str | bytes) -> str:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def observed(
    data: pd.Series | pd.DataFrame,
    source_id: str,
    source_url: str,
    raw_payload: str | bytes | None = None,
    notes: str = "",
) -> TracedSeries:
    """Construye una serie OBSERVED. Solo deben llamarlo los módulos de descarga."""
    prov = Provenance(
        kind=DataKind.OBSERVED,
        source_id=source_id,
        source_url=source_url,
        retrieved_at=datetime.now(timezone.utc),
        rows=len(data),
        first_obs=_fmt_index(data, 0),
        last_obs=_fmt_index(data, -1),
        content_sha256=sha256_of(raw_payload) if raw_payload is not None else None,
        notes=notes,
    )
    return TracedSeries(data=data, provenance=prov)


def synthetic(data: pd.Series | pd.DataFrame, source_id: str, notes: str = "") -> TracedSeries:
    """Construye una serie SINTÉTICA, marcada de forma indeleble. Solo para tests."""
    prov = Provenance(
        kind=DataKind.SYNTHETIC,
        source_id=f"SYNTHETIC:{source_id}",
        source_url="",
        retrieved_at=datetime.now(timezone.utc),
        rows=len(data),
        first_obs=_fmt_index(data, 0),
        last_obs=_fmt_index(data, -1),
        notes=notes or "Dato artificial de test. Prohibido su uso en reportes.",
    )
    return TracedSeries(data=data, provenance=prov)


def dump_lineage(series_map: dict[str, TracedSeries], path: str) -> None:
    """Persiste la procedencia de todas las series de una corrida, para auditoría."""
    payload = {
        name: [p.to_dict() for p in ts.lineage] for name, ts in series_map.items()
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
