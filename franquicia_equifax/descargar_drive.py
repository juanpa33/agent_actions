"""Descarga las planillas de Google Drive como .xlsx, para no tener que pasar los Excel a mano.

Funciona con planillas de Google Sheets (se exportan a .xlsx) y con archivos .xlsx subidos a Drive.
Usa una *cuenta de servicio* de Google, que sirve para correr sin intervención (cron):

  1. En https://console.cloud.google.com creá un proyecto, habilitá la "Google Drive API"
     y creá una cuenta de servicio. Descargá su clave JSON.
  2. Compartí cada planilla con el mail de la cuenta de servicio (termina en
     @...iam.gserviceaccount.com) como *Lector*.
  3. En config/informe.json poné la ruta del JSON en "credenciales_google" y los IDs en "drive".

El ID de un archivo es la parte de la URL entre /d/ y /edit:
    https://docs.google.com/spreadsheets/d/<ID>/edit

Uso suelto:
    python descargar_drive.py <ID> salida.xlsx
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.googleapis.com/drive/v3/files/"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEETS = "application/vnd.google-apps.spreadsheet"


def token(credenciales: str) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    cred = service_account.Credentials.from_service_account_file(
        os.path.expanduser(credenciales), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    cred.refresh(Request())
    return cred.token


def _get(url: str, tk: str) -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tk}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def descargar(file_id: str, destino: str, tk: str) -> dict:
    meta = json.loads(_get(API + file_id + "?fields=name,mimeType,modifiedTime&supportsAllDrives=true", tk))
    if meta["mimeType"] == SHEETS:
        url = API + file_id + "/export?" + urllib.parse.urlencode({"mimeType": XLSX})
    else:
        url = API + file_id + "?alt=media&supportsAllDrives=true"
    Path(destino).parent.mkdir(parents=True, exist_ok=True)
    Path(destino).write_bytes(_get(url, tk))
    print(f"  Drive: '{meta['name']}' (modificado {meta['modifiedTime'][:10]}) -> {destino}")
    return meta


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cfg = json.loads((Path(__file__).parent / "config" / "informe.json").read_text())
    descargar(sys.argv[1], sys.argv[2], token(cfg["credenciales_google"]))
