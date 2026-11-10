# Funcionamiento de una red neuronal Transformer — "Attention Is All You Need"

Simulador interactivo en HTML, pensado para chicos y chicas (aprox. 9 a 14 años), que muestra **paso a paso** cómo funciona un Transformer, la red neuronal presentada en el artículo *"Attention Is All You Need"* (Vaswani y otros, Google, 2017).

## Contenido de la carpeta

| Archivo | Para qué sirve |
|---|---|
| `simulador-transformer.html` | El simulador. Se abre con doble clic en cualquier navegador (Safari, Chrome, Firefox). No necesita internet ni instalar nada. |
| `guia-para-docentes.md` | Guía para la persona adulta que acompaña: recorrido de clase, actividad sin pantalla, glosario y respuestas. |
| `README.md` | Este archivo. |

## Cómo usarlo

1. Abrí `simulador-transformer.html` con doble clic.
2. Avanzá con **Siguiente →** o con las flechas del teclado.
3. En cada paso hay un recuadro amarillo (👉) que dice qué tocar.

## Los 6 pasos

1. **La idea.** La palabra "banco" cambia de sentido según la frase. El chico toca la palabra que da la pista y descubre qué es "prestar atención".
2. **Fichas.** La frase se corta en fichas y cada palabra recibe una "ficha de personaje" con 4 puntajes (embedding), más su número de lugar.
3. **Atención.** Cada palabra reparte 100 puntos entre las demás. Primero el chico **adivina** a cuál mira más y después lo comprueba.
4. **Mezcla.** Cada palabra recibe información de las que miró. Se compara su ficha antes y después.
5. **Predicción.** El modelo propone la palabra siguiente con su probabilidad. El chico elige y arma la frase de a una palabra.
6. **Repaso.** Resumen en 4 ideas y mini desafío de 3 preguntas.

Los detalles más técnicos (Pregunta, Etiqueta y Contenido, es decir Q, K y V; softmax; la fórmula; las cabezas de atención; las capas) están en las secciones plegables **"Para curiosos"**, para no cargar el recorrido principal.

## Simplificaciones (importante)

Es un **modelo de juguete**, pensado para enseñar:

- Usa **4 números** por palabra (el original usaba 512), con nombres que se pueden leer: ser vivo, acción, comida, lugar o cosa. En un modelo real esos números no tienen nombre y se aprenden solos.
- Las reglas de atención están **armadas a mano** para que los resultados se entiendan. En un Transformer real se aprenden entrenando con muchísimo texto.
- Trabaja con 4 frases de ejemplo y un diccionario de unas 25 palabras.
- La palabra siguiente sale de reglas simples, no de un entrenamiento real.

Lo que sí es igual al artículo: el orden de los pasos, la atención calculada con Pregunta y Etiqueta dividida por √d, el softmax que reparte el 100%, la posición calculada con seno y coseno, y la escritura de una ficha por vez.

## Fuentes consultadas

- Vaswani, A. y otros (2017). *Attention Is All You Need*. arXiv:1706.03762 — https://arxiv.org/abs/1706.03762
- IBM — *What is self-attention?* — https://www.ibm.com/think/topics/self-attention
- Codecademy — *Transformer architecture: self-attention mechanism* — https://www.codecademy.com/article/transformer-architecture-self-attention-mechanism
- USC CAIS++ — *Transformers* — https://caisplusplus.usc.edu/curriculum/neural-network-flavors/transformers
- Turner, R. (2023). *An Introduction to Transformers* — https://arxiv.org/pdf/2304.10557
