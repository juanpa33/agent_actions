# Limitaciones

Lo que este sistema **no** puede hacer, dicho antes de que arriesgues dinero.

## 1. Dos años de datos no alcanzan para validar una estrategia

Dos años de datos diarios son unas 500 observaciones. Suena a mucho y no lo es.

Con una volatilidad anual del 30%, típica de NVDA, el error estándar del retorno
medio anual estimado sobre dos años ronda los 21 puntos porcentuales. Es decir:
una estrategia cuyo verdadero retorno esperado es 0% puede mostrar +20% en dos
años sin que haya nada raro. El ruido es más grande que casi cualquier efecto que
uno espere encontrar.

La función `min_track_record_length` calcula, para cada resultado, cuántas
observaciones harían falta para afirmar que el Sharpe es distinto de cero con 95%
de confianza. En la mayoría de los casos el número es **mayor que los datos
disponibles**, y el reporte lo dice.

**Recomendación concreta:** corré `--anios 10` para la validación estadística, y
usá la ventana de 2 años solo para describir el período reciente. Son dos
preguntas distintas y conviene no mezclarlas.

## 2. Sesgo de supervivencia en el top 10 del NASDAQ

Analizar las diez mayores empresas de hoy selecciona precisamente a las que
subieron. NVIDIA está en esa lista **porque** multiplicó su valor; no es una
muestra aleatoria del mercado.

Cualquier estrategia aplicada a ese conjunto va a lucir bien, y eso no dice nada
sobre cómo habría funcionado eligiendo en tiempo real, sin saber quién iba a
ganar. Un análisis sin este sesgo requeriría reconstruir la composición del
índice en cada fecha histórica (datos *point-in-time*), que no están disponibles
gratuitamente.

**Lectura correcta:** los resultados del top 10 describen cómo se habría
comportado la estrategia sobre estas empresas. No son una estimación de su
desempeño futuro sobre las empresas que serán grandes mañana.

## 3. Riesgos específicos de YPF que ninguna serie de precios contiene

YPF está expuesta a factores que no aparecen en dos años de cotizaciones:

- **Controles de cambio.** El acceso al CCL puede restringirse por regulación.
  El backtest asume que se puede entrar y salir libremente.
- **Regulación de precios internos** de combustibles, que afecta márgenes por
  decisión administrativa y no de mercado.
- **Litigios internacionales** derivados de la expropiación de 2012, con montos
  materiales respecto de la capitalización de la empresa.
- **Riesgo soberano.** La correlación con el riesgo país argentino se dispara
  justo en los momentos de estrés, que es cuando la diversificación haría falta.

Son riesgos de cola: no se manifiestan casi nunca, y cuando lo hacen dominan
todo lo demás. Un modelo entrenado sobre un período sin esos eventos los estima
implícitamente en cero.

## 4. La liquidez de BYMA no es la de Wall Street

El modelo de costos asume que se puede ejecutar al precio de cierre con un
deslizamiento fijo. En BYMA, con libros menos profundos, una orden grande mueve
el precio, y el deslizamiento real crece con el tamaño de la operación.

El backtest **no modela impacto de mercado**. Para montos chicos la aproximación
es razonable; para montos grandes, subestima los costos.

## 5. El régimen puede cambiar

Todo el andamiaje estadístico supone que el futuro se parece estadísticamente al
pasado. Cuando esa suposición se rompe —cambio de política monetaria, cambio
estructural en la demanda de chips de IA, cambio de gobierno— el modelo falla
exactamente cuando más importa.

Ni el momentum ni el filtro de tendencia protegen de un salto brusco: reaccionan
después del movimiento, por construcción.

## 6. Lo que el sistema no hace

- **No opera.** No hay conexión con ningún broker. Produce señales, no órdenes.
- **No predice precios.** Clasifica el estado actual como favorable o
  desfavorable según reglas explícitas. Eso no es un pronóstico.
- **No optimiza carteras.** No calcula asignaciones óptimas entre activos ni
  matrices de covarianza. Evalúa cada activo por separado.
- **No considera impuestos.** En Argentina, el tratamiento impositivo de la renta
  financiera puede cambiar sustancialmente el resultado neto.
- **No sabe nada de tu situación.** Horizonte, tolerancia real a perder,
  necesidades de liquidez, resto de tu patrimonio. Nada de eso entra al modelo, y
  todo eso importa más que la señal.

## 7. Dependencia de proveedores sin garantía de servicio

Yahoo Finance no ofrece SLA ni API pública documentada, y su cobertura de BYMA
es especialmente frágil. Stooq no cubre BYMA, así que **YPFD.BA se analiza sin
segunda fuente**: si Yahoo publica un dato malo para ese papel, nada lo detecta
salvo los chequeos de anomalías internos.

Si vas a decidir montos relevantes, contratá datos con garantía de servicio.

## 8. El Deflated Sharpe depende de tu honestidad

El parámetro `configuraciones_evaluadas` tiene que reflejar **todas** las
variantes que probaste en toda la investigación, incluidas las que descartaste.

El sistema no puede saber cuántas cosas probaste. Si probás treinta y declarás
una, el DSR va a decir que tu resultado es significativo cuando no lo es, y la
única persona perjudicada vas a ser vos.
