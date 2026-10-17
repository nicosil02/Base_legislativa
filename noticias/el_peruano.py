"""Scraper de El Peruano — Normas Legales por fecha.

busquedas.elperuano.pe es una SPA Remix que sirve los datos server-side
renderizados en el HTML inicial. Cada norma es un card con:
    <p class="text-sm font-semibold text-primary">{SECTOR}</p>
    <a href="/dispositivo/NL/{id}">
      <p>{TIPO}</p>              <- ej: RESOLUCIÓN SUPREMA
      <p>{NÚMERO}</p>            <- ej: N° 152-2026-JUS
    </a>
    <a href="/dispositivo/NL/{id}">{TÍTULO}</a>

Este scraper:
  1) Consulta busquedas.elperuano.pe?tipoPublicacion=NL&fechaIni=X&fechaFin=X
  2) Parsea todas las normas del rango de fechas (iterando páginas).
  3) Cada norma se clasifica con noticias/temas.py.
  4) Si matchea algún sector, se persiste como noticia.

Uso:
    python -m noticias.el_peruano sync                # normas de hoy
    python -m noticias.el_peruano sync --dias 7       # ultimos 7 dias
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from core.tiempo import ahora_lima
from noticias.scraper import HEADERS, _make_session, _unescape
from noticias.temas import clasificar

log = logging.getLogger(__name__)

BASE_URL = "https://busquedas.elperuano.pe"
FUENTE_NOMBRE = "El Peruano — Normas Legales"


# Regex del bloque card: sector + tipo + numero + titulo.
# El HTML entre <p>sector</p> y </a></div> puede tener otro contenido, pero
# extraemos el trio (tipo, numero, titulo) que siempre viene junto en el <a>.
_RE_CARD = re.compile(
    r'<p[^>]*class="[^"]*font-semibold[^"]*text-primary[^"]*"[^>]*>'
    r'([^<]+?)</p>.*?'                       # 1: sector
    r'<a[^>]+href="(/dispositivo/NL/\d+-\d+)"[^>]*>.*?'  # 2: url relativa
    r'<p[^>]*>([^<]+?)</p>\s*'               # 3: tipo (RESOLUCIÓN SUPREMA, etc.)
    r'<p[^>]*>([^<]+?)</p>.*?'               # 4: numero
    r'</a>\s*</div>\s*<div[^>]*>\s*'
    r'<a[^>]+href="\2"[^>]*>([^<]+?)</a>',   # 5: título
    re.DOTALL | re.IGNORECASE,
)

_RE_TOTAL = re.compile(r'(\d+)\s*<!--[^>]*-->\s*<!--[^>]*-->\s*dispositivos', re.I)


def parse_page(html: str) -> tuple[list[dict], int]:
    """Devuelve (items, total_dispositivos). items sin dedup."""
    total = 0
    m = _RE_TOTAL.search(html)
    if m:
        total = int(m.group(1))
    items = []
    for m in _RE_CARD.finditer(html):
        sector, url_rel, tipo, numero, titulo = (_unescape(x) for x in m.groups())
        items.append({
            "sector": sector,
            "url": BASE_URL + url_rel,
            "id_dispositivo": url_rel.rsplit("/", 1)[-1],  # ej: 2539838-9
            "tipo": tipo,
            "numero": numero,
            "titulo": titulo,
        })
    return items, total


def fetch_range(session, fecha_ini: str, fecha_fin: str, max_pages: int = 20) -> list[dict]:
    """Consulta el rango [fecha_ini, fecha_fin] (YYYYMMDD) paginando.

    Cada página trae ~20 items. max_pages=20 → hasta 400 items."""
    all_items: list[dict] = []
    seen_ids: set[str] = set()
    for page in range(max_pages):
        start = page * 20
        url = (f"{BASE_URL}/?tipoPublicacion=NL"
               f"&fechaIni={fecha_ini}&fechaFin={fecha_fin}"
               f"&ci=ONLY&start={start}")
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
        except Exception as e:
            log.warning("El Peruano fetch fail page=%d: %s", page, e)
            break
        items, total = parse_page(r.text)
        if not items:
            break
        new_this_page = 0
        for it in items:
            if it["id_dispositivo"] in seen_ids:
                continue
            seen_ids.add(it["id_dispositivo"])
            all_items.append(it)
            new_this_page += 1
        log.info("El Peruano page=%d items=%d nuevos=%d total_reportado=%d",
                 page, len(items), new_this_page, total)
        # Si esta página no aportó nuevos (ya vistos), no vale la pena seguir.
        if new_this_page == 0:
            break
        # Si ya juntamos todo lo que reporta el sitio, parar.
        if len(all_items) >= total:
            break
    return all_items


def build_noticia(item: dict, fecha_iso: str, temas: list[str]) -> dict:
    """Convierte una norma en dict listo para upsert_noticia."""
    titulo = f"{item['sector']} — {item['tipo']} {item['numero']}: {item['titulo']}"
    return {
        "url": item["url"],
        "titulo": titulo[:500],
        "resumen": item["titulo"][:500],
        "fecha_pub": fecha_iso,
        "autor": item["sector"],
        "tags": "|".join(temas + ["el-peruano", "normativa"]),
    }


def _fecha_a_iso(fecha_yyyymmdd: str) -> str:
    """Convierte YYYYMMDD a ISO UTC (para fecha_pub)."""
    return f"{fecha_yyyymmdd[:4]}-{fecha_yyyymmdd[4:6]}-{fecha_yyyymmdd[6:8]}T00:00:00Z"


def run_sync(db, dias: int = 1) -> dict:
    """Sync de las últimas N días de normas legales."""
    stats = {"items_totales": 0, "matches": 0, "nuevas": 0, "actualizadas": 0, "errores": 0}
    session = _make_session()
    session.headers.update(HEADERS)

    fuente_id = db.upsert_fuente({
        "categoria": "Institucion", "pais": "PE",
        "nombre": FUENTE_NOMBRE,
        "url": "https://busquedas.elperuano.pe/",
        "rss_url": None, "tipo": "custom", "activa": 1,
        "notas": "Normas Legales del día vía scraping busquedas.elperuano.pe",
        # Sin clientes, alerts/relevancia.py descarta estas normas antes de
        # que Gemini las juzgue: "todos" deja decidir al ranking.
        "clientes": ["todos"],
    })

    # Un dia por consulta y fecha de Lima: con un rango, una norma de ayer
    # quedaba con fecha de hoy (upsert_noticia reescribe fecha_pub).
    hoy = ahora_lima().date()
    pares = []
    for i in range(dias - 1, -1, -1):
        dia = (hoy - timedelta(days=i)).strftime("%Y%m%d")
        try:
            pares += [(it, _fecha_a_iso(dia)) for it in fetch_range(session, dia, dia)]
        except Exception as e:
            log.warning("El Peruano fetch_range error (%s): %s", dia, e)
            stats["errores"] += 1
    log.info("El Peruano: %d dia(s) hasta %s", dias, hoy)

    stats["items_totales"] = len(pares)
    for it, fecha_iso in pares:
        # Se guardan TODAS las normas (como el resto de fuentes); el tema
        # solo va como tag para la UI.
        signal = f"{it['sector']} {it['tipo']} {it['titulo']}"
        temas = clasificar(signal, None)
        stats["matches"] += 1
        try:
            is_new, changed = db.upsert_noticia(fuente_id, build_noticia(it, fecha_iso, temas))
            if is_new:
                stats["nuevas"] += 1
            elif changed:
                stats["actualizadas"] += 1
        except Exception as e:
            log.warning("El Peruano upsert fail: %s", e)
            stats["errores"] += 1

    log.info("El Peruano sync: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--dias", type=int, default=1,
                    help="dias hacia atrás para sync (default 1 = solo hoy)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from noticias.db import Database
    with Database(args.db) as db:
        db.init_schema()
        stats = run_sync(db, dias=args.dias)
        print(f"El Peruano sync: {stats}")
