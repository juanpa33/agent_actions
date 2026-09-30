# Asistente conversacional y agente de pricing

Dos conversadores sobre las mismas herramientas (`tools.py`), con permisos distintos:

| | Asistente | Agente de pricing |
|---|---|---|
| Lee KPIs, pickup, compset, paridad, canales, frescura, SQL de solo lectura | ✅ | ✅ |
| Pide recomendaciones de precio al motor de reglas | ❌ | ✅ |
| **Propone** cambios a la cola de aprobación | ❌ | ✅ |
| **Aprueba / publica** precios | ❌ | ❌ (solo una persona) |

## Cómo se usa

```bash
pip install -e ".[llm,dev]"
hotelsim init                        # simula ~520 días de historia y corre bronce→plata→oro
hotelsim serve                       # http://127.0.0.1:8765  tablero + chat + aprobación
hotelsim chat --agent                # o por terminal
```

- **Sin credenciales** corre en *modo sin conexión*: un enrutador por palabras clave sobre las mismas herramientas. Sirve para probar el producto completo, no entiende preguntas libres.
- **Con `ANTHROPIC_API_KEY`** (o un perfil de `ant auth login`) usa Claude con *tool use*. Variables: `HOTELSIM_MODEL` (por defecto `claude-opus-5-5`), `HOTELSIM_EFFORT` (`medium`), `HOTELSIM_FALLBACKS=0` para desactivar el *fallback* server-side ante rechazos del clasificador, `HOTELSIM_OFFLINE=1` para forzar el modo sin conexión.
- **El camino con Claude no se probó contra la API real** en este entorno (no hay credenciales). Se testeó el ciclo de herramientas con un cliente simulado (`tests/test_conversadores.py`): llamada de herramienta → resultado → respuesta, herramienta fallida, rechazo del clasificador y que el agente nunca reciba una herramienta de aprobación. La primera corrida real puede requerir ajustes (p. ej. los parámetros beta de `fallbacks`).

## Barreras de seguridad (en código, no solo en el prompt)

1. **El agente no tiene herramienta de aprobación.** `approve()` está en `channels.py` y solo la llaman la CLI (`hotelsim approve --user …`) y el botón del tablero; exige un nombre de persona (rechaza "agente", "claude", "IA"…).
2. **Validación dura al proponer y de nuevo al aprobar**: hotel y tipo de habitación válidos, fecha dentro del horizonte, piso/techo por hotel y tipo, cambio máximo ±20 % (el motor recomienda como máximo ±15 %).
3. **Misma tarifa en todos los canales** (paridad): el conector simulado publica en motor propio, Booking, Expedia y Despegar con el mismo precio.
4. **SQL de solo lectura**: una sola sentencia `SELECT/WITH`, lista blanca de tablas gold, conexión DuckDB `read_only`, tope de 60 filas; bloquea `ATTACH`, `COPY`, `read_parquet`, tablas silver, etc. (tests en `test_channels_y_seguridad.py`).
5. **Auditoría**: `data/outbox/audit.jsonl` registra propuestas, rechazos y aprobaciones con quién y cuándo.
6. **Los datos que lee el modelo son datos, no instrucciones**: los resultados de herramientas vuelven como `tool_result`; el prompt de sistema indica no presentar la simulación como información real.

## Cómo decide el motor (`pricing.py`)

1. **Proyección de ocupación final por pickup**: OTB hoy + (final del año pasado − OTB del año pasado a esta altura) × √(ritmo). Si no hay historia comparable, usa la curva de lead time (0,7/0,3 de mezcla cuando hay ambas).
2. **Reglas aditivas**: ocupación proyectada alta/baja (amortiguadas a >45 días), ritmo vs. año pasado, evento de impacto medio/alto, pocas habitaciones disponibles.
3. **Competencia**: tope a 1,30× y piso a 0,85× la mediana del compset.
4. **Barreras**: paso máximo ±15 %, piso/techo del hotel, no mover si el cambio <2 %.

Cada recomendación incluye los motivos y una confianza (alta/media/baja).

## Backtest (`hotelsim backtest`)

Para cada noche-habitación de los últimos 120 días reconstruye lo que el motor habría visto a 14 días. Ejemplo de una
corrida (semilla 7, hoy simulado 2026-09-30, 1.068 casos):

| Señal del motor | Casos | Ocupación final media | % de fechas ≥90 % llenas |
|---|---|---|---|
| subir | 286 | 75,5 % | 20,3 % |
| mantener | 307 | 57,5 % | 0,3 % |
| bajar | 475 | 42,6 % | 0,4 % |

Las fechas en las que sugería subir terminaron mucho más llenas que aquellas en las que sugería bajar: **la señal
ordena bien**. Esa lectura no depende de ningún supuesto de elasticidad.

El ingreso contrafactual (+2,9 % a +3,3 % según elasticidad supuesta 0,8–1,6) **es una estimación bajo supuestos**,
sobre datos sintéticos cuya política de precios "histórica" fue ingenua a propósito (ignora eventos). Muestra que la
mecánica funciona; **no es una promesa de mejora en un hotel real**, donde la política previa suele ser mejor que esa.
Es conservador en fechas agotadas (la demanda perdida por falta de cupo no se observa).

## Siguientes pasos razonables con un cliente real

1. Reemplazar los adaptadores por los del sistema real del hotel y medir la reconciliación contra su reporte de gestión.
2. Calibrar reglas y umbrales con el revenue manager (qué es "ocupación alta" en su hotel).
3. Probar el agente en *modo sombra* (propone, no publica) durante 4–6 semanas y medir aciertos antes de habilitar el envío.
4. Integrar el envío de tarifas por el channel manager del hotel o un Connectivity Partner certificado (ver `docs/FUENTES.md`).
