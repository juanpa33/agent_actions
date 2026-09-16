# Lo que la simulación enseña

Este documento reúne lo que se aprende mirando cómo se comportan las tácticas de
posición, más allá del número final de una corrida.

## 1. El oráculo: el número que nunca vas a alcanzar

La simulación incluye una estrategia llamada ORÁCULO que compra en el mínimo
real y vende en el máximo real. Hace trampa a propósito: mira el gráfico
terminado.

Existe para una sola cosa. Cuando alguien dice *"si comprabas en el mínimo y
vendías en el máximo ganabas X"*, ese X es el número del oráculo, y es
**inalcanzable por definición**: el mínimo solo se reconoce cuando ya pasó.

La distancia entre el oráculo y la estrategia ejecutable es la medida honesta de
cuánto cuesta no ser adivino. Y no hay técnica que recupere esa diferencia.

## 2. "Esperar el mínimo" puede significar no comprar nunca

En el experimento sobre 200 caminos con tendencia alcista, la regla de comprar
cerca del mínimo **nunca llegó a abrir posición en el 46% de los casos**. El
precio jamás volvió cerca de su mínimo, porque el mínimo quedaba cada vez más
lejos hacia atrás mientras la acción subía.

No es un empate ni un resultado neutro: es no haber participado. El costo de
oportunidad no aparece en ningún estado de cuenta, pero es real.

**Consecuencia práctica:** si vas a usar una regla de mínimos, usá una ventana
móvil (mínimo de 52 semanas) en vez del mínimo histórico. El mínimo histórico de
una acción que sube es un punto que puede no volver jamás.

## 3. Vender de a pedazos: qué gana y qué pierde

La táctica de vender fracciones y recomprar en las bajas tiene ventajas y costos
concretos, y conviene verlos por separado.

**Gana:**
- Realiza ganancias sin quedarse afuera del todo.
- El núcleo que nunca se vende protege del peor escenario de la regla: que
  vendas y el activo siga subiendo sin vos.
- Reduce el arrepentimiento, que es un factor real: una táctica que no podés
  sostener emocionalmente no sirve por más que el backtest la bendiga.

**Pierde:**
- **Cada operación paga costos.** En BYMA el costo de ida y vuelta puede comerse
  buena parte de la ganancia de un movimiento chico.
- **Menos acciones significan menos dividendos.** En la simulación de ejemplo, el
  cobro trimestral bajó de USD 25 a USD 14 después de vender dos tramos. Es
  aritmética, pero se olvida.
- **Cada venta puede ser un hecho imponible.** No está modelado, y en Argentina
  puede cambiar el resultado neto de forma sustancial.

## 4. El comparador que importa no es el otro algoritmo

Es comprar y no hacer nada.

En el régimen de tendencia alcista del experimento, comprar y mantener le ganó a
las dos estrategias activas. Si una táctica no le gana a eso, no justifica su
complejidad, su riesgo operativo, sus costos ni tu tiempo.

La pregunta a hacerse frente a cualquier estrategia no es "¿gana plata?" sino
"¿gana más que no hacer nada?".

## 5. Los errores no son todos del mismo tamaño

- El momentum se equivoca **quedándose afuera de una suba**.
- La reversión se equivoca **comprando algo que se desploma**.

En el régimen de decadencia del experimento, la reversión terminó en −74% contra
−30% del momentum. De perder 30% se vuelve con +43%; de perder 74% hacen falta
**+285%**. Perderse una ganancia y perder capital no son errores equivalentes, y
cualquier evaluación que los trate igual está mal planteada.

## 6. Dividendos: verificá antes de contar con ellos

Verificado al momento de escribir esto:

- **YPF no paga dividendos.** Rendimiento 0,00%. Los últimos pagos fueron en 2016
  y 2017, y no hay política formal de dividendos.
- **NVIDIA paga USD 1,00 por acción al año**, un rendimiento de 0,46%. Sobre 100
  acciones, unos USD 100 anuales.

Una estrategia de dividendos sobre estos dos papeles no tiene de dónde agarrarse.
Si querés esa fuente de retorno, hay que buscar otras empresas, y eso cambia
todo el análisis.

Y una advertencia sobre el rendimiento por dividendo: como se calcula
`dividendo / precio`, **sube cuando el precio se derrumba**. Un rendimiento
llamativamente alto suele señalar una empresa en problemas, justo antes de que
recorte el dividendo.

## 7. Detalle técnico que evita un error de medición

La simulación usa precios **sin ajustar por dividendos**, a propósito.

Los gráficos y backtests suelen usar precios ajustados, donde el dividendo ya
está descontado del precio histórico. Si sobre esos precios además sumaras los
dividendos como plata que entra, los estarías contando dos veces.

Por eso los precios de la simulación no coinciden con los del gráfico ajustado.
No es un error: es la única forma de tratar al dividendo como lo que es, plata
que llega a la cuenta en una fecha concreta.

## Cómo correrlo

```bash
python scripts/simular_acciones.py --ticker NVDA --acciones 100 --anios 2
python scripts/simular_acciones.py --ticker NVDA --acciones 100 --anios 10
```

O desde GitHub: **Actions → Análisis de acciones → Run workflow**, con
*Simular 100 acciones en dinero* tildado.
