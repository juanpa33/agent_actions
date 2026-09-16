# Metodología

Este documento explica qué hace el sistema y, sobre todo, por qué cada decisión
es defendible. Si algo acá no te cierra, esa es exactamente la discusión que hay
que tener antes de poner plata.

## 1. El problema que este diseño intenta evitar

Construir una estrategia que se vea bien sobre datos pasados es trivial. Con
suficientes indicadores y suficientes combinaciones de parámetros, siempre se
encuentra una configuración con un retorno excelente en el período estudiado. El
problema es que ese resultado, en la enorme mayoría de los casos, es ruido.

Bailey, Borwein, López de Prado y Zhu lo formalizaron en *The Probability of
Backtest Overfitting* (Journal of Computational Finance, 2017): si se prueban
suficientes variantes sobre una muestra finita, el Sharpe de la mejor tiende a
ser alto **aunque ninguna variante tenga poder predictivo real**. El backtest
deja de medir la estrategia y pasa a medir cuántas cosas probaste.

Todo lo que sigue está organizado alrededor de no caer en eso.

## 2. Datos

### Fuentes

| Dato | Fuente primaria | Validación |
|---|---|---|
| Precios NASDAQ y ADR YPF | Yahoo Finance (yfinance) | Stooq, segunda fuente independiente |
| Precios YPFD (BYMA) | Yahoo Finance | Sin segunda fuente pública confiable — se declara en el reporte |
| IPC Argentina | INDEC vía `apis.datos.gob.ar` | — |
| Composición Nasdaq-100 | Tenencias publicadas del ETF QQQ (Invesco) | — |
| Eventos societarios | SEC EDGAR (formularios 8-K y 6-K) | — |

### Reglas de integridad

1. **Toda serie lleva procedencia.** Fuente, URL, momento de descarga y hash del
   contenido. Implementado en `provenance.py`, y no es opcional: las funciones
   de descarga son las únicas que pueden crear datos `OBSERVED`.
2. **Los datos faltantes se denuncian, no se rellenan.** No hay interpolación de
   precios ni extrapolación de IPC. Si falta un dato, el pipeline lanza
   `MissingDataError`. Un pipeline que falla es molesto; uno que entrega un
   número plausible e incorrecto es peligroso.
3. **Los datos sintéticos no pueden publicarse.** Los datos de test se marcan
   como `SYNTHETIC` y la marca se propaga a través de cualquier cadena de
   cálculos. Antes de escribir el reporte, `assert_no_synthetic_data` aborta si
   detecta contaminación.
4. **Dos fuentes, reconciliadas.** Yahoo y Stooq se comparan día a día. Las
   diferencias por encima del 1% se listan en el reporte. No se "corrigen": se
   informan, porque no hay forma de saber cuál de las dos está bien.
5. **Detección de patologías.** Precios no positivos, fechas duplicadas, saltos
   de más de 8 desvíos y series congeladas. Un split no ajustado aparece como un
   retorno de -90% en un día y este chequeo lo atrapa.

## 3. El caso argentino: YPFD en BYMA

Analizar una acción argentina en pesos nominales es un error de medición. El
retorno nominal está dominado por la inflación: una acción que perdió poder
adquisitivo puede mostrar un retorno positivo de tres dígitos.

El sistema aplica dos correcciones.

### 3.1 Conversión a dólares por CCL implícito

```
CCL = precio_YPFD_en_ARS × acciones_por_ADS / precio_ADR_YPF_en_USD
```

Es el tipo de cambio efectivo al que accede un inversor local, y no depende de
ninguna estimación: sale de dos precios de mercado observados.

### 3.2 El split 10:1 y por qué casi rompe todo

El 4 de agosto de 2026 se hizo efectivo en BYMA un split 10:1 de YPFD, junto con
el cambio de la razón del ADR de 1:1 a 1:10. El precio del ADR quedó inalterado;
el local se dividió por diez.

Esto tiene una consecuencia que rompe el cálculo si se la ignora. Con precios
**crudos**, la razón es variable en el tiempo: 1 antes del split, 10 después.
Con precios **ajustados por split** (que es lo que entrega Yahoo con
`auto_adjust=True`), el proveedor divide por diez todo el historial local previo,
mientras que el ADR no se toca. La derivación está en
`argentina.effective_ratio_for_adjusted_series`, y el resultado es que sobre
series ajustadas la razón efectiva es **constante e igual a 10**.

