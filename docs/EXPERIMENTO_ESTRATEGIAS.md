# Experimento: ¿comprar en mínimos o seguir la tendencia?

## La pregunta

¿Conviene comprar cerca de los mínimos y vender cerca de los máximos (reversión
a la media), o comprar lo que viene subiendo (momentum)?

## Por qué no alcanza con mirar los datos de NVIDIA e YPF

Porque de cada acción tenemos **un solo camino histórico**. Si una estrategia le
ganó a la otra sobre NVIDIA en los últimos dos años, eso puede deberse a que es
mejor, o a que ese camino en particular la favoreció. Con una sola observación no
hay forma de distinguir las dos cosas.

La solución es la misma que usa un ensayo clínico: en vez de un paciente, muchos.
Se simulan cientos de caminos con propiedades matemáticas **conocidas de
antemano**, y se mide con qué frecuencia gana cada estrategia.

Esto no reemplaza al análisis de los datos reales. Responde una pregunta
distinta y complementaria: *dado un mercado que se comporta de tal manera, ¿qué
estrategia le conviene?* Después, mirando los datos reales, se ve a cuál de esos
comportamientos se parece cada activo.

## Método

- 200 caminos simulados por régimen, 1500 ruedas cada uno (~6 años).
- Tres regímenes: tendencial (deriva +25%/año), lateral (oscila sin tendencia,
  proceso de Ornstein-Uhlenbeck), decadencia (deriva −20%/año).
- Las tres estrategias con la misma vara: mismos costos (0,05% por operación),
  ejecución diferida a t+1, rebalanceo semanal.
- Semilla fija: el experimento es reproducible con
  `python scripts/experimento_estrategias.py --caminos 200`.

## Resultados

### Mercado con tendencia alcista sostenida

| Estrategia | Retorno mediano | Caída máx. | Sin operar |
|---|---|---|---|
| Comprar y mantener | **+173,6%** | −49,0% | 0% |
| Momentum + tendencia | +77,2% | −40,9% | 0% |
| Reversión a la media | +11,8% | −10,2% | **46%** |

**El hallazgo más importante de todo el experimento está en la última columna.**
En el 46% de los caminos, la estrategia de comprar en mínimos **nunca llegó a
comprar**. El precio jamás volvió a acercarse a su mínimo histórico, porque el
mínimo quedaba cada vez más lejos hacia atrás mientras el activo subía.

Esperar el mínimo histórico de una acción en tendencia alcista es esperar algo
que puede no volver a ocurrir nunca.

### Mercado lateral, sin tendencia

| Estrategia | Retorno mediano | Caída máx. |
|---|---|---|
| Reversión a la media | **+45,1%** | −29,5% |
| Comprar y mantener | −1,4% | −43,0% |
| Momentum + tendencia | −39,6% | −51,9% |

Acá la intuición de comprar barato **funciona, y muy bien**: le gana a comprar y
mantener en el 94% de los caminos. El momentum le gana a la reversión en el 0%
de los caminos — no en pocos: en ninguno.

Tiene sentido: en un mercado que oscila alrededor de un valor, la reversión a la
media es una propiedad real de la serie, no una esperanza. Y el momentum compra
sistemáticamente en los techos y vende en los pisos.

### Mercado en decadencia estructural

| Estrategia | Retorno mediano | Caída máx. |
|---|---|---|
| Momentum + tendencia | **−29,6%** | −46,0% |
| Reversión a la media | −74,1% | −82,5% |
| Comprar y mantener | −83,3% | −89,6% |

El escenario del cuchillo que cae. La reversión compra en cada nuevo mínimo, y
cada nuevo mínimo es seguido por otro más bajo: termina perdiendo 74% contra el
30% del momentum, que se va a efectivo cuando la tendencia se rompe.

Nótese que ninguna estrategia "gana" acá. La diferencia entre perder 30% y perder
74% es, de todos modos, enorme: de la primera se vuelve con +43%, de la segunda
hacen falta +285%.

## Conclusión

**Ninguna de las dos estrategias es mejor en abstracto. Cada una gana en un tipo
de mercado y pierde feo en el otro.**

| | Tendencial | Lateral | Decadencia |
|---|---|---|---|
| Momentum | segundo | **pésimo** | mejor |
| Reversión | **no opera** | mejor | pésimo |
| Comprar y mantener | **mejor** | intermedio | peor |

Tres lecturas que se desprenden:

1. **La pregunta "¿cuál estrategia es mejor?" está mal formulada.** La pregunta
   útil es "¿a qué régimen se parece este activo?", y esa se responde con datos.

2. **Comprar y mantener gana en el régimen tendencial**, que es donde vivieron
   las grandes tecnológicas de la última década. Ninguna estrategia activa le
   ganó ahí, ni siquiera el momentum. Complejidad no es lo mismo que ventaja.

3. **El riesgo de la reversión es asimétrico.** Cuando se equivoca, se equivoca
   comprando algo que se desploma, y pierde 74%. Cuando el momentum se equivoca,
   se equivoca quedándose afuera de una suba. Perderse una ganancia y perder el
   capital no son errores del mismo tamaño.

## Limitaciones de este experimento

- **Las series simuladas no son mercados reales.** Los mercados cambian de
  régimen, tienen colas más gordas que estas simulaciones y sus retornos no son
  independientes entre sí.
- **Los regímenes están puros.** Un activo real alterna entre los tres, y cuándo
  cambia solo se sabe después.
- **Los parámetros de la reversión (10% del mínimo, 95% del máximo) son
  razonables pero arbitrarios.** Otros valores dan otros resultados; no se
  optimizaron, justamente para no ajustarlos a este experimento.

## Cómo reproducirlo

```bash
python scripts/experimento_estrategias.py --caminos 200
```

La salida completa de la corrida documentada acá está en
[`resultado_experimento.txt`](resultado_experimento.txt).

Para la comparación sobre los datos reales de NVIDIA e YPF:

```bash
python scripts/run_analysis.py --solo NVDA,YPFD.BA --comparar
```

O desde GitHub: pestaña **Actions** → **Análisis de acciones** → **Run
workflow**, con la opción *Comparar estrategias* tildada.
