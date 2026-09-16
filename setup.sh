#!/usr/bin/env bash
# Instalación para Mac y Linux. Uso:  bash setup.sh
set -euo pipefail

echo "=============================================="
echo " Agente revisor de acciones - instalación"
echo "=============================================="
echo

# --- Python ---
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "FALTA PYTHON."
  echo
  echo "Descargalo de https://www.python.org/downloads/ (botón amarillo),"
  echo "instalalo, cerrá y volvé a abrir la Terminal, y corré de nuevo:"
  echo "    bash setup.sh"
  exit 1
fi

VERSION=$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])')
echo "Python encontrado: $VERSION"

if ! $PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo
  echo "Tu Python es $VERSION y hace falta 3.10 o superior."
  echo "Actualizalo desde https://www.python.org/downloads/"
  exit 1
fi

# --- Entorno aislado ---
# Se usa un entorno virtual para no tocar el Python del sistema: así nada de
# este proyecto puede romper otra cosa instalada en tu máquina.
echo
echo "Creando el entorno aislado (.venv) ..."
$PY -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "Instalando las librerías necesarias (puede tardar unos minutos) ..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

# --- Verificación ---
echo
echo "Verificando que todo funcione ..."
if python -m pytest tests/ -q; then
  echo
  echo "=============================================="
  echo " Listo. Todo instalado y verificado."
  echo "=============================================="
  echo
  echo "Para correr el análisis, copiá y pegá estas dos líneas:"
  echo
  echo "    source .venv/bin/activate"
  echo "    python scripts/run_analysis.py --solo NVDA,YPFD.BA"
  echo
  echo "El reporte queda en reports/reporte.md"
  echo "Para abrirlo:  open reports/reporte.md"
else
  echo
  echo "Los tests fallaron. NO corras el análisis todavía:"
  echo "si el motor no pasa sus propias verificaciones, su reporte no vale."
  echo "Mandame el texto de arriba y lo resolvemos."
  exit 1
fi
