"""Lectura de las matrices puntuales de PLs que Nicolas mantiene a mano en
Excel (Bayer Crop/Syngenta, Incode) - complementan el filtro por categoria
de scraper/categorias.py::CATEGORIA_CLIENTES_PL, que puede no detectar un PL
realmente relevante si su tema literal no calza con la categoria del cliente
(confirmado en vivo 2026-09-13: 4 PLs reales de la matriz Bayer Crop en Peru
cayeron en categorias "Consumo masivo"/"Tributos", no "Agricultura" - son
leyes tributarias que afectan al agro, no leyes agrarias en si).

Se lee el Excel directo en cada carga (decision de Nicolas 2026-09-13: sigue
editando el archivo como siempre, sin pasos extra) - ambos archivos se
versionan en el repo (ver .gitignore) igual que notas.md, para que la app en
produccion tambien los pueda leer.

Nicolas confirmo 2026-09-13:
- Bayer Crop (hojas PERU y ECUADOR): funciona 100%, usar tal cual.
- Incode Peru (hoja "Peru Legislativo"): desactualizada (PLs archivados al
  pasar al Congreso bicameral) - NO USAR.
- Incode Ecuador (hoja "Ecuador Legislativo"): la lista de PLs es real, solo
  el estado que trae la matriz puede estar desactualizado - se usa el
  numero de PL para cruzar, no el estado_matriz como fuente de verdad.
"""
from __future__ import annotations

import re
from pathlib import Path

CLIENTES_DIR = Path(__file__).resolve().parent

# La columna "Proyecto" de la matriz Peru trae texto libre alrededor del
# codigo real ("N° 00011-2026-2031-CD", "Proposición N° 00080-...") -
# se extrae solo el codigo (mismo formato que proyecto_ley en nuestra DB:
# 5 digitos-4 digitos-4 digitos-2/3 letras) para poder cruzar por igualdad
# exacta contra pages/1_Peru.py::df["PL"].
_RE_PL_PE = re.compile(r"\d+-\d{4}-\d{4}-[A-Za-z]{1,3}")


def _normalizar_pl_pe(texto: str) -> str | None:
    m = _RE_PL_PE.search(str(texto))
    return m.group(0).upper() if m else None

BAYER_CROP_XLSX = CLIENTES_DIR / "MatrizPLAndinos_Bayer CROP.xlsx"
INCODE_XLSX = CLIENTES_DIR / "140125 - Matriz - Matriz Legislativa y Regulatoria INCODE.xlsx"


_RE_DIGITS = re.compile(r"\d{5,}")


def _split_numeros(valor, extraer_digitos: bool = False) -> list[str]:
    """Una celda puede traer un solo numero o varios separados por salto de
    linea/coma/barra (PLs unificados en Ecuador, o formato mixto tipo
    "Cod. AN-2024-2928 / 450889") - normaliza a lista de strings.

    `extraer_digitos`: para Ecuador, si un token no es puramente numerico
    (trae el "codigo de tramite" AN-XXX en vez del n_tramite numerico que
    usamos para cruzar), se intenta extraer la corrida de 5+ digitos que
    hay adentro. NO usar para Peru - ahi el codigo real ES alfanumerico
    ("00011-2026-2031-CD") y este atajo lo rompería."""
    if valor is None:
        return []
    if isinstance(valor, (int, float)):
        return [str(int(valor))]
    texto = str(valor).replace(",", "\n").replace("/", "\n")
    tokens = [p.strip() for p in texto.split("\n") if p.strip()]
    if not extraer_digitos:
        return tokens
    out = []
    for t in tokens:
        m = _RE_DIGITS.search(t)
        out.append(m.group(0) if m else t)
    return out


