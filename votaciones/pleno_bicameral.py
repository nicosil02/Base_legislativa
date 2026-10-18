"""Votaciones nominales y asistencias del Pleno bicameral (2026-2031).

Senado y Diputados publican en "Sesiones del Pleno" un PDF de "Votaciones y
Asistencias" por sesion: una pagina por asistencia o votacion, con tres
columnas de (bancada, nombre, voto) y abajo los totales. Se lee por posicion
de las palabras (pymupdf "words"): el texto plano sale desordenado en los
PDF escaneados con capa OCR del Senado.

  python -m votaciones.pleno_bicameral sync [--db proyectos.db]

Gotchas:
- Las versiones "_vbo"/"_vb" (firmadas) suelen ser escaneos SIN texto; las
  "PROVISIONAL" son PDF de texto pero se reemplazan en la web. Por eso se
  suman las URL que pleno.agenda_pdf ya guardo (ahi quedaron provisionales).
  La misma votacion de dos PDF cae en la misma clave y gana la que cuadra.
- TODO OCR: paginas sin texto se cuentan en pleno_votacion_pdf
  (paginas_sin_texto) y se saltan. votaciones/ocr_pleno.py tiene el OCR del
  periodo anterior si hace falta.
- Fila sin voto = SINRESP (en el Senado ahi aparece el que preside).
"""
from __future__ import annotations

import collections
import json
import logging
import re
import sqlite3
from pathlib import Path

import requests

from core.db import now_iso
from core.text import sin_tildes
from pleno.agenda_pdf import FUENTES, HEADERS, _fecha_a_iso

log = logging.getLogger(__name__)

# Link de la columna "Votaciones y Asistencias" (mismo aria-label en las dos
# camaras, aunque el layout de la tabla es distinto).
_RE_LINK = re.compile(
    r'<a[^>]+href="([^"]+\.pdf)"[^>]*aria-label="[^"]*Votaciones y Asistencias', re.I)
_RE_FECHA_FILA = re.compile(r'data-search="\s*(\d{2}/\d{2}/\d{4})')

_RE_CABECERA = re.compile(
    r"(VOTACION|ASISTENCIA):?\s*Fecha:\s*(\d{2}/\d{2}/\d{4})\s*Hora:\s*(\d{1,2})\s*:\s*(\d{2})\s*([AP])\.?\s*M",
    re.I)
_RE_SIGLA = re.compile(r"^[A-Z]{1,5}$")
_RE_VOTO = re.compile(r"^(SI|NO|ABST\.?|PRE|AUS|LO|LV|LE|LP|LS|SUS)?[+\-]*$", re.I)
_RE_PL = re.compile(
    r"(?:PROYECTO|PROPOSICION)\s+(?:DE\s+)?(?:LEY|RESOLUCION\s+LEGISLATIVA|LEGISLATIVA)\s*(?:N[^\s\d]{0,2}\s*)?(\d+)")
_MARCA_AGUA = {"COPIA", "INFORMATIVA", "INFORMACION", "PROVISIONAL", "SIN", "REGISTROS", "ORALES"}

# Etiqueta del cuadro de totales -> clave; y clave -> codigo de voto que cuenta.
_TOTALES = [("A FAVOR", "si"), ("EN CONTRA", "no"), ("ABSTENCION", "abst"), ("SIN RESPUESTA", "sin_resp"),
            ("PRESENTE", "pre"), ("AUSENTE", "aus"), ("LIC. OFICIAL", "lo"), ("LIC. PERSONAL", "lp"),
            ("LIC. POR ENFERMEDAD", "le"), ("LIC. POR VIAJE", "lv"), ("SUSPENDIDO", "sus")]
_CODIGO = {"si": "SI", "no": "NO", "abst": "ABST", "sin_resp": "SINRESP", "pre": "PRE", "aus": "AUS",
           "lo": "LO", "lp": "LP", "le": "LE", "lv": "LV"}

