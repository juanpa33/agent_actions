# Funcionamiento de una red neuronal Transformer — "Attention Is All You Need"

Simulador interactivo en HTML, pensado para chicos y chicas (aprox. 10 a 15 años), que muestra **paso a paso** cómo funciona un Transformer, la red neuronal presentada en el artículo *"Attention Is All You Need"* (Vaswani y otros, Google, 2017).

## Contenido de la carpeta

| Archivo | Para qué sirve |
|---|---|
| `simulador-transformer.html` | El simulador. Se abre con doble clic en cualquier navegador (Safari, Chrome, Firefox). No necesita internet ni instalar nada. |
| `guia-para-docentes.md` | Guía para la persona adulta que acompaña: cómo usarlo en clase, actividades, glosario y preguntas. |
| `README.md` | Este archivo. |

## Cómo usarlo

1. Abrí `simulador-transformer.html` con doble clic.
2. Escribí una frase corta (por ejemplo, *"el gato come pescado"*) o elegí uno de los ejemplos.
3. Avanzá con **Siguiente →** o con las flechas del teclado. También podés saltar a cualquier paso desde la barra de arriba.
4. En cada paso, tocá las palabras para ver qué hace el modelo con cada una.

## Los 11 pasos del simulador

0. **Inicio**: qué es un Transformer y de dónde viene la idea de la "atención".
1. **Fichas (tokenización)**: la frase se corta en tokens.
2. **Números (embeddings)**: cada palabra pasa a ser una lista de números.
3. **Posición**: se suman ondas seno/coseno para que el modelo sepa el orden.
4. **Q · K · V**: cada palabra arma su Pregunta, su Etiqueta y su Contenido.
5. **Puntajes**: producto punto entre Preguntas y Etiquetas, dividido por √d.
6. **Atención (softmax)**: los puntajes se vuelven porcentajes que suman 100%.
7. **Mezcla**: cada palabra combina los Contenidos según esos porcentajes. Acá aparece la fórmula del artículo: `softmax(Q·Kᵀ/√d)·V`.
8. **Multi-cabeza**: varias "cabezas" de atención miran cosas distintas.
9. **Capas**: atención + red feed-forward, apiladas muchas veces (6 en el modelo original).
10. **Predicción**: se calcula la probabilidad de la próxima palabra y se va escribiendo de a una.
11. **Resumen y mini desafío**.

## Simplificaciones (importante)

Es un **modelo de juguete**, pensado para enseñar:

- Usa listas de **4 números** por palabra (el original usaba 512), con características que se pueden leer: 🐾 ser vivo, 🏃 acción, 🍎 comida, 🏠 lugar/cosa. En un modelo real esas características no tienen nombre: el modelo las aprende solo.
- Las matrices Q, K y V están **armadas a mano** para que los resultados se entiendan. En un Transformer real se aprenden entrenando con muchísimo texto.
- El diccionario es chiquito, de unas 40 palabras. Las palabras que no conoce reciben números al azar, aunque siempre los mismos para la misma palabra.
- La predicción de la próxima palabra usa reglas simples y no un entrenamiento real.

Lo que sí es igual al artículo: el orden de los pasos, la fórmula de atención con la división por √d, el softmax, la codificación posicional con seno y coseno, la idea de varias cabezas y de capas apiladas, y la generación de una ficha por vez.

## Fuentes consultadas

- Vaswani, A. y otros (2017). *Attention Is All You Need*. arXiv:1706.03762 — https://arxiv.org/abs/1706.03762
- IBM — *What is self-attention?* — https://www.ibm.com/think/topics/self-attention
- Codecademy — *Transformer architecture: self-attention mechanism* — https://www.codecademy.com/article/transformer-architecture-self-attention-mechanism
- USC CAIS++ — *Transformers* — https://caisplusplus.usc.edu/curriculum/neural-network-flavors/transformers
- Turner, R. (2023). *An Introduction to Transformers* — https://arxiv.org/pdf/2304.10557
- Slides del curso CS546 (Univ. de Illinois) sobre Vaswani y otros — https://courses.grainger.illinois.edu/cs546/sp2018/Slides/Mar15_Vaswani.pdf
