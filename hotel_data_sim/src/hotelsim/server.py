"""Servidor local (stdlib) con tablero, chat, aprobación humana y simulación en vivo.

    hotelsim serve            →  http://127.0.0.1:8765

Escucha solo en 127.0.0.1 por defecto: no expone datos ni acciones a la red.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import channels, dashboard, pipeline
from .assistant import Conversation
from .llm import get_engine

LOCK = threading.Lock()
SESSIONS: dict[str, Conversation] = {}
MAX_SESSIONS = 50


class Handler(BaseHTTPRequestHandler):
    engine = None

    def log_message(self, *a):   # silencio
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode())

    def do_GET(self):
        with LOCK:
            try:
                if self.path in ("/", "/index.html"):
                    return self._send(200, dashboard.build_html(live=True, engine=self.engine.name).encode(), "text/html; charset=utf-8")
                if self.path == "/api/state":
                    st = dashboard.collect()
                    st["engine"] = self.engine.name
                    return self._json(st)
                self._json(dict(error="no encontrado"), 404)
            except Exception as e:
                self._json(dict(error=f"{type(e).__name__}: {e}"), 500)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(dict(error="JSON inválido"), 400)
        with LOCK:
            try:
                if self.path == "/api/chat":
                    msg = str(body.get("message", "")).strip()[:2000]
                    mode = body.get("mode", "assistant")
                    if not msg or mode not in ("assistant", "agent"):
                        return self._json(dict(error="mensaje o modo inválido"), 400)
                    key = f"{body.get('session', 'x')}:{mode}"
                    if key not in SESSIONS:
                        if len(SESSIONS) >= MAX_SESSIONS:
                            SESSIONS.pop(next(iter(SESSIONS)))
                        SESSIONS[key] = Conversation(mode, engine=self.engine)
                    r = SESSIONS[key].ask(msg)
                    return self._json(dict(text=r.text, tools=[c["name"] for c in r.tool_calls], engine=r.engine))
                if self.path == "/api/approve":
                    return self._json(self._approve(body))
                if self.path == "/api/reject":
                    return self._json(dict(rejected=channels.reject(list(body.get("ids", [])), str(body.get("user", "")))))
                if self.path == "/api/tick":
                    pipeline.tick(int(body.get("minutes", 60)), log=lambda *a: None)
                    from .ingest import get_clock
                    return self._json(dict(message=f"Simulación avanzó. Ahora: {get_clock():%Y-%m-%d %H:%M}"))
                self._json(dict(error="no encontrado"), 404)
            except channels.ValidationError as e:
                self._json(dict(error=str(e)), 400)
            except Exception as e:
                self._json(dict(error=f"{type(e).__name__}: {e}"), 500)

    def _approve(self, body: dict) -> dict:
        res = channels.approve(list(body.get("ids", [])), str(body.get("user", "")))
        pipeline.refresh(log=lambda *a: None)   # que el ARI publicado ya figure en el tablero
        return res


def serve(port: int = 8765, host: str = "127.0.0.1") -> None:
    Handler.engine = get_engine()
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Tablero en http://{host}:{port}  (motor de conversación: {Handler.engine.name})  — Ctrl+C para salir")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nchau")