_CAMARA_PL = {"senado": "S", "diputados": "D"}


def _limpia(s: str) -> str:
    return sin_tildes(s).upper()


def lineas(words) -> list[tuple[float, list[tuple[float, str]]]]:
    """words = [(x, y, texto)] -> [(y, [(x, texto)])] agrupando por altura."""
    out: list = []
    for x, y, t in sorted(words, key=lambda w: (round(w[1]), w[0])):
        if out and abs(out[-1][0] - y) < 3:
            out[-1][1].append((x, t))
        else:
            out.append((y, [(x, t)]))
    return [(y, sorted(ws)) for y, ws in out]


def _numero(t: str) -> int | None:
    t = t.strip()
    if t in ("o", "O"):  # el OCR lee el cero como "o"
        return 0
    return int(t) if t.isdigit() else None


def _hora24(h: str, m: str, ap: str) -> str:
    h = int(h) % 12 + (12 if ap.upper() == "P" else 0)
    return f"{h:02d}:{m}"


def parse_pagina(words) -> dict | None:
    """Una pagina = una asistencia o votacion. None si no tiene cabecera."""
    ls = lineas(words)
    texto = [(y, " ".join(t for _, t in ws), ws) for y, ws in ls]
    cab = None
    for y, s, _ in texto:
        m = _RE_CABECERA.search(_limpia(s))
        if m:
            cab = (y, m)
            break
    if not cab:
        return None
    y_cab, m = cab
    tipo = "votacion" if m.group(1).upper().startswith("VOT") else "asistencia"
    y_fin = next((y for y, s, _ in texto if y > y_cab and _limpia(s).startswith("RESULTADO")), 1e9)

    # Siglas de bancada: las del cuadro "Grupo Parlamentario" de abajo (asi
    # un apellido corto o una palabra del asunto no pasan por bancada).
    x_grupo = next((x for y, ws in ls if y >= y_fin for x, t in ws if _limpia(t) == "GRUPO"), None)
    siglas = {t for y, ws in ls if y >= y_fin for x, t in ws
              if x_grupo is not None and abs(x - x_grupo) <= 5 and _RE_SIGLA.match(t) and t != "GRUPO"}
    # Columnas: x donde esas siglas aparecen varias veces.
    # (el OCR corre la x 1-2 pt entre filas: se cuenta con tolerancia).
    xs = [x for y, ws in ls if y_cab < y < y_fin for x, t in ws if t in siglas]
    cols = [x for x in xs if sum(abs(x - x2) <= 5 for x2 in xs) >= 5]

    def es_bancada(x, t):
        return t in siglas and any(abs(x - c) <= 5 for c in cols)

    votos, y_primera = [], None
    for y, ws in ls:
        if not (y_cab < y < y_fin) or not any(es_bancada(x, t) for x, t in ws):
            continue
        y_primera = y_primera or y
        seg = None  # lo que este antes de la primera bancada (marca de agua "COPIA") se ignora
        for x, t in ws + [(1e9, "")]:
            if es_bancada(x, t) or x == 1e9:
                if seg and len(seg) >= 2:
                    x0, bancada = seg[0]
                    es_voto = [x2 - x0 >= 140 and bool(_RE_VOTO.match(t2)) for x2, t2 in seg[1:]]
                    nombre = " ".join(t2 for (x2, t2), v in zip(seg[1:], es_voto) if not v)
                    voto = re.sub(r"[+\-.]", "", "".join(t2 for (x2, t2), v in zip(seg[1:], es_voto) if v)).upper()
                    # Fila sin voto = "sin respuesta" (ahi cae tambien el que preside
                    # en el Senado; en Diputados el que preside no sale en la lista).
                    votos.append((re.sub(r"\s*,\s*", ", ", nombre).strip(" ,"), bancada, voto or "SINRESP"))
                seg = [(x, t)]
            elif seg is not None:
                seg.append((x, t))

    asunto = ""
    if tipo == "votacion":
        y_asu = next((y for y, s, _ in texto if _limpia(s).startswith("ASUNTO")), None)
        if y_asu is not None:
            partes = []
            for y, s, ws in texto:
                if y_asu <= y < (y_primera or y_fin) and not {_limpia(t) for _, t in ws} <= _MARCA_AGUA:
                    partes.append(re.sub(r"^Asunto:\s*", "", s, flags=re.I))
            asunto = " ".join(p for p in partes if p).strip()

    totales = {}
    nums = [(y, x, _numero(t)) for y, ws in ls if y >= y_fin for x, t in ws if 120 < x < 200]
    nums = [n for n in nums if n[2] is not None]
    for y, s, _ in texto:
        if y < y_fin:
            continue
        s = _limpia(s)
        for etiqueta, clave in _TOTALES:
            if s.startswith(etiqueta) and clave not in totales:
                cerca = [n for n in nums if abs(n[0] - y) <= 4.5]
                totales[clave] = min(cerca, key=lambda n: abs(n[0] - y))[2] if cerca else 0
                break

    conteo = collections.Counter(v for _, _, v in votos)
    claves = [k for k in _CODIGO if k in totales]
    cuadra = bool(votos) and bool(claves) and all(conteo[_CODIGO[k]] == totales[k] for k in claves)
    return {"tipo": tipo, "fecha": _fecha_a_iso(m.group(2)), "hora": _hora24(m.group(3), m.group(4), m.group(5)),
            "asunto": asunto, "votos": votos, "totales": totales, "cuadra": cuadra}