Usar la razón equivocada divide o multiplica por diez todo el CCL histórico, y
con él toda la serie en dólares. Por eso `validate_ccl_continuity` verifica que
el CCL no dé un salto en la fecha del split: el tipo de cambio puede saltar por
una devaluación, pero no puede saltar el día exacto de una acción societaria de
una empresa. Si lo hace, es un error de datos, y el reporte lo dice en lugar de
seguir adelante.

### 3.3 Deflación por IPC

Como lectura complementaria se deflacta la serie nominal por el IPC de INDEC.
Los días posteriores al último IPC publicado quedan fuera del resultado: el IPC
se publica con rezago y extrapolarlo sería fabricar el dato más sensible del
cálculo.

## 4. Señales

Criterio de inclusión: solo indicadores con evidencia publicada de que su poder
predictivo sobrevive fuera de la muestra donde fueron descubiertos.

| Señal | Referencia | Regla |
|---|---|---|
| Momentum de series de tiempo 12-1 | Moskowitz, Ooi & Pedersen (2012), JFE 104(2) | Vota SÍ si el retorno de los últimos 12 meses, salteando el último, es positivo |
| Filtro de tendencia SMA 200 | Faber (2007), Journal of Wealth Management 9(4) | Vota SÍ si el precio está por encima de su media de 200 ruedas |
| Cercanía al máximo de 52 semanas | George & Hwang (2004), Journal of Finance 59(5) | Vota SÍ si el precio está a menos de 25% de su máximo anual |

Se saltea el mes más reciente en el momentum por el efecto de reversión de corto
plazo documentado en Jegadeesh (1990), Journal of Finance 45(3).

**Se decide comprar cuando al menos 2 de las 3 señales votan que sí.** Si no, la
posición va a efectivo. Es una estrategia *long-only*: nunca se vende en corto.

### Por qué pesos iguales y no optimizados

Porque optimizar los pesos sobre ~500 observaciones consume los grados de
libertad disponibles y produce una combinación ajustada al ruido de esta muestra
en particular. DeMiguel, Garlappi y Uppal, en *Optimal Versus Naive
Diversification* (Review of Financial Studies, 2009), muestran que la regla
ingenua 1/N supera consistentemente a los esquemas optimizados una vez
contabilizado el error de estimación.

### Qué quedó afuera y por qué

- **Cruces de MACD, RSI, estocástico, bandas de Bollinger con parámetros
  ajustados.** Park & Irwin (2007), *What Do We Know About the Profitability of
  Technical Analysis?* (Journal of Economic Surveys 21(4)), documentan que los
  resultados positivos en mercados desarrollados se desvanecen a partir de los
  años noventa y son atribuibles en buena medida al data snooping.
- **Ondas de Elliott, Fibonacci, patrones chartistas.** No producen reglas
  falsables, así que no son evaluables científicamente.
- **Cualquier parámetro elegido por su desempeño en estos datos.** Todos los
  valores usados son los de los papers originales.

## 5. Gestión de posición

- **Tamaño por volatilidad objetivo.** El peso se escala inverso a la
  volatilidad realizada de 63 ruedas, apuntando a 15% anualizado, con tope en 1
  (sin apalancamiento). Referencia: Moreira & Muir (2017), *Volatility-Managed
  Portfolios*, Journal of Finance 72(4).
- **Stop por ATR.** Salida si el precio cae 3 ATR desde el máximo de la posición.
  Tras un stop **no se reingresa** hasta que la señal de entrada se apague y se
  vuelva a encender: un stop que recompra al día siguiente no protege de nada y
  solo paga costos.

  Aclaración honesta: la evidencia académica sobre stops es ambigua. Reducen la
  caída máxima pero recortan ganancias al salir en retrocesos transitorios. Se
  incluye porque el perfil elegido es conservador, no porque esté probado que
  mejore el retorno esperado.

## 6. Backtest

Tres precauciones no negociables:

1. **Sin sesgo de anticipación.** La señal calculada con el cierre de `t` se
   ejecuta en `t+1`. Hay tests que lo verifican mecánicamente, incluido uno que
   construye una señal con visión del futuro y comprueba que el motor no le
   permite capitalizarla.
2. **Con costos.** Comisión, derechos de mercado y deslizamiento se descuentan en
   cada cambio de posición. Los valores por defecto para BYMA son sustancialmente
   mayores que los de EE.UU., porque lo son en la realidad. **Reemplazalos por el
   tarifario de tu comitente**: la rentabilidad de una estrategia de rotación
   semanal es muy sensible a este número.
