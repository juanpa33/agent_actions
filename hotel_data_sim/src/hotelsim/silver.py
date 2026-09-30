"""Capa SILVER: limpieza, normalización, deduplicación y cruce de fuentes.

Acá vive lo que más duele en los hoteles reales: el mismo dato en varios sistemas con
claves, monedas, códigos de habitación y formatos de fecha distintos.

  1. Adaptadores por fuente → esquema común de eventos de reserva.
  2. Cuarentena de lo inválido (malformado, importe <= 0, fechas incoherentes).
  3. Deduplicación de reenvíos.
  4. Colapso de eventos a estado actual por reserva (equivalente a MERGE / apply_changes).
  5. Cruce PMS ↔ channel manager: primero por referencia de OTA normalizada, luego por
     coincidencia difusa (hotel, habitación, fechas, canal, importe en USD, huésped).
  6. Conversión a USD con el tipo de cambio del día de la reserva.

Se reconstruye desde bronze en cada corrida (idempotente). En la nube el equivalente
incremental es `dlt.apply_changes` (Databricks) o `MERGE` (BigQuery): ver `cloud/`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import numpy as np
import pandas as pd

from . import config as C
from .ingest import get_clock, read_bronze
from .sources import CLOUDBEDS_SOURCE, MEWS_ORIGIN, OPERA_SOURCE

INV = lambda m: {v: k for k, v in m.items()}  # noqa: E731
ROOM_INV = {src: INV(m) for src, m in C.ROOM_CODES.items()}
CM_HOTEL_INV = INV(C.CM_HOTEL_CODES)
EVENT_COLS = ["source", "hotel_id", "native_id", "event_type", "event_ts", "created_at", "checkin", "checkout",
              "room_type", "total_local", "currency", "channel", "ext_ref", "guest", "adults", "ingested_at"]
MEWS_UTC_SHIFT_H = 3   # el mundo sintético emite Mews en "UTC" = hora local + 3 h


def norm_ref(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    digits = re.sub(r"\D", "", str(x))
    return digits if len(digits) >= 8 else None


def _j(raw: str) -> dict:
    return json.loads(raw)


# --------------------------------------------------------------------------- adaptadores
def parse_opera(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    good, bad = [], []
    for r in df.itertuples():
        try:
            d = _j(r.raw)
            x = d["reservation"]
            chan = INV(OPERA_SOURCE)[x["sourceCode"]]
            ref = x.get("externalReference")
            good.append(dict(
                source="pms_opera", hotel_id=d["hotelId"], native_id=x["resvNameId"],
                event_type="cancelled" if d["eventType"].endswith("CANCELLED") else "created",
                event_ts=d["eventTimestamp"], created_at=x["createdAt"], checkin=x["arrival"], checkout=x["departure"],
                room_type=ROOM_INV["opera"][x["roomCategory"]], total_local=float(x["totalAmount"]),
                currency=x["currencyCode"], channel=chan, ext_ref=norm_ref(ref), guest=x["guestName"],
                adults=x.get("adults"), ingested_at=r.ingested_at))
        except (KeyError, ValueError, TypeError) as e:
            bad.append(dict(source="pms_opera", file=r.file, line_no=r.line_no, reason=f"esquema: {e!r}", raw=r.raw))
    return good, bad


def parse_cloudbeds(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    good, bad = [], []
    for r in df.itertuples():
        try:
            d = _j(r.raw)
            hotel = r.hotel_dir
            good.append(dict(
                source="pms_cloudbeds", hotel_id=hotel, native_id=d["Reservation Number"],
                event_type="cancelled" if d["Event"] == "canceled" else "created",
                event_ts=datetime.strptime(d["Event Time"], "%d/%m/%Y %H:%M").isoformat(),
                created_at=datetime.strptime(d["Booking DateTime"], "%d/%m/%Y %H:%M").isoformat(),
                checkin=datetime.strptime(d["Check-In"], "%d/%m/%Y").date().isoformat(),
                checkout=datetime.strptime(d["Check-Out"], "%d/%m/%Y").date().isoformat(),
                room_type=ROOM_INV["cloudbeds"][d["Room Type"]], total_local=float(d["Grand Total"].replace(",", ".")),
                currency=d["Currency"], channel=INV(CLOUDBEDS_SOURCE)[d["Source"]],
                ext_ref=norm_ref(d["Third Party Confirmation Number"]), guest=d["Guest Name"],
                adults=int(d["Adults"]), ingested_at=r.ingested_at))
        except (KeyError, ValueError, TypeError) as e:
            bad.append(dict(source="pms_cloudbeds", file=r.file, line_no=r.line_no, reason=f"esquema: {e!r}", raw=r.raw))
    return good, bad


def parse_mews(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    good, bad = [], []
    shift = pd.Timedelta(hours=MEWS_UTC_SHIFT_H)
    for r in df.itertuples():
        try:
            d = _j(r.raw)
            x = d["Reservation"]
            local = lambda s: (pd.Timestamp(s).tz_localize(None) - shift).isoformat()  # noqa: E731
            good.append(dict(
                source="pms_mews", hotel_id=r.hotel_dir, native_id=x["Id"],
                event_type="cancelled" if d["Event"]["Type"] == "ReservationCanceled" else "created",
                event_ts=local(d["Event"]["TimeUtc"]), created_at=local(x["CreatedUtc"]),
                checkin=x["StartUtc"][:10], checkout=x["EndUtc"][:10],
                room_type=ROOM_INV["mews"][x["RequestedResourceCategoryId"]],
                total_local=float(x["TotalAmount"]["GrossValue"]), currency=x["TotalAmount"]["Currency"],
                channel=INV(MEWS_ORIGIN)[x["Origin"]], ext_ref=norm_ref(x.get("ChannelNumber")),
                guest=f'{x["Customer"]["LastName"]}, {x["Customer"]["FirstName"]}', adults=x.get("AdultCount"),
                ingested_at=r.ingested_at))
        except (KeyError, ValueError, TypeError) as e:
            bad.append(dict(source="pms_mews", file=r.file, line_no=r.line_no, reason=f"esquema: {e!r}", raw=r.raw))
    return good, bad


def parse_cm(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    good, bad = [], []
    for r in df.itertuples():
        try:
            d = _j(r.raw)
            good.append(dict(
                source="cm_reservations", hotel_id=CM_HOTEL_INV[d["hotelCode"]], native_id=d["channelResId"],
                event_type="cancelled" if d["messageType"] == "CANCEL" else "created", event_ts=d["receivedAt"],
                created_at=d["bookedAt"], checkin=d["checkIn"], checkout=d["checkOut"],
                room_type=ROOM_INV["cm"][d["roomCode"]], total_local=float(d["grossTotal"]), currency=d["currency"],
                channel=d["channel"], ext_ref=norm_ref(d["channelResId"]), guest=d["guest"]["name"],
                adults=d.get("adults"), ingested_at=r.ingested_at, commission_pct=d.get("commissionPct")))
        except (KeyError, ValueError, TypeError) as e:
            bad.append(dict(source="cm_reservations", file=r.file, line_no=r.line_no, reason=f"esquema: {e!r}", raw=r.raw))
    return good, bad


PARSERS = {"pms_opera": parse_opera, "pms_cloudbeds": parse_cloudbeds, "pms_mews": parse_mews, "cm_reservations": parse_cm}


def load_events() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Bronze → eventos normalizados + cuarentena + métricas de calidad."""
    goods, quarantine, dq = [], [], {}
    for source, fn in PARSERS.items():
        b = read_bronze(source)
        if b.empty:
            continue
        unparsable = b[~b.parse_ok]
        for r in unparsable.itertuples():
            quarantine.append(dict(source=source, file=r.file, line_no=r.line_no, reason="malformado", raw=r.raw))
        good, bad = fn(b[b.parse_ok])
        quarantine += bad
        goods += good
        dq[f"{source}.registros"] = len(b)
    ev = pd.DataFrame(goods)
    if ev.empty:
        return pd.DataFrame(columns=EVENT_COLS), pd.DataFrame(quarantine), dq
    for c in ("event_ts", "created_at", "ingested_at"):
        ev[c] = pd.to_datetime(ev[c])
    for c in ("checkin", "checkout"):
        ev[c] = pd.to_datetime(ev[c])
    if "commission_pct" not in ev:
        ev["commission_pct"] = np.nan
    invalid = (ev.total_local <= 0) | (ev.checkout <= ev.checkin)
    for r in ev[invalid].itertuples():
        quarantine.append(dict(source=r.source, file="", line_no=-1, reason="importe/fechas inválidos",
                               raw=f"{r.native_id} total={r.total_local} {r.checkin.date()}→{r.checkout.date()}"))
    ev = ev[~invalid]
    before = len(ev)
    ev = ev.drop_duplicates(["source", "hotel_id", "native_id", "event_type"], keep="first")
    dq["duplicados_eliminados"] = before - len(ev)
    q = pd.DataFrame(quarantine, columns=["source", "file", "line_no", "reason", "raw"])
    dq["cuarentena"] = len(q)
    return ev.reset_index(drop=True), q, dq


