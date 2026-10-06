"""Votaciones nominales del Pleno del Congreso del Peru (2021-2026) por OCR.

Fuente: la vista Lotus "new_asistenciavotacion" del Congreso, que lista un
PDF escaneado por sesion ("Asistencias y votaciones de la sesion del ...").
Cada pagina de votacion trae el asunto arriba y luego 3 columnas de
"BANCADA  APELLIDOS, NOMBRES  VOTO" (130 congresistas), ver pag2.png de la
prueba del 2026-10-06. Openpolitica ya extrajo hasta el 2024-03-07; este
modulo cubre el resto (y sirve para validar contra lo de ellos).

Uso:
  python -m votaciones.ocr_pleno indice                  # lista sesiones -> CSV
  python -m votaciones.ocr_pleno procesar --desde 2024-03-08 --parte 0 --partes 8 --db votaciones_pe.db
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import re
import sqlite3
import sys
from pathlib import Path

import requests

BASE = "https://www2.congreso.gob.pe/Sicr/RelatAgenda/PlenoComiPerm20112016.nsf/"
INDICE_URL = BASE + "new_asistenciavotacion?OpenForm&ExpandView&Count=3000&Seq=1"
UA = {"User-Agent": "Mozilla/5.0"}

VOTOS = {
    "SI": "SI", "NO": "NO", "ABST": "ABSTENCION", "SINRES": "SIN_RESPONDER",
    "AUS": "AUSENTE", "LO": "LICENCIA_OFICIAL", "LE": "LICENCIA_POR_ENFERMEDAD",
    "LP": "LICENCIA_PERSONAL", "L25A": "LICENCIA_SIN_GOCE", "SUS": "SUSPENDIDO",
    "F": "FALLECIDO",
}
_VOTO_RE = re.compile(r"^(SI|NO|Abst|SinRes|aus|LO|LE|LP|L25A|Sus|F)\b\.?\s*[+\-]*$", re.I)


def listar_sesiones(periodo: str = "2021 - 2026") -> list[dict]:
    t = requests.get(INDICE_URL, headers=UA, timeout=120).text
    out, actual = [], None
    for m in re.finditer(
            r"Periodo Parlamentario (\d{4} - \d{4})|(\d\d/\d\d/\d{4})</font></td><td><font[^>]*>"
            r"<A HREF=javascript:openWindow\('([^']+)'\)><div[^>]*>(.*?)</A>", t):
        if m.group(1):
            actual = m.group(1)
            continue
        if actual != periodo:
            continue
        f = m.group(2)
        out.append({"fecha": f"{f[6:]}-{f[:2]}-{f[3:5]}",
                    "titulo": html.unescape(m.group(4)).strip(),
                    "url": BASE + m.group(3)})
    return out


def _ocr():
    # Mismos modelos "small" que noticias/registro_oficial_ec.py.
    from paddleocr import PaddleOCR
    return PaddleOCR(text_detection_model_name="PP-OCRv6_small_det",
                     text_recognition_model_name="PP-OCRv6_small_rec",
                     use_doc_orientation_classify=False, use_doc_unwarping=False,
                     use_textline_orientation=False, text_recognition_batch_size=64)


def _rec():
    from paddleocr import TextRecognition
    return TextRecognition(model_name="PP-OCRv6_small_rec")


def ocr_pagina(ocr, page, dpi: int = 150):
    import numpy as np
    from PIL import Image
    pix = page.get_pixmap(dpi=dpi)
    img = np.array(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    r = ocr.predict(img)[0]
    items = [(t, [int(v) for v in b[:4]]) for t, b in zip(r["rec_texts"], r["rec_boxes"].tolist())]
    return items, pix.width, img


def completar_votos(p: dict, img, rec) -> int:
    """Segunda pasada: el detector a veces no ve el voto de la 1ra columna
    (queda pegado a la bancada de la 2da). Se recorta la zona donde deberia
    estar el voto (a ~0.21 del ancho desde el inicio del nombre) y se lee
    solo con el reconocedor. Devuelve cuantos recupero."""
    ancho = img.shape[1]
    n = 0
    for i, (nombre, bancada, voto, x, y) in enumerate(p["votos"]):
        if voto:
            continue
        x0, x1 = int(x + ancho * 0.19), min(ancho, int(x + ancho * 0.255))
        y0, y1 = max(0, int(y - ancho * 0.004)), min(img.shape[0], int(y + ancho * 0.014))
        if x1 - x0 < 5 or y1 - y0 < 5:
            continue
        t = rec.predict(img[y0:y1, x0:x1])[0]["rec_text"]
        v = normalizar_voto(t) or (normalizar_voto(m.group(1)) if (m := re.match(r"(SI|NO|Abst|SinRes|aus)", t.strip())) else None)
        if v:
            p["votos"][i] = (nombre, bancada, v, x, y)
            n += 1
    return n


def normalizar_voto(t: str) -> str | None:
    m = _VOTO_RE.match(t.strip())
    return VOTOS[m.group(1).upper()] if m else None


_BANCADA_RE = re.compile(r"^[A-Z]{2,4}(-[A-Z]{2,4})?$")
_VOTO_PEGADO = re.compile(r"\s((SI|NO)\s*[+\-]{2,3}|Abst\.|SinRes|aus)$")


def _fila(grupo: list) -> tuple | None:
    """Una fila de una columna, ordenada por x: [bancada] nombre... [voto].
    El nombre puede venir partido en 2 cajas y con '.' en vez de ','
    ("BARBARAN REYES." + "ROSANGELLA ANDREA")."""
    g = sorted(grupo, key=lambda c: c[1])
    bancada = voto = None
    if len(g) > 1 and _BANCADA_RE.match(g[0][2].strip()):
        bancada = g.pop(0)[2].strip()
    if g and normalizar_voto(g[-1][2]):
        voto = normalizar_voto(g.pop()[2])
    if not g:
        return None
    y, x = g[0][0], g[0][1]
    nombre = " ".join(t.strip() for _, _, t in g).strip()
    m = _VOTO_PEGADO.search(nombre)  # "AZURIN LOAYZA, ALFREDO SI +++"
    if m and not voto:
        voto, nombre = normalizar_voto(m.group(1)), nombre[:m.start()].strip()
    if "," not in nombre:
        nombre = nombre.replace(".", ",", 1)
    return (re.sub(r"\s+", " ", nombre), bancada, voto, x, y) if nombre else None


def parsear_pagina(items: list[tuple[str, list[int]]], ancho: int) -> dict | None:
    """Una pagina de votacion -> {asunto, fecha, hora, votos: [(nombre, bancada, voto)]}.
    Devuelve None si no es pagina de votacion (asistencia, caratula)."""
    # rec_texts no viene de arriba hacia abajo: ordenar antes de leer la cabecera.
    items = sorted(items, key=lambda it: (it[1][1], it[1][0]))
    cab = " ".join(t for t, _ in items[:40])
    if "VOTACI" not in cab.upper():
        return None
    fh = re.search(r"Fecha:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*Hora:\s*(\d{1,2}:\d\d\s*[ap]\.?\s*m)", cab, re.I)
    # El asunto va entre "Asunto:" y la primera fila (primera bancada a la izquierda).
    y_asunto = next((b[1] for t, b in items if t.strip().lower().startswith("asunto")), None)
    y_ini = next((b[1] for t, b in items if _BANCADA_RE.match(t.strip()) and b[0] < ancho * 0.1
                  and (y_asunto is None or b[1] > y_asunto + 10)), 0)
    fin = next((b[1] for t, b in items if t.strip().lower().startswith("resultados de")), 10**9)
    asunto = ""
    if y_asunto is not None:
        asunto = " ".join(t for t, b in items if y_asunto + 5 < b[1] < y_ini - 5).strip()

    # 3 columnas de igual ancho (medidas en la prueba: cortes en ~34% y ~64%).
    cortes = (ancho * 0.345, ancho * 0.645)
    celdas: dict[int, list] = {0: [], 1: [], 2: []}
    for t, b in items:
        if not (y_ini - 8 <= b[1] < fin - 5):
            continue
        col = 0 if b[0] < cortes[0] else 1 if b[0] < cortes[1] else 2
        celdas[col].append((b[1], b[0], t))
    votos = []
    paso = max(8, ancho // 110)  # tolerancia vertical de una fila
    for cs in celdas.values():
        cs.sort()
        grupo: list = []
        for c in cs + [(10**9, 0, "")]:
            if grupo and c[0] - grupo[0][0] > paso:
                votos.append(_fila(grupo))
                grupo = []
            grupo.append(c)
    votos = [v for v in votos if v and v[0]]
    return {"asunto": asunto,
            "fecha": f"{fh.group(3)}-{int(fh.group(2)):02d}-{int(fh.group(1)):02d}" if fh else None,
            "hora": re.sub(r"[\s.]", "", fh.group(4)).lower() if fh else None,
            "votos": votos}


ESQUEMA = """
CREATE TABLE IF NOT EXISTS votacion (
  id INTEGER PRIMARY KEY, sesion_url TEXT, pagina INT, fecha TEXT, hora TEXT,
  asunto TEXT, n_votos INT, UNIQUE(sesion_url, pagina));