3. **Rebalanceo semanal.** Coherente con el horizonte elegido de semanas a meses,
   y evita reaccionar a cada oscilación diaria.

## 7. Validación estadística

Esta es la parte que decide si el resultado vale algo.

### Deflated Sharpe Ratio

Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, Journal of Portfolio
Management 40(5). Ajusta el Sharpe por número de configuraciones probadas,
asimetría, curtosis y largo de la muestra. Responde a: *dado que probé N
variantes, ¿este Sharpe supera lo que esperaría del puro azar?*

**El parámetro `configuraciones_evaluadas` del archivo de configuración es
crítico y es responsabilidad tuya mantenerlo honesto.** Si probás veinte
variantes y declarás una, el DSR va a decir que tu resultado es significativo
cuando no lo es. El sistema no puede saber cuántas cosas probaste.

### Probability of Backtest Overfitting

Validación cruzada combinatoria simétrica (CSCV). Parte la historia en bloques,
prueba todas las formas de usar la mitad para elegir la mejor configuración y la
otra mitad para evaluarla, y mide con qué frecuencia la ganadora queda por debajo
de la mediana fuera de muestra. Un PBO por encima de 50% significa que el
proceso de selección está eligiendo ruido.

### Bootstrap estacionario

Politis & Romano (1994), Journal of the American Statistical Association 89(428).
Construye intervalos de confianza respetando la autocorrelación y la agrupación
de volatilidad de los retornos. Remuestrear día por día los destruiría y
produciría intervalos demasiado angostos.

**Si el intervalo de confianza del Sharpe incluye el cero, no se puede afirmar
que la estrategia tenga habilidad**, por atractivo que sea el retorno del
backtest.

### Walk-forward

Ventanas expansivas y estrictamente cronológicas: cada tramo de evaluación es
posterior a su tramo de entrenamiento. La validación cruzada aleatoria, habitual
en aprendizaje automático, es inválida con series temporales financieras porque
filtra información del futuro hacia el pasado.

## 8. Noticias: por qué un estudio de eventos y no un puntaje de sentimiento

Pedirle a un modelo de lenguaje que lea titulares y devuelva un número entre -1 y
+1 produce una cifra que parece un dato y no lo es: no tiene unidad, no tiene
error de medición, no es reproducible y no se puede auditar. Incorporarla a una
decisión de inversión es incorporar una opinión disfrazada de medición.

El sistema hace otra cosa:

1. **Recolecta eventos fechados de fuentes oficiales.** SEC EDGAR, formularios
   8-K (emisores de EE.UU.) y 6-K (emisores extranjeros, como YPF). Son
   obligatorios, están fechados con precisión y son gratuitos. Un evento mal
   fechado por un día destruye la medición.
2. **Los clasifica con reglas legibles.** Están en `news.py`, en texto plano, y
   cualquiera puede discutir por qué un hecho quedó en una categoría.
3. **Mide el efecto con retornos anormales.** Metodología de estudio de eventos:
   Fama, Fisher, Jensen & Roll (1969) y MacKinlay (1997), *Event Studies in
   Economics and Finance*, Journal of Economic Literature 35(1). Se estima el
   retorno normal del activo con un modelo de mercado ajustado sobre 250 ruedas
   previas al evento, y se mide cuánto se desvió el retorno efectivo. Esa
   desviación tiene un error estándar calculable, así que se puede decir si el
   movimiento fue estadísticamente distinguible del ruido habitual del papel.
4. **Agrega por categoría.** La pregunta que importa para operar no es si una
   noticia puntual movió el precio, sino si una CLASE de noticia lo mueve de
   forma sistemática. Con menos de 5 eventos por categoría no se reporta
   inferencia: sería numerología.

Esto distingue además el movimiento atribuible al mercado del atribuible a la
empresa: si el papel cayó porque cayó todo el mercado, eso no es un retorno
anormal y el método no lo cuenta como tal.

`news.sentiment_score()` existe y lanza `NotImplementedError` a propósito, con la
explicación. Hay un test que lo verifica, para que la decisión no se revierta sin
que alguien lo note.

## 9. Universo del NASDAQ

El top 10 por capitalización **no está escrito en el código**. Se resuelve contra
las tenencias publicadas del ETF QQQ y las capitalizaciones de Yahoo. Hay una
lista de respaldo fechada para el caso de que ambas fuentes fallen, y cuando se
usa, el reporte lo dice de forma visible. Un dato viejo usado a sabiendas es
aceptable; usado sin saberlo, no.
