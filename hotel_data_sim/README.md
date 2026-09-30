# hotelsim — simulador MVP de un producto de datos para hoteles (LATAM)

Muestra de punta a punta cómo se ve unificar los sistemas de un hotel **casi en tiempo real**, para decidir con datos
frescos: ingesta → cruce de fuentes → lago (bronce/plata/oro) → reporting → asistente conversacional → agente de
pricing con aprobación humana. Con **datos sintéticos** (3 hoteles ficticios: Mendoza, Cartagena, Ciudad de México).

> Hoteles, tarifas, eventos y reservas son inventados. Sirve para probar el producto y el método, no para sacar
> conclusiones de mercado. Ver [`docs/FUENTES.md`](docs/FUENTES.md) para qué está verificado y qué es supuesto.

## Probarlo (5 minutos)

```bash
cd hotel_data_sim
pip install -e ".[llm,dev]"     # Python >= 3.10
hotelsim init                   # ~10 s: simula ~520 días, aterriza archivos, bronce→plata→oro
hotelsim serve                  # http://127.0.0.1:8765
```

En el tablero: elegí un hotel, conversá con el asistente, pasá al **Agente de pricing**, pedile *«Recomendame precios
para los próximos 14 días»* y luego *«Proponé los cambios»*. Las propuestas quedan **pendientes**: una persona pone su
nombre y las aprueba (se publican en un conector simulado). **▶ Avanzar 1 h** simula que llegan reservas nuevas y
reprocesa todo.

Por terminal: `hotelsim chat --agent` · `hotelsim recommend` · `hotelsim pending` · `hotelsim approve --user "Ana" --all`
· `hotelsim backtest` · `hotelsim status` · `hotelsim dashboard --out reports/dashboard.html` (HTML estático).

Sin credenciales el chat corre en *modo sin conexión* (palabras clave). Con `ANTHROPIC_API_KEY` usa Claude
([detalles y límites](docs/AGENTE.md)).

## Qué contiene

| Pieza | Dónde |
|---|---|
| Mundo sintético (demanda, elasticidad, cancelaciones, canales) | `src/hotelsim/generator.py` |
| Fuentes crudas heterogéneas y sucias (3 PMS, channel manager, rate shopper, FX, POS) | `src/hotelsim/sources.py` |
| Bronce: ingesta incremental con checkpoint | `src/hotelsim/ingest.py` |
| Plata: parseo, cuarentena, dedupe, cruce PMS↔channel manager, USD | `src/hotelsim/silver.py` |
| Oro: KPIs, pickup/pace, compset, paridad, canales (SQL) | `sql/*.sql`, `src/hotelsim/gold.py` |
| Tablero + servidor local | `src/hotelsim/dashboard.{py,html}`, `server.py` |
| Asistente y agente (herramientas, prompts, motor Claude/offline) | `tools.py`, `assistant.py`, `llm.py`, `offline.py` |
| Motor de pricing, cola de aprobación, conector simulado, backtest | `pricing.py`, `channels.py`, `backtest.py` |
| Referencia para Databricks y GCP (**no ejecutada aquí**) | `cloud/` |
| Arquitectura, fuentes, diseño del agente | `docs/` |

## Lo que está probado y lo que no

- ✅ `python -m pytest` (40 tests, ~20 s): el pipeline reconcilia contra la verdad del simulador, detecta la suciedad inyectada, el cruce entre sistemas funciona, el SQL de solo lectura bloquea lo peligroso, el agente no puede aprobar, un precio aprobado llega al ARI tras un tick.
- ✅ Tablero revisado en un navegador real (Chromium) en modo claro.
- ⚠️ **Claude real**: no probado contra la API (sin credenciales en este entorno); el ciclo de herramientas se testeó con un cliente simulado.
- ⚠️ **`cloud/`** (Databricks, Terraform/BigQuery, Pub/Sub): escrito desde la documentación oficial, sin ejecutar ni validar con las herramientas de cada nube.
- ⚠️ Formatos de fuente son imitaciones genéricas, no los esquemas reales de Opera/Mews/Cloudbeds/Booking.
- ⚠️ El backtest valida la señal del motor sobre datos sintéticos; **no prueba mejoras de ingresos** en un hotel real.