def pley_de_asunto(asunto: str) -> int | None:
    m = _RE_PL.search(_limpia(asunto or ""))
    return int(m.group(1)) if m else None  # ponytail: solo el primer PL si el asunto junta varios


def parse_pdf(pdf_bytes: bytes) -> tuple[list[dict], int]:
    """(bloques, paginas_sin_texto)."""
    import pymupdf
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    bloques, sin_texto = [], 0
    try:
        for page in doc:
            words = [(w[0], w[1], w[4]) for w in page.get_text("words")]
            if not words:
                sin_texto += 1  # TODO OCR: escaneo sin capa de texto
                continue
            b = parse_pagina(words)
            if b:
                bloques.append(b)
    finally:
        doc.close()
    return bloques, sin_texto


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS votacion_pleno (
            id TEXT PRIMARY KEY,          -- camara:fecha:hora:tipo+orden
            camara TEXT NOT NULL, fecha TEXT NOT NULL, hora TEXT NOT NULL,
            tipo TEXT NOT NULL,           -- votacion | asistencia
            asunto TEXT,
            pl_cod_tipo_parl TEXT, pley_num INTEGER,
            si INTEGER, no INTEGER, abst INTEGER, sin_resp INTEGER,
            totales TEXT,                 -- JSON del cuadro de totales
            n_votos INTEGER, cuadra INTEGER,
            pdf_url TEXT, fetched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS voto_pleno_nominal (
            votacion_id TEXT NOT NULL, congresista TEXT NOT NULL,
            bancada TEXT, voto TEXT NOT NULL,
            PRIMARY KEY (votacion_id, congresista)
        );
        CREATE INDEX IF NOT EXISTS ix_vpn_cong ON voto_pleno_nominal(congresista);
        CREATE INDEX IF NOT EXISTS ix_vp_pl ON votacion_pleno(pley_num);
        CREATE TABLE IF NOT EXISTS pleno_votacion_pdf (
            pdf_url TEXT PRIMARY KEY, camara TEXT, fecha TEXT,
            paginas_sin_texto INTEGER, bloques INTEGER, fetched_at TEXT
        );
    """)
    conn.commit()


def guardar(conn: sqlite3.Connection, camara: str, pdf_url: str, bloques: list[dict]) -> int:
    """Upsert idempotente. Si la votacion ya esta (de otro PDF), se pisa solo
    si la nueva cuadra al menos igual de bien. Devuelve bloques escritos."""
    vistos = collections.Counter()
    escritos = 0
    for b in bloques:
        base = f"{camara}:{b['fecha']}:{b['hora']}:{b['tipo'][0]}"
        vistos[base] += 1
        vid = f"{base}{vistos[base]}"
        prev = conn.execute("SELECT cuadra FROM votacion_pleno WHERE id=?", (vid,)).fetchone()
        if prev and prev[0] > int(b["cuadra"]):
            continue
        t = b["totales"]
        pley = pley_de_asunto(b["asunto"])
        conn.execute("INSERT OR REPLACE INTO votacion_pleno VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            vid, camara, b["fecha"], b["hora"], b["tipo"], b["asunto"] or None,
            _CAMARA_PL.get(camara) if pley else None, pley,
            t.get("si"), t.get("no"), t.get("abst"), t.get("sin_resp"), json.dumps(t),
            len(b["votos"]), int(b["cuadra"]), pdf_url, now_iso()))
        conn.execute("DELETE FROM voto_pleno_nominal WHERE votacion_id=?", (vid,))
        conn.executemany("INSERT OR REPLACE INTO voto_pleno_nominal VALUES (?,?,?,?)",
                         [(vid, n, ban, v) for n, ban, v in b["votos"]])
        escritos += 1
    conn.commit()
    return escritos


def pdfs_publicados(session) -> list[tuple[str, str, str]]:
    """[(camara, fecha, url)] de la columna Votaciones y Asistencias."""
    out = []
    for camara, url in FUENTES:
        r = session.get(url, timeout=25)
        r.raise_for_status()
        for fila in r.text.split("<tr data-periodo")[1:]:
            f = _RE_FECHA_FILA.search(fila)
            for u in _RE_LINK.findall(fila):
                out.append((camara, _fecha_a_iso(f.group(1)) if f else "", u))
    return out


def pdfs_de_agenda(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Las provisionales que pleno.agenda_pdf guardo antes de que las cambien."""
    try:
        filas = conn.execute("SELECT camara, fecha, pdf_url FROM pleno_agenda_pdf").fetchall()
    except sqlite3.OperationalError:
        return []
    return [tuple(f) for f in filas if re.search(r"asistencia|votaci", f[2], re.I)]


def run_sync(db_path: str | Path) -> dict:
    stats = {"pdfs": 0, "bloques": 0, "paginas_sin_texto": 0, "errores": 0}
    conn = sqlite3.connect(str(db_path))
    init_schema(conn)
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        urls = pdfs_publicados(session)
    except Exception as e:
        log.warning("votaciones pleno: listado fallo: %s", e)
        urls, stats["errores"] = [], 1
    hechos = {r[0] for r in conn.execute("SELECT pdf_url FROM pleno_votacion_pdf")}
    for camara, fecha, url in dict.fromkeys(pdfs_de_agenda(conn) + urls):
        if url in hechos:
            continue
        hechos.add(url)
        try:
            r = session.get(url, timeout=60)
            r.raise_for_status()
            bloques, sin_texto = parse_pdf(r.content)
        except Exception as e:
            log.warning("votaciones pleno %s: %s", url, e)
            stats["errores"] += 1
            continue
        n = guardar(conn, camara, url, bloques)
        conn.execute("INSERT OR REPLACE INTO pleno_votacion_pdf VALUES (?,?,?,?,?,?)",
                     (url, camara, fecha, sin_texto, len(bloques), now_iso()))
        conn.commit()
        stats["pdfs"] += 1
        stats["bloques"] += n
        stats["paginas_sin_texto"] += sin_texto
        for b in bloques:
            if not b["cuadra"]:
                log.warning("no cuadra: %s %s %s %s", camara, b["fecha"], b["hora"], b["tipo"])
    conn.close()
    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync"])
    p.add_argument("--db", default="proyectos.db")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Votaciones del Pleno (PDF): {run_sync(a.db)}")
