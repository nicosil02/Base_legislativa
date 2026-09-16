"""Agendas del Pleno bicameral (Senado + Diputados) - via PDF, no la API JSON.

pleno/api.py + pleno/sync.py cubren agendas del Pleno via la API JSON de
adp-portal-service, pero esa API sigue sin tener NINGUNA agenda del periodo
bicameral 2026-2031 (verificado en vivo 2026-09-15, igual que el 09-11
documentado en pleno/api.py) - el Congreso bicameral las publica como PDF
en el sitio propio de cada camara, no por esa API. Este modulo scrapea esas
paginas (tabla HTML simple, sin JS) y baja/extrae texto de cada PDF nuevo.

Uso:
    python -m pleno.agenda_pdf sync
    python -m pleno.agenda_pdf test
"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0"}

FUENTES = [
    ("senado", "https://senado.congreso.gob.pe/sesiones_del_pleno/"),
    ("diputados", "https://diputados.congreso.gob.pe/sesiones-del-pleno/"),
]

# Cada fila de la tabla: <tr data-periodo="..."><td data-search="DD/MM/AAAA">
# fecha</td> ... <td data-search="archivo.pdf"><a class="fsm-pub-doc"
# href="URL">... - verificado en vivo 2026-09-15 contra ambos sitios
# (mismo layout WordPress en las dos camaras).
_RE_FILA = re.compile(
    r'<tr[^>]*data-periodo="([^"]*)"[^>]*>\s*'
    r'<td[^>]*data-search="(\d{2}/\d{2}/\d{4})"[^>]*>.*?</td>\s*'
    r'<td[^>]*data-search="[^"]*\.pdf"[^>]*>\s*'
    r'<a[^>]+class="fsm-pub-doc"[^>]+href="([^"]+)"',
    re.DOTALL | re.IGNORECASE,
)


def _fecha_a_iso(fecha_ddmmyyyy: str) -> str:
    d, m, y = fecha_ddmmyyyy.split("/")
    return f"{y}-{m}-{d}"


def fetch_agendas(session, camara: str, url: str) -> list[dict]:
    """[{camara, periodo, fecha, pdf_url}] - SOLO las filas que tienen PDF
    de Agenda (muchas sesiones solo tienen Acta/Diario de Debates, sin
    agenda previa publicada todavia - se saltean, no hay nada que bajar)."""
    r = session.get(url, timeout=25)
    r.raise_for_status()
    out = []
    for periodo, fecha_str, pdf_url in _RE_FILA.findall(r.text):
        out.append({
            "camara": camara,
            "periodo": periodo,
            "fecha": _fecha_a_iso(fecha_str),
            "pdf_url": pdf_url,
        })
    return out


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 20000) -> str:
    """Texto de la agenda - son PDFs de texto real (no escaneados), sin
    necesidad de OCR (a diferencia de noticias/registro_oficial_ec.py)."""
    import pymupdf as fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        parts = [page.get_text() for page in doc]
        return "\n".join(parts).strip()[:max_chars]
    finally:
        doc.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pleno_agenda_pdf (
            camara TEXT NOT NULL,
            fecha TEXT NOT NULL,
            pdf_url TEXT NOT NULL,
            texto TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (camara, fecha)
        )
    """)
    conn.commit()


def run_sync(db_path: str | Path, max_nuevos: int = 50) -> dict:
    """Baja las agendas del Pleno (Senado + Diputados) que todavia no
    tenemos guardadas. `max_nuevos` acota cuantos PDFs nuevos bajar por
    corrida - de mas, solo como freno de seguridad (el volumen real es
    ~10-20 por camara por año legislativo, verificado en vivo 2026-09-15:
    7 Senado + 10 Diputados en total); pedido de Nicolas de tener
    SIEMPRE todas las agendas disponibles, no una ventana parcial."""
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
                "SELECT 1 FROM pleno_agenda_pdf WHERE camara=? AND fecha=?",
                (fila["camara"], fila["fecha"]),
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
                    (fila["camara"], fila["fecha"], fila["pdf_url"], texto,
                     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
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


def _demo():
    """Self-check parseo con las paginas reales (test lento - hace 2
    requests, una por camara, sin bajar ningun PDF)."""
    session = requests.Session()
    session.headers.update(HEADERS)
    total = 0
    for camara, url in FUENTES:
        filas = fetch_agendas(session, camara, url)
        assert len(filas) > 0, f"{camara}: esperaba >=1 fila con PDF, hay 0"
        f = filas[0]
        for k in ("camara", "fecha", "pdf_url"):
            assert f.get(k), f"{camara}: fila sin {k!r}: {f}"
        assert f["pdf_url"].startswith("https://") and f["pdf_url"].endswith(".pdf")
        print(f"OK {camara}: {len(filas)} fila(s) con Agenda PDF, "
              f"mas reciente {f['fecha']} -> {f['pdf_url']}")
        total += len(filas)
    assert total > 0


def _test_parse_fila_sin_red():
    """Parseo del regex contra HTML fijo, sin red - valida el patron
    exacto encontrado en vivo 2026-09-15 en ambos sitios."""
    html = '''
    <tr data-periodo="2026-2027">
        <td data-search="10/09/2026">10/09/2026</td>
        <td data-search="AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf">
            <a class="fsm-pub-doc" href="https://diputados.congreso.gob.pe/wp-content/uploads/2026/09/AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf">ver</a>
        </td>
        <td data-search="">&mdash;</td>
    </tr>
    <tr data-periodo="2026-2027">
        <td data-search="10/09/2026">10/09/2026</td>
        <td data-search="">&mdash;</td>
    </tr>
    '''
    filas = list(_RE_FILA.findall(html))
    assert len(filas) == 1, f"esperaba 1 fila con PDF (la 2da no tiene), hay {len(filas)}"
    periodo, fecha, pdf_url = filas[0]
    assert fecha == "10/09/2026"
    assert pdf_url.endswith("AGENDA-PLENO-DIPUTADOS-10-09-2026.pdf")
    assert _fecha_a_iso(fecha) == "2026-09-10"
    print("OK agenda_pdf: regex de fila distingue filas con/sin PDF de agenda")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync", "demo", "test"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--max-nuevos", type=int, default=10)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "demo":
        _demo()
    elif args.cmd == "test":
        _test_parse_fila_sin_red()
    else:
        stats = run_sync(args.db, max_nuevos=args.max_nuevos)
        print(f"Agendas del Pleno (PDF): {stats}")
