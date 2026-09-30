"""Renderiza el mundo sintético como archivos crudos de "sistemas fuente" en la zona de aterrizaje.

Cada sistema tiene su propio formato, códigos, moneda y zona horaria/relojes, como
pasa en la realidad. Los formatos son IMITACIONES genéricas inspiradas en el estilo de
cada tipo de sistema (PMS tipo Opera / tipo Cloudbeds / tipo Mews, channel manager,
rate shopper): NO son los esquemas reales de esos productos. Para un cliente real, se
reemplazan los adaptadores de `silver.py` por los del esquema oficial de cada API.

Suciedad inyectada a propósito (con semilla fija): eventos duplicados por reenvío,
líneas malformadas, importes negativos, referencias de OTA ausentes en el PMS,
latencia PMS vs channel manager y reservas que aún no llegaron al PMS.
"""
from __future__ import annotations

import csv
import io
import json
import zlib
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config as C
from .generator import Booking, World, fx_rate, round_local

OPERA_SOURCE = {"DIRECT": "WEB", "BOOKING": "BKG", "EXPEDIA": "EXP", "DESPEGAR": "DSP", "CORP": "COR"}
MEWS_ORIGIN = {"DIRECT": "Booking engine", "BOOKING": "Booking.com", "EXPEDIA": "Expedia",
               "DESPEGAR": "Despegar", "CORP": "Corporate"}
CLOUDBEDS_SOURCE = {"DIRECT": "Website", "BOOKING": "Booking.com", "EXPEDIA": "Expedia",
                    "DESPEGAR": "Despegar", "CORP": "Corporate"}
PMS_COLUMNS_CLOUDBEDS = ["Event", "Event Time", "Reservation Number", "Booking DateTime", "Check-In", "Check-Out",
                         "Room Type", "Grand Total", "Currency", "Status", "Source",
                         "Third Party Confirmation Number", "Guest Name", "Adults"]


def _u(*parts) -> float:
    """Número pseudoaleatorio determinístico en [0,1) a partir de claves (estable entre procesos)."""
    return (zlib.crc32("|".join(map(str, parts)).encode()) & 0xFFFFFF) / 0x1000000


def _emit_ts(b: Booking, ts: datetime, kind: str, target: str) -> datetime | None:
    """Momento en que el evento llega al sistema `target`; None = nunca llega (aún)."""
    if target == "cm":
        return ts + timedelta(seconds=int(_u(b.id, kind, "cm") * 120))
    if b.channel in C.OTA_CHANNELS:           # las OTAs entran por el channel manager y bajan al PMS
        if _u(b.id, kind, "lost") < 0.01:
            return None
        if _u(b.id, kind, "slow") < 0.02:
            return ts + timedelta(days=1 + _u(b.id, kind, "d") * 2)
        return ts + timedelta(minutes=5 + _u(b.id, kind, "lat") * 35)
    return ts                                   # directo/corporativo nacen en el PMS


def _pms_total_local(b: Booking, h: C.Hotel) -> float:
    return round_local(h.currency, b.total_usd * fx_rate(h.currency, b.booked_at.date()))


def _ext_ref(b: Booking) -> str | None:
    if b.ota_ref is None or _u(b.id, "noref") < 0.08:
        return None
    return b.ota_ref


def _neg(b: Booking, kind: str) -> float:
    return -1.0 if _u(b.id, kind, "neg") < 0.001 else 1.0


