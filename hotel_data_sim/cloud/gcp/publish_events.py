"""Reproduce los archivos de aterrizaje del simulador como mensajes de Pub/Sub (referencia, NO ejecutado aquí).

    pip install google-cloud-pubsub
    python publish_events.py --project MI_PROYECTO --topic hotel-reservation-events --landing ../../data/landing

Cada mensaje = una línea cruda del sistema fuente; atributos: source y hotel_id. La suscripción a
BigQuery (terraform/main.tf) los escribe en `hotel_bronze.reservation_events`.
"""
import argparse
import json
from pathlib import Path

from google.cloud import pubsub_v1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--landing", required=True)
    ap.add_argument("--limit", type=int, default=1000)
    a = ap.parse_args()
    pub = pubsub_v1.PublisherClient()
    topic = pub.topic_path(a.project, a.topic)
    sent = 0
    for f in sorted(Path(a.landing).glob("pms_*/*/*.jsonl")) + sorted(Path(a.landing).glob("cm_reservations/*/*.jsonl")):
        source, hotel = f.parts[-3], f.parts[-2]
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                json.loads(line)          # el bronce de BigQuery (JSON) no acepta líneas malformadas: van a un DLQ aparte
            except json.JSONDecodeError:
                continue
            pub.publish(topic, line.encode(), source=source, hotel_id=hotel)
            sent += 1
            if sent >= a.limit:
                return print(f"{sent} mensajes publicados")
    print(f"{sent} mensajes publicados")


if __name__ == "__main__":
    main()
