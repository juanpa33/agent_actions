"""Motores de conversación: Claude (API de Anthropic) o modo sin conexión con reglas fijas.

`get_engine()` elige Claude si hay credenciales en el entorno (ANTHROPIC_API_KEY,
ANTHROPIC_AUTH_TOKEN o un perfil de `ant auth login`); si no, el modo sin conexión permite
probar el tablero, las herramientas y el flujo de aprobación sin gastar nada.

Configuración por entorno:
  HOTELSIM_MODEL       modelo de Claude (por defecto claude-opus-5-5)
  HOTELSIM_EFFORT      low|medium|high (por defecto medium)
  HOTELSIM_FALLBACKS   0 para desactivar el fallback server-side ante rechazos del clasificador
  HOTELSIM_OFFLINE     1 fuerza el modo sin conexión
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable

from . import tools as T

MAX_TOOL_RESULT_CHARS = 14000
MAX_STEPS = 10


@dataclass
class Reply:
    text: str
    tool_calls: list[dict] = field(default_factory=list)   # [{name, args, ok}]
    engine: str = "offline"
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)


def _clip(result: dict) -> str:
    s = json.dumps(result, ensure_ascii=False, default=str)
    return s if len(s) <= MAX_TOOL_RESULT_CHARS else s[:MAX_TOOL_RESULT_CHARS] + '…[resultado recortado]'


def has_credentials() -> bool:
    if os.environ.get("HOTELSIM_OFFLINE") == "1":
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    from pathlib import Path
    return (Path.home() / ".config" / "anthropic").exists()


class ClaudeEngine:
    name = "claude"

    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = os.environ.get("HOTELSIM_MODEL", "claude-opus-5-5")
        self.effort = os.environ.get("HOTELSIM_EFFORT", "medium")
        self.fallbacks = os.environ.get("HOTELSIM_FALLBACKS", "1") != "0"

    def _create(self, system: str, messages: list[dict], schemas: list[dict]):
        kwargs = dict(
            model=self.model, max_tokens=16000, system=system, messages=messages, tools=schemas,
            thinking={"type": "adaptive"}, output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
        )
        if self.fallbacks:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        return self.client.beta.messages.create(**kwargs)

    def run(self, system: str, history: list[dict], registry: dict[str, Callable], schemas: dict[str, dict]) -> Reply:
        a = self.anthropic
        tool_defs = [dict(name=n, **schemas[n]) for n in registry]
        calls: list[dict] = []
        usage = dict(input_tokens=0, output_tokens=0, cache_read_input_tokens=0)
        for _ in range(MAX_STEPS):
            try:
                resp = self._create(system, history, tool_defs)
            except a.RateLimitError:
                return Reply("Claude está limitando la tasa de pedidos; probá de nuevo en un minuto.", calls, self.name, "error")
            except a.AuthenticationError:
                return Reply("Las credenciales de Anthropic no son válidas (revisá ANTHROPIC_API_KEY).", calls, self.name, "error")
            except a.APIConnectionError:
                return Reply("No pude conectarme a la API de Anthropic.", calls, self.name, "error")
            except a.APIStatusError as e:
                return Reply(f"Error de la API ({e.status_code}): {e.message}", calls, self.name, "error")
            for k in usage:
                usage[k] += getattr(resp.usage, k, 0) or 0
            history.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
            if resp.stop_reason == "refusal":
                return Reply("Claude no pudo responder a este pedido (rechazo del clasificador de seguridad). Reformulá la consulta.",
                             calls, self.name, "refusal", usage)
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason == "tool_use":
                results = []
                for b in resp.content:
                    if b.type == "tool_use":
                        out = T.execute(b.name, b.input, registry)
                        calls.append(dict(name=b.name, args=b.input, ok="error" not in out))
                        results.append(dict(type="tool_result", tool_use_id=b.id, content=_clip(out), is_error="error" in out))
                history.append({"role": "user", "content": results})
                continue
            text = "".join(b.text for b in resp.content if b.type == "text")
            if resp.stop_reason == "max_tokens":
                text += "\n\n(La respuesta se cortó por longitud.)"
            return Reply(text, calls, self.name, resp.stop_reason, usage)
        return Reply("Alcancé el máximo de pasos de herramientas sin terminar; acotá la pregunta.", calls, self.name, "max_steps", usage)


def get_engine():
    if has_credentials():
        try:
            return ClaudeEngine()
        except ImportError:
            pass
    from .offline import OfflineEngine
    return OfflineEngine()