def pms_record(b: Booking, kind: str, ts: datetime) -> tuple[str, dict | list]:
    h = C.HOTEL_BY_ID[b.hotel]
    total = _pms_total_local(b, h) * _neg(b, kind)
    native_id = f"{h.id}-{b.id:07d}"
    checkout = b.checkin + timedelta(days=b.nights)
    ref = _ext_ref(b)
    cancelled = kind == "cancelled"
    if h.pms == "opera":
        prefix = OPERA_SOURCE[b.channel]
        return "pms_opera", {
            "eventType": "RESERVATION_CANCELLED" if cancelled else "RESERVATION_CREATED",
            "eventTimestamp": ts.isoformat(timespec="seconds"), "hotelId": h.id,
            "reservation": {
                "resvNameId": native_id, "arrival": b.checkin.isoformat(), "departure": checkout.isoformat(),
                "roomCategory": C.ROOM_CODES["opera"][b.room], "totalAmount": total, "currencyCode": h.currency,
                "resvStatus": "CANCELLED" if cancelled else "RESERVED", "sourceCode": prefix,
                "externalReference": f"{prefix}-{ref}" if ref else None,
                "createdAt": b.booked_at.isoformat(timespec="seconds"),
                "guestName": b.guest, "adults": b.adults,
            }}
    if h.pms == "cloudbeds":
        fmt = "%d/%m/%Y %H:%M"
        return "pms_cloudbeds", {
            "Event": "canceled" if cancelled else "created", "Event Time": ts.strftime(fmt),
            "Reservation Number": native_id, "Booking DateTime": b.booked_at.strftime(fmt),
            "Check-In": b.checkin.strftime("%d/%m/%Y"), "Check-Out": checkout.strftime("%d/%m/%Y"),
            "Room Type": C.ROOM_CODES["cloudbeds"][b.room], "Grand Total": f"{total:.2f}".replace(".", ","),
            "Currency": h.currency, "Status": "canceled" if cancelled else "confirmed",
            "Source": CLOUDBEDS_SOURCE[b.channel], "Third Party Confirmation Number": ref or "",
            "Guest Name": b.guest, "Adults": b.adults,
        }
    return "pms_mews", {   # mews
        "Event": {"Type": "ReservationCanceled" if cancelled else "ReservationCreated",
                  "TimeUtc": (ts + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "Reservation": {
            "Id": native_id, "StartUtc": f"{b.checkin.isoformat()}T18:00:00Z", "EndUtc": f"{checkout.isoformat()}T15:00:00Z",
            "CreatedUtc": (b.booked_at + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "RequestedResourceCategoryId": C.ROOM_CODES["mews"][b.room],
            "TotalAmount": {"Currency": h.currency, "GrossValue": total},
            "State": "Canceled" if cancelled else "Confirmed", "Origin": MEWS_ORIGIN[b.channel],
            "ChannelNumber": ref, "Customer": {"LastName": b.guest.split(", ")[0], "FirstName": b.guest.split(", ")[1]},
            "AdultCount": b.adults,
        }}


def cm_record(b: Booking, kind: str, ts: datetime) -> dict:
    h = C.HOTEL_BY_ID[b.hotel]
    if b.channel == "DESPEGAR":
        gross, cur = round_local(h.currency, b.total_usd * fx_rate(h.currency, b.booked_at.date())), h.currency
    else:
        gross, cur = b.total_usd, "USD"
    return {
        "msgId": f"M{b.id:08d}-{kind[0]}", "receivedAt": ts.isoformat(timespec="seconds"),
        "messageType": "CANCEL" if kind == "cancelled" else "NEW", "channel": b.channel,
        "channelResId": b.ota_ref, "hotelCode": C.CM_HOTEL_CODES[b.hotel], "roomCode": C.ROOM_CODES["cm"][b.room],
        "checkIn": b.checkin.isoformat(), "checkOut": (b.checkin + timedelta(days=b.nights)).isoformat(),
        "grossTotal": gross * _neg(b, kind + "cm"), "currency": cur,
        "commissionPct": C.CHANNELS[b.channel]["commission"] * 100, "bookedAt": b.booked_at.isoformat(timespec="seconds"),
        "guest": {"name": b.guest, "country": b.guest_country}, "adults": b.adults,
    }


def collect_records(world: World, a: datetime, b: datetime) -> list[dict]:
    """Registros que LLEGAN a cada sistema en [a, b) (considera la latencia de emisión)."""
    out: list[dict] = []
    lookback = a - timedelta(days=4)
    for ts, kind, bk in (e for e in ((t, k, world.bookings[i]) for t, k, i in world.events) if lookback <= e[0] < b):
        targets = ["pms"] + (["cm"] if bk.channel in C.OTA_CHANNELS else [])
        for target in targets:
            emit = _emit_ts(bk, ts, kind, target)
            if emit is None or not (a <= emit < b):
                continue
            if target == "cm":
                out.append(dict(source="cm_reservations", hotel=None, emit=emit, payload=cm_record(bk, kind, emit)))
            else:
                src, payload = pms_record(bk, kind, emit)
                out.append(dict(source=src, hotel=bk.hotel, emit=emit, payload=payload))
            if _u(bk.id, kind, target, "dup") < 0.01:    # reenvío duplicado
                out.append(dict(out[-1], emit=emit))
    return out


def _file_key(emit: datetime, cutoff_daily: datetime, live_tag: str | None) -> str:
    if live_tag:
        return f"live_{live_tag}"
    return emit.strftime("%Y%m%d") if emit >= cutoff_daily else emit.strftime("%Y%m")


def _write(path: Path, source: str, payloads: list[dict], seed_key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if source == "pms_cloudbeds":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(PMS_COLUMNS_CLOUDBEDS)
        for i, p in enumerate(payloads):
            row = [p[c] for c in PMS_COLUMNS_CLOUDBEDS]
            if _u(seed_key, i, "bad") < 0.003:
                row = row[:5]                       # fila truncada
            w.writerow(row)
        path.write_text(buf.getvalue(), encoding="utf-8")
        return
    lines = []
    for i, p in enumerate(payloads):
        s = json.dumps(p, ensure_ascii=False)
        if _u(seed_key, i, "bad") < 0.003:
            s = s[: len(s) // 2]                    # línea malformada
        lines.append(s)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reservation_files(world: World, a: datetime, b: datetime, live_tag: str | None = None) -> int:
    records = collect_records(world, a, b)
    cutoff = b - timedelta(days=14)
    groups: dict[tuple[str, str | None, str], list[dict]] = defaultdict(list)
    for r in records:
        groups[(r["source"], r["hotel"], _file_key(r["emit"], cutoff, live_tag))].append(r)
    for (source, hotel, key), items in groups.items():
        items.sort(key=lambda r: r["emit"])
        folder = C.LANDING / source / (hotel or "all")
        ext = "csv" if source == "pms_cloudbeds" else "jsonl"
        _write(folder / f"{key}.{ext}", source, [r["payload"] for r in items], f"{source}{hotel}{key}")
    return len(records)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def write_snapshots(world: World, ts: datetime, tag: str | None = None, shop_days_back: int = 0) -> None:
    """ARI del channel manager, rate shopper y (una vez) maestros: eventos, FX y POS."""
    stamp = tag or ts.strftime("%Y%m%d_%H%M")
    _write_csv(C.LANDING / "cm_ari" / f"ari_{stamp}.csv", world.ari_rows(ts))
    for k in range(shop_days_back + 1):
        d = ts.date() - timedelta(days=k)
        _write_csv(C.LANDING / "rate_shopper" / f"shop_{d.strftime('%Y%m%d')}.csv", world.comp_rows(d))


def write_reference(world: World) -> None:
    p = C.LANDING / "events_calendar"
    p.mkdir(parents=True, exist_ok=True)
    (p / "events.json").write_text(json.dumps(world.events_calendar(), ensure_ascii=False, indent=1), encoding="utf-8")
    d = world.window_start - timedelta(days=260)   # cubre reservas creadas durante el calentamiento
    end = world.as_of + timedelta(days=C.FUTURE_DAYS)
    months = sorted({(x.year, x.month) for x in (d + timedelta(days=i) for i in range((end - d).days + 1))})
    for y, m in months:
        a = date(y, m, 1)
        b = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1))
        _write_csv(C.LANDING / "fx" / f"fx_{y}{m:02d}.csv", world.fx_rows(max(a, d), min(b, end)))
    # POS: solo hasta hoy (los días futuros aún no facturaron)
    for y, m in months:
        a = date(y, m, 1)
        b = min(date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1), world.as_of - timedelta(days=1))
        if a <= b and b >= world.window_start:
            _write_csv(C.LANDING / "pos" / f"pos_{y}{m:02d}.csv", world.pos_rows(max(a, world.window_start), b))


def write_pos_day(world: World, d: date, tag: str) -> None:
    _write_csv(C.LANDING / "pos" / f"pos_live_{tag}.csv", world.pos_rows(d, d))


def write_history(world: World) -> int:
    start = datetime.combine(world.window_start - timedelta(days=250), datetime.min.time())
    n = write_reservation_files(world, start, world.now)
    write_snapshots(world, world.now, tag=world.now.strftime("%Y%m%d_%H%M"), shop_days_back=14)
    write_reference(world)
    return n