CREATE TABLE IF NOT EXISTS voto (
  votacion_id INT, congresista TEXT, bancada TEXT, voto TEXT);
CREATE TABLE IF NOT EXISTS sesion_procesada (url TEXT PRIMARY KEY, paginas INT, votaciones INT);
"""


def procesar_sesion(con: sqlite3.Connection, ocr, rec, s: dict) -> int:
    import pymupdf
    if con.execute("SELECT 1 FROM sesion_procesada WHERE url=?", (s["url"],)).fetchone():
        return 0
    pdf = pymupdf.open(stream=requests.get(s["url"], headers=UA, timeout=300).content, filetype="pdf")
    n = 0
    for i, page in enumerate(pdf):
        try:
            items, ancho, img = ocr_pagina(ocr, page)
            p = parsear_pagina(items, ancho)
            if not p or len(p["votos"]) < 50:  # asistencia o pagina rota
                continue
            completar_votos(p, img, rec)
        except Exception as e:  # una pagina rota no tira la sesion entera
            print(f"[votaciones] {s['fecha']} pagina {i}: {e}", flush=True)
            continue
        cur = con.execute(
            "INSERT OR REPLACE INTO votacion (sesion_url,pagina,fecha,hora,asunto,n_votos) VALUES (?,?,?,?,?,?)",
            (s["url"], i, p["fecha"] or s["fecha"], p["hora"], p["asunto"], len(p["votos"])))
        con.executemany("INSERT INTO voto VALUES (?,?,?,?)",
                        [(cur.lastrowid, *v[:3]) for v in p["votos"]])
        n += 1
    con.execute("INSERT OR REPLACE INTO sesion_procesada VALUES (?,?,?)", (s["url"], pdf.page_count, n))
    con.commit()
    print(f"[votaciones] {s['fecha']}: {pdf.page_count} paginas, {n} votaciones", flush=True)
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("indice")
    p = sub.add_parser("procesar")
    p.add_argument("--desde", default="2024-03-08")
    p.add_argument("--hasta", default="2026-07-26")
    p.add_argument("--parte", type=int, default=0)
    p.add_argument("--partes", type=int, default=1)
    p.add_argument("--db", default="votaciones_pe.db")
    j = sub.add_parser("juntar")
    j.add_argument("--salida", default="votaciones_pe.db")
    j.add_argument("partes", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "juntar":
        con = sqlite3.connect(a.salida)
        con.executescript(ESQUEMA)
        for parte in a.partes:
            con.execute("ATTACH ? AS p", (parte,))
            # ids nuevos para no chocar entre partes
            base = con.execute("SELECT COALESCE(MAX(id), 0) FROM votacion").fetchone()[0]
            con.execute("INSERT OR IGNORE INTO votacion SELECT id + ?, sesion_url, pagina, fecha, hora, "
                        "asunto, n_votos FROM p.votacion", (base,))
            con.execute("INSERT INTO voto SELECT votacion_id + ?, congresista, bancada, voto FROM p.voto", (base,))
            con.execute("INSERT OR IGNORE INTO sesion_procesada SELECT * FROM p.sesion_procesada")
            con.commit()
            con.execute("DETACH p")
        print(f"[votaciones] {con.execute('SELECT COUNT(*) FROM votacion').fetchone()[0]} votaciones juntadas")
        return 0
    sesiones = [s for s in listar_sesiones() if "vot" in s["titulo"].lower()]
    if a.cmd == "indice":
        w = csv.writer(sys.stdout)
        w.writerow(["fecha", "titulo", "url"])
        w.writerows([s["fecha"], s["titulo"], s["url"]] for s in sesiones)
        return 0
    sel = sorted((s for s in sesiones if a.desde <= s["fecha"] <= a.hasta),
                 key=lambda s: s["fecha"])[a.parte::a.partes]
    print(f"[votaciones] parte {a.parte}/{a.partes}: {len(sel)} sesiones", flush=True)
    con = sqlite3.connect(a.db)
    con.executescript(ESQUEMA)
    ocr, rec = _ocr(), _rec()
    for s in sel:
        try:
            procesar_sesion(con, ocr, rec, s)
        except Exception as e:  # una sesion rota no frena el resto
            print(f"[votaciones] fallo {s['fecha']} {s['url']}: {e}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
