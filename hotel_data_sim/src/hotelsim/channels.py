"""Cola de aprobación y conector simulado de canales (Booking, Expedia, Despegar, motor propio).

Flujo de seguridad (human-in-the-loop):

    agente PROPONE  →  cola (estado "propuesto")  →  PERSONA aprueba  →  conector publica

El agente de IA solo tiene la herramienta de proponer. `approve()` la ejecuta una persona
(CLI o botón del tablero). Además del control humano hay validaciones duras en `propose`
y se re-validan en `approve`: hotel y fecha válidos, piso/techo del hotel y cambio máximo
(`MAX_PUSH_PCT`). Todo queda en un registro de auditoría append-only.

El conector es un SIMULADOR: escribe en `data/outbox/` un payload de estilo OTA. La
integración real con Booking.com requiere ser Connectivity Partner certificado y usar su
Rates & Availability API (ver docs/FUENTES.md); ese código reemplaza a `MockOTAConnector`.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

from . import config as C
from .generator import World, fx_rate, round_local
from .ingest import get_clock

PRICE_CHANNELS = ["DIRECT", "BOOKING", "EXPEDIA", "DESPEGAR"]   # misma BAR en todos: paridad


class ValidationError(ValueError):
    pass


def _load() -> list[dict]:
    return json.loads(C.QUEUE_FILE.read_text()) if C.QUEUE_FILE.exists() else []


def _save(q: list[dict]) -> None:
    C.ROOT.mkdir(parents=True, exist_ok=True)
    C.QUEUE_FILE.write_text(json.dumps(q, ensure_ascii=False, indent=1, default=str))


def _audit(event: str, **data) -> None:
    C.OUTBOX.mkdir(parents=True, exist_ok=True)
    with open(C.OUTBOX / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(ts=datetime.now().isoformat(timespec="seconds"), event=event, **data),
                           ensure_ascii=False, default=str) + "\n")


def validate_change(ch: dict) -> None:
    h = C.HOTEL_BY_ID.get(ch.get("hotel_id"))
    if h is None:
        raise ValidationError(f"hotel desconocido: {ch.get('hotel_id')}")
    room = ch.get("room_type")
    if room not in h.rooms:
        raise ValidationError(f"tipo de habitación inválido para {h.id}: {room}")
    today = get_clock().date()
    d = date.fromisoformat(str(ch["stay_date"])[:10])
    if not (today <= d <= today + timedelta(days=C.FUTURE_DAYS)):
        raise ValidationError(f"fecha fuera de horizonte: {d}")
    cur, new = float(ch["current_usd"]), float(ch["new_usd"])
    ratio = h.base_usd[room] / h.base_usd["STD"]
    lo, hi = h.floor_usd * ratio, h.ceiling_usd * ratio
    if not (lo <= new <= hi):
        raise ValidationError(f"precio ${new:.0f} fuera de piso/techo del hotel (${lo:.0f}–${hi:.0f})")
    if cur > 0 and abs(new / cur - 1) > C.MAX_PUSH_PCT:
        raise ValidationError(f"cambio {new / cur - 1:+.0%} supera el máximo permitido ±{C.MAX_PUSH_PCT:.0%}")


def propose(changes: list[dict], proposed_by: str = "agente") -> dict:
    """Agrega propuestas a la cola. Devuelve {'accepted': [...], 'rejected': [{'change','error'}]}."""
    queue = _load()
    accepted, rejected = [], []
    for ch in changes:
        try:
            validate_change(ch)
        except (ValidationError, KeyError, ValueError) as e:
            rejected.append(dict(change=ch, error=str(e)))
            continue
        key = (ch["hotel_id"], ch["room_type"], str(ch["stay_date"])[:10])
        for old in queue:   # una sola propuesta vigente por clave
            if old["status"] == "propuesto" and (old["hotel_id"], old["room_type"], old["stay_date"]) == key:
                old["status"] = "reemplazado"
        entry = dict(id=uuid.uuid4().hex[:8], status="propuesto", hotel_id=ch["hotel_id"], room_type=ch["room_type"],
                     stay_date=key[2], current_usd=float(ch["current_usd"]), new_usd=float(ch["new_usd"]),
                     reasons=ch.get("reasons", []), proposed_by=proposed_by,
                     proposed_at=get_clock().isoformat(timespec="seconds"))
        queue.append(entry)
        accepted.append(entry)
    _save(queue)
    _audit("propose", by=proposed_by, accepted=[e["id"] for e in accepted], rejected=len(rejected))
    return dict(accepted=accepted, rejected=rejected)


def list_queue(status: str | None = "propuesto") -> list[dict]:
    q = _load()
    return [e for e in q if status is None or e["status"] == status]


def reject(ids: list[str], by: str) -> int:
    q, n = _load(), 0
    for e in q:
        if e["id"] in ids and e["status"] == "propuesto":
            e.update(status="rechazado", decided_by=by)
            n += 1
    _save(q)
    _audit("reject", by=by, ids=ids)
    return n


class MockOTAConnector:
    """Simula el envío de tarifas a cada canal. Payload ilustrativo de estilo OTA (no es el esquema real)."""

    def __init__(self, channel: str):
        self.channel = channel

    def push_rates(self, hotel_id: str, changes: list[dict], world: World | None) -> dict:
        h = C.HOTEL_BY_ID[hotel_id]
        fx = fx_rate(h.currency, get_clock().date())
        items = [dict(roomCode=C.ROOM_CODES["cm"][c["room_type"]], stayDate=c["stay_date"],
                      amount=round_local(h.currency, c["new_usd"] * fx), currency=h.currency) for c in changes]
        payload = dict(connector="mock", channel=self.channel, hotelCode=C.CM_HOTEL_CODES[hotel_id],
                       sentAt=get_clock().isoformat(timespec="seconds"), rates=items)
        C.OUTBOX.mkdir(parents=True, exist_ok=True)
        f = C.OUTBOX / f"{get_clock():%Y%m%d%H%M%S}_{self.channel}_{hotel_id}_{uuid.uuid4().hex[:4]}.json"
        f.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
        return dict(channel=self.channel, status="ok", items=len(items), file=f.name)


def approve(ids: list[str], approved_by: str) -> dict:
    """Aprobación HUMANA: publica en todos los canales (misma tarifa → paridad) y deja auditoría."""
    if not approved_by or approved_by.strip().lower() in {"agente", "agent", "claude", "ia", "ai"}:
        raise ValidationError("la aprobación debe venir de una persona identificada")
    q = _load()
    chosen = [e for e in q if e["id"] in ids and e["status"] == "propuesto"]
    results, failed = [], []
    by_hotel: dict[str, list[dict]] = {}
    for e in chosen:
        try:
            validate_change(dict(e, current_usd=e["current_usd"], new_usd=e["new_usd"]))
            by_hotel.setdefault(e["hotel_id"], []).append(e)
        except ValidationError as err:
            e.update(status="falló", error=str(err))
            failed.append(dict(id=e["id"], error=str(err)))
    world = World.load() if C.STATE_FILE.exists() else None
    for hotel_id, items in by_hotel.items():
        for ch in PRICE_CHANNELS:
            results.append(dict(hotel_id=hotel_id, **MockOTAConnector(ch).push_rates(hotel_id, items, world)))
        for e in items:
            e.update(status="publicado", decided_by=approved_by, pushed_at=get_clock().isoformat(timespec="seconds"))
            if world is not None:
                world.set_override(hotel_id, e["room_type"], date.fromisoformat(e["stay_date"]), e["new_usd"])
    if world is not None and by_hotel:
        from . import sources
        sources.write_snapshots(world, world.now, tag=f"push_{world.now:%Y%m%d%H%M%S}")
        world.save()
    _save(q)
    _audit("approve", by=approved_by, ids=[e["id"] for e in chosen], pushed=len(results), failed=failed)
    return dict(published=[e["id"] for e in chosen if e["status"] == "publicado"], failed=failed, pushes=results)
