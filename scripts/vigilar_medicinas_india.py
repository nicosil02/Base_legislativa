"""Avisa por Telegram cuando haya noticias de la firma o llegada de la
compra de medicinas de Ecuador a India (Estado a Estado, distribucion a
cargo de la empresa publica AIL EP). Al 12/10/2026 el Gobierno decia
que estaba "en fase final" desde septiembre, sin firma confirmada.

Miramos noticias de los ultimos 3 dias en la DB y Google News.

Uso: python scripts/vigilar_medicinas_india.py [--db proyectos.db]
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

# ponytail: fecha de corte fija; extender si la compra sigue sin cerrarse.
HASTA = date(2026, 12, 31)
CLAVE = "vigilar_medicinas_india_vistos"
UA = {"User-Agent": "Mozilla/5.0"}
TEMA = re.compile(r"(?i)\bindia\b.*(medicin|medicament|f[aá]rmaco)|"
                  r"(medicin|medicament|f[aá]rmaco).*\bindia\b|\bAIL\b")
# Lo que separa la firma/llegada de una nota cualquiera sobre el tema.
SENAL = re.compile(r"(?i)firm|suscri|contrat|convenio|acuerdo|concret[oó]|lleg|arrib|lote|"
                   r"desembarc|entreg|\bAIL\b")


def es_aviso(texto: str) -> bool:
    return bool(TEMA.search(texto) and SENAL.search(texto))


def candidatos_db(db: str) -> list[tuple[str, str]]:
    if not Path(db).exists():
        return []
    c = sqlite3.connect(db)
    filas = c.execute(
        "SELECT n.url, n.titulo, COALESCE(n.resumen,'') FROM noticias n "
        "JOIN noticias_fuentes f ON f.id = n.fuente_id WHERE f.pais = 'EC' "
        "AND COALESCE(n.fecha_pub, n.first_seen_at) > datetime('now', '-3 days')"
    ).fetchall()
    return [(u, f"Prensa: {t}") for u, t, r in filas
            if es_aviso(f"{t} {re.sub('<[^>]+>', ' ', r)}")]


def candidatos_google_news() -> list[tuple[str, str]]:
    out = []
    for q in ("medicinas India Ecuador", "medicamentos India Ecuador", '"AIL EP"'):
        try:
            x = requests.get("https://news.google.com/rss/search", headers=UA, timeout=30,
                             params={"q": f"{q} when:3d", "hl": "es-419", "gl": "EC",
                                     "ceid": "EC:es-419"}).text
        except Exception as e:
            print(f"[india] fallo Google News: {e}")
            continue
        for it in re.findall(r"<item>(.*?)</item>", x, re.S):
            t = html.unescape(re.search(r"<title>(.*?)</title>", it).group(1))
            if es_aviso(t):
                out.append((re.search(r"<link>(.*?)</link>", it).group(1), f"Prensa: {t}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="proyectos.db")
    a = ap.parse_args()
    if date.today() > HASTA:
        print("[india] vigilancia vencida, nada que hacer")
        return 0

    c = sqlite3.connect(a.db)
    c.execute("CREATE TABLE IF NOT EXISTS app_state (k TEXT PRIMARY KEY, v TEXT)")
    fila = c.execute("SELECT v FROM app_state WHERE k=?", (CLAVE,)).fetchone()
    vistos = set(json.loads(fila[0])) if fila else set()

    nuevos = {}
    for url, desc in candidatos_db(a.db) + candidatos_google_news():
        if url and url not in vistos:
            nuevos[url] = desc
    print(f"[india] {len(nuevos)} candidato(s) nuevo(s)")
    if not nuevos:
        return 0

    lineas = [f"• {d}\n{u}" for u, d in list(nuevos.items())[:8]]
    msg = ("💊 Ecuador: novedades sobre la compra de medicinas a India "
           "(Estado a Estado, distribución por AIL EP)\n\n" + "\n\n".join(lineas))
    # Solo se marca como visto si el aviso salio; si falla, se reintenta.
    if enviar_whatsapp(msg):
        vistos.update(nuevos)
        c.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)",
                  (CLAVE, json.dumps(sorted(vistos))))
        c.commit()
    return 0


def _test():
    assert es_aviso("Ecuador firmó el acuerdo para comprar medicinas a India")
    assert es_aviso("Llega el primer lote de medicamentos de la India")
    assert es_aviso("Ecuador anuncia acuerdo histórico con India para la adquisición de medicinas")
    assert es_aviso("AIL EP inicia distribución de fármacos")
    assert not es_aviso("Ecuador compra medicinas y vehículos a India, que demanda teca")
    assert not es_aviso("Uruguay goleó 6-1 a India en su gira asiática")
    print("OK vigilar_medicinas_india")


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        _test()
        sys.exit(0)
    sys.exit(main())
