# Guía para docentes, madres y padres

**Simulador: Funcionamiento de una red neuronal Transformer — "Attention Is All You Need"**

- **Edad sugerida:** 10 a 15 años. Con chicos de 8 o 9 años conviene recorrer solo los pasos 0, 1, 6 y 10.
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

Ejemplo para la pizarra: en *"el gato come pescado"*, para entender **come** hay que saber **quién** come (gato) y **qué** come (pescado). En el paso 6 del simulador se ve que "come" le presta más atención justamente a esas dos palabras.

---

## Recorrido sugerido

| Momento | Pasos | Qué hacer | Pregunta para el grupo |
|---|---|---|---|
| Arranque (5 min) | 0 | Leer la presentación de "Atento". | ¿Alguna vez usaron un asistente que escribe o traduce? |
| Las palabras se vuelven números (10 min) | 1, 2 | Probar con palabras parecidas: "gato" y "perro". | ¿Por qué tendrán números parecidos? |
| El orden importa (5 min) | 3 | Comparar "el gato come pescado" con "el pescado come gato". | ¿Significan lo mismo? ¿Cómo se da cuenta la computadora? |
| La feria de ciencias (10 min) | 4, 5 | Hacer la dinámica de los carteles (ver abajo). | ¿Qué busca un verbo? ¿Qué ofrece un sustantivo? |
| La torta de la atención (10 min) | 6, 7 | Tocar cada palabra y mirar las líneas. | ¿A quién mira "come"? ¿Y "el"? |
| Detectives y edificio (5 min) | 8, 9 | Cambiar de cabeza y comparar. | ¿Por qué servirá tener varios detectives? |
| Escribir solo (10 min) | 10, 11 | Agregar palabras y hacer el mini desafío. | ¿La frase que armó tiene sentido? ¿Por qué a veces no? |

## Actividad desconectada: "La feria de los carteles"

Sirve para entender Q, K y V con el cuerpo, sin pantalla.

1. Cada chico es una palabra de la frase y recibe tres papelitos:
   - 🔴 **Pregunta** (lo que busca). Por ejemplo, "come" busca "¿quién?" y "¿qué comida?".
   - 🔵 **Etiqueta** (lo que ofrece, colgada al cuello). Por ejemplo, "gato" ofrece "soy un ser vivo".
   - 🟢 **Contenido** (un dato que comparte). Por ejemplo, "tengo bigotes y maúllo".
2. Cada uno lee las etiquetas de los demás y reparte **10 porotos** (su 100% de atención) entre las palabras que más le sirven.
3. Cada uno anota los contenidos que "recibió", dando más peso a quien le dio más porotos. Eso es el **licuado** del paso 7.
4. Para cerrar, comparar con lo que muestra el simulador en el paso 6.

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

## Respuestas del mini desafío (paso 11)

1. Para saber el orden de las palabras.
2. Lo que la palabra está buscando.
3. 100%.
4. Una ficha por vez.

## Para conversar: uso responsable de la IA

- Estos modelos **adivinan** la palabra más probable, así que pueden decir cosas falsas con mucha seguridad. Siempre hay que chequear.
- Aprenden de textos escritos por personas, así que pueden copiar errores o prejuicios.
- No conviene compartir datos personales con un asistente de IA.

## Aclaración sobre el simulador

Es una versión simplificada: 4 números por palabra en lugar de 512, matrices armadas a mano en lugar de aprendidas y un diccionario chiquito. Los pasos y la fórmula de atención sí son los del artículo original. Los detalles están en el `README.md`.

## Para seguir aprendiendo (adultos)

- Artículo original: https://arxiv.org/abs/1706.03762
- IBM, *What is self-attention?*: https://www.ibm.com/think/topics/self-attention
- Turner, *An Introduction to Transformers*: https://arxiv.org/pdf/2304.10557
