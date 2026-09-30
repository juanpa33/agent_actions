"""Capa BRONZE: ingesta incremental de archivos crudos, sin transformar.

Equivalente local de Databricks Auto Loader / de un Pub/Sub→BigQuery subscription:
solo procesa archivos nuevos (checkpoint), conserva el registro crudo tal cual
llegó (texto o JSON) junto con metadatos de origen, y NO rechaza nada: lo malformado
también se guarda (`parse_ok = False`) y se cuarentena recién en silver.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config as C


def get_clock() -> datetime:
    f = C.ROOT / "clock.json"
    if f.exists():
        return datetime.fromisoformat(json.loads(f.read_text())["now"])
    return datetime.now()


def set_clock(ts: datetime) -> None:
    C.ROOT.mkdir(parents=True, exist_ok=True)
    (C.ROOT / "clock.json").write_text(json.dumps({"now": ts.isoformat(timespec="seconds")}))


def _load_checkpoint() -> dict:
    f = C.CHECKPOINTS / "bronze.json"
    return json.loads(f.read_text()) if f.exists() else {"files": {}, "batches": 0}


def _read_file(path: Path) -> list[tuple[int, str, bool]]:
    """Devuelve [(nro_linea, raw, parse_ok)]. raw es JSON (str) si pudo parsearse, si no el texto original."""
    text = path.read_text(encoding="utf-8")
    out: list[tuple[int, str, bool]] = []
    if path.suffix == ".csv":
        reader = csv.reader(text.splitlines())
        header = next(reader, None)
        for i, row in enumerate(reader, start=2):
            if header and len(row) == len(header):
                out.append((i, json.dumps(dict(zip(header, row)), ensure_ascii=False), True))
            else:
                out.append((i, ",".join(row), False))
    elif path.suffix == ".jsonl":
        for i, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                json.loads(line)
                out.append((i, line, True))
            except json.JSONDecodeError:
                out.append((i, line, False))
    elif path.suffix == ".json":
        for i, obj in enumerate(json.loads(text), start=1):
            out.append((i, json.dumps(obj, ensure_ascii=False), True))
    return out


def ingest(clock: datetime | None = None) -> dict:
    """Ingesta los archivos nuevos de la zona de aterrizaje. Idempotente."""
    clock = clock or get_clock()
    ck = _load_checkpoint()
    new_files = sorted(p for p in C.LANDING.rglob("*") if p.is_file() and str(p.relative_to(C.LANDING)) not in ck["files"])
    by_source: dict[str, list[dict]] = {}
    for p in new_files:
        rel = p.relative_to(C.LANDING)
        source = rel.parts[0]
        hotel_dir = rel.parts[1] if len(rel.parts) > 2 else None
        for line_no, raw, ok in _read_file(p):
            by_source.setdefault(source, []).append(dict(
                source=source, hotel_dir=hotel_dir, file=str(rel), line_no=line_no, raw=raw,
                parse_ok=ok, ingested_at=clock.isoformat(timespec="seconds"),
            ))
    stats = {"batch": ck["batches"] + 1, "clock": clock.isoformat(timespec="seconds"),
             "files": len(new_files), "records": {}, "bad": {}}
    for source, rows in by_source.items():
        df = pd.DataFrame(rows)
        d = C.BRONZE / source
        d.mkdir(parents=True, exist_ok=True)
        df.to_parquet(d / f"part_{stats['batch']:05d}.parquet", index=False)
        stats["records"][source] = len(df)
        stats["bad"][source] = int((~df["parse_ok"]).sum())
    for p in new_files:
        ck["files"][str(p.relative_to(C.LANDING))] = True
    ck["batches"] += 1
    C.CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    (C.CHECKPOINTS / "bronze.json").write_text(json.dumps(ck))
    with open(C.CHECKPOINTS / "ingest_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(stats) + "\n")
    return stats


def read_bronze(source: str) -> pd.DataFrame:
    d = C.BRONZE / source
    parts = sorted(d.glob("part_*.parquet")) if d.exists() else []
    if not parts:
        return pd.DataFrame(columns=["source", "hotel_dir", "file", "line_no", "raw", "parse_ok", "ingested_at"])
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
