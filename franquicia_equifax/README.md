# Tablero de control: franquicia Equifax Cuyo (Virtus)

Convierte el Excel mensual de liquidaciones (`Calculo_transferencias_Virtus.xlsx`)
en un tablero HTML, pensado para explicar el negocio paso a paso, y en un análisis
con ideas de optimización.

Todo corre en tu computadora. El tablero es **un solo archivo HTML sin dependencias
externas**, así que funciona sin internet y no manda datos a ningún lado.

## Cómo lo corro

```bash
pip install openpyxl
cd franquicia_equifax
python extraer_datos.py ~/Descargas/Calculo_transferencias_Virtus.xlsx   # -> datos/virtus_mensual.json
python generar_tablero.py                                                 # -> salida/tablero_virtus.html
```

Después abrís `salida/tablero_virtus.html` con doble clic.

Cada mes, cuando agregues la hoja nueva al Excel:

1. Sumá una línea en `HOJAS` dentro de `extraer_datos.py`, con el nombre de la hoja, el mes de liquidación y el mes de ventas.
2. Cargá la inflación del mes en `config/ipc.json`.
3. Volvé a correr los dos comandos.

## Qué hay en el tablero

| Sección | Qué responde |
|---|---|
| Resumen | Cuánto se cobró, gastó y repartió en 12 meses; punto de equilibrio; crecimiento real; variabilidad |
| Un mes paso a paso | Cascada desde la comisión hasta la transferencia a cada socio, para cualquier mes |
| Evolución | Adónde fue cada peso, mes a mes (gastos / resguardo / socios) |
| Punto de equilibrio | Apalancamiento operativo: gastos como % del ingreso según el tamaño del mes |
| Costos | Ranking de rubros y mapa de calor rubro × mes, con el detalle de cada concepto |
| Socios | Reparto mensual, acumulado y cambios de porcentaje |
| Conclusiones, ideas y comparación | Análisis con los números actualizados, contra negocios parecidos |

El botón **Pesos de hoy** ajusta todos los montos por inflación (IPC INDEC).

## Archivos

- `extraer_datos.py`: lee todas las hojas (que tienen formatos distintos), clasifica cada gasto en un rubro y verifica que cada mes cierre (disponible = gastos + resguardo + reparto).
- `generar_tablero.py`: calcula los indicadores y escribe los textos de análisis con esos números.
- `plantilla.html`: el diseño y los gráficos (SVG + JavaScript, sin librerías).
- `config/ipc.json`: la inflación mensual. **Enero a julio de 2026 son una estimación**: reemplazala por el dato oficial.

## Privacidad

El `.gitignore` excluye el Excel, `datos/` y `salida/`. Este repositorio es público y esos
archivos tienen montos por socio, así que no los subas. Los CBU y alias del Excel no se
copian al tablero.
