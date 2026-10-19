"""OCR de las paginas escaneadas de "Votaciones y Asistencias" del Pleno
bicameral (las que votaciones/pleno_bicameral.py cuenta en
pleno_votacion_pdf.paginas_sin_texto y salta).

Va en su propio workflow (votaciones-ocr-bicameral.yml): PaddleOCR pesa
cientos de MB y tarda ~10-20 s por pagina en CPU. Usa el mismo OCR que
votaciones/ocr_pleno.py y el mismo parser por posicion que los PDF de texto:
las cajas del OCR se pasan a palabras con su x en puntos PDF. Guarda en las
mismas tablas con la misma clave; la columna `cuadra` dice si los votos
leidos suman los totales del PDF.

  python -m votaciones.pleno_bicameral_ocr [--db proyectos.db] [--minutos 90]

Cada PDF se procesa entero (paginas de texto + escaneadas, en orden: la
clave lleva el orden de la votacion dentro del PDF) y se anota en
pleno_votacion_ocr para no repetirlo.
"""
from __future__ import annotations

import argparse
import collections
import logging
import re
import sqlite3
import time
import unicodedata

import requests

from core.db import now_iso
from votaciones.pleno_bicameral import (_CODIGO, _RE_SIGLA, _RE_VOTO, HEADERS, _limpia, guardar, init_schema, lineas,
                                        parse_pagina)

log = logging.getLogger(__name__)

# Voto pegado al nombre en la misma caja: "ALEJANDROPRE", "PIERANGELISI",
# "ALEJANDROLO". Se separa solo si la caja termina donde terminan los votos
# sueltos de la pagina (no por el texto: "SEFERINO" termina en NO).
_PEGADO = re.compile(r"(?<=[A-ZÁÉÍÓÚÑ,.])(PRE|AUS|ABST\.?|SI|NO|LO|LE|LP|LV)$", re.I)
# Las cajas del OCR de una misma fila bailan +-4 pt de alto (filas cada ~11 pt).
TOL_OCR = 5
_ARREGLOS = {"5I": "SI", "S1": "SI", "SL": "SI", "N0": "NO", "NO-": "NO"}


def palabras_ocr(items, ancho_px: float, ancho_pt: float) -> list[tuple[float, float, str]]:
    """Cajas del OCR [(texto, [x0, y0, x1, y1]) en pixeles] -> [(x, y, palabra)]
    en puntos PDF, como page.get_text("words"). La x de cada palabra se
    reparte por caracteres dentro de la caja; la y es el centro de la caja."""
    k = ancho_pt / ancho_px
    out = []
    limpio = [(unicodedata.normalize("NFKC", t).replace("—", "-").replace("–", "-").strip(), b)  # "NO—"
              for t, b in items]
    fin_votos = [b[2] for t, b in limpio if t and _RE_VOTO.match(_ARREGLOS.get(t.upper(), t))]
    for t, (x0, y0, x1, y1) in limpio:
        if sum(abs(x1 - f) * k <= 6 for f in fin_votos) >= 3:
            t = _PEGADO.sub(r" \1", t)
        if not t:
            continue
        por_car = (x1 - x0) / len(t)
        ms = list(re.finditer(r"\S+", t))
        for i, m in enumerate(ms):
            w = _ARREGLOS.get(m.group().upper(), m.group())
            x = (x0 + m.start() * por_car) * k
            if i == len(ms) - 1 and i and _RE_VOTO.match(w):
                # Voto al final de la caja del nombre: entre los dos hay un hueco
                # que el reparto por caracteres no ve; se mide desde el borde derecho.
                x = x1 * k - 6 * len(w)
            out.append((x, (y0 + y1) / 2 * k, w))
    return _enderezar(out)


def _enderezar(words):
    """Escaneos torcidos (~1 grado: la 3ra columna queda 5 pt mas arriba que la
    1ra, media fila): se prueba cada pendiente y se queda la que deja menos
    lineas, o sea las filas mejor alineadas."""
    def n_lineas(s):
        return len(lineas([(x, y - s * x, t) for x, y, t in words], 2.5))
    s = min((i / 1000 for i in range(-30, 31)), key=lambda s: (n_lineas(s), abs(s)))
    return [(x, y - s * x, t) for x, y, t in words]


_MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
_MESES["setiembre"] = 9
_RE_SESION = re.compile(r"SESION DEL:?\s*(\d{1,2}) DE ([A-Z]+) DE (\d{4})")


def parse_nominal(words, tol: float = TOL_OCR) -> dict | None:
    """Formato "VOTACION NOMINAL" de las primeras sesiones (jul-ago 2026):
    dos mitades de "N.° | GRUPO | CONGRESISTA | SI | NO | ABST" con una marca
    (√) en la columna del voto o un codigo (LE, LP...) en su lugar. Sin hora:
    la clave usa hora vacia + orden dentro del PDF."""
    ls = lineas(words, tol)
    texto = [(y, _limpia(" ".join(t for _, t in ws)), ws) for y, ws in ls]
    if not any("NOMINAL" in s for _, s, _ in texto):
        return None
    fecha = None
    for _, s, _ in texto:
        m = _RE_SESION.search(s)
        if m and m.group(2).lower() in _MESES:
            fecha = f"{m.group(3)}-{_MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
            break
    # Cabecera de columnas: la linea con SI, NO y ABST (dos veces, una por mitad).
    cab = next(((y, ws) for y, s, ws in texto if {"SI", "NO"} <= set(s.split()) and "ABST" in s), None)
    if not fecha or not cab:
        return None
    y_cab, ws_cab = cab
    cols = {}
    for x, t in ws_cab:
        v = {"SI": "SI", "NO": "NO"}.get(_limpia(t).strip("."), "ABST" if _limpia(t).startswith("ABST") else None)
        if v:
            cols.setdefault(v, []).append(x)
    if not all(len(cols.get(v, [])) == 2 for v in ("SI", "NO", "ABST")):
        return None
    mitades = [{v: sorted(cols[v])[i] for v in cols} for i in (0, 1)]
    y_asu = next((y for y, s, _ in texto if s.startswith("ASUNTO")), None)
    asunto = " ".join(s for y, s, _ in texto if y_asu is not None and y_asu <= y < y_cab - 8)
    asunto = re.sub(r"^ASUNTO:?\s*", "", asunto).strip()
    # (el asunto queda sin tildes: sale de _limpia)

    totales, votos = {}, []
    for y, s, ws in texto:
        if y <= y_cab:
            continue
        if s.startswith(("LEYENDA", "RESULTADO")):
            break
        nums = [(x, t) for x, t in ws if t.isdigit()]
        if not totales and nums and not any(t.isalpha() and len(t) > 3 for _, t in ws):
            # fila de totales bajo la cabecera (igual en las dos mitades)
            for v, xv in mitades[0].items():
                cerca = [int(t) for x, t in nums if abs(x - xv) <= 12]
                if cerca:
                    totales[{"SI": "si", "NO": "no", "ABST": "abst"}[v]] = cerca[0]
            continue
        # Cada mitad de la fila empieza con su N.° (1-130).
        segs, seg = [], None
        for x, t in ws:
            if t.isdigit() and len(t) <= 3:
                seg = [(x, t)]
                segs.append(seg)
            elif seg is not None:
                seg.append((x, t))
        for seg in segs:
            mit = next((m for m in mitades if m["SI"] > seg[0][0]), None)
            if not mit or len(seg) < 3:
                continue
            resto = seg[1:]
            bancada = resto.pop(0)[1] if _RE_SIGLA.match(resto[0][1]) else None
            voto, nombre = None, []
            for x, t in resto:
                col = next((v for v, xv in mit.items() if abs(x - xv) <= 10), None)
                if col and x > mit["SI"] - 15:
                    voto = col if not re.fullmatch(r"[A-Z]{1,4}", t) or t == "V" else t
                else:
                    nombre.append(t)
            if nombre:
                votos.append((" ".join(nombre), bancada, voto or "SINRESP"))
    if not votos:  # hoja final con solo el resumen de la misma votacion
        return None
    conteo = collections.Counter(v for _, _, v in votos)
    cuadra = bool(votos) and bool(totales) and all(conteo[_CODIGO[k]] == n for k, n in totales.items())
    return {"tipo": "votacion", "fecha": fecha, "hora": "", "asunto": asunto, "votos": votos,
            "totales": totales, "cuadra": cuadra}


