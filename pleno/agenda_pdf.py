"""Agendas del Pleno bicameral (Senado + Diputados) desde los PDF que publica
cada camara en su sitio (la API JSON de pleno/api.py no tiene el periodo
bicameral). Scrapea la tabla HTML y extrae el texto de cada PDF nuevo.

Uso:
    python -m pleno.agenda_pdf sync
"""
from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import requests

from core.db import now_iso

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}

FUENTES = [
    ("senado", "https://senado.congreso.gob.pe/sesiones_del_pleno/"),
    ("diputados", "https://diputados.congreso.gob.pe/sesiones-del-pleno/"),
]

# Cada fila: <tr data-periodo="..."><td data-search="DD/MM/AAAA">fecha</td>
# [<td class="snp26-sesion-celda">Sesion</td> (solo Senado, desde oct 2026)]
# <td data-search="archivo.pdf ..."><a class="fsm-pub-doc" href="URL"> = Agenda
# y despues Acta, Diario, etc. Se lee celda por celda: con la Agenda vacia
# una regex de corrido tomaba el primer PDF de la fila (el Diario).
_RE_TR = re.compile(r'<tr[^>]*data-periodo="([^"]*)"[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
_RE_TD = re.compile(r'<td([^>]*)>(.*?)</td>', re.DOTALL | re.IGNORECASE)
_RE_FECHA = re.compile(r'data-search="(\d{2}/\d{2}/\d{4})"')
_RE_HREF = re.compile(r'class="fsm-pub-doc"[^>]+href="([^"]+\.pdf)"', re.IGNORECASE)


def _filas(html_text: str) -> list[tuple[str, str, str]]:
    """[(periodo, DD/MM/AAAA, url de la Agenda)] de las filas que tienen Agenda."""
    out = []
    for periodo, fila in _RE_TR.findall(html_text):
        celdas = [(attrs, cont) for attrs, cont in _RE_TD.findall(fila)
                  if "sesion-celda" not in attrs]
        if len(celdas) < 2:
            continue
        fecha = _RE_FECHA.search(celdas[0][0])
        href = _RE_HREF.search(celdas[1][1])
        if fecha and href:
            out.append((periodo, fecha.group(1), href.group(1)))
    return out


def _fecha_a_iso(fecha_ddmmyyyy: str) -> str:
    d, m, y = fecha_ddmmyyyy.split("/")
    return f"{y}-{m}-{d}"


def fetch_agendas(session, camara: str, url: str) -> list[dict]:
    """[{camara, periodo, fecha, pdf_url}] de las filas con PDF de Agenda
    (las que solo tienen Acta/Diario de Debates se saltean)."""
    r = session.get(url, timeout=25)
    r.raise_for_status()
    out = []
    for periodo, fecha_str, pdf_url in _filas(r.text):
        out.append({
            "camara": camara,
            "periodo": periodo,
            "fecha": _fecha_a_iso(fecha_str),
            "pdf_url": pdf_url,
        })
    return out


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 20000) -> str:
    """Texto de la agenda (PDFs de texto, no escaneados: sin OCR)."""
    import pymupdf as fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        parts = [page.get_text() for page in doc]
        return "\n".join(parts).strip()[:max_chars]
    finally:
        doc.close()


def init_schema(conn: sqlite3.Connection) -> None:
    # PK de 3 columnas: una fecha puede tener varios PDF y un PDF puede
    # cubrir varios dias.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pleno_agenda_pdf (
            camara TEXT NOT NULL,
            fecha TEXT NOT NULL,
            pdf_url TEXT NOT NULL,
            texto TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (camara, fecha, pdf_url)
        )
    """)
    conn.commit()


def run_sync(db_path: str | Path, max_nuevos: int = 50) -> dict:
    """Baja las agendas del Pleno que todavia no estan guardadas (todas, no
    una ventana). `max_nuevos` es solo un freno: son ~10-20 por camara al anio."""
    stats = {"filas_vistas": 0, "nuevas": 0, "errores": 0}
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    session = requests.Session()
    session.headers.update(HEADERS)

    bajadas = 0
    for camara, url in FUENTES:
        try:
            filas = fetch_agendas(session, camara, url)
        except Exception as e:
            log.warning("agenda_pdf %s: fetch fallo: %s", camara, e)
            stats["errores"] += 1
            continue
        stats["filas_vistas"] += len(filas)
        for fila in filas:
            if bajadas >= max_nuevos:
                break
            existe = conn.execute(
                "SELECT 1 FROM pleno_agenda_pdf WHERE camara=? AND fecha=? AND pdf_url=?",
                (fila["camara"], fila["fecha"], fila["pdf_url"]),
            ).fetchone()
            if existe:
                continue
            try:
                r = session.get(fila["pdf_url"], timeout=30)
                r.raise_for_status()
                texto = extract_pdf_text(r.content)
                if not texto:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO pleno_agenda_pdf
                       (camara, fecha, pdf_url, texto, fetched_at)
                       VALUES (?,?,?,?,?)""",
                    (fila["camara"], fila["fecha"], fila["pdf_url"], texto, now_iso()),
                )
                conn.commit()
                stats["nuevas"] += 1
                bajadas += 1
            except Exception as e:
                log.warning("agenda_pdf %s %s: fallo bajando PDF: %s",
                            fila["camara"], fila["fecha"], e)
                stats["errores"] += 1

    conn.close()
    log.info("agenda_pdf sync: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--max-nuevos", type=int, default=50)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = run_sync(args.db, max_nuevos=args.max_nuevos)
    print(f"Agendas del Pleno (PDF): {stats}")