# --------------------------------------------------------------------------- tipo de cambio
def load_fx() -> pd.DataFrame:
    b = read_bronze("fx")
    if b.empty:
        return pd.DataFrame(columns=["date", "currency", "local_per_usd"])
    rows = [_j(r) for r in b[b.parse_ok].raw]
    fx = pd.DataFrame(rows)
    fx["date"] = pd.to_datetime(fx["date"])
    fx["local_per_usd"] = fx["local_per_usd"].astype(float)
    return fx.drop_duplicates(["date", "currency"]).sort_values("date").reset_index(drop=True)


def to_usd(df: pd.DataFrame, amount: str, currency: str, date_col: str, fx: pd.DataFrame, out: str) -> pd.DataFrame:
    """Convierte con el último FX disponible a la fecha (merge_asof por moneda)."""
    df = df.copy()
    df["_d"] = pd.to_datetime(df[date_col]).dt.normalize()
    left = df.sort_values("_d")
    right = fx.rename(columns={"date": "_d", "currency": currency})[["_d", currency, "local_per_usd"]]
    merged = pd.merge_asof(left, right.sort_values("_d"), on="_d", by=currency, direction="backward")
    rate = merged["local_per_usd"].where(merged[currency] != "USD", 1.0)
    merged[out] = (merged[amount] / rate).round(2)
    merged["fx_missing"] = rate.isna()
    return merged.drop(columns=["_d", "local_per_usd"]).sort_index()


