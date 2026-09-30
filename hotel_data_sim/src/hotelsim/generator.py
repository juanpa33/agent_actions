"""Mundo sintético: demanda, precios, reservas, cancelaciones y telemetría de fuentes.

El mundo se simula por pasos de tiempo (1 día en la historia, minutos en modo
"vivo"). En cada paso, para cada fecha de estadía futura, la cantidad esperada de
reservas nuevas es:

    llegadas_totales(fecha, precio) × P(lead time cae dentro del paso)

donde `llegadas_totales` depende de temporada, día de la semana, eventos, un shock
latente por fecha y la **elasticidad-precio** frente a la tarifa publicada (BAR).
Por eso cambiar un precio (p. ej. aprobado por el agente) cambia las reservas
futuras: hay un circuito cerrado para probar el agente.

La política de precios "histórica" es deliberadamente ingenua (solo temporada y día
de semana, ignora eventos): deja ingresos sobre la mesa que un buen revenue
management puede capturar.
"""
from __future__ import annotations

import heapq
import math
import pickle
import zlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

import numpy as np

from . import config as C
from .config import Hotel

ROOM_DEMAND_FACTOR = {"STD": 1.0, "SUP": 0.92, "STE": 0.8}
LEISURE_DOW = [0.75, 0.75, 0.8, 0.9, 1.2, 1.3, 0.9]    # lunes..domingo
BUSINESS_DOW = [1.05, 1.2, 1.2, 1.1, 0.85, 0.65, 0.7]
BUSINESS_HOTELS = {"MEX01"}
LOOKAHEAD_DAYS = 240
FIRST_NAMES = ["Ana", "Luis", "María", "Juan", "Sofía", "Carlos", "Lucía", "Diego", "Valentina", "Mateo",
               "Camila", "Andrés", "Paula", "Martín", "Laura", "Javier", "Julia", "Pablo", "Emma", "Tomás"]
LAST_NAMES = ["García", "Rodríguez", "Martínez", "López", "González", "Pérez", "Sánchez", "Romero", "Torres",
              "Díaz", "Ramírez", "Flores", "Acosta", "Benítez", "Castro", "Herrera", "Molina", "Silva", "Ortiz", "Vega"]
GUEST_COUNTRIES = {
    "BOOKING": ["AR", "BR", "US", "ES", "CL", "CO", "MX", "UY", "DE"],
    "EXPEDIA": ["US", "CA", "AR", "MX", "BR", "GB"],
    "DESPEGAR": ["AR", "CO", "MX", "CL", "PE", "UY"],
    "DIRECT": ["AR", "CO", "MX", "CL", "US", "BR"],
    "CORP": ["AR", "CO", "MX"],
}
COMPETITORS = {
    "MDZ01": ["Bodega Hotel Cordillera", "Posada del Malbec", "Hotel Plaza Andina", "Resort Uco Valley"],
    "CTG01": ["Casa Murallas", "Hotel Bahía Vieja", "Boutique Caribe", "Palacio Colonial"],
    "MEX01": ["Hotel Alameda", "Torre Polanco", "Casa Roma Suites", "Hotel Zócalo Grand"],
}
COMP_OFFSET = [0.92, 1.0, 1.08, 1.17]


def _cdf_gamma2(x: np.ndarray, theta: float) -> np.ndarray:
    """CDF de una gamma de forma 2 (lead times con cola larga)."""
    z = np.maximum(x, 0.0) / theta
    return 1.0 - np.exp(-z) * (1.0 + z)