def _ocr_motor():
    from votaciones.ocr_pleno import _ocr
    return _ocr()


def bloques_pdf(pdf_bytes: bytes, ocr) -> tuple[list[dict], int]:
    """Todas las paginas en orden (las de texto con su texto, las escaneadas
    por OCR). Devuelve (bloques, paginas_ocr)."""
    import pymupdf
    from votaciones.ocr_pleno import ocr_pagina
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    bloques, n_ocr = [], 0
    try:
        for i, page in enumerate(doc):
            words = [(w[0], w[1], w[4]) for w in page.get_text("words")]
            escaneada = not words
            if escaneada:
                try:
                    items, ancho_px, _ = ocr_pagina(ocr, page, dpi=200)
                except Exception as e:  # una pagina rota no tira el PDF
                    log.warning("OCR pagina %s: %s", i, e)
                    continue
                n_ocr += 1
                words = palabras_ocr(items, ancho_px, page.rect.width)
            b = parse_pagina(words, tol=TOL_OCR if escaneada else 3) or (escaneada and parse_nominal(words))
            if b:
                bloques.append(b)
    finally:
        doc.close()
    return bloques, n_ocr


# Cambio del parser que puede hacer cuadrar lo que antes no: los PDF con
# bloques que no cuadraban, procesados antes de esta fecha, se rehacen una vez.
PARSER_DESDE = "2026-10-19T02:40:00Z"  # cuadro de bancadas tambien en asistencias + ausentes de mas en Resultado


def pendientes(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """[(camara, pdf_url)] con paginas escaneadas que todavia no pasaron por OCR
    (o que no cuadraban con un parser anterior a PARSER_DESDE)."""
    return [tuple(r) for r in conn.execute(
        "SELECT camara, pdf_url FROM pleno_votacion_pdf WHERE paginas_sin_texto > 0 "
        "AND pdf_url NOT IN (SELECT pdf_url FROM pleno_votacion_ocr "
        "                    WHERE cuadran >= bloques OR fetched_at >= ?) ORDER BY fecha",
        (PARSER_DESDE,))]


def run(db_path: str, minutos: float = 90) -> dict:
    stats = {"pdfs": 0, "paginas_ocr": 0, "bloques": 0, "cuadran": 0, "pendientes": 0}
    conn = sqlite3.connect(db_path)
    init_schema(conn)
    cola = pendientes(conn)
    stats["pendientes"] = len(cola)
    if not cola:
        return stats
    ocr = _ocr_motor()
    session = requests.Session()
    session.headers.update(HEADERS)
    fin = time.time() + minutos * 60
    for camara, url in cola:
        if time.time() > fin:  # lo que falte va en la proxima corrida
            break
        try:
            try:
                r = session.get(url, timeout=120)
            except requests.RequestException:  # el Senado a veces no responde a la primera
                time.sleep(30)
                r = session.get(url, timeout=180)
            r.raise_for_status()
            bloques, n_ocr = bloques_pdf(r.content, ocr)
        except Exception as e:
            log.warning("OCR %s: %s", url, e)
            continue
        guardar(conn, camara, url, bloques, pisar_empate=False)
        cuadran = sum(b["cuadra"] for b in bloques)
        conn.execute("INSERT OR REPLACE INTO pleno_votacion_ocr VALUES (?,?,?,?,?)",
                     (url, n_ocr, len(bloques), cuadran, now_iso()))
        conn.commit()
        stats["pdfs"] += 1
        stats["paginas_ocr"] += n_ocr
        stats["bloques"] += len(bloques)
        stats["cuadran"] += cuadran
        log.info("%s: %s paginas OCR, %s bloques, %s cuadran", url.rsplit("/", 1)[-1], n_ocr, len(bloques), cuadran)
    stats["pendientes"] = len(pendientes(conn))  # lo que queda para la proxima corrida
    conn.close()
    return stats


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--minutos", type=float, default=90)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"Votaciones del Pleno (OCR): {run(a.db, a.minutos)}")