def _leer_hoja(path: Path, hoja: str, header_row: int,
                cols: dict[str, str | list[str]]) -> list[dict]:
    """Lee una hoja mapeando nombres de columna (`cols`: alias -> header real,
    o lista de variantes aceptadas - ej. la hoja ECUADOR tiene el typo
    "Tit�lo" en vez de "T�tulo") a partir de la fila de headers. Filas
    totalmente vacias se saltean. Si el archivo/hoja no existe, devuelve
    lista vacia (no rompe la app si Nicolas todavia no subio o renombro algo)."""
    import openpyxl

    if not path.exists():
        return []
    wb = openpyxl.load_workbook(path, data_only=True)
    if hoja not in wb.sheetnames:
        return []
    ws = wb[hoja]
    # Los headers reales tienen inconsistencias (espacios de mas, typos como
    # "Tit�lo" en vez de "T�tulo") - matchear normalizado (strip + lower) en
    # vez de comparacion exacta.
    headers_norm = [
        (str(c.value).strip().lower() if c.value is not None else None)
        for c in next(ws.iter_rows(min_row=header_row, max_row=header_row))
    ]
    idx = {}
    for alias, candidatos in cols.items():
        if isinstance(candidatos, str):
            candidatos = [candidatos]
        for real in candidatos:
            real_norm = real.strip().lower()
            if real_norm in headers_norm:
                idx[alias] = headers_norm.index(real_norm)
                break
    out = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not any(c is not None for c in row):
            continue
        out.append({alias: row[i] for alias, i in idx.items()})
    return out


def matriz_bayer_crop(pais: str) -> list[dict]:
    """PLs puntuales de la matriz Bayer Crop/Syngenta para `pais` ("PE"/"EC").
    Cada dict: pl_numero, titulo_matriz, tema_matriz, estado_matriz."""
    hoja = "PERÚ" if pais == "PE" else "ECUADOR"
    filas = _leer_hoja(
        BAYER_CROP_XLSX, hoja, header_row=(3 if pais == "PE" else 2),
        cols={"titulo": ["Título", "Titúlo"], "proyecto": "Proyecto", "tema": "Tema", "estado": "Estado"},
    )
    out = []
    for f in filas:
        for num in _split_numeros(f.get("proyecto"), extraer_digitos=(pais == "EC")):
            if pais == "PE":
                num = _normalizar_pl_pe(num)
                if not num:
                    continue
            out.append({
                "pl_numero": num, "titulo_matriz": f.get("titulo"),
                "tema_matriz": f.get("tema"), "estado_matriz": f.get("estado"),
            })
    return out


def matriz_incode_ec() -> list[dict]:
    """PLs puntuales de la matriz Incode para Ecuador (la unica hoja que
    Nicolas confirmo vigente - la de Peru esta desactualizada, no se lee)."""
    filas = _leer_hoja(
        INCODE_XLSX, "Ecuador Legislativo", header_row=2,
        cols={"titulo": ["Título", "Titúlo"], "proyecto": "Proyecto", "tema": "Tema", "estado": "Estado"},
    )
    out = []
    for f in filas:
        for num in _split_numeros(f.get("proyecto"), extraer_digitos=True):
            out.append({
                "pl_numero": num, "titulo_matriz": f.get("titulo"),
                "tema_matriz": f.get("tema"), "estado_matriz": f.get("estado"),
            })
    return out


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    pe = matriz_bayer_crop("PE")
    ec = matriz_bayer_crop("EC")
    inc = matriz_incode_ec()
    assert isinstance(pe, list) and isinstance(ec, list) and isinstance(inc, list)
    if BAYER_CROP_XLSX.exists():
        assert len(pe) > 0, "esperaba PLs reales en la matriz Bayer Crop PE"
        assert len(ec) > 0, "esperaba PLs reales en la matriz Bayer Crop EC"
        assert all(f["pl_numero"] and f["titulo_matriz"] for f in pe), (
            "algun PL de PE quedo sin titulo - revisar header 'Titulo/Titulo'")
        assert all(f["pl_numero"] and f["titulo_matriz"] for f in ec), (
            "algun PL de EC quedo sin titulo - la hoja ECUADOR tiene el typo 'Titulo'")
        print(f"OK matriz_bayer_crop('PE'): {len(pe)} PLs")
        print(f"OK matriz_bayer_crop('EC'): {len(ec)} PLs")
    else:
        print("SKIP: no se encontro el Excel de Bayer Crop en este entorno")
    if INCODE_XLSX.exists():
        assert len(inc) > 0, "esperaba PLs reales en la matriz Incode Ecuador"
        print(f"OK matriz_incode_ec(): {len(inc)} PLs")
    else:
        print("SKIP: no se encontro el Excel de Incode en este entorno")


if __name__ == "__main__":
    _demo()
