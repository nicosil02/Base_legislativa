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

import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone

from noticias.scraper import HEADERS, _make_session
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


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(s or "")).strip()


def parse_page(html: str) -> tuple[list[dict], int]:
    """Devuelve (items, total_dispositivos). items sin dedup."""
    total = 0
    m = _RE_TOTAL.search(html)
    if m:
        total = int(m.group(1))
    items = []
    for m in _RE_CARD.finditer(html):
        sector, url_rel, tipo, numero, titulo = (_clean(x) for x in m.groups())
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
    })

    hoy = datetime.now(timezone.utc)
    ini = (hoy - timedelta(days=dias - 1)).strftime("%Y%m%d")
    fin = hoy.strftime("%Y%m%d")
    log.info("El Peruano: rango %s → %s (%d dia(s))", ini, fin, dias)

    try:
        items = fetch_range(session, ini, fin)
    except Exception as e:
        log.warning("El Peruano fetch_range error: %s", e)
        stats["errores"] += 1
        return stats

    stats["items_totales"] = len(items)
    fecha_iso = _fecha_a_iso(fin)  # Usamos la fecha_fin como pub_date aproximada
    for it in items:
        signal = f"{it['sector']} {it['tipo']} {it['titulo']}"
        temas = clasificar(signal, None)
        if not temas:
            continue
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


def _demo():
    """Self-check parseo con una página real (test lento — hace 1 request)."""
    session = _make_session(); session.headers.update(HEADERS)
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    r = session.get(f"{BASE_URL}/?tipoPublicacion=NL&fechaIni={hoy}&fechaFin={hoy}", timeout=25)
    items, total = parse_page(r.text)
    assert len(items) > 0, "esperaba >=1 item, hay 0"
    it = items[0]
    for k in ("sector", "url", "tipo", "numero", "titulo"):
        assert it.get(k), f"item sin {k!r}: {it}"
    assert it["url"].startswith("https://busquedas.elperuano.pe/dispositivo/NL/")
    print(f"OK parse_page: {len(items)} items, total reportado={total}")
    print(f"  primer item: {it['sector']} / {it['tipo']} / {it['numero']} / {it['titulo'][:60]}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync", "demo"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--dias", type=int, default=1,
                    help="dias hacia atrás para sync (default 1 = solo hoy)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "demo":
        _demo()
    else:
        from noticias.db import Database
        with Database(args.db) as db:
            db.init_schema()
            stats = run_sync(db, dias=args.dias)
            print(f"El Peruano sync: {stats}")
