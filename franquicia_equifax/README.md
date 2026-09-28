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
python extraer_prospeccion.py ~/Descargas/PROSPECCION.xlsx              # -> datos/prospeccion.json (opcional)
python generar_tablero.py                                                 # -> salida/tablero_virtus.html
```

Si existe `datos/prospeccion.json`, el tablero suma la pestaña **Prospección**.

Después abrís `salida/tablero_virtus.html` con doble clic.

## Informe mensual en PDF (un solo comando)

```bash
pip install openpyxl playwright
python -m playwright install chromium          # una sola vez
cp config/informe.ejemplo.json config/informe.json   # y completá las rutas de los Excel
python informe_mensual.py                      # -> salida/Informe_Virtus_<mes>.pdf (no envía nada)
python informe_mensual.py --enviar             # además lo manda por mail
```

El PDF es A4, en tema claro. Trae una portada con los números del mes, las dos pestañas
completas (Finanzas y Prospección), el mapa de calor de cada año y las explicaciones desplegadas.
También se puede exportar solo el PDF de un tablero ya generado: `python exportar_pdf.py`.

**Planillas desde Google Drive.** Si en `config/informe.json` completás `drive` con los IDs de las
planillas y `credenciales_google` con la clave de una cuenta de servicio, el informe baja solo la
versión vigente de cada planilla (Google Sheets se exporta a .xlsx). Hace falta `pip install google-auth`
y compartir las planillas con el mail de la cuenta de servicio como *Lector*. Los pasos están en
`descargar_drive.py`.

**Envío por mail.** Completá `envio` en `config/informe.json` (remitente, destinatarios, SMTP)
y definí la contraseña en la variable de entorno `VIRTUS_SMTP_PASSWORD`. Nunca va en el archivo.
Con Gmail, usá una *contraseña de aplicación*. Sin `--enviar` solo muestra una vista previa del mail.

**Una vez por mes, solo.** Cron (Linux/Mac) o Programador de tareas (Windows). Los pasos
están al principio de `informe_mensual.py`.

## Cada mes, cuando agregues la hoja nueva al Excel

1. La hoja nueva se detecta sola por su nombre (“Octubre (septiembre)” → liquidación de octubre) y aparece un aviso.
   Si el mes detectado es correcto, sumala a `HOJAS` en `extraer_datos.py` para dejarla fija.
2. Cargá la inflación del mes en `config/ipc.json`.
3. Corré `python informe_mensual.py`.

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
| **Pestaña Prospección** | Embudo llamada → atiende → interesado → alta, comparación por comercial y por mes, día a día, día de la semana (con intervalos de confianza), patrones, comparación con estudios de call centers y sugerencias |

El mapa de calor de gastos tiene un selector de año.

El botón **Pesos de hoy** ajusta todos los montos por inflación (IPC INDEC).

## Archivos

- `extraer_datos.py`: lee todas las hojas (que tienen formatos distintos), clasifica cada gasto en un rubro y verifica que cada mes cierre (disponible = gastos + resguardo + reparto).
- `generar_tablero.py`: calcula los indicadores y escribe los textos de análisis con esos números.
- `extraer_prospeccion.py`: lee la planilla de llamadas (un bloque por comercial y por mes) y descarta los bloques copiados de otra hoja.
- `prospeccion.py`: calcula el embudo, los patrones y los textos de la pestaña Prospección.
- `plantilla.html`: el diseño y los gráficos (SVG + JavaScript, sin librerías). Con `?pdf` en la URL se abre en modo impresión.
- `exportar_pdf.py`: imprime el tablero a PDF A4 con Chromium sin ventana.
- `informe_mensual.py`: todo el proceso del mes (Excel → tablero → PDF → mail).
- `config/informe.ejemplo.json`: modelo de configuración de rutas y envío.
- `config/ipc.json`: la inflación mensual. **Enero a julio de 2026 son una estimación**: reemplazala por el dato oficial.

## Privacidad

El `.gitignore` excluye el Excel, `datos/`, `salida/`, los PDF y `config/informe.json` (mails). Este repositorio es público y esos
archivos tienen montos por socio, así que no los subas. Los CBU y alias del Excel no se
copian al tablero.
