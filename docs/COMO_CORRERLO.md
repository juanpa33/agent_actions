# Cómo correr el análisis

Dos caminos. El primero no requiere instalar nada.

---

## Camino 1: en GitHub, sin instalar nada

### La primera vez

1. Entrá a tu repositorio:
   **https://github.com/juanpa33/agent_actions**

2. Arriba, hacé clic en la pestaña **Actions**.

3. Si aparece un cartel que dice *"Workflows aren't being run on this forked
   repository"* o te pide habilitar, hacé clic en el botón verde
   **I understand my workflows, go ahead and enable them**.

4. En la columna izquierda, hacé clic en **Análisis de acciones**.

5. A la derecha aparece un botón gris que dice **Run workflow**. Hacé clic.

6. Se abre un panel con cuatro cosas para elegir:

   | Campo | Qué poner |
   |---|---|
   | **Use workflow from** | Elegí la rama `claude/stock-review-agent-agct6q` |
   | **Qué analizar** | `NVDA + YPF` |
   | **Años de historia** | `2` para empezar |
   | **Incluir estudio de eventos** | dejalo tildado |

7. Hacé clic en el botón verde **Run workflow**.

8. Esperá. Aparece una línea nueva con un círculo amarillo girando. Tarda entre
   2 y 5 minutos. Cuando termina bien, el círculo se pone verde con un tilde.

### Bajar el reporte

1. Hacé clic en la línea de la corrida que terminó.
2. Bajá hasta el final de la página, hasta la sección **Artifacts**.
3. Hacé clic en **reporte-acciones-1** (el número cambia en cada corrida).
   Se descarga un archivo `.zip`.
4. Abrilo. Adentro está **`reporte.md`**, que podés abrir con cualquier editor
   de texto, o arrastrar a una ventana del navegador.

### Las próximas veces

Directo al paso 4: Actions → Análisis de acciones → Run workflow.

### Si sale mal (círculo rojo)

No entres en pánico: el sistema está hecho para fallar en voz alta antes que
inventar datos. La causa más frecuente es que Yahoo Finance limitó los pedidos
desde los servidores de GitHub.

1. Esperá diez minutos y volvé a correrlo. Suele alcanzar.
2. Si vuelve a fallar, en **Artifacts** vas a encontrar
   `log_de_ejecucion.txt` con el error exacto. Pasámelo y lo miramos.
3. Como alternativa, corrélo en tu computadora con el Camino 2: desde tu
   conexión de internet normal no suele haber límites.

---

## Camino 2: en tu Mac

### La primera vez

Abrí la aplicación **Terminal** (apretá `Cmd + Espacio`, escribí "Terminal" y
Enter). Pegá esto y apretá Enter:

```bash
cd ~/Desktop
git clone https://github.com/juanpa33/agent_actions.git
cd agent_actions
git checkout claude/stock-review-agent-agct6q
bash setup.sh
```

`setup.sh` verifica que tengas Python, arma un entorno aislado, instala lo que
hace falta y corre los tests. Si algo falta, te dice exactamente qué.

Si te avisa que no tenés Python, instalalo desde
**https://www.python.org/downloads/** (el botón amarillo grande) y volvé a
correr `bash setup.sh`.

### Correr el análisis

Cada vez que quieras el reporte actualizado:

```bash
cd ~/Desktop/agent_actions
source .venv/bin/activate
python scripts/run_analysis.py --solo NVDA,YPFD.BA
```

El reporte queda en `reports/reporte.md`. Para abrirlo:

```bash
open reports/reporte.md
```

### Variantes útiles

```bash
# Validación estadística en serio: 10 años en vez de 2
python scripts/run_analysis.py --solo NVDA,YPFD.BA --anios 10

# Agregar el top 10 del NASDAQ (tarda bastante más)
python scripts/run_analysis.py

# Más rápido: sin consultar SEC EDGAR
python scripts/run_analysis.py --solo NVDA,YPFD.BA --sin-eventos
```

---

## Qué mirar cuando tengas el reporte

Leelo en este orden:

1. **Advertencias de esta corrida** (arriba de todo). Si dice que el CCL saltó
   en la fecha del split, **parate ahí**: la serie de YPF en dólares no es
   confiable y hay que resolverlo antes de mirar nada más.

2. **Resumen de señales vigentes**. La columna `Decisión` dice
   `COMPRAR/MANTENER` o `EFECTIVO` para cada papel. `EFECTIVO` significa no
   tener el papel; nunca significa vender en corto.

3. **Validez estadística**. Esta es la tabla que decide si el resto vale algo:

   - **IC 95%**: si dice *incluye 0*, no se puede afirmar que la estrategia
     funcione. El retorno que muestre el backtest es compatible con la suerte.
   - **DSR**: si es menor a 0,95, la columna Veredicto dice `NO PASA`. Tomá la
     señal como una observación interesante, no como evidencia.

4. **Limitaciones** (al final). Sobre todo la parte de que dos años no alcanzan.

Lo más probable con dos años de datos es que el DSR dé `NO PASA` en casi todo.
**Eso no es un defecto del sistema: es el resultado honesto.** Un programa que
te diera certezas con 500 observaciones te estaría mintiendo.
