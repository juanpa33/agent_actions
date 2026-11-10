# Guía para docentes, madres y padres

**Simulador: Funcionamiento de una red neuronal Transformer — "Attention Is All You Need"**

- **Edad sugerida:** 9 a 14 años. Las secciones "Para curiosos" son opcionales y apuntan a los más grandes.
- **Duración:** entre 40 y 60 minutos.
- **Qué hace falta:** una computadora o tablet con navegador. No necesita internet.

---

## Objetivos

Al terminar, se espera que los chicos puedan:

1. Explicar que una computadora convierte las palabras en **números** para poder trabajar con ellas.
2. Contar con sus palabras qué es la **atención**: cada palabra decide a cuáles otras mirar más.
3. Entender que estos modelos escriben **una palabra por vez**, adivinando la más probable.
4. Reconocer que la IA **aprende de ejemplos** y que puede equivocarse.

## La idea principal, en una frase

> Para entender una palabra, hay que mirar a las otras palabras de la frase. El Transformer aprende **a cuáles mirar**.

Ejemplo para la pizarra: en *"el gato come pescado"*, para entender **come** hay que saber **quién** come (gato) y **qué** come (pescado). En el paso 3 del simulador se ve que "come" le presta más atención justamente a esas dos palabras.

---

## Recorrido sugerido

| Momento | Paso | Qué hacer | Pregunta para el grupo |
|---|---|---|---|
| Arranque (5 min) | 1 | Tocar la palabra que da la pista de "banco". | ¿Se les ocurren otras palabras con dos significados? |
| Las palabras se vuelven números (10 min) | 2 | Comparar las fichas de "gato" y "perro". | ¿Por qué tendrán puntajes parecidos? |
| Adivinar la atención (15 min) | 3 | Adivinar antes de tocar, con cada palabra. | ¿A quién mira "come"? ¿Y "el"? ¿Por qué? |
| El antes y el después (5 min) | 4 | Mirar la barra amarilla. | ¿Qué aprendió "come" de "gato"? |
| Escribir de a una (10 min) | 5 | Armar frases eligiendo palabras, incluso las menos probables. | ¿La frase tiene sentido? ¿Por qué a veces no? |
| Cierre (5 min) | 6 | Hacer el mini desafío. | ¿Cómo se lo explicarían a un amigo? |

## Actividad desconectada: "La feria de los carteles"

Sirve para entender la atención con el cuerpo, sin pantalla. Corresponde a la sección "Para curiosos" del paso 3 (Pregunta, Etiqueta y Contenido).

1. Cada chico es una palabra de la frase y recibe tres papelitos:
   - 🔴 **Pregunta** (lo que busca). Por ejemplo, "come" busca "¿quién?" y "¿qué comida?".
   - 🔵 **Etiqueta** (lo que ofrece, colgada al cuello). Por ejemplo, "gato" ofrece "soy un ser vivo".
   - 🟢 **Contenido** (un dato que comparte). Por ejemplo, "tengo bigotes y maúllo".
2. Cada uno lee las etiquetas de los demás y reparte **10 porotos** (su 100% de atención) entre las palabras que más le sirven.
3. Cada uno anota los contenidos que "recibió", dando más peso a quien le dio más porotos. Eso es la **mezcla** del paso 4.
4. Para cerrar, comparar con lo que muestra el simulador en el paso 3.

## Glosario simple

| Palabra | Explicación para chicos |
|---|---|
| **Red neuronal** | Un programa formado por muchas "neuronas" de números conectadas, que aprende con ejemplos. |
| **Transformer** | Un tipo de red neuronal que lee todas las palabras a la vez y usa la atención. |
| **Token / ficha** | Un pedacito de texto: una palabra o parte de una palabra. |
| **Embedding** | La lista de números que representa a una palabra, como una ficha de personaje. |
| **Codificación posicional** | Números extra que le dicen al modelo en qué lugar está cada palabra. |
| **Query (Q) / Pregunta** | Lo que una palabra está buscando. |
| **Key (K) / Etiqueta** | Lo que una palabra ofrece a las demás. |
| **Value (V) / Contenido** | La información que una palabra comparte. |
| **Producto punto** | Multiplicar dos listas número por número y sumar todo. Mide cuánto "combinan". |
| **Softmax** | Convierte puntajes en porcentajes que suman 100%. |
| **Atención** | Cuánto mira cada palabra a cada una de las otras. |
| **Multi-cabeza** | Varias atenciones al mismo tiempo, cada una mirando algo distinto. |
| **Capa** | Un "piso" del modelo: atención más una pequeña red que piensa. |
| **Codificador / Decodificador** | La parte que lee y la parte que escribe, en el modelo original. |

## Respuestas del mini desafío (paso 6)

1. Cada palabra mira a las demás.
2. 100.
3. Una ficha por vez.

## Para conversar: uso responsable de la IA

- Estos modelos **adivinan** la palabra más probable, así que pueden decir cosas falsas con mucha seguridad. Siempre hay que chequear.
- Aprenden de textos escritos por personas, así que pueden copiar errores o prejuicios.
- No conviene compartir datos personales con un asistente de IA.

## Aclaración sobre el simulador

Es una versión simplificada: 4 números por palabra en lugar de 512, reglas armadas a mano en lugar de aprendidas y solo 4 frases de ejemplo. Los pasos y la fórmula de atención sí son los del artículo original. Los detalles están en el `README.md`.

## Para seguir aprendiendo (adultos)

- Artículo original: https://arxiv.org/abs/1706.03762
- IBM, *What is self-attention?*: https://www.ibm.com/think/topics/self-attention
- Turner, *An Introduction to Transformers*: https://arxiv.org/pdf/2304.10557