# --------------------------------------------------------------------------- colapso y cruce
def collapse(ev: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Eventos → una fila por reserva con estado actual (equivale a MERGE por clave)."""
    if ev.empty:
        return ev
    ev = ev.assign(_ord=(ev.event_type != "created").astype(int)).sort_values(keys + ["_ord", "event_ts"])
    attrs = ev.drop_duplicates(keys, keep="first").drop(columns=["_ord", "event_type"])
    canc = (ev[ev.event_type == "cancelled"].drop_duplicates(keys)[keys + ["event_ts"]]
            .rename(columns={"event_ts": "cancelled_at"}))
    first = ev.groupby(keys, as_index=False)["event_ts"].min().rename(columns={"event_ts": "first_seen_at"})
    out = attrs.drop(columns=["event_ts"]).merge(canc, on=keys, how="left").merge(first, on=keys, how="left")
    return out.reset_index(drop=True)


def build_reservations(ev: pd.DataFrame, fx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = {}
    pms = collapse(ev[ev.source.str.startswith("pms_")], ["hotel_id", "native_id"])
    cm = collapse(ev[ev.source == "cm_reservations"], ["hotel_id", "channel", "native_id"])
    for d in (pms, cm):
        d["nights"] = (d.checkout - d.checkin).dt.days
    pms = to_usd(pms, "total_local", "currency", "created_at", fx, "total_usd")
    cm = to_usd(cm, "total_local", "currency", "created_at", fx, "total_usd")
    pms["pms_row"], cm["cm_row"] = np.arange(len(pms)), np.arange(len(cm))

    ota = pms.channel.isin(C.OTA_CHANNELS)
    exact = pms[ota & pms.ext_ref.notna()].merge(
        cm, left_on=["hotel_id", "channel", "ext_ref"], right_on=["hotel_id", "channel", "native_id"],
        suffixes=("", "_cm"))
    exact["match_status"] = "cruzada_por_referencia"

    used_p, used_c = set(exact.pms_row), set(exact.cm_row)
    p_rem = pms[ota & ~pms.pms_row.isin(used_p)]
    c_rem = cm[~cm.cm_row.isin(used_c)]
    fz = p_rem.merge(c_rem, on=["hotel_id", "room_type", "checkin", "checkout", "channel"], suffixes=("", "_cm"))
    fz["rel"] = (fz.total_usd - fz.total_usd_cm).abs() / fz.total_usd_cm
    fz["same_guest"] = fz.guest.str.lower().str.strip() == fz.guest_cm.str.lower().str.strip()
    fz = fz[(fz.rel <= 0.05) & fz.same_guest].sort_values("rel")
    fz = fz.drop_duplicates("pms_row").drop_duplicates("cm_row")
    fz["match_status"] = "cruzada_por_similitud"
    used_p |= set(fz.pms_row)
    used_c |= set(fz.cm_row)

    matched = pd.concat([exact, fz], ignore_index=True)
    pms_only = pms[~pms.pms_row.isin(used_p)].copy()
    pms_only["match_status"] = np.where(pms_only.channel.isin(C.OTA_CHANNELS), "solo_pms_sin_mensaje_cm", "directa_solo_pms")
    cm_only = cm[~cm.cm_row.isin(used_c)].copy()
    cm_only["match_status"] = "solo_channel_manager"

    def base(df, in_pms, in_cm, res_key_fn, cancel_cols):
        out = pd.DataFrame({
            "res_key": df.apply(res_key_fn, axis=1) if len(df) else [],
            "hotel_id": df.hotel_id, "room_type": df.room_type, "channel": df.channel,
            "checkin": df.checkin, "checkout": df.checkout, "nights": df.nights,
            "created_at": df.created_at, "total_local": df.total_local, "currency": df.currency,
            "total_usd": df.total_usd, "guest": df.guest, "match_status": df.match_status,
            "in_pms": in_pms, "in_cm": in_cm,
        })
        out["cancelled_at"] = df[cancel_cols].min(axis=1) if len(df) else pd.NaT
        out["first_seen_at"] = df[[c for c in ("first_seen_at", "first_seen_at_cm") if c in df]].min(axis=1)
        return out

    m = matched.copy()
    if len(m):
        m["created_at"] = m[["created_at", "created_at_cm"]].min(axis=1)
    parts = [
        base(m, True, True, lambda r: f'{r.hotel_id}:{r.native_id}', [c for c in ("cancelled_at", "cancelled_at_cm") if c in m]) if len(m) else None,
        base(pms_only, True, False, lambda r: f'{r.hotel_id}:{r.native_id}', ["cancelled_at"]) if len(pms_only) else None,
        base(cm_only, False, True, lambda r: f'{r.hotel_id}:{r.channel}:{r.native_id}', ["cancelled_at"]) if len(cm_only) else None,
    ]
    res = pd.concat([p for p in parts if p is not None], ignore_index=True)
    res["status"] = np.where(res.cancelled_at.notna(), "cancelada", "activa")
    commission = res.channel.map({k: v["commission"] for k, v in C.CHANNELS.items()})
    res["commission_pct"] = commission
    res["net_usd"] = (res.total_usd * (1 - commission)).round(2)
    res = res.sort_values(["hotel_id", "checkin", "created_at"]).reset_index(drop=True)
    stats.update({f"cruce.{k}": int(v) for k, v in res.match_status.value_counts().items()})
    stats["reservas_totales"] = len(res)
    stats["fx_faltante"] = int(pms.fx_missing.sum() + cm.fx_missing.sum())
    return res, stats


# --------------------------------------------------------------------------- otras fuentes
def _csv_source(name: str) -> pd.DataFrame:
    b = read_bronze(name)
    if b.empty:
        return pd.DataFrame()
    return pd.DataFrame([_j(r) for r in b[b.parse_ok].raw])


def build_ari(fx: pd.DataFrame) -> pd.DataFrame:
    a = _csv_source("cm_ari")
    if a.empty:
        return a
    a["snapshot_ts"] = pd.to_datetime(a.snapshot_ts)
    a["stay_date"] = pd.to_datetime(a.stay_date)
    a["rate_amount"] = a.rate_amount.astype(float)
    a["available"] = a.available.astype(int)
    a = a.sort_values("snapshot_ts", kind="stable").drop_duplicates(["hotel_code", "room_code", "stay_date", "channel"], keep="last")
    a["hotel_id"] = a.hotel_code.map(CM_HOTEL_INV)
    a["room_type"] = a.room_code.map(ROOM_INV["cm"])
    a = to_usd(a, "rate_amount", "currency", "snapshot_ts", fx, "rate_usd")
    return a[["hotel_id", "room_type", "stay_date", "channel", "rate_amount", "currency", "rate_usd", "available", "snapshot_ts"]]


def build_compset() -> pd.DataFrame:
    c = _csv_source("rate_shopper")
    if c.empty:
        return c
    c["shop_date"] = pd.to_datetime(c.shop_date)
    c["stay_date"] = pd.to_datetime(c.stay_date)
    c["rate"] = c.rate.astype(float)
    c["hotel_id"] = c.hotel_code.map(CM_HOTEL_INV)
    return (c.sort_values("shop_date", kind="stable").drop_duplicates(["hotel_id", "competitor", "stay_date", "shop_date"], keep="last")
            .rename(columns={"rate": "rate_usd"})[["hotel_id", "competitor", "shop_date", "stay_date", "rate_usd"]])


def build_events() -> pd.DataFrame:
    e = _csv_source("events_calendar")
    if e.empty:
        return e
    e["hotel_id"] = e.hotel_code.map(CM_HOTEL_INV)
    e["start_date"] = pd.to_datetime(e.start_date)
    e["end_date"] = pd.to_datetime(e.end_date)
    return e.drop_duplicates(["hotel_id", "event", "start_date"])[["hotel_id", "event", "start_date", "end_date", "expected_impact"]]


def build_pos(fx: pd.DataFrame) -> pd.DataFrame:
    p = _csv_source("pos")
    if p.empty:
        return p
    p["business_date"] = pd.to_datetime(p.business_date)
    p["revenue"] = p.revenue.astype(float)
    p["hotel_id"] = p.hotel_code.map(CM_HOTEL_INV)
    p = p.drop_duplicates(["hotel_id", "business_date", "outlet"])
    p = to_usd(p, "revenue", "currency", "business_date", fx, "revenue_usd")
    return p[["hotel_id", "business_date", "outlet", "revenue", "currency", "revenue_usd", "covers"]]


def build_source_health(ev: pd.DataFrame, clock: datetime) -> pd.DataFrame:
    rows = []
    for (src, hotel), g in ev.groupby(["source", "hotel_id"]):
        last_ev, last_ing = g.event_ts.max(), g.ingested_at.max()
        rows.append(dict(source=src, hotel_id=hotel, registros=len(g), ultimo_evento=last_ev, ultima_ingesta=last_ing,
                         minutos_desde_ultimo_evento=round((clock - last_ev).total_seconds() / 60, 1)))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- orquestación
def run_silver() -> dict:
    C.SILVER.mkdir(parents=True, exist_ok=True)
    clock = get_clock()
    ev, quarantine, dq = load_events()
    fx = load_fx()
    res, stats = build_reservations(ev, fx)
    dq.update(stats)
    tables = {
        "reservation": res, "fx": fx, "ari": build_ari(fx), "compset": build_compset(),
        "events": build_events(), "pos": build_pos(fx), "quarantine": quarantine,
        "source_health": build_source_health(ev, clock),
        "dq": pd.DataFrame([dict(check=k, value=float(v)) for k, v in sorted(dq.items())]),
        "meta": pd.DataFrame([dict(as_of_ts=clock, as_of_date=pd.Timestamp(clock).normalize())]),
    }
    for name, df in tables.items():
        if not df.empty:
            df.to_parquet(C.SILVER / f"{name}.parquet", index=False)
    return dq
