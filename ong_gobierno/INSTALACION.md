# Sistema de expedientes y gobierno — versión 1

Qué hace:

- **Expedientes** con número, tema, qué se vota, responsable y fecha de vencimiento.
- **Votación** de los 4 miembros: A favor, En contra o Abstención.
  - Se cierra con **3 votos iguales** (aprobado o rechazado), aunque falte uno.
  - Si votaron los 4 y nadie llegó a 3 (por ejemplo 2 a 2), **se vuelve a votar
    el viernes siguiente** (nueva ronda).
- **Mails automáticos** (todos los días a las 8):
  - al responsable, **2 días antes** del vencimiento;
  - a los 4, **el día anterior a la reunión**, con la lista de temas abiertos;
  - a los 4, cuando un tema se cierra o queda sin mayoría.
- **Historial** de todo lo que pasó (quién votó, cuándo, qué se creó).

La página tiene tres secciones:

- **Inicio**: explica cómo se usa, la regla de 3 de 4 con ejemplos y el camino
  de un expediente. Muestra cuántos votos te faltan dar.
- **Votar**: temas abiertos, aprobados que falta hacer (con el botón
  **"Ya lo hice"** para el responsable), alta de expedientes y archivo.
- **Tablero**: cuántos hay en cada estado, vencidos, tabla por responsable
  (incluye cuántos abrió cada uno) y detalle filtrable.

Estados del tablero (decidir y después hacer):

| Estado | Qué significa |
|---|---|
| Pendiente | Abierto, nadie votó todavía en esta ronda |
| En curso | La votación está en marcha |
| Terminado | Ya se decidió: aprobado o rechazado |
| Finalizado | Estaba aprobado y el responsable marcó "Ya lo hice" |

Los aprobados siguen recibiendo el aviso de vencimiento hasta que se marcan
como hechos.

Los datos quedan en una planilla de Google, compartida solo con ustedes cuatro.

## Instalación (una sola vez, unos 15 minutos)

La hace quien es dueña de la cuenta, desde una computadora.

1. Entrá a [sheets.new](https://sheets.new) y creá una planilla. Ponele de
   nombre, por ejemplo, **"ONG — Expedientes"**.
2. Menú **Extensiones → Apps Script**. Se abre el editor.
3. En el archivo `Código.gs` borrá todo y pegá el contenido de **`Codigo.gs`**.
4. Botón **+** → **HTML** → nombre **`Index`** (exacto, con mayúscula). Borrá
   lo que trae y pegá el contenido de **`Index.html`**.
5. Engranaje **Configuración del proyecto** → tildá **"Mostrar el archivo de
   manifiesto appsscript.json"**. Volvé al editor, abrí `appsscript.json` y
   reemplazalo por el contenido de **`appsscript.json`**.
6. Guardá (ícono del disquete). Arriba elegí la función **`instalar`** y tocá
   **Ejecutar**. Google va a pedir permisos: **Revisar permisos → tu cuenta →
   Configuración avanzada → Ir a … (no seguro) → Permitir**. Es tu propio
   programa: el aviso es normal.
7. Volvé a la planilla:
   - Hoja **Miembros**: poné nombre y mail (de Google) de los 4.
   - Hoja **Configuracion**: nombre de la ONG y hora de la reunión
     (`19:30` o `20:00`).
8. **Compartir** la planilla con los otros 3 mails, como **Editor**. Esto hace
   falta para que puedan votar desde la página.
9. En Apps Script: **Implementar → Nueva implementación → Aplicación web**.
   - Ejecutar como: **Usuario que accede a la aplicación web**.
   - Quién tiene acceso: **Cualquier usuario con cuenta de Google**.
   - **Implementar** y copiá la **URL** que termina en `/exec`.

Aunque cualquiera con esa URL puede abrir la página, solo ven y votan los mails
que están en la hoja **Miembros**. Al resto le aparece "no está en la lista".

## Ponerlo en Google Sites

1. En [sites.google.com](https://sites.google.com) creá un sitio (o abrí el de la ONG).
2. **Insertar → Insertar (Embed) → Por URL** y pegá la URL `/exec`.
   Agrandá el cuadro para que ocupe la página.
3. Agregá también un **Botón** con el texto *"Abrir en pantalla completa"* y la
   misma URL. Es útil en el celular, o si el cuadro pide iniciar sesión.
4. En **Compartir** del sitio, restringí quién puede verlo a ustedes cuatro.
5. **Publicar**.

**La primera vez** que cada miembro entra, Google le pide permiso. Conviene
abrir la URL `/exec` directamente (no desde el sitio), aceptar, y a partir de
ahí usar el sitio normalmente.

## Probar antes de usarlo en serio

1. Creen un expediente de prueba con vencimiento dentro de 2 días.
2. Votan 3 "A favor": tiene que quedar **Aprobado** y llegarles un mail a los 4.
3. Creen otro y voten 2 a favor y 2 en contra: tiene que quedar abierto con
   "se vuelve a votar el viernes".
4. El responsable del primero toca **"Ya lo hice"**: en el Tablero tiene que
   pasar a **Finalizado**.
5. En la planilla, menú **ONG → Mandar avisos de hoy ahora**: al responsable
   del primer expediente le tiene que llegar el recordatorio.
6. Si todo está bien, borren las filas de prueba de las hojas Expedientes,
   Votos e Historial. La numeración vuelve a empezar en 1.

## Cambios de código

Después de pegar una versión nueva: **Implementar → Gestionar
implementaciones → editar (lápiz) → Versión: Nueva → Implementar**. La URL no
cambia.

## Limitaciones de esta versión

- Como los 4 son editores de la planilla, alguien podría modificar a mano un
  voto en la hoja. El **Historial** registra los votos hechos desde la página,
  así que una diferencia se nota. Si hace falta, más adelante se puede blindar.
- Todavía **no** incluye: aportes y reportes, temario trimestral/mensual/semanal,
  adjuntar documentos, ni la parte de IA.

## Pruebas de las reglas

```bash
node ong_gobierno/pruebas/prueba_logica.js
```

Verifican la mayoría de 3 sobre 4, el empate que pasa al viernes siguiente, el
aviso 2 días antes, el recordatorio del día anterior a la reunión y los estados
del tablero.

Vista previa con datos inventados (se abre en cualquier navegador):
`pruebas/vista_previa.html`. Agregando `#tablero` o `#expedientes` al final de
la dirección se abre directo en esa sección.
