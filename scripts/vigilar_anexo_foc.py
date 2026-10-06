"""Avisa por Telegram cuando aparezca el Anexo 1 de la Resolucion
AGR-AGROCALIDAD/DE-2026-0085-R (delimitacion de sitio infectado, zona de
amortiguamiento y zona de observacion por Foc R4T).

El Registro Oficial 381 (01/10/2026) publico la resolucion pero no el
anexo; el Art. 9 dice que se difundira "por los medios oficiales de la
Agencia". Miramos: archivos subidos a agrocalidad.gob.ec, posts de
Agrocalidad, ediciones nuevas del Registro Oficial en la DB y Google News.

Uso: python scripts/vigilar_anexo_foc.py [--db proyectos.db]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from congreso_live.notify import enviar_whatsapp  # noqa: E402

# ponytail: vigilancia con fecha de corte fija; si el anexo no sale para
# entonces, extender la fecha o pedirlo a Agrocalidad por escrito.
HASTA = date(2026, 12, 31)
CLAVE = "vigilar_anexo_foc_vistos"
WP = "https://www.agrocalidad.gob.ec/wp-json/wp/v2"
UA = {"User-Agent": "Mozilla/5.0"}
# Lo que distingue al anexo de una nota cualquiera sobre Fusarium.
SENAL = re.compile(r"(?i)amortiguamiento|zona de observaci|anexo|delimitaci|"
                   r"0085|predios|cantones|parroquias")
FOC = re.compile(r"(?i)r4t|fusarium")


def _get_json(url: str, **params):
    try:
        r = requests.get(url, params=params, headers=UA, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # una fuente caida no debe tumbar las demas
        print(f"[foc] fallo {url}: {e}")
        return []


def candidatos_agrocalidad() -> list[tuple[str, str]]:
    out = []
    # El anexo firmado se llama "...amortiguamiento_y_zona_de_observacion_por_foc_r4t...pdf"
    # "anexo"/"0085" por si lo suben con un nombre generico; solo PDFs para
    # no avisar por cada foto de capacitacion.
    for q in ("amortiguamiento", "r4t", "foc", "anexo", "0085"):
        for m in _get_json(f"{WP}/media", search=q, after="2026-09-17T00:00:00", per_page=20):
            if q in ("anexo", "0085") and not (m.get("source_url") or "").lower().endswith(".pdf"):
                continue
            out.append((m.get("source_url") or m.get("link"),
                        f"Archivo en agrocalidad.gob.ec: {html.unescape(m['title']['rendered'])}"))
    for q in ("R4T", "Fusarium", "cuarentena"):
        for p in _get_json(f"{WP}/posts", search=q, after="2026-10-01T00:00:00", per_page=20):
            texto = p["title"]["rendered"] + " " + p.get("content", {}).get("rendered", "")
            if FOC.search(texto) and SENAL.search(texto):
                out.append((p["link"], f"Agrocalidad: {html.unescape(p['title']['rendered'])}"))
    return out


def candidatos_registro_oficial(db: str) -> list[tuple[str, str]]:
    if not Path(db).exists():
        return []
    c = sqlite3.connect(db)
    # El resumen en la DB se corta en 1500 caracteres y el sumario de una
    # edicion es mas largo, asi que se lee la pagina completa de cada
    # edicion de los ultimos 3 dias (son ~5 por dia).
    filas = c.execute(
        "SELECT DISTINCT n.url, n.titulo FROM noticias n "
        "JOIN noticias_fuentes f ON f.id = n.fuente_id "
        "WHERE f.nombre LIKE 'Registro Oficial%' AND n.fecha_pub > '2026-10-02' "
        "AND n.fecha_pub > datetime('now', '-3 days') "
        "AND n.url LIKE '%registroficial.gob.ec%'").fetchall()
    out = []
    for u, t in filas:
        try:
            pagina = requests.get(u, headers=UA, timeout=30).text
        except Exception as e:
            print(f"[foc] fallo {u}: {e}")
            continue
        texto = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", pagina)))
        if FOC.search(texto) or "Foc R4T" in texto:
            out.append((u, f"Registro Oficial: {t} menciona Foc R4T"))
    return out


def candidatos_google_news() -> list[tuple[str, str]]:
    out = []
    for q in ('"R4T" anexo', '"R4T" amortiguamiento', 'Fusarium cuarentena Agrocalidad zonas'):
        try:
            x = requests.get("https://news.google.com/rss/search", headers=UA, timeout=30,
                             params={"q": f"{q} when:3d", "hl": "es-419", "gl": "EC",
                                     "ceid": "EC:es-419"}).text
        except Exception as e:
            print(f"[foc] fallo Google News: {e}")
            continue
        for it in re.findall(r"<item>(.*?)</item>", x, re.S):
            t = html.unescape(re.search(r"<title>(.*?)</title>", it).group(1))
            if FOC.search(t) and SENAL.search(t):
                out.append((re.search(r"<link>(.*?)</link>", it).group(1), f"Prensa: {t}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="proyectos.db")
    a = ap.parse_args()
    if date.today() > HASTA:
        print("[foc] vigilancia vencida, nada que hacer")
        return 0

    c = sqlite3.connect(a.db)
    c.execute("CREATE TABLE IF NOT EXISTS app_state (k TEXT PRIMARY KEY, v TEXT)")
    fila = c.execute("SELECT v FROM app_state WHERE k=?", (CLAVE,)).fetchone()
    vistos = set(json.loads(fila[0])) if fila else set()

    nuevos = {}
    for url, desc in (candidatos_agrocalidad() + candidatos_registro_oficial(a.db)
                      + candidatos_google_news()):
        if url and url not in vistos:
            nuevos[url] = desc
    print(f"[foc] {len(nuevos)} candidato(s) nuevo(s)")
    if not nuevos:
        return 0

    lineas = [f"• {d}\n{u}" for u, d in list(nuevos.items())[:8]]
    msg = ("🌱 Ecuador: posible publicación del Anexo 1 de la Resolución "
           "AGR-AGROCALIDAD/DE-2026-0085-R (zonas de cuarentena por Foc R4T)\n\n"
           + "\n\n".join(lineas))
    # Solo se marca como visto si el aviso salio; si falla, se reintenta.
    if enviar_whatsapp(msg):
        vistos.update(nuevos)
        c.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)",
                  (CLAVE, json.dumps(sorted(vistos))))
        c.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
