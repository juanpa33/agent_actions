"""Orquestación de punta a punta: simular → aterrizar → bronze → silver → gold."""
from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta

from . import config as C
from .generator import World
from .ingest import ingest, set_clock
from .silver import run_silver
from . import sources


def reset_data() -> None:
    for p in (C.LANDING, C.LAKE, C.OUTBOX):
        if p.exists():
            shutil.rmtree(p)
    for f in (C.STATE_FILE, C.QUEUE_FILE, C.ROOT / "clock.json"):
        if f.exists():
            f.unlink()


def refresh(log=print) -> dict:
    """Bronze → silver → gold sobre lo que haya en la zona de aterrizaje."""
    from .gold import run_gold
    stats = {"bronze": ingest()}
    log(f"  bronze: {stats['bronze']['files']} archivos nuevos, {sum(stats['bronze']['records'].values())} registros")
    stats["silver"] = run_silver()
    log(f"  silver: {int(stats['silver'].get('reservas_totales', 0))} reservas unificadas, "
        f"{int(stats['silver'].get('cuarentena', 0))} en cuarentena")
    stats["gold"] = run_gold()
    log(f"  gold: {len(stats['gold'])} tablas")
    return stats


def init(as_of: date | None = None, seed: int = C.DEFAULT_SEED, log=print) -> World:
    reset_data()
    log(f"Simulando historia hasta {as_of or C.default_as_of()} (semilla {seed})...")
    w = World(as_of=as_of, seed=seed)
    w.simulate_history()
    log(f"  {w.summary()}")
    set_clock(w.now)
    n = sources.write_history(w)
    log(f"  {n} registros crudos escritos en {C.LANDING}")
    w.save()
    log("Procesando medallion...")
    refresh(log)
    return w


def tick(minutes: int = 60, log=print) -> dict:
    """Avanza el reloj simulado: nuevas reservas/cancelaciones llegan como archivos y se procesan."""
    w = World.load()
    a, b = w.tick(minutes)
    tag = b.strftime("%Y%m%d%H%M")
    n = sources.write_reservation_files(w, a, b, live_tag=tag)
    sources.write_snapshots(w, b, tag=f"live_{tag}")
    set_clock(b)
    w.save()
    log(f"Tick {a:%Y-%m-%d %H:%M} → {b:%H:%M}: {n} registros nuevos")
    return refresh(log)
