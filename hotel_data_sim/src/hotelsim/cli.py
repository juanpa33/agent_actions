"""Línea de comandos: `hotelsim <comando>`."""
from __future__ import annotations

import argparse
import sys
from datetime import date

import pandas as pd


def _print_df(df: pd.DataFrame, **kw) -> None:
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(df.to_string(index=False, **kw))


def cmd_init(a):
    from . import pipeline
    pipeline.init(date.fromisoformat(a.as_of) if a.as_of else None, a.seed)
    print("\nListo. Probá: `hotelsim serve` (tablero + chat) o `hotelsim chat --agent`.")


def cmd_tick(a):
    from . import pipeline
    for _ in range(a.count):
        pipeline.tick(a.minutes)


def cmd_refresh(a):
    from . import pipeline
    pipeline.refresh()


def cmd_status(a):
    from . import tools
    import json
    print(json.dumps(tools.data_freshness(), ensure_ascii=False, indent=1))


def cmd_dashboard(a):
    from pathlib import Path
    from . import dashboard
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dashboard.build_html(live=False), encoding="utf-8")
    print(f"Tablero estático en {out}")


def cmd_serve(a):
    from . import server
    server.serve(a.port, a.host)


def cmd_chat(a):
    from .assistant import Conversation
    c = Conversation("agent" if a.agent else "assistant")
    print(f"Modo {c.mode} · motor {c.engine.name}. Escribí 'salir' para terminar.\n")
    while True:
        try:
            q = input("vos> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"salir", "exit", "quit"}:
            break
        if q:
            r = c.ask(q)
            print(f"\n{r.text}\n" + (f"[herramientas: {', '.join(t['name'] for t in r.tool_calls)}]\n" if r.tool_calls else ""))


def cmd_recommend(a):
    from . import pricing
    rec = pricing.recommendations(a.days, a.hotel)
    rec = rec.reindex(rec.change_pct.abs().sort_values(ascending=False).index).head(a.limit)
    out = rec[["hotel_id", "room_type", "stay_date", "bar_usd", "rec_bar_usd", "change_pct", "proj_occ", "confidence"]].copy()
    out["stay_date"] = out.stay_date.dt.strftime("%Y-%m-%d")
    out["change_pct"] = out.change_pct.map("{:+.0%}".format)
    out["proj_occ"] = out.proj_occ.map("{:.0%}".format)
    _print_df(out)
    print("\nMotivos del primero:", "; ".join(rec.iloc[0].reasons) if len(rec) else "-")


def cmd_pending(a):
    from . import channels
    q = channels.list_queue("propuesto" if not a.all else None)
    if not q:
        print("No hay propuestas.")
        return
    _print_df(pd.DataFrame(q)[["id", "status", "hotel_id", "room_type", "stay_date", "current_usd", "new_usd", "proposed_by"]])


def cmd_approve(a):
    from . import channels, pipeline
    ids = [e["id"] for e in channels.list_queue("propuesto")] if a.all else a.ids
    if not ids:
        print("Indicá --ids o --all")
        return 1
    res = channels.approve(ids, a.user)
    print(f"Publicadas: {len(res['published'])} · fallidas: {len(res['failed'])} · envíos a canales: {len(res['pushes'])}")
    for f in res["failed"]:
        print("  falló", f)
    pipeline.refresh(log=lambda *x: None)


def cmd_reject(a):
    from . import channels
    print("Rechazadas:", channels.reject(a.ids, a.user))


def cmd_backtest(a):
    from . import backtest
    r = backtest.run()
    print(f"Casos evaluados: {r['n']} (cambios sugeridos: {r.get('changed', 0)})\n")
    print("1) Calidad de la señal (¿terminaron más llenas las fechas donde sugería subir?)")
    s = r["signal"].copy()
    for c in ("ocupacion_final_media", "pct_llenas_90", "cambio_medio"):
        s[c] = s[c].map("{:.1%}".format)
    _print_df(s)
    print("\n2) Ingreso contrafáctico bajo distintas elasticidades (supuesto, no observado)")
    t = r["summary"].copy()
    t["ingreso_real"] = t.ingreso_real.map("{:,.0f}".format)
    t["ingreso_contrafactual"] = t.ingreso_contrafactual.map("{:,.0f}".format)
    t["delta_pct"] = t.delta_pct.map("{:+.1%}".format)
    _print_df(t)
    print("\nDatos sintéticos: valida la mecánica y el método, no promete resultados en un hotel real.")


def cmd_reset(a):
    from . import pipeline
    pipeline.reset_data()
    print("Datos locales borrados.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="hotelsim", description="Simulador de producto de datos para hoteles LATAM")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="simula historia, aterriza archivos y corre bronze→silver→gold")
    s.add_argument("--as-of", help="fecha 'hoy' de la simulación (YYYY-MM-DD); por defecto hoy")
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("tick", help="avanza el reloj simulado y procesa lo nuevo (casi tiempo real)")
    s.add_argument("--minutes", type=int, default=60)
    s.add_argument("--count", type=int, default=1)
    s.set_defaults(fn=cmd_tick)
    sub.add_parser("refresh", help="reprocesa bronze→silver→gold").set_defaults(fn=cmd_refresh)
    sub.add_parser("status", help="frescura y calidad de datos").set_defaults(fn=cmd_status)
    s = sub.add_parser("dashboard", help="genera el tablero HTML estático")
    s.add_argument("--out", default="reports/dashboard.html")
    s.set_defaults(fn=cmd_dashboard)
    s = sub.add_parser("serve", help="tablero interactivo + chat + aprobación (http://127.0.0.1:8765)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("chat", help="conversar por terminal")
    s.add_argument("--agent", action="store_true", help="modo agente de pricing (propone precios)")
    s.set_defaults(fn=cmd_chat)
    s = sub.add_parser("recommend", help="recomendaciones del motor de pricing")
    s.add_argument("--hotel")
    s.add_argument("--days", type=int, default=30)
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(fn=cmd_recommend)
    s = sub.add_parser("pending", help="propuestas en la cola de aprobación")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_pending)
    s = sub.add_parser("approve", help="APROBAR (persona) y publicar en canales simulados")
    s.add_argument("--user", required=True, help="nombre de quien aprueba")
    s.add_argument("--ids", nargs="*", default=[])
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("reject", help="rechazar propuestas")
    s.add_argument("--user", required=True)
    s.add_argument("--ids", nargs="+", required=True)
    s.set_defaults(fn=cmd_reject)
    sub.add_parser("backtest", help="backtest del motor de pricing sobre la historia").set_defaults(fn=cmd_backtest)
    sub.add_parser("reset", help="borra los datos locales").set_defaults(fn=cmd_reset)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
