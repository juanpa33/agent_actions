# Agente revisor de acciones — NVIDIA, YPF y top 10 del NASDAQ

Sistema de análisis cuantitativo que descarga precios reales, calcula señales con
respaldo académico, las backtestea sin sesgo de anticipación y —lo más
importante— **te dice cuándo el resultado no es estadísticamente distinguible de
la suerte**.

> **No es asesoramiento financiero.** Produce señales y estadística, no
> recomendaciones. Las decisiones y sus consecuencias son tuyas.

## Qué analiza

| Activo | Símbolo | Cómo se analiza |
|---|---|---|
| NVIDIA | `NVDA` | Directo en USD |
| YPF | `YPFD.BA` | BYMA en pesos, **convertido a USD por CCL implícito** |
| Top 10 NASDAQ | dinámico | Resuelto desde las tenencias del ETF QQQ + capitalización |
| Benchmark | `^NDX` | Nasdaq-100, base del modelo de mercado |

## Instalación

```bash
git clone <este-repo>
cd agent_actions
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Análisis completo: NVDA + YPFD.BA + top 10 del NASDAQ
python scripts/run_analysis.py

# Solo los dos que te interesan
python scripts/run_analysis.py --solo NVDA,YPFD.BA

# Validación estadística seria: 10 años en vez de 2 (ver más abajo por qué)
python scripts/run_analysis.py --anios 10

# Sin estudio de eventos (más rápido, no consulta SEC EDGAR)
python scripts/run_analysis.py --sin-eventos
```

Salida: `reports/reporte.md` y `reports/reporte.procedencia.json` con la cadena
completa de origen de cada dato.

**Requiere conexión a internet.** No hay modo sin datos: el programa no inventa
series.

## Las cuatro reglas del sistema

**1. Ningún dato sin procedencia.** Cada serie lleva fuente, URL, momento de
descarga y hash. Los datos de test se marcan como sintéticos, la marca se propaga
por cualquier cadena de cálculos, y el reporte aborta si detecta contaminación.

**2. Lo que falta se denuncia, no se rellena.** Sin interpolación de precios ni
extrapolación de IPC. Si falta un dato, el pipeline falla. Un número plausible e
incorrecto es peor que ningún número.

**3. Los parámetros salen de los papers, no de estos datos.** SMA de 200 ruedas
(Faber 2007), momentum 12-1 (Moskowitz, Ooi & Pedersen 2012), máximo de 52
semanas (George & Hwang 2004). Ajustar un parámetro para mejorar el backtest es
justamente lo que lo invalida.

**4. El retorno del backtest no decide nada. La estadística sí.** El número que
importa es el Deflated Sharpe Ratio, que descuenta cuántas configuraciones
probaste. Por debajo de 0,95, el resultado es compatible con el azar por
espectacular que luzca el retorno.

## Qué hace distinto a esto de un script de trading cualquiera

### Maneja el split 10:1 de YPF

El 4 de agosto de 2026, YPFD hizo un split 10:1 en BYMA y la razón del ADR pasó
de 1:1 a 1:10. Si se calcula el CCL implícito con la razón equivocada, toda la
serie histórica en dólares queda multiplicada o dividida por diez.

El sistema deriva la razón efectiva según la serie esté ajustada o cruda
(`argentina.py`), y después **verifica** que el CCL resultante no dé un salto en
la fecha del split. Un tipo de cambio puede saltar por una devaluación, pero no
el día exacto de una acción societaria: si salta, es un error de datos y el
reporte lo dice en vez de seguir.

### Convierte las noticias en estadística, no en opinión

No hay puntajes de sentimiento. `news.sentiment_score()` lanza
`NotImplementedError` a propósito: un número generado leyendo titulares no tiene
unidad, ni error de medición, ni reproducibilidad.

En su lugar: eventos fechados de SEC EDGAR (8-K y 6-K), clasificados con reglas
legibles, y medidos con **retornos anormales** contra un modelo de mercado
estimado sobre las 250 ruedas previas (MacKinlay 1997). Eso sí tiene error
estándar, así que se puede decir si el movimiento fue distinguible del ruido
normal del papel — y separa lo que se movió por el mercado de lo que se movió
por la empresa.

### Te dice cuándo no sabe

El reporte incluye intervalos de confianza por bootstrap estacionario, p-valores,
probabilidad de sobreajuste y el largo mínimo de historial necesario para
concluir algo. Si el intervalo del Sharpe incluye el cero, lo dice.

## Advertencia sobre los dos años

Dos años de datos diarios son ~500 observaciones. Con volatilidad del 30% anual,
el error estándar del retorno medio ronda los 21 puntos porcentuales: una
estrategia con retorno esperado real de 0% puede mostrar +20% en dos años por
puro azar.

Para **describir** el período reciente, dos años están bien. Para **validar** una
estrategia, corré `--anios 10`. Son preguntas distintas.

## Configuración

`config/analysis.yaml`. Dos parámetros merecen atención especial:

- **`configuraciones_evaluadas`**: cuántas variantes probaste en toda la
  investigación, incluidas las descartadas. Es el insumo del Deflated Sharpe.
  Declararlo de menos infla artificialmente la significancia de tu resultado, y
  el sistema no tiene forma de verificarlo.
- **`costos`**: los valores por defecto son órdenes de magnitud públicos, no las
  condiciones de tu cuenta. Los de BYMA son mucho mayores que los de EE.UU.
  Reemplazalos por tu tarifario real antes de operar.

## Tests

```bash
python -m pytest tests/ -q
```

Corren sin red. Verifican, entre otras cosas: que la contaminación sintética no
puede llegar a un reporte, que una señal con visión del futuro no puede
capitalizarla, que el Deflated Sharpe rechaza la mejor de 200 series de ruido
puro, que aplicar mal el split de YPF dispara la alarma, y que el estudio de
eventos encuentra un shock inyectado sin inventar uno donde no lo hay.

## Documentación

- [`docs/METODOLOGIA.md`](docs/METODOLOGIA.md) — qué hace cada pieza y por qué es
  defendible, con las referencias completas.
- [`docs/LIMITACIONES.md`](docs/LIMITACIONES.md) — lo que el sistema no puede
  hacer. Leelo antes de arriesgar plata.

## Estructura

```
src/stockagent/
  provenance.py     Trazabilidad obligatoria; barrera anti datos sintéticos
  datasources/      Yahoo, Stooq, INDEC + reconciliación entre fuentes
  argentina.py      CCL implícito, split 10:1, deflación por IPC
  indicators.py     Solo indicadores con evidencia publicada
  signals.py        Combinación por voto, pesos iguales (no optimizados)
  backtest.py       Ejecución en t+1, costos, walk-forward
  statistics.py     Deflated Sharpe, PBO, bootstrap estacionario
  events.py         Estudio de eventos con retornos anormales
  news.py           Eventos de SEC EDGAR (sin puntajes de sentimiento)
  universe.py       Top 10 del NASDAQ resuelto dinámicamente
  report.py         Reporte en Markdown con incertidumbre explícita
```
