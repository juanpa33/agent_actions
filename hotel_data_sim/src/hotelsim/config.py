"""Configuración del simulador: hoteles sintéticos, canales, eventos y rutas.

TODO lo de este archivo es FICTICIO / ilustrativo: hoteles, tarifas, tipos de
cambio y eventos no provienen de ninguna fuente real. Sirve para ejercitar el
pipeline, no para sacar conclusiones de mercado.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("HOTELSIM_HOME", Path(__file__).resolve().parents[2] / "data"))
LANDING = ROOT / "landing"
LAKE = ROOT / "lake"
BRONZE = LAKE / "bronze"
SILVER = LAKE / "silver"
CHECKPOINTS = LAKE / "_checkpoints"
GOLD_DB = LAKE / "gold.duckdb"
STATE_FILE = ROOT / "world_state.pkl"
OUTBOX = ROOT / "outbox"
QUEUE_FILE = ROOT / "pricing_queue.json"

DEFAULT_SEED = 7
HISTORY_DAYS = 520      # historia hacia atrás (permite comparar contra "mismo día del año pasado")
FUTURE_DAYS = 180       # horizonte de estadías futuras con reservas "on the books"


def default_as_of() -> date:
    env = os.environ.get("HOTELSIM_AS_OF")
    return date.fromisoformat(env) if env else date.today()


@dataclass(frozen=True)
class Hotel:
    id: str
    name: str
    city: str
    country: str
    currency: str
    pms: str                      # sistema fuente de gestión (determina formato crudo)
    rooms: dict[str, int]         # tipo unificado -> cantidad de habitaciones
    base_usd: dict[str, float]    # tarifa base (USD) por tipo
    base_occ: float               # ocupación media objetivo
    elasticity: float             # elasticidad-precio de la demanda (verdad oculta del simulador)
    season: dict[int, float]      # factor estacional por mes
    events: list[tuple[str, int, int, int, float]] = field(default_factory=list)
    # (nombre, mes, día, duración_días, multiplicador de demanda)
    floor_usd: float = 0.0
    ceiling_usd: float = 0.0

    @property
    def total_rooms(self) -> int:
        return sum(self.rooms.values())


HOTELS: list[Hotel] = [
    Hotel(
        id="MDZ01", name="Hotel Viñedos de Luján", city="Mendoza", country="AR",
        currency="ARS", pms="opera",
        rooms={"STD": 24, "SUP": 14, "STE": 7},
        base_usd={"STD": 95.0, "SUP": 130.0, "STE": 215.0},
        base_occ=0.62, elasticity=1.6,
        season={1: 1.15, 2: 1.2, 3: 1.25, 4: 0.9, 5: 0.75, 6: 0.8, 7: 1.15, 8: 0.9,
                9: 0.95, 10: 1.05, 11: 1.0, 12: 1.1},
        events=[("Fiesta de la Vendimia (ilustrativo)", 3, 1, 4, 1.45),
                ("Receso invernal (ilustrativo)", 7, 14, 10, 1.3),
                ("Fin de semana largo octubre (ilustrativo)", 10, 10, 4, 1.25),
                ("Fin de año (ilustrativo)", 12, 26, 7, 1.35)],
        floor_usd=60.0, ceiling_usd=420.0,
    ),
    Hotel(
        id="CTG01", name="Hotel Casa Getsemaní", city="Cartagena", country="CO",
        currency="COP", pms="cloudbeds",
        rooms={"STD": 20, "SUP": 14, "STE": 6},
        base_usd={"STD": 88.0, "SUP": 120.0, "STE": 190.0},
        base_occ=0.66, elasticity=1.3,
        season={1: 1.3, 2: 1.05, 3: 1.0, 4: 1.1, 5: 0.75, 6: 1.0, 7: 1.1, 8: 0.85,
                9: 0.7, 10: 0.85, 11: 0.95, 12: 1.35},
        events=[("Año nuevo (ilustrativo)", 12, 28, 6, 1.5),
                ("Semana Santa (ilustrativo)", 4, 1, 8, 1.35),
                ("Festival de cine (ilustrativo)", 3, 12, 5, 1.2),
                ("Puente festivo noviembre (ilustrativo)", 11, 8, 4, 1.25)],
        floor_usd=55.0, ceiling_usd=380.0,
    ),
    Hotel(
        id="MEX01", name="Hotel Reforma Central", city="Ciudad de México", country="MX",
        currency="MXN", pms="mews",
        rooms={"STD": 40, "SUP": 25, "STE": 10},
        base_usd={"STD": 105.0, "SUP": 140.0, "STE": 240.0},
        base_occ=0.72, elasticity=1.1,
        season={1: 0.85, 2: 0.95, 3: 1.05, 4: 1.0, 5: 0.95, 6: 0.9, 7: 0.95, 8: 0.9,
                9: 0.95, 10: 1.2, 11: 1.15, 12: 0.9},
        events=[("Gran premio (ilustrativo)", 10, 24, 4, 1.6),
                ("Día de Muertos (ilustrativo)", 10, 31, 4, 1.35),
                ("Feria de negocios marzo (ilustrativo)", 3, 18, 3, 1.3),
                ("Congreso anual (ilustrativo)", 6, 9, 3, 1.25)],
        floor_usd=70.0, ceiling_usd=480.0,
    ),
]

HOTEL_BY_ID = {h.id: h for h in HOTELS}
ROOM_TYPES = ["STD", "SUP", "STE"]

# Moneda local por USD (valor inicial y deriva mensual) — sintético.
FX = {
    "ARS": {"start": 1250.0, "monthly_drift": 0.022, "noise": 0.004},
    "COP": {"start": 4050.0, "monthly_drift": 0.000, "noise": 0.006},
    "MXN": {"start": 18.6, "monthly_drift": 0.000, "noise": 0.005},
}

# Canales: participación, lead time medio (días), prob. de cancelación, comisión
CHANNELS = {
    "DIRECT":  dict(label="Motor propio / web", share=0.30, lead=26, cancel=0.10, commission=0.00),
    "BOOKING": dict(label="Booking.com",        share=0.38, lead=34, cancel=0.28, commission=0.15),
    "EXPEDIA": dict(label="Expedia",            share=0.10, lead=30, cancel=0.22, commission=0.16),
    "DESPEGAR": dict(label="Despegar",          share=0.14, lead=42, cancel=0.18, commission=0.14),
    "CORP":    dict(label="Corporativo",        share=0.08, lead=10, cancel=0.05, commission=0.00),
}
OTA_CHANNELS = ["BOOKING", "EXPEDIA", "DESPEGAR"]

# Códigos de habitación propios de cada sistema fuente (el cruce requiere un mapeo)
ROOM_CODES = {
    "opera":     {"STD": "DBLSTD", "SUP": "DBLSUP", "STE": "JRSTE"},
    "cloudbeds": {"STD": "Habitación Estándar", "SUP": "Habitación Superior", "STE": "Suite"},
    "mews":      {"STD": "a1f3-std", "SUP": "a1f3-sup", "STE": "a1f3-ste"},
    "cm":        {"STD": "RM-01", "SUP": "RM-02", "STE": "RM-03"},
}
CM_HOTEL_CODES = {"MDZ01": "CM-88101", "CTG01": "CM-88102", "MEX01": "CM-88103"}

# Barreras de seguridad del agente de pricing
MAX_STEP_PCT = 0.15         # cambio máximo por recomendación
MAX_PUSH_PCT = 0.20         # tope duro al publicar en canales
PARITY_TOLERANCE = 0.01
