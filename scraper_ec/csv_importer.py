"""Importer del CSV export del portal Ppless v2 (Asamblea Nacional Ecuador).

Formato del CSV (descargado clickeando el botón "CSV" en la página
`https://proyectosdeley.asambleanacional.gob.ec/report`):

Columnas (separadas por ';', valores entre comillas, nulls como 'null'):
  1. Proyecto de Ley            (título)
  2. Fecha Documento            (YYYY-MM-DD)
  3. Fecha de Presentación      (YYYY-MM-DD)
  4. N. Trámite                 (numérico o alfanumérico, identificador único)
  5. N. Documento               (usualmente igual a N. Trámite)
  6. Estado                     (texto libre)
  7. Comisión asignada          (texto, "No Asignado" si no hay)
  8. Fecha Calificación CAL     (YYYY-MM-DD o 'null')
  9. Proponentes                ("NAME1(TIPO1)/ NAME2(TIPO2)/ ...")

Incluye también un diccionario `COMISION_TYPOS` para corregir errores
ortográficos conocidos en el campo `Comisión asignada` del portal oficial.
Se aplica automáticamente al importar.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterator


# Correcciones a errores ortográficos conocidos del portal oficial.
# Las claves son los strings TAL CUAL aparecen en el CSV; los valores son la
# versión corregida que se persiste en la DB. Agregar entradas nuevas a
# medida que aparezcan typos.
COMISION_TYPOS: dict[str, str] = {
    "Comisión de Bodiversidad y Recursos Naturales":
        "Comisión de Biodiversidad y Recursos Naturales",
}


def fix_comision_typo(nombre: str | None) -> str | None:
    """Aplica COMISION_TYPOS si el nombre matchea exacto. Caso contrario,
    devuelve el nombre sin cambios."""
    if not nombre:
        return nombre
    return COMISION_TYPOS.get(nombre, nombre)


# Mapeo de header del CSV → key interno usado por db.upsert_from_csv_row
HEADER_MAP = {
    "Proyecto de Ley": "titulo",
    "Fecha Documento": "fec_documento",
    "Fecha de Presentación": "fec_presentacion",
    "N. Trámite": "n_tramite",
    "N. Documento": "n_documento",
    "Estado": "estado",
    "Comisión asignada": "comision_asignada",
    "Fecha Calificación CAL": "fec_calificacion_cal",
    "Proponentes": "proponentes_raw",
}


# Regex para "NAME(TIPO)" — captura el contenido del paréntesis al final.
# Tolerante a espacios alrededor del paréntesis.
_PROP_RE = re.compile(r"^\s*(?P<nombre>.+?)\s*\(\s*(?P<tipo>[^)]+)\s*\)\s*$")


def _clean_value(v: str | None) -> str | None:
    """Normaliza un valor del CSV: 'null' literal → None, strip whitespace."""
    if v is None:
        return None
    v = v.strip()
    if not v or v.lower() == "null":
        return None
    return v


def parse_proponentes(raw: str | None) -> list[dict]:
    """Parsea el campo Proponentes del CSV en una lista de {nombre, tipo}.

    Formato típico: "DURÁN AGUILAR LILIANA(ASAMBLEÍSTA)/ CORREA GONZALEZ(ASAMBLEÍSTA)"
    Separador: '/'. Cada item tiene "NAME(TIPO)". Si el TIPO no está entre
    paréntesis, se queda en None.
    """
    if not raw:
        return []
    out: list[dict] = []
    for chunk in raw.split("/"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _PROP_RE.match(chunk)
        if m:
            out.append({"nombre": m.group("nombre").strip(), "tipo": m.group("tipo").strip()})
        else:
            out.append({"nombre": chunk, "tipo": None})
    return out


def tipo_principal(proponentes: list[dict]) -> str | None:
    """Devuelve el tipo del primer proponente (firmante principal).

    En la práctica suele ser ASAMBLEÍSTA, EJECUTIVO, INSTITUTO DE SEGURIDAD
    SOCIAL DE LAS FUERZAS ARMADAS, PROCURADURÍA GENERAL DEL ESTADO, etc.
    """
    if not proponentes:
        return None
    return proponentes[0].get("tipo")


def iter_rows(csv_path: str | Path) -> Iterator[dict]:
    """Yield dicts listos para `Database.upsert_from_csv_row`.

    Maneja:
      - encoding utf-8 (con BOM o sin)
      - separador ';'
      - quoting con '"'
      - normalización de 'null' → None
      - split de proponentes en lista estructurada
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=";", quotechar='"')
        if not reader.fieldnames:
            raise ValueError(f"CSV sin headers: {path}")

        # Validación: faltan columnas esperadas?
        expected = set(HEADER_MAP.keys())
        actual = set(reader.fieldnames)
        missing = expected - actual
        if missing:
            raise ValueError(
                f"CSV con columnas faltantes: {missing}.\n"
                f"Headers encontrados: {reader.fieldnames}"
            )

        for raw_row in reader:
            row: dict = {}
            for header, key in HEADER_MAP.items():
                row[key] = _clean_value(raw_row.get(header))

            # Validación mínima: n_tramite, titulo, estado, fec_presentacion requeridos
            if not row.get("n_tramite") or not row.get("titulo"):
                continue  # fila inválida, saltar
            if not row.get("fec_presentacion"):
                continue
            row.setdefault("estado", "PROYECTO PRESENTADO")

            # Aplicar correcciones de typos conocidos del portal
            row["comision_asignada"] = fix_comision_typo(row.get("comision_asignada"))

            # Split proponentes
            propon = parse_proponentes(row.get("proponentes_raw"))
            row["proponentes_lista"] = propon
            row["tipo_proponente"] = tipo_principal(propon)

            row["periodo"] = "2025-2029"

            yield row


def import_csv(csv_path: str | Path, db) -> dict:
    """Importa el CSV completo a la DB. Devuelve estadísticas del import.

    Args:
        csv_path: ruta al CSV
        db: instancia de scraper_ec.db.Database (ya inicializada)

    Returns:
        {"vistos": int, "nuevos": int, "actualizados": int, "errores": int, "cambios_por_campo": {...}}
    """
    from scraper_ec.db import now_iso

    run_id = db.start_run(csv_source=str(Path(csv_path).resolve()))
    now = now_iso()
    vistos = nuevos = actualizados = errores = 0
    cambios_por_campo: dict[str, int] = {}

    try:
        for row in iter_rows(csv_path):
            vistos += 1
            try:
                is_new, changed = db.upsert_from_csv_row(row, now)
                if is_new:
                    nuevos += 1
                elif changed:
                    actualizados += 1
                for c in changed:
                    if c != "__new__":
                        cambios_por_campo[c] = cambios_por_campo.get(c, 0) + 1

                # Clasificación temática (solo con título — CSV no trae sumilla)
                if is_new or "titulo" in changed:
                    db.classify_and_save(row["n_tramite"], row["titulo"])
            except Exception as e:
                errores += 1
                print(f"[error] proyecto {row.get('n_tramite')}: {e}")
        db.finish_run(
            run_id, vistos=vistos, nuevos=nuevos,
            actualizados=actualizados, errores=errores,
            mensaje=f"import_csv: {Path(csv_path).name}",
        )
    except Exception as e:
        db.finish_run(
            run_id, vistos=vistos, nuevos=nuevos,
            actualizados=actualizados, errores=errores + 1,
            mensaje=f"FAIL: {e}",
        )
        raise

    return {
        "vistos": vistos,
        "nuevos": nuevos,
        "actualizados": actualizados,
        "errores": errores,
        "cambios_por_campo": cambios_por_campo,
    }