def daterange(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def fx_rate(currency: str, d: date) -> float:
    """Unidades de moneda local por USD (sintético, con deriva y ruido suave)."""
    p = C.FX[currency]
    months = (d.year - 2025) * 12 + d.month - 1 + d.day / 30.0
    smooth = 1.0 + p["noise"] * math.sin(d.toordinal() / 6.3) + p["noise"] * 0.5 * math.sin(d.toordinal() / 1.9)
    return p["start"] * (1.0 + p["monthly_drift"]) ** months * smooth


def round_local(currency: str, amount: float) -> float:
    step = {"ARS": 10.0, "COP": 100.0, "MXN": 1.0}.get(currency, 1.0)
    return round(amount / step) * step


def is_business(h: Hotel) -> bool:
    return h.id in BUSINESS_HOTELS


def dow_factor(h: Hotel, d: date) -> float:
    return (BUSINESS_DOW if is_business(h) else LEISURE_DOW)[d.weekday()]


def event_factor(h: Hotel, d: date) -> float:
    best = 1.0
    for y in (d.year - 1, d.year, d.year + 1):
        for _, m, dd, dur, mult in h.events:
            start = date(y, m, dd)
            if start <= d < start + timedelta(days=dur):
                best = max(best, mult)
    return best


def event_name(h: Hotel, d: date) -> str | None:
    for y in (d.year - 1, d.year, d.year + 1):
        for name, m, dd, dur, _ in h.events:
            start = date(y, m, dd)
            if start <= d < start + timedelta(days=dur):
                return name
    return None


def default_bar_usd(h: Hotel, room: str, d: date) -> float:
    """Política histórica ingenua: temporada (mitad de amplitud) + día de semana. Ignora eventos."""
    base = h.base_usd[room] * (1.0 + 0.5 * (h.season[d.month] - 1.0))
    if is_business(h):
        base *= 1.05 if d.weekday() in (1, 2, 3) else 1.0
    else:
        base *= 1.08 if d.weekday() in (4, 5) else 1.0
    return float(round(base))


def parity_leak(h: Hotel, room: str, d: date) -> float:
    """Factor de precio que Booking muestra vs. directo (simula fugas de paridad ~6% de los días)."""
    key = (zlib.crc32(f"{h.id}|{room}|{d.toordinal()}|leak".encode()) & 0xFFFF) / 0xFFFF
    return 0.94 if key < 0.06 else 1.0


def channel_factor(h: Hotel, channel: str, room: str, d: date) -> float:
    if channel == "BOOKING":
        return parity_leak(h, room, d)
    return 1.0


@dataclass
class Booking:
    id: int
    hotel: str
    room: str
    channel: str
    checkin: date
    nights: int
    booked_at: datetime
    cancel_ts: datetime | None
    total_usd: float
    ota_ref: str | None
    guest: str
    guest_country: str
    adults: int
    cancelled_at: datetime | None = None


class World:
    def __init__(self, as_of: date | None = None, seed: int = C.DEFAULT_SEED, hotels: list[Hotel] | None = None):
        self.as_of = as_of or C.default_as_of()
        self.seed = seed
        self.hotels = hotels or C.HOTELS
        self.rng = np.random.default_rng(seed)
        self.now = datetime.combine(self.as_of, time(12, 0))
        self.window_start = self.as_of - timedelta(days=C.HISTORY_DAYS)
        self.future_end = self.as_of + timedelta(days=C.FUTURE_DAYS)
        self.bookings: dict[int, Booking] = {}
        self.sold: dict[tuple[str, str, date], int] = defaultdict(int)
        self.lost: dict[tuple[str, str, date], int] = defaultdict(int)
        self.cancel_heap: list[tuple[datetime, int]] = []
        self.events: list[tuple[datetime, str, int]] = []   # (ts, 'created'|'cancelled', booking_id)
        self.overrides: dict[tuple[str, str, date], float] = {}
        self._seq = 0
        self._dates = daterange(self.window_start, self.future_end + timedelta(days=30))
        self._idx = {d: i for i, d in enumerate(self._dates)}
        self._prep()

    # ------------------------------------------------------------------ preparación
    def _prep(self) -> None:
        n = len(self._dates)
        self.default_bar: dict[tuple[str, str], np.ndarray] = {}
        self.base_arrivals: dict[tuple[str, str], np.ndarray] = {}
        for h in self.hotels:
            rng = np.random.default_rng(self.seed * 1000 + sum(map(ord, h.id)))
            avg_los = 1.9 if is_business(h) else 2.3
            shock = np.exp(rng.normal(0, 0.12, size=n))
            for room in C.ROOM_TYPES:
                bars = np.array([default_bar_usd(h, room, d) for d in self._dates])
                self.default_bar[(h.id, room)] = bars
                idx = np.array([
                    h.season[d.month] * dow_factor(h, d) * event_factor(h, d) for d in self._dates
                ])
                occ = h.base_occ * idx * ROOM_DEMAND_FACTOR[room] * shock
                self.base_arrivals[(h.id, room)] = 1.25 * occ * h.rooms[room] / avg_los   # 1.25 compensa cancelaciones

    def bar_usd(self, hotel: str, room: str, d: date) -> float:
        ov = self.overrides.get((hotel, room, d))
        if ov is not None:
            return ov
        return float(self.default_bar[(hotel, room)][self._idx[d]])

    def set_override(self, hotel: str, room: str, d: date, usd: float) -> None:
        self.overrides[(hotel, room, d)] = float(usd)

    # ------------------------------------------------------------------ simulación
    def simulate_history(self) -> None:
        t = datetime.combine(self.window_start - timedelta(days=LOOKAHEAD_DAYS), time(0))
        while t < self.now:
            t1 = min(t + timedelta(days=1), self.now)
            self.step(t, t1)
            t = t1

    def tick(self, minutes: int = 60) -> tuple[datetime, datetime]:
        t0, t1 = self.now, self.now + timedelta(minutes=minutes)
        self.step(t0, t1)
        self.now = t1
        return t0, t1

    def _release_cancellations(self, upto: datetime) -> None:
        while self.cancel_heap and self.cancel_heap[0][0] <= upto:
            ts, bid = heapq.heappop(self.cancel_heap)
            b = self.bookings[bid]
            b.cancelled_at = ts
            for k in range(b.nights):
                self.sold[(b.hotel, b.room, b.checkin + timedelta(days=k))] -= 1
            self.events.append((ts, "cancelled", bid))

    def step(self, t0: datetime, t1: datetime) -> None:
        self._release_cancellations(t1)
        first = max(t0.date(), self.window_start)
        last = min(t0.date() + timedelta(days=LOOKAHEAD_DAYS), self.future_end)
        if first > last:
            return
        dates = daterange(first, last)
        ii = np.array([self._idx[d] for d in dates])
        inst = np.array([(datetime.combine(d, time(23, 0)) - t0).total_seconds() / 86400 for d in dates])
        inst1 = np.array([(datetime.combine(d, time(23, 0)) - t1).total_seconds() / 86400 for d in dates])
        chs = list(C.CHANNELS)
        shares = np.array([C.CHANNELS[c]["share"] for c in chs])
        w = np.zeros((len(chs), len(dates)))
        for k, c in enumerate(chs):
            theta = C.CHANNELS[c]["lead"] / 2.0
            w[k] = shares[k] * np.clip(_cdf_gamma2(inst, theta) - _cdf_gamma2(inst1, theta), 0, None)
        total_w = w.sum(axis=0)
        new: list[Booking] = []
        for h in self.hotels:
            for room in C.ROOM_TYPES:
                bars = self.default_bar[(h.id, room)][ii].copy()
                for j, d in enumerate(dates):   # overrides son pocos; chequeo directo
                    ov = self.overrides.get((h.id, room, d))
                    if ov is not None:
                        bars[j] = ov
                price_factor = (bars / h.base_usd[room]) ** (-h.elasticity)
                lam = self.base_arrivals[(h.id, room)][ii] * price_factor * total_w
                draws = self.rng.poisson(np.clip(lam, 0, 50))
                for j in np.nonzero(draws)[0]:
                    pj = w[:, j] / total_w[j]
                    for _ in range(int(draws[j])):
                        ch = chs[int(self.rng.choice(len(chs), p=pj))]
                        new.append(self._make_booking(h, room, dates[j], ch, t0, t1))
        new.sort(key=lambda b: b.booked_at)
        for b in new:
            self._release_cancellations(b.booked_at)
            cap = self._hotel(b.hotel).rooms[b.room]
            nights = [b.checkin + timedelta(days=k) for k in range(b.nights)]
            if any(self.sold[(b.hotel, b.room, n)] >= cap for n in nights):
                for n in nights:
                    self.lost[(b.hotel, b.room, n)] += 1
                continue
            for n in nights:
                self.sold[(b.hotel, b.room, n)] += 1
            self._seq += 1
            b.id = self._seq
            self.bookings[b.id] = b
            self.events.append((b.booked_at, "created", b.id))
            if b.cancel_ts is not None:
                heapq.heappush(self.cancel_heap, (b.cancel_ts, b.id))

    def _hotel(self, hid: str) -> Hotel:
        return C.HOTEL_BY_ID[hid]

    def _make_booking(self, h: Hotel, room: str, d: date, ch: str, t0: datetime, t1: datetime) -> Booking:
        rng = self.rng
        booked_at = t0 + (t1 - t0) * float(rng.random())
        los = 1 + int(rng.poisson(0.9 if is_business(h) else 1.3))
        los = min(los, 7)
        total = 0.0
        for k in range(los):
            n = d + timedelta(days=k)
            if n > self.future_end + timedelta(days=29):
                break
            total += self.bar_usd(h.id, room, n) * channel_factor(h, ch, room, n)
        checkin_ts = datetime.combine(d, time(15, 0))
        cancel_ts = None
        lead_days = (checkin_ts - booked_at).total_seconds() / 86400
        if lead_days > 1.0 and rng.random() < C.CHANNELS[ch]["cancel"]:
            ts = checkin_ts - timedelta(days=float(rng.exponential(9.0)))
            ts = max(ts, booked_at + timedelta(hours=float(rng.uniform(2, 48))))
            if ts < checkin_ts:
                cancel_ts = ts
        ota_ref = None
        if ch in C.OTA_CHANNELS:
            ota_ref = str(int(rng.integers(1_000_000_000, 9_999_999_999)))
        return Booking(
            id=0, hotel=h.id, room=room, channel=ch, checkin=d, nights=los, booked_at=booked_at,
            cancel_ts=cancel_ts, total_usd=round(total, 2), ota_ref=ota_ref,
            guest=f"{LAST_NAMES[int(rng.integers(len(LAST_NAMES)))]}, {FIRST_NAMES[int(rng.integers(len(FIRST_NAMES)))]}",
            guest_country=str(rng.choice(GUEST_COUNTRIES[ch])), adults=int(rng.choice([1, 2, 2, 2, 3])),
        )

    # ------------------------------------------------------------------ vistas de datos "de fuente"
    def ari_rows(self, ts: datetime, days: int = 120) -> list[dict]:
        rows = []
        for h in self.hotels:
            fx = fx_rate(h.currency, ts.date())
            for room in C.ROOM_TYPES:
                for d in daterange(max(ts.date(), self.window_start), ts.date() + timedelta(days=days)):
                    if d > self.future_end:
                        break
                    for ch in ("DIRECT", "BOOKING", "EXPEDIA", "DESPEGAR"):
                        usd = self.bar_usd(h.id, room, d) * channel_factor(h, ch, room, d)
                        rows.append(dict(
                            snapshot_ts=ts.isoformat(timespec="seconds"), hotel_code=C.CM_HOTEL_CODES[h.id],
                            room_code=C.ROOM_CODES["cm"][room], stay_date=d.isoformat(), channel=ch,
                            rate_amount=round_local(h.currency, usd * fx), currency=h.currency,
                            available=max(0, h.rooms[room] - self.sold[(h.id, room, d)]),
                        ))
        return rows

    def comp_rows(self, shop_date: date, days: int = 120) -> list[dict]:
        rows = []
        for h in self.hotels:
            rng = np.random.default_rng(self.seed + shop_date.toordinal() * 13 + sum(map(ord, h.id)))
            for d in daterange(shop_date, shop_date + timedelta(days=days)):
                i = self._idx.get(d)
                if i is None:
                    continue
                market = (h.base_usd["STD"] * (1 + 0.6 * (h.season[d.month] - 1))
                          * event_factor(h, d) ** 0.55 * dow_factor(h, d) ** 0.7)
                for k, name in enumerate(COMPETITORS[h.id]):
                    noise = float(np.exp(np.random.default_rng(self.seed + i * 31 + k).normal(0, 0.05)))
                    jitter = float(np.exp(rng.normal(0, 0.01)))
                    rows.append(dict(
                        shop_date=shop_date.isoformat(), hotel_code=C.CM_HOTEL_CODES[h.id], competitor=name,
                        stay_date=d.isoformat(), room_desc="Double Standard", currency="USD",
                        rate=round(market * COMP_OFFSET[k] * noise * jitter, 2), source="rate_shopper",
                    ))
        return rows

    def events_calendar(self) -> list[dict]:
        rows = []
        for h in self.hotels:
            for y in range(self.window_start.year - 1, self.future_end.year + 2):
                for name, m, dd, dur, mult in h.events:
                    start = date(y, m, dd)
                    rows.append(dict(
                        hotel_code=C.CM_HOTEL_CODES[h.id], city=h.city, event=name,
                        start_date=start.isoformat(), end_date=(start + timedelta(days=dur - 1)).isoformat(),
                        expected_impact="alto" if mult >= 1.4 else ("medio" if mult >= 1.25 else "bajo"),
                    ))
        return rows

    def fx_rows(self, a: date, b: date) -> list[dict]:
        return [dict(date=d.isoformat(), currency=cur, local_per_usd=round(fx_rate(cur, d), 4))
                for d in daterange(a, b) for cur in C.FX]

    def pos_rows(self, a: date, b: date) -> list[dict]:
        rows = []
        for h in self.hotels:
            for d in daterange(a, b):
                occupied = sum(self.sold[(h.id, r, d)] for r in C.ROOM_TYPES)
                rng = np.random.default_rng(self.seed + d.toordinal() + sum(map(ord, h.id)))
                usd = occupied * 22.0 * float(np.exp(rng.normal(0, 0.15)))
                rows.append(dict(hotel_code=C.CM_HOTEL_CODES[h.id], business_date=d.isoformat(), outlet="F&B",
                                 revenue=round_local(h.currency, usd * fx_rate(h.currency, d)),
                                 currency=h.currency, covers=int(occupied * 1.6)))
        return rows

    # ------------------------------------------------------------------ persistencia
    def save(self) -> None:
        C.ROOT.mkdir(parents=True, exist_ok=True)
        with open(C.STATE_FILE, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load() -> "World":
        with open(C.STATE_FILE, "rb") as f:
            return pickle.load(f)

    def summary(self) -> dict:
        created = len(self.bookings)
        cancelled = sum(1 for b in self.bookings.values() if b.cancelled_at)
        return dict(as_of=self.now.isoformat(timespec="minutes"), bookings=created, cancelled=cancelled,
                    lost_room_nights=int(sum(self.lost.values())), overrides=len(self.overrides))


def iter_events(world: World, a: datetime, b: datetime) -> Iterable[tuple[datetime, str, Booking]]:
    for ts, kind, bid in world.events:
        if a <= ts < b:
            yield ts, kind, world.bookings[bid]
